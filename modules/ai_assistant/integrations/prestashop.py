"""
Integracja AI Assistant z PrestaShop — wyszukiwanie produktów w sklepie
"""

import re
import logging
import requests
from typing import Dict, List, Optional

from flask import current_app

logger = logging.getLogger(__name__)

# Słowa kluczowe sugerujące pytanie o produkty w sklepie
_PRODUCT_KEYWORDS = [
    'mamy', 'macie', 'szukam', 'klient szuka', 'chce kupić',
    'w sklepie', 'w ofercie', 'dostępny', 'dostępne', 'link do',
    'gdzie kupić', 'gdzie zamówić', 'produkt', 'cena produktu',
    'ile kosztuje', 'potrzebuje', 'pyta o',
]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------
def _extract_dimensions(message: str) -> Dict[str, int]:
    """Wyciąga wymiary z wiadomości (np. 146x38x4 lub 150x60)."""
    dimensions: Dict[str, int] = {}
    patterns = [
        r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)',
        r'(\d+)\s*[xX×]\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            groups = match.groups()
            if len(groups) >= 1:
                dimensions['length'] = int(groups[0])
            if len(groups) >= 2:
                dimensions['width'] = int(groups[1])
            if len(groups) >= 3:
                dimensions['thickness'] = int(groups[2])
            break
    return dimensions


def _extract_search_query(message: str) -> str:
    """Wyciąga frazę do wyszukania z wiadomości użytkownika."""
    message_lower = message.lower()

    stop_words = [
        'mamy', 'macie', 'czy', 'jest', 'są', 'klient', 'szuka', 'chce',
        'pyta', 'o', 'w', 'na', 'do', 'z', 'i', 'a', 'lub', 'albo',
        'sklepie', 'ofercie', 'dostępny', 'dostępne', 'link', 'gdzie',
        'kupić', 'zamówić', 'potrzebuje', 'potrzebuje', 'proszę', 'prosze'
    ]

    words = message_lower.split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    product_terms: List[str] = []
    for word in keywords:
        if any(g in word for g in ['dęb', 'dąb', 'jesion', 'buk', 'dębowy', 'jesionowy', 'bukowy']):
            product_terms.append(word)
        elif any(t in word for t in ['blat', 'stopień', 'schod', 'parapet', 'klejonka']):
            product_terms.append(word)
        elif any(t in word for t in ['lity', 'mikrowczep', 'surowy', 'olejowany', 'lakierowany']):
            product_terms.append(word)
        elif 'x' in word and any(c.isdigit() for c in word):
            product_terms.append(word)
        elif word in ['a/b', 'ab', 'b/b', 'bb']:
            product_terms.append(word)

    if product_terms:
        return ' '.join(product_terms[:4])

    return ' '.join(keywords[:3]) if keywords else ""


# ---------------------------------------------------------------------------
# PrestaShopIntegration
# ---------------------------------------------------------------------------
class PrestaShopIntegration:
    """Serwis do komunikacji z PrestaShop API."""

    def __init__(self):
        self.api_url = "https://woodpower.pl/api"
        self.api_key = self._get_api_key()
        self.shop_url = "https://woodpower.pl"

    @staticmethod
    def _get_api_key() -> str:
        config = current_app.config.get('AI_ASSISTANT', {})
        return config.get('prestashop_api_key', '')

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Product search
    # ------------------------------------------------------------------
    def search_products(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_configured():
            logger.warning("PrestaShop API nie skonfigurowane")
            return []

        try:
            response = requests.get(
                f"{self.api_url}/search",
                params={'output_format': 'JSON', 'query': query, 'language': 1},
                auth=(self.api_key, ''),
                timeout=10
            )

            if response.status_code != 200:
                logger.error(f"PrestaShop search error: {response.status_code}")
                return []

            data = response.json()
            product_ids = [p['id'] for p in data.get('products', [])][:limit]

            if not product_ids:
                return []

            products = []
            for pid in product_ids:
                product = self._get_product_details(pid)
                if product and product.get('active') == '1':
                    products.append(product)

            return products

        except requests.exceptions.Timeout:
            logger.error("PrestaShop timeout")
            return []
        except Exception as e:
            logger.error(f"PrestaShop error: {str(e)}")
            return []

    def _get_product_details(self, product_id: int) -> Optional[Dict]:
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

            link_rewrite = product.get('link_rewrite', '')
            if isinstance(link_rewrite, dict):
                link_rewrite = link_rewrite.get('language', {}).get('value', '') or (list(link_rewrite.values())[0] if link_rewrite else '')

            name = product.get('name', '')
            if isinstance(name, dict):
                name = name.get('language', {}).get('value', '') or (list(name.values())[0] if name else '')

            price = float(product.get('price', 0))
            price_brutto = price * 1.23

            return {
                'id': product.get('id'),
                'name': name,
                'price_netto': round(price, 2),
                'price_brutto': round(price_brutto, 2),
                'url': f"{self.shop_url}/{product_id}-{link_rewrite}.html",
                'active': product.get('active', '0')
            }

        except Exception as e:
            logger.error(f"PrestaShop error getting product {product_id}: {str(e)}")
            return None

    # ------------------------------------------------------------------
    # Dimension-tolerant search
    # ------------------------------------------------------------------
    def search_with_dimension_tolerance(self, base_query: str, dimensions: Dict[str, int], tolerance: int = 15) -> List[Dict]:
        products = self.search_products(base_query, limit=20)

        if not products or not dimensions:
            return products[:5] if products else []

        scored_products = []
        for p in products:
            name = p.get('name', '').lower()
            score = self._calculate_dimension_score(name, dimensions, tolerance)
            if score >= 0:
                scored_products.append((score, p))

        scored_products.sort(key=lambda x: x[0])
        return [p for _score, p in scored_products[:5]]

    @staticmethod
    def _calculate_dimension_score(product_name: str, dimensions: Dict[str, int], tolerance: int) -> int:
        """
        Oblicza score dopasowania wymiarów.
        Produkt musi być >= szukanego wymiaru (można skrócić, nie można wydłużyć).
        Zwraca 0 = idealne, >0 = trzeba skrócić, -1 = nie pasuje.
        """
        dim_patterns = [
            r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)',
            r'(\d+)\s*[xX×]\s*(\d+)',
            r'(\d+)\s*cm',
        ]

        found_dims: List[int] = []
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
            return 1000

        total_diff = 0
        target_dims = [v for v in dimensions.values() if v]

        for target in target_dims:
            valid_dims = [d for d in found_dims if d >= target]
            if not valid_dims:
                return -1
            best_match = min(valid_dims)
            diff = best_match - target
            if diff > tolerance:
                return -1
            total_diff += diff

        return total_diff

    # ------------------------------------------------------------------
    # Formatter
    # ------------------------------------------------------------------
    def format_products_for_ai(self, products: List[Dict]) -> str:
        if not products:
            return "Nie znaleziono produktów w sklepie."

        lines = ["**Znalezione produkty w sklepie:**\n"]
        for i, p in enumerate(products, 1):
            lines.append(f"**{i}. [{p['name']}]({p['url']})**")
            lines.append(f"   Cena: **{p['price_brutto']:.2f} zł** brutto ({p['price_netto']:.2f} zł netto)")
            if i < len(products):
                lines.append("\n---\n")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def get_context_for_message(self, message: str) -> str:
        """
        Główny punkt wejścia — wywoływany z routera.
        Zwraca sformatowany markdown lub pusty string.
        """
        message_lower = message.lower()

        # Sprawdź czy wiadomość dotyczy produktów
        is_product_query = any(kw in message_lower for kw in _PRODUCT_KEYWORDS)
        if not is_product_query:
            return ""

        search_query = _extract_search_query(message)
        if not search_query:
            return ""

        try:
            dimensions = _extract_dimensions(message)

            if dimensions:
                products = self.search_with_dimension_tolerance(search_query, dimensions)
            else:
                products = self.search_products(search_query)

            if not products:
                return ""

            return f"**Dane z PrestaShop:**\n\n{self.format_products_for_ai(products)}"

        except Exception as e:
            logger.error(f"PrestaShop integration error: {e}")
            return ""
