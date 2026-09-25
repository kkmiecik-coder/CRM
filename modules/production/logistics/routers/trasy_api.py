# -*- coding: utf-8 -*-
"""
API tras, floty i dostępności — /production/api/logistics/* (etap 3).

Eksport do Routimo (`GET /routes/<id>/routimo`) NIE jest tu — dochodzi w Task 7
(R2, kontroler): dodanie go teraz jako 501 tylko po to, by go zastąpić w kolejnym
zadaniu, jest zbędnym krokiem pośrednim.
"""
from datetime import date

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.models import Route, STATUSY_TRASY, Vehicle
from modules.production.logistics.routers.panel_api import _blad, _user_id, guard
from modules.production.logistics.services import fleet, geocoding, lista, routes, routing
from modules.production.logistics.services.delivery import LogistykaBlad

KOLEJNOSC_STATUSOW = {'robocza': 0, 'zatwierdzona': 1, 'wykonana': 2}
# Jak panel_api.LIMIT_HURTU (etap 2) — ta sama wartość, osobna stała: routery nie
# dzielą między sobą stanu ani stałych.
LIMIT_HURTU = 500
KOMUNIKAT_KONFLIKT = (u'Zamówienie trafiło w międzyczasie na inną trasę — '
                     u'odśwież listę i spróbuj ponownie.')


# ── Pomocnicze ───────────────────────────────────────────────────────────

def _cialo():
    """
    Ciało JSON żądania jako `dict`. Brak ciała (albo `null`) liczy się jak pusty
    obiekt — ten sam wzorzec co `request.get_json(silent=True) or {}` w
    panel_api.py. Cokolwiek innego niż obiekt (lista, tekst, liczba) odrzucamy
    TU, jedną wspólną funkcją — bez niej każdy z wielu endpointów tego routera,
    które czytają ciało, powtarzałby ten sam warunek osobno (R9), a `.get()`
    gołej listy/liczby niżej rzuciłby AttributeError (500) zamiast czytelnej
    odmowy.
    """
    dane = request.get_json(silent=True)
    if dane is None:
        return {}
    if not isinstance(dane, dict):
        raise LogistykaBlad(u'Nieprawidłowe dane żądania.', status=422)
    return dane


def _stopy_z_ciala(dane):
    ids = dane.get('order_ids')
    if not isinstance(ids, list) or not ids or len(ids) > LIMIT_HURTU:
        raise LogistykaBlad(u'Podaj od 1 do {} zamówień.'.format(LIMIT_HURTU), status=422)
    return ids


def _odmowa(e):
    db.session.rollback()
    return _blad(e.komunikat, e.status)


def _konflikt():
    # (R9) UNIQUE na prod_route_stops.order_id jako ostatnia linia obrony, gdy
    # dwie osoby jednocześnie dodają to samo zamówienie do dwóch różnych tras —
    # blokada globalna (routes.zablokuj_trasy) serializuje zapisy JEDNEGO procesu,
    # ale gunicorn ma kilka procesów roboczych, każdy z własną blokadą MySQL.
    db.session.rollback()
    return _blad(KOMUNIKAT_KONFLIKT, 409)


def _szczegoly(route):
    zamowienia = routes.zamowienia_trasy(route)
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    if routing.przelicz(route, punkty):
        db.session.commit()
    dane = routes.serializuj_trase(route, zamowienia, punkty)
    dane['przystanki'] = [{'pozycja': i, 'zamowienie': lista.serializuj(o, punkty.get(o.id), route)}
                          for i, o in enumerate(zamowienia, start=1)]
    dane['przebieg'] = routing.przebieg(route)
    return dane


def _trasa_albo_none(route_id):
    return Route.query.get(route_id)


def _akcja(route_id, funkcja):
    """
    Wspólny szkielet endpointów zmieniających trasę: 404, gdy jej nie ma; `funkcja`
    (zwykle lambda wołająca services/routes.py) razem z commitem w jednym
    try/except — `LogistykaBlad` (odmowa czytelna dla człowieka, w tym 404 „trasa
    zniknęła w międzyczasie" z routes.zablokuj_trasy) i `IntegrityError` (wyścig o
    UNIQUE, patrz `_konflikt`) obie kończą się bez zmian w bazie. Odpowiedź zawsze
    niesie świeże `route` (przez `_szczegoly`) — `dodaj_przystanki` dokłada `dodane`/
    `bledy` na najwyższy poziom (rozpoznane po kluczu `dodane`), inne funkcje pod
    kluczem `wynik` (np. `complete` → `dostarczone`/`niedostarczone`).
    """
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    try:
        wynik = funkcja(trasa)
        db.session.commit()
    except LogistykaBlad as e:
        return _odmowa(e)
    except IntegrityError:
        return _konflikt()
    odpowiedz = {'success': True, 'route': _szczegoly(trasa)}
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
    return jsonify({'success': True, 'drivers': fleet.kierowcy()})


@logistics_panel_bp.route('/availability', methods=['GET'])
@guard
def availability():
    try:
        od = date.fromisoformat(request.args.get('date_from', ''))
        do = date.fromisoformat(request.args.get('date_to') or request.args.get('date_from', ''))
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    if do < od:
        return _blad(u'Data „do” jest wcześniejsza niż „od”.', 422)
    route_id = request.args.get('route_id', type=int)
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
        # (R9) Zawsze porównujemy z sparsowanym `date`, nigdy z surowym tekstem
        # żądania — DATE w MySQL 8 na nieprawidłowym literale rzuca 1525 (500),
        # SQLite testów by tego nie złapało.
        if request.args.get('od'):
            zapytanie = zapytanie.filter(Route.date_to >= date.fromisoformat(request.args['od']))
        if request.args.get('do'):
            zapytanie = zapytanie.filter(Route.date_from <= date.fromisoformat(request.args['do']))
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    trasy = sorted(zapytanie.all(), key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    wynik = []
    for trasa in trasy:
        zamowienia = routes.zamowienia_trasy(trasa)
        wynik.append(routes.serializuj_trase(
            trasa, zamowienia, geocoding.geo_zamowien([o.id for o in zamowienia])))
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
        return _konflikt()
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
    wynik = []
    przeliczono = False
    aktywne = Route.query.filter(Route.status.in_(routes.AKTYWNE)).order_by(Route.date_from).all()
    for trasa in aktywne:
        zamowienia = routes.zamowienia_trasy(trasa)
        punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
        if not przeliczono and routing.przelicz(trasa, punkty):
            przeliczono = True
            db.session.commit()
        wynik.append({
            'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status,
            'date_from': trasa.date_from.isoformat(), 'date_to': trasa.date_to.isoformat(),
            'przebieg': routing.przebieg(trasa), 'przyblizony': bool(trasa.geometry_approx),
            'przystanki': [{'pozycja': i, 'order_id': o.id, 'numer': o.internal_order_number,
                            'klient': o.client_name,
                            'lat': float(punkty[o.id].lat)
                                  if punkty.get(o.id) and punkty[o.id].lat is not None else None,
                            'lng': float(punkty[o.id].lng)
                                  if punkty.get(o.id) and punkty[o.id].lng is not None else None}
                           for i, o in enumerate(zamowienia, start=1)],
        })
    return jsonify({'success': True, 'routes': wynik})


@logistics_panel_bp.route('/routes/<int:route_id>', methods=['GET'])
@guard
def route_get(route_id):
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    return jsonify({'success': True, 'route': _szczegoly(trasa)})


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
    return _akcja(route_id, lambda t: routes.zmien_kolejnosc(t, _cialo().get('order_ids') or []))


@logistics_panel_bp.route('/routes/<int:route_id>/approve', methods=['POST'])
@guard
def route_approve(route_id):
    return _akcja(route_id, lambda t: routes.zatwierdz(t, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/revert', methods=['POST'])
@guard
def route_revert(route_id):
    return _akcja(route_id, lambda t: routes.cofnij_do_roboczej(t, user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/complete', methods=['POST'])
@guard
def route_complete(route_id):
    return _akcja(route_id, lambda t: routes.wykonaj(
        t, _cialo().get('delivered_order_ids'), user_id=_user_id()))


@logistics_panel_bp.route('/routes/<int:route_id>/restore', methods=['POST'])
@guard
def route_restore(route_id):
    return _akcja(route_id, lambda t: routes.przywroc(t, user_id=_user_id()))
