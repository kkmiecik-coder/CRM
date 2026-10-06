/**
 * Priorytety produkcji — wspólny komponent panelu biura (krok K4a; spec 2026-10-04, sekcje 3.1, 5.3, 5.7, 7.1–7.3).
 * modules/production/priorytety/static/js/priorytety.js
 *
 * Ładuje go raz na stronę templates/panel/dashboard.html (przed products-module.js). Wystawia window.Priorytety:
 * klienta API priorytetów, znaczek i wybierak gwiazdek 0–5, modal priorytetu zamówienia i modal drabiny. Oba modale
 * to natywne <dialog> budowane tutaj (bez szablonu blueprintu priorytetów — zakładka renderuje się bez niego).
 * Z komponentu korzystają Lista produkcyjna (products-module.js) i Logistyka (logistics.js). Nikt poza tym plikiem
 * nie woła końcówek priorytetów.
 *
 * API (modules/production/priorytety/routers/panel_api.py, prefiks /production/api/priorytety):
 *   GET  /kolejka                          kolejka zamówień aktywnych po randze liczonej na żywo
 *   GET  /odlozenia                        otwarte odłożenia stanowisk (plakietki „Odłożone na …”)
 *   GET  /zamowienia/<id>/priorytet        dane modalu priorytetu
 *   PUT  /zamowienia/gwiazdki              {order_ids, gwiazdki} — jedyny zapis gwiazdek (ustawGwiazdki)
 *   GET  /drabina                          widoczne szczeble z licznikami i ostrzeżeniami o datach tras
 *   PUT  /drabina/kolejnosc                {szczebel_id, pozycja, oczekiwane} — jedyny zapis drabiny (przesunSzczebel)
 *   GET  /stoly                            stoły i odłożone stanowisk (klucze kafli do „Zdejmij”)
 *   POST /stoly/<kod>/wyslij               {order_id} — „Wyślij na stanowisko” (wyslijNaStanowisko)
 *   POST /stoly/<kod>/zdejmij              {unit_key} — „Zdejmij ze stołu” (zdejmijZeStolu)
 *   GET  /kolejka?stanowisko=&limit=1      pierwszy kafel kolejki (czy zdjęty kafel wróci)
 *
 * Zdarzenie po zmianie: ProductionShared.eventBus.emit('priorytety:zmiana', {rodzaj, order_ids}).
 *
 * Zasady: dane z API trafiają do HTML wyłącznie przez esc() (także komunikaty w powiadomieniach — ToastSystem
 * składa treść przez innerHTML). Jedno żądanie na akcję i jeden zapis naraz (zapisTrwa); błąd 500 nie jest
 * ponawiany (serwer sam ponowił raz po zakleszczeniu MySQL).
 */
(function () {
    'use strict';

    if (window.Priorytety) return;

    const API = '/production/api/priorytety';
    // Lustro stale.LIMIT_HURTU z serwera: ponad tyle zamówień naraz UI odmawia bez wysyłki.
    const LIMIT_HURTU = 500;

    const ETYKIETY_TAGOW = {
        po_terminie: 'Po terminie',
        blisko_terminu: 'Blisko terminu',
        rozpoczete: 'Rozpoczęte',
    };
    // Miejscownik nazw stanowisk do plakietki „Odłożone na Sklejaniu” (Doprecyzowania p. 6). Nieznany kod →
    // „na <nazwa z API>”.
    const MIEJSCOWNIK = {
        cutting: 'Wycinaniu',
        assembly: 'Składaniu',
        gluing: 'Sklejaniu',
        formatting: 'Formatowaniu',
        edges: 'Krawędziach',
        painting: 'Lakierni',
        packaging: 'Pakowaniu',
    };
    const POWODY_ODLOZENIA = {
        brak_materialu: 'brak materiału',
        awaria_maszyny: 'awaria maszyny',
        brak_miejsca: 'brak miejsca',
        czeka_na_biuro: 'czeka na biuro',
    };

    let zapisTrwa = false;

    // ── Pomocnicze ──────────────────────────────────────────────────────────

    function esc(wartosc) {
        if (wartosc === null || wartosc === undefined) return '';
        return String(wartosc).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    class Blad extends Error {
        constructor(message, status, kod, dane) {
            super(message);
            this.name = 'BladPriorytetow';
            this.status = status;
            this.kod = kod || null;
            this.dane = dane || null;
        }
    }

    function komunikatBledu(status, dane) {
        if (dane && typeof dane.message === 'string' && dane.message) return dane.message;
        if (status === 401) return 'Sesja wygasła. Zaloguj się ponownie.';
        if (status === 403) return 'Brak uprawnień do priorytetów.';
        if (status === 0) return 'Brak połączenia z serwerem.';
        return 'Błąd serwera (' + status + ').';
    }

    async function zapytanie(sciezka, opcje) {
        const o = opcje || {};
        const naglowki = { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' };
        const ustawienia = { method: o.metoda || 'GET', credentials: 'same-origin', headers: naglowki };
        if (o.dane !== undefined) {
            naglowki['Content-Type'] = 'application/json';
            ustawienia.body = JSON.stringify(o.dane);
        }
        let odp;
        try {
            odp = await fetch(API + sciezka, ustawienia);
        } catch (e) {
            throw new Blad(komunikatBledu(0, null), 0, 'brak_polaczenia');
        }
        let dane = null;
        try { dane = await odp.json(); } catch (e) { dane = null; }
        if (!odp.ok || !dane || dane.success === false) {
            const kod = dane && typeof dane.error === 'string' ? dane.error : null;
            throw new Blad(komunikatBledu(odp.status, dane), odp.status, kod, dane);
        }
        return dane;
    }

    function powiadom(tresc, typ) {
        const t = window.ProductionShared && window.ProductionShared.toastSystem;
        if (t) t.show(esc(tresc), typ, { duration: typ === 'warning' ? 8000 : 4000 });
    }

    // Zdarzenie po zapisie: {rodzaj: 'gwiazdki'|'drabina'|'stol', order_ids, gwiazdki?} (gwiazdki — nowa liczba
    // przy rodzaju 'gwiazdki', żeby słuchacze poprawili swoje wiersze bez odczytu).
    function emituj(rodzaj, orderIds, dodatki) {
        const bus = window.ProductionShared && window.ProductionShared.eventBus;
        if (bus) bus.emit('priorytety:zmiana', Object.assign({ rodzaj: rodzaj, order_ids: orderIds || [] }, dodatki));
    }

    // 'YYYY-MM-DD' → 'dd.mm.rrrr'
    function dataPl(iso) {
        if (!iso || typeof iso !== 'string' || iso.length < 10) return '';
        return iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4);
    }

    // 'YYYY-MM-DDTHH:MM:SS' → 'hh:mm dd.mm.rrrr'
    function czasPl(iso) {
        if (!iso || typeof iso !== 'string' || iso.length < 16) return '';
        return iso.slice(11, 16) + ' ' + dataPl(iso);
    }

    // Godzina odłożenia: dziś „9:40”, inny dzień „4.10 9:40”.
    function godzinaOdlozenia(iso) {
        if (!iso || typeof iso !== 'string' || iso.length < 16) return '';
        const godzina = String(Number(iso.slice(11, 13))) + ':' + iso.slice(14, 16);
        const teraz = new Date();
        const dzis = teraz.getFullYear() + '-' + String(teraz.getMonth() + 1).padStart(2, '0') + '-' +
            String(teraz.getDate()).padStart(2, '0');
        if (iso.slice(0, 10) === dzis) return godzina;
        return String(Number(iso.slice(8, 10))) + '.' + iso.slice(5, 7) + ' ' + godzina;
    }

    // ── Gwiazdki ────────────────────────────────────────────────────────────

    function liczbaGwiazdek(n) {
        const v = Number(n);
        return Number.isInteger(v) && v >= 0 && v <= 5 ? v : 0;
    }

    function opisGwiazdek(n) {
        const v = liczbaGwiazdek(n);
        return v === 0 ? 'bez gwiazdek' : v + ' z 5 gwiazdek';
    }

    function gwiazdkiHtml(n, opcje) {
        const v = liczbaGwiazdek(n);
        const male = opcje && opcje.male ? ' pr-gwiazdki--male' : '';
        return '<span class="pr-gwiazdki pr-gwiazdki--' + v + male + '" role="img" aria-label="' +
            esc(opisGwiazdek(v)) + '">' + '★'.repeat(v) + '☆'.repeat(5 - v) + '</span>';
    }

    let wybierakOtwarty = null;     // {element, zakoncz}

    function zamknijWybierak(wynik) {
        if (!wybierakOtwarty) return;
        const w = wybierakOtwarty;
        wybierakOtwarty = null;
        w.zakoncz(wynik);
    }

    /**
     * Dymek wyboru gwiazdek 0–5 pod kotwicą. Jeden na stronę. Strzałki ←/→ przenoszą fokus, Enter wybiera,
     * Esc i klik obok zamykają z wynikiem null. To zwykły div (nie <dialog>), więc klawisze, które obsługuje,
     * zatrzymuje (stopPropagation), żeby nie dotarły do skrótów list.
     */
    function wybierzGwiazdki(kotwica, aktualne, opcje) {
        zamknijWybierak(null);
        const obecne = liczbaGwiazdek(aktualne);
        return new Promise((rozwiaz) => {
            const dymek = document.createElement('div');
            dymek.className = 'pr-wybierak';
            dymek.setAttribute('role', 'dialog');
            dymek.setAttribute('aria-label', 'Wybierz liczbę gwiazdek');
            let html = '<div class="pr-wybierak-przyciski">';
            for (let n = 0; n <= 5; n++) {
                html += '<button type="button" class="pr-wybierak-opcja" data-pr-gwiazdki="' + n + '"' +
                    ' aria-pressed="' + (n === obecne ? 'true' : 'false') + '"' +
                    ' aria-label="' + esc(n === 0 ? 'Bez gwiazdek' : opisGwiazdek(n)) + '">' +
                    (n === 0 ? 'Bez gwiazdek' : gwiazdkiHtml(n, { male: true })) + '</button>';
            }
            html += '</div>';
            if (opcje && opcje.opis) html += '<p class="pr-wybierak-opis">' + esc(opcje.opis) + '</p>';
            dymek.innerHTML = html;
            document.body.appendChild(dymek);

            const r = kotwica.getBoundingClientRect();
            const szer = dymek.offsetWidth;
            const wys = dymek.offsetHeight;
            let lewo = Math.min(Math.max(8, r.left), window.innerWidth - szer - 8);
            let gora = r.bottom + 4;
            if (gora + wys > window.innerHeight - 8) gora = Math.max(8, r.top - wys - 4);
            dymek.style.left = Math.max(8, lewo) + 'px';
            dymek.style.top = gora + 'px';

            const opcjeEl = Array.from(dymek.querySelectorAll('.pr-wybierak-opcja'));
            const zKlawiatury = (e) => {
                const i = opcjeEl.indexOf(document.activeElement);
                if (e.key === 'Escape') {
                    e.preventDefault(); e.stopPropagation(); zamknijWybierak(null);
                } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                    e.preventDefault(); e.stopPropagation();
                    const krok = e.key === 'ArrowRight' ? 1 : -1;
                    const cel = opcjeEl[(Math.max(i, 0) + krok + opcjeEl.length) % opcjeEl.length];
                    cel.focus();
                } else if (e.key === 'Enter' || e.key === ' ') {
                    e.stopPropagation();
                } else if (e.key === 'Tab') {
                    e.preventDefault(); e.stopPropagation(); zamknijWybierak(null);
                }
            };
            const klikObok = (e) => {
                if (!dymek.contains(e.target)) zamknijWybierak(null);
            };
            // Zmiana rozmiaru okna albo przewinięcie (lista Logistyki ma własny suwak) zamyka dymek — dymek ma
            // position: fixed i stałby obok innego wiersza niż kotwica, do której zapisze wybór.
            const zamknijPrzyZmianie = () => zamknijWybierak(null);
            dymek.addEventListener('keydown', zKlawiatury);
            dymek.addEventListener('click', (e) => {
                const przycisk = e.target.closest('.pr-wybierak-opcja');
                if (przycisk) zamknijWybierak(Number(przycisk.dataset.prGwiazdki));
            });
            // Klik obok rejestrujemy w następnym obrocie pętli, żeby nie złapał kliknięcia, które otworzyło dymek.
            setTimeout(() => document.addEventListener('mousedown', klikObok, true), 0);
            window.addEventListener('resize', zamknijPrzyZmianie);
            document.addEventListener('scroll', zamknijPrzyZmianie, true);

            wybierakOtwarty = {
                element: dymek,
                zakoncz: (wynik) => {
                    document.removeEventListener('mousedown', klikObok, true);
                    window.removeEventListener('resize', zamknijPrzyZmianie);
                    document.removeEventListener('scroll', zamknijPrzyZmianie, true);
                    dymek.remove();
                    if (kotwica && document.contains(kotwica)) kotwica.focus();
                    rozwiaz(wynik);
                },
            };
            (opcjeEl[obecne] || opcjeEl[0]).focus();
        });
    }

    /**
     * Jedyny zapis gwiazdek we froncie (modal, hurt Listy produkcyjnej, kolumna ★ Logistyki). Unikalne id,
     * najwyżej LIMIT_HURTU w jednym żądaniu (bez dzielenia na partie — każda partia byłaby osobną transakcją).
     */
    async function ustawGwiazdki(orderIds, gwiazdki) {
        const ids = Array.from(new Set((orderIds || []).filter(Number.isInteger)));
        if (!ids.length) throw new Blad('Nie wybrano zamówień.', 400, 'dane_niepoprawne');
        if (ids.length > LIMIT_HURTU) {
            throw new Blad('Najwyżej ' + LIMIT_HURTU + ' zamówień naraz.', 400, 'za_duzo_zamowien');
        }
        const odp = await zapytanie('/zamowienia/gwiazdki', {
            metoda: 'PUT', dane: { order_ids: ids, gwiazdki: liczbaGwiazdek(gwiazdki) },
        });
        if (odp.przeliczenie === 'nieudane') {
            powiadom('Gwiazdki zapisane. Kolejka przeliczy się przy najbliższym przebiegu (do godziny).', 'warning');
        }
        emituj('gwiazdki', ids, { gwiazdki: liczbaGwiazdek(gwiazdki) });
        return odp;
    }

    // ── Kolejka, odłożenia, etykiety ────────────────────────────────────────

    async function pobierzKolejke() {
        const odp = await zapytanie('/kolejka');
        const mapa = new Map();
        (odp.zamowienia || []).forEach((wpis) => mapa.set(wpis.order_id, wpis));
        return mapa;
    }

    async function pobierzOdlozenia() {
        const odp = await zapytanie('/odlozenia');
        const mapa = new Map();
        (odp.odlozenia || []).forEach((o) => {
            if (!mapa.has(o.order_id)) mapa.set(o.order_id, []);
            mapa.get(o.order_id).push(o);
        });
        return mapa;
    }

    function etykietaTagu(tag) {
        return ETYKIETY_TAGOW[tag] || String(tag || '');
    }

    function naStanowisku(kod, nazwa) {
        return MIEJSCOWNIK[kod] || nazwa || kod || '';
    }

    function powodOdlozenia(o) {
        if (o.powod === 'inne') return o.notatka || 'inne';
        return POWODY_ODLOZENIA[o.powod] || o.powod || '';
    }

    // Jedna linia odłożenia (zwykły tekst): „brak materiału, 9:40, Adam Kowalski”.
    function opisOdlozenia(o) {
        return [powodOdlozenia(o), godzinaOdlozenia(o.odlozono || o.kiedy), o.pracownik]
            .filter((x) => x).join(', ');
    }

    /**
     * Tekst plakietki „Odłożone na …” dla odłożeń JEDNEGO stanowiska (Doprecyzowania p. 6): jedno odłożenie —
     * „Odłożone na Sklejaniu: brak materiału, 9:40, Adam Kowalski”, kilka — „Odłożone na Sklejaniu: 2”.
     * Zwykły tekst — wołający escapuje.
     */
    function etykietaOdlozenia(odlozenia) {
        const lista = odlozenia || [];
        if (!lista.length) return '';
        const o = lista[0];
        const na = 'Odłożone na ' + naStanowisku(o.stanowisko, o.nazwa);
        return lista.length === 1 ? na + ': ' + opisOdlozenia(o) : na + ': ' + lista.length;
    }

    // Szczegóły odłożeń (podpowiedź plakietki): każda pozycja w osobnej linii, z notatką.
    function opisOdlozen(odlozenia) {
        return (odlozenia || []).map((o) => {
            const kto = o.short_id || o.numer || '';
            const notatka = o.notatka && o.powod !== 'inne' ? ' (' + o.notatka + ')' : '';
            return (kto ? kto + ': ' : '') + opisOdlozenia(o) + notatka;
        }).join('\n');
    }

    // ── Stoły stanowisk: „Wyślij na stanowisko”, „Zdejmij ze stołu” (spec 5.7) ──

    // Lustro ustawienia.STANOWISKA_BEZ_STOLU: Lakiernia pracuje z listy, nie ma stołu (spec, ustalenie 15).
    const STANOWISKA_BEZ_STOLU = ['painting'];
    // Kafel zdjęty ze stołu wraca do kolejki; doróbka i kafel pierwszy w kolejce wejdą znowu przy najbliższym
    // dopełnieniu stołu (decyzja centrali, pytanie 9 raportu K3 — bez zmiany zachowania serwera).
    const WROCI_PRZY_DOPELNIENIU = 'Kafel wróci przy następnym dopełnieniu stołu.';
    // Komunikaty kodów błędów końcówek stołu (raport K3). Funkcja dostaje (nazwa stanowiska, numer zamówienia).
    const KOMUNIKATY_STOLU = {
        dane_niepoprawne: () => 'Nie udało się odczytać kafla albo zamówienia. Odśwież okno i spróbuj jeszcze raz.',
        stanowisko_nieznane: () => 'Nie ma takiego stanowiska.',
        zamowienie_nieznane: () => 'Nie ma takiego zamówienia.',
        brak_na_stanowisku: (na, numer) => 'Zamówienie ' + (numer || '') + ' nie ma teraz żadnej pozycji na ' + na +
            '. Biuro nie przeskakuje procesu.',
        stanowisko_bez_stolu: (na) => 'Na ' + na + ' nie ma stołu: stanowisko pracuje z pełnej listy.',
        brak_kafla: () => 'Tego kafla nie ma już na stole (ktoś go właśnie zamknął albo zdjął).',
        blad_serwera: () => 'Nie udało się zapisać zmian. Spróbuj ponownie za chwilę.',
    };

    /** Komunikat po polsku dla błędu akcji stołu (zwykły tekst — wołający wstawia go przez textContent). */
    function komunikatStolu(blad, kod, numer) {
        const tekst = blad && KOMUNIKATY_STOLU[blad.kod];
        return tekst ? tekst(naStanowisku(kod), numer) : ((blad && blad.message) || 'Nieznany błąd.');
    }

    /** Jedyne wywołanie „Wyślij na stanowisko” we froncie: kafle zamówienia na stół stanowiska ponad K. */
    async function wyslijNaStanowisko(kod, orderId) {
        const odp = await zapytanie('/stoly/' + encodeURIComponent(kod) + '/wyslij', {
            metoda: 'POST', dane: { order_id: orderId },
        });
        emituj('stol', [orderId]);
        return odp;
    }

    /**
     * Jedyne wywołanie „Zdejmij ze stołu” we froncie. Po zdjęciu sprawdza pierwszy kafel kolejki stanowiska:
     * jeśli to ten sam kafel, `wroci` = true (wejdzie z powrotem przy najbliższym dopełnieniu stołu).
     */
    async function zdejmijZeStolu(kod, unitKey) {
        const odp = await zapytanie('/stoly/' + encodeURIComponent(kod) + '/zdejmij', {
            metoda: 'POST', dane: { unit_key: unitKey },
        });
        let wroci = false;
        try {
            const kolejka = await zapytanie('/kolejka?stanowisko=' + encodeURIComponent(kod) + '&limit=1');
            const pierwszy = (kolejka.kafle || [])[0];
            if (pierwszy) {
                wroci = pierwszy.product_id != null ? unitKey === 'p:' + pierwszy.product_id
                    : unitKey === 'o:' + pierwszy.order_id;
            }
        } catch (e) {
            wroci = false;      // podgląd kolejki to tylko opis — zdjęcie się udało
        }
        emituj('stol', odp.order_id != null ? [odp.order_id] : []);
        return { odp: odp, wroci: wroci };
    }

    // ── Modal priorytetu ────────────────────────────────────────────────────

    // Akcje logu pokazywane w historii modalu (etykiety po polsku; spec 5.3, 5.7, 5.8).
    const AKCJE_HISTORII = {
        gwiazdki: 'Gwiazdki',
        wyslanie: 'Wysłanie na stół',
        zdjecie: 'Zdjęcie ze stołu',
        odlozenie: 'Odłożenie',
        odlozenie_zamkniete: 'Zamknięcie odłożonego',
        start_stolow: 'Start stołów',
    };
    const ZRODLA_KAFLA = { biuro: 'wysłane przez biuro', start: 'rozpoczęte przed startem', dorobka: 'doróbka' };
    const LIMIT_HISTORII = 20;

    let modalPriorytetu = null;
    // stoly: null (nie czytano), Map(kod → {stol: [], odlozone: []}) albo 'blad'.
    let stanModalu = { orderId: null, dane: null, stoly: null, opener: null, doPrzywrocenia: false, numerZadania: 0 };

    function dialogPriorytetu() {
        if (modalPriorytetu) return modalPriorytetu;
        const d = document.createElement('dialog');
        d.className = 'pr-modal';
        d.id = 'pr-modal-priorytetu';
        d.setAttribute('aria-labelledby', 'pr-modal-priorytetu-tytul');
        d.innerHTML =
            '<div class="pr-modal-naglowek">' +
            '<h2 class="pr-modal-tytul" id="pr-modal-priorytetu-tytul">Priorytet zamówienia</h2>' +
            '<button type="button" class="pr-modal-zamknij" data-pr-akcja="zamknij" aria-label="Zamknij">×</button>' +
            '</div>' +
            '<p class="pr-modal-komunikat" role="alert" hidden></p>' +
            '<p class="pr-modal-info" role="status" hidden></p>' +
            '<div class="pr-modal-tresc"></div>';
        d.addEventListener('click', (e) => {
            const przycisk = e.target.closest('[data-pr-akcja]');
            if (!przycisk || !d.contains(przycisk)) return;
            obsluzAkcjeModalu(przycisk);
        });
        // Esc: zamykamy sami i od razu oddajemy fokus — `close` przychodzi dopiero z następną klatką animacji
        // (w karcie w tle wcale), więc samo `close` nie wystarcza.
        d.addEventListener('cancel', (e) => {
            e.preventDefault();
            zamknijModalPriorytetu();
        });
        d.addEventListener('close', przywrocFokusModalu);
        document.body.appendChild(d);
        modalPriorytetu = d;
        return d;
    }

    function przywrocFokusModalu() {
        if (!stanModalu.doPrzywrocenia) return;
        stanModalu.doPrzywrocenia = false;
        const opener = stanModalu.opener;
        stanModalu.opener = null;
        if (opener && document.contains(opener)) {
            opener.focus();
            return;
        }
        // Lista przerysowała karty po zapisie (zdarzenie 'priorytety:zmiana') i przycisk, który otworzył okno,
        // zniknął — fokus na przycisk okna tej samej karty zamówienia, nie na body.
        if (stanModalu.orderId == null) return;
        const zastepca = document.querySelector('[data-order-id="' + stanModalu.orderId + '"] [aria-haspopup="dialog"]');
        if (zastepca) zastepca.focus();
    }

    function zamknijModalPriorytetu() {
        if (modalPriorytetu && modalPriorytetu.open) modalPriorytetu.close();
        przywrocFokusModalu();
    }

    function komunikatModalu(tresc) {
        const el = dialogPriorytetu().querySelector('.pr-modal-komunikat');
        el.textContent = tresc || '';
        el.hidden = !tresc;
    }

    function infoModalu(tresc) {
        const el = dialogPriorytetu().querySelector('.pr-modal-info');
        el.textContent = tresc || '';
        el.hidden = !tresc;
    }

    function sekcja(tytul, html) {
        return '<section class="pr-sekcja"><h3 class="pr-sekcja-tytul">' + tytul + '</h3>' + html + '</section>';
    }

    function htmlGwiazdekModalu(d) {
        const obecne = liczbaGwiazdek(d.gwiazdki);
        let html = '<div class="pr-gwiazdki-wybor" role="group" aria-label="Gwiazdki zamówienia">';
        for (let n = 1; n <= 5; n++) {
            html += '<button type="button" class="pr-gwiazdka' + (n <= obecne ? ' is-pelna' : '') + '"' +
                ' data-pr-akcja="gwiazdki" data-pr-gwiazdki="' + n + '"' +
                ' aria-pressed="' + (n === obecne ? 'true' : 'false') + '"' +
                ' aria-label="' + esc(opisGwiazdek(n)) + '">' + (n <= obecne ? '★' : '☆') + '</button>';
        }
        html += '<button type="button" class="pr-bez-gwiazdek" data-pr-akcja="gwiazdki" data-pr-gwiazdki="0"' +
            ' aria-pressed="' + (obecne === 0 ? 'true' : 'false') + '">Bez gwiazdek</button></div>';
        const u = d.gwiazdki_ustawione;
        html += '<p class="pr-opis">' + (u ? 'Ustawił: ' + esc(u.kto || 'nieznany użytkownik') + ', ' +
            esc(czasPl(u.kiedy)) : 'Nikt jeszcze nie ustawiał') + '</p>';
        return html;
    }

    function htmlSzczebla(d) {
        if (d.aktywne === false) {
            return '<p class="pr-opis">Zamówienie jest poza kolejką produkcji (spakowane, wstrzymane albo ' +
                'anulowane).</p>';
        }
        const s = d.szczebel;
        let html = '<p>';
        if (s) html += esc(s.etykieta) + ', ' + esc('szczebel ' + s.pozycja + ' z ' + s.z);
        else html += 'Szczebel nieznany';
        html += '</p><p class="pr-opis">Miejsce w kolejce: <strong>' + esc(d.ranga != null ? d.ranga : '—') +
            '</strong></p>';
        return html;
    }

    function htmlTerminu(d) {
        let html = '<p>' + (d.termin ? esc(dataPl(d.termin)) : 'brak terminu');
        (d.tagi || []).forEach((tag) => {
            html += ' <span class="pr-tag pr-tag--' + esc(tag) + '">' + esc(etykietaTagu(tag)) + '</span>';
        });
        html += '</p><p class="pr-opis">Trasa: ';
        if (d.trasa) html += esc(d.trasa.nazwa) + (d.trasa.date_from ? ', od ' + esc(dataPl(d.trasa.date_from)) : '');
        else html += 'bez trasy';
        return html + '</p>';
    }

    /** Czy modal potrzebuje kluczy kafli z GET /stoly (coś leży na stole albo jest odłożone). */
    function trzebaStolow(d) {
        return (d.stanowiska || []).some((s) => (s.na_stole || []).length || (s.odlozone || []).length);
    }

    /** Kafle tego zamówienia na stołach stanowisk (klucz kafla, źródło, doróbka) — tylko odczyt GET /stoly. */
    async function wczytajStoly(orderId) {
        try {
            const odp = await zapytanie('/stoly');
            const mapa = new Map();
            (odp.stanowiska || []).forEach((s) => {
                mapa.set(s.stanowisko, {
                    stol: (s.stol || []).filter((k) => k.order_id === orderId),
                    odlozone: (s.odlozone || []).filter((k) => k.order_id === orderId),
                });
            });
            return mapa;
        } catch (e) {
            console.warn('[Priorytety] Stoły stanowisk niedostępne:', e);
            return 'blad';
        }
    }

    // Kafel stołu z przyciskiem „Zdejmij ze stołu”; doróbka dostaje opis, że wróci przy dopełnieniu.
    function htmlKaflaStolu(kod, k) {
        const oznaczenie = k.short_id || k.numer || k.unit_key;
        const zrodlo = ZRODLA_KAFLA[k.zrodlo] || '';
        // `wroci_przy_dopelnieniu` liczy GET /stoly (doróbka albo kafel, który wejdzie przy dopełnieniu stołu).
        const wroci = k.wroci_przy_dopelnieniu || k.dorobka || k.zrodlo === 'dorobka';
        return '<span class="pr-kafel">' + esc(oznaczenie) +
            (zrodlo ? ' <span class="pr-znacznik pr-znacznik--zrodlo">' + esc(zrodlo) + '</span>' : '') +
            ' <button type="button" class="pr-przycisk pr-przycisk--maly" data-pr-akcja="zdejmij"' +
            ' data-stanowisko="' + esc(kod) + '" data-unit-key="' + esc(k.unit_key) + '"' +
            ' aria-label="' + esc('Zdejmij ze stołu: ' + oznaczenie) + '">Zdejmij ze stołu</button>' +
            (wroci ? ' <span class="pr-opis pr-opis--maly">' + esc(WROCI_PRZY_DOPELNIENIU) + '</span>' : '') +
            '</span>';
    }

    function htmlGdzieLezy(d) {
        const stanowiska = d.stanowiska || [];
        if (!stanowiska.length) return '<p class="pr-opis">Żadna pozycja nie czeka na stanowisku.</p>';
        const stoly = stanModalu.stoly instanceof Map ? stanModalu.stoly : null;
        let html = '<div class="pr-tabela-zawijaj"><table class="pr-tabela"><thead><tr>' +
            '<th scope="col">Stanowisko</th><th scope="col">Pozycji</th><th scope="col">Na stole</th>' +
            '<th scope="col">Odłożone</th><th scope="col">W kolejce</th><th scope="col">Stół</th>' +
            '</tr></thead><tbody>';
        stanowiska.forEach((s) => {
            const kod = s.stanowisko;
            const kafle = stoly && stoly.get(kod) ? stoly.get(kod).stol : null;
            let naStole;
            if (kafle && kafle.length) naStole = kafle.map((k) => htmlKaflaStolu(kod, k)).join('');
            else if ((s.na_stole || []).length) naStole = (s.na_stole || []).map((x) => esc(x)).join(', ');
            else naStole = '—';
            const wKolejce = s.w_kolejce ? esc(s.w_kolejce.miejsce + ' z ' + s.w_kolejce.z) : '—';
            const akcja = STANOWISKA_BEZ_STOLU.includes(s.stanowisko)
                ? '<span class="pr-opis">bez stołu (pracuje z listy)</span>'
                : '<button type="button" class="pr-przycisk pr-przycisk--maly" data-pr-akcja="wyslij"' +
                  ' data-stanowisko="' + esc(kod) + '">Wyślij na stanowisko</button>';
            html += '<tr><th scope="row">' + esc(s.nazwa) +
                (s.niekompletne ? ' <span class="pr-znacznik">niekompletne</span>' : '') + '</th>' +
                '<td>' + esc(s.pozycji) + '</td><td>' + naStole + '</td>' +
                '<td>' + esc((s.odlozone || []).length) + '</td><td>' + wKolejce + '</td>' +
                '<td>' + akcja + '</td></tr>';
        });
        html += '</tbody></table></div>';
        if (stanModalu.stoly === 'blad') {
            html += '<p class="pr-opis">Nie udało się wczytać stołów stanowisk, więc „Zdejmij ze stołu” jest ' +
                'chwilowo niedostępne. Zamknij i otwórz okno ponownie.</p>';
        }
        return html;
    }

    function htmlOdlozen(d) {
        const wiersze = [];
        const stoly = stanModalu.stoly instanceof Map ? stanModalu.stoly : null;
        (d.stanowiska || []).forEach((s) => {
            const kod = s.stanowisko;
            const kafle = stoly && stoly.get(kod) ? stoly.get(kod).odlozone : null;
            // Z GET /stoly (z kluczem kafla, więc z „Zdejmij”), a gdy go nie ma — z danych modalu.
            const lista = kafle && kafle.length ? kafle : (s.odlozone || []);
            lista.forEach((o) => {
                const notatka = o.notatka && o.powod !== 'inne' ? o.notatka : '';
                const tekst = [powodOdlozenia(o), notatka, czasPl(o.odlozono || o.kiedy), o.pracownik]
                    .filter((x) => x).join(', ');
                const pozycja = o.short_id ? ' (' + o.short_id + ')' : '';
                wiersze.push('<li>' + esc(s.nazwa) + esc(pozycja) + ': ' + esc(tekst) +
                    (o.unit_key ? ' ' + htmlKaflaStolu(kod, o) : '') + '</li>');
            });
        });
        return wiersze.length ? '<ul class="pr-lista">' + wiersze.join('') + '</ul>' : '';
    }

    function opisWpisuHistorii(h) {
        const etykieta = AKCJE_HISTORII[h.akcja] || h.akcja;
        if (h.akcja === 'gwiazdki') return (h.stare != null ? h.stare : '0') + ' → ' + (h.nowe != null ? h.nowe : '0');
        const na = h.stanowisko ? ' (na ' + naStanowisku(h.stanowisko) + ')' : '';
        if (h.akcja === 'odlozenie') return etykieta + na + ': ' + powodOdlozenia({ powod: h.powod, notatka: h.notatka });
        if (h.akcja === 'start_stolow') return etykieta + na + ': ' + (h.nowe || '0');
        return etykieta + na;
    }

    function htmlHistorii(d) {
        const wpisy = (d.historia || []).filter((h) => Object.prototype.hasOwnProperty.call(AKCJE_HISTORII, h.akcja))
            .slice(0, LIMIT_HISTORII);
        if (!wpisy.length) return '<p class="pr-opis">Brak wpisów</p>';
        return '<ul class="pr-lista pr-historia">' + wpisy.map((h) => '<li>' + esc(opisWpisuHistorii(h)) +
            ' · ' + esc(h.kto || '—') + ' · ' + esc(czasPl(h.kiedy)) + '</li>').join('') + '</ul>';
    }

    function renderujModal() {
        const d = stanModalu.dane;
        const dialog = dialogPriorytetu();
        const z = d.zamowienie || {};
        const klient = z.klient;
        dialog.querySelector('.pr-modal-tytul').innerHTML = 'Priorytet zamówienia ' + esc(z.numer) +
            (klient ? ' <span class="pr-modal-klient">' + esc(klient) + '</span>' : '');
        const odlozenia = htmlOdlozen(d);
        dialog.querySelector('.pr-modal-tresc').innerHTML =
            sekcja('Gwiazdki', htmlGwiazdekModalu(d)) +
            sekcja('Szczebel', htmlSzczebla(d)) +
            sekcja('Termin', htmlTerminu(d)) +
            sekcja('Gdzie leży', htmlGdzieLezy(d)) +
            (odlozenia ? sekcja('Odłożenia', odlozenia) : '') +
            sekcja('Historia', htmlHistorii(d));
        oznaczZapisModalu(zapisTrwa);
    }

    function oznaczZapisModalu(czeka) {
        if (!modalPriorytetu) return;
        modalPriorytetu.querySelectorAll('[data-pr-akcja]:not([data-pr-akcja="zamknij"])').forEach((el) => {
            if (czeka) el.setAttribute('aria-disabled', 'true');
            else el.removeAttribute('aria-disabled');
        });
    }

    async function wczytajModal(orderId) {
        const numer = ++stanModalu.numerZadania;
        try {
            const dane = await zapytanie('/zamowienia/' + encodeURIComponent(orderId) + '/priorytet');
            const stoly = trzebaStolow(dane) ? await wczytajStoly(orderId) : null;
            if (numer !== stanModalu.numerZadania) return false;
            stanModalu.dane = dane;
            stanModalu.stoly = stoly;
            renderujModal();
            return true;
        } catch (e) {
            if (numer !== stanModalu.numerZadania) return false;
            komunikatModalu(e.status === 404 ? 'Nie ma takiego zamówienia.' : e.message);
            return false;
        }
    }

    /** Modal priorytetu zamówienia: gwiazdki, szczebel, termin, gdzie leży, odłożenia, historia (spec 7.1). */
    async function otworzModalPriorytetu(orderId) {
        const id = Number(orderId);
        if (!Number.isInteger(id)) return;
        const dialog = dialogPriorytetu();
        // Okno już otwarte (np. drugie wywołanie) — zostaje pierwotny element do powrotu fokusu.
        const opener = dialog.open ? stanModalu.opener : document.activeElement;
        stanModalu = {
            orderId: id, dane: null, stoly: null, opener: opener, doPrzywrocenia: true,
            numerZadania: stanModalu.numerZadania,
        };
        komunikatModalu('');
        infoModalu('');
        dialog.querySelector('.pr-modal-tytul').textContent = 'Priorytet zamówienia';
        dialog.querySelector('.pr-modal-tresc').innerHTML = '<p class="pr-opis">Wczytywanie…</p>';
        if (!dialog.open) dialog.showModal();
        if (await wczytajModal(id)) {
            const aktualna = dialog.querySelector('.pr-gwiazdki-wybor [aria-pressed="true"]');
            if (aktualna) aktualna.focus();
        }
    }

    async function zapiszGwiazdkiModalu(n) {
        if (zapisTrwa) return;
        const d = stanModalu.dane;
        if (!d || liczbaGwiazdek(d.gwiazdki) === n) return;
        zapisTrwa = true;
        oznaczZapisModalu(true);
        komunikatModalu('');
        infoModalu('');
        try {
            await ustawGwiazdki([stanModalu.orderId], n);
            await wczytajModal(stanModalu.orderId);
            const aktualna = modalPriorytetu.querySelector('.pr-gwiazdki-wybor [aria-pressed="true"]');
            if (aktualna) aktualna.focus();
        } catch (e) {
            komunikatModalu(e.message);
        } finally {
            zapisTrwa = false;
            oznaczZapisModalu(false);
        }
    }

    function nazwaStanowiskaModalu(kod) {
        const s = ((stanModalu.dane && stanModalu.dane.stanowiska) || []).find((x) => x.stanowisko === kod);
        return s ? s.nazwa : kod;
    }

    // Opis wyniku „Wyślij” (zwykły tekst do textContent).
    function opisWyslania(odp, kod) {
        const nazwa = nazwaStanowiskaModalu(kod);
        if (odp.wynik === 'juz_na_stole') return 'Zamówienie już leży na stole stanowiska ' + nazwa + '.';
        const wyslane = (odp.wyslane || []).length;
        const przywrocone = (odp.przywrocone || []).length;
        let tekst = 'Na stół stanowiska ' + nazwa + ' wysłano kafli: ' + (wyslane + przywrocone) + '.';
        if (przywrocone) tekst += ' W tym przywrócone z odłożonych: ' + przywrocone + '.';
        return tekst;
    }

    /** „Wyślij na stanowisko” i „Zdejmij ze stołu” z modalu — jeden zapis naraz, potem odczyt modalu od nowa. */
    async function akcjaStolu(przycisk) {
        if (zapisTrwa) return;
        const akcja = przycisk.dataset.prAkcja;
        const kod = przycisk.dataset.stanowisko;
        const numer = stanModalu.dane && stanModalu.dane.zamowienie ? stanModalu.dane.zamowienie.numer : '';
        zapisTrwa = true;
        oznaczZapisModalu(true);
        komunikatModalu('');
        infoModalu('');
        try {
            let info;
            if (akcja === 'wyslij') {
                info = opisWyslania(await wyslijNaStanowisko(kod, stanModalu.orderId), kod);
            } else {
                const wynik = await zdejmijZeStolu(kod, przycisk.dataset.unitKey);
                info = 'Zdjęto ze stołu stanowiska ' + nazwaStanowiskaModalu(kod) + '. ' +
                    (wynik.wroci ? WROCI_PRZY_DOPELNIENIU : 'Kafel wrócił do kolejki stanowiska.');
            }
            await wczytajModal(stanModalu.orderId);
            infoModalu(info);
            // Kliknięty przycisk zniknął przy przerysowaniu — fokus na „Wyślij” tego stanowiska, nie na body.
            const wyslij = Array.from(modalPriorytetu.querySelectorAll('[data-pr-akcja="wyslij"]'))
                .find((el) => el.dataset.stanowisko === kod);
            if (wyslij) wyslij.focus();
        } catch (e) {
            komunikatModalu(komunikatStolu(e, kod, numer));
            if (e.kod === 'brak_kafla') await wczytajModal(stanModalu.orderId);
        } finally {
            zapisTrwa = false;
            oznaczZapisModalu(false);
        }
    }

    function obsluzAkcjeModalu(przycisk) {
        const akcja = przycisk.dataset.prAkcja;
        if (akcja === 'zamknij') { zamknijModalPriorytetu(); return; }
        if (przycisk.getAttribute('aria-disabled') === 'true') return;
        if (akcja === 'gwiazdki') zapiszGwiazdkiModalu(Number(przycisk.dataset.prGwiazdki));
        else if (akcja === 'wyslij' || akcja === 'zdejmij') akcjaStolu(przycisk);
    }

    // ── Drabina priorytetów ─────────────────────────────────────────────────
    // Szczeble gwiazdek są stałe, tagi i trasy ruchome (spec 3.1). Strzałka ↑/↓ wysyła pozycję sąsiada w WIDOCZNEJ
    // drabinie (±1) razem z `oczekiwane` — id widocznych szczebli z ostatniego odczytu; inna drabina na serwerze →
    // 409 `drabina_zmieniona` i odczyt od nowa (Doprecyzowania p. 8). Przeciąganie wierszy pominięte (opcja planu).

    const IKONY_SZCZEBLI = { gwiazdki: 'fa-star', tag: 'fa-tag', trasa: 'fa-truck' };
    const KOMUNIKAT_DRABINA_ZMIENIONA = 'Drabina zmieniła się w międzyczasie. Sprawdź i spróbuj jeszcze raz.';

    let modalDrabiny = null;
    let stanDrabiny = { szczeble: [], ostrzezenia: [], uzupelniono: 0 };
    let openerDrabiny = null;

    function dialogDrabiny() {
        if (modalDrabiny) return modalDrabiny;
        const d = document.createElement('dialog');
        d.className = 'pr-modal pr-modal--drabina';
        d.id = 'pr-modal-drabiny';
        d.setAttribute('aria-labelledby', 'pr-modal-drabiny-tytul');
        d.innerHTML =
            '<div class="pr-modal-naglowek">' +
            '<h2 class="pr-modal-tytul" id="pr-modal-drabiny-tytul">Drabina priorytetów</h2>' +
            '<button type="button" class="pr-modal-zamknij" data-pr-drabina="zamknij" aria-label="Zamknij">×</button>' +
            '</div>' +
            '<p class="pr-modal-komunikat" role="alert" hidden></p>' +
            '<div class="pr-modal-tresc">' +
            '<p class="pr-opis">Zamówienie z trasy bierze szczebel trasy. Zamówienie bez trasy bierze najwyższy ze ' +
            'swoich szczebli (gwiazdki, tagi).</p>' +
            '<div class="pr-drabina-uwagi"></div>' +
            '<ol class="pr-drabina"></ol>' +
            '</div>';
        d.addEventListener('click', obsluzKlikDrabiny);
        // Esc: zamykamy sami i od razu oddajemy fokus (jak w modalu priorytetu — `close` bywa spóźnione).
        d.addEventListener('cancel', (e) => {
            e.preventDefault();
            zamknijDrabine();
        });
        d.addEventListener('close', przywrocFokusDrabiny);
        document.body.appendChild(d);
        modalDrabiny = d;
        return d;
    }

    function przywrocFokusDrabiny() {
        const opener = openerDrabiny;
        openerDrabiny = null;
        if (opener && document.contains(opener)) opener.focus();
    }

    function zamknijDrabine() {
        if (modalDrabiny && modalDrabiny.open) modalDrabiny.close();
        przywrocFokusDrabiny();
    }

    function komunikatDrabiny(tresc) {
        const el = dialogDrabiny().querySelector('.pr-modal-komunikat');
        el.textContent = tresc || '';
        el.hidden = !tresc;
    }

    function wierszDrabiny(s, i, n) {
        const nazwa = s.etykieta;
        const pusty = s.w_produkcji === 0 ? ' pr-szczebel--pusty' : '';
        const tresc = s.rodzaj === 'gwiazdki' ? gwiazdkiHtml(s.gwiazdki) : esc(nazwa);
        let html = '<li class="pr-szczebel pr-szczebel--' + esc(s.rodzaj) + pusty + '" data-pr-szczebel="' +
            esc(s.id) + '">' +
            '<span class="pr-szczebel-pozycja">' + esc(i + 1) + '</span>' +
            '<i class="fas ' + (IKONY_SZCZEBLI[s.rodzaj] || 'fa-tag') + ' pr-szczebel-ikona" aria-hidden="true"></i>' +
            '<span class="pr-szczebel-nazwa">' + tresc;
        if (s.trasa) {
            const od = dataPl(s.trasa.date_from);
            const doDnia = dataPl(s.trasa.date_to);
            html += ' <span class="pr-szczebel-daty">' + esc(od + (doDnia && doDnia !== od ? '–' + doDnia : '')) +
                '</span> <span class="pr-trasa-status pr-trasa-status--' + esc(s.trasa.status) + '">' +
                esc(s.trasa.status) + '</span>';
        }
        html += '</span><span class="pr-licznik">' + esc(s.w_produkcji + ' w produkcji') + '</span>';
        if (s.ruchomy) {
            html += '<span class="pr-strzalki">' +
                '<button type="button" class="pr-strzalka" data-pr-drabina="gora" data-pr-id="' + esc(s.id) + '"' +
                (i === 0 ? ' disabled' : '') + ' aria-label="' + esc('Przesuń wyżej: ' + nazwa) + '">↑</button>' +
                '<button type="button" class="pr-strzalka" data-pr-drabina="dol" data-pr-id="' + esc(s.id) + '"' +
                (i === n - 1 ? ' disabled' : '') + ' aria-label="' + esc('Przesuń niżej: ' + nazwa) + '">↓</button>' +
                '</span>';
        } else {
            html += '<span class="pr-staly" title="Szczebel gwiazdek jest stały">' +
                '<i class="fas fa-lock" aria-hidden="true"></i> stały</span>';
        }
        return html + '</li>';
    }

    function renderujDrabine() {
        const d = dialogDrabiny();
        const szczeble = stanDrabiny.szczeble || [];
        d.querySelector('.pr-drabina').innerHTML = szczeble.map((s, i) => wierszDrabiny(s, i, szczeble.length)).join('');
        let uwagi = '';
        const ostrzezenia = stanDrabiny.ostrzezenia || [];
        if (stanDrabiny.uzupelniono > 0) {
            uwagi += '<p class="pr-modal-info" role="status">' +
                esc('Dopisano brakujące szczeble drabiny: ' + stanDrabiny.uzupelniono + '.') + '</p>';
        }
        if (ostrzezenia.length) {
            uwagi += '<ul class="pr-drabina-ostrzezenia" role="status">' +
                ostrzezenia.map((o) => '<li>' + esc(o.message) + '</li>').join('') + '</ul>';
        }
        d.querySelector('.pr-drabina-uwagi').innerHTML = uwagi;
        oznaczCzekanie(zapisTrwa);
    }

    function oznaczCzekanie(czeka) {
        if (!modalDrabiny) return;
        modalDrabiny.querySelectorAll('.pr-strzalka').forEach((el) => {
            if (czeka) el.setAttribute('aria-disabled', 'true');
            else el.removeAttribute('aria-disabled');
        });
    }

    // Fokus po przerysowaniu na tę samą strzałkę tego samego szczebla; na krańcu (strzałka wyłączona) na drugą.
    function przywrocFokus(id, kierunek) {
        if (!modalDrabiny) return;
        const strzalki = Array.from(modalDrabiny.querySelectorAll('.pr-strzalka'))
            .filter((el) => Number(el.dataset.prId) === id);
        const ta = strzalki.find((el) => el.dataset.prDrabina === (kierunek < 0 ? 'gora' : 'dol'));
        const druga = strzalki.find((el) => el !== ta);
        const cel = ta && !ta.disabled ? ta : druga;
        if (cel) cel.focus();
    }

    async function wczytajDrabine() {
        try {
            stanDrabiny = await zapytanie('/drabina');
            renderujDrabine();
            return true;
        } catch (e) {
            komunikatDrabiny(e.message);
            return false;
        }
    }

    async function przesunSzczebel(id, kierunek) {
        if (zapisTrwa) return;
        const szczeble = stanDrabiny.szczeble || [];
        const i = szczeble.findIndex((s) => s.id === id);
        const cel = i + 1 + kierunek;                // pozycja 1-based w widocznej drabinie
        if (i < 0 || cel < 1 || cel > szczeble.length) return;
        zapisTrwa = true;
        oznaczCzekanie(true);
        komunikatDrabiny('');
        try {
            const odp = await zapytanie('/drabina/kolejnosc', {
                metoda: 'PUT',
                dane: { szczebel_id: id, pozycja: cel, oczekiwane: stanDrabiny.szczeble.map((s) => s.id) },
            });
            stanDrabiny = odp;
            renderujDrabine();
            przywrocFokus(id, kierunek);
            if (odp.przeliczenie === 'nieudane') {
                powiadom('Kolejność zapisana. Kolejka przeliczy się przy najbliższym przebiegu (do godziny).', 'warning');
            }
            emituj('drabina', []);
        } catch (e) {
            if (e.kod === 'drabina_zmieniona') {
                await wczytajDrabine();
                przywrocFokus(id, kierunek);
                komunikatDrabiny(KOMUNIKAT_DRABINA_ZMIENIONA);
            } else {
                komunikatDrabiny(e.message);
            }
        } finally {
            zapisTrwa = false;
            oznaczCzekanie(false);
        }
    }

    function obsluzKlikDrabiny(e) {
        const przycisk = e.target.closest('[data-pr-drabina]');
        if (!przycisk) return;
        const akcja = przycisk.dataset.prDrabina;
        if (akcja === 'zamknij') { zamknijDrabine(); return; }
        if (przycisk.disabled || przycisk.getAttribute('aria-disabled') === 'true') return;
        przesunSzczebel(Number(przycisk.dataset.prId), akcja === 'gora' ? -1 : 1);
    }

    /** Modal „Drabina priorytetów” (spec 7.1): szczeble z licznikami, strzałki ↑↓, ostrzeżenie o datach tras. */
    async function otworzDrabine() {
        const d = dialogDrabiny();
        if (!d.open) openerDrabiny = document.activeElement;
        komunikatDrabiny('');
        d.querySelector('.pr-drabina').innerHTML = '<li class="pr-opis">Wczytywanie…</li>';
        d.querySelector('.pr-drabina-uwagi').innerHTML = '';
        if (!d.open) d.showModal();
        if (await wczytajDrabine()) {
            const pierwsza = d.querySelector('.pr-strzalka:not([disabled])');
            if (pierwsza) pierwsza.focus();
        }
    }

    // ── Okno potwierdzenia (K4-poprawka-1) ──────────────────────────────────

    let oknoPotwierdzenia = null;

    /**
     * Okno potwierdzenia akcji hurtowej: natywny <dialog> z „Anuluj” i przyciskiem zatwierdzającym. Fokus startuje
     * na „Anuluj”, więc Enter wciśnięty jeszcze w wybieraku gwiazdek (albo przytrzymany) zamyka okno bez zapisu —
     * zatwierdzić można tylko klikiem albo Tab i Enter. Esc i „Anuluj” = odmowa; fokus wraca od razu, bez czekania
     * na `close` (w karcie w tle nie przychodzi). Treść tylko przez textContent. Zwraca Promise<boolean>.
     * opcje: {tytul, tresc, zatwierdz} — zatwierdz to napis przycisku zatwierdzającego.
     */
    function potwierdz(opcje) {
        const o = opcje || {};
        if (oknoPotwierdzenia) oknoPotwierdzenia.zakoncz(false);
        const opener = document.activeElement;
        const d = document.createElement('dialog');
        d.className = 'pr-modal pr-modal--potwierdzenie';
        d.setAttribute('aria-labelledby', 'pr-potwierdzenie-tytul');
        d.setAttribute('aria-describedby', 'pr-potwierdzenie-tresc');
        d.innerHTML =
            '<div class="pr-modal-naglowek">' +
            '<h2 class="pr-modal-tytul" id="pr-potwierdzenie-tytul"></h2>' +
            '</div>' +
            '<div class="pr-modal-tresc">' +
            '<p class="pr-potwierdzenie-tresc" id="pr-potwierdzenie-tresc"></p>' +
            '<div class="pr-potwierdzenie-przyciski">' +
            '<button type="button" class="pr-przycisk" data-pr-potwierdz="nie">Anuluj</button>' +
            '<button type="button" class="pr-przycisk pr-przycisk--glowny" data-pr-potwierdz="tak"></button>' +
            '</div>' +
            '</div>';
        d.querySelector('.pr-modal-tytul').textContent = o.tytul || 'Potwierdź';
        d.querySelector('.pr-potwierdzenie-tresc').textContent = o.tresc || '';
        d.querySelector('[data-pr-potwierdz="tak"]').textContent = o.zatwierdz || 'Zatwierdź';
        document.body.appendChild(d);
        return new Promise((rozwiaz) => {
            const stan = {};
            const zakoncz = (wynik) => {
                if (oknoPotwierdzenia !== stan) return;
                oknoPotwierdzenia = null;
                if (d.open) d.close();
                d.remove();
                if (opener && document.contains(opener) && opener.focus) opener.focus();
                rozwiaz(wynik);
            };
            stan.zakoncz = zakoncz;
            oknoPotwierdzenia = stan;
            d.addEventListener('cancel', (e) => {
                e.preventDefault();
                zakoncz(false);
            });
            d.addEventListener('click', (e) => {
                const p = e.target.closest('[data-pr-potwierdz]');
                if (p) zakoncz(p.dataset.prPotwierdz === 'tak');
            });
            d.showModal();
            d.querySelector('[data-pr-potwierdz="nie"]').focus();
        });
    }

    // ── Eksport ─────────────────────────────────────────────────────────────

    window.Priorytety = Object.freeze({
        API: API,
        LIMIT_HURTU: 500,
        Blad: Blad,
        zapytanie: zapytanie,
        esc: esc,
        gwiazdkiHtml: gwiazdkiHtml,
        opisGwiazdek: opisGwiazdek,
        wybierzGwiazdki: wybierzGwiazdki,
        ustawGwiazdki: ustawGwiazdki,
        pobierzKolejke: pobierzKolejke,
        pobierzOdlozenia: pobierzOdlozenia,
        etykietaOdlozenia: etykietaOdlozenia,
        opisOdlozen: opisOdlozen,
        etykietaTagu: etykietaTagu,
        naStanowisku: naStanowisku,
        dataPl: dataPl,
        otworzModalPriorytetu: otworzModalPriorytetu,
        otworzDrabine: otworzDrabine,
        wyslijNaStanowisko: wyslijNaStanowisko,
        zdejmijZeStolu: zdejmijZeStolu,
        komunikatStolu: komunikatStolu,
        potwierdz: potwierdz,
    });
}());
