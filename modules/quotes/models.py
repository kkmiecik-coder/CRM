# modules/quotes/models.py

from extensions import db
import secrets
import string
from datetime import datetime

# Importuj główne modele z calculator
from modules.calculator.models import (
    Quote,
    QuoteItem,
    QuoteItemDetails,
    QuoteCounter,
    QuoteLog,
    Multiplier,
    Price,
    User,
    FinishingTypePrice,
    FinishingColor
)

# Importuj model Client z modułu clients
try:
    from modules.clients.models import Client
except ImportError:
    # Jeśli nie możemy zaimportować, zdefiniuj placeholder
    class Client:
        pass

# Modele specyficzne dla modułu quotes

class QuoteStatus(db.Model):
    __tablename__ = 'quote_statuses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color_hex = db.Column('color_hex', db.String(20), nullable=True)
    
    def __repr__(self):
        return f"<QuoteStatus {self.name}>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color_hex
        }


class DiscountReason(db.Model):
    __tablename__ = 'discount_reasons'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, server_default=db.func.current_timestamp(), server_onupdate=db.func.current_timestamp())
    
    def __repr__(self):
        return f"<DiscountReason {self.name}>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active
        }
    
    @classmethod
    def get_active_reasons(cls):
        """Zwraca wszystkie aktywne powody rabatów"""
        return cls.query.filter_by(is_active=True).order_by(cls.name).all()
    
    @classmethod
    def get_active_reasons_dict(cls):
        """Zwraca aktywne powody rabatów jako słownik"""
        return [reason.to_dict() for reason in cls.get_active_reasons()]


# Eksportuj wszystkie modele dla łatwego importowania
__all__ = [
    # Z calculator
    'Quote',
    'QuoteItem',
    'QuoteItemDetails',
    'QuoteCounter',
    'QuoteLog',
    'Multiplier',
    'Price',
    'User',
    'FinishingTypePrice',
    'FinishingColor',
    # Z clients
    'Client',
    # Lokalne
    'QuoteStatus',
    'DiscountReason'
]