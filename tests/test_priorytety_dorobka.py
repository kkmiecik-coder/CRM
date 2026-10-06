# -*- coding: utf-8 -*-
"""
Doróbka w nowych priorytetach (plan K1, Task 5; spec 2026-10-04, sekcje 3.2, 4.2, 9.5): ranga 0 i ramka od
utworzenia, bez „ręcznego nadpisania”; przeliczenie rang niczego tu nie zmienia; Formatowanie nie kasuje już rangi.

Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProductionProduct, ProductionReworkLog
from modules.production.priorytety.services import kolejka
from modules.production.services import rework_service
from tests.blokady_pomocnicze import Zapytania
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, zamrozony_dzien  # noqa: F401

pytestmark = pytest.mark.usefixtures('zamrozony_dzien', 'czyste_ustawienia')


def _odrzuc(pozycja_id, stanowisko='packaging'):
    return rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                                  rejected_at_station=stanowisko)


def _flagi(pozycja_id):
    db.session.expire_all()
    pozycja = db.session.get(ProductionProduct, pozycja_id)
    return pozycja.priority_rank, pozycja.is_priority, pozycja.priority_manual_override


def test_dorobka_dostaje_range_0_i_is_priority_bez_manual_override(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    oryginal_id = sorted(p.id for p in order.products)[0]
    with Zapytania() as z:
        _oryginal, dorobka, _wpis = _odrzuc(oryginal_id)
    dorobka_id = dorobka.id
    assert _flagi(dorobka_id) == (0, True, False)
    dorobka = db.session.get(ProductionProduct, dorobka_id)
    assert dorobka.original_product_id == oryginal_id
    assert dorobka.current_status == 'czeka_na_wyciecie'
    # ranga idzie w INSERT-cie doróbki — żadnego osobnego UPDATE rangi po wstawieniu
    assert not [sql for sql, _p in z.lista
                if sql.startswith('UPDATE prod_products') and 'priority_rank' in sql.split(' WHERE ')[0]]
    # oryginał nie dostaje nic z priorytetów doróbki
    assert _flagi(oryginal_id) == (None, False, False)


def test_utrwal_zostawia_dorobce_zero(app):
    drabina_domyslna()
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    _oryginal, dorobka, _wpis = _odrzuc(pozycje[0])
    dorobka_id = dorobka.id

    raport = kolejka.utrwal()

    assert raport['success'] is True, raport
    assert (raport['zamowien'], raport['pozycji']) == (1, 3)
    # zmieniają się dwie pozycje zamówienia; doróbka ma swoje 0 od utworzenia
    assert raport['zmienione_pozycje'] == 2
    assert _flagi(dorobka_id) == (0, True, False)
    assert _flagi(pozycje[0]) == (101, False, False) and _flagi(pozycje[1]) == (102, False, False)
    assert db.session.get(type(order), order_id).priority_rank == 1
    drugi = kolejka.utrwal()
    assert (drugi['zmienione_zamowienia'], drugi['zmienione_pozycje']) == (0, 0)


def test_complete_task_na_formatowaniu_nie_rusza_rangi_dorobki_ale_zamyka_log(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    oryginal = order.products[0]
    dorobka = produkt(order, status='czeka_na_sklejanie', sekwencja=1, original_product_id=oryginal.id,
                      priority_rank=0, is_priority=True)
    wpis = ProductionReworkLog(original_product_id=oryginal.id, rework_product_id=dorobka.id, quantity=2,
                               rejected_at_station='packaging', returned_to_station='cutting',
                               reason_category='inne')
    db.session.add(wpis)
    db.session.commit()
    dorobka_id, wpis_id = dorobka.id, wpis.id

    dorobka.complete_task('gluing')
    db.session.commit()

    dorobka = db.session.get(ProductionProduct, dorobka_id)
    assert dorobka.current_status == 'czeka_na_formatowanie'
    # ranga i ramka zostają do końca produkcji — doróbka jest pierwsza na KAŻDYM stanowisku
    assert _flagi(dorobka_id) == (0, True, False)
    # wpis audytu doróbki zamyka się jak dotąd
    assert db.session.get(ProductionReworkLog, wpis_id).closed_at is not None


def test_lock_i_unlock_priority_nic_nie_robia(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_sklejanie',))
    pozycja = order.products[0]
    pozycja.priority_rank, pozycja.is_priority = 205, False
    db.session.commit()

    pozycja.lock_priority(1)
    pozycja.lock_priority(rank=0)          # dawniej ValueError dla rangi < 1
    assert (pozycja.priority_rank, pozycja.is_priority, pozycja.priority_manual_override) == (205, False, False)
    assert pozycja not in db.session.dirty

    # zaszłość z dawnego algorytmu: unlock jej nie rusza (zeruje ją najbliższe kolejka.utrwal)
    pozycja.priority_manual_override = True
    db.session.commit()
    pozycja.unlock_priority()
    assert pozycja.priority_manual_override is True
    assert pozycja.is_priority_locked is True
    assert pozycja not in db.session.dirty
