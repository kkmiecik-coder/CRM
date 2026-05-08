# modules/reports/parser.py
"""
Parser nazw produktów z Baselinker
Wyciąga wymiary, gatunek, technologię, klasę i wykończenie z nazwy produktu

POPRAWKA: Rozszerzono obsługę formatów wymiarów:
- 90x44x2,1 cm (przecinki jako separatory dziesiętne)  
- 90x44x2,1cm (bez spacji przed cm)
- 90,3x44x2,1 cm (przecinki w długości)
- 90,7x44.5x2,1 cm (mieszane formaty kropka/przecinek)
"""

import re
from typing import Any, Dict, Optional, Tuple
from decimal import Decimal
from modules.logging import get_structured_logger
# Inicjalizacja loggera
reports_logger = get_structured_logger('reports.routers')
reports_logger.info("✅ reports_logger zainicjowany poprawnie w parser.py")


class ProductNameParser:
    """
    Klasa do parsowania nazw produktów z Baselinker
    
    Przykłady nazw:
    - "Klejonka bukowa mikrowczep A/B 98.0×40.0×2.0cm"
    - "Parapet 160x20x2 cm dębowy lity B/B surowy"
    - "Blat drewniany dębowy mikrowczep A/B 90x60x2 cm surowy"
    - "Spocznik dąb lity A/B 190x88x3 cm lakierowany"
    - NOWE FORMATY:
    - "Produkt 90x44x2,1 cm" (przecinek jako separator dziesiętny)
    - "Produkt 90x44x2,1cm" (bez spacji przed cm)
    - "Produkt 90,3x44x2,1 cm" (przecinki w długości)
    - "Produkt 90,7x44.5x2,1 cm" (mieszane formaty)
    """
    
    # Mapowanie gatunków drewna
    WOOD_SPECIES_MAP = {
        'bukowa': 'buk',
        'bukowy': 'buk', 
        'bukowe': 'buk',
        'dębowa': 'dąb',
        'dębowy': 'dąb',
        'dębowe': 'dąb',
        'jesionowa': 'jesion',
        'jesionowy': 'jesion',
        'jesionowe': 'jesion',
        'dąb': 'dąb',  # już w formie kanonicznej
        'jesion': 'jesion',
        'buk': 'buk'
    }
    
    # Mapowanie technologii
    TECHNOLOGY_MAP = {
        'lity': 'lity',
        'lita': 'lity',
        'lite': 'lity',
        'mikrowczep': 'mikrowczep'
    }
    
    # Mapowanie wykończeń
    FINISH_MAP = {
        'surowy': 'surowy',
        'surowa': 'surowy',
        'surowe': 'surowy',
        'lakierowany': 'lakierowany',
        'lakierowana': 'lakierowany',
        'lakierowane': 'lakierowany',
        'olejowany': 'olejowany',
        'olejowana': 'olejowany',
        'olejowane': 'olejowany',
        'bezbarwny': 'lakierowany'  # "lakierowany bezbarwny"
    }
    
    # Mapowanie typów produktów
    PRODUCT_TYPE_MAP = {
        # Istniejące produkty
        'klejonka': 'klejonka',
        'klejonki': 'klejonka',
        'deska': 'deska',
        'deski': 'deska',
        'blat': 'klejonka',
        'blaty': 'klejonka',
        'parapet': 'klejonka',
        'parapety': 'klejonka',
        'spocznik': 'klejonka',
        'spoczniki': 'klejonka',
        'schody': 'klejonka',
        'trep': 'klejonka',
        'trepy': 'klejonka',
        'podstopień': 'klejonka',
        'podstopnie': 'klejonka',
        'stopień': 'klejonka',
        'stopnie': 'klejonka',
    
        # NOWE: Worki opałowe
        'worki opałowe': 'worek opałowy',
        'worek opałowy': 'worek opałowy',
        'worek': 'worek opałowy',
        'wór': 'worek opałowy',
        'woreczek': 'worek opałowy',
        'opał': 'worek opałowy',
        'opałowy': 'worek opałowy',
        'opałowe': 'worek opałowy',
        'do palenia': 'worek opałowy',
    
        # NOWE: Suszenie usługowe
        'suszenie': 'suszenie',
        'suszenia': 'suszenie',
        'wysuszenie': 'suszenie',
        'wysuszenia': 'suszenie',
        'usługa': 'suszenie',
        'usługowe': 'suszenie',
        'usługa suszenia': 'suszenie',
        'suszenie usługowe': 'suszenie',
    
        # NOWE: Tarcica
        'tarcica': 'tarcica',
        'tarcicy': 'tarcica',
    }
    
    def __init__(self):
        # POPRAWKA: Rozszerzone regex dla wymiarów - obsługuje różne separatory i formaty
        self.dimension_patterns = [
            # Format z przecinkami jako separatory dziesiętne (np. 90,3x44x2,1 cm)
            r'(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)\s*cm',
            
            # Format bez spacji przed cm (np. 90x44x2,1cm)
            r'(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)cm',
            
            # Format ze spacją przed cm (klasyczny, np. 90x44x2,1 cm)
            r'(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)\s*[×x*]\s*(\d+(?:[,\.]\d+)?)\s+cm',
            
            # Format z ukośnikami (np. 120/30/2,5 cm)
            r'(\d+(?:[,\.]\d+)?)\s*/\s*(\d+(?:[,\.]\d+)?)\s*/\s*(\d+(?:[,\.]\d+)?)\s*cm',
            
            # Format z ukośnikami bez spacji przed cm
            r'(\d+(?:[,\.]\d+)?)\s*/\s*(\d+(?:[,\.]\d+)?)\s*/\s*(\d+(?:[,\.]\d+)?)cm',
        ]
        
        # Regex dla klasy drewna
        self.class_pattern = r'([AB]/[AB]|[AB]-[AB])'
        
        # Kompiluj regex'y dla wydajności
        self.compiled_dimension_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.dimension_patterns]
        self.compiled_class_pattern = re.compile(self.class_pattern)
    
    def parse_product_name(self, product_name: str) -> Dict[str, Any]:
        """
        Parsuje nazwę produktu i wyciąga wszystkie możliwe informacje
        
        Args:
            product_name (str): Nazwa produktu z Baselinker
            
        Returns:
            Dict[str, Any]: Słownik z wyciągniętymi informacjami
        """
        if not product_name:
            return self._empty_result()
        
        name_lower = product_name.lower()
        result = {
            'product_type': None,      # klejonka/deska
            'wood_species': None,      # dąb/jesion/buk
            'technology': None,        # lity/mikrowczep
            'wood_class': None,        # A/B, B/B
            'finish_state': 'surowy',  # domyślnie surowy
            'length_cm': None,
            'width_cm': None,
            'thickness_cm': None,
            'volume_per_piece': None,  # w m3
            'parsed_successfully': False,
            'raw_name': product_name
        }
        
        try:
            # 1. Wyciągnij typ produktu
            result['product_type'] = self._extract_product_type(name_lower)
            
            # 2. Wyciągnij gatunek drewna
            result['wood_species'] = self._extract_wood_species(name_lower)
            
            # 3. Wyciągnij technologię
            result['technology'] = self._extract_technology(name_lower)
            
            # 4. Wyciągnij klasę drewna
            result['wood_class'] = self._extract_wood_class(product_name)
            
            # 5. Wyciągnij wykończenie
            result['finish_state'] = self._extract_finish_state(name_lower)
            
            # 6. Wyciągnij wymiary
            dimensions = self._extract_dimensions(product_name)
            if dimensions:
                result['length_cm'] = dimensions[0]
                result['width_cm'] = dimensions[1] 
                result['thickness_cm'] = dimensions[2]
                result['volume_per_piece'] = self._calculate_volume(dimensions)
            
            # Sprawdź czy parsowanie było udane
            result['parsed_successfully'] = self._is_parsing_successful(result)
            
        except Exception as e:
            reports_logger.warning(f"[ProductNameParser] Błąd parsowania '{product_name}': {e}")
            result['parsed_successfully'] = False

        return result
    
    def _extract_product_type(self, name_lower: str) -> Optional[str]:
        """
        Wyciąga typ produktu - domyślnie klejonka, chyba że znajdzie słowo wskazujące na deskę
        """
        # Sprawdź czy nazwa zawiera słowa wskazujące na konkretny typ
        for key, value in self.PRODUCT_TYPE_MAP.items():
            if key in name_lower:
                return value
        
        # Jeśli nie znaleziono żadnego słowa kluczowego, domyślnie zwróć 'klejonka'
        return 'klejonka'
    
    def _extract_wood_species(self, name_lower: str) -> Optional[str]:
        """Wyciąga gatunek drewna"""
        for key, value in self.WOOD_SPECIES_MAP.items():
            if key in name_lower:
                return value
        return None
    
    def _extract_technology(self, name_lower: str) -> Optional[str]:
        """Wyciąga technologię"""
        for key, value in self.TECHNOLOGY_MAP.items():
            if key in name_lower:
                return value
        return None
    
    def _extract_wood_class(self, product_name: str) -> Optional[str]:
        """Wyciąga klasę drewna (A/B, B/B)"""
        match = self.compiled_class_pattern.search(product_name)
        if match:
            wood_class = match.group(1)
            # Normalizuj format (A-B -> A/B)
            return wood_class.replace('-', '/')
        return None
    
    def _extract_finish_state(self, name_lower: str) -> str:
        """Wyciąga stan wykończenia"""
        for key, value in self.FINISH_MAP.items():
            if key in name_lower:
                return value
        return 'surowy'  # domyślnie surowy
    
    def _extract_dimensions(self, product_name: str) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
        """
        POPRAWKA: Wyciąga wymiary (długość × szerokość × grubość) 
        Obsługuje różne formaty: przecinki/kropki jako separatory dziesiętne, 
        z/bez spacji przed 'cm'
        """
        for pattern in self.compiled_dimension_patterns:
            match = pattern.search(product_name)
            if match:
                try:
                    # Zamień przecinki na kropki dla poprawnej konwersji do Decimal
                    length_str = match.group(1).replace(',', '.')
                    width_str = match.group(2).replace(',', '.')
                    thickness_str = match.group(3).replace(',', '.')
                    
                    length = Decimal(length_str)
                    width = Decimal(width_str)
                    thickness = Decimal(thickness_str)
                    
                    return (length, width, thickness)
                except (ValueError, TypeError) as e:
                    # Loguj błąd dla debugowania
                    reports_logger.warning(f"[ProductNameParser] Błąd konwersji wymiarów: {e}, input: {match.groups()}")
                    continue
        return None
    
    def _calculate_volume(self, dimensions: Tuple[Decimal, Decimal, Decimal]) -> Decimal:
        """Oblicza objętość w m3"""
        length_cm, width_cm, thickness_cm = dimensions
        # Konwersja z cm3 na m3 (dzielimy przez 1,000,000)
        volume_cm3 = length_cm * width_cm * thickness_cm
        volume_m3 = volume_cm3 / 1000000
        return volume_m3.quantize(Decimal('0.0001'))  # Zaokrąglenie do 4 miejsc po przecinku
    
    def _is_parsing_successful(self, result: Dict) -> bool:
        """Sprawdza czy parsowanie było udane"""
        # Minimalne wymagania: wymiary + gatunek lub typ produktu
        has_dimensions = all([
            result['length_cm'] is not None,
            result['width_cm'] is not None, 
            result['thickness_cm'] is not None
        ])
        
        has_basic_info = result['wood_species'] is not None or result['product_type'] is not None
        
        return has_dimensions and has_basic_info
    
    def _empty_result(self) -> Dict[str, Any]:
        """Zwraca pusty wynik - domyślnie klejonka"""
        return {
            'product_type': 'klejonka',  # domyślnie klejonka
            'wood_species': None,
            'technology': None,
            'wood_class': None,
            'finish_state': 'surowy',
            'length_cm': None,
            'width_cm': None,
            'thickness_cm': None,
            'volume_per_piece': None,
            'parsed_successfully': False,
            'raw_name': ''
        }


# ===== FUNKCJE POMOCNICZE =====

def parse_single_product(product_name: str) -> Dict[str, Any]:
    """
    Funkcja pomocnicza do parsowania pojedynczej nazwy produktu
    
    Args:
        product_name (str): Nazwa produktu
        
    Returns:
        Dict[str, Any]: Wynik parsowania
    """
    parser = ProductNameParser()
    return parser.parse_product_name(product_name)


def test_parser():
    """
    Funkcja testowa parsera - ROZSZERZONA O NOWE FORMATY
    """
    parser = ProductNameParser()
    
    test_names = [
        # Stare formaty (powinny nadal działać)
        "Klejonka bukowa mikrowczep A/B 98.0×40.0×2.0cm",
        "Parapet 160x20x2 cm dębowy lity B/B surowy",
        "Blat drewniany dębowy mikrowczep A/B 90x60x2 cm surowy",
        "Spocznik dąb lity A/B 190x88x3 cm lakierowany",
        
        # NOWE FORMATY Z PRZECINKAMI
        "Klejonka bukowa mikrowczep A/B 90x44x2,1 cm",      # przecinek w grubości
        "Parapet dębowy lity B/B 90x44x2,1cm",              # bez spacji przed cm
        "Blat jesionowy mikrowczep A/B 90,3x44x2,1 cm",     # przecinek w długości
        "Spocznik dębowy lity A/B 90,7x44.5x2,1 cm",        # mieszane formaty
        "Trep bukowy A/B 120,5/30,2/4,8 cm",                # z ukośnikami
        "Stopień dębowy B/B 95,3×35,7×3,2cm",               # bez spacji, przecinki
        
        # EDGE CASES
        "Produkt 100x50x3,0 cm",                            # tylko w grubości
        "Test 90,0x44,0x2,0 cm",                            # wszędzie przecinki
    ]
    
    print("🔍 TEST PARSERA NAZW PRODUKTÓW - ROZSZERZONA WERSJA")
    print("=" * 80)
    
    for name in test_names:
        result = parser.parse_product_name(name)
        print(f"\n📦 PRODUKT: {name}")
        print(f"   ✅ Sukces: {result['parsed_successfully']}")
        print(f"   🏷️  Typ: {result['product_type']}")
        print(f"   🌳 Gatunek: {result['wood_species']}")
        print(f"   ⚙️  Technologia: {result['technology']}")
        print(f"   📊 Klasa: {result['wood_class']}")
        print(f"   🎨 Wykończenie: {result['finish_state']}")
        print(f"   📏 Wymiary: {result['length_cm']}×{result['width_cm']}×{result['thickness_cm']} cm")
        print(f"   📦 Objętość: {result['volume_per_piece']} m³")

if __name__ == "__main__":
    # Uruchom test parsera
    test_parser()