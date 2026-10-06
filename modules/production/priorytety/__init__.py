# -*- coding: utf-8 -*-
"""
Priorytety produkcji — jedno źródło kolejności produkcji, ustawiane przez biuro na poziomie zamówienia:
gwiazdki 0–5, tagi terminowe i trasy ułożone na drabinie szczebli. Z drabiny serwis wylicza rangę zamówień
i pozycji (`services/kolejka.py`) i zapisuje ją jako pamięć podręczną w kolumnach `prod_orders.priority_rank`,
`priority_rung` oraz `prod_products.priority_rank`, `is_priority`.

Spec: docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md (poza gitem). Wzór układu pakietu:
modules/production/logistics/.

Krok K1 programu założył fundament: modele, stałe, ustawienia i serwisy rangi. Krok K2 dokłada blueprint panelu
biura (`routers/panel_api.py`), rejestrowany w app.py pod /production/api/priorytety.
"""
from flask import Blueprint

priorytety_panel_bp = Blueprint(
    'priorytety_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/priorytety',
)

# Modele muszą być w metadata, zanim ktokolwiek zrobi create_all (setup-db, fixtury testów).
from . import models  # noqa: E402,F401

# Router na samym końcu: importuje `priorytety_panel_bp` z tego modułu (cykl importów jak w logistyce).
from modules.production.priorytety.routers import panel_api  # noqa: E402,F401
