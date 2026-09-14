# -*- coding: utf-8 -*-
"""
403 station_mismatch musi zostawać w kolejce offline tabletu.

Tło: @with_idempotency zapisuje odpowiedź pod X-Operation-Id dla KAŻDEGO
statusu poniżej 500, który nie jest wymieniony w retryable_statuses, a przy
ponowieniu odtwarza ją bez wywołania handlera. Gdy 403 nie jest na tej liście,
rozjazd rejestracji urządzenia ze stanowiskiem zamienia się w TRWAŁĄ UTRATĘ
odbitych sztuk: tablet dostaje zapamiętane 403 przez cały okres retencji wpisu,
klasyfikuje odpowiedź jako ostateczną i usuwa akcję z kolejki, meldując przy tym
udaną synchronizację.

Przyczyna 403 jest zawsze odwracalna bez udziału tabletu (przerejestrowanie
urządzenia, korekta station_code, zmiana kodu stanowiska po stronie serwera),
więc kod należy do tej samej rodziny co 400/404/409.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask, jsonify
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProcessedMobileOperation
from modules.production.services.mobile_api_service import with_idempotency
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA
from modules.production.sawmill.routers.mobile_api import (
    BLEDY_DO_PONOWIENIA as BLEDY_DO_PONOWIENIA_TRAKOWNI,
)
# Importy rejestrujące mappery — configure_mappers() przy pierwszym query
# potrzebuje ich do rozwiązania relationshipów z modules/users/models.py.
# Wzorzec i uzasadnienie jak w tests/test_sawmill_hooks.py.
from modules.users.models import User  # noqa: F401
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401


_TABLES = [ProcessedMobileOperation.__table__]


@pytest.fixture()
def app():
    """Minimalny Flask + SQLAlchemy na SQLite in-memory (StaticPool — jedno
    współdzielone połączenie, żeby zapis z jednego request-contextu był widoczny
    w kolejnym zapytaniu w tym samym teście)."""
    flask_app = Flask(__name__)
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(flask_app)
    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield flask_app
        db.session.remove()


def _odpowiedz_station_mismatch():
    return jsonify({
        'error': 'station_mismatch',
        'device_station': 'finishing',
        'requested_station': 'painting',
    }), 403


# ---- stałe --------------------------------------------------------------

def test_403_jest_na_liscie_ponowien_api_produkcyjnego():
    assert 403 in BLEDY_DO_PONOWIENIA


def test_403_jest_na_liscie_ponowien_trakowni():
    """Trakownia trzyma własną kopię listy i ma ten sam mechanizm 403."""
    assert 403 in BLEDY_DO_PONOWIENIA_TRAKOWNI


# ---- zachowanie ---------------------------------------------------------

def test_403_station_mismatch_nie_zapisuje_wpisu_idempotencji(app):
    """
    403 ma zachowywać się jak 5xx: rollback i BRAK wpisu w
    processed_mobile_operations, żeby akcja została w kolejce tabletu.
    """
    @with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
    def handler():
        return _odpowiedz_station_mismatch()

    with app.test_request_context(
        '/api/mobile/orders/1/complete',
        headers={'X-Operation-Id': 'op-403-1'},
    ):
        _, status = handler()

    assert status == 403
    with app.app_context():
        assert ProcessedMobileOperation.query.count() == 0


def test_403_station_mismatch_pozwala_na_retry(app):
    """
    Scenariusz ratunkowy end-to-end: pierwsze żądanie trafia na rozjazd
    rejestracji i dostaje 403. Po naprawie przyczyny tablet ponawia wpis z TYM
    SAMYM X-Operation-Id — handler MUSI zostać wywołany ponownie, a odbite
    sztuki zapisane.
    """
    wywolania = {'n': 0}

    @with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
    def handler():
        wywolania['n'] += 1
        if wywolania['n'] == 1:
            return _odpowiedz_station_mismatch()
        return jsonify({'ok': True}), 200

    with app.test_request_context('/x', headers={'X-Operation-Id': 'op-403-2'}):
        _, status1 = handler()
    with app.test_request_context('/x', headers={'X-Operation-Id': 'op-403-2'}):
        _, status2 = handler()

    assert status1 == 403
    assert status2 == 200
    assert wywolania['n'] == 2, (
        u'handler nie został wywołany ponownie — 403 zostało odtworzone '
        u'z processed_mobile_operations, czyli praca z kolejki offline przepadła'
    )
    with app.app_context():
        assert ProcessedMobileOperation.query.count() == 1
        assert ProcessedMobileOperation.query.first().response_status == 200


def test_422_nadal_jest_zapamietywane(app):
    """
    Strażnik zakresu: rozszerzamy listę o JEDEN kod, nie o całe 4xx. 422
    (np. odrzucony powód zakończenia sesji) to błąd żądania, który po
    ponowieniu dałby ten sam wynik — ma dalej być zapamiętywany, żeby tablet
    nie kręcił się w kółko.
    """
    @with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
    def handler():
        return jsonify({'error': 'invalid_reason'}), 422

    with app.test_request_context('/y', headers={'X-Operation-Id': 'op-422-1'}):
        _, status = handler()

    assert status == 422
    with app.app_context():
        assert ProcessedMobileOperation.query.count() == 1
