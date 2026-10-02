# -*- coding: utf-8 -*-
"""
Jedno automatyczne ponowienie zapisu Dostawy po zakleszczeniu MySQL 1213 (fala końcowa kroku 4.4b, znalezisko B1
przeglądu gałęzi). Dostawa blokuje pozycje WSZYSTKICH zamówień trasy w kolejności (zamówienie, id), więc z pisarzami
wielu pozycji bez blokady zamówień (przeliczenie i przeciąganie priorytetów, druk TCP) rzadkie 1213 jest możliwe —
jak w hurcie i przeniesieniu osieroconych. Telefon (`dostawa_api._zapis`) i akcje Dostawy w panelu tras
(`trasy_api._akcja`: odhaczenie, „Cofnij załadunek”, „Cofnij dostarczenie”, „Cofnij zatwierdzenie”) ponawiają raz:
rollback i cały zapis od nowa, decyzja na nowym stanie. Drugie 1213 — 500 bez zapisów; inny kod — bez ponowienia.
Telefon ponawia WEWNĄTRZ handlera, więc wpis idempotencji powstaje raz (dla wyniku drugiej próby).

SQLite nie zakleszcza się — 1213 podajemy podmienioną funkcją serwisu, która najpierw robi PRAWDZIWY zapis (jego
zmiany są w sesji, więc rollback musi je cofnąć), a potem rzuca błąd sterownika.
"""
import pytest
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import bl_sync, dostawa, dostawa_widok
from modules.production.models import ProcessedMobileOperation, ProductionProduct
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import T0, naglowki, telefon_kierowcy, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, DZIS_TESTOW, app, client  # noqa: F401

API = '/api/mobile/delivery'


def _blad_mysql(kod, komunikat='Deadlock found when trying to get lock'):
    return OperationalError('UPDATE prod_products SET ...', {}, Exception(kod, komunikat))


def _scenariusz(monkeypatch, nazwa, wyniki):
    """
    Podmienia `dostawa.<nazwa>`: n-te wywołanie wykonuje PRAWDZIWĄ funkcję (z flushem — zapisy w bazie transakcji),
    a potem rzuca `wyniki[n]`, gdy to wyjątek; poza listą działa normalnie. `wyniki[n]` może też być funkcją bez
    argumentów — wtedy zamiast prawdziwego zapisu wołamy ją (np. cudzy zapis zatwierdzony przed ponowieniem) i rzucamy
    1213. Zwraca listę wywołań (liczba prób).
    """
    oryginal = getattr(dostawa, nazwa)
    wywolania = []

    def falszywa(*args, **kwargs):
        numer = len(wywolania)
        wywolania.append(numer)
        wynik = wyniki[numer] if numer < len(wyniki) else None
        if callable(wynik) and not isinstance(wynik, Exception):
            wynik()
            raise _blad_mysql(1213)
        odpowiedz = oryginal(*args, **kwargs)
        db.session.flush()
        if wynik is not None:
            raise wynik
        return odpowiedz

    monkeypatch.setattr(dostawa, nazwa, falszywa)
    return wywolania


@pytest.fixture(autouse=True)
def bez_propagacji_wyjatkow(app):
    """Błąd, którego zapis nie obsłuży (drugie 1213, inny kod), ma dać odpowiedź 500 jak na serwerze — kontener testów
    ma FLASK_DEBUG=1, a w trybie debug Flask przepuszcza wyjątek do klienta testowego."""
    app.config['PROPAGATE_EXCEPTIONS'] = False


@pytest.fixture()
def dopychacz(monkeypatch):
    """Starty dopychacza Base. (bl_sync.po_zmianie) — każdy z listą zamówień."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    return wywolania


def _w_trasie(k=None):
    """(trasa w drodze z dwoma zamówieniami załadowanymi, pierwsze zamówienie, drugie zamówienie)."""
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', kierowca_id=k.id if k else None, od=DZIS_TESTOW, loaded_at=T0,
              departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t, kto_id=7)
    return t, a, b


def _liczba(order_id, akcja):
    db.session.rollback()
    return LogisticsLog.query.filter_by(order_id=order_id, action=akcja).count()


def _statusy(order_id):
    db.session.rollback()
    return [p.current_status for p in ProductionProduct.query.filter_by(order_id=order_id)
            .order_by(ProductionProduct.id)]


# --- Telefon kierowcy (dostawa_api._zapis) -----------------------------------------------------------------------

def test_telefon_ponawia_raz_po_1213(app, client, monkeypatch, dopychacz):
    """1213 po prawdziwym zapisie pierwszej próby → jedno ponowienie: 200, jeden skutek (pozycje, jeden wpis logu,
    jeden start dopychacza z jednym zamówieniem) i jeden wpis idempotencji."""
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid = t.id, a.id
    proby = _scenariusz(monkeypatch, 'dostarcz', [_blad_mysql(1213)])

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k, op_id='op-1213'))

    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['changed'] is True and len(proby) == 2
    assert _statusy(oid) == ['dostarczone', 'dostarczone']
    assert _liczba(oid, 'dostarczone') == 1
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-1213').count() == 1
    assert dopychacz == [[oid]]


def test_telefon_cofniecie_niedostarczenia_ponawia_raz_po_1213(app, client, monkeypatch, dopychacz):
    """U10: „Cofnij niedostarczenie” z telefonu idzie przez ten sam szkielet zapisu (_zapis) — jedno ponowienie,
    jeden wpis logu i jeden wpis idempotencji."""
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    dostawa.nie_dostarcz(t, a.id, 'odmowa', worker_id=k.id, teraz=T0)
    db.session.commit()
    rid, oid = t.id, a.id
    proby = _scenariusz(monkeypatch, 'cofnij_niedostarczenie', [_blad_mysql(1213)])

    r = client.post(API + '/routes/%d/stops/%d/undo-not-delivered' % (rid, oid),
                    headers=naglowki(device, k, op_id='op-1213-nd'))

    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['changed'] is True and len(proby) == 2
    assert _liczba(oid, 'niedostarczenie_cofniete') == 1
    assert RouteStop.query.filter_by(order_id=oid).one().not_delivered_at is None
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-1213-nd').count() == 1


def test_telefon_druga_proba_decyduje_na_nowym_stanie(app, client, monkeypatch, dopychacz):
    """Ofiara zakleszczenia traci transakcję, a cudzy zapis się zatwierdza (drugi telefon dostarczył ten przystanek).
    Druga próba decyduje na nowym stanie — powtórka bez zmian, bez wpisu i bez dopychacza z pierwszej próby."""
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid, kid = t.id, a.id, k.id
    oryginal = dostawa.dostarcz

    def drugi_telefon_dostarczyl():
        db.session.rollback()                                       # serwer cofa transakcję ofiary
        oryginal(db.session.get(Route, rid), oid, worker_id=kid, teraz=T0)
        db.session.commit()                                         # cudzy zapis zatwierdzony

    proby = []

    def falszywa(*args, **kwargs):
        proby.append(1)
        if len(proby) == 1:
            oryginal(*args, **kwargs)                               # zapis pierwszej próby: plan dopychacza w `g`
            db.session.flush()
            drugi_telefon_dostarczyl()
            raise _blad_mysql(1213)
        return oryginal(*args, **kwargs)

    monkeypatch.setattr(dostawa, 'dostarcz', falszywa)

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k))

    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['changed'] is False and len(proby) == 2
    assert _liczba(oid, 'dostarczone') == 1                         # tylko cudzy wpis
    assert dopychacz == []                                          # plan pierwszej próby porzucony przy rollbacku


def test_telefon_dwa_1213_z_rzedu_to_500_bez_zapisow(app, client, monkeypatch, dopychacz):
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid = t.id, a.id
    proby = _scenariusz(monkeypatch, 'dostarcz', [_blad_mysql(1213), _blad_mysql(1213)])

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k, op_id='op-2x'))

    assert r.status_code == 500 and len(proby) == 2                 # najwyżej jedno ponowienie
    assert _statusy(oid) == ['zaladowane', 'zaladowane'] and _liczba(oid, 'dostarczone') == 0
    assert RouteStop.query.filter_by(order_id=oid).one().delivered_at is None
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-2x').count() == 0   # 5xx niezapamiętane
    assert dopychacz == []


@pytest.mark.parametrize('blad', [_blad_mysql(1205, 'Lock wait timeout exceeded'),
                                  OperationalError('SELECT 1', {}, Exception())], ids=['1205', 'bez_kodu'])
def test_telefon_inny_blad_bez_ponowienia(app, client, monkeypatch, dopychacz, blad):
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid = t.id, a.id
    proby = _scenariusz(monkeypatch, 'dostarcz', [blad])

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k))

    assert r.status_code == 500 and len(proby) == 1
    assert _statusy(oid) == ['zaladowane', 'zaladowane'] and dopychacz == []


def test_telefon_1213_przy_flushu_zapisow_akcji_jest_ponawiane(app, client, monkeypatch, dopychacz):
    """`_zapis` wypycha zapisy akcji flushem WEWNĄTRZ ponowienia, zanim handler odda wynik dekoratorowi idempotencji.
    Zakleszczenie przy tym flushu (UPDATE-y czekają tam na cudze blokady) daje więc jedno ponowienie i 200, a nie 500
    z commitu dekoratora. Pierwszy jawny flush po zbudowaniu odpowiedzi rzuca 1213 — to flush `_zapis`."""
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid = t.id, a.id
    odpowiedzi, rzucone = [], []
    oryginal_widok = dostawa_widok.trasa_po_zapisie

    def widok(trasa_):
        wynik = oryginal_widok(trasa_)
        odpowiedzi.append(1)
        return wynik

    oryginal_flush = db.session.flush

    def flush(*args, **kwargs):
        if odpowiedzi and not rzucone:
            rzucone.append(1)
            raise _blad_mysql(1213)
        return oryginal_flush(*args, **kwargs)

    monkeypatch.setattr(dostawa_widok, 'trasa_po_zapisie', widok)
    monkeypatch.setattr(db.session, 'flush', flush)

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k, op_id='op-flush'))

    assert r.status_code == 200, r.get_data()[:300]
    assert rzucone == [1] and len(odpowiedzi) == 2                  # 1213 przy flushu, potem druga próba
    assert r.get_json()['changed'] is True
    assert _liczba(oid, 'dostarczone') == 1
    assert ProcessedMobileOperation.query.filter_by(operation_id='op-flush').count() == 1
    assert dopychacz == [[oid]]


def test_telefon_ponowienie_zaczyna_od_kierowcy(app, client, monkeypatch):
    """Druga próba zaczyna od nowa od kierowcy: sesje pracowników to pierwsze blokady zapisu telefonu, a rollback
    cofnął ich odświeżenie z pierwszej próby."""
    from modules.production.services import worker_service
    device, k = telefon_kierowcy()
    t, a, _b = _w_trasie(k)
    rid, oid = t.id, a.id
    _scenariusz(monkeypatch, 'dostarcz', [_blad_mysql(1213)])
    dotkniecia = []
    oryginal = worker_service.touch_sessions
    monkeypatch.setattr(worker_service, 'touch_sessions',
                        lambda *a_, **k_: dotkniecia.append(1) or oryginal(*a_, **k_))

    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, oid), headers=naglowki(device, k))

    assert r.status_code == 200, r.get_data()[:300]
    assert len(dotkniecia) == 2


# --- Panel tras (trasy_api._akcja) ------------------------------------------------------------------------------

def _zaladowana():
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a], status='zaladowana', loaded_at=T0)
    zaladuj_wprost(paczki_a, t, kto_id=7)
    return t, a


def _zatwierdzona_w_zaladunku():
    a, paczki_a = zamowienie_z_paczkami()
    t = trasa([a], status='zatwierdzona')
    zaladuj_wprost(paczki_a, t, kto_id=7)
    return t, a


def _dostarczona():
    t, a, _b = _w_trasie()
    dostawa.dostarcz(t, a.id, worker_id=7, teraz=T0)
    db.session.commit()
    return t, a


def _niedostarczona():
    """(trasa w drodze z pierwszym zamówieniem niedostarczonym — U10, przystanek zostaje na trasie, zamówienie)."""
    t, a, _b = _w_trasie()
    dostawa.nie_dostarcz(t, a.id, 'odmowa', worker_id=7, teraz=T0)
    db.session.commit()
    return t, a


def _z_dopychaczem(przygotuj, ktore):
    """Przygotowanie akcji panelu → (trasa, zamówienie akcji, [id zamówień, z którymi dopychacz Base. ma ruszyć raz
    po commicie drugiej próby]); `ktore(trasa, zamówienia)` wybiera je z zamówień przygotowania."""
    def wrapper():
        wynik = przygotuj()
        return wynik[0], wynik[1], sorted(o.id for o in ktore(*wynik))
    return wrapper


AKCJE_PANELU = {
    # nazwa: (funkcja serwisu, przygotowanie → (trasa, zamówienie, oczekiwany dopychacz), ścieżka, ciało,
    #         akcja logu skutku, status trasy po)
    'unload': ('cofnij_zaladunek', _z_dopychaczem(_zaladowana, lambda t, a: [a]), '/routes/{r}/unload', None,
               'zaladunek', 'zatwierdzona'),
    # Zaznaczone a → „Dostarczona” (149778), odznaczone b → „Planowana trasa” (417343): jeden start z oboma.
    'complete': ('odhacz', _z_dopychaczem(_w_trasie, lambda t, a, b: [a, b]), '/routes/{r}/complete',
                 lambda oid: {'delivered_order_ids': [oid]}, 'dostarczone', 'wykonana'),
    'undo-delivered': ('cofnij_dostarczenie', _z_dopychaczem(_dostarczona, lambda t, a: [a]),
                       '/routes/{r}/stops/{o}/undo-delivered', None, 'dostarczenie_cofniete', 'w_trasie'),
    # U10: „Cofnij niedostarczenie” nie zmienia statusów Base.; „Zdejmij z trasy” wysyła 417343.
    'undo-not-delivered': ('cofnij_niedostarczenie', _z_dopychaczem(_niedostarczona, lambda t, a: []),
                           '/routes/{r}/stops/{o}/undo-not-delivered', None, 'niedostarczenie_cofniete', 'w_trasie'),
    'remove-not-delivered': ('zdejmij_niedostarczone', _z_dopychaczem(_niedostarczona, lambda t, a: [a]),
                             '/routes/{r}/stops/{o}/remove-not-delivered', None, 'trasa_usuniete', 'w_trasie'),
    # „Cofnij zatwierdzenie” nie zmienia statusów Base. — dopychacz nie rusza wcale.
    'revert': ('cofnij_zatwierdzenie', _z_dopychaczem(_zatwierdzona_w_zaladunku, lambda t, a: []),
               '/routes/{r}/revert', None, 'zaladunek', 'robocza'),
}


def _post_panelu(client, akcja, rid, oid):
    _funkcja, _przygotuj, sciezka, cialo, _log, _status = AKCJE_PANELU[akcja]
    return client.post(BASE + sciezka.format(r=rid, o=oid), json=cialo(oid) if cialo else None)


@pytest.mark.parametrize('akcja', sorted(AKCJE_PANELU))
def test_panel_ponawia_raz_po_1213(app, client, monkeypatch, dopychacz, akcja):
    funkcja, przygotuj, _sciezka, _cialo, log_skutku, status_po = AKCJE_PANELU[akcja]
    t, a, oczekiwany = przygotuj()
    rid, oid = t.id, a.id
    dopychacz.clear()
    proby = _scenariusz(monkeypatch, funkcja, [_blad_mysql(1213)])

    r = _post_panelu(client, akcja, rid, oid)

    assert r.status_code == 200, r.get_data()[:300]
    assert len(proby) == 2
    assert r.get_json()['route']['status'] == status_po
    assert _liczba(oid, log_skutku) == 1
    # Dokładnie jeden start dopychacza z planem drugiej próby — plan pierwszej przepadł razem z jej rollbackiem.
    assert dopychacz == ([oczekiwany] if oczekiwany else [])


@pytest.mark.parametrize('akcja', sorted(AKCJE_PANELU))
def test_panel_dwa_1213_z_rzedu_to_500_bez_zapisow(app, client, monkeypatch, dopychacz, akcja):
    funkcja, przygotuj, _sciezka, _cialo, log_skutku, _status_po = AKCJE_PANELU[akcja]
    t, a, _oczekiwany = przygotuj()
    rid, oid = t.id, a.id
    status_przed = t.status
    przed = _liczba(oid, log_skutku)
    dopychacz.clear()
    proby = _scenariusz(monkeypatch, funkcja, [_blad_mysql(1213), _blad_mysql(1213)])

    r = _post_panelu(client, akcja, rid, oid)

    assert r.status_code == 500 and len(proby) == 2
    assert _liczba(oid, log_skutku) == przed
    assert db.session.get(Route, rid).status == status_przed and dopychacz == []


@pytest.mark.parametrize('akcja', sorted(AKCJE_PANELU))
def test_panel_inny_kod_bez_ponowienia(app, client, monkeypatch, dopychacz, akcja):
    funkcja, przygotuj, _sciezka, _cialo, _log, _status_po = AKCJE_PANELU[akcja]
    t, a, _oczekiwany = przygotuj()
    rid, oid = t.id, a.id
    status_przed = t.status
    proby = _scenariusz(monkeypatch, funkcja, [_blad_mysql(1205, 'Lock wait timeout exceeded')])

    r = _post_panelu(client, akcja, rid, oid)

    assert r.status_code == 500 and len(proby) == 1
    db.session.rollback()
    assert db.session.get(Route, rid).status == status_przed


def test_panel_cofniecie_zatwierdzenia_ponawia_od_nowej_transakcji_pod_blokada_tras(app, client, monkeypatch):
    """„Cofnij zatwierdzenie” sprawdza znaczniki załadunku zwykłym odczytem, więc transakcja zaczyna się od nowa tuż
    przed blokadą tras (panel_api._zapis_pod_blokada). Ponowienie robi to samo: druga blokada tras wypada przed
    ponownym odczytem trasy w drugiej próbie."""
    from sqlalchemy import event

    from modules.production.logistics.services.routes import KLUCZ_BLOKADY
    t, _a = _zatwierdzona_w_zaladunku()
    rid = t.id
    _scenariusz(monkeypatch, 'cofnij_zatwierdzenie', [_blad_mysql(1213)])

    with Zapytania() as z:
        def rollback(_polaczenie):
            z.lista.append(('ROLLBACK', None))
        event.listen(db.engine, 'rollback', rollback)
        try:
            r = client.post(BASE + '/routes/%d/revert' % rid)
        finally:
            event.remove(db.engine, 'rollback', rollback)

    assert r.status_code == 200, r.get_data()[:300]
    # Rollback po 1213, a po nim — pierwszym zapytaniem drugiej próby — blokada tras, dopiero potem odczyt trasy.
    po_rollbacku = [sql_par for sql_par in z.lista[z.lista.index(('ROLLBACK', None)) + 1:]
                    if sql_par[0] not in ('ROLLBACK', 'COMMIT')]
    pierwsze_sql, parametry = po_rollbacku[0]
    assert (pierwsze_sql.startswith('SELECT') and 'FROM prod_config' in pierwsze_sql
            and pierwsze_sql.endswith(' FOR UPDATE') and KLUCZ_BLOKADY in tuple(parametry or ())), pierwsze_sql
    assert 'FROM prod_routes' in po_rollbacku[1][0]


def test_panel_inne_akcje_tras_bez_ponowienia(app, client, monkeypatch):
    """Ponowienie dotyczy tylko akcji Dostawy — zatwierdzenie trasy (etap 3) po 1213 kończy się 500 po jednej próbie."""
    from modules.production.logistics.services import routes
    a, _p = zamowienie_z_paczkami()
    t = trasa([a], status='robocza')
    rid = t.id
    proby = []
    oryginal = routes.zatwierdz

    def falszywa(*args, **kwargs):
        proby.append(1)
        oryginal(*args, **kwargs)
        raise _blad_mysql(1213)

    monkeypatch.setattr(routes, 'zatwierdz', falszywa)

    r = client.post(BASE + '/routes/%d/approve' % rid)

    assert r.status_code == 500 and len(proby) == 1
