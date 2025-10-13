# app/modules/users/decorators/permission_required.py
"""
Dekorator sprawdzania dostępu do modułów
=========================================

Nowy dekorator @require_module_access() używający systemu uprawnień.

Usage:
    @require_module_access('quotes')
    def quotes_dashboard():
        ...
    
    @require_module_access('users')
    def manage_team():
        ...

Autor: Konrad Kmiecik + Claude AI
Data: 2025-01-13
"""

from functools import wraps
from flask import session, flash, redirect, url_for, current_app, render_template
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def require_module_access(module_key: str, redirect_to: str = 'dashboard.dashboard'):
    """
    Dekorator sprawdzający dostęp do modułu
    
    Sprawdza czy zalogowany użytkownik ma dostęp do określonego modułu
    używając PermissionService.
    
    Args:
        module_key (str): Klucz modułu (np. 'quotes', 'production', 'users')
        redirect_to (str): Endpoint do przekierowania przy braku dostępu (opcjonalnie)
    
    Returns:
        Funkcja dekoratora
    
    Examples:
        >>> @require_module_access('quotes')
        ... def quotes_dashboard():
        ...     return "Quotes Dashboard"
        
        >>> @require_module_access('users')
        ... def manage_team():
        ...     return "Team Management"
    
    Raises:
        Redirect: Przekierowanie na stronę access_denied lub login
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 1. Sprawdź czy użytkownik jest zalogowany
            user_email = session.get('user_email')
            
            if not user_email:
                logger.warning(f"Próba dostępu do modułu '{module_key}' bez zalogowania")
                flash("Twoja sesja wygasła. Zaloguj się ponownie.", "error")
                return redirect(url_for('login'))
            
            # 2. Pobierz użytkownika z bazy
            # Import lokalnie aby uniknąć circular imports
            from ..models import User, Module
            
            user = User.query.filter_by(email=user_email).first()
            
            if not user:
                logger.error(f"Użytkownik {user_email} nie istnieje w bazie")
                flash("Użytkownik nie istnieje.", "error")
                session.clear()
                return redirect(url_for('login'))
            
            # 3. Sprawdź czy konto jest aktywne
            if not user.is_active():
                logger.warning(f"Próba dostępu użytkownika {user.email} (ID: {user.id}) - konto nieaktywne")
                flash("Twoje konto zostało dezaktywowane. Skontaktuj się z administratorem.", "error")
                session.clear()
                return redirect(url_for('login'))
            
            # 4. Sprawdź dostęp do modułu
            from ..services.permission_service import PermissionService
            
            has_access = PermissionService.user_has_module_access(user.id, module_key)
            
            if not has_access:
                logger.warning(
                    f"User {user.email} (ID: {user.id}) próbował uzyskać dostęp do modułu '{module_key}' "
                    f"- BRAK UPRAWNIEŃ"
                )
                
                # Pobierz nazwę modułu dla lepszej informacji
                module = Module.query.filter_by(module_key=module_key).first()
                module_name = module.display_name if module else module_key.title()
                
                # Przekieruj na dedykowaną stronę access_denied
                return render_template(
                    'access_denied.html',
                    module_name=module_name,
                    module_key=module_key,
                    user_email=user.email,
                    redirect_url=url_for(redirect_to)
                ), 403
            
            # 5. Dostęp przyznany - wykonaj funkcję
            logger.info(f"User {user.email} (ID: {user.id}) uzyskał dostęp do modułu '{module_key}'")
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_any_module_access(*module_keys: str, redirect_to: str = 'dashboard.dashboard'):
    """
    Dekorator sprawdzający dostęp do KTÓREGOKOLWIEK z modułów
    
    Użytkownik musi mieć dostęp do przynajmniej jednego z podanych modułów.
    
    Args:
        *module_keys: Lista kluczy modułów (np. 'quotes', 'production')
        redirect_to: Endpoint do przekierowania przy braku dostępu
    
    Examples:
        >>> @require_any_module_access('quotes', 'production')
        ... def reports_dashboard():
        ...     # Dostępne dla użytkowników mających quotes LUB production
        ...     return "Reports"
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_email = session.get('user_email')
            
            if not user_email:
                flash("Twoja sesja wygasła. Zaloguj się ponownie.", "error")
                return redirect(url_for('login'))
            
            from ..models import User
            user = User.query.filter_by(email=user_email).first()
            
            if not user or not user.is_active():
                flash("Brak dostępu.", "error")
                return redirect(url_for('login'))
            
            from ..services.permission_service import PermissionService
            
            # Sprawdź czy użytkownik ma dostęp do któregokolwiek modułu
            has_any_access = any(
                PermissionService.user_has_module_access(user.id, mk)
                for mk in module_keys
            )
            
            if not has_any_access:
                logger.warning(
                    f"User {user.email} (ID: {user.id}) próbował uzyskać dostęp "
                    f"- wymaga któregoś z modułów: {module_keys}"
                )
                
                return render_template(
                    'access_denied.html',
                    module_name=f"jeden z: {', '.join(module_keys)}",
                    user_email=user.email,
                    redirect_url=url_for(redirect_to)
                ), 403
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_all_modules_access(*module_keys: str, redirect_to: str = 'dashboard.dashboard'):
    """
    Dekorator sprawdzający dostęp do WSZYSTKICH podanych modułów
    
    Użytkownik musi mieć dostęp do każdego z podanych modułów.
    
    Args:
        *module_keys: Lista kluczy modułów (np. 'quotes', 'production')
        redirect_to: Endpoint do przekierowania przy braku dostępu
    
    Examples:
        >>> @require_all_modules_access('quotes', 'production')
        ... def advanced_reports():
        ...     # Dostępne TYLKO dla użytkowników mających quotes AND production
        ...     return "Advanced Reports"
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_email = session.get('user_email')
            
            if not user_email:
                flash("Twoja sesja wygasła. Zaloguj się ponownie.", "error")
                return redirect(url_for('login'))
            
            from ..models import User
            user = User.query.filter_by(email=user_email).first()
            
            if not user or not user.is_active():
                flash("Brak dostępu.", "error")
                return redirect(url_for('login'))
            
            from ..services.permission_service import PermissionService
            
            # Sprawdź czy użytkownik ma dostęp do wszystkich modułów
            has_all_access = all(
                PermissionService.user_has_module_access(user.id, mk)
                for mk in module_keys
            )
            
            if not has_all_access:
                logger.warning(
                    f"User {user.email} (ID: {user.id}) próbował uzyskać dostęp "
                    f"- wymaga wszystkich modułów: {module_keys}"
                )
                
                return render_template(
                    'access_denied.html',
                    module_name=f"wszystkie: {', '.join(module_keys)}",
                    user_email=user.email,
                    redirect_url=url_for(redirect_to)
                ), 403
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator