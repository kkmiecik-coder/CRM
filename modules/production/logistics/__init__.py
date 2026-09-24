# -*- coding: utf-8 -*-
"""
Logistyka równoległa — sposób dostawy zamówienia, niezależny od pipeline'u
produkcji. Spec: docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md
(poza gitem). Blueprint rejestrowany w app.py pod /production/api/logistics.
"""
from flask import Blueprint

logistics_panel_bp = Blueprint(
    'logistics_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/logistics',
)

# Model musi być w metadata, zanim ktokolwiek zrobi create_all.
from modules.production.logistics import models  # noqa: E402,F401

from modules.production.logistics.routers import cron_api  # noqa: E402,F401
