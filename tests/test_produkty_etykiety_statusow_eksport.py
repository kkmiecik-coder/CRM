# -*- coding: utf-8 -*-
"""
Etykiety i kolory statusów w eksportach XLSX/PDF.

_format_status zwraca nierozpoznany status SUROWY (common_api.py:126), więc
niepełna migracja daje w arkuszu „czeka_na_krawedzie" obok „Czeka na
pakowanie" — brzydko, ale bez błędu. Brakowało tam też od zawsze lakierni
i logistyki.

status_colors jest zmienną LOKALNĄ funkcji eksportu XLSX — nie da się jej
zaimportować ani wywołać bez budowania całego skoroszytu, więc sprawdzamy
ją strukturalnie na źródle (konwencja tests/test_checkout_js.py). W całym
pliku jest dokładnie jedno wystąpienie `status_colors = {`.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.routers.api.common_api import _format_status
from tests.krawedzie_fixtures import PY_PRODUCTS_API, zrodlo


def test_status_krawedzi_ma_polska_etykiete():
    assert _format_status('czeka_na_krawedzie') == 'Czeka na krawędzie'


def test_dopisano_brakujace_etykiety_lakierni_i_logistyki():
    assert _format_status('czeka_na_lakiernie') == 'Czeka na lakiernię'
    assert _format_status('czeka_na_logistyke') == 'Czeka na logistykę'


def test_stara_etykieta_wykanczania_znika():
    """Nierozpoznany status wraca surowy — to jest dowód, że klucza już nie ma."""
    assert _format_status('czeka_na_wykanczanie') == 'czeka_na_wykanczanie'


def test_eksport_xlsx_ma_kolory_obu_nowych_statusow():
    kod = zrodlo(PY_PRODUCTS_API)
    poczatek = kod.index('status_colors = {')
    blok = kod[poczatek:kod.index('}', poczatek)]
    assert "'czeka_na_krawedzie'" in blok
    assert "'czeka_na_lakiernie'" in blok
    assert "'czeka_na_wykanczanie'" not in blok
