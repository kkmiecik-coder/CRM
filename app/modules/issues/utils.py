# app/modules/issues/utils.py
"""
Funkcje pomocnicze modułu ticketów

Funkcje:
- generate_ticket_number(): Generowanie unikalnego ID ticketu
- format_file_size(): Formatowanie rozmiaru pliku
- get_status_info(): Pobieranie informacji o statusie
- get_priority_info(): Pobieranie informacji o priorytecie
- get_category_info(): Pobieranie informacji o kategorii

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

import secrets
import string
from .models import Ticket


def generate_ticket_number() -> str:
    """
    Generuje unikalny 8-znakowy ID ticketu (duże litery + cyfry)
    
    Returns:
        str: Unikalny numer ticketu (np. "A4G8Y4A6")
    
    Raises:
        RuntimeError: Jeśli nie można wygenerować unikalnego ID po 100 próbach
    """
    chars = string.ascii_uppercase + string.digits
    max_attempts = 100
    
    for _ in range(max_attempts):
        ticket_number = ''.join(secrets.choice(chars) for _ in range(8))
        
        # Sprawdź czy ID jest unikalne
        if not Ticket.query.filter_by(ticket_number=ticket_number).first():
            return ticket_number
    
    # Jeśli po 100 próbach nie znaleziono unikalnego ID
    raise RuntimeError("Nie można wygenerować unikalnego ID ticketu")


def format_file_size(size_bytes: int) -> str:
    """
    Formatuje rozmiar pliku do czytelnej postaci
    
    Args:
        size_bytes: Rozmiar w bajtach
    
    Returns:
        str: Sformatowany rozmiar (np. "2.5 MB", "345 KB")
    
    Examples:
        >>> format_file_size(1024)
        '1.0 KB'
        >>> format_file_size(1536000)
        '1.46 MB'
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def get_status_info(status: str) -> dict:
    """
    Pobiera informacje o statusie ticketu
    
    Args:
        status: Klucz statusu (new, open, in_progress, closed, cancelled)
    
    Returns:
        dict: Informacje o statusie (name, color, icon, description)
    
    Examples:
        >>> get_status_info('new')
        {'name': 'Nowy', 'color': '#4CAF50', 'icon': '🟢', ...}
    """
    from .config import TICKET_STATUSES
    return TICKET_STATUSES.get(status, {
        'name': 'Nieznany',
        'color': '#000000',
        'icon': '❓',
        'description': 'Nieznany status'
    })


def get_priority_info(priority: str) -> dict:
    """
    Pobiera informacje o priorytecie ticketu
    
    Args:
        priority: Klucz priorytetu (low, medium, high, critical)
    
    Returns:
        dict: Informacje o priorytecie (name, color, icon, sort_order)
    
    Examples:
        >>> get_priority_info('high')
        {'name': 'Wysoki', 'color': '#FF9800', 'icon': '🟠', ...}
    """
    from .config import TICKET_PRIORITIES
    return TICKET_PRIORITIES.get(priority, {
        'name': 'Nieznany',
        'color': '#000000',
        'icon': '❓',
        'sort_order': 0
    })


def get_category_info(category: str) -> dict:
    """
    Pobiera informacje o kategorii
    
    Args:
        category: Klucz kategorii (crm, baselinker, responso, strona_www, inne)
    
    Returns:
        dict: Informacje o kategorii (name, icon, subcategories)
    
    Examples:
        >>> get_category_info('crm')
        {'name': 'CRM', 'icon': '🧮', 'subcategories': {...}}
    """
    from .config import TICKET_CATEGORIES
    return TICKET_CATEGORIES.get(category, {
        'name': 'Nieznana',
        'icon': '❓',
        'subcategories': {}
    })