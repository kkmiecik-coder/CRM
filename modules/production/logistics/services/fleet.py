# -*- coding: utf-8 -*-
"""Flota pojazdów i lista kierowców (pracownicy produkcji) — spec 8.1."""
import re

from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics.models import Route, RouteStop, STATUSY_TRASY_AKTYWNE, Vehicle
from modules.production.logistics.services import delivery
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker, get_local_now

MAKS_LADOWNOSC_KG = 100000
# (fix-2, Minor 3 residual) Jak routes._ID_RE: cyfry ASCII, 1-9 znaków —
# `str.isdigit()` przepuszcza też np. „²”/„①”, na których goły `int()` rzuca
# ValueError (500) zamiast czytelnego 422.
_ID_RE = re.compile(r'[0-9]{1,9}')


def serializuj_pojazd(v):
    return {'id': v.id, 'name': v.name, 'registration': v.registration,
            'capacity_kg': v.capacity_kg, 'is_active': bool(v.is_active)}


def lista_pojazdow(tylko_aktywne=False):
    zapytanie = Vehicle.query
    if tylko_aktywne:
        zapytanie = zapytanie.filter(Vehicle.is_active.is_(True))
    return [serializuj_pojazd(v) for v in zapytanie.order_by(Vehicle.name).all()]


def zapisz_pojazd(dane, pojazd=None):
    # (fix-1, Ruling C) `name`/`registration` spoza `str` (np. {"name": 5} z JSON API
    # etapu 6) rzucałyby AttributeError na .strip()/.upper() gołego inta — 500
    # zamiast czytelnej odmowy.
    nazwa_surowa = dane.get('name')
    if not isinstance(nazwa_surowa, str):
        raise LogistykaBlad(u'Podaj nazwę pojazdu (do 100 znaków).', status=422)
    nazwa = nazwa_surowa.strip()
    if not nazwa or len(nazwa) > 100:
        raise LogistykaBlad(u'Podaj nazwę pojazdu (do 100 znaków).', status=422)
    rejestracja_surowa = dane.get('registration')
    if rejestracja_surowa is not None and not isinstance(rejestracja_surowa, str):
        raise LogistykaBlad(u'Numer rejestracyjny podaj jako tekst.', status=422)
    rejestracja = ' '.join((rejestracja_surowa or '').upper().split()) or None
    if rejestracja and len(rejestracja) > 20:
        raise LogistykaBlad(u'Numer rejestracyjny może mieć najwyżej 20 znaków.', status=422)
    ladownosc = dane.get('capacity_kg')
    # bool jest podklasą int w Pythonie — bez wyłączenia `True` przeszłoby jako 1 kg.
    if isinstance(ladownosc, bool):
        raise LogistykaBlad(u'Ładowność podaj w pełnych kilogramach.', status=422)
    if ladownosc in (None, ''):
        ladownosc = None
    elif isinstance(ladownosc, int):
        pass
    elif isinstance(ladownosc, str) and _ID_RE.fullmatch(ladownosc.strip()):
        ladownosc = int(ladownosc.strip())
    else:
        # Nigdy gołego int()/float() na nieznanym typie — 1e400 (JSON) parsuje się
        # jako inf, a int(inf) rzuca OverflowError zamiast czytelnego 422.
        raise LogistykaBlad(u'Ładowność podaj w pełnych kilogramach.', status=422)
    if ladownosc is not None and not 0 < ladownosc <= MAKS_LADOWNOSC_KG:
        raise LogistykaBlad(u'Ładowność musi być dodatnia.', status=422)

    # Zmiana nazwy ISTNIEJĄCEGO pojazdu (nie nowego) — trzeba podbić pozycje na trasach,
    # zanim nadpiszemy pojazd.name poniżej (inaczej nie mamy już starej wartości).
    zmiana_nazwy = pojazd is not None and pojazd.name != nazwa
    if pojazd is None:
        pojazd = Vehicle(is_active=True)
        db.session.add(pojazd)
    pojazd.name, pojazd.registration, pojazd.capacity_kg = nazwa, rejestracja, ladownosc
    db.session.flush()

    if zmiana_nazwy:
        _podbij_zamowienia_pojazdu(pojazd)

    return pojazd


def _podbij_zamowienia_pojazdu(pojazd):
    """
    Tablet pokazuje `transport.vehicle_name` dla zamówień na aktywnej trasie, a ETag
    jego kolejki liczy się z MAX(updated_at) pozycji — zmiana nazwy pojazdu musi więc
    podbić pozycje wszystkich zamówień na trasach ROBOCZYCH/ZATWIERDZONYCH tego pojazdu
    (spec 6.5). Trasy WYKONANE tabletu już nie interesują. Jedno zapytanie z JOIN-em
    RouteStop → Route, bez zapytania o trasę per zamówienie.
    """
    teraz = get_local_now()
    zamowienia = (ProductionOrder.query
                  .options(selectinload(ProductionOrder.products))
                  .join(RouteStop, RouteStop.order_id == ProductionOrder.id)
                  .join(Route, Route.id == RouteStop.route_id)
                  .filter(Route.vehicle_id == pojazd.id,
                          Route.status.in_(STATUSY_TRASY_AKTYWNE))
                  .all())
    for order in zamowienia:
        delivery.podbij_pozycje(order, teraz)


def ustaw_aktywnosc(pojazd, aktywny):
    pojazd.is_active = bool(aktywny)
    pojazd.deactivated_at = None if aktywny else get_local_now()
    return pojazd


def kierowcy():
    pracownicy = (ProductionWorker.query.filter(ProductionWorker.is_active.is_(True))
                  .order_by(ProductionWorker.sort_order, ProductionWorker.last_name).all())
    return [{'id': p.id, 'nazwa': u'{} {}'.format(p.first_name, p.last_name).strip()}
            for p in pracownicy]
