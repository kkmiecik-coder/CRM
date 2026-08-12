# -*- coding: utf-8 -*-
"""
Wspólne narzędzia testów.

ZAMRAŻANIE ZEGARA (`zegar`)
===========================

Testy, które budują dane względem „teraz" (sesja sprzed sześciu godzin, zmiana
od 8:00), są zależne od PORY URUCHOMIENIA pakietu: uruchomione po nocnym
cutoffie albo przed poranną zmianą przechodzą przez zupełnie inne gałęzie kodu
niż w środku dnia. Taki test nie jest sitem — jest ruletką, która milczy
w godzinach pracy i odpala się dopiero na produkcji.

Fixture podmienia klasę `datetime` w module modules.production.models, czyli
dokładnie tę, z której get_local_now() bierze bieżącą chwilę. Wszystkie moduły
wołają tę jedną funkcję (importują ją po nazwie, ale ciało i tak sięga do
globalsów models), więc jedna podmiana zamraża czas w całej aplikacji — także
w serwisach i routerach wołanych przez test_client.

Podmieniamy klasę, a nie samą funkcję, bo `from ..models import get_local_now`
wiąże OBIEKT funkcji w kilkunastu modułach — podmiana atrybutu models nie
dosięgłaby żadnego z nich.
"""

from datetime import datetime, time

import pytest


class _ZamrozonyDatetime(datetime):
    """datetime z zatrzymanym now(); reszta zachowania bez zmian."""

    _chwila = None

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._chwila
        # pytz oczekuje naiwnej chwili — get_local_now() zaraz i tak zdejmie
        # tzinfo, ale przechodzimy tą samą drogą co produkcja.
        return tz.localize(cls._chwila)


@pytest.fixture()
def zegar(monkeypatch):
    """
    Zamraża czas lokalny aplikacji. Zwraca funkcję ustawiającą chwilę:

        chwila = zegar()                       # dziś o 12:00
        chwila = zegar(godzina=6, minuta=30)   # dziś o 6:30
        chwila = zegar(datetime(2026, 8, 11, 23, 55))

    Domyślne 12:00 to środek zmiany: daleko od nocnego cutoffu (23:00) i od
    granicy doby, więc test operujący godzinami wstecz i w przód nie wypada
    poza dobę.
    """
    from modules.production import models

    def ustaw(chwila=None, godzina=12, minuta=0):
        if chwila is None:
            chwila = datetime.combine(models.get_local_now().date(),
                                      time(godzina, minuta))
        monkeypatch.setattr(
            models, 'datetime',
            type('ZegarTestowy', (_ZamrozonyDatetime,), {'_chwila': chwila}))
        return chwila

    return ustaw
