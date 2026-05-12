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
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Date, Numeric, Enum, Boolean, JSON, ForeignKey
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship, validates, backref
from sqlalchemy.sql import func
from sqlalchemy.exc import SQLAlchemyError
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

class ProductionConfiguration(db.Model):
    """Słownik kombinacji (gatunek, technologia, klasa)."""
    __tablename__ = 'prod_configurations'

    id = Column(Integer, primary_key=True)
    species = Column(String(50), nullable=False)
    technology = Column(String(50), nullable=False)
    wood_class = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=get_local_now)

    __table_args__ = (
        db.UniqueConstraint('species', 'technology', 'wood_class', name='uq_config'),
    )

    def __repr__(self):
        return f'<ProductionConfiguration {self.species}/{self.technology}/{self.wood_class}>'

    @classmethod
    def find_or_create(cls, species, technology, wood_class):
        """Znajdź istniejącą konfigurację lub utwórz nową. Idempotentne."""
        s = species or 'unknown'
        t = technology or 'unknown'
        w = wood_class or 'unknown'
        cfg = cls.query.filter_by(species=s, technology=t, wood_class=w).first()
        if cfg:
            return cfg
        cfg = cls(species=s, technology=t, wood_class=w)
        db.session.add(cfg)
        db.session.flush()
        return cfg


class ProductionOrder(db.Model):
    """
    Zamówienie produkcyjne — jeden wiersz per baselinker_order_id.
    Zawiera dane wspólne dla wszystkich produktów w zamówieniu.
    """
    __tablename__ = 'prod_orders'

    id = Column(Integer, primary_key=True)
    baselinker_order_id = Column(Integer, nullable=False, unique=True, index=True)
    internal_order_number = Column(String(20), nullable=False)
    baselinker_status_id = Column(Integer, index=True)
    payment_date = Column(DateTime, index=True)

    client_order_number = Column(String(200))
    order_notes = Column(Text)

    client_name = Column(String(255), index=True)
    client_email = Column(String(255))
    client_phone = Column(String(50))
    delivery_address = Column(Text)

    delivery_method = Column(String(255))
    delivery_fullname = Column(String(255))
    delivery_company = Column(String(255))
    delivery_city = Column(String(100))
    delivery_postcode = Column(String(20))
    delivery_country_code = Column(String(10))

    override_delivery_method = Column(String(255))
    logistics_completed_at = Column(DateTime, index=True)

    shipping_package_id = Column(Integer)
    shipping_tracking_number = Column(String(100))
    shipping_courier_name = Column(String(100))
    shipping_price = Column(Numeric(10, 2))
    shipping_label_base64 = Column(LONGTEXT)
    shipping_created_at = Column(DateTime)

    attachment_file_name = Column(String(255))
    attachment_file_url = Column(Text)

    sync_source = Column(Enum('baselinker_auto', 'manual_entry', name='sync_source'),
                         default='baselinker_auto')
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    products = relationship('ProductionProduct', back_populates='order',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ProductionOrder BL={self.baselinker_order_id} #{self.internal_order_number}>'

    @property
    def is_personal_pickup(self):
        """Czy zamówienie jest do odbioru osobistego."""
        if self.delivery_method:
            method_lower = self.delivery_method.lower()
            for keyword in ['odbiór', 'odbior', 'osobisty', 'przy odbiorze', 'pickup', 'self pickup']:
                if keyword in method_lower:
                    return True
        has_address = bool(self.delivery_address and self.delivery_address.strip())
        has_city = bool(self.delivery_city and self.delivery_city.strip())
        has_postcode = bool(self.delivery_postcode and self.delivery_postcode.strip())
        if not has_address and not has_city and not has_postcode:
            return True
        return False

    @property
    def delivery_type(self):
        return 'personal_pickup' if self.is_personal_pickup else 'courier'

    @property
    def has_attachment(self):
        return bool(self.attachment_file_url and self.attachment_file_url.strip())

    @property
    def attachment_file_extension(self):
        if not self.attachment_file_name:
            return None
        return self.attachment_file_name.split('.')[-1].lower() if '.' in self.attachment_file_name else None

    @property
    def is_attachment_image(self):
        return self.attachment_file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']

    @property
    def is_attachment_pdf(self):
        return self.attachment_file_extension == 'pdf'

    @property
    def has_order_notes(self):
        return bool(self.order_notes and self.order_notes.strip())

    @property
    def has_client_order_number(self):
        return bool(self.client_order_number and self.client_order_number.strip())


class ProductionProduct(db.Model):
    """Pozycja produktu w zamówieniu. Zachowuje stare prod_items.id."""
    __tablename__ = 'prod_products'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    configuration_id = Column(Integer, ForeignKey('prod_configurations.id'),
                              nullable=True, index=True)

    short_product_id = Column(String(20), nullable=False, index=True)
    original_product_id = Column(
        Integer,
        ForeignKey('prod_products.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment='FK do oryginalnego prod_products gdy ten rekord jest doróbką; NULL dla oryginałów'
    )
    product_sequence_in_order = Column(Integer, nullable=False)
    baselinker_product_id = Column(String(50))
    original_product_name = Column(Text, nullable=False)

    parsed_length_cm = Column(Numeric(10, 2))
    parsed_width_cm = Column(Numeric(10, 2))
    parsed_thickness_cm = Column(Numeric(10, 2))
    parsed_finish_state = Column(String(50))
    parsed_finish_type = Column(String(20), default='surowe', nullable=False)
    parsed_finish_color_type = Column(String(20))
    parsed_finish_gloss = Column(String(20))
    parsed_finish_color = Column(String(50))

    parsed_edge_processing = Column(Boolean, default=False, nullable=False)
    cut_to_size = Column(Boolean, default=True, nullable=False)
    parsed_edge_type = Column(String(20))
    parsed_edge_radius = Column(Integer)
    parsed_edge_angle = Column(Integer)
    parsed_edge_letters = Column(JSON)
    edge_svg = Column(Text)
    shape_svg = Column(Text)
    lamella_direction = Column(Integer)
    quote_item_detail_id = Column(Integer)

    thickness_group = Column(String(10), index=True)
    volume_m3 = Column(Numeric(10, 6))
    unit_price_net = Column(Numeric(10, 2))
    total_value_net = Column(Numeric(10, 2))
    quantity = Column(Integer, default=1, nullable=False)

    current_status = Column(Enum(
        'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_kompletacje',
        'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_wykanczanie',
        'czeka_na_lakiernie', 'czeka_na_logistyke', 'czeka_na_pakowanie',
        'spakowane', 'anulowane', 'wstrzymane', 'w_realizacji',
        name='production_status'
    ), default='czeka_na_wyciecie', nullable=False, index=True)

    deadline_date = Column(Date, index=True)
    days_until_deadline = Column(Integer)

    priority_rank = Column(Integer, index=True)
    priority_manual_override = Column(Boolean, default=False, index=True)
    is_priority = Column(Boolean, default=False, nullable=False, index=True)

    # quantity_done_* i *_completed_at - jak w starym modelu
    quantity_done_cutting = Column(Integer, default=0, nullable=False)
    quantity_done_assembly = Column(Integer, default=0, nullable=False)
    quantity_done_completion = Column(Integer, default=0, nullable=False)
    quantity_done_gluing = Column(Integer, default=0, nullable=False)
    quantity_done_formatting = Column(Integer, default=0, nullable=False)
    quantity_done_finishing = Column(Integer, default=0, nullable=False)
    quantity_done_painting = Column(Integer, default=0, nullable=False)
    quantity_done_packaging = Column(Integer, default=0, nullable=False)

    cutting_completed_at = Column(DateTime, index=True)
    assembly_completed_at = Column(DateTime, index=True)
    completion_completed_at = Column(DateTime, index=True)
    gluing_completed_at = Column(DateTime, index=True)
    formatting_completed_at = Column(DateTime, index=True)
    finishing_completed_at = Column(DateTime, index=True)
    painting_completed_at = Column(DateTime, index=True)
    packaging_completed_at = Column(DateTime, index=True)

    label_printed_at = Column(DateTime)
    label_print_count = Column(Integer, default=0, nullable=False)

    production_notes = Column(Text)
    quality_issues = Column(Text)

    created_at = Column(DateTime, default=get_local_now, index=True)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    order = relationship('ProductionOrder', back_populates='products')
    configuration = relationship('ProductionConfiguration')
    original = relationship(
        'ProductionProduct',
        remote_side='ProductionProduct.id',
        backref='rework_children',
        foreign_keys=[original_product_id],
    )

    def __repr__(self):
        return f'<ProductionProduct {self.short_product_id}: {self.current_status}>'

    @validates('short_product_id')
    def validate_product_id(self, key, product_id):
        import re
        if not re.match(r'^\d+_\d+$', product_id):
            raise ValueError(f"Product ID musi być w formacie N_S, otrzymano: {product_id}")
        return product_id

    # === STARE PROPERTIES (zachowane bez zmian) ===
    @property
    def thickness(self):
        return self.parsed_thickness_cm

    @property
    def finish_state(self):
        return self.parsed_finish_state

    @property
    def is_rework(self):
        return self.original_product_id is not None

    @property
    def status_display_name(self):
        status_names = {
            'czeka_na_wyciecie': 'Czeka na wycięcie',
            'czeka_na_skladanie': 'Czeka na składanie',
            'czeka_na_kompletacje': 'Czeka na kompletację',
            'czeka_na_sklejanie': 'Czeka na sklejanie',
            'czeka_na_formatowanie': 'Czeka na formatowanie',
            'czeka_na_wykanczanie': 'Czeka na wykańczanie',
            'czeka_na_lakiernie': 'Czeka na lakiernię',
            'czeka_na_logistyke': 'Czeka na logistykę',
            'czeka_na_pakowanie': 'Czeka na pakowanie',
            'spakowane': 'Spakowane',
            'anulowane': 'Anulowane',
            'wstrzymane': 'Wstrzymane',
            'w_realizacji': 'W realizacji'
        }
        return status_names.get(self.current_status, self.current_status)

    @property
    def is_overdue(self):
        if not self.deadline_date:
            return False
        return date.today() > self.deadline_date

    @property
    def is_priority_locked(self):
        return bool(self.priority_manual_override)

    # === METODY DOMENOWE (przeniesione 1:1 ze starego ProductionItem) ===
    def get_thickness_group(self):
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
        self.thickness_group = self.get_thickness_group()
        return self.thickness_group

    def lock_priority(self, rank: int):
        if rank < 1:
            raise ValueError("Numer priorytetu musi być >= 1")
        self.priority_rank = rank
        self.priority_manual_override = True

    def unlock_priority(self):
        self.priority_manual_override = False

    def is_in_production_queue(self):
        return self.current_status in [
            'czeka_na_wyciecie', 'czeka_na_skladanie',
            'czeka_na_pakowanie', 'w_realizacji'
        ]

    def validate_for_prioritization(self):
        required_fields = {
            'species': self.configuration.species if self.configuration else None,
            'finish_state': self.parsed_finish_state,
            'thickness': self.parsed_thickness_cm,
            'wood_class': self.configuration.wood_class if self.configuration else None,
            'width': self.parsed_width_cm,
            'length': self.parsed_length_cm
        }
        missing_fields = [
            n for n, v in required_fields.items()
            if not v or (isinstance(v, str) and v.strip() == '')
        ]
        is_valid = len(missing_fields) == 0 and self.is_in_production_queue()
        return is_valid, missing_fields

    def get_quantity_done(self, station_code):
        return getattr(self, f'quantity_done_{station_code}', 0)

    def set_quantity_done(self, station_code, value, *,
                          actor_user_id=None, actor_device_id=None, source='web'):
        attr_name = f'quantity_done_{station_code}'
        old_value = getattr(self, attr_name, 0) or 0
        # quantity_done może przekraczać quantity gdy oryginał stracił sztuki przez reject
        # (statystyki pracy stanowisk są pełną historią, niezależnie od bieżącego batcha).
        value = max(0, value)
        setattr(self, attr_name, value)

        now = get_local_now()

        completed_attr = f'{station_code}_completed_at'
        if value >= self.quantity:
            if getattr(self, completed_attr) is None:
                setattr(self, completed_attr, now)
        else:
            setattr(self, completed_attr, None)

        self.updated_at = now

        if value != old_value and self.id is not None:
            normalized_source = source if source in ('web', 'mobile', 'admin', 'system', 'auto_skip') else 'web'
            event = ProductionStationEvent(
                production_item_id=self.id,
                station_code=station_code,
                delta=value - old_value,
                quantity_done_after=value,
                created_at=now,
                user_id=actor_user_id,
                device_id=actor_device_id,
                source=normalized_source,
            )
            db.session.add(event)
        return value

    def increment_quantity_done(self, station_code, amount=1, **actor_kwargs):
        current = self.get_quantity_done(station_code)
        return self.set_quantity_done(station_code, current + amount, **actor_kwargs)

    def decrement_quantity_done(self, station_code, amount=1, **actor_kwargs):
        current = self.get_quantity_done(station_code)
        return self.set_quantity_done(station_code, current - amount, **actor_kwargs)

    def is_station_complete(self, station_code):
        return self.get_quantity_done(station_code) >= self.quantity

    def should_skip_finishing(self):
        if self.parsed_finish_type == 'surowe':
            return not self.parsed_edge_processing
        return False

    def should_skip_to_logistics(self):
        return self.cut_to_size is False

    def complete_task(self, station_code):
        now = get_local_now()
        next_status_map = {
            'cutting': 'czeka_na_kompletacje',
            'assembly': 'czeka_na_kompletacje',
            'completion': 'czeka_na_sklejanie',
            'gluing': 'czeka_na_formatowanie',
            'formatting': 'czeka_na_wykanczanie',
            'finishing': 'czeka_na_logistyke',
            'painting': 'czeka_na_logistyke',
            'packaging': 'spakowane'
        }
        if station_code in next_status_map:
            next_status = next_status_map[station_code]

            if station_code == 'gluing' and self.should_skip_to_logistics():
                next_status = 'czeka_na_logistyke'
                for skipped in ('formatting', 'finishing'):
                    self.set_quantity_done(skipped, self.quantity, source='auto_skip')
                    completed_attr = f'{skipped}_completed_at'
                    if getattr(self, completed_attr, None) is None:
                        setattr(self, completed_attr, now)

            if station_code == 'formatting' and self.should_skip_finishing():
                next_status = 'czeka_na_logistyke'
                self.set_quantity_done('finishing', self.quantity, source='system')

            if station_code == 'finishing':
                if self.parsed_finish_type in ('olejowane', 'lakierowane'):
                    next_status = 'czeka_na_lakiernie'

            if next_status == 'czeka_na_logistyke' and (self.order and self.order.is_personal_pickup):
                next_status = 'czeka_na_pakowanie'
                if self.order:
                    self.order.logistics_completed_at = now

            self.current_status = next_status
            completed_attr = f'{station_code}_completed_at'
            if getattr(self, completed_attr, None) is None:
                setattr(self, completed_attr, now)

        self.updated_at = now


# Alias kompatybilności dla starego kodu — zostanie usunięty osobnym commitem
ProductionItem = ProductionProduct


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
        'api_error', 'database_error', 'priority_calc_error', 'template_error',
        name='error_type'
    ), nullable=False, index=True)
    error_message = Column(Text, nullable=False)
    error_details_json = Column(JSON)
    stack_trace = Column(Text)  # Pełny stack trace dla debugowania

    # KONTEKST BŁĘDU
    related_product_id = Column(Integer, ForeignKey('prod_products.id'))
    related_order_id = Column(Integer)
    request_url = Column(String(500))  # URL gdzie wystąpił błąd
    request_method = Column(String(10))  # GET, POST, etc.

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
    related_product = relationship("ProductionProduct")
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


class LabelPrintJob(db.Model):
    """
    Zadanie drukowania etykiety w kolejce do print-agenta.
    Wstawiane przez CRM gdy LABEL_PRINTER_USE_AGENT=True; pobierane przez
    agent przez /api/print-agent/jobs i drukowane lokalnie w LAN biura.
    """
    __tablename__ = 'prod_print_queue'

    STATUS_PENDING = 'pending'
    STATUS_PRINTED = 'printed'
    STATUS_FAILED = 'failed'
    STATUS_EXPIRED = 'expired'

    id = Column(Integer, primary_key=True)
    short_product_id = Column(String(20), nullable=False, index=True)
    baselinker_order_id = Column(Integer, nullable=True)
    zpl_payload = Column(Text, nullable=False)
    station_code = Column(String(50), nullable=False)
    requested_by_type = Column(String(20), nullable=False, comment='user|device')
    requested_by_id = Column(String(100), nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(
        Enum('pending', 'printed', 'failed', 'expired', name='print_job_status'),
        default='pending', nullable=False, index=True,
    )
    printed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    def __repr__(self):
        return f'<LabelPrintJob {self.id} {self.short_product_id} {self.status}>'


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


class ProductionDevice(db.Model):
    """
    Urządzenia mobilne (tablety) zarejestrowane do API produkcyjnego.
    Każdy tablet produkcyjny to osobny rekord z własnym JWT token_version.
    Bump token_version = unieważnienie wszystkich istniejących JWT tego urządzenia.
    """
    __tablename__ = 'prod_devices'

    id = Column(Integer, primary_key=True)
    device_id = Column(String(64), unique=True, nullable=False, index=True)
    device_name = Column(String(128), nullable=True)
    station_code = Column(String(32), nullable=False, index=True)
    token_version = Column(Integer, nullable=False, default=1)
    last_ip = Column(String(45), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, default=get_local_now, nullable=False)
    app_version = Column(String(32), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    VALID_STATION_CODES = {
        'packaging', 'cutting', 'assembly', 'completion', 'gluing', 'formatting', 'finishing'
    }

    @validates('station_code')
    def validate_station_code(self, key, value):
        if value not in self.VALID_STATION_CODES:
            raise ValueError(
                f"Nieprawidłowy station_code: {value}. "
                f"Dozwolone: {sorted(self.VALID_STATION_CODES)}"
            )
        return value

    def __repr__(self):
        return f'<ProductionDevice {self.device_id} [{self.station_code}]>'

    def touch(self, ip=None, app_version=None):
        """Aktualizuje last_seen_at, last_ip, app_version. Nie commituje."""
        self.last_seen_at = get_local_now()
        if ip:
            self.last_ip = ip
        if app_version:
            self.app_version = app_version

    def revoke_tokens(self):
        """Unieważnia wszystkie istniejące JWT przez bump token_version."""
        self.token_version += 1
        logger.info("Unieważniono tokeny urządzenia", extra={
            'device_id': self.device_id,
            'station_code': self.station_code,
            'new_token_version': self.token_version
        })


class ProcessedMobileOperation(db.Model):
    """
    Idempotency log dla Mobile API — każdy operation_id jednoznacznie
    identyfikuje żądanie z offline queue tabletu. Retry z tym samym
    X-Operation-Id zwraca zapisany response, bez wykonywania akcji.

    Zapisywane są tylko odpowiedzi 2xx i 4xx. 5xx nie — klient retry.
    """
    __tablename__ = 'processed_mobile_operations'

    operation_id = Column(String(64), primary_key=True)
    endpoint = Column(String(64), nullable=False, index=True)
    order_id = Column(Integer, nullable=True)
    device_id = Column(String(64), nullable=True, index=True)
    response_status = Column(Integer, nullable=False)
    response_body = Column(LONGTEXT, nullable=False)
    processed_at = Column(DateTime, default=get_local_now, nullable=False, index=True)

    def __repr__(self):
        return (
            f'<ProcessedMobileOperation {self.operation_id} '
            f'[{self.endpoint} → {self.response_status}]>'
        )


class MobileAppRelease(db.Model):
    """
    Release aplikacji mobilnej (APK dla tabletów stanowiskowych).

    Plik APK trzymany lokalnie w `instance/<file_path>` (poza repo).
    Tablet pyta `/api/mobile/app/version` o najnowszy aktywny release i pobiera
    APK przez `/api/mobile/app/apk?version=<version_code>`. SHA-256 jest do
    weryfikacji integralności pobierania (Android sprawdza po stronie klienta).

    is_active=False = release wycofany (np. krytyczny bug); pomijany przy
    rozstrzyganiu „najnowszej wersji" — nie usuwamy fizycznie żeby zachować
    historię i móc dojść co kiedy było wgrane.
    """
    __tablename__ = 'mobile_app_releases'

    id = Column(Integer, primary_key=True)
    version_code = Column(Integer, unique=True, nullable=False, index=True)
    version_name = Column(String(50), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    release_notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, default=get_local_now)
    uploaded_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    uploaded_by = relationship("User")

    def __repr__(self):
        return f'<MobileAppRelease v{self.version_code} ({self.version_name})>'

    @classmethod
    def latest_active(cls):
        """
        Najnowszy aktywny release (po version_code DESC) lub None.

        Endpoint /api/mobile/app/version pyta tablet o najnowszy APK przed
        każdą rejestracją — jeśli wybuchnie, tablet w ogóle się nie podłączy.
        Mid-query disconnect MySQL na shared hostingu CyberFolks potrafi
        zostawić cursor bez metadanych wierszy, co eskaluje na poziomie
        ORM do NoSuchColumnError ('mobile_app_releases.id') albo bare
        AttributeError na '_NoResultMetaData'. W obu przypadkach lepiej
        zwrócić None (klient widzi 'brak nowego release'u' i nie próbuje
        update'u) niż 500.
        """
        try:
            return cls.query.filter_by(is_active=True).order_by(
                cls.version_code.desc()
            ).first()
        except (SQLAlchemyError, AttributeError) as e:
            logger.warning(
                "MobileAppRelease.latest_active() padło — zwracam None",
                error_type=type(e).__name__,
                error=str(e)
            )
            try:
                db.session.rollback()
            except Exception:
                pass
            return None

class ProductionStationEvent(db.Model):
    """
    Log zdarzeń stanowiskowych — każda zmiana quantity_done_<station>
    (zarówno + jak i -) tworzy rekord. Pozwala odpowiedzieć na pytanie
    "co stanowisko X zrobiło dnia Y" niezależnie od bieżącego stanu pozycji.

    Zapis NIE jest backfillowany — historia zaczyna się od wdrożenia tabeli.
    """
    __tablename__ = 'prod_station_events'

    id = Column(Integer, primary_key=True)
    production_item_id = Column(
        Integer, ForeignKey('prod_products.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    station_code = Column(String(32), nullable=False, index=True)
    delta = Column(Integer, nullable=False,
                   comment='Zmiana wartości quantity_done (+/-)')
    quantity_done_after = Column(Integer, nullable=False,
                                 comment='Stan quantity_done_<station> po operacji')
    created_at = Column(DateTime, default=get_local_now, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    device_id = Column(String(64), nullable=True, index=True,
                       comment='prod_devices.device_id (gdy mobile)')
    source = Column(
        Enum('web', 'mobile', 'admin', 'system', 'auto_skip',
             name='station_event_source'),
        nullable=False, default='web', index=True
    )

    item = relationship(
        'ProductionProduct',
        backref=backref('station_events', passive_deletes=True)
    )
    user = relationship('User')

    def __repr__(self):
        sign = '+' if self.delta >= 0 else ''
        return (f'<ProductionStationEvent item={self.production_item_id} '
                f'{self.station_code} {sign}{self.delta} '
                f'→ {self.quantity_done_after}>')
