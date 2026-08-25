# -*- coding: utf-8 -*-
"""Wysyłka dziennego raportu produkcji."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db, mail
from modules.production.models import ProductionConfig
from modules.production.services import config_service, report_mailer

# ProductionConfig.updated_by ma ForeignKey('users.id'). Metadata tego procesu
# nigdy nie widziała tabeli users (moduł production jej nie importuje), więc
# bez tego importu create_all([ProductionConfig.__table__]) wybucha przy
# rozwiązywaniu FK: NoReferencedTableError. Samego Usera nie tworzymy w bazie —
# rejestracja definicji tabeli w metadata wystarczy.
from modules.users.models import User  # noqa: F401
# User.multiplier -> Multiplier -> Quote -> Client -> ... łańcuch relationshipów
# stringowych ciągnie się dalej niż samo User. SQLAlchemy konfiguruje WSZYSTKIE
# zarejestrowane mappery na raz (configure_mappers()), więc każdy człon musi
# być zaimportowany, choć tworzymy tylko tabelę ProductionConfig. Ten sam
# zestaw importów co w tests/test_daily_report.py, z tego samego powodu.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

PONIEDZIALEK = date(2026, 8, 10)

DANE = {
    'dzien': PONIEDZIALEK,
    'wykonanie': {'sztuki': 342, 'm3': 4.187, 'wartosc_netto': 28450.0,
                  'pozycje': 51, 'zamowienia': 18, 'cofniecia': 4},
    'ludzie': {'osoby': 5, 'godziny': 37.5, 'pokrycie_proc': 92.0,
               'wiersze': [], 'nieprzypisane': {'sztuki': 0.0, 'm3': 0.0}},
    'trakownia': {'klody': 12, 'm3': 8.4},
    'stanowiska': [{'kod': 'gluing', 'etykieta': 'Sklejanie', 'sztuki': 342,
                    'm3': 4.187, 'wartosc_netto': 28450.0, 'cofniecia': 4,
                    'kolejka_szt': 1204, 'kolejka_m3': 15.3}],
    'terminy': {'po_terminie': 18, 'dzis': 3, '1_2_dni': 7,
                '3_7_dni': 12, '8_dni_plus': 40, 'bez_terminu': 2},
}


# Katalog szablonow produkcji liczony od korzenia repo. Flask(__name__) w pliku
# testu ma root_path = tests/, wiec sciezka wzgledna prowadzilaby do
# nieistniejacego tests/modules/production/templates.
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
    app.config['MAIL_SUPPRESS_SEND'] = True
    db.init_app(app)
    mail.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine,
                               tables=[ProductionConfig.__table__])
        yield app
        db.session.remove()


def _ustaw_odbiorcow(wartosc):
    db.session.add(ProductionConfig(config_key='DAILY_REPORT_RECIPIENTS',
                                    config_value=wartosc, config_type='string'))
    db.session.commit()
    # get_config() czyta przez ProductionConfigService — proces-wide singleton
    # z cache TTL=60 min (modules/production/services/config_service.py).
    # Bez invalidacji kolejny test (nowa baza in-memory, ten sam proces
    # pytest) dostałby odpowiedź z cache poprzedniego testu zamiast świeżego
    # zapytania do swojej własnej bazy.
    config_service.invalidate_config_cache()


def test_odbiorcy_z_konfiguracji(app):
    with app.app_context():
        _ustaw_odbiorcow(' konrad@woodpower.pl , biuro@woodpower.pl ')

        assert report_mailer.odbiorcy() == ['konrad@woodpower.pl',
                                            'biuro@woodpower.pl']


def test_pusta_lista_odbiorcow_nie_wysyla(app):
    """Pusta konfiguracja jest wyłącznikiem funkcji, nie błędem."""
    with app.app_context():
        _ustaw_odbiorcow('')

        with mail.record_messages() as wyslane:
            ile = report_mailer.wyslij_raport(DANE, b'udawane-bajty')

        assert ile == 0
        assert wyslane == []


def test_mail_ma_zalacznik_i_temat(app):
    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        with mail.record_messages() as wyslane:
            ile = report_mailer.wyslij_raport(DANE, b'udawane-bajty')

        assert ile == 1
        msg = wyslane[0]
        assert msg.subject == 'Raport produkcji — 10.08.2026 (poniedziałek)'
        assert msg.recipients == ['konrad@woodpower.pl']
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == 'Raport_produkcji_2026-08-10.xlsx'
        assert msg.attachments[0].content_type == (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def test_tresc_maila_ma_kluczowe_liczby(app):
    """
    O 18:00 na telefonie najpierw widać treść, a załącznik otwiera się
    świadomie — najważniejsze liczby muszą być w treści.
    """
    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(DANE, b'udawane-bajty')

        tresc = wyslane[0].html
        assert '342' in tresc            # sztuki
        assert '28 450' in tresc or '28450' in tresc   # wartość
        assert '92' in tresc             # pokrycie
        assert '18' in tresc             # po terminie
        assert 'serwer2100532.home.pl' not in tresc    # logo z serwera do dekomisji


def test_odbiorcy_podani_wprost_maja_pierwszenstwo(app):
    """Tryb testowy komendy CLI: --do nie rusza konfiguracji."""
    with app.app_context():
        _ustaw_odbiorcow('biuro@woodpower.pl')

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(DANE, b'udawane-bajty',
                                        odbiorcy=['test@woodpower.pl'])

        assert wyslane[0].recipients == ['test@woodpower.pl']


def test_brak_pokrycia_nie_wypisuje_none(app):
    """
    pokrycie_atrybucji_dziennie() zwraca None, gdy nie było ŻADNEGO ruchu —
    świadomie, żeby nie kłamać zerem (reports_service.py:938). Raport idzie
    także w taki dzień (brak maila ma znaczyć awarię, a cron 1-5 nie zna świąt:
    1 maja czy 11 listopada w dzień roboczy odpali przebieg), więc szablon
    musi pokazać myślnik. Wprost wstawiona wartość dawała „(pokrycie None%)".
    """
    dane = dict(DANE)
    dane['ludzie'] = dict(DANE['ludzie'], osoby=0, godziny=0.0,
                          pokrycie_proc=None)

    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(dane, b'udawane-bajty')

        tresc = wyslane[0].html
        assert 'None' not in tresc
        assert 'pokrycie —' in tresc


def test_liczby_maja_polski_zapis_dziesietny(app):
    """
    Mail miesza jednostki w jednym zdaniu, więc nie może mieszać konwencji:
    „4.187 m³" obok „28 450 zł" wyglądało jak dwa różne raporty sklejone razem.
    """
    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(DANE, b'udawane-bajty')

        tresc = wyslane[0].html
        assert '4,187 m³' in tresc
        assert '37,5 h' in tresc
        assert '28 450 zł' in tresc
        assert '4.187' not in tresc
        assert '37.5' not in tresc


def test_odmiana_rzeczownika_po_liczbie(app):
    """„2 osób" i „1 kłód" to nie jest polski. Reguła: 1 / 2–4 / reszta."""
    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        dane = dict(DANE)
        dane['ludzie'] = dict(DANE['ludzie'], osoby=2)
        dane['trakownia'] = {'klody': 1, 'm3': 1.5}

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(dane, b'udawane-bajty')

        tresc = wyslane[0].html
        assert '2 osoby' in tresc
        assert '1 kłoda' in tresc

        dane['ludzie'] = dict(DANE['ludzie'], osoby=5)
        dane['trakownia'] = {'klody': 12, 'm3': 18.0}

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(dane, b'udawane-bajty')

        tresc = wyslane[0].html
        assert '5 osób' in tresc
        assert '12 kłód' in tresc


def test_kolejka_i_termin_to_osobne_zdania(app):
    """
    kolejka_szt liczy SZTUKI w statusach kolejkowych, terminy.po_terminie liczy
    POZYCJE w niemal wszystkich statusach. „0 szt. — w tym 18 pozycji po
    terminie" sugerowało podzbiór, którym te liczby nie są.
    """
    dane = dict(DANE)
    dane['stanowiska'] = [dict(DANE['stanowiska'][0], kolejka_szt=0,
                               kolejka_m3=0.0)]

    with app.app_context():
        _ustaw_odbiorcow('konrad@woodpower.pl')

        with mail.record_messages() as wyslane:
            report_mailer.wyslij_raport(dane, b'udawane-bajty')

        tresc = wyslane[0].html
        assert 'w tym 18' not in tresc
        assert 'Po terminie:' in tresc
