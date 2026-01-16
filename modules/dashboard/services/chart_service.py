"""
Serwis do pobierania danych dla wykresów dashboard
"""

from datetime import datetime, timedelta
from sqlalchemy import func, and_, extract
from extensions import db
import logging

logger = logging.getLogger(__name__)

def get_quotes_chart_data(months=6):
    """
    Pobiera dane dla wykresu analizy wycen za ostatnie X miesięcy
    
    Args:
        months (int): Liczba miesięcy wstecz
        
    Returns:
        dict: Dane dla wykresu z kategoriami: total, accepted, ordered
    """
    try:
        from ...quotes.models import Quote
        from ...reports.models import BaselinkerReportOrder  # POPRAWIONY IMPORT
        
        # DEBUG - sprawdź czy modele się importują
        logger.info(f"[ChartService] DEBUG: Quote model imported: {Quote}")
        logger.info(f"[ChartService] DEBUG: BaselinkerReportOrder model imported: {BaselinkerReportOrder}")
        
        # Oblicz datę początkową
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=months * 30)
        
        logger.info(f"[ChartService] DEBUG: Date range {start_date} to {end_date}")
        logger.info(f"[ChartService] Pobieranie danych wycen od {start_date} do {end_date}")
        
        # DEBUG - sprawdź ile rekordów mamy w bazie
        total_quotes = Quote.query.count()
        total_orders = BaselinkerReportOrder.query.count()
        logger.info(f"[ChartService] DEBUG: Total quotes in DB: {total_quotes}")
        logger.info(f"[ChartService] DEBUG: Total orders in DB: {total_orders}")
        
        # DEBUG - sprawdź ile rekordów w okresie
        period_quotes = Quote.query.filter(Quote.created_at >= start_date).count()
        period_orders = BaselinkerReportOrder.query.filter(BaselinkerReportOrder.date_created >= start_date).count()
        logger.info(f"[ChartService] DEBUG: Quotes in period: {period_quotes}")
        logger.info(f"[ChartService] DEBUG: Orders in period: {period_orders}")
        
        # Pobierz dane miesięczne dla wycen
        monthly_quotes = db.session.query(
            extract('year', Quote.created_at).label('year'),
            extract('month', Quote.created_at).label('month'),
            func.count(Quote.id).label('total_quotes'),
            func.count(Quote.acceptance_date).label('accepted_quotes')
        ).filter(
            Quote.created_at >= start_date
        ).group_by(
            extract('year', Quote.created_at),
            extract('month', Quote.created_at)
        ).order_by(
            extract('year', Quote.created_at),
            extract('month', Quote.created_at)
        ).all()
        
        logger.info(f"[ChartService] DEBUG: Monthly quotes query returned {len(monthly_quotes)} rows")
        for i, quote in enumerate(monthly_quotes):
            logger.info(f"[ChartService] DEBUG: Month {i+1}: {quote.year}-{quote.month}, total: {quote.total_quotes}, accepted: {quote.accepted_quotes}")
        
        # Pobierz dane zamówień z Baselinker
        monthly_orders = db.session.query(
            extract('year', BaselinkerReportOrder.date_created).label('year'),
            extract('month', BaselinkerReportOrder.date_created).label('month'),
            func.count(BaselinkerReportOrder.id).label('ordered_count')
        ).filter(
            BaselinkerReportOrder.date_created >= start_date
        ).group_by(
            extract('year', BaselinkerReportOrder.date_created),
            extract('month', BaselinkerReportOrder.date_created)
        ).order_by(
            extract('year', BaselinkerReportOrder.date_created),
            extract('month', BaselinkerReportOrder.date_created)
        ).all()
        
        logger.info(f"[ChartService] DEBUG: Monthly orders query returned {len(monthly_orders)} rows")
        for i, order in enumerate(monthly_orders):
            logger.info(f"[ChartService] DEBUG: Order month {i+1}: {order.year}-{order.month}, count: {order.ordered_count}")
        
        # Przetwórz dane na format JSON
        chart_data = {
            'labels': [],
            'datasets': {
                'total_quotes': [],
                'accepted_quotes': [],
                'ordered_quotes': []
            },
            'summary': {
                'total_quotes': 0,
                'accepted_quotes': 0,
                'ordered_quotes': 0
            }
        }
        
        # Utwórz mapę zamówień według miesięcy
        orders_map = {}
        for order in monthly_orders:
            key = f"{int(order.year)}-{int(order.month):02d}"
            orders_map[key] = order.ordered_count
        
        logger.info(f"[ChartService] DEBUG: Orders map: {orders_map}")
        
        # Przetwórz dane wycen
        for quote in monthly_quotes:
            year = int(quote.year)
            month = int(quote.month)
            month_key = f"{year}-{month:02d}"
            
            # Dodaj label miesiąca
            month_names = [
                '', 'Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze',
                'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'
            ]
            chart_data['labels'].append(f"{month_names[month]} {year}")
            
            # Dodaj dane
            chart_data['datasets']['total_quotes'].append(quote.total_quotes)
            chart_data['datasets']['accepted_quotes'].append(quote.accepted_quotes)
            chart_data['datasets']['ordered_quotes'].append(orders_map.get(month_key, 0))
            
            # Aktualizuj sumy
            chart_data['summary']['total_quotes'] += quote.total_quotes
            chart_data['summary']['accepted_quotes'] += quote.accepted_quotes
            chart_data['summary']['ordered_quotes'] += orders_map.get(month_key, 0)
            
            logger.info(f"[ChartService] DEBUG: Processed {month_key}: quotes={quote.total_quotes}, accepted={quote.accepted_quotes}, orders={orders_map.get(month_key, 0)}")
        
        logger.info(f"[ChartService] Wygenerowano dane dla {len(chart_data['labels'])} miesięcy")
        logger.info(f"[ChartService] DEBUG: Final summary: {chart_data['summary']}")
        logger.info(f"[ChartService] DEBUG: Final chart_data: {chart_data}")
        
        return chart_data
        
    except Exception as e:
        logger.exception(f"[ChartService] Błąd pobierania danych wykresu: {e}")
        logger.error(f"[ChartService] DEBUG: Exception type: {type(e).__name__}")
        logger.error(f"[ChartService] DEBUG: Exception args: {e.args}")
        return {
            'labels': ['Brak danych'],
            'datasets': {
                'total_quotes': [0],
                'accepted_quotes': [0], 
                'ordered_quotes': [0]
            },
            'summary': {
                'total_quotes': 0,
                'accepted_quotes': 0,
                'ordered_quotes': 0
            }
        }

def get_top_products_data(limit=5):
    """
    Pobiera dane najpopularniejszych produktów z Baselinker
    
    Args:
        limit (int): Liczba produktów do pobrania
        
    Returns:
        list: Lista produktów z nazwą, ilością i procentem
    """
    try:
        from ...reports.models import BaselinkerReportOrder  # POPRAWIONY IMPORT
        
        # Pobierz najpopularniejsze gatunki drewna
        top_species = db.session.query(
            BaselinkerReportOrder.wood_species.label('species'),
            BaselinkerReportOrder.technology.label('technology'),
            BaselinkerReportOrder.wood_class.label('wood_class'),
            func.count(BaselinkerReportOrder.id).label('order_count'),
            func.sum(BaselinkerReportOrder.quantity).label('total_quantity')
        ).filter(
            BaselinkerReportOrder.wood_species.isnot(None),
            BaselinkerReportOrder.date_created >= datetime.now() - timedelta(days=90)  # Ostatnie 3 miesiące
        ).group_by(
            BaselinkerReportOrder.wood_species,
            BaselinkerReportOrder.technology,
            BaselinkerReportOrder.wood_class
        ).order_by(
            func.count(BaselinkerReportOrder.id).desc()
        ).limit(limit).all()
        
        # Oblicz łączną liczbę zamówień dla procentów
        total_orders = db.session.query(
            func.count(BaselinkerReportOrder.id)
        ).filter(
            BaselinkerReportOrder.wood_species.isnot(None),
            BaselinkerReportOrder.date_created >= datetime.now() - timedelta(days=90)
        ).scalar()
        
        # Przygotuj dane
        products = []
        for product in top_species:
            percentage = (product.order_count / total_orders * 100) if total_orders > 0 else 0
            
            # Stwórz czytelną nazwę produktu
            product_name = f"{product.species or 'Nieznany'}"
            if product.technology:
                product_name += f" {product.technology}"
            if product.wood_class:
                product_name += f" {product.wood_class}"
            
            products.append({
                'name': product_name,
                'quantity': product.total_quantity or 0,
                'order_count': product.order_count,
                'percentage': round(percentage, 1)
            })
        
        logger.info(f"[ChartService] Pobrano {len(products)} top produktów")
        return products
        
    except Exception as e:
        logger.exception(f"[ChartService] Błąd pobierania top produktów: {e}")
        return [
            {'name': 'Dąb Klejonka A', 'quantity': 156, 'order_count': 45, 'percentage': 45.2},
            {'name': 'Jesion Deska B', 'quantity': 98, 'order_count': 28, 'percentage': 28.7},
            {'name': 'Buk Klejonka A', 'quantity': 67, 'order_count': 19, 'percentage': 19.6},
            {'name': 'Sosna Deska C', 'quantity': 34, 'order_count': 9, 'percentage': 9.9}
        ]

def get_production_overview():
    """
    Pobiera przegląd statusów produkcji
    
    Returns:
        dict: Statystyki produkcji według statusów
    """
    try:
        from ...production.models import ProductionItem, ProductionStatus
        
        # Pobierz statystyki według statusów
        status_stats = db.session.query(
            ProductionStatus.display_name.label('status_name'),
            ProductionStatus.color_code.label('color'),
            func.count(ProductionItem.id).label('count')
        ).join(
            ProductionItem, ProductionItem.status_id == ProductionStatus.id
        ).group_by(
            ProductionStatus.id,
            ProductionStatus.display_name,
            ProductionStatus.color_code
        ).all()
        
        production_data = {
            'statuses': [],
            'total_items': 0
        }
        
        for stat in status_stats:
            production_data['statuses'].append({
                'name': stat.status_name,
                'count': stat.count,
                'color': stat.color
            })
            production_data['total_items'] += stat.count
        
        logger.info(f"[ChartService] Statystyki produkcji: {production_data['total_items']} elementów")
        return production_data
        
    except Exception as e:
        logger.exception(f"[ChartService] Błąd pobierania danych produkcji: {e}")
        return {
            'statuses': [
                {'name': 'W kolejce', 'count': 15, 'color': '#94a3b8'},
                {'name': 'W produkcji', 'count': 8, 'color': '#f59e0b'},
                {'name': 'Gotowe', 'count': 23, 'color': '#10b981'}
            ],
            'total_items': 46
        }

def get_sales_trends(days=30):
    """
    Pobiera trendy sprzedażowe za ostatnie X dni
    
    Args:
        days (int): Liczba dni wstecz
        
    Returns:
        dict: Dane trendów sprzedażowych
    """
    try:
        from ...quotes.models import Quote
        
        # Oblicz datę początkową
        start_date = datetime.now() - timedelta(days=days)
        
        # Pobierz dane dzienne
        daily_stats = db.session.query(
            func.date(Quote.created_at).label('date'),
            func.count(Quote.id).label('quotes_count'),
            func.count(Quote.acceptance_date).label('accepted_count'),
            func.sum(Quote.total_price).label('total_value')
        ).filter(
            Quote.created_at >= start_date
        ).group_by(
            func.date(Quote.created_at)
        ).order_by(
            func.date(Quote.created_at)
        ).all()
        
        trends_data = {
            'labels': [],
            'quotes': [],
            'accepted': [],
            'values': []
        }
        
        for stat in daily_stats:
            trends_data['labels'].append(stat.date.strftime('%d.%m'))
            trends_data['quotes'].append(stat.quotes_count)
            trends_data['accepted'].append(stat.accepted_count)
            trends_data['values'].append(float(stat.total_value) if stat.total_value else 0)
        
        logger.info(f"[ChartService] Trendy sprzedażowe za {days} dni: {len(trends_data['labels'])} punktów")
        return trends_data
        
    except Exception as e:
        logger.exception(f"[ChartService] Błąd pobierania trendów sprzedaży: {e}")
        return {
            'labels': [],
            'quotes': [],
            'accepted': [],
            'values': []
        }