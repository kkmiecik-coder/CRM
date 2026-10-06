# -*- coding: utf-8 -*-
"""Front listy produktów i archiwum zna statusy po spakowaniu (logistyka etap 4, krok 4.3, spec 8.6).
Testy tekstowe jak tests/test_produkty_js_klasy_statusow.py."""
import os
import re

from modules.production.logistics import sposoby

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules')
NOWE = {'zweryfikowane': 'Zweryfikowane', 'zaladowane': u'Załadowane', 'dostarczone': 'Dostarczone'}


def _plik(nazwa):
    with open(os.path.join(JS, nazwa), encoding='utf-8') as f:
        return f.read()


def test_stala_spakowane_lub_dalej_w_liscie_produktow():
    js = _plik('products-module.js')
    stala = re.search(r"const STATUSY_PO_SPAKOWANIU = \[([^\]]*)\]", js)
    assert stala, 'brak stałej STATUSY_PO_SPAKOWANIU'
    assert re.findall(r"'(\w+)'", stala.group(1)) == list(sposoby.STATUSY_PO_SPAKOWANIU)
    # Pytania „czy skończone” idą przez stałą, nie przez porównanie z 'spakowane'.
    assert not re.search(r"(===|!==)\s*'spakowane'", js)


def test_etykiety_nowych_statusow():
    for nazwa in ('products-module.js', 'archive-module.js'):
        js = _plik(nazwa)
        for status, etykieta in NOWE.items():
            assert "'%s': '%s'" % (status, etykieta) in js, (nazwa, status)


def test_klasy_css_nowych_statusow_jak_zakonczone():
    js = _plik('products-module.js')
    for status in NOWE:
        # getStatusCSSClass domyślnie daje 'paused' — nowe statusy muszą mieć wpis jawnie.
        assert re.search(r"'%s':\s*'completed'" % status, js), status
        assert re.search(r"'%s':\s*'status-completed'" % status, js), status
        assert re.search(r"'%s':\s*'badge-completed'" % status, js), status
    arch = _plik('archive-module.js')
    for status in NOWE:
        assert re.search(r"'%s':\s*'status-completed'" % status, arch), status
        assert re.search(r"'%s':\s*'badge-completed'" % status, arch), status


def test_archiwum_pokazuje_prawdziwy_etap_zamowienia():
    """Krok 4.5: etap karty z serwera (order_stage_*), a nie stałe „Spakowane”; anulowane na czerwono."""
    arch = _plik('archive-module.js')
    assert "status: product.order_stage_status || 'spakowane'" in arch
    assert "statusLabel: product.order_stage_label || 'Spakowane'" in arch
    assert re.search(r"'anulowane':\s*'status-cancelled'", arch)
    assert re.search(r"'anulowane':\s*'badge-cancelled'", arch)
