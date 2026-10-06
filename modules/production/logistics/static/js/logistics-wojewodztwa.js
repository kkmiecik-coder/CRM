/**
 * Logistyka — filtr województw listy zamówień (runda 2 logistyki, spec 2.5).
 * modules/production/logistics/static/js/logistics-wojewodztwa.js
 *
 * Zwykły <script src> obok logistics.js. production-app-loader odtwarza tagi <script>
 * asynchronicznie, więc kolejność względem logistics.js nie jest gwarantowana — dlatego
 * rozmawiamy przez zdarzenie na document, nie przez wnętrze logistics.js:
 *   wysyłamy `logistics:wojewodztwa` {root, wybrane: ['podkarpackie', …]} po każdej zmianie
 *   wyboru (pole, „Wyczyść”). logistics.js ustawia wtedy filtr listy `woj`
 *   (GET /orders?woj=…&woj=…), przeładowuje listę (a z nią mapę) i przełącza mapę
 *   z „Trasy” na „Zamówienia”.
 * Publicznie: window.LogisticsWojewodztwa = {root, wybrane(), wyczysc(opcje), zniszcz()};
 *   wyczysc({cicho: true}) odznacza bez zdarzenia (logistics.js sam przeładowuje listę).
 *
 * Opcje (16 województw, „Zagranica”, „Bez województwa”) renderuje serwer
 * (modules/production/logistics/wojewodztwa.py). Wyboru nie zapamiętujemy (spec 2.5).
 * Panel zamyka Esc (fokus wraca na przycisk), klik obok i wyjście fokusem poza panel.
 */
(function () {
    'use strict';

    if (window.LogisticsWojewodztwa && typeof window.LogisticsWojewodztwa.zniszcz === 'function') {
        try { window.LogisticsWojewodztwa.zniszcz(); } catch (e) { /* stara instancja i tak idzie do kosza */ }
    }

    const root = document.getElementById('logistics-root');
    const kontener = root ? root.querySelector('[data-lg-woj="kontener"]') : null;
    if (!root || !kontener) return;

    const przycisk = kontener.querySelector('[data-lg-woj="przycisk"]');
    const etykieta = kontener.querySelector('[data-lg-woj="etykieta"]');
    const panel = kontener.querySelector('[data-lg-woj="panel"]');
    if (!przycisk || !etykieta || !panel) return;

    const sluchacze = new AbortController();   // jeden sygnał odpina wszystkie nasłuchy
    const naSluch = { signal: sluchacze.signal };
    let zniszczona = false;

    const pola = () => Array.from(panel.querySelectorAll('input[data-lg-woj-pole]'));

    function wybrane() {
        return pola().filter((p) => p.checked).map((p) => p.value);
    }

    function renderujPrzycisk() {
        const n = wybrane().length;
        etykieta.textContent = n ? 'Województwa (' + n + ')' : 'Województwa';
        przycisk.classList.toggle('is-aktywny', n > 0);
    }

    function ogloszZmiane() {
        if (zniszczona) return;
        document.dispatchEvent(new CustomEvent('logistics:wojewodztwa', {
            detail: { root: root, wybrane: wybrane() },
        }));
    }

    function otworz() {
        if (!panel.hidden) return;
        panel.hidden = false;
        przycisk.setAttribute('aria-expanded', 'true');
        const pierwsze = pola().find((p) => p.checked) || pola()[0];
        if (pierwsze) pierwsze.focus();
    }

    function zamknij(oddajFokus) {
        if (panel.hidden) return;
        panel.hidden = true;
        przycisk.setAttribute('aria-expanded', 'false');
        if (oddajFokus) przycisk.focus();
    }

    /** Odznacza wszystkie pola; bez `cicho` ogłasza zmianę (lista przeładuje się sama). */
    function wyczysc(opcje) {
        const o = opcje || {};
        let zmiana = false;
        pola().forEach((p) => {
            if (p.checked) {
                p.checked = false;
                zmiana = true;
            }
        });
        renderujPrzycisk();
        if (zmiana && !o.cicho) ogloszZmiane();
    }

    function naKlawisz(e) {
        if (e.key === 'Escape' && !panel.hidden) {
            e.preventDefault();
            zamknij(true);
        }
    }

    // Klik obok panelu (faza przechwytywania — mapa i lista zatrzymują część zdarzeń u siebie).
    function naWskaznik(e) {
        if (!panel.hidden && !kontener.contains(e.target)) zamknij(false);
    }

    function zniszcz() {
        zniszczona = true;
        sluchacze.abort();
        if (window.LogisticsWojewodztwa === api) delete window.LogisticsWojewodztwa;
    }

    const api = { root: root, wybrane: wybrane, wyczysc: wyczysc, zniszcz: zniszcz };

    przycisk.addEventListener('click', () => {
        if (panel.hidden) otworz(); else zamknij(false);
    }, naSluch);
    panel.addEventListener('change', (e) => {
        if (!e.target.matches('input[data-lg-woj-pole]')) return;
        renderujPrzycisk();
        ogloszZmiane();
    }, naSluch);
    panel.addEventListener('click', (e) => {
        if (e.target.closest('[data-lg-woj="wyczysc"]')) wyczysc();
    }, naSluch);
    // Wyjście fokusem (Tab) poza przycisk i panel zamyka panel.
    kontener.addEventListener('focusout', (e) => {
        if (e.relatedTarget && !kontener.contains(e.relatedTarget)) zamknij(false);
    }, naSluch);
    document.addEventListener('keydown', naKlawisz, naSluch);
    document.addEventListener('pointerdown', naWskaznik, { capture: true, signal: sluchacze.signal });

    window.LogisticsWojewodztwa = api;
    renderujPrzycisk();
})();
