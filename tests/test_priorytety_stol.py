# -*- coding: utf-8 -*-
"""
Stół stanowiska (priorytety produkcji, krok K3; spec 2026-10-04, sekcje 5.1–5.8, 9.2, 9.4): zdjęcie kafla
u każdego pisarza, bramka ZAKOŃCZ, dopełnianie, Odłóż, „Wyślij na stanowisko”, start stołów.

SQLite nie ma blokad wierszy ani migawki MySQL, więc kolejności blokad pilnujemy na kolejności zapytań
(tests/blokady_pomocnicze.py: `Zapytania` dopisuje klauzulę blokady tak, jak wysłałby ją MySQL), a odczyt bieżący
— cudzym zapisem wstrzykniętym surowym SQL-em „za plecami” sesji.

Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import itertools
from datetime import datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import (
    ProcessedMobileOperation, ProductionDevice, ProductionOrder, ProductionProduct)
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, StationDesk
from modules.production.priorytety.services import drabina, kolejka, stol, widok
from modules.production.routers import mobile_api
from modules.production.services import rework_service
from modules.production.services.mobile_api_service import generate_token
from modules.production.services.sync_service import BaselinkerSyncService
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, odczyt_biezacy_pozycji_wielu_zamowien, odczyt_biezacy_zamowien)
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, ustaw  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia')

_licznik = itertools.count(1)
_POZYCJE = ProductionProduct.__table__
_STOL = StationDesk.__table__
T0 = datetime(2026, 10, 5, 8, 0)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Wyjście z produkcji i spakowanie planują status Base. po commicie — w testach go nie wysyłamy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


# ── pomocniki ───────────────────────────────────────────────────────────────────────────────────────────────

def _urzadzenie(stanowisko, wersja=None):
    """Tablet stanowiska; `wersja` = kod wersji appki z heartbeatu (None = tablet bez heartbeatu)."""
    device = ProductionDevice(device_id='TAB-STOL-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko, last_app_version_code=wersja)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(stanowisko, wersja=None):
    """Nagłówki tabletu stanowiska z NOWYM `X-Operation-Id`."""
    return _nowa_operacja({'Authorization': 'Bearer ' + generate_token(_urzadzenie(stanowisko, wersja))})


def _nowa_operacja(naglowki):
    return dict(naglowki, **{'X-Operation-Id': 'op-stol-%d' % next(_licznik)})


def _tryb(stanowisko, tryb='stol'):
    ustaw(stale.klucz_tryb(stanowisko), tryb)


def _prog_wersji(kod):
    ustaw(stale.KLUCZ_MIN_APP, kod, 'integer')


def _miejsca(stanowisko, ile):
    ustaw(stale.klucz_stol(stanowisko), ile, 'integer')


def _kafel(stanowisko, obiekt, odlozony=False, zrodlo='kolejka', pobrano=T0, **kolumny):
    """Wiersz stołu dla pozycji (kafel `p:`) albo zamówienia (kafel `o:`). Commituje. Zwraca id wiersza."""
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


def _klucze(stanowisko=None):
    """Klucze wierszy stołu z bazy (świeży odczyt), posortowane."""
    db.session.rollback()
    zapytanie = db.session.query(StationDesk.station_code, StationDesk.unit_key)
    if stanowisko is not None:
        zapytanie = zapytanie.filter(StationDesk.station_code == stanowisko)
    return sorted('%s/%s' % tuple(wiersz) for wiersz in zapytanie.all())


def _zakoncz(client, pozycja_id, naglowki, stanowisko):
    return client.post('/api/mobile/orders/%d/complete' % pozycja_id, headers=naglowki,
                       json={'station_code': stanowisko})


def _licz(client, pozycja_id, naglowki, stanowisko, ile=1):
    return client.patch('/api/mobile/orders/%d/quantity' % pozycja_id, headers=naglowki,
                        json={'station_code': stanowisko, 'quantity_done': ile})


def _status(pozycja_id):
    db.session.rollback()
    return db.session.query(ProductionProduct.current_status).filter(ProductionProduct.id == pozycja_id).scalar()


def _odczyt_stolu(sql):
    return sql.startswith('SELECT') and 'FROM prod_station_desk' in sql


def _blokujacy(sql):
    return sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))


def _stol_po_kluczu(sql):
    """Odczyt bieżący WŁASNEGO kafla: po (station_code, unit_key), FOR UPDATE."""
    return (_odczyt_stolu(sql) and 'prod_station_desk.unit_key = ?' in sql.split(' WHERE ', 1)[-1]
            and sql.endswith(' FOR UPDATE'))


def _stol_po_zamowieniu(sql):
    """Odczyt bieżący wierszy stołu WŁASNEGO zamówienia: po order_id, FOR UPDATE."""
    return (_odczyt_stolu(sql) and 'WHERE prod_station_desk.order_id = ?' in sql and sql.endswith(' FOR UPDATE'))


def _po_resolve_workers(monkeypatch, akcja):
    """Przelotka na mobile_api._resolve_workers: po prawdziwym wywołaniu (ostatni krok handlera przed blokadami)
    wykonuje `akcja()` — cudzy zapis „po migawce” żądania."""
    oryginal = mobile_api._resolve_workers

    def przelotka():
        wynik = oryginal()
        akcja()
        return wynik

    monkeypatch.setattr(mobile_api, '_resolve_workers', przelotka)


# ── stol.py: klucze, zdjęcie kafla ──────────────────────────────────────────────────────────────────────────

def test_unit_key_pozycji_i_zamowienia(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    assert stol.unit_key(order.products[0]) == 'p:%d' % order.products[0].id
    assert stol.unit_key(order) == 'o:%d' % order.id
    assert (stol.KAFEL_POZYCJA, stol.KAFEL_ZAMOWIENIE) == ('p', 'o')


def test_zdejmij_kafel_usuwa_wiersz_i_loguje_zamkniecie_odlozenia(app):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    odlozona, zwykla = order.products
    _kafel('gluing', odlozona, odlozony=True)
    _kafel('gluing', zwykla)

    assert stol.zdejmij_kafel(odlozona, 'gluing', teraz=T0, worker_id=7, device_id=3,
                              zamkniecie_odlozenia=True) is True
    assert stol.zdejmij_kafel(zwykla, 'gluing', zamkniecie_odlozenia=True) is True
    assert stol.zdejmij_kafel(zwykla, 'gluing') is False          # już go nie ma
    db.session.commit()

    assert _klucze() == []
    logi = PriorityLog.query.all()
    assert len(logi) == 1                                          # tylko kafel odłożony zostawia ślad
    assert (logi[0].action, logi[0].order_id, logi[0].product_id, logi[0].station_code) == (
        'odlozenie_zamkniete', order.id, odlozona.id, 'gluing')
    assert (logi[0].reason, logi[0].note, logi[0].worker_id, logi[0].device_id) == (
        'brak_materialu', u'czekamy na dąb', 7, 3)
    assert logi[0].old_value == T0.isoformat(timespec='seconds')


def test_zdejmij_nieaktualne_zostawia_kafel_na_stanowisku(app):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_formatowanie'))
    na_sklejaniu, dalej = order.products
    _kafel('gluing', na_sklejaniu)
    _kafel('gluing', dalej)                 # pozycja poszła dalej, a jej kafel został

    assert stol.zdejmij_nieaktualne(order) == {'gluing'}
    db.session.commit()

    assert _klucze() == ['gluing/p:%d' % na_sklejaniu.id]


def test_zdejmij_nieaktualne_usuwa_kafel_zamowienia_gdy_niekompletne(app):
    """Kafel-zamówienie z kolejki leży na Formatowaniu tylko, gdy zamówienie jest tam kompletne (spec 5.6 p. 2):
    doróbka cofnięta przed Formatowanie zdejmuje kafel."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    _kafel('formatting', order)
    assert stol.zdejmij_nieaktualne(order) == set()

    order.products[1].current_status = 'czeka_na_sklejanie'
    assert stol.zdejmij_nieaktualne(order) == {'formatting'}
    db.session.commit()
    assert _klucze() == []


def _z_omijajaca(status_omijajacej='czeka_na_sklejanie', status_zwyklej='czeka_na_formatowanie'):
    """Zamówienie z pytania 8 raportu K3: pozycja z docięciem na `status_zwyklej` i pozycja BEZ docięcia
    (`cut_to_size=False` — ścieżka omija Formatowanie i Krawędzie) na `status_omijajacej`."""
    order = zamowienie(statusy=(status_zwyklej,))
    produkt(order, status=status_omijajacej, sekwencja=2, cut_to_size=False)
    db.session.commit()
    return order


def test_kompletne_na_bez_pozycji_omijajacej_stanowisko(app):
    """K3-poprawka-1 (spec 5.6 p. 2): pozycja bez docięcia stojąca przed Formatowaniem nie liczy się do jego
    kompletności; do kompletności Pakowania — liczy się."""
    order = _z_omijajaca()
    assert stol.kompletne_na(order, 'formatting') is True
    pakowane = _z_omijajaca(status_zwyklej='czeka_na_pakowanie')
    assert stol.kompletne_na(pakowane, 'packaging') is False
    zwykle = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    assert stol.kompletne_na(zwykle, 'formatting') is False


def test_zdejmij_nieaktualne_zostawia_kafel_gdy_wczesniej_tylko_omijajaca(app):
    order = _z_omijajaca()
    _kafel('formatting', order)

    assert stol.zdejmij_nieaktualne(order) == set()
    db.session.commit()
    assert _klucze() == ['formatting/o:%d' % order.id]


def test_zdejmij_nieaktualne_zostawia_niekompletny_kafel_wyslany_przez_biuro(app):
    """Kafle `biuro` i `start` biuro kładzie świadomie także dla niekompletnych zamówień (spec 5.7, 5.8) — leżą,
    dopóki zamówienie ma na stanowisku choć jedną pozycję."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    _kafel('formatting', order, zrodlo='biuro')
    assert stol.zdejmij_nieaktualne(order) == set()

    order.products[0].current_status = 'czeka_na_krawedzie'       # ostatnia pozycja zeszła z Formatowania
    assert stol.zdejmij_nieaktualne(order) == {'formatting'}


def test_zdejmij_nieaktualne_usuwa_kafel_innej_jednostki_i_usunietej_pozycji(app):
    """Wiersz z kluczem innej jednostki niż bieżąca jednostka stanowiska jest nieaktualny (raport K2); tak samo
    wiersz pozycji, której nie ma już w zamówieniu (SQLite nie robi kaskady FK)."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    na_formatowaniu, na_sklejaniu = order.products
    _kafel('formatting', na_formatowaniu)                         # Formatowanie ma jednostkę `zamowienie`
    db.session.execute(_STOL.insert().values(station_code='gluing', order_id=order.id, product_id=987654,
                                             unit_key='p:987654', pulled_at=T0, zrodlo='kolejka'))
    db.session.commit()
    _kafel('gluing', na_sklejaniu)

    assert stol.zdejmij_nieaktualne(order) == {'formatting', 'gluing'}
    db.session.commit()
    assert _klucze() == ['gluing/p:%d' % na_sklejaniu.id]


def test_zdejmij_nieaktualne_widzi_kafel_wstawiony_po_migawce(app):
    """`dopelnij` wstawia i zatwierdza kafel po migawce żądania pisarza, a przed jego blokadą zamówienia. Zwykły
    odczyt stołu na MySQL by go nie zobaczył — dlatego wiersze stołu zamówienia czytamy odczytem BIEŻĄCYM."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    assert StationDesk.query.filter_by(station_code='gluing').all() == []      # „migawka”: stół pusty
    db.session.execute(_STOL.insert().values(station_code='gluing', order_id=order.id, product_id=pozycja.id,
                                             unit_key='p:%d' % pozycja.id, pulled_at=T0, zrodlo='kolejka'))
    pozycja.current_status = 'czeka_na_formatowanie'

    with Zapytania() as z:
        assert stol.zdejmij_nieaktualne(order) == {'gluing'}
    db.session.commit()

    assert _klucze() == []
    odczyty = [sql for sql, _p in z.lista if _odczyt_stolu(sql)]
    assert len(odczyty) == 1 and _stol_po_zamowieniu(odczyty[0])
    # UPDATE pozycji pisarza idzie do bazy PRZED blokadą wierszy stołu
    assert z.pierwsze(lambda sql: sql.startswith('UPDATE prod_products')) < z.pierwsze(_stol_po_zamowieniu)


# ── ZAKOŃCZ zdejmuje kafel (Review Focus 3) ─────────────────────────────────────────────────────────────────

def test_zakoncz_zdejmuje_kafel_pozycji(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    pierwsza, druga = order.products
    _kafel('gluing', pierwsza)
    _kafel('gluing', druga)

    r = _zakoncz(client, pierwsza.id, _naglowki('gluing'), 'gluing')

    assert r.status_code == 200, r.get_json()
    assert _status(pierwsza.id) == 'czeka_na_formatowanie'
    assert _klucze() == ['gluing/p:%d' % druga.id]
    assert PriorityLog.query.count() == 0


def test_zakoncz_ostatniej_pozycji_zdejmuje_kafel_zamowienia(app, client):
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    pierwsza, druga = order.products
    _kafel('formatting', order)
    naglowki = _naglowki('formatting')

    assert _zakoncz(client, pierwsza.id, naglowki, 'formatting').status_code == 200
    assert _klucze() == ['formatting/o:%d' % order.id]             # druga pozycja dalej czeka na Formatowaniu

    assert _zakoncz(client, druga.id, _nowa_operacja(naglowki), 'formatting').status_code == 200
    assert _klucze() == []


def test_zakoncz_odlozonego_loguje_odlozenie_zamkniete(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja, odlozony=True)
    naglowki = _naglowki('gluing')
    device_pk = ProductionDevice.query.order_by(ProductionDevice.id.desc()).first().id

    assert _zakoncz(client, pozycja.id, naglowki, 'gluing').status_code == 200

    assert _klucze() == []
    logi = PriorityLog.query.all()
    assert [(w.action, w.order_id, w.product_id, w.station_code, w.reason, w.device_id) for w in logi] == [
        ('odlozenie_zamkniete', order.id, pozycja.id, 'gluing', 'brak_materialu', device_pk)]


def test_zakoncz_odlozonego_kafla_zamowienia_loguje_dopiero_gdy_kafel_znika(app, client):
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    pierwsza, druga = order.products
    _kafel('formatting', order, odlozony=True)
    naglowki = _naglowki('formatting')

    assert _zakoncz(client, pierwsza.id, naglowki, 'formatting').status_code == 200
    assert PriorityLog.query.count() == 0 and _klucze() == ['formatting/o:%d' % order.id]

    assert _zakoncz(client, druga.id, _nowa_operacja(naglowki), 'formatting').status_code == 200
    assert [w.action for w in PriorityLog.query.all()] == ['odlozenie_zamkniete'] and _klucze() == []


def test_hurt_wstrzymanie_zdejmuje_kafel(app):
    """Hurtowa zmiana statusu wołana wprost (`_zapisz_zmiane_statusu`) — bez rejestrowania całego API produkcji
    w aplikacji testowej logistyki."""
    from modules.production.routers.api import products_api
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    wstrzymywana, zostaje = order.products
    _kafel('gluing', wstrzymywana)
    _kafel('gluing', zostaje)

    wynik = products_api._zapisz_zmiane_statusu([wstrzymywana.id], 'wstrzymane', None)

    assert wynik['success'] is True and wynik['processed_count'] == 1
    assert wynik['zdjete_stanowiska'] == ['gluing']
    assert _klucze() == ['gluing/p:%d' % zostaje.id]


def test_hurt_anulowanie_i_inny_status_zdejmuja_kafle(app):
    from modules.production.routers.api import products_api
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie', 'czeka_na_formatowanie'))
    anulowana, przesunieta, na_formatowaniu = order.products
    _kafel('gluing', anulowana)
    _kafel('gluing', przesunieta)

    products_api._zapisz_zmiane_statusu([anulowana.id], 'anulowane', None)
    wynik = products_api._zapisz_zmiane_statusu([przesunieta.id], 'czeka_na_formatowanie', None)

    assert wynik['zdjete_stanowiska'] == ['gluing']
    assert _klucze() == []


def test_base_usuniecie_pozycji_zdejmuje_kafel(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    usuwana, zostaje = order.products
    _kafel('gluing', usuwana)
    _kafel('gluing', zostaje)
    bl_id, zostaje_id = order.baselinker_order_id, zostaje.id

    wynik = BaselinkerSyncService().apply_baselinker_changes(
        bl_id, {'products_to_remove': [{'id': usuwana.id, 'short_product_id': usuwana.short_product_id}]})

    assert wynik['success'] is True and wynik['removed'] == 1, wynik
    assert wynik['zdjete_stanowiska'] == ['gluing']
    assert _klucze() == ['gluing/p:%d' % zostaje_id]


def test_base_nowa_pozycja_zdejmuje_kafel_zamowienia_na_pakowaniu(app, monkeypatch):
    """Nowa pozycja z Base. zaczyna od Wycinania, więc zamówienie przestaje być kompletne na Pakowaniu."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), numer_wewnetrzny='1450')
    _kafel('packaging', order)
    serwis = BaselinkerSyncService()
    order_id = order.id
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr(serwis, '_create_production_product_from_data', lambda dane: ProductionProduct(
        order_id=order_id, short_product_id=dane['short_product_id'],
        product_sequence_in_order=dane['product_sequence_in_order'],
        original_product_name=dane['original_product_name'], quantity=1, current_status='czeka_na_wyciecie'))
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)

    wynik = serwis.apply_baselinker_changes(order.baselinker_order_id,
                                            {'products_to_add': [{'order_product_id': '77'}]})

    assert wynik['success'] is True and wynik['added'] == 1, wynik
    assert wynik['zdjete_stanowiska'] == ['packaging']
    assert _klucze() == []


def test_dorobka_zdejmuje_kafel_zamowienia_na_formatowaniu(app):
    """Doróbka z Formatowania wraca na początek procesu: zamówienie nie jest już kompletne na Formatowaniu."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    _kafel('formatting', order)

    rework_service.reject_product_quantity(product_id=order.products[0].id, quantity=1, reason_category='wymiary',
                                           rejected_at_station='formatting')

    assert _klucze() == []


def test_dorobka_oryginal_anulowany_zdejmuje_kafel_pozycji(app):
    """Odrzucenie wszystkich sztuk anuluje oryginał — jego kafel na Krawędziach znika."""
    order = zamowienie(statusy=('czeka_na_krawedzie', 'czeka_na_krawedzie'))
    odrzucana, zostaje = order.products
    _kafel('edges', odrzucana)
    _kafel('edges', zostaje)

    rework_service.reject_product_quantity(product_id=odrzucana.id, quantity=2, reason_category='jakosc_krawedzi',
                                           rejected_at_station='edges')

    assert _status(odrzucana.id) == 'anulowane'
    assert _klucze() == ['edges/p:%d' % zostaje.id]


def test_cron_osierocone_zdejmuje_kafel(app, client, monkeypatch):
    """Cron przenosi pozycję z archiwalnego `czeka_na_logistyke` do pakowania: kafel pozycji z innego stanowiska
    znika, a kafel zamówienia na Pakowaniu (teraz kompletnego) zostaje."""
    from modules.production.logistics.services import bl_sync, geocoding
    from modules.production.priorytety.services import kolejka
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': True})
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_logistyke'))
    w_pakowaniu, osierocona = order.products
    _kafel('packaging', order)
    _kafel('edges', osierocona)             # taki kafel nie powinien istnieć — cron sprząta go przy okazji

    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})

    assert r.status_code == 200 and r.get_json()['przeniesione_z_logistyki'] == 1
    assert _klucze() == ['packaging/o:%d' % order.id]


def test_zdjecie_kafla_po_blokadzie_zamowienia_i_pozycji(app, client):
    """Kolejność ZAKOŃCZ w trybie `stol` (spec 9.4): zamówienie → pozycje → własny kafel (bramka) → UPDATE pozycji
    → wiersze stołu własnego zamówienia → DELETE. Nikt nie blokuje wierszy stołu całego stanowiska."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja)
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        r = _zakoncz(client, pozycja.id, naglowki, 'gluing')

    assert r.status_code == 200, r.get_json()
    kolejnosc = [z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(_stol_po_kluczu),
                 z.pierwsze(lambda sql: sql.startswith('UPDATE prod_products')), z.pierwsze(_stol_po_zamowieniu),
                 z.pierwsze(lambda sql: sql.startswith('DELETE FROM prod_station_desk'))]
    assert kolejnosc == sorted(kolejnosc), kolejnosc
    blokujace = [sql for sql, _p in z.lista if _odczyt_stolu(sql) and _blokujacy(sql)]
    assert blokujace and all(_stol_po_kluczu(sql) or _stol_po_zamowieniu(sql) for sql in blokujace)
    # ZAKOŃCZ nie bierze blokady stołu stanowiska (bierze ją tylko dopełnianie we własnym żądaniu)
    assert not [1 for _sql, parametry in z.lista
                if any(str(p).startswith('priorytety_blokada_') for p in (parametry or ()))]


# ── bramka ZAKOŃCZ (Review Focus 4) ─────────────────────────────────────────────────────────────────────────

def test_bramka_409_nie_na_stole_w_trybie_stol(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',), numer_wewnetrzny='1234')
    pozycja = order.products[0]
    _tryb('gluing')

    r = _zakoncz(client, pozycja.id, _naglowki('gluing'), 'gluing')

    assert r.status_code == 409
    assert r.get_json()['error'] == 'nie_na_stole'
    assert r.get_json()['message'] == u'Zamówienie 1234 nie leży na stole Sklejania.'
    assert _status(pozycja.id) == 'czeka_na_sklejanie'


def test_bramka_przepuszcza_kafel_na_stole(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    _tryb('gluing')

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing'), 'gluing').status_code == 200
    assert _klucze() == []


def test_bramka_przepuszcza_odlozony(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0], odlozony=True)
    _tryb('gluing')

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing'), 'gluing').status_code == 200
    assert _klucze() == []


def test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia(app, client):
    """Stanowisko zamówieniowe (spec 5.6 p. 2): pozycję zamówienia NIEKOMPLETNEGO wolno formatować bez wiersza
    stołu (sekcja „Niekompletne” nie jest zapisana); kompletne zamówienie bez wiersza → 409."""
    niekompletne = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    kompletne = zamowienie(statusy=('czeka_na_formatowanie',))
    _tryb('formatting')
    naglowki = _naglowki('formatting')

    assert _licz(client, niekompletne.products[0].id, naglowki, 'formatting').status_code == 200
    assert _zakoncz(client, niekompletne.products[0].id, _nowa_operacja(naglowki), 'formatting').status_code == 200

    r = _zakoncz(client, kompletne.products[0].id, _nowa_operacja(naglowki), 'formatting')
    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'
    assert _licz(client, kompletne.products[0].id, _nowa_operacja(naglowki), 'formatting').status_code == 409


def test_bramka_zakoncz_zamowienie_kompletne_mimo_omijajacej(app, client):
    """Zamówienie, któremu przed Formatowaniem została tylko pozycja bez docięcia, jest KOMPLETNE — nie korzysta
    z furtki „Niekompletne”, więc bez wiersza stołu ZAKOŃCZ dostaje 409, a z wierszem przechodzi."""
    order = _z_omijajaca()
    _tryb('formatting')
    naglowki = _naglowki('formatting')

    r = _zakoncz(client, order.products[0].id, naglowki, 'formatting')
    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'

    _kafel('formatting', order)
    assert _zakoncz(client, order.products[0].id, _nowa_operacja(naglowki), 'formatting').status_code == 200
    assert _klucze() == []


def test_bramka_widzi_kafel_wstawiony_po_migawce(app, client, monkeypatch):
    """Kafel wstawiony przez dopełnianie innego tabletu po migawce żądania: bramka czyta własny wiersz odczytem
    bieżącym pod blokadą zamówienia, więc ZAKOŃCZ przechodzi."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _tryb('gluing')
    naglowki = _naglowki('gluing')
    wiersz = dict(station_code='gluing', order_id=order.id, product_id=pozycja.id, unit_key='p:%d' % pozycja.id,
                  pulled_at=T0, zrodlo='kolejka')

    def cudzy_zapis():
        assert StationDesk.query.filter_by(station_code='gluing').all() == []      # „migawka”: stół pusty
        db.session.execute(_STOL.insert().values(**wiersz))

    _po_resolve_workers(monkeypatch, cudzy_zapis)
    with Zapytania() as z:
        r = _zakoncz(client, pozycja.id, naglowki, 'gluing')

    assert r.status_code == 200, r.get_json()
    assert z.pierwsze(blokada_pozycji) < z.pierwsze(_stol_po_kluczu)
    assert _klucze() == []


def test_bramka_pakowanie_bez_sposobu_dostawy_tylko_bramka_stolu(app, client):
    """Po logistyce 4.6 (spec 5.1, 5.5) sposób dostawy niczego nie blokuje: Pakowanie bez sposobu poza stołem dostaje
    zwykłe 409 `nie_na_stole`, a leżące na stole spakuje się normalnie (dawniej 409 `delivery_method_not_set`)."""
    order = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',))
    _tryb('packaging')

    r = _zakoncz(client, order.products[0].id, _naglowki('packaging'), 'packaging')
    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'

    _kafel('packaging', order)
    r = _zakoncz(client, order.products[0].id, _naglowki('packaging'), 'packaging')

    assert r.status_code == 200, r.get_json()
    assert _status(order.products[0].id) == 'spakowane'
    assert _klucze() == []


def test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel(app, client):
    """Tablet z wersją poniżej progu dostaje zachowanie `stary` (spec 5.5): ZAKOŃCZ bez bramki, a kafel — jeśli
    leżał — schodzi ze stołu."""
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    z_kaflem, bez_kafla = order.products
    _kafel('gluing', z_kaflem)
    _tryb('gluing')
    _prog_wersji(100)
    naglowki = _naglowki('gluing', wersja=50)

    assert _zakoncz(client, z_kaflem.id, naglowki, 'gluing').status_code == 200
    assert _klucze() == []
    assert _zakoncz(client, bez_kafla.id, _nowa_operacja(naglowki), 'gluing').status_code == 200


def test_bramka_tablet_bez_heartbeatu_to_stara_appka(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _tryb('gluing')
    _prog_wersji(100)

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing', wersja=None), 'gluing').status_code == 200


def test_bramka_nowa_appka_ponad_progiem_ma_bramke(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _tryb('gluing')
    _prog_wersji(100)

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing', wersja=100), 'gluing').status_code == 409


def test_bramka_prog_zero_to_brak_bramki_wersji(app, client):
    """Próg 0 (domyślny) = nie ma bramki wersji: w trybie `stol` bramka stołu obowiązuje każdego."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _tryb('gluing')
    _prog_wersji(0)

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing', wersja=None), 'gluing').status_code == 409


def test_tryb_stary_bez_bramki(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        r = _zakoncz(client, order.products[0].id, naglowki, 'gluing')

    assert r.status_code == 200
    # w trybie `stary` bramka nie czyta stołu; jedyny odczyt stołu to uzgodnienie po ZAKOŃCZ
    assert [sql for sql, _p in z.lista if _odczyt_stolu(sql) and not _stol_po_zamowieniu(sql)] == []


def test_licznik_409_nie_na_stole_w_trybie_stol(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    na_stole, poza = order.products
    _kafel('gluing', na_stole)
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    assert _licz(client, na_stole.id, naglowki, 'gluing').status_code == 200
    r = _licz(client, poza.id, _nowa_operacja(naglowki), 'gluing')
    assert r.status_code == 409 and r.get_json()['error'] == 'nie_na_stole'
    db.session.rollback()
    assert db.session.get(ProductionProduct, poza.id).quantity_done_gluing in (0, None)
    # licznik nie zdejmuje kafla
    assert _klucze() == ['gluing/p:%d' % na_stole.id]


def test_licznik_nie_bierze_blokady_zamowienia(app, client):
    """Licznik sztuk zostaje pisarzem pozycji BEZ blokady zamówienia: bramka czyta stół zwykłym odczytem."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        r = _licz(client, order.products[0].id, naglowki, 'gluing')

    assert r.status_code == 200
    assert not [sql for sql, _p in z.lista if blokada_zamowien(sql) or blokada_pozycji(sql)]
    assert not [sql for sql, _p in z.lista if _blokujacy(sql)]


def test_nie_na_stole_nie_zapisuje_wpisu_idempotencji(app, client):
    """409 `nie_na_stole` jest w BLEDY_DO_PONOWIENIA: akcja z kolejki offline przejdzie z tym samym
    X-Operation-Id, gdy kafel wejdzie na stół."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    assert _zakoncz(client, pozycja.id, naglowki, 'gluing').status_code == 409
    assert ProcessedMobileOperation.query.count() == 0

    _kafel('gluing', pozycja)
    assert _zakoncz(client, pozycja.id, naglowki, 'gluing').status_code == 200
    assert ProcessedMobileOperation.query.count() == 1


# ══ Task 2: dopełnianie stołu (spec 5.1, 5.2, 5.6) ══════════════════════════════════════════════════════════

def _dopelnij(stanowisko, teraz=T0):
    """Dopełnienie jak w routerze: commit (koniec migawki) → `stol.dopelnij` → commit."""
    db.session.commit()
    wynik = stol.dopelnij(stanowisko, teraz=teraz)
    pobrane = [w.unit_key for w in wynik.pobrane]
    db.session.commit()
    return wynik, pobrane


def _dorobka(order, status, sekwencja=1, utworzono=T0):
    """Pozycja-doróbka (ma `original_product_id`) zamówienia `order` w statusie `status`."""
    return produkt(order, status=status, sekwencja=sekwencja, original_product_id=order.products[0].id,
                   created_at=utworzono, priority_rank=0)


def _na_stole(stanowisko):
    """(unit_key, zrodlo) kafli leżących na stole, w kolejności `stol.kafle`."""
    db.session.rollback()
    return [(w.unit_key, w.zrodlo) for w in stol.kafle(stanowisko) if w.postponed_at is None]


def test_dopelnij_do_k_w_kolejnosci_kandydatow(app, monkeypatch):
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    p1, p2, p3, p4 = [p.id for p in order.products]
    monkeypatch.setattr(kolejka, 'kandydaci_stanowiska',
                        lambda *a, **k: kolejka.Kandydaci(kafle=[p3, p1, p2, p4], niekompletne=[]))

    wynik, pobrane = _dopelnij('gluing')

    assert pobrane == ['p:%d' % p3, 'p:%d' % p1]
    assert wynik.kolejka_dalej == 2 and wynik.niekompletne == []
    wiersze = StationDesk.query.order_by(StationDesk.id).all()
    assert [(w.station_code, w.order_id, w.product_id, w.pulled_at, w.postponed_at) for w in wiersze] == [
        ('gluing', order.id, p3, T0, None), ('gluing', order.id, p1, T0, None)]


def test_dopelnij_pomija_kafle_na_stole_i_odlozone(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    na_stole, odlozona, wolna, kolejna = order.products
    _kafel('gluing', na_stole)
    _kafel('gluing', odlozona, odlozony=True)

    wynik, pobrane = _dopelnij('gluing')

    # K=2: jeden kafel leży, odłożony się nie liczy i nie wraca — wchodzi jeden nowy
    assert pobrane == ['p:%d' % wolna.id]
    assert wynik.kolejka_dalej == 1
    assert _dopelnij('gluing')[1] == []          # stół pełny: drugie dopełnienie niczego nie dokłada
    assert kolejna.id


def test_dopelnij_dorobka_w_ramach_k(app):
    """K3-poprawka-1 (spec 5.1, decyzja Konrada 5.10): doróbka stoi na początku kolejki i wchodzi W RAMACH K —
    nie ponad K. Trzy doróbki przy K = 2: wchodzą dwie najstarsze, trzecia i zwykła pozycja czekają w kolejce."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    zwykla = order.products[0]
    srednia = _dorobka(order, 'czeka_na_sklejanie', utworzono=datetime(2026, 10, 5, 7, 0))
    najstarsza = _dorobka(order, 'czeka_na_sklejanie', sekwencja=2, utworzono=datetime(2026, 10, 5, 6, 0))
    najmlodsza = _dorobka(order, 'czeka_na_sklejanie', sekwencja=3, utworzono=datetime(2026, 10, 5, 7, 30))
    db.session.commit()

    wynik, pobrane = _dopelnij('gluing')

    assert pobrane == ['p:%d' % najstarsza.id, 'p:%d' % srednia.id]
    assert _na_stole('gluing') == [('p:%d' % najstarsza.id, 'dorobka'), ('p:%d' % srednia.id, 'dorobka')]
    assert wynik.kolejka_dalej == 2                 # trzecia doróbka i zwykła pozycja
    assert stol.stan('gluing').kolejka_dalej == 2
    assert _dopelnij('gluing')[1] == []             # stół pełny: kolejne dopełnienie niczego nie dokłada
    assert zwykla.id and najmlodsza.id


def test_dopelnij_dorobka_nie_wchodzi_na_pelny_stol(app):
    """Stół pełny kaflami z kolejki: doróbka czeka (nie wchodzi ponad K). Gdy zwolni się miejsce, wchodzi jako
    PIERWSZA — przed zwykłą pozycją — ze źródłem `dorobka`."""
    _miejsca('gluing', 1)
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    lezy, zwykla = order.products
    _kafel('gluing', lezy)                                   # stół pełny (K=1)
    dorobka = _dorobka(order, 'czeka_na_sklejanie')
    db.session.commit()

    wynik, pobrane = _dopelnij('gluing')
    assert pobrane == [] and wynik.kolejka_dalej == 2
    assert _na_stole('gluing') == [('p:%d' % lezy.id, 'kolejka')]

    # kafel zakończony: pozycja idzie dalej, wiersz schodzi ze stołu
    StationDesk.query.filter_by(unit_key='p:%d' % lezy.id).delete()
    lezy.current_status = 'czeka_na_formatowanie'
    db.session.commit()
    wynik, pobrane = _dopelnij('gluing')
    assert pobrane == ['p:%d' % dorobka.id] and wynik.kolejka_dalej == 1
    assert _na_stole('gluing') == [('p:%d' % dorobka.id, 'dorobka')]
    assert zwykla.id


def test_dopelnij_zapisuje_zrodlo_kolejka_i_dorobka(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    zwykla = order.products[0]
    dorobka = _dorobka(order, 'czeka_na_sklejanie')
    db.session.commit()

    _dopelnij('gluing')

    assert _na_stole('gluing') == [('p:%d' % dorobka.id, 'dorobka'), ('p:%d' % zwykla.id, 'kolejka')]


def test_dopelnij_liczy_do_k_kafle_kazdego_zrodla(app):
    """Spec 5.1: dopełnianie liczy WSZYSTKIE kafle leżące na stole — także doróbki, wysłane przez biuro
    i startowe — i dobiera z kolejki dopiero, gdy jest ich mniej niż K."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    a, b, c, d = order.products
    _kafel('gluing', a, zrodlo='dorobka')
    _kafel('gluing', b, zrodlo='biuro')

    wynik, pobrane = _dopelnij('gluing')
    assert pobrane == [] and wynik.kolejka_dalej == 2

    # doróbka zakończona: pozycja idzie dalej, jej kafel schodzi ze stołu
    StationDesk.query.filter_by(unit_key='p:%d' % a.id).delete()
    a.current_status = 'czeka_na_formatowanie'
    db.session.commit()
    assert _dopelnij('gluing')[1] == ['p:%d' % c.id]
    assert d.id


def test_dopelnij_startowe_trzymaja_miejsca_az_zejda_ponizej_k(app):
    """Start stołów (spec 5.8 p. 5): kafle startowe leżą ponad K, a kolejka dokłada dopiero, gdy zejdą poniżej K."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 5)
    pozycje = order.products
    for p in pozycje[:3]:
        _kafel('gluing', p, zrodlo='start')

    assert _dopelnij('gluing')[1] == []
    StationDesk.query.filter(StationDesk.unit_key.in_(['p:%d' % p.id for p in pozycje[:2]])).delete(
        synchronize_session=False)
    for p in pozycje[:2]:
        p.current_status = 'czeka_na_formatowanie'      # dwa kafle startowe zakończone
    db.session.commit()
    assert _dopelnij('gluing')[1] == ['p:%d' % pozycje[3].id]


def test_dopelnij_nie_liczy_wiersza_innej_jednostki(app):
    """Sklejanie ma jednostkę `pozycja`: zaległy wiersz `o:` (po zmianie jednostki) nie zajmuje miejsca i nikogo
    nie ukrywa."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    _kafel('gluing', order)

    _wynik, pobrane = _dopelnij('gluing')

    assert pobrane == ['p:%d' % order.products[0].id, 'p:%d' % order.products[1].id]


def test_dopelnij_pakowanie_bez_sposobu_dostawy_wchodzi_jak_kazde(app):
    """Po logistyce 4.6 (spec 5.1, decyzja Konrada 5.10) zamówienie bez sposobu dostawy jest zwykłym kandydatem
    Pakowania: wchodzi na stół w kolejności kolejki i liczy się w `kolejka_dalej` (dawniej było pomijane)."""
    bez_sposobu = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',))
    kurier = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    drugi = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',))
    _miejsca('packaging', 1)

    wynik, pobrane = _dopelnij('packaging')

    assert pobrane == ['o:%d' % bez_sposobu.id]
    assert wynik.kolejka_dalej == 2
    assert stol.stan('packaging').kolejka_dalej == 2
    assert kurier.id and drugi.id


def test_dopelnij_formatowanie_kompletne_na_stol_niekompletne_osobno(app):
    """Przykład X/Y ze specu 5.6: X ma 1 z 4 pozycji na Formatowaniu (reszta na Sklejaniu) — idzie do sekcji
    „Niekompletne” z listą brakujących; kompletne Y wchodzi na stół."""
    x = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie',
                            'czeka_na_sklejanie'))
    y = zamowienie(statusy=('czeka_na_formatowanie',) * 3)

    wynik, pobrane = _dopelnij('formatting')

    assert pobrane == ['o:%d' % y.id]
    assert wynik.kolejka_dalej == 0
    assert len(wynik.niekompletne) == 1
    wiersz = wynik.niekompletne[0]
    assert (wiersz.order.id, wiersz.na_stanowisku, wiersz.pozycji) == (x.id, 1, 4)
    assert [(p.id, kod) for p, kod in wiersz.brakuje] == [(p.id, 'gluing') for p in x.products[1:]]


def test_dopelnij_formatowanie_pozycja_omijajaca_nie_trzyma_w_niekompletnych(app):
    """Przykład z pytania 8 raportu K3: zamówienie wchodzi na stół Formatowania, choć jego pozycja bez docięcia
    stoi jeszcze na Sklejaniu. Na Pakowaniu ta sama pozycja nadal trzyma zamówienie w „Niekompletnych”."""
    order = _z_omijajaca()
    zwykle = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))

    wynik, pobrane = _dopelnij('formatting')

    assert pobrane == ['o:%d' % order.id]
    (wiersz,) = wynik.niekompletne
    assert (wiersz.order.id, wiersz.na_stanowisku, wiersz.pozycji) == (zwykle.id, 1, 2)
    stan = stol.stan('formatting')
    assert [w.unit_key for w in stan.wiersze] == ['o:%d' % order.id]
    assert [n.order.id for n in stan.niekompletne] == [zwykle.id]

    pakowane = _z_omijajaca(status_zwyklej='czeka_na_pakowanie')
    pakowane.override_delivery_method = s.KURIER
    db.session.commit()
    wynik, pobrane = _dopelnij('packaging')
    assert pobrane == []
    (wiersz,) = wynik.niekompletne
    assert (wiersz.order.id, wiersz.na_stanowisku, wiersz.pozycji) == (pakowane.id, 1, 2)
    assert [(p.id, kod) for p, kod in wiersz.brakuje] == [(pakowane.products[1].id, 'gluing')]


def test_dopelnij_niekompletne_bez_omijajacej_w_liczniku(app):
    """„1/2 na stanowisku”: pozycja omijająca Formatowanie nie wchodzi do mianownika ani do listy brakujących."""
    order = _z_omijajaca()
    brakujaca = produkt(order, status='czeka_na_wyciecie', sekwencja=3)
    db.session.commit()

    wynik, pobrane = _dopelnij('formatting')

    assert pobrane == []
    (wiersz,) = wynik.niekompletne
    assert (wiersz.order.id, wiersz.na_stanowisku, wiersz.pozycji) == (order.id, 1, 2)
    assert [(p.id, kod) for p, kod in wiersz.brakuje] == [(brakujaca.id, 'cutting')]


def test_dopelnij_nie_doczytuje_kolumn_sciezki(app):
    """Reguła ścieżki czyta `cut_to_size`, obróbkę krawędzi i wykończenie — kolumny muszą być w odczycie
    kandydatów, inaczej każda pozycja doczytywałaby je osobnym zapytaniem (i to pod limitem czekania `desk`)."""
    for _ in range(3):
        _z_omijajaca()
    db.session.commit()

    with Zapytania() as z:
        stol.dopelnij('formatting', teraz=T0)

    assert not [sql for sql, _p in z.lista
                if sql.startswith('SELECT') and 'FROM prod_products' in sql and 'WHERE prod_products.id = ' in sql]
    db.session.rollback()


def test_dopelnij_niekompletnych_najwyzej_k(app):
    _miejsca('formatting', 1)
    for _ in range(3):
        zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))

    wynik, pobrane = _dopelnij('formatting')

    assert pobrane == [] and len(wynik.niekompletne) == 1


def test_dopelnij_ostatnia_pozycja_czyni_zamowienie_kompletnym(app, client):
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    ostatnia = order.products[1]
    assert _dopelnij('formatting')[1] == []

    assert _zakoncz(client, ostatnia.id, _naglowki('gluing'), 'gluing').status_code == 200

    assert _dopelnij('formatting')[1] == ['o:%d' % order.id]


def test_dopelnij_pozycja_omijajaca_formatowanie_nie_jest_brakujaca(app):
    """Pozycja bez docięcia idzie ze Sklejania prosto do pakowania — dla Formatowania jest już „dalej”."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_pakowanie'))
    order.products[1].cut_to_size = False
    db.session.commit()

    wynik, pobrane = _dopelnij('formatting')

    assert pobrane == ['o:%d' % order.id] and wynik.niekompletne == []


def test_dopelnij_formatowanie_dorobka_kompletna_w_ramach_k(app):
    """Doróbka na stanowisku zamówieniowym: KOMPLETNE zamówienie z doróbką czekającą na Formatowaniu jest pierwsze
    w kolejce i wchodzi w ramach K jako `dorobka` (K3-poprawka-1: nie ponad K); niekompletne zostaje
    w „Niekompletnych” (kafla-zamówienia nie da się puścić po kawałku)."""
    _miejsca('formatting', 1)
    zwykle = zamowienie(statusy=('czeka_na_formatowanie',), priority_rung=1, priority_rank=1, priority_stars=5)
    z_dorobka = zamowienie(statusy=('czeka_na_pakowanie',), priority_rung=9, priority_rank=2)
    _dorobka(z_dorobka, 'czeka_na_formatowanie')
    niekompletne = zamowienie(statusy=('czeka_na_sklejanie',))
    _dorobka(niekompletne, 'czeka_na_formatowanie')
    db.session.commit()

    wynik, pobrane = _dopelnij('formatting')

    # jedno miejsce: bierze je zamówienie z doróbką, choć drugie ma pięć gwiazdek
    assert pobrane == ['o:%d' % z_dorobka.id] and wynik.kolejka_dalej == 1
    assert StationDesk.query.filter_by(unit_key='o:%d' % z_dorobka.id).one().zrodlo == 'dorobka'
    assert [w.order.id for w in wynik.niekompletne] == [niekompletne.id]
    # stół pełny: drugie zamówienie z doróbką czeka, nie wchodzi ponad K
    kolejne = zamowienie(statusy=('czeka_na_pakowanie',))
    _dorobka(kolejne, 'czeka_na_formatowanie')
    db.session.commit()
    wynik, pobrane = _dopelnij('formatting')
    assert pobrane == [] and wynik.kolejka_dalej == 2
    assert zwykle.id


def test_dopelnij_kolejnosc_jak_podglad_kolejki_k2(app):
    """Stół bierze dokładnie to, co pokazuje podgląd `GET /kolejka?stanowisko=` (to samo wejście algorytmu)."""
    drabina_domyslna()
    pozny = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'), priority_rung=9, priority_rank=3)
    pilny = zamowienie(statusy=('czeka_na_sklejanie',), priority_rung=1, priority_rank=1, priority_stars=5)
    rozpoczete = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), priority_rung=9,
                            priority_rank=2)
    _miejsca('gluing', 3)
    podglad = ['p:%d' % kafel['product_id'] for kafel in widok.kolejka_stanowiska('gluing')['kafle']]
    assert len(podglad) == 4

    wynik, pobrane = _dopelnij('gluing')

    assert pobrane == podglad[:3] and wynik.kolejka_dalej == 1
    # pilne (pięć gwiazdek) pierwsze, potem pozycja zamówienia rozpoczętego (tag „Rozpoczęte” na żywo), potem reszta
    assert pobrane[0] == 'p:%d' % pilny.products[0].id
    assert pobrane[1] == 'p:%d' % rozpoczete.products[1].id
    assert pozny.id


def test_dopelnij_przekazuje_szczebel_rozpoczete_i_jednostke(app, monkeypatch):
    """Twardy wymóg K1/K2: bez `szczebel_rozpoczete` tag „Rozpoczęte” nie podnosi pozycji na stole, a bez
    `jednostka=ustawienia.jednostka(S)` podgląd i stół rozjadą się po zmianie jednostki przez admina."""
    drabina_domyslna()
    zamowienie(statusy=('czeka_na_sklejanie',))
    ustaw(stale.klucz_jednostka('gluing'), 'zamowienie')
    wolania = []
    oryginal = kolejka.kandydaci_stanowiska

    def szpieg(stanowisko, pozycje, statusy_zamowien, **kwargs):
        wolania.append((stanowisko, kwargs, statusy_zamowien))
        return oryginal(stanowisko, pozycje, statusy_zamowien, **kwargs)

    monkeypatch.setattr(kolejka, 'kandydaci_stanowiska', szpieg)
    _dopelnij('gluing')

    assert len(wolania) == 1
    stanowisko, kwargs, statusy_zamowien = wolania[0]
    assert stanowisko == 'gluing'
    # `omijajace` (K3-poprawka-1): pozycje, których ścieżka omija stanowisko — Sklejania nie omija nic
    assert kwargs == {'szczebel_rozpoczete': drabina.pozycja_tagu('rozpoczete'), 'jednostka': 'zamowienie',
                      'omijajace': frozenset()}
    assert kwargs['szczebel_rozpoczete'] == 5
    # statusy jako pary (product_id, status) — kontrakt K1
    (pary,) = statusy_zamowien.values()
    assert pary[0][1] == 'czeka_na_sklejanie' and isinstance(pary[0][0], int)


def test_dopelnij_po_blokadzie_widzi_cudzy_kafel(app, monkeypatch):
    """Dwa `desk` naraz (Review Focus 2): drugi czeka na blokadzie stanowiska, a po niej czyta stół od nowa —
    kafel wstawiony przez pierwszego nie jest dublowany."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    pierwszy, drugi, trzeci = order.products
    assert StationDesk.query.all() == []                       # „migawka” sprzed blokady: stół pusty
    oryginal = stol.zablokuj_stanowisko

    def po_blokadzie(stanowisko):
        wynik = oryginal(stanowisko)
        db.session.execute(_STOL.insert().values(station_code='gluing', order_id=order.id, product_id=pierwszy.id,
                                                 unit_key='p:%d' % pierwszy.id, pulled_at=T0, zrodlo='kolejka'))
        return wynik

    monkeypatch.setattr(stol, 'zablokuj_stanowisko', po_blokadzie)
    _wynik, pobrane = _dopelnij('gluing')

    assert pobrane == ['p:%d' % drugi.id]
    assert _klucze() == sorted(['gluing/p:%d' % pierwszy.id, 'gluing/p:%d' % drugi.id])
    assert trzeci.id


def test_dopelnij_widzi_biezacy_status_pozycji(app, monkeypatch):
    """Kandydat, który po migawce poszedł dalej (ZAKOŃCZ drugiego tabletu), nie wchodzi na stół: statusy pozycji
    czytamy odczytem bieżącym, a nie z obiektów zostawionych w sesji."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    pierwszy, drugi, trzeci = order.products
    trzymane = list(order.products)                            # obiekty w sesji w STARYM stanie
    oryginal = stol.zablokuj_stanowisko

    def po_blokadzie(stanowisko):
        wynik = oryginal(stanowisko)
        db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pierwszy.id)
                           .values(current_status='czeka_na_formatowanie'))
        assert pierwszy.current_status == 'czeka_na_sklejanie'
        return wynik

    monkeypatch.setattr(stol, 'zablokuj_stanowisko', po_blokadzie)
    wynik = stol.dopelnij('gluing', teraz=T0)

    assert [w.unit_key for w in wynik.pobrane] == ['p:%d' % drugi.id, 'p:%d' % trzeci.id]
    assert trzymane


# ── kolejność blokad dopełniania (Review Focus 1) ───────────────────────────────────────────────────────────

def _ze_znacznikiem_commitu(z):
    def po_commicie(_polaczenie):
        z.lista.append(('COMMIT', None))
    return po_commicie


def _blokada_stanowiska(stanowisko):
    def warunek(wpis):
        sql, parametry = wpis
        return (sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')
                and stale.klucz_blokady(stanowisko) in tuple(parametry or ()))
    return warunek


def _indeks(z, warunek):
    return next(i for i, wpis in enumerate(z.lista) if warunek(wpis))


def test_dopelnij_commit_blokada_stanowiska_zamowienia_pozycje_potem_insert(app, client):
    """`GET desk`: COMMIT → blokada stanowiska (pierwsze polecenie nowej transakcji, zero odczytów pomiędzy) →
    zamówienia FOR SHARE rosnąco → pozycje FOR SHARE po (order_id, id) → zwykły odczyt stołu → INSERT → COMMIT."""
    starsze = zamowienie(statusy=('czeka_na_sklejanie',))
    nowsze = zamowienie(statusy=('czeka_na_sklejanie',))
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        sluchacz = _ze_znacznikiem_commitu(z)
        event.listen(db.engine, 'commit', sluchacz)
        try:
            r = client.get('/api/mobile/stations/gluing/desk', headers=naglowki)
        finally:
            event.remove(db.engine, 'commit', sluchacz)

    assert r.status_code == 200, r.get_json()
    blokada = _indeks(z, _blokada_stanowiska('gluing'))
    assert z.lista[blokada - 1] == ('COMMIT', None)            # nic między commitem a blokadą
    zamowienia = _indeks(z, lambda w: odczyt_biezacy_zamowien(w[0]))
    pozycje = _indeks(z, lambda w: odczyt_biezacy_pozycji_wielu_zamowien(w[0]))
    stol_odczyt = next(i for i, (sql, _p) in enumerate(z.lista) if i > pozycje and _odczyt_stolu(sql))
    wstawka = _indeks(z, lambda w: w[0].startswith('INSERT INTO prod_station_desk'))
    commit_po = next(i for i, wpis in enumerate(z.lista) if i > wstawka and wpis == ('COMMIT', None))
    assert blokada < zamowienia < pozycje < stol_odczyt < wstawka < commit_po
    assert list(z.lista[zamowienia][1]) == [starsze.id, nowsze.id]
    assert list(z.lista[pozycje][1]) == [starsze.id, nowsze.id]
    assert not _blokujacy(z.lista[stol_odczyt][0])
    # między blokadą stanowiska a commitem zapisu żadnej blokady X zamówień ani pozycji
    assert not [sql for sql, _p in z.lista[blokada + 1:commit_po]
                if sql.startswith('SELECT') and sql.endswith(' FOR UPDATE')]


def test_dopelnij_nie_blokuje_wierszy_stolu(app):
    zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    db.session.commit()
    with Zapytania() as z:
        stol.dopelnij('gluing', teraz=T0)
        db.session.commit()
    odczyty = [sql for sql, _p in z.lista if _odczyt_stolu(sql)]
    assert odczyty and not [sql for sql in odczyty if _blokujacy(sql)]


def test_dopelnij_bez_blokady_tras_i_paczek(app):
    from modules.production.logistics.services import paczki, routes
    zamowienie(statusy=('czeka_na_sklejanie',))
    db.session.commit()
    with Zapytania() as z:
        stol.dopelnij('gluing', teraz=T0)
    parametry = [p for _sql, wiersz in z.lista for p in (wiersz or ())]
    assert routes.KLUCZ_BLOKADY not in parametry
    assert paczki.KLUCZ_BLOKADY not in parametry


def test_zakoncz_nie_dotyka_blokady_stanowiska(app, client):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        assert _zakoncz(client, order.products[0].id, naglowki, 'gluing').status_code == 200

    assert not [1 for _sql, parametry in z.lista
                if any(str(p).startswith('priorytety_blokada_') for p in (parametry or ()))]


def test_dopelnij_ustawienia_po_blokadzie(app):
    """Ustawienia stanowiska (K, jednostka) czytamy PO blokadzie: między commitem a blokadą nie wolno nic czytać."""
    zamowienie(statusy=('czeka_na_sklejanie',))
    db.session.commit()
    with Zapytania() as z:
        stol.dopelnij('gluing', teraz=T0)
    blokada = _indeks(z, _blokada_stanowiska('gluing'))
    assert blokada == 0
    ustawienia_odczyty = [i for i, (_sql, parametry) in enumerate(z.lista)
                          if any(str(p).startswith(('priorytety_stol_', 'priorytety_jednostka_'))
                                 for p in (parametry or ()))]
    assert ustawienia_odczyty and min(ustawienia_odczyty) > blokada


def test_kafle_kolejnosc_zrodel_na_stole(app):
    """Spec 5.1: na stole doróbki, wysłane przez biuro, startowe, pobrane — w grupie po czasie wejścia;
    odłożone osobno, najdłużej leżące pierwsze."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 7)
    p = order.products
    _kafel('gluing', p[0], zrodlo='kolejka', pobrano=datetime(2026, 10, 5, 8, 0))
    _kafel('gluing', p[1], zrodlo='start', pobrano=datetime(2026, 10, 5, 7, 0))
    _kafel('gluing', p[2], zrodlo='biuro', pobrano=datetime(2026, 10, 5, 9, 0))
    _kafel('gluing', p[3], zrodlo='dorobka', pobrano=datetime(2026, 10, 5, 10, 0))
    _kafel('gluing', p[4], zrodlo='kolejka', pobrano=datetime(2026, 10, 5, 6, 0))
    _kafel('gluing', p[5], odlozony=True, postponed_at=datetime(2026, 10, 5, 9, 30))
    _kafel('gluing', p[6], odlozony=True, postponed_at=datetime(2026, 10, 5, 9, 10))

    wiersze = stol.kafle('gluing')

    assert [w.unit_key for w in wiersze] == ['p:%d' % p[i].id for i in (3, 2, 1, 4, 0, 6, 5)]
    assert [w.postponed_at is None for w in wiersze] == [True] * 5 + [False] * 2


# ══ Task 3: Odłóż (spec 5.3, 9.2) ═══════════════════════════════════════════════════════════════════════════

def _odloz(pozycja, stanowisko, powod='brak_materialu', notatka=None, zakres='pozycja', **kwargs):
    """Odłożenie jak w handlerze: blokada zamówienia i pozycji, potem `stol.odloz`. Bez commita."""
    from modules.production.services import blokady_zamowien
    item = blokady_zamowien.zablokuj_zamowienie_pozycji(pozycja.id)
    return stol.odloz(item.order_id, item.id if zakres == 'pozycja' else None, stanowisko, powod, notatka,
                      kwargs.pop('worker_id', None), kwargs.pop('device_id', None), teraz=T0, **kwargs)


def _limit_odlozen(stanowisko, ile):
    ustaw(stale.klucz_limit(stanowisko), ile, 'integer')


def test_odloz_ustawia_postponed_i_loguje(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja)

    wiersz = _odloz(pozycja, 'gluing', powod='awaria_maszyny', notatka=u'pękł pas', worker_id=7, device_id=3)
    db.session.commit()

    assert (wiersz.postponed_at, wiersz.postpone_reason, wiersz.postpone_note) == (T0, 'awaria_maszyny', u'pękł pas')
    assert (wiersz.postponed_by_worker_id, wiersz.postponed_device_id) == (7, 3)
    (log,) = PriorityLog.query.all()
    assert (log.action, log.order_id, log.product_id, log.station_code) == ('odlozenie', order.id, pozycja.id, 'gluing')
    assert (log.reason, log.note, log.worker_id, log.device_id, log.created_at) == (
        'awaria_maszyny', u'pękł pas', 7, 3, T0)
    # kafel zostaje wierszem stołu (sekcja „Odłożone”), nie znika
    assert _klucze() == ['gluing/p:%d' % pozycja.id]


def test_odloz_limit_409(app):
    """Limit otwartych odłożeń na stanowisko (spec 5.3): przy limicie Odłóż odmawia z komunikatem dla człowieka."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    a, b, c, d = order.products
    _limit_odlozen('gluing', 2)
    _kafel('gluing', a, odlozony=True)
    _kafel('gluing', b)
    _kafel('gluing', c)

    _odloz(b, 'gluing')                      # jeden odłożony → drugi przechodzi
    db.session.commit()

    with pytest.raises(stol.BladStolu) as blad:
        _odloz(c, 'gluing')
    db.session.rollback()
    assert (blad.value.kod, blad.value.status) == ('limit_odlozen', 409)
    assert blad.value.komunikat == u'Na Sklejaniu leżą 2 odłożone pozycje. Zamknij którąś, zanim odłożysz kolejną.'
    assert StationDesk.query.filter(StationDesk.postponed_at.isnot(None)).count() == 2
    assert d.id


@pytest.mark.parametrize('stanowisko, ile, komunikat', [
    ('gluing', 1, u'Na Sklejaniu leży 1 odłożona pozycja. Zamknij którąś, zanim odłożysz kolejną.'),
    ('gluing', 10, u'Na Sklejaniu leży 10 odłożonych pozycji. Zamknij którąś, zanim odłożysz kolejną.'),
    ('formatting', 1, u'Na Formatowaniu leży 1 odłożone zamówienie. Zamknij któreś, zanim odłożysz kolejne.'),
    ('formatting', 3, u'Na Formatowaniu leżą 3 odłożone zamówienia. Zamknij któreś, zanim odłożysz kolejne.'),
    ('packaging', 12, u'Na Pakowaniu leży 12 odłożonych zamówień. Zamknij któreś, zanim odłożysz kolejne.'),
])
def test_komunikat_limitu_odlozen_po_polsku(stanowisko, ile, komunikat):
    jednostka = 'zamowienie' if stanowisko in ('formatting', 'packaging') else 'pozycja'
    assert stol.komunikat_limitu(stanowisko, ile, jednostka) == komunikat


def test_odloz_nie_blokuje_cudzych_wierszy_stolu(app):
    """Odłóż blokuje TYLKO wiersz własnego kafla; limit liczy zwykłym odczytem (plan, Doprecyzowania p. 13) —
    blokada wierszy całego stanowiska dawała cykl z ZAKOŃCZ innego zamówienia."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    inne = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    _kafel('gluing', inne.products[0], odlozony=True)
    db.session.commit()

    with Zapytania() as z:
        _odloz(order.products[0], 'gluing')
        db.session.flush()

    blokujace = [sql for sql, _p in z.lista if 'FROM prod_station_desk' in sql and _blokujacy(sql)]
    assert len(blokujace) == 1 and _stol_po_kluczu(blokujace[0])
    licznik = [sql for sql, _p in z.lista if sql.startswith('SELECT count(') and 'FROM prod_station_desk' in sql]
    assert len(licznik) == 1 and not _blokujacy(licznik[0])
    assert 'prod_station_desk.postponed_at IS NOT NULL' in licznik[0]


def test_odloz_nie_na_stole_409(app):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'), numer_wewnetrzny='1777')
    bez_kafla, odlozona = order.products
    _kafel('gluing', odlozona, odlozony=True)

    for pozycja in (bez_kafla, odlozona):          # brak wiersza; wiersz już odłożony
        with pytest.raises(stol.BladStolu) as blad:
            _odloz(pozycja, 'gluing')
        db.session.rollback()
        assert (blad.value.kod, blad.value.status) == ('nie_na_stole', 409)
        assert blad.value.komunikat == u'Zamówienie 1777 nie leży na stole Sklejania.'
    assert PriorityLog.query.count() == 0


def test_odloz_powod_inne_bez_notatki_400(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])

    for notatka in (None, '', '   '):
        with pytest.raises(stol.BladStolu) as blad:
            _odloz(order.products[0], 'gluing', powod='inne', notatka=notatka)
        db.session.rollback()
        assert (blad.value.kod, blad.value.status) == ('powod_niepoprawny', 400)

    wiersz = _odloz(order.products[0], 'gluing', powod='inne', notatka=u'  czekam na szablon ')
    assert (wiersz.postpone_reason, wiersz.postpone_note) == ('inne', u'czekam na szablon')


def test_odloz_powod_nieznany_400(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])

    for powod in ('nie_chce_mi_sie', '', None):
        with pytest.raises(stol.BladStolu) as blad:
            _odloz(order.products[0], 'gluing', powod=powod)
        db.session.rollback()
        assert (blad.value.kod, blad.value.status) == ('powod_niepoprawny', 400)
    assert StationDesk.query.filter(StationDesk.postponed_at.isnot(None)).count() == 0


def test_odloz_kafel_zamowienia_na_formatowaniu(app):
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie'))
    _kafel('formatting', order)

    wiersz = _odloz(order.products[1], 'formatting', zakres='zamowienie')
    db.session.commit()

    assert (wiersz.unit_key, wiersz.product_id, wiersz.postponed_at) == ('o:%d' % order.id, None, T0)
    (log,) = PriorityLog.query.all()
    assert (log.action, log.order_id, log.product_id) == ('odlozenie', order.id, None)


def test_odlozony_nie_jest_pobierany_ponownie(app):
    """Odłożony kafel zostaje na tablecie i NIE wraca do kolejki (spec 5.3): na stół wchodzi następny."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    a, b, c = order.products
    _miejsca('gluing', 1)
    assert _dopelnij('gluing')[1] == ['p:%d' % a.id]

    _odloz(a, 'gluing')
    db.session.commit()

    assert _dopelnij('gluing')[1] == ['p:%d' % b.id]
    wiersze = stol.kafle('gluing')
    assert [(w.unit_key, w.postponed_at is not None) for w in wiersze] == [
        ('p:%d' % b.id, False), ('p:%d' % a.id, True)]
    assert c.id


def test_odloz_zablokuj_zamowienie_potem_stol(app, client):
    """Kolejność Odłóż (spec 9.4): zamówienie → pozycje → własny wiersz stołu (odczyt bieżący) → UPDATE wiersza →
    INSERT logu; bez blokady stanowiska."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    naglowki = _naglowki('gluing')

    with Zapytania() as z:
        r = client.post('/api/mobile/orders/%d/postpone' % order.products[0].id, headers=naglowki,
                        json={'station_code': 'gluing', 'zakres': 'pozycja', 'powod': 'brak_miejsca'})

    assert r.status_code == 200, r.get_json()
    # Oba zapisy idą jednym flushem (SQLAlchemy sam ustala ich kolejność) — ważne, że PO blokadach: wiersz stołu
    # jest już zablokowany odczytem bieżącym, a INSERT logu sprawdza FK zamówienia trzymanego X.
    zapisy = min(z.pierwsze(lambda sql: sql.startswith('UPDATE prod_station_desk')),
                 z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_priority_log')))
    kolejnosc = [z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(_stol_po_kluczu), zapisy]
    assert kolejnosc == sorted(kolejnosc), kolejnosc
    assert not [1 for _sql, parametry in z.lista
                if any(str(p).startswith('priorytety_blokada_') for p in (parametry or ()))]


# ══ Task 5b: „Wyślij na stanowisko” i „Zdejmij ze stołu” (spec 5.7) ═════════════════════════════════════════

def _wyslij(stanowisko, order, user_id=7):
    """Jak router panelu: commit → `stol.wyslij` → commit. Zwraca wynik serwisu."""
    db.session.commit()
    wynik = stol.wyslij(stanowisko, order.id, user_id, teraz=T0)
    db.session.commit()
    return wynik


def test_wyslij_pozycje_w_statusie_stanowiska_ponad_k(app):
    """Biuro kładzie na stół te pozycje zamówienia, które są TERAZ w statusie stanowiska (bez przeskakiwania
    procesu) — ponad K, ze źródłem `biuro`, na początek stołu."""
    inne = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    _kafel('gluing', inne.products[0])
    _kafel('gluing', inne.products[1])                             # stół pełny (K=2)
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_sklejanie'))
    a, dalej, c = order.products

    wynik = _wyslij('gluing', order)

    assert wynik == {'wyslane': ['p:%d' % a.id, 'p:%d' % c.id], 'przywrocone': [], 'juz_na_stole': []}
    assert _na_stole('gluing')[:2] == [('p:%d' % a.id, 'biuro'), ('p:%d' % c.id, 'biuro')]
    assert len(_na_stole('gluing')) == 4
    wiersz = StationDesk.query.filter_by(unit_key='p:%d' % a.id).one()
    assert (wiersz.sent_by_user_id, wiersz.pulled_at, wiersz.order_id, wiersz.product_id) == (7, T0, order.id, a.id)
    logi = PriorityLog.query.order_by(PriorityLog.id).all()
    assert [(w.action, w.order_id, w.product_id, w.station_code, w.user_id, w.new_value) for w in logi] == [
        ('wyslanie', order.id, a.id, 'gluing', 7, 'p:%d' % a.id),
        ('wyslanie', order.id, c.id, 'gluing', 7, 'p:%d' % c.id)]
    assert dalej.id


def test_wyslij_kafel_zamowienia_takze_niekompletny(app):
    """Stanowisko zamówieniowe: biuro świadomie wypycha także zamówienie NIEKOMPLETNE (spec 5.7)."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))

    wynik = _wyslij('formatting', order)

    assert wynik['wyslane'] == ['o:%d' % order.id]
    assert _na_stole('formatting') == [('o:%d' % order.id, 'biuro')]
    (log,) = PriorityLog.query.all()
    assert (log.action, log.order_id, log.product_id) == ('wyslanie', order.id, None)


def test_wyslany_niekompletny_kafel_przezywa_zakoncz_pozycji(app, client):
    """Kafel `biuro` niekompletnego zamówienia nie znika przy ZAKOŃCZ pozycji z wcześniejszego stanowiska (dalej jest
    niekompletne) — schodzi dopiero, gdy z Formatowania zejdzie ostatnia pozycja."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie'))
    na_formatowaniu, na_sklejaniu, _trzecia = order.products
    _wyslij('formatting', order)

    assert _zakoncz(client, na_sklejaniu.id, _naglowki('gluing'), 'gluing').status_code == 200
    assert _klucze('formatting') == ['formatting/o:%d' % order.id]

    naglowki = _naglowki('formatting')
    assert _zakoncz(client, na_formatowaniu.id, naglowki, 'formatting').status_code == 200
    assert _zakoncz(client, na_sklejaniu.id, _nowa_operacja(naglowki), 'formatting').status_code == 200
    assert _klucze('formatting') == []


def test_wyslij_juz_na_stole_bez_zmian(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0], zrodlo='kolejka', pobrano=datetime(2026, 10, 4, 12, 0))

    wynik = _wyslij('gluing', order)

    assert wynik == {'wyslane': [], 'przywrocone': [], 'juz_na_stole': ['p:%d' % order.products[0].id]}
    wiersz = StationDesk.query.one()
    assert (wiersz.zrodlo, wiersz.pulled_at, wiersz.sent_by_user_id) == ('kolejka', datetime(2026, 10, 4, 12, 0), None)
    assert PriorityLog.query.count() == 0


def test_wyslij_odlozony_wraca_na_stol(app):
    """Jedyne „przywróć” odłożenia — robi je biuro, nie tablet (spec 5.3, 5.7)."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja, odlozony=True, postponed_by_worker_id=4, postponed_device_id=2)

    wynik = _wyslij('gluing', order)

    assert wynik == {'wyslane': [], 'przywrocone': ['p:%d' % pozycja.id], 'juz_na_stole': []}
    wiersz = StationDesk.query.one()
    assert (wiersz.postponed_at, wiersz.postpone_reason, wiersz.postpone_note, wiersz.postponed_by_worker_id,
            wiersz.postponed_device_id) == (None, None, None, None, None)
    assert (wiersz.zrodlo, wiersz.sent_by_user_id, wiersz.pulled_at) == ('biuro', 7, T0)
    (log,) = PriorityLog.query.all()
    assert (log.action, log.old_value, log.reason, log.user_id) == ('wyslanie', 'odlozone', 'brak_materialu', 7)


def test_wyslij_brak_na_stanowisku_409(app):
    order = zamowienie(statusy=('czeka_na_formatowanie', 'spakowane'), numer_wewnetrzny='1888')
    db.session.commit()

    with pytest.raises(stol.BladStolu) as blad:
        stol.wyslij('gluing', order.id, 7)
    db.session.rollback()

    assert (blad.value.kod, blad.value.status) == ('brak_na_stanowisku', 409)
    assert blad.value.komunikat == u'Zamówienie 1888 nie ma teraz żadnej pozycji na Sklejaniu.'
    assert StationDesk.query.count() == 0


def test_wyslij_zamowienie_nieznane_404(app):
    db.session.commit()
    with pytest.raises(stol.BladStolu) as blad:
        stol.wyslij('gluing', 987654, 7)
    db.session.rollback()
    assert (blad.value.kod, blad.value.status) == ('zamowienie_nieznane', 404)


def test_wyslij_pakowanie_bez_sposobu_dostawy_kladzie_kafel(app):
    """„Wyślij” na Pakowanie nie pyta o sposób dostawy (spec 5.1 po logistyce 4.6; dawniej 409)."""
    order = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',), numer_wewnetrzny='1889')
    db.session.commit()

    wynik = stol.wyslij('packaging', order.id, 7)
    db.session.commit()

    assert wynik['wyslane'] == ['o:%d' % order.id]
    assert [(w.unit_key, w.zrodlo) for w in StationDesk.query.all()] == [('o:%d' % order.id, 'biuro')]


def test_wyslij_lakiernia_409(app):
    order_id = zamowienie(statusy=('czeka_na_lakiernie',)).id
    db.session.commit()

    with Zapytania() as z:
        with pytest.raises(stol.BladStolu) as blad:
            stol.wyslij('painting', order_id, 7)

    assert (blad.value.kod, blad.value.status) == ('stanowisko_bez_stolu', 409)
    assert z.lista == []                    # odmowa przed blokadą i przed jakimkolwiek zapytaniem


def test_wyslij_kolejnosc_blokad_jak_dopelnij(app):
    """Spec 9.4: blokada stanowiska → zamówienie FOR SHARE → jego pozycje FOR SHARE → własne wiersze stołu
    (odczyt bieżący po kluczu) → zapis. Bez blokad X zamówień, bez blokady tras."""
    from modules.production.logistics.services import routes
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    _kafel('gluing', order.products[1], odlozony=True)
    order_id = order.id
    klucze = sorted('p:%d' % pozycja.id for pozycja in order.products)
    db.session.commit()

    with Zapytania() as z:
        stol.wyslij('gluing', order_id, 7, teraz=T0)
        db.session.flush()

    blokada = _indeks(z, _blokada_stanowiska('gluing'))
    zamowienia = _indeks(z, lambda w: odczyt_biezacy_zamowien(w[0]))
    pozycje = _indeks(z, lambda w: odczyt_biezacy_pozycji_wielu_zamowien(w[0]))
    stol_odczyt = _indeks(z, lambda w: _odczyt_stolu(w[0]))
    zapis_stolu = _indeks(z, lambda w: w[0].startswith(('INSERT INTO prod_station_desk', 'UPDATE prod_station_desk')))
    assert blokada == 0
    assert blokada < zamowienia < pozycje < stol_odczyt < zapis_stolu
    assert list(z.lista[zamowienia][1]) == [order_id] and list(z.lista[pozycje][1]) == [order_id]
    # Wiersze stołu: tylko własne klucze, odczytem bieżącym — KAŻDY KLUCZ OSOBNO, równością po obu kolumnach klucza
    # unikalnego (na MySQL dostęp `const`: blokada jednego rekordu albo samej luki), w ustalonej kolejności kluczy.
    # `unit_key IN (…) ORDER BY id` MySQL wykonuje skanem indeksu stanowiska albo całej tabeli (EXPLAIN w raporcie
    # K3) i blokuje CUDZE kafle — cykl z ZAKOŃCZ innego zamówienia (przegląd końcowy K3, W1).
    odczyty_stolu = [(sql, parametry) for sql, parametry in z.lista if _odczyt_stolu(sql)]
    assert len(odczyty_stolu) == 3
    for sql, _parametry in odczyty_stolu:
        assert _stol_po_kluczu(sql), sql
        assert ' IN (' not in sql and 'ORDER BY' not in sql, sql
    assert [tuple(parametry)[:2] for _sql, parametry in odczyty_stolu] == [('gluing', klucz) for klucz in klucze]
    # żadnej blokady X zamówień ani pozycji, żadnej blokady tras
    assert not [sql for sql, _p in z.lista if blokada_zamowien(sql) or blokada_pozycji(sql)]
    assert routes.KLUCZ_BLOKADY not in [p for _sql, wiersz in z.lista for p in (wiersz or ())]


def test_wyslij_widzi_biezacy_status_pozycji(app, monkeypatch):
    """Pozycja, którą tablet zakończył po migawce żądania biura, nie trafia na stół: statusy z odczytu bieżącego."""
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    zakonczona, czeka = order.products
    trzymane = list(order.products)
    oryginal = stol.zablokuj_stanowisko

    def po_blokadzie(stanowisko):
        wynik = oryginal(stanowisko)
        db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == zakonczona.id)
                           .values(current_status='czeka_na_formatowanie'))
        return wynik

    monkeypatch.setattr(stol, 'zablokuj_stanowisko', po_blokadzie)
    wynik = stol.wyslij('gluing', order.id, 7, teraz=T0)

    assert wynik['wyslane'] == ['p:%d' % czeka.id]
    assert trzymane


def test_zdejmij_przez_biuro_usuwa_i_loguje(app):
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    na_stole, odlozona = order.products
    _kafel('gluing', na_stole, zrodlo='start')
    _kafel('gluing', odlozona, odlozony=True)
    db.session.commit()

    pierwszy = stol.zdejmij_przez_biuro('gluing', 'p:%d' % na_stole.id, 7, teraz=T0)
    db.session.commit()
    drugi = stol.zdejmij_przez_biuro('gluing', 'p:%d' % odlozona.id, 7, teraz=T0)
    db.session.commit()

    assert pierwszy == {'unit_key': 'p:%d' % na_stole.id, 'order_id': order.id, 'product_id': na_stole.id,
                        'odlozony': False}
    assert drugi['odlozony'] is True
    assert _klucze() == []
    logi = PriorityLog.query.order_by(PriorityLog.id).all()
    assert [(w.action, w.order_id, w.product_id, w.station_code, w.user_id, w.new_value, w.old_value)
            for w in logi] == [
        ('zdjecie', order.id, na_stole.id, 'gluing', 7, 'p:%d' % na_stole.id, 'start'),
        ('zdjecie', order.id, odlozona.id, 'gluing', 7, 'p:%d' % odlozona.id, 'odlozone')]


def test_zdejmij_przez_biuro_brak_kafla_404(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('formatting', order.products[0])         # inne stanowisko
    db.session.commit()

    for klucz in ('p:%d' % order.products[0].id, 'o:%d' % order.id, 'p:987654'):
        with pytest.raises(stol.BladStolu) as blad:
            stol.zdejmij_przez_biuro('gluing', klucz, 7)
        db.session.rollback()
        assert (blad.value.kod, blad.value.status) == ('brak_kafla', 404), klucz

    for klucz in ('x:1', 'p:', '12', None, 'p:1; DROP'):
        with pytest.raises(stol.BladStolu) as blad:
            stol.zdejmij_przez_biuro('gluing', klucz, 7)
        db.session.rollback()
        assert (blad.value.kod, blad.value.status) == ('dane_niepoprawne', 400), klucz
    assert _klucze() == ['formatting/p:%d' % order.products[0].id]


def test_zdejmij_przez_biuro_kolejnosc_blokad(app):
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    _kafel('gluing', order.products[0])
    klucz = 'p:%d' % order.products[0].id
    db.session.commit()

    with Zapytania() as z:
        stol.zdejmij_przez_biuro('gluing', klucz, 7, teraz=T0)
        db.session.flush()

    blokada = _indeks(z, _blokada_stanowiska('gluing'))
    zamowienia = _indeks(z, lambda w: odczyt_biezacy_zamowien(w[0]))
    pozycje = _indeks(z, lambda w: odczyt_biezacy_pozycji_wielu_zamowien(w[0]))
    # własny wiersz: odczyt bieżący po kluczu kafla — po blokadach zamówienia i pozycji
    wlasny_wiersz = _indeks(z, lambda w: _stol_po_kluczu(w[0]))
    blokujace_stolu = [sql for sql, _p in z.lista if _odczyt_stolu(sql) and _blokujacy(sql)]
    assert len(blokujace_stolu) == 1 and ' IN (' not in blokujace_stolu[0] and 'ORDER BY' not in blokujace_stolu[0]
    usuniecie = _indeks(z, lambda w: w[0].startswith('DELETE FROM prod_station_desk'))
    assert blokada == 0 and blokada < zamowienia < pozycje < wlasny_wiersz < usuniecie
    assert not [sql for sql, _p in z.lista if blokada_zamowien(sql) or blokada_pozycji(sql)]


def test_zdjety_kafel_wraca_do_kolejki(app):
    """„Zdejmij” nie zabiera pozycji ze stanowiska: kafel wraca do kolejki i dopełnianie może go wziąć znowu."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    assert _dopelnij('gluing')[1] == ['p:%d' % pozycja.id]

    stol.zdejmij_przez_biuro('gluing', 'p:%d' % pozycja.id, 7)
    db.session.commit()
    assert _klucze() == []
    assert stol.stan('gluing').kolejka_dalej == 1

    assert _dopelnij('gluing')[1] == ['p:%d' % pozycja.id]


# ══ Task 5c: start stołów — kafle rozpoczęte (spec 5.8, ustalenie 17) ═══════════════════════════════════════

def _zdarzenie(pozycja, stanowisko, zrodlo='mobile', delta=1):
    """Zdarzenie stanowiskowe pozycji i licznik sztuk — jak po `set_quantity_done` z danego źródła."""
    from modules.production.models import ProductionStationEvent
    setattr(pozycja, 'quantity_done_%s' % stanowisko, pozycja.quantity)
    db.session.add(ProductionStationEvent(production_item_id=pozycja.id, station_code=stanowisko, delta=delta,
                                          quantity_done_after=pozycja.quantity, source=zrodlo))
    db.session.commit()


def _rozpoczete(stanowisko):
    db.session.rollback()
    return [(k['unit_key'], k['powod']) for k in stol.rozpoczete_na_stanowisku(stanowisko)]


def test_rozpoczete_pozycja_z_licznikiem(app):
    """Pozycja w statusie stanowiska z licznikiem sztuk > 0: ktoś już przy niej pracuje."""
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    zaczeta, nietknieta = order.products
    zaczeta.quantity_done_gluing = 1
    db.session.commit()

    kafle = stol.rozpoczete_na_stanowisku('gluing')

    assert kafle == [{'unit_key': 'p:%d' % zaczeta.id, 'order_id': order.id,
                      'numer': order.internal_order_number, 'product_id': zaczeta.id,
                      'short_id': zaczeta.short_product_id, 'powod': 'licznik', 'na_stole': False}]
    assert nietknieta.id


def test_rozpoczete_tylko_z_licznika_pozycja(app):
    """K3-poprawka-1 (spec 5.8, decyzja Konrada 5.10): kaflem startowym jest WYŁĄCZNIE pozycja w statusie stanowiska
    z licznikiem sztuk > 0. Reguła „inna pozycja zamówienia już tu zrobiona” odpadła — pozostałe pozycje zamówienia
    zaczętego na stanowisku nie wchodzą (biuro dokłada je „Wyślij”)."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie'))
    zrobiona, w_rekach, nietknieta = order.products
    _zdarzenie(zrobiona, 'gluing', 'mobile')            # zrobiona ręcznie na Sklejaniu i już dalej
    w_rekach.quantity_done_gluing = 1
    db.session.commit()

    assert _rozpoczete('gluing') == [('p:%d' % w_rekach.id, 'licznik')]
    assert nietknieta.id


def test_rozpoczete_tylko_z_licznika_zamowienie(app):
    """Stanowisko zamówieniowe: zamówienie, którego inna pozycja przeszła już Formatowanie (z tabletu albo
    automatem), a czekające tu pozycje mają licznik 0, NIE jest kaflem startowym."""
    order = zamowienie(statusy=('czeka_na_pakowanie', 'czeka_na_formatowanie'))
    pominieta, czeka = order.products
    _zdarzenie(pominieta, 'formatting', 'auto_skip')
    reczne = zamowienie(statusy=('czeka_na_krawedzie', 'czeka_na_formatowanie'))
    _zdarzenie(reczne.products[0], 'formatting', 'mobile')
    systemowe = zamowienie(statusy=('czeka_na_lakiernie', 'czeka_na_krawedzie'))
    _zdarzenie(systemowe.products[0], 'edges', 'system')

    assert _rozpoczete('formatting') == []
    assert _rozpoczete('edges') == []

    # dopiero licznik na pozycji CZEKAJĄCEJ na stanowisku robi z zamówienia kafel startowy
    czeka.quantity_done_formatting = 1
    db.session.commit()
    assert _rozpoczete('formatting') == [('o:%d' % order.id, 'licznik')]


def test_rozpoczete_pomija_pozycje_anulowane_i_wstrzymane(app):
    """Licznik pozycji anulowanej albo wstrzymanej nie robi kafla: pozycja nie czeka na stanowisku."""
    order = zamowienie(statusy=('anulowane', 'wstrzymane', 'czeka_na_sklejanie'))
    _zdarzenie(order.products[0], 'gluing', 'mobile')
    _zdarzenie(order.products[1], 'gluing', 'mobile')

    assert _rozpoczete('gluing') == []


def test_rozpoczete_zamowienie_na_formatowaniu(app):
    """Stanowisko zamówieniowe: kaflem startowym jest ZAMÓWIENIE — także niekompletne — gdy ma tu pozycję
    z licznikiem > 0."""
    z_licznikiem = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_formatowanie', 'czeka_na_sklejanie'))
    z_licznikiem.products[1].quantity_done_formatting = 1
    zaczete = zamowienie(statusy=('czeka_na_krawedzie', 'czeka_na_formatowanie', 'czeka_na_sklejanie'))
    _zdarzenie(zaczete.products[0], 'formatting', 'web')
    nietkniete = zamowienie(statusy=('czeka_na_formatowanie',))
    db.session.commit()

    kafle = stol.rozpoczete_na_stanowisku('formatting')

    assert [(k['unit_key'], k['powod'], k['product_id'], k['short_id']) for k in kafle] == [
        ('o:%d' % z_licznikiem.id, 'licznik', None, None)]
    assert nietkniete.id


def test_rozpoczete_pakowanie_bez_sposobu_dostawy_wchodzi(app):
    """Start stołów (spec 5.8) bierze rozpoczęte Pakowanie także bez sposobu dostawy (5.1 po logistyce 4.6)."""
    bez_sposobu = zamowienie(sposob=None, statusy=('czeka_na_pakowanie',))
    bez_sposobu.products[0].quantity_done_packaging = 1
    kurier = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    kurier.products[0].quantity_done_packaging = 1
    db.session.commit()

    assert _rozpoczete('packaging') == [('o:%d' % bez_sposobu.id, 'licznik'), ('o:%d' % kurier.id, 'licznik')]


def test_rozpoczete_lakiernia_nie_ma_stolu(app):
    with pytest.raises(stol.BladStolu) as blad:
        stol.rozpoczete_na_stanowisku('painting')
    assert blad.value.kod == 'stanowisko_bez_stolu'


def _przygotuj(stanowisko, user_id=7):
    db.session.commit()
    wynik = stol.przygotuj_start(stanowisko, user_id, teraz=T0)
    db.session.commit()
    return wynik


def test_przygotuj_start_wstawia_zrodlo_start_ponad_k(app):
    """„Przygotuj stoły”: kafle rozpoczęte stają się wierszami stołu `start` — wszystkie, ponad K."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 4)
    for pozycja in order.products[:3]:
        pozycja.quantity_done_gluing = 1
    db.session.commit()

    wynik = _przygotuj('gluing')

    assert wynik == {'dodane': 3, 'juz_byly': 0}
    assert _na_stole('gluing') == [('p:%d' % p.id, 'start') for p in order.products[:3]]
    wiersz = StationDesk.query.order_by(StationDesk.id).first()
    assert (wiersz.sent_by_user_id, wiersz.pulled_at, wiersz.postponed_at) == (7, T0, None)
    (log,) = PriorityLog.query.all()
    assert (log.action, log.station_code, log.new_value, log.old_value, log.user_id, log.order_id) == (
        'start_stolow', 'gluing', '3', '0', 7, None)


def test_przygotuj_start_bez_reguly_zamowienia(app):
    """K3-poprawka-1: „Przygotuj stoły” kładzie tylko pozycje z licznikiem — nie resztę zamówienia zaczętego na
    stanowisku."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie', 'czeka_na_sklejanie'))
    zrobiona, w_rekach, nietknieta = order.products
    _zdarzenie(zrobiona, 'gluing', 'mobile')
    w_rekach.quantity_done_gluing = 1
    db.session.commit()

    assert _przygotuj('gluing') == {'dodane': 1, 'juz_byly': 0}
    assert _na_stole('gluing') == [('p:%d' % w_rekach.id, 'start')]
    assert nietknieta.id


def test_przygotuj_start_idempotentne(app):
    """Ponowne wywołanie dokłada tylko nowe rozpoczęte; istniejących wierszy (na stole i odłożonych) nie rusza.
    Kafel zdjęty ręcznie wraca, jeśli nadal jest rozpoczęty — poprawki robi się po ostatnim przebiegu."""
    order = zamowienie(statusy=('czeka_na_sklejanie',) * 3)
    a, b, c = order.products
    a.quantity_done_gluing = b.quantity_done_gluing = 1
    db.session.commit()
    _kafel('gluing', b, odlozony=True, zrodlo='kolejka')

    assert _przygotuj('gluing') == {'dodane': 1, 'juz_byly': 1}
    assert _przygotuj('gluing') == {'dodane': 0, 'juz_byly': 2}
    odlozony = StationDesk.query.filter_by(unit_key='p:%d' % b.id).one()
    assert (odlozony.zrodlo, odlozony.postponed_at) == ('kolejka', T0)

    c.quantity_done_gluing = 1
    StationDesk.query.filter_by(unit_key='p:%d' % a.id).delete()
    db.session.commit()
    assert _przygotuj('gluing') == {'dodane': 2, 'juz_byly': 1}
    assert [w.action for w in PriorityLog.query.all()] == ['start_stolow'] * 3


def test_przygotuj_start_kolejnosc_blokad(app):
    """Jak dopełnianie (spec 9.4): blokada stanowiska → zamówienia FOR SHARE → pozycje FOR SHARE → zwykły odczyt
    stołu → INSERT. Bez blokad X zamówień i bez blokowania wierszy stołu."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    order.products[0].quantity_done_gluing = 1
    db.session.commit()

    with Zapytania() as z:
        stol.przygotuj_start('gluing', 7, teraz=T0)
        db.session.flush()

    blokada = _indeks(z, _blokada_stanowiska('gluing'))
    zamowienia = _indeks(z, lambda w: odczyt_biezacy_zamowien(w[0]))
    pozycje = _indeks(z, lambda w: odczyt_biezacy_pozycji_wielu_zamowien(w[0]))
    stol_odczyt = _indeks(z, lambda w: _odczyt_stolu(w[0]))
    wstawka = _indeks(z, lambda w: w[0].startswith('INSERT INTO prod_station_desk'))
    assert blokada == 0 and blokada < zamowienia < pozycje < stol_odczyt < wstawka
    assert not [sql for sql, _p in z.lista if _odczyt_stolu(sql) and _blokujacy(sql)]
    assert not [sql for sql, _p in z.lista if blokada_zamowien(sql) or blokada_pozycji(sql)]


def test_przygotuj_start_widzi_biezacy_stan_pozycji(app, monkeypatch):
    """Pozycja zakończona przez tablet po migawce żądania nie staje się kaflem startowym."""
    order = zamowienie(statusy=('czeka_na_sklejanie', 'czeka_na_sklejanie'))
    zakonczona, zaczeta = order.products
    zakonczona.quantity_done_gluing = zaczeta.quantity_done_gluing = 1
    db.session.commit()
    trzymane = list(order.products)
    oryginal = stol.zablokuj_stanowisko

    def po_blokadzie(stanowisko):
        wynik = oryginal(stanowisko)
        db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == zakonczona.id)
                           .values(current_status='czeka_na_formatowanie'))
        return wynik

    monkeypatch.setattr(stol, 'zablokuj_stanowisko', po_blokadzie)
    assert stol.przygotuj_start('gluing', 7, teraz=T0) == {'dodane': 1, 'juz_byly': 0}
    db.session.commit()
    assert _klucze() == ['gluing/p:%d' % zaczeta.id]
    assert trzymane


def test_zakoncz_w_trybie_stary_zdejmuje_kafel_startowy(app, client):
    """Stoły przygotowane dzień wcześniej, stanowisko jeszcze w `stary`: ZAKOŃCZ bez bramki, a kafel startowy
    schodzi ze stołu razem z pozycją (spec 5.5, 5.8 p. 2)."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    order.products[0].quantity_done_gluing = 1
    db.session.commit()
    _przygotuj('gluing')
    assert _klucze() == ['gluing/p:%d' % order.products[0].id]
    assert stale.TRYBY[0] == 'stary'

    assert _zakoncz(client, order.products[0].id, _naglowki('gluing'), 'gluing').status_code == 200

    assert _klucze() == []


# ── K3-poprawka-2: bramka statusu — 409 `pozycja_poza_stanowiskiem` (rozstrz. 22 centrali, spec 5.5) ─────────

def _poza_stanowiskiem(r, komunikat=None):
    dane = r.get_json()
    assert r.status_code == 409 and dane['error'] == 'pozycja_poza_stanowiskiem', dane
    if komunikat is not None:
        assert dane['message'] == komunikat


def test_poza_stanowiskiem_pakowanie_kafel_zamowienia_z_pozycjami_w_roznych_statusach(app, client):
    """Pakowanie: kafel-zamówienie (wysłany przez biuro, więc i niekompletny) leży na stole. ZAKOŃCZ i licznik
    przechodzą tylko dla pozycji czekającej na Pakowaniu; spakowana i stojąca na Krawędziach dostają 409, bez zapisu
    i bez wpisu idempotencji."""
    order = zamowienie(statusy=('czeka_na_pakowanie', 'spakowane', 'czeka_na_krawedzie'))
    czeka, spakowana, na_krawedziach = order.products
    _kafel('packaging', order, zrodlo=stale.ZRODLO_BIURO)
    _tryb('packaging')
    naglowki = _naglowki('packaging')

    _poza_stanowiskiem(_zakoncz(client, spakowana.id, naglowki, 'packaging'),
                       u'Pozycja %s nie czeka na Pakowaniu.' % spakowana.short_product_id)
    _poza_stanowiskiem(_licz(client, na_krawedziach.id, _nowa_operacja(naglowki), 'packaging'))
    _poza_stanowiskiem(_zakoncz(client, na_krawedziach.id, _nowa_operacja(naglowki), 'packaging'))
    assert ProcessedMobileOperation.query.count() == 0
    assert (_status(spakowana.id), _status(na_krawedziach.id)) == ('spakowane', 'czeka_na_krawedzie')
    db.session.rollback()
    assert db.session.get(ProductionProduct, na_krawedziach.id).quantity_done_packaging in (0, None)

    assert _zakoncz(client, czeka.id, _nowa_operacja(naglowki), 'packaging').status_code == 200
    assert _status(czeka.id) == 'spakowane'


def test_poza_stanowiskiem_formatowanie_niekompletne_zamowienie(app, client):
    """Furtka „Niekompletne” (spec 5.6 p. 2) przepuszcza pozycje zamówienia niekompletnego bez wiersza stołu — ale
    tylko te, które czekają na Formatowaniu. Pozycja ze Sklejania nie może przeskoczyć dalej przez ZAKOŃCZ
    Formatowania (dawniej `complete_task('formatting')` przestawiał ją na Krawędzie)."""
    order = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), numer_wewnetrzny='1203')
    na_formatowaniu, na_sklejaniu = order.products
    _tryb('formatting')
    naglowki = _naglowki('formatting')

    _poza_stanowiskiem(_zakoncz(client, na_sklejaniu.id, naglowki, 'formatting'),
                       u'Pozycja %s nie czeka na Formatowaniu.' % na_sklejaniu.short_product_id)
    _poza_stanowiskiem(_licz(client, na_sklejaniu.id, _nowa_operacja(naglowki), 'formatting'))
    assert _status(na_sklejaniu.id) == 'czeka_na_sklejanie'

    assert _zakoncz(client, na_formatowaniu.id, _nowa_operacja(naglowki), 'formatting').status_code == 200


def test_poza_stanowiskiem_pozycja_omijajaca_stanowisko(app, client):
    """Pozycja bez docięcia omija Formatowanie: zamówienie jest kompletne i leży na stole, ale ZAKOŃCZ tej pozycji na
    Formatowaniu → 409; pozycja z docięciem kończy się normalnie."""
    order = _z_omijajaca()
    z_docieciem, omijajaca = order.products
    _kafel('formatting', order)
    _tryb('formatting')
    naglowki = _naglowki('formatting')

    _poza_stanowiskiem(_zakoncz(client, omijajaca.id, naglowki, 'formatting'))
    assert _status(omijajaca.id) == 'czeka_na_sklejanie'
    assert _zakoncz(client, z_docieciem.id, _nowa_operacja(naglowki), 'formatting').status_code == 200


def test_poza_stanowiskiem_stanowisko_pozycyjne_przed_nie_na_stole(app, client):
    """Stanowisko pozycyjne: pozycja, która poszła dalej (Sklejanie → Formatowanie), dostaje konkretny kod
    `pozycja_poza_stanowiskiem`, nie `nie_na_stole` — appka porzuca wpis bez dodatkowych zapytań."""
    order = zamowienie(statusy=('czeka_na_formatowanie',))
    _tryb('gluing')

    _poza_stanowiskiem(_zakoncz(client, order.products[0].id, _naglowki('gluing'), 'gluing'))
    assert _status(order.products[0].id) == 'czeka_na_formatowanie'


def test_poza_stanowiskiem_bez_bramki_w_stary_dla_starej_appki_i_lakierni(app, client):
    """Tryb `stary`, stara appka (poniżej progu) i Lakiernia — zachowanie sprzed poprawki (bez bramki statusu)."""
    w_stary = zamowienie(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    assert _zakoncz(client, w_stary.products[1].id, _naglowki('formatting'), 'formatting').status_code == 200

    stara = zamowienie(statusy=('czeka_na_formatowanie',))
    _tryb('gluing')
    _prog_wersji(100)
    assert _zakoncz(client, stara.products[0].id, _naglowki('gluing', wersja=50), 'gluing').status_code == 200

    lakiernia = zamowienie(statusy=('czeka_na_pakowanie',))
    _tryb('painting')       # pomyłkowe `stol` dla Lakierni — bramki i tak nie ma (spec 5.5)
    r = _licz(client, lakiernia.products[0].id, _naglowki('painting'), 'painting')
    assert r.status_code == 200, r.get_json()


def test_poza_stanowiskiem_zakoncz_czyta_status_pod_blokada_zamowienia(app, client, monkeypatch):
    """ZAKOŃCZ sprawdza status pozycji wczytanej odczytem bieżącym pod blokadą zamówienia: zmiana statusu
    zatwierdzona przez innego pisarza po migawce żądania jest widoczna (bramka nie decyduje na migawce)."""
    order = zamowienie(statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    _kafel('gluing', pozycja)
    _tryb('gluing')
    naglowki = _naglowki('gluing')

    def cudzy_zapis():
        db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pozycja.id)
                           .values(current_status='czeka_na_formatowanie'))

    _po_resolve_workers(monkeypatch, cudzy_zapis)
    _poza_stanowiskiem(_zakoncz(client, pozycja.id, naglowki, 'gluing'))
    assert _klucze() == ['gluing/p:%d' % pozycja.id]        # odmowa niczego nie zdejmuje
