# -*- coding: utf-8 -*-
"""
Obciążenie stanowiska — ile dni pracy stoi przed nim w kolejce.

`m³ oczekujące / średni dzienny przerób`. Miara odpowiada na pytanie, na
które nie odpowiada ani sama kolejka, ani „postęp dnia": czy ta kolejka jest
duża dla TEGO stanowiska.

Zmierzone na produkcji 2026-09-16: Krawędzie miały 8 sztuk w kolejce —
najmniej na hali — ale przy przerobie 0,061 m³/dzień dawało to 2,6 dnia,
drugi najgorszy wynik. Pakowanie odwrotnie: 59 sztuk, a schodzą w 0,8 dnia.
Po samej liczbie sztuk oba stanowiska były nie do odróżnienia od zdrowych.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
    ProductionStationEvent,
)
from modules.production.services.station_events_service import srednie_tempo_stanowisk
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionStationEvent,
)]

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


DZIS = date(2026, 9, 16)


_LICZNIK = {'n': 0}


def _produkt(volume=1.0):
    _LICZNIK['n'] += 1
    order = ProductionOrder(baselinker_order_id=_LICZNIK['n'],
                            internal_order_number='26/%05d' % _LICZNIK['n'])
    db.session.add(order)
    db.session.flush()
    p = ProductionProduct(
        order_id=order.id, short_product_id='26%03d_1' % _LICZNIK['n'],
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=1, current_status='czeka_na_sklejanie', volume_m3=volume)
    db.session.add(p)
    db.session.flush()
    return p


def _zdarzenie(produkt, stanowisko, dzien, delta=1, source='mobile'):
    # quantity_done_after to licznik sztuk PO zdarzeniu, NOT NULL w schemacie.
    # Tempo liczy się z samej delty, więc dla tych testów wartość jest obojętna
    # — ale kolumna musi być wypełniona, żeby wiersz w ogóle wszedł.
    e = ProductionStationEvent(
        production_item_id=produkt.id,
        station_code=stanowisko,
        delta=delta,
        quantity_done_after=max(0, delta),
        source=source,
        created_at=datetime.combine(dzien, datetime.min.time()) + timedelta(hours=9),
    )
    db.session.add(e)
    db.session.flush()
    return e


def test_tempo_dzieli_sie_przez_dni_z_aktywnoscia(app):
    """
    Mianownikiem są DNI ROBOCZE stanowiska, a nie dni kalendarzowe okna.
    Stanowisko pracujące dwa dni w tygodniu dostałoby inaczej sztucznie
    zaniżone tempo, a przez to zawyżone obciążenie — i wyglądałoby na
    zapchane tylko dlatego, że nie pracuje codziennie.
    """
    p = _produkt(volume=2.0)
    _zdarzenie(p, 'gluing', DZIS - timedelta(days=1))
    _zdarzenie(p, 'gluing', DZIS - timedelta(days=5))

    tempo = srednie_tempo_stanowisk(dni=14, dzis=DZIS)

    # 4 m³ w dwóch dniach roboczych = 2 m³ na dzień, a nie 4/14.
    assert round(tempo['gluing'], 3) == 2.0


def test_zdarzenia_automatu_nie_licza_sie_do_tempa(app):
    """
    auto_skip i system to odbicia stanowisk POMINIĘTYCH, generowane przez
    complete_task() — nikt ich fizycznie nie wykonał. Wliczone do tempa
    zawyżałyby przerób i zaniżały obciążenie, czyli chowały wąskie gardło.
    Na produkcji to 9% wszystkich zdarzeń, więc nie jest to margines.
    """
    p = _produkt(volume=1.0)
    _zdarzenie(p, 'formatting', DZIS, source='mobile')
    _zdarzenie(p, 'formatting', DZIS, source='auto_skip')
    _zdarzenie(p, 'formatting', DZIS, source='system')

    tempo = srednie_tempo_stanowisk(dni=14, dzis=DZIS)

    assert round(tempo['formatting'], 3) == 1.0


def test_stanowisko_bez_przerobu_nie_ma_wpisu(app):
    """
    Brak klucza, a nie zero — dzielenie kolejki przez zerowe tempo dałoby
    nieskończoność. Widok ma w takim wypadku napisać „—", a nie liczbę.
    """
    p = _produkt()
    _zdarzenie(p, 'gluing', DZIS)

    assert 'painting' not in srednie_tempo_stanowisk(dni=14, dzis=DZIS)


def test_okno_odcina_starsze_dni(app):
    """
    Tempo ma opisywać BIEŻĄCĄ wydolność stanowiska. Zdarzenie sprzed
    kwartału nie może ciągnąć średniej, bo obciążenie liczone z niego
    opisywałoby halę, której już nie ma.
    """
    p = _produkt(volume=3.0)
    _zdarzenie(p, 'edges', DZIS - timedelta(days=2))
    _zdarzenie(p, 'edges', DZIS - timedelta(days=90))

    tempo = srednie_tempo_stanowisk(dni=14, dzis=DZIS)

    assert round(tempo['edges'], 3) == 3.0


def test_cofniecie_sztuki_obniza_tempo(app):
    """
    delta bywa ujemna (cofnięcie sztuki ze stanowiska). Tempo liczy się
    z sumy delt, więc zwrot obniża przerób — inaczej stanowisko oddające
    braki wyglądałoby na wydajniejsze, niż jest.
    """
    p = _produkt(volume=1.0)
    _zdarzenie(p, 'packaging', DZIS, delta=5)
    _zdarzenie(p, 'packaging', DZIS, delta=-2)

    assert round(srednie_tempo_stanowisk(dni=14, dzis=DZIS)['packaging'], 3) == 3.0


def test_domyslna_data_bierze_sie_z_zegara_aplikacji(app):
    """
    Wywołanie bez `dzis` musi działać — tak woła je dashboard. Wszystkie
    testy wyżej podają datę jawnie, więc brakujący import get_local_now
    przeszedłby przez nie bez śladu i wywrócił się dopiero na panelu.
    """
    p = _produkt(volume=1.0)
    _zdarzenie(p, 'gluing', date.today())

    assert srednie_tempo_stanowisk()['gluing'] > 0
