# -*- coding: utf-8 -*-
"""POST /api/mobile/manager/products/status — zmiana statusu pozycji z tabletu kierownika (kontrakt §6).

Ta sama operacja co hurtowa zmiana statusu w panelu (serwis `zmiana_statusu`), z kierownikiem jako aktorem.
Testy jadą na SQLite, więc NIE sprawdzają blokad MySQL — kolejność blokad pilnuje test na zapisanych zapytaniach."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.production.kierownik.services import biala_lista
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import (
    ProcessedMobileOperation, ProductionOrder, ProductionProduct, ProductionProductEvent, ProductionWorkerSession,
    get_local_now,
)
from modules.production.priorytety.models import StationDesk
from modules.production.services import zmiana_statusu
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien
from tests.dostawa_pomocnicze import trasa
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import DZIS_TESTOW, app, client, zamowienie  # noqa: F401

URL = API + '/products/status'
ZAMKNIETE = datetime(2026, 9, 20, 12, 0, 0)


def test_trasa_jest_na_liscie_endpointow():
    assert ('POST', '/products/status') in ENDPOINTY_KIEROWNIKA


@pytest.fixture()
def tablet(app, monkeypatch):
    # Audyt zdarzeń pozycji (listener before_flush) działa tylko przy istniejącej tabeli: zakładamy ją w bazie
    # testu i włączamy flagę „tabela jest” na czas testu (monkeypatch przywraca ją po teście).
    from modules.production.services import product_events
    ProductionProductEvent.__table__.create(bind=db.engine, checkfirst=True)
    monkeypatch.setattr(product_events, '_TABLE_AVAILABLE', True)
    return tablet_kierownika()


@pytest.fixture()
def sygnaly(monkeypatch):
    """Sygnały stanowisk wysłane po commicie: lista kodów w kolejności publikacji."""
    from modules.production.services import realtime_service
    wyslane = []
    monkeypatch.setattr(realtime_service, 'publish_station_signal', lambda kod: wyslane.append(kod) or True)
    return wyslane


@pytest.fixture()
def utrwalenia(monkeypatch):
    """Przeliczenia rang wykonane po commicie (`kolejka.utrwal`): liczba wywołań."""
    from modules.production.priorytety.services import kolejka
    wywolania = []
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: wywolania.append(1) or {'success': True})
    return wywolania


def _wyslij(client, tablet, cialo, op_id=None, **naglowki_dodatkowe):
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik, op_id=op_id)
    naglowek.update(naglowki_dodatkowe)
    return client.post(URL, json=cialo, headers=naglowek)


def _zmien(client, tablet, ids, status, op_id=None):
    return _wyslij(client, tablet, {'product_ids': ids, 'status': status}, op_id=op_id)


def _ok(r):
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _status(product_id):
    db.session.rollback()
    return db.session.get(ProductionProduct, product_id).current_status


def _id_pozycji(zam):
    return [p.id for p in sorted(zam.products, key=lambda p: p.id)]


def _na_trasie_w_drodze(*zamowienia_):
    """Trasa w drodze z przystankami podanych zamówień (zamówienie nie może wracać do produkcji)."""
    return trasa(list(zamowienia_), status='w_trasie', od=DZIS_TESTOW)


# --- skutki jak w panelu ------------------------------------------------------------------------------------------

def test_zmiana_statusu_skutki_jak_web(client, tablet, sygnaly, utrwalenia):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00701', bl_id=910701)
    (pid,) = _id_pozycji(z)
    db.session.add(StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id))
    db.session.commit()

    odp = _ok(_zmien(client, tablet, [pid], 'wstrzymane'))

    assert odp['message'] == u'Zmieniono status 1 pozycji.'
    assert (odp['zmienione'], odp['odmowione'], odp['odmowy'], odp['nieznane']) == (1, 0, [], [])
    assert odp['zdjete_ze_stolow'] == ['formatting']
    assert odp['pozycje'] == [{'product_id': pid, 'order_id': z.id, 'status': 'wstrzymane',
                               'status_etykieta': 'Wstrzymane'}]
    assert _status(pid) == 'wstrzymane'
    assert StationDesk.query.filter_by(order_id=z.id).count() == 0       # kafel zszedł ze stołu w tej transakcji
    assert sygnaly == ['formatting']                                      # plan sygnałów wykonany po commicie
    assert utrwalenia == [1]                                              # rangi przeliczone raz, po commicie
    assert biala_lista.zakazane_w(odp) == []


def test_sygnal_dla_stanowiska_ktoremu_doszla_praca(client, tablet, sygnaly):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00702', bl_id=910702)
    (pid,) = _id_pozycji(z)

    odp = _ok(_zmien(client, tablet, [pid], 'czeka_na_krawedzie'))

    assert odp['zdjete_ze_stolow'] == []
    assert sygnaly == ['edges']
    assert odp['pozycje'][0]['status_etykieta'] == u'Czeka na krawędzie'


def test_aktor_kierownik_w_historii(client, tablet):
    device, kierownik = tablet
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00703', bl_id=910703)
    (pid,) = _id_pozycji(z)

    _ok(_zmien(client, tablet, [pid], 'wstrzymane'))

    db.session.rollback()
    zdarzenia = ProductionProductEvent.query.filter_by(production_item_id=pid, event_type='status_change').all()
    assert len(zdarzenia) == 1
    assert (zdarzenia[0].old_value, zdarzenia[0].new_value) == ('czeka_na_formatowanie', 'wstrzymane')
    assert (zdarzenia[0].worker_id, zdarzenia[0].actor_type, zdarzenia[0].source) == (kierownik.id, 'worker', 'mobile')
    assert zdarzenia[0].device_id == device.device_id


def test_zapis_przedluza_sesje_kierownika(client, tablet):
    device, kierownik = tablet
    dawniej = get_local_now() - timedelta(minutes=40)
    sesja = ProductionWorkerSession(worker_id=kierownik.id, station_code='manager', device_id=device.device_id,
                                    session_group='grupa-1', started_at=dawniej, last_activity_at=dawniej,
                                    work_date=dawniej.date())
    db.session.add(sesja)
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00704', bl_id=910704)
    db.session.commit()
    sesja_id = sesja.id

    _ok(_zmien(client, tablet, _id_pozycji(z), 'wstrzymane'))

    db.session.rollback()
    assert db.session.get(ProductionWorkerSession, sesja_id).last_activity_at > dawniej + timedelta(minutes=30)


def test_pozycja_z_archiwum_wraca_do_active(client, tablet):
    """Review Focus 1: zamówienie zamknięte w Logistyce, pozycja cofnięta do pakowania → znów na liście bieżących."""
    device, kierownik = tablet
    z = zamowienie(statusy=('spakowane',), numer_wewnetrzny='26/00705', bl_id=910705, logistics_closed_at=ZAMKNIETE)
    (pid,) = _id_pozycji(z)

    def numery(widok):
        r = client.get(API + '/orders', query_string={'view': widok}, headers=naglowki(device, kierownik))
        assert r.status_code == 200, r.get_data()[:300]
        return [o['numer'] for o in r.get_json()['zamowienia']]

    assert numery('active') == [] and numery('archive') == ['26/00705']

    _ok(_zmien(client, tablet, [pid], 'czeka_na_pakowanie'))

    assert numery('active') == ['26/00705'] and numery('archive') == []


def test_nie_wysyla_do_base(client, tablet, monkeypatch):
    from modules.production.logistics.services import bl_sync
    from modules.production.services import baselinker_status_sync
    wywolania = []
    for nazwa in ('_process_pending', '_call_set_order_status', '_schedule_retry'):
        monkeypatch.setattr(baselinker_status_sync, nazwa, lambda *a, _n=nazwa, **k: wywolania.append(_n))
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: wywolania.append('dopychacz') or True)
    z = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'), numer_wewnetrzny='26/00706',
                   bl_id=910706)

    for status in ('spakowane', 'anulowane', 'wstrzymane', 'czeka_na_pakowanie'):
        _ok(_zmien(client, tablet, _id_pozycji(z), status))

    assert wywolania == []
    db.session.rollback()
    assert db.session.get(ProductionOrder, z.id).bl_status_pending_id is None


# --- walidacja ---------------------------------------------------------------------------------------------------

def test_status_niedozwolony_400_z_lista(client, tablet):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00707', bl_id=910707)
    (pid,) = _id_pozycji(z)

    for status in ('zweryfikowane', 'zaladowane', 'czeka_na_logistyke', 'zupelnie_nieistniejacy'):
        r = _zmien(client, tablet, [pid], status, op_id='op-status-' + status)
        assert r.status_code == 400, (status, r.get_data()[:300])
        dane = r.get_json()
        assert dane['error'] == 'status_niedozwolony' and dane['message']
        assert dane['dozwolone'] == sorted(zmiana_statusu.DOZWOLONE_STATUSY)
        assert 'wstrzymane' in dane['dozwolone'] and 'zweryfikowane' not in dane['dozwolone']
    assert _status(pid) == 'czeka_na_formatowanie'
    assert ProcessedMobileOperation.query.count() == 0           # 4xx niezapamiętane pod X-Operation-Id


@pytest.mark.parametrize('cialo', [
    None,
    {},
    {'status': 'wstrzymane'},
    {'product_ids': [], 'status': 'wstrzymane'},
    {'product_ids': list(range(1, 502)), 'status': 'wstrzymane'},
    {'product_ids': 5, 'status': 'wstrzymane'},
    {'product_ids': '5', 'status': 'wstrzymane'},
    {'product_ids': ['a'], 'status': 'wstrzymane'},
    {'product_ids': [1, 2.5], 'status': 'wstrzymane'},
    {'product_ids': [True], 'status': 'wstrzymane'},
    {'product_ids': [None], 'status': 'wstrzymane'},
    {'product_ids': [1]},
    {'product_ids': [1], 'status': 5},
    [1, 2],
])
def test_dane_niepoprawne(client, tablet, cialo):
    r = _wyslij(client, tablet, cialo)
    assert r.status_code == 400, r.get_data()[:300]
    assert r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']
    assert ProcessedMobileOperation.query.count() == 0


def test_powtorzenia_id_sa_usuwane(client, tablet):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00708', bl_id=910708)
    (pid,) = _id_pozycji(z)
    odp = _ok(_zmien(client, tablet, [pid] * 600, 'wstrzymane'))      # po usunięciu powtórzeń: jedno id
    assert odp['zmienione'] == 1 and len(odp['pozycje']) == 1


def test_brak_operation_id_400(client, tablet):
    device, kierownik = tablet
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00709', bl_id=910709)
    naglowek = naglowki(device, kierownik)
    del naglowek['X-Operation-Id']

    r = client.post(URL, json={'product_ids': _id_pozycji(z), 'status': 'wstrzymane'}, headers=naglowek)

    assert r.status_code == 400 and r.get_json()['error'] == 'missing_operation_id'
    assert _status(_id_pozycji(z)[0]) == 'czeka_na_formatowanie'


# --- pozycje nieznane ----------------------------------------------------------------------------------------------

def test_wszystkie_nieznane_404(client, tablet):
    r = _zmien(client, tablet, [999999, 999998], 'wstrzymane')
    assert r.status_code == 404
    assert r.get_json()['error'] == 'pozycje_nieznane' and r.get_json()['message']
    assert ProcessedMobileOperation.query.count() == 0


def test_czesciowo_nieznane_200(client, tablet):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00710', bl_id=910710)
    (pid,) = _id_pozycji(z)

    odp = _ok(_zmien(client, tablet, [pid, 999999], 'wstrzymane'))

    assert odp['nieznane'] == [999999]
    assert odp['zmienione'] == 1 and [p['product_id'] for p in odp['pozycje']] == [pid]


# --- trasa w drodze ------------------------------------------------------------------------------------------------

def test_trasa_w_drodze_409_bez_zapisu(client, tablet, sygnaly, utrwalenia):
    z = zamowienie(statusy=('zaladowane', 'zaladowane'), numer_wewnetrzny='26/00711', bl_id=910711)
    ids = _id_pozycji(z)
    _na_trasie_w_drodze(z)

    r = _zmien(client, tablet, ids, 'czeka_na_pakowanie', op_id='op-409')

    assert r.status_code == 409, r.get_data()[:300]
    dane = r.get_json()
    assert dane['error'] == 'trasa_w_drodze' and '26/00711' in dane['message']
    assert [_status(i) for i in ids] == ['zaladowane', 'zaladowane']
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-409').count() == 0    # niezapamiętane
    assert sygnaly == [] and utrwalenia == []                                              # nic nie zaplanowane

    # Ponowienie z tym samym op_id po zdjęciu zamówienia z trasy to nowa decyzja na nowym stanie.
    Route.query.delete()
    RouteStop.query.delete()
    db.session.commit()
    assert _ok(_zmien(client, tablet, ids, 'czeka_na_pakowanie', op_id='op-409'))['zmienione'] == 2


def test_anulowanie_na_trasie_w_drodze_przechodzi(client, tablet):
    """Dostawa obsługuje zamówienie anulowane, więc anulowanie nie jest powrotem do produkcji (kontrakt §6)."""
    z = zamowienie(statusy=('zaladowane',), numer_wewnetrzny='26/00712', bl_id=910712)
    ids = _id_pozycji(z)
    _na_trasie_w_drodze(z)

    odp = _ok(_zmien(client, tablet, ids, 'anulowane'))

    assert odp['zmienione'] == 1 and odp['odmowione'] == 0


def test_czesciowa_odmowa_200(client, tablet, sygnaly, utrwalenia):
    na_trasie = zamowienie(statusy=('zaladowane', 'zaladowane'), numer_wewnetrzny='26/00713', bl_id=910713)
    wolne = zamowienie(statusy=('spakowane',), numer_wewnetrzny='26/00714', bl_id=910714)
    ids_trasa, (id_wolnej,) = _id_pozycji(na_trasie), _id_pozycji(wolne)
    _na_trasie_w_drodze(na_trasie)

    odp = _ok(_zmien(client, tablet, ids_trasa + [id_wolnej], 'czeka_na_pakowanie'))

    assert (odp['zmienione'], odp['odmowione']) == (1, 2)
    assert len(odp['odmowy']) == 1 and '26/00713' in odp['odmowy'][0]          # po jednym zdaniu na zamówienie
    assert odp['message'] == u'Zmieniono status 1 pozycji. Odmówiono: 2.'
    stan = {p['product_id']: (p['order_id'], p['status']) for p in odp['pozycje']}
    assert stan == {ids_trasa[0]: (na_trasie.id, 'zaladowane'), ids_trasa[1]: (na_trasie.id, 'zaladowane'),
                    id_wolnej: (wolne.id, 'czeka_na_pakowanie')}               # odmówione z dawnym statusem
    assert _status(ids_trasa[0]) == 'zaladowane' and _status(id_wolnej) == 'czeka_na_pakowanie'
    assert sygnaly == ['packaging'] and utrwalenia == [1]


# --- idempotencja i ponowienie po zakleszczeniu --------------------------------------------------------------------

def test_idempotencja_ta_sama_odpowiedz(client, tablet, monkeypatch):
    """Review Focus 2: drugie żądanie z tym samym X-Operation-Id dostaje zapamiętaną odpowiedź, bez ponownego zapisu."""
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00715', bl_id=910715)
    (pid,) = _id_pozycji(z)
    wywolania = []
    oryginal = zmiana_statusu.zmien_status
    monkeypatch.setattr(zmiana_statusu, 'zmien_status', lambda *a, **k: wywolania.append(1) or oryginal(*a, **k))

    pierwsza = _zmien(client, tablet, [pid], 'wstrzymane', op_id='op-idem')
    druga = _zmien(client, tablet, [pid], 'wstrzymane', op_id='op-idem')

    assert pierwsza.status_code == druga.status_code == 200
    assert pierwsza.get_json() == druga.get_json()
    assert len(wywolania) == 1
    db.session.rollback()
    assert ProductionProductEvent.query.filter_by(production_item_id=pid, event_type='status_change').count() == 1
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-idem').count() == 1


def _blad_mysql(kod):
    return OperationalError('UPDATE prod_products SET ...', {}, Exception(kod, 'Deadlock found when trying to get lock'))


def _scenariusz(monkeypatch, wyniki):
    """
    Podmienia `zmiana_statusu.zmien_status`: n-te wywołanie wykonuje PRAWDZIWY zapis (jego zmiany są w sesji, więc
    rollback musi je cofnąć) i rzuca `wyniki[n]`, gdy to wyjątek; `wyniki[n]` będące funkcją bez argumentów zastępuje
    zapis cudzą, zatwierdzoną zmianą i rzuca 1213. Poza listą działa normalnie. Zwraca listę prób.
    """
    oryginal = zmiana_statusu.zmien_status
    proby = []

    def falszywa(*args, **kwargs):
        numer = len(proby)
        proby.append(numer)
        wynik = wyniki[numer] if numer < len(wyniki) else None
        if callable(wynik) and not isinstance(wynik, Exception):
            wynik()
            raise _blad_mysql(1213)
        odpowiedz = oryginal(*args, **kwargs)
        db.session.flush()
        if wynik is not None:
            raise wynik
        return odpowiedz

    monkeypatch.setattr(zmiana_statusu, 'zmien_status', falszywa)
    return proby


@pytest.fixture()
def bez_propagacji_wyjatkow(app):
    """Błąd, którego zapis nie obsłuży, ma dać 500 jak na serwerze (kontener testów ma FLASK_DEBUG=1)."""
    app.config['PROPAGATE_EXCEPTIONS'] = False


def test_ponowienie_1213(client, tablet, monkeypatch, sygnaly, utrwalenia):
    """1213 po prawdziwym zapisie pierwszej próby → jedno ponowienie wewnątrz handlera: 200, jeden skutek, jeden
    wpis idempotencji, sygnały i przeliczenie tylko z drugiej próby."""
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00716', bl_id=910716)
    (pid,) = _id_pozycji(z)
    db.session.add(StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id))
    db.session.commit()
    proby = _scenariusz(monkeypatch, [_blad_mysql(1213)])

    odp = _ok(_zmien(client, tablet, [pid], 'wstrzymane', op_id='op-1213'))

    assert len(proby) == 2
    assert odp['zmienione'] == 1 and odp['zdjete_ze_stolow'] == ['formatting']
    assert _status(pid) == 'wstrzymane'
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-1213').count() == 1
    assert ProductionProductEvent.query.filter_by(production_item_id=pid, event_type='status_change').count() == 1
    assert sygnaly == ['formatting'] and utrwalenia == [1]


def test_ponowienie_decyduje_na_nowym_stanie(client, tablet, monkeypatch, sygnaly, utrwalenia):
    """Między próbami ktoś ładuje zamówienie na trasę w drodze: druga próba widzi to i odmawia (409 zamiast zapisu
    na starej decyzji); odpowiedź niezapamiętana, plan sygnałów i przeliczenia z pierwszej próby nie wychodzi."""
    z = zamowienie(statusy=('zaladowane',), numer_wewnetrzny='26/00717', bl_id=910717)
    (pid,) = _id_pozycji(z)

    def cudzy_zapis():
        db.session.rollback()
        _na_trasie_w_drodze(z)

    proby = _scenariusz(monkeypatch, [cudzy_zapis])

    r = _zmien(client, tablet, [pid], 'czeka_na_pakowanie', op_id='op-nowy-stan')

    assert len(proby) == 2
    assert r.status_code == 409 and r.get_json()['error'] == 'trasa_w_drodze'
    assert _status(pid) == 'zaladowane'
    assert ProcessedMobileOperation.query.count() == 0
    assert sygnaly == [] and utrwalenia == []


def test_ponowienie_porzuca_plan_pierwszej_proby(client, tablet, monkeypatch, sygnaly, utrwalenia):
    """Pierwsza próba zdążyła zaplanować sygnały i przeliczenie, a potem 1213 na `flush` handlera: oba plany muszą
    przepaść jawnie (`sygnaly.porzuc`, `kolejka.porzuc_zaplanowane`), a druga próba planuje od nowa."""
    from modules.production.priorytety.services import kolejka, sygnaly as plan_sygnalow
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00718', bl_id=910718)
    (pid,) = _id_pozycji(z)
    db.session.add(StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id))
    db.session.commit()
    stan, porzucone = {'zaplanowano': False, 'rzucono': False}, []
    for modul, nazwa in ((plan_sygnalow, 'porzuc'), (kolejka, 'porzuc_zaplanowane')):
        oryginal = getattr(modul, nazwa)
        monkeypatch.setattr(modul, nazwa, lambda _o=oryginal, _n=nazwa: porzucone.append(_n) or _o())
    oryginal_plan = kolejka.zaplanuj_po_commicie
    monkeypatch.setattr(kolejka, 'zaplanuj_po_commicie',
                        lambda: stan.update(zaplanowano=True) or oryginal_plan())
    oryginal_flush = db.session.flush

    def flush(*a, **k):
        # Pierwszy flush PO zaplanowaniu (flush handlera) rzuca zakleszczenie; kolejne działają.
        if stan['zaplanowano'] and not stan['rzucono']:
            stan['rzucono'] = True
            raise _blad_mysql(1213)
        return oryginal_flush(*a, **k)

    monkeypatch.setattr(db.session, 'flush', flush)

    odp = _ok(_zmien(client, tablet, [pid], 'wstrzymane'))

    assert stan['rzucono'] and odp['zmienione'] == 1
    assert sorted(porzucone) == ['porzuc', 'porzuc_zaplanowane']
    assert sygnaly == ['formatting'] and utrwalenia == [1]


def test_drugie_1213_to_500_bez_zapisu(client, tablet, monkeypatch, bez_propagacji_wyjatkow, sygnaly, utrwalenia):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00719', bl_id=910719)
    (pid,) = _id_pozycji(z)
    proby = _scenariusz(monkeypatch, [_blad_mysql(1213), _blad_mysql(1213)])

    r = _zmien(client, tablet, [pid], 'wstrzymane', op_id='op-2x1213')

    assert r.status_code == 500 and len(proby) == 2
    assert _status(pid) == 'czeka_na_formatowanie'
    assert ProcessedMobileOperation.query.count() == 0
    assert sygnaly == [] and utrwalenia == []


def test_inny_kod_bazy_bez_ponowienia(client, tablet, monkeypatch, bez_propagacji_wyjatkow):
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00720', bl_id=910720)
    (pid,) = _id_pozycji(z)
    proby = _scenariusz(monkeypatch, [_blad_mysql(1205)])

    r = _zmien(client, tablet, [pid], 'wstrzymane', op_id='op-1205')

    assert r.status_code == 500 and len(proby) == 1
    assert _status(pid) == 'czeka_na_formatowanie'
    assert ProcessedMobileOperation.query.count() == 0


# --- kolejność blokad ----------------------------------------------------------------------------------------------

def test_kolejnosc_blokad_i_brak_odczytu_miedzy_commitem_a_blokada(client, tablet):
    """Pracownicy (sesje) → COMMIT → blokada tras → zamówienia → pozycje. Między ostatnim COMMIT-em przed blokadą
    tras a nią stoi jedno zapytanie: odczyt samych kolumn (id, order_id) pozycji — kolumny, które się nie zmieniają,
    brane zwykłym odczytem także w panelu (`zablokuj_zamowienia_i_pozycje`). Żadnego odświeżenia obiektu ORM
    (kierownika, urządzenia) pomiędzy."""
    z = zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny='26/00721', bl_id=910721)
    (pid,) = _id_pozycji(z)
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik)
    db.session.commit()

    with Zapytania() as zapytania:
        event.listen(db.engine, 'commit', lambda conn: zapytania.lista.append(('COMMIT', None)))
        r = client.post(URL, json={'product_ids': [pid], 'status': 'wstrzymane'}, headers=naglowek)
    assert r.status_code == 200, r.get_data()[:300]

    sql = [s for s, _p in zapytania.lista]
    sesje = max(i for i, s in enumerate(sql) if 'prod_worker_sessions' in s and s.startswith('SELECT'))
    blokada_tras = next(i for i, s in enumerate(sql) if 'prod_config' in s and s.endswith('FOR UPDATE'))
    zamowienia_ = zapytania.pierwsze(blokada_zamowien)
    pozycje = zapytania.pierwsze(blokada_pozycji)
    assert sesje < blokada_tras < zamowienia_ < pozycje

    ostatni_commit = max(i for i in range(blokada_tras) if sql[i] == 'COMMIT')
    assert sesje < ostatni_commit
    miedzy = sql[ostatni_commit + 1:blokada_tras]
    assert len(miedzy) == 1 and miedzy[0].startswith('SELECT prod_products.id AS prod_products_id, '
                                                     'prod_products.order_id'), miedzy
