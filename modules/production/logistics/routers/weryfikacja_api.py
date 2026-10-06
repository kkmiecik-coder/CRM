# -*- coding: utf-8 -*-
"""
API telefonu Weryfikacji — /api/mobile/verification/* (logistyka etap 4, krok 4.3, spec 8).

Reużywa autoryzację i idempotencję API mobilnego produkcji (require_device_token, with_idempotency).
Handlery zapisu NIE commitują — robi to dekorator idempotencji. Kolejność blokad każdego zapisu:
pracownicy (touch_sessions w _pracownik) → paczki.zablokuj_deklaracje() → zamówienie po PK →
paczki → pozycje. Deklaracja paczek i ponowny druk z telefonu idą istniejącymi endpointami
/api/mobile/orders/<nr>/packages (stanowisko 'verification' jest w paczki.STANOWISKA_PACZEK).

Zapisy (poza problem/resolve) działają tylko na zamówieniach z zakresu listy: poza nim 409 `order_status`
(weryfikacja.sprawdz_zakres, niezapamiętane w idempotencji). GET /orders/<nr> zostaje bez ograniczenia.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics.services import paczki, routes, weryfikacja
from modules.production.models import ProductionOrder, ProductionPackage, get_local_now
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA, _zamowienie_po_numerze
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import require_device_token, with_idempotency
from modules.production.services.station_catalog import resolve_station_code
from modules.production.services.worker_service import WorkerError
from modules.production.utils.cache import cached_json, if_none_match, make_weak_etag, no_store_json, not_modified

logger = get_structured_logger('production.logistics.weryfikacja_api')

weryfikacja_mobile_bp = Blueprint('weryfikacja_mobile', __name__)

# Wersja KSZTAŁTU odpowiedzi listy — część ETagu (jak KSZTALT_ODPOWIEDZI_KOLEJKI w mobile_api).
# PODBIJ przy każdej zmianie zestawu pól w weryfikacja.serializuj_zamowienie().
#   1 — 2026-09-30: pierwsza wersja (krok 4.3)
KSZTALT_LISTY = 1


def wymaga_weryfikacji(f):
    """Urządzenie zarejestrowane na stanowisku Weryfikacja (kod z JWT, jak druk etykiet paczek)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if resolve_station_code((g.device.station_code or '').strip()) != weryfikacja.STANOWISKO:
            return jsonify({'error': 'station_not_allowed',
                            'message': u'To urządzenie nie jest zarejestrowane na stanowisku Weryfikacja.'}), 403
        return f(*args, **kwargs)
    return wrapper


def _pracownik():
    """
    (worker_id, None) albo (None, odpowiedź). Zapis Weryfikacji zawsze ma pracownika (spec 8.1) —
    niezależnie od WORKER_SELECTION_REQUIRED: brak nagłówka X-Worker-Ids → 400 worker_required
    (w BLEDY_DO_PONOWIENIA — akcja zostaje w kolejce offline, appka wraca na „Kto pracuje?”).
    """
    try:
        ids = worker_service.resolve_worker_ids(request.headers.get('X-Worker-Ids'), required=False)
    except WorkerError as e:
        payload, status = e.as_response()
        return None, (jsonify(payload), status)
    if not ids:
        return None, (jsonify({'error': 'worker_required',
                               'message': u'Wybierz pracownika („Kto pracuje?”) — weryfikacja zapisuje, '
                                          u'kto sprawdził paczki.'}), 400)
    g.worker_ids = ids   # audyt zmian statusu pozycji (product_events.current_actor)
    worker_service.touch_sessions(ids, device_id=g.device.device_id)
    return ids[0], None


def _brak_zamowienia(numer):
    return jsonify({'error': 'order_not_found', 'message': u'Nie ma zamówienia {}.'.format(numer)}), 404


def _blad(e):
    return jsonify({'error': e.kod, 'message': e.komunikat}), e.status


def _dane_json():
    """Ciało JSON jako słownik; brak, zły JSON albo inny typ niż obiekt → pusty słownik (kontrakt: pola opcjonalne)."""
    dane = request.get_json(silent=True)
    return dane if isinstance(dane, dict) else {}


@weryfikacja_mobile_bp.route('/orders', methods=['GET'])
@require_device_token
@wymaga_weryfikacji
def verification_orders():
    """GET /api/mobile/verification/orders — lista „Do weryfikacji” (spec 8.2) z ETagiem."""
    teraz = get_local_now()
    zamowienia, pakunki, trasy = weryfikacja.lista(teraz)
    etag = make_weak_etag('weryfikacja', KSZTALT_LISTY, *weryfikacja.podpis_listy(zamowienia, pakunki, teraz))
    if if_none_match(etag):
        return not_modified(etag)
    return cached_json({
        'orders': [weryfikacja.serializuj_zamowienie(o, pakunki.get(o.id, []), trasy.get(o.id))
                   for o in zamowienia],
        'count': len(zamowienia),
    }, etag)


@weryfikacja_mobile_bp.route('/orders/<numer>', methods=['GET'])
@require_device_token
@wymaga_weryfikacji
def verification_order_details(numer):
    """GET /api/mobile/verification/orders/<nr> — zamówienie z pozycjami, bez cache."""
    order = _zamowienie_po_numerze(numer)
    if order is None:
        return _brak_zamowienia(numer)
    return no_store_json({'order': weryfikacja.serializuj_zamowienie(
        order, paczki.aktualne_paczki(order.id), routes.trasy_zamowien([order.id]).get(order.id),
        z_pozycjami=True)})


def _zamowienie_do_zapisu(numer):
    """Kolejność blokad zapisu Weryfikacji: blokada deklaracji paczek → wiersz zamówienia po PK."""
    paczki.zablokuj_deklaracje()
    return _zamowienie_po_numerze(numer, do_zapisu=True)


def _odpowiedz(order, message, **dodatkowe):
    # Skład paczek z odczytu bieżącego (blokady i tak są wzięte): zwykły SELECT pokazałby migawkę
    # MySQL sprzed czekania na blokady, czyli paczki sprzed cudzej deklaracji albo weryfikacji.
    dane = {'order': weryfikacja.serializuj_zamowienie(
                order, paczki.aktualne_paczki(order.id, do_zapisu=True),
                routes.trasy_zamowien([order.id]).get(order.id)),
            'message': message}
    dane.update(dodatkowe)
    return jsonify(dane), 200


@weryfikacja_mobile_bp.route('/packages/<int:package_id>/verify', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_package_verify(package_id):
    """POST /api/mobile/verification/packages/<id>/verify {"method": "skan"|"reczne"} (spec 8.3)."""
    metoda = _dane_json().get('method') or 'skan'
    if metoda not in weryfikacja.METODY:
        return jsonify({'error': 'invalid_method', 'message': u'Sposób weryfikacji: „skan” albo „reczne”.'}), 422
    worker_id, err = _pracownik()
    if err:
        return err
    paczki.zablokuj_deklaracje()
    # Zamówienie paczki ustalamy zwykłym odczytem, a blokujemy najpierw zamówienie, potem paczkę —
    # ta sama kolejność co deklaracja (zamówienie → paczki), więc bez cyklu blokad.
    order_id = db.session.query(ProductionPackage.order_id).filter_by(id=package_id).scalar()
    if order_id is None:
        return jsonify({'error': 'package_not_found', 'message': u'Nie ma paczki P-{}.'.format(package_id)}), 404
    order = ProductionOrder.query.filter_by(id=order_id).with_for_update().populate_existing().one()
    paczka = ProductionPackage.query.filter_by(id=package_id).with_for_update().populate_existing().one()
    try:
        zmieniono, zweryfikowane = weryfikacja.zweryfikuj_paczke(paczka, order, metoda, worker_id=worker_id,
                                                                device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    aktualne = paczki.aktualne_paczki(order.id, do_zapisu=True)
    licznik = u'{} / {}'.format(sum(1 for p in aktualne if p.verified_at is not None), len(aktualne))
    if zmieniono and zweryfikowane:
        komunikat = u'Zamówienie {} zweryfikowane ({}).'.format(order.internal_order_number, licznik)
    elif zmieniono:
        komunikat = u'Paczka {} sprawdzona ({}).'.format(paczka.kod, licznik)
    else:
        komunikat = u'Paczka {} była już sprawdzona ({}).'.format(paczka.kod, licznik)
    logger.info("Weryfikacja: paczka", extra={'package': paczka.kod, 'changed': zmieniono,
                                              'order_verified': zweryfikowane, 'device_id': g.device.device_id})
    return _odpowiedz(order, komunikat, package=paczki.serializuj_paczke(paczka),
                      order_verified=zweryfikowane, changed=zmieniono)


@weryfikacja_mobile_bp.route('/packages/<int:package_id>/unverify', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_package_unverify(package_id):
    """POST /api/mobile/verification/packages/<id>/unverify — cofnięcie sprawdzenia jednej paczki (spec 4.5, 8.3)."""
    worker_id, err = _pracownik()
    if err:
        return err
    # Kolejność blokad identyczna jak w verification_package_verify: deklaracje → zamówienie → paczka → serwis.
    paczki.zablokuj_deklaracje()
    order_id = db.session.query(ProductionPackage.order_id).filter_by(id=package_id).scalar()
    if order_id is None:
        return jsonify({'error': 'package_not_found', 'message': u'Nie ma paczki P-{}.'.format(package_id)}), 404
    order = ProductionOrder.query.filter_by(id=order_id).with_for_update().populate_existing().one()
    paczka = ProductionPackage.query.filter_by(id=package_id).with_for_update().populate_existing().one()
    try:
        zmieniono, bylo_zweryfikowane = weryfikacja.cofnij_sprawdzenie_paczki(
            paczka, order, worker_id=worker_id, device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    # Po cofnięciu zamówienie nigdy nie jest zweryfikowane; bez zmiany zostaje, jakie było.
    zweryfikowane = False if zmieniono else bylo_zweryfikowane
    aktualne = paczki.aktualne_paczki(order.id, do_zapisu=True)
    licznik = u'{} / {}'.format(sum(1 for p in aktualne if p.verified_at is not None), len(aktualne))
    if zmieniono and bylo_zweryfikowane:
        komunikat = u'{} — cofnięto sprawdzenie. Zamówienie {} wraca do sprawdzania ({}).'.format(
            paczka.kod, order.internal_order_number, licznik)
    elif zmieniono:
        komunikat = u'{} — cofnięto sprawdzenie ({}).'.format(paczka.kod, licznik)
    else:
        komunikat = u'{} nie była sprawdzona ({}).'.format(paczka.kod, licznik)
    logger.info("Weryfikacja: cofnięcie paczki", extra={'package': paczka.kod, 'changed': zmieniono,
                                                       'order_verified': zweryfikowane,
                                                       'device_id': g.device.device_id})
    return _odpowiedz(order, komunikat, package=paczki.serializuj_paczke(paczka),
                      order_verified=zweryfikowane, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/verify-all', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_verify_all(numer):
    """POST /api/mobile/verification/orders/<nr>/verify-all — wszystkie ważne paczki ręcznie."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        zmieniono = weryfikacja.zweryfikuj_wszystkie(order, worker_id=worker_id, device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    komunikat = (u'Zamówienie {} zweryfikowane ręcznie.' if zmieniono
                 else u'Zamówienie {} było już zweryfikowane.').format(order.internal_order_number)
    return _odpowiedz(order, komunikat, order_verified=True, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/unverify', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_unverify(numer):
    """POST /api/mobile/verification/orders/<nr>/unverify — „Cofnij weryfikację” (spec 4.5)."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.cofnij_weryfikacje(order, worker_id=worker_id, device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    return _odpowiedz(order, u'Cofnięto weryfikację zamówienia {} — paczki trzeba sprawdzić od nowa.'.format(
        order.internal_order_number), changed=True)


@weryfikacja_mobile_bp.route('/orders/<numer>/problem', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_problem(numer):
    """POST /api/mobile/verification/orders/<nr>/problem {"reason", "note"} (spec 8.3)."""
    dane = _dane_json()
    try:
        weryfikacja.waliduj_powod(dane.get('reason'))
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.zglos_problem(order, dane.get('reason'), dane.get('note'), worker_id=worker_id,
                                  device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    return _odpowiedz(order, u'Zgłoszono problem w zamówieniu {}: {}.'.format(
        order.internal_order_number, weryfikacja.POWODY_PROBLEMU[dane.get('reason')]), changed=True)


@weryfikacja_mobile_bp.route('/orders/<numer>/problem/resolve', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_problem_resolve(numer):
    """POST /api/mobile/verification/orders/<nr>/problem/resolve — zdjęcie flagi problemu."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    # Kolejność blokad (paczki → pozycje) jak w pozostałych zapisach; rozwiaz_problem podbija pozycje.
    weryfikacja.zablokuj_stan(order)
    zmieniono = weryfikacja.rozwiaz_problem(order, worker_id=worker_id, device_id=g.device.id)
    komunikat = (u'Problem w zamówieniu {} rozwiązany.' if zmieniono
                 else u'Zamówienie {} nie ma otwartego problemu.').format(order.internal_order_number)
    return _odpowiedz(order, komunikat, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/revert-to-packing', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_revert_to_packing(numer):
    """POST /api/mobile/verification/orders/<nr>/revert-to-packing {"reason"?, "note"?} (spec 8.4)."""
    dane = _dane_json()
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.cofnij_do_pakowania(order, dane.get('reason'), dane.get('note'), worker_id=worker_id,
                                        device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    # Priorytety produkcji (spec 2026-10-04, 9.3): pozycje wracają do `czeka_na_pakowanie`, więc zamówienie znów jest
    # w kolejce produkcji — bez przeliczenia stałoby z rangą z ostatniego razu aż do godzinnego crona. To jedyny zapis
    # Weryfikacji, który przestawia pozycje na status produkcji. Handler nie commituje: planujemy, a przeliczenie
    # wykona with_idempotency po udanym commicie. Import lokalny (cykl importów z pakietem logistyki).
    from modules.production.priorytety.services import kolejka, sygnaly
    kolejka.zaplanuj_po_commicie()
    # Pakowanie dostało pracę z powrotem (spec 5.4): sygnał `station:packaging` tylko planujemy — wyśle go
    # with_idempotency po udanym commicie; przy odmowie i rollbacku plan nie powstaje albo przepada.
    sygnaly.zaplanuj('packaging')
    return _odpowiedz(order, u'Zamówienie {} wraca do pakowania. Paczki są nieaktualne — pakowacz '
                             u'zadeklaruje je od nowa.'.format(order.internal_order_number), changed=True)
