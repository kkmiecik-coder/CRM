# -*- coding: utf-8 -*-
"""Kaskada deduplikacji klienta: e-mail -> NIP -> telefon. Nigdy sama nazwa.

Dlaczego nie po nazwie: w arkuszu sprzedazowym 49 duplikatow bierze sie
wylacznie z wielkosci liter, a samo nazwisko i imie z nazwiskiem (np.
„Szablonowy" i „Jan Szablonowy") to dwa osobne wpisy tego samego klienta.
Dopasowanie po nazwie scalaloby rozne osoby i rozdzielalo te sama.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.dedup import (
    norm_email, norm_nip, norm_phone, znajdz_lub_utworz_klienta,
)
from modules.reports.models_sales import SalesClient

# Import czegokolwiek z modules.reports wykonuje modules/reports/__init__.py
# -> routers.py -> podpakiet modules.users, a User ma relacje db.relationship('Multiplier')
# podana stringiem. SQLAlchemy nie rozwiaze jej, dopoki caly graf modeli nie jest
# zaimportowany — ten sam gotcha i to samo rozwiazanie co w
# tests/test_bot_api_by_token_integration.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [SalesClient.__table__]


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


# --- normalizacja ---

def test_norm_email_male_litery_bez_spacji():
    assert norm_email('  Jan.Makietowy@Example.COM ') == 'jan.makietowy@example.com'


def test_norm_email_puste_daje_none():
    assert norm_email('') is None
    assert norm_email(None) is None
    assert norm_email('   ') is None


def test_norm_nip_same_cyfry():
    assert norm_nip('813-33-55-123') == '8133355123'
    assert norm_nip('PL 813 335 5123') == '8133355123'


def test_norm_phone_zdejmuje_prefiks_krajowy():
    assert norm_phone('+48 500 200 300') == '500200300'
    assert norm_phone('0048500200300') == '500200300'
    assert norm_phone('500-200-300') == '500200300'


def test_norm_phone_za_krotki_daje_none():
    """Cztery cyfry to nie numer telefonu, tylko smiec w kolumnie."""
    assert norm_phone('123') is None


# --- kaskada ---

def test_dopasowanie_po_mailu(app):
    with app.app_context():
        a = znajdz_lub_utworz_klienta(email='JAN@example.com', nip=None,
                                      phone=None, nazwa='Jan K.')
        db.session.commit()
        b = znajdz_lub_utworz_klienta(email='jan@EXAMPLE.com', nip=None,
                                      phone='500200300', nazwa='Jan Makietowy')
        db.session.commit()
        assert a.id == b.id
        assert SalesClient.query.count() == 1


def test_dopasowanie_po_nipie_gdy_mail_sie_zmienil(app):
    with app.app_context():
        a = znajdz_lub_utworz_klienta(email='stary@firma.pl', nip='8133355123',
                                      phone=None, nazwa='Firma')
        db.session.commit()
        b = znajdz_lub_utworz_klienta(email='nowy@firma.pl', nip='813-33-55-123',
                                      phone=None, nazwa='Firma')
        db.session.commit()
        assert a.id == b.id


def test_dopasowanie_po_telefonie_gdy_brak_maila_i_nipu(app):
    with app.app_context():
        a = znajdz_lub_utworz_klienta(email=None, nip=None,
                                      phone='500200300', nazwa='Klient')
        db.session.commit()
        b = znajdz_lub_utworz_klienta(email=None, nip=None,
                                      phone='+48500200300', nazwa='Klient')
        db.session.commit()
        assert a.id == b.id


def test_sama_nazwa_nigdy_nie_laczy(app):
    """Dwa rozne zamowienia od „Szablonowy" bez zadnego klucza to dwa rekordy."""
    with app.app_context():
        a = znajdz_lub_utworz_klienta(email=None, nip=None, phone=None, nazwa='Szablonowy')
        db.session.commit()
        b = znajdz_lub_utworz_klienta(email=None, nip=None, phone=None, nazwa='szablonowy')
        db.session.commit()
        assert a.id != b.id
        assert SalesClient.query.count() == 2


def test_brak_wszystkich_kluczy_oznacza_do_scalenia(app):
    with app.app_context():
        k = znajdz_lub_utworz_klienta(email=None, nip=None, phone=None, nazwa='Anonim')
        db.session.commit()
        assert k.needs_merge is True


def test_klient_z_kluczem_nie_jest_oznaczony(app):
    with app.app_context():
        k = znajdz_lub_utworz_klienta(email='a@b.pl', nip=None, phone=None, nazwa='A')
        db.session.commit()
        assert k.needs_merge is False


def test_nip_ustawia_typ_klienta_na_b2b(app):
    with app.app_context():
        k = znajdz_lub_utworz_klienta(email='f@firma.pl', nip='8133355123',
                                      phone=None, nazwa='Firma')
        db.session.commit()
        assert k.client_kind == 'b2b'


def test_brak_nipu_ustawia_detal(app):
    with app.app_context():
        k = znajdz_lub_utworz_klienta(email='j@example.com', nip=None,
                                      phone=None, nazwa='Jan')
        db.session.commit()
        assert k.client_kind == 'detal'


def test_wspolny_telefon_nie_scala_dwoch_klientow_po_kolizji(app):
    """Odtwarza scenariusz ze zgloszenia: wspolny telefon recepcji firmy.

    1. Zamowienie A (brak maila i NIP-u, telefon recepcji X) -> klient C1.
    2. Zamowienie B (mail anny, brak telefonu) -> klient C2.
    3. Zamowienie C (mail anny ORAZ telefon X) trafia po mailu do C2. Telefon
       X nalezy juz do C1, wiec nie wolno go dopisac do C2 — trzeba oznaczyc
       C2 do recznego scalenia, a C1 ma zostac jedynym posiadaczem telefonu.
    """
    with app.app_context():
        c1 = znajdz_lub_utworz_klienta(email=None, nip=None,
                                       phone='500200300', nazwa='Recepcja firmy X')
        db.session.commit()

        c2 = znajdz_lub_utworz_klienta(email='anna@firma.pl', nip=None,
                                       phone=None, nazwa='Anna')
        db.session.commit()
        assert c1.id != c2.id

        c2_po_kolizji = znajdz_lub_utworz_klienta(email='anna@firma.pl', nip=None,
                                                   phone='500200300', nazwa='Anna')
        db.session.commit()

        assert c2_po_kolizji.id == c2.id
        assert c2_po_kolizji.phone_norm is None
        assert c2_po_kolizji.needs_merge is True

        c1_po_odswiezeniu = SalesClient.query.filter_by(id=c1.id).first()
        assert c1_po_odswiezeniu.phone_norm == '500200300'
        assert SalesClient.query.filter_by(phone_norm='500200300').count() == 1


def test_wspolny_nip_nie_scala_dwoch_klientow_po_kolizji(app):
    """Analogiczny scenariusz do kolizji telefonu, ale dla NIP-u — zywa sciezka,
    bo `znaleziony` trafia tu po e-mailu (inny klucz niz ten, ktory koliduje).

    1. Zamowienie A (brak maila, NIP firmy X) -> klient C1, typ 'b2b'.
    2. Zamowienie B (mail anny, brak NIP-u) -> klient C2, typ 'detal'.
    3. Zamowienie C (mail anny ORAZ NIP firmy X) trafia po mailu do C2. NIP X
       nalezy juz do C1, wiec nie wolno go dopisac do C2 — trzeba oznaczyc C2
       do recznego scalenia, a jego typ klienta MA ZOSTAC 'detal' (awans na
       'b2b' nastepuje tylko razem z faktycznym zapisaniem NIP-u).
    """
    with app.app_context():
        c1 = znajdz_lub_utworz_klienta(email=None, nip='8133355123',
                                       phone=None, nazwa='Firma X')
        db.session.commit()
        assert c1.client_kind == 'b2b'

        c2 = znajdz_lub_utworz_klienta(email='anna@firma.pl', nip=None,
                                       phone=None, nazwa='Anna')
        db.session.commit()
        assert c1.id != c2.id
        assert c2.client_kind == 'detal'

        c2_po_kolizji = znajdz_lub_utworz_klienta(email='anna@firma.pl',
                                                   nip='813-33-55-123',
                                                   phone=None, nazwa='Anna')
        db.session.commit()

        assert c2_po_kolizji.id == c2.id
        assert c2_po_kolizji.nip_norm is None
        assert c2_po_kolizji.needs_merge is True
        assert c2_po_kolizji.client_kind == 'detal'

        c1_po_odswiezeniu = SalesClient.query.filter_by(id=c1.id).first()
        assert c1_po_odswiezeniu.nip_norm == '8133355123'
        assert SalesClient.query.filter_by(nip_norm='8133355123').count() == 1
