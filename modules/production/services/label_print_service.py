"""
Serwis drukowania etykiet produkcyjnych (Xprinter XP-423B, ZPL).

Konfiguracja w prod_config (7 kluczy LABEL_PRINTER_*), edytowalna w
panelu admin ?tab=config. Wydruk = raw TCP socket do drukarki w LAN.

Wzorzec użycia:
    result = print_labels_batch(['25_04250_3'], 'formatting',
                                {'type': 'user', 'id': 1})
"""
from __future__ import annotations

import socket
from datetime import datetime

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob, ProductionConfig, ProductionItem, ProductionOrder

logger = get_structured_logger('production.label_print')

DEFAULT_CONFIG = {
    'ip': '192.168.100.199',
    'port': 9100,
    'timeout_seconds': 3,
    'retry_count': 1,
    'offset_lt': -16,
    'offset_ls': 112,
    'allowed_stations': ['formatting', 'packaging'],
    'use_agent': False,
    'agent_token': '',
}

_PL_TO_ASCII = str.maketrans({
    'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
    'ó': 'o', 'ś': 's', 'ż': 'z', 'ź': 'z',
    'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
    'Ó': 'O', 'Ś': 'S', 'Ż': 'Z', 'Ź': 'Z',
})


class StationNotAllowed(Exception):
    """Stacja spoza LABEL_PRINTER_ALLOWED_STATIONS."""


def _normalize_text(s):
    """ASCII-safe — drukarka ZPL nie obsługuje polskich diakrytyków."""
    if not s:
        return ''
    return str(s).translate(_PL_TO_ASCII)


def _format_edge_label(item):
    """Łączy parsed_edge_type + radius + angle w czytelny string ('FAZA R5 45')."""
    if not item.parsed_edge_processing or not item.parsed_edge_type:
        return ''
    parts = [str(item.parsed_edge_type).upper()]
    if item.parsed_edge_radius:
        parts.append(f'R{item.parsed_edge_radius}')
    if item.parsed_edge_angle:
        parts.append(str(item.parsed_edge_angle))
    return _normalize_text(' '.join(parts))


def _coerce_int(raw, default):
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return default


def _load_config():
    """Czyta 7 kluczy LABEL_PRINTER_* z prod_config + fallback do DEFAULT_CONFIG."""
    keys = [
        'LABEL_PRINTER_IP',
        'LABEL_PRINTER_PORT',
        'LABEL_PRINTER_TIMEOUT_SECONDS',
        'LABEL_PRINTER_RETRY_COUNT',
        'LABEL_PRINTER_OFFSET_LT',
        'LABEL_PRINTER_OFFSET_LS',
        'LABEL_PRINTER_ALLOWED_STATIONS',
        'LABEL_PRINTER_USE_AGENT',
        'LABEL_PRINTER_AGENT_TOKEN',
    ]
    rows = {
        c.config_key: c.config_value
        for c in ProductionConfig.query.filter(ProductionConfig.config_key.in_(keys)).all()
    }

    allowed_raw = rows.get('LABEL_PRINTER_ALLOWED_STATIONS', ','.join(DEFAULT_CONFIG['allowed_stations']))
    allowed = [s.strip() for s in str(allowed_raw).split(',') if s.strip()] or list(DEFAULT_CONFIG['allowed_stations'])

    ip_value = (rows.get('LABEL_PRINTER_IP') or DEFAULT_CONFIG['ip']).strip() or DEFAULT_CONFIG['ip']

    use_agent_raw = (rows.get('LABEL_PRINTER_USE_AGENT', 'false') or 'false').strip().lower()

    return {
        'ip': ip_value,
        'port': _coerce_int(rows.get('LABEL_PRINTER_PORT', DEFAULT_CONFIG['port']), DEFAULT_CONFIG['port']),
        'timeout_seconds': _coerce_int(rows.get('LABEL_PRINTER_TIMEOUT_SECONDS', DEFAULT_CONFIG['timeout_seconds']), DEFAULT_CONFIG['timeout_seconds']),
        'retry_count': _coerce_int(rows.get('LABEL_PRINTER_RETRY_COUNT', DEFAULT_CONFIG['retry_count']), DEFAULT_CONFIG['retry_count']),
        'offset_lt': _coerce_int(rows.get('LABEL_PRINTER_OFFSET_LT', DEFAULT_CONFIG['offset_lt']), DEFAULT_CONFIG['offset_lt']),
        'offset_ls': _coerce_int(rows.get('LABEL_PRINTER_OFFSET_LS', DEFAULT_CONFIG['offset_ls']), DEFAULT_CONFIG['offset_ls']),
        'allowed_stations': allowed,
        'use_agent': use_agent_raw in ('1', 'true', 'yes', 'on'),
        'agent_token': (rows.get('LABEL_PRINTER_AGENT_TOKEN') or '').strip(),
    }


def _compute_unit_offsets(items_by_id):
    """Dla każdego short_product_id w batchu zwraca (offset, total_units) w obrębie
    zamówienia BaseLinker.

    offset = liczba sztuk wszystkich pozycji o niższym product_sequence_in_order
    total_units = suma sztuk WSZYSTKICH pozycji w zamówieniu (nie tylko z batcha).

    Numeracja etykiet: dla pozycji A (qty 5, seq 1) i B (qty 3, seq 2) w 1 zamówieniu:
      A → offsets 0..4 → labels 1/8..5/8
      B → offsets 5..7 → labels 6/8..8/8

    Zwraca: dict {short_product_id: (offset, total_units)}.
    Pozycje bez baselinker_order_id dostają (0, copies(item)) — same dla siebie.
    """
    info = {}
    order_ids = {
        item.baselinker_order_id
        for item in items_by_id.values()
        if item is not None and item.baselinker_order_id
    }

    siblings_by_order = {}
    if order_ids:
        all_siblings = (
            ProductionItem.query
            .join(ProductionOrder)
            .filter(ProductionOrder.baselinker_order_id.in_(order_ids))
            .all()
        )
        for sib in all_siblings:
            siblings_by_order.setdefault(sib.baselinker_order_id, []).append(sib)

    for order_id, siblings in siblings_by_order.items():
        # Sortowanie: najpierw po product_sequence_in_order (None na koniec), potem po id.
        siblings.sort(key=lambda s: (
            s.product_sequence_in_order if s.product_sequence_in_order is not None else 10**9,
            s.id or 0,
        ))
        cumulative = 0
        total = sum(_resolve_copies(s) for s in siblings)
        for s in siblings:
            info[s.short_product_id] = (cumulative, total)
            cumulative += _resolve_copies(s)

    # Items bez baselinker_order_id — numeracja lokalna (sama dla siebie).
    for sid, item in items_by_id.items():
        if item is None or sid in info:
            continue
        info[sid] = (0, _resolve_copies(item))

    return info


def _resolve_copies(item):
    """Liczba kopii etykiety = item.quantity (fallback 1).

    Drukujemy po jednej etykiecie na każdą sztukę pozycji, bo każda sztuka
    jest pakowana/oznaczana osobno. Dla quantity ≤ 0 lub None drukujemy 1.
    """
    try:
        n = int(getattr(item, 'quantity', 1) or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, n)


def _resolve_client_label(item):
    """Fallback chain dla pola 'klient' na etykiecie."""
    candidates = [
        getattr(item, 'client_name', None),
        getattr(item, 'delivery_fullname', None),
        getattr(item, 'delivery_company', None),
        getattr(item, 'client_order_number', None),
        getattr(item, 'internal_order_number', None),
    ]
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return _normalize_text(str(candidate).strip())
    return 'Brak danych'


def _format_delivery_label(item):
    """Zwraca pełną treść sposobu dostawy.

    Kolejność warunków 1:1 z mobile_api_service / web-templatką:
      - override transport_woodpower → 'Transport WoodPower'
      - override kurier_baselinker  → nazwa kuriera z delivery_method (lub 'Kurier')
      - is_personal_pickup           → 'Odbior osobisty'
      - default                      → delivery_method z BL (np. 'InPost Paczkomaty 24/7')
                                       lub 'Kurier' gdy brak danych
    """
    override = (getattr(item, 'override_delivery_method', None) or '').strip().lower()
    delivery_method = (getattr(item, 'delivery_method', None) or '').strip()

    if override == 'transport_woodpower':
        return _normalize_text('Transport WoodPower')
    if override == 'kurier_baselinker':
        return _normalize_text(delivery_method) if delivery_method else 'Kurier'
    try:
        if getattr(item, 'is_personal_pickup', False):
            return _normalize_text('Odbior osobisty')
    except Exception:
        pass
    return _normalize_text(delivery_method) if delivery_method else 'Kurier'


def _format_finish_label(item):
    """Rozszerzony opis wykończenia: 'LAK MAT BRUNAT 22-23' / 'OLEJ' / 'LAK MAT' itp.

    Skróty:
      lakierowane → LAK, olejowane → OLEJ
      matowy → MAT, półmatowy → PMAT
    Zwraca '' dla 'surowe' lub braku danych."""
    finish_raw = (item.parsed_finish_type or '').strip().lower()
    if not finish_raw or finish_raw == 'surowe':
        return ''
    parts = []
    if finish_raw == 'lakierowane':
        parts.append('LAK')
    elif finish_raw == 'olejowane':
        parts.append('OLEJ')
    else:
        parts.append(_normalize_text(finish_raw).upper())

    gloss = (item.parsed_finish_gloss or '').strip().lower()
    if gloss == 'matowy':
        parts.append('MAT')
    elif gloss in ('półmatowy', 'polmatowy'):
        parts.append('PMAT')
    elif gloss:
        parts.append(_normalize_text(gloss).upper())

    color = (item.parsed_finish_color or '').strip()
    if color:
        parts.append(_normalize_text(color).upper())

    return ' '.join(parts)


# Layout (px @ 8 dpmm, etykieta 60×40 mm = 480×320 px)
#
# Konwencja: w ZPL preambule ^LS0 (drukarka nie modyfikuje globalnie pozycji).
# `cfg['offset_ls']` traktujemy jako kalibracyjny shift POZIOMY całej treści —
# dodawany do każdego ^FO_x. User reguluje w panelu admin (?tab=config) — większa
# wartość = treść bardziej w prawo, mniejsza = w lewo.
_LABEL_WIDTH = 480
_LABEL_HEIGHT = 320
_VISUAL_MARGIN_LEFT = 4     # bazowy padding od lewej (przed shiftem z cfg) — 0.5 mm
_VISUAL_MARGIN_RIGHT = 25
_QR_VISUAL_X = 388          # pozycja QR od lewej krawędzi
_QR_VISUAL_Y = 55
_QR_VISUAL_GAP = 12         # odstęp separatora od QR
_BADGE_HEIGHT = 34
_BADGE_GAP = 12             # odstęp między badge'ami
_BADGE_FONT_SIZE = 18
_BADGE_CHAR_PX = 14         # realistyczna szerokość znaku w foncie 18
_BADGE_PADDING_X = 20       # padding wewnętrzny — tekst odsunięty od lewej krawędzi badge'a


def _badge_zpl(x, y, text, filled=True):
    """Pojedynczy badge: tło (wypełnione lub ramka) + tekst wyśrodkowany w pionie.
    Zwraca (zpl_string, width_px) — szerokość liczona z długości tekstu.
    """
    text_px = max(1, len(text)) * _BADGE_CHAR_PX
    width = text_px + 2 * _BADGE_PADDING_X
    if filled:
        bg = f"^FO{x},{y}^GB{width},{_BADGE_HEIGHT},{_BADGE_HEIGHT},B,3^FS"
        txt = f"^FO{x + _BADGE_PADDING_X},{y + 7}^A0N,{_BADGE_FONT_SIZE},{_BADGE_FONT_SIZE}^FR^FD{text}^FS"
    else:
        bg = f"^FO{x},{y}^GB{width},{_BADGE_HEIGHT},3,B,3^FS"
        txt = f"^FO{x + _BADGE_PADDING_X},{y + 7}^A0N,{_BADGE_FONT_SIZE},{_BADGE_FONT_SIZE}^FD{text}^FS"
    return f"{bg}\n{txt}", width


def _layout_badges_row(badges, y, x_start, x_max):
    """Układa badge'y horyzontalnie od x_start, z gap.
    Pomija pojedyncze badge które nie zmieszczą się do x_max.
    Wszystkie x w przestrzeni ZPL (po dodaniu ^LS).
    """
    parts = []
    x = x_start
    for text, filled in badges:
        zpl, width = _badge_zpl(x, y, text, filled=filled)
        if x + width > x_max:
            continue
        parts.append(zpl)
        x += width + _BADGE_GAP
    return "\n".join(parts)


def generate_label_zpl(item, cfg, label_index=None, total_units=None):
    """
    Generuje ZPL dla etykiety 60×40 mm.

    Args:
        item: ProductionItem
        cfg: dict z _load_config()
        label_index: numer tej etykiety w zamówieniu (1-based, liczony per sztuka,
                     nie per pozycja). Jeśli podany razem z total_units, w nagłówku
                     pojawi się "{label_index}/{total_units}" (np. "3/10" — trzecia
                     sztuka z 10 wszystkich sztuk w zamówieniu).
        total_units: suma sztuk wszystkich pozycji w zamówieniu (SUM(quantity)).

    Layout (od góry):
      - czarny pasek nagłówkowy "WoodPower" — pełna szerokość
      - numery: "{short_id} | {n}/{total} | BL: {bl_id}" — jedna linia
      - klient (fallback chain) — jedna linia
      - QR — pod prawą krawędzią
      - separator
      - nazwa produktu — jedna linia (skrócona)
      - badges row 1 (gatunek/technologia/klasa) — wypełnione, dynamiczna szerokość
      - badges row 2 (wykończenie/krawędź) — z ramką, pomijane gdy puste
    """
    species = _normalize_text(item.parsed_wood_species or '').upper() or 'BRAK'
    technology = _normalize_text(item.parsed_technology or '').upper() or 'BRAK'
    wood_class = _normalize_text(item.parsed_wood_class or '').upper() or '-'
    finish_label = _format_finish_label(item)
    edge_label = _format_edge_label(item)
    name = _normalize_text(item.original_product_name or '')[:80]
    short_id = _normalize_text(item.short_product_id or '')
    bl_id = item.baselinker_order_id or 0
    client_label = _resolve_client_label(item)
    delivery_label = _format_delivery_label(item)

    # Numeracja sztuki w zamówieniu: "3/10" = 3-cia sztuka z 10 wszystkich w zamówieniu.
    # Jeśli wywołujący nie poda label_index/total_units (np. legacy code path),
    # pomijamy element bez fallbacku — bezpieczniej niż mylące "pozycja/liczba pozycji".
    seq_label = ''
    if label_index and total_units and total_units > 0:
        seq_label = f"{int(label_index)}/{int(total_units)}"

    numbers_line = (
        f"{short_id} | {seq_label} | BL: {bl_id}" if seq_label
        else f"{short_id} | BL: {bl_id}"
    )

    # Badges row 1 — zawsze wszystkie 3 (mają fallback BRAK/-)
    row1 = [(species, True), (technology, True), (wood_class, True)]

    # Badges row 2 — tylko gdy są dane
    row2 = []
    if finish_label:
        row2.append((finish_label, False))
    if edge_label:
        row2.append((edge_label, False))

    shift_x = cfg['offset_ls']
    zpl_margin_l = shift_x + _VISUAL_MARGIN_LEFT
    zpl_qr_x = shift_x + _QR_VISUAL_X
    content_width = _LABEL_WIDTH - _VISUAL_MARGIN_LEFT - _VISUAL_MARGIN_RIGHT
    separator_width = _QR_VISUAL_X - _VISUAL_MARGIN_LEFT - _QR_VISUAL_GAP

    badges_x_max = shift_x + _LABEL_WIDTH - _VISUAL_MARGIN_RIGHT
    badges_row1_zpl = _layout_badges_row(row1, y=212, x_start=zpl_margin_l, x_max=badges_x_max)
    badges_row2_zpl = _layout_badges_row(row2, y=256, x_start=zpl_margin_l, x_max=badges_x_max) if row2 else ""

    # Header — czarny pasek na pełną szerokość fizyczną
    header_x = shift_x
    header_width = _LABEL_WIDTH

    return (
        "^XA\n"
        f"^PW{_LABEL_WIDTH}\n"
        f"^LL{_LABEL_HEIGHT}\n"
        f"^LT{cfg['offset_lt']}\n"
        "^LS0\n"
        "^CI28\n"
        "\n"
        # Header — czarny pasek
        f"^FO{header_x},0^GB{header_width},50,50^FS\n"
        f"^FO{shift_x + 15},10^A0N,32,32^FR^FDWoodPower^FS\n"
        "\n"
        # Numery — jedna linia, font 26
        f"^FO{zpl_margin_l},62^A0N,26,26^FD{numbers_line}^FS\n"
        # Klient — pod numerami, font 22
        f"^FO{zpl_margin_l},96^A0N,22,22^FB{separator_width},1,0,L^FD{client_label}^FS\n"
        # Dostawa — pod klientem, font 18 (^FB ogranicza do 1 linii w obszarze przed QR)
        f"^FO{zpl_margin_l},124^A0N,18,18^FB{separator_width},1,0,L^FDDostawa: {delivery_label}^FS\n"
        "\n"
        # QR — pod prawą krawędzią
        f"^FO{zpl_qr_x},{_QR_VISUAL_Y}^BQN,2,4^FDLA,{short_id}^FS\n"
        "\n"
        # Separator — kończy się przed QR
        f"^FO{zpl_margin_l},151^GB{separator_width},2,2^FS\n"
        "\n"
        # Nazwa produktu — jedna linia, font 22
        f"^FO{zpl_margin_l},164^A0N,22,22^FB{content_width},2,0,L^FD{name}^FS\n"
        "\n"
        + badges_row1_zpl + "\n"
        + (badges_row2_zpl + "\n" if badges_row2_zpl else "")
        + "^XZ\n"
    )


def _open_printer_socket(cfg):
    """Otwiera socket TCP do drukarki z konfigurowaną liczbą prób."""
    last_err = None
    attempts = max(1, cfg['retry_count'] + 1)
    for attempt in range(attempts):
        try:
            return socket.create_connection(
                (cfg['ip'], cfg['port']),
                timeout=cfg['timeout_seconds'],
            )
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            last_err = e
            logger.warning(
                "Label printer connection attempt failed",
                extra={'attempt': attempt + 1, 'error': str(e), 'ip': cfg['ip']},
            )
    logger.error(
        "Label printer unreachable",
        extra={'error': str(last_err), 'ip': cfg['ip'], 'port': cfg['port']},
    )
    return None


def print_labels_batch(short_product_ids, station_code, actor):
    """
    Drukuje etykiety dla podanej listy short_product_id (single = lista 1-elementowa).
    Best-effort: jeden socket per request, kontynuuje przy błędach pojedynczych etykiet
    (przerywa tylko gdy socket się zerwie — błąd send oznacza utratę połączenia).

    Args:
        short_product_ids: iterable stringów
        station_code: 'formatting' / 'packaging' / ... (techniczne kody z DB/JWT)
        actor: dict {'type': 'user'|'device', 'id': ...}

    Returns dict:
        success: bool — True jeśli WSZYSTKIE etykiety wydrukowane
        success_count: int
        failed_count: int
        connection_error: bool — True gdy drukarka nieosiągalna (success_count == 0)
        message: str — human-readable
        results: list[dict] z {short_product_id, success, message, label_print_count}

    Raises:
        StationNotAllowed: gdy station_code spoza LABEL_PRINTER_ALLOWED_STATIONS
    """
    ids = [str(x).strip() for x in short_product_ids if str(x).strip()]
    cfg = _load_config()

    if station_code not in cfg['allowed_stations']:
        raise StationNotAllowed(
            f"Stanowisko '{station_code}' nie ma uprawnień do drukowania "
            f"(dozwolone: {', '.join(cfg['allowed_stations'])})"
        )

    if not ids:
        return {
            'success': False, 'success_count': 0, 'failed_count': 0,
            'connection_error': False, 'queued': False,
            'message': 'Brak produktów do wydrukowania.',
            'results': [],
        }

    items_by_id = {
        i.short_product_id: i
        for i in ProductionItem.query.filter(ProductionItem.short_product_id.in_(ids)).all()
    }

    # Tryb agenta — zamiast TCP wstaw rekordy do prod_print_queue
    if cfg['use_agent']:
        return _enqueue_labels(ids, items_by_id, station_code, actor, cfg)

    sock = _open_printer_socket(cfg)
    if sock is None:
        return {
            'success': False, 'success_count': 0, 'failed_count': len(ids),
            'connection_error': True, 'queued': False,
            'message': 'Drukarka offline — sprawdź zasilanie/kabel.',
            'results': [
                {'short_product_id': sid, 'success': False,
                 'message': 'Drukarka nieosiągalna', 'label_print_count': 0}
                for sid in ids
            ],
        }

    results = []
    success_count = 0
    socket_broken = False
    unit_offsets = _compute_unit_offsets(items_by_id)

    try:
        for sid in ids:
            item = items_by_id.get(sid)
            if item is None:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': f'Nie znaleziono produktu {sid}',
                    'label_print_count': 0,
                    'copies_requested': 0,
                    'copies_printed': 0,
                })
                continue
            if socket_broken:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': 'Pominięto — utracono połączenie z drukarką',
                    'label_print_count': item.label_print_count or 0,
                    'copies_requested': _resolve_copies(item),
                    'copies_printed': 0,
                })
                continue

            copies = _resolve_copies(item)
            offset, total_units = unit_offsets.get(sid, (0, copies))
            copies_printed = 0
            for i in range(copies):
                label_index = offset + i + 1
                zpl_bytes = generate_label_zpl(
                    item, cfg,
                    label_index=label_index,
                    total_units=total_units,
                ).encode('utf-8')
                try:
                    sock.sendall(zpl_bytes)
                    copies_printed += 1
                except (OSError, socket.timeout) as e:
                    logger.error(
                        "Label send failed mid-batch",
                        extra={'short_product_id': sid, 'error': str(e),
                               'copies_done': copies_printed, 'copies_total': copies},
                    )
                    socket_broken = True
                    break

            if copies_printed > 0:
                item.label_printed_at = datetime.utcnow()
                item.label_print_count = (item.label_print_count or 0) + copies_printed

            if copies_printed == copies:
                results.append({
                    'short_product_id': sid, 'success': True,
                    'message': f'Wysłano do drukarki ({copies_printed} szt.)',
                    'label_print_count': item.label_print_count,
                    'copies_requested': copies,
                    'copies_printed': copies_printed,
                })
                success_count += 1
                logger.info(
                    "Label printed",
                    extra={
                        'short_product_id': sid, 'station': station_code,
                        'actor_type': actor.get('type'), 'actor_id': actor.get('id'),
                        'count': item.label_print_count,
                        'copies': copies_printed,
                    },
                )
            else:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': f'Wysyłka przerwana ({copies_printed}/{copies} szt.)',
                    'label_print_count': item.label_print_count or 0,
                    'copies_requested': copies,
                    'copies_printed': copies_printed,
                })

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        try:
            sock.close()
        except OSError:
            pass

    failed_count = len(ids) - success_count
    total_labels = sum(r.get('copies_requested', 0) for r in results)
    printed_labels = sum(r.get('copies_printed', 0) for r in results)
    return {
        'success': success_count == len(ids) and success_count > 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'total_labels': total_labels,
        'printed_labels': printed_labels,
        'connection_error': False,
        'queued': False,
        'message': (
            f'Wydrukowano {printed_labels} etykiet'
            if success_count == len(ids)
            else f'Wysłano {printed_labels}/{total_labels} etykiet'
        ),
        'results': results,
    }


def _enqueue_labels(ids, items_by_id, station_code, actor, cfg):
    """
    Tryb LABEL_PRINTER_USE_AGENT=True: dla każdego znalezionego item generuje
    ZPL i wstawia rekord do prod_print_queue. Print-agent na hubie biura
    pobiera pending przez /api/print-agent/jobs i drukuje lokalnie.

    Returns: dict zgodny z print_labels_batch (z dodatkowym queued=True).
    """
    results = []
    success_count = 0
    actor_type = str(actor.get('type') or '')[:20]
    actor_id = str(actor.get('id') if actor.get('id') is not None else '')[:100]
    unit_offsets = _compute_unit_offsets(items_by_id)

    try:
        for sid in ids:
            item = items_by_id.get(sid)
            if item is None:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': f'Nie znaleziono produktu {sid}',
                    'label_print_count': 0,
                })
                continue
            try:
                copies = _resolve_copies(item)
                offset, total_units = unit_offsets.get(sid, (0, copies))
                job_ids = []
                for i in range(copies):
                    label_index = offset + i + 1
                    zpl = generate_label_zpl(
                        item, cfg,
                        label_index=label_index,
                        total_units=total_units,
                    )
                    job = LabelPrintJob(
                        short_product_id=sid,
                        baselinker_order_id=item.baselinker_order_id,
                        zpl_payload=zpl,
                        station_code=station_code,
                        requested_by_type=actor_type or 'user',
                        requested_by_id=actor_id or '0',
                        status=LabelPrintJob.STATUS_PENDING,
                    )
                    db.session.add(job)
                    db.session.flush()  # żeby dostać job.id
                    job_ids.append(job.id)
                # Bumpujemy licznik i timestamp tak samo jak w trybie TCP
                item.label_printed_at = datetime.utcnow()
                item.label_print_count = (item.label_print_count or 0) + copies
                results.append({
                    'short_product_id': sid, 'success': True,
                    'message': f'Dodano do kolejki drukowania ({copies} szt.)',
                    'label_print_count': item.label_print_count,
                    'queue_job_id': job_ids[0],            # back-compat: pierwszy job
                    'queue_job_ids': job_ids,              # pełna lista (1 per kopia)
                    'copies_requested': copies,
                    'copies_printed': copies,
                })
                success_count += 1
                logger.info(
                    "Label queued for print agent",
                    extra={
                        'short_product_id': sid, 'station': station_code,
                        'actor_type': actor_type, 'actor_id': actor_id,
                        'copies': copies,
                    },
                )
            except Exception as e:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': f'Błąd kolejkowania: {e}',
                    'label_print_count': item.label_print_count or 0,
                    'copies_requested': _resolve_copies(item),
                    'copies_printed': 0,
                })
                logger.error(
                    "Label enqueue failed",
                    extra={'short_product_id': sid, 'error': str(e)},
                )

        if success_count > 0:
            db.session.commit()
        else:
            db.session.rollback()
    except Exception:
        db.session.rollback()
        raise

    failed_count = len(ids) - success_count
    total_labels = sum(r.get('copies_requested', 0) for r in results)
    printed_labels = sum(r.get('copies_printed', 0) for r in results)
    return {
        'success': success_count > 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'total_labels': total_labels,
        'printed_labels': printed_labels,
        'connection_error': False,
        'queued': True,
        'message': (
            f'Wysłano {total_labels} etykiet do drukarki'
            if success_count == len(ids)
            else f'Zakolejkowano {printed_labels}/{total_labels} etykiet'
        ),
        'results': results,
    }
