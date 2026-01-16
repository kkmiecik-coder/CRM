# modules/production/services/baselinker_status_cache.py
"""
Serwis Cache Statusów Baselinker
===============================

Implementuje cache'owanie statusów z Baselinker API w tabeli prod_config:
- Automatyczne pobieranie statusów z API przy pierwszym wywołaniu
- Cache z 7-dniowym TTL (Time To Live)
- Automatyczne odświeżanie przy przedawnieniu cache
- Inteligentne sortowanie według workflow produkcyjnego
- Obsługa błędów z fallback statusami
- Niestandardowe mapowanie kolejności w prod_config

Workflow sortowania:
1. Niestandardowe mapowanie z prod_config (najwyższy priorytet)
2. Wzorce nazw dla automatycznego kategoryzowania
3. Fallback - nieznane statusy na końcu listy

Autor: System
Wersja: 1.0
Data: 2025-01-17
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from modules.logging import get_structured_logger

logger = get_structured_logger('production.baselinker_cache')

class BaselinkerStatusCacheService:
    """
    Serwis zarządzania cache statusów Baselinker
    
    Zapewnia wydajne pobieranie statusów z automatycznym odświeżaniem,
    inteligentnym sortowaniem i obsługą błędów.
    """
    
    # Konfiguracja cache
    CACHE_KEY = 'BASELINKER_STATUSES_CACHE'
    CACHE_TTL_DAYS = 7
    CUSTOM_ORDER_KEY = 'baselinker_status_custom_order'
    
    # Wzorce nazw dla automatycznego sortowania (od najbardziej do najmniej specyficznych)
    STATUS_CATEGORY_PATTERNS = {
        'nowe_nieoplacone': {'pattern': ['nowe', 'nieopłacone'], 'order': 1},
        'nowe_oplacone': {'pattern': ['nowe', 'opłacone'], 'order': 2},
        
        'produkcja_surowe': {'pattern': ['produkcji', 'surowe'], 'order': 10},
        'produkcja_olejowanie': {'pattern': ['produkcji', 'olejowanie'], 'order': 11},
        'produkcja_bejcowanie': {'pattern': ['produkcji', 'bejcowanie'], 'order': 12},
        'produkcja_lakierowanie': {'pattern': ['produkcji', 'lakierowanie'], 'order': 13},
        'produkcja_suszenie': {'pattern': ['produkcji', 'suszenie'], 'order': 14},
        'produkcja_inne': {'pattern': ['produkcji'], 'order': 15},  # Fallback dla innych produkcji
        
        'produkcja_zakonczona': {'pattern': ['produkcja', 'zakończona'], 'order': 20},
        
        'spakowane': {'pattern': ['spakowane'], 'order': 30},
        'zgloszona_wysylka': {'pattern': ['zgłoszona', 'wysyłki'], 'order': 31},
        'wyslane_kurier': {'pattern': ['wysłane', 'kurier'], 'order': 32},
        'wyslane_transport': {'pattern': ['wysłane', 'transport'], 'order': 33},
        
        'czeka_odbior': {'pattern': ['czeka', 'odbiór'], 'order': 40},
        'dostarczona_kurier': {'pattern': ['dostarczona', 'kurier'], 'order': 41},
        'dostarczona_transport': {'pattern': ['dostarczona', 'transport'], 'order': 42},
        'odebrane': {'pattern': ['odebrane'], 'order': 43},
        
        'reklamacja': {'pattern': ['reklamacja'], 'order': 90},
        'anulowane': {'pattern': ['anulowane'], 'order': 91}
    }
    
    # Fallback statusy na wypadek błędu API (posortowane wg workflow)
    FALLBACK_STATUSES = [
        {'id': 155824, 'name': 'Nowe - opłacone'},
        {'id': 138619, 'name': 'W produkcji - surowe'},
        {'id': 138620, 'name': 'Produkcja zakończona'},
        {'id': 138623, 'name': 'Zamówienie spakowane'}
    ]
    
    def __init__(self):
        """Inicjalizacja serwisu cache statusów"""
        logger.info("Inicjalizacja BaselinkerStatusCacheService", extra={
            'cache_key': self.CACHE_KEY,
            'ttl_days': self.CACHE_TTL_DAYS,
            'pattern_categories': len(self.STATUS_CATEGORY_PATTERNS)
        })
    
    def get_statuses(self, user_id: Optional[int] = None) -> Tuple[List[Dict], bool, float]:
        """
        Pobiera statusy Baselinker z cache lub API (posortowane według workflow)
        
        Args:
            user_id (int, optional): ID użytkownika dla logowania
            
        Returns:
            Tuple[List[Dict], bool, float]: (statusy_posortowane, czy_z_cache, wiek_cache_w_godzinach)
        """
        try:
            logger.info("Pobieranie statusów Baselinker", extra={
                'user_id': user_id,
                'cache_key': self.CACHE_KEY
            })
            
            # Sprawdź cache
            cached_data, cache_age_hours = self._get_cached_statuses()
            
            if cached_data and cache_age_hours < (self.CACHE_TTL_DAYS * 24):
                # Cache ważny - zwróć z cache (posortowane)
                sorted_statuses = self._sort_statuses_by_workflow(cached_data)
                logger.info("Użyto cache statusów Baselinker", extra={
                    'cache_age_hours': round(cache_age_hours, 2),
                    'statuses_count': len(sorted_statuses),
                    'user_id': user_id
                })
                return sorted_statuses, True, cache_age_hours
            
            # Cache przedawniony lub brak - pobierz z API
            logger.info("Cache przedawniony - pobieranie z API", extra={
                'cache_age_hours': round(cache_age_hours, 2) if cache_age_hours else None,
                'ttl_hours': self.CACHE_TTL_DAYS * 24
            })
            
            api_statuses = self._fetch_statuses_from_api()
            
            if api_statuses:
                # Posortuj według workflow przed zapisem do cache
                sorted_statuses = self._sort_statuses_by_workflow(api_statuses)
                # Zapisz posortowane do cache
                self._save_statuses_to_cache(sorted_statuses, user_id)
                logger.info("Statusy pobrane z API, posortowane i zapisane do cache", extra={
                    'statuses_count': len(sorted_statuses),
                    'user_id': user_id
                })
                return sorted_statuses, False, 0.0
            else:
                # Błąd API - użyj fallback (już posortowane)
                logger.warning("Błąd API - użyto fallback statusów", extra={
                    'fallback_count': len(self.FALLBACK_STATUSES),
                    'user_id': user_id
                })
                return self.FALLBACK_STATUSES, False, 0.0
                
        except Exception as e:
            logger.error("Błąd pobierania statusów Baselinker", extra={
                'error': str(e),
                'user_id': user_id
            })
            # W przypadku błędu zwróć fallback
            return self.FALLBACK_STATUSES, False, 0.0
    
    def _get_cached_statuses(self) -> Tuple[Optional[List[Dict]], Optional[float]]:
        """
        Pobiera statusy z cache w prod_config
        
        Returns:
            Tuple[Optional[List[Dict]], Optional[float]]: (statusy, wiek_cache_w_godzinach)
        """
        try:
            from .config_service import get_config_service
            config_service = get_config_service()
            
            if not config_service:
                logger.warning("Nie można zainicjować ProductionConfigService")
                return None, None
            
            # Pobierz dane cache z prod_config
            cached_value = config_service.get_config(self.CACHE_KEY, default=None)
            
            if not cached_value:
                logger.debug("Brak cache statusów w prod_config")
                return None, None
            
            # Parse JSON cache
            try:
                cache_data = json.loads(cached_value) if isinstance(cached_value, str) else cached_value
            except json.JSONDecodeError as e:
                logger.warning("Błędny format JSON w cache statusów", extra={'error': str(e)})
                return None, None
            
            # Sprawdź strukturę cache
            if not isinstance(cache_data, dict) or 'statuses' not in cache_data or 'timestamp' not in cache_data:
                logger.warning("Nieprawidłowa struktura cache statusów", extra={
                    'cache_keys': list(cache_data.keys()) if isinstance(cache_data, dict) else 'NOT_DICT'
                })
                return None, None
            
            # Oblicz wiek cache
            try:
                cache_timestamp = cache_data['timestamp']
                cache_dt = datetime.fromisoformat(cache_timestamp.replace('Z', '+00:00'))
                cache_age = datetime.utcnow() - cache_dt.replace(tzinfo=None)
                cache_age_hours = cache_age.total_seconds() / 3600
                
                statuses = cache_data['statuses']
                
                logger.debug("Znaleziono cache statusów", extra={
                    'cache_age_hours': round(cache_age_hours, 2),
                    'statuses_count': len(statuses),
                    'cache_timestamp': cache_timestamp
                })
                
                return statuses, cache_age_hours
                
            except (ValueError, KeyError) as e:
                logger.warning("Błąd parsowania timestamp cache", extra={'error': str(e)})
                return None, None
            
        except Exception as e:
            logger.error("Błąd odczytu cache statusów", extra={'error': str(e)})
            return None, None
    
    def _fetch_statuses_from_api(self) -> Optional[List[Dict]]:
        """
        Pobiera statusy z Baselinker API
        
        Returns:
            Optional[List[Dict]]: Lista statusów lub None przy błędzie
        """
        try:
            from .sync_service import get_sync_service
            sync_service = get_sync_service()
            
            if not sync_service:
                logger.error("Nie można zainicjować BaselinkerSyncService")
                return None
            
            # Pobierz statusy przez istniejącą metodę
            api_statuses = sync_service.get_baselinker_statuses()
            
            if not api_statuses:
                logger.warning("Brak statusów w odpowiedzi API")
                return None
            
            # Konwertuj format {id: name} na [{'id': id, 'name': name}]
            formatted_statuses = [
                {
                    'id': int(status_id),
                    'name': status_name
                }
                for status_id, status_name in api_statuses.items()
            ]
            
            logger.debug("Sformatowano statusy z API", extra={
                'original_count': len(api_statuses),
                'formatted_count': len(formatted_statuses)
            })
            
            return formatted_statuses
            
        except Exception as e:
            logger.error("Błąd pobierania statusów z API", extra={
                'error': str(e),
                'error_type': type(e).__name__
            })
            return None
    
    def _save_statuses_to_cache(self, statuses: List[Dict], user_id: Optional[int] = None) -> bool:
        """
        Zapisuje statusy do cache w prod_config
        
        Args:
            statuses (List[Dict]): Lista statusów do zapisania
            user_id (int, optional): ID użytkownika
            
        Returns:
            bool: True jeśli zapis udany
        """
        try:
            from .config_service import get_config_service
            config_service = get_config_service()
            
            if not config_service:
                logger.error("Nie można zainicjować ProductionConfigService")
                return False
            
            # Przygotuj dane do cache
            cache_data = {
                'statuses': statuses,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'source': 'baselinker_api',
                'cached_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'ttl_days': self.CACHE_TTL_DAYS
            }
            
            # Zapisz do prod_config
            success = config_service.set_config(
                key=self.CACHE_KEY,
                value=json.dumps(cache_data),
                config_type='json',
                user_id=user_id,
                description=f'Cache statusów Baselinker ({self.CACHE_TTL_DAYS} dni TTL)'
            )
            
            if success:
                logger.info("Zapisano statusy do cache", extra={
                    'statuses_count': len(statuses),
                    'user_id': user_id,
                    'cache_key': self.CACHE_KEY
                })
            else:
                logger.error("Błąd zapisu statusów do cache")
            
            return success
            
        except Exception as e:
            logger.error("Błąd zapisu cache statusów", extra={
                'error': str(e),
                'statuses_count': len(statuses),
                'user_id': user_id
            })
            return False
    
    def _load_custom_status_mapping(self) -> Dict[str, int]:
        """
        Ładuje niestandardowe mapowanie statusów z prod_config
        
        Returns:
            Dict[str, int]: Mapowanie {nazwa_statusu: kolejność}
        """
        try:
            from .config_service import get_config_service
            config_service = get_config_service()
            
            if not config_service:
                return {}
            
            # Klucz w prod_config dla niestandardowego mapowania
            custom_mapping_json = config_service.get_config(
                self.CUSTOM_ORDER_KEY, 
                default=None
            )
            
            if custom_mapping_json:
                try:
                    custom_mapping = json.loads(custom_mapping_json) if isinstance(custom_mapping_json, str) else custom_mapping_json
                    logger.debug("Załadowano niestandardowe mapowanie statusów", extra={
                        'custom_mappings_count': len(custom_mapping)
                    })
                    return custom_mapping
                except json.JSONDecodeError as e:
                    logger.warning("Błędny format niestandardowego mapowania statusów", extra={'error': str(e)})
            
            return {}
            
        except Exception as e:
            logger.error("Błąd ładowania niestandardowego mapowania statusów", extra={'error': str(e)})
            return {}
    
    def _get_status_order_by_name(self, status_name: str) -> int:
        """
        Określa kolejność statusu na podstawie nazwy (niestandardowe mapowanie + wzorce)
        
        Args:
            status_name (str): Nazwa statusu
            
        Returns:
            int: Numer kolejności (niższy = wcześniej)
        """
        if not status_name:
            return 999
        
        # Sprawdź niestandardowe mapowanie (ma priorytet)
        custom_mapping = self._load_custom_status_mapping()
        if status_name in custom_mapping:
            custom_order = custom_mapping[status_name]
            logger.debug("Użyto niestandardowego mapowania", extra={
                'status_name': status_name,
                'custom_order': custom_order
            })
            return custom_order
        
        status_lower = status_name.lower().strip()
        
        # Sprawdź wzorce w kolejności od najbardziej specyficznych
        for category, config in self.STATUS_CATEGORY_PATTERNS.items():
            patterns = config['pattern']
            
            # Sprawdź czy wszystkie wzorce występują w nazwie
            if all(pattern.lower() in status_lower for pattern in patterns):
                logger.debug("Dopasowano status do kategorii", extra={
                    'status_name': status_name,
                    'category': category,
                    'order': config['order'],
                    'matched_patterns': patterns
                })
                return config['order']
        
        # Brak dopasowania - status nieznany (na końcu)
        logger.warning("Nieznany status - brak dopasowania wzorca", extra={
            'status_name': status_name,
            'assigned_order': 999,
            'suggestion': f'Rozważ dodanie niestandardowego mapowania: {self.CUSTOM_ORDER_KEY}'
        })
        return 999
    
    def _sort_statuses_by_workflow(self, statuses: List[Dict]) -> List[Dict]:
        """
        Sortuje statusy według kolejności w workflow produkcyjnym (oparty na nazwach)
        
        Args:
            statuses (List[Dict]): Lista statusów do posortowania
            
        Returns:
            List[Dict]: Posortowana lista statusów
        """
        def get_sort_order(status):
            status_name = status.get('name', '')
            order = self._get_status_order_by_name(status_name)
            
            # Drugorzędne sortowanie alfabetyczne w ramach tej samej kategorii
            return (order, status_name.lower())
        
        sorted_statuses = sorted(statuses, key=get_sort_order)
        
        # Loguj informacje o sortowaniu
        sort_info = [
            {
                'id': s.get('id'),
                'name': s.get('name'),
                'order': self._get_status_order_by_name(s.get('name', ''))
            }
            for s in sorted_statuses[:5]  # Pierwszych 5 dla logowania
        ]
        
        unknown_count = len([s for s in statuses if self._get_status_order_by_name(s.get('name', '')) == 999])
        
        logger.info("Posortowano statusy według workflow", extra={
            'original_count': len(statuses),
            'sorted_count': len(sorted_statuses),
            'first_5_statuses': sort_info,
            'unknown_statuses_count': unknown_count
        })
        
        return sorted_statuses
    
    def update_custom_status_order(self, status_name: str, order: int, user_id: Optional[int] = None) -> bool:
        """
        Aktualizuje niestandardową kolejność dla konkretnego statusu
        
        Args:
            status_name (str): Nazwa statusu
            order (int): Nowa kolejność
            user_id (int, optional): ID użytkownika
            
        Returns:
            bool: True jeśli aktualizacja udana
        """
        try:
            from .config_service import get_config_service
            config_service = get_config_service()
            
            if not config_service:
                return False
            
            # Pobierz aktualne mapowanie
            current_mapping = self._load_custom_status_mapping()
            
            # Dodaj/zaktualizuj mapowanie
            current_mapping[status_name] = order
            
            # Zapisz z powrotem do prod_config
            success = config_service.set_config(
                key=self.CUSTOM_ORDER_KEY,
                value=json.dumps(current_mapping),
                config_type='json',
                user_id=user_id,
                description='Niestandardowe mapowanie kolejności statusów Baselinker'
            )
            
            if success:
                logger.info("Zaktualizowano niestandardową kolejność statusu", extra={
                    'status_name': status_name,
                    'new_order': order,
                    'user_id': user_id
                })
            
            return success
            
        except Exception as e:
            logger.error("Błąd aktualizacji niestandardowej kolejności statusu", extra={
                'status_name': status_name,
                'order': order,
                'error': str(e)
            })
            return False
    
    def invalidate_cache(self, user_id: Optional[int] = None) -> bool:
        """
        Invaliduje cache statusów (usuwa z prod_config)
        
        Args:
            user_id (int, optional): ID użytkownika
            
        Returns:
            bool: True jeśli usunięcie udane
        """
        try:
            from .config_service import get_config_service
            config_service = get_config_service()
            
            if not config_service:
                logger.error("Nie można zainicjować ProductionConfigService")
                return False
            
            # Usuń cache (ustaw wartość na pusty string)
            success = config_service.set_config(
                key=self.CACHE_KEY,
                value='',
                config_type='json',
                user_id=user_id,
                description='Cache statusów Baselinker (invalidated)'
            )
            
            logger.info("Invalidowano cache statusów", extra={
                'user_id': user_id,
                'cache_key': self.CACHE_KEY
            })
            
            return success
            
        except Exception as e:
            logger.error("Błąd invalidacji cache statusów", extra={
                'error': str(e),
                'user_id': user_id
            })
            return False


# Singleton instance dla globalnego dostępu
_status_cache_instance = None

def get_status_cache_service() -> BaselinkerStatusCacheService:
    """
    Pobiera singleton instance BaselinkerStatusCacheService
    
    Returns:
        BaselinkerStatusCacheService: Instancja serwisu cache statusów
    """
    global _status_cache_instance
    
    if _status_cache_instance is None:
        _status_cache_instance = BaselinkerStatusCacheService()
        logger.info("Utworzono singleton BaselinkerStatusCacheService")
    
    return _status_cache_instance

# Helper functions
def get_baselinker_statuses(user_id: Optional[int] = None) -> Tuple[List[Dict], bool, float]:
    """
    Helper function dla pobierania statusów Baselinker
    
    Args:
        user_id (int, optional): ID użytkownika
        
    Returns:
        Tuple[List[Dict], bool, float]: (statusy, czy_z_cache, wiek_cache_w_godzinach)
    """
    return get_status_cache_service().get_statuses(user_id)

def update_status_order(status_name: str, order: int, user_id: Optional[int] = None) -> bool:
    """
    Helper function dla aktualizacji kolejności statusu
    
    Args:
        status_name (str): Nazwa statusu
        order (int): Nowa kolejność
        user_id (int, optional): ID użytkownika
        
    Returns:
        bool: True jeśli aktualizacja udana
    """
    return get_status_cache_service().update_custom_status_order(status_name, order, user_id)

def invalidate_baselinker_statuses_cache(user_id: Optional[int] = None) -> bool:
    """
    Helper function dla invalidacji cache statusów
    
    Args:
        user_id (int, optional): ID użytkownika
        
    Returns:
        bool: True jeśli invalidacja udana
    """
    return get_status_cache_service().invalidate_cache(user_id)