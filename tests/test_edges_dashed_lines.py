"""Testy _ensure_dashed_lines — styk sanityzatora SVG z generatorem PDF.

Regresja, ktora te testy pilnuja: sanityzator emituje elementy bez dzieci
w formie skroconej (``<line .../>``), a ``_ensure_dashed_lines`` doklejalo
atrybut wzorcem ``>$``, czyli ZA ukosnikiem — dawalo to
``<line .../ stroke-dasharray="5,3">``, XML nie do sparsowania. cairosvg
zwracalo wtedy None i kolumna "Widok izometryczny" znikala z PDF oferty
(dla krawedzi nie ma fallbacku inline SVG, jest tylko dla ksztaltu).

Buga nie bylo widac, dopoki funkcja dostawala wylacznie surowe SVG
z przegladarki, ktore uzywa formy pelnej ``<line></line>``.
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.baselinker.edges_pdf_generator import EdgesPdfGenerator


def _gen():
    # pomijamy __init__ — testujemy czysta funkcje tekstowa
    return EdgesPdfGenerator.__new__(EdgesPdfGenerator)


def _svg(linia):
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + linia + '</svg>'


def test_tag_samozamykajacy_daje_poprawny_xml():
    wej = _svg('<line class="edges-line edges-hidden" x1="0" y1="0" x2="5" y2="5"/>')
    out = _gen()._ensure_dashed_lines(wej)
    ET.fromstring(out)  # nie moze rzucic
    assert 'stroke-dasharray="5,3"' in out
    assert '/ stroke-dasharray' not in out


def test_tag_otwierajacy_dziala_jak_dotad():
    wej = _svg('<line class="edges-line edges-hidden" x1="0" y1="0" x2="5" y2="5"></line>')
    out = _gen()._ensure_dashed_lines(wej)
    ET.fromstring(out)
    assert 'stroke-dasharray="5,3"' in out


def test_istniejacy_dasharray_nie_jest_dublowany():
    wej = _svg('<line class="hidden" x1="0" y1="0" x2="5" y2="5" stroke-dasharray="2,2"/>')
    out = _gen()._ensure_dashed_lines(wej)
    ET.fromstring(out)
    assert out.count('stroke-dasharray') == 1


def test_linia_widoczna_nie_dostaje_dasharray():
    wej = _svg('<line class="edges-line" x1="0" y1="0" x2="5" y2="5"/>')
    out = _gen()._ensure_dashed_lines(wej)
    ET.fromstring(out)
    assert 'stroke-dasharray' not in out


def test_pelny_lancuch_sanityzator_potem_dasharray():
    """Sanityzator -> _ensure_dashed_lines -> parsowalny XML.

    To jest dokladnie kolejnosc ze sciezki PDF w modules/quotes/routers.py.
    """
    from modules.quotes.services.svg_sanitizer import sanitize_svg

    surowy = _svg(
        '<line class="edges-line edges-hidden" x1="0" y1="0" x2="5" y2="5"'
        ' style="stroke: rgb(102, 102, 102); stroke-width: 2"></line>'
    )
    oczyszczony = sanitize_svg(surowy)
    assert oczyszczony is not None

    out = _gen()._ensure_dashed_lines(oczyszczony)
    ET.fromstring(out)
    assert 'stroke-dasharray="5,3"' in out
    # kolor z inline style ma przezyc konwersje na atrybut prezentacyjny
    assert 'rgb(102, 102, 102)' in out or '#666' in out


def test_puste_wejscie_przechodzi_bez_zmian():
    g = _gen()
    assert g._ensure_dashed_lines('') == ''
    assert g._ensure_dashed_lines(None) is None
