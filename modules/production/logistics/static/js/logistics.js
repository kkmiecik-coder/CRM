/**
 * Logistyka — logika zakładki panelu produkcji.
 * modules/production/logistics/static/js/logistics.js
 *
 * Plik przyjeżdża razem z fragmentem tab_content.html (<script src> na końcu
 * szablonu). production-app-loader.js wstawia fragment przez innerHTML
 * i „odtwarza” tag <script> (executeInlineScripts), więc w chwili uruchomienia
 * DOM zakładki już istnieje — inicjalizacja idzie od razu, bez DOMContentLoaded.
 *
 * Ponowne wykonanie (ProductionApp.forceRefresh() ładuje fragment od nowa):
 * na starcie sprzątamy po poprzedniej instancji (window.LogisticsTab.zniszcz) —
 * zegar odświeżania, oczekujące żądania i nasłuch na document. Nasłuchy na
 * samym #logistics-root giną razem ze starym węzłem, więc nic się nie dubluje.
 *
 * API (modules/production/logistics/routers/panel_api.py):
 *   GET  {API}/orders?sposob=&q=&zamkniete=1   lista + liczniki + pauza Base.
 *                                              + bez_lokalizacji, geokoder_dziala,
 *                                              geokoder_postep ({zrobione, wszystkie} | null)
 *   POST {API}/orders/delivery-method          {order_ids, sposob}
 *   POST {API}/orders/<id>/handed-over         „Wydane klientowi”
 *   POST {API}/geocode                         „Zlokalizuj teraz” (wątek w tle, 202)
 *   GET  {API}/geocode                         lekki stan geokodera (postęp przycisku)
 *   PUT  {API}/orders/<id>/address             poprawka adresu (dwuklik w adres)
 *
 * Mapa (etap 2) to osobny plik logistics-map.js, ładowany po Leaflecie —
 * może pojawić się PO tym pliku. Łączymy się z nią, gdy ogłosi gotowość
 * (zdarzenie `logistics:mapa-gotowa`) albo od razu, jeśli już jest:
 * po każdym renderze listy przekazujemy jej wiersze widoczne w tabeli
 * (window.LogisticsMap.render), klik w wiersz woła highlight(), a klik
 * w pinezkę wraca przez onSelect() i podświetla wiersz. Licznik „Bez
 * lokalizacji” i „Zlokalizuj teraz” w nagłówku mapy obsługuje ten plik —
 * to filtr listy i odświeżanie listy.
 *
 * Filtr etapu działa PO STRONIE PRZEGLĄDARKI (parametru `etap` nie wysyłamy):
 * lista wyboru ma pokazywać etapy obecne na liście, a po zawężeniu na
 * serwerze zostałby w niej tylko jeden etap. Przy okazji przełączanie etapu
 * nie kosztuje zapytania.
 *
 * Każdy tekst z API przechodzi przez esc() przed wstawieniem do HTML.
 *
 * Etap 3 (trasy i flota — kod w logistics-routes.js i logistics-fleet.js) dokłada
 * tu tylko punkty zaczepienia: podzakładki Dashboard | Trasy | Flota (pokazWidok),
 * plakietkę trasy pod selectem sposobu, filtr „Transport bez trasy” (sposob=bez_trasy),
 * akcję hurtową „Dodaj do trasy…” i komunikat po zdjęciu zamówień z trasy
 * (usunieto_z_trasy). Nowe pliki rozmawiają z tym wyłącznie przez
 * window.LogisticsTab = {root, odswiez, komunikat, pokazWidok, zniszcz}.
 *
 * Kontrakt etapu 3 (zdarzenia na document, detail.root = #logistics-root):
 *   `logistics:widok` {root, widok, opcje} — wysyła pokazWidok() po każdym przełączeniu
 *       podzakładki (widok: 'dashboard' | 'routes' | 'fleet'; opcje jak w wywołaniu, np.
 *       {route_id}). Słuchają logistics-routes.js (Trasy: świeża lista, dostępność) i
 *       logistics-fleet.js (Flota: świeże dane).
 *   atrybut `data-lg-otworz-trase` — pokazWidok('routes', {route_id}) stawia go na panelu
 *       tras ([data-logistics-view="routes"]); logistics-routes.js otwiera tę trasę i zdejmuje
 *       atrybut (działa także wtedy, gdy plik tras wczyta się dopiero po tym wywołaniu).
 *   `logistics:trasy-zmienione` {root} — wysyłamy, gdy zmiana sposobu dostawy zdjęła
 *       zamówienia z trasy (usunieto_z_trasy); lista tras, otwarta trasa i mapa tras od nowa.
 *   atrybut `data-lg-trasy-blad` na #logistics-root — loader w tab_content.html stawia go,
 *       gdy logistics-routes.js się nie wczytał: „Dodaj do trasy…” mówi wtedy o błędzie.
 *   window.LogisticsMap.onBlad(cb) — odmowa zapisu punktu na mapie spoza bieżącego trybu
 *       (A2) trafia tu jako komunikat Dashboardu.
 */
(function () {
    'use strict';

    // Sprzątanie po poprzednim wykonaniu tego pliku (forceRefresh zakładki).
    if (window.LogisticsTab && typeof window.LogisticsTab.zniszcz === 'function') {
        try { window.LogisticsTab.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    if (!root) return;

    // data-api = url_for('logistics_panel.orders') → baza bez końcowego /orders.
    const API = (root.getAttribute('data-api') || '/production/api/logistics/orders')
        .replace(/\/orders\/?$/, '');
    // Logo Base. (16 px) przy podpowiedzi sposobu — adres z url_for w szablonie.
    const LOGO_BASE = root.getAttribute('data-logo-base') || '';

    // ── Słowniki ────────────────────────────────────────────────────────────

    const SPOSOBY = ['kurier_baselinker', 'transport_woodpower', 'odbior_osobisty'];
    // Etykiety w interfejsie zakładki (backend podpisuje transport jako
    // „Transport WoodPower” — to tekst do Base., tu mówimy po ludzku).
    const ETYKIETY = {
        kurier_baselinker: 'Kurier',
        transport_woodpower: 'Transport własny',
        odbior_osobisty: 'Odbiór osobisty',
    };
    const NIE_USTAWIONO = 'Nie ustawiono';

    // Kolejność etapów w filtrze = kolejność linii produkcyjnej.
    const KOLEJNOSC_ETAPOW = [
        'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
        'czeka_na_formatowanie', 'czeka_na_krawedzie', 'czeka_na_lakiernie',
        'czeka_na_pakowanie', 'spakowane', 'wstrzymane', 'anulowane',
    ];

    const ODSWIEZANIE_MS = 60000;   // lista odświeża się co 60 s…
    // …a co 30 s, póki geokoder pracuje w tle (nowe pinezki; postęp idzie osobno,
    // lekkim GET /geocode). Pełna lista z pozycjami to setki KB — przegląd D17.
    const ODSWIEZANIE_GEO_MS = 30000;
    // Sam postęp geokodera (GET /geocode, lekkie) — co 1,5 s: krótki przebieg
    // kończył się między odświeżeniami listy i przycisk nie pokazywał postępu.
    const STAN_GEO_MS = 1500;
    const ZEGAR_MS = 5000;          // …sprawdzane co 5 s (powrót na zakładkę po przerwie)
    // Po „Zlokalizuj teraz” wątek dopiero bierze dzierżawę — przez tyle czasu
    // przycisk zostaje „w toku”, nawet gdy pierwsza odpowiedź powie, że stoi.
    const OCHRONA_GEO_MS = 5000;
    const DEBOUNCE_SZUKAJ_MS = 300;
    // Strzałki na zamkniętym <select> w Windows od razu zmieniają wartość
    // i odpalają `change`. Krótka zwłoka wysyła tylko wartość, na której
    // użytkownik się zatrzymał — myszką nie da się jej zauważyć.
    const ZWLOKA_SELECTA_MS = 350;
    const LIMIT_HURTU = 500;        // jak LIMIT_HURTU w panel_api.py

    // Etap 3: podzakładki (data-lg-widok na przyciskach, data-logistics-view na panelach).
    const WIDOKI = ['dashboard', 'routes', 'fleet'];
    const KLUCZ_WIDOKU_LS = 'logistyka.widok';
    const STATUSY_TRAS = { robocza: 'robocza', zatwierdzona: 'zatwierdzona', wykonana: 'wykonana' };
    // Status trasy na plakietce jako znak — te same ikony co w edytorze trasy (ołówek = szkic,
    // kłódka = zatwierdzona, ptaszek = wykonana); całą szerokość plakietki dostaje nazwa.
    const IKONY_TRAS = { robocza: 'fa-pen', zatwierdzona: 'fa-lock', wykonana: 'fa-check' };

    // ── Stan ────────────────────────────────────────────────────────────────

    const stan = {
        wiersze: [],                // ostatnia lista z API (przed filtrem etapu)
        liczniki: null,
        wstrzymaneDo: null,
        // geo: filtr dokładności lokalizacji (po stronie przeglądarki, jak etap):
        // '' | 'dokladna' | 'przyblizona' | 'reczna' | 'brak' („Bez lokalizacji”).
        filtr: { sposob: '', etap: '', q: '', zamkniete: false, geo: '' },
        zaznaczone: new Set(),
        rozwiniete: new Set(),      // id zamówień z rozwiniętymi pozycjami (przeżywa odświeżenie)
        ostatniKlik: null,          // id do zaznaczania zakresu z Shiftem
        wysylane: new Set(),        // id wierszy, dla których leci POST
        // id → sposób, który właśnie zapisujemy: przerysowany w trakcie wiersz
        // pokazuje wybraną wartość, a nie mignięcie starą z serwera.
        docelowe: new Map(),
        hurtTrwa: false,
        ostatnieOdswiezenie: 0,
        pierwszeLadowanie: true,
        blad: null,
        bezLokalizacji: null,       // licznik z API (otwarte zamówienia bez punktu)
        geokoderDziala: false,
        geokoderPostep: null,       // {zrobione, wszystkie} z API albo null (wątek dopiero startuje)
        ochronaGeoDo: 0,            // patrz OCHRONA_GEO_MS
        naLiscie: [],               // id wierszy w tabeli — to samo widzi mapa
        wskazany: null,             // id wiersza podświetlonego z mapy
        dopasujMape: false,         // po zmianie filtra mapa dopasowuje widok
        // Sortowanie z nagłówka tabeli: {kolumna, kierunek: 1 | -1} albo null —
        // wtedy kolejność z API („Nie ustawiono” na górze, potem termin).
        sort: null,
        widok: 'dashboard',         // bieżąca podzakładka (etap 3)
    };

    const oczekujaceSelecty = new Map();   // id → timeout zwłoki selecta
    let kontrolerListy = null;
    let numerZapytania = 0;
    let zegar = null;
    let timerSzukania = null;
    let timerStanuGeo = null;       // odpytywanie GET /geocode w trakcie przebiegu
    let zniszczona = false;
    let mapaPolaczona = null;       // instancja window.LogisticsMap, z którą rozmawiamy
    // Chwila ostatniego kliknięcia/klawisza w zakładce — odświeżanie z zegara
    // czeka, aż logistyk przestanie działać (np. ma rozwiniętą listę selecta).
    let ostatniaAktywnosc = 0;
    const CISZA_PRZED_ODSWIEZENIEM_MS = 10000;

    const el = (nazwa) => root.querySelector('[data-lg="' + nazwa + '"]');
    const tbody = el('wiersze');
    const tabela = root.querySelector('.lg-tabela');

    // ── Pomocnicze ──────────────────────────────────────────────────────────

    function esc(wartosc) {
        if (wartosc === null || wartosc === undefined) return '';
        return String(wartosc).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    // Odmiana: 1 zamówienie, 2–4 zamówienia, 5+ zamówień (12–14 → zamówień).
    function odmiana(n, formy) {
        const d = n % 10;
        const s = n % 100;
        if (n === 1) return formy[0];
        if (d >= 2 && d <= 4 && (s < 12 || s > 14)) return formy[1];
        return formy[2];
    }

    const ZAMOWIENIE = ['zamówienie', 'zamówienia', 'zamówień'];
    const ileZamowien = (n) => n + ' ' + odmiana(n, ZAMOWIENIE);

    const liczbaM3 = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: 3, maximumFractionDigits: 3 });

    function dzisIso() {
        const d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }

    // 'YYYY-MM-DD' → '25.09' (rok dopisany, gdy inny niż bieżący).
    function dataKrotka(iso) {
        if (!iso) return '';
        const [r, m, d] = iso.slice(0, 10).split('-');
        if (!d) return iso;
        return d + '.' + m + (r !== String(new Date().getFullYear()) ? '.' + r : '');
    }

    // 'YYYY-MM-DDTHH:MM:SS' → 'HH:MM' (serwer podaje czas lokalny bez strefy).
    function godzina(iso) {
        const t = (iso || '').split('T')[1] || '';
        return t.slice(0, 5);
    }

    function dniPoTerminie(iso) {
        const [r, m, d] = iso.split('-').map(Number);
        const dzis = new Date();
        const roznica = Date.UTC(dzis.getFullYear(), dzis.getMonth(), dzis.getDate()) - Date.UTC(r, m - 1, d);
        return Math.round(roznica / 86400000);
    }

    const znajdz = (id) => stan.wiersze.find((w) => w.id === id) || null;
    const kluczSposobu = (w) => w.sposob || 'brak';

    // ── Komunikacja z API ───────────────────────────────────────────────────

    class BladApi extends Error {
        constructor(komunikat, status) {
            super(komunikat);
            this.status = status;
        }
    }

    function komunikatBledu(status, dane) {
        // 401/403 z bramki dostępu niosą kody ('unauthorized'), nie zdania.
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

    // ── Lista ───────────────────────────────────────────────────────────────

    /**
     * tryb 'auto'  — odświeżanie z zegara: tabela zostaje, błąd idzie do komunikatu.
     * tryb 'uzytkownik' — filtr, wyszukiwarka, przycisk: tabela przygasa
     *   na czas zapytania, błąd zastępuje tabelę (dane nie pasują już do filtrów).
     */
    async function wczytaj(tryb) {
        if (zniszczona) return;
        if (kontrolerListy) kontrolerListy.abort();
        const kontroler = new AbortController();
        kontrolerListy = kontroler;
        const moje = ++numerZapytania;

        const params = new URLSearchParams();
        if (stan.filtr.sposob) params.set('sposob', stan.filtr.sposob);
        if (stan.filtr.q) params.set('q', stan.filtr.q);
        // Bez frazy API odpowiada 422 — przełącznik i tak jest wtedy wyłączony.
        if (stan.filtr.q && stan.filtr.zamkniete) params.set('zamkniete', '1');

        const przycisk = root.querySelector('[data-lg-akcja="odswiez"]');
        if (tryb !== 'auto') {
            if (stan.pierwszeLadowanie || stan.blad) pokazStan('ladowanie');
            else tabela.classList.add('is-laduje');
            przycisk.classList.add('is-kreci');
        }

        try {
            const dane = await zapytanie('/orders?' + params.toString(), { signal: kontroler.signal });
            if (zniszczona || moje !== numerZapytania) return;
            stan.wiersze = Array.isArray(dane.orders) ? dane.orders : [];
            stan.liczniki = dane.liczniki || null;
            stan.wstrzymaneDo = dane.base_wstrzymane_do || null;
            przyjmijStanGeo(dane);
            stan.blad = null;
            stan.pierwszeLadowanie = false;
            stan.ostatnieOdswiezenie = Date.now();
            usunKomunikat('odswiezanie');
            renderujWszystko();
        } catch (e) {
            if (zniszczona || moje !== numerZapytania || (e && e.name === 'AbortError')) return;
            // Nieudane odświeżenie też liczy się jako próba — inaczej zegar
            // ponawiałby je co 5 s i zasypywał komunikatami. Zegar ponawia
            // co 60 s także ze stanu błędu; sukces sam go zdejmie.
            stan.ostatnieOdswiezenie = Date.now();
            if (tryb === 'auto' && !stan.pierwszeLadowanie && !stan.blad) {
                pokazKomunikat('blad', 'Nie udało się odświeżyć listy. ' + e.message,
                    { klucz: 'odswiezanie', ponow: true });
            } else {
                // Lista nie pasuje już do filtrów — nic z niej nie może zostać
                // do zaznaczenia ani akcji hurtowej.
                stan.wiersze = [];
                stan.naLiscie = [];
                stan.blad = e.message;
                pokazStan('blad');
                przekazDoMapy();
            }
            stan.pierwszeLadowanie = false;
        } finally {
            if (moje === numerZapytania) {
                kontrolerListy = null;
                tabela.classList.remove('is-laduje');
                przycisk.classList.remove('is-kreci');
            }
        }
    }

    function poEtapie() {
        if (!stan.filtr.etap) return stan.wiersze;
        return stan.wiersze.filter((w) => w.etap && w.etap.status === stan.filtr.etap);
    }

    // Rodzaj lokalizacji wiersza — ten sam podział w filtrze i w jego licznikach.
    function rodzajLokalizacji(w) {
        if (!w.geo) return 'brak';
        if (w.geo.source === 'reczna') return 'reczna';
        return w.geo.quality === 'przyblizona' ? 'przyblizona' : 'dokladna';
    }

    const RODZAJE_LOKALIZACJI = [
        ['dokladna', 'Dokładna'], ['przyblizona', 'Przybliżona'],
        ['reczna', 'Ustawiona ręcznie'], ['brak', 'Bez lokalizacji'],
    ];

    function widoczneWiersze() {
        const wiersze = poEtapie();
        return posortuj(stan.filtr.geo ? wiersze.filter((w) => rodzajLokalizacji(w) === stan.filtr.geo) : wiersze);
    }

    // ── Sortowanie (klik w nagłówek; drugi klik w ten sam odwraca) ─────────
    // Po stronie przeglądarki, na liście z API — jak filtry etapu i lokalizacji.
    // Puste wartości zawsze na końcu (w obu kierunkach), remis rozstrzyga numer.
    // Wybór zostaje w localStorage tej przeglądarki (jak proporcje i podkład mapy).

    const KLUCZ_SORTOWANIA_LS = 'logistyka.lista.sortowanie';
    const porownajTekst = new Intl.Collator('pl', { sensitivity: 'base', numeric: true }).compare;
    const porownajLiczby = (a, b) => a - b;
    const pustyTekst = (t) => (t === null || t === undefined || String(t).trim() === '' ? null : String(t));

    const KOLUMNY_SORTOWANIA = {
        numer: { wartosc: (w) => pustyTekst(w.numer), porownaj: porownajTekst },
        klient: { wartosc: (w) => pustyTekst(w.klient), porownaj: porownajTekst },
        // Adres: miejscowość, potem kod i ulica — grupuje zamówienia z jednej miejscowości.
        adres: {
            // Bez miejscowości (sam kod albo ulica) liczy się jak pusty — na końcu
            // w OBU kierunkach (przegląd D9: człon w komparatorze odwracał się z nim).
            wartosc: (w) => (w.miasto ? [w.miasto, w.kod || '', w.adres || ''] : null),
            porownaj: (a, b) => porownajTekst(a[0], b[0]) || porownajTekst(a[1], b[1]) ||
                porownajTekst(a[2], b[2]),
        },
        metoda: { wartosc: (w) => pustyTekst(w.metoda_z_base), porownaj: porownajTekst },
        // Sposób: kolejność liczników nad listą (Nie ustawiono, Kurier, Transport, Odbiór).
        sposob: { wartosc: (w) => ['brak'].concat(SPOSOBY).indexOf(kluczSposobu(w)), porownaj: porownajLiczby },
        // Etap: kolejność linii produkcyjnej, nie alfabet.
        etap: {
            wartosc: (w) => {
                const i = KOLEJNOSC_ETAPOW.indexOf(w.etap && w.etap.status);
                return i === -1 ? KOLEJNOSC_ETAPOW.length : i;
            },
            porownaj: porownajLiczby,
        },
        termin: { wartosc: (w) => pustyTekst(w.termin), porownaj: (a, b) => (a < b ? -1 : (a > b ? 1 : 0)) },
        m3: { wartosc: (w) => (Number(w.m3) > 0 ? Number(w.m3) : null), porownaj: porownajLiczby },
    };

    function posortuj(wiersze) {
        const s = stan.sort;
        const def = s && KOLUMNY_SORTOWANIA[s.kolumna];
        if (!def) return wiersze;
        return wiersze.map((w, i) => ({ w: w, i: i, v: def.wartosc(w) }))
            .sort((a, b) => {
                const pa = a.v === null;
                const pb = b.v === null;
                if (pa !== pb) return pa ? 1 : -1;
                const r = (pa ? 0 : def.porownaj(a.v, b.v) * s.kierunek) ||
                    porownajTekst(String(a.w.numer || ''), String(b.w.numer || ''));
                return r || a.i - b.i;
            })
            .map((x) => x.w);
    }

    function wczytajSortowanie() {
        try {
            const s = JSON.parse(window.localStorage.getItem(KLUCZ_SORTOWANIA_LS) || 'null');
            if (s && KOLUMNY_SORTOWANIA[s.kolumna] && (s.kierunek === 1 || s.kierunek === -1)) {
                return { kolumna: s.kolumna, kierunek: s.kierunek };
            }
        } catch (e) { /* brak localStorage albo śmieci w nim — kolejność z API */ }
        return null;
    }

    // Klik: rosnąco → malejąco → kolejność domyślna z API (przegląd D10: bez trzeciego
    // kroku kolejka pracy „Nie ustawiono na górze” znikała w tej przeglądarce na stałe).
    function ustawSortowanie(kolumna) {
        if (!KOLUMNY_SORTOWANIA[kolumna]) return;
        const ta = stan.sort && stan.sort.kolumna === kolumna;
        if (ta && stan.sort.kierunek === -1) {
            stan.sort = null;
        } else {
            stan.sort = { kolumna: kolumna, kierunek: ta ? -1 : 1 };
        }
        try {
            if (stan.sort) window.localStorage.setItem(KLUCZ_SORTOWANIA_LS, JSON.stringify(stan.sort));
            else window.localStorage.removeItem(KLUCZ_SORTOWANIA_LS);
        } catch (e) { /* wybór nie przeżyje przeładowania */ }
        renderujSortowanie();
        renderujTabele();
    }

    // aria-sort na <th> (czytnik ekranu) i znak kierunku przy aktywnej kolumnie.
    function renderujSortowanie() {
        root.querySelectorAll('.lg-tabela th[data-lg-sort-kolumna]').forEach((th) => {
            const kolumna = th.getAttribute('data-lg-sort-kolumna');
            const aktywna = !!(stan.sort && stan.sort.kolumna === kolumna);
            const rosnaco = aktywna && stan.sort.kierunek === 1;
            th.setAttribute('aria-sort', aktywna ? (rosnaco ? 'ascending' : 'descending') : 'none');
            th.classList.toggle('is-sortowana', aktywna);
            const przycisk = th.querySelector('.lg-sort');
            if (przycisk) {
                const nazwa = przycisk.getAttribute('data-nazwa') || kolumna;
                przycisk.title = !aktywna
                    ? 'Sortuj według: ' + nazwa
                    : (rosnaco
                        ? 'Sortowanie: ' + nazwa + ' rosnąco. Kliknij, żeby odwrócić.'
                        : 'Sortowanie: ' + nazwa + ' malejąco. Kliknij, żeby wrócić do kolejności domyślnej.');
            }
        });
    }

    // Filtry inne niż „Bez lokalizacji” zawężają listę — licznik „Bez lokalizacji”
    // (globalny, z API) mówi wtedy więcej, niż widać; stąd „· w widoku k”.
    const zawezonyWidok = () => !!(stan.filtr.sposob || stan.filtr.etap || stan.filtr.q);
    const bezGeoWWidoku = () => poEtapie().filter((w) => !w.geo).length;

    // ── Render: nagłówek, liczniki, baner, etapy ────────────────────────────

    function renderujWszystko() {
        renderujLiczniki();
        renderujBaner();
        renderujEtapy();
        renderujFiltrGeo();
        renderujGeo();
        renderujTabele();
        renderujOdswiezono();
    }

    function renderujOdswiezono() {
        const teraz = new Date();
        el('odswiezono').textContent = 'Stan na ' + String(teraz.getHours()).padStart(2, '0') + ':' +
            String(teraz.getMinutes()).padStart(2, '0');
    }

    function renderujLiczniki() {
        const l = stan.liczniki;
        root.querySelectorAll('[data-licznik]').forEach((span) => {
            const klucz = span.getAttribute('data-licznik');
            let wartosc = null;
            if (l) {
                wartosc = klucz === 'wszystkie'
                    ? ['brak'].concat(SPOSOBY).reduce((suma, k) => suma + (Number(l[k]) || 0), 0)
                    : (Number(l[klucz]) || 0);
            }
            span.textContent = wartosc === null ? '–' : String(wartosc);
        });
        root.querySelectorAll('[data-lg-sposob]').forEach((b) => {
            const aktywny = b.getAttribute('data-lg-sposob') === stan.filtr.sposob;
            b.classList.toggle('is-aktywny', aktywny);
            b.setAttribute('aria-pressed', aktywny ? 'true' : 'false');
        });
        const brak = root.querySelector('.lg-licznik--brak');
        brak.classList.toggle('is-niepusty', !!(l && Number(l.brak) > 0));
    }

    function renderujBaner() {
        const baner = el('baner');
        if (!stan.wstrzymaneDo) {
            if (!baner.hidden) {
                baner.hidden = true;
                dopasujWysokosc();
            }
            return;
        }
        const iso = stan.wstrzymaneDo;
        const kiedy = (iso.slice(0, 10) === dzisIso() ? '' : dataKrotka(iso) + ' ') + godzina(iso);
        el('baner-tekst').textContent = 'Wysyłka do Base. wstrzymana do ' + kiedy +
            ' (limit API). Zmiany zostaną wysłane automatycznie.';
        baner.hidden = false;
        dopasujWysokosc();
    }

    function renderujEtapy() {
        const select = el('etap');
        const ile = new Map();
        const nazwy = new Map();
        stan.wiersze.forEach((w) => {
            if (!w.etap) return;
            ile.set(w.etap.status, (ile.get(w.etap.status) || 0) + 1);
            nazwy.set(w.etap.status, w.etap.nazwa || w.etap.status);
        });
        // Wybrany etap zostaje na liście, nawet gdy po odświeżeniu nic w nim nie ma.
        if (stan.filtr.etap && !ile.has(stan.filtr.etap)) {
            ile.set(stan.filtr.etap, 0);
            nazwy.set(stan.filtr.etap, select.selectedOptions[0] ? select.selectedOptions[0].dataset.nazwa || stan.filtr.etap : stan.filtr.etap);
        }
        const ranga = (s) => {
            const i = KOLEJNOSC_ETAPOW.indexOf(s);
            return i === -1 ? KOLEJNOSC_ETAPOW.length : i;
        };
        const statusy = Array.from(ile.keys()).sort((a, b) => ranga(a) - ranga(b) || a.localeCompare(b));
        let html = '<option value="">Wszystkie etapy</option>';
        statusy.forEach((s) => {
            html += '<option value="' + esc(s) + '" data-nazwa="' + esc(nazwy.get(s)) + '"' +
                (s === stan.filtr.etap ? ' selected' : '') + '>' +
                esc(nazwy.get(s)) + ' (' + ile.get(s) + ')</option>';
        });
        select.innerHTML = html;
        select.classList.toggle('is-aktywny', !!stan.filtr.etap);
    }

    // Filtr dokładności lokalizacji: liczby przy opcjach liczą listę z API
    // (jak filtr etapu), wybrana opcja zostaje, nawet gdy jej liczba spadnie do zera.
    function renderujFiltrGeo() {
        const select = el('geo');
        const ile = { dokladna: 0, przyblizona: 0, reczna: 0, brak: 0 };
        stan.wiersze.forEach((w) => { ile[rodzajLokalizacji(w)] += 1; });
        let html = '<option value="">Wszystkie</option>';
        RODZAJE_LOKALIZACJI.forEach(([klucz, nazwa]) => {
            html += '<option value="' + klucz + '"' + (klucz === stan.filtr.geo ? ' selected' : '') + '>' +
                nazwa + ' (' + ile[klucz] + ')</option>';
        });
        select.innerHTML = html;
        select.classList.toggle('is-aktywny', !!stan.filtr.geo);
    }

    function renderujIle() {
        const widoczne = widoczneWiersze().length;
        const wszystkie = stan.wiersze.length;
        // „7 z 24 zamówień” — po „z” dopełniacz: 1 zamówienia, reszta zamówień.
        el('ile').textContent = (stan.filtr.etap || stan.filtr.geo)
            ? widoczne + ' z ' + wszystkie + ' ' + (wszystkie === 1 ? 'zamówienia' : 'zamówień')
            : ileZamowien(widoczne);
    }

    function renderujPrzelacznikZamknietych() {
        const pole = el('zamkniete-pole');
        const box = el('zamkniete');
        const jestFraza = !!stan.filtr.q;
        box.disabled = !jestFraza;
        if (!jestFraza) box.checked = false;
        pole.classList.toggle('is-nieaktywny', !jestFraza);
        pole.title = jestFraza
            ? 'Szukaj także w zamówieniach zamkniętych (najnowsze 50)'
            : 'Wpisz frazę, żeby szukać także w zamkniętych zamówieniach';
        el('zamkniete-podpowiedz').hidden = jestFraza;
    }

    // ── Render: tabela ──────────────────────────────────────────────────────

    function komorkaStanu(tresc, klasa) {
        return '<tr class="lg-wiersz-stanu"><td colspan="10"><div class="lg-stan ' + (klasa || '') + '">' +
            tresc + '</div></td></tr>';
    }

    function przyciskStanu(akcja, etykieta, ikona) {
        return '<button type="button" class="lg-przycisk" data-lg-akcja="' + akcja + '">' +
            (ikona ? '<i class="fas ' + ikona + '" aria-hidden="true"></i>' : '') + esc(etykieta) + '</button>';
    }

    function pokazStan(rodzaj) {
        let tresc;
        if (rodzaj === 'ladowanie') {
            tresc = '<span class="lg-stan-tytul">Ładowanie zamówień…</span>';
            tbody.innerHTML = komorkaStanu(tresc);
        } else if (rodzaj === 'blad') {
            tresc = '<span class="lg-stan-tytul">Nie udało się pobrać zamówień.</span>' +
                '<span class="lg-stan-opis">' + esc(stan.blad) + '</span>' +
                przyciskStanu('ponow', 'Spróbuj ponownie', 'fa-rotate-right');
            tbody.innerHTML = komorkaStanu(tresc, 'lg-stan--blad');
            el('ile').textContent = '';
            stan.zaznaczone.clear();
            renderujZaznaczenie();
        }
    }

    function pustyStan() {
        const f = stan.filtr;
        let tytul, opis = '', przycisk = '';
        const bezPunktu = stan.bezLokalizacji || 0;
        if (f.geo === 'brak' && poEtapie().length && zawezonyWidok() && bezPunktu > 0) {
            // Licznik jest globalny — pusty widok nie może twierdzić, że wszystko ma punkt.
            tytul = 'W tym widoku wszystkie zamówienia mają punkt na mapie.';
            opis = 'Bez lokalizacji ' + odmiana(bezPunktu, ['jest', 'są', 'jest']) + ' ' + ileZamowien(bezPunktu) +
                '. Zdejmij filtry, żeby je zobaczyć.';
            przycisk = przyciskStanu('zdejmij-filtry', 'Zdejmij filtry');
        } else if (f.geo === 'brak' && poEtapie().length) {
            tytul = 'Każde zamówienie na liście ma już punkt na mapie.';
            przycisk = przyciskStanu('bez-lokalizacji', 'Pokaż wszystkie z listy');
        } else if (f.geo && poEtapie().length) {
            const nazwa = (RODZAJE_LOKALIZACJI.find((r) => r[0] === f.geo) || [f.geo, f.geo])[1];
            tytul = 'Na liście nie ma zamówień z lokalizacją „' + nazwa.toLowerCase() + '”.';
            przycisk = przyciskStanu('wszystkie-lokalizacje', 'Pokaż wszystkie lokalizacje');
        } else if (f.etap && stan.wiersze.length) {
            const opcja = el('etap').selectedOptions[0];
            tytul = 'Na liście nie ma zamówień na etapie „' + ((opcja && opcja.dataset.nazwa) || f.etap) + '”.';
            przycisk = przyciskStanu('wszystkie-etapy', 'Pokaż wszystkie etapy');
        } else if (f.q) {
            tytul = 'Nic nie pasuje do „' + f.q + '”' + (f.zamkniete ? ', także wśród zamkniętych.' : '.');
            if (!f.zamkniete) {
                opis = 'Szukamy w otwartych zamówieniach. Zamówienia wydane i wysłane są zamknięte.';
                przycisk = przyciskStanu('szukaj-zamkniete', 'Szukaj także w zamkniętych', 'fa-magnifying-glass');
            }
        } else if (f.sposob === 'bez_trasy') {
            // Etap 3: filtr „Transport bez trasy”.
            tytul = 'Każde otwarte zamówienie z transportem własnym jest już na trasie.';
            przycisk = przyciskStanu('pokaz-wszystkie', 'Pokaż wszystkie otwarte');
        } else if (f.sposob === 'brak') {
            tytul = 'Każde otwarte zamówienie ma ustawiony sposób dostawy.';
            opis = 'Nowe zamówienia z Base. pojawią się tutaj same.';
            przycisk = przyciskStanu('pokaz-wszystkie', 'Pokaż wszystkie otwarte');
        } else if (f.sposob) {
            tytul = 'Żadne otwarte zamówienie nie ma sposobu dostawy „' + (ETYKIETY[f.sposob] || f.sposob) + '”.';
            przycisk = przyciskStanu('pokaz-wszystkie', 'Pokaż wszystkie otwarte');
        } else {
            tytul = 'Brak otwartych zamówień w logistyce.';
            opis = 'Zamówienia pojawiają się tu zaraz po pobraniu z Base.';
        }
        return komorkaStanu('<span class="lg-stan-tytul">' + esc(tytul) + '</span>' +
            (opis ? '<span class="lg-stan-opis">' + esc(opis) + '</span>' : '') + przycisk);
    }

    function selectSposobu(w, zablokowany, powod) {
        const cel = stan.docelowe.get(w.id);
        const wybrany = cel === 'brak' ? null : (cel || w.sposob);
        // „Nie ustawiono” zawsze na liście: logistyk, który ustawił sposób nie temu
        // zamówieniu, cofa wybór (API: sposob = 'brak').
        let opcje = '<option value="brak"' + (wybrany ? '' : ' selected') + '>' + NIE_USTAWIONO + '</option>';
        SPOSOBY.forEach((s) => {
            opcje += '<option value="' + s + '"' + (wybrany === s ? ' selected' : '') + '>' + ETYKIETY[s] + '</option>';
        });
        return '<select class="form-select form-select-sm lg-sposob' + (wybrany ? '' : ' lg-sposob--brak') + '"' +
            ' aria-label="Sposób dostawy zamówienia ' + esc(w.numer) + '"' +
            (zablokowany ? ' disabled title="' + esc(powod) + '"' : '') + '>' + opcje + '</select>';
    }

    // Klasa koloru trasy z mapy (jedno źródło wzoru, logistics-map.js); bez mapy — bez koloru.
    function kolorTrasy(id) {
        const m = mapa();
        return m && typeof m.kolorTrasy === 'function' ? m.kolorTrasy(id) : '';
    }

    /**
     * Etap 3: plakietka trasy pod selectem sposobu (bez nowej kolumny — układ przy
     * 1280 px czeka na decyzję). Zamówienie na trasie: klik otwiera trasę w zakładce
     * „Trasy”. Transport własny bez trasy: „bez trasy”, klik = okno „Dodaj do trasy…”
     * dla tego jednego zamówienia.
     * (oględziny Task 8, I1) Całą szerokość plakietki dostaje NAZWA trasy; status to znak
     * (ołówek / kłódka / ptaszek, jak w edytorze), a pasek z lewej ma kolor trasy z mapy —
     * kilka zatwierdzonych tras naraz da się rozróżnić bez najeżdżania. Pełny opis ze
     * statusem: title i aria-label.
     */
    function plakietkaTrasy(w) {
        if (w.trasa) {
            const status = STATUSY_TRAS[w.trasa.status] || String(w.trasa.status || '');
            const opis = 'Trasa ' + w.trasa.nazwa + ', ' + status + '. Otwórz trasę.';
            const kolor = kolorTrasy(w.trasa.id);
            return '<button type="button" class="lg-plakietka-trasy lg-plakietka-trasy--' + esc(w.trasa.status) +
                (kolor ? ' lg-plakietka-trasy--kolor ' + kolor : '') + '"' +
                ' data-lg-akcja="pokaz-trase" data-trasa-id="' + esc(w.trasa.id) + '"' +
                ' title="' + esc(opis) + '" aria-label="' + esc(opis) + '">' +
                '<i class="fas ' + (IKONY_TRAS[w.trasa.status] || 'fa-route') + ' lg-plakietka-trasy-status" aria-hidden="true"></i>' +
                '<span class="lg-plakietka-trasy-nazwa">' + esc(w.trasa.nazwa) + '</span></button>';
        }
        if (w.sposob !== 'transport_woodpower' || w.zamkniete || w.wydane) return '';
        return '<button type="button" class="lg-plakietka-trasy lg-plakietka-trasy--brak" data-lg-akcja="dodaj-do-trasy"' +
            ' title="Zamówienie bez trasy. Kliknij, żeby dodać je do trasy."' +
            ' aria-label="' + esc('Zamówienie ' + w.numer + ' bez trasy. Dodaj do trasy') + '">bez trasy</button>';
    }

    function ikona(klasaFa, klasa, opis) {
        return '<i class="fas ' + klasaFa + ' ' + klasa + '" role="img" aria-label="' + esc(opis) +
            '" title="' + esc(opis) + '"></i>';
    }

    function komorkaTerminu(iso) {
        if (!iso) return '<span class="lg-brak-danych">brak</span>';
        const dni = dniPoTerminie(iso);
        let klasa = 'lg-termin';
        let tytul = 'Termin ' + dataKrotka(iso);
        if (dni > 0) {
            klasa += ' is-po-terminie';
            tytul = 'Po terminie: ' + dni + ' ' + odmiana(dni, ['dzień', 'dni', 'dni']);
        } else if (dni === 0) {
            klasa += ' is-dzis';
            tytul = 'Termin dziś';
        }
        return '<time class="' + klasa + '" datetime="' + esc(iso) + '" title="' + esc(tytul) + '">' +
            esc(dataKrotka(iso)) + '</time>';
    }

    /**
     * Pinezka przy numerze: ten sam znak i kolor co na mapie (kolor = sposób
     * dostawy, przerywana obwódka = lokalizacja przybliżona) — klik pokazuje
     * zamówienie na mapie. Bez punktu: celownik „Ustaw na mapie” (z napisem,
     * gdy włączony filtr „Bez lokalizacji”).
     */
    function przyciskMapy(w) {
        const sposob = SPOSOBY.includes(w.sposob) ? w.sposob : 'brak';
        if (w.geo) {
            const przyblizona = w.geo.quality === 'przyblizona';
            const opis = 'Pokaż zamówienie ' + w.numer + ' na mapie' + (przyblizona ? ' (lokalizacja przybliżona)' : '');
            return '<button type="button" class="lg-na-mapie" data-lg-akcja="pokaz-na-mapie"' +
                ' title="' + esc(opis) + '" aria-label="' + esc(opis) + '">' +
                '<span class="lg-pin lg-pin--' + sposob + (przyblizona ? ' lg-pin--przyblizona' : '') + '" aria-hidden="true"></span>' +
                '</button>';
        }
        return '<button type="button" class="lg-na-mapie lg-na-mapie--ustaw" data-lg-akcja="ustaw-na-mapie"' +
            ' title="Ustaw na mapie" aria-label="' + esc('Ustaw na mapie miejsce dostawy zamówienia ' + w.numer) + '">' +
            '<i class="fas fa-location-crosshairs" aria-hidden="true"></i>' +
            '<span class="lg-na-mapie-tekst">Ustaw na mapie</span></button>';
    }

    /**
     * Adres w dwóch liniach (kolumna „Adres”, a węziej pod nazwą klienta):
     * kod pocztowy + miejscowość, pod spodem ulica z numerami tak, jak przyszła
     * z Base. Obie linie przycinane wielokropkiem, pełna treść w title.
     */
    // Adres poprawiamy tylko w zamówieniu, które jeszcze jedzie (backend też odmawia).
    const adresDoPoprawki = (w) => !w.wydane && !w.zamkniete && !(w.etap && w.etap.status === 'anulowane');

    function adresHtml(w) {
        if (!adresDoPoprawki(w)) {
            return '<span class="lg-adres-statyczny">' + liniiAdresu(w, 'brak') + '</span>';
        }
        // Dwuklik (albo Enter na fokusie) otwiera poprawkę adresu — patrz otworzAdres().
        // Etykieta niesie sam adres: czytnik ekranu czyta ją ZAMIAST treści przycisku.
        const tekst = [[w.kod, w.miasto].filter(Boolean).join(' '), w.adres].filter(Boolean).join(', ');
        const opis = (tekst ? 'Adres: ' + tekst : 'Brak adresu') + '. Dwuklik albo Enter: popraw adres.';
        return '<span class="lg-adres" data-lg-adres tabindex="0" role="button" aria-label="' + esc(opis) + '">' +
            liniiAdresu(w, 'brak, dodaj adres') + '</span>';
    }

    function liniiAdresu(w, brak) {
        const miejscowosc = [w.kod, w.miasto].filter(Boolean).join(' ');
        const gora = miejscowosc
            ? '<span class="lg-adres-linia lg-adres-miejscowosc" title="' + esc(miejscowosc) + '">' +
                (w.kod ? '<span class="lg-adres-kod">' + esc(w.kod) + '</span>' + (w.miasto ? ' ' : '') : '') +
                esc(w.miasto || '') + '</span>'
            : '<span class="lg-adres-linia lg-adres-miejscowosc lg-brak-danych">' + esc(brak) + '</span>';
        const dol = w.adres
            ? '<span class="lg-adres-linia lg-adres-ulica" title="' + esc(w.adres) + '">' + esc(w.adres) + '</span>'
            : '';
        return gora + dol;
    }

    /**
     * Rozwinięty wiersz: pozycje zamówienia jak na liście produktów — nazwa i ID,
     * gatunek / technologia / klasa / grubość, ilość, m³ i stanowisko, na którym
     * pozycja czeka (ta sama kropka i nazwa co w kolumnie „Etap produkcji”).
     * Anulowane zostają na liście, wyszarzone.
     */
    function pozycjeHtml(w) {
        const pozycje = Array.isArray(w.pozycje) ? w.pozycje : [];
        const tresc = pozycje.length ? pozycje.map((p) => {
            const grubosc = p.grubosc_cm ? String(p.grubosc_cm).replace('.', ',') + ' cm' : null;
            const znaczniki = [p.gatunek, p.technologia, p.klasa, grubosc]
                .filter(Boolean).map((t) => '<span class="lg-pozycja-znacznik">' + esc(t) + '</span>');
            if (p.bez_dociecia) znaczniki.push('<span class="lg-pozycja-znacznik lg-pozycja-znacznik--uwaga">bez docięcia</span>');
            if (p.dorobka) znaczniki.push('<span class="lg-pozycja-znacznik lg-pozycja-znacznik--uwaga">doróbka</span>');
            const etap = p.etap || { status: '', nazwa: '' };
            const m3 = Number(p.m3) > 0 ? liczbaM3.format(Number(p.m3)) + ' m³' : '—';
            return '<div class="lg-pozycja' + (p.anulowana ? ' is-anulowana' : '') + '">' +
                '<div class="lg-pozycja-nazwa"><span class="lg-pozycja-tekst" title="' + esc(p.nazwa) + '">' +
                    esc(p.nazwa || '—') + '</span><span class="lg-pozycja-id">' + esc(p.id) + '</span></div>' +
                '<div class="lg-pozycja-znaczniki">' + znaczniki.join('') + '</div>' +
                '<span class="lg-pozycja-ilosc">' + esc(p.ilosc) + ' szt.</span>' +
                '<span class="lg-pozycja-m3">' + m3 + '</span>' +
                '<span class="lg-etap lg-pozycja-etap" data-etap="' + esc(etap.status) + '">' +
                    (etap.status === 'spakowane'
                        ? '<i class="fas fa-check lg-etap-znak" aria-hidden="true"></i>'
                        : '<span class="lg-etap-znak" aria-hidden="true"></span>') +
                    '<span class="lg-etap-nazwa">' + esc(etap.nazwa || etap.status) + '</span></span>' +
                '</div>';
        }).join('') : '<div class="lg-pozycja lg-pozycja--pusto">Zamówienie nie ma pozycji.</div>';
        return '<tr class="lg-pozycje-wiersz" data-pozycje-dla="' + esc(w.id) + '">' +
            '<td colspan="10"><div class="lg-pozycje" id="lg-pozycje-' + esc(w.id) + '" role="region"' +
            ' aria-label="' + esc('Pozycje zamówienia ' + w.numer) + '">' + tresc + '</div></td></tr>';
    }

    function wierszHtml(w) {
        const etap = w.etap || { status: '', nazwa: '' };
        const anulowane = etap.status === 'anulowane';
        const wysylany = stan.wysylane.has(w.id) || oczekujaceSelecty.has(w.id);
        const zaznaczony = stan.zaznaczone.has(w.id);

        const klasy = ['lg-wiersz'];
        if (!w.sposob) klasy.push('lg-wiersz--brak');
        if (zaznaczony) klasy.push('is-zaznaczony');
        if (stan.wskazany === w.id) klasy.push('is-wskazany');
        if (w.zamkniete) klasy.push('is-zamkniete');
        if (anulowane) klasy.push('is-anulowane');
        if (wysylany) klasy.push('is-wysylanie');
        const rozwiniety = stan.rozwiniete.has(w.id);
        if (rozwiniety) klasy.push('is-rozwiniety');

        // Blokady selecta — te same warunki, na których backend odmówiłby zmiany.
        let powod = '';
        if (w.wydane) powod = 'Zamówienie wydane klientowi. Sposobu dostawy nie można już zmienić.';
        else if (anulowane) powod = 'Zamówienie anulowane.';
        else if (stan.wysylane.has(w.id)) powod = 'Zapisywanie…';

        const metoda = w.metoda_z_base
            ? '<span class="lg-metoda" title="' + esc(w.metoda_z_base) + '">' + esc(w.metoda_z_base) + '</span>'
            : '<span class="lg-metoda lg-brak-danych">brak w Base.</span>';
        let podpowiedz = '';
        if (w.podpowiedz && w.podpowiedz !== w.sposob) {
            // Logo Base. zamiast słowa „Podpowiedź:” — słowo zabierało ~60 px i ucinało
            // „Transport własny”. To samo logo stoi na „Przyjmij podpowiedzi z Base.”
            // i w legendzie; obrazek dekoracyjny (alt=""), znaczenie niesie tekst i title.
            const nazwa = ETYKIETY[w.podpowiedz] || w.podpowiedz;
            podpowiedz = '<span class="lg-podpowiedz' + (w.sposob ? '' : ' lg-podpowiedz--kolejka') + '"' +
                ' title="Podpowiedź z Base.: ' + esc(nazwa) + '">' +
                (LOGO_BASE ? '<img class="lg-logo-base" src="' + esc(LOGO_BASE) + '" alt="" width="16" height="16">' : '') +
                '<span class="visually-hidden">Podpowiedź z Base.: </span>' + esc(nazwa) + '</span>';
        }

        const ikony = [];
        if (w.przepakowanie) ikony.push(ikona('fa-box-open', 'lg-ikona--przepakowanie', 'Czeka na przepakowanie na kuriera'));
        if (w.etykiety_sprzed_zmiany) ikony.push(ikona('fa-tags', 'lg-ikona--etykiety', 'Etykiety wydrukowane przed zmianą sposobu dostawy'));
        if (w.base_czeka) ikony.push(ikona('fa-cloud-arrow-up', 'lg-ikona--base', 'Base.: czeka na wysłanie'));
        if (w.geo && w.geo.adres_zmieniony) {
            ikony.push(ikona('fa-map-location-dot', 'lg-ikona--adres',
                'Adres zmieniony po ręcznym ustawieniu punktu. Sprawdź punkt na mapie.'));
        }

        let akcja = '';
        if (w.wydane) {
            akcja = '<span class="lg-wydane" title="Wydane klientowi ' + esc(dataKrotka(w.wydane) + ', ' + godzina(w.wydane)) + '">' +
                '<i class="fas fa-check" aria-hidden="true"></i><span>Wydane</span>' +
                '<span class="lg-wydane-data">' + esc(dataKrotka(w.wydane)) + '</span></span>';
        } else if (w.sposob === 'odbior_osobisty' && w.spakowane) {
            akcja = '<button type="button" class="lg-przycisk lg-przycisk--wydaj" data-lg-akcja="wydaj"' +
                (stan.wysylane.has(w.id) ? ' disabled' : '') + '>' +
                'Wydane klientowi</button>';
        } else if (w.zamkniete) {
            akcja = '<span class="lg-pigulka">Zamknięte</span>';
        }

        const m3 = Number(w.m3) > 0 ? liczbaM3.format(Number(w.m3)) : '—';

        return '<tr class="' + klasy.join(' ') + '" data-id="' + esc(w.id) + '">' +
            '<td class="lg-k-zaznacz"><div class="lg-zaznacz-komorka"><label class="lg-zaznacz-pole">' +
                '<input type="checkbox" class="lg-zaznacz" aria-label="Zaznacz zamówienie ' + esc(w.numer) + '"' +
                (zaznaczony ? ' checked' : '') + '></label>' +
                // Trójkąt jak na liście produktów; rozwija też klik w tło wiersza.
                '<button type="button" class="lg-rozwin" data-lg-akcja="rozwin" aria-expanded="' + rozwiniety + '"' +
                ' aria-controls="lg-pozycje-' + esc(w.id) + '"' +
                ' aria-label="' + esc((rozwiniety ? 'Zwiń' : 'Pokaż') + ' pozycje zamówienia ' + w.numer) + '">' +
                '<span aria-hidden="true">▶</span></button></div></td>' +
            // Numer zamówienia w Base. tylko w podpowiedzi: druga linia poszerzała
            // kolumnę o ~25 px, a na 1280 px z panelem bocznym liczy się każdy piksel.
            '<td class="lg-k-numer"><div class="lg-numer-komorka">' + przyciskMapy(w) +
                '<span class="lg-numer"' +
                (w.baselinker_order_id ? ' title="Numer w Base.: ' + esc(w.baselinker_order_id) + '"' : '') + '>' +
                esc(w.numer) + '</span></div></td>' +
            '<td class="lg-k-klient"><span class="lg-klient"' + (w.klient ? ' title="' + esc(w.klient) + '"' : '') + '>' +
                (w.klient ? esc(w.klient) : '<span class="lg-brak-danych">brak nazwy</span>') + '</span>' +
                // Zawsze, także bez adresu: poniżej 1100 px to jedyne miejsce, z którego
                // da się go dodać (kolumna „Adres” jest schowana) — przegląd W2.
                '<span class="lg-w-klient-adres">' + adresHtml(w) + '</span>' +
                '<span class="lg-drugi lg-w-klient-metoda" title="' + esc(w.metoda_z_base || '') + '">Base.: ' +
                    esc(w.metoda_z_base || 'brak') + '</span>' +
                (podpowiedz ? '<span class="lg-w-klient-metoda">' + podpowiedz + '</span>' : '') + '</td>' +
            '<td class="lg-k-adres">' + adresHtml(w) + '</td>' +
            '<td class="lg-k-metoda">' + metoda + podpowiedz + '</td>' +
            '<td class="lg-k-sposob">' + selectSposobu(w, !!powod, powod) + plakietkaTrasy(w) + '</td>' +
            '<td class="lg-k-etap"><span class="lg-etap" data-etap="' + esc(etap.status) + '">' +
                (etap.status === 'spakowane'
                    ? '<i class="fas fa-check lg-etap-znak" aria-hidden="true"></i>'
                    : '<span class="lg-etap-znak" aria-hidden="true"></span>') +
                '<span class="lg-etap-nazwa">' + esc(etap.nazwa || etap.status) + '</span></span></td>' +
            '<td class="lg-k-termin">' + komorkaTerminu(w.termin) + '</td>' +
            '<td class="lg-k-m3"><span class="lg-m3">' + m3 + '</span></td>' +
            '<td class="lg-k-stan"><div class="lg-stan-komorka">' +
                (ikony.length ? '<span class="lg-ikony">' + ikony.join('') + '</span>' : '') + akcja +
            '</div></td>' +
            '</tr>' + (rozwiniety ? pozycjeHtml(w) : '');
    }

    // Rozwinięcie wiersza: klik w tło wiersza albo w trójkąt. Bez przerysowania
    // całej tabeli — dokładamy albo zdejmujemy tylko wiersz pozycji.
    function przelaczRozwiniecie(id) {
        const w = znajdz(id);
        const tr = tbody.querySelector('tr[data-id="' + id + '"]');
        if (!w || !tr) return;
        const rozwin = !stan.rozwiniete.has(id);
        if (rozwin) stan.rozwiniete.add(id); else stan.rozwiniete.delete(id);
        const stary = tr.nextElementSibling;
        if (stary && stary.hasAttribute('data-pozycje-dla')) stary.remove();
        if (rozwin) tr.insertAdjacentHTML('afterend', pozycjeHtml(w));
        tr.classList.toggle('is-rozwiniety', rozwin);
        const przycisk = tr.querySelector('.lg-rozwin');
        if (przycisk) {
            przycisk.setAttribute('aria-expanded', String(rozwin));
            przycisk.setAttribute('aria-label', (rozwin ? 'Zwiń' : 'Pokaż') + ' pozycje zamówienia ' + w.numer);
        }
    }

    function renderujTabele() {
        const widoczne = widoczneWiersze();
        // Zaznaczenie obejmuje tylko to, co widać — akcja hurtowa nie może
        // dotknąć wiersza schowanego filtrem.
        const ids = new Set(widoczne.map((w) => w.id));
        stan.zaznaczone.forEach((id) => { if (!ids.has(id)) stan.zaznaczone.delete(id); });

        const fokus = fokusWiersza(tbody);

        tbody.innerHTML = widoczne.length ? widoczne.map(wierszHtml).join('') : pustyStan();
        tabela.classList.toggle('is-bez-geo', stan.filtr.geo === 'brak');
        stan.naLiscie = widoczne.map((w) => w.id);
        renderujIle();
        renderujZaznaczenie();
        przekazDoMapy();
        przywrocFokus(fokus, tbody);
    }

    // Fokus klawiatury w wierszu (select sposobu, pinezka / „Ustaw na mapie”,
    // checkbox) przeżywa przerysowanie — ten sam rodzaj pola w tym samym wierszu.
    // Adres jest w wierszu dwa razy (pod klientem i w kolumnie) — stąd także kolumna.
    const KLASY_FOKUSU = ['lg-sposob', 'lg-na-mapie', 'lg-zaznacz', 'lg-rozwin', 'lg-adres', 'lg-plakietka-trasy'];

    function fokusWiersza(kontener) {
        const a = document.activeElement;
        const tr = a && kontener.contains(a) ? a.closest('tr[data-id]') : null;
        const klasa = tr ? KLASY_FOKUSU.find((k) => a.classList.contains(k)) : null;
        if (!klasa) return null;
        const td = a.closest('td');
        const kolumna = td ? Array.from(td.classList).find((k) => k.indexOf('lg-k-') === 0) : null;
        return { id: tr.getAttribute('data-id'), klasa: klasa, kolumna: kolumna || null };
    }

    function przywrocFokus(fokus, kontener) {
        if (!fokus) return;
        const cel = kontener.querySelector('tr[data-id="' + fokus.id + '"] ' +
            (fokus.kolumna ? 'td.' + fokus.kolumna + ' ' : '') + '.' + fokus.klasa);
        if (cel && !cel.disabled) cel.focus({ preventScroll: true });
    }

    // Podmiana wierszy odpowiedzią API — BEZ przeładowania listy. Wiersz, który
    // przestał pasować do filtra (np. dostał sposób przy filtrze „Nie ustawiono”),
    // zostaje na miejscu do następnego odświeżenia: lista nie ucieka spod
    // kursora, a logistyk widzi, co właśnie zmienił.
    // `zmienione` (opcjonalnie): id, które naprawdę się zmieniły — tylko one
    // dostają błysk; wiersz odrzucony albo bez zmiany przerysowuje się po cichu.
    function podmienWiersze(zamowienia, zmienione) {
        (zamowienia || []).forEach((nowy) => {
            const i = stan.wiersze.findIndex((w) => w.id === nowy.id);
            if (i === -1) return;
            const stary = stan.wiersze[i];
            przeliczLiczniki(stary, nowy);
            stan.wiersze[i] = nowy;
            odswiezWiersz(nowy.id, !zmienione || zmienione.includes(nowy.id));
        });
        renderujLiczniki();
        renderujEtapy();
        renderujFiltrGeo();
        renderujIle();
        renderujGeo();
        przekazDoMapy();
    }

    // Liczniki liczą otwarte zamówienia wg sposobu. Zamiast dociągać całą listę
    // po każdej zmianie przesuwamy jedną jednostkę; zegar i tak wyrówna je co 60 s.
    function przeliczLiczniki(stary, nowy) {
        const l = stan.liczniki;
        if (!l) return;
        if (stary && !stary.zamkniete) l[kluczSposobu(stary)] = Math.max(0, (Number(l[kluczSposobu(stary)]) || 0) - 1);
        if (nowy && !nowy.zamkniete) l[kluczSposobu(nowy)] = (Number(l[kluczSposobu(nowy)]) || 0) + 1;
    }

    function odswiezWiersz(id, blysk) {
        const w = znajdz(id);
        const tr = tbody.querySelector('tr[data-id="' + id + '"]');
        if (!w || !tr) return;
        const fokus = fokusWiersza(tr);
        const tmp = document.createElement('tbody');
        tmp.innerHTML = wierszHtml(w);
        const nowyTr = tmp.firstElementChild;
        const pozycje = tr.nextElementSibling;
        if (pozycje && pozycje.hasAttribute('data-pozycje-dla')) pozycje.remove();
        const nowePozycje = nowyTr.nextElementSibling;
        tr.replaceWith(nowyTr);
        if (nowePozycje) nowyTr.after(nowePozycje);
        if (blysk) nowyTr.classList.add('is-zmieniony');
        przywrocFokus(fokus, tbody);
    }

    // ── Zaznaczanie ─────────────────────────────────────────────────────────

    function renderujZaznaczenie() {
        const widoczne = widoczneWiersze();
        const n = stan.zaznaczone.size;
        const wszystkie = el('zaznacz-wszystkie');
        wszystkie.checked = n > 0 && n === widoczne.length;
        wszystkie.indeterminate = n > 0 && n < widoczne.length;
        wszystkie.disabled = widoczne.length === 0;
        el('hurt').hidden = n === 0;
        el('hurt-ile').textContent = String(n);
        root.querySelectorAll('.lg-hurt button').forEach((b) => { b.disabled = stan.hurtTrwa; });
    }

    function ustawZaznaczenie(id, zaznacz) {
        if (zaznacz) stan.zaznaczone.add(id); else stan.zaznaczone.delete(id);
        const tr = tbody.querySelector('tr[data-id="' + id + '"]');
        if (tr) {
            tr.classList.toggle('is-zaznaczony', zaznacz);
            const box = tr.querySelector('.lg-zaznacz');
            if (box) box.checked = zaznacz;
        }
    }

    function klikCheckboxa(box, zShiftem) {
        const tr = box.closest('tr');
        const id = Number(tr.getAttribute('data-id'));
        const zaznacz = box.checked;
        if (zShiftem && stan.ostatniKlik !== null) {
            const kolejnosc = widoczneWiersze().map((w) => w.id);
            const a = kolejnosc.indexOf(stan.ostatniKlik);
            const b = kolejnosc.indexOf(id);
            if (a !== -1 && b !== -1) {
                kolejnosc.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((x) => ustawZaznaczenie(x, zaznacz));
            }
        }
        ustawZaznaczenie(id, zaznacz);
        stan.ostatniKlik = id;
        renderujZaznaczenie();
    }

    function odznaczWszystko() {
        Array.from(stan.zaznaczone).forEach((id) => ustawZaznaczenie(id, false));
        stan.ostatniKlik = null;
        renderujZaznaczenie();
    }

    // ── Komunikaty ──────────────────────────────────────────────────────────

    const IKONY_KOMUNIKATU = {
        ok: 'fa-circle-check', uwaga: 'fa-box-open', blad: 'fa-circle-exclamation', info: 'fa-circle-info',
    };

    /**
     * typ: ok | uwaga | blad | info. Treść i pozycje listy idą przez textContent
     * (bez HTML). ok/info znikają same po 6 s, uwaga i błąd czekają na zamknięcie.
     * lista: [{numer, tekst}], ponow: przycisk „Spróbuj ponownie” (odświeża listę),
     * ikona (etap 3): klasa Font Awesome zamiast domyślnej dla typu.
     * Komunikat trafia do podzakładki, na której jest logistyk (etap 3: Trasy i Flota
     * mają własne miejsce na komunikaty — w schowanym Dashboardzie nikt by ich nie zobaczył).
     * widok (oględziny Task 8, M16): stała podzakładka komunikatu — np. wynik lokalizowania
     * w tle dotyczy mapy i listy Dashboardu, więc nie pojawia się we Flocie.
     * Publicznie: window.LogisticsTab.komunikat (logistics-routes.js, logistics-fleet.js).
     */
    function pokazKomunikat(typ, tresc, opcje) {
        const o = opcje || {};
        if (o.klucz) usunKomunikat(o.klucz);
        const box = document.createElement('div');
        box.className = 'lg-komunikat lg-komunikat--' + typ;
        box.setAttribute('role', typ === 'blad' ? 'alert' : 'status');
        if (o.klucz) box.setAttribute('data-klucz', o.klucz);

        const ik = document.createElement('i');
        ik.className = 'fas ' + (o.ikona || IKONY_KOMUNIKATU[typ] || IKONY_KOMUNIKATU.info);
        ik.setAttribute('aria-hidden', 'true');
        box.appendChild(ik);

        const cialo = document.createElement('div');
        cialo.className = 'lg-komunikat-tresc';
        const tekst = document.createElement('span');
        tekst.textContent = tresc;
        cialo.appendChild(tekst);
        if (o.ponow) {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'lg-przycisk';
            b.setAttribute('data-lg-akcja', 'ponow');
            b.textContent = 'Spróbuj ponownie';
            cialo.appendChild(b);
        }
        if (o.lista && o.lista.length) {
            const ul = document.createElement('ul');
            ul.className = 'lg-komunikat-lista';
            o.lista.forEach((poz) => {
                const li = document.createElement('li');
                if (poz.numer) {
                    const b = document.createElement('b');
                    b.textContent = poz.numer;
                    li.appendChild(b);
                }
                li.appendChild(document.createTextNode(poz.tekst || ''));
                ul.appendChild(li);
            });
            cialo.appendChild(ul);
        }
        box.appendChild(cialo);

        const x = document.createElement('button');
        x.type = 'button';
        x.className = 'lg-komunikat-zamknij';
        x.setAttribute('aria-label', 'Zamknij komunikat');
        x.setAttribute('data-lg-akcja', 'zamknij-komunikat');
        x.textContent = '×';
        box.appendChild(x);

        const widok = WIDOKI.includes(o.widok) ? o.widok : stan.widok;
        (root.querySelector('[data-lg-komunikaty="' + widok + '"]') || el('komunikaty')).appendChild(box);
        if (typ === 'ok' || typ === 'info') {
            setTimeout(() => { if (box.isConnected) box.remove(); }, 6000);
        }
    }

    function usunKomunikat(klucz) {
        root.querySelectorAll('.lg-komunikat[data-klucz="' + klucz + '"]').forEach((k) => k.remove());
    }

    // ── Zmiana sposobu dostawy ──────────────────────────────────────────────

    function numerZamowienia(id, zamowienia) {
        const z = (zamowienia || []).find((o) => o.id === id) || znajdz(id);
        return z ? z.numer : '#' + id;
    }

    /** Jedno żądanie POST /orders/delivery-method (≤ 500 id). */
    async function wyslijSposob(ids, sposob) {
        ids.forEach((id) => {
            stan.wysylane.add(id);
            stan.docelowe.set(id, sposob);
            odswiezWiersz(id, false);
        });
        try {
            return await zapytanie('/orders/delivery-method', {
                metoda: 'POST', dane: { order_ids: ids, sposob: sposob },
            });
        } finally {
            ids.forEach((id) => {
                stan.wysylane.delete(id);
                stan.docelowe.delete(id);
            });
        }
    }

    // (oględziny Task 8, M14) Tekst serwera zwykle sam zaczyna się od numeru („Zamówienie
    // 1512 jest na zatwierdzonej trasie…”) — wtedy numer przed nim byłby drugi raz.
    function pozycjaOdmowy(numer, tekst) {
        const t = String(tekst || '');
        return { numer: numer && t.indexOf(String(numer)) === -1 ? numer : '', tekst: t };
    }

    /** Wynik jednej lub kilku odpowiedzi → wiersze + komunikaty. */
    function podsumujZmiany(wynik, pojedynczo, opisAkcji) {
        podmienWiersze(wynik.orders, wynik.zmienione);
        const numer = (id) => numerZamowienia(id, wynik.orders);

        if (!pojedynczo) {
            const n = wynik.zmienione.length;
            if (n) {
                pokazKomunikat('ok', opisAkcji + ': ' + ileZamowien(n) + '.', { klucz: 'wynik' });
            } else if (!wynik.bledy.length) {
                pokazKomunikat('info', 'Nic się nie zmieniło. Zaznaczone zamówienia miały już ten sposób dostawy.',
                    { klucz: 'wynik' });
            }
        }
        if (wynik.przepakowanie.length) {
            const numery = wynik.przepakowanie.map(numer).join(', ');
            pokazKomunikat('uwaga', wynik.przepakowanie.length === 1
                ? 'Zamówienie ' + numery + ' wraca do pakowania: czeka na przepakowanie na kuriera.'
                : 'Wracają do pakowania, czekają na przepakowanie na kuriera: ' + numery + '.');
        }
        if (wynik.bledy.length) {
            const n = wynik.bledy.length;
            // Dopełniacz po przeczeniu: „nie zmieniono 1 zamówienia / 2 zamówień”.
            pokazKomunikat('blad', 'Nie zmieniono ' + n + ' ' + odmiana(n, ['zamówienia', 'zamówień', 'zamówień']) + ':', {
                lista: wynik.bledy.map((b) => pozycjaOdmowy(numer(b.order_id), b.komunikat)),
            });
        }
        if (wynik.usunieto_z_trasy.length) pokazUsunieteZTras(wynik.usunieto_z_trasy, numer);
    }

    /**
     * Etap 3: zmiana sposobu zamówienia z trasy roboczej sama zdejmuje je z trasy
     * (usunieto_z_trasy: [{order_id, trasa: nazwa}]) — logistyk ma to zobaczyć, a trasy
     * (lista, edytor, mapa tras) odświeżyć się same (zdarzenie dla logistics-routes.js).
     */
    function pokazUsunieteZTras(usuniete, numer) {
        const wgTras = new Map();
        usuniete.forEach((u) => {
            const nazwa = String(u.trasa || '');
            if (!wgTras.has(nazwa)) wgTras.set(nazwa, []);
            wgTras.get(nazwa).push(numer(u.order_id));
        });
        wgTras.forEach((numery, nazwa) => {
            let tresc;
            if (numery.length === 1) tresc = 'Zamówienie ' + numery[0] + ' usunięto z trasy „' + nazwa + '”.';
            else if (numery.length <= 6) tresc = 'Zamówienia ' + numery.join(', ') + ' usunięto z trasy „' + nazwa + '”.';
            else tresc = 'Z trasy „' + nazwa + '” usunięto ' + ileZamowien(numery.length) + '.';
            pokazKomunikat('uwaga', tresc, { ikona: 'fa-route' });
        });
        document.dispatchEvent(new CustomEvent('logistics:trasy-zmienione', { detail: { root: root } }));
    }

    function nowyWynik() {
        return { zmienione: [], przepakowanie: [], bledy: [], orders: [], usunieto_z_trasy: [] };
    }

    function dolacz(wynik, dane) {
        wynik.zmienione = wynik.zmienione.concat(dane.zmienione || []);
        wynik.przepakowanie = wynik.przepakowanie.concat(dane.przepakowanie || []);
        wynik.bledy = wynik.bledy.concat(dane.bledy || []);
        wynik.orders = wynik.orders.concat(dane.orders || []);
        wynik.usunieto_z_trasy = wynik.usunieto_z_trasy.concat(dane.usunieto_z_trasy || []);
    }

    // Select w wierszu: od razu (po krótkiej zwłoce, patrz ZWLOKA_SELECTA_MS)
    // jedno żądanie dla jednego zamówienia.
    function zmianaSelecta(select) {
        const tr = select.closest('tr');
        const id = Number(tr.getAttribute('data-id'));
        const w = znajdz(id);
        if (!w) return;
        clearTimeout(oczekujaceSelecty.get(id));
        oczekujaceSelecty.delete(id);
        stan.docelowe.delete(id);
        const wartosc = select.value;
        if (!wartosc || wartosc === (w.sposob || 'brak')) {
            tr.classList.remove('is-wysylanie');
            return;
        }
        tr.classList.add('is-wysylanie');
        stan.docelowe.set(id, wartosc);
        oczekujaceSelecty.set(id, setTimeout(async () => {
            oczekujaceSelecty.delete(id);
            if (zniszczona) return;
            try {
                const dane = await wyslijSposob([id], wartosc);
                const wynik = nowyWynik();
                dolacz(wynik, dane);
                podsumujZmiany(wynik, true);
            } catch (e) {
                // Select wraca do stanu z serwera.
                odswiezWiersz(id, false);
                pokazKomunikat('blad', 'Nie zmieniono sposobu dostawy zamówienia ' + w.numer + '. ' + e.message);
            }
        }, ZWLOKA_SELECTA_MS));
    }

    async function hurtowo(grupy, opisAkcji) {
        // grupy: Map(sposob → [id]); po jednym żądaniu na sposób (i na paczkę 500 id).
        stan.hurtTrwa = true;
        renderujZaznaczenie();
        const wynik = nowyWynik();
        let bladPolaczenia = null;
        try {
            for (const [sposob, ids] of grupy) {
                for (let i = 0; i < ids.length; i += LIMIT_HURTU) {
                    const paczka = ids.slice(i, i + LIMIT_HURTU);
                    try {
                        dolacz(wynik, await wyslijSposob(paczka, sposob));
                    } catch (e) {
                        bladPolaczenia = e;
                        paczka.forEach((id) => odswiezWiersz(id, false));
                    }
                }
            }
        } finally {
            stan.hurtTrwa = false;
        }
        if (zniszczona) return;
        podsumujZmiany(wynik, false, opisAkcji);
        if (bladPolaczenia) {
            pokazKomunikat('blad', 'Część zmian nie została zapisana. ' + bladPolaczenia.message);
        } else {
            odznaczWszystko();
        }
        renderujZaznaczenie();
    }

    function hurtSposob(sposob) {
        const ids = Array.from(stan.zaznaczone);
        if (!ids.length || !SPOSOBY.includes(sposob)) return;
        hurtowo(new Map([[sposob, ids]]), 'Ustawiono „' + ETYKIETY[sposob] + '”');
    }

    function hurtPodpowiedzi() {
        const wybrane = Array.from(stan.zaznaczone).map(znajdz).filter(Boolean);
        const doZmiany = wybrane.filter((w) => w.podpowiedz && SPOSOBY.includes(w.podpowiedz) && w.podpowiedz !== w.sposob);
        if (!doZmiany.length) {
            pokazKomunikat('info', 'Zaznaczone zamówienia mają już sposób dostawy zgodny z podpowiedzią z Base.',
                { klucz: 'wynik' });
            return;
        }
        // Podpowiedź nie powinna po cichu nadpisać decyzji, którą ktoś już podjął.
        const nadpisze = doZmiany.filter((w) => w.sposob);
        if (nadpisze.length && !window.confirm(
            ileZamowien(nadpisze.length) + ' z zaznaczonych ' +
            odmiana(nadpisze.length, ['ma', 'mają', 'ma']) + ' już ustawiony inny sposób dostawy. ' +
            'Zastąpić go podpowiedzią z Base.?')) {
            return;
        }
        const grupy = new Map();
        doZmiany.forEach((w) => {
            if (!grupy.has(w.podpowiedz)) grupy.set(w.podpowiedz, []);
            grupy.get(w.podpowiedz).push(w.id);
        });
        hurtowo(grupy, 'Przyjęto podpowiedzi z Base.');
    }

    // ── Trasy (etap 3): „Dodaj do trasy…” i podzakładki ─────────────────────

    /**
     * Okno „Dodaj do trasy…” żyje w logistics-routes.js (window.LogisticsRoutes) —
     * tu tylko przekazujemy wiersze i podmieniamy je odpowiedzią (plakietka trasy od razu).
     * Obietnica daje null, gdy logistyk zamknął okno bez dodawania.
     */
    function dodajDoTrasy(wiersze, powrot, poDodaniu) {
        const trasy = window.LogisticsRoutes;
        if (!trasy || trasy.root !== root || typeof trasy.dodajDoTrasy !== 'function') {
            // (oględziny Task 8, m6) Plik tras się nie wczytał (loader stawia data-lg-trasy-blad)
            // — mówimy prawdę, zamiast w nieskończoność „jeszcze się wczytują”.
            if (root.hasAttribute('data-lg-trasy-blad')) {
                pokazKomunikat('blad', 'Nie udało się wczytać tras. Odśwież stronę, żeby spróbować ponownie.',
                    { klucz: 'trasa' });
            } else {
                pokazKomunikat('info', 'Trasy jeszcze się wczytują. Spróbuj za chwilę.', { klucz: 'trasa' });
            }
            return;
        }
        trasy.dodajDoTrasy(wiersze, { powrot: powrot }).then((wynik) => {
            if (zniszczona || !wynik) return;
            if (wynik.orders && wynik.orders.length) podmienWiersze(wynik.orders, wynik.dodane);
            if (poDodaniu) poDodaniu(wynik);
        }).catch((e) => console.error('[Logistyka] Dodaj do trasy:', e));
    }

    /**
     * (oględziny Task 8, I3) Po udanym hurtowym „Dodaj do trasy…” pasek hurtu znika razem
     * z przyciskiem, z którego otwarto okno — fokus idzie na plakietkę trasy pierwszego
     * dodanego wiersza (widać od razu, na jakiej trasie jest), a gdy tego wiersza nie ma na
     * liście — na wyszukiwarkę listy.
     */
    function fokusPoDodaniuDoTrasy(dodane) {
        const ids = new Set((dodane || []).map(Number));
        const tr = Array.from(tbody.querySelectorAll('tr[data-id]'))
            .find((w) => ids.has(Number(w.getAttribute('data-id'))));
        const cel = (tr && tr.querySelector('.lg-plakietka-trasy')) || el('q');
        if (cel && cel.offsetParent !== null) cel.focus();
    }

    function hurtTrasa(przycisk) {
        const wybrane = Array.from(stan.zaznaczone).map(znajdz).filter(Boolean);
        if (!wybrane.length) return;
        dodajDoTrasy(wybrane, przycisk, (wynik) => {
            if (!wynik.dodane || !wynik.dodane.length) return;
            odznaczWszystko();
            fokusPoDodaniuDoTrasy(wynik.dodane);
        });
    }

    /**
     * Podzakładka Dashboard | Trasy | Flota bez przeładowania. opcje.route_id — trasa do
     * otwarcia w edytorze (logistics-routes.js czyta ją z panelu tras, także gdy wczyta
     * się dopiero po tym wywołaniu). Powrót na Dashboard odświeża listę zamówień (trasy
     * mogły ją zmienić), a mapę przerysowuje jej własny ResizeObserver.
     */
    function pokazWidok(widok, opcje) {
        if (zniszczona || !WIDOKI.includes(widok)) return false;
        const o = opcje || {};
        const poprzedni = stan.widok;
        const aktywny = document.activeElement;
        const panelPoprzedni = root.querySelector('[data-logistics-view="' + poprzedni + '"]');
        const fokusZnika = poprzedni !== widok && !!(aktywny && panelPoprzedni && panelPoprzedni.contains(aktywny));
        stan.widok = widok;
        let zakladka = null;
        root.querySelectorAll('[data-lg-widok]').forEach((b) => {
            const ta = b.getAttribute('data-lg-widok') === widok;
            b.classList.toggle('is-aktywna', ta);
            b.setAttribute('aria-selected', ta ? 'true' : 'false');
            b.tabIndex = ta ? 0 : -1;
            if (ta) zakladka = b;
        });
        root.querySelectorAll('[data-logistics-view]').forEach((p) => {
            p.hidden = p.getAttribute('data-logistics-view') !== widok;
        });
        // „Stan na” i „Odśwież” dotyczą listy zamówień — poza Dashboardem niewidoczne
        // (miejsce zostaje, nagłówek nie skacze).
        const akcje = root.querySelector('.lg-naglowek-akcje');
        if (akcje) akcje.classList.toggle('is-ukryte', widok !== 'dashboard');
        if (!o.bezZapisu) {
            try { window.localStorage.setItem(KLUCZ_WIDOKU_LS, widok); } catch (e) { /* wybór nie przeżyje przeładowania */ }
        }
        if (o.route_id !== undefined && o.route_id !== null) {
            const panelTras = root.querySelector('[data-logistics-view="routes"]');
            if (panelTras) panelTras.setAttribute('data-lg-otworz-trase', String(o.route_id));
        }
        // Fokus w chowanym panelu (np. klik w plakietkę trasy) przechodzi na zakładkę.
        if (fokusZnika && zakladka) zakladka.focus({ preventScroll: true });
        if (widok === 'dashboard' && poprzedni !== 'dashboard') {
            dopasujWysokosc();
            if (!stan.pierwszeLadowanie) wczytaj('uzytkownik');
        }
        document.dispatchEvent(new CustomEvent('logistics:widok', { detail: { root: root, widok: widok, opcje: o } }));
        return true;
    }

    // Strzałki / Home / End na pasku podzakładek (wzorzec ARIA „tabs”, aktywacja od razu).
    function klawiszZakladek(e) {
        const zakladki = Array.from(root.querySelectorAll('[data-lg-widok]'));
        const i = zakladki.indexOf(e.target.closest ? e.target.closest('[data-lg-widok]') : null);
        if (i === -1) return;
        let j = null;
        if (e.key === 'ArrowRight') j = (i + 1) % zakladki.length;
        else if (e.key === 'ArrowLeft') j = (i - 1 + zakladki.length) % zakladki.length;
        else if (e.key === 'Home') j = 0;
        else if (e.key === 'End') j = zakladki.length - 1;
        if (j === null) return;
        e.preventDefault();
        pokazWidok(zakladki[j].getAttribute('data-lg-widok'));
        zakladki[j].focus();
    }

    // ── Wydane klientowi ────────────────────────────────────────────────────

    async function wydaj(id) {
        const w = znajdz(id);
        if (!w || stan.wysylane.has(id)) return;
        if (!window.confirm('Zamówienie ' + w.numer + ' zostało odebrane przez klienta?')) return;
        stan.wysylane.add(id);
        odswiezWiersz(id, false);
        try {
            const dane = await zapytanie('/orders/' + encodeURIComponent(id) + '/handed-over', { metoda: 'POST', dane: {} });
            stan.wysylane.delete(id);
            if (zniszczona) return;
            podmienWiersze([dane.order]);
            pokazKomunikat('ok', 'Zamówienie ' + w.numer + ' wydane klientowi.', { klucz: 'wynik' });
        } catch (e) {
            stan.wysylane.delete(id);
            odswiezWiersz(id, false);
            pokazKomunikat('blad', 'Nie oznaczono wydania zamówienia ' + w.numer + '. ' + e.message);
        }
    }

    // ── Lokalizacja: licznik „Bez lokalizacji”, „Zlokalizuj teraz” ─────────

    function przyjmijStanGeo(dane) {
        if (dane.bez_lokalizacji !== undefined && dane.bez_lokalizacji !== null) {
            stan.bezLokalizacji = Number(dane.bez_lokalizacji) || 0;
        }
        const dziala = !!dane.geokoder_dziala || Date.now() < stan.ochronaGeoDo;
        if (stan.geokoderDziala && !dziala) {
            // (oględziny Task 8, M16) Wynik dotyczy mapy i listy — tylko na Dashboardzie.
            pokazKomunikat('ok', 'Lokalizowanie zakończone. Bez lokalizacji: ' +
                (stan.bezLokalizacji === null ? '–' : stan.bezLokalizacji) + '.', { klucz: 'geo', widok: 'dashboard' });
        }
        stan.geokoderDziala = dziala;
        stan.geokoderPostep = dziala ? postepGeokodera(dane.geokoder_postep) : null;
        if (dziala && !timerStanuGeo) planujStanGeo(STAN_GEO_MS);
    }

    function planujStanGeo(ms) {
        clearTimeout(timerStanuGeo);
        timerStanuGeo = zniszczona ? null : setTimeout(sprawdzStanGeo, ms);
    }

    // Lekkie GET /geocode co STAN_GEO_MS, póki przebieg trwa: odświeża tylko
    // przycisk i licznik. Na koniec lista odświeża się przy najbliższej ciszy
    // (zegar), żeby dociągnąć nowe pinezki bez przerywania pracy logistyka.
    async function sprawdzStanGeo() {
        timerStanuGeo = null;
        if (zniszczona || !stan.geokoderDziala) return;
        if (!zakladkaWidoczna()) {
            // Schowana zakładka nie potrzebuje postępu co 1,5 s (przegląd D16).
            planujStanGeo(STAN_GEO_MS * 5);
            return;
        }
        try {
            const dane = await zapytanie('/geocode');
            if (zniszczona) return;
            przyjmijStanGeo(dane);
            renderujGeo();
            if (!stan.geokoderDziala) stan.ostatnieOdswiezenie = 0;
        } catch (e) {
            if (!zniszczona && stan.geokoderDziala) planujStanGeo(STAN_GEO_MS * 3);
        }
    }

    // geokoder_postep: null albo {zrobione, wszystkie}; `wszystkie` rośnie, gdy
    // przebieg dokłada zamówienia dodane w trakcie. Bez sensownych liczb → null
    // (przycisk mówi wtedy samo „Lokalizowanie…”).
    function postepGeokodera(p) {
        if (!p || typeof p !== 'object') return null;
        const wszystkie = Number(p.wszystkie);
        const zrobione = Number(p.zrobione);
        if (!Number.isFinite(wszystkie) || !Number.isFinite(zrobione) || wszystkie <= 0) return null;
        return { zrobione: Math.min(Math.max(0, Math.floor(zrobione)), wszystkie), wszystkie: Math.floor(wszystkie) };
    }

    function renderujGeo() {
        const licznik = el('bez-lokalizacji-przycisk');
        const n = stan.bezLokalizacji;
        el('bez-lokalizacji').textContent = n === null ? '–' : String(n);
        const bezGeo = stan.filtr.geo === 'brak';
        licznik.classList.toggle('is-aktywny', bezGeo);
        licznik.classList.toggle('is-niepusty', !!n);
        licznik.setAttribute('aria-pressed', bezGeo ? 'true' : 'false');
        // Przy zerze nie ma czego pokazać — chyba że filtr jest włączony (trzeba go zdjąć).
        licznik.disabled = !n && !bezGeo;
        licznik.title = bezGeo
            ? 'Pokaż wszystkie zamówienia z listy'
            : 'Pokaż na liście zamówienia bez punktu na mapie';
        // Globalny licznik + ile z nich jest w zawężonym widoku (sposób, etap, fraza).
        const widok = el('bez-lokalizacji-widok');
        const zawezony = n !== null && zawezonyWidok();
        widok.textContent = zawezony ? '· w widoku ' + bezGeoWWidoku() : '';
        widok.hidden = !zawezony;

        // W toku: przycisk nieaktywny, „Lokalizowanie… 37 / 120” i pasek wypełnienia
        // w tle (proporcja zrobione / wszystkie). Zanim wątek poda postęp — bez liczb.
        const przycisk = el('zlokalizuj');
        const p = stan.geokoderDziala ? stan.geokoderPostep : null;
        przycisk.disabled = stan.geokoderDziala;
        przycisk.classList.toggle('is-w-toku', stan.geokoderDziala);
        przycisk.classList.toggle('ma-postep', !!p);
        przycisk.title = stan.geokoderDziala
            ? 'Lokalizowanie w tle' + (p ? ': ' + p.zrobione + ' z ' + p.wszystkie : '…')
            : 'Znajdź na mapie adresy zamówień, które jeszcze nie mają punktu';
        el('zlokalizuj-tekst').textContent = stan.geokoderDziala ? 'Lokalizowanie…' : 'Zlokalizuj teraz';
        const liczby = el('zlokalizuj-liczby');
        liczby.textContent = p ? Math.floor(100 * p.zrobione / p.wszystkie) + '%' : '';
        liczby.hidden = !p;
        el('zlokalizuj-postep').style.width = p ? (100 * p.zrobione / p.wszystkie).toFixed(1) + '%' : '0%';
        if (stan.geokoderDziala) {
            przycisk.setAttribute('aria-label', p
                ? 'Lokalizowanie adresów w tle: ' + Math.floor(100 * p.zrobione / p.wszystkie) +
                    '% (' + p.zrobione + ' z ' + p.wszystkie + ')'
                : 'Lokalizowanie adresów w tle');
        } else {
            przycisk.removeAttribute('aria-label');
        }
    }

    function ustawFiltrGeo(wartosc) {
        stan.filtr.geo = wartosc;
        stan.dopasujMape = true;
        renderujFiltrGeo();
        renderujGeo();
        renderujTabele();
    }

    // Licznik „Bez lokalizacji” przełącza filtr lokalizacji na „Bez lokalizacji” i z powrotem.
    function przelaczBezGeo() {
        ustawFiltrGeo(stan.filtr.geo === 'brak' ? '' : 'brak');
    }

    async function zlokalizujTeraz(ciche) {
        if (stan.geokoderDziala || zniszczona) return;
        stan.geokoderDziala = true;
        stan.geokoderPostep = null;
        stan.ochronaGeoDo = Date.now() + OCHRONA_GEO_MS;
        renderujGeo();
        try {
            await zapytanie('/geocode', { metoda: 'POST', dane: {} });
            if (zniszczona) return;
            if (!ciche) {
                pokazKomunikat('info', 'Lokalizowanie w tle. Postęp widać na przycisku nad mapą.',
                    { klucz: 'geo' });
            }
            // Postęp z GET /geocode zaraz po starcie wątku; lista odświeży się z zegara.
            stan.ostatnieOdswiezenie = Date.now();
            planujStanGeo(700);
        } catch (e) {
            if (zniszczona) return;
            stan.geokoderDziala = false;
            stan.ochronaGeoDo = 0;
            renderujGeo();
            pokazKomunikat('blad', 'Nie uruchomiono lokalizowania. ' + e.message, { klucz: 'geo' });
        }
    }

    // ── Mapa (window.LogisticsMap z logistics-map.js) ───────────────────────

    // Tylko mapa tego fragmentu — po forceRefresh stara instancja może jeszcze
    // wisieć w window, zanim wykona się nowy logistics-map.js.
    function mapa() {
        const m = window.LogisticsMap;
        return m && m.root === root ? m : null;
    }

    function polaczZMapa() {
        const m = mapa();
        if (!m || m === mapaPolaczona || zniszczona) return;
        mapaPolaczona = m;
        m.onSelect(naWyborNaMapie);
        m.onZmiana(naZmianePunktu);
        if (typeof m.onBlad === 'function') m.onBlad(naBladMapy);
        przekazDoMapy();
        // Kolory tras na plakietkach pochodzą z mapy — wiersze na trasach dostają je teraz.
        if (!stan.pierwszeLadowanie && stan.wiersze.some((w) => w.trasa)) renderujTabele();
    }

    // (oględziny Task 8, A2) Odmowa zapisu punktu, gdy logistyk pracuje już nad następnym
    // zamówieniem (pasek mapy należy do niego) — komunikat na Dashboardzie, gdzie jest mapa.
    function naBladMapy(tekst) {
        if (zniszczona || !tekst) return;
        pokazKomunikat('blad', tekst, { widok: 'dashboard' });
    }

    function naGotowaMape(e) {
        if (e.detail && e.detail.root === root) polaczZMapa();
    }

    /** Mapa pokazuje dokładnie wiersze z tabeli (filtry, etap, wyszukiwarka). */
    function przekazDoMapy() {
        const m = mapa();
        if (!m || m !== mapaPolaczona) return;
        const ids = new Set(stan.naLiscie);
        const dopasuj = stan.dopasujMape;
        stan.dopasujMape = false;
        try {
            m.render(stan.wiersze.filter((w) => ids.has(w.id)), { dopasuj: dopasuj });
        } catch (e) {
            console.error('[Logistyka] Mapa nie przyjęła listy:', e);
        }
    }

    function pokazNaMapie(id, jawnie) {
        const w = znajdz(id);
        const m = mapa();
        if (!w || !w.geo) return;
        if (!m) {
            if (jawnie) pokazKomunikat('info', 'Mapa jeszcze się wczytuje.', { klucz: 'mapa' });
            return;
        }
        // Stronę do mapy (układ mapa-nad-listą) przewija tylko jawny przycisk pinezki,
        // nie zwykły klik w wiersz — logistyk nie traci miejsca na liście.
        if (!m.highlight(id, { przewin: jawnie }) && jawnie && m.zajeta()) {
            pokazKomunikat('info', 'Najpierw zakończ ustawianie punktu na mapie (Esc anuluje).', { klucz: 'mapa' });
        }
    }

    function ustawNaMapie(id) {
        const w = znajdz(id);
        const m = mapa();
        if (!w) return;
        if (!m || !m.ustawNaMapie(w)) {
            pokazKomunikat('blad', 'Mapa nie jest gotowa. Odśwież zakładkę i spróbuj ponownie.', { klucz: 'mapa' });
        }
    }

    // Klik w wiersz (poza polami, przyciskami i zaznaczaniem tekstu) = pokaż na mapie.
    // Klik w tło wiersza rozwija pozycje zamówienia (jak na liście produktów).
    // Pola, przyciski i adres (dwuklik = poprawka) mają swoje działanie; na mapę
    // prowadzi pinezka przy numerze. Zaznaczony tekst = kopiowanie, nie klik.
    function klikWiersza(e) {
        const tr = e.target.closest('tr[data-id]');
        if (!tr || !tbody.contains(tr)) return;
        if (e.target.closest('input, select, label, button, a, textarea, [data-lg-adres]')) return;
        const zaznaczenie = window.getSelection ? String(window.getSelection()) : '';
        if (zaznaczenie) return;
        przelaczRozwiniecie(Number(tr.getAttribute('data-id')));
    }

    function naWyborNaMapie(id, info) {
        if (zniszczona) return;
        stan.wskazany = id === undefined ? null : id;
        tbody.querySelectorAll('tr.is-wskazany').forEach((tr) => tr.classList.remove('is-wskazany'));
        if (stan.wskazany === null) return;
        const tr = tbody.querySelector('tr[data-id="' + stan.wskazany + '"]');
        if (!tr) return;
        tr.classList.add('is-wskazany');
        // Klik w pinezkę przewija listę do wiersza; klik w wiersz — nie.
        if (info && info.zrodlo === 'mapa') {
            // Obok mapy przewija się ramka tabeli, w układzie piętrowym — strona.
            const r = tr.getBoundingClientRect();
            const ramka = tr.closest('.lg-tabela-ramka');
            const rr = ramka && ramka.scrollHeight > ramka.clientHeight ? ramka.getBoundingClientRect() : null;
            const gora = rr ? rr.top + 40 : 60;
            const dol = rr ? rr.bottom - 10 : (window.innerHeight || document.documentElement.clientHeight) - 60;
            if (r.top < gora || r.bottom > dol) {
                const bezRuchu = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
                tr.scrollIntoView({ block: 'center', behavior: bezRuchu ? 'auto' : 'smooth' });
            }
        }
    }

    /** Punkt zapisany na mapie (ustawiony, poprawiony, przywrócony automat). */
    function naZmianePunktu(order, rodzaj) {
        if (zniszczona || !order) return;
        const stary = znajdz(order.id);
        if (stan.bezLokalizacji !== null && !order.zamkniete && stary) {
            if (!stary.geo && order.geo) stan.bezLokalizacji = Math.max(0, stan.bezLokalizacji - 1);
            if (stary.geo && !order.geo) stan.bezLokalizacji += 1;
        }
        podmienWiersze([order]);
        // Przywrócony automat: od razu uruchamiamy lokalizowanie w tle.
        if (rodzaj === 'przywrocono') zlokalizujTeraz(true);
    }

    // ── Poprawka adresu (dwuklik w adres) ───────────────────────────────────

    const dialogAdresu = el('adres-dialog');
    const formAdresu = el('adres-form');
    let adresDla = null;            // id zamówienia w otwartym oknie
    let adresZapis = false;
    let adresPowrot = null;         // element, na który wraca fokus po zamknięciu

    function otworzAdres(id, zrodlo) {
        const w = znajdz(id);
        if (!w || !dialogAdresu || dialogAdresu.open) return;
        adresDla = id;
        adresPowrot = zrodlo || null;
        el('adres-numer').textContent = w.numer || '';
        formAdresu.elements.adres.value = w.adres || '';
        formAdresu.elements.kod.value = w.kod || '';
        formAdresu.elements.miasto.value = w.miasto || '';
        bladAdresu('');
        ustawZapisAdresu(false);
        dialogAdresu.showModal();
        formAdresu.elements.adres.focus();
        formAdresu.elements.adres.select();
    }

    function bladAdresu(tekst) {
        const p = el('adres-blad');
        p.textContent = tekst;
        p.hidden = !tekst;
    }

    function ustawZapisAdresu(trwa) {
        adresZapis = trwa;
        el('adres-zapisz').disabled = trwa;
        el('adres-zapisz').textContent = trwa ? 'Zapisywanie…' : 'Zapisz';
        // „Anuluj” w trakcie zapisu zgubiłby odpowiedź, także błąd (przegląd D12).
        el('adres-anuluj').disabled = trwa;
        Array.from(formAdresu.elements).forEach((pole) => {
            if (pole.tagName === 'INPUT') pole.readOnly = trwa;
        });
    }

    // Zamyka okno i od razu oddaje fokus adresowi zamówienia (także przerysowanemu po
    // zapisie — wtedy szuka go po id w tej samej kolumnie: „Adres” albo pod klientem).
    // Nie w zdarzeniu `close`: przychodzi asynchronicznie, a fokus ma wrócić zawsze.
    function zamknijAdres() {
        if (!dialogAdresu || !dialogAdresu.open) return;
        const id = adresDla;
        let cel = adresPowrot;
        adresDla = null;
        adresPowrot = null;
        dialogAdresu.close();
        if (cel && !cel.isConnected && id !== null) {
            const podKlientem = !!cel.closest('.lg-w-klient-adres');
            cel = tbody.querySelector('tr[data-id="' + id + '"] ' +
                (podKlientem ? '.lg-w-klient-adres' : '.lg-k-adres') + ' [data-lg-adres]');
        }
        if (cel && cel.isConnected) cel.focus({ preventScroll: true });
    }

    async function zapiszAdres() {
        if (adresZapis || adresDla === null) return;
        const id = adresDla;
        const w = znajdz(id);
        const dane = {
            adres: formAdresu.elements.adres.value.trim(),
            kod: formAdresu.elements.kod.value.trim(),
            miasto: formAdresu.elements.miasto.value.trim(),
        };
        if (!dane.adres || !dane.miasto) {
            bladAdresu('Podaj ulicę z numerem i miejscowość.');
            (dane.adres ? formAdresu.elements.miasto : formAdresu.elements.adres).focus();
            return;
        }
        ustawZapisAdresu(true);
        bladAdresu('');
        const numer = w ? w.numer : '#' + id;
        try {
            const odp = await zapytanie('/orders/' + id + '/address', { metoda: 'PUT', dane: dane });
            if (zniszczona) return;
            // Okno mogło zniknąć bez nas (Chrome: drugi Esc zamyka mimo preventDefault)
            // albo pokazuje już inne zamówienie — wtedy nie ruszamy go, wynik w komunikacie.
            const nadal = adresDla === id;
            if (nadal) ustawZapisAdresu(false);
            // Najpierw nowy wiersz, potem zamknięcie — fokus wraca już na przerysowany adres.
            if (odp.order) podmienWiersze([odp.order], odp.zmieniono ? [id] : []);
            if (nadal) zamknijAdres();
            if (odp.zmieniono) {
                pokazKomunikat('ok', 'Adres zamówienia ' + numer + ' zapisany. Wyślemy go do Base., ' +
                    'a punkt na mapie ustalimy od nowa.', { klucz: 'adres' });
                // Geokoder ruszył w tle — przycisk „Zlokalizuj teraz” pokaże postęp.
                stan.geokoderDziala = true;
                stan.ochronaGeoDo = Date.now() + OCHRONA_GEO_MS;
                renderujGeo();
                planujStanGeo(700);
            } else {
                pokazKomunikat('info', 'Adres zamówienia ' + numer + ' bez zmian.', { klucz: 'adres' });
            }
        } catch (e) {
            if (zniszczona) return;
            if (adresDla === id) {
                ustawZapisAdresu(false);
                bladAdresu('Nie zapisano adresu. ' + e.message);
            } else {
                pokazKomunikat('blad', 'Nie zapisano adresu zamówienia ' + numer + '. ' + e.message,
                    { klucz: 'adres' });
            }
        }
    }

    if (formAdresu) {
        formAdresu.addEventListener('submit', (e) => {
            e.preventDefault();
            zapiszAdres();
        });
        // Zamknięcie inną drogą niż zamknijAdres() (np. wymuszone przez przeglądarkę)
        // też kończy „okno dla zamówienia X” — patrz `nadal` w zapiszAdres().
        dialogAdresu.addEventListener('close', () => {
            adresDla = null;
            adresPowrot = null;
        });
        dialogAdresu.addEventListener('cancel', (e) => {
            // Esc: zamykamy sami (z oddaniem fokusu); w trakcie zapisu wcale — odpowiedź
            // i tak musi trafić do listy.
            e.preventDefault();
            if (!adresZapis) zamknijAdres();
        });
        // Klik w tło okna (poza formularzem) zamyka je, jak Esc.
        dialogAdresu.addEventListener('click', (e) => {
            if (e.target === dialogAdresu && !adresZapis) zamknijAdres();
        });
    }

    root.addEventListener('dblclick', (e) => {
        const adres = e.target.closest('[data-lg-adres]');
        const tr = adres && adres.closest('tr[data-id]');
        if (!tr || !tbody.contains(tr)) return;
        e.preventDefault();
        if (window.getSelection) window.getSelection().removeAllRanges();  // dwuklik zaznacza słowo
        otworzAdres(Number(tr.getAttribute('data-id')), adres);
    });

    // ── Wysokość układu obok siebie ─────────────────────────────────────────
    // Lista i mapa mają wspólną wysokość: do dołu okna (min. 440 px). Tabela
    // przewija się w swojej ramce — bez tego strona rosła z każdym zamówieniem.

    function przewijanyRodzic(start) {
        for (let e = start.parentElement; e; e = e.parentElement) {
            const o = getComputedStyle(e).overflowY;
            if ((o === 'auto' || o === 'scroll') && e.clientHeight > 0) return e;
        }
        return null;
    }

    function dopasujWysokosc() {
        // Tylko czy zakładka jest wyrenderowana (schowana .tab-pane nie ma wymiarów);
        // document.hidden nie przeszkadza — liczymy z układu, nie z klatek.
        if (zniszczona || !root.isConnected || !root.getClientRects().length) return;
        const siatka = root.querySelector('.lg-uklad-siatka');
        // Etap 3: schowany panel Dashboardu (inna podzakładka) nie ma wymiarów — liczymy
        // dopiero po powrocie (pokazWidok).
        if (!siatka || !siatka.getClientRects().length) return;
        const rodzic = przewijanyRodzic(root);
        const widok = rodzic ? rodzic.clientHeight : window.innerHeight;
        // Pozycja w treści przewijanego rodzica — niezależnie od bieżącego przewinięcia.
        const poczatek = rodzic ? rodzic.getBoundingClientRect().top - rodzic.scrollTop : -window.scrollY;
        const gora = siatka.getBoundingClientRect().top - poczatek;
        // Odstępy POD siatką (padding zakładki, panelu, .main-content) mierzymy po
        // kolei w górę drzewa, zamiast zgadywać stałą: każdy przodek dokłada tyle,
        // o ile jego dół wystaje poniżej dołu dziecka.
        let ponizej = 0;
        let dziecko = siatka;
        for (let e = siatka.parentElement; e && e !== rodzic; e = e.parentElement) {
            ponizej += Math.max(0, e.getBoundingClientRect().bottom - dziecko.getBoundingClientRect().bottom);
            dziecko = e;
        }
        ponizej += parseFloat(getComputedStyle(rodzic || document.body).paddingBottom) || 0;
        const wys = Math.max(440, Math.floor(widok - gora - ponizej));
        siatka.style.setProperty('--lg-uklad-wys', wys + 'px');
        // Układ piętrowy (mapa nad listą): tabela też przewija się w ramce, najwyżej
        // na wysokość okna — CSS bierze stąd --lg-widok-wys.
        siatka.style.setProperty('--lg-widok-wys', Math.floor(widok) + 'px');
    }

    // ── Filtry ──────────────────────────────────────────────────────────────

    function ustawSposobFiltra(sposob) {
        // Drugie kliknięcie aktywnego licznika zdejmuje filtr.
        stan.filtr.sposob = stan.filtr.sposob === sposob ? '' : sposob;
        stan.dopasujMape = true;
        // Zmiana filtra kończy zaznaczenie od razu (także pasek hurtu), zanim
        // przyjdzie nowa lista — akcja nie może trafić w wiersze z poprzedniego widoku.
        odznaczWszystko();
        renderujLiczniki();
        wczytaj('uzytkownik');
    }

    /** Pusty stan „Bez lokalizacji” w zawężonym widoku: zostaje sam filtr „Bez lokalizacji”. */
    function zdejmijFiltry() {
        clearTimeout(timerSzukania);
        stan.filtr.sposob = '';
        stan.filtr.etap = '';
        stan.filtr.q = '';
        stan.filtr.zamkniete = false;
        el('q').value = '';
        stan.dopasujMape = true;
        renderujPrzelacznikZamknietych();
        odznaczWszystko();
        renderujLiczniki();
        wczytaj('uzytkownik');
    }

    function zmianaFrazy(natychmiast) {
        clearTimeout(timerSzukania);
        const q = el('q').value.trim();
        const wykonaj = () => {
            if (q === stan.filtr.q) return;
            stan.filtr.q = q;
            stan.dopasujMape = true;
            if (!q) stan.filtr.zamkniete = false;
            renderujPrzelacznikZamknietych();
            odznaczWszystko();
            wczytaj('uzytkownik');
        };
        if (natychmiast) wykonaj(); else timerSzukania = setTimeout(wykonaj, DEBOUNCE_SZUKAJ_MS);
    }

    // ── Zdarzenia (delegacja na korzeniu zakładki) ──────────────────────────

    root.addEventListener('click', (e) => {
        const zakladka = e.target.closest('[data-lg-widok]');
        if (zakladka) {
            pokazWidok(zakladka.getAttribute('data-lg-widok'));
            return;
        }
        const sortuj = e.target.closest('[data-lg-sort]');
        if (sortuj && tabela.contains(sortuj)) {
            ustawSortowanie(sortuj.getAttribute('data-lg-sort'));
            return;
        }
        const box = e.target.closest('.lg-zaznacz');
        if (box && tbody.contains(box)) {
            // `click`, nie `change` — tylko tu jest shiftKey do zaznaczania zakresu.
            klikCheckboxa(box, e.shiftKey);
            return;
        }
        const licznik = e.target.closest('[data-lg-sposob]');
        if (licznik) {
            ustawSposobFiltra(licznik.getAttribute('data-lg-sposob'));
            return;
        }
        const przycisk = e.target.closest('[data-lg-akcja]');
        if (!przycisk) {
            klikWiersza(e);
            return;
        }
        if (przycisk.disabled) return;
        const akcja = przycisk.getAttribute('data-lg-akcja');
        const tr = przycisk.closest('tr[data-id]');
        switch (akcja) {
            case 'odswiez':
            case 'ponow':
                usunKomunikat('odswiezanie');
                wczytaj('uzytkownik');
                break;
            case 'hurt-sposob':
                hurtSposob(przycisk.getAttribute('data-sposob'));
                break;
            case 'hurt-podpowiedzi':
                hurtPodpowiedzi();
                break;
            case 'hurt-trasa':
                hurtTrasa(przycisk);
                break;
            case 'dodaj-do-trasy': {
                const w = tr ? znajdz(Number(tr.getAttribute('data-id'))) : null;
                if (w) dodajDoTrasy([w], przycisk);
                break;
            }
            case 'pokaz-trase':
                pokazWidok('routes', { route_id: Number(przycisk.getAttribute('data-trasa-id')) });
                break;
            case 'odznacz':
                odznaczWszystko();
                break;
            case 'wydaj':
                if (tr) wydaj(Number(tr.getAttribute('data-id')));
                break;
            case 'pokaz-wszystkie':
                stan.filtr.sposob = '';
                stan.dopasujMape = true;
                renderujLiczniki();
                wczytaj('uzytkownik');
                break;
            case 'szukaj-zamkniete':
                el('zamkniete').checked = true;
                stan.filtr.zamkniete = true;
                stan.dopasujMape = true;
                wczytaj('uzytkownik');
                break;
            case 'wszystkie-etapy':
                stan.filtr.etap = '';
                stan.dopasujMape = true;
                renderujEtapy();
                renderujGeo();
                renderujTabele();
                break;
            case 'zdejmij-filtry':
                zdejmijFiltry();
                break;
            case 'zamknij-komunikat':
                przycisk.closest('.lg-komunikat').remove();
                break;
            case 'bez-lokalizacji':
                przelaczBezGeo();
                break;
            case 'wszystkie-lokalizacje':
                ustawFiltrGeo('');
                break;
            case 'adres-anuluj':
                if (!adresZapis) zamknijAdres();
                break;
            case 'zlokalizuj':
                zlokalizujTeraz(false);
                break;
            case 'pokaz-na-mapie':
                if (tr) pokazNaMapie(Number(tr.getAttribute('data-id')), true);
                break;
            case 'rozwin':
                if (tr) przelaczRozwiniecie(Number(tr.getAttribute('data-id')));
                break;
            case 'ustaw-na-mapie':
                if (tr) ustawNaMapie(Number(tr.getAttribute('data-id')));
                break;
            case 'do-listy': {
                // Bez zmiany adresu (#) — fokus na tabeli, następny Tab to pierwszy wiersz.
                e.preventDefault();
                const lista = root.querySelector('#logistics-lista');
                if (lista) lista.focus();
                break;
            }
            default:
                break;
        }
    });

    root.addEventListener('change', (e) => {
        const t = e.target;
        if (t.classList.contains('lg-sposob')) {
            zmianaSelecta(t);
        } else if (t === el('zaznacz-wszystkie')) {
            const zaznacz = t.checked;
            widoczneWiersze().forEach((w) => ustawZaznaczenie(w.id, zaznacz));
            stan.ostatniKlik = null;
            renderujZaznaczenie();
        } else if (t === el('zamkniete')) {
            stan.filtr.zamkniete = t.checked && !!stan.filtr.q;
            stan.dopasujMape = true;
            odznaczWszystko();
            wczytaj('uzytkownik');
        } else if (t === el('etap')) {
            stan.filtr.etap = t.value;
            stan.dopasujMape = true;
            t.classList.toggle('is-aktywny', !!t.value);
            renderujGeo();   // „· w widoku k” liczy się po etapie
            renderujTabele();
        } else if (t === el('geo')) {
            ustawFiltrGeo(t.value);
        }
    });

    // Enter / spacja na adresie (fokus z klawiatury) = dwuklik myszą.
    root.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const adres = e.target.closest && e.target.closest('[data-lg-adres]');
        const tr = adres && adres.closest('tr[data-id]');
        if (!tr || !tbody.contains(tr)) return;
        e.preventDefault();
        otworzAdres(Number(tr.getAttribute('data-id')), adres);
    });

    const odnotujAktywnosc = () => { ostatniaAktywnosc = Date.now(); };
    root.addEventListener('pointerdown', odnotujAktywnosc);
    root.addEventListener('keydown', odnotujAktywnosc);

    el('q').addEventListener('input', () => zmianaFrazy(false));
    el('q').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            zmianaFrazy(true);
        } else if (e.key === 'Escape' && el('q').value) {
            e.preventDefault();
            el('q').value = '';
            zmianaFrazy(true);
        }
    });

    // ── Odświeżanie co 60 s ─────────────────────────────────────────────────

    function zakladkaWidoczna() {
        // Nieaktywna zakładka panelu to .tab-pane bez .active (display: none).
        return !document.hidden && root.isConnected && root.getClientRects().length > 0;
    }

    function uzytkownikPracuje() {
        return stan.zaznaczone.size > 0 || stan.hurtTrwa || stan.wysylane.size > 0 ||
            oczekujaceSelecty.size > 0 || !!kontrolerListy ||
            // Korekta / ustawianie punktu na mapie — odświeżenie nie może jej przerwać.
            !!(mapa() && mapa().zajeta()) ||
            // Otwarte okno poprawki adresu (etap 3: też „Dodaj do trasy…” i inne okna zakładki).
            !!(dialogAdresu && dialogAdresu.open) || !!root.querySelector('dialog[open]') ||
            // Rozwinięta lista selecta zniknęłaby spod ręki razem z przerysowaną
            // tabelą. Otwarcia natywnego selecta nie da się odczytać, więc
            // czekamy na chwilę ciszy po ostatnim kliknięciu/klawiszu.
            Date.now() - ostatniaAktywnosc < CISZA_PRZED_ODSWIEZENIEM_MS;
    }

    function tik() {
        if (zniszczona || stan.pierwszeLadowanie) return;
        // Etap 3: na Trasach i Flocie lista stoi — odświeży się przy powrocie na Dashboard.
        if (stan.widok !== 'dashboard') return;
        if (!zakladkaWidoczna() || uzytkownikPracuje()) return;
        const okres = stan.geokoderDziala ? ODSWIEZANIE_GEO_MS : ODSWIEZANIE_MS;
        if (Date.now() - stan.ostatnieOdswiezenie >= okres) wczytaj('auto');
    }

    function przyWidocznosci() {
        if (!document.hidden) {
            dopasujWysokosc();
            tik();
        }
    }

    function zniszcz() {
        zniszczona = true;
        clearInterval(zegar);
        clearTimeout(timerSzukania);
        clearTimeout(timerStanuGeo);
        window.removeEventListener('resize', dopasujWysokosc);
        document.removeEventListener('shown.bs.tab', naPokazanieZakladki);
        if (obserwatorWysokosci) obserwatorWysokosci.disconnect();
        zamknijAdres();
        oczekujaceSelecty.forEach((t) => clearTimeout(t));
        oczekujaceSelecty.clear();
        if (kontrolerListy) kontrolerListy.abort();
        document.removeEventListener('visibilitychange', przyWidocznosci);
        document.removeEventListener('logistics:mapa-gotowa', naGotowaMape);
        if (window.LogisticsTab && window.LogisticsTab.zniszcz === zniszcz) delete window.LogisticsTab;
    }

    // ── Start ───────────────────────────────────────────────────────────────

    window.LogisticsTab = {
        root: root,
        odswiez: () => wczytaj('uzytkownik'),
        // Etap 3 — dla logistics-routes.js i logistics-fleet.js.
        komunikat: (typ, tresc, opcje) => pokazKomunikat(typ, tresc, opcje),
        pokazWidok: pokazWidok,
        zniszcz: zniszcz,
    };

    // Ostatnia podzakładka w tej przeglądarce (etap 3). Lista wczytuje się i tak —
    // powrót na Dashboard jest wtedy od razu gotowy.
    const pasekZakladek = root.querySelector('.lg-podzakladki');
    if (pasekZakladek) pasekZakladek.addEventListener('keydown', klawiszZakladek);
    let zapamietanyWidok = 'dashboard';
    try {
        const v = window.localStorage.getItem(KLUCZ_WIDOKU_LS);
        if (WIDOKI.includes(v)) zapamietanyWidok = v;
    } catch (e) { /* bez localStorage — Dashboard */ }
    pokazWidok(zapamietanyWidok, { bezZapisu: true });

    function naPokazanieZakladki(e) {
        if (e.target && e.target.id === 'logistics-tab') dopasujWysokosc();
    }

    // Przegląd D13: `shown.bs.tab` w tym panelu w praktyce nie przychodzi (loader
    // zakładek sam przełącza .active), a zmiana okna na innej zakładce zostawiała starą
    // wysokość. Obserwujemy szerokość korzenia: schowany = 0, pokazany albo szerszy/
    // węższy (też zwinięty panel boczny) = przeliczenie. Samą zmianę wysokości (w tym
    // naszą, z --lg-uklad-wys) pomijamy — bez pętli.
    let szerokoscKorzenia = null;
    const obserwatorWysokosci = typeof ResizeObserver === 'function'
        ? new ResizeObserver((wpisy) => {
            const szerokosc = Math.round(wpisy[wpisy.length - 1].contentRect.width);
            if (szerokosc === szerokoscKorzenia) return;
            szerokoscKorzenia = szerokosc;
            if (szerokosc > 0) dopasujWysokosc();
        })
        : null;

    document.addEventListener('visibilitychange', przyWidocznosci);
    document.addEventListener('logistics:mapa-gotowa', naGotowaMape);
    window.addEventListener('resize', dopasujWysokosc);
    document.addEventListener('shown.bs.tab', naPokazanieZakladki);
    if (obserwatorWysokosci) obserwatorWysokosci.observe(root);
    dopasujWysokosc();
    stan.sort = wczytajSortowanie();
    renderujSortowanie();
    polaczZMapa();
    zegar = setInterval(tik, ZEGAR_MS);
    renderujPrzelacznikZamknietych();
    wczytaj('uzytkownik');
})();
