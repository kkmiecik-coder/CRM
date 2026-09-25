# -*- coding: utf-8 -*-
"""Flota pojazdów i lista kierowców (pracownicy produkcji) — spec 8.1."""
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics.models import Route, RouteStop, STATUSY_TRASY_AKTYWNE, Vehicle
from modules.production.logistics.services import delivery
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker, get_local_now

MAKS_LADOWNOSC_KG = 100000


def serializuj_pojazd(v):
    return {'id': v.id, 'name': v.name, 'registration': v.registration,
            'capacity_kg': v.capacity_kg, 'is_active': bool(v.is_active)}


def lista_pojazdow(tylko_aktywne=False):
    zapytanie = Vehicle.query
    if tylko_aktywne:
        zapytanie = zapytanie.filter(Vehicle.is_active.is_(True))
    return [serializuj_pojazd(v) for v in zapytanie.order_by(Vehicle.name).all()]


def zapisz_pojazd(dane, pojazd=None):
    nazwa = (dane.get('name') or '').strip()
    if not nazwa or len(nazwa) > 100:
        raise LogistykaBlad(u'Podaj nazwę pojazdu (do 100 znaków).', status=422)
    rejestracja = ' '.join((dane.get('registration') or '').upper().split()) or None
    if rejestracja and len(rejestracja) > 20:
        raise LogistykaBlad(u'Numer rejestracyjny może mieć najwyżej 20 znaków.', status=422)
    ladownosc = dane.get('capacity_kg')
    if ladownosc in (None, ''):
        ladownosc = None
    else:
        try:
            ladownosc = int(ladownosc)
        except (TypeError, ValueError):
            raise LogistykaBlad(u'Ładowność podaj w pełnych kilogramach.', status=422)
        if not 0 < ladownosc <= MAKS_LADOWNOSC_KG:
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
