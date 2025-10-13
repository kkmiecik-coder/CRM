# app/modules/users/decorators/access_control.py
"""
Dekorator kontroli dostępu
===========================

Jeden uniwersalny dekorator @access_control do kontroli dostępu w całej aplikacji.
Przygotowany na przyszłe rozszerzenie o system uprawnień (Faza 2).

Użycie:
    @access_control(roles=['admin'])
    @access_control(roles=['admin', 'user'])
    @access_control(roles=['admin'], redirect_to='dashboard.dashboard')

Autor: Konrad Kmiecik
Data: 2025-01-10
"""

from functools import wraps
from flask import session, flash, redirect, url_for, request, abort
from typing import List, Optional


def access_control(roles: Optional[List[str]] = None, 
                   redirect_to: str = 'dashboard.dashboard',
                   allow_all: bool = False):
    """
    Uniwersalny dekorator kontroli dostępu
    
    Args:
        roles: Lista dozwolonych ról (np. ['admin', 'user'])
        redirect_to: Endpoint do przekierowania przy braku dostępu
        allow_all: Jeśli True, pozwala wszystkim zalogowanym użytkownikom
    
    Usage:
        # Tylko admin
        @access_control(roles=['admin'])
        def admin_function():
            ...
        
        # Admin lub user
        @access_control(roles=['admin', 'user'])
        def user_function():
            ...
        
        # Wszyscy zalogowani
        @access_control(allow_all=True)
        def logged_in_function():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Sprawdź czy użytkownik jest zalogowany
            user_email = session.get('user_email')
            if not user_email:
                flash("Twoja sesja wygasła. Zaloguj się ponownie.", "error")
                return redirect(url_for('login'))
            
            # Import User lokalnie aby uniknąć circular imports
            from ..models import User
            
            user = User.query.filter_by(email=user_email).first()
            if not user:
                flash("Użytkownik nie istnieje.", "error")
                return redirect(url_for('login'))
            
            # Sprawdź czy konto jest aktywne
            if not user.is_active():
                flash("Twoje konto zostało dezaktywowane.", "error")
                session.clear()
                return redirect(url_for('login'))
            
            # Jeśli allow_all=True, każdy zalogowany użytkownik ma dostęp
            if allow_all:
                return func(*args, **kwargs)
            
            # Jeśli nie podano ról, domyślnie wymagamy admin
            if roles is None:
                required_roles = ['admin']
            else:
                required_roles = roles
            
            # Sprawdź czy użytkownik ma odpowiednią rolę
            user_role = user.role.lower() if user.role else None
            
            if user_role not in [r.lower() for r in required_roles]:
                flash(f"Nie masz uprawnień do tej funkcji. Wymagana rola: {', '.join(required_roles)}", "error")
                return redirect(url_for(redirect_to))
            
            # Dostęp przyznany
            return func(*args, **kwargs)
        
        return wrapper
    return decorator