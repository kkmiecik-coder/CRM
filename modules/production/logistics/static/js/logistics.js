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
 *                                              + bez_lokalizacji, geokoder_dziala
 *   POST {API}/orders/delivery-method          {order_ids, sposob}
 *   POST {API}/orders/<id>/handed-over         „Wydane klientowi”
 *   POST {API}/geocode                         „Zlokalizuj teraz” (wątek w tle, 202)
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
    const ODSWIEZANIE_GEO_MS = 10000; // …a co 10 s, póki geokoder pracuje w tle
    const ZEGAR_MS = 5000;          // …sprawdzane co 5 s (powrót na zakładkę po przerwie)
    // Po „Zlokalizuj teraz” wątek dopiero bierze dzierżawę — przez tyle czasu
    // przycisk zostaje „w toku”, nawet gdy pierwsza odpowiedź powie, że stoi.
    const OCHRONA_GEO_MS = 15000;
    const DEBOUNCE_SZUKAJ_MS = 300;
    // Strzałki na zamkniętym <select> w Windows od razu zmieniają wartość
    // i odpalają `change`. Krótka zwłoka wysyła tylko wartość, na której
    // użytkownik się zatrzymał — myszką nie da się jej zauważyć.
    const ZWLOKA_SELECTA_MS = 350;
    const LIMIT_HURTU = 500;        // jak LIMIT_HURTU w panel_api.py

    // ── Stan ────────────────────────────────────────────────────────────────

    const stan = {
        wiersze: [],                // ostatnia lista z API (przed filtrem etapu)
        liczniki: null,
        wstrzymaneDo: null,
        // bezGeo: filtr „Bez lokalizacji” (po stronie przeglądarki, jak etap).
        filtr: { sposob: '', etap: '', q: '', zamkniete: false, bezGeo: false },
        zaznaczone: new Set(),
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
        ochronaGeoDo: 0,            // patrz OCHRONA_GEO_MS
        naLiscie: [],               // id wierszy w tabeli — to samo widzi mapa
        wskazany: null,             // id wiersza podświetlonego z mapy
        dopasujMape: false,         // po zmianie filtra mapa dopasowuje widok
    };

    const oczekujaceSelecty = new Map();   // id → timeout zwłoki selecta
    let kontrolerListy = null;
    let numerZapytania = 0;
    let zegar = null;
    let timerSzukania = null;
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

    function widoczneWiersze() {
        const wiersze = poEtapie();
        return stan.filtr.bezGeo ? wiersze.filter((w) => !w.geo) : wiersze;
    }

    // ── Render: nagłówek, liczniki, baner, etapy ────────────────────────────

    function renderujWszystko() {
        renderujLiczniki();
        renderujBaner();
        renderujEtapy();
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
            baner.hidden = true;
            return;
        }
        const iso = stan.wstrzymaneDo;
        const kiedy = (iso.slice(0, 10) === dzisIso() ? '' : dataKrotka(iso) + ' ') + godzina(iso);
        el('baner-tekst').textContent = 'Wysyłka do Base. wstrzymana do ' + kiedy +
            ' (limit API). Zmiany zostaną wysłane automatycznie.';
        baner.hidden = false;
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

    function renderujIle() {
        const widoczne = widoczneWiersze().length;
        const wszystkie = stan.wiersze.length;
        // „7 z 24 zamówień” — po „z” dopełniacz: 1 zamówienia, reszta zamówień.
        el('ile').textContent = (stan.filtr.etap || stan.filtr.bezGeo)
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
        if (f.bezGeo && poEtapie().length) {
            tytul = 'Każde zamówienie na liście ma już punkt na mapie.';
            przycisk = przyciskStanu('bez-lokalizacji', 'Pokaż wszystkie z listy');
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
        const wybrany = stan.docelowe.get(w.id) || w.sposob;
        let opcje = '';
        // „Nie ustawiono” tylko do wyświetlenia: nie da się go wybrać ani do niego wrócić.
        if (!wybrany) opcje += '<option value="" selected disabled>' + NIE_USTAWIONO + '</option>';
        SPOSOBY.forEach((s) => {
            opcje += '<option value="' + s + '"' + (wybrany === s ? ' selected' : '') + '>' + ETYKIETY[s] + '</option>';
        });
        return '<select class="form-select form-select-sm lg-sposob' + (wybrany ? '' : ' lg-sposob--brak') + '"' +
            ' aria-label="Sposób dostawy zamówienia ' + esc(w.numer) + '"' +
            (zablokowany ? ' disabled title="' + esc(powod) + '"' : '') + '>' + opcje + '</select>';
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

        // Blokady selecta — te same warunki, na których backend odmówiłby zmiany.
        let powod = '';
        if (w.wydane) powod = 'Zamówienie wydane klientowi. Sposobu dostawy nie można już zmienić.';
        else if (anulowane) powod = 'Zamówienie anulowane.';
        else if (stan.wysylane.has(w.id)) powod = 'Zapisywanie…';

        const miasto = [w.kod, w.miasto].filter(Boolean).join(' ');
        const metoda = w.metoda_z_base
            ? '<span class="lg-metoda" title="' + esc(w.metoda_z_base) + '">' + esc(w.metoda_z_base) + '</span>'
            : '<span class="lg-metoda lg-brak-danych">brak w Base.</span>';
        let podpowiedz = '';
        if (w.podpowiedz && w.podpowiedz !== w.sposob) {
            // Żarówka zamiast słowa „Podpowiedź:” — słowo zabierało ~60 px i ucinało
            // „Transport własny”. Ta sama ikona stoi na „Przyjmij podpowiedzi z Base.”.
            const nazwa = ETYKIETY[w.podpowiedz] || w.podpowiedz;
            podpowiedz = '<span class="lg-podpowiedz' + (w.sposob ? '' : ' lg-podpowiedz--kolejka') + '"' +
                ' title="Podpowiedź z Base.: ' + esc(nazwa) + '">' +
                '<i class="fas fa-lightbulb" aria-hidden="true"></i>' +
                '<span class="visually-hidden">Podpowiedź: </span>' + esc(nazwa) + '</span>';
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
            '<td class="lg-k-zaznacz"><label class="lg-zaznacz-pole">' +
                '<input type="checkbox" class="lg-zaznacz" aria-label="Zaznacz zamówienie ' + esc(w.numer) + '"' +
                (zaznaczony ? ' checked' : '') + '></label></td>' +
            // Numer zamówienia w Base. tylko w podpowiedzi: druga linia poszerzała
            // kolumnę o ~25 px, a na 1280 px z panelem bocznym liczy się każdy piksel.
            '<td class="lg-k-numer"><div class="lg-numer-komorka">' + przyciskMapy(w) +
                '<span class="lg-numer"' +
                (w.baselinker_order_id ? ' title="Numer w Base.: ' + esc(w.baselinker_order_id) + '"' : '') + '>' +
                esc(w.numer) + '</span></div></td>' +
            '<td class="lg-k-klient"><span class="lg-klient"' + (w.klient ? ' title="' + esc(w.klient) + '"' : '') + '>' +
                (w.klient ? esc(w.klient) : '<span class="lg-brak-danych">brak nazwy</span>') + '</span>' +
                (miasto ? '<span class="lg-drugi lg-w-klient-miasto">' + esc(miasto) + '</span>' : '') +
                '<span class="lg-drugi lg-w-klient-metoda" title="' + esc(w.metoda_z_base || '') + '">Base.: ' +
                    esc(w.metoda_z_base || 'brak') + '</span>' +
                (podpowiedz ? '<span class="lg-w-klient-metoda">' + podpowiedz + '</span>' : '') + '</td>' +
            '<td class="lg-k-miasto">' + (w.miasto ? esc(w.miasto) : '<span class="lg-brak-danych">brak</span>') +
                (w.kod ? '<span class="lg-drugi lg-drugi--mono">' + esc(w.kod) + '</span>' : '') + '</td>' +
            '<td class="lg-k-metoda">' + metoda + podpowiedz + '</td>' +
            '<td class="lg-k-sposob">' + selectSposobu(w, !!powod, powod) + '</td>' +
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
            '</tr>';
    }

    function renderujTabele() {
        const widoczne = widoczneWiersze();
        // Zaznaczenie obejmuje tylko to, co widać — akcja hurtowa nie może
        // dotknąć wiersza schowanego filtrem.
        const ids = new Set(widoczne.map((w) => w.id));
        stan.zaznaczone.forEach((id) => { if (!ids.has(id)) stan.zaznaczone.delete(id); });

        // Fokus klawiatury (select albo checkbox wiersza) przeżywa przerysowanie.
        const a = document.activeElement;
        const fokus = a && tbody.contains(a) && a.closest('tr[data-id]')
            ? { id: a.closest('tr[data-id]').getAttribute('data-id'), klasa: a.classList.contains('lg-sposob') ? 'lg-sposob' : 'lg-zaznacz' }
            : null;

        tbody.innerHTML = widoczne.length ? widoczne.map(wierszHtml).join('') : pustyStan();
        tabela.classList.toggle('is-bez-geo', stan.filtr.bezGeo);
        stan.naLiscie = widoczne.map((w) => w.id);
        renderujIle();
        renderujZaznaczenie();
        przekazDoMapy();

        if (fokus) {
            const cel = tbody.querySelector('tr[data-id="' + fokus.id + '"] .' + fokus.klasa);
            if (cel && !cel.disabled) cel.focus({ preventScroll: true });
        }
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
        const fokusNaSelect = document.activeElement && tr.contains(document.activeElement) &&
            document.activeElement.classList.contains('lg-sposob');
        const tmp = document.createElement('tbody');
        tmp.innerHTML = wierszHtml(w);
        const nowyTr = tmp.firstElementChild;
        tr.replaceWith(nowyTr);
        if (blysk) nowyTr.classList.add('is-zmieniony');
        if (fokusNaSelect) {
            const s = nowyTr.querySelector('.lg-sposob');
            if (s && !s.disabled) s.focus();
        }
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
     * lista: [{numer, tekst}], ponow: przycisk „Spróbuj ponownie” (odświeża listę).
     */
    function pokazKomunikat(typ, tresc, opcje) {
        const o = opcje || {};
        if (o.klucz) usunKomunikat(o.klucz);
        const box = document.createElement('div');
        box.className = 'lg-komunikat lg-komunikat--' + typ;
        box.setAttribute('role', typ === 'blad' ? 'alert' : 'status');
        if (o.klucz) box.setAttribute('data-klucz', o.klucz);

        const ik = document.createElement('i');
        ik.className = 'fas ' + (IKONY_KOMUNIKATU[typ] || IKONY_KOMUNIKATU.info);
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

        el('komunikaty').appendChild(box);
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
                lista: wynik.bledy.map((b) => ({ numer: numer(b.order_id), tekst: b.komunikat })),
            });
        }
    }

    function nowyWynik() {
        return { zmienione: [], przepakowanie: [], bledy: [], orders: [] };
    }

    function dolacz(wynik, dane) {
        wynik.zmienione = wynik.zmienione.concat(dane.zmienione || []);
        wynik.przepakowanie = wynik.przepakowanie.concat(dane.przepakowanie || []);
        wynik.bledy = wynik.bledy.concat(dane.bledy || []);
        wynik.orders = wynik.orders.concat(dane.orders || []);
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
        if (!wartosc || wartosc === (w.sposob || '')) {
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
            pokazKomunikat('ok', 'Lokalizowanie zakończone. Bez lokalizacji: ' +
                (stan.bezLokalizacji === null ? '–' : stan.bezLokalizacji) + '.', { klucz: 'geo' });
        }
        stan.geokoderDziala = dziala;
    }

    function renderujGeo() {
        const licznik = el('bez-lokalizacji-przycisk');
        const n = stan.bezLokalizacji;
        el('bez-lokalizacji').textContent = n === null ? '–' : String(n);
        licznik.classList.toggle('is-aktywny', stan.filtr.bezGeo);
        licznik.classList.toggle('is-niepusty', !!n);
        licznik.setAttribute('aria-pressed', stan.filtr.bezGeo ? 'true' : 'false');
        // Przy zerze nie ma czego pokazać — chyba że filtr jest włączony (trzeba go zdjąć).
        licznik.disabled = !n && !stan.filtr.bezGeo;
        licznik.title = stan.filtr.bezGeo
            ? 'Pokaż wszystkie zamówienia z listy'
            : 'Pokaż na liście zamówienia bez punktu na mapie';

        // Krótki napis w toku — w wąskiej kolumnie mapy (od 300 px) licznik
        // i przycisk mają się zmieścić w jednej linii; pełne zdanie niesie
        // komunikat i podpowiedź przycisku.
        const przycisk = el('zlokalizuj');
        przycisk.disabled = stan.geokoderDziala;
        przycisk.classList.toggle('is-kreci', stan.geokoderDziala);
        przycisk.title = stan.geokoderDziala
            ? 'Lokalizowanie w tle… Lista odświeża się co 10 s.'
            : 'Znajdź na mapie adresy zamówień, które jeszcze nie mają punktu';
        el('zlokalizuj-tekst').textContent = stan.geokoderDziala ? 'Lokalizowanie…' : 'Zlokalizuj teraz';
    }

    function przelaczBezGeo() {
        stan.filtr.bezGeo = !stan.filtr.bezGeo;
        renderujGeo();
        renderujTabele();
    }

    async function zlokalizujTeraz(ciche) {
        if (stan.geokoderDziala || zniszczona) return;
        stan.geokoderDziala = true;
        stan.ochronaGeoDo = Date.now() + OCHRONA_GEO_MS;
        renderujGeo();
        try {
            await zapytanie('/geocode', { metoda: 'POST', dane: {} });
            if (zniszczona) return;
            if (!ciche) {
                pokazKomunikat('info', 'Lokalizowanie w tle… Lista odświeża się co 10 s, a licznik „Bez lokalizacji” pokazuje postęp.',
                    { klucz: 'geo' });
            }
            // Pierwsze odświeżenie za ODSWIEZANIE_GEO_MS (zegar liczy od teraz).
            stan.ostatnieOdswiezenie = Date.now();
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
        przekazDoMapy();
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
        if (!m.highlight(id) && jawnie && m.zajeta()) {
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
    function klikWiersza(e) {
        const tr = e.target.closest('tr[data-id]');
        if (!tr || !tbody.contains(tr)) return;
        if (e.target.closest('input, select, label, button, a, textarea')) return;
        const zaznaczenie = window.getSelection ? String(window.getSelection()) : '';
        if (zaznaczenie) return;
        pokazNaMapie(Number(tr.getAttribute('data-id')), false);
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
            const r = tr.getBoundingClientRect();
            const wys = window.innerHeight || document.documentElement.clientHeight;
            if (r.top < 60 || r.bottom > wys - 60) {
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
                renderujTabele();
                break;
            case 'zamknij-komunikat':
                przycisk.closest('.lg-komunikat').remove();
                break;
            case 'bez-lokalizacji':
                przelaczBezGeo();
                break;
            case 'zlokalizuj':
                zlokalizujTeraz(false);
                break;
            case 'pokaz-na-mapie':
                if (tr) pokazNaMapie(Number(tr.getAttribute('data-id')), true);
                break;
            case 'ustaw-na-mapie':
                if (tr) ustawNaMapie(Number(tr.getAttribute('data-id')));
                break;
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
            renderujTabele();
        }
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
            // Rozwinięta lista selecta zniknęłaby spod ręki razem z przerysowaną
            // tabelą. Otwarcia natywnego selecta nie da się odczytać, więc
            // czekamy na chwilę ciszy po ostatnim kliknięciu/klawiszu.
            Date.now() - ostatniaAktywnosc < CISZA_PRZED_ODSWIEZENIEM_MS;
    }

    function tik() {
        if (zniszczona || stan.pierwszeLadowanie) return;
        if (!zakladkaWidoczna() || uzytkownikPracuje()) return;
        const okres = stan.geokoderDziala ? ODSWIEZANIE_GEO_MS : ODSWIEZANIE_MS;
        if (Date.now() - stan.ostatnieOdswiezenie >= okres) wczytaj('auto');
    }

    function przyWidocznosci() {
        if (!document.hidden) tik();
    }

    function zniszcz() {
        zniszczona = true;
        clearInterval(zegar);
        clearTimeout(timerSzukania);
        oczekujaceSelecty.forEach((t) => clearTimeout(t));
        oczekujaceSelecty.clear();
        if (kontrolerListy) kontrolerListy.abort();
        document.removeEventListener('visibilitychange', przyWidocznosci);
        document.removeEventListener('logistics:mapa-gotowa', naGotowaMape);
        if (window.LogisticsTab && window.LogisticsTab.zniszcz === zniszcz) delete window.LogisticsTab;
    }

    // ── Start ───────────────────────────────────────────────────────────────

    window.LogisticsTab = {
        odswiez: () => wczytaj('uzytkownik'),
        zniszcz: zniszcz,
    };

    document.addEventListener('visibilitychange', przyWidocznosci);
    document.addEventListener('logistics:mapa-gotowa', naGotowaMape);
    polaczZMapa();
    zegar = setInterval(tik, ZEGAR_MS);
    renderujPrzelacznikZamknietych();
    wczytaj('uzytkownik');
})();
