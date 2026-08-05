# -*- coding: utf-8 -*-
"""Numeracja zleceń trakowania — TRK/RRRR/NNN."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.sawmill.models import SawmillCounter
from modules.production.sawmill.services import numbering
from modules.production.sawmill.services.numbering import next_order_number
from modules.users.models import User
# Sam import User nie wystarcza — to samo uzasadnienie co w test_sawmill_models.py
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

_TABLES = [User.__table__, SawmillCounter.__table__]


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


def test_pierwszy_numer_w_roku(app):
    with app.app_context():
        assert next_order_number(2026) == 'TRK/2026/001'
        db.session.commit()


def test_kolejne_numery_rosna(app):
    with app.app_context():
        numery = [next_order_number(2026) for _ in range(3)]
        db.session.commit()
        assert numery == ['TRK/2026/001', 'TRK/2026/002', 'TRK/2026/003']


def test_reset_na_nowy_rok(app):
    with app.app_context():
        next_order_number(2026)
        next_order_number(2026)
        db.session.commit()
        assert next_order_number(2027) == 'TRK/2027/001'
        db.session.commit()


def test_przepelnienie_powyzej_999(app):
    """Pad do 3 cyfr, ale numer 1000 ma się zapisać, nie urwać."""
    with app.app_context():
        db.session.add(SawmillCounter(year=2026, last_number=999))
        db.session.commit()
        assert next_order_number(2026) == 'TRK/2026/1000'
        db.session.commit()


def test_numer_miesci_sie_w_kolumnie(app):
    with app.app_context():
        db.session.add(SawmillCounter(year=2026, last_number=999998))
        db.session.commit()
        numer = next_order_number(2026)
        db.session.commit()
        assert len(numer) <= 24


def test_domyslny_rok_to_biezacy(app):
    from datetime import datetime
    with app.app_context():
        numer = next_order_number()
        db.session.commit()
        assert numer.startswith('TRK/{}/'.format(datetime.now().year))


def test_wyscig_o_pierwszy_wiersz_rocznika(app):
    """
    Symulacja wyścigu przy leniwym zakładaniu wiersza licznika dla nowego
    roku: dwie transakcje wchodzące na pierwsze zlecenie roku jednocześnie
    obie widzą brak wiersza i obie próbują go wstawić — druga powinna
    dostać IntegrityError na duplikacie klucza głównego, złapać go
    (SAVEPOINT), ponowić SELECT i dostać poprawny kolejny numer zamiast
    wywalać wyjątkiem cały request.

    UWAGA: SQLite nie ma blokad wierszy i ignoruje with_for_update(), więc
    realnej współbieżności nie da się tu odtworzyć (jeden proces, jedno
    połączenie). Symulujemy kolizję: podmieniamy wewnętrzne zapytanie tak,
    żeby przy pierwszym wywołaniu zwróciło None (jakby konkurent jeszcze
    nie zacommitował), mimo że wiersz fizycznie już istnieje w bazie
    (jakby konkurent zdążył go wstawić) — dzięki temu próba insertu w
    next_order_number() naprawdę wywoła IntegrityError, a test sprawdza
    zachowanie funkcji (zwrócony numer, brak wyjątku), nie implementację.
    """
    with app.app_context():
        # Wiersz „wstawiony przez konkurenta" tuż przed naszą próbą insertu.
        db.session.add(SawmillCounter(year=2026, last_number=5))
        db.session.commit()

        real_select = numbering._select_counter_for_update
        wywolania = {'n': 0}

        def fake_select(year):
            wywolania['n'] += 1
            if wywolania['n'] == 1:
                # Pierwsze sprawdzenie „nie widzi" wiersza konkurenta.
                return None
            # Ponowienie po IntegrityError — realny SELECT, znajduje wiersz.
            return real_select(year)

        with patch.object(numbering, '_select_counter_for_update', side_effect=fake_select):
            numer = next_order_number(2026)
        db.session.commit()

        assert numer == 'TRK/2026/006'
        assert wywolania['n'] == 2
