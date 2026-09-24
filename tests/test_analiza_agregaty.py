# -*- coding: utf-8 -*-
"""Agregaty dashboardu Analizy sprzedazowej (modules/reports/analytics.py).

Trzy niezmienniki, ktore te testy pilnuja:
1. Objetosc NIGDY nie wlicza uslug (group_type == 'usluga'). Na produkcji
   suszenie uslugowe podbijalo wrzesien 2025 z ~12 m3 na 167 m3, bo w takiej
   pozycji ilosc oznacza metry szescienne.
2. Szereg miesieczny ma ciagla os — miesiac bez zamowien to zero, nie dziura.
   Bez tego wykres skleilby marzec z majem i pokazal wzrost, ktorego nie bylo.
3. Konwersja lead -> klient liczy sie przez DOPASOWANIE E-MAILA, a nie przez
   kolumne sales_clients.lead_id: ta kolumna nie ma dzis ani jednego pisarza
   (znalezisko z finalnego przegladu Planu A), wiec oparcie karty na niej
   pokazywaloby stale 0,0%.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.analytics import (
    klienci_wg_liczby_zamowien, konwersja_lead_klient, lejek_wycen,
    nowi_klienci, ostrzezenie_salda, suma_kosztu_kuriera, szereg_miesieczny,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Blok "rejestr mapperow" — bez niego SQLAlchemy rzuca InvalidRequestError przy
# pierwszym query. User ma relationship('Multiplier') podana stringiem i nie
# rozwiaze jej, dopoki caly graf modeli nie jest zaimportowany. Ten sam gotcha
# i to samo rozwiazanie co w tests/test_bot_api_by_token_integration.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
# prod_orders jest po drugiej stronie lejka wycen (stopien „W realizacji"),
# wiec tabela MUSI istniec w bazie testowej — inaczej kazdy test dotykajacy
# /api/analytics wywala sie na „no such table: prod_orders".
# `prod_orders.shipping_label_base64` jest kolumna typu LONGTEXT (dialekt
# MySQL), a SQLite nie umie takiej skompilowac — `create_all` wywala sie
# CompileError, zanim ruszy pierwszy test. Uczymy wiec kompilator SQLite
# czytac LONGTEXT jako TEXT. Szim jest TESTOWY: na produkcji kolumna ma
# zostac LONGTEXT-em, bo trzyma etykiete kurierska w base64.
@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'

from modules.production.models import ProductionOrder  # noqa: F401 — rejestr mapperów
from modules.users.models import User  # noqa: F401 — rejestr mapperów
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem, ProductionOrder,
)]


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


def _zamowienie(bl_id, dzien, pozycje, saldo='0', status='Nowe', kurier=None,
                kanal='shop', gatunek='dąb', client_id=None):
    """pozycje: lista krotek (value_net, total_volume, group_type)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal(saldo), current_status=status,
                     delivery_cost=None if kurier is None else Decimal(kurier),
                     order_source=kanal, client_id=client_id)
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto),
            total_volume=Decimal(objetosc), group_type=grupa,
            wood_species=gatunek, quantity=1))
    return zam


# --- szereg miesieczny ------------------------------------------------------

def test_szereg_grupuje_po_miesiacach(app):
    with app.app_context():
        _zamowienie(1, date(2026, 1, 10), [('100.00', '0.10', 'towar')])
        _zamowienie(2, date(2026, 1, 20), [('150.00', '0.20', 'towar')])
        _zamowienie(3, date(2026, 3, 5), [('300.00', '0.30', 'towar')])
        db.session.commit()

        szereg = szereg_miesieczny(date(2026, 1, 1), date(2026, 3, 31))

        assert [(w['rok'], w['miesiac']) for w in szereg] == [(2026, 1), (2026, 2), (2026, 3)]
        assert szereg[0]['netto'] == Decimal('250.00')
        assert szereg[0]['zamowienia'] == 2


def test_szereg_wypelnia_pusty_miesiac_zerem(app):
    """Luty bez zamowien ma byc wierszem z zerem, nie dziura w osi."""
    with app.app_context():
        _zamowienie(1, date(2026, 1, 10), [('100.00', '0.10', 'towar')])
        _zamowienie(2, date(2026, 3, 5), [('300.00', '0.30', 'towar')])
        db.session.commit()

        szereg = szereg_miesieczny(date(2026, 1, 1), date(2026, 3, 31))

        luty = [w for w in szereg if w['miesiac'] == 2][0]
        assert luty['netto'] == Decimal('0')
        assert luty['objetosc'] == Decimal('0')
        assert luty['zamowienia'] == 0


def test_szereg_wyklucza_uslugi_z_objetosci_ale_nie_z_netto(app):
    """Suszenie uslugowe 88 m3 nie moze wejsc do metrow szesciennych."""
    with app.app_context():
        _zamowienie(1, date(2026, 5, 4),
                    [('1000.00', '2.50', 'towar'), ('800.00', '88.00', 'usługa')])
        db.session.commit()

        szereg = szereg_miesieczny(date(2026, 5, 1), date(2026, 5, 31))

        assert szereg[0]['objetosc'] == Decimal('2.50')
        assert szereg[0]['netto'] == Decimal('1800.00')


def test_szereg_przechodzi_przez_granice_roku(app):
    with app.app_context():
        _zamowienie(1, date(2025, 12, 30), [('100.00', '0.10', 'towar')])
        _zamowienie(2, date(2026, 1, 2), [('200.00', '0.10', 'towar')])
        db.session.commit()

        szereg = szereg_miesieczny(date(2025, 12, 1), date(2026, 1, 31))

        assert [(w['rok'], w['miesiac']) for w in szereg] == [(2025, 12), (2026, 1)]


# --- klienci ----------------------------------------------------------------

def _klient(orders_count, lifetime_net, first_order_at=None, email_norm=None):
    k = SalesClient(orders_count=orders_count, lifetime_net=Decimal(lifetime_net),
                    first_order_at=first_order_at, email_norm=email_norm,
                    display_name='Klient')
    db.session.add(k)
    db.session.flush()
    return k


def test_kubelki_klientow_maja_stala_kolejnosc_i_lapia_granice(app):
    with app.app_context():
        _klient(1, '1000.00')
        _klient(3, '2000.00')
        _klient(4, '3000.00')
        _klient(9, '4000.00')
        _klient(10, '5000.00')
        db.session.commit()

        kubelki = klienci_wg_liczby_zamowien()

        assert [k['kubelek'] for k in kubelki] == ['1 zam.', '2–3', '4–9', '10+']
        assert [k['klienci'] for k in kubelki] == [1, 1, 2, 1]
        assert kubelki[2]['netto'] == Decimal('7000.00')


def test_klient_bez_zamowien_nie_wchodzi_do_zadnego_kubelka(app):
    with app.app_context():
        _klient(0, '0.00')
        db.session.commit()

        assert sum(k['klienci'] for k in klienci_wg_liczby_zamowien()) == 0


def test_nowi_klienci_liczy_po_dacie_pierwszego_zamowienia(app):
    with app.app_context():
        # Klienci z REALNYM zamówieniem w sales_orders — `nowi_klienci` liczy
        # po JOIN-ie z `SalesOrder`, więc samo `first_order_at` bez wiersza
        # w `sales_orders` (patrz test niżej) to za mało.
        w_okresie = _klient(1, '100.00', first_order_at=date(2026, 9, 3))
        _zamowienie(1, date(2026, 9, 3), [('100.00', '0.10', 'towar')],
                   client_id=w_okresie.id)
        przed_okresem = _klient(1, '100.00', first_order_at=date(2026, 8, 30))
        _zamowienie(2, date(2026, 8, 30), [('100.00', '0.10', 'towar')],
                   client_id=przed_okresem.id)
        _klient(1, '100.00', first_order_at=None)
        db.session.commit()

        assert nowi_klienci(date(2026, 9, 1), date(2026, 9, 21)) == 1


def test_nowi_klienci_ignoruje_klienta_bez_prawdziwego_zamowienia(app):
    """Regresja 22.09.2026: dashboard i Eksplorator liczyły „nowych klientów"
    dwoma NIEZALEŻNYMI zapytaniami i dawały dwie różne liczby za ten sam
    okres (381 vs 380) — patrz `raport-fala4-klienci.md`.

    Winowajcą był klient `sales_clients` z ręcznie ustawionym `first_order_at`
    i `orders_count=1`, ale BEZ ani jednego wiersza w `sales_orders` (wpis
    testowy „TEST Weryfikacja" na produkcji, id=2622). Samo
    `sales_clients.first_order_at` liczyło go jako nowego, zapytanie idące
    przez JOIN z `SalesOrder` — nie. `nowi_klienci` MUSI iść drugą drogą:
    denormalizacja bez realnego zamówienia się nie liczy.
    """
    with app.app_context():
        _klient(1, '0.00', first_order_at=date(2026, 9, 18))  # bez SalesOrder
        db.session.commit()

        assert nowi_klienci(date(2026, 9, 1), date(2026, 9, 21)) == 0


def test_konwersja_liczy_po_mailu_a_nie_po_lead_id(app):
    """lead_id nie ma dzis pisarza — karta nie moze na nim stac."""
    with app.app_context():
        db.session.add(Client(client_number='L1', client_name='Makietowy',
                              email='  Jan.Makietowy@example.COM '))
        _klient(1, '100.00', email_norm='jan.makietowy@example.com')
        _klient(1, '100.00', email_norm='nikt@example.com')
        db.session.commit()

        wynik = konwersja_lead_klient()

        assert wynik['klientow'] == 2
        assert wynik['z_leada'] == 1
        assert wynik['procent'] == Decimal('50.0')
        assert wynik['dowiazanych_lead_id'] == 0


def test_konwersja_na_pustej_bazie_nie_dzieli_przez_zero(app):
    with app.app_context():
        assert konwersja_lead_klient()['procent'] == Decimal('0')


# --- lejek ------------------------------------------------------------------
# Piec stopni, wszystkie liczone z JEDNEGO zbioru: wycen utworzonych w okresie.
# Trzy pulapki, ktorych pilnuja testy nizej:
# 1. `quotes.base_linker_order_id` to VARCHAR, a `sales_orders.baselinker_order_id`
#    i `prod_orders.baselinker_order_id` sa liczbami. Dowiazanie musi zniesc
#    pusty napis, spacje i wartosc nieliczbowa — bez wywrotki i bez sklejania
#    smieci z zamowieniem numer zero.
# 2. Saldo bierzemy z `SalesOrder`, nigdy sumowane po pozycjach.
# 3. Stopnie 4 i 5 NIE sa zagniezdzone: zamowienie wchodzi na produkcje po
#    zaliczce, wiec bywa „w realizacji" nie bedac „oplacone".


def _wycena(numer, kiedy, bl_order=None, status_id=None, akceptacja=None,
            kwota=None, autor=None, zrodlo=None):
    db.session.add(Quote(quote_number=numer, created_at=kiedy,
                         base_linker_order_id=bl_order, status_id=status_id,
                         acceptance_date=akceptacja, user_id=autor,
                         source=zrodlo,
                         total_price=None if kwota is None else Decimal(kwota)))


def _zlecenie(bl_id, numer='W/1'):
    """Zamowienie, ktore weszlo na produkcje."""
    db.session.add(ProductionOrder(baselinker_order_id=bl_id,
                                   internal_order_number=numer))


def _uzytkownik(ident, imie, nazwisko):
    db.session.add(User(id=ident, email=f'{ident}@woodpower.pl', password='x',
                        role='user', active=True,
                        first_name=imie, last_name=nazwisko))


def _stopnie(wynik):
    return {s['klucz']: s['liczba'] for s in wynik['stopnie']}


def test_lejek_ma_piec_stopni_liczonych_wobec_pierwszego(app):
    with app.app_context():
        # Wycena pelnej sciezki: zaakceptowana, zamowiona, oplacona, w produkcji.
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101',
                akceptacja=datetime(2026, 9, 2, 12, 0))
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')], saldo='0')
        _zlecenie(101)
        # Zaakceptowana, ale nikt jej nie zamowil.
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0),
                akceptacja=datetime(2026, 9, 3, 12, 0))
        # Dwie, ktore zostaly na pierwszym stopniu.
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0))
        _wycena('4/26/W', datetime(2026, 9, 5, 10, 0))
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert _stopnie(wynik) == {'utworzone': 4, 'zaakceptowane': 2,
                                   'zamowione': 1, 'oplacone': 1, 'w_realizacji': 1}
        # Udzial KAZDEGO stopnia liczy sie wobec stopnia PIERWSZEGO, nie wobec
        # poprzedniego — inaczej nie da sie porownac dwoch stopni miedzy soba.
        assert [s['udzial'] for s in wynik['stopnie']] == [
            Decimal('100.0'), Decimal('50.0'), Decimal('25.0'),
            Decimal('25.0'), Decimal('25.0')]


def test_lejek_uznaje_zamowiona_po_numerze_z_baselinkera(app):
    """Stopien „Zamowione" to NUMER ZAMOWIENIA, nie status wyceny.

    Poprzednia wersja karty brala numer LUB status 4 („Zamowione"). Na
    produkcyjnym zrzucie roznica to 2 wyceny na 1365 (status 4 bez numeru),
    a definicja „trafila do BaseLinkera" jest jedyna, ktora da sie dowiazac
    do sprzedazy i produkcji — czyli do stopni 4 i 5. Dwie definicje
    zamowienia w jednej karcie znaczylyby, ze stopien trzeci moze byc
    WIEKSZY od czwartego z powodu, ktorego nie widac na ekranie.
    """
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0))
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), bl_order='38623765')
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0), status_id=4)
        _wycena('4/26/W', datetime(2026, 9, 5, 10, 0), bl_order='')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['wycen'] == 4
        assert wynik['zamienionych'] == 1
        assert wynik['procent'] == Decimal('25.0')


def test_lejek_znosi_smieci_w_kolumnie_numeru_zamowienia(app):
    """`base_linker_order_id` to VARCHAR i bywa czymkolwiek.

    Rzutowanie napisu na liczbe dawaloby tu 0 dla „brak" i skleilo te wycene
    z dowolnym zamowieniem o numerze zero. Porownujemy wiec jako TEKST.
    """
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order=' 101 ')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), bl_order='brak')
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0), bl_order='   ')
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')], saldo='0')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        # Same spacje to brak numeru; „brak" numerem jest, tylko nie trafia
        # w zadne zamowienie.
        assert _stopnie(wynik)['zamowione'] == 2
        assert _stopnie(wynik)['oplacone'] == 1
        assert wynik['dopasowanych'] == 1


def test_lejek_bierze_saldo_z_zamowienia_a_nie_z_pozycji(app):
    """Regresja klasy bledow, przez ktora saldo bylo zawyzone 7,58x.

    Zamowienie z trzema pozycjami i dodatnim saldem ma NIE wpasc do
    „Oplacone" — i ma sie policzyc raz, a nie trzy razy.
    """
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101')
        _zamowienie(101, date(2026, 9, 2),
                    [('100.00', '0.10', 'towar'), ('200.00', '0.20', 'towar'),
                     ('300.00', '0.30', 'towar')], saldo='500.00')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert _stopnie(wynik)['utworzone'] == 1
        assert _stopnie(wynik)['zamowione'] == 1
        assert _stopnie(wynik)['oplacone'] == 0


def test_lejek_pokazuje_ile_wycen_nie_ma_odpowiednika_w_sprzedazy(app):
    """1365 wycen z numerem wobec 1173 dowiazanych — roznica jest PRAWDZIWA.

    Tabela sprzedazy obejmuje wezszy zakres niz wyceny, wiec czesc numerow
    nie trafia w nic. Bez tej liczby stopien „Oplacone" wyglada na spadek
    konwersji, a jest brakiem danych.
    """
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), bl_order='999')
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')], saldo='0')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert _stopnie(wynik)['zamowione'] == 2
        assert wynik['dopasowanych'] == 1


def test_lejek_w_realizacji_nie_musi_byc_podzbiorem_oplaconych(app):
    """Zamowienie wchodzi na produkcje po zaliczce.

    Na wrzesniu 2026 bylo 42 oplacone przy 55 w realizacji. Lejek ma to
    pokazac, a nie „poprawic" — kazdy stopien liczy sie wobec pierwszego.
    """
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), bl_order='101')
        _zamowienie(101, date(2026, 9, 2), [('100.00', '0.10', 'towar')],
                    saldo='300.00')
        _zlecenie(101)
        db.session.commit()

        stopnie = _stopnie(lejek_wycen(date(2026, 9, 1), date(2026, 9, 30)))

        assert stopnie['oplacone'] == 0
        assert stopnie['w_realizacji'] == 1


def test_lejek_obejmuje_caly_ostatni_dzien_okresu(app):
    """created_at to DateTime — wycena o 23:50 ostatniego dnia musi sie liczyc."""
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 21, 23, 50))
        db.session.commit()

        assert lejek_wycen(date(2026, 9, 1), date(2026, 9, 21))['wycen'] == 1


def test_lejek_liczy_srednia_wyceny_i_srednia_zamowionej(app):
    """Dwie srednie obok siebie odpowiadaja na pytanie „czy zamawiane sa
    wyceny drozsze, czy tansze niz przecietna"."""
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), kwota='1000.00')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), kwota='3000.00',
                bl_order='101')
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0), kwota='5000.00',
                bl_order='102')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['srednia_wycena'] == Decimal('3000.00')
        # Srednia z PODZBIORU, nie srednia z zerami za niezamowione.
        assert wynik['srednia_zamowiona'] == Decimal('4000.00')


def test_mediana_czasu_do_zamowienia_nie_daje_sie_przesunac_ogonem(app):
    """Srednia klamalaby: jedno zamowienie zlozone rok po wycenie przesuwa ja
    o miesiace, a mediana zostaje tam, gdzie jest wiekszosc."""
    with app.app_context():
        for i, (dzien_wyceny, dzien_zamowienia) in enumerate((
                (2, 2), (3, 3), (4, 4), (5, 5), (6, 200))):
            _wycena(f'{i}/26/W', datetime(2026, 9, dzien_wyceny, 10, 0),
                    bl_order=str(100 + i))
            _zamowienie(100 + i, date(2026, 9, 1) + timedelta(days=dzien_zamowienia - 1),
                        [('100.00', '0.10', 'towar')], saldo='0')
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        # Cztery zamowienia tego samego dnia co wycena i jedno po 195 dniach.
        assert wynik['mediana_probka'] == 5
        assert wynik['mediana_dni'] == Decimal('0.0')


def test_mediana_bez_ani_jednej_pary_jest_nieokreslona(app):
    """Zero to konkretna odpowiedz („zamawiaja tego samego dnia"), a brak
    danych nia nie jest — karta ma pokazac kreske, nie zero."""
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0))
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['mediana_dni'] is None
        assert wynik['mediana_probka'] == 0


def test_podzial_po_opiekunie_sumuje_sie_do_stopnia_pierwszego(app):
    """Suma wycen w podziale MUSI byc rowna stopniowi pierwszemu — inaczej
    karta przeczy sama sobie. Stad zlaczenie zewnetrzne z `users`: wycena bez
    autora ma wpasc do wiersza „(brak)", a nie wyparowac."""
    with app.app_context():
        _uzytkownik(11, 'Łukasz', 'Próbny')
        _uzytkownik(54, 'Ewa', 'Fikcyjna')
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), autor=11, bl_order='101')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), autor=11)
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0), autor=54)
        _wycena('4/26/W', datetime(2026, 9, 5, 10, 0), autor=None)
        db.session.commit()

        wynik = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30),
                            podzialy=('caretaker',))
        podzial = wynik['podzial']['caretaker']

        assert sum(w['wycen'] for w in podzial) == wynik['wycen']
        # Sortowanie malejaco po liczbie WYCEN, nie po konwersji: handlowiec
        # z jedna wycena i jednym zamowieniem ma 100% i bez proby obok
        # wygladalby na najlepszego w firmie.
        assert podzial[0]['wartosc'] == 'Łukasz Próbny'
        assert podzial[0]['wycen'] == 2
        assert podzial[0]['zamowione'] == 1
        assert podzial[0]['konwersja'] == Decimal('50.0')
        assert [w['wartosc'] for w in podzial if w['wartosc'] is None] == [None]


def test_podzial_po_kanale_scala_pusty_napis_z_brakiem(app):
    """NULL i '' znacza to samo („nie wiadomo"), a w bazie zyja obok siebie —
    bez scalenia karta pokazalaby dwa wiersze „(brak)"."""
    with app.app_context():
        _wycena('1/26/W', datetime(2026, 9, 2, 10, 0), zrodlo='OLX')
        _wycena('2/26/W', datetime(2026, 9, 3, 10, 0), zrodlo='')
        _wycena('3/26/W', datetime(2026, 9, 4, 10, 0), zrodlo=None)
        db.session.commit()

        podzial = lejek_wycen(date(2026, 9, 1), date(2026, 9, 30),
                              podzialy=('order_source',))['podzial']['order_source']

        assert [(w['wartosc'], w['wycen']) for w in podzial] == [(None, 2), ('OLX', 1)]


def test_podzial_lejka_spoza_listy_jest_bledem_a_nie_pusta_lista(app):
    """Cicha pusta lista dla literowki w nazwie wymiaru znaczylaby „ten
    handlowiec nie zrobil nic", zamiast „zapytales o cos, czego nie ma"."""
    with app.app_context():
        with pytest.raises(ValueError):
            lejek_wycen(date(2026, 9, 1), date(2026, 9, 30),
                        podzialy=('delivery_state',))


def test_wymiary_lejka_sa_nazwami_z_rejestru_pol():
    """Lista podzialow nie jest wlasnym slownikiem karty — kazda NAZWA ma
    istniec w rejestrze i miec tam `wymiar=True`."""
    from modules.reports.analytics import WYMIARY_LEJKA
    from modules.reports.fields import wymiary_proste

    assert set(WYMIARY_LEJKA) <= set(wymiary_proste())


def test_kazdy_wymiar_lejka_ma_wlasna_etykiete():
    """Nazwa bez etykiety znaczy selektor z pusta opcja albo KeyError przy
    skladaniu payloadu — jedno i drugie na produkcji, bo lista jest stala."""
    from modules.reports.analytics import ETYKIETY_LEJKA, WYMIARY_LEJKA

    assert set(ETYKIETY_LEJKA) == set(WYMIARY_LEJKA)
    assert all(ETYKIETY_LEJKA[n].strip() for n in WYMIARY_LEJKA)


def test_etykiety_lejka_nie_powielaja_etykiet_z_rejestru_pol():
    """NIEZMIENNIK: ta sama etykieta znaczy wszedzie to samo.

    NIE „ujednolicaj" tego z rejestrem pol. Rejestr podpisuje kolumny
    ZAMOWIENIA, a lejek grupuje po kolumnach WYCENY i sa to inne zbiory
    wartosci. Zmierzone na produkcji 23.09.2026:

        quotes.source             OLX 1795, E-mail 1147, Telefon 941,
                                  (puste) 323, Osobiscie 193, Asystent AI 70
        sales_orders.order_source personal 1271, shop 1158, allegro 841,
                                  olx 53

    Jedyna nazwa brzmiaca w obu tak samo to OLX — i tam stoi 1795 wobec 53.
    Pod wspolnym podpisem „Kanal sprzedazy" ktos zestawilby te dwie liczby
    i wyliczyl trzyprocentowa konwersje z dwoch ROZNYCH wymiarow. Stad
    „Zrodlo wyceny" zamiast „Kanal sprzedazy" i „Autor wyceny" zamiast
    „Opiekun".

    Ten projekt potknal sie o to juz dwa razy: raz Eksplorator pokazywal te
    sama wartosc jako „Sklep" w jednym panelu i „shop" w drugim, raz karta
    pod tytulem „Sprzedaz netto" wypisywala metry szescienne.
    """
    from modules.reports.analytics import ETYKIETY_LEJKA
    from modules.reports.fields import POLA

    etykiety_rejestru = {pole.etykieta for pole in POLA.values()}
    for nazwa, etykieta in ETYKIETY_LEJKA.items():
        assert etykieta not in etykiety_rejestru, (
            f'podzial lejka „{nazwa}" jest podpisany „{etykieta}" — tak samo '
            f'jak pole w rejestrze, ktore opisuje INNA kolumne i inny zbior '
            f'wartosci (patrz docstring tego testu)')
        assert etykieta != POLA[nazwa].etykieta


# --- saldo i kurier ---------------------------------------------------------

def test_ostrzezenie_salda_liczy_stare_zamowienia_w_produkcji(app):
    with app.app_context():
        _zamowienie(1, date(2026, 1, 5), [('100.00', '0.10', 'towar')],
                    saldo='500.00', status='W produkcji — surowe')
        _zamowienie(2, date(2026, 1, 6), [('100.00', '0.10', 'towar')],
                    saldo='300.00', status='Nowe — opłacone')
        _zamowienie(3, date(2026, 9, 20), [('100.00', '0.10', 'towar')],
                    saldo='900.00', status='W produkcji — surowe')
        db.session.commit()

        wynik = ostrzezenie_salda(date(2026, 9, 21))

        assert wynik['zamowienia'] == 1
        assert wynik['saldo'] == Decimal('500.00')


def test_suma_kosztu_kuriera_ignoruje_puste(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), [('100.00', '0.10', 'towar')], kurier='120.00')
        _zamowienie(2, date(2026, 9, 3), [('100.00', '0.10', 'towar')], kurier=None)
        db.session.commit()

        assert suma_kosztu_kuriera(date(2026, 9, 1), date(2026, 9, 30)) == Decimal('120.00')


# --- filtr (druga seria segmentu porownawczego) -----------------------------

def test_szereg_z_filtrem_zaweza_do_wybranego_kanalu(app):
    """Druga seria wykresu trendu to ten sam szereg, tylko z filtrem."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), [('300.00', '0.30', 'towar')], kanal='shop')
        _zamowienie(2, date(2026, 9, 3), [('700.00', '0.70', 'towar')], kanal='allegro')
        db.session.commit()

        bez = szereg_miesieczny(date(2026, 9, 1), date(2026, 9, 30))
        z_filtrem = szereg_miesieczny(date(2026, 9, 1), date(2026, 9, 30),
                                      filtr={'order_source': ['shop']})

        assert bez[0]['netto'] == Decimal('1000.00')
        assert z_filtrem[0]['netto'] == Decimal('300.00')
        assert z_filtrem[0]['zamowienia'] == 1
        # Os zostaje ciagla takze z filtrem — pusty miesiac to zero, nie dziura.
        assert len(z_filtrem) == len(bez) == 1


def test_suma_kosztu_kuriera_z_filtrem_po_pozycji_nie_powiela_kosztu(app):
    """Kurier zyje na ZAMOWIENIU. Filtr po gatunku wchodzi EXISTS-em, wiec
    zamowienie z dwunastoma debowymi pozycjami wnosi koszt RAZ."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), [('100.00', '0.01', 'towar')] * 12,
                    kurier='120.00', gatunek='dąb')
        _zamowienie(2, date(2026, 9, 3), [('100.00', '0.10', 'towar')],
                    kurier='80.00', gatunek='jesion')
        db.session.commit()

        assert suma_kosztu_kuriera(date(2026, 9, 1), date(2026, 9, 30),
                                   filtr={'wood_species': ['dąb']}) == Decimal('120.00')
