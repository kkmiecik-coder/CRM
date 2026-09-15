# -*- coding: utf-8 -*-
"""
Serializer szczegółów produktu (/products/<id>/details, /products-filtered).

To on karmi modal produktu. Bez parsed_edge_processing nowa reguła
„Krawędzie tylko gdy jest obróbka krawędzi" ZAWSZE policzy w modalu „brak
krawędzi" i wytnie stanowisko z timeline'u — bez błędu, bez śladu w logach.
Sprawdzone na działającym kontenerze: dziś ten serializer nie zwraca ani
'parsed_edge_processing', ani 'painting_completed_at'.

ProductionProduct nie ma kolumn *_started_at ani *_duration_minutes (jedyne
*_started_at w models.py to sync_started_at:587 na logu synchronizacji), więc
'finishing_started_at' zawsze serializowało się jako None. Tego artefaktu nie
przenosimy na 'edges_started_at'.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _szczegoly(client, pid):
    r = client.get(BASE + '/products/{}/details'.format(pid))
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane['product']


def test_szczegoly_niosa_daty_krawedzi_i_lakierni(client, app):
    poludnie = datetime.combine(date.today(), time(12, 0))
    pid, _ = produkt(app, edges_completed_at=poludnie,
                     painting_completed_at=poludnie)
    p = _szczegoly(client, pid)
    # station_fields (products_api.py:2342) musi objąć oba kody, inaczej daty
    # wyjdą jako obiekty datetime i jsonify odda nieczytelny format RFC 822.
    assert isinstance(p['edges_completed_at'], str)
    assert isinstance(p['painting_completed_at'], str)


def test_szczegoly_niosa_liczniki_obu_stanowisk(client, app):
    pid, _ = produkt(app, quantity=4, quantity_done_edges=3,
                     quantity_done_painting=1)
    p = _szczegoly(client, pid)
    assert p['quantity_done_edges'] == 3
    assert p['quantity_done_painting'] == 1


def test_szczegoly_niosa_obrobke_krawedzi(client, app):
    pid_z, _ = produkt(app, edge_processing=True, numer='25/00001')
    pid_bez, _ = produkt(app, edge_processing=False, numer='25/00002')
    assert _szczegoly(client, pid_z)['parsed_edge_processing'] is True
    assert _szczegoly(client, pid_bez)['parsed_edge_processing'] is False


def test_szczegoly_nie_niosa_juz_pol_wykanczania(client, app):
    pid, _ = produkt(app)
    p = _szczegoly(client, pid)
    for klucz in ('finishing_started_at', 'finishing_completed_at',
                  'finishing_duration_minutes', 'quantity_done_finishing',
                  'edges_started_at', 'edges_duration_minutes'):
        assert klucz not in p, u'zbędne pole: {}'.format(klucz)


def test_lista_filtrowana_ma_ten_sam_ksztalt(client, app):
    """/products-filtered używa tego samego serializera — modal czyta z cache."""
    produkt(app, quantity=4, quantity_done_edges=2)
    r = client.get(BASE + '/products-filtered')
    assert r.status_code == 200, r.get_data()[:500]
    pozycja = r.get_json()['products'][0]
    assert pozycja['quantity_done_edges'] == 2
    assert 'parsed_edge_processing' in pozycja
