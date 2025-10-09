# modules/quotes/__init__.py
from flask import Blueprint

quotes_bp = Blueprint(
    "quotes",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/quotes/static"
)

from . import routers