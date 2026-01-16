# app/modules/sales/utils.py
"""
Sales Utils
===========

Funkcje pomocnicze dla modułu Sales.

Utils:
- generate_nda_pdf: Generowanie PDF z umową NDA
- rate_limit: Dekorator rate limiting

Autor: Development Team
Data: 2025-10-24
"""

from functools import wraps
from flask import request, jsonify
from datetime import datetime, timedelta
import io


# ============================================================================
# RATE LIMITING
# ============================================================================

# Prosta implementacja rate limiting w pamięci
_rate_limit_storage = {}

def rate_limit(max_requests=5, window=60):
    """
    Dekorator rate limiting
    
    Args:
        max_requests (int): Maksymalna liczba requestów
        window (int): Okno czasowe w sekundach
    
    Usage:
        @rate_limit(max_requests=10, window=60)
        def my_endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Identyfikator klienta (IP)
            client_id = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_id and ',' in client_id:
                client_id = client_id.split(',')[0].strip()
            
            # Klucz w storage
            key = f"{f.__name__}:{client_id}"
            now = datetime.now()
            
            # Inicjalizacja jeśli brak
            if key not in _rate_limit_storage:
                _rate_limit_storage[key] = []
            
            # Usuń stare requesty spoza okna
            _rate_limit_storage[key] = [
                timestamp for timestamp in _rate_limit_storage[key]
                if now - timestamp < timedelta(seconds=window)
            ]
            
            # Sprawdź limit
            if len(_rate_limit_storage[key]) >= max_requests:
                return jsonify({
                    'success': False,
                    'error': 'Zbyt wiele requestów. Spróbuj ponownie za chwilę.'
                }), 429
            
            # Dodaj nowy request
            _rate_limit_storage[key].append(now)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============================================================================
# NDA PDF GENERATION
# ============================================================================

def generate_nda_pdf(data):
    """
    Generuj PDF z NDA używając WeasyPrint i HTML template
    
    Args:
        data (dict): Dane z formularza zawierające:
            Dane osobowe:
            - first_name, last_name, email, phone
            - city, address (adres), postal_code
            
            Dane B2B (opcjonalnie):
            - cooperation_type: 'b2b' lub 'contract'
            - company_name, nip, regon
            - company_address, company_city, company_postal_code
            
    Returns:
        bytes: PDF jako surowe bajty
        
    Raises:
        Exception: Gdy WeasyPrint nie jest zainstalowany lub wystąpi błąd generowania
    
    Example:
        >>> data = {
        ...     'first_name': 'Jan',
        ...     'last_name': 'Kowalski',
        ...     'email': 'jan@example.com',
        ...     'city': 'Warszawa',
        ...     'address': 'ul. Przykładowa 10',
        ...     'postal_code': '00-001',
        ...     'cooperation_type': 'contract'
        ... }
        >>> pdf_bytes = generate_nda_pdf(data)
    """
    try:
        from weasyprint import HTML
        from flask import render_template, current_app
        import os
        
        # Dodaj bieżącą datę do danych
        data['current_date'] = datetime.now().strftime('%d.%m.%Y')
        
        # Sprawdź czy to B2B
        is_b2b = data.get('cooperation_type') == 'b2b'
        data['is_b2b_bool'] = is_b2b
                
        # Przygotuj ścieżki do obrazów (bezwzględne, rzeczywiste ścieżki na dysku)
        app_root = os.path.abspath(current_app.root_path)
        
        # Ścieżki do logo i podpisu
        logo_path = os.path.abspath(
            os.path.join(app_root, 'static', 'images', 'logo.png')
        )
        sign_path = os.path.abspath(
            os.path.join(
                app_root, 
                'modules', 
                'sales', 
                'static', 
                'media', 
                'images', 
                'sign.png'
            )
        )
        
        # Jeśli pliki nie istnieją, użyj placeholder lub pomiń
        if not os.path.exists(logo_path):
            logo_path = None
        
        if not os.path.exists(sign_path):
            sign_path = None
        
        # Dodaj ścieżki do danych dla template
        data['logo_path'] = logo_path
        data['sign_path'] = sign_path
        
        # Renderuj HTML template z danymi
        html_content = render_template(
            'nda_template.html',
            **data
        )
        
        # Generuj PDF z HTML - zwróć surowe bajty
        html = HTML(string=html_content, base_url=app_root)
        pdf_bytes = html.write_pdf()
        
        # Zwróć surowe bajty
        return pdf_bytes
        
    except ImportError as e:
        error_msg = "WeasyPrint nie jest zainstalowane. Użyj: pip install WeasyPrint"
        current_app.logger.error(error_msg)
        raise Exception(error_msg)
        
    except Exception as e:
        current_app.logger.error(f"Error generating NDA PDF: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        raise