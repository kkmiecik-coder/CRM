# -*- coding: utf-8 -*-
"""
Modele trakowni — osobny rejestr surowca wchodzącego do zakładu.

Nie ma żadnego powiązania z prod_orders / prod_products. Trakownia nie jest
ogniwem pipeline'u produktów, tylko rejestracją tego, co przyjechało
od dostawcy i zostało rozcięte.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from extensions import db

# ── Statusy zlecenia ────────────────────────────────────────────────────────
STATUS_NEW = 'new'
STATUS_IN_PROGRESS = 'in_progress'
STATUS_COMPLETED = 'completed'
STATUS_SETTLED = 'settled'

# Tablet może dodawać i zmieniać pomiary tylko w tych statusach.
OPEN_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS)

# Panel może zmieniać pomiary także po zakończeniu przez pracownika,
# ale nie po rozliczeniu — tam wymagane jest najpierw „Cofnij rozliczenie".
PANEL_WRITABLE_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED)

ALL_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_SETTLED)

# ── Akcje audytu ────────────────────────────────────────────────────────────
# log_create pochodzi z tabletu, log_create_manual z panelu — rozróżnienie jest
# istotne, bo pomiar przepisany przez biuro ma inną wagę dowodową przy sporze
# z dostawcą niż zmierzony na stanowisku.
AUDIT_ACTIONS = frozenset({
    'log_create', 'log_create_manual', 'log_update', 'log_delete',
    'order_create', 'order_update', 'order_delete',
    'order_complete', 'order_reopen', 'order_settle', 'order_unsettle',
    'delivery_update', 'delivery_delete',
})


class SawmillSupplier(db.Model):
    """Dostawca surowca. W CRM nie było dotąd tej encji — clients to odbiorcy."""
    __tablename__ = 'prod_sawmill_suppliers'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    nip = Column(String(20), nullable=True)
    address_street = Column(String(200), nullable=True)
    address_zip = Column(String(12), nullable=True)
    address_city = Column(String(120), nullable=True)
    contact_person = Column(String(120), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(160), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.now)

    def __repr__(self):
        return '<SawmillSupplier {}>'.format(self.name)


class SawmillSpecies(db.Model):
    """Gatunek surowca. Seed: Dąb, Jesion, Buk — reszta przez CRUD w panelu."""
    __tablename__ = 'prod_sawmill_species'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)
    short_code = Column(String(8), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    def __repr__(self):
        return '<SawmillSpecies {}>'.format(self.name)


class SawmillCounter(db.Model):
    """Licznik numeracji zleceń, jeden wiersz na rok."""
    __tablename__ = 'prod_sawmill_counters'

    year = Column(SmallInteger, primary_key=True)
    last_number = Column(Integer, nullable=False, default=0)

    def __repr__(self):
        return '<SawmillCounter {}={}>'.format(self.year, self.last_number)


class SawmillDelivery(db.Model):
    """
    Dostawa — nagłówek faktury. Numer i data faktury są opcjonalne, bo drewno
    bywa przywożone bez niej. Dostawa nie ma własnego numeru; identyfikują ją
    dostawca, data i ewentualna faktura.
    """
    __tablename__ = 'prod_sawmill_deliveries'

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey('prod_sawmill_suppliers.id'),
                         nullable=False, index=True)
    invoice_number = Column(String(64), nullable=True, index=True)
    invoice_date = Column(Date, nullable=True)
    delivery_date = Column(Date, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.now)

    supplier = relationship('SawmillSupplier', lazy='joined')

    def __repr__(self):
        return '<SawmillDelivery {} {}>'.format(self.id, self.invoice_number or 'bez faktury')


class SawmillOrder(db.Model):
    """
    Zlecenie trakowania. Każda pozycja dostawy tworzy osobne zlecenie.

    Pola oznaczone w specyfikacji kłódką NIGDY nie trafiają na tablet —
    pracownik nie może znać deklaracji, bo wtedy pomiary zaczną się do niej
    zbiegać. Pilnuje tego serializer z białą listą pól.
    """
    __tablename__ = 'prod_sawmill_orders'

    id = Column(Integer, primary_key=True)
    order_number = Column(String(24), nullable=False, unique=True)
    delivery_id = Column(Integer, ForeignKey('prod_sawmill_deliveries.id'),
                         nullable=False, index=True)
    species_id = Column(Integer, ForeignKey('prod_sawmill_species.id'),
                        nullable=False, index=True)

    # Deklaracja dostawcy — wymagana zawsze, także gdy nie ma faktury.
    declared_volume_m3 = Column(Numeric(10, 3), nullable=False)
    declared_logs_count = Column(Integer, nullable=True)
    price_per_m3 = Column(Numeric(10, 2), nullable=True)
    declared_value = Column(Numeric(12, 2), nullable=True)

    # Objętość uzgodniona z dostawcą po weryfikacji różnicy.
    agreed_volume_m3 = Column(Numeric(10, 3), nullable=True)

    status = Column(String(16), nullable=False, default=STATUS_NEW, index=True)
    notes = Column(Text, nullable=True)
    settlement_notes = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by_device = Column(String(64), nullable=True)
    settled_at = Column(DateTime, nullable=True)
    settled_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    created_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.now)

    delivery = relationship('SawmillDelivery', lazy='joined')
    species = relationship('SawmillSpecies', lazy='joined')

    def __repr__(self):
        return '<SawmillOrder {} [{}]>'.format(self.order_number, self.status)


class SawmillLog(db.Model):
    """
    Pojedyncza kłoda. volume_m3 jest wyliczana przy zapisie i przechowywana —
    gdyby kiedyś zmienił się wzór, historyczne rozliczenia muszą zostać takie,
    jakie były w chwili pomiaru.
    """
    __tablename__ = 'prod_sawmill_logs'

    id = Column(Integer, primary_key=True)
    # Bez index=True — kompozytowy Index('ix_sawmill_log_order_active', ...)
    # niżej działa jako prefiks indeksu na samym order_id (MySQL), osobny
    # indeks byłby zbędny; zgodne z SQL, który ma tylko indeks kompozytowy.
    order_id = Column(Integer, ForeignKey('prod_sawmill_orders.id'),
                      nullable=False)
    # Numer nadawany przez serwer, nie tablet — przy kolejce offline dwa
    # urządzenia wysyłające naraz nadałyby te same numery.
    sequence_no = Column(Integer, nullable=False)

    # Obwód w połowie długości kłody — jedyny pomiar przekroju, jaki wykonuje
    # pracownik (metodyka Hubera, patrz services/volume.py).
    mid_circumference_cm = Column(Numeric(6, 1), nullable=False)
    length_cm = Column(Numeric(6, 1), nullable=False)
    volume_m3 = Column(Numeric(12, 6), nullable=False)

    device_id = Column(String(64), nullable=True, index=True)
    # Czas z tabletu — przy kolejce offline może być sprzed godzin.
    measured_at = Column(DateTime, nullable=False)
    # Czas wpłynięcia na serwer.
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.now)

    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint('order_id', 'sequence_no', name='uq_sawmill_log_seq'),
        Index('ix_sawmill_log_order_active', 'order_id', 'is_deleted'),
    )

    def __repr__(self):
        return '<SawmillLog {}#{} {} m3>'.format(self.order_id, self.sequence_no, self.volume_m3)


class SawmillAudit(db.Model):
    """
    Ślad audytowy zleceń i pomiarów.

    order_id celowo NIE ma klucza obcego, tylko indeks — wpisy muszą przeżyć
    usunięcie zlecenia, inaczej akcja order_delete nie miałaby gdzie się zapisać.
    Zdarzenia dostawy zapisujemy na każdym jej zleceniu, bo order_id jest NOT NULL
    i właśnie tam biuro chce je zobaczyć.
    """
    __tablename__ = 'prod_sawmill_audit'

    # BIGINT świadomie — audyt to tabela tylko dopisywana, rosnąca szybciej
    # niż reszta, zgodnie ze schematem w docs/superpowers/specs/2026-08-05-trakownia.sql.
    # with_variant(Integer, 'sqlite'): czysty BigInteger nie dostaje w SQLite
    # aliasu na rowid (autoincrement) — dialekt sqlite kompiluje go jako
    # BIGINT, a SQLite włącza automatyczny rowid tylko dla kolumny typu
    # dosłownie INTEGER. Bez tej wariancji każdy insert do tej tabeli w
    # testach (SQLite, bez Dockera) wywala się na `NOT NULL constraint
    # failed: prod_sawmill_audit.id`. Na MySQL/produkcji bez zmian — nadal
    # BIGINT AUTO_INCREMENT zgodnie ze schematem SQL.
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True)
    order_id = Column(Integer, nullable=False, index=True)
    log_id = Column(Integer, nullable=True)
    action = Column(String(24), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    device_id = Column(String(64), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)

    def __repr__(self):
        return '<SawmillAudit {} {}>'.format(self.action, self.order_id)
