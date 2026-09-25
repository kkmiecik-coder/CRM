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
 * Plik NIE zależy od logistics.js. Kontrakt (etap 3 dołoży warstwę tras):
 *   window.LogisticsMap.render(zamowienia, {dopasuj})  pinezki zamówień z `geo`
 *   window.LogisticsMap.highlight(id, {przewin})       przybliżenie + dymek (przewin: strona do mapy)
 *   window.LogisticsMap.onSelect(cb)                   cb(id | null, {zrodlo: 'mapa'|'lista'})
 *   window.LogisticsMap.onZmiana(cb)                   cb(zamowienie, rodzaj) po zapisie punktu
 *   window.LogisticsMap.ustawNaMapie(zamowienie | id)  tryb „następny klik = punkt”
 *   window.LogisticsMap.anuluj(), .zajeta(), .mapa(), .root, .zniszcz()
 * Gotowość ogłasza zdarzenie `logistics:mapa-gotowa` na document (detail.root).
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

    // Kafelek podglądu w przycisku podkładu — okolice magazynu (Bachórz), z=9.
    const PODGLAD_LAT = 49.84;
    const PODGLAD_LNG = 22.25;
    const PODGLAD_Z = 9;

    const ZOOM_WSKAZANIA = 12;      // klik w wiersz: co najmniej takie przybliżenie…
    const ZOOM_WSKAZANIA_MAKS = 15; // …i najwyżej takie (po rozsunięciu klastra mapa stoi na 19)
    const ZOOM_KOREKTY = 15;        // „Popraw lokalizację”: widać ulice i numery
    const ZOOM_DOPASOWANIA = 12;    // dopasowanie do pinezek nie wchodzi głębiej
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
    let klastry = null;              // L.MarkerClusterGroup z pinezkami zamówień
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
    const przyciskZakladki = document.getElementById('logistics-tab');

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
        const adres = adresTekst(z);

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
            (adres ? '<div class="lg-dymek-adres">' + esc(adres) + '</div>' : '') +
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
     */
    function nowaWarstwaKafelkow(podklad) {
        const warstwa = L.tileLayer(szablonKafelkow(podklad), {
            subdomains: podklad.subdomains,
            maxZoom: podklad.maxZoom,
        });
        if (zKluczem(podklad)) {
            let udane = 0;
            warstwa.on('tileload', () => { udane += 1; });
            warstwa.on('tileerror', () => {
                if (udane || kluczOdrzucony || warstwa !== warstwaKafelkow) return;
                kluczOdrzucony = true;
                console.warn('[LogisticsMap] CARTO odrzuciło klucz kafelków (np. klucz ograniczony do innej domeny). ' +
                    'Mapa pokazuje kafelki CARTO bez klucza, ze znakiem wodnym.');
                // Po bieżącym zdarzeniu — redraw w środku obsługi błędu kafelka
                // mieszałby Leafletowi stan kafelków tej samej warstwy.
                setTimeout(() => {
                    if (zniszczona || !mapa || warstwa !== warstwaKafelkow) return;
                    warstwa.setUrl(szablonKafelkow(aktywnyPodklad));   // ten sam podkład, te same subdomeny
                    podgladyPodkladow.forEach((img, id) => {
                        const p = PODKLADY.find((x) => x.id === id);
                        if (p && p.klucz) img.src = adresPodgladu(p, true);
                    });
                }, 0);
            });
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
    }

    function zaznaczAktywnyPodklad() {
        if (!kontrolkaPodkladowEl) return;
        kontrolkaPodkladowEl.querySelectorAll('[data-podklad]').forEach((b) => {
            const aktywny = b.getAttribute('data-podklad') === aktywnyPodklad.id;
            b.setAttribute('aria-pressed', aktywny ? 'true' : 'false');
            b.classList.toggle('is-aktywny', aktywny);
        });
    }

    /** Kontrolka Leafleta: rząd ilustrowanych przycisków (podgląd stylu + nazwa). */
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
                    const etykieta = L.DomUtil.create('span', 'lg-mapa-podklad-nazwa', b);
                    etykieta.textContent = podklad.nazwa;
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

    // ── Inicjalizacja (dopiero gdy kontener jest widoczny) ─────────────────

    function maWymiary() {
        return kontener.isConnected && kontener.clientWidth > 0 && kontener.clientHeight > 0;
    }

    function zainicjuj() {
        if (mapa || zniszczona || !maWymiary()) return;

        mapa = L.map(kontener, {
            attributionControl: false,
            minZoom: 5,
            maxZoom: 19,
            zoomAnimation: !bezRuchu,
            fadeAnimation: !bezRuchu,
            markerZoomAnimation: !bezRuchu,
        });
        aktywnyPodklad = PODKLADY.find((p) => p.id === czytajPodklad()) || PODKLADY[0];
        kontrolkaAtrybucji = L.control.attribution({ prefix: false }).addTo(mapa);
        kontrolkaAtrybucji.addAttribution(aktywnyPodklad.atrybucja);
        warstwaKafelkow = nowaWarstwaKafelkow(aktywnyPodklad).addTo(mapa);
        mapa.fitBounds(POLSKA, { padding: [8, 8] });

        klastry = L.markerClusterGroup({
            showCoverageOnHover: false,
            maxClusterRadius: 44,
            spiderfyOnMaxZoom: true,
            animate: !bezRuchu,
            iconCreateFunction: ikonaKlastra,
        });
        mapa.addLayer(klastry);
        warstwaEdycji = L.layerGroup().addTo(mapa);

        dodajMagazyn();
        dodajKontrolkeDopasowania();
        dodajKontrolkePodkladow();
        mapa.on('click', klikMapy);

        ukryjStanMapy();
        narysuj(ostatnie);
        if (czekaNaDopasowanie || (!dopasowanoPierwszy && znaczniki.size)) {
            dopasuj();
            dopasowanoPierwszy = true;
        }
        czekaNaDopasowanie = false;
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
                a.title = 'Pokaż wszystkie pinezki';
                a.setAttribute('aria-label', 'Pokaż wszystkie pinezki');
                a.innerHTML = '<i class="fas fa-expand" aria-hidden="true"></i>';
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.on(a, 'click', (e) => {
                    L.DomEvent.preventDefault(e);
                    dopasuj();
                });
                return div;
            },
        });
        new Kontrolka().addTo(mapa);
    }

    function dopasuj() {
        if (!mapa) return;
        const punkty = [];
        znaczniki.forEach((m) => punkty.push(m.getLatLng()));
        if (!punkty.length) {
            mapa.fitBounds(POLSKA, { padding: [8, 8], animate: !bezRuchu });
            return;
        }
        if (isFinite(magazyn.lat) && isFinite(magazyn.lng)) punkty.push(L.latLng(magazyn.lat, magazyn.lng));
        mapa.fitBounds(L.latLngBounds(punkty), { padding: [36, 36], maxZoom: ZOOM_DOPASOWANIA, animate: !bezRuchu });
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
            (z.geo && z.geo.quality === 'przyblizona' ? ', lokalizacja przybliżona' : ''));
    }

    function aktualizujZnacznik(m, z) {
        const klucz = kluczZnacznika(z);
        if (m.lgKlucz === klucz) return;
        const stary = m.getLatLng();
        const przesuniety = stary.lat !== z.geo.lat || stary.lng !== z.geo.lng;
        m.lgKlucz = klucz;
        m.options.lgSposob = kluczSposobu(z.sposob);
        if (przesuniety) {
            // markercluster nie śledzi setLatLng — zdejmujemy i dodajemy na nowo.
            const otwarty = m.isPopupOpen();
            klastry.removeLayer(m);
            m.setLatLng([z.geo.lat, z.geo.lng]);
            m.setIcon(ikonaZamowienia(z, { wybrana: wybrany === z.id }));
            klastry.addLayer(m);
            opiszZnacznik(m, z.id);
            if (otwarty) otworzDymek(z.id, 'mapa');
        } else {
            m.setIcon(ikonaZamowienia(z, { wybrana: wybrany === z.id }));
            opiszZnacznik(m, z.id);
            klastry.refreshClusters(m);
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
        if (doUsuniecia.length) klastry.removeLayers(doUsuniecia);
        if (nowe.length) klastry.addLayers(nowe);
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
        klastry.zoomToShowLayer(m, otworz);
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
        // Oryginał znika z klastrów na czas korekty; przeciągamy osobną pinezkę.
        klastry.removeLayer(m);
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
            if (zniszczona || tryb !== biezacy) return;
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
            if (zniszczona || tryb !== biezacy) return;
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
            klastry.addLayer(t.oryginal);
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
        ustawUdzial(udzial);
        zapiszUdzial(udzial);
        odswiezPoPastylce();
    }

    function przywrocDomyslnyPodzial() {
        zapiszUdzial(null);
        ustawUdzial(null);
        odswiezPoPastylce();
    }

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
            dopasuj();
            dopasowanoPierwszy = true;
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

    // Widoczność: zakładka Bootstrap (shown.bs.tab) i każda zmiana rozmiaru
    // kontenera (zwinięcie panelu bocznego, zmiana układu, ukrycie zakładki).
    function poZmianieRozmiaru() {
        if (zniszczona) return;
        if (!mapa) {
            zainicjuj();
        } else if (przeciaganie) {
            odswiezPoPastylce();   // w trakcie przeciągania pilnuje tego klatka
        } else if (maWymiary()) {
            mapa.invalidateSize({ pan: false });
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
        znaczniki.clear();
        zamowienia.clear();
        sluchaczeWyboru.length = 0;
        sluchaczeZmian.length = 0;
        if (window.LogisticsMap === api) delete window.LogisticsMap;
    }

    const api = {
        root: root,
        render: render,
        highlight: highlight,
        onSelect: onSelect,
        onZmiana: onZmiana,
        ustawNaMapie: ustawNaMapie,
        anuluj: anulujTryb,
        zajeta: () => !!tryb,
        mapa: () => mapa,
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
