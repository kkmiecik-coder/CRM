# -*- coding: utf-8 -*-
"""Wymiar zlozony w wg_wymiaru: grupowanie po kilku kolumnach naraz.

Dwa niezmienniki, ktore te testy pilnuja:
1. WSTECZNA ZGODNOSC. Wymiar jednokolumnowy ma dawac dokladnie to, co dawal
   przed zmiana — z surowa wartoscia kolumny w kluczu `wartosc`, a nie
   z jednoelementowa krotka. aggregates.py jest zweryfikowany na produkcyjnych
   danych i zmiana ksztaltu wyniku zepsulaby kazdego konsumenta naraz.
2. Wymiar zlozony NIE JEST kolumna. Nie ma go w zadnym modelu, wiec
   getattr(SalesOrderItem, 'konfiguracja') musi sie wywalac — to jest cel,
   a nie usterka. Grupowanie idzie po jego skladnikach.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.aggregates import SEPARATOR_ZLOZONY, kolumny_wymiaru, wg_wymiaru
from modules.reports.fields import POLA, wymiary, wymiary_proste
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Blok "rejestr mapperow" — bez niego SQLAlchemy rzuca InvalidRequestError przy
# pierwszym query. User ma relationship('Multiplier') podana stringiem i nie
# rozwiaze jej, dopoki caly graf modeli nie jest zaimportowany. Ten sam gotcha
# i to samo rozwiazanie co w tests/test_sales_aggregates.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]


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


def _zamowienie(bl_id, dzien, kanal='shop', pozycje=()):
    """pozycje: lista krotek (netto, objetosc, grupa, gatunek, technologia, klasa)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal('0'), order_source=kanal,
                     caretaker='Łukasz Próbny')
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa, gatunek, technologia, klasa in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type=grupa, wood_species=gatunek, technology=technologia,
            wood_class=klasa, quantity=1))
    return zam


OKRES = (date(2026, 9, 1), date(2026, 9, 30))


# --- rejestr ----------------------------------------------------------------

def test_rejestr_zna_konfiguracje_jako_wymiar_zlozony():
    pole = POLA['konfiguracja']
    assert pole.wymiar is True
    assert pole.skladniki == ('wood_species', 'technology', 'wood_class')
    assert pole.etykieta == 'Gatunek · technologia · klasa'
    assert 'konfiguracja' in wymiary()


def test_skladniki_wymiaru_zlozonego_sa_polami_rejestru():
    """Literowka w skladniku wywali sie dopiero przy pierwszym grupowaniu."""
    for nazwa, pole in POLA.items():
        if pole.skladniki is None:
            continue
        for skladnik in pole.skladniki:
            assert skladnik in POLA, f'{nazwa}: skladnik {skladnik} spoza rejestru'


def test_wymiary_proste_pomijaja_zlozone():
    """Po wymiarze zlozonym nie filtrujemy — jego wartosc nie przechodzi
    przez format filtra w adresie (Zadanie 2)."""
    assert 'konfiguracja' not in wymiary_proste()
    assert 'wood_species' in wymiary_proste()
    assert set(wymiary_proste()) | {'konfiguracja'} == set(wymiary())


def test_wymiar_zlozony_nie_ma_kolumny_w_modelu():
    """Celowo: to byt rejestru, nie kolumna bazy. Arkusz Planu C ma go pomijac
    po `pole.skladniki is not None`, a nie probowac wyrenderowac."""
    assert not hasattr(SalesOrderItem, 'konfiguracja')
    assert not hasattr(SalesOrder, 'konfiguracja')


def test_etykieta_kanalu_brzmi_jak_w_makiecie():
    """Makieta (Main.dc.html:175, Eksplorator.dc.html) mowi „Kanal sprzedazy",
    a teksty interfejsu sa w README makiet wymienione jako wiazace."""
    assert POLA['order_source'].etykieta == 'Kanał sprzedaży'


# --- kolumny_wymiaru --------------------------------------------------------

def test_kolumny_wymiaru_dla_prostego_daje_jedna_kolumne(app):
    with app.app_context():
        assert len(kolumny_wymiaru('order_source')) == 1
        assert len(kolumny_wymiaru('wood_species')) == 1


def test_kolumny_wymiaru_dla_zlozonego_daje_trzy_kolumny(app):
    with app.app_context():
        kolumny = kolumny_wymiaru('konfiguracja')
        assert [k.key for k in kolumny] == ['wood_species', 'technology', 'wood_class']


def test_kolumny_wymiaru_odrzuca_nazwe_spoza_rejestru(app):
    with app.app_context():
        with pytest.raises(ValueError):
            kolumny_wymiaru('paid_cash')


def test_kolumny_wymiaru_odrzuca_pole_z_modulu_produkcji(app):
    with app.app_context():
        with pytest.raises(ValueError):
            kolumny_wymiaru('gluing_done_at')


# --- regresja: wymiar jednokolumnowy ----------------------------------------

def test_regresja_wymiar_prosty_po_zamowieniu_bez_zmian(app):
    """Ksztalt wyniku ma byc identyczny jak przed zmiana: `wartosc` to surowa
    wartosc kolumny, NIE krotka jednoelementowa."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop',
                    [('750.00', '0.50', 'towar', 'dąb', 'lity', 'A/B')])
        _zamowienie(2, date(2026, 9, 3), 'allegro',
                    [('250.00', '0.20', 'towar', 'dąb', 'lity', 'A/B')])
        db.session.commit()

        wiersze = wg_wymiaru('order_source', *OKRES)

        assert [w['wartosc'] for w in wiersze] == ['shop', 'allegro']
        # `sztuki` (24.09.2026) — sztuki produktow z tego samego zapytania.
        assert wiersze[0] == {'wartosc': 'shop', 'netto': Decimal('750.00'),
                              'objetosc': Decimal('0.50'), 'sztuki': 1,
                              'zamowienia': 1}


def test_regresja_wymiar_prosty_po_pozycji_bez_zmian(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop', [
            ('600.00', '0.30', 'towar', 'dąb', 'lity', 'A/B'),
            ('400.00', '0.20', 'towar', 'jesion', 'mikrowczep', 'A/B'),
        ])
        db.session.commit()

        wiersze = wg_wymiaru('wood_species', *OKRES)

        assert [w['wartosc'] for w in wiersze] == ['dąb', 'jesion']
        assert wiersze[1]['netto'] == Decimal('400.00')


def test_regresja_wymiar_prosty_z_pusta_wartoscia_nadal_daje_None(app):
    """`(brak)` powstaje dopiero w serwisie — agregat oddaje surowe None."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), None,
                    [('100.00', '0.10', 'towar', 'dąb', 'lity', 'A/B')])
        db.session.commit()

        assert wg_wymiaru('order_source', *OKRES)[0]['wartosc'] is None


# --- wymiar złożony ---------------------------------------------------------

def test_zlozony_grupuje_po_trzech_kolumnach_naraz(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop', [
            ('600.00', '0.30', 'towar', 'dąb', 'lity', 'A/B'),
            ('400.00', '0.20', 'towar', 'dąb', 'lity', 'A/B'),
        ])
        db.session.commit()

        wiersze = wg_wymiaru('konfiguracja', *OKRES)

        assert len(wiersze) == 1
        assert wiersze[0]['wartosc'] == ('dąb', 'lity', 'A/B')
        assert wiersze[0]['netto'] == Decimal('1000.00')
        assert wiersze[0]['objetosc'] == Decimal('0.50')


def test_zlozony_rozdziela_rozne_kombinacje(app):
    """Ten sam gatunek w dwoch technologiach to DWA wiersze."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop', [
            ('600.00', '0.30', 'towar', 'dąb', 'lity', 'A/B'),
            ('400.00', '0.20', 'towar', 'dąb', 'mikrowczep', 'A/B'),
            ('100.00', '0.05', 'towar', 'dąb', 'lity', 'B/B'),
        ])
        db.session.commit()

        wiersze = wg_wymiaru('konfiguracja', *OKRES)

        assert len(wiersze) == 3
        assert wiersze[0]['wartosc'] == ('dąb', 'lity', 'A/B')
        assert {w['wartosc'] for w in wiersze} == {
            ('dąb', 'lity', 'A/B'), ('dąb', 'mikrowczep', 'A/B'), ('dąb', 'lity', 'B/B')}


def test_zlozony_z_pusta_skladowa_nie_gubi_wiersza(app):
    """Parser nie zawsze wyciaga klase z nazwy produktu — taki wiersz ma
    zostac, z None w skladowej, a nie wypasc z karty."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop',
                    [('300.00', '0.10', 'towar', 'dąb', 'lity', None)])
        db.session.commit()

        wiersze = wg_wymiaru('konfiguracja', *OKRES)

        assert len(wiersze) == 1
        assert wiersze[0]['wartosc'] == ('dąb', 'lity', None)


def test_zlozony_wyklucza_uslugi_z_objetosci(app):
    """Pulapka nr 2 Planu A obowiazuje tak samo w wymiarze zlozonym."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop', [
            ('1000.00', '2.50', 'towar', 'dąb', 'lity', 'A/B'),
            ('800.00', '88.00', 'usługa', 'dąb', 'lity', 'A/B'),
        ])
        db.session.commit()

        wiersz = wg_wymiaru('konfiguracja', *OKRES)[0]

        assert wiersz['objetosc'] == Decimal('2.50')
        assert wiersz['netto'] == Decimal('1800.00')


def test_zlozony_liczy_zamowienia_przez_distinct(app):
    """Dwie pozycje tej samej konfiguracji w jednym zamowieniu to JEDNO
    zamowienie, nie dwa."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), 'shop', [
            ('600.00', '0.30', 'towar', 'dąb', 'lity', 'A/B'),
            ('400.00', '0.20', 'towar', 'dąb', 'lity', 'A/B'),
        ])
        _zamowienie(2, date(2026, 9, 3), 'shop',
                    [('100.00', '0.10', 'towar', 'dąb', 'lity', 'A/B')])
        db.session.commit()

        assert wg_wymiaru('konfiguracja', *OKRES)[0]['zamowienia'] == 2


def test_separator_zlozonego_jest_srodkowa_kropka():
    """Etykiete sklejamy w serwisie, ale separator ma jedno zrodlo."""
    assert SEPARATOR_ZLOZONY == ' · '
