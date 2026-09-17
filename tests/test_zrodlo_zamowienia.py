# -*- coding: utf-8 -*-
"""
Testy źródła zamówienia (kanału sprzedaży) w module produkcji.

Źródło steruje tym, jaki kod rabatowy trafi do paczki na pakowaniu, więc
najgroźniejsze są tu dwie pomyłki: potraktowanie `order_source_id = 0`
(„Detal") jak braku danych oraz mylenie źródeł o tym samym identyfikatorze
w różnych kanałach (0 to zarówno „Detal" w `personal`, jak i „Zwrot do
zamówienia" w `order_return`).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.models import ProductionOrder
from modules.production.services.sync_service import BaselinkerSyncService
# Konstruktor modelu odpala configure_mappers() dla CAŁEGO rejestru, więc bez
# tych importów wywraca się na relationship('User') / ('Multiplier') / ('Client').
# Ten sam zestaw co w tests/test_archive_tab.py.
from modules.users.models import User  # noqa: F401
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401


# Słownik w kształcie, jaki zwraca getOrderSources (po normalizacji kluczy na int).
SLOWNIK_ZRODEL = {
    'personal': {
        0: 'Detal',
        63189: 'Czernecki',
        68971: 'Stały B2B',
        85727: 'Dębuś VPS',
    },
    'shop': {5029946: 'Presta VPS'},
    'allegro': {8881: 'woodpower'},
    'olx': {12428: 'OLX'},
    'order_return': {0: 'Zwrot do zamówienia'},
}


def _serwis_z_slownikiem(slownik=None):
    """Serwis bez __init__ (nie potrzebuje configu Flaska), z gotowym cache źródeł."""
    svc = BaselinkerSyncService.__new__(BaselinkerSyncService)
    svc._order_sources_cache = SLOWNIK_ZRODEL if slownik is None else slownik
    svc._order_sources_cache_time = datetime.now()
    svc._order_sources_cache_ttl = 43200
    return svc


def _zamowienie(**kwargs):
    return ProductionOrder(**kwargs)


# ---------------------------------------------------------------------------
# Etykieta dla człowieka (ProductionOrder.order_source_display)
# ---------------------------------------------------------------------------

def test_allegro_pokazuje_nazwe_kanalu_a_nie_loginu_konta():
    # „woodpower" to login konta sprzedażowego — pakowaczowi nie mówi nic
    # ponad samo „Allegro".
    order = _zamowienie(order_source='allegro', order_source_id=8881,
                        order_source_name='woodpower')
    assert order.order_source_display == 'Allegro'


def test_sklep_pokazuje_kanal():
    order = _zamowienie(order_source='shop', order_source_id=5029946,
                        order_source_name='Presta VPS')
    assert order.order_source_display == 'Sklep'


def test_zrodla_wlasne_pokazuja_nazwe_bo_rozrozniaja_detal_od_b2b():
    detal = _zamowienie(order_source='personal', order_source_id=0,
                        order_source_name='Detal')
    b2b = _zamowienie(order_source='personal', order_source_id=68971,
                      order_source_name='Stały B2B')
    assert detal.order_source_display == 'Detal'
    assert b2b.order_source_display == 'Stały B2B'


def test_brak_zrodla_daje_none():
    assert _zamowienie().order_source_display is None
    assert _zamowienie(order_source='').order_source_display is None


def test_wlasne_bez_nazwy_spada_do_etykiety_kanalu():
    order = _zamowienie(order_source='personal', order_source_id=99999)
    assert order.order_source_display == 'Własne'


def test_nieznany_kanal_pokazuje_nazwe_ze_slownika():
    # BaseLinker może dołożyć kanał, którego nie ma w naszej mapie — wtedy
    # lepsza jest nazwa źródła niż surowy klucz.
    order = _zamowienie(order_source='empik', order_source_id=123,
                        order_source_name='Empik Marketplace')
    assert order.order_source_display == 'Empik Marketplace'


def test_nieznany_kanal_bez_nazwy_pokazuje_klucz():
    order = _zamowienie(order_source='empik', order_source_id=123)
    assert order.order_source_display == 'empik'


# ---------------------------------------------------------------------------
# Wyciąganie z zamówienia BaseLinkera (extract_order_source)
# ---------------------------------------------------------------------------

def test_wyciaga_pare_i_nazwe_ze_slownika():
    svc = _serwis_z_slownikiem()
    dane = svc.extract_order_source({
        'order_id': 25208907, 'order_source': 'allegro', 'order_source_id': 8881,
    })
    assert dane == {
        'order_source': 'allegro',
        'order_source_id': 8881,
        'order_source_name': 'woodpower',
    }


def test_id_zero_to_detal_a_nie_brak_danych():
    # 0 jest falsy — najłatwiejsza pomyłka w tym kodzie.
    svc = _serwis_z_slownikiem()
    dane = svc.extract_order_source({
        'order_id': 1, 'order_source': 'personal', 'order_source_id': 0,
    })
    assert dane['order_source_id'] == 0
    assert dane['order_source_name'] == 'Detal'


def test_to_samo_id_w_innym_kanale_daje_inne_zrodlo():
    # personal/0 = Detal, order_return/0 = Zwrot. Klucz to PARA, nie samo id.
    svc = _serwis_z_slownikiem()
    detal = svc.extract_order_source({'order_source': 'personal', 'order_source_id': 0})
    zwrot = svc.extract_order_source({'order_source': 'order_return', 'order_source_id': 0})
    assert detal['order_source_name'] == 'Detal'
    assert zwrot['order_source_name'] == 'Zwrot do zamówienia'


def test_identyfikator_jako_tekst_jest_normalizowany():
    # BaseLinker potrafi oddać identyfikator jako string.
    svc = _serwis_z_slownikiem()
    dane = svc.extract_order_source({'order_source': 'shop', 'order_source_id': '5029946'})
    assert dane['order_source_id'] == 5029946
    assert dane['order_source_name'] == 'Presta VPS'


def test_brak_kanalu_daje_pusty_wynik():
    # Pusty dict, a nie klucze z None: upsert zamówienia pomija klucze o wartości
    # None, ale pusty wynik jest jednoznaczny i nie wchodzi do product_data.
    svc = _serwis_z_slownikiem()
    assert svc.extract_order_source({'order_id': 1}) == {}
    assert svc.extract_order_source({'order_source': '   '}) == {}


def test_zrodlo_spoza_slownika_zapisuje_pare_bez_nazwy():
    # Awaria pobrania słownika albo świeże źródło nie mogą zgubić samego kanału.
    svc = _serwis_z_slownikiem({})
    dane = svc.extract_order_source({'order_source': 'allegro', 'order_source_id': 8881})
    assert dane['order_source'] == 'allegro'
    assert dane['order_source_id'] == 8881
    assert dane['order_source_name'] is None


def test_nazwa_i_kanal_przycinane_do_dlugosci_kolumn():
    svc = _serwis_z_slownikiem({'x' * 60: {1: 'y' * 150}})
    dane = svc.extract_order_source({'order_source': 'x' * 60, 'order_source_id': 1})
    assert len(dane['order_source']) == 50
    assert len(dane['order_source_name']) == 100


def test_awaria_api_nie_jest_odpytywana_raz_na_zamowienie():
    """
    Partia synchronizacji to setki zamówień, a każde pyta o słownik źródeł.
    Bez pamięci nieudanego pobrania awaria BaseLinkera dawałaby setki timeoutów
    zamiast jednego — i zamiast opóźnienia robiłaby z synchronizacji zawis.
    """
    svc = BaselinkerSyncService.__new__(BaselinkerSyncService)
    svc.api_key = 'token-testowy'
    svc._order_sources_cache = None
    svc._order_sources_cache_time = None
    svc._order_sources_cache_ttl = 43200
    svc._order_sources_blad_time = None
    svc._order_sources_blad_ttl = 300

    wywolania = []

    def _padnij(request_data):
        wywolania.append(request_data)
        raise RuntimeError('BaseLinker niedostępny')

    svc._make_api_request = _padnij

    for _ in range(5):
        assert svc.get_order_sources() == {}

    assert len(wywolania) == 1, f'API odpytane {len(wywolania)} razy zamiast raz'


# ---------------------------------------------------------------------------
# Strażnik ścieżki zapisu
# ---------------------------------------------------------------------------

def test_pola_zrodla_sa_na_liscie_pol_zamowienia():
    """
    Upsert zamówienia w `_create_production_product_from_data` przepisuje TYLKO
    klucze z ORDER_LEVEL_KEYS. Pole spoza tej listy trafiłoby do konstruktora
    ProductionProduct i wywróciłoby synchronizację, więc pominięcie jej przy
    dodawaniu kolumny jest cichym błędem, którego nie widać w żadnym innym teście.
    """
    import inspect
    zrodlo = inspect.getsource(
        BaselinkerSyncService._create_production_product_from_data
    )
    for pole in ('order_source', 'order_source_id', 'order_source_name'):
        assert f"'{pole}'" in zrodlo, f"{pole} nie jest w ORDER_LEVEL_KEYS"


# ---------------------------------------------------------------------------
# Serializery — źródło musi dojść do panelu, modala i tabletu
# ---------------------------------------------------------------------------

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
)

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/test_archive_tab.py
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

# serialize_order() (API mobilne) dolicza otwarte poprawki i zdarzenia stanowisk,
# więc same prod_orders/prod_products nie wystarczą.
_TABELE = [m.__table__ for m in (
    User, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker,
)]


@pytest.fixture()
def apka():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


def _produkt_z_zrodlem(**zrodlo):
    cfg = ProductionConfiguration(species='dąb', technology='lity', wood_class='A/B')
    db.session.add(cfg)
    order = ProductionOrder(
        baselinker_order_id=25208907, internal_order_number='WP-26-00001', **zrodlo)
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, configuration_id=cfg.id, short_product_id='2600001_1',
        original_product_name='Blat dębowy 120x80x4', current_status='czeka_na_wyciecie',
        quantity=1, product_sequence_in_order=1)
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_zrodlo_dochodzi_do_wszystkich_trzech_serializerow(apka):
    """
    Panel (lista), modal szczegółów i API mobilne mają własne serializery.
    Pominięcie któregokolwiek znaczy, że pakowacz przy tablecie albo przy
    komputerze nie zobaczy kanału — a to jest cały sens tej zmiany.
    """
    from modules.production.routers.api.products_api import (
        _serialize_product, _serialize_production_item,
    )
    from modules.production.services.mobile_api_service import serialize_order

    produkt = _produkt_z_zrodlem(
        order_source='allegro', order_source_id=8881, order_source_name='woodpower')

    lista = _serialize_product(produkt, {}, {})
    modal = _serialize_production_item(produkt)
    tablet = serialize_order(produkt)

    for nazwa, dane in (('lista', lista), ('modal', modal), ('tablet', tablet)):
        assert dane['order_source_display'] == 'Allegro', f'brak etykiety w: {nazwa}'
        assert dane['order_source'] == 'allegro', f'brak kanału w: {nazwa}'
        assert dane['order_source_id'] == 8881, f'brak id w: {nazwa}'
        assert dane['order_source_name'] == 'woodpower', f'brak nazwy w: {nazwa}'


def test_zamowienie_bez_zrodla_nie_wywraca_serializerow(apka):
    """Zamówienia ręczne i te spoza okna BaseLinkera mają puste źródło."""
    from modules.production.routers.api.products_api import (
        _serialize_product, _serialize_production_item,
    )
    from modules.production.services.mobile_api_service import serialize_order

    produkt = _produkt_z_zrodlem()

    for dane in (_serialize_product(produkt, {}, {}),
                 _serialize_production_item(produkt),
                 serialize_order(produkt)):
        assert dane['order_source_display'] is None
        assert dane['order_source'] is None
