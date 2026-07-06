"""
Test regresyjny wydajności/poprawnosci FinishingOption.get_flat_list()/get_tree().

Cel: potwierdzić, że po eliminacji N+1 (zapytania per węzeł po relacji
parent/children) wynik jest identyczny co do kluczy i wartości z kontraktem
to_dict(), a liczba zapytań SQL dla drzewka wielopoziomowego wynosi 1
(zamiast O(N)).

Nie używamy pełnego create_app() (zgodnie z konwencją repo - patrz
test_display_monitor_service.py) - budujemy minimalną, izolowaną aplikację
Flask + SQLAlchemy na SQLite in-memory z samą tabelą finishing_options.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy import event

from extensions import db
from modules.calculator.models import FinishingOption

# modules/calculator/models.py definiuje relacje (Quote.client, Quote.quote_status,
# QuoteItem.discount_reason) do modeli z innych modułów. SQLAlchemy konfiguruje
# WSZYSTKIE mappery leniwie przy pierwszym użyciu sesji, więc żeby mapper Quote/
# QuoteItem mógł się poprawnie skonfigurować (inaczej: InvalidRequestError przy
# pierwszym query, nawet dla niepowiązanej tabeli finishing_options), te moduły
# muszą być zaimportowane - ich tabel nie tworzymy ani nie używamy w tym teście.
import modules.clients.models  # noqa: F401
import modules.quotes.models  # noqa: F401


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        # Tworzymy tylko tabelę finishing_options - test ma być izolowany
        # i szybki, bez pełnego create_app() ani innych modeli.
        FinishingOption.__table__.create(db.engine)

        # Drzewko 3-poziomowe z gałęzią nieaktywną i dziedziczeniem ceny/kodu:
        # Lakierowane (id=1, code=LAK, price=100)
        #   Bezbarwne (id=2, price=None -> dziedziczy 100)
        #     Mat (id=3, price=150, aktywne)
        #     Polysk (id=4, price=None -> dziedziczy 100, NIEAKTYWNE)
        # Surowe (id=5, code=SUR, price=0)
        # Wyciecie (id=6, code=None, price=None, brak rodzica -> effective 0, inherited_code None)
        db.session.add_all([
            FinishingOption(id=1, parent_id=None, level=0, name='Lakierowane',
                             code='LAK', price_netto=100, is_active=True, sort_order=0),
            FinishingOption(id=5, parent_id=None, level=0, name='Surowe',
                             code='SUR', price_netto=0, is_active=True, sort_order=1),
            FinishingOption(id=6, parent_id=None, level=0, name='Wyciecie',
                             code=None, price_netto=None, is_active=True, sort_order=2),
        ])
        db.session.commit()
        db.session.add_all([
            FinishingOption(id=2, parent_id=1, level=1, name='Bezbarwne',
                             code=None, price_netto=None, is_active=True, sort_order=0),
        ])
        db.session.commit()
        db.session.add_all([
            FinishingOption(id=3, parent_id=2, level=2, name='Mat',
                             code=None, price_netto=150, is_active=True, sort_order=0),
            FinishingOption(id=4, parent_id=2, level=2, name='Polysk',
                             code=None, price_netto=None, is_active=False, sort_order=1),
        ])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


def _count_queries(fn):
    """Zlicza zapytania SQL wykonane wewnątrz fn() na aktualnym db.engine."""
    counter = {'n': 0}

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter['n'] += 1

    event.listen(db.engine, 'before_cursor_execute', _before_cursor_execute)
    try:
        result = fn()
    finally:
        event.remove(db.engine, 'before_cursor_execute', _before_cursor_execute)
    return result, counter['n']


def test_get_flat_list_jedno_zapytanie_sql(app):
    with app.app_context():
        db.session.expire_all()
        _, n_queries = _count_queries(FinishingOption.get_flat_list)
        assert n_queries == 1, f"Oczekiwano 1 zapytania SQL, wykonano {n_queries}"


def test_get_flat_list_include_inactive_jedno_zapytanie_sql(app):
    with app.app_context():
        db.session.expire_all()
        _, n_queries = _count_queries(lambda: FinishingOption.get_flat_list(include_inactive=True))
        assert n_queries == 1, f"Oczekiwano 1 zapytania SQL, wykonano {n_queries}"


def test_get_tree_jedno_zapytanie_sql(app):
    with app.app_context():
        db.session.expire_all()
        _, n_queries = _count_queries(FinishingOption.get_tree)
        assert n_queries == 1, f"Oczekiwano 1 zapytania SQL, wykonano {n_queries}"


def test_get_flat_list_kontrakt_aktywne(app):
    with app.app_context():
        flat = FinishingOption.get_flat_list()

        # Nieaktywne 'Polysk' (id=4) pominięte.
        ids = [item['id'] for item in flat]
        assert ids == [1, 2, 3, 5, 6]

        by_id = {item['id']: item for item in flat}

        # Dziedziczenie ceny i full_path przez 2 poziomy.
        assert by_id[1]['full_path'] == 'Lakierowane'
        assert by_id[1]['effective_price_netto'] == 100.0
        assert by_id[1]['inherited_code'] == 'LAK'
        assert by_id[1]['depth'] == 0

        assert by_id[2]['full_path'] == 'Lakierowane > Bezbarwne'
        assert by_id[2]['price_netto'] is None
        assert by_id[2]['effective_price_netto'] == 100.0  # dziedziczone z rodzica
        assert by_id[2]['inherited_code'] == 'LAK'  # dziedziczony kod
        assert by_id[2]['depth'] == 1

        assert by_id[3]['full_path'] == 'Lakierowane > Bezbarwne > Mat'
        assert by_id[3]['price_netto'] == 150.0
        assert by_id[3]['effective_price_netto'] == 150.0  # własna cena, nie dziedziczona
        assert by_id[3]['depth'] == 2

        # Korzeń bez kodu i ceny -> effective 0, inherited_code None (brak rodzica).
        assert by_id[6]['effective_price_netto'] == 0.0
        assert by_id[6]['inherited_code'] is None


def test_get_flat_list_include_inactive_zawiera_wszystkie(app):
    with app.app_context():
        flat = FinishingOption.get_flat_list(include_inactive=True)
        ids = sorted(item['id'] for item in flat)
        assert ids == [1, 2, 3, 4, 5, 6]

        by_id = {item['id']: item for item in flat}
        # Nieaktywne 'Polysk' też dziedziczy poprawnie.
        assert by_id[4]['effective_price_netto'] == 100.0
        assert by_id[4]['is_active'] is False


def test_get_tree_kontrakt_zagniezdzone_dzieci(app):
    with app.app_context():
        tree = FinishingOption.get_tree()

        # Tylko aktywne korzenie, posortowane po sort_order.
        root_ids = [root['id'] for root in tree]
        assert root_ids == [1, 5, 6]

        lakierowane = tree[0]
        assert lakierowane['full_path'] == 'Lakierowane'
        assert len(lakierowane['children']) == 1

        bezbarwne = lakierowane['children'][0]
        assert bezbarwne['full_path'] == 'Lakierowane > Bezbarwne'
        assert bezbarwne['effective_price_netto'] == 100.0

        # Nieaktywne dziecko 'Polysk' NIE pojawia się w drzewku (include_children
        # w oryginalnym to_dict() filtruje po is_active).
        child_names = [c['name'] for c in bezbarwne['children']]
        assert child_names == ['Mat']


def test_get_flat_list_i_get_tree_zgodne_co_do_kluczy_z_to_dict(app):
    """
    Kontrakt: klucze zwracane przez get_flat_list()/get_tree() muszą pokrywać
    się z kluczami zwracanymi przez FinishingOption.to_dict() (konsumenci:
    pricing_service._finishing_maps_from_flat_list, get_finishing_prices_data,
    bot_api /options).
    """
    with app.app_context():
        opt = FinishingOption.query.get(3)
        expected_keys = set(opt.to_dict(include_effective_price=True).keys())

        flat = FinishingOption.get_flat_list()
        item = next(i for i in flat if i['id'] == 3)
        flat_keys = set(item.keys()) - {'depth', 'indent'}
        assert flat_keys == expected_keys

        tree = FinishingOption.get_tree()
        root = tree[0]
        tree_keys = set(root.keys()) - {'children'}
        assert tree_keys == expected_keys
