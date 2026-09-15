# -*- coding: utf-8 -*-
"""
Okres przejściowy: stary kod stanowiska 'finishing' w raportach.

Po rozdzieleniu wykańczania na Krawędzie i Lakiernię kod 'finishing' znika
z katalogu, ale NIE znika z zapisanych linków, zakładek przeglądarki i adresów
krążących w mailach. Cztery bramki walidacji ?station= w reports_api odrzucały
taki kod czystym 400 „Nieprawidłowe stanowisko" — te testy pilnują, że bramki
rozwijają alias na 'edges' i oddają dane Krawędzi.

Decyzja o zasięgu aliasu jest w sekcji 3 specyfikacji: alias działa WSZĘDZIE,
nie tylko na /api/mobile/*.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession,
)
from modules.users.models import User
# configure_mappers() przy pierwszym zapytaniu konfiguruje CAŁY rejestr —
# bez tych importów wywala się na relationship('Multiplier') / ('Client').
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

BASE = '/production/api'

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w pozostałych pakietach.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

# Stały poniedziałek: raporty kubełkują po dobach i po dniach tygodnia.
PONIEDZIALEK = date(2026, 8, 10)
ZAKRES = f'start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    # LOGIN_DISABLED neutralizuje login_required — testujemy ciało endpointów.
    app.config['LOGIN_DISABLED'] = True

    from modules.production.routers.api import api_bp
    app.register_blueprint(api_bp, url_prefix=BASE)
    db.init_app(app)

    with app.app_context():
        # HOUR()/MINUTE() istnieją w MySQL, ale nie w SQLite — a timeline
        # /reports/station-output liczy z nich kubełki co pół godziny (patrz
        # ten sam zabieg w tests/test_reports_service.py). Bez rejestracji
        # zapytanie wywraca się na sqlite3.OperationalError, zanim alias
        # zdąży cokolwiek udowodnić.
        @event.listens_for(db.engine, 'connect')
        def _funkcje_czasu(polaczenie, _rekord):
            polaczenie.create_function(
                'hour', 1, lambda s: int(str(s)[11:13]) if s else 0)
            polaczenie.create_function(
                'minute', 1, lambda s: int(str(s)[14:16]) if s else 0)

        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def zalogowany(monkeypatch):
    """
    Endpointy raportów logują user_id na ścieżce błędu (_blad_serwera,
    reports_api.py:113), a testowa apka nie ma LoginManagera. Podmieniamy
    `current_user` w przestrzeni modułu (endpoint importuje go po nazwie),
    żeby ewentualny błąd wewnątrz endpointu dał czytelny traceback,
    a nie AttributeError na loggerze.
    """
    from modules.production.routers.api import reports_api

    monkeypatch.setattr(reports_api, 'current_user',
                        type('UzytkownikTestowy', (), {'id': 1, 'role': 'admin'})())
    return reports_api


def _praca_na_krawedziach():
    """Zamówienie + produkt + jeden PODPISANY event na stanowisku Krawędzie."""
    order = ProductionOrder(baselinker_order_id=1,
                            internal_order_number='26/00001',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id='26001_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=10, volume_m3=0.5, current_status='czeka_na_lakiernie',
        created_at=datetime.combine(PONIEDZIALEK, time(9, 0)))
    pracownik = ProductionWorker(first_name='Adam', last_name='Nowak')
    db.session.add_all([produkt, pracownik])
    db.session.commit()

    ev = ProductionStationEvent(
        production_item_id=produkt.id, station_code='edges', delta=4,
        quantity_done_after=4, source='mobile',
        created_at=datetime.combine(PONIEDZIALEK, time(10, 0)))
    db.session.add(ev)
    db.session.flush()
    db.session.add(ProductionStationEventWorker(
        event_id=ev.id, worker_id=pracownik.id, share=1.0))
    db.session.commit()
    return produkt


def test_stary_link_pokrycia_atrybucji_oddaje_dane_krawedzi(app, client, zalogowany):
    """Bramka wspólna _waliduj_stanowisko() — /reports/attribution-coverage."""
    with app.app_context():
        _praca_na_krawedziach()

    stary = client.get(
        f'{BASE}/reports/attribution-coverage?station=finishing&{ZAKRES}')
    nowy = client.get(
        f'{BASE}/reports/attribution-coverage?station=edges&{ZAKRES}')

    assert stary.status_code == 200, stary.get_json()
    assert stary.get_json()['success'] is True
    assert stary.get_json() == nowy.get_json()
    assert stary.get_json()['summary']['pieces_abs'] == 4


def test_stary_link_wkladu_osob_oddaje_dane_krawedzi(app, client, zalogowany):
    """
    Bramka /reports/station-worker-output — 'all' jest tu zabronione,
    więc kod stanowiska JEST obowiązkowy i alias musi zadziałać.
    """
    with app.app_context():
        _praca_na_krawedziach()

    odp = client.get(
        f'{BASE}/reports/station-worker-output?station=finishing&{ZAKRES}')

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    # Echo kodu w odpowiedzi musi być KANONICZNE — inaczej front dostaje
    # z powrotem martwy kod i wkleja go do kolejnego żądania.
    assert dane['station'] == 'edges'
    assert dane['station_label'] == 'Krawędzie'
    assert dane['summary']['station_events'] == 1


def test_stary_link_wydajnosci_pracownikow_oddaje_wiersze_krawedzi(
        app, client, zalogowany):
    """Bramka /reports/worker-output."""
    with app.app_context():
        _praca_na_krawedziach()

    odp = client.get(f'{BASE}/reports/worker-output?station=finishing&{ZAKRES}')

    assert odp.status_code == 200, odp.get_json()
    raport = odp.get_json()['report']
    assert raport['station'] == 'edges'
    assert [w['station_label'] for w in raport['rows']] == ['Krawędzie']


def test_stary_link_wykonania_stanowiska_oddaje_wiersze_krawedzi(
        app, client, zalogowany):
    """
    Bramka /reports/station-output (reports_api.py:596-601).

    Ta bramka ODRZUCA martwy kod czystym 400 — nie ma tu cichej pustej listy.
    Objawem braku aliasu jest więc zapisany link, który przestaje działać
    z komunikatem o nieprawidłowym stanowisku.
    """
    with app.app_context():
        _praca_na_krawedziach()

    odp = client.get(f'{BASE}/reports/station-output?station=finishing&{ZAKRES}')

    assert odp.status_code == 200, odp.get_json()
    pozycje = odp.get_json()['items']
    assert pozycje, 'stary link oddał pustą listę zamiast pracy Krawędzi'
    assert {p['station_code'] for p in pozycje} == {'edges'}


def test_nieznane_stanowisko_dalej_leci_400(app, client, zalogowany):
    """Alias nie ma prawa rozszczelnić walidacji — literówka nadal jest błędem."""
    odp = client.get(f'{BASE}/reports/station-output?station=nie_ma_takiego&{ZAKRES}')
    assert odp.status_code == 400


def test_alias_nie_dziala_w_druga_strone():
    """
    'edges' jest kodem KANONICZNYM, nie aliasem 'finishing' (pełny kontrakt
    resolve_station_code — w nagłówku planu). Odwrotny kierunek sprawiłby, że
    zdjęcie okresu przejściowego (krok 20 wdrożenia) niczego nie zmienia,
    bo martwy kod wracałby do bazy.
    """
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('finishing') == 'edges'
    assert resolve_station_code('edges') == 'edges'


def test_serwis_wkladu_osob_rozwija_alias(app):
    """
    Bramka serwisu jest DRUGA, niezależna od routera: eksport, testy i każdy
    inny konsument wołają agregat wprost, z pominięciem walidacji w reports_api.
    Dla nich zapisany kod 'finishing' musi znaczyć to samo co 'edges'.
    """
    from modules.production.services import reports_service

    with app.app_context():
        _praca_na_krawedziach()

        stary = reports_service.wklad_pracownikow_na_stanowisku(
            'finishing', PONIEDZIALEK, PONIEDZIALEK)
        nowy = reports_service.wklad_pracownikow_na_stanowisku(
            'edges', PONIEDZIALEK, PONIEDZIALEK)

        assert stary == nowy
        # Echo kodu w odpowiedzi musi być KANONICZNE — inaczej front dostaje
        # z powrotem martwy kod i wkleja go do kolejnego żądania.
        assert stary['station'] == 'edges'
        assert stary['station_label'] == 'Krawędzie'
        assert stary['summary']['station_events'] == 1


def test_serwis_dalej_odrzuca_nieznane_i_zbiorcze_stanowisko(app):
    """
    Alias rozszerza bramkę o JEDEN kod, a nie rozszczelnia jej: literówka i
    'all' nadal mają lecieć błędem, a nie kompletem zer wyglądającym na wynik.
    """
    from modules.production.services import reports_service
    from modules.production.services.worker_stats_service import ZakresError

    with app.app_context():
        with pytest.raises(ZakresError):
            reports_service.wklad_pracownikow_na_stanowisku(
                'nie_ma_takiego', PONIEDZIALEK, PONIEDZIALEK)
        with pytest.raises(ZakresError):
            reports_service.wklad_pracownikow_na_stanowisku(
                'all', PONIEDZIALEK, PONIEDZIALEK)
