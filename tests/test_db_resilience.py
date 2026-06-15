"""Testy wykrywania zatrutego/rozsynchronizowanego połączenia MySQL.

Gdy pula odda połączenie w stanie "commands out of sync", SELECT wraca z
kursorem bez opisu kolumn → SQLAlchemy buduje wynik na _NoResultMetaData, a
odczyt wiersza woła _indexes_for_keys i leci CZYSTYM AttributeError (NIE
SQLAlchemyError). Taki wyjątek omija wszystkie handlery DB w app.py, dlatego
musimy go rozpoznać po podpisie — ale tylko jego, nie zwykłych bugów.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_resilience import is_corrupted_result_error


def test_podpis_no_result_metadata_jest_zatruty():
    exc = AttributeError("'_NoResultMetaData' object has no attribute '_indexes_for_keys'")
    assert is_corrupted_result_error(exc) is True


def test_sam_indexes_for_keys_wystarcza():
    exc = AttributeError("something about _indexes_for_keys here")
    assert is_corrupted_result_error(exc) is True


def test_zwykly_attribute_error_nie_jest_zatruty():
    exc = AttributeError("'NoneType' object has no attribute 'email'")
    assert is_corrupted_result_error(exc) is False


def test_inny_typ_wyjatku_nie_jest_zatruty():
    # Tylko AttributeError jest objawem tego konkretnego rozsynchronizowania.
    assert is_corrupted_result_error(ValueError("_NoResultMetaData")) is False


def test_none_nie_wybucha():
    assert is_corrupted_result_error(None) is False


# --- Test kontraktu handlera (na minimalnej aplikacji, bez prawdziwej DB) ----
# Odwzorowuje logikę @app.errorhandler(AttributeError) z app.py: zatrute
# połączenie → invalidate + 500; zwykły AttributeError → leci dalej.
import pytest
from flask import Flask, jsonify


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app._invalidated = []

    @flask_app.errorhandler(AttributeError)
    def handle_corrupted_connection(e):
        if not is_corrupted_result_error(e):
            raise e
        flask_app._invalidated.append(True)
        return jsonify({'error': 'database_error'}), 500

    @flask_app.route('/zatrute')
    def zatrute():
        raise AttributeError("'_NoResultMetaData' object has no attribute '_indexes_for_keys'")

    @flask_app.route('/zwykly-bug')
    def zwykly_bug():
        raise AttributeError("'NoneType' object has no attribute 'email'")

    return flask_app


def test_zatrute_polaczenie_jest_obsluzone_i_invalidowane(app):
    with app.test_client() as c:
        r = c.get('/zatrute')
        assert r.status_code == 500
        assert r.json['error'] == 'database_error'
    assert app._invalidated == [True]


def test_zwykly_bug_nie_jest_obslugiwany_jako_db(app):
    # Prawdziwy AttributeError musi lecieć dalej jako nieobsłużony błąd.
    app.testing = True
    with app.test_client() as c:
        with pytest.raises(AttributeError):
            c.get('/zwykly-bug')
    assert app._invalidated == []
