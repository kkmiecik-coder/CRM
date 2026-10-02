# -*- coding: utf-8 -*-
"""
API telefonu kierowcy — /api/mobile/delivery/* (logistyka etap 4, krok 4.4, spec 9; kontrakt w planie 4.4b).

Reużywa autoryzację i idempotencję API mobilnego produkcji (require_device_token, with_idempotency). Każde żądanie
ma kierowcę: pierwszy identyfikator z X-Worker-Ids, aktywny pracownik ze znacznikiem is_driver. Lista „Moje trasy”
(GET /routes) zawiera tylko trasy zalogowanego kierowcy; szczegóły trasy (GET /routes/<id>) widzi i zapisy na niej
robi każdy aktywny kierowca (decyzja Konrada 5 — zastępstwo załatwia zmiana kierowcy w panelu, appka pokazuje tylko
trasy zalogowanego, a serwerowi przyjmowanie cudzych nie szkodzi). Handlery zapisu NIE commitują — robi to dekorator idempotencji; 400/403/404/409 nie są zapamiętywane
(BLEDY_DO_PONOWIENIA), 422 jest. Dopychacz Base. rusza dopiero po commicie (serwis tylko planuje:
bl_sync.zaplanuj_po_commicie; dekorator woła wyslij_zaplanowane). Kolejność blokad zapisu: pracownicy
(touch_sessions w _kierowca) → dostawa.zablokuj (trasy → deklaracje paczek → zamówienia trasy rosnąco → paczki →
pozycje). Zakleszczenie MySQL 1213 — jedno ponowienie całego zapisu w handlerze (_zapis).

Każda odpowiedź 200 zapisu — także `changed: false` (powtórka z kolejki offline, Ruling 23 i 26) — niesie pełną trasę
(`route`, ten sam kształt co GET) i `message`: appka podmienia swoją trasę na tę z odpowiedzi.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics.models import Route
from modules.production.logistics.services import bl_sync, dostawa, dostawa_widok, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA
from modules.production.services import blokady_zamowien, worker_service
from modules.production.services.mobile_api_service import require_device_token, with_idempotency
from modules.production.services.station_catalog import resolve_station_code
from modules.production.services.worker_service import WorkerError
from modules.production.utils.cache import cached_json, if_none_match, make_weak_etag, no_store_json, not_modified

logger = get_structured_logger('production.logistics.dostawa_api')

dostawa_mobile_bp = Blueprint('dostawa_mobile', __name__)

# Wersja KSZTAŁTU odpowiedzi trasy — część ETagu (jak KSZTALT_LISTY Weryfikacji).
# PODBIJ przy każdej zmianie zestawu pól w dostawa_widok.serializuj().
#   1 — 2026-10-01: pierwsza wersja (krok 4.4)
#   2 — 2026-10-02: U10 (Ruling 32) — stan przystanku 'niedostarczone', `not_delivered`, `stops_not_delivered`,
#       `removed_not_delivered`
KSZTALT_TRASY = 2
# Dopisek komunikatu, gdy zapis zamknął trasę z niedostarczonymi (U10: schodzą wtedy do puli).
TRASA_ZAKONCZONA = u' Trasa zakończona — niedostarczone wracają do puli bez trasy.'


def wymaga_dostawy(f):
    """Urządzenie zarejestrowane na stanowisku Dostawa — kolumna `station_code` urządzenia z bazy (g.device
    z require_device_token), nie wartość z tokenu; jak Weryfikacja."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if resolve_station_code((g.device.station_code or '').strip()) != dostawa.STANOWISKO:
            return jsonify({'error': 'station_not_allowed',
                            'message': u'To urządzenie nie jest zarejestrowane na stanowisku Dostawa.'}), 403
        return f(*args, **kwargs)
    return wrapper


def _nie_kierowca():
    return jsonify({'error': 'not_a_driver',
                    'message': u'Ten pracownik nie jest aktywnym kierowcą (Flota → Kierowcy).'}), 403


def _kierowca(dotknij=True):
    """
    (kierowca, None) albo (None, odpowiedź). Pierwszy identyfikator z X-Worker-Ids = kierowca (spec 9.1). Brak
    nagłówka → 400 worker_required; nieznany identyfikator albo zły nagłówek → kody WorkerError jak w `complete`;
    bez znacznika kierowcy albo nieaktywny → 403 not_a_driver (kontrakt API Dostawy — także nieaktywny, a nie
    409 worker_inactive). 400, 403 i 404 są w BLEDY_DO_PONOWIENIA: akcja zostaje w kolejce offline, appka wraca na
    wybór kierowcy. `dotknij` — zapis odświeża sesje pracowników (pierwsze blokady transakcji); odczyt nie.
    """
    try:
        ids = worker_service.resolve_worker_ids(request.headers.get('X-Worker-Ids'), required=False)
    except WorkerError as e:
        if e.error_code == 'worker_inactive':
            # Appka Dostawy wysyła jeden identyfikator — kierowcę — więc nieaktywny z nagłówka to on (kontrakt:
            # 403 not_a_driver). Przy kilku identyfikatorach dotyczyłoby to każdego nieaktywnego z listy.
            return None, _nie_kierowca()
        payload, status = e.as_response()
        return None, (jsonify(payload), status)
    if not ids:
        return None, (jsonify({'error': 'worker_required',
                               'message': u'Wybierz kierowcę — Dostawa zapisuje, kto ładował i dostarczył.'}), 400)
    kierowca = ProductionWorker.query.get(ids[0])
    if kierowca is None or not kierowca.is_driver or not kierowca.is_active:
        return None, _nie_kierowca()
    g.worker_ids = ids   # audyt zmian statusu pozycji (product_events.current_actor)
    if dotknij:
        worker_service.touch_sessions(ids, device_id=g.device.device_id)
    return kierowca, None


def _brak_trasy():
    return jsonify({'error': 'route_not_found', 'message': u'Nie ma takiej trasy.'}), 404


def _blad(e):
    """Odmowa serwisu → {error, message, …dane}. Odmowy Dostawy mają kod (DostawaBlad); LogistykaBlad bez kodu
    (zabezpieczenie — żadna odmowa nie może wyjść jako 500) dostaje kod według statusu HTTP."""
    kod = getattr(e, 'kod', None) or {404: 'route_not_found', 422: 'invalid_request'}.get(e.status, 'route_status')
    odpowiedz = dict(e.dane or {})
    odpowiedz.update(error=kod, message=e.komunikat)
    return jsonify(odpowiedz), e.status


def _dane_json():
    """Ciało JSON jako słownik; brak, zły JSON albo inny typ niż obiekt → pusty słownik (pola są opcjonalne)."""
    dane = request.get_json(silent=True)
    return dane if isinstance(dane, dict) else {}


def _numer(order_id):
    """
    Numer wewnętrzny zamówienia do komunikatu. Wołać PRZED akcją serwisu: kolumna się nie zmienia, więc zwykły
    odczyt wystarczy, a po blokadach zapis nie czyta już stanu zwykłym SELECT-em (Ruling P2 — zamówienie, którego
    po powrocie z serwisu nikt nie trzyma, czytane byłoby od nowa z migawki).
    """
    order = ProductionOrder.query.get(order_id)
    return (order.internal_order_number or u'#{}'.format(order_id)) if order is not None else u'#{}'.format(order_id)


def _zapis(route_id, akcja):
    """
    Szkielet zapisu: kierowca (pracownicy pierwsi w kolejności blokad), trasa (404 — także robocza, której telefon
    nie widzi), akcja serwisu Dostawy, odpowiedź z pełną trasą z odczytu bieżącego (dostawa_widok.trasa_po_zapisie —
    te same blokady, trzymane do końca transakcji). `akcja(trasa, kierowca) -> (komunikat, {pola dodatkowe})`.

    Odmowy serwisu i odczyt trasy po zapisie stoją w jednym `try`: trasa skasowana w międzyczasie daje 404
    route_not_found (dostawa.zablokuj), a nie 500.

    Odmowa = żadnych zapisów akcji, stąd rollback przed odpowiedzią. 400/403/404/409 cofa i tak with_idempotency
    (BLEDY_DO_PONOWIENIA), ale 422 zapamiętuje i commituje RAZEM z transakcją. Serwis Dostawy rzuca 422 tylko przed
    zapisami (walidacja wejścia: waliduj_powod, waliduj_metode), a ten rollback pilnuje tego także na przyszłość —
    inaczej częściowe zapisy weszłyby do bazy razem z wpisem idempotencji.

    Jedno automatyczne ponowienie po zakleszczeniu MySQL 1213 (fala końcowa 4.4b, B1). Dostawa blokuje pozycje
    WSZYSTKICH zamówień trasy w kolejności (zamówienie, id), a trasa robocza i zatwierdzona może mieć zamówienia
    w produkcji (doróbka dokłada pozycję o wyższym id do starszego zamówienia). Pisarze wielu pozycji bez blokady
    zamówień (przeliczenie i przeciąganie priorytetów, druk TCP) piszą rosnąco po id, więc rzadkie 1213 jest możliwe —
    jak w hurcie i przeniesieniu osieroconych. Wtedy rollback, porzucenie planu dopychacza Base. z tej próby i CAŁY
    zapis od nowa: kierowca (sesje pracowników to pierwsze blokady), trasa, akcja — decyzja na nowym stanie. Ponowienie
    jest WEWNĄTRZ handlera, więc dekorator idempotencji widzi jeden wynik i zapisuje jeden wpis. Drugie 1213 i każdy
    inny błąd bazy idą dalej (with_idempotency: rollback i 500, wpis niezapamiętany). `flush` w środku `try` wypycha
    zapisy akcji, zanim handler odda wynik — inaczej zakleszczenie przy flushu w commicie dekoratora wypadłoby poza
    ponowieniem.
    """
    for proba in (1, 2):
        kierowca, err = _kierowca()
        if err:
            return err
        trasa = Route.query.get(route_id)
        if trasa is None or trasa.status == 'robocza':
            return _brak_trasy()
        try:
            komunikat, dodatkowe = akcja(trasa, kierowca)
            dane = {'route': dostawa_widok.trasa_po_zapisie(trasa), 'message': komunikat}
            db.session.flush()
            break
        except LogistykaBlad as e:
            db.session.rollback()
            return _blad(e)
        except OperationalError as e:
            if proba == 2 or blokady_zamowien.kod_mysql(e) != 1213:
                raise
            db.session.rollback()
            bl_sync.porzuc_zaplanowane()
            logger.warning('Dostawa: zakleszczenie 1213, ponawiam raz', extra={
                'route_id': route_id, 'endpoint': request.endpoint, 'device_id': g.device.device_id})
    dane.update(dodatkowe)
    logger.info('Dostawa: zapis', extra={'route_id': route_id, 'endpoint': request.endpoint,
                                         'changed': dodatkowe.get('changed'), 'worker_id': kierowca.id,
                                         'device_id': g.device.device_id})
    return jsonify(dane), 200


# ── Odczyty ─────────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes', methods=['GET'])
@require_device_token
@wymaga_dostawy
def delivery_routes():
    """GET /api/mobile/delivery/routes — „Moje trasy” kierowcy (spec 9.2), bez cache."""
    kierowca, err = _kierowca(dotknij=False)
    if err:
        return err
    trasy = dostawa_widok.lista_moich_tras(kierowca.id, routes.dzis())
    return no_store_json({'routes': trasy, 'count': len(trasy)})


@dostawa_mobile_bp.route('/routes/<int:route_id>', methods=['GET'])
@require_device_token
@wymaga_dostawy
def delivery_route(route_id):
    """GET /api/mobile/delivery/routes/<id> — trasa z przystankami i paczkami, ETag z treści (max-age=0)."""
    _kierowca_, err = _kierowca(dotknij=False)
    if err:
        return err
    wczytane = dostawa_widok.wczytaj(route_id)
    if wczytane is None or wczytane[0].status == 'robocza':
        return _brak_trasy()
    dane = dostawa_widok.serializuj(*wczytane)
    etag = make_weak_etag('dostawa', KSZTALT_TRASY, route_id, dostawa_widok.podpis(dane))
    if if_none_match(etag):
        return not_modified(etag, max_age=0)
    return cached_json({'route': dane}, etag, max_age=0)


# ── Załadunek ───────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes/<int:route_id>/packages/<int:package_id>/load', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_package_load(route_id, package_id):
    """POST …/packages/<id>/load {"method": "skan"|"reczne"} (spec 9.3); brak pola = skan."""
    metoda = _dane_json().get('method')
    try:
        dostawa.waliduj_metode(metoda)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        paczka, zmieniono = dostawa.zaladuj_paczke(trasa, package_id, metoda, worker_id=kierowca.id,
                                                   device_id=g.device.id)
        komunikat = (u'Paczka {} załadowana.' if zmieniono else u'Paczka {} była już załadowana.').format(paczka.kod)
        return komunikat, {'package': dostawa_widok.serializuj_paczke(paczka, trasa), 'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/packages/<int:package_id>/unload', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_package_unload(route_id, package_id):
    """POST …/packages/<id>/unload — cofnięcie pomyłki przed zakończeniem załadunku (spec 9.3)."""
    def akcja(trasa, kierowca):
        paczka, zmieniono = dostawa.rozladuj_paczke(trasa, package_id, worker_id=kierowca.id, device_id=g.device.id)
        komunikat = (u'Paczka {} zdjęta z auta.' if zmieniono else u'Paczka {} nie była załadowana.').format(paczka.kod)
        return komunikat, {'package': dostawa_widok.serializuj_paczke(paczka, trasa), 'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/stays', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_stays(route_id, order_id):
    """POST …/stops/<order_id>/stays {"reason", "note"?} — „Zostaje” (spec 9.3)."""
    dane = _dane_json()
    try:
        dostawa.waliduj_powod(dane.get('reason'), dostawa.POWODY_ZOSTAJE)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        zmieniono = dostawa.ustaw_zostaje(trasa, order_id, dane.get('reason'), dane.get('note'),
                                          worker_id=kierowca.id, device_id=g.device.id)
        return (u'Zamówienie {} zostaje: {}.'.format(numer, dostawa.POWODY_ZOSTAJE[dane.get('reason')]),
                {'changed': zmieniono})
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/stays', methods=['DELETE'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_stays_remove(route_id, order_id):
    """DELETE …/stops/<order_id>/stays — zdjęcie „Zostaje” przed zakończeniem załadunku."""
    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        zmieniono = dostawa.zdejmij_zostaje(trasa, order_id, worker_id=kierowca.id, device_id=g.device.id)
        return (u'Zamówienie {} jedzie.' if zmieniono
                else u'Zamówienie {} nie miało „Zostaje”.').format(numer), {'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/finish-loading', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_finish_loading(route_id):
    """
    POST …/finish-loading — „Zakończ załadunek” (spec 9.3); braki → 409 loading_incomplete z `braki`.
    Trasa już załadowana albo w drodze (powtórka z kolejki offline z nowym X-Operation-Id, Ruling 23) → 200
    {changed: false, removed: []}: serwis zwraca wtedy `usuniete` = None (nie pustą listę — stąd `is not None`).
    """
    def akcja(trasa, kierowca):
        trasa_po, usuniete = dostawa.zakoncz_zaladunek(trasa, worker_id=kierowca.id, device_id=g.device.id)
        if usuniete is None:
            return (u'Załadunek trasy „{}” był już zakończony.'.format(trasa_po.name),
                    {'changed': False, 'removed': []})
        komunikat = u'Załadunek zakończony — przystanków: {}.'.format(len(trasa_po.stops))
        if usuniete:
            komunikat += u' Zdjęte z trasy: {}.'.format(u', '.join(
                z['internal_order_number'] or u'#{}'.format(z['order_id']) for z in usuniete))
        return komunikat, {'changed': True, 'removed': usuniete}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/depart', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_depart(route_id):
    """POST …/depart — „Ruszam w trasę” (spec 9.4). Trasa już w drodze albo wykonana (Ruling 23) → 200
    changed: false."""
    def akcja(trasa, kierowca):
        trasa_po, zmieniono = dostawa.ruszaj(trasa, worker_id=kierowca.id, device_id=g.device.id)
        if zmieniono:
            komunikat = u'Trasa „{}” w drodze.'
        elif trasa_po.status == 'wykonana':
            komunikat = u'Trasa „{}” jest już zakończona.'
        else:
            komunikat = u'Trasa „{}” była już w drodze.'
        return komunikat.format(trasa_po.name), {'changed': zmieniono}
    return _zapis(route_id, akcja)


# ── Dostarczenia ────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_delivered(route_id, order_id):
    """POST …/stops/<order_id>/delivered — „Dostarczone” (spec 9.5)."""
    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        wynik = dostawa.dostarcz(trasa, order_id, worker_id=kierowca.id, device_id=g.device.id)
        _t, zmieniono, zamknieta = wynik
        komunikat = (u'Dostarczono zamówienie {}.' if zmieniono
                     else u'Zamówienie {} było już dostarczone.').format(numer)
        if zamknieta:
            # Runda 1 U10: dopisek o puli tylko, gdy to zamknięcie naprawdę zdjęło niedostarczone (stan pod blokadami).
            komunikat += TRASA_ZAKONCZONA if wynik.zdjete_do_puli else u' Trasa zakończona.'
        return komunikat, {'changed': zmieniono, 'route_completed': zamknieta}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/not-delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_not_delivered(route_id, order_id):
    """
    POST …/stops/<order_id>/not-delivered {"reason", "note"?} — „Niedostarczone” (spec 9.5, 4.5; U10, Ruling 32:
    przystanek zostaje na trasie do jej końca, ze stanem 'niedostarczone'). Ten sam powód i notatka na przystanku już
    niedostarczonym albo powtórka z nowym X-Operation-Id po zejściu przystanku do puli (Ruling 26, kolejka offline) →
    200 {changed: false, route_completed: false} z pełną trasą, jak powtórki zakończenia załadunku i wyjazdu
    (Ruling 23); inny powód albo notatka → zmiana. Każdy inny brak przystanku → 404 stop_not_found.
    """
    dane = _dane_json()
    try:
        dostawa.waliduj_powod(dane.get('reason'), dostawa.POWODY_NIEDOSTARCZENIA)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(trasa, order_id, dane.get('reason'), dane.get('note'),
                                                              worker_id=kierowca.id, device_id=g.device.id)
        if not zmieniono:
            # Runda 1 U10: tekst ze świeżej trasy spod blokad — bez zmian nic nie zeszło z trasy, więc przystanek jest
            # na niej wtedy i tylko wtedy, gdy to powtórka na niedostarczonym (inaczej zszedł już do puli).
            na_trasie = any(s.order_id == order_id for s in trasa_po.stops)
            tekst = (u'Zamówienie {} jest już oznaczone jako niedostarczone.' if na_trasie
                     else u'Zamówienie {} było już rozliczone jako niedostarczone.')
            return tekst.format(numer), {'changed': False, 'route_completed': False}
        if zamknieta:
            return (u'Zamówienie {} niedostarczone.'.format(numer) + TRASA_ZAKONCZONA,
                    {'changed': True, 'route_completed': True})
        return (u'Zamówienie {} niedostarczone — zostaje na trasie do jej końca.'.format(numer),
                {'changed': True, 'route_completed': False})
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_undo_delivered(route_id, order_id):
    """POST …/stops/<order_id>/undo-delivered — cofnięcie ostatniego dostarczenia (spec 9.5; także zaraz po
    automatycznym zamknięciu trasy — decyzja Konrada 3)."""
    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        _t, zmieniono = dostawa.cofnij_dostarczenie(trasa, order_id, z_telefonu=True, worker_id=kierowca.id,
                                                    device_id=g.device.id)
        return (u'Cofnięto dostarczenie zamówienia {}.' if zmieniono
                else u'Zamówienie {} nie było dostarczone.').format(numer), {'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-not-delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_undo_not_delivered(route_id, order_id):
    """
    POST …/stops/<order_id>/undo-not-delivered — „Cofnij niedostarczenie” (U10, Ruling 32): przystanek wraca do „do
    dostarczenia”. Przystanek, który nie jest niedostarczony → 200 changed: false (powtórka z kolejki offline); brak
    przystanku (np. zamówienie zeszło do puli przy zamknięciu trasy) → 404 stop_not_found z komunikatem.
    """
    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        _t, zmieniono = dostawa.cofnij_niedostarczenie(trasa, order_id, worker_id=kierowca.id,
                                                       device_id=g.device.id)
        return (u'Cofnięto niedostarczenie zamówienia {} — znów do dostarczenia.' if zmieniono
                else u'Zamówienie {} nie było oznaczone jako niedostarczone.').format(numer), {'changed': zmieniono}
    return _zapis(route_id, akcja)
