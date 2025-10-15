# Dashboard services

from .stats_service import get_dashboard_stats
from .weather_service import get_weather_data
from .chart_service import get_quotes_chart_data, get_top_products_data, get_production_overview
from .partner_stats_service import get_partner_dashboard_stats, get_partner_top_products_data, get_partner_quotes_chart_data

__all__ = [
    'get_dashboard_stats',
    'get_weather_data',
    'get_quotes_chart_data',
    'get_top_products_data',
    'get_production_overview',
    'get_partner_dashboard_stats',
    'get_partner_top_products_data',
    'get_partner_quotes_chart_data'
]