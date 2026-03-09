# modules/calculator/__init__.py
"""
Moduł Calculator - kalkulator wycen WoodPower.
Blueprint + rejestracja routerów z podkatalogu routers/.
"""

from flask import Blueprint

calculator_bp = Blueprint(
    'calculator',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/calculator/static'
)

from .routers import register_calculator_routers
register_calculator_routers(calculator_bp)
