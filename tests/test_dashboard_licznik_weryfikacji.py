# -*- coding: utf-8 -*-
"""
Pasek Weryfikacji na dashboardzie przy błędzie licznika (fala końcowa kroku 4.3, F5, Ruling 18):
błąd licznika to null w odpowiedzi i „—” na pasku, bez klasy alarmu — nie zero ani ostatnie liczby.

Prawdziwe żądania HTTP na wspólnej apce testów panelu (tests/krawedzie_fixtures.py): dashboard czyta
kilkanaście tabel modułu produkcji, więc schemat zakłada db.create_all(), a adres, do którego szablon
paska linkuje (production_main.dashboard), dostaje atrapę.
"""
import re

import pytest

from extensions import db
from tests.krawedzie_fixtures import BASE, app, client  # noqa: F401


@pytest.fixture()
def panel(app):
    import modules.production.logistics.models  # noqa: F401  (tabele logistyki do create_all)
    db.create_all()
    app.add_url_rule('/production/panel-atrapa', endpoint='production.production_main.dashboard',
                     view_func=lambda: '')
    return app


def _licznik_rzuca(monkeypatch):
    from modules.production.logistics.services import weryfikacja
    monkeypatch.setattr(weryfikacja, 'liczba_problemow', lambda: 1 / 0)


def _liczniki_na_pasku(html):
    """(tekst „Do weryfikacji”, tekst „Problemy”, czy blok „Problemy” ma klasę is-alarm)."""
    do = re.search(r'id="verification-pending">([^<]*)<', html).group(1)
    problemy = re.search(r'id="verification-problems">([^<]*)<', html).group(1)
    alarm = 'il-logistyka-weryfikacja-problemy is-alarm' in html
    return do, problemy, alarm


def test_dashboard_data_przy_bledzie_licznika_daje_200_i_null(client, panel, monkeypatch):
    _licznik_rzuca(monkeypatch)
    r = client.get(BASE + '/dashboard-data')
    assert r.status_code == 200
    assert r.get_json()['data']['verification'] == {'pending': None, 'problems': None}


def test_dashboard_data_z_licznikami(client, panel, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    monkeypatch.setattr(weryfikacja, 'liczba_do_weryfikacji', lambda teraz: 3)
    monkeypatch.setattr(weryfikacja, 'liczba_problemow', lambda: 2)
    r = client.get(BASE + '/dashboard-data')
    assert r.status_code == 200
    assert r.get_json()['data']['verification'] == {'pending': 3, 'problems': 2}


def test_zakladka_dashboardu_przy_bledzie_licznika_ma_null_i_kreski_bez_alarmu(client, panel, monkeypatch):
    _licznik_rzuca(monkeypatch)
    r = client.get(BASE + '/dashboard-tab-content?initial_load=true')
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['initial_data']['logistics']['verification_pending'] is None
    assert dane['initial_data']['logistics']['verification_problems'] is None
    assert _liczniki_na_pasku(dane['html']) == (u'—', u'—', False)


@pytest.mark.parametrize('do_weryfikacji, problemy, alarm', [(0, 0, False), (4, 2, True)])
def test_zakladka_dashboardu_z_licznikami(client, panel, monkeypatch, do_weryfikacji, problemy, alarm):
    from modules.production.logistics.services import weryfikacja
    monkeypatch.setattr(weryfikacja, 'liczba_do_weryfikacji', lambda teraz: do_weryfikacji)
    monkeypatch.setattr(weryfikacja, 'liczba_problemow', lambda: problemy)
    r = client.get(BASE + '/dashboard-tab-content?initial_load=true')
    assert r.status_code == 200
    assert r.get_json()['initial_data']['logistics']['verification_problems'] == problemy
    assert _liczniki_na_pasku(r.get_json()['html']) == (str(do_weryfikacji), str(problemy), alarm)
