"""
Serwis drukowania etykiet produkcyjnych (Xprinter XP-423B, ZPL).

Konfiguracja w prod_config (7 kluczy LABEL_PRINTER_*), edytowalna w
panelu admin ?tab=config. Wydruk = raw TCP socket do drukarki w LAN.

Wzorzec użycia:
    result = print_labels_batch(['25_04250_3'], 'formatowanie',
                                {'type': 'user', 'id': 1})
"""
from __future__ import annotations

import socket
from datetime import datetime

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionConfig, ProductionItem

logger = get_structured_logger('production.label_print')

DEFAULT_CONFIG = {
    'ip': '192.168.100.199',
    'port': 9100,
    'timeout_seconds': 3,
    'retry_count': 1,
    'offset_lt': -16,
    'offset_ls': 112,
    'allowed_stations': ['formatowanie', 'pakowanie'],
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
    ]
    rows = {
        c.config_key: c.config_value
        for c in ProductionConfig.query.filter(ProductionConfig.config_key.in_(keys)).all()
    }

    allowed_raw = rows.get('LABEL_PRINTER_ALLOWED_STATIONS', ','.join(DEFAULT_CONFIG['allowed_stations']))
    allowed = [s.strip() for s in str(allowed_raw).split(',') if s.strip()] or list(DEFAULT_CONFIG['allowed_stations'])

    ip_value = (rows.get('LABEL_PRINTER_IP') or DEFAULT_CONFIG['ip']).strip() or DEFAULT_CONFIG['ip']

    return {
        'ip': ip_value,
        'port': _coerce_int(rows.get('LABEL_PRINTER_PORT', DEFAULT_CONFIG['port']), DEFAULT_CONFIG['port']),
        'timeout_seconds': _coerce_int(rows.get('LABEL_PRINTER_TIMEOUT_SECONDS', DEFAULT_CONFIG['timeout_seconds']), DEFAULT_CONFIG['timeout_seconds']),
        'retry_count': _coerce_int(rows.get('LABEL_PRINTER_RETRY_COUNT', DEFAULT_CONFIG['retry_count']), DEFAULT_CONFIG['retry_count']),
        'offset_lt': _coerce_int(rows.get('LABEL_PRINTER_OFFSET_LT', DEFAULT_CONFIG['offset_lt']), DEFAULT_CONFIG['offset_lt']),
        'offset_ls': _coerce_int(rows.get('LABEL_PRINTER_OFFSET_LS', DEFAULT_CONFIG['offset_ls']), DEFAULT_CONFIG['offset_ls']),
        'allowed_stations': allowed,
    }


def generate_label_zpl(item, cfg):
    """
    Generuje ZPL dla etykiety 60x40 mm (layout v8, zatwierdzony).
    Kalibracja przez ^LT/^LS z konfiguracji (drukarka ma odwróconą konwencję ^LS —
    dodatnia wartość = w lewo).
    """
    species = _normalize_text(item.parsed_wood_species or '').upper() or 'BRAK'
    technology = _normalize_text(item.parsed_technology or '').upper() or 'BRAK'
    wood_class = _normalize_text(item.parsed_wood_class or '').upper() or '-'
    finish = _normalize_text(item.parsed_finish_type or '').upper() or 'SUROWE'
    edge_label = _format_edge_label(item) or 'BRAK'
    name = _normalize_text(item.original_product_name or '')[:80]
    short_id = _normalize_text(item.short_product_id or '')
    bl_id = item.baselinker_order_id or 0

    return (
        "^XA\n"
        "^PW480\n"
        "^LL320\n"
        f"^LT{cfg['offset_lt']}\n"
        f"^LS{cfg['offset_ls']}\n"
        "^CI28\n"
        "\n"
        "^FO0,0^GB480,50,50^FS\n"
        "^FO15,10^A0N,32,32^FR^FDWoodPower^FS\n"
        "\n"
        f"^FO15,62^A0N,32,32^FD{short_id}^FS\n"
        f"^FO15,102^A0N,22,22^FDBL: {bl_id}^FS\n"
        "\n"
        f"^FO380,60^BQN,2,4^FDLA,{short_id}^FS\n"
        "\n"
        "^FO15,145^GB345,2,2^FS\n"
        "\n"
        f"^FO15,158^A0N,22,22^FB450,2,0,L^FD{name}^FS\n"
        "\n"
        "^FO15,212^GB95,34,34,B,3^FS\n"
        f"^FO22,219^A0N,22,22^FR^FD{species}^FS\n"
        "\n"
        "^FO118,212^GB145,34,34,B,3^FS\n"
        f"^FO128,221^A0N,20,20^FR^FD{technology}^FS\n"
        "\n"
        "^FO271,212^GB58,34,34,B,3^FS\n"
        f"^FO281,219^A0N,22,22^FR^FD{wood_class}^FS\n"
        "\n"
        "^FO15,256^GB110,34,3,B,3^FS\n"
        f"^FO25,263^A0N,22,22^FD{finish}^FS\n"
        "\n"
        "^FO133,256^GB180,34,3,B,3^FS\n"
        f"^FO143,265^A0N,20,20^FD{edge_label}^FS\n"
        "\n"
        "^XZ\n"
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
        station_code: 'formatowanie' / 'pakowanie' / ...
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
            'connection_error': False,
            'message': 'Brak produktów do wydrukowania.',
            'results': [],
        }

    items_by_id = {
        i.short_product_id: i
        for i in ProductionItem.query.filter(ProductionItem.short_product_id.in_(ids)).all()
    }

    sock = _open_printer_socket(cfg)
    if sock is None:
        return {
            'success': False, 'success_count': 0, 'failed_count': len(ids),
            'connection_error': True,
            'message': 'Drukarka offline — sprawdź zasilanie/kabel.',
            'results': [
                {'short_product_id': sid, 'success': False,
                 'message': 'Drukarka nieosiągalna', 'label_print_count': 0}
                for sid in ids
            ],
        }

    results = []
    success_count = 0

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
                zpl = generate_label_zpl(item, cfg)
                sock.sendall(zpl.encode('utf-8'))
                item.label_printed_at = datetime.utcnow()
                item.label_print_count = (item.label_print_count or 0) + 1
                results.append({
                    'short_product_id': sid, 'success': True,
                    'message': 'Wysłano do drukarki',
                    'label_print_count': item.label_print_count,
                })
                success_count += 1
                logger.info(
                    "Label printed",
                    extra={
                        'short_product_id': sid, 'station': station_code,
                        'actor_type': actor.get('type'), 'actor_id': actor.get('id'),
                        'count': item.label_print_count,
                    },
                )
            except (OSError, socket.timeout) as e:
                results.append({
                    'short_product_id': sid, 'success': False,
                    'message': f'Błąd wysyłki: {e}',
                    'label_print_count': item.label_print_count or 0,
                })
                logger.error(
                    "Label send failed mid-batch",
                    extra={'short_product_id': sid, 'error': str(e)},
                )
                # Socket zerwany — nie próbujemy dalej
                break

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
    return {
        'success': success_count == len(ids) and success_count > 0,
        'success_count': success_count,
        'failed_count': failed_count,
        'connection_error': False,
        'message': (
            f'Wydrukowano {success_count} etykiet'
            if success_count == len(ids)
            else f'Wysłano {success_count}/{len(ids)} etykiet'
        ),
        'results': results,
    }
