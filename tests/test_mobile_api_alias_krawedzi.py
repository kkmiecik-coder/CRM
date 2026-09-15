# -*- coding: utf-8 -*-
"""
Okres przejściowy 'finishing' -> 'edges' w API mobilnym.

Stanowisko Wykańczanie zmieniło nazwę na Krawędzie (kod 'edges'), a Lakiernia
('painting') awansowała z zakładki tabletu na pełnoprawne stanowisko. Tablety
z kodem 'finishing' chodzą jeszcze na starym APK, więc backend musi rozwijać
ten kod na 'edges' NA WEJŚCIU — inaczej stary tablet dostaje 404
unknown_station (kod zniknął z katalogu) albo 403 station_mismatch. Ten drugi
przypadek jest groźniejszy: @with_idempotency zapamiętuje na 7 dni każdy
status poniżej 500 spoza BLEDY_DO_PONOWIENIA, więc odbite sztuki z kolejki
offline przepadają, a tablet melduje udaną synchronizację.

Ten plik znika razem z aliasem — patrz krok 20 planu wdrożenia.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct,
    ProductionReworkLog, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import (
    STATION_COMPLETED_AT_FIELD,
    STATION_QUANTITY_FIELD,
    generate_token,
)
from modules.users.models import User
# Importy rejestrujące mappery — configure_mappers() przy pierwszym query
# potrzebuje ich do rozwiązania relationshipów z modules/users/models.py.
# Wzorzec i uzasadnienie jak w tests/test_mobile_complete_bl_sync_queue.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]

# SQLite nie zna LONGTEXT — to samo obejście co w pozostałych testach mobilnych.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64,
        'jwt_expiry_days': 365,
        'ip_whitelist': [],
        'min_supported_app_version': '0.0.0',
    }
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def czysty_cache_configu():
    """ProductionConfigService trzyma konfigurację w singletonie z cache'em."""
    from modules.production.services.config_service import invalidate_config_cache
    invalidate_config_cache()
    yield
    invalidate_config_cache()


def _token(app, station_code='finishing', device_id='TABLET-1'):
    """Rejestruje urządzenie wprost w bazie i zwraca JWT."""
    with app.app_context():
        device = ProductionDevice(device_id=device_id, device_name='Tablet',
                                  station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _naglowki(token, operation_id=None):
    naglowki = {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'}
    if operation_id:
        naglowki['X-Operation-Id'] = operation_id
    return naglowki


def _produkt(app, status='czeka_na_krawedzie', quantity=2,
             finish_type='surowe', obrobka_krawedzi=True,
             baselinker_order_id=990001, internal_order_number='26/00042'):
    """
    Zamówienie z jedną pozycją. Zwraca id produktu.

    Adres dostawy jest OBOWIĄZKOWY, nie ozdobny. ProductionOrder
    .is_personal_pickup (models.py:172-185) zwraca True, gdy zamówienie nie ma
    ANI adresu, ANI miasta, ANI kodu pocztowego — a complete_task (models.py:518)
    zamienia wtedy 'czeka_na_logistyke' na 'czeka_na_pakowanie'. Bez tych pól
    test trasy sprawdzałby odbiór osobisty zamiast routingu stanowisk.
    """
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=baselinker_order_id,
            internal_order_number=internal_order_number,
            delivery_method='Kurier DPD',
            delivery_address='ul. Testowa 1',
            delivery_city='Warszawa',
            delivery_postcode='00-001',
        )
        db.session.add(order)
        db.session.flush()
        produkt = ProductionProduct(
            order_id=order.id, short_product_id='26042_1',
            product_sequence_in_order=1, original_product_name='Blat dębowy',
            quantity=quantity, current_status=status,
            parsed_finish_type=finish_type,
            parsed_edge_processing=obrobka_krawedzi,
        )
        db.session.add(produkt)
        db.session.commit()
        return produkt.id


def _urzadzenie_stub(station_code):
    """Lekki stub ProductionDevice do funkcji czystych (bez bazy)."""
    return SimpleNamespace(station_code=station_code)


# ============================================================================
# MAPY KOLUMN STANOWISKA
# ============================================================================

def test_mapa_licznika_zna_krawedzie_zamiast_wykanczania():
    """
    Klucz 'edges' to STANOWISKO Krawędzie, nie dane krawędziowe produktu
    (parsed_edges_groups) — te dwa znaczenia stoją w module obok siebie.
    """
    assert STATION_QUANTITY_FIELD['edges'] == 'quantity_done_edges'


def test_mapa_znacznika_czasu_zna_krawedzie_zamiast_wykanczania():
    assert STATION_COMPLETED_AT_FIELD['edges'] == 'edges_completed_at'


def test_zadna_mapa_kolumn_nie_trzyma_juz_kodu_finishing():
    """
    Obie mapy są BRAMKAMI CZŁONKOSTWA (mobile_api_service.py:1115, :1151),
    a nazwy kolumn model składa f-stringiem z kodu stanowiska. Wpis
    'finishing' niczego by nie przekierował — przepuściłby martwy kod do
    setattr(self, 'quantity_done_finishing', ...), czyli na atrybut-widmo.
    Alias ma być rozwinięty wyżej, w routerze.
    """
    assert 'finishing' not in STATION_QUANTITY_FIELD
    assert 'finishing' not in STATION_COMPLETED_AT_FIELD


def test_obie_mapy_wskazuja_na_istniejace_kolumny_modelu():
    """Literówka w nazwie kolumny daje cicho quantity_done: null, nie błąd."""
    for kod, kolumna in STATION_QUANTITY_FIELD.items():
        assert hasattr(ProductionProduct, kolumna), \
            'brak kolumny {} dla stanowiska {}'.format(kolumna, kod)
    for kod, kolumna in STATION_COMPLETED_AT_FIELD.items():
        assert hasattr(ProductionProduct, kolumna), \
            'brak kolumny {} dla stanowiska {}'.format(kolumna, kod)


# ============================================================================
# KONTROLA DOSTĘPU URZĄDZENIA (funkcja czysta, bez bazy)
# ============================================================================

def test_stary_tablet_finishing_siega_po_krawedzie():
    """
    Wiersz 'finishing' w prod_devices zostaje po urządzeniu pominiętym przez
    migrację albo przywróconym z backupu. Bez normalizacji strony urządzenia
    device='finishing' vs żądanie 'edges' daje 403 station_mismatch — jedyny
    status, po którym praca z kolejki offline przepada bezpowrotnie.
    """
    from modules.production.services.mobile_api_service import device_can_access_station
    assert device_can_access_station(_urzadzenie_stub('finishing'), 'edges') is True


def test_stary_tablet_finishing_siega_po_lakiernie():
    """STRAŻNIK: to działa już dziś, przez grupę {'finishing','painting'}."""
    from modules.production.services.mobile_api_service import device_can_access_station
    assert device_can_access_station(_urzadzenie_stub('finishing'), 'painting') is True


def test_nowy_tablet_krawedzi_siega_po_lakiernie():
    from modules.production.services.mobile_api_service import device_can_access_station
    assert device_can_access_station(_urzadzenie_stub('edges'), 'painting') is True


def test_nowy_tablet_lakierni_siega_po_krawedzie():
    from modules.production.services.mobile_api_service import device_can_access_station
    assert device_can_access_station(_urzadzenie_stub('painting'), 'edges') is True


def test_tablet_formatowania_nie_siega_po_krawedzie():
    """STRAŻNIK: alias nie może rozluźnić dostępu dla stanowisk spoza grupy."""
    from modules.production.services.mobile_api_service import device_can_access_station
    assert device_can_access_station(_urzadzenie_stub('formatting'), 'edges') is False


def test_grupa_stanowisk_opisuje_krawedzie_i_lakiernie():
    from modules.production.services.mobile_api_service import STATION_GROUPS
    assert STATION_GROUPS == [{'edges', 'painting'}]


# ============================================================================
# TELEMETRIA TABLETÓW
# ============================================================================

def test_telemetria_obejmuje_krawedzie_i_lakiernie():
    """
    Kod spoza tej krotki jest przez build_devices_telemetry odfiltrowywany
    PO CICHU (mobile_api_service.py:271). Brak 'painting' = kafel Lakierni
    na zawsze „Niedostępne", co na dashboardzie wygląda jak awaria sprzętu.
    """
    from modules.production.services.mobile_api_service import (
        _STATION_CODES_WITH_TABLETS,
    )
    assert 'edges' in _STATION_CODES_WITH_TABLETS
    assert 'painting' in _STATION_CODES_WITH_TABLETS
    assert 'finishing' not in _STATION_CODES_WITH_TABLETS
    assert 'sawmill' in _STATION_CODES_WITH_TABLETS


def test_tablet_lakierni_nie_jest_odfiltrowany_z_telemetrii():
    from modules.production.services.mobile_api_service import (
        build_devices_telemetry,
    )
    teraz = datetime(2026, 9, 15, 12, 0, 0)
    tablet = SimpleNamespace(
        station_code='painting',
        is_active=True,
        last_heartbeat_at=teraz - timedelta(minutes=2),
        last_seen_at=None,
        last_battery_pct=88,
        last_battery_charging=False,
        last_temperature_c=31.0,
        last_app_version_code=42,
        app_version='1.4.0',
        last_ip='10.0.0.7',
    )
    wynik = build_devices_telemetry([tablet], now=teraz)
    assert wynik['painting']['active'] is True
    assert wynik['painting']['status_label'] == 'Aktywne'
    assert wynik['painting']['battery_pct'] == 88


def test_tablet_krawedzi_z_niezmigrowanym_kodem_nie_ma_telemetrii():
    """
    Świadome ograniczenie: telemetria czyta station_code SUROWO, bez aliasu.
    Urządzenie, którego migracja nie ruszyła, pokaże się jako „Niedostępne" —
    i o to chodzi, bo to sygnał niedokończonej migracji prod_devices, a nie
    stan do zamaskowania. Punkt 14e weryfikacji po deployu tego pilnuje.
    """
    from modules.production.services.mobile_api_service import (
        build_devices_telemetry,
    )
    teraz = datetime(2026, 9, 15, 12, 0, 0)
    stary = SimpleNamespace(
        station_code='finishing',
        is_active=True,
        last_heartbeat_at=teraz - timedelta(minutes=1),
        last_seen_at=None,
        last_battery_pct=90,
        last_battery_charging=False,
        last_temperature_c=30.0,
        last_app_version_code=41,
        app_version='1.3.0',
        last_ip='10.0.0.6',
    )
    wynik = build_devices_telemetry([stary], now=teraz)
    assert 'finishing' not in wynik
    assert wynik['edges']['active'] is False
