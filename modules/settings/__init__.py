# app/modules/settings/__init__.py
"""
Moduł ustawień aplikacji
========================

Zarządzanie konfiguracją systemu CRM - dostępne tylko dla administratorów.

Funkcjonalności:
- Źródła wycen (quote_sources)
- Konfiguracja integracji (Baselinker, API)
- Ustawienia systemu
"""

from flask import Blueprint

settings_bp = Blueprint(
    'settings',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/settings/static'
)

from . import routers
