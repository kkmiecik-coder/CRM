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
 *   GET    {API}/drivers                kierowcy (aktywni ze znacznikiem) z nazwami tras roboczych/zatwierdzonych
 *   GET    {API}/drivers/candidates     aktywni pracownicy bez znacznika — okno „Dodaj kierowcę”
 *   POST   {API}/drivers                {worker_id} → {driver, drivers}
 *   DELETE {API}/drivers/<id>           zdjęcie znacznika → {driver, drivers} (na swoich trasach zostaje)
 * Odmowa to {success: false, error: „…”} (404/409/422) — w oknie pojazdu albo w komunikacie.
 *
 * Komunikaty przez window.LogisticsTab.komunikat; publicznie window.LogisticsFleet = {root, zniszcz}.
 * Każdy tekst z API przechodzi przez esc() albo textContent.
 *
 * Zdarzenia (document, detail.root = #logistics-root): słuchamy `logistics:widok`
 * (logistics.js — Flota na ekranie = świeże dane), wysyłamy `logistics:flota-zmieniona`
 * po każdym zapisie pojazdu (dodanie, zmiana, wyłączenie, włączenie) — edytor trasy
 * (logistics-routes.js) pobiera wtedy dostępność pojazdów od nowa, oraz po każdej zmianie kierowców (runda 2).
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

    // Runda 2 (spec 2.6): okno „Dodaj kierowcę” (poza panelem Floty, jak okno pojazdu).
    const dialogKierowcy = root.querySelector('[data-lg="kierowca-dialog"]');
    const formKierowcy = el('kierowca-form');
    const kandydaciQ = el('kandydaci-q');
    const kandydaciEl = el('kandydaci');
    const kandydaciStanEl = el('kandydaci-stan');
    const bladKierowcyEl = el('kierowca-blad');
    const kandydaciPonowBtn = el('kandydaci-ponow');

    const stan = {
        pojazdy: [],
        kierowcy: [],
        wczytano: false,         // pojazdy
        blad: null,              // błąd odczytu pojazdów
        // (D11) Kierowcy czytani niezależnie od pojazdów: własne „wczytano” i własny błąd.
        kierowcyWczytani: false,
        kierowcyBlad: null,
        zapisywane: new Set(),   // id pojazdów, dla których leci „Wyłącz/Włącz”
        kandydaci: null,               // okno „Dodaj kierowcę”: GET /drivers/candidates (null = w drodze)
        kandydaciBlad: null,           // (D7) błąd tego odczytu — okno pokazuje wtedy tylko błąd i ponowienie
        dodaniKierowcy: new Set(),     // id pracowników, dla których leci POST /drivers
        usuwaniKierowcy: new Set(),    // id kierowców, dla których leci DELETE /drivers/<id>
        ostatnioDodany: '',            // nazwa ostatnio dodanego — potwierdzenie w oknie
    };
    let edytowany = null;        // otwarte okno: {id | null, powrot, zapis}
    let kontroler = null;
    let zniszczona = false;
    let kontrolerKandydatow = null;
    let powrotKierowcy = null;
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

    // (przegląd końcowy, minor 2) Brak odpowiedzi (0) albo błąd serwera (≥ 500): zapis mógł
    // przejść, a odpowiedź nie dotarła — lista od nowa, zamiast drugiego „Dodaj pojazd”
    // (pojazdu nie da się potem usunąć, najwyżej wyłączyć).
    const niepewnaOdpowiedz = (e) => !!e && e.name !== 'AbortError' && (e.status === 0 || e.status >= 500);

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
        renderujKierowcow();
        przywrocFokus(fokus);
    }

    async function wczytaj() {
        if (zniszczona) return;
        if (kontroler) kontroler.abort();
        const moj = new AbortController();
        kontroler = moj;
        // (D11) Pojazdy i kierowcy to dwa niezależne odczyty: błąd /drivers nie chowa pojazdów
        // (i odwrotnie) — każda lista pokazuje swój wynik albo swój błąd.
        const [pojazdy, kierowcy] = await Promise.allSettled([
            zapytanie('/vehicles', { signal: moj.signal }),
            zapytanie('/drivers', { signal: moj.signal }),
        ]);
        // Przerwane (nowsze wczytanie albo zniszczenie instancji) — wynik należy do kogoś innego.
        if (zniszczona || moj !== kontroler) return;
        kontroler = null;
        const bladP = pojazdy.status === 'rejected' ? pojazdy.reason : null;
        const bladK = kierowcy.status === 'rejected' ? kierowcy.reason : null;
        // Lista już na ekranie, a odświeżenie nie wyszło: lista zostaje, błąd w komunikacie.
        const nieodswiezone = [];
        if (bladP) {
            stan.blad = bladP.message;
            if (stan.wczytano) nieodswiezone.push(['pojazdów', bladP]);
        } else {
            stan.pojazdy = Array.isArray(pojazdy.value.vehicles) ? pojazdy.value.vehicles : [];
            stan.wczytano = true;
            stan.blad = null;
        }
        if (bladK) {
            stan.kierowcyBlad = bladK.message;
            if (stan.kierowcyWczytani) nieodswiezone.push(['kierowców', bladK]);
        } else {
            stan.kierowcy = Array.isArray(kierowcy.value.drivers) ? kierowcy.value.drivers : [];
            stan.kierowcyWczytani = true;
            stan.kierowcyBlad = null;
        }
        if (nieodswiezone.length) {
            komunikat('blad', 'Nie odświeżono ' + nieodswiezone.map((n) => n[0]).join(' ani ') + '. ' +
                nieodswiezone[0][1].message, { klucz: 'flota' });
        }
        renderuj();
    }

    function przyjmijPojazd(pojazd) {
        if (!pojazd) return;
        const i = stan.pojazdy.findIndex((p) => p.id === pojazd.id);
        if (i === -1) stan.pojazdy.push(pojazd); else stan.pojazdy[i] = pojazd;
        renderuj();
        // (oględziny Task 8, M2) Otwarta trasa ma od razu aktualne pojazdy (nazwa, ładowność,
        // wyłączony / włączony) w wyborze pojazdu.
        document.dispatchEvent(new CustomEvent('logistics:flota-zmieniona', { detail: { root: root } }));
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
            const niepewna = niepewnaOdpowiedz(e);
            komunikat('blad', 'Nie zmieniono pojazdu „' + pojazd.name + '”. ' + e.message +
                (niepewna ? ' Zmiana mogła się zapisać — odświeżamy listę pojazdów.' : ''), { klucz: 'flota' });
            if (niepewna) wczytaj();
        } finally {
            if (!zniszczona) {
                stan.zapisywane.delete(id);
                renderuj();
            }
        }
    }

    // ── Okno pojazdu (dodanie i edycja) ─────────────────────────────────────

    // (oględziny Task 8, M15) Pole z błędem: aria-invalid i aria-describedby na tekst błędu,
    // żeby czytnik ekranu powiązał komunikat z polem. Znika przy poprawce pola i z błędem.
    function oznaczPole(pole) {
        if (!pole) return;
        pole.setAttribute('aria-invalid', 'true');
        pole.setAttribute('aria-describedby', 'lg-pojazd-blad');
    }

    function zdejmijOznaczenia() {
        if (!form) return;
        form.querySelectorAll('[aria-invalid]').forEach((p) => {
            p.removeAttribute('aria-invalid');
            p.removeAttribute('aria-describedby');
        });
    }

    function pokazBlad(tekst) {
        if (!bladEl) return;
        bladEl.textContent = tekst || '';
        bladEl.hidden = !tekst;
        if (!tekst) zdejmijOznaczenia();
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
        const poleLadownosci = form.elements.namedItem('capacity_kg');
        const ladownosc = poleLadownosci.value.trim();
        const bladLadownosci = {
            blad: 'Ładowność podaj w pełnych kilogramach (od 1 do ' + liczbaCala.format(MAKS_LADOWNOSC_KG) + ').',
            pole: 'capacity_kg',
        };
        if (!nazwa || nazwa.length > 100) return { blad: 'Podaj nazwę pojazdu (do 100 znaków).', pole: 'name' };
        if (rejestracja.length > 20) return { blad: 'Numer rejestracyjny może mieć najwyżej 20 znaków.', pole: 'registration' };
        // (przegląd końcowy, minor 5) Pole liczbowe z czymś, czego przeglądarka nie umie odczytać
        // (np. „12e”), ma value === '' — bez tego zapis wyczyściłby ładowność i zgłosił sukces.
        if (poleLadownosci.validity && poleLadownosci.validity.badInput) return bladLadownosci;
        let kg = null;
        if (ladownosc) {
            if (!/^[0-9]{1,6}$/.test(ladownosc) || Number(ladownosc) <= 0 || Number(ladownosc) > MAKS_LADOWNOSC_KG) {
                return bladLadownosci;
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
            zdejmijOznaczenia();
            pokazBlad(wynik.blad);
            const pole = form.elements.namedItem(wynik.pole);
            oznaczPole(pole);
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
            // Okno zamknięte w trakcie zapisu (minor 3) — fokusu nie zabieramy spod ręki.
            if (edytowany === e) zamknijDialog(odp.vehicle.id);
            komunikat('ok', (e.id ? 'Zapisano pojazd „' : 'Dodano pojazd „') + odp.vehicle.name + '”.', { klucz: 'flota' });
        } catch (err) {
            if (zniszczona) return;
            const niepewna = niepewnaOdpowiedz(err);
            const tekst = err.message + (niepewna ? (e.id
                ? ' Zmiana mogła się zapisać — odświeżamy listę pojazdów.'
                : ' Pojazd mógł już zostać dodany — sprawdź listę, zanim dodasz go ponownie.') : '');
            if (niepewna) wczytaj();
            if (edytowany !== e) {
                // (przegląd końcowy, minor 3) Okno zamknięte w trakcie zapisu (drugi Esc w Chrome
                // zamyka je mimo blokady) — odmowa nie może przepaść bez słowa.
                komunikat('blad', 'Nie zapisano pojazdu „' + wynik.dane.name + '”. ' + tekst, { klucz: 'flota' });
                return;
            }
            ustawZapis(false);
            pokazBlad(tekst);
        }
    }

    // ── Kierowcy (runda 2, spec 2.6) ────────────────────────────────────────

    // „Łukasz” znajduje się po „lukasz” — wyszukiwarka bez ogonków i wielkości liter.
    function bezOgonkow(tekst) {
        return String(tekst || '').toLocaleLowerCase('pl').replace(/ł/g, 'l')
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    const listaTras = (trasy) => trasy.map((t) => '„' + t + '”').join(', ');

    function kierowcaHtml(k) {
        const usuwany = stan.usuwaniKierowcy.has(k.id);
        const trasy = Array.isArray(k.trasy) ? k.trasy : [];
        return '<li class="lg-kierowca' + (usuwany ? ' is-zapisywany' : '') + '" data-kierowca-id="' + esc(k.id) + '">' +
            '<i class="fas fa-user" aria-hidden="true"></i>' +
            '<span class="lg-kierowca-nazwa">' + esc(k.nazwa) + '</span>' +
            (trasy.length ? '<span class="lg-kierowca-trasy" title="' + esc('Na trasach: ' + trasy.join(', ')) + '">' +
                trasy.length + ' ' + odmiana(trasy.length, ['trasa', 'trasy', 'tras']) + '</span>' : '') +
            '<button type="button" class="lg-ikona-przycisk lg-kierowca-usun" data-lg-flota-akcja="usun-kierowce"' +
                (usuwany ? ' aria-disabled="true"' : '') +
                ' aria-label="' + esc('Usuń ' + k.nazwa + ' z kierowców') + '" title="Usuń z kierowców">' +
                '<i class="fas fa-trash-can" aria-hidden="true"></i></button>' +
            '</li>';
    }

    function renderujKierowcow() {
        if (!kierowcyEl) return;
        // Fokus na koszu przeżywa przerysowanie; po usunięciu — następny kosz albo „Dodaj kierowcę”.
        const a = document.activeElement;
        const li = a && kierowcyEl.contains(a) ? a.closest('[data-kierowca-id]') : null;
        const indeks = li ? Array.from(kierowcyEl.children).indexOf(li) : -1;
        const naPonowieniu = !!(a && kierowcyEl.contains(a) && a.getAttribute('data-lg-flota-akcja') === 'ponow');
        let html = '';
        if (stan.kierowcyBlad && !stan.kierowcyWczytani) {
            // (D11) Kierowcy się nie wczytali (pojazdy obok mogą działać) — błąd zamiast pustej listy,
            // która wyglądałaby jak „nie ma jeszcze kierowców”.
            html = '<li class="lg-kierowcy-blad">' +
                '<span class="lg-stan-tytul">Nie udało się pobrać kierowców.</span>' +
                '<span class="lg-stan-opis">' + esc(stan.kierowcyBlad) + '</span>' +
                '<button type="button" class="lg-przycisk" data-lg-flota-akcja="ponow">' +
                '<i class="fas fa-rotate-right" aria-hidden="true"></i>Spróbuj ponownie</button></li>';
        } else if (stan.kierowcyWczytani) {
            html = stan.kierowcy.length ? stan.kierowcy.map(kierowcaHtml).join('')
                : '<li class="lg-kierowcy-pusto">Dodaj kierowców spośród pracowników.</li>';
        }
        kierowcyEl.innerHTML = html;
        if (kierowcyIleEl) kierowcyIleEl.textContent = stan.kierowcyWczytani ? String(stan.kierowcy.length) : '';
        if (naPonowieniu) {
            // „Spróbuj ponownie” zniknął razem z błędem — fokus na nowy (znów błąd) albo „Dodaj kierowcę”.
            const cel = kierowcyEl.querySelector('[data-lg-flota-akcja="ponow"]') ||
                panel.querySelector('[data-lg-flota-akcja="dodaj-kierowce"]');
            if (cel) cel.focus({ preventScroll: true });
            return;
        }
        if (!li) return;
        const cel = kierowcyEl.querySelector('[data-kierowca-id="' + li.getAttribute('data-kierowca-id') + '"] .lg-kierowca-usun') ||
            (kierowcyEl.children[Math.min(indeks, kierowcyEl.children.length - 1)] || { querySelector: () => null })
                .querySelector('.lg-kierowca-usun') ||
            panel.querySelector('[data-lg-flota-akcja="dodaj-kierowce"]');
        if (cel) cel.focus({ preventScroll: true });
    }

    function przyjmijKierowcow(lista) {
        if (Array.isArray(lista)) {
            // Pełna lista z POST/DELETE /drivers — tak samo dobra jak odczyt GET /drivers.
            stan.kierowcy = lista;
            stan.kierowcyWczytani = true;
            stan.kierowcyBlad = null;
        }
        renderujKierowcow();
        // Otwarta trasa ma od razu aktualny wybór kierowcy (logistics-routes.js, dostępność).
        document.dispatchEvent(new CustomEvent('logistics:flota-zmieniona', { detail: { root: root } }));
    }

    function potwierdzenieUsuniecia(k) {
        const trasy = Array.isArray(k.trasy) ? k.trasy : [];
        return 'Usunąć „' + k.nazwa + '” z kierowców?\n' + (trasy.length
            ? 'Na ' + (trasy.length === 1 ? 'trasie ' : 'trasach ') + listaTras(trasy) +
                ' dalej będzie kierowcą — tam nic się nie zmieni. Do nowych tras nie będzie do wyboru.'
            : 'Pracownik zostaje w systemie, tylko nie będzie do wyboru w trasach.');
    }

    async function usunKierowce(id) {
        const k = stan.kierowcy.find((x) => x.id === id);
        if (!k || stan.usuwaniKierowcy.has(id)) return;
        if (!window.confirm(potwierdzenieUsuniecia(k))) return;
        stan.usuwaniKierowcy.add(id);
        renderujKierowcow();
        try {
            const odp = await zapytanie('/drivers/' + encodeURIComponent(id), { metoda: 'DELETE' });
            if (zniszczona) return;
            const zostaje = odp.driver && Array.isArray(odp.driver.trasy) ? odp.driver.trasy : [];
            stan.usuwaniKierowcy.delete(id);
            przyjmijKierowcow(odp.drivers);
            komunikat('info', '„' + k.nazwa + '” nie jest już kierowcą.' + (zostaje.length
                ? ' Zostaje na ' + (zostaje.length === 1 ? 'trasie ' : 'trasach ') + listaTras(zostaje) + '.' : ''),
                { klucz: 'kierowcy' });
        } catch (e) {
            if (zniszczona) return;
            const niepewna = niepewnaOdpowiedz(e);
            komunikat('blad', 'Nie usunięto „' + k.nazwa + '” z kierowców. ' + e.message +
                (niepewna ? ' Zmiana mogła się zapisać — odświeżamy listę kierowców.' : ''), { klucz: 'kierowcy' });
            if (niepewna) wczytaj();
        } finally {
            if (!zniszczona && stan.usuwaniKierowcy.delete(id)) renderujKierowcow();
        }
    }

    function pokazBladKierowcy(tekst) {
        if (!bladKierowcyEl) return;
        bladKierowcyEl.textContent = tekst || '';
        bladKierowcyEl.hidden = !tekst;
    }

    function kandydatHtml(k) {
        const dodawany = stan.dodaniKierowcy.has(k.id);
        return '<li class="lg-kandydat-kierowcy" data-pracownik-id="' + esc(k.id) + '">' +
            '<span class="lg-kandydat-kierowcy-nazwa">' + esc(k.nazwa) + '</span>' +
            '<button type="button" class="lg-przycisk" data-lg-flota-akcja="wybierz-kierowce"' +
                (dodawany ? ' aria-disabled="true"' : '') + ' aria-label="' + esc('Dodaj ' + k.nazwa + ' do kierowców') + '">' +
                '<i class="fas fa-plus" aria-hidden="true"></i>' + (dodawany ? 'Dodawanie…' : 'Dodaj') + '</button>' +
            '</li>';
    }

    function renderujKandydatow() {
        if (!kandydaciEl) return;
        const a = document.activeElement;
        const fokusLi = a && kandydaciEl.contains(a) ? a.closest('[data-pracownik-id]') : null;
        const indeks = fokusLi ? Array.from(kandydaciEl.children).indexOf(fokusLi) : -1;
        const fraza = kandydaciQ ? kandydaciQ.value.trim() : '';
        const q = bezOgonkow(fraza);
        const teksty = [];
        let html = '';
        // (D7) Po błędzie wczytania okno pokazuje tylko błąd (lg-dialog-blad) i „Spróbuj ponownie” —
        // pusta lista nie znaczy wtedy „wszyscy są już kierowcami”.
        if (!stan.kandydaciBlad) {
            if (stan.ostatnioDodany) teksty.push('Dodano „' + stan.ostatnioDodany + '” do kierowców.');
            if (stan.kandydaci === null) {
                teksty.push('Wczytywanie pracowników…');
            } else {
                const pasujacy = stan.kandydaci.filter((k) => !q || bezOgonkow(k.nazwa).includes(q));
                html = pasujacy.map(kandydatHtml).join('');
                if (!stan.kandydaci.length) teksty.push('Wszyscy aktywni pracownicy są już kierowcami.');
                else if (!pasujacy.length) teksty.push('Nikt nie pasuje do „' + fraza + '”.');
            }
        }
        kandydaciEl.innerHTML = html;
        if (kandydaciStanEl) kandydaciStanEl.textContent = teksty.join(' ');
        if (kandydaciPonowBtn) kandydaciPonowBtn.hidden = !stan.kandydaciBlad;
        if (!fokusLi) return;
        const id = fokusLi.getAttribute('data-pracownik-id');
        const przyciski = Array.from(kandydaciEl.querySelectorAll('button'));
        const cel = kandydaciEl.querySelector('[data-pracownik-id="' + id + '"] button') ||
            przyciski[Math.min(indeks, przyciski.length - 1)] || kandydaciQ;
        if (cel) cel.focus({ preventScroll: true });
    }

    async function wczytajKandydatow() {
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        const moj = new AbortController();
        kontrolerKandydatow = moj;
        stan.kandydaci = null;
        // (D7) Nowa próba zdejmuje błąd poprzedniego wczytania — tylko ten: odmowa „Dodaj” (404/409
        // woła wczytanie od nowa) zostaje w oknie.
        if (stan.kandydaciBlad) {
            stan.kandydaciBlad = null;
            pokazBladKierowcy('');
        }
        renderujKandydatow();
        try {
            const odp = await zapytanie('/drivers/candidates', { signal: moj.signal });
            if (zniszczona || moj !== kontrolerKandydatow) return;
            stan.kandydaci = Array.isArray(odp.candidates) ? odp.candidates : [];
        } catch (e) {
            if ((e && e.name === 'AbortError') || zniszczona || moj !== kontrolerKandydatow) return;
            stan.kandydaci = [];
            stan.kandydaciBlad = 'Nie wczytano pracowników. ' + e.message;
            pokazBladKierowcy(stan.kandydaciBlad);
        } finally {
            if (moj === kontrolerKandydatow) kontrolerKandydatow = null;
        }
        renderujKandydatow();
    }

    function otworzKierowcow(powrot) {
        if (!dialogKierowcy || dialogKierowcy.open) return;
        powrotKierowcy = powrot || null;
        stan.ostatnioDodany = '';
        pokazBladKierowcy('');
        if (kandydaciQ) kandydaciQ.value = '';
        dialogKierowcy.showModal();
        if (kandydaciQ) kandydaciQ.focus();
        wczytajKandydatow();
    }

    // Zamknięcie zawsze możliwe: każdy „Dodaj” to osobny zapis, który kończy się sam (lista
    // kierowców za oknem i tak dostanie wynik), więc nie polegamy na zdarzeniu `close`.
    function zamknijKierowcow() {
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        if (dialogKierowcy && dialogKierowcy.open) dialogKierowcy.close();
        const cel = powrotKierowcy && powrotKierowcy.isConnected ? powrotKierowcy
            : panel.querySelector('[data-lg-flota-akcja="dodaj-kierowce"]');
        powrotKierowcy = null;
        if (cel) cel.focus({ preventScroll: true });
    }

    async function dodajKierowce(id) {
        const k = (stan.kandydaci || []).find((x) => x.id === id);
        if (!k || stan.dodaniKierowcy.has(id)) return;
        stan.dodaniKierowcy.add(id);
        pokazBladKierowcy('');
        renderujKandydatow();
        try {
            const odp = await zapytanie('/drivers', { metoda: 'POST', dane: { worker_id: id } });
            if (zniszczona) return;
            stan.kandydaci = (stan.kandydaci || []).filter((x) => x.id !== id);
            stan.ostatnioDodany = k.nazwa;
            przyjmijKierowcow(odp.drivers);
            // (oględziny rundy 2, pkt 6) Otwarte okno ma własne potwierdzenie („Dodano „X” do
            // kierowców.”), a komunikat zakładki leżałby pod nim (warstwa górna <dialog>) i znikał
            // niewidziany — pokazujemy go tylko wtedy, gdy okno zamknięto w trakcie zapisu.
            if (!(dialogKierowcy && dialogKierowcy.open)) komunikat('ok', 'Dodano kierowcę „' + k.nazwa + '”.', { klucz: 'kierowcy' });
        } catch (e) {
            if (zniszczona) return;
            const tekst = 'Nie dodano „' + k.nazwa + '”. ' + e.message;
            if (dialogKierowcy && dialogKierowcy.open) pokazBladKierowcy(tekst);
            else komunikat('blad', tekst, { klucz: 'kierowcy' });
            // 404/409 (pracownik zniknął albo przestał być aktywny) albo niepewna odpowiedź — od nowa.
            if (e.status === 404 || e.status === 409 || niepewnaOdpowiedz(e)) {
                wczytaj();
                if (dialogKierowcy && dialogKierowcy.open) wczytajKandydatow();
            }
        } finally {
            if (!zniszczona) {
                stan.dodaniKierowcy.delete(id);
                renderujKandydatow();
            }
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
        else if (akcja === 'dodaj-kierowce') otworzKierowcow(przycisk);
        else if (akcja === 'usun-kierowce') {
            const li = przycisk.closest('[data-kierowca-id]');
            if (li) usunKierowce(Number(li.getAttribute('data-kierowca-id')));
        }
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
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        if (dialogKierowcy && dialogKierowcy.open) dialogKierowcy.close();
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
        // Poprawka pola z błędem: błąd walidacji i oznaczenie pola znikają.
        form.addEventListener('input', (e) => {
            if (e.target && e.target.getAttribute && e.target.getAttribute('aria-invalid') === 'true') pokazBlad('');
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
    if (dialogKierowcy) {
        dialogKierowcy.addEventListener('click', (e) => {
            if (e.target === dialogKierowcy) {
                zamknijKierowcow();
                return;
            }
            const b = e.target.closest('[data-lg-flota-akcja]');
            if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true') return;
            const akcja = b.getAttribute('data-lg-flota-akcja');
            if (akcja === 'kierowca-zamknij') {
                zamknijKierowcow();
            } else if (akcja === 'wybierz-kierowce') {
                const li = b.closest('[data-pracownik-id]');
                if (li) dodajKierowce(Number(li.getAttribute('data-pracownik-id')));
            } else if (akcja === 'kandydaci-ponow') {
                // (D7) Przycisk zniknie razem z błędem — fokus najpierw na wyszukiwarkę okna.
                if (kandydaciQ) kandydaciQ.focus();
                wczytajKandydatow();
            }
        }, naSluch);
        dialogKierowcy.addEventListener('cancel', (e) => {
            e.preventDefault();
            zamknijKierowcow();
        }, naSluch);
        if (formKierowcy) formKierowcy.addEventListener('submit', (e) => e.preventDefault(), naSluch);
        if (kandydaciQ) kandydaciQ.addEventListener('input', renderujKandydatow, naSluch);
    }
    document.addEventListener('logistics:widok', naZmianeWidoku, naSluch);

    renderuj();
    if (!panel.hidden) wczytaj();
})();
