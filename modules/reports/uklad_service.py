# -*- coding: utf-8 -*-
"""Odczyt i zapis prywatnego układu pulpitu Analizy sprzedażowej.

JEDYNE miejsce w kodzie, które dotyka tabeli `reports_dashboard_layouts`.
Trasa i serwis danych rozmawiają z układem wyłącznie przez te trzy funkcje,
więc reguła „brak wiersza to układ domyślny, pusty wiersz to pusty pulpit"
jest zapisana raz.
"""

from typing import List, Optional, Sequence, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from extensions import db
from modules.reports.models_uklad import UkladDashboardu
from modules.reports.uklad import (
    UKLAD_DOMYSLNY, Instancja, uklad_do_json, uklad_z_bazy,
)


def _wiersz(user) -> Optional[UkladDashboardu]:
    return UkladDashboardu.query.filter_by(user_id=user.id).first()


def uklad_uzytkownika(user) -> Tuple[List[Instancja], int]:
    """(kafelki, liczba pominiętych) dla tego użytkownika.

    BRAK WIERSZA ≠ PUSTY UKŁAD. Brak wiersza znaczy „nigdy nie dotykał trybu
    edycji" i daje układ domyślny. Wiersz z pustą listą znaczy „usunął
    wszystkie kafelki" i daje pusty pulpit ze stanem pustym. Gdyby te dwa
    stany dawały to samo, nie dałoby się usunąć ostatniego kafelka — pulpit
    sam by się odtwarzał.

    `user=None` (teoretycznie niemożliwe, bo dekorator sprawdza sesję wcześniej)
    daje układ domyślny, a nie wyjątek: lepiej pokazać pulpit niż stronę błędu.
    """
    if user is None:
        return list(UKLAD_DOMYSLNY), 0
    wiersz = _wiersz(user)
    if wiersz is None:
        return list(UKLAD_DOMYSLNY), 0
    return uklad_z_bazy(wiersz.uklad)


def zapisz_uklad(user, uklad: Sequence[Instancja]) -> None:
    """Zapisuje układ tego użytkownika. Wołający MUSI go wcześniej zwalidować
    przez `uklad.parsuj_uklad` — ta funkcja niczego nie sprawdza.

    RÓWNOLEGŁOŚĆ. Dwie karty przeglądarki tego samego użytkownika mogą zapisać
    naraz; wygrywa ostatni zapis i tak ma być — to prywatna preferencja
    interfejsu, nie dane księgowe, a straż optymistyczna wymagałaby pokazania
    użytkownikowi konfliktu, którego on sam ze sobą nie ma jak rozstrzygnąć.
    Wyścig przy PIERWSZYM zapisie (dwa INSERT-y naraz) łapie UNIQUE(user_id)
    i obsługujemy go wprost, żeby użytkownik nie zobaczył 500.

    Drugi wyścig (przegląd gałęzi, D1): „Przywróć domyślny" w drugiej karcie
    kasuje wiersz między naszym odczytem a UPDATE-em. UPDATE trafia wtedy
    w zero wierszy i SQLAlchemy rzuca StaleDataError (zmierzone na MySQL 8.4,
    pymysql liczy dopasowane wiersze). Ta sama reguła „wygrywa ostatni zapis":
    wiersz powstaje od nowa. Jedna ponowna próba, bez pętli.
    """
    surowe = uklad_do_json(uklad)
    wiersz = _wiersz(user)
    if wiersz is not None:
        wiersz.uklad = surowe
        try:
            db.session.commit()
            return
        except StaleDataError:
            db.session.rollback()
    _wstaw(user, surowe)


def _wstaw(user, surowe) -> None:
    """INSERT wiersza układu, z obsługą wyścigu dwóch pierwszych zapisów."""
    db.session.add(UkladDashboardu(user_id=user.id, uklad=surowe))
    try:
        db.session.commit()
    except IntegrityError:
        # Ktoś (druga karta przeglądarki) wstawił wiersz między naszym
        # odczytem a zapisem. Wracamy po niego i nadpisujemy.
        db.session.rollback()
        wiersz = _wiersz(user)
        if wiersz is None:
            raise
        wiersz.uklad = surowe
        db.session.commit()


def przywroc_domyslny(user) -> bool:
    """Kasuje wiersz układu. Zwraca True, gdy było co kasować.

    KASUJEMY, a nie zapisujemy w wierszu dzisiejszej listy domyślnej. Dzięki
    temu przyszła zmiana układu domyślnego dosięgnie też ludzi, którzy kiedyś
    kliknęli „Przywróć domyślny" — a zapisana kopia zamroziłaby im układ
    z dnia kliknięcia.
    """
    wiersz = _wiersz(user)
    if wiersz is None:
        return False
    db.session.delete(wiersz)
    db.session.commit()
    return True
