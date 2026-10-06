# -*- coding: utf-8 -*-
"""
Lakiernia bez stołu — lista po grupach wykończenia (priorytety produkcji, krok K3, Task 5a; spec 2026-10-04,
ustalenie 15, sekcje 3.2 „Lista Lakierni”, 5.5, 6.3). Lakiernia zostaje na stałe w trybie listy: tablet pokazuje
całą listę, pracownik wybiera sam, ZAKOŃCZ bez bramki stołu, a kolejność listy układa serwer — grupa wykończenia
w jednym ciągu (jedno rozrobione wiadro), grupy po najpilniejszej pozycji.

Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import itertools
from datetime import datetime
from types import SimpleNamespace

import pytest

from extensions import db
from modules.production.models import ProcessedMobileOperation, ProductionDevice, ProductionProduct
from modules.production.priorytety import stale
from modules.production.priorytety.models import StationDesk
from modules.production.priorytety.services import lista, ustawienia
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token, serialize_order
from tests.blokady_pomocnicze import Zapytania
from tests.logistyka_fixtures import app, client, produkt, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, ustaw  # noqa: F401

pytestmark = pytest.mark.usefixtures('czyste_ustawienia')

_licznik = itertools.count(1)
OLEJ_BIALY = dict(parsed_finish_type='olejowane', parsed_finish_color_type='barwne', parsed_finish_color=u'biały')
OLEJ_BEZBARWNY = dict(parsed_finish_type='olejowane', parsed_finish_color_type='bezbarwne')
LAKIER_MAT = dict(parsed_finish_type='lakierowane', parsed_finish_color_type='bezbarwne', parsed_finish_gloss='mat')
LAKIER_POLYSK = dict(parsed_finish_type='lakierowane', parsed_finish_color_type='bezbarwne',
                     parsed_finish_gloss=u'połysk')


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(stanowisko='painting'):
    device = ProductionDevice(device_id='TAB-LAK-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device)}


def _operacja(naglowki):
    return dict(naglowki, **{'X-Operation-Id': 'op-lak-%d' % next(_licznik)})


def _pozycja(ranga, wykonczenie, status='czeka_na_lakiernie', **kolumny):
    """Zamówienie z jedną pozycją o randze `ranga` i wykończeniu `wykonczenie`. Zwraca pozycję."""
    order = zamowienie(statusy=())
    pozycja = produkt(order, status=status, priority_rank=ranga, **dict(wykonczenie, **kolumny))
    db.session.commit()
    return pozycja


def _lista(client, stanowisko='painting', naglowki=None, etag=None):
    naglowki = dict(naglowki or _naglowki(stanowisko))
    if etag:
        naglowki['If-None-Match'] = etag
    return client.get('/api/mobile/stations/%s/orders' % stanowisko, headers=naglowki)


def _ids(odpowiedz):
    return [pozycja['id'] for pozycja in odpowiedz.get_json()['orders']]


# ── klucz grupy (czyste funkcje) ────────────────────────────────────────────────────────────────────────────

def _atrapa(**pola):
    dane = dict(parsed_finish_type=None, parsed_finish_color_type=None, parsed_finish_color=None,
                parsed_finish_gloss=None)
    dane.update(pola)
    return SimpleNamespace(**dane)


def test_klucz_grupy_normalizuje():
    """Klucz jak sortowanie „Partia” w appce (decyzja Konrada 5.10): rodzaj, typ koloru, kolor, a połysk tylko dla
    lakierowanych. Wartości bez spacji na brzegach, małymi literami; pusty napis = brak."""
    assert lista.klucz_grupy_wykonczenia(_atrapa(
        parsed_finish_type=' Olejowane ', parsed_finish_color_type='BARWNE', parsed_finish_color=u' Biały',
        parsed_finish_gloss='mat')) == ('olejowane', 'barwne', u'biały', None)      # olej: połysk się nie liczy
    assert lista.klucz_grupy_wykonczenia(_atrapa(
        parsed_finish_type='lakierowane', parsed_finish_color_type='', parsed_finish_color='   ',
        parsed_finish_gloss=' MAT ')) == ('lakierowane', None, None, 'mat')
    assert lista.klucz_grupy_wykonczenia(_atrapa()) == (None, None, None, None)
    # brak wartości to osobna wartość klucza, a nie „pasuje do wszystkiego”
    assert (lista.klucz_grupy_wykonczenia(_atrapa(parsed_finish_type='lakierowane'))
            != lista.klucz_grupy_wykonczenia(_atrapa(parsed_finish_type='lakierowane', parsed_finish_gloss='mat')))
    # typ koloru rozdziela grupy o tym samym kolorze
    assert (lista.klucz_grupy_wykonczenia(_atrapa(parsed_finish_type='olejowane', parsed_finish_color_type='barwne'))
            != lista.klucz_grupy_wykonczenia(_atrapa(parsed_finish_type='olejowane',
                                                     parsed_finish_color_type='bezbarwne')))


def test_grupa_wykonczenia_json():
    assert lista.grupa_wykonczenia_json(_atrapa(
        parsed_finish_type='lakierowane', parsed_finish_color_type='bezbarwne',
        parsed_finish_gloss=u'Połysk')) == {
            'rodzaj': 'lakierowane', 'typ_koloru': 'bezbarwne', 'kolor': None, 'polysk': u'połysk'}


def test_porzadek_listy_innego_stanowiska_oddaje_te_sama_liste():
    pozycje = [object(), object()]
    assert lista.porzadek_listy('gluing', pozycje) is pozycje
    assert set(ustawienia.STANOWISKA_BEZ_STOLU) == {'painting'}


# ── lista Lakierni (Review Focus 9) ─────────────────────────────────────────────────────────────────────────

def test_lista_lakierni_grupy_wykonczenia_w_jednym_ciagu(app, client):
    """Grupy przeplecione rangami (A 1, B 2, A 3, B 4) wychodzą ciągiem: A1, A3, B2, B4 — także gdy w środku
    grupy stoi pozycja mniej pilna niż pierwsza pozycja następnej grupy (jedno rozrobione wiadro)."""
    a1 = _pozycja(101, OLEJ_BIALY)
    b2 = _pozycja(201, LAKIER_MAT)
    a3 = _pozycja(301, OLEJ_BIALY)
    b4 = _pozycja(401, LAKIER_MAT)

    assert _ids(_lista(client)) == [a1.id, a3.id, b2.id, b4.id]


def test_lista_lakierni_grupa_bez_limitu(app, client):
    pilna_inna = _pozycja(150, LAKIER_MAT)
    grupa = [_pozycja(100 + 100 * i, OLEJ_BIALY) for i in range(12)]

    assert _ids(_lista(client)) == [p.id for p in grupa] + [pilna_inna.id]


def test_lista_lakierni_grupy_po_najpilniejszej_pozycji(app, client):
    a_pozna = _pozycja(205, OLEJ_BIALY)
    b_pilna = _pozycja(101, LAKIER_MAT)
    b_pozna = _pozycja(900, LAKIER_MAT)
    c = _pozycja(150, LAKIER_POLYSK)

    # grupa z najpilniejszą pozycją pierwsza: B (101), potem C (150), potem A (205)
    assert _ids(_lista(client)) == [b_pilna.id, b_pozna.id, c.id, a_pozna.id]


def test_lista_lakierni_remis_grup_po_kluczu_grupy(app, client):
    """Pozycje bez rangi (zamówienia jeszcze nieprzeliczone) i z tego samego zamówienia: o kolejności grup
    rozstrzyga klucz pozycji, a przy pełnym remisie — nazwa grupy; brak wartości na końcu."""
    order = zamowienie(statusy=())
    bez_wykonczenia = produkt(order, status='czeka_na_lakiernie', sekwencja=1, parsed_finish_type=None)
    olej = produkt(order, status='czeka_na_lakiernie', sekwencja=2, **OLEJ_BIALY)
    lakier = produkt(order, status='czeka_na_lakiernie', sekwencja=3, **LAKIER_MAT)
    db.session.commit()

    # te same rangi (brak) i ten sam numer zamówienia: grupy po najmniejszym id pozycji
    assert _ids(_lista(client)) == [bez_wykonczenia.id, olej.id, lakier.id]


def test_lista_lakierni_dorobka_pierwsza_i_jej_grupa_pierwsza(app, client):
    """Doróbka ciągnie swoją grupę na początek listy (potwierdzone przez Konrada 5.10): grupa z doróbką przed każdą
    bez doróbki, doróbka na jej początku; dwie doróbki w różnych grupach — grupa starszej doróbki pierwsza."""
    pilna = _pozycja(101, OLEJ_BIALY)
    w_grupie_dorobki = _pozycja(500, LAKIER_MAT)
    order = zamowienie(statusy=('czeka_na_pakowanie',))
    mlodsza = produkt(order, status='czeka_na_lakiernie', priority_rank=0, original_product_id=order.products[0].id,
                      created_at=datetime(2026, 10, 5, 9, 0), **LAKIER_MAT)
    starsza = produkt(order, status='czeka_na_lakiernie', priority_rank=0, original_product_id=order.products[0].id,
                      created_at=datetime(2026, 10, 5, 7, 0), **LAKIER_POLYSK)
    db.session.commit()

    kolejnosc = [i for i in _ids(_lista(client)) if i != order.products[0].id]
    assert kolejnosc == [starsza.id, mlodsza.id, w_grupie_dorobki.id, pilna.id]


def test_lista_lakierni_pozycje_w_innych_statusach_na_koncu(app, client):
    """Lista oddaje całe zamówienia (appka pokazuje resztę jako kontekst): pozycje w innych statusach idą na
    koniec, po dzisiejszym kluczu (ranga, numer, id)."""
    order = zamowienie(statusy=())
    w_pakowaniu = produkt(order, status='czeka_na_pakowanie', sekwencja=1, priority_rank=101)
    na_lakierni = produkt(order, status='czeka_na_lakiernie', sekwencja=2, priority_rank=102, **OLEJ_BIALY)
    inna = _pozycja(300, LAKIER_MAT)
    db.session.commit()

    assert _ids(_lista(client)) == [na_lakierni.id, inna.id, w_pakowaniu.id]


def test_lista_lakierni_bez_rangi_na_koncu_grupy(app, client):
    bez_rangi = _pozycja(None, OLEJ_BIALY)
    z_ranga = _pozycja(700, OLEJ_BIALY)
    inna = _pozycja(800, LAKIER_MAT)

    assert _ids(_lista(client)) == [z_ranga.id, bez_rangi.id, inna.id]


@pytest.mark.parametrize('stanowisko', ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging'])
def test_lista_innych_stanowisk_bez_zmian(app, client, stanowisko):
    """Pozostałe stanowiska: kolejność listy jak dotąd (ranga, numer zamówienia, id) — wykończenie jej nie rusza —
    i `grupa_wykonczenia` równe null."""
    from modules.production.services.mobile_api_service import STATION_STATUS_MAP
    status = STATION_STATUS_MAP[stanowisko]
    c = _pozycja(300, OLEJ_BIALY, status=status)
    a = _pozycja(100, LAKIER_MAT, status=status)
    b = _pozycja(200, OLEJ_BIALY, status=status)
    bez_rangi = _pozycja(None, LAKIER_MAT, status=status)

    r = _lista(client, stanowisko)

    assert _ids(r) == [a.id, b.id, c.id, bez_rangi.id]
    assert all(pozycja['grupa_wykonczenia'] is None for pozycja in r.get_json()['orders'])


def test_delta_lakierni_all_ids_w_kolejnosci_listy(app, client):
    a1 = _pozycja(101, OLEJ_BIALY)
    b2 = _pozycja(201, LAKIER_MAT)
    a3 = _pozycja(301, OLEJ_BIALY)
    order = zamowienie(statusy=())
    w_pakowaniu = produkt(order, status='czeka_na_pakowanie', sekwencja=1, priority_rank=50)
    db.session.commit()
    naglowki = _naglowki()

    r = client.get('/api/mobile/stations/painting/orders/since?ts=2020-01-01T00:00:00', headers=naglowki)

    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    # delta niesie tylko pozycje w statusie Lakierni — w kolejności listy
    assert dane['all_ids'] == [a1.id, a3.id, b2.id]
    assert [pozycja['id'] for pozycja in dane['changed']] == [a1.id, a3.id, b2.id]
    assert dane['changed'][0]['grupa_wykonczenia'] == {
        'rodzaj': 'olejowane', 'typ_koloru': 'barwne', 'kolor': u'biały', 'polysk': None}
    assert w_pakowaniu.id not in dane['all_ids']

    # zmienione tylko dwie pozycje: względna kolejność jak na liście
    tabela = ProductionProduct.__table__
    db.session.execute(tabela.update().where(tabela.c.id.in_([b2.id, a3.id]))
                       .values(updated_at=datetime(2030, 1, 1)))
    db.session.commit()
    r = client.get('/api/mobile/stations/painting/orders/since?ts=2029-01-01T00:00:00', headers=naglowki)
    assert [pozycja['id'] for pozycja in r.get_json()['changed']] == [a3.id, b2.id]
    assert r.get_json()['all_ids'] == [a1.id, a3.id, b2.id]


def test_delta_innego_stanowiska_bez_zmian(app, client):
    c = _pozycja(300, OLEJ_BIALY, status='czeka_na_sklejanie')
    a = _pozycja(100, LAKIER_MAT, status='czeka_na_sklejanie')

    r = client.get('/api/mobile/stations/gluing/orders/since?ts=2020-01-01T00:00:00',
                   headers=_naglowki('gluing'))

    assert r.get_json()['all_ids'] == [a.id, c.id]


def test_lista_lakierni_etag_bez_zmian_budowy_ksztalt_6(app, client):
    """ETag listy liczy się jak dotąd (max updated_at, liczba, KSZTALT): zmiana wykończenia pozycji podbija
    `updated_at`, więc daje nowy ETag i nową kolejność; bez zmian danych — 304."""
    a = _pozycja(101, OLEJ_BIALY)
    b = _pozycja(201, LAKIER_MAT)
    c = _pozycja(301, OLEJ_BIALY)
    naglowki = _naglowki()
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 6

    pierwsza = _lista(client, naglowki=naglowki)
    etag = pierwsza.headers['ETag']
    assert etag.endswith(':6"') and _ids(pierwsza) == [a.id, c.id, b.id]
    assert _lista(client, naglowki=naglowki, etag=etag).status_code == 304

    pozycja = db.session.get(ProductionProduct, c.id)
    pozycja.parsed_finish_type, pozycja.parsed_finish_gloss = 'lakierowane', 'mat'
    pozycja.parsed_finish_color_type, pozycja.parsed_finish_color = 'bezbarwne', None
    pozycja.updated_at = datetime(2030, 1, 1)
    db.session.commit()

    druga = _lista(client, naglowki=naglowki, etag=etag)
    assert druga.status_code == 200 and druga.headers['ETag'] != etag
    assert _ids(druga) == [a.id, b.id, c.id]


def test_serialize_order_grupa_wykonczenia(app):
    pozycja = _pozycja(101, LAKIER_POLYSK)

    dla_lakierni = serialize_order(pozycja, station_code='painting')
    assert dla_lakierni['grupa_wykonczenia'] == {
        'rodzaj': 'lakierowane', 'typ_koloru': 'bezbarwne', 'kolor': None, 'polysk': u'połysk'}
    klucze = list(dla_lakierni)
    assert klucze.index('grupa_wykonczenia') == klucze.index('priorytet') + 1
    assert serialize_order(pozycja, station_code='edges')['grupa_wykonczenia'] is None
    assert serialize_order(pozycja)['grupa_wykonczenia'] is None


# ── Lakiernia nie ma stołu: bramka, desk, postpone ──────────────────────────────────────────────────────────

def test_bramka_lakierni_otwarta_mimo_trybu_stol(app, client):
    """Pomyłkowe `priorytety_tryb_painting = stol` w Konfiguracji nie może zatrzymać ZAKOŃCZ z listy: bramka stołu
    Lakierni nie dotyczy nigdy — i w ogóle nie czyta stołu."""
    ustaw(stale.klucz_tryb('painting'), 'stol')
    ustaw(stale.KLUCZ_MIN_APP, 0, 'integer')
    pierwsza = _pozycja(101, OLEJ_BIALY)
    druga = _pozycja(102, OLEJ_BIALY)
    naglowki = _naglowki()

    r = client.patch('/api/mobile/orders/%d/quantity' % pierwsza.id, headers=_operacja(naglowki),
                     json={'station_code': 'painting', 'quantity_done': 1})
    assert r.status_code == 200, r.get_json()

    with Zapytania() as z:
        r = client.post('/api/mobile/orders/%d/complete' % druga.id, headers=_operacja(naglowki),
                        json={'station_code': 'painting'})
    assert r.status_code == 200, r.get_json()
    odczyty_stolu = [sql for sql, _p in z.lista if sql.startswith('SELECT') and 'FROM prod_station_desk' in sql]
    # jedyny odczyt stołu to uzgodnienie wierszy zamówienia po ZAKOŃCZ (po order_id) — bramka stołu nie czyta
    assert all('WHERE prod_station_desk.order_id = ?' in sql for sql in odczyty_stolu)
    assert not [1 for _sql, parametry in z.lista
                if any(str(p).startswith('priorytety_tryb_') for p in (parametry or ()))]


def test_desk_i_postpone_lakierni_409_bez_zapisu(app, client):
    pozycja = _pozycja(101, OLEJ_BIALY)
    oczekiwane = {'error': 'stanowisko_bez_stolu', 'message': u'Lakiernia pracuje z listy, bez stołu.'}

    for stanowisko in ('edges', 'painting'):            # tablet Krawędzi obsługuje też Lakiernię
        naglowki = _naglowki(stanowisko)
        with Zapytania() as z:
            r = client.get('/api/mobile/stations/painting/desk', headers=naglowki)
        assert r.status_code == 409 and r.get_json() == oczekiwane
        assert not [1 for _sql, parametry in z.lista
                    if any(str(p).startswith('priorytety_blokada_') for p in (parametry or ()))]

        with Zapytania() as z:
            r = client.post('/api/mobile/orders/%d/postpone' % pozycja.id, headers=_operacja(naglowki),
                            json={'station_code': 'painting', 'zakres': 'pozycja', 'powod': 'brak_materialu'})
        assert r.status_code == 409 and r.get_json() == oczekiwane
        # odmowa od razu w handlerze: bez blokady zamówienia i bez odczytu stołu
        assert not [sql for sql, _p in z.lista if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]

    db.session.rollback()
    assert StationDesk.query.count() == 0
    assert ProcessedMobileOperation.query.count() == 0


def test_serwis_stolu_odmawia_lakierni(app):
    """Zapora w samym serwisie: stół Lakierni nie powstaje, nawet gdy ktoś ominie router."""
    from modules.production.priorytety.services import stol
    _pozycja(101, OLEJ_BIALY)
    db.session.commit()

    with pytest.raises(stol.BladStolu) as blad:
        stol.dopelnij('painting')
    assert (blad.value.kod, blad.value.status) == ('stanowisko_bez_stolu', 409)
    db.session.rollback()
    assert StationDesk.query.count() == 0
