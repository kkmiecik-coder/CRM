# modules/reports/__init__.py
"""
Moduł Raportów - Wood Power CRM
Odpowiedzialny za gromadzenie i wyświetlanie danych o sprzedaży z Baselinker
"""

from flask import Blueprint

# Utworzenie Blueprint dla modułu reports
reports_bp = Blueprint(
    "reports", 
    __name__,
    template_folder="templates",
    static_folder="static",
    url_prefix="/reports"
)

# Import routingu po utworzeniu Blueprint (unikamy circular imports)
from . import routers

# Eksportujemy Blueprint dla łatwego importu w głównej aplikacji
__all__ = ['reports_bp']