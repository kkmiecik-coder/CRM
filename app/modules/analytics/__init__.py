# modules/analytics/__init__.py

from flask import Blueprint

analytics_bp = Blueprint(
    "analytics",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/analytics/static"
)

# Import routers AFTER blueprint creation
from . import routers

# Import models for other modules to use
from .models import AnalyticsQueries, AnalyticsExportHelper