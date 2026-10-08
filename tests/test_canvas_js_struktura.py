# -*- coding: utf-8 -*-
"""Struktura źródeł JS Canvy (narożniki, wycięcia, narzędzia).

W obrazie testowym NIE MA Node — sprawdzamy źródło (konwencja tests/test_arkusz_js.py).
Że geometria liczy dobrze, dowodzi krok przeglądarkowy na wspólnych przypadkach
tests/fixtures/narozniki_przypadki.json.
"""
import os
import re

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(KORZEN, 'modules', 'calculator', 'static', 'js')
SZABLON = os.path.join(KORZEN, 'modules', 'calculator', 'templates', 'calculator.html')


def _czytaj(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def _js(nazwa):
    return _czytaj(os.path.join(JS, nazwa))


def _kolejnosc_skryptow():
    return re.findall(r"filename='js/([\w./-]+\.js)'", _czytaj(SZABLON))


def test_geometria_ladowana_przed_canvasem():
    s = _kolejnosc_skryptow()
    assert s.index('shape-geometry.js') < s.index('shape-corners.js') < s.index('shape-cutouts.js') < s.index('shape-canvas.js')


def test_shape_corners_eksportuje_api():
    js = _js('shape-corners.js')
    for nazwa in ('normalize', 'hasAny', 'cornerAngle', 'geometry', 'maxCornerMm', 'maxUniformMm',
                  'clampCorners', 'contourSegments', 'flatten', 'contourArea',
                  'midpointDistance', 'valueFromMidpointDistance', 'label'):
        assert re.search(r'\b' + nazwa + r'\s*:\s*' + nazwa + r'\b', js), nazwa
    assert 'window.ShapeCorners = ShapeCorners' in js


def test_shape_cutouts_eksportuje_api():
    js = _js('shape-cutouts.js')
    for nazwa in ('normalize', 'fromHoles', 'fromShapeData', 'clone', 'ring', 'area', 'perimeterCm',
                  'bounds', 'bracketPoints', 'translate', 'roundCoords', 'scaleToBounds', 'rotate',
                  'containedIn', 'overlaps', 'invalidIndices', 'toHoles', 'pathSegments',
                  'makeEllipse', 'makeRect', 'serialize', 'newId'):
        assert re.search(r'\b' + nazwa + r'\s*:\s*' + nazwa + r'\b', js), nazwa
    assert 'window.ShapeCutouts = ShapeCutouts' in js


def test_elipsy_rysowane_bezierem_bo_canvas2svg_nie_ma_ellipse():
    # canvas2svg (vendor) nie implementuje ctx.ellipse() — eksport SVG by ją zgubił
    assert "type: 'bezier'" in _js('shape-cutouts.js')


def test_build_shape_data_przyjmuje_narozniki_i_wyciecia():
    js = _js('shape-geometry.js')
    assert 'function buildShapeData(shapeType, params, vertices, cutouts, rotation, corners)' in js
    assert 'function outerRing(shapeType, params, vertices, corners)' in js
    assert 'function calculateAreas(shapeType, params, vertices, corners, cutouts)' in js
    for nazwa in ('outerRing', 'calculateAreas'):
        assert re.search(r'\b' + nazwa + r'\s*:\s*' + nazwa + r'\b', js), nazwa


NARZEDZIA = {'select', 'direct', 'add', 'remove', 'ellipse', 'rect', 'corner', 'rotate'}


def test_narzedzia_ladowane_przed_canvasem():
    s = _kolejnosc_skryptow()
    assert s.index('shape-cutouts.js') < s.index('shape-tools.js') < s.index('shape-canvas.js')


def test_shape_tools_definiuje_identyfikatory_narzedzi():
    js = _js('shape-tools.js')
    ids = set(re.findall(r"'(\w+)'", re.search(r'var IDS = \[([^\]]+)\]', js).group(1)))
    assert ids == NARZEDZIA
    assert 'window.ShapeTools = ShapeTools' in js


def test_canvas_bez_starego_stanu_holes():
    js = _js('shape-canvas.js')
    assert 'state.holes' not in js
    assert 'state.cutouts' in js and 'state.corners' in js


def test_destroy_zdejmuje_nasluchy_z_canvasu():
    # Bez tego każde ponowne utworzenie Canvy dokłada komplet obsługi myszy
    js = _js('shape-canvas.js')
    assert 'function _on(' in js
    assert 'removeEventListener' in js
    assert 'canvasElement.addEventListener(' not in js


def test_pasek_ma_wszystkie_narzedzia():
    html = _czytaj(SZABLON)
    assert set(re.findall(r'data-shape-tool="(\w+)"', html)) == NARZEDZIA


def test_skroty_jak_w_illustratorze():
    js = _js('shape-editor.js')
    for wpis in ("v: 'select'", "a: 'direct'", "'+': 'add'", "'=': 'add'", "'-': 'remove'",
                 "l: 'ellipse'", "m: 'rect'", "n: 'corner'", "r: 'rotate'"):
        assert wpis in js, wpis
    assert "d: 'remove'" not in js


def test_widocznosc_narozników_w_panelu_oka():
    assert 'data-visibility-key="corners"' in _czytaj(SZABLON)


def test_suwak_rysunek_przy_naglowku_produkt():
    html = _czytaj(SZABLON)
    naglowek = html[html.index('class="product-data-header"'):]
    naglowek = naglowek[:naglowek.index('</div>')]
    assert '>Produkt</h2>' in naglowek
    assert 'data-shape-canvas-toggle' in naglowek
    # Suwak dla wszystkich ról, także partnerów — bez warunku na rolę
    assert 'user_role' not in naglowek


def test_wszystkie_ksztalty_dla_wszystkich_rol():
    # Decyzja 7.10: partnerzy też widzą trójkąty, trapezy, równoległobok i wielokąt
    html = _czytaj(SZABLON)
    lista = html[html.index('data-field="shapeSelect"'):]
    lista = lista[:lista.index('</select>')]
    assert 'user_role' not in lista
    for ksztalt in ('triangle_right', 'trapezoid_symmetric', 'parallelogram', 'polygon'):
        assert 'value="' + ksztalt + '"' in lista


def test_edytor_pilnuje_widocznosci_i_poprawnosci():
    js = _js('shape-editor.js')
    for nazwa in ('_applyCanvasVisibility', 'isGeometryValid', 'hasFeatures', 'getCanvas',
                  'refreshAfterExternalChange', '_onDimInput'):
        assert nazwa in js, nazwa


def test_zapis_blokowany_przy_zlych_wycieciach():
    js = _js('save_quote.js')
    walidacja = js[js.index('function validateForm()'):js.index('function showFieldError')]
    assert 'isGeometryValid' in walidacja


def test_kopia_produktu_przywraca_ksztalt_prostokata_z_cechami():
    js = _js('calculator-products.js')
    assert "if (sourceData.shape && sourceData.shape !== 'rectangular') {" not in js
    assert 'restore(sourceData.shape, sourceData.shapeData)' in js


def test_wymiary_z_pol_na_canve_tylko_dodatnie_a_z_cechami_po_change():
    # Pusty/zerowy wymiar zerowałby wierzchołki i kasował narożniki; wartości pośrednie
    # przy pisaniu przycinałyby je bez odwrotu
    js = _js('shape-editor.js')
    blok = js[js.index('function _onDimInput'):js.index('function _afterCanvasChange')]
    assert '_nonZeroInputs()' in blok
    assert "e.type === 'change'" in blok
    assert '_hasFeatures()' in blok
    assert 'canvas.setOuterParams(_paramsFromInputs())' not in js
    assert "addEventListener('change', _onDimInput)" in js


def test_init_normalizuje_stan_sklonowanego_formularza():
    js = _js('shape-editor.js')
    koniec = js[js.index('function _buildShapeData'):]
    koniec = koniec[:re.search(r'return \{\s+setShape', koniec).start()]
    assert '_applyCanvasVisibility();' in koniec
    assert '_updateValidity();' in koniec


def test_zwykly_prostokat_i_kolo_nie_zalezy_od_suwaka():
    js = _js('shape-editor.js')
    # dane kształtu: gałąź Canvy tylko dla kształtów nietypowych albo z cechami
    budowa = js[js.index('function _buildShapeData'):js.index('// Zwykły prostokąt/koło (z rysunkiem czy bez) — dokładnie')]
    assert '!_isSimpleShape(currentShape) || canvas.hasFeatures()' in budowa
    # currentParams nie jest nadpisywane wymiarami prostokąta/koła
    wczytanie = js[js.index('function _loadSimpleShapeIntoCanvas'):js.index('function _loadDefaultShapeIntoCanvas')]
    assert 'currentParams =' not in wczytanie
    assert 'currentParams =' not in js[js.index('function _onDimInput'):js.index('function _afterCanvasChange')]
    zmiana_z_canvy = js[js.index('function _onCanvasParamsChange'):js.index('function _onCanvasShapeTypeChange')]
    assert 'if (!_isSimpleShape(currentShape)) currentParams =' in zmiana_z_canvy
    # pola powierzchni tylko dla kształtu nietypowego albo z cechami
    sync = js[js.index('function _syncToMainDimensions'):js.index('var cutouts = canvas.getCutouts()')]
    assert '_isSimpleShape(currentShape) && !canvas.hasFeatures()' in sync
    # po każdej zmianie widoczności pola powierzchni są przeliczane
    widocznosc = js[js.index('function _applyCanvasVisibility'):js.index('function _syncSwitch')]
    assert '_syncToMainDimensions()' in widocznosc


def test_isupdating_zwalniane_w_finally_i_suwak_po_powrocie_do_prostokata():
    js = _js('shape-editor.js')
    assert len(re.findall(r'finally\s*\{\s*isUpdating = false;', js)) == 2
    zmiana_typu = js[js.index('function _onCanvasShapeTypeChange'):js.index('function _syncToMainDimensions')]
    assert 'userWantsCanvas = true' in zmiana_typu


def test_etykieta_suwaka_kotwiczy_ukryty_input():
    css = _czytaj(os.path.join(KORZEN, 'modules', 'calculator', 'static', 'css', 'shape_canvas.css'))
    blok = css[css.index('.shape-canvas-switch {'):]
    blok = blok[:blok.index('}')]
    assert 'position: relative' in blok


# --- Zadanie 4, runda poprawek 1 ---

def _blok_narzedzia(js, naglowek):
    # Ciało funkcji najwyższego poziomu w shape-tools.js (do następnej `    function`)
    start = js.index(naglowek)
    return js[start:js.index('\n    function ', start + 1)]


def test_klamerki_wyciec_liczone_unikalnie_przy_dopasowaniu():
    # Prostokątne wycięcie ma każdą współrzędną dwa razy, elipsa cx/cy dwa razy — liczone
    # bez deduplikacji dawały margines za każdy punkt i Canva zapadała się przy kilku wycięciach
    js = _js('shape-canvas.js')
    liczenie = js[js.index('function _bracketCounts'):js.index('function _renderBbox')]
    assert 'state.cutouts' in liczenie
    assert '_pushUnique(' in liczenie
    # Jedna wspólna funkcja dla rysowania klamerek i dopasowania widoku
    assert js.count('function _pushUnique(') == 1
    rysowanie = js[js.index('function _renderBbox'):js.index('function _renderBracket')]
    assert 'function _pushUnique(' not in rysowanie
    assert '_pushUnique(' in rysowanie


def test_przeciaganie_punktu_wyciecia_przycina_narozniki_od_poczatku_gestu():
    js = _js('shape-tools.js')
    pomoc = _blok_narzedzia(js, 'function _tryCutoutEdit(')
    assert 'ShapeCorners.clampCorners(' in pomoc
    assert '_cutoutValid(api, ci)' in pomoc
    a = _blok_narzedzia(js, 'function _direct(')
    assert 'baseCorners' in a
    assert '_tryCutoutEdit(' in a
    assert '_tryCutoutEdit: _tryCutoutEdit' in js


def test_cofanie_ignorowane_w_trakcie_gestu():
    tools = _js('shape-tools.js')
    for naglowek in ('function _direct(', 'function _rotate('):
        assert 'inGesture:' in _blok_narzedzia(tools, naglowek), naglowek
    canvas = _js('shape-canvas.js')
    assert 'function _gestureInProgress()' in canvas
    for naglowek in ('function undo()', 'function redo()'):
        blok = canvas[canvas.index(naglowek):]
        blok = blok[:blok.index('\n        }\n')]
        assert '_gestureInProgress()' in blok, naglowek
    assert 'gestureInProgress: _gestureInProgress' in canvas


def test_plus_przy_limicie_wyciec_klik_poza_ksztaltem_przesuwa_widok():
    add = _blok_narzedzia(_js('shape-tools.js'), 'function _add(')
    assert add.index('if (!wolneMiejsce(x, y)) return false;') < add.index('S.cutouts.length >= ShapeCutouts.MAX_CUTOUTS')


def test_naglowek_canvasu_wymienia_zaleznosci():
    js = _js('shape-canvas.js')
    naglowek = js[:js.index('var ShapeCanvas')]
    for nazwa in ('ShapeGeometry', 'ShapeCorners', 'ShapeCutouts', 'ShapeTools'):
        assert nazwa in naglowek, nazwa


def test_wyciecie_punkt_po_punkcie_co_najmniej_1_cm():
    add = _blok_narzedzia(_js('shape-tools.js'), 'function _add(')
    zatwierdz = add[add.index('function zatwierdz'):add.index('function wolneMiejsce')]
    assert 'ShapeCutouts.MIN_SIZE_CM' in zatwierdz
    assert 'co najmniej' in zatwierdz
    assert zatwierdz.index('MIN_SIZE_CM') < zatwierdz.index('api.pushUndo()')


# --- Zadanie 4, runda poprawek 1b ---

def test_przeciaganie_wierzcholka_przycina_narozniki_obrysu_od_poczatku_gestu():
    # Jak dla wycięć: migawka narożników obrysu w onDown, przycinanie od niej w każdym ruchu
    a = _blok_narzedzia(_js('shape-tools.js'), 'function _direct(')
    assert 'baseOuterCorners = ShapeCorners.normalize(S.corners' in a
    assert 'S.corners = ShapeCorners.clampCorners(S.vertices, drag.baseOuterCorners)' in a


def test_minimum_1_cm_przy_edycji_wyciecia_tylko_w_try_cutout_edit():
    js = _js('shape-tools.js')
    pomoc = _blok_narzedzia(js, 'function _tryCutoutEdit(')
    assert 'ShapeCutouts.MIN_SIZE_CM' in pomoc
    assert 'api.showHint(' in pomoc
    # Odrzucamy tylko zmniejszenie: istniejące małe wycięcie da się przesunąć
    assert 'przed.w' in pomoc and 'przed.h' in pomoc
    # _cutoutValid zasila getInvalidCutouts i blokadę zapisu — stare wyceny z wycięciem
    # poniżej 1 cm muszą dać się zapisać, więc minimum NIE może tam trafić
    assert 'MIN_SIZE_CM' not in _blok_narzedzia(js, 'function _cutoutValid(')


def test_seria_podpowiedzi_przywraca_tekst_sprzed_pierwszej():
    js = _js('shape-canvas.js')
    blok = js[js.index('function _showHint('):js.index('function _findEdgeAt(')]
    assert 'if (!state._hintSaved)' in blok
    assert 'state._hintSaved = null' in blok


# --- Zadanie 6: narzędzie V ---

def test_narzedzie_v_jest_domyslne():
    assert "var DEFAULT_TOOL = 'select';" in _js('shape-editor.js')
    assert "activeTool: 'select'" in _js('shape-canvas.js')
    assert re.search(r'\b_select\(api\)', _js('shape-tools.js'))
    html = _czytaj(SZABLON)
    przycisk = re.search(r'<button[^>]*data-shape-tool="select"[^>]*>', html).group(0)
    assert 'hidden' not in przycisk and 'active' in przycisk
    # A przestaje być domyślne: aktywny jest tylko jeden przycisk paska
    assert 'active' not in re.search(r'<button[^>]*data-shape-tool="direct"[^>]*>', html).group(0)


def test_narzedzie_v_edytuje_wyciecia_wspolna_funkcja_i_zglasza_gest():
    v = _blok_narzedzia(_js('shape-tools.js'), 'function _select(')
    # Walidacja, minimum 1 cm i narożniki od początku gestu — tylko przez _tryCutoutEdit
    assert '_tryCutoutEdit(' in v
    assert '_cutoutValid(' not in v
    # Ctrl+Z i ↩ w trakcie przeciągania nie robią nic (api.gestureInProgress)
    assert 'inGesture: function() { return gest !== null; }' in v
    # Narożniki wielokąta z migawki z początku gestu, nie z bieżącego stanu
    assert 'gest.base.corners' in v


def test_narzedzie_v_klik_w_etykiete_odleglosci_nie_zmienia_zaznaczenia():
    # Dwuklik składa się z dwóch kliknięć: pierwsze w etykietę (poza wycięciem) nie może
    # odznaczyć wycięcia, bo etykiety znikają razem z zaznaczeniem i dwuklik nie zadziała
    v = _blok_narzedzia(_js('shape-tools.js'), 'function _select(')
    onDown = v[v.index('onDown: function'):v.index('onMove: function')]
    assert onDown.index('trafionaEtykieta(') < onDown.index("{ kind: 'outer' }")


def test_narzedzie_v_zmiana_narzedzia_czysci_zaznaczenie_i_klawisze_nie_ruszaja_gestu():
    v = _blok_narzedzia(_js('shape-tools.js'), 'function _select(')
    deaktywacja = v[v.index('onDeactivate:'):v.index('reset:')]
    assert 'S.selection = null' in deaktywacja
    # Delete w trakcie przeciągania zostawiłby gest z indeksem nieistniejącego wycięcia
    klawisze = v[v.index('onKey: function'):v.index('onDblClick: function')]
    assert klawisze.index('if (gest)') < klawisze.index("'Delete'")


# --- Zadanie 7: narzędzia L i M ---

def test_narzedzia_elipsa_i_prostokat():
    js = _js('shape-tools.js')
    assert re.search(r"ellipse:\s*_shapeDraw\(api, 'ellipse'", js)
    assert re.search(r"rect:\s*_shapeDraw\(api, 'rect'", js)
    html = _czytaj(SZABLON)
    for narzedzie in ('ellipse', 'rect'):
        przycisk = re.search(r'<button[^>]*data-shape-tool="' + narzedzie + r'"[^>]*>', html).group(0)
        assert 'hidden' not in przycisk
    assert 'traceSegments: _traceSegments' in _js('shape-canvas.js')


def test_narzedzia_l_m_nie_gubia_pozostalych_narzedzi_w_create():
    # create() zachowuje V i pozostałe narzędzia; nakładka zaznaczenia V trafia do L i M
    create = _js('shape-tools.js')
    create = create[create.index('function create(api)'):]
    for wpis in ('select: select', 'direct: _direct(api)', 'add: _add(api)',
                 'remove: _remove(api)', 'rotate: _rotate(api)'):
        assert wpis in create
    assert 'select.renderOverlay' in create


def test_narzedzia_l_m_minimum_1_cm_na_zaokraglonym_kandydacie_i_zgloszenie_gestu():
    l_m = _blok_narzedzia(_js('shape-tools.js'), 'function _shapeDraw(')
    onUp = l_m[l_m.index('onUp: function'):l_m.index('onLeave:')]
    # Minimum liczone na wyniku zaokrąglenia do 0,1 cm (z tolerancją na floaty), nie na surowej ramce
    assert 'roundCoords(' in onUp and '_wymiary(nowe)' in onUp and 'EPS_WYMIARU_CM' in onUp
    assert onUp.index('_wymiary(nowe)') < onUp.index('containedIn(') < onUp.index('overlaps(')
    # Kliknięcie bez przeciągnięcia (ramka o zerowym wymiarze) odrzucone przed roundCoords:
    # ShapeCutouts.clone gubi elipsę o półosi 0, a roundCoords rzuciłby wtedy TypeError
    assert onUp.index('b.maxX > b.minX') < onUp.index('roundCoords(')
    # Walidacja i komunikaty jak w „+” (wycięcie punkt po punkcie)
    assert 'Wycięcie musi mieścić się wewnątrz kształtu.' in onUp
    assert 'Wycięcia nie mogą się przecinać.' in onUp
    # Ctrl+Z i ↩ w trakcie przeciągania nie robią nic (api.gestureInProgress)
    assert 'inGesture: function() { return rys !== null; }' in l_m


def test_narzedzia_l_m_zmiana_narzedzia_czysci_zaznaczenie_jak_v():
    l_m = _blok_narzedzia(_js('shape-tools.js'), 'function _shapeDraw(')
    deaktywacja = l_m[l_m.index('onDeactivate:'):l_m.index('onDown:')]
    assert 'rys = null' in deaktywacja and 'S.selection = null' in deaktywacja


# --- Zadanie 6, runda poprawek 1 ---

def _v():
    return _blok_narzedzia(_js('shape-tools.js'), 'function _select(')


def test_v_zmiana_bez_efektu_nie_robi_wpisu_historii_ani_emitchange():
    # I1: drgnięcie przy kliknięciu, powrót gestu do startu, ta sama wartość w dwukliku
    v = _v()
    assert 'function _odcisk(' in _js('shape-tools.js')
    gest = v[v.index('function sprobujWGescie'):v.index('function sprobujKrok')]
    assert gest.count('_odcisk(') == 2 and 'return _odcisk(' in gest and '!== przed' in gest
    krok = v[v.index('function sprobujKrok'):v.index('function nowaRamka')]
    assert '!== przed' in krok
    # Gest, który wrócił do startu, zdejmuje swój wpis (jak _rotate przy delcie 0)
    koniec = v[v.index('function zakonczGest'):v.index('function wyczyscKursor')]
    assert 'gest.undoPushed && api.snapshot() === gest.snapshot' in koniec
    assert 'api.popUndo()' in koniec
    assert 'onUp: function() { return zakonczGest(); }' in v
    assert 'zakonczGest();' in v[v.index('onDeactivate:'):v.index('reset:')]


def test_v_czysci_kursor_przy_zmianie_narzedzia_i_resecie():
    v = _v()
    assert "api.canvas.style.cursor = ''" in v[v.index('function wyczyscKursor'):v.index('return {', v.index('function wyczyscKursor'))]
    assert 'wyczyscKursor()' in v[v.index('onDeactivate:'):v.index('reset:')]
    assert 'wyczyscKursor()' in v[v.index('reset:'):v.index('inGesture:')]


def test_v_etykiety_rozmiaru_odsuwane_od_etykiet_odleglosci():
    v = _v()
    rysuj = v[v.index('function rysujOdleglosci'):v.index('return {', v.index('function rysujOdleglosci'))]
    assert 'ramkiNachodza(' in v and 'odsunEtykiete(' in rysuj
    # Trafienia dwukliku zapisywane po odsunięciu — trafionaEtykieta trafia w to, co widać
    assert rysuj.index('odsunEtykiete(') < rysuj.index('etykiety.push(')
    assert rysuj.count('etykiety.push(') == 1


def test_v_klawisze_ze_skrotami_przegladarki_i_seria_trzymanej_strzalki():
    klawisze = _v()
    klawisze = klawisze[klawisze.index('onKey: function'):klawisze.index('onDblClick: function')]
    assert klawisze.index('e.ctrlKey || e.metaKey || e.altKey') < klawisze.index('if (gest)')
    # Wpis historii tylko przy pierwszym naciśnięciu serii (e.repeat)
    assert 'e.repeat && seriaKlawisza === e.key' in klawisze
    assert klawisze.index('e.repeat && seriaKlawisza === e.key') < klawisze.index('api.pushUndoSnapshot(snap)')


def test_podpowiedz_v_wspomina_a_do_punktow_obrysu():
    js = _js('shape-editor.js')
    assert 'A = punkty obrysu' in js[js.index('select:'):js.index('direct:')]


def test_ten_sam_wybor_narzedzia_nie_czysci_zaznaczenia():
    js = _js('shape-canvas.js')
    blok = js[js.index('function setActiveTool('):js.index('function setCornerType(')]
    assert 'if (tool === state.activeTool) return;' in blok
    assert blok.index('if (tool === state.activeTool) return;') < blok.index('stary.onDeactivate()')


def test_polosie_elipsy_zaokraglane_do_5_mm():
    # Ø 3,5 cm = półoś 1,75; do 0,1 cm wychodziło 3,4 albo 3,6. Środek i punkty nadal 0,1 cm.
    js = _js('shape-cutouts.js')
    assert 'function _round05(v) { return Math.round(v * 20) / 20; }' in js
    blok = js[js.index('function roundCoords'):js.index('function scaleToBounds')]
    assert 'k.rx = _round05(k.rx); k.ry = _round05(k.ry);' in blok
    assert 'k.cx = _round(k.cx); k.cy = _round(k.cy);' in blok


def test_jedna_definicja_kola_wsrod_elips():
    tools = _js('shape-tools.js')
    assert tools.count('function _jestKolem(') == 1
    assert '_jestKolem: _jestKolem' in tools
    # Porównanie półosi tylko w helperze; V i canvas używają go zamiast własnych progów
    assert tools.count('Math.abs(c.rx - c.ry)') == 1
    assert 'Math.abs(baza.rx - baza.ry)' not in tools
    canvas = _js('shape-canvas.js')
    assert 'ShapeTools._jestKolem(c)' in canvas and 'Math.abs(c.rx - c.ry)' not in canvas


def test_v_trafiona_etykieta_to_najblizsza_nie_pierwsza_z_listy():
    # Odsunięta etykieta rozmiaru leży ok. 20 px od etykiety odległości, a promień trafienia to 22 px
    v = _v()
    trafienie = v[v.index('function trafionaEtykieta'):v.index('function sprobujWGescie')]
    assert 'najblizej' in trafienie and 'odl < najblizej' in trafienie


# --- Zadanie 6, runda poprawek 1b ---

def test_l_m_po_narysowaniu_obsluguja_klawisze_zaznaczenia_jak_v():
    js = _js('shape-tools.js')
    create = js[js.index('function create(api)'):]
    # Klawisze V trafiają do L i M tak samo jak jego nakładka
    assert create.count('select.onKey') == 2 and create.count('select.renderOverlay') == 2
    l_m = _blok_narzedzia(js, 'function _shapeDraw(')
    assert 'klawiszeZaznaczenia' in l_m[:l_m.index('return {')]
    klawisze = l_m[l_m.index('onKey: function'):l_m.index('renderOverlay:')]
    # W trakcie rysowania bez zmian: tylko Esc anuluje, inne klawisze nieobsłużone
    rysowanie = klawisze[klawisze.index('if (rys)'):klawisze.index('return klawiszeZaznaczenia')]
    assert "e.key === 'Escape'" in rysowanie and 'anuluj()' in rysowanie and 'return false;' in rysowanie
    # Dopiero bez rysowania klawisze idą do V
    assert klawisze.index('if (rys)') < klawisze.index('klawiszeZaznaczenia(e)')


def test_komentarz_zaznaczenia_w_stanie_canvasu_wymienia_l_i_m():
    js = _js('shape-canvas.js')
    linia = [l for l in js.splitlines() if l.strip().startswith('selection: null,')][0]
    assert 'V' in linia and 'L i M' in linia


# --- Zadanie 8: synchronizacja krawędzi z rysunkiem ---

def test_synchronizacja_krawedzi_ladowana_przed_edytorem_i_krawedziami():
    s = _kolejnosc_skryptow()
    assert s.index('shape-canvas.js') < s.index('shape-edges-sync.js') < s.index('shape-editor.js')
    assert s.index('shape-edges-sync.js') < s.index('edges.js')


def test_canvas_nie_udaje_wpisywania_dlugosci():
    # Udawany input na polu Długość kasował krawędzie przy każdej zmianie rysunku
    js = _js('shape-editor.js')
    assert '_notifyBackup' not in js
    assert "new CustomEvent('shape:changed'" in js
    assert 'ShapeEdgesSync.syncForm(form)' in js


def test_backup_szkicu_slucha_zmian_rysunku():
    assert "'shape:changed'" in _js('qdraft_backup.js')


def test_edges_eksportuje_zapis_bez_modalu():
    js = _js('edges.js')
    for nazwa in ('setFormEdges', 'renderEdgesSummary'):
        assert re.search(r'\b' + nazwa + r'\b\s*[,:]', js[js.rindex('return {'):]), nazwa
    assert 'updateOpenButton: renderEdgesSummary' in js


def test_uzgodnienie_po_wczytaniu_i_kopii():
    assert 'ShapeEdgesSync.reconcileAfterRestore' in _js('quote_edit_loader.js')
    assert 'ShapeEdgesSync.reconcileAfterRestore' in _js('calculator-products.js')


# --- Zadanie 9: krawędzie wycięć w modalu i na podglądach ---

def test_modal_krawedzi_bierze_definicje_z_rysunku():
    js = _js('edges.js')
    assert 'ShapeEdgesSync.edgeDefinitions' in js
    assert 'function showCutoutGroupsForSimpleShape(' in js
    # Piony wycięć to narożniki (jak w pricing_service), nie metry bieżące
    assert "group === 'hole_vertical'" in js


def test_podglady_rysuja_wyciecia():
    js = _js('edges.js')
    assert 'function generateRectPreviewSVG(svgEl, length, width, thickness, activeEdges, shapeData)' in js
    assert 'function generateRoundPreviewSVG(svgEl, length, width, thickness, activeEdges, shapeData)' in js
    assert 'function _svgWyciec(' in js


# --- Zadanie 8, runda poprawek 1 ---

def test_unieważnianie_krawedzi_porownuje_rodziny_liter_nie_surowy_typ():
    # Trapez/trójkąt po pierwszym ruchu punktu to „polygon” z tymi samymi literami G/D/P
    js = _js('shape-edges-sync.js')
    assert 'function _rodzina(shape)' in js
    inv = js[js.index('function invalidateEntries'):js.index('function edgeDefinitions')]
    assert '_rodzina(prev.shape) === _rodzina(next.shape)' in inv
    assert 'prev.shape === next.shape' not in inv


def test_zmiana_rysunku_uruchamia_walidacje_i_podsumowanie_bez_inputu():
    ev = _js('calculator-events.js')
    assert "document.addEventListener('shape:changed'" in ev
    blok = ev[ev.index("document.addEventListener('shape:changed'"):]
    assert '_validationHandler.call(input)' in blok and 'updateGlobalSummary()' in blok
    # Udawany input kasowałby krawędzie
    assert "new Event('input'" not in blok.split('});')[0]
    edges = _js('edges.js')
    blok_edges = edges[edges.index("document.addEventListener('shape:changed'"):]
    assert 'updateButtonState(form)' in blok_edges.split('});')[0]


def test_odtworzenie_szkicu_uzgadnia_krawedzie_z_rysunkiem():
    js = _js('qdraft_backup.js')
    start = js.index('async restoreEdges(')
    metoda = js[start:js.index('startNewQuote() {', start)]
    assert 'ShapeEdgesSync.reconcileAfterRestore(form)' in metoda


def test_nowy_produkt_nie_dziedziczy_topologii_krawedzi():
    js = _js('calculator-products.js')
    assert 'delete form.dataset.edgesTopology;' in js


# --- Zadanie 11: narzędzie N (frezowanie i fazowanie przeciąganiem kropki) ---

def test_narzedzie_naroznikow_i_przelacznik_typu():
    assert re.search(r'\bcorner:\s*_corner\(api\)', _js('shape-tools.js'))
    html = _czytaj(SZABLON)
    przycisk = re.search(r'<button[^>]*data-shape-tool="corner"[^>]*>', html).group(0)
    assert 'hidden' not in przycisk
    pasek = html[html.index('data-corner-type-bar'):]
    pasek = pasek[:pasek.index('</div>')]
    assert 'data-corner-type="round"' in pasek and 'Frezowanie' in pasek
    assert 'data-corner-type="chamfer"' in pasek and 'Fazowanie' in pasek
    assert 'setCornerType' in _js('shape-editor.js')


def _n():
    return _blok_narzedzia(_js('shape-tools.js'), 'function _corner(')


def test_n_pasek_typu_widoczny_tylko_przy_narzedziu_n_i_typ_trafia_na_nowa_canve():
    js = _js('shape-editor.js')
    assert 'cornerTypeBar.hidden = (tool !== \'corner\')' in js[js.index('function _setActiveToolButton'):js.index('function _setTool')]
    ensure = js[js.index('function _ensureCanvas'):js.index('function _destroyCanvas')]
    assert ensure.index('canvas.setActiveTool(DEFAULT_TOOL);') < ensure.index('canvas.setCornerType(cornerType);')
    # Podpowiedź i skrót N już są — nie dublujemy
    assert js.count("corner: 'Przeciągnij kropkę") == 1 and js.count("n: 'corner'") == 1
    # Klon formularza z otwartym N: typ i widoczność paska wyprowadzane od zera przy init
    assert '_setCornerType(cornerType);' in js and 'if (cornerTypeBar) cornerTypeBar.hidden = true;' in js
    assert '.shape-corner-type[hidden]' in _czytaj(os.path.join(KORZEN, 'modules', 'calculator', 'static', 'css', 'shape_canvas.css'))


def test_n_zglasza_gest_i_czysci_kursor():
    n = _n()
    assert 'inGesture: function() { return drag !== null; }' in n
    assert "api.canvas.style.cursor = ''" in n
    assert 'wyczyscKursor()' in n[n.index('onDeactivate:'):n.index('onDown:')]
    assert 'wyczyscKursor()' in n[n.index('reset:'):n.index('onDown:')]


def test_n_zmiana_bez_efektu_nie_robi_wpisu_historii_ani_emitchange():
    n = _n()
    # Wpis historii i emitChange tylko, gdy narożniki pierścienia naprawdę się zmieniły
    ruch = n[n.index('onMove:'):n.index('onUp:')]
    assert '!== przed' in ruch
    assert ruch.index('!== przed') < ruch.index('api.pushUndoSnapshot(drag.snapshot)') < ruch.index('api.emitChange()')
    # Gest, który wrócił do startu, zdejmuje swój wpis (jak V i R)
    koniec = n[n.index('function zakoncz'):n.index('return {', n.index('function zakoncz'))]
    assert 'drag.undoPushed && api.snapshot() === drag.snapshot' in koniec
    assert 'api.popUndo()' in koniec
    dwuklik = n[n.index('onDblClick:'):n.index('renderOverlay:')]
    assert '!== przed' in dwuklik
    assert dwuklik.index('!== przed') < dwuklik.index('api.pushUndoSnapshot(snap)') < dwuklik.index('api.emitChange()')


def test_n_limit_z_geometrii_i_kolizja_z_wycieciami():
    n = _n()
    assert 'ShapeCorners.maxCornerMm(' in n and 'ShapeCorners.maxUniformMm(' in n
    assert 'ShapeCutouts.invalidIndices(' in n
    # Obrys koła nie ma narożników, wielokątne wycięcia w kole mają
    assert "S.shapeType !== 'circle'" in n and "c.type === 'polygon'" in n


# --- Zadanie 12: krawędzie → rysunek (modal, stare wyceny, limity narożników) ---

def test_kierunek_krawedzie_do_rysunku():
    js = _js('shape-edges-sync.js')
    for nazwa in ('cornerLetter', 'parseCornerLetter', 'pullCornersFromEdges', 'maxForLetter'):
        assert re.search(r'\b' + nazwa + r'\s*:\s*' + nazwa + r'\b', js), nazwa
    assert "['N1', 'N2', 'N4', 'N3']" in js
    zastosuj = _js('edges.js')
    zastosuj = zastosuj[zastosuj.index('function applyEdges()'):zastosuj.index('function buildBasicEdgesData')]
    assert 'pullCornersFromEdges' in zastosuj
    assert 'applyCorners' in _js('shape-editor.js')


def test_szkic_pamieta_tryb_krawedzi():
    js = _js('qdraft_backup.js')
    assert 'mode: form.dataset.edgesMode' in js
    assert 'form.dataset.edgesMode = edges.mode' in js


def test_uzgodnienie_po_wczytaniu_nie_zeruje_narozników_z_rysunku():
    # Wycena bez narożników w krawędziach (nowa, z samym `shape_data.corners`) nie może
    # stracić narożników: puste dane przeniesione na rysunek wyzerowałyby je wszystkie.
    js = _js('shape-edges-sync.js')
    pull = js[js.index('function pullCornersFromEdges'):js.index('function maxForLetter')]
    assert 'onlyIfAny' in pull
    assert 'opcje.onlyIfAny && !jakikolwiek' in pull
    uzgodnij = js[js.index('function reconcileAfterRestore'):js.index('return {', js.index('function reconcileAfterRestore'))]
    assert 'pullCornersFromEdges(form, { onlyIfAny: true })' in uzgodnij
    assert 'rememberTopology(form)' in uzgodnij
    # „Zastosuj” w modalu to jawna edycja użytkownika: zawsze przenosi (bez onlyIfAny)
    zastosuj = _js('edges.js')
    zastosuj = zastosuj[zastosuj.index('function applyEdges()'):zastosuj.index('function buildBasicEdgesData')]
    assert 'pullCornersFromEdges(state.currentForm)' in zastosuj
    assert 'onlyIfAny' not in zastosuj


def test_przeniesienie_narozników_nie_przepisuje_wpisow_krawedzi():
    # Cena krawędzi starej wyceny nie może się zmienić po wczytaniu: applyCorners nie woła
    # syncForm ani _notifyShapeChanged (tylko odświeża rysunek i pola)
    js = _js('shape-editor.js')
    start = js.index('applyCorners: function(spec)')
    metoda = js[start:js.index('showHint: function(msg)', start)]
    assert 'canvas.setAllCorners(spec)' in metoda
    assert '_afterCanvasChange()' in metoda
    assert 'syncForm' not in metoda and '_notifyShapeChanged' not in metoda
    assert 'showHint: _showHint' in _js('shape-canvas.js')


def test_modal_krawedzi_limity_i_kat_narozników():
    edges = _js('edges.js')
    lista = edges[edges.index('function renderAdvancedList()'):edges.index('function onAdvancedRowChange')]
    assert 'ShapeEdgesSync.maxForLetter(state.currentForm, def.letter, cfg.type)' in lista
    assert "(cfg.type!=='chamfer' || naroznik)?'disabled':''" in lista
    zmiana = edges[edges.index('function onAdvancedRowChange'):edges.index('function updateAdvancedPrice')]
    assert 'next.angle_value = 45' in zmiana
    assert zmiana.index('next.angle_value = 45') < zmiana.index('state.advanced.edges.set(letter, next)')


# --- Zadanie 13: rysunek → krawędzie (narożniki w wycenie, tryb zaawansowany) ---

def test_rysunek_zapisuje_narozniki_w_krawedziach():
    js = _js('shape-edges-sync.js')
    assert re.search(r'\bcornerEntries\s*:\s*cornerEntries\b', js)
    sync = js[js.index('function syncForm('):]
    sync = sync[:sync.index('\n    }\n')]
    assert 'cornerEntries(' in sync and "'advanced'" in sync


def test_zakladka_podstawowa_zablokowana_przy_naroznikach_z_rysunku():
    js = _js('edges.js')
    blok = js[js.index('function refreshBasicDisabledState()'):js.index('function advancedIsMixed()')]
    assert 'isCornerLetter' in blok


def test_wpisy_naroznikow_zachowuja_ceny_gdy_nic_sie_nie_zmienilo():
    # Wpisy z rysunku nie mają pól cenowych; bez ponownego użycia identycznych wpisów
    # każda synchronizacja wyglądałaby na zmianę i przeliczała krawędzie oraz cenę od nowa
    js = _js('shape-edges-sync.js')
    sync = js[js.index('function syncForm('):]
    sync = sync[:sync.index('\n    }\n')]
    assert '_taSamaKrawedz(' in sync
    assert '_taSamaKrawedz' in js[:js.index('function syncForm(')]


def test_zastosuj_odswieza_wpisy_naroznikow_z_rysunku_po_przycieciu():
    # Rysunek jest źródłem prawdy o narożnikach: po przeniesieniu z modalu (i przycięciu do
    # geometrii) wpisy krawędzi odtwarzamy z niego. Topologię zapamiętujemy przed syncForm,
    # inaczej nieaktualna sygnatura unieważniłaby świeżo zapisane litery.
    js = _js('edges.js')
    zastosuj = js[js.index('function applyEdges()'):js.index('function buildBasicEdgesData')]
    pull = zastosuj.index('pullCornersFromEdges(')
    pamietaj = zastosuj.index('rememberTopology(')
    sync = zastosuj.index('syncForm(state.currentForm)')
    assert pull < pamietaj < sync
    assert zastosuj.count('syncForm(') == 1


def test_wymiar_zatwierdzony_z_cechami_odswieza_wpisy_naroznikow():
    # Rysunek z narożnikami dostaje wymiar dopiero na change (narożniki przycięte) —
    # krawędzie muszą pójść za nim, bo watcher wymiarów reaguje tylko na input
    js = _js('shape-editor.js')
    blok = js[js.index('function _onDimInput'):js.index('function _afterCanvasChange')]
    assert 'ShapeEdgesSync.syncForm(form)' in blok
    assert blok.index('canvas.setOuterParams(') < blok.index('ShapeEdgesSync.syncForm(form)')


# --- Zadanie 12, runda poprawek 1 ---

def test_szkic_finalizacja_uzgadnia_krawedzie_po_restore_ksztaltu():
    # restore buduje Canvę od zera z samego shape_data i kasuje narożniki przeniesione z krawędzi
    js = _js('qdraft_backup.js')
    start = js.index('// Etap 4: Finalizacja')
    blok = js[start:js.index('this.updateProgress(100)', start)]
    assert 'editor.restore(' in blok and 'ShapeEdgesSync.reconcileAfterRestore(form)' in blok
    assert blok.index('editor.restore(') < blok.index('ShapeEdgesSync.reconcileAfterRestore(form)')


def test_apply_corners_utworzony_rysunek_zostaje_wlaczony():
    js = _js('shape-editor.js')
    start = js.index('applyCorners: function(spec)')
    metoda = js[start:js.index('showHint: function(msg)', start)]
    assert 'userWantsCanvas = true;' in metoda
    assert metoda.index('_loadSimpleShapeIntoCanvas()') < metoda.index('userWantsCanvas = true;') < metoda.index('canvas.setAllCorners(spec)')


def test_set_all_corners_przycina_rowne_narozniki_jednakowo():
    js = _js('shape-canvas.js')
    start = js.index('function setAllCorners(spec)')
    metoda = js[start:js.index('function hasFeatures()', start)]
    wyrownanie = js[js.index('function _wyrownajRowneNarozniki'):start]
    assert 'ShapeCorners.maxUniformMm(pts, wzor.type)' in wyrownanie
    # Tylko pełny zestaw jednakowych rogów; inaczej zwykłe przycinanie
    assert 'lista.length !== pts.length' in wyrownanie
    assert 'lista[i].type !== wzor.type || lista[i].r_mm !== wzor.r_mm' in wyrownanie
    # „clamped” liczone względem tego, co zażądano (przed wyrównaniem)
    assert metoda.index('var zadane = stan();') < metoda.index('_wyrownajRowneNarozniki(state.vertices') < metoda.index('_afterGeometryEdit();')
    assert '_wyrownajRowneNarozniki(c.points, c.corners)' in metoda


def test_litery_narozników_numerowane_od_jedynki():
    js = _js('shape-edges-sync.js')
    parse = js[js.index('function parseCornerLetter'):js.index('// Narożniki z danych krawędzi → rysunek')]
    assert 'Number(m[1]) >= 1 && Number(m[2]) >= 1' in parse
    assert "(m && Number(m[1]) >= 1)" in parse


# --- Zadanie 13, runda poprawek 1: blokada zakładki Podstawowy ---

def test_otwarcie_modalu_zdejmuje_blokade_zakladki_podstawowej():
    # Klasa i baner zmienia tylko refreshBasicDisabledState (z switchTab). Bez zdjęcia przy
    # wczytywaniu stanu blokada po produkcie z narożnikami przechodziłaby na kolejne produkty.
    js = _js('edges.js')
    blok = js[js.index('function loadSavedState()'):]
    blok = blok[:blok.index('// Jeśli mamy zapisany tryb advanced')]
    assert "classList.remove('edges-basic-panel-disabled')" in blok
    assert 'basicDisabledBanner.style.display' in blok
    # Nie wołamy tu refreshBasicDisabledState: stara forma basic z narożnikami zablokowałaby Podstawowy
    assert 'refreshBasicDisabledState()' not in blok


def test_zastosuj_przy_zablokowanym_podstawowym_stosuje_zaawansowana():
    # Zablokowany Podstawowy nie ma własnej konfiguracji; pusta podstawowa zdjęłaby narożniki z rysunku
    js = _js('edges.js')
    zastosuj = js[js.index('function applyEdges()'):js.index('function buildBasicEdgesData')]
    assert "state.activeTab === 'basic'" in zastosuj
    assert "elements.panelBasic?.classList.contains('edges-basic-panel-disabled')" in zastosuj
    assert "const edgesMode = podstawowyZablokowany ? 'advanced' : state.activeTab" in zastosuj
    assert 'const edgesMode = state.activeTab' not in zastosuj


def test_naglowek_synchronizacji_opisuje_oba_kierunki_narozników():
    js = _js('shape-edges-sync.js')
    naglowek = js[:js.index('var ShapeEdgesSync')]
    assert 'dołoży' not in naglowek
    assert 'cornerEntries' in naglowek and 'pullCornersFromEdges' in naglowek


# --- Poprawka końcowa (przegląd całej gałęzi), część JS ---

def test_szkic_przywraca_ksztalt_kazdego_ksztaltu_przed_krawedziami():
    # J1: prostokąt z wycięciami też dostaje rysunek przed restoreEdges — inaczej modal
    # i „Zastosuj” nie znają liter wycięć (H*) i gubią je z krawędzi
    js = _js('qdraft_backup.js')
    start = js.index('async restoreProduct(')
    metoda = js[start:js.index('async restoreFormField(', start)]
    i_restore = metoda.index('editor.restore(mappedShape')
    assert "!== 'rectangular'" not in metoda[:i_restore]
    assert i_restore < metoda.index('this.restoreEdges(form')


def test_uzgodnienie_przenosi_narozniki_tylko_dla_starych_danych():
    # J1: rysunek z jakimkolwiek narożnikiem (obrys albo wycięcie) jest źródłem prawdy
    js = _js('shape-edges-sync.js')
    start = js.index('function reconcileAfterRestore')
    uzgodnij = js[start:js.index('return {', start)]
    assert '_rysunekMaNarozniki(editor.getShapeData())' in uzgodnij
    assert uzgodnij.index('_rysunekMaNarozniki(') < uzgodnij.index('pullCornersFromEdges(form, { onlyIfAny: true })')
    assert uzgodnij.index('pullCornersFromEdges(') < uzgodnij.index('rememberTopology(form)')
    pomoc = js[js.index('function _rysunekMaNarozniki'):start]
    assert 'ShapeCorners.hasAny(sd.corners)' in pomoc
    assert "c.type === 'polygon' && ShapeCorners.hasAny(c.corners)" in pomoc


def test_pola_prostokata_ida_za_rysunkiem_bez_inputu():
    # J2: cofnięcie zmiany wymiaru prostokąta z cechami przywraca też pola (cena liczy się z pól)
    js = _js('shape-editor.js')
    blok = js[js.index('function _onCanvasParamsChange'):js.index('function _onCanvasShapeTypeChange')]
    assert "if (currentShape === 'rectangular') _rectInputsFromVertices(vertices);" in blok
    pomoc = js[js.index('function _rectInputsFromVertices'):js.index('function _loadSimpleShapeIntoCanvas')]
    assert 'lengthInput.value = l' in pomoc and 'widthInput.value = w' in pomoc
    # Bez udawanego inputu — kasowałby krawędzie
    assert 'dispatchEvent' not in pomoc


def test_dwuklik_w_wymiar_prostokata_idzie_przez_set_outer_params():
    # J4: prostokąt zostaje prostokątem; wielokąt — wierzchołek na siatce 0,1 cm
    js = _js('shape-canvas.js')
    blok = js[js.index('function _editDimensionAt'):js.index('function _findVertexAt')]
    assert 'Math.abs(newLen - pokazana) < 1e-9' in blok
    prost = blok[blok.index("if (state.shapeType === 'rectangular')"):blok.index('var skala')]
    assert "'length' : 'width'" in prost and 'setOuterParams(wymiary)' in prost
    assert '_convertToPolygonIfNeeded' not in prost
    assert '_round(state.vertices[vi][0] + oldDx * skala)' in blok


def test_migawka_historii_niesie_typ_ksztaltu():
    # J3: Ctrl+Z po +, −, A i obrocie przywraca też typ (prostokąt zamiast wielokąta)
    js = _js('shape-canvas.js')
    blok = js[js.index('function _snapshot()'):js.index('function _pushUndoSnapshot')]
    assert 'shapeType: state.shapeType' in blok
    assert 'state.onShapeTypeChange(s.shapeType)' in blok
    assert 'restoreSnapshot: _restoreSnapshot' in js


def test_a_wpis_cofania_i_konwersja_przy_pierwszej_realnej_zmianie():
    # J3: kliknięcie w punkt (także z drgnięciem myszy) nie zamienia prostokąta w wielokąt
    a = _blok_narzedzia(_js('shape-tools.js'), 'function _direct(')
    down = a[a.index('onDown:'):a.index('onMove:')]
    assert 'api.pushUndo()' not in down and 'convertToPolygonIfNeeded' not in down
    assert 'snapshot: api.snapshot()' in down and 'downSnap:' in down
    ruch = a[a.index('onMove:'):a.index('onUp:')]
    assert ruch.index('api.convertToPolygonIfNeeded()') < ruch.index('if (zmiana) {')
    assert ruch.index('if (zmiana) {') < ruch.index('zapiszUndoRaz();') < ruch.index('api.emitChange();')
    koniec = a[a.index('function zakoncz'):a.index('return {')]
    assert 'api.popUndo()' in koniec and 'api.restoreSnapshot(d.snapshot)' in koniec


def test_obrot_wracajacy_do_zera_przywraca_migawke_startu():
    r = _blok_narzedzia(_js('shape-tools.js'), 'function _rotate(')
    koniec = r[r.index('function zakoncz'):r.index('return {')]
    assert 'api.restoreSnapshot(rd.baseSnapshot)' in koniec and 'api.popUndo()' in koniec


def test_powrot_do_prostego_ksztaltu_przywraca_params_sprzed_konwersji():
    # J7: obrót tam i z powrotem (cofnięcie) nie zmienia zapisu zwykłego prostokąta
    js = _js('shape-editor.js')
    blok = js[js.index('function _onCanvasShapeTypeChange'):js.index('function _syncToMainDimensions')]
    assert 'paramsPrzedKonwersja = Object.assign({}, currentParams)' in blok
    assert 'if (paramsPrzedKonwersja) currentParams = paramsPrzedKonwersja;' in blok
    assert '_syncToMainDimensions()' in blok


def test_reczny_reset_krawedzi_zdejmuje_narozniki_z_rysunku():
    # J5: „Resetuj” = brak obróbki, także narożników; reset z docięcia = Nie rysunku nie rusza
    js = _js('edges.js')
    start = js.index("const resetBtn = e.target.closest('.edges-reset-btn');")
    blok = js[start:js.index('return;', start)]
    assert blok.index('resetEdges();') < blok.index('pullCornersFromEdges(form)') < blok.index('syncForm(form)')
    assert "form.dataset.cutToSize !== 'false'" in blok
    assert 'onlyIfAny' not in blok


def test_dociecie_nie_bez_wpisow_krawedzi_powrot_odtwarza_narozniki():
    sync = _js('shape-edges-sync.js')
    blok = sync[sync.index('function syncForm('):]
    blok = blok[:blok.index('\n    }\n')]
    assert blok.index('if (_bezDociecia(form)) return;') < blok.index('form.dataset.edgesTopology = ')
    assert "form.dataset.cutToSize === 'false'" in sync[sync.index('function _bezDociecia'):sync.index('function syncForm(')]
    cts = _js('cut_to_size.js')
    assert 'if (!wasValue && newValue && window.ShapeEdgesSync)' in cts
    assert 'window.ShapeEdgesSync.syncForm(form)' in cts


def test_wpisy_krawedzi_maja_pelna_dokladnosc_dlugosci():
    # J6: cena na ekranie (wpisy) = cena po zapisie (geometria); zaokrąglamy tylko do wyświetlania
    sync = _js('shape-edges-sync.js')
    odswiez = sync[sync.index('function refreshLengths'):sync.index('var PROSTOKAT_NAROZNIKI')]
    assert 'length_cm: dl, length_mm: dl * 10' in odswiez
    assert 'Math.round' not in odswiez
    # Szum floatów nie przepisuje krawędzi przy każdym ruchu
    assert '_taSamaDlugosc(e.length_cm, dl)' in odswiez
    assert 'EPS_DLUGOSCI_CM' in sync[sync.index('function _taSamaDlugosc'):sync.index('function refreshLengths')]
    rogi = sync[sync.index('function cornerEntries'):sync.index('function _taSamaKrawedz')]
    assert 'length_cm: thicknessCm,' in rogi and 'Math.round' not in rogi
    taka_sama = sync[sync.index('function _taSamaKrawedz'):sync.index('function _kanon')]
    assert '_taSamaDlugosc(a.length_cm, b.length_cm)' in taka_sama
    edges = _js('edges.js')
    assert not re.search(r'length_(cm|mm):\s*Math\.round', edges)


def test_zapisane_narozniki_przycinane_wzgledem_zaokraglonych_wierzcholkow():
    # J15: narożnik na limicie od dokładnych wierzchołków przekraczał zapisany (0,1 cm) bok
    js = _js('shape-geometry.js')
    blok = js[js.index('function buildShapeData('):js.index('// PUBLIC API', js.index('function buildShapeData('))]
    assert 'ShapeCorners.clampCorners(zapisaneWierzcholki, ShapeCorners.normalize(corners, vertices.length))' in blok
    assert 'vertices: zapisaneWierzcholki,' in blok
    assert "if (s.type === 'polygon') s.corners = ShapeCorners.clampCorners(s.points, s.corners);" in blok


def test_podpowiedz_w_pelnym_ekranie_i_po_destroy():
    # J8: w trybie pełnoekranowym edytor (z podpowiedzią) jest poza .quote-form
    js = _js('shape-canvas.js')
    blok = js[js.index('function _showHint('):js.index('function _findEdgeAt(')]
    assert "canvasElement.closest('[data-shape-editor]')" in blok
    assert "closest('.quote-form')" not in blok
    assert 'function _restoreHint()' in blok and 'setTimeout(_restoreHint, 3000)' in blok
    destroy = js[js.index('destroy: function() {'):]
    destroy = destroy[:destroy.index('\n            }\n')]
    assert destroy.index('clearTimeout(state._hintTimeout);') < destroy.index('_restoreHint();')


def test_resize_observer_nie_dopasowuje_widoku_w_trakcie_gestu():
    # J10
    js = _js('shape-canvas.js')
    blok = js[js.index('var resizeObserver = new ResizeObserver('):js.index('resizeObserver.observe(')]
    assert 'if (!_gestureInProgress()) fitToView();' in blok


def test_prostokat_bez_liter_bokow_na_rysunku():
    # J9: boki prostokąta w module krawędzi to A–H, litery G1–G4 myliłyby (też w SVG produkcji)
    js = _js('shape-canvas.js')
    blok = js[js.index('function _renderSingleDimension('):js.index('// SCALE INDICATOR')]
    assert "if (edgeId && state.shapeType !== 'rectangular') {" in blok


def test_etykieta_fazowania_zalezy_od_kata_rogu():
    # J14: „×45°” tylko w rogu prostym, inaczej równe ramiona „{r}×{r}”
    js = _js('shape-corners.js')
    blok = js[js.index('function label(corner, theta)'):js.index('return {', js.index('function label(corner, theta)'))]
    assert 'Math.abs(theta * 180 / Math.PI - 90) <= 0.5' in blok
    assert "corner.r_mm + '×' + corner.r_mm" in blok
    assert 'ShapeCorners.label(corner, ang.theta)' in _js('shape-canvas.js')


def test_zmiana_rysunku_oznacza_wysylke_i_zmiany_w_edycji():
    # J11: dawny udawany input uruchamiał też znacznik nieaktualnej wysyłki i wykrywanie zmian
    dostawa = _js('calculator-delivery.js')
    assert "calculator.addEventListener('shape:changed', handleShippingChange, true);" in dostawa
    loader = _js('quote_edit_loader.js')
    blok = loader[loader.index('_attachChangeListeners() {'):loader.index('takeSnapshot() {')]
    assert "calculator.addEventListener('shape:changed', (e) => scheduleCheck(e), true);" in blok


def test_zmiana_ksztaltu_z_listy_wysyla_zdarzenie_a_synchronizacja_go_nie_blokuje():
    # J12
    js = _js('shape-editor.js')
    zmiana = js[js.index('function _switchShape('):js.index('function _setupCircleSync(')]
    assert zmiana.rstrip().endswith('_emitShapeChangedEvent();\n        }')
    assert 'ShapeEdgesSync' not in zmiana and '_notifyShapeChanged' not in zmiana
    powiadom = js[js.index('function _notifyShapeChanged('):js.index('function _emitShapeChangedEvent(')]
    assert powiadom.index('try {') < powiadom.index('syncForm(form)') < powiadom.index('} finally {') < powiadom.index('_emitShapeChangedEvent();')


def test_baner_zakladki_podstawowej_z_polskimi_cudzyslowami():
    # J13
    edges = _js('edges.js')
    assert '„Zaawansowany”' in edges and '„Zaawansowany"' not in edges
    modal = _czytaj(os.path.join(KORZEN, 'modules', 'calculator', 'templates', 'partials', 'edges_modal.html'))
    assert '„Zaawansowany"' not in modal


# --- Ponowna recenzja: docięcie do wymiaru przy wczytywaniu ---

def test_wczytanie_ustawia_dociecie_przed_ksztaltem_i_wymiarami():
    # Input pól przy wczytywaniu uruchamia syncForm; przy docięciu „Nie” nie może ono zapisać
    # narożników z rysunku do krawędzi (cena na ekranie ≠ zapis bez krawędzi)
    loader = _js('quote_edit_loader.js')
    start = loader.index('async restoreProduct(form, product)')
    metoda = loader[start:loader.index('async restoreShape(', start)]
    i_cts = metoda.index('window.cutToSize.set(form')
    assert i_cts < metoda.index('this.restoreShape(') < metoda.index("this.setField(form, '[data-field=\"length\"]'")
    assert metoda.count('window.cutToSize.set(') == 1
    szkic = _js('qdraft_backup.js')
    start = szkic.index('async restoreProduct(')
    metoda = szkic[start:szkic.index('async restoreFormField(', start)]
    i_cts = metoda.index('window.cutToSize.set(form')
    assert i_cts < metoda.index('editor.restore(mappedShape') < metoda.index("this.restoreFormField(form, '[data-field=\"length\"]'")
    assert metoda.count('window.cutToSize.set(') == 1


# --- Oględziny 1 (8.10): etykieta narożnika przy narzędziu N, modal krawędzi = rysunek sekcji ---

def test_etykieta_naroznika_za_kropka_przy_aktywnym_n():
    # U1: kropka N leży tuż za środkiem łuku i zasłaniała „R60”. Przy aktywnym N (poza eksportem)
    # etykieta stoi za kropką; bez N i w SVG dla produkcji — pozycja jak dotąd
    js = _js('shape-canvas.js')
    blok = js[js.index('function _renderCornerLabels()'):js.index('function _renderAngles()')]
    assert "!state._svgExportMode && state.activeTool === 'corner'" in blok
    assert '.dotPlacement(ang.theta, corner)' in blok
    assert 'ctx.measureText(tekst).width / 2' in blok
    assert 'ShapeCorners.midpointDistance(ang.theta, corner) * state.scale + _scaled(18)' in blok
    narzedzia = _js('shape-tools.js')
    n = narzedzia[narzedzia.index('function _corner(api)'):narzedzia.index('function _dymek(')]
    assert 'dotPlacement: function(theta, corner)' in n
    # kropka rysowana i odsunięcie etykiety liczone z tej samej odległości
    assert n.count('odlegloscKropki(') == 3
    # zmiana narzędzia przerysowuje, więc etykieta wraca na miejsce po wyjściu z N
    zmiana = js[js.index('function setActiveTool(tool)'):js.index('function setCornerType(')]
    assert zmiana.rstrip().endswith('render();\n        }')


def test_modal_krawedzi_rysuje_tym_samym_rysunkiem_co_sekcja():
    # U2: modal (Podstawowy i wizualizacja Zaawansowanego) rysuje to samo co sekcja „Krawędzie”
    # (z wycięciami) — jedną funkcją _drawEdgesFigure dla prostokąta, koła i wielokąta
    js = _js('edges.js')
    for martwa in ('generateProportionalSVG', 'generateRoundSVG', 'generateCornerLabel', 'function generateLabel('):
        assert martwa not in js, martwa
    otwarcie = js[js.index('async function openModal('):js.index('function closeModal(')]
    assert otwarcie.count('renderModalSvg();') == 1
    assert 'generateShapePreviewSVG(' not in otwarcie and '_drawEdgesFigure(' not in otwarcie
    start = js.index('function renderModalSvg(')
    rys = js[start:js.index('\n    }\n', start)]
    assert '_drawEdgesFigure(elements.svg, state.currentForm, state.basic.selectedEdges);' in rys
    assert "elements.labelsGroup = elements.svg.querySelector('#edgeLabelsGroup');" in rys
    assert "classList.toggle('edges-labels-hidden', !state.labelsVisible)" in rys
    assert 'attachSvgEventListeners();' in rys
    zaaw = js[js.index('function renderAdvancedVisualization('):js.index('function setupAdvancedActions(')]
    assert '_drawEdgesFigure(svg, state.currentForm, ustawione);' in zaaw
    assert 'cloneNode' not in zaaw
    assert "'#2E7D32'" in zaaw and "'#ED6B24'" in zaaw and "'#cccccc'" in zaaw
    # Zapis z modalu: ten sam rysunek co podgląd, bez wyjątku dla prostokąta/koła z wycięciami
    zapis = js[js.index('function applyEdges('):js.index('function _wpisWyciecia(')]
    assert 'const edgesSvg = _buildEdgesSvgHeadless(state.currentForm, edgesData, edgesMode);' in zapis
    assert 'buildEdgesSvgForSave(' not in zapis
    # Koło: checkbox KG/KD przełącza linię i etykietę (rysunek sekcji ma etykiety z zaznaczeniem)
    start = js.index('function updateRoundSvgHighlights(')
    okragle = js[start:js.index('\n    }\n', start)]
    assert "['KG', 'KD'].forEach(edge => updateSvgEdge(edge, state.basic.selectedEdges.has(edge)));" in okragle
