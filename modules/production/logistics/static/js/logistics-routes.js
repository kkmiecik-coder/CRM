/**
 * Logistyka — podzakładka „Trasy” (etap 3), okno „Dodaj do trasy…” i widok tras
 * na mapie Dashboardu.
 * modules/production/logistics/static/js/logistics-routes.js
 *
 * Ładowanie: inline loader z tab_content.html, PO logistics-map.js (atrybut
 * data-skrypt-trasy na #logistics-map) — także gdy mapa się nie wczytała: lista
 * tras, edytor i „Dodaj do trasy…” działają bez niej, mapka edytora mówi wtedy,
 * że jej nie ma. Ponowne wykonanie (forceRefresh zakładki) sprząta po poprzedniej
 * instancji (window.LogisticsRoutes.zniszcz): zapytania, zegary, mapka, nasłuchy.
 *
 * Granice: z logistics.js korzystamy WYŁĄCZNIE przez window.LogisticsTab
 * (komunikat, pokazWidok), z mapy Dashboardu przez window.LogisticsMap
 * (ustawWidok, widok, renderTrasy, onWyborTrasy, nowaWarstwaPodkladu, kolorTrasy).
 *
 * API (modules/production/logistics/routers/trasy_api.py, panel_api.py):
 *   GET    {API}/routes[?status=&od=&do=]            lista (wykonane: domyślnie 30 dni)
 *   POST   {API}/routes                              nowa trasa → {route}
 *   GET    {API}/routes/map                          aktywne trasy z przebiegiem (mapa Dashboardu)
 *   GET    {API}/routes/<id>                         szczegóły → {route: {…, przystanki, przebieg}}
 *          przystanek = {pozycja, anulowane, zamowienie}: pozycja — numer wśród AKTYWNYCH
 *          przystanków (kolejność Routimo), null dla anulowanego; podsumowanie.przystanki —
 *          tylko aktywne, podsumowanie.anulowane — anulowane w całości
 *   PUT    {API}/routes/<id>                         zapis formularza (robocza)
 *   DELETE {API}/routes/<id>                         usunięcie (robocza)
 *   POST   {API}/routes/<id>/stops                   {order_ids} → {route, dodane, bledy}
 *   DELETE {API}/routes/<id>/stops/<order_id>        zdjęcie przystanku
 *   PUT    {API}/routes/<id>/stops/order             {order_ids} — nowa kolejność
 *   POST   {API}/routes/<id>/approve | /revert | /complete | /restore
 *          /complete {delivered_order_ids} (wymagane); 409 z `niespakowane` [id], gdy jako
 *          dostarczone oznaczono zamówienie, które nie jest w całości spakowane
 *   GET    {API}/routes/<id>/routimo                 plik .xlsx (zatwierdzona, wykonana);
 *          nagłówek X-Routimo-Pominiete = ile anulowanych przystanków pominięto
 *   GET    {API}/availability?date_from=&date_to=&route_id=   pojazdy i kierowcy, zajęci z nazwą trasy
 *   GET    {API}/orders?sposob=bez_trasy&q=          „Do dodania”
 * Odmowa to zawsze {success: false, error: „…”} (404/409/422) — tekst serwera
 * pokazujemy przy formularzu edytora albo w oknie.
 *
 * Publicznie: window.LogisticsRoutes = {root, otworz(route_id), dodajDoTrasy(zamowienia, opcje), zniszcz()}.
 * Każdy tekst z API przechodzi przez esc() albo textContent.
 *
 * Kontrakt ze zdarzeniami (wszystkie na document, detail.root = #logistics-root):
 *   `logistics:widok` {root, widok, opcje} (logistics.js, pokazWidok) — podzakładka na ekranie;
 *       widok 'routes' = pokazano(): świeża lista tras, dostępność pojazdów, trasa do otwarcia.
 *   atrybut `data-lg-otworz-trase` na panelu [data-logistics-view="routes"] — id trasy do
 *       otwarcia; stawia go pokazWidok('routes', {route_id}) (klik w plakietkę trasy na liście,
 *       w trasę na mapie), także ZANIM ten plik się wczyta. Zdejmujemy go przy otwieraniu.
 *   `logistics:trasy-zmienione` {root} (logistics.js) — zmiana sposobu dostawy zdjęła
 *       zamówienia z tras: lista, otwarta trasa i mapa tras pobierają się od nowa.
 *   `logistics:flota-zmieniona` {root} (logistics-fleet.js) — dostępność pojazdów od nowa.
 *   `logistics:podklad` {root, podklad} (logistics-map.js) — mapka edytora zmienia podkład
 *       razem z mapą Dashboardu.
 *   `logistics:mapa-gotowa` {root} (logistics-map.js) — łączymy się z mapą Dashboardu.
 *
 * Zmiany trasy (mutacja): jedna naraz NA TRASĘ, odpowiedź trafia do edytora tylko wtedy,
 * gdy użytkownik jest wciąż przy tej samej trasie (sesja edytora) — patrz przyjmijOdpowiedz.
 */
(function () {
    'use strict';

    if (window.LogisticsRoutes && typeof window.LogisticsRoutes.zniszcz === 'function') {
        try { window.LogisticsRoutes.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    const panel = root ? root.querySelector('[data-logistics-view="routes"]') : null;
    if (!root || !panel) return;

    // data-api = url_for('logistics_panel.orders') → baza bez końcowego /orders.
    const API = (root.getAttribute('data-api') || '/production/api/logistics/orders')
        .replace(/\/orders\/?$/, '');
    const L = window.L || null;

    // ── Stałe ───────────────────────────────────────────────────────────────

    const POLSKA = [[49.0, 14.1], [54.9, 24.2]];
    const ZOOM_DOPASOWANIA = 12;
    const ZWLOKA_KOLEJNOSCI_MS = 450;   // ↑↑↑ z klawiatury = jeden zapis, nie trzy
    const DNI_WYKONANYCH = 30;          // domyślne okno wykonanych, jak DNI_WYKONANYCH_DOMYSLNIE w API
    const ZWLOKA_DOSTEPNOSCI_MS = 250;
    const DEBOUNCE_SZUKAJ_MS = 300;
    // Jak WAGA_KG_NA_M3 w services/routes.py — tylko podgląd w oknie „Dodaj do trasy…”;
    // wagę trasy zawsze liczy serwer (podsumowanie).
    const WAGA_KG_NA_M3 = 800;
    const TRANSPORT = 'transport_woodpower';
    // Zakres roku w filtrze „Wykonane” (jak min/max w szablonie) — Chrome przepuszcza w polu
    // daty rok 5–6-cyfrowy (np. 92026), a serwer taki odrzuca (oględziny M5). Filtr przeszukuje
    // historię, więc granic dat trasy (niżej) celowo nie ma.
    const ROK_FILTRA_OD = 2000;
    const ROK_FILTRA_DO = 2099;
    // (M8) Granice dat trasy — jak services/routes.py (granice_dat): dziś − 1 rok … dziś + 2 lata,
    // „do” najwyżej 31 dni po „od”. Formularz trasy i okno „Dodaj do trasy…” liczą je przy
    // otwarciu (min/max pól), serwer i tak sprawdza to samo.
    const LATA_WSTECZ = 1;
    const LATA_NAPRZOD = 2;
    const MAKS_ROZPIETOSC_DNI = 31;
    // (oględziny M10) Zapas od krawędzi mapki przy dopasowaniu: z lewej kolumna +/−
    // i „Pokaż całą trasę”, u dołu atrybucja — żaden przystanek nie ląduje pod kontrolką.
    const MARGINES_MAPKI = { paddingTopLeft: [54, 30], paddingBottomRight: [30, 30] };

    const NAZWY_STATUSOW = { robocza: 'Robocza', zatwierdzona: 'Zatwierdzona', wykonana: 'Wykonana' };
    const IKONY_STATUSOW = { robocza: 'fa-pen', zatwierdzona: 'fa-lock', wykonana: 'fa-check' };
    // [akcja, etykieta, ikona, odmiana przycisku] — przyciski edytora wg statusu (R12:
    // „Odhacz jako wykonaną” także z roboczej).
    const AKCJE = {
        nowa: [
            ['utworz', 'Utwórz trasę', 'fa-plus', 'glowny'],
            ['anuluj-nowa', 'Anuluj', '', ''],
        ],
        robocza: [
            ['zapisz', 'Zapisz', 'fa-floppy-disk', ''],
            ['zatwierdz', 'Zatwierdź', 'fa-lock', 'glowny'],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
            ['usun', 'Usuń trasę', 'fa-trash-can', 'niebezpieczny'],
        ],
        zatwierdzona: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', 'glowny'],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
            ['cofnij', 'Cofnij do roboczej', 'fa-lock-open', ''],
        ],
        wykonana: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', ''],
            ['przywroc', 'Przywróć trasę', 'fa-rotate-left', ''],
        ],
    };

    const bezRuchu = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    const magazyn = {
        lat: parseFloat(root.getAttribute('data-magazyn-lat')),
        lng: parseFloat(root.getAttribute('data-magazyn-lng')),
        nazwa: root.getAttribute('data-magazyn-nazwa') || 'Magazyn',
    };

    // ── Elementy ────────────────────────────────────────────────────────────

    const el = (nazwa) => root.querySelector('[data-lg-trasy="' + nazwa + '"]');
    const uklad = el('uklad');
    const stanListyEl = el('stan');
    const listy = {
        robocza: { lista: el('robocze'), ile: el('robocze-ile') },
        zatwierdzona: { lista: el('zatwierdzone'), ile: el('zatwierdzone-ile') },
        wykonana: { lista: el('wykonane-lista'), ile: el('wykonane-ile') },
    };
    const filtrWykonanychEl = el('wykonane-filtr');
    const opisWykonanychEl = el('wykonane-opis');
    const edytor = el('edytor');
    const pustyEl = el('pusty');
    const trescEl = el('tresc');
    const ukladEdytoraEl = trescEl ? trescEl.querySelector('.lg-edytor-uklad') : null;
    const statusEl = el('status');
    const tytulEl = el('tytul');
    const akcjeEl = el('akcje');
    const bladEl = el('blad');
    const form = el('form');
    const polaEl = el('pola');
    const selectPojazdu = el('pojazd');
    const selectKierowcy = el('kierowca');
    const uwagaPojazduEl = el('uwaga-pojazd');
    const uwagaKierowcyEl = el('uwaga-kierowca');
    const podsumowanieEl = el('podsumowanie');
    const liniaEl = el('linia');
    const przystankiEl = el('przystanki');
    const przystankiStanEl = el('przystanki-stan');
    const ogloszenieEl = el('ogloszenie');
    const mapkaEl = el('mapka');
    const mapkaStanEl = el('mapka-stan');
    const kandydaciSekcja = el('kandydaci-sekcja');
    const kandydaciEl = el('kandydaci');
    const kandydaciQ = el('kandydaci-q');
    const kandydaciIleEl = el('kandydaci-ile');
    const dodajZaznaczoneBtn = root.querySelector('[data-lg-trasy-akcja="dodaj-zaznaczone"]');
    const dodajZaznaczoneTekst = el('dodaj-zaznaczone-tekst');
    const odswiezListeBtn = root.querySelector('[data-lg-trasy-akcja="odswiez-liste"]');
    const przelacznikMapy = root.querySelector('[data-lg-mapa="widoki"]');

    const dialogDodaj = root.querySelector('[data-lg="trasa-dodaj-dialog"]');
    const formDodaj = el('dodaj-form');
    const dodajIleEl = el('dodaj-ile');
    const dodajOpisEl = el('dodaj-opis');
    const dodajTrasyEl = el('dodaj-trasy');
    const dodajNowaEl = el('dodaj-nowa');
    const dodajBladEl = el('dodaj-blad');
    const dodajZapiszBtn = el('dodaj-zapisz');

    const dialogWykonaj = root.querySelector('[data-lg="trasa-wykonaj-dialog"]');
    const formWykonaj = el('wykonaj-form');
    const wykonajNazwaEl = el('wykonaj-nazwa');
    const wykonajListaEl = el('wykonaj-lista');
    const wykonajIleEl = el('wykonaj-ile');
    const wykonajBladEl = el('wykonaj-blad');
    const wykonajZapiszBtn = el('wykonaj-zapisz');

    // ── Stan ────────────────────────────────────────────────────────────────

    const stan = {
        trasy: [],                // GET /routes: robocze, zatwierdzone i wykonane z domyślnego okna
        listaWczytana: false,
        listaBlad: null,
        filtrWykonanych: null,    // null = domyślne okno serwera (30 dni); {od, do, trasy}
        otwarta: null,            // trasa w edytorze (odpowiedź GET /routes/<id>) albo null
        nowa: false,              // formularz nowej, jeszcze niezapisanej trasy
        kolejnosc: null,          // lokalna kolejność przystanków (id zamówień), zanim serwer ją przyjmie
        dostepnosc: null,         // {pojazdy, kierowcy} z GET /availability dla dat z formularza
        wybranyPojazd: '',        // wybór w selectach — przeżywa odświeżenie dostępności
        wybranyKierowca: '',
        migawka: '',              // pola formularza po wczytaniu / zapisie („niezapisane zmiany”)
        // (oględziny A1) Trasy ze zmianą w drodze: klucz trasy (kluczTrasy) → przyciski TEJ
        // trasy czekają; inną trasę można w tym czasie otworzyć i zmieniać.
        wToku: new Set(),
        // Numer sesji edytora — rośnie przy każdym przejściu do innej trasy, nowej trasy albo
        // zamknięciu edytora (resetEdytora). Odpowiedź mutacji z innej sesji nie przejmuje edytora.
        sesja: 0,
        kandydaci: [],
        kandydaciWczytani: false,
        kandydaciBlad: null,
        kandydaciQ: '',
        zaznaczeniKandydaci: new Set(),
        dodawani: new Set(),      // kandydaci w trakcie dodawania
    };

    let zniszczona = false;
    const sluchacze = new AbortController();   // jeden sygnał odpina wszystkie nasłuchy
    const naSluch = { signal: sluchacze.signal };
    let kontrolerListy = null;
    let kontrolerWykonanych = null;
    let kontrolerTrasy = null;
    let kontrolerDostepnosci = null;
    let kontrolerKandydatow = null;
    let kontrolerMapy = null;
    let timerDostepnosci = null;
    let timerSzukania = null;
    let timerKolejnosci = null;
    let kolejnoscObietnica = null;   // pętla zapisu kolejności (dokonczKolejnosc na nią czeka)
    let mapaPolaczona = null;        // window.LogisticsMap, z którą rozmawiamy
    let odpiecieMapy = null;         // odpina słuchacza onWyborTrasy
    let przeciagany = null;          // id zamówienia przeciąganego przystanku
    let chwytZPrzycisku = false;     // wciśnięcie zaczęło się na przycisku — to nie przeciąganie
    let dodawanie = null;            // otwarte okno „Dodaj do trasy…”
    const dodawaniaWTle = new Set(); // zapisy okna zamkniętego w trakcie (minor 3) — kończą się w tle
    let wykonywanie = null;          // otwarte okno „Odhacz jako wykonaną”
    // (oględziny m3) Trasy zmienione u nas (odpowiedź mutacji albo odczyt trasy): id →
    // {wersja, trasa (skrót listy) | null = usunięta}. Lista pobrana PRZED taką zmianą nie
    // nadpisuje jej starszym wierszem serwera (scalZLokalnymi).
    let licznikZmian = 0;
    const lokalneZmiany = new Map();

    // Mapka edytora — osobna instancja Leafleta.
    let mapka = null;
    let warstwaMapki = null;
    let kafelkiMapki = null;          // L.TileLayer podkładu mapki (podmieniany za mapą Dashboardu)
    let mapkaDopasowana = false;
    let mapkaCzekaNaDopasowanie = false;
    // (oględziny I2) Schowana mapka (rozmiar 0) po powrocie dopasowuje się do trasy od nowa —
    // chyba że użytkownik sam ją przesunął albo przybliżył od ostatniego dopasowania.
    let mapkaUkryta = false;
    let mapkaRuszona = false;
    let dopasowanieMapkiWToku = false;   // movestart dopasowania to nie ruch użytkownika
    let obserwatorMapki = null;
    const znacznikiMapki = new Map();   // id zamówienia → L.Marker przystanku

    // ── Pomocnicze ──────────────────────────────────────────────────────────

    function esc(wartosc) {
        if (wartosc === null || wartosc === undefined) return '';
        return String(wartosc).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    // Odmiana: 1 przystanek, 2–4 przystanki, 5+ przystanków (12–14 → przystanków).
    function odmiana(n, formy) {
        const d = n % 10;
        const s = n % 100;
        if (n === 1) return formy[0];
        if (d >= 2 && d <= 4 && (s < 12 || s > 14)) return formy[1];
        return formy[2];
    }

    const ZAMOWIENIE = ['zamówienie', 'zamówienia', 'zamówień'];
    const PRZYSTANEK = ['przystanek', 'przystanki', 'przystanków'];
    const ileZamowien = (n) => n + ' ' + odmiana(n, ZAMOWIENIE);
    const ilePrzystankow = (n) => n + ' ' + odmiana(n, PRZYSTANEK);

    const liczbaM3 = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
    const liczbaCala = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 });
    const liczbaKm = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const kg = (n) => liczbaCala.format(Math.round(Number(n) || 0)) + ' kg';

    function czasHM(minuty) {
        const m = Math.max(0, Math.round(Number(minuty) || 0));
        return Math.floor(m / 60) + ':' + String(m % 60).padStart(2, '0');
    }

    const dwa = (n) => String(n).padStart(2, '0');

    function dzisIso() {
        const d = new Date();
        return d.getFullYear() + '-' + dwa(d.getMonth() + 1) + '-' + dwa(d.getDate());
    }

    // 'RRRR-MM-DD' ± dni, kalendarzowo (w UTC — bez skoków przy zmianie czasu).
    function plusDni(iso, dni) {
        const [r, m, d] = String(iso).split('-').map(Number);
        const x = new Date(Date.UTC(r, m - 1, d + dni));
        return x.getUTCFullYear() + '-' + dwa(x.getUTCMonth() + 1) + '-' + dwa(x.getUTCDate());
    }

    // Ten sam dzień `lata` lat dalej (ujemne — wcześniej); 29.02 w roku zwykłym → 28.02, jak serwer.
    function oLata(iso, lata) {
        const [r, m, d] = String(iso).split('-').map(Number);
        const rok = r + lata;
        const ostatniDzien = new Date(Date.UTC(rok, m, 0)).getUTCDate();
        return rok + '-' + dwa(m) + '-' + dwa(Math.min(d, ostatniDzien));
    }

    function roznicaDni(od, doDnia) {
        const [r1, m1, d1] = String(od).split('-').map(Number);
        const [r2, m2, d2] = String(doDnia).split('-').map(Number);
        return Math.round((Date.UTC(r2, m2 - 1, d2) - Date.UTC(r1, m1 - 1, d1)) / 86400000);
    }

    // 'RRRR-MM-DD' → 'dd.mm.rrrr' — tak samo jak w komunikatach serwera.
    function dataPelna(iso) {
        const [r, m, d] = String(iso).split('-');
        return d + '.' + m + '.' + r;
    }

    /** (M8) Granice dat trasy na dziś: {min, max} jako 'RRRR-MM-DD' (patrz LATA_WSTECZ). */
    function graniceDat() {
        const dzis = dzisIso();
        return { min: oLata(dzis, -LATA_WSTECZ), max: oLata(dzis, LATA_NAPRZOD) };
    }

    // 'YYYY-MM-DD' → '25.09' (rok dopisany, gdy inny niż bieżący) — jak na liście zamówień.
    function dataKrotka(iso) {
        if (!iso) return '';
        const [r, m, d] = String(iso).slice(0, 10).split('-');
        if (!d) return String(iso);
        return d + '.' + m + (r !== String(new Date().getFullYear()) ? '.' + r : '');
    }

    function zakresDat(od, doDnia) {
        const a = dataKrotka(od);
        const b = dataKrotka(doDnia);
        return !b || a === b ? a : a + '–' + b;
    }

    function dniPoTerminie(iso) {
        const [r, m, d] = String(iso).split('-').map(Number);
        const dzis = new Date();
        return Math.round((Date.UTC(dzis.getFullYear(), dzis.getMonth(), dzis.getDate()) - Date.UTC(r, m - 1, d)) / 86400000);
    }

    // Wartość pola daty 'RRRR-MM-DD': rok czterocyfrowy, prawdziwy dzień (bez 31.02).
    function poprawnaData(v) {
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v || ''));
        if (!m) return false;
        const r = Number(m[1]);
        const d = new Date(Date.UTC(r, Number(m[2]) - 1, Number(m[3])));
        return d.getUTCFullYear() === r && d.getUTCMonth() === Number(m[2]) - 1 && d.getUTCDate() === Number(m[3]);
    }

    // Tylko filtr „Wykonane” — daty trasy mają ciaśniejsze granice (graniceDat).
    const rokWZakresie = (v) => {
        const r = Number(String(v).slice(0, 4));
        return r >= ROK_FILTRA_OD && r <= ROK_FILTRA_DO;
    };

    const wGranicach = (v, g) => poprawnaData(v) && v >= g.min && v <= g.max;

    /**
     * Błąd wartości daty 'RRRR-MM-DD' w formacie interfejsu (dd.mm.rrrr). granice — {min, max}
     * (formularz trasy, M8: ten sam tekst co serwer) albo null (filtr „Wykonane”: tylko rok
     * w rozsądnym zakresie), wymagane — pusta wartość to błąd.
     */
    function bladWartosciDaty(v, etykieta, wymagane, granice) {
        if (!v) return wymagane ? 'Podaj datę „' + etykieta + '”.' : null;
        if (!poprawnaData(v)) return 'Podaj datę „' + etykieta + '” w formacie dd.mm.rrrr.';
        if (granice) {
            if (!wGranicach(v, granice)) {
                return 'Data „' + etykieta + '” musi być między ' + dataPelna(granice.min) + ' a ' +
                    dataPelna(granice.max) + '.';
            }
        } else if (!rokWZakresie(v)) {
            return 'Sprawdź rok w dacie „' + etykieta + '” (dd.mm.rrrr, lata ' + ROK_FILTRA_OD + '–' + ROK_FILTRA_DO + ').';
        }
        return null;
    }

    /**
     * (oględziny M5) Błąd pola daty, zanim cokolwiek pójdzie do serwera. pole — <input type="date">
     * (niepełna data z klawiatury: validity.badInput, wartość pusta), etykieta — „od” / „do”.
     */
    function bladDaty(pole, etykieta, wymagane, granice) {
        if (pole && pole.validity && pole.validity.badInput) {
            return 'Podaj pełną datę „' + etykieta + '” w formacie dd.mm.rrrr.';
        }
        return bladWartosciDaty(pole ? pole.value : '', etykieta, wymagane, granice);
    }

    /**
     * (M8) min/max pól dat formularza trasy (edytor, okno „Dodaj do trasy…”): „od” w granicach
     * dat trasy, „do” od „od” najwyżej do „od” + 31 dni. Wołane przy otwarciu formularza i po
     * zmianie „od” — granice liczone od dzisiejszej daty w chwili otwarcia.
     */
    function ustawGraniceDat(formularz) {
        const od = formularz ? formularz.elements.namedItem('date_from') : null;
        const doDnia = formularz ? formularz.elements.namedItem('date_to') : null;
        if (!od || !doDnia) return;
        const g = graniceDat();
        od.min = g.min;
        od.max = g.max;
        const start = wGranicach(od.value, g) ? od.value : null;
        const koniec = start ? plusDni(start, MAKS_ROZPIETOSC_DNI) : g.max;
        doDnia.min = start || g.min;
        doDnia.max = koniec < g.max ? koniec : g.max;
    }

    // Trasa tylko do odczytu: bez min/max — jej daty mogą już być poza dzisiejszymi granicami.
    function zdejmijGraniceDat(formularz) {
        ['date_from', 'date_to'].forEach((nazwa) => {
            const p = formularz ? formularz.elements.namedItem(nazwa) : null;
            if (p) {
                p.removeAttribute('min');
                p.removeAttribute('max');
            }
        });
    }

    // (oględziny M14) Tekst serwera zwykle sam zaczyna się od numeru zamówienia
    // („Zamówienie 1512 jest…”) — wtedy numer przed nim byłby drugi raz.
    function pozycjaOdmowy(numer, tekst) {
        const t = String(tekst || '');
        // Odstęp między numerem a tekstem daje CSS (margines <b> w liście komunikatu).
        return { numer: numer && t.indexOf(String(numer)) === -1 ? numer : '', tekst: t };
    }

    const rowne = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
    const samZestaw = (a, b) => a.length === b.length && a.every((x) => b.indexOf(x) !== -1);

    // isFinite(null) === true — brak współrzędnych trzeba odsiać wprost.
    const maGeo = (z) => !!(z && z.geo && z.geo.lat !== null && z.geo.lng !== null &&
        isFinite(z.geo.lat) && isFinite(z.geo.lng));

    // (I5) Przystanek anulowany = zamówienie bez aktywnych pozycji. Szczegóły trasy niosą
    // `anulowane` przy przystanku; w danych zamówienia to etap „anulowane” — ta sama definicja,
    // z niej korzystamy tam, gdzie jest samo zamówienie (schemat przystanków, mapka).
    const anulowane = (z) => !!(z && z.etap && z.etap.status === 'anulowane');

    // (I1) Stan pakowania przystanku: 'spakowane' | 'niespakowane' | 'anulowane'.
    const stanPakowania = (z) => (anulowane(z) ? 'anulowane' : (z && z.spakowane ? 'spakowane' : 'niespakowane'));

    /**
     * Znacznik etapu w kropce koloru stanowiska — ten sam co w kolumnie „Etap” listy zamówień
     * (logistics.css, .lg-etap[data-etap]); spakowane z ptaszkiem. tekst — napis obok kropki.
     */
    function znacznikEtapuHtml(status, tekst, klasa) {
        const znak = status === 'spakowane'
            ? '<i class="fas fa-check lg-etap-znak" aria-hidden="true"></i>'
            : '<span class="lg-etap-znak" aria-hidden="true"></span>';
        return '<span class="lg-etap' + (klasa ? ' ' + klasa : '') + '" data-etap="' + esc(status) + '">' + znak +
            '<span class="lg-etap-nazwa">' + esc(tekst) + '</span></span>';
    }

    // Wiersz przystanku w edytorze: etap zamówienia, które NIE jest jeszcze spakowane (stanowisko,
    // na którym czeka) — wyjątek widać od razu, a spakowane (gotowe) wiersze zostają spokojne
    // i nazwa klienta ma całą szerokość. Pełny stan każdego przystanku pokazuje okno „Odhacz”.
    function etapPrzystankuHtml(z) {
        if (stanPakowania(z) !== 'niespakowane') return '';
        const etap = (z && z.etap) || { status: '', nazwa: '' };
        return znacznikEtapuHtml(etap.status, etap.nazwa || etap.status || '', 'lg-przystanek-etap');
    }

    // Okno „Odhacz”: stan pakowania słowami rulingu I1 — „spakowane”, „niespakowane — <etap>”, „anulowane”.
    function stanWykonaniaHtml(z, stanP) {
        if (stanP === 'spakowane') return znacznikEtapuHtml('spakowane', 'spakowane');
        if (stanP === 'anulowane') return znacznikEtapuHtml('anulowane', 'anulowane');
        const etap = (z && z.etap) || { status: '', nazwa: '' };
        return znacznikEtapuHtml(etap.status, 'niespakowane — ' + (etap.nazwa || etap.status || ''));
    }

    // (I5) „1 anulowane zamówienie”, „2 anulowane zamówienia”, „5 anulowanych zamówień”.
    const ileAnulowanych = (n) => n + ' ' + odmiana(n, ['anulowane zamówienie', 'anulowane zamówienia', 'anulowanych zamówień']);

    function ustawKolor(element, klasa) {
        if (!element) return;
        Array.from(element.classList).forEach((k) => {
            if (k.indexOf('lg-trasa-kolor-') === 0) element.classList.remove(k);
        });
        if (klasa) element.classList.add(klasa);
    }

    function mapaDashboardu() {
        const m = window.LogisticsMap;
        return m && m.root === root ? m : null;
    }

    // Kolor trasy z mapy Dashboardu (jedno źródło wzoru); bez mapy — atrament panelu.
    function kolor(id) {
        const m = mapaDashboardu();
        return m && typeof m.kolorTrasy === 'function' && id !== null && id !== undefined ? m.kolorTrasy(id) : '';
    }

    function komunikat(typ, tresc, opcje) {
        const tab = window.LogisticsTab;
        if (tab && tab.root === root && typeof tab.komunikat === 'function') {
            tab.komunikat(typ, tresc, opcje);
        } else {
            console.warn('[LogisticsRoutes]', tresc);   // lista jeszcze się nie wczytała
        }
    }

    // (oględziny M15) Pole z błędem: aria-invalid i aria-describedby na tekst błędu — czytnik
    // ekranu wiąże komunikat z polem. Zdejmujemy przy poprawce pola i przy zniknięciu błędu.
    function oznaczPole(p, idBledu) {
        if (!p) return;
        p.setAttribute('aria-invalid', 'true');
        if (idBledu) p.setAttribute('aria-describedby', idBledu);
    }

    function zdejmijOznaczenie(p) {
        if (!p || !p.hasAttribute || !p.hasAttribute('aria-invalid')) return;
        p.removeAttribute('aria-invalid');
        p.removeAttribute('aria-describedby');
    }

    function zdejmijOznaczenia(formularz) {
        if (formularz) formularz.querySelectorAll('[aria-invalid]').forEach(zdejmijOznaczenie);
    }

    let numerBledu = 0;   // rośnie z każdym pokazanym błędem edytora (wczytajDostepnosc)
    // Rodzaj bieżącego błędu edytora (runda 2, przegląd pkt 3): 'pole' (walidacja pola —
    // znika dopiero przy zmianie pola), 'serwer' (odmowa zmiany), 'konflikt' (odmowa
    // w sprawie pojazdu albo kierowcy — bladZasobu) i 'dostepnosc' (nie wczytano dostępności)
    // — te dwa ostatnie znikają też, gdy dostępność dla bieżących pól wczyta się bez problemu.
    let rodzajBledu = null;

    function pokazBlad(tekst, rodzaj) {
        if (!bladEl) return;
        if (tekst) numerBledu += 1;
        rodzajBledu = tekst ? (rodzaj || 'serwer') : null;
        bladEl.textContent = tekst || '';
        bladEl.hidden = !tekst;
        if (!tekst) zdejmijOznaczenia(form);
    }

    function oglos(tekst) {
        if (!ogloszenieEl) return;
        ogloszenieEl.textContent = '';
        // Po wyczyszczeniu — czytnik ekranu ogłasza też ten sam tekst drugi raz.
        setTimeout(() => { if (!zniszczona) ogloszenieEl.textContent = tekst; }, 30);
    }

    // ── Komunikacja z API ───────────────────────────────────────────────────

    // dane — ciało odmowy (np. `niespakowane` z POST /complete), gdy serwer je przysłał.
    class BladApi extends Error {
        constructor(komunikat, status, dane) {
            super(komunikat);
            this.status = status;
            this.dane = dane || null;
        }
    }

    /**
     * (przegląd końcowy, minor 2) Brak odpowiedzi (0) albo błąd serwera (≥ 500) to NIE czysta
     * odmowa: serwer mógł zmianę zapisać, a odpowiedź nie dotarła (Wi-Fi) albo padła po
     * commicie (serializacja). Wtedy dane trzeba pobrać od nowa, a po „utwórz” powiedzieć, że
     * trasa mogła już powstać — inaczej drugie kliknięcie tworzy duplikat.
     */
    const niepewnaOdpowiedz = (e) => !!e && !przerwane(e) && (e.status === 0 || e.status >= 500);

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
            throw new BladApi(komunikatBledu(odp.status, dane), odp.status, dane);
        }
        return dane;
    }

    function przerwane(e) {
        return !!(e && e.name === 'AbortError');
    }

    // ── Lista tras ──────────────────────────────────────────────────────────

    function statusHtml(status) {
        return '<span class="lg-status lg-status--' + esc(status) + '"><i class="fas ' +
            (IKONY_STATUSOW[status] || 'fa-circle') + '" aria-hidden="true"></i>' +
            esc(NAZWY_STATUSOW[status] || status) + '</span>';
    }

    // (oględziny Task 8, runda 2) „Trasa Trasa A…” w etykietach, gdy nazwa sama zaczyna się
    // od słowa „trasa” — wtedy bez dopisanego „Trasa”.
    const nazwaWOpisie = (nazwa) => (/^\s*trasa(\s|$)/i.test(String(nazwa || '')) ? String(nazwa) : 'Trasa ' + nazwa);

    function pozycjaListyHtml(t) {
        const p = t.podsumowanie || {};
        const otwarta = !!(stan.otwarta && stan.otwarta.id === t.id && !stan.nowa);
        const przekroczona = !!p.przekroczona_ladownosc;
        const ile = Number(p.przystanki) || 0;
        const pojazd = t.pojazd ? t.pojazd.name + (t.pojazd.is_active === false ? ' (wyłączony)' : '') : null;
        const kierowca = t.kierowca ? t.kierowca.nazwa : null;
        const klasy = ['lg-trasa-pozycja', 'lg-trasa-pozycja--' + String(t.status || ''), kolor(t.id)];
        if (otwarta) klasy.push('is-otwarta');
        // Etykieta wprost — treść to kilka pól obok siebie, czytnik skleiłby je bez przerw.
        const opis = nazwaWOpisie(t.nazwa) + ', ' + zakresDat(t.date_from, t.date_to) +
            ', ' + (pojazd ? 'pojazd ' + pojazd : 'bez pojazdu') + ', ' + (kierowca ? 'kierowca ' + kierowca : 'bez kierowcy') +
            ', ' + ilePrzystankow(ile) + ', ' + kg(p.waga_kg) + (przekroczona ? ', przekroczona ładowność pojazdu' : '');
        return '<li><button type="button" class="' + klasy.join(' ') + '" data-lg-trasa-id="' + esc(t.id) + '"' +
            ' aria-label="' + esc(opis) + '"' + (otwarta ? ' aria-current="true"' : '') + '>' +
            '<span class="lg-trasa-pozycja-nazwa">' + esc(t.nazwa) + '</span>' +
            (przekroczona ? '<i class="fas fa-triangle-exclamation lg-trasa-pozycja-ostrzezenie" role="img"' +
                ' aria-label="Przekroczona ładowność pojazdu" title="Przekroczona ładowność pojazdu"></i>' : '') +
            '<span class="lg-trasa-pozycja-daty">' + esc(zakresDat(t.date_from, t.date_to)) + '</span>' +
            '<span class="lg-trasa-pozycja-zasoby">' +
                '<span><i class="fas fa-truck" aria-hidden="true"></i>' +
                    (pojazd ? esc(pojazd) : '<span class="lg-brak-danych">bez pojazdu</span>') + '</span>' +
                '<span><i class="fas fa-user" aria-hidden="true"></i>' +
                    (kierowca ? esc(kierowca) : '<span class="lg-brak-danych">bez kierowcy</span>') + '</span>' +
            '</span>' +
            '<span class="lg-trasa-pozycja-liczby">' +
                '<span><b>' + ile + '</b> ' + odmiana(ile, PRZYSTANEK) + '</span>' +
                '<span' + (przekroczona ? ' class="is-przekroczona"' : '') + '><b>' +
                    esc(liczbaCala.format(Number(p.waga_kg) || 0)) + '</b> kg</span>' +
            '</span>' +
            '</button></li>';
    }

    const poDacie = (a, b) => (a.date_from < b.date_from ? -1 : (a.date_from > b.date_from ? 1 : a.id - b.id));

    /**
     * (oględziny Task 8, runda 2, N1) Lista rysuje się od nowa (innerHTML) — fokus na pozycji
     * trasy przechodzi na tę samą trasę w nowej liście (także gdy trasa zmieniła sekcję, np.
     * robocza → zatwierdzona), zamiast spaść na <body>.
     */
    function renderujListe() {
        const a = document.activeElement;
        const pozycjaZFokusem = a && a.closest && panel.contains(a) ? a.closest('[data-lg-trasa-id]') : null;
        const fokusNaTrasie = pozycjaZFokusem ? pozycjaZFokusem.getAttribute('data-lg-trasa-id') : null;
        rysujListe();
        if (fokusNaTrasie !== null) {
            const nowa = panel.querySelector('[data-lg-trasa-id="' + fokusNaTrasie + '"]');
            if (nowa && nowa !== document.activeElement && nowa.offsetParent !== null) nowa.focus({ preventScroll: true });
        }
    }

    function rysujListe() {
        const wgStatusu = (status) => stan.trasy.filter((t) => t.status === status).sort(poDacie);
        // Wykonane: najnowsze na górze (archiwum), robocze i zatwierdzone — najbliższe na górze.
        const wykonane = (stan.filtrWykonanych ? stan.filtrWykonanych.trasy : wgStatusu('wykonana'))
            .slice().sort((a, b) => poDacie(b, a));
        const sekcje = {
            robocza: [wgStatusu('robocza'), 'Brak tras roboczych.'],
            zatwierdzona: [wgStatusu('zatwierdzona'), 'Brak zatwierdzonych tras.'],
            wykonana: [wykonane, stan.filtrWykonanych ? 'Brak wykonanych tras w tych dniach.'
                : 'Brak wykonanych tras w ostatnich 30 dniach.'],
        };
        Object.keys(listy).forEach((status) => {
            const { lista, ile } = listy[status];
            const [trasy, pusto] = sekcje[status];
            if (!lista) return;
            if (!stan.listaWczytana) {
                lista.innerHTML = '';
                if (ile) ile.textContent = '';
                return;
            }
            if (ile) ile.textContent = String(trasy.length);
            lista.innerHTML = trasy.length ? trasy.map(pozycjaListyHtml).join('')
                : '<li class="lg-trasy-pusto">' + esc(pusto) + '</li>';
        });
        if (uklad) uklad.classList.toggle('is-edytor-otwarty', !!(stan.otwarta || stan.nowa));
        renderujStanListy();
    }

    function renderujStanListy() {
        if (!stanListyEl) return;
        stanListyEl.classList.remove('is-blad');
        if (stan.listaBlad) {
            stanListyEl.textContent = 'Nie udało się pobrać tras. ' + stan.listaBlad;
            stanListyEl.classList.add('is-blad');
            stanListyEl.hidden = false;
        } else if (!stan.listaWczytana) {
            stanListyEl.textContent = 'Ładowanie tras…';
            stanListyEl.hidden = false;
        } else {
            stanListyEl.hidden = true;
        }
    }

    /**
     * (oględziny m3) Lista z serwera + zmiany tras przyjęte u nas PO wysłaniu zapytania
     * (start = licznikZmian z chwili wysłania). Wolna lista, wysłana przed mutacją, nie cofa
     * wiersza, który odpowiedź mutacji już poprawiła, i nie wskrzesza usuniętej trasy.
     * pasuje(trasa) — czy skrót trasy należy do tej listy (np. tylko wykonane).
     */
    function scalZLokalnymi(trasy, start, pasuje) {
        let wynik = trasy;
        lokalneZmiany.forEach((z, id) => {
            if (z.wersja <= start) return;
            wynik = wynik.filter((t) => t.id !== id);
            if (z.trasa && (!pasuje || pasuje(z.trasa))) wynik.push(z.trasa);
        });
        return wynik;
    }

    async function wczytajListe() {
        if (zniszczona) return;
        if (kontrolerListy) kontrolerListy.abort();
        const kontroler = new AbortController();
        kontrolerListy = kontroler;
        const start = licznikZmian;
        if (odswiezListeBtn) odswiezListeBtn.classList.add('is-kreci');
        try {
            const dane = await zapytanie('/routes', { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerListy) return;
            stan.trasy = scalZLokalnymi(Array.isArray(dane.routes) ? dane.routes : [], start);
            stan.listaWczytana = true;
            stan.listaBlad = null;
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerListy) return;
            stan.listaBlad = e.message;
        } finally {
            if (kontroler === kontrolerListy) {
                kontrolerListy = null;
                if (odswiezListeBtn) odswiezListeBtn.classList.remove('is-kreci');
            }
        }
        renderujListe();
        if (stan.filtrWykonanych) wczytajWykonane(stan.filtrWykonanych.od, stan.filtrWykonanych.do);
    }

    /** Filtr „Wykonane”: od/do → GET /routes?status=wykonana&od=&do= (starsze niż domyślne 30 dni). */
    async function wczytajWykonane(od, doDnia) {
        if (zniszczona) return;
        if (kontrolerWykonanych) kontrolerWykonanych.abort();
        if (!od && !doDnia) {
            kontrolerWykonanych = null;
            stan.filtrWykonanych = null;
            if (opisWykonanychEl) opisWykonanychEl.textContent = 'Ostatnie 30 dni.';
            renderujListe();
            return;
        }
        if (od && doDnia && doDnia < od) {
            if (opisWykonanychEl) opisWykonanychEl.textContent = 'Data „do” jest wcześniejsza niż „od”.';
            return;
        }
        const kontroler = new AbortController();
        kontrolerWykonanych = kontroler;
        const start = licznikZmian;
        const p = new URLSearchParams({ status: 'wykonana' });
        if (od) p.set('od', od);
        if (doDnia) p.set('do', doDnia);
        if (opisWykonanychEl) opisWykonanychEl.textContent = 'Wczytywanie…';
        try {
            const dane = await zapytanie('/routes?' + p.toString(), { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerWykonanych) return;
            const filtr = { od: od, do: doDnia };
            filtr.trasy = scalZLokalnymi(Array.isArray(dane.routes) ? dane.routes : [], start,
                (t) => t.status === 'wykonana' && pasujeDoFiltraWykonanych(t, filtr));
            stan.filtrWykonanych = filtr;
            if (opisWykonanychEl) {
                // Bez „od” serwer i tak tnie do ostatnich 30 dni (domyślne okno wykonanych).
                opisWykonanychEl.textContent = od
                    ? 'Od ' + dataKrotka(od) + (doDnia ? ' do ' + dataKrotka(doDnia) : '') + '.'
                    : 'Do ' + dataKrotka(doDnia) + ', z ostatnich 30 dni.';
            }
            renderujListe();
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerWykonanych) return;
            if (opisWykonanychEl) opisWykonanychEl.textContent = 'Nie wczytano wykonanych tras. ' + e.message;
        } finally {
            if (kontroler === kontrolerWykonanych) kontrolerWykonanych = null;
        }
    }

    /**
     * (przegląd końcowy, minor 8) Czy wykonana trasa należy do listy filtra „Wykonane” — ten sam
     * warunek co serwer (GET /routes?status=wykonana&od=&do=): „od” → date_to ≥ od, „do” →
     * date_from ≤ do, a bez „od” serwer tnie do ostatnich DNI_WYKONANYCH dni. Trasa odhaczona
     * przy włączonym filtrze trafia na tę listę tylko wtedy, gdy mieści się w jego datach.
     */
    function pasujeDoFiltraWykonanych(t, filtr) {
        if (!filtr) return true;
        const odDnia = filtr.od || plusDni(dzisIso(), -DNI_WYKONANYCH);
        if (t.date_to < odDnia) return false;
        return !(filtr.do && t.date_from > filtr.do);
    }

    function skrotTrasy(r) {
        return {
            id: r.id, nazwa: r.nazwa, date_from: r.date_from, date_to: r.date_to, status: r.status,
            pojazd: r.pojazd, kierowca: r.kierowca, notatka: r.notatka,
            zatwierdzona: r.zatwierdzona, wykonana: r.wykonana, podsumowanie: r.podsumowanie,
        };
    }

    /** Odpowiedź mutacji (route) poprawia pozycję listy od razu, bez pobierania całej listy. */
    function aktualizujNaLiscie(route) {
        const s = skrotTrasy(route);
        licznikZmian += 1;
        lokalneZmiany.set(s.id, { wersja: licznikZmian, trasa: s });
        const i = stan.trasy.findIndex((t) => t.id === s.id);
        if (i === -1) stan.trasy.push(s); else stan.trasy[i] = s;
        if (stan.filtrWykonanych) {
            const lista = stan.filtrWykonanych.trasy;
            const j = lista.findIndex((t) => t.id === s.id);
            if (s.status === 'wykonana' && pasujeDoFiltraWykonanych(s, stan.filtrWykonanych)) {
                if (j === -1) lista.push(s); else lista[j] = s;
            } else if (j !== -1) {
                lista.splice(j, 1);
            }
        }
        renderujListe();
    }

    function usunZListy(id) {
        licznikZmian += 1;
        lokalneZmiany.set(id, { wersja: licznikZmian, trasa: null });
        stan.trasy = stan.trasy.filter((t) => t.id !== id);
        if (stan.filtrWykonanych) stan.filtrWykonanych.trasy = stan.filtrWykonanych.trasy.filter((t) => t.id !== id);
        renderujListe();
    }

    // ── Edytor: otwieranie, zamykanie, stan formularza ─────────────────────

    const pole = (nazwa) => (form ? form.elements.namedItem(nazwa) : null);
    const edytowalnaTrasa = () => !!(stan.otwarta && !stan.nowa && stan.otwarta.status === 'robocza');
    const edytowalnaForma = () => stan.nowa || edytowalnaTrasa();
    const liczbaPrzystankow = () => (stan.otwarta && !stan.nowa ? (stan.otwarta.przystanki || []).length : 0);

    function daneFormularza() {
        const od = pole('date_from') ? pole('date_from').value : '';
        const doDnia = pole('date_to') ? pole('date_to').value : '';
        return {
            name: pole('name') ? pole('name').value.trim() : '',
            date_from: od,
            date_to: doDnia || od,
            vehicle_id: selectPojazdu && selectPojazdu.value ? Number(selectPojazdu.value) : null,
            driver_worker_id: selectKierowcy && selectKierowcy.value ? Number(selectKierowcy.value) : null,
            notes: pole('notes') ? (pole('notes').value.trim() || null) : null,
        };
    }

    const migawkaFormularza = () => JSON.stringify(daneFormularza());
    const zmieniony = () => edytowalnaForma() && !!stan.migawka && migawkaFormularza() !== stan.migawka;

    /**
     * Te same zasady co serwer (services/routes.py, _dane_trasy) — błąd od razu, bez zapytania.
     * formularz (edytor albo okno „Dodaj do trasy…”) — jego pola dat sprawdzamy wprost
     * (niepełna data z klawiatury), zanim cokolwiek pójdzie do serwera. (M8) Granice dat trasy
     * i „do” najwyżej 31 dni po „od” — z tymi samymi tekstami co odmowa serwera.
     */
    function bladFormularza(dane, formularz) {
        if (!dane.name) return { tekst: 'Podaj nazwę trasy.', pole: 'name' };
        if (dane.name.length > 120) return { tekst: 'Nazwa trasy może mieć najwyżej 120 znaków.', pole: 'name' };
        const polaDat = formularz ? formularz.elements : null;
        const od = polaDat ? polaDat.namedItem('date_from') : null;
        const doDnia = polaDat ? polaDat.namedItem('date_to') : null;
        const g = graniceDat();
        let blad = od ? bladDaty(od, 'od', true, g) : bladWartosciDaty(dane.date_from, 'od', true, g);
        if (blad) return { tekst: blad, pole: 'date_from' };
        blad = doDnia ? bladDaty(doDnia, 'do', false, g) : bladWartosciDaty(dane.date_to, 'do', false, g);
        if (blad) return { tekst: blad, pole: 'date_to' };
        if (!poprawnaData(dane.date_from) || !poprawnaData(dane.date_to)) {
            return { tekst: 'Podaj datę „od” w formacie dd.mm.rrrr.', pole: 'date_from' };
        }
        if (dane.date_to < dane.date_from) return { tekst: 'Data „do” jest wcześniejsza niż „od”.', pole: 'date_to' };
        if (roznicaDni(dane.date_from, dane.date_to) > MAKS_ROZPIETOSC_DNI) {
            return {
                tekst: 'Data „do” może być najwyżej ' + MAKS_ROZPIETOSC_DNI + ' dni po dacie „od” (najpóźniej ' +
                    dataPelna(plusDni(dane.date_from, MAKS_ROZPIETOSC_DNI)) + ').',
                pole: 'date_to',
            };
        }
        return null;
    }

    // Kontrola formularza edytora w chwili kliknięcia (przed mutacją): błąd przy polu, fokus na nim.
    function formularzPoprawny() {
        const blad = bladFormularza(daneFormularza(), form);
        if (!blad) return true;
        fokusNaBledneZPola(blad);
        return false;
    }

    function resetEdytora() {
        // Nowa sesja edytora: spóźnione odpowiedzi mutacji poprzedniej już go nie przejmą.
        stan.sesja += 1;
        clearTimeout(timerDostepnosci);
        clearTimeout(timerSzukania);
        if (kontrolerDostepnosci) kontrolerDostepnosci.abort();
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        kontrolerDostepnosci = null;
        kontrolerKandydatow = null;
        stan.kolejnosc = null;
        stan.dostepnosc = null;
        stan.migawka = '';
        stan.kandydaci = [];
        stan.kandydaciWczytani = false;
        stan.kandydaciBlad = null;
        stan.kandydaciQ = '';
        stan.zaznaczeniKandydaci.clear();
        stan.dodawani.clear();
        if (kandydaciQ) kandydaciQ.value = '';
        mapkaDopasowana = false;
        mapkaRuszona = false;
        if (akcjeEl) akcjeEl.removeAttribute('data-klucz');
        pokazBlad('');
    }

    // Klucz trasy dla stan.wToku: 'nowa' (formularz nowej trasy), id trasy albo null.
    function kluczTrasy() {
        if (stan.nowa) return 'nowa';
        return stan.otwarta ? String(stan.otwarta.id) : null;
    }

    /** Czy trasa w edytorze ma zmianę w drodze (jej przyciski czekają). */
    function akcjaTrwa() {
        const k = kluczTrasy();
        return k !== null && stan.wToku.has(k);
    }

    // Użytkownik jest wciąż w tej samej sesji edytora co w chwili kliknięcia (ctx z mutacji).
    const naEkranie = (ctx) => !zniszczona && !!ctx && ctx.sesja === stan.sesja;

    // W trakcie wczytywania innej trasy: użytkownik już zgodził się porzucić zmiany bieżącej
    // (pozwolOpuscic przy kliknięciu) — × w tym czasie nie pyta o to samo drugi raz.
    let zmianyPorzucone = false;
    // Sesja edytora trasy, która wciąż jest na ekranie w trakcie wczytywania innej (runda 3,
    // pkt 3) — wraca, gdy wczytanie się nie uda i edytor zostaje przy poprzedniej trasie.
    let sesjaWidocznej = 0;

    /** Czy wolno zostawić bieżącą trasę (niezapisane zmiany, kolejność w drodze). */
    async function pozwolOpuscic() {
        if (zmieniony() && !zmianyPorzucone) {
            const nazwa = stan.nowa ? 'Nowa trasa' : 'Trasa „' + stan.otwarta.nazwa + '”';
            if (!window.confirm(nazwa + ' ma niezapisane zmiany. Porzucić je?')) return false;
        }
        await dokonczKolejnosc();
        return !zniszczona;
    }

    /**
     * (runda 2, N6 + runda 3, pkt 4) W trakcie wczytywania formularz poprzedniej trasy,
     * jej akcje, przystanki i „Do dodania” są inert — tekst wpisany w nich zaraz zniknąłby
     * pod nową trasą. „‹ Wszystkie trasy” i × zostają czynne: przerywają wczytywanie.
     */
    function ustawWczytywanie(trwa) {
        if (edytor) {
            edytor.classList.toggle('is-laduje', trwa);
            if (trwa) edytor.setAttribute('aria-busy', 'true'); else edytor.removeAttribute('aria-busy');
        }
        [form, akcjeEl, podsumowanieEl, ukladEdytoraEl, kandydaciSekcja].forEach((czesc) => {
            if (czesc) czesc.inert = trwa;
        });
    }

    // (runda 3, pkt 5) Sąsiad pozycji trasy na liście (następna, a gdy to ostatnia —
    // poprzednia) i nagłówek jej sekcji — fokus po zniknięciu trasy (404 przy otwieraniu).
    function sasiadNaLiscie(id) {
        const b = panel.querySelector('[data-lg-trasa-id="' + id + '"]');
        const li = b ? b.closest('li') : null;
        if (!li) return null;
        const pozycjaW = (el_) => (el_ ? el_.querySelector('[data-lg-trasa-id]') : null);
        const obok = pozycjaW(li.nextElementSibling) || pozycjaW(li.previousElementSibling);
        const sekcja = li.closest('.lg-trasy-sekcja');
        return {
            id: obok ? obok.getAttribute('data-lg-trasa-id') : null,
            tytul: sekcja ? sekcja.querySelector('.lg-trasy-sekcja-tytul') : null,
        };
    }

    function fokusNaSasiada(sasiad) {
        if (!fokusZgubiony()) return;
        const b = sasiad && sasiad.id !== null ? panel.querySelector('[data-lg-trasa-id="' + sasiad.id + '"]') : null;
        if (b && b.offsetParent !== null) {
            b.focus({ preventScroll: true });
            return;
        }
        // Nagłówek sekcji listy (Robocze / Zatwierdzone — h3; Wykonane — <summary>).
        const tytul = sasiad && sasiad.tytul && sasiad.tytul.offsetParent !== null ? sasiad.tytul : null;
        if (tytul) {
            if (tytul.tagName !== 'SUMMARY' && !tytul.hasAttribute('tabindex')) tytul.setAttribute('tabindex', '-1');
            tytul.focus({ preventScroll: true });
            return;
        }
        const nowa = root.querySelector('[data-lg-trasy-akcja="nowa"]');
        if (nowa) nowa.focus({ preventScroll: true });
    }

    async function otworz(routeId, opcje) {
        const o = opcje || {};
        const id = Number(routeId);
        if (zniszczona || !isFinite(id) || id <= 0) return;
        if (stan.otwarta && stan.otwarta.id === id && !stan.nowa) {
            // (przegląd końcowy, minor 1) Klik w trasę, która JUŻ jest na ekranie, w trakcie
            // wczytywania innej przerywa tamto wczytywanie — inaczej spóźniona trasa zastąpiłaby
            // tę, przy której użytkownik właśnie został. Sesja wraca do trasy na ekranie.
            if (kontrolerTrasy) {
                przerwijWczytywanie();
                stan.sesja = sesjaWidocznej;
            }
            renderujListe();
            if (o.fokus && tytulEl) tytulEl.focus();
            return;
        }
        if (!(await pozwolOpuscic())) return;
        // Sesja trasy na ekranie — zapamiętana tylko przy pierwszym z kolejnych kliknięć
        // (kolejne przerywają poprzednie wczytywanie, a na ekranie wciąż jest ta sama trasa).
        if (!kontrolerTrasy) sesjaWidocznej = stan.sesja;
        if (kontrolerTrasy) kontrolerTrasy.abort();
        const kontroler = new AbortController();
        kontrolerTrasy = kontroler;
        zmianyPorzucone = true;
        // (runda 2, przegląd pkt 2) Użytkownik już opuścił bieżącą trasę — nowa sesja od razu,
        // nie dopiero po odpowiedzi: błąd spóźnionej zmiany poprzedniej trasy trafia wtedy do
        // komunikatu z jej nazwą, a nie do pola błędu, które zaraz wyczyści resetEdytora().
        stan.sesja += 1;
        const sesjaProby = stan.sesja;
        ustawWczytywanie(true);
        if (!stan.otwarta && !stan.nowa && pustyEl) {
            pustyEl.querySelector('.lg-stan-tytul').textContent = 'Wczytywanie trasy…';
        }
        try {
            const dane = await zapytanie('/routes/' + id, { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerTrasy) return;
            // Przed fokusem: element w poddrzewie inert nie przyjmuje fokusu.
            ustawWczytywanie(false);
            resetEdytora();
            stan.nowa = false;
            stan.otwarta = null;
            przyjmijTrase(dane.route, { formularz: true });
            if (edytowalnaTrasa()) wczytajKandydatow();
            if (o.fokus && tytulEl) tytulEl.focus();
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerTrasy) return;
            // (runda 3, pkt 3) Edytor zostaje przy poprzedniej trasie — jej sesja wraca, żeby
            // odpowiedź jej zapisu w drodze (także odmowa) trafiła znów do edytora, a nie do
            // komunikatu, przy „Zapisz” wyglądającym jak po udanym zapisie.
            if (stan.sesja === sesjaProby) stan.sesja = sesjaWidocznej;
            if (e.status === 404) {
                const sasiad = sasiadNaLiscie(id);
                usunZListy(id);
                komunikat('blad', 'Tej trasy już nie ma. Ktoś mógł ją usunąć.', { klucz: 'trasa' });
                fokusNaSasiada(sasiad);
            } else {
                komunikat('blad', 'Nie wczytano trasy. ' + e.message, { klucz: 'trasa' });
            }
        } finally {
            if (kontroler === kontrolerTrasy) koniecWczytywania();
        }
    }

    // Koniec wczytywania trasy (udane, nieudane albo przerwane „Nową trasą” / zamknięciem).
    function koniecWczytywania() {
        kontrolerTrasy = null;
        zmianyPorzucone = false;
        ustawWczytywanie(false);
        if (pustyEl) pustyEl.querySelector('.lg-stan-tytul').textContent = 'Wybierz trasę z listy albo utwórz nową.';
    }

    // Przerwanie wczytywania innej trasy — od razu, żeby fokus mógł wejść do formularza.
    function przerwijWczytywanie() {
        if (!kontrolerTrasy) return;
        kontrolerTrasy.abort();
        koniecWczytywania();
    }

    async function nowaTrasa() {
        if (zniszczona || !(await pozwolOpuscic())) return;
        przerwijWczytywanie();
        resetEdytora();
        stan.otwarta = null;
        stan.nowa = true;
        renderujEdytor({ formularz: true });
        renderujListe();
        if (pole('name')) pole('name').focus();
    }

    async function zamknijEdytor() {
        if (zniszczona || !(await pozwolOpuscic())) return;
        przerwijWczytywanie();
        const byla = stan.otwarta;
        resetEdytora();
        stan.otwarta = null;
        stan.nowa = false;
        renderujEdytor();
        renderujListe();
        // Fokus na pozycję zamkniętej trasy (wąsko lista wraca na ekran).
        const pozycja = byla ? root.querySelector('[data-lg-trasa-id="' + byla.id + '"]') : null;
        const cel = pozycja || root.querySelector('[data-lg-trasy-akcja="nowa"]');
        if (cel) cel.focus({ preventScroll: true });
    }

    /**
     * Odpowiedź API z trasą → stan, lista i edytor (formularz tylko, gdy opcje.formularz,
     * inna trasa albo inny status — pola trasy tylko do odczytu pokazują wartości z serwera).
     */
    function przyjmijTrase(route, opcje) {
        const o = opcje || {};
        if (!route || zniszczona) return;
        const poprzednia = stan.otwarta;
        const inna = !poprzednia || poprzednia.id !== route.id;
        const innyStatus = !inna && poprzednia.status !== route.status;
        const idsPrzed = poprzednia && !inna ? (poprzednia.przystanki || []).map((p) => p.zamowienie.id) : [];
        stan.otwarta = route;
        stan.nowa = false;
        const idsPo = kolejnoscSerwera();
        if (stan.kolejnosc && (inna || !samZestaw(stan.kolejnosc, idsPo) || rowne(stan.kolejnosc, idsPo))) {
            stan.kolejnosc = null;
        }
        aktualizujNaLiscie(route);
        renderujEdytor({ formularz: !!o.formularz || inna || innyStatus, dopasujMapke: inna || !samZestaw(idsPrzed, idsPo) });
        if (o.zmiana) odswiezMapeTrasPoZmianie();
    }

    /**
     * (oględziny A1) Odpowiedź mutacji → edytor TYLKO w tej samej sesji edytora (ctx.sesja):
     * użytkownik nie przeszedł w międzyczasie do innej trasy, do nowej trasy ani nie zamknął
     * edytora. Inaczej poprawiamy tylko pozycję listy i mapę tras — spóźniona odpowiedź
     * trasy A nie przejmuje edytora z trasą B i nie nadpisuje jej formularza. Gdy w
     * międzyczasie otwarto ponownie TĘ SAMĄ trasę: świeże przystanki, podsumowanie i status,
     * a pola formularza zostają takie, jak je widać (chyba że zmienił się status). (runda 2,
     * przegląd pkt 6) Pola nieruszane od ponownego otwarcia dostają wartości z odpowiedzi —
     * odczyt przy otwarciu mógł jeszcze nie mieć zapisu, który właśnie wrócił.
     */
    function przyjmijOdpowiedz(ctx, route, opcje) {
        const o = opcje || {};
        if (!route || zniszczona) return;
        if (naEkranie(ctx)) {
            przyjmijTrase(route, o);
            return;
        }
        if (!stan.nowa && stan.otwarta && stan.otwarta.id === route.id) {
            przyjmijTrase(route, { zmiana: o.zmiana, formularz: !!stan.migawka && migawkaFormularza() === stan.migawka });
            return;
        }
        aktualizujNaLiscie(route);
        if (o.zmiana) odswiezMapeTrasPoZmianie();
    }

    function renderujEdytor(opcje) {
        const o = opcje || {};
        const t = stan.otwarta;
        if (!edytor || !pustyEl || !trescEl) return;
        if (!t && !stan.nowa) {
            pustyEl.hidden = false;
            trescEl.hidden = true;
            ustawKolor(edytor, '');
            zniszczMapke();
            if (uklad) uklad.classList.remove('is-edytor-otwarty');
            return;
        }
        pustyEl.hidden = true;
        trescEl.hidden = false;
        if (uklad) uklad.classList.add('is-edytor-otwarty');
        ustawKolor(edytor, t ? kolor(t.id) : '');
        statusEl.innerHTML = t ? statusHtml(t.status) : '';
        tytulEl.textContent = t ? t.nazwa : 'Nowa trasa';
        // (runda 2, przegląd pkt 5) Trasa tylko do odczytu zawsze pokazuje wartości z serwera
        // — także opis pojazdu w selekcie (nazwa, „wyłączony z floty”) po odświeżeniu trasy.
        if (o.formularz || !edytowalnaForma()) wypelnijFormularz();
        polaEl.disabled = !edytowalnaForma();
        renderujAkcje();
        renderujPodsumowanie();
        renderujPrzystanki();
        renderujKandydatow();
        odswiezMapke({ dopasuj: !!o.dopasujMapke });
    }

    function wypelnijFormularz() {
        const t = stan.otwarta;
        if (stan.nowa || !t) {
            const dzis = dzisIso();
            pole('name').value = '';
            pole('date_from').value = dzis;
            pole('date_to').value = dzis;
            pole('notes').value = '';
            stan.wybranyPojazd = '';
            stan.wybranyKierowca = '';
        } else {
            pole('name').value = t.nazwa || '';
            pole('date_from').value = t.date_from || '';
            pole('date_to').value = t.date_to || '';
            pole('notes').value = t.notatka || '';
            stan.wybranyPojazd = t.pojazd ? String(t.pojazd.id) : '';
            stan.wybranyKierowca = t.kierowca ? String(t.kierowca.id) : '';
        }
        // (M8) Granice dat trasy od dzisiejszej daty — przy każdym wypełnieniu formularza.
        if (edytowalnaForma()) ustawGraniceDat(form); else zdejmijGraniceDat(form);
        renderujSelecty();
        stan.migawka = migawkaFormularza();
        if (edytowalnaForma()) wczytajDostepnosc();
    }

    // ── Pojazd i kierowca: dostępność w dniach trasy ────────────────────────

    function opisPojazdu(p) {
        return p.name + (p.registration ? ', ' + p.registration : '') +
            (p.capacity_kg ? ', do ' + kg(p.capacity_kg) : '');
    }

    function opcjaHtml(wartosc, tekst, wylaczona, wybrana) {
        return '<option value="' + esc(wartosc) + '"' + (wylaczona ? ' disabled' : '') + (wybrana ? ' selected' : '') + '>' +
            esc(tekst) + '</option>';
    }

    function ustawUwage(element, tekst) {
        if (!element) return;
        element.innerHTML = tekst ? '<i class="fas fa-triangle-exclamation" aria-hidden="true"></i><span>' + esc(tekst) + '</span>' : '';
        element.hidden = !tekst;
    }

    /**
     * Selecty z GET /availability: zajęci w tych dniach widoczni, wyszarzeni, z dopiskiem
     * „(zajęty — nazwa trasy)”. Pojazd trasy wyłączony z floty (dostępność zna tylko
     * aktywne) i kierowca, który przestał być aktywny — zostają wybrani (I3: serwer przyjmuje
     * niezmieniony wyłączony pojazd i kierowcę), ale po zmianie nie da się do nich wrócić.
     */
    function renderujSelecty() {
        if (!selectPojazdu || !selectKierowcy) return;
        const t = stan.nowa ? null : stan.otwarta;
        const d = edytowalnaForma() ? stan.dostepnosc : null;
        const wP = stan.wybranyPojazd;
        const wK = stan.wybranyKierowca;
        let pojazdy = '<option value=""' + (wP ? '' : ' selected') + '>Bez pojazdu</option>';
        let kierowcy = '<option value=""' + (wK ? '' : ' selected') + '>Bez kierowcy</option>';
        let uwagaP = '';
        let uwagaK = '';
        if (d) {
            (d.pojazdy || []).forEach((p) => {
                pojazdy += opcjaHtml(p.id, opisPojazdu(p) + (p.zajety ? ' (zajęty — ' + (p.trasa || 'inna trasa') + ')' : ''),
                    !!p.zajety, String(p.id) === wP);
            });
            const pojazd = (d.pojazdy || []).find((p) => String(p.id) === wP);
            if (wP && !pojazd) {
                const znany = t && t.pojazd && String(t.pojazd.id) === wP ? t.pojazd : null;
                pojazdy += opcjaHtml(wP, (znany ? znany.name : 'Pojazd nr ' + wP) + ' (wyłączony z floty)', true, true);
                uwagaP = 'Pojazd jest wyłączony z floty. Zostaje na tej trasie; po zmianie nie wybierzesz go ponownie.';
            } else if (pojazd && pojazd.zajety) {
                uwagaP = 'Pojazd jest zajęty w tych dniach na trasie „' + (pojazd.trasa || 'inna trasa') +
                    '”. Wybierz inny albo zmień daty.';
            }
            (d.kierowcy || []).forEach((k) => {
                kierowcy += opcjaHtml(k.id, k.nazwa + (k.zajety ? ' (zajęty — ' + (k.trasa || 'inna trasa') + ')' : ''),
                    !!k.zajety, String(k.id) === wK);
            });
            const kierowca = (d.kierowcy || []).find((k) => String(k.id) === wK);
            if (wK && !kierowca) {
                const znany = t && t.kierowca && String(t.kierowca.id) === wK ? t.kierowca : null;
                kierowcy += opcjaHtml(wK, (znany ? znany.nazwa : 'Kierowca nr ' + wK) + ' (nieaktywny)', true, true);
                uwagaK = 'Kierowca nie jest już aktywnym pracownikiem. Zostaje na tej trasie; po zmianie nie wybierzesz go ponownie.';
            } else if (kierowca && kierowca.zajety) {
                uwagaK = 'Kierowca jest zajęty w tych dniach na trasie „' + (kierowca.trasa || 'inna trasa') +
                    '”. Wybierz innego albo zmień daty.';
            }
        } else {
            // Tylko do odczytu albo dostępność jeszcze w drodze: sama bieżąca wartość trasy.
            if (t && t.pojazd && String(t.pojazd.id) === wP) {
                pojazdy += opcjaHtml(wP, opisPojazdu(t.pojazd) + (t.pojazd.is_active === false ? ' (wyłączony z floty)' : ''),
                    false, true);
            }
            if (t && t.kierowca && String(t.kierowca.id) === wK) {
                kierowcy += opcjaHtml(wK, t.kierowca.nazwa, false, true);
            }
        }
        selectPojazdu.innerHTML = pojazdy;
        selectKierowcy.innerHTML = kierowcy;
        ustawUwage(uwagaPojazduEl, uwagaP);
        ustawUwage(uwagaKierowcyEl, uwagaK);
        odswiezAkcje();
    }

    function planujDostepnosc() {
        clearTimeout(timerDostepnosci);
        timerDostepnosci = setTimeout(wczytajDostepnosc, ZWLOKA_DOSTEPNOSCI_MS);
    }

    async function wczytajDostepnosc() {
        clearTimeout(timerDostepnosci);
        if (zniszczona || !edytowalnaForma()) return;
        const dane = daneFormularza();
        // (oględziny M1) Niepełna albo błędna data (np. rok 92026 w trakcie wpisywania z
        // klawiatury) nie idzie do serwera — zostaje dostępność dla ostatnich dobrych dat.
        // (M8) Tak samo daty poza granicami trasy — zapisu i tak by nie było.
        const g = graniceDat();
        if (!wGranicach(dane.date_from, g) || !wGranicach(dane.date_to, g) || dane.date_to < dane.date_from ||
            roznicaDni(dane.date_from, dane.date_to) > MAKS_ROZPIETOSC_DNI) return;
        if (kontrolerDostepnosci) kontrolerDostepnosci.abort();
        const kontroler = new AbortController();
        kontrolerDostepnosci = kontroler;
        const p = new URLSearchParams({ date_from: dane.date_from, date_to: dane.date_to });
        if (!stan.nowa && stan.otwarta) p.set('route_id', String(stan.otwarta.id));
        const dla = stan.nowa ? 'nowa' : stan.otwarta.id;
        const bladPrzed = numerBledu;
        try {
            const odp = await zapytanie('/availability?' + p.toString(), { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerDostepnosci) return;
            if ((stan.nowa ? 'nowa' : (stan.otwarta && stan.otwarta.id)) !== dla) return;
            stan.dostepnosc = { pojazdy: odp.pojazdy || [], kierowcy: odp.kierowcy || [] };
            renderujSelecty();
            // (oględziny M1) Dostępność dla bieżących pól przyszła — czerwony błąd sprzed
            // poprawki (np. „Pojazd jest zajęty…”) już nie dotyczy tego, co widać. Błąd, który
            // pojawił się W TRAKCIE tego zapytania (inna akcja), zostaje; walidacja pola
            // („Podaj nazwę trasy.”) też — ona znika dopiero przy zmianie pola (runda 2, pkt 3).
            if (numerBledu === bladPrzed && (rodzajBledu === 'konflikt' || rodzajBledu === 'dostepnosc')) pokazBlad('');
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerDostepnosci) return;
            pokazBlad('Nie wczytano dostępności pojazdów i kierowców. ' + e.message, 'dostepnosc');
        } finally {
            if (kontroler === kontrolerDostepnosci) kontrolerDostepnosci = null;
        }
    }

    // ── Edytor: przyciski akcji ─────────────────────────────────────────────

    function renderujAkcje() {
        if (!akcjeEl) return;
        const klucz = stan.nowa ? 'nowa' : (stan.otwarta ? stan.otwarta.status : '');
        // Przyciski od nowa tylko przy zmianie statusu — fokus na przycisku przeżywa zapis.
        if (akcjeEl.getAttribute('data-klucz') !== klucz) {
            akcjeEl.setAttribute('data-klucz', klucz);
            akcjeEl.innerHTML = (AKCJE[klucz] || []).map(([akcja, etykieta, ikona, odmianaPrzycisku]) =>
                '<button type="button" class="lg-przycisk' + (odmianaPrzycisku ? ' lg-przycisk--' + odmianaPrzycisku : '') + '"' +
                ' data-lg-trasy-akcja="' + akcja + '">' +
                (ikona ? '<i class="fas ' + ikona + '" aria-hidden="true"></i>' : '') + esc(etykieta) + '</button>'
            ).join('');
        }
        odswiezAkcje();
    }

    /**
     * Stan przycisków: „Zapisz” tylko przy zmianach (i wtedy główny), bez przystanków nie ma
     * czego zatwierdzać. Zmiana tej trasy w drodze: aria-disabled, nie disabled — przycisk
     * z fokusem zostaje pod klawiaturą (oględziny I3), a klik i tak przechodzi przez mutacja().
     */
    function odswiezAkcje() {
        if (!akcjeEl) return;
        const zmiany = zmieniony();
        const ile = liczbaPrzystankow();
        const czeka = akcjaTrwa();
        akcjeEl.querySelectorAll('[data-lg-trasy-akcja]').forEach((b) => {
            const akcja = b.getAttribute('data-lg-trasy-akcja');
            let wylaczony = false;
            let tytul = '';
            if (akcja === 'zapisz') {
                // W trakcie zapisu „Zapisz” czeka (aria-disabled) zamiast gasnąć pod fokusem.
                wylaczony = !zmiany && !czeka;
                b.classList.toggle('lg-przycisk--glowny', zmiany);
                if (!zmiany && !czeka) tytul = 'Brak zmian do zapisania.';
            } else if (akcja === 'zatwierdz') {
                b.classList.toggle('lg-przycisk--glowny', !zmiany);
                if (!ile) {
                    wylaczony = true;
                    tytul = 'Dodaj przystanki, żeby zatwierdzić trasę.';
                } else if (zmiany) {
                    tytul = 'Zapisze zmiany i zatwierdzi trasę.';
                }
            } else if (akcja === 'wykonaj' && !ile) {
                wylaczony = true;
                tytul = 'Trasa nie ma przystanków.';
            }
            b.disabled = wylaczony;
            if (czeka && !wylaczony) {
                b.setAttribute('aria-disabled', 'true');
                tytul = 'Poczekaj, aż zapisze się poprzednia zmiana tej trasy.';
            } else {
                b.removeAttribute('aria-disabled');
            }
            if (tytul) b.title = tytul; else b.removeAttribute('title');
        });
        if (dodajZaznaczoneBtn) renderujPrzyciskDodawania();
        odswiezPrzyciskiPrzystankow();
    }

    /** Migawka z chwili kliknięcia: trasa, sesja edytora, dane formularza, fokus (oględziny A1). */
    function migawkaMutacji() {
        const nowa = stan.nowa;
        const trasa = nowa ? null : stan.otwarta;
        return {
            klucz: kluczTrasy(),
            sesja: stan.sesja,
            nowa: nowa,
            trasa: trasa,
            id: trasa ? trasa.id : null,
            nazwa: nowa ? 'Nowa trasa' : 'Trasa „' + (trasa ? trasa.nazwa : '') + '”',
            dane: daneFormularza(),
            zmiany: zmieniony(),
            fokus: document.activeElement,
        };
    }

    /**
     * Wspólny szkielet zmian trasy (oględziny A1): jedna naraz NA TRASĘ — przyciski tej
     * trasy czekają, a inne trasy można w tym czasie otwierać i zmieniać (serwer i tak
     * szereguje zapisy blokadą tras). Najpierw zapis kolejności w drodze. fn(ctx) pracuje
     * na migawce z chwili kliknięcia (ctx.trasa, ctx.dane), nie na stan.otwarta — ta mogła
     * się zmienić, zanim przyszła odpowiedź. Błąd serwera (409/422): przy formularzu, gdy
     * użytkownik jest wciąż przy tej trasie, inaczej komunikatem z nazwą trasy. Po 409/404
     * trasa na serwerze jest inna niż nasza kopia — pobieramy ją od nowa (oględziny m4).
     * (przegląd końcowy, minor 2) Brak odpowiedzi albo błąd serwera (niepewnaOdpowiedz) — zmiana
     * mogła się zapisać: lista i trasa od nowa, a przy tworzeniu ostrzeżenie przed duplikatem.
     * opcje.odczyt — operacja niczego nie zmienia (eksport do Routimo): bez tego ostrzeżenia.
     */
    async function mutacja(fn, opcje) {
        if (zniszczona || akcjaTrwa()) return null;
        const odczyt = !!(opcje && opcje.odczyt);
        const ctx = migawkaMutacji();
        if (ctx.klucz === null) return null;
        stan.wToku.add(ctx.klucz);
        odswiezAkcje();
        renderujKandydatow();
        pokazBlad('');
        let odswiez = false;
        try {
            await dokonczKolejnosc();
            return await fn(ctx);
        } catch (e) {
            if (zniszczona || przerwane(e)) return null;
            const niepewna = !odczyt && niepewnaOdpowiedz(e);
            const konflikt = e.status === 409 || e.status === 404 || niepewna;
            let tekst = e.message;
            if (niepewna) {
                tekst += ctx.nowa
                    ? ' Trasa mogła już powstać — sprawdź listę tras, zanim utworzysz ją ponownie.'
                    : ' Zmiana mogła się zapisać — trasę pobieramy od nowa.';
                wczytajListe();
            }
            if (naEkranie(ctx)) {
                pokazBlad(tekst, bladZasobu(e) ? 'konflikt' : 'serwer');
                odswiez = konflikt && !ctx.nowa;
            } else {
                // (runda 2, przegląd pkt 1) Klucz tej trasy, nie wspólny 'trasa': następny
                // komunikat innej trasy („Zapisano trasę „B”.”) nie może zdjąć tego błędu.
                komunikat('blad', ctx.nazwa + ': ' + tekst, { klucz: kluczBleduTrasy(ctx.klucz) });
                if (konflikt && !niepewna) wczytajListe();
            }
            return null;
        } finally {
            stan.wToku.delete(ctx.klucz);
            if (!zniszczona) {
                odswiezAkcje();
                renderujKandydatow();
                if (naEkranie(ctx)) oddajFokus(ctx);
                if (odswiez) odswiezOtwarta();
            }
        }
    }

    // Fokus „zgubiony”: na <body>, na elemencie usuniętym z DOM, albo w tej zakładce na
    // elemencie schowanym lub nieaktywnym (przeglądarka i tak zaraz przeniesie go na <body> —
    // reguła „focus fixup”). Fokus poza zakładką (np. menu boczne) i w otwartym oknie — nie.
    function fokusZgubiony() {
        const a = document.activeElement;
        if (!a || a === document.body || a === document.documentElement || !a.isConnected) return true;
        if (!root.contains(a) || (a.closest && a.closest('dialog[open]'))) return false;
        return a.disabled === true || a.offsetParent === null;
    }

    /**
     * (oględziny I3) Po zmianie trasy fokus nie spada na <body>: kliknięty przycisk zniknął
     * (inny status = inne przyciski) albo zgasł („Zapisz” po zapisie). Wraca na niego, gdy
     * znów działa, a inaczej na tytuł edytora (ten sam, na który trafia otwarcie trasy z mapy).
     * Fokus, który użytkownik sam przeniósł w trakcie (np. do notatki), zostaje.
     */
    function oddajFokus(ctx) {
        if (!fokusZgubiony()) return;
        const b = ctx.fokus;
        const cel = b && b !== document.body && b.isConnected && !b.disabled && b.offsetParent !== null ? b : tytulEl;
        if (cel && cel.isConnected && cel.offsetParent !== null) cel.focus({ preventScroll: true });
    }

    // Klucz komunikatu z błędem zmiany trasy spoza ekranu — osobny dla każdej trasy.
    const kluczBleduTrasy = (klucz) => 'trasa-blad-' + (klucz === null || klucz === undefined ? 'nowa' : klucz);

    // Odmowa dotycząca pojazdu albo kierowcy (services/routes.py, _sprawdz_zasoby: zajęty
    // w tych dniach, wyłączony z floty, nieaktywny) — tylko taki błąd kasuje udana dostępność.
    const bladZasobu = (e) => !!e && (e.status === 409 || e.status === 422) &&
        /zajęty|wyłączony z floty|aktywnego kierowcy/i.test(String(e.message || ''));

    function fokusNaBledneZPola(blad) {
        pokazBlad(blad.tekst, 'pole');
        const p = pole(blad.pole);
        oznaczPole(p, 'lg-edytor-blad');
        if (p && !p.disabled) p.focus();
    }

    async function zapisz(ctx, ciche) {
        const t = ctx.trasa;
        if (!t || ctx.nowa || t.status !== 'robocza') return false;
        const dane = ctx.dane;
        const blad = bladFormularza(dane);
        if (blad) {
            if (naEkranie(ctx)) fokusNaBledneZPola(blad);
            return false;
        }
        // (oględziny A1) Zmiany w drodze to nie „niezapisane zmiany” — przejście do innej trasy
        // w trakcie zapisu nie pyta o ich porzucenie. Odmowa serwera przywraca poprzedni stan
        // („Zapisz” znów aktywny przy tych samych polach).
        const wyslane = JSON.stringify(dane);
        const migawkaPrzed = stan.migawka;
        if (naEkranie(ctx)) stan.migawka = wyslane;
        let odp;
        try {
            odp = await zapytanie('/routes/' + t.id, { metoda: 'PUT', dane: dane });
        } catch (e) {
            // Po trasie, nie po sesji (runda 3, pkt 3): odmowa w trakcie wczytywania innej trasy
            // też przywraca „niezapisane zmiany”, gdy ta trasa wciąż jest w edytorze.
            if (stan.migawka === wyslane && !stan.nowa && stan.otwarta && stan.otwarta.id === t.id) stan.migawka = migawkaPrzed;
            throw e;
        }
        if (zniszczona) return false;
        // Pola zmienione W TRAKCIE zapisu zostają — formularz z serwera tylko bez takich zmian.
        const formularz = !naEkranie(ctx) || migawkaFormularza() === wyslane;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: formularz, zmiana: true });
        if (!ciche) komunikat('ok', 'Zapisano trasę „' + odp.route.nazwa + '”.', { klucz: 'trasa' });
        return true;
    }

    async function utworz(ctx) {
        if (!ctx.nowa) return;
        const dane = ctx.dane;
        const blad = bladFormularza(dane);
        if (blad) {
            if (naEkranie(ctx)) fokusNaBledneZPola(blad);
            return;
        }
        // Jak w zapisz(): dane w drodze to nie „niezapisane zmiany” (× w trakcie nie pyta).
        const wyslane = JSON.stringify(dane);
        const migawkaPrzed = stan.migawka;
        if (naEkranie(ctx)) stan.migawka = wyslane;
        let odp;
        try {
            odp = await zapytanie('/routes', { metoda: 'POST', dane: dane });
        } catch (e) {
            if (stan.migawka === wyslane && stan.nowa) stan.migawka = migawkaPrzed;
            throw e;
        }
        if (zniszczona) return;
        const komunikatOk = 'Utworzono trasę „' + odp.route.nazwa + '”. Dodaj do niej zamówienia z listy „Do dodania”.';
        if (!naEkranie(ctx) || !stan.nowa) {
            // (A1) Formularz nowej trasy porzucony w trakcie (inna trasa, zamknięty edytor albo
            // świeży formularz „Nowa trasa”) — trasa jest na liście, edytor zostaje przy swoim.
            aktualizujNaLiscie(odp.route);
            odswiezMapeTrasPoZmianie();
            komunikat('ok', komunikatOk, { klucz: 'trasa' });
            return;
        }
        resetEdytora();
        stan.nowa = false;
        przyjmijTrase(odp.route, { formularz: true, zmiana: true });
        wczytajKandydatow();
        komunikat('ok', komunikatOk, { klucz: 'trasa' });
        if (kandydaciQ && !kandydaciSekcja.hidden) kandydaciQ.focus({ preventScroll: true });
    }

    // Zmiana statusu zakończona w tej samej sesji: fokus na tytuł, bo kliknięty przycisk
    // zniknął (inny status = inne przyciski). Fokus przeniesiony przez użytkownika gdzie
    // indziej (np. do notatki) zostaje.
    function fokusNaTytul(ctx) {
        if (!naEkranie(ctx) || !tytulEl || tytulEl.offsetParent === null) return;
        const a = document.activeElement;
        if (fokusZgubiony() || a === ctx.fokus || !!(akcjeEl && akcjeEl.contains(a))) tytulEl.focus({ preventScroll: true });
    }

    async function zatwierdz(ctx) {
        if (ctx.zmiany && !(await zapisz(ctx, true))) return;
        const t = ctx.trasa;
        if (!t) return;
        const odp = await zapytanie('/routes/' + t.id + '/approve', { metoda: 'POST', dane: {} });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: true, zmiana: true });
        komunikat('ok', 'Trasa „' + odp.route.nazwa + '” zatwierdzona. Możesz ją wyeksportować do Routimo.',
            { klucz: 'trasa' });
        fokusNaTytul(ctx);
    }

    async function cofnij(ctx) {
        const t = ctx.trasa;
        if (!t) return;
        const odp = await zapytanie('/routes/' + t.id + '/revert', { metoda: 'POST', dane: {} });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: true, zmiana: true });
        wczytajKandydatow();
        komunikat('info', 'Trasa „' + odp.route.nazwa + '” znów jest robocza.', { klucz: 'trasa' });
        fokusNaTytul(ctx);
    }

    async function przywroc(ctx) {
        const t = ctx.trasa;
        if (!t) return;
        const odp = await zapytanie('/routes/' + t.id + '/restore', { metoda: 'POST', dane: {} });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: true, zmiana: true });
        komunikat('info', 'Trasa „' + odp.route.nazwa + '” przywrócona do zatwierdzonych.', { klucz: 'trasa' });
        fokusNaTytul(ctx);
    }

    async function usunTrase(ctx) {
        const t = ctx.trasa;
        if (!t) return;
        await zapytanie('/routes/' + t.id, { metoda: 'DELETE' });
        if (zniszczona) return;
        usunZListy(t.id);
        odswiezMapeTrasPoZmianie();
        komunikat('ok', 'Usunięto trasę „' + t.nazwa + '”.', { klucz: 'trasa' });
        // (A1) Edytor zamykamy tylko wtedy, gdy wciąż pokazuje TĘ trasę — inna otwarta w
        // międzyczasie zostaje, a fokus nie przeskakuje spod ręki.
        if (stan.nowa || !stan.otwarta || stan.otwarta.id !== t.id) return;
        const a = document.activeElement;
        const fokusWEdytorze = !a || a === document.body || (edytor && edytor.contains(a));
        resetEdytora();
        stan.otwarta = null;
        renderujEdytor();
        renderujListe();
        const cel = root.querySelector('[data-lg-trasy-akcja="nowa"]');
        if (cel && fokusWEdytorze) cel.focus({ preventScroll: true });
    }

    function nazwaZNaglowka(naglowek) {
        if (!naglowek) return null;
        const utf = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(naglowek);
        if (utf) {
            try { return decodeURIComponent(utf[1].trim()); } catch (e) { /* zwykła nazwa niżej */ }
        }
        const zwykla = /filename\s*=\s*"?([^";]+)"?/i.exec(naglowek);
        return zwykla ? zwykla[1].trim() : null;
    }

    /**
     * Eksport do Routimo: plik przez fetch → <a href download> z adresem blob, żeby odmowę
     * serwera (np. 409, gdy ktoś w międzyczasie cofnął zatwierdzenie) pokazać przy formularzu,
     * a nie pobierać jako „plik” z tekstem błędu.
     */
    async function eksportujRoutimo(ctx) {
        const t = ctx.trasa;
        if (!t) return;
        let odp;
        try {
            odp = await fetch(API + '/routes/' + t.id + '/routimo', {
                credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
        } catch (e) {
            throw new BladApi('Brak połączenia z serwerem.', 0);
        }
        const typ = odp.headers.get('Content-Type') || '';
        if (!odp.ok || typ.indexOf('application/json') !== -1) {
            let dane = null;
            try { dane = await odp.json(); } catch (e) { dane = null; }
            throw new BladApi(komunikatBledu(odp.status, dane), odp.status, dane);
        }
        // (przegląd końcowy, minor 4) Tylko prawdziwy arkusz — strona HTML (np. logowania albo
        // błędu serwera pośredniego) z kodem 200 nie może się zapisać jako „plik dla Routimo”.
        if (typ.indexOf('spreadsheetml') === -1) {
            throw new BladApi('Serwer nie przysłał pliku Excel dla Routimo (HTTP ' + odp.status + '). Spróbuj ponownie.', odp.status);
        }
        const plik = await odp.blob();
        const nazwa = nazwaZNaglowka(odp.headers.get('Content-Disposition')) || 'routimo_trasa_' + t.id + '.xlsx';
        const adres = URL.createObjectURL(plik);
        const a = document.createElement('a');
        a.href = adres;
        a.download = nazwa;
        a.hidden = true;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(adres), 60000);
        // (I5) Przystanki zamówień anulowanych serwer pomija — mówimy, ile ich było.
        const pominiete = parseInt(odp.headers.get('X-Routimo-Pominiete') || '0', 10) || 0;
        komunikat(pominiete > 0 ? 'info' : 'ok', 'Pobrano plik dla Routimo: ' + nazwa + '.' + (pominiete > 0
            ? ' Pominięto ' + pominiete + ' ' + odmiana(pominiete, ['anulowany przystanek', 'anulowane przystanki',
                'anulowanych przystanków']) + '.'
            : ''), { klucz: 'trasa' });
    }

    // ── Podsumowanie ────────────────────────────────────────────────────────

    function renderujPodsumowanie() {
        if (!podsumowanieEl) return;
        const t = stan.otwarta;
        if (!t || stan.nowa) {
            podsumowanieEl.innerHTML = '';
            return;
        }
        const p = t.podsumowanie || {};
        const ladownosc = t.pojazd && t.pojazd.capacity_kg ? Number(t.pojazd.capacity_kg) : null;
        const waga = Number(p.waga_kg) || 0;
        const przekroczona = !!p.przekroczona_ladownosc;
        const przeliczanie = !!(stan.kolejnosc || kolejnoscObietnica);
        const km = p.km !== null && p.km !== undefined ? liczbaKm.format(Number(p.km)) + ' km' : '—';
        const czas = p.minuty !== null && p.minuty !== undefined ? czasHM(p.minuty) : '—';
        const komorka = (etykieta, wartosc, klasa, tytul) => '<div' + (klasa ? ' class="' + klasa + '"' : '') +
            (tytul ? ' title="' + esc(tytul) + '"' : '') + '><dt>' + etykieta + '</dt><dd>' + wartosc + '</dd></div>';
        let html = '<dl class="lg-podsumowanie-liczby' + (przeliczanie ? ' is-przeliczanie' : '') + '">' +
            komorka('Przystanki', String(Number(p.przystanki) || 0)) +
            komorka('Objętość', esc(liczbaM3.format(Number(p.m3) || 0)) + ' m³') +
            komorka('Waga', esc(kg(waga)) + (ladownosc ? ' <small>/ ' + esc(kg(ladownosc)) + '</small>' : ''),
                przekroczona ? 'is-przekroczona' : '', 'Szacunek: objętość × ' + WAGA_KG_NA_M3 + ' kg/m³') +
            komorka('Dystans', esc(km), '', p.przyblizony ? 'W linii prostej — przebieg przybliżony' : '') +
            komorka('Czas jazdy', esc(czas), '', p.minuty === null || p.minuty === undefined
                ? 'Czas nieznany (przebieg przybliżony albo brak przystanków)' : '') +
            '</dl>';
        const uwagi = [];
        if (przekroczona) {
            uwagi.push('<li class="is-blad"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i>' +
                'Przekroczona ładowność pojazdu (' + esc(kg(waga)) + ' &gt; ' + esc(kg(ladownosc)) + ')</li>');
        }
        // (I5) Przystanki zamówień anulowanych w całości: nie liczą się do przystanków ani wagi,
        // Routimo ich nie dostanie — logistyk zdejmuje je z trasy.
        const anul = Number(p.anulowane) || 0;
        if (anul) {
            const rada = t.status === 'robocza' ? '; usuń je z trasy'
                : (t.status === 'zatwierdzona' ? '; cofnij zatwierdzenie i usuń je z trasy' : '');
            uwagi.push('<li class="is-uwaga"><i class="fas fa-ban" aria-hidden="true"></i>' +
                esc(ileAnulowanych(anul) + ' — nie ' + odmiana(anul, ['trafi', 'trafią', 'trafią']) + ' do Routimo' + rada) +
                '</li>');
        }
        const bezGeo = Number(p.bez_lokalizacji) || 0;
        if (bezGeo) {
            uwagi.push('<li class="is-uwaga"><span class="lg-pin lg-pin--pusta" aria-hidden="true"></span>' +
                esc(ilePrzystankow(bezGeo)) + ' bez lokalizacji (punkt ustawisz na mapie Dashboardu)</li>');
        }
        if (p.przyblizony && Number(p.przystanki)) {
            uwagi.push('<li class="is-info"><i class="fas fa-route" aria-hidden="true"></i>' +
                'Przebieg przybliżony: linie proste, odległość w linii prostej, czas nieznany</li>');
        }
        if (uwagi.length) html += '<ul class="lg-podsumowanie-uwagi">' + uwagi.join('') + '</ul>';
        podsumowanieEl.innerHTML = html;
    }

    // ── Przystanki: schemat linii, kolejność ────────────────────────────────

    const kolejnoscSerwera = () => (stan.otwarta && !stan.nowa ? (stan.otwarta.przystanki || []) : [])
        .map((p) => p.zamowienie.id);
    const kolejnoscWidoczna = () => stan.kolejnosc || kolejnoscSerwera();

    function przystankiWidoczne() {
        const t = stan.otwarta;
        if (!t || stan.nowa) return [];
        const po = new Map((t.przystanki || []).map((p) => [p.zamowienie.id, p.zamowienie]));
        return kolejnoscWidoczna().map((id) => po.get(id)).filter(Boolean);
    }

    function adresHtml(z) {
        const miejscowosc = [z.kod, z.miasto].filter(Boolean).join(' ');
        const gora = miejscowosc
            ? '<span class="lg-adres-linia lg-adres-miejscowosc" title="' + esc(miejscowosc) + '">' +
                (z.kod ? '<span class="lg-adres-kod">' + esc(z.kod) + '</span>' + (z.miasto ? ' ' : '') : '') +
                esc(z.miasto || '') + '</span>'
            : '<span class="lg-adres-linia lg-adres-miejscowosc lg-brak-danych">brak adresu</span>';
        const dol = z.adres
            ? '<span class="lg-adres-linia lg-adres-ulica" title="' + esc(z.adres) + '">' + esc(z.adres) + '</span>'
            : '';
        return gora + dol;
    }

    const m3Tekst = (z) => (Number(z.m3) > 0 ? liczbaM3.format(Number(z.m3)) + ' m³' : '—');

    /**
     * (oględziny m7) Dwa różne znaczenia, dwa różne wyglądy stacji — na liście przystanków,
     * na mapce i w oknie „Odhacz”: punkt PRZYBLIŻONY (miejscowość) = przerywana obwódka
     * w kolorze trasy, jak przerywana pinezka; BRAK punktu = szara kropkowana tarcza.
     */
    function klasaGeoStacji(z) {
        if (!maGeo(z)) return 'lg-stacja--bez-geo';
        return z.geo.quality === 'przyblizona' ? 'lg-stacja--przyblizona' : '';
    }

    /**
     * Wiersz przystanku. indeks — miejsce na liście (od 0; ↑/↓), numer — numer stacji wśród
     * AKTYWNYCH przystanków (jak `pozycja` z API — kolejność w Routimo); null = anulowany (I5):
     * stacja „—”, plakietka „Anulowane”, wiersz przygaszony. Pozostałe mają etap zamówienia
     * (ptaszek = spakowane) — widać, co jeszcze nie jest gotowe do odhaczenia.
     */
    function przystanekHtml(z, indeks, ile, numer, edyt) {
        const anul = numer === null;
        const bezGeo = !maGeo(z);
        const opis = (anul ? 'przystanek anulowany' : 'przystanek ' + numer) + ', zamówienie ' + z.numer;
        const klasyStacji = ['lg-stacja'];
        const geo = anul ? 'lg-stacja--anulowana' : klasaGeoStacji(z);
        if (geo) klasyStacji.push(geo);
        if (!anul && String(numer).length > 2) klasyStacji.push('lg-stacja--dlugi');
        return '<li class="lg-przystanek' + (anul ? ' lg-przystanek--anulowany' : '') + '" data-order-id="' + esc(z.id) + '"' +
            (edyt ? ' draggable="true"' : '') + '>' +
            '<span class="' + klasyStacji.join(' ') + '" aria-hidden="true"' +
                (geo === 'lg-stacja--przyblizona' ? ' title="Punkt przybliżony (miejscowość)"' : '') + '>' + (anul ? '—' : numer) + '</span>' +
            (edyt ? '<span class="lg-przystanek-uchwyt" aria-hidden="true" title="Przeciągnij, żeby zmienić kolejność">' +
                '<i class="fas fa-grip-vertical"></i></span>' : '') +
            '<div class="lg-przystanek-tresc">' +
                '<div class="lg-przystanek-gora"><span class="lg-numer">' + esc(z.numer) + '</span>' +
                    '<span class="lg-przystanek-klient"' + (z.klient ? ' title="' + esc(z.klient) + '"' : '') + '>' +
                    (z.klient ? esc(z.klient) : '<span class="lg-brak-danych">brak nazwy</span>') + '</span>' +
                    (anul ? '<span class="lg-plakietka-anulowane" title="Zamówienie anulowane w całości — nie trafi do Routimo.">Anulowane</span>'
                        : etapPrzystankuHtml(z)) +
                '</div>' +
                '<div class="lg-przystanek-adres">' + adresHtml(z) + '</div>' +
            '</div>' +
            '<div class="lg-przystanek-meta">' +
                (bezGeo && !anul ? '<span class="lg-pin lg-pin--pusta" role="img" aria-label="Brak punktu na mapie"' +
                    ' title="Brak punktu na mapie. Ustawisz go na mapie Dashboardu."></span>' : '') +
                '<span class="lg-przystanek-m3">' + m3Tekst(z) + '</span>' +
                (edyt ? '<div class="lg-przystanek-akcje">' +
                    '<button type="button" class="lg-ikona-przycisk" data-lg-przystanek="gora"' + (indeks === 0 ? ' disabled' : '') +
                        ' aria-label="' + esc('Przesuń wyżej: ' + opis) + '" title="Wyżej"><i class="fas fa-arrow-up" aria-hidden="true"></i></button>' +
                    '<button type="button" class="lg-ikona-przycisk" data-lg-przystanek="dol"' + (indeks === ile - 1 ? ' disabled' : '') +
                        ' aria-label="' + esc('Przesuń niżej: ' + opis) + '" title="Niżej"><i class="fas fa-arrow-down" aria-hidden="true"></i></button>' +
                    // Bez disabled na czas innej zmiany (fokus zostaje) — czekanie pokazuje
                    // aria-disabled z odswiezPrzyciskiPrzystankow(), a mutacja() i tak czeka.
                    '<button type="button" class="lg-przycisk lg-przycisk--cichy lg-przystanek-usun" data-lg-przystanek="usun"' +
                        ' aria-label="' + esc('Usuń z trasy zamówienie ' + z.numer) + '" title="Usuń z trasy">' +
                        '<i class="fas fa-xmark" aria-hidden="true"></i><span>Usuń z trasy</span></button>' +
                    '</div>' : '') +
            '</div>' +
            '</li>';
    }

    function fokusPrzystanku() {
        const a = document.activeElement;
        const li = a && przystankiEl && przystankiEl.contains(a) ? a.closest('.lg-przystanek[data-order-id]') : null;
        if (!li) return null;
        return {
            id: Number(li.getAttribute('data-order-id')),
            akcja: a.getAttribute('data-lg-przystanek'),
            indeks: Array.from(przystankiEl.children).indexOf(li),
        };
    }

    // Fokus wraca na ten sam przycisk przesuniętego przystanku (u góry ↑ jest nieaktywna — wtedy ↓);
    // po usunięciu — na sąsiedni przystanek. (runda 2, N2) Gdy przycisków już nie ma (trasa
    // przeszła w tylko do odczytu, np. odmowa kolejności, bo ktoś ją zatwierdził) — na tytuł
    // edytora, jak po innych zmianach statusu, a nie na <body>.
    function przywrocFokusPrzystanku(f) {
        if (!f) return;
        let li = przystankiEl.querySelector('.lg-przystanek[data-order-id="' + f.id + '"]');
        if (!li) {
            const wiersze = przystankiEl.querySelectorAll('.lg-przystanek[data-order-id]');
            li = wiersze[Math.min(f.indeks, wiersze.length - 1)] || null;
        }
        const kolejnosc = f.akcja === 'gora' ? ['gora', 'dol', 'usun'] : (f.akcja === 'dol' ? ['dol', 'gora', 'usun'] : ['usun', 'gora', 'dol']);
        for (let i = 0; li && i < kolejnosc.length; i += 1) {
            const b = li.querySelector('[data-lg-przystanek="' + kolejnosc[i] + '"]');
            if (b && !b.disabled) {
                b.focus({ preventScroll: true });
                return;
            }
        }
        // Według stanu trasy, nie widoczności „Do dodania” — tę renderujKandydatow() chowa
        // dopiero po przystankach (trasa właśnie przeszła w tylko do odczytu).
        if (kandydaciQ && edytowalnaTrasa()) {
            kandydaciQ.focus({ preventScroll: true });
        } else if (tytulEl && tytulEl.offsetParent !== null) {
            tytulEl.focus({ preventScroll: true });
        }
    }

    // (runda 2, N4) Przyciski przystanków (↑/↓, „Usuń z trasy”) i przeciąganie w trakcie zmiany
    // tej trasy wyglądają na nieaktywne jak przyciski nagłówka (aria-disabled — fokus zostaje,
    // a klik i tak czeka: przesun() i „Usuń z trasy” mówią czytnikowi, na co czekają).
    function odswiezPrzyciskiPrzystankow() {
        if (!przystankiEl) return;
        const czeka = akcjaTrwa();
        if (liniaEl) liniaEl.classList.toggle('is-czeka', czeka);
        przystankiEl.querySelectorAll('[data-lg-przystanek]').forEach((b) => {
            if (czeka) b.setAttribute('aria-disabled', 'true'); else b.removeAttribute('aria-disabled');
        });
    }

    function renderujStanPrzystankow() {
        if (!przystankiStanEl) return;
        const kolejne = przystankiWidoczne();
        const anul = kolejne.filter(anulowane).length;
        przystankiStanEl.textContent = stan.kolejnosc || kolejnoscObietnica
            ? 'Zapisywanie kolejności…'
            : (stan.otwarta && !stan.nowa
                ? ilePrzystankow(kolejne.length - anul) + (anul ? ' + ' + ileAnulowanych(anul) : '') : '');
    }

    function renderujPrzystanki() {
        if (!przystankiEl || !liniaEl) return;
        const t = stan.otwarta;
        if (!t || stan.nowa) {
            ustawKolor(liniaEl, '');
            liniaEl.classList.remove('is-przyblizona');
            liniaEl.classList.add('is-tylko-odczyt');
            przystankiEl.innerHTML = '<li class="lg-przystanek lg-przystanek--pusto">Utwórz trasę, a potem dodaj do niej zamówienia.</li>';
            renderujStanPrzystankow();
            return;
        }
        const edyt = t.status === 'robocza';
        ustawKolor(liniaEl, kolor(t.id));
        liniaEl.classList.toggle('is-przyblizona', !!(t.podsumowanie && t.podsumowanie.przyblizony));
        liniaEl.classList.toggle('is-tylko-odczyt', !edyt);
        const kolejne = przystankiWidoczne();
        const fokus = fokusPrzystanku();
        // (I5) Numer wśród aktywnych, liczony z widocznej kolejności — ta sama reguła co `pozycja`
        // z API (routes.numeracja_przystankow), a przy przesuwaniu nowe numery widać od razu.
        let numer = 0;
        przystankiEl.innerHTML = kolejne.length
            ? kolejne.map((z, i) => przystanekHtml(z, i, kolejne.length, anulowane(z) ? null : (numer += 1), edyt)).join('')
            : '<li class="lg-przystanek lg-przystanek--pusto">' + (edyt
                ? 'Brak przystanków. Dodaj zamówienia z listy „Do dodania” niżej albo na Dashboardzie („Dodaj do trasy…”).'
                : 'Trasa nie ma przystanków.') + '</li>';
        odswiezPrzyciskiPrzystankow();
        przywrocFokusPrzystanku(fokus);
        renderujStanPrzystankow();
    }

    function oznaczPrzeniesiony(orderId) {
        const li = przystankiEl.querySelector('.lg-przystanek[data-order-id="' + orderId + '"]');
        if (!li) return;
        li.classList.add('is-przeniesiony');
        setTimeout(() => { if (li.isConnected) li.classList.remove('is-przeniesiony'); }, 1300);
    }

    /** Nowa lokalna kolejność od razu (lista, numery, mapka); zapis do serwera po krótkiej zwłoce. */
    function przesun(orderId, doIndeksu) {
        if (!edytowalnaTrasa()) return;
        // (oględziny m2) Jak przy przeciąganiu: w trakcie innej zmiany tej trasy (dodawanie,
        // usuwanie, zapis) kolejność czeka — lokalna zmiana rozjechałaby się z odpowiedzią.
        if (akcjaTrwa()) {
            oglos('Poczekaj, aż zapisze się poprzednia zmiana trasy.');
            return;
        }
        const ids = kolejnoscWidoczna().slice();
        const z = ids.indexOf(orderId);
        if (z === -1) return;
        const cel = Math.max(0, Math.min(ids.length - 1, doIndeksu));
        if (cel === z) return;
        ids.splice(z, 1);
        ids.splice(cel, 0, orderId);
        stan.kolejnosc = rowne(ids, kolejnoscSerwera()) ? null : ids;
        renderujPrzystanki();
        oznaczPrzeniesiony(orderId);
        renderujPodsumowanie();
        odswiezMapke();
        const przesuniety = przystankiWidoczne()[cel];
        oglos('Zamówienie ' + (przesuniety ? przesuniety.numer : '') + ' na pozycji ' + (cel + 1) + ' z ' + ids.length + '.');
        planujKolejnosc();
    }

    function planujKolejnosc() {
        clearTimeout(timerKolejnosci);
        timerKolejnosci = setTimeout(() => {
            timerKolejnosci = null;
            uruchomZapisKolejnosci();
        }, ZWLOKA_KOLEJNOSCI_MS);
        renderujStanPrzystankow();
    }

    function uruchomZapisKolejnosci() {
        if (!kolejnoscObietnica) {
            kolejnoscObietnica = petlaKolejnosci().catch((e) => {
                console.error('[LogisticsRoutes] Zapis kolejności:', e);
                return false;
            }).then((odmowa) => {
                kolejnoscObietnica = null;
                if (zniszczona) return;
                renderujStanPrzystankow();
                renderujPodsumowanie();
                odswiezMapke();
                // (oględziny m4) Odmowa (409 — np. ktoś w międzyczasie zatwierdził trasę) znaczy,
                // że trasa na serwerze jest inna niż nasza kopia: pobieramy ją od nowa.
                if (odmowa) odswiezOtwarta();
            });
        }
        return kolejnoscObietnica;
    }

    /**
     * Wysyła NAJNOWSZĄ lokalną kolejność, dopóki różni się od tej na serwerze (przesunięcia
     * w trakcie zapisu). Daje true, gdy serwer odmówił (wtedy trasa idzie do odświeżenia).
     */
    async function petlaKolejnosci() {
        while (!zniszczona && stan.kolejnosc && edytowalnaTrasa()) {
            const t = stan.otwarta;
            const ids = stan.kolejnosc.slice();
            try {
                const odp = await zapytanie('/routes/' + t.id + '/stops/order', { metoda: 'PUT', dane: { order_ids: ids } });
                if (zniszczona) return false;
                if (!stan.otwarta || stan.nowa || stan.otwarta.id !== t.id) {
                    aktualizujNaLiscie(odp.route);   // edytor już przy innej trasie — tylko lista
                    return false;
                }
                if (stan.kolejnosc && rowne(stan.kolejnosc, ids)) stan.kolejnosc = null;
                przyjmijTrase(odp.route, { zmiana: true });
            } catch (e) {
                if (zniszczona || przerwane(e)) return false;
                if (!stan.otwarta || stan.nowa || stan.otwarta.id !== t.id) {
                    komunikat('blad', 'Trasa „' + t.nazwa + '”: nie zapisano kolejności przystanków. ' + e.message,
                        { klucz: kluczBleduTrasy(String(t.id)) });
                    return false;
                }
                // Do czasu odświeżenia — ostatnia kolejność potwierdzona przez serwer.
                stan.kolejnosc = null;
                renderujPrzystanki();
                pokazBlad('Nie zapisano kolejności przystanków. ' + e.message, 'serwer');
                // (minor 2) Po niepewnej odpowiedzi kolejność mogła się zapisać — też od nowa.
                return e.status === 409 || e.status === 404 || e.status === 422 || niepewnaOdpowiedz(e);
            }
        }
        return false;
    }

    /** Przed każdą inną zmianą trasy: oczekująca kolejność leci od razu i czekamy na nią. */
    async function dokonczKolejnosc() {
        if (timerKolejnosci) {
            clearTimeout(timerKolejnosci);
            timerKolejnosci = null;
        }
        if (stan.kolejnosc || kolejnoscObietnica) await uruchomZapisKolejnosci();
    }

    async function usunPrzystanek(ctx, orderId) {
        const t = ctx.trasa;
        if (!t || t.status !== 'robocza') return;
        const p = (t.przystanki || []).find((x) => x.zamowienie.id === orderId);
        const numer = p ? p.zamowienie.numer : '';
        const odp = await zapytanie('/routes/' + t.id + '/stops/' + encodeURIComponent(orderId), { metoda: 'DELETE' });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { zmiana: true });
        komunikat('ok', 'Zamówienie ' + numer + ' usunięto z trasy „' + odp.route.nazwa + '”. Wróciło do „Do dodania”.',
            { klucz: 'trasa' });
        // Zamówienie wróciło do puli — „Do dodania” odświeża się dla trasy, która jest teraz w edytorze.
        wczytajKandydatow();
    }

    // Klik w przystanek na mapce: wiersz na liście mignie ramką i przewinie się w pole widzenia.
    function wskazPrzystanek(orderId) {
        const li = przystankiEl.querySelector('.lg-przystanek[data-order-id="' + orderId + '"]');
        if (!li) return;
        przystankiEl.querySelectorAll('.lg-przystanek.is-wskazany').forEach((x) => x.classList.remove('is-wskazany'));
        li.classList.add('is-wskazany');
        li.scrollIntoView({ block: 'nearest', behavior: bezRuchu ? 'auto' : 'smooth' });
        setTimeout(() => { if (li.isConnected) li.classList.remove('is-wskazany'); }, 1800);
    }

    // ── Przeciąganie przystanków (HTML5 drag & drop; klawiatura: ↑/↓) ───────

    function celUpuszczenia(e) {
        const li = e.target && e.target.closest ? e.target.closest('.lg-przystanek[data-order-id]') : null;
        if (!li || !przystankiEl.contains(li)) return null;
        const r = li.getBoundingClientRect();
        return { li: li, id: Number(li.getAttribute('data-order-id')), przed: e.clientY < r.top + r.height / 2 };
    }

    function oznaczCel(cel) {
        przystankiEl.querySelectorAll('.is-cel-przed, .is-cel-za').forEach((x) => x.classList.remove('is-cel-przed', 'is-cel-za'));
        if (cel && cel.id !== przeciagany) cel.li.classList.add(cel.przed ? 'is-cel-przed' : 'is-cel-za');
    }

    function zakonczPrzeciaganie() {
        przeciagany = null;
        if (!przystankiEl) return;
        przystankiEl.querySelectorAll('.is-przeciagany').forEach((x) => x.classList.remove('is-przeciagany'));
        oznaczCel(null);
    }

    function naDragStart(e) {
        const li = e.target && e.target.closest ? e.target.closest('.lg-przystanek[draggable="true"]') : null;
        if (!li || chwytZPrzycisku || !edytowalnaTrasa() || akcjaTrwa()) {
            e.preventDefault();
            return;
        }
        przeciagany = Number(li.getAttribute('data-order-id'));
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            // Firefox nie zacznie przeciągania bez danych.
            try { e.dataTransfer.setData('text/plain', String(przeciagany)); } catch (err) { /* starszy silnik */ }
        }
        li.classList.add('is-przeciagany');
    }

    function naDragOver(e) {
        if (przeciagany === null) return;
        const cel = celUpuszczenia(e);
        if (!cel) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        oznaczCel(cel);
    }

    function naDragLeave(e) {
        if (przeciagany !== null && (!e.relatedTarget || !przystankiEl.contains(e.relatedTarget))) oznaczCel(null);
    }

    function naDrop(e) {
        if (przeciagany === null) return;
        e.preventDefault();
        const cel = celUpuszczenia(e);
        const id = przeciagany;
        zakonczPrzeciaganie();
        if (!cel || cel.id === id) return;
        const ids = kolejnoscWidoczna();
        let indeks = ids.indexOf(cel.id) + (cel.przed ? 0 : 1);
        if (ids.indexOf(id) < indeks) indeks -= 1;   // po wyjęciu przeciąganego lista jest krótsza
        przesun(id, indeks);
    }

    // ── Do dodania (transport własny bez trasy) ─────────────────────────────

    function terminHtml(iso) {
        if (!iso) return '<span class="lg-termin lg-brak-danych">brak</span>';
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
        return '<time class="' + klasa + '" datetime="' + esc(iso) + '" title="' + esc(tytul) + '">' + esc(dataKrotka(iso)) + '</time>';
    }

    function kandydatHtml(z) {
        const zaznaczony = stan.zaznaczeniKandydaci.has(z.id);
        const dodawany = stan.dodawani.has(z.id);
        // aria-disabled, nie disabled: przycisk z fokusem nie może zniknąć spod klawiatury
        // na czas zapisu (klik i tak przechodzi przez mutacja(), jedna zmiana naraz).
        const wylaczony = dodawany || akcjaTrwa();
        return '<li class="lg-kandydat' + (zaznaczony ? ' is-zaznaczony' : '') + (dodawany ? ' is-dodawany' : '') + '"' +
            ' data-order-id="' + esc(z.id) + '">' +
            '<label class="lg-zaznacz-pole"><input type="checkbox" class="lg-kandydat-zaznacz"' + (zaznaczony ? ' checked' : '') +
                (dodawany ? ' disabled' : '') + ' aria-label="' + esc('Zaznacz zamówienie ' + z.numer) + '"></label>' +
            '<span class="lg-numer">' + esc(z.numer) + '</span>' +
            '<div class="lg-kandydat-tresc"><span class="lg-kandydat-klient"' + (z.klient ? ' title="' + esc(z.klient) + '"' : '') + '>' +
                (z.klient ? esc(z.klient) : '<span class="lg-brak-danych">brak nazwy</span>') + '</span>' + adresHtml(z) + '</div>' +
            terminHtml(z.termin) +
            '<span class="lg-m3">' + (maGeo(z) ? '' : '<span class="lg-pin lg-pin--pusta" role="img" aria-label="Brak punktu na mapie"' +
                ' title="Brak punktu na mapie"></span> ') + m3Tekst(z) + '</span>' +
            '<button type="button" class="lg-przycisk" data-lg-kandydat="dodaj"' + (wylaczony ? ' aria-disabled="true"' : '') +
                ' aria-label="' + esc('Dodaj do trasy zamówienie ' + z.numer) + '">' +
                '<i class="fas fa-plus" aria-hidden="true"></i>Dodaj</button>' +
            '</li>';
    }

    function renderujPrzyciskDodawania() {
        const n = stan.zaznaczeniKandydaci.size;
        if (dodajZaznaczoneTekst) dodajZaznaczoneTekst.textContent = n ? 'Dodaj zaznaczone (' + n + ')' : 'Dodaj zaznaczone';
        dodajZaznaczoneBtn.disabled = !n;
        // Zmiana tej trasy w drodze: czeka, ale zostaje pod fokusem (jak przyciski edytora).
        if (n && akcjaTrwa()) dodajZaznaczoneBtn.setAttribute('aria-disabled', 'true');
        else dodajZaznaczoneBtn.removeAttribute('aria-disabled');
    }

    function renderujKandydatow() {
        if (!kandydaciSekcja || !kandydaciEl) return;
        const pokaz = edytowalnaTrasa();
        kandydaciSekcja.hidden = !pokaz;
        if (!pokaz) return;
        const stanHtml = (tekst, blad) => '<li class="lg-kandydaci-stan' + (blad ? ' is-blad' : '') + '">' + esc(tekst) + '</li>';
        const n = stan.kandydaci.length;
        // Fokus na „Dodaj” / polu wyboru przeżywa przerysowanie; dodany wiersz znika — wtedy
        // sąsiedni, a gdy lista opustoszeje — wyszukiwarka.
        const a = document.activeElement;
        const li = a && kandydaciEl.contains(a) ? a.closest('.lg-kandydat[data-order-id]') : null;
        const fokus = li ? {
            id: li.getAttribute('data-order-id'),
            zaznacz: a.classList.contains('lg-kandydat-zaznacz'),
            indeks: Array.from(kandydaciEl.children).indexOf(li),
        } : null;
        if (stan.kandydaciBlad && !n) {
            kandydaciEl.innerHTML = stanHtml('Nie wczytano zamówień. ' + stan.kandydaciBlad, true);
        } else if (!stan.kandydaciWczytani) {
            kandydaciEl.innerHTML = stanHtml('Wczytywanie zamówień…');
        } else if (!n) {
            kandydaciEl.innerHTML = stanHtml(stan.kandydaciQ
                ? 'Nic nie pasuje do „' + stan.kandydaciQ + '”.'
                : 'Każde otwarte zamówienie z transportem własnym jest już na trasie.');
        } else {
            kandydaciEl.innerHTML = stan.kandydaci.map(kandydatHtml).join('');
        }
        if (fokus) {
            let wiersz = kandydaciEl.querySelector('.lg-kandydat[data-order-id="' + fokus.id + '"]');
            if (!wiersz) {
                const wiersze = kandydaciEl.querySelectorAll('.lg-kandydat[data-order-id]');
                wiersz = wiersze[Math.min(fokus.indeks, wiersze.length - 1)] || null;
            }
            const cel = wiersz ? wiersz.querySelector(fokus.zaznacz ? '.lg-kandydat-zaznacz' : '[data-lg-kandydat="dodaj"]') : null;
            if (cel && !cel.disabled) cel.focus({ preventScroll: true });
            else if (kandydaciQ) kandydaciQ.focus({ preventScroll: true });
        }
        if (kandydaciIleEl) {
            // (oględziny M4) „1 pasujące zamówienie”, „2 pasujące zamówienia”, „5 pasujących zamówień”.
            kandydaciIleEl.textContent = stan.kandydaciWczytani && !stan.kandydaciBlad
                ? (stan.kandydaciQ
                    ? n + ' ' + odmiana(n, ['pasujące zamówienie', 'pasujące zamówienia', 'pasujących zamówień'])
                    : ileZamowien(n)) + ' z transportem własnym bez trasy'
                : 'transport własny bez trasy';
        }
        if (dodajZaznaczoneBtn) renderujPrzyciskDodawania();
    }

    async function wczytajKandydatow() {
        if (zniszczona || !edytowalnaTrasa()) return;
        if (kontrolerKandydatow) kontrolerKandydatow.abort();
        const kontroler = new AbortController();
        kontrolerKandydatow = kontroler;
        const p = new URLSearchParams({ sposob: 'bez_trasy' });
        if (stan.kandydaciQ) p.set('q', stan.kandydaciQ);
        try {
            const dane = await zapytanie('/orders?' + p.toString(), { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerKandydatow) return;
            stan.kandydaci = Array.isArray(dane.orders) ? dane.orders : [];
            stan.kandydaciWczytani = true;
            stan.kandydaciBlad = null;
            const ids = new Set(stan.kandydaci.map((k) => k.id));
            stan.zaznaczeniKandydaci.forEach((id) => { if (!ids.has(id)) stan.zaznaczeniKandydaci.delete(id); });
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerKandydatow) return;
            stan.kandydaciBlad = e.message;
            stan.kandydaciWczytani = true;
        } finally {
            if (kontroler === kontrolerKandydatow) kontrolerKandydatow = null;
        }
        if (!zniszczona) renderujKandydatow();
    }

    async function dodajKandydatow(ctx, ids) {
        const t = ctx.trasa;
        if (!t || t.status !== 'robocza' || !ids.length) return;
        // Numery do komunikatu odmowy — lista „Do dodania” mogła się w międzyczasie zmienić.
        const znane = stan.kandydaci.slice();
        ids.forEach((id) => stan.dodawani.add(id));
        renderujKandydatow();
        try {
            const odp = await zapytanie('/routes/' + t.id + '/stops', { metoda: 'POST', dane: { order_ids: ids } });
            if (zniszczona) return;
            const dodane = Array.isArray(odp.dodane) ? odp.dodane : [];
            const bledy = Array.isArray(odp.bledy) ? odp.bledy : [];
            // Dodane zamówienia są już na trasie — znikają z „Do dodania” także innej otwartej trasy.
            stan.kandydaci = stan.kandydaci.filter((k) => dodane.indexOf(k.id) === -1);
            dodane.forEach((id) => stan.zaznaczeniKandydaci.delete(id));
            przyjmijOdpowiedz(ctx, odp.route, { zmiana: true });
            if (dodane.length) {
                komunikat('ok', 'Dodano do trasy „' + odp.route.nazwa + '”: ' + ileZamowien(dodane.length) + '.',
                    { klucz: 'trasa', ikona: 'fa-route' });
            }
            if (bledy.length) pokazBledyDodawania(bledy, odp.route.nazwa, znane);
        } finally {
            ids.forEach((id) => stan.dodawani.delete(id));
            if (!zniszczona) {
                renderujKandydatow();
                // „Dodaj zaznaczone” gaśnie po dodaniu — fokus nie może zostać na <body>.
                if (naEkranie(ctx) && kandydaciQ && fokusZgubiony() && !kandydaciSekcja.hidden) {
                    kandydaciQ.focus({ preventScroll: true });
                }
            }
        }
    }

    function pokazBledyDodawania(bledy, nazwaTrasy, znane) {
        const numer = (id) => {
            const z = (znane || []).find((x) => x.id === id);
            return z ? z.numer : '#' + id;
        };
        // (przegląd końcowy, minor 8) Z kluczem — kolejna odmowa zastępuje poprzednią, zamiast
        // układać trwałe okienka błędów jedno na drugim w nakładce Tras.
        komunikat('blad', 'Nie dodano do trasy „' + nazwaTrasy + '” ' + bledy.length + ' ' +
            odmiana(bledy.length, ['zamówienia', 'zamówień', 'zamówień']) + ':', {
            lista: bledy.map((b) => pozycjaOdmowy(numer(b.order_id), b.komunikat)),
            klucz: 'trasa-bledy-dodawania',
        });
    }

    // ── Mapka trasy w edytorze (osobna instancja Leafleta) ──────────────────

    function pokazStanMapki(tekst) {
        if (!mapkaStanEl) return;
        mapkaStanEl.textContent = tekst || '';
        mapkaStanEl.hidden = !tekst;
    }

    /** GeoJSON przebiegu (LineString / MultiLineString, [lng, lat]) → linie [lat, lng]. */
    function liniePrzebiegu(geo) {
        if (!geo || !Array.isArray(geo.coordinates)) return [];
        const naPunkty = (wsp) => (Array.isArray(wsp) ? wsp : [])
            .filter((p) => Array.isArray(p) && p[0] !== null && p[1] !== null && isFinite(p[0]) && isFinite(p[1]))
            .map((p) => [Number(p[1]), Number(p[0])]);
        let linie = [];
        if (geo.type === 'LineString') linie = [naPunkty(geo.coordinates)];
        else if (geo.type === 'MultiLineString') linie = geo.coordinates.map(naPunkty);
        return linie.filter((l) => l.length > 1);
    }

    /** Podkład jak na mapie Dashboardu (ten sam klucz CARTO); bez niej — OpenStreetMap, bez klucza. */
    function warstwaPodkladuMapki() {
        const m = mapaDashboardu();
        const warstwa = m && typeof m.nowaWarstwaPodkladu === 'function' ? m.nowaWarstwaPodkladu() : null;
        if (warstwa) return warstwa;
        return L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
        });
    }

    // (oględziny M9) Najszerszy dymek = pół mapki bez marginesu: dymek z kierunkiem 'auto'
    // (w stronę środka mapki) zawsze mieści się w jej granicach.
    function ustawSzerokoscDymkow() {
        if (!mapkaEl || !mapkaEl.clientWidth) return;
        mapkaEl.style.setProperty('--lg-dymek-maks', Math.max(140, Math.round(mapkaEl.clientWidth / 2 - 28)) + 'px');
    }

    /** „Pokaż całą trasę” pod +/−, w tej samej oprawie co „Pokaż wszystkie trasy” na mapie Dashboardu. */
    function dodajKontrolkeCalejTrasy() {
        const Kontrolka = L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function () {
                const div = L.DomUtil.create('div', 'leaflet-bar lg-mapa-kontrolka');
                const a = L.DomUtil.create('a', '', div);
                a.href = '#';
                a.setAttribute('role', 'button');
                a.title = 'Pokaż całą trasę';
                a.setAttribute('aria-label', 'Pokaż całą trasę');
                a.innerHTML = '<i class="fas fa-expand" aria-hidden="true"></i>';
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.on(a, 'click', (e) => {
                    L.DomEvent.preventDefault(e);
                    dopasujMapke();
                });
                return div;
            },
        });
        new Kontrolka().addTo(mapka);
    }

    function zapewnijMapke() {
        if (mapka) return true;
        if (zniszczona || !mapkaEl) return false;
        if (!L) {
            pokazStanMapki('Mapa niedostępna: nie wczytała się biblioteka map. Przystanki działają bez niej.');
            return false;
        }
        // Schowana podzakładka nie ma wymiarów — mapka powstanie, gdy ResizeObserver je zobaczy.
        if (!mapkaEl.isConnected || !mapkaEl.clientWidth || !mapkaEl.clientHeight) return false;
        mapka = L.map(mapkaEl, {
            minZoom: 5,
            maxZoom: 19,
            // Kółko myszy przybliża dopiero po kliknięciu w mapkę — przewijanie edytora nie łapie się na niej.
            scrollWheelZoom: false,
            // (oględziny I2) Rozmiar pilnuje ResizeObserver (naRozmiarMapki). Nasłuch okna
            // Leafleta przesuwał SCHOWANĄ mapkę (rozmiar 0) i po powrocie trasa była poza kadrem.
            trackResize: false,
            // (oględziny M13) Własna kontrolka zoomu — z polskimi podpisami.
            zoomControl: false,
            zoomAnimation: !bezRuchu,
            fadeAnimation: !bezRuchu,
            markerZoomAnimation: !bezRuchu,
        });
        L.control.zoom({ zoomInTitle: 'Przybliż', zoomOutTitle: 'Oddal' }).addTo(mapka);
        dodajKontrolkeCalejTrasy();
        mapka.attributionControl.setPrefix(false);
        kafelkiMapki = warstwaPodkladuMapki().addTo(mapka);
        warstwaMapki = L.featureGroup().addTo(mapka);
        mapkaUkryta = false;
        mapkaRuszona = false;
        // Ruch mapki, który nie jest naszym dopasowaniem = użytkownik przesunął/przybliżył.
        mapka.on('movestart', () => { if (!dopasowanieMapkiWToku) mapkaRuszona = true; });
        mapka.on('dragstart', () => { mapkaRuszona = true; });
        mapka.on('moveend', () => { dopasowanieMapkiWToku = false; });
        dopasowanieMapkiWToku = true;
        mapka.fitBounds(POLSKA, { padding: [8, 8] });
        dopasowanieMapkiWToku = false;
        mapka.on('click', () => { if (mapka) mapka.scrollWheelZoom.enable(); });
        mapka.on('mouseout', () => { if (mapka) mapka.scrollWheelZoom.disable(); });
        ustawSzerokoscDymkow();
        return true;
    }

    /** (oględziny M6) Podkład Dashboardu zmieniony przy otwartym edytorze — mapka za nim. */
    function naZmianePodkladu(e) {
        if (!e.detail || e.detail.root !== root || zniszczona || !mapka) return;
        const nowa = warstwaPodkladuMapki();
        try {
            nowa.addTo(mapka);
        } catch (err) {
            try { mapka.removeLayer(nowa); } catch (err2) { /* nie zdążyła się dodać */ }
            return;
        }
        if (kafelkiMapki) mapka.removeLayer(kafelkiMapki);
        kafelkiMapki = nowa;
    }

    function ikonaStacji(numer, klasaKoloru, klasaGeo) {
        const tekst = String(numer);
        return L.divIcon({
            className: 'lg-znacznik-przystanku',
            html: '<span class="lg-stacja lg-stacja--mapa ' + klasaKoloru + (tekst.length > 2 ? ' lg-stacja--dlugi' : '') +
                (klasaGeo ? ' ' + klasaGeo : '') + '">' + esc(tekst) + '</span>',
            iconSize: [24, 24],
            iconAnchor: [12, 12],
            // Dymek z kierunkiem 'auto' (lewo/prawo, w stronę środka mapki) — od krawędzi stacji.
            tooltipAnchor: [12, 0],
        });
    }

    function narysujMapke() {
        if (!mapka || !warstwaMapki) return;
        warstwaMapki.clearLayers();
        znacznikiMapki.clear();
        if (isFinite(magazyn.lat) && isFinite(magazyn.lng)) {
            L.marker([magazyn.lat, magazyn.lng], {
                icon: L.divIcon({
                    className: 'lg-znacznik-magazyn',
                    html: '<span class="lg-magazyn lg-magazyn--mapa"><i class="fas fa-industry" aria-hidden="true"></i></span>',
                    iconSize: [24, 36],
                    iconAnchor: [12, 36],
                    tooltipAnchor: [0, -36],
                }),
                zIndexOffset: 1000,
                keyboard: false,
            }).bindTooltip(esc(magazyn.nazwa), { direction: 'top', className: 'lg-podpowiedz-mapy', opacity: 1 })
                .addTo(warstwaMapki);
        }
        const t = stan.otwarta;
        if (!t || stan.nowa) {
            pokazStanMapki('');
            return;
        }
        const klasa = kolor(t.id);
        const przyblizony = !!(t.podsumowanie && t.podsumowanie.przyblizony);
        // Kolejność zmieniona, serwer jeszcze nie przeliczył przebiegu — stara linia blednie.
        const nieaktualna = !!(stan.kolejnosc || kolejnoscObietnica);
        liniePrzebiegu(t.przebieg).forEach((punkty) => {
            L.polyline(punkty, {
                className: 'lg-trasa-obrys', color: '#fff', weight: 8, opacity: 0.9,
                interactive: false, lineCap: 'round', lineJoin: 'round',
            }).addTo(warstwaMapki);
            L.polyline(punkty, {
                className: 'lg-trasa-linia ' + klasa + (przyblizony ? ' is-przyblizona' : '') + (nieaktualna ? ' is-nieaktualna' : ''),
                color: '#1a1a2e', weight: 4, opacity: 1, lineCap: 'round', lineJoin: 'round',
                dashArray: przyblizony ? '8 8' : null, interactive: false,
            }).addTo(warstwaMapki);
        });
        const kolejne = przystankiWidoczne();
        let numer = 0;   // (I5) numer wśród aktywnych, jak na liście przystanków
        kolejne.forEach((z) => {
            const anul = anulowane(z);
            if (!anul) numer += 1;
            if (!maGeo(z)) return;
            const przyblizony = z.geo.quality === 'przyblizona';
            const uwaga = anul ? 'Anulowane — nie trafi do Routimo'
                : (przyblizony ? 'Punkt przybliżony (miejscowość)' : '');
            const znacznik = L.marker([z.geo.lat, z.geo.lng], {
                icon: ikonaStacji(anul ? '—' : numer, klasa, anul ? 'lg-stacja--anulowana' : klasaGeoStacji(z)),
                keyboard: false,          // klawiatura ma listę przystanków obok
                zIndexOffset: anul ? 400 : 500,
                riseOnHover: true,
            }).bindTooltip('<b>' + (anul ? '— ' : numer + '. ') + esc(z.numer) + '</b>' + (z.klient ? ' ' + esc(z.klient) : '') +
                (uwaga ? '<span class="lg-podpowiedz-mapy-uwaga">' + esc(uwaga) + '</span>' : ''), {
                // (oględziny M9) Kierunek wybiera Leaflet (w stronę środka), tekst się zawija —
                // dymek przystanku przy krawędzi mapki nie wychodzi poza nią.
                className: 'lg-podpowiedz-mapy lg-podpowiedz-mapy--zawijana', direction: 'auto', opacity: 1,
            });
            znacznik.on('click', () => wskazPrzystanek(z.id));
            znacznik.addTo(warstwaMapki);
            znacznikiMapki.set(z.id, znacznik);
        });
        if (kolejne.length && !kolejne.some(maGeo)) {
            pokazStanMapki('Przystanki tej trasy nie mają jeszcze punktów na mapie.');
        } else {
            pokazStanMapki('');
        }
    }

    /**
     * Cała trasa w kadrze: przystanki, przebieg i magazyn, z zapasem na kontrolki (M10).
     * animuj === false — bez animacji (powrót z ukrycia, zmiana rozmiaru). Dopasowanie zeruje
     * „mapka ruszona” — od teraz liczy się ruch użytkownika od tego dopasowania.
     */
    function dopasujMapke(animuj) {
        if (!mapka) return;
        if (mapkaEl.clientWidth && mapkaEl.clientHeight) mapka.invalidateSize({ pan: false });
        const punkty = [];
        przystankiWidoczne().forEach((z) => { if (maGeo(z)) punkty.push(L.latLng(z.geo.lat, z.geo.lng)); });
        const t = stan.otwarta;
        if (t && !stan.nowa) liniePrzebiegu(t.przebieg).forEach((l) => l.forEach((p) => punkty.push(L.latLng(p[0], p[1]))));
        if (isFinite(magazyn.lat) && isFinite(magazyn.lng)) punkty.push(L.latLng(magazyn.lat, magazyn.lng));
        mapkaRuszona = false;
        dopasowanieMapkiWToku = true;
        if (punkty.length < 2) {
            if (punkty.length === 1) mapka.setView(punkty[0], 9, { animate: false });
            else mapka.fitBounds(POLSKA, { padding: [8, 8], animate: false });
            dopasowanieMapkiWToku = false;
            return;
        }
        const anim = animuj !== false && !bezRuchu;
        mapka.fitBounds(L.latLngBounds(punkty), Object.assign({ maxZoom: ZOOM_DOPASOWANIA, animate: anim }, MARGINES_MAPKI));
        // Bez animacji mapka już stoi (moveend przyszedł w środku fitBounds); z animacją flaga
        // zejdzie na moveend — ruch w trakcie animacji to nie ruch użytkownika.
        if (!anim) dopasowanieMapkiWToku = false;
    }

    function odswiezMapke(opcje) {
        const o = opcje || {};
        if ((!stan.otwarta && !stan.nowa) || zniszczona) {
            zniszczMapke();
            return;
        }
        if (o.dopasuj) mapkaCzekaNaDopasowanie = true;
        if (!zapewnijMapke()) return;
        narysujMapke();
        if (mapkaCzekaNaDopasowanie || !mapkaDopasowana) {
            dopasujMapke();
            mapkaDopasowana = true;
            mapkaCzekaNaDopasowanie = false;
        }
    }

    function zniszczMapke() {
        znacznikiMapki.clear();
        if (mapka) {
            try { mapka.remove(); } catch (e) { /* kontener mógł już zniknąć z DOM */ }
        }
        mapka = null;
        warstwaMapki = null;
        kafelkiMapki = null;
        mapkaDopasowana = false;
        mapkaUkryta = false;
        mapkaRuszona = false;
        dopasowanieMapkiWToku = false;
    }

    /**
     * ResizeObserver mapki. (oględziny I2) Schowana (podzakładka, inna zakładka panelu) ma
     * rozmiar 0 — tylko to odnotowujemy. Po powrocie (0 → > 0) okno mogło mieć już inną
     * szerokość: invalidateSize trzyma środek, a mapka nieruszana przez użytkownika od
     * ostatniego dopasowania dopasowuje się do trasy od nowa. Tak samo przy zwykłej zmianie
     * rozmiaru (np. mapka przechodzi pod przystanki) — przesuniętej ręcznie nie ruszamy.
     */
    function naRozmiarMapki() {
        if (zniszczona || !mapkaEl) return;
        const widoczna = !!(mapkaEl.isConnected && mapkaEl.clientWidth && mapkaEl.clientHeight);
        if (!mapka) {
            if (widoczna && (stan.otwarta || stan.nowa)) odswiezMapke({ dopasuj: true });
            return;
        }
        if (!widoczna) {
            mapkaUkryta = true;
            return;
        }
        ustawSzerokoscDymkow();
        mapkaUkryta = false;
        // (runda 2, N9) Zawsze ze środkiem na miejscu — przesunięta ręcznie mapka nie ucieka
        // w róg przy zmianie rozmiaru; nieruszana i tak dopasowuje się do trasy.
        mapka.invalidateSize({ pan: true, animate: false });
        if (!mapkaRuszona && (stan.otwarta || stan.nowa)) dopasujMapke(false);
    }

    // ── Mapa Dashboardu: widok „Trasy” ──────────────────────────────────────

    async function odswiezMapeTras() {
        const m = mapaDashboardu();
        if (!m || typeof m.renderTrasy !== 'function' || zniszczona) return;
        if (kontrolerMapy) kontrolerMapy.abort();
        const kontroler = new AbortController();
        kontrolerMapy = kontroler;
        try {
            const dane = await zapytanie('/routes/map', { signal: kontroler.signal });
            if (zniszczona || kontroler !== kontrolerMapy) return;
            const mm = mapaDashboardu();
            if (mm) mm.renderTrasy(Array.isArray(dane.routes) ? dane.routes : []);
        } catch (e) {
            if (przerwane(e) || zniszczona || kontroler !== kontrolerMapy) return;
            const mm = mapaDashboardu();
            if (mm) mm.renderTrasy(null, { blad: e.message });
        } finally {
            if (kontroler === kontrolerMapy) kontrolerMapy = null;
        }
    }

    // Po każdej zmianie trasy: mapa w widoku tras pobiera je od nowa; w widoku zamówień —
    // pobierze przy wejściu w widok (zawsze pobiera).
    function odswiezMapeTrasPoZmianie() {
        const m = mapaDashboardu();
        if (m && typeof m.widok === 'function' && m.widok() === 'trasy') odswiezMapeTras();
    }

    function klikWidokuMapy(e) {
        const b = e.target && e.target.closest ? e.target.closest('[data-lg-mapa-widok]') : null;
        if (!b || b.disabled) return;
        const m = mapaDashboardu();
        if (!m || typeof m.ustawWidok !== 'function') return;
        const widok = b.getAttribute('data-lg-mapa-widok');
        if (typeof m.widok === 'function' && m.widok() === widok) return;
        if (!m.ustawWidok(widok)) {
            komunikat('info', 'Poczekaj, aż zapisze się punkt na mapie.', { klucz: 'mapa' });
            return;
        }
        if (widok === 'trasy') odswiezMapeTras();
    }

    function naWyborTrasyNaMapie(id) {
        if (zniszczona) return;
        const tab = window.LogisticsTab;
        if (tab && tab.root === root && typeof tab.pokazWidok === 'function') {
            tab.pokazWidok('routes', { route_id: id });
        } else {
            otworz(id, { fokus: true });
        }
    }

    function polaczZMapa() {
        const m = mapaDashboardu();
        if (!m || m === mapaPolaczona || zniszczona) return;
        if (odpiecieMapy) odpiecieMapy();
        mapaPolaczona = m;
        odpiecieMapy = typeof m.onWyborTrasy === 'function' ? m.onWyborTrasy(naWyborTrasyNaMapie) : null;
        // Przełącznik „Zamówienia | Trasy” czekał nieaktywny na ten plik i na mapę.
        if (przelacznikMapy && typeof m.ustawWidok === 'function') {
            przelacznikMapy.querySelectorAll('[data-lg-mapa-widok]').forEach((b) => { b.disabled = false; });
            if (typeof m.widok === 'function' && m.widok() === 'trasy') odswiezMapeTras();
        }
        // Kolory tras na liście i w edytorze pochodzą z mapy — teraz już są.
        renderujListe();
        if (stan.otwarta || stan.nowa) renderujEdytor();
    }

    // ── Okno „Dodaj do trasy…” (z listy Dashboardu) ─────────────────────────

    function opisPominietych(lista) {
        const bezTransportu = lista.filter((z) => z.sposob !== TRANSPORT).length;
        const naTrasie = lista.filter((z) => z.sposob === TRANSPORT && z.trasa).length;
        const zamkniete = lista.filter((z) => z.sposob === TRANSPORT && !z.trasa && (z.zamkniete || z.wydane)).length;
        const czesci = [];
        if (bezTransportu) czesci.push(ileZamowien(bezTransportu) + ' bez transportu własnego');
        if (naTrasie) czesci.push(ileZamowien(naTrasie) + ' już na trasie');
        if (zamkniete) czesci.push(ileZamowien(zamkniete) + ' ' + odmiana(zamkniete, ['zamknięte', 'zamknięte', 'zamkniętych']));
        return czesci.join(', ');
    }

    /**
     * Publiczne (logistics.js: pasek hurtu i „bez trasy” w wierszu). zamowienia — wiersze
     * listy ({id, numer, sposob, trasa, zamkniete, m3}). Na trasę trafia tylko otwarty
     * transport własny bez trasy — resztę pomijamy i mówimy o tym w oknie. Obietnica daje
     * {dodane, bledy, orders} (orders = świeże wiersze z plakietką trasy) albo null.
     */
    function dodajDoTrasy(zamowienia, opcje) {
        const o = opcje || {};
        const lista = (Array.isArray(zamowienia) ? zamowienia : []).filter((z) => z && z.id);
        if (zniszczona || !dialogDodaj || !formDodaj || !lista.length) return Promise.resolve(null);
        const pasujace = lista.filter((z) => z.sposob === TRANSPORT && !z.trasa && !z.zamkniete && !z.wydane);
        if (!pasujace.length) {
            komunikat('info', 'Na trasę trafiają tylko otwarte zamówienia z transportem własnym, które nie są jeszcze na trasie. ' +
                'Wśród zaznaczonych: ' + opisPominietych(lista) + '.', { klucz: 'trasa' });
            return Promise.resolve(null);
        }
        if (dodawanie || dialogDodaj.open) return Promise.resolve(null);
        return new Promise((gotowe) => {
            dodawanie = {
                zamowienia: pasujace,
                pominiete: lista.filter((z) => pasujace.indexOf(z) === -1),
                gotowe: gotowe,
                powrot: o.powrot || null,
                trasy: null,
                wynik: null,
                zapis: false,
            };
            otworzOknoDodawania();
        });
    }

    function otworzOknoDodawania() {
        const d = dodawanie;
        const n = d.zamowienia.length;
        const m3 = d.zamowienia.reduce((s, z) => s + (Number(z.m3) || 0), 0);
        d.m3 = m3;
        dodajIleEl.textContent = n === 1 ? d.zamowienia[0].numer : '';
        dodajOpisEl.textContent = (n === 1 ? '' : 'Zaznaczone: ' + ileZamowien(n) + ', ') +
            (n === 1 ? 'Objętość ' : 'razem ') + liczbaM3.format(m3) + ' m³, około ' + kg(m3 * WAGA_KG_NA_M3) + '.' +
            (d.pominiete.length ? ' Pominiemy ' + opisPominietych(d.pominiete) + '.' : '');
        dodajTrasyEl.innerHTML = '<p class="lg-dialog-opis">Wczytywanie tras roboczych…</p>';
        formDodaj.querySelectorAll('input[name="trasa"]').forEach((r) => { r.checked = false; });
        formDodaj.elements.namedItem('name').value = '';
        formDodaj.elements.namedItem('date_from').value = dzisIso();
        formDodaj.elements.namedItem('date_to').value = dzisIso();
        ustawGraniceDat(formDodaj);   // (M8) granice od dzisiejszej daty, przy każdym otwarciu
        dodajNowaEl.hidden = true;
        bladDodawania('');
        ustawZapisDodawania(false);
        odswiezWyborTras();
        dialogDodaj.showModal();
        const nowa = formDodaj.querySelector('input[name="trasa"][value="nowa"]');
        if (nowa) nowa.focus();
        wczytajTrasyRobocze();
    }

    async function wczytajTrasyRobocze() {
        const d = dodawanie;
        if (!d) return;
        try {
            const dane = await zapytanie('/routes?status=robocza');
            if (zniszczona || dodawanie !== d) return;
            d.trasy = (Array.isArray(dane.routes) ? dane.routes : []).slice().sort(poDacie);
            // Ponowne wczytanie (po niepewnej odpowiedzi) zostawia wybraną trasę, jeśli jest na liście.
            const przed = formDodaj.querySelector('.lg-wybor-trasy-lista input[name="trasa"]:checked');
            const wybrana = przed && d.trasy.some((t) => String(t.id) === przed.value) ? Number(przed.value) : null;
            renderujTrasyDoWyboru(wybrana !== null ? wybrana : (d.trasy.length === 1 ? d.trasy[0].id : null));
            const zaznaczony = formDodaj.querySelector('input[name="trasa"]:checked');
            const a = document.activeElement;
            if (!d.trasy.length && !zaznaczony) {
                wybierzNowaWOknie();
            } else if (a && a.name === 'trasa' && a.value === 'nowa' && !a.checked) {
                // Fokus był na „Nowa trasa” tylko dlatego, że lista się wczytywała — teraz
                // na wybraną (jedyną) trasę albo na pierwszą z listy.
                const cel = zaznaczony || dodajTrasyEl.querySelector('input[name="trasa"]');
                if (cel) cel.focus();
            }
        } catch (e) {
            if (zniszczona || dodawanie !== d) return;
            d.trasy = [];
            dodajTrasyEl.innerHTML = '<p class="lg-dialog-opis">Nie wczytano tras roboczych: ' + esc(e.message) +
                ' Możesz dodać zamówienia do nowej trasy.</p>';
            wybierzNowaWOknie();
        }
    }

    function renderujTrasyDoWyboru(wybrana) {
        const d = dodawanie;
        if (!d) return;
        if (!d.trasy.length) {
            dodajTrasyEl.innerHTML = '<p class="lg-dialog-opis">Nie ma tras roboczych. Utwórz nową.</p>';
            odswiezWyborTras();
            return;
        }
        dodajTrasyEl.innerHTML = d.trasy.map((t) => {
            const p = t.podsumowanie || {};
            const ladownosc = t.pojazd && t.pojazd.capacity_kg ? Number(t.pojazd.capacity_kg) : null;
            const po = Math.round(((Number(p.m3) || 0) + d.m3) * WAGA_KG_NA_M3);
            const przekroczy = !!(ladownosc && po > ladownosc);
            return '<label class="lg-wybor-trasy-opcja ' + kolor(t.id) + '">' +
                '<input type="radio" name="trasa" value="' + esc(t.id) + '"' + (t.id === wybrana ? ' checked' : '') + '>' +
                '<span class="lg-wybor-trasy-nazwa">' + esc(t.nazwa) + '</span>' +
                '<span class="lg-wybor-trasy-daty">' + esc(zakresDat(t.date_from, t.date_to)) +
                    (t.pojazd ? ', ' + esc(t.pojazd.name) : '') + '</span>' +
                '<span class="lg-wybor-trasy-liczby"><b>' + esc(Number(p.przystanki) || 0) + '</b> ' +
                    odmiana(Number(p.przystanki) || 0, PRZYSTANEK) + '<br>' +
                    '<span' + (przekroczy ? ' class="is-przekroczona"' : '') + '>po dodaniu ok. ' + esc(kg(po)) +
                    (ladownosc ? ' / ' + esc(kg(ladownosc)) : '') + '</span></span>' +
                '</label>';
        }).join('');
        odswiezWyborTras();
    }

    function wybierzNowaWOknie() {
        const nowa = formDodaj.querySelector('input[name="trasa"][value="nowa"]');
        if (nowa) nowa.checked = true;
        odswiezWyborTras();
        const nazwa = formDodaj.elements.namedItem('name');
        if (nazwa) nazwa.focus();
    }

    function odswiezWyborTras() {
        const wybrany = formDodaj.querySelector('input[name="trasa"]:checked');
        formDodaj.querySelectorAll('.lg-wybor-trasy-opcja').forEach((opcja) => {
            const r = opcja.querySelector('input[name="trasa"]');
            opcja.classList.toggle('is-wybrana', !!(r && r.checked));
        });
        dodajNowaEl.hidden = !(wybrany && wybrany.value === 'nowa');
        if (dodajZapiszBtn && !(dodawanie && dodawanie.zapis)) dodajZapiszBtn.disabled = !wybrany;
    }

    function bladDodawania(tekst) {
        dodajBladEl.textContent = tekst || '';
        dodajBladEl.hidden = !tekst;
        if (!tekst) zdejmijOznaczenia(formDodaj);
    }

    function ustawZapisDodawania(trwa) {
        if (dodawanie) dodawanie.zapis = trwa;
        dodajZapiszBtn.disabled = trwa || !formDodaj.querySelector('input[name="trasa"]:checked');
        dodajZapiszBtn.textContent = trwa ? 'Dodawanie…' : 'Dodaj do trasy';
        const anuluj = formDodaj.querySelector('[data-lg-trasy-akcja="dodaj-anuluj"]');
        if (anuluj) anuluj.disabled = trwa;
        formDodaj.querySelectorAll('input').forEach((pole_) => { pole_.disabled = trwa; });
    }

    /**
     * Zapis okna „Dodaj do trasy…”: (nowa trasa →) POST /stops. (przegląd końcowy, minor 3) Okno
     * zamknięte w trakcie zapisu (drugi Esc w Chrome zamyka je mimo blokady) nie gubi wyniku:
     * zapis kończy się w tle (dodawaniaWTle), lista, edytor i mapa dostają odpowiedź, a wynik
     * albo odmowa trafia do komunikatu. (minor 2) Brak odpowiedzi albo błąd serwera: trasa lub
     * przystanki mogły już się zapisać — dane od nowa i ostrzeżenie przed powtórką.
     */
    async function zapiszDodawanie() {
        const d = dodawanie;
        if (!d || d.zapis) return;
        const wybor = formDodaj.querySelector('input[name="trasa"]:checked');
        if (!wybor) {
            bladDodawania('Wybierz trasę albo „Nowa trasa”.');
            return;
        }
        // Wynik do okna tylko wtedy, gdy wciąż jest otwarte dla TEGO zapisu.
        const wOknie = () => !zniszczona && dodawanie === d;
        const ids = d.zamowienia.map((z) => z.id);
        let trasaId = null;
        let nowa = null;
        if (wybor.value === 'nowa') {
            const dane = {
                name: formDodaj.elements.namedItem('name').value.trim(),
                date_from: formDodaj.elements.namedItem('date_from').value,
                date_to: formDodaj.elements.namedItem('date_to').value || formDodaj.elements.namedItem('date_from').value,
            };
            const blad = bladFormularza(dane, formDodaj);
            if (blad) {
                bladDodawania(blad.tekst);
                const p = formDodaj.elements.namedItem(blad.pole);
                oznaczPole(p, 'lg-trasa-dodaj-blad');
                if (p) p.focus();
                return;
            }
            ustawZapisDodawania(true);
            bladDodawania('');
            try {
                const odp = await zapytanie('/routes', { metoda: 'POST', dane: dane });
                if (zniszczona) return;
                nowa = odp.route;
                trasaId = nowa.id;
                if (stan.listaWczytana) aktualizujNaLiscie(nowa);
            } catch (e) {
                if (zniszczona) return;
                const niepewna = niepewnaOdpowiedz(e);
                const tekst = e.message + (niepewna
                    ? ' Trasa mogła już powstać — sprawdź trasy robocze, zanim utworzysz ją ponownie.' : '');
                if (niepewna) wczytajListe();
                if (wOknie()) {
                    ustawZapisDodawania(false);
                    bladDodawania(tekst);
                    if (niepewna) wczytajTrasyRobocze();
                } else {
                    komunikat('blad', 'Nie utworzono trasy „' + dane.name + '”. ' + tekst, { klucz: 'trasa-dodaj-blad' });
                    zakonczDodawanieWTle(d);
                }
                return;
            }
        } else {
            trasaId = Number(wybor.value);
            ustawZapisDodawania(true);
            bladDodawania('');
        }
        try {
            const odp = await zapytanie('/routes/' + trasaId + '/stops', { metoda: 'POST', dane: { order_ids: ids } });
            if (zniszczona) return;
            const dodane = Array.isArray(odp.dodane) ? odp.dodane : [];
            const bledy = Array.isArray(odp.bledy) ? odp.bledy : [];
            d.wynik = {
                dodane: dodane,
                bledy: bledy,
                orders: (odp.route.przystanki || []).map((p) => p.zamowienie).filter((z) => dodane.indexOf(z.id) !== -1),
            };
            if (stan.listaWczytana || nowa) aktualizujNaLiscie(odp.route);
            if (stan.otwarta && !stan.nowa && stan.otwarta.id === odp.route.id && !akcjaTrwa() && !stan.kolejnosc) {
                przyjmijTrase(odp.route);
                wczytajKandydatow();
            }
            odswiezMapeTrasPoZmianie();
            if (wOknie()) zamknijOknoDodawania(); else zakonczDodawanieWTle(d);
            if (dodane.length) {
                komunikat('ok', 'Dodano do trasy „' + odp.route.nazwa + '”: ' + ileZamowien(dodane.length) + '.',
                    { klucz: 'trasa-dodane', ikona: 'fa-route' });
            }
            if (bledy.length) pokazBledyDodawania(bledy, odp.route.nazwa, d.zamowienia);
        } catch (e) {
            if (zniszczona) return;
            const niepewna = niepewnaOdpowiedz(e);
            const dopisek = niepewna ? ' Zamówienia mogły już trafić na trasę — sprawdź ją, zanim dodasz je ponownie.' : '';
            if (niepewna) {
                wczytajListe();
                if (stan.otwarta && !stan.nowa && stan.otwarta.id === trasaId && !akcjaTrwa() && !stan.kolejnosc) odswiezOtwarta();
                odswiezMapeTrasPoZmianie();
            }
            const poczatek = nowa ? 'Utworzono trasę „' + nowa.nazwa + '”, ale nie dodano do niej zamówień. ' : '';
            if (!wOknie()) {
                komunikat('blad', (poczatek || 'Nie dodano zamówień do trasy. ') + e.message + dopisek,
                    { klucz: 'trasa-dodaj-blad' });
                zakonczDodawanieWTle(d);
                return;
            }
            if (nowa) {
                // Trasa już jest — ponowienie ma dodać do niej, a nie tworzyć drugiej.
                d.trasy = (d.trasy || []).concat([nowa]);
                renderujTrasyDoWyboru(nowa.id);
            }
            ustawZapisDodawania(false);
            bladDodawania(poczatek + e.message + (dopisek || (nowa ? ' Spróbuj ponownie.' : '')));
            if (niepewna && !nowa) wczytajTrasyRobocze();
        }
    }

    // Zapis dokończony w tle (okno zamknięte w trakcie) — obietnica dodajDoTrasy się rozstrzyga.
    function zakonczDodawanieWTle(d) {
        dodawaniaWTle.delete(d);
        d.gotowe(d.wynik || null);
    }

    /** Zamyka okno, oddaje fokus i dopiero wtedy odpowiada logistics.js (fokus przeżyje przerysowanie wiersza). */
    function zamknijOknoDodawania() {
        const d = dodawanie;
        dodawanie = null;
        if (dialogDodaj && dialogDodaj.open) dialogDodaj.close();
        if (!d) return;
        if (d.powrot && d.powrot.isConnected) d.powrot.focus({ preventScroll: true });
        d.gotowe(d.wynik || null);
    }

    /**
     * (minor 3) Okno zamknięte inną drogą niż nasze (np. drugi Esc przeglądarki). W trakcie
     * zapisu nie porzucamy go: zapis kończy się w tle (zapiszDodawanie) i zgłasza wynik
     * komunikatem, a okno jest znów wolne dla kolejnego „Dodaj do trasy…”.
     */
    function poZamknieciuOknaDodawania() {
        const d = dodawanie;
        if (!d) return;
        if (!d.zapis) {
            zamknijOknoDodawania();
            return;
        }
        dodawanie = null;
        dodawaniaWTle.add(d);
        ustawZapisDodawania(false);
        if (d.powrot && d.powrot.isConnected) d.powrot.focus({ preventScroll: true });
    }

    // ── Okno „Odhacz jako wykonaną” ─────────────────────────────────────────
    //
    // (przegląd końcowy, Important) Lista przystanków w oknie pochodzi ZAWSZE ze świeżego
    // GET /routes/<id>, pobranego przy otwarciu („Wczytywanie przystanków…”, odhaczenie czeka),
    // a nie z kopii w edytorze: przystanek zdjęty w międzyczasie przez kogoś innego wracał
    // zaznaczony (422 bez wyjaśnienia), a dodany w ogóle się nie pojawiał i szedł do puli.
    // Odmowa 409/422 albo niepewna odpowiedź pobiera trasę od nowa i przebudowuje listę:
    // wybory przy przystankach, które zostały, przeżywają, a okno mówi, co doszło i co zniknęło.
    // (I1) Każdy przystanek pokazuje stan pakowania. Dostarczone mogą być tylko spakowane
    // w całości (serwer odmawia 409 z `niespakowane`) — pole niespakowanego jest nieaktywne,
    // anulowanego też (takie zamówienie schodzi z trasy i do żadnej puli nie wraca).

    function bladWykonania(tekst) {
        wykonajBladEl.textContent = tekst || '';
        wykonajBladEl.hidden = !tekst;
    }

    // Wyjaśnienie pod stanem przystanku, którego nie da się oznaczyć jako dostarczony (ruling I1).
    const UWAGA_WYKONANIA = {
        niespakowane: 'wróci do puli bez trasy; spakuj na tablecie, żeby oznaczyć jako dostarczone',
        anulowane: 'zdejmiemy z trasy',
    };

    function stanPrzystankuWykonania(p) {
        const z = p.zamowienie || {};
        if (p.anulowane || anulowane(z)) return 'anulowane';
        return z.spakowane ? 'spakowane' : 'niespakowane';
    }

    function pozycjaWykonaniaHtml(w, p) {
        const z = p.zamowienie;
        const stanP = stanPrzystankuWykonania(p);
        const mozna = stanP === 'spakowane';
        // Domyślnie dostarczone są tylko spakowane; wybór użytkownika przeżywa przebudowę listy.
        const zaznaczone = mozna && (w.wybory.has(z.id) ? w.wybory.get(z.id) : true);
        const numer = p.pozycja === null || p.pozycja === undefined ? '—' : p.pozycja;
        const miejscowosc = [z.kod, z.miasto].filter(Boolean).join(' ');
        const adres = [miejscowosc, z.adres].filter(Boolean).join(', ');
        const geo = stanP === 'anulowane' ? 'lg-stacja--anulowana' : klasaGeoStacji(z);
        const nowy = w.nowe.has(z.id);
        const uwaga = UWAGA_WYKONANIA[stanP];
        return '<li><label class="lg-wykonaj-pozycja lg-wykonaj-pozycja--' + stanP + (nowy ? ' is-nowy' : '') + '">' +
            '<input type="checkbox" value="' + esc(z.id) + '"' + (zaznaczone ? ' checked' : '') +
                (mozna ? ' data-lg-mozna="1"' : ' disabled') + '>' +
            '<span class="lg-stacja' + (geo ? ' ' + geo : '') + '" aria-hidden="true">' + esc(numer) + '</span>' +
            '<span class="lg-wykonaj-tresc"><span class="lg-numer">' + esc(z.numer) + '</span>' +
                '<span class="lg-wykonaj-klient">' + (z.klient ? esc(z.klient) : 'brak nazwy') + '</span>' +
                (nowy ? '<span class="lg-wykonaj-nowy">nowy na trasie</span>' : '') +
                (adres ? '<span class="lg-wykonaj-adres" title="' + esc(adres) + '">' + esc(adres) + '</span>' : '') +
                '<span class="lg-wykonaj-stan">' + stanWykonaniaHtml(z, stanP) +
                    (uwaga ? '<span class="lg-wykonaj-uwaga">' + esc(uwaga) + '</span>' : '') + '</span>' +
            '</span>' +
            '<span class="lg-wykonaj-powrot">wróci do puli bez trasy</span>' +
            '</label></li>';
    }

    function pokazStanListyWykonania(tekst, blad) {
        wykonajListaEl.innerHTML = '<li class="lg-wykonaj-stan-listy' + (blad ? ' is-blad' : '') + '">' + esc(tekst) + '</li>';
        wykonajIleEl.textContent = '';
        wykonajIleEl.classList.remove('is-uwaga');
    }

    function renderujListeWykonania(w) {
        const przystanki = (w.trasa && w.trasa.przystanki) || [];
        if (!przystanki.length) {
            pokazStanListyWykonania('Trasa nie ma już przystanków.');
            return;
        }
        wykonajListaEl.innerHTML = przystanki.map((p) => pozycjaWykonaniaHtml(w, p)).join('');
        odswiezLicznikWykonania();
    }

    /** Liczniki pod listą: dostarczone, wracające do puli (w tym niespakowane) i anulowane. */
    function odswiezLicznikWykonania() {
        const pola = Array.from(wykonajListaEl.querySelectorAll('input[type="checkbox"]'));
        if (!pola.length) return;
        let dostarczone = 0;
        let wracaja = 0;
        let niespakowane = 0;
        let anul = 0;
        pola.forEach((c) => {
            const pozycja = c.closest('.lg-wykonaj-pozycja');
            const klasy = pozycja ? pozycja.classList : null;
            const stanP = klasy && klasy.contains('lg-wykonaj-pozycja--anulowane') ? 'anulowane'
                : (klasy && klasy.contains('lg-wykonaj-pozycja--niespakowane') ? 'niespakowane' : 'spakowane');
            if (c.checked) {
                dostarczone += 1;
            } else if (stanP === 'anulowane') {
                anul += 1;
            } else {
                wracaja += 1;
                if (stanP === 'niespakowane') niespakowane += 1;
            }
            // Odznaczony SPAKOWANY: ciepłe tło i „wróci do puli”; niespakowany ma własny opis.
            if (pozycja) pozycja.classList.toggle('is-niedostarczone', !c.checked && stanP === 'spakowane');
        });
        const czesci = [dostarczone
            ? 'Dostarczone: ' + dostarczone + ' z ' + pola.length + '.'
            : 'Nic nie zaznaczono: trasa będzie wykonana bez przystanków.'];
        if (wracaja) {
            czesci.push(ileZamowien(wracaja) + ' ' + odmiana(wracaja, ['wróci', 'wrócą', 'wróci']) + ' do puli bez trasy' +
                (niespakowane ? ' (w tym ' + niespakowane + ' ' + odmiana(niespakowane, ['niespakowane', 'niespakowane',
                    'niespakowanych']) + ')' : '') + '.');
        }
        if (anul) czesci.push(ileAnulowanych(anul) + ' zdejmiemy z trasy.');
        wykonajIleEl.classList.toggle('is-uwaga', !dostarczone);
        wykonajIleEl.textContent = czesci.join(' ');
    }

    /**
     * Przyciski i pola okna: odhaczenie czeka na świeżą listę i na zapis; trasy, która nie jest
     * już robocza ani zatwierdzona (albo nie ma przystanków), odhaczyć się nie da. Pola
     * niespakowanych i anulowanych zostają nieaktywne także po nieudanym zapisie.
     */
    function odswiezPrzyciskiWykonania() {
        const w = wykonywanie;
        const trwa = !!(w && w.zapis);
        const wczytuje = !!(w && w.wczytywanie);
        const t = w ? w.trasa : null;
        const aktywna = !!(t && (t.status === 'robocza' || t.status === 'zatwierdzona') && (t.przystanki || []).length);
        wykonajZapiszBtn.disabled = trwa || wczytuje || !aktywna;
        wykonajZapiszBtn.textContent = trwa ? 'Zapisywanie…' : 'Odhacz jako wykonaną';
        const anuluj = formWykonaj.querySelector('[data-lg-trasy-akcja="wykonaj-anuluj"]');
        if (anuluj) anuluj.disabled = trwa;
        wykonajListaEl.querySelectorAll('input[type="checkbox"]').forEach((c) => {
            c.disabled = trwa || wczytuje || !aktywna || c.getAttribute('data-lg-mozna') !== '1';
        });
        if (wczytuje) wykonajListaEl.setAttribute('aria-busy', 'true'); else wykonajListaEl.removeAttribute('aria-busy');
    }

    function ustawZapisWykonania(trwa) {
        if (wykonywanie) wykonywanie.zapis = trwa;
        odswiezPrzyciskiWykonania();
    }

    // „Nowe na trasie: 26/00014. Zdjęte z trasy: 26/00012.” — różnica list przed i po odświeżeniu.
    function opisZmianPrzystankow(przed, po) {
        const idsPrzed = new Set((przed.przystanki || []).map((p) => p.zamowienie.id));
        const idsPo = new Set((po.przystanki || []).map((p) => p.zamowienie.id));
        const nowe = (po.przystanki || []).filter((p) => !idsPrzed.has(p.zamowienie.id)).map((p) => p.zamowienie.numer);
        const zdjete = (przed.przystanki || []).filter((p) => !idsPo.has(p.zamowienie.id)).map((p) => p.zamowienie.numer);
        const czesci = [];
        if (nowe.length) czesci.push('Nowe na trasie: ' + nowe.join(', ') + '.');
        if (zdjete.length) czesci.push('Zdjęte z trasy: ' + zdjete.join(', ') + '.');
        return czesci.length ? 'Lista przystanków jest już aktualna. ' + czesci.join(' ') : '';
    }

    /**
     * Świeży odczyt trasy z okna poprawia też edytor pod oknem — gdy pokazuje tę trasę i nie ma
     * w drodze jej zmiany ani kolejności; starszy odczyt nie cofa świeższej odpowiedzi mutacji
     * (ta sama reguła co odswiezOtwarta).
     */
    function przyjmijOdczytTrasy(route, start) {
        if (zniszczona || !route || !stan.otwarta || stan.nowa || stan.otwarta.id !== route.id ||
            akcjaTrwa() || stan.kolejnosc) return;
        const lokalna = lokalneZmiany.get(route.id);
        if (lokalna && lokalna.wersja > start) return;
        przyjmijTrase(route);
        if (edytowalnaTrasa()) wczytajKandydatow();
    }

    // Trasa z okna zniknęła (404 — ktoś ją usunął): okno się zamyka, edytor i lista bez niej.
    function trasaZniknelaZOkna(w) {
        zamknijWykonanie(true);
        const wEdytorze = !!(stan.otwarta && !stan.nowa && stan.otwarta.id === w.id);
        if (wEdytorze) {
            resetEdytora();
            stan.otwarta = null;
            renderujEdytor();
        }
        usunZListy(w.id);
        odswiezMapeTrasPoZmianie();
        komunikat('blad', 'Trasy „' + w.nazwa + '” już nie ma. Ktoś mógł ją usunąć.', { klucz: 'trasa' });
        const cel = wEdytorze ? root.querySelector('[data-lg-trasy-akcja="nowa"]') : (w.powrot && w.powrot.isConnected ? w.powrot : null);
        if (cel && cel.offsetParent !== null) cel.focus({ preventScroll: true });
    }

    // Po odhaczeniu (także takim, którego odpowiedź nie dotarła) — komunikat i fokus; trasę do
    // edytora i listy wołający przyjmuje wcześniej (przyjmijOdpowiedz). naMiejscu — sprzed tego.
    function poOdhaczeniu(w, route, wynik, naMiejscu) {
        if (wynik) {
            const d = (wynik.dostarczone || []).length;
            // Anulowane (według listy w oknie) do żadnej puli nie wracają — po prostu schodzą z trasy.
            const anulowaneWOknie = new Set(((w.trasa && w.trasa.przystanki) || [])
                .filter((p) => stanPrzystankuWykonania(p) === 'anulowane').map((p) => p.zamowienie.id));
            const niedostarczone = wynik.niedostarczone || [];
            const a = niedostarczone.filter((id) => anulowaneWOknie.has(id)).length;
            const n = niedostarczone.length - a;
            komunikat('ok', 'Trasa „' + route.nazwa + '” wykonana: dostarczono ' + ileZamowien(d) +
                (n ? ', ' + ileZamowien(n) + ' ' + odmiana(n, ['wraca', 'wracają', 'wraca']) + ' do puli bez trasy' : '') +
                (a ? ', ' + ileAnulowanych(a) + ' ' + odmiana(a, ['zdjęte', 'zdjęte', 'zdjętych']) + ' z trasy' : '') + '.',
                { klucz: 'trasa' });
        } else {
            komunikat('ok', 'Trasa „' + route.nazwa + '” jest wykonana — odpowiedź serwera nie dotarła, ale odhaczenie się zapisało.',
                { klucz: 'trasa' });
        }
        if (naMiejscu && tytulEl && tytulEl.offsetParent !== null) {
            tytulEl.focus({ preventScroll: true });
        } else if (w.powrot && w.powrot.isConnected && w.powrot.offsetParent !== null && !w.powrot.disabled) {
            w.powrot.focus({ preventScroll: true });
        }
    }

    // Fokus po wczytaniu listy: z początkowego „Anuluj” (albo zgubionego) na pierwszy przystanek
    // do odhaczenia; fokusu przeniesionego przez użytkownika w trakcie wczytywania nie zabieramy.
    function fokusWOknieWykonania(poczatkowy) {
        const a = document.activeElement;
        const anuluj = formWykonaj.querySelector('[data-lg-trasy-akcja="wykonaj-anuluj"]');
        const zgubiony = !a || a === document.body || !a.isConnected || !dialogWykonaj.contains(a) || a.disabled;
        if (!zgubiony && !(poczatkowy && a === anuluj)) return;
        const cel = wykonajListaEl.querySelector('input[type="checkbox"]:not(:disabled)') ||
            (!wykonajZapiszBtn.disabled ? wykonajZapiszBtn : anuluj);
        if (cel) cel.focus();
    }

    /**
     * Świeża trasa do okna (GET /routes/<id>) i lista z niej. opcje (po odmowie odhaczenia):
     * tekst — odmowa do pokazania w oknie, niespakowane — id z 409 (odznaczamy je), niepewna —
     * odpowiedź nie dotarła: trasa już wykonana znaczy, że odhaczenie się zapisało.
     */
    async function wczytajDoWykonania(w, opcje) {
        const o = opcje || {};
        if (w.kontroler) w.kontroler.abort();
        const kontroler = new AbortController();
        w.kontroler = kontroler;
        w.wczytywanie = true;
        if (!w.trasa) pokazStanListyWykonania('Wczytywanie przystanków…');
        odswiezPrzyciskiWykonania();
        const start = licznikZmian;
        let dane = null;
        let blad = null;
        try {
            dane = await zapytanie('/routes/' + w.id, { signal: kontroler.signal });
        } catch (e) {
            blad = e;
        }
        if (zniszczona || w.kontroler !== kontroler || (blad && przerwane(blad))) return;
        w.kontroler = null;
        w.wczytywanie = false;
        if (wykonywanie !== w) return;   // okno zamknięte w międzyczasie
        if (blad) {
            if (blad.status === 404) {
                trasaZniknelaZOkna(w);
                return;
            }
            if (!w.trasa) pokazStanListyWykonania('Nie wczytano przystanków trasy.', true);
            bladWykonania((o.tekst ? o.tekst + ' ' : '') + 'Nie wczytano aktualnej listy przystanków: ' + blad.message +
                ' Zamknij okno i otwórz je ponownie.');
            odswiezPrzyciskiWykonania();
            return;
        }
        const trasa = dane.route;
        if (o.niepewna && trasa.status === 'wykonana') {
            zamknijWykonanie(true);
            const naMiejscu = naEkranie(w);
            przyjmijOdpowiedz(w, trasa, { formularz: true, zmiana: true });
            poOdhaczeniu(w, trasa, null, naMiejscu);
            return;
        }
        przyjmijOdczytTrasy(trasa, start);
        const poprzednia = w.trasa;
        w.trasa = trasa;
        if (poprzednia) {
            const przed = new Set((poprzednia.przystanki || []).map((p) => p.zamowienie.id));
            w.nowe = new Set((trasa.przystanki || []).map((p) => p.zamowienie.id).filter((id) => !przed.has(id)));
        }
        (o.niespakowane || []).forEach((id) => w.wybory.set(Number(id), false));
        renderujListeWykonania(w);
        odswiezPrzyciskiWykonania();
        const teksty = [];
        if (o.tekst) teksty.push(o.tekst);
        if (o.niepewna) teksty.push('Trasa nie jest odhaczona — spróbuj ponownie.');
        if (poprzednia) {
            const zmiany = opisZmianPrzystankow(poprzednia, trasa);
            if (zmiany) teksty.push(zmiany);
        }
        if (trasa.status !== 'robocza' && trasa.status !== 'zatwierdzona') {
            teksty.push('Trasa „' + trasa.nazwa + '” jest już ' + String(NAZWY_STATUSOW[trasa.status] || trasa.status).toLowerCase() +
                ' — nie ma czego odhaczać.');
        } else if (!(trasa.przystanki || []).length) {
            teksty.push('Trasa nie ma już przystanków — nie ma czego odhaczać.');
        }
        bladWykonania(teksty.join(' '));
        fokusWOknieWykonania(!poprzednia);
    }

    let wykonanieOtwierane = false;   // dwuklik „Odhacz” nie otwiera okna dwa razy (showModal rzuca)

    async function otworzWykonanie(powrot) {
        const t = stan.otwarta;
        if (!t || stan.nowa || (t.status !== 'robocza' && t.status !== 'zatwierdzona') || !dialogWykonaj) return;
        if (wykonanieOtwierane || wykonywanie || dialogWykonaj.open || akcjaTrwa()) return;
        if (zmieniony() && !formularzPoprawny()) return;
        wykonanieOtwierane = true;
        try {
            await przygotujWykonanie(powrot);
        } finally {
            wykonanieOtwierane = false;
        }
    }

    async function przygotujWykonanie(powrot) {
        const sesja = stan.sesja;
        // Niezapisane zmiany roboczej — najpierw zapis (po odhaczeniu trasa jest tylko do odczytu).
        if (zmieniony()) {
            const ok = await mutacja((ctx) => zapisz(ctx, true));
            if (!ok) return;
        } else {
            await dokonczKolejnosc();
        }
        // (oględziny A1) W trakcie zapisu użytkownik przeszedł do innej trasy albo zamknął
        // edytor — okno „Odhacz” nie otwiera się dla trasy, której nie wybierał.
        if (zniszczona || stan.sesja !== sesja) return;
        const trasa = stan.otwarta;
        if (!trasa || stan.nowa || (trasa.status !== 'robocza' && trasa.status !== 'zatwierdzona')) return;
        const w = {
            id: trasa.id, nazwa: trasa.nazwa, sesja: sesja, powrot: powrot || null, zapis: false,
            wczytywanie: false, trasa: null, wybory: new Map(), nowe: new Set(), kontroler: null,
        };
        wykonywanie = w;
        wykonajNazwaEl.textContent = trasa.nazwa;
        ustawKolor(wykonajListaEl, kolor(trasa.id));
        bladWykonania('');
        pokazStanListyWykonania('Wczytywanie przystanków…');
        dialogWykonaj.showModal();
        const anuluj = formWykonaj.querySelector('[data-lg-trasy-akcja="wykonaj-anuluj"]');
        if (anuluj) anuluj.focus();
        await wczytajDoWykonania(w);
    }

    // bezFokusu — po udanym odhaczeniu fokus ustawia poOdhaczeniu (przyciski będą inne).
    function zamknijWykonanie(bezFokusu) {
        const w = wykonywanie;
        wykonywanie = null;
        if (w && w.kontroler) w.kontroler.abort();
        if (dialogWykonaj && dialogWykonaj.open) dialogWykonaj.close();
        if (bezFokusu) return;
        const cel = w && w.powrot && w.powrot.isConnected ? w.powrot : tytulEl;
        if (cel) cel.focus({ preventScroll: true });
    }

    /**
     * (oględziny A1) Odhaczamy trasę z okna (w.id), nie tę, która akurat jest w edytorze —
     * gdy edytor zmienił się pod oknem, wynik i tak trafia na listę, a komunikat mówi, która
     * trasa została wykonana. (I3) Po odhaczeniu fokus na tytuł edytora. Odmowa 409/422 albo
     * niepewna odpowiedź przy otwartym oknie: lista od nowa (wczytajDoWykonania), tekst odmowy
     * zostaje w oknie, zamówienia z `niespakowane` odznaczone.
     */
    async function zatwierdzWykonanie() {
        const w = wykonywanie;
        if (!w || w.zapis || w.wczytywanie || !w.trasa || zniszczona) return;
        const klucz = String(w.id);
        if (stan.wToku.has(klucz)) return;
        // Zawsze jawna lista (także pusta) — bez niej serwer odmawia (M6). Tylko pola, które da
        // się zaznaczyć: niespakowane i anulowane nigdy nie idą jako dostarczone.
        const dostarczone = Array.from(wykonajListaEl.querySelectorAll('input[type="checkbox"]'))
            .filter((c) => c.checked && c.getAttribute('data-lg-mozna') === '1').map((c) => Number(c.value));
        ustawZapisWykonania(true);
        bladWykonania('');
        stan.wToku.add(klucz);
        odswiezAkcje();
        let odswiez = false;
        try {
            const odp = await zapytanie('/routes/' + w.id + '/complete', {
                metoda: 'POST', dane: { delivered_order_ids: dostarczone },
            });
            if (zniszczona) return;
            stan.wToku.delete(klucz);
            zamknijWykonanie(true);
            const naMiejscu = naEkranie(w);
            przyjmijOdpowiedz(w, odp.route, { formularz: true, zmiana: true });
            poOdhaczeniu(w, odp.route, odp.wynik || {}, naMiejscu);
        } catch (e) {
            if (zniszczona) return;
            const niepewna = niepewnaOdpowiedz(e);
            const odNowa = e.status === 409 || e.status === 422 || niepewna;
            if (wykonywanie === w) {
                ustawZapisWykonania(false);
                if (e.status === 404) {
                    trasaZniknelaZOkna(w);
                } else if (odNowa) {
                    const niespakowane = e.dane && Array.isArray(e.dane.niespakowane) ? e.dane.niespakowane : [];
                    if (niepewna) wczytajListe();
                    wczytajDoWykonania(w, { tekst: e.message, niespakowane: niespakowane, niepewna: niepewna });
                } else {
                    bladWykonania(e.message);
                }
            } else {
                // Okno zamknięte w trakcie zapisu — odmowa trafia do komunikatu, edytor od nowa.
                komunikat('blad', 'Trasa „' + w.nazwa + '”: ' + e.message +
                    (niepewna ? ' Odhaczenie mogło się zapisać — trasę pobieramy od nowa.' : ''),
                    { klucz: kluczBleduTrasy(klucz) });
                if (niepewna) wczytajListe();
                odswiez = odNowa || e.status === 404;
            }
        } finally {
            stan.wToku.delete(klucz);
            if (!zniszczona) {
                odswiezAkcje();
                if (odswiez && stan.otwarta && !stan.nowa && stan.otwarta.id === w.id) odswiezOtwarta();
            }
        }
    }

    // ── Zdarzenia ───────────────────────────────────────────────────────────

    function akcjaEdytora(akcja, przycisk) {
        const t = stan.otwarta;
        switch (akcja) {
            case 'nowa':
                nowaTrasa();
                break;
            case 'odswiez-liste':
                wczytajListe();
                if (stan.otwarta && !akcjaTrwa() && !stan.kolejnosc) odswiezOtwarta();
                break;
            case 'zamknij':
            case 'anuluj-nowa':
                zamknijEdytor();
                break;
            case 'utworz':
                if (formularzPoprawny()) mutacja(utworz);
                break;
            case 'zapisz':
                if (formularzPoprawny()) mutacja((ctx) => zapisz(ctx, false));
                break;
            case 'zatwierdz':
                if (!zmieniony() || formularzPoprawny()) mutacja(zatwierdz);
                break;
            case 'cofnij':
                if (t && window.confirm('Cofnąć zatwierdzenie trasy „' + t.nazwa + '”?\n' +
                    'Trasę będzie można znów edytować. Plik dla Routimo trzeba będzie wyeksportować ponownie.')) {
                    mutacja(cofnij);
                }
                break;
            case 'przywroc':
                if (t && window.confirm('Przywrócić trasę „' + t.nazwa + '” do zatwierdzonych?\n' +
                    'Jej zamówienia wrócą do otwartych w logistyce.')) {
                    mutacja(przywroc);
                }
                break;
            case 'usun': {
                const ile = liczbaPrzystankow();
                if (t && window.confirm('Usunąć trasę „' + t.nazwa + '”?' +
                    (ile ? '\n' + ileZamowien(ile) + ' ' + odmiana(ile, ['wróci', 'wrócą', 'wróci']) + ' do puli bez trasy.' : ''))) {
                    mutacja(usunTrase);
                }
                break;
            }
            case 'routimo':
                mutacja(eksportujRoutimo, { odczyt: true });
                break;
            case 'wykonaj':
                otworzWykonanie(przycisk);
                break;
            case 'dodaj-zaznaczone':
                mutacja((ctx) => dodajKandydatow(ctx, Array.from(stan.zaznaczeniKandydaci)));
                break;
            case 'wykonane-reset':
                if (filtrWykonanychEl) filtrWykonanychEl.reset();
                wczytajWykonane('', '');
                break;
            default:
                break;
        }
    }

    function naKlikPanelu(e) {
        const pozycja = e.target.closest('[data-lg-trasa-id]');
        if (pozycja && panel.contains(pozycja)) {
            // (runda 2, N1) Jak przy otwarciu z mapy: fokus na tytuł edytora — wąsko lista
            // znika z ekranu, a szeroko klawiatura trafia od razu do otwartej trasy.
            otworz(Number(pozycja.getAttribute('data-lg-trasa-id')), { fokus: true });
            return;
        }
        const przystanek = e.target.closest('[data-lg-przystanek]');
        if (przystanek && !przystanek.disabled) {
            const li = przystanek.closest('.lg-przystanek[data-order-id]');
            if (!li) return;
            const id = Number(li.getAttribute('data-order-id'));
            const akcja = przystanek.getAttribute('data-lg-przystanek');
            const indeks = kolejnoscWidoczna().indexOf(id);
            if (akcja === 'gora') przesun(id, indeks - 1);
            else if (akcja === 'dol') przesun(id, indeks + 1);
            else if (akcja === 'usun' && akcjaTrwa()) oglos('Poczekaj, aż zapisze się poprzednia zmiana trasy.');
            else if (akcja === 'usun') mutacja((ctx) => usunPrzystanek(ctx, id));
            return;
        }
        const kandydat = e.target.closest('[data-lg-kandydat="dodaj"]');
        if (kandydat && !kandydat.disabled && kandydat.getAttribute('aria-disabled') !== 'true') {
            const li = kandydat.closest('.lg-kandydat[data-order-id]');
            if (li) mutacja((ctx) => dodajKandydatow(ctx, [Number(li.getAttribute('data-order-id'))]));
            return;
        }
        const przycisk = e.target.closest('[data-lg-trasy-akcja]');
        // aria-disabled = zmiana tej trasy w drodze: bez pytań (confirm) i bez drugiej zmiany.
        if (przycisk && !przycisk.disabled && przycisk.getAttribute('aria-disabled') !== 'true') {
            akcjaEdytora(przycisk.getAttribute('data-lg-trasy-akcja'), przycisk);
        }
    }

    // (oględziny M1) Zmiana pola formularza: stary czerwony błąd dotyczył poprzednich wartości.
    function poZmianiePola(t) {
        if (!form || !form.contains(t) || bladEl.hidden) return;
        pokazBlad('');
    }

    function naZmianePanelu(e) {
        const t = e.target;
        poZmianiePola(t);
        if (t === selectPojazdu) {
            stan.wybranyPojazd = t.value;
            renderujSelecty();
        } else if (t === selectKierowcy) {
            stan.wybranyKierowca = t.value;
            renderujSelecty();
        } else if (t === pole('date_from') || t === pole('date_to')) {
            // Data „od” po „do” — przesuwamy „do” (trasa co najmniej jednodniowa). Tylko
            // poprawną datą: rok 92026 z niedokończonego wpisywania nie może trafić do „do”.
            if (t === pole('date_from') && wGranicach(t.value, graniceDat()) &&
                pole('date_to').value && pole('date_to').value < t.value) {
                pole('date_to').value = t.value;
            }
            // (M8) min/max „do” idą za „od” (najwyżej 31 dni po nim).
            if (t === pole('date_from') && edytowalnaForma()) ustawGraniceDat(form);
            planujDostepnosc();
            odswiezAkcje();
        } else if (t.classList && t.classList.contains('lg-kandydat-zaznacz')) {
            const li = t.closest('.lg-kandydat[data-order-id]');
            if (!li) return;
            const id = Number(li.getAttribute('data-order-id'));
            if (t.checked) stan.zaznaczeniKandydaci.add(id); else stan.zaznaczeniKandydaci.delete(id);
            li.classList.toggle('is-zaznaczony', t.checked);
            renderujPrzyciskDodawania();
        }
    }

    function naWpisywaniePanelu(e) {
        const t = e.target;
        if (form && form.contains(t)) {
            poZmianiePola(t);
            odswiezAkcje();
        } else if (t === kandydaciQ) {
            clearTimeout(timerSzukania);
            timerSzukania = setTimeout(() => {
                const q = kandydaciQ.value.trim();
                if (q === stan.kandydaciQ) return;
                stan.kandydaciQ = q;
                wczytajKandydatow();
            }, DEBOUNCE_SZUKAJ_MS);
        }
    }

    function naKlawiszPanelu(e) {
        const t = e.target;
        if (e.key === 'Enter' && form && form.contains(t) && t.tagName === 'INPUT') {
            // Enter w polu formularza = główna akcja: utworzenie albo zapis.
            e.preventDefault();
            if (akcjaTrwa()) return;
            if (stan.nowa) {
                if (formularzPoprawny()) mutacja(utworz);
            } else if (zmieniony() && formularzPoprawny()) {
                mutacja((ctx) => zapisz(ctx, false));
            }
        } else if (e.key === 'Enter' && t === kandydaciQ) {
            // Enter — szukamy od razu, bez czekania na zwłokę wpisywania.
            e.preventDefault();
            clearTimeout(timerSzukania);
            const q = kandydaciQ.value.trim();
            if (q !== stan.kandydaciQ) {
                stan.kandydaciQ = q;
                wczytajKandydatow();
            }
        } else if (e.key === 'Escape' && t === kandydaciQ && kandydaciQ.value) {
            e.preventDefault();
            kandydaciQ.value = '';
            clearTimeout(timerSzukania);
            stan.kandydaciQ = '';
            wczytajKandydatow();
        }
    }

    function naWyslaniePanelu(e) {
        if (e.target === filtrWykonanychEl) {
            e.preventDefault();
            const od = filtrWykonanychEl.elements.namedItem('od');
            const doDnia = filtrWykonanychEl.elements.namedItem('do');
            zdejmijOznaczenia(filtrWykonanychEl);
            // (oględziny M5) Błędna data nie idzie do serwera — komunikat w formacie pola.
            const bladOd = bladDaty(od, 'od', false);
            const bladDo = bladOd ? null : bladDaty(doDnia, 'do', false);
            if (bladOd || bladDo) {
                const zle = bladOd ? od : doDnia;
                if (opisWykonanychEl) opisWykonanychEl.textContent = bladOd || bladDo;
                oznaczPole(zle, 'lg-trasy-wykonane-opis');
                zle.focus();
                return;
            }
            wczytajWykonane(od.value, doDnia.value);
        } else if (e.target === form) {
            e.preventDefault();
        }
    }

    function naNajazdPrzystanku(e) {
        const li = e.target.closest ? e.target.closest('.lg-przystanek[data-order-id]') : null;
        const znacznik = li ? znacznikiMapki.get(Number(li.getAttribute('data-order-id'))) : null;
        znacznikiMapki.forEach((m) => { if (m !== znacznik && m.isTooltipOpen()) m.closeTooltip(); });
        if (znacznik && !znacznik.isTooltipOpen()) znacznik.openTooltip();
    }

    function naOpuszczeniePrzystankow() {
        znacznikiMapki.forEach((m) => { if (m.isTooltipOpen()) m.closeTooltip(); });
    }

    async function odswiezOtwarta() {
        const t = stan.otwarta;
        if (!t || stan.nowa || zniszczona) return;
        const start = licznikZmian;
        try {
            const dane = await zapytanie('/routes/' + t.id);
            if (zniszczona || !stan.otwarta || stan.nowa || stan.otwarta.id !== t.id || akcjaTrwa() || stan.kolejnosc) return;
            // (oględziny m3) Trasa zmieniła się u nas po wysłaniu tego odczytu (odpowiedź
            // mutacji jest świeższa) — starszy odczyt jej nie cofa.
            const lokalna = lokalneZmiany.get(t.id);
            if (lokalna && lokalna.wersja > start) return;
            przyjmijTrase(dane.route);
            if (edytowalnaTrasa()) wczytajKandydatow();
        } catch (e) {
            if (zniszczona || !stan.otwarta || stan.otwarta.id !== t.id) return;
            if (e.status === 404) {
                resetEdytora();
                stan.otwarta = null;
                usunZListy(t.id);
                renderujEdytor();
                komunikat('blad', 'Trasy „' + t.nazwa + '” już nie ma. Ktoś mógł ją usunąć.', { klucz: 'trasa' });
            }
        }
    }

    /**
     * Podzakładka „Trasy” na ekranie: świeża lista, ewentualna trasa do otwarcia (pokazWidok)
     * i (oględziny M2) świeża dostępność pojazdów i kierowców — we Flocie mogła się zmienić
     * ładowność, nazwa albo włączenie pojazdu.
     */
    function pokazano() {
        if (zniszczona) return;
        wczytajListe();
        const doOtwarcia = panel.getAttribute('data-lg-otworz-trase');
        if (doOtwarcia) {
            panel.removeAttribute('data-lg-otworz-trase');
            otworz(Number(doOtwarcia), { fokus: true });
            return;
        }
        if (stan.otwarta && !akcjaTrwa() && !stan.kolejnosc) odswiezOtwarta();
        if (edytowalnaForma()) wczytajDostepnosc();
    }

    function naZmianeWidoku(e) {
        const d = e.detail || {};
        if (d.root !== root) return;
        if (d.widok === 'routes') pokazano();
    }

    // logistics.js: zmiana sposobu dostawy zdjęła zamówienia z trasy (usunieto_z_trasy).
    function naZmianeTras(e) {
        if (!e.detail || e.detail.root !== root || zniszczona) return;
        if (stan.listaWczytana) wczytajListe();
        if (stan.otwarta && !akcjaTrwa() && !stan.kolejnosc) odswiezOtwarta();
        odswiezMapeTrasPoZmianie();
    }

    // (oględziny M2) logistics-fleet.js: pojazd dodany, zmieniony, wyłączony albo włączony.
    // Przy schowanych Trasach (zmiany robi się we Flocie) dostępność pobierze pokazano()
    // przy powrocie — bez drugiego, zbędnego zapytania (runda 2, drobiazgi).
    function naZmianeFloty(e) {
        if (!e.detail || e.detail.root !== root || zniszczona || panel.hidden) return;
        if (edytowalnaForma()) wczytajDostepnosc();
    }

    // (oględziny M12) Przeładowanie albo zamknięcie karty z niezapisanymi zmianami trasy
    // (albo kolejnością, która jeszcze nie poszła do serwera) — przeglądarka pyta.
    function przedZamknieciem(e) {
        if (zniszczona || !(zmieniony() || stan.kolejnosc)) return;
        e.preventDefault();
        e.returnValue = '';
    }

    function naGotowaMape(e) {
        if (e.detail && e.detail.root === root) polaczZMapa();
    }

    function zniszcz() {
        zniszczona = true;
        sluchacze.abort();
        [kontrolerListy, kontrolerWykonanych, kontrolerTrasy, kontrolerDostepnosci, kontrolerKandydatow, kontrolerMapy]
            .forEach((k) => { if (k) k.abort(); });
        clearTimeout(timerDostepnosci);
        clearTimeout(timerSzukania);
        clearTimeout(timerKolejnosci);
        if (odpiecieMapy) odpiecieMapy();
        odpiecieMapy = null;
        mapaPolaczona = null;
        if (obserwatorMapki) obserwatorMapki.disconnect();
        zniszczMapke();
        if (dodawanie) {
            const d = dodawanie;
            dodawanie = null;
            d.gotowe(null);
        }
        dodawaniaWTle.forEach((d) => d.gotowe(null));
        dodawaniaWTle.clear();
        if (dialogDodaj && dialogDodaj.open) dialogDodaj.close();
        if (wykonywanie && wykonywanie.kontroler) wykonywanie.kontroler.abort();
        wykonywanie = null;
        if (dialogWykonaj && dialogWykonaj.open) dialogWykonaj.close();
        if (window.LogisticsRoutes === api) delete window.LogisticsRoutes;
    }

    const api = {
        root: root,
        otworz: (routeId) => otworz(routeId),
        dodajDoTrasy: dodajDoTrasy,
        zniszcz: zniszcz,
    };

    // ── Start ───────────────────────────────────────────────────────────────

    window.LogisticsRoutes = api;

    panel.addEventListener('click', naKlikPanelu, naSluch);
    panel.addEventListener('change', naZmianePanelu, naSluch);
    panel.addEventListener('input', naWpisywaniePanelu, naSluch);
    panel.addEventListener('keydown', naKlawiszPanelu, naSluch);
    panel.addEventListener('submit', naWyslaniePanelu, naSluch);
    if (przystankiEl) {
        przystankiEl.addEventListener('pointerdown', (e) => {
            chwytZPrzycisku = !!(e.target.closest && e.target.closest('button, a, input, select, textarea'));
        }, naSluch);
        przystankiEl.addEventListener('dragstart', naDragStart, naSluch);
        przystankiEl.addEventListener('dragover', naDragOver, naSluch);
        przystankiEl.addEventListener('dragleave', naDragLeave, naSluch);
        przystankiEl.addEventListener('drop', naDrop, naSluch);
        przystankiEl.addEventListener('dragend', zakonczPrzeciaganie, naSluch);
        przystankiEl.addEventListener('mouseover', naNajazdPrzystanku, naSluch);
        przystankiEl.addEventListener('mouseleave', naOpuszczeniePrzystankow, naSluch);
    }
    if (przelacznikMapy) przelacznikMapy.addEventListener('click', klikWidokuMapy, naSluch);

    if (dialogDodaj && formDodaj) {
        formDodaj.addEventListener('submit', (e) => {
            e.preventDefault();
            zapiszDodawanie();
        }, naSluch);
        formDodaj.addEventListener('change', (e) => {
            if (e.target && e.target.name === 'trasa') {
                odswiezWyborTras();
                bladDodawania('');
                if (e.target.value === 'nowa') {
                    const nazwa = formDodaj.elements.namedItem('name');
                    if (nazwa) nazwa.focus();
                }
            } else if (e.target === formDodaj.elements.namedItem('date_from')) {
                const doDnia = formDodaj.elements.namedItem('date_to');
                const od = e.target.value;
                if (wGranicach(od, graniceDat()) && doDnia.value && doDnia.value < od) doDnia.value = od;
                ustawGraniceDat(formDodaj);   // (M8) min/max „do” za „od”
            }
        }, naSluch);
        formDodaj.addEventListener('click', (e) => {
            const b = e.target.closest('[data-lg-trasy-akcja="dodaj-anuluj"]');
            if (b && !b.disabled) zamknijOknoDodawania();
        }, naSluch);
        // Poprawka pola z błędem: błąd i oznaczenie pola znikają (oględziny M1, M15).
        formDodaj.addEventListener('input', (e) => {
            if (e.target && e.target.getAttribute && e.target.getAttribute('aria-invalid') === 'true') bladDodawania('');
        }, naSluch);
        // Esc: zamykamy sami (z oddaniem fokusu); w trakcie zapisu wcale — wynik musi trafić do listy.
        dialogDodaj.addEventListener('cancel', (e) => {
            e.preventDefault();
            if (!(dodawanie && dodawanie.zapis)) zamknijOknoDodawania();
        }, naSluch);
        dialogDodaj.addEventListener('click', (e) => {
            if (e.target === dialogDodaj && !(dodawanie && dodawanie.zapis)) zamknijOknoDodawania();
        }, naSluch);
        // Zamknięte inną drogą (np. przez przeglądarkę) — obietnica i tak musi się rozstrzygnąć,
        // a zapis w toku kończy się w tle (poZamknieciuOknaDodawania).
        dialogDodaj.addEventListener('close', poZamknieciuOknaDodawania, naSluch);
    }

    if (dialogWykonaj && formWykonaj) {
        formWykonaj.addEventListener('submit', (e) => {
            e.preventDefault();
            zatwierdzWykonanie();
        }, naSluch);
        formWykonaj.addEventListener('change', (e) => {
            // Wybór użytkownika zapamiętany — przeżyje przebudowę listy po odmowie serwera.
            const c = e.target;
            if (wykonywanie && c && c.type === 'checkbox') wykonywanie.wybory.set(Number(c.value), c.checked);
            odswiezLicznikWykonania();
        }, naSluch);
        formWykonaj.addEventListener('click', (e) => {
            const b = e.target.closest('[data-lg-trasy-akcja="wykonaj-anuluj"]');
            if (b && !b.disabled) zamknijWykonanie();
        }, naSluch);
        dialogWykonaj.addEventListener('cancel', (e) => {
            e.preventDefault();
            if (!(wykonywanie && wykonywanie.zapis)) zamknijWykonanie();
        }, naSluch);
        dialogWykonaj.addEventListener('click', (e) => {
            if (e.target === dialogWykonaj && !(wykonywanie && wykonywanie.zapis)) zamknijWykonanie();
        }, naSluch);
        // Zamknięte inną drogą: wczytywanie listy przerwane; zapis w toku kończy się sam
        // (zatwierdzWykonanie zgłasza wynik komunikatem, gdy okna już nie ma).
        dialogWykonaj.addEventListener('close', () => {
            const w = wykonywanie;
            wykonywanie = null;
            if (w && w.kontroler) w.kontroler.abort();
        }, naSluch);
    }

    document.addEventListener('logistics:widok', naZmianeWidoku, naSluch);
    document.addEventListener('logistics:trasy-zmienione', naZmianeTras, naSluch);
    document.addEventListener('logistics:flota-zmieniona', naZmianeFloty, naSluch);
    document.addEventListener('logistics:podklad', naZmianePodkladu, naSluch);
    document.addEventListener('logistics:mapa-gotowa', naGotowaMape, naSluch);
    window.addEventListener('beforeunload', przedZamknieciem, naSluch);
    if (filtrWykonanychEl) {
        filtrWykonanychEl.addEventListener('input', (e) => zdejmijOznaczenie(e.target), naSluch);
    }

    if (mapkaEl && typeof ResizeObserver === 'function') {
        obserwatorMapki = new ResizeObserver(naRozmiarMapki);
        obserwatorMapki.observe(mapkaEl);
    }

    polaczZMapa();
    renderujListe();
    renderujEdytor();
    if (!panel.hidden) pokazano();
})();
