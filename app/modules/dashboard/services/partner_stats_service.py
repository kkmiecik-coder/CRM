"""
Serwis statystyk dla dashboardu partnera
Zwraca TYLKO dane przypisane do konkretnego partnera

Autor: Konrad Kmiecik
Data: 2025-01-15
"""

from extensions import db
from datetime import datetime, timedelta
from sqlalchemy import extract, func
import logging

logger = logging.getLogger(__name__)


def get_partner_dashboard_stats(user):
    """
    Pobiera statystyki dla konkretnego partnera
    """
    from ...quotes.models import Quote, QuoteStatus
    
    try:
        now = datetime.now()
        
        # Wszystkie wyceny partnera z tego miesiąca
        month_quotes = Quote.query.filter(
            Quote.user_id == user.id,
            extract('year', Quote.created_at) == now.year,
            extract('month', Quote.created_at) == now.month
        ).all()
        
        month_count = len(month_quotes)
        
        # Pobierz ID statusu "Zaakceptowane" (id = 3)
        accepted_status = QuoteStatus.query.filter_by(name='Zaakceptowane').first()
        accepted_status_id = accepted_status.id if accepted_status else 3
        
        # Zaakceptowane wyceny (status_id = 3)
        accepted_quotes = [q for q in month_quotes if q.status_id == accepted_status_id]
        accepted_count = len(accepted_quotes)
        
        # Zamówione (mają base_linker_order_id)
        ordered_quotes = [q for q in month_quotes if q.base_linker_order_id is not None]
        ordered_count = len(ordered_quotes)
        
        # Oblicz współczynniki
        acceptance_rate = 0.0
        ordered_rate = 0.0
        
        if month_count > 0:
            acceptance_rate = (accepted_count / month_count) * 100
            ordered_rate = (ordered_count / month_count) * 100
        
        # Oblicz wartość netto zamówień (tylko produkty, bez wysyłki)
        ordered_value_net = 0.0
        for quote in ordered_quotes:
            # Sumuj wartość netto wszystkich wybranych produktów z wyceny
            quote_products_net = 0.0
    
            # Pobierz tylko wybrane itemy (is_selected=True)
            selected_items = quote.items.filter_by(is_selected=True).all()

            for item in selected_items:
                quote_products_net += item.get_total_price_netto()
    
            ordered_value_net += quote_products_net
        
        # Ostatnie wyceny partnera (5 najnowszych)
        recent_quotes = Quote.query.filter_by(user_id=user.id)\
            .order_by(Quote.created_at.desc())\
            .limit(5)\
            .all()
        
        recent_quotes_data = []
        for quote in recent_quotes:
            # Pobierz nazwę statusu
            status_name = quote.quote_status.name if quote.quote_status else 'Nieznany'
            
            # Nazwa klienta
            client_name = 'Brak danych'
            if quote.client:
                if hasattr(quote.client, 'company_name') and quote.client.company_name:
                    client_name = quote.client.company_name
                elif hasattr(quote.client, 'name') and quote.client.name:
                    client_name = quote.client.name
            
            recent_quotes_data.append({
                'id': quote.id,
                'quote_number': quote.quote_number or 'Brak numeru',
                'client_name': client_name,
                'created_at': quote.created_at,
                'total_price': float(quote.total_price) if quote.total_price else 0,
                'status': status_name,
                'status_display': status_name
            })
        
        stats = {
            'quotes': {
                'month_count': month_count,
                'accepted_count': accepted_count,
                'acceptance_rate': round(acceptance_rate, 1),
                'ordered_count': ordered_count,
                'ordered_rate': round(ordered_rate, 1),
                'ordered_value_net': round(ordered_value_net, 2)
            },
            'recent': {
                'quotes': recent_quotes_data
            }
        }
        
        logger.info(f"[PartnerStats] Statystyki partnera {user.email}: "
                   f"Wyceny: {month_count}, Zaakceptowane: {accepted_count}, "
                   f"Zamówione: {ordered_count}, Wartość: {ordered_value_net:.2f} zł")
        
        return stats
    
    except Exception as e:
        logger.exception(f"[PartnerStats] Błąd pobierania statystyk partnera: {e}")
        
        return {
            'quotes': {
                'month_count': 0,
                'accepted_count': 0,
                'acceptance_rate': 0.0,
                'ordered_count': 0,
                'ordered_rate': 0.0,
                'ordered_value_net': 0.0
            },
            'recent': {'quotes': []}
        }


def get_partner_top_products_data(user_id, limit=5):
    """
    Pobiera top produkty dla konkretnego partnera
    Na podstawie variant_code z wycen
    """
    from ...quotes.models import Quote, QuoteItem
    
    try:
        # Pobierz najpopularniejsze variant_code z wycen partnera
        products_query = db.session.query(
            QuoteItem.variant_code,
            func.count(QuoteItem.id).label('count')
        ).join(
            Quote, Quote.id == QuoteItem.quote_id
        ).filter(
            Quote.user_id == user_id,
            QuoteItem.variant_code.isnot(None),
            QuoteItem.is_selected == True  # Tylko wybrane warianty
        ).group_by(
            QuoteItem.variant_code
        ).order_by(
            func.count(QuoteItem.id).desc()
        ).limit(limit).all()
        
        # Oblicz total dla procentów
        total_count = sum(p.count for p in products_query)
        
        products = []
        for product in products_query:
            percentage = (product.count / total_count * 100) if total_count > 0 else 0
            
            products.append({
                'name': product.variant_code or 'Nieznany produkt',
                'quantity': product.count,
                'percentage': round(percentage, 1)
            })
        
        logger.info(f"[PartnerStats] Pobrano {len(products)} top produktów dla partnera {user_id}")
        
        return products
    
    except Exception as e:
        logger.exception(f"[PartnerStats] Błąd pobierania top produktów: {e}")
        return []


def get_partner_quotes_chart_data(user_id, months=6):
    """
    Dane do wykresu wycen partnera (ostatnie N miesięcy)
    OPCJONALNE - może być użyte w przyszłości
    
    Args:
        user_id: ID partnera
        months: Liczba miesięcy wstecz
    
    Returns:
        dict: Dane wykresu (labels, datasets, summary)
    """
    from ...quotes.models import Quote
    
    try:
        now = datetime.now()
        start_date = now - timedelta(days=30 * months)
        
        # Pobierz wyceny partnera z ostatnich N miesięcy
        quotes = Quote.query.filter(
            Quote.user_id == user_id,
            Quote.created_at >= start_date
        ).all()
        
        # Grupuj po miesiącach
        monthly_data = {}
        
        for quote in quotes:
            if not quote.created_at:
                continue
            
            month_key = quote.created_at.strftime('%Y-%m')
            
            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    'total': 0,
                    'accepted': 0,
                    'ordered': 0
                }
            
            monthly_data[month_key]['total'] += 1
            
            # Sprawdź status przez relację
            if quote.quote_status and quote.quote_status.name == 'Zaakceptowane':
                monthly_data[month_key]['accepted'] += 1

            if quote.base_linker_order_id:
                monthly_data[month_key]['ordered'] += 1
        
        # Przygotuj dane dla wykresu
        labels = []
        total_data = []
        accepted_data = []
        ordered_data = []
        
        # Sortuj miesiące chronologicznie
        sorted_months = sorted(monthly_data.keys())
        
        for month_key in sorted_months:
            # Format etykiety: "Sty 2025"
            date_obj = datetime.strptime(month_key, '%Y-%m')
            month_label = date_obj.strftime('%b %Y')
            
            labels.append(month_label)
            total_data.append(monthly_data[month_key]['total'])
            accepted_data.append(monthly_data[month_key]['accepted'])
            ordered_data.append(monthly_data[month_key]['ordered'])
        
        chart_data = {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Wszystkie',
                    'data': total_data,
                    'color': '#64748b'
                },
                {
                    'label': 'Zaakceptowane',
                    'data': accepted_data,
                    'color': '#16a34a'
                },
                {
                    'label': 'Zamówione',
                    'data': ordered_data,
                    'color': '#ED6B24'
                }
            ],
            'summary': {
                'total_quotes': sum(total_data),
                'accepted_quotes': sum(accepted_data),
                'ordered_quotes': sum(ordered_data)
            }
        }
        
        logger.info(f"[PartnerStats] Dane wykresu dla partnera {user_id}: {len(labels)} miesięcy")
        
        return chart_data
    
    except Exception as e:
        logger.exception(f"[PartnerStats] Błąd generowania wykresu: {e}")
        
        return {
            'labels': [],
            'datasets': [],
            'summary': {
                'total_quotes': 0,
                'accepted_quotes': 0,
                'ordered_quotes': 0
            }
        }