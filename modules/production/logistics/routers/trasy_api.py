# -*- coding: utf-8 -*-
"""
API tras, floty i dostępności — /production/api/logistics/* (etap 3).

Eksport do Routimo: `GET /routes/<id>/routimo` (Task 7) — formatowanie w
modules/production/logistics/services/routimo.py, wspólne z eksportem
zakładki Raporty (modules/reports/routers.generate_routimo_excel).
"""
import io
from datetime import date, timedelta

from flask import jsonify, request, send_file
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.models import Route, STATUSY_TRASY, Vehicle
from modules.production.logistics.routers.panel_api import LIMIT_HURTU, _blad, _user_id, guard
from modules.production.logistics.services import fleet, geocoding, lista, routes, routimo, routing
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionProduct, get_local_now

KOLEJNOSC_STATUSOW = {'robocza': 0, 'zatwierdzona': 1, 'wykonana': 2}
# (I1, ruling okna domyślnego) Bez jawnego `od` GET /routes ciągnąłby WSZYSTKIE
# trasy w historii firmy — trasy WYKONANE (zamknięty, archiwalny stan) starsze
# niż tyle dni znikają z domyślnego widoku; robocza/zatwierdzona NIGDY nie są
# tym oknem przycinane (to bieżąca praca logistyki).
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
    db.session.rollback()
    return _blad(e.komunikat, e.status)


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


def _zamowienia_z_produktami(route):
    """
    (M2, poprawka po przeglądzie) Zamówienia trasy z pozycjami i konfiguracjami
    jednym zapytaniem każde — ten sam eager loading co `lista.pobierz`.
    `routes.zamowienia_trasy` (bez `selectinload`) tu nie wystarcza:
    `podsumowanie`/`lista.serializuj` czytają `order.products` i
    `produkt.configuration` — bez tego każde zamówienie (i każda jego pozycja)
    to osobne, leniwe zapytanie w szczegółach JEDNEJ trasy.
    """
    ids = [s.order_id for s in route.stops]
    if not ids:
        return []
    po_id = {o.id: o for o in ProductionOrder.query.options(
        selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration)
    ).filter(ProductionOrder.id.in_(ids)).all()}
    return [po_id[i] for i in ids if i in po_id]


def _wczytaj_trasy(zapytanie):
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
    tak jak w `routes.zamowienia_trasy`).
    """
    trasy = (zapytanie
            .options(selectinload(Route.stops), selectinload(Route.vehicle),
                     selectinload(Route.driver))
            .all())
    wszystkie_ids = list({s.order_id for trasa in trasy for s in trasa.stops})
    zamowienia_po_id = {}
    if wszystkie_ids:
        zamowienia_po_id = {o.id: o for o in ProductionOrder.query.options(
            selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration)
        ).filter(ProductionOrder.id.in_(wszystkie_ids)).all()}
    punkty = geocoding.geo_zamowien(wszystkie_ids)
    zamowienia_wg_trasy = {
        trasa.id: [zamowienia_po_id[s.order_id] for s in trasa.stops if s.order_id in zamowienia_po_id]
        for trasa in trasy
    }
    return trasy, zamowienia_wg_trasy, punkty


def _szczegoly(route, przelicz_wykonana=False):
    zamowienia = _zamowienia_z_produktami(route)
    punkty = geocoding.geo_zamowien([o.id for o in zamowienia])
    # (M4, spec 8.2) Trasa WYKONANA jest tylko do odczytu — samo jej obejrzenie
    # nie może przeliczać (i nadpisywać) przebiegu/dystansu/czasu w cache.
    # Wyjątek (oględziny Task 8, M3): odpowiedź POST /complete — odhaczenie właśnie
    # zdjęło niedostarczone przystanki, więc przebieg liczymy raz, dla przystanków,
    # które naprawdę pojechały. Potem trasa znów tylko do odczytu.
    if (route.status != 'wykonana' or przelicz_wykonana) and routing.przelicz(route, punkty):
        db.session.commit()
    dane = routes.serializuj_trase(route, zamowienia, punkty)
    dane['przystanki'] = [{'pozycja': i, 'zamowienie': lista.serializuj(o, punkty.get(o.id), route)}
                          for i, o in enumerate(zamowienia, start=1)]
    dane['przebieg'] = routing.przebieg(route)
    return dane


def _trasa_albo_none(route_id):
    return Route.query.get(route_id)


def _akcja(route_id, funkcja, przelicz_wykonana=False):
    """
    Wspólny szkielet endpointów zmieniających trasę: 404, gdy jej nie ma; `funkcja`
    (zwykle lambda wołająca services/routes.py) razem z commitem w jednym
    try/except — `LogistykaBlad` (odmowa czytelna dla człowieka, w tym 404 „trasa
    zniknęła w międzyczasie" z routes.zablokuj_trasy) i `IntegrityError` (wyścig o
    UNIQUE, patrz `_konflikt`) obie kończą się bez zmian w bazie. Odpowiedź zawsze
    niesie świeże `route` (przez `_szczegoly`) — `dodaj_przystanki` dokłada `dodane`/
    `bledy` na najwyższy poziom (rozpoznane po kluczu `dodane`), inne funkcje pod
    kluczem `wynik` (np. `complete` → `dostarczone`/`niedostarczone`).
    `przelicz_wykonana` — tylko /complete: jedno przeliczenie przebiegu mimo statusu
    `wykonana` (patrz `_szczegoly`).
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
        return _konflikt(KOMUNIKAT_KONFLIKT_PRZYSTANKU)
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
        # (R9) Zawsze porównujemy z sparsowanym `date`, nigdy z surowym tekstem
        # żądania — DATE w MySQL 8 na nieprawidłowym literale rzuca 1525 (500),
        # SQLite testów by tego nie złapało.
        od = date.fromisoformat(request.args['od']) if request.args.get('od') else None
        do = date.fromisoformat(request.args['do']) if request.args.get('do') else None
    except ValueError:
        return _blad(u'Podaj daty RRRR-MM-DD.', 422)
    if od is not None:
        zapytanie = zapytanie.filter(Route.date_to >= od)
    else:
        # (I1, ruling okna domyślnego) Brak `od` → trasy WYKONANE starsze niż
        # DNI_WYKONANYCH_DOMYSLNIE dni znikają z listy; robocza/zatwierdzona
        # przechodzą zawsze (pierwszy człon OR-a).
        granica = get_local_now().date() - timedelta(days=DNI_WYKONANYCH_DOMYSLNIE)
        zapytanie = zapytanie.filter(or_(Route.status != 'wykonana', Route.date_to >= granica))
    if do is not None:
        zapytanie = zapytanie.filter(Route.date_from <= do)
    trasy, zamowienia_wg_trasy, punkty = _wczytaj_trasy(zapytanie)
    trasy = sorted(trasy, key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    wynik = [routes.serializuj_trase(trasa, zamowienia_wg_trasy[trasa.id], punkty) for trasa in trasy]
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
    wynik = []
    przeliczono = False
    for trasa in trasy:
        zamowienia = zamowienia_wg_trasy[trasa.id]
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


@logistics_panel_bp.route('/routes/<int:route_id>/routimo', methods=['GET'])
@guard
def route_routimo(route_id):
    """
    Eksport trasy do Routimo (spec 8.4, Task 7) — tylko do odczytu: żadnej
    blokady trasy (routes.zablokuj_trasy) i żadnego wołania ORS, w przeciwieństwie
    do _szczegoly/routing.przelicz. Dostępny dla trasy zatwierdzonej ORAZ wykonanej
    (R11, kontroler) — przewoźnik może pobrać plik ponownie już po zamknięciu trasy;
    robocza (jeszcze się zmienia) zwraca 409, jak reszta operacji na trasie.
    """
    trasa = _trasa_albo_none(route_id)
    if trasa is None:
        return _blad(u'Nie ma takiej trasy.', 404)
    if trasa.status not in ('zatwierdzona', 'wykonana'):
        return _blad(u'Eksport do Routimo jest dostępny po zatwierdzeniu trasy.', 409)
    tresc = routimo.zbuduj_excel(routimo.wiersze_trasy(trasa))
    return send_file(io.BytesIO(tresc), as_attachment=True,
                     download_name=routimo.nazwa_pliku(trasa),
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


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
        t, _cialo().get('delivered_order_ids'), user_id=_user_id()), przelicz_wykonana=True)


@logistics_panel_bp.route('/routes/<int:route_id>/restore', methods=['POST'])
@guard
def route_restore(route_id):
    return _akcja(route_id, lambda t: routes.przywroc(t, user_id=_user_id()))
