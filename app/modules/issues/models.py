# app/modules/issues/models.py
"""
Modele danych dla systemu ticketów

Modele:
- Ticket: Główne zgłoszenia
- TicketMessage: Wiadomości w ticketach (konwersacja)
- TicketAttachment: Załączniki do ticketów

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

from extensions import db
from datetime import datetime


# ============================================================================
# MODEL: Ticket - Zgłoszenia
# ============================================================================

class Ticket(db.Model):
    """
    Model ticketu (zgłoszenia)
    """
    __tablename__ = 'issues_tickets'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(8), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    
    # Kategoryzacja
    category = db.Column(db.String(50), nullable=False)
    subcategory = db.Column(db.String(50), nullable=True)
    
    # Status i priorytet
    priority = db.Column(
        db.Enum('low', 'medium', 'high', 'critical', name='ticket_priority'),
        default='medium',
        nullable=False
    )
    status = db.Column(
        db.Enum('new', 'open', 'in_progress', 'closed', 'cancelled', name='ticket_status'),
        default='new',
        nullable=False,
        index=True
    )
    
    # Użytkownicy
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    
    # Daty
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow, index=True)
    first_response_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    
    # Relacje
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_tickets')
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id], backref='assigned_tickets')
    messages = db.relationship('TicketMessage', back_populates='ticket', cascade='all, delete-orphan', order_by='TicketMessage.created_at')
    attachments = db.relationship('TicketAttachment', back_populates='ticket', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Ticket #{self.ticket_number}: {self.title[:30]}>"
    
    def to_dict(self):
        """Konwersja do słownika dla API"""
        return {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'title': self.title,
            'category': self.category,
            'subcategory': self.subcategory,
            'priority': self.priority,
            'status': self.status,
            'created_by_user_id': self.created_by_user_id,
            'created_by_email': self.created_by.email if self.created_by else None,
            'created_by_name': f"{self.created_by.first_name} {self.created_by.last_name}" if self.created_by and self.created_by.first_name else self.created_by.email if self.created_by else 'Unknown',  # ← DODANE
            'assigned_to_user_id': self.assigned_to_user_id,
            'assigned_to_email': self.assigned_to.email if self.assigned_to else None,
            'assigned_to_name': f"{self.assigned_to.first_name} {self.assigned_to.last_name}" if self.assigned_to and self.assigned_to.first_name else self.assigned_to.email if self.assigned_to else None,  # ← DODANE
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'first_response_at': self.first_response_at.isoformat() if self.first_response_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'messages_count': len(self.messages) if self.messages else 0,
            'attachments_count': len(self.attachments) if self.attachments else 0
        }


# ============================================================================
# MODEL: TicketMessage - Wiadomości w ticketach
# ============================================================================

class TicketMessage(db.Model):
    """
    Model wiadomości w tickecie (konwersacja)
    """
    __tablename__ = 'issues_ticket_messages'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('issues_tickets.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    is_internal_note = db.Column(db.Boolean, default=False, nullable=False)
    
    # Daty
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relacje
    ticket = db.relationship('Ticket', back_populates='messages')
    user = db.relationship('User', backref='ticket_messages')
    attachments = db.relationship('TicketAttachment', back_populates='message', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<TicketMessage ticket_id={self.ticket_id} user_id={self.user_id}>"
    
    def to_dict(self):
        """Konwersja do słownika dla API"""
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'user_id': self.user_id,
            'user_email': self.user.email if self.user else None,
            'user_name': f"{self.user.first_name} {self.user.last_name}" if self.user and self.user.first_name else self.user.email if self.user else 'Unknown',
            'user_role': self.user.role if self.user else None,
            'user_avatar': self.user.avatar_path if self.user and self.user.avatar_path else None,  # ← DODANE
            'message': self.message,
            'is_internal_note': self.is_internal_note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'attachments': [att.to_dict() for att in self.attachments] if self.attachments else []
        }


# ============================================================================
# MODEL: TicketAttachment - Załączniki do ticketów
# ============================================================================

class TicketAttachment(db.Model):
    """
    Model załącznika do ticketu
    """
    __tablename__ = 'issues_ticket_attachments'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('issues_tickets.id'), nullable=True, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('issues_ticket_messages.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # Informacje o pliku
    filename = db.Column(db.String(255), nullable=False)  # uuid_original.ext
    original_filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(500), nullable=False)  # względna ścieżka
    filesize = db.Column(db.Integer, nullable=False)  # bajty
    mimetype = db.Column(db.String(100), nullable=False)
    
    # Daty
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacje
    ticket = db.relationship('Ticket', back_populates='attachments')
    message = db.relationship('TicketMessage', back_populates='attachments')
    user = db.relationship('User', backref='ticket_attachments')
    
    def __repr__(self):
        return f"<TicketAttachment {self.original_filename}>"
    
    def to_dict(self):
        """Konwersja do słownika dla API"""
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'message_id': self.message_id,
            'user_id': self.user_id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'filepath': self.filepath,
            'filesize': self.filesize,
            'filesize_mb': round(self.filesize / (1024 * 1024), 2),
            'mimetype': self.mimetype,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# ============================================================================
# MODEL: TicketEvent - Logi zdarzeń w ticketach
# ============================================================================

class TicketEvent(db.Model):
    """
    Model eventów/zdarzeń w tickecie (timeline)
    """
    __tablename__ = 'issues_ticket_events'
    
    # Pola podstawowe
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('issues_tickets.id'), nullable=False, index=True)
    
    # Typ zdarzenia
    event_type = db.Column(db.String(50), nullable=False)
    
    # Kto wykonał akcję
    performed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # Wartości (przed/po)
    old_value = db.Column(db.String(100), nullable=True)
    new_value = db.Column(db.String(100), nullable=True)
    
    # Dodatkowe dane (JSON) - ZMIENIONA NAZWA!
    extra_data = db.Column(db.JSON, nullable=True)
    
    # Data
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relacje
    ticket = db.relationship('Ticket', backref='events')
    performed_by = db.relationship('User', backref='ticket_events')
    
    def __repr__(self):
        return f"<TicketEvent {self.event_type} ticket_id={self.ticket_id}>"
    
    def to_dict(self):
        """Konwersja do słownika dla API"""
        return {
            'type': 'event',
            'id': self.id,
            'ticket_id': self.ticket_id,
            'event_type': self.event_type,
            'performed_by_user_id': self.performed_by_user_id,
            'performed_by_name': f"{self.performed_by.first_name} {self.performed_by.last_name}" if self.performed_by and self.performed_by.first_name else self.performed_by.email if self.performed_by else 'System',
            'old_value': self.old_value,
            'new_value': self.new_value,
            'extra_data': self.extra_data,  # ← Zmienione z metadata
            'created_at': self.created_at.isoformat() if self.created_at else None
        }