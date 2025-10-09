# modules/analytics/models.py

from sqlalchemy import func, text, and_, or_
from extensions import db
from datetime import datetime, timedelta
import json
from typing import Dict, List, Any, Optional

# Import modeli z innych modułów
from modules.calculator.models import Quote, QuoteItem, User
from modules.quotes.models import QuoteStatus
from modules.clients.models import Client
from modules.baselinker.models import BaselinkerOrderLog
from modules.public_calculator.models import PublicSession


class AnalyticsQueries:
    """Klasa zawierająca wszystkie zapytania analityczne"""
    
    @staticmethod
    def get_sales_kpi_data() -> Dict[str, Any]:
        """Pobiera główne KPI sprzedażowe"""
        
        # Ostatnie 12 miesięcy
        twelve_months_ago = datetime.now() - timedelta(days=365)
        current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Podstawowe metryki
        total_quotes = db.session.query(func.count(Quote.id)).scalar()
        
        # Wartość ofert
        total_value = db.session.query(func.sum(Quote.total_price)).filter(
            Quote.total_price.isnot(None)
        ).scalar() or 0
        
        monthly_value = db.session.query(func.sum(Quote.total_price)).filter(
            and_(
                Quote.created_at >= current_month_start,
                Quote.total_price.isnot(None)
            )
        ).scalar() or 0
        
        avg_deal_value = db.session.query(func.avg(Quote.total_price)).filter(
            Quote.total_price.isnot(None)
        ).scalar() or 0
        
        # Konwersje
        accepted_quotes = db.session.query(func.count(Quote.id)).filter(
            Quote.acceptance_date.isnot(None)
        ).scalar()
        
        baselinker_orders = db.session.query(func.count(Quote.id)).filter(
            Quote.base_linker_order_id.isnot(None)
        ).scalar()
        
        # Wskaźniki konwersji
        conversion_accepted = round((accepted_quotes / total_quotes * 100), 2) if total_quotes > 0 else 0
        conversion_baselinker = round((baselinker_orders / total_quotes * 100), 2) if total_quotes > 0 else 0
        
        return {
            'total_quotes': total_quotes,
            'total_value': round(total_value, 2),
            'monthly_value': round(monthly_value, 2),
            'avg_deal_value': round(avg_deal_value, 2),
            'accepted_quotes': accepted_quotes,
            'baselinker_orders': baselinker_orders,
            'conversion_accepted': conversion_accepted,
            'conversion_baselinker': conversion_baselinker
        }
    
    @staticmethod
    def get_sales_trends_data(months: int = 12) -> List[Dict[str, Any]]:
        """Pobiera trendy sprzedażowe dla ostatnich N miesięcy"""
        
        start_date = datetime.now() - timedelta(days=months*30)
        
        # Zapytanie o trendy miesięczne
        trends_query = db.session.query(
            func.date_format(Quote.created_at, '%Y-%m').label('month'),
            func.count(Quote.id).label('quotes_count'),
            func.sum(Quote.total_price).label('total_value'),
            func.avg(Quote.total_price).label('avg_value'),
            func.count(Quote.acceptance_date).label('accepted_count'),
            func.count(Quote.base_linker_order_id).label('baselinker_count')
        ).filter(
            Quote.created_at >= start_date
        ).group_by(
            func.date_format(Quote.created_at, '%Y-%m')
        ).order_by(
            func.date_format(Quote.created_at, '%Y-%m')
        ).all()
        
        trends_data = []
        for row in trends_query:
            month_data = {
                'month': row.month,
                'quotes_count': row.quotes_count,
                'total_value': round(row.total_value or 0, 2),
                'avg_value': round(row.avg_value or 0, 2),
                'accepted_count': row.accepted_count,
                'baselinker_count': row.baselinker_count,
                'conversion_accepted': round((row.accepted_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0,
                'conversion_baselinker': round((row.baselinker_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0
            }
            trends_data.append(month_data)
        
        return trends_data
    
    @staticmethod
    def get_team_performance_data() -> List[Dict[str, Any]]:
        """Pobiera statystyki performance zespołu"""
        
        team_query = db.session.query(
            User.id,
            User.first_name,
            User.last_name,
            User.email,
            func.count(Quote.id).label('quotes_count'),
            func.sum(Quote.total_price).label('total_value'),
            func.avg(Quote.total_price).label('avg_value'),
            func.count(Quote.acceptance_date).label('accepted_count'),
            func.count(Quote.base_linker_order_id).label('baselinker_count')
        ).outerjoin(
            Quote, User.id == Quote.user_id
        ).filter(
            User.role.in_(['user', 'admin'])  # wykluczamy inne role jeśli są
        ).group_by(
            User.id, User.first_name, User.last_name, User.email
        ).all()
        
        team_data = []
        for row in team_query:
            user_data = {
                'user_id': row.id,
                'first_name': row.first_name or '',
                'last_name': row.last_name or '',
                'email': row.email,
                'full_name': f"{row.first_name or ''} {row.last_name or ''}".strip() or row.email,
                'quotes_count': row.quotes_count,
                'total_value': round(row.total_value or 0, 2),
                'avg_value': round(row.avg_value or 0, 2),
                'accepted_count': row.accepted_count,
                'baselinker_count': row.baselinker_count,
                'conversion_accepted': round((row.accepted_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0,
                'conversion_baselinker': round((row.baselinker_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0
            }
            team_data.append(user_data)
        
        # Sortuj według liczby ofert (malejąco)
        team_data.sort(key=lambda x: x['quotes_count'], reverse=True)
        
        return team_data
    
    @staticmethod
    def get_clients_analytics_data(limit: int = 20) -> List[Dict[str, Any]]:
        """Pobiera statystyki najważniejszych klientów"""
        
        clients_query = db.session.query(
            Client.id,
            Client.client_name,
            Client.delivery_city,
            Client.source,
            func.count(Quote.id).label('quotes_count'),
            func.sum(Quote.total_price).label('total_value'),
            func.avg(Quote.total_price).label('avg_value'),
            func.count(Quote.acceptance_date).label('accepted_count'),
            func.count(Quote.base_linker_order_id).label('baselinker_count')
        ).outerjoin(
            Quote, Client.id == Quote.client_id
        ).group_by(
            Client.id, Client.client_name, Client.delivery_city, Client.source
        ).having(
            func.count(Quote.id) > 0  # tylko klienci z ofertami
        ).order_by(
            func.sum(Quote.total_price).desc()
        ).limit(limit).all()
        
        clients_data = []
        for row in clients_query:
            client_data = {
                'client_id': row.id,
                'client_name': row.client_name or 'Brak nazwy',
                'delivery_city': row.delivery_city or '-',
                'source': row.source or '-',
                'quotes_count': row.quotes_count,
                'total_value': round(row.total_value or 0, 2),
                'avg_value': round(row.avg_value or 0, 2),
                'accepted_count': row.accepted_count,
                'baselinker_count': row.baselinker_count,
                'conversion_accepted': round((row.accepted_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0,
                'conversion_baselinker': round((row.baselinker_count / row.quotes_count * 100), 2) if row.quotes_count > 0 else 0
            }
            clients_data.append(client_data)
        
        return clients_data
    
    @staticmethod
    def get_baselinker_analytics_data() -> Dict[str, Any]:
        """Pobiera statystyki Baselinker - POPRAWIONA WERSJA"""
        
        # Podstawowe statystyki zamówień
        total_orders = db.session.query(func.count(Quote.id)).filter(
            Quote.base_linker_order_id.isnot(None)
        ).scalar()
        
        total_quotes = db.session.query(func.count(Quote.id)).scalar()
        conversion_rate = round((total_orders / total_quotes * 100), 2) if total_quotes > 0 else 0
        
        # Statystyki logów (ostatnie 30 dni) - UPROSZCZONA WERSJA bez func.case
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        total_attempts = db.session.query(func.count(BaselinkerOrderLog.id)).filter(
            BaselinkerOrderLog.created_at >= thirty_days_ago
        ).scalar() or 0
        
        successful = db.session.query(func.count(BaselinkerOrderLog.id)).filter(
            BaselinkerOrderLog.created_at >= thirty_days_ago,
            BaselinkerOrderLog.status == 'success'
        ).scalar() or 0
        
        errors = db.session.query(func.count(BaselinkerOrderLog.id)).filter(
            BaselinkerOrderLog.created_at >= thirty_days_ago,
            BaselinkerOrderLog.status == 'error'
        ).scalar() or 0
        
        success_rate = 0
        if total_attempts > 0:
            success_rate = round((successful / total_attempts * 100), 2)
        
        # Konwersja według statusów ofert
        status_conversion = db.session.query(
            QuoteStatus.name,
            func.count(Quote.id).label('total_quotes'),
            func.count(Quote.base_linker_order_id).label('baselinker_orders')
        ).outerjoin(
            Quote, QuoteStatus.id == Quote.status_id
        ).group_by(
            QuoteStatus.id, QuoteStatus.name
        ).all()
        
        status_data = []
        for row in status_conversion:
            conv_rate = round((row.baselinker_orders / row.total_quotes * 100), 2) if row.total_quotes > 0 else 0
            status_data.append({
                'status_name': row.name or 'Brak statusu',
                'total_quotes': row.total_quotes,
                'baselinker_orders': row.baselinker_orders,
                'conversion_rate': conv_rate
            })
        
        # Ostatnie logi (10 najnowszych)
        recent_logs = db.session.query(BaselinkerOrderLog).order_by(
            BaselinkerOrderLog.created_at.desc()
        ).limit(10).all()
        
        logs_data = []
        for log in recent_logs:
            logs_data.append({
                'id': log.id,
                'quote_id': log.quote_id,
                'action': log.action,
                'status': log.status,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '-',
                'error_message': log.error_message[:100] if log.error_message else None
            })
        
        return {
            'total_orders': total_orders,
            'total_quotes': total_quotes,
            'conversion_rate': conversion_rate,
            'logs_stats': {
                'total_attempts': total_attempts,
                'successful': successful,
                'errors': errors,
                'success_rate': success_rate
            },
            'status_conversion': status_data,
            'recent_logs': logs_data
        }
    
    @staticmethod
    def get_geography_stats() -> Dict[str, Any]:
        """Pobiera statystyki geograficzne klientów"""
        
        # Statystyki według miast
        cities_stats = db.session.query(
            Client.delivery_city,
            func.count(Client.id).label('clients_count'),
            func.count(Quote.id).label('quotes_count'),
            func.sum(Quote.total_price).label('total_value')
        ).outerjoin(
            Quote, Client.id == Quote.client_id
        ).filter(
            Client.delivery_city.isnot(None),
            Client.delivery_city != ''
        ).group_by(
            Client.delivery_city
        ).order_by(
            func.count(Quote.id).desc()
        ).limit(15).all()
        
        cities_data = []
        for row in cities_stats:
            cities_data.append({
                'city': row.delivery_city,
                'clients_count': row.clients_count,
                'quotes_count': row.quotes_count,
                'total_value': round(row.total_value or 0, 2)
            })
        
        # Statystyki według źródeł
        sources_stats = db.session.query(
            Client.source,
            func.count(Client.id).label('clients_count'),
            func.count(Quote.id).label('quotes_count'),
            func.sum(Quote.total_price).label('total_value')
        ).outerjoin(
            Quote, Client.id == Quote.client_id
        ).filter(
            Client.source.isnot(None),
            Client.source != ''
        ).group_by(
            Client.source
        ).order_by(
            func.count(Quote.id).desc()
        ).all()
        
        sources_data = []
        for row in sources_stats:
            sources_data.append({
                'source': row.source,
                'clients_count': row.clients_count,
                'quotes_count': row.quotes_count,
                'total_value': round(row.total_value or 0, 2)
            })
        
        return {
            'cities': cities_data,
            'sources': sources_data
        }
    
    @staticmethod
    def get_popular_products_data(limit: int = 10) -> List[Dict[str, Any]]:
        """Pobiera statystyki najpopularniejszych produktów z ofert"""
        
        products_query = db.session.query(
            QuoteItem.variant_code,
            func.count(QuoteItem.id).label('usage_count'),
            func.avg(QuoteItem.price_per_m3).label('avg_price_m3'),
            func.sum(QuoteItem.volume_m3).label('total_volume'),
            func.avg(QuoteItem.length_cm).label('avg_length'),
            func.avg(QuoteItem.width_cm).label('avg_width'),
            func.avg(QuoteItem.thickness_cm).label('avg_thickness')
        ).filter(
            QuoteItem.variant_code.isnot(None),
            QuoteItem.variant_code != '',
            QuoteItem.is_selected == 1  # tylko wybrane produkty
        ).group_by(
            QuoteItem.variant_code
        ).order_by(
            func.count(QuoteItem.id).desc()
        ).limit(limit).all()
        
        products_data = []
        for row in products_query:
            products_data.append({
                'variant_code': row.variant_code,
                'usage_count': row.usage_count,
                'avg_price_m3': round(row.avg_price_m3 or 0, 2),
                'total_volume': round(row.total_volume or 0, 3),
                'avg_dimensions': f"{round(row.avg_length or 0, 1)} x {round(row.avg_width or 0, 1)} x {round(row.avg_thickness or 0, 1)}"
            })
        
        return products_data


class AnalyticsExportHelper:
    """Pomocnicze funkcje do exportu danych"""
    
    @staticmethod
    def prepare_sales_export_data() -> Dict[str, List[Dict]]:
        """Przygotowuje dane sprzedażowe do exportu"""
        
        kpi_data = AnalyticsQueries.get_sales_kpi_data()
        trends_data = AnalyticsQueries.get_sales_trends_data()
        
        # Format danych dla Excel/CSV
        kpi_export = [
            {'Metryka': 'Łączna liczba ofert', 'Wartość': kpi_data['total_quotes']},
            {'Metryka': 'Łączna wartość ofert (PLN)', 'Wartość': kpi_data['total_value']},
            {'Metryka': 'Miesięczna wartość (PLN)', 'Wartość': kpi_data['monthly_value']},
            {'Metryka': 'Średnia wartość oferty (PLN)', 'Wartość': kpi_data['avg_deal_value']},
            {'Metryka': 'Oferty zaakceptowane', 'Wartość': kpi_data['accepted_quotes']},
            {'Metryka': 'Zamówienia Baselinker', 'Wartość': kpi_data['baselinker_orders']},
            {'Metryka': 'Konwersja accepted (%)', 'Wartość': kpi_data['conversion_accepted']},
            {'Metryka': 'Konwersja Baselinker (%)', 'Wartość': kpi_data['conversion_baselinker']}
        ]
        
        return {
            'kpi': kpi_export,
            'trends': trends_data
        }
    
    @staticmethod
    def prepare_team_export_data() -> List[Dict]:
        """Przygotowuje dane zespołu do exportu"""
        return AnalyticsQueries.get_team_performance_data()
    
    @staticmethod
    def prepare_clients_export_data() -> Dict[str, List[Dict]]:
        """Przygotowuje dane klientów do exportu"""
        
        clients_data = AnalyticsQueries.get_clients_analytics_data(50)  # więcej dla exportu
        geography_data = AnalyticsQueries.get_geography_stats()
        
        return {
            'top_clients': clients_data,
            'cities': geography_data['cities'],
            'sources': geography_data['sources']
        }
    
    @staticmethod 
    def prepare_baselinker_export_data() -> Dict[str, List[Dict]]:
        """Przygotowuje dane Baselinker do exportu"""
        
        bl_data = AnalyticsQueries.get_baselinker_analytics_data()
        
        # Przekształć logs_stats na format exportu
        logs_export = [
            {'Metryka': 'Łączne próby', 'Wartość': bl_data['logs_stats']['total_attempts']},
            {'Metryka': 'Udane', 'Wartość': bl_data['logs_stats']['successful']},
            {'Metryka': 'Błędy', 'Wartość': bl_data['logs_stats']['errors']},
            {'Metryka': 'Wskaźnik sukcesu (%)', 'Wartość': bl_data['logs_stats']['success_rate']}
        ]
        
        return {
            'logs_stats': logs_export,
            'status_conversion': bl_data['status_conversion'],
            'recent_logs': bl_data['recent_logs']
        }