# -*- coding: utf-8 -*-
"""
Trasy tabletu kierownika hali — /api/mobile/manager/* (kontrakt: docs/api-mobile-kierownik.md).

Każda trasa: @require_device_token → @wymaga_kierownika (services/bramka.py); zapisy dodatkowo
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True). Kolejne trasy dopisują
następne zadania planu.
"""
from flask import Blueprint

kierownik_mobile_bp = Blueprint('kierownik_mobile', __name__)
