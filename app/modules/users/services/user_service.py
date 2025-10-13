# app/modules/users/services/user_service.py
"""
Serwis zarządzania użytkownikami
=================================

Centralna logika biznesowa dla operacji na użytkownikach:
- Tworzenie, edycja, usuwanie użytkowników
- Zarządzanie profilami
- Zmiana haseł i avatarów

Autor: Konrad Kmiecik
Data: 2025-01-10
"""

from extensions import db
from ..models import User
from werkzeug.security import generate_password_hash
from typing import Optional, Dict, Any, List
from datetime import datetime


class UserService:
    """Serwis zarządzania użytkownikami"""
    
    @staticmethod
    def get_all_users(active_only: bool = False) -> List[User]:
        """
        Pobiera wszystkich użytkowników
        
        Args:
            active_only: Czy pobierać tylko aktywnych użytkowników
        
        Returns:
            List[User]: Lista użytkowników
        """
        query = User.query
        
        if active_only:
            query = query.filter_by(active=True)
        
        return query.order_by(User.created_at.desc()).all()
    
    @staticmethod
    def get_user_by_id(user_id: int) -> Optional[User]:
        """
        Pobiera użytkownika po ID
        
        Args:
            user_id: ID użytkownika
        
        Returns:
            User lub None
        """
        return User.query.get(user_id)
    
    @staticmethod
    def get_user_by_email(email: str) -> Optional[User]:
        """
        Pobiera użytkownika po emailu
        
        Args:
            email: Adres email
        
        Returns:
            User lub None
        """
        return User.query.filter_by(email=email).first()
    
    @staticmethod
    def create_user(email: str, password: str, first_name: str = None, 
                   last_name: str = None, role: str = 'user', 
                   multiplier_id: int = None) -> User:
        """
        Tworzy nowego użytkownika
        
        Args:
            email: Adres email
            password: Hasło (będzie zahashowane)
            first_name: Imię
            last_name: Nazwisko
            role: Rola użytkownika
            multiplier_id: ID mnożnika (dla partnerów)
        
        Returns:
            User: Utworzony użytkownik
        
        Raises:
            ValueError: Jeśli użytkownik o tym emailu już istnieje
        """
        # Sprawdź czy użytkownik już istnieje
        existing = UserService.get_user_by_email(email)
        if existing:
            raise ValueError(f"Użytkownik o emailu {email} już istnieje")
        
        # Utwórz użytkownika
        user = User(
            email=email,
            password=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            role=role,
            multiplier_id=multiplier_id,
            active=True
        )
        
        db.session.add(user)
        db.session.commit()
        
        return user
    
    @staticmethod
    def update_user(user_id: int, **kwargs) -> User:
        """
        Aktualizuje dane użytkownika
        
        Args:
            user_id: ID użytkownika
            **kwargs: Pola do aktualizacji
        
        Returns:
            User: Zaktualizowany użytkownik
        
        Raises:
            ValueError: Jeśli użytkownik nie istnieje
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        # Aktualizuj tylko dozwolone pola
        allowed_fields = ['first_name', 'last_name', 'email', 'role', 
                         'phone', 'avatar_path', 'multiplier_id']
        
        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(user, key):
                setattr(user, key, value)
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return user
    
    @staticmethod
    def update_password(user_id: int, old_password: str, new_password: str) -> bool:
        """
        Zmienia hasło użytkownika
        
        Args:
            user_id: ID użytkownika
            old_password: Stare hasło (do weryfikacji)
            new_password: Nowe hasło
        
        Returns:
            bool: True jeśli hasło zostało zmienione
        
        Raises:
            ValueError: Jeśli stare hasło jest nieprawidłowe
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        # Sprawdź stare hasło
        if not user.check_password(old_password):
            raise ValueError("Nieprawidłowe obecne hasło")
        
        # Ustaw nowe hasło
        user.set_password(new_password)
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return True
    
    @staticmethod
    def update_avatar(user_id: int, avatar_path: str) -> User:
        """
        Aktualizuje avatar użytkownika
        
        Args:
            user_id: ID użytkownika
            avatar_path: Ścieżka do nowego avatara
        
        Returns:
            User: Zaktualizowany użytkownik
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        user.avatar_path = avatar_path
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return user
    
    @staticmethod
    def activate_user(user_id: int) -> User:
        """
        Aktywuje użytkownika
        
        Args:
            user_id: ID użytkownika
        
        Returns:
            User: Zaktualizowany użytkownik
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        user.active = True
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return user
    
    @staticmethod
    def deactivate_user(user_id: int) -> User:
        """
        Dezaktywuje użytkownika
        
        Args:
            user_id: ID użytkownika
        
        Returns:
            User: Zaktualizowany użytkownik
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        user.active = False
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return user
    
    @staticmethod
    def delete_user(user_id: int, force: bool = False) -> bool:
        """
        Usuwa użytkownika
        
        Args:
            user_id: ID użytkownika
            force: Czy wymusić usunięcie (nawet admin)
        
        Returns:
            bool: True jeśli użytkownik został usunięty
        
        Raises:
            ValueError: Jeśli próba usunięcia admina bez force
        """
        user = UserService.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"Użytkownik o ID {user_id} nie istnieje")
        
        # Zabezpieczenie - nie usuwaj admina bez force
        if user.is_admin() and not force:
            raise ValueError("Nie można usunąć administratora bez parametru force=True")
        
        db.session.delete(user)
        db.session.commit()
        
        return True