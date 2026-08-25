# -*- coding: utf-8 -*-
"""
Generator numerów zleceń trakowania: TRK/RRRR/NNN.

Rok brany z daty UTWORZENIA zlecenia, nie z daty dostawy. Numer jest
identyfikatorem wewnętrznym nadawanym w chwili zakładania zlecenia —
wiązanie go z datą dostawy sprawiłoby, że grudniowa dostawa wprowadzona
w styczniu dostaje numer z poprzedniego rocznika, wpadając między numery
już wydane. Chronologia nadawania ma być monotoniczna.
"""

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.models import get_local_now
from modules.production.sawmill.models import SawmillCounter

NUMBER_PREFIX = 'TRK'


def _select_counter_for_update(year):
    """Blokujący SELECT wiersza licznika dla danego roku (lub None, gdy brak)."""
    return (
        db.session.query(SawmillCounter)
        .filter(SawmillCounter.year == year)
        .with_for_update()
        .first()
    )


def next_order_number(year=None):
    """
    Rezerwuje kolejny numer w danym roku i zwraca go jako string.

    NIE commituje — wywołujący robi commit razem z insertem zlecenia,
    żeby przy wycofaniu transakcji numer nie przepadł.
    """
    if year is None:
        # get_local_now, nie datetime.now: kontener chodzi na UTC — zlecenie
        # założone 31.12 wieczorem czasu lokalnego dostałoby numer z
        # kolejnego rocznika (UTC już po północy), zanim jeszcze lokalnie
        # wybiła północ.
        year = get_local_now().year

    counter = _select_counter_for_update(year)

    if counter is None:
        # Wiersz na nowy rok zakładany leniwie, przy pierwszym zleceniu.
        # `SELECT ... FOR UPDATE` na nieistniejącym kluczu nie daje blokady
        # wyłącznej (blokada luki), więc dwie równoległe transakcje mogą
        # obie zobaczyć None i obie spróbować wstawić ten sam wiersz —
        # druga dostanie IntegrityError na duplikacie klucza głównego.
        # SAVEPOINT (begin_nested) pozwala złapać ten wyjątek bez psucia
        # transakcji wywołującego (tam ląduje też insert zlecenia, dla
        # którego numer jest generowany) — ten sam wzorzec co przy
        # nadawaniu sequence_no kłodom.
        try:
            with db.session.begin_nested():
                counter = SawmillCounter(year=year, last_number=1)
                db.session.add(counter)
                db.session.flush()
        except IntegrityError:
            # Konkurent zdążył wstawić wiersz pierwszy — pobierz go
            # (blokująco), zamiast wywalać cały request.
            counter = _select_counter_for_update(year)
            counter.last_number += 1
            db.session.flush()
    else:
        counter.last_number += 1
        db.session.flush()

    # Pad do 3 cyfr, ale powyżej 999 numer rośnie naturalnie (TRK/2026/1000).
    return '{}/{}/{:03d}'.format(NUMBER_PREFIX, year, counter.last_number)
