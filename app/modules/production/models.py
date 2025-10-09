# modules/production/models.py
"""
Modele SQLAlchemy dla modułu Production
========================================

Definiuje wszystkie tabele bazy danych dla systemu zarządzania produkcją:
- ProductionItem - główna tabela produktów z nowym formatem ID + NOWY SYSTEM PRIORYTETÓW
- ProductionOrderCounter - liczniki numerów zamówień per rok
- ProductionPriorityConfig - konfiguracja systemu priorytetów
- ProductionSyncLog - logi synchronizacji z Baselinker
- ProductionError - rejestr błędów systemu
- ProductionConfig - konfiguracja modułu

Autor: Konrad Kmiecik
Wersja: 2.0 (Enhanced Priority System - Data opłacenia + grupowanie tygodniowe)
Data: 2025-01-22
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, Numeric, Enum, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func
from extensions import db
from modules.logging import get_structured_logger
import pytz

logger = get_structured_logger('production.models')

def get_local_now():
    """
    Zwraca aktualny czas w strefie czasowej Polski
    Zastępuje get_local_now() dla poprawnego wyświetlania czasu
    """
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)

class ProductionOrderCounter(db.Model):
    """
    Liczniki numerów zamówień produkcyjnych per rok
    Zapewnia unikalne numerowanie w formacie YY_NNNNN
    """
    __tablename__ = 'prod_order_counters'
    
    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False, unique=True)
    current_counter = Column(Integer, default=0, nullable=False)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ProductionOrderCounter {self.year}: {self.current_counter}>'
    
    @classmethod
    def get_next_counter(cls, year=None):
        """
        Pobiera i inkrementuje licznik dla podanego roku
        
        Args:
            year (int, optional): Rok dla którego pobrać licznik. Domyślnie aktualny rok.
            
        Returns:
            int: Następny numer w sekwencji
        """
        if year is None:
            year = datetime.now().year
            
        counter = cls.query.filter_by(year=year).first()
        if not counter:
            counter = cls(year=year, current_counter=0)
            db.session.add(counter)
            
        counter.current_counter += 1
        counter.last_updated_at = get_local_now()
        
        db.session.commit()
        
        logger.info("Wygenerowano nowy licznik", extra={
            'year': year,
            'counter': counter.current_counter
        })
        
        return counter.current_counter

class ProductionItem(db.Model):
    """
    Główna tabela produktów w systemie produkcyjnym
    Każdy rekord reprezentuje pojedynczy produkt z unikalnym ID w formacie YY_NNNNN_S
    
    ENHANCED VERSION 2.0: Nowy system priorytetów oparty na dacie opłacenia
    """
    __tablename__ = 'prod_items'
    
    id = Column(Integer, primary_key=True)
    
    # IDENTYFIKATORY SYSTEMU
    short_product_id = Column(String(16), unique=True, nullable=False, index=True)
    internal_order_number = Column(String(8), nullable=False, index=True)
    product_sequence_in_order = Column(Integer, nullable=False)
    
    # DANE BASELINKER
    baselinker_order_id = Column(Integer, nullable=False, index=True)
    baselinker_product_id = Column(String(50))
    original_product_name = Column(Text, nullable=False)
    baselinker_status_id = Column(Integer)
    
    # DANE PRODUKTU (PARSOWANE) - używamy istniejących nazw kolumn
    parsed_wood_species = Column(String(50))  # species dla algorytmu
    parsed_technology = Column(String(50))
    parsed_wood_class = Column(String(10))    # wood_class dla algorytmu
    parsed_length_cm = Column(Numeric(10, 2))
    parsed_width_cm = Column(Numeric(10, 2))
    parsed_thickness_cm = Column(Numeric(10, 2))  # bazowe dla thickness_group
    parsed_finish_state = Column(String(50))   # finish_state dla algorytmu
    
    # KALKULACJE BIZNESOWE
    volume_m3 = Column(Numeric(10, 4))
    unit_price_net = Column(Numeric(10, 2))
    total_value_net = Column(Numeric(10, 2))

    # DANE KLIENTA
    client_name = Column(String(255), index=True)
    client_email = Column(String(255))
    client_phone = Column(String(50))
    delivery_address = Column(Text)
    
    # STATUS PRODUKCJI
    current_status = Column(Enum(
        'czeka_na_wyciecie',
        'czeka_na_skladanie',
        'czeka_na_pakowanie', 
        'spakowane',
        'anulowane',
        'wstrzymane',
        'w_realizacji',  # dodatkowy status
        name='production_status'
    ), default='czeka_na_wyciecie', nullable=False, index=True)
    
    # PRIORYTETY I PLANOWANIE - STARY SYSTEM (zachowujemy kompatybilność)
    deadline_date = Column(Date, index=True)
    days_until_deadline = Column(Integer)
    
    # ============================================================================
    # NOWY SYSTEM PRIORYTETÓW - ENHANCED VERSION 2.0
    # ============================================================================
    
    # NOWE KOLUMNY DLA ALGORYTMU OPARTEGO NA DACIE OPŁACENIA
    priority_rank = Column(Integer, nullable=True, index=True, 
                          comment='Wizualna numeracja priorytetów 1,2,3,4... (NULL = automatyczne obliczanie)')
    
    payment_date = Column(DateTime, nullable=True, index=True,
                         comment='Data opłacenia zamówienia (status change na 155824 "Nowe - opłacone")')
    
    priority_manual_override = Column(Boolean, default=False, index=True,
                                    comment='Czy priorytet został zmieniony ręcznie przez administratora')
    
    thickness_group = Column(String(10), nullable=True, index=True,
                           comment='Grupa grubości dla algorytmu priorytetów: 0-2.5, 2.6-3.5, 3.6-4.5, 4.6+')
    
    # ŚLEDZENIE CZASU WYKONANIA - WYCINANIE
    cutting_started_at = Column(DateTime)
    cutting_completed_at = Column(DateTime, index=True)
    cutting_duration_minutes = Column(Integer)
    cutting_assigned_worker_id = Column(Integer, ForeignKey('users.id'))
    
    # ŚLEDZENIE CZASU WYKONANIA - SKŁADANIE
    assembly_started_at = Column(DateTime)
    assembly_completed_at = Column(DateTime, index=True)
    assembly_duration_minutes = Column(Integer)
    assembly_assigned_worker_id = Column(Integer, ForeignKey('users.id'))
    
    # ŚLEDZENIE CZASU WYKONANIA - PAKOWANIE
    packaging_started_at = Column(DateTime)
    packaging_completed_at = Column(DateTime, index=True)
    packaging_duration_minutes = Column(Integer)
    packaging_assigned_worker_id = Column(Integer, ForeignKey('users.id'))
    
    # UWAGI I PROBLEMY
    production_notes = Column(Text)
    quality_issues = Column(Text)
    
    # METADANE
    created_at = Column(DateTime, default=get_local_now, index=True)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    sync_source = Column(Enum('baselinker_auto', 'manual_entry', name='sync_source'), 
                        default='baselinker_auto')
    
    # RELACJE
    cutting_worker = relationship("User", foreign_keys=[cutting_assigned_worker_id])
    assembly_worker = relationship("User", foreign_keys=[assembly_assigned_worker_id])  
    packaging_worker = relationship("User", foreign_keys=[packaging_assigned_worker_id])
    
    def __repr__(self):
        return f'<ProductionItem {self.short_product_id}: {self.current_status}, priority_rank={self.priority_rank}>'
    
    @validates('short_product_id')
    def validate_product_id(self, key, product_id):
        """Walidacja formatu Product ID: YY_NNNNN_S"""
        import re
        pattern = r'^\d{2}_\d{5}_\d+$'
        if not re.match(pattern, product_id):
            raise ValueError(f"Product ID musi być w formacie YY_NNNNN_S, otrzymano: {product_id}")
        return product_id
    
    # ============================================================================
    # PROPERTIES - ZACHOWUJEMY KOMPATYBILNOŚĆ
    # ============================================================================
    
    @property
    def is_overdue(self):
        """Sprawdza czy produkt przekroczył deadline"""
        if not self.deadline_date:
            return False
        return date.today() > self.deadline_date
    
    @property
    def status_display_name(self):
        """Nazwa statusu do wyświetlania"""
        status_names = {
            'czeka_na_wyciecie': 'Czeka na wycięcie',
            'czeka_na_skladanie': 'Czeka na składanie',
            'czeka_na_pakowanie': 'Czeka na pakowanie',
            'spakowane': 'Spakowane',
            'anulowane': 'Anulowane',
            'wstrzymane': 'Wstrzymane',
            'w_realizacji': 'W realizacji'
        }
        return status_names.get(self.current_status, self.current_status)
    
    @property
    def thickness(self):
        """Alias dla kompatybilności z nowym systemem priorytetów"""
        return self.parsed_thickness_cm
    
    @property
    def species(self):
        """Alias dla nowego algorytmu priorytetów"""
        return self.parsed_wood_species
    
    @property
    def finish_state(self):
        """Alias dla nowego algorytmu priorytetów"""
        return self.parsed_finish_state
    
    @property
    def wood_class(self):
        """Alias dla nowego algorytmu priorytetów"""
        return self.parsed_wood_class
    
    # ============================================================================
    # NOWE METODY DLA ENHANCED PRIORITY SYSTEM 2.0
    # ============================================================================
    
    def get_thickness_group(self):
        """
        Oblicza grupę grubości na podstawie parsed_thickness_cm
        
        Returns:
            str: Grupa grubości ('0-2.5', '2.6-3.5', '3.6-4.5', '4.6+') lub None
        """
        if not self.parsed_thickness_cm:
            return None
            
        thickness = float(self.parsed_thickness_cm)
        if thickness <= 2.5:
            return "0-2.5"
        elif thickness <= 3.5:
            return "2.6-3.5"
        elif thickness <= 4.5:
            return "3.6-4.5"
        else:
            return "4.6+"
    
    def update_thickness_group(self):
        """
        Aktualizuje thickness_group na podstawie aktualnej parsed_thickness_cm
        
        Returns:
            str: Nowa wartość thickness_group
        """
        self.thickness_group = self.get_thickness_group()
        logger.debug("Zaktualizowano thickness_group", extra={
            'product_id': self.short_product_id,
            'thickness_cm': float(self.parsed_thickness_cm) if self.parsed_thickness_cm else None,
            'thickness_group': self.thickness_group
        })
        return self.thickness_group
    
    @property
    def is_priority_locked(self):
        """
        Sprawdza czy priorytet jest zablokowany (manual override)
        
        Returns:
            bool: True jeśli priorytet jest ustawiony ręcznie
        """
        return bool(self.priority_manual_override)
    
    def lock_priority(self, rank: int):
        """
        Blokuje priorytet na określonej pozycji (manual override)
        """
        if rank < 1:
            raise ValueError("Numer priorytetu musi być >= 1")
        
        self.priority_rank = rank
        # USUŃ TO: self.priority_score = max(1, 1000 - rank)
        self.priority_manual_override = True
    
        logger.info("Zablokowano priorytet produktu", extra={
            'product_id': self.short_product_id,
            'priority_rank': rank,
            # USUŃ TO: 'priority_score': self.priority_score,
            'manual_override': True
        })
    
    def unlock_priority(self):
        """
        Odblokowuje priorytet (będzie obliczany automatycznie)
        """
        old_rank = self.priority_rank
        self.priority_manual_override = False
        # Nie czyścimy priority_rank - zostanie zaktualizowany przez algorytm
        
        logger.info("Odblokowano priorytet produktu", extra={
            'product_id': self.short_product_id,
            'old_priority_rank': old_rank,
            'manual_override': False
        })
    
    def is_in_production_queue(self):
        """
        Sprawdza czy produkt jest w kolejce produkcyjnej (kwalifikuje się do priorytetyzacji)
        
        Returns:
            bool: True jeśli produkt jest w aktywnej kolejce produkcyjnej
        """
        active_statuses = [
            'czeka_na_wyciecie',
            'czeka_na_skladanie', 
            'czeka_na_pakowanie',
            'w_realizacji'
        ]
        return self.current_status in active_statuses
    
    def validate_for_prioritization(self):
        """
        Sprawdza czy produkt ma wszystkie wymagane dane do priorytetyzacji
        
        Returns:
            tuple: (is_valid: bool, missing_fields: list)
        """
        required_fields = {
            'species': self.parsed_wood_species,
            'finish_state': self.parsed_finish_state,
            'thickness': self.parsed_thickness_cm,
            'wood_class': self.parsed_wood_class,
            'width': self.parsed_width_cm,
            'length': self.parsed_length_cm
        }
        
        missing_fields = [
            field_name for field_name, field_value in required_fields.items()
            if not field_value or (isinstance(field_value, str) and field_value.strip() == '')
        ]
        
        is_valid = len(missing_fields) == 0 and self.is_in_production_queue()
        
        return is_valid, missing_fields
    
    # ============================================================================
    # METODY ZACHOWANE DLA KOMPATYBILNOŚCI
    # ============================================================================
    
    def start_task(self, station_code, worker_id=None):
        """Rozpoczęcie pracy na stanowisku - ZACHOWANE"""
        now = get_local_now()
        
        if station_code == 'cutting':
            self.cutting_started_at = now
            self.cutting_assigned_worker_id = worker_id
            self.current_status = 'czeka_na_wyciecie'
            
        elif station_code == 'assembly':
            self.assembly_started_at = now
            self.assembly_assigned_worker_id = worker_id
            self.current_status = 'czeka_na_skladanie'
            
        elif station_code == 'packaging':
            self.packaging_started_at = now
            self.packaging_assigned_worker_id = worker_id
            self.current_status = 'czeka_na_pakowanie'
        
        self.updated_at = now
        
        logger.info("Rozpoczęto zadanie", extra={
            'product_id': self.short_product_id,
            'station': station_code,
            'worker_id': worker_id,
            'new_status': self.current_status
        })
    
    def complete_task(self, station_code):
        """Ukończenie pracy na stanowisku - ZACHOWANE"""
        now = get_local_now()
        
        if station_code == 'cutting':
            self.cutting_completed_at = now
            if self.cutting_started_at:
                self.cutting_duration_minutes = int(
                    (now - self.cutting_started_at).total_seconds() / 60
                )
            self.current_status = 'czeka_na_skladanie'
            
        elif station_code == 'assembly':
            self.assembly_completed_at = now
            if self.assembly_started_at:
                self.assembly_duration_minutes = int(
                    (now - self.assembly_started_at).total_seconds() / 60
                )
            self.current_status = 'czeka_na_pakowanie'
            
        elif station_code == 'packaging':
            self.packaging_completed_at = now
            if self.packaging_started_at:
                self.packaging_duration_minutes = int(
                    (now - self.packaging_started_at).total_seconds() / 60
                )
            self.current_status = 'spakowane'
        
        self.updated_at = now
        
        logger.info("Ukończono zadanie", extra={
            'product_id': self.short_product_id,
            'station': station_code,
            'new_status': self.current_status,
            'duration_minutes': getattr(self, f'{station_code}_duration_minutes')
        })

class ProductionPriorityConfig(db.Model):
    """
    Konfiguracja systemu priorytetów dla produktów
    UWAGA: Ta tabela zostanie zastąpiona przez nowy system w wersji 2.0
    Zachowujemy dla kompatybilności z istniejącym kodem
    """
    __tablename__ = 'prod_priority_config'
    
    id = Column(Integer, primary_key=True)
    config_name = Column(String(100), nullable=False)
    criteria_json = Column(JSON, nullable=False)
    weight_percentage = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    display_order = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ProductionPriorityConfig {self.config_name}: {self.weight_percentage}%>'
    
    @validates('weight_percentage')
    def validate_weight(self, key, weight):
        """Walidacja wagi procentowej"""
        if not 0 <= weight <= 100:
            raise ValueError("Waga musi być między 0 a 100")
        return weight

class ProductionSyncLog(db.Model):
    """
    Logi synchronizacji z systemem Baselinker
    Śledzenie operacji automatycznej synchronizacji danych
    ROZSZERZONY o nowe typy sync dla enhanced priority system
    """
    __tablename__ = 'prod_sync_logs'
    
    id = Column(Integer, primary_key=True)
    sync_type = Column(Enum('cron_auto', 'manual_trigger', 'priority_recalc', name='sync_type'), nullable=False)
    sync_started_at = Column(DateTime, nullable=False, index=True)
    sync_completed_at = Column(DateTime, index=True)
    sync_duration_seconds = Column(Integer)
    
    # REZULTATY SYNCHRONIZACJI
    orders_processed = Column(Integer, default=0)
    products_created = Column(Integer, default=0)
    products_updated = Column(Integer, default=0)
    products_with_errors = Column(Integer, default=0)
    
    # DODAĆ TE BRAKUJĄCE POLA (zgodnie z database_structure.md):
    orders_fetched = Column(Integer, default=0)
    products_skipped = Column(Integer, default=0)
    processed_status_ids = Column(Text)
    baselinker_api_response_time_ms = Column(Integer)
    error_count = Column(Integer, default=0)
    error_details = Column(Text)
    
    # NOWE POLA DLA ENHANCED PRIORITY SYSTEM
    priority_recalc_triggered = Column(Boolean, default=False)
    priority_recalc_duration_seconds = Column(Integer)
    manual_overrides_preserved = Column(Integer, default=0)
    
    # STATUS I BŁĘDY
    sync_status = Column(Enum('in_progress', 'completed', 'failed', 'partial', name='sync_status'), 
                        default='in_progress', nullable=False)
    error_message = Column(Text)
    error_details_json = Column(JSON)
    
    # METADANE
    triggered_by_user_id = Column(Integer, ForeignKey('users.id'))
    baselinker_status_filter = Column(String(50))
    
    # RELACJE
    triggered_by = relationship("User")
    
    def __repr__(self):
        return f'<ProductionSyncLog {self.sync_type} {self.sync_started_at}: {self.sync_status}>'
    
    def start_sync(self, sync_type, user_id=None, status_filter=None):
        """Rozpoczęcie synchronizacji"""
        self.sync_type = sync_type
        self.sync_started_at = get_local_now()
        self.sync_status = 'in_progress'
        self.triggered_by_user_id = user_id
        self.baselinker_status_filter = status_filter
        
        logger.info("Rozpoczęto synchronizację", extra={
            'sync_id': self.id,
            'sync_type': sync_type,
            'user_id': user_id,
            'status_filter': status_filter
        })
    
    def complete_sync(self, success=True, error_message=None):
        """Zakończenie synchronizacji"""
        self.sync_completed_at = get_local_now()
        
        if self.sync_started_at:
            self.sync_duration_seconds = int(
                (self.sync_completed_at - self.sync_started_at).total_seconds()
            )
        
        if success:
            self.sync_status = 'completed' if self.products_with_errors == 0 else 'partial'
        else:
            self.sync_status = 'failed'
            self.error_message = error_message
        
        logger.info("Zakończono synchronizację", extra={
            'sync_id': self.id,
            'sync_status': self.sync_status,
            'duration_seconds': self.sync_duration_seconds,
            'orders_processed': self.orders_processed,
            'products_created': self.products_created,
            'products_updated': self.products_updated
        })

class ProductionError(db.Model):
    """
    Rejestr błędów systemu produkcyjnego
    Śledzenie wszystkich problemów w module production
    ZACHOWANE bez zmian dla kompatybilności
    """
    __tablename__ = 'prod_errors'
    
    id = Column(Integer, primary_key=True)
    error_type = Column(Enum(
        'sync_error', 'parsing_error', 'validation_error', 
        'api_error', 'database_error', 'priority_calc_error', name='error_type'
    ), nullable=False, index=True)
    error_message = Column(Text, nullable=False)
    error_details_json = Column(JSON)
    
    # KONTEKST BŁĘDU
    related_product_id = Column(Integer, ForeignKey('prod_items.id'))
    related_order_id = Column(Integer)
    
    # STATUS ROZWIĄZANIA
    is_resolved = Column(Boolean, default=False, index=True)
    resolution_notes = Column(Text)
    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey('users.id'))
    
    # METADANE
    error_occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    user_ip = Column(String(45))
    user_agent = Column(Text)
    
    # RELACJE
    related_product = relationship("ProductionItem")
    resolver = relationship("User")
    
    def __repr__(self):
        return f'<ProductionError {self.error_type} {self.error_occurred_at}>'
    
    def resolve(self, user_id, resolution_notes=None):
        """
        Oznacza błąd jako rozwiązany
        
        Args:
            user_id (int): ID użytkownika rozwiązującego
            resolution_notes (str, optional): Notatki rozwiązania
        """
        self.is_resolved = True
        self.resolved_at = get_local_now()
        self.resolved_by = user_id
        if resolution_notes:
            self.resolution_notes = resolution_notes
            
        logger.info("Rozwiązano błąd", extra={
            'error_id': self.id,
            'error_type': self.error_type,
            'resolved_by': user_id
        })

class ProductionConfig(db.Model):
    """
    Konfiguracja systemu produkcyjnego
    Centralne zarządzanie ustawieniami modułu
    ZACHOWANE bez zmian dla kompatybilności
    """
    __tablename__ = 'prod_config'
    
    id = Column(Integer, primary_key=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=False)
    config_description = Column(Text)
    config_type = Column(Enum('string', 'integer', 'boolean', 'json', 'ip_list', name='config_type'),
                        default='string')
    
    # METADANE
    updated_by = Column(Integer, ForeignKey('users.id'))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # RELACJE
    updater = relationship("User")
    
    def __repr__(self):
        return f'<ProductionConfig {self.config_key}: {self.config_value[:50]}>'
    
    @property
    def parsed_value(self):
        """Parsuje wartość konfiguracji zgodnie z typem"""
        if self.config_type == 'boolean':
            return self.config_value.lower() in ('true', '1', 'yes', 'on')
        elif self.config_type == 'integer':
            try:
                return int(self.config_value)
            except ValueError:
                return 0
        elif self.config_type == 'json':
            try:
                import json
                return json.loads(self.config_value)
            except (ValueError, TypeError):
                return {}
        elif self.config_type == 'ip_list':
            return [ip.strip() for ip in self.config_value.split(',') if ip.strip()]
        else:
            return self.config_value

class ProductionSecurityEvent(db.Model):
    """
    Zdarzenia bezpieczeństwa w module production
    Oddzielna tabela od błędów produkcyjnych - NIE zapisuje do prod_errors
    """
    __tablename__ = 'prod_security_events'
    
    id = Column(Integer, primary_key=True)
    event_type = Column(Enum(
        'access_granted', 'access_denied', 'ip_added', 
        'ip_removed', 'config_change', name='security_event_type'
    ), nullable=False, index=True)
    
    # Informacje o zdarzeniu
    ip_address = Column(String(45), nullable=False, index=True)
    station_type = Column(String(50))
    request_path = Column(String(255))
    request_method = Column(String(10))
    
    # Szczegóły
    user_agent = Column(Text)
    event_details = Column(JSON)
    
    # Metadane
    created_at = Column(DateTime, default=get_local_now, index=True)
    
    def __repr__(self):
        return f'<SecurityEvent {self.event_type} from {self.ip_address} at {self.created_at}>'
    
    @classmethod
    def log_event(cls, event_type, ip_address, details=None):
        """
        Szybka metoda do logowania zdarzeń
        
        Args:
            event_type (str): Typ zdarzenia
            ip_address (str): Adres IP
            details (dict): Dodatkowe szczegóły
        """
        try:
            event = cls(
                event_type=event_type,
                ip_address=ip_address,
                station_type=details.get('station_type') if details else None,
                request_path=details.get('path') if details else None,
                request_method=details.get('method') if details else None,
                user_agent=details.get('user_agent') if details else None,
                event_details=details
            )
            
            db.session.add(event)
            db.session.commit()
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error("Błąd zapisywania security event", extra={
                'event_type': event_type,
                'ip_address': ip_address,
                'error': str(e)
            })
            return False