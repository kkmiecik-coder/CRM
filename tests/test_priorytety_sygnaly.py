# -*- coding: utf-8 -*-
"""
Sygnały realtime dla tabletów stanowisk (priorytety produkcji, krok K3; spec 2026-10-04, sekcje 5.4, 6.3, 9.4):
najpierw baza, potem sygnał BEZ ładunku na kanał `station:<kod>` — zawsze po commicie, nigdy w transakcji;
`publish` nie rzuca. Tablet po sygnale woła `GET desk`.

Sygnały z hurtowej zmiany statusu i zmian z Base. (aplikacja API produkcji) sprawdza
tests/test_priorytety_wyzwalacze_produkty.py. Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import itertools
from datetime import datetime

import jwt
import pytest
import requests
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProductionDevice, ProductionOrder, ProductionProduct
from modules.production.priorytety import stale
from modules.production.priorytety.models import StationDesk
from modules.production.priorytety.services import sygnaly
from modules.production.services import mobile_api_service, realtime_service
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, ustaw  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia')

_licznik = itertools.count(1)
T0 = datetime(2026, 10, 5, 8, 0)
REALTIME = {
    'enabled': True, 'api_url': 'http://127.0.0.1:8091/api/publish', 'api_key': 'test-key',
    'token_hmac_secret': 'test-secret', 'token_ttl_seconds': 3600,
    'sse_url': 'https://crm.woodpower.pl/realtime/connection/uni_sse',
}


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def wyslane(app, monkeypatch):
    """Podgląd `realtime_service.publish`: lista zdarzeń w kolejności — ('COMMIT', None) przy commicie połączenia
    i (kanał, dane) przy każdej publikacji. Czyści plan sygnałów w `g` (fikstura `app` trzyma jeden kontekst)."""
    from flask import g
    zdarzenia = []
    app.config['REALTIME'] = dict(REALTIME)
    monkeypatch.setattr(realtime_service, 'publish',
                        lambda kanal, dane: zdarzenia.append((kanal, dane)) or True)

    def po_commicie(_polaczenie):
        zdarzenia.append(('COMMIT', None))

    event.listen(db.engine, 'commit', po_commicie)
    g.pop(sygnaly._PLAN_W_G, None)
    yield zdarzenia
    g.pop(sygnaly._PLAN_W_G, None)
    event.remove(db.engine, 'commit', po_commicie)


def _kanaly(zdarzenia):
    return [kanal for kanal, _dane in zdarzenia if kanal != 'COMMIT']


def _naglowki(stanowisko):
    device = ProductionDevice(device_id='TAB-SYG-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device)}


def _operacja(naglowki):
    return dict(naglowki, **{'X-Operation-Id': 'op-syg-%d' % next(_licznik)})


def _kafel(stanowisko, obiekt, **kolumny):
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    dane.update(kolumny)
    db.session.add(StationDesk(station_code=stanowisko, pulled_at=T0, zrodlo='kolejka', **dane))
    db.session.commit()


def _zakoncz(client, pozycja_id, naglowki, stanowisko):
    return client.post('/api/mobile/orders/%d/complete' % pozycja_id, headers=naglowki,
                       json={'station_code': stanowisko})


# ── realtime_service: kanał stanowiska ──────────────────────────────────────────────────────────────────────

def test_publish_station_signal_kanal_i_ladunek(app, wyslane):
    assert realtime_service.channel_station('gluing') == 'station:gluing'
    assert realtime_service.publish_station_signal('gluing') is True
    # sygnał bez ładunku użytkowego: tylko „coś się zmieniło na stanowisku”
    assert wyslane == [('station:gluing', {'kind': 'station', 'station': 'gluing'})]


def test_publish_station_signal_nie_rzuca_gdy_broker_padl(app, monkeypatch):
    app.config['REALTIME'] = dict(REALTIME)

    def padl(*args, **kwargs):
        raise requests.ConnectionError('broker nie odpowiada')

    monkeypatch.setattr(realtime_service.requests, 'post', padl)
    monkeypatch.setattr(realtime_service, '_alert', lambda *a, **k: None)

    assert realtime_service.publish_station_signal('gluing') is False


def test_publish_station_signal_wylaczony_false(app, monkeypatch):
    """`REALTIME.enabled=false` (także brak sekcji): publikacja zwraca False bez wyjątku i bez sieci — tablety
    wracają do odpytywania."""
    wolania = []
    monkeypatch.setattr(realtime_service.requests, 'post', lambda *a, **k: wolania.append(1))
    app.config['REALTIME'] = {'enabled': False}
    assert realtime_service.publish_station_signal('gluing') is False
    app.config.pop('REALTIME')
    assert realtime_service.publish_station_signal('gluing') is False
    assert wolania == []


# ── sygnaly.py: planowanie i wysyłka ────────────────────────────────────────────────────────────────────────

def test_zaplanuj_bez_kontekstu_zadania_nic_nie_robi(monkeypatch):
    """Serwisy (doróbka, cron) planują sygnał także w testach jednostkowych i skryptach — bez żądania nic się nie
    dzieje i nic nie pada."""
    wolania = []
    monkeypatch.setattr(realtime_service, 'publish', lambda *a: wolania.append(a) or True)
    sygnaly.zaplanuj('gluing')
    sygnaly.porzuc()
    assert sygnaly.wyslij() == []
    assert wolania == []


def test_wyslij_raz_na_kod_i_czysci_g(app, wyslane):
    with app.test_request_context('/'):
        sygnaly.zaplanuj('gluing', 'formatting')
        sygnaly.zaplanuj('gluing', None, 'nie-ma-takiego', 'sawmill')       # powtórka, brak i nieznane kody
        assert sygnaly.wyslij() == ['gluing', 'formatting']
        assert _kanaly(wyslane) == ['station:gluing', 'station:formatting']
        assert sygnaly.wyslij() == []                                       # plan wyczyszczony
        assert len(_kanaly(wyslane)) == 2


def test_wyslij_z_kodami_wprost_i_porzuc(app, wyslane):
    with app.test_request_context('/'):
        sygnaly.zaplanuj('gluing')
        sygnaly.porzuc()
        assert sygnaly.wyslij() == []
        # router panelu i `desk` wysyłają po własnym commicie, bez planowania
        sygnaly.zaplanuj('cutting')
        assert sygnaly.wyslij('packaging', 'cutting') == ['cutting', 'packaging']
    assert _kanaly(wyslane) == ['station:cutting', 'station:packaging']


def test_wyslij_nie_rzuca_gdy_publikacja_pada(app, monkeypatch):
    def awaria(kod):
        raise RuntimeError('nieoczekiwany blad publikacji')

    monkeypatch.setattr(realtime_service, 'publish_station_signal', awaria)
    with app.test_request_context('/'):
        sygnaly.zaplanuj('gluing')
        assert sygnaly.wyslij() == []


@pytest.mark.parametrize('stanowisko, kolumny, nastepne', [
    ('gluing', {}, 'formatting'),
    ('gluing', {'cut_to_size': False}, 'packaging'),
    ('edges', {'parsed_finish_type': 'olejowane'}, 'painting'),
    ('edges', {}, 'packaging'),
    ('packaging', {}, None),
])
def test_nastepne_stanowisko_po_zakonczeniu(app, stanowisko, kolumny, nastepne):
    order = zamowienie(sposob=s.KURIER, statusy=(mobile_api_service.STATION_STATUS_MAP[stanowisko],))
    pozycja = order.products[0]
    for kolumna, wartosc in kolumny.items():
        setattr(pozycja, kolumna, wartosc)
    pozycja.complete_task(stanowisko)
    assert sygnaly.nastepne_stanowisko(pozycja) == nastepne


# ── sygnały z API mobilnego (Review Focus 6) ────────────────────────────────────────────────────────────────

def test_zakoncz_sygnal_na_to_i_nastepne_stanowisko(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _operacja(_naglowki('gluing'))
    del wyslane[:]

    assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200

    assert _kanaly(wyslane) == ['station:gluing', 'station:formatting']
    assert ('station:gluing', {'kind': 'station', 'station': 'gluing'}) in wyslane
    # oba sygnały PO commicie zapisu: przed pierwszą publikacją jest commit, po niej żadnego
    pierwsza = next(i for i, (kanal, _d) in enumerate(wyslane) if kanal != 'COMMIT')
    assert ('COMMIT', None) in wyslane[:pierwsza]
    assert ('COMMIT', None) not in wyslane[pierwsza:]


def test_zakoncz_sygnal_takze_na_stanowisko_zdjetego_kafla(app, client, wyslane):
    """Uzgadnianie stołu po ZAKOŃCZ zdejmuje też zaległy kafel pozycji z innego stanowiska — to stanowisko
    dostaje sygnał razem z bieżącym i następnym."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('edges', order.products[0])              # zaległy kafel (nie powinien istnieć) — ZAKOŃCZ go sprząta
    naglowki = _operacja(_naglowki('gluing'))
    del wyslane[:]

    assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200

    assert _kanaly(wyslane) == ['station:gluing', 'station:formatting', 'station:edges']


def test_sygnal_nie_idzie_przy_rollbacku_409(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    naglowki = _naglowki('gluing')
    del wyslane[:]

    r = _zakoncz(client, order.products[0].id, _operacja(naglowki), 'gluing')
    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'
    assert _kanaly(wyslane) == []

    # następne, udane żądanie nie dosyła niczego po tamtej odmowie
    inne = zamowienie(statusy=('czeka_na_formatowanie',))
    r = client.patch('/api/mobile/orders/%d/quantity' % inne.products[0].id,
                     headers=_operacja(_naglowki('formatting')),
                     json={'station_code': 'formatting', 'quantity_done': 1})
    assert r.status_code == 200
    assert _kanaly(wyslane) == ['station:formatting']


def test_sygnal_nie_idzie_przy_powtorce_idempotentnej(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _operacja(_naglowki('gluing'))
    assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200
    del wyslane[:]

    assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200

    assert _kanaly(wyslane) == []


def test_sygnal_nie_idzie_przy_wyjatku_handlera(app, client, wyslane, monkeypatch):
    from modules.production.routers import mobile_api
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    naglowki = _naglowki('gluing')
    app.config['PROPAGATE_EXCEPTIONS'] = False

    def awaria(*args, **kwargs):
        raise RuntimeError('sztuczna awaria zapisu')

    with monkeypatch.context() as m:
        m.setattr(mobile_api, 'serialize_order', awaria)      # wyjątek PO zaplanowaniu sygnałów
        del wyslane[:]
        r = _zakoncz(client, order.products[0].id, _operacja(naglowki), 'gluing')
    assert r.status_code == 500
    assert _kanaly(wyslane) == []

    # plan przepadł razem z transakcją: następne żądanie wysyła tylko własne sygnały
    r = client.patch('/api/mobile/orders/%d/quantity' % order.products[1].id, headers=_operacja(naglowki),
                     json={'station_code': 'gluing', 'quantity_done': 1})
    assert r.status_code == 200
    assert _kanaly(wyslane) == ['station:gluing']


def test_sygnal_stanowiska_przed_hakiem_base(app, client, wyslane, monkeypatch):
    """K3-poprawka-1 (D3 z przeglądu K3): sygnał stanowiska idzie tuż po commicie, PRZED hakiem statusu Base. —
    pierwsza próba `setOrderStatus` jest synchronicznym HTTP, na które drugi tablet nie ma czekać."""
    monkeypatch.setattr('modules.production.services.baselinker_status_sync.flush_pending_syncs',
                        lambda: wyslane.append(('BASE', None)))
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _operacja(_naglowki('gluing'))
    del wyslane[:]

    assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200

    kolejnosc = [kanal for kanal, _dane in wyslane]
    assert kolejnosc.count('BASE') == 1
    assert (kolejnosc.index('COMMIT') < kolejnosc.index('station:gluing') < kolejnosc.index('station:formatting')
            < kolejnosc.index('BASE'))


def test_blad_haka_base_nie_gubi_sygnalu(app, client, wyslane, monkeypatch):
    def awaria():
        raise RuntimeError('Base. nie odpowiada')

    monkeypatch.setattr('modules.production.services.baselinker_status_sync.flush_pending_syncs', awaria)
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    del wyslane[:]

    assert _zakoncz(client, order.products[0].id, _operacja(_naglowki('gluing')), 'gluing').status_code == 200
    assert _kanaly(wyslane) == ['station:gluing', 'station:formatting']


def test_licznik_sygnal_na_to_stanowisko(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _operacja(_naglowki('gluing'))
    del wyslane[:]

    r = client.patch('/api/mobile/orders/%d/quantity' % order.products[0].id, headers=naglowki,
                     json={'station_code': 'gluing', 'quantity_done': 1})

    assert r.status_code == 200
    assert _kanaly(wyslane) == ['station:gluing']
    assert wyslane[0] == ('COMMIT', None) or ('COMMIT', None) in wyslane[:wyslane.index(
        ('station:gluing', {'kind': 'station', 'station': 'gluing'}))]


def test_postpone_sygnal(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    naglowki = _operacja(_naglowki('gluing'))
    del wyslane[:]

    r = client.post('/api/mobile/orders/%d/postpone' % order.products[0].id, headers=naglowki,
                    json={'station_code': 'gluing', 'zakres': 'pozycja', 'powod': 'brak_materialu'})

    assert r.status_code == 200
    assert _kanaly(wyslane) == ['station:gluing']
    assert wyslane[-2:] == [('COMMIT', None), ('station:gluing', {'kind': 'station', 'station': 'gluing'})]


def test_desk_sygnal_tylko_gdy_dopelnil(app, client, wyslane):
    """Pobranie na stół budzi drugi tablet stanowiska; `desk`, który niczego nie dołożył, nie wysyła nic."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    ustaw(stale.klucz_tryb('gluing'), 'stol')         # dopełnia tylko tryb `stol` (K3-poprawka-2)
    naglowki = _naglowki('gluing')
    del wyslane[:]

    assert client.get('/api/mobile/stations/gluing/desk', headers=naglowki).status_code == 200
    assert _kanaly(wyslane) == ['station:gluing']
    indeks = wyslane.index(('station:gluing', {'kind': 'station', 'station': 'gluing'}))
    assert wyslane[indeks - 1] == ('COMMIT', None)                 # zaraz po commicie dopełnienia

    del wyslane[:]
    assert client.get('/api/mobile/stations/gluing/desk', headers=naglowki).status_code == 200
    assert _kanaly(wyslane) == []


def test_dorobka_sygnal_na_stanowisko_powrotu(app, client, wyslane):
    """Doróbka z Formatowania wraca na początek procesu (Wycinanie) i staje tam na początku kolejki: sygnał na
    stanowisko odrzucające i stanowisko powrotu."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    naglowki = _operacja(_naglowki('formatting'))
    del wyslane[:]

    r = client.post('/api/mobile/orders/%d/reject' % order.products[0].id, headers=naglowki,
                    json={'station_code': 'formatting', 'quantity': 1, 'reason_category': 'wymiary'})

    assert r.status_code == 200, r.get_json()
    assert _kanaly(wyslane) == ['station:formatting', 'station:cutting']
    pierwsza = next(i for i, (kanal, _d) in enumerate(wyslane) if kanal != 'COMMIT')
    assert ('COMMIT', None) in wyslane[:pierwsza]


def test_dorobka_odrzucona_bez_sygnalu(app, client, wyslane):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _operacja(_naglowki('formatting'))
    del wyslane[:]

    r = client.post('/api/mobile/orders/%d/reject' % order.products[0].id, headers=naglowki,
                    json={'station_code': 'formatting', 'quantity': 1, 'reason_category': 'wymiary'})

    assert r.status_code == 409
    assert _kanaly(wyslane) == []


def test_cron_sygnal_po_commicie_fazy_1(app, client, wyslane, monkeypatch):
    """Cron przenosi osierocone pozycje do pakowania: sygnał na Pakowanie (doszła praca) i na stanowiska, z których
    zdjęto kafel — po commicie pierwszej fazy."""
    from modules.production.logistics.services import bl_sync, geocoding
    from modules.production.priorytety.services import kolejka
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': True})
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_logistyke'))
    _kafel('edges', order.products[1])
    del wyslane[:]

    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})

    assert r.status_code == 200 and r.get_json()['przeniesione_z_logistyki'] == 1
    assert sorted(_kanaly(wyslane)) == ['station:edges', 'station:packaging']
    pierwsza = next(i for i, (kanal, _d) in enumerate(wyslane) if kanal != 'COMMIT')
    assert wyslane[pierwsza - 1] == ('COMMIT', None)

    # nic do przeniesienia — bez sygnału
    del wyslane[:]
    assert client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA}).status_code == 200
    assert _kanaly(wyslane) == []


# ── GET /api/mobile/realtime-token ──────────────────────────────────────────────────────────────────────────

def test_realtime_token_kanaly_stanowiska(app, client):
    app.config['REALTIME'] = dict(REALTIME)
    naglowki = _naglowki('edges')
    device_id = ProductionDevice.query.order_by(ProductionDevice.id.desc()).first().device_id

    r = client.get('/api/mobile/realtime-token', headers=naglowki)

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert set(dane) == {'enabled', 'token', 'ttl_seconds', 'sse_url', 'channels'}
    assert dane['enabled'] is True and dane['ttl_seconds'] == 3600
    assert dane['sse_url'] == REALTIME['sse_url']
    # tablet Krawędzi obsługuje też Lakiernię (grupa stanowisk) — oba kanały w tokenie
    assert dane['channels'] == ['station:edges', 'station:painting']
    claims = jwt.decode(dane['token'], 'test-secret', algorithms=['HS256'])
    assert claims['channels'] == ['station:edges', 'station:painting']
    assert claims['sub'] == 'device:' + device_id


def test_realtime_token_jedno_stanowisko(app, client):
    app.config['REALTIME'] = dict(REALTIME)
    r = client.get('/api/mobile/realtime-token', headers=_naglowki('gluing'))
    assert r.status_code == 200 and r.get_json()['channels'] == ['station:gluing']


def test_realtime_token_503_gdy_wylaczony(app, client):
    """Realtime wyłączony: 503 — appka zostaje przy odpytywaniu (30 s przy pustym stole, 5 min przy pełnym)."""
    naglowki = _naglowki('gluing')
    for konfiguracja in ({'enabled': False}, None):
        if konfiguracja is None:
            app.config.pop('REALTIME', None)
        else:
            app.config['REALTIME'] = konfiguracja
        r = client.get('/api/mobile/realtime-token', headers=naglowki)
        assert r.status_code == 503
        assert r.get_json() == {'enabled': False, 'reason': 'realtime disabled'}


def test_realtime_token_503_bez_sekretu(app, client):
    app.config['REALTIME'] = dict(REALTIME, token_hmac_secret='')
    r = client.get('/api/mobile/realtime-token', headers=_naglowki('gluing'))
    assert r.status_code == 503
    assert r.get_json() == {'enabled': False, 'reason': 'misconfigured'}


def test_realtime_token_404_trakownia(app, client):
    """Tablet spoza stanowisk produktu (trakownia, weryfikacja, dostawa) nie ma stołu ani kanału."""
    app.config['REALTIME'] = dict(REALTIME)
    for stanowisko in ('sawmill', 'verification'):
        r = client.get('/api/mobile/realtime-token', headers=_naglowki(stanowisko))
        assert r.status_code == 404 and r.get_json()['error'] == 'unknown_station', stanowisko


def test_realtime_token_wymaga_tokena_urzadzenia(app, client):
    app.config['REALTIME'] = dict(REALTIME)
    assert client.get('/api/mobile/realtime-token').status_code == 401


def test_trzy_koncowki_mobilne_priorytetow_sa_w_aplikacji(app):
    reguly = {(regula.rule, tuple(sorted(regula.methods - {'HEAD', 'OPTIONS'}))) for regula in app.url_map.iter_rules()}
    assert ('/api/mobile/stations/<station_code>/desk', ('GET',)) in reguly
    assert ('/api/mobile/orders/<int:order_id>/postpone', ('POST',)) in reguly
    assert ('/api/mobile/realtime-token', ('GET',)) in reguly


# ── dekorator with_idempotency: plan sygnałów a rollback ────────────────────────────────────────────────────

@pytest.mark.parametrize('status', [409, 400, 500])
def test_dekorator_porzuca_plan_przy_rollbacku(app, wyslane, status):
    """Handler zaplanował sygnał, a potem odpowiedział kodem do ponowienia albo 5xx: dekorator robi rollback
    i PORZUCA plan — sygnał nie może pójść ani teraz, ani przy następnym żądaniu."""
    from flask import jsonify

    @mobile_api_service.with_idempotency(retryable_statuses={400, 403, 404, 409})
    def handler():
        sygnaly.zaplanuj('gluing')
        return jsonify({'error': 'odmowa'}), status

    with app.test_request_context('/api/mobile/orders/1/complete', headers={'X-Operation-Id': 'op-syg-x%d' % status}):
        _odpowiedz, kod = handler()
        assert kod == status
        assert sygnaly.wyslij() == []
    assert _kanaly(wyslane) == []


def test_dekorator_wysyla_plan_po_commicie(app, wyslane):
    from flask import jsonify

    @mobile_api_service.with_idempotency(retryable_statuses={409})
    def handler():
        sygnaly.zaplanuj('gluing', 'formatting')
        return jsonify({'ok': True}), 200

    del wyslane[:]
    with app.test_request_context('/api/mobile/orders/1/complete', headers={'X-Operation-Id': 'op-syg-ok'}):
        _odpowiedz, kod = handler()
    assert kod == 200
    assert wyslane[-3:] == [('COMMIT', None), ('station:gluing', {'kind': 'station', 'station': 'gluing'}),
                            ('station:formatting', {'kind': 'station', 'station': 'formatting'})]
