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


# ============================================================================
# BRAMKA _resolve_station_code — CZTERY ENDPOINTY MUTUJĄCE
# ============================================================================
#
# Tylko te cztery mogą zapisać kod stanowiska do bazy:
#   POST  /orders/<id>/complete   (mobile_api.py:339)
#   PATCH /orders/<id>/quantity   (mobile_api.py:391)
#   POST  /orders/<id>/reject     (mobile_api.py:441)
#   POST  /sessions/start         (mobile_api.py:1000)

def test_stary_tablet_domyka_krawedzie_przez_complete(client, app):
    """
    Bez aliasu kod 'finishing' wypada z STATION_STATUS_MAP (katalog zna już
    tylko 'edges') i bramka oddaje 404 unknown_station — stary APK przestaje
    domykać cokolwiek.
    """
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=4,
                          finish_type='olejowane', obrobka_krawedzi=True)

    odp = client.post('/api/mobile/orders/{}/complete'.format(produkt_id),
                      headers=_naglowki(token, operation_id='op-complete-1'),
                      json={})

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['status'] == 'czeka_na_lakiernie'

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        assert produkt.quantity_done_edges == 4
        assert produkt.edges_completed_at is not None
        assert produkt.current_status == 'czeka_na_lakiernie'

        kody = {e.station_code for e in ProductionStationEvent.query.all()}
        assert kody == {'edges'}


def test_body_z_kodem_finishing_tez_rozwija_sie_na_edges(client, app):
    """Stary APK potrafi podać station_code jawnie w ciele żądania."""
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=2,
                          finish_type='surowe', obrobka_krawedzi=True)

    odp = client.post('/api/mobile/orders/{}/complete'.format(produkt_id),
                      headers=_naglowki(token, operation_id='op-complete-2'),
                      json={'station_code': 'finishing'})

    assert odp.status_code == 200, odp.get_json()
    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        assert produkt.quantity_done_edges == 2
        assert produkt.current_status == 'czeka_na_logistyke'


def test_stary_tablet_odbija_sztuki_przez_patch_quantity(client, app):
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=4)

    odp = client.patch('/api/mobile/orders/{}/quantity'.format(produkt_id),
                       headers=_naglowki(token, operation_id='op-qty-1'),
                       json={'quantity_done': 2})

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['quantity_done'] == 2

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        assert produkt.quantity_done_edges == 2
        # Wartość CZĘŚCIOWA kasuje znacznik domknięcia (models.py:448-449).
        assert produkt.edges_completed_at is None

        zdarzenia = ProductionStationEvent.query.all()
        assert [e.station_code for e in zdarzenia] == ['edges']
        assert zdarzenia[0].delta == 2


def test_alias_nie_dziala_w_druga_strone():
    """
    Strażnik kontraktu z nagłówka planu, postawiony na ścieżce mobilnej:
    nowy tablet z kodem kanonicznym ma działać wprost, a nie przez tablicę
    tłumaczeń.
    """
    from modules.production.services.station_catalog import resolve_station_code
    assert resolve_station_code('edges') == 'edges'
    assert resolve_station_code('finishing') == 'edges'
    assert resolve_station_code('painting') == 'painting'


def test_stary_tablet_przechodzi_bramke_rejectu(client, app):
    """
    Reject jest MVP-owo tylko dla formatowania (rework_service.py:22), więc
    tablet Krawędzi ma dostać 400 invalid_station. Istotne jest to, CZEGO
    nie dostaje: 404 unknown_station znaczyłoby, że alias nie zadziałał
    i kod poległ na bramce, a 403 station_mismatch — że poległ na kontroli
    dostępu. Ten drugi jest w zbiorze BLEDY_DO_PONOWIENIA, ale i tak
    zatrzymałby kolejkę offline tabletu.
    """
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=4)

    odp = client.post('/api/mobile/orders/{}/reject'.format(produkt_id),
                      headers=_naglowki(token, operation_id='op-rej-1'),
                      json={'quantity': 1, 'reason_category': 'wymiary'})

    assert odp.status_code == 400, odp.get_json()
    assert odp.get_json()['error'] == 'invalid_station'
    assert 'formatting' in odp.get_json()['detail']


def test_stary_tablet_otwiera_sesje_na_krawedziach(client, app):
    """
    Trzecia bramka: znane_kody = ProductionDevice.VALID_STATION_CODES, gdzie
    'finishing' na okres przejściowy ZOSTAJE. Bez rozwinięcia aliasu żądanie
    przeszłoby walidację i zapisało martwy kod do prod_worker_sessions —
    czyli dokładnie tam, gdzie liczy się czas pracy i „szybki wybór" profili.
    """
    token = _token(app, station_code='finishing')
    with app.app_context():
        pracownik = ProductionWorker(first_name='Ewa', last_name='Nowak',
                                     is_active=True, sort_order=0)
        db.session.add(pracownik)
        db.session.commit()
        pracownik_id = pracownik.id

    odp = client.post('/api/mobile/sessions/start',
                      headers=_naglowki(token, operation_id='op-ses-1'),
                      json={'worker_ids': [pracownik_id],
                            'session_group': 'grupa-1'})

    assert odp.status_code == 200, odp.get_json()
    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.station_code == 'edges'
        assert sesja.worker_id == pracownik_id
        assert sesja.is_open


def test_zaden_endpoint_mutujacy_nie_zapisuje_kodu_finishing(client, app):
    """
    Zbiorcza asercja końcowa: po przejściu wszystkich czterech ścieżek
    w bazie nie ma ANI JEDNEGO wiersza z martwym kodem stanowiska.
    """
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=4)
    with app.app_context():
        pracownik = ProductionWorker(first_name='Jan', last_name='Zielinski',
                                     is_active=True, sort_order=0)
        db.session.add(pracownik)
        db.session.commit()
        pracownik_id = pracownik.id

    client.post('/api/mobile/sessions/start',
                headers=_naglowki(token, operation_id='op-z-1'),
                json={'worker_ids': [pracownik_id], 'session_group': 'g-z'})
    client.patch('/api/mobile/orders/{}/quantity'.format(produkt_id),
                 headers=_naglowki(token, operation_id='op-z-2'),
                 json={'quantity_done': 1})
    client.post('/api/mobile/orders/{}/reject'.format(produkt_id),
                headers=_naglowki(token, operation_id='op-z-3'),
                json={'quantity': 1, 'reason_category': 'wymiary'})
    client.post('/api/mobile/orders/{}/complete'.format(produkt_id),
                headers=_naglowki(token, operation_id='op-z-4'),
                json={})

    with app.app_context():
        kody_zdarzen = {e.station_code
                        for e in ProductionStationEvent.query.all()}
        kody_sesji = {s.station_code
                      for s in ProductionWorkerSession.query.all()}
        assert 'finishing' not in kody_zdarzen
        assert 'finishing' not in kody_sesji
        assert kody_zdarzen == {'edges'}
        assert kody_sesji == {'edges'}


# ============================================================================
# REJESTRACJA URZĄDZENIA
# ============================================================================

def test_rejestracja_starym_kodem_zapisuje_kod_kanoniczny(client, app):
    """
    Bez normalizacji stary APK zapisuje 'finishing' w prod_devices przy
    każdym odnowieniu JWT i sam odtwarza wiersz, który migracja przed chwilą
    poprawiła. Rejestracja jest jedynym miejscem, w którym urządzenie
    przedstawia się kodem stanowiska.
    """
    odp = client.post('/api/mobile/register', json={
        'device_id': 'TABLET-STARY',
        'device_name': 'Tablet wykanczalni',
        'station_code': 'finishing',
    })

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'edges'

    with app.app_context():
        urzadzenie = ProductionDevice.query.filter_by(
            device_id='TABLET-STARY').one()
        assert urzadzenie.station_code == 'edges'


def test_rejestracja_tabletu_lakierni(client, app):
    """STRAŻNIK W1: do 09.2026 'painting' nie było w VALID_STATION_CODES."""
    odp = client.post('/api/mobile/register', json={
        'device_id': 'TABLET-LAKIERNIA',
        'device_name': 'Tablet lakierni',
        'station_code': 'painting',
    })

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'painting'


def test_nowy_tablet_lakierni_domyka_lakiernie(client, app):
    """
    STRAŻNIK trasy: Lakiernia jako PEŁNOPRAWNE stanowisko z własnym tabletem,
    bez pośrednictwa grupy STATION_GROUPS. To jest docelowy stan po kroku 17
    wdrożenia — dziś ścieżka jest nieosiągalna, bo takiego tabletu nie da się
    zarejestrować.
    """
    rej = client.post('/api/mobile/register', json={
        'device_id': 'TABLET-LAK-2',
        'device_name': 'Tablet lakierni',
        'station_code': 'painting',
    })
    assert rej.status_code == 200, rej.get_json()
    token = rej.get_json()['token']

    produkt_id = _produkt(app, status='czeka_na_lakiernie', quantity=2,
                          finish_type='lakierowane', obrobka_krawedzi=False)

    odp = client.post('/api/mobile/orders/{}/complete'.format(produkt_id),
                      headers=_naglowki(token, operation_id='op-lak-1'),
                      json={})

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['status'] == 'czeka_na_logistyke'

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        assert produkt.quantity_done_painting == 2
        assert produkt.painting_completed_at is not None

        kody = {e.station_code for e in ProductionStationEvent.query.all()}
        assert kody == {'painting'}


def test_rejestracja_nieznanym_kodem_dalej_odrzucana(client, app):
    """STRAŻNIK: alias rozwija JEDEN kod, nie otwiera bramki na dowolny."""
    odp = client.post('/api/mobile/register', json={
        'device_id': 'TABLET-X',
        'device_name': 'Tablet',
        'station_code': 'wykanczanie',
    })

    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'invalid_station_code'


# ============================================================================
# KOLEJKA STANOWISKA
# ============================================================================

def test_stary_adres_kolejki_oddaje_kolejke_krawedzi(client, app):
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_krawedzie', quantity=3)

    odp = client.get('/api/mobile/stations/finishing/orders',
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    assert dane['station_code'] == 'edges'
    assert dane['count'] == 1
    assert dane['orders'][0]['quantity_done'] == 0


def test_stary_i_nowy_adres_kolejki_daja_ten_sam_etag(client, app):
    """
    station_code wchodzi do ETaga (mobile_api.py:235). Bez normalizacji
    tablet przełączony ze starego adresu na nowy pobiera pełną listę
    ponownie — a cały park robi to naraz, w chwili gdy gunicorn dopiero
    wstaje po restarcie.
    """
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_krawedzie', quantity=3)

    stary = client.get('/api/mobile/stations/finishing/orders',
                       headers=_naglowki(token))
    nowy = client.get('/api/mobile/stations/edges/orders',
                      headers=_naglowki(token))

    assert stary.status_code == 200, stary.get_json()
    assert nowy.status_code == 200, nowy.get_json()
    assert stary.headers['ETag'] == nowy.headers['ETag']
    assert stary.get_json() == nowy.get_json()


def test_stary_tablet_widzi_kolejke_lakierni(client, app):
    """STRAŻNIK: STATION_GROUPS + normalizacja obu stron z zadania 2."""
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_lakiernie', quantity=1,
             finish_type='lakierowane', obrobka_krawedzi=False)

    odp = client.get('/api/mobile/stations/painting/orders',
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'painting'
    assert odp.get_json()['count'] == 1


def test_nowy_tablet_krawedzi_pobiera_kolejke_bez_aliasu(client, app):
    """STRAŻNIK: docelowy tablet z kodem 'edges' działa bez tablicy tłumaczeń."""
    token = _token(app, station_code='edges', device_id='TABLET-EDGES')
    _produkt(app, status='czeka_na_krawedzie', quantity=3)

    odp = client.get('/api/mobile/stations/edges/orders',
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'edges'
    assert odp.get_json()['count'] == 1


# ============================================================================
# SZCZEGÓŁY ZLECENIA
# ============================================================================

def test_szczegoly_zlecenia_dla_starego_tabletu_maja_licznik(client, app):
    """
    JEDYNY endpoint mobilny bez walidacji kodu stanowiska — nie przechodzi
    przez _resolve_station_code. Bez normalizacji kod 'finishing' wypada
    z bramki członkostwa STATION_QUANTITY_FIELD (mobile_api_service.py:1024)
    i odpowiedź niesie quantity_done: null. Bez błędu, bez logu — tablet
    pokazuje 0 z N dla pozycji, na której coś już odbito.
    """
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=5)

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.quantity_done_edges = 2
        db.session.commit()

    odp = client.get('/api/mobile/orders/{}'.format(produkt_id),
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['quantity_done'] == 2


def test_szczegoly_zlecenia_dla_nowego_tabletu_krawedzi(client, app):
    """STRAŻNIK: tablet z kanonicznym kodem działa bez aliasu."""
    token = _token(app, station_code='edges', device_id='TABLET-EDGES')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=5)

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.quantity_done_edges = 4
        db.session.commit()

    odp = client.get('/api/mobile/orders/{}'.format(produkt_id),
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['quantity_done'] == 4


# ============================================================================
# SUMMARY I DELTA SYNC
# ============================================================================

def test_metryki_stanowiska_dzialaja_pod_starym_kodem(client, app):
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_krawedzie', quantity=3)

    odp = client.get('/api/mobile/stations/finishing/summary',
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    assert dane['station_code'] == 'edges'
    assert dane['queue']['count'] == 1


def test_metryki_lakierni_ze_starego_tabletu(client, app):
    """STRAŻNIK: zakładka Lakierni na starym tablecie ma dalej działać."""
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_lakiernie', quantity=2,
             finish_type='olejowane', obrobka_krawedzi=False)

    odp = client.get('/api/mobile/stations/painting/summary',
                     headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'painting'
    assert odp.get_json()['queue']['count'] == 1


def test_delta_sync_dziala_pod_starym_kodem(client, app):
    token = _token(app, station_code='finishing')
    produkt_id = _produkt(app, status='czeka_na_krawedzie', quantity=3)

    odp = client.get(
        '/api/mobile/stations/finishing/orders/since?ts=2020-01-01T00:00:00',
        headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    assert dane['station_code'] == 'edges'
    assert dane['all_ids'] == [produkt_id]
    assert dane['changed'][0]['quantity_done'] == 0


# ============================================================================
# DRUK ETYKIET
# ============================================================================

def _podmien_druk(monkeypatch, przechwycone):
    """Podmienia print_labels_batch i zapisuje kod stanowiska, z jakim wołano."""
    def fake_batch(short_product_ids, station_code, actor):
        przechwycone.append(station_code)
        return {
            'success': True,
            'success_count': len(list(short_product_ids)),
            'failed_count': 0,
            'connection_error': False,
            'message': 'OK',
            'results': [],
        }

    monkeypatch.setattr(
        'modules.production.services.label_print_service.print_labels_batch',
        fake_batch,
    )


def test_druk_pojedynczej_etykiety_uzywa_kodu_kanonicznego(
        client, app, monkeypatch):
    """
    Oba endpointy druku OMIJAJĄ _resolve_station_code — czytają
    g.device.station_code wprost (mobile_api.py:682, :709). Bez własnej
    normalizacji tablet z niezmigrowanym wierszem dostaje 403
    StationNotAllowed po cichu, bo 'finishing' nie ma prawa wstępu na listę
    LABEL_PRINTER_ALLOWED_STATIONS.
    """
    przechwycone = []
    _podmien_druk(monkeypatch, przechwycone)
    token = _token(app, station_code='finishing')

    odp = client.post('/api/mobile/products/26042_1/print-label',
                      headers=_naglowki(token), json={})

    assert odp.status_code == 200, odp.get_json()
    assert przechwycone == ['edges']


def test_druk_etykiet_zamowienia_uzywa_kodu_kanonicznego(
        client, app, monkeypatch):
    przechwycone = []
    _podmien_druk(monkeypatch, przechwycone)
    token = _token(app, station_code='finishing')
    _produkt(app, status='czeka_na_krawedzie', quantity=1)

    odp = client.post('/api/mobile/orders/990001/print-labels',
                      headers=_naglowki(token), json={})

    assert odp.status_code == 200, odp.get_json()
    assert przechwycone == ['edges']


# ============================================================================
# STAN SESJI — /sessions/active
# ============================================================================

def test_stan_sesji_echuje_kanoniczny_kod_urzadzenia(client, app):
    """
    Ostatnie miejsce oddające tabletowi surowy station_code. Apka zapamiętuje
    tę wartość i odsyła ją w ciele operacji mutujących, więc bez normalizacji
    stary kod krąży w kółko także po migracji prod_devices.
    """
    token = _token(app, station_code='finishing')

    odp = client.get('/api/mobile/sessions/active', headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    assert odp.get_json()['station_code'] == 'edges'
    assert odp.get_json()['session_group'] is None
    assert odp.get_json()['worker_ids'] == []


def test_stan_sesji_normalizuje_kod_w_wierszu_sesji(client, app):
    """
    Wiersz prod_worker_sessions sprzed migracji może jeszcze nieść stary kod
    (sesja otwarta w chwili deployu, wpis przywrócony z backupu). Na tablecie
    to pole rysuje nagłówek stanowiska — surowe 'finishing' wygląda jak
    przełączenie na nieistniejące stanowisko.
    """
    token = _token(app, station_code='finishing')
    with app.app_context():
        pracownik = ProductionWorker(first_name='Piotr', last_name='Wisniewski',
                                     is_active=True, sort_order=0)
        db.session.add(pracownik)
        db.session.flush()
        teraz = get_local_now()
        sesja = ProductionWorkerSession(
            worker_id=pracownik.id,
            station_code='finishing',
            device_id='TABLET-1',
            started_at=teraz,
            last_activity_at=teraz,
            work_date=teraz.date(),
            session_group='grupa-sprzed-migracji',
        )
        db.session.add(sesja)
        db.session.commit()
        pracownik_id = pracownik.id

    odp = client.get('/api/mobile/sessions/active', headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    assert dane['station_code'] == 'edges'
    assert dane['session_group'] == 'grupa-sprzed-migracji'
    assert dane['worker_ids'] == [pracownik_id]
    assert len(dane['sessions']) == 1
    assert dane['sessions'][0]['station_code'] == 'edges'
    assert dane['sessions'][0]['worker_name'] == 'Piotr Wisniewski'


# ============================================================================
# KATALOG PRACOWNIKÓW
# ============================================================================

def test_szybki_wybor_profili_dziala_na_starym_tablecie(client, app):
    """
    recent_on_station liczy worker_service._workers_recent_on_station po
    prod_worker_sessions.station_code. Migracja przepisała sesje na 'edges',
    więc bez normalizacji kodu z JWT zapytanie leci po martwym 'finishing'
    i sekcja „szybki wybór" na tablecie Krawędzi jest pusta — bez błędu.
    """
    token = _token(app, station_code='finishing')
    with app.app_context():
        pracownik = ProductionWorker(first_name='Adam', last_name='Kowalski',
                                     is_active=True, sort_order=0)
        db.session.add(pracownik)
        db.session.flush()
        wczoraj = get_local_now() - timedelta(days=1)
        sesja = ProductionWorkerSession(
            worker_id=pracownik.id,
            station_code='edges',
            device_id='TABLET-1',
            started_at=wczoraj,
            # last_activity_at jest NOT NULL i NIE MA defaultu w modelu
            # (models.py:1324) — bez tego pola insert leci IntegrityError.
            last_activity_at=wczoraj,
            work_date=wczoraj.date(),
            session_group='grupa-historyczna',
        )
        db.session.add(sesja)
        db.session.commit()
        pracownik_id = pracownik.id

    odp = client.get('/api/mobile/workers', headers=_naglowki(token))

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    profile = {w['id']: w for w in dane['workers']}
    assert profile[pracownik_id]['recent_on_station'] is True


def test_katalog_pracownikow_ma_ten_sam_etag_dla_obu_kodow(client, app):
    """
    station_code wchodzi do ETaga katalogu (mobile_api.py:860). Bez
    normalizacji dwa tablety tego samego stanowiska mają dwa różne klucze
    cache i oba pobierają pełny katalog przy każdym starcie.
    """
    stary = _token(app, station_code='finishing', device_id='TABLET-STARY')
    nowy = _token(app, station_code='edges', device_id='TABLET-NOWY')

    odp_stary = client.get('/api/mobile/workers', headers=_naglowki(stary))
    odp_nowy = client.get('/api/mobile/workers', headers=_naglowki(nowy))

    assert odp_stary.status_code == 200, odp_stary.get_json()
    assert odp_nowy.status_code == 200, odp_nowy.get_json()
    assert odp_stary.headers['ETag'] == odp_nowy.headers['ETag']
    assert (odp_stary.get_json()['catalog_version']
            == odp_stary.headers['ETag'])


# ============================================================================
# DOKUMENTACJA ŚCIEŻKI MOBILNEJ
# ============================================================================

def test_docstringi_sciezki_mobilnej_opisuja_nowa_trase():
    """
    Docstringi tych trzech funkcji są jedynym opisem routingu w warstwie
    mobilnej. Zdanie „skip finishing dla surowych bez krawędzi" opisuje
    regułę ZNIESIONĄ: should_skip_edges() pyta wyłącznie o obróbkę
    krawędzi, niezależnie od wykończenia. Zostawiony napis myli przy
    następnym audycie bardziej niż jego brak.
    """
    from modules.production.routers import mobile_api as router
    from modules.production.services import mobile_api_service as serwis

    teksty = {
        '_resolve_workers': router._resolve_workers.__doc__,
        'order_complete': router.order_complete.__doc__,
        'mark_order_complete': serwis.mark_order_complete.__doc__,
    }
    for nazwa, tekst in sorted(teksty.items()):
        assert tekst, 'brak docstringu: {}'.format(nazwa)
        assert 'finishing' not in tekst, \
            '{} dalej opisuje stanowisko kodem finishing'.format(nazwa)
        assert 'wykańczal' not in tekst, \
            '{} dalej mówi o wykańczalni'.format(nazwa)
