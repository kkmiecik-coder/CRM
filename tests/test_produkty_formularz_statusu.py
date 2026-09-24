# -*- coding: utf-8 -*-
"""
Formularz masowej zmiany statusu w szablonie zakładki Produkty.

Ten select (products-tab-content.html:287-301) oferuje trzy wartości, których
enum production_status nigdy nie miał ('w_trakcie_ciecia',
'w_trakcie_skladania', 'w_trakcie_pakowania') — po dodaniu walidacji
w endpointcie bulk-action każda z nich kończy się HTTP 400, a przed nią
kończyłaby się błędem MySQL 1265 wywalającym cały batch. Nie miał za to ani
lakierni, ani logistyki.

To JEDYNE wystąpienie słowa 'wykanczanie' w tym szablonie (grep: 1 trafienie).

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.models import ProductionItem
from tests.krawedzie_fixtures import SZABLON_PRODUKTOW, zrodlo


def _wartosci_selecta():
    html = zrodlo(SZABLON_PRODUKTOW)
    poczatek = html.index('<select class="form-select" id="bulk-new-status">')
    blok = html[poczatek:html.index('</select>', poczatek)]
    return [w for w in re.findall(r'<option value="([^"]*)"', blok) if w]


def test_kazda_opcja_istnieje_w_enumie_modelu():
    dozwolone = set(ProductionItem.current_status.type.enums)
    nadmiarowe = [w for w in _wartosci_selecta() if w not in dozwolone]
    assert nadmiarowe == [], u'statusy spoza enuma: {}'.format(nadmiarowe)


def test_formularz_oferuje_krawedzie_i_lakiernie_bez_logistyki():
    wartosci = _wartosci_selecta()
    for status in ('czeka_na_krawedzie', 'czeka_na_lakiernie'):
        assert status in wartosci, u'brak opcji {}'.format(status)
    html = zrodlo(SZABLON_PRODUKTOW)
    assert 'value="czeka_na_logistyke"' not in html


def test_formularz_nie_oferuje_juz_wykanczania():
    assert 'czeka_na_wykanczanie' not in _wartosci_selecta()
