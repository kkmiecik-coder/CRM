# app/modules/issues/services.py
"""
Logika biznesowa modułu ticketów

Serwisy:
- TicketService: Operacje na ticketach
- AttachmentService: Zarządzanie załącznikami
- NotificationService: Wysyłka powiadomień

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

from extensions import db, mail
from modules.logging import get_logger
from modules.users.models import User
from flask import current_app, render_template, url_for
from flask_mail import Message
from .models import Ticket, TicketMessage, TicketAttachment
from .utils import generate_ticket_number
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid

logger = get_logger('issues.services')


# ============================================================================
# TICKET SERVICE
# ============================================================================

class TicketService:
    """Serwis zarządzania ticketami"""
    
    @staticmethod
    def create_ticket(user_id: int, title: str, category: str, 
                     subcategory: str, priority: str, initial_message: str,
                     attachment_ids: list = None) -> Ticket:
        """
        Tworzy nowy ticket
        
        Args:
            user_id: ID użytkownika
            title: Tytuł ticketu
            category: Kategoria
            subcategory: Podkategoria
            priority: Priorytet
            initial_message: Pierwsza wiadomość
            attachment_ids: Lista ID załączników
        
        Returns:
            Ticket: Utworzony ticket
        
        Raises:
            ValueError: Błąd walidacji
        """
        try:
            # Walidacja
            if not title or len(title) < 5:
                raise ValueError("Tytuł musi mieć minimum 5 znaków")
            
            if not initial_message or len(initial_message) < 10:
                raise ValueError("Wiadomość musi mieć minimum 10 znaków")
            
            # Generuj unikalny numer ticketu
            ticket_number = generate_ticket_number()
            
            # Utwórz ticket
            ticket = Ticket(
                ticket_number=ticket_number,
                title=title,
                category=category,
                subcategory=subcategory,
                priority=priority,
                status='new',
                created_by_user_id=user_id
            )
            db.session.add(ticket)
            db.session.flush()  # Pobierz ID
            
            # Dodaj pierwszą wiadomość
            message = TicketMessage(
                ticket_id=ticket.id,
                user_id=user_id,
                message=initial_message,
                is_internal_note=False
            )
            db.session.add(message)
            db.session.flush()
            
            # Przypisz załączniki
            if attachment_ids:
                for att_id in attachment_ids[:5]:  # Max 5
                    attachment = TicketAttachment.query.get(att_id)
                    if attachment and attachment.user_id == user_id:
                        attachment.ticket_id = ticket.id
                        attachment.message_id = message.id
                        # Przenieś plik z temp do folderu ticketu
                        AttachmentService.move_attachment_to_ticket(att_id, ticket_number)
            
            db.session.commit()
            
            # Wyślij powiadomienie do adminów
            NotificationService.notify_admins_new_ticket(ticket)
            
            return ticket
        
        except ValueError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Błąd tworzenia ticketu: {e}")
            raise
    
    @staticmethod
    def add_message(ticket_id: int, user_id: int, message_text: str,
                   is_internal_note: bool = False, attachment_ids: list = None) -> TicketMessage:
        """
        Dodaje wiadomość do ticketu
        
        Args:
            ticket_id: ID ticketu
            user_id: ID użytkownika
            message_text: Treść wiadomości
            is_internal_note: Czy to notatka wewnętrzna
            attachment_ids: Lista ID załączników
        
        Returns:
            TicketMessage: Utworzona wiadomość
        """
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                raise ValueError("Ticket nie istnieje")
            
            user = User.query.get(user_id)
            
            # Dodaj wiadomość
            message = TicketMessage(
                ticket_id=ticket_id,
                user_id=user_id,
                message=message_text,
                is_internal_note=is_internal_note
            )
            db.session.add(message)
            db.session.flush()
            
            # Aktualizuj updated_at ticketu
            ticket.updated_at = datetime.utcnow()
            
            # Jeśli to pierwsza odpowiedź admina, zapisz first_response_at
            if user.role == 'admin' and not ticket.first_response_at:
                ticket.first_response_at = datetime.utcnow()
            
            # Przypisz załączniki
            if attachment_ids:
                for att_id in attachment_ids[:5]:
                    attachment = TicketAttachment.query.get(att_id)
                    if attachment and attachment.user_id == user_id:
                        attachment.message_id = message.id
                        attachment.ticket_id = ticket_id
                        # Przenieś plik z temp do folderu ticketu
                        AttachmentService.move_attachment_to_ticket(att_id, ticket.ticket_number)
            
            db.session.commit()
            
            # Wyślij powiadomienie
            if user.role == 'admin' and not is_internal_note:
                NotificationService.notify_user_new_response(ticket)
            
            return message
        
        except ValueError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Błąd dodawania wiadomości: {e}")
            raise
    
    @staticmethod
    def change_status(ticket_id: int, new_status: str, user_id: int) -> Ticket:
        """
        Zmienia status ticketu
        
        Args:
            ticket_id: ID ticketu
            new_status: Nowy status
            user_id: ID użytkownika wykonującego zmianę
        
        Returns:
            Ticket: Zaktualizowany ticket
        """
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                raise ValueError("Ticket nie istnieje")
            
            old_status = ticket.status
            ticket.status = new_status
            ticket.updated_at = datetime.utcnow()
            
            # Jeśli zamknięto, zapisz closed_at
            if new_status == 'closed':
                ticket.closed_at = datetime.utcnow()
            
            db.session.commit()
            
            return ticket
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Błąd zmiany statusu: {e}")
            raise
    
    @staticmethod
    def change_priority(ticket_id: int, new_priority: str, user_id: int) -> Ticket:
        """
        Zmienia priorytet ticketu
        
        Args:
            ticket_id: ID ticketu
            new_priority: Nowy priorytet
            user_id: ID użytkownika wykonującego zmianę
        
        Returns:
            Ticket: Zaktualizowany ticket
        """
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                raise ValueError("Ticket nie istnieje")
            
            old_priority = ticket.priority
            ticket.priority = new_priority
            ticket.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            return ticket
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Błąd zmiany priorytetu: {e}")
            raise
    
    @staticmethod
    def assign_ticket(ticket_id: int, admin_user_id: int) -> Ticket:
        """
        Przypisuje ticket do admina
        
        Args:
            ticket_id: ID ticketu
            admin_user_id: ID admina
        
        Returns:
            Ticket: Zaktualizowany ticket
        """
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                raise ValueError("Ticket nie istnieje")
            
            ticket.assigned_to_user_id = admin_user_id
            ticket.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            return ticket
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Błąd przypisywania ticketu: {e}")
            raise
    
    @staticmethod
    def get_user_tickets(user_id: int, is_admin: bool = False, 
                        status: str = None, limit: int = 50, offset: int = 0) -> dict:
        """
        Pobiera tickety użytkownika
        
        Args:
            user_id: ID użytkownika
            is_admin: Czy użytkownik jest adminem
            status: Filtr po statusie
            limit: Limit wyników
            offset: Offset dla paginacji
        
        Returns:
            dict: {'tickets': [...], 'total': int}
        """
        try:
            # Admin widzi wszystkie, user tylko swoje
            if is_admin:
                query = Ticket.query
            else:
                query = Ticket.query.filter_by(created_by_user_id=user_id)
            
            # Filtr statusu
            if status:
                query = query.filter_by(status=status)
            
            # Sortowanie
            query = query.order_by(Ticket.updated_at.desc())
            
            total = query.count()
            tickets = query.limit(limit).offset(offset).all()
            
            return {
                'tickets': tickets,
                'total': total
            }
        
        except Exception as e:
            logger.error(f"Błąd pobierania ticketów: {e}")
            raise
    
    @staticmethod
    def can_user_access_ticket(user_id: int, ticket: Ticket) -> bool:
        """Sprawdza czy użytkownik ma dostęp do ticketu"""
        user = User.query.get(user_id)
        if not user:
            return False
        return user.role == 'admin' or ticket.created_by_user_id == user_id
    
    @staticmethod
    def can_user_add_message(user_id: int, ticket: Ticket) -> bool:
        """Sprawdza czy użytkownik może dodać wiadomość"""
        user = User.query.get(user_id)
        if not user:
            return False
        return user.role == 'admin' or ticket.created_by_user_id == user_id


# ============================================================================
# ATTACHMENT SERVICE
# ============================================================================

class AttachmentService:
    """Serwis zarządzania załącznikami"""
    
    UPLOAD_FOLDER = 'modules/issues/uploads'
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_ATTACHMENTS = 5
    
    @staticmethod
    def save_attachment(file, user_id: int) -> TicketAttachment:
        """
        Zapisuje załącznik (tymczasowo, bez przypisania do ticketu)
        
        Args:
            file: FileStorage z Flask
            user_id: ID użytkownika
        
        Returns:
            TicketAttachment: Zapisany załącznik
        
        Raises:
            ValueError: Błąd walidacji
        """
        try:
            # Walidacja rozmiaru
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > AttachmentService.MAX_FILE_SIZE:
                raise ValueError(f"Plik jest za duży. Maksymalny rozmiar: 5 MB")
            
            if file_size == 0:
                raise ValueError("Plik jest pusty")
            
            # Generuj unikalną nazwę
            original_filename = secure_filename(file.filename)
            if not original_filename:
                raise ValueError("Nieprawidłowa nazwa pliku")
            
            unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
            
            # Zapisz tymczasowo w folderze temp
            temp_folder = os.path.join(AttachmentService.UPLOAD_FOLDER, 'temp')
            os.makedirs(temp_folder, exist_ok=True)
            
            temp_filepath = os.path.join(temp_folder, unique_filename)
            file.save(temp_filepath)
            
            # Utwórz rekord w bazie (bez ticket_id)
            attachment = TicketAttachment(
                user_id=user_id,
                filename=unique_filename,
                original_filename=original_filename,
                filepath=f"temp/{unique_filename}",
                filesize=file_size,
                mimetype=file.content_type or 'application/octet-stream'
            )
            db.session.add(attachment)
            db.session.commit()
            
            return attachment
        
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Błąd zapisu załącznika: {e}")
            raise
    
    @staticmethod
    def move_attachment_to_ticket(attachment_id: int, ticket_number: str):
        """
        Przenosi załącznik z temp do folderu ticketu
        
        Args:
            attachment_id: ID załącznika
            ticket_number: Numer ticketu
        """
        try:
            attachment = TicketAttachment.query.get(attachment_id)
            if not attachment:
                return
            
            # Utwórz folder ticketu
            ticket_folder = os.path.join(AttachmentService.UPLOAD_FOLDER, ticket_number)
            os.makedirs(ticket_folder, exist_ok=True)
            
            # Przenieś plik
            old_path = os.path.join(AttachmentService.UPLOAD_FOLDER, attachment.filepath)
            new_path = os.path.join(ticket_folder, attachment.filename)
            
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
                attachment.filepath = f"{ticket_number}/{attachment.filename}"
                db.session.commit()
        
        except Exception as e:
            logger.error(f"Błąd przenoszenia załącznika: {e}")


# ============================================================================
# NOTIFICATION SERVICE
# ============================================================================

class NotificationService:
    """Serwis powiadomień email"""
    
    @staticmethod
    def notify_admins_new_ticket(ticket: Ticket):
        """
        Wysyła email do wszystkich adminów o nowym tickecie
        
        Args:
            ticket: Obiekt ticketu
        """
        try:
            # Pobierz wszystkich adminów
            admins = User.query.filter_by(role='admin', active=True).all()
            
            if not admins:
                logger.error("Brak adminów do powiadomienia")
                return
            
            # Pobierz pierwszą wiadomość
            first_message = TicketMessage.query.filter_by(ticket_id=ticket.id).first()
            
            # Przygotuj email
            subject = f"[Ticket #{ticket.ticket_number}] Nowe zgłoszenie: {ticket.title}"
            
            for admin in admins:
                try:
                    msg = Message(
                        subject,
                        sender=current_app.config.get("MAIL_USERNAME"),
                        recipients=[admin.email]
                    )
                    
                    # Renderuj HTML
                    msg.html = render_template(
                        'issues/emails/new_ticket_admin.html',
                        ticket=ticket,
                        admin=admin,
                        first_message=first_message,
                        ticket_url=url_for('issues.ticket_detail', 
                                          ticket_number=ticket.ticket_number, 
                                          _external=True)
                    )
                    
                    mail.send(msg)
                except Exception as e:
                    logger.error(f"Błąd wysyłania emaila do {admin.email}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Błąd wysyłania powiadomień do adminów: {e}")
    
    @staticmethod
    def notify_user_new_response(ticket: Ticket):
        """
        Wysyła email do użytkownika o odpowiedzi admina
        
        Args:
            ticket: Obiekt ticketu
        """
        try:
            user = ticket.created_by
            if not user:
                return
            
            subject = f"[Ticket #{ticket.ticket_number}] Otrzymałeś odpowiedź"
            
            msg = Message(
                subject,
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[user.email]
            )
            
            msg.html = render_template(
                'issues/emails/new_response_user.html',
                ticket=ticket,
                user=user,
                ticket_url=url_for('issues.ticket_detail', 
                                  ticket_number=ticket.ticket_number, 
                                  _external=True)
            )
            
            mail.send(msg)
        
        except Exception as e:
            logger.error(f"Błąd wysyłania powiadomienia do użytkownika: {e}")