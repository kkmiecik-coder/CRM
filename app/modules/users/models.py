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
    role_id = db.Column(db.Integer, db.ForeignKey('users_roles.id'), nullable=True, index=True)
    
    # Multiplier dla partnerów
    multiplier_id = db.Column(db.Integer, db.ForeignKey('multipliers.id'), nullable=True)
    multiplier = db.relationship('Multiplier', foreign_keys=[multiplier_id])

    assigned_role = db.relationship('Role', back_populates='users', foreign_keys=[role_id])
    custom_permissions = db.relationship('UserPermission',back_populates='user',foreign_keys='UserPermission.user_id',cascade='all, delete-orphan')
    
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

# ============================================================================
# MODEL: Module - Moduły w systemie CRM
# ============================================================================

class Module(db.Model):
    """
    Moduły w systemie CRM (quotes, production, users, etc.)
    
    access_type:
        - 'public': dostępny dla wszystkich zalogowanych (np. dashboard)
        - 'protected': wymaga uprawnień (sprawdzane przez system)
        - 'custom': ma własną logikę autoryzacji (np. production z IP whitelist)
    """
    __tablename__ = 'users_modules'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    module_key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    
    # Typ dostępu
    access_type = db.Column(
        db.Enum('public', 'protected', 'custom', name='module_access_type'),
        nullable=False,
        default='protected'
    )
    
    # Status
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, 
        nullable=False, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # Relacje
    role_permissions = db.relationship(
        'RolePermission',
        back_populates='module',
        cascade='all, delete-orphan'
    )
    user_permissions = db.relationship(
        'UserPermission',
        back_populates='module',
        cascade='all, delete-orphan'
    )
    
    def __repr__(self):
        return f"<Module {self.module_key}: {self.display_name}>"
    
    def to_dict(self):
        """Konwersja do słownika (dla API)"""
        return {
            'id': self.id,
            'module_key': self.module_key,
            'display_name': self.display_name,
            'description': self.description,
            'icon': self.icon,
            'access_type': self.access_type,
            'is_active': self.is_active,
            'sort_order': self.sort_order
        }


# ============================================================================
# MODEL: Role - Role użytkowników
# ============================================================================

class Role(db.Model):
    """
    Role użytkowników w systemie (admin, user, partner)
    
    is_system: True = rola systemowa (chroniona przed usunięciem)
    """
    __tablename__ = 'users_roles'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Flags
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, 
        nullable=False, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # Relacje
    permissions = db.relationship(
        'RolePermission',
        back_populates='role',
        cascade='all, delete-orphan'
    )
    users = db.relationship(
        'User',
        back_populates='assigned_role',
        foreign_keys='User.role_id'
    )
    
    def __repr__(self):
        return f"<Role {self.role_name}: {self.display_name}>"
    
    def to_dict(self):
        """Konwersja do słownika (dla API)"""
        return {
            'id': self.id,
            'role_name': self.role_name,
            'display_name': self.display_name,
            'description': self.description,
            'is_system': self.is_system,
            'is_active': self.is_active
        }


# ============================================================================
# MODEL: RolePermission - Domyślne uprawnienia ról
# ============================================================================

class RolePermission(db.Model):
    """
    Domyślne uprawnienia dla ról (które moduły ma dana rola)
    
    Przykład: Rola "admin" ma dostęp do modułów: quotes, production, users
    """
    __tablename__ = 'users_role_permissions'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('users_roles.id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('users_modules.id'), nullable=False, index=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relacje
    role = db.relationship('Role', back_populates='permissions')
    module = db.relationship('Module', back_populates='role_permissions')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    
    # Unique constraint (jedna rola może mieć moduł tylko raz)
    __table_args__ = (
        db.UniqueConstraint('role_id', 'module_id', name='unique_role_module'),
    )
    
    def __repr__(self):
        role_name = self.role.role_name if self.role else 'Unknown'
        module_key = self.module.module_key if self.module else 'Unknown'
        return f"<RolePermission {role_name} -> {module_key}>"


# ============================================================================
# MODEL: UserPermission - Indywidualne uprawnienia użytkowników
# ============================================================================

class UserPermission(db.Model):
    """
    Indywidualne nadpisania uprawnień dla użytkowników
    
    access_type:
        - 'grant': nadaj dostęp (nawet jeśli rola nie ma)
        - 'revoke': odbierz dostęp (nawet jeśli rola ma) - DENY WYGRYWA!
    
    Przykład: Jan ma rolę "user" (bez production), ale indywidualnie 
              nadano mu dostęp (grant) do production
    """
    __tablename__ = 'users_user_permissions'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('users_modules.id'), nullable=False, index=True)
    access_type = db.Column(
        db.Enum('grant', 'revoke', name='user_permission_access_type'),
        nullable=False
    )
    
    # Metadata
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    
    # Relacje
    user = db.relationship('User', foreign_keys=[user_id], back_populates='custom_permissions')
    module = db.relationship('Module', back_populates='user_permissions')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    
    # Unique constraint (jeden użytkownik może mieć nadpisanie dla modułu tylko raz)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'module_id', name='unique_user_module'),
    )
    
    def __repr__(self):
        user_email = self.user.email if self.user else 'Unknown'
        module_key = self.module.module_key if self.module else 'Unknown'
        return f"<UserPermission {user_email} -> {module_key} ({self.access_type})>"


# ============================================================================
# MODEL: PermissionAuditLog - Historia zmian uprawnień
# ============================================================================

class PermissionAuditLog(db.Model):
    """
    Audit log - historia zmian uprawnień
    
    change_type:
        - 'role_changed': Zmiana roli użytkownika
        - 'module_granted': Nadanie dostępu do modułu
        - 'module_revoked': Odebranie dostępu do modułu
    
    Przykład: "Admin Kowalski nadał Janowi Nowakowi dostęp do modułu Production"
    """
    __tablename__ = 'users_permissions_audit_log'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Typ zmiany
    change_type = db.Column(db.String(50), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    
    # Wartości (JSON)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    
    # Metadata przeglądarki
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    
    # Timestamp
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relacje
    user = db.relationship('User', foreign_keys=[user_id], backref='permission_changes')
    changed_by = db.relationship('User', foreign_keys=[changed_by_user_id])
    
    def __repr__(self):
        user_email = self.user.email if self.user else 'Unknown'
        return f"<PermissionAuditLog {self.change_type} for {user_email}>"
    
    def to_dict(self):
        """Konwersja do słownika (dla API)"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_email': self.user.email if self.user else None,
            'changed_by_user_id': self.changed_by_user_id,
            'changed_by_email': self.changed_by.email if self.changed_by else None,
            'change_type': self.change_type,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'reason': self.reason,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }