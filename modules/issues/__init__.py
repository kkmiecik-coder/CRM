# app/modules/issues/__init__.py
"""
Moduł Issues - System Ticketów
================================

System zgłoszeń błędów i pomocy technicznej z dwustronną komunikacją.

Features:
- Tworzenie ticketów przez użytkowników
- Dwustronna komunikacja (konwersacja)
- Załączniki (max 5 plików, max 5MB każdy)
- Powiadomienia email
- Panel Help Center
- Panel administratora

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

from flask import Blueprint
import os

# Określ ścieżkę do folderu modułu
_current_dir = os.path.dirname(os.path.abspath(__file__))

# Utworzenie blueprinta
issues_bp = Blueprint(
    'issues',
    __name__,
    template_folder=os.path.join(_current_dir, 'templates'),
    static_folder=os.path.join(_current_dir, 'static'),
    url_prefix='/issues'
)

# Import routes na końcu aby uniknąć circular imports
from . import routers

# Eksport modeli dla łatwego importu
from .models import Ticket, TicketMessage, TicketAttachment

__all__ = ['issues_bp', 'Ticket', 'TicketMessage', 'TicketAttachment']