# -*- coding: utf-8 -*-
"""
Modele priorytetów produkcji (spec 2026-10-04, sekcje 8.2–8.4). Kolumny zamówienia (`priority_stars`,
`priority_rank`, `priority_rung`) siedzą na ProductionOrder.

Trasa jest tu wyłącznie napisem (`'prod_routes.id'`, `relationship('Route')`), bez importu modeli logistyki:
pakiet logistyki importuje swoje routery, a te sięgają do priorytetów — import modeli w obie strony zrobiłby cykl.
"""
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import relationship

from extensions import db
from modules.production.models import get_local_now
from modules.production.priorytety import stale


class PriorityRung(db.Model):
    """
    Szczebel drabiny priorytetów: gwiazdki (stałe), tag terminowy albo trasa (ruchome).

    `position` jest renumerowane 1..n przy każdym zapisie drabiny i obejmuje WSZYSTKIE wiersze — także szczeble
    tras, które przestały być robocze/zatwierdzone (ukryte w widoku, wracają w to samo miejsce po „Cofnij
    załadunek”). Zapis wyłącznie pod blokadą tras (`priorytety.services.drabina`).
    """
    __tablename__ = 'prod_priority_rungs'
    __table_args__ = (
        UniqueConstraint('kind', 'stars', name='uq_prod_priority_rungs_stars'),
        UniqueConstraint('kind', 'tag', name='uq_prod_priority_rungs_tag'),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(Enum(*stale.RODZAJE_SZCZEBLA, name='priority_rung_kind'), nullable=False)
    # 0–5 dla szczebla gwiazdek, inaczej NULL.
    stars = Column(SmallInteger)
    # stale.TAGI dla szczebla tagu, inaczej NULL.
    tag = Column(String(32))
    route_id = Column(Integer, ForeignKey('prod_routes.id', ondelete='CASCADE'), unique=True)
    position = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    updated_by = Column(Integer)

    route = relationship('Route')

    @property
    def klucz(self):
        """Klucz szczebla, jakim posługuje się algorytm rangi: ('stars', n) | ('tag', t) | ('route', id)."""
        if self.kind == 'stars':
            return ('stars', self.stars)
        if self.kind == 'tag':
            return ('tag', self.tag)
        return ('route', self.route_id)

    def __repr__(self):
        return '<PriorityRung %s %s poz=%s>' % (self.kind, self.klucz[1], self.position)


class PriorityLog(db.Model):
    """Każda zmiana priorytetów zostawia tu wiersz: gwiazdki, przesunięcie szczebla, odłożenie, ustawienia,
    ręczne przeliczenie."""
    __tablename__ = 'prod_priority_log'

    id = Column(Integer, primary_key=True)
    action = Column(Enum(*stale.AKCJE_LOGU, name='priority_log_action'), nullable=False)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'), index=True)
    # Kafel-pozycja (odłożenia na stanowiskach pozycyjnych).
    product_id = Column(Integer)
    # Szczebel trasy.
    route_id = Column(Integer, index=True)
    station_code = Column(String(32), index=True)
    old_value = Column(String(64))
    new_value = Column(String(64))
    # Powód odłożenia (stale.POWODY_ODLOZENIA) i notatka.
    reason = Column(String(32))
    note = Column(String(255))
    user_id = Column(Integer)
    # Akcje z tabletów mają pracownika i urządzenie (prod_devices.id), a nie użytkownika panelu.
    worker_id = Column(Integer)
    device_id = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=get_local_now, index=True)


class StationDesk(db.Model):
    """
    Stół stanowiska: kafle, które tablety stanowiska pokazują jako „do zrobienia” (`postponed_at` NULL) oraz
    kafle odłożone (`postponed_at` NOT NULL). Wiersz znika razem z kaflem.
    """
    __tablename__ = 'prod_station_desk'
    __table_args__ = (
        UniqueConstraint('station_code', 'unit_key', name='uq_prod_station_desk_unit'),
    )

    id = Column(Integer, primary_key=True)
    station_code = Column(String(32), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'), nullable=False, index=True)
    # NULL dla kafla-zamówienia.
    product_id = Column(Integer, ForeignKey('prod_products.id', ondelete='CASCADE'), index=True)
    # `p:<product_id>` albo `o:<order_id>`.
    unit_key = Column(String(24), nullable=False)
    pulled_at = Column(DateTime, nullable=False, default=get_local_now)
    postponed_at = Column(DateTime)
    postpone_reason = Column(String(32))
    postpone_note = Column(String(255))
    postponed_by_worker_id = Column(Integer)
    postponed_device_id = Column(Integer)
    # Skąd kafel wziął się na stole: stale.ZRODLA_KAFLA (kolejka, dorobka, biuro, start) — spec 5.1.
    zrodlo = Column(String(16), nullable=False, default=stale.ZRODLO_KOLEJKA, server_default=stale.ZRODLO_KOLEJKA)
    # Użytkownik panelu, który wysłał kafel na stół („Wyślij na stanowisko”) albo przygotował start stołów.
    sent_by_user_id = Column(Integer)
