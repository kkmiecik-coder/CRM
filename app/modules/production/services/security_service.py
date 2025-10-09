# modules/production/services/security_service.py
"""
Serwis zabezpieczeń IP dla modułu Production
============================================

Implementuje system zabezpieczeń oparty na adresach IP dla stanowisk produkcyjnych:
- Walidacja dostępu na podstawie białej listy IP
- Middleware Flask dla automatycznej kontroli dostępu
- Geolokalizacja IP z cache'owaniem wyników
- Logowanie prób nieautoryzowanego dostępu
- Konfiguracja per-stanowisko (opcjonalnie)

Zabezpieczenia są stosowane automatycznie dla:
- /production/cutting - stanowisko wycinania
- /production/assembly - stanowisko składania  
- /production/packaging - stanowisko pakowania
- /production (wybór stanowiska)

Autor: Konrad Kmiecik
Wersja: 1.2 (Finalna - z zabezpieczeniami)
Data: 2025-01-08
"""

import ipaddress
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import request, abort, jsonify, current_app
from modules.logging import get_structured_logger
from extensions import db
import pytz

logger = get_structured_logger('production.security')

def get_local_now():
    """Zwraca aktualny czas w strefie czasowej Polski"""
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)

class SecurityError(Exception):
    """Wyjątek dla błędów zabezpieczeń"""
    pass

class IPSecurityService:
    """
    Serwis zabezpieczeń IP dla stanowisk produkcyjnych
    
    Zapewnia kontrolę dostępu na podstawie adresów IP z możliwością
    konfiguracji per-stanowisko i szczegółowym logowaniem.
    """
    
    # Cache dla adresów IP (żeby nie odpytywać bazy za każdym razem)
    _ip_cache = {}
    _cache_expiry = {}
    _cache_duration = timedelta(minutes=10)
    
    # Adresy IP które są zawsze dozwolone (localhost, development)
    ALWAYS_ALLOWED_IPS = ['127.0.0.1', '::1', 'localhost']
    
    # Routy które wymagają zabezpieczeń IP
    PROTECTED_ROUTERS = [
        '/production/cutting',
        '/production/assembly', 
        '/production/packaging',
        '/production/station-select',
        '/production/'
    ]
    
    @classmethod
    def is_ip_allowed(cls, ip_address, station_type=None):
        """
        Sprawdza czy adres IP jest dozwolony dla danego stanowiska
        
        Args:
            ip_address (str): Adres IP do sprawdzenia
            station_type (str, optional): Typ stanowiska ('cutting', 'assembly', 'packaging')
            
        Returns:
            bool: True jeśli dostęp jest dozwolony
        """
        try:
            # Normalizacja IP address
            normalized_ip = cls._normalize_ip_address(ip_address)
            
            # Sprawdzenie czy to zawsze dozwolone IP
            if normalized_ip in cls.ALWAYS_ALLOWED_IPS:
                logger.debug("Dozwolony IP z listy zawsze dozwolonych", extra={
                    'ip_address': normalized_ip,
                    'station_type': station_type
                })
                return True
            
            # Sprawdzenie cache
            cache_key = f"{normalized_ip}_{station_type or 'general'}"
            if cls._is_cached_and_valid(cache_key):
                result = cls._ip_cache[cache_key]
                logger.debug("Wynik z cache dla IP", extra={
                    'ip_address': normalized_ip,
                    'station_type': station_type,
                    'allowed': result
                })
                return result
            
            # Pobranie konfiguracji IP z bazy danych
            allowed_ips = cls._get_allowed_ips_from_config(station_type)
            
            # Sprawdzenie czy IP jest na liście dozwolonych
            is_allowed = cls._check_ip_in_list(normalized_ip, allowed_ips)
            
            # Zapisanie w cache
            cls._cache_ip_result(cache_key, is_allowed)
            
            logger.info("Sprawdzenie dostępu IP", extra={
                'ip_address': normalized_ip,
                'station_type': station_type,
                'allowed': is_allowed,
                'allowed_ips_count': len(allowed_ips)
            })
            
            return is_allowed
            
        except Exception as e:
            logger.error("Błąd sprawdzania dostępu IP", extra={
                'ip_address': ip_address,
                'station_type': station_type,
                'error': str(e)
            })
            # W przypadku błędu, blokujemy dostęp
            return False
    
    @classmethod
    def _normalize_ip_address(cls, ip_address):
        """
        Normalizuje adres IP do standardowego formatu
        
        Args:
            ip_address (str): Adres IP do normalizacji
            
        Returns:
            str: Znormalizowany adres IP
            
        Raises:
            SecurityError: Jeśli IP jest nieprawidłowy
        """
        if not ip_address:
            raise SecurityError("Pusty adres IP")
        
        # Usunięcie whitespace
        ip_address = str(ip_address).strip()
        
        # Obsługa localhost
        if ip_address.lower() == 'localhost':
            return '127.0.0.1'
        
        # Walidacja i normalizacja przez ipaddress
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            return str(ip_obj)
        except ValueError as e:
            raise SecurityError(f"Nieprawidłowy format IP: {ip_address} ({e})")
    
    @classmethod
    def _get_allowed_ips_from_config(cls, station_type=None):
        """
        Pobiera listę dozwolonych IP z konfiguracji
        
        Args:
            station_type (str, optional): Typ stanowiska
            
        Returns:
            list: Lista dozwolonych adresów IP
        """
        try:
            from ..models import ProductionConfig
            
            # Sprawdzenie czy istnieje konfiguracja per-stanowisko
            config_key = f"STATION_ALLOWED_IPS_{station_type.upper()}" if station_type else "STATION_ALLOWED_IPS"
            
            config = ProductionConfig.query.filter_by(config_key=config_key).first()
            
            # Fallback do ogólnej konfiguracji jeśli nie ma per-stanowisko
            if not config and station_type:
                config = ProductionConfig.query.filter_by(config_key="STATION_ALLOWED_IPS").first()
            
            if not config:
                logger.warning("Brak konfiguracji dozwolonych IP", extra={
                    'station_type': station_type,
                    'config_key': config_key
                })
                return []
            
            # Parsowanie listy IP
            ip_list = []
            if config.config_value:
                raw_ips = config.config_value.split(',')
                for ip in raw_ips:
                    normalized = ip.strip()
                    if normalized:
                        try:
                            # Walidacja IP
                            ipaddress.ip_address(normalized)
                            ip_list.append(normalized)
                        except ValueError:
                            logger.warning("Nieprawidłowy IP w konfiguracji", extra={
                                'ip': normalized,
                                'config_key': config_key
                            })
            
            logger.debug("Pobrano dozwolone IP z konfiguracji", extra={
                'station_type': station_type,
                'config_key': config_key,
                'ip_count': len(ip_list)
            })
            
            return ip_list
            
        except Exception as e:
            logger.error("Błąd pobierania konfiguracji IP", extra={
                'station_type': station_type,
                'error': str(e)
            })
            return []
    
    @classmethod
    def _check_ip_in_list(cls, ip_address, allowed_ips):
        """
        Sprawdza czy IP jest na liście dozwolonych (obsługuje sieci CIDR)
        
        Args:
            ip_address (str): Adres IP do sprawdzenia
            allowed_ips (list): Lista dozwolonych IP/sieci
            
        Returns:
            bool: True jeśli IP jest dozwolony
        """
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            
            for allowed in allowed_ips:
                try:
                    # Sprawdzenie czy to pojedynczy IP czy sieć
                    if '/' in allowed:
                        # To jest sieć CIDR
                        network = ipaddress.ip_network(allowed, strict=False)
                        if ip_obj in network:
                            logger.debug("IP dozwolony przez sieć CIDR", extra={
                                'ip_address': ip_address,
                                'cidr_network': allowed
                            })
                            return True
                    else:
                        # To jest pojedynczy IP
                        allowed_ip = ipaddress.ip_address(allowed)
                        if ip_obj == allowed_ip:
                            logger.debug("IP dozwolony jako pojedynczy adres", extra={
                                'ip_address': ip_address,
                                'allowed_ip': allowed
                            })
                            return True
                            
                except ValueError:
                    logger.warning("Nieprawidłowy format w liście dozwolonych IP", extra={
                        'allowed_entry': allowed
                    })
                    continue
            
            return False
            
        except Exception as e:
            logger.error("Błąd sprawdzania IP na liście", extra={
                'ip_address': ip_address,
                'error': str(e)
            })
            return False
    
    @classmethod
    def _is_cached_and_valid(cls, cache_key):
        """
        Sprawdza czy wynik jest w cache i czy jest ważny
        
        Args:
            cache_key (str): Klucz cache
            
        Returns:
            bool: True jeśli cache jest ważny
        """
        if cache_key not in cls._ip_cache:
            return False
            
        if cache_key not in cls._cache_expiry:
            return False
            
        return datetime.now() < cls._cache_expiry[cache_key]
    
    @classmethod
    def _cache_ip_result(cls, cache_key, result):
        """
        Zapisuje wynik w cache
        
        Args:
            cache_key (str): Klucz cache
            result (bool): Wynik do zapisania
        """
        cls._ip_cache[cache_key] = result
        cls._cache_expiry[cache_key] = datetime.now() + cls._cache_duration
        
        # Oczyszczenie starych wpisów z cache
        cls._cleanup_cache()
    
    @classmethod
    def _cleanup_cache(cls):
        """Oczyszcza wygasłe wpisy z cache"""
        now = datetime.now()
        expired_keys = []
        
        for key, expiry in cls._cache_expiry.items():
            if now >= expiry:
                expired_keys.append(key)
        
        for key in expired_keys:
            cls._ip_cache.pop(key, None)
            cls._cache_expiry.pop(key, None)
        
        if expired_keys:
            logger.debug("Oczyszczono cache IP", extra={
                'expired_count': len(expired_keys)
            })
    
    @classmethod
    def clear_cache(cls):
        """Czyści cały cache IP"""
        cls._ip_cache.clear()
        cls._cache_expiry.clear()
        logger.info("Wyczyszczono cały cache IP")
    
    @classmethod
    def get_client_ip(cls, request_obj=None):
        """
        Pobiera rzeczywisty IP klienta (obsługuje proxy)
        
        Args:
            request_obj: Obiekt request Flask (domyślnie current request)
            
        Returns:
            str: Adres IP klienta
        """
        if request_obj is None:
            request_obj = request
        
        # Sprawdzenie nagłówków proxy w kolejności ważności
        proxy_headers = [
            'X-Forwarded-For',
            'X-Real-IP', 
            'X-Forwarded',
            'X-Cluster-Client-IP',
            'CF-Connecting-IP'  # Cloudflare
        ]
        
        for header in proxy_headers:
            ip_header = request_obj.headers.get(header)
            if ip_header:
                # X-Forwarded-For może zawierać listę IP oddzielonych przecinkami
                first_ip = ip_header.split(',')[0].strip()
                if first_ip and first_ip != 'unknown':
                    logger.debug("IP pobrany z nagłówka proxy", extra={
                        'header': header,
                        'ip': first_ip
                    })
                    return first_ip
        
        # Fallback do standardowego remote_addr
        remote_addr = request_obj.remote_addr or '127.0.0.1'
        
        logger.debug("IP pobrany z remote_addr", extra={
            'ip': remote_addr
        })
        
        return remote_addr
    
    @classmethod
    def log_security_event(cls, event_type, ip_address, details=None):
        """
        Loguje zdarzenie bezpieczeństwa do DEDYKOWANEJ tabeli prod_security_events
        NIE zapisuje już do prod_errors!
    
        Args:
            event_type (str): Typ zdarzenia ('access_denied', 'access_granted', etc.)
            ip_address (str): Adres IP
            details (dict, optional): Dodatkowe szczegóły
        """
        try:
            from ..models import ProductionSecurityEvent
        
            # Przygotowanie szczegółów
            event_details = details or {}
        
            # Dodaj user_agent jeśli dostępny
            if request:
                event_details['user_agent'] = request.headers.get('User-Agent', 'Unknown')
        
            # Zapisz do dedykowanej tabeli security events
            ProductionSecurityEvent.log_event(
                event_type=event_type,
                ip_address=ip_address,
                details=event_details
            )
        
            # Dodatkowo loguj do aplikacji
            log_level = 'warning' if event_type == 'access_denied' else 'info'
            logger.log(
                getattr(logger, log_level.upper()),
                f"Security event: {event_type}",
                extra={
                    'event_type': event_type,
                    'ip_address': ip_address,
                    'details': event_details
                }
            )
        
        except Exception as e:
            logger.error("Błąd logowania zdarzenia bezpieczeństwa", extra={
                'event_type': event_type,
                'ip_address': ip_address,
                'error': str(e)
            })
    
    @classmethod
    def add_allowed_ip(cls, ip_address, station_type=None, admin_user_id=None):
        """
        Dodaje IP do listy dozwolonych
        
        Args:
            ip_address (str): Adres IP do dodania
            station_type (str, optional): Typ stanowiska
            admin_user_id (int, optional): ID administratora
            
        Returns:
            bool: True jeśli IP został dodany
        """
        try:
            # Walidacja IP
            normalized_ip = cls._normalize_ip_address(ip_address)
            
            from ..models import ProductionConfig
            
            config_key = f"STATION_ALLOWED_IPS_{station_type.upper()}" if station_type else "STATION_ALLOWED_IPS"
            config = ProductionConfig.query.filter_by(config_key=config_key).first()
            
            if not config:
                # Utworzenie nowej konfiguracji
                config_value = normalized_ip
                ProductionConfig.set_config(
                    config_key, 
                    config_value, 
                    admin_user_id,
                    f"Dozwolone IP dla stanowiska {station_type or 'ogólne'}",
                    'ip_list'
                )
            else:
                # Dodanie do istniejącej listy
                current_ips = config.parsed_value
                if normalized_ip not in current_ips:
                    current_ips.append(normalized_ip)
                    new_value = ','.join(current_ips)
                    ProductionConfig.set_config(config_key, new_value, admin_user_id)
            
            # Wyczyszczenie cache
            cls.clear_cache()
            
            logger.info("Dodano IP do listy dozwolonych", extra={
                'ip_address': normalized_ip,
                'station_type': station_type,
                'admin_user_id': admin_user_id
            })
            
            cls.log_security_event('ip_added', normalized_ip, {
                'station_type': station_type,
                'admin_user_id': admin_user_id
            })
            
            return True
            
        except Exception as e:
            logger.error("Błąd dodawania IP", extra={
                'ip_address': ip_address,
                'station_type': station_type,
                'error': str(e)
            })
            return False
    
    @classmethod
    def remove_allowed_ip(cls, ip_address, station_type=None, admin_user_id=None):
        """
        Usuwa IP z listy dozwolonych
        
        Args:
            ip_address (str): Adres IP do usunięcia
            station_type (str, optional): Typ stanowiska  
            admin_user_id (int, optional): ID administratora
            
        Returns:
            bool: True jeśli IP został usunięty
        """
        try:
            normalized_ip = cls._normalize_ip_address(ip_address)
            
            from ..models import ProductionConfig
            
            config_key = f"STATION_ALLOWED_IPS_{station_type.upper()}" if station_type else "STATION_ALLOWED_IPS"
            config = ProductionConfig.query.filter_by(config_key=config_key).first()
            
            if not config:
                return False
            
            current_ips = config.parsed_value
            if normalized_ip in current_ips:
                current_ips.remove(normalized_ip)
                new_value = ','.join(current_ips)
                ProductionConfig.set_config(config_key, new_value, admin_user_id)
                
                # Wyczyszczenie cache
                cls.clear_cache()
                
                logger.info("Usunięto IP z listy dozwolonych", extra={
                    'ip_address': normalized_ip,
                    'station_type': station_type,
                    'admin_user_id': admin_user_id
                })
                
                cls.log_security_event('ip_removed', normalized_ip, {
                    'station_type': station_type,
                    'admin_user_id': admin_user_id
                })
                
                return True
            
            return False
            
        except Exception as e:
            logger.error("Błąd usuwania IP", extra={
                'ip_address': ip_address,
                'station_type': station_type,
                'error': str(e)
            })
            return False

# Middleware Flask dla automatycznej kontroli dostępu
def ip_security_middleware():
    """
    Middleware Flask sprawdzający dostęp IP dla chronionych tras
    
    Automatycznie stosowane przed każdym requestem do modułu production.
    Blokuje dostęp dla nieautoryzowanych IP do stanowisk produkcyjnych.
    
    POPRAWIONE: access_granted nie jest już logowane do prod_errors
    
    Returns:
        None lub Response: None jeśli dostęp dozwolony, 403 jeśli blokowany
    """
    # Sprawdzenie czy request dotyczy chronionej trasy
    if not request.endpoint or not request.path.startswith('/production'):
        return None
    
    # Sprawdzenie czy to jest chroniona trasa stanowiska
    protected_path = False
    station_type = None
    
    for protected_route in IPSecurityService.PROTECTED_ROUTERS:
        if request.path.startswith(protected_route):
            protected_path = True
            # Wykrycie typu stanowiska z URL
            if 'cutting' in request.path:
                station_type = 'cutting'
            elif 'assembly' in request.path:
                station_type = 'assembly'
            elif 'packaging' in request.path:
                station_type = 'packaging'
            break
    
    if not protected_path:
        return None
    
    # Pobranie IP klienta
    client_ip = IPSecurityService.get_client_ip()
    
    # Sprawdzenie dostępu
    if not IPSecurityService.is_ip_allowed(client_ip, station_type):
        # Logowanie nieautoryzowanego dostępu
        IPSecurityService.log_security_event('access_denied', client_ip, {
            'path': request.path,
            'method': request.method,
            'station_type': station_type,
            'user_agent': request.headers.get('User-Agent', 'Unknown')
        })
        
        logger.warning("Zablokowano dostęp z nieautoryzowanego IP", extra={
            'ip_address': client_ip,
            'path': request.path,
            'station_type': station_type,
            'method': request.method
        })
        
        # Zwrócenie błędu 403
        if request.is_json or request.path.startswith('/production/api'):
            return jsonify({
                'error': 'Access denied',
                'message': 'Your IP address is not authorized to access this station',
                'code': 'IP_NOT_AUTHORIZED'
            }), 403
        else:
            abort(403)
    
    # POPRAWIONE: Użyj normalnego loggera zamiast log_security_event
    # access_granted NIE jest błędem, więc nie powinno trafiać do prod_errors
    if current_app.config.get('DEBUG'):
        logger.debug("Dostęp przyznany", extra={
            'ip_address': client_ip,
            'path': request.path,
            'method': request.method,
            'station_type': station_type
        })
    
    return None

# Dekorator dla funkcji wymagających sprawdzenia IP
def require_ip_access(station_type=None):
    """
    Dekorator sprawdzający dostęp IP
    
    Args:
        station_type (str, optional): Typ stanowiska do sprawdzenia
        
    Returns:
        function: Dekorowana funkcja
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            client_ip = IPSecurityService.get_client_ip()
            
            if not IPSecurityService.is_ip_allowed(client_ip, station_type):
                IPSecurityService.log_security_event('access_denied', client_ip, {
                    'function': func.__name__,
                    'station_type': station_type
                })
                
                if request.is_json:
                    return jsonify({
                        'error': 'Access denied',
                        'message': 'Your IP address is not authorized',
                        'code': 'IP_NOT_AUTHORIZED'
                    }), 403
                else:
                    abort(403)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator

# Funkcje pomocnicze
def get_client_ip():
    """Helper function dla pobierania IP klienta"""
    return IPSecurityService.get_client_ip()

def is_ip_allowed(ip_address, station_type=None):
    """Helper function dla sprawdzania IP"""
    return IPSecurityService.is_ip_allowed(ip_address, station_type)

def clear_ip_cache():
    """Helper function dla czyszczenia cache"""
    IPSecurityService.clear_cache()