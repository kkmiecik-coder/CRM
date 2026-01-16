# app/modules/production/services/shipping_service.py
# Serwis do obsługi wysyłek kurierskich (2025-12)

import requests
import time
import logging
from typing import Dict, List, Optional, Any
from flask import current_app

logger = logging.getLogger(__name__)


class ShippingService:
    """
    Serwis do obliczania wymiarów paczek, pobierania ofert z GlobKurier
    i wybierania najtańszej opcji wysyłki.
    """

    # Limity kuriera
    COURIER_LIMITS = {
        'max_weight_kg': 31.5,
        'max_dimension_cm': 200,
        'margin_cm': 5  # margines na opakowanie
    }

    # Współczynnik przeliczania objętości na wagę (kg/m³)
    WEIGHT_FACTOR = 800

    # Konfiguracja timeout i retry
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 2
    RETRY_DELAY = 2
    RETRYABLE_STATUS_CODES = [502, 503, 504]

    # Słowa kluczowe do wykluczania automatów paczkowych
    AUTOMAT_KEYWORDS = ['automat', 'paczkomat', 'point', 'box', 'locker', 'parcel locker']

    def __init__(self):
        self.glob_config = None
        self._token = None
        self._token_timestamp = None

    def _get_glob_config(self) -> Dict:
        """Pobiera konfigurację GlobKurier z aplikacji Flask."""
        if self.glob_config is None:
            self.glob_config = current_app.config.get("GLOB_KURIER")
            if not self.glob_config:
                raise ValueError("Brak konfiguracji GLOB_KURIER w aplikacji")
        return self.glob_config

    def _make_request_with_retry(
        self,
        request_func,
        request_name: str,
        *args,
        **kwargs
    ) -> Optional[requests.Response]:
        """
        Wykonuje request z mechanizmem retry dla błędów tymczasowych.
        """
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = self.REQUEST_TIMEOUT

                logger.info(f"[Shipping] {request_name} - próba {attempt + 1}/{self.MAX_RETRIES + 1}")
                response = request_func(*args, **kwargs)

                if response.status_code == 200 or response.status_code not in self.RETRYABLE_STATUS_CODES:
                    return response

                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        f"[Shipping] {request_name} - błąd {response.status_code}, "
                        f"retry za {self.RETRY_DELAY}s..."
                    )
                    time.sleep(self.RETRY_DELAY)
                    continue

                return response

            except requests.exceptions.Timeout:
                logger.error(f"[Shipping] {request_name} - timeout po {self.REQUEST_TIMEOUT}s")
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"[Shipping] {request_name} - retry za {self.RETRY_DELAY}s...")
                    time.sleep(self.RETRY_DELAY)
                    continue
                else:
                    raise
            except requests.exceptions.RequestException as e:
                logger.error(f"[Shipping] {request_name} - wyjątek: {e}")
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"[Shipping] {request_name} - retry za {self.RETRY_DELAY}s...")
                    time.sleep(self.RETRY_DELAY)
                    continue
                else:
                    raise

        return None

    def _get_globkurier_token(self) -> str:
        """
        Loguje się do GlobKurier i zwraca token autoryzacyjny.
        Token jest cache'owany na czas sesji.
        """
        # Sprawdź czy mamy aktualny token (cache na 5 minut)
        if self._token and self._token_timestamp:
            if time.time() - self._token_timestamp < 300:  # 5 minut
                logger.debug("[Shipping] Używam cached tokena GlobKurier")
                return self._token

        config = self._get_glob_config()
        auth_url = config["endpoint"] + "/auth/login"
        login_payload = {
            "email": config["login"],
            "password": config["password"]
        }
        headers = {
            "Content-Type": "application/json",
            "accept-language": "en"
        }

        logger.info("[Shipping] Logowanie do GlobKurier API")

        auth_response = self._make_request_with_retry(
            requests.post,
            "auth/login",
            auth_url,
            headers=headers,
            json=login_payload
        )

        if not auth_response:
            raise ConnectionError("Nie otrzymano odpowiedzi od GlobKurier po wszystkich próbach logowania")

        if auth_response.status_code != 200:
            raise ConnectionError(f"Błąd logowania do GlobKurier: status {auth_response.status_code}")

        auth_data = auth_response.json()
        token = auth_data.get("token")

        if not token:
            raise ValueError("Nie otrzymano tokena autoryzacyjnego od GlobKurier")

        # Cache'uj token
        self._token = token
        self._token_timestamp = time.time()

        logger.info("[Shipping] Pomyślnie zalogowano do GlobKurier")
        return token

    def calculate_package_dimensions(self, products: List[Any]) -> Dict:
        """
        Oblicza wymiary pojedynczej paczki dla listy produktów.

        Logika:
        - length = max(all lengths) + margin
        - width = max(all widths) + margin
        - height = sum(all thicknesses * quantity) + margin
        - weight = sum(volume_m3 * quantity) * WEIGHT_FACTOR

        Args:
            products: Lista obiektów ProductionItem

        Returns:
            Dict z wymiarami i informacją o limitach
        """
        logger.info(f"[Shipping] Obliczanie wymiarów dla {len(products)} produktów")

        max_length = 0
        max_width = 0
        total_thickness = 0
        total_volume = 0

        for product in products:
            length = float(product.parsed_length_cm or 0)
            width = float(product.parsed_width_cm or 0)
            thickness = float(product.parsed_thickness_cm or 0)
            volume = float(product.volume_m3 or 0)
            qty = int(product.quantity or 1)

            logger.debug(
                f"[Shipping] Produkt: {length}x{width}x{thickness}cm, "
                f"vol={volume}m³, qty={qty}"
            )

            max_length = max(max_length, length)
            max_width = max(max_width, width)
            total_thickness += thickness * qty
            total_volume += volume * qty

        margin = self.COURIER_LIMITS['margin_cm']

        dimensions = {
            'length': int(round(max_length + margin)),
            'width': int(round(max_width + margin)),
            'height': int(round(total_thickness + margin)),
            'weight': round(total_volume * self.WEIGHT_FACTOR, 2),
            'max_dimension': int(round(max(max_length, max_width, total_thickness) + margin))
        }

        # Sprawdź limity
        limits_check = self.check_limits(dimensions)
        dimensions['within_limits'] = limits_check['within_limits']
        dimensions['limit_issues'] = limits_check.get('issues', [])

        logger.info(
            f"[Shipping] Wymiary paczki: {dimensions['length']}x{dimensions['width']}x{dimensions['height']}cm, "
            f"{dimensions['weight']}kg, within_limits={dimensions['within_limits']}"
        )

        return dimensions

    def check_limits(self, dimensions: Dict) -> Dict:
        """
        Sprawdza czy wymiary mieszczą się w limitach kuriera.

        Returns:
            Dict z within_limits (bool) i issues (lista problemów)
        """
        issues = []
        max_weight = self.COURIER_LIMITS['max_weight_kg']
        max_dim = self.COURIER_LIMITS['max_dimension_cm']

        if dimensions.get('weight', 0) > max_weight:
            issues.append(f"waga {dimensions['weight']} kg > limit {max_weight} kg")

        for dim_name in ['length', 'width', 'height']:
            dim_value = dimensions.get(dim_name, 0)
            if dim_value > max_dim:
                issues.append(f"{dim_name} {dim_value} cm > limit {max_dim} cm")

        return {
            'within_limits': len(issues) == 0,
            'issues': issues
        }

    def generate_packaging_variants(self, products: List[Any]) -> List[Dict]:
        """
        Generuje warianty pakowania:
        1. Pojedyncze paczki (każdy produkt osobno)
        2. Jedna paczka (wszystko razem)
        3. Smart grouping (inteligentne grupowanie)

        Returns:
            Lista wariantów z nazwą, listą paczek i walidacją limitów
        """
        logger.info(f"[Shipping] Generowanie wariantów pakowania dla {len(products)} produktów")

        variants = []

        # Wariant 1: Wszystko razem
        combined_dims = self.calculate_package_dimensions(products)
        variants.append({
            'name': 'combined',
            'display_name': 'Wszystko w jednej paczce',
            'packages': [{
                'products': products,
                'dimensions': combined_dims
            }],
            'total_packages': 1,
            'valid': combined_dims['within_limits']
        })

        # Wariant 2: Pojedyncze paczki (każdy produkt osobno)
        if len(products) > 1:
            individual_packages = []
            all_valid = True

            for product in products:
                dims = self.calculate_package_dimensions([product])
                individual_packages.append({
                    'products': [product],
                    'dimensions': dims
                })
                if not dims['within_limits']:
                    all_valid = False

            variants.append({
                'name': 'individual',
                'display_name': 'Każdy produkt osobno',
                'packages': individual_packages,
                'total_packages': len(individual_packages),
                'valid': all_valid
            })

        # Wariant 3: Smart grouping (tylko dla >2 produktów)
        if len(products) > 2:
            smart_variant = self._generate_smart_grouping(products)
            if smart_variant:
                variants.append(smart_variant)

        logger.info(f"[Shipping] Wygenerowano {len(variants)} wariantów pakowania")
        return variants

    def _generate_smart_grouping(self, products: List[Any]) -> Optional[Dict]:
        """
        Inteligentne grupowanie produktów:
        - Grupuj produkty o podobnych wymiarach
        - Nie łącz ekstremalnych różnic (np. 50x50 z 250x120)
        """
        logger.debug("[Shipping] Generowanie smart grouping")

        # Sortuj produkty po maksymalnym wymiarze
        sorted_products = sorted(
            products,
            key=lambda p: max(
                float(p.parsed_length_cm or 0),
                float(p.parsed_width_cm or 0)
            ),
            reverse=True
        )

        groups = []
        current_group = []
        current_max_dim = 0

        for product in sorted_products:
            prod_max_dim = max(
                float(product.parsed_length_cm or 0),
                float(product.parsed_width_cm or 0)
            )

            # Jeśli różnica wymiarów > 100%, zacznij nową grupę
            if current_group and current_max_dim > 0:
                ratio = prod_max_dim / current_max_dim if current_max_dim else 1
                if ratio < 0.5:  # Produkt jest o ponad 50% mniejszy
                    groups.append(current_group)
                    current_group = []
                    current_max_dim = 0

            current_group.append(product)
            if prod_max_dim > current_max_dim:
                current_max_dim = prod_max_dim

        if current_group:
            groups.append(current_group)

        # Jeśli mamy tylko jedną grupę, smart grouping nie ma sensu
        if len(groups) <= 1:
            return None

        # Oblicz wymiary dla każdej grupy
        packages = []
        all_valid = True

        for group in groups:
            dims = self.calculate_package_dimensions(group)
            packages.append({
                'products': group,
                'dimensions': dims
            })
            if not dims['within_limits']:
                all_valid = False

        return {
            'name': 'smart',
            'display_name': f'Inteligentne grupowanie ({len(groups)} paczki)',
            'packages': packages,
            'total_packages': len(packages),
            'valid': all_valid
        }

    def get_quotes_for_package(
        self,
        package: Dict,
        receiver_postcode: str,
        sender_postcode: str = "36-068"
    ) -> List[Dict]:
        """
        Pobiera oferty kurierskie z GlobKurier dla pojedynczej paczki.

        Args:
            package: Dict z wymiarami (length, width, height, weight)
            receiver_postcode: Kod pocztowy odbiorcy
            sender_postcode: Kod pocztowy nadawcy (domyślnie Bachórz)

        Returns:
            Lista ofert z ceną, nazwą kuriera i service_id
        """
        logger.info(
            f"[Shipping] Pobieranie ofert dla paczki "
            f"{package['length']}x{package['width']}x{package['height']}cm, "
            f"{package['weight']}kg -> {receiver_postcode}"
        )

        try:
            token = self._get_globkurier_token()
            config = self._get_glob_config()

            products_url = config["endpoint"] + "/products"
            headers = {
                "accept-language": "en",
                "x-auth-token": token
            }

            query_params = {
                "width": package['width'],
                "height": package['height'],
                "length": package['length'],
                "weight": f"{package['weight']:.2f}",
                "quantity": 1,
                "senderCountryId": "1",  # Polska
                "receiverCountryId": "1",  # Polska
                "senderPostCode": sender_postcode,
                "receiverPostCode": receiver_postcode
            }

            response = self._make_request_with_retry(
                requests.get,
                "products",
                products_url,
                headers=headers,
                params=query_params
            )

            if not response:
                logger.error("[Shipping] Nie otrzymano odpowiedzi od GlobKurier")
                return []

            if response.status_code != 200:
                logger.error(f"[Shipping] Błąd pobierania ofert: status {response.status_code}")
                return []

            quote_data = response.json()

            logger.debug(f"[Shipping] Typ odpowiedzi GlobKurier: {type(quote_data)}")
            logger.debug(f"[Shipping] Klucze odpowiedzi: {list(quote_data.keys()) if isinstance(quote_data, dict) else 'N/A'}")

            # Parsuj odpowiedź - GlobKurier zwraca dane w kategoriach (dict)
            all_products = []

            if isinstance(quote_data, dict):
                for category in quote_data:
                    items = quote_data[category]
                    if isinstance(items, list):
                        all_products.extend(items)
                    elif isinstance(items, dict):
                        all_products.append(items)
            elif isinstance(quote_data, list):
                # Jeśli API zwróci listę bezpośrednio
                all_products = quote_data
            else:
                logger.warning(f"[Shipping] Nieoczekiwany format odpowiedzi: {type(quote_data)}")

            logger.info(f"[Shipping] Znaleziono {len(all_products)} produktów przed filtracją")

            # Mapuj na nasz format
            quotes = []
            for i, product in enumerate(all_products):
                if not isinstance(product, dict):
                    logger.warning(f"[Shipping] Pominięto produkt - nie jest dict: {type(product)}")
                    continue

                # DEBUG: Pokaż wszystkie klucze pierwszych 3 produktów
                if i < 3:
                    logger.info(f"[Shipping] DEBUG produkt {i}: klucze={list(product.keys())}")
                    logger.info(f"[Shipping] DEBUG produkt {i}: pełne dane={product}")

                carrier_name = product.get("carrierName", "Nieznany")
                service_name = product.get("serviceName", product.get("productName", ""))
                gross_price = product.get("grossPrice", 0)
                service_id = product.get("serviceId") or product.get("productId") or product.get("id") or ""

                logger.debug(f"[Shipping] Oferta: {carrier_name} - {service_name}, service_id={service_id}")

                # Filtruj automaty paczkowe
                full_name = f"{carrier_name} {service_name}".lower()
                is_automat = any(kw in full_name for kw in self.AUTOMAT_KEYWORDS)

                if is_automat:
                    logger.debug(f"[Shipping] Pominięto automat: {carrier_name} - {service_name}")
                    continue

                quotes.append({
                    'courier_name': carrier_name,
                    'service_name': service_name,
                    'service_id': service_id,
                    'price': float(gross_price) if gross_price else 0,
                    'price_netto': round(float(gross_price) / 1.23, 2) if gross_price else 0,
                    'logo': product.get("carrierLogoLink", "")
                })

            logger.info(f"[Shipping] Otrzymano {len(quotes)} ofert (po filtracji automatów)")
            return quotes

        except Exception as e:
            logger.error(f"[Shipping] Wyjątek podczas pobierania ofert: {e}")
            import traceback
            logger.error(f"[Shipping] Stack trace: {traceback.format_exc()}")
            return []

    def get_cheapest_option(
        self,
        package: Dict,
        receiver_postcode: str,
        sender_postcode: str = "36-068"
    ) -> Optional[Dict]:
        """
        Pobiera najtańszą ofertę kurierską (door-to-door) dla paczki.

        Returns:
            Dict z danymi najtańszej oferty lub None jeśli brak ofert
        """
        quotes = self.get_quotes_for_package(package, receiver_postcode, sender_postcode)

        if not quotes:
            return None

        # Znajdź najtańszą
        cheapest = min(quotes, key=lambda x: x.get('price', float('inf')))

        logger.info(
            f"[Shipping] Najtańsza oferta: {cheapest['courier_name']} - "
            f"{cheapest['service_name']} = {cheapest['price']} zł"
        )

        return cheapest

    async def get_cheapest_for_variants(
        self,
        variants: List[Dict],
        receiver_postcode: str,
        sender_postcode: str = "36-068"
    ) -> Optional[Dict]:
        """
        Porównuje koszty wszystkich wariantów pakowania
        i zwraca najtańszy.

        Returns:
            Dict z informacją o najlepszym wariancie
        """
        logger.info(f"[Shipping] Porównywanie {len(variants)} wariantów pakowania")

        best_option = None
        best_total_cost = float('inf')

        for variant in variants:
            if not variant.get('valid'):
                logger.debug(f"[Shipping] Pomijam nieprawidłowy wariant: {variant['name']}")
                continue

            total_cost = 0
            package_quotes = []

            for pkg in variant.get('packages', []):
                dims = pkg.get('dimensions', {})
                cheapest = self.get_cheapest_option(
                    package={
                        'length': dims.get('length', 0),
                        'width': dims.get('width', 0),
                        'height': dims.get('height', 0),
                        'weight': dims.get('weight', 0)
                    },
                    receiver_postcode=receiver_postcode,
                    sender_postcode=sender_postcode
                )

                if not cheapest:
                    logger.warning(f"[Shipping] Brak ofert dla paczki w wariancie {variant['name']}")
                    total_cost = float('inf')
                    break

                total_cost += cheapest['price']
                package_quotes.append(cheapest)

            if total_cost < best_total_cost:
                best_total_cost = total_cost
                best_option = {
                    'variant_name': variant['name'],
                    'variant_display_name': variant['display_name'],
                    'total_packages': variant['total_packages'],
                    'total_price': total_cost,
                    'package_quotes': package_quotes
                }

        if best_option:
            logger.info(
                f"[Shipping] Najlepszy wariant: {best_option['variant_display_name']} = "
                f"{best_option['total_price']} zł ({best_option['total_packages']} paczek)"
            )

        return best_option
