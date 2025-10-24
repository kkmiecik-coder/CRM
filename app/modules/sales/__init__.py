# app/modules/sales/__init__.py
"""
Sales Module
============

Moduł rekrutacji handlowców WoodPower.

Składa się z:
1. Strona rekrutacyjna z formularzem aplikacyjnym
2. Panel administracyjny do zarządzania aplikacjami

Autor: Development Team
Data: 2025-10-24
"""

from flask import Blueprint

# Utworzenie Blueprint
sales_bp = Blueprint(
    'sales',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/sales',
    url_prefix='/sales'
)

# Import routes
from . import routers

__all__ = ['sales_bp']