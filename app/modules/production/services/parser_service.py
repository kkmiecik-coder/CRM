# modules/production/services/parser_service.py
"""
Serwis parsowania nazw produktów dla modułu Production
======================================================

Implementuje inteligentny system parsowania nazw produktów z Baselinker:
- Wykorzystanie istniejącego parsera z modułu reports
- Ekstraktowanie parametrów: gatunek, technologia, klasa, wymiary, wykończenie
- Cache wyników parsowania dla wydajności
- Fallback do wartości domyślnych przy błędach
- Obsługa różnych formatów nazw produktów

Parsowane parametry:
- wood_species (gatunek drewna): Dąb, Buk, Jesion, itp.
- technology (technologia): Klejonka, Deska, Fornir, itp.
- wood_class (klasa drewna): A, B, C, Rustic, itp.
- dimensions (wymiary): długość x szerokość x grubość (cm)
- finish_state (wykończenie): Surowe, Olejowane, Bejcowane, Lakierowane

Autor: Konrad Kmiecik
Wersja: 1.2 (Finalna - z zabezpieczeniami)
Data: 2025-01-08
"""

import re
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from modules.logging import get_structured_logger

logger = get_structured_logger('production.parser')

class ParsingError(Exception):
    """Wyjątek dla błędów parsowania"""
    pass

class ProductNameParser:
    """
    Serwis parsowania nazw produktów z cache'owaniem wyników
    
    Wykorzystuje istniejący parser z modułu reports z dodatkowymi
    funkcjonalnościami specyficznymi dla modułu produkcji.
    """
    
    def __init__(self, cache_duration_minutes=120):
        """
        Inicjalizacja parsera z cache
        
        Args:
            cache_duration_minutes (int): Czas życia cache w minutach
        """
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
        self._parse_cache = {}
        self._cache_timestamps = {}
        self._lock = threading.RLock()
        
        # Import parsera z modułu reports
        self._reports_parser = None
        self._init_reports_parser()
        
        # Wzorce regex dla dodatkowego parsowania
        self._dimension_patterns = [
            r'(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)',  # 120x80x2.5
            r'(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)',        # 120/80/2.5
            r'(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)',        # 120-80-2.5
        ]
        
        # Mapowanie wykończeń
        self._finish_mapping = {
            'surowe': 'surowe',
            'sur': 'surowe',
            'raw': 'surowe',
            'olejowane': 'olejowane', 
            'olej': 'olejowane',
            'oil': 'olejowane',
            'bejcowane': 'bejcowane',
            'bejca': 'bejcowane',
            'stain': 'bejcowane',
            'lakierowane': 'lakierowane',
            'lakier': 'lakierowane',
            'lacquer': 'lakierowane',
            'matt': 'lakierowane_matt',
            'matowe': 'lakierowane_matt',
            'satin': 'lakierowane_satin',
            'satynowe': 'lakierowane_satin',
            'gloss': 'lakierowane_gloss',
            'połysk': 'lakierowane_gloss'
        }
        
        # Mapowanie gatunków drewna
        self._wood_species_mapping = {
            'dab': 'dąb',
            'dąb': 'dąb',
            'dębowa': 'dąb',
            'dębowy': 'dąb',
            'dębowe': 'dąb',
            'oak': 'dąb',
            'buk': 'buk',
            'bukowa': 'buk',
            'bukowy': 'buk', 
            'bukowe': 'buk',
            'beech': 'buk',
            'jesion': 'jesion',
            'jesionowa': 'jesion',
            'jesionowy': 'jesion',
            'jesionowe': 'jesion',
            'ash': 'jesion'
        }

        # Mapowanie klasy drewna
        self._wood_class_mapping = {
            'A/B': 'A/B',
            'a/B': 'A/B',
            'A/b': 'A/B',
            'a/b': 'A/B',
            'a-b': 'A/B',
            'A-B': 'A/B',
            'A-b': 'A/B',
            'a-B': 'A/B',
            'AB': 'A/B', 
            'Ab': 'A/B',
            'aB': 'A/B',
            'ab': 'A/B',
            'B/B': 'B/B',
            'b/B': 'B/B',
            'B/b': 'B/B',
            'b/b': 'B/B',
            'b-b': 'B/B',
            'B-B': 'B/B',
            'B-b': 'B/B',
            'b-B': 'B/B',
            'BB': 'B/B', 
            'Bb': 'B/B',
            'bB': 'B/B',
            'bb': 'B/B'
        }
        
        # Mapowanie technologii
        self._technology_mapping = {
            'lity': 'lity',
            'lita': 'lity',
            'lite': 'lity',
            'mikrowczep': 'mikrowczep'
        }
        
        logger.info("Inicjalizacja ProductNameParser", extra={
            'cache_duration_minutes': cache_duration_minutes,
            'reports_parser_available': self._reports_parser is not None
        })
    
    def _init_reports_parser(self):
        """ Inicjalizacja parsera z modułu reports """
        try:
            from modules.reports.parser import ProductNameParser as ReportsProductNameParser
            reports_parser_instance = ReportsProductNameParser()
            self._reports_parser = reports_parser_instance.parse_product_name
            logger.info("Zainicjalizowano parser z modułu reports")
        
        except ImportError as e:
            logger.warning("Nie można zaimportować parsera z modułu reports", extra={
                'error': str(e),
                'fallback': 'Używanie wbudowanego parsera'
            })
            self._reports_parser = None
        
        except Exception as e:
            logger.warning("Błąd inicjalizacji parsera z modułu reports", extra={
                'error': str(e),
                'fallback': 'Używanie wbudowanego parsera'
            })
            self._reports_parser = None
    
    def parse_product_name(self, product_name: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Parsuje nazwę produktu i zwraca strukturalne dane
        
        Args:
            product_name (str): Nazwa produktu do sparsowania
            use_cache (bool): Czy używać cache
            
        Returns:
            Dict[str, Any]: Słownik z sparsowanymi parametrami:
            {
                'wood_species': str,        # Gatunek drewna
                'technology': str,          # Technologia
                'wood_class': str,          # Klasa drewna  
                'length_cm': float,         # Długość w cm
                'width_cm': float,          # Szerokość w cm
                'thickness_cm': float,      # Grubość w cm
                'finish_state': str,        # Stan wykończenia
                'volume_m3': float,         # Objętość w m³ (jeśli wymiary dostępne)
                'parsing_success': bool,    # Czy parsowanie się udało
                'parsing_confidence': float, # Pewność parsowania (0-1)
                'original_name': str,       # Oryginalna nazwa
                'parsing_errors': List[str] # Lista błędów parsowania
            }
        """
        if not product_name or not isinstance(product_name, str):
            return self._get_default_parsing_result(product_name or '', 
                                                  errors=['Pusta lub nieprawidłowa nazwa produktu'])
        
        # Normalizacja nazwy produktu
        normalized_name = self._normalize_product_name(product_name)
        
        # Sprawdzenie cache
        if use_cache:
            with self._lock:
                cache_key = self._get_cache_key(normalized_name)
                if self._is_cache_valid(cache_key):
                    logger.debug("Wynik parsowania z cache", extra={
                        'product_name': product_name[:50]
                    })
                    return self._parse_cache[cache_key].copy()
        
        try:
            # Parsowanie główne
            result = self._perform_parsing(normalized_name, product_name)
            
            # Zapisanie w cache
            if use_cache:
                with self._lock:
                    cache_key = self._get_cache_key(normalized_name)
                    self._parse_cache[cache_key] = result.copy()
                    self._cache_timestamps[cache_key] = datetime.now()
            
            logger.info("Sparsowano nazwę produktu", extra={
                'product_name': product_name[:50],
                'parsing_success': result['parsing_success'],
                'confidence': result['parsing_confidence'],
                'wood_species': result.get('wood_species'),
                'technology': result.get('technology'),
                'dimensions': f"{result.get('length_cm')}x{result.get('width_cm')}x{result.get('thickness_cm')}"
            })
            
            return result
            
        except Exception as e:
            logger.error("Błąd parsowania nazwy produktu", extra={
                'product_name': product_name,
                'error': str(e)
            })
            return self._get_default_parsing_result(product_name, 
                                                  errors=[f'Błąd parsowania: {str(e)}'])
    
    def _normalize_product_name(self, product_name: str) -> str:
        """
        Normalizuje nazwę produktu do parsowania
        
        Args:
            product_name (str): Oryginalna nazwa
            
        Returns:
            str: Znormalizowana nazwa
        """
        # Podstawowe czyszczenie
        normalized = product_name.strip().lower()
        
        # Usunięcie nadmiarowych spacji
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Zamiana przecinków na kropki w liczbach
        normalized = re.sub(r'(\d+),(\d+)', r'\1.\2', normalized)
        
        # Standardizacja separatorów wymiarów
        normalized = re.sub(r'\s*[x×]\s*', 'x', normalized)
        
        return normalized
    
    def _perform_parsing(self, normalized_name: str, original_name: str) -> Dict[str, Any]:
        """
        Wykonuje faktyczne parsowanie nazwy produktu
        
        Args:
            normalized_name (str): Znormalizowana nazwa
            original_name (str): Oryginalna nazwa
            
        Returns:
            Dict[str, Any]: Wynik parsowania
        """
        result = self._get_default_parsing_result(original_name)
        errors = []
        confidence_factors = []
        
        try:
            # 1. Próba parsowania przez parser z modułu reports
            if self._reports_parser:
                try:
                    reports_result = self._reports_parser(original_name) if self._reports_parser else None
                    if reports_result and isinstance(reports_result, dict):
                        result.update(self._map_reports_parser_result(reports_result))
                        confidence_factors.append(0.8)
                        logger.debug("Użyto parsera z modułu reports", extra={
                            'parsed_fields': list(reports_result.keys())
                        })
                    else:
                        errors.append("Parser reports zwrócił pusty wynik")
                except Exception as e:
                    errors.append(f"Błąd parsera reports: {str(e)}")
                    logger.debug("Błąd parsera reports, używam wbudowanego", extra={
                        'error': str(e)
                    })
            
            # 2. Parsowanie wymiarów
            dimensions = self._parse_dimensions(normalized_name)
            if dimensions:
                result.update(dimensions)
                confidence_factors.append(0.9)  # Wymiary są bardzo pewne
            else:
                errors.append("Nie znaleziono wymiarów w nazwie")
            
            # 3. Parsowanie gatunku drewna
            wood_species = self._parse_wood_species(normalized_name)
            if wood_species:
                result['wood_species'] = wood_species
                confidence_factors.append(0.7)
            else:
                errors.append("Nie rozpoznano gatunku drewna")
            
            # 4. Parsowanie technologii
            technology = self._parse_technology(normalized_name)
            if technology:
                result['technology'] = technology
                confidence_factors.append(0.6)
            else:
                errors.append("Nie rozpoznano technologii")
            
            # 5. Parsowanie wykończenia
            finish_state = self._parse_finish_state(normalized_name)
            if finish_state:
                result['finish_state'] = finish_state
                confidence_factors.append(0.6)
            else:
                # Domyślnie surowe jeśli nie znaleziono wykończenia
                result['finish_state'] = 'surowe'
            
            # 6. Parsowanie klasy drewna
            wood_class = self._parse_wood_class(normalized_name)
            if wood_class:
                result['wood_class'] = wood_class
                confidence_factors.append(0.5)
            else:
                errors.append("Nie rozpoznano klasy drewna")
            
            # 7. Obliczenie objętości jeśli mamy wymiary
            if all(result.get(dim) for dim in ['length_cm', 'width_cm', 'thickness_cm']):
                try:
                    volume = (result['length_cm'] * result['width_cm'] * result['thickness_cm']) / 1000000  # cm³ na m³
                    result['volume_m3'] = round(volume, 6)
                    confidence_factors.append(0.9)  # Objętość jest bardzo pewna jeśli mamy wymiary
                except (ValueError, TypeError):
                    errors.append("Błąd obliczania objętości")
            
            # 8. Obliczenie ogólnej pewności parsowania
            if confidence_factors:
                result['parsing_confidence'] = sum(confidence_factors) / len(confidence_factors)
                result['parsing_success'] = result['parsing_confidence'] > 0.3
            else:
                result['parsing_confidence'] = 0.0
                result['parsing_success'] = False
            
            result['parsing_errors'] = errors
            
            return result
            
        except Exception as e:
            logger.error("Błąd podczas parsowania", extra={
                'normalized_name': normalized_name,
                'error': str(e)
            })
            result['parsing_errors'] = errors + [f"Błąd ogólny: {str(e)}"]
            return result
    
    def _map_reports_parser_result(self, reports_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mapuje wynik parsera z modułu reports na format produkcyjny
        
        Args:
            reports_result (Dict[str, Any]): Wynik z parsera reports
            
        Returns:
            Dict[str, Any]: Zmapowany wynik
        """
        mapped = {}
        
        # Mapowanie pól
        field_mapping = {
            'species': 'wood_species',
            'technology': 'technology', 
            'wood_class': 'wood_class',
            'length': 'length_cm',
            'width': 'width_cm',
            'thickness': 'thickness_cm',
            'finish': 'finish_state'
        }
        
        for reports_field, production_field in field_mapping.items():
            if reports_field in reports_result and reports_result[reports_field]:
                mapped[production_field] = reports_result[reports_field]
        
        return mapped
    
    def _parse_dimensions(self, name: str) -> Optional[Dict[str, float]]:
        """
        Parsuje wymiary z nazwy produktu
        
        Args:
            name (str): Nazwa do parsowania
            
        Returns:
            Optional[Dict[str, float]]: Słownik z wymiarami lub None
        """
        for pattern in self._dimension_patterns:
            match = re.search(pattern, name)
            if match:
                try:
                    dims = [float(dim.replace(',', '.')) for dim in match.groups()]
                    
                    # Sortowanie wymiarów: długość (największy) > szerokość > grubość (najmniejszy)
                    dims_sorted = sorted(dims, reverse=True)
                    
                    return {
                        'length_cm': dims_sorted[0],
                        'width_cm': dims_sorted[1], 
                        'thickness_cm': dims_sorted[2]
                    }
                except (ValueError, IndexError):
                    continue
        
        return None
    
    def _parse_wood_species(self, name: str) -> Optional[str]:
        """
        Parsuje gatunek drewna z nazwy
        
        Args:
            name (str): Nazwa do parsowania
            
        Returns:
            Optional[str]: Gatunek drewna lub None
        """
        for key, species in self._wood_species_mapping.items():
            if key in name:
                return species
        
        return None
    
    def _parse_technology(self, name: str) -> Optional[str]:
        """
        Parsuje technologię z nazwy
        
        Args:
            name (str): Nazwa do parsowania
            
        Returns:
            Optional[str]: Technologia lub None
        """
        for key, tech in self._technology_mapping.items():
            if key in name:
                return tech
        
        # Domyślna technologia na podstawie innych wskazówek
        if 'solid' in name or 'jednolita' in name:
            return 'deska'
        elif 'glued' in name or 'klejona' in name:
            return 'klejonka'
        
        return None
    
    def _parse_finish_state(self, name: str) -> Optional[str]:
        """
        Parsuje stan wykończenia z nazwy
        
        Args:
            name (str): Nazwa do parsowania
            
        Returns:
            Optional[str]: Stan wykończenia lub None
        """
        for key, finish in self._finish_mapping.items():
            if key in name:
                return finish
        
        return None
    
    def _parse_wood_class(self, name: str) -> Optional[str]:
        """
        Parsuje klase drewna z nazwy
        
        Args:
            name (str): Nazwa do parsowania
            
        Returns:
            Optional[str]: Klasa wykończenia lub None
        """
        for key, finish in self._wood_class_mapping.items():
            if key in name:
                return finish
        
        return None
    
    def _get_default_parsing_result(self, original_name: str, errors: List[str] = None) -> Dict[str, Any]:
        """
        Zwraca domyślny wynik parsowania
        
        Args:
            original_name (str): Oryginalna nazwa produktu
            errors (List[str], optional): Lista błędów
            
        Returns:
            Dict[str, Any]: Domyślny wynik
        """
        return {
            'wood_species': None,
            'technology': None,
            'wood_class': None,
            'length_cm': None,
            'width_cm': None,
            'thickness_cm': None,
            'finish_state': 'surowe',  # Domyślne wykończenie
            'volume_m3': None,
            'parsing_success': False,
            'parsing_confidence': 0.0,
            'original_name': original_name,
            'parsing_errors': errors or []
        }
    
    def _get_cache_key(self, normalized_name: str) -> str:
        """
        Generuje klucz cache dla nazwy produktu
        
        Args:
            normalized_name (str): Znormalizowana nazwa
            
        Returns:
            str: Klucz cache
        """
        import hashlib
        return hashlib.md5(normalized_name.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """
        Sprawdza czy wpis w cache jest ważny
        
        Args:
            cache_key (str): Klucz cache
            
        Returns:
            bool: True jeśli cache jest ważny
        """
        if cache_key not in self._parse_cache:
            return False
            
        if cache_key not in self._cache_timestamps:
            return False
            
        cache_age = datetime.now() - self._cache_timestamps[cache_key]
        return cache_age < self.cache_duration
    
    def invalidate_cache(self):
        """Invaliduje cały cache parsowania"""
        with self._lock:
            self._parse_cache.clear()
            self._cache_timestamps.clear()
            
        logger.info("Invalidated parser cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Pobiera statystyki cache
        
        Returns:
            Dict[str, Any]: Statystyki cache
        """
        with self._lock:
            now = datetime.now()
            valid_entries = 0
            
            for key in self._cache_timestamps:
                if (now - self._cache_timestamps[key]) < self.cache_duration:
                    valid_entries += 1
            
            return {
                'total_entries': len(self._parse_cache),
                'valid_entries': valid_entries,
                'expired_entries': len(self._parse_cache) - valid_entries,
                'cache_duration_minutes': self.cache_duration.total_seconds() / 60,
                'cache_hit_ratio': self._calculate_hit_ratio()
            }
    
    def _calculate_hit_ratio(self) -> float:
        """Oblicza współczynnik trafień cache (placeholder)"""
        # W pełnej implementacji można by śledzić hits/misses
        return 0.0
    
    def parse_multiple_products(self, product_names: List[str], use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Parsuje wiele nazw produktów jednocześnie
        
        Args:
            product_names (List[str]): Lista nazw do sparsowania
            use_cache (bool): Czy używać cache
            
        Returns:
            List[Dict[str, Any]]: Lista wyników parsowania
        """
        results = []
        
        for name in product_names:
            try:
                result = self.parse_product_name(name, use_cache)
                results.append(result)
            except Exception as e:
                logger.error("Błąd parsowania w batch", extra={
                    'product_name': name,
                    'error': str(e)
                })
                results.append(self._get_default_parsing_result(name, [str(e)]))
        
        success_count = sum(1 for r in results if r['parsing_success'])
        
        logger.info("Sparsowano batch nazw produktów", extra={
            'total_count': len(product_names),
            'success_count': success_count,
            'success_rate': success_count / len(product_names) if product_names else 0
        })
        
        return results
    
    def validate_parsing_result(self, result: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Waliduje wynik parsowania i zwraca uwagi/ostrzeżenia
        
        Args:
            result (Dict[str, Any]): Wynik parsowania do walidacji
            
        Returns:
            Dict[str, List[str]]: Słownik z uwagami ('warnings', 'errors', 'suggestions')
        """
        validation = {
            'warnings': [],
            'errors': [],
            'suggestions': []
        }
        
        # Sprawdzenie wymiarów
        if result.get('length_cm') and result.get('width_cm') and result.get('thickness_cm'):
            if result['length_cm'] < result['width_cm']:
                validation['warnings'].append("Długość jest mniejsza od szerokości - sprawdź kolejność wymiarów")
            
            if result['thickness_cm'] > 10:
                validation['warnings'].append("Grubość wydaje się bardzo duża (>10cm)")
            
            if result['thickness_cm'] < 0.5:
                validation['warnings'].append("Grubość wydaje się bardzo mała (<0.5cm)")
        else:
            validation['errors'].append("Brak kompletnych wymiarów produktu")
        
        # Sprawdzenie gatunku
        if not result.get('wood_species'):
            validation['suggestions'].append("Rozważ dodanie gatunku drewna do nazwy produktu")
        
        # Sprawdzenie technologii
        if not result.get('technology'):
            validation['suggestions'].append("Rozważ sprecyzowanie technologii (klejonka/deska)")
        
        # Sprawdzenie pewności parsowania
        if result.get('parsing_confidence', 0) < 0.5:
            validation['warnings'].append("Niska pewność parsowania - sprawdź wyniki ręcznie")
        
        return validation

# Singleton instance dla globalnego dostępu
_parser_instance = None
_parser_lock = threading.Lock()

def get_parser_service() -> ProductNameParser:
    """
    Pobiera singleton instance ProductNameParser
    
    Returns:
        ProductNameParser: Instancja parsera
    """
    global _parser_instance
    
    if _parser_instance is None:
        with _parser_lock:
            if _parser_instance is None:
                _parser_instance = ProductNameParser()
                logger.info("Utworzono singleton ProductNameParser")
    
    return _parser_instance

# Funkcje pomocnicze
def parse_product_name(product_name: str, use_cache: bool = True) -> Dict[str, Any]:
    """Helper function dla parsowania nazwy produktu"""
    return get_parser_service().parse_product_name(product_name, use_cache)

def parse_multiple_products(product_names: List[str], use_cache: bool = True) -> List[Dict[str, Any]]:
    """Helper function dla parsowania wielu produktów"""
    return get_parser_service().parse_multiple_products(product_names, use_cache)

def invalidate_parser_cache():
    """Helper function dla invalidacji cache parsera"""
    get_parser_service().invalidate_cache()