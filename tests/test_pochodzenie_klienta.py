# -*- coding: utf-8 -*-
"""„Pochodzenie klienta" (`sales_orders.client_origin`) — partia E, punkt E6.

Do 23.09.2026 zapis proponował pochodzenie TYLKO przy pierwszym zapisie
i TYLKO gdy zamówienie było już w module produkcji. 14 z 14 nowych zamówień
z 23.09 zostało przez to bez pochodzenia, a wszystkie 3324 zamówienia
z backfillu mają je puste — karta „Klienci według: Pochodzenie klienta"
i rozbicie kanału ręcznego pokazywały same „(brak)".

Reguła po zmianie:
  * wypełniamy wyłącznie PUSTE pole, przy KAŻDYM zapisie;
  * źródło: słownik BaseLinkera `getOrderSources` po PARZE (kanał, id),
    a gdy słownika brak albo para jest nieznana — nazwa z produkcji;
  * wartości niepustej (ręcznej) nie ruszamy nigdy;
  * awaria słownika nie wywraca zapisu.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import ingest
from modules.reports.ingest import zapisz_zamowienia
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
from uzupelnij_pochodzenie_klienta import uzupelnij_pochodzenie  # noqa: E402

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/krawedzie_fixtures.py
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_TABLES = [m.__table__ for m in
           (SalesClient, SalesOrder, SalesOrderItem, Client, ProductionOrder)]

TS_18_09 = 1789714800

# Kształt dokładnie taki, jaki oddaje `BaselinkerSyncService.get_order_sources`:
# kanał -> {id (int) -> nazwa}. Id 0 jest w DWÓCH kanałach i znaczy co innego.
SLOWNIK = {
    'personal': {0: 'Detal', 68971: 'Stały B2B', 68974: 'PH Stały B2B'},
    'order_return': {0: 'Zwrot do zamówienia'},
    'shop': {5029946: 'Presta VPS'},
    'allegro': {8881: 'woodpower'},
}


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


@pytest.fixture()
def slownik(monkeypatch):
    """Podmienia jedyne miejsce, które rozmawia z BaseLinkerem. Liczy wywołania,
    bo słownik ma się pobrać najwyżej RAZ na paczkę."""
    stan = {'slownik': SLOWNIK, 'wywolania': 0}

    def pobierz():
        stan['wywolania'] += 1
        if isinstance(stan['slownik'], Exception):
            raise stan['slownik']
        return stan['slownik']

    monkeypatch.setattr(ingest, 'slownik_zrodel_baselinkera', pobierz)
    return stan


def zamowienie(order_id=50854536, **nadpisania):
    baza = {
        'order_id': order_id, 'date_add': TS_18_09, 'date_confirmed': TS_18_09,
        'order_status_id': 138619, 'delivery_fullname': 'Jan Przykładowy',
        'email': f'klient{order_id}@example.com', 'phone': '',
        'delivery_postcode': '40-100', 'delivery_state': 'śląskie',
        'delivery_price': 0.0, 'payment_done': 0.0,
        'order_source': 'personal', 'order_source_id': 68971,
        'custom_extra_fields': {'105623': 'Łukasz Próbny', '106169': 'netto'},
        'products': [{'order_product_id': 991, 'quantity': 1, 'price_brutto': 800.00,
                      'name': 'Blat dębowy lity A/B 100x50x2 cm'}],
    }
    baza.update(nadpisania)
    return baza


def prod_zamowienie(bl_id, nazwa_zrodla, zrodlo='personal'):
    db.session.add(ProductionOrder(baselinker_order_id=bl_id,
                                   internal_order_number='26_00001',
                                   order_source=zrodlo, order_source_name=nazwa_zrodla))
    db.session.commit()


def pochodzenie(bl_id=50854536):
    db.session.expire_all()
    return SalesOrder.query.filter_by(baselinker_order_id=bl_id).one().client_origin


# ===== zapis bieżący (ingest.py) ========================================

def test_puste_pochodzenie_wypelnia_sie_ze_slownika(app, slownik):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'Stały B2B'


def test_slownik_czyta_pare_kanal_i_id_a_nie_samo_id(app, slownik):
    """Id 0 to „Detal" w `personal` i „Zwrot do zamówienia" w `order_return`."""
    with app.app_context():
        zapisz_zamowienia([
            zamowienie(order_id=1, order_source='personal', order_source_id=0),
            zamowienie(order_id=2, order_source='order_return', order_source_id=0),
        ])
        assert pochodzenie(1) == 'Detal'
        assert pochodzenie(2) == 'Zwrot do zamówienia'


def test_identyfikator_zrodla_zapisuje_sie_dla_nowego_zamowienia(app, slownik):
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_source='shop', order_source_id='5029946')])
        zam = SalesOrder.query.one()
        assert (zam.order_source, zam.order_source_id) == ('shop', 5029946)
        assert zam.client_origin == 'Presta VPS'


def test_reczna_wartosc_nie_jest_ruszana_przy_kolejnym_zapisie(app, slownik):
    with app.app_context():
        zapisz_zamowienia([zamowienie()])
        zam = SalesOrder.query.one()
        zam.client_origin = 'Szablonowy'      # poprawka w Arkuszu
        db.session.commit()
        zapisz_zamowienia([zamowienie(order_status_id=138620)])
        assert pochodzenie() == 'Szablonowy'


def test_puste_pochodzenie_wypelnia_sie_takze_przy_kolejnym_zapisie(app, slownik):
    """Do partii E pochodzenie proponowane było tylko przy PIERWSZYM zapisie —
    zamówienie, któremu wtedy się nie udało, zostawało puste na zawsze."""
    with app.app_context():
        slownik['slownik'] = RuntimeError('BaseLinker nie odpowiada')
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() is None

        slownik['slownik'] = SLOWNIK
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'Stały B2B'


def test_pusty_napis_to_tez_puste_pochodzenie(app, slownik):
    with app.app_context():
        db.session.add(SalesOrder(baselinker_order_id=50854536,
                                  date_created=date(2026, 9, 18), client_origin=''))
        db.session.commit()
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'Stały B2B'


def test_awaria_slownika_nie_wywraca_zapisu_i_zostawia_pole_puste(app, slownik):
    with app.app_context():
        slownik['slownik'] = RuntimeError('BaseLinker nie odpowiada')
        stat = zapisz_zamowienia([zamowienie()])
        assert stat['nowe'] == 1
        assert stat['bledy'] == []
        assert pochodzenie() is None


def test_nieznana_para_bierze_nazwe_z_produkcji(app, slownik):
    with app.app_context():
        prod_zamowienie(50854536, 'Dębuś VPS')
        zapisz_zamowienia([zamowienie(order_source_id=85727)])   # nie ma w słowniku
        assert pochodzenie() == 'Dębuś VPS'


def test_awaria_slownika_bierze_nazwe_z_produkcji(app, slownik):
    with app.app_context():
        slownik['slownik'] = RuntimeError('BaseLinker nie odpowiada')
        prod_zamowienie(50854536, 'Nowy B2B')
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'Nowy B2B'


def test_slownik_wygrywa_z_produkcja(app, slownik):
    """Kolejność z decyzji: najpierw słownik po parze przychodzącego zamówienia,
    produkcja dopiero wtedy, gdy słownik nie zna pary."""
    with app.app_context():
        prod_zamowienie(50854536, 'Nazwa sprzed zmiany w BL')
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'Stały B2B'


def test_slownik_pobiera_sie_najwyzej_raz_na_paczke(app, slownik):
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_id=n) for n in (1, 2, 3)])
        assert slownik['wywolania'] == 1


def test_slownik_nie_jest_pobierany_gdy_nikt_go_nie_potrzebuje(app, slownik):
    """Zamówienie bez identyfikatora źródła albo z wypełnionym pochodzeniem
    nie ma po co pytać BaseLinkera."""
    with app.app_context():
        zapisz_zamowienia([zamowienie(order_source_id=None)])
        assert slownik['wywolania'] == 0


def test_dluga_nazwa_ze_slownika_jest_przycinana_do_kolumny(app, slownik):
    with app.app_context():
        slownik['slownik'] = {'personal': {68971: 'x' * 80}}
        zapisz_zamowienia([zamowienie()])
        assert pochodzenie() == 'x' * 50


# ===== skrypt zaległości: scripts/uzupelnij_pochodzenie_klienta.py ========

def _zamowienie_w_bazie(bl_id, kanal=None, id_zrodla=None, pochodzenie_=None):
    db.session.add(SalesOrder(baselinker_order_id=bl_id, date_created=date(2026, 9, 1),
                              order_source=kanal, order_source_id=id_zrodla,
                              client_origin=pochodzenie_))


def _zaleglosci():
    """Pięć zamówień: (a) produkcja, (b) słownik, ręczne, nieustalalne x2."""
    prod_zamowienie(1, 'Stały B2B')
    prod_zamowienie(3, 'Nadpisałoby ręczne')
    _zamowienie_w_bazie(1, 'personal')                        # (a)
    _zamowienie_w_bazie(2, 'shop', 5029946)                   # (b)
    _zamowienie_w_bazie(3, 'personal', 68971, 'Szablonowy')    # ręczne — nie ruszać
    _zamowienie_w_bazie(4, 'allegro')                         # brak danych
    _zamowienie_w_bazie(5, 'personal', 99999)                 # para nieznana
    db.session.commit()


def _pochodzenia():
    db.session.expire_all()
    return {z.baselinker_order_id: z.client_origin for z in SalesOrder.query.all()}


def test_skrypt_na_sucho_nic_nie_zapisuje_i_liczy(app):
    with app.app_context():
        _zaleglosci()
        przed = _pochodzenia()

        raport = uzupelnij_pochodzenie(lambda: SLOWNIK, zapisz=False)

        assert _pochodzenia() == przed
        assert raport['pustych'] == 4
        assert raport['z_produkcji'] == 1
        assert raport['ze_slownika'] == 1
        assert raport['zostaje_pustych'] == 2
        assert raport['pozostale_wg_kanalu'] == {'allegro': 1, 'personal': 1}


def test_skrypt_apply_wypelnia_tylko_puste(app):
    with app.app_context():
        _zaleglosci()

        uzupelnij_pochodzenie(lambda: SLOWNIK, zapisz=True)

        assert _pochodzenia() == {1: 'Stały B2B', 2: 'Presta VPS', 3: 'Szablonowy',
                                  4: None, 5: None}


def test_skrypt_bez_slownika_wypelnia_z_produkcji_i_nie_pada(app):
    with app.app_context():
        _zaleglosci()

        def awaria():
            raise RuntimeError('BaseLinker nie odpowiada')

        raport = uzupelnij_pochodzenie(awaria, zapisz=True)

        assert raport['slownik_dostepny'] is False
        assert raport['z_produkcji'] == 1
        assert raport['ze_slownika'] == 0
        assert _pochodzenia()[1] == 'Stały B2B'


def test_skrypt_nie_pyta_baselinkera_gdy_nie_ma_o_co(app):
    with app.app_context():
        _zamowienie_w_bazie(4, 'allegro')
        db.session.commit()
        wywolania = []
        uzupelnij_pochodzenie(lambda: wywolania.append(1) or SLOWNIK, zapisz=False)
        assert wywolania == []


def test_skrypt_jest_idempotentny(app):
    with app.app_context():
        _zaleglosci()
        uzupelnij_pochodzenie(lambda: SLOWNIK, zapisz=True)
        raport = uzupelnij_pochodzenie(lambda: SLOWNIK, zapisz=True)
        assert raport['z_produkcji'] == 0 and raport['ze_slownika'] == 0
        assert raport['pustych'] == 2
