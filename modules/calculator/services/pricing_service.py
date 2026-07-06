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
