# -*- coding: utf-8 -*-
"""Flota pojazdów i kierowcy tras (pracownicy produkcji ze znacznikiem is_driver) — spec 8.1, runda 2 (2.6)."""
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
    if zmiana_nazwy:
        # (M2) Podbicie zmienia pozycje zamówień z tras — to zapis „trasowy”, więc blokada
        # tras PIERWSZA (zasada routes.zablokuj_trasy), przed zapisem wiersza pojazdu:
        # piszący trasę bierze blokadę, a potem czyta ten pojazd FOR UPDATE
        # (routes._sprawdz_zasoby); my w odwrotnej kolejności (pojazd, potem blokada)
        # zakleszczylibyśmy się z nim. Pod blokadą podbicie nie przeplata się też
        # z odhaczaniem trasy (te same pozycje w innej kolejności — MySQL 1213).
        from modules.production.logistics.services import routes
        routes.zablokuj_trasy()
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
    (spec 6.5). Trasy WYKONANE tabletu już nie interesują.

    (M2) Wołane pod blokadą tras (zapisz_pojazd). Przystanki odczytem BIEŻĄCYM (FOR SHARE):
    zwykły SELECT czytałby migawkę sprzed czekania na blokadę i pominąłby zamówienie dodane
    w tym czasie do trasy z tym pojazdem — tablet zostałby ze starą nazwą (ETag bez zmian).
    Blokujemy tylko przystanki i trasy; zamówienia z pozycjami wczytuje osobne, zwykłe zapytanie.
    """
    teraz = get_local_now()
    ids = [order_id for (order_id,) in
           db.session.query(RouteStop.order_id)
           .join(Route, Route.id == RouteStop.route_id)
           .filter(Route.vehicle_id == pojazd.id, Route.status.in_(STATUSY_TRASY_AKTYWNE))
           .with_for_update(read=True).all()]
    if not ids:
        return
    zamowienia = (ProductionOrder.query
                  .options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids))
                  .all())
    for order in zamowienia:
        delivery.podbij_pozycje(order, teraz)


def ustaw_aktywnosc(pojazd, aktywny):
    pojazd.is_active = bool(aktywny)
    pojazd.deactivated_at = None if aktywny else get_local_now()
    return pojazd


def nazwa_pracownika(p):
    return u'{} {}'.format(p.first_name, p.last_name).strip()


def _pracownicy(kierowca):
    """Aktywni pracownicy produkcji ze znacznikiem kierowcy (True) albo bez niego (False)."""
    return (ProductionWorker.query
            .filter(ProductionWorker.is_active.is_(True), ProductionWorker.is_driver.is_(kierowca))
            .order_by(ProductionWorker.sort_order, ProductionWorker.last_name).all())


def kierowcy():
    """
    (runda 2, spec 2.6) Kierowcy tras: AKTYWNI pracownicy ze znacznikiem is_driver (do rundy 2
    — wszyscy aktywni). Kształt bez zmian, [{id, nazwa}] — używają go GET /drivers
    (przez kierowcy_z_trasami) i routes.dostepnosc (wybór kierowcy w edytorze trasy).
    """
    return [{'id': p.id, 'nazwa': nazwa_pracownika(p)} for p in _pracownicy(True)]


def kandydaci_na_kierowcow():
    """Okno „Dodaj kierowcę” we Flocie: aktywni pracownicy BEZ znacznika."""
    return [{'id': p.id, 'nazwa': nazwa_pracownika(p)} for p in _pracownicy(False)]


def trasy_kierowcow(ids):
    """
    {worker_id: [nazwa trasy, …]} — trasy robocze i zatwierdzone (po dacie od, potem id),
    na których pracownik jest kierowcą. Potwierdzenie zdjęcia znacznika podaje je z nazwy:
    kierowca na nich zostaje (spec 2.6, rozstrzygnięcie 33).
    """
    if not ids:
        return {}
    wynik = {}
    for worker_id, nazwa in (db.session.query(Route.driver_worker_id, Route.name)
                             .filter(Route.driver_worker_id.in_(list(ids)),
                                     Route.status.in_(STATUSY_TRASY_AKTYWNE))
                             .order_by(Route.date_from, Route.id).all()):
        wynik.setdefault(worker_id, []).append(nazwa)
    return wynik


def kierowcy_z_trasami():
    """GET /drivers: kierowcy z nazwami ich aktywnych tras — dwa zapytania na całą listę."""
    lista = kierowcy()
    trasy = trasy_kierowcow([k['id'] for k in lista])
    return [dict(k, trasy=trasy.get(k['id'], [])) for k in lista]


def serializuj_kierowce(p):
    return {'id': p.id, 'nazwa': nazwa_pracownika(p), 'is_driver': bool(p.is_driver),
            'trasy': trasy_kierowcow([p.id]).get(p.id, [])}


def _id_pracownika(wartosc):
    """
    Identyfikator pracownika z ciała żądania: int (nie bool — `True` to w Pythonie 1) albo
    tekst z cyframi ASCII (_ID_RE), zakres 1…999 999 999. Wszystko inne → 422; nigdy gołego
    int() na nieznanym typie (wzór: routes._id).
    """
    liczba = None
    if isinstance(wartosc, int) and not isinstance(wartosc, bool):
        liczba = wartosc
    elif isinstance(wartosc, str) and _ID_RE.fullmatch(wartosc.strip()):
        liczba = int(wartosc.strip())
    if liczba is None or not 0 < liczba < 10 ** 9:
        raise LogistykaBlad(u'Wybierz pracownika z listy.', status=422)
    return liczba


def _pracownik(worker_id):
    pracownik = ProductionWorker.query.get(_id_pracownika(worker_id))
    if pracownik is None:
        raise LogistykaBlad(u'Nie ma takiego pracownika.', status=404)
    return pracownik


def dodaj_kierowce(worker_id):
    """
    (runda 2, spec 2.6) Znacznik kierowcy na aktywnym pracowniku. Idempotentne. 404 — nie ma
    pracownika, 409 — pracownik nieaktywny. To NIE jest zapis trasy: bez routes.zablokuj_trasy();
    trasy sprawdzają kierowcę przy własnym zapisie (_sprawdz_zasoby). Nie commituje.
    """
    pracownik = _pracownik(worker_id)
    if not pracownik.is_active:
        raise LogistykaBlad(u'{} nie jest już aktywnym pracownikiem — nie może zostać kierowcą.'.format(
            nazwa_pracownika(pracownik)), status=409)
    pracownik.is_driver = True
    db.session.flush()
    return pracownik


def usun_kierowce(worker_id):
    """
    Zdjęcie znacznika: pracownik zostaje w systemie, a na trasach, na których już jest
    kierowcą, zostaje (routes._sprawdz_zasoby przepuszcza niezmienionego kierowcę —
    rozstrzygnięcie 33). Idempotentne; 404 — nie ma pracownika. Bez blokady tras. Nie commituje.
    """
    pracownik = _pracownik(worker_id)
    pracownik.is_driver = False
    db.session.flush()
    return pracownik
