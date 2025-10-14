# modules/reports/models.py
"""
Modele bazy danych dla modułu Reports
"""

from extensions import db
from datetime import datetime, timedelta
from sqlalchemy import Index
import re
from .utils import PostcodeToStateMapper
from modules.logging import get_structured_logger
# Inicjalizacja loggera
reports_logger = get_structured_logger('reports.routers')
reports_logger.info("✅ reports_logger zainicjowany poprawnie w models.py")


class BaselinkerReportOrder(db.Model):
    """
    Model dla tabeli raportów zamówień z Baselinker
    Każdy wiersz = jeden produkt w zamówieniu
    """
    __tablename__ = 'baselinker_reports_orders'
    
    # === PODSTAWOWE POLA ===
    id = db.Column(db.Integer, primary_key=True)
    is_manual = db.Column(db.Boolean, default=False, nullable=False, comment="Czy rekord dodany ręcznie")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === DANE ZAMÓWIENIA (kolumny 1-14) ===
    date_created = db.Column(db.Date, nullable=False, comment="1. Data")
    total_m3 = db.Column(db.Numeric(10, 4), nullable=True, comment="2. TTL m3 (obliczane)")
    order_amount_net = db.Column(db.Numeric(10, 2), nullable=True, comment="3. Kwota zamówień netto")
    baselinker_order_id = db.Column(db.Integer, nullable=True, unique=False, comment="4. Numer zamówienia Baselinker")
    internal_order_number = db.Column(db.String(50), nullable=True, comment="5. Numer wew. zamówienia (extra_field_1)")
    customer_name = db.Column(db.String(200), nullable=True, comment="6. Imię i nazwisko")
    delivery_postcode = db.Column(db.String(20), nullable=True, comment="7. Kod pocztowy dostawy")
    delivery_city = db.Column(db.String(100), nullable=True, comment="8. Miejscowość dostawy")
    delivery_address = db.Column(db.String(250), nullable=True, comment="9. Ulica i numer domu/mieszkania")
    delivery_state = db.Column(db.String(50), nullable=True, comment="10. Województwo dostawy")
    phone = db.Column(db.String(100), nullable=True, comment="11. Numer telefonu")
    caretaker = db.Column(db.String(100), nullable=True, comment="12. Opiekun (kto złożył zamówienie)")
    delivery_method = db.Column(db.String(100), nullable=True, comment="13. Metoda dostawy")
    order_source = db.Column(db.String(50), nullable=True, comment="14. Źródło zamówienia")
    
    # === NOWE POLA DLA OBSŁUGI NETTO/BRUTTO ===
    price_type = db.Column(db.Enum('netto', 'brutto', '', name='price_type_enum'), nullable=True, default='', comment="Typ ceny z extra_field_106169: netto/brutto/puste")
    original_amount_from_baselinker = db.Column(db.Numeric(10, 2), nullable=True, comment="Oryginalna kwota pobrana z Baselinker przed konwersją")

    # === DANE PRODUKTU (kolumny 15-24) ===
    group_type = db.Column(db.Enum('towar', 'usługa', name='group_type_enum'), nullable=True, comment="15. Grupa")
    product_type = db.Column(db.Enum('klejonka', 'deska', 'worek opałowy', 'tarcica', 'suszenie', 'klejenie', name='product_type_enum'), nullable=True, comment="16. Rodzaj")
    finish_state = db.Column(db.String(50), nullable=True, comment="17. Stan (wykończenie)")
    wood_species = db.Column(db.String(50), nullable=True, comment="18. Gatunek")
    technology = db.Column(db.String(50), nullable=True, comment="19. Technologia")
    wood_class = db.Column(db.String(10), nullable=True, comment="20. Klasa")
    length_cm = db.Column(db.Numeric(10, 2), nullable=True, comment="21. Długość")
    width_cm = db.Column(db.Numeric(10, 2), nullable=True, comment="22. Szerokość")
    thickness_cm = db.Column(db.Numeric(10, 2), nullable=True, comment="23. Grubość")
    quantity = db.Column(db.Integer, nullable=True, comment="24. Ilość")
    
    # === CENY I WARTOŚCI (kolumny 25-32) ===
    price_gross = db.Column(db.Numeric(10, 2), nullable=True, comment="25. Cena brutto")
    price_net = db.Column(db.Numeric(10, 2), nullable=True, comment="26. Cena netto")
    value_gross = db.Column(db.Numeric(10, 2), nullable=True, comment="27. Wartość brutto")
    value_net = db.Column(db.Numeric(10, 2), nullable=True, comment="28. Wartość netto")
    volume_per_piece = db.Column(db.Numeric(10, 4), nullable=True, comment="29. Objętość 1 szt.")
    total_volume = db.Column(db.Numeric(10, 4), nullable=True, comment="30. Objętość TTL")
    total_surface_m2 = db.Column(db.Numeric(10, 4), nullable=True, comment="30a. Powierzchnia całkowita produktu (m²)")
    price_per_m3 = db.Column(db.Numeric(10, 2), nullable=True, comment="31. Cena za m3")
    avg_order_price_per_m3 = db.Column(db.Numeric(10, 2), nullable=True, comment="32. Średnia cena za m3 w zamówieniu")
    realization_date = db.Column(db.Date, nullable=True, comment="33. Data realizacji")
    
    # === STATUS I PŁATNOŚCI (kolumny 33-37) ===
    current_status = db.Column(db.String(100), nullable=True, comment="34. Status")
    delivery_cost = db.Column(db.Numeric(10, 2), nullable=True, comment="35. Koszt kuriera dla klienta")
    payment_method = db.Column(db.String(100), nullable=True, comment="36. Sposób płatności")
    paid_amount_net = db.Column(db.Numeric(10, 2), default=0.00, comment="37. Zapłacono TTL netto")
    balance_due = db.Column(db.Numeric(10, 2), nullable=True, comment="38. Saldo")
    
    # === PRODUKCJA I ODBIÓR (kolumny 38-40) ===
    production_volume = db.Column(db.Numeric(10, 4), default=0.00, comment="39. Ilość w produkcji")
    production_value_net = db.Column(db.Numeric(10, 2), default=0.00, comment="40. Wartość netto w produkcji")
    ready_pickup_volume = db.Column(db.Numeric(10, 4), default=0.00, comment="41. Ilość gotowa do odbioru")
    ready_pickup_value_net = db.Column(db.Numeric(10, 2), default=0.00, comment="41a. Wartość netto gotowa do odbioru")
    
    # === POLA TECHNICZNE (nie wyświetlane w tabeli) ===
    baselinker_status_id = db.Column(db.Integer, nullable=True, comment="ID statusu z Baselinker")
    raw_product_name = db.Column(db.Text, nullable=True, comment="Oryginalna nazwa produktu z Baselinker")
    email = db.Column(db.String(150), nullable=True, comment="Email klienta")
    
    # === INDEKSY ===
    __table_args__ = (
        Index('idx_baselinker_order_id', 'baselinker_order_id'),
        Index('idx_date_created', 'date_created'),
        Index('idx_is_manual', 'is_manual'),
        Index('idx_internal_order_number', 'internal_order_number'),
    )
    
    def __repr__(self):
        return f'<BaselinkerReportOrder {self.id}: Order {self.baselinker_order_id}, {self.customer_name}>'
    
    
    @classmethod
    def get_filtered_orders(cls, filters=None, date_from=None, date_to=None):
        """
        Pobiera zamówienia z filtrami

        Args:
            filters (dict): Słownik filtrów {kolumna: lista_wartości}
            date_from (date): Data od
            date_to (date): Data do

        Returns:
            Query: SQLAlchemy Query object
        """
        query = cls.query

        # Filtr daty
        if date_from:
            query = query.filter(cls.date_created >= date_from)
        if date_to:
            query = query.filter(cls.date_created <= date_to)

        # Dodatkowe filtry (obsługa multiple values)
        if filters:
            for column, values in filters.items():
                if values and hasattr(cls, column):
                    column_attr = getattr(cls, column)
                    if isinstance(values, list) and values:
                        # Multiple values - użyj IN
                        query = query.filter(column_attr.in_(values))
                    elif isinstance(values, str) and values.strip():
                        # Single value - użyj LIKE
                        query = query.filter(column_attr.like(f'%{values.strip()}%'))

        # POPRAWKA SORTOWANIA: Najnowsze daty na górze jako GŁÓWNY priorytet
        from sqlalchemy import case, desc, asc

        return query.order_by(
            # PRIORYTET 1: Najnowsze daty na górze (główne kryterium)
            desc(cls.date_created),
            # PRIORYTET 2: W ramach tego samego dnia - ręczne wpisy NA POCZĄTKU
            cls.is_manual.desc(),  # TRUE (ręczne) przed FALSE (automatyczne)
            # PRIORYTET 3: W ramach tego samego dnia i typu - większe ID (nowsze)
            desc(cls.id),
            # PRIORYTET 4: Baselinker ID jako ostatnie kryterium
            desc(case(
                (cls.baselinker_order_id.is_(None), 0),  # NULL = najniższy priorytet
                else_=cls.baselinker_order_id
            ))
        )
    
    @classmethod
    def get_orders_by_date_range(cls, days_back=None):
        """
        Pobiera zamówienia z ostatnich X dni lub wszystkie jeśli days_back=None

        Args:
            days_back (int): Ile dni wstecz (None = wszystkie zamówienia)

        Returns:
            List[BaselinkerReportOrder]: Lista zamówień
        """
        query = cls.query

        # ZMIANA: Tylko jeśli podano days_back, dodaj filtr daty
        if days_back is not None:
            date_from = datetime.now().date() - timedelta(days=days_back)
            query = query.filter(cls.date_created >= date_from)
        
        print(f"[DEBUG] get_orders_by_date_range: Pokazuję WSZYSTKIE statusy (bez domyślnych wykluczeń)")

        return query.order_by(cls.date_created.desc()).all()
    
    @classmethod
    def get_statistics(cls, filtered_query=None):
        """
        Oblicza statystyki dla widocznych (przefiltrowanych) zamówień
        NAPRAWKA: Poprawione grupowanie zamówień i obliczenia
        NOWE: Dodana kolumna "Do odebrania" (pickup_ready_volume)
        POPRAWKA 1: Dodano statystykę "wartość klejonek netto"
        POPRAWKA 2: TTL m3 teraz tylko dla klejonek
        POPRAWKI 3 i 4: Dodano statystyki dla deski
        POPRAWKA 5: Dodano statystykę "wartość usług netto"

        Args:
            filtered_query: Query object z filtrami

        Returns:
            dict: Słownik ze statystykami
        """
        if filtered_query is None:
            filtered_query = cls.query

        orders = filtered_query.all()

        stats = {
            'total_m3': 0.0,  # TTL m3 klejonki
            'order_amount_net': 0.0,
            'value_net': 0.0,
            'value_gross': 0.0,
            'avg_price_per_m3': 0.0,
            'delivery_cost': 0.0,
            'paid_amount_net': 0.0,
            'balance_due': 0.0,
            'production_volume': 0.0,
            'production_value_net': 0.0,
            'ready_pickup_volume': 0.0,
            'ready_pickup_value_net': 0.0,
            'pickup_ready_volume': 0.0,
            'unique_orders': 0,
            'products_count': 0,
            'klejonka_value_net': 0.0,
            'drying_total_m3': 0.0,
            'deska_value_net': 0.0,
            'deska_total_m3': 0.0,
            'services_value_net': 0.0,
            'suszenie_value_net': 0.0,
            'klejenie_value_net': 0.0
        }

        if not orders:
            return stats

        # Grupowanie zamówień z obsługą ręcznych wpisów
        orders_by_unique_id = {}
        for order in orders:
            # Dla zamówień z Baselinker używamy baselinker_order_id
            # Dla ręcznych wpisów każdy ma unikalny klucz
            if order.baselinker_order_id:
                unique_id = f"bl_{order.baselinker_order_id}"
            else:
                unique_id = f"manual_{order.id}"

            if unique_id not in orders_by_unique_id:
                orders_by_unique_id[unique_id] = {
                    'products': [],
                    'is_manual': order.is_manual or False
                }
            orders_by_unique_id[unique_id]['products'].append(order)

        product_level_stats = {
            'total_m3': 0.0,
            'value_net': 0.0,
            'value_gross': 0.0,
            'production_volume': 0.0,
            'production_value_net': 0.0,
            'ready_pickup_volume': 0.0,
            'ready_pickup_value_net': 0.0,
            'pickup_ready_volume': 0.0,
            'klejonka_value_net': 0.0,
            'drying_total_m3': 0.0,
            'deska_value_net': 0.0,
            'deska_total_m3': 0.0,
            'services_value_net': 0.0,
            'suszenie_value_net': 0.0,
            'klejenie_value_net': 0.0
        }

        for order in orders:
            if order.product_type == 'klejonka':
                product_level_stats['total_m3'] += float(order.total_volume or 0)

            product_level_stats['value_net'] += float(order.value_net or 0)
            product_level_stats['value_gross'] += float(order.value_gross or 0)
            
            if order.product_type == 'klejonka':
                product_level_stats['production_volume'] += float(order.production_volume or 0)
                product_level_stats['production_value_net'] += float(order.production_value_net or 0)
                
                product_level_stats['ready_pickup_volume'] += float(order.ready_pickup_volume or 0)
                product_level_stats['ready_pickup_value_net'] += float(order.ready_pickup_value_net or 0)

            if (order.baselinker_status_id in [105113, 149777, 138620] and 
                order.product_type == 'klejonka'):
                product_level_stats['pickup_ready_volume'] += float(order.total_volume or 0)

            if order.product_type == 'klejonka':
                product_level_stats['klejonka_value_net'] += float(order.value_net or 0)

            if order.product_type in ['deska', 'tarcica']:
                product_level_stats['deska_value_net'] += float(order.value_net or 0)
                product_level_stats['deska_total_m3'] += float(order.total_volume or 0)

            if order.product_type == 'suszenie':
                product_level_stats['drying_total_m3'] += float(order.total_volume or 0)

            if order.group_type == 'usługa':
                value_net = float(order.value_net or 0)
                product_level_stats['services_value_net'] += value_net
                
                # POPRAWKA 4: Podział usług na suszenie i klejenie
                if order.product_type == 'suszenie':
                    product_level_stats['suszenie_value_net'] += value_net
                else:
                    # Wszystkie pozostałe usługi (w tym klejenie) traktuj jako klejenie
                    product_level_stats['klejenie_value_net'] += value_net

        order_level_stats = {
            'order_amount_net': 0.0,
            'delivery_cost': 0.0,
            'paid_amount_net': 0.0,
            'balance_due': 0.0
        }

        for unique_id, order_group in orders_by_unique_id.items():
            products = order_group['products']
            is_manual = order_group['is_manual']

            if not products:
                continue

            # Weź pierwszy produkt jako reprezentanta zamówienia
            representative_product = products[0]

            # NAPRAWKA: Dla ręcznych wpisów każdy jest osobnym "zamówieniem"
            if is_manual:
                # Dla ręcznych wpisów sumujemy wszystkie wartości
                for product in products:
                    order_level_stats['order_amount_net'] += float(product.order_amount_net or 0)
                    order_level_stats['delivery_cost'] += float(product.delivery_cost or 0)
                    order_level_stats['paid_amount_net'] += float(product.paid_amount_net or 0)
            
                    # ZMIANA: Do zapłaty netto = wartość produktów - zapłacono (BEZ kosztów kuriera)
                    product_balance = float(product.order_amount_net or 0) - float(product.paid_amount_net or 0)
                    order_level_stats['balance_due'] += product_balance
            else:
                # Dla zamówień Baselinker - raz na zamówienie (z pierwszego produktu)
                order_level_stats['order_amount_net'] += float(representative_product.order_amount_net or 0)
                order_level_stats['delivery_cost'] += float(representative_product.delivery_cost or 0)
                order_level_stats['paid_amount_net'] += float(representative_product.paid_amount_net or 0)
        
                # ZMIANA: Do zapłaty netto = wartość produktów - zapłacono (BEZ kosztów kuriera)
                product_balance = float(representative_product.order_amount_net or 0) - float(representative_product.paid_amount_net or 0)
                order_level_stats['balance_due'] += product_balance

        # Połącz statystyki
        stats.update(product_level_stats)
        stats.update(order_level_stats)

        # POPRAWKA: Oblicz średnią cenę za m³ jako średnią arytmetyczną (jak w Excel)
        # Zamiast dzielić łączną wartość przez łączną objętość

        # Zbierz wszystkie ceny za m³ z produktów (pomijając 0 i None)
        price_per_m3_values = []
        for order in orders:
            price_per_m3 = float(order.price_per_m3 or 0)
            if price_per_m3 > 0:  # Pomiń produkty bez ceny za m³
                price_per_m3_values.append(price_per_m3)

        # Oblicz średnią arytmetyczną (jak Excel AVERAGE)
        if price_per_m3_values:
            stats['avg_price_per_m3'] = sum(price_per_m3_values) / len(price_per_m3_values)
        else:
            stats['avg_price_per_m3'] = 0.0

        # NAPRAWKA: Dodaj walidację danych
        for key, value in stats.items():
            if not isinstance(value, (int, float)) or value < 0:
                stats[key] = 0.0

        # Liczba unikalnych zamówień (grupowanie po baselinker_order_id lub ręcznych wpisach)
        unique_orders = len(orders_by_unique_id)

        # Liczba produktów fizycznych (wykluczając usługi)
        products_count = len([order for order in orders if order.group_type != 'usługa'])

        # Dodaj do statystyk
        stats['unique_orders'] = unique_orders
        stats['products_count'] = products_count

        return stats
    
    @classmethod
    def get_comparison_statistics(cls, current_filters=None, current_date_from=None, current_date_to=None):
        """
        Oblicza statystyki porównawcze dla poprzedniego okresu
        
        Args:
            current_filters: Filtry dla bieżącego okresu
            current_date_from: Data początkowa bieżącego okresu
            current_date_to: Data końcowa bieżącego okresu
            
        Returns:
            dict: Słownik z procentowymi zmianami
        """
        if not current_date_from or not current_date_to:
            return {}
            
        # Oblicz długość okresu
        period_length = (current_date_to - current_date_from).days + 1
        
        # Oblicz datę końcową poprzedniego okresu (dzień przed current_date_from)
        prev_date_to = current_date_from - timedelta(days=1)
        prev_date_from = prev_date_to - timedelta(days=period_length - 1)
        
        # Pobierz statystyki dla bieżącego okresu
        current_query = cls.get_filtered_orders(current_filters, current_date_from, current_date_to)
        current_stats = cls.get_statistics(current_query)
        
        # Pobierz statystyki dla poprzedniego okresu
        prev_query = cls.get_filtered_orders(current_filters, prev_date_from, prev_date_to)
        prev_stats = cls.get_statistics(prev_query)
        
        # Oblicz procentowe zmiany
        comparison = {}
        for key in current_stats.keys():
            current_val = float(current_stats[key] or 0)
            prev_val = float(prev_stats[key] or 0)
            
            if prev_val > 0:
                change_percent = ((current_val - prev_val) / prev_val) * 100
                comparison[key] = {
                    'change_percent': round(change_percent, 1),
                    'is_positive': change_percent >= 0
                }
            else:
                # Jeśli poprzednia wartość = 0, ale obecna > 0, to 100% wzrost
                if current_val > 0:
                    comparison[key] = {
                        'change_percent': 100.0,
                        'is_positive': True
                    }
                else:
                    comparison[key] = {
                        'change_percent': 0.0,
                        'is_positive': True
                    }
        
        return comparison

    def calculate_surface_area(self):
        """
        Oblicza powierzchnię całkowatą sześcianu (suma wszystkich 6 ścian)
    
        Returns:
            float: Powierzchnia w m² lub 0 jeśli brak wymiarów
        """
        if not (self.length_cm and self.width_cm and self.thickness_cm):
            return 0.0
    
        try:
            # Konwersja z cm na m
            length_m = float(self.length_cm) / 100
            width_m = float(self.width_cm) / 100
            thickness_m = float(self.thickness_cm) / 100
        
            # Powierzchnia sześcianu = 2 × (długość×szerokość + długość×grubość + szerokość×grubość)
            surface_one_piece = 2 * (
                length_m * width_m +      # 2 ściany: góra i dół
                length_m * thickness_m +  # 2 ściany: przód i tył
                width_m * thickness_m     # 2 ściany: lewo i prawo
            )
        
            # Powierzchnia całkowita = powierzchnia 1 sztuki × ilość
            quantity = float(self.quantity or 1)
            total_surface = surface_one_piece * quantity
        
            return round(total_surface, 4)
        
        except (ValueError, TypeError) as e:
            reports_logger.warning(f"Błąd obliczania powierzchni: {e}")
            return 0.0
    
    def calculate_fields(self):
        """Oblicza automatyczne pola w rekordzie"""
    
        # NOWE: Sprawdź czy to usługa
        if self.group_type == 'usługa':
            # === OBSŁUGA USŁUG ===
            if self.total_volume is not None and self.total_volume > 0:
                if (self.volume_per_piece is None or self.volume_per_piece == 0) and self.quantity:
                    self.volume_per_piece = float(self.total_volume) / float(self.quantity)
                if self.value_net is not None and self.total_volume > 0:
                    self.price_per_m3 = float(self.value_net) / float(self.total_volume)
            else:
                self.volume_per_piece = None
                self.total_volume = None
                self.price_per_m3 = None

            # Oblicz datę realizacji (data + 14 dni, pomiń weekendy)
            if self.date_created:
                target_date = self.date_created + timedelta(days=14)
                # Jeśli wypada w sobotę (5) lub niedzielę (6), przesuń na poniedziałek
                while target_date.weekday() >= 5:  # 5=sobota, 6=niedziela
                    target_date += timedelta(days=1)
                self.realization_date = target_date

            # Oblicz saldo (wartość netto zamówienia - zapłacono netto)
            if self.order_amount_net is not None and self.paid_amount_net is not None and self.delivery_cost is not None:
                # POPRAWKA: Logika zależna od typu ceny zamówienia
                price_type = (self.price_type or '').strip().lower()

                if price_type == 'netto':
                    # Zamówienia NETTO: klient płaci produkty netto + kuriera brutto
                    total_order_to_pay = float(self.order_amount_net) + float(self.delivery_cost)
                else:
                    # Zamówienia BRUTTO: porównujemy wszystko na netto
                    delivery_cost_net = float(self.delivery_cost) / 1.23 if self.delivery_cost else 0.0
                    total_order_to_pay = float(self.order_amount_net) + delivery_cost_net

                # Saldo = całkowita kwota do zapłaty - zapłacono netto
                self.balance_due = total_order_to_pay - float(self.paid_amount_net)

            # Automatyczne uzupełnianie województwa na podstawie kodu pocztowego
            self.auto_fill_delivery_state()

            # Oblicz produkcję i odbiór na podstawie statusu (bez objętości)
            self.update_production_fields()

            # Normalizuj województwo
            self.normalize_delivery_state()

            reports_logger.debug("Obliczono pola dla usługi",
                           service_name=self.raw_product_name,
                           balance_due=self.balance_due)
        
        else:
            # === ULEPSZONA LOGIKA DLA PRODUKTÓW FIZYCZNYCH ===

            # ✅ POPRAWKA: Oblicz objętość tylko jeśli NIE jest już ustawiona przez analizę objętości
            # Jeśli volume_per_piece i total_volume są już ustawione (z analizy objętości),
            # to NIE nadpisuj ich obliczeniami z wymiarów
            has_existing_volume = (
                self.volume_per_piece is not None and self.volume_per_piece > 0 and
                self.total_volume is not None and self.total_volume > 0
            )
    
            if not has_existing_volume and self.length_cm and self.width_cm and self.thickness_cm:
                # Oblicz objętość pojedynczej sztuki z wymiarów (tylko jeśli nie ma już objętości)
                length_m = float(self.length_cm) / 100
                width_m = float(self.width_cm) / 100  
                thickness_m = float(self.thickness_cm) / 100
                self.volume_per_piece = length_m * width_m * thickness_m
    
                # Oblicz łączną objętość
                if self.quantity:
                    self.total_volume = self.volume_per_piece * float(self.quantity)

            # Oblicz powierzchnię całkowitą (suma 6 ścian sześcianu)
            self.total_surface_m2 = self.calculate_surface_area()
        
            # Oblicz cenę za m³ (tylko jeśli jest objętość)
            if self.price_net and self.volume_per_piece and self.volume_per_piece > 0:
                self.price_per_m3 = float(self.price_net) / float(self.volume_per_piece)
            
            # Oblicz datę realizacji (data + 14 dni, pomiń weekendy)
            if self.date_created:
                target_date = self.date_created + timedelta(days=14)
                # Jeśli wypada w sobotę (5) lub niedzielę (6), przesuń na poniedziałek
                while target_date.weekday() >= 5:  # 5=sobota, 6=niedziela
                    target_date += timedelta(days=1)
                self.realization_date = target_date
            
            # Oblicz saldo (wartość netto zamówienia - zapłacono netto)
            if self.order_amount_net is not None and self.paid_amount_net is not None and self.delivery_cost is not None:
                # POPRAWKA: Logika zależna od typu ceny zamówienia
                price_type = (self.price_type or '').strip().lower()
            
                if price_type == 'netto':
                    # Zamówienia NETTO: klient płaci produkty netto + kuriera brutto
                    total_order_to_pay = float(self.order_amount_net) + float(self.delivery_cost)
                else:
                    # Zamówienia BRUTTO: porównujemy wszystko na netto
                    delivery_cost_net = float(self.delivery_cost) / 1.23 if self.delivery_cost else 0.0
                    total_order_to_pay = float(self.order_amount_net) + delivery_cost_net
        
                # Saldo = całkowita kwota do zapłaty - zapłacono netto
                self.balance_due = total_order_to_pay - float(self.paid_amount_net)
            
            # Automatyczne uzupełnianie województwa na podstawie kodu pocztowego
            self.auto_fill_delivery_state()
        
            # Oblicz produkcję i odbiór na podstawie statusu
            self.update_production_fields()
    
            # Normalizuj województwo
            self.normalize_delivery_state()
        
            # Ustaw domyślny product_type na 'klejonka' jeśli nie ma
            if not self.product_type:
                self.product_type = 'klejonka'

            # NOWE: Zachowaj avg_order_price_per_m3 jeśli już jest ustawione
            # (nie nadpisuj wartości ustawionej przez service.py)
            if not hasattr(self, 'avg_order_price_per_m3') or self.avg_order_price_per_m3 is None:
                # Dla pojedynczych rekordów ustaw na podstawie price_per_m3
                if hasattr(self, 'price_per_m3') and self.price_per_m3:
                    self.avg_order_price_per_m3 = self.price_per_m3
                else:
                    self.avg_order_price_per_m3 = 0.0

    def auto_fill_delivery_state(self):
        """
        Automatycznie uzupełnia województwo na podstawie kodu pocztowego
        Logika zgodna z wymaganiami:
        1. Jeśli województwo jest wpisane - puszczamy dalej
        2. Jeśli nie ma województwa, sprawdzamy kod pocztowy i uzupełniamy
        3. Jeśli nie ma województwa ani kodu pocztowego - puszczamy dalej
        """
        # KROK 1: Jeśli mamy województwo, nie robimy nic
        if self.delivery_state and self.delivery_state.strip():
            return
    
        # KROK 2: Jeśli nie ma województwa, ale mamy kod pocztowy - uzupełniamy
        if self.delivery_postcode and self.delivery_postcode.strip():
        
            auto_state = PostcodeToStateMapper.get_state_from_postcode(self.delivery_postcode)
            if auto_state:
                self.delivery_state = auto_state
                # Loguj automatyczne uzupełnienie (nie print, tylko strukturalny log)
                from modules.logging import get_structured_logger
                logger = get_structured_logger('reports.auto_fill')
                logger.info("Automatyczne uzupełnienie województwa",
                           record_id=getattr(self, 'id', 'NEW'),
                           postcode=self.delivery_postcode,
                           auto_filled_state=auto_state)
    
        # KROK 3: Jeśli nie ma województwa ani kodu pocztowego - nie robimy nic (puszczamy dalej)
    
    def normalize_delivery_state(self):
        """
        Normalizuje nazwę województwa do standardowego formatu
        """
        if not self.delivery_state:
            return
            
        state_lower = self.delivery_state.lower().strip()
        
        # Mapowanie województw
        states_map = {
            'dolnośląskie': 'Dolnośląskie',
            'dolnoslaskie': 'Dolnośląskie',
            'kujawsko-pomorskie': 'Kujawsko-Pomorskie',
            'kujawsko pomorskie': 'Kujawsko-Pomorskie',
            'lubelskie': 'Lubelskie',
            'lubuskie': 'Lubuskie',
            'łódzkie': 'Łódzkie',
            'lodzkie': 'Łódzkie',
            'małopolskie': 'Małopolskie',
            'malopolskie': 'Małopolskie',
            'mazowieckie': 'Mazowieckie',
            'opolskie': 'Opolskie',
            'podkarpackie': 'Podkarpackie',
            'podlaskie': 'Podlaskie',
            'pomorskie': 'Pomorskie',
            'śląskie': 'Śląskie',
            'slaskie': 'Śląskie',
            'świętokrzyskie': 'Świętokrzyskie',
            'swietokrzyskie': 'Świętokrzyskie',
            'warmińsko-mazurskie': 'Warmińsko-Mazurskie',
            'warminsko-mazurskie': 'Warmińsko-Mazurskie',
            'warminsko mazurskie': 'Warmińsko-Mazurskie',
            'wielkopolskie': 'Wielkopolskie',
            'zachodniopomorskie': 'Zachodniopomorskie'
        }
        
        # Sprawdź czy istnieje mapowanie
        normalized = states_map.get(state_lower)
        if normalized:
            self.delivery_state = normalized
        else:
            # Capitalize pierwszą literę jeśli nie ma mapowania
            self.delivery_state = self.delivery_state.strip().capitalize()
    
    def update_production_fields(self):
        """
        Aktualizuje pola produkcji na podstawie aktualnego statusu
        """
        if not self.current_status:
            return
    
        status_lower = self.current_status.lower()

        # Reset wartości
        self.production_volume = 0.0
        self.production_value_net = 0.0
        self.ready_pickup_volume = 0.0
        self.ready_pickup_value_net = 0.0

        # Jeśli status zawiera "w produkcji" LUB to "Nowe - opłacone"
        if 'w produkcji' in status_lower or 'nowe - opłacone' in status_lower:
            self.production_volume = float(self.total_volume or 0.0)
            self.production_value_net = float(self.value_net or 0.0)
    
        # NOWA LOGIKA: Statusy dla "Wyprodukowane" (zamiast tylko "Czeka na odbiór osobisty")
        # ID statusów: 138620, 138623, 105113, 105114, 149763, 149777, 138624, 149778, 149779
        elif (self.baselinker_status_id and
              self.baselinker_status_id in [138620, 138623, 105113, 105114, 149763, 149777, 138624, 149778, 149779]):
            self.ready_pickup_volume = float(self.total_volume or 0.0)
            self.ready_pickup_value_net = float(self.value_net or 0.0)
    
        # FALLBACK: Sprawdź także po nazwie statusu (dla ręcznych wpisów lub starych rekordów bez baselinker_status_id)
        elif any(status_name in status_lower for status_name in [
            'produkcja zakończona',           # 138620
            'zamówienie spakowane',           # 138623
            'paczka zgłoszona do wysyłki',    # 105113
            'wysłane - kurier',               # 105114
            'wysłane - transport woodpower',  # 149763
            'czeka na odbiór osobisty',       # 149777
            'dostarczona - kurier',           # 138624
            'dostarczona - transport woodpower', # 149778
            'odebrane'                        # 149779
        ]):
            self.ready_pickup_volume = float(self.total_volume or 0.0)
            self.ready_pickup_value_net = float(self.value_net or 0.0)
    
    def to_dict(self):
        """
        Konwertuje obiekt do słownika (dla JSON)
        """
        return {
            'id': self.id,
            'is_manual': self.is_manual,
            'date_created': self.date_created.strftime('%d-%m-%Y') if self.date_created else None,
            'total_m3': float(self.total_volume or 0),
            'order_amount_net': float(self.order_amount_net or 0),
            'baselinker_order_id': self.baselinker_order_id,
            'internal_order_number': self.internal_order_number,
            'customer_name': self.customer_name,
            'delivery_postcode': self.delivery_postcode,
            'delivery_city': self.delivery_city,
            'delivery_address': self.delivery_address,
            'delivery_state': self.delivery_state,
            'phone': self.phone,
            'caretaker': self.caretaker,
            'delivery_method': self.delivery_method,
            'order_source': self.order_source,
            'group_type': self.group_type,
            'product_type': self.product_type,
            'finish_state': self.finish_state,
            'wood_species': self.wood_species,
            'technology': self.technology,
            'wood_class': self.wood_class,
            'length_cm': float(self.length_cm or 0),
            'width_cm': float(self.width_cm or 0),
            'thickness_cm': float(self.thickness_cm or 0),
            'quantity': self.quantity,
            'price_gross': float(self.price_gross or 0),
            'price_net': float(self.price_net or 0),
            'value_gross': float(self.value_gross or 0),
            'value_net': float(self.value_net or 0),
            'volume_per_piece': float(self.volume_per_piece or 0),
            'total_volume': float(self.total_volume or 0),
            'total_surface_m2': float(self.total_surface_m2 or 0),
            'price_per_m3': float(self.price_per_m3 or 0),
            'avg_order_price_per_m3': float(self.avg_order_price_per_m3 or 0),
            'realization_date': self.realization_date.strftime('%d-%m-%Y') if self.realization_date else None,
            'current_status': self.current_status,
            'delivery_cost': float(self.delivery_cost or 0),
            'payment_method': self.payment_method,
            'paid_amount_net': float(self.paid_amount_net or 0),
            'balance_due': float(self.balance_due or 0),
            'production_volume': float(self.production_volume or 0),
            'production_value_net': float(self.production_value_net or 0),
            'pickup_ready': 1 if (self.baselinker_status_id in [105113, 149777, 138620]) else 0,  # NOWE: Obliczona wartość dla sortowania
            'ready_pickup_volume': float(self.ready_pickup_volume or 0),
            'ready_pickup_value_net': float(self.ready_pickup_value_net or 0)
        }

    def process_baselinker_amount(self, baselinker_amount: float, price_type_from_api: str) -> tuple:
        """
        Przetwarza kwotę z Baselinker na podstawie typu ceny
    
        Args:
            baselinker_amount: kwota z Baselinker
            price_type_from_api: typ ceny z extra_field_106169
        
        Returns:
            tuple: (processed_amount, price_type) - przetworzona kwota i typ
        """
        # Zapisz oryginalną kwotę
        self.original_amount_from_baselinker = baselinker_amount

        # Normalizuj wartość z API
        price_type = (price_type_from_api or '').strip().lower()

        if price_type == 'netto':
            # Kwota z Baselinker jest NETTO - zostaw bez zmian
            # System dalej sam przeliczy brutto gdy będzie potrzebował
            processed_amount = float(baselinker_amount)
            self.price_type = 'netto'
        elif price_type == 'brutto':
            # Kwota z Baselinker jest BRUTTO - zostaw bez zmian  
            processed_amount = float(baselinker_amount)
            self.price_type = 'brutto'
        else:
            # Puste lub nieznane - traktuj jako brutto (domyślnie)
            processed_amount = float(baselinker_amount)
            self.price_type = ''

        return processed_amount, self.price_type


class ReportsSyncLog(db.Model):
    """
    Log synchronizacji z Baselinker
    """
    __tablename__ = 'reports_sync_log'
    
    id = db.Column(db.Integer, primary_key=True)
    sync_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sync_type = db.Column(db.Enum('manual', 'auto', 'status_sync', name='sync_type_enum'), nullable=False)
    orders_processed = db.Column(db.Integer, default=0)
    orders_added = db.Column(db.Integer, default=0)
    orders_updated = db.Column(db.Integer, default=0)
    errors_count = db.Column(db.Integer, default=0)
    status = db.Column(db.Enum('success', 'error', 'partial', name='sync_status_enum'), nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    
    def __repr__(self):
        return f'<ReportsSyncLog {self.id}: {self.sync_date}, {self.status}>'