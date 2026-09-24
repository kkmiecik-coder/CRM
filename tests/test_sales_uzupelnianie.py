# -*- coding: utf-8 -*-
"""Dwie kolumny, ktorych do Planu C nikt nie wypelnial:
sales_clients.lead_id i sales_orders.client_origin.

Tabele produkcji sa tu potrzebne naprawde — client_origin bierze sie
z prod_orders.order_source_display. LONGTEXT (MySQL) nie istnieje w SQLite,
stad podmiana typu kolumny; ta sama konwencja co tests/krawedzie_fixtures.py:56.
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
from modules.reports.analytics import konwersja_lead_klient
from modules.reports.dedup import dowiaz_lead
from modules.reports.ingest import origin_z_produkcji, zapisz_zamowienia
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.production.models import ProductionOrder

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client
import modules.quotes.models  # noqa: F401 — rejestr mapperów

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from uzupelnij_sales_braki import uzupelnij_leady, uzupelnij_origin  # noqa: E402

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/krawedzie_fixtures.py
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_TABLES = [m.__table__ for m in
           (SalesClient, SalesOrder, SalesOrderItem, Client, ProductionOrder)]

TS_18_09 = 1789714800


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def lead(numer, nazwa='Lead', email=None, nip=None, telefon=None):
    l = Client(client_number=numer, client_name=nazwa, email=email,
               invoice_nip=nip, phone=telefon)
    db.session.add(l)
    db.session.flush()
    return l


def klient_sprzedazowy(email=None, nip=None, telefon=None, nazwa='Klient'):
    k = SalesClient(email_norm=email, nip_norm=nip, phone_norm=telefon,
                    display_name=nazwa, needs_merge=False)
    db.session.add(k)
    db.session.flush()
    return k


def zamowienie(order_id=50854536, **nadpisania):
    baza = {
        'order_id': order_id, 'date_add': TS_18_09, 'date_confirmed': TS_18_09,
        'order_status_id': 138619, 'delivery_fullname': 'Jan Przykładowy',
        'email': 'jan.przykladowy@example.com', 'phone': '601202303',
        'delivery_postcode': '40-100', 'delivery_state': 'śląskie',
        'delivery_price': 0.0, 'payment_done': 0.0, 'order_source': 'shop',
        'custom_extra_fields': {'105623': 'Łukasz Próbny', '106169': 'netto'},
        'products': [{'order_product_id': 991, 'quantity': 1, 'price_brutto': 800.00,
                      'name': 'Blat dębowy lity A/B 100x50x2 cm'}],
    }
    baza.update(nadpisania)
    return baza


def prod_zamowienie(bl_id, zrodlo='personal', nazwa_zrodla='Stały B2B'):
    p = ProductionOrder(baselinker_order_id=bl_id, internal_order_number='26_00001',
                        order_source=zrodlo, order_source_name=nazwa_zrodla)
    db.session.add(p)
    db.session.commit()
    return p


# ===== dowiaz_lead =====================================================

def test_lead_dowiazuje_sie_po_mailu(app):
    with app.app_context():
        l = lead('L1', email='jan.przykladowy@example.com')
        k = klient_sprzedazowy(email='jan.przykladowy@example.com')
        assert dowiaz_lead(k) == l.id
        assert k.lead_id == l.id


def test_lead_dopasowuje_maila_bez_wzgledu_na_wielkosc_liter(app):
    # leads.email nie jest znormalizowany i ma 21 e-maili wystepujacych
    # wielokrotnie (spec 3.4), wiec porownanie musi ignorowac wielkosc liter
    # i biale znaki.
    with app.app_context():
        l = lead('L1', email='  Jan.Przykladowy@Example.COM ')
        k = klient_sprzedazowy(email='jan.przykladowy@example.com')
        assert dowiaz_lead(k) == l.id


def test_lead_dowiazuje_sie_po_nipie_gdy_brak_maila(app):
    with app.app_context():
        l = lead('L1', nip='123-456-78-90')
        k = klient_sprzedazowy(nip='1234567890')
        assert dowiaz_lead(k) == l.id


def test_lead_dowiazuje_sie_po_telefonie_gdy_brak_maila_i_nipu(app):
    with app.app_context():
        l = lead('L1', telefon='+48 601 202 303')
        k = klient_sprzedazowy(telefon='601202303')
        assert dowiaz_lead(k) == l.id


def test_lead_nie_dowiazuje_sie_po_samej_nazwie(app):
    with app.app_context():
        lead('L1', nazwa='Jan Szablonowy')
        k = klient_sprzedazowy(nazwa='Jan Szablonowy')
        assert dowiaz_lead(k) is None
        assert k.lead_id is None


def test_dwa_leady_z_tym_samym_mailem_nie_dowiazuja_sie_wcale(app):
    # 21 e-maili w leads wystepuje wielokrotnie. Wybor „pierwszego lepszego"
    # bylby niedeterministyczny, a zly lead klamie na karcie konwersji
    # trwale i po cichu. Ta sama filozofia co przy kolizjach w deduplikacji.
    with app.app_context():
        lead('L1', email='dup@example.com')
        lead('L2', email='DUP@example.com')
        k = klient_sprzedazowy(email='dup@example.com')
        assert dowiaz_lead(k) is None
        assert k.needs_merge is True


def test_juz_dowiazany_klient_nie_jest_ruszany(app):
    with app.app_context():
        l1 = lead('L1', email='a@example.com')
        lead('L2', email='b@example.com')
        k = klient_sprzedazowy(email='b@example.com')
        k.lead_id = l1.id
        assert dowiaz_lead(k) == l1.id
        assert k.lead_id == l1.id


def test_brak_dopasowania_zostawia_lead_id_puste(app):
    with app.app_context():
        lead('L1', email='ktos@example.com')
        k = klient_sprzedazowy(email='nikt@example.com')
        assert dowiaz_lead(k) is None
        assert k.lead_id is None


def test_zapis_przyrostowy_dowiazuje_lead(app):
    with app.app_context():
        l = lead('L1', email='jan.przykladowy@example.com')
        zapisz_zamowienia([zamowienie()])
        assert SalesClient.query.one().lead_id == l.id


def test_indeks_leadow_budowany_raz_na_cala_paczke(app, monkeypatch):
    # ZNALEZISKO WAZNE (przeglad Zadania 4, dedup.py:169): dowiaz_lead bez
    # indeksu wczytywalo CALA tabele leads do Pythona az 3x NA ZAMOWIENIE
    # (mail -> NIP -> telefon), powtarzajac to przy kazdym kolejnym
    # zamowieniu klienta bez lead_id — zmierzone: 20-77 ms na jedno
    # wczytanie, ~6-20 s doklejone do synchronizacji 100 zamowien.
    # zapisz_zamowienia ma budowac indeks RAZ na cala paczke (leniwie, przy
    # pierwszym kliencie, ktory go potrzebuje), nie ponownie dla kazdego
    # kolejnego zamowienia.
    with app.app_context():
        lead('L1', email='jeden@example.com')
        lead('L2', email='dwa@example.com')
        lead('L3', email='trzy@example.com')
        db.session.commit()

        import modules.reports.ingest as ingest
        oryginal = ingest.zbuduj_indeks_leadow
        wywolania = []

        def podliczany(sesja=None):
            wywolania.append(1)
            return oryginal(sesja)

        monkeypatch.setattr(ingest, 'zbuduj_indeks_leadow', podliczany)

        # Telefon MUSI byc rozny per zamowienie — domyslny w helperze
        # zamowienie() jest wspolny dla wszystkich, a znajdz_lub_utworz_klienta
        # dopasowuje tez po telefonie: wspolny numer scalilby wszystkie trzy
        # zamowienia w JEDNEGO klienta, zamiast dac trzech oddzielnych.
        zamowienia = [
            zamowienie(order_id=1, email='jeden@example.com', phone='600000001'),
            zamowienie(order_id=2, email='dwa@example.com', phone='600000002'),
            zamowienie(order_id=3, email='trzy@example.com', phone='600000003'),
        ]
        wynik = zapisz_zamowienia(zamowienia)

        assert wynik['nowe'] == 3
        # Trzej rozni nowi klienci, kazdy dowiazany do INNEGO leada — a mimo
        # to indeks zbudowany dokladnie raz na cala paczke.
        assert len(wywolania) == 1

        klienci = {k.email_norm: k.lead_id for k in SalesClient.query.all()}
        assert klienci['jeden@example.com'] is not None
        assert klienci['dwa@example.com'] is not None
        assert klienci['trzy@example.com'] is not None
        assert len({klienci['jeden@example.com'], klienci['dwa@example.com'],
                   klienci['trzy@example.com']}) == 3


def test_indeks_leadow_nie_budowany_gdy_paczka_go_nie_potrzebuje(app, monkeypatch):
    # Indeks jest leniwy: paczka zlozona wylacznie z klientow, ktorzy juz
    # maja lead_id, nie powinna placic kosztu wczytania tabeli leads wcale.
    with app.app_context():
        l = lead('L1', email='jeden@example.com')
        k = klient_sprzedazowy(email='jeden@example.com')
        k.lead_id = l.id
        db.session.commit()

        import modules.reports.ingest as ingest
        wywolania = []
        monkeypatch.setattr(ingest, 'zbuduj_indeks_leadow',
                            lambda sesja=None: wywolania.append(1))

        zapisz_zamowienia([zamowienie(order_id=1, email='jeden@example.com')])

        assert wywolania == []


# ===== client_origin ===================================================

def test_client_origin_bierze_sie_z_produkcji_przy_wstawianiu(app):
    with app.app_context():
        prod_zamowienie(50854536, 'personal', 'Stały B2B')
        zapisz_zamowienia([zamowienie()])
        assert SalesOrder.query.one().client_origin == 'Stały B2B'


def test_client_origin_bierze_nazwe_zrodla_a_nie_kanal(app):
    # prod_orders.order_source trzyma KANAL („shop"), a to samo mamy juz
    # w sales_orders.order_source. client_origin ma niesc NAZWE zrodla,
    # bo to ona rozroznia „Detal" od „Staly B2B" wewnatrz kanalu recznego.
    with app.app_context():
        prod_zamowienie(50854536, 'shop', 'Presta VPS')
        zapisz_zamowienia([zamowienie()])
        zam = SalesOrder.query.one()
        assert zam.client_origin == 'Presta VPS'
        assert zam.order_source == 'shop'


def test_client_origin_zostaje_pusty_gdy_produkcja_nie_zna_nazwy_zrodla(app):
    # 473 z 1610 zamowien majacych pare w produkcji ma pusta nazwe zrodla.
    with app.app_context():
        prod_zamowienie(50854536, 'shop', None)
        zapisz_zamowienia([zamowienie()])
        assert SalesOrder.query.one().client_origin is None


def test_client_origin_nie_jest_nadpisywany_przy_aktualizacji(app):
    # Kolumna jest tylko-CRM i edytowalna w arkuszu. Synchronizacja ma prawo
    # ja ZAPROPONOWAC, dopoki jest pusta (od partii E przy kazdym zapisie,
    # nie tylko pierwszym), i nie ma prawa ruszyc wartosci niepustej.
    with app.app_context():
        prod_zamowienie(50854536, 'personal', 'Stały B2B')
        zapisz_zamowienia([zamowienie()])
        zam = SalesOrder.query.one()
        zam.client_origin = 'Szablonowy'
        db.session.commit()
        zapisz_zamowienia([zamowienie(order_status_id=138620)])
        assert SalesOrder.query.one().client_origin == 'Szablonowy'


def test_client_origin_zostaje_pusty_gdy_produkcja_nie_zna_zamowienia(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        assert SalesOrder.query.one().client_origin is None


def test_origin_z_produkcji_zwraca_none_dla_zamowienia_bez_zrodla(app):
    with app.app_context():
        prod_zamowienie(50854536, None, None)
        assert origin_z_produkcji(50854536) is None


def test_dluga_nazwa_zrodla_jest_przycinana_do_szerokosci_kolumny(app):
    # order_source_name to VARCHAR(100), client_origin VARCHAR(50).
    with app.app_context():
        prod_zamowienie(50854536, 'personal', 'x' * 100)
        assert len(origin_z_produkcji(50854536)) == 50


# ===== skrypt jednorazowy ==============================================

def test_skrypt_uzupelnia_lead_id_istniejacym_klientom(app):
    with app.app_context():
        l = lead('L1', email='stary@example.com')
        k = klient_sprzedazowy(email='stary@example.com')
        wynik = uzupelnij_leady()
        assert wynik == {'sprawdzonych': 1, 'dowiazanych': 1, 'niejednoznacznych': 0}
        assert SalesClient.query.get(k.id).lead_id == l.id


def test_skrypt_uzupelnia_client_origin_istniejacym_zamowieniom(app):
    with app.app_context():
        prod_zamowienie(777, 'allegro', 'woodpower')
        db.session.add(SalesOrder(baselinker_order_id=777, date_created=date(2026, 9, 1)))
        db.session.commit()
        wynik = uzupelnij_origin()
        assert wynik == {'sprawdzonych': 1, 'uzupelnionych': 1}
        assert SalesOrder.query.one().client_origin == 'woodpower'


def test_skrypt_jest_idempotentny(app):
    with app.app_context():
        lead('L1', email='stary@example.com')
        klient_sprzedazowy(email='stary@example.com')
        prod_zamowienie(777, 'allegro', 'woodpower')
        db.session.add(SalesOrder(baselinker_order_id=777, date_created=date(2026, 9, 1)))
        db.session.commit()
        uzupelnij_leady()
        uzupelnij_origin()
        # Drugi przebieg nie ma juz czego uzupelniac — zero sprawdzanych,
        # bo obie funkcje filtruja po kolumnie IS NULL.
        assert uzupelnij_leady() == {'sprawdzonych': 0, 'dowiazanych': 0,
                                     'niejednoznacznych': 0}
        assert uzupelnij_origin() == {'sprawdzonych': 0, 'uzupelnionych': 0}


# ===== niezmiennik miedzypanelowy ======================================

def test_konwersja_liczona_po_mailu_zgadza_sie_z_dowiazanymi_lead_id(app):
    # analytics.py:190 mowi wprost: „gdy Plan C doda pisarza, obie liczby
    # powinny sie zejsc". Tego nie widac w tescie zadnego pojedynczego
    # komponentu — karta liczy po mailach, pisarz zapisuje lead_id — wiec
    # relacja miedzy nimi musi miec wlasny test.
    with app.app_context():
        lead('L1', email='a@example.com')
        lead('L2', email='b@example.com')
        for mail in ('a@example.com', 'b@example.com', 'c@example.com'):
            # Karta liczy KUPUJĄCYCH, czyli klientów z co najmniej jednym
            # zamówieniem w sprzedaży (partia E, punkt E5) — klient bez
            # zamówień nie wchodzi do mianownika konwersji.
            klient_sprzedazowy(email=mail).orders_count = 1
        db.session.commit()
        uzupelnij_leady()
        dane = konwersja_lead_klient()
        assert dane['klientow'] == 3
        assert dane['z_leada'] == 2
        assert dane['dowiazanych_lead_id'] == dane['z_leada']
