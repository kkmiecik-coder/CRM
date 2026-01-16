"""
Error Service - Centralne logowanie błędów w module production

Funkcjonalność:
- log_production_error() - zapisuje błędy do tabeli prod_errors
- Automatyczne zbieranie kontekstu (IP, URL, stack trace)
- Wsparcie dla różnych typów błędów
"""

import traceback
from flask import request
from datetime import datetime
from app import db
from ..models import ProductionError


def log_production_error(
    error_type: str,
    error_message: str,
    error_details: dict = None,
    exception: Exception = None,
    related_product_id: int = None,
    related_order_id: int = None,
    include_stack_trace: bool = True
):
    """
    Loguje błąd do tabeli prod_errors

    Args:
        error_type (str): Typ błędu z enum ('template_error', 'api_error', etc.)
        error_message (str): Opis błędu
        error_details (dict, optional): Dodatkowe szczegóły w formacie JSON
        exception (Exception, optional): Obiekt wyjątku do zapisania stack trace
        related_product_id (int, optional): ID powiązanego produktu
        related_order_id (int, optional): ID powiązanego zamówienia
        include_stack_trace (bool): Czy dołączyć pełny stack trace (default: True)

    Returns:
        ProductionError: Utworzony obiekt błędu

    Example:
        >>> try:
        >>>     # some code
        >>> except Exception as e:
        >>>     log_production_error(
        >>>         error_type='template_error',
        >>>         error_message='Błąd renderowania szablonu',
        >>>         exception=e,
        >>>         error_details={'template': 'cutting.html'}
        >>>     )
    """
    try:
        # Zbierz stack trace jeśli dostępny
        stack_trace_text = None
        if include_stack_trace:
            if exception:
                stack_trace_text = ''.join(traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                ))
            else:
                stack_trace_text = ''.join(traceback.format_stack())

        # Zbierz kontekst requesta jeśli dostępny
        user_ip = None
        user_agent = None
        request_url = None
        request_method = None

        try:
            if request:
                user_ip = request.remote_addr
                user_agent = request.headers.get('User-Agent')
                request_url = request.url
                request_method = request.method
        except RuntimeError:
            # Brak kontekstu requesta (np. w background task)
            pass

        # Utwórz wpis w bazie
        production_error = ProductionError(
            error_type=error_type,
            error_message=error_message,
            error_details_json=error_details,
            stack_trace=stack_trace_text,
            related_product_id=related_product_id,
            related_order_id=related_order_id,
            request_url=request_url,
            request_method=request_method,
            user_ip=user_ip,
            user_agent=user_agent,
            error_occurred_at=datetime.utcnow()
        )

        db.session.add(production_error)
        db.session.commit()

        return production_error

    except Exception as logging_error:
        # Nie pozwól aby błąd logowania zepsuł aplikację
        # Fallback do print jeśli logowanie się nie powiedzie
        print(f"[ERROR SERVICE] Nie udało się zapisać błędu do bazy: {logging_error}")
        print(f"[ERROR SERVICE] Oryginalny błąd: {error_type} - {error_message}")
        try:
            db.session.rollback()
        except:
            pass
        return None


def log_template_error(template_name: str, error_message: str, exception: Exception = None):
    """
    Skrót do logowania błędów szablonów Jinja

    Args:
        template_name (str): Nazwa szablonu (np. 'cutting.html')
        error_message (str): Opis błędu
        exception (Exception, optional): Obiekt wyjątku

    Example:
        >>> log_template_error('cutting.html', 'Attribute error', exception=e)
    """
    return log_production_error(
        error_type='template_error',
        error_message=error_message,
        error_details={'template': template_name},
        exception=exception
    )


def log_api_error(endpoint: str, error_message: str, exception: Exception = None, status_code: int = None):
    """
    Skrót do logowania błędów API

    Args:
        endpoint (str): Endpoint API (np. '/api/orders')
        error_message (str): Opis błędu
        exception (Exception, optional): Obiekt wyjątku
        status_code (int, optional): HTTP status code
    """
    error_details = {'endpoint': endpoint}
    if status_code:
        error_details['status_code'] = status_code

    return log_production_error(
        error_type='api_error',
        error_message=error_message,
        error_details=error_details,
        exception=exception
    )
