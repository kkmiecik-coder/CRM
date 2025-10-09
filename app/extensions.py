# extensions.py
"""
Extensions dla aplikacji Flask
==============================

Centralna inicjalizacja wszystkich rozszerzeń Flask.
Naprawia błąd: AttributeError: 'Flask' object has no attribute 'login_manager'

Rozszerzenia:
- SQLAlchemy (db)
- Flask-Mail (mail) 
- Flask-Login (login_manager)

Autor: Konrad Kmiecik
Data: 2025-09-10
"""

from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_login import LoginManager

# ============================================================================
# INICJALIZACJA ROZSZERZEŃ
# ============================================================================

# Baza danych
db = SQLAlchemy()

# Obsługa emaili
mail = Mail()

# Zarządzanie sesjami użytkowników
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Wymagane logowanie aby uzyskać dostęp do tej strony.'
login_manager.login_message_category = 'info'

# ============================================================================
# KONFIGURACJA LOGIN MANAGERA
# ============================================================================

@login_manager.user_loader
def load_user(user_id):
    """
    Callback wymagany przez Flask-Login do ładowania użytkownika
    
    Args:
        user_id (str): ID użytkownika z sesji Flask-Login
        
    Returns:
        User: Obiekt użytkownika lub None
    """
    try:
        # Import lokalny aby uniknąć circular imports
        from modules.calculator.models import User
        user = User.query.get(int(user_id))
        
        # Dodatkowa walidacja - sprawdź czy konto jest aktywne
        if user and not user.is_active():
            return None
            
        return user
    except (ValueError, AttributeError, TypeError) as e:
        # Loguj błąd ale nie crashuj aplikacji
        print(f"[LoginManager] Błąd ładowania użytkownika {user_id}: {e}")
        return None

def init_extensions(app):
    """
    Inicjalizuje wszystkie rozszerzenia z aplikacją Flask
    
    Args:
        app: Instancja aplikacji Flask
    """
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    
    # Dodatkowa konfiguracja dla developmentu
    if app.config.get('DEBUG'):
        app.logger.info("Extensions zainicjalizowane w trybie DEBUG")
    
    app.logger.info("✅ Wszystkie rozszerzenia zainicjalizowane poprawnie")