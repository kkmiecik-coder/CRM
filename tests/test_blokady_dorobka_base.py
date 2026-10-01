# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” w doróbce i w zmianach z Base. (logistyka etap 4, krok 4.4a). SQLite pomija FOR UPDATE
i nie ma migawki MySQL: kolejność blokad sprawdzamy na kolejności zapytań (tests/blokady_pomocnicze.py), a odczyt
bieżący — obiektem zostawionym w sesji w starym stanie przy cudzym zapisie w bazie (surowy UPDATE poza ORM).
"""
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services import rework_service
from modules.production.services.sync_service import BaselinkerSyncService
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, zapis
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

T0 = datetime(2026, 10, 1, 8, 0)
_POZYCJE = ProductionProduct.__table__


def _odrzuc(pozycja_id, stanowisko='packaging'):
    return rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                                  rejected_at_station=stanowisko)


def _serwis_z_nowa_pozycja(monkeypatch, order, zdarzenia=None):
    """Serwis z Base. podmienionym na odpowiedź z jedną nową pozycją (bez sieci, bez parsera nazw).
    `zdarzenia` — lista, do której wywołanie Base. dopisuje ('base', None) w kolejności zapytań SQL."""
    serwis = BaselinkerSyncService()

    def zamowienie_z_base(_id):
        if zdarzenia is not None:
            zdarzenia.append(('base', None))
        return {'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]}

    def nowa_pozycja(dane):
        return ProductionProduct(order_id=order.id, short_product_id=dane['short_product_id'],
                                 product_sequence_in_order=dane['product_sequence_in_order'],
                                 original_product_name=dane['original_product_name'], quantity=1,
                                 current_status='czeka_na_wyciecie')

    monkeypatch.setattr(serwis, 'get_order_from_baselinker', zamowienie_z_base)
    monkeypatch.setattr(serwis, '_create_production_product_from_data', nowa_pozycja)
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    return serwis


# --- Doróbka -------------------------------------------------------------------------------------------

def test_dorobka_blokuje_zamowienie_przed_pozycjami_przed_zapisem(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    with Zapytania() as z:
        _odrzuc(pozycje[1])
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert sorted(z.lista[blokada][1]) == pozycje


def test_dorobka_sprawdza_stanowisko_na_biezacym_statusie(app):
    """Pozycja w sesji czeka na pakowanie (migawka), a w bazie inny tablet ją już spakował — doróbka z pakowania
    dostaje 409 zamiast cofnąć spakowaną sztukę."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    pozycja = order.products[0]
    assert pozycja.current_status == 'czeka_na_pakowanie'
    db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pozycja.id).values(current_status='spakowane'))
    assert pozycja.current_status == 'czeka_na_pakowanie'          # obiekt w sesji nadal stary
    with pytest.raises(rework_service.RejectError) as e:
        _odrzuc(pozycja.id)
    assert e.value.code == 'product_not_on_station'


# --- Zmiany z Base. ---------------------------------------------------------------------------------------

def test_zmiany_z_base_pytaja_base_przed_blokadami(app, monkeypatch):
    """Wywołanie Base. trwa do kilkudziesięciu sekund — nie może się odbyć pod blokadą wiersza zamówienia, na którą
    czekają tablety (timeout gunicorna 30 s)."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny='1450')
    bl_id = order.baselinker_order_id
    with Zapytania() as z:
        serwis = _serwis_z_nowa_pozycja(monkeypatch, order, zdarzenia=z.lista)
        wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    base = next(i for i, (sql, _p) in enumerate(z.lista) if sql == 'base')
    assert base < z.pierwsze(blokada_zamowien)


def test_zmiany_z_base_blokuja_zamowienie_przed_zapisem_pozycji(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane'))
    order_id = order.id
    pierwsza = order.products[0]
    zmiany = {'products_to_update': [{'id': pierwsza.id, 'short_product_id': pierwsza.short_product_id,
                                      'changes': [{'field': 'quantity', 'new_value': 5}]}],
              'order_level': [{'field': 'delivery_city', 'new_value': u'Rzeszów'}]}
    bl_id = order.baselinker_order_id
    with Zapytania() as z:
        wynik = BaselinkerSyncService().apply_baselinker_changes(bl_id, zmiany)
    assert wynik['success'] is True and wynik['updated'] == 1, wynik
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]


def test_zmiany_z_base_nowa_pozycja_otwiera_zamkniete_od_razu(app, monkeypatch):
    """Zamknięte zamówienie kurierskie z nową pozycją z Base. wraca do otwartych od razu, nie po godzinnym cronie."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny='1450', logistics_closed_at=T0)
    order_id, bl_id = order.id, order.baselinker_order_id
    serwis = _serwis_z_nowa_pozycja(monkeypatch, order)
    wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).logistics_closed_at is None


def test_zmiany_z_base_usuniecie_niespakowanej_zamyka_kuriera_od_razu(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_wyciecie'))
    order_id, bl_id = order.id, order.baselinker_order_id
    usuwana = order.products[1]
    wynik = BaselinkerSyncService().apply_baselinker_changes(
        bl_id, {'products_to_remove': [{'id': usuwana.id, 'short_product_id': usuwana.short_product_id}]})
    assert wynik['success'] is True and wynik['removed'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).logistics_closed_at is not None


def test_zmiany_z_base_nowa_pozycja_nie_nadpisuje_zrodla_synchronizacji(app, monkeypatch):
    """Decyzja Konrada 1.10: dodanie pozycji z panelu admina ustawiało zamówieniu sync_source='admin_update', a kolumna
    to ENUM('baselinker_auto','manual_entry') — na MySQL w trybie ścisłym wywracało to całą operację (1265). SQLite
    ENUM-u nie pilnuje, więc sprawdzamy samą wartość. Prawdziwe _create_production_product_from_data (bez podmiany)."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny='1450', sync_source='baselinker_auto')
    order_id, bl_id = order.id, order.baselinker_order_id
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).sync_source == 'baselinker_auto'
    assert ProductionProduct.query.filter_by(order_id=order_id).count() == 2
