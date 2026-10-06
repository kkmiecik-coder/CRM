"""Logika linii czasu produkcji dla bloku 'Zamówienie' w modalu wyceny.

Czyste funkcje (bez dostępu do bazy) — operują na obiektach produktopodobnych.
Trasa produktu odzwierciedla przepływ z ProductionProduct.complete_task
(modules/production/models.py). To DRUGA, ręcznie synchronizowana kopia tej
reguły — zgodności obu pilnuje tests/test_krawedzie_parytet_reguly.py.
"""

# Kropki linii czasu w kolejności. 'entry' łączy wycinanie i składanie.
TIMELINE_STATIONS = [
    {'key': 'entry',      'name': 'Wycinanie / Składanie'},
    {'key': 'gluing',     'name': 'Sklejanie'},
    {'key': 'formatting', 'name': 'Formatowanie'},
    {'key': 'edges',      'name': 'Krawędzie'},
    {'key': 'painting',   'name': 'Lakiernia'},
    {'key': 'packaging',  'name': 'Pakowanie'},
]

# Indeks etapu każdej kropki w przepływie (wyprowadzony z TIMELINE_STATIONS).
STATION_STAGE = {st['key']: i for i, st in enumerate(TIMELINE_STATIONS)}

# Statusy oznaczające "produkt stoi na tej kropce".
STATION_AT_STATUSES = {
    'entry': {'czeka_na_wyciecie', 'czeka_na_skladanie'},
    'gluing': {'czeka_na_sklejanie'},
    'formatting': {'czeka_na_formatowanie'},
    'edges': {'czeka_na_krawedzie'},
    'painting': {'czeka_na_lakiernie'},
    'packaging': {'czeka_na_pakowanie'},
}

# Porządek statusów do porównań before/at/after.
STATUS_ORDINAL = {
    'czeka_na_wyciecie': 0, 'czeka_na_skladanie': 0,
    'czeka_na_sklejanie': 1,
    'czeka_na_formatowanie': 2,
    'czeka_na_krawedzie': 3,
    'czeka_na_lakiernie': 4,
    'czeka_na_logistyke': 4.5,
    'czeka_na_pakowanie': 5,
    'spakowane': 6,
}

_STATUS_DISPLAY = {
    'czeka_na_wyciecie': 'Czeka na wycięcie',
    'czeka_na_skladanie': 'Czeka na składanie',
    'czeka_na_sklejanie': 'Czeka na sklejanie',
    'czeka_na_formatowanie': 'Czeka na formatowanie',
    'czeka_na_krawedzie': 'Czeka na krawędzie',
    'czeka_na_lakiernie': 'Czeka na lakiernię',
    'czeka_na_logistyke': 'Czeka na logistykę',
    'czeka_na_pakowanie': 'Czeka na pakowanie',
    'spakowane': 'Spakowane',
    'anulowane': 'Anulowane',
    'wstrzymane': 'Wstrzymane',
    'w_realizacji': 'W realizacji',
}

_STATUS_BADGE = {
    'czeka_na_wyciecie': 'badge-cutting',
    'czeka_na_skladanie': 'badge-assembly',
    'czeka_na_sklejanie': 'badge-gluing',
    'czeka_na_formatowanie': 'badge-formatting',
    # Nazwa klasy CSS jest HISTORYCZNA i zostaje celowo nietknięta: stanowisko
    # nazywa się dziś Krawędzie, ale selektor dalej brzmi 'badge-finishing'.
    # Definicje żyją w modules/quotes/static/css/quotes.css:7316 oraz
    # modules/production/static/css/products-tab.css:578-579 i 2238 (razem ze
    # zmienną --il-finishing). Przemianowanie nie daje użytkownikowi nic,
    # a rozsypuje trzy pliki JS (products-module.js, archive-module.js),
    # więc świadomie go nie robimy.
    'czeka_na_krawedzie': 'badge-finishing',
    'czeka_na_lakiernie': 'badge-painting',
    'czeka_na_logistyke': 'badge-logistics',
    'czeka_na_pakowanie': 'badge-packaging',
    'spakowane': 'badge-completed',
    'wstrzymane': 'badge-paused',
    'anulowane': 'badge-cancelled',
    'w_realizacji': 'badge-assembly',
}


# Sync z ProductionProduct.should_skip_edges w modules/production/models.py.
# Druga, RĘCZNIE synchronizowana kopia reguły — parytetu pilnuje
# tests/test_krawedzie_parytet_reguly.py.
def _should_skip_edges(product):
    """Bez obróbki krawędzi nie ma czego robić na Krawędziach — niezależnie
    od wykończenia."""
    return not product.parsed_edge_processing


def product_in_route(product, station_key):
    """Czy produkt przechodzi przez dane stanowisko."""
    if station_key in ('entry', 'gluing', 'packaging'):
        return True
    if station_key == 'formatting':
        return product.cut_to_size is True
    if station_key == 'edges':
        return product.cut_to_size is True and not _should_skip_edges(product)
    if station_key == 'painting':
        return (product.cut_to_size is True
                and product.parsed_finish_type in ('olejowane', 'lakierowane'))
    return False


def _product_state(product, station_key):
    """'before' | 'at' | 'left' względem kropki."""
    status = product.current_status
    if status in STATION_AT_STATUSES[station_key]:
        return 'at'
    ordinal = STATUS_ORDINAL.get(status)
    if ordinal is None:
        # wstrzymane / w_realizacji / nieznane — bezpiecznie nie zaznaczaj postępu
        return 'before'
    return 'left' if ordinal > STATION_STAGE[station_key] else 'before'


def station_color(station_key, routed_products):
    """Kolor kropki dla produktów, których trasa zawiera to stanowisko.

    Zwraca 'green' | 'yellow' | 'gray', albo None gdy kropkę należy ukryć
    (żaden produkt jej nie przechodzi).
    """
    if not routed_products:
        return None
    states = [_product_state(p, station_key) for p in routed_products]
    if all(s == 'left' for s in states):
        return 'green'
    if all(s == 'before' for s in states):
        return 'gray'
    return 'yellow'


def format_dimension(value):
    """Liczba -> string z polskim przecinkiem, bez zbędnych zer. None -> '-'."""
    if value is None:
        return '-'
    f = float(value)
    if f == int(f):
        return str(int(f))
    return ('%g' % f).replace('.', ',')


def _format_product(product):
    cfg = getattr(product, 'configuration', None)
    return {
        'short_product_id': product.short_product_id,
        'length_cm': format_dimension(product.parsed_length_cm),
        'width_cm': format_dimension(product.parsed_width_cm),
        'thickness_cm': format_dimension(product.parsed_thickness_cm),
        'species': getattr(cfg, 'species', None) if cfg else None,
        'technology': getattr(cfg, 'technology', None) if cfg else None,
        'wood_class': getattr(cfg, 'wood_class', None) if cfg else None,
    }


def build_timeline_payload(products):
    """Lista kropek do renderowania. Pomija stanowiska bez produktów w trasie
    i produkty anulowane."""
    active = [p for p in products if p.current_status != 'anulowane']
    out = []
    for st in TIMELINE_STATIONS:
        key = st['key']
        routed = [p for p in active if product_in_route(p, key)]
        color = station_color(key, routed)
        if color is None:
            continue
        here = [p for p in routed if p.current_status in STATION_AT_STATUSES[key]]
        out.append({
            'code': key,
            'name': st['name'],
            'color': color,
            'active': bool(here),
            'products_here': [_format_product(p) for p in here],
        })
    return out


def order_status_badge(products):
    """Status całego zamówienia (jak panel admina). Liczy wszystkie produkty."""
    # UWAGA: świadomie liczy WSZYSTKIE produkty (także anulowane), aby odwzorować panel administracyjny produkcji. Timeline (build_timeline_payload) anulowane wyklucza — asymetria zamierzona.
    if not products:
        return {'label': '-', 'badge_class': 'badge-completed'}
    statuses = {p.current_status for p in products}
    if len(statuses) == 1:
        status = next(iter(statuses))
        return {
            'label': _STATUS_DISPLAY.get(status, status),
            'badge_class': _STATUS_BADGE.get(status, 'badge-completed'),
        }
    completed = sum(1 for p in products if p.current_status == 'spakowane')
    return {'label': f'Różne ({completed}/{len(products)})', 'badge_class': 'badge-mixed'}
