# modules/calculator/routers/__init__.py
"""
Routery modułu Calculator.
Rejestracja tras bezpośrednio na głównym blueprint (bez sub-blueprintów).
"""

import logging

logger = logging.getLogger(__name__)


def register_calculator_routers(main_blueprint):
    """
    Rejestruje wszystkie trasy na głównym blueprint kalkulatora.
    Każdy moduł routerów definiuje register_routes(bp) zamiast własnego Blueprint.
    """
    registered_count = 0

    router_modules = [
        ('main', 'modules.calculator.routers.main_routers'),
        ('shipping', 'modules.calculator.routers.shipping_routers'),
        ('quote', 'modules.calculator.routers.quote_routers'),
        ('client', 'modules.calculator.routers.client_routers'),
        ('edge', 'modules.calculator.routers.edge_routers'),
        ('finishing', 'modules.calculator.routers.finishing_routers'),
        ('draft', 'modules.calculator.routers.draft_routers'),
    ]

    for name, module_path in router_modules:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            mod.register_routes(main_blueprint)
            registered_count += 1
            logger.debug(f"Zarejestrowano {name}_routers")
        except ImportError as e:
            logger.warning(f"Nie można zaimportować {name}_routers: {e}")
        except Exception as e:
            logger.error(f"Błąd rejestracji {name}_routers: {e}")

    logger.info(f"Zarejestrowano {registered_count}/{len(router_modules)} routerów kalkulatora")
    return registered_count


__all__ = ['register_calculator_routers']
