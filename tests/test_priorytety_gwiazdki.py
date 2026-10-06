# -*- coding: utf-8 -*-
"""
Gwiazdki zamówienia: `gwiazdki.ustaw` (plan K1, Task 4; spec 2026-10-04, sekcje 9.2 i 9.4).

Kolejność: `FOR UPDATE` zamówień rosnąco po id → zapis zamówień i wpisów logu. Bez blokady tras, bez pozycji,
bez commita (commit przed i po robi router) i bez przeliczenia rang.

Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
from datetime import datetime

import pytest

from extensions import db
from modules.production.models import ProductionOrder
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog
from modules.production.priorytety.services import gwiazdki
from tests.blokady_pomocnicze import Zapytania, blokada_zamowien, zapis
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

TERAZ = datetime(2026, 10, 5, 9, 30)


def _trzy_zamowienia():
    ids = [zamowienie().id, zamowienie().id, zamowienie().id]
    db.session.commit()
    return ids


def _gwiazdki(order_id):
    db.session.expire_all()
    order = db.session.get(ProductionOrder, order_id)
    return order.priority_stars, order.priority_stars_set_at, order.priority_stars_set_by


def test_ustaw_blokuje_zamowienia_rosnaco_przed_zapisem(app):
    a, b, c = _trzy_zamowienia()
    with Zapytania() as z:
        gwiazdki.ustaw([c, a, b], 3, user_id=7)
    # blokada zamówień jest PIERWSZYM zapytaniem, rosnąco po id — niezależnie od kolejności w żądaniu
    assert z.pierwsze(blokada_zamowien) == 0
    assert list(z.lista[0][1]) == [a, b, c]
    assert z.pierwsze(blokada_zamowien) < z.pierwsze(zapis)
    # log gwiazdek ma FK do zamówienia — jego INSERT też idzie po blokadzie
    assert z.pierwsze(blokada_zamowien) < z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_priority_log'))
    # bez blokady tras i bez sięgania po pozycje
    assert not [sql for sql, _p in z.lista if 'FROM prod_config' in sql]
    assert not [sql for sql, _p in z.lista if 'prod_products' in sql]
    # po blokadzie same zapisy — żadnego odczytu między nimi
    assert not [sql for sql, _p in z.lista[1:] if sql.startswith('SELECT')]


def test_ustaw_zapisuje_gwiazdki_czas_autora_i_log(app):
    a, b, c = _trzy_zamowienia()
    wynik = gwiazdki.ustaw([b, a], 4, user_id=7, teraz=TERAZ)
    db.session.commit()
    assert wynik == {'zmienione': [a, b], 'bez_zmian': [], 'brak': []}
    assert _gwiazdki(a) == (4, TERAZ, 7) and _gwiazdki(b) == (4, TERAZ, 7)
    assert _gwiazdki(c) == (0, None, None)
    wpisy = PriorityLog.query.order_by(PriorityLog.order_id).all()
    assert [(w.action, w.order_id, w.old_value, w.new_value, w.user_id, w.created_at) for w in wpisy] == [
        ('gwiazdki', a, '0', '4', 7, TERAZ), ('gwiazdki', b, '0', '4', 7, TERAZ)]

    # zdjęcie gwiazdek to też zmiana z wpisem w logu
    assert gwiazdki.ustaw([a], 0, user_id=8)['zmienione'] == [a]
    db.session.commit()
    gw, kiedy, kto = _gwiazdki(a)
    assert (gw, kto) == (0, 8) and kiedy > TERAZ
    ostatni = PriorityLog.query.order_by(PriorityLog.id.desc()).first()
    assert (ostatni.order_id, ostatni.old_value, ostatni.new_value) == (a, '4', '0')


def test_ustaw_pomija_bez_zmian_i_brakujace(app):
    a, b, _c = _trzy_zamowienia()
    gwiazdki.ustaw([a], 2, user_id=1, teraz=TERAZ)
    db.session.commit()
    wynik = gwiazdki.ustaw([b, a, 999999, a, b], 2, user_id=9)
    db.session.commit()
    assert wynik == {'zmienione': [b], 'bez_zmian': [a], 'brak': [999999]}
    # zamówienie bez zmiany zachowuje autora i czas poprzedniego ustawienia, bez drugiego wpisu
    assert _gwiazdki(a) == (2, TERAZ, 1)
    assert _gwiazdki(b)[0] == 2 and _gwiazdki(b)[2] == 9
    assert PriorityLog.query.filter_by(order_id=a).count() == 1
    assert PriorityLog.query.filter_by(order_id=b).count() == 1


@pytest.mark.parametrize('zle', [6, -1, True, False, '3', None, 2.0])
def test_ustaw_odmawia_gwiazdek_poza_0_5(app, zle):
    a, _b, _c = _trzy_zamowienia()
    with Zapytania() as z:
        with pytest.raises(gwiazdki.BladGwiazdek) as e:
            gwiazdki.ustaw([a], zle)
    assert e.value.komunikat
    assert z.lista == []            # odmowa przed jakimkolwiek zapytaniem
    assert _gwiazdki(a)[0] == 0


def test_ustaw_odmawia_zlej_listy_zamowien_i_ponad_limit(app):
    a, _b, _c = _trzy_zamowienia()
    for zle in ([], None, 'abc', a, [a, True], [str(a)], [a, None], [1.0],
                list(range(1, stale.LIMIT_HURTU + 2))):
        with Zapytania() as z:
            with pytest.raises(gwiazdki.BladGwiazdek):
                gwiazdki.ustaw(zle, 3)
        assert z.lista == [], zle
    # dokładnie limit przechodzi (nieistniejące id lądują w „brak”)
    wynik = gwiazdki.ustaw(list(range(1, stale.LIMIT_HURTU + 1)), 3)
    assert len(wynik['zmienione']) + len(wynik['brak']) == stale.LIMIT_HURTU
    db.session.rollback()


def test_ustaw_nie_commituje(app):
    a, b, _c = _trzy_zamowienia()
    assert gwiazdki.ustaw([a, b], 5, user_id=7)['zmienione'] == [a, b]
    db.session.rollback()
    assert _gwiazdki(a) == (0, None, None) and _gwiazdki(b) == (0, None, None)
    assert PriorityLog.query.count() == 0


def test_ustaw_nie_przelicza_rang(app, monkeypatch):
    """Ranga zmienia się dopiero po commicie routera (`kolejka.utrwal_po_commicie`), nigdy w transakcji gwiazdek."""
    from modules.production.priorytety.services import kolejka
    a, _b, _c = _trzy_zamowienia()

    def zakazane(*args, **kwargs):
        raise AssertionError('gwiazdki.ustaw nie moze wolac utrwal')
    monkeypatch.setattr(kolejka, 'utrwal', zakazane)
    gwiazdki.ustaw([a], 5)
    db.session.commit()
    assert db.session.get(ProductionOrder, a).priority_rank is None
