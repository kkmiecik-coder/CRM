# modules/calculator/models.py
"""
Modele modułu Calculator.
Jeden plik (kompatybilność wsteczna - importowany z wielu modułów).
"""

from extensions import db
from datetime import datetime
from sqlalchemy.dialects.mysql import DECIMAL
import secrets
import string
import sys
import uuid
from modules.users.models import User


# ============================================
# === KONFIGURACJA ===
# ============================================

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
    width_min = db.Column(DECIMAL(10, 2), nullable=False, default=0)
    width_max = db.Column(DECIMAL(10, 2), nullable=False, default=999.99)
    price_per_m3 = db.Column(DECIMAL(10, 2), nullable=False)

    def __repr__(self):
        return f"<Price id={self.id}, {self.species}, {self.wood_class}, {self.price_per_m3} PLN/m³>"

    def to_dict(self):
        return {
            'id': self.id,
            'species': self.species,
            'technology': self.technology,
            'wood_class': self.wood_class,
            'thickness_min': float(self.thickness_min) if self.thickness_min else 0,
            'thickness_max': float(self.thickness_max) if self.thickness_max else 0,
            'length_min': float(self.length_min) if self.length_min else 0,
            'length_max': float(self.length_max) if self.length_max else 0,
            'width_min': float(self.width_min) if self.width_min else 0,
            'width_max': float(self.width_max) if self.width_max else 0,
            'price_per_m3': float(self.price_per_m3) if self.price_per_m3 else 0,
        }


class Multiplier(db.Model):
    __tablename__ = 'multipliers'

    id = db.Column(db.Integer, primary_key=True)
    client_type = db.Column(db.String(100))
    multiplier = db.Column(db.Numeric(5, 2))

    def __repr__(self):
        return f"<Multiplier {self.client_type}: {self.multiplier}>"


class CalculatorSetting(db.Model):
    """Ustawienia kalkulatora (klucz-wartość)"""
    __tablename__ = 'calculator_settings'

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_value(cls, key, default=None):
        setting = cls.query.filter_by(setting_key=key).first()
        return setting.setting_value if setting else default

    @classmethod
    def set_value(cls, key, value, description=None):
        setting = cls.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = str(value)
            if description is not None:
                setting.description = description
        else:
            setting = cls(setting_key=key, setting_value=str(value), description=description)
            db.session.add(setting)
        db.session.commit()
        return setting

    def to_dict(self):
        return {
            'id': self.id,
            'setting_key': self.setting_key,
            'setting_value': self.setting_value,
            'description': self.description,
        }

    def __repr__(self):
        return f'<CalculatorSetting {self.setting_key}={self.setting_value}>'


# ============================================
# === WYKOŃCZENIA ===
# ============================================

class FinishingTypePrice(db.Model):
    __tablename__ = 'finishing_type_prices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price_netto = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'price_netto': float(self.price_netto) if self.price_netto else 0,
            'is_active': self.is_active,
        }

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


class FinishingOption(db.Model):
    """
    Hierarchiczne opcje wykończeń z dziedziczeniem cen.
    Struktura drzewka: Surowe / Lakierowane > Bezbarwne > Matowe / Olejowanie itd.
    """
    __tablename__ = 'finishing_options'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('finishing_options.id'), nullable=True, index=True)
    level = db.Column(db.Integer, nullable=False, default=0)

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), nullable=True)
    price_netto = db.Column(db.Numeric(10, 2), nullable=True)
    image_path = db.Column(db.String(255), nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = db.relationship(
        'FinishingOption',
        remote_side=[id],
        backref=db.backref('children', lazy='dynamic')
    )

    def get_effective_price(self):
        if self.price_netto is not None:
            return float(self.price_netto)
        if self.parent:
            return self.parent.get_effective_price()
        return 0.0

    def get_full_path(self):
        path = [self.name]
        current = self.parent
        while current:
            path.insert(0, current.name)
            current = current.parent
        return ' > '.join(path)

    def get_ancestors(self):
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    def get_root(self):
        current = self
        while current.parent:
            current = current.parent
        return current

    def get_code(self):
        if self.code:
            return self.code
        if self.parent:
            return self.parent.get_code()
        return None

    def to_dict(self, include_children=False, include_effective_price=True):
        result = {
            'id': self.id,
            'parent_id': self.parent_id,
            'level': self.level,
            'name': self.name,
            'code': self.code,
            'price_netto': float(self.price_netto) if self.price_netto is not None else None,
            'image_path': self.image_path,
            'is_active': self.is_active,
            'sort_order': self.sort_order,
            'full_path': self.get_full_path(),
        }

        if include_effective_price:
            result['effective_price_netto'] = self.get_effective_price()
            result['inherited_code'] = self.get_code()

        if include_children:
            active_children = [c for c in self.children if c.is_active]
            result['children'] = [
                child.to_dict(include_children=True, include_effective_price=include_effective_price)
                for child in sorted(active_children, key=lambda x: x.sort_order)
            ]

        return result

    @classmethod
    def get_tree(cls):
        roots = cls.query.filter_by(parent_id=None, is_active=True).order_by(cls.sort_order).all()
        return [root.to_dict(include_children=True) for root in roots]

    @classmethod
    def get_flat_list(cls, include_inactive=False):
        result = []

        def traverse(options, depth=0):
            for opt in sorted(options, key=lambda x: x.sort_order):
                if include_inactive or opt.is_active:
                    item = opt.to_dict()
                    item['depth'] = depth
                    item['indent'] = '—' * depth
                    result.append(item)

                    children = list(opt.children)
                    if include_inactive:
                        traverse(children, depth + 1)
                    else:
                        traverse([c for c in children if c.is_active], depth + 1)

        query = cls.query.filter_by(parent_id=None)
        if not include_inactive:
            query = query.filter_by(is_active=True)
        roots = query.order_by(cls.sort_order).all()
        traverse(roots)
        return result

    @classmethod
    def get_all_active_as_choices(cls):
        flat = cls.get_flat_list()
        return [(item['id'], f"{'  ' * item['depth']}{item['name']}") for item in flat]

    def __repr__(self):
        price_str = f'{self.price_netto} PLN/m²' if self.price_netto else 'dziedziczona'
        return f'<FinishingOption {self.name} (L{self.level}): {price_str}>'


# ============================================
# === KRAWĘDZIE ===
# ============================================

class EdgeOption(db.Model):
    """Typy obróbki krawędzi (ostre, fazowanie, zaokrąglenie)"""
    __tablename__ = 'edge_options'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(32), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    price_per_mb = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    corner_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    r_min = db.Column(db.Integer, nullable=True)
    r_max = db.Column(db.Integer, nullable=True)
    r_default = db.Column(db.Integer, nullable=True)

    chamfer_angles = db.Column(db.JSON, nullable=True)
    angle_default = db.Column(db.Integer, nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'price_per_mb': float(self.price_per_mb) if self.price_per_mb else 0,
            'corner_price': float(self.corner_price) if self.corner_price else 0,
            'r_min': self.r_min,
            'r_max': self.r_max,
            'r_default': self.r_default,
            'chamfer_angles': self.chamfer_angles,
            'angle_default': self.angle_default,
            'is_active': self.is_active,
        }

    def __repr__(self):
        return f'<EdgeOption {self.type}: {self.price_per_mb} PLN/mb>'


# ============================================
# === ŹRÓDŁA WYCEN ===
# ============================================

class QuoteSource(db.Model):
    """Źródła wycen - prosta lista źródeł zapytań."""
    __tablename__ = 'quote_sources'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    skip_contact_validation = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    allowed_roles = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_allowed_for_role(self, user_role, is_flexible_partner=False):
        if self.allowed_roles is None:
            return True
        effective_role = 'flexible_partner' if is_flexible_partner else user_role
        return effective_role in self.allowed_roles

    @classmethod
    def get_sources_for_user(cls, user_role, is_flexible_partner=False):
        sources = cls.query.filter_by(is_active=True).order_by(cls.sort_order).all()
        return [s for s in sources if s.is_allowed_for_role(user_role, is_flexible_partner)]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sort_order': self.sort_order,
            'skip_contact_validation': self.skip_contact_validation,
            'is_active': self.is_active,
            'allowed_roles': self.allowed_roles,
        }

    def __repr__(self):
        return f'<QuoteSource {self.id}: {self.name}>'


# ============================================
# === WYCENY ===
# ============================================

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

    # Strona klienta i rabaty
    public_token = db.Column(db.String(32), unique=True)
    client_comments = db.Column(db.Text)
    is_client_editable = db.Column(db.Boolean, default=True)

    # Akceptacja przez klienta
    acceptance_date = db.Column(db.DateTime)
    accepted_by_email = db.Column(db.String(255))

    # Akceptacja przez użytkownika wewnętrznego
    accepted_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Grupa cenowa
    quote_multiplier = db.Column(db.Numeric(5, 2))
    quote_client_type = db.Column(db.String(100))

    # Typ wyceny (brutto/netto)
    quote_type = db.Column(db.Enum('brutto', 'netto'), default='brutto')

    # Notatki
    notes = db.Column(db.Text)

    # Załącznik
    attachment_filename = db.Column(db.String(255), nullable=True)
    attachment_stored_name = db.Column(db.String(255), nullable=True)

    # UUID do edycji - bezpieczny identyfikator zamiast ID w URL
    edit_uuid = db.Column(db.String(36), unique=True, nullable=True, default=lambda: str(uuid.uuid4()))

    # ============================================
    # DOKUMENTY SPRZEDAŻY BASELINKER
    # ============================================

    # Faktura
    baselinker_invoice_id = db.Column(db.Integer, nullable=True)
    baselinker_invoice_number = db.Column(db.String(50), nullable=True)
    baselinker_invoice_file = db.Column(db.Text, nullable=True)
    baselinker_invoice_fetched_at = db.Column(db.DateTime, nullable=True)

    # Korekta faktury
    baselinker_correction_invoice_id = db.Column(db.Integer, nullable=True)
    baselinker_correction_invoice_number = db.Column(db.String(50), nullable=True)
    baselinker_correction_invoice_file = db.Column(db.Text, nullable=True)
    baselinker_correction_last_check = db.Column(db.DateTime, nullable=True)

    # E-paragon
    baselinker_receipt_url = db.Column(db.String(500), nullable=True)
    baselinker_receipt_last_check = db.Column(db.DateTime, nullable=True)

    # Strona informacyjna
    baselinker_order_page = db.Column(db.String(255), nullable=True)

    # Relacje
    user = db.relationship('User', foreign_keys=[user_id], backref='quotes')
    client = db.relationship('Client', backref='quotes')
    quote_status = db.relationship('QuoteStatus', backref='quotes')
    accepted_by_user = db.relationship('User', foreign_keys=[accepted_by_user_id], backref='accepted_quotes')
    items = db.relationship('QuoteItem', back_populates='quote', lazy='dynamic')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.public_token:
            self.public_token = self.generate_public_token()
        if not self.edit_uuid:
            self.edit_uuid = str(uuid.uuid4())

    @staticmethod
    def generate_public_token():
        characters = string.ascii_uppercase + string.digits
        while True:
            token = ''.join(secrets.choice(characters) for _ in range(32))
            if not Quote.query.filter_by(public_token=token).first():
                return token

    def get_public_url(self):
        if not self.public_token:
            self.public_token = self.generate_public_token()
            db.session.commit()
        return f"/quotes/c/{self.public_token}"

    def disable_client_editing(self):
        self.is_client_editable = False

    def get_selected_items(self):
        return [item for item in self.items if item.is_selected]

    def get_total_original_price_netto(self):
        selected_items = self.get_selected_items()
        return sum(item.get_total_original_price_netto() for item in selected_items)

    def get_total_original_price_brutto(self):
        selected_items = self.get_selected_items()
        return sum(item.get_total_original_price_brutto() for item in selected_items)

    def get_total_current_price_netto(self):
        selected_items = self.get_selected_items()
        return sum(item.get_total_price_netto() for item in selected_items)

    def get_total_current_price_brutto(self):
        selected_items = self.get_selected_items()
        return sum(item.get_total_price_brutto() for item in selected_items)

    def get_total_discount_amount_netto(self):
        return self.get_total_original_price_netto() - self.get_total_current_price_netto()

    def get_total_discount_amount_brutto(self):
        return self.get_total_original_price_brutto() - self.get_total_current_price_brutto()

    def is_eligible_for_order(self):
        if self.status_id != 3:
            return False
        if self.base_linker_order_id:
            return False
        selected_items = [item for item in self.items if item.is_selected]
        if not selected_items:
            return False
        if not self.client:
            return False
        if not self.client.email and not self.client.phone:
            return False
        return True

    def apply_total_discount(self, discount_percentage, reason_id=None):
        all_items = [item for item in self.items]
        print(f"[apply_total_discount] Znaleziono {len(all_items)} pozycji dla quote_id={self.id}", file=sys.stderr)

        affected_count = 0
        for item in all_items:
            print(f"[apply_total_discount] Przetwarzam item ID={item.id}, variant={item.variant_code}", file=sys.stderr)
            item.apply_discount(discount_percentage, reason_id)
            affected_count += 1

        print(f"[apply_total_discount] Zaktualizowano {affected_count} pozycji", file=sys.stderr)
        return affected_count

    @property
    def finishing_details(self):
        from extensions import db
        QuoteItemDetailsModel = db.Model.registry._class_registry.get('QuoteItemDetails')
        if QuoteItemDetailsModel:
            return db.session.query(QuoteItemDetailsModel).filter_by(quote_id=self.id)
        return db.session.query(db.Model).filter(False)

    # Helper'y dokumentów sprzedaży
    def has_invoice(self):
        return self.baselinker_invoice_number is not None

    def has_correction(self):
        return self.baselinker_correction_invoice_number is not None

    def has_receipt(self):
        return self.baselinker_receipt_url is not None

    def should_check_correction(self):
        if not self.baselinker_correction_last_check:
            return True
        from datetime import timedelta
        time_since_check = datetime.utcnow() - self.baselinker_correction_last_check
        return time_since_check > timedelta(hours=1)

    def should_check_receipt(self):
        if not self.baselinker_receipt_last_check:
            return True
        from datetime import timedelta
        time_since_check = datetime.utcnow() - self.baselinker_receipt_last_check
        return time_since_check > timedelta(hours=1)

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
    real_volume_m3 = db.Column(db.Numeric(10, 6))
    price_per_m3 = db.Column(db.Numeric(10, 2))
    multiplier = db.Column(db.Numeric(5, 2))
    is_selected = db.Column(db.Boolean, default=False)

    # Ceny jednostkowe
    price_netto = db.Column(db.Numeric(10, 2))
    price_brutto = db.Column(db.Numeric(10, 2))

    # Rabaty (ceny jednostkowe)
    original_price_netto = db.Column(db.Numeric(10, 2))
    original_price_brutto = db.Column(db.Numeric(10, 2))
    discount_percentage = db.Column(db.Numeric(5, 2), default=0)
    show_on_client_page = db.Column(db.Boolean, default=True)
    discount_reason_id = db.Column(db.Integer, db.ForeignKey('discount_reasons.id'))

    # Relacje
    quote = db.relationship('Quote', back_populates='items')
    discount_reason = db.relationship('DiscountReason', backref='quote_items')

    def get_quantity(self):
        try:
            from extensions import db
            result = db.session.execute(
                db.text("SELECT quantity FROM quote_items_details WHERE quote_id = :quote_id AND product_index = :product_index"),
                {'quote_id': self.quote_id, 'product_index': self.product_index}
            ).fetchone()
            if result and result[0]:
                return int(result[0])
            else:
                return 1
        except Exception as e:
            print(f"[QuoteItem.get_quantity] Error: {str(e)}", file=sys.stderr)
            return 1

    def get_total_price_netto(self):
        quantity = self.get_quantity()
        return float(self.price_netto or 0) * quantity

    def get_total_price_brutto(self):
        quantity = self.get_quantity()
        return float(self.price_brutto or 0) * quantity

    def get_total_original_price_netto(self):
        quantity = self.get_quantity()
        original = self.original_price_netto or self.price_netto or 0
        return float(original) * quantity

    def get_total_original_price_brutto(self):
        quantity = self.get_quantity()
        original = self.original_price_brutto or self.price_brutto or 0
        return float(original) * quantity

    def apply_discount(self, discount_percentage, reason_id=None):
        if self.original_price_netto is None:
            self.original_price_netto = self.price_netto
            self.original_price_brutto = self.price_brutto
        self.discount_percentage = discount_percentage
        self.discount_reason_id = reason_id
        discount_multiplier = 1 - (discount_percentage / 100)
        self.price_netto = float(self.original_price_netto) * discount_multiplier
        self.price_brutto = float(self.original_price_brutto) * discount_multiplier
        return self

    def get_discount_amount_netto(self):
        if self.original_price_netto and self.price_netto:
            unit_discount = float(self.original_price_netto) - float(self.price_netto)
            return unit_discount * self.get_quantity()
        return 0

    def get_discount_amount_brutto(self):
        if self.original_price_brutto and self.price_brutto:
            unit_discount = float(self.original_price_brutto) - float(self.price_brutto)
            return unit_discount * self.get_quantity()
        return 0

    def has_discount(self):
        return self.discount_percentage != 0

    def reset_discount(self):
        if self.original_price_netto is not None:
            self.price_netto = self.original_price_netto
            self.price_brutto = self.original_price_brutto
            self.discount_percentage = 0
            self.discount_reason_id = None

    def to_dict(self):
        quantity = self.get_quantity()
        return {
            'id': self.id,
            'product_index': self.product_index,
            'variant_code': self.variant_code,
            'length_cm': float(self.length_cm) if self.length_cm else None,
            'width_cm': float(self.width_cm) if self.width_cm else None,
            'thickness_cm': float(self.thickness_cm) if self.thickness_cm else None,
            'volume_m3': float(self.volume_m3) if self.volume_m3 else None,
            'real_volume_m3': float(self.real_volume_m3) if self.real_volume_m3 else None,
            'price_per_m3': float(self.price_per_m3) if self.price_per_m3 else None,
            'multiplier': float(self.multiplier) if self.multiplier else None,
            'is_selected': self.is_selected,
            'show_on_client_page': self.show_on_client_page,
            # Wartości całkowite (kompatybilność)
            'final_price_netto': self.get_total_price_netto(),
            'final_price_brutto': self.get_total_price_brutto(),
            'original_price_netto': self.get_total_original_price_netto() if self.original_price_netto else None,
            'original_price_brutto': self.get_total_original_price_brutto() if self.original_price_brutto else None,
            # Ceny jednostkowe
            'unit_price_netto': float(self.price_netto) if self.price_netto else None,
            'unit_price_brutto': float(self.price_brutto) if self.price_brutto else None,
            'quantity': quantity,
            'discount_percentage': float(self.discount_percentage) if self.discount_percentage else 0,
            'discount_reason_id': self.discount_reason_id,
            'has_discount': self.has_discount(),
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

    # Obróbka krawędzi
    edges_config = db.Column(db.JSON, nullable=True)
    edges_type = db.Column(db.String(32), nullable=True)
    edges_r_value = db.Column(db.Integer, nullable=True)
    edges_angle_value = db.Column(db.Integer, nullable=True)
    edges_price_netto = db.Column(db.Numeric(10, 2), default=0)
    edges_price_brutto = db.Column(db.Numeric(10, 2), default=0)
    edges_svg = db.Column(db.Text, nullable=True)
    baselinker_order_product_id = db.Column(db.Integer, nullable=True,
                                            comment='ID produktu z BaseLinker getOrders — do matchowania z ProductionItem')

    # Kształt produktu
    shape = db.Column(db.String(50), default='rectangular')
    round_surcharge_netto = db.Column(db.Numeric(10, 2), default=0)
    round_surcharge_brutto = db.Column(db.Numeric(10, 2), default=0)

    shape_data = db.Column(db.Text, nullable=True)  # JSON: params, vertices, real_area_cm2, bbox
    shape_svg = db.Column(db.Text, nullable=True)    # SVG string for display in quotes/PDF
    lamella_direction = db.Column(db.Integer, nullable=True)  # 0, 45, 90, 135 — tylko kszalty nieregularne

    # Docięcie do wymiaru (czy klient otrzymuje produkt docięty do wymiaru z kalkulatora)
    cut_to_size = db.Column(db.Boolean, nullable=False, default=True, server_default='1')

    __table_args__ = (
        db.UniqueConstraint('quote_id', 'product_index', name='uq_quote_product'),
    )

    def to_dict(self):
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
            'quantity': self.quantity,
            'edges_config': self.edges_config,
            'edges_type': self.edges_type,
            'edges_r_value': self.edges_r_value,
            'edges_angle_value': self.edges_angle_value,
            'edges_price_netto': float(self.edges_price_netto) if self.edges_price_netto else 0.0,
            'edges_price_brutto': float(self.edges_price_brutto) if self.edges_price_brutto else 0.0,
            'edges_svg': self.edges_svg,
            'shape': self.shape or 'rectangular',
            'round_surcharge_netto': float(self.round_surcharge_netto) if self.round_surcharge_netto else 0.0,
            'round_surcharge_brutto': float(self.round_surcharge_brutto) if self.round_surcharge_brutto else 0.0,
            'shape_data': self.shape_data,
            'shape_svg': self.shape_svg,
            'cut_to_size': bool(self.cut_to_size),
            'lamella_direction': self.lamella_direction,
        }

    def __repr__(self):
        return f"<QuoteItemDetails Quote:{self.quote_id} Produkt:{self.product_index} Qty:{self.quantity}>"


# ============================================
# === DRAFTY KALKULATORA ===
# ============================================

class CalculatorDraft(db.Model):
    __tablename__ = 'calculator_drafts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    draft_data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', name='uq_calculator_draft_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'draft_data': self.draft_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<CalculatorDraft user_id={self.user_id}>'
