# -*- coding: utf-8 -*-
"""Modele logistyki równoległej. Kolumny zamówienia siedzą na ProductionOrder."""
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String

from extensions import db
from modules.production.models import get_local_now

AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status')


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
