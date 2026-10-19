# -*- coding: utf-8 -*-
"""
Trasy tabletu kierownika hali — /api/mobile/manager/* (kontrakt: docs/api-mobile-kierownik.md).

Każda trasa: @require_device_token → @wymaga_kierownika (services/bramka.py); zapisy dodatkowo
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True). Kolejne trasy dopisują
następne zadania planu.
"""
from flask import Blueprint, request

from modules.production.kierownik.services import zamowienia
from modules.production.kierownik.services.bramka import blad, wymaga_kierownika
from modules.production.services.mobile_api_service import require_device_token
from modules.production.utils.cache import cached_json, if_none_match, no_store_json, not_modified

kierownik_mobile_bp = Blueprint('kierownik_mobile', __name__)

# Listy mają słaby ETag i Cache-Control: private, max-age=15 (kontrakt §2).
MAX_AGE_LISTY = 15


@kierownik_mobile_bp.route('/orders', methods=['GET'])
@require_device_token
@wymaga_kierownika
def lista_zamowien():
    """Lista zamówień (bieżące, archiwum, wszystkie) ze statystykami na całym przefiltrowanym zbiorze (§5.1)."""
    try:
        parametry = zamowienia.wczytaj_parametry(request.args)
    except zamowienia.BladParametru as e:
        return blad('dane_niepoprawne', str(e), 400)
    etag = zamowienia.etag_listy(parametry)
    if if_none_match(etag):
        return not_modified(etag, max_age=MAX_AGE_LISTY)
    return cached_json(zamowienia.lista(**parametry), etag, max_age=MAX_AGE_LISTY)


@kierownik_mobile_bp.route('/orders/<int:order_id>', methods=['GET'])
@require_device_token
@wymaga_kierownika
def karta_zamowienia(order_id):
    """Karta zamówienia z pełnymi pozycjami, załącznikami i miejscem na stołach stanowisk (§5.2). `no-store`."""
    dane = zamowienia.karta(order_id)
    if dane is None:
        return blad('zamowienie_nieznane', u'Nie ma takiego zamówienia.', 404)
    return no_store_json(dane)


@kierownik_mobile_bp.route('/products/<int:product_id>/history', methods=['GET'])
@require_device_token
@wymaga_kierownika
def historia_pozycji(product_id):
    """Historia pozycji: przepływ po stanowiskach i oś zdarzeń od najnowszych (§5.3). `no-store`."""
    dane = zamowienia.historia(product_id)
    if dane is None:
        return blad('pozycja_nieznana', u'Nie ma takiej pozycji.', 404)
    return no_store_json(dane)
