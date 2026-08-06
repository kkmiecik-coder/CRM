# -*- coding: utf-8 -*-
"""Test trasy HTML zakładki Trakownia w panelu produkcji."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.sawmill_fixtures import BASE, app, client  # noqa: F401


def test_zakladka_sie_renderuje(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Nowa dostawa' in html
    assert 'Różnica m³' in html
    # Symbol delty jest zakazany w całym interfejsie — nieczytelny dla biura.
    assert 'Δ' not in html


def test_zakladka_ma_wszystkie_przyciski_gorne(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    for etykieta in ('Nowa dostawa', 'Dostawcy', 'Gatunki', 'Eksport XLSX'):
        assert etykieta in html


def test_zakladka_ma_filtr_odchylen(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert 'only_deviation' in html or 'tylko odchylenia' in html.lower()
