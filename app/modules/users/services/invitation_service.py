# app/modules/users/services/invitation_service.py
"""
Serwis zarządzania zaproszeniami
=================================

Logika biznesowa dla zaproszeń użytkowników:
- Tworzenie zaproszeń
- Wysyłanie emaili z tokenem
- Akceptacja zaproszeń
- Zarządzanie tokenami

Autor: Konrad Kmiecik
Data: 2025-01-10
"""

from extensions import db, mail
from ..models import Invitation, User
from flask import url_for, render_template, current_app
from flask_mail import Message
from typing import Optional, List
from datetime import datetime, timedelta
import secrets


class InvitationService:
    """Serwis zarządzania zaproszeniami"""
    
    @staticmethod
    def create_invitation(email: str, role: str = 'user', 
                         multiplier_id: int = None, 
                         expires_days: int = 7) -> Invitation:
        """
        Tworzy zaproszenie dla nowego użytkownika
        
        Args:
            email: Adres email
            role: Rola użytkownika
            multiplier_id: ID mnożnika (dla partnerów)
            expires_days: Ile dni token jest ważny
        
        Returns:
            Invitation: Utworzone zaproszenie
        
        Raises:
            ValueError: Jeśli użytkownik już istnieje lub zaproszenie jest aktywne
        """
        # Sprawdź czy użytkownik już istnieje
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            raise ValueError(f"Użytkownik o emailu {email} już istnieje")
        
        # Sprawdź czy jest aktywne zaproszenie
        existing_invitation = Invitation.query.filter_by(email=email, active=True).first()
        if existing_invitation:
            raise ValueError(f"Aktywne zaproszenie dla {email} już istnieje")
        
        # Generuj bezpieczny token
        token = secrets.token_urlsafe(32)
        
        # Ustaw datę wygaśnięcia
        expires_at = datetime.utcnow() + timedelta(days=expires_days)
        
        # Utwórz zaproszenie
        invitation = Invitation(
            email=email,
            token=token,
            role=role,
            multiplier_id=multiplier_id,
            active=True,
            expires_at=expires_at
        )
        
        db.session.add(invitation)
        db.session.commit()
        
        return invitation
    
    @staticmethod
    def send_invitation_email(invitation: Invitation) -> bool:
        """
        Wysyła email z zaproszeniem
        
        Args:
            invitation: Obiekt zaproszenia
        
        Returns:
            bool: True jeśli email został wysłany
        """
        try:
            # Generuj link do akceptacji zaproszenia
            invitation_link = url_for('accept_invitation', 
                                     token=invitation.token, 
                                     _external=True)
            
            # Przygotuj wiadomość
            subject = "Zaproszenie do CRM WoodPower"
            
            msg = Message(
                subject,
                sender=current_app.config.get("MAIL_USERNAME"),
                recipients=[invitation.email]
            )
            
            # Renderuj szablon HTML
            msg.html = render_template(
                "new_account_register_mail.html",
                invitation_link=invitation_link
            )
            
            # Wyślij email
            mail.send(msg)
            
            return True
            
        except Exception as e:
            current_app.logger.error(f"Błąd wysyłania zaproszenia: {str(e)}")
            return False
    
    @staticmethod
    def get_invitation_by_token(token: str) -> Optional[Invitation]:
        """
        Pobiera zaproszenie po tokenie
        
        Args:
            token: Token zaproszenia
        
        Returns:
            Invitation lub None
        """
        return Invitation.query.filter_by(token=token, active=True).first()
    
    @staticmethod
    def validate_invitation(token: str) -> tuple[bool, str]:
        """
        Waliduje zaproszenie
        
        Args:
            token: Token zaproszenia
        
        Returns:
            tuple[bool, str]: (czy_valid, komunikat_błędu)
        """
        invitation = InvitationService.get_invitation_by_token(token)
        
        if not invitation:
            return False, "Zaproszenie jest nieprawidłowe lub nieaktywne"
        
        # Sprawdź czy nie wygasło
        if invitation.expires_at and invitation.expires_at < datetime.utcnow():
            invitation.active = False
            db.session.commit()
            return False, "Zaproszenie wygasło"
        
        # Sprawdź czy użytkownik już nie istnieje
        existing_user = User.query.filter_by(email=invitation.email).first()
        if existing_user:
            invitation.active = False
            db.session.commit()
            return False, "Konto z tym e-mailem już istnieje"
        
        return True, ""
    
    @staticmethod
    def accept_invitation(token: str, password: str, 
                         first_name: str = None, 
                         last_name: str = None,
                         avatar_path: str = None) -> User:
        """
        Akceptuje zaproszenie i tworzy konto użytkownika
        
        Args:
            token: Token zaproszenia
            password: Hasło użytkownika
            first_name: Imię
            last_name: Nazwisko
            avatar_path: Ścieżka do avatara
        
        Returns:
            User: Utworzony użytkownik
        
        Raises:
            ValueError: Jeśli zaproszenie jest nieprawidłowe
        """
        # Walidacja zaproszenia
        is_valid, error_msg = InvitationService.validate_invitation(token)
        if not is_valid:
            raise ValueError(error_msg)
        
        invitation = InvitationService.get_invitation_by_token(token)
        
        # Utwórz użytkownika
        from .user_service import UserService
        
        user = UserService.create_user(
            email=invitation.email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=invitation.role if invitation.role else 'user',
            multiplier_id=invitation.multiplier_id
        )
        
        # Ustaw avatar jeśli podano
        if avatar_path:
            user.avatar_path = avatar_path
            db.session.commit()
        
        # Dezaktywuj zaproszenie
        invitation.active = False
        db.session.commit()
        
        return user
    
    @staticmethod
    def get_all_invitations(active_only: bool = True) -> List[Invitation]:
        """
        Pobiera wszystkie zaproszenia
        
        Args:
            active_only: Czy tylko aktywne zaproszenia
        
        Returns:
            List[Invitation]: Lista zaproszeń
        """
        query = Invitation.query
        
        if active_only:
            query = query.filter_by(active=True)
        
        return query.order_by(Invitation.created_at.desc()).all()
    
    @staticmethod
    def cancel_invitation(invitation_id: int) -> bool:
        """
        Anuluje zaproszenie
        
        Args:
            invitation_id: ID zaproszenia
        
        Returns:
            bool: True jeśli zaproszenie zostało anulowane
        """
        invitation = Invitation.query.get(invitation_id)
        if not invitation:
            raise ValueError(f"Zaproszenie o ID {invitation_id} nie istnieje")
        
        invitation.active = False
        db.session.commit()
        
        return True
    
    @staticmethod
    def delete_invitation(invitation_id: int) -> bool:
        """
        Usuwa zaproszenie
        
        Args:
            invitation_id: ID zaproszenia
        
        Returns:
            bool: True jeśli zaproszenie zostało usunięte
        """
        invitation = Invitation.query.get(invitation_id)
        if not invitation:
            raise ValueError(f"Zaproszenie o ID {invitation_id} nie istnieje")
        
        db.session.delete(invitation)
        db.session.commit()
        
        return True