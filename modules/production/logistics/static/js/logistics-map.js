/**
 * Logistyka — mapa zamówień na dashboardzie zakładki (etap 2).
 * modules/production/logistics/static/js/logistics-map.js
 *
 * Ładowanie: inline skrypt z tab_content.html dociąga PO KOLEI Leaflet,
 * klastry i ten plik (ruling R5 — skrypty fragmentu są odtwarzane przez
 * createElement, czyli asynchronicznie). W chwili uruchomienia DOM zakładki
 * istnieje, a window.L i L.markerClusterGroup są gotowe.
 *
 * Ponowne wykonanie (forceRefresh wstawia fragment od nowa): na starcie
 * sprzątamy po poprzedniej instancji — mapa Leaflet, obserwator rozmiaru,
 * nasłuchy na document i przycisku zakładki, zegary.
 *
 * Plik NIE zależy od logistics.js. Kontrakt:
 *   window.LogisticsMap.render(zamowienia, {dopasuj})  pinezki zamówień z `geo`
 *   window.LogisticsMap.highlight(id, {przewin})       przybliżenie + dymek (przewin: strona do mapy)
 *   window.LogisticsMap.onSelect(cb)                   cb(id | null, {zrodlo: 'mapa'|'lista'})
 *   window.LogisticsMap.onZmiana(cb)                   cb(zamowienie, rodzaj) po zapisie punktu
 *   window.LogisticsMap.ustawNaMapie(zamowienie | id)  tryb „następny klik = punkt”
 *   window.LogisticsMap.anuluj(), .zajeta(), .mapa(), .root, .zniszcz()
 * Etap 3 (widok tras, dane i przełącznik obsługuje logistics-routes.js):
 *   window.LogisticsMap.ustawWidok('zamowienia'|'trasy') zdejmuje/zakłada warstwę pinezek i tras
 *   window.LogisticsMap.renderTrasy(trasy, {blad})       aktywne trasy z GET /routes/map
 *   window.LogisticsMap.onWyborTrasy(cb)                 cb(route_id) — klik w trasę albo w legendę
 *   window.LogisticsMap.nowaWarstwaPodkladu()            L.TileLayer bieżącego podkładu (mapka edytora)
 *   window.LogisticsMap.kolorTrasy(id), .widok()         klasa koloru trasy, bieżący widok
 *   window.LogisticsMap.onBlad(cb)                       cb(tekst) — odmowa zapisu punktu, gdy pasek
 *                                                        trybu należy już do następnego zamówienia
 * Gotowość ogłasza zdarzenie `logistics:mapa-gotowa` na document (detail.root), zmianę
 * podkładu — `logistics:podklad` (detail {root, podklad}; mapka edytora trasy idzie za nią).
 *
 * Na mapie: przełącznik podkładu (miniaturki, lewy dolny róg) i „Grupuj pinezki”
 * (prawy górny róg; wyłączony = zwykła L.FeatureGroup zamiast klastrów).
 *
 * Tu żyje też PASTYLKA między listą a mapą (układ obok siebie): proporcja
 * kolumn z przeciągania / strzałek, zapamiętana w localStorage tej przeglądarki.
 *
 * API (modules/production/logistics/routers/panel_api.py):
 *   PUT  {API}/orders/<id>/geo        {lat, lng} → {success, order}
 *   POST {API}/orders/<id>/geo/reset  → {success, order}  (geo: null, wraca do automatu)
 *
 * Współrzędne liczy wyłącznie serwer (geokoder w tle) — przeglądarka niczego
 * nie geokoduje. Każdy tekst z API przechodzi przez esc() albo textContent.
 */
(function () {
    'use strict';

    if (window.LogisticsMap && typeof window.LogisticsMap.zniszcz === 'function') {
        try { window.LogisticsMap.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    const kontener = document.getElementById('logistics-map');
    if (!root || !kontener) return;

    const pasekEl = root.querySelector('[data-lg-mapa="pasek"]');
    const stanEl = root.querySelector('[data-lg-mapa="stan"]');
    const panel = root.querySelector('.lg-mapa-panel');
    const siatka = root.querySelector('.lg-uklad-siatka');
    const uchwyt = root.querySelector('[data-lg-mapa="uchwyt"]');
    const pastylka = root.querySelector('[data-lg-mapa="pastylka"]');

    if (!window.L || !window.L.markerClusterGroup) {
        if (stanEl) {
            stanEl.textContent = 'Nie udało się wczytać mapy. Lista działa bez niej.';
            stanEl.classList.add('is-blad');
        }
        return;
    }

    const L = window.L;

    // data-api = url_for('logistics_panel.orders') → baza bez końcowego /orders.
    const API = (root.getAttribute('data-api') || '/production/api/logistics/orders')
        .replace(/\/orders\/?$/, '');

    // ── Stałe ───────────────────────────────────────────────────────────────

    const POLSKA = [[49.0, 14.1], [54.9, 24.2]];

    // CARTO od 2026 wymaga klucza API dla kafelków rastrowych (bez niego znak
    // wodny „API KEY REQUIRED"). Klucz wstawia serwer jako data-atrybut na tym
    // samym elemencie (panel_api.py: tab_content() czyta config/core.json,
    // pole CARTO_BASEMAPS_KEY) — tu tylko dokładamy go do adresu kafelków CARTO.
    // Klucz i tak jest widoczny w przeglądarce (adresy kafelków) — ochronę
    // daje ograniczenie domen w panelu CARTO, nie tajność tego atrybutu.
    const KLUCZ_KAFELKOW = kontener.getAttribute('data-carto-key') || '';

    const ATRYBUCJA_OSM = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
    const ATRYBUCJA_CARTO = ATRYBUCJA_OSM +
        ' © <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';

    // Podkłady mapy — użytkownik przełącza je kontrolką na mapie (dodajKontrolkePodkladow).
    // Voyager domyślny; wybór zapamiętany per przeglądarka (KLUCZ_PODKLADU_LS).
    // `klucz: true` = kafelek CARTO (dokładamy ?key=, gdy KLUCZ_KAFELKOW niepusty).
    const PODKLADY = [
        {
            id: 'voyager', nazwa: 'Voyager', klucz: true, subdomains: 'abcd', maxZoom: 19,
            url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
            atrybucja: ATRYBUCJA_CARTO,
        },
        {
            id: 'positron', nazwa: 'Positron', klucz: true, subdomains: 'abcd', maxZoom: 19,
            url: 'https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png',
            atrybucja: ATRYBUCJA_CARTO,
        },
        {
            // Adres OSM nie używa {s} — subdomeny tylko po to, żeby opcje warstwy nigdy
            // nie były pustą listą (pusta lista + {s} w adresie = wyjątek Leafleta).
            id: 'osm', nazwa: 'OpenStreetMap', klucz: false, subdomains: 'abc', maxZoom: 19,
            url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            atrybucja: ATRYBUCJA_OSM,
        },
    ];
    const PODKLAD_DOMYSLNY = 'voyager';
    const KLUCZ_PODKLADU_LS = 'logistyka.mapa.podklad';
    const KLUCZ_GRUPOWANIA_LS = 'logistyka.mapa.grupuj';   // '0' = pinezki osobno

    // Kafelek podglądu w przycisku podkładu — okolice magazynu (Bachórz), z=9.
    const PODGLAD_LAT = 49.84;
    const PODGLAD_LNG = 22.25;
    const PODGLAD_Z = 9;

    const ZOOM_WSKAZANIA = 12;      // klik w wiersz: co najmniej takie przybliżenie…
    const ZOOM_WSKAZANIA_MAKS = 15; // …i najwyżej takie (po rozsunięciu klastra mapa stoi na 19)
    const ZOOM_KOREKTY = 15;        // „Popraw lokalizację”: widać ulice i numery
    const ZOOM_DOPASOWANIA = 12;    // dopasowanie do pinezek nie wchodzi głębiej
    // (oględziny Task 8, M10) Zapas od krawędzi przy dopasowaniu: z lewej kolumna +/−
    // i „pokaż wszystko”, u góry „Grupuj pinezki”, u dołu miniaturki podkładu i atrybucja —
    // żadna pinezka ani przystanek trasy nie ląduje pod kontrolką.
    const MARGINES_DOPASOWANIA = { paddingTopLeft: [56, 44], paddingBottomRight: [36, 64] };
    const CZAS_PROBY_DYMKU_MS = 1500; // przybliżenie + rozsunięcie klastra trwa ~0,5 s
    const PASEK_OK_MS = 5000;

    // Pastylka — te same liczby co w logistics.css (rowek 16 px, minima kolumn).
    const SZER_ROWKA = 16;
    const MAPA_MIN_PX = 300;        // mapa nie znika
    const LISTA_MIN_PX = 640;       // poniżej ~720 px tabela przewija się w bok we własnej ramce
    const KROK_PASTYLKI_PX = 24;    // strzałka w lewo/prawo
    const KLUCZ_UDZIALU = 'logistyka.mapa.udzial';

    const SPOSOBY = ['kurier_baselinker', 'transport_woodpower', 'odbior_osobisty'];
    // Te same etykiety co w logistics.js (backend podpisuje transport jako
    // „Transport WoodPower” — to tekst do Base., w zakładce mówimy po ludzku).
    const ETYKIETY = {
        brak: 'Nie ustawiono',
        kurier_baselinker: 'Kurier',
        transport_woodpower: 'Transport własny',
        odbior_osobisty: 'Odbiór osobisty',
    };

    const bezRuchu = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    const magazyn = {
        lat: parseFloat(root.getAttribute('data-magazyn-lat')),
        lng: parseFloat(root.getAttribute('data-magazyn-lng')),
        nazwa: root.getAttribute('data-magazyn-nazwa') || 'Magazyn',
    };

    // ── Stan ────────────────────────────────────────────────────────────────

    let mapa = null;                 // L.Map — powstaje, gdy kontener ma wymiary
    // Pinezki zamówień: L.MarkerClusterGroup („Grupuj pinezki” włączone, domyślnie)
    // albo zwykła L.FeatureGroup — przełącznik na mapie, wybór w localStorage.
    let pinezki = null;
    let grupowanie = true;
    let przelacznikGrupowania = null; // <input role="switch"> w kontrolce na mapie
    let warstwaEdycji = null;        // tymczasowa pinezka korekty / ustawiania
    let warstwaKafelkow = null;      // L.TileLayer aktywnego podkładu (Voyager/Positron/OSM)
    let kontrolkaAtrybucji = null;   // L.Control.Attribution — treść zależy od podkładu
    let kontrolkaPodkladowEl = null; // <div> kontrolki wyboru podkładu (przyciski z podglądem)
    let aktywnyPodklad = null;       // element z PODKLADY
    // CARTO odrzuciło klucz (np. klucz ograniczony do innej domeny): do końca tej
    // instancji mapy kafelki i podglądy CARTO idą bez klucza — znak wodny zamiast pustki.
    let kluczOdrzucony = false;
    const podgladyPodkladow = new Map(); // id podkładu → <img> podglądu w kontrolce
    // Numer ostatniego żądania otwarcia dymku (klik w wiersz, zapis punktu). Spóźnione
    // wywołania zwrotne (moveend, zoomToShowLayer) starszych żądań nic nie otwierają.
    let nrWskazania = 0;
    let oczekujaceWskazanie = null;  // nasłuch moveend ostatniego highlight()
    const znaczniki = new Map();     // id → L.Marker (tylko zamówienia z geo)
    const zamowienia = new Map();    // id → zamówienie z ostatniego render()
    let ostatnie = [];               // ostatnia lista z render() (także przed inicjalizacją)
    let czekaNaDopasowanie = false;  // render({dopasuj}) przyszedł, zanim powstała mapa
    let dopasowanoPierwszy = false;
    let wybrany = null;              // id zamówienia z otwartym dymkiem
    let zrodloOtwarcia = 'mapa';     // kto otwiera dymek: klik w pinezkę czy lista
    let tryb = null;                 // {rodzaj: 'korekta'|'ustaw', id, z, znacznik, nowy, zapisywanie, blad}
    let timerPaska = null;
    let timerWskazania = null;
    let obserwator = null;
    let zniszczona = false;
    let przeciaganie = null;         // {id: pointerId, chwyt: px od prawej krawędzi siatki}
    let klatkaPastylki = 0;          // requestAnimationFrame odświeżenia mapy przy przeciąganiu
    const sluchaczeWyboru = [];
    const sluchaczeZmian = [];
    const sluchaczeBledow = [];      // onBlad (etap 3): odmowy zapisu punktu spoza bieżącego trybu
    const przyciskZakladki = document.getElementById('logistics-tab');
    // (oględziny Task 8, I2) Mapa schowana (podzakładka, inna zakładka panelu) ma rozmiar 0.
    // Po powrocie dopasowuje się do treści widoku od nowa — chyba że użytkownik ją przesunął
    // albo przybliżył od ostatniego dopasowania (widokRuszony).
    let mapaUkryta = false;
    let widokRuszony = false;
    let dopasowanieWToku = false;    // movestart dopasowania to nie ruch użytkownika
    // Proporcja listy i mapy zmieniona z klawiatury albo dwuklikiem pastylki — do najbliższej
    // klatki zmiana rozmiaru mapy idzie ścieżką pastylki (lewy górny róg, jak w etapie 2).
    let pastylkaZmienia = false;

    // ── Stan widoku „Trasy” (etap 3) ──
    // Kolory tras: paleta w logistics-trasy.css (--lg-trasa-0…11 i klasy lg-trasa-kolor-N).
    // Kolor wynika z id trasy, nie z miejsca na liście — zniknięcie innej trasy go nie zmienia.
    // (oględziny Task 8, M7/m5) 12 barw: 6 rodzin odcieni × jasna/ciemna, ułożonych tak, że
    // trasy o bliskich id (6 kolejnych) mają wyraźnie różne kolory — i żaden nie przypomina
    // pinezek sposobu dostawy (szary, niebieski, zielony, fioletowy).
    const LICZBA_KOLOROW_TRAS = 12;
    let widok = 'zamowienia';        // 'zamowienia' | 'trasy' — który zestaw warstw leży na mapie
    let warstwaTras = null;          // L.LayerGroup: przebiegi i przystanki aktywnych tras
    let trasyDane = null;            // ostatnia lista z renderTrasy() (null = jeszcze nie przyszła)
    let bladTras = null;             // tekst błędu pobrania tras (renderTrasy(…, {blad}))
    let dopasowanoTrasy = false;     // pierwsze trasy na mapie dopasowują widok, kolejne już nie
    let dopasujPoPowrocie = false;   // render({dopasuj}) w widoku tras — dopasujemy po powrocie
    let przyciskDopasowania = null;  // <a> kontrolki „pokaż wszystko” (tytuł zależy od widoku)
    const grupyTras = new Map();     // id trasy → L.FeatureGroup (linie i przystanki tej trasy)
    let wyroznionaTrasa = null;      // id trasy wyróżnionej najechaniem (mapa albo legenda)
    const sluchaczeWyboruTrasy = [];
    // Warstwy kafelków z kluczem CARTO spoza tej mapy (mapka edytora trasy): po odrzuceniu
    // klucza przechodzą na adresy bez klucza razem z mapą Dashboardu.
    const warstwyZewnetrzne = new Set();
    const legendaZamowien = root.querySelector('[data-lg-mapa="legenda"]');
    const legendaTras = root.querySelector('[data-lg-mapa="legenda-trasy"]');

    // ── Pomocnicze ──────────────────────────────────────────────────────────

    function esc(wartosc) {
        if (wartosc === null || wartosc === undefined) return '';
        return String(wartosc).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    const kluczSposobu = (sposob) => (SPOSOBY.includes(sposob) ? sposob : 'brak');
    const maGeo = (z) => !!(z && z.geo && isFinite(z.geo.lat) && isFinite(z.geo.lng));

    // 'YYYY-MM-DD' → '25.09' (rok dopisany, gdy inny niż bieżący) — jak na liście.
    function dataKrotka(iso) {
        if (!iso) return '';
        const [r, m, d] = iso.slice(0, 10).split('-');
        if (!d) return iso;
        return d + '.' + m + (r !== String(new Date().getFullYear()) ? '.' + r : '');
    }

    function dniPoTerminie(iso) {
        const [r, m, d] = iso.split('-').map(Number);
        const dzis = new Date();
        return Math.round((Date.UTC(dzis.getFullYear(), dzis.getMonth(), dzis.getDate()) - Date.UTC(r, m - 1, d)) / 86400000);
    }

    function adresTekst(z) {
        const miejscowosc = [z.kod, z.miasto].filter(Boolean).join(' ');
        return [z.adres, miejscowosc].filter(Boolean).join(', ');
    }

    function komunikatBledu(status, dane) {
        if (status === 401) return 'Sesja wygasła. Zaloguj się ponownie.';
        if (status === 403) return 'Brak dostępu do modułu produkcji.';
        if (dane && typeof dane.error === 'string' && dane.error) return dane.error;
        if (status >= 500) return 'Błąd serwera (HTTP ' + status + ').';
        return 'Nieoczekiwana odpowiedź serwera (HTTP ' + status + ').';
    }

    async function wyslij(sciezka, ustawienia) {
        const naglowki = { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' };
        if (ustawienia.body !== undefined) naglowki['Content-Type'] = 'application/json';
        let odp;
        try {
            odp = await fetch(API + sciezka, Object.assign({ credentials: 'same-origin', headers: naglowki }, ustawienia));
        } catch (e) {
            throw new Error('Brak połączenia z serwerem.');
        }
        let dane = null;
        try { dane = await odp.json(); } catch (e) { dane = null; }
        if (!odp.ok || !dane || dane.success === false) throw new Error(komunikatBledu(odp.status, dane));
        return dane;
    }

    // ── Ikony ───────────────────────────────────────────────────────────────

    /** Pinezka zamówienia: kolor = sposób dostawy, przerywana obwódka = przybliżona. */
    function ikonaZamowienia(z, opcje) {
        const o = opcje || {};
        const klasy = ['lg-pin', 'lg-pin--mapa', 'lg-pin--' + kluczSposobu(z.sposob)];
        if (z.geo && z.geo.quality === 'przyblizona') klasy.push('lg-pin--przyblizona');
        if (o.wybrana) klasy.push('is-wybrana');
        if (o.edycja) klasy.push('is-edytowana');
        const znak = z.geo && z.geo.adres_zmieniony
            ? '<span class="lg-pin-znak" aria-hidden="true">!</span>' : '';
        return L.divIcon({
            className: 'lg-znacznik',
            html: '<span class="' + klasy.join(' ') + '"></span>' + znak,
            // Czubek kropli (obrócony o -45° kwadrat 20 px) wypada w (12, 30).
            iconSize: [24, 30],
            iconAnchor: [12, 30],
            popupAnchor: [0, -28],
            tooltipAnchor: [0, -28],
        });
    }

    /**
     * Klaster: neutralne białe koło z liczbą; cienki pierścień pokazuje proporcje
     * sposobów dostawy w środku (szary / niebieski / zielony / fioletowy).
     */
    function ikonaKlastra(klaster) {
        const dzieci = klaster.getAllChildMarkers();
        const ile = dzieci.length;
        const liczby = { brak: 0, kurier_baselinker: 0, transport_woodpower: 0, odbior_osobisty: 0 };
        dzieci.forEach((m) => { liczby[m.options.lgSposob || 'brak'] += 1; });
        let od = 0;
        const odcinki = [];
        ['brak'].concat(SPOSOBY).forEach((k) => {
            if (!liczby[k]) return;
            const do_ = od + (liczby[k] / ile) * 100;
            odcinki.push('var(--lg-sposob-' + k + ') ' + od.toFixed(2) + '% ' + do_.toFixed(2) + '%');
            od = do_;
        });
        const rozmiar = ile < 10 ? 34 : (ile < 50 ? 40 : 46);
        const opis = ile + ' zamówień w tym miejscu. Kliknij, żeby przybliżyć.';
        return L.divIcon({
            className: 'lg-znacznik-klaster',
            html: '<div class="lg-klaster" style="--lg-klaster-pierscien: conic-gradient(' + odcinki.join(', ') + ')"' +
                ' title="' + esc(opis) + '"><span>' + ile + '</span></div>',
            iconSize: [rozmiar, rozmiar],
        });
    }

    // ── Treść dymków ────────────────────────────────────────────────────────

    function podpowiedzHtml(z) {
        let html = '<b>' + esc(z.numer) + '</b>' + (z.klient ? ' ' + esc(z.klient) : '');
        if (z.geo && z.geo.quality === 'przyblizona') {
            html += '<span class="lg-podpowiedz-mapy-uwaga">Lokalizacja przybliżona (miejscowość)</span>';
        }
        return html;
    }

    function terminHtml(iso) {
        if (!iso) return '<span class="lg-brak-danych">brak</span>';
        const dni = dniPoTerminie(iso);
        let klasa = 'lg-termin';
        if (dni > 0) klasa += ' is-po-terminie';
        else if (dni === 0) klasa += ' is-dzis';
        return '<time class="' + klasa + '" datetime="' + esc(iso) + '">' + esc(dataKrotka(iso)) +
            (dni > 0 ? ' <span class="lg-dymek-po">po terminie</span>' : '') + '</time>';
    }

    function dymekHtml(z) {
        if (!z) return '';
        const sposob = kluczSposobu(z.sposob);
        const etap = z.etap || { status: '', nazwa: '' };
        const geo = z.geo || {};
        // Adres jak w kolumnie „Adres” listy: kod + miejscowość, pod spodem ulica z numerami.
        const miejscowosc = [z.kod, z.miasto].filter(Boolean).join(' ');
        const adres = (miejscowosc ? '<span class="lg-dymek-miejscowosc">' + esc(miejscowosc) + '</span>' : '') +
            (z.adres ? '<span class="lg-dymek-ulica">' + esc(z.adres) + '</span>' : '');

        const uwagi = [];
        if (geo.adres_zmieniony) {
            uwagi.push('<p class="lg-dymek-uwaga lg-dymek-uwaga--adres"><i class="fas fa-map-location-dot" aria-hidden="true"></i>' +
                'Adres w Base. zmienił się po ręcznym ustawieniu punktu. Sprawdź, czy punkt jest aktualny.</p>');
        }
        if (geo.quality === 'przyblizona') {
            uwagi.push('<p class="lg-dymek-uwaga"><span class="lg-pin lg-pin--' + sposob + ' lg-pin--przyblizona" aria-hidden="true"></span>' +
                'Lokalizacja przybliżona (miejscowość)</p>');
        } else if (geo.source === 'reczna') {
            uwagi.push('<p class="lg-dymek-uwaga"><i class="fas fa-hand-pointer" aria-hidden="true"></i>Punkt ustawiony ręcznie</p>');
        }

        const akcje = ['<button type="button" class="lg-przycisk" data-lg-mapa-akcja="popraw" data-id="' + esc(z.id) + '">' +
            '<i class="fas fa-up-down-left-right" aria-hidden="true"></i>Popraw lokalizację</button>'];
        if (geo.adres_zmieniony) {
            akcje.push('<button type="button" class="lg-przycisk" data-lg-mapa-akcja="potwierdz" data-id="' + esc(z.id) + '">' +
                '<i class="fas fa-check" aria-hidden="true"></i>Potwierdź punkt</button>');
        }
        if (geo.source === 'reczna') {
            akcje.push('<button type="button" class="lg-przycisk lg-przycisk--cichy" data-lg-mapa-akcja="przywroc" data-id="' + esc(z.id) + '">' +
                '<i class="fas fa-rotate-left" aria-hidden="true"></i>Przywróć automat</button>');
        }

        return '<div class="lg-dymek-tresc">' +
            '<div class="lg-dymek-gora">' +
                '<span class="lg-dymek-numer">' + esc(z.numer) + '</span>' +
                '<span class="lg-dymek-sposob"><span class="lg-pin lg-pin--' + sposob + '" aria-hidden="true"></span>' +
                    esc(ETYKIETY[sposob]) + '</span>' +
            '</div>' +
            '<div class="lg-dymek-klient">' + (z.klient ? esc(z.klient) : '<span class="lg-brak-danych">brak nazwy</span>') + '</div>' +
            (adres ? '<div class="lg-dymek-adres">' + adres + '</div>' : '') +
            '<dl class="lg-dymek-dane">' +
                '<div><dt>Etap</dt><dd><span class="lg-etap" data-etap="' + esc(etap.status) + '">' +
                    (etap.status === 'spakowane'
                        ? '<i class="fas fa-check lg-etap-znak" aria-hidden="true"></i>'
                        : '<span class="lg-etap-znak" aria-hidden="true"></span>') +
                    '<span class="lg-etap-nazwa">' + esc(etap.nazwa || etap.status) + '</span></span></dd></div>' +
                '<div><dt>Termin</dt><dd>' + terminHtml(z.termin) + '</dd></div>' +
            '</dl>' +
            uwagi.join('') +
            '<div class="lg-dymek-akcje">' + akcje.join('') + '</div>' +
            '</div>';
    }

    // ── Pasek mapy (tryb pracy i wynik akcji) ───────────────────────────────

    /**
     * typ: tryb | ok | blad | info. Treść przez textContent. przyciski:
     * [{etykieta, akcja, glowny, ikona}] — akcje obsługuje klikPaska().
     * ok/info znikają same, tryb i błąd zostają.
     */
    function pokazPasek(typ, tresc, przyciski, opcje) {
        if (!pasekEl) return;
        const o = opcje || {};
        clearTimeout(timerPaska);
        pasekEl.innerHTML = '';
        pasekEl.className = 'lg-mapa-pasek lg-mapa-pasek--' + typ;

        const ikony = { tryb: 'fa-location-crosshairs', ok: 'fa-circle-check', blad: 'fa-circle-exclamation', info: 'fa-circle-info' };
        const ik = document.createElement('i');
        ik.className = 'fas ' + (o.ikona || ikony[typ] || ikony.info);
        ik.setAttribute('aria-hidden', 'true');
        pasekEl.appendChild(ik);

        const tekst = document.createElement('span');
        tekst.className = 'lg-mapa-pasek-tekst';
        tekst.textContent = tresc;
        if (o.podpis) {
            const podpis = document.createElement('span');
            podpis.className = 'lg-mapa-pasek-podpis';
            podpis.textContent = o.podpis;
            tekst.appendChild(podpis);
        }
        pasekEl.appendChild(tekst);

        if (przyciski && przyciski.length) {
            const grupa = document.createElement('span');
            grupa.className = 'lg-mapa-pasek-przyciski';
            przyciski.forEach((p) => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'lg-mapa-pasek-przycisk' + (p.glowny ? ' is-glowny' : '');
                b.setAttribute('data-lg-mapa-akcja', p.akcja);
                if (p.wylaczony) b.disabled = true;
                b.textContent = p.etykieta;
                grupa.appendChild(b);
            });
            pasekEl.appendChild(grupa);
        }
        pasekEl.hidden = false;
        if (typ === 'ok' || typ === 'info') {
            timerPaska = setTimeout(() => { if (!tryb) ukryjPasek(); }, PASEK_OK_MS);
        }
    }

    function ukryjPasek() {
        clearTimeout(timerPaska);
        if (!pasekEl) return;
        pasekEl.hidden = true;
        pasekEl.innerHTML = '';
    }

    function pasekTrybu() {
        if (!tryb) return;
        const numer = tryb.z.numer;
        const blad = tryb.blad ? { podpis: 'Nie zapisano: ' + tryb.blad } : {};
        if (tryb.zapisywanie) {
            pokazPasek('tryb', 'Zapisywanie punktu zamówienia ' + numer + '…',
                [{ etykieta: 'Anuluj', akcja: 'anuluj', wylaczony: true }],
                { ikona: bezRuchu ? 'fa-hourglass-half' : 'fa-spinner fa-spin' });
            return;
        }
        if (tryb.rodzaj === 'ustaw') {
            const adres = adresTekst(tryb.z);
            pokazPasek('tryb', 'Kliknij na mapie miejsce dostawy zamówienia ' + numer + '.',
                [{ etykieta: 'Anuluj (Esc)', akcja: 'anuluj' }],
                Object.assign({ podpis: adres ? 'Adres: ' + adres : 'Brak adresu w zamówieniu.' }, blad));
            return;
        }
        if (!tryb.nowy) {
            pokazPasek('tryb', 'Przeciągnij pinezkę zamówienia ' + numer + ' w miejsce dostawy albo kliknij to miejsce na mapie.',
                [{ etykieta: 'Anuluj (Esc)', akcja: 'anuluj' }], Object.assign({ ikona: 'fa-up-down-left-right' }, blad));
            return;
        }
        pokazPasek('tryb', 'Zapisać nowe miejsce dostawy zamówienia ' + numer + '?',
            [{ etykieta: 'Zapisz', akcja: 'zapisz', glowny: true }, { etykieta: 'Anuluj', akcja: 'anuluj' }],
            Object.assign({ ikona: 'fa-up-down-left-right' }, blad));
    }

    function klikPaska(e) {
        const b = e.target.closest('[data-lg-mapa-akcja]');
        if (!b || b.disabled) return;
        const akcja = b.getAttribute('data-lg-mapa-akcja');
        if (akcja === 'anuluj') anulujTryb();
        else if (akcja === 'zapisz') zapiszKorekte();
        else if (akcja === 'zamknij-pasek') ukryjPasek();
    }

    // ── Stan mapy (ładowanie, brak pinezek) ─────────────────────────────────

    function pokazStanMapy(tresc, klasa) {
        if (!stanEl) return;
        stanEl.className = 'lg-mapa-stan' + (klasa ? ' ' + klasa : '');
        stanEl.textContent = tresc;
        stanEl.hidden = false;
    }

    function ukryjStanMapy() {
        if (stanEl) stanEl.hidden = true;
    }

    function odswiezStanMapy() {
        if (!mapa) return;
        if (widok === 'trasy') {
            stanMapyTras();
            return;
        }
        const zGeo = ostatnie.filter(maGeo).length;
        if (ostatnie.length && !zGeo) {
            pokazStanMapy(ostatnie.length === 1
                ? 'To zamówienie nie ma jeszcze punktu na mapie. Ustaw go przyciskiem „Ustaw na mapie” przy numerze.'
                : 'Zamówienia z listy nie mają jeszcze punktów na mapie. Ustawisz je przyciskiem „Ustaw na mapie” przy numerze.');
        } else {
            ukryjStanMapy();
        }
    }

    // ── Podkład mapy (Voyager / Positron / OpenStreetMap) ───────────────────

    // localStorage bywa niedostępny (tryb prywatny) — wtedy Voyager, bez błędów.
    function czytajPodklad() {
        try {
            const v = window.localStorage.getItem(KLUCZ_PODKLADU_LS);
            return PODKLADY.some((p) => p.id === v) ? v : PODKLAD_DOMYSLNY;
        } catch (e) {
            return PODKLAD_DOMYSLNY;
        }
    }

    function zapiszPodklad(id) {
        try { window.localStorage.setItem(KLUCZ_PODKLADU_LS, id); } catch (e) { /* wybór nie przeżyje przeładowania */ }
    }

    const zKluczem = (podklad) => !!(podklad.klucz && KLUCZ_KAFELKOW && !kluczOdrzucony);

    // Szablon adresu kafelków Leafleta ({s}/{z}/{x}/{y}{r}) — klucz CARTO tylko
    // dla podkładów CARTO, gdy KLUCZ_KAFELKOW jest niepusty i CARTO go nie odrzuciło.
    function szablonKafelkow(podklad, bezKlucza) {
        return podklad.url + (zKluczem(podklad) && !bezKlucza ? '?key=' + encodeURIComponent(KLUCZ_KAFELKOW) : '');
    }

    /**
     * Warstwa kafelków podkładu z JEGO opcjami (subdomeny, zoom). Kafelki CARTO
     * z kluczem pilnują odrzucenia klucza: błąd kafelka, zanim którykolwiek
     * załadował się z kluczem = klucz nie działa (403 dla obcej domeny,
     * cofnięty klucz) → raz na instancję mapy przechodzimy na adresy bez klucza.
     * Pojedynczy błąd sieci po udanych kafelkach niczego nie przełącza.
     *
     * zewnetrzna (etap 3): warstwa dla innej mapy (mapka edytora trasy, patrz
     * nowaWarstwaPodkladu) — pilnuje odrzucenia klucza sama, a po nim wszystkie
     * warstwy z kluczem (tej mapy i zewnętrzne) przechodzą na adresy bez klucza naraz.
     */
    function nowaWarstwaKafelkow(podklad, zewnetrzna) {
        const warstwa = L.tileLayer(szablonKafelkow(podklad), {
            subdomains: podklad.subdomains,
            maxZoom: podklad.maxZoom,
        });
        if (zKluczem(podklad)) {
            let udane = 0;
            warstwa.on('tileload', () => { udane += 1; });
            warstwa.on('tileerror', () => {
                if (udane || kluczOdrzucony || (!zewnetrzna && warstwa !== warstwaKafelkow)) return;
                kluczOdrzucony = true;
                console.warn('[LogisticsMap] CARTO odrzuciło klucz kafelków (np. klucz ograniczony do innej domeny). ' +
                    'Mapa pokazuje kafelki CARTO bez klucza, ze znakiem wodnym.');
                // Po bieżącym zdarzeniu — redraw w środku obsługi błędu kafelka
                // mieszałby Leafletowi stan kafelków tej samej warstwy.
                setTimeout(() => {
                    if (zniszczona) return;
                    // Aktywny podkład tej mapy (ten sam podkład, te same subdomeny) i mapki tras.
                    if (mapa && warstwaKafelkow && aktywnyPodklad) warstwaKafelkow.setUrl(szablonKafelkow(aktywnyPodklad));
                    warstwyZewnetrzne.forEach((w) => w.warstwa.setUrl(szablonKafelkow(w.podklad)));
                    podgladyPodkladow.forEach((img, id) => {
                        const p = PODKLADY.find((x) => x.id === id);
                        if (p && p.klucz) img.src = adresPodgladu(p, true);
                    });
                }, 0);
            });
            if (zewnetrzna) {
                const wpis = { warstwa: warstwa, podklad: podklad };
                warstwyZewnetrzne.add(wpis);
                // Zniszczenie mapki (mapka.remove()) zdejmuje warstwę — koniec pilnowania.
                warstwa.on('remove', () => warstwyZewnetrzne.delete(wpis));
            }
        }
        return warstwa;
    }

    // z/x/y kafelka slippy map dla współrzędnych — do podglądu w przycisku.
    function wspolrzedneKafelka(lat, lng, z) {
        const n = Math.pow(2, z);
        const latRad = lat * Math.PI / 180;
        return {
            x: Math.floor((lng + 180) / 360 * n),
            y: Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n),
        };
    }

    // Konkretny adres kafelka (bez placeholderów) w okolicy magazynu — podgląd stylu w przycisku.
    function adresPodgladu(podklad, bezKlucza) {
        const wsp = wspolrzedneKafelka(PODGLAD_LAT, PODGLAD_LNG, PODGLAD_Z);
        return szablonKafelkow(podklad, bezKlucza)
            .replace('{s}', (podklad.subdomains || 'a').charAt(0) || 'a')
            .replace('{z}', PODGLAD_Z).replace('{x}', wsp.x).replace('{y}', wsp.y)
            .replace('{r}', '');
    }

    /**
     * Podmienia aktywny podkład bez przebudowy mapy — pinezki, klastry, widok
     * i tryby nietknięte. Cała nowa warstwa, nie setUrl: setUrl zostawiał opcje
     * poprzedniego podkładu (po OSM puste subdomeny → adres CARTO z {s} rzucał
     * wyjątek i mapa zostawała bez kafelków). Kafelki leżą w tilePane, pinezki
     * i klastry w markerPane — zostają nad nimi. Wybór zapisujemy dopiero po
     * udanym przełączeniu.
     */
    function przelaczPodklad(id) {
        if (!mapa || zniszczona) return;
        const podklad = PODKLADY.find((p) => p.id === id);
        if (!podklad || podklad === aktywnyPodklad) return;
        const stara = warstwaKafelkow;
        const nowa = nowaWarstwaKafelkow(podklad);
        try {
            nowa.addTo(mapa);
        } catch (e) {
            try { mapa.removeLayer(nowa); } catch (err) { /* nie zdążyła się dodać */ }
            console.error('[LogisticsMap] Nie przełączono podkładu:', e);
            return;
        }
        warstwaKafelkow = nowa;
        if (stara) mapa.removeLayer(stara);
        if (kontrolkaAtrybucji) {
            kontrolkaAtrybucji.removeAttribution(aktywnyPodklad.atrybucja);
            kontrolkaAtrybucji.addAttribution(podklad.atrybucja);
        }
        aktywnyPodklad = podklad;
        zapiszPodklad(id);
        zaznaczAktywnyPodklad();
        // (oględziny Task 8, M6) Mapka otwartego edytora trasy przechodzi na ten sam podkład.
        document.dispatchEvent(new CustomEvent('logistics:podklad', { detail: { root: root, podklad: id } }));
    }

    function zaznaczAktywnyPodklad() {
        if (!kontrolkaPodkladowEl) return;
        kontrolkaPodkladowEl.querySelectorAll('[data-podklad]').forEach((b) => {
            const aktywny = b.getAttribute('data-podklad') === aktywnyPodklad.id;
            b.setAttribute('aria-pressed', aktywny ? 'true' : 'false');
            b.classList.toggle('is-aktywny', aktywny);
        });
    }

    /**
     * Kontrolka Leafleta: rząd samych miniaturek (podgląd stylu), bez podpisów —
     * nazwa w title i aria-label. Kompaktowa, żeby w wąskiej (300 px) i niskiej
     * mapie nie zasłaniała pinezek ani atrybucji.
     */
    function dodajKontrolkePodkladow() {
        const Kontrolka = L.Control.extend({
            options: { position: 'bottomleft' },
            onAdd: function () {
                const div = L.DomUtil.create('div', 'lg-mapa-podklady');
                div.setAttribute('role', 'group');
                div.setAttribute('aria-label', 'Podkład mapy');
                PODKLADY.forEach((podklad) => {
                    const b = L.DomUtil.create('button', 'lg-mapa-podklad', div);
                    b.type = 'button';
                    b.setAttribute('data-podklad', podklad.id);
                    b.title = 'Podkład mapy: ' + podklad.nazwa;
                    b.setAttribute('aria-label', 'Podkład mapy: ' + podklad.nazwa);
                    const podglad = L.DomUtil.create('span', 'lg-mapa-podklad-podglad', b);
                    podglad.setAttribute('aria-hidden', 'true');
                    const img = L.DomUtil.create('img', '', podglad);
                    // Podgląd CARTO z kluczem, którego CARTO nie przyjmuje: raz ten sam
                    // kafelek bez klucza (znak wodny zamiast zepsutego obrazka), bez pętli.
                    if (zKluczem(podklad)) {
                        const naBlad = () => {
                            img.removeEventListener('error', naBlad);
                            const bez = adresPodgladu(podklad, true);
                            if (img.src !== bez) img.src = bez;
                        };
                        img.addEventListener('error', naBlad);
                    }
                    img.src = adresPodgladu(podklad);
                    podgladyPodkladow.set(podklad.id, img);
                    img.alt = '';
                    img.width = 56;
                    img.height = 56;
                    img.loading = 'lazy';
                    img.decoding = 'async';
                    L.DomEvent.on(b, 'click', (e) => {
                        L.DomEvent.preventDefault(e);
                        przelaczPodklad(podklad.id);
                    });
                });
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                kontrolkaPodkladowEl = div;
                zaznaczAktywnyPodklad();
                return div;
            },
        });
        new Kontrolka().addTo(mapa);
    }

    // ── Grupowanie pinezek (klastry albo każda pinezka osobno) ──────────────

    // Domyślnie włączone; localStorage bywa niedostępny — wtedy też włączone.
    function czytajGrupowanie() {
        try {
            return window.localStorage.getItem(KLUCZ_GRUPOWANIA_LS) !== '0';
        } catch (e) {
            return true;
        }
    }

    function zapiszGrupowanie(wlaczone) {
        try { window.localStorage.setItem(KLUCZ_GRUPOWANIA_LS, wlaczone ? '1' : '0'); } catch (e) { /* wybór nie przeżyje przeładowania */ }
    }

    function nowaWarstwaPinezek() {
        if (!grupowanie) return L.featureGroup();
        return L.markerClusterGroup({
            showCoverageOnHover: false,
            maxClusterRadius: 44,
            spiderfyOnMaxZoom: true,
            animate: !bezRuchu,
            iconCreateFunction: ikonaKlastra,
        });
    }

    // L.FeatureGroup nie ma addLayers/removeLayers (hurtowych metod klastrów).
    function dodajPinezki(lista) {
        if (!lista.length) return;
        if (pinezki.addLayers) pinezki.addLayers(lista);
        else lista.forEach((m) => pinezki.addLayer(m));
    }

    function usunPinezki(lista) {
        if (!lista.length) return;
        if (pinezki.removeLayers) pinezki.removeLayers(lista);
        else lista.forEach((m) => pinezki.removeLayer(m));
    }

    /**
     * Przenosi te same obiekty pinezek do warstwy drugiego rodzaju — bez
     * odtwarzania mapy i bez zmiany widoku. Pinezka w trakcie korekty (poza
     * warstwą) zostaje poza nią; otwarty dymek otwiera się ponownie.
     */
    function ustawGrupowanie(wlaczone) {
        if (!mapa || zniszczona || wlaczone === grupowanie) return;
        const m = wybrany !== null ? znaczniki.get(wybrany) : null;
        const otwarty = m && m.isPopupOpen() ? wybrany : null;
        const pominiety = tryb && tryb.rodzaj === 'korekta' ? tryb.oryginal : null;
        anulujWskazanie();
        const stara = pinezki;
        mapa.removeLayer(stara);
        stara.clearLayers();
        grupowanie = wlaczone;
        pinezki = nowaWarstwaPinezek();
        // Widok tras: nowa warstwa czeka poza mapą (grupowanie dotyczy tylko zamówień).
        if (widok === 'zamowienia') mapa.addLayer(pinezki);
        const wszystkie = [];
        znaczniki.forEach((z) => { if (z !== pominiety) wszystkie.push(z); });
        dodajPinezki(wszystkie);
        zapiszGrupowanie(wlaczone);
        if (przelacznikGrupowania) przelacznikGrupowania.checked = wlaczone;
        if (otwarty !== null) otworzDymek(otwarty, 'lista');
    }

    /** Kontrolka Leafleta w prawym górnym rogu: przełącznik „Grupuj pinezki”. */
    function dodajPrzelacznikGrupowania() {
        const Kontrolka = L.Control.extend({
            options: { position: 'topright' },
            onAdd: function () {
                const pole = L.DomUtil.create('label', 'lg-mapa-grupuj');
                pole.title = 'Łącz pobliskie pinezki w koła z liczbą zamówień';
                const input = L.DomUtil.create('input', '', pole);
                input.type = 'checkbox';
                input.setAttribute('role', 'switch');
                input.checked = grupowanie;
                const tekst = L.DomUtil.create('span', '', pole);
                tekst.textContent = 'Grupuj pinezki';
                L.DomEvent.on(input, 'change', () => ustawGrupowanie(input.checked));
                L.DomEvent.disableClickPropagation(pole);
                L.DomEvent.disableScrollPropagation(pole);
                przelacznikGrupowania = input;
                return pole;
            },
        });
        new Kontrolka().addTo(mapa);
    }

    // ── Inicjalizacja (dopiero gdy kontener jest widoczny) ─────────────────

    function maWymiary() {
        return kontener.isConnected && kontener.clientWidth > 0 && kontener.clientHeight > 0;
    }

    // (oględziny Task 8, M9) Najszerszy dymek trasy / przystanku = pół mapy bez marginesu:
    // dymek z kierunkiem 'auto' (w stronę środka mapy) zawsze mieści się w jej granicach.
    function ustawSzerokoscDymkow() {
        if (!kontener.clientWidth) return;
        kontener.style.setProperty('--lg-dymek-maks', Math.max(140, Math.round(kontener.clientWidth / 2 - 28)) + 'px');
    }

    function zainicjuj() {
        if (mapa || zniszczona || !maWymiary()) return;

        mapa = L.map(kontener, {
            attributionControl: false,
            // (oględziny Task 8, M13) Własna kontrolka zoomu — z polskimi podpisami (niżej).
            zoomControl: false,
            // (oględziny Task 8, I2) Rozmiar pilnuje ResizeObserver (poZmianieRozmiaru). Nasłuch
            // okna Leafleta przesuwał SCHOWANĄ mapę (rozmiar 0) przy każdej zmianie szerokości
            // okna i po powrocie na Dashboard pinezki i trasy były poza kadrem.
            trackResize: false,
            minZoom: 5,
            maxZoom: 19,
            zoomAnimation: !bezRuchu,
            fadeAnimation: !bezRuchu,
            markerZoomAnimation: !bezRuchu,
        });
        // Pierwsza w lewym górnym rogu — nad „pokaż wszystko”, jak domyślna kontrolka.
        L.control.zoom({ zoomInTitle: 'Przybliż', zoomOutTitle: 'Oddal' }).addTo(mapa);
        // Ruch mapy, który nie jest naszym dopasowaniem = użytkownik przesunął / przybliżył
        // (także wskazanie zamówienia z listy albo korekta punktu — też „oglądam co innego”).
        mapa.on('movestart', () => { if (!dopasowanieWToku) widokRuszony = true; });
        mapa.on('dragstart', () => { widokRuszony = true; });
        mapa.on('moveend', () => { dopasowanieWToku = false; });
        aktywnyPodklad = PODKLADY.find((p) => p.id === czytajPodklad()) || PODKLADY[0];
        kontrolkaAtrybucji = L.control.attribution({ prefix: false }).addTo(mapa);
        kontrolkaAtrybucji.addAttribution(aktywnyPodklad.atrybucja);
        warstwaKafelkow = nowaWarstwaKafelkow(aktywnyPodklad).addTo(mapa);
        dopasujGranice(POLSKA, { padding: [8, 8] });
        ustawSzerokoscDymkow();

        grupowanie = czytajGrupowanie();
        pinezki = nowaWarstwaPinezek();
        // Etap 3: na mapie leży warstwa bieżącego widoku — pinezki albo trasy.
        warstwaTras = L.layerGroup();
        mapa.addLayer(widok === 'trasy' ? warstwaTras : pinezki);
        warstwaEdycji = L.layerGroup().addTo(mapa);

        dodajMagazyn();
        dodajKontrolkeDopasowania();
        dodajKontrolkePodkladow();
        dodajPrzelacznikGrupowania();
        mapa.on('click', klikMapy);

        ukryjStanMapy();
        narysuj(ostatnie);
        narysujTrasy();
        const dopasujPinezki = czekaNaDopasowanie || (!dopasowanoPierwszy && znaczniki.size);
        if (widok === 'trasy') {
            if (dopasujPinezki) dopasujPoPowrocie = true;
            if (trasyDane && trasyDane.length) {
                dopasujTrasy();
                dopasowanoTrasy = true;
            }
        } else if (dopasujPinezki) {
            dopasuj();
            dopasowanoPierwszy = true;
        }
        czekaNaDopasowanie = false;
        odswiezStanMapy();
    }

    function dodajMagazyn() {
        if (!isFinite(magazyn.lat) || !isFinite(magazyn.lng)) return;
        const m = L.marker([magazyn.lat, magazyn.lng], {
            // Kwadrat na cienkim maszcie NAD punktem (dół masztu = magazyn):
            // klaster zamówień z okolicy, wyśrodkowany obok, zostaje widoczny
            // pod spodem razem z liczbą.
            icon: L.divIcon({
                className: 'lg-znacznik-magazyn',
                html: '<span class="lg-magazyn lg-magazyn--mapa"><i class="fas fa-industry" aria-hidden="true"></i></span>',
                iconSize: [24, 36],
                iconAnchor: [12, 36],
                tooltipAnchor: [0, -36],
            }),
            // Nad klastrami i pinezkami — punkt odniesienia ma być zawsze widać.
            zIndexOffset: 1000,
            keyboard: false,
            alt: 'Magazyn',
        }).addTo(mapa);
        m.bindTooltip(esc(magazyn.nazwa), { direction: 'top', className: 'lg-podpowiedz-mapy', opacity: 1 });
    }

    function dodajKontrolkeDopasowania() {
        const Kontrolka = L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function () {
                const div = L.DomUtil.create('div', 'leaflet-bar lg-mapa-kontrolka');
                const a = L.DomUtil.create('a', '', div);
                a.href = '#';
                a.setAttribute('role', 'button');
                a.innerHTML = '<i class="fas fa-expand" aria-hidden="true"></i>';
                przyciskDopasowania = a;
                opiszPrzyciskDopasowania();
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.on(a, 'click', (e) => {
                    L.DomEvent.preventDefault(e);
                    // Etap 3: w widoku tras „pokaż wszystko” obejmuje trasy, nie ukryte pinezki.
                    dopasujBiezacy();
                });
                return div;
            },
        });
        new Kontrolka().addTo(mapa);
    }

    /**
     * Każde dopasowanie widoku przechodzi tędy: świeży rozmiar kontenera (klik „pokaż
     * wszystko” zaraz po powrocie z ukrycia liczył ze starego), a „widok ruszony” zeruje się —
     * od teraz liczy się ruch użytkownika od TEGO dopasowania (oględziny Task 8, I2).
     */
    function dopasujGranice(granice, opcje) {
        if (!mapa) return;
        if (maWymiary()) mapa.invalidateSize({ pan: false });
        widokRuszony = false;
        dopasowanieWToku = true;
        mapa.fitBounds(granice, opcje);
        // Bez animacji mapa już stoi (moveend przyszedł w środku fitBounds); z animacją flaga
        // zejdzie na moveend — ruch w trakcie animacji to nie ruch użytkownika.
        if (!opcje || opcje.animate === false || bezRuchu) dopasowanieWToku = false;
    }

    // Treść bieżącego widoku: trasy w widoku „Trasy”, pinezki w widoku „Zamówienia”.
    function dopasujBiezacy(animuj) {
        if (widok === 'trasy') dopasujTrasy(animuj);
        else dopasuj(animuj);
    }

    // animuj === false — bez animacji (powrót z ukrycia).
    function dopasuj(animuj) {
        if (!mapa) return;
        const punkty = [];
        znaczniki.forEach((m) => punkty.push(m.getLatLng()));
        const anim = animuj !== false && !bezRuchu;
        if (!punkty.length) {
            dopasujGranice(POLSKA, { padding: [8, 8], animate: anim });
            return;
        }
        if (isFinite(magazyn.lat) && isFinite(magazyn.lng)) punkty.push(L.latLng(magazyn.lat, magazyn.lng));
        dopasujGranice(L.latLngBounds(punkty), Object.assign({ maxZoom: ZOOM_DOPASOWANIA, animate: anim }, MARGINES_DOPASOWANIA));
    }

    // Tablet w układzie jedna-pod-drugą: mapa może być poza ekranem.
    function pokazMapeNaEkranie() {
        if (!panel) return;
        const r = panel.getBoundingClientRect();
        const wys = window.innerHeight || document.documentElement.clientHeight;
        if (r.top < 0 || r.bottom > wys) {
            panel.scrollIntoView({ block: 'nearest', behavior: bezRuchu ? 'auto' : 'smooth' });
        }
    }

    // ── Pinezki ─────────────────────────────────────────────────────────────

    function kluczZnacznika(z) {
        const g = z.geo;
        return [g.lat, g.lng, g.quality, g.source, g.adres_zmieniony ? 1 : 0, kluczSposobu(z.sposob)].join('|');
    }

    function nowyZnacznik(z) {
        const id = z.id;
        const m = L.marker([z.geo.lat, z.geo.lng], {
            icon: ikonaZamowienia(z, { wybrana: wybrany === id }),
            riseOnHover: true,
            lgId: id,
            lgSposob: kluczSposobu(z.sposob),
        });
        m.lgKlucz = kluczZnacznika(z);
        m.on('add', () => opiszZnacznik(m, id));
        m.bindPopup(() => dymekHtml(zamowienia.get(id)), {
            className: 'lg-dymek',
            // Wąska kolumna mapy (od 300 px) musi pomieścić dymek z marginesem.
            minWidth: 220,
            maxWidth: 260,
            autoPanPadding: [12, 12],
        });
        m.bindTooltip(() => podpowiedzHtml(zamowienia.get(id) || z), {
            className: 'lg-podpowiedz-mapy',
            direction: 'top',
            opacity: 1,
        });
        m.on('popupopen', (e) => {
            // Otwarty dymek (także kliknięty na mapie) kończy wcześniejsze wskazania z listy.
            anulujWskazanie();
            m.closeTooltip();
            podepnijDymek(e.popup);
            const zrodlo = zrodloOtwarcia;
            zrodloOtwarcia = 'mapa';
            ustawWybrany(id, zrodlo);
        });
        m.on('popupclose', () => {
            // Otwarcie innego dymku zamyka ten — wybór zdejmujemy dopiero, gdy
            // po chwili żaden dymek nie jest otwarty.
            setTimeout(() => {
                if (zniszczona || wybrany !== id || m.isPopupOpen()) return;
                // Dymek zamknięty przez wejście w korektę tego zamówienia — wiersz
                // zostaje podświetlony do końca trybu.
                if (tryb && tryb.id === id) return;
                ustawWybrany(null, 'mapa');
            }, 0);
        });
        return m;
    }

    // divIcon nie ma `alt` — czytnik ekranu dostaje aria-label na elemencie
    // znacznika (Leaflet daje mu tabindex i role=button). Po setIcon element
    // jest nowy, więc etykietę nadajemy znowu.
    function opiszZnacznik(m, id) {
        const el = m.getElement();
        const z = zamowienia.get(id);
        if (!el || !z) return;
        el.setAttribute('aria-label', 'Zamówienie ' + z.numer + (z.klient ? ', ' + z.klient : '') +
            ', ' + ETYKIETY[kluczSposobu(z.sposob)] +
            (z.geo && z.geo.quality === 'przyblizona' ? ', lokalizacja przybliżona' : '') +
            (z.geo && z.geo.adres_zmieniony ? ', adres zmieniony po ręcznym ustawieniu punktu' : ''));
    }

    function aktualizujZnacznik(m, z) {
        const klucz = kluczZnacznika(z);
        if (m.lgKlucz === klucz) return;
        const stary = m.getLatLng();
        const przesuniety = stary.lat !== z.geo.lat || stary.lng !== z.geo.lng;
        m.lgKlucz = klucz;
        m.options.lgSposob = kluczSposobu(z.sposob);
        if (przesuniety) {
            // markercluster nie śledzi setLatLng — zdejmujemy i dodajemy na nowo
            // (pinezka w trakcie korekty jest poza warstwą i tam zostaje).
            const otwarty = m.isPopupOpen();
            const wWarstwie = pinezki.hasLayer(m);
            if (wWarstwie) pinezki.removeLayer(m);
            m.setLatLng([z.geo.lat, z.geo.lng]);
            m.setIcon(ikonaZamowienia(z, { wybrana: wybrany === z.id }));
            if (wWarstwie) pinezki.addLayer(m);
            opiszZnacznik(m, z.id);
            if (otwarty) otworzDymek(z.id, 'mapa');
        } else {
            m.setIcon(ikonaZamowienia(z, { wybrana: wybrany === z.id }));
            opiszZnacznik(m, z.id);
            if (pinezki.refreshClusters) pinezki.refreshClusters(m);
            if (m.isPopupOpen()) m.getPopup().update();
        }
    }

    /** Różnicowe odświeżenie pinezek — otwarty dymek przeżywa odświeżenie listy. */
    function narysuj(lista) {
        zamowienia.clear();
        lista.forEach((z) => zamowienia.set(z.id, z));
        if (!mapa) return;

        const obecne = new Set();
        const nowe = [];
        lista.forEach((z) => {
            if (!maGeo(z)) return;
            obecne.add(z.id);
            const m = znaczniki.get(z.id);
            if (m) {
                aktualizujZnacznik(m, z);
            } else {
                const n = nowyZnacznik(z);
                znaczniki.set(z.id, n);
                nowe.push(n);
            }
        });
        const doUsuniecia = [];
        znaczniki.forEach((m, id) => {
            if (!obecne.has(id)) {
                doUsuniecia.push(m);
                znaczniki.delete(id);
            }
        });
        usunPinezki(doUsuniecia);
        dodajPinezki(nowe);
        // Otwarty dymek usuniętej pinezki zamyka się sam (popupclose → wybór null).
        odswiezStanMapy();
    }

    function ustawWybrany(id, zrodlo) {
        const poprzedni = wybrany;
        wybrany = id;
        [poprzedni, id].forEach((x) => {
            if (x === null || x === undefined) return;
            const m = znaczniki.get(x);
            const z = zamowienia.get(x);
            if (m && z && maGeo(z)) {
                m.setIcon(ikonaZamowienia(z, { wybrana: wybrany === x }));
                opiszZnacznik(m, x);
            }
        });
        if (poprzedni === id) return;
        sluchaczeWyboru.forEach((cb) => {
            try { cb(id, { zrodlo: zrodlo }); } catch (e) { console.error('[LogisticsMap] onSelect:', e); }
        });
    }

    /**
     * nr: numer żądania z highlight() (bez niego — nowe żądanie). zoomToShowLayer
     * potrafi wywołać funkcję zwrotną dużo później (po animacji, po rozsunięciu
     * klastra) — otwiera dymek tylko wtedy, gdy w międzyczasie nie przyszło
     * nowsze żądanie (szybkie kliknięcia dwóch wierszy).
     */
    function otworzDymek(id, zrodlo, nr, proba) {
        const m = znaczniki.get(id);
        if (!mapa || !m) return false;
        const moje = nr === undefined ? ++nrWskazania : nr;
        const nrProby = proba || 1;
        let aktualna = true;   // ta próba wciąż może otworzyć dymek
        const otworz = () => {
            if (!aktualna || zniszczona || moje !== nrWskazania || znaczniki.get(id) !== m) return;
            aktualna = false;
            zrodloOtwarcia = zrodlo || 'mapa';
            m.openPopup();
            zrodloOtwarcia = 'mapa';
        };
        // Bez grupowania pinezka jest na mapie — highlight() już ją przybliżył.
        if (!pinezki.zoomToShowLayer) {
            otworz();
            return true;
        }
        pinezki.zoomToShowLayer(m, otworz);
        if (aktualna) {
            // markercluster czeka na moveend, przy którym pinezka (albo jej klaster)
            // jest widoczna. Gdy jego przybliżenie wypadło w trakcie innej animacji,
            // Leaflet je pominął i czekanie się nie kończy — wtedy raz ponawiamy,
            // a spóźnione wywołanie porzuconej próby już niczego nie otworzy.
            setTimeout(() => {
                if (!aktualna) return;
                aktualna = false;
                if (nrProby < 2 && !zniszczona && moje === nrWskazania) otworzDymek(id, zrodlo, moje, nrProby + 1);
            }, CZAS_PROBY_DYMKU_MS);
        }
        return true;
    }

    // Przyciski w dymku. Leaflet zatrzymuje propagację kliknięć z dymku
    // (disableClickPropagation), więc delegacja na kontenerze mapy ich nie
    // zobaczy — słuchamy na samym elemencie dymku (przeżywa popup.update()).
    function podepnijDymek(popup) {
        const el = popup.getElement();
        if (!el || el.lgPodpiety) return;
        el.lgPodpiety = true;
        el.addEventListener('click', (e) => {
            const b = e.target.closest('[data-lg-mapa-akcja]');
            if (!b || b.disabled) return;
            const id = Number(b.getAttribute('data-id'));
            const akcja = b.getAttribute('data-lg-mapa-akcja');
            if (akcja === 'popraw') zacznijKorekte(id);
            else if (akcja === 'przywroc') przywrocAutomat(id);
            else if (akcja === 'potwierdz') potwierdzPunkt(id, b);
        });
    }

    // ── Zapis punktu ────────────────────────────────────────────────────────

    /**
     * Odpowiedź API → stan mapy + słuchacze (lista podmienia wiersz, licznik
     * „Bez lokalizacji” się zmniejsza). W trakcie trybu (logistyk zaczął już
     * następne zamówienie) pinezek nie ruszamy — zakonczTryb() narysuje ostatnią listę.
     */
    function przyjmijZamowienie(order, rodzaj) {
        if (!order) return;
        const i = ostatnie.findIndex((z) => z.id === order.id);
        if (i !== -1) ostatnie[i] = order;
        zamowienia.set(order.id, order);
        if (!tryb) narysuj(ostatnie.length ? ostatnie : [order]);
        sluchaczeZmian.forEach((cb) => {
            try { cb(order, rodzaj); } catch (e) { console.error('[LogisticsMap] onZmiana:', e); }
        });
    }

    /**
     * (oględziny Task 8, A2) Odmowa zapisu punktu, gdy logistyk pracuje już nad NASTĘPNYM
     * zamówieniem (szybka praca na kolejce): pasek trybu należy do nowego zamówienia, więc
     * błąd (np. 409 — przystanek zatwierdzonej trasy) idzie do słuchaczy onBlad (logistics.js
     * robi z niego komunikat listy), zamiast zginąć po cichu.
     */
    // Początek zdania z numerem zamówienia tylko wtedy, gdy tekst serwera go nie zawiera
    // (zwykle „Zamówienie 1659 jest…” — numer dwa razy czytałby się źle, runda 2).
    function bladPunktu(poczatek, numer, e) {
        const tekst = String((e && e.message) || '');
        return (tekst.indexOf(String(numer)) === -1 ? poczatek + ' zamówienia ' + numer : poczatek) + '. ' + tekst;
    }

    function zglosBlad(tekst) {
        if (!sluchaczeBledow.length) {
            console.warn('[LogisticsMap]', tekst);
            return;
        }
        sluchaczeBledow.forEach((cb) => {
            try { cb(tekst); } catch (e) { console.error('[LogisticsMap] onBlad:', e); }
        });
    }

    function zapiszPunkt(id, latlng) {
        const punkt = L.latLng(latlng).wrap();
        return wyslij('/orders/' + encodeURIComponent(id) + '/geo', {
            method: 'PUT',
            body: JSON.stringify({
                lat: Math.round(punkt.lat * 1e6) / 1e6,
                lng: Math.round(punkt.lng * 1e6) / 1e6,
            }),
        });
    }

    // ── Tryb „Popraw lokalizację” ───────────────────────────────────────────

    function zacznijKorekte(id) {
        const z = zamowienia.get(id);
        const m = znaczniki.get(id);
        if (!mapa || !z || !m || !maGeo(z)) return;
        zakonczTryb();
        anulujWskazanie();
        mapa.closePopup();
        const start = m.getLatLng();
        // Oryginał znika z warstwy pinezek na czas korekty; przeciągamy osobną pinezkę.
        pinezki.removeLayer(m);
        const tymczasowa = L.marker(start, {
            icon: ikonaZamowienia(z, { edycja: true }),
            draggable: true,
            autoPan: true,
            zIndexOffset: 2000,
            alt: 'Nowe miejsce dostawy zamówienia ' + z.numer,
        }).addTo(warstwaEdycji);
        tymczasowa.on('dragend', () => zaproponuj(tymczasowa.getLatLng()));
        tryb = { rodzaj: 'korekta', id: id, z: z, oryginal: m, znacznik: tymczasowa, nowy: null, zapisywanie: false, blad: null };
        kontener.classList.add('is-korekta');
        ustawWybrany(id, 'lista');
        mapa.setView(start, Math.max(mapa.getZoom(), ZOOM_KOREKTY), { animate: !bezRuchu });
        pasekTrybu();
    }

    function zaproponuj(latlng) {
        if (!tryb || tryb.rodzaj !== 'korekta' || tryb.zapisywanie) return;
        tryb.nowy = latlng;
        tryb.blad = null;
        tryb.znacznik.setLatLng(latlng);
        pasekTrybu();
    }

    async function zapiszKorekte() {
        if (!tryb || tryb.rodzaj !== 'korekta' || !tryb.nowy || tryb.zapisywanie) return;
        const biezacy = tryb;
        biezacy.zapisywanie = true;
        biezacy.znacznik.dragging.disable();
        pasekTrybu();
        try {
            const dane = await zapiszPunkt(biezacy.id, biezacy.nowy);
            if (zniszczona) return;
            if (tryb !== biezacy) {
                // W trakcie zapisu logistyk przeszedł do następnego zamówienia —
                // punkt i tak jest zapisany: lista i licznik dostają go od razu.
                przyjmijZamowienie(dane.order, 'poprawiono');
                return;
            }
            zakonczTryb();
            przyjmijZamowienie(dane.order, 'poprawiono');
            pokazPasek('ok', 'Zapisano nowe miejsce dostawy zamówienia ' + biezacy.z.numer + '.');
            otworzDymek(dane.order.id, 'mapa');
        } catch (e) {
            if (zniszczona) return;
            if (tryb !== biezacy) {
                zglosBlad(bladPunktu('Nie zapisano nowego miejsca dostawy', biezacy.z.numer, e));
                return;
            }
            biezacy.zapisywanie = false;
            biezacy.blad = e.message;
            biezacy.znacznik.dragging.enable();
            pasekTrybu();
        }
    }

    // ── Tryb „Ustaw na mapie” (zamówienie bez punktu) ───────────────────────

    function ustawNaMapie(arg) {
        const z = (arg && typeof arg === 'object') ? arg : zamowienia.get(Number(arg));
        if (!mapa || !z || zniszczona) return false;
        // Etap 3: punkt stawia się na pinezkach — z widoku tras wracamy do zamówień.
        if (widok !== 'zamowienia' && !ustawWidok('zamowienia')) return false;
        zakonczTryb();
        anulujWskazanie();
        mapa.closePopup();
        tryb = { rodzaj: 'ustaw', id: z.id, z: z, znacznik: null, nowy: null, zapisywanie: false, blad: null };
        kontener.classList.add('is-celowanie');
        // Wiersz zamówienia podświetlony na liście przez cały tryb.
        ustawWybrany(z.id, 'lista');
        pokazMapeNaEkranie();
        pasekTrybu();
        return true;
    }

    async function ustawPunkt(latlng) {
        const biezacy = tryb;
        biezacy.zapisywanie = true;
        biezacy.blad = null;
        biezacy.znacznik = L.marker(latlng, {
            icon: ikonaZamowienia(Object.assign({}, biezacy.z, { geo: { quality: 'dokladna' } }), { edycja: true }),
            interactive: false,
            zIndexOffset: 2000,
        }).addTo(warstwaEdycji);
        pasekTrybu();
        try {
            const dane = await zapiszPunkt(biezacy.id, latlng);
            if (zniszczona) return;
            if (tryb !== biezacy) {
                // Szybka praca na kolejce: „Ustaw na mapie” następnego zamówienia
                // w trakcie zapisu. Zapis się udał — wiersz i licznik od razu,
                // pinezka po zakończeniu nowego trybu.
                przyjmijZamowienie(dane.order, 'ustawiono');
                return;
            }
            zakonczTryb();
            przyjmijZamowienie(dane.order, 'ustawiono');
            pokazPasek('ok', 'Ustawiono miejsce dostawy zamówienia ' + biezacy.z.numer + '.');
            otworzDymek(dane.order.id, 'mapa');
        } catch (e) {
            if (zniszczona) return;
            if (tryb !== biezacy) {
                zglosBlad(bladPunktu('Nie ustawiono miejsca dostawy', biezacy.z.numer, e));
                return;
            }
            warstwaEdycji.removeLayer(biezacy.znacznik);
            biezacy.znacznik = null;
            biezacy.zapisywanie = false;
            biezacy.blad = e.message;
            pasekTrybu();
        }
    }

    function klikMapy(e) {
        if (!tryb || tryb.zapisywanie) return;
        if (tryb.rodzaj === 'ustaw') ustawPunkt(e.latlng);
        else if (tryb.rodzaj === 'korekta') zaproponuj(e.latlng);
    }

    /** Sprząta po trybie: tymczasowa pinezka, oryginał wraca do klastrów. */
    function zakonczTryb() {
        if (!tryb) return;
        const t = tryb;
        tryb = null;
        if (warstwaEdycji) warstwaEdycji.clearLayers();
        if (t.rodzaj === 'korekta' && t.oryginal && znaczniki.get(t.id) === t.oryginal) {
            pinezki.addLayer(t.oryginal);
        }
        kontener.classList.remove('is-korekta', 'is-celowanie');
        ukryjPasek();
        if (wybrany === t.id) ustawWybrany(null, 'mapa');
        // render() w trakcie trybu tylko zapamiętał listę — teraz ją rysujemy.
        narysuj(ostatnie);
    }

    function anulujTryb() {
        if (!tryb || tryb.zapisywanie) return;
        zakonczTryb();
    }

    function naKlawisz(e) {
        if (e.key === 'Escape' && tryb && !tryb.zapisywanie) {
            anulujTryb();
        }
    }

    // ── „Przywróć automat” i „Potwierdź punkt” ──────────────────────────────

    async function przywrocAutomat(id) {
        const z = zamowienia.get(id);
        if (!z) return;
        if (!window.confirm('Usunąć ręcznie ustawiony punkt zamówienia ' + z.numer + '?\n' +
            'Zamówienie zostanie zlokalizowane od nowa według adresu z Base.')) return;
        pokazPasek('info', 'Przywracanie automatu dla zamówienia ' + z.numer + '…');
        try {
            const dane = await wyslij('/orders/' + encodeURIComponent(id) + '/geo/reset', { method: 'POST', body: '{}' });
            if (zniszczona) return;
            if (mapa) mapa.closePopup();
            przyjmijZamowienie(dane.order, 'przywrocono');
            pokazPasek('ok', 'Przywrócono automat dla zamówienia ' + z.numer + '. Nowy punkt pojawi się po lokalizowaniu w tle.');
        } catch (e) {
            if (zniszczona) return;
            pokazPasek('blad', 'Nie przywrócono automatu dla zamówienia ' + z.numer + '. ' + e.message,
                [{ etykieta: 'Zamknij', akcja: 'zamknij-pasek' }]);
        }
    }

    // Ikona „adres zmieniony” gaśnie dopiero po ponownym zapisaniu punktu
    // (ustaw_recznie zeruje flagę) — „Potwierdź punkt” zapisuje go bez zmian.
    async function potwierdzPunkt(id, przycisk) {
        const z = zamowienia.get(id);
        if (!maGeo(z)) return;
        if (przycisk) przycisk.disabled = true;
        try {
            const dane = await zapiszPunkt(id, L.latLng(z.geo.lat, z.geo.lng));
            if (zniszczona) return;
            przyjmijZamowienie(dane.order, 'potwierdzono');
            pokazPasek('ok', 'Potwierdzono punkt zamówienia ' + z.numer + '.');
        } catch (e) {
            if (zniszczona) return;
            if (przycisk && przycisk.isConnected) przycisk.disabled = false;
            pokazPasek('blad', 'Nie potwierdzono punktu zamówienia ' + z.numer + '. ' + e.message,
                [{ etykieta: 'Zamknij', akcja: 'zamknij-pasek' }]);
        }
    }

    // ── Pastylka: proporcja listy i mapy ────────────────────────────────────

    // localStorage bywa niedostępny (tryb prywatny, zablokowane dane strony) —
    // wtedy zwyczajnie domyślny podział, bez błędów.
    function czytajUdzial() {
        try {
            const v = parseFloat(window.localStorage.getItem(KLUCZ_UDZIALU));
            return v > 0 && v < 1 ? v : null;
        } catch (e) {
            return null;
        }
    }

    function zapiszUdzial(udzial) {
        try {
            if (udzial === null) window.localStorage.removeItem(KLUCZ_UDZIALU);
            else window.localStorage.setItem(KLUCZ_UDZIALU, udzial.toFixed(4));
        } catch (e) { /* bez pamięci — podział wróci do domyślnego po przeładowaniu */ }
    }

    const obokSiebie = () => !!(uchwyt && uchwyt.offsetParent !== null);

    /**
     * udzial = szerokość mapy / szerokość siatki. CSS dostaje clamp, więc
     * minima kolumn trzymają się także po zmianie szerokości okna; null =
     * domyślny podział z logistics.css.
     */
    function ustawUdzial(udzial) {
        if (!siatka) return;
        if (udzial === null) {
            siatka.style.removeProperty('--lg-mapa-kolumna');
        } else {
            siatka.style.setProperty('--lg-mapa-kolumna', 'clamp(' + MAPA_MIN_PX + 'px, calc(100% * ' +
                udzial.toFixed(4) + '), calc(100% - ' + (SZER_ROWKA + LISTA_MIN_PX) + 'px))');
        }
    }

    function szerokoscMapy() {
        return panel ? panel.getBoundingClientRect().width : 0;
    }

    /** Szerokość mapy w px → udział, z minimami obu kolumn. */
    function udzialDlaMapy(px) {
        const szer = siatka.getBoundingClientRect().width;
        const maks = szer - SZER_ROWKA - LISTA_MIN_PX;
        const mapaPx = Math.max(MAPA_MIN_PX, Math.min(maks, px));
        return mapaPx / szer;
    }

    // aria-valuenow = udział listy w % (separator stoi na prawym brzegu listy).
    function opiszPastylke() {
        if (!pastylka || !siatka || !obokSiebie()) return;
        const dostepne = siatka.getBoundingClientRect().width - SZER_ROWKA;
        if (dostepne <= 0) return;
        const lista = Math.round(((dostepne - szerokoscMapy()) / dostepne) * 100);
        const min = Math.round((LISTA_MIN_PX / dostepne) * 100);
        const maks = Math.round(((dostepne - MAPA_MIN_PX) / dostepne) * 100);
        pastylka.setAttribute('aria-valuenow', String(lista));
        pastylka.setAttribute('aria-valuemin', String(Math.min(min, maks)));
        pastylka.setAttribute('aria-valuemax', String(maks));
        pastylka.setAttribute('aria-valuetext', 'Lista ' + lista + '%, mapa ' + (100 - lista) + '%');
    }

    // Leaflet musi przeliczyć rozmiar po zmianie szerokości kolumny — w trakcie
    // przeciągania najwyżej raz na klatkę.
    function odswiezPoPastylce() {
        if (klatkaPastylki) return;
        klatkaPastylki = window.requestAnimationFrame(() => {
            klatkaPastylki = 0;
            pastylkaZmienia = false;
            if (mapa && maWymiary()) mapa.invalidateSize({ pan: false });
            opiszPastylke();
        });
    }

    function naPastylkeWDol(e) {
        if (!obokSiebie() || !siatka) return;
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        e.preventDefault();   // bez zaznaczania tekstu i bez przewijania dotykiem
        const prawa = siatka.getBoundingClientRect().right;
        // Chwyt względem miejsca kliknięcia — kolumna nie skacze pod kursor.
        przeciaganie = { id: e.pointerId, chwyt: prawa - e.clientX - szerokoscMapy() };
        try { uchwyt.setPointerCapture(e.pointerId); } catch (err) { /* stary przeglądarkowy silnik */ }
        uchwyt.classList.add('is-przeciagany');
        document.documentElement.classList.add('lg-przeciaganie-uchwytu');
    }

    function naPastylkeRuch(e) {
        if (!przeciaganie || e.pointerId !== przeciaganie.id) return;
        const prawa = siatka.getBoundingClientRect().right;
        przeciaganie.udzial = udzialDlaMapy(prawa - e.clientX - przeciaganie.chwyt);
        ustawUdzial(przeciaganie.udzial);
        odswiezPoPastylce();
    }

    function zakonczPrzeciaganie() {
        if (!przeciaganie) return;
        const koniec = przeciaganie;
        przeciaganie = null;
        if (uchwyt) {
            uchwyt.classList.remove('is-przeciagany');
            try { uchwyt.releasePointerCapture(koniec.id); } catch (err) { /* już zwolniony */ }
        }
        document.documentElement.classList.remove('lg-przeciaganie-uchwytu');
        if (klatkaPastylki) {
            window.cancelAnimationFrame(klatkaPastylki);
            klatkaPastylki = 0;
        }
        pastylkaZmienia = false;
        if (mapa && maWymiary()) mapa.invalidateSize({ pan: false });
        opiszPastylke();
        if (koniec.udzial !== undefined) zapiszUdzial(koniec.udzial);
    }

    function naPastylkeKlawisz(e) {
        if (!obokSiebie()) return;
        const szer = siatka.getBoundingClientRect().width;
        let mapaPx = szerokoscMapy();
        // Separator stoi na prawym brzegu listy: strzałka w lewo = węższa lista, szersza mapa.
        if (e.key === 'ArrowLeft') mapaPx += KROK_PASTYLKI_PX;
        else if (e.key === 'ArrowRight') mapaPx -= KROK_PASTYLKI_PX;
        else if (e.key === 'Home') mapaPx = szer;          // lista najwęższa
        else if (e.key === 'End') mapaPx = MAPA_MIN_PX;    // mapa najwęższa
        else return;
        e.preventDefault();
        const udzial = udzialDlaMapy(mapaPx);
        pastylkaZmienia = true;
        ustawUdzial(udzial);
        zapiszUdzial(udzial);
        odswiezPoPastylce();
    }

    function przywrocDomyslnyPodzial() {
        pastylkaZmienia = true;
        zapiszUdzial(null);
        ustawUdzial(null);
        odswiezPoPastylce();
    }

    // ── Widok „Trasy” (etap 3) ──────────────────────────────────────────────
    // Pinezki zamówień i trasy to dwie warstwy tej samej mapy: ustawWidok zdejmuje
    // jedną i zakłada drugą, bez przebudowy mapy (podkład, magazyn, pastylka,
    // „Grupuj pinezki” i położenie mapy zostają). Dane tras pobiera
    // logistics-routes.js (GET /routes/map) i podaje przez renderTrasy().

    const NAZWY_STATUSOW_TRAS = { robocza: 'Robocza', zatwierdzona: 'Zatwierdzona', wykonana: 'Wykonana' };

    function kolorTrasy(id) {
        const n = Math.abs(Math.floor(Number(id) || 0));
        return 'lg-trasa-kolor-' + (n % LICZBA_KOLOROW_TRAS);
    }

    // 'YYYY-MM-DD' ×2 → '25.09' albo '25.09–26.09' (jak na liście tras).
    function zakresDat(od, doDnia) {
        const a = dataKrotka(od);
        const b = dataKrotka(doDnia);
        return !b || a === b ? a : a + '–' + b;
    }

    // isFinite(null) === true — brak współrzędnych trzeba odsiać wprost.
    const maPunkt = (p) => !!p && p.lat !== null && p.lng !== null && p.lat !== undefined &&
        p.lng !== undefined && isFinite(p.lat) && isFinite(p.lng);

    /** GeoJSON przebiegu (LineString / MultiLineString, [lng, lat]) → linie [lat, lng] dla L.polyline. */
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

    /**
     * Przystanek: biała „stacja” z obwódką w kolorze trasy i numerem — ta sama co w edytorze trasy.
     * (I5) Anulowany (zamówienie bez aktywnych pozycji, API: `anulowane`, `pozycja` = null) —
     * szara stacja z „—”: Routimo go pomija, więc numer mają tylko aktywne przystanki.
     */
    function ikonaPrzystanku(numer, klasaKoloru, anulowany) {
        const tekst = anulowany ? '—' : String(numer);
        return L.divIcon({
            className: 'lg-znacznik-przystanku',
            html: '<span class="lg-stacja lg-stacja--mapa ' + klasaKoloru + (tekst.length > 2 ? ' lg-stacja--dlugi' : '') +
                (anulowany ? ' lg-stacja--anulowana' : '') + '">' + esc(tekst) + '</span>',
            iconSize: [24, 24],
            iconAnchor: [12, 12],
            // Dymek z kierunkiem 'auto' (lewo/prawo, w stronę środka mapy) — od krawędzi stacji.
            tooltipAnchor: [12, 0],
        });
    }

    function opisTrasy(t) {
        return t.nazwa + ' (' + zakresDat(t.date_from, t.date_to) + ', ' +
            (NAZWY_STATUSOW_TRAS[t.status] || t.status || '').toLowerCase() + ')';
    }

    /** Warstwa tras od nowa z trasyDane — linie w kolorze trasy na białej podkładce, numerowane przystanki. */
    function narysujTrasy() {
        grupyTras.clear();
        if (!mapa || !warstwaTras) return;
        warstwaTras.clearLayers();
        (trasyDane || []).forEach((t) => {
            const klasa = kolorTrasy(t.id);
            const grupa = L.featureGroup();
            liniePrzebiegu(t.przebieg).forEach((punkty) => {
                // Biała podkładka pod linią — trasa czytelna na każdym podkładzie i nad inną trasą.
                L.polyline(punkty, {
                    className: 'lg-trasa-obrys', color: '#fff', weight: 8, opacity: 0.9,
                    interactive: false, lineCap: 'round', lineJoin: 'round',
                }).addTo(grupa);
                // Kolor linii daje CSS (klasa koloru trasy); `color` to tylko zapas bez arkusza.
                L.polyline(punkty, {
                    className: 'lg-trasa-linia ' + klasa + (t.przyblizony ? ' is-przyblizona' : ''),
                    color: '#1a1a2e', weight: 4, opacity: 1, lineCap: 'round', lineJoin: 'round',
                    // Przebieg przybliżony (linie proste) — przerywana, jak przybliżona pinezka.
                    dashArray: t.przyblizony ? '8 8' : null,
                }).bindTooltip(esc(opisTrasy(t)) + '<span class="lg-podpowiedz-mapy-uwaga">' +
                    (t.przyblizony ? 'Przebieg przybliżony. ' : '') + 'Kliknij, żeby otworzyć trasę.</span>', {
                    // (oględziny Task 8, M9) Kierunek 'auto' (w stronę środka mapy) i zawijany tekst
                    // — w wąskiej kolumnie mapy (1440 px z panelem) dymek nie wychodzi poza mapę.
                    className: 'lg-podpowiedz-mapy lg-podpowiedz-mapy--zawijana', sticky: true, direction: 'auto', opacity: 1,
                }).addTo(grupa);
            });
            (t.przystanki || []).forEach((p) => {
                if (!maPunkt(p)) return;
                const anulowany = !!p.anulowane;
                L.marker([p.lat, p.lng], {
                    icon: ikonaPrzystanku(p.pozycja, klasa, anulowany),
                    // Klawiatura wybiera trasy z legendy pod mapą — bez setek przystanków Tab.
                    keyboard: false,
                    zIndexOffset: anulowany ? 400 : 500,
                    riseOnHover: true,
                }).bindTooltip('<b>' + (anulowany ? '— ' : esc(p.pozycja) + '. ') + esc(p.numer) + '</b>' +
                    (p.klient ? ' ' + esc(p.klient) : '') +
                    '<span class="lg-podpowiedz-mapy-uwaga">' + esc(t.nazwa) + '</span>' +
                    (anulowany ? '<span class="lg-podpowiedz-mapy-uwaga">Anulowane — nie trafi do Routimo</span>' : ''), {
                    className: 'lg-podpowiedz-mapy lg-podpowiedz-mapy--zawijana', direction: 'auto', opacity: 1,
                }).addTo(grupa);
            });
            // Klik w linię albo przystanek = trasa w edytorze; najechanie wyróżnia trasę.
            grupa.on('click', (e) => {
                if (e.originalEvent) L.DomEvent.stopPropagation(e);
                wybierzTrase(t.id);
            });
            grupa.on('mouseover', () => wyroznijTrase(t.id));
            grupa.on('mouseout', () => wyroznijTrase(null));
            warstwaTras.addLayer(grupa);
            grupyTras.set(t.id, grupa);
        });
    }

    /** Pozostałe trasy przygasają (CSS), wyróżniona idzie na wierzch; też pozycja w legendzie. */
    function wyroznijTrase(id) {
        const nowa = id === undefined ? null : id;
        if (nowa === wyroznionaTrasa) return;
        wyroznionaTrasa = nowa;
        kontener.classList.toggle('lg-trasy-wyroznienie', nowa !== null);
        grupyTras.forEach((grupa, idTrasy) => {
            grupa.eachLayer((w) => {
                const element = w.getElement ? w.getElement() : null;
                if (element) element.classList.toggle('is-wyrozniona', idTrasy === nowa);
            });
            if (idTrasy === nowa && mapa && mapa.hasLayer(grupa)) grupa.bringToFront();
        });
        if (legendaTras) {
            legendaTras.querySelectorAll('[data-lg-mapa-trasa]').forEach((b) => {
                b.classList.toggle('is-wyrozniona', Number(b.getAttribute('data-lg-mapa-trasa')) === nowa);
            });
        }
    }

    function dopasujTrasy(animuj) {
        if (!mapa) return;
        const punkty = [];
        (trasyDane || []).forEach((t) => {
            (t.przystanki || []).forEach((p) => { if (maPunkt(p)) punkty.push(L.latLng(p.lat, p.lng)); });
            liniePrzebiegu(t.przebieg).forEach((linia) => linia.forEach((p) => punkty.push(L.latLng(p[0], p[1]))));
        });
        const anim = animuj !== false && !bezRuchu;
        if (!punkty.length) {
            dopasujGranice(POLSKA, { padding: [8, 8], animate: anim });
            return;
        }
        if (isFinite(magazyn.lat) && isFinite(magazyn.lng)) punkty.push(L.latLng(magazyn.lat, magazyn.lng));
        dopasujGranice(L.latLngBounds(punkty), Object.assign({ maxZoom: ZOOM_DOPASOWANIA, animate: anim }, MARGINES_DOPASOWANIA));
    }

    /** Legenda pod mapą w widoku tras: każda trasa to przycisk (klawiatura) — klik otwiera ją w edytorze. */
    function renderujLegendeTras() {
        if (!legendaTras) return;
        const pusto = (tekst) => '<span class="lg-legenda-tras-pusto">' + esc(tekst) + '</span>';
        if (bladTras && !trasyDane) {
            legendaTras.innerHTML = pusto('Nie wczytano tras.');
            return;
        }
        if (!trasyDane) {
            legendaTras.innerHTML = pusto('Wczytywanie tras…');
            return;
        }
        if (!trasyDane.length) {
            legendaTras.innerHTML = pusto('Brak aktywnych tras (roboczych ani zatwierdzonych).');
            return;
        }
        legendaTras.innerHTML = trasyDane.map((t) => {
            const status = String(t.status || '');
            return '<button type="button" class="lg-legenda-trasa ' + kolorTrasy(t.id) + '" data-lg-mapa-trasa="' + esc(t.id) + '"' +
                ' title="' + esc('Otwórz trasę ' + opisTrasy(t)) + '" aria-label="' + esc('Otwórz trasę ' + opisTrasy(t)) + '">' +
                '<span class="lg-legenda-trasa-linia' + (t.przyblizony ? ' is-przyblizona' : '') + '" aria-hidden="true"></span>' +
                '<span class="lg-legenda-trasa-nazwa">' + esc(t.nazwa) + '</span>' +
                '<span class="lg-legenda-trasa-daty">' + esc(zakresDat(t.date_from, t.date_to)) + '</span>' +
                '<span class="lg-status lg-status--male lg-status--' + esc(status) + '">' +
                    esc(NAZWY_STATUSOW_TRAS[status] || status) + '</span>' +
                '</button>';
        }).join('');
    }

    /** Nakładka stanu w widoku tras (ładowanie, błąd, brak tras, brak punktów). */
    function stanMapyTras() {
        if (bladTras) {
            pokazStanMapy('Nie udało się wczytać tras. ' + bladTras, 'is-blad');
            return;
        }
        if (!trasyDane) {
            pokazStanMapy('Wczytywanie tras…', 'is-ladowanie');
            return;
        }
        if (!trasyDane.length) {
            pokazStanMapy('Brak aktywnych tras. Nową trasę utworzysz w zakładce „Trasy”.');
            return;
        }
        if (!trasyDane.some((t) => (t.przystanki || []).some(maPunkt))) {
            pokazStanMapy(trasyDane.some((t) => (t.przystanki || []).length)
                ? 'Przystanki aktywnych tras nie mają jeszcze punktów na mapie.'
                : 'Aktywne trasy nie mają jeszcze przystanków.');
            return;
        }
        ukryjStanMapy();
    }

    function opiszPrzyciskDopasowania() {
        if (!przyciskDopasowania) return;
        const tekst = widok === 'trasy' ? 'Pokaż wszystkie trasy' : 'Pokaż wszystkie pinezki';
        przyciskDopasowania.title = tekst;
        przyciskDopasowania.setAttribute('aria-label', tekst);
    }

    /** Stan przełącznika „Zamówienia | Trasy” w nagłówku mapy, legendy i opisów mapy. */
    function zaznaczWidok() {
        root.querySelectorAll('[data-lg-mapa-widok]').forEach((b) => {
            const aktywny = b.getAttribute('data-lg-mapa-widok') === widok;
            b.setAttribute('aria-pressed', aktywny ? 'true' : 'false');
            b.classList.toggle('is-aktywny', aktywny);
        });
        const opis = widok === 'trasy' ? 'Mapa tras' : 'Mapa zamówień';
        kontener.setAttribute('aria-label', opis);
        if (panel) panel.setAttribute('aria-label', opis);
        kontener.classList.toggle('is-widok-tras', widok === 'trasy');
        if (legendaZamowien) legendaZamowien.hidden = widok === 'trasy';
        if (legendaTras) legendaTras.hidden = widok !== 'trasy';
        opiszPrzyciskDopasowania();
    }

    /**
     * 'zamowienia' | 'trasy'. Zwraca false, gdy nie da się przełączyć (zapis punktu
     * w toku — pinezka musi zostać do odpowiedzi serwera). Tryb korekty / ustawiania
     * punktu bez zapisu po prostu się kończy.
     */
    function ustawWidok(nowy) {
        if (zniszczona || (nowy !== 'zamowienia' && nowy !== 'trasy')) return false;
        if (nowy === widok) {
            zaznaczWidok();
            return true;
        }
        if (tryb && tryb.zapisywanie) return false;
        zakonczTryb();
        anulujWskazanie();
        wyroznijTrase(null);
        widok = nowy;
        if (mapa) {
            mapa.closePopup();
            if (widok === 'trasy') {
                mapa.removeLayer(pinezki);
                mapa.addLayer(warstwaTras);
                if (!dopasowanoTrasy && trasyDane && trasyDane.length) {
                    dopasujTrasy();
                    dopasowanoTrasy = true;
                }
            } else {
                mapa.removeLayer(warstwaTras);
                mapa.addLayer(pinezki);
                if (dopasujPoPowrocie) {
                    dopasuj();
                    dopasowanoPierwszy = true;
                }
                dopasujPoPowrocie = false;
            }
        }
        zaznaczWidok();
        odswiezStanMapy();
        return true;
    }

    /**
     * trasy: lista z GET /routes/map ([{id, nazwa, status, date_from, date_to, przebieg,
     * przyblizony, przystanki: [{pozycja, anulowane, order_id, numer, klient, lat, lng}]}]);
     * pozycja — numer wśród aktywnych przystanków, null dla anulowanego (I5).
     * opcje.blad: tekst błędu pobrania — poprzednie trasy (jeśli były) zostają na mapie.
     * Pierwsze trasy dopasowują widok; kolejne (po każdej zmianie trasy) już nie ruszają mapy.
     */
    function renderTrasy(trasy, opcje) {
        if (zniszczona) return;
        const o = opcje || {};
        if (o.blad) {
            bladTras = String(o.blad);
        } else {
            bladTras = null;
            trasyDane = Array.isArray(trasy) ? trasy.slice() : [];
        }
        wyroznijTrase(null);
        narysujTrasy();
        renderujLegendeTras();
        if (mapa && widok === 'trasy' && !dopasowanoTrasy && trasyDane && trasyDane.length) {
            dopasujTrasy();
            dopasowanoTrasy = true;
        }
        odswiezStanMapy();
    }

    function onWyborTrasy(cb) {
        if (typeof cb === 'function') sluchaczeWyboruTrasy.push(cb);
        return () => {
            const i = sluchaczeWyboruTrasy.indexOf(cb);
            if (i !== -1) sluchaczeWyboruTrasy.splice(i, 1);
        };
    }

    function wybierzTrase(id) {
        if (zniszczona || !isFinite(id)) return;
        sluchaczeWyboruTrasy.slice().forEach((cb) => {
            try { cb(id); } catch (e) { console.error('[LogisticsMap] onWyborTrasy:', e); }
        });
    }

    /**
     * Nowa L.TileLayer bieżącego podkładu dla innej mapy (mapka edytora trasy): ten sam
     * klucz CARTO i ta sama obsługa odrzuconego klucza co tutaj. Działa też, zanim ta
     * mapa powstała (Dashboard schowany) — wtedy podkład z wyboru zapamiętanego w przeglądarce.
     */
    function nowaWarstwaPodkladu() {
        if (zniszczona) return null;
        const podklad = aktywnyPodklad || PODKLADY.find((p) => p.id === czytajPodklad()) || PODKLADY[0];
        const warstwa = nowaWarstwaKafelkow(podklad, true);
        // Atrybucja w opcjach warstwy — domyślna kontrolka mapki zbierze ją sama
        // (ta mapa ma kontrolkę ręczną, więc tu warstwy jej nie niosą).
        warstwa.options.attribution = podklad.atrybucja;
        return warstwa;
    }

    function klikLegendyTras(e) {
        const b = e.target.closest('[data-lg-mapa-trasa]');
        if (b) wybierzTrase(Number(b.getAttribute('data-lg-mapa-trasa')));
    }

    function najazdLegendyTras(e) {
        const b = e.target.closest('[data-lg-mapa-trasa]');
        wyroznijTrase(b ? Number(b.getAttribute('data-lg-mapa-trasa')) : null);
    }

    const zdejmijWyroznienie = () => wyroznijTrase(null);

    // ── Interfejs publiczny ─────────────────────────────────────────────────

    function render(lista, opcje) {
        if (zniszczona) return;
        ostatnie = Array.isArray(lista) ? lista.slice() : [];
        const dopasujTeraz = !!(opcje && opcje.dopasuj);
        if (!mapa) {
            zamowienia.clear();
            ostatnie.forEach((z) => zamowienia.set(z.id, z));
            if (dopasujTeraz) czekaNaDopasowanie = true;
            return;
        }
        // W trakcie korekty/ustawiania nie ruszamy pinezek — zakonczTryb()
        // narysuje ostatnią listę.
        if (tryb) return;
        narysuj(ostatnie);
        if (dopasujTeraz || (!dopasowanoPierwszy && znaczniki.size)) {
            // Widok tras: pinezek nie widać — widok dopasujemy po powrocie do zamówień.
            if (widok === 'trasy') {
                dopasujPoPowrocie = true;
            } else {
                dopasuj();
                dopasowanoPierwszy = true;
            }
        }
    }

    /** Nasłuch moveend poprzedniego highlight() — nowe wskazanie go zdejmuje. */
    function porzucWskazanie() {
        clearTimeout(timerWskazania);
        if (oczekujaceWskazanie && mapa) mapa.off('moveend', oczekujaceWskazanie);
        oczekujaceWskazanie = null;
    }

    /** Unieważnia oczekujące otwarcie dymku (otwarty inny dymek, początek trybu). */
    function anulujWskazanie() {
        porzucWskazanie();
        nrWskazania += 1;
    }

    /**
     * Pokazuje zamówienie na mapie i otwiera jego dymek. opcje.przewin — tylko
     * jawne „pokaż na mapie” (przycisk pinezki w wierszu): w układzie mapa-nad-
     * listą przewija stronę do mapy. Zwykły klik w wiersz strony nie przewija.
     */
    function highlight(id, opcje) {
        const m = znaczniki.get(id);
        if (!mapa || !m || tryb) return false;
        // Etap 3: w widoku tras pinezek nie widać — jawne „pokaż na mapie” wraca do zamówień.
        if (widok !== 'zamowienia' && !(opcje && opcje.przewin && ustawWidok('zamowienia'))) return false;
        if (opcje && opcje.przewin) pokazMapeNaEkranie();
        porzucWskazanie();
        const nr = ++nrWskazania;
        const cel = m.getLatLng();
        // Po rozsunięciu klastra mapa stoi na maksymalnym zoomie — nie trzymamy się go.
        const zoom = Math.min(Math.max(mapa.getZoom(), ZOOM_WSKAZANIA), ZOOM_WSKAZANIA_MAKS);
        // Nasłuch moveend podpinamy PO setView: setView przerywa animację poprzedniego
        // wskazania, a Leaflet kończy ją zdarzeniem moveend jeszcze w środku setView —
        // wcześniej podpięty nasłuch otwierałby dymek w pół drogi, a dalsza animacja
        // zostawiała mapę na zoomie, na którym pinezka siedzi w klastrze (bez dymku).
        mapa.setView(cel, zoom, { animate: !bezRuchu });
        if (zniszczona || nr !== nrWskazania) return true;
        const naMiejscu = () => mapa.getZoom() === zoom &&
            mapa.latLngToContainerPoint(cel).distanceTo(mapa.getSize().divideBy(2)) < 1;
        let zostaloProb = 3;
        let zrobione = false;
        const otworz = () => {
            if (zniszczona || zrobione || nr !== nrWskazania) return;
            if (!naMiejscu() && zostaloProb > 0) {
                // Leaflet pomija setView w trakcie animacji zoomu (np. po poprzednim
                // wskazaniu kliknięty chwilę wcześniej wiersz) — ponawiamy na miejscu.
                zostaloProb -= 1;
                mapa.setView(cel, zoom, { animate: !bezRuchu });
                if (zrobione || nr !== nrWskazania) return;   // bez animacji moveend już otworzył
                if (!naMiejscu()) {
                    clearTimeout(timerWskazania);
                    timerWskazania = setTimeout(otworz, 700);
                    return;
                }
            }
            zrobione = true;
            porzucWskazanie();
            otworzDymek(id, 'lista', nr);
        };
        // Bez animacji (albo gdy widok się nie zmienił) mapa już stoi na miejscu.
        if (naMiejscu()) {
            otworz();
            return true;
        }
        oczekujaceWskazanie = otworz;
        mapa.on('moveend', otworz);
        // Zapas, gdyby moveend nie przyszedł (przerwana animacja, ukryta karta).
        timerWskazania = setTimeout(otworz, 700);
        return true;
    }

    function onSelect(cb) {
        if (typeof cb === 'function') sluchaczeWyboru.push(cb);
        return () => {
            const i = sluchaczeWyboru.indexOf(cb);
            if (i !== -1) sluchaczeWyboru.splice(i, 1);
        };
    }

    function onZmiana(cb) {
        if (typeof cb === 'function') sluchaczeZmian.push(cb);
        return () => {
            const i = sluchaczeZmian.indexOf(cb);
            if (i !== -1) sluchaczeZmian.splice(i, 1);
        };
    }

    function onBlad(cb) {
        if (typeof cb === 'function') sluchaczeBledow.push(cb);
        return () => {
            const i = sluchaczeBledow.indexOf(cb);
            if (i !== -1) sluchaczeBledow.splice(i, 1);
        };
    }

    // Widoczność: zakładka Bootstrap (shown.bs.tab) i każda zmiana rozmiaru
    // kontenera (zwinięcie panelu bocznego, zmiana układu, ukrycie zakładki).
    // (oględziny Task 8, I2) Schowana mapa (podzakładka Trasy/Flota, inna zakładka panelu)
    // ma rozmiar 0 — tylko to odnotowujemy. Po powrocie (0 → > 0) okno mogło mieć już inną
    // szerokość: invalidateSize trzyma środek mapy, a mapa nieruszana przez użytkownika od
    // ostatniego dopasowania dopasowuje się od nowa do treści widoku (trasy albo pinezki).
    function poZmianieRozmiaru() {
        if (zniszczona) return;
        if (!mapa) {
            zainicjuj();
        } else if (!maWymiary()) {
            mapaUkryta = true;
        } else if (przeciaganie) {
            odswiezPoPastylce();   // w trakcie przeciągania pilnuje tego klatka
        } else if (mapaUkryta) {
            mapaUkryta = false;
            mapa.invalidateSize({ pan: true, animate: false });
            ustawSzerokoscDymkow();
            if (!widokRuszony && !tryb) dopasujBiezacy(false);
            opiszPastylke();
        } else if (pastylkaZmienia) {
            // Proporcja listy i mapy z klawiatury / dwukliku — jak przy przeciąganiu (etap 2).
            odswiezPoPastylce();
        } else {
            // (runda 2, N9) Widoczna zmiana rozmiaru (okno, panel boczny, układ obok siebie →
            // mapa nad listą): środek zostaje na miejscu, jak w etapie 2 (nasłuch okna Leafleta,
            // teraz wyłączony). Lewy górny róg zostaje tylko przy zmianie proporcji pastylką.
            mapa.invalidateSize({ pan: true, animate: false });
            ustawSzerokoscDymkow();
            opiszPastylke();
        }
    }

    function zniszcz() {
        zniszczona = true;
        clearTimeout(timerPaska);
        clearTimeout(timerWskazania);
        if (obserwator) obserwator.disconnect();
        document.removeEventListener('keydown', naKlawisz);
        window.removeEventListener('resize', poZmianieRozmiaru);
        if (przyciskZakladki) przyciskZakladki.removeEventListener('shown.bs.tab', poZmianieRozmiaru);
        if (pasekEl) pasekEl.removeEventListener('click', klikPaska);
        zakonczPrzeciaganie();
        if (uchwyt) {
            uchwyt.removeEventListener('pointerdown', naPastylkeWDol);
            uchwyt.removeEventListener('pointermove', naPastylkeRuch);
            uchwyt.removeEventListener('pointerup', zakonczPrzeciaganie);
            uchwyt.removeEventListener('pointercancel', zakonczPrzeciaganie);
            uchwyt.removeEventListener('lostpointercapture', zakonczPrzeciaganie);
            uchwyt.removeEventListener('dblclick', przywrocDomyslnyPodzial);
        }
        if (pastylka) pastylka.removeEventListener('keydown', naPastylkeKlawisz);
        if (legendaTras) {
            legendaTras.removeEventListener('click', klikLegendyTras);
            legendaTras.removeEventListener('mouseover', najazdLegendyTras);
            legendaTras.removeEventListener('focusin', najazdLegendyTras);
            legendaTras.removeEventListener('mouseleave', zdejmijWyroznienie);
            legendaTras.removeEventListener('focusout', zdejmijWyroznienie);
        }
        // Klasa na <html> nie może przeżyć instancji (kursor i zaznaczanie całej strony).
        document.documentElement.classList.remove('lg-przeciaganie-uchwytu');
        if (mapa) {
            try { mapa.remove(); } catch (e) { /* kontener mógł już zniknąć z DOM */ }
        }
        // mapa.remove() usuwa DOM kontrolki podkładów (i jej przyciski) razem z resztą
        // warstw — tu tylko zwalniamy referencje z tego zamknięcia.
        mapa = null;
        warstwaKafelkow = null;
        kontrolkaAtrybucji = null;
        kontrolkaPodkladowEl = null;
        przelacznikGrupowania = null;
        przyciskDopasowania = null;
        pinezki = null;
        warstwaTras = null;
        trasyDane = null;
        grupyTras.clear();
        warstwyZewnetrzne.clear();
        podgladyPodkladow.clear();
        znaczniki.clear();
        zamowienia.clear();
        sluchaczeWyboru.length = 0;
        sluchaczeZmian.length = 0;
        sluchaczeBledow.length = 0;
        sluchaczeWyboruTrasy.length = 0;
        if (window.LogisticsMap === api) delete window.LogisticsMap;
    }

    const api = {
        root: root,
        render: render,
        highlight: highlight,
        onSelect: onSelect,
        onZmiana: onZmiana,
        onBlad: onBlad,
        ustawNaMapie: ustawNaMapie,
        anuluj: anulujTryb,
        zajeta: () => !!tryb,
        mapa: () => mapa,
        // Etap 3 — widok tras (logistics-routes.js).
        ustawWidok: ustawWidok,
        widok: () => widok,
        renderTrasy: renderTrasy,
        onWyborTrasy: onWyborTrasy,
        nowaWarstwaPodkladu: nowaWarstwaPodkladu,
        kolorTrasy: kolorTrasy,
        zniszcz: zniszcz,
    };

    // ── Start ───────────────────────────────────────────────────────────────

    if (pasekEl) pasekEl.addEventListener('click', klikPaska);
    // Pastylka: przechwycenie wskaźnika na rowku, więc ruch i puszczenie
    // przychodzą do niego — bez nasłuchów na document.
    if (uchwyt && pastylka && siatka) {
        uchwyt.addEventListener('pointerdown', naPastylkeWDol);
        uchwyt.addEventListener('pointermove', naPastylkeRuch);
        uchwyt.addEventListener('pointerup', zakonczPrzeciaganie);
        uchwyt.addEventListener('pointercancel', zakonczPrzeciaganie);
        uchwyt.addEventListener('lostpointercapture', zakonczPrzeciaganie);
        uchwyt.addEventListener('dblclick', przywrocDomyslnyPodzial);
        pastylka.addEventListener('keydown', naPastylkeKlawisz);
        // Zapamiętany podział PRZED utworzeniem mapy — Leaflet startuje od razu
        // w docelowym rozmiarze.
        ustawUdzial(czytajUdzial());
    }
    if (legendaTras) {
        legendaTras.addEventListener('click', klikLegendyTras);
        legendaTras.addEventListener('mouseover', najazdLegendyTras);
        legendaTras.addEventListener('focusin', najazdLegendyTras);
        legendaTras.addEventListener('mouseleave', zdejmijWyroznienie);
        legendaTras.addEventListener('focusout', zdejmijWyroznienie);
    }
    zaznaczWidok();
    renderujLegendeTras();
    document.addEventListener('keydown', naKlawisz);
    if (przyciskZakladki) przyciskZakladki.addEventListener('shown.bs.tab', poZmianieRozmiaru);
    if (window.ResizeObserver) {
        obserwator = new ResizeObserver(poZmianieRozmiaru);
        obserwator.observe(kontener);
    } else {
        window.addEventListener('resize', poZmianieRozmiaru);
    }

    window.LogisticsMap = api;
    zainicjuj();
    opiszPastylke();
    if (!mapa) pokazStanMapy('Mapa pojawi się po otwarciu zakładki.', 'is-ladowanie');
    document.dispatchEvent(new CustomEvent('logistics:mapa-gotowa', { detail: { root: root } }));
})();
