"""
Serwis cenowy — jedyne źródło prawdy o liczeniu wycen.
Port logiki z JS (calculator-core.js, calculator-ui.js, edges.js).
Czyste funkcje: dane cennikowe wstrzykiwane przez PricingData (testy bez DB).

UWAGA PARYTET: liczymy na floatach i zaokrąglamy dokładnie tam, gdzie JS.
Wszelkie "dziwactwa" (ceil grubości, circle liczony wzorem prostokąta w wykończeniu,
piony P* jako narożniki w krawędziach) są CELOWE — tak liczy frontend na produkcji.
"""

import json as _json
import math
import time
import threading
from dataclasses import dataclass, field

from flask import current_app

from modules.calculator.services.edge_calculator import (
    EDGE_DEFINITIONS, calculate_ellipse_perimeter_mm, _generate_edge_definitions,
)

# Legacy fallbacki cen wykończenia (calculator-ui.js:606-614)
# UWAGA: realna nazwa roota w drzewku FinishingOption to 'Lakierowane'
# (zweryfikowane FinishingOption.query.filter_by(parent_id=None) — id=2,
# code='LAK'). Klucz 'Lakierowanie' zostaje obok dla legacy payloadów
# (starsze integracje/testy mogły wysyłać tę formę).
_LEGACY_FINISHING_FALLBACK = {
    ('Lakierowanie', 'Bezbarwne'): ('Lakierowane bezbarwne', 200.0),
    ('Lakierowanie', 'Barwne'): ('Lakierowane barwne', 250.0),
    ('Lakierowane', 'Bezbarwne'): ('Lakierowane bezbarwne', 200.0),
    ('Lakierowane', 'Barwne'): ('Lakierowane barwne', 250.0),
    ('Olejowanie', None): ('Olejowanie', 250.0),
}

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


def _finishing_maps_from_flat_list(flat_list):
    """
    Buduje mapy cen wykończeń z płaskiej listy FinishingOption.get_flat_list().

    UWAGA PARYTET: musi odpowiadać dokładnie temu, co robi frontend w
    loadFinishingPrices() (calculator-ui.js:33-56) — JS liczy na
    effective_price_netto (cena EFEKTYWNA, dziedziczona z rodzica gdy opcja
    nie ma własnej ceny), NIE na surowym price_netto. Stary endpoint
    get_finishing_prices_data() też zwraca effective_price_netto (patrz wyżej).

    Zwraca (by_id, by_path, cutout_price_netto):
    - by_id[id]: dict opcji z price_netto ustawionym na effective_price_netto,
      plus full_path/level/code/inherited_code.
    - by_path[full_path] = float(effective_price_netto) dla KAŻDEJ opcji
      (jak window.finishingPrices w JS), plus klucz legacy
      fullPath.replace(' > ', ' ') z pierwszą literą wielką (JS:44-47),
      plus — dla level==0 — klucz z samą nazwą (JS:49-52).
    - cutout_price_netto = effective_price_netto opcji, której code lub
      inherited_code == 'CUTOUT' (JS:56).
    """
    by_id = {}
    by_path = {}
    cutout_price = 0.0

    for opt in flat_list:
        effective_price = opt.get('effective_price_netto')
        opt_with_effective = dict(opt)
        opt_with_effective['price_netto'] = effective_price
        by_id[opt['id']] = opt_with_effective

        full_path = opt.get('full_path') or opt.get('name')
        if effective_price is not None:
            price_float = float(effective_price)
            by_path[full_path] = price_float

            # Klucz legacy: "Lakierowanie > Bezbarwne" -> "Lakierowanie bezbarwne"
            # (JS String.replace(' > ', ' ') zamienia tylko PIERWSZE wystąpienie)
            legacy_name = full_path.replace(' > ', ' ', 1).lower()
            legacy_name_capitalized = legacy_name[:1].upper() + legacy_name[1:] if legacy_name else legacy_name
            by_path[legacy_name_capitalized] = price_float

            # Opcje główne (poziom 0) — też pod samą nazwą
            if opt.get('level') == 0:
                by_path[opt['name']] = price_float

        code = opt.get('code') or opt.get('inherited_code')
        if code == 'CUTOUT':
            cutout_price = float(effective_price or 0)

    return by_id, by_path, cutout_price


def _build_pricing_data():
    """Ładuje cenniki z DB. Jedyna funkcja w tym module dotykająca bazy."""
    from modules.calculator.models import (
        Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting
    )

    price_entries = [p.to_dict() for p in Price.query.all()]

    multipliers = {
        m.client_type: float(m.multiplier)
        for m in Multiplier.query.all() if m.client_type
    }

    finishing_by_id, finishing_by_path, cutout_price = _finishing_maps_from_flat_list(
        FinishingOption.get_flat_list()
    )

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


# Cache cenników w pamięci procesu — cenniki zmieniają się raz na
# tygodnie/miesiące (potwierdzone przez usera), więc odpytywanie 5 tabel
# przy KAŻDYM /calculate jest zbędnym obciążeniem bazy. TTL to tylko siatka
# bezpieczeństwa na wypadek edycji poza aplikacją (np. phpMyAdmin) —
# normalnie cache jest odświeżany od razu przez invalidate_pricing_cache()
# wołane po zapisie w panelu admina.
_PRICING_CACHE = {'data': None, 'ts': 0.0}
_PRICING_CACHE_LOCK = threading.Lock()
# 1 godzina — cenniki zmieniają się raz na tygodnie/miesiące, a zmiany przez
# panel admina i tak odświeżają cache natychmiast przez invalidate_pricing_cache();
# TTL to wyłącznie siatka bezpieczeństwa na zmiany poza aplikacją (np. phpMyAdmin).
PRICING_CACHE_TTL = 3600  # sekundy


def load_pricing_data(use_cache=True):
    """Zwraca PricingData — z cache (domyślnie) albo świeżo z bazy.

    use_cache=False wymusza pominięcie cache (np. golden check / testy
    porównawcze, gdzie chcemy mieć pewność, że dane pochodzą wprost z DB).
    """
    if use_cache:
        now = time.time()
        cached = _PRICING_CACHE['data']
        if cached is not None and (now - _PRICING_CACHE['ts']) < PRICING_CACHE_TTL:
            return cached

    data = _build_pricing_data()

    if use_cache:
        with _PRICING_CACHE_LOCK:
            _PRICING_CACHE['data'] = data
            _PRICING_CACHE['ts'] = time.time()

    return data


def invalidate_pricing_cache():
    """Czyści cache cenników — wołać zaraz po zapisie zmian w panelu admina
    (prices/finishing_options/edge_options/calculator_settings), żeby zmiana
    była widoczna natychmiast w /calculate, bez czekania na TTL."""
    with _PRICING_CACHE_LOCK:
        _PRICING_CACHE['data'] = None
        _PRICING_CACHE['ts'] = 0.0


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


def calculate_finishing(product, data):
    """Odpowiednik JS calculateFinishingCost (calculator-ui.js:493-651)."""
    finishing_type = product.get('finishing_type') or 'Surowe'
    zero = {'netto': 0.0, 'brutto': 0.0, 'price_per_m2': 0.0, 'surface_m2': 0.0}

    if finishing_type == 'Surowe':
        return zero

    # JS: Lakierowanie pokazuje sekcję połysku; brak wyboru połysku -> cena 0.
    # UWAGA: realna nazwa roota w drzewku FinishingOption to 'Lakierowane'
    # (zweryfikowane w DB — id=2, code='LAK'); 'Lakierowanie' zostaje w
    # sprawdzeniu dla legacy payloadów (starsze wywołania/testy).
    if finishing_type in ('Lakierowanie', 'Lakierowane') and not product.get('finishing_gloss_level'):
        return zero

    # Guard: brak któregoś wymiaru (None/pusty/nie-liczbowy) -> zero,
    # odpowiednik JS recalculateEdgesForForm:2050-2052 (analogiczny guard
    # zastosowany też w calculate_edges_pricing).
    for dim_key in ('length', 'width', 'thickness'):
        dim_val = product.get(dim_key)
        if dim_val is None or dim_val == '':
            return zero
        try:
            float(dim_val)
        except (TypeError, ValueError):
            return zero

    length_m = float(product['length']) / 100
    width_m = float(product['width']) / 100
    thickness_m = float(product['thickness']) / 100
    quantity = int(product.get('quantity', 1))
    shape = product.get('shape', 'rectangular')

    # Powierzchnia — UWAGA: tylko 'round' ma wzór elipsy; 'circle' i nieregularne
    # wpadają we wzór prostopadłościanu (tak liczy JS — nie "poprawiać")
    if shape == 'round':
        a, b = length_m / 2, width_m / 2
        top_bottom = 2 * math.pi * a * b
        perimeter = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
        surface_per_piece = top_bottom + perimeter * thickness_m
    else:
        surface_per_piece = 2 * (length_m * width_m + length_m * thickness_m + width_m * thickness_m)

    surface_total = surface_per_piece * quantity

    # Cena za m² — kolejność fallbacków jak w JS (593-614)
    price_per_m2 = 0.0
    option_id = product.get('finishing_option_id')
    if option_id and option_id in data.finishing_options_by_id:
        opt = data.finishing_options_by_id[option_id]
        if opt.get('price_netto'):
            price_per_m2 = float(opt['price_netto'])
    if price_per_m2 == 0.0 and product.get('finishing_full_path'):
        price_per_m2 = data.finishing_options_by_path.get(product['finishing_full_path'], 0.0)
    # Wykończenia wielopoziomowe (Lakierowane > Barwne > <KOLOR>): cena siedzi na
    # LIŚCIU koloru (np. 'Lakierowane > Barwne > BRUNAT 22-15' = 150), a węzeł
    # wariantu ('Lakierowane > Barwne') ma cenę 0. Zapis wyceny (save_quote.js) i
    # boty NIE wysyłają finishing_full_path ani finishing_option_id — tylko
    # type+variant+color. Bez tego odtworzenia legacy fallback poniżej trafia w
    # węzeł wariantu (0.0) i cała pozycja Barwne wychodzi 0 zł. Odbudowujemy
    # kanoniczną ścieżkę liścia z type+variant+color i pobieramy cenę stamtąd.
    if price_per_m2 == 0.0 and product.get('finishing_color'):
        variant = product.get('finishing_variant')
        leaf_parts = [finishing_type] + ([variant] if variant else []) + [product['finishing_color']]
        color_path = ' > '.join(leaf_parts)
        price_per_m2 = data.finishing_options_by_path.get(color_path, 0.0)
    if price_per_m2 == 0.0:
        variant = product.get('finishing_variant')
        key = (finishing_type, variant if finishing_type in ('Lakierowanie', 'Lakierowane') else None)
        legacy = _LEGACY_FINISHING_FALLBACK.get(key)
        if legacy:
            path_name, default = legacy
            price_per_m2 = data.finishing_options_by_path.get(path_name, default)

    netto = round_grosze(surface_total * price_per_m2)
    brutto = round_grosze(netto * VAT)
    return {'netto': netto, 'brutto': brutto,
            'price_per_m2': price_per_m2, 'surface_m2': surface_total}


# Krawędzie obwodowe dla kształtów okrągłych
_ROUND_EDGE_LETTERS = {'KG', 'KD'}


def calculate_edges_pricing(edges, product, data):
    """
    Ceny krawędzi zapisywane do DB liczy modal applyEdges (edges.js:1536-1582) —
    TO jest źródło prawdy dla semantyki cenowej, nie recalculateEdgesForForm.
    Klasyfikacja krawędzi (narożniki N1-N4, piony P*/H*.P*, kształt okrągły/
    nieregularny, długości) jest wspólna dla obu trybów i pokrywa się z tym,
    co dziś jest w tej funkcji.

    Tryb liczenia zależy od `product['edges_mode']`:
    - 'advanced' (edges.js:1546-1577): PER KRAWĘDŹ zaokrąglamy netto_i=round2(raw_i)
      i brutto_i=round2(raw_i*VAT) (brutto liczone z RAW, nie z zaokrąglonego netto!),
      a total_netto/total_brutto to round2(Σ zaokrąglonych × qty).
    - basic/None/legacy (domyślne, jak dotychczas): sumujemy NIEzaokrąglone
      wartości per-edge, a zaokrąglamy dopiero raz na końcu × qty.

    Narożniki: krawędź o wymiarze thickness (N1-N4) LUB pion dynamiczny
    (P*, H*.P*) — modal applyEdges klasyfikuje piony po group=='vertical'
    z definicji dynamicznych, więc traktowanie H*.P* jako narożnik flat
    per_corner jest tu POPRAWNE. Quirk `letter.startsWith('P')`, wcześniej
    widoczny w JS recalculateEdgesForForm (Task 9: ciało tej funkcji
    przebudowane, liczenie cen w JS usunięte na rzecz danych z backendu)
    — celowo NIE replikowany.

    UWAGA: legacy edge_calculator.calculate_all_edges (liczył inaczej) zostało
    usunięte jako martwy kod (Task 9, zero referencji) — ta funkcja jest teraz
    jedynym źródłem prawdy dla cen krawędzi.
    """
    if not edges:
        return {'netto': 0.0, 'brutto': 0.0, 'details': []}

    # Guard: brak któregoś wymiaru (None/pusty/nie-liczbowy) -> zero,
    # odpowiednik JS recalculateEdgesForForm:2050-2052.
    for dim_key in ('length', 'width', 'thickness'):
        dim_val = product.get(dim_key)
        if dim_val is None or dim_val == '':
            return {'netto': 0.0, 'brutto': 0.0, 'details': []}
        try:
            float(dim_val)
        except (TypeError, ValueError):
            return {'netto': 0.0, 'brutto': 0.0, 'details': []}

    dims = {'length': float(product['length']), 'width': float(product['width']),
            'thickness': float(product['thickness'])}
    quantity = int(product.get('quantity', 1))
    shape = product.get('shape', 'rectangular')
    is_round = shape in ('round', 'circle')
    is_advanced = product.get('edges_mode') == 'advanced'

    # Definicje dynamiczne dla nieregularnych — do wyznaczenia długości G*/D*
    dynamic_defs = {}
    shape_data = product.get('shape_data')
    if shape_data and shape not in ('rectangular',):
        if isinstance(shape_data, str):
            shape_data = _json.loads(shape_data)
        for d in _generate_edge_definitions(shape, shape_data, dims['thickness']):
            dynamic_defs[d['id']] = d

    total_netto = 0.0          # suma RAW (tryb basic)
    total_netto_rounded = 0.0  # suma zaokrąglonych per-edge netto (tryb advanced)
    total_brutto_rounded = 0.0  # suma zaokrąglonych per-edge brutto liczonych z RAW (tryb advanced)
    details = []
    for edge in edges:
        letter = str(edge.get('letter') or edge.get('id') or '').upper()
        etype = edge.get('type', 'sharp')
        prices = data.edge_prices.get(etype, {'per_mb': 0.0, 'per_corner': 0.0})

        length_cm = 0.0
        is_corner = False
        if etype == 'sharp':
            pass  # 0 zł, ale zostaje w details
        elif is_round and letter in _ROUND_EDGE_LETTERS:
            length_cm = calculate_ellipse_perimeter_mm(dims['length'] * 10, dims['width'] * 10) / 10
        elif letter in EDGE_DEFINITIONS:
            d = EDGE_DEFINITIONS[letter]
            is_corner = d['group'] == 'corner'
            length_cm = dims['thickness'] if is_corner else dims[d['dimension']]
        else:
            # Nieregularny: piony (P*, H*.P*) = narożniki flat; G*/D* per mb (JS 2092-2101)
            base_id = letter.split('.')[-1] if '.' in letter else letter
            if base_id.startswith('P'):
                is_corner = True
                length_cm = dims['thickness']
            elif letter in dynamic_defs:
                length_cm = dynamic_defs[letter]['length_cm']
            elif edge.get('length_cm') is not None:
                length_cm = float(edge['length_cm'])
            else:
                continue  # nieznana krawędź — jak JS (return w forEach)

        if etype == 'sharp':
            price_netto = 0.0
        elif is_corner:
            price_netto = prices['per_corner']
        else:
            price_netto = (length_cm / 100) * prices['per_mb']

        total_netto += price_netto
        price_netto_rounded = round_grosze(price_netto)
        price_brutto_rounded = round_grosze(price_netto * VAT)
        total_netto_rounded += price_netto_rounded
        total_brutto_rounded += price_brutto_rounded
        details.append({'letter': letter, 'type': etype,
                        'length_cm': round_grosze(length_cm),
                        'price_netto': price_netto_rounded,
                        'price_brutto': price_brutto_rounded,
                        'is_corner': is_corner})

    if is_advanced:
        # applyEdges (edges.js:1546-1577): sumujemy ZAOKRĄGLONE per-edge
        # wartości, brutto per-edge liczone z RAW (nie z zaokrąglonego netto).
        return {
            'netto': round_grosze(total_netto_rounded * quantity),
            'brutto': round_grosze(total_brutto_rounded * quantity),
            'details': details,
        }

    return {
        'netto': round_grosze(total_netto * quantity),
        'brutto': round_grosze(total_netto * VAT * quantity),
        'details': details,
    }


# =============================================================================
# Istniejące API endpointu GET /calculator/api/finishing-prices (sprzed przebudowy).
# Przywrócone verbatim z main po tym, jak przebudowa nadpisała plik i skasowała
# te funkcje — używane przez modules/calculator/routers/finishing_routers.py
# oraz frontend (calculator-ui.js: loadFinishingPrices / window.cutoutPriceNetto).
# =============================================================================


def get_finishing_prices_data():
    """
    Pobiera ceny wykończeń z bazy danych - hierarchiczne drzewko.
    Jeśli nowa tabela finishing_options nie działa, fallback do finishing_type_prices.

    Returns:
        tuple: (lista cen, kod HTTP)
    """
    from modules.calculator.models import FinishingOption, FinishingTypePrice

    try:
        # Spróbuj z nowej tabeli hierarchicznej
        try:
            flat_list = FinishingOption.get_flat_list(include_inactive=False)
            if flat_list:
                prices_data = []
                for opt in flat_list:
                    prices_data.append({
                        'id': opt['id'],
                        'name': opt['name'],
                        'code': opt.get('code') or opt.get('inherited_code'),
                        'full_path': opt['full_path'],
                        'price_netto': opt['effective_price_netto'],
                        'level': opt['level'],
                        'parent_id': opt['parent_id'],
                        'image_path': opt.get('image_path'),
                    })
                return prices_data, 200
        except Exception as e:
            current_app.logger.warning(f"Fallback do starej tabeli finishing: {e}")

        # Fallback: stara tabela
        prices = FinishingTypePrice.query.filter_by(is_active=True).all()
        prices_data = []
        for price in prices:
            prices_data.append({
                'id': price.id,
                'name': price.name,
                'price_netto': float(price.price_netto),
            })
        return prices_data, 200

    except Exception as e:
        current_app.logger.error(f"Błąd pobierania cen wykończeń: {str(e)}")
        return {"success": False, "error": "Blad pobierania cen wykonczeń"}, 500


# =============================================================================
# Task 5: Walidacja i agregacja wyceny — calculate_quote i helper'y
# =============================================================================

def _err(field, code, message, product_index=None, limit=None, given=None):
    """Buduje błąd w standardowym formacie: field, code, message + opcjonalne metadane."""
    e = {'field': field, 'code': code, 'message': message}
    if product_index is not None:
        e['product_index'] = product_index
    if limit is not None:
        e['limit'] = limit
    if given is not None:
        e['given'] = given
    return e


def _pricing_limits(data):
    """Globalne min/max z cennika — jak JS getPricingLimits (calculator-core.js:225)."""
    if not data.price_entries:
        return None
    return {
        'length_min': min(e['length_min'] for e in data.price_entries),
        'length_max': max(e['length_max'] for e in data.price_entries),
        'width_min': min(e['width_min'] for e in data.price_entries),
        'width_max': max(e['width_max'] for e in data.price_entries),
        'thickness_min': min(e['thickness_min'] for e in data.price_entries),
        'thickness_max': max(e['thickness_max'] for e in data.price_entries),
    }


def resolve_multiplier(client_type, explicit_multiplier, data):
    """Partner z fixed mnożnikiem podaje explicit_multiplier; reszta grupę cenową."""
    if explicit_multiplier is not None:
        return float(explicit_multiplier), None
    if not client_type:
        return None, _err('client_type', 'MISSING', 'Nie wybrano grupy cenowej.')
    if client_type not in data.multipliers:
        dostepne = ', '.join(sorted(data.multipliers)) or 'brak'
        return None, _err('client_type', 'UNKNOWN_CLIENT_TYPE',
                          f'Nieznana grupa cenowa "{client_type}". Dostępne: {dostepne}.')
    return data.multipliers[client_type], None


_FIELD_PL = {'length': 'długość', 'width': 'szerokość', 'thickness': 'grubość'}


def _safe_number(raw, caster):
    """Próbuje skonwertować raw przez caster (float/int); (True, wartość) albo (False, None)."""
    try:
        return True, caster(raw)
    except (TypeError, ValueError):
        return False, None


def validate_product(product, data):
    """
    Walidacja wymiarów — komunikaty PL gotowe do przekazania klientowi przez LLM.

    UWAGA (bot/LLM): pola numeryczne (length/width/thickness/quantity) mogą
    przyjść jako string z LLM (np. '"abc"' zamiast liczby) — konwersja jest
    tu bezpieczna (bez wyjątku), nieudana konwersja daje błąd INVALID_TYPE
    zamiast crashować calculate_quote. Wcześniejszy zwrot błędów (return
    errors) gwarantuje, że dalsze float(...)/int(...) w calculate_material_variants/
    calculate_finishing/calculate_edges_pricing NIE zostaną wywołane dla
    produktu z błędami walidacji (patrz calculate_quote: `if p_errors: ... continue`).
    """
    errors = []
    idx = product.get('index')

    parsed = {}
    for field in ('length', 'width', 'thickness'):
        val = product.get(field)
        if val is None or val == '':
            errors.append(_err(field, 'MISSING',
                               f'Brak wymiaru: {_FIELD_PL[field]} (w cm).', idx))
            continue
        ok, num = _safe_number(val, float)
        if not ok:
            errors.append(_err(field, 'INVALID_TYPE',
                               f'{_FIELD_PL[field].capitalize()} musi być liczbą (podano: "{val}").',
                               idx))
            continue
        parsed[field] = num

    qty = product.get('quantity')
    if not qty:
        errors.append(_err('quantity', 'MISSING', 'Podaj ilość sztuk (minimum 1).', idx))
    else:
        ok, qty_num = _safe_number(qty, int)
        if not ok:
            errors.append(_err('quantity', 'INVALID_TYPE',
                               f'Ilość sztuk musi być liczbą (podano: "{qty}").', idx))
        elif qty_num < 1:
            errors.append(_err('quantity', 'MISSING', 'Podaj ilość sztuk (minimum 1).', idx))

    if errors:
        return errors

    limits = _pricing_limits(data)
    if not limits:
        return [_err('products', 'NO_PRICELIST', 'Brak cennika w systemie.', idx)]

    shape = product.get('shape', 'rectangular')
    checks = []
    if shape == 'circle':
        # Koło: średnica (length) musi mieścić się w obu zakresach (JS 448-453)
        d_min = max(limits['length_min'], limits['width_min'])
        d_max = min(limits['length_max'], limits['width_max'])
        checks.append(('length', 'średnica', parsed['length'], d_min, d_max))
    else:
        checks.append(('length', 'długość', parsed['length'],
                       limits['length_min'], limits['length_max']))
        checks.append(('width', 'szerokość', parsed['width'],
                       limits['width_min'], limits['width_max']))
    checks.append(('thickness', 'grubość', parsed['thickness'],
                   limits['thickness_min'], limits['thickness_max']))

    for field, name_pl, val, vmin, vmax in checks:
        if val > vmax:
            errors.append(_err(field, 'MAX_EXCEEDED',
                               f'Maksymalna {name_pl} to {vmax:g} cm (podano {val:g} cm).',
                               idx, limit=vmax, given=val))
        elif val < vmin:
            errors.append(_err(field, 'MIN_NOT_MET',
                               f'Minimalna {name_pl} to {vmin:g} cm (podano {val:g} cm).',
                               idx, limit=vmin, given=val))
    return errors


def calculate_quote(payload, data):
    """Główna funkcja: pełny breakdown wyceny albo lista błędów. Nic nie zapisuje."""
    errors = []
    multiplier, m_err = resolve_multiplier(
        payload.get('client_type'), payload.get('multiplier'), data)
    if m_err:
        return {'ok': False, 'errors': [m_err], 'products': [], 'totals': None}

    products_out = []
    sums = {'order_netto': 0.0, 'order_brutto': 0.0,
            'finishing_netto': 0.0, 'finishing_brutto': 0.0,
            'edges_netto': 0.0, 'edges_brutto': 0.0}

    for product in payload.get('products', []):
        idx = product.get('index')
        p_errors = validate_product(product, data)
        if p_errors:
            errors.extend(p_errors)
            products_out.append({'index': idx, 'errors': p_errors,
                                 'variants': [], 'finishing': None, 'edges': None})
            continue

        variants = calculate_material_variants(product, multiplier, data)
        finishing = calculate_finishing(product, data)
        edges = calculate_edges_pricing(product.get('edges'), product, data)

        selected_code = product.get('selected_variant')
        selected = next((v for v in variants
                         if v['variant_code'] == selected_code and v.get('available')), None)
        if selected_code and not selected:
            available = [v['variant_code'] for v in variants if v.get('available')]
            e = _err('selected_variant', 'VARIANT_UNAVAILABLE',
                     f'Wariant "{selected_code}" jest niedostępny dla tych wymiarów. '
                     f'Dostępne warianty: {", ".join(available) or "żadne"}.', idx)
            errors.append(e)
            products_out.append({'index': idx, 'errors': [e], 'variants': variants,
                                 'finishing': finishing, 'edges': edges})
            continue

        if selected:
            sums['order_netto'] += selected['total_netto']
            sums['order_brutto'] += selected['total_brutto']
        sums['finishing_netto'] += finishing['netto']
        sums['finishing_brutto'] += finishing['brutto']
        sums['edges_netto'] += edges['netto']
        sums['edges_brutto'] += edges['brutto']

        products_out.append({'index': idx, 'errors': [], 'variants': variants,
                             'finishing': finishing, 'edges': edges})

    shipping = payload.get('shipping') or {}
    ship_netto = float(shipping.get('netto') or 0)
    ship_brutto = float(shipping.get('brutto') or 0)

    totals = None
    if not errors:
        # Jak JS updateGlobalSummary: total = order + finishing + edges + shipping
        totals = {**{k: round_grosze(v) for k, v in sums.items()},
                  'shipping_netto': ship_netto, 'shipping_brutto': ship_brutto,
                  'total_netto': round_grosze(sums['order_netto'] + sums['finishing_netto']
                                              + sums['edges_netto'] + ship_netto),
                  'total_brutto': round_grosze(sums['order_brutto'] + sums['finishing_brutto']
                                               + sums['edges_brutto'] + ship_brutto)}

    return {'ok': not errors, 'errors': errors, 'products': products_out,
            'totals': totals, 'multiplier': multiplier}
