# -*- coding: utf-8 -*-
"""
U10, runda 1 poprawek (przeglądy części 1 i 2): zamknięcie trasy z niedostarczonymi KAŻDĄ ścieżką — doróbka i zmiana
z Base. (także bez powrotu do produkcji, C2), panelowe „Zdejmij z trasy” na trasie już rozliczonej; wymagane
zamówienia przy zamknięciu; postęp ze stałym mianownikiem; historia jako ostatni odczyt blokujący zapisu telefonu;
teksty komunikatów telefonu ze stanu pod blokadami; liczba zapytań list i szczegółów z historią.
"""
import gc

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import dostawa, routes
from modules.production.models import ProductionPackage, ProductionProduct
from modules.production.services import rework_service
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import (T0, naglowki, odsmiecaj_po_blokadach, telefon_kierowcy, trasa, zaladuj_wprost,
                                     zamowienie_z_paczkami, zwykle_odczyty_stanu)
from tests.logistyka_fixtures import BASE, DZIS_TESTOW, app, client  # noqa: F401
from tests.test_dostawa_dorobka_na_trasie import _serwis_z_nowa_pozycja

API = '/api/mobile/delivery'
T1 = T0.replace(hour=9)
T2 = T0.replace(hour=10)
WYSLANE, PLANOWANA = 149763, 417343


def _zaladowane(statusy=('zaladowane', 'zaladowane')):
    order, lista = zamowienie_z_paczkami(statusy=statusy)
    order.bl_status_pending_id = WYSLANE
    db.session.commit()
    return order, lista


def _w_trasie(*zamowienia, kierowca_id=None):
    t = trasa([o for o, _ in zamowienia], status='w_trasie', loaded_at=T0, departed_at=T0, kierowca_id=kierowca_id,
              od=DZIS_TESTOW)
    for _o, lista in zamowienia:
        zaladuj_wprost(lista, t, kto_id=7)
    return t


def _dostarczony(t, order):
    """Przystanek dostarczony wprost w bazie (bez dostawa.dostarcz — ten zamknąłby trasę za wcześnie)."""
    stop = RouteStop.query.filter_by(route_id=t.id, order_id=order.id).one()
    stop.delivered_at, stop.delivered_by_worker_id = T0, 7
    for p in order.products:
        p.current_status = 'dostarczone'
    db.session.commit()


def _w_pakowaniu(order):
    return next(p for p in order.products if p.current_status == 'czeka_na_pakowanie')


def _sprawdz_zejscie_do_puli(order_id, paczki_ids, route_id, kto):
    """A zeszło do puli przy zamknięciu: bez przystanku, pozycje zweryfikowane, znaczniki czyste, 417343, wpis."""
    db.session.expire_all()
    assert RouteStop.query.filter_by(order_id=order_id).first() is None
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).all()
    assert {p.current_status for p in pozycje} == {'zweryfikowane'}
    assert pozycje[0].order.bl_status_pending_id == PLANOWANA
    assert all(db.session.get(ProductionPackage, i).loaded_route_id is None for i in paczki_ids)
    usuniete, = LogisticsLog.query.filter_by(order_id=order_id, action='trasa_usuniete', route_id=route_id).all()
    assert usuniete.note == 'niedostarczone' and (usuniete.worker_id, usuniete.user_id) == kto
    assert LogisticsLog.query.filter_by(order_id=order_id, action='trasa_status').count() == 0


# --- Important (cz. 1 #1): zamknięcie trasy przez doróbkę i zmianę z Base. ----------------------------------------

def test_dorobka_zamyka_trase_i_zdejmuje_niedostarczone_do_puli(app):
    a, b, c = _zaladowane(), _zaladowane(('zaladowane', 'czeka_na_pakowanie')), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    db.session.commit()
    _dostarczony(t, c[0])
    route_id, a_id, c_id, paczki_a = t.id, a[0].id, c[0].id, [p.id for p in a[1]]

    rework_service.reject_product_quantity(product_id=_w_pakowaniu(b[0]).id, quantity=1, reason_category='inne',
                                           rejected_at_station='packaging', worker_ids=[9])

    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert (trasa_po.status, trasa_po.completed_by) == ('wykonana', None)
    assert [s.order_id for s in trasa_po.stops] == [c_id]
    _sprawdz_zejscie_do_puli(a_id, paczki_a, route_id, (9, None))
    wpis, = LogisticsLog.query.filter_by(order_id=c_id, action='trasa_status').all()   # tylko przy tych, które zostały
    assert (wpis.old_value, wpis.new_value) == ('w_trasie', 'wykonana')


def test_zmiana_z_base_zamyka_trase_i_zdejmuje_niedostarczone_do_puli(app, monkeypatch):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    _dostarczony(t, c[0])
    route_id, a_id, c_id, paczki_a = t.id, a[0].id, c[0].id, [p.id for p in a[1]]

    wynik = _serwis_z_nowa_pozycja(monkeypatch, b[0]).apply_baselinker_changes(
        b[0].baselinker_order_id, {'products_to_add': [{'order_product_id': '77'}]}, user_id=5)

    assert wynik['success'] is True, wynik
    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert trasa_po.status == 'wykonana' and [s.order_id for s in trasa_po.stops] == [c_id]
    _sprawdz_zejscie_do_puli(a_id, paczki_a, route_id, (None, 5))


def test_zamkniecie_przez_dorobke_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Ruling P2 na ścieżce doróbki, która zamyka trasę i zdejmuje niedostarczone: od pierwszej blokady zamówień żaden
    zwykły SELECT zamówień, pozycji, paczek ani tras (obiekty odłączone, pamięć odśmiecana po blokadach)."""
    a, b = _zaladowane(), _zaladowane(('zaladowane', 'czeka_na_pakowanie'))
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    db.session.commit()
    route_id, pozycja_id = t.id, _w_pakowaniu(b[0]).id
    db.session.expunge_all()
    gc.collect()
    licznik = odsmiecaj_po_blokadach(monkeypatch)
    with Zapytania() as z:
        rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                               rejected_at_station='packaging', worker_ids=[9])
    assert licznik['zapisz_log'] > 0
    db.session.expire_all()
    assert db.session.get(Route, route_id).status == 'wykonana'
    # Odczyt pozycji po PK (prod_products.id = ?) robi sama doróbka, także bez U10 i bez zamknięcia trasy (sprawdzone
    # sondą na trasie otwartej) — poza zakresem; z zamknięcia i zejścia do puli nie ma żadnego zwykłego odczytu.
    assert [sql for sql in zwykle_odczyty_stanu(z) if not sql.endswith('WHERE prod_products.id = ?')] == []


# --- cz. 1 #3: trasa rozliczona bez zdarzenia zamykającego (C2) -------------------------------------------------

def test_zmiana_z_base_bez_powrotu_do_produkcji_zamyka_trase_rozliczona(app):
    """Klient anulował w Base. ostatni otwarty przystanek B (C2: przystanek anulowanego w całości jest rozliczony),
    reszta jest niedostarczona — zmiana z Base. nie cofa B do produkcji, ale zamyka trasę, a A schodzi do puli."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    for p in b[0].products:
        p.current_status = 'anulowane'          # anulowanie z Base. zapisane przez serwis zmian
    db.session.commit()
    route_id, a_id, b_id, paczki_a = t.id, a[0].id, b[0].id, [p.id for p in a[1]]

    routes.zablokuj_trasy()
    blokady = dostawa.blokady_trasy_w_drodze(b_id)
    assert dostawa.zdejmij_z_trasy_w_drodze(blokady, blokady[1][b_id], dostawa.POWOD_ZMIANY_BASE, T2,
                                            user_id=5) is None
    db.session.commit()

    trasa_po = db.session.get(Route, route_id)
    assert trasa_po.status == 'wykonana' and [s.order_id for s in trasa_po.stops] == [b_id]
    _sprawdz_zejscie_do_puli(a_id, paczki_a, route_id, (None, 5))


def test_zdejmij_z_trasy_w_panelu_zamyka_trase_rozliczona(app):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, c[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    db.session.commit()
    for p in b[0].products:
        p.current_status = 'anulowane'          # C2: rozliczona, ale nikt jej nie zamknął
    db.session.commit()
    assert t.status == 'w_trasie'
    route_id, c_id, paczki_c = t.id, c[0].id, [p.id for p in c[1]]

    trasa_po = dostawa.zdejmij_niedostarczone(t, a[0].id, user_id=1, teraz=T2)
    db.session.commit()

    assert (trasa_po.status, trasa_po.completed_by) == ('wykonana', None)
    assert [s.order_id for s in trasa_po.stops] == [b[0].id]
    _sprawdz_zejscie_do_puli(c_id, paczki_c, route_id, (None, 1))


def test_zdejmij_z_trasy_nierozliczonej_nie_zamyka(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert dostawa.zdejmij_niedostarczone(t, a[0].id, user_id=1, teraz=T2).status == 'w_trasie'


# --- cz. 1 #2: zamknięcie wymaga zamówień trasy ---------------------------------------------------------------------

def test_zamkniecie_bez_zamowienia_niedostarczonego_to_blad_programisty(app):
    a = _zaladowane()
    t = _w_trasie(a)
    stop = RouteStop.query.filter_by(order_id=a[0].id).one()
    stop.not_delivered_at, stop.not_delivered_reason = T1, 'odmowa'
    db.session.commit()
    with pytest.raises(RuntimeError, match='brak zablokowanego zamówienia'):
        dostawa._zamknij_jesli_rozliczona(t, T2, {}, {})
    db.session.rollback()
    with pytest.raises(TypeError):
        dostawa._zamknij_jesli_rozliczona(t, T2)   # pylint: disable=no-value-for-parameter


def test_rozliczenie_rozpakowuje_sie_jak_krotka_i_liczy_zdjete(app):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    wynik = dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    assert (wynik[1:], wynik.zdjete_do_puli) == ((True, False), 0)
    dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T1)
    trasa_po, zmieniono, zamknieta = wynik = dostawa.dostarcz(t, c[0].id, worker_id=7, teraz=T2)
    assert (zmieniono, zamknieta, wynik.zdjete_do_puli) == (True, True, 2)
    assert dostawa.dostarcz(trasa_po, c[0].id, worker_id=7).zdjete_do_puli == 0      # powtórka


# --- cz. 1 #4: postęp ze stałym mianownikiem -----------------------------------------------------------------------

def test_postep_mianownik_staly_przy_zamknieciu(app, client):
    """R32.8 po rundzie 1: Y = przystanki + zdjęte DO PULI jako niedostarczone. Anulowane w całości niedostarczone
    nie liczy się ani przed zamknięciem, ani po nim; doróbka nie jest zejściem do puli."""
    a, b = _zaladowane(), _zaladowane()
    c = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, c[0].id, 'inne', worker_id=7, teraz=T1)
    db.session.commit()
    rid = t.id
    przed = client.get(BASE + '/routes/%d' % rid).get_json()['route']['postep']
    assert przed == {'przystanki': 2, 'zaladowane': 2, 'dostarczone': 0, 'niedostarczone': 1, 'zdjete': 0}
    dostawa.dostarcz(db.session.get(Route, rid), b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    po = client.get(BASE + '/routes/%d' % rid).get_json()['route']
    assert po['status'] == 'wykonana'
    assert po['postep'] == {'przystanki': 1, 'zaladowane': 1, 'dostarczone': 1, 'niedostarczone': 1, 'zdjete': 1}
    assert przed['przystanki'] + przed['zdjete'] == po['postep']['przystanki'] + po['postep']['zdjete']
    # Historia (removed_not_delivered / niedostarczone_zdjete) pokazuje oba — to informacja, nie licznik.
    assert sorted(h['order_id'] for h in po['niedostarczone_zdjete']) == sorted([a[0].id, c[0].id])
    lista = next(x for x in client.get(BASE + '/routes').get_json()['routes'] if x['id'] == rid)
    assert lista['postep'] == po['postep']


def test_zdjete_do_postepu_pomija_powrot_do_produkcji(app):
    historia = {1: [{'order_id': 10, 'powod': 'dorobka'}, {'order_id': 11, 'powod': 'zmiana_base'}]}
    assert dostawa.zdjete_do_postepu(historia) == {1: []}


# --- cz. 1 uwaga obowiązkowa: historia jako ostatni odczyt blokujący zapisu telefonu -------------------------------

def test_historia_ostatnim_odczytem_blokujacym_zapisu_telefonu(app, client):
    """Odczyt historii (LOCK IN SHARE MODE na indeksie route_id) to OSTATNI odczyt blokujący transakcji zapisu
    telefonu — po nim zapis na nic już nie czeka; numer i klient zdjętych idą potem zwykłym odczytem, bez ORDER BY
    w odczycie blokującym. Telefon nie pokazuje niedostarczonego jako „do dostarczenia” w żadnym polu."""
    device, k = telefon_kierowcy()
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, kierowca_id=k.id)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=k.id, teraz=T1)
    db.session.commit()
    with Zapytania() as z:
        r = client.post(API + '/routes/%d/stops/%d/delivered' % (t.id, b[0].id), headers=naglowki(device, k))
    assert r.status_code == 200 and r.get_json()['route_completed'] is True
    blokujace = [sql for sql, _p in z.lista if sql.startswith('SELECT')
                 and sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    ostatni = blokujace[-1]
    assert 'FROM prod_logistics_log' in ostatni and 'prod_logistics_log.route_id IN' in ostatni
    assert 'ORDER BY' not in ostatni
    po = z.lista[[sql for sql, _p in z.lista].index(ostatni) + 1:]
    assert any('FROM prod_orders' in sql for sql, _p in po)         # numer i klient zdjętych — zwykły odczyt
    # Przed zamknięciem: niedostarczony nie wygląda jak załadowany ani do dostarczenia.
    c, d = _zaladowane(), _zaladowane()
    t2 = _w_trasie(c, d, kierowca_id=k.id)
    dostawa.nie_dostarcz(t2, c[0].id, 'odmowa', worker_id=k.id, teraz=T1)
    db.session.commit()
    trasa_ = client.get(API + '/routes/%d' % t2.id, headers=naglowki(device, k)).get_json()['route']
    stop = next(s for s in trasa_['stops'] if s['order_id'] == c[0].id)
    assert (stop['state'], stop['state_label'], stop['delivered_at']) == ('niedostarczone', u'Niedostarczone', None)
    assert stop['not_delivered'] is not None
    assert (trasa_['stops_delivered'], trasa_['stops_not_delivered']) == (0, 1)


# --- cz. 2 #1: komunikaty telefonu ze stanu pod blokadami ------------------------------------------------------------

def test_komunikat_zamkniecia_bez_puli_gdy_nic_nie_zeszlo(app, client):
    """Zamknięcie dostarczeniem niedostarczonego X (B anulowane w Base. już po niedostarczeniu X — trasa rozliczona,
    ale niezamknięta; C dostarczone): do puli nic nie schodzi, więc bez dopisku o puli — dawny odczyt sprzed blokad
    liczył X jako „były niedostarczone”."""
    device, k = telefon_kierowcy()
    x, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(x, b, c, kierowca_id=k.id)
    _dostarczony(t, c[0])
    dostawa.nie_dostarcz(t, x[0].id, 'odmowa', worker_id=k.id, teraz=T1)
    db.session.commit()
    for p in b[0].products:
        p.current_status = 'anulowane'
    db.session.commit()
    assert t.status == 'w_trasie'
    r = client.post(API + '/routes/%d/stops/%d/delivered' % (t.id, x[0].id), headers=naglowki(device, k))
    dane = r.get_json()
    assert dane['route_completed'] is True
    assert dane['message'] == u'Dostarczono zamówienie {}. Trasa zakończona.'.format(x[0].internal_order_number)


def test_komunikat_zamkniecia_po_zdjeciu_w_panelu(app, client):
    """Logistyk zdjął niedostarczone A w panelu, potem kierowca dostarcza ostatnie B — przy tym zamknięciu nic nie
    zeszło do puli, więc bez dopisku."""
    device, k = telefon_kierowcy()
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, kierowca_id=k.id)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=k.id, teraz=T1)
    db.session.commit()
    dostawa.zdejmij_niedostarczone(t, a[0].id, user_id=1, teraz=T1)
    db.session.commit()
    dane = client.post(API + '/routes/%d/stops/%d/delivered' % (t.id, b[0].id), headers=naglowki(device, k)).get_json()
    assert dane['message'] == u'Dostarczono zamówienie {}. Trasa zakończona.'.format(b[0].internal_order_number)


def test_komunikat_powtorki_niedostarczenia_po_zamknieciu(app, client):
    device, k = telefon_kierowcy()
    a = _zaladowane()
    t = _w_trasie(a, kierowca_id=k.id)
    adres = API + '/routes/%d/stops/%d/not-delivered' % (t.id, a[0].id)
    dane = client.post(adres, headers=naglowki(device, k), json={'reason': 'odmowa'}).get_json()
    assert dane['route_completed'] is True
    dane = client.post(adres, headers=naglowki(device, k), json={'reason': 'odmowa'}).get_json()
    assert (dane['changed'], dane['route_completed']) == (False, False)
    assert dane['message'] == u'Zamówienie {} było już rozliczone jako niedostarczone.'.format(
        a[0].internal_order_number)


# --- cz. 2 #2: liczba zapytań z historią -----------------------------------------------------------------------------

def _licz_zapytania(client, sciezka):
    licznik = []
    sluchacz = lambda *a, **k: licznik.append(1)  # noqa: E731
    event.listen(db.engine, 'before_cursor_execute', sluchacz)
    try:
        r = client.get(BASE + sciezka)
    finally:
        event.remove(db.engine, 'before_cursor_execute', sluchacz)
    assert r.status_code == 200, r.get_data()[:300]
    return len(licznik), r.get_json()


def _trasy_ze_zdjetymi(ile_tras, ile_zamowien):
    """Trasy w drodze i dostarczone, każda z `ile_zamowien` przystankami: połowa zostaje (jeden dostarczony),
    połowa niedostarczona i zdjęta do puli w panelu (na trasie w drodze) albo przy zamknięciu (dostarczona)."""
    wynik = []
    for i in range(ile_tras):
        zam = [_zaladowane() for _ in range(2 * ile_zamowien)]
        t = _w_trasie(*zam)
        for order, _l in zam[ile_zamowien:]:
            dostawa.nie_dostarcz(t, order.id, 'odmowa', worker_id=7, teraz=T1)
        db.session.commit()
        if i % 2:
            for order, _l in zam[:ile_zamowien]:
                dostawa.dostarcz(t, order.id, worker_id=7, teraz=T2)       # ostatnie zamyka trasę
        else:
            for order, _l in zam[ile_zamowien:]:
                dostawa.zdejmij_niedostarczone(t, order.id, user_id=1, teraz=T2)
        db.session.commit()
        wynik.append(t.id)
    return wynik


def test_lista_tras_z_historia_stala_liczba_zapytan(app, client):
    _trasy_ze_zdjetymi(1, 1)
    malo, dane = _licz_zapytania(client, '/routes?od=2026-01-01')
    assert len(dane['routes']) == 1
    _trasy_ze_zdjetymi(3, 3)
    duzo, dane = _licz_zapytania(client, '/routes?od=2026-01-01')
    assert len(dane['routes']) == 4
    assert duzo == malo, (malo, duzo)
    assert all(t['postep']['zdjete'] for t in dane['routes'])


@pytest.mark.parametrize('dostarczona', [False, True])
def test_szczegoly_trasy_z_historia_stala_liczba_zapytan(app, client, dostarczona):
    male = _trasy_ze_zdjetymi(2, 2)[1 if dostarczona else 0]
    duze = _trasy_ze_zdjetymi(2, 12)[1 if dostarczona else 0]
    _licz_zapytania(client, '/routes/%d' % male)        # pierwsze wejście może przeliczyć przebieg
    _licz_zapytania(client, '/routes/%d' % duze)
    malo, dane_male = _licz_zapytania(client, '/routes/%d' % male)
    duzo, dane_duze = _licz_zapytania(client, '/routes/%d' % duze)
    assert (len(dane_male['route']['niedostarczone_zdjete']), len(dane_duze['route']['niedostarczone_zdjete'])) == \
        (2, 12)
    assert duzo == malo, (malo, duzo)
