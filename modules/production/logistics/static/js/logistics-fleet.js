/**
 * Logistyka — podzakładka „Flota” (etap 3).
 * modules/production/logistics/static/js/logistics-fleet.js
 *
 * Zwykły <script src> obok logistics.js (bez Leafleta). Dane pobiera przy każdym
 * wejściu na podzakładkę (zdarzenie `logistics:widok` z logistics.js). Pojazdów
 * nie kasujemy: „Wyłącz” zostawia pojazd na starych trasach, ale nie da się go
 * wybrać do nowych — wyłączone stoją wyszarzone na końcu listy.
 *
 * API (modules/production/logistics/routers/trasy_api.py):
 *   GET  {API}/vehicles                 wszystkie pojazdy
 *   POST {API}/vehicles                 {name, registration, capacity_kg} → {vehicle}
 *   PUT  {API}/vehicles/<id>            jw. — zmiana
 *   POST {API}/vehicles/<id>/active     {active: true | false}
 *   GET  {API}/drivers                  aktywni pracownicy produkcji (kierowcy tras)
 * Odmowa to {success: false, error: „…”} (404/409/422) — w oknie pojazdu albo w komunikacie.
 *
 * Komunikaty przez window.LogisticsTab.komunikat; publicznie window.LogisticsFleet = {root, zniszcz}.
 * Każdy tekst z API przechodzi przez esc() albo textContent.
 */
(function () {
    'use strict';

    if (window.LogisticsFleet && typeof window.LogisticsFleet.zniszcz === 'function') {
        try { window.LogisticsFleet.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    const panel = root ? root.querySelector('[data-logistics-view="fleet"]') : null;
    if (!root || !panel) return;

    // data-api = url_for('logistics_panel.orders') → baza bez końcowego /orders.
    const API = (root.getAttribute('data-api') || '/production/api/logistics/orders')
        .replace(/\/orders\/?$/, '');

    const MAKS_LADOWNOSC_KG = 100000;   // jak fleet.MAKS_LADOWNOSC_KG

    const el = (nazwa) => root.querySelector('[data-lg-flota="' + nazwa + '"]');
    const wierszeEl = el('wiersze');
    const ileEl = el('ile');
    const kierowcyEl = el('kierowcy');
    const kierowcyIleEl = el('kierowcy-ile');
    const dialog = root.querySelector('[data-lg="pojazd-dialog"]');
    const form = el('form');
    const tytulEl = el('tytul');
    const bladEl = el('blad');
    const zapiszBtn = el('zapisz');

    const stan = {
        pojazdy: [],
        kierowcy: [],
        wczytano: false,
        blad: null,
        zapisywane: new Set(),   // id pojazdów, dla których leci „Wyłącz/Włącz”
    };
    let edytowany = null;        // otwarte okno: {id | null, powrot, zapis}
    let kontroler = null;
    let zniszczona = false;
    const sluchacze = new AbortController();   // jeden sygnał odpina wszystkie nasłuchy
    const naSluch = { signal: sluchacze.signal };

    // ── Pomocnicze ──────────────────────────────────────────────────────────

    function esc(wartosc) {
        if (wartosc === null || wartosc === undefined) return '';
        return String(wartosc).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function odmiana(n, formy) {
        const d = n % 10;
        const s = n % 100;
        if (n === 1) return formy[0];
        if (d >= 2 && d <= 4 && (s < 12 || s > 14)) return formy[1];
        return formy[2];
    }

    const liczbaCala = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 });
    const porownajTekst = new Intl.Collator('pl', { sensitivity: 'base', numeric: true }).compare;

    function komunikat(typ, tresc, opcje) {
        const tab = window.LogisticsTab;
        if (tab && tab.root === root && typeof tab.komunikat === 'function') {
            tab.komunikat(typ, tresc, opcje);
        } else {
            console.warn('[LogisticsFleet]', tresc);
        }
    }

    class BladApi extends Error {
        constructor(komunikat, status) {
            super(komunikat);
            this.status = status;
        }
    }

    function komunikatBledu(status, dane) {
        if (status === 401) return 'Sesja wygasła. Zaloguj się ponownie.';
        if (status === 403) return 'Brak dostępu do modułu produkcji.';
        if (dane && typeof dane.error === 'string' && dane.error) return dane.error;
        if (status >= 500) return 'Błąd serwera (HTTP ' + status + ').';
        return 'Nieoczekiwana odpowiedź serwera (HTTP ' + status + ').';
    }

    async function zapytanie(sciezka, opcje) {
        const o = opcje || {};
        const naglowki = { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' };
        const ustawienia = { method: o.metoda || 'GET', credentials: 'same-origin', headers: naglowki };
        if (o.dane !== undefined) {
            naglowki['Content-Type'] = 'application/json';
            ustawienia.body = JSON.stringify(o.dane);
        }
        if (o.signal) ustawienia.signal = o.signal;
        let odp;
        try {
            odp = await fetch(API + sciezka, ustawienia);
        } catch (e) {
            if (e && e.name === 'AbortError') throw e;
            throw new BladApi('Brak połączenia z serwerem.', 0);
        }
        let dane = null;
        try { dane = await odp.json(); } catch (e) { dane = null; }
        if (!odp.ok || !dane || dane.success === false) {
            throw new BladApi(komunikatBledu(odp.status, dane), odp.status);
        }
        return dane;
    }

    // ── Lista pojazdów ──────────────────────────────────────────────────────

    // Aktywne po nazwie, wyłączone po nazwie — na końcu.
    function posortowane() {
        return stan.pojazdy.slice().sort((a, b) => {
            if (!!a.is_active !== !!b.is_active) return a.is_active ? -1 : 1;
            return porownajTekst(String(a.name || ''), String(b.name || ''));
        });
    }

    function wierszHtml(p) {
        const aktywny = !!p.is_active;
        const zapisywany = stan.zapisywane.has(p.id);
        const przelacz = aktywny ? 'wylacz' : 'wlacz';
        // aria-disabled, nie disabled: przycisk z fokusem zostaje pod klawiaturą na czas zapisu.
        const czeka = zapisywany ? ' aria-disabled="true"' : '';
        return '<tr class="lg-wiersz-floty' + (aktywny ? '' : ' is-wylaczony') + (zapisywany ? ' is-zapisywany' : '') + '"' +
            ' data-pojazd-id="' + esc(p.id) + '">' +
            '<td><span class="lg-pojazd-nazwa">' + esc(p.name) + '</span></td>' +
            '<td>' + (p.registration ? '<span class="lg-rejestracja">' + esc(p.registration) + '</span>'
                : '<span class="lg-brak-danych">brak</span>') + '</td>' +
            '<td class="lg-k-liczba">' + (p.capacity_kg
                ? '<span class="lg-ladownosc">' + esc(liczbaCala.format(Number(p.capacity_kg))) + ' kg</span>'
                : '<span class="lg-brak-danych">nie podano</span>') + '</td>' +
            '<td><span class="lg-flota-status">' + (aktywny ? 'Aktywny' : 'Wyłączony') + '</span></td>' +
            '<td class="lg-k-akcje"><span class="lg-flota-akcje">' +
                '<button type="button" class="lg-przycisk" data-lg-flota-akcja="edytuj"' + czeka +
                    ' aria-label="' + esc('Edytuj pojazd ' + p.name) + '"><i class="fas fa-pen" aria-hidden="true"></i>Edytuj</button>' +
                '<button type="button" class="lg-przycisk' + (aktywny ? ' lg-przycisk--cichy' : '') + '"' +
                    ' data-lg-flota-akcja="' + przelacz + '"' + czeka +
                    ' aria-label="' + esc((aktywny ? 'Wyłącz pojazd ' : 'Włącz pojazd ') + p.name) + '"' +
                    ' title="' + (aktywny ? 'Zostanie na dotychczasowych trasach, ale nie wybierzesz go do nowych.'
                        : 'Znów będzie do wyboru w trasach.') + '">' +
                    '<i class="fas ' + (aktywny ? 'fa-power-off' : 'fa-rotate-left') + '" aria-hidden="true"></i>' +
                    (aktywny ? 'Wyłącz' : 'Włącz') + '</button>' +
            '</span></td>' +
            '</tr>';
    }

    function wierszStanuHtml(tytul, opis, blad, przycisk) {
        return '<tr class="lg-wiersz-stanu"><td colspan="5"><div class="lg-stan' + (blad ? ' lg-stan--blad' : '') + '">' +
            '<span class="lg-stan-tytul">' + esc(tytul) + '</span>' +
            (opis ? '<span class="lg-stan-opis">' + esc(opis) + '</span>' : '') + (przycisk || '') +
            '</div></td></tr>';
    }

    // Fokus na przycisku w wierszu przeżywa przerysowanie (wiersz może zmienić miejsce po „Wyłącz”).
    function fokusWiersza() {
        const a = document.activeElement;
        const tr = a && wierszeEl && wierszeEl.contains(a) ? a.closest('tr[data-pojazd-id]') : null;
        if (!tr) return null;
        const akcja = a.getAttribute('data-lg-flota-akcja');
        return { id: tr.getAttribute('data-pojazd-id'), rodzaj: akcja === 'edytuj' ? 'edytuj' : 'przelacz' };
    }

    function przywrocFokus(fokus) {
        if (!fokus) return;
        const tr = wierszeEl.querySelector('tr[data-pojazd-id="' + fokus.id + '"]');
        if (!tr) return;
        const cel = tr.querySelector(fokus.rodzaj === 'edytuj' ? '[data-lg-flota-akcja="edytuj"]'
            : '[data-lg-flota-akcja="wylacz"], [data-lg-flota-akcja="wlacz"]');
        if (cel && !cel.disabled) cel.focus({ preventScroll: true });
    }

    function renderuj() {
        if (!wierszeEl) return;
        const fokus = fokusWiersza();
        if (stan.blad && !stan.wczytano) {
            wierszeEl.innerHTML = wierszStanuHtml('Nie udało się pobrać floty.', stan.blad, true,
                '<button type="button" class="lg-przycisk" data-lg-flota-akcja="ponow">' +
                '<i class="fas fa-rotate-right" aria-hidden="true"></i>Spróbuj ponownie</button>');
        } else if (!stan.wczytano) {
            wierszeEl.innerHTML = wierszStanuHtml('Ładowanie floty…');
        } else if (!stan.pojazdy.length) {
            wierszeEl.innerHTML = wierszStanuHtml('Flota jest pusta.',
                'Dodaj pierwszy pojazd — potem wybierzesz go w trasie.', false,
                '<button type="button" class="lg-przycisk" data-lg-flota-akcja="dodaj">' +
                '<i class="fas fa-plus" aria-hidden="true"></i>Dodaj pojazd</button>');
        } else {
            wierszeEl.innerHTML = posortowane().map(wierszHtml).join('');
        }
        if (ileEl) {
            const aktywne = stan.pojazdy.filter((p) => p.is_active).length;
            const wylaczone = stan.pojazdy.length - aktywne;
            ileEl.textContent = stan.wczytano && stan.pojazdy.length
                ? aktywne + ' ' + odmiana(aktywne, ['aktywny', 'aktywne', 'aktywnych']) +
                    (wylaczone ? ', ' + wylaczone + ' ' + odmiana(wylaczone, ['wyłączony', 'wyłączone', 'wyłączonych']) : '')
                : '';
        }
        if (kierowcyEl) {
            kierowcyEl.innerHTML = !stan.wczytano ? ''
                : (stan.kierowcy.length
                    ? stan.kierowcy.map((k) => '<li><i class="fas fa-user" aria-hidden="true"></i>' + esc(k.nazwa) + '</li>').join('')
                    : '<li class="lg-kierowcy-pusto">Brak aktywnych pracowników produkcji.</li>');
        }
        if (kierowcyIleEl) kierowcyIleEl.textContent = stan.wczytano ? String(stan.kierowcy.length) : '';
        przywrocFokus(fokus);
    }

    async function wczytaj() {
        if (zniszczona) return;
        if (kontroler) kontroler.abort();
        const moj = new AbortController();
        kontroler = moj;
        try {
            const [pojazdy, kierowcy] = await Promise.all([
                zapytanie('/vehicles', { signal: moj.signal }),
                zapytanie('/drivers', { signal: moj.signal }),
            ]);
            if (zniszczona || moj !== kontroler) return;
            stan.pojazdy = Array.isArray(pojazdy.vehicles) ? pojazdy.vehicles : [];
            stan.kierowcy = Array.isArray(kierowcy.drivers) ? kierowcy.drivers : [];
            stan.wczytano = true;
            stan.blad = null;
        } catch (e) {
            if ((e && e.name === 'AbortError') || zniszczona || moj !== kontroler) return;
            stan.blad = e.message;
            if (stan.wczytano) komunikat('blad', 'Nie odświeżono floty. ' + e.message, { klucz: 'flota' });
        } finally {
            if (moj === kontroler) kontroler = null;
        }
        renderuj();
    }

    function przyjmijPojazd(pojazd) {
        if (!pojazd) return;
        const i = stan.pojazdy.findIndex((p) => p.id === pojazd.id);
        if (i === -1) stan.pojazdy.push(pojazd); else stan.pojazdy[i] = pojazd;
        renderuj();
    }

    async function ustawAktywnosc(id, aktywny) {
        const pojazd = stan.pojazdy.find((p) => p.id === id);
        if (!pojazd || stan.zapisywane.has(id)) return;
        stan.zapisywane.add(id);
        renderuj();
        try {
            // Wprost wartość logiczna JSON — serwer odrzuca „true” jako tekst (R9).
            const odp = await zapytanie('/vehicles/' + encodeURIComponent(id) + '/active', {
                metoda: 'POST', dane: { active: aktywny },
            });
            if (zniszczona) return;
            stan.zapisywane.delete(id);
            przyjmijPojazd(odp.vehicle);
            komunikat(aktywny ? 'ok' : 'info', aktywny
                ? 'Pojazd „' + odp.vehicle.name + '” znów jest do wyboru w trasach.'
                : 'Pojazd „' + odp.vehicle.name + '” wyłączony. Zostaje na dotychczasowych trasach, do nowych go nie wybierzesz.',
                { klucz: 'flota' });
        } catch (e) {
            if (zniszczona) return;
            komunikat('blad', 'Nie zmieniono pojazdu „' + pojazd.name + '”. ' + e.message, { klucz: 'flota' });
        } finally {
            if (!zniszczona) {
                stan.zapisywane.delete(id);
                renderuj();
            }
        }
    }

    // ── Okno pojazdu (dodanie i edycja) ─────────────────────────────────────

    function pokazBlad(tekst) {
        if (!bladEl) return;
        bladEl.textContent = tekst || '';
        bladEl.hidden = !tekst;
    }

    function ustawZapis(trwa) {
        if (edytowany) edytowany.zapis = trwa;
        zapiszBtn.disabled = trwa;
        zapiszBtn.textContent = trwa ? 'Zapisywanie…' : (edytowany && edytowany.id ? 'Zapisz' : 'Dodaj pojazd');
        const anuluj = form.querySelector('[data-lg-flota-akcja="anuluj"]');
        if (anuluj) anuluj.disabled = trwa;
        Array.from(form.elements).forEach((pole) => {
            if (pole.tagName === 'INPUT') pole.readOnly = trwa;
        });
    }

    function otworzDialog(pojazd, powrot) {
        if (!dialog || !form || dialog.open) return;
        edytowany = { id: pojazd ? pojazd.id : null, powrot: powrot || null, zapis: false };
        tytulEl.textContent = pojazd ? 'Edytuj pojazd' : 'Nowy pojazd';
        if (pojazd) {
            const numer = document.createElement('span');
            numer.className = 'lg-dialog-numer';
            numer.textContent = pojazd.name;
            tytulEl.appendChild(numer);
        }
        form.elements.namedItem('name').value = pojazd ? pojazd.name || '' : '';
        form.elements.namedItem('registration').value = pojazd ? pojazd.registration || '' : '';
        form.elements.namedItem('capacity_kg').value = pojazd && pojazd.capacity_kg ? String(pojazd.capacity_kg) : '';
        pokazBlad('');
        ustawZapis(false);
        dialog.showModal();
        const nazwa = form.elements.namedItem('name');
        nazwa.focus();
        nazwa.select();
    }

    // Zamyka okno i oddaje fokus: po zapisie — na „Edytuj” zapisanego pojazdu, inaczej tam, skąd otwarto.
    function zamknijDialog(idPojazdu) {
        const e = edytowany;
        edytowany = null;
        if (dialog && dialog.open) dialog.close();
        let cel = null;
        if (idPojazdu !== undefined && idPojazdu !== null && wierszeEl) {
            cel = wierszeEl.querySelector('tr[data-pojazd-id="' + idPojazdu + '"] [data-lg-flota-akcja="edytuj"]');
        }
        if (!cel && e && e.powrot && e.powrot.isConnected) cel = e.powrot;
        if (!cel) cel = panel.querySelector('[data-lg-flota-akcja="dodaj"]');
        if (cel) cel.focus({ preventScroll: true });
    }

    /** Te same zasady co serwer (services/fleet.py, zapisz_pojazd) — błąd od razu, bez zapytania. */
    function daneFormularza() {
        const nazwa = form.elements.namedItem('name').value.trim();
        const rejestracja = form.elements.namedItem('registration').value.trim();
        const ladownosc = form.elements.namedItem('capacity_kg').value.trim();
        if (!nazwa || nazwa.length > 100) return { blad: 'Podaj nazwę pojazdu (do 100 znaków).', pole: 'name' };
        if (rejestracja.length > 20) return { blad: 'Numer rejestracyjny może mieć najwyżej 20 znaków.', pole: 'registration' };
        let kg = null;
        if (ladownosc) {
            if (!/^[0-9]{1,6}$/.test(ladownosc) || Number(ladownosc) <= 0 || Number(ladownosc) > MAKS_LADOWNOSC_KG) {
                return { blad: 'Ładowność podaj w pełnych kilogramach (od 1 do ' + liczbaCala.format(MAKS_LADOWNOSC_KG) + ').',
                    pole: 'capacity_kg' };
            }
            kg = Number(ladownosc);
        }
        return { dane: { name: nazwa, registration: rejestracja || null, capacity_kg: kg } };
    }

    async function zapisz() {
        const e = edytowany;
        if (!e || e.zapis) return;
        const wynik = daneFormularza();
        if (wynik.blad) {
            pokazBlad(wynik.blad);
            const pole = form.elements.namedItem(wynik.pole);
            if (pole) pole.focus();
            return;
        }
        ustawZapis(true);
        pokazBlad('');
        try {
            const odp = e.id
                ? await zapytanie('/vehicles/' + encodeURIComponent(e.id), { metoda: 'PUT', dane: wynik.dane })
                : await zapytanie('/vehicles', { metoda: 'POST', dane: wynik.dane });
            if (zniszczona) return;
            przyjmijPojazd(odp.vehicle);
            zamknijDialog(odp.vehicle.id);
            komunikat('ok', (e.id ? 'Zapisano pojazd „' : 'Dodano pojazd „') + odp.vehicle.name + '”.', { klucz: 'flota' });
        } catch (err) {
            if (zniszczona || edytowany !== e) return;
            ustawZapis(false);
            pokazBlad(err.message);
        }
    }

    // ── Zdarzenia ───────────────────────────────────────────────────────────

    function naKlik(e) {
        const przycisk = e.target.closest('[data-lg-flota-akcja]');
        if (!przycisk || przycisk.disabled || przycisk.getAttribute('aria-disabled') === 'true') return;
        const akcja = przycisk.getAttribute('data-lg-flota-akcja');
        const tr = przycisk.closest('tr[data-pojazd-id]');
        const id = tr ? Number(tr.getAttribute('data-pojazd-id')) : null;
        const pojazd = id !== null ? stan.pojazdy.find((p) => p.id === id) : null;
        if (akcja === 'dodaj') otworzDialog(null, przycisk);
        else if (akcja === 'edytuj' && pojazd) otworzDialog(pojazd, przycisk);
        else if (akcja === 'wylacz' && pojazd) ustawAktywnosc(id, false);
        else if (akcja === 'wlacz' && pojazd) ustawAktywnosc(id, true);
        else if (akcja === 'ponow') wczytaj();
    }

    function naZmianeWidoku(e) {
        const d = e.detail || {};
        if (d.root === root && d.widok === 'fleet') wczytaj();
    }

    function zniszcz() {
        zniszczona = true;
        sluchacze.abort();
        if (kontroler) kontroler.abort();
        edytowany = null;
        if (dialog && dialog.open) dialog.close();
        if (window.LogisticsFleet === api) delete window.LogisticsFleet;
    }

    const api = { root: root, zniszcz: zniszcz };

    // ── Start ───────────────────────────────────────────────────────────────

    window.LogisticsFleet = api;
    panel.addEventListener('click', naKlik, naSluch);
    if (dialog && form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            zapisz();
        }, naSluch);
        form.addEventListener('click', (e) => {
            const b = e.target.closest('[data-lg-flota-akcja="anuluj"]');
            if (b && !b.disabled) zamknijDialog();
        }, naSluch);
        // Esc i klik w tło zamykają (w trakcie zapisu — nie: odpowiedź musi trafić do listy).
        dialog.addEventListener('cancel', (e) => {
            e.preventDefault();
            if (!(edytowany && edytowany.zapis)) zamknijDialog();
        }, naSluch);
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog && !(edytowany && edytowany.zapis)) zamknijDialog();
        }, naSluch);
        dialog.addEventListener('close', () => { edytowany = null; }, naSluch);
    }
    document.addEventListener('logistics:widok', naZmianeWidoku, naSluch);

    renderuj();
    if (!panel.hidden) wczytaj();
})();
