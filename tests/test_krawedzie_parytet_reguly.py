# -*- coding: utf-8 -*-
"""
Parytet dwóch kopii reguły routingu Krawędzi.

Reguła „czy produkt wchodzi na Krawędzie" żyje w repozytorium DWA RAZY:

  1. ProductionProduct.should_skip_edges + complete_task  (modules/production/models.py)
  2. order_timeline_service._should_skip_edges + product_in_route

Kopia druga karmi modal wyceny, kopia pierwsza prowadzi fizyczne sztuki przez
halę. Rozjazd nie daje wyjątku — daje kropkę w modalu, której produkt nigdy
nie odwiedzi (albo brak kropki przy stanowisku, na którym stoi). Dlatego jest
tu osobny strażnik.

Ten plik NIE ma fixture'u bazy i NIE flushuje niczego: complete_task na obiekcie
transient (id is None, order is None) nie tworzy eventu i nie dotyka sesji
SQLAlchemy — zweryfikowane empirycznie.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.

Import User/Multiplier/Client/quotes jest mimo to OBOWIĄZKOWY: bez nich
konfiguracja mapperów pada na InvalidRequestError „expression 'User' failed to
locate a name" już przy pierwszym ProductionProduct(...).
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.models import ProductionProduct
from modules.production.services import order_timeline_service as ots
from modules.users.models import User  # noqa: F401
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

# Wartości faktycznie występujące w prod_products.parsed_finish_type plus
# 'bejcowane'. Ta ostatnia w danych produkcyjnych NIE występuje, ale kwietniowy
# projekt ją wymieniał, a kod (models.complete_task i order_timeline_service)
# sprawdza wyłącznie ('olejowane', 'lakierowane'). Obie kopie są w tym zgodnie
# niekompletne, więc parytet zachodzi — a gdy ktoś rozszerzy JEDNĄ z nich,
# te testy się zapalą. Rozszerzenie warunku to osobne zadanie (sekcja 4
# specyfikacji, luka nr 1).
WYKONCZENIA = ('surowe', 'olejowane', 'lakierowane', 'bejcowane')


def _produkt(finish, edge, cut_to_size=True, status='czeka_na_formatowanie'):
    return ProductionProduct(
        quantity=1,
        current_status=status,
        parsed_finish_type=finish,
        parsed_edge_processing=edge,
        cut_to_size=cut_to_size)


def test_obie_kopie_reguly_daja_ten_sam_wynik():
    for finish, edge, cut in itertools.product(WYKONCZENIA, (True, False), (True, False)):
        produkt = _produkt(finish, edge, cut_to_size=cut)
        assert produkt.should_skip_edges() == ots._should_skip_edges(produkt), (
            finish, edge, cut)


def test_status_po_formatowaniu_zgadza_sie_z_kropka_krawedzi():
    """
    Model decyduje, DOKĄD produkt jedzie z formatowania; timeline decyduje,
    CZY kropka Krawędzi w ogóle się pojawia. Te dwie odpowiedzi muszą być
    tą samą odpowiedzią.
    """
    for finish, edge in itertools.product(WYKONCZENIA, (True, False)):
        produkt = _produkt(finish, edge)
        produkt.complete_task('formatting')
        stoi_na_krawedziach = produkt.current_status == 'czeka_na_krawedzie'
        assert stoi_na_krawedziach is ots.product_in_route(produkt, 'edges'), (
            finish, edge, produkt.current_status)


def test_kropka_lakierni_zgadza_sie_z_wyjsciem_z_krawedzi():
    for finish in WYKONCZENIA:
        produkt = _produkt(finish, edge=True, status='czeka_na_krawedzie')
        produkt.complete_task('edges')
        idzie_do_lakierni = produkt.current_status == 'czeka_na_lakiernie'
        assert idzie_do_lakierni is ots.product_in_route(produkt, 'painting'), (
            finish, produkt.current_status)


def test_skrot_bez_dociecia_zgadza_sie_w_obu_kopiach():
    """cut_to_size=False zamyka formatowanie i Krawędzie w modelu, a w timeline
    ukrywa obie kropki."""
    for finish, edge in itertools.product(WYKONCZENIA, (True, False)):
        produkt = _produkt(finish, edge, cut_to_size=False,
                           status='czeka_na_sklejanie')
        produkt.complete_task('gluing')
        assert produkt.current_status == 'czeka_na_pakowanie', (finish, edge)
        assert ots.product_in_route(produkt, 'formatting') is False
        assert ots.product_in_route(produkt, 'edges') is False
        assert ots.product_in_route(produkt, 'painting') is False


def test_bejcowane_omija_lakiernie_w_obu_kopiach_jednakowo():
    """
    Strażnik znanej luki: dopóki kod zna tylko olej i lakier, produkt bejcowany
    ominie Lakiernię — ale ma ją ominąć TAK SAMO w modelu i na linii czasu.
    Gdy ktoś rozszerzy jedną kopię, ten test się zapali.
    """
    produkt = _produkt('bejcowane', edge=True, status='czeka_na_krawedzie')
    produkt.complete_task('edges')
    assert produkt.current_status == 'czeka_na_pakowanie'
    assert ots.product_in_route(produkt, 'painting') is False
