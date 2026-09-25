# -*- coding: utf-8 -*-
import os

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(KATALOG, 'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(*sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(_plik(katalog, f) for f in os.listdir(katalog) if f.endswith('.js'))


def test_szablon_laduje_leaflet_z_repo():
    html = _plik(LOG, 'templates', 'logistics', 'tab_content.html')
    assert 'vendor/leaflet/leaflet.js' in html
    assert 'vendor/leaflet-markercluster/leaflet.markercluster.js' in html
    assert 'id="logistics-map"' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_js_mapy_obsluguje_korekte_i_lokalizowanie():
    js = _js()
    for fraza in ('/geocode', '/geo/reset', "method: 'PUT'", 'basemaps.cartocdn.com',
                  'markerClusterGroup', 'window.LogisticsMap', 'bez_lokalizacji'):
        assert fraza in js, fraza
    assert 'unpkg.com' not in js and 'BaseLinker' not in js


# ─── Fala poprawek po finalnym przeglądzie (frontend) ───────────────────────
# Zachowanie w przeglądarce (przełączanie podkładu, wyścigi dymków, zapis w trakcie
# nowego trybu) sprawdza harness w przeglądarce — tu pilnujemy tego, co widać w kodzie.

def _mapa_js():
    return _plik(LOG, 'static', 'js', 'logistics-map.js')


def _lista_js():
    return _plik(LOG, 'static', 'js', 'logistics.js')


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def test_podklad_przelacza_cala_warstwe_a_nie_setUrl():
    """C1: setUrl zostawiał subdomeny OSM ('') i adres CARTO z {s} rzucał wyjątek."""
    js = _mapa_js()
    assert "subdomains: ''" not in js
    przelacz = _funkcja(js, 'przelaczPodklad')
    assert 'nowaWarstwaKafelkow(podklad)' in przelacz
    assert 'removeLayer(stara)' in przelacz
    assert 'setUrl' not in przelacz
    # Zapis wyboru dopiero po udanym dodaniu nowej warstwy.
    assert przelacz.index('nowa.addTo(mapa)') < przelacz.index('zapiszPodklad(id)')


def test_odrzucony_klucz_carto_przechodzi_raz_na_kafelki_bez_klucza():
    """UF2: 403 na kafelku z kluczem → ta sama warstwa bez klucza + ostrzeżenie; podglądy też."""
    js = _mapa_js()
    warstwa = _funkcja(js, 'nowaWarstwaKafelkow')
    assert "'tileerror'" in warstwa and "'tileload'" in warstwa
    assert 'kluczOdrzucony = true' in warstwa and 'console.warn' in warstwa
    assert 'adresPodgladu(p, true)' in warstwa
    kontrolka = _funkcja(js, 'dodajKontrolkePodkladow')
    assert "addEventListener('error'" in kontrolka and "removeEventListener('error'" in kontrolka


def test_zwykly_klik_w_wiersz_nie_przewija_strony_do_mapy():
    """I3: przewija tylko jawny przycisk pinezki (i „Ustaw na mapie”)."""
    assert 'm.highlight(id, { przewin: jawnie })' in _lista_js()
    highlight = _funkcja(_mapa_js(), 'highlight')
    assert 'if (opcje && opcje.przewin) pokazMapeNaEkranie();' in highlight
    assert highlight.count('pokazMapeNaEkranie') == 1


def test_wskazanie_ma_numer_zadania_i_zoom_z_gornym_limitem():
    """I2 + m1: spóźnione wywołania starszych wskazań nic nie otwierają; zoom nie klei się na 19."""
    js = _mapa_js()
    dymek = _funkcja(js, 'otworzDymek')
    assert 'moje !== nrWskazania' in dymek
    highlight = _funkcja(js, 'highlight')
    assert 'porzucWskazanie()' in highlight and 'nr !== nrWskazania' in highlight
    assert 'ZOOM_WSKAZANIA_MAKS' in highlight
    assert 'Math.max(mapa.getZoom(), ZOOM_WSKAZANIA), { animate' not in highlight


def test_zapis_punktu_w_trakcie_nowego_trybu_trafia_na_liste():
    """I1: wynik zapisu nie ginie, gdy logistyk zaczął już następne „Ustaw na mapie”."""
    js = _mapa_js()
    for nazwa, rodzaj in (('ustawPunkt', "'ustawiono'"), ('zapiszKorekte', "'poprawiono'")):
        tresc = _funkcja(js, nazwa)
        galaz = tresc[tresc.index('if (tryb !== biezacy) {'):]
        assert galaz.index('przyjmijZamowienie(dane.order, ' + rodzaj + ')') < galaz.index('return;'), nazwa
    assert 'if (!tryb) narysuj(' in _funkcja(js, 'przyjmijZamowienie')


def test_fokus_przezywa_przerysowanie_takze_na_przycisku_mapy():
    """m2: fokus na pinezce / „Ustaw na mapie” nie przeskakuje na checkbox."""
    js = _lista_js()
    assert "const KLASY_FOKUSU = ['lg-sposob', 'lg-na-mapie', 'lg-zaznacz'];" in js
    assert 'przywrocFokus(fokus, tbody)' in _funkcja(js, 'renderujTabele')
    assert 'przywrocFokus(fokus, tbody)' in _funkcja(js, 'odswiezWiersz')


def _css():
    return _plik(LOG, 'static', 'css', 'logistics.css')


def _szablon():
    return _plik(LOG, 'templates', 'logistics', 'tab_content.html')


def _regula_css(css, selektor):
    start = css.index(selektor + ' {')
    return css[start:css.index('}', start)]


def test_przelacznik_podkladow_bez_podpisow_z_nazwa_w_etykiecie():
    """UF6: same miniaturki; nazwa w title i aria-label, aktywny z obwódką."""
    js, css = _mapa_js(), _css()
    kontrolka = _funkcja(js, 'dodajKontrolkePodkladow')
    assert 'lg-mapa-podklad-nazwa' not in js and 'lg-mapa-podklad-nazwa' not in css
    assert "b.setAttribute('aria-label', 'Podkład mapy: ' + podklad.nazwa);" in kontrolka
    assert 'border-color' in _regula_css(css, '.logistics-tab .lg-mapa-podklad.is-aktywny,\n.logistics-tab .lg-mapa-podklad.is-aktywny:hover')


def test_stan_pustej_mapy_u_gory_a_nie_na_przelaczniku_podkladow():
    """UF1/m4: komunikat „brak pinezek” u góry, pod kontrolkami, nie na dole mapy."""
    regula = _regula_css(_css(), '.logistics-tab .lg-mapa-stan')
    assert 'top: 48px' in regula and 'bottom' not in regula


def test_grupowanie_pinezek_przelacznikiem_na_mapie():
    """UF4: klastry albo zwykła warstwa, wybór w localStorage, dymki bez zoomToShowLayer."""
    js = _mapa_js()
    assert "'logistyka.mapa.grupuj'" in js
    assert 'L.featureGroup()' in _funkcja(js, 'nowaWarstwaPinezek')
    przelacznik = _funkcja(js, 'dodajPrzelacznikGrupowania')
    assert "input.setAttribute('role', 'switch')" in przelacznik and 'Grupuj pinezki' in przelacznik
    assert 'if (!pinezki.zoomToShowLayer) {' in _funkcja(js, 'otworzDymek')
    assert 'klastry.' not in js


def test_legenda_i_opis_pinezki_objasniaja_zmieniony_adres():
    """m5: pomarańczowy „!” w legendzie mapy i w aria-label pinezki."""
    html = _szablon()
    legenda = html[html.index('class="lg-mapa-legenda"'):]
    assert 'lg-pin-znak--legenda' in legenda[:legenda.index('</div>')]
    assert 'adres zmieniony po ręcznym ustawieniu punktu' in _funkcja(_mapa_js(), 'opiszZnacznik')


def test_odnosnik_do_listy_przed_mapa():
    """m6: klawiatura przeskakuje pinezki odnośnikiem widocznym przy fokusie."""
    html = _szablon()
    assert html.index('Przejdź do listy zamówień') < html.index('id="logistics-map"')
    assert 'id="logistics-lista" tabindex="-1"' in html
    assert "case 'do-listy':" in _lista_js()
    assert ':not(:focus)' in _css()


def test_postep_geokodera_na_przycisku_zlokalizuj():
    """UF3: w toku przycisk nieaktywny, postęp w procentach (życzenie właściciela 25.09), pasek w tle, aria-label z postępem."""
    js, html, css = _lista_js(), _szablon(), _css()
    assert 'data-lg="zlokalizuj-postep"' in html and 'data-lg="zlokalizuj-liczby"' in html
    assert 'postepGeokodera(dane.geokoder_postep)' in js
    geo = _funkcja(js, 'renderujGeo')
    assert "Math.floor(100 * p.zrobione / p.wszystkie) + '%'" in geo
    assert "'Lokalizowanie adresów w tle: '" in geo and "p.zrobione + ' z ' + p.wszystkie" in geo
    assert "el('zlokalizuj-postep').style.width" in geo
    assert 'is-kreci' not in geo   # bez kręcącej się ikony — jedyny ruch to szerokość paska
    assert 'transition: width' in _regula_css(css, '.logistics-tab .lg-zlokalizuj-postep')
    postep = _funkcja(js, 'postepGeokodera')
    assert 'wszystkie <= 0' in postep and 'return null' in postep


def test_licznik_bez_lokalizacji_pokazuje_ile_w_zawezonym_widoku():
    """m3 / R12: licznik globalny + „· w widoku k”; pusty stan nie przeczy licznikowi."""
    js = _lista_js()
    assert "'· w widoku ' + bezGeoWWidoku()" in _funkcja(js, 'renderujGeo')
    pusty = _funkcja(js, 'pustyStan')
    assert 'W tym widoku wszystkie zamówienia mają punkt na mapie.' in pusty
    assert "przyciskStanu('zdejmij-filtry', 'Zdejmij filtry')" in pusty
    assert "case 'zdejmij-filtry':" in js


def test_logo_base_zamiast_zarowki():
    """UF5: PNG 32×32 w repo, 16 px w trzech miejscach, alt="" (dekoracja)."""
    import struct
    png = open(os.path.join(LOG, 'static', 'img', 'base-logo.png'), 'rb').read()
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', png[16:24]) == (32, 32)
    html, js, css = _szablon(), _lista_js(), _css()
    for tekst in (html, js, css):
        assert 'fa-lightbulb' not in tekst and 'lg-ikona--podpowiedz' not in tekst
    assert html.count("filename='img/base-logo.png'") == 3   # data-logo-base, legenda, hurt
    assert html.count('class="lg-logo-base"') == 2 and html.count('alt="" width="16" height="16"') == 2
    assert '<img class="lg-logo-base" src="\' + esc(LOGO_BASE) + \'" alt="" width="16" height="16">' in js


def test_kolumna_adres_w_dwoch_liniach():
    """UF7: „Miasto” → „Adres”: kod + miejscowość, pod spodem ulica; to samo w dymku."""
    html, js, css = _szablon(), _lista_js(), _css()
    naglowek = html[html.index('class="lg-k-adres"'):]
    assert 'data-nazwa="Adres">Adres<' in naglowek[:naglowek.index('</th>')]
    for tekst in (html, js, css):
        assert 'lg-k-miasto' not in tekst and 'lg-w-klient-miasto' not in tekst
    adres = _funkcja(js, 'liniiAdresu')
    assert "[w.kod, w.miasto].filter(Boolean).join(' ')" in adres
    assert 'title="\' + esc(w.adres) + \'"' in adres and 'lg-adres-ulica' in adres
    assert 'lg-brak-danych">brak</span>' in adres
    linia = _regula_css(css, '.logistics-tab .lg-adres-linia')
    assert 'text-overflow: ellipsis' in linia and 'min-width: 100%' in linia
    dymek = _funkcja(_mapa_js(), 'dymekHtml')
    assert 'lg-dymek-miejscowosc' in dymek and 'lg-dymek-ulica' in dymek and 'esc(z.adres)' in dymek
