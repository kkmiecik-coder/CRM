# modules/production/services/priority_service.py
"""
Serwis priorytetów dla modułu Production - ENHANCED VERSION 2.0
================================================================

NOWY SYSTEM PRIORYTETÓW oparty na dacie opłacenia i grupowaniu tygodniowym
Zastępuje poprzedni system wagowy (deadline/value/volume/fifo).

ALGORYTM ENHANCED PRIORITY SYSTEM 2.0:
1. Pobieranie WSZYSTKICH produktów z kolejki produkcyjnej (niespakowanych)
2. Grupowanie po tygodniach (pon-niedz) względem payment_date
3. Obliczanie statystyk częstotliwości dla każdego tygodnia:
   - species (gatunek drewna)
   - finish_state (stan wykończenia) 
   - thickness_group (grupa grubości)
   - wood_class (klasa drewna)
4. Ustalanie priorytetów grup: "więcej = wyżej" w każdym tygodniu
5. Sortowanie wielopoziomowe:
   payment_date ASC → species → thickness_group → finish_state → wood_class
6. Przypisywanie numeracji sekwencyjnej 1,2,3,4... z pomijaniem manual overrides
7. Przypisywanie numeracji sekwencyjnej priority_rank

Autor: Konrad Kmiecik
Wersja: 2.0 (Enhanced Priority System - Payment Date + Weekly Grouping)
Data: 2025-01-22
"""

import threading
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict
from modules.logging import get_structured_logger
from sqlalchemy import func
from sqlalchemy.orm import joinedload

logger = get_structured_logger('production.priority.v2')

class PriorityError(Exception):
    """Wyjątek dla błędów kalkulacji priorytetów"""
    pass

class NewPriorityCalculator:
    """
    Nowy kalkulator priorytetów oparty na dacie opłacenia i grupowaniu tygodniowym
    
    ENHANCED VERSION 2.0 - kompletnie przepisany algorytm:
    - Zastąpienie systemu wagowego logiką opartą na payment_date
    - Grupowanie tygodniowe z priorytetem dla częściej występujących kombinacji
    - Numeracja sekwencyjna 1,2,3,4... zamiast punktowej 100,110,120...
    - Respect manual overrides (priority_manual_override = TRUE)
    - Scope: wszystkie produkty w kolejce bez ograniczenia czasowego
    """
    
    def __init__(self):
        """
        Inicjalizacja nowego kalkulatora priorytetów
        """
        self._lock = threading.RLock()
        
        # Konfiguracja algorytmu
        self.active_statuses = [
            'czeka_na_wyciecie',
            'czeka_na_skladanie',
            'czeka_na_sklejanie',
            'czeka_na_formatowanie',
            'czeka_na_wykanczanie',
            'czeka_na_pakowanie',
            'w_realizacji'
        ]
        
        logger.info("Inicjalizacja NewPriorityCalculator v2.0", extra={
            'algorithm': 'payment_date_weekly_grouping',
            'active_statuses': self.active_statuses,
            'scope': 'all_active_products_unlimited'
        })
    
    def recalculate_all_priorities(self) -> Dict[str, Any]:
        """
        Główna metoda przeliczająca wszystkie priorytety
        
        ALGORYTM:
        1. Pobiera WSZYSTKIE aktywne produkty z kolejki (niespakowane)
        2. Grupuje po tygodniach względem payment_date  
        3. Oblicza statystyki częstotliwości w każdym tygodniu
        4. Ustala priorytety grup: "więcej = wyżej"
        5. Sortuje produkty wielopoziomowo
        6. Przypisuje numery 1,2,3,4... z pomijaniem manual overrides
        7. Aktualizuje bazę danych
        
        Returns:
            Dict[str, Any]: Szczegółowy raport z przeliczenia
        """
        start_time = datetime.now()
        
        try:
            with self._lock:
                logger.info("Rozpoczęcie przeliczania wszystkich priorytetów v2.0")
                
                # KROK 1: Pobieranie wszystkich aktywnych produktów
                products = self.get_active_products_for_prioritization()
                logger.info(f"Pobrano {len(products)} aktywnych produktów z kolejki")
                
                if not products:
                    return {
                        'success': True,
                        'products_processed': 0,
                        'message': 'Brak produktów w kolejce do priorytetyzacji',
                        'duration_seconds': 0
                    }
                
                # KROK 2: Aktualizacja thickness_group dla wszystkich produktów
                thickness_updated = self.update_thickness_groups_batch(products)
                logger.debug(f"Zaktualizowano thickness_group dla {thickness_updated} produktów")
                
                # KROK 3: Grupowanie po tygodniach
                weekly_groups = self.group_products_by_weeks(products)
                logger.info(f"Pogrupowano produkty w {len(weekly_groups)} tygodni")
                
                # KROK 4-6: Przetwarzanie każdego tygodnia i sortowanie globalne
                all_sorted_products = []
                week_stats = {}
                
                for week_key, week_products in weekly_groups.items():
                    # Statystyki częstotliwości dla tygodnia
                    stats = self.calculate_week_statistics(week_products)
                    week_stats[week_key] = stats
                    
                    # Priorytety grup dla tygodnia
                    group_priorities = self.determine_group_priorities(stats)
                    
                    # Sortowanie produktów w tygodniu
                    sorted_week_products = self.sort_products_by_rules(week_products, group_priorities)
                    all_sorted_products.extend(sorted_week_products)
                
                logger.info(f"Posortowano wszystkie produkty globalnie: {len(all_sorted_products)}")
                
                # KROK 7: Przypisanie numeracji sekwencyjnej
                ranking_result = self.assign_sequential_ranks(all_sorted_products)
                
                # KROK 8: Commit zmian w bazie danych
                from extensions import db
                db.session.commit()
                
                duration = (datetime.now() - start_time).total_seconds()
                
                result = {
                    'success': True,
                    'products_processed': len(products),
                    'products_prioritized': ranking_result['products_updated'],
                    'manual_overrides_preserved': ranking_result['manual_overrides_preserved'],
                    'weekly_groups_processed': len(weekly_groups),
                    'duration_seconds': round(duration, 2),
                    'algorithm_version': '2.0',
                    'week_statistics': week_stats,
                    'ranking_details': ranking_result
                }
                
                logger.info("Zakończono przeliczanie priorytetów", extra=result)
                return result
                
        except Exception as e:
            logger.error("Błąd przeliczania priorytetów", extra={
                'error': str(e),
                'duration_seconds': (datetime.now() - start_time).total_seconds()
            })
            
            return {
                'success': False,
                'error': str(e),
                'products_processed': 0,
                'duration_seconds': (datetime.now() - start_time).total_seconds()
            }
    
    def get_active_products_for_prioritization(self) -> List:
        """
        Pobiera WSZYSTKIE produkty aktywne w kolejce produkcyjnej
        
        KRYTERIA WŁĄCZENIA:
        - Status w kolejce produkcyjnej (przed pakowaniem)
        - BEZ ograniczenia czasowego - wszystkie aktywne niezależnie od daty
        - Wykluczone: produkty już spakowane przez ostatnie stanowisko
        
        Returns:
            List[ProductionItem]: Lista aktywnych produktów
        """
        try:
            from ..models import ProductionItem, ProductionOrder

            # Query wszystkich produktów w statusach aktywnych
            query = ProductionItem.query.join(ProductionOrder).options(
                joinedload(ProductionItem.order),
                joinedload(ProductionItem.configuration),
            ).filter(
                ProductionItem.current_status.in_(self.active_statuses)
            ).order_by(
                func.isnull(ProductionOrder.payment_date),
                ProductionOrder.payment_date.asc(),
                ProductionItem.created_at.asc()
            )

            products = query.all()
            
            logger.debug("Pobrano produkty dla priorytetyzacji", extra={
                'total_count': len(products),
                'active_statuses': self.active_statuses,
                'scope': 'unlimited_time_range'
            })
            
            return products
            
        except Exception as e:
            logger.error("Błąd pobierania produktów dla priorytetyzacji", extra={
                'error': str(e)
            })
            return []
    
    def group_products_by_weeks(self, products: List) -> Dict[str, List]:
        """
        Grupuje produkty według tygodni (poniedziałek 00:00 - niedziela 23:59)
        na podstawie payment_date
        
        Args:
            products: Lista produktów do pogrupowania
            
        Returns:
            Dict[str, List]: Słownik "2025-W03" -> [produkty]
        """
        weekly_groups = defaultdict(list)
        
        for product in products:
            if product.order and product.order.payment_date:
                # Oblicz granice tygodnia dla payment_date
                week_start, week_end = self.get_week_boundaries(product.order.payment_date)

                # Format klucza: YYYY-WNN
                year = week_start.year
                week_number = week_start.isocalendar()[1]
                week_key = f"{year}-W{week_number:02d}"

            else:
                # Produkty bez payment_date w osobnej grupie
                week_key = "no-payment-date"

            weekly_groups[week_key].append(product)
        
        # Sortowanie kluczy tygodni chronologicznie
        sorted_groups = {}
        for week_key in sorted(weekly_groups.keys()):
            sorted_groups[week_key] = weekly_groups[week_key]
        
        logger.debug("Pogrupowano produkty po tygodniach", extra={
            'weekly_groups': {k: len(v) for k, v in sorted_groups.items()}
        })
        
        return sorted_groups
    
    def get_week_boundaries(self, date_input: datetime) -> Tuple[datetime, datetime]:
        """
        Oblicza początek i koniec tygodnia (poniedziałek 00:00 - niedziela 23:59)
        
        Args:
            date_input: Data wejściowa
            
        Returns:
            Tuple[datetime, datetime]: (week_start, week_end)
        """
        if isinstance(date_input, str):
            date_input = datetime.fromisoformat(date_input)
        elif isinstance(date_input, date):
            date_input = datetime.combine(date_input, datetime.min.time())
        
        # Znajdź poniedziałek tego tygodnia (weekday: 0=Mon, 6=Sun)
        days_since_monday = date_input.weekday()
        week_start = date_input - timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Niedziela 23:59:59
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        return week_start, week_end
    
    def calculate_week_statistics(self, products: List) -> Dict[str, Dict[str, int]]:
        """
        Oblicza statystyki częstotliwości występowania dla produktów w danym tygodniu
        
        Args:
            products: Lista produktów z danego tygodnia
            
        Returns:
            Dict[str, Dict[str, int]]: Statystyki {kategoria: {wartość: count}}
        """
        stats = {
            'species': defaultdict(int),
            'technology': defaultdict(int),
            'finish_state': defaultdict(int),
            'thickness_group': defaultdict(int),
            'wood_class': defaultdict(int)
        }
        
        for product in products:
            # Zliczanie gatunków
            if product.configuration and product.configuration.species:
                stats['species'][product.configuration.species] += 1

            # Zliczanie technologii
            if product.configuration and product.configuration.technology:
                stats['technology'][product.configuration.technology] += 1

            # Zliczanie stanów wykończenia
            if product.parsed_finish_state:
                stats['finish_state'][product.parsed_finish_state] += 1

            # Zliczanie grup grubości
            if product.thickness_group:
                stats['thickness_group'][product.thickness_group] += 1

            # Zliczanie klas drewna
            if product.configuration and product.configuration.wood_class:
                stats['wood_class'][product.configuration.wood_class] += 1
        
        # Konwersja defaultdict na dict dla loggingu
        final_stats = {
            category: dict(counts) 
            for category, counts in stats.items()
        }
        
        return final_stats
    
    def determine_group_priorities(self, stats: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
        """
        Ustala priorytety grup na zasadzie "więcej = wyżej"
        
        Args:
            stats: Statystyki częstotliwości z calculate_week_statistics
            
        Returns:
            Dict[str, Dict[str, int]]: {kategoria: {wartość: priorytet}}
                gdzie priorytet: 1=najwyższy, 2=drugi, etc.
        """
        group_priorities = {}
        
        for category, value_counts in stats.items():
            if not value_counts:
                group_priorities[category] = {}
                continue
            
            # Sortowanie według częstotliwości malejąco (więcej = wyżej)
            sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
            
            # Przypisanie priorytetów: 1=najczęściej występujący, 2=drugi, etc.
            priorities = {}
            for rank, (value, count) in enumerate(sorted_values, 1):
                priorities[value] = rank
            
            group_priorities[category] = priorities
        
        logger.debug("Ustalono priorytety grup", extra={
            'group_priorities': group_priorities
        })
        
        return group_priorities
    
    def sort_products_by_rules(self, products: List, group_priorities: Dict[str, Dict[str, int]]) -> List:
        """
        Sortuje produkty według nowych reguł priorytetów
        
        SORTOWANIE WIELOPOZIOMOWE:
        1. payment_date ASC (starsze = wyższy priorytet)
        2. species (według group_priorities)
        3. thickness_group (według group_priorities) 
        4. finish_state (według group_priorities)
        5. wood_class (według group_priorities)
        
        Args:
            products: Lista produktów do posortowania
            group_priorities: Priorytety grup z determine_group_priorities
            
        Returns:
            List: Posortowana lista produktów
        """
        logger.debug("Group priorities calculated", extra={
            'group_priorities': group_priorities,
            'products_count': len(products)
        })
        
        def get_sort_key(product):
            """
            POPRAWIONA LOGIKA - deadline_date jako primary key
            
            Kolejność sortowania priorytetów:
            1. DEADLINE_DATE (tylko dzień, bez godzin) - najważniejszy
            2. SPECIES (gatunek drewna) - według częstotliwości w tygodniu
            3. TECHNOLOGY (technologia wykonania) - według częstotliwości
            4. THICKNESS_GROUP (grupa grubości) - według częstotliwości
            5. WOOD_CLASS (klasa drewna) - według częstotliwości
            6. PAYMENT_DATE (data opłacenia) - tie-breaker, starsze = wyższy priorytet
            7. ID produktu - final tie-breaker dla stabilności sortowania
            """

            logger.debug(f"Product {product.id} sort data", extra={
                'product_id': product.id,
                'deadline_date': product.deadline_date,
                'parsed_wood_species': getattr(product.configuration, 'species', 'NONE') if product.configuration else 'NONE',
                'parsed_technology': (product.configuration.technology if product.configuration else None) or 'NONE',
                'thickness_group': getattr(product, 'thickness_group', 'NONE'),
                'parsed_wood_class': getattr(product.configuration, 'wood_class', 'NONE') if product.configuration else 'NONE',
                'payment_date': product.order.payment_date if product.order else None
            })
            
            # 1. DEADLINE_DATE - najważniejszy (termin dostawy) - tylko DZIEŃ!
            deadline_key = product.deadline_date if product.deadline_date else date.max
            
            # 2. W ramach tego samego deadline - parametry wykonawcze:
            # SPECIES (gatunek drewna) - według group_priorities
            species_priority = group_priorities.get('species', {}).get(
                product.configuration.species if product.configuration else None, 999
            )

            # TECHNOLOGY (technologia) - według group_priorities
            tech_priority = group_priorities.get('technology', {}).get(
                product.configuration.technology if product.configuration else None, 999
            )

            # THICKNESS_GROUP (grubość) - według group_priorities
            thickness_priority = group_priorities.get('thickness_group', {}).get(
                product.thickness_group, 999
            )

            # WOOD_CLASS (klasa drewna) - według group_priorities
            wood_class_priority = group_priorities.get('wood_class', {}).get(
                product.configuration.wood_class if product.configuration else None, 999
            )

            # 3. Payment_date jako tie-breaker (starsze opłacenie = wyższy priorytet)
            payment_date_key = (product.order.payment_date if product.order else None) or datetime.max
            
            # 4. ID jako final tie-breaker
            id_key = product.id
            
            return (
                deadline_key,          # 1. Deadline (najważniejszy)
                species_priority,      # 2. Gatunek 
                tech_priority,         # 3. Technologia
                thickness_priority,    # 4. Grubość
                wood_class_priority,   # 5. Klasa
                payment_date_key,      # 6. Data opłacenia (tie-breaker)
                id_key                 # 7. ID (stabilność)
            )
        
        try:
            sorted_products = sorted(products, key=get_sort_key)
            
            logger.debug("Posortowano produkty według nowych reguł", extra={
                'products_count': len(products),
                'sorted_count': len(sorted_products)
            })
            
            return sorted_products
            
        except Exception as e:
            logger.error("Błąd sortowania produktów", extra={
                'error': str(e),
                'products_count': len(products)
            })
            # Fallback - return unsorted
            return products
    
    def assign_sequential_ranks(self, sorted_products: List) -> Dict[str, Any]:
        """
        Przypisuje numery priorytetów 1,2,3,4... z pomijaniem manual overrides
    
        Args:
            sorted_products: Lista produktów posortowanych według reguł
        
        Returns:
            Dict[str, Any]: Statystyki przypisania rang
        """
        # Pobierz zarezerwowane rangi (manual overrides)
        reserved_ranks = self.get_reserved_ranks()
    
        current_rank = 1
        products_updated = 0
        manual_overrides_preserved = len(reserved_ranks)
    
        for product in sorted_products:
            # Pomijaj produkty z manual override
            if product.is_priority_locked:
                logger.debug(f"Pominięto produkt z manual override: {product.short_product_id} (rank: {product.priority_rank})")
                continue
        
            # Znajdź następny dostępny rank (pomijając zarezerwowane)
            while current_rank in reserved_ranks:
                current_rank += 1
        
            # ZMIANA: Przypisz tylko priority_rank (usuń priority_score)
            old_rank = product.priority_rank
            product.priority_rank = current_rank
        
            logger.debug(f"Zaktualizowano priorytet: {product.short_product_id} {old_rank} → {current_rank}")
        
            current_rank += 1
            products_updated += 1
    
        result = {
            'products_updated': products_updated,
            'manual_overrides_preserved': manual_overrides_preserved,
            'highest_rank_assigned': current_rank - 1,
            'reserved_ranks_count': len(reserved_ranks),
            'reserved_ranks': sorted(list(reserved_ranks)) if reserved_ranks else []
        }
    
        logger.info("Przypisano numery priorytetów", extra=result)
        return result
    
    def get_reserved_ranks(self) -> Set[int]:
        """
        Pobiera numery priorytetów zarezerwowane przez manual overrides
        
        Returns:
            Set[int]: Zestaw zajętych numerów priorytetów
        """
        try:
            from ..models import ProductionItem
            
            # Query produktów z manual override i przypisanym priority_rank
            reserved_products = ProductionItem.query.filter(
                ProductionItem.priority_manual_override == True,
                ProductionItem.priority_rank.isnot(None),
                ProductionItem.current_status.in_(self.active_statuses)
            ).all()
            
            reserved_ranks = {p.priority_rank for p in reserved_products if p.priority_rank}
            
            logger.debug(f"Znaleziono {len(reserved_ranks)} zarezerwowanych rangów: {sorted(reserved_ranks)}")
            return reserved_ranks
            
        except Exception as e:
            logger.error("Błąd pobierania zarezerwowanych rangów", extra={'error': str(e)})
            return set()
    
    def update_thickness_groups_batch(self, products: List) -> int:
        """
        Masowa aktualizacja thickness_group dla produktów
        
        Args:
            products: Lista produktów do zaktualizowania
            
        Returns:
            int: Liczba zaktualizowanych produktów
        """
        updated_count = 0
        
        for product in products:
            old_group = product.thickness_group
            new_group = product.update_thickness_group()
            
            if old_group != new_group:
                updated_count += 1
        
        logger.debug(f"Masowa aktualizacja thickness_group: {updated_count} produktów")
        return updated_count
    
    def validate_product_for_prioritization(self, product) -> Tuple[bool, List[str]]:
        """
        Sprawdza czy produkt może uczestniczyć w priorytetyzacji

        Args:
            product: Instancja ProductionItem

        Returns:
            Tuple[bool, List[str]]: (is_valid, missing_fields)
        """
        return product.validate_for_prioritization()

# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_priority_calculator_instance = None
_calculator_lock = threading.Lock()

def get_priority_calculator() -> NewPriorityCalculator:
    """
    Pobiera singleton instance NewPriorityCalculator
    
    Returns:
        NewPriorityCalculator: Instancja nowego kalkulatora
    """
    global _priority_calculator_instance
    
    if _priority_calculator_instance is None:
        with _calculator_lock:
            if _priority_calculator_instance is None:
                _priority_calculator_instance = NewPriorityCalculator()
                logger.info("Utworzono singleton NewPriorityCalculator v2.0")
    
    return _priority_calculator_instance

# ============================================================================
# HELPER FUNCTIONS - ZACHOWANE DLA KOMPATYBILNOŚCI
# ============================================================================

def recalculate_priorities() -> Dict[str, Any]:
    """
    Przelicza priorytety wszystkich aktywnych produktów

    Returns:
        dict: Rezultat przeliczenia
    """
    calculator = get_priority_calculator()
    if not calculator:
        return {'success': False, 'error': 'Calculator unavailable'}
    return calculator.recalculate_all_priorities()

# ============================================================================
# HELPER FUNCTIONS DLA ENHANCED PRIORITY SYSTEM 2.0
# ============================================================================

def recalculate_all_priorities() -> Dict[str, Any]:
    """
    Helper function dla pełnego przeliczenia wszystkich priorytetów
    
    Returns:
        Dict[str, Any]: Raport z przeliczenia
    """
    return get_priority_calculator().recalculate_all_priorities()

def get_priority_statistics() -> Dict[str, Any]:
    """
    Pobiera statystyki systemu priorytetów
    
    Returns:
        Dict[str, Any]: Statystyki priorytetów
    """
    try:
        from ..models import ProductionItem
        
        # Policz produkty w kolejce
        active_count = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie',
                'czeka_na_sklejanie',
                'czeka_na_formatowanie', 'czeka_na_wykanczanie',
                'czeka_na_pakowanie', 'w_realizacji'
            ])
        ).count()

        # Policz manual overrides
        manual_overrides = ProductionItem.query.filter(
            ProductionItem.priority_manual_override == True,
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie',
                'czeka_na_sklejanie',
                'czeka_na_formatowanie', 'czeka_na_wykanczanie',
                'czeka_na_pakowanie', 'w_realizacji'
            ])
        ).count()
        
        # Ostatnia aktualizacja (najnowszy updated_at)
        latest_update = ProductionItem.query.filter(
            ProductionItem.priority_rank.isnot(None)
        ).order_by(ProductionItem.updated_at.desc()).first()
        
        return {
            'active_products_count': active_count,
            'manual_overrides_count': manual_overrides,
            'last_calculation': latest_update.updated_at if latest_update else None,
            'algorithm_version': '2.0',
            'algorithm_type': 'payment_date_weekly_grouping'
        }
        
    except Exception as e:
        logger.error("Błąd pobierania statystyk priorytetów", extra={'error': str(e)})
        return {
            'error': str(e),
            'active_products_count': 0,
            'manual_overrides_count': 0,
            'last_calculation': None
        }