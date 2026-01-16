"""
Serwis do odpytywania Baselinker API dla AI Assistant
Z kontrolą uprawnień i rate limitingiem
"""

import time
import re
import threading
from typing import Dict, List, Optional, Tuple
from flask import current_app, session, has_request_context
from collections import defaultdict
from datetime import datetime

from extensions import db


# Thread-local storage dla user_id (używane gdy brak request context)
_thread_user_data = threading.local()


def set_thread_user_id(user_id: Optional[int]):
    """Ustawia user_id dla bieżącego wątku"""
    _thread_user_data.user_id = user_id


def get_thread_user_id() -> Optional[int]:
    """Pobiera user_id dla bieżącego wątku"""
    return getattr(_thread_user_data, 'user_id', None)


# Słownik zdrobnień polskich imion
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


class RateLimiter:
    """
    Rate limiter per user - max N requests per minute
    Przechowuje w pamięci (można rozbudować na Redis)
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = defaultdict(list)  # user_id -> [timestamp, ...]

    def is_allowed(self, user_id: int) -> Tuple[bool, Optional[int]]:
        """
        Sprawdza czy użytkownik może wykonać zapytanie.
        Returns:
            (True, None) jeśli dozwolone
            (False, seconds_to_wait) jeśli zablokowane
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Usuń stare wpisy
        self._requests[user_id] = [
            ts for ts in self._requests[user_id]
            if ts > window_start
        ]

        if len(self._requests[user_id]) >= self.max_requests:
            # Oblicz ile czekać
            oldest = min(self._requests[user_id])
            wait_time = int(oldest + self.window_seconds - now) + 1
            return False, wait_time

        return True, None

    def record_request(self, user_id: int):
        """Rejestruje zapytanie"""
        self._requests[user_id].append(time.time())


class BaselinkerAIService:
    """
    Serwis do odpytywania Baselinker API przez AI Assistant
    Z kontrolą uprawnień i rate limitingiem
    """

    # Globalna instancja rate limitera (wspólna dla wszystkich requestów)
    _rate_limiter = RateLimiter(max_requests=5, window_seconds=60)

    def __init__(self):
        self.logger = current_app.logger
        self._bl_service = None  # Lazy init

    @property
    def bl_service(self):
        """Lazy initialization BaselinkerService"""
        if self._bl_service is None:
            from modules.baselinker.service import BaselinkerService
            self._bl_service = BaselinkerService()
        return self._bl_service

    # =====================================================
    # METODY KONTROLI UPRAWNIEŃ
    # =====================================================

    def _get_current_user(self):
        """Pobiera aktualnie zalogowanego użytkownika"""
        from modules.users.models import User

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

    def _can_access_order(self, user, baselinker_order_id: int) -> bool:
        """
        Sprawdza czy użytkownik może uzyskać dostęp do zamówienia.

        Admin/User: pełny dostęp
        Partner: tylko zamówienia powiązane z jego wycenami
        """
        if self._is_admin_or_user(user):
            return True

        if self._is_partner(user):
            from modules.calculator.models import Quote
            # Sprawdź czy istnieje Quote z tym zamówieniem BL i user_id == partner
            quote = Quote.query.filter(
                Quote.base_linker_order_id == str(baselinker_order_id),
                Quote.user_id == user.id
            ).first()
            return quote is not None

        return False

    def _can_access_client(self, user, client) -> bool:
        """
        Sprawdza czy użytkownik może uzyskać dostęp do klienta.

        Admin/User: pełny dostęp
        Partner: tylko klienci których jest opiekunem LUB stworzył
        """
        if self._is_admin_or_user(user):
            return True

        if self._is_partner(user):
            from modules.calculator.models import Quote

            # Klient stworzony przez partnera
            if client.created_by_user_id == user.id:
                return True

            # Klient ma Quote gdzie partner jest opiekunem
            has_quote = Quote.query.filter(
                Quote.client_id == client.id,
                Quote.user_id == user.id
            ).first()
            return has_quote is not None

        return False

    def _get_partner_accessible_order_ids(self, user) -> List[int]:
        """
        Zwraca listę ID zamówień Baselinker dostępnych dla partnera.
        """
        if not self._is_partner(user):
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

    # =====================================================
    # RATE LIMITING
    # =====================================================

    def check_rate_limit(self, user) -> Tuple[bool, Optional[str]]:
        """
        Sprawdza rate limit dla użytkownika.
        Returns:
            (True, None) jeśli OK
            (False, error_message) jeśli przekroczono limit
        """
        allowed, wait_time = self._rate_limiter.is_allowed(user.id)
        if not allowed:
            return False, f"Przekroczono limit zapytań. Poczekaj {wait_time} sekund i spróbuj ponownie."
        return True, None

    def record_api_call(self, user):
        """Rejestruje wywołanie API"""
        self._rate_limiter.record_request(user.id)

    # =====================================================
    # WYSZUKIWANIE KLIENTÓW
    # =====================================================

    def _normalize_name(self, name: str) -> str:
        """Normalizuje imię (lowercase, bez polskich znaków)"""
        name = name.lower().strip()
        # Zamiana polskich znaków
        replacements = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
            'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z'
        }
        for pl, ascii_char in replacements.items():
            name = name.replace(pl, ascii_char)
        return name

    def _get_name_variants(self, name: str) -> List[str]:
        """
        Zwraca wszystkie warianty imienia (oryginalne + zdrobnienia + pełne formy).
        """
        normalized = self._normalize_name(name)
        variants = {normalized, name.lower()}

        # Sprawdź czy to zdrobnienie - dodaj pełną formę
        for full_name, diminutives in POLISH_NAME_DIMINUTIVES.items():
            normalized_diminutives = [self._normalize_name(d) for d in diminutives]
            if normalized in normalized_diminutives:
                variants.add(full_name)
                variants.add(self._normalize_name(full_name))

        # Sprawdź czy to pełna forma - dodaj zdrobnienia
        if normalized in POLISH_NAME_DIMINUTIVES:
            for dim in POLISH_NAME_DIMINUTIVES[normalized]:
                variants.add(dim.lower())
                variants.add(self._normalize_name(dim))

        # Bez polskich znaków też
        for v in list(variants):
            variants.add(self._normalize_name(v))

        return list(variants)

    def search_clients_by_name(self, name_query: str, user) -> List[Dict]:
        """
        Wyszukuje klientów po imieniu/nazwisku z obsługą zdrobnień.
        Uwzględnia uprawnienia użytkownika.

        Returns:
            Lista słowników z danymi klientów
        """
        from modules.clients.models import Client
        from modules.calculator.models import Quote
        from sqlalchemy import or_, func

        # Podziel zapytanie na słowa i generuj warianty dla każdego
        words = name_query.strip().split()
        all_variants = []
        for word in words:
            all_variants.extend(self._get_name_variants(word))

        # Dla partnera - pobierz tylko dostępnych klientów
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

            # Połącz
            accessible_client_ids = list(set(own_client_ids + quote_client_ids))

            if not accessible_client_ids:
                return []

            # Buduj filtry nazwy
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
            # Admin/User - szukaj we wszystkich
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

    # =====================================================
    # POBIERANIE DANYCH Z BASELINKER
    # =====================================================

    def get_order_by_id(self, order_id: int, user) -> Dict:
        """
        Pobiera zamówienie po ID Baselinker z kontrolą uprawnień.

        Returns:
            {
                'success': True/False,
                'order': {...} lub 'error': '...'
            }
        """
        # Sprawdź uprawnienia
        if not self._can_access_order(user, order_id):
            return {
                'success': False,
                'error': 'Nie masz uprawnień do tego zamówienia. Jako partner widzisz tylko zamówienia z własnych wycen.'
            }

        # Sprawdź rate limit
        allowed, error = self.check_rate_limit(user)
        if not allowed:
            return {'success': False, 'error': error}

        # Wywołaj API
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

            order = orders[0]
            return {
                'success': True,
                'order': self._format_order_for_ai(order)
            }

        except Exception as e:
            self.logger.error(f"[BaselinkerAI] Błąd pobierania zamówienia {order_id}: {e}")
            return {
                'success': False,
                'error': f'Błąd komunikacji z Baselinker: {str(e)}'
            }

    def get_orders_for_client(self, client_id: int, user, limit: int = 5) -> Dict:
        """
        Pobiera zamówienia dla klienta.

        Returns:
            {
                'success': True/False,
                'client': {...},
                'orders': [...] lub 'error': '...'
            }
        """
        from modules.clients.models import Client
        from modules.calculator.models import Quote

        # Pobierz klienta
        client = Client.query.get(client_id)
        if not client:
            return {
                'success': False,
                'error': 'Klient nie znaleziony'
            }

        # Sprawdź uprawnienia do klienta
        if not self._can_access_client(user, client):
            return {
                'success': False,
                'error': 'Nie mogę udzielić odpowiedzi - to nie Twój klient.'
            }

        # Pobierz wyceny klienta z zamówieniami BL
        quotes_query = Quote.query.filter(
            Quote.client_id == client_id,
            Quote.base_linker_order_id.isnot(None)
        )

        # Dla partnera - tylko jego wyceny
        if self._is_partner(user):
            quotes_query = quotes_query.filter(Quote.user_id == user.id)

        quotes = quotes_query.order_by(Quote.created_at.desc()).limit(limit).all()

        if not quotes:
            return {
                'success': True,
                'client': {
                    'id': client.id,
                    'name': client.client_name,
                    'email': client.email
                },
                'orders': [],
                'message': 'Brak zamówień dla tego klienta'
            }

        # Sprawdź rate limit
        allowed, error = self.check_rate_limit(user)
        if not allowed:
            return {'success': False, 'error': error}

        self.record_api_call(user)

        # Pobierz szczegóły zamówień z Baselinker
        orders_data = []
        for quote in quotes:
            try:
                order_id = int(quote.base_linker_order_id)
                response = self.bl_service._make_request('getOrders', {
                    'order_id': order_id,
                    'include_custom_extra_fields': True
                })

                if response.get('status') == 'SUCCESS':
                    bl_orders = response.get('orders', [])
                    if bl_orders:
                        formatted = self._format_order_for_ai(bl_orders[0])
                        formatted['quote_number'] = quote.quote_number
                        orders_data.append(formatted)

            except Exception as e:
                self.logger.warning(f"[BaselinkerAI] Błąd pobierania zamówienia {quote.base_linker_order_id}: {e}")

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
        """
        Pobiera statystyki zamówień partnera.

        Returns:
            {
                'success': True/False,
                'stats': {...}
            }
        """
        if not self._is_partner(user):
            return {
                'success': False,
                'error': 'Ta funkcja jest dostępna tylko dla partnerów'
            }

        from modules.calculator.models import Quote

        # Statystyki z lokalnej bazy (bez API BL)
        quotes = Quote.query.filter(Quote.user_id == user.id).all()

        total_quotes = len(quotes)
        quotes_with_orders = [q for q in quotes if q.base_linker_order_id]
        total_orders = len(quotes_with_orders)

        # Suma wartości
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

    # =====================================================
    # FORMATOWANIE ODPOWIEDZI DLA AI
    # =====================================================

    def _get_status_name(self, status_id: int) -> str:
        """Pobiera nazwę statusu z bazy BaselinkerConfig"""
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
        """
        Formatuje dane zamówienia do czytelnej postaci dla AI.
        """
        # Timestamp na datę
        date_add = order.get('date_add')
        if date_add:
            date_add = datetime.fromtimestamp(date_add).strftime('%Y-%m-%d %H:%M')

        date_confirmed = order.get('date_confirmed')
        if date_confirmed:
            date_confirmed = datetime.fromtimestamp(date_confirmed).strftime('%Y-%m-%d %H:%M')

        # Produkty
        products = []
        for p in order.get('products', []):
            products.append({
                'name': p.get('name'),
                'quantity': p.get('quantity'),
                'price_brutto': p.get('price_brutto'),
                'sku': p.get('sku')
            })

        # Wartość zamówienia
        total_products = sum(
            float(p.get('price_brutto', 0)) * int(p.get('quantity', 1))
            for p in order.get('products', [])
        )

        delivery_price = float(order.get('delivery_price', 0))
        payment_done = float(order.get('payment_done', 0))

        # Pobierz nazwę statusu z bazy
        status_id = order.get('order_status_id')
        status_name = self._get_status_name(status_id)

        # Oblicz total
        total_value = total_products + delivery_price

        # Sprawdź czy opłacone - payment_done >= total_value
        is_paid = payment_done >= total_value if total_value > 0 else False
        payment_remaining = max(0, total_value - payment_done)

        return {
            'order_id': order.get('order_id'),
            'internal_number': order.get('extra_field_1'),  # Numer wewnętrzny
            'date_created': date_add,
            'date_confirmed': date_confirmed,
            'status_id': status_id,
            'status_name': status_name,

            # Klient
            'client_name': order.get('user_login') or order.get('delivery_fullname'),
            'email': order.get('email'),
            'phone': order.get('phone'),

            # Adres dostawy
            'delivery_address': order.get('delivery_address'),
            'delivery_city': order.get('delivery_city'),
            'delivery_postcode': order.get('delivery_postcode'),

            # Produkty
            'products': products,
            'products_count': len(products),

            # Finanse
            'products_value': round(total_products, 2),
            'delivery_price': delivery_price,
            'total_value': round(total_value, 2),
            'payment_done': payment_done,
            'is_paid': is_paid,
            'payment_remaining': round(payment_remaining, 2),

            # Metadane
            'delivery_method': order.get('delivery_method'),
            'payment_method': order.get('payment_method'),
            'admin_comments': order.get('admin_comments'),
            'user_comments': order.get('user_comments'),
            'order_page': order.get('order_page')
        }

    def format_order_response(self, order_data: Dict) -> str:
        """
        Formatuje dane zamówienia do czytelnej odpowiedzi tekstowej (markdown).
        """
        if not order_data:
            return "Brak danych zamówienia."

        lines = [
            f"**Zamówienie #{order_data.get('order_id')}**",
        ]

        if order_data.get('internal_number'):
            lines.append(f"Numer wewnętrzny: {order_data['internal_number']}")

        lines.append(f"Data: {order_data.get('date_created', 'brak')}")

        # Status zamówienia
        status_name = order_data.get('status_name', 'Nieznany')
        lines.append(f"**Status:** {status_name}")

        # Status płatności
        if order_data.get('is_paid'):
            lines.append(f"**Płatność:** OPŁACONE ({order_data.get('payment_done', 0):.2f} zł)")
        else:
            remaining = order_data.get('payment_remaining', 0)
            paid = order_data.get('payment_done', 0)
            lines.append(f"**Płatność:** Wpłacono {paid:.2f} zł, do zapłaty {remaining:.2f} zł")

        # Klient
        lines.append(f"\n**Klient:** {order_data.get('client_name', 'brak')}")
        if order_data.get('phone'):
            lines.append(f"Tel: {order_data['phone']}")
        if order_data.get('email'):
            lines.append(f"Email: {order_data['email']}")

        # Adres
        if order_data.get('delivery_address'):
            lines.append(f"\n**Adres dostawy:**")
            lines.append(f"{order_data.get('delivery_address')}")
            lines.append(f"{order_data.get('delivery_postcode')} {order_data.get('delivery_city')}")

        # Produkty
        lines.append(f"\n**Produkty ({order_data.get('products_count', 0)}):**")
        for p in order_data.get('products', []):
            price = float(p.get('price_brutto', 0))
            qty = int(p.get('quantity', 1))
            lines.append(f"- {p.get('name')} x{qty} = {price * qty:.2f} zł")

        # Podsumowanie
        lines.append(f"\n**Podsumowanie:**")
        lines.append(f"Produkty: {order_data.get('products_value', 0):.2f} zł")
        lines.append(f"Wysyłka: {order_data.get('delivery_price', 0):.2f} zł ({order_data.get('delivery_method', 'brak')})")
        lines.append(f"**Razem: {order_data.get('total_value', 0):.2f} zł**")

        # Uwagi
        if order_data.get('admin_comments'):
            lines.append(f"\n**Uwagi:** {order_data['admin_comments']}")

        return "\n".join(lines)
