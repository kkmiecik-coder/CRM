# app/modules/users/__init__.py
from flask import Blueprint
import os

# Określ ścieżkę do folderu modułu
_current_dir = os.path.dirname(os.path.abspath(__file__))

# Utworzenie blueprinta
users_bp = Blueprint(
    'users',
    __name__,
    template_folder=os.path.join(_current_dir, 'templates'),  # ← ABSOLUTNA ŚCIEŻKA
    static_folder=os.path.join(_current_dir, 'static'),
    url_prefix='/users'
)

# Import routes na końcu aby uniknąć circular imports
from . import routes

# Eksport modeli dla łatwego importu
from .models import User, Invitation

__all__ = ['users_bp', 'User', 'Invitation']