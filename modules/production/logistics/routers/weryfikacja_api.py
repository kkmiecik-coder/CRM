# -*- coding: utf-8 -*-
"""
API telefonu Weryfikacji — /api/mobile/verification/* (logistyka etap 4, krok 4.3, spec 8).

Reużywa autoryzację i idempotencję API mobilnego produkcji (require_device_token, with_idempotency).
Handlery zapisu NIE commitują — robi to dekorator idempotencji. Kolejność blokad każdego zapisu:
pracownicy (touch_sessions w _pracownik) → paczki.zablokuj_deklaracje() → zamówienie po PK →
paczki → pozycje. Deklaracja paczek i ponowny druk z telefonu idą istniejącymi endpointami
/api/mobile/orders/<nr>/packages (stanowisko 'verification' jest w paczki.STANOWISKA_PACZEK).
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from modules.logging import get_structured_logger
from modules.production.logistics.services import paczki, routes, weryfikacja
from modules.production.models import get_local_now
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA, _zamowienie_po_numerze  # noqa: F401
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import require_device_token, with_idempotency  # noqa: F401
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
