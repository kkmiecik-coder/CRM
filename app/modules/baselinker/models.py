# app/modules/baselinker/models.py
from extensions import db
from datetime import datetime

class BaselinkerOrderLog(db.Model):
    """Model do logowania operacji z Baselinker API"""
    __tablename__ = 'baselinker_order_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'), nullable=False)
    baselinker_order_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    request_data = db.Column(db.Text)
    response_data = db.Column(db.Text)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    quote = db.relationship('Quote', backref='baselinker_logs')
    user = db.relationship('User', backref='baselinker_actions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'quote_id': self.quote_id,
            'baselinker_order_id': self.baselinker_order_id,
            'action': self.action,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by
        }


class BaselinkerConfig(db.Model):
    """
    Konfiguracja Baselinker - źródła, statusy itp.
    
    NOWA KOLUMNA: allowed_roles (JSON)
    - NULL = dostępne dla wszystkich ról
    - JSON array = dostępne tylko dla wymienionych ról
      np. ["admin", "user", "flexible_partner"]
    """
    __tablename__ = 'baselinker_config'
    
    id = db.Column(db.Integer, primary_key=True)
    config_type = db.Column(db.String(50), nullable=False)
    baselinker_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # NOWA KOLUMNA - kontrola dostępu
    allowed_roles = db.Column(db.JSON, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_default_order_source(cls):
        return cls.query.filter_by(config_type='order_source', is_default=True, is_active=True).first()
    
    @classmethod
    def get_default_order_status(cls):
        return cls.query.filter_by(config_type='order_status', is_default=True, is_active=True).first()
    
    def is_allowed_for_role(self, user_role, is_flexible_partner=False):
        """
        Sprawdza czy dany element jest dostępny dla roli użytkownika
        
        Args:
            user_role (str): 'admin', 'user', 'partner'
            is_flexible_partner (bool): Czy użytkownik jest flexible partner
            
        Returns:
            bool: True jeśli element jest dostępny
        """
        # NULL = brak ograniczeń, dostępne dla wszystkich
        if self.allowed_roles is None:
            return True
        
        # Określ efektywną rolę użytkownika
        effective_role = 'flexible_partner' if is_flexible_partner else user_role
        
        # Sprawdź czy rola jest na liście dozwolonych
        return effective_role in self.allowed_roles
    
    def to_dict(self, include_permissions=False):
        """Konwersja do słownika dla JSON"""
        data = {
            'id': self.baselinker_id,  # WAŻNE: używamy baselinker_id jako 'id'
            'name': self.name,
            'is_default': self.is_default,
            'is_active': self.is_active
        }
        
        if include_permissions:
            data['allowed_roles'] = self.allowed_roles
            
        return data