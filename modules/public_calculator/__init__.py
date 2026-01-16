from flask import Blueprint

public_calculator_bp = Blueprint(
    'public_calculator',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/public_calculator/static'
)

from . import routers