# -*- coding: utf-8 -*-
"""
Trakownia — podmoduł produkcji rejestrujący cięcie kłód.

Dwa blueprinty: panel (przeglądarka, sesja użytkownika) i mobile (tablet,
JWT urządzenia). Rejestrowane w app.py z osobnymi prefiksami.
"""

from flask import Blueprint

sawmill_panel_bp = Blueprint(
    'sawmill_panel', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/sawmill',
)

sawmill_mobile_bp = Blueprint('sawmill_mobile', __name__)

# Import routerów NA KOŃCU — rejestrują trasy na powyższych blueprintach.
from modules.production.sawmill.routers import mobile_api, panel_api  # noqa: E402,F401
