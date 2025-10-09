# modules/calculator/__init__.py
from flask import Blueprint

calculator_bp= Blueprint(
    'calculator',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/calculator/static'
)

from .routers import calculator_bp
