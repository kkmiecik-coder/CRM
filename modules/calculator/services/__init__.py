# modules/calculator/services/__init__.py
"""
Serwisy modułu Calculator.
Wzorzec z dashboard - importy z try/except.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from .shipping_service import get_shipping_quotes
    logger.debug("Zaimportowano shipping_service")
except ImportError as e:
    logger.warning(f"Nie można zaimportować shipping_service: {e}")
    get_shipping_quotes = None

try:
    from .quote_service import create_quote, generate_quote_number
    logger.debug("Zaimportowano quote_service")
except ImportError as e:
    logger.warning(f"Nie można zaimportować quote_service: {e}")
    create_quote = None
    generate_quote_number = None

try:
    from .client_service import search_clients_by_term
    logger.debug("Zaimportowano client_service")
except ImportError as e:
    logger.warning(f"Nie można zaimportować client_service: {e}")
    search_clients_by_term = None

try:
    from .pricing_service import get_finishing_prices_data
    logger.debug("Zaimportowano pricing_service")
except ImportError as e:
    logger.warning(f"Nie można zaimportować pricing_service: {e}")
    get_finishing_prices_data = None

try:
    from .draft_service import save_draft, load_draft, delete_draft
    logger.debug("Zaimportowano draft_service")
except ImportError as e:
    logger.warning(f"Nie można zaimportować draft_service: {e}")
    save_draft = None
    load_draft = None
    delete_draft = None

__all__ = [
    'get_shipping_quotes',
    'create_quote',
    'generate_quote_number',
    'search_clients_by_term',
    'get_finishing_prices_data',
    'save_draft',
    'load_draft',
    'delete_draft',
]
