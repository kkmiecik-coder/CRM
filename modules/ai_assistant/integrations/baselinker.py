"""
Integracja AI Assistant z Baselinker API
Odpytywanie zamówień z kontrolą uprawnień, rate limitingiem i cache
"""

import re
import time
import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from flask import current_app
from extensions import db
from modules.ai_assistant.services.cache_service import CacheService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Słownik zdrobnień polskich imion
# ---------------------------------------------------------------------------
POLISH_NAME_DIMINUTIVES = {
    # Męskie
    'zbigniew': ['zbyszek', 'zbysio', 'zbysiu'],
    'krzysztof': ['krzysiek', 'krzyś', 'krzysio'],
    'jan': ['janek', 'jasiek', 'jasio'],
    'stanislaw': ['staszek', 'staś', 'stasio'],
    'piotr': ['piotrek', 'piotruś'],
    'andrzej': ['andrzejek', 'jędrek', 'jędruś'],
    'tomasz': ['tomek', 'tomuś'],
    'michal': ['michał', 'misiek', 'michałek'],
    'wojciech': ['wojtek', 'wojtuś'],
    'adam': ['adaś', 'adamek'],
    'marek': ['mareczek', 'maruś'],
    'pawel': ['paweł', 'pawełek'],
    'lukasz': ['łukasz', 'łukaszek'],
    'marcin': ['marcinek'],
    'jacek': ['jacuś'],
    'robert': ['robercik'],
    'grzegorz': ['grzesiek', 'grześ'],
    'dariusz': ['darek', 'daro'],
    'mariusz': ['mariuszek'],
    'rafal': ['rafał', 'rafałek'],
    'jozef': ['józef', 'józek', 'józio'],
    'tadeusz': ['tadek', 'tadzio'],
    'jerzy': ['jurek', 'jureczek'],
    'henryk': ['heniek', 'henio'],
    'kazimierz': ['kazik', 'kazio'],
    'stefan': ['stefek', 'stefcio'],
    'wladyslaw': ['władysław', 'władek', 'władzio'],
    'bogdan': ['bogdanek'],
    'leszek': ['leszeczek'],
    'ryszard': ['rysiek', 'ryśko'],
    'edward': ['edek', 'edzio'],
    'miroslaw': ['mirosław', 'mirek', 'mireczek'],
    'wieslaw': ['wiesław', 'wiesiek', 'wiesio'],
    'zdzislaw': ['zdzisław', 'zdzisiek', 'zdzicho'],
    'czeslaw': ['czesław', 'czesiek', 'czesio'],
    'roman': ['romek', 'romanek'],
    'artur': ['arturek'],
    'sebastian': ['sebek', 'sebuś'],
    'karol': ['karolek'],
    'konrad': ['konradek'],
    'przemyslaw': ['przemysław', 'przemek', 'przemuś'],
    'dominik': ['dominiczek'],
    'damian': ['damianek'],
    'patryk': ['patyczek'],
    'kamil': ['kamilek'],
    'dawid': ['dawidek'],
    'jakub': ['kuba', 'kubuś'],
    'mateusz': ['mateuszek', 'mati'],
    'szymon': ['szymonek', 'szymek'],
    'filip': ['filipek'],
    'bartosz': ['bartek', 'barteczek'],
    'maciej': ['maciek', 'maciuś'],
    # Żeńskie
    'barbara': ['basia', 'baśka'],
    'anna': ['ania', 'anka', 'aneczka'],
    'maria': ['marysia', 'maryśka'],
    'katarzyna': ['kasia', 'kaśka', 'kasieńka'],
    'malgorzata': ['małgorzata', 'małgosia', 'gosia', 'gośka'],
    'agnieszka': ['aga', 'agusia', 'agnisia'],
    'krystyna': ['krysia', 'kryśka'],
    'elzbieta': ['elżbieta', 'ela', 'elka', 'elżunia'],
    'teresa': ['terenia', 'tereska'],
    'joanna': ['asia', 'joasia', 'joanusia'],
    'magdalena': ['magda', 'madzia', 'magdusia'],
    'monika': ['monia', 'monisia'],
    'aleksandra': ['ola', 'oleńka', 'alka'],
    'dorota': ['dorotka', 'dorcia'],
    'ewa': ['ewka', 'ewunia'],
    'justyna': ['justynka'],
    'beata': ['beatka'],
    'iwona': ['iwonka'],
    'renata': ['renatka'],
    'danuta': ['danka', 'danusia'],
    'halina': ['hala', 'halinka'],
    'irena': ['irenka', 'irka'],
    'zofia': ['zosia', 'zośka'],
    'jadwiga': ['jadzia', 'jadźka'],
    'helena': ['helenka', 'hela'],
    'natalia': ['natalka', 'nati'],
    'karolina': ['karolinka', 'karo'],
    'paulina': ['paula', 'paulinka'],
    'weronika': ['wera', 'weronka'],
    'sylwia': ['sylwka'],
    'aneta': ['anetka'],
    'edyta': ['edytka'],
    'marta': ['martusia', 'martuś'],
    'patrycja': ['patka', 'pati'],
    'kinga': ['kingusia'],
    'dominika': ['dominiczka'],
}


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """Rate limiter per user — max N requests per minute."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[int, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> Tuple[bool, Optional[int]]:
        now = time.time()
        window_start = now - self.window_seconds

        self._requests[user_id] = [
            ts for ts in self._requests[user_id]
            if ts > window_start
        ]

        if len(self._requests[user_id]) >= self.max_requests:
            oldest = min(self._requests[user_id])
            wait_time = int(oldest + self.window_seconds - now) + 1
            return False, wait_time

        return True, None

    def record_request(self, user_id: int):
        self._requests[user_id].append(time.time())


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------
def _extract_order_id(message: str) -> Optional[int]:
    """Wyciąga ID zamówienia Baselinker z wiadomości."""
    patterns = [
        r'zamówieni[ae]\s*(?:#|nr|numer|id)?[:\s]*(\d{7,10})',
        r'zamowieni[ae]\s*(?:#|nr|numer|id)?[:\s]*(\d{7,10})',
        r'order\s*(?:#|id)?[:\s]*(\d{7,10})',
        r'bl\s*(?:#|id)?[:\s]*(\d{7,10})',
        r'baselinker\s*(?:#|id)?[:\s]*(\d{7,10})',
        r'#(\d{7,10})',
        r'(?:^|\s)(\d{8})(?:\s|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_client_name(message: str) -> Optional[str]:
    """Wyciąga imię/nazwisko klienta z wiadomości (kontekst BL)."""
    patterns = [
        r'zamówieni[ae]\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
        r'zamowieni[ae]\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
        r'klient[a]?\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
        r'(?:znajd[źz]|szukaj)\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
        r'(?:status|sprawdź|sprawdz)\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
    ]
    skip_words = ['zamówienie', 'zamowienie', 'status', 'baselinker', 'order']
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if name.lower() not in skip_words:
                return name
    return None


# ---------------------------------------------------------------------------
# BaselinkerIntegration
# ---------------------------------------------------------------------------
class BaselinkerIntegration:
    """
    Integracja z Baselinker API dla AI Assistant.
    Kontrola uprawnień, rate limiting, cache (local DB first).
    """

    _rate_limiter = RateLimiter(max_requests=5, window_seconds=60)

    def __init__(self):
        self._bl_service = None
        self.cache = CacheService()

    @property
    def bl_service(self):
        if self._bl_service is None:
            from modules.baselinker.service import BaselinkerService
            self._bl_service = BaselinkerService()
        return self._bl_service

    # ------------------------------------------------------------------
    # Access control helpers (using User model methods)
    # ------------------------------------------------------------------
    def _can_access_order(self, user, baselinker_order_id: int) -> bool:
        if user.is_admin() or user.is_user():
            return True
        if user.is_partner():
            from modules.calculator.models import Quote
            quote = Quote.query.filter(
                Quote.base_linker_order_id == str(baselinker_order_id),
                Quote.user_id == user.id
            ).first()
            return quote is not None
        return False

    def _can_access_client(self, user, client) -> bool:
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

    def _get_partner_accessible_order_ids(self, user) -> List[int]:
        if not user.is_partner():
            return []
        from modules.calculator.models import Quote
        quotes = Quote.query.filter(
            Quote.user_id == user.id,
            Quote.base_linker_order_id.isnot(None)
        ).all()
        order_ids = []
        for q in quotes:
            try:
                order_ids.append(int(q.base_linker_order_id))
            except (ValueError, TypeError):
                pass
        return order_ids

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def check_rate_limit(self, user) -> Tuple[bool, Optional[str]]:
        allowed, wait_time = self._rate_limiter.is_allowed(user.id)
        if not allowed:
            return False, f"Przekroczono limit zapytań. Poczekaj {wait_time} sekund i spróbuj ponownie."
        return True, None

    def record_api_call(self, user):
        self._rate_limiter.record_request(user.id)

    # ------------------------------------------------------------------
    # Name search helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_name(name: str) -> str:
        name = name.lower().strip()
        replacements = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
            'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z'
        }
        for pl, ascii_char in replacements.items():
            name = name.replace(pl, ascii_char)
        return name

    @classmethod
    def _get_name_variants(cls, name: str) -> List[str]:
        normalized = cls._normalize_name(name)
        variants = {normalized, name.lower()}

        for full_name, diminutives in POLISH_NAME_DIMINUTIVES.items():
            normalized_diminutives = [cls._normalize_name(d) for d in diminutives]
            if normalized in normalized_diminutives:
                variants.add(full_name)
                variants.add(cls._normalize_name(full_name))

        if normalized in POLISH_NAME_DIMINUTIVES:
            for dim in POLISH_NAME_DIMINUTIVES[normalized]:
                variants.add(dim.lower())
                variants.add(cls._normalize_name(dim))

        for v in list(variants):
            variants.add(cls._normalize_name(v))

        return list(variants)

    # ------------------------------------------------------------------
    # Client search
    # ------------------------------------------------------------------
    def search_clients_by_name(self, name_query: str, user) -> List[Dict]:
        from modules.clients.models import Client
        from modules.calculator.models import Quote
        from sqlalchemy import or_, func

        words = name_query.strip().split()
        all_variants: List[str] = []
        for word in words:
            all_variants.extend(self._get_name_variants(word))

        if user.is_partner():
            own_client_ids = [c[0] for c in db.session.query(Client.id).filter(
                Client.created_by_user_id == user.id
            ).all()]
            quote_client_ids = [c[0] for c in db.session.query(Quote.client_id).filter(
                Quote.user_id == user.id,
                Quote.client_id.isnot(None)
            ).distinct().all()]
            accessible_client_ids = list(set(own_client_ids + quote_client_ids))
            if not accessible_client_ids:
                return []

            name_filters = []
            for variant in all_variants:
                pattern = f"%{variant}%"
                name_filters.append(func.lower(Client.client_name).like(pattern))
                name_filters.append(func.lower(Client.delivery_name).like(pattern))

            clients = Client.query.filter(
                Client.id.in_(accessible_client_ids),
                or_(*name_filters)
            ).limit(10).all()
        else:
            name_filters = []
            for variant in all_variants:
                pattern = f"%{variant}%"
                name_filters.append(func.lower(Client.client_name).like(pattern))
                name_filters.append(func.lower(Client.delivery_name).like(pattern))
            clients = Client.query.filter(or_(*name_filters)).limit(10).all()

        return [
            {
                'id': c.id,
                'client_number': getattr(c, 'client_number', None),
                'client_name': c.client_name,
                'email': c.email,
                'phone': c.phone,
                'city': getattr(c, 'delivery_city', None)
            }
            for c in clients
        ]

    # ------------------------------------------------------------------
    # Order fetching (local DB first, then BL API with cache)
    # ------------------------------------------------------------------
    def _get_local_order_data(self, order_id: int) -> Optional[Dict]:
        """Sprawdza lokalną bazę (Quote) pod kątem danych zamówienia."""
        from modules.calculator.models import Quote
        quote = Quote.query.filter(
            Quote.base_linker_order_id == str(order_id)
        ).first()
        if not quote:
            return None
        return {
            'quote_number': quote.quote_number,
            'client_name': quote.client.client_name if quote.client else None,
            'status': quote.quote_status.name if quote.quote_status else None,
            'total_price': float(quote.total_price) if quote.total_price else 0,
        }

    def get_order_by_id(self, order_id: int, user) -> Dict:
        if not self._can_access_order(user, order_id):
            return {
                'success': False,
                'error': 'Nie masz uprawnień do tego zamówienia. Jako partner widzisz tylko zamówienia z własnych wycen.'
            }

        allowed, error = self.check_rate_limit(user)
        if not allowed:
            return {'success': False, 'error': error}

        # Cache check
        cache_key = f'bl:order:{order_id}'
        cached = self.cache.get(cache_key)
        if cached:
            return {'success': True, 'order': cached}

        self.record_api_call(user)

        try:
            response = self.bl_service._make_request('getOrders', {
                'order_id': order_id,
                'include_custom_extra_fields': True
            })

            if response.get('status') != 'SUCCESS':
                return {
                    'success': False,
                    'error': response.get('error_message', 'Błąd API Baselinker')
                }

            orders = response.get('orders', [])
            if not orders:
                return {
                    'success': False,
                    'error': f'Nie znaleziono zamówienia o ID {order_id} w systemie Baselinker.'
                }

            formatted = self._format_order_for_ai(orders[0])
            self.cache.set(cache_key, formatted)
            return {'success': True, 'order': formatted}

        except Exception as e:
            logger.error(f"Błąd pobierania zamówienia {order_id}: {e}")
            return {
                'success': False,
                'error': f'Błąd komunikacji z Baselinker: {str(e)}'
            }

    def get_orders_for_client(self, client_id: int, user, limit: int = 5) -> Dict:
        from modules.clients.models import Client
        from modules.calculator.models import Quote

        client = Client.query.get(client_id)
        if not client:
            return {'success': False, 'error': 'Klient nie znaleziony'}

        if not self._can_access_client(user, client):
            return {'success': False, 'error': 'Nie mogę udzielić odpowiedzi - to nie Twój klient.'}

        quotes_query = Quote.query.filter(
            Quote.client_id == client_id,
            Quote.base_linker_order_id.isnot(None)
        )
        if user.is_partner():
            quotes_query = quotes_query.filter(Quote.user_id == user.id)

        quotes = quotes_query.order_by(Quote.created_at.desc()).limit(limit).all()

        if not quotes:
            return {
                'success': True,
                'client': {'id': client.id, 'name': client.client_name, 'email': client.email},
                'orders': [],
                'message': 'Brak zamówień dla tego klienta'
            }

        allowed, error = self.check_rate_limit(user)
        if not allowed:
            return {'success': False, 'error': error}

        self.record_api_call(user)

        orders_data = []
        for quote in quotes:
            try:
                bl_order_id = int(quote.base_linker_order_id)

                # Cache check per order
                cache_key = f'bl:order:{bl_order_id}'
                cached = self.cache.get(cache_key)
                if cached:
                    cached['quote_number'] = quote.quote_number
                    orders_data.append(cached)
                    continue

                response = self.bl_service._make_request('getOrders', {
                    'order_id': bl_order_id,
                    'include_custom_extra_fields': True
                })
                if response.get('status') == 'SUCCESS':
                    bl_orders = response.get('orders', [])
                    if bl_orders:
                        formatted = self._format_order_for_ai(bl_orders[0])
                        self.cache.set(cache_key, formatted)
                        formatted['quote_number'] = quote.quote_number
                        orders_data.append(formatted)
            except Exception as e:
                logger.warning(f"Błąd pobierania zamówienia {quote.base_linker_order_id}: {e}")

        return {
            'success': True,
            'client': {
                'id': client.id,
                'name': client.client_name,
                'email': client.email,
                'phone': client.phone
            },
            'orders': orders_data
        }

    def get_partner_statistics(self, user) -> Dict:
        if not user.is_partner():
            return {'success': False, 'error': 'Ta funkcja jest dostępna tylko dla partnerów'}

        from modules.calculator.models import Quote
        quotes = Quote.query.filter(Quote.user_id == user.id).all()

        total_quotes = len(quotes)
        quotes_with_orders = [q for q in quotes if q.base_linker_order_id]
        total_orders = len(quotes_with_orders)
        total_value = sum(float(q.total_price or 0) for q in quotes_with_orders)

        return {
            'success': True,
            'stats': {
                'total_quotes': total_quotes,
                'total_orders': total_orders,
                'total_value': round(total_value, 2),
                'conversion_rate': round(total_orders / total_quotes * 100, 1) if total_quotes > 0 else 0
            }
        }

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------
    def _get_status_name(self, status_id: int) -> str:
        if not status_id:
            return "Nieznany"
        try:
            from modules.baselinker.models import BaselinkerConfig
            config = BaselinkerConfig.query.filter_by(
                config_type='order_status',
                baselinker_id=status_id
            ).first()
            if config:
                return config.name
            return f"Status #{status_id}"
        except Exception:
            return f"Status #{status_id}"

    def _format_order_for_ai(self, order: Dict) -> Dict:
        date_add = order.get('date_add')
        if date_add:
            date_add = datetime.fromtimestamp(date_add).strftime('%Y-%m-%d %H:%M')

        date_confirmed = order.get('date_confirmed')
        if date_confirmed:
            date_confirmed = datetime.fromtimestamp(date_confirmed).strftime('%Y-%m-%d %H:%M')

        products = []
        for p in order.get('products', []):
            products.append({
                'name': p.get('name'),
                'quantity': p.get('quantity'),
                'price_brutto': p.get('price_brutto'),
                'sku': p.get('sku')
            })

        total_products = sum(
            float(p.get('price_brutto', 0)) * int(p.get('quantity', 1))
            for p in order.get('products', [])
        )
        delivery_price = float(order.get('delivery_price', 0))
        payment_done = float(order.get('payment_done', 0))

        status_id = order.get('order_status_id')
        status_name = self._get_status_name(status_id)

        total_value = total_products + delivery_price
        is_paid = payment_done >= total_value if total_value > 0 else False
        payment_remaining = max(0, total_value - payment_done)

        return {
            'order_id': order.get('order_id'),
            'internal_number': order.get('extra_field_1'),
            'date_created': date_add,
            'date_confirmed': date_confirmed,
            'status_id': status_id,
            'status_name': status_name,
            'client_name': order.get('user_login') or order.get('delivery_fullname'),
            'email': order.get('email'),
            'phone': order.get('phone'),
            'delivery_address': order.get('delivery_address'),
            'delivery_city': order.get('delivery_city'),
            'delivery_postcode': order.get('delivery_postcode'),
            'products': products,
            'products_count': len(products),
            'products_value': round(total_products, 2),
            'delivery_price': delivery_price,
            'total_value': round(total_value, 2),
            'payment_done': payment_done,
            'is_paid': is_paid,
            'payment_remaining': round(payment_remaining, 2),
            'delivery_method': order.get('delivery_method'),
            'payment_method': order.get('payment_method'),
            'admin_comments': order.get('admin_comments'),
            'user_comments': order.get('user_comments'),
            'order_page': order.get('order_page')
        }

    def format_order_response(self, order_data: Dict) -> str:
        """Formatuje dane zamówienia do czytelnej odpowiedzi markdown."""
        if not order_data:
            return "Brak danych zamówienia."

        lines = [
            f"**Zamówienie #{order_data.get('order_id')}**",
        ]

        if order_data.get('internal_number'):
            lines.append(f"Numer wewnętrzny: {order_data['internal_number']}")

        lines.append(f"Data: {order_data.get('date_created', 'brak')}")
        lines.append(f"**Status:** {order_data.get('status_name', 'Nieznany')}")

        if order_data.get('is_paid'):
            lines.append(f"**Płatność:** OPŁACONE ({order_data.get('payment_done', 0):.2f} zł)")
        else:
            remaining = order_data.get('payment_remaining', 0)
            paid = order_data.get('payment_done', 0)
            lines.append(f"**Płatność:** Wpłacono {paid:.2f} zł, do zapłaty {remaining:.2f} zł")

        lines.append(f"\n**Klient:** {order_data.get('client_name', 'brak')}")
        if order_data.get('phone'):
            lines.append(f"Tel: {order_data['phone']}")
        if order_data.get('email'):
            lines.append(f"Email: {order_data['email']}")

        if order_data.get('delivery_address'):
            lines.append(f"\n**Adres dostawy:**")
            lines.append(f"{order_data.get('delivery_address')}")
            lines.append(f"{order_data.get('delivery_postcode')} {order_data.get('delivery_city')}")

        lines.append(f"\n**Produkty ({order_data.get('products_count', 0)}):**")
        for p in order_data.get('products', []):
            price = float(p.get('price_brutto', 0))
            qty = int(p.get('quantity', 1))
            lines.append(f"- {p.get('name')} x{qty} = {price * qty:.2f} zł")

        lines.append(f"\n**Podsumowanie:**")
        lines.append(f"Produkty: {order_data.get('products_value', 0):.2f} zł")
        lines.append(f"Wysyłka: {order_data.get('delivery_price', 0):.2f} zł ({order_data.get('delivery_method', 'brak')})")
        lines.append(f"**Razem: {order_data.get('total_value', 0):.2f} zł**")

        if order_data.get('admin_comments'):
            lines.append(f"\n**Uwagi:** {order_data['admin_comments']}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def get_context_for_message(self, message: str, user) -> str:
        """
        Główny punkt wejścia — wywoływany z routera.
        Zwraca sformatowany markdown lub pusty string.
        """
        order_id = _extract_order_id(message)
        client_name = _extract_client_name(message)

        # Jeśli nic nie wykryto — nic do zrobienia
        if not order_id and not client_name:
            return ""

        try:
            # Zapytanie o konkretne zamówienie po ID
            if order_id:
                result = self.get_order_by_id(order_id, user)
                if result['success']:
                    return f"**Dane zamówienia z Baselinker:**\n\n{self.format_order_response(result['order'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Zapytanie o klienta
            if client_name:
                clients = self.search_clients_by_name(client_name, user)

                if not clients:
                    if user.is_partner():
                        return f"**Nie mogę udzielić odpowiedzi** - nie znaleziono klienta '{client_name}' wśród Twoich klientów."
                    else:
                        return f"**Nie znaleziono klientów** pasujących do: {client_name}"

                if len(clients) == 1:
                    client = clients[0]
                    result = self.get_orders_for_client(client['id'], user)
                    if result['success']:
                        if result['orders']:
                            orders_text = "\n\n---\n\n".join([
                                self.format_order_response(o) for o in result['orders']
                            ])
                            return f"**Zamówienia klienta {client['client_name']}:**\n\n{orders_text}"
                        else:
                            return f"**Klient {client['client_name']}** nie ma jeszcze zamówień w systemie."
                    else:
                        return f"**Błąd:** {result['error']}"
                else:
                    clients_list = "\n".join([
                        f"- {c['client_name']} ({c.get('city', 'brak miasta')}) - {c.get('email', 'brak email')}"
                        for c in clients
                    ])
                    return (
                        f"**Znaleziono {len(clients)} klientów pasujących do \"{client_name}\":**\n\n"
                        f"{clients_list}\n\n"
                        f"Proszę doprecyzować, o którego klienta chodzi (podaj pełne imię i nazwisko lub email)."
                    )

        except Exception as e:
            logger.error(f"Błąd pobierania kontekstu BL: {e}")
            return f"**Błąd komunikacji z Baselinker:** {str(e)}"

        return ""
