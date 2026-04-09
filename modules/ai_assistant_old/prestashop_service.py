"""
Serwis do wyszukiwania produktów w PrestaShop
"""

import requests
from flask import current_app
from typing import List, Dict, Optional


class PrestaShopService:
    """Serwis do komunikacji z PrestaShop API"""

    def __init__(self):
        self.api_url = "https://woodpower.pl/api"
        self.api_key = self._get_api_key()
        self.shop_url = "https://woodpower.pl"

    def _get_api_key(self) -> str:
        """Pobiera klucz API PrestaShop z konfiguracji"""
        config = current_app.config.get('AI_ASSISTANT', {})
        return config.get('prestashop_api_key', '')

    def is_configured(self) -> bool:
        """Sprawdza czy API jest skonfigurowane"""
        return bool(self.api_key)

    def search_products(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Wyszukuje produkty po nazwie

        Args:
            query: Fraza do wyszukania
            limit: Maksymalna liczba wyników

        Returns:
            Lista produktów z nazwą, ceną i linkiem
        """
        if not self.is_configured():
            current_app.logger.warning("[PrestaShop] API nie skonfigurowane")
            return []

        try:
            # Użyj endpoint search
            response = requests.get(
                f"{self.api_url}/search",
                params={
                    'output_format': 'JSON',
                    'query': query,
                    'language': 1
                },
                auth=(self.api_key, ''),
                timeout=10
            )

            if response.status_code != 200:
                current_app.logger.error(f"[PrestaShop] Search error: {response.status_code}")
                return []

            data = response.json()
            product_ids = [p['id'] for p in data.get('products', [])][:limit]

            if not product_ids:
                return []

            # Pobierz szczegóły produktów
            products = []
            for pid in product_ids:
                product = self._get_product_details(pid)
                if product and product.get('active') == '1':
                    products.append(product)

            return products

        except requests.exceptions.Timeout:
            current_app.logger.error("[PrestaShop] Timeout")
            return []
        except Exception as e:
            current_app.logger.error(f"[PrestaShop] Error: {str(e)}")
            return []

    def _get_product_details(self, product_id: int) -> Optional[Dict]:
        """Pobiera szczegóły produktu"""
        try:
            response = requests.get(
                f"{self.api_url}/products/{product_id}",
                params={'output_format': 'JSON'},
                auth=(self.api_key, ''),
                timeout=5
            )

            if response.status_code != 200:
                return None

            data = response.json()
            product = data.get('product', {})

            # Buduj URL produktu: {id}-{link_rewrite}.html
            link_rewrite = product.get('link_rewrite', '')
            if isinstance(link_rewrite, dict):
                link_rewrite = link_rewrite.get('language', {}).get('value', '') or list(link_rewrite.values())[0] if link_rewrite else ''

            name = product.get('name', '')
            if isinstance(name, dict):
                name = name.get('language', {}).get('value', '') or list(name.values())[0] if name else ''

            price = float(product.get('price', 0))
            price_brutto = price * 1.23  # VAT 23%

            return {
                'id': product.get('id'),
                'name': name,
                'price_netto': round(price, 2),
                'price_brutto': round(price_brutto, 2),
                'url': f"{self.shop_url}/{product_id}-{link_rewrite}.html",
                'active': product.get('active', '0')
            }

        except Exception as e:
            current_app.logger.error(f"[PrestaShop] Error getting product {product_id}: {str(e)}")
            return None

    def format_products_for_ai(self, products: List[Dict]) -> str:
        """Formatuje listę produktów do odpowiedzi AI - czytelna lista z separatorami"""
        if not products:
            return "Nie znaleziono produktów w sklepie."

        lines = ["**Znalezione produkty w sklepie:**\n"]

        for i, p in enumerate(products, 1):
            # Numerowany produkt z linkiem markdown
            lines.append(f"**{i}. [{p['name']}]({p['url']})**")
            lines.append(f"   💰 Cena: **{p['price_brutto']:.2f} zł** brutto ({p['price_netto']:.2f} zł netto)")

            # Separator między produktami (ale nie po ostatnim)
            if i < len(products):
                lines.append("\n---\n")

        return "\n".join(lines)

    def search_with_dimension_tolerance(self, base_query: str, dimensions: Dict[str, int], tolerance: int = 15) -> List[Dict]:
        """
        Wyszukuje produkty z tolerancją wymiarów.

        Args:
            base_query: Bazowa fraza (np. "blat dębowy")
            dimensions: Słownik wymiarów {'length': 146, 'width': 38, 'thickness': 4}
            tolerance: Tolerancja w cm (domyślnie ±15cm)

        Returns:
            Lista produktów, posortowana wg podobieństwa wymiarów
        """
        # Najpierw szukamy po samej frazie
        products = self.search_products(base_query, limit=20)

        if not products or not dimensions:
            return products[:5] if products else []

        # Filtruj i sortuj wg podobieństwa wymiarów
        scored_products = []
        for p in products:
            name = p.get('name', '').lower()
            score = self._calculate_dimension_score(name, dimensions, tolerance)
            if score >= 0:  # -1 oznacza że wymiary są poza tolerancją
                scored_products.append((score, p))

        # Sortuj po score (niższy = lepsze dopasowanie)
        scored_products.sort(key=lambda x: x[0])

        return [p for score, p in scored_products[:5]]

    def _calculate_dimension_score(self, product_name: str, dimensions: Dict[str, int], tolerance: int) -> int:
        """
        Oblicza score dopasowania wymiarów.
        WAŻNE: Produkt musi być >= szukanego wymiaru (można skrócić, nie można wydłużyć!)

        Zwraca:
        - 0 = idealne dopasowanie
        - >0 = produkt większy (można skrócić) - im mniejsza wartość tym lepiej
        - -1 = produkt za mały (nie pasuje!)
        """
        import re

        # Wyciągnij wymiary z nazwy produktu (szukamy wzorców jak 150x60, 140x40x3)
        dim_patterns = [
            r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)',  # 150x60x4
            r'(\d+)\s*[xX×]\s*(\d+)',  # 150x60
            r'(\d+)\s*cm',  # 150 cm
        ]

        found_dims = []
        for pattern in dim_patterns:
            matches = re.findall(pattern, product_name)
            if matches:
                for m in matches:
                    if isinstance(m, tuple):
                        found_dims.extend([int(d) for d in m if d])
                    else:
                        found_dims.append(int(m))
                break

        if not found_dims:
            return 1000  # Brak wymiarów w nazwie - neutralny score

        # Porównaj z szukanymi wymiarami
        total_diff = 0
        target_dims = [v for v in dimensions.values() if v]

        for target in target_dims:
            # Znajdź najbliższy wymiar w produkcie który jest >= target
            valid_dims = [d for d in found_dims if d >= target]

            if not valid_dims:
                # Produkt jest za mały - nie pasuje!
                return -1

            # Wybierz najmniejszy wymiar który jest >= target
            best_match = min(valid_dims)
            diff = best_match - target  # Ile trzeba skrócić

            if diff > tolerance:
                return -1  # Za duża różnica - nie opłaca się

            total_diff += diff

        return total_diff
