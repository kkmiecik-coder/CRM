# -*- coding: utf-8 -*-
"""Wspólne dane testów tabletu kierownika hali (API /api/mobile/manager/*): urządzenie `manager`, profil kierownika,
nagłówki i lista wszystkich endpointów blueprintu. Importuj razem z fiksturami:

    from tests.kierownik_pomocnicze import ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
    from tests.logistyka_fixtures import app, client  # noqa: F401
"""
import itertools

from extensions import db
from modules.production.models import ProductionDevice, ProductionWorker
from modules.production.services.mobile_api_service import generate_token

API = '/api/mobile/manager'

# Wszystkie endpointy blueprintu (metoda, wzór reguły Flaska względem API). Każde zadanie z trasami dopisuje tu swoje;
# test_lista_endpointow_bramek_jest_pelna porównuje listę z regułami zarejestrowanymi w aplikacji.
ENDPOINTY_KIEROWNIKA = []

_licznik = itertools.count(1)


def tablet_kierownika(imie='Karol', nazwisko=None):
    """(urządzenie stanowiska `manager`, aktywny pracownik ze znacznikiem is_manager)."""
    device = ProductionDevice(device_id='TAB-KIEROWNIK-%d' % next(_licznik), device_name='Tablet kierownika',
                              station_code='manager')
    kierownik = ProductionWorker(first_name=imie, last_name=nazwisko or 'Kierownik %d' % next(_licznik),
                                 is_active=True, is_manager=True)
    db.session.add_all([device, kierownik])
    db.session.commit()
    return device, kierownik


def naglowki(device, kto=None, op_id=None):
    """Bearer urządzenia, X-Worker-Ids (gdy podano pracownika) i X-Operation-Id."""
    wynik = {'Authorization': 'Bearer ' + generate_token(device),
             'X-Operation-Id': op_id or 'op-kier-%d' % next(_licznik)}
    if kto is not None:
        wynik['X-Worker-Ids'] = str(kto.id)
    return wynik
