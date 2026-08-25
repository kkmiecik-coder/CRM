# -*- coding: utf-8 -*-
"""
Komenda CLI `flask raport-dzienny`.

To JEDYNE wejście produkcyjne całej funkcji: cron woła wrapper, wrapper woła
tę komendę i nic więcej. Kody wyjścia mają tu znaczenie operacyjne — na nich
stoi alarmowanie: cron hostingu mailuje wyjście przy niezerowym kodzie, więc
„brak odbiorców" MUSI kończyć się zerem (to wyłącznik funkcji), a awaria
wysyłki jedynką (to awaria).
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db, mail
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.sawmill.models import (
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder,
    SawmillSpecies, SawmillSupplier,
)
from modules.production.services import config_service
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

# Komenda jest zdefiniowana wewnątrz register_cli_commands() w app.py, więc
# nie da się jej wziąć bez zaimportowania tego modułu — a app.py tworzy na
# końcu instancję WSGI (`app = create_app()`). Ta instancja jest tu nieużywana
# i NIE służy do testu: wszystko jedzie na własnej aplikacji z fixture'a,
# z bazą SQLite w pamięci i zdławioną wysyłką maili.
from app import register_cli_commands

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
    SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery,
    SawmillOrder, SawmillLog, SawmillAudit,
)]

# shipping_label_base64 jest typem MySQL-owym (LONGTEXT) — SQLite go nie zna.
# Ta sama podmiana co w tests/test_daily_report.py:46.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

PONIEDZIALEK = date(2026, 8, 10)

# Katalog szablonów produkcji liczony od korzenia repo — Flask(__name__) w pliku
# testu ma root_path = tests/. Ta sama sztuczka co w test_daily_report_mail.py.
_SZABLONY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'templates')


@pytest.fixture()
def app():
    app = Flask(__name__, template_folder=_SZABLONY)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['MAIL_USERNAME'] = 'crm@woodpower.pl'
    # PRZED mail.init_app(): Flask-Mail zamraża tę flagę w stanie rozszerzenia
    # przy inicjalizacji, a późniejsze ustawienie config[] jest już ignorowane.
    # Na tym w tym projekcie raz otworzyło się realne połączenie SMTP z testu.
    app.config['MAIL_SUPPRESS_SEND'] = True
    db.init_app(app)
    mail.init_app(app)
    register_cli_commands(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        assert app.extensions['mail'].suppress is True
        yield app
        db.session.remove()


def _ustaw_odbiorcow(wartosc):
    db.session.add(ProductionConfig(config_key='DAILY_REPORT_RECIPIENTS',
                                    config_value=wartosc, config_type='string'))
    db.session.commit()
    # ProductionConfigService to singleton procesu z cache TTL=60 min — bez
    # invalidacji kolejny test dostałby odpowiedź z cache poprzedniego.
    config_service.invalidate_config_cache()


def _uruchom(app, *argumenty):
    return app.test_cli_runner().invoke(
        args=['raport-dzienny'] + list(argumenty))


# ============================================================================
# TRYB --sucho
# ============================================================================

def test_sucho_nie_wysyla_maila(app, monkeypatch):
    """
    Tryb do ręcznego sprawdzenia liczb przed wdrożeniem. Podmieniamy sam
    mail.send(), a nie polegamy na MAIL_SUPPRESS_SEND: chodzi o to, że kod
    W OGÓLE tam nie wchodzi, a nie o to, że wejście jest nieszkodliwe.
    """
    wywolania = []
    monkeypatch.setattr(mail, 'send', lambda msg: wywolania.append(msg))

    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat(), '--sucho')

        assert wynik.exit_code == 0, wynik.output
        assert wywolania == []
        assert 'mail nie został wysłany' in wynik.output


# ============================================================================
# KODY WYJŚCIA
# ============================================================================

def test_zla_data_konczy_sie_niezerowym_kodem(app):
    """Literówka w --data ma być głośna: cron mailuje wyjście przy błędzie."""
    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        wynik = _uruchom(app, '--data', '2026-13-99', '--sucho')

        assert wynik.exit_code != 0
        assert 'zła data' in wynik.output


def test_pusta_lista_odbiorcow_konczy_sie_zerem(app):
    """
    Pusta konfiguracja to WYŁĄCZNIK funkcji (nie ma osobnego klucza
    DAILY_REPORT_ENABLED), więc nie może wyglądać na awarię — inaczej cron
    mailowałby alarm codziennie o 18:00 przez cały okres wyłączenia.
    """
    with app.app_context():
        _ustaw_odbiorcow('')

        wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat())

        assert wynik.exit_code == 0, wynik.output
        assert 'DAILY_REPORT_RECIPIENTS' in wynik.output


def test_blad_wysylki_konczy_sie_jedynka(app, monkeypatch):
    """
    Awaria SMTP MUSI dać niezerowy kod — na tym stoi całe alarmowanie. Bez
    tego zerwana wysyłka byłaby niewidoczna tygodniami.
    """
    def wybuchnij(msg):
        raise RuntimeError('SMTP padł')

    monkeypatch.setattr(mail, 'send', wybuchnij)

    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat())

        assert wynik.exit_code == 1
        assert 'BŁĄD wysyłki' in wynik.output


# ============================================================================
# --do
# ============================================================================

def test_do_nadpisuje_konfiguracje_nie_modyfikujac_jej(app):
    """
    Tryb testowy: mail idzie pod wskazany adres, ale zapisana lista zostaje
    nietknięta — po ręcznym przebiegu z --do następny cron ma iść tam,
    gdzie szedł wcześniej.
    """
    with app.app_context():
        _ustaw_odbiorcow('biuro@woodpower.pl')

        with mail.record_messages() as wyslane:
            wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat(),
                             '--do', 'test@woodpower.pl')

        assert wynik.exit_code == 0, wynik.output
        assert len(wyslane) == 1
        assert wyslane[0].recipients == ['test@woodpower.pl']

        config_service.invalidate_config_cache()
        assert config_service.get_config('DAILY_REPORT_RECIPIENTS') == \
            'biuro@woodpower.pl'


def test_puste_do_nie_wskazuje_na_konfiguracje(app):
    """
    `--do ' , '` po strip() daje pustą listę, ale konfiguracja NIE była wtedy
    czytana — komunikat odsyłający do DAILY_REPORT_RECIPIENTS wysyłał
    wdrażającego pod zły adres.
    """
    with app.app_context():
        _ustaw_odbiorcow('biuro@woodpower.pl')

        wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat(),
                         '--do', ' , ')

        assert wynik.exit_code == 0, wynik.output
        assert '--do' in wynik.output
        assert 'DAILY_REPORT_RECIPIENTS' not in wynik.output


# ============================================================================
# --zapisz
# ============================================================================

def test_zapisz_tworzy_plik_xlsx(app, tmp_path):
    """--zapisz służy do podejrzenia arkusza bez ruszania skrzynki."""
    sciezka = tmp_path / 'raport.xlsx'

    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        wynik = _uruchom(app, '--data', PONIEDZIALEK.isoformat(),
                         '--zapisz', str(sciezka), '--sucho')

        assert wynik.exit_code == 0, wynik.output
        assert sciezka.exists()
        assert sciezka.read_bytes()[:2] == b'PK'   # nagłówek ZIP-a, czyli XLSX
