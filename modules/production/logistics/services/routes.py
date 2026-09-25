# -*- coding: utf-8 -*-
"""
Trasy transportu własnego (spec, sekcja 8.2).

Statusy: robocza (pełna edycja) → zatwierdzona (zablokowana, eksport Routimo)
→ wykonana (tylko odczyt; przywracana do zatwierdzonej). Funkcje NIE commitują.
Każda zmiana widoczna na tablecie podbija updated_at pozycji zamówień
(ETag kolejek tabletów — spec 6.5).
"""
from datetime import date

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import Route, RouteStop, STATUSY_TRASY_AKTYWNE, Vehicle
from modules.production.logistics.services import delivery, fleet
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker, get_local_now

# Ta sama wartość, co stała modelu (Task 1) — trasy, które widzi tablet i które
# blokują pojazd/kierowcę. Import zamiast drugiej literalnej krotki: jedno miejsce
# prawdy o tym, co znaczy "aktywna trasa".
AKTYWNE = STATUSY_TRASY_AKTYWNE
WAGA_KG_NA_M3 = 800
MAKS_NAZWA = 120


# ── Pomocnicze ─────────────────────────────────────────────────────────────

def _data(wartosc, pole):
    if isinstance(wartosc, date):
        return wartosc
    try:
        return date.fromisoformat(str(wartosc))
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Pole „{}”: podaj datę RRRR-MM-DD.'.format(pole), status=422)


def _id(wartosc, pole):
    if wartosc in (None, '', 0, '0'):
        return None
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Pole „{}”: nieprawidłowa wartość.'.format(pole), status=422)


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

def zajetosc(date_from, date_to, pomin_route_id=None):
    zapytanie = Route.query.filter(Route.status.in_(AKTYWNE),
                                   Route.date_from <= date_to, Route.date_to >= date_from)
    if pomin_route_id:
        zapytanie = zapytanie.filter(Route.id != pomin_route_id)
    pojazdy, kierowcy = {}, {}
    for trasa in zapytanie.order_by(Route.date_from).all():
        if trasa.vehicle_id:
            pojazdy.setdefault(trasa.vehicle_id, trasa.name)
        if trasa.driver_worker_id:
            kierowcy.setdefault(trasa.driver_worker_id, trasa.name)
    return {'pojazdy': pojazdy, 'kierowcy': kierowcy}


def dostepnosc(date_from, date_to, pomin_route_id=None):
    z = zajetosc(date_from, date_to, pomin_route_id)
    return {
        'pojazdy': [dict(p, zajety=p['id'] in z['pojazdy'], trasa=z['pojazdy'].get(p['id']))
                    for p in fleet.lista_pojazdow(tylko_aktywne=True)],
        'kierowcy': [dict(k, zajety=k['id'] in z['kierowcy'], trasa=z['kierowcy'].get(k['id']))
                     for k in fleet.kierowcy()],
    }


def _sprawdz_zasoby(od, do, vehicle_id, driver_id, pomin_route_id=None):
    if vehicle_id:
        # FOR UPDATE na wierszu pojazdu serializuje dwa równoległe zapisy tras (MySQL);
        # SQLite go ignoruje, testy jadą sekwencyjnie.
        pojazd = Vehicle.query.with_for_update().filter_by(id=vehicle_id).first()
        if pojazd is None:
            raise LogistykaBlad(u'Nie ma takiego pojazdu.', status=422)
        if not pojazd.is_active:
            raise LogistykaBlad(u'Pojazd „{}” jest wyłączony z floty.'.format(pojazd.name), status=422)
    if driver_id:
        kierowca = ProductionWorker.query.get(driver_id)
        if kierowca is None or not kierowca.is_active:
            raise LogistykaBlad(u'Nie ma takiego aktywnego kierowcy.', status=422)
    z = zajetosc(od, do, pomin_route_id)
    if vehicle_id and vehicle_id in z['pojazdy']:
        raise LogistykaBlad(u'Pojazd jest zajęty na trasie „{}” w tych dniach.'.format(
            z['pojazdy'][vehicle_id]))
    if driver_id and driver_id in z['kierowcy']:
        raise LogistykaBlad(u'Kierowca jest zajęty na trasie „{}” w tych dniach.'.format(
            z['kierowcy'][driver_id]))


def _dane_trasy(dane):
    nazwa = (dane.get('name') or '').strip()
    if not nazwa or len(nazwa) > MAKS_NAZWA:
        raise LogistykaBlad(u'Podaj nazwę trasy (do {} znaków).'.format(MAKS_NAZWA), status=422)
    od = _data(dane.get('date_from'), u'data od')
    do = _data(dane.get('date_to') or dane.get('date_from'), u'data do')
    if do < od:
        raise LogistykaBlad(u'Data „do” jest wcześniejsza niż „od”.', status=422)
    notatka = (dane.get('notes') or '').strip() or None
    return (nazwa, od, do, _id(dane.get('vehicle_id'), u'pojazd'),
            _id(dane.get('driver_worker_id'), u'kierowca'), notatka)


# ── Tworzenie i edycja ────────────────────────────────────────────────────

def utworz(dane, user_id=None):
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

def przystanek_zamowienia(order_id):
    return RouteStop.query.filter_by(order_id=order_id).first()


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
    db.session.flush()
    db.session.expire(route, ['stops'])
    for pozycja, przystanek in enumerate(route.stops, start=1):
        przystanek.position = pozycja


def dodaj_przystanki(route, order_ids, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    order_ids = _lista_id(order_ids)
    teraz = get_local_now()
    unikalne = list(dict.fromkeys(order_ids))
    zamowienia = {o.id: o for o in
                  ProductionOrder.query.filter(ProductionOrder.id.in_(unikalne)).all()}
    pozycja = max([s.position for s in route.stops] or [0])
    dodane, bledy = [], []
    for order_id in unikalne:
        order = zamowienia.get(order_id)
        if order is None:
            bledy.append({'order_id': order_id, 'komunikat': u'Nie ma takiego zamówienia.'})
            continue
        numer = order.internal_order_number
        if sposoby.normalizuj(order.override_delivery_method) != sposoby.TRANSPORT:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} nie ma ustawionego transportu własnego.'.format(numer)})
            continue
        if order.logistics_closed_at is not None:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest zamknięte w logistyce.'.format(numer)})
            continue
        inny = przystanek_zamowienia(order_id)
        if inny is not None:
            bledy.append({'order_id': order_id, 'komunikat':
                          u'Zamówienie {} jest już na trasie „{}”.'.format(numer, inny.route.name)})
            continue
        pozycja += 1
        db.session.add(RouteStop(route_id=route.id, order_id=order_id, position=pozycja))
        db.session.flush()
        delivery.zapisz_log(order, 'trasa_dodane', None, route.name[:64], user_id=user_id,
                            route_id=route.id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        dodane.append(order_id)
    db.session.expire(route, ['stops'])
    return {'dodane': dodane, 'bledy': bledy}


def usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True):
    if wymagaj_roboczej:
        _wymagaj_statusu(route, 'robocza')
    przystanek = RouteStop.query.filter_by(route_id=route.id, order_id=order_id).first()
    if przystanek is None:
        raise LogistykaBlad(u'Tego zamówienia nie ma na trasie „{}”.'.format(route.name), status=404)
    order = ProductionOrder.query.get(order_id)
    db.session.delete(przystanek)
    _przenumeruj(route)
    teraz = get_local_now()
    delivery.zapisz_log(order, 'trasa_usuniete', route.name[:64], None, user_id=user_id,
                        note=note, route_id=route.id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return order


def zmien_kolejnosc(route, order_ids):
    _wymagaj_statusu(route, 'robocza')
    nowe = _lista_id(order_ids)
    obecne = {s.order_id: s for s in route.stops}
    if len(nowe) != len(obecne) or set(nowe) != set(obecne):
        raise LogistykaBlad(u'Kolejność musi zawierać dokładnie przystanki tej trasy.', status=422)
    for pozycja, order_id in enumerate(nowe, start=1):
        obecne[order_id].position = pozycja
    db.session.flush()
    db.session.expire(route, ['stops'])


# ── Statusy ───────────────────────────────────────────────────────────────

def zatwierdz(route, user_id=None):
    _wymagaj_statusu(route, 'robocza')
    if not route.stops:
        raise LogistykaBlad(u'Trasa bez przystanków nie może być zatwierdzona.', status=422)
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'zatwierdzona', teraz, user_id
    _log_statusu(route, 'robocza', 'zatwierdzona', user_id, teraz)
    _podbij_trase(route, teraz)


def cofnij_do_roboczej(route, user_id=None):
    _wymagaj_statusu(route, 'zatwierdzona')
    teraz = get_local_now()
    route.status, route.approved_at, route.approved_by = 'robocza', None, None
    _log_statusu(route, 'zatwierdzona', 'robocza', user_id, teraz)
    _podbij_trase(route, teraz)


def wykonaj(route, dostarczone_ids=None, user_id=None):
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
