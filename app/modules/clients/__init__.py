from flask import Blueprint

clients_bp = Blueprint(
    "clients",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/clients/static"
)

from . import routers