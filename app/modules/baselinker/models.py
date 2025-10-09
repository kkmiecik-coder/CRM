# app/modules/baselinker/models.py
from extensions import db
from datetime import datetime

class BaselinkerOrderLog(db.Model):
    """Model do logowania operacji z Baselinker API"""
    __tablename__ = 'baselinker_order_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'), nullable=False)
    baselinker_order_id = db.Column(db.Integer, nullable=True)  # ID zamówienia w Baselinker
    action = db.Column(db.String(50), nullable=False)  # 'create_order', 'update_order', etc.
    status = db.Column(db.String(20), nullable=False)  # 'success', 'error', 'pending'
    request_data = db.Column(db.Text)  # JSON request sent to API
    response_data = db.Column(db.Text)  # JSON response from API
    error_message = db.Column(db.Text)  # Error message if any
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
    """Konfiguracja Baselinker - źródła, statusy itp."""
    __tablename__ = 'baselinker_config'
    
    id = db.Column(db.Integer, primary_key=True)
    config_type = db.Column(db.String(50), nullable=False)  # 'order_source', 'order_status', 'payment_method'
    baselinker_id = db.Column(db.Integer, nullable=False)  # ID w systemie Baselinker
    name = db.Column(db.String(255), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_default_order_source(cls):
        return cls.query.filter_by(config_type='order_source', is_default=True, is_active=True).first()
    
    @classmethod
    def get_default_order_status(cls):
        return cls.query.filter_by(config_type='order_status', is_default=True, is_active=True).first()