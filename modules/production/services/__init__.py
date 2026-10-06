# modules/production/services/__init__.py
"""
Serwisy modułu Production
=========================

Centralna inicjalizacja wszystkich serwisów biznesowych modułu produkcyjnego:
- ProductIDGenerator - generowanie unikalnych ID w formacie YY_NNNNN_S
- IPSecurityService - zabezpieczenia IP dla stanowisk produkcyjnych
- ProductionConfigService - cache konfiguracji z automatycznym odświeżaniem
- ProductNameParser - parsowanie nazw produktów z Baselinker
- NewPriorityCalculator - obliczanie priorytetów v2.0 (payment date + weekly grouping)
- BaselinkerSyncService - synchronizacja z API Baselinker

Autor: Konrad Kmiecik
Wersja: 1.2 (Finalna - z zabezpieczeniami)
Data: 2025-01-08
"""

from modules.logging import get_structured_logger

logger = get_structured_logger('production.services')

# Import wszystkich serwisów (będą dodawane postupnie)
try:
    from .id_generator import ProductIDGenerator
    logger.debug("Zaimportowano ProductIDGenerator")
except ImportError as e:
    logger.warning(f"Nie można zaimportować ProductIDGenerator: {e}")
    ProductIDGenerator = None

try:
    from .security_service import IPSecurityService, ip_security_middleware
    logger.debug("Zaimportowano IPSecurityService")
except ImportError as e:
    logger.warning(f"Nie można zaimportować IPSecurityService: {e}")
    IPSecurityService = None
    ip_security_middleware = None

try:
    from .config_service import ProductionConfigService
    logger.debug("Zaimportowano ProductionConfigService")
except ImportError as e:
    logger.warning(f"Nie można zaimportować ProductionConfigService: {e}")
    ProductionConfigService = None

try:
    from .parser_service import ProductNameParser
    logger.debug("Zaimportowano ProductNameParser")
except ImportError as e:
    logger.warning(f"Nie można zaimportować ProductNameParser: {e}")
    ProductNameParser = None

try:
    from .priority_service import NewPriorityCalculator
    logger.debug("Zaimportowano NewPriorityCalculator")
except ImportError as e:
    logger.warning(f"Nie można zaimportować NewPriorityCalculator: {e}")
    NewPriorityCalculator = None

try:
    from .sync_service import BaselinkerSyncService
    logger.debug("Zaimportowano BaselinkerSyncService")
except ImportError as e:
    logger.warning(f"Nie można zaimportować BaselinkerSyncService: {e}")
    BaselinkerSyncService = None

# Singleton instances dla cache'owanych serwisów
_config_service_instance = None
_parser_instance = None
_priority_calculator_instance = None

def get_config_service():
    """
    Pobiera singleton instance ProductionConfigService
    
    Returns:
        ProductionConfigService: Serwis konfiguracji z cache
    """
    global _config_service_instance
    
    if _config_service_instance is None and ProductionConfigService:
        _config_service_instance = ProductionConfigService()
        logger.info("Utworzono singleton ProductionConfigService")
    
    return _config_service_instance

def get_parser_service():
    """
    Pobiera singleton instance ProductNameParser
    
    Returns:
        ProductNameParser: Serwis parsowania nazw produktów
    """
    global _parser_instance
    
    if _parser_instance is None and ProductNameParser:
        _parser_instance = ProductNameParser()
        logger.info("Utworzono singleton ProductNameParser")
    
    return _parser_instance

def get_priority_calculator():
    """
    Pobiera singleton instance NewPriorityCalculator

    Returns:
        NewPriorityCalculator: Kalkulator priorytetów v2.0
    """
    global _priority_calculator_instance

    if _priority_calculator_instance is None and NewPriorityCalculator:
        _priority_calculator_instance = NewPriorityCalculator()
        logger.info("Utworzono singleton NewPriorityCalculator v2.0")

    return _priority_calculator_instance

def invalidate_caches():
    """
    Invaliduje wszystkie cache serwisów
    Używane po aktualizacji konfiguracji
    """
    global _config_service_instance, _parser_instance, _priority_calculator_instance
    
    # Invalidacja cache konfiguracji
    if _config_service_instance:
        try:
            _config_service_instance.invalidate_cache()
            logger.info("Zinvalidowano cache ProductionConfigService")
        except AttributeError:
            pass
    
    # Invalidacja cache parsera
    if _parser_instance:
        try:
            _parser_instance.invalidate_cache()
            logger.info("Zinvalidowano cache ProductNameParser")
        except AttributeError:
            pass
    
    logger.info("Zinvalidowano wszystkie cache serwisów production")

def reload_services():
    """
    Przeładowuje wszystkie serwisy singleton
    Używane po restarcie lub aktualizacji modułu
    """
    global _config_service_instance, _parser_instance, _priority_calculator_instance
    
    # Reset wszystkich instancji
    _config_service_instance = None
    _parser_instance = None
    _priority_calculator_instance = None
    
    # Ponowne utworzenie
    get_config_service()
    get_parser_service() 
    get_priority_calculator()
    
    logger.info("Przeładowano wszystkie serwisy production")

# Funkcje pomocnicze dla szybkiego dostępu
def generate_product_id(baselinker_order_id, sequence_number):
    """
    Szybkie generowanie Product ID
    
    Args:
        baselinker_order_id (int): ID zamówienia z Baselinker
        sequence_number (int): Numer sekwencji produktu w zamówieniu
        
    Returns:
        dict: Słownik z product_id i internal_order_number
    """
    if not ProductIDGenerator:
        logger.error("ProductIDGenerator nie jest dostępny")
        return None
        
    try:
        return ProductIDGenerator.generate_product_id(baselinker_order_id, sequence_number)
    except Exception as e:
        logger.error("Błąd generowania Product ID", extra={
            'baselinker_order_id': baselinker_order_id,
            'sequence_number': sequence_number,
            'error': str(e)
        })
        return None

def check_ip_access(ip_address, station_type=None):
    """
    Szybkie sprawdzenie dostępu IP
    
    Args:
        ip_address (str): Adres IP do sprawdzenia
        station_type (str, optional): Typ stanowiska
        
    Returns:
        bool: True jeśli dostęp jest dozwolony
    """
    if not IPSecurityService:
        logger.warning("IPSecurityService nie jest dostępny - domyślnie allow")
        return True
        
    try:
        return IPSecurityService.is_ip_allowed(ip_address, station_type)
    except Exception as e:
        logger.error("Błąd sprawdzania dostępu IP", extra={
            'ip_address': ip_address,
            'station_type': station_type,
            'error': str(e)
        })
        return False

def parse_product_name(product_name):
    """
    Szybkie parsowanie nazwy produktu
    
    Args:
        product_name (str): Nazwa produktu do sparsowania
        
    Returns:
        dict: Słownik z sparsowanymi parametrami
    """
    parser = get_parser_service()
    if not parser:
        logger.error("ProductNameParser nie jest dostępny")
        return {}
        
    try:
        return parser.parse_product_name(product_name)
    except Exception as e:
        logger.error("Błąd parsowania nazwy produktu", extra={
            'product_name': product_name,
            'error': str(e)
        })
        return {}

def recalculate_priorities():
    """
    Przelicza priorytety wszystkich aktywnych produktów

    Returns:
        dict: Rezultat przeliczenia
    """
    calculator = get_priority_calculator()
    if not calculator:
        logger.error("NewPriorityCalculator nie jest dostępny")
        return {'success': False, 'error': 'Calculator unavailable'}

    try:
        return calculator.recalculate_all_priorities()
    except Exception as e:
        logger.error("Błąd przeliczania priorytetów", extra={'error': str(e)})
        return {'success': False, 'error': str(e)}

def get_config_value(key, default=None):
    """
    Szybkie pobranie wartości konfiguracji
    
    Args:
        key (str): Klucz konfiguracji
        default: Wartość domyślna
        
    Returns:
        Wartość konfiguracji lub default
    """
    config_service = get_config_service()
    if not config_service:
        logger.error("ProductionConfigService nie jest dostępny")
        return default
        
    try:
        return config_service.get_config(key, default)
    except Exception as e:
        logger.error("Błąd pobierania konfiguracji", extra={
            'config_key': key,
            'error': str(e)
        })
        return default

# Health check dla wszystkich serwisów
def health_check():
    """
    Sprawdza status wszystkich serwisów
    
    Returns:
        dict: Status każdego serwisu
    """
    status = {
        'ProductIDGenerator': ProductIDGenerator is not None,
        'IPSecurityService': IPSecurityService is not None,
        'ProductionConfigService': ProductionConfigService is not None,
        'ProductNameParser': ProductNameParser is not None,
        'NewPriorityCalculator': NewPriorityCalculator is not None,
        'BaselinkerSyncService': BaselinkerSyncService is not None,
        'config_service_instance': _config_service_instance is not None,
        'parser_instance': _parser_instance is not None,
        'priority_calculator_instance': _priority_calculator_instance is not None
    }
    
    all_healthy = all(status.values())
    
    logger.info("Health check serwisów production", extra={
        'all_healthy': all_healthy,
        'status': status
    })
    
    return {
        'healthy': all_healthy,
        'services': status,
        'timestamp': logger._get_timestamp() if hasattr(logger, '_get_timestamp') else None
    }

# Eksport głównych komponentów
__all__ = [
    # Klasy serwisów
    'ProductIDGenerator',
    'IPSecurityService', 
    'ProductionConfigService',
    'ProductNameParser',
    'NewPriorityCalculator',
    'BaselinkerSyncService',
    
    # Singleton gettery
    'get_config_service',
    'get_parser_service', 
    'get_priority_calculator',
    
    # Funkcje zarządzania cache
    'invalidate_caches',
    'reload_services',
    
    # Funkcje pomocnicze
    'generate_product_id',
    'check_ip_access',
    'parse_product_name',
    'recalculate_priorities',
    'get_config_value',
    
    # Middleware
    'ip_security_middleware',
    
    # Health check
    'health_check'
]

# Metadata serwisów
__version__ = '1.2.0'
__services_count__ = 6
__description__ = 'Serwisy biznesowe modułu production z cache i singleton pattern'

logger.info("Zainicjalizowano moduł serwisów production", extra={
    'version': __version__,
    'services_count': __services_count__,
    'available_services': [name for name in __all__ if globals().get(name) is not None]
})