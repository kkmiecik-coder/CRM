# -*- coding: utf-8 -*-
"""
Bramka dostępu tabletu kierownika hali (spec 2.4, kontrakt §2.1).

Dekorator `wymaga_kierownika` stoi PO `require_device_token` (kroki 1 i 2 kontraktu: 401 i 426) i sprawdza dalej, w tej
kolejności: stanowisko urządzenia (403 station_not_allowed), nagłówek X-Worker-Ids (400 worker_required, 422
invalid_worker_ids), istnienie pracownika (404 worker_not_found), jego aktywność i znacznik kierownika (403
not_a_manager). Odczyty też wymagają kierownika — bez profilu nic nie widać.
"""
from functools import wraps

from flask import g, jsonify, request

from modules.production.models import ProductionWorker
from modules.production.services import worker_service
from modules.production.services.worker_service import WorkerError

STANOWISKO = 'manager'


def blad(kod, komunikat, status, **dane):
    """Odpowiedź błędu kierownika: ({error, message, …dane}, status HTTP)."""
    cialo = dict(dane)
    cialo.update(error=kod, message=komunikat)
    return jsonify(cialo), status


def kierownik():
    """
    (kierownik, None) albo (None, odpowiedź). Pierwszy identyfikator z X-Worker-Ids = kierownik. Kolejność odmów
    z kontraktu §2.1: brak nagłówka → 400 worker_required; pusty albo niepoprawny → 422 invalid_worker_ids;
    nieznany pracownik → 404 worker_not_found; nieaktywny albo bez is_manager → 403 not_a_manager.
    Wołane także przy ponowieniu zapisu po MySQL 1213 (jak dostawa_api._kierowca) — niczego nie czyta z `g`.
    """
    try:
        ids = worker_service.parse_worker_ids_header(request.headers.get('X-Worker-Ids'))
    except WorkerError as e:
        return None, blad('invalid_worker_ids', e.detail or u'Niepoprawny nagłówek X-Worker-Ids.', e.status_code)
    if ids is None:
        return None, blad('worker_required', u'Wybierz profil kierownika.', 400)
    pracownik = ProductionWorker.query.get(ids[0])
    if pracownik is None:
        return None, blad('worker_not_found', u'Nie ma takiego pracownika. Odśwież listę i wybierz profil.', 404)
    if not pracownik.is_active or not pracownik.is_manager:
        return None, blad('not_a_manager', u'Ten pracownik nie jest aktywnym kierownikiem hali.', 403)
    return pracownik, None


def wymaga_kierownika(f):
    """
    Urządzenie zarejestrowane jako `manager` (kolumna z bazy — g.device z require_device_token, bez aliasów) oraz
    aktywny pracownik ze znacznikiem is_manager w X-Worker-Ids. Ustawia g.kierownik i g.worker_ids = [id]:
    listener product_events bierze z tego aktora zdarzeń pozycji (historia pokaże kierownika).
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if (g.device.station_code or '').strip() != STANOWISKO:
            return blad('station_not_allowed', u'To urządzenie nie jest zarejestrowane jako tablet kierownika.', 403)
        wybrany, odmowa = kierownik()
        if odmowa is not None:
            return odmowa
        g.kierownik = wybrany
        g.worker_ids = [wybrany.id]
        return f(*args, **kwargs)
    return wrapper
