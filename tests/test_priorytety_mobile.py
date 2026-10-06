# -*- coding: utf-8 -*-
"""
Końcówki API mobilnego priorytetów produkcji (krok K3; spec 2026-10-04, sekcje 6.1–6.3): `GET desk` (stół
stanowiska z dopełnianiem), `POST postpone` (Odłóż), `GET realtime-token`, pole `priorytet` w serializerze i listach.

Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import itertools
import json
from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProcessedMobileOperation, ProductionDevice, ProductionProduct
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, StationDesk
from modules.production.priorytety.services import kolejka, stol
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import Zapytania
from tests.logistyka_fixtures import app, client, pracownik, produkt, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, ustaw  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia')

_licznik = itertools.count(1)
_STOL = StationDesk.__table__
T0 = datetime(2026, 10, 5, 8, 0)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(stanowisko, wersja=None):
    device = ProductionDevice(device_id='TAB-MOB-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko, last_app_version_code=wersja)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device)}


def _operacja(naglowki):
    return dict(naglowki, **{'X-Operation-Id': 'op-mob-%d' % next(_licznik)})


def _desk(client, stanowisko, naglowki, etag=None):
    naglowki = dict(naglowki)
    if etag:
        naglowki['If-None-Match'] = etag
    return client.get('/api/mobile/stations/%s/desk' % stanowisko, headers=naglowki)


def _kafel(stanowisko, obiekt, odlozony=False, zrodlo='kolejka', pobrano=T0, **kolumny):
    from modules.production.models import ProductionOrder
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    if odlozony:
        dane.update(postponed_at=T0, postpone_reason='brak_materialu', postpone_note=u'czekamy na dąb')
    dane.update(kolumny)
    wiersz = StationDesk(station_code=stanowisko, pulled_at=pobrano, zrodlo=zrodlo, **dane)
    db.session.add(wiersz)
    db.session.commit()
    return wiersz.id


def _tryb(stanowisko, tryb='stol'):
    ustaw(stale.klucz_tryb(stanowisko), tryb)


def _blad_mysql(kod, komunikat='Deadlock found when trying to get lock'):
    return OperationalError('SELECT prod_config ...', {}, Exception(kod, komunikat))


# ══ GET /api/mobile/stations/<kod>/desk ═════════════════════════════════════════════════════════════════════

POLA_STOLU = {'station_code', 'tryb', 'jednostka', 'miejsca', 'stol', 'odlozone', 'niekompletne', 'limit_odlozen',
              'kolejka_dalej'}
POLA_POZYCJI = {'id', 'short_id', 'internal_order_number', 'product_name', 'quantity_ordered', 'quantity_done',
                'priority_rank', 'is_priority', 'status', 'transport', 'packing_hint', 'label_offset', 'updated_at'}


def test_desk_ksztalt_odpowiedzi_pozycja(app, client):
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    pierwsza, druga, trzecia, czwarta = order.products
    _kafel('gluing', czwarta, odlozony=True)

    r = _desk(client, 'gluing', _naglowki('gluing'))

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert set(dane) == POLA_STOLU
    assert (dane['station_code'], dane['jednostka'], dane['miejsca'], dane['limit_odlozen']) == (
        'gluing', 'pozycja', 2, 10)
    assert dane['kolejka_dalej'] == 1 and dane['niekompletne'] == []
    assert [wpis['kafel']['id'] for wpis in dane['stol']] == [pierwsza.id, druga.id]
    for wpis in dane['stol']:
        assert set(wpis) == {'kafel', 'pobrano', 'zrodlo'}
        assert wpis['zrodlo'] == 'kolejka' and wpis['pobrano']
        assert POLA_POZYCJI <= set(wpis['kafel'])
        assert wpis['kafel']['quantity_done'] == 0 or wpis['kafel']['quantity_done'] is None
    (odlozony,) = dane['odlozone']
    assert set(odlozony) == {'kafel', 'odlozono', 'powod', 'notatka', 'pracownik'}
    assert odlozony['kafel']['id'] == czwarta.id
    assert (odlozony['powod'], odlozony['notatka'], odlozony['pracownik']) == (
        'brak_materialu', u'czekamy na dąb', None)
    assert odlozony['odlozono'] == T0.isoformat()
    assert trzecia.id


def test_desk_ksztalt_odpowiedzi_zamowienie(app, client):
    _tryb('formatting')
    kompletne = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'), numer_wewnetrzny='1501')
    niekompletne = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), numer_wewnetrzny='1502')

    r = _desk(client, 'formatting', _naglowki('formatting'))

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['jednostka'] == 'zamowienie'
    (wpis,) = dane['stol']
    kafel = wpis['kafel']
    assert set(kafel) == {'zamowienie', 'pozycje'}
    assert kafel['zamowienie']['order_id'] == kompletne.id
    assert kafel['zamowienie']['internal_order_number'] == '1501'
    assert {'client_name', 'delivery_type', 'transport', 'packing_hint', 'delivery_city', 'delivery_postcode',
            'order_notes', 'order_source', 'deadline', 'baselinker_order_id',
            'client_order_number'} <= set(kafel['zamowienie'])
    assert [p['id'] for p in kafel['pozycje']] == [p.id for p in kompletne.products]
    (brakujace,) = dane['niekompletne']
    assert set(brakujace) == {'kafel', 'na_stanowisku', 'pozycji', 'brakuje'}
    assert (brakujace['na_stanowisku'], brakujace['pozycji']) == (1, 2)
    assert brakujace['kafel']['zamowienie']['order_id'] == niekompletne.id
    assert brakujace['brakuje'] == [{'short_id': niekompletne.products[1].short_product_id, 'stanowisko': 'gluing'}]


def test_desk_dopelnia_i_commituje(app, client):
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)

    assert _desk(client, 'gluing', _naglowki('gluing')).status_code == 200

    db.session.rollback()
    wiersze = StationDesk.query.order_by(StationDesk.id).all()
    assert [(w.station_code, w.unit_key, w.zrodlo) for w in wiersze] == [
        ('gluing', 'p:%d' % order.products[0].id, 'kolejka'), ('gluing', 'p:%d' % order.products[1].id, 'kolejka')]


def test_desk_formatowanie_pozycja_omijajaca_nie_trzyma_w_niekompletnych(app, client):
    """K3-poprawka-1 (spec 5.6 p. 2): zamówienie z pozycją bez docięcia stojącą jeszcze na Sklejaniu wchodzi na
    stół Formatowania (kafel niesie wszystkie pozycje), a sekcja „Niekompletne” jest pusta."""
    _tryb('formatting')
    order = zamowienie(statusy=('czeka_na_formatowanie',))
    produkt(order, status='czeka_na_sklejanie', sekwencja=2, cut_to_size=False)
    db.session.commit()

    dane = _desk(client, 'formatting', _naglowki('formatting')).get_json()

    assert dane['niekompletne'] == []
    (wpis,) = dane['stol']
    assert wpis['kafel']['zamowienie']['order_id'] == order.id
    assert [p['cut_to_size'] for p in wpis['kafel']['pozycje']] == [True, False]


def test_imie_z_inicjalem():
    """K3-poprawka-1 (spec 6.1, decyzja Konrada 5.10): na tablecie „Adam K.” — pełne nazwisko tylko w panelu."""
    assert stol.imie_z_inicjalem(u'Adam', u'Kowalski') == u'Adam K.'
    assert stol.imie_z_inicjalem(u' Anna ', u' nowak-Kowalska ') == u'Anna N.'
    assert stol.imie_z_inicjalem(u'Łukasz', u'żak') == u'Łukasz Ż.'
    assert stol.imie_z_inicjalem(u'Adam', None) == u'Adam'
    assert stol.imie_z_inicjalem(u'Adam', u'  ') == u'Adam'
    assert stol.imie_z_inicjalem(None, u'Kowalski') == u'K.'
    assert stol.imie_z_inicjalem(None, None) is None
    assert stol.imie_z_inicjalem(u'', u'') is None


def test_desk_odlozony_pracownik_imie_z_inicjalem(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    kto = pracownik(imie='Adam', nazwisko='Kowalski')
    _kafel('gluing', order.products[0], odlozony=True, postponed_by_worker_id=kto.id)

    dane = _desk(client, 'gluing', _naglowki('gluing')).get_json()

    (odlozony,) = dane['odlozone']
    assert odlozony['pracownik'] == u'Adam K.'
    assert u'Kowalski' not in json.dumps(dane['odlozone'], ensure_ascii=False)


def test_desk_stol_ma_zrodlo(app, client):
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    p = order.products
    _kafel('gluing', p[0], zrodlo='start')
    _kafel('gluing', p[1], zrodlo='biuro')
    dorobka = produkt(order, status='czeka_na_sklejanie', sekwencja=1, original_product_id=p[0].id)
    db.session.commit()
    naglowki = _naglowki('gluing')

    # K = 2 zajęte przez kafle biura i startowy: doróbka czeka w kolejce (K3-poprawka-1 — w ramach K, nie ponad)
    dane = _desk(client, 'gluing', naglowki).get_json()
    assert [(wpis['kafel']['id'], wpis['zrodlo']) for wpis in dane['stol']] == [(p[1].id, 'biuro'), (p[0].id, 'start')]
    assert dane['miejsca'] == 2 and dane['kolejka_dalej'] == 2

    # wolne trzecie miejsce bierze doróbka (początek kolejki); na stole stoi pierwsza (spec 5.1)
    ustaw(stale.klucz_stol('gluing'), 3, 'integer')
    dane = _desk(client, 'gluing', naglowki).get_json()
    assert [(wpis['kafel']['id'], wpis['zrodlo']) for wpis in dane['stol']] == [
        (dorobka.id, 'dorobka'), (p[1].id, 'biuro'), (p[0].id, 'start')]
    assert dane['miejsca'] == 3 and dane['kolejka_dalej'] == 1


def test_desk_odlozone_po_czasie_odlozenia(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 2)
    wczesniej, pozniej = order.products[1], order.products[0]
    _kafel('gluing', pozniej, odlozony=True, postponed_at=datetime(2026, 10, 5, 9, 40))
    _kafel('gluing', wczesniej, odlozony=True, postponed_at=datetime(2026, 10, 5, 8, 50))

    dane = _desk(client, 'gluing', _naglowki('gluing')).get_json()

    assert [wpis['kafel']['id'] for wpis in dane['odlozone']] == [wczesniej.id, pozniej.id]


def test_desk_kafel_zamowienia_ma_wszystkie_pozycje(app, client):
    """Kafel-zamówienie niesie WSZYSTKIE pozycje zamówienia (także w innych statusach — appka pokazuje postęp
    i plakietki sąsiednich stanowisk), w kolejności pozycji w zamówieniu."""
    _tryb('packaging')
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'spakowane', 'czeka_na_pakowanie'))

    dane = _desk(client, 'packaging', _naglowki('packaging')).get_json()

    (wpis,) = dane['stol']
    assert [(p['id'], p['status']) for p in wpis['kafel']['pozycje']] == [
        (p.id, p.current_status) for p in order.products]


def test_desk_pakowanie_bez_sposobu_dostawy_na_stole(app, client):
    """Tablet Pakowania dostaje zamówienie bez sposobu dostawy na stół jak każde inne (spec 5.1 po logistyce 4.6;
    dawniej `desk` go w ogóle nie pokazywał)."""
    _tryb('packaging')
    bez_sposobu = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',))
    kurier = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    ustaw(stale.klucz_stol('packaging'), 1, 'integer')

    dane = _desk(client, 'packaging', _naglowki('packaging')).get_json()

    assert [[p['id'] for p in wpis['kafel']['pozycje']] for wpis in dane['stol']] == [[bez_sposobu.products[0].id]]
    assert dane['kolejka_dalej'] == 1
    assert kurier.id


def test_desk_etag_304_i_zmiana_po_zmianie_stolu(app, client):
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    naglowki = _naglowki('gluing')
    pierwsza = _desk(client, 'gluing', naglowki)
    etag = pierwsza.headers['ETag']
    assert pierwsza.status_code == 200 and etag.startswith('W/"desk:gluing:')

    druga = _desk(client, 'gluing', naglowki, etag=etag)
    assert druga.status_code == 304 and druga.headers['ETag'] == etag and druga.data == b''

    # kafel schodzi ze stołu (ZAKOŃCZ drugiego tabletu) — stół się dopełnia, ETag jest inny
    db.session.execute(_STOL.delete().where(_STOL.c.unit_key == 'p:%d' % order.products[0].id))
    db.session.execute(ProductionProduct.__table__.update()
                       .where(ProductionProduct.__table__.c.id == order.products[0].id)
                       .values(current_status='czeka_na_formatowanie'))
    db.session.commit()
    trzecia = _desk(client, 'gluing', naglowki, etag=etag)
    assert trzecia.status_code == 200 and trzecia.headers['ETag'] != etag
    assert [w['kafel']['id'] for w in trzecia.get_json()['stol']] == [order.products[1].id, order.products[2].id]


def test_desk_etag_zmienia_sie_po_liczniku_sztuk(app, client):
    """Drugi tablet ma zobaczyć „2/15” od razu: licznik sztuk wchodzi do ETagu wprost, nie tylko przez
    `updated_at` (dwie zmiany w tej samej sekundzie dałyby ten sam znacznik)."""
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja_id, zmieniono = order.products[0].id, order.products[0].updated_at
    naglowki = _naglowki('gluing')
    etag = _desk(client, 'gluing', naglowki).headers['ETag']

    # licznik rośnie, a `updated_at` zostaje ten sam — jak druga zmiana w tej samej sekundzie na MySQL
    tabela = ProductionProduct.__table__
    db.session.execute(tabela.update().where(tabela.c.id == pozycja_id)
                       .values(quantity_done_gluing=1, updated_at=zmieniono))
    db.session.commit()

    r = _desk(client, 'gluing', naglowki, etag=etag)
    assert r.status_code == 200 and r.get_json()['stol'][0]['kafel']['quantity_done'] == 1


def test_desk_cache_control_max_age_0(app, client):
    """Tablet (OkHttp Cache) ma pytać serwer ZA KAŻDYM razem: z `max-age=15` odpowiedź po sygnale wracałaby przez
    15 s z pamięci tabletu — bez dopełnienia i bez zmian z drugiego tabletu."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')

    pierwsza = _desk(client, 'gluing', naglowki)
    druga = _desk(client, 'gluing', naglowki, etag=pierwsza.headers['ETag'])

    assert (pierwsza.status_code, druga.status_code) == (200, 304)
    assert pierwsza.headers['Cache-Control'] == 'private, max-age=0'
    assert druga.headers['Cache-Control'] == 'private, max-age=0'


def test_desk_urzadzenie_lakierni_widzi_krawedzie(app, client):
    """Grupa stanowisk Krawędzie + Lakiernia jest symetryczna: urządzenie zarejestrowane na Lakierni czyta stół
    Krawędzi."""
    _tryb('edges')
    zamowienie(statusy=('czeka_na_krawedzie',))

    r = _desk(client, 'edges', _naglowki('painting'))

    assert r.status_code == 200 and len(r.get_json()['stol']) == 1


def test_desk_station_mismatch_403(app, client):
    r = _desk(client, 'gluing', _naglowki('packaging'))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_mismatch'
    assert StationDesk.query.count() == 0


def test_desk_unknown_station_404(app, client):
    for kod in ('nie-ma-takiego', 'sawmill', 'verification'):
        r = _desk(client, kod, _naglowki('gluing'))
        assert r.status_code == 404 and r.get_json()['error'] == 'unknown_station', kod


def test_desk_wymaga_tokena_urzadzenia(app, client):
    assert client.get('/api/mobile/stations/gluing/desk').status_code == 401


def test_desk_w_trybie_stary_nie_dopelnia(app, client):
    """K3-poprawka-2 (spec 6.3): w trybie `stary` (domyślnym) `desk` niczego nie kładzie na stół — oddaje pusty stół
    z `tryb: "stary"` i licznikiem kolejki."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    assert stale.TRYBY[0] == 'stary'

    r = _desk(client, 'gluing', _naglowki('gluing'))

    assert r.status_code == 200
    assert (r.get_json()['tryb'], r.get_json()['stol'], r.get_json()['kolejka_dalej']) == ('stary', [], 1)


def test_desk_ponawia_raz_po_1213(app, client, monkeypatch):
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    oryginal = stol.dopelnij
    proby = []

    def z_zakleszczeniem(stanowisko, **kwargs):
        proby.append(stanowisko)
        if len(proby) == 1:
            oryginal(stanowisko, **kwargs)          # zapis pierwszej próby musi zostać cofnięty
            raise _blad_mysql(1213)
        return oryginal(stanowisko, **kwargs)

    monkeypatch.setattr(stol, 'dopelnij', z_zakleszczeniem)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 200 and proby == ['gluing', 'gluing']
    assert len(r.get_json()['stol']) == 1
    db.session.rollback()
    assert StationDesk.query.count() == 1


def test_desk_dwa_1213_to_500_bez_zapisow(app, client, monkeypatch):
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    oryginal = stol.dopelnij
    proby = []

    def zawsze_zakleszczenie(stanowisko, **kwargs):
        proby.append(stanowisko)
        oryginal(stanowisko, **kwargs)
        raise _blad_mysql(1213)

    monkeypatch.setattr(stol, 'dopelnij', zawsze_zakleszczenie)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 500
    assert r.get_json() == {'error': 'desk_failed'}
    assert len(proby) == 2                  # jedno ponowienie, nie więcej
    db.session.rollback()
    assert StationDesk.query.count() == 0


def test_desk_inny_blad_bazy_500_bez_ponowienia(app, client, monkeypatch):
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    proby = []

    def awaria(stanowisko, **kwargs):
        proby.append(1)
        raise _blad_mysql(1040, 'Too many connections')

    monkeypatch.setattr(stol, 'dopelnij', awaria)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 500 and r.get_json() == {'error': 'desk_failed'} and proby == [1]


# ── limit czekania na blokady w dopełnianiu (przegląd końcowy K3, W2) ────────────────────────────────────────
#
# `desk` wołają wszystkie tablety stanowiska, co 30 s i po każdym sygnale, a dopełnienie czyta odczytem bieżącym
# zamówienia wszystkich kandydatów. Jedna długo trzymana cudza blokada zamówienia zatrzymałaby każde takie żądanie
# na limicie serwera (50 s, gunicorn ubija po 30 s) i zajęła workery całego CRM. Dlatego transakcja dopełnienia
# czeka na blokadę najwyżej `kolejka.LIMIT_CZEKANIA_NA_BLOKADE_S`; po 1205 tablet dostaje stół bez dopełnienia.

@pytest.fixture()
def limit_czekania(monkeypatch):
    """Udaje MySQL dla limitu czekania: ustawienia sesji wysłane na połączeniu żądania trafiają na listę (sql,
    połączenie) zamiast do SQLite."""
    wyslane = []
    monkeypatch.setattr(kolejka, '_ma_limit_czekania', lambda polaczenie: True)
    monkeypatch.setattr(kolejka, '_wyslij_ustawienie', lambda polaczenie, sql: wyslane.append((sql, polaczenie)))
    return wyslane


def test_desk_ogranicza_czekanie_na_blokady_i_przywraca_limit(app, client, monkeypatch):
    """COMMIT → SET limit → blokada stanowiska → odczyty bieżące → SET DEFAULT → INSERT → COMMIT, wszystko na
    jednym połączeniu. Limit wraca PRZED commitem: commit oddaje połączenie do puli."""
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    polaczenia = []
    monkeypatch.setattr(kolejka, '_ma_limit_czekania', lambda polaczenie: True)

    with Zapytania() as z:
        def ustawienie(polaczenie, sql):
            polaczenia.append(polaczenie)
            z.lista.append((sql, ()))

        def po_commicie(_polaczenie):
            z.lista.append(('COMMIT', None))

        monkeypatch.setattr(kolejka, '_wyslij_ustawienie', ustawienie)
        event.listen(db.engine, 'commit', po_commicie)
        try:
            r = _desk(client, 'gluing', naglowki)
        finally:
            event.remove(db.engine, 'commit', po_commicie)

    assert r.status_code == 200 and len(r.get_json()['stol']) == 1
    teksty = [sql for sql, _p in z.lista]
    ustaw_limit = teksty.index(kolejka._SQL_USTAW_LIMIT)
    przywroc = teksty.index(kolejka._SQL_PRZYWROC_LIMIT)
    blokada = next(i for i, sql in enumerate(teksty) if 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE'))
    pozycje = next(i for i, sql in enumerate(teksty)
                   if 'FROM prod_products' in sql and sql.endswith(' LOCK IN SHARE MODE'))
    wstawka = next(i for i, sql in enumerate(teksty) if sql.startswith('INSERT INTO prod_station_desk'))
    commit_po = next(i for i, sql in enumerate(teksty) if i > wstawka and sql == 'COMMIT')
    assert teksty[ustaw_limit - 1] == 'COMMIT'          # limit to pierwsze polecenie nowej transakcji…
    assert blokada == ustaw_limit + 1                   # …a zaraz po nim blokada stanowiska, bez odczytu pomiędzy
    assert blokada < pozycje < przywroc < wstawka < commit_po
    assert teksty.count(kolejka._SQL_USTAW_LIMIT) == 1 and teksty.count(kolejka._SQL_PRZYWROC_LIMIT) == 1
    assert len(polaczenia) == 2 and polaczenia[0] is polaczenia[1]


def test_desk_1205_oddaje_stol_bez_dopelnienia_i_bez_ponowienia(app, client, monkeypatch, limit_czekania):
    """Cudza blokada trzymana dłużej niż limit: bez ponowienia (znów czekałoby na tę samą blokadę) i bez 500 —
    tablet dostaje bieżący stół, wolne miejsce zajmie następny `desk` (sygnał albo siatka odpytywania)."""
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    lezy, czeka = order.products
    _kafel('gluing', lezy)
    naglowki = _naglowki('gluing')
    sygnaly_wyslane = []
    monkeypatch.setattr('modules.production.services.realtime_service.publish_station_signal',
                        lambda kod: sygnaly_wyslane.append(kod) or True)
    proby = []

    def czekanie_przekroczone(stanowisko, **kwargs):
        proby.append(stanowisko)
        raise _blad_mysql(1205, 'Lock wait timeout exceeded; try restarting transaction')

    monkeypatch.setattr(stol, 'dopelnij', czekanie_przekroczone)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 200, r.get_json()
    assert proby == ['gluing']
    dane = r.get_json()
    assert [wpis['kafel']['id'] for wpis in dane['stol']] == [lezy.id]      # stół bez dopełnienia
    assert dane['kolejka_dalej'] == 1
    assert [sql for sql, _polaczenie in limit_czekania] == [kolejka._SQL_USTAW_LIMIT, kolejka._SQL_PRZYWROC_LIMIT]
    assert sygnaly_wyslane == []
    db.session.rollback()
    assert StationDesk.query.count() == 1 and czeka.id


def test_desk_po_1213_ponowienie_tez_ma_limit(app, client, monkeypatch, limit_czekania):
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    oryginal = stol.dopelnij
    proby = []

    def z_zakleszczeniem(stanowisko, **kwargs):
        proby.append(stanowisko)
        if len(proby) == 1:
            raise _blad_mysql(1213)
        return oryginal(stanowisko, **kwargs)

    monkeypatch.setattr(stol, 'dopelnij', z_zakleszczeniem)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 200 and len(r.get_json()['stol']) == 1 and len(proby) == 2
    assert [sql for sql, _polaczenie in limit_czekania] == [
        kolejka._SQL_USTAW_LIMIT, kolejka._SQL_PRZYWROC_LIMIT, kolejka._SQL_USTAW_LIMIT, kolejka._SQL_PRZYWROC_LIMIT]


def test_desk_1213_potem_1205_stol_bez_dopelnienia(app, client, monkeypatch, limit_czekania):
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    kody = [1213, 1205]

    def awarie(stanowisko, **kwargs):
        raise _blad_mysql(kody.pop(0))

    monkeypatch.setattr(stol, 'dopelnij', awarie)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 200 and r.get_json()['stol'] == [] and kody == []


def test_desk_nieudane_przywrocenie_limitu_uniewaznia_polaczenie(app, client, monkeypatch):
    """Połączenie, któremu nie udało się przywrócić limitu, nie może wrócić do puli z krótkim limitem."""
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    wyslane, uniewaznione = [], []

    def ustawienie(polaczenie, sql):
        wyslane.append((sql, polaczenie))
        if sql == kolejka._SQL_PRZYWROC_LIMIT:
            raise RuntimeError('zerwane polaczenie')

    monkeypatch.setattr(kolejka, '_ma_limit_czekania', lambda polaczenie: True)
    monkeypatch.setattr(kolejka, '_wyslij_ustawienie', ustawienie)
    monkeypatch.setattr(stol, '_uniewaznij_polaczenie', uniewaznione.append)
    r = _desk(client, 'gluing', naglowki)

    assert r.status_code == 200
    assert [sql for sql, _polaczenie in wyslane] == [kolejka._SQL_USTAW_LIMIT, kolejka._SQL_PRZYWROC_LIMIT]
    assert uniewaznione == [wyslane[0][1]]


def test_uniewaznij_polaczenie_zamkniete_wymienia_pule(app, monkeypatch):
    """Ostatnia zapora: połączenie już oddane do puli (zamknięte) nie daje się unieważnić — wymieniamy całą pulę,
    żeby krótki limit nie trafił do ZAKOŃCZ ani hurtu innego żądania."""
    wymiany = []

    class Zamkniete(object):
        def invalidate(self):
            raise RuntimeError('This Connection is closed')

    monkeypatch.setattr(db.engine, 'dispose', lambda: wymiany.append(1))
    stol._uniewaznij_polaczenie(Zamkniete())
    assert wymiany == [1]

    class Otwarte(object):
        uniewaznione = 0

        def invalidate(self):
            self.uniewaznione += 1

    otwarte = Otwarte()
    stol._uniewaznij_polaczenie(otwarte)
    assert otwarte.uniewaznione == 1 and wymiany == [1]


def test_desk_bez_limitu_poza_mysql(app, client, monkeypatch):
    """SQLite testów nie zna `innodb_lock_wait_timeout` — nic nie jest wysyłane."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    wyslane = []
    monkeypatch.setattr(kolejka, '_wyslij_ustawienie', lambda polaczenie, sql: wyslane.append(sql))

    assert _desk(client, 'gluing', _naglowki('gluing')).status_code == 200
    assert wyslane == []


def test_dopelnienie_pod_limitem_nie_flushuje_przed_przywroceniem(app, monkeypatch, limit_czekania):
    """W zasięgu limitu nie ma flusha: nieudany flush zwalnia połączenie sesji, a wtedy limitu nie byłoby jak
    przywrócić. INSERT-y idą dopiero przy commicie, po `SET … = DEFAULT`."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    db.session.commit()
    with Zapytania() as z:
        with stol.krotkie_czekanie_na_blokady():
            stol.dopelnij('gluing')
            db.session.query(StationDesk.id).all()      # zapytanie w zasięgu NIE wypycha oczekujących INSERT-ów
            w_zasiegu = len([sql for sql, _p in z.lista if sql.startswith('INSERT INTO prod_station_desk')])
        db.session.commit()
    assert w_zasiegu == 0
    assert len([sql for sql, _p in z.lista if sql.startswith('INSERT INTO prod_station_desk')]) == 1
    assert [sql for sql, _polaczenie in limit_czekania] == [kolejka._SQL_USTAW_LIMIT, kolejka._SQL_PRZYWROC_LIMIT]


def test_desk_commit_przed_blokada_bez_odczytu_pomiedzy(app, client):
    """Migawka żądania (touch urządzenia, odczyty `g.device`) kończy się commitem TUŻ przed blokadą stanowiska:
    między nimi nie ma żadnego zapytania — pierwszy zwykły odczyt nowej transakcji idzie już pod blokadą."""
    _tryb('gluing')
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        def po_commicie(_polaczenie):
            z.lista.append(('COMMIT', None))
        event.listen(db.engine, 'commit', po_commicie)
        try:
            assert _desk(client, 'gluing', naglowki).status_code == 200
        finally:
            event.remove(db.engine, 'commit', po_commicie)

    blokada = next(i for i, (sql, parametry) in enumerate(z.lista)
                   if sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')
                   and 'priorytety_blokada_gluing' in tuple(parametry or ()))
    assert z.lista[blokada - 1] == ('COMMIT', None)
    # odczyty kontroli dostępu (g.device) są PRZED tym commitem
    assert any(sql.startswith('SELECT') and 'FROM prod_devices' in sql for sql, _p in z.lista[:blokada - 1])


# ══ POST /api/mobile/orders/<id>/postpone (Odłóż, spec 5.3, 6.2) ════════════════════════════════════════════

def _postpone(client, pozycja_id, naglowki, stanowisko, zakres='pozycja', powod='brak_materialu', **cialo):
    return client.post('/api/mobile/orders/%d/postpone' % pozycja_id, headers=naglowki,
                       json=dict({'station_code': stanowisko, 'zakres': zakres, 'powod': powod}, **cialo))


def test_postpone_200_zwraca_stol_z_odlozonym(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    a, b, c = order.products
    _kafel('gluing', a)
    _kafel('gluing', b)
    kto = pracownik(imie='Adam', nazwisko='Kowalski')
    naglowki = dict(_operacja(_naglowki('gluing')), **{'X-Worker-Ids': str(kto.id)})

    r = _postpone(client, a.id, naglowki, 'gluing', powod='inne', notatka=u'czekam na szablon')

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert set(dane) == POLA_STOLU
    # stół jak w `desk`, ale BEZ dopełniania: po Odłóż zostaje jeden kafel, następny dociągnie `GET desk`
    assert [w['kafel']['id'] for w in dane['stol']] == [b.id]
    assert dane['kolejka_dalej'] == 1
    (odlozony,) = dane['odlozone']
    assert odlozony['kafel']['id'] == a.id
    assert (odlozony['powod'], odlozony['notatka'], odlozony['pracownik']) == (
        'inne', u'czekam na szablon', u'Adam K.')      # tablet: imię + inicjał nazwiska (spec 6.1)
    assert odlozony['odlozono']
    db.session.rollback()
    assert StationDesk.query.filter(StationDesk.postponed_at.isnot(None)).count() == 1
    (log,) = PriorityLog.query.all()
    assert (log.action, log.worker_id, log.reason) == ('odlozenie', kto.id, 'inne')
    assert log.device_id == ProductionDevice.query.order_by(ProductionDevice.id.desc()).first().id
    assert c.id


def test_postpone_limit_409_bez_wpisu_idempotencji(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    a, b = order.products
    ustaw(stale.klucz_limit('gluing'), 1, 'integer')
    _kafel('gluing', a, odlozony=True)
    _kafel('gluing', b)

    r = _postpone(client, b.id, _operacja(_naglowki('gluing')), 'gluing')

    assert r.status_code == 409
    assert r.get_json() == {
        'error': 'limit_odlozen',
        'message': u'Na Sklejaniu leży 1 odłożona pozycja. Zamknij którąś, zanim odłożysz kolejną.'}
    assert ProcessedMobileOperation.query.count() == 0
    db.session.rollback()
    assert StationDesk.query.filter(StationDesk.postponed_at.isnot(None)).count() == 1


def test_postpone_nie_na_stole_409_bez_wpisu_idempotencji(app, client):
    """Kafel nie leży na stole — np. drugi tablet już go zakończył (spec 6.2)."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))

    r = _postpone(client, order.products[0].id, _operacja(_naglowki('gluing')), 'gluing')

    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'
    assert ProcessedMobileOperation.query.count() == 0 and PriorityLog.query.count() == 0


def test_postpone_zakres_niezgodny_z_jednostka_400(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    naglowki = _naglowki('gluing')

    r = _postpone(client, order.products[0].id, _operacja(naglowki), 'gluing', zakres='zamowienie')
    assert r.status_code == 400 and r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']

    for cialo in ({'zakres': 'kafel'}, {'powod': 5}, {'notatka': 7}, {'notatka': 'x' * 256}):
        r = _postpone(client, order.products[0].id, _operacja(naglowki), 'gluing', **cialo)
        assert r.status_code == 400 and r.get_json()['error'] == 'dane_niepoprawne', cialo
    db.session.rollback()
    assert StationDesk.query.filter(StationDesk.postponed_at.isnot(None)).count() == 0


def test_postpone_powod_niepoprawny_400(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    naglowki = _naglowki('gluing')

    for cialo in ({'powod': 'bo_tak'}, {'powod': 'inne'}, {'powod': 'inne', 'notatka': '  '}):
        r = _postpone(client, order.products[0].id, _operacja(naglowki), 'gluing', **cialo)
        assert r.status_code == 400 and r.get_json()['error'] == 'powod_niepoprawny', cialo
        assert r.get_json()['message']


def test_postpone_order_not_found_404(app, client):
    r = _postpone(client, 987654, _operacja(_naglowki('gluing')), 'gluing')
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_postpone_kafel_zamowienia_po_id_pozycji(app, client):
    """`zakres: zamowienie` — w ścieżce id POZYCJI zamówienia (appka zna id pozycji, jak w `complete`), a odkładany
    jest kafel `o:<order_id>`."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    _kafel('formatting', order)

    r = _postpone(client, order.products[1].id, _operacja(_naglowki('formatting')), 'formatting',
                  zakres='zamowienie', powod='czeka_na_biuro')

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['stol'] == [] and dane['odlozone'][0]['kafel']['zamowienie']['order_id'] == order.id
    assert dane['odlozone'][0]['powod'] == 'czeka_na_biuro'


def test_postpone_powtorka_idempotentna_zwraca_zapisana_odpowiedz(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    naglowki = _operacja(_naglowki('gluing'))

    pierwsza = _postpone(client, order.products[0].id, naglowki, 'gluing')
    druga = _postpone(client, order.products[0].id, naglowki, 'gluing')

    assert (pierwsza.status_code, druga.status_code) == (200, 200)
    assert druga.get_json() == pierwsza.get_json()
    assert PriorityLog.query.filter_by(action='odlozenie').count() == 1
    assert ProcessedMobileOperation.query.count() == 1


def test_postpone_w_trybie_stary_dziala(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    assert stale.TRYBY[0] == 'stary'

    assert _postpone(client, order.products[0].id, _operacja(_naglowki('gluing')), 'gluing').status_code == 200


def test_zakoncz_odlozonego_200(app, client):
    """Odłożony kafel da się zakończyć w każdej chwili (spec 5.3): bramka przepuszcza, wiersz znika, w logu
    `odlozenie_zamkniete`."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja)
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    naglowki = _naglowki('gluing')
    assert _postpone(client, pozycja.id, _operacja(naglowki), 'gluing').status_code == 200

    r = client.post('/api/mobile/orders/%d/complete' % pozycja.id, headers=_operacja(naglowki),
                    json={'station_code': 'gluing'})

    assert r.status_code == 200, r.get_json()
    db.session.rollback()
    assert StationDesk.query.count() == 0
    assert [w.action for w in PriorityLog.query.order_by(PriorityLog.id)] == ['odlozenie', 'odlozenie_zamkniete']


def test_desk_etag_304_i_zmiana_po_odlozeniu(app, client):
    _tryb('gluing')
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    naglowki = _naglowki('gluing')
    etag = _desk(client, 'gluing', naglowki).headers['ETag']
    assert _desk(client, 'gluing', naglowki, etag=etag).status_code == 304

    assert _postpone(client, order.products[0].id, _operacja(naglowki), 'gluing').status_code == 200

    r = _desk(client, 'gluing', naglowki, etag=etag)
    assert r.status_code == 200 and r.headers['ETag'] != etag
    dane = r.get_json()
    assert [w['kafel']['id'] for w in dane['odlozone']] == [order.products[0].id]
    # miejsce po odłożonym zajmuje następny kafel z kolejki
    assert [w['kafel']['id'] for w in dane['stol']] == [order.products[1].id, order.products[2].id]


# ══ Pole `priorytet` w serializerze, KSZTALT 6 (spec 6.1, 6.3) ══════════════════════════════════════════════

def _trasa(nazwa, status, zamowienia, data=None):
    """Trasa z przystankami i własnym szczeblem drabiny (miejsce domyślne: pod pięcioma gwiazdkami). Commituje."""
    from datetime import date, timedelta
    from modules.production.logistics.models import Route, RouteStop
    from modules.production.priorytety.services import drabina
    data = data or date(2026, 10, 8)
    trasa = Route(name=nazwa, date_from=data, date_to=data + timedelta(days=1), status='robocza')
    db.session.add(trasa)
    db.session.flush()
    for i, order in enumerate(zamowienia, start=1):
        db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=i))
    drabina.zapewnij_szczebel_trasy(trasa)
    trasa.status = status
    db.session.commit()
    return trasa


def _priorytet(pozycja, stanowisko='gluing'):
    from modules.production.services.mobile_api_service import serialize_order
    db.session.rollback()
    return serialize_order(db.session.get(ProductionProduct, pozycja.id), station_code=stanowisko)['priorytet']


def test_serialize_order_ma_priorytet_i_ksztalt_6(app):
    from modules.production.services.mobile_api_service import serialize_order
    drabina_domyslna()
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'), priority_stars=2, priority_rung=7,
                       priority_rank=4)

    dto = serialize_order(order.products[1], station_code='gluing')

    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 6
    assert dto['priorytet'] == {'gwiazdki': 2, 'szczebel': 'gwiazdki', 'trasa': None, 'pozycja_w_zamowieniu': '2/2'}
    # pola dla starej appki zostają
    assert 'priority_rank' in dto and 'is_priority' in dto
    klucze = list(dto)
    assert klucze.index('priorytet') == klucze.index('is_priority') + 1


@pytest.mark.parametrize('rung, szczebel', [
    (1, 'gwiazdki'), (2, 'po_terminie'), (4, 'blisko_terminu'), (5, 'rozpoczete'), (9, 'gwiazdki'),
    (None, None), (0, None), (77, None),
])
def test_priorytet_szczebel_z_rangi_i_drabiny(app, rung, szczebel):
    """Rodzaj szczebla = wiersz drabiny pod indeksem WIDOCZNYM z `prod_orders.priority_rung`; brak rangi
    (zamówienie jeszcze nieprzeliczone) albo indeks spoza drabiny → null."""
    drabina_domyslna()
    order = zamowienie(statusy=('czeka_na_sklejanie',), priority_rung=rung, priority_stars=3)

    assert _priorytet(order.products[0]) == {
        'gwiazdki': 3, 'szczebel': szczebel, 'trasa': None, 'pozycja_w_zamowieniu': '1/1'}


def test_priorytet_trasa_z_id_nazwa_i_data(app):
    drabina_domyslna()
    order = zamowienie(sposob=s.TRANSPORT, statusy=('czeka_na_sklejanie',))
    trasa = _trasa(u'Śląsk', 'zatwierdzona', [order])
    order.priority_rung = 2                 # szczebel trasy stoi pod pięcioma gwiazdkami
    db.session.commit()

    assert _priorytet(order.products[0]) == {
        'gwiazdki': 0, 'szczebel': 'trasa', 'trasa': {'id': trasa.id, 'nazwa': u'Śląsk', 'data': '2026-10-08'},
        'pozycja_w_zamowieniu': '1/1'}


def test_priorytet_szczebel_po_indeksie_widocznym(app):
    """`priority_rung` to indeks wśród szczebli WIDOCZNYCH. Szczebel trasy załadowanej zostaje w tabeli (ukryty)
    i nie może przesuwać numeracji: indeks 2 to „Po terminie”, nie ukryta trasa."""
    drabina_domyslna()
    na_trasie = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    _trasa(u'Mazowsze', 'zaladowana', [na_trasie])
    order = zamowienie(statusy=('czeka_na_sklejanie',), priority_rung=2)

    assert _priorytet(order.products[0])['szczebel'] == 'po_terminie'


def test_priorytet_dorobka(app):
    drabina_domyslna()
    order = zamowienie(statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'), priority_rung=1, priority_stars=5)
    dorobka = produkt(order, status='czeka_na_sklejanie', sekwencja=2, original_product_id=order.products[1].id)
    db.session.commit()

    # doróbka ma własną plakietkę i miejsce ORYGINAŁU w zamówieniu (nie jest trzecią pozycją)
    assert _priorytet(dorobka) == {'gwiazdki': 5, 'szczebel': 'dorobka', 'trasa': None,
                                   'pozycja_w_zamowieniu': '2/2'}
    assert _priorytet(order.products[1], 'packaging')['pozycja_w_zamowieniu'] == '2/2'


def test_priorytet_pozycja_w_zamowieniu_pomija_anulowane(app):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'anulowane', 'czeka_na_sklejanie'))
    pierwsza, anulowana, ostatnia = order.products

    assert _priorytet(pierwsza)['pozycja_w_zamowieniu'] == '1/2'
    assert _priorytet(ostatnia)['pozycja_w_zamowieniu'] == '2/2'
    assert _priorytet(anulowana)['pozycja_w_zamowieniu'] is None


def test_priorytet_dorobka_po_anulowanym_oryginale(app):
    """Oryginał odrzucony w całości jest anulowany, ale jego miejsce w zamówieniu zajmuje doróbka."""
    order = zamowienie(statusy=('czeka_na_sklejanie', 'anulowane'))
    dorobka = produkt(order, status='czeka_na_wyciecie', sekwencja=2, original_product_id=order.products[1].id)
    db.session.commit()

    assert _priorytet(dorobka, 'cutting')['pozycja_w_zamowieniu'] == '2/2'
    assert _priorytet(order.products[0])['pozycja_w_zamowieniu'] == '1/2'


def _lista(client, stanowisko, naglowki, etag=None):
    naglowki = dict(naglowki)
    if etag:
        naglowki['If-None-Match'] = etag
    return client.get('/api/mobile/stations/%s/orders' % stanowisko, headers=naglowki)


def test_lista_stanowiska_ma_priorytet_na_kazdej_pozycji(app, client):
    drabina_domyslna()
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_formatowanie'), priority_rung=6, priority_stars=3)

    dane = _lista(client, 'gluing', _naglowki('gluing')).get_json()

    assert [(p['id'], p['priorytet']) for p in dane['orders']] == [
        (order.products[0].id, {'gwiazdki': 3, 'szczebel': 'gwiazdki', 'trasa': None,
                                'pozycja_w_zamowieniu': '1/2'}),
        (order.products[1].id, {'gwiazdki': 3, 'szczebel': 'gwiazdki', 'trasa': None,
                                'pozycja_w_zamowieniu': '2/2'})]


def test_lista_stanowiska_etag_zmienia_sie_po_ksztalcie(app, client):
    """Stara appka z zapamiętanym ETagiem kształtu 5 dostaje pełną listę (200), a nie 304 — inaczej nowe pole
    nie dotarłoby do niej, dopóki w kolejce coś się nie zmieni."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')
    etag = _lista(client, 'gluing', naglowki).headers['ETag']
    assert etag.endswith(':6"')
    assert _lista(client, 'gluing', naglowki, etag=etag).status_code == 304

    stary = etag[:-len(':6"')] + ':5"'
    assert _lista(client, 'gluing', naglowki, etag=stary).status_code == 200


def test_lista_i_delta_licza_kontekst_raz(app, client, monkeypatch):
    """Listy liczą kontekst priorytetu RAZ na żądanie (jedna mapa dla wszystkich pozycji), nie osobno na pozycję."""
    for _ in range(3):
        zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    naglowki = _naglowki('gluing')
    wolania = []
    oryginal = stol.kontekst_priorytetu

    def szpieg(items, **kwargs):
        wolania.append(len(list(items)))
        return oryginal(items, **kwargs)

    monkeypatch.setattr(stol, 'kontekst_priorytetu', szpieg)

    assert _lista(client, 'gluing', naglowki).status_code == 200
    assert wolania == [6]

    del wolania[:]
    r = client.get('/api/mobile/stations/gluing/orders/since?ts=2020-01-01T00:00:00', headers=naglowki)
    assert r.status_code == 200 and len(r.get_json()['changed']) == 6
    assert wolania == [6]
    assert all(p['priorytet']['pozycja_w_zamowieniu'] for p in r.get_json()['changed'])

    del wolania[:]
    r = client.get('/api/mobile/orders/search?q=26/', headers=naglowki)
    assert r.status_code == 200
    assert len(wolania) <= 1

    del wolania[:]
    assert _desk(client, 'gluing', naglowki).status_code == 200
    assert len(wolania) == 1


def test_desk_kafel_ma_priorytet(app, client):
    _tryb('formatting')
    _tryb('gluing')
    drabina_domyslna()
    pozycyjne = zamowienie(statusy=('czeka_na_sklejanie',), priority_rung=3, priority_stars=4)
    zamowieniowe = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'), priority_rung=6,
                              priority_stars=3)

    kafel = _desk(client, 'gluing', _naglowki('gluing')).get_json()['stol'][0]['kafel']
    assert kafel['id'] == pozycyjne.products[0].id
    assert kafel['priorytet'] == {'gwiazdki': 4, 'szczebel': 'gwiazdki', 'trasa': None,
                                  'pozycja_w_zamowieniu': '1/1'}

    kafel = _desk(client, 'formatting', _naglowki('formatting')).get_json()['stol'][0]['kafel']
    assert kafel['zamowienie']['order_id'] == zamowieniowe.id
    # na zamówieniu priorytet bez miejsca pozycji; każda pozycja ma swoje
    assert kafel['zamowienie']['priorytet'] == {'gwiazdki': 3, 'szczebel': 'gwiazdki', 'trasa': None}
    assert [p['priorytet']['pozycja_w_zamowieniu'] for p in kafel['pozycje']] == ['1/2', '2/2']


# ══ K3-poprawka-2: pole `tryb`, `desk` w `stary` tylko do odczytu (spec 6.1, 6.3; rozstrz. 19 centrali) ═══════

def _zapis(sql):
    return sql.startswith(('INSERT', 'UPDATE', 'DELETE'))


def test_desk_oddaje_tryb(app, client):
    """`tryb` w odpowiedzi `desk` i `postpone`: domyślnie `stary`, po przełączeniu w Konfiguracji `stol`."""
    zamowienie(statusy=('czeka_na_sklejanie',) * 2)
    naglowki = _naglowki('gluing')

    dane = _desk(client, 'gluing', naglowki).get_json()
    assert set(dane) == POLA_STOLU and dane['tryb'] == 'stary'

    _tryb('gluing')
    dane = _desk(client, 'gluing', naglowki).get_json()
    assert dane['tryb'] == 'stol'

    r = client.post('/api/mobile/orders/%d/postpone' % dane['stol'][0]['kafel']['id'], headers=_operacja(naglowki),
                    json={'station_code': 'gluing', 'zakres': 'pozycja', 'powod': 'brak_materialu'})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['tryb'] == 'stol'


def test_desk_stary_nie_dopelnia_i_nie_blokuje(app, client, monkeypatch):
    """W trybie `stary` `desk` jest zwykłym odczytem: bez blokady stanowiska, bez odczytów blokujących, bez limitu
    czekania, bez INSERT i bez commita po touchu urządzenia. Kafle leżące na stole (np. startowe po „Przygotuj
    stoły”) widać tylko do odczytu."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    _kafel('gluing', order.products[2], zrodlo='start')
    naglowki = _naglowki('gluing')
    ustawienia_limitu = []
    monkeypatch.setattr(kolejka, '_ma_limit_czekania', lambda polaczenie: True)
    monkeypatch.setattr(kolejka, '_wyslij_ustawienie', lambda polaczenie, sql: ustawienia_limitu.append(sql))
    monkeypatch.setattr(stol, 'dopelnij', lambda *a, **k: pytest.fail('dopełnianie w trybie stary'))
    monkeypatch.setattr(stol, 'zablokuj_stanowisko', lambda *a, **k: pytest.fail('blokada stanowiska w trybie stary'))

    with Zapytania() as z:
        def po_commicie(_polaczenie):
            z.lista.append(('COMMIT', None))
        event.listen(db.engine, 'commit', po_commicie)
        try:
            r = _desk(client, 'gluing', naglowki)
        finally:
            event.remove(db.engine, 'commit', po_commicie)

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['tryb'] == 'stary'
    assert [(w['kafel']['id'], w['zrodlo']) for w in dane['stol']] == [(order.products[2].id, 'start')]
    assert dane['kolejka_dalej'] == 2
    assert ustawienia_limitu == []
    assert [sql for sql, _p in z.lista if sql.startswith('SELECT') and sql.endswith(
        (' FOR UPDATE', ' LOCK IN SHARE MODE'))] == []
    # jedyny zapis i jedyny commit to touch urządzenia w `require_device_token` (przed handlerem)
    zapisy = [sql for sql, _p in z.lista if _zapis(sql)]
    assert len(zapisy) == 1 and zapisy[0].startswith('UPDATE prod_devices')
    assert [sql for sql, _p in z.lista].count('COMMIT') == 1
    assert z.pierwsze(lambda sql: sql == 'COMMIT') > z.pierwsze(lambda sql: sql.startswith('UPDATE prod_devices'))
    assert not any(str(p).startswith('priorytety_blokada_') for _sql, parametry in z.lista
                   for p in (parametry or ()))
    db.session.rollback()
    assert StationDesk.query.count() == 1


def test_desk_stary_bez_sygnalu(app, client, monkeypatch):
    zamowienie(statusy=('czeka_na_sklejanie',))
    wyslane = []
    monkeypatch.setattr(mobile_api.sygnaly, 'wyslij', lambda *kody: wyslane.append(kody))

    assert _desk(client, 'gluing', _naglowki('gluing')).status_code == 200
    assert wyslane == []


def test_desk_stol_dopelnia(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    _tryb('gluing')

    dane = _desk(client, 'gluing', _naglowki('gluing')).get_json()

    assert dane['tryb'] == 'stol'
    assert [w['kafel']['id'] for w in dane['stol']] == [order.products[0].id, order.products[1].id]
    db.session.rollback()
    assert StationDesk.query.count() == 2


def test_desk_przelaczenie_trybu_miedzy_wywolaniami(app, client):
    """`stary` → `stol` → `stary`: ETag zmienia się przy każdym przełączeniu (tablet z zapamiętanym ETagiem nie
    dostaje 304 ze starym trybem), stół dopełnia się dopiero w `stol`, a po powrocie do `stary` nic nie dochodzi."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    naglowki = _naglowki('gluing')

    r = _desk(client, 'gluing', naglowki)
    etag_stary = r.headers['ETag']
    assert r.get_json()['tryb'] == 'stary' and r.get_json()['stol'] == []
    assert _desk(client, 'gluing', naglowki, etag=etag_stary).status_code == 304

    _tryb('gluing')
    r = _desk(client, 'gluing', naglowki, etag=etag_stary)
    assert r.status_code == 200
    assert r.get_json()['tryb'] == 'stol' and len(r.get_json()['stol']) == 2
    etag_stol = r.headers['ETag']

    _tryb('gluing', 'stary')
    db.session.execute(_STOL.delete().where(_STOL.c.product_id == order.products[0].id))
    db.session.commit()
    r = _desk(client, 'gluing', naglowki, etag=etag_stol)
    assert r.status_code == 200
    assert r.get_json()['tryb'] == 'stary'
    assert [w['kafel']['id'] for w in r.get_json()['stol']] == [order.products[1].id]     # bez dopełnienia
    db.session.rollback()
    assert StationDesk.query.count() == 1


def test_desk_etag_zalezy_od_trybu_i_ksztaltu_stolu(app, client, monkeypatch):
    """Ten sam stół, inny tryb → inny ETag; podbity `KSZTALT_ODPOWIEDZI_STOLU` (2: pole `tryb`) → inny ETag."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    assert mobile_api.KSZTALT_ODPOWIEDZI_STOLU == 2
    with app.test_request_context():
        stary = mobile_api._etag_stolu('gluing')
        _tryb('gluing')
        stol_etag = mobile_api._etag_stolu('gluing')
        monkeypatch.setattr(mobile_api, 'KSZTALT_ODPOWIEDZI_STOLU', 1)
        poprzedni_ksztalt = mobile_api._etag_stolu('gluing')
    assert len({stary, stol_etag, poprzedni_ksztalt}) == 3


def test_desk_lakiernia_409_w_obu_trybach(app, client):
    for tryb in ('stary', 'stol'):
        _tryb('painting', tryb)
        r = _desk(client, 'painting', _naglowki('painting'))
        assert r.status_code == 409 and r.get_json()['error'] == 'stanowisko_bez_stolu'
    assert StationDesk.query.count() == 0
