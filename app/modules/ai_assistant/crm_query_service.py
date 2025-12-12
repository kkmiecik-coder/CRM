"""
Serwis do odpytywania lokalnej bazy CRM dla AI Assistant
Tylko READ-ONLY - bez modyfikacji danych
"""

import re
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from flask import current_app, session, has_request_context
from sqlalchemy import or_, func, desc

from extensions import db


class CRMQueryService:
    """
    Serwis do odpytywania lokalnej bazy CRM przez AI Assistant.
    Dostęp tylko do odczytu (READ-ONLY).
    Kontrola uprawnień: Admin/User widzą wszystko, Partner tylko swoje dane.
    """

    def __init__(self):
        self.logger = current_app.logger

    # =====================================================
    # METODY KONTROLI UPRAWNIEŃ
    # =====================================================

    def _get_current_user(self):
        """Pobiera aktualnie zalogowanego użytkownika"""
        from modules.users.models import User
        from .baselinker_ai_service import get_thread_user_id

        # Najpierw spróbuj z sesji (jeśli mamy request context)
        user_id = None
        if has_request_context():
            user_id = session.get('user_id')

        # Jeśli brak - użyj thread-local storage (dla wątków SSE)
        if not user_id:
            user_id = get_thread_user_id()

        if not user_id:
            return None
        return User.query.get(user_id)

    def _is_partner(self, user) -> bool:
        """Sprawdza czy użytkownik jest partnerem"""
        return user.role and user.role.lower() == 'partner'

    def _is_admin_or_user(self, user) -> bool:
        """Sprawdza czy użytkownik ma pełny dostęp"""
        return user.role and user.role.lower() in ['admin', 'administrator', 'user']

    def _can_access_quote(self, user, quote) -> bool:
        """Sprawdza czy użytkownik może zobaczyć wycenę"""
        if self._is_admin_or_user(user):
            return True
        if self._is_partner(user):
            return quote.user_id == user.id
        return False

    def _can_access_client(self, user, client) -> bool:
        """Sprawdza czy użytkownik może zobaczyć klienta"""
        if self._is_admin_or_user(user):
            return True
        if self._is_partner(user):
            from modules.calculator.models import Quote
            # Klient stworzony przez partnera
            if client.created_by_user_id == user.id:
                return True
            # Klient ma wycenę partnera
            has_quote = Quote.query.filter(
                Quote.client_id == client.id,
                Quote.user_id == user.id
            ).first()
            return has_quote is not None
        return False

    # =====================================================
    # WYCENY (QUOTES)
    # =====================================================

    def search_quotes(self, user, query: Optional[str] = None,
                     status_name: Optional[str] = None,
                     client_name: Optional[str] = None,
                     date_from: Optional[datetime] = None,
                     date_to: Optional[datetime] = None,
                     limit: int = 10) -> Dict:
        """
        Wyszukuje wyceny z filtrowaniem.

        Args:
            user: zalogowany użytkownik
            query: numer wyceny lub fragment
            status_name: nazwa statusu (np. "Zaakceptowane")
            client_name: imię/nazwisko klienta
            date_from: data od
            date_to: data do
            limit: max wyników

        Returns:
            {'success': True, 'quotes': [...]} lub {'success': False, 'error': '...'}
        """
        try:
            from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails
            from modules.quotes.models import QuoteStatus
            from modules.clients.models import Client

            base_query = Quote.query

            # Filtruj dla partnera
            if self._is_partner(user):
                base_query = base_query.filter(Quote.user_id == user.id)

            # Filtr po numerze wyceny
            if query:
                base_query = base_query.filter(
                    Quote.quote_number.ilike(f'%{query}%')
                )

            # Filtr po statusie
            if status_name:
                status = QuoteStatus.query.filter(
                    func.lower(QuoteStatus.name).like(f'%{status_name.lower()}%')
                ).first()
                if status:
                    base_query = base_query.filter(Quote.status_id == status.id)

            # Filtr po kliencie
            if client_name:
                client_ids = db.session.query(Client.id).filter(
                    func.lower(Client.client_name).like(f'%{client_name.lower()}%')
                ).all()
                client_ids = [c[0] for c in client_ids]
                if client_ids:
                    base_query = base_query.filter(Quote.client_id.in_(client_ids))
                else:
                    return {'success': True, 'quotes': [], 'message': f'Nie znaleziono klienta: {client_name}'}

            # Filtr po datach
            if date_from:
                base_query = base_query.filter(Quote.created_at >= date_from)
            if date_to:
                base_query = base_query.filter(Quote.created_at <= date_to)

            # Sortuj i ogranicz
            quotes = base_query.order_by(desc(Quote.created_at)).limit(limit).all()

            return {
                'success': True,
                'quotes': [self._format_quote_summary(q) for q in quotes],
                'count': len(quotes)
            }

        except Exception as e:
            self.logger.error(f"[CRMQuery] Błąd wyszukiwania wycen: {e}")
            return {'success': False, 'error': str(e)}

    def get_quote_details(self, user, quote_number: str) -> Dict:
        """
        Pobiera szczegóły wyceny po numerze.

        Args:
            user: zalogowany użytkownik
            quote_number: numer wyceny (np. "123/01/25/W")

        Returns:
            {'success': True, 'quote': {...}} lub {'success': False, 'error': '...'}
        """
        try:
            from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails
            from modules.quotes.models import QuoteStatus
            from modules.clients.models import Client

            self.logger.info(f"[CRMQuery] get_quote_details: szukam wyceny '{quote_number}'")

            # Znajdź wycenę - najpierw dokładne dopasowanie
            quote = Quote.query.filter(
                Quote.quote_number == quote_number
            ).first()

            # Jeśli nie znaleziono - spróbuj z ilike
            if not quote:
                self.logger.info(f"[CRMQuery] Dokładne dopasowanie nie znalazło, próbuję ilike")
                quote = Quote.query.filter(
                    Quote.quote_number.ilike(f'%{quote_number}%')
                ).first()

            # Debug: sprawdź jakie wyceny są w bazie (ostatnie 5)
            if not quote:
                recent_quotes = Quote.query.order_by(Quote.id.desc()).limit(5).all()
                quote_nums = [q.quote_number for q in recent_quotes]
                self.logger.info(f"[CRMQuery] Nie znaleziono. Ostatnie 5 wycen w bazie: {quote_nums}")

                # Sprawdź czy mamy w ogóle wyceny
                total_count = Quote.query.count()
                self.logger.info(f"[CRMQuery] Łączna liczba wycen w bazie: {total_count}")

                return {'success': False, 'error': f'Nie znaleziono wyceny: {quote_number}'}

            self.logger.info(f"[CRMQuery] Znaleziono wycenę: {quote.quote_number} (id={quote.id})")

            # Sprawdź uprawnienia
            if not self._can_access_quote(user, quote):
                return {'success': False, 'error': 'Nie masz uprawnień do tej wyceny.'}

            return {
                'success': True,
                'quote': self._format_quote_full(quote)
            }

        except Exception as e:
            self.logger.error(f"[CRMQuery] Błąd pobierania wyceny: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    def get_quotes_statistics(self, user, days: int = 30) -> Dict:
        """
        Pobiera statystyki wycen za ostatnie N dni.
        """
        try:
            from modules.calculator.models import Quote
            from modules.quotes.models import QuoteStatus

            date_from = datetime.utcnow() - timedelta(days=days)

            base_query = Quote.query.filter(Quote.created_at >= date_from)

            # Filtruj dla partnera
            if self._is_partner(user):
                base_query = base_query.filter(Quote.user_id == user.id)

            quotes = base_query.all()

            total_count = len(quotes)
            total_value = sum(float(q.total_price or 0) for q in quotes)

            # Status counts
            status_counts = {}
            for q in quotes:
                status_name = q.quote_status.name if q.quote_status else 'Brak statusu'
                status_counts[status_name] = status_counts.get(status_name, 0) + 1

            # Wyceny z zamówieniami BL
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
            self.logger.error(f"[CRMQuery] Błąd statystyk wycen: {e}")
            return {'success': False, 'error': str(e)}

    # =====================================================
    # KLIENCI (CLIENTS)
    # =====================================================

    def search_clients(self, user, query: str, limit: int = 10) -> Dict:
        """
        Wyszukuje klientów po nazwie, email lub telefonie.
        """
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            self.logger.info(f"[CRMQuery] search_clients: szukam klienta '{query}'")

            # Buduj filtr
            search_filter = or_(
                func.lower(Client.client_name).like(f'%{query.lower()}%'),
                func.lower(Client.email).like(f'%{query.lower()}%'),
                Client.phone.like(f'%{query}%'),
                Client.client_number.like(f'%{query}%')
            )

            base_query = Client.query.filter(search_filter)

            # Dla partnera - tylko dostępni klienci
            if self._is_partner(user):
                # Klienci stworzeni przez partnera
                own_client_ids = db.session.query(Client.id).filter(
                    Client.created_by_user_id == user.id
                ).all()
                own_client_ids = [c[0] for c in own_client_ids]

                # Klienci z wycen partnera
                quote_client_ids = db.session.query(Quote.client_id).filter(
                    Quote.user_id == user.id,
                    Quote.client_id.isnot(None)
                ).distinct().all()
                quote_client_ids = [c[0] for c in quote_client_ids]

                accessible_ids = list(set(own_client_ids + quote_client_ids))

                if not accessible_ids:
                    return {'success': True, 'clients': [], 'count': 0}

                base_query = base_query.filter(Client.id.in_(accessible_ids))

            clients = base_query.limit(limit).all()

            self.logger.info(f"[CRMQuery] search_clients: znaleziono {len(clients)} klientów")

            return {
                'success': True,
                'clients': [self._format_client_summary(c) for c in clients],
                'count': len(clients)
            }

        except Exception as e:
            self.logger.error(f"[CRMQuery] Błąd wyszukiwania klientów: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    def get_client_details(self, user, client_identifier: str) -> Dict:
        """
        Pobiera szczegóły klienta po numerze lub nazwie.
        """
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            self.logger.info(f"[CRMQuery] get_client_details: szukam klienta '{client_identifier}'")

            # Szukaj po numerze lub nazwie
            client = Client.query.filter(
                or_(
                    Client.client_number == client_identifier,
                    func.lower(Client.client_name).like(f'%{client_identifier.lower()}%')
                )
            ).first()

            if not client:
                # Debug: sprawdź ile jest klientów w bazie
                total_count = Client.query.count()
                self.logger.info(f"[CRMQuery] Nie znaleziono. Łączna liczba klientów w bazie: {total_count}")
                return {'success': False, 'error': f'Nie znaleziono klienta: {client_identifier}'}

            self.logger.info(f"[CRMQuery] Znaleziono klienta: {client.client_name} (id={client.id})")

            # Sprawdź uprawnienia
            if not self._can_access_client(user, client):
                return {'success': False, 'error': 'Nie masz uprawnień do tego klienta.'}

            # Pobierz wyceny klienta
            quotes_query = Quote.query.filter(Quote.client_id == client.id)
            if self._is_partner(user):
                quotes_query = quotes_query.filter(Quote.user_id == user.id)

            recent_quotes = quotes_query.order_by(desc(Quote.created_at)).limit(5).all()

            return {
                'success': True,
                'client': self._format_client_full(client),
                'recent_quotes': [self._format_quote_summary(q) for q in recent_quotes]
            }

        except Exception as e:
            self.logger.error(f"[CRMQuery] Błąd pobierania klienta: {e}")
            return {'success': False, 'error': str(e)}

    def get_client_quotes_summary(self, user, client_id: int) -> Dict:
        """
        Pobiera podsumowanie wycen dla klienta.
        """
        try:
            from modules.clients.models import Client
            from modules.calculator.models import Quote

            client = Client.query.get(client_id)
            if not client:
                return {'success': False, 'error': 'Klient nie znaleziony'}

            if not self._can_access_client(user, client):
                return {'success': False, 'error': 'Nie masz uprawnień do tego klienta.'}

            quotes_query = Quote.query.filter(Quote.client_id == client_id)
            if self._is_partner(user):
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
            self.logger.error(f"[CRMQuery] Błąd podsumowania klienta: {e}")
            return {'success': False, 'error': str(e)}

    # =====================================================
    # STATUSY WYCEN
    # =====================================================

    def get_quote_statuses(self) -> Dict:
        """
        Zwraca listę wszystkich statusów wycen.
        """
        try:
            from modules.quotes.models import QuoteStatus

            statuses = QuoteStatus.query.all()

            return {
                'success': True,
                'statuses': [
                    {
                        'id': s.id,
                        'name': s.name,
                        'color': s.color_hex
                    }
                    for s in statuses
                ]
            }

        except Exception as e:
            self.logger.error(f"[CRMQuery] Błąd pobierania statusów: {e}")
            return {'success': False, 'error': str(e)}

    # =====================================================
    # FORMATOWANIE DANYCH
    # =====================================================

    def _format_quote_summary(self, quote) -> Dict:
        """Formatuje wycenę do krótkiego podsumowania"""
        return {
            'quote_number': quote.quote_number,
            'created_at': quote.created_at.strftime('%Y-%m-%d %H:%M') if quote.created_at else None,
            'status': quote.quote_status.name if quote.quote_status else 'Brak statusu',
            'client_name': quote.client.client_name if quote.client else 'Brak klienta',
            'total_price': float(quote.total_price) if quote.total_price else 0,
            'has_order': bool(quote.base_linker_order_id),
            'order_id': quote.base_linker_order_id
        }

    def _format_quote_full(self, quote) -> Dict:
        """Formatuje wycenę ze wszystkimi szczegółami"""
        from modules.calculator.models import QuoteItem, QuoteItemDetails

        # Pobierz pozycje
        items = list(quote.items)

        # Pobierz szczegóły pozycji
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

        # Opiekun wyceny
        owner_name = None
        if quote.user:
            owner_name = quote.user.name if hasattr(quote.user, 'name') else quote.user.username

        return {
            'quote_number': quote.quote_number,
            'created_at': quote.created_at.strftime('%Y-%m-%d %H:%M') if quote.created_at else None,
            'status': quote.quote_status.name if quote.quote_status else 'Brak statusu',
            'status_color': quote.quote_status.color_hex if quote.quote_status else None,

            # Klient
            'client': {
                'name': quote.client.client_name if quote.client else None,
                'email': quote.client.email if quote.client else None,
                'phone': quote.client.phone if quote.client else None,
                'client_number': quote.client.client_number if quote.client else None
            } if quote.client else None,

            # Opiekun
            'owner': owner_name,

            # Finanse
            'total_price': float(quote.total_price) if quote.total_price else 0,
            'quote_type': quote.quote_type,  # 'brutto' lub 'netto'
            'multiplier': float(quote.quote_multiplier) if quote.quote_multiplier else None,
            'client_type': quote.quote_client_type,

            # Wysyłka
            'shipping': {
                'courier': quote.courier_name,
                'cost_netto': float(quote.shipping_cost_netto) if quote.shipping_cost_netto else None,
                'cost_brutto': float(quote.shipping_cost_brutto) if quote.shipping_cost_brutto else None
            } if quote.courier_name else None,

            # Pozycje
            'items': formatted_items,
            'items_count': len(formatted_items),
            'selected_items_count': len([i for i in formatted_items if i['is_selected']]),

            # Baselinker
            'baselinker_order_id': quote.base_linker_order_id,

            # Akceptacja
            'acceptance_date': quote.acceptance_date.strftime('%Y-%m-%d %H:%M') if quote.acceptance_date else None,
            'accepted_by_email': quote.accepted_by_email,

            # Notatki
            'notes': quote.notes,
            'client_comments': quote.client_comments,

            # Źródło
            'source': quote.source
        }

    def _format_client_summary(self, client) -> Dict:
        """Formatuje klienta do krótkiego podsumowania"""
        return {
            'id': client.id,
            'client_number': client.client_number,
            'client_name': client.client_name,
            'email': client.email,
            'phone': client.phone,
            'city': client.delivery_city
        }

    def _format_client_full(self, client) -> Dict:
        """Formatuje klienta ze wszystkimi szczegółami"""
        return {
            'id': client.id,
            'client_number': client.client_number,
            'client_name': client.client_name,
            'email': client.email,
            'phone': client.phone,

            # Adres dostawy
            'delivery_address': {
                'name': client.delivery_name,
                'company': client.delivery_company,
                'address': client.delivery_address,
                'zip': client.delivery_zip,
                'city': client.delivery_city,
                'region': client.delivery_region,
                'country': client.delivery_country
            },

            # Adres fakturowy
            'invoice_address': {
                'name': client.invoice_name,
                'company': client.invoice_company,
                'address': client.invoice_address,
                'zip': client.invoice_zip,
                'city': client.invoice_city,
                'nip': client.invoice_nip
            } if client.invoice_nip or client.invoice_company else None,

            # Meta
            'source': client.source,
            'notes': client.notes
        }

    # =====================================================
    # FORMATOWANIE ODPOWIEDZI DLA AI (MARKDOWN)
    # =====================================================

    def format_quote_response(self, quote_data: Dict) -> str:
        """Formatuje wycenę do czytelnej odpowiedzi tekstowej (markdown)"""
        if not quote_data:
            return "Brak danych wyceny."

        lines = [
            f"**Wycena {quote_data.get('quote_number')}**",
            f"Data: {quote_data.get('created_at', 'brak')}",
            f"**Status:** {quote_data.get('status', 'nieznany')}"
        ]

        # Klient
        client = quote_data.get('client')
        if client:
            lines.append(f"\n**Klient:** {client.get('name', 'brak')}")
            if client.get('email'):
                lines.append(f"Email: {client['email']}")
            if client.get('phone'):
                lines.append(f"Tel: {client['phone']}")

        # Opiekun
        if quote_data.get('owner'):
            lines.append(f"\n**Opiekun:** {quote_data['owner']}")

        # Pozycje
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

        # Wysyłka
        shipping = quote_data.get('shipping')
        if shipping:
            lines.append(f"\n**Wysyłka:** {shipping.get('courier', 'brak')} - {shipping.get('cost_brutto', 0):.2f} zł brutto")

        # Podsumowanie
        lines.append(f"\n**Wartość wyceny: {quote_data.get('total_price', 0):.2f} zł**")

        # Baselinker
        if quote_data.get('baselinker_order_id'):
            lines.append(f"\n**Zamówienie Baselinker:** #{quote_data['baselinker_order_id']}")

        # Akceptacja
        if quote_data.get('acceptance_date'):
            lines.append(f"**Zaakceptowana:** {quote_data['acceptance_date']}")
            if quote_data.get('accepted_by_email'):
                lines.append(f"przez: {quote_data['accepted_by_email']}")

        # Notatki
        if quote_data.get('notes'):
            lines.append(f"\n**Notatki:** {quote_data['notes']}")

        return "\n".join(lines)

    def format_client_response(self, client_data: Dict, recent_quotes: List[Dict] = None) -> str:
        """Formatuje klienta do czytelnej odpowiedzi tekstowej"""
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

        # Adres dostawy
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

        # Dane fakturowe
        invoice = client_data.get('invoice_address')
        if invoice and invoice.get('nip'):
            lines.append(f"\n**Dane do faktury:**")
            if invoice.get('company'):
                lines.append(f"Firma: {invoice['company']}")
            lines.append(f"NIP: {invoice['nip']}")

        # Źródło
        if client_data.get('source'):
            lines.append(f"\n**Źródło:** {client_data['source']}")

        # Notatki
        if client_data.get('notes'):
            lines.append(f"\n**Notatki:** {client_data['notes']}")

        # Ostatnie wyceny
        if recent_quotes:
            lines.append(f"\n**Ostatnie wyceny ({len(recent_quotes)}):**")
            for q in recent_quotes:
                status = q.get('status', 'brak statusu')
                price = q.get('total_price', 0)
                has_order = "✓ zamówienie" if q.get('has_order') else ""
                lines.append(f"- {q['quote_number']} ({status}) - {price:.2f} zł {has_order}")

        return "\n".join(lines)

    def format_quotes_list_response(self, quotes: List[Dict]) -> str:
        """Formatuje listę wycen"""
        if not quotes:
            return "Nie znaleziono wycen."

        lines = [f"**Znaleziono {len(quotes)} wycen:**\n"]

        for q in quotes:
            status = q.get('status', 'brak statusu')
            client = q.get('client_name', 'brak klienta')
            price = q.get('total_price', 0)
            order_info = f" → zamówienie #{q['order_id']}" if q.get('has_order') else ""

            lines.append(f"- **{q['quote_number']}** ({status})")
            lines.append(f"  Klient: {client} | Wartość: {price:.2f} zł{order_info}")

        return "\n".join(lines)

    def format_statistics_response(self, stats: Dict) -> str:
        """Formatuje statystyki"""
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

        # Status breakdown
        by_status = s.get('by_status', {})
        if by_status:
            lines.append("\n**Wg statusu:**")
            for status, count in by_status.items():
                lines.append(f"- {status}: {count}")

        return "\n".join(lines)
