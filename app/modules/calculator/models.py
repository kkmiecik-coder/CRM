# modules/calculator/models.py

from extensions import db
from datetime import datetime
from sqlalchemy.dialects.mysql import DECIMAL
import secrets
import string
import sys


class Multiplier(db.Model):
    __tablename__ = 'multipliers'
    
    id = db.Column(db.Integer, primary_key=True)
    client_type = db.Column(db.String(100))
    multiplier = db.Column(db.Numeric(5, 2))

    def __repr__(self):
        return f"<Multiplier {self.client_type}: {self.multiplier}>"

class Quote(db.Model):
    __tablename__ = 'quotes'
    
    id = db.Column(db.Integer, primary_key=True)
    quote_number = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'))
    status_id = db.Column(db.Integer, db.ForeignKey('quote_statuses.id'))
    base_linker_order_id = db.Column(db.String(100))
    source = db.Column(db.String(100))
    total_price = db.Column(db.Numeric(10, 2))
    courier_name = db.Column(db.String(100))
    shipping_cost_netto = db.Column(db.Numeric(10, 2))
    shipping_cost_brutto = db.Column(db.Numeric(10, 2))
    
    # POLA dla strony klienta i rabatów
    public_token = db.Column(db.String(32), unique=True)
    client_comments = db.Column(db.Text)
    is_client_editable = db.Column(db.Boolean, default=True)
    
    # POLA dla obsługi akceptacji przez klienta
    acceptance_date = db.Column(db.DateTime)
    accepted_by_email = db.Column(db.String(255))
    
    # NOWE POLE - akceptacja przez użytkownika wewnętrznego
    accepted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # POLE: Mnożnik (grupa cenowa) przypisany do wyceny
    quote_multiplier = db.Column(db.Numeric(5, 2))
    quote_client_type = db.Column(db.String(100))  # Nazwa grupy cenowej
    
    # POPRAWIONE RELACJE - bez konfliktów
    user = db.relationship('User', foreign_keys=[user_id], backref='quotes')
    client = db.relationship('Client', backref='quotes')
    quote_status = db.relationship('QuoteStatus', backref='quotes')
    accepted_by_user = db.relationship('User', foreign_keys=[accepted_by_user_id], backref='accepted_quotes')
    
    # POPRAWIONA RELACJA - używamy back_populates zamiast backref
    items = db.relationship('QuoteItem', back_populates='quote', lazy='dynamic')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.public_token:
            self.public_token = self.generate_public_token()

    @staticmethod
    def generate_public_token():
        """Generuje unikalny 32-znakowy token"""
        characters = string.ascii_uppercase + string.digits
        while True:
            token = ''.join(secrets.choice(characters) for _ in range(32))
            # Sprawdź czy token już istnieje
            if not Quote.query.filter_by(public_token=token).first():
                return token

    def get_public_url(self):
        """Generuje publiczny URL dla klienta"""
        if not self.public_token:
            self.public_token = self.generate_public_token()
            # Zapisz token do bazy danych
            db.session.commit()
    
        return f"/quotes/c/{self.public_token}"

    def disable_client_editing(self):
        """Wyłącza możliwość edycji przez klienta (np. po akceptacji)"""
        self.is_client_editable = False

    def get_selected_items(self):
        """Zwraca tylko wybrane pozycje wyceny"""
        return [item for item in self.items if item.is_selected]

    def get_total_original_price_netto(self):
        """Zwraca oryginalną cenę netto wszystkich wybranych pozycji (wartości całkowite)"""
        selected_items = self.get_selected_items()
        return sum(item.get_total_original_price_netto() for item in selected_items)

    def get_total_original_price_brutto(self):
        """Zwraca oryginalną cenę brutto wszystkich wybranych pozycji (wartości całkowite)"""
        selected_items = self.get_selected_items()
        return sum(item.get_total_original_price_brutto() for item in selected_items)

    def get_total_current_price_netto(self):
        """Zwraca aktualną cenę netto wszystkich wybranych pozycji (wartości całkowite)"""
        selected_items = self.get_selected_items()
        return sum(item.get_total_price_netto() for item in selected_items)

    def get_total_current_price_brutto(self):
        """Zwraca aktualną cenę brutto wszystkich wybranych pozycji (wartości całkowite)"""
        selected_items = self.get_selected_items()
        return sum(item.get_total_price_brutto() for item in selected_items)

    def get_total_discount_amount_netto(self):
        """Zwraca łączną kwotę rabatu netto (wartości całkowite)"""
        return self.get_total_original_price_netto() - self.get_total_current_price_netto()

    def get_total_discount_amount_brutto(self):
        """Zwraca łączną kwotę rabatu brutto (wartości całkowite)"""
        return self.get_total_original_price_brutto() - self.get_total_current_price_brutto()

    def is_eligible_for_order(self):
        """
        Sprawdza czy wycena może być złożona jako zamówienie w Baselinker
    
        Returns:
            bool: True jeśli wycena może zostać złożona jako zamówienie
        """
        # Wycena musi być zaakceptowana przez klienta (status ID 3 = "Zaakceptowane")
        if self.status_id != 3:
            return False
    
        # Wycena nie może mieć już złożonego zamówienia
        if self.base_linker_order_id:
            return False
    
        # Wycena musi mieć co najmniej jeden wybrany element
        selected_items = [item for item in self.items if item.is_selected]
        if not selected_items:
            return False
    
        # Wycena musi mieć klienta z podstawowymi danymi
        if not self.client:
            return False
    
        if not self.client.email and not self.client.phone:
            return False
    
        return True

    def apply_total_discount(self, discount_percentage, reason_id=None):
        """Zastosowuje rabat do wszystkich wariantów w wycenie"""
        # POPRAWKA: Użyj self.items zamiast query
        all_items = [item for item in self.items]

        print(f"[apply_total_discount] Znaleziono {len(all_items)} wszystkich pozycji dla quote_id={self.id}", file=sys.stderr)

        affected_count = 0

        for item in all_items:
            print(f"[apply_total_discount] Przetwarzam item ID={item.id}, variant={item.variant_code}", file=sys.stderr)
            item.apply_discount(discount_percentage, reason_id)
            affected_count += 1

        print(f"[apply_total_discount] Zaktualizowano {affected_count} pozycji", file=sys.stderr)
        return affected_count

    @property
    def finishing_details(self):
        """Zwraca szczegóły wykończenia dla wyceny"""
        # POPRAWKA: Importuj z właściwego miejsca
        from extensions import db
        # Dynamiczny import aby uniknąć circular imports
        QuoteItemDetails = db.Model.registry._class_registry.get('QuoteItemDetails')
        if QuoteItemDetails:
            return db.session.query(QuoteItemDetails).filter_by(quote_id=self.id)
        return db.session.query(db.Model).filter(False)  # Pusty query jako fallback

    def __repr__(self):
        return f"<Quote {self.quote_number}>"

class QuoteItem(db.Model):
    __tablename__ = 'quote_items'
    
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'))
    product_index = db.Column(db.Integer)
    variant_code = db.Column(db.String(50))
    length_cm = db.Column(db.Numeric(10, 2))
    width_cm = db.Column(db.Numeric(10, 2))
    thickness_cm = db.Column(db.Numeric(10, 2))
    volume_m3 = db.Column(db.Numeric(10, 6))
    price_per_m3 = db.Column(db.Numeric(10, 2))
    multiplier = db.Column(db.Numeric(5, 2))
    is_selected = db.Column(db.Boolean, default=False)
    
    # ZMIENIONE NAZWY KOLUMN: final_price_* -> price_* (ceny jednostkowe!)
    price_netto = db.Column(db.Numeric(10, 2))      # Cena za 1 sztukę netto
    price_brutto = db.Column(db.Numeric(10, 2))     # Cena za 1 sztukę brutto
    
    # POLA dla rabatów (nadal ceny jednostkowe)
    original_price_netto = db.Column(db.Numeric(10, 2))   # Oryginalna cena za 1 sztukę netto
    original_price_brutto = db.Column(db.Numeric(10, 2))  # Oryginalna cena za 1 sztukę brutto
    discount_percentage = db.Column(db.Numeric(5, 2), default=0)
    show_on_client_page = db.Column(db.Boolean, default=True)
    discount_reason_id = db.Column(db.Integer, db.ForeignKey('discount_reasons.id'))
    
    # POPRAWIONA RELACJA - używamy back_populates zamiast backref
    quote = db.relationship('Quote', back_populates='items')
    discount_reason = db.relationship('DiscountReason', backref='quote_items')

    # ========== NOWE METODY POMOCNICZE ==========
    
    def get_quantity(self):
        """
        Pobiera ilość dla tego wariantu z QuoteItemDetails lub zwraca 1 jako domyślną
        """
        try:
            # Importuj dynamicznie aby uniknąć circular imports
            from extensions import db
        
            # Znajdź odpowiadający QuoteItemDetails
            result = db.session.execute(
                db.text("SELECT quantity FROM quote_items_details WHERE quote_id = :quote_id AND product_index = :product_index"),
                {'quote_id': self.quote_id, 'product_index': self.product_index}
            ).fetchone()
        
            if result and result[0]:
                return int(result[0])
            else:
                return 1
            
        except Exception as e:
            print(f"[QuoteItem.get_quantity] Error getting quantity: {str(e)}", file=sys.stderr)
            return 1
    
    def get_total_price_netto(self):
        """Zwraca wartość całkowitą netto (cena jednostkowa × ilość)"""
        quantity = self.get_quantity()
        return float(self.price_netto or 0) * quantity
    
    def get_total_price_brutto(self):
        """Zwraca wartość całkowitą brutto (cena jednostkowa × ilość)"""
        quantity = self.get_quantity()
        return float(self.price_brutto or 0) * quantity
    
    def get_total_original_price_netto(self):
        """Zwraca oryginalną wartość całkowitą netto"""
        quantity = self.get_quantity()
        original = self.original_price_netto or self.price_netto or 0
        return float(original) * quantity
    
    def get_total_original_price_brutto(self):
        """Zwraca oryginalną wartość całkowitą brutto"""
        quantity = self.get_quantity()
        original = self.original_price_brutto or self.price_brutto or 0
        return float(original) * quantity

    # ========== ZAKTUALIZOWANE METODY RABATÓW ==========
    
    def apply_discount(self, discount_percentage, reason_id=None):
        """Zastosowuje rabat do pozycji (na cenach jednostkowych)"""
        # Jeśli nie ma ceny oryginalnej, ustaw obecną jako oryginalną
        if self.original_price_netto is None:
            self.original_price_netto = self.price_netto
            self.original_price_brutto = self.price_brutto
        
        self.discount_percentage = discount_percentage
        self.discount_reason_id = reason_id
        
        # Oblicz nowe ceny jednostkowe
        discount_multiplier = 1 - (discount_percentage / 100)
        self.price_netto = float(self.original_price_netto) * discount_multiplier
        self.price_brutto = float(self.original_price_brutto) * discount_multiplier
        
        return self

    def get_discount_amount_netto(self):
        """Zwraca kwotę rabatu netto (całkowita, nie jednostkowa)"""
        if self.original_price_netto and self.price_netto:
            unit_discount = float(self.original_price_netto) - float(self.price_netto)
            return unit_discount * self.get_quantity()
        return 0

    def get_discount_amount_brutto(self):
        """Zwraca kwotę rabatu brutto (całkowita, nie jednostkowa)"""
        if self.original_price_brutto and self.price_brutto:
            unit_discount = float(self.original_price_brutto) - float(self.price_brutto)
            return unit_discount * self.get_quantity()
        return 0

    def has_discount(self):
        """Sprawdza czy pozycja ma zastosowany rabat"""
        return self.discount_percentage != 0

    def reset_discount(self):
        """Resetuje rabat do wartości oryginalnych"""
        if self.original_price_netto is not None:
            self.price_netto = self.original_price_netto
            self.price_brutto = self.original_price_brutto
            self.discount_percentage = 0
            self.discount_reason_id = None

    # ========== ZAKTUALIZOWANA METODA to_dict ==========
    
    def to_dict(self):
        """Konwertuje do słownika dla API (z wartościami całkowitymi dla kompatybilności)"""
        quantity = self.get_quantity()
        
        return {
            'id': self.id,
            'product_index': self.product_index,
            'variant_code': self.variant_code,
            'length_cm': float(self.length_cm) if self.length_cm else None,
            'width_cm': float(self.width_cm) if self.width_cm else None,
            'thickness_cm': float(self.thickness_cm) if self.thickness_cm else None,
            'volume_m3': float(self.volume_m3) if self.volume_m3 else None,
            'price_per_m3': float(self.price_per_m3) if self.price_per_m3 else None,
            'multiplier': float(self.multiplier) if self.multiplier else None,
            'is_selected': self.is_selected,
            'show_on_client_page': self.show_on_client_page,
            
            # KOMPATYBILNOŚĆ: Zwracamy wartości całkowite z nazwami jak wcześniej
            'final_price_netto': self.get_total_price_netto(),
            'final_price_brutto': self.get_total_price_brutto(),
            'original_price_netto': self.get_total_original_price_netto() if self.original_price_netto else None,
            'original_price_brutto': self.get_total_original_price_brutto() if self.original_price_brutto else None,
            
            # NOWE: Dodajemy też ceny jednostkowe
            'unit_price_netto': float(self.price_netto) if self.price_netto else None,
            'unit_price_brutto': float(self.price_brutto) if self.price_brutto else None,
            'quantity': quantity,
            
            'discount_percentage': float(self.discount_percentage) if self.discount_percentage else 0,
            'discount_reason_id': self.discount_reason_id,
            'has_discount': self.has_discount()
        }

    def __repr__(self):
        return f"<QuoteItem {self.id} - Quote {self.quote_id} - Unit: {self.price_brutto} PLN>"


class QuoteItemDetails(db.Model):
    __tablename__ = 'quote_items_details'

    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'))
    product_index = db.Column(db.Integer)
    finishing_type = db.Column(db.String(100))
    finishing_variant = db.Column(db.String(100))
    finishing_color = db.Column(db.String(100))
    finishing_gloss_level = db.Column(db.String(50))
    finishing_price_netto = db.Column(db.Numeric(10, 2))
    finishing_price_brutto = db.Column(db.Numeric(10, 2))
    quantity = db.Column(db.Integer, default=1, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('quote_id', 'product_index', name='uq_quote_product'),
    )

    def to_dict(self):
        """Konwertuje obiekt na słownik"""
        return {
            'id': self.id,
            'quote_id': self.quote_id,
            'product_index': self.product_index,
            'finishing_type': self.finishing_type,
            'finishing_variant': self.finishing_variant,
            'finishing_color': self.finishing_color,
            'finishing_gloss_level': self.finishing_gloss_level,
            'finishing_price_netto': float(self.finishing_price_netto) if self.finishing_price_netto else 0.0,
            'finishing_price_brutto': float(self.finishing_price_brutto) if self.finishing_price_brutto else 0.0,
            'quantity': self.quantity
        }

    def __repr__(self):
        return f"<QuoteItemDetails Quote:{self.quote_id} Produkt:{self.product_index} Qty:{self.quantity}>"

class QuoteCounter(db.Model):
    __tablename__ = 'quote_counters'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    current_number = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<QuoteCounter {self.month}/{self.year}: {self.current_number}>"

class QuoteLog(db.Model):
    __tablename__ = 'quote_logs'
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    change_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<QuoteLog Quote:{self.quote_id} ChangedBy:{self.user_id} at {self.change_time}>"
    
class Price(db.Model):
    __tablename__ = 'prices'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    species = db.Column(db.String(50), nullable=False)
    technology = db.Column(db.String(50), nullable=False)
    wood_class = db.Column(db.String(10), nullable=False)
    thickness_min = db.Column(DECIMAL(4, 2), nullable=False)
    thickness_max = db.Column(DECIMAL(4, 2), nullable=False)
    length_min = db.Column(DECIMAL(10, 2), nullable=False)
    length_max = db.Column(DECIMAL(10, 2), nullable=False)
    price_per_m3 = db.Column(DECIMAL(10, 2), nullable=False)

    def __repr__(self):
        return f"<Price id={self.id}, {self.species}, {self.wood_class}, {self.price_per_m3} PLN/m³>"

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin  # DODANE
from extensions import db

# ... inne importy i modele ...

class User(UserMixin, db.Model):  # DODANE UserMixin
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    reset_token = db.Column(db.String(255))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    avatar_path = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    multiplier_id = db.Column(db.Integer, db.ForeignKey('multipliers.id'))
    
    # Relacja: User → Multiplier
    multiplier = db.relationship('Multiplier', backref='users')

    # ============================================================================
    # METODY WYMAGANE PRZEZ FLASK-LOGIN (DODANE)
    # ============================================================================
    
    def is_authenticated(self):
        """Zwraca True jeśli użytkownik jest zalogowany"""
        return True
    
    def is_active(self):
        """Zwraca True jeśli konto jest aktywne"""
        return self.active  # Używa istniejącego pola boolean
    
    def is_anonymous(self):
        """Zwraca True dla użytkowników anonimowych"""
        return False
    
    def get_id(self):
        """Zwraca unikalny identyfikator użytkownika jako string"""
        return str(self.id)
    
    # ============================================================================
    # DODATKOWE METODY POMOCNICZE
    # ============================================================================
    
    def get_full_name(self):
        """Zwraca pełne imię i nazwisko lub email"""
        if self.first_name or self.last_name:
            return f"{self.first_name or ''} {self.last_name or ''}".strip()
        return self.email
    
    def is_admin(self):
        """Sprawdza czy użytkownik ma rolę admin"""
        return self.role and self.role.lower() in ['admin', 'administrator']
    
    def can_access_production(self):
        """Sprawdza czy użytkownik może dostać się do modułu produkcji"""
        return self.is_active() and self.role in ['admin', 'user', 'production']

    def __repr__(self):
        return f"<User {self.email}>"

class Invitation(db.Model):
    __tablename__ = 'invitations'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    token = db.Column(db.String(256), nullable=False, unique=True)
    active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20))
    multiplier_id = db.Column(db.Integer, db.ForeignKey('multipliers.id'), nullable=True)
    multiplier = db.relationship('Multiplier')

    def __repr__(self):
        return f'<Invitation {self.email} - {"active" if self.active else "inactive"}>'

class FinishingTypePrice(db.Model):
    __tablename__ = 'finishing_type_prices'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # np. "Surowe", "Lakierowane bezbarwne", "Lakierowane barwne", "Olejowanie"
    price_netto = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # Cena netto za m²
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Czy aktywne

    def __repr__(self):
        return f'<FinishingTypePrice {self.name}: {self.price_netto} PLN/m²>'

class FinishingColor(db.Model):
    __tablename__ = 'finishing_colors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image_path = db.Column(db.String(255), nullable=True)
    is_available = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<FinishingColor {self.name}>'