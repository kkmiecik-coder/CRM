
# modules/production/services/id_generator.py - POPRAWIONA LOGIKA
"""
Generator ID produktów - POPRAWIONA WERSJA
Zgodna ze specyfikacją: YY_XXXXX_ZZ
"""

import re
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from extensions import db
from modules.logging import get_structured_logger
import threading
import sys

logger = get_structured_logger('production.id_generator')

class ProductIDGeneratorError(Exception):
    """Wyjątek dla błędów generatora ID"""
    pass

class ProductIDGenerator:
    """
    Generator unikalnych ID produktów - POPRAWIONA WERSJA
    
    Format: YY_XXXXX_ZZ gdzie:
    - YY = rok (25 dla 2025)
    - XXXXX = numer zamówienia (unikalny, inkrementalny)
    - ZZ = numer produktu w zamówieniu (1, 2, 3...)
    """

    # Cache dla mapowania baselinker_order_id -> internal_order_number
    _order_mapping_cache = {}
    _cache_lock = threading.Lock() if 'threading' in sys.modules else None
    
    # Pattern dla walidacji formatu ID
    PRODUCT_ID_PATTERN = re.compile(r'^(\d{2})_(\d{5})_(\d+)$')
    INTERNAL_ORDER_PATTERN = re.compile(r'^(\d{2})_(\d{5})$')

    @classmethod
    def generate_product_id_for_order(cls, baselinker_order_id, total_products_count):
        """
        POPRAWIONA WERSJA: Generuje ID zgodnie ze specyfikacją
        
        Logika:
        1. Sprawdź czy zamówienie już istnieje
        2. Jeśli TAK - użyj istniejącego internal_order_number i kontynuuj sekwencję
        3. Jeśli NIE - wygeneruj nowy internal_order_number
        4. Zawsze generuj kolejne product_ids bez duplikatów
        
        Args:
            baselinker_order_id (int): ID zamówienia w Baselinker
            total_products_count (int): Łączna liczba produktów (suma wszystkich quantity)
        
        Returns:
            dict: {
                'internal_order_number': str,    # '25_00048'
                'product_ids': [str],            # ['25_00048_1', '25_00048_2', ...]
                'year_code': str,                # '25'
                'order_counter': int,            # 48
                'is_existing_order': bool        # True jeśli zamówienie już istniało
            }
        """
        try:
            logger.info("Rozpoczęcie generowania ID dla zamówienia", extra={
                'baselinker_order_id': baselinker_order_id,
                'total_products_count': total_products_count
            })

            # KROK 1: Sprawdź czy zamówienie już istnieje w bazie
            from ..models import ProductionItem
            existing_items = ProductionItem.query.filter_by(
                baselinker_order_id=baselinker_order_id
            ).all()
            
            is_existing_order = len(existing_items) > 0
            
            if is_existing_order:
                # ZAMÓWIENIE JUŻ ISTNIEJE - użyj istniejącego internal_order_number
                first_item = existing_items[0]
                existing_internal_order = first_item.internal_order_number
                
                # Wyciągnij year_code i order_counter z istniejącego numeru
                match = cls.INTERNAL_ORDER_PATTERN.match(existing_internal_order)
                if not match:
                    logger.error("Nieprawidłowy format istniejącego internal_order_number", extra={
                        'baselinker_order_id': baselinker_order_id,
                        'existing_internal_order': existing_internal_order
                    })
                    raise ProductIDGeneratorError(f"Nieprawidłowy format internal_order_number: {existing_internal_order}")
                
                year_code = match.group(1)
                order_counter = int(match.group(2))
                internal_order_number = existing_internal_order
                
                # Znajdź następne dostępne sekwencje (ZZ)
                existing_sequences = []
                for item in existing_items:
                    match = cls.PRODUCT_ID_PATTERN.match(item.short_product_id)
                    if match:
                        sequence = int(match.group(3))  # ZZ część
                        existing_sequences.append(sequence)
                
                existing_sequences = sorted(existing_sequences)
                next_sequence_start = max(existing_sequences) + 1 if existing_sequences else 1
                
                logger.info("Zamówienie już istnieje - kontynuuję sekwencję", extra={
                    'baselinker_order_id': baselinker_order_id,
                    'existing_internal_order': internal_order_number,
                    'existing_items_count': len(existing_items),
                    'existing_sequences': existing_sequences,
                    'next_sequence_start': next_sequence_start
                })
                
            else:
                # NOWE ZAMÓWIENIE - wygeneruj nowy internal_order_number
                current_year = datetime.now().year
                year_code = str(current_year)[-2:]  # "25" dla 2025
                
                # Pobierz następny unikalny numer zamówienia
                order_counter = cls._get_next_order_counter(current_year)
                internal_order_number = f"{year_code}_{order_counter:05d}"  # "25_00048"
                next_sequence_start = 1
                
                logger.info("Nowe zamówienie - wygenerowano internal_order_number", extra={
                    'baselinker_order_id': baselinker_order_id,
                    'internal_order_number': internal_order_number,
                    'order_counter': order_counter
                })

            # KROK 2: Wygeneruj wszystkie product_ids
            product_ids = []
            for i in range(total_products_count):
                sequence_num = next_sequence_start + i
                product_id = f"{internal_order_number}_{sequence_num}"
                product_ids.append(product_id)

            logger.info("Wygenerowane product_ids", extra={
                'baselinker_order_id': baselinker_order_id,
                'product_ids': product_ids
            })

            # KROK 3: Sprawdź unikalność wszystkich nowych product_ids
            conflicting_ids = []
            for product_id in product_ids:
                existing_product = ProductionItem.query.filter_by(
                    short_product_id=product_id
                ).first()
                
                if existing_product:
                    conflicting_ids.append({
                        'product_id': product_id,
                        'existing_record_id': existing_product.id,
                        'existing_order_id': existing_product.baselinker_order_id
                    })

            if conflicting_ids:
                logger.error("BŁĄD: Wygenerowane product_ids już istnieją!", extra={
                    'baselinker_order_id': baselinker_order_id,
                    'internal_order_number': internal_order_number,
                    'conflicting_ids': conflicting_ids[:3],
                    'total_conflicts': len(conflicting_ids)
                })
                raise ProductIDGeneratorError(f"Konflikty ID: {len(conflicting_ids)} z {total_products_count} już istnieje")

            # KROK 4: Zapisz do cache (tylko dla nowych zamówień)
            result = {
                'internal_order_number': internal_order_number,
                'product_ids': product_ids,
                'year_code': year_code,
                'order_counter': order_counter,
                'is_existing_order': is_existing_order
            }
            
            if not is_existing_order:
                cls._order_mapping_cache[baselinker_order_id] = {
                    'internal_order_number': internal_order_number,
                    'year_code': year_code,
                    'order_counter': order_counter
                }
            
            logger.info("SUKCES: Wygenerowano unikalne ID dla zamówienia", extra={
                'baselinker_order_id': baselinker_order_id,
                'internal_order_number': internal_order_number,
                'total_products': total_products_count,
                'first_id': product_ids[0] if product_ids else None,
                'last_id': product_ids[-1] if product_ids else None,
                'order_counter': order_counter,
                'is_existing_order': is_existing_order,
                'all_ids': product_ids
            })
            
            return result
            
        except Exception as e:
            logger.error("BŁĄD krytyczny w generowaniu ID", extra={
                'baselinker_order_id': baselinker_order_id,
                'total_products_count': total_products_count,
                'error': str(e)
            })
            raise ProductIDGeneratorError(f"Nie można wygenerować ID dla zamówienia {baselinker_order_id}: {str(e)}")
        
    
    @classmethod
    def _get_next_order_counter(cls, year):
        """
        Pobiera i inkrementuje licznik zamówień dla podanego roku
        
        WAŻNE: Ta metoda zwiększa licznik o 1 za każdym wywołaniem
        
        Args:
            year (int): Rok dla którego pobrać licznik
        
        Returns:
            int: Następny numer w sekwencji (XXXXX)
        """
        try:
            from ..models import ProductionOrderCounter
        
            # Szukanie istniejącego licznika
            counter = ProductionOrderCounter.query.filter_by(year=year).first()
        
            if not counter:
                # Utworzenie nowego licznika dla roku - rozpoczynamy od 1
                counter = ProductionOrderCounter(
                    year=year,
                    current_counter=1
                )
                db.session.add(counter)
                logger.info("Utworzono nowy licznik dla roku", extra={
                    'year': year,
                    'starting_counter': 1
                })
            else:
                # Inkrementacja istniejącego licznika
                counter.current_counter += 1
                counter.last_updated_at = datetime.utcnow()
                logger.debug("Zinkrementowano licznik", extra={
                    'year': year,
                    'new_counter': counter.current_counter
                })
        
            next_counter = counter.current_counter
            db.session.commit()
        
            logger.info("Pobrano kolejny licznik zamówienia", extra={
                'year': year,
                'counter': next_counter
            })
        
            return next_counter
        
        except IntegrityError as e:
            db.session.rollback()
            logger.error("Błąd integralności podczas pobierania licznika", extra={
                'year': year,
                'error': str(e)
            })
            raise ProductIDGeneratorError(f"Błąd integralności bazy danych: {str(e)}")
        
        except Exception as e:
            db.session.rollback()
            logger.error("Błąd pobierania licznika zamówienia", extra={
                'year': year,
                'error': str(e)
            })
            raise ProductIDGeneratorError(f"Nie można pobrać licznika: {str(e)}")
    
    @classmethod
    def validate_product_id_format(cls, product_id):
        """
        Waliduje format Product ID
        
        Args:
            product_id (str): ID do sprawdzenia
            
        Returns:
            bool: True jeśli format jest poprawny
        """
        if not isinstance(product_id, str):
            return False
            
        match = cls.PRODUCT_ID_PATTERN.match(product_id)
        if not match:
            return False
            
        year_code, order_number, sequence = match.groups()
        
        try:
            year_int = int(year_code)
            if not (20 <= year_int <= 99):
                return False
                
            order_int = int(order_number)
            if not (1 <= order_int <= 99999):
                return False
                
            sequence_int = int(sequence)
            if not (1 <= sequence_int <= 999):
                return False
        except ValueError:
            return False
            
        return True
    
    @classmethod
    def validate_internal_order_format(cls, internal_order):
        """
        Waliduje format wewnętrznego numeru zamówienia
        
        Args:
            internal_order (str): Numer do sprawdzenia (format: YY_NNNNN)
            
        Returns:
            bool: True jeśli format jest poprawny
        """
        if not isinstance(internal_order, str):
            return False
            
        return bool(cls.INTERNAL_ORDER_PATTERN.match(internal_order))
    
    @classmethod
    def parse_product_id(cls, product_id):
        """Parsuje Product ID na komponenty"""
        if not cls.validate_product_id_format(product_id):
            return None
            
        match = cls.PRODUCT_ID_PATTERN.match(product_id)
        year_code, order_number, sequence = match.groups()
        
        year_int = int(year_code)
        full_year = 2000 + year_int if year_int >= 20 else 1900 + year_int
        
        return {
            'year_code': year_code,
            'order_counter': int(order_number),
            'sequence': int(sequence),
            'internal_order_number': f"{year_code}_{order_number}",
            'full_year': full_year
        }
    
    @classmethod
    def get_current_counter_for_year(cls, year=None):
        """
        Pobiera aktualny licznik dla roku (bez inkrementacji)
        
        Args:
            year (int, optional): Rok. Domyślnie aktualny rok.
            
        Returns:
            int: Aktualny licznik lub 0 jeśli nie istnieje
        """
        if year is None:
            year = datetime.now().year
            
        try:
            from ..models import ProductionOrderCounter
            
            counter = ProductionOrderCounter.query.filter_by(year=year).first()
            return counter.current_counter if counter else 0
            
        except Exception as e:
            logger.error("Błąd pobierania aktualnego licznika", extra={
                'year': year,
                'error': str(e)
            })
            return 0
    
    @classmethod
    def generate_multiple_product_ids(cls, baselinker_order_id, product_count):
        """
        Generuje wiele Product ID dla tego samego zamówienia - UŻYWA generate_product_id_for_order()
        
        Args:
            baselinker_order_id (int): ID zamówienia w Baselinker
            product_count (int): Liczba produktów do wygenerowania
            
        Returns:
            list: Lista słowników z wygenerowanymi ID w starym formacie dla zgodności
        """
        if not isinstance(product_count, int) or product_count <= 0:
            raise ProductIDGeneratorError(f"Nieprawidłowa liczba produktów: {product_count}")
            
        if product_count > 999:
            raise ProductIDGeneratorError(f"Zbyt duża liczba produktów: {product_count} (max 999)")
        
        try:
            # UŻYJ poprawnej metody generate_product_id_for_order()
            order_result = cls.generate_product_id_for_order(baselinker_order_id, product_count)
            
            # Przekonwertuj na stary format dla zgodności z istniejącym kodem
            results = []
            for i, product_id in enumerate(order_result['product_ids']):
                result = {
                    'product_id': product_id,  # '25_00024_1'
                    'internal_order_number': order_result['internal_order_number'],  # '25_00024'
                    'year_code': order_result['year_code'],  # '25'
                    'order_counter': order_result['order_counter'],  # 24
                    'sequence': i + 1  # 1, 2, 3, ...
                }
                results.append(result)
            
            logger.info("Wygenerowano wiele Product ID", extra={
                'baselinker_order_id': baselinker_order_id,
                'product_count': product_count,
                'internal_order': order_result['internal_order_number'],
                'first_id': results[0]['product_id'],
                'last_id': results[-1]['product_id']
            })
            
            return results
            
        except Exception as e:
            logger.error("Błąd generowania wielu Product ID", extra={
                'baselinker_order_id': baselinker_order_id,
                'product_count': product_count,
                'error': str(e)
            })
            raise ProductIDGeneratorError(f"Nie można wygenerować wielu ID: {str(e)}")
    
    @classmethod
    def is_product_id_unique(cls, product_id):
        """
        Sprawdza czy Product ID jest unikalny w bazie danych
        
        Args:
            product_id (str): ID do sprawdzenia
            
        Returns:
            bool: True jeśli ID jest unikalny
        """
        try:
            from ..models import ProductionItem
            
            existing = ProductionItem.query.filter_by(
                short_product_id=product_id
            ).first()
            
            is_unique = existing is None
            
            logger.debug("Sprawdzono unikalność Product ID", extra={
                'product_id': product_id,
                'is_unique': is_unique
            })
            
            return is_unique
            
        except Exception as e:
            logger.error("Błąd sprawdzania unikalności Product ID", extra={
                'product_id': product_id,
                'error': str(e)
            })
            return False
    
    @classmethod
    def reset_counter_for_year(cls, year, new_value=0, admin_user_id=None):
        """
        Resetuje licznik dla roku (funkcja administracyjna)
        
        Args:
            year (int): Rok do resetowania
            new_value (int): Nowa wartość licznika
            admin_user_id (int, optional): ID administratora wykonującego reset
            
        Returns:
            bool: True jeśli reset się powiódł
            
        Raises:
            ProductIDGeneratorError: W przypadku błędu
        """
        try:
            from ..models import ProductionOrderCounter
            
            counter = ProductionOrderCounter.query.filter_by(year=year).first()
            
            if not counter:
                # Utworzenie nowego licznika
                counter = ProductionOrderCounter(
                    year=year,
                    current_counter=new_value
                )
                db.session.add(counter)
            else:
                # Reset istniejącego licznika
                old_value = counter.current_counter
                counter.current_counter = new_value
                counter.last_updated_at = datetime.utcnow()
                
                logger.warning("Reset licznika zamówień", extra={
                    'year': year,
                    'old_value': old_value,
                    'new_value': new_value,
                    'admin_user_id': admin_user_id
                })
            
            db.session.commit()
            
            logger.info("Zresetowano licznik dla roku", extra={
                'year': year,
                'new_value': new_value,
                'admin_user_id': admin_user_id
            })
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error("Błąd resetowania licznika", extra={
                'year': year,
                'new_value': new_value,
                'admin_user_id': admin_user_id,
                'error': str(e)
            })
            raise ProductIDGeneratorError(f"Nie można zresetować licznika: {str(e)}")
        
    @classmethod
    def validate_database_consistency(cls):
        """Waliduje spójność liczników z danymi w bazie"""
        try:
            from ..models import ProductionItem, ProductionOrderCounter
            
            logger.info("Rozpoczęcie walidacji spójności bazy danych")
            
            current_year = datetime.now().year
            year_code = str(current_year)[-2:]
            
            # Sprawdź duplikaty short_product_id
            duplicates_query = db.session.execute(text("""
                SELECT short_product_id, COUNT(*) as count 
                FROM prod_items 
                WHERE short_product_id IS NOT NULL
                GROUP BY short_product_id 
                HAVING COUNT(*) > 1
                LIMIT 10
            """))
            
            duplicates = duplicates_query.fetchall()
            if duplicates:
                logger.error("DUPLIKATY: Znaleziono duplikaty short_product_id", extra={
                    'duplicates_count': len(duplicates),
                    'sample_duplicates': [{'id': d[0], 'count': d[1]} for d in duplicates]
                })
                return {'duplicates_found': len(duplicates), 'valid': False}
            
            # Sprawdź synchronizację licznika
            counter_record = ProductionOrderCounter.query.filter_by(year=current_year).first()
            
            if counter_record:
                # Znajdź najwyższy numer zamówienia w bazie dla bieżącego roku
                max_order_query = db.session.execute(text("""
                    SELECT MAX(
                        CASE 
                            WHEN internal_order_number REGEXP '^[0-9]{2}_[0-9]{5}$'
                            THEN CAST(SUBSTRING(internal_order_number, 4, 5) AS UNSIGNED)
                            ELSE 0
                        END
                    ) as max_order
                    FROM prod_items 
                    WHERE internal_order_number LIKE :year_pattern
                """), {'year_pattern': f'{year_code}_%'})
                
                max_order_result = max_order_query.fetchone()
                max_order_in_db = max_order_result[0] if max_order_result and max_order_result[0] else 0
                
                is_synchronized = counter_record.current_counter >= max_order_in_db
                
                logger.info("Walidacja synchronizacji licznika", extra={
                    'current_counter': counter_record.current_counter,
                    'max_order_in_db': max_order_in_db,
                    'is_synchronized': is_synchronized,
                    'year': current_year
                })
                
                if not is_synchronized:
                    logger.error("DESYNC: Licznik jest mniejszy niż najwyższy numer w bazie!", extra={
                        'counter_value': counter_record.current_counter,
                        'max_in_db': max_order_in_db,
                        'difference': max_order_in_db - counter_record.current_counter
                    })
                    return {'duplicates_found': 0, 'synchronized': False, 'valid': False}
            
            return {'duplicates_found': 0, 'synchronized': True, 'valid': True}
            
        except Exception as e:
            logger.error("Błąd walidacji spójności bazy danych", extra={'error': str(e)})
            return {'error': str(e), 'valid': False}


    @classmethod
    def clear_order_cache(cls):
        """Czyści cache mapowania zamówień z logowaniem"""
        cache_size_before = len(cls._order_mapping_cache)
        
        if cache_size_before > 0:
            logger.info("Czyszczenie cache mapowania zamówień", extra={
                'cached_orders_count': cache_size_before,
                'cached_orders': list(cls._order_mapping_cache.keys())[:10]  # Pokaż pierwsze 10
            })
        
        cls._order_mapping_cache.clear()
        
        logger.info("Wyczyszczono cache mapowania zamówień", extra={
            'cleared_orders_count': cache_size_before
        })

# Funkcje pomocnicze na poziomie modułu
def generate_product_id(baselinker_order_id, sequence_number):
    """
    Wrapper funkcji generowania ID - DEPRECATED, użyj generate_product_id_for_order()
    
    UWAGA: Ta funkcja jest zachowana tylko dla zgodności wstecznej.
    Dla nowych implementacji używaj ProductIDGenerator.generate_product_id_for_order()
    """
    logger.warning("Użyto deprecated funkcji generate_product_id()", extra={
        'baselinker_order_id': baselinker_order_id,
        'sequence_number': sequence_number
    })
    
    # Wygeneruj ID dla pojedynczego produktu używając poprawnej metody
    order_result = ProductIDGenerator.generate_product_id_for_order(baselinker_order_id, 1)
    
    return {
        'product_id': order_result['product_ids'][0],  # Pierwszy (i jedyny) ID
        'internal_order_number': order_result['internal_order_number'],
        'year_code': order_result['year_code'],
        'order_counter': order_result['order_counter'],
        'sequence': sequence_number
    }

def validate_product_id(product_id):
    """Wrapper funkcji walidacji ID"""
    return ProductIDGenerator.validate_product_id_format(product_id)

def parse_product_id(product_id):
    """Wrapper funkcji parsowania ID"""
    return ProductIDGenerator.parse_product_id(product_id)