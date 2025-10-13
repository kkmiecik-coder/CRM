# app/modules/users/models.py
"""
Modele użytkowników i zaproszeń
================================

Przeniesione z modules/calculator/models.py do dedykowanego modułu users.

Modele:
- User: Użytkownicy systemu CRM
- Invitation: Zaproszenia do systemu

Autor: Konrad Kmiecik
Data: 2025-01-10
"""

from extensions import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


# ============================================================================
# MODEL: User - Użytkownicy systemu
# ============================================================================

class User(UserMixin, db.Model):
    """
    Użytkownicy systemu CRM
    Przeniesione z calculator/models.py
    """
    __tablename__ = 'users'
    
    # ========== PODSTAWOWE POLA ==========
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    
    # Dane osobowe
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    
    # Avatar
    avatar_path = db.Column(db.String(255), nullable=True)
    
    # Status
    active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Token resetowania hasła
    reset_token = db.Column(db.String(256), nullable=True)
    
    # Rola użytkownika
    role = db.Column(db.String(20), nullable=True)
    
    # Multiplier dla partnerów
    multiplier_id = db.Column(db.Integer, db.ForeignKey('multipliers.id'), nullable=True)
    multiplier = db.relationship('Multiplier', foreign_keys=[multiplier_id])
    
    # Stanowisko produkcyjne
    assigned_workstation_id = db.Column(db.Integer, nullable=True)
    
    # ========== METADANE ==========
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # ========== FLASK-LOGIN WYMAGANE METODY ==========
    
    def is_authenticated(self):
        """Zwraca True jeśli użytkownik jest zalogowany"""
        return True
    
    def is_active(self):
        """Zwraca True jeśli konto jest aktywne"""
        return self.active
    
    def is_anonymous(self):
        """Zwraca True dla użytkowników anonimowych"""
        return False
    
    def get_id(self):
        """Zwraca unikalny identyfikator użytkownika jako string"""
        return str(self.id)
    
    # ========== METODY UŻYTKOWNIKA ==========
    
    def get_full_name(self):
        """Zwraca pełne imię i nazwisko lub email"""
        if self.first_name or self.last_name:
            return f"{self.first_name or ''} {self.last_name or ''}".strip()
        return self.email
    
    def set_password(self, password):
        """Ustawia zahashowane hasło"""
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        """Sprawdza poprawność hasła"""
        return check_password_hash(self.password, password)
    
    # ========== METODY KONTROLI DOSTĘPU ==========
    
    def is_admin(self):
        """Sprawdza czy użytkownik ma rolę admin"""
        return self.role and self.role.lower() in ['admin', 'administrator']
    
    def is_partner(self):
        """Sprawdza czy użytkownik ma rolę partner"""
        return self.role and self.role.lower() == 'partner'
    
    def is_user(self):
        """Sprawdza czy użytkownik ma rolę user"""
        return self.role and self.role.lower() == 'user'
    
    def can_access_production(self):
        """Sprawdza czy użytkownik może dostać się do modułu produkcji"""
        return self.is_active() and self.role in ['admin', 'user', 'production']
    
    def __repr__(self):
        return f"<User {self.email}>"


# ============================================================================
# MODEL: Invitation - Zaproszenia użytkowników
# ============================================================================

class Invitation(db.Model):
    """Zaproszenia do systemu"""
    __tablename__ = 'invitations'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    token = db.Column(db.String(256), nullable=False, unique=True)
    active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), nullable=True)
    
    # Multiplier dla partnerów
    multiplier_id = db.Column(db.Integer, db.ForeignKey('multipliers.id'), nullable=True)
    multiplier = db.relationship('Multiplier')
    
    # Metadane
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<Invitation {self.email} - {"active" if self.active else "inactive"}>'