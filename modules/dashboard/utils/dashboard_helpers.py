"""
Funkcje pomocnicze dla dashboard
"""

from datetime import datetime, timedelta

def format_currency(amount):
    """
    Formatuje kwotę w walucie PLN
    
    Args:
        amount (float): Kwota do formatowania
        
    Returns:
        str: Sformatowana kwota
    """
    if amount is None:
        return "0,00 zł"
    
    try:
        return f"{amount:,.0f} zł".replace(",", " ")
    except:
        return "0 zł"

def format_percentage(value, total):
    """
    Oblicza i formatuje procent
    
    Args:
        value (int): Wartość
        total (int): Całość
        
    Returns:
        str: Sformatowany procent
    """
    if total == 0:
        return "0%"
    
    try:
        percentage = (value / total) * 100
        return f"{percentage:.1f}%"
    except:
        return "0%"

def get_date_ranges():
    """
    Zwraca przydatne zakresy dat
    
    Returns:
        dict: Słownik z datami
    """
    today = datetime.now().date()
    
    return {
        'today': today,
        'yesterday': today - timedelta(days=1),
        'week_start': today - timedelta(days=today.weekday()),
        'month_start': today.replace(day=1),
        'year_start': today.replace(month=1, day=1),
        'last_30_days': today - timedelta(days=30)
    }

def get_greeting_for_user(user):
    """
    Generuje spersonalizowane powitanie dla użytkownika
    
    Args:
        user: Obiekt użytkownika
        
    Returns:
        str: Spersonalizowane powitanie
    """
    current_hour = datetime.now().hour
    
    if current_hour < 12:
        greeting = "Dzień dobry"
    elif current_hour < 17:
        greeting = "Dzień dobry"
    else:
        greeting = "Dobry wieczór"
    
    if user and (user.first_name or user.last_name):
        name = f"{user.first_name} {user.last_name}".strip()
        return f"{greeting}, {name}! 👋"
    else:
        return f"{greeting}! 👋"

def calculate_growth_percentage(current, previous):
    """
    Oblicza procent wzrostu/spadku między dwiema wartościami
    
    Args:
        current (float): Aktualna wartość
        previous (float): Poprzednia wartość
        
    Returns:
        dict: Słownik z procentem i kierunkiem zmiany
    """
    if previous == 0:
        if current > 0:
            return {'percentage': 100, 'direction': 'up', 'formatted': '+100%'}
        else:
            return {'percentage': 0, 'direction': 'neutral', 'formatted': '0%'}
    
    try:
        percentage = ((current - previous) / previous) * 100
        
        if percentage > 0:
            return {
                'percentage': round(percentage, 1),
                'direction': 'up',
                'formatted': f'+{percentage:.1f}%'
            }
        elif percentage < 0:
            return {
                'percentage': round(abs(percentage), 1),
                'direction': 'down', 
                'formatted': f'-{abs(percentage):.1f}%'
            }
        else:
            return {
                'percentage': 0,
                'direction': 'neutral',
                'formatted': '0%'
            }
    except:
        return {'percentage': 0, 'direction': 'neutral', 'formatted': '0%'}

def truncate_text(text, max_length=50):
    """
    Skraca tekst do określonej długości
    
    Args:
        text (str): Tekst do skrócenia
        max_length (int): Maksymalna długość
        
    Returns:
        str: Skrócony tekst
    """
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length-3] + "..."

def get_status_color(status_name):
    """
    Zwraca kolor dla statusu
    
    Args:
        status_name (str): Nazwa statusu
        
    Returns:
        str: Kod koloru hex
    """
    status_colors = {
        'pending': '#FF9800',    # Pomarańczowy
        'accepted': '#4CAF50',   # Zielony
        'rejected': '#F44336',   # Czerwony
        'draft': '#9E9E9E',      # Szary
        'sent': '#2196F3',       # Niebieski
        'expired': '#795548'     # Brązowy
    }
    
    return status_colors.get(status_name.lower(), '#333333')