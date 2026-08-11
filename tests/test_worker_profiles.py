# -*- coding: utf-8 -*-
"""
Profile pracowników — katalog, sesje i atrybucja pracy.

Projekt: docs/worker-profiles-backend.md (etapy 1-3).

Najważniejszy test w tym pliku to
test_complete_tworzy_event_z_atrybucja: pilnuje naprawy z §8 (pułapka nr 1).
Przed nią mobilne /orders/<id>/complete NIE tworzyło żadnego wpisu
w prod_station_events, więc po usunięciu paneli webowych statystyki stanowisk
gubiłyby całą pracę zamykaną przyciskiem "gotowe".
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession, get_local_now,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Import wymagany, żeby topologiczne sortowanie FK w create_all znalazło
# tabelę 'users' — ten sam powód co w test_mobile_complete_bl_sync_queue.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionReworkLog,
    ProductionWorker, ProductionWorkerSession, ProductionStationEvent,
    ProductionStationEventWorker,
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
        'token_ttl_days': 365,
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
    """
    ProductionConfigService trzyma konfigurację w singletonie z cache'em —
    bez tego wartość ustawiona w jednym teście przeciekłaby do następnego.
    """
    from modules.production.services.config_service import invalidate_config_cache
    invalidate_config_cache()
    yield
    invalidate_config_cache()


# ============================================================================
# POMOCNICZE
# ============================================================================

def _token(app, station_code='gluing', device_id='TABLET-1'):
    with app.app_context():
        device = ProductionDevice(device_id=device_id, device_name='Tablet',
                                  station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _naglowki(token, worker_ids=None, operation_id=None):
    naglowki = {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'}
    if worker_ids is not None:
        naglowki['X-Worker-Ids'] = worker_ids
    if operation_id:
        naglowki['X-Operation-Id'] = operation_id
    return naglowki


def _pracownicy(app, ilu=2, aktywni=True):
    with app.app_context():
        dodani = []
        for i in range(ilu):
            w = ProductionWorker(first_name=f'Imie{i}', last_name=f'Nazwisko{i}',
                                 is_active=aktywni, sort_order=i)
            db.session.add(w)
            dodani.append(w)
        db.session.commit()
        return [w.id for w in dodani]


def _produkt(app, status='czeka_na_sklejanie', quantity=10):
    with app.app_context():
        order = ProductionOrder(baselinker_order_id=990001,
                                internal_order_number='26/00042')
        db.session.add(order)
        db.session.flush()
        produkt = ProductionProduct(
            order_id=order.id, short_product_id='26042_1',
            product_sequence_in_order=1, original_product_name='Blat dębowy',
            quantity=quantity, current_status=status)
        db.session.add(produkt)
        db.session.commit()
        return produkt.id


def _iso_apki(dt):
    """
    DOKŁADNIE to, co wysyła tablet: naive czas warszawski BEZ offsetu, ucięty
    do sekund — `SyncQueueDrainer.toLocalIso()` (ISO_LOCAL_DATE_TIME).

    Domyślny helper znaczników w tym pliku. Testy sesji jadące na formacie
    z offsetem przechodziły, gdy serwer czytał naive jako UTC — czyli maskowały
    rozjazd o pełną strefę na każdej sesji z kolejki offline.
    """
    return dt.replace(microsecond=0).isoformat()


def _iso_z_offsetem(dt):
    """Naive czas warszawski → ISO Z OFFSETEM. Kontrakt dopuszcza obie formy."""
    import pytz
    return pytz.timezone('Europe/Warsaw').localize(dt).isoformat()


def _zapisz_config(app, klucz, wartosc, typ='boolean', updated_at=None):
    """
    Sam zapis do prod_config — BEZ dotykania cache'u w tym procesie.

    updated_at (gdy podany) dociskamy osobnym UPDATE-em na poziomie Core.
    Kolumna ma `onupdate=datetime.utcnow`, więc przypisanie na obiekcie ORM
    zostałoby nadpisane i test "dwie zmiany w tej samej sekundzie" mierzyłby
    przypadek zamiast tego, co miał mierzyć.
    """
    with app.app_context():
        wpis = ProductionConfig.query.filter_by(config_key=klucz).first()
        if wpis:
            wpis.config_value = str(wartosc)
        else:
            db.session.add(ProductionConfig(config_key=klucz, config_value=str(wartosc),
                                            config_type=typ))
        db.session.commit()

        if updated_at is not None:
            db.session.execute(
                ProductionConfig.__table__.update()
                .where(ProductionConfig.__table__.c.config_key == klucz)
                .values(updated_at=updated_at))
            db.session.commit()


def _ustaw_config(app, klucz, wartosc, typ='boolean', updated_at=None):
    from modules.production.services.config_service import invalidate_config_cache
    _zapisz_config(app, klucz, wartosc, typ, updated_at)
    invalidate_config_cache()


def _ustaw_config_z_innego_procesu(app, klucz, wartosc, typ='boolean'):
    """
    Zmiana konfiguracji widziana tak, jak widzi ją proces SERWUJĄCY tablety:
    wiersz w bazie już nowy, ale cache tego procesu nadal trzyma starą wartość.

    Dokładnie ta sytuacja na produkcji — Passenger trzyma kilka procesów,
    a set_config invaliduje cache tylko w tym, który obsłużył panel.
    """
    _zapisz_config(app, klucz, wartosc, typ)


# ============================================================================
# KATALOG
# ============================================================================

def test_katalog_zwraca_aktywnych_i_konfiguracje(client, app):
    token = _token(app)
    _pracownicy(app, 2)
    with app.app_context():
        db.session.add(ProductionWorker(first_name='Zwolniony', last_name='Kowalski',
                                        is_active=False))
        db.session.commit()

    odp = client.get('/api/mobile/workers', headers=_naglowki(token))

    assert odp.status_code == 200
    dane = odp.get_json()
    assert [w['first_name'] for w in dane['workers']] == ['Imie0', 'Imie1']
    # Apka nie hardkoduje żadnej z tych wartości — muszą przyjść z katalogiem.
    assert dane['selection_required'] is False
    assert dane['idle_timeout_minutes'] == 120
    assert dane['night_cutoff'] == '23:00'
    assert dane['quick_pick_count'] == 8
    assert dane['catalog_version']


def test_katalog_zwraca_inicjaly_i_kolor_bez_zdjecia(client, app):
    token = _token(app)
    _pracownicy(app, 1)

    dane = client.get('/api/mobile/workers', headers=_naglowki(token)).get_json()
    kafelek = dane['workers'][0]

    assert kafelek['initials'] == 'IN'
    assert kafelek['avatar_url'] is None
    assert kafelek['color_hex'].startswith('#')
    assert kafelek['allowed_stations'] == []   # brak ograniczeń = wszystkie


def test_katalog_odpowiada_304_gdy_nic_sie_nie_zmienilo(client, app):
    token = _token(app)
    _pracownicy(app, 1)

    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    etag = pierwsza.headers['ETag']

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = etag
    druga = client.get('/api/mobile/workers', headers=naglowki)

    assert druga.status_code == 304


def test_catalog_version_jest_tym_samym_stringiem_co_etag(client, app):
    """
    Apka NIE echuje nagłówka ETag. Wysyła jako If-None-Match POLE
    `catalog_version` z ciała (WorkerRepositoryImpl: `configStore
    .catalogVersion()`, zapisywane z `body.catalogVersion`).

    Dopóki to były dwa różne stringi, warunkowy GET nie trafiał NIGDY: tablet
    dostawał 200 z pełnym katalogiem przy każdym starcie i każdym odświeżeniu,
    a gałąź NOT_MODIFIED po ich stronie była martwa.
    """
    token = _token(app)
    _pracownicy(app, 1)

    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    catalog_version = pierwsza.get_json()['catalog_version']
    assert catalog_version == pierwsza.headers['ETag']

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = catalog_version
    assert client.get('/api/mobile/workers', headers=naglowki).status_code == 304


def test_kazdy_klucz_konfiguracji_uniewaznia_catalog_version(client, app):
    """
    Odpowiedź na pytanie zespołu mobilnego: ETag obejmuje WSZYSTKIE cztery
    klucze konfiguracji, więc zmiana kill-switcha dojeżdża na tablety.
    Sprawdzane po tej wartości, którą apka faktycznie odsyła.
    """
    token = _token(app)
    _pracownicy(app, 1)

    zmiany = (
        ('WORKER_SELECTION_REQUIRED', 'true', 'boolean', 'selection_required', True),
        ('WORKER_SESSION_IDLE_TIMEOUT_MINUTES', 45, 'integer', 'idle_timeout_minutes', 45),
        ('WORKER_SESSION_NIGHT_CUTOFF', '22:30', 'string', 'night_cutoff', '22:30'),
        ('WORKER_QUICK_PICK_COUNT', 6, 'integer', 'quick_pick_count', 6),
    )

    for klucz, wartosc, typ, pole, oczekiwane in zmiany:
        poprzedni = client.get('/api/mobile/workers',
                               headers=_naglowki(token)).get_json()['catalog_version']
        _ustaw_config(app, klucz, wartosc, typ=typ)

        naglowki = _naglowki(token)
        naglowki['If-None-Match'] = poprzedni
        odp = client.get('/api/mobile/workers', headers=naglowki)

        assert odp.status_code == 200, f'304 mimo zmiany {klucz}'
        assert odp.get_json()[pole] == oczekiwane


def test_kill_switch_z_innego_procesu_dojezdza_mimo_cache(client, app):
    """
    ETag liczyliśmy prosto z bazy, a ciało z 60-minutowego cache PROCESU.
    Zmiana z panelu obsługiwanego przez inny proces Passengera dawała więc
    odpowiedź NOWY ETag + STARA wartość: tablet zapisywał ją i od następnego
    żądania dostawał 304, czyli zostawał na starym kill-switchu także po
    wygaśnięciu cache.
    """
    token = _token(app)
    _pracownicy(app, 1)

    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    assert pierwsza.get_json()['selection_required'] is False
    catalog_version = pierwsza.get_json()['catalog_version']

    _ustaw_config_z_innego_procesu(app, 'WORKER_SELECTION_REQUIRED', 'true')

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = catalog_version
    druga = client.get('/api/mobile/workers', headers=naglowki)

    assert druga.status_code == 200
    assert druga.get_json()['selection_required'] is True
    assert druga.get_json()['catalog_version'] != catalog_version


def test_dwie_zmiany_w_tej_samej_sekundzie_docieraja_na_tablet(client, app):
    """
    Segment konfiguracji w ETagu bierzemy z WARTOŚCI, nie z MAX(updated_at).
    Znacznik ma rozdzielczość sekundy (a kolumna jest `datetime NULL` bez
    ON UPDATE), więc druga zmiana w tej samej sekundzie — dwuklik "Zapisz",
    dwa zapisy z różnych podsystemów — była dla tabletu nieosiągalna na
    zawsze: dostawał 304 z ETagiem sprzed niej.
    """
    token = _token(app)
    _pracownicy(app, 1)
    znacznik = get_local_now().replace(microsecond=0)

    _ustaw_config(app, 'WORKER_QUICK_PICK_COUNT', 8, typ='integer', updated_at=znacznik)
    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    poprzedni = pierwsza.get_json()['catalog_version']

    # Ta sama sekunda w updated_at — dla ETagu liczonego ze znacznika czasu
    # ta zmiana jest niewidoczna.
    _ustaw_config(app, 'WORKER_QUICK_PICK_COUNT', 2, typ='integer', updated_at=znacznik)

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = poprzedni
    odp = client.get('/api/mobile/workers', headers=naglowki)

    assert odp.status_code == 200
    assert odp.get_json()['quick_pick_count'] == 2
    # Asercja wprost na nagłówku: bez odcisku wartości ETag byłby identyczny,
    # więc każdy klient trzymający poprzedni dostawałby 304 aż do następnej
    # zmiany prod_config.
    assert odp.headers['ETag'] != pierwsza.headers['ETag']


# ============================================================================
# SESJE
# ============================================================================

def test_start_sesji_tworzy_wiersz_na_pracownika(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'grupa-1'})

    assert odp.status_code == 200
    dane = odp.get_json()
    assert dane['session_group'] == 'grupa-1'
    assert len(dane['sessions']) == 2

    with app.app_context():
        sesje = ProductionWorkerSession.query.all()
        assert len(sesje) == 2
        assert {s.worker_id for s in sesje} == set(ids)
        assert all(s.station_code == 'gluing' for s in sesje)
        assert all(s.work_date == s.started_at.date() for s in sesje)
        urzadzenie = ProductionDevice.query.first()
        assert urzadzenie.last_worker_session_at is not None


def test_start_sesji_domyka_poprzednia_obsade_jako_replaced(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[0]], 'session_group': 'zmiana-1'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[1]], 'session_group': 'zmiana-2'})

    with app.app_context():
        pierwsza = ProductionWorkerSession.query.filter_by(session_group='zmiana-1').one()
        druga = ProductionWorkerSession.query.filter_by(session_group='zmiana-2').one()
        assert pierwsza.ended_at is not None
        assert pierwsza.end_reason == 'replaced'
        assert druga.ended_at is None


def test_start_sesji_nie_przyjmuje_czasu_z_przyszlosci(client, app):
    """started_at przycinane do min(client, now) — tablet mógł mieć zły zegar."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    przyszlosc = (get_local_now() + timedelta(days=2)).isoformat()

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g', 'started_at': przyszlosc})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.started_at <= get_local_now() + timedelta(minutes=1)


def test_started_at_bez_strefy_jest_czytany_jako_czas_lokalny(client, app):
    """
    KONTRAKT Z APKĄ: timestamp BEZ offsetu to CZAS LOKALNY.

    Apka wysyła dokładnie taki string (SyncQueueDrainer.toLocalIso →
    ISO_LOCAL_DATE_TIME w Europe/Warsaw), tak samo jak measured_at trakowni.
    Czytanie go jako UTC przesuwało sesję rozpoczętą o 6:12 na 8:12 i o tyle
    samo zaniżało czas pracy w raporcie.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g',
                      'started_at': '2026-08-11T06:12:00'})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.started_at == datetime(2026, 8, 11, 6, 12)
        assert sesja.work_date == datetime(2026, 8, 11).date()


def test_started_at_z_offsetem_jest_przeliczany_na_czas_lokalny(client, app):
    """
    Kontrakt dopuszcza OBIE formy, żeby ewentualne przejście apki na
    ISO_OFFSET_DATE_TIME nie wymagało zmiany serwera. 04:12 UTC = 06:12 lokalnie.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g',
                      'started_at': '2026-08-11T04:12:00Z'})

    with app.app_context():
        assert ProductionWorkerSession.query.one().started_at == datetime(2026, 8, 11, 6, 12)


def test_ended_at_z_kolejki_offline_nie_lezy_w_przyszlosci(client, app):
    """
    Tablet online kończy sesję "teraz". Gdy serwer czytał naive jako UTC,
    ended_at lądował o pełny offset strefy PO czasie serwera — sesja trwająca
    30 minut raportowała 2,5 godziny, a panel pokazywał koniec w przyszłości.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    start = get_local_now() - timedelta(minutes=30)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g',
                      'started_at': _iso_apki(start)})
    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                      json={'session_group': 'g', 'reason': 'manual',
                            'ended_at': _iso_apki(get_local_now())})

    assert odp.status_code == 200
    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.ended_at <= get_local_now()
        assert 29 <= sesja.duration_minutes <= 31


def test_zegar_tabletu_z_przyszlosci_jest_przycinany_a_nie_odrzucany(client, app):
    """
    Dryf zegara nie może zablokować kolejki: 4xx to u klienta wpis do
    interwencji biura, więc znacznik z przyszłości PRZYCINAMY do teraz.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'g',
                            'started_at': _iso_apki(get_local_now() + timedelta(hours=5))})

    assert odp.status_code == 200
    with app.app_context():
        assert ProductionWorkerSession.query.one().started_at <= get_local_now()


def test_start_sesji_odrzuca_nieaktywnego_pracownika(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1, aktywni=False)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'g'})

    assert odp.status_code == 409
    assert odp.get_json()['error'] == 'worker_inactive'


def test_start_sesji_jest_idempotentny(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    naglowki = _naglowki(token, operation_id='op-123')

    pierwsza = client.post('/api/mobile/sessions/start', headers=naglowki,
                           json={'worker_ids': ids, 'session_group': 'g'})
    druga = client.post('/api/mobile/sessions/start', headers=naglowki,
                        json={'worker_ids': ids, 'session_group': 'g'})

    assert pierwsza.status_code == 200
    assert druga.status_code == 200
    with app.app_context():
        assert ProductionWorkerSession.query.count() == 1


def test_koniec_sesji_domyka_cala_grupe(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'grupa-x'})

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                      json={'session_group': 'grupa-x', 'reason': 'manual'})

    assert odp.status_code == 200
    assert odp.get_json()['closed'] == 2
    with app.app_context():
        sesje = ProductionWorkerSession.query.all()
        assert all(s.ended_at is not None and s.end_reason == 'manual' for s in sesje)


def test_koniec_sesji_odrzuca_powody_zarezerwowane_dla_backendu(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    for powod in ('replaced', 'admin'):
        odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                          json={'session_group': 'g', 'reason': powod})
        assert odp.status_code == 422, powod
        assert odp.get_json()['error'] == 'invalid_end_reason'


def test_aktywne_sesje_po_restarcie_apki(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    dane = client.get('/api/mobile/sessions/active',
                      headers=_naglowki(token)).get_json()

    assert dane['session_group'] == 'g'
    assert len(dane['sessions']) == 2
    assert dane['sessions'][0]['worker_name'] == 'Imie0 Nazwisko0'


# ============================================================================
# PRZEJĘCIE PROFILU MIĘDZY TABLETAMI (wariant A) I SPÓŹNIONY START
#
# Decyzja zespołu mobilnego z 11.08.2026: jeden tablet = jeden pracownik,
# a kolizję rozstrzyga SERWER — wskazanie tego samego profilu na drugim
# tablecie domyka poprzednią sesję jako 'replaced'. Kolizja nie jest błędem:
# 409 oznaczałoby w kolejce offline "wpis czeka na interwencję biura".
# ============================================================================

def test_przejecie_profilu_domyka_sesje_na_pierwszym_tablecie(client, app):
    """Wariant A: jeden pracownik = maksymalnie jedna otwarta sesja."""
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                json={'worker_ids': ids, 'session_group': 'na-tablecie-1'})
    druga = client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                        json={'worker_ids': ids, 'session_group': 'na-tablecie-2'})

    # Przejęcie profilu to normalna sytuacja — nigdy 409.
    assert druga.status_code == 200

    with app.app_context():
        pierwsza = ProductionWorkerSession.query.filter_by(
            session_group='na-tablecie-1').one()
        assert pierwsza.ended_at is not None
        assert pierwsza.end_reason == 'replaced'
        assert pierwsza.duration_minutes >= 0

        otwarte = ProductionWorkerSession.query.filter_by(ended_at=None).all()
        assert len(otwarte) == 1
        assert otwarte[0].device_id == 'TABLET-2'


def test_stary_tablet_po_przejeciu_wraca_na_bramke(client, app):
    """
    Apka wykrywa przejęcie pollingiem /sessions/active co 60 s — endpoint
    MUSI oddać session_group: null, inaczej tablet nigdy nie wróci na ekran
    wyboru i będzie podpisywał pracę cudzym profilem.
    """
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                json={'worker_ids': ids, 'session_group': 'g1'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                json={'worker_ids': ids, 'session_group': 'g2'})

    stary = client.get('/api/mobile/sessions/active', headers=_naglowki(token1))
    nowy = client.get('/api/mobile/sessions/active', headers=_naglowki(token2))

    assert stary.status_code == 200
    assert stary.get_json()['session_group'] is None
    assert stary.get_json()['sessions'] == []
    assert nowy.get_json()['session_group'] == 'g2'


def test_przejecie_profilu_nie_rusza_obsady_innych_tabletow(client, app):
    """Domykamy sesje TEGO pracownika i TEGO urządzenia — nie całą halę."""
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    token3 = _token(app, device_id='TABLET-3')
    ids = _pracownicy(app, 2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                json={'worker_ids': [ids[0]], 'session_group': 'przejmowana'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                json={'worker_ids': [ids[1]], 'session_group': 'obca'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token3),
                json={'worker_ids': [ids[0]], 'session_group': 'przejmujaca'})

    with app.app_context():
        stan = {s.session_group: s.ended_at for s in ProductionWorkerSession.query.all()}
        assert stan['przejmowana'] is not None
        assert stan['obca'] is None            # kolega przy sąsiednim tablecie pracuje dalej
        assert stan['przejmujaca'] is None


def test_spozniony_start_nie_cofa_obsady(client, app):
    """
    Tablet-1 był offline od rana i dopiero teraz dosyła SESSION_START sprzed
    czterech godzin. Nowsza sesja na Tablecie-2 (przejęty profil) ma zostać
    nietknięta — inaczej pracownik "wraca" na tablet, przy którym nie stoi.
    """
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)

    biezaca = client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                          json={'worker_ids': ids, 'session_group': 'biezaca'})
    assert biezaca.status_code == 200

    rano = get_local_now() - timedelta(hours=4)
    spozniona = client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                            json={'worker_ids': ids, 'session_group': 'spozniona',
                                  'started_at': _iso_apki(rano)})

    # 2xx, nie 4xx — 4xx zablokowałoby kolejkę offline tabletu.
    assert spozniona.status_code == 200
    dane = spozniona.get_json()
    assert dane['superseded'] is True
    # Tablet-1 nie ma już żadnej otwartej sesji — apka pójdzie na bramkę.
    assert dane['session_group'] is None
    assert dane['sessions'] == []

    with app.app_context():
        otwarte = ProductionWorkerSession.query.filter_by(ended_at=None).all()
        assert [s.session_group for s in otwarte] == ['biezaca']

        # Spóźniony start zapisuje się jako sesja HISTORYCZNA: czas pracy sprzed
        # przejęcia nie znika z raportu, ale nie wraca na halę.
        stara = ProductionWorkerSession.query.filter_by(session_group='spozniona').one()
        assert stara.end_reason == 'replaced'
        assert stara.ended_at == otwarte[0].started_at
        assert stara.work_date == rano.date()
        assert 235 <= stara.duration_minutes <= 240


def test_spozniony_start_nie_daje_ujemnego_czasu_pracy(client, app):
    """
    Ten sam tablet, kolejka wysłana nie po kolei. Domknięcie bieżącej sesji
    czasem sprzed jej startu dawało ended_at < started_at i ujemne minuty
    w panelu "kto na hali".
    """
    token = _token(app, device_id='TABLET-1')
    ids = _pracownicy(app, 2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[0]], 'session_group': 'biezaca'})
    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': [ids[1]], 'session_group': 'z-poranka',
                            'started_at': _iso_apki(get_local_now() - timedelta(hours=3))})

    assert odp.status_code == 200
    with app.app_context():
        sesje = ProductionWorkerSession.query.all()
        assert all(s.duration_minutes >= 0 for s in sesje)
        biezaca = ProductionWorkerSession.query.filter_by(session_group='biezaca').one()
        assert biezaca.ended_at is None      # świeższa obsada zostaje na stanowisku


def test_spozniony_start_nie_zabiera_pracownikowi_biezacej_sesji(client, app):
    """
    Na tablecie wisi sesja INNEGO pracownika, nowsza niż znacznik z kolejki.
    Start jest wtedy spóźniony — i wolno mu tylko zapisać wiersz historyczny.

    Dawniej domykał przy okazji wszystkie starsze kolizje, w tym sesję
    WSKAZANEGO pracownika na jego własnym tablecie. Efekt: człowiek, który
    stał przy TABLET-A i pracował, tracił sesję, nowej nie dostawał (bo
    historyczna nie wchodzi na halę) i znikał z panelu "kto na hali".
    """
    tab_a = _token(app, device_id='TABLET-A')
    tab_b = _token(app, device_id='TABLET-B')
    beata, celina = _pracownicy(app, 2)
    t = (get_local_now() - timedelta(hours=1)).replace(microsecond=0)

    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_a),
                json={'worker_ids': [celina], 'session_group': 'A-celina',
                      'started_at': _iso_apki(t)})
    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_b),
                json={'worker_ids': [beata], 'session_group': 'B-beata',
                      'started_at': _iso_apki(t + timedelta(minutes=5))})

    # Z kolejki TABLET-B dochodzi wybór Celiny ze znacznikiem SPRZED Beaty.
    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(tab_b),
                      json={'worker_ids': [celina], 'session_group': 'B-celina',
                            'started_at': _iso_apki(t)})

    assert odp.status_code == 200
    with app.app_context():
        otwarte = {s.session_group for s
                   in ProductionWorkerSession.query.filter_by(ended_at=None).all()}
        assert otwarte == {'A-celina', 'B-beata'}, 'spóźniony start ruszył obsadę'

        historyczna = ProductionWorkerSession.query.filter_by(
            session_group='B-celina').one()
        assert historyczna.end_reason == 'replaced'
        assert historyczna.ended_at == t + timedelta(minutes=5)


def test_spozniony_start_po_zamknietej_sesji_nie_zaklada_widma(client, app):
    """
    Tablet był offline cały dzień. Zanim jego start dotarł, pracownik zdążył
    przepracować dzień na innym tablecie i wyjść — jego sesje są ZAMKNIĘTE.

    Wykrywanie spóźnienia patrzyło tylko na sesje OTWARTE, więc nie widziało
    tu żadnej kolizji i zakładało wiersz OTWARTY WSTECZ: pracownik wracał na
    panel "kto na hali" godziny po wyjściu z hali, z licznikiem lecącym dalej.
    """
    tab_a = _token(app, device_id='TABLET-A')
    tab_b = _token(app, device_id='TABLET-B')
    ids = _pracownicy(app, 1)
    t = (get_local_now() - timedelta(hours=6)).replace(microsecond=0)
    dzienna = t + timedelta(hours=2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_b),
                json={'worker_ids': ids, 'session_group': 'B-dzienna',
                      'started_at': _iso_apki(dzienna)})
    client.post('/api/mobile/sessions/end', headers=_naglowki(tab_b),
                json={'session_group': 'B-dzienna', 'reason': 'manual',
                      'ended_at': _iso_apki(get_local_now() - timedelta(hours=1))})

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(tab_a),
                      json={'worker_ids': ids, 'session_group': 'A-zalegla',
                            'started_at': _iso_apki(t)})

    assert odp.status_code == 200
    assert odp.get_json()['superseded'] is True
    with app.app_context():
        assert ProductionWorkerSession.query.filter_by(ended_at=None).count() == 0
        zalegla = ProductionWorkerSession.query.filter_by(session_group='A-zalegla').one()
        assert zalegla.ended_at == dzienna
        assert zalegla.duration_minutes == 120


def test_start_z_poprzedniej_doby_domyka_sie_na_nocnym_cutoffie(client, app):
    """
    Start z wczoraj, którego nikt nie zastąpił (tablet offline od poprzedniego
    dnia, pracownik dziś jeszcze nie siadł). Zostawiony otwarty pokazywałby
    dziś kilkanaście godzin pracy. Domykamy go tam, gdzie domknąłby go cron.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    wczoraj = (get_local_now() - timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'wczorajsza',
                            'started_at': _iso_apki(wczoraj)})

    assert odp.status_code == 200
    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.is_open is False
        assert sesja.end_reason == 'night_cutoff'
        assert sesja.ended_at == datetime.combine(wczoraj.date(), time(23, 0))
        assert sesja.work_date == wczoraj.date()


def test_spozniony_end_koryguje_czas_ale_nie_powod(client, app):
    """
    'replaced' to nasze ZGADNIĘCIE końca ("do startu następczyni"). Gdy tablet
    dosyła prawdziwą godzinę wyjścia, jest ona bliższa prawdzie — bez korekty
    raport dopisywał człowiekowi cały czas między wyjściem a przejęciem profilu.

    Powód zostaje 'replaced' — wymóg (c) zespołu mobilnego dotyczy POWODU.
    """
    tab_a = _token(app, device_id='TABLET-A')
    tab_b = _token(app, device_id='TABLET-B')
    ids = _pracownicy(app, 1)
    rano = (get_local_now() - timedelta(hours=6)).replace(microsecond=0)
    prawdziwy_koniec = rano + timedelta(hours=2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_a),
                json={'worker_ids': ids, 'session_group': 'A-rano',
                      'started_at': _iso_apki(rano)})
    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_b),
                json={'worker_ids': ids, 'session_group': 'B-po',
                      'started_at': _iso_apki(rano + timedelta(hours=4))})

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(tab_a),
                      json={'session_group': 'A-rano', 'reason': 'manual',
                            'ended_at': _iso_apki(prawdziwy_koniec)})

    assert odp.status_code == 200
    assert odp.get_json()['no_op'] is True      # domknięcia nie było, była korekta
    with app.app_context():
        sesja = ProductionWorkerSession.query.filter_by(session_group='A-rano').one()
        assert sesja.end_reason == 'replaced'
        assert sesja.ended_at == prawdziwy_koniec
        assert sesja.duration_minutes == 120


def test_spozniony_end_nie_wydluza_sesji_domknietej_przez_serwer(client, app):
    """
    Korekta działa TYLKO w dół, w oknie [started_at, obecny ended_at).
    Koniec późniejszy niż przejęcie profilu oznaczałby, że pracownik był
    w dwóch miejscach naraz — takiego cofnięcia nie robimy nigdy.
    """
    tab_a = _token(app, device_id='TABLET-A')
    tab_b = _token(app, device_id='TABLET-B')
    ids = _pracownicy(app, 1)
    rano = (get_local_now() - timedelta(hours=6)).replace(microsecond=0)
    przejecie = rano + timedelta(hours=2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_a),
                json={'worker_ids': ids, 'session_group': 'A-rano',
                      'started_at': _iso_apki(rano)})
    client.post('/api/mobile/sessions/start', headers=_naglowki(tab_b),
                json={'worker_ids': ids, 'session_group': 'B-po',
                      'started_at': _iso_apki(przejecie)})

    client.post('/api/mobile/sessions/end', headers=_naglowki(tab_a),
                json={'session_group': 'A-rano', 'reason': 'manual',
                      'ended_at': _iso_apki(rano + timedelta(hours=5))})

    with app.app_context():
        sesja = ProductionWorkerSession.query.filter_by(session_group='A-rano').one()
        assert sesja.ended_at == przejecie
        assert sesja.end_reason == 'replaced'


def test_powtorka_startu_tej_samej_grupy_nie_dubluje_sesji(client, app):
    """
    Retry z kolejki offline potrafi przyjść z innym X-Operation-Id (albo bez
    niego), więc dekorator idempotencji tego nie złapie. Drugi komplet wierszy
    dla tego samego UUID podwoiłby czas pracy w raporcie.
    """
    token = _token(app, device_id='TABLET-1')
    ids = _pracownicy(app, 1)

    pierwsza = client.post('/api/mobile/sessions/start',
                           headers=_naglowki(token, operation_id='op-1'),
                           json={'worker_ids': ids, 'session_group': 'ta-sama'})
    druga = client.post('/api/mobile/sessions/start',
                        headers=_naglowki(token, operation_id='op-2'),
                        json={'worker_ids': ids, 'session_group': 'ta-sama'})

    assert pierwsza.status_code == 200
    assert druga.status_code == 200
    assert druga.get_json()['session_group'] == 'ta-sama'
    with app.app_context():
        assert ProductionWorkerSession.query.count() == 1
        assert ProductionWorkerSession.query.one().ended_at is None


def test_akcje_z_kolejki_starego_tabletu_przechodza_po_przejeciu(client, app):
    """
    Wymóg (a) zespołu mobilnego: akcja jest przyjmowana na podstawie samego
    X-Worker-Ids, BEZ otwartej sesji. Po przejęciu profilu w kolejce starego
    tabletu leżą akcje wykonane wcześniej offline — odrzucenie ich ("brak
    otwartej sesji") wróciłoby do apki jako BLOCKED i zatrzymało halę.
    """
    _ustaw_config(app, 'WORKER_SELECTION_REQUIRED', 'true')   # bramka WŁĄCZONA
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=8)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                json={'worker_ids': ids, 'session_group': 'stara'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                json={'worker_ids': ids, 'session_group': 'nowa'})

    odp = client.post(f'/api/mobile/orders/{produkt_id}/complete',
                      headers=_naglowki(token1, worker_ids=str(ids[0])), json={})

    assert odp.status_code == 200
    with app.app_context():
        event = ProductionStationEvent.query.filter_by(station_code='gluing').one()
        atrybucja = ProductionStationEventWorker.query.one()
        assert atrybucja.worker_id == ids[0]
        assert atrybucja.event_id == event.id
        assert str(atrybucja.share) == '1.000000'
        # Sesja na TABLECIE-1 jest już domknięta, więc atrybucja nie wskazuje
        # żadnej — praca liczy się po worker_id i nie ginie.
        assert atrybucja.session_id is None
        # Domknięta sesja NIE ożywa przy spóźnionej akcji.
        stara = ProductionWorkerSession.query.filter_by(session_group='stara').one()
        assert stara.ended_at is not None


# ============================================================================
# KONTRAKT PRZEWODOWY SESJI (kształt JSON, kody, nagłówki)
#
# Pisma zespołu mobilnego z 11.08.2026 + kod klienta (crm_prod_app):
#   ActiveSessionResponseDto  — {session_group, worker_ids, started_at}
#   SyncQueueDrainer          — 2xx = Success, 4xx = wpis wypada z kolejki
#                               albo czeka na interwencję biura
#   CrmApi.getActiveSession   — @Headers("Cache-Control: no-store")
#
# Te testy pilnują KSZTAŁTU, nie logiki — logika sesji wyżej. Rozjazd kształtu
# nie wysypie apki (ignoreUnknownKeys), tylko po cichu da wartości domyślne
# z DTO: pusta lista pracowników i null zamiast grupy.
# ============================================================================

def test_active_ma_pola_kontraktu_na_poziomie_glownym(client, app):
    """
    worker_ids i started_at MUSZĄ leżeć obok session_group, nie w sessions[].
    Apka czyta wyłącznie poziom główny — zagnieżdżone widzi jako brak danych.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'kontrakt-1'})

    dane = client.get('/api/mobile/sessions/active',
                      headers=_naglowki(token)).get_json()

    assert dane['session_group'] == 'kontrakt-1'
    assert dane['worker_ids'] == ids
    assert isinstance(dane['started_at'], str) and dane['started_at']
    # Pola dodatkowe zostają — panel i diagnostyka z nich korzystają, a apka
    # je ignoruje (ignoreUnknownKeys = true w NetworkModule).
    assert dane['sessions'][0]['worker_name'] == 'Imie0 Nazwisko0'
    assert dane['station_code'] == 'gluing'
    assert dane['idle_timeout_minutes'] == 120


def test_active_bez_sesji_ma_pelny_ksztalt_a_nie_puste_cialo(client, app):
    """Brak sesji to 200 z session_group: null — nie 404 i nie {}."""
    token = _token(app)

    odp = client.get('/api/mobile/sessions/active', headers=_naglowki(token))

    assert odp.status_code == 200
    dane = odp.get_json()
    assert dane['session_group'] is None
    assert dane['worker_ids'] == []
    assert dane['started_at'] is None
    # Klucze kontraktu są ZAWSZE, także w stanie pustym — apka nie musi
    # rozróżniać "null" od "brak pola".
    assert {'session_group', 'worker_ids', 'started_at'} <= set(dane)


def test_active_nie_wolno_cachowac(client, app):
    """
    Odpowiedź "sesja nadal Twoja" przetrzymana w cache = tablet, który po
    przejęciu profilu dalej podpisuje pracę cudzym nazwiskiem. Endpoint
    celowo NIE używa cached_json (ETag + max-age=15 jak /workers).
    """
    token = _token(app)

    odp = client.get('/api/mobile/sessions/active', headers=_naglowki(token))

    assert odp.headers['Cache-Control'] == 'no-store'
    assert 'max-age' not in odp.headers['Cache-Control']
    assert odp.headers.get('ETag') is None


def test_active_oddaje_najnowsza_grupe_gdy_urzadzenie_ma_widmo(client, app):
    """
    Dane zastane: sesja otwarta sprzed wdrożenia wariantu A wisi na tym samym
    urządzeniu. get_active_sessions() sortuje rosnąco, więc branie sesje[0]
    oddawało apce grupę NAJSTARSZĄ — tablet trzymałby się widma.
    """
    token = _token(app, device_id='TABLET-1')
    ids = _pracownicy(app, 2)

    with app.app_context():
        wczoraj = get_local_now() - timedelta(hours=20)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[1], station_code='gluing', device_id='TABLET-1',
            session_group='widmo', started_at=wczoraj, last_activity_at=wczoraj,
            work_date=wczoraj.date(), source='mobile'))
        db.session.commit()

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[0]], 'session_group': 'biezaca'})

    dane = client.get('/api/mobile/sessions/active',
                      headers=_naglowki(token)).get_json()

    assert dane['session_group'] == 'biezaca'
    assert dane['worker_ids'] == [ids[0]]
    assert len(dane['sessions']) == 1      # widmo nie doklejone do listy


def test_start_zwraca_200_takze_przy_kolizji(client, app):
    """
    Kontrakt mówi 200 dla każdego przyjętego startu. Klient klasyfikuje całe
    2xx jako Success (classifySyncOutcome), więc zmiana z 201 nic mu nie robi —
    ale usuwa rozjazd z dokumentem, na którym oprze się ich test kontraktowy.
    """
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)

    pierwszy = client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                           json={'worker_ids': ids, 'session_group': 'a'})
    kolizja = client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                          json={'worker_ids': ids, 'session_group': 'b'})

    assert pierwszy.status_code == 200
    assert kolizja.status_code == 200
    # Kod HTTP nie niesie już informacji "otwarto czy nie" — niesie ją flaga.
    assert pierwszy.get_json()['superseded'] is False
    assert kolizja.get_json()['superseded'] is False
    # Start oddaje ten sam komplet pól co /sessions/active (nadzbiór).
    assert kolizja.get_json()['worker_ids'] == ids
    assert kolizja.get_json()['session_group'] == 'b'


def test_end_dla_sesji_domknietej_przez_serwer_jest_no_opem(client, app):
    """
    Spóźniony end z kolejki offline dla grupy, którą serwer domknął jako
    'replaced'. Ma być 200 i NIE MOŻE nadpisać powodu — inaczej raport
    pokazałby ręczne zakończenie zamiast przejęcia profilu.
    """
    token1 = _token(app, device_id='TABLET-1')
    token2 = _token(app, device_id='TABLET-2')
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token1),
                json={'worker_ids': ids, 'session_group': 'przejeta'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token2),
                json={'worker_ids': ids, 'session_group': 'przejmujaca'})

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token1),
                      json={'session_group': 'przejeta', 'reason': 'manual'})

    assert odp.status_code == 200
    assert odp.get_json()['no_op'] is True
    assert odp.get_json()['closed'] == 0
    with app.app_context():
        sesja = ProductionWorkerSession.query.filter_by(
            session_group='przejeta').one()
        assert sesja.end_reason == 'replaced'


def test_end_nieznanej_grupy_jest_no_opem_a_nie_404(client, app):
    """
    end potrafi dojść przed swoim startem (jedna kolejka offline, inna
    kolejność wysyłki). 404 klasyfikowało się u klienta jako Rejected: wpis
    wypadał z kolejki i liczył się jako błąd sesji.
    """
    token = _token(app)

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                      json={'session_group': 'nigdy-nie-istniala',
                            'reason': 'manual'})

    assert odp.status_code == 200
    assert odp.get_json()['no_op'] is True
    with app.app_context():
        # No-op nie zakłada wierszy "na wszelki wypadek".
        assert ProductionWorkerSession.query.count() == 0


def test_end_zwraca_cialo_json_a_nie_puste_204(client, app):
    """
    Apka deklaruje Response<Unit>, więc ciało jest jej obojętne — ale przy
    200 konwerter kotlinx MUSI mieć co sparsować. Puste ciało poszłoby jako
    SerializationException, czyli wpis wracałby do kolejki jako Transient
    i mielił się do MAX_RETRIES.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                      json={'session_group': 'g', 'reason': 'manual'})

    assert odp.status_code == 200
    assert odp.headers['Content-Type'].startswith('application/json')
    assert odp.data.strip()                     # 204 dawało tu pusty bajt-string
    assert isinstance(odp.get_json(), dict)


def test_end_powtorzony_z_tym_samym_operation_id_oddaje_200_z_cialem(client, app):
    """
    Replay idempotencji odtwarza ZAPAMIĘTANY status i ciało. Przy 204 zapisywał
    się pusty string, a przy 404 (nieznana grupa) — trwałe 404 pod tym
    X-Operation-Id, bez szansy na ponowienie.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})
    naglowki = _naglowki(token, operation_id='op-end-77')

    pierwszy = client.post('/api/mobile/sessions/end', headers=naglowki,
                           json={'session_group': 'g', 'reason': 'manual'})
    replay = client.post('/api/mobile/sessions/end', headers=naglowki,
                         json={'session_group': 'g', 'reason': 'manual'})

    assert pierwszy.status_code == 200
    assert replay.status_code == 200
    assert replay.get_json() == pierwszy.get_json()


# ============================================================================
# WALIDACJA X-Worker-Ids
# ============================================================================

def test_bez_naglowka_przy_wlaczonej_bramce_jest_400(client, app):
    token = _token(app)
    _ustaw_config(app, 'WORKER_SELECTION_REQUIRED', 'true')
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token), json={'quantity_done': 3})

    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'worker_ids_required'


def test_bez_naglowka_przy_wylaczonej_bramce_akcja_przechodzi(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token), json={'quantity_done': 3})

    assert odp.status_code == 200
    with app.app_context():
        assert ProductionStationEvent.query.count() == 1
        assert ProductionStationEventWorker.query.count() == 0


def test_pusty_naglowek_to_422_nie_kill_switch(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids=''),
                       json={'quantity_done': 3})

    assert odp.status_code == 422
    assert odp.get_json()['error'] == 'invalid_worker_ids'


def test_smieci_w_naglowku_to_422(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids='abc,def'),
                       json={'quantity_done': 3})

    assert odp.status_code == 422


def test_nieznany_pracownik_to_404(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids='999'),
                       json={'quantity_done': 3})

    assert odp.status_code == 404
    assert odp.get_json()['error'] == 'worker_not_found'


def test_dezaktywowany_pracownik_to_409(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)
    with app.app_context():
        ProductionWorker.query.get(ids[0]).deactivate()
        db.session.commit()

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids=str(ids[0])),
                       json={'quantity_done': 3})

    assert odp.status_code == 409
    assert odp.get_json()['error'] == 'worker_inactive'


# ============================================================================
# ATRYBUCJA
# ============================================================================

def test_complete_tworzy_event_z_atrybucja(client, app):
    """
    Naprawa pułapki nr 1 (§8): przed nią complete wołał wyłącznie
    complete_task(), które NIE tworzy eventu dla zamykanego stanowiska —
    praca zamknięta przyciskiem "gotowe" nie zostawiała żadnego śladu.
    """
    token = _token(app)
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, quantity=10)

    odp = client.post(f'/api/mobile/orders/{produkt_id}/complete',
                      headers=_naglowki(token, worker_ids=f'{ids[0]},{ids[1]}'),
                      json={})

    assert odp.status_code == 200
    with app.app_context():
        event = ProductionStationEvent.query.filter_by(station_code='gluing').one()
        assert event.delta == 10
        assert event.source == 'mobile'

        atrybucje = ProductionStationEventWorker.query.filter_by(event_id=event.id).all()
        assert {a.worker_id for a in atrybucje} == set(ids)
        assert all(str(a.share) == '0.500000' for a in atrybucje)
        assert sum(a.share for a in atrybucje) == 1
        # Atrybucja wskazuje sesję tylko wtedy, gdy sesja istnieje — tu jej nie ma.
        assert all(a.session_id is None for a in atrybucje)


def test_complete_wiaze_atrybucje_z_otwarta_sesja(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        atrybucja = ProductionStationEventWorker.query.one()
        assert atrybucja.session_id == sesja.id
        # Akcja produkcyjna przedłuża sesję — nie ma osobnego heartbeatu.
        assert sesja.last_activity_at >= sesja.started_at


def test_jeden_pracownik_dostaje_caly_udzial(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=_naglowki(token, worker_ids=str(ids[0])),
                 json={'quantity_done': 4})

    with app.app_context():
        atrybucja = ProductionStationEventWorker.query.one()
        assert str(atrybucja.share) == '1.000000'


def test_complete_po_odbiciu_wszystkich_sztuk_nie_dubluje_eventu(client, app):
    """delta = 0 nie tworzy eventu, więc statystyki nie liczą pracy dwa razy."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=5)

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=_naglowki(token, worker_ids=str(ids[0])),
                 json={'quantity_done': 5})
    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(station_code='gluing').all()
        assert len(eventy) == 1
        assert eventy[0].delta == 5


def test_retry_po_reaktywacji_pracownika_zapisuje_prace(client, app):
    """
    Najgroźniejszy scenariusz kolejki offline: tablet wysyła wykonaną robotę,
    dostaje 409 (pracownik dezaktywowany), admin przywraca pracownika, tablet
    ponawia z tym samym X-Operation-Id. Bez retryable_statuses dekorator
    ODTWARZAŁBY zapamiętane 409 bez wywołania handlera i praca przepadłaby,
    mimo że przyczyna błędu już nie istnieje.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]), operation_id='op-offline-1')

    with app.app_context():
        ProductionWorker.query.get(ids[0]).deactivate()
        db.session.commit()

    odrzucone = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                             headers=naglowki, json={'quantity_done': 6})
    assert odrzucone.status_code == 409

    with app.app_context():
        # 409 z walidacji profilu NIE MOŻE zostać zapamiętane
        assert ProcessedMobileOperation.query.filter_by(
            operation_id='op-offline-1').count() == 0
        ProductionWorker.query.get(ids[0]).reactivate()
        db.session.commit()

    ponowione = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                             headers=naglowki, json={'quantity_done': 6})

    assert ponowione.status_code == 200
    with app.app_context():
        assert ProductionProduct.query.get(produkt_id).quantity_done_gluing == 6
        assert ProductionStationEventWorker.query.count() == 1


def test_udana_akcja_nadal_jest_zapamietywana(client, app):
    """Kontrola: poluzowanie idempotencji nie może otworzyć drogi duplikatom."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]), operation_id='op-udane')

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=naglowki, json={'quantity_done': 4})
    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=naglowki, json={'quantity_done': 4})

    with app.app_context():
        assert ProcessedMobileOperation.query.filter_by(
            operation_id='op-udane').count() == 1
        assert ProductionStationEvent.query.filter_by(station_code='gluing').count() == 1


def test_zmiana_konfiguracji_uniewaznia_etag_katalogu(client, app):
    """
    Payload katalogu niesie ustawienia z prod_config. Gdyby ETag ich nie
    obejmował, tablet dostawałby 304 ze starym selection_required — czyli
    przestawiony kill-switch nie docierałby na halę.
    """
    token = _token(app)
    _pracownicy(app, 1)

    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    etag_przed = pierwsza.headers['ETag']

    _ustaw_config(app, 'WORKER_SELECTION_REQUIRED', 'true')

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = etag_przed
    druga = client.get('/api/mobile/workers', headers=naglowki)

    assert druga.status_code == 200, 'katalog odpowiedział 304 mimo zmiany konfiguracji'
    assert druga.headers['ETag'] != etag_przed
    assert druga.get_json()['selection_required'] is True


def test_complete_nie_cofa_sztuk_gdy_quantity_spadlo(client, app):
    """
    quantity potrafi SPAŚĆ poniżej już odbitych sztuk: doróbka zabiera sztuki
    oryginałowi, sync Baselinkera koryguje zamówienie w dół. Wcześniej
    mark_order_complete() przypisywał quantity twardo, więc kolejne "gotowe"
    dawało delta < 0 — kasowało historyczny quantity_done, wpisywało do audytu
    fałszywe "cofnięcie" i odejmowało pracownikowi sztuki w raporcie imiennym.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]))

    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.quantity = 7            # doróbka / korekta zamówienia
        db.session.commit()

    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(station_code='gluing').all()
        assert all(e.delta > 0 for e in eventy), \
            f'ujemne delty: {[e.delta for e in eventy]}'
        # Drugie "gotowe" nie ma czego dodać, więc nie powstaje nowy event
        assert len(eventy) == 1
        assert eventy[0].delta == 10
        # Historyczny dorobek stanowiska zostaje nietknięty
        assert ProductionProduct.query.get(produkt_id).quantity_done_gluing == 10


def test_complete_domyka_brakujace_sztuki_normalnie(client, app):
    """Kontrola do testu wyżej: przy niepełnym odbiciu complete dalej dolicza resztę."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]))

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=naglowki, json={'quantity_done': 4})
    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(
            station_code='gluing').order_by(ProductionStationEvent.id).all()
        assert [e.delta for e in eventy] == [4, 6]
        assert ProductionProduct.query.get(produkt_id).quantity_done_gluing == 10


def test_reject_zapisuje_pierwszego_pracownika_w_audycie(client, app):
    token = _token(app, station_code='formatting')
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, status='czeka_na_formatowanie', quantity=10)

    odp = client.post(f'/api/mobile/orders/{produkt_id}/reject',
                      headers=_naglowki(token, worker_ids=f'{ids[0]},{ids[1]}'),
                      json={'quantity': 2, 'reason_category': 'wymiary'})

    assert odp.status_code == 200
    with app.app_context():
        wpis = ProductionReworkLog.query.one()
        assert wpis.worker_id == ids[0]
        # Doróbka nie generuje eventu stanowiskowego, więc nie ma atrybucji dzielonej.
        assert ProductionStationEventWorker.query.count() == 0


def test_complete_nadal_kolejkuje_sync_baselinkera(client, app, monkeypatch):
    """
    Regresja po zmianie kolejności w mark_order_complete: hook BL musi zostać.
    Duplikuje intencję test_mobile_complete_bl_sync_queue.py, ale tutaj
    z atrybucją w tle — to ta ścieżka się zmieniła.
    """
    token = _token(app, station_code='packaging')
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, status='czeka_na_pakowanie')

    zaplanowane = []
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda numer, stanowisko: zaplanowane.append((numer, stanowisko)))

    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    assert zaplanowane == [('26/00042', 'packaging')]


# ============================================================================
# DOMYKANIE ZAPOMNIANYCH SESJI (cron)
# ============================================================================

def test_cron_domyka_sesje_po_bezczynnosci(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(hours=5),
            last_activity_at=teraz - timedelta(hours=4),
            work_date=teraz.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=teraz)

        sesja = ProductionWorkerSession.query.one()
        assert wynik['idle_timeout'] == 1
        assert sesja.end_reason == 'idle_timeout'
        # Koniec ustawiony na moment faktycznego wygaśnięcia, nie na czas
        # uruchomienia crona — opóźniony cron nie zawyża czasu pracy.
        assert sesja.ended_at == teraz - timedelta(hours=2)


def test_cron_domyka_sesje_po_nocnym_cutoffie(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        wczoraj = datetime(2026, 8, 10, 20, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=wczoraj, last_activity_at=wczoraj,
            work_date=wczoraj.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=datetime(2026, 8, 11, 6, 0))

        sesja = ProductionWorkerSession.query.one()
        assert wynik['night_cutoff'] == 1
        assert sesja.end_reason == 'night_cutoff'
        assert sesja.ended_at == datetime(2026, 8, 10, 23, 0)


def test_cron_nie_rusza_swiezych_sesji(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(minutes=30),
            last_activity_at=teraz - timedelta(minutes=5),
            work_date=teraz.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=teraz)

        assert wynik == {'night_cutoff': 0, 'idle_timeout': 0}
        assert ProductionWorkerSession.query.one().ended_at is None


def test_cron_jest_idempotentny(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(hours=5),
            last_activity_at=teraz - timedelta(hours=4),
            work_date=teraz.date()))
        db.session.commit()

        worker_service.close_stale_sessions(now=teraz)
        drugi_przebieg = worker_service.close_stale_sessions(now=teraz)

        assert drugi_przebieg == {'night_cutoff': 0, 'idle_timeout': 0}


# ============================================================================
# KATALOG — CRUD I DEZAKTYWACJA
# ============================================================================

def test_dezaktywacja_domyka_otwarte_sesje(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        worker_service.start_session(ids, 'gluing', device_id='TABLET-1',
                                     session_group='g')

        worker_service.deactivate_worker(ids[0])

        pracownik = ProductionWorker.query.get(ids[0])
        sesja = ProductionWorkerSession.query.one()
        assert pracownik.is_active is False
        assert pracownik.deactivated_at is not None
        assert sesja.end_reason == 'admin'


def test_walidacja_nieznanego_stanowiska_w_katalogu(app):
    with app.app_context():
        with pytest.raises(worker_service.WorkerError) as exc:
            worker_service.create_worker('Adam', 'Kowalski',
                                         allowed_stations=['nieistniejace'])
        assert exc.value.error_code == 'invalid_station_code'


def test_pracownik_z_ograniczeniem_stanowisk(app):
    with app.app_context():
        worker = worker_service.create_worker('Adam', 'Kowalski',
                                              allowed_stations=['gluing', 'assembly'])
        assert worker.allowed_stations == 'gluing,assembly'
        assert worker.can_work_at('gluing') is True
        assert worker.can_work_at('packaging') is False


# ============================================================================
# ZAKŁADKA PANELU CRM
# ============================================================================

def test_panel_hali_pokazuje_bezczynnosc_i_dorobek(app):
    """
    Sesja bez wskaźnika bezczynności i bez wyniku to lista zalogowanych,
    nie obraz hali (spec §7.1 wymagała "roboty w tej sesji").
    """
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, quantity=20)

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.volume_m3 = 0.4          # bez objętości kolumna m³ zawsze byłaby zerem
        pracujacy = worker_service.start_session([ids[0]], 'gluing',
                                                 device_id='TABLET-1',
                                                 session_group='pracuje')[0]
        worker_service.start_session([ids[1]], 'gluing', device_id='TABLET-2',
                                     session_group='stoi')

        produkt.set_quantity_done('gluing', 6, source='mobile',
                                  actor_worker_ids=[ids[0]],
                                  actor_session_ids={ids[0]: pracujacy.id})
        # Ten pracownik odbił coś godzinę temu i od tego czasu nic
        pracujacy.last_activity_at = get_local_now() - timedelta(minutes=75)
        db.session.commit()

        sesje = worker_service.serialize_sessions_for_panel(
            worker_service.get_active_sessions())
        wg_pracownika = {s['worker_id']: s for s in sesje}

        z_dorobkiem = wg_pracownika[ids[0]]
        assert z_dorobkiem['pieces'] == 6.0
        assert z_dorobkiem['m3'] > 0
        assert 74 <= z_dorobkiem['idle_minutes'] <= 76
        # 75 min < domyślny timeout 120 min, więc jeszcze bez alarmu
        assert z_dorobkiem['idle_over_timeout'] is False

        bez_dorobku = wg_pracownika[ids[1]]
        assert bez_dorobku['pieces'] == 0
        assert bez_dorobku['idle_minutes'] is not None


def test_panel_hali_oznacza_przekroczony_timeout(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        sesja = worker_service.start_session(ids, 'gluing', device_id='TABLET-1',
                                             session_group='dawno')[0]
        sesja.last_activity_at = get_local_now() - timedelta(minutes=200)
        db.session.commit()

        wynik = worker_service.serialize_sessions_for_panel(
            worker_service.get_active_sessions())[0]

        assert wynik['idle_minutes'] >= 199
        assert wynik['idle_over_timeout'] is True


def test_zakladka_pracownikow_renderuje_sie(app):
    """
    Renderowanie templatki zakładki — łapie błędy Jinja (literówki w polach,
    tojson na obiekcie), których testy API nie dotykają, bo zwracają JSON.
    """
    from flask import render_template
    from modules.production.routers.api.workers_api import _serialize_worker

    ids = _pracownicy(app, 1)
    with app.app_context():
        worker_service.start_session(ids, 'gluing', device_id='TABLET-1',
                                     session_group='g')
        pracownicy = [_serialize_worker(w) for w in worker_service.list_workers(True)]
        sesje = [worker_service.serialize_session_for_panel(s)
                 for s in worker_service.get_active_sessions()]
        konfiguracja = worker_service.get_worker_config()

    szablonowa_app = Flask(
        __name__,
        template_folder=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'modules', 'production', 'templates'))

    with szablonowa_app.test_request_context():
        html = render_template('components/workers-tab-content.html',
                               workers=pracownicy, active_sessions=sesje,
                               config=konfiguracja,
                               station_choices=[('gluing', 'Sklejanie'),
                                                ('packaging', 'Pakowanie')],
                               crm_users=[{'id': 1, 'label': 'admin@woodpower.pl'}])

    assert 'Imie0 Nazwisko0' in html
    assert 'IN' in html                      # kafelek z inicjałami
    assert 'TABLET-1' in html                # sekcja "kto teraz na hali"
    assert 'Dodaj pracownika' in html
    # Komunikat o kill-switchu ma być po ludzku i odsyłać do konkretnego miejsca
    # w panelu — bez nazw kluczy konfiguracyjnych, których nikt na hali nie zna.
    assert 'Wybór pracownika na tablecie jest teraz dobrowolny' in html
    assert 'Wymagaj wyboru pracownika' in html
    assert 'WORKER_SELECTION_REQUIRED' not in html
    assert 'Robota z 7 dni' in html
    assert 'Konto CRM' in html
    # Stanowiska po polsku — użytkownik panelu nie musi znać kodów z API
    assert 'Sklejanie' in html
    assert '>gluing<' not in html


def test_etykiety_stanowisk_sa_po_polsku(app):
    with app.app_context():
        assert worker_service.station_label('gluing') == 'Sklejanie'
        assert worker_service.station_label('cutting') == 'Wycinanie - mikro'
        assert worker_service.station_label('packaging') == 'Pakowanie'
        assert worker_service.station_label('sawmill') == 'Trakownia'
        # Nieznany kod nie wywraca widoku — pokazujemy go surowo
        assert worker_service.station_label('cos_nowego') == 'cos_nowego'
        assert worker_service.station_label(None) == '—'

        kody = [kod for kod, _ in worker_service.station_choices()]
        # Kolejność procesu, nie alfabetyczna
        assert kody[:3] == ['cutting', 'assembly', 'gluing']
        assert all(nazwa != kod for kod, nazwa in worker_service.station_choices())


def test_podsumowanie_roboty_liczy_udzialy_i_pomija_eventy_automatu(app):
    """
    Kolumna "robota z 7 dni" musi dzielić sztuki wg share i pomijać eventy
    stanowisk pominiętych (auto_skip/system) — inaczej sklejacz dostałby
    kredyt za formatowanie, którego nikt nie wykonał.
    """
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, quantity=10)

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.volume_m3 = 0.5
        produkt.set_quantity_done('gluing', 8, source='mobile', actor_worker_ids=ids)
        # Event automatu — z atrybucją, żeby sprawdzić, że filtr działa po
        # source, a nie po samym braku wiersza atrybucji.
        produkt.set_quantity_done('formatting', 10, source='auto_skip',
                                  actor_worker_ids=[ids[0]])
        db.session.commit()

        podsumowanie = worker_service.get_workers_activity_summary()

        assert podsumowanie[ids[0]]['pieces'] == 4.0      # 8 sztuk / 2 osoby
        assert podsumowanie[ids[1]]['pieces'] == 4.0
        assert podsumowanie[ids[0]]['m3'] == 2.0          # 0.5 m³ × 8 × 0.5
