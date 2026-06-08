"""Testy flagi blokady parsowania w podglądzie synchronizacji (fetch_orders_preview).

Pozycje usługowe (np. "Docięcie do wymiaru - usługa...") nie mają wymiarów i nie
powinny blokować całego zamówienia w modalu jako "Błąd parsowania".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.routers.api.sync_api import order_has_blocking_parsing_error


def _product(name, has_parsing_error, already_in_db=False, is_service_item=False):
    return {
        'name': name,
        'has_parsing_error': has_parsing_error,
        'already_in_db': already_in_db,
        'is_service_item': is_service_item,
    }


def test_pozycja_uslugowa_nie_blokuje_zamowienia():
    produkty = [
        _product('Blat dębowy 120x80x4', has_parsing_error=False),
        _product('Docięcie do wymiaru - usługa cięcia', has_parsing_error=True, is_service_item=True),
    ]
    assert order_has_blocking_parsing_error(produkty) is False


def test_zamowienie_tylko_uslugowe_nie_blokuje():
    produkty = [_product('usługa cięcia', has_parsing_error=True, is_service_item=True)]
    assert order_has_blocking_parsing_error(produkty) is False


def test_realny_produkt_z_bledem_blokuje():
    produkty = [_product('Jakiś nieparsowalny produkt', has_parsing_error=True)]
    assert order_has_blocking_parsing_error(produkty) is True


def test_produkt_juz_w_bazie_nie_blokuje():
    produkty = [_product('Produkt z błędem', has_parsing_error=True, already_in_db=True)]
    assert order_has_blocking_parsing_error(produkty) is False


def test_realny_blad_blokuje_mimo_uslugi():
    produkty = [
        _product('Docięcie - usługa', has_parsing_error=True, is_service_item=True),
        _product('Blat z nierozpoznaną klasą', has_parsing_error=True),
    ]
    assert order_has_blocking_parsing_error(produkty) is True


def test_wszystko_ok_nie_blokuje():
    produkty = [_product('Blat dębowy 120x80x4 A/B lity olejowany', has_parsing_error=False)]
    assert order_has_blocking_parsing_error(produkty) is False
