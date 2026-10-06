# -*- coding: utf-8 -*-
"""
Wspólne pomocniki testów priorytetów produkcji (program P1, 2026-10). Zwykły moduł pomocniczy, NIE conftest —
konwencja tests/logistyka_fixtures.py i tests/krawedzie_fixtures.py. Importuj w pliku testów:

    from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, ustaw, zamrozony_dzien  # noqa: F401

Aplikację i tabele daje fixtura `app` z logistyka_fixtures albo krawedzie_fixtures (obie zakładają tabele pakietu
`priorytety`). Ten moduł nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
from datetime import date

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityRung
from modules.production.priorytety.services import kolejka
from modules.production.services import config_service

# „Dziś” przeliczenia rang zamrożone na poniedziałek 5.10.2026: terminy wpisane w testach (październik–listopad
# 2026) nie mogą z czasem zacząć łapać tagów „Po terminie” i „Blisko terminu”.
DZIS = date(2026, 10, 5)


def drabina_domyslna():
    """Dziewięć szczebli stałych jak seed migracji (spec 3.1), `position` 1..9. Commituje. Zwraca wiersze."""
    szczeble = []
    for pozycja, (rodzaj, wartosc) in enumerate(stale.DRABINA_DOMYSLNA, start=1):
        szczeble.append(PriorityRung(
            kind=rodzaj,
            stars=wartosc if rodzaj == 'stars' else None,
            tag=wartosc if rodzaj == 'tag' else None,
            position=pozycja))
    db.session.add_all(szczeble)
    db.session.commit()
    return szczeble


@pytest.fixture()
def zamrozony_dzien(monkeypatch):
    """`kolejka.dzis()` (data, od której `utrwal` liczy tagi terminowe) = DZIS."""
    monkeypatch.setattr(kolejka, 'dzis', lambda: DZIS)
    return DZIS


@pytest.fixture()
def czyste_ustawienia():
    """Singleton `config_service` trzyma wartości 60 minut na proces — bez czyszczenia test widziałby ustawienie
    poprzedniego testu. Czyścimy przed i po."""
    config_service.invalidate_config_cache()
    yield
    config_service.invalidate_config_cache()


def ustaw(klucz, wartosc, typ='string'):
    """Wiersz `prod_config` (nowy albo nadpisany) + unieważnienie pamięci podręcznej. Commituje."""
    wiersz = ProductionConfig.query.filter_by(config_key=klucz).first()
    if wiersz is None:
        wiersz = ProductionConfig(config_key=klucz, config_value=str(wartosc), config_type=typ)
        db.session.add(wiersz)
    else:
        wiersz.config_value = str(wartosc)
        wiersz.config_type = typ
    db.session.commit()
    config_service.invalidate_config_cache()
    return wiersz


@pytest.fixture()
def szpieg_utrwal(app, monkeypatch):
    """
    Licznik wywołań `kolejka.utrwal`: woła oryginał i notuje raport oraz to, czy wywołanie padło „po commicie”
    (`czysta`): `db.session` nie ma obiektów czekających na zapis ORAZ od ostatniego commitu albo rollbacku nie
    poszedł do bazy żaden zapis. Samo `db.session.new/dirty/deleted` nie wystarcza — po `flush()` są puste,
    a transakcja z zapisem dalej jest otwarta; na MySQL `utrwal` czekałoby wtedy na własne blokady (warunek wstępny
    w `kolejka.py`), czego SQLite testów nie pokaże.

    Zapisy liczymy na silniku (INSERT/UPDATE/DELETE, zerowane przy commicie i rollbacku połączenia). Własna sesja
    `utrwal` zaczyna pisać dopiero po zanotowaniu wpisu, więc w chwili wywołania licznik widzi wyłącznie pracę
    wołającego.

    Czyści plan przeliczenia w `g` przed i po teście: fikstura `app` trzyma jeden kontekst aplikacji, więc `g` jest
    wspólne dla wszystkich żądań testu.
    """
    from flask import g

    wywolania = []
    oryginal = kolejka.utrwal
    niezatwierdzone = [0]

    def przed_zapytaniem(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            niezatwierdzone[0] += 1

    def koniec_transakcji(conn):
        niezatwierdzone[0] = 0

    def utrwal(*args, **kwargs):
        wpis = {'czysta': (not (db.session.new or db.session.dirty or db.session.deleted)
                           and niezatwierdzone[0] == 0),
                'zrodlo': kwargs.get('zrodlo'), 'raport': None}
        wywolania.append(wpis)
        wpis['raport'] = oryginal(*args, **kwargs)
        return wpis['raport']

    silnik = db.engine
    event.listen(silnik, 'before_cursor_execute', przed_zapytaniem)
    event.listen(silnik, 'commit', koniec_transakcji)
    event.listen(silnik, 'rollback', koniec_transakcji)
    monkeypatch.setattr(kolejka, 'utrwal', utrwal)
    g.pop(kolejka._PLAN_W_G, None)
    yield wywolania
    g.pop(kolejka._PLAN_W_G, None)
    event.remove(silnik, 'before_cursor_execute', przed_zapytaniem)
    event.remove(silnik, 'commit', koniec_transakcji)
    event.remove(silnik, 'rollback', koniec_transakcji)
