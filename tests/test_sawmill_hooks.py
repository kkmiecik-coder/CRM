# -*- coding: utf-8 -*-
"""Zmiany w istniejącym kodzie, od których zależy trakownia."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect
from datetime import timedelta

import pytest
from flask import Flask, jsonify, session
from sqlalchemy import Text
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation,
    ProductionDevice,
    get_local_now,
)
from modules.production.services.mobile_api_service import (
    _STATION_CODES_WITH_TABLETS,
    cleanup_old_operations,
    with_idempotency,
)
from modules.users.decorators import require_module_access
from modules.users.services.permission_service import PermissionService
# Importy poniżej same w sobie nie są używane w testach z tego pliku, ale
# rejestrują mappery, których configure_mappers() (wywoływane przy pierwszym
# query/flush na JAKIMKOLWIEK modelu w procesie) potrzebuje do rozwiązania
# relationshipów zdefiniowanych w modules/users/models.py (User.multiplier).
# Identyczne uzasadnienie i wzorzec jak w tests/test_sawmill_numbering.py
# oraz tests/test_bot_api_by_token_integration.py.
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401 — rejestracja tabeli 'multipliers'
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus  # noqa: F401


def test_sawmill_jest_dozwolonym_kodem_stanowiska():
    assert 'sawmill' in ProductionDevice.VALID_STATION_CODES


def test_sawmill_ma_telemetrie():
    """Bez tego build_devices_telemetry po cichu odfiltruje trak."""
    assert 'sawmill' in _STATION_CODES_WITH_TABLETS


def test_idempotency_przyjmuje_retryable_statuses():
    params = inspect.signature(with_idempotency).parameters
    assert 'retryable_statuses' in params


def test_idempotency_dziala_nadal_bez_nawiasow():
    """Istniejące stanowiska używają @with_idempotency bez wywołania."""
    def handler():
        return {'ok': True}, 200
    owinięty = with_idempotency(handler)
    assert callable(owinięty)


def test_cleanup_przyjmuje_retencje_per_endpoint():
    params = inspect.signature(cleanup_old_operations).parameters
    assert 'endpoint_retention' in params


def test_dekorator_dostepu_ma_wariant_json():
    params = inspect.signature(require_module_access).parameters
    assert 'as_json' in params


def test_longtext_ma_wariant_sqlite():
    """
    Bez tego nie da się zbudować tabeli idempotencji w testach na SQLite.

    Uwaga: `.dialect_impl()` na typie z `with_variant()` w SQLAlchemy 1.4 zawsze
    zwraca obiekt `Variant` (kopię zewnętrznego TypeDecorator z podmienionym
    `.impl`), nigdy bezpośrednio typ docelowy — to udokumentowana mechanika
    `TypeDecorator._gen_dialect_impl`, nie błąd tej kolumny. Właściwym API do
    pobrania faktycznego, rozwiniętego typu dla danego dialektu jest
    `.type_engine()`. Realny cel with_variant (poprawne DDL) weryfikujemy przez
    `.compile(dialect=...)`.
    """
    kolumna = ProcessedMobileOperation.__table__.c.response_body
    dialekt_sqlite = __import__(
        'sqlalchemy.dialects.sqlite', fromlist=['dialect']
    ).dialect()

    typ_dla_sqlite = kolumna.type.type_engine(dialekt_sqlite)
    assert isinstance(typ_dla_sqlite, Text)

    # I to, co faktycznie ma znaczenie dla `db.metadata.create_all` na SQLite:
    # wygenerowane DDL to TEXT, nie (nieobsługiwane przez SQLite) LONGTEXT.
    assert kolumna.type.compile(dialect=dialekt_sqlite) == 'TEXT'


# ============================================================================
# TESTY ZACHOWANIA (recenzja Zadania 5) — nie tylko sygnatury, ale realne
# efekty w bazie / odpowiedziach HTTP.
# ============================================================================

_TABLES = [ProcessedMobileOperation.__table__]


@pytest.fixture()
def app():
    """Minimalny Flask + SQLAlchemy na SQLite in-memory (StaticPool — jedno
    współdzielone połączenie, żeby zapisy w jednym request-contexcie były
    widoczne w kolejnych zapytaniach w tym samym teście)."""
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


# ---- a) with_idempotency(retryable_statuses={409}) -----------------------

def test_idempotency_retryable_status_nie_zapisuje_wpisu(app):
    """
    409 wymieniony w retryable_statuses ma zachowywać się jak 5xx: rollback
    i BRAK wpisu w processed_mobile_operations. Inaczej po ponownym otwarciu
    zlecenia ten sam X-Operation-Id odtworzyłby zapamiętane 409 bez
    wywołania handlera i pomiar z trakowni przepadłby bezpowrotnie.
    """
    @with_idempotency(retryable_statuses={409})
    def handler():
        return jsonify({'error': 'conflict'}), 409

    with app.test_request_context(
        '/api/mobile/sawmill/measurements',
        headers={'X-Operation-Id': 'op-retryable-1'},
    ):
        _, status = handler()
        assert status == 409
        assert ProcessedMobileOperation.query.count() == 0


def test_idempotency_409_bez_retryable_statuses_zapisuje_wpis(app):
    """
    Bez retryable_statuses (istniejące stanowiska, @with_idempotency zwykłe
    lub z pustym zbiorem) 409 to zwykły status 4xx — dekorator go zapisuje
    jak dotąd. Potwierdza brak regresji domyślnego zachowania.
    """
    @with_idempotency
    def handler():
        return jsonify({'error': 'conflict'}), 409

    with app.test_request_context(
        '/api/mobile/cutting/complete',
        headers={'X-Operation-Id': 'op-plain-1'},
    ):
        _, status = handler()
        assert status == 409
        assert ProcessedMobileOperation.query.count() == 1
        zapisany = ProcessedMobileOperation.query.first()
        assert zapisany.operation_id == 'op-plain-1'
        assert zapisany.response_status == 409


def test_idempotency_retryable_status_pozwala_na_retry(app):
    """
    Scenariusz ratunkowy trakowni end-to-end: pierwszy request dostaje 409
    (retryable) — nic nie zapisano, więc drugi request z TYM SAMYM
    X-Operation-Id nie trafia na replay i faktycznie wywołuje handler
    ponownie (tak jak tablet ponawiający pomiar po otwarciu zlecenia).
    """
    wywolania = {'n': 0}

    @with_idempotency(retryable_statuses={409})
    def handler():
        wywolania['n'] += 1
        if wywolania['n'] == 1:
            return jsonify({'error': 'conflict'}), 409
        return jsonify({'ok': True}), 200

    with app.test_request_context('/x', headers={'X-Operation-Id': 'op-retry-2'}):
        _, status1 = handler()
    with app.test_request_context('/x', headers={'X-Operation-Id': 'op-retry-2'}):
        _, status2 = handler()

    assert status1 == 409
    assert status2 == 200
    assert wywolania['n'] == 2
    with app.app_context():
        assert ProcessedMobileOperation.query.count() == 1
        assert ProcessedMobileOperation.query.first().response_status == 200


# ---- b) cleanup_old_operations(endpoint_retention=...) -------------------

def test_cleanup_endpoint_retention_chroni_prefiks_ale_nie_wildcard_lookalike(app):
    """
    Wiersze z prefiksem objętym dłuższą retencją przeżywają domyślne
    czyszczenie, pozostałe (na domyślnej retencji) nie. Pokrywa też naprawę
    z punktu 1: endpoint dopasowujący się do wzorca TYLKO przez wildcard `_`
    (np. 'sawmillXmobile.cos' pod LIKE 'sawmill_mobile.%' bez ESCAPE) nie
    może być potraktowany jak trakownia — musi wpaść pod domyślną (krótszą)
    retencję i zostać usunięty.
    """
    now = get_local_now()
    with app.app_context():
        wiersze = {
            # Prawdziwy prefiks trakowni, 10 dni — młodszy niż jej retencja
            # (31 dni), więc ma przeżyć.
            'sawmill-old-protected': ('sawmill_mobile.record', now - timedelta(days=10)),
            # Prawdziwy prefiks trakowni, 35 dni — starszy niż jej retencja,
            # ma zostać usunięty przez pętlę per-prefiks.
            'sawmill-very-old-expired': ('sawmill_mobile.record', now - timedelta(days=35)),
            # Inne stanowisko, domyślna retencja (7 dni), 10 dni — usunięte.
            'cutting-old': ('cutting_mobile.complete', now - timedelta(days=10)),
            # Inne stanowisko, domyślna retencja, 3 dni — przeżywa.
            'cutting-fresh': ('cutting_mobile.complete', now - timedelta(days=3)),
            # Regresja z punktu 1: NIE zaczyna się dosłownie od 'sawmill_mobile.'
            # (drugi znak to 'X', nie '_'), ale bez ESCAPE dopasowałby się do
            # LIKE 'sawmill_mobile.%'. 10 dni — starszy niż domyślne 7, więc
            # musi zostać usunięty (nie chroniony 31-dniową retencją trakowni).
            'wildcard-lookalike': ('sawmillXmobile.cos', now - timedelta(days=10)),
        }
        for op_id, (endpoint, processed_at) in wiersze.items():
            db.session.add(ProcessedMobileOperation(
                operation_id=op_id,
                endpoint=endpoint,
                response_status=200,
                response_body='{}',
                processed_at=processed_at,
            ))
        db.session.commit()

        cleanup_old_operations(
            older_than_days=7,
            endpoint_retention={'sawmill_mobile.': 31},
        )

        pozostale = {r.operation_id for r in ProcessedMobileOperation.query.all()}
        assert pozostale == {'sawmill-old-protected', 'cutting-fresh'}


# ---- c) require_module_access(..., as_json=True) --------------------------

@pytest.fixture()
def perm_app():
    """Osobna, lekka apka Flask (bez DB) — require_module_access ma dwie
    ścieżki wyjścia zanim dotknie bazy (brak sesji), a dla ścieżki
    „brak uprawnień" PermissionService jest zamockowany, więc DB nie jest
    tu potrzebne."""
    flask_app = Flask(__name__)
    flask_app.config['SECRET_KEY'] = 'test-secret'
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    flask_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login-page')
    db.init_app(flask_app)
    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[User.__table__])
        yield flask_app
        db.session.remove()


def test_require_module_access_as_json_401_bez_sesji(perm_app):
    """Brak sesji + as_json=True → 401 JSON, bez redirectu/HTML."""
    @require_module_access('trakownia', as_json=True)
    def widok():
        return jsonify({'ok': True})

    with perm_app.test_request_context('/api/mobile/sawmill/queue'):
        response, status = widok()
        assert status == 401
        assert response.get_json() == {'error': 'unauthorized'}


def test_require_module_access_bez_as_json_zwraca_redirect_jak_dotad(perm_app):
    """Bez as_json (domyślnie False) zachowanie ma pozostać identyczne:
    redirect na login, nie JSON — brak regresji dla istniejących stanowisk
    webowych korzystających z tego dekoratora."""
    @require_module_access('trakownia')
    def widok():
        return 'ok'

    with perm_app.test_request_context('/production/dashboard'):
        response = widok()
        assert response.status_code == 302
        assert '/login' in response.headers['Location']


def test_require_module_access_as_json_403_brak_uprawnien(perm_app, monkeypatch):
    """Zalogowany, aktywny user bez dostępu do modułu + as_json=True →
    403 JSON, bez render_template (który wymagałby access_denied.html)."""
    with perm_app.app_context():
        user = User(email='trak@woodpower.pl', password='x', active=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    monkeypatch.setattr(
        PermissionService, 'user_has_module_access',
        staticmethod(lambda uid, module_key: False),
    )

    @require_module_access('trakownia', as_json=True)
    def widok():
        return jsonify({'ok': True})

    with perm_app.test_request_context('/api/mobile/sawmill/queue'):
        session['user_email'] = 'trak@woodpower.pl'
        response, status = widok()
        assert status == 403
        assert response.get_json() == {'error': 'module_access_denied'}


# ---- b) with_idempotency(require_operation_id=True) ----------------------

def test_idempotency_przyjmuje_require_operation_id():
    params = inspect.signature(with_idempotency).parameters
    assert 'require_operation_id' in params
    # Domyślnie WYŁĄCZONE — ten sam dekorator obsługuje stanowiska produkcji,
    # których aplikacja Android jest już wdrożona na produkcji.
    assert params['require_operation_id'].default is False


def test_brak_naglowka_bez_wymogu_wykonuje_handler(app):
    """
    REGRESJA CHRONIĄCA WDROŻONĄ FLOTĘ: endpointy pozostałych stanowisk
    (@with_idempotency bez argumentów) muszą dalej działać bez nagłówka.
    Zaostrzenie globalne popsułoby tablety pracujące dziś na hali.
    """
    wywolania = []

    @with_idempotency
    def handler():
        wywolania.append(1)
        return jsonify({'ok': True}), 200

    with app.test_request_context('/api/mobile/complete'):
        _, status = handler()
        assert status == 200
        assert wywolania == [1]


def test_brak_naglowka_z_wymogiem_daje_400_i_nie_wola_handlera(app):
    wywolania = []

    @with_idempotency(require_operation_id=True)
    def handler():
        wywolania.append(1)
        return jsonify({'ok': True}), 200

    with app.test_request_context('/api/mobile/sawmill/measurements'):
        response, status = handler()
        assert status == 400
        assert response.get_json()['error'] == 'missing_operation_id'
        # Handler nie może się wykonać — inaczej sprawdzenie byłoby po zapisie.
        assert wywolania == []


def test_wymog_nie_psuje_dzialania_z_naglowkiem(app):
    @with_idempotency(retryable_statuses={409}, require_operation_id=True)
    def handler():
        return jsonify({'ok': True}), 200

    with app.test_request_context(
        '/api/mobile/sawmill/measurements',
        headers={'X-Operation-Id': 'op-wymog-hook-1'},
    ):
        _, status = handler()
        assert status == 200
        assert ProcessedMobileOperation.query.count() == 1
