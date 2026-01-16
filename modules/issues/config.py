# app/modules/issues/config.py
"""
Konfiguracja modułu ticketów

Zawiera:
- Kategorie i podkategorie
- Statusy i priorytety
- Limity i walidacje
- Linki do pomocy (placeholders)

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

# ============================================================================
# KATEGORIE I PODKATEGORIE
# ============================================================================

TICKET_CATEGORIES = {
    'crm': {
        'name': 'CRM',
        'icon': '🧮',
        'description': 'Kalkulator, wyceny, zamówienia',
        'subcategories': {
            'calculator': 'Kalkulator',
            'quotes': 'Wyceny',
            'clients': 'Klienci',
            'production': 'Produkcja',
            'users': 'Użytkownicy',
            'dashboard': 'Dashboard',
            'other': 'Inne'
        }
    },
    'baselinker': {
        'name': 'Baselinker',
        'icon': '📦',
        'description': 'Synchronizacja, produkty, zamówienia',
        'subcategories': {
            'orders': 'Zamówienia',
            'sync': 'Synchronizacja',
            'products': 'Produkty',
            'inventory': 'Magazyn',
            'other': 'Inne'
        }
    },
    'responso': {
        'name': 'Responso',
        'icon': '💬',
        'description': 'Komunikacja z klientem na wielu kanałach',
        'subcategories': {
            'templates': 'Szablony',
            'automation': 'Automatyzacja',
            'integration': 'Integracja',
            'other': 'Inne'
        }
    },
    'strona_www': {
        'name': 'Strona WWW',
        'icon': '🌐',
        'description': 'Sklep internetowy',
        'subcategories': {
            'display': 'Wyświetlanie',
            'forms': 'Formularze',
            'products': 'Produkty',
            'performance': 'Wydajność',
            'other': 'Inne'
        }
    },
    'inne': {
        'name': 'Inne',
        'icon': '❓',
        'description': 'Wszystkie inne tematy',
        'subcategories': {
            'general': 'Ogólne',
            'feature_request': 'Prośba o funkcję',
            'question': 'Pytanie'
        }
    }
}


# ============================================================================
# STATUSY TICKETÓW
# ============================================================================

TICKET_STATUSES = {
    'new': {
        'name': 'Nowy',
        'color': '#4CAF50',
        'icon': '🟢',
        'description': 'Ticket właśnie utworzony, czeka na przejrzenie'
    },
    'open': {
        'name': 'Otwarty',
        'color': '#FFC107',
        'icon': '🟡',
        'description': 'Ticket przejrzany przez admina, w trakcie analizy'
    },
    'in_progress': {
        'name': 'W trakcie realizacji',
        'color': '#2196F3',
        'icon': '🔵',
        'description': 'Ticket jest aktualnie rozwiązywany'
    },
    'closed': {
        'name': 'Zamknięty',
        'color': '#9E9E9E',
        'icon': '✅',
        'description': 'Problem został rozwiązany'
    },
    'cancelled': {
        'name': 'Anulowany',
        'color': '#F44336',
        'icon': '❌',
        'description': 'Ticket anulowany'
    }
}


# ============================================================================
# PRIORYTETY TICKETÓW
# ============================================================================

TICKET_PRIORITIES = {
    'low': {
        'name': 'Niski',
        'color': '#8BC34A',
        'icon': '🟢',
        'sort_order': 1
    },
    'medium': {
        'name': 'Średni',
        'color': '#FFC107',
        'icon': '🟡',
        'sort_order': 2
    },
    'high': {
        'name': 'Wysoki',
        'color': '#FF9800',
        'icon': '🟠',
        'sort_order': 3
    },
    'critical': {
        'name': 'Krytyczny',
        'color': '#F44336',
        'icon': '🔴',
        'sort_order': 4
    }
}


# ============================================================================
# LIMITY I WALIDACJE
# ============================================================================

# Załączniki
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB w bajtach
MAX_ATTACHMENTS_PER_MESSAGE = 5

# Walidacje tekstu
MIN_TITLE_LENGTH = 5
MAX_TITLE_LENGTH = 255
MIN_MESSAGE_LENGTH = 10


# ============================================================================
# LINKI DO POMOCY (PLACEHOLDERS)
# ============================================================================

HELP_LINKS = [
    {
        'title': '[Placeholder 1] Jak stworzyć wycenę?',
        'url': '/help/jak-stworzyc-wycene',
        'icon': '📝'
    },
    {
        'title': '[Placeholder 2] Synchronizacja z Baselinker',
        'url': '/help/synchronizacja-baselinker',
        'icon': '🔄'
    },
    {
        'title': '[Placeholder 3] Zarządzanie użytkownikami',
        'url': '/help/zarzadzanie-uzytkownikami',
        'icon': '👥'
    },
    {
        'title': '[Placeholder 4] Problem z produkcją',
        'url': '/help/problem-z-produkcja',
        'icon': '🏭'
    },
    {
        'title': '[Placeholder 5] Raporty i statystyki',
        'url': '/help/raporty-i-statystyki',
        'icon': '📊'
    }
]