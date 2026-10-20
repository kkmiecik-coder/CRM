# -*- coding: utf-8 -*-
"""
Pozycje `wstrzymane` nie wchodzą do liczników niespakowanej pracy na dashboardzie i Liście produkcyjnej.

Wstrzymana pozycja nie stoi w kolejce żadnego stanowiska (nie ma jej w `STATION_PENDING_STATUS`), więc widżet
„W produkcji teraz” i statystyki Listy produkcyjnej nie mogą jej liczyć, bo wychodzi z tego inna liczba m³ niż suma
kolejek stanowisk (na produkcji 20.10.2026: 16,37 zamiast 15,58). Pełne uruchomienie dashboardu wymaga DDL całego modułu
produkcji, więc — jak w tests/test_dashboard_krawedzie.py — test jest TEKSTOWY i pilnuje wszystkich kopii zapytania.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUKCJA = os.path.join(KORZEN, 'modules', 'production')


def _plik(*sciezka):
    with open(os.path.join(PRODUKCJA, *sciezka), encoding='utf-8') as f:
        return f.read()


def test_widzet_w_produkcji_teraz_pomija_wstrzymane_we_wszystkich_kopiach():
    """Trzy kopie obliczenia: pierwszy render strony i dwa endpointy odświeżania (dashboard_api)."""
    zrodla = {
        'main_routers': _plik('routers', 'main_routers.py'),
        'dashboard_api': _plik('routers', 'api', 'dashboard_api.py'),
    }
    wzorzec = re.compile(r"current_status\.notin_\(sposoby\.STATUSY_PO_SPAKOWANIU \+ \(([^)]*)\)\)")
    znalezione = {nazwa: wzorzec.findall(tresc) for nazwa, tresc in zrodla.items()}

    assert len(znalezione['main_routers']) == 1
    assert len(znalezione['dashboard_api']) == 2
    for nazwa, krotki in znalezione.items():
        for krotka in krotki:
            assert "'anulowane'" in krotka and "'wstrzymane'" in krotka, (nazwa, krotka)


def test_statystyki_listy_produkcyjnej_pomijaja_wstrzymane():
    js = _plik('static', 'js', 'modules', 'products-module.js')
    assert "status === 'wstrzymane'" in js
    assert "'anulowane', 'wstrzymane'" in _plik('routers', 'api', 'products_api.py')


def test_dopisek_wstrzymanych_jest_pod_wartoscia_objetosci():
    """Dopisek mieszka w kontenerze wartości (kolumna), a nie jako trzecie dziecko wiersza karty."""
    html = _plik('templates', 'components', 'products-tab-content.html')
    assert re.search(r'il-stat-value-wrap">\s*<span class="il-stat-value" id="il-stats-volume">.*?'
                     r'id="il-stats-volume-held"', html, re.S)
