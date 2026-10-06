# -*- coding: utf-8 -*-
"""Krok 4.3, spec 8.7: zmiana sposobu dostawy na zamówieniu w całości spakowanym wymaga decyzji o przepakowaniu."""
import re

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import delivery as d
from modules.production.models import ProductionPackage, get_local_now
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

T0 = get_local_now().replace(microsecond=0)

OBOWIAZKOWE = [(s.TRANSPORT, s.KURIER), (s.ODBIOR, s.KURIER),
               (s.KURIER, s.BRAK), (s.TRANSPORT, s.BRAK), (s.ODBIOR, s.BRAK)]
DOBROWOLNE = [(s.KURIER, s.TRANSPORT), (s.KURIER, s.ODBIOR), (s.TRANSPORT, s.ODBIOR), (s.ODBIOR, s.TRANSPORT)]


def test_banery_logistyki():
    assert s.baner_logistyki(None) == u'Logistyka: sposób dostawy do ustalenia'
    assert s.baner_logistyki(s.BRAK) == u'Logistyka: sposób dostawy do ustalenia'
    assert s.baner_logistyki(s.KURIER) == u'Logistyka: zmiana sposobu dostawy na Kurier'
    assert s.baner_logistyki(s.TRANSPORT) == u'Logistyka: zmiana sposobu dostawy na Transport WoodPower'
    assert s.baner_logistyki(s.ODBIOR) == u'Logistyka: zmiana sposobu dostawy na Odbiór osobisty'


@pytest.mark.parametrize('tekst, systemowy', [
    (None, True), (u'', True), (s.PRZEPAKUJ_NA_KURIERA, True), (s.baner_logistyki(None), True),
    (s.baner_logistyki(s.ODBIOR), True), (u'Weryfikacja: Uszkodzenie: pęknięty blat', False),
])
def test_baner_systemowy_to_brak_kurier_albo_panel(tekst, systemowy):
    assert s.baner_systemowy(tekst) is systemowy


@pytest.mark.parametrize('stary,nowy,obowiazkowe', [(st, no, True) for st, no in OBOWIAZKOWE]
                         + [(st, no, False) for st, no in DOBROWOLNE]
                         + [(None, s.KURIER, False), (None, s.ODBIOR, False)])
def test_przepakowanie_obowiazkowe(stary, nowy, obowiazkowe):
    # W OBOWIAZKOWE „nie ustawiono” jest zapisane jako s.BRAK, a przepakowanie_obowiazkowe dostaje None.
    assert d.przepakowanie_obowiazkowe(stary, None if nowy == s.BRAK else nowy) is obowiazkowe


def _akcje():
    return [l.action for l in LogisticsLog.query.order_by(LogisticsLog.id)]


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE + DOBROWOLNE)
def test_bez_decyzji_wymaga_decyzji_i_nic_nie_zmienia(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane', 'zweryfikowane'))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, nowy, teraz=T0)
        assert e.value.dane['kod'] == 'wymaga_decyzji_przepakowania'
        oczekiwane = ['przepakuj'] if (stary, nowy) in OBOWIAZKOWE else ['przepakuj', 'bez_przepakowania']
        assert e.value.dane['opcje'] == oczekiwane
        assert s.normalizuj(order.override_delivery_method) == stary
        assert [p.current_status for p in order.products] == ['spakowane', 'zweryfikowane']
        assert _akcje() == []


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE)
def test_bez_przepakowania_przy_obowiazkowym_odmawia(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane',))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, nowy, teraz=T0, przepakowanie=False)
        assert e.value.dane['kod'] == 'wymaga_przepakowania'
        assert s.normalizuj(order.override_delivery_method) == stary
        assert order.products[0].current_status == 'spakowane'


@pytest.mark.parametrize('stary,nowy', DOBROWOLNE)
def test_bez_przepakowania_przy_dobrowolnym_zmienia_jak_dotad(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane',))
        wynik = d.ustaw_sposob_dostawy(order, nowy, teraz=T0, przepakowanie=False)
        assert wynik['zmieniono'] is True and wynik['przepakowanie'] is False
        assert order.override_delivery_method == nowy
        assert order.products[0].current_status == 'spakowane'
        assert order.bl_status_pending_id == s.STATUS_PO_SPAKOWANIU[nowy]
        assert order.repack_required is False


@pytest.mark.parametrize('stary,nowy', OBOWIAZKOWE + DOBROWOLNE)
def test_z_przepakowaniem_cofa_do_pakowania(app, stary, nowy):
    with app.app_context():
        order = zamowienie(sposob=stary, statusy=('spakowane', 'zweryfikowane'))
        # Deklaracja paczek i weryfikacja: reguła unieważniania etapów działa tylko na zamówieniu, które je ma.
        order.verified_at = T0
        order.packages_declared_at = T0
        db.session.add(ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=T0))
        db.session.commit()
        wynik = d.ustaw_sposob_dostawy(order, nowy, user_id=3, teraz=T0, przepakowanie=True)
        db.session.commit()
        assert wynik['przepakowanie'] is True
        assert all(p.current_status == 'czeka_na_pakowanie' for p in order.products)
        assert all(p.packaging_completed_at is None for p in order.products)
        assert order.repack_required is True
        assert order.verified_at is None
        assert order.packages_declared_at is None
        assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order.id))
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        if nowy == s.BRAK:
            assert order.override_delivery_method is None
            assert order.repack_reason == s.baner_logistyki(None)
        elif nowy == s.KURIER:
            assert order.repack_reason == s.PRZEPAKUJ_NA_KURIERA
        else:
            assert order.override_delivery_method == nowy
            assert order.repack_reason == s.baner_logistyki(nowy)
        assert 'przepakowanie' in _akcje()


def test_czesciowo_spakowane_jak_dotad_bez_decyzji(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'czeka_na_pakowanie'))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)          # bez parametru: auto, jak dotąd
        assert wynik['przepakowanie'] is True
        order2 = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'czeka_na_pakowanie'))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order2, s.BRAK, teraz=T0, przepakowanie=True)
        assert e.value.dane.get('kod') is None                             # dawny błąd „nie da się cofnąć”


def test_baner_weryfikacji_nie_jest_nadpisywany(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        order.repack_required = True
        order.repack_reason = u'Weryfikacja: Uszkodzenie: pęknięty blat'
        db.session.commit()
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0, przepakowanie=True)
        assert order.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat'


def test_baner_logistyki_przepisuje_sie_przy_kolejnej_zmianie(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0, przepakowanie=True)
        assert order.repack_reason == s.baner_logistyki(s.ODBIOR)
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)    # pozycje już w pakowaniu → zwykła zmiana
        assert order.repack_required is True
        assert order.repack_reason == s.baner_logistyki(s.TRANSPORT)


def test_brak_z_przepakowaniem_potem_wybor_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0, przepakowanie=True)
        assert order.override_delivery_method is None
        assert order.repack_reason == s.baner_logistyki(None)
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)
        assert order.override_delivery_method == s.ODBIOR
        assert order.repack_reason == s.baner_logistyki(s.ODBIOR)


def test_blokady_wygrywaja_z_decyzja(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('dostarczone',))
        order.handed_over_at = T0
        db.session.commit()
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0, przepakowanie=True)
        assert e.value.dane.get('kod') is None


def _post(client, ids, sposob, **extra):
    dane = {'order_ids': ids, 'sposob': sposob}
    dane.update(extra)
    return client.post(BASE + '/orders/delivery-method', json=dane)


def test_endpoint_bez_decyzji_nie_zmienia_i_zwraca_kod(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        nie = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        ids = [spak.id, nie.id]
    r = _post(client, ids, s.ODBIOR)
    assert r.status_code == 200
    j = r.get_json()
    assert j['zmienione'] == [ids[1]]
    [b] = j['bledy']
    assert b['order_id'] == ids[0] and b['kod'] == 'wymaga_decyzji_przepakowania'
    assert b['opcje'] == ['przepakuj', 'bez_przepakowania'] and b['komunikat']


def test_endpoint_z_decyzja_true_przepakowuje(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        i = spak.id
    j = _post(client, [i], s.TRANSPORT, przepakowanie=True).get_json()
    assert j['przepakowanie'] == [i] and j['zmienione'] == [i]


def test_endpoint_false_przy_obowiazkowym_w_bledach(app, client):
    with app.app_context():
        spak = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        i = spak.id
    j = _post(client, [i], s.KURIER, przepakowanie=False).get_json()
    assert j['zmienione'] == [] and j['bledy'][0]['kod'] == 'wymaga_przepakowania'


@pytest.mark.parametrize('wartosc', ['tak', 1, 0, [], {}])
def test_endpoint_zla_wartosc_przepakowania_422(client, wartosc):
    r = _post(client, [1], s.KURIER, przepakowanie=wartosc)
    assert r.status_code == 422


def test_endpoint_blokuje_zamowienia_przed_odczytem_pozycji(app, client):
    """Kolejność zapytań: SELECT zamówień ORDER BY id (FOR UPDATE na MySQL) przed SELECT pozycji i przed zapisami."""
    from sqlalchemy import event
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        b = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        ids = [b.id, a.id]
        zapytania = []
        silnik = db.engine

        def sluchaj(conn, cursor, statement, parameters, context, executemany):
            zapytania.append(statement)
        event.listen(silnik, 'before_cursor_execute', sluchaj)
        try:
            _post(client, ids, s.ODBIOR, przepakowanie=False)
        finally:
            event.remove(silnik, 'before_cursor_execute', sluchaj)
    # Zapytanie blokujące wybiera WYŁĄCZNIE kolumnę id (SELECT prod_orders.id AS prod_orders_id FROM prod_orders …,
    # na MySQL z FOR UPDATE), a pełny odczyt zamówień ma dalej kolejne kolumny. Predykat nie łapie więc zwykłego
    # odczytu: bez blokady zamówień test pada (sprawdzone cofnięciem jej na chwilę).
    i_zam = next(i for i, q in enumerate(zapytania)
                 if re.match(r'\s*SELECT\s+prod_orders\.id(\s+AS\s+prod_orders_id)?\s+FROM\s+prod_orders', q, re.I)
                 and 'ORDER BY' in q.upper())
    i_poz = next(i for i, q in enumerate(zapytania) if 'FROM prod_products' in q)
    i_upd = next(i for i, q in enumerate(zapytania) if q.lstrip().upper().startswith('UPDATE'))
    assert i_zam < i_poz < i_upd


# ── I1b: jedno automatyczne ponowienie po zakleszczeniu 1213 (fala końcowa 8.7) ──────────────────
# Panel jest ofiarą zakleszczenia ze stanowiskiem (spec 8.7, „Współbieżność”). Żądanie jest bezpieczne
# do powtórzenia, bo decyzja jest jawna w ciele, więc `delivery_method` powtarza zapis najwyżej raz
# i tylko po 1213. Błąd po ponowieniu idzie do globalnego handlera OperationalError (app.py: rollback
# i odpowiedź 500); apka testowa go nie ma (a w trybie debug Flask przepuszcza wyjątek do testu),
# więc `_globalny_handler` go odtwarza.

def _blad_mysql(kod, komunikat):
    from sqlalchemy.exc import OperationalError
    return OperationalError('UPDATE prod_orders SET ...', {}, Exception(kod, komunikat))


def _globalny_handler(app):
    """Odpowiednik handlera OperationalError z app.py: rollback i 500. Rejestrować przed pierwszym żądaniem."""
    from flask import jsonify
    from sqlalchemy.exc import OperationalError

    @app.errorhandler(OperationalError)
    def _blad_bazy(e):
        db.session.rollback()
        return jsonify({'error': 'database_error'}), 500


def _scenariusz(monkeypatch, wyniki):
    """Podmienia `ustaw_sposob_dostawy`: n-te wywołanie najpierw wykonuje PRAWDZIWĄ zmianę (zostaje w sesji,
    więc rollback musi ją cofnąć), a potem rzuca `wyniki[n]`, gdy to wyjątek. Poza listą działa normalnie.
    Zwraca listę numerów zamówień z kolejnych wywołań."""
    oryginal = d.ustaw_sposob_dostawy
    wywolania = []

    def falszywa(order, sposob, **kwargs):
        wynik = oryginal(order, sposob, **kwargs)
        numer = len(wywolania)
        wywolania.append(order.id)
        if numer < len(wyniki) and wyniki[numer] is not None:
            raise wyniki[numer]
        return wynik
    monkeypatch.setattr(d, 'ustaw_sposob_dostawy', falszywa)
    return wywolania


def _sposob_w_bazie(order_id):
    from modules.production.models import ProductionOrder
    db.session.rollback()   # świeży odczyt, bez migawki z poprzedniego żądania
    return ProductionOrder.query.get(order_id).override_delivery_method


def test_endpoint_ponawia_raz_po_1213_i_zmienia_zamowienie(app, client, monkeypatch):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        i = order.id
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(1213, 'Deadlock found when trying to get lock')])
    r = _post(client, [i], s.ODBIOR)
    assert r.status_code == 200
    j = r.get_json()
    assert j['success'] is True and j['zmienione'] == [i] and j['bledy'] == []
    assert wywolania == [i, i]                      # pierwsza próba (1213) i jedno ponowienie
    with app.app_context():
        assert _sposob_w_bazie(i) == s.ODBIOR
        assert len(_akcje()) == 1                   # wpis logu z pierwszej próby wycofał rollback


def test_endpoint_ponowienie_liczy_wyniki_od_zera(app, client, monkeypatch):
    """Hurt dwóch zamówień: 1213 na drugim w pierwszej próbie. Wynik drugiej próby nie dokłada pierwszego
    zamówienia drugi raz."""
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        b = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        ids = [a.id, b.id]
    wywolania = _scenariusz(monkeypatch, [None, _blad_mysql(1213, 'Deadlock')])
    j = _post(client, ids, s.ODBIOR).get_json()
    assert wywolania == [ids[0], ids[1], ids[0], ids[1]]
    assert j['zmienione'] == ids and j['bledy'] == []


def test_endpoint_druga_proba_decyduje_na_nowym_stanie(app, client, monkeypatch):
    """Między próbami stanowisko spakowało zamówienie (commit zamyka 1213). Ponowienie widzi stan po
    commicie: zamówienie w całości spakowane bez decyzji → `wymaga_decyzji_przepakowania`, nic się nie zmienia."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        i = order.id
    oryginal = d.ustaw_sposob_dostawy
    wywolania = []

    def stanowisko_wygrywa(order, sposob, **kwargs):
        wywolania.append(order.id)
        if len(wywolania) == 1:
            db.session.rollback()
            for p in order.products:
                p.current_status = 'spakowane'      # commit „stanowiska” poza naszą transakcją
            db.session.commit()
            raise _blad_mysql(1213, 'Deadlock')
        return oryginal(order, sposob, **kwargs)
    monkeypatch.setattr(d, 'ustaw_sposob_dostawy', stanowisko_wygrywa)
    j = _post(client, [i], s.ODBIOR).get_json()
    assert wywolania == [i, i]
    assert j['zmienione'] == []
    assert [b['kod'] for b in j['bledy']] == ['wymaga_decyzji_przepakowania']
    with app.app_context():
        assert _sposob_w_bazie(i) == s.KURIER


def test_endpoint_dwa_1213_z_rzedu_to_500_i_zamowienie_bez_zmian(app, client, monkeypatch):
    _globalny_handler(app)
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        i = order.id
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(1213, 'Deadlock'), _blad_mysql(1213, 'Deadlock')])
    r = _post(client, [i], s.ODBIOR)
    assert r.status_code == 500
    assert wywolania == [i, i]                      # najwyżej jedno ponowienie
    with app.app_context():
        assert _sposob_w_bazie(i) == s.KURIER and _akcje() == []


def test_endpoint_inny_operational_error_nie_jest_ponawiany(app, client, monkeypatch):
    _globalny_handler(app)
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        i = order.id
    wywolania = _scenariusz(monkeypatch, [_blad_mysql(2006, 'MySQL server has gone away')])
    r = _post(client, [i], s.ODBIOR)
    assert r.status_code == 500
    assert wywolania == [i]
    with app.app_context():
        assert _sposob_w_bazie(i) == s.KURIER
