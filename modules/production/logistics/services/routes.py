# -*- coding: utf-8 -*-
"""
Trasy transportu własnego (spec, sekcja 8.2).

Statusy: robocza (pełna edycja) → zatwierdzona (zablokowana, eksport Routimo)
→ wykonana (tylko odczyt; przywracana do zatwierdzonej). Funkcje NIE commitują.
Każda zmiana widoczna na tablecie podbija updated_at pozycji zamówień
(ETag kolejek tabletów — spec 6.5).
"""
import re
from datetime import date

from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.models import Route, RouteStop, STATUSY_TRASY_AKTYWNE, Vehicle
from modules.production.logistics.services import delivery, fleet
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import (
    ProductionConfig, ProductionOrder, ProductionWorker, get_local_now,
)

logger = get_structured_logger('production.logistics.routes')

# Ta sama wartość, co stała modelu (Task 1) — trasy, które widzi tablet i które
# blokują pojazd/kierowcę. Import zamiast drugiej literalnej krotki: jedno miejsce
# prawdy o tym, co znaczy "aktywna trasa".
AKTYWNE = STATUSY_TRASY_AKTYWNE
WAGA_KG_NA_M3 = 800
MAKS_NAZWA = 120
# (fix-2, przegląd Task 6) prod_routes.notes to TEXT w MySQL (limit 65 535 B) —
# bez tego limitu notatka dłuższa od tego (nie licząc wielobajtowych znaków —
# jeszcze mniej) rzuciłaby MySQL 1406 dopiero przy commicie (500; SQLite testów
# tego nie zobaczy, bo nie ma takiego ograniczenia). 2000 znaków to zapas daleko
# poniżej limitu, czytelny 422 zamiast niejasnego błędu bazy.
MAKS_NOTATKA = 2000
# Klucz wiersza prod_config, który serializuje zapisy tras — patrz zablokuj_trasy().
KLUCZ_BLOKADY = 'logistyka_trasy_blokada'
# (fix-2, Minor 3 residual) Cyfry ASCII, 1-9 znaków — `str.isdigit()` przepuszcza
# też np. „²”/„①” (Unicode), na których goły `int()` rzuca ValueError; górny limit
# długości chroni przed >4300-cyfrowym tekstem, na którym `int()` też rzuca
# ValueError (limit CPython 3.11+) zamiast czytelnego 422.
_ID_RE = re.compile(r'[0-9]{1,9}')
# Ostrzeżenie o brakującym wierszu blokady najwyżej raz na proces (jak
# panel_api._carto_key_ostrzezono) — nie chcemy zalewać logu przy każdym zapisie.
_blokada_ostrzezono = False


# ── Pomocnicze ─────────────────────────────────────────────────────────────

def _data(wartosc, pole):
    if isinstance(wartosc, date):
        return wartosc
    try:
        return date.fromisoformat(str(wartosc))
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Pole „{}”: podaj datę RRRR-MM-DD.'.format(pole), status=422)


def _id(wartosc, pole):
    """
    (fix-1, Ruling C + fix-2, Minor 3 residual/O4) Przyjmuje WYŁĄCZNIE `int` (nie
    `bool` — `bool` jest podklasą `int` w Pythonie, `True` inaczej stałby się id=1)
    albo tekst dopasowany do `_ID_RE` (cyfry ASCII, 1-9 znaków); nigdy nie woła
    gołego `int()`/`float()` na nieznanym typie. Floaty ZAWSZE 422 — także `0.0`,
    które dawniej (przez `in (None, '', 0, '0')`) po cichu stawało się `None`.
    Po sparsowaniu wartość 0 (int `0`, `'0'`, `'00'`, ...) oznacza „brak" → `None`,
    tak samo jak `None`/`''` — nigdy `vehicle_id=0` (złamałoby FK przy flushu).
    """
    if wartosc is None or wartosc == '':
        return None
    if isinstance(wartosc, (bool, float)):
        raise LogistykaBlad(u'Pole „{}”: nieprawidłowa wartość.'.format(pole), status=422)
    if isinstance(wartosc, int):
        liczba = wartosc
    elif isinstance(wartosc, str) and _ID_RE.fullmatch(wartosc.strip()):
        liczba = int(wartosc.strip())
    else:
        raise LogistykaBlad(u'Pole „{}”: nieprawidłowa wartość.'.format(pole), status=422)
    return None if liczba == 0 else liczba


def zablokuj_trasy(route=None):
    """
    (fix-1, Ruling A) Blokada globalna „jeden piszący trasy naraz" + — gdy podano
    `route` — jej ODCZYT BIEŻĄCY razem z przystankami. Zwraca świeżą trasę (albo
    None, gdy wołane bez argumentu).

    DLACZEGO: nic w repo nie ustawia poziomu izolacji, więc MySQL 8.4 pracuje na
    REPEATABLE READ. Migawka zwykłego SELECT-a pochodzi z PIERWSZEGO zwykłego
    odczytu CAŁEJ transakcji — nie z chwili wzięcia blokady. Wołający prawie zawsze
    coś już przeczytał, zanim tu dotarł (Flask-Login ładuje usera; `edytuj`/
    `przywroc` dostają już wczytaną trasę), więc samo wzięcie blokady NIE
    wystarcza — potrzeba odczytu BIEŻĄCEGO: `FOR UPDATE`/`FOR SHARE` w InnoDB
    czyta ostatni ZACOMMITOWANY wiersz (nie migawkę), a `populate_existing()`
    wymusza nadpisanie atrybutów obiektu już siedzącego w identity mapie —
    bez tego SQLAlchemy oddałby starą kopię z pamięci mimo świeżego SELECT-a.

    Jeden WSPÓLNY wiersz blokady (zamiast osobnych blokad per pojazd/kierowca)
    serializuje WSZYSTKIE zapisy tras jedną kolejką. WoodPower ma 1–2 osoby w
    logistyce, więc to nic nie kosztuje, a jest odporne na zakleszczenie: blokady
    per zasób wzięte przez dwie trasy w RÓŻNEJ kolejności (np. trasa A bierze
    pojazd V1 potem czeka na V2, trasa B odwrotnie) mogłyby się zakleszczyć —
    jeden wspólny zamek pierwszy eliminuje ten scenariusz.

    ZASADA: każda funkcja zmieniająca trasę woła to PIERWSZA, przed jakimkolwiek
    zapisem. Wywołania zagnieżdżone w tej samej transakcji (np. `wykonaj` →
    `usun_przystanek`) są bezpieczne — blokada jest już trzymana (MySQL pozwala
    tej samej transakcji wielokrotnie zablokować ten sam wiersz), a autoflush
    przed kolejnym SELECT-em i tak wypycha wcześniejsze zmiany tej transakcji.

    Brak wiersza blokady (świeża baza przed migracją — SQLite testów go nie ma)
    NIE blokuje zapisu: ostrzeżenie raz na proces, migracja go zakłada (fail-open).
    """
    global _blokada_ostrzezono
    wiersz = (ProductionConfig.query.filter_by(config_key=KLUCZ_BLOKADY)
              .with_for_update().first())
    if wiersz is None and not _blokada_ostrzezono:
        _blokada_ostrzezono = True
        logger.warning(u"Brak wiersza blokady tras '{}' w prod_config - zapisy tras "
                       u"NIE sa serializowane (migracja go zaklada)".format(KLUCZ_BLOKADY))
    if route is None:
        return None
    swieza = (Route.query.options(joinedload(Route.stops))
             .filter(Route.id == route.id)
             .with_for_update().populate_existing().one_or_none())
    if swieza is None:
        raise LogistykaBlad(u'Nie ma takiej trasy.', status=404)
    return swieza


def _lista_id(wartosc):
    """
    Lista/krotka Pythonowych int-ów identyfikatorów zamówień z zewnątrz (JSON API
    etapu 3 wywoła to wprost na ciele żądania). `bool` NIE liczy się jako int tutaj,
    mimo że w Pythonie jest podklasą int — [True] inaczej przeszłoby jako id=1.
    Każdy inny typ (napis, float, dict, None w środku) i każdy typ inny niż
    list/tuple (np. napis „abc”, który sam jest iterowalny) odrzucamy tu, PRZED
    jakąkolwiek zmianą w sesji — ten sam wzorzec co panel_api.py:117 (etap 2).
    """
    if (not isinstance(wartosc, (list, tuple))
            or any(not isinstance(i, int) or isinstance(i, bool) for i in wartosc)):
        raise LogistykaBlad(u'Identyfikatory zamówień muszą być listą liczb całkowitych.',
                            status=422)
    return list(wartosc)


def _wymagaj_statusu(route, *statusy):
    if route.status not in statusy:
        opis = {'robocza': u'robocza', 'zatwierdzona': u'zatwierdzona', 'wykonana': u'wykonana'}
        raise LogistykaBlad(u'Trasa „{}” jest {} — ta operacja nie jest dostępna.'.format(
            route.name, opis.get(route.status, route.status)))


def zamowienia_trasy(route):
    ids = [s.order_id for s in route.stops]
    if not ids:
        return []
    po_id = {o.id: o for o in ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).all()}
    return [po_id[i] for i in ids if i in po_id]


def _podbij_trase(route, teraz):
    for order in zamowienia_trasy(route):
        delivery.podbij_pozycje(order, teraz)


def _log_statusu(route, stary, nowy, user_id, teraz):
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', stary, nowy, user_id=user_id,
                            route_id=route.id, teraz=teraz)


# ── Zajętość zasobów ──────────────────────────────────────────────────────

def zajetosc(date_from, date_to, pomin_route_id=None, aktualny=False):
    zapytanie = Route.query.filter(Route.status.in_(AKTYWNE),
                                   Route.date_from <= date_to, Route.date_to >= date_from)
    if pomin_route_id:
        zapytanie = zapytanie.filter(Route.id != pomin_route_id)
    if aktualny:
        # (fix-1, Ruling A4) Odczyt bieżący (FOR SHARE) — zwykły SELECT czytałby
        # z migawki REPEATABLE READ sprzed wzięcia blokady globalnej
        # (zablokuj_trasy, wywołana wcześniej przez wołającego _sprawdz_zasoby),
        # więc mógłby nie zobaczyć trasy, którą inny piszący właśnie zacommitował.
        zapytanie = zapytanie.with_for_update(read=True).populate_existing()
    pojazdy, kierowcy = {}, {}
    for trasa in zapytanie.order_by(Route.date_from).all():
        if trasa.vehicle_id:
            pojazdy.setdefault(trasa.vehicle_id, trasa.name)
        if trasa.driver_worker_id:
            kierowcy.setdefault(trasa.driver_worker_id, trasa.name)
    return {'pojazdy': pojazdy, 'kierowcy': kierowcy}


def dostepnosc(date_from, date_to, pomin_route_id=None):
    z = zajetosc(date_from, date_to, pomin_route_id)   # podgląd UI — zwykły odczyt wystarczy
    return {
        'pojazdy': [dict(p, zajety=p['id'] in z['pojazdy'], trasa=z['pojazdy'].get(p['id']))
                    for p in fleet.lista_pojazdow(tylko_aktywne=True)],
        'kierowcy': [dict(k, zajety=k['id'] in z['kierowcy'], trasa=z['kierowcy'].get(k['id']))
                     for k in fleet.kierowcy()],
    }


def _sprawdz_zasoby(od, do, vehicle_id, driver_id, pomin_route_id=None):
    if vehicle_id:
        # (fix-1, Ruling A4 + fix-2, N3) To jest odczyt BIEŻĄCY is_active, NIE
        # serializacja — serializację zapewnia wspólna blokada wzięta przez
        # zablokuj_trasy() na starcie funkcji wołającej. Bez FOR UPDATE zwykły
        # SELECT czytałby is_active z migawki transakcji sprzed tamtej blokady
        # (REPEATABLE READ), więc mógłby przepuścić pojazd wyłączony z floty w
        # międzyczasie. `populate_existing()` jest tu równie konieczne jak
        # `with_for_update()`: bez niego, gdy `Vehicle` o tym id jest już w
        # identity mapie (np. wczytany wcześniej w tym samym żądaniu), SQLAlchemy
        # oddałby STARĄ kopię z pamięci zamiast nadpisać ją świeżym `is_active`.
        pojazd = (Vehicle.query.filter_by(id=vehicle_id)
                 .with_for_update().populate_existing().first())
        if pojazd is None:
            raise LogistykaBlad(u'Nie ma takiego pojazdu.', status=422)
        if not pojazd.is_active:
            raise LogistykaBlad(u'Pojazd „{}” jest wyłączony z floty.'.format(pojazd.name), status=422)
    if driver_id:
        kierowca = ProductionWorker.query.get(driver_id)
        if kierowca is None or not kierowca.is_active:
            raise LogistykaBlad(u'Nie ma takiego aktywnego kierowcy.', status=422)
    # Sprawdzenie konfliktu MUSI być odczytem bieżącym (Ruling A4) — inaczej
    # trasa, którą inny piszący właśnie zacommitował, byłaby niewidoczna.
    z = zajetosc(od, do, pomin_route_id, aktualny=True)
    if vehicle_id and vehicle_id in z['pojazdy']:
        raise LogistykaBlad(u'Pojazd jest zajęty na trasie „{}” w tych dniach.'.format(
            z['pojazdy'][vehicle_id]))
    if driver_id and driver_id in z['kierowcy']:
        raise LogistykaBlad(u'Kierowca jest zajęty na trasie „{}” w tych dniach.'.format(
            z['kierowcy'][driver_id]))


def _dane_trasy(dane):
    # (fix-1, Ruling C) `name`/`notes` spoza `str` (np. {"name": 5} z JSON API etapu 6)
    # rzucałyby AttributeError na .strip() gołego inta — 500 zamiast czytelnej odmowy.
    nazwa_surowa = dane.get('name')
    if not isinstance(nazwa_surowa, str):
        raise LogistykaBlad(u'Podaj nazwę trasy (do {} znaków).'.format(MAKS_NAZWA), status=422)
    nazwa = nazwa_surowa.strip()
    if not nazwa or len(nazwa) > MAKS_NAZWA:
        raise LogistykaBlad(u'Podaj nazwę trasy (do {} znaków).'.format(MAKS_NAZWA), status=422)
    od = _data(dane.get('date_from'), u'data od')
    do = _data(dane.get('date_to') or dane.get('date_from'), u'data do')
    if do < od:
        raise LogistykaBlad(u'Data „do” jest wcześniejsza niż „od”.', status=422)
    notatka_surowa = dane.get('notes')
    if notatka_surowa is not None and not isinstance(notatka_surowa, str):
        raise LogistykaBlad(u'Pole „notatka”: podaj tekst.', status=422)
    notatka = (notatka_surowa or '').strip() or None
    if notatka is not None and len(notatka) > MAKS_NOTATKA:
        raise LogistykaBlad(u'Notatka może mieć najwyżej {} znaków.'.format(MAKS_NOTATKA),
                            status=422)
    return (nazwa, od, do, _id(dane.get('vehicle_id'), u'pojazd'),
            _id(dane.get('driver_worker_id'), u'kierowca'), notatka)


# ── Tworzenie i edycja ────────────────────────────────────────────────────

def utworz(dane, user_id=None):
    zablokuj_trasy()   # (fix-1, Ruling A3) blokada PIERWSZA, przed jakimkolwiek odczytem/zapisem
    nazwa, od, do, pojazd_id, kierowca_id, notatka = _dane_trasy(dane)
    _sprawdz_zasoby(od, do, pojazd_id, kierowca_id)
    teraz = get_local_now()
    trasa = Route(name=nazwa, date_from=od, date_to=do, vehicle_id=pojazd_id,
                  driver_worker_id=kierowca_id, notes=notatka, status='robocza',
                  created_at=teraz, created_by=user_id, updated_at=teraz, geometry_approx=False)
    db.session.add(trasa)
    db.session.flush()
    return trasa


def edytuj(route, dane, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'robocza')
    nazwa, od, do, pojazd_id, kierowca_id, notatka = _dane_trasy(dane)
    _sprawdz_zasoby(od, do, pojazd_id, kierowca_id, pomin_route_id=route.id)
    route.name, route.date_from, route.date_to = nazwa, od, do
    route.vehicle_id, route.driver_worker_id, route.notes = pojazd_id, kierowca_id, notatka
    db.session.flush()
    db.session.expire(route, ['vehicle', 'driver'])
    _podbij_trase(route, get_local_now())
    return route


# ── Odczyty dla innych modułów ────────────────────────────────────────────

def przystanek_zamowienia(order_id, aktualny=False):
    zapytanie = RouteStop.query.filter_by(order_id=order_id)
    if aktualny:
        # (fix-1, Ruling A6) Woła np. delivery._przystanek_do_zmiany PRZED
        # odczytem statusu trasy — patrz zablokuj_trasy() po co.
        zapytanie = zapytanie.with_for_update(read=True).populate_existing()
    return zapytanie.first()


def trasy_zamowien(order_ids):
    if not order_ids:
        return {}
    wiersze = (db.session.query(RouteStop.order_id, Route)
               .join(Route, RouteStop.route_id == Route.id)
               .filter(RouteStop.order_id.in_(list(order_ids))).all())
    return {order_id: trasa for order_id, trasa in wiersze}


def mapa_tras_aktywnych():
    wiersze = (db.session.query(RouteStop.order_id, Route)
               .join(Route, RouteStop.route_id == Route.id)
               .filter(Route.status.in_(AKTYWNE)).all())
    return {order_id: trasa for order_id, trasa in wiersze}


def trasa_dla_tabletu(order_id):
    """Trasa (robocza/zatwierdzona) zamówienia; jedno zapytanie na żądanie HTTP (cache w g)."""
    from flask import g, has_request_context
    if has_request_context():
        mapa = getattr(g, '_logistyka_trasy_aktywne', None)
        if mapa is None:
            mapa = g._logistyka_trasy_aktywne = mapa_tras_aktywnych()
    else:
        mapa = mapa_tras_aktywnych()
    return mapa.get(order_id)


# ── Przystanki ────────────────────────────────────────────────────────────

def _przenumeruj(route):
    """
    (fix-2, O1) Renumeruje ze ŚWIEŻEJ `route.stops` w pamięci (załadowanej przez
    `zablokuj_trasy` pod blokadą) — ŻADNEGO `expire()` + zwykłego zapytania.
    Zwykły SELECT czytałby migawkę transakcji sprzed zdjęcia blokady, więc trasa
    usuwana tuż po zmianie kolejności zacommitowanej przez poprzedniego piszącego
    renumerowałaby ze starego porządku (cicho cofając tamtą zmianę), a przy
    dwóch usunięciach z rzędu mogłaby trafić UPDATE-em w wiersz, którego już nie
    ma (StaleDataError, potwierdzone realnym wyścigiem dwóch sesji MySQL).
    Wołający (`usun_przystanek`) musi wcześniej zdjąć usuwany przystanek z
    `route.stops` — ta funkcja renumeruje to, co w kolekcji zostało.
    """
    for pozycja, przystanek in enumerate(route.stops, start=1):
        przystanek.position = pozycja
    db.session.flush()


def dodaj_przystanki(route, order_ids, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'robocza')
    order_ids = _lista_id(order_ids)
    teraz = get_local_now()
    unikalne = list(dict.fromkeys(order_ids))
    zamowienia = {o.id: o for o in
                  ProductionOrder.query.filter(ProductionOrder.id.in_(unikalne)).all()}
    # (fix-1, Ruling A5) JEDNO bieżące zapytanie o wszystkie żądane id zamiast
    # przystanek_zamowienia() w pętli per zamówienie — ten sam powód co reszta
    # blokad w tym pliku: zwykły SELECT czytałby z migawki sprzed zablokuj_trasy()
    # powyżej i mógłby nie zobaczyć przystanku, który inny piszący dopiero co dodał.
    zajete = dict(db.session.query(RouteStop.order_id, Route.name)
                  .join(Route, RouteStop.route_id == Route.id)
                  .filter(RouteStop.order_id.in_(unikalne))
                  .with_for_update(read=True).all())
    pozycja = max([s.position for s in route.stops] or [0])
    dodane, bledy = [], []
    for order_id in unikalne:
        order = zamowienia.get(order_id)
        if order is None:
            bledy.append({'order_id': order_id, 'komunikat': u'Nie ma takiego zamówienia.'})
            continue
        numer = order.internal_order_number
        # Znana resztka ryzyka (fix-1, Ruling A8 — świadomie NIE domykana): zmiana
        # sposobu dostawy na kuriera i dodanie tego samego zamówienia do trasy w tej
        # samej milisekundzie nadal mogą oba przejść — zamknięcie tego wymagałoby
        # blokady na prod_orders, co zakleszczałoby się z synchronizacją Base.
        if sposoby.normalizuj(order.override_delivery_method) != sposoby.TRANSPORT:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} nie ma ustawionego transportu własnego.'.format(numer)})
            continue
        if order.logistics_closed_at is not None:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest zamknięte w logistyce.'.format(numer)})
            continue
        if order_id in zajete:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest już na trasie „{}”.'.format(numer, zajete[order_id])})
            continue
        pozycja += 1
        # (fix-2, O1) Dopisujemy do route.stops W PAMIĘCI (cascade='save-update'
        # dopisze go do sesji sam) zamiast db.session.add() + expire() po pętli —
        # route.stops zostaje jedynym, spójnym źródłem prawdy, świeżym od
        # zablokuj_trasy() na starcie tej funkcji; żadnego zwykłego zapytania,
        # które czytałoby migawkę sprzed zdjęcia blokady.
        route.stops.append(RouteStop(route_id=route.id, order_id=order_id, position=pozycja))
        db.session.flush()
        delivery.zapisz_log(order, 'trasa_dodane', None, route.name[:64], user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        dodane.append(order_id)
    return {'dodane': dodane, 'bledy': bledy}


def usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True):
    # (fix-1, Ruling A3) Wołania zagnieżdżone (wykonaj/usun w pętli) są bezpieczne —
    # patrz docstring zablokuj_trasy().
    route = zablokuj_trasy(route)
    if wymagaj_roboczej:
        _wymagaj_statusu(route, 'robocza')
    # (fix-2, O1) Przystanek szukany w ŚWIEŻEJ route.stops (z zablokuj_trasy
    # powyżej), NIE nowym zapytaniem — zwykły SELECT czytałby migawkę transakcji
    # sprzed zdjęcia blokady: mógłby zgubić przystanek dodany przez poprzedniego
    # piszącego (fałszywe 404 — potwierdzone realnym wyścigiem dwóch sesji MySQL:
    # wykonaj rzucał 404 na przystanku dodanym równolegle) albo trafić na już
    # usunięty (StaleDataError przy DELETE nieistniejącego wiersza).
    przystanek = next((s for s in route.stops if s.order_id == order_id), None)
    if przystanek is None:
        raise LogistykaBlad(u'Tego zamówienia nie ma na trasie „{}”.'.format(route.name), status=404)
    order = ProductionOrder.query.get(order_id)
    # Zdejmujemy z route.stops W PAMIĘCI (cascade='delete-orphan' skasuje wiersz) —
    # _przenumeruj renumeruje z tej samej, już poprawnej kolekcji.
    route.stops.remove(przystanek)
    _przenumeruj(route)
    teraz = get_local_now()
    delivery.zapisz_log(order, 'trasa_usuniete', route.name[:64], None, user_id=user_id,
                        note=note, route_id=route.id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return order


def zmien_kolejnosc(route, order_ids):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'robocza')
    nowe = _lista_id(order_ids)
    obecne = {s.order_id: s for s in route.stops}
    if len(nowe) != len(obecne) or set(nowe) != set(obecne):
        raise LogistykaBlad(u'Kolejność musi zawierać dokładnie przystanki tej trasy.', status=422)
    for pozycja, order_id in enumerate(nowe, start=1):
        obecne[order_id].position = pozycja
    # (fix-2, O1) Porządek w PAMIĘCI (sort route.stops), bez expire() + zwykłego
    # zapytania — ten sam powód co _przenumeruj/dodaj_przystanki w tym pliku.
    route.stops.sort(key=lambda s: s.position)
    db.session.flush()


# ── Statusy ───────────────────────────────────────────────────────────────

def zatwierdz(route, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'robocza')
    if not route.stops:
        raise LogistykaBlad(u'Trasa bez przystanków nie może być zatwierdzona.', status=422)
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'zatwierdzona', teraz, user_id
    _log_statusu(route, 'robocza', 'zatwierdzona', user_id, teraz)
    _podbij_trase(route, teraz)


def cofnij_do_roboczej(route, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'zatwierdzona')
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'robocza', None, None
    _log_statusu(route, 'zatwierdzona', 'robocza', user_id, teraz)
    _podbij_trase(route, teraz)


def wykonaj(route, dostarczone_ids=None, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, *AKTYWNE)
    na_trasie = [s.order_id for s in route.stops]
    if not na_trasie:
        raise LogistykaBlad(u'Trasa nie ma przystanków.', status=422)
    dostarczone = set(na_trasie) if dostarczone_ids is None else set(_lista_id(dostarczone_ids))
    if not dostarczone <= set(na_trasie):
        raise LogistykaBlad(u'Część zamówień nie należy do tej trasy.', status=422)
    niedostarczone = [i for i in na_trasie if i not in dostarczone]
    for order_id in niedostarczone:
        usun_przystanek(route, order_id, user_id=user_id, note=u'niedostarczone',
                        wymagaj_roboczej=False)
    teraz = get_local_now()
    stary = route.status
    route.status, route.completed_at, route.completed_by = 'wykonana', teraz, user_id
    db.session.flush()
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', stary, 'wykonana', user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)
    return {'dostarczone': [i for i in na_trasie if i in dostarczone],
            'niedostarczone': niedostarczone}


def przywroc(route, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'wykonana')
    _sprawdz_zasoby(route.date_from, route.date_to, route.vehicle_id, route.driver_worker_id,
                    pomin_route_id=route.id)
    teraz = get_local_now()
    route.status, route.completed_at, route.completed_by = 'zatwierdzona', None, None
    db.session.flush()
    for order in zamowienia_trasy(route):
        delivery.zapisz_log(order, 'trasa_status', 'wykonana', 'zatwierdzona', user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)


def usun(route, user_id=None):
    route = zablokuj_trasy(route)   # (fix-1, Ruling A3) przed _wymagaj_statusu — świeży stan
    _wymagaj_statusu(route, 'robocza')
    for order_id in [s.order_id for s in route.stops]:
        usun_przystanek(route, order_id, user_id=user_id, note=u'usunięcie trasy')
    db.session.delete(route)
    db.session.flush()


# ── Podsumowanie i serializacja ───────────────────────────────────────────

def podsumowanie(route, zamowienia, punkty):
    m3 = sum(float(p.volume_m3 or 0) * (p.quantity or 1)
             for o in zamowienia for p in delivery.aktywne_produkty(o))
    waga = int(round(m3 * WAGA_KG_NA_M3))
    ladownosc = route.vehicle.capacity_kg if route.vehicle is not None else None
    return {
        'przystanki': len(zamowienia),
        'm3': round(m3, 4),
        'waga_kg': waga,
        'km': float(route.distance_km) if route.distance_km is not None else None,
        'minuty': route.duration_min,
        'przyblizony': bool(route.geometry_approx),
        'bez_lokalizacji': sum(1 for o in zamowienia
                               if punkty.get(o.id) is None or punkty[o.id].lat is None),
        'przekroczona_ladownosc': bool(ladownosc) and waga > ladownosc,
    }


def serializuj_trase(route, zamowienia=None, punkty=None):
    kierowca = route.driver
    dane = {
        'id': route.id,
        'nazwa': route.name,
        'date_from': route.date_from.isoformat(),
        'date_to': route.date_to.isoformat(),
        'status': route.status,
        'pojazd': fleet.serializuj_pojazd(route.vehicle) if route.vehicle is not None else None,
        'kierowca': ({'id': kierowca.id, 'nazwa': u'{} {}'.format(kierowca.first_name,
                                                                   kierowca.last_name).strip()}
                     if kierowca is not None else None),
        'notatka': route.notes,
        'zatwierdzona': route.approved_at.isoformat() if route.approved_at else None,
        'wykonana': route.completed_at.isoformat() if route.completed_at else None,
    }
    if zamowienia is not None:
        dane['podsumowanie'] = podsumowanie(route, zamowienia, punkty or {})
    return dane
