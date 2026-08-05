# -*- coding: utf-8 -*-
"""Zmiany w istniejącym kodzie, od których zależy trakownia."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect

from sqlalchemy import Text

from modules.production.models import ProcessedMobileOperation, ProductionDevice
from modules.production.services.mobile_api_service import (
    _STATION_CODES_WITH_TABLETS,
    cleanup_old_operations,
    with_idempotency,
)
from modules.users.decorators import require_module_access


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
