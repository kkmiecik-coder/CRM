# app/modules/baselinker/__init__.py
from flask import Blueprint

baselinker_bp = Blueprint(
    "baselinker",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/baselinker/static"
)

from . import routers