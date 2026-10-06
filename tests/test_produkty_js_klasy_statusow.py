# -*- coding: utf-8 -*-
"""
Klasy CSS statusów i dropdown masowej zmiany statusu w products-module.js.

Nazwy klas CSS ('status-finishing', 'badge-finishing') ZOSTAJĄ świadomie —
rename arkuszy jest osobnym zadaniem, a te selektory nadal istnieją
w products-tab.css (:446-447, :578-582). Zmieniamy wyłącznie KLUCZE statusów.

Dropdown JS (showBulkStatusChangeDropdown) jest drugim, obok szablonu,
miejscem wysyłającym new_status do /products/bulk-action — po zwężeniu enuma
stary status kończy się tam HTTP 400.

UWAGA NA KOTWICĘ: `const statuses = [` występuje w tym pliku DWA razy —
raz w linii 1390 (`const statuses = [...new Set(...)]`) i raz w dropdownie
(:2740). Szukanie po samym tym ciągu łapie to pierwsze wystąpienie i wciąga
1350 linii nieswojego kodu, więc najpierw kotwiczymy się na nazwie metody.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.models import ProductionItem
from tests.krawedzie_fixtures import JS_PRODUKTY, zrodlo


def _blok(naglowek, domkniecie='\n        };\n'):
    js = zrodlo(JS_PRODUKTY)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    poczatek = js.index(naglowek)
    reszta = js[poczatek:]
    return reszta[:reszta.index(domkniecie)]


def _lista_dropdownu():
    """Tablica statusów WEWNĄTRZ showBulkStatusChangeDropdown, nie żadna inna."""
    js = zrodlo(JS_PRODUKTY)
    metoda = js[js.index('showBulkStatusChangeDropdown(selectedIds) {'):]
    metoda = metoda[:metoda.index('\n    }\n')]
    poczatek = metoda.index('const statuses = [')
    return metoda[poczatek:metoda.index('];', poczatek)]


def test_klasa_stanowiska_liczy_sie_ze_statusu_krawedzi():
    blok = _blok('    getStationClassFromStatus(status) {')
    assert "'czeka_na_krawedzie': 'status-finishing'" in blok
    assert "'czeka_na_wykanczanie'" not in blok


def test_klasa_pigulki_liczy_sie_ze_statusu_krawedzi():
    blok = _blok('    getStatusBadgeClass(status) {')
    assert "'czeka_na_krawedzie': 'badge-finishing'" in blok
    assert "'czeka_na_wykanczanie'" not in blok


def test_dropdown_masowej_zmiany_oferuje_krawedzie():
    blok = _lista_dropdownu()
    assert "value: 'czeka_na_krawedzie', label: 'Krawędzie'" in blok
    assert 'czeka_na_wykanczanie' not in blok


def test_kazdy_status_dropdownu_istnieje_w_enumie_modelu():
    blok = _lista_dropdownu()
    dozwolone = set(ProductionItem.current_status.type.enums)
    wartosci = re.findall(r"value: '(\w+)'", blok)
    assert wartosci, u'nie znaleziono żadnej wartości — kotwica się rozjechała'
    nadmiarowe = [w for w in wartosci if w not in dozwolone]
    assert nadmiarowe == [], u'statusy spoza enuma: {}'.format(nadmiarowe)
