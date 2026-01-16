# modules/logging/structured_logger.py
"""
Wrapper dla standardowego loggera obsługujący strukturalne logowanie
"""
import logging
import json
from typing import Any, Dict

class StructuredLogger:
    """Logger wrapper obsługujący dodatkowe parametry kontekstowe"""
    
    def __init__(self, logger: logging.Logger):
        self._logger = logger
    
    def _format_message(self, message: str, **kwargs) -> str:
        """Formatuje wiadomość z dodatkowymi parametrami - POPRAWKA ENKODOWANIA"""
        if not kwargs:
            return message
        
        # Konwertuj wszystkie wartości na stringi - BEZPIECZNIE
        formatted_kwargs = {}
        for key, value in kwargs.items():
            try:
                if isinstance(value, (dict, list)):
                    # POPRAWKA: ensure_ascii=True dla bezpieczeństwa
                    formatted_kwargs[key] = json.dumps(value, ensure_ascii=True)
                else:
                    # POPRAWKA: Bezpieczna konwersja na string
                    str_value = str(value)
                    # Usuń polskie znaki jeśli są problematyczne
                    safe_value = str_value.encode('ascii', errors='replace').decode('ascii')
                    formatted_kwargs[key] = safe_value
            except Exception as e:
                # Fallback dla problematycznych wartości
                formatted_kwargs[key] = f"<encoding_error:{type(value).__name__}>"
        
        # Buduj suffiks z parametrami
        try:
            params_str = " ".join([f"{k}={v}" for k, v in formatted_kwargs.items()])
            return f"{message} {params_str}"
        except Exception as e:
            # Ostateczny fallback
            return f"{message} <params_encoding_error>"
    
    def debug(self, message: str, **kwargs):
        """Log debug z dodatkowymi parametrami"""
        try:
            formatted_msg = self._format_message(message, **kwargs)
            self._logger.debug(formatted_msg)
        except Exception as e:
            # Fallback - loguj tylko podstawową wiadomość
            self._logger.debug(f"{message} <formatting_error>")
    
    def info(self, message: str, **kwargs):
        """Log info z dodatkowymi parametrami"""
        try:
            formatted_msg = self._format_message(message, **kwargs)
            self._logger.info(formatted_msg)
        except Exception as e:
            self._logger.info(f"{message} <formatting_error>")
    
    def warning(self, message: str, **kwargs):
        """Log warning z dodatkowymi parametrami"""
        try:
            formatted_msg = self._format_message(message, **kwargs)
            self._logger.warning(formatted_msg)
        except Exception as e:
            self._logger.warning(f"{message} <formatting_error>")
    
    def error(self, message: str, **kwargs):
        """Log error z dodatkowymi parametrami"""
        try:
            formatted_msg = self._format_message(message, **kwargs)
            self._logger.error(formatted_msg)
        except Exception as e:
            self._logger.error(f"{message} <formatting_error>")
    
    def critical(self, message: str, **kwargs):
        """Log critical z dodatkowymi parametrami"""
        try:
            formatted_msg = self._format_message(message, **kwargs)
            self._logger.critical(formatted_msg)
        except Exception as e:
            self._logger.critical(f"{message} <formatting_error>")
    
    # Przekieruj inne metody na standardowy logger
    def __getattr__(self, name):
        return getattr(self._logger, name)