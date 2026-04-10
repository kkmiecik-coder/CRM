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
    request_data = db.Column(db.Text(4294967295))
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

    Kolumny kontroli dostępu:
    - allowed_roles (JSON): role które mogą WYBRAĆ to źródło przy tworzeniu zamówienia
    - visible_for_roles (JSON): role dla których źródło jest WIDOCZNE w ustawieniach
    - assigned_user_ids (JSON): ID użytkowników dla których to źródło jest domyślne
      np. "Czarnecki" -> [14, 15]

    NULL = dostępne dla wszystkich
    """
    __tablename__ = 'baselinker_config'

    id = db.Column(db.Integer, primary_key=True)
    config_type = db.Column(db.String(50), nullable=False)
    baselinker_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    # Kontrola dostępu - kto może używać źródła
    allowed_roles = db.Column(db.JSON, nullable=True)

    # Widoczność w ustawieniach
    visible_for_roles = db.Column(db.JSON, nullable=True)

    # Przypisani użytkownicy (dla których to źródło jest domyślne)
    assigned_user_ids = db.Column(db.JSON, nullable=True)

    # Kolejność wyświetlania
    sort_order = db.Column(db.Integer, default=0)

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
    
    def is_assigned_to_user(self, user_id):
        """
        Sprawdza czy źródło jest przypisane do konkretnego użytkownika

        Args:
            user_id (int): ID użytkownika

        Returns:
            bool: True jeśli użytkownik jest na liście assigned_user_ids
        """
        if self.assigned_user_ids is None:
            return False
        return user_id in self.assigned_user_ids

    def is_visible_for_role(self, user_role, is_flexible_partner=False):
        """
        Sprawdza czy źródło jest widoczne dla danej roli (w ustawieniach)

        Args:
            user_role (str): 'admin', 'user', 'partner'
            is_flexible_partner (bool): Czy użytkownik jest flexible partner

        Returns:
            bool: True jeśli element jest widoczny
        """
        if self.visible_for_roles is None:
            return True

        effective_role = 'flexible_partner' if is_flexible_partner else user_role
        return effective_role in self.visible_for_roles

    @classmethod
    def get_order_sources_for_user(cls, user_id, user_role, is_flexible_partner=False):
        """
        Pobiera źródła zamówień dostępne dla użytkownika

        Args:
            user_id (int): ID użytkownika
            user_role (str): Rola użytkownika
            is_flexible_partner (bool): Czy flexible partner

        Returns:
            list: Lista źródeł dostępnych dla użytkownika
        """
        sources = cls.query.filter_by(
            config_type='order_source',
            is_active=True
        ).order_by(cls.sort_order).all()

        return [s for s in sources if s.is_allowed_for_role(user_role, is_flexible_partner)]

    @classmethod
    def suggest_order_source(cls, user_id, user_role, client=None, is_flexible_partner=False):
        """
        Sugeruje źródło zamówienia na podstawie kontekstu

        Logika:
        1. Jeśli użytkownik ma przypisane źródło (assigned_user_ids) -> to źródło
        2. Jeśli klient ma zapisane order_source_id -> to źródło
        3. Jeśli klient ma NIP (B2B):
           - Jeśli ma >1 zamówień i poprzednie było "Nowy B2B" -> "Stały B2B"
           - W przeciwnym razie -> "Nowy B2B"
        4. Jeśli klient nie ma NIP (Detal) -> "Detal"
        5. Domyślne źródło (is_default=True)

        Args:
            user_id (int): ID użytkownika
            user_role (str): Rola użytkownika
            client: Obiekt klienta (opcjonalny)
            is_flexible_partner (bool): Czy flexible partner

        Returns:
            BaselinkerConfig lub None: Sugerowane źródło
        """
        # 1. Sprawdź czy użytkownik ma przypisane źródło
        sources = cls.query.filter_by(
            config_type='order_source',
            is_active=True
        ).all()

        for source in sources:
            if source.is_assigned_to_user(user_id):
                return source

        # 2. Sprawdź czy klient ma zapisane źródło
        if client and hasattr(client, 'order_source_id') and client.order_source_id:
            client_source = cls.query.filter_by(
                config_type='order_source',
                baselinker_id=client.order_source_id,
                is_active=True
            ).first()
            if client_source:
                return client_source

        # 3-4. Logika B2B vs Detal (na podstawie NIP)
        if client and hasattr(client, 'invoice_nip') and client.invoice_nip:
            # Klient ma NIP = B2B
            # Sprawdź ile zamówień ma klient i jakie było poprzednie źródło
            # Ta logika zostanie zaimplementowana w serwisie z dostępem do zamówień
            pass

        # 5. Domyślne źródło
        return cls.get_default_order_source()

    def to_dict(self, include_permissions=False, include_config=False):
        """Konwersja do słownika dla JSON"""
        data = {
            'id': self.baselinker_id,  # WAŻNE: używamy baselinker_id jako 'id'
            'db_id': self.id,  # Wewnętrzne ID w bazie
            'name': self.name,
            'is_default': self.is_default,
            'is_active': self.is_active,
            'sort_order': self.sort_order
        }

        if include_permissions:
            data['allowed_roles'] = self.allowed_roles

        if include_config:
            data['visible_for_roles'] = self.visible_for_roles
            data['assigned_user_ids'] = self.assigned_user_ids
            data['allowed_roles'] = self.allowed_roles

        return data