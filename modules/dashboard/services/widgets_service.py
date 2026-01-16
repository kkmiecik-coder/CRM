"""
Serwis do zarządzania widgetami dashboard
"""

def get_changelog_data():
    """
    Zwraca dane changelog (na razie statyczne, można przenieść do bazy)
    
    Returns:
        list: Lista wpisów changelog
    """
    changelog_entries = [
        {
            'date': '30.06.2025',
            'is_open': True,  # Pierwszy wpis domyślnie otwarty
            'sections': [
                {
                    'title': 'Dodano',
                    'items': ['Moduł logowań zdarzeń aplikacji']
                },
                {
                    'title': 'Naprawiono', 
                    'items': ['Poprawna wysyłka województwa do BL']
                }
            ]
        },
        {
            'date': '19.06.2025',
            'is_open': False,
            'sections': [
                {
                    'title': 'Zmieniono',
                    'items': [
                        'Sposób akceptacji wyceny - od teraz klient sam wpisuje dane do dostawy czy dane klienta',
                        'Okno szczegółów oraz edycji klienta zostały scalone w jedną opcję'
                    ]
                },
                {
                    'title': 'Naprawiono',
                    'items': [
                        'Okno edycji klientów - poprawnie wyświetla wyceny przypisane do klienta, przejście do nich.',
                        'Po wyborze OLX w trakcie zapisu wyceny nie jest wymagany mail, ani numer telefonu.'
                    ]
                }
            ]
        },
        {
            'date': '18.06.2025', 
            'is_open': False,
            'sections': [
                {
                    'title': 'Dodano',
                    'items': ['Możliwość wpisania własnego kuriera oraz kosztów podczas tworzenia wyceny']
                },
                {
                    'title': 'Zmieniono',
                    'items': [
                        'Podgląd podstawowych informacji w trakcie tworzenia wyceny',
                        'Wygląd formularza wyceny/wyboru kuriera'
                    ]
                },
                {
                    'title': 'Naprawiono',
                    'items': ['Wycena niekompletna sprawia wyłączenie przycisków zapisu lub wyceny wysyłki']
                }
            ]
        },
        {
            'date': '13.06.2025',
            'is_open': False, 
            'sections': [
                {
                    'title': 'Dodano',
                    'items': [
                        'Mozliwość edycji ilości produktów w wycenie',
                        'Widok cen oraz wartości wariantów', 
                        'Mozliwość zaakceptowania oferty przez handlowca po stronie szczegółów wyceny',
                        'Wyświetlanie ilości produktów na szczegółach wyceny oraz wysyłka informacji do baselinkera'
                    ]
                },
                {
                    'title': 'Naprawiono',
                    'items': [
                        'Ilość oraz kwoty produktów są teraz poprawnie przekazywane do zamówienia w Baselikerze',
                        'Błąd z wyświetlaniem ilości produktów w szczegółach wyceny',
                        'Kopiowanie grupy cenowej do nowych produktów',
                        'Zamówienie do BL nie wysyła już numeru wyceny do numeru wew. zam.'
                    ]
                }
            ]
        }
    ]
    
    return changelog_entries

def get_quick_shortcuts():
    """
    Zwraca listę szybkich skrótów dla dashboard
    
    Returns:
        list: Lista skrótów
    """
    shortcuts = [
        {
            'title': 'Nowa Wycena',
            'url': '/calculator/',
            'icon': 'calculator',
            'description': 'Stwórz nową wycenę dla klienta'
        },
        {
            'title': 'Lista Klientów', 
            'url': '/clients',
            'icon': 'users',
            'description': 'Zarządzaj bazą klientów'
        },
        {
            'title': 'Wszystkie Wyceny',
            'url': '/quotes',
            'icon': 'file-text',
            'description': 'Przeglądaj wszystkie wyceny'
        },
        {
            'title': 'Raporty',
            'url': '/reports',
            'icon': 'bar-chart',
            'description': 'Analiza sprzedaży i statystyki'
        },
        {
            'title': 'Ustawienia',
            'url': '/settings',
            'icon': 'settings',
            'description': 'Konfiguracja systemu'
        }
    ]
    
    return shortcuts

def get_system_status():
    """
    Sprawdza status różnych komponentów systemu
    
    Returns:
        dict: Status systemów
    """
    status = {
        'baselinker': {
            'status': 'ok',  # ok, warning, error
            'message': 'Połączenie aktywne',
            'last_sync': 'przed chwilą'
        },
        'email': {
            'status': 'ok',
            'message': 'Serwis dostępny',
            'last_sent': 'dziś o 14:30'
        }
    }
    
    return status