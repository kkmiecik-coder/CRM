# -*- coding: utf-8 -*-
"""POST /api/mobile/manager/stations/<kod>/desk i /desk/remove — „Na stół” i „Zdejmij ze stołu” z tabletu kierownika
(kontrakt §7.3, §7.4) oraz kanały realtime tabletu kierownika (§9).

Testy jadą na SQLite, więc NIE sprawdzają blokad MySQL — kolejność blokad pilnuje test na zapisanych zapytaniach
(`tests/blokady_pomocnicze.py` odtwarza FOR UPDATE i LOCK IN SHARE MODE, które SQLite wycina z tekstu SQL)."""
import itertools

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.production.kierownik.services import biala_lista
from modules.production.models import ProcessedMobileOperation, ProductionDevice
from modules.production.priorytety.models import PriorityLog, StationDesk
from modules.production.priorytety.services import stol, ustawienia, widok
from modules.production.services.station_catalog import STATION_ORDER
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, indeks_blokady_tras, odczyt_biezacy_pozycji_wielu_zamowien,
    odczyt_biezacy_zamowien,
)
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, ustaw, zamrozony_dzien  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia', 'zamrozony_dzien')

_licznik = itertools.count(1)
REALTIME = {
    'enabled': True, 'api_url': 'http://127.0.0.1:8091/api/publish', 'api_key': 'test-key',
    'token_hmac_secret': 'test-secret', 'token_ttl_seconds': 3600,
    'sse_url': 'https://crm.woodpower.pl/realtime/connection/uni_sse',
}


@pytest.fixture()
def tablet(app):
    drabina_domyslna()
    return tablet_kierownika(imie='Jan', nazwisko='Kierownik')


@pytest.fixture()
def sygnaly(monkeypatch):
    """Sygnały stanowisk wysłane po commicie: lista kodów w kolejności publikacji."""
    from modules.production.services import realtime_service
    wyslane = []
    monkeypatch.setattr(realtime_service, 'publish_station_signal', lambda kod: wyslane.append(kod) or True)
    return wyslane


def _post(client, tablet, kod, akcja, cialo, op_id=None):
    device, kierownik = tablet
    return client.post('%s/stations/%s/%s' % (API, kod, akcja), json=cialo,
                       headers=naglowki(device, kierownik, op_id=op_id))


def na_stol(client, tablet, kod, order_id, op_id=None):
    return _post(client, tablet, kod, 'desk', {'order_id': order_id}, op_id)


def zdejmij(client, tablet, kod, unit_key, op_id=None):
    return _post(client, tablet, kod, 'desk/remove', {'unit_key': unit_key}, op_id)


def _ok(r):
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _na_formatowaniu(numer='26/00901', bl_id=910901):
    return zamowienie(statusy=('czeka_na_formatowanie',), numer_wewnetrzny=numer, bl_id=bl_id)


# --- lista endpointów ---------------------------------------------------------------------------------------------

def test_trasy_sa_na_liscie_endpointow():
    assert ('POST', '/stations/<kod>/desk') in ENDPOINTY_KIEROWNIKA
    assert ('POST', '/stations/<kod>/desk/remove') in ENDPOINTY_KIEROWNIKA


# --- „Na stół” -----------------------------------------------------------------------------------------------------

def test_na_stol_z_tabletu(client, tablet, sygnaly):
    device, kierownik = tablet
    z = _na_formatowaniu()

    odp = _ok(na_stol(client, tablet, 'formatting', z.id))

    assert odp['wynik'] == 'wyslano'
    assert odp['wyslane'] == ['o:%d' % z.id] and odp['przywrocone'] == [] and odp['juz_na_stole'] == []
    assert odp['message'] == u'Zamówienie 26/00901 jest na stole Formatowania.'
    wiersz = StationDesk.query.filter_by(station_code='formatting').one()
    assert (wiersz.zrodlo, wiersz.sent_by_worker_id, wiersz.sent_by_user_id) == ('biuro', kierownik.id, None)
    log = PriorityLog.query.filter_by(action='wyslanie').one()
    assert (log.worker_id, log.device_id, log.user_id) == (kierownik.id, device.id, None)
    assert (log.station_code, log.new_value, log.order_id) == ('formatting', 'o:%d' % z.id, z.id)
    assert sygnaly == ['formatting']                                      # tablety stanowiska dociągają stół
    assert biala_lista.zakazane_w(odp) == []


def test_na_stol_stanowisko_pozycyjne_kladzie_kazda_pozycje(client, tablet):
    ustaw('priorytety_jednostka_gluing', 'pozycja')
    z = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'), numer_wewnetrzny='26/00902', bl_id=910902)
    ids = sorted(p.id for p in z.products)

    odp = _ok(na_stol(client, tablet, 'gluing', z.id))

    assert odp['wyslane'] == ['p:%d' % i for i in ids]
    assert sorted(k['unit_key'] for k in odp['stanowisko']['stol']) == ['p:%d' % i for i in ids]


def test_na_stol_dziala_w_trybie_stary(client, tablet):
    assert ustawienia.tryb('formatting') == 'stary'
    z = _na_formatowaniu('26/00903', 910903)
    assert _ok(na_stol(client, tablet, 'formatting', z.id))['wynik'] == 'wyslano'


def test_wyslal_w_widoku_to_kierownik(client, tablet):
    z = _na_formatowaniu('26/00904', 910904)
    _ok(na_stol(client, tablet, 'formatting', z.id))

    db.session.rollback()
    stol_formatowania = widok.stoly_panelu(['formatting'])[0]['stol']

    assert [k['wyslal'] for k in stol_formatowania] == ['Jan Kierownik']      # web widzi to samo co tablet
    assert stol_formatowania[0]['zrodlo'] == 'biuro'


def test_wyslal_z_panelu_dalej_jest_uzytkownikiem(app, client, tablet):
    """Kafel wysłany z panelu (`sent_by_user_id`) nie ma pracownika: `wyslal` nadal pochodzi z użytkownika."""
    from modules.users.models import User
    uzytkownik = User(email='biuro@example.com', password='x', first_name='Ewa', last_name='Biuro', active=True)
    db.session.add(uzytkownik)
    db.session.commit()
    z = _na_formatowaniu('26/00905', 910905)
    stol.wyslij('formatting', z.id, uzytkownik.id)
    db.session.commit()

    assert [k['wyslal'] for k in widok.stoly_panelu(['formatting'])[0]['stol']] == ['Ewa Biuro']


def test_na_stol_drugi_raz_to_juz_na_stole(client, tablet, sygnaly):
    z = _na_formatowaniu('26/00906', 910906)
    _ok(na_stol(client, tablet, 'formatting', z.id))
    del sygnaly[:]

    odp = _ok(na_stol(client, tablet, 'formatting', z.id))

    assert odp['wynik'] == 'juz_na_stole' and odp['wyslane'] == [] and odp['juz_na_stole'] == ['o:%d' % z.id]
    assert PriorityLog.query.filter_by(action='wyslanie').count() == 1
    assert sygnaly == []                                                  # nic się nie zmieniło, nic nie wysyłamy


def test_na_stol_przywraca_odlozony_kafel(client, tablet):
    from modules.production.models import get_local_now
    z = _na_formatowaniu('26/00907', 910907)
    db.session.add(StationDesk(station_code='formatting', order_id=z.id, unit_key='o:%d' % z.id,
                               postponed_at=get_local_now(), postpone_reason='brak_materialu'))
    db.session.commit()

    odp = _ok(na_stol(client, tablet, 'formatting', z.id))

    assert odp['wynik'] == 'wyslano' and odp['przywrocone'] == ['o:%d' % z.id]
    wiersz = StationDesk.query.filter_by(station_code='formatting').one()
    assert wiersz.postponed_at is None and wiersz.sent_by_worker_id == tablet[1].id


def test_na_stol_nie_zmienia_stolu_przy_odmowie(client, tablet):
    z = zamowienie(statusy=('czeka_na_sklejanie',), numer_wewnetrzny='26/00908', bl_id=910908)

    r = na_stol(client, tablet, 'formatting', z.id)

    assert r.status_code == 409 and r.get_json()['error'] == 'brak_na_stanowisku'
    assert StationDesk.query.count() == 0 and PriorityLog.query.count() == 0


def _op_zapamietane(op_id):
    db.session.rollback()
    return ProcessedMobileOperation.query.filter_by(operation_id=op_id).count()


def test_na_stol_bledy(client, tablet, sygnaly):
    z = _na_formatowaniu('26/00909', 910909)
    nie_ma = z.id + 1000

    przypadki = [
        # (stanowisko, ciało, status, kod błędu)
        ('formatting', {'order_id': nie_ma}, 404, 'zamowienie_nieznane'),
        ('gluing', {'order_id': z.id}, 409, 'brak_na_stanowisku'),
        ('painting', {'order_id': z.id}, 409, 'stanowisko_bez_stolu'),
        ('nie-ma', {'order_id': z.id}, 404, 'stanowisko_nieznane'),
        ('formatting', {}, 400, 'dane_niepoprawne'),
        ('formatting', {'order_id': '12'}, 400, 'dane_niepoprawne'),
        ('formatting', {'order_id': True}, 400, 'dane_niepoprawne'),
        ('formatting', {'order_id': 1.5}, 400, 'dane_niepoprawne'),
        ('formatting', [z.id], 400, 'dane_niepoprawne'),
    ]
    for i, (kod, cialo, status, blad) in enumerate(przypadki):
        op_id = 'op-stol-blad-%d' % i
        r = _post(client, tablet, kod, 'desk', cialo, op_id)
        assert (r.status_code, r.get_json()['error']) == (status, blad), (kod, cialo, r.get_data()[:200])
        assert r.get_json()['message']
        assert _op_zapamietane(op_id) == 0, (kod, cialo)                  # 4xx nie jest zapamiętane pod op_id
    assert StationDesk.query.count() == 0 and PriorityLog.query.count() == 0
    assert sygnaly == []


def test_na_stol_bez_operation_id_400(client, tablet):
    z = _na_formatowaniu('26/00910', 910910)
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik)
    del naglowek['X-Operation-Id']
    r = client.post(API + '/stations/formatting/desk', json={'order_id': z.id}, headers=naglowek)
    assert r.status_code == 400 and r.get_json()['error'] == 'missing_operation_id'
    assert StationDesk.query.count() == 0


# --- „Zdejmij ze stołu” --------------------------------------------------------------------------------------------

def test_zdejmij_z_tabletu_i_brak_kafla(client, tablet, sygnaly):
    device, kierownik = tablet
    z = _na_formatowaniu('26/00911', 910911)
    _ok(na_stol(client, tablet, 'formatting', z.id))
    del sygnaly[:]
    klucz = 'o:%d' % z.id

    odp = _ok(zdejmij(client, tablet, 'formatting', klucz))

    assert (odp['unit_key'], odp['order_id'], odp['product_id'], odp['odlozony']) == (klucz, z.id, None, False)
    assert odp['message'] == u'Zdjęto kafel zamówienia 26/00911 ze stołu Formatowania.'
    assert StationDesk.query.count() == 0
    log = PriorityLog.query.filter_by(action='zdjecie').one()
    assert (log.worker_id, log.device_id, log.user_id) == (kierownik.id, device.id, None)
    assert (log.station_code, log.new_value, log.old_value) == ('formatting', klucz, 'biuro')
    assert sygnaly == ['formatting']
    assert biala_lista.zakazane_w(odp) == []

    # drugi raz ten sam kafel (nowy op_id): 404 brak_kafla, bez zapamiętania
    op_id = 'op-stol-drugi-raz'
    r = zdejmij(client, tablet, 'formatting', klucz, op_id)
    assert r.status_code == 404 and r.get_json()['error'] == 'brak_kafla'
    assert _op_zapamietane(op_id) == 0
    assert sygnaly == ['formatting']                                      # odmowa nie wysłała drugiego sygnału


def test_zdejmij_odlozony_kafel_pozycji(client, tablet):
    from modules.production.models import get_local_now
    ustaw('priorytety_jednostka_gluing', 'pozycja')
    z = zamowienie(statusy=('czeka_na_sklejanie',), numer_wewnetrzny='26/00912', bl_id=910912)
    (pozycja,) = z.products
    db.session.add(StationDesk(station_code='gluing', order_id=z.id, product_id=pozycja.id,
                               unit_key='p:%d' % pozycja.id, postponed_at=get_local_now(),
                               postpone_reason='brak_materialu'))
    db.session.commit()
    nazwa_pozycji = pozycja.short_product_id or u'#%d' % pozycja.id

    odp = _ok(zdejmij(client, tablet, 'gluing', 'p:%d' % pozycja.id))

    assert odp['odlozony'] is True and odp['product_id'] == pozycja.id
    # Kafel pozycji nazwany jej skróconym numerem; odłożone po polsku w miejscowniku („na Sklejaniu”).
    assert odp['message'] == u'Zdjęto kafel pozycji {} z odłożonych na Sklejaniu.'.format(nazwa_pozycji)
    assert StationDesk.query.count() == 0


def test_zdejmij_bledy(client, tablet, sygnaly):
    z = _na_formatowaniu('26/00913', 910913)
    _ok(na_stol(client, tablet, 'formatting', z.id))
    del sygnaly[:]

    przypadki = [
        ('formatting', {'unit_key': 'o:999999'}, 404, 'brak_kafla'),
        ('formatting', {'unit_key': 'x:1'}, 400, 'dane_niepoprawne'),
        ('formatting', {'unit_key': 'o:0'}, 400, 'dane_niepoprawne'),
        ('formatting', {'unit_key': 12}, 400, 'dane_niepoprawne'),
        ('formatting', {}, 400, 'dane_niepoprawne'),
        ('painting', {'unit_key': 'o:1'}, 409, 'stanowisko_bez_stolu'),
        ('nie-ma', {'unit_key': 'o:1'}, 404, 'stanowisko_nieznane'),
    ]
    for i, (kod, cialo, status, blad) in enumerate(przypadki):
        op_id = 'op-stol-zdejmij-blad-%d' % i
        r = _post(client, tablet, kod, 'desk/remove', cialo, op_id)
        assert (r.status_code, r.get_json()['error']) == (status, blad), (kod, cialo, r.get_data()[:200])
        assert _op_zapamietane(op_id) == 0
    assert StationDesk.query.count() == 1 and PriorityLog.query.filter_by(action='zdjecie').count() == 0
    assert sygnaly == []


# --- stan po zapisie -----------------------------------------------------------------------------------------------

def test_odpowiedz_ma_stan_po_zapisie(client, tablet):
    z = _na_formatowaniu('26/00914', 910914)
    klucz = 'o:%d' % z.id

    po_wyslaniu = _ok(na_stol(client, tablet, 'formatting', z.id))['stanowisko']
    assert po_wyslaniu['kod'] == 'formatting'
    assert [k['unit_key'] for k in po_wyslaniu['stol']] == [klucz]
    assert po_wyslaniu['stol'][0]['wyslal'] == 'Jan Kierownik'

    po_zdjeciu = _ok(zdejmij(client, tablet, 'formatting', klucz))['stanowisko']
    assert po_zdjeciu['stol'] == []                       # stan po zapisie: kafel zszedł ze stołu w tej transakcji


def test_odpowiedz_stanowiska_jak_odczyt(client, tablet):
    """Pole `stanowisko` odpowiedzi to ten sam kształt co `GET /stations/<kod>` (§7.2)."""
    z = _na_formatowaniu('26/00915', 910915)
    zapis = _ok(na_stol(client, tablet, 'formatting', z.id))['stanowisko']
    device, kierownik = tablet
    odczyt = _ok(client.get(API + '/stations/formatting', headers=naglowki(device, kierownik)))
    assert sorted(zapis) == sorted(odczyt)
    assert zapis['stol'] == odczyt['stol']


# --- idempotencja i ponowienie ------------------------------------------------------------------------------------

def test_idempotencja_na_stol(client, tablet, sygnaly):
    z = _na_formatowaniu('26/00916', 910916)

    pierwsza = _ok(na_stol(client, tablet, 'formatting', z.id, op_id='op-stol-idem'))
    druga = _ok(na_stol(client, tablet, 'formatting', z.id, op_id='op-stol-idem'))

    assert druga == pierwsza                                                # ta sama odpowiedź, bez ponownego zapisu
    assert PriorityLog.query.filter_by(action='wyslanie').count() == 1
    assert StationDesk.query.count() == 1
    assert sygnaly == ['formatting']                                        # powtórka nie wysyła drugiego sygnału


def test_idempotencja_zdejmij(client, tablet):
    z = _na_formatowaniu('26/00917', 910917)
    _ok(na_stol(client, tablet, 'formatting', z.id))
    pierwsza = _ok(zdejmij(client, tablet, 'formatting', 'o:%d' % z.id, op_id='op-stol-idem-z'))
    druga = _ok(zdejmij(client, tablet, 'formatting', 'o:%d' % z.id, op_id='op-stol-idem-z'))
    assert druga == pierwsza
    assert PriorityLog.query.filter_by(action='zdjecie').count() == 1


def _blad_mysql(kod):
    return OperationalError('UPDATE', {}, Exception(kod, 'blad'))


def test_ponowienie_1213_na_stol(client, tablet, monkeypatch, sygnaly):
    z = _na_formatowaniu('26/00918', 910918)
    oryginal = stol.wyslij
    wywolania = []

    def falszywa(*args, **kwargs):
        wywolania.append(1)
        if len(wywolania) == 1:
            raise _blad_mysql(1213)
        return oryginal(*args, **kwargs)
    monkeypatch.setattr(stol, 'wyslij', falszywa)

    odp = _ok(na_stol(client, tablet, 'formatting', z.id))

    assert len(wywolania) == 2 and odp['wynik'] == 'wyslano'
    assert StationDesk.query.count() == 1 and PriorityLog.query.filter_by(action='wyslanie').count() == 1
    assert sygnaly == ['formatting']


# --- blokady ------------------------------------------------------------------------------------------------------

def _po_ostatnim_commicie_przed(sql, indeks):
    return max(i for i in range(indeks) if sql[i] == 'COMMIT')


def _zapytania_zapisu(client, tablet, kod, akcja, cialo):
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik)
    db.session.commit()
    with Zapytania() as zapytania:
        event.listen(db.engine, 'commit', lambda conn: zapytania.lista.append(('COMMIT', None)))
        r = client.post('%s/stations/%s/%s' % (API, kod, akcja), json=cialo, headers=naglowek)
    assert r.status_code == 200, r.get_data()[:300]
    return zapytania


def _jest_blokada_stanowiska(sql, parametry, kod):
    return (sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')
            and ustawienia.klucz_blokady(kod) in tuple(parametry or ()))


def test_pierwszy_odczyt_po_commicie_to_blokada_stanowiska(client, tablet):
    """Sesje pracownika → COMMIT → pierwszy odczyt nowej transakcji = `SELECT … prod_config … FOR UPDATE` na wierszu
    `priorytety_blokada_<S>` (nic pomiędzy: ani odświeżenie kierownika, ani urządzenia) → zamówienie i pozycje
    LOCK IN SHARE MODE → zapisy. Nigdy FOR UPDATE na zamówieniach i pozycjach, nigdy blokada tras."""
    z = _na_formatowaniu('26/00919', 910919)
    zapytania = _zapytania_zapisu(client, tablet, 'formatting', 'desk', {'order_id': z.id})
    sql = [s for s, _p in zapytania.lista]

    blokada = next(i for i, (s, p) in enumerate(zapytania.lista) if _jest_blokada_stanowiska(s, p, 'formatting'))
    ostatni_commit = _po_ostatnim_commicie_przed(sql, blokada)
    assert sql[ostatni_commit + 1:blokada] == [], sql[ostatni_commit + 1:blokada]   # blokada otwiera transakcję

    zamowienia_ = zapytania.pierwsze(odczyt_biezacy_zamowien)
    pozycje = zapytania.pierwsze(odczyt_biezacy_pozycji_wielu_zamowien)
    zapis = next(i for i, s in enumerate(sql) if s.startswith(('INSERT INTO prod_station_desk',
                                                               'INSERT INTO prod_priority_log')))
    assert blokada < zamowienia_ < pozycje < zapis
    # sesje pracowników (przedłużenie sesji kierownika) przed COMMIT-em poprzedzającym blokadę
    sesje = max(i for i, s in enumerate(sql[:blokada]) if 'prod_worker_sessions' in s)
    assert sesje < ostatni_commit

    # pisarz stołu: żadnych blokad X zamówień i pozycji, żadnej blokady tras
    assert not any(blokada_zamowien(s) or blokada_pozycji(s) for s in sql)
    with pytest.raises(StopIteration):
        indeks_blokady_tras(zapytania)
    # faza decyzji (od blokady do pierwszego zapisu): każdy odczyt zamówień i pozycji jest blokujący współdzielnie;
    # zwykłe odczyty tych tabel (stan stanowiska w odpowiedzi) wolno dopiero po zapisach
    for s in sql[blokada:zapis]:
        if s.startswith('SELECT') and ('FROM prod_orders' in s or 'FROM prod_products' in s):
            assert s.endswith(' LOCK IN SHARE MODE'), s


def test_pierwszy_odczyt_po_commicie_przy_zdejmowaniu(client, tablet):
    z = _na_formatowaniu('26/00920', 910920)
    _ok(na_stol(client, tablet, 'formatting', z.id))
    zapytania = _zapytania_zapisu(client, tablet, 'formatting', 'desk/remove', {'unit_key': 'o:%d' % z.id})
    sql = [s for s, _p in zapytania.lista]

    blokada = next(i for i, (s, p) in enumerate(zapytania.lista) if _jest_blokada_stanowiska(s, p, 'formatting'))
    assert sql[_po_ostatnim_commicie_przed(sql, blokada) + 1:blokada] == []
    assert not any(blokada_zamowien(s) or blokada_pozycji(s) for s in sql)
    with pytest.raises(StopIteration):
        indeks_blokady_tras(zapytania)
    # wiersz stołu kafla: odczyt bieżący równością po całym kluczu unikalnym, nigdy wszystkich wierszy stanowiska
    biezace = [(s, p) for s, p in zapytania.lista if s.startswith('SELECT') and 'FROM prod_station_desk' in s
               and s.endswith(' FOR UPDATE')]
    assert len(biezace) == 1
    assert 'prod_station_desk.station_code = ?' in biezace[0][0] and 'prod_station_desk.unit_key = ?' in biezace[0][0]
    assert 'o:%d' % z.id in tuple(biezace[0][1])


# --- realtime -----------------------------------------------------------------------------------------------------

def test_realtime_token_kierownika_7_kanalow(app, client, tablet):
    import jwt
    app.config['REALTIME'] = dict(REALTIME)
    device, _kierownik = tablet

    r = client.get('/api/mobile/realtime-token', headers=naglowki(device))

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    oczekiwane = ['station:' + kod for kod in STATION_ORDER]
    assert len(oczekiwane) == 7 and dane['channels'] == oczekiwane
    assert set(dane) == {'enabled', 'token', 'ttl_seconds', 'sse_url', 'channels'}
    claims = jwt.decode(dane['token'], 'test-secret', algorithms=['HS256'])
    assert claims['channels'] == oczekiwane and claims['sub'] == 'device:' + device.device_id


def test_realtime_token_kierownika_503_gdy_wylaczony(app, client, tablet):
    app.config['REALTIME'] = {'enabled': False}
    r = client.get('/api/mobile/realtime-token', headers=naglowki(tablet[0]))
    assert r.status_code == 503 and r.get_json() == {'enabled': False, 'reason': 'realtime disabled'}


def test_realtime_token_innych_urzadzen_bez_zmian(app, client, tablet):
    """Trakownia nadal dostaje 404 `unknown_station`, a tablet stanowiska tylko swoją grupę."""
    app.config['REALTIME'] = dict(REALTIME)
    for kod, kanaly in (('sawmill', None), ('gluing', ['station:gluing']), ('edges', ['station:edges',
                                                                                     'station:painting'])):
        urzadzenie = ProductionDevice(device_id='TAB-RT-%d' % next(_licznik), device_name='Tablet', station_code=kod)
        db.session.add(urzadzenie)
        db.session.commit()
        r = client.get('/api/mobile/realtime-token', headers=naglowki(urzadzenie))
        if kanaly is None:
            assert r.status_code == 404 and r.get_json()['error'] == 'unknown_station'
        else:
            assert r.status_code == 200 and r.get_json()['channels'] == kanaly
