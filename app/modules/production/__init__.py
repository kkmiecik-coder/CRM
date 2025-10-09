# modules/production/__init__.py
"""
Moduł Production - System Zarządzania Produkcją WoodPower CRM
============================================================

Moduł implementuje kompletny workflow produkcyjny:
- Automatyczna synchronizacja zamówień z Baselinker
- Rozbijanie zamówień na produkty z nowym formatem ID (25_05248_1)
- Workflow przez 3 stanowiska: Wycinanie → Składanie → Pakowanie
- Interfejsy zoptymalizowane pod tablety z zabezpieczeniem IP
- System priorytetów i monitoring produkcji w czasie rzeczywistym

Autor: Konrad Kmiecik
Wersja: 1.2 (Finalna - z zabezpieczeniami)
Data: 2025-01-08
"""

from flask import Blueprint
from modules.logging import get_structured_logger

# Inicjalizacja loggera dla modułu
logger = get_structured_logger('production.module')

# Utworzenie Blueprint dla modułu produkcyjnego
production_bp = Blueprint(
    'production',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/production/static',
    url_prefix='/production'
)

# Import routerów będzie obsłużony w modules/production/routers

# Import serwisów (będą dodane postupnie)
try:
    from .services.id_generator import ProductIDGenerator
    from .services.security_service import IPSecurityService
    from .services.config_service import ProductionConfigService
    from .services.parser_service import ProductNameParser
    from .services.priority_service import PriorityCalculator
    from .services.sync_service import BaselinkerSyncService
    
    logger.info("Zaimportowano wszystkie serwisy modułu production")
    
except ImportError as e:
    # Serwisy będą dodawane postupnie
    logger.warning(f"Nie można zaimportować serwisów: {e}")

# Import modeli (będą dodane w następnym kroku)
try:
    from .models import (
        ProductionItem,
        ProductionOrderCounter, 
        ProductionPriorityConfig,
        ProductionSyncLog,
        ProductionError,
        ProductionConfig
    )
    
    logger.info("Zaimportowano wszystkie modele modułu production")
    
except ImportError as e:
    # Modele będą dodane w następnym kroku
    logger.warning(f"Nie można zaimportować modeli: {e}")

# Middleware zabezpieczeń IP (będzie dodane wraz z security_service)
try:
    from .services.security_service import ip_security_middleware
except ImportError as e:
    logger.warning(
        "Middleware zabezpieczeń IP nie jest jeszcze dostępne",
        extra={"error": str(e)}
    )

    def ip_security_middleware():  # type: ignore
        return None
else:
    logger.info("Middleware zabezpieczeń IP dostępne")


def apply_security():
    """Zastosowanie middleware zabezpieczeń dla modułu production"""
    return ip_security_middleware()

# Funkcje pomocnicze dla innych modułów
def get_production_status_summary():
    """
    Pobiera podsumowanie statusów produkcji dla dashboardu głównego
    
    Returns:
        dict: Słownik z liczbą produktów per status
    """
    try:
        from .models import ProductionItem
        from sqlalchemy import func
        from extensions import db
        
        summary = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('total_volume'),
            func.sum(ProductionItem.total_value_net).label('total_value')
        ).filter(
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.current_status).all()
        
        result = {}
        for status, count, volume, value in summary:
            result[status] = {
                'count': count or 0,
                'volume_m3': float(volume or 0),
                'value_net': float(value or 0)
            }
            
        logger.info("Pobrano podsumowanie statusów produkcji", extra={
            'statuses_count': len(result),
            'total_items': sum(s['count'] for s in result.values())
        })
        
        return result
        
    except Exception as e:
        logger.error("Błąd pobierania podsumowania produkcji", extra={
            'error': str(e)
        })
        return {}

def get_high_priority_items_count():
    """
    Pobiera liczbę elementów o wysokim priorytecie
    
    Returns:
        int: Liczba elementów o wysokim priorytecie
    """
    try:
        from .models import ProductionItem
        from extensions import db
        
        count = db.session.query(ProductionItem).filter(
            ProductionItem.priority_score >= 150,
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 
                'czeka_na_skladanie', 
                'czeka_na_pakowanie'
            ])
        ).count()
        
        logger.debug("Pobrano liczbę elementów o wysokim priorytecie", extra={
            'high_priority_count': count
        })
        
        return count
        
    except Exception as e:
        logger.error("Błąd pobierania liczby elementów o wysokim priorytecie", extra={
            'error': str(e)
        })
        return 0

def is_sync_running():
    """
    Sprawdza czy synchronizacja z Baselinker jest w toku
    
    Returns:
        bool: True jeśli synchronizacja jest w toku
    """
    try:
        from .models import ProductionSyncLog
        from extensions import db
        
        running_sync = db.session.query(ProductionSyncLog).filter(
            ProductionSyncLog.sync_status == 'running'
        ).first()
        
        return running_sync is not None
        
    except Exception as e:
        logger.error("Błąd sprawdzania statusu synchronizacji", extra={
            'error': str(e)
        })
        return False

# Eksport głównych komponentów
__all__ = [
    'production_bp',
    'get_production_status_summary',
    'get_high_priority_items_count', 
    'is_sync_running'
]

# Metadata modułu
__version__ = '1.2.0'
__author__ = 'Konrad Kmiecik'
__description__ = 'System zarządzania produkcją z automatyczną synchronizacją Baselinker'

logger.info("Zainicjalizowano moduł production", extra={
    'version': __version__,
    'blueprint_name': production_bp.name,
    'url_prefix': production_bp.url_prefix
})