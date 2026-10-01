# -*- coding: utf-8 -*-
"""
Pomocnik testów kolejności blokad („zamówienie najpierw”, logistyka etap 4, krok 4.4a).

SQLite pomija FOR UPDATE, więc kolejności blokad pilnujemy na kolejności samych zapytań (jak
tests/test_produkty_masowa_zmiana_statusu.py): blokada zamówień to zawsze `WHERE prod_orders.id IN (…)
ORDER BY prod_orders.id`, blokada pozycji — `WHERE prod_products.id IN (…) ORDER BY prod_products.id`
(modules/production/services/blokady_zamowien.py), a zapis — pierwszy UPDATE albo INSERT zamówienia lub pozycji.
"""
from sqlalchemy import event

from extensions import db


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
        self.lista.append((' '.join(statement.split()), parameters))

    def pierwsze(self, warunek):
        """Indeks pierwszego zapytania spełniającego `warunek(sql)`; brak → StopIteration (test pada)."""
        return next(i for i, (sql, _parametry) in enumerate(self.lista) if warunek(sql))


def blokada_zamowien(sql):
    return (sql.startswith('SELECT') and 'FROM prod_orders' in sql and 'WHERE prod_orders.id IN' in sql
            and 'ORDER BY prod_orders.id' in sql)


def blokada_pozycji(sql):
    return (sql.startswith('SELECT') and 'FROM prod_products' in sql and 'WHERE prod_products.id IN' in sql
            and 'ORDER BY prod_products.id' in sql)


def zapis(sql):
    return sql.startswith(('UPDATE prod_products', 'UPDATE prod_orders', 'INSERT INTO prod_products',
                           'DELETE FROM prod_products'))
