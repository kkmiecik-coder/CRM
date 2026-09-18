# -*- coding: utf-8 -*-
"""
Kolejka synchronizacji statusów BaseLinkera w okresie przejściowym Krawędzi.

Kolejka deduplikuje po krotce (numer_zamówienia, kod_stanowiska). Dopóki tablety
meldują jeszcze stary kod 'finishing', ten sam numer może wpaść do niej dwa razy
- raz jako 'finishing', raz jako 'edges' - i BaseLinker dostanie dwa
setOrderStatus pod rząd. Alias rozwijamy więc na WEJŚCIU, tak jak w API mobilnym.

Testy nie potrzebują bazy: schedule_after_station_complete operuje wyłącznie
na flask.g, które żyje w kontekście aplikacji. Ten plik nie zakłada tabeli
prod_product_events, bo nie robi tego żaden inny plik w pakiecie — listener
audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask, g

from modules.production.services import baselinker_status_sync as bl


@pytest.fixture()
def app():
    aplikacja = Flask(__name__)
    with aplikacja.app_context():
        yield aplikacja


def test_alias_finishing_trafia_do_kolejki_jako_edges(app):
    """Stary tablet melduje 'finishing' — w kolejce ma stanąć kod kanoniczny."""
    bl.schedule_after_station_complete('26/00044', 'finishing')

    assert g.pending_baselinker_syncs == [('26/00044', 'edges')]


def test_alias_i_kod_kanoniczny_nie_dubluja_wpisu(app):
    """
    Dwa tablety tej samej brygady — jeden przed aktualizacją, jeden po niej —
    domykają pozycje tego samego zamówienia. Bez normalizacji na wejściu
    deduplikacja po krotce nie zadziała i BaseLinker dostanie dwa setOrderStatus.
    """
    bl.schedule_after_station_complete('26/00044', 'finishing')
    bl.schedule_after_station_complete('26/00044', 'edges')

    assert g.pending_baselinker_syncs == [('26/00044', 'edges')]


def test_stanowiska_z_srodka_linii_nadal_nie_trafiaja_do_kolejki(app):
    """Wycinanie nie kończy produkcji — guard ma je dalej odrzucać."""
    bl.schedule_after_station_complete('26/00044', 'cutting')

    assert getattr(g, 'pending_baselinker_syncs', []) == []


def test_krawedzie_i_lakiernia_koncza_produkcje():
    """Strażnik Zadania 1 — zielony od chwili dopisania 'edges' do zbioru."""
    assert {'edges', 'painting'} <= bl.PRODUCTION_STATIONS


def test_kolejki_krawedzi_i_lakierni_nie_zamykaja_produkcji_przedwczesnie():
    """
    POSTPROD_STATUSES odpowiada na pytanie „czy produkcja tej pozycji się
    skończyła". Dopisanie tam statusu kolejki zamknęłoby produkcję w BL,
    zanim ktokolwiek tknie sztukę na stanowisku.
    """
    assert 'czeka_na_krawedzie' not in bl.POSTPROD_STATUSES
    assert 'czeka_na_lakiernie' not in bl.POSTPROD_STATUSES


def test_alias_nie_wplywa_na_stanowisko_pakowania(app):
    """
    Wzmocnienie: 'packaging' NIE jest w PRODUCTION_STATIONS (ma osobną gałąź
    w schedule_after_station_complete), a resolve_station_code('packaging')
    jest bezpieczną tożsamością — sam fakt wołania resolve_station_code na
    wejściu nie może wybić 'packaging' poza dozwoloną ścieżkę ani zmienić
    jego nazwy.
    """
    bl.schedule_after_station_complete('26/00044', 'packaging')

    assert g.pending_baselinker_syncs == [('26/00044', 'packaging')]


def test_kod_nieznany_spoza_aliasow_przechodzi_bez_zmian_i_jest_odrzucany(app):
    """
    Wzmocnienie: resolve_station_code zwraca nieznane stringi bez zmian
    (mapuje tylko klucze zarejestrowane w STATION_CODE_ALIASES). Kod, którego
    nikt nie zaalias'ował, ma zostać odrzucony przez guard tak samo jak dziś,
    a nie np. rzucić wyjątkiem albo zostać cicho przepuszczony.
    """
    bl.schedule_after_station_complete('26/00044', 'nieistniejace_stanowisko')

    assert getattr(g, 'pending_baselinker_syncs', []) == []
