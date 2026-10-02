# -*- coding: utf-8 -*-
"""
API tras, floty i dostępności — /production/api/logistics/* (etap 3).

Eksport do Routimo: `GET /routes/<id>/routimo` (Task 7) — formatowanie w
modules/production/logistics/services/routimo.py, wspólne z eksportem
zakładki Raporty (modules/reports/routers.generate_routimo_excel).

Dostawa (krok 4.4): `POST /routes/<id>/unload` („Cofnij załadunek”), `POST /routes/<id>/stops/<oid>/undo-delivered`
(„Cofnij dostarczenie”), odhaczenie `/complete` przez services/dostawa.py. U10 (Ruling 32): niedostarczony przystanek
zostaje na trasie w drodze — `POST /routes/<id>/stops/<oid>/undo-not-delivered` („Cofnij niedostarczenie”)
i `/remove-not-delivered` („Zdejmij z trasy”), historia zdjętych w `niedostarczone_zdjete`.

Optymalizacja kolejności (krok 4.4d): `POST /routes/<id>/optimize` — podgląd (services/optymalizacja.py), bez zapisu.
"""
import io
from datetime import timedelta

from flask import jsonify, request, send_file
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import ObjectDeletedError, StaleDataError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.models import LogisticsLog, Route, STATUSY_TRASY, Vehicle
from modules.production.logistics.routers.panel_api import LIMIT_HURTU, _blad, _user_id, _zapis_pod_blokada, guard
from modules.production.logistics.services import (bl_sync, dostawa, fleet, geocoding, lista, optymalizacja, paczki,
                                                   routes, routimo, routing)
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services import blokady_zamowien

logger = get_structured_logger('production.logistics.trasy_api')

# Sekcje listy tras w kolejności cyklu trasy (krok 4.4: załadowane i w trasie między zatwierdzonymi a wykonanymi).
KOLEJNOSC_STATUSOW = {'robocza': 0, 'zatwierdzona': 1, 'zaladowana': 2, 'w_trasie': 3, 'wykonana': 4}
# (I1, ruling okna domyślnego) Bez jawnego `od` GET /routes ciągnąłby WSZYSTKIE
# trasy w historii firmy — trasy WYKONANE (zamknięty, archiwalny stan) starsze
# niż tyle dni znikają z domyślnego widoku; trasy w każdym innym statusie (robocza,
# zatwierdzona, załadowana, w trasie) NIGDY nie są tym oknem przycinane (to bieżąca praca).
DNI_WYKONANYCH_DOMYSLNIE = 30
KOMUNIKAT_KONFLIKT_PRZYSTANKU = (u'Zamówienie trafiło w międzyczasie na inną trasę — '
                                 u'odśwież listę i spróbuj ponownie.')
KOMUNIKAT_KONFLIKT_TRASY = u'Dane trasy zmieniły się w międzyczasie — odśwież i spróbuj ponownie.'


# ── Pomocnicze ───────────────────────────────────────────────────────────

def _cialo():
    """
    Ciało JSON żądania jako `dict`. Brak ciała → `{}`; ciało NIEPUSTE, które nie
    sparsuje się do obiektu JSON (zły JSON, zły Content-Type, JSON nie-obiektowy:
    lista/tekst/liczba/`null`) → 422.

    (M1, poprawka po przeglądzie) `request.get_json(silent=True)` zwraca `None`
    RÓWNIEŻ dla ciała, które jest śmieciem (zły JSON albo zły Content-Type) —
    nie tylko dla braku ciała. Samo sprawdzenie `dane is None` nie odróżnia tych
    dwóch przypadków, więc `POST /complete` z zepsutym ciałem trafiał w gałąź
    „brak delivered_order_ids = wszystkie dostarczone" zamiast czytelnej odmowy:
    cichy, masowy zapis zamiast błędu wejścia. `request.get_data()` (surowe bajty,
    cachowane — Flask i tak już je przeczytał w `get_json`) rozstrzyga: niepuste
    ciało, które nie sparsowało się do `dict`, zawsze 422.
    """
    dane = request.get_json(silent=True)
    if isinstance(dane, dict):
        return dane
    if not request.get_data(cache=True):
        return {}
    raise LogistykaBlad(u'Nieprawidłowe dane żądania.', status=422)


def _stopy_z_ciala(dane):
    ids = dane.get('order_ids')
    if not isinstance(ids, list) or not ids or len(ids) > LIMIT_HURTU:
        raise LogistykaBlad(u'Podaj od 1 do {} zamówień.'.format(LIMIT_HURTU), status=422)
    return ids


def _odmowa(e):
    """Odmowa serwisu → {success: false, error, …e.dane} (np. `niespakowane` z /complete)."""
    db.session.rollback()
    odpowiedz = dict(e.dane or {})
    odpowiedz.update(success=False, error=e.komunikat)
    return jsonify(odpowiedz), e.status


def _data_z_parametru(nazwa, domyslna=None):
    """
    (M11) Parametr zapytania z datą: tylko RRRR-MM-DD (routes.parsuj_date), pusty → `domyslna`.
    Zły format → ValueError (wołający odpowiada 422). Nigdy nie porównujemy z surowym tekstem
    żądania — DATE w MySQL 8 na nieprawidłowym literale rzuca 1525 (500), SQLite by tego nie
    złapało (R9).
    """
    tekst = request.args.get(nazwa)
    if not tekst:
        return domyslna
    return routes.parsuj_date(tekst)


def _konflikt(komunikat):
    """
    (M6, poprawka po przeglądzie — poprzedni komentarz był błędny) Blokada
    globalna (`routes.zablokuj_trasy`) to PRAWDZIWA blokada MySQL — wiersz
    zablokowany `FOR UPDATE` w `prod_config` — więc serializuje WSZYSTKICH
    piszących trasy, także równoległe procesy robocze gunicorna, nie tylko jeden
    proces. Mimo to łapiemy `IntegrityError` jako ostatnią linię obrony, gdy:
    (a) brakuje wiersza blokady (`zablokuj_trasy` działa wtedy fail-open — patrz
    jej docstring), (b) piszący nie przechodzi przez tę blokadę. W `_akcja`:
    UNIQUE na `prod_route_stops.order_id`, gdy dwie osoby dodają to samo
    zamówienie do dwóch tras naraz. W `route_create`: jedyny realny wyścig to FK
    na pojeździe/kierowcy — stąd inny, ogólny tekst zamiast tego o przystanku.
    """
    db.session.rollback()
    return _blad(komunikat, 409)


def _zamowienia_z_produktami(route, swieze=False):
    """
    (M2, poprawka po przeglądzie) Zamówienia trasy z pozycjami i konfiguracjami
    jednym zapytaniem każde — ten sam eager loading co `lista.pobierz`.
    `routes.zamowienia_trasy` (bez `selectinload`) tu nie wystarcza:
    `podsumowanie`/`lista.serializuj` czytają `order.products` i
    `produkt.configuration` — bez tego każde zamówienie (i każda jego pozycja)
    to osobne, leniwe zapytanie w szczegółach JEDNEJ trasy.
    `swieze` — po commicie (M7): populate_existing, żeby ładowanie zbiorcze wypełniło
    od nowa obiekty wygaszone commitem, zamiast zostawić je leniwym odczytom.
    """
    ids = [s.order_id for s in route.stops]
    if not ids:
        return []
    zapytanie = ProductionOrder.query.options(
        selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration)
    ).filter(ProductionOrder.id.in_(ids))
    if swieze:
        zapytanie = zapytanie.populate_existing()
    po_id = {o.id: o for o in zapytanie.all()}
    return [po_id[i] for i in ids if i in po_id]


def _trasa_ze_szczegolami(route_id, swieze=False):
    """Trasa z przystankami, pojazdem i kierowcą — po jednym zapytaniu na relację."""
    zapytanie = (Route.query
                 .options(selectinload(Route.stops), selectinload(Route.vehicle),
                          selectinload(Route.driver))
                 .filter(Route.id == route_id))
    if swieze:
        zapytanie = zapytanie.populate_existing()
    return zapytanie.one_or_none()


def _przystanki_mapy(zamowienia, punkty, przystanki=None):
    """
    Przystanki trasy dla GET /routes/map — (I5) z numerem wśród aktywnych i flagą anulowanych.
    (U4, oględziny 2.10) `dostarczone` — przystanek z delivered_at (zielona stacja na mapie, jak na osi edytora);
    `przystanki` = {order_id: RouteStop} trasy (już wczytane selectinload — bez dodatkowych zapytań).
    """
    przystanki = przystanki or {}

    def wspolrzedna(order_id, pole):
        punkt = punkty.get(order_id)
        wartosc = getattr(punkt, pole) if punkt is not None else None
        return float(wartosc) if wartosc is not None else None

    def dostarczony(order_id):
        stop = przystanki.get(order_id)
        return bool(stop is not None and stop.delivered_at is not None)

    def niedostarczony(order_id):
        # U10 (Ruling 32): niedostarczony wisi na trasie w drodze do jej końca — szara stacja na mapie.
        stop = przystanki.get(order_id)
        return bool(stop is not None and stop.not_delivered_at is not None)
    return [{'pozycja': numer, 'anulowane': anulowane, 'order_id': o.id,
             'numer': o.internal_order_number, 'klient': o.client_name,
             'lat': wspolrzedna(o.id, 'lat'), 'lng': wspolrzedna(o.id, 'lng'),
             'dostarczone': dostarczony(o.id), 'niedostarczone': niedostarczony(o.id)}
            for o, numer, anulowane in routes.numeracja_przystankow(zamowienia)]


def _wczytaj_trasy(zapytanie, swieze=False):
    """
    (I1, poprawka po przeglądzie) Zbiorcze wczytanie tras do listy/mapy bez
    lawiny zapytań: trasy razem z przystankami/pojazdem/kierowcą (`selectinload`,
    po jednym zapytaniu na każdą relację — nie R tras × S przystanków), zamówienia
    WSZYSTKICH tras jednym zapytaniem z tym samym eager loadingiem co
    `lista.pobierz` (pozycje + konfiguracje), punkty geo jednym zapytaniem. Bez
    tego każda trasa osobno odpytywałaby swoje przystanki/zamówienia/pozycje/geo —
    R × (3 + S) zapytań na jedno żądanie, na synchronicznych workerach gunicorna,
    od których zależą też tablety hali.

    Zwraca `(trasy, zamowienia_wg_trasy, punkty)`; `zamowienia_wg_trasy[route.id]`
    to lista zamówień W KOLEJNOŚCI przystanków tej trasy (przystanek bez
    dopasowanego zamówienia — np. skasowanego w międzyczasie — jest pomijany,
    tak jak w `routes.zamowienia_trasy`). `swieze` — ponowne wczytanie po commicie (M7),
    patrz `_zamowienia_z_produktami`.
    """
    zapytanie = zapytanie.options(selectinload(Route.stops), selectinload(Route.vehicle),
                                  selectinload(Route.driver))
    if swieze:
        zapytanie = zapytanie.populate_existing()
    trasy = zapytanie.all()
    wszystkie_ids = list({s.order_id for trasa in trasy for s in trasa.stops})
    zamowienia_po_id = {}
    if wszystkie_ids:
        zamowienia = ProductionOrder.query.options(
            selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration)
        ).filter(ProductionOrder.id.in_(wszystkie_ids))
        if swieze:
            zamowienia = zamowienia.populate_existing()
        zamowienia_po_id = {o.id: o for o in zamowienia.all()}
    punkty = geocoding.geo_zamowien(wszystkie_ids)
    zamowienia_wg_trasy = {
        trasa.id: [zamowienia_po_id[s.order_id] for s in trasa.stops if s.order_id in zamowienia_po_id]
        for trasa in trasy
    }
    return trasy, zamowienia_wg_trasy, punkty


def _cofniecia_dostarczen(route_id, order_ids):
    """
    (U8, oględziny 2.10) Czas ostatniego „Cofnij dostarczenie” (wpis logu `dostarczenie_cofniete`) zamówień na TEJ
    trasie: {order_id: datetime}. Jedno zapytanie dla całej trasy (MAX po zamówieniu, indeks order_id), zwykły
    odczyt — to tylko widok, bez blokad.
    """
    if not order_ids:
        return {}
    wiersze = db.session.query(LogisticsLog.order_id, func.max(LogisticsLog.created_at)).filter(
        LogisticsLog.order_id.in_(order_ids),
        LogisticsLog.route_id == route_id,
        LogisticsLog.action == 'dostarczenie_cofniete',
    ).group_by(LogisticsLog.order_id).all()
    return {order_id: kiedy for order_id, kiedy in wiersze if kiedy is not None}


def _dostawa_przystanku(stop, cofnieto=None):
    """
    Krok 4.4: dostarczenie i „Zostaje” przystanku dla edytora trasy i okna „Odhacz”. W słowniku zamówienia
    (`zamowienie.dostawa`), bo front buduje listę przystanków z samych zamówień (przystankiWidoczne).
    (U8) `cofnieto` — kiedy ostatnio cofnięto dostarczenie na tej trasie (_cofniecia_dostarczen); przystanek znów
    dostarczony (delivered_at) ma tu null — ślad cofnięcia widać tylko do ponownego dostarczenia.
    """
    if stop is None:
        return {'dostarczono': None, 'zostaje': None, 'cofnieto': None, 'niedostarczono': None}
    zostaje = None
    if stop.stays_reason:
        zostaje = {'powod': stop.stays_reason,
                   'etykieta': dostawa.POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason),
                   'notatka': stop.stays_note}
    # U10 (Ruling 32): przystanek niedostarczony zostaje na trasie w drodze do jej końca.
    niedostarczono = None
    if stop.not_delivered_at is not None:
        niedostarczono = {'powod': stop.not_delivered_reason,
                          'etykieta': dostawa.etykieta_powodu(stop.not_delivered_reason),
                          'notatka': stop.not_delivered_note, 'kiedy': stop.not_delivered_at.isoformat()}
    return {'dostarczono': stop.delivered_at.isoformat() if stop.delivered_at else None, 'zostaje': zostaje,
            'cofnieto': cofnieto.isoformat() if cofnieto and stop.delivered_at is None else None,
            'niedostarczono': niedostarczono}


def _niedostarczone_zdjete(historia):
    """
    U10 (Ruling 32): historia trasy (dostawa.niedostarczone_zdjete) dla edytora — z numerem, klientem i miastem
    zamówienia (zwykły odczyt samych kolumn: zamówienia nie ma już na trasie, to tylko widok).
    """
    ids = [w['order_id'] for w in historia]
    zamowienia = {}
    if ids:
        zamowienia = {i: (numer, klient, miasto) for i, numer, klient, miasto in db.session.query(
            ProductionOrder.id, ProductionOrder.internal_order_number, ProductionOrder.client_name,
            ProductionOrder.delivery_city).filter(ProductionOrder.id.in_(ids))}
    wynik = []
    for w in historia:
        numer, klient, miasto = zamowienia.get(w['order_id'], (None, None, None))
        wynik.append({'order_id': w['order_id'], 'numer': numer, 'klient': klient, 'miasto': miasto,
                      'powod': w['powod'], 'etykieta': w['etykieta'], 'notatka': w['notatka'],
                      'kiedy': w['kiedy'].isoformat()})
    return wynik


def _szczegoly(route, przelicz_wykonana=False):
    """
    Szczegóły trasy dla edytora: podsumowanie, przystanki (I5: `pozycja` = numer wśród
    aktywnych przystanków, None dla anulowanego; `anulowane`), przebieg.
    """
    route_id = route.id
    zamowienia = _zamowienia_z_produktami(route)
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    # (M4, spec 8.2) Trasa WYKONANA jest tylko do odczytu — samo jej obejrzenie
    # nie może przeliczać (i nadpisywać) przebiegu/dystansu/czasu w cache.
    # Wyjątek (oględziny Task 8, M3): odpowiedź POST /complete — odhaczenie właśnie
    # zdjęło niedostarczone przystanki, więc przebieg liczymy raz, dla przystanków,
    # które naprawdę pojechały. Potem trasa znów tylko do odczytu.
    if (route.status != 'wykonana' or przelicz_wykonana) and routing.przelicz(route, punkty):
        db.session.commit()
        # (M7) Commit wygasił wszystko w sesji (expire_on_commit) — serializacja dociągałaby
        # trasę, przystanki, pojazd, kierowcę, zamówienia, pozycje i punkty wiersz po wierszu
        # (dodanie 1 przystanku do trasy z 40 = ~140 zapytań). Te same zapytania zbiorcze od nowa.
        swieza = _trasa_ze_szczegolami(route_id, swieze=True)
        if swieza is not None:
            route = swieza
            zamowienia = _zamowienia_z_produktami(route, swieze=True)
            punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    pakunki = paczki.aktualne_paczki_zamowien([o.id for o in zamowienia])
    historia = dostawa.niedostarczone_zdjete([route])[route.id]
    # Runda 1 U10 (R32.8): do postępu liczą się tylko zdjęte do puli jako niedostarczone (mianownik stały przy zamknięciu).
    dane = routes.serializuj_trase(route, zamowienia, punkty, pakunki,
                                   dostawa.zdjete_do_postepu({route.id: historia})[route.id])
    dane['niedostarczone_zdjete'] = _niedostarczone_zdjete(historia)
    przystanki = {s.order_id: s for s in route.stops}
    cofniecia = _cofniecia_dostarczen(route.id, [s.order_id for s in route.stops if s.delivered_at is None])
    dane['przystanki'] = []
    for o, numer, anulowane in routes.numeracja_przystankow(zamowienia):
        zamowienie = lista.serializuj(o, punkty.get(o.id), route, pakunki.get(o.id, []))
        zamowienie['dostawa'] = _dostawa_przystanku(przystanki.get(o.id), cofniecia.get(o.id))
        dane['przystanki'].append({'pozycja': numer, 'anulowane': anulowane, 'zamowienie': zamowienie})
    dane['przebieg'] = routing.przebieg(route)
    return dane


def _trasa_albo_none(route_id):
    return Route.query.get(route_id)


def _akcja(route_id, funkcja, przelicz_wykonana=False, ponow_po_1213=False, przed=None):
    """
    Wspólny szkielet endpointów zmieniających trasę: 404, gdy jej nie ma; `funkcja`
    (lambda wołająca services/routes.py albo services/dostawa.py) razem z commitem w jednym
    try/except — `LogistykaBlad` (odmowa czytelna dla człowieka, w tym 404 „trasa
    zniknęła w międzyczasie" z routes.zablokuj_trasy) i `IntegrityError` (wyścig o
    UNIQUE, patrz `_konflikt`) obie kończą się bez zmian w bazie. Odpowiedź zawsze
    niesie świeże `route` (przez `_szczegoly`) — `dodaj_przystanki` dokłada `dodane`/
    `bledy` na najwyższy poziom (rozpoznane po kluczu `dodane`), inne funkcje pod
    kluczem `wynik` (np. `complete` → `dostarczone`/`niedostarczone`).
    `przelicz_wykonana` — tylko /complete: jedno przeliczenie przebiegu mimo statusu
    `wykonana` (patrz `_szczegoly`).

    `ponow_po_1213` — akcje Dostawy (odhaczenie, „Cofnij załadunek”, „Cofnij dostarczenie”, „Cofnij zatwierdzenie”,
    od U10 także „Cofnij niedostarczenie” i „Zdejmij z trasy” niedostarczonego;
    fala końcowa 4.4b, B1): blokują pozycje wszystkich zamówień trasy w kolejności (zamówienie, id), więc z pisarzami
    wielu pozycji bez blokady zamówień (priorytety, druk TCP) rzadkie MySQL 1213 jest możliwe. Wtedy jedno ponowienie:
    rollback, porzucenie planu dopychacza Base. z tej próby i cała akcja od nowa (trasa, `funkcja`, commit), decyzja na
    nowym stanie. Drugie 1213 i każdy inny błąd bazy idą dalej do globalnej obsługi (rollback, 500). Ponowienie obejmuje
    tylko `funkcja` i commit — nigdy `_szczegoly` po commicie (zapis już się odbył). `przed` — wołane na początku
    KAŻDEJ próby, przed odczytem trasy (np. `_zapis_pod_blokada` dla „Cofnij zatwierdzenie”: transakcja od nowa tuż
    przed blokadą tras, także w drugiej próbie).
    """
    for proba in (1, 2):
        if przed is not None:
            przed()
        trasa = _trasa_albo_none(route_id)
        if trasa is None:
            return _blad(u'Nie ma takiej trasy.', 404)
        try:
            wynik = funkcja(trasa)
            db.session.commit()
            break
        except LogistykaBlad as e:
            return _odmowa(e)
        except IntegrityError:
            return _konflikt(KOMUNIKAT_KONFLIKT_PRZYSTANKU)
        except OperationalError as e:
            if not ponow_po_1213 or proba == 2 or blokady_zamowien.kod_mysql(e) != 1213:
                raise
            db.session.rollback()
            bl_sync.porzuc_zaplanowane()
            logger.warning('Trasy: zakleszczenie 1213 w akcji Dostawy, ponawiam raz', extra={
                'route_id': route_id, 'endpoint': request.endpoint})
    # Krok 4.4: przejścia Dostawy z panelu (odhaczenie, cofnięcia) zostawiają znaczniki statusów Base. —
    # dopychacz rusza dopiero po udanym commicie (bl_sync.zaplanuj_po_commicie w serwisie).
    bl_sync.wyslij_zaplanowane()
    odpowiedz = {'success': True, 'route': _szczegoly(trasa, przelicz_wykonana)}
    if isinstance(wynik, dict):
        odpowiedz.update(wynik if 'dodane' in wynik else {'wynik': wynik})
    return jsonify(odpowiedz)


# ── Flota ────────────────────────────────────────────────────────────────

@logistics_panel_bp.route('/vehicles', methods=['GET'])
@guard
def vehicles():
    return jsonify({'success': True,
                    'vehicles': fleet.lista_pojazdow(tylko_aktywne=request.args.get('aktywne') == '1')})


@logistics_panel_bp.route('/vehicles', methods=['POST'])
@guard
def vehicle_create():
    try:
        pojazd = fleet.zapisz_pojazd(_cialo())
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)}), 201


@logistics_panel_bp.route('/vehicles/<int:vehicle_id>', methods=['PUT'])
@guard
def vehicle_update(vehicle_id):
    pojazd = Vehicle.query.get(vehicle_id)
    if pojazd is None:
        return _blad(u'Nie ma takiego pojazdu.', 404)
    try:
        dane = dict(fleet.serializuj_pojazd(pojazd), **_cialo())
        fleet.zapisz_pojazd(dane, pojazd)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)})


@logistics_panel_bp.route('/vehicles/<int:vehicle_id>/active', methods=['POST'])
@guard
def vehicle_active(vehicle_id):
    pojazd = Vehicle.query.get(vehicle_id)
    if pojazd is None:
        return _blad(u'Nie ma takiego pojazdu.', 404)
    try:
        aktywny = _cialo().get('active')
        # (R9) `bool(...)` zamieniłoby tekst "false" (prawda dla niepustego
        # napisu) w True — wymagamy WPROST wartości logicznej JSON.
        if not isinstance(aktywny, bool):
            raise LogistykaBlad(u'Pole „active” musi być wartością prawda/fałsz.', status=422)
        fleet.ustaw_aktywnosc(pojazd, aktywny)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'vehicle': fleet.serializuj_pojazd(pojazd)})


@logistics_panel_bp.route('/drivers', methods=['GET'])
@guard
def drivers():
    # (runda 2, spec 2.6) Tylko kierowcy (aktywni, is_driver) z nazwami ich tras aktywnych (robocza,
    # zatwierdzona, załadowana, w trasie) — Flota podaje je w potwierdzeniu zdjęcia znacznika.
    return jsonify({'success': True, 'drivers': fleet.kierowcy_z_trasami()})


@logistics_panel_bp.route('/drivers/candidates', methods=['GET'])
@guard
def driver_candidates():
    return jsonify({'success': True, 'candidates': fleet.kandydaci_na_kierowcow()})


@logistics_panel_bp.route('/drivers', methods=['POST'])
@guard
def driver_add():
    """{worker_id} → {driver, drivers}. Znacznik kierowcy to nie zapis trasy — bez blokady tras."""
    try:
        pracownik = fleet.dodaj_kierowce(_cialo().get('worker_id'))
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'driver': fleet.serializuj_kierowce(pracownik),
                    'drivers': fleet.kierowcy_z_trasami()})


@logistics_panel_bp.route('/drivers/<int:worker_id>', methods=['DELETE'])
@guard
def driver_remove(worker_id):
    """Zdjęcie znacznika → {driver, drivers}; pracownik zostaje, na swoich trasach też."""
    try:
        pracownik = fleet.usun_kierowce(worker_id)
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True, 'driver': fleet.serializuj_kierowce(pracownik),
                    'drivers': fleet.kierowcy_z_trasami()})


@logistics_panel_bp.route('/availability', methods=['GET'])
@guard
def availability():
    try:
        od = routes.parsuj_date(request.args.get('date_from', ''))
        do = routes.parsuj_date(request.args.get('date_to') or request.args.get('date_from', ''))
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    if do < od:
        return _blad(u'Data „do” jest wcześniejsza niż „od”.', 422)
    route_id_surowy = request.args.get('route_id')
    route_id = None
    if route_id_surowy:
        # (M8) `type=int` Werkzeuga po cichu zwraca `None` na złej wartości —
        # `route_id=abc` wyglądałby jak „nie podano", zamiast odmowy.
        try:
            route_id = int(route_id_surowy)
        except ValueError:
            return _blad(u'Nieprawidłowy identyfikator trasy.', 422)
    return jsonify(dict(routes.dostepnosc(od, do, route_id), success=True))


# ── Trasy ────────────────────────────────────────────────────────────────

@logistics_panel_bp.route('/routes', methods=['GET'])
@guard
def routes_list():
    zapytanie = Route.query
    status = request.args.get('status')
    if status:
        if status not in STATUSY_TRASY:
            return _blad(u'Nieznany status trasy.', 422)
        zapytanie = zapytanie.filter(Route.status == status)
    try:
        # (M8) Filtr wyszukiwania wykonanych celowo BEZ granic dat tras (routes.granice_dat)
        # — to przeszukiwanie historii; sprawdzamy tylko format (M11).
        od = _data_z_parametru('od')
        do = _data_z_parametru('do')
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    if od is not None:
        zapytanie = zapytanie.filter(Route.date_to >= od)
    else:
        # (I1, ruling okna domyślnego) Brak `od` → trasy WYKONANE starsze niż
        # DNI_WYKONANYCH_DOMYSLNIE dni znikają z listy; każdy inny status (także
        # załadowana i w trasie) przechodzi zawsze (pierwszy człon OR-a). „Dziś” z routes.dzis() — to samo,
        # które wyznacza granice dat tras.
        granica = routes.dzis() - timedelta(days=DNI_WYKONANYCH_DOMYSLNIE)
        zapytanie = zapytanie.filter(or_(Route.status != 'wykonana', Route.date_to >= granica))
    if do is not None:
        zapytanie = zapytanie.filter(Route.date_from <= do)
    trasy, zamowienia_wg_trasy, punkty = _wczytaj_trasy(zapytanie)
    trasy = sorted(trasy, key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    # Krok 4.4: postęp Dostawy przy każdej trasie — paczki wszystkich tras jednym zapytaniem.
    pakunki = paczki.aktualne_paczki_zamowien(
        [o.id for zamowienia in zamowienia_wg_trasy.values() for o in zamowienia])
    # U10: historia niedostarczonych wszystkich tras listy jednym zapytaniem (postęp „niedostarczono”).
    historia = dostawa.zdjete_do_postepu(dostawa.niedostarczone_zdjete(trasy))
    wynik = [routes.serializuj_trase(trasa, zamowienia_wg_trasy[trasa.id], punkty, pakunki, historia[trasa.id])
             for trasa in trasy]
    return jsonify({'success': True, 'routes': wynik})


@logistics_panel_bp.route('/routes', methods=['POST'])
@guard
def route_create():
    try:
        trasa = routes.utworz(_cialo(), user_id=_user_id())
        db.session.commit()
    except LogistykaBlad as e:
        return _odmowa(e)
    except IntegrityError:
        return _konflikt(KOMUNIKAT_KONFLIKT_TRASY)
    return jsonify({'success': True, 'route': _szczegoly(trasa)}), 201


@logistics_panel_bp.route('/routes/map', methods=['GET'])
@guard
def routes_map():
    """
    (R8, kontroler) Co najwyżej JEDNO przeliczenie przebiegu (routing.przelicz)
    na to żądanie: z kluczem ORS każde przeliczenie to zapytanie HTTP do 8 s,
    a gunicorn ubija żądanie po 30 s — po pętli po wszystkich aktywnych trasach
    kilka nieaktualnych przebiegów naraz (np. zaraz po tym, jak geokoder w tle
    uzupełnił współrzędne wielu zamówieniom) zabiłoby worker PRZED commitem
    pierwszej z nich, więc każde kolejne otwarcie mapy zawieszałoby się od nowa.
    Reszta tras w tym żądaniu wraca z przebiegiem z cache (przeliczy je kolejne
    żądanie) — UI i tak odświeża mapę po każdej zmianie trasy.
    """
    # (M8) Sortowanie po (date_from, id) — nie samym date_from — żeby kolejność
    # (a więc i kolory tras w UI) była stabilna między żądaniami przy remisie dnia.
    zapytanie = Route.query.filter(Route.status.in_(routes.AKTYWNE)).order_by(Route.date_from, Route.id)
    trasy, zamowienia_wg_trasy, punkty = _wczytaj_trasy(zapytanie)   # (I1) ten sam eager loading co lista
    for trasa in trasy:
        if routing.przelicz(trasa, punkty):
            db.session.commit()
            # (M7) Commit wygasił wszystkie trasy, zamówienia i punkty — bez ponownego
            # wczytania serializacja reszty tras szłaby wiersz po wierszu (setki zapytań).
            # R8: po pierwszym przeliczeniu kończymy — reszta przeliczy się w kolejnych żądaniach.
            trasy, zamowienia_wg_trasy, punkty = _wczytaj_trasy(zapytanie, swieze=True)
            break
    wynik = [{
        'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status,
        'date_from': trasa.date_from.isoformat(), 'date_to': trasa.date_to.isoformat(),
        'przebieg': routing.przebieg(trasa), 'przyblizony': bool(trasa.geometry_approx),
        'przystanki': _przystanki_mapy(zamowienia_wg_trasy[trasa.id], punkty, {s.order_id: s for s in trasa.stops}),
    } for trasa in trasy]
    return jsonify({'success': True, 'routes': wynik})


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['GET'])
@guard
def route_get(route_id):
    trasa = _trasa_ze_szczegolami(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        szczegoly = _szczegoly(trasa)
    except (StaleDataError, ObjectDeletedError):
        # (M11) GET zapisuje przebieg (_szczegoly → routing.przelicz → commit) bez blokady
        # tras. Trasa usunięta w tym czasie: UPDATE nie trafia w wiersz (StaleDataError)
        # albo wygaszona po commicie trasa nie ma już wiersza (ObjectDeletedError) — to 404,
        # nie 500.
        db.session.rollback()
        return _blad(u'Nie ma takiej trasy.', 404)
    return jsonify({'success': True, 'route': szczegoly})


@logistics_panel_bp.route('/routes/<int:route_id>/routimo', methods=['GET'])
@guard
def route_routimo(route_id):
    """
    Eksport trasy do Routimo (spec 8.4, Task 7) — tylko do odczytu: żadnej
    blokady trasy (routes.zablokuj_trasy) i żadnego wołania ORS, w przeciwieństwie
    do _szczegoly/routing.przelicz. Dostępny od zatwierdzonej wzwyż: zatwierdzona, załadowana, w trasie i wykonana
    (R11 — przewoźnik może pobrać plik ponownie po zamknięciu trasy); robocza (jeszcze się zmienia) zwraca 409,
    jak reszta operacji na trasie.
    (I5) Przystanki anulowanych zamówień pomijamy; ich liczba idzie w nagłówku
    X-Routimo-Pominiete (zawsze, także 0) — interfejs dopisuje ją do komunikatu po pobraniu.
    """
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    if trasa.status not in ('zatwierdzona', 'zaladowana', 'w_trasie', 'wykonana'):
        return _blad(u'Eksport do Routimo jest dostępny po zatwierdzeniu trasy.', 409)
    wiersze, pominiete = routimo.przygotuj_eksport(trasa)
    odpowiedz = send_file(io.BytesIO(routimo.zbuduj_excel(wiersze)), as_attachment=True,
                          download_name=routimo.nazwa_pliku(trasa),
                          mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    odpowiedz.headers['X-Routimo-Pominiete'] = str(pominiete)
    return odpowiedz


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['PUT'])
@guard
def route_update(route_id):
    return _akcja(route_id, lambda t: routes.edytuj(t, _cialo(), user_id=_user_id()) and None)


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['DELETE'])
@guard
def route_delete(route_id):
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        routes.usun(trasa, user_id=_user_id())
    except LogistykaBlad as e:
        return _odmowa(e)
    db.session.commit()
    return jsonify({'success': True})


@logistics_panel_bp.route('/routes/<int:route_id>/stops', methods=['POST'])
@guard
def route_stops_add(route_id):
    return _akcja(route_id, lambda t: routes.dodaj_przystanki(
        t, _stopy_z_ciala(_cialo()), user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>', methods=['DELETE'])
@guard
def route_stop_remove(route_id, order_id):
    return _akcja(route_id, lambda t: routes.usun_przystanek(t, order_id, user_id=_user_id()) and None)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/order', methods=['PUT'])
@guard
def route_stops_order(route_id):
    # Krok 4.4d: `obecne_order_ids` (opcjonalne) — kolejność, na której oparto nową (okno optymalizacji);
    # inna niż bieżąca → 409 (routes.zmien_kolejnosc).
    return _akcja(route_id, lambda t: routes.zmien_kolejnosc(t, _cialo().get('order_ids') or [],
                                                             oczekiwane=_cialo().get('obecne_order_ids')))


@logistics_panel_bp.route('/routes/<int:route_id>/optimize', methods=['POST'])
@guard
def route_optimize(route_id):
    """
    Podgląd optymalizacji kolejności przystanków trasy roboczej (krok 4.4d, spec 9.9) — ORS Optimization,
    NIC nie zapisuje i nie bierze blokady tras. Zastosowanie: PUT /routes/<id>/stops/order z `order_ids`
    i `obecne_order_ids` z tej odpowiedzi. Odmowy: 404, 409 (status), 422 (mniej niż 2 przystanki z dokładnym
    punktem, za dużo przystanków), 502 (błąd albo limit ORS), 503 (brak klucza ORS).
    """
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        wynik = optymalizacja.zaproponuj(trasa)
    except LogistykaBlad as e:
        return _odmowa(e)
    return jsonify({'success': True, 'optymalizacja': wynik})


@logistics_panel_bp.route('/routes/<int:route_id>/approve', methods=['POST'])
@guard
def route_approve(route_id):
    return _akcja(route_id, lambda t: routes.zatwierdz(t, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/revert', methods=['POST'])
@guard
def route_revert(route_id):
    # Krok 4.4 (Ruling 21b): cofnięcie zatwierdzenia czyści znaczniki załadunku tej trasy
    # (dostawa.cofnij_zatwierdzenie), a sprawdza je zwykłym odczytem — transakcja zaczyna się więc od nowa
    # tuż przed blokadą tras, żeby migawka powstała już pod nią (_zapis_pod_blokada), także w ponowieniu po 1213
    # (`przed` wołane na początku każdej próby). Użytkownik PRZED commitem: po nim current_user.id to zwykły
    # SELECT, czyli migawka sprzed blokady.
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.cofnij_zatwierdzenie(t, user_id=user_id) and None,
                  ponow_po_1213=True, przed=_zapis_pod_blokada)


# Akcje Dostawy w panelu (krok 4.4) ponawiają się raz po MySQL 1213 (_akcja, `ponow_po_1213`). Użytkownika czytamy
# przed pierwszą próbą: po rollbacku current_user.id byłby zwykłym SELECT-em w nowej transakcji.

@logistics_panel_bp.route('/routes/<int:route_id>/unload', methods=['POST'])
@guard
def route_unload(route_id):
    """„Cofnij załadunek” (krok 4.4, spec 4.5 i 9.7): trasa załadowana wraca do zatwierdzonej."""
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.cofnij_zaladunek(t, user_id=user_id) and None, ponow_po_1213=True)


@logistics_panel_bp.route('/routes/<int:route_id>/complete', methods=['POST'])
@guard
def route_complete(route_id):
    # (M6) `delivered_order_ids` wymagane (lista, także pusta) — brak albo null to 422
    # z dostawa.odhacz, nie „wszystko dostarczone”. (I1) 409 z `niespakowane` przechodzi
    # przez _akcja → _odmowa razem z pozostałymi polami odmowy. Krok 4.4: odhaczenie wysyła statusy Base.
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.odhacz(
        t, _cialo().get('delivered_order_ids'), user_id=user_id), przelicz_wykonana=True, ponow_po_1213=True)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-delivered', methods=['POST'])
@guard
def route_stop_undo_delivered(route_id, order_id):
    """„Cofnij dostarczenie” przy przystanku (krok 4.4, spec 4.5 i 9.7) — zastępuje „Przywróć trasę”."""
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.cofnij_dostarczenie(t, order_id, user_id=user_id) and None,
                  ponow_po_1213=True)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-not-delivered', methods=['POST'])
@guard
def route_stop_undo_not_delivered(route_id, order_id):
    """„Cofnij niedostarczenie” przy przystanku trasy w drodze (U10, Ruling 32) — symetrycznie do „Cofnij
    dostarczenie”; przystanek, który nie jest niedostarczony — bez zmian."""
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.cofnij_niedostarczenie(t, order_id, user_id=user_id) and None,
                  ponow_po_1213=True)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>/remove-not-delivered', methods=['POST'])
@guard
def route_stop_remove_not_delivered(route_id, order_id):
    """„Zdejmij z trasy” niedostarczony przystanek trasy w drodze (U10, Ruling 32): zamówienie od razu wraca do puli
    bez trasy (Base. 417343 po commicie), historia zostaje."""
    user_id = _user_id()
    return _akcja(route_id, lambda t: dostawa.zdejmij_niedostarczone(t, order_id, user_id=user_id) and None,
                  ponow_po_1213=True)
