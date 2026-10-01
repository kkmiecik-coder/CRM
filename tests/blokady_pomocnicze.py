# -*- coding: utf-8 -*-
"""
Pomocnik testów kolejności blokad („zamówienie najpierw”, logistyka etap 4, krok 4.4a).

SQLite pomija FOR UPDATE, więc kolejności blokad pilnujemy na kolejności samych zapytań (jak
tests/test_produkty_masowa_zmiana_statusu.py): blokada zamówień to zawsze `WHERE prod_orders.id IN (…)
ORDER BY prod_orders.id`, blokada pozycji — wszystkie pozycje jednego zamówienia po `order_id`,
`WHERE prod_products.order_id = ? ORDER BY prod_products.id` (parametr: id zamówienia;
modules/production/services/blokady_zamowien.py), a zapis — pierwszy UPDATE albo INSERT zamówienia lub pozycji
(także INSERT do tabeli z FK do `prod_orders`: patrz `zapis`). Leniwe wczytanie `order.products` ma odwrotny
warunek (`WHERE ? = prod_products.order_id`) i nie ma ORDER BY, więc predykat go nie łapie.

Oba predykaty blokad wymagają też, żeby odczyt był BLOKUJĄCY. SQLite wycina FOR UPDATE z tekstu SQL, więc
`Zapytania` czyta klauzulę z samego zapytania (`with_for_update()` → `compiled.statement._for_update_arg`,
SQLAlchemy 1.4, Select z ORM i z Core) i dopisuje ją na końcu zapamiętanego SQL tak, jak wysłałby ją MySQL:
` FOR UPDATE` albo ` LOCK IN SHARE MODE` (`with_for_update(read=True)`). Zwykły SELECT tego samego kształtu
nie jest blokadą i predykaty go nie łapią.
"""
from sqlalchemy import event

from extensions import db
from modules.production.models import ProductionProduct


class Zapytania(object):
    """Zapytania SQL w kolejności wykonania (spłaszczone spacje) razem z parametrami."""

    def __init__(self):
        self.lista = []

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self._zapisz)
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, 'before_cursor_execute', self._zapisz)
        return False

    def _zapisz(self, conn, cursor, statement, parameters, context, executemany):
        sql = ' '.join(statement.split())
        blokada = klauzula_blokady(context)
        if blokada and not sql.endswith(blokada):
            sql += ' ' + blokada
        self.lista.append((sql, parameters))

    def pierwsze(self, warunek):
        """Indeks pierwszego zapytania spełniającego `warunek(sql)`; brak → StopIteration (test pada)."""
        return next(i for i, (sql, _parametry) in enumerate(self.lista) if warunek(sql))


def klauzula_blokady(context):
    """
    'FOR UPDATE' albo 'LOCK IN SHARE MODE' (składnia MySQL dla `with_for_update(read=True)`), gdy zapytanie jest
    odczytem blokującym; inaczej None (zwykły SELECT, zapis, surowy SQL bez skompilowanego zapytania).
    """
    zapytanie = getattr(getattr(context, 'compiled', None), 'statement', None)
    argument = getattr(zapytanie, '_for_update_arg', None)
    if argument is None:
        return None
    return 'LOCK IN SHARE MODE' if argument.read else 'FOR UPDATE'


def blokada_zamowien(sql):
    return (sql.startswith('SELECT') and 'FROM prod_orders' in sql and 'WHERE prod_orders.id IN' in sql
            and 'ORDER BY prod_orders.id' in sql and sql.endswith(' FOR UPDATE'))


def blokada_pozycji(sql):
    return (sql.startswith('SELECT') and 'FROM prod_products' in sql and 'WHERE prod_products.order_id = ?' in sql
            and 'ORDER BY prod_products.id' in sql and sql.endswith(' FOR UPDATE'))


def zapis(sql):
    """
    Pierwszy zapis, który może czekać na cudzą blokadę zamówienia albo pozycji: UPDATE/INSERT/DELETE zamówienia lub
    pozycji, a także INSERT do tabel z FK do `prod_orders` (`prod_logistics_log`, `prod_packages`,
    `prod_route_stops`) — InnoDB sprawdza FK blokadą S na wierszu zamówienia, więc taki INSERT przed blokadą
    zamówienia to też sięgnięcie po zamówienie.
    """
    return sql.startswith(('UPDATE prod_products', 'UPDATE prod_orders', 'INSERT INTO prod_products',
                           'DELETE FROM prod_products', 'INSERT INTO prod_logistics_log',
                           'INSERT INTO prod_packages', 'INSERT INTO prod_route_stops'))


def id_zapisow_pozycji(lista):
    """
    Id pozycji z kolejnych UPDATE-ów `prod_products` (`… WHERE prod_products.id = ?`, id to ostatni parametr),
    w kolejności wykonania — czyli w kolejności blokad X na pozycjach. Zapis wsadowy (executemany) rozwijamy
    wiersz po wierszu, w kolejności parametrów: tak wykonuje go też PyMySQL (UPDATE jeden po drugim).
    """
    ids = []
    for sql, parametry in lista:
        if not (isinstance(sql, str) and sql.startswith('UPDATE prod_products')
                and sql.endswith('WHERE prod_products.id = ?')):
            continue
        wiersze = parametry if parametry and isinstance(parametry[0], (list, tuple)) else [parametry]
        ids.extend(wiersz[-1] for wiersz in wiersze)
    return ids


def dodaj_pozycje_za_plecami(order_id, sekwencja, status='czeka_na_wyciecie'):
    """Cudzy zapis po migawce: pozycja zamówienia wstawiona surowym INSERT-em, poza ORM — sesja o niej nie wie
    (kolekcja `order.products` już wczytana jej nie ma). Zwraca id nowej pozycji."""
    wynik = db.session.execute(ProductionProduct.__table__.insert().values(
        order_id=order_id, short_product_id='%d_%d' % (order_id, sekwencja), product_sequence_in_order=sekwencja,
        original_product_name='Blat dębowy 100x60x4', quantity=1, current_status=status))
    return wynik.inserted_primary_key[0]
