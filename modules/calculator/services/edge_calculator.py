"""
Serwis do kalkulacji cen obróbki krawędzi.
Wzorowany na WoodPriceCalculator.php z PrestaShop woodconfigurator.
"""

from decimal import Decimal, ROUND_HALF_UP

# ============================================
# DEFINICJE KRAWĘDZI
# ============================================

EDGE_DEFINITIONS = {
    # Krawędzie poziome górne (źródło wymiaru)
    'A': {'group': 'top', 'dimension': 'length', 'name': 'Góra przednia', 'name_full': 'Góra przednia (długość)'},
    'B': {'group': 'top', 'dimension': 'length', 'name': 'Góra tylna', 'name_full': 'Góra tylna (długość)'},
    'C': {'group': 'top', 'dimension': 'width', 'name': 'Góra lewa', 'name_full': 'Góra lewa (szerokość)'},
    'D': {'group': 'top', 'dimension': 'width', 'name': 'Góra prawa', 'name_full': 'Góra prawa (szerokość)'},

    # Krawędzie poziome dolne
    'E': {'group': 'bottom', 'dimension': 'length', 'name': 'Dół przednia', 'name_full': 'Dół przednia (długość)'},
    'F': {'group': 'bottom', 'dimension': 'length', 'name': 'Dół tylna', 'name_full': 'Dół tylna (długość)'},
    'G': {'group': 'bottom', 'dimension': 'width', 'name': 'Dół lewa', 'name_full': 'Dół lewa (szerokość)'},
    'H': {'group': 'bottom', 'dimension': 'width', 'name': 'Dół prawa', 'name_full': 'Dół prawa (szerokość)'},

    # Narożniki (krawędzie pionowe)
    'N1': {'group': 'corner', 'dimension': 'thickness', 'name': 'Przedni lewy', 'name_full': 'Narożnik przedni lewy'},
    'N2': {'group': 'corner', 'dimension': 'thickness', 'name': 'Przedni prawy', 'name_full': 'Narożnik przedni prawy'},
    'N3': {'group': 'corner', 'dimension': 'thickness', 'name': 'Tylny lewy', 'name_full': 'Narożnik tylny lewy'},
    'N4': {'group': 'corner', 'dimension': 'thickness', 'name': 'Tylny prawy', 'name_full': 'Narożnik tylny prawy'},
}

# Definicje krawędzi okrągłych (obwodowe)
ROUND_EDGE_DEFINITIONS = {
    'KG': {'group': 'round_perimeter', 'name': 'Krawędź górna', 'name_full': 'Krawędź górna (obwód)'},
    'KD': {'group': 'round_perimeter', 'name': 'Krawędź dolna', 'name_full': 'Krawędź dolna (obwód)'},
}

# Grupy krawędzi dla szybkich akcji
EDGE_GROUPS = {
    'top': ['A', 'B', 'C', 'D'],
    'bottom': ['E', 'F', 'G', 'H'],
    'horizontal': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
    'corner': ['N1', 'N2', 'N3', 'N4'],
    'all': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'N1', 'N2', 'N3', 'N4'],
    'round_all': ['KG', 'KD']
}

# ============================================
# DOMYŚLNE CENY (można nadpisać z bazy)
# ============================================

DEFAULT_PRICES = {
    'sharp': {'per_mb': Decimal('0.00'), 'per_corner': Decimal('0.00')},
    'chamfer': {'per_mb': Decimal('15.00'), 'per_corner': Decimal('5.00')},
    'round': {'per_mb': Decimal('15.00'), 'per_corner': Decimal('5.00')},
}

# Limity promienia R
R_LIMITS = {
    'chamfer': {'min': 3, 'max': 10, 'default': 3},
    'round': {'min': 3, 'max': 20, 'default': 5},
}

VAT_RATE = Decimal('1.23')

import math


# ============================================
# FUNKCJE POMOCNICZE
# ============================================

def calculate_ellipse_perimeter_mm(length_mm, width_mm):
    """
    Oblicza obwód elipsy w mm (aproksymacja Ramanujan).
    length_mm, width_mm to wymiary prostokąta opisanego na elipsie.
    """
    a = length_mm / 2
    b = width_mm / 2
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def calculate_round_edge_price(edge_letter, length_mm, width_mm, edge_type='round', prices=None):
    """
    Oblicza cenę obróbki krawędzi obwodowej dla kształtu okrągłego.

    Returns:
        dict: {letter, type, length_mm, length_mb, price_netto, price_brutto, ...}
    """
    if edge_letter not in ROUND_EDGE_DEFINITIONS:
        return None

    edge_def = ROUND_EDGE_DEFINITIONS[edge_letter]
    perimeter_mm = calculate_ellipse_perimeter_mm(length_mm, width_mm)
    perimeter_mb = Decimal(str(perimeter_mm)) / Decimal('1000')

    if prices is None:
        prices = DEFAULT_PRICES
    type_prices = prices.get(edge_type, DEFAULT_PRICES.get(edge_type, {}))
    price_per_mb = type_prices.get('per_mb', Decimal('15.00'))

    price_netto = (perimeter_mb * price_per_mb).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    price_brutto = (price_netto * VAT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'letter': edge_letter,
        'type': edge_type,
        'group': edge_def['group'],
        'name': edge_def['name'],
        'length_mm': round(perimeter_mm, 2),
        'length_mb': float(perimeter_mb),
        'is_round_perimeter': True,
        'price_netto': float(price_netto),
        'price_brutto': float(price_brutto)
    }

def get_edge_definition(edge_letter: str) -> dict:
    """
    Zwraca definicję krawędzi na podstawie litery.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)

    Returns:
        Słownik z definicją lub None
    """
    return EDGE_DEFINITIONS.get(edge_letter.upper())


def get_edge_length_mm(edge_letter: str, dimensions: dict) -> int:
    """
    Zwraca długość krawędzi w mm na podstawie litery i wymiarów produktu.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)
        dimensions: Słownik z kluczami 'length', 'width', 'thickness' (w cm)

    Returns:
        Długość krawędzi w mm
    """
    definition = get_edge_definition(edge_letter)
    if not definition:
        return 0

    dimension_key = definition['dimension']
    length_cm = dimensions.get(dimension_key, 0)

    # Konwersja cm → mm
    return int(float(length_cm) * 10)


def get_edge_length_cm(edge_letter: str, dimensions: dict) -> float:
    """
    Zwraca długość krawędzi w cm.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)
        dimensions: Słownik z kluczami 'length', 'width', 'thickness' (w cm)

    Returns:
        Długość krawędzi w cm
    """
    definition = get_edge_definition(edge_letter)
    if not definition:
        return 0.0

    dimension_key = definition['dimension']
    return float(dimensions.get(dimension_key, 0))


def is_corner_edge(edge_letter: str) -> bool:
    """
    Sprawdza czy krawędź jest narożnikiem (pionowa).

    Args:
        edge_letter: Litera krawędzi

    Returns:
        True jeśli narożnik, False w przeciwnym razie
    """
    definition = get_edge_definition(edge_letter)
    return definition and definition['group'] == 'corner'


# ============================================
# KALKULACJA CEN
# ============================================

def get_prices_from_db():
    """
    Pobiera ceny z bazy danych (EdgeOption).
    Jeśli brak w bazie, zwraca DEFAULT_PRICES.

    Returns:
        Słownik z cenami dla każdego typu obróbki
    """
    try:
        from modules.calculator.models import EdgeOption

        prices = {}
        options = EdgeOption.query.filter_by(is_active=True).all()

        for opt in options:
            prices[opt.type] = {
                'per_mb': Decimal(str(opt.price_per_mb or 0)),
                'per_corner': Decimal(str(opt.corner_price or 0))
            }

        # Uzupełnij brakujące typy domyślnymi wartościami
        for edge_type, default_price in DEFAULT_PRICES.items():
            if edge_type not in prices:
                prices[edge_type] = default_price

        return prices

    except Exception as e:
        print(f"[edge_calculator] Error loading prices from DB: {e}")
        return DEFAULT_PRICES


def calculate_edge_price(edge_letter: str, edge_type: str, dimensions: dict,
                         r_value: int = None, prices: dict = None) -> dict:
    """
    Oblicza cenę dla pojedynczej krawędzi.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)
        edge_type: Typ obróbki ('sharp', 'chamfer', 'round')
        dimensions: Wymiary produktu w cm {'length', 'width', 'thickness'}
        r_value: Promień R (opcjonalny)
        prices: Słownik z cenami (opcjonalny, jeśli None pobierze z bazy)

    Returns:
        Słownik z ceną netto, brutto i szczegółami
    """
    # Ostre = bez kosztu
    if edge_type == 'sharp':
        return {
            'edge_letter': edge_letter,
            'edge_type': edge_type,
            'length_mm': 0,
            'length_cm': 0,
            'r_value': None,
            'price_netto': Decimal('0.00'),
            'price_brutto': Decimal('0.00'),
            'is_corner': is_corner_edge(edge_letter)
        }

    # Pobierz ceny
    if prices is None:
        prices = get_prices_from_db()

    edge_prices = prices.get(edge_type, DEFAULT_PRICES.get(edge_type, DEFAULT_PRICES['sharp']))

    # Oblicz długość
    length_mm = get_edge_length_mm(edge_letter, dimensions)
    length_cm = get_edge_length_cm(edge_letter, dimensions)

    # Sprawdź czy narożnik
    is_corner = is_corner_edge(edge_letter)

    if is_corner:
        # Narożniki - stała cena za sztukę
        price_netto = edge_prices['per_corner']
    else:
        # Krawędzie poziome - cena za metr bieżący
        length_mb = Decimal(str(length_mm)) / Decimal('1000')
        price_netto = length_mb * edge_prices['per_mb']

    # Zaokrąglij do 2 miejsc po przecinku
    price_netto = price_netto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    price_brutto = (price_netto * VAT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'edge_letter': edge_letter,
        'edge_type': edge_type,
        'length_mm': length_mm,
        'length_cm': length_cm,
        'r_value': r_value,
        'price_netto': price_netto,
        'price_brutto': price_brutto,
        'is_corner': is_corner
    }


def calculate_all_edges(edges_config: list, dimensions: dict) -> dict:
    """
    Oblicza cenę dla wszystkich wybranych krawędzi.

    Args:
        edges_config: Lista konfiguracji krawędzi
                     [{'letter': 'A', 'type': 'chamfer', 'r_value': 3}, ...]
        dimensions: Wymiary produktu {'length': 100, 'width': 25, 'thickness': 3}

    Returns:
        Słownik z podsumowaniem i listą szczegółów
    """
    # Pobierz ceny raz dla wszystkich krawędzi
    prices = get_prices_from_db()

    details = []
    total_netto = Decimal('0.00')
    total_brutto = Decimal('0.00')
    total_length_mm = 0
    horizontal_count = 0
    corner_count = 0

    for edge in edges_config:
        letter = edge.get('letter', '').upper()
        edge_type = edge.get('type', 'sharp')
        r_value = edge.get('r_value')

        # Pomijamy ostre krawędzie (brak kosztu)
        if edge_type == 'sharp':
            continue

        # Oblicz cenę dla tej krawędzi
        result = calculate_edge_price(letter, edge_type, dimensions, r_value, prices)

        # Konwertuj Decimal na float dla JSON
        result_serializable = {
            **result,
            'price_netto': float(result['price_netto']),
            'price_brutto': float(result['price_brutto'])
        }
        details.append(result_serializable)

        # Sumuj
        total_netto += result['price_netto']
        total_brutto += result['price_brutto']
        total_length_mm += result['length_mm']

        if result['is_corner']:
            corner_count += 1
        else:
            horizontal_count += 1

    return {
        'details': details,
        'horizontal_count': horizontal_count,
        'corner_count': corner_count,
        'total_count': horizontal_count + corner_count,
        'total_length_mm': total_length_mm,
        'total_length_mb': round(total_length_mm / 1000, 3),
        'total_netto': float(total_netto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'total_brutto': float(total_brutto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    }


def get_edge_definitions_for_frontend() -> dict:
    """
    Zwraca definicje krawędzi w formacie odpowiednim dla frontendu.

    Returns:
        Słownik z definicjami krawędzi i grupami
    """
    return {
        'edges': EDGE_DEFINITIONS,
        'groups': EDGE_GROUPS,
        'r_limits': R_LIMITS
    }


def validate_r_value(edge_type: str, r_value: int) -> tuple:
    """
    Waliduje wartość promienia R dla danego typu obróbki.

    Args:
        edge_type: Typ obróbki ('chamfer', 'round')
        r_value: Wartość promienia do walidacji

    Returns:
        Tuple (is_valid, corrected_value, message)
    """
    if edge_type not in R_LIMITS:
        return (True, r_value, None)

    limits = R_LIMITS[edge_type]

    if r_value < limits['min']:
        return (False, limits['min'], f"Minimalna wartość R dla {edge_type} to {limits['min']} mm")

    if r_value > limits['max']:
        return (False, limits['max'], f"Maksymalna wartość R dla {edge_type} to {limits['max']} mm")

    return (True, r_value, None)


# ============================================
# DYNAMICZNE KRAWĘDZIE DLA NIEREGULARNYCH KSZTAŁTÓW
# ============================================

def _load_edge_prices():
    """Ładuje ceny krawędzi z bazy danych lub zwraca domyślne."""
    try:
        from modules.calculator.models import EdgeOption
        options = EdgeOption.query.filter(
            (EdgeOption.is_active == True) | (EdgeOption.is_active.is_(None))
        ).all()
        prices = {}
        for opt in options:
            prices[opt.type] = {
                'per_mb': Decimal(str(opt.price_per_mb)) if opt.price_per_mb else Decimal('0'),
                'per_corner': Decimal(str(opt.corner_price)) if opt.corner_price else Decimal('0'),
            }
        return prices if prices else DEFAULT_PRICES
    except Exception:
        return DEFAULT_PRICES


def _generate_edge_definitions(shape_type, shape_data, thickness_cm):
    """
    Generuje definicje krawędzi G (góra), D (dół), P (pion) dla nieregularnych kształtów.
    """
    edges = []
    vertices = shape_data.get('vertices')
    params = shape_data.get('params', {})

    if shape_type == 'circle':
        d = params.get('diameter', 0)
        perimeter = math.pi * d

        edges.append({'id': 'G1', 'type_label': 'top', 'length_cm': perimeter, 'name': 'Obwód (góra)'})
        edges.append({'id': 'D1', 'type_label': 'bottom', 'length_cm': perimeter, 'name': 'Obwód (dół)'})
        edges.append({'id': 'P1', 'type_label': 'vertical', 'length_cm': perimeter, 'name': 'Krawędź boczna (obwód)'})
        return edges

    if not vertices or len(vertices) < 3:
        return edges

    n = len(vertices)
    for i in range(n):
        j = (i + 1) % n
        dx = vertices[j][0] - vertices[i][0]
        dy = vertices[j][1] - vertices[i][1]
        length = math.sqrt(dx * dx + dy * dy)
        edges.append({'id': 'G{}'.format(i + 1), 'type_label': 'top', 'length_cm': length, 'name': 'Góra {}'.format(i + 1)})
        edges.append({'id': 'D{}'.format(i + 1), 'type_label': 'bottom', 'length_cm': length, 'name': 'Dół {}'.format(i + 1)})

    for i in range(n):
        edges.append({'id': 'P{}'.format(i + 1), 'type_label': 'vertical', 'length_cm': thickness_cm, 'name': 'Pion {}'.format(i + 1)})

    return edges


def calculate_dynamic_edges(shape_type, shape_data_json, thickness_cm, edges_config, prices=None):
    """
    Oblicza krawędzie dla nieregularnych kształtów.
    Zwraca szczegóły krawędzi G (góra), D (dół), P (pion) z cenami.

    edges_config format:
    [{"id": "G1", "type": "chamfer", "r_value": 3}, ...]
    """
    import json

    if not shape_data_json:
        return {"details": [], "total_netto": 0, "total_brutto": 0, "edge_definitions": []}

    shape_data = json.loads(shape_data_json) if isinstance(shape_data_json, str) else shape_data_json

    edge_defs = _generate_edge_definitions(shape_type, shape_data, thickness_cm)

    if not prices:
        prices = _load_edge_prices()

    total_netto = Decimal('0')
    total_brutto = Decimal('0')
    details = []

    for edge_cfg in (edges_config or []):
        edge_id = edge_cfg.get('id', '')
        edge_type = edge_cfg.get('type', 'sharp')

        if edge_type == 'sharp':
            details.append({
                'id': edge_id, 'type': edge_type,
                'price_netto': 0, 'price_brutto': 0, 'length_mm': 0
            })
            continue

        edge_def = next((e for e in edge_defs if e['id'] == edge_id), None)
        if not edge_def:
            continue

        length_mm = edge_def['length_cm'] * 10
        type_prices = prices.get(edge_type, DEFAULT_PRICES.get(edge_type, {}))
        per_mb = type_prices.get('per_mb', Decimal('0'))

        price_netto = (Decimal(str(length_mm)) / Decimal('1000') * per_mb).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        price_brutto = (price_netto * VAT_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_netto += price_netto
        total_brutto += price_brutto

        details.append({
            'id': edge_id,
            'type': edge_type,
            'edge_type_label': edge_def.get('type_label', ''),
            'length_mm': float(length_mm),
            'price_netto': float(price_netto),
            'price_brutto': float(price_brutto)
        })

    return {
        'details': details,
        'total_netto': float(total_netto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'total_brutto': float(total_brutto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'edge_definitions': edge_defs
    }


def get_dynamic_edge_definitions(shape_type, shape_data_json, thickness_cm):
    """
    Zwraca definicje dynamicznych krawędzi (bez kalkulacji cen).
    Używane przez frontend do renderowania UI wyboru krawędzi.
    """
    import json

    if not shape_data_json:
        return []

    shape_data = json.loads(shape_data_json) if isinstance(shape_data_json, str) else shape_data_json
    return _generate_edge_definitions(shape_type, shape_data, thickness_cm)
