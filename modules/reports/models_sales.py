# -*- coding: utf-8 -*-
"""Modele Analizy sprzedażowej: klient -> zamówienie -> pozycja.

DLACZEGO TRZY TABELE, A NIE JEDNA PŁASKA
========================================
Poprzednik (`baselinker_reports_orders`) trzyma 1 wiersz = 1 POZYCJA, z polami
poziomu zamówienia powielonymi w każdym wierszu. Zmierzone na produkcji
21.09.2026: `SUM(balance_due)` po wierszach daje 5 618 320 zł, a to samo saldo
liczone raz na zamówienie — 741 279 zł. Siedmiokrotne zawyżenie, i ani jeden
test tego nie łapał, bo testów nie było wcale.

Rozdzielenie poziomów usuwa całą klasę błędów zamiast ją obchodzić: nie da się
już pomylić `SUM` z `MAX`, bo wartość istnieje tylko w jednym miejscu.
Precedens w tym repo: prod_items -> prod_orders/prod_products (05.2026).
"""

from datetime import datetime

from extensions import db


class SalesClient(db.Model):
    """Kupujący. Budowany z BaseLinkera przy synchronizacji, deduplikowany."""
    __tablename__ = 'sales_clients'

    id = db.Column(db.Integer, primary_key=True)
    # Opcjonalne dowiązanie do rejestru wycenianych (dawne `clients`).
    # Nullable, bo tylko 23,2% kupujących miało wcześniej wycenę.
    lead_id = db.Column(db.Integer, nullable=True, index=True)

    # Trzy klucze deduplikacji, w kolejności pewności. Nazwa NIGDY nie jest
    # kluczem — w Excelu 49 duplikatów bierze się z samej wielkości liter.
    email_norm = db.Column(db.String(150), nullable=True, index=True)
    nip_norm = db.Column(db.String(20), nullable=True, index=True)
    phone_norm = db.Column(db.String(20), nullable=True, index=True)

    display_name = db.Column(db.String(200), nullable=True)
    client_kind = db.Column(db.Enum('detal', 'b2b', name='sales_client_kind'), nullable=True)
    needs_merge = db.Column(db.Boolean, default=False, nullable=False,
                            comment='Brak wszystkich trzech kluczy — do ręcznego scalenia')

    first_order_at = db.Column(db.Date, nullable=True)
    last_order_at = db.Column(db.Date, nullable=True)
    orders_count = db.Column(db.Integer, default=0, nullable=False)
    lifetime_net = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)


class SalesOrder(db.Model):
    """Jeden wiersz na zamówienie. Wszystko, co dotyczy całego zamówienia."""
    __tablename__ = 'sales_orders'

    id = db.Column(db.Integer, primary_key=True)
    baselinker_order_id = db.Column(db.Integer, nullable=True, unique=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('sales_clients.id'), nullable=True, index=True)

    date_created = db.Column(db.Date, nullable=False, index=True)
    internal_order_number = db.Column(db.String(50), nullable=True)

    customer_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    delivery_address = db.Column(db.String(250), nullable=True)
    delivery_postcode = db.Column(db.String(20), nullable=True)
    delivery_city = db.Column(db.String(100), nullable=True)
    delivery_state = db.Column(db.String(50), nullable=True, index=True)

    caretaker = db.Column(db.String(100), nullable=True, index=True)
    order_source = db.Column(db.String(50), nullable=True, index=True)
    order_source_id = db.Column(db.Integer, nullable=True)
    # Segmentacja z Excela: Detal / Nowy B2B / Stały B2B / PH / nazwa partnera / Dębuś.
    # BaseLinker nie pozwala zmienić źródła zamówienia, więc to pole jest nasze.
    client_origin = db.Column(db.String(50), nullable=True, index=True)

    delivery_method = db.Column(db.String(255), nullable=True)
    own_transport = db.Column(db.Boolean, default=False, nullable=False)
    delivery_cost = db.Column(db.Numeric(10, 2), nullable=True)

    price_type = db.Column(db.Enum('netto', 'brutto', '', name='sales_price_type'),
                           nullable=True, default='')
    payment_method = db.Column(db.String(255), nullable=True)
    paid_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    payment_date = db.Column(db.Date, nullable=True)
    balance_due = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    # Rozbicie wpłat na kasę i dwa rachunki — BaseLinker zna tylko sumę.
    advance_cash = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    advance_wp = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    advance_loza = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    paid_cash = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    paid_wp = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    paid_loza = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    current_status = db.Column(db.String(100), nullable=True, index=True)
    baselinker_status_id = db.Column(db.Integer, nullable=True)
    picked_up = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    client = db.relationship('SalesClient', backref='orders')
    items = db.relationship('SalesOrderItem', back_populates='order',
                            cascade='all, delete-orphan', lazy='selectin')


class SalesOrderItem(db.Model):
    """Jeden wiersz na pozycję produktową zamówienia."""
    __tablename__ = 'sales_order_items'

    # TOŻSAMOŚĆ POZYCJI. Klucz `bl_order_product_id` ma wskazywać DOKŁADNIE
    # jeden wiersz zamówienia — na tym stoi całe dopasowywanie w
    # `modules/reports/ingest.py::_upsert_pozycje` (reguła 1: „dopasowanie
    # WYŁĄCZNIE po `bl_order_product_id`, bez żadnego fallbacku").
    #
    # ZNALEZISKO WAŻNE (trzecia kontrola adwersaryjna). Ograniczenie istniało
    # tylko w bazie (`migrations/2026-09-23-unikalnosc-klucza-pozycji.sql`),
    # a nie w modelu. Pakiet testów buduje SQLite Z METADANYCH MODELU, więc
    # ŻADEN test tej reguły nie sprawdzał: dublet przechodził lokalnie i padał
    # dopiero na produkcji błędem 1062. Ta sama klasa rozjazdu model-baza, co
    # w pamięci projektu „Migracje maskowane przez create_all".
    #
    # NAZWA MUSI SIĘ ZGADZAĆ z nazwą z migracji (`uq_soi_order_bl_product`).
    # Migracja sprawdza istnienie indeksu po nazwie w `information_schema`,
    # a na czystej instalacji tabelę zakłada `create_all` z tego modelu —
    # rozjazd nazw dałby dwa niezależne indeksy na tych samych kolumnach.
    #
    # NULL-e się nie zderzają: ani MySQL/InnoDB, ani SQLite nie uznają NULL-a
    # za równy NULL-owi w indeksie unikalnym. Dlatego 7938 wierszy backfillu
    # (wszystkie bez klucza) przechodzi bez konfliktu. ZERO to już zwykła
    # wartość i kolidowałoby samo ze sobą — stąd normalizacja 0 -> NULL przy
    # zapisie w `_upsert_pozycje`.
    __table_args__ = (
        db.UniqueConstraint('order_id', 'bl_order_product_id',
                            name='uq_soi_order_bl_product'),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    bl_order_product_id = db.Column(db.BigInteger, nullable=True)

    wood_species = db.Column(db.String(50), nullable=True, index=True)
    technology = db.Column(db.String(50), nullable=True)
    wood_class = db.Column(db.String(10), nullable=True)
    finish_state = db.Column(db.String(50), nullable=True)
    group_type = db.Column(db.String(30), nullable=True, index=True)
    product_type = db.Column(db.String(30), nullable=True, index=True)

    length_cm = db.Column(db.Numeric(10, 2), nullable=True)
    width_cm = db.Column(db.Numeric(10, 2), nullable=True)
    thickness_cm = db.Column(db.Numeric(10, 2), nullable=True)
    quantity = db.Column(db.Integer, nullable=True)

    price_gross = db.Column(db.Numeric(10, 2), nullable=True)
    price_net = db.Column(db.Numeric(10, 2), nullable=True)
    value_gross = db.Column(db.Numeric(10, 2), nullable=True)
    value_net = db.Column(db.Numeric(10, 2), nullable=True)

    volume_per_piece = db.Column(db.Numeric(10, 6), nullable=True)
    total_volume = db.Column(db.Numeric(10, 6), nullable=True)
    total_surface_m2 = db.Column(db.Numeric(10, 4), nullable=True)
    price_per_m3 = db.Column(db.Numeric(10, 2), nullable=True)

    raw_product_name = db.Column(db.Text, nullable=True)

    order = db.relationship('SalesOrder', back_populates='items')
