"""
Serwis do kalkulacji cen obróbki krawędzi.
Wzorowany na WoodPriceCalculator.php z PrestaShop woodconfigurator.
"""

import re

from decimal import Decimal, ROUND_HALF_UP
from modules.logging import get_logger

logger = get_logger('calculator.edge_calculator')

HOLE_EDGE_RE = re.compile(r'^H(\d+)\.(G|N|D|P)(\d+)$')
OUTER_EDGE_RE = re.compile(r'^(G|N|D|P)(\d+)$')


def parse_edge_id(edge_id):
    """
    Parsuje ID krawędzi do struktury:
    - outer:  {'kind': 'outer', 'type': 'G'|'N'|'D'|'P', 'idx': int 0-based}
    - hole:   {'kind': 'hole',  'type': 'G'|'N'|'D'|'P', 'hole_idx': int 0-based, 'idx': int 0-based}
    - None gdy nieznany format / pusty / nie-string.
    """
    if not edge_id or not isinstance(edge_id, str):
        return None
    m = HOLE_EDGE_RE.match(edge_id)
    if m:
        return {
            'kind': 'hole',
            'hole_idx': int(m.group(1)) - 1,
            'type': m.group(2),
            'idx': int(m.group(3)) - 1,
        }
    m = OUTER_EDGE_RE.match(edge_id)
    if m:
        return {
            'kind': 'outer',
            'type': m.group(1),
            'idx': int(m.group(2)) - 1,
        }
    return None


_HOLE_TYPE_PL = {'G': 'góra', 'D': 'dół', 'P': 'pion', 'N': 'narożnik'}
_OUTER_TYPE_PL = {'G': 'Krawędź', 'D': 'Krawędź dolna', 'P': 'Krawędź boczna', 'N': 'Narożnik'}


def human_edge_label(edge_id):
    """
    Zwraca polską czytelną etykietę dla ID krawędzi.
    Przykłady:
    - 'G1' -> 'Krawędź 1'
    - 'N4' -> 'Narożnik 4'
    - 'H1.G2' -> 'Wycięcie 1, góra 2'
    - 'H2.P3' -> 'Wycięcie 2, pion 3'
    Jeśli nieznany format — zwraca surowe ID.
    """
    parsed = parse_edge_id(edge_id)
    if not parsed:
        return str(edge_id) if edge_id is not None else ''
    if parsed['kind'] == 'hole':
        type_name = _HOLE_TYPE_PL.get(parsed['type'], 'element')
        return 'Wycięcie {}, {} {}'.format(parsed['hole_idx'] + 1, type_name, parsed['idx'] + 1)
    type_name = _OUTER_TYPE_PL.get(parsed['type'], 'Element')
    return '{} {}'.format(type_name, parsed['idx'] + 1)

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


# ============================================
# KALKULACJA CEN
# ============================================

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

    # Krawędzie dziur: pełna symetria z outer dynamicznym (G góra, D dół, P pion)
    holes = shape_data.get('holes') or []
    for h_idx, hole in enumerate(holes):
        if not hole or len(hole) < 3:
            continue
        h_num = h_idx + 1
        m = len(hole)
        # G — góra (per krawędź dziury)
        for j in range(m):
            k = (j + 1) % m
            hdx = hole[k][0] - hole[j][0]
            hdy = hole[k][1] - hole[j][1]
            h_length = math.sqrt(hdx * hdx + hdy * hdy)
            edges.append({
                'id': 'H{}.G{}'.format(h_num, j + 1),
                'type_label': 'top',
                'length_cm': h_length,
                'name': 'Wycięcie {}, góra {}'.format(h_num, j + 1),
            })
        # D — dół (per krawędź dziury, ta sama długość co góra)
        for j in range(m):
            k = (j + 1) % m
            hdx = hole[k][0] - hole[j][0]
            hdy = hole[k][1] - hole[j][1]
            h_length = math.sqrt(hdx * hdx + hdy * hdy)
            edges.append({
                'id': 'H{}.D{}'.format(h_num, j + 1),
                'type_label': 'bottom',
                'length_cm': h_length,
                'name': 'Wycięcie {}, dół {}'.format(h_num, j + 1),
            })
        # P — pion (per wierzchołek dziury, długość = grubość)
        for j in range(m):
            edges.append({
                'id': 'H{}.P{}'.format(h_num, j + 1),
                'type_label': 'vertical',
                'length_cm': thickness_cm,
                'name': 'Wycięcie {}, pion {}'.format(h_num, j + 1),
            })

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

        # Narożniki — cena flat per sztuka
        if edge_def.get('type_label') == 'corner':
            per_corner = type_prices.get('per_corner', Decimal('0'))
            price_netto = Decimal(str(per_corner)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
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
