"""
Serwis cenowy — jedyne źródło prawdy o liczeniu wycen.
Port logiki z JS (calculator-core.js, calculator-ui.js, edges.js).
Czyste funkcje: dane cennikowe wstrzykiwane przez PricingData (testy bez DB).

UWAGA PARYTET: liczymy na floatach i zaokrąglamy dokładnie tam, gdzie JS.
Wszelkie "dziwactwa" (ceil grubości, circle liczony wzorem prostokąta w wykończeniu,
piony P* jako narożniki w krawędziach) są CELOWE — tak liczy frontend na produkcji.
"""

import math
from dataclasses import dataclass, field

VAT = 1.23

# Odpowiednik variantMapping z calculator-core.js:155
VARIANT_MAPPING = {
    'dab-lity-ab': {'species': 'Dąb', 'technology': 'Lity', 'wood_class': 'A/B'},
    'dab-lity-bb': {'species': 'Dąb', 'technology': 'Lity', 'wood_class': 'B/B'},
    'dab-micro-ab': {'species': 'Dąb', 'technology': 'Mikrowczep', 'wood_class': 'A/B'},
    'dab-micro-bb': {'species': 'Dąb', 'technology': 'Mikrowczep', 'wood_class': 'B/B'},
    'jes-lity-ab': {'species': 'Jesion', 'technology': 'Lity', 'wood_class': 'A/B'},
    'jes-micro-ab': {'species': 'Jesion', 'technology': 'Mikrowczep', 'wood_class': 'A/B'},
    'buk-lity-ab': {'species': 'Buk', 'technology': 'Lity', 'wood_class': 'A/B'},
    'buk-micro-ab': {'species': 'Buk', 'technology': 'Mikrowczep', 'wood_class': 'A/B'},
}


def round_grosze(value):
    """Odpowiednik JS roundToGrosze: Math.round((v+EPSILON)*100)/100 (half-up dla cen >= 0)."""
    return math.floor((value + 1e-9) * 100 + 0.5) / 100


@dataclass
class PricingData:
    """Zrzut cenników z DB — zwykłe typy, żeby testy nie potrzebowały bazy."""
    price_entries: list = field(default_factory=list)          # wiersze prices jako dict (jak Price.to_dict())
    multipliers: dict = field(default_factory=dict)            # client_type -> float(multiplier)
    finishing_options_by_id: dict = field(default_factory=dict)   # id -> dict opcji (price_netto, full_path, ...)
    finishing_options_by_path: dict = field(default_factory=dict) # full_path -> float(price_netto)
    edge_prices: dict = field(default_factory=dict)            # type -> {'per_mb': float, 'per_corner': float}
    cutout_price_netto: float = 0.0
    round_surcharge_netto: float = 0.0


def load_pricing_data():
    """Ładuje cenniki z DB. Jedyna funkcja w tym module dotykająca bazy."""
    from modules.calculator.models import (
        Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting
    )

    price_entries = [p.to_dict() for p in Price.query.all()]

    multipliers = {
        m.client_type: float(m.multiplier)
        for m in Multiplier.query.all() if m.client_type
    }

    finishing_by_id = {}
    finishing_by_path = {}
    cutout_price = 0.0
    for opt in FinishingOption.get_flat_list():
        finishing_by_id[opt['id']] = opt
        if opt.get('price_netto') is not None:
            finishing_by_path[opt['full_path']] = float(opt['price_netto'])
        if opt.get('code') == 'CUTOUT' or opt.get('inherited_code') == 'CUTOUT':
            cutout_price = float(opt.get('price_netto') or 0)

    edge_prices = {}
    for e in EdgeOption.query.filter_by(is_active=True).all():
        edge_prices[e.type] = {
            'per_mb': float(e.price_per_mb or 0),
            'per_corner': float(e.corner_price or 0),
        }

    surcharge = float(CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00'))

    return PricingData(
        price_entries=price_entries,
        multipliers=multipliers,
        finishing_options_by_id=finishing_by_id,
        finishing_options_by_path=finishing_by_path,
        edge_prices=edge_prices,
        cutout_price_netto=cutout_price,
        round_surcharge_netto=surcharge,
    )


def find_price_entry(data, species, technology, wood_class, thickness, length, width):
    """Odpowiednik JS getPrice (calculator-core.js:286) — ceil grubości, zakresy z cennika."""
    rounded_thickness = math.ceil(thickness)
    for entry in data.price_entries:
        if (entry['species'] == species
                and entry['technology'] == technology
                and entry['wood_class'] == wood_class
                and entry['thickness_min'] <= rounded_thickness <= entry['thickness_max']
                and entry['length_min'] <= length <= entry['length_max']
                and entry['width_min'] <= width <= entry['width_max']):
            return entry
    return None


def calculate_material_variants(product, multiplier, data):
    """Odpowiednik pętli wariantów w JS updatePrices (calculator-core.js:527-591)."""
    length = float(product['length'])
    width = float(product['width'])
    thickness = float(product['thickness'])
    quantity = int(product.get('quantity', 1))
    shape = product.get('shape', 'rectangular')
    holes_count = int(product.get('holes_count', 0))

    # JS: calculateSingleVolume(length, width, Math.ceil(thickness))
    volume = (length / 100) * (width / 100) * (math.ceil(thickness) / 100)

    results = []
    for code, cfg in VARIANT_MAPPING.items():
        match = find_price_entry(
            data, cfg['species'], cfg['technology'], cfg['wood_class'],
            thickness, length, width
        )
        if not match:
            results.append({'variant_code': code, 'available': False})
            continue

        unit_netto = volume * match['price_per_m3'] * multiplier
        # Dopłaty PO mnożniku, per sztuka (JS 546-556)
        if shape in ('round', 'circle') and data.round_surcharge_netto:
            unit_netto += data.round_surcharge_netto
        if holes_count > 0 and data.cutout_price_netto > 0:
            unit_netto += holes_count * data.cutout_price_netto

        unit_brutto = round_grosze(unit_netto * VAT)
        results.append({
            'variant_code': code,
            'available': True,
            'volume_m3': volume,
            'price_per_m3': match['price_per_m3'],
            'multiplier': multiplier,
            'unit_netto': unit_netto,                       # celowo niezaokrąglone (jak JS finalPrice)
            'unit_brutto': unit_brutto,
            'total_netto': round_grosze(unit_netto * quantity),
            'total_brutto': round_grosze(unit_brutto * quantity),
        })
    return results
