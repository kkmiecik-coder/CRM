# modules/logging/__init__.py
"""
Moduł logowania aplikacji Wood Power CRM
"""

from .logger import AppLogger, get_logger
from .config import LogConfig
from .routers import logging_bp
from .structured_logger import StructuredLogger

def get_structured_logger(module_name):
    """
    Pobiera strukturalny logger dla modułu
    
    Args:
        module_name (str): Nazwa modułu (np. 'baselinker.service')
    
    Returns:
        StructuredLogger: Logger obsługujący dodatkowe parametry
    """
    base_logger = AppLogger.get_logger(module_name)
    return StructuredLogger(base_logger)

__all__ = ['AppLogger', 'get_logger', 'get_structured_logger', 'LogConfig', 'logging_bp', 'StructuredLogger']