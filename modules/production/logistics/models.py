# -*- coding: utf-8 -*-
"""Modele logistyki równoległej. Kolumny zamówienia siedzą na ProductionOrder."""
from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import LONGTEXT

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


STATUSY_TRASY = ('robocza', 'zatwierdzona', 'wykonana')


class Vehicle(db.Model):
    """Pojazd floty. Nigdy nie kasujemy — wyłączamy (is_active=False)."""
    __tablename__ = 'prod_vehicles'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    registration = Column(String(20))
    capacity_kg = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=get_local_now, nullable=False)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    deactivated_at = Column(DateTime)


class Route(db.Model):
    """Trasa transportu własnego: Robocza → Zatwierdzona → Wykonana."""
    __tablename__ = 'prod_routes'

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    status = Column(Enum(*STATUSY_TRASY, name='route_status'), nullable=False,
                    default='robocza', index=True)
    vehicle_id = Column(Integer, ForeignKey('prod_vehicles.id', ondelete='SET NULL'), index=True)
    driver_worker_id = Column(Integer, ForeignKey('prod_workers.id', ondelete='SET NULL'), index=True)
    notes = Column(Text)
    approved_at = Column(DateTime)
    approved_by = Column(Integer)
    completed_at = Column(DateTime)
    completed_by = Column(Integer)
    created_at = Column(DateTime, default=get_local_now, nullable=False)
    created_by = Column(Integer)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    # Cache przebiegu z ORS; przeliczany, gdy zmieni się geometry_hash (kolejność + współrzędne).
    geometry_json = Column(Text().with_variant(LONGTEXT(), 'mysql'))
    distance_km = Column(Numeric(8, 1))
    duration_min = Column(Integer)
    geometry_hash = Column(String(40))
    geometry_approx = Column(Boolean, nullable=False, default=False)

    vehicle = relationship('Vehicle')
    driver = relationship('ProductionWorker')
    stops = relationship('RouteStop', back_populates='route', order_by='RouteStop.position',
                         cascade='all, delete-orphan')


class RouteStop(db.Model):
    """Przystanek = zamówienie na trasie. Zamówienie jest na co najwyżej jednej trasie."""
    __tablename__ = 'prod_route_stops'

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey('prod_routes.id', ondelete='CASCADE'),
                      nullable=False, index=True)
    order_id = Column(Integer, ForeignKey('prod_orders.id', ondelete='CASCADE'),
                      nullable=False, unique=True)
    position = Column(Integer, nullable=False)

    route = relationship('Route', back_populates='stops')
