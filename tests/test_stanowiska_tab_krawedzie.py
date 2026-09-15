# -*- coding: utf-8 -*-
"""
Zakładka Stanowiska po podziale Wykańczania na Krawędzie i Lakiernię.

stations_api.py trzyma PIĘĆ równoległych map kodów w jednej funkcji (lista,
status kolejki, kolumna daty, nazwa, ikona). Rozjazd którejkolwiek nie wywala
endpointu: kolumna pobierana jest przez getattr w try/except AttributeError
(stations_api.py:78-90), więc literówka daje CICHO zero ukończonych, nie błąd.

Kolejność stanowisk sprawdzamy na HTML-u, nie na dict-cie: jsonify domyślnie
sortuje klucze alfabetycznie, więc `data` po deserializacji NIE niesie już
kolejności wstawiania.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401

KOLEJNOSC = ['cutting', 'assembly', 'gluing', 'formatting',
             'edges', 'painting', 'packaging']


def _stanowiska(client):
    r = client.get(BASE + '/stations-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane


def test_zakladka_zna_krawedzie_i_lakiernie(client, app):
    dane = _stanowiska(client)
    assert set(dane['data']) == set(KOLEJNOSC)
    assert dane['data']['edges']['name'] == 'Krawędzie'
    assert dane['data']['painting']['name'] == 'Lakiernia'
    assert 'finishing' not in dane['data']


def test_lakiernia_stoi_zaraz_za_krawedziami_w_przeplywie(client, app):
    """Kolejność kafli w HTML = kolejność strzałek w „Przepływie produkcji"."""
    dane = _stanowiska(client)
    assert re.findall(r"navigateToStation\('(\w+)'\)", dane['html']) == KOLEJNOSC


def test_kolejki_obu_stanowisk_licza_wlasne_statusy(client, app):
    produkt(app, status='czeka_na_krawedzie', numer='25/00001')
    produkt(app, status='czeka_na_krawedzie', numer='25/00002')
    produkt(app, status='czeka_na_lakiernie', numer='25/00003')

    dane = _stanowiska(client)
    assert dane['data']['edges']['stats']['total_pending'] == 2
    assert dane['data']['painting']['stats']['total_pending'] == 1


def test_domkniecia_licza_sie_z_wlasnych_kolumn(client, app):
    """
    completed_field_map pobiera kolumnę przez getattr w try/except
    AttributeError — literówka w nazwie kolumny daje CICHO zero ukończonych,
    a nie błąd. Dlatego pilnujemy obu kolumn osobno.
    """
    poludnie = datetime.combine(date.today(), time(12, 0))
    produkt(app, status='czeka_na_logistyke', numer='25/00004',
            edges_completed_at=poludnie)
    produkt(app, status='czeka_na_logistyke', numer='25/00005',
            painting_completed_at=poludnie)

    dane = _stanowiska(client)
    assert dane['data']['edges']['stats']['today_completed'] == 1
    assert dane['data']['painting']['stats']['today_completed'] == 1
