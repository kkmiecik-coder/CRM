# -*- coding: utf-8 -*-
"""Idempotentny upsert zamowien z BaseLinkera do sales_*.

Minimalny Flask + SQLAlchemy na SQLite in-memory, StaticPool, jawna lista
tabel — konwencja tests/test_sales_models.py. db.create_all() probowalby
skompilowac LONGTEXT z innych modulow, czego SQLite nie potrafi.
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
from modules.reports.ingest import zapisz_zamowienia
from modules.reports.models import BaselinkerReportOrder
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]

# 2026-09-18 07:00 UTC = 09:00 w Warszawie (ta sama data w obu strefach).
TS_18_09 = 1789714800
TS_19_09 = 1789801200
# 2026-09-18 23:30 UTC = 2026-09-19 01:30 w Warszawie — DWIE ROZNE DATY.
TS_NOCNY = 1789774200


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


def zamowienie(order_id=50854536, **nadpisania):
    baza = {
        'order_id': order_id,
        'date_add': TS_18_09,
        'date_confirmed': TS_18_09,
        'order_status_id': 138619,
        'extra_field_1': 'WP-2026-0912',
        'delivery_fullname': 'Jan Przykładowy',
        'email': 'jan.przykladowy@example.com',
        'phone': '+48 601 202 303',
        'delivery_postcode': '40-100',
        'delivery_city': 'Katowice',
        'delivery_state': 'śląskie',
        'delivery_method': 'Kurier DPD',
        'delivery_price': 0.0,
        'payment_method': 'Przelew',
        'payment_done': 0.0,
        'order_source': 'shop',
        'custom_extra_fields': {'105623': 'Łukasz Próbny', '106169': 'netto'},
        'products': [
            {'order_product_id': 991, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 1, 'price_brutto': 800.00},
        ],
    }
    baza.update(nadpisania)
    return baza


DEBOWY = 'Blat dębowy lity A/B 100x50x2 cm'
BUKOWY = 'Blat bukowy lity B/B 140x70x3 cm'
JESIONOWY = 'Blat jesionowy lity A/A 200x90x4 cm'


def produkt(order_product_id, nazwa=DEBOWY, quantity=1, price_brutto=800.00):
    """Pozycja tak, jak oddaje ja `getOrders`. `order_product_id=None` = bez klucza."""
    pozycja = {'name': nazwa, 'quantity': quantity, 'price_brutto': price_brutto}
    if order_product_id is not None:
        pozycja['order_product_id'] = order_product_id
    return pozycja


def zamowienie_z_backfillu(pozycje, order_id=50854536):
    """Zamowienie w takim stanie, w jakim zostawil je jednorazowy backfill.

    Wiersze pozycji NIE MAJA `bl_order_product_id` — zmierzone na
    woodpower_crm_local: wszystkie 7938 wierszy backfillu maja tam NULL
    i nigdy klucza nie dostana, bo zamowienia starsze niz trzy miesiace
    siedza w archiwum BaseLinkera, ktorego `getOrders` nie widzi.
    """
    zam = SalesOrder(baselinker_order_id=order_id, date_created=date(2026, 9, 18),
                     customer_name='Jan Przykładowy')
    zam.items = [SalesOrderItem(bl_order_product_id=None, **p) for p in pozycje]
    db.session.add(zam)
    db.session.commit()
    return zam


def test_pierwszy_zapis_tworzy_zamowienie_pozycje_i_klienta(app):
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie()])
        assert stat['nowe'] == 1
        assert stat['zaktualizowane'] == 0
        assert stat['pozycje'] == 1
        assert stat['klienci_nowi'] == 1

        zam = SalesOrder.query.one()
        assert zam.baselinker_order_id == 50854536
        assert zam.date_created == date(2026, 9, 18)
        assert zam.client_id is not None
        assert len(zam.items) == 1
        assert zam.items[0].bl_order_product_id == 991


def test_ponowny_zapis_tego_samego_zamowienia_nie_dubluje(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        stat = zapisz_zamowienia([zamowienie()])
        assert stat['nowe'] == 0
        assert stat['zaktualizowane'] == 1
        assert SalesOrder.query.count() == 1
        assert SalesOrderItem.query.count() == 1
        assert SalesClient.query.count() == 1


def test_ponowny_zapis_aktualizuje_pola_z_baselinkera(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zapisz_zamowienia([zamowienie(order_status_id=138620, payment_done=984.00,
                                      custom_extra_fields={'105623': 'Ewa Fikcyjna',
                                                           '106169': 'netto'})])
        zam = SalesOrder.query.one()
        assert zam.current_status == 'Produkcja zakończona'
        assert zam.caretaker == 'Ewa Fikcyjna'
        assert zam.paid_amount == Decimal('984.00')


def test_ponowny_zapis_nie_kasuje_kolumn_tylko_crm(app):
    # Rozlacznosc zbiorow ze spec 5.2: pol, ktorych BaseLinker nie zna,
    # synchronizacja nie ma prawa dotknac. Bez tego kazde pobranie zamowien
    # kasowalo by reczna prace w arkuszu.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zam = SalesOrder.query.one()
        zam.client_origin = 'Stały B2B'
        zam.own_transport = True
        zam.picked_up = True
        zam.paid_cash = Decimal('100.00')
        zam.advance_wp = Decimal('50.00')
        db.session.commit()

        zapisz_zamowienia([zamowienie(order_status_id=138620)])

        zam = SalesOrder.query.one()
        assert zam.client_origin == 'Stały B2B'
        assert zam.own_transport is True
        assert zam.picked_up is True
        assert zam.paid_cash == Decimal('100.00')
        assert zam.advance_wp == Decimal('50.00')
        assert zam.current_status == 'Produkcja zakończona'


def test_ponowny_zapis_aktualizuje_pozycje_i_dokłada_nowe(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zapisz_zamowienia([zamowienie(products=[
            {'order_product_id': 991, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 2, 'price_brutto': 800.00},
            {'order_product_id': 992, 'name': 'Blat bukowy lity B/B 140x70x3 cm',
             'quantity': 1, 'price_brutto': 300.00},
        ])])
        pozycje = SalesOrderItem.query.order_by(SalesOrderItem.bl_order_product_id).all()
        assert len(pozycje) == 2
        assert pozycje[0].quantity == 2
        assert pozycje[1].wood_species == 'buk'


# ===== reczna praca na pozycjach przezywa synchronizacje ================
#
# ZNALEZISKO KRYTYCZNE (kontrola adwersaryjna 22.09.2026): upsert podmienial
# CALA kolekcje pozycji (`zamowienie.items = [...]`), a `cascade` ma
# `delete-orphan` — kazde pobranie zamowien kasowalo wiersze i zakladalo je
# od nowa. Kolumny pozycji oznaczone w rejestrze jako CRM-owe (gatunek,
# technologia, klasa, wykonczenie, wymiary, grupa, rodzaj) sa EDYTOWALNE
# w arkuszu i BaseLinker ich nie zna — `setOrderProductFields` nie ustawia
# nazwy produktu, z ktorej parser je czyta (fields.py:216-227). Reczna
# poprawka przepadala wiec przy najblizszej synchronizacji, takze tej
# z crona produkcji. To ta sama rozlacznosc zbiorow ze spec 5.2, ktorej
# poziom ZAMOWIENIA pilnuje od poczatku.

def test_reczna_poprawka_pozycji_przezywa_synchronizacje(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        id_pozycji = pozycja.id

        # Operator poprawia w arkuszu to, czego parser nie wyczytal z nazwy.
        pozycja.wood_species = 'jesion'
        pozycja.wood_class = 'B/B'
        pozycja.finish_state = 'olejowane'
        pozycja.length_cm = Decimal('120.00')
        pozycja.group_type = 'usługa'
        pozycja.product_type = 'parapet'
        db.session.commit()

        zapisz_zamowienia([zamowienie()])

        pozycja = SalesOrderItem.query.one()
        assert pozycja.id == id_pozycji, 'pozycja zostala skasowana i odtworzona'
        assert pozycja.wood_species == 'jesion'
        assert pozycja.wood_class == 'B/B'
        assert pozycja.finish_state == 'olejowane'
        assert pozycja.length_cm == Decimal('120.00')
        assert pozycja.group_type == 'usługa'
        assert pozycja.product_type == 'parapet'


def test_pochodne_licza_sie_z_wymiarow_po_recznej_poprawce(app):
    # Objetosc, powierzchnia i cena za m3 to kolumny WYLICZANE — po recznej
    # zmianie wymiaru maja pochodzic z wymiaru, ktory NAPRAWDE jest
    # w wierszu, a nie z nazwy produktu w BaseLinkerze. Inaczej arkusz
    # pokazywalby w jednym wierszu nowa dlugosc i stara objetosc, a suma
    # „TTL m³" w stopce bylaby cicho zla.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        pozycja.length_cm = Decimal('120.00')     # z nazwy parser czyta 100
        db.session.commit()

        zapisz_zamowienia([zamowienie()])

        pozycja = SalesOrderItem.query.one()
        # 1,20 m x 0,50 m x 0,02 m = 0,012 m3, ilosc 1
        assert pozycja.volume_per_piece == Decimal('0.012000')
        assert pozycja.total_volume == Decimal('0.012000')
        # 2 * (1,20*0,50 + 1,20*0,02 + 0,50*0,02) = 1,2680 m2
        assert pozycja.total_surface_m2 == Decimal('1.2680')


def test_synchronizacja_nadal_nadpisuje_pozycje_w_polach_z_baselinkera(app):
    # Druga strona tej samej granicy: ilosc i cena NALEZA do BaseLinkera
    # (fields.py:243-245, zapis przez setOrderProductFields), wiec zmiana
    # w BL ma nadpisac wartosc u nas — takze wtedy, gdy ktos wczesniej
    # poprawil w tym wierszu kolumny CRM-owe.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        pozycja.wood_species = 'jesion'
        pozycja.quantity = 99
        pozycja.price_gross = Decimal('1.00')
        db.session.commit()

        zapisz_zamowienia([zamowienie(products=[
            {'order_product_id': 991, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 4, 'price_brutto': 950.00},
        ])])

        pozycja = SalesOrderItem.query.one()
        # Typ ceny zamowienia to „netto", wiec price_brutto z BL niesie NETTO.
        assert pozycja.quantity == 4
        assert pozycja.price_net == Decimal('950.00')
        assert pozycja.price_gross == Decimal('1168.50')
        assert pozycja.value_net == Decimal('3800.00')
        # Reczna poprawka kolumny CRM-owej dalej stoi.
        assert pozycja.wood_species == 'jesion'


def test_chronione_kolumny_pozycji_pochodza_z_rejestru_a_nie_z_recznej_listy(app):
    # Lista kolumn chronionych przed nadpisaniem MUSI byc pochodna rejestru
    # pol — recznie przepisana rozjechalaby sie z `fields.py` przy pierwszej
    # zmianie i cicho odslonila kolumne, ktora arkusz dalej pokazuje jako
    # edytowalna. Test pilnuje takze tego, ze kazda chroniona kolumna
    # naprawde wychodzi z mappera (literowka w rejestrze nie ma jak
    # zadzialac po cichu).
    from modules.reports.fields import POLA, Poziom, Zrodlo
    from modules.reports.ingest import KOLUMNY_POZYCJI_TYLKO_CRM, mapuj_pozycje

    z_rejestru = {nazwa for nazwa, pole in POLA.items()
                  if pole.poziom is Poziom.POZYCJA and pole.zrodlo is Zrodlo.CRM}
    assert KOLUMNY_POZYCJI_TYLKO_CRM == z_rejestru
    assert 'wood_species' in KOLUMNY_POZYCJI_TYLKO_CRM
    assert 'quantity' not in KOLUMNY_POZYCJI_TYLKO_CRM     # ta nalezy do BL

    klucze_mappera = set(mapuj_pozycje(zamowienie())[0])
    assert KOLUMNY_POZYCJI_TYLKO_CRM <= klucze_mappera


def test_pozycje_bez_identyfikatora_z_baselinkera_nie_mnoza_sie(app):
    # BaseLinker nie zawsze oddaje `order_product_id`. Pozycja bez klucza
    # nie ma tozsamosci, wiec NIE dopasowujemy jej do niczego — ale nie wolno
    # jej tez dokladac przy kazdym przebiegu, bo licznik pozycji rosnie wtedy
    # bez konca, a wraz z nim SUM po `sales_order_items`. Pierwszy zapis
    # (zamowienie nie ma jeszcze ani jednego wiersza, nie ma czego przestawic
    # ani zdublowac) zaklada wiersze; kazdy kolejny POMIJA je i liczy.
    produkty = [produkt(None, DEBOWY), produkt(None, BUKOWY, price_brutto=300.00)]
    with app.app_context():
        pierwszy = zapisz_zamowienia([zamowienie(products=produkty)])
        drugi = zapisz_zamowienia([zamowienie(products=produkty)])
        assert SalesOrderItem.query.count() == 2
        assert pierwszy['pozycje_nowe'] == 2
        assert drugi['pozycje_nowe'] == 0
        assert drugi['pozycje_pominiete'] == 2


# ===== TOZSAMOSC POZYCJI: KLUCZ ALBO NIC (fala 4, 22.09.2026) ===========
#
# Poprzednie rozwiazanie dopasowywalo pozycje trzema przebiegami: po kluczu,
# po nazwie i po kolejnosci. Kontrola adwersaryjna zlamala dwa slabsze
# WYKONANIEM, wiec heurystyki tozsamosci znikaja w calosci. Regula, ktorej
# pilnuja testy ponizej:
#   1. dopasowanie WYLACZNIE po `bl_order_product_id`;
#   2. wiersza BEZ klucza nie usuwamy NIGDY (to dziedzictwo backfillu);
#   3. usuwamy wylacznie wiersz, ktory MA klucz, a klucza nie ma w przysylce;
#   4. pozycji z BL bez klucza nie dopasowujemy do niczego;
#   5. przysylka pusta albo niepelna (pozycja bez klucza) niczego nie kasuje;
#   6. kazde usuniecie i kazde pominiecie jest policzone i widoczne.
#
# Cena tej zachowawczosci jest jawna i zmierzona: wiersz bez klucza, ktorego
# BaseLinker przysyla dzis pod kluczem, zostaje obok nowego — czyli dubluje
# sie w arkuszu. Dublet WIDAC, przestawione dane RECZNE — nie. Licznik
# `pozycje_zachowane_bez_klucza` pokazuje skale zjawiska.

def test_pozycja_z_bl_bez_klucza_nie_przejmuje_wiersza_z_kluczem(app):
    # ZNALEZISKO KRYTYCZNE 1. Przebiegi „po nazwie" i „po kolejnosci"
    # warunkowaly dopasowanie BRAKIEM klucza w wierszu, wiec pozycja z BL bez
    # `order_product_id` nie trafiala do wiersza, ktory ten klucz JUZ MA.
    # Wiersz zostawal nieprzypisany i wypadal z kolekcji jako „skasowany
    # w BaseLinkerze" — razem z cala reczna praca — a na jego miejsce
    # wchodzil swiezy, pusty.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        id_pozycji = pozycja.id
        pozycja.wood_species = 'jesion'            # reczna poprawka w arkuszu
        db.session.commit()

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(None, DEBOWY, quantity=9)])])
        db.session.expire_all()

        pozycje = SalesOrderItem.query.all()
        assert len(pozycje) == 1
        assert pozycje[0].id == id_pozycji, 'wiersz zostal skasowany i odtworzony'
        assert pozycje[0].bl_order_product_id == 991
        assert pozycje[0].wood_species == 'jesion'
        assert pozycje[0].quantity == 1, 'bezkluczowa pozycja nadpisala wiersz'
        assert stat['pozycje_pominiete'] == 1
        assert stat['pozycje_usuniete'] == 0
        assert stat['ostrzezenie'], 'pominiecie przeszlo po cichu'


def test_nowy_produkt_nie_przejmuje_wiersza_po_pozycji_skasowanej_w_bl(app):
    # ZNALEZISKO KRYTYCZNE 2. Wiersze bez klucza (czyli CALY backfill) plus
    # przebieg „po kolejnosci": gdy w BaseLinkerze jedna pozycja znika, a inna
    # dochodzi, NOWY produkt siadal na wierszu po SKASOWANYM i przejmowal jego
    # reczne poprawki. To nie utrata danych, tylko ich PRZESTAWIENIE —
    # gorsze, bo z arkusza niewidoczne.
    with app.app_context():
        zam = zamowienie_z_backfillu([
            {'quantity': 1, 'raw_product_name': DEBOWY, 'wood_species': 'dąb'},
            {'quantity': 1, 'raw_product_name': BUKOWY, 'wood_species': 'buk',
             'finish_state': 'olejowane'},          # reczna praca operatora
        ])
        id_bukowej = zam.items[1].id

        # W BaseLinkerze bukowy znika, a dochodzi zupelnie inny produkt.
        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, quantity=3),
            produkt(993, JESIONOWY, quantity=1, price_brutto=1500.00),
        ])])
        db.session.expire_all()

        bukowa = SalesOrderItem.query.get(id_bukowej)
        assert bukowa is not None, 'wiersz bez klucza zostal skasowany'
        assert bukowa.raw_product_name == BUKOWY, 'nowy produkt przejal wiersz'
        assert bukowa.wood_species == 'buk'
        assert bukowa.finish_state == 'olejowane'
        assert bukowa.quantity == 1
        assert bukowa.bl_order_product_id is None
        assert stat['pozycje_nowe'] == 2
        assert stat['pozycje_usuniete'] == 0
        assert stat['pozycje_zachowane_bez_klucza'] == 2


def test_pusta_lista_pozycji_z_bl_nie_kasuje_niczego(app):
    # ZNALEZISKO WAZNE. Zmierzone 1 -> 0: pusta lista `products` kasowala
    # komplet pozycji razem z reczna praca. Pusta przysylka nie jest dowodem
    # na to, ze zamowienie nie ma pozycji — jest dowodem na to, ze cos poszlo
    # nie tak po stronie BaseLinkera.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        id_pozycji = pozycja.id
        pozycja.wood_species = 'jesion'
        db.session.commit()

        stat = zapisz_zamowienia([zamowienie(products=[])])
        db.session.expire_all()

        pozycje = SalesOrderItem.query.all()
        assert len(pozycje) == 1
        assert pozycje[0].id == id_pozycji
        assert pozycje[0].wood_species == 'jesion'
        assert stat['pozycje_usuniete'] == 0
        assert stat['podejrzane_paczki_pozycji'] == 1
        assert stat['ostrzezenie'], 'podejrzana przysylka przeszla po cichu'


def test_wiersze_o_identycznej_nazwie_nie_sa_przestawiane(app):
    # ZNALEZISKO WAZNE. Nazwa nie rozstrzyga miedzy wierszami o IDENTYCZNEJ
    # nazwie — a takie sa w danych normalne (dwa te same blaty w jednym
    # zamowieniu, rozniace sie wylacznie reczna adnotacja). Dopasowanie
    # po nazwie mieszalo im dane; teraz nie dopasowujemy ich wcale.
    with app.app_context():
        zam = zamowienie_z_backfillu([
            {'quantity': 1, 'raw_product_name': DEBOWY, 'wood_species': 'jesion',
             'product_type': 'blat'},
            {'quantity': 4, 'raw_product_name': DEBOWY, 'wood_species': 'dąb',
             'product_type': 'parapet'},
        ])
        id_pierwszej, id_drugiej = zam.items[0].id, zam.items[1].id

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, quantity=7),
            produkt(992, DEBOWY, quantity=8, price_brutto=900.00),
        ])])
        db.session.expire_all()

        pierwsza = SalesOrderItem.query.get(id_pierwszej)
        druga = SalesOrderItem.query.get(id_drugiej)
        assert (pierwsza.quantity, pierwsza.product_type) == (1, 'blat')
        assert (druga.quantity, druga.product_type) == (4, 'parapet')
        assert SalesOrderItem.query.count() == 4
        assert stat['pozycje_nowe'] == 2
        assert stat['pozycje_zachowane_bez_klucza'] == 2


def test_wiersz_bez_klucza_nie_znika_choc_bl_go_nie_przyslal(app):
    # Regula 2: wiersza bez klucza nie usuwamy NIGDY. Tu przysylka jest
    # pelna (kazda pozycja ma klucz), wiec usuwanie w ogole dziala — a mimo
    # to wiersz-dziedzictwo zostaje. Stary przebieg „po kolejnosci" oddawal
    # go pierwszej lepszej pozycji z BL.
    with app.app_context():
        zam = zamowienie_z_backfillu([
            {'quantity': 2, 'raw_product_name': 'Suszenie tarcicy',
             'group_type': 'usługa'},
        ])
        id_uslugi = zam.items[0].id

        stat = zapisz_zamowienia([zamowienie()])     # BL zna tylko pozycje 991
        db.session.expire_all()

        usluga = SalesOrderItem.query.get(id_uslugi)
        assert usluga is not None
        assert usluga.raw_product_name == 'Suszenie tarcicy'
        assert usluga.bl_order_product_id is None
        assert SalesOrderItem.query.count() == 2
        assert stat['pozycje_usuniete'] == 0
        assert stat['pozycje_zachowane_bez_klucza'] == 1


def test_zmiana_kolejnosci_pozycji_w_bl_nie_przestawia_danych(app):
    # Kolejnosc pozycji w odpowiedzi BaseLinkera nie jest gwarantowana.
    # Dopasowanie po kluczu jest na nia odporne z definicji — ten test jest
    # zabezpieczeniem przed powrotem jakiegokolwiek przebiegu „po kolejnosci".
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(992, BUKOWY, price_brutto=300.00)])])
        po_kluczu = {p.bl_order_product_id: p.id for p in SalesOrderItem.query.all()}
        for pozycja in SalesOrderItem.query.all():
            pozycja.finish_state = ('olejowane' if pozycja.bl_order_product_id == 991
                                    else 'surowe')
        db.session.commit()

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(992, BUKOWY, quantity=5, price_brutto=300.00),
            produkt(991, DEBOWY, quantity=7),
        ])])
        db.session.expire_all()

        debowa = SalesOrderItem.query.get(po_kluczu[991])
        bukowa = SalesOrderItem.query.get(po_kluczu[992])
        assert (debowa.quantity, debowa.finish_state) == (7, 'olejowane')
        assert (bukowa.quantity, bukowa.finish_state) == (5, 'surowe')
        assert stat['pozycje_zaktualizowane'] == 2
        assert stat['pozycje_nowe'] == 0
        assert stat['pozycje_usuniete'] == 0


def test_dane_z_bl_nadal_nadpisuja_swoje_pola_mimo_wiersza_bez_klucza(app):
    # Kontrola pozytywna do calej tej zachowawczosci: obecnosc wiersza bez
    # klucza NIE zamraza aktualizacji. Ilosc i cena naleza do BaseLinkera
    # (fields.py) i pozycja dopasowana po kluczu ma je przyjac.
    with app.app_context():
        zamowienie_z_backfillu([
            {'quantity': 2, 'raw_product_name': 'Suszenie tarcicy',
             'group_type': 'usługa'},
        ])
        zapisz_zamowienia([zamowienie()])            # zaklada wiersz z kluczem 991
        db.session.expire_all()

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, quantity=4, price_brutto=950.00)])])
        db.session.expire_all()

        pozycja = SalesOrderItem.query.filter_by(bl_order_product_id=991).one()
        # Typ ceny zamowienia to „netto", wiec price_brutto z BL niesie NETTO.
        assert pozycja.quantity == 4
        assert pozycja.price_net == Decimal('950.00')
        assert pozycja.value_net == Decimal('3800.00')
        assert stat['pozycje_zaktualizowane'] == 1


def test_pozycja_usunieta_w_baselinkerze_znika_takze_u_nas(app):
    # Regula 3: wiersz Z kluczem, ktorego klucza nie ma w PELNEJ przysylce,
    # znika — to jedyny przypadek, w ktorym cokolwiek kasujemy.
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(992, BUKOWY, price_brutto=300.00)])])
        assert SalesOrderItem.query.count() == 2

        stat = zapisz_zamowienia([zamowienie()])
        db.session.expire_all()

        assert SalesOrderItem.query.count() == 1
        assert SalesOrderItem.query.one().bl_order_product_id == 991
        assert stat['pozycje_usuniete'] == 1


def test_pozycja_dodana_i_usunieta_w_bl_sa_policzone_osobno(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(992, BUKOWY, price_brutto=300.00)])])

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, quantity=2),
            produkt(993, JESIONOWY, price_brutto=1500.00),
        ])])
        db.session.expire_all()

        assert {p.bl_order_product_id for p in SalesOrderItem.query.all()} == {991, 993}
        assert stat['pozycje_nowe'] == 1
        assert stat['pozycje_zaktualizowane'] == 1
        assert stat['pozycje_usuniete'] == 1


def test_kasowanie_pozycji_zostawia_slad_w_logu(app, monkeypatch):
    # „Koniec cichych kasowan": usuniecie wiersza ma byc widoczne w logu
    # na poziomie ostrzezenia, nie tylko w bazie.
    from modules.reports import ingest

    zapisane = []
    monkeypatch.setattr(ingest.logger, 'warning',
                        lambda komunikat, **dane: zapisane.append((komunikat, dane)))
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(992, BUKOWY, price_brutto=300.00)])])
        assert not [d for _, d in zapisane if d.get('pozycje_usuniete')]

        zapisz_zamowienia([zamowienie()])

    assert any(d.get('pozycje_usuniete') == 1 for _, d in zapisane), \
        'skasowanie pozycji nie zostawilo sladu w logu'


def test_klient_deduplikuje_sie_po_mailu_miedzy_zamowieniami(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_id=1), zamowienie(order_id=2)])
        assert SalesOrder.query.count() == 2
        assert SalesClient.query.count() == 1


def test_klient_dostaje_nip_z_danych_do_faktury(app):
    # Backfill nie mial skad wziac NIP-u (stara tabela go nie trzymala),
    # wiec szczebel NIP-owy kaskady byl w nim martwy, a client_kind zawsze
    # 'detal'. Zapis przyrostowy czyta invoice_nip wprost z BaseLinkera.
    with app.app_context():
        zapisz_zamowienia([zamowienie(email='', invoice_nip='123-456-78-90')])
        klient = SalesClient.query.one()
        assert klient.nip_norm == '1234567890'
        assert klient.client_kind == 'b2b'


def test_liczniki_klienta_nie_rosna_przy_powtornym_zapisie(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zapisz_zamowienia([zamowienie()])
        klient = SalesClient.query.one()
        assert klient.orders_count == 1
        assert klient.lifetime_net == Decimal('800.00')


def test_liczniki_klienta_obejmuja_pierwsze_i_ostatnie_zamowienie(app):
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_id=1),
                           zamowienie(order_id=2, date_add=TS_19_09)])
        klient = SalesClient.query.one()
        assert klient.orders_count == 2
        assert klient.first_order_at == date(2026, 9, 18)
        assert klient.last_order_at == date(2026, 9, 19)
        assert klient.lifetime_net == Decimal('1600.00')


def _liczniki_klienta():
    # expire_all: zapis idzie WŁASNĄ sesją analityki, więc obiekt z `db.session`
    # trzymałby stan sprzed kolejnej synchronizacji.
    db.session.expire_all()
    klient = SalesClient.query.one()
    return (klient.orders_count, klient.lifetime_net,
            klient.first_order_at, klient.last_order_at)


def test_zmiana_statusu_przelicza_klienta_w_obie_strony(app):
    """Partia E, punkt E5: anulowane i nieopłacone nie są sprzedażą, więc nie
    wchodzą do denormalizacji klienta. Przejście statusu przy kolejnej
    synchronizacji ma ją przeliczyć — nieopłacone → opłacone dokłada
    zamówienie, opłacone → anulowane je zabiera."""
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_status_id=105112)])   # nieopłacone
        assert _liczniki_klienta() == (0, Decimal('0.00'), None, None)

        zapisz_zamowienia([zamowienie(order_status_id=155824)])   # opłacone
        assert _liczniki_klienta() == (1, Decimal('800.00'),
                                       date(2026, 9, 18), date(2026, 9, 18))

        zapisz_zamowienia([zamowienie(order_status_id=138625)])   # anulowane
        assert _liczniki_klienta() == (0, Decimal('0.00'), None, None)


def test_anulowane_nie_przesuwa_dat_klienta(app):
    """Klient z zamówieniem opłaconym 19.09 i anulowanym 18.09: pierwsze
    zamówienie to 19.09 — inaczej karta „Nowi w okresie" liczyłaby go
    według daty zamówienia, którego nie było."""
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_id=1, order_status_id=138625),
                           zamowienie(order_id=2, date_add=TS_19_09)])
        assert _liczniki_klienta() == (1, Decimal('800.00'),
                                       date(2026, 9, 19), date(2026, 9, 19))


def test_zamowienie_bez_numeru_baselinkera_jest_pomijane_i_liczone(app):
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id=None)])
        assert stat['pominiete'] == 1
        assert stat['nowe'] == 0
        assert SalesOrder.query.count() == 0
        # ZNALEZISKO WAZNE (przeglad Zadania 6): pomijamy, ale MELDUJEMY.
        # Zamowienie bez numeru BL przepadalo cicho, a nie ma jak go potem
        # dosynchronizowac — uzytkownik musi o tym wiedziec.
        assert len(stat['bledy']) == 1
        assert stat['bledy'][0]['order_id'] is None
        assert 'bez numeru' in stat['bledy'][0]['blad']


@pytest.mark.parametrize('bez_numeru', [None, '', 0, 'abc', 0.4])
def test_zamowienie_bez_numeru_nigdy_nie_zapisuje_sie_jako_zero(app, bez_numeru):
    # ZNALEZISKO WAZNE (przeglad Zadania 6): `baselinker_order_id` jest
    # UNIQUE. Zapisanie braku numeru jako 0 zajmowaloby ten slot na stale,
    # a DRUGIE takie zamowienie wywracaloby zapis na duplikacie klucza
    # zamiast zostac pominiete. Ta sama decyzja, co w
    # scripts/backfill_sales_tables.py (licznik `bez_numeru_bl`).
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id=bez_numeru),
                                  zamowienie(order_id=bez_numeru)])
        assert stat['pominiete'] == 2
        assert stat['nowe'] == 0
        assert SalesOrder.query.count() == 0
        assert SalesOrder.query.filter_by(baselinker_order_id=0).count() == 0
        # Dwa takie zamowienia w jednej paczce to dwa czyste pominiecia,
        # a nie wyjatek IntegrityError na drugim z nich.
        assert all('bez numeru' in b['blad'] for b in stat['bledy'])


def test_element_nie_bedacy_slownikiem_jest_pomijany(app):
    with app.app_context():
        stat = zapisz_zamowienia(['śmieć', None, 42])
        assert stat['pominiete'] == 3
        assert stat['bledy'] == []


def test_bledne_zamowienie_nie_przerywa_reszty_paczki(app, monkeypatch):
    import modules.reports.ingest as ingest
    oryginal = ingest.mapuj_pozycje

    def wybuchowy(order):
        if order.get('order_id') == 2:
            raise ValueError('sztuczna awaria mappera')
        return oryginal(order)

    monkeypatch.setattr(ingest, 'mapuj_pozycje', wybuchowy)
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id=1), zamowienie(order_id=2),
                                  zamowienie(order_id=3)])
        assert stat['nowe'] == 2
        assert len(stat['bledy']) == 1
        assert stat['bledy'][0]['order_id'] == 2
        assert 'sztuczna awaria' in stat['bledy'][0]['blad']
        assert {z.baselinker_order_id for z in SalesOrder.query.all()} == {1, 3}


def test_wynik_ma_komplet_kluczy_statystyk(app):
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie()], zrodlo='produkcja')
        assert set(stat) == {'nowe', 'zaktualizowane', 'pozycje', 'klienci_nowi',
                             'pominiete', 'bledy', 'zrodlo', 'ostrzezenie',
                             'pozycje_nowe', 'pozycje_zaktualizowane',
                             'pozycje_usuniete', 'pozycje_pominiete',
                             'pozycje_zachowane_bez_klucza',
                             'podejrzane_paczki_pozycji',
                             # Fala 5: powod pominiecia pozycji (powtorzony
                             # klucz w przysylce) i duplikat zamowienia
                             # w paczce — jedno i drugie musi byc widoczne
                             # w wyniku, nie tylko w bazie.
                             'pozycje_powtorzony_klucz', 'duplikaty_zamowien'}
        assert stat['ostrzezenie'] is None   # paczka przeszla w komplecie
        assert stat['zrodlo'] == 'produkcja'
        # `pozycje` liczy pozycje PRZYSLANE przez BaseLinkera. To za malo,
        # zeby zobaczyc, co sie z nimi stalo — stad osobne liczniki tego,
        # co naprawde powstalo, zmienilo sie, zniknelo i zostalo pominiete.
        assert stat['pozycje'] == 1
        assert stat['pozycje_nowe'] == 1
        assert stat['pozycje_zaktualizowane'] == 0
        assert stat['pozycje_usuniete'] == 0


def test_pusta_lista_nie_wywala_i_zwraca_zera(app):
    with app.app_context():
        stat = zapisz_zamowienia([])
        assert stat['nowe'] == 0 and stat['pozycje'] == 0 and stat['bledy'] == []


def test_saldo_po_zapisie_siedzi_wylacznie_na_zamowieniu(app):
    # Niezmiennik, ktory poprzednik lamal 7,58-krotnie: SUM po pozycjach
    # nie ma prawa wyprodukowac salda.
    with app.app_context():
        zapisz_zamowienia([zamowienie(payment_done=300.00, products=[
            {'order_product_id': 1, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 1, 'price_brutto': 400.00},
            {'order_product_id': 2, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 1, 'price_brutto': 400.00},
        ])])
        zam = SalesOrder.query.one()
        assert zam.balance_due == Decimal('500.00')
        assert not any(hasattr(p, 'balance_due') for p in zam.items)


# --- Testy z przeglądu Zadania 2 -------------------------------------------
#
# Żaden z 16 testów powyżej (podanych w briefie) nie dotyka gałęzi „zamówienie
# bez klucza dedupikacji" — wszystkie podają mail albo NIP. Testy niżej łapią
# pięć znalezisk z przeglądu.


def test_zamowienie_bez_zadnego_klucza_dedupikacji_nie_mnozy_klientow(app):
    # ZNALEZISKO KRYTYCZNE: `znajdz_lub_utworz_klienta` przy braku maila,
    # NIP-u i telefonu >=9 cyfr ZAWSZE zakłada nowego klienta (dedup.py).
    # Bez re-pinowania istniejącego klienta każdy kolejny przebieg tego
    # samego zamówienia (cron produkcji, powtórne „Pobierz zamówienia")
    # dokładałby kolejnego sierotę: 3 przebiegi = 3 wiersze w sales_clients,
    # SUM(lifetime_net) potrojone, a osierocone rekordy zostają z zerem
    # dowiązanych zamówień.
    with app.app_context():
        zam = zamowienie(email='', phone='123')  # telefon <9 cyfr, brak NIP-u
        stat = None
        for _ in range(3):
            stat = zapisz_zamowienia([zam])

        assert SalesClient.query.count() == 1
        assert SalesOrder.query.count() == 1
        assert stat['klienci_nowi'] == 0
        assert stat['zaktualizowane'] == 1

        klient = SalesClient.query.one()
        assert klient.orders_count == 1
        assert klient.lifetime_net == Decimal('800.00')
        assert SalesOrder.query.filter_by(client_id=klient.id).count() == 1


def test_klient_traci_zamowienie_gdy_ono_przenosi_sie_do_innego_klienta(app):
    # ZNALEZISKO WAŻNE: gdy zamówienie zmienia klienta między przebiegami
    # (poprawiony e-mail w BaseLinkerze, dopisany NIP), stary klient bez
    # przeliczenia zostawał z licznikami po zamówieniu, które już do niego
    # nie należy (orders_count=1, lifetime_net=800.00 przy zerze powiązanych
    # zamówień).
    #
    # `db.session.remove()` po kazdym zapisie jest tu KONIECZNE: analityka
    # pisze przez WLASNA sesje (patrz „WLASNOSC SESJI" w ingest.py), wiec
    # obiekty wczytane wczesniej przez `db.session` zostaja w jej mapie
    # tozsamosci ze starymi licznikami. Test sprawdza stan ZAPISANY, wiec
    # czyta go swiezą sesja.
    with app.app_context():
        zapisz_zamowienia([zamowienie(email='a@example.com', phone='')])
        db.session.remove()
        stary_klient = SalesClient.query.filter_by(email_norm='a@example.com').one()
        assert stary_klient.orders_count == 1
        assert stary_klient.lifetime_net == Decimal('800.00')

        zapisz_zamowienia([zamowienie(email='b@example.com', phone='')])
        db.session.remove()

        stary_klient = SalesClient.query.filter_by(email_norm='a@example.com').one()
        assert stary_klient.orders_count == 0
        assert stary_klient.lifetime_net == Decimal('0.00')

        nowy_klient = SalesClient.query.filter_by(email_norm='b@example.com').one()
        assert nowy_klient.orders_count == 1
        assert nowy_klient.lifetime_net == Decimal('800.00')
        assert SalesOrder.query.one().client_id == nowy_klient.id


def test_zamowienie_podane_pod_kluczem_id_jest_idempotentne(app):
    # ZNALEZISKO WAŻNE: `mapuj_zamowienie` czyta WYŁĄCZNIE `order_id`
    # (domyślnie 0) — bez wymuszenia `baselinker_order_id` po pętli setattr,
    # zamówienie podane pod kluczem `id` zapisywało się z numerem 0, a drugi
    # przebieg wpadał w UNIQUE constraint zamiast zaktualizować wiersz.
    with app.app_context():
        zam = zamowienie()
        zam['id'] = zam.pop('order_id')

        stat1 = zapisz_zamowienia([zam])
        assert stat1['nowe'] == 1
        assert stat1['pominiete'] == 0
        assert stat1['bledy'] == []
        assert SalesOrder.query.one().baselinker_order_id == 50854536

        stat2 = zapisz_zamowienia([zam])
        assert stat2['bledy'] == []
        assert stat2['zaktualizowane'] == 1
        assert SalesOrder.query.count() == 1


def test_zamowienie_z_order_id_zmiennoprzecinkowym_jest_idempotentne(app):
    # To samo znalezisko co wyżej, druga odsłona: `order_id` zmiennoprzecinkowy
    # (12.9) musi konwertować się na TĘ SAMĄ liczbę (12) przy wyszukaniu wiersza
    # i przy jego zapisaniu, inaczej drugi przebieg tworzy duplikat i wywala
    # się na UNIQUE constraint.
    with app.app_context():
        stat1 = zapisz_zamowienia([zamowienie(order_id=12.9)])
        assert stat1['nowe'] == 1
        assert stat1['bledy'] == []
        assert SalesOrder.query.one().baselinker_order_id == 12

        stat2 = zapisz_zamowienia([zamowienie(order_id=12.9)])
        assert stat2['bledy'] == []
        assert stat2['zaktualizowane'] == 1
        assert SalesOrder.query.count() == 1


def test_order_id_niekonwertowalny_na_int_jest_pomijany(app):
    # Wariant tego samego znaleziska: order_id nienumeryczny nie ma prawa
    # zapisać się jako 0 (zajmując ten slot na stałe) — ma być pominięty.
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id='abc')])
        assert stat['pominiete'] == 1
        assert stat['nowe'] == 0
        assert len(stat['bledy']) == 1
        assert stat['bledy'][0]['order_id'] is None
        assert SalesOrder.query.count() == 0


def test_blad_w_wyniku_nie_zawiera_calego_wyjatku_z_parametrami(app, monkeypatch):
    # ZNALEZISKO WAŻNE: `str(wyjątku)` dla `IntegrityError` SQLAlchemy wkleja
    # cały INSERT z parametrami — imię, mail, telefon, adres klienta. Ten
    # słownik trafia do przeglądarki przez endpointy Zadań 4/6, więc w
    # `bledy` ma iść krótki komunikat (typ + pierwsza linia), nie cały
    # `str(wyjątku)`.
    import modules.reports.ingest as ingest

    komunikat = (
        "(pymysql.err.IntegrityError) (1062, \"Duplicate entry '50854536'\")\n"
        "[SQL: INSERT INTO sales_orders (customer_name, email, phone, "
        "delivery_address) VALUES (%s, %s, %s, %s)]\n"
        "[parameters: ('Jan Przykładowy', 'jan.przykladowy@example.com', "
        "'+48 601 202 303', 'ul. Testowa 1')]"
    )

    def wybuchowy(order):
        raise RuntimeError(komunikat)

    monkeypatch.setattr(ingest, 'mapuj_pozycje', wybuchowy)
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie()])
        assert len(stat['bledy']) == 1
        blad = stat['bledy'][0]['blad']
        assert 'RuntimeError' in blad
        assert "Duplicate entry" in blad
        assert 'jan.przykladowy@example.com' not in blad
        assert 'Jan Przykładowy' not in blad
        assert 'Testowa' not in blad
        assert len(blad) < len(komunikat)


def test_klienci_nowi_nie_rosnie_gdy_zapis_zamowienia_sie_nie_udal(app, monkeypatch):
    # ZNALEZISKO WAŻNE: `stat['klienci_nowi']` rosło PRZED commitem (od razu
    # po `flush()` tworzącym klienta). `db.session.rollback()` po awarii
    # dalszej części zapisu cofał wstawienie klienta, ale licznik zostawał
    # podbity — funkcja raportowała klienci_nowi=1 przy zera wierszach
    # w sales_clients.
    import modules.reports.ingest as ingest

    def wybuchowy(klient, sesja):
        raise RuntimeError('sztuczna awaria po utworzeniu klienta')

    monkeypatch.setattr(ingest, '_przelicz_klienta', wybuchowy)
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie()])
        assert stat['klienci_nowi'] == 0
        assert stat['nowe'] == 0
        assert len(stat['bledy']) == 1
        assert SalesClient.query.count() == 0
        assert SalesOrder.query.count() == 0


# ===== wlasnosc sesji ===================================================
#
# ZNALEZISKO KRYTYCZNE (kontrola adwersaryjna 22.09.2026). Do tej zmiany
# `zapisz_zamowienia` wolalo `db.session.commit()` po kazdym zamowieniu
# i `db.session.rollback()` przy bledzie. Sesja jest w Flasku JEDNA
# i wspoldzielona z produkcja, wiec analityka mogla zatwierdzic albo
# WYCOFAC niedokonczona prace produkcji — a produkcja to tor krytyczny,
# na jej danych pracuja tablety na hali.
#
# Straznik `sesja_bez_cudzych_zmian()` tego nie lapal: patrzyl na
# `db.session.new/dirty/deleted`, a produkcja zostawia prace ZFLUSHOWANA,
# czyli te zbiory sa puste. Zostal usuniety razem z cala konstrukcja —
# analityka ma teraz WLASNA sesje i `db.session` nie dotyka wcale.

def _szpieg_wspolnej_sesji(monkeypatch):
    """Podglada `commit()`/`rollback()` na prawdziwym obiekcie `Session`
    spod rejestru `scoped_session`. Spy na klasie `Session` nie odroznilby
    sesji wspolnej od wlasnej sesji analityki."""
    wolania = []
    sesja = db.session()
    for nazwa in ('commit', 'rollback'):
        oryginal = getattr(sesja, nazwa)

        def opakowanie(_oryginal=oryginal, _nazwa=nazwa):
            wolania.append(_nazwa)
            return _oryginal()

        monkeypatch.setattr(sesja, nazwa, opakowanie)
    return wolania


def test_zapis_nie_wola_commita_ani_rollbacku_na_wspolnej_sesji(app, monkeypatch):
    # Paczka mieszana: jedno zamowienie poprawne (sciezka commita) i jedno
    # felerne (sciezka rollbacku). Ani jedno, ani drugie nie ma prawa siegnac
    # do `db.session`.
    with app.app_context():
        wolania = _szpieg_wspolnej_sesji(monkeypatch)

        stat = zapisz_zamowienia([
            zamowienie(order_id=1),
            zamowienie(order_id=2, delivery_price='nie-liczba'),
        ])

        assert stat['nowe'] == 1
        assert len(stat['bledy']) == 1
        assert wolania == [], 'analityka ruszyla wspoldzielona sesje: %r' % (wolania,)


def test_cudza_niezatwierdzona_praca_nie_blokuje_juz_zapisu(app):
    # ZMIANA ZACHOWANIA i jest zamierzona. Dawniej straznik odrzucal CALA
    # paczke, gdy ktokolwiek mial cos niezatwierdzonego w `db.session` —
    # analityka po cichu nie dostawala nic. Wlasna sesja zdejmuje ten powod:
    # analityka pisze normalnie, a cudza praca zostaje nietknieta.
    with app.app_context():
        obcy = SalesClient(display_name='Cudzy wiersz w toku')
        db.session.add(obcy)   # dodany, NIE zatwierdzony

        stat = zapisz_zamowienia([zamowienie()])

        # Asercja musi isc przed jakimkolwiek zapytaniem przez `db.session`,
        # bo autoflush sam wypchnalby `obcy` z `session.new`.
        assert obcy in db.session.new
        assert stat['nowe'] == 1
        assert stat['pominiete'] == 0
        assert stat['bledy'] == []

        with db.session.no_autoflush:
            assert SalesOrder.query.count() == 1

        db.session.rollback()


# ===== ksztalt argumentu ================================================

@pytest.mark.parametrize('argument', [42, 'smiec', 3.14, {'order_id': 1}])
def test_argument_nie_bedacy_lista_nie_wypuszcza_wyjatku(app, argument):
    # ZNALEZISKO DROBNE (przeglad Zadania 6): `zapisz_zamowienia(42)`
    # wypuszczal na zewnatrz TypeError z petli. Ta funkcja jest wolana
    # z zaczepu produkcji i z endpointu HTTP — jedno i drugie meldowaloby
    # awarie calej analityki, choc problemem jest wylacznie ksztalt
    # argumentu.
    with app.app_context():
        stat = zapisz_zamowienia(argument)
        assert stat['nowe'] == 0
        assert len(stat['bledy']) == 1
        assert SalesOrder.query.count() == 0


def test_none_zamiast_listy_to_pusta_paczka_a_nie_blad(app):
    with app.app_context():
        stat = zapisz_zamowienia(None)
        assert stat['nowe'] == 0
        assert stat['bledy'] == []


# ===== zapisane wartosci zgadzaja sie z danymi historycznymi ============

def test_wojewodztwo_zapisuje_sie_wielka_litera_jak_cala_baza(app):
    # Zmierzone na woodpower_crm_local: sales_orders ma 3028 wierszy
    # z WIELKIEJ litery i 0 z malej, baselinker_reports_orders — 6543 z
    # wielkiej i 0 z malej. Male litery rozbilyby slownik wojewodztw na
    # dwa kubelki dla jednego regionu.
    with app.app_context():
        zapisz_zamowienia([zamowienie(delivery_state='śląskie'),
                           zamowienie(order_id=50854537, delivery_state='',
                                      delivery_postcode='00-950')])
        zapisane = sorted(z.delivery_state for z in SalesOrder.query.all())
        assert zapisane == ['Mazowieckie', 'Śląskie']
        for wartosc in zapisane:
            wzorzec = BaselinkerReportOrder(delivery_state=wartosc)
            wzorzec.normalize_delivery_state()
            assert wartosc == wzorzec.delivery_state


def test_powierzchnia_zapisana_zgadza_sie_ze_wzorem_historycznym(app):
    # Kolumna total_surface_m2 niesie pole CALEGO prostopadloscianu
    # (19 096,25 m2 w 7911 wierszach historycznych), nie jednej sciany
    # (8 563,81 m2). Test sprawdza wartosc PO ZAPISIE, a nie tylko
    # z mappera — kolumna ma DECIMAL(10,4).
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            {'order_product_id': 991, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
             'quantity': 3, 'price_brutto': 800.00}])])
        pozycja = SalesOrderItem.query.one()

        wzorzec = BaselinkerReportOrder(
            length_cm=pozycja.length_cm, width_cm=pozycja.width_cm,
            thickness_cm=pozycja.thickness_cm, quantity=pozycja.quantity)
        assert float(pozycja.total_surface_m2) == wzorzec.calculate_surface_area()
        assert float(pozycja.total_surface_m2) == 3.18


def test_brak_statusu_zapisuje_sie_jako_null(app):
    # Kolumna current_status jest indeksowana i widoczna w arkuszu —
    # doslowny napis "Status None" trafilby uzytkownikowi wprost do komorki.
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_status_id=None)])
        zam = SalesOrder.query.one()
        assert zam.current_status is None
        assert zam.baselinker_status_id is None


def test_data_zamowienia_zapisuje_sie_w_strefie_warszawskiej(app):
    # TS_NOCNY to 2026-09-18 23:30 UTC, czyli 2026-09-19 01:30 w Polsce.
    # Zegar kontenera (UTC) wpisalby tu 18 wrzesnia i zamowienie z nocy
    # 19-go liczyloby sie do sprzedazy dnia poprzedniego.
    with app.app_context():
        zapisz_zamowienia([zamowienie(date_add=TS_NOCNY, date_confirmed=TS_NOCNY,
                                      payment_done=100.0)])
        zam = SalesOrder.query.one()
        assert zam.date_created == date(2026, 9, 19)
        assert zam.payment_date == date(2026, 9, 19)


# ===== RESZTKI PO REGULE „KLUCZ ALBO NIC" (fala 5, 22.09.2026) ==========
#
# Regula z fali 4 (dopasowanie WYLACZNIE po `bl_order_product_id`) miala
# cztery szczeliny, wszystkie zmierzone przez kontrole adwersaryjna. Testy
# ponizej pilnuja ich zamkniecia.


def zamowienie_z_wierszami(wiersze, order_id=50854536):
    """Zamowienie z wierszami podanymi WPROST (takze z `bl_order_product_id`).

    `zamowienie_z_backfillu` zaklada wiersze bez klucza; tutaj potrzebny jest
    stan dowolny.

    UWAGA (23.09.2026): DWOCH wierszy jednego zamowienia o tym samym kluczu
    juz sie tedy nie zbuduje. Migracja `2026-09-23-unikalnosc-klucza-pozycji`
    zalozyla UNIQUE(order_id, bl_order_product_id), a od trzeciej kontroli
    adwersaryjnej to samo ograniczenie ma `SalesOrderItem.__table_args__` —
    wiec pilnuje go takze SQLite budowany w tych testach z metadanych modelu.
    """
    zam = SalesOrder(baselinker_order_id=order_id, date_created=date(2026, 9, 18),
                     customer_name='Jan Przykładowy')
    zam.items = [SalesOrderItem(**w) for w in wiersze]
    db.session.add(zam)
    db.session.commit()
    return zam


# --- KRYTYCZNE 1: powtorzony klucz w jednej przysylce ------------------

def test_dwa_wiersze_o_tym_samym_kluczu_sa_juz_niemozliwe(app):
    # ZNALEZISKO KRYTYCZNE (fala 5) i co sie z nim stalo.
    #
    # Ten test odtwarzal dopasowanie "po kolejnosci" wracajace tylnymi
    # drzwiami: przy DWOCH wierszach o tym samym kluczu i DWOCH kopiach tego
    # klucza w przysylce `kandydaci.pop(0)` oddawal pierwszy wiersz pierwszej
    # kopii, drugi — drugiej. Zabezpieczeniem byla regula 6 w `_upsert_pozycje`.
    #
    # Od 23.09.2026 stanu wyjsciowego NIE DA SIE JUZ ZBUDOWAC: dwa wiersze
    # jednego zamowienia o tym samym `bl_order_product_id` odrzuca baza
    # (migracja `2026-09-23-unikalnosc-klucza-pozycji`), a od trzeciej
    # kontroli adwersaryjnej rowniez SQLite w tych testach, bo ograniczenie
    # trafilo wreszcie do modelu. Test mierzy wiec to, co jest prawda:
    # premisa jest strukturalnie wykluczona.
    #
    # Sama regula 6 (powtorzony klucz w PRZYSYLCE) zostaje pokryta przez dwa
    # testy nizej — one nie potrzebuja dubletu w bazie.
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        with pytest.raises(IntegrityError):
            zamowienie_z_wierszami([
                {'bl_order_product_id': 991, 'quantity': 1, 'raw_product_name': DEBOWY,
                 'wood_species': 'dąb', 'finish_state': 'olejowane'},
                {'bl_order_product_id': 991, 'quantity': 1, 'raw_product_name': BUKOWY,
                 'wood_species': 'buk'},
            ])
        db.session.rollback()


def test_powtorzony_klucz_nie_dubluje_wiersza_ani_go_nie_nadpisuje(app):
    # Druga odslona tego samego: w bazie JEDEN wiersz, w przysylce DWIE
    # kopie jego klucza. Pierwsza kopia nadpisywala wiersz, druga zakladala
    # nowy z tym samym kluczem — czyli sama produkowala stan, ktory przy
    # nastepnej synchronizacji dopasowuje sie po kolejnosci.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        pozycja = SalesOrderItem.query.one()
        id_pozycji = pozycja.id
        pozycja.wood_species = 'jesion'            # reczna poprawka w arkuszu
        db.session.commit()

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, quantity=5),
            produkt(991, BUKOWY, quantity=7, price_brutto=300.00),
        ])])
        db.session.expire_all()

        pozycje = SalesOrderItem.query.all()
        assert len(pozycje) == 1
        assert pozycje[0].id == id_pozycji
        assert pozycje[0].wood_species == 'jesion'
        assert pozycje[0].quantity == 1, 'kopia nadpisala wiersz'
        assert stat['pozycje_pominiete'] == 2
        assert stat['podejrzane_paczki_pozycji'] == 1


def test_powtorzony_klucz_nie_kasuje_wiersza_o_innym_kluczu(app):
    # Przysylka z powtorzonym kluczem nie jest spisem inwentarza, wiec nie
    # kasuje NICZEGO — tak samo jak przysylka pusta i przysylka z pozycja
    # bez klucza (regula 5).
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(992, BUKOWY, price_brutto=300.00)])])

        stat = zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY), produkt(991, DEBOWY)])])
        db.session.expire_all()

        assert {p.bl_order_product_id for p in SalesOrderItem.query.all()} == {991, 992}
        assert stat['pozycje_usuniete'] == 0
        assert stat['podejrzane_paczki_pozycji'] == 1


# --- KRYTYCZNE 2: jedna definicja salda --------------------------------

def test_saldo_po_synchronizacji_zgadza_sie_z_przeliczeniem_arkusza(app):
    # ZNALEZISKO KRYTYCZNE (fala 5). Zamowienie z wierszem-dziedzictwem
    # (backfill, bez klucza) ORAZ tym samym produktem przyslanym dzis
    # z kluczem ma DWA wiersze. `ingest` liczyl saldo z PRZYSYLKI, a
    # `arkusz_zapis._przelicz_saldo` z WIERSZY — dwie funkcje, dwa wyniki dla
    # tego samego zamowienia. Praktyczny skutek: pierwsza reczna edycja
    # dowolnego skladnika przesuwala saldo bez zadnego zdarzenia
    # biznesowego pod spodem.
    from modules.reports.arkusz_zapis import _przelicz_saldo

    with app.app_context():
        zamowienie_z_backfillu([
            {'quantity': 1, 'raw_product_name': DEBOWY, 'wood_species': 'dąb',
             'group_type': 'towar', 'value_net': Decimal('800.00')},
        ])

        zapisz_zamowienia([zamowienie()])
        db.session.expire_all()

        zam = SalesOrder.query.one()
        assert len(zam.items) == 2, 'dublet dziedzictwa nie powstal'
        saldo_z_synchronizacji = zam.balance_due

        _przelicz_saldo(zam)
        assert zam.balance_due == saldo_z_synchronizacji, \
            'saldo z ingest i saldo z arkusza to dwie rozne liczby'
        # Wybrana definicja: saldo liczy sie z WIERSZY, ktore zostaly
        # w bazie — czyli z dubletem. Uzasadnienie w `ingest.oblicz_saldo`.
        assert saldo_z_synchronizacji == Decimal('1600.00')


def test_pusta_przysylka_nie_zeruje_salda(app):
    # Ta sama szczelina od drugiej strony: pusta lista `products` nie kasuje
    # wierszy (regula 5), ale saldo liczone z PRZYSYLKI spadalo do zera i
    # zamowienie znikalo z naleznosci, mimo ze wiersze na 800 zl dalej stoja
    # w bazie.
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zapisz_zamowienia([zamowienie(products=[])])
        db.session.expire_all()

        zam = SalesOrder.query.one()
        assert len(zam.items) == 1
        assert zam.balance_due == Decimal('800.00')


# --- WAZNE 3: jedna normalizacja identyfikatora ------------------------

def test_identyfikator_pozycji_normalizuje_sie_jak_numer_zamowienia(app):
    # ZNALEZISKO WAZNE (fala 5). `_numer_bl({'order_id': 991.0})` dawalo 991,
    # a `_identyfikator(991.0)` dawalo None, bo robilo `int(str(x).strip())`,
    # czyli `int('991.0')` -> ValueError. Ta sama wartosc, dwa wyniki:
    # zamowienie zapisywalo sie poprawnie, a jego pozycje traktowane byly
    # jak bezkluczowe i przy KAZDEJ kolejnej synchronizacji pomijane.
    from modules.reports.ingest import _identyfikator, _numer_bl

    assert _identyfikator(991.0) == _numer_bl({'order_id': 991.0}) == 991
    assert _identyfikator('991') == _identyfikator(991) == 991

    with app.app_context():
        pierwszy = zapisz_zamowienia([zamowienie(products=[
            {'order_product_id': 991.0, 'name': DEBOWY,
             'quantity': 1, 'price_brutto': 800.00}])])
        assert SalesOrderItem.query.one().bl_order_product_id == 991
        assert pierwszy['pozycje_nowe'] == 1

        drugi = zapisz_zamowienia([zamowienie(products=[
            {'order_product_id': '991', 'name': DEBOWY,
             'quantity': 2, 'price_brutto': 800.00}])])
        db.session.expire_all()

        assert SalesOrderItem.query.count() == 1
        assert drugi['pozycje_zaktualizowane'] == 1
        assert drugi['pozycje_pominiete'] == 0
        assert SalesOrderItem.query.one().quantity == 2


# --- WAZNE 4: zero to brak identyfikatora ------------------------------

@pytest.mark.parametrize('zero', [0, '0', 0.0])
def test_zerowy_identyfikator_pozycji_znaczy_brak(app, zero):
    # ZNALEZISKO WAZNE (fala 5). `_identyfikator_pozycji('0')` dawalo 0,
    # a warunek sprawdzal `klucz is None` — integracja wstawiajaca 0 zamiast
    # braku dostawala JEDEN wspolny „identyfikator" dla wszystkiego, wiec
    # wszystkie pozycje zamowienia laduja pod tym samym kluczem i mieszaja
    # sie miedzy soba. Ta sama decyzja, co dla numeru zamowienia
    # (`_numer_bl` NIGDY nie zwraca 0).
    with app.app_context():
        pierwszy = zapisz_zamowienia([zamowienie(products=[
            produkt(zero, DEBOWY), produkt(zero, BUKOWY, price_brutto=300.00)])])
        assert pierwszy['pozycje_nowe'] == 2
        assert SalesOrderItem.query.filter_by(bl_order_product_id=0).count() == 0
        assert all(p.bl_order_product_id is None for p in SalesOrderItem.query.all())

        drugi = zapisz_zamowienia([zamowienie(products=[
            produkt(zero, DEBOWY), produkt(zero, BUKOWY, price_brutto=300.00)])])
        db.session.expire_all()

        assert SalesOrderItem.query.count() == 2, 'zerowy klucz mnozy wiersze'
        assert drugi['pozycje_pominiete'] == 2
        assert drugi['podejrzane_paczki_pozycji'] == 1


# --- WAZNE 5: dwie kopie tego samego zamowienia w jednej paczce --------

def test_druga_kopia_zamowienia_w_paczce_jest_pomijana_i_liczona(app):
    # ZNALEZISKO WAZNE (fala 5). Paczka [kopia z pozycjami 991 i 992, kopia
    # tylko z 991] konczyla sie tak, ze wygrywala OSTATNIA: druga kopia
    # nadpisywala pola zamowienia i — jako „pelna przysylka" — KASOWALA
    # wiersz 992 razem z reczna praca. Rozstrzygniecie: paczka z duplikatem
    # zamowienia jest podejrzana, liczy sie PIERWSZA kopia, kazda kolejna
    # jest pomijana, policzona i zgloszona.
    with app.app_context():
        stat = zapisz_zamowienia([
            zamowienie(products=[produkt(991, DEBOWY),
                                 produkt(992, BUKOWY, price_brutto=300.00)]),
            zamowienie(products=[produkt(991, DEBOWY, quantity=5)]),
        ])
        db.session.expire_all()

        assert SalesOrder.query.count() == 1
        assert {p.bl_order_product_id for p in SalesOrderItem.query.all()} == {991, 992}
        assert SalesOrderItem.query.filter_by(bl_order_product_id=991).one().quantity == 1
        assert stat['nowe'] == 1
        assert stat['zaktualizowane'] == 0
        assert stat['pominiete'] == 1
        assert stat['duplikaty_zamowien'] == 1
        assert len(stat['bledy']) == 1
        assert stat['bledy'][0]['order_id'] == 50854536
        assert 'duplikat' in stat['bledy'][0]['blad'].lower()
        assert stat['ostrzezenie'], 'duplikat zamowienia przeszedl po cichu'


def test_duplikat_zamowienia_nie_blokuje_pozostalych_z_paczki(app):
    # Duplikat jest problemem JEDNEGO zamowienia, nie calej paczki.
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id=1), zamowienie(order_id=1),
                                  zamowienie(order_id=2)])
        assert {z.baselinker_order_id for z in SalesOrder.query.all()} == {1, 2}
        assert stat['nowe'] == 2
        assert stat['duplikaty_zamowien'] == 1


def test_duplikat_zamowienia_lapie_sie_takze_przy_innym_zapisie_numeru(app):
    # Dedupikacja wyzej (`fetch_orders_from_date_range`) porownuje SUROWE
    # `order_id`, wiec kopie zapisane jako 991 i '991' ja omijaja. Tutaj
    # numer jest juz znormalizowany (`_numer_bl`), wiec duplikat widac.
    with app.app_context():
        stat = zapisz_zamowienia([zamowienie(order_id=50854536),
                                  zamowienie(order_id='50854536')])
        assert SalesOrder.query.count() == 1
        assert stat['nowe'] == 1
        assert stat['duplikaty_zamowien'] == 1


# --- FALA 6: saldo liczy sie ZE WSZYSTKICH pozycji, razem z usluga ------

# ZMIERZONE 22.09.2026 na `woodpower_crm_local`, cala tabela `sales_orders`
# (3324 zamowienia), wszystkie warianty tego samego wzoru
# „netto pozycji + kurier - wplata":
#
#   zapisane dzis w kolumnie `balance_due` ........ 732 418,20 zl
#   wariant Z USLUGAMI ........................... 732 517,93 zl  (roznica 99,73)
#   wariant BEZ USLUG (definicja sprzed fali 6) ... 649 723,04 zl  (roznica 82 695,16)
#   netto samych uslug ............................ 82 794,89 zl
#
# Per zamowienie: 3319/3324 zgadza sie z wariantem Z USLUGAMI, 3292 z wariantem
# bez uslug — czyli KAZDE z 27 zamowien majacych usluge zgadza sie z „z uslugami".
SALDO_W_BAZIE = Decimal('732418.20')
SALDO_Z_USLUGAMI = Decimal('732517.93')
SALDO_BEZ_USLUG = Decimal('649723.04')
NETTO_USLUG = Decimal('82794.89')

# Ksztalt tabeli: 3324 zamowienia, 27 z pozycja uslugowa (12 mieszanych
# towar+usluga, 15 wylacznie uslugowych).
ZAMOWIEN = 3324
ZAMOWIEN_MIESZANYCH = 12
ZAMOWIEN_TYLKO_USLUGA = 15


def _rozloz(suma: Decimal, ile: int):
    """Dzieli kwote na `ile` czesci co do grosza. Reszta ladu je na ostatniej."""
    from decimal import ROUND_DOWN
    czesc = (suma / ile).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return [czesc] * (ile - 1) + [suma - czesc * (ile - 1)]


def test_saldo_wlicza_pozycje_uslugowa(app):
    # NIEZMIENNIK. Saldo to pieniadze, ktore klient jest nam winien —
    # za suszenie uslugowe tez jest winien. Wykluczanie uslug jest poprawna
    # regula dla METROW SZESCIENNYCH (usluga nie ma objetosci) i tam zostaje
    # bez zmian, ale nie dla pieniedzy.
    with app.app_context():
        zapisz_zamowienia([zamowienie(products=[
            produkt(991, DEBOWY, price_brutto=800.00),
            produkt(992, 'Suszenie usługowe 4m3', price_brutto=200.00),
        ])])
        db.session.expire_all()

        zam = SalesOrder.query.one()
        assert {p.group_type for p in zam.items} == {'towar', 'usługa'}
        # Zamowienie jest oznaczone jako netto, kurier 0, wplata 0.
        assert zam.balance_due == Decimal('1000.00'), \
            'saldo pomija usluge — klient jest nam winien takze za nia'


def test_saldo_zgadza_sie_z_pomiarem_z_bazy_a_nie_z_wariantem_bez_uslug():
    # TEST POROWNAWCZY oparty na pomiarze wyzej. Zestaw odtwarza ksztalt
    # tabeli `sales_orders`: 3324 zamowienia, 27 z usluga (12 mieszanych,
    # 15 tylko uslugowych), netto towarow i netto uslug rowne zmierzonym.
    #
    # Kurier i wplata wchodza do OBU definicji identycznie, wiec ich nie
    # modelujemy — roznica miedzy wariantami to DOKLADNIE netto uslug.
    from modules.reports.ingest import oblicz_saldo

    uslugi = _rozloz(NETTO_USLUG, ZAMOWIEN_MIESZANYCH + ZAMOWIEN_TYLKO_USLUGA)
    tylko_towar = ZAMOWIEN - ZAMOWIEN_MIESZANYCH - ZAMOWIEN_TYLKO_USLUGA
    towary = _rozloz(SALDO_BEZ_USLUG, ZAMOWIEN_MIESZANYCH + tylko_towar)

    zamowienia = []
    for i in range(ZAMOWIEN_MIESZANYCH):
        zamowienia.append([('towar', towary[i]), ('usługa', uslugi[i])])
    for i in range(ZAMOWIEN_TYLKO_USLUGA):
        zamowienia.append([('usługa', uslugi[ZAMOWIEN_MIESZANYCH + i])])
    for i in range(tylko_towar):
        zamowienia.append([('towar', towary[ZAMOWIEN_MIESZANYCH + i])])
    assert len(zamowienia) == ZAMOWIEN

    policzone = sum(oblicz_saldo([w for _, w in pary], 0, 'netto', 0)
                    for pary in zamowienia)
    bez_uslug = sum(oblicz_saldo([w for g, w in pary if g != 'usługa'],
                                 0, 'netto', 0)
                    for pary in zamowienia)

    assert bez_uslug == SALDO_BEZ_USLUG, 'zestaw nie odtwarza pomiaru'
    assert policzone == SALDO_Z_USLUGAMI, \
        'saldo liczy sie inaczej, niz policzone sa dane lezace w bazie'
    # Wariant z uslugami odtwarza stan bazy z dokladnoscia do zaokraglen
    # (99,73 zl na 732 tysiacach = 0,014%), wariant bez uslug rozjezdza sie
    # o cale netto uslug.
    assert abs(policzone - SALDO_W_BAZIE) == Decimal('99.73')
    assert abs(bez_uslug - SALDO_W_BAZIE) == Decimal('82695.16')
    assert policzone - bez_uslug == NETTO_USLUG


def test_przeliczenie_po_upsercie_takze_wlicza_usluge(app):
    # Drugi wolajacy `oblicz_saldo`: `_upsert_zamowienia` przelicza saldo
    # Z WIERSZY po zapisie pozycji (`saldo_z_wierszy`). Ma dac te sama liczbe,
    # co mapper — inaczej saldo skakaloby przy kazdej synchronizacji.
    from modules.reports.ingest import mapuj_zamowienie, saldo_z_wierszy

    surowe = zamowienie(delivery_price=123.00, payment_done=300.00, products=[
        produkt(991, DEBOWY, price_brutto=800.00),
        produkt(992, 'Suszenie usługowe 4m3', price_brutto=200.00),
    ])
    with app.app_context():
        zapisz_zamowienia([surowe])
        db.session.expire_all()
        zam = SalesOrder.query.one()
        # 800 + 200 netto + 123 kuriera (zamowienie netto) - 300 wplaty.
        assert zam.balance_due == Decimal('823.00')
        assert saldo_z_wierszy(zam) == mapuj_zamowienie(surowe)['balance_due']
