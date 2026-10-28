/**
 * Zakładka „Drukarki” (agent druku v2) — modules/production/templates/components/printers-tab-content.html.
 *
 * Plik ładuje panel/dashboard.html; treść zakładki przychodzi AJAX-em (loadPrintersTab w production-app-loader.js),
 * a skrypt na końcu szablonu woła DrukarkiTab.init(korzeń). Ponowne wczytanie zakładki (forceRefresh) woła init
 * jeszcze raz — stary timer jest wtedy zatrzymywany, a zdarzenia wiszą na nowym korzeniu.
 *
 * API: /production/api/drukarki (modules/production/drukarki/routers/panel_api.py). Przegląd (stan, zadania, Ponów,
 * Anuluj, wydruk próbny) dla każdego z dostępem do panelu produkcji; reszta tylko admin — także po stronie serwera.
 * Stan odświeżany co 15 s, tylko gdy zakładka jest widoczna. Token agenta pokazujemy w oknie raz i nie trzymamy go
 * w żadnej zmiennej po zamknięciu okna.
 */
(function () {
    'use strict';

    const ODSWIEZANIE_MS = 15000;
    const ADRES_USTAWIEN = '/production/api/update-configs';

    const NAZWY_DRUKAREK = { etykiety: 'Etykiety 60×40', wysylka: 'Paczki 100×150' };
    const NAZWY_DRUKAREK_DLUGIE = { etykiety: 'drukarka etykiet', wysylka: 'drukarka paczek' };
    const NAZWY_STANOWISK = {
        cutting: 'Wycinanie', assembly: 'Składanie', gluing: 'Sklejanie', formatting: 'Formatowanie',
        edges: 'Krawędzie', painting: 'Lakiernia', packaging: 'Pakowanie', verification: 'Weryfikacja',
        manager: 'Kierownik hali'
    };
    // Stan drukarki (docs/api-mobile-drukarki.md 2.2): żółty = wymaga uwagi, czerwony = nie drukuje.
    const STANY_DRUKARKI = {
        gotowa: ['gotowa', 'ok'],
        brak_papieru: ['brak etykiet', 'warn'],
        otwarta_klapa: ['otwarta klapa', 'warn'],
        pauza: ['wstrzymana', 'warn'],
        offline: ['nie odpowiada', 'danger'],
        blad: ['błąd', 'danger'],
        nieznany: ['stan nieznany', 'danger']
    };
    const STANY_ZADANIA = {
        pending: ['czeka', 'warn'],
        claimed: ['pobrane przez agenta', 'info'],
        sending: ['w wysyłce', 'info'],
        printed: ['wydrukowane', 'ok'],
        failed: ['błąd', 'danger'],
        unknown: ['wysłane, bez potwierdzenia', 'szara'],
        expired: ['wygasłe', 'szara'],
        cancelled: ['anulowane', 'szara']
    };
    const PONAWIALNE = ['failed', 'expired', 'unknown', 'printed'];
    const BLEDY = {
        brak_aktywnego_agenta: 'Żaden nowy agent druku jeszcze się nie zgłosił. Sparuj agenta w „Agenci i wydania” i uruchom go na komputerze hali.',
        zadania_nie_mozna_ponowic: 'Tego zadania nie można ponowić: wciąż czeka w kolejce albo zostało anulowane.',
        zadania_nie_mozna_anulowac: 'Anulować można tylko zadanie, które czeka w kolejce. To zadanie agent już pobrał.',
        brak_zadania: 'Nie ma takiego zadania. Odśwież listę.',
        nieznana_drukarka: 'Nieznana drukarka.',
        brak_agenta: 'Nie ma takiego agenta. Odśwież listę.',
        brak_konfiguracji: 'Aktywny agent nie ma jeszcze konfiguracji.',
        brak_wydania: 'Nie ma takiego wydania. Odśwież listę.',
        bledne_pole_aktywne: 'Nieprawidłowa wartość przełącznika.',
        blad_serwera: 'Błąd serwera. Spróbuj ponownie za chwilę.'
    };

    let biezacy = null;   // stan bieżącej instancji zakładki (po ponownym wczytaniu zastępowany)

    // ── pomocnicze ──────────────────────────────────────────────────────────────────────────────────────────────

    function esc(s) {
        return String(s ?? '').replace(/[&<>"']/g,
            c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function toast(tekst, typ) {
        const app = window.ProductionApp;
        if (app?.shared?.toastSystem) app.shared.toastSystem.show(tekst, typ || 'info');
        else alert(tekst);
    }

    function godzina(iso, zSekundami) {
        if (!iso) return '—';
        const d = new Date(iso);
        const opcje = { hour: '2-digit', minute: '2-digit' };
        if (zSekundami) opcje.second = '2-digit';
        const dzis = new Date();
        const czas = d.toLocaleTimeString('pl-PL', opcje);
        return d.toDateString() === dzis.toDateString()
            ? czas : d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit' }) + ' ' + czas;
    }

    function temu(iso) {
        if (!iso) return 'nigdy';
        const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
        if (s < 60) return s + ' s temu';
        if (s < 3600) return Math.floor(s / 60) + ' min temu';
        if (s < 86400) return Math.floor(s / 3600) + ' godz. temu';
        return godzina(iso);
    }

    function pigulka(tekst, rodzaj) {
        return `<span class="drk-pigulka drk-pigulka--${rodzaj}">${esc(tekst)}</span>`;
    }

    /** Błąd odpowiedzi z kodem API (`kod`) i polskim tekstem (`message`). */
    class BladApi extends Error {
        constructor(tekst, kod, status, dane) {
            super(tekst);
            this.kod = kod;
            this.status = status;
            this.dane = dane;
        }
    }

    async function zapytaj(metoda, adres, cialo, formularz) {
        const opcje = { method: metoda, headers: { 'X-Requested-With': 'XMLHttpRequest' } };
        if (formularz) {
            opcje.body = formularz;
        } else if (cialo !== undefined) {
            opcje.headers['Content-Type'] = 'application/json';
            opcje.body = JSON.stringify(cialo);
        }
        let r;
        try {
            r = await fetch(adres, opcje);
        } catch (e) {
            throw new BladApi('Brak połączenia z serwerem.', 'siec', 0, null);
        }
        let dane = null;
        try { dane = await r.json(); } catch (e) { /* pusta albo nie-JSON odpowiedź */ }
        if (r.status === 401) {
            zatrzymajTimer();
            throw new BladApi('Sesja wygasła — zaloguj się ponownie.', 'sesja', 401, dane);
        }
        if (r.status === 403) throw new BladApi('Brak uprawnień administratora.', 'uprawnienia', 403, dane);
        if (!r.ok || !dane || dane.success === false) {
            const kod = dane && dane.error;
            // Kod maszynowy (bez spacji) tłumaczymy; zdanie z serwera (update-configs) pokazujemy wprost.
            const tekst = (kod && BLEDY[kod]) || (dane && dane.komunikat)
                || (kod && /\s/.test(kod) ? kod : '') || `Nie udało się wykonać operacji (HTTP ${r.status}).`;
            throw new BladApi(tekst, kod, r.status, dane);
        }
        return dane;
    }

    function zatrzymajTimer() {
        if (window.__drukarkiTimer) {
            clearInterval(window.__drukarkiTimer);
            window.__drukarkiTimer = null;
        }
    }

    function zakladkaWidoczna() {
        const panel = document.getElementById('printers-tab-content');
        return !document.hidden && !!panel && panel.classList.contains('active');
    }

    // ── instancja zakładki ──────────────────────────────────────────────────────────────────────────────────────

    function init(root) {
        if (!root) return;
        zatrzymajTimer();
        zapnijSluchaczZakladki();
        const api = root.dataset.apiBase || '/production/api/drukarki';
        const admin = root.dataset.isAdmin === 'true';
        const $ = (id) => document.getElementById(id);
        const stan = {
            migawka: null,
            strona: 1,
            konfiguracja: null,
            zaladowane: {}           // podzakładki admina już wczytane
        };
        biezacy = stan;

        // ── podzakładki (tylko admin) ──
        const przyciski = [...root.querySelectorAll('.drk-subnav-btn')];
        function wybierzPodzakladke(sub, fokus) {
            przyciski.forEach(b => {
                const aktywny = b.dataset.sub === sub;
                b.classList.toggle('active', aktywny);
                b.setAttribute('aria-selected', aktywny ? 'true' : 'false');
                b.tabIndex = aktywny ? 0 : -1;
                const panel = $(b.getAttribute('aria-controls'));
                if (panel) panel.hidden = !aktywny;
                if (aktywny && fokus) b.focus();
            });
            if (sub === 'konfiguracja' && !stan.zaladowane.konfiguracja) wczytajKonfiguracje();
            if (sub === 'agenci' && !stan.zaladowane.agenci) wczytajAgentow();
            if (sub === 'agenci' && !stan.zaladowane.wydania) wczytajWydania();
        }
        przyciski.forEach((b, i) => {
            b.addEventListener('click', () => wybierzPodzakladke(b.dataset.sub, false));
            b.addEventListener('keydown', (ev) => {
                let cel = null;
                if (ev.key === 'ArrowRight') cel = (i + 1) % przyciski.length;
                else if (ev.key === 'ArrowLeft') cel = (i - 1 + przyciski.length) % przyciski.length;
                else if (ev.key === 'Home') cel = 0;
                else if (ev.key === 'End') cel = przyciski.length - 1;
                if (cel === null) return;
                ev.preventDefault();
                wybierzPodzakladke(przyciski[cel].dataset.sub, true);
            });
        });

        // ════════════════ PRZEGLĄD: karty stanu ════════════════

        function rysujAgenta(agent) {
            const karta = $('drk-stan-agent');
            const tresc = karta.querySelector('[data-drk-tresc]');
            karta.classList.remove('drk-stan--alarm', 'drk-stan--uwaga');
            if (!agent) {
                tresc.innerHTML = `<div class="drk-stan-glowny">${pigulka('niesparowany', 'szara')}</div>
                    <span class="drk-drobne">Nowy agent druku jeszcze się nie zgłosił.${admin ? ' Sparuj go w „Agenci i wydania”.' : ''}</span>`;
                return;
            }
            const szczegoly = `wersja ${esc(agent.wersja || '?')} · push: ${agent.push ? 'połączony' : 'brak'}`;
            if (agent.online) {
                tresc.innerHTML = `<div class="drk-stan-glowny">${pigulka('online', 'ok')}
                        <span>ostatni sygnał ${esc(temu(agent.ostatni_kontakt))}</span></div>
                    <span class="drk-drobne">${szczegoly}</span>`;
            } else {
                karta.classList.add('drk-stan--alarm');
                tresc.innerHTML = `<div class="drk-stan-glowny">${pigulka('brak kontaktu', 'danger')}
                        <span class="drk-stan-komunikat">brak kontaktu od ${esc(godzina(agent.ostatni_kontakt))}</span></div>
                    <span class="drk-drobne">${szczegoly}</span>`;
            }
        }

        function rysujDrukarke(d) {
            const karta = $('drk-stan-' + d.nazwa);
            if (!karta) return;
            const tresc = karta.querySelector('[data-drk-tresc]');
            karta.classList.remove('drk-stan--alarm', 'drk-stan--uwaga');
            const liczby = `<div class="drk-stan-liczby"><span>w kolejce: <strong>${d.w_kolejce}</strong></span>
                <span>dziś: <strong>${d.dzis}</strong></span></div>`;
            const [tekst, rodzaj] = STANY_DRUKARKI[d.stan] || STANY_DRUKARKI.nieznany;
            if (rodzaj === 'warn') karta.classList.add('drk-stan--uwaga');
            if (rodzaj === 'danger') karta.classList.add('drk-stan--alarm');
            const od = d.od ? ` od ${esc(godzina(d.od))}` : '';
            const komunikat = d.stan !== 'gotowa' && d.komunikat
                ? `<span class="drk-stan-komunikat">${esc(d.komunikat)}${od}</span>` : '';
            tresc.innerHTML = `<div class="drk-stan-glowny">${pigulka(tekst, rodzaj)}</div>${komunikat}${liczby}`;
        }

        async function odswiezStan() {
            try {
                const m = await zapytaj('GET', api + '/stan');
                stan.migawka = m;
                rysujAgenta(m.agent);
                m.drukarki.forEach(rysujDrukarke);
                $('drk-odswiezono').textContent = 'odświeżono ' + new Date().toLocaleTimeString('pl-PL');
            } catch (e) {
                $('drk-odswiezono').textContent = 'nie udało się odświeżyć: ' + e.message;
            }
        }

        // ════════════════ PRZEGLĄD: lista zadań ════════════════

        function skad(z) {
            if (z.stanowisko) return NAZWY_STANOWISK[z.stanowisko] || z.stanowisko;
            const [typ] = String(z.kto || '').split(':');
            return { user: 'Panel CRM', device: 'Tablet', system: 'System', agent: 'Agent druku' }[typ] || z.kto || '—';
        }

        function wierszZadania(z) {
            const [tekst, rodzaj] = STANY_ZADANIA[z.stan] || [z.stan, 'szara'];
            const blad = z.blad && (z.stan === 'failed' || z.stan === 'unknown' || z.stan === 'expired')
                ? `<span class="drk-drobne drk-blad-zadania" title="${esc(z.blad)}">${esc(z.blad)}</span>` : '';
            const akcje = [];
            if (PONAWIALNE.includes(z.stan)) {
                akcje.push(`<button type="button" class="btn btn-outline-primary btn-sm drk-btn" data-drk-akcja="ponow"
                    aria-label="Ponów zadanie ${z.id}">Ponów</button>`);
            }
            if (z.stan === 'pending') {
                akcje.push(`<button type="button" class="btn btn-outline-danger btn-sm drk-btn" data-drk-akcja="anuluj"
                    aria-label="Anuluj zadanie ${z.id}">Anuluj</button>`);
            }
            return `<tr data-id="${z.id}">
                <td class="drk-k-czas drk-k-glowna drk-mono" title="${esc(z.czas ? new Date(z.czas).toLocaleString('pl-PL') : '')}">${esc(godzina(z.czas, true))}</td>
                <td class="drk-k-drukarka" data-label="Drukarka"><span class="drk-ell">${esc(NAZWY_DRUKAREK[z.drukarka] || z.drukarka)}</span></td>
                <td class="drk-k-co" data-label="Co"><span class="drk-ell drk-mono" title="${esc(z.kod)}">${esc(z.kod)}</span></td>
                <td class="drk-k-skad" data-label="Skąd"><span class="drk-ell" title="${esc(z.kto)}">${esc(skad(z))}</span></td>
                <td class="drk-k-stan" data-label="Stan"><div>${pigulka(tekst, rodzaj)}${blad}</div></td>
                <td class="drk-k-akcje">${akcje.join('')}</td>
            </tr>`;
        }

        async function odswiezZadania() {
            const parametry = new URLSearchParams({ strona: String(stan.strona) });
            const drukarka = $('drk-filtr-drukarka').value;
            const stanZad = $('drk-filtr-stan').value;
            if (drukarka) parametry.set('drukarka', drukarka);
            if (stanZad) parametry.set('stan', stanZad);
            try {
                const dane = await zapytaj('GET', api + '/zadania?' + parametry.toString());
                    const lista = $('drk-zadania-lista');
                lista.innerHTML = dane.zadania.length ? dane.zadania.map(wierszZadania).join('')
                    : `<tr class="drk-pusty"><td colspan="6" class="drk-pusto">${drukarka || stanZad
                        ? 'Brak zadań dla wybranych filtrów.' : 'Kolejka druku jest pusta. Zadania pojawią się po wydruku etykiety na stanowisku.'}</td></tr>`;
                const od = dane.razem ? (dane.strona - 1) * dane.na_strone + 1 : 0;
                const do_ = Math.min(dane.razem, dane.strona * dane.na_strone);
                $('drk-zadania-licznik').textContent = dane.razem ? `Zadania ${od}–${do_} z ${dane.razem}` : '';
                $('drk-strona-nowsze').disabled = dane.strona <= 1;
                $('drk-strona-starsze').disabled = do_ >= dane.razem;
            } catch (e) {
                $('drk-zadania-lista').innerHTML = `<tr class="drk-pusty"><td colspan="6" class="drk-pusto">Nie udało się wczytać zadań: ${esc(e.message)}</td></tr>`;
            }
        }

        function odswiezPrzeglad() {
            return Promise.all([odswiezStan(), odswiezZadania()]);
        }

        $('drk-odswiez').addEventListener('click', odswiezPrzeglad);
        $('drk-filtr-drukarka').addEventListener('change', () => { stan.strona = 1; odswiezZadania(); });
        $('drk-filtr-stan').addEventListener('change', () => { stan.strona = 1; odswiezZadania(); });
        $('drk-strona-nowsze').addEventListener('click', () => { stan.strona = Math.max(1, stan.strona - 1); odswiezZadania(); });
        $('drk-strona-starsze').addEventListener('click', () => { stan.strona += 1; odswiezZadania(); });

        // ════════════════ AKCJE (delegacja na korzeń zakładki) ════════════════

        async function akcjaPrzycisku(btn, funkcja) {
            btn.disabled = true;
            try {
                await funkcja();
            } catch (e) {
                toast(e.message, 'error');
            } finally {
                btn.disabled = false;
            }
        }

        root.addEventListener('click', (ev) => {
            const btn = ev.target.closest('[data-drk-akcja]');
            if (!btn || !root.contains(btn)) return;
            const akcja = btn.dataset.drkAkcja;
            const drukarka = btn.dataset.drukarka;
            const wiersz = btn.closest('tr[data-id]');
            const id = wiersz ? Number(wiersz.dataset.id) : null;
            switch (akcja) {
                case 'ponow':
                    return akcjaPrzycisku(btn, async () => {
                        const w = await zapytaj('POST', `${api}/zadania/${id}/ponow`);
                        toast(`Zadanie ponowione jako nr ${w.id}. Etykieta wyjdzie, gdy agent je pobierze.`, 'success');
                        await odswiezPrzeglad();
                    });
                case 'anuluj':
                    if (!confirm('Anulować to zadanie? Etykieta nie zostanie wydrukowana.')) return;
                    return akcjaPrzycisku(btn, async () => {
                        await zapytaj('POST', `${api}/zadania/${id}/anuluj`);
                        toast('Zadanie anulowane.', 'success');
                        await odswiezPrzeglad();
                    });
                case 'wydruk-probny':
                    return akcjaPrzycisku(btn, async () => {
                        await zapytaj('POST', `${api}/wydruk-probny/${drukarka}`);
                        toast(`Wydruk próbny w kolejce (${NAZWY_DRUKAREK_DLUGIE[drukarka]}). Etykieta wyjdzie, gdy agent pobierze zadanie.`, 'success');
                        await odswiezPrzeglad();
                    });
                case 'kalibracja':
                    if (!confirm(`Skalibrować: ${NAZWY_DRUKAREK_DLUGIE[drukarka]}? Drukarka przewinie kilka pustych etykiet.`)) return;
                    return akcjaPrzycisku(btn, async () => {
                        await zapytaj('POST', `${api}/kalibracja/${drukarka}`);
                        toast('Polecenie kalibracji wysłane do agenta.', 'success');
                    });
                case 'nowy-token':
                    return nowyToken(btn, id);
                case 'uniewaznij':
                    return uniewaznij(btn, id);
                default:
                    return;
            }
        });

        // ════════════════ ADMIN ════════════════
        if (!admin) {
            startTimera();
            odswiezPrzeglad();
            return;
        }

        // ── token pokazany raz ──
        const modalToken = new bootstrap.Modal($('drk-modal-token'));
        function pokazToken(token, opis) {
            $('drk-token-opis').textContent = opis;
            $('drk-token').value = token;
            modalToken.show();
        }
        $('drk-modal-token').addEventListener('hidden.bs.modal', () => {
            $('drk-token').value = '';          // po zamknięciu tokenu nie ma już nigdzie na stronie
        });
        $('drk-modal-token').addEventListener('shown.bs.modal', () => $('drk-token').select());
        $('drk-token-kopiuj').addEventListener('click', async () => {
            const pole = $('drk-token');
            try {
                await navigator.clipboard.writeText(pole.value);
            } catch (e) {
                pole.select();
                document.execCommand('copy');   // zapas dla przeglądarki bez dostępu do schowka (http)
            }
            toast('Token skopiowany do schowka.', 'success');
        });

        // ── agenci ──
        function wierszAgenta(a) {
            const stanAgenta = a.uniewazniony ? pigulka('unieważniony', 'szara')
                : a.online ? pigulka('online', 'ok')
                : a.ostatni_kontakt ? pigulka('brak kontaktu', 'danger') : pigulka('nie zgłosił się', 'szara');
            const akcje = a.uniewazniony ? '' : `
                <button type="button" class="btn btn-outline-secondary btn-sm drk-btn" data-drk-akcja="nowy-token">Nowy token</button>
                <button type="button" class="btn btn-outline-danger btn-sm drk-btn" data-drk-akcja="uniewaznij">Unieważnij</button>`;
            return `<tr data-id="${a.id}">
                <td class="drk-k-nazwa drk-k-glowna"><span class="drk-ell" title="${esc(a.nazwa)}"><strong>${esc(a.nazwa)}</strong></span></td>
                <td class="drk-k-kontakt" data-label="Ostatni kontakt"><div>${stanAgenta}
                    <span class="drk-drobne">${esc(a.ostatni_kontakt ? temu(a.ostatni_kontakt) : 'jeszcze nie')}</span></div></td>
                <td class="drk-k-wersja-agenta drk-mono" data-label="Wersja">${esc(a.wersja || '—')}</td>
                <td class="drk-k-utworzono" data-label="Sparowany">${esc(godzina(a.utworzono))}</td>
                <td class="drk-k-akcje">${akcje}</td>
            </tr>`;
        }
        let agenci = [];
        async function wczytajAgentow() {
            try {
                const dane = await zapytaj('GET', api + '/agenci');
                agenci = dane.agenci;
                stan.zaladowane.agenci = true;
                $('drk-agenci-lista').innerHTML = agenci.length ? agenci.map(wierszAgenta).join('')
                    : '<tr class="drk-pusty"><td colspan="5" class="drk-pusto">Brak agentów. Kliknij „Dodaj agenta”, żeby dostać token dla komputera hali.</td></tr>';
            } catch (e) {
                $('drk-agenci-lista').innerHTML = `<tr class="drk-pusty"><td colspan="5" class="drk-pusto">${esc(e.message)}</td></tr>`;
            }
        }

        const modalAgent = new bootstrap.Modal($('drk-modal-agent'));
        $('drk-dodaj-agenta').addEventListener('click', () => {
            $('drk-agent-nazwa').value = '';
            $('drk-agent-blad').classList.add('d-none');
            modalAgent.show();
        });
        $('drk-modal-agent').addEventListener('shown.bs.modal', () => $('drk-agent-nazwa').focus());
        $('drk-agent-ok').addEventListener('click', async (ev) => {
            const przycisk = ev.currentTarget;
            przycisk.disabled = true;
            try {
                const wynik = await zapytaj('POST', api + '/agenci', { nazwa: $('drk-agent-nazwa').value.trim() });
                modalAgent.hide();
                pokazToken(wynik.token, `Agent „${wynik.nazwa}” jest sparowany. Wpisz ten token w agencie druku na komputerze hali.`);
                await wczytajAgentow();
            } catch (e) {
                $('drk-agent-blad').textContent = e.message;
                $('drk-agent-blad').classList.remove('d-none');
            } finally {
                przycisk.disabled = false;
            }
        });

        function nowyToken(btn, id) {
            const a = agenci.find(x => x.id === id);
            if (!confirm(`Wydać nowy token dla „${a ? a.nazwa : 'agenta'}”? Stary token przestanie działać — agent połączy się dopiero po wpisaniu nowego.`)) return;
            return akcjaPrzycisku(btn, async () => {
                const wynik = await zapytaj('POST', `${api}/agenci/${id}/token`);
                pokazToken(wynik.token, `Nowy token dla „${a ? a.nazwa : 'agenta'}”. Wpisz go w agencie druku na komputerze hali.`);
                await wczytajAgentow();
            });
        }

        function uniewaznij(btn, id) {
            const a = agenci.find(x => x.id === id);
            if (!confirm(`Unieważnić agenta „${a ? a.nazwa : ''}”? Straci dostęp przy najbliższym połączeniu.`)) return;
            return akcjaPrzycisku(btn, async () => {
                await zapytaj('POST', `${api}/agenci/${id}/uniewaznij`);
                toast('Agent unieważniony.', 'success');
                await Promise.all([wczytajAgentow(), odswiezStan()]);
            });
        }

        // ── wydania ──
        function wierszWydania(w) {
            return `<tr data-id="${w.id}">
                <td class="drk-k-wersja-agenta drk-k-glowna drk-mono"><strong>${esc(w.wersja)}</strong></td>
                <td class="drk-k-rozmiar drk-liczba" data-label="Rozmiar">${(w.rozmiar / 1048576).toFixed(2)} MB</td>
                <td class="drk-k-sha" data-label="SHA-256"><code title="${esc(w.sha256)}">${esc((w.sha256 || '').slice(0, 12))}…</code></td>
                <td class="drk-k-notatki" data-label="Co się zmieniło"><span class="drk-ell" title="${esc(w.notatki || '')}">${esc(w.notatki || '—')}</span></td>
                <td class="drk-k-utworzono" data-label="Wgrano">${esc(godzina(w.wgrano))}</td>
                <td class="drk-k-aktywne">
                    <div class="form-check form-switch m-0 drk-przelacznik">
                        <input class="form-check-input drk-wydanie-aktywne" type="checkbox" ${w.aktywne ? 'checked' : ''}
                               aria-label="Aktywne: wersja ${esc(w.wersja)}">
                    </div>
                </td>
            </tr>`;
        }
        async function wczytajWydania() {
            try {
                const dane = await zapytaj('GET', api + '/wydania');
                stan.zaladowane.wydania = true;
                $('drk-wydania-lista').innerHTML = dane.wydania.length ? dane.wydania.map(wierszWydania).join('')
                    : '<tr class="drk-pusty"><td colspan="6" class="drk-pusto">Brak wydań. Wgraj instalator agenta w formularzu powyżej.</td></tr>';
            } catch (e) {
                $('drk-wydania-lista').innerHTML = `<tr class="drk-pusty"><td colspan="6" class="drk-pusto">${esc(e.message)}</td></tr>`;
            }
        }
        $('drk-wydania-lista').addEventListener('change', async (ev) => {
            const przelacznik = ev.target.closest('.drk-wydanie-aktywne');
            if (!przelacznik) return;
            const id = Number(przelacznik.closest('tr').dataset.id);
            const aktywne = przelacznik.checked;
            try {
                await zapytaj('PATCH', `${api}/wydania/${id}/aktywne`, { aktywne });
                toast(aktywne ? 'Wydanie aktywne — agent je pobierze.' : 'Wydanie wyłączone.', 'success');
            } catch (e) {
                przelacznik.checked = !aktywne;
                toast(e.message, 'error');
            }
        });
        $('drk-wydanie-form').addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const formularzHtml = ev.currentTarget;
            const status = $('drk-wydanie-status');
            const przycisk = $('drk-wydanie-wgraj');
            if (!$('drk-wydanie-plik').files.length || !$('drk-wydanie-wersja').value.trim()) {
                status.textContent = 'Wybierz plik instalatora i wpisz wersję.';
                status.className = 'drk-status drk-status--blad';
                return;
            }
            przycisk.disabled = true;
            status.textContent = 'Wgrywanie…';
            status.className = 'drk-status';
            try {
                const formularz = new FormData(formularzHtml);
                const w = await zapytaj('POST', api + '/wydania', undefined, formularz);
                status.textContent = `Wgrano wersję ${w.wersja}` + (w.aktywne ? ' — aktywna.' : ' — nieaktywna; włącz ją w liście poniżej.');
                status.className = 'drk-status drk-status--ok';
                formularzHtml.reset();
                await wczytajWydania();
            } catch (e) {
                status.textContent = e.message;
                status.className = 'drk-status drk-status--blad';
            } finally {
                przycisk.disabled = false;
            }
        });

        // ════════════════ KONFIGURACJA AGENTA (dokument z wersją) ════════════════

        const form = $('drk-konf-form');
        function wierszDrukarki(d, nr) {
            const p = (pole) => `drk-konf-d${nr}-${pole}`;
            const opcje = (lista, wybrana) => lista.map(([w, t]) =>
                `<option value="${w}" ${w === wybrana ? 'selected' : ''}>${esc(t)}</option>`).join('');
            return `<div class="drk-drukarka-wiersz" data-wiersz>
                <div class="drk-pole"><label for="${p('nazwa')}">Drukarka</label>
                    <select id="${p('nazwa')}" data-pole="nazwa">${opcje([['etykiety', 'Etykiety 60×40'], ['wysylka', 'Paczki 100×150']], d.nazwa)}</select></div>
                <div class="drk-pole"><label for="${p('ip')}">Adres IP</label>
                    <input type="text" id="${p('ip')}" data-pole="ip" value="${esc(d.ip ?? '')}" inputmode="decimal" autocomplete="off"></div>
                <div class="drk-pole"><label for="${p('port')}">Port</label>
                    <input type="number" id="${p('port')}" data-pole="port" min="1" max="65535" value="${esc(d.port ?? 9100)}"></div>
                <div class="drk-pole"><label for="${p('model')}">Model</label>
                    <input type="text" id="${p('model')}" data-pole="model" value="${esc(d.model ?? '')}" placeholder="np. XP-423B"></div>
                <div class="drk-pole"><label for="${p('odczyt_stanu')}">Odczyt stanu</label>
                    <select id="${p('odczyt_stanu')}" data-pole="odczyt_stanu">${opcje([['snmp', 'SNMP'], ['brak', 'brak']], d.odczyt_stanu)}</select></div>
                <div class="drk-pole"><label for="${p('limit_wysylki_s')}">Limit wysyłki (s)</label>
                    <input type="number" id="${p('limit_wysylki_s')}" data-pole="limit_wysylki_s" min="1" value="${esc(d.limit_wysylki_s ?? 10)}"></div>
                <button type="button" class="drk-drukarka-usun" data-usun-drukarke title="Usuń drukarkę z konfiguracji"
                        aria-label="Usuń drukarkę z konfiguracji"><i class="fas fa-trash" aria-hidden="true"></i></button>
            </div>`;
        }

        let licznikWierszy = 0;
        function rysujDrukarkiKonfiguracji(drukarki) {
            $('drk-konf-drukarki').innerHTML = drukarki.map(d => wierszDrukarki(d, licznikWierszy++)).join('');
            uaktualnijDodawanie();
        }
        function uaktualnijDodawanie() {
            const wiersze = $('drk-konf-drukarki').querySelectorAll('[data-wiersz]').length;
            $('drk-konf-dodaj-drukarke').disabled = wiersze >= 2;
        }
        $('drk-konf-dodaj-drukarke').addEventListener('click', () => {
            const zajete = [...$('drk-konf-drukarki').querySelectorAll('[data-pole="nazwa"]')].map(s => s.value);
            const nazwa = zajete.includes('etykiety') ? 'wysylka' : 'etykiety';
            const nowa = nazwa === 'etykiety'
                ? { nazwa, ip: '', port: 9100, model: 'XP-423B', odczyt_stanu: 'snmp', limit_wysylki_s: 10 }
                : { nazwa, ip: '', port: 9100, model: 'XP-410B', odczyt_stanu: 'brak', limit_wysylki_s: 10 };
            $('drk-konf-drukarki').insertAdjacentHTML('beforeend', wierszDrukarki(nowa, licznikWierszy++));
            uaktualnijDodawanie();
        });
        $('drk-konf-drukarki').addEventListener('click', (ev) => {
            const usun = ev.target.closest('[data-usun-drukarke]');
            if (!usun) return;
            usun.closest('[data-wiersz]').remove();
            uaktualnijDodawanie();
        });

        function wartoscSciezki(obiekt, sciezka) {
            return sciezka.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obiekt);
        }
        function ustawSciezke(obiekt, sciezka, wartosc) {
            const klucze = sciezka.split('.');
            let o = obiekt;
            klucze.slice(0, -1).forEach((k, i) => {
                if (o[k] == null || typeof o[k] !== 'object') o[k] = /^\d+$/.test(klucze[i + 1]) ? [] : {};
                o = o[k];
            });
            o[klucze[klucze.length - 1]] = wartosc;
        }
        // Pole liczbowe: liczba całkowita, a puste/niepoprawne zostaje tekstem — serwer odpowie czytelnym błędem.
        function liczba(tekst) {
            return /^-?\d+$/.test(String(tekst).trim()) ? parseInt(tekst, 10) : tekst;
        }

        function wypelnijFormularz(dane) {
            rysujDrukarkiKonfiguracji(Array.isArray(dane.drukarki) ? dane.drukarki : []);
            form.querySelectorAll('[data-sciezka]').forEach(pole => {
                const w = wartoscSciezki(dane, pole.dataset.sciezka);
                pole.value = w == null ? '' : w;
            });
        }

        function zbierzFormularz() {
            // Start od wczytanego dokumentu: pola, których formularz nie zna, wracają do serwera bez zmian.
            const dane = JSON.parse(JSON.stringify(stan.konfiguracja.dane || {}));
            dane.drukarki = [...$('drk-konf-drukarki').querySelectorAll('[data-wiersz]')].map(w => {
                const d = {};
                w.querySelectorAll('[data-pole]').forEach(p => {
                    const pole = p.dataset.pole;
                    d[pole] = (pole === 'port' || pole === 'limit_wysylki_s') ? liczba(p.value) : p.value.trim();
                });
                return d;
            });
            form.querySelectorAll('[data-sciezka]').forEach(pole => {
                const sciezka = pole.dataset.sciezka;
                ustawSciezke(dane, sciezka, sciezka.startsWith('przesuniecia.') ? liczba(pole.value) : pole.value);
            });
            return dane;
        }

        function pokazBledy(lista) {
            const box = $('drk-konf-bledy');
            if (!lista || !lista.length) { box.hidden = true; box.innerHTML = ''; return; }
            box.innerHTML = `<strong>Konfiguracja nie została zapisana:</strong><ul>${lista.map(b => `<li>${esc(b)}</li>`).join('')}</ul>`;
            box.hidden = false;
        }

        function opisWersji(k) {
            const zrodlo = k.zrodlo === 'agent' ? 'agent druku' : 'CRM';
            return `Wersja ${k.wersja} · zapisano ${godzina(k.zapisano)} · źródło: ${zrodlo}`;
        }

        async function wczytajKonfiguracje() {
            const komunikat = $('drk-konf-komunikat');
            pokazBledy(null);
            $('drk-konf-nadpisano').hidden = true;
            try {
                const k = await zapytaj('GET', api + '/konfiguracja');
                stan.konfiguracja = k;
                stan.zaladowane.konfiguracja = true;
                $('drk-konf-wersja').textContent = opisWersji(k);
                wypelnijFormularz(k.dane);
                komunikat.hidden = true;
                form.hidden = false;
                await wczytajHistorie();
            } catch (e) {
                stan.konfiguracja = null;
                form.hidden = true;
                $('drk-konf-wersja').textContent = 'Brak konfiguracji do edycji';
                komunikat.textContent = e.message;
                komunikat.hidden = false;
                $('drk-historia-lista').innerHTML = '<tr class="drk-pusty"><td colspan="4" class="drk-pusto">Historia pojawi się po sparowaniu i pierwszym kontakcie agenta.</td></tr>';
            }
        }
        $('drk-konf-wczytaj').addEventListener('click', () => { $('drk-konf-status').textContent = ''; wczytajKonfiguracje(); });

        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            if (!stan.konfiguracja) return;
            const status = $('drk-konf-status');
            const przycisk = $('drk-konf-zapisz');
            pokazBledy(null);
            $('drk-konf-nadpisano').hidden = true;
            przycisk.disabled = true;
            status.textContent = 'Zapisywanie…';
            status.className = 'drk-status';
            try {
                const w = await zapytaj('PUT', api + '/konfiguracja',
                    { dane: zbierzFormularz(), wersja_bazowa: stan.konfiguracja.wersja });
                status.textContent = `Zapisano wersję ${w.wersja}. Agent pobierze ją sam.`;
                status.className = 'drk-status drk-status--ok';
                if (w.nadpisano) {
                    const nad = $('drk-konf-nadpisano');
                    nad.textContent = `Zapisano wersję ${w.wersja} i nadpisano wersję ${w.nadpisano}, zapisaną w międzyczasie ` +
                        '(przez agenta albo inną osobę). Sprawdź w historii, co zawierała.';
                    nad.hidden = false;
                }
                stan.konfiguracja = { ...stan.konfiguracja, wersja: w.wersja, dane: w.dane, zrodlo: 'crm', zapisano: new Date().toISOString() };
                $('drk-konf-wersja').textContent = opisWersji(stan.konfiguracja);
                wypelnijFormularz(w.dane);
                await wczytajHistorie();
            } catch (e) {
                status.textContent = '';
                if (e.kod === 'bledna_konfiguracja' && e.dane && e.dane.bledy) pokazBledy(e.dane.bledy);
                else pokazBledy([e.message]);
            } finally {
                przycisk.disabled = false;
            }
        });

        // ── historia: lista zmienionych pól między „przed” i „po” ──
        function splaszcz(obiekt, prefiks, wynik) {
            if (obiekt !== null && typeof obiekt === 'object') {
                Object.keys(obiekt).forEach(k => splaszcz(obiekt[k], prefiks ? prefiks + '.' + k : k, wynik));
            } else {
                wynik[prefiks] = obiekt;
            }
            return wynik;
        }
        function zmiany(przed, po) {
            const a = splaszcz(przed || {}, '', {});
            const b = splaszcz(po || {}, '', {});
            const sciezki = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
            return sciezki.filter(s => JSON.stringify(a[s]) !== JSON.stringify(b[s]))
                .map(s => `<li><code>${esc(s)}</code>: ${esc(a[s] === undefined ? '—' : a[s])} → ${esc(b[s] === undefined ? '—' : b[s])}</li>`);
        }
        async function wczytajHistorie() {
            try {
                const dane = await zapytaj('GET', api + '/konfiguracja/historia');
                $('drk-historia-lista').innerHTML = dane.historia.length ? dane.historia.map(h => {
                    const lista = h.przed ? zmiany(h.przed, h.po) : [];
                    const opis = !h.przed ? '<span class="drk-drobne">pierwsza wersja</span>'
                        : lista.length ? `<ul class="drk-zmiany">${lista.slice(0, 8).join('')}${lista.length > 8 ? `<li>i ${lista.length - 8} więcej</li>` : ''}</ul>`
                        : '<span class="drk-drobne">bez zmian w treści</span>';
                    const nadpisala = h.nadpisana_wersja
                        ? `<span class="drk-drobne">nadpisała wersję ${h.nadpisana_wersja}</span>` : '';
                    const zrodlo = h.zrodlo === 'agent' ? 'agent druku' : 'CRM';
                    return `<tr>
                        <td class="drk-k-wersja drk-k-glowna drk-mono"><strong>${h.wersja}</strong></td>
                        <td class="drk-k-czas" data-label="Czas">${esc(godzina(h.czas ? h.czas + 'Z' : null))}</td>
                        <td class="drk-k-zrodlo" data-label="Skąd"><div>${esc(zrodlo)}<span class="drk-drobne">${esc(h.aktor || '')}</span>${nadpisala}</div></td>
                        <td class="drk-k-zmiany" data-label="Zmiany"><div>${opis}</div></td>
                    </tr>`;
                }).join('') : '<tr class="drk-pusty"><td colspan="4" class="drk-pusto">Brak zapisanych zmian.</td></tr>';
            } catch (e) {
                $('drk-historia-lista').innerHTML = `<tr class="drk-pusty"><td colspan="4" class="drk-pusto">${esc(e.message)}</td></tr>`;
            }
        }

        // ════════════════ USTAWIENIA DRUKU (stanowiska uprawnione do druku etykiet) ════════════════
        // Zmiany zbieramy jak pasek Konfiguracji (porównanie z wartością z serwera) i zapisujemy jednym
        // POST /production/api/update-configs. Przesunięć tu nie ma — edytuje je tylko dokument konfiguracji.

        // Czas zmiany z serwera jest w UTC — pokazujemy go w czasie lokalnym.
        root.querySelectorAll('.drk-czas[data-czas]').forEach(el => {
            el.textContent = new Date(el.dataset.czas).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' });
        });
        const polaUstawien = [...root.querySelectorAll('.drk-ust')];
        polaUstawien.forEach(p => { p.dataset.pierwotna = p.value; });
        function wartoscUstawienia(p) {
            return p.dataset.typ === 'liczba' ? liczba(p.value) : p.value;
        }
        function zmienioneUstawienia() {
            const wynik = {};
            polaUstawien.forEach(p => { if (p.value !== p.dataset.pierwotna) wynik[p.dataset.klucz] = wartoscUstawienia(p); });
            return wynik;
        }
        function odswiezPasekZapisu() {
            const zmienione = zmienioneUstawienia();
            const ile = Object.keys(zmienione).length;
            polaUstawien.forEach(p => p.closest('.config-item').classList.toggle('config-item-changed', p.value !== p.dataset.pierwotna));
            $('drk-ustawienia-zapis').hidden = !ile;
            $('drk-ustawienia-zapis-tekst').textContent = ile === 1 ? '1 niezapisana zmiana' : `${ile} niezapisane zmiany`;
        }
        polaUstawien.forEach(p => p.addEventListener(p.tagName === 'SELECT' ? 'change' : 'input', odswiezPasekZapisu));
        root.querySelectorAll('[data-drk-reset]').forEach(b => b.addEventListener('click', () => {
            const pole = root.querySelector(`.drk-ust[data-klucz="${b.dataset.drkReset}"]`);
            if (!pole || pole.dataset.domyslna === undefined) return;
            pole.value = pole.dataset.domyslna;
            odswiezPasekZapisu();
        }));
        $('drk-ustawienia-cofnij').addEventListener('click', () => {
            polaUstawien.forEach(p => { p.value = p.dataset.pierwotna; });
            odswiezPasekZapisu();
        });
        $('drk-ustawienia-zapisz').addEventListener('click', async (ev) => {
            const przycisk = ev.currentTarget;
            const configs = zmienioneUstawienia();
            if (!Object.keys(configs).length) return;
            przycisk.disabled = true;
            try {
                const wynik = await zapytaj('POST', ADRES_USTAWIEN, { configs });
                polaUstawien.forEach(p => { if (p.dataset.klucz in configs) p.dataset.pierwotna = p.value; });
                odswiezPasekZapisu();
                toast(wynik.message || 'Zapisano.', 'success');
            } catch (e) {
                const szczegoly = e.dane && e.dane.validation_errors;
                const tekst = szczegoly
                    ? Object.entries(szczegoly).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join('; ')
                    : '';
                toast(tekst ? `${e.message}: ${tekst}` : e.message, 'error');
            } finally {
                przycisk.disabled = false;
            }
        });

        startTimera();
        odswiezPrzeglad();
    }

    // Odświeżanie stanu co 15 s, tylko gdy zakładka jest widoczna. Lista zadań odświeża się razem z nim.
    function startTimera() {
        zatrzymajTimer();
        window.__drukarkiTimer = setInterval(() => {
            if (!zakladkaWidoczna() || !document.getElementById('drk-root')) return;
            document.getElementById('drk-odswiez')?.click();
        }, ODSWIEZANIE_MS);
    }

    // Powrót na zakładkę: odśwież od razu, bez czekania na najbliższy tik. Jeden słuchacz na stronę, zapinany przy
    // pierwszym init — wtedy ProductionApp na pewno już istnieje (to on wczytał zakładkę).
    function zapnijSluchaczZakladki() {
        if (window.__drukarkiSluchaczZakladki) return;
        const bus = window.ProductionApp?.shared?.eventBus;
        if (!bus || typeof bus.on !== 'function') return;
        window.__drukarkiSluchaczZakladki = true;
        bus.on('tab:changed', (dane) => {
            if (dane && dane.tab === 'printers-tab' && biezacy && document.getElementById('drk-root')) {
                document.getElementById('drk-odswiez')?.click();
            }
        });
    }

    window.DrukarkiTab = { init };
})();
