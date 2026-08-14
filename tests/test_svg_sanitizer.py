"""Testy sanityzatora SVG (modules.quotes.services.svg_sanitizer).

Kontekst: kolumny quote_items_details.shape_svg / edges_svg trafiaja do bazy
verbatim, a potem sa wstrzykiwane przez innerHTML na publicznej (bez logowania)
stronie wyceny. SVG dopuszcza <script>, on*=, <foreignObject>, javascript: w
xlink:href — czyli stored XSS. Sanityzator ma to wyciac.

Kontrakt:
    sanitize_svg(raw) -> str albo None
"""
import os
import re
import sys
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.quotes.services.svg_sanitizer import (
    ALLOWED_ATTRIBUTES,
    MAX_DEPTH,
    STYLE_PROPERTIES,
    sanitize_svg,
)


# Realny zrzut z canvas2svg (modules/calculator/static/js/shape-canvas.js:1605)
# z dostrzyknietym viewBox + preserveAspectRatio (linia 1623).
CANVAS2SVG_SAMPLE = (
    '<?xml version="1.0"?>\n'
    '<svg viewBox="0 0 800 600" preserveAspectRatio="xMidYMid meet"'
    ' xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
    ' width="800" height="600">'
    '<defs/>'
    '<g fill="rgb(0,0,0)" stroke-width="2" stroke="rgb(30,64,175)"'
    ' transform="matrix(1,0,0,1,0,0)" stroke-miterlimit="10">'
    '<path fill="none" d="M 100 100 L 700 100 L 700 500 L 100 500 Z"'
    ' stroke="rgb(30,64,175)" stroke-width="2"/>'
    '</g>'
    '<g><text x="400" y="80" text-anchor="middle" font-size="16"'
    ' font-family="sans-serif" fill="rgb(15,23,42)">120 cm</text></g>'
    '</svg>'
)


# ---------------------------------------------------------------------------
# 1. Happy path — prawdziwy SVG z kalkulatora przechodzi bez uszczerbku
# ---------------------------------------------------------------------------

def test_happy_path_canvas2svg_zachowuje_wymiary_i_ksztalt():
    out = sanitize_svg(CANVAS2SVG_SAMPLE)

    assert out is not None
    assert out.startswith('<svg')
    # front potrzebuje natywnych wymiarow
    assert 'viewBox="0 0 800 600"' in out
    assert 'width="800"' in out
    assert 'height="600"' in out
    assert 'preserveAspectRatio="xMidYMid meet"' in out
    # geometria ksztaltu musi przezyc
    assert 'd="M 100 100 L 700 100 L 700 500 L 100 500 Z"' in out
    # deklaracja XML nie jest czescia wyniku (innerHTML jej nie potrzebuje)
    assert '<?xml' not in out


def test_happy_path_zachowuje_prezentacje_grupy_i_tekst():
    out = sanitize_svg(CANVAS2SVG_SAMPLE)

    assert '<g' in out and '</g>' in out
    assert '<defs' in out
    assert 'transform="matrix(1,0,0,1,0,0)"' in out
    assert 'stroke-width="2"' in out
    assert 'fill="none"' in out
    assert 'text-anchor="middle"' in out
    assert 'font-family="sans-serif"' in out
    assert '120 cm' in out
    # ZMIANA (znalezisko A3): stroke-miterlimit jest atrybutem NIEAKTYWNYM
    # (nie niesie URL-i ani kodu), a canvas2svg stawia go na kazdej grupie —
    # wycinanie go bylo nadmiarowa sanityzacja. Scislosc whitelisty pilnuje
    # test_nieznany_atrybut_usuniety.
    assert 'stroke-miterlimit="10"' in out


def test_zachowuje_defs_clippath_gradienty_z_wielkoscia_liter():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<defs>'
        '<linearGradient id="g" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>'
        '</linearGradient>'
        '<clipPath id="c"><rect x="0" y="0" width="10" height="10"/></clipPath>'
        '</defs>'
        '<circle cx="5" cy="5" r="4" clip-path="url(#c)" fill="url(#g)"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    # nazwy SVG sa case-sensitive — sanityzator musi odtworzyc kanoniczna pisownie
    assert 'linearGradient' in out
    assert 'clipPath' in out
    assert 'gradientUnits="userSpaceOnUse"' in out
    assert 'stop-color="#ffffff"' in out
    assert 'clip-path="url(#c)"' in out
    assert 'fill="url(#g)"' in out


# ---------------------------------------------------------------------------
# 2. Skrypty i elementy wykonujace kod
# ---------------------------------------------------------------------------

def test_script_z_alertem_usuniety():
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect x="1"/></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert 'script' not in out.lower()
    assert 'alert' not in out
    assert '<rect' in out  # reszta rysunku zostaje


def test_script_pisany_mieszana_wielkoscia_liter_usuniety():
    # ZMIANA (znalezisko D1): wejscie mialo wczesniej WYLACZNIE <ScRiPt>, wiec
    # po sanityzacji nie zostawal ani jeden element rysujacy — dzis to zwraca
    # None (patrz test_D1_*). Dokladamy <rect>, zeby test dalej sprawdzal to,
    # o co mu chodzi: usuwanie skryptu pisanego mieszana wielkoscia liter.
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<ScRiPt>alert(document.cookie)</ScRiPt><rect x="1"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'script' not in out.lower()
    assert 'cookie' not in out
    assert '<rect' in out


def test_script_z_prefiksem_namespace_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg">'
        '<svg:script>alert(1)</svg:script><path d="M0 0"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'script' not in out.lower()
    assert 'alert' not in out
    assert 'd="M0 0"' in out


def test_foreignobject_z_html_w_srodku_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<foreignObject width="100" height="100">'
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<img src="x" onerror="alert(1)">tekst w HTML</img>'
        '</body>'
        '</foreignObject>'
        '<rect x="1"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'foreignobject' not in out.lower()
    assert 'onerror' not in out.lower()
    assert 'alert' not in out
    assert 'tekst w HTML' not in out  # cale poddrzewo wycinamy, nie tylko tag
    assert '<rect' in out


def test_iframe_embed_object_usuniete():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<iframe src="https://evil.example/x"></iframe>'
        '<embed src="https://evil.example/x.swf"/>'
        '<object data="https://evil.example/x.html"></object>'
        '<path d="M1 1"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'iframe' not in out.lower()
    assert 'embed' not in out.lower()
    assert '<object' not in out.lower()
    assert 'evil.example' not in out
    assert 'd="M1 1"' in out


def test_animate_z_onbegin_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="0" y="0" width="10" height="10">'
        '<animate attributeName="x" onbegin="alert(1)" dur="1s"/>'
        '<set attributeName="fill" to="red" onbegin="alert(2)"/>'
        '</rect>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'animate' not in out.lower()
    assert '<set' not in out.lower()
    assert 'onbegin' not in out.lower()
    assert 'alert' not in out
    assert '<rect' in out


# ---------------------------------------------------------------------------
# 3. Atrybuty zdarzen (on*)
# ---------------------------------------------------------------------------

def test_svg_z_onload_atrybut_usuniety():
    raw = '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)" width="10" height="10"><path d="M0 0"/></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert 'onload' not in out.lower()
    assert 'alert' not in out
    # reszta svg nietknieta
    assert 'width="10"' in out
    assert 'd="M0 0"' in out


def test_rect_z_wielkimi_literami_ONLOAD_usuniety():
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" y="2" ONLOAD="alert(1)" OnClick="alert(2)"/></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert 'onload' not in out.lower()
    assert 'onclick' not in out.lower()
    assert 'alert' not in out
    assert 'x="1"' in out and 'y="2"' in out


def test_wszystkie_atrybuty_on_usuniete():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="1" cy="2" r="3" onmouseover="steal()" onfocus="steal()"'
        ' onbegin="steal()" onmouseenter="steal()" fill="#fff"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert re.search(r'\son[a-z]+\s*=', out, re.I) is None  # zaden atrybut on* nie przeszedl
    assert 'steal' not in out
    assert 'cx="1"' in out and 'fill="#fff"' in out


def test_nieznany_atrybut_usuniety():
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" data-payload="zly" formaction="x" srcdoc="y"/></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert 'data-payload' not in out
    assert 'formaction' not in out
    assert 'srcdoc' not in out
    assert 'x="1"' in out


# ---------------------------------------------------------------------------
# 4. URL-e: href / xlink:href
# ---------------------------------------------------------------------------

def test_use_z_xlink_href_javascript_atrybut_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href="javascript:alert(1)" x="5" y="5"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower()
    assert 'href' not in out.lower()
    assert '<use' in out  # sam element jest legalny, znika tylko atrybut
    assert 'x="5"' in out


def test_use_z_href_fragmentem_zachowany():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><path id="a" d="M0 0 L1 1"/></defs>'
        '<use href="#a" x="5" y="5"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href="#a"' in out
    assert '<use' in out


def test_a_z_href_javascript_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<a href="javascript:alert(1)"><text x="1" y="1">kliknij</text></a></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower()
    assert 'href' not in out.lower()
    assert 'kliknij' in out  # tresc zostaje, znika tylko opakowanie <a>


def test_href_z_encja_numeryczna_javascript_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<a href="&#106;avascript:alert(1)"><text x="1" y="1">tresc</text></a></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower()
    assert '&#106;' not in out
    assert 'alert' not in out


def test_href_z_bialymi_znakami_w_schemacie_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href="java\tscript:alert(1)"/>'
        '<use xlink:href=" JAVASCRIPT:alert(2)"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower().replace('\t', '').replace(' ', '')
    assert 'alert' not in out
    assert 'href' not in out.lower()


def test_href_zewnetrzny_usuniety_a_fragment_zostaje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<use href="https://evil.example/x.svg#a"/>'
        '<use href="#ok"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'evil.example' not in out
    assert 'href="#ok"' in out


# ---------------------------------------------------------------------------
# 5. style / CSS
# ---------------------------------------------------------------------------

def test_atrybut_style_z_url_javascript_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" style="fill:url(javascript:alert(1));width:expression(alert(2))" fill="#abc"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'style' not in out.lower()
    assert 'javascript' not in out.lower()
    assert 'expression' not in out.lower()
    assert 'fill="#abc"' in out


def test_element_style_z_css_usuniety():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<style>@import url(https://evil.example/x.css); rect{fill:red}</style>'
        '<rect x="1"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'style' not in out.lower()
    assert 'evil.example' not in out
    assert '@import' not in out
    assert '<rect' in out


# ---------------------------------------------------------------------------
# 6. Wejscia puste / bledne / ekstremalne
# ---------------------------------------------------------------------------

def test_none_zwraca_none():
    assert sanitize_svg(None) is None


def test_pusty_string_zwraca_none():
    assert sanitize_svg('') is None


def test_same_biale_znaki_zwracaja_none():
    assert sanitize_svg('   \n\t  ') is None


def test_smieciowy_xml_zwraca_none_bez_wyjatku():
    assert sanitize_svg('<svg><<< &&& nie-xml </spath') is None
    assert sanitize_svg('{"to": "json, nie svg"}') is None
    assert sanitize_svg('<html><body><p>strona</p></body></html>') is None


def test_doctype_z_definicja_encji_nie_rozwija_sie():
    # XXE / billion laughs — encja nie moze zostac rozwinieta w wyniku
    raw = (
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">&xxe;</text></svg>'
    )
    out = sanitize_svg(raw)

    assert out is None or ('passwd' not in out and 'ENTITY' not in out and '&xxe;' not in out)


def test_wejscie_nie_bedace_stringiem_zwraca_none():
    assert sanitize_svg(123) is None
    assert sanitize_svg(['<svg/>']) is None
    assert sanitize_svg({'svg': 1}) is None


def test_niedomkniete_tagi_nie_rzucaja_wyjatkiem():
    out = sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><g><path d="M0 0"')
    # nie ma kontraktu na tresc — kontrakt to "nie rzuca i zwraca str albo None"
    assert out is None or isinstance(out, str)

    out2 = sanitize_svg('<svg><rect x="1"/></g></svg>')
    assert out2 is None or isinstance(out2, str)


def test_bardzo_duze_wejscie_nie_wywala_funkcji():
    raw = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    raw += '<path d="M0 0 L1 1"/>' * 5000
    raw += '</svg>'

    out = sanitize_svg(raw)

    assert isinstance(out, str)
    assert out.count('<path') == 5000


def test_wejscie_ponad_limit_zwraca_none():
    raw = '<svg>' + ('<path d="M0 0 L1 1"/>' * 100000) + '</svg>'
    assert len(raw) > 1000000
    assert sanitize_svg(raw) is None  # twardy limit zamiast zadlawienia sie


def test_glebokie_zagniezdzenie_nie_rzuca():
    raw = '<svg xmlns="http://www.w3.org/2000/svg">' + '<g>' * 500 + '<path d="M0 0"/>' + '</g>' * 500 + '</svg>'
    out = sanitize_svg(raw)
    assert out is None or isinstance(out, str)


# ---------------------------------------------------------------------------
# 7. Wlasnosci wyniku
# ---------------------------------------------------------------------------

def test_tekst_jest_escapowany():
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">&lt;script&gt;alert(1)&lt;/script&gt;</text></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert '<script' not in out
    assert '&lt;script&gt;' in out


def test_cdata_ze_skryptem_jest_escapowany_a_nie_wykonywalny():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text x="1" y="1"><![CDATA[<script>alert(1)</script>]]></text></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    # tresc CDATA zostaje, ale jako tekst — nie jako znacznik
    assert '<script' not in out
    assert '&lt;script&gt;' in out


def test_niezadeklarowany_prefiks_namespace_zwraca_none():
    # fail-closed: wejscie nie jest poprawnym XML-em (prefiks xlink bez xmlns:xlink)
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" xlink:href="#a"/></svg>'
    assert sanitize_svg(raw) is None


def test_wynik_ma_namespace_svg_nawet_gdy_wejscie_go_nie_ma():
    out = sanitize_svg('<svg width="10" height="10"><path d="M0 0"/></svg>')

    assert out is not None
    assert 'xmlns="http://www.w3.org/2000/svg"' in out


def test_sanityzacja_jest_idempotentna():
    once = sanitize_svg(CANVAS2SVG_SAMPLE)
    twice = sanitize_svg(once)

    assert once is not None
    assert twice == once


# ===========================================================================
# 8. Regresja po audycie adwersaryjnym (znaleziska A1-A3, B1-B2, C1, D1-D3, E1)
# ===========================================================================

# Zrzut edges_svg tak, jak buduje go edges.js: CALY wyglad siedzi w inline
# style (el.style.setProperty), bo publiczna strona nie ma regul .edges-face
# ani .edges-line — te sa tylko w wewnetrznym quotes.css.
EDGES_SAMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" id="edgesSvg" viewBox="0 0 200 120">'
    '<path class="edges-face edges-face-top" d="M0 0 L100 0 L100 100 L0 100 Z'
    ' M20 20 L40 20 L40 40 L20 40 Z" fill-rule="evenodd"'
    ' style="fill: #e8e8e8; stroke: none;"/>'
    '<path class="edges-face edges-face-front" d="M0 100 L100 100 L100 110 L0 110 Z"'
    ' style="fill: #d8d8d8;"/>'
    # zaokraglona (zielona), fazowana (pomaranczowa), nieobrobiona (szara)
    '<line class="edges-line" data-edge="A" x1="0" y1="0" x2="100" y2="0"'
    ' style="fill: none; stroke: #2E7D32; stroke-width: 3px;"/>'
    '<line class="edges-line" data-edge="B" x1="100" y1="0" x2="100" y2="100"'
    ' style="fill: none; stroke: #ED6B24; stroke-width: 3px;"/>'
    '<line class="edges-line" data-edge="C" x1="0" y1="100" x2="100" y2="100"'
    ' style="fill: none; stroke: #666; stroke-width: 2px;"/>'
    '</svg>'
)


# --- A1: inline style konwertowany na atrybuty prezentacyjne ---------------

def test_A1_wyglad_edges_svg_przezywa_sanityzacje():
    out = sanitize_svg(EDGES_SAMPLE)

    assert out is not None
    # wypelnienia scian (bez nich path renderuje sie na CZARNO)
    assert 'fill="#e8e8e8"' in out
    assert 'fill="#d8d8d8"' in out
    assert 'stroke="none"' in out
    # kolory krawedzi — w trybie advanced to JEDYNY nosnik informacji,
    # ktora krawedz jest zaokraglona (#2E7D32), a ktora fazowana (#ED6B24)
    assert 'stroke="#2E7D32"' in out
    assert 'stroke="#ED6B24"' in out
    assert 'stroke="#666"' in out
    # grubosc: 3 dla obrobionych, 2 dla nieobrobionych
    assert 'stroke-width="3px"' in out
    assert 'stroke-width="2px"' in out
    # ...ale sam atrybut style nie moze wyjsc na zewnatrz
    assert ' style="' not in out


def test_A1_inline_style_wygrywa_nad_atrybutem_prezentacyjnym():
    # CSS-owo inline style ma pierwszenstwo przed atrybutem prezentacyjnym
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" fill="#000000" stroke="#111111" style="fill:#ED6B24"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'fill="#ED6B24"' in out
    assert '#000000' not in out
    # atrybut, ktorego style nie nadpisuje, zostaje nietkniety
    assert 'stroke="#111111"' in out
    assert len(re.findall(r'\sfill="', out)) == 1


def test_A1_style_nie_przepuszcza_wlasciwosci_spoza_whitelisty():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" y="2" width="3" height="4"'
        ' style="behavior:url(#x);-moz-binding:url(#y);content:\'x\';'
        'width:expression(alert(1));fill:#abc"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'behavior' not in out.lower()
    assert 'binding' not in out.lower()
    assert 'content' not in out.lower()
    assert 'expression' not in out.lower()
    assert 'fill="#abc"' in out
    # geometria nie daje sie nadpisac ze style — width nie jest wlasciwoscia
    # prezentacyjna na naszej liscie
    assert 'width="3"' in out


def test_A1_niebezpieczna_wartosc_w_style_wypada_a_reszta_zostaje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="fill:url(javascript:alert(1));'
        'stroke:#666;stroke-width:2"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower()
    assert 'alert' not in out
    assert 'fill=' not in out
    assert 'stroke="#666"' in out
    assert 'stroke-width="2"' in out


def test_A1_style_z_url_do_zasobu_zewnetrznego_wypada():
    # WeasyPrint pobiera http(s) SERWEROWO — url() spoza dokumentu nie moze przejsc
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="fill:url(https://evil.example/x.svg#g);stroke:#666"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'evil.example' not in out
    assert 'stroke="#666"' in out


def test_A1_wlasciwosci_ze_stylu_sa_podzbiorem_whitelisty_atrybutow():
    # gwarancja konstrukcyjna: przez style nie da sie wprowadzic niczego,
    # czego nie wolnoby wpisac wprost w atrybucie
    assert STYLE_PROPERTIES
    assert STYLE_PROPERTIES <= ALLOWED_ATTRIBUTES


def test_A1_atrybut_style_z_prefiksem_svg_tez_jest_konwertowany():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg">'
        '<path d="M0 0" s:style="fill:#abc;behavior:url(#x)"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'fill="#abc"' in out
    assert 'behavior' not in out.lower()
    assert ' style="' not in out


# --- A2: fill-rule / clip-rule ---------------------------------------------

def test_A2_fill_rule_evenodd_zostaje_bo_wycina_otwory():
    # bez fill-rule produkt z wycieciami pokaze sie klientowi jako LITA plyta
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0 L100 0 L100 100 L0 100 Z M20 20 L40 20 L40 40 L20 40 Z"'
        ' fill-rule="evenodd" clip-rule="evenodd"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'fill-rule="evenodd"' in out
    assert 'clip-rule="evenodd"' in out


def test_A2_fill_rule_przechodzi_takze_ze_stylu():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="fill-rule:evenodd"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'fill-rule="evenodd"' in out


def test_A2_realny_edges_svg_zachowuje_fill_rule():
    out = sanitize_svg(EDGES_SAMPLE)

    assert out is not None
    assert 'fill-rule="evenodd"' in out


# --- A3: pozostale nieaktywne atrybuty prezentacyjne ------------------------

def test_A3_nieaktywne_atrybuty_prezentacyjne_zostaja():
    # ZMIANA (znalezisko F1): visibility i display WYPADLY z tej listy. Byly tu
    # jako "nieaktywne", bo nie niosa URL-i ani kodu — ale sa jak najbardziej
    # aktywne pod katem widocznosci i potrafily wygasic caly podglad
    # (patrz test_F1_*). Reszta atrybutow ma zostac bez zmian.
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" paint-order="stroke fill markers"'
        ' vector-effect="non-scaling-stroke" stroke-miterlimit="10"/>'
        '<text x="1" y="1" font-style="italic" text-decoration="underline">A</text>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    for oczekiwany in (
        'paint-order="stroke fill markers"',
        'vector-effect="non-scaling-stroke"',
        'stroke-miterlimit="10"',
        'font-style="italic"',
        'text-decoration="underline"',
    ):
        assert oczekiwany in out


def test_A3_paint_order_przechodzi_takze_ze_stylu():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="paint-order:stroke;font-style:italic"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'paint-order="stroke"' in out
    assert 'font-style="italic"' in out


# --- B1: duplikaty atrybutow (wynik musi byc poprawnym XML) -----------------

def test_B1_duplikat_przez_wielkosc_liter_emitowany_raz():
    # w XML nazwy sa case-sensitive, wiec x i X to DWA legalne atrybuty,
    # ktore sprowadzaja sie do jednej nazwy kanonicznej
    raw = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" X="2" y="3" Y="4"/></svg>'
    out = sanitize_svg(raw)

    assert out is not None
    assert len(re.findall(r'\sx="', out)) == 1
    assert len(re.findall(r'\sy="', out)) == 1
    assert 'x="1"' in out and 'y="3"' in out  # pierwszy wygrywa
    ElementTree.fromstring(out)  # duplikat atrybutu = fatal error XML


def test_B1_duplikat_przez_drugi_prefiks_svg_emitowany_raz():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg">'
        '<path d="M0 0" fill="#abc" s:fill="#def"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert len(re.findall(r'\sfill="', out)) == 1
    assert 'fill="#abc"' in out
    assert '#def' not in out
    ElementTree.fromstring(out)


def test_B1_wynik_z_duplikatami_parsuje_sie_w_sciezce_pdf_i_jest_idempotentny():
    # WeasyPrint/cairosvg parsuje ten sam string XML-owo — niepoprawny XML
    # wywalal generowanie PDF, a sanitize_svg(sanitize_svg(x)) dawalo None
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg"'
        ' width="10" height="10">'
        '<rect x="1" X="2" y="3" fill="#abc" s:fill="#def" s:stroke="#123" stroke="#456"/>'
        '</svg>'
    )
    once = sanitize_svg(raw)

    assert once is not None
    ElementTree.fromstring(once)
    assert sanitize_svg(once) == once


# --- B2: wstrzykniecie xmlns (namespace confusion) --------------------------

def test_B2_wstrzykniete_xmlns_przez_prefiks_svg_odrzucone():
    # s:xmlns przy prefiksie zwiazanym z SVG_NS przychodzi jako {SVG_NS}xmlns
    # i po odcieciu URI zostawalo gole "xmlns" — poddrzewo wychodzilo poza SVG
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg">'
        '<g s:xmlns="http://www.w3.org/1999/xhtml"><path d="M0 0"/></g></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'xhtml' not in out
    # jedyna deklaracja przestrzeni nazw to ta doklejona przez sanityzator
    assert out.count('xmlns') == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in out
    assert 'd="M0 0"' in out


def test_B2_xmlns_nie_jest_na_whitescie_atrybutow():
    assert 'xmlns' not in ALLOWED_ATTRIBUTES
    assert 'xmlns:xlink' not in ALLOWED_ATTRIBUTES


def test_B2_deklaracja_xlink_nadal_dokladana_gdy_wynik_jej_potrzebuje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<defs><path id="a" d="M0 0"/></defs><use xlink:href="#a"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in out
    assert 'xlink:href="#a"' in out
    ElementTree.fromstring(out)


# --- C1: obejscie walidacji URL ---------------------------------------------

def test_C1_niedomkniete_url_odrzucone():
    # dla przegladarki niedomkniete url( to wciaz poprawny <url-token>,
    # a stary wzorzec url\(([^)]*)\) nie dawal ZADNEGO dopasowania -> przepustka
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" y="2" fill="url(https://evil.example/x" stroke="url(#ok)"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'evil.example' not in out
    assert 'fill=' not in out
    assert 'stroke="url(#ok)"' in out


def test_C1_niedomkniete_url_w_stylu_odrzucone():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" style="fill:url(https://evil.example/pobierz;stroke:#666"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'evil.example' not in out
    assert 'fill=' not in out
    assert 'stroke="#666"' in out


def test_C1_kazde_url_musi_byc_pelnym_fragmentem():
    zle = [
        'url(https://evil.example/x.svg#g)',     # domkniete, ale zewnetrzne
        'url("https://evil.example/x")',         # w cudzyslowie
        'url(//evil.example/x)',                 # protocol-relative
        'url(#ok)url(https://evil.example/x',    # drugie niedomkniete
        'url(url(#ok))',                         # zagniezdzone
        'url(',                                  # sam token
    ]
    for wartosc in zle:
        raw = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<rect x='1' fill='%s'/></svg>" % wartosc
        )
        out = sanitize_svg(raw)

        assert out is not None, wartosc
        assert 'evil.example' not in out, wartosc
        assert 'fill=' not in out, wartosc


def test_C1_poprawne_odwolanie_do_fragmentu_nadal_przechodzi():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" fill="url(#ok)" clip-path="url(  #c  )"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'fill="url(#ok)"' in out
    assert 'clip-path="url(  #c  )"' in out


# --- D1: pusty wynik ma byc None, nie truthy pustym <svg> -------------------

def test_D1_brak_elementow_rysujacych_zwraca_none():
    # konsument rozroznia "jest podglad" po prawdziwosci wartosci, wiec pusty
    # <svg></svg> wyrenderowalby klientowi pusta ramke
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    ) is None
    assert sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"></svg>') is None
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><title>t</title><desc>d</desc></svg>'
    ) is None
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><defs>'
        '<linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>'
        '</defs></svg>'
    ) is None
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><body/></foreignObject></svg>'
    ) is None


def test_D1_jeden_element_rysujacy_wystarczy():
    assert sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>') is not None
    assert sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect x="1"/></svg>') is not None
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><g><text x="1" y="1">A</text></g></svg>'
    ) is not None


# --- D2: przekroczenie MAX_DEPTH = odrzucenie, nie kadlubek -----------------

def test_D2_przekroczenie_max_depth_zwraca_none():
    glebokie = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        + '<g>' * (MAX_DEPTH + 5)
        + '<path d="M0 0"/>'
        + '</g>' * (MAX_DEPTH + 5)
        + '</svg>'
    )
    assert sanitize_svg(glebokie) is None


def test_D2_dokument_ponizej_limitu_przechodzi_w_calosci():
    plytkie = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        + '<g>' * 10 + '<path d="M0 0"/>' + '</g>' * 10 + '</svg>'
    )
    out = sanitize_svg(plytkie)

    assert out is not None
    assert 'd="M0 0"' in out  # geometria nie zostala po cichu obcieta


# --- D3: wyjatek z normalizacji wejscia nie moze wyjsc na zewnatrz ----------

def test_D3_wyjatek_z_len_na_wejsciu_nie_wychodzi_na_zewnatrz():
    class _WybuchowyStr(str):
        def __len__(self):
            raise RuntimeError('len() wybucha')

    zle = _WybuchowyStr('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>')
    assert sanitize_svg(zle) is None  # kontrakt: nigdy nie rzuca


def test_D3_wyjatek_z_decode_na_bajtach_nie_wychodzi_na_zewnatrz():
    class _WybuchoweBajty(bytes):
        def decode(self, *args, **kwargs):
            raise RuntimeError('decode() wybucha')

    assert sanitize_svg(_WybuchoweBajty(b'<svg/>')) is None


def test_D3_wyjatek_z_replace_na_wejsciu_nie_wychodzi_na_zewnatrz():
    class _ZlosliwyStr(str):
        def replace(self, *args, **kwargs):
            raise RuntimeError('replace() wybucha')

    assert sanitize_svg(_ZlosliwyStr('<svg><path d="M0 0"/></svg>')) is None


# --- E1: kolizje id miedzy produktami na jednej stronie ---------------------

E1_SAMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" id="edgesSvg">'
    '<defs><clipPath id="clip1"><rect x="0" y="0" width="10" height="10"/></clipPath></defs>'
    '<path id="face" d="M0 0" clip-path="url(#clip1)" fill="url(#grad)"/>'
    '<use href="#face" x="1" y="1"/>'
    '</svg>'
)


def test_E1_id_prefix_prefiksuje_identyfikatory_i_odwolania():
    out = sanitize_svg(E1_SAMPLE, id_prefix='poz2-')

    assert out is not None
    assert 'id="poz2-edgesSvg"' in out
    assert 'id="poz2-clip1"' in out
    assert 'id="poz2-face"' in out
    assert 'clip-path="url(#poz2-clip1)"' in out
    assert 'fill="url(#poz2-grad)"' in out
    assert 'href="#poz2-face"' in out
    # zadne odwolanie ani id nie zostaje bez prefiksu
    assert 'url(#clip1)' not in out
    assert 'url(#grad)' not in out
    assert '"#face"' not in out
    assert 'id="clip1"' not in out


def test_E1_prefiks_dziala_takze_dla_referencji_ze_stylu():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="fill:url(#grad)"/></svg>'
    )
    out = sanitize_svg(raw, id_prefix='poz3-')

    assert out is not None
    assert 'fill="url(#poz3-grad)"' in out


def test_E1_dwa_produkty_z_roznymi_prefiksami_nie_koliduja():
    # publiczna strona sklada wiele produktow w JEDEN dokument HTML, a url(#id)
    # rozwiazuje sie dokumentowo do pierwszego takiego id
    a = sanitize_svg(E1_SAMPLE, id_prefix='poz1-')
    b = sanitize_svg(E1_SAMPLE, id_prefix='poz2-')

    identyfikatory_a = set(re.findall(r'id="([^"]+)"', a))
    identyfikatory_b = set(re.findall(r'id="([^"]+)"', b))

    assert identyfikatory_a and identyfikatory_b
    assert not (identyfikatory_a & identyfikatory_b)
    ElementTree.fromstring('<root xmlns="http://www.w3.org/2000/svg">%s%s</root>' % (a, b))


def test_E1_bez_parametru_zachowanie_bez_zmian():
    # istniejace wywolania w routers.py nie moga zmienic wyniku
    out = sanitize_svg(E1_SAMPLE)

    assert out is not None
    assert 'id="edgesSvg"' in out
    assert 'clip-path="url(#clip1)"' in out
    assert 'href="#face"' in out


def test_E1_niepoprawny_id_prefix_zwraca_none():
    # fail-closed: ciche pominiecie prefiksu przywrociloby kolizje
    assert sanitize_svg(E1_SAMPLE, id_prefix='"><script>alert(1)</script>') is None
    assert sanitize_svg(E1_SAMPLE, id_prefix='poz 1') is None
    assert sanitize_svg(E1_SAMPLE, id_prefix='') is None
    assert sanitize_svg(E1_SAMPLE, id_prefix=123) is None
    assert sanitize_svg(E1_SAMPLE, id_prefix='1poz') is None


def test_E1_wynik_z_prefiksem_jest_stabilny_i_poprawny_xml_owo():
    once = sanitize_svg(E1_SAMPLE, id_prefix='poz1-')

    assert once is not None
    ElementTree.fromstring(once)
    # ponowny przebieg (juz bez prefiksu) niczego nie psuje
    assert sanitize_svg(once) == once


# --- Kontrola calosci: realny edges_svg w sciezce PDF -----------------------

def test_realny_edges_svg_po_sanityzacji_jest_poprawnym_xml():
    # ten sam string idzie do WeasyPrint/cairosvg, ktory parsuje XML-owo
    out = sanitize_svg(EDGES_SAMPLE, id_prefix='poz1-')

    assert out is not None
    ElementTree.fromstring(out)
    assert 'id="poz1-edgesSvg"' in out
    assert 'evil' not in out


# ===========================================================================
# 9. Regresja po drugiej rundzie audytu (znaleziska F1-F6)
# ===========================================================================

# --- F1: visibility/display nie moga wygasic podgladu ----------------------
#
# edges.js buildEdgesSvgForSave() (modules/calculator/static/js/edges.js:1778)
# ustawia svgClone.style.visibility = 'hidden' PRZED pomiarem getBBox() i
# zdejmuje ja dopiero po pomiarze. Gdy getBBox() rzuci, catch to polyka i
# zwracany outerHTML zachowuje style="position: absolute; visibility: hidden".
# Dopoki sanityzator wycinal style, znikalo to przypadkiem. Po dodaniu
# konwersji style -> atrybut prezentacyjny (znalezisko A1) visibility zaczela
# przezywac, a klient dostawal PUSTY prostokat zamiast izometrii krawedzi.

EDGES_HIDDEN_SAMPLE = (
    '<svg xmlns="http://www.w3.org/2000/svg" id="edgesSvg" viewBox="0 0 200 120"'
    ' style="position: absolute; visibility: hidden;">'
    '<path class="edges-face" d="M0 0 L100 0 L100 100 L0 100 Z"'
    ' style="fill: #e8e8e8; stroke: none;"/>'
    '<line class="edges-line" x1="0" y1="0" x2="100" y2="0"'
    ' style="fill: none; stroke: #2E7D32; stroke-width: 3px;"/>'
    '</svg>'
)


def test_F1_realny_edges_svg_z_ukryciem_w_stylu_nie_gasnie():
    out = sanitize_svg(EDGES_HIDDEN_SAMPLE)

    assert out is not None
    assert 'visibility' not in out.lower()
    assert 'hidden' not in out.lower()
    # rysunek ma zostac widoczny i kompletny
    assert 'd="M0 0 L100 0 L100 100 L0 100 Z"' in out
    assert 'fill="#e8e8e8"' in out
    assert 'stroke="#2E7D32"' in out


def test_F1_visibility_hidden_jako_atrybut_znika():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" visibility="hidden">'
        '<path d="M0 0" visibility="hidden" fill="#abc"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'visibility' not in out.lower()
    assert 'hidden' not in out.lower()
    assert 'fill="#abc"' in out


def test_F1_display_none_znika_z_atrybutu_i_ze_stylu():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" display="none" fill="#abc"/>'
        '<rect x="1" style="display:none;fill:#def"/>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'display' not in out.lower()
    assert 'none' not in out.lower().replace('stroke="none"', '')
    assert 'fill="#abc"' in out
    assert 'fill="#def"' in out


def test_F1_visibility_i_display_poza_obiema_listami():
    # gwarancja, ze nie wroca "tylnymi drzwiami" przez konwersje style -> atrybut
    for nazwa in ('visibility', 'display'):
        assert nazwa not in ALLOWED_ATTRIBUTES
        assert nazwa not in STYLE_PROPERTIES


# --- F2: url() jest ASCII case-insensitive ---------------------------------

def test_F2_url_wielkimi_literami_tez_dostaje_prefiks():
    # walidacja pracuje na wartosci zlowercasowanej, wiec URL(#grad) przechodzi
    # jako referencja fragmentowa; bez IGNORECASE w podmianie id dostawalo
    # prefiks, a odwolanie NIE — referencja wisiala albo trafiala w cudze id
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="grad"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
        '<path d="M0 0" fill="URL(#grad)" stroke="Url(#grad)"/></svg>'
    )
    out = sanitize_svg(raw, id_prefix='poz2-')

    assert out is not None
    assert 'id="poz2-grad"' in out
    assert 'fill="URL(#poz2-grad)"' in out
    assert 'stroke="Url(#poz2-grad)"' in out
    # zadne odwolanie nie zostaje bez prefiksu
    for referencja in re.findall(r'url\(\s*["\']?\s*#([^)"\'\s]+)', out, re.I):
        assert referencja.startswith('poz2-'), referencja


def test_F2_url_wielkimi_literami_ze_stylu_tez_dostaje_prefiks():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0" style="fill:URL(#grad)"/></svg>'
    )
    out = sanitize_svg(raw, id_prefix='poz3-')

    assert out is not None
    assert 'poz3-grad' in out
    assert 'URL(#grad)' not in out


# --- F3: has_drawing nie moze byc omijalny jednym <g> ----------------------

def test_F3_grupa_z_dowolna_trescia_nie_uchodzi_za_rysunek():
    # inner byl dowolnym niepustym stringiem, wiec zaliczala sie spacja,
    # luzny tekst, <title>, <desc> czy <defs> z gradientem — a konsument
    # dostawal truthy SVG bez ani jednego elementu rysujacego (pusta ramka)
    puste = [
        '<g><title>t</title></g>',
        '<g> </g>',
        '<g>.</g>',
        '<g><defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs></g>',
        '<g><desc>opis</desc></g>',
        '<g><g><g>tekst luzem</g></g></g>',
    ]
    for wnetrze in puste:
        raw = '<svg xmlns="http://www.w3.org/2000/svg">%s</svg>' % wnetrze
        assert sanitize_svg(raw) is None, wnetrze


def test_F3_grupa_z_prawdziwym_rysunkiem_nadal_przechodzi():
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><g><path d="M0 0"/></g></svg>'
    ) is not None
    assert sanitize_svg(
        '<svg xmlns="http://www.w3.org/2000/svg"><g><title>t</title><rect x="1"/></g></svg>'
    ) is not None


# --- F4: escape CSS nie moze omijac walidacji url()/schematu ---------------

def test_F4_escape_css_w_url_nie_omija_walidacji():
    # tokenizer CSS rozwija escape'y PRZED rozpoznaniem funkcji, wiec kazdy z
    # tych zapisow jest dla przegladarki poprawnym url-tokenem, choc literal
    # "url(" w nich nie wystepuje
    zle = [
        '\\75 rl(https://evil.example/x)',
        'u\\72 l(https://evil.example/x)',
        '\\000075rl(https://evil.example/x)',
        '\\75\nrl(https://evil.example/x)',
    ]
    for wartosc in zle:
        raw = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<rect x="1" fill="%s" stroke="#666"/></svg>' % wartosc
        )
        out = sanitize_svg(raw)

        assert out is not None, wartosc
        assert 'evil.example' not in out, wartosc
        assert 'fill=' not in out, wartosc
        assert 'stroke="#666"' in out, wartosc


def test_F4_escape_css_w_stylu_nie_omija_walidacji():
    # ta sama luka na NOWEJ powierzchni: _parse_style waliduje tym samym
    # _value_is_safe, wiec przez style:fill wjezdzaloby to na atrybut
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" style="fill:\\75 rl(https://evil.example/x);stroke:#666"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'evil.example' not in out
    assert 'fill=' not in out
    assert 'stroke="#666"' in out


def test_F4_escape_css_w_schemacie_javascript_nie_omija_walidacji():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" fill="j\\61 vascript:alert(1)"'
        ' style="stroke:j\\61 vascript:alert(2);stroke-width:2"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'javascript' not in out.lower()
    assert 'alert' not in out
    assert 'fill=' not in out
    assert 'stroke=' not in out
    assert 'stroke-width="2"' in out


def test_F4_escape_css_w_href_odrzucony_bo_uri_go_nie_rozwija():
    # href konsumuje parser URI, ktory escape'ow CSS NIE rozwija — "\23 a" to
    # dla niego adres wzgledny, a nie fragment "#a"
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<use href="\\23 a" x="5"/><path d="M0 0"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert 'x="5"' in out


def test_F4_backslash_w_zwyklej_wartosci_nie_kasuje_atrybutu():
    # rozwijamy escape'y do KONTROLI, a nie odrzucamy hurtem wszystkiego
    # z backslashem — inaczej tracimy poprawne wartosci
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text x="1" y="1" font-family="My\\ Font" fill="url(#ok)">A</text></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'font-family="My\\ Font"' in out
    assert 'fill="url(#ok)"' in out


# --- F5: biale znaki w wartosciach atrybutow -------------------------------

def test_F5_biale_znaki_w_atrybucie_sa_kodowane_encjami():
    # parser rozwija &#10;/&#13;/&#9; do prawdziwego znaku, a doslowny bialy
    # znak w wartosci atrybutu podlega przy NASTEPNYM parsowaniu XML-owej
    # normalizacji (kazdy -> spacja). Bez kodowania sciezka HTML (innerHTML,
    # bez normalizacji) i XML (WeasyPrint) czytaly INNE wartosci.
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path id="a&#9;b" d="M0 0&#10;L1 1&#13;Z" transform="translate(1,&#9;2)"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert '&#10;' in out and '&#13;' in out and '&#9;' in out
    assert '\n' not in out and '\r' not in out and '\t' not in out
    # wartosc przezywa ponowne parsowanie XML-owe w niezmienionej postaci
    element = ElementTree.fromstring(out)[0]
    assert element.get('d') == 'M0 0\nL1 1\rZ'
    assert element.get('id') == 'a\tb'
    assert element.get('transform') == 'translate(1,\t2)'


def test_F5_sanityzacja_wartosci_z_bialymi_znakami_jest_idempotentna():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M0 0&#10;L1 1" transform="translate(1,&#9;2)"/></svg>'
    )
    once = sanitize_svg(raw)

    assert once is not None
    assert sanitize_svg(once) == once


def test_F5_powrot_karetki_w_tresci_jest_kodowany():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text x="1" y="1">linia&#13;druga</text></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert '&#13;' in out
    assert '\r' not in out
    assert sanitize_svg(out) == out


# --- F6: cykl <use> rozwijany dopiero w rendererze -------------------------

def test_F6_bezposredni_cykl_use_traci_referencje():
    # 170 bajtow wystarczy, zeby wyczerpac stos cairosvg/WeasyPrint przy PDF;
    # MAX_DEPTH tego nie lapie, bo zrodlo jest PLASKIE
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g id="a"><use href="#a"/><path d="M0 0"/></g></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert '<use' in out  # element zostaje, znika tylko referencja
    assert 'd="M0 0"' in out
    ElementTree.fromstring(out)


def test_F6_use_odwolujacy_sie_do_siebie_traci_referencje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<use id="u" href="#u"/><path d="M0 0"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert 'id="u"' in out


def test_F6_posredni_cykl_przez_przodka_traci_referencje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g id="a"><g id="b"><use href="#a"/></g><path d="M0 0"/></g></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert 'd="M0 0"' in out


def test_F6_posredni_cykl_a_b_a_traci_referencje():
    # a -> b -> a: oba <use> sa plaskimi rodzenstwami, zaden nie jest
    # potomkiem swojego celu, a rozwiniecie i tak nie ma konca
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g id="a"><use href="#b"/></g>'
        '<g id="b"><use href="#a"/></g>'
        '<path d="M0 0"/></svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert 'd="M0 0"' in out


def test_F6_cykl_wykryty_takze_przez_xlink_href_i_z_prefiksem():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<g id="a"><use xlink:href="#a"/><path d="M0 0"/></g></svg>'
    )
    out = sanitize_svg(raw, id_prefix='poz1-')

    assert out is not None
    assert 'href' not in out.lower()
    assert 'id="poz1-a"' in out
    ElementTree.fromstring(out)


def test_F6_poprawne_use_bez_cyklu_zachowuje_referencje():
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg" id="edgesSvg">'
        '<defs><path id="p" d="M0 0 L1 1"/></defs>'
        '<g id="wrap"><use href="#p" x="5" y="5"/></g>'
        '</svg>'
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href="#p"' in out
    assert 'x="5"' in out

    # to samo z prefiksem
    z_prefiksem = sanitize_svg(raw, id_prefix='poz2-')
    assert z_prefiksem is not None
    assert 'href="#poz2-p"' in z_prefiksem


def test_F6_dlugi_lancuch_use_nie_wywraca_sanityzatora():
    # lancuch a1 -> a2 -> ... -> aN domkniety z powrotem do a1: wykrywanie
    # cyklu musi byc iteracyjne, inaczej samo wykrywanie przepelnia stos
    ogniwa = ''.join(
        '<g id="a%d"><use href="#a%d"/></g>' % (i, i + 1) for i in range(1, 2000)
    )
    ogniwa += '<g id="a2000"><use href="#a1"/></g>'
    raw = (
        '<svg xmlns="http://www.w3.org/2000/svg">%s<path d="M0 0"/></svg>' % ogniwa
    )
    out = sanitize_svg(raw)

    assert out is not None
    assert 'href' not in out.lower()
    assert 'd="M0 0"' in out
