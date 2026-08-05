# -*- coding: utf-8 -*-
"""
Generator numerów zleceń trakowania: TRK/RRRR/NNN.

Rok brany z daty UTWORZENIA zlecenia, nie z daty dostawy. Numer jest
identyfikatorem wewnętrznym nadawanym w chwili zakładania zlecenia —
wiązanie go z datą dostawy sprawiłoby, że grudniowa dostawa wprowadzona
w styczniu dostaje numer z poprzedniego rocznika, wpadając między numery
już wydane. Chronologia nadawania ma być monotoniczna.
"""

from datetime import datetime

from extensions import db
from modules.production.sawmill.models import SawmillCounter

NUMBER_PREFIX = 'TRK'


def next_order_number(year=None):
    """
    Rezerwuje kolejny numer w danym roku i zwraca go jako string.

    NIE commituje — wywołujący robi commit razem z insertem zlecenia,
    żeby przy wycofaniu transakcji numer nie przepadł.
    """
    if year is None:
        year = datetime.now().year

    counter = (
        db.session.query(SawmillCounter)
        .filter(SawmillCounter.year == year)
        .with_for_update()
        .first()
    )

    if counter is None:
        # Wiersz na nowy rok zakładany leniwie, przy pierwszym zleceniu.
        counter = SawmillCounter(year=year, last_number=0)
        db.session.add(counter)
        db.session.flush()

    counter.last_number += 1
    db.session.flush()

    # Pad do 3 cyfr, ale powyżej 999 numer rośnie naturalnie (TRK/2026/1000).
    return '{}/{}/{:03d}'.format(NUMBER_PREFIX, year, counter.last_number)
