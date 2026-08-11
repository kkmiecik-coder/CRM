"""
Scalanie historii produktu z dwóch źródeł: prod_product_events (zmiany
statusu, priorytetu, doróbki) i prod_station_events (praca stanowisk).

Praca stanowisk jest zwijana do jednego wpisu na stanowisko — inaczej
produkt na 150 sztuk dałby 150 wierszy w akordeonie. Cofnięcia sztuk
(delta < 0) wypadają z agregacji i stają się osobnymi wpisami, bo są
sygnałem problemu i nie mogą się uśrednić w sumie.
"""


def aggregate_station_events(events):
    """
    Czysta funkcja: zamienia listę zdarzeń stanowiskowych na wpisy osi czasu.

    Zwraca listę słowników — grupy pracy ('kind': 'work') i pojedyncze
    cofnięcia ('kind': 'reject'). Bez sortowania; kolejność ustala merge_history.
    """
    groups = {}
    rejects = []

    for e in events:
        if e.delta < 0:
            rejects.append({
                'kind': 'reject',
                'station_code': e.station_code,
                'delta': e.delta,
                'quantity_done_after': e.quantity_done_after,
                'at': e.created_at,
                'device_id': e.device_id,
                'user_id': e.user_id,
                'source': getattr(e, 'source', None),
            })
            continue

        g = groups.get(e.station_code)
        if g is None:
            g = {
                'kind': 'work',
                'station_code': e.station_code,
                'total': 0,
                'event_count': 0,
                'first_at': e.created_at,
                'last_at': e.created_at,
                'device_ids': [],
                'user_ids': [],
                # last_device_id/last_user_id/last_source — aktor (i jego
                # źródło) zdarzenia o najpóźniejszym created_at. Inicjalizujemy
                # już tutaj (nie dopiero przy update last_at), bo pierwsze
                # zdarzenie w grupie na starcie JEST tym najpóźniejszym
                # widzianym dotąd.
                'last_device_id': e.device_id,
                'last_user_id': e.user_id,
                'last_source': getattr(e, 'source', None),
                'entries': [],
            }
            groups[e.station_code] = g

        g['total'] += e.delta
        g['event_count'] += 1
        if e.created_at < g['first_at']:
            g['first_at'] = e.created_at
        if e.created_at > g['last_at']:
            g['last_at'] = e.created_at
            # flow potrzebuje autora OSTATNIEGO zdarzenia (domknięcie stanowiska),
            # nie pierwszego — inaczej przy dwóch osobach/tabletach na stanowisku
            # modal wskaże niewłaściwego autora. Aktualizujemy w tym samym miejscu
            # co last_at, żeby zdarzenia napływające nie po kolei (created_at)
            # nie rozjechały last_at z last_device_id/last_user_id/last_source.
            # source jest tu kluczowy dla automatycznego pomijania stanowisk
            # (source='auto_skip') — bez niego SYSTEM_REASONS nie ma jak
            # dobrać czytelnego tekstu "System (pominięto automatycznie)".
            g['last_device_id'] = e.device_id
            g['last_user_id'] = e.user_id
            g['last_source'] = getattr(e, 'source', None)
        if e.device_id and e.device_id not in g['device_ids']:
            g['device_ids'].append(e.device_id)
        if e.user_id and e.user_id not in g['user_ids']:
            g['user_ids'].append(e.user_id)
        g['entries'].append({
            'at': e.created_at,
            'delta': e.delta,
            'quantity_done_after': e.quantity_done_after,
            'device_id': e.device_id,
            'user_id': e.user_id,
        })

    for g in groups.values():
        # Znacznik sortowania osi czasu — grupa "dzieje się" w momencie ostatniego odbicia
        g['at'] = g['last_at']

    return list(groups.values()) + rejects


# Nazwy stanowisk — spójne z routers/stations/__init__.py:624 i monitors.py:184
STATION_NAMES = {
    'cutting': 'Wycinanie - mikro',
    'assembly': 'Składanie - lite',
    'gluing': 'Sklejanie',
    'formatting': 'Formatowanie',
    'finishing': 'Wykańczanie',
    'painting': 'Lakiernia',
    'packaging': 'Pakowanie',
}

# Powody działania automatu — czytelne dla człowieka
SYSTEM_REASONS = {
    'auto_skip': 'System (pominięto automatycznie)',
    'sync': 'System (synchronizacja BaseLinker)',
    'system': 'System',
    # Panel stanowiskowy jest chroniony walidacją IP, a nie logowaniem —
    # nie ma tu ani urządzenia, ani zalogowanego użytkownika, ale JEST
    # kontekst żądania HTTP. To odróżnia człowieka przy stanowisku od
    # automatu (source='system'), który pomija stanowiska bez żądania.
    'web': 'Panel stanowiskowy (bez logowania)',
}


def actor_label(actor_type, user_name=None, device_name=None,
                station_code=None, source=None):
    """Czysta funkcja: etykieta aktora do wyświetlenia w modalu."""
    if actor_type == 'user':
        return f'{user_name} (panel)' if user_name else 'Panel web'

    if actor_type == 'device':
        if device_name:
            return device_name
        if station_code:
            return STATION_NAMES.get(station_code, station_code)
        return 'Tablet'

    return SYSTEM_REASONS.get(source, 'System')


def is_manual_status_change(entry):
    """
    Zmiana statusu wykonana przez człowieka z panelu — sygnatura obejścia
    normalnego przepływu. To ona dostaje w modalu znacznik „ręcznie".

    Plakietka dotyczy WYŁĄCZNIE zmian statusu (event_type == 'status_change'),
    nie priorytetu ani innych zdarzeń o kind='status' — inaczej pojedyncza,
    ręczna zmiana priorytetu (która przetrwa filtr masowej renumeracji w
    product_events.py) dostałaby mylącą plakietkę „ręcznie", tak jakby to
    była zmiana statusu.
    """
    return (entry.get('kind') == 'status'
            and entry.get('event_type') == 'status_change'
            and entry.get('actor_type') == 'user'
            and entry.get('source') in ('web', 'admin'))


def merge_history(status_events, station_entries):
    """Scala oba źródła w jedną oś czasu, od najnowszego."""
    merged = list(status_events) + list(station_entries)
    merged.sort(key=lambda e: e['at'], reverse=True)
    return merged


def _name_maps(user_ids, device_ids):
    """Mapy id→nazwa dla użytkowników i urządzeń (dwa zapytania, nie N)."""
    from modules.production.models import ProductionDevice
    from modules.users.models import User

    users = {}
    if user_ids:
        for u in User.query.filter(User.id.in_(list(user_ids))).all():
            users[u.id] = u.get_full_name()

    devices = {}
    if device_ids:
        rows = ProductionDevice.query.filter(
            ProductionDevice.device_id.in_(list(device_ids))
        ).all()
        for d in rows:
            devices[d.device_id] = d.device_name or STATION_NAMES.get(
                d.station_code, d.station_code)

    return users, devices


def build_product_history(product_id):
    """
    Pełna historia produktu: mapa autorów domknięcia stanowisk (flow)
    oraz scalona oś czasu (history). Jedno wywołanie obsługuje obie
    sekcje modalu, dzięki czemu zawsze pokazują spójne dane.
    """
    from modules.production.models import (
        ProductionProductEvent, ProductionStationEvent,
    )

    status_rows = ProductionProductEvent.query.filter(
        ProductionProductEvent.production_item_id == product_id
    ).order_by(ProductionProductEvent.created_at).all()

    station_rows = ProductionStationEvent.query.filter(
        ProductionStationEvent.production_item_id == product_id
    ).order_by(ProductionStationEvent.created_at).all()

    user_ids = {r.user_id for r in status_rows if r.user_id}
    user_ids |= {r.user_id for r in station_rows if r.user_id}
    device_ids = {r.device_id for r in status_rows if r.device_id}
    device_ids |= {r.device_id for r in station_rows if r.device_id}
    users, devices = _name_maps(user_ids, device_ids)

    def _label(actor_type, user_id, device_id, station_code, source):
        return actor_label(
            actor_type,
            user_name=users.get(user_id),
            device_name=devices.get(device_id),
            station_code=station_code,
            source=source,
        )

    status_entries = []
    for r in status_rows:
        entry = {
            'kind': 'status',
            'at': r.created_at,
            'event_type': r.event_type,
            'old_value': r.old_value,
            'new_value': r.new_value,
            'actor_type': r.actor_type,
            'source': r.source,
            'endpoint': r.endpoint,
            'note': r.note,
            'actor_label': _label(r.actor_type, r.user_id, r.device_id, None, r.source),
        }
        entry['manual'] = is_manual_status_change(entry)
        status_entries.append(entry)

    station_entries = aggregate_station_events(station_rows)
    for entry in station_entries:
        if entry['kind'] == 'work':
            # Autor domknięcia stanowiska = aktor OSTATNIEGO zdarzenia (last_at),
            # nie pierwszego z listy — device_ids/user_ids to tylko zbiór
            # wszystkich, kto dotknął stanowiska, bez info o kolejności.
            device_id = entry['last_device_id']
            user_id = entry['last_user_id']
            source = entry['last_source']
        else:
            device_id, user_id = entry.get('device_id'), entry.get('user_id')
            source = entry.get('source')
        actor_type = 'device' if device_id else ('user' if user_id else 'system')
        # source jest kluczowy dla odbić auto_skip/system: to jedyny sygnał,
        # że produkt przeskoczył stanowisko automatycznie, a nie zrobił tego
        # człowiek — bez niego actor_label zawsze zwracał neutralne "System".
        entry['actor_label'] = _label(
            actor_type, user_id, device_id, entry['station_code'], source)
        # Czytelna nazwa stanowiska — front nie dorabia własnego słownika
        entry['station_name'] = STATION_NAMES.get(
            entry['station_code'], entry['station_code'])
        entry['manual'] = False

    # Kto fizycznie pracował przy tym produkcie — z atrybucji profili
    # (docs/worker-profiles-backend.md §7.3). Odrębne od actor_label, który
    # mówi o URZĄDZENIU albo koncie CRM: tablet w sklejalni to jedno, a Adam
    # i Bartek, którzy przy nim stali, to co innego. Puste dla produktów
    # sprzed wdrożenia profili i dla pracy bez wybranego profilu.
    from .worker_stats_service import get_workers_for_products
    pracownicy_stanowisk = get_workers_for_products([product_id]).get(product_id, {})

    for entry in station_entries:
        if entry['kind'] == 'work':
            entry['workers'] = pracownicy_stanowisk.get(entry['station_code'], [])

    # flow — ostatnie zdarzenie pracy na każdym stanowisku wskazuje autora domknięcia
    flow = {}
    for entry in station_entries:
        if entry['kind'] != 'work':
            continue
        flow[entry['station_code']] = {
            'completed_at': entry['last_at'].isoformat(),
            'actor_label': entry['actor_label'],
            'workers': entry.get('workers', []),
        }

    history = merge_history(status_entries, station_entries)
    for entry in history:
        entry['at'] = entry['at'].isoformat()
        for key in ('first_at', 'last_at'):
            if entry.get(key):
                entry[key] = entry[key].isoformat()
        for sub in entry.get('entries', []):
            sub['at'] = sub['at'].isoformat()

    return {'flow': flow, 'history': history}
