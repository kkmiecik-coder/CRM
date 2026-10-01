# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” w doróbce i w zmianach z Base. (logistyka etap 4, krok 4.4a). SQLite pomija FOR UPDATE
i nie ma migawki MySQL: kolejność blokad sprawdzamy na kolejności zapytań (tests/blokady_pomocnicze.py), a odczyt
bieżący — obiektem zostawionym w sesji w starym stanie przy cudzym zapisie w bazie (surowy UPDATE poza ORM).
Kolejność COMMIT-u i odczytu blokującego — znacznikami na tej samej osi czasu co zapytania (`_os_zdarzen`).
"""
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Query

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services import rework_service
from modules.production.services.sync_service import BaselinkerSyncService
from modules.users.models import User
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, dodaj_pozycje_za_plecami, zapis)
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


@contextmanager
def _os_zdarzen():
    """
    Zapytania SQL (tests/blokady_pomocnicze.py) z dwoma znacznikami na tej samej osi czasu: ('commit', None) przy każdym
    COMMIT-cie połączenia i ('for_update', None) przy każdym zapytaniu z `with_for_update()`. SQLite wycina FOR UPDATE
    z tekstu SQL, więc odczyt blokujący widać tylko po wywołaniu `with_for_update()`; znacznik wpada tuż przed SQL tego
    zapytania (zapytanie wykonuje się zaraz po zbudowaniu).
    """
    with Zapytania() as z:
        def commit(_polaczenie):
            z.lista.append(('commit', None))

        oryginal = Query.with_for_update

        def z_blokada(self, *args, **kwargs):
            z.lista.append(('for_update', None))
            return oryginal(self, *args, **kwargs)

        event.listen(db.engine, 'commit', commit)
        Query.with_for_update = z_blokada
        try:
            yield z
        finally:
            Query.with_for_update = oryginal
            event.remove(db.engine, 'commit', commit)


def _jak_router(z):
    """`current_user.id` w routerze to zwykły odczyt: tu MySQL zakłada migawkę REPEATABLE READ, jeszcze przed wywołaniem
    funkcji serwisu. Znacznik ('router', None) oznacza początek osi czasu po tym odczycie."""
    db.session.query(User.id).first()
    z.lista.append(('router', None))


def _os(zdarzenia):
    """Oś czasu do komunikatów asercji: znaczniki jak są, SQL skrócony do pierwszych 70 znaków."""
    return [e[0] if e[0] in ('router', 'base', 'commit', 'for_update') else e[0][:70] for e in zdarzenia]


def _sprawdz_commit_i_blokujacy_odczyt_id(z, po):
    """
    Po zdarzeniu `po` pierwszy COMMIT (kończy starą migawkę) wypada PRZED pierwszą blokadą zamówień, a zaraz po nim idzie
    odczyt BLOKUJĄCY id zamówienia po baselinker_order_id (jak `_zapis_pod_blokada()` w panelu Logistyki): taki odczyt nie
    zakłada migawki, więc pierwszy zwykły odczyt nowej transakcji (lista pozycji do zablokowania) wypada już po blokadzie
    zamówienia. Zwraca indeks COMMIT-u.
    """
    start = z.lista.index(po)
    commit = z.lista.index(('commit', None), start)
    blokada = z.pierwsze(blokada_zamowien)
    assert commit < blokada, 'COMMIT dopiero po pierwszej blokadzie zamówień: %s' % _os(z.lista[start:blokada + 1])
    assert z.lista[commit + 1] == ('for_update', None), \
        'po COMMIT-cie nie idzie odczyt blokujący: %s' % _os(z.lista[commit:commit + 3])
    assert 'baselinker_order_id' in z.lista[commit + 2][0], \
        'odczyt blokujący nie czyta id po baselinker_order_id: %s' % _os(z.lista[commit:commit + 3])
    return commit


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
    assert list(z.lista[blokada][1]) == [order_id]   # wszystkie pozycje zamówienia, po order_id


def test_dorobka_regula_decyduje_na_pozycjach_z_odczytu_biezacego(app, monkeypatch):
    """Reguła unieważniania etapów (spec 8.5) decyduje po doróbce na pozycjach z odczytu blokującego po `order_id`,
    wykonanego już po zapisie doróbki. Dotąd kolekcja była wygaszana i czytana od nowa zwykłym odczytem — na MySQL
    z migawki sprzed blokady, bez pozycji dodanej w międzyczasie przez inny zapis. W chwili decyzji kolekcja ma
    wszystkie pozycje (także dodaną za plecami ORM przed doróbką i samą doróbkę), a dostęp do niej nie wysyła już
    żadnego zapytania. SQLite nie ma migawki, więc dodaną pozycję widziałby i zwykły odczyt: o tym, skąd jest
    kolekcja, rozstrzyga brak zapytania przy decyzji i odczyt blokujący po INSERT-cie doróbki."""
    from modules.production.logistics.services import weryfikacja
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    dodana = dodaj_pozycje_za_plecami(order_id, 3)
    oryginal = weryfikacja.uniewaznij_etapy
    przy_decyzji = []

    def regula(order_, teraz, powod, **kwargs):
        with Zapytania() as przy_odczycie:
            ids = [p.id for p in order_.products]
        przy_decyzji.append((order_.id, ids, przy_odczycie.lista))
        return oryginal(order_, teraz, powod, **kwargs)

    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy', regula)
    with Zapytania() as z:
        _oryginal, dorobka, _log = _odrzuc(pozycje[1])
    assert len(przy_decyzji) == 1
    zamowienie_id, ids, zapytania_przy_decyzji = przy_decyzji[0]
    assert zapytania_przy_decyzji == [], zapytania_przy_decyzji   # kolekcja z odczytu blokującego, nie leniwa
    assert (zamowienie_id, ids) == (order_id, pozycje + [dodana, dorobka.id])
    wstawienie = z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_products'))
    po_wstawieniu = [i for i, (sql, _p) in enumerate(z.lista) if i > wstawienie and blokada_pozycji(sql)]
    assert po_wstawieniu and list(z.lista[po_wstawieniu[0]][1]) == [order_id]


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
    to ENUM('baselinker_auto','manual_entry') — na MySQL w trybie ścisłym wywracało to całą operację (1265). SQLite nie
    ma CHECK dla ENUM, ale Enum SQLAlchemy rzuca LookupError przy odczycie wartości spoza listy, więc stary kod kończy się
    success False; asercja wartości pilnuje, żeby źródła nie podmienić na inną dozwoloną wartość (stąd 'manual_entry',
    a nie domyślne 'baselinker_auto'). Prawdziwe _create_production_product_from_data (bez podmiany)."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny='1450', sync_source='manual_entry')
    order_id, bl_id = order.id, order.baselinker_order_id
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).sync_source == 'manual_entry'
    assert ProductionProduct.query.filter_by(order_id=order_id).count() == 2


def test_zmiany_z_base_po_wywolaniu_base_zaczynaja_nowa_transakcje_z_blokujacym_odczytem(app, monkeypatch):
    """
    Migawka REPEATABLE READ powstaje przy pierwszym zwykłym odczycie transakcji, w żądaniu admina już w routerze
    (`current_user.id`), czyli PRZED wywołaniem HTTP do Base., które trwa do kilkudziesięciu sekund. Pozycja dopisana
    w tym czasie (np. doróbka z tabletu) nie byłaby widoczna dla zwykłych odczytów pod blokadą zamówienia: wypadłaby
    z listy blokowanych pozycji i z przeliczenia zamknięcia. Po wywołaniu Base. idzie więc COMMIT (kończy starą migawkę),
    a pierwszym poleceniem nowej transakcji jest odczyt BLOKUJĄCY id zamówienia: nie zakłada migawki, więc lista pozycji
    do zablokowania jest czytana już po blokadzie zamówienia.
    """
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny='1450')
    bl_id = order.baselinker_order_id
    with _os_zdarzen() as z:
        _jak_router(z)
        serwis = _serwis_z_nowa_pozycja(monkeypatch, order, zdarzenia=z.lista)
        wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    _sprawdz_commit_i_blokujacy_odczyt_id(z, po=('base', None))


def test_zmiany_z_base_bez_wywolania_base_tez_koncza_stara_migawke(app):
    """To samo bez dodawania pozycji (nie ma wywołania Base.): migawka z początku żądania i tak jest starsza niż blokada
    zamówienia, a czekanie na cudzy zapis (np. doróbkę) zostawiłoby zwykłe odczyty pod blokadą na stanie sprzed niego."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), numer_wewnetrzny='1450')
    pierwsza = order.products[0]
    zmiany = {'products_to_update': [{'id': pierwsza.id, 'short_product_id': pierwsza.short_product_id,
                                      'changes': [{'field': 'quantity', 'new_value': 5}]}]}
    bl_id = order.baselinker_order_id
    serwis = BaselinkerSyncService()
    with _os_zdarzen() as z:
        _jak_router(z)
        wynik = serwis.apply_baselinker_changes(bl_id, zmiany)
    assert wynik['success'] is True and wynik['updated'] == 1, wynik
    _sprawdz_commit_i_blokujacy_odczyt_id(z, po=('router', None))
