"""
API sub-package for production module.
Split from monolithic api_routers.py into per-tab files.
"""
from flask import Blueprint
from modules.logging import get_structured_logger

api_bp = Blueprint('production_api', __name__)
logger = get_structured_logger('production.api')

# Import models (shared across all API files)
try:
    from ...models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig, get_local_now
except ImportError:
    from modules.production.models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig, get_local_now

# Import and register common components
from .common_api import register_error_handlers, register_middleware
register_error_handlers(api_bp)
register_middleware(api_bp)

# Import all route modules (registers routes on api_bp)
from . import dashboard_api
from . import products_api
from . import reports_api
from . import stations_api
from . import config_api
from . import sync_api
from . import logistics_api

logger.info("Zainicjalizowano API routers modułu production (sub-package)", extra={
    'blueprint_name': api_bp.name,
    'prd_compliance': True
})
