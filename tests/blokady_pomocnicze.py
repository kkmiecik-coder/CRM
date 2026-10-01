# -*- coding: utf-8 -*-
"""
Pomocnik testów kolejności blokad („zamówienie najpierw”, logistyka etap 4, krok 4.4a).

SQLite pomija FOR UPDATE, więc kolejności blokad pilnujemy na kolejności samych zapytań (jak
tests/test_produkty_masowa_zmiana_statusu.py): blokada zamówień to zawsze `WHERE prod_orders.id IN (…)
ORDER BY prod_orders.id`, blokada pozycji — wszystkie pozycje jednego zamówienia po `order_id`,
`WHERE prod_products.order_id = ? ORDER BY prod_products.id` (parametr: id zamówienia;
modules/production/services/blokady_zamowien.py), a zapis — pierwszy UPDATE albo INSERT zamówienia lub pozycji.
Leniwe wczytanie `order.products` ma odwrotny warunek (`WHERE ? = prod_products.order_id`) i nie ma ORDER BY,
więc predykat go nie łapie.
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
        self.lista.append((' '.join(statement.split()), parameters))

    def pierwsze(self, warunek):
        """Indeks pierwszego zapytania spełniającego `warunek(sql)`; brak → StopIteration (test pada)."""
        return next(i for i, (sql, _parametry) in enumerate(self.lista) if warunek(sql))


def blokada_zamowien(sql):
    return (sql.startswith('SELECT') and 'FROM prod_orders' in sql and 'WHERE prod_orders.id IN' in sql
            and 'ORDER BY prod_orders.id' in sql)


def blokada_pozycji(sql):
    return (sql.startswith('SELECT') and 'FROM prod_products' in sql and 'WHERE prod_products.order_id = ?' in sql
            and 'ORDER BY prod_products.id' in sql)


def zapis(sql):
    return sql.startswith(('UPDATE prod_products', 'UPDATE prod_orders', 'INSERT INTO prod_products',
                           'DELETE FROM prod_products'))


def dodaj_pozycje_za_plecami(order_id, sekwencja, status='czeka_na_wyciecie'):
    """Cudzy zapis po migawce: pozycja zamówienia wstawiona surowym INSERT-em, poza ORM — sesja o niej nie wie
    (kolekcja `order.products` już wczytana jej nie ma). Zwraca id nowej pozycji."""
    wynik = db.session.execute(ProductionProduct.__table__.insert().values(
        order_id=order_id, short_product_id='%d_%d' % (order_id, sekwencja), product_sequence_in_order=sekwencja,
        original_product_name='Blat dębowy 100x60x4', quantity=1, current_status=status))
    return wynik.inserted_primary_key[0]
