# -*- coding: utf-8 -*-
"""
Drabina priorytetów: szczeble gwiazdek (stałe), tagów i tras (ruchome) — spec 2026-10-04, sekcje 3.1 i 4.4.

Kolejność blokad (spec 9.4, CLAUDE.md „Trasy logistyki — jeden piszący naraz”): każdy zapis drabiny idzie pod
blokadą tras `routes.zablokuj_trasy()` — bierze ją wołający (`routes.utworz`, `routes.usun`) albo sama funkcja
(`przesun`, `uzupelnij`; ponowna blokada w tej samej transakcji jest bezpieczna) — potem wszystkie wiersze
`prod_priority_rungs` FOR UPDATE po `position`, dopiero zapisy. Drabina nie dotyka zamówień ani pozycji.

Widok drabiny (`szczeble`) pokazuje szczeble gwiazdek i tagów oraz szczeble tras roboczych/zatwierdzonych. Wiersz
szczebla trasy załadowanej, w drodze albo wykonanej zostaje w tabeli (ukryty) i wraca w to samo miejsce po
„Cofnij załadunek”. `position` jest renumerowane 1..n po WSZYSTKICH wierszach, a pozycje pokazywane ludziom
i zapisywane w `prod_orders.priority_rung` to indeksy wśród szczebli WIDOCZNYCH.

Funkcje nie commitują.
"""
from sqlalchemy import or_

from extensions import db
from modules.logging import get_structured_logger
# Moduł, nie nazwa: testy podmieniają `routes.zablokuj_trasy`, a import nazwy ominąłby podmianę.
from modules.production.logistics.services import routes
from modules.production.logistics.models import Route
from modules.production.models import get_local_now
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, PriorityRung

logger = get_structured_logger('production.priorytety.drabina')


class BladDrabiny(Exception):
    """Odmowa zapisu drabiny: `kod` (dla klienta API), `komunikat` po polsku, `status` HTTP."""

    def __init__(self, kod, komunikat, status):
        super(BladDrabiny, self).__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


def szczeble(aktualny=False):
    """
    Widoczne szczeble drabiny po `position`: gwiazdki, tagi i trasy robocze/zatwierdzone.

    `aktualny=True` — odczyt BIEŻĄCY (`FOR UPDATE` + `populate_existing`) szczebli i statusów ich tras; wołać
    tylko pod blokadą tras.
    """
    zapytanie = (PriorityRung.query
                 .outerjoin(Route, Route.id == PriorityRung.route_id)
                 .filter(or_(PriorityRung.kind != 'route',
                             Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE)))
                 .order_by(PriorityRung.position, PriorityRung.id))
    if aktualny:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.all()


def wszystkie_do_zapisu():
    """Wszystkie wiersze drabiny (także ukryte szczeble tras) FOR UPDATE, po `position`. Tylko pod blokadą tras."""
    return (PriorityRung.query.order_by(PriorityRung.position, PriorityRung.id)
            .with_for_update().populate_existing().all())


def _aktywne_trasy(route_ids):
    """
    Id tras (spośród `route_ids`), które są robocze albo zatwierdzone. Odczyt bieżący (`FOR SHARE`): wołający
    trzyma blokadę tras, ale migawka transakcji mogła powstać przed nią (REPEATABLE READ) — zwykły SELECT
    pokazałby status sprzed cudzego zapisu.
    """
    ids = sorted({i for i in route_ids if i is not None})
    if not ids:
        return set()
    wiersze = (db.session.query(Route.id)
               .filter(Route.id.in_(ids), Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE))
               .order_by(Route.id).with_for_update(read=True).all())
    return {wiersz[0] for wiersz in wiersze}


def _aktywne_w(wszystkie):
    return _aktywne_trasy(s.route_id for s in wszystkie if s.kind == 'route')


def _widoczne(wszystkie, aktywne_route_ids):
    return [s for s in wszystkie if s.kind != 'route' or s.route_id in aktywne_route_ids]


def miejsce_domyslne(wszystkie, aktywne_route_ids):
    """
    Indeks (0-based) w liście `wszystkie`, pod którym wchodzi nowy szczebel trasy (spec 3.1): bezpośrednio za
    najniższym szczeblem trasy roboczej/zatwierdzonej, a gdy takiej nie ma — bezpośrednio za pięcioma gwiazdkami.
    Drabina bez szczebla pięciu gwiazdek (baza bez seedu) → na samą górę.
    """
    indeksy_tras = [i for i, s in enumerate(wszystkie)
                    if s.kind == 'route' and s.route_id in aktywne_route_ids]
    if indeksy_tras:
        return indeksy_tras[-1] + 1
    for i, s in enumerate(wszystkie):
        if s.kind == 'stars' and s.stars == stale.GWIAZDKI_MAX:
            return i + 1
    return 0


def _przenumeruj(wszystkie, teraz):
    for i, szczebel in enumerate(wszystkie):
        if szczebel.position != i + 1:
            szczebel.position = i + 1
            szczebel.updated_at = teraz


def _wstaw_szczebel_trasy(wszystkie, route_id, user_id, teraz):
    """Nowy szczebel trasy w miejscu domyślnym listy `wszystkie` (zmienia ją w miejscu) + renumeracja + log."""
    aktywne = _aktywne_w(wszystkie) | {route_id}
    szczebel = PriorityRung(kind='route', route_id=route_id, position=0, created_at=teraz, updated_at=teraz,
                            updated_by=user_id)
    wszystkie.insert(miejsce_domyslne(wszystkie, aktywne - {route_id}), szczebel)
    _przenumeruj(wszystkie, teraz)
    db.session.add(szczebel)
    db.session.flush()
    db.session.add(PriorityLog(action='szczebel', route_id=route_id, user_id=user_id, created_at=teraz,
                               new_value=str(_widoczne(wszystkie, aktywne).index(szczebel) + 1)))
    db.session.flush()
    return szczebel


def zapewnij_szczebel_trasy(route, user_id=None):
    """
    Szczebel trasy `route` — istniejący albo nowy w miejscu domyślnym (renumeracja wszystkich wierszy, log
    `szczebel`). Idempotentne: trasa po „Cofnij załadunek” ma swój wiersz przez cały czas.

    WARUNEK WSTĘPNY: wołający trzyma blokadę tras (`routes.utworz`, `uzupelnij`).
    """
    wszystkie = wszystkie_do_zapisu()
    for szczebel in wszystkie:
        if szczebel.kind == 'route' and szczebel.route_id == route.id:
            return szczebel
    return _wstaw_szczebel_trasy(wszystkie, route.id, user_id, get_local_now())


def usun_szczebel_trasy(route_id):
    """
    Usuwa szczebel trasy (jeśli jest) i renumeruje resztę. Zwraca, czy coś usunął. Na MySQL dubluje FK
    `ON DELETE CASCADE`, ale renumeruje od razu; na SQLite testów to jedyna droga.

    WARUNEK WSTĘPNY: wołający trzyma blokadę tras (`routes.usun`).
    """
    wszystkie = wszystkie_do_zapisu()
    szczebel = next((s for s in wszystkie if s.kind == 'route' and s.route_id == route_id), None)
    if szczebel is None:
        return False
    wszystkie.remove(szczebel)
    db.session.delete(szczebel)
    _przenumeruj(wszystkie, get_local_now())
    db.session.flush()
    return True


def przesun(rung_id, pozycja, user_id=None):
    """
    Przesuwa szczebel tagu albo trasy na pozycję `pozycja` (1-based) liczoną wśród szczebli WIDOCZNYCH. Szczeble
    gwiazdek są nieruchome. Renumeruje wszystkie wiersze i zapisuje log `szczebel` (stara i nowa pozycja).

    Sama bierze blokadę tras. Odmowy: `BladDrabiny` — `brak_szczebla` 404, `szczebel_staly` 400,
    `trasa_nieaktywna` 409, `pozycja_poza_zakresem` 400.
    """
    routes.zablokuj_trasy()
    wszystkie = wszystkie_do_zapisu()
    szczebel = next((s for s in wszystkie if s.id == rung_id), None)
    if szczebel is None:
        raise BladDrabiny('brak_szczebla', u'Nie ma takiego szczebla.', 404)
    if szczebel.kind == 'stars':
        raise BladDrabiny('szczebel_staly', u'Szczebli gwiazdek nie można przesuwać.', 400)
    aktywne = _aktywne_w(wszystkie)
    if szczebel.kind == 'route' and szczebel.route_id not in aktywne:
        raise BladDrabiny('trasa_nieaktywna',
                          u'Trasa tego szczebla nie jest już robocza ani zatwierdzona.', 409)
    widoczne = _widoczne(wszystkie, aktywne)
    if isinstance(pozycja, bool) or not isinstance(pozycja, int) or not 1 <= pozycja <= len(widoczne):
        raise BladDrabiny('pozycja_poza_zakresem',
                          u'Podaj pozycję od 1 do {}.'.format(len(widoczne)), 400)
    stara = widoczne.index(szczebel) + 1
    if stara == pozycja:
        return szczebel

    # Wyjęcie i wstawienie przed widocznym szczeblem, który po przesunięciu ma stać tuż pod naszym (albo na
    # koniec). Ukryte szczeble tras zostają tam, gdzie były.
    teraz = get_local_now()
    pozostale = [s for s in widoczne if s is not szczebel]
    wszystkie.remove(szczebel)
    if pozycja - 1 < len(pozostale):
        wszystkie.insert(wszystkie.index(pozostale[pozycja - 1]), szczebel)
    else:
        wszystkie.append(szczebel)
    _przenumeruj(wszystkie, teraz)
    szczebel.updated_at = teraz
    szczebel.updated_by = user_id
    db.session.add(PriorityLog(
        action='szczebel', route_id=szczebel.route_id, old_value=str(stara), new_value=str(pozycja),
        note=szczebel.tag if szczebel.kind == 'tag' else None, user_id=user_id, created_at=teraz))
    db.session.flush()
    return szczebel


def uzupelnij(user_id=None):
    """
    Samonaprawa drabiny: dopisuje brakujące szczeble stałe (na końcu, w kolejności domyślnej — na pustej drabinie
    daje to seed migracji) i szczeble tras roboczych/zatwierdzonych bez szczebla (w miejscu domyślnym, rosnąco
    po id trasy — tak samo liczy je `kolejka.policz`). Zwraca liczbę dopisanych.

    Sama bierze blokadę tras. Potrzebna po wdrożeniu (trasy sprzed migracji nie mają szczebli) i w cronie.
    """
    routes.zablokuj_trasy()
    wszystkie = wszystkie_do_zapisu()
    teraz = get_local_now()
    istniejace = {s.klucz for s in wszystkie}
    dopisane = 0

    for rodzaj, wartosc in stale.DRABINA_DOMYSLNA:
        if (rodzaj, wartosc) in istniejace:
            continue
        szczebel = PriorityRung(kind=rodzaj, stars=wartosc if rodzaj == 'stars' else None,
                                tag=wartosc if rodzaj == 'tag' else None, position=0,
                                created_at=teraz, updated_at=teraz, updated_by=user_id)
        wszystkie.append(szczebel)
        db.session.add(szczebel)
        dopisane += 1
        logger.warning(u'Drabina priorytetów bez szczebla stałego — dopisany na końcu',
                       extra={'rodzaj': rodzaj, 'wartosc': str(wartosc)})
    if dopisane:
        _przenumeruj(wszystkie, teraz)
        db.session.flush()

    trasy = (db.session.query(Route.id).filter(Route.status.in_(stale.STATUSY_TRASY_NA_DRABINIE))
             .order_by(Route.id).with_for_update(read=True).all())
    for (route_id,) in trasy:
        if ('route', route_id) in istniejace:
            continue
        _wstaw_szczebel_trasy(wszystkie, route_id, user_id, teraz)
        dopisane += 1
        logger.info(u'Drabina priorytetów: dopisany szczebel trasy', extra={'route_id': route_id})
    return dopisane


def pozycja_szczebla(szczebel, widoczne=None):
    """Pozycja szczebla wśród widocznych, 1-based („szczebel 1 z 11”); None, gdy szczebel jest ukryty.
    `widoczne` — wynik `szczeble()`, jeśli wołający już go ma (bez ponownego odczytu)."""
    widoczne = szczeble() if widoczne is None else widoczne
    for i, kandydat in enumerate(widoczne, start=1):
        if kandydat.id == szczebel.id:
            return i
    return None


def pozycja_tagu(tag, widoczne=None):
    """Pozycja szczebla tagu wśród widocznych, 1-based; None, gdy drabina nie ma takiego szczebla."""
    widoczne = szczeble() if widoczne is None else widoczne
    for i, kandydat in enumerate(widoczne, start=1):
        if kandydat.kind == 'tag' and kandydat.tag == tag:
            return i
    return None
