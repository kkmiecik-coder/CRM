# -*- coding: utf-8 -*-
"""Modele logistyki równoległej. Kolumny zamówienia siedzą na ProductionOrder."""
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String

from extensions import db
from modules.production.models import get_local_now

AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status', 'adres')


class LogisticsLog(db.Model):
    """Każda zmiana logistyki zamówienia zostawia tu jeden wiersz."""
    __tablename__ = 'prod_logistics_log'

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    action = Column(Enum(*AKCJE_LOGU, name='logistics_log_action'), nullable=False)
    old_value = Column(String(64))
    new_value = Column(String(64))
    route_id = Column(Integer)
    user_id = Column(Integer, index=True)
    note = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=get_local_now, index=True)


class OrderGeo(db.Model):
    """Współrzędne adresu dostawy zamówienia (etap 2). Jeden wiersz na zamówienie."""
    __tablename__ = 'prod_order_geo'

    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'), primary_key=True)
    lat = Column(Numeric(9, 6))
    lng = Column(Numeric(9, 6))
    source = Column(Enum('gugik', 'nominatim', 'reczna', name='order_geo_source'))
    quality = Column(Enum('dokladna', 'przyblizona', 'nie_znaleziono', name='order_geo_quality'),
                     nullable=False)
    # SHA-1 znormalizowanego adresu, z którego liczono — zmiana adresu w Base. = inny skrót.
    address_hash = Column(String(40), nullable=False)
    # Punkt ręczny, a adres w Base. zmienił się później — ikona „adres zmieniony".
    address_changed_after_manual = Column(Boolean, nullable=False, default=False)
    # Nieudane próby automatu dla TEGO adresu; po MAKS_PROB automat odpuszcza.
    attempts = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
