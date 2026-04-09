"""
Integracja AI Assistant z lokalną bazą CRM (wyceny, klienci)
Tylko READ-ONLY — bez modyfikacji danych
"""

import re
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_, func, desc
from extensions import db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------
def _extract_quote_number(message: str) -> Optional[str]:
    """Wyciąga numer wyceny z wiadomości (format NN/MM/RR/W)."""
    patterns = [
        r'(?:wycen[aę]|ofert[aę])\s+(\d{1,3}/\d{2}/\d{2}/[A-Z])',
        r'(\d{1,3}/\d{2}/\d{2}/[A-Z])',
        r'(?:wycen[aę]|ofert[aę])\s+(\d{1,3}-\d{2}-\d{2}-[A-Z])',
        r'(\d{1,3}-\d{2}-\d{2}-[A-Z])',
        r'(?:wycen[aę]|ofert[aę])\s+(?:nr|numer)?[:\s]*(\d{1,3}[/\-]\d{2}[/\-]\d{2}[/\-][A-Z])',
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            quote_num = match.group(1).replace('-', '/')
            return quote_num.upper()
    return None


def _extract_crm_client_query(message: str) -> Optional[str]:
    """Wyciąga zapytanie o klienta dla CRM."""
    skip_words = [
        'wycena', 'wyceny', 'wycenę', 'oferta', 'oferty', 'ofertę',
        'dane', 'szczegóły', 'szczegoly', 'info', 'status', 'jaki', 'jaka', 'jest',
        'pana', 'pani', 'pan', 'klienta', 'klient',
        'znajdź', 'znajdz', 'szukaj', 'pokaż', 'pokaz', 'sprawdź', 'sprawdz',
        'numerze', 'numer', 'nr', 'po', 'dla', 'tego', 'ten', 'ta', 'to',
        'proszę', 'prosze', 'podaj', 'daj', 'zobacz',
    ]

    # Jeśli wiadomość dotyczy numeru wyceny — nie szukaj klienta
    if re.search(r'(?:po\s+)?numer(?:ze)?\s+\d', message, re.IGNORECASE):
        return None
    if re.search(r'\d{1,3}[/\-]\d{2}[/\-]\d{2}[/\-][A-Z]', message, re.IGNORECASE):
        return None

    patterns = [
        r'(?:wycen[ayę]|ofert[ayę]|status)[^a-ząćęłńóśźż]*(?:pana?|pani)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
        r'(?:pana?|pani)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
        r'(?:dane|szczegóły|szczegoly|info)\s+klient[a]?\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ0-9\s]+)',
        r'klient[a]?\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
        r'(?:wyceny|oferty)\s+(?:dla\s+)?klient[a]?\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ\s]+)',
        r'([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)\s+(?:wycen[ayę]|ofert[ayę])',
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name_words = name.lower().split()
            if all(word not in skip_words for word in name_words) and len(name) > 3:
                return name
    return None


# ---------------------------------------------------------------------------
# CRMQueryIntegration
# ---------------------------------------------------------------------------
class CRMQueryIntegration:
    """
    Serwis do odpytywania lokalnej bazy CRM przez AI Assistant.
    Dostęp READ-ONLY. Kontrola uprawnień: Admin/User = wszystko, Partner = swoje.
    """

    # ------------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _can_access_quote(user, quote) -> bool:
        if user.is_admin() or user.is_user():
            return True
        if user.is_partner():
            return quote.user_id == user.id
        return False

    @staticmethod
    def _can_access_client(user, client) -> bool:
        if user.is_admin() or user.is_user():
            return True
        if user.is_partner():
            from modules.calculator.models import Quote
            if client.created_by_user_id == user.id:
                return True
            has_quote = Quote.query.filter(
                Quote.client_id == client.id,
                Quote.user_id == user.id
            ).first()
            return has_quote is not None
        return False

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------
    def search_quotes(self, user, query: Optional[str] = None,
                      status_name: Optional[str] = None,
                      client_name: Optional[str] = None,
                      date_from: Optional[datetime] = None,
                      date_to: Optional[datetime] = None,
                      limit: int = 10) -> Dict:
        try:
            from modules.calculator.models import Quote
            from modules.quotes.models import QuoteStatus
            from modules.clients.models import Client

            base_query = Quote.query
            if user.is_partner():
                base_query = base_query.filter(Quote.user_id == user.id)

            if query:
                base_query = base_query.filter(Quote.quote_number.ilike(f'%{query}%'))

            if status_name:
                status = QuoteStatus.query.filter(
                    func.lower(QuoteStatus.name).like(f'%{status_name.lower()}%')
                ).first()
                if status:
                    base_query = base_query.filter(Quote.status_id == status.id)

            if client_name:
                client_ids = [c[0] for c in db.session.query(Client.id).filter(
                    func.lower(Client.client_name).like(f'%{client_name.lower()}%')
                ).all()]
                if client_ids:
                    base_query = base_query.filter(Quote.client_id.in_(client_ids))
                else:
                    return {'success': True, 'quotes': [], 'message': f'Nie znaleziono klienta: {client_name}'}

            if date_from:
                base_query = base_query.filter(Quote.created_at >= date_from)
            if date_to:
                base_query = base_query.filter(Quote.created_at <= date_to)

            quotes = base_query.order_by(desc(Quote.created_at)).limit(limit).all()

            return {
                'success': True,
                'quotes': [self._format_quote_summary(q) for q in quotes],
                'count': len(quotes)
            }
        except Exception as e:
            logger.error(f"Błąd wyszukiwania wycen: {e}")
            return {'success': False, 'error': str(e)}

    def get_quote_details(self, user, quote_number: str) -> Dict:
        try:
            from modules.calculator.models import Quote

            quote = Quote.query.filter(Quote.quote_number == quote_number).first()
            if not quote:
                quote = Quote.query.filter(Quote.quote_number.ilike(f'%{quote_number}%')).first()
            if not quote:
                # Debug: pokaż ostatnie wyceny żeby zrozumieć format
                recent = Quote.query.order_by(Quote.id.desc()).limit(5).all()
                recent_nums = [q.quote_number for q in recent]
                logger.warning(f"Nie znaleziono wyceny '{quote_number}'. Ostatnie 5 w bazie: {recent_nums}")
                return {'success': False, 'error': f'Nie znaleziono danych dla wyceny {quote_number} w systemie. Sprawdź proszę numer.'}

            if not self._can_access_quote(user, quote):
                return {'success': False, 'error': 'Nie masz uprawnień do tej wyceny.'}

            return {'success': True, 'quote': self._format_quote_full(quote)}
        except Exception as e:
            logger.error(f"Błąd pobierania wyceny: {e}")
            return {'success': False, 'error': str(e)}

    def get_quotes_statistics(self, user, days: int = 30) -> Dict:
        try:
            from modules.calculator.models import Quote

            date_from = datetime.utcnow() - timedelta(days=days)
            base_query = Quote.query.filter(Quote.created_at >= date_from)

            if user.is_partner():
                base_query = base_query.filter(Quote.user_id == user.id)

            quotes = base_query.all()
            total_count = len(quotes)
            total_value = sum(float(q.total_price or 0) for q in quotes)

            status_counts = {}
            for q in quotes:
                sn = q.quote_status.name if q.quote_status else 'Brak statusu'
                status_counts[sn] = status_counts.get(sn, 0) + 1

            with_orders = len([q for q in quotes if q.base_linker_order_id])

            return {
                'success': True,
                'statistics': {
                    'period_days': days,
                    'total_quotes': total_count,
                    'total_value': round(total_value, 2),
                    'average_value': round(total_value / total_count, 2) if total_count > 0 else 0,
                    'with_orders': with_orders,
                    'conversion_rate': round(with_orders / total_count * 100, 1) if total_count > 0 else 0,
                    'by_status': status_counts
                }
            }
        except Exception as e:
            logger.error(f"Błąd statystyk wycen: {e}")
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def search_clients(self, user, query: str, limit: int = 10) -> Dict:
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            search_filter = or_(
                func.lower(Client.client_name).like(f'%{query.lower()}%'),
                func.lower(Client.email).like(f'%{query.lower()}%'),
                Client.phone.like(f'%{query}%'),
                Client.client_number.like(f'%{query}%')
            )
            base_query = Client.query.filter(search_filter)

            if user.is_partner():
                own_client_ids = [c[0] for c in db.session.query(Client.id).filter(
                    Client.created_by_user_id == user.id
                ).all()]
                quote_client_ids = [c[0] for c in db.session.query(Quote.client_id).filter(
                    Quote.user_id == user.id,
                    Quote.client_id.isnot(None)
                ).distinct().all()]
                accessible_ids = list(set(own_client_ids + quote_client_ids))
                if not accessible_ids:
                    return {'success': True, 'clients': [], 'count': 0}
                base_query = base_query.filter(Client.id.in_(accessible_ids))

            clients = base_query.limit(limit).all()
            return {
                'success': True,
                'clients': [self._format_client_summary(c) for c in clients],
                'count': len(clients)
            }
        except Exception as e:
            logger.error(f"Błąd wyszukiwania klientów: {e}")
            return {'success': False, 'error': str(e)}

    def get_client_details(self, user, client_identifier: str) -> Dict:
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            client = Client.query.filter(
                or_(
                    Client.client_number == client_identifier,
                    func.lower(Client.client_name).like(f'%{client_identifier.lower()}%')
                )
            ).first()

            if not client:
                return {'success': False, 'error': f'Nie znaleziono klienta: {client_identifier}'}

            if not self._can_access_client(user, client):
                return {'success': False, 'error': 'Nie masz uprawnień do tego klienta.'}

            quotes_query = Quote.query.filter(Quote.client_id == client.id)
            if user.is_partner():
                quotes_query = quotes_query.filter(Quote.user_id == user.id)

            recent_quotes = quotes_query.order_by(desc(Quote.created_at)).limit(5).all()

            return {
                'success': True,
                'client': self._format_client_full(client),
                'recent_quotes': [self._format_quote_summary(q) for q in recent_quotes]
            }
        except Exception as e:
            logger.error(f"Błąd pobierania klienta: {e}")
            return {'success': False, 'error': str(e)}

    def get_client_quotes_summary(self, user, client_id: int) -> Dict:
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            client = Client.query.get(client_id)
            if not client:
                return {'success': False, 'error': 'Klient nie znaleziony'}

            if not self._can_access_client(user, client):
                return {'success': False, 'error': 'Nie masz uprawnień do tego klienta.'}

            quotes_query = Quote.query.filter(Quote.client_id == client_id)
            if user.is_partner():
                quotes_query = quotes_query.filter(Quote.user_id == user.id)

            quotes = quotes_query.all()
            total_value = sum(float(q.total_price or 0) for q in quotes)
            with_orders = len([q for q in quotes if q.base_linker_order_id])

            return {
                'success': True,
                'summary': {
                    'client_name': client.client_name,
                    'total_quotes': len(quotes),
                    'total_value': round(total_value, 2),
                    'orders_placed': with_orders
                }
            }
        except Exception as e:
            logger.error(f"Błąd podsumowania klienta: {e}")
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Quote statuses
    # ------------------------------------------------------------------
    def get_quote_statuses(self) -> Dict:
        try:
            from modules.quotes.models import QuoteStatus
            statuses = QuoteStatus.query.all()
            return {
                'success': True,
                'statuses': [{'id': s.id, 'name': s.name, 'color': s.color_hex} for s in statuses]
            }
        except Exception as e:
            logger.error(f"Błąd pobierania statusów: {e}")
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------
    @staticmethod
    def _format_quote_summary(quote) -> Dict:
        return {
            'quote_number': quote.quote_number,
            'created_at': quote.created_at.strftime('%Y-%m-%d %H:%M') if quote.created_at else None,
            'status': quote.quote_status.name if quote.quote_status else 'Brak statusu',
            'client_name': quote.client.client_name if quote.client else 'Brak klienta',
            'total_price': float(quote.total_price) if quote.total_price else 0,
            'has_order': bool(quote.base_linker_order_id),
            'order_id': quote.base_linker_order_id
        }

    @staticmethod
    def _format_quote_full(quote) -> Dict:
        from modules.calculator.models import QuoteItemDetails

        items = list(quote.items)
        details = QuoteItemDetails.query.filter(QuoteItemDetails.quote_id == quote.id).all()
        details_map = {d.product_index: d for d in details}

        formatted_items = []
        for item in items:
            detail = details_map.get(item.product_index)
            formatted_items.append({
                'product_index': item.product_index,
                'variant_code': item.variant_code,
                'dimensions': f"{item.length_cm}x{item.width_cm}x{item.thickness_cm} cm" if item.length_cm else None,
                'volume_m3': float(item.volume_m3) if item.volume_m3 else None,
                'price_netto': float(item.price_netto) if item.price_netto else None,
                'price_brutto': float(item.price_brutto) if item.price_brutto else None,
                'is_selected': item.is_selected,
                'discount_percentage': float(item.discount_percentage) if item.discount_percentage else 0,
                'quantity': detail.quantity if detail else 1,
                'finishing': {
                    'type': detail.finishing_type if detail else None,
                    'color': detail.finishing_color if detail else None,
                    'variant': detail.finishing_variant if detail else None
                } if detail else None
            })

        owner_name = None
        if quote.user:
            owner_name = quote.user.get_full_name() if quote.user else None

        return {
            'quote_number': quote.quote_number,
            'created_at': quote.created_at.strftime('%Y-%m-%d %H:%M') if quote.created_at else None,
            'status': quote.quote_status.name if quote.quote_status else 'Brak statusu',
            'status_color': quote.quote_status.color_hex if quote.quote_status else None,
            'client': {
                'name': quote.client.client_name if quote.client else None,
                'email': quote.client.email if quote.client else None,
                'phone': quote.client.phone if quote.client else None,
                'client_number': quote.client.client_number if quote.client else None
            } if quote.client else {'name': None, 'email': None, 'phone': None, 'client_number': None},
            'owner': owner_name,
            'total_price': float(quote.total_price) if quote.total_price else 0,
            'quote_type': quote.quote_type,
            'multiplier': float(quote.quote_multiplier) if quote.quote_multiplier else None,
            'client_type': quote.quote_client_type,
            'shipping': {
                'courier': quote.courier_name,
                'cost_netto': float(quote.shipping_cost_netto) if quote.shipping_cost_netto else None,
                'cost_brutto': float(quote.shipping_cost_brutto) if quote.shipping_cost_brutto else None
            } if quote.courier_name else None,
            'items': formatted_items,
            'items_count': len(formatted_items),
            'selected_items_count': len([i for i in formatted_items if i['is_selected']]),
            'baselinker_order_id': quote.base_linker_order_id,
            'acceptance_date': quote.acceptance_date.strftime('%Y-%m-%d %H:%M') if quote.acceptance_date else None,
            'accepted_by_email': quote.accepted_by_email,
            'notes': quote.notes,
            'client_comments': quote.client_comments,
            'source': quote.source
        }

    @staticmethod
    def _format_client_summary(client) -> Dict:
        return {
            'id': client.id,
            'client_number': client.client_number,
            'client_name': client.client_name,
            'email': client.email,
            'phone': client.phone,
            'city': client.delivery_city
        }

    @staticmethod
    def _format_client_full(client) -> Dict:
        return {
            'id': client.id,
            'client_number': client.client_number,
            'client_name': client.client_name,
            'email': client.email,
            'phone': client.phone,
            'delivery_address': {
                'name': client.delivery_name,
                'company': client.delivery_company,
                'address': client.delivery_address,
                'zip': client.delivery_zip,
                'city': client.delivery_city,
                'region': client.delivery_region,
                'country': client.delivery_country
            },
            'invoice_address': {
                'name': client.invoice_name,
                'company': client.invoice_company,
                'address': client.invoice_address,
                'zip': client.invoice_zip,
                'city': client.invoice_city,
                'nip': client.invoice_nip
            } if client.invoice_nip or client.invoice_company else None,
            'source': client.source,
            'notes': client.notes
        }

    # ------------------------------------------------------------------
    # Markdown formatters
    # ------------------------------------------------------------------
    def format_quote_response(self, quote_data: Dict) -> str:
        if not quote_data:
            return "Brak danych wyceny."

        lines = [
            f"**Wycena {quote_data.get('quote_number')}**",
            f"Data: {quote_data.get('created_at', 'brak')}",
            f"**Status:** {quote_data.get('status', 'nieznany')}"
        ]

        client = quote_data.get('client') or {}
        client_name = client.get('name')
        if client_name:
            lines.append(f"\n**Klient:** {client_name}")
            if client.get('email'):
                lines.append(f"Email: {client['email']}")
            if client.get('phone'):
                lines.append(f"Tel: {client['phone']}")
        else:
            lines.append(f"\n**Klient:** nieprzypisany")

        if quote_data.get('owner'):
            lines.append(f"\n**Opiekun:** {quote_data['owner']}")

        items = quote_data.get('items', [])
        selected_count = quote_data.get('selected_items_count', 0)
        lines.append(f"\n**Produkty ({selected_count} wybranych z {len(items)}):**")

        for item in items:
            if not item.get('is_selected'):
                continue
            qty = item.get('quantity', 1)
            dims = item.get('dimensions', 'brak wymiarów')
            price = item.get('price_brutto', 0)

            line = f"- {dims}"
            if qty > 1:
                line += f" x{qty}"
            line += f" = {price * qty:.2f} zł brutto"

            if item.get('discount_percentage', 0) > 0:
                line += f" (rabat {item['discount_percentage']}%)"

            finishing = item.get('finishing')
            if finishing and finishing.get('type'):
                line += f" [{finishing['type']}"
                if finishing.get('color'):
                    line += f" - {finishing['color']}"
                line += "]"
            lines.append(line)

        shipping = quote_data.get('shipping')
        if shipping:
            lines.append(f"\n**Wysyłka:** {shipping.get('courier', 'brak')} - {shipping.get('cost_brutto', 0):.2f} zł brutto")

        lines.append(f"\n**Wartość wyceny: {quote_data.get('total_price', 0):.2f} zł**")

        if quote_data.get('baselinker_order_id'):
            lines.append(f"\n**Zamówienie Baselinker:** #{quote_data['baselinker_order_id']}")

        if quote_data.get('acceptance_date'):
            lines.append(f"**Zaakceptowana:** {quote_data['acceptance_date']}")
            if quote_data.get('accepted_by_email'):
                lines.append(f"przez: {quote_data['accepted_by_email']}")

        if quote_data.get('notes'):
            lines.append(f"\n**Notatki:** {quote_data['notes']}")

        return "\n".join(lines)

    def format_client_response(self, client_data: Dict, recent_quotes: List[Dict] = None) -> str:
        if not client_data:
            return "Brak danych klienta."

        lines = [
            f"**Klient: {client_data.get('client_name')}**",
            f"Numer: {client_data.get('client_number', 'brak')}"
        ]

        if client_data.get('email'):
            lines.append(f"Email: {client_data['email']}")
        if client_data.get('phone'):
            lines.append(f"Tel: {client_data['phone']}")

        delivery = client_data.get('delivery_address', {})
        if delivery.get('city'):
            addr_parts = []
            if delivery.get('address'):
                addr_parts.append(delivery['address'])
            if delivery.get('zip'):
                addr_parts.append(delivery['zip'])
            if delivery.get('city'):
                addr_parts.append(delivery['city'])
            if addr_parts:
                lines.append(f"\n**Adres dostawy:**")
                lines.append(", ".join(addr_parts))

        invoice = client_data.get('invoice_address')
        if invoice and invoice.get('nip'):
            lines.append(f"\n**Dane do faktury:**")
            if invoice.get('company'):
                lines.append(f"Firma: {invoice['company']}")
            lines.append(f"NIP: {invoice['nip']}")

        if client_data.get('source'):
            lines.append(f"\n**Źródło:** {client_data['source']}")

        if client_data.get('notes'):
            lines.append(f"\n**Notatki:** {client_data['notes']}")

        if recent_quotes:
            lines.append(f"\n**Ostatnie wyceny ({len(recent_quotes)}):**")
            for q in recent_quotes:
                status = q.get('status', 'brak statusu')
                price = q.get('total_price', 0)
                has_order = "zamówienie" if q.get('has_order') else ""
                lines.append(f"- {q['quote_number']} ({status}) - {price:.2f} zł {has_order}")

        return "\n".join(lines)

    def format_quotes_list_response(self, quotes: List[Dict]) -> str:
        if not quotes:
            return "Nie znaleziono wycen."

        lines = [f"**Znaleziono {len(quotes)} wycen:**\n"]
        for q in quotes:
            status = q.get('status', 'brak statusu')
            client = q.get('client_name', 'brak klienta')
            price = q.get('total_price', 0)
            order_info = f" -> zamówienie #{q['order_id']}" if q.get('has_order') else ""
            lines.append(f"- **{q['quote_number']}** ({status})")
            lines.append(f"  Klient: {client} | Wartość: {price:.2f} zł{order_info}")

        return "\n".join(lines)

    def format_statistics_response(self, stats: Dict) -> str:
        if not stats:
            return "Brak danych statystycznych."

        s = stats
        lines = [
            f"**Statystyki wycen (ostatnie {s.get('period_days', 30)} dni):**\n",
            f"Łącznie wycen: **{s.get('total_quotes', 0)}**",
            f"Łączna wartość: **{s.get('total_value', 0):.2f} zł**",
            f"Średnia wartość: {s.get('average_value', 0):.2f} zł",
            f"Złożonych zamówień: {s.get('with_orders', 0)}",
            f"Konwersja: **{s.get('conversion_rate', 0)}%**",
        ]

        by_status = s.get('by_status', {})
        if by_status:
            lines.append("\n**Wg statusu:**")
            for status, count in by_status.items():
                lines.append(f"- {status}: {count}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def get_context_for_message(self, message: str, user) -> str:
        """
        Główny punkt wejścia — wywoływany z routera.
        Zwraca sformatowany markdown lub pusty string.
        """
        quote_number = _extract_quote_number(message)
        client_query = _extract_crm_client_query(message)
        message_lower = message.lower()

        try:
            # Konkretna wycena
            if quote_number:
                result = self.get_quote_details(user, quote_number)
                if result['success']:
                    return f"**Dane wyceny z CRM:**\n\n{self.format_quote_response(result['quote'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Zapytanie o klienta
            if client_query:
                result = self.get_client_details(user, client_query)
                if result['success']:
                    return f"**Dane klienta z CRM:**\n\n{self.format_client_response(result['client'], result.get('recent_quotes', []))}"
                else:
                    search_result = self.search_clients(user, client_query)
                    if search_result['success'] and search_result['clients']:
                        if len(search_result['clients']) == 1:
                            client = search_result['clients'][0]
                            detail_result = self.get_client_details(user, client['client_number'])
                            if detail_result['success']:
                                return f"**Dane klienta z CRM:**\n\n{self.format_client_response(detail_result['client'], detail_result.get('recent_quotes', []))}"
                        else:
                            clients_list = "\n".join([
                                f"- {c['client_name']} ({c.get('city', 'brak miasta')}) - {c.get('email', 'brak email')}"
                                for c in search_result['clients']
                            ])
                            return (
                                f"**Znaleziono {len(search_result['clients'])} klientów pasujących do \"{client_query}\":**\n\n"
                                f"{clients_list}\n\n"
                                f"Proszę doprecyzować, o którego klienta chodzi."
                            )
                    return f"**Nie znaleziono klienta:** {client_query}"

            # Statystyki
            if any(kw in message_lower for kw in ['statystyki', 'statystyka', 'ile wycen', 'suma wycen', 'wartość wycen']):
                days = 30
                if '7 dni' in message_lower or 'tydzień' in message_lower or 'tydzien' in message_lower:
                    days = 7
                elif '90 dni' in message_lower or '3 miesiące' in message_lower or '3 miesiac' in message_lower:
                    days = 90
                elif 'rok' in message_lower or '365' in message_lower:
                    days = 365

                result = self.get_quotes_statistics(user, days=days)
                if result['success']:
                    return f"**Dane z CRM:**\n\n{self.format_statistics_response(result['statistics'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Ostatnie wyceny
            if any(kw in message_lower for kw in ['ostatnie wyceny', 'moje wyceny', 'lista wycen', 'pokaż wyceny', 'pokaz wyceny']):
                status_name = None
                if 'zaakceptowan' in message_lower:
                    status_name = 'zaakceptowan'
                elif 'oczekuj' in message_lower or 'wysłan' in message_lower or 'wyslan' in message_lower:
                    status_name = 'wysłan'
                elif 'szkic' in message_lower or 'draft' in message_lower:
                    status_name = 'szkic'

                result = self.search_quotes(user, status_name=status_name, limit=10)
                if result['success']:
                    return f"**Dane z CRM:**\n\n{self.format_quotes_list_response(result['quotes'])}"
                else:
                    return f"**Błąd:** {result['error']}"

        except Exception as e:
            logger.error(f"Błąd pobierania kontekstu CRM: {e}")
            return f"**Błąd komunikacji z CRM:** {str(e)}"

        return ""
