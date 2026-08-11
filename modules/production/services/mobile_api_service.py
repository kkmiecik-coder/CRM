"""
Mobile API service — JWT, rejestracja urządzeń, serializacja DTO.

Obsługuje warstwę logiki dla blueprintu mobile_api_bp (natywna appka Android).
Router (`routers/mobile_api.py`) powinien być cienki — walidacja wejścia
i wywołanie funkcji z tego modułu.

Tranzycje statusu deleguje do `ProductionItem.complete_task()` — tej samej
metody modelu, której używa web-handler `/production/api/complete-task`.
"""

import ipaddress
import json
from datetime import datetime, time, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt
import pytz
from flask import current_app, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import (
    MobileAppRelease,
    ProcessedMobileOperation,
    ProductionDevice,
    ProductionItem,
    get_local_now,
)

logger = get_structured_logger('production.mobile_api')


def _rework_open_count(item):
    """Zwraca liczbę otwartych doróbek dla danego oryginału (0 dla doróbki samej w sobie)."""
    if item.is_rework or item.id is None:
        return 0
    from modules.production.models import ProductionReworkLog
    return db.session.query(ProductionReworkLog).filter(
        ProductionReworkLog.original_product_id == item.id,
        ProductionReworkLog.closed_at.is_(None),
    ).count()

# ============================================================================
# MAPOWANIE STANOWISK
# ============================================================================

# station_code → current_status w bazie (queue filter)
STATION_STATUS_MAP = {
    'packaging': 'czeka_na_pakowanie',
    'cutting': 'czeka_na_wyciecie',
    'assembly': 'czeka_na_skladanie',
    'gluing': 'czeka_na_sklejanie',
    'formatting': 'czeka_na_formatowanie',
    'finishing': 'czeka_na_wykanczanie',
    'painting': 'czeka_na_lakiernie',
}

# station_code → nazwa kolumny z licznikiem wykonanych sztuk
STATION_QUANTITY_FIELD = {
    'packaging': 'quantity_done_packaging',
    'cutting': 'quantity_done_cutting',
    'assembly': 'quantity_done_assembly',
    'gluing': 'quantity_done_gluing',
    'formatting': 'quantity_done_formatting',
    'finishing': 'quantity_done_finishing',
    'painting': 'quantity_done_painting',
}

# station_code → nazwa kolumny z timestampem ukończenia
STATION_COMPLETED_AT_FIELD = {
    'packaging': 'packaging_completed_at',
    'cutting': 'cutting_completed_at',
    'assembly': 'assembly_completed_at',
    'gluing': 'gluing_completed_at',
    'formatting': 'formatting_completed_at',
    'finishing': 'finishing_completed_at',
    'painting': 'painting_completed_at',
}

# Odwrotne mapowanie current_status → station_code (dla globalnego search,
# żeby UI wiedział na którym stanowisku aktualnie wisi pozycja).
STATUS_TO_STATION = {v: k for k, v in STATION_STATUS_MAP.items()}

# Aliasy stanowisk — urządzenie zarejestrowane jako jedno z poniższych może
# operować na pozostałych z tego samego zbioru. Tablet w wykańczalni rejestruje
# się jako `finishing`, ale w UI ma TabBar z dwiema zakładkami (Produkcja /
# Lakiernia) i fetchuje obie listy z tego samego JWT.
STATION_GROUPS = [
    {'finishing', 'painting'},
]


def device_can_access_station(device, station_code):
    """
    True gdy urządzenie może operować na danym stanowisku — bezpośrednio
    (device.station_code == station_code) lub przez alias (np. tablet
    zarejestrowany jako 'finishing' obsługuje też 'painting').
    """
    if not device or not station_code:
        return False
    device_station = device.station_code
    if device_station == station_code:
        return True
    for group in STATION_GROUPS:
        if device_station in group and station_code in group:
            return True
    return False


# ============================================================================
# KONFIGURACJA
# ============================================================================

def _get_config():
    return current_app.config.get('API_MOBILE', {})


def _get_jwt_secret():
    secret = _get_config().get('jwt_secret')
    if not secret or secret == 'WYGENERUJ_64_ZNAKOWY_LOSOWY_CIAG':
        raise RuntimeError(
            "API_MOBILE.jwt_secret nie jest skonfigurowany w config/core.json. "
            "Wygeneruj losowy 64-znakowy string."
        )
    return secret


# ============================================================================
# JWT
# ============================================================================

def generate_token(device):
    """Generuje JWT dla urządzenia. Domyślny expiry: 365 dni."""
    expiry_days = _get_config().get('jwt_expiry_days', 365)
    now = datetime.utcnow()
    payload = {
        'device_id': device.device_id,
        'station_code': device.station_code,
        'token_version': device.token_version,
        'iat': now,
        'exp': now + timedelta(days=expiry_days),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm='HS256')


def validate_token(token):
    """
    Waliduje JWT. Zwraca (device, claims) lub rzuca ValueError.

    Sprawdza: podpis, exp, istnienie i aktywność urządzenia, zgodność token_version.
    token_version w claimach musi być równy wartości w bazie — jeśli admin
    zbumpował token_version (np. po kradzieży tabletu), wszystkie stare JWT
    przestają działać natychmiast.
    """
    try:
        claims = jwt.decode(token, _get_jwt_secret(), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise ValueError('Token wygasł')
    except jwt.InvalidTokenError as e:
        raise ValueError(f'Token nieprawidłowy: {e}')

    device_id = claims.get('device_id')
    if not device_id:
        raise ValueError('Token bez device_id')

    device = ProductionDevice.query.filter_by(device_id=device_id).first()
    if not device:
        raise ValueError('Urządzenie nieznane')
    if not device.is_active:
        raise ValueError('Urządzenie zablokowane')
    if device.token_version != claims.get('token_version'):
        raise ValueError('Token unieważniony (token_version mismatch)')

    return device, claims


# ============================================================================
# IP WHITELIST (opcjonalny)
# ============================================================================

def _ip_in_whitelist(ip_str):
    """True gdy IP jest w whitelist LUB whitelist jest wyłączony w configu."""
    config = _get_config()
    if not config.get('require_ip_whitelist', False):
        return True
    whitelist = config.get('ip_whitelist', []) or []
    if not whitelist:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    for cidr in whitelist:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if ip in network:
                return True
        except ValueError:
            continue
    return False


def _version_too_old(actual, minimum):
    """SemVer comparison. True gdy actual < minimum."""
    try:
        a = tuple(int(x) for x in actual.split('.')[:3])
        m = tuple(int(x) for x in minimum.split('.')[:3])
        return a < m
    except (ValueError, AttributeError):
        return False


# ============================================================================
# HEARTBEAT — agregacja telemetrii dla dashboardu
# ============================================================================

HEARTBEAT_ACTIVE_THRESHOLD_MINUTES = 20

_STATION_CODES_WITH_TABLETS = (
    'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging',
    'sawmill',
)


def build_devices_telemetry(devices, now=None):
    """
    Buduje słownik telemetrii per station_code z listy ProductionDevice.

    Pure function — testowalna z stubami (SimpleNamespace).
    `devices`: iterable obiektów z atrybutami modelu ProductionDevice.
    `now`: datetime do liczenia progu (testowalność); default = get_local_now().

    Reguły:
    - Tylko is_active=True urządzenia są brane pod uwagę (fleet max APK i mapping).
    - "Najświeższy sygnał" = max(last_heartbeat_at, last_seen_at). HeartbeatWorker bije
      co 15 min, ale last_seen_at jest pingowane przy każdym requeście mobile (poprzez
      require_device_token), więc tablet aktywnie korzystający z API liczy się jako
      "Aktywne" zanim wyśle pierwszy heartbeat.
    - Gdy >1 urządzenie na station_code, bierzemy to z najświeższym sygnałem.
    - Próg `active`: najświeższy sygnał w ciągu ostatnich 20 min.
    - Telemetria (bateria/temp/version_code) wypełniona dopiero po pierwszym heartbeat —
      do tego czasu pola pozostają None, ale status_label już może być "Aktywne".
    - `apk_outdated`: tablet z last_app_version_code < max(last_app_version_code)
      ze wszystkich aktywnych urządzeń.
    """
    if now is None:
        now = get_local_now()

    active_devices = [d for d in devices if getattr(d, 'is_active', True)]

    fleet_max_apk = None
    for d in active_devices:
        v = getattr(d, 'last_app_version_code', None)
        if v is not None and (fleet_max_apk is None or v > fleet_max_apk):
            fleet_max_apk = v

    def _latest_signal(d):
        hb = getattr(d, 'last_heartbeat_at', None)
        seen = getattr(d, 'last_seen_at', None)
        if hb and seen:
            return max(hb, seen)
        return hb or seen

    per_station = {}
    for d in active_devices:
        sc = getattr(d, 'station_code', None)
        if sc not in _STATION_CODES_WITH_TABLETS:
            continue
        current = per_station.get(sc)
        if current is None:
            per_station[sc] = d
            continue
        d_sig = _latest_signal(d)
        c_sig = _latest_signal(current)
        if d_sig and (c_sig is None or d_sig > c_sig):
            per_station[sc] = d

    threshold = timedelta(minutes=HEARTBEAT_ACTIVE_THRESHOLD_MINUTES)

    result = {}
    for code in _STATION_CODES_WITH_TABLETS:
        d = per_station.get(code)
        if d is None:
            result[code] = {
                'active': False,
                'status_label': 'Niedostępne',
                'last_heartbeat_at': None,
                'battery_pct': None,
                'battery_charging': None,
                'temperature_c': None,
                'app_version_name': None,
                'app_version_code': None,
                'ip_address': None,
                'apk_outdated': False,
            }
            continue

        last_hb = getattr(d, 'last_heartbeat_at', None)
        latest = _latest_signal(d)
        active = bool(latest and (now - latest) < threshold)
        apk_code = getattr(d, 'last_app_version_code', None)
        apk_outdated = bool(
            fleet_max_apk and apk_code and apk_code < fleet_max_apk
        )

        result[code] = {
            'active': active,
            'status_label': 'Aktywne' if active else 'Niedostępne',
            'last_heartbeat_at': last_hb.isoformat() if last_hb else None,
            'battery_pct': getattr(d, 'last_battery_pct', None),
            'battery_charging': getattr(d, 'last_battery_charging', None),
            'temperature_c': getattr(d, 'last_temperature_c', None),
            'app_version_name': getattr(d, 'app_version', None),
            'app_version_code': apk_code,
            'ip_address': getattr(d, 'last_ip', None),
            'apk_outdated': apk_outdated,
        }

    return result


def get_devices_telemetry():
    """
    Thin wrapper — pobiera urządzenia z DB i deleguje do build_devices_telemetry.
    Wywoływane z routerów dashboardu.
    """
    devices = ProductionDevice.query.all()
    return build_devices_telemetry(devices)


# ============================================================================
# HEARTBEAT — walidacja payloadu
# ============================================================================

def validate_heartbeat_payload(payload):
    """
    Waliduje payload heartbeata urządzenia. Zwraca None gdy OK, lub
    krótki string z opisem błędu (do umieszczenia w response).

    Pure function — bez Flask context, bez DB. Testowalna unit.
    """
    battery_pct = payload.get('battery_pct')
    if battery_pct is not None:
        if not isinstance(battery_pct, int) or isinstance(battery_pct, bool) or not (0 <= battery_pct <= 100):
            return 'battery_pct out of range'

    temp = payload.get('temperature_c')
    if temp is not None:
        if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not (-20.0 <= temp <= 100.0):
            return 'temperature_c out of range'

    if 'app_version_code' not in payload or payload.get('app_version_code') is None:
        return 'app_version_code required'
    if not isinstance(payload['app_version_code'], int) or isinstance(payload['app_version_code'], bool):
        return 'app_version_code required'

    name = payload.get('app_version_name')
    if not name or not isinstance(name, str):
        return 'app_version_name required'

    return None


# ============================================================================
# DEKORATOR
# ============================================================================

def require_device_token(f):
    """
    Wymaga `Authorization: Bearer <JWT>`. Opcjonalnie sprawdza IP whitelist
    i minimalną wersję appki z `X-App-Version`.

    Po sukcesie wypełnia `g.device` i `g.claims`, touch'uje `last_seen_at`.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        if not _ip_in_whitelist(ip or ''):
            logger.warning("Mobile API: IP poza whitelist", extra={'ip': ip})
            return jsonify({'error': 'ip_not_allowed'}), 403

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'missing_token'}), 401
        token = auth_header[7:].strip()

        try:
            device, claims = validate_token(token)
        except ValueError as e:
            logger.warning("Mobile API: token invalid", extra={
                'ip': ip,
                'error': str(e)
            })
            return jsonify({'error': 'invalid_token', 'detail': str(e)}), 401

        app_version = request.headers.get('X-App-Version', '').strip()
        min_version = _get_config().get('min_supported_app_version', '0.0.0')
        if app_version and _version_too_old(app_version, min_version):
            return jsonify({
                'error': 'app_version_too_old',
                'min_supported': min_version,
                'your_version': app_version,
            }), 426

        try:
            device.touch(ip=ip, app_version=app_version or None)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Mobile API: touch device failed", extra={'error': str(e)})

        g.device = device
        g.claims = claims
        return f(*args, **kwargs)
    return wrapper


# ============================================================================
# IDEMPOTENCY (X-Operation-Id)
# ============================================================================

def with_idempotency(f=None, retryable_statuses=None, require_operation_id=False):
    """
    Decorator dla endpointów mutujących stan (POST /complete, PATCH /quantity).
    Obsługuje nagłówek X-Operation-Id:
    - brak → zachowanie zależne od require_operation_id (niżej)
    - istnieje w bazie → zwraca zapisany response, bez wywoływania handlera
    - nowy → wywołuje handler, zapisuje response w jednej transakcji (tylko 2xx/4xx)

    5xx i nieobsłużone wyjątki → rollback + re-raise, wpis NIE zapisywany
    (żeby klient mógł retry). Handler MUSI zwracać (response, status)
    i NIE MOŻE wewnątrz wywoływać db.session.commit() — zrobi to decorator.

    retryable_statuses: zbiór kodów 4xx, które mają być traktowane jak 5xx —
    rollback i BRAK zapisu, żeby klient mógł ponowić z tym samym
    X-Operation-Id. Trakownia używa {409}: gdy zlecenie zostało w międzyczasie
    zamknięte, admin je otwiera i tablet dosyła pomiary z kolejki. Bez tego
    dekorator odtwarzałby zapamiętane 409 bez wywołania handlera i pomiar
    przepadłby bezpowrotnie.

    Domyślnie pusty zbiór — zero zmian dla istniejących stanowisk. Działa
    zarówno bez nawiasów (@with_idempotency), jak i z argumentem
    (@with_idempotency(retryable_statuses={409})).

    require_operation_id: gdy True, żądanie BEZ nagłówka dostaje 400
    (`missing_operation_id`) zamiast zostać wykonane. Używa tego wyłącznie
    trakownia, której kontrakt deklaruje nagłówek jako wymagany, a aplikacja
    Android jeszcze nie istnieje — bez tego pominięcie nagłówka po stronie
    klienta tworzyłoby duplikat kłody przy każdym retry po timeoucie (na
    samym pomiarze nie ma unikatu, sequence_no nadaje serwer), a rozbieżność
    ujawniłaby się dopiero jako zawyżona objętość w rozliczeniu z dostawcą.

    Domyślnie False, bo tego samego dekoratora używają stanowiska produkcji,
    których aplikacja Android JEST JUŻ WDROŻONA — zaostrzenie globalne
    popsułoby działającą flotę tabletów.

    Kod 400, nie 422: w tym kontrakcie 422 znaczy „dane są błędne, nie
    ponawiaj", a tu wadliwe jest samo żądanie, nie pomiar.
    """
    retryable = frozenset(retryable_statuses or ())

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_id = request.headers.get('X-Operation-Id', '').strip()

            # Przed handlerem i przed jakimkolwiek zapisem do bazy.
            if require_operation_id and not op_id:
                logger.warning("Mobile API: brak X-Operation-Id", extra={
                    'endpoint': '{}.{}'.format(func.__module__, func.__name__),
                })
                return jsonify({
                    'error': 'missing_operation_id',
                    'detail': u'nagłówek X-Operation-Id jest wymagany '
                              u'dla operacji zmieniających dane',
                }), 400

            # Replay dla znanego op_id
            if op_id:
                existing = ProcessedMobileOperation.query.filter_by(
                    operation_id=op_id
                ).first()
                if existing:
                    logger.info("Mobile API idempotent replay", extra={
                        'operation_id': op_id,
                        'endpoint': existing.endpoint,
                        'original_status': existing.response_status,
                    })
                    try:
                        body = json.loads(existing.response_body)
                    except (ValueError, TypeError):
                        body = {}
                    return jsonify(body), existing.response_status

            # Handler wykonuje akcję (bez commit)
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                db.session.rollback()
                logger.error("Mobile API handler exception", extra={
                    'endpoint': request.endpoint,
                    'operation_id': op_id or None,
                    'error': str(e),
                })
                raise  # Flask error handler → 500, NIE zapisujemy w idempotency

            # Normalizacja wyniku
            if isinstance(result, tuple):
                response_obj = result[0]
                status_code = int(result[1]) if len(result) >= 2 else 200
            else:
                response_obj = result
                status_code = getattr(response_obj, 'status_code', 200)

            # 5xx (oraz statusy w `retryable`, np. 409 trakowni) → rollback, nie
            # zapisuj (klient retry z tym samym X-Operation-Id)
            if status_code >= 500 or status_code in retryable:
                db.session.rollback()
                return response_obj, status_code

            # 2xx / 4xx — commit, zapisz operation_id w tej samej transakcji
            if op_id:
                try:
                    body_dict = (
                        response_obj.get_json()
                        if hasattr(response_obj, 'get_json')
                        else response_obj
                    )
                    body_json = json.dumps(body_dict, ensure_ascii=False)
                except Exception:
                    body_json = '{}'

                op_record = ProcessedMobileOperation(
                    operation_id=op_id,
                    endpoint=request.endpoint or 'unknown',
                    order_id=kwargs.get('order_id'),
                    device_id=g.device.device_id if hasattr(g, 'device') else None,
                    response_status=status_code,
                    response_body=body_json,
                )
                db.session.add(op_record)

                try:
                    db.session.commit()
                except IntegrityError:
                    # Race: równoczesny request z tym samym op_id zdążył commit
                    # pierwszy. Rollback naszej sesji i zwróć zapisany przez
                    # rywala response.
                    db.session.rollback()
                    existing = ProcessedMobileOperation.query.filter_by(
                        operation_id=op_id
                    ).first()
                    if existing:
                        logger.info("Mobile API idempotent race resolved", extra={
                            'operation_id': op_id,
                            'winning_status': existing.response_status,
                        })
                        try:
                            body = json.loads(existing.response_body)
                        except (ValueError, TypeError):
                            body = {}
                        return jsonify(body), existing.response_status
                    logger.error(
                        "Mobile API IntegrityError bez istniejącego wpisu",
                        extra={'operation_id': op_id},
                    )
                    return jsonify({'error': 'idempotency_conflict'}), 500
            else:
                db.session.commit()

            # Hook BL: po commit może triggerować zmiany statusu w BaseLinker
            try:
                from .baselinker_status_sync import flush_pending_syncs
                flush_pending_syncs()
            except Exception as bl_error:
                logger.error("Mobile API: błąd flush BL status sync", extra={
                    'error': str(bl_error),
                })

            return response_obj, status_code
        return wrapper

    # Użycie bez nawiasów: @with_idempotency — f to od razu funkcja handlera.
    # Użycie z argumentem: @with_idempotency(retryable_statuses={409}) — f jest
    # None przy pierwszym wywołaniu, decorator() zostaje zaaplikowany dopiero
    # gdy Python nałoży zwrócony obiekt na funkcję.
    if f is not None:
        return decorator(f)
    return decorator


# Trakownia: measured_at sięga 30 dni wstecz, więc wpisy idempotencji muszą
# przeżyć dłużej niż domyślny tydzień — inaczej retry z długiej kolejki
# offline utworzy duplikaty kłód.
SAWMILL_RETENTION = {'sawmill_mobile.': 31}


def _escape_like_prefix(prefix):
    """
    Escapuje znaki specjalne LIKE (`%`, `_`) oraz sam znak ucieczki (`\\`)
    w dosłownym prefiksie endpointu, żeby np. `_` w 'sawmill_mobile.' nie był
    trafnie odczytany jako wildcard LIKE dopasowujący DOWOLNY jeden znak
    (`LIKE 'sawmill_mobile.%'` bez ESCAPE dopasowałby też 'sawmillXmobile.*').

    Wybór `ESCAPE '\\'` (a nie np. ręczne dzielenie na `LIKE`+regexp) bo:
    - to natywna, deklaratywna klauzula SQL LIKE, jednoznacznie wspierana
      i identycznie się zachowująca w MySQL i SQLite (obydwa dialekty
      respektują ESCAPE), więc zero warunków per-silnik;
    - `.like(pattern, escape='\\')` w SQLAlchemy 1.4 kompiluje się do tej
      klauzuli wprost — bez potrzeby `text()` czy surowego SQL.
    """
    return prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def cleanup_old_operations(older_than_days=7, endpoint_retention=None):
    """
    Usuwa wpisy z processed_mobile_operations starsze niż older_than_days dni.
    Używane przez `flask cleanup-mobile-operations` CLI command.

    endpoint_retention: mapa {prefiks_endpointu: dni} dla endpointów
    wymagających dłuższej retencji niż domyślna. Trakownia dopuszcza
    measured_at do 30 dni wstecz, więc tablet offline dłużej niż tydzień
    zduplikowałby kłody — jej operacje trzymamy 31 dni. Pozostałe stanowiska
    bez zmian (domyślnie None → tylko SAWMILL_RETENTION).

    Returns:
        int: liczba usuniętych wierszy (suma z obu przebiegów)
    """
    if endpoint_retention is None:
        endpoint_retention = SAWMILL_RETENTION

    now = get_local_now()
    deleted = 0

    # Endpointy z niestandardową retencją — usuń tylko to, co starsze niż ich
    # własny próg. Prefiks escapowany (patrz `_escape_like_prefix`) — inaczej
    # `_` w prefiksie dopasowałby się jako wildcard do dowolnego znaku.
    for prefix, days in endpoint_retention.items():
        cutoff = now - timedelta(days=days)
        deleted += (
            ProcessedMobileOperation.query
            .filter(ProcessedMobileOperation.endpoint.like(
                _escape_like_prefix(prefix) + '%', escape='\\'
            ))
            .filter(ProcessedMobileOperation.processed_at < cutoff)
            .delete(synchronize_session=False)
        )

    # Reszta endpointów — domyślna retencja, z wykluczeniem prefiksów już
    # obsłużonych wyżej (żeby nie usunąć ich świeżych wpisów przed czasem).
    # Ta sama escapowana logika co wyżej — rozjazd między obiema pętlami
    # oznaczałby wiersze usuwane dwa razy albo nieusuwane wcale.
    cutoff = now - timedelta(days=older_than_days)
    query = ProcessedMobileOperation.query.filter(
        ProcessedMobileOperation.processed_at < cutoff
    )
    for prefix in endpoint_retention:
        query = query.filter(~ProcessedMobileOperation.endpoint.like(
            _escape_like_prefix(prefix) + '%', escape='\\'
        ))
    deleted += query.delete(synchronize_session=False)

    db.session.commit()
    logger.info("Mobile API: cleanup zakończony", extra={
        'deleted_count': deleted,
        'older_than_days': older_than_days,
        'endpoint_retention': endpoint_retention,
        'cutoff': cutoff.isoformat(),
    })
    return deleted


# ============================================================================
# REJESTRACJA URZĄDZENIA
# ============================================================================

def register_device(device_id, device_name, station_code):
    """
    Idempotentna rejestracja urządzenia po device_id.
    Re-rejestracja: aktualizuje station_code/device_name, reaktywuje is_active.
    Zwraca (device, token).
    """
    device = ProductionDevice.query.filter_by(device_id=device_id).first()
    if device:
        device.station_code = station_code
        if device_name:
            device.device_name = device_name
        device.is_active = True
        logger.info("Mobile API: re-registration", extra={
            'device_id': device_id,
            'station_code': station_code,
        })
    else:
        device = ProductionDevice(
            device_id=device_id,
            device_name=device_name or None,
            station_code=station_code,
        )
        db.session.add(device)
        logger.info("Mobile API: new device registered", extra={
            'device_id': device_id,
            'station_code': station_code,
        })

    db.session.commit()
    token = generate_token(device)
    return device, token


# ============================================================================
# GLOBALNE WYSZUKIWANIE ZAMÓWIEŃ (mobile)
# ============================================================================

import re

DIMENSION_TOLERANCE_MM = 5

# Akceptujemy x, X, ×, * lub białe znaki jako separator między liczbami.
# Liczby z kropką lub przecinkiem jako separatorem dziesiętnym.
_DIM_TOKEN_RE = re.compile(r'^-?\d+(?:[.,]\d+)?$')
_DIM_SPLIT_RE = re.compile(r'[xX×*\s]+')


def parse_dimension_query(query):
    """
    Parsuje query jako 1-3 liczby (cm) → posortowana lista wymiarów w mm.

    Zwraca None gdy query nie wygląda na zapytanie wymiarowe (np. zawiera
    litery inne niż x/X poza separatorami). Lista pusta jest niemożliwa —
    zwracamy None w takim przypadku.

    Identyczna logika jak StationSearchDialog.kt#parseDimensionQuery w
    crm_prod_app — zachowanie 1:1 (multiset matching + tolerancja ±5 mm
    aplikowane potem w `_match_item_dimensions`).
    """
    if not query:
        return None
    raw = query.strip()
    if not raw:
        return None
    tokens = [t for t in _DIM_SPLIT_RE.split(raw) if t]
    if not tokens or len(tokens) > 3:
        return None
    mm_values = []
    for tok in tokens:
        if not _DIM_TOKEN_RE.match(tok):
            return None
        try:
            cm = float(tok.replace(',', '.'))
        except ValueError:
            return None
        if cm <= 0:
            return None
        mm_values.append(int(round(cm * 10)))
    mm_values.sort()
    return mm_values


def _match_item_dimensions(item, query_mm_sorted):
    """
    Greedy multiset match — dla każdej liczby z query szuka najmniejszej
    wolnej osi (length/width/thickness) w tolerancji ±5 mm.
    """
    axes_cm = [
        item.parsed_length_cm,
        item.parsed_width_cm,
        item.parsed_thickness_cm,
    ]
    axes_mm = sorted(
        [int(round(float(a) * 10)) for a in axes_cm if a is not None]
    )
    if not axes_mm:
        return False
    used = [False] * len(axes_mm)
    for q in query_mm_sorted:
        lo, hi = q - DIMENSION_TOLERANCE_MM, q + DIMENSION_TOLERANCE_MM
        picked = -1
        for i, axis in enumerate(axes_mm):
            if used[i]:
                continue
            if lo <= axis <= hi:
                picked = i
                break
        if picked == -1:
            return False
        used[picked] = True
    return True


def search_orders_global(query, limit=50):
    """
    Globalne wyszukiwanie zamówień (po wszystkich stanowiskach).

    Etapy:
      1. Parsuj query — czy wygląda na wymiary?
      2. SQL: szeroki pre-filter — text ILIKE OR (luźny zakres wymiarów).
         Dla wymiarów pre-filtr zwraca pozycje gdzie którakolwiek z osi
         mieści się w [min(q)-5, max(q)+5]; właściwy multiset-match
         robimy w Pythonie.
      3. Python: dopasuj wymiarowo (multiset, tolerancja ±5 mm).
      4. Zbierz internal_order_number pasujących pozycji, posortuj po
         priority_rank ASC NULLS LAST, internal_order_number.
      5. Po przycięciu do `limit` zamówień dociągnij WSZYSTKIE pozycje
         z tych zamówień.

    Zwraca: (items_list, has_more, total_matching_orders).
    `items_list` — lista ProductionItem (z joinedload(order, configuration)).
    `has_more` — True gdy total_matching_orders > limit.
    """
    from sqlalchemy import or_, and_, cast, String

    # Klauzule SQL — szeroki kandydat.
    from modules.production.models import ProductionOrder  # local import — unika cykli

    q = (query or '').strip()
    like = f'%{q}%'
    text_clauses = [
        ProductionOrder.internal_order_number.ilike(like),
        cast(ProductionOrder.baselinker_order_id, String).ilike(like),
        ProductionOrder.client_order_number.ilike(like),
        ProductionOrder.client_name.ilike(like),
    ]

    dim_mm_sorted = parse_dimension_query(q)
    dim_clauses = []
    if dim_mm_sorted:
        lo = min(dim_mm_sorted) - DIMENSION_TOLERANCE_MM
        hi = max(dim_mm_sorted) + DIMENSION_TOLERANCE_MM
        # Numeric * 10 → mm
        lo_cm = lo / 10.0
        hi_cm = hi / 10.0
        dim_clauses = [
            and_(ProductionItem.parsed_length_cm.isnot(None),
                 ProductionItem.parsed_length_cm.between(lo_cm, hi_cm)),
            and_(ProductionItem.parsed_width_cm.isnot(None),
                 ProductionItem.parsed_width_cm.between(lo_cm, hi_cm)),
            and_(ProductionItem.parsed_thickness_cm.isnot(None),
                 ProductionItem.parsed_thickness_cm.between(lo_cm, hi_cm)),
        ]

    candidate_filter = or_(*text_clauses, *dim_clauses)

    candidates = db.session.query(ProductionItem).options(
        joinedload(ProductionItem.order),
        joinedload(ProductionItem.configuration),
    ).join(
        ProductionOrder, ProductionItem.order_id == ProductionOrder.id,
    ).filter(candidate_filter).all()

    # Sprawdź czy pozycja pasuje TEXT-em (na poziomie order) lub wymiarowo.
    # Pre-filter SQL mógł zwrócić pozycje, które same nie pasują wymiarowo,
    # ale pasuje TEXT na ich zamówieniu — wtedy też ok.
    q_lower = q.lower()
    def _text_match(item):
        order = item.order
        if not order:
            return False
        if order.internal_order_number and q_lower in order.internal_order_number.lower():
            return True
        if order.baselinker_order_id is not None and q_lower in str(order.baselinker_order_id):
            return True
        if order.client_order_number and q_lower in order.client_order_number.lower():
            return True
        if order.client_name and q_lower in order.client_name.lower():
            return True
        return False

    matching_order_ids = set()
    for item in candidates:
        if not item.order:
            continue
        text_ok = _text_match(item)
        dim_ok = bool(dim_mm_sorted) and _match_item_dimensions(item, dim_mm_sorted)
        if text_ok or dim_ok:
            matching_order_ids.add(item.order_id)

    if not matching_order_ids:
        return [], False, 0

    # Sortuj zamówienia po (priority_rank ASC NULLS LAST, internal_order_number).
    # Priorytet zamówienia = MIN(priority_rank) jego pozycji.
    NULLS_LAST = 999999
    order_min_prio = {}
    order_internal_no = {}
    for item in candidates:
        if item.order_id not in matching_order_ids:
            continue
        rank = item.priority_rank if item.priority_rank is not None else NULLS_LAST
        if item.order_id not in order_min_prio or rank < order_min_prio[item.order_id]:
            order_min_prio[item.order_id] = rank
        if item.order and item.order_id not in order_internal_no:
            order_internal_no[item.order_id] = item.order.internal_order_number or ''

    sorted_order_ids = sorted(
        matching_order_ids,
        key=lambda oid: (order_min_prio.get(oid, NULLS_LAST), order_internal_no.get(oid, '')),
    )
    total_orders = len(sorted_order_ids)
    has_more = total_orders > limit
    selected_order_ids = sorted_order_ids[:limit]

    if not selected_order_ids:
        return [], has_more, total_orders

    # Pełne pozycje dla wybranych zamówień — łącznie z tymi które nie pasują
    # do query (UI grupuje per internal_order_number i pokazuje całą grupę).
    items = db.session.query(ProductionItem).options(
        joinedload(ProductionItem.order),
        joinedload(ProductionItem.configuration),
    ).filter(
        ProductionItem.order_id.in_(selected_order_ids),
    ).order_by(
        func.coalesce(ProductionItem.priority_rank, NULLS_LAST).asc(),
        ProductionItem.order_id.asc(),
        ProductionItem.product_sequence_in_order.asc(),
    ).all()

    return items, has_more, total_orders


# ============================================================================
# SERIALIZER: ProductionItem → OrderDto
# ============================================================================

_ATTACHMENT_MIME_BY_EXT = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'pdf': 'application/pdf',
}


def _build_attachments(item):
    """
    Lista załączników dla OrderDto.

    Etap 1.5: tylko załącznik z Baselinker (ProductionItem.attachment_file_url) —
    publiczny URL CDN, tablet pobiera bezpośrednio (bez Authorization). Quote
    attachments (quote_item_detail_id → Quote.attachment_stored_name) są pominięte
    — ich endpoint `/quotes/api/attachment/<name>` wymaga sesji Flask-Login,
    więc nieosiągalny z JWT tabletu. Wymagałby osobnego proxy pod require_device_token.

    size_bytes = 0 — Baselinker nie zwraca rozmiaru, a HEAD na każde serialize
    byłby zbyt drogi. Android użyje Content-Length z response przy pobieraniu.
    """
    url = ((item.order.attachment_file_url if item.order else None) or '').strip()
    if not url:
        return []

    name = ((item.order.attachment_file_name if item.order else None) or '').strip() or url.rsplit('/', 1)[-1]
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    mime_type = _ATTACHMENT_MIME_BY_EXT.get(ext, 'application/octet-stream')

    return [{
        'url': url,
        'name': name,
        'mime_type': mime_type,
        'size_bytes': 0,
    }]


def serialize_order(item, station_code=None):
    """
    ProductionItem → dict (OrderDto).
    Gdy podano station_code, dokłada quantity_done dla tego stanowiska.
    """
    def _num(value):
        return float(value) if value is not None else None

    def _iso(dt):
        return dt.isoformat() if dt else None

    dimensions = None
    if any([item.parsed_length_cm, item.parsed_width_cm, item.parsed_thickness_cm]):
        def _mm(cm):
            return int(float(cm) * 10) if cm is not None else None
        dimensions = {
            'length_mm': _mm(item.parsed_length_cm),
            'width_mm': _mm(item.parsed_width_cm),
            'thickness_mm': _mm(item.parsed_thickness_cm),
        }

    finish = None
    if item.parsed_finish_type and item.parsed_finish_type != 'surowe':
        finish = {
            'type': item.parsed_finish_type,
            'color_type': item.parsed_finish_color_type,
            'color': item.parsed_finish_color,
            'gloss': item.parsed_finish_gloss,
        }

    edge = None
    if item.parsed_edge_processing:
        from modules.calculator.services.edge_calculator import human_edge_label
        raw_letters = item.parsed_edge_letters or []
        raw_groups = item.parsed_edges_groups or []
        edge = {
            'type': item.parsed_edge_type,
            'radius': item.parsed_edge_radius,
            'angle': item.parsed_edge_angle,
            'letters': raw_letters,
            'letters_labeled': [human_edge_label(l) for l in raw_letters],
            # Multi-group (tryb Zaawansowany) — lista grup {type, radius, angle, letters}.
            # Pusta lista = legacy single-group (użyj pól type/radius/angle/letters powyżej jako fallback).
            'groups': [
                {
                    **g,
                    'letters_labeled': [human_edge_label(l) for l in (g.get('letters') or [])],
                }
                for g in raw_groups
            ],
        }

    quantity_done = None
    if station_code and station_code in STATION_QUANTITY_FIELD:
        quantity_done = getattr(item, STATION_QUANTITY_FIELD[station_code], None)

    # Kategoria dostawy — kolejność warunków przeniesiona z badge'a dostawy
    # w panelu pakowania (templates/stations/packaging.html, usunięty w Etapie 0
    # profili pracowników; kod w historii gita, commit 0391556).
    # Odrębna od property ProductionItem.delivery_type (zwracającej tylko 2 wartości).
    override_delivery = item.order.override_delivery_method if item.order else None
    is_personal = item.order.is_personal_pickup if item.order else False
    if override_delivery == 'transport_woodpower':
        delivery_type = 'transport_woodpower'
    elif override_delivery == 'kurier_baselinker':
        delivery_type = 'courier_baselinker'
    elif is_personal:
        delivery_type = 'personal_pickup'
    else:
        delivery_type = 'courier'

    return {
        'id': item.id,
        'short_id': item.short_product_id,
        'internal_order_number': item.order.internal_order_number if item.order else None,
        'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
        'product_name': item.original_product_name,
        'client_name': item.order.client_name if item.order else None,
        'client_order_number': item.order.client_order_number if item.order else None,
        'delivery_type': delivery_type,
        'wood_species': item.configuration.species if item.configuration else None,
        'wood_class': item.configuration.wood_class if item.configuration else None,
        'technology': item.configuration.technology if item.configuration else None,
        'dimensions': dimensions,
        'volume_m3': _num(item.volume_m3),
        'quantity_ordered': item.quantity,
        'quantity_done': quantity_done,
        'priority_rank': item.priority_rank,
        'is_priority': item.is_priority,
        'status': item.current_status,
        'status_display': item.status_display_name,
        'finish': finish,
        'edge': edge,
        'delivery_city': item.order.delivery_city if item.order else None,
        'delivery_postcode': item.order.delivery_postcode if item.order else None,
        'deadline': _iso(item.deadline_date) if item.deadline_date else None,
        'order_notes': item.order.order_notes if item.order else None,
        'production_notes': item.production_notes,
        'attachments': _build_attachments(item),
        'shape_svg': item.shape_svg,
        'shape': item.shape,
        'edge_svg': item.edge_svg,
        'has_edge': bool(item.parsed_edge_processing),
        'cut_to_size': bool(getattr(item, 'cut_to_size', True)),
        'lamella_direction': item.lamella_direction,
        'updated_at': _iso(item.updated_at),
        'is_rework': item.is_rework,
        'original_product_id': item.original_product_id,
        'rework_open_count': _rework_open_count(item),
    }


# ============================================================================
# AKCJE NA ZLECENIACH
# ============================================================================

def mark_order_complete(item, station_code, *, device_id=None,
                        worker_ids=None, session_ids=None):
    """
    Oznacza zlecenie jako ukończone na danym stanowisku.

    Deleguje do `ProductionItem.complete_task(station_code)` — tej samej
    metody modelu której używa web-handler `/production/api/complete-task`.
    Pełna tranzycja statusu (cutting/assembly/gluing/formatting/finishing/
    painting/packaging) plus reguły specjalne (skip finishing dla surowych
    bez krawędzi, lakiernia dla olejowanych/lakierowanych, personal_pickup
    omija logistykę) są obsłużone w modelu.

    NAJPIERW domykamy sztuki przez set_quantity_done(), DOPIERO POTEM
    complete_task(). Powód (docs/worker-profiles-backend.md §8, pułapka nr 1):
    complete_task() tworzy ProductionStationEvent WYŁĄCZNIE dla stanowisk
    pomijanych (auto_skip / system), więc samo zamknięcie stanowiska nie
    zostawiało dotąd ŻADNEGO śladu w prod_station_events. Po usunięciu paneli
    webowych ta ścieżka jest jedyną, którą zamyka się stanowisko — bez tej
    kolejności atrybucja pokryłaby tylko PATCH /quantity, a statystyki
    stanowisk gubiłyby całą pracę zamykaną przyciskiem "gotowe".

    Gdy wszystkie sztuki były już odbite wcześniej, set_quantity_done()
    nie tworzy niczego (delta = 0) — duplikatu nie ma.

    Rejestruje też hook do BL (uruchamiany po commit decoratora
    `with_idempotency`) który może zmienić status zamówienia w BaseLinker
    na "Produkcja zakończona" / "Zamówienie spakowane".
    """
    if station_code not in STATION_QUANTITY_FIELD:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    # max(), nie samo item.quantity: quantity potrafi SPAŚĆ poniżej już odbitych
    # sztuk — doróbka zabiera sztuki oryginałowi (rework_service), a sync
    # Baselinkera potrafi skorygować zamówienie w dół. Twarde przypisanie dawało
    # wtedy delta < 0 przy kolejnym "gotowe" (retry z kolejki offline, dwuklik,
    # powrót doróbki): kasowało historyczny quantity_done, wpisywało do audytu
    # fałszywe "cofnięcie" (product_history_service traktuje delta<0 jako reject)
    # i odejmowało pracownikowi sztuki w raporcie imiennym.
    # "Gotowe" znaczy "wszystko zrobione", nigdy "zrób mniej niż już zrobiono".
    item.set_quantity_done(
        station_code,
        max(item.quantity, item.get_quantity_done(station_code) or 0),
        actor_device_id=device_id,
        source='mobile',
        actor_worker_ids=worker_ids,
        actor_session_ids=session_ids,
    )

    item.complete_task(station_code)

    from .baselinker_status_sync import schedule_after_station_complete
    if item.order:
        schedule_after_station_complete(item.order.internal_order_number, station_code)


def update_order_quantity(item, station_code, quantity_done, *, device_id=None,
                          worker_ids=None, session_ids=None):
    """
    Aktualizuje liczbę ukończonych sztuk na stanowisku (0 <= qd <= item.quantity).

    Deleguje do `ProductionItem.set_quantity_done()` żeby spójnie z webem
    zalogować zdarzenie w `prod_station_events` (source='mobile') i — gdy
    tablet przysłał X-Worker-Ids — dopiąć atrybucję dzieloną.
    """
    if station_code not in STATION_QUANTITY_FIELD:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    if quantity_done < 0:
        raise ValueError('quantity_done nie może być ujemny')
    if quantity_done > item.quantity:
        raise ValueError(
            f'quantity_done ({quantity_done}) > quantity ({item.quantity})'
        )

    item.set_quantity_done(
        station_code,
        quantity_done,
        actor_device_id=device_id,
        source='mobile',
        actor_worker_ids=worker_ids,
        actor_session_ids=session_ids,
    )


# ============================================================================
# APP VERSION / APK HOSTING
# ============================================================================

# Limit rozmiaru APK (50 MB) — sanity check przy uploadzie. Globalny
# MAX_CONTENT_LENGTH Flask jest większy (100 MB w app.py), ale APK
# WoodPower ma ~11 MB, więc 50 MB to z dużym zapasem.
APK_MAX_SIZE_BYTES = 50 * 1024 * 1024

# TODO: weryfikacja podpisu APK certem produkcyjnym WoodPower.
# Cert SHA-256 (zachowany żeby nie szukać przy implementacji):
#   d5e2a671e60dc6c8a0b95ad60334c2f9e841c8e36d84a8444d25b2dcd247fa29
# pyaxmlparser nie wystawia signing certa — wymaga apksigner (subprocess
# z Android SDK build-tools) lub własnego parsera bloku v2/v3 signing.
# Wdrożymy w osobnym commicie kiedy zajdzie potrzeba (obecnie soft-skip).


def _instance_apk_dir():
    """Pełna ścieżka do katalogu instance/mobile_apk/. Tworzy jeśli brak."""
    base = Path(current_app.instance_path) / 'mobile_apk'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _release_absolute_path(release):
    """Pełna ścieżka do pliku APK dla danego release'u."""
    return Path(current_app.instance_path) / release.file_path


def get_app_version_info():
    """
    Metadane najnowszego aktywnego release'u (publiczne — klient woła przed
    rejestracją do sanity-check'u). Gdy w bazie nie ma żadnego release'u →
    zwraca {'version_code': 0} (klient interpretuje jako "brak update'ów").
    """
    release = MobileAppRelease.latest_active()
    if release is None:
        return {
            'version_code': 0,
            'version_name': None,
            'sha256': None,
            'release_notes': None,
            'apk_url': None,
            'min_supported_version': _get_config().get(
                'min_supported_app_version', '0.0.0'
            ),
        }

    return {
        'version_code': release.version_code,
        'version_name': release.version_name,
        'sha256': release.sha256,
        'release_notes': release.release_notes,
        'file_size_bytes': release.file_size_bytes,
        'apk_url': f'/api/mobile/app/apk?version={release.version_code}',
        'min_supported_version': _get_config().get(
            'min_supported_app_version', '0.0.0'
        ),
    }


def stream_apk_response(version_code):
    """
    Streaming pliku APK dla zadanego version_code. 404 gdy release nie istnieje
    lub jest nieaktywny. Plik wysyłany przez send_from_directory (streaming
    Flaska, mimetype application/vnd.android.package-archive).
    """
    from flask import send_from_directory

    release = MobileAppRelease.query.filter_by(
        version_code=version_code,
        is_active=True,
    ).first()
    if release is None:
        return jsonify({'error': 'release_not_found'}), 404

    path = _release_absolute_path(release)
    if not path.is_file():
        logger.error("Mobile API: release w DB istnieje ale plik APK nie", extra={
            'version_code': version_code,
            'expected_path': str(path),
        })
        return jsonify({'error': 'release_file_missing'}), 404

    return send_from_directory(
        path.parent,
        path.name,
        mimetype='application/vnd.android.package-archive',
        as_attachment=True,
        download_name=f'woodpower-crm-prod-app-{release.version_code}.apk',
    )


# ----------------------------------------------------------------------------
# UPLOAD / RELEASE MANAGEMENT (admin)
# ----------------------------------------------------------------------------

def _hash_file_sha256(path, chunk_size=1024 * 1024):
    """SHA-256 pliku, czytany w kawałkach (1 MB) żeby nie ładować ~11 MB do RAM."""
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def register_release(file_storage, version_code, version_name, release_notes, user_id):
    """
    Rejestruje nowy release APK.

    Kroki:
    1. Save uploadu do tymczasowego pliku w instance/mobile_apk/.
    2. Walidacja rozmiaru (<= APK_MAX_SIZE_BYTES).
    3. Walidacja: version_code > max(istniejących); brak duplikatu.
    4. SHA-256 całego pliku.
    5. Rename pliku do finalnej nazwy `<version_code>-<sha256_short>.apk`.
    6. INSERT do mobile_app_releases.

    `version_code` i `version_name` admin podaje w formularzu (z build.gradle.kts).
    Backend nie parsuje już manifestu APK — pyaxmlparser był wąskim gardłem
    (2-3 min na shared hostingu) i wycinamy go z flow uploadu.

    Rzuca ValueError dla błędów walidacji (400 dla klienta), inne wyjątki
    propagują do error handlera.
    """
    import os
    import secrets

    if file_storage is None or not file_storage.filename:
        raise ValueError('Brak pliku APK')

    apk_dir = _instance_apk_dir()
    tmp_name = f'.upload-{secrets.token_hex(8)}.apk'
    tmp_path = apk_dir / tmp_name

    try:
        file_storage.save(str(tmp_path))
        size = tmp_path.stat().st_size

        if size == 0:
            raise ValueError('Plik APK jest pusty')
        if size > APK_MAX_SIZE_BYTES:
            raise ValueError(
                f'Plik APK ({size} B) przekracza limit '
                f'{APK_MAX_SIZE_BYTES} B (50 MB)'
            )

        max_existing = db.session.query(
            func.coalesce(func.max(MobileAppRelease.version_code), 0)
        ).scalar() or 0
        if version_code <= max_existing:
            raise ValueError(
                f'versionCode {version_code} musi być > '
                f'najwyższy istniejący ({max_existing}). '
                'Zwiększ versionCode w build.gradle przed buildem.'
            )

        sha256 = _hash_file_sha256(tmp_path)
        sha_short = sha256[:8]

        final_name = f'{version_code}-{sha_short}.apk'
        final_path = apk_dir / final_name
        if final_path.exists():
            raise ValueError(
                f'Plik {final_name} już istnieje — sugeruje race lub '
                'duplikat APK. Sprawdź ręcznie zawartość katalogu.'
            )
        os.replace(str(tmp_path), str(final_path))

        rel_path = f'mobile_apk/{final_name}'

        release = MobileAppRelease(
            version_code=version_code,
            version_name=version_name,
            file_path=rel_path,
            file_size_bytes=size,
            sha256=sha256,
            release_notes=(release_notes or '').strip() or None,
            uploaded_by_user_id=user_id,
            is_active=True,
        )
        db.session.add(release)
        db.session.commit()

        logger.info("Mobile APK release registered", extra={
            'version_code': version_code,
            'version_name': version_name,
            'sha256': sha256,
            'size_bytes': size,
            'uploaded_by': user_id,
        })
        return release

    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        db.session.rollback()
        raise


def list_releases():
    """Wszystkie release'y posortowane od najnowszego, jako lista dictów."""
    releases = MobileAppRelease.query.order_by(
        MobileAppRelease.version_code.desc()
    ).all()
    return [
        {
            'id': r.id,
            'version_code': r.version_code,
            'version_name': r.version_name,
            'file_size_bytes': r.file_size_bytes,
            'sha256': r.sha256,
            'sha256_short': r.sha256[:8],
            'release_notes': r.release_notes,
            'uploaded_at': r.uploaded_at.isoformat() if r.uploaded_at else None,
            'uploaded_by_user_id': r.uploaded_by_user_id,
            'is_active': r.is_active,
        }
        for r in releases
    ]


def set_release_active(release_id, is_active):
    """Toggle is_active dla release'u — pozwala wycofać buggy build."""
    release = MobileAppRelease.query.get(release_id)
    if release is None:
        raise ValueError(f'Release {release_id} nie istnieje')
    release.is_active = bool(is_active)
    db.session.commit()
    logger.info("Mobile APK release active toggled", extra={
        'release_id': release_id,
        'version_code': release.version_code,
        'is_active': release.is_active,
    })
    return release


# ============================================================================
# SUMMARY (dashboard stanowiska)
# ============================================================================

def _today_range_warsaw():
    """(today_start, tomorrow_start) jako naive datetimes w strefie Warszawy."""
    now_pl = get_local_now()
    today_start = datetime.combine(now_pl.date(), time.min)
    tomorrow_start = today_start + timedelta(days=1)
    return today_start, tomorrow_start


def compute_station_summary(station_code):
    """
    Metryki stanowiska:
    - queue: count aktualnie oczekujących + łączne m³ + ile priorytetów
    - completed_today: count ukończonych dzisiaj + łączne m³ (na tym stanowisku)
    """
    status = STATION_STATUS_MAP.get(station_code)
    completed_field_name = STATION_COMPLETED_AT_FIELD.get(station_code)
    if not status or not completed_field_name:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    queue_agg = db.session.query(
        func.count(ProductionItem.id),
        func.coalesce(func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0),
        func.sum(
            db.case(
                (ProductionItem.is_priority == True, 1),  # noqa: E712
                else_=0,
            )
        ),
    ).filter(ProductionItem.current_status == status).one()

    today_start, tomorrow_start = _today_range_warsaw()
    # Faktyczna praca dziś — z prod_station_events (uwzględnia partial work,
    # nie wymaga że wszystkie sztuki pozycji są ukończone).
    from .station_events_service import get_station_work_in_range
    try:
        completed_work = get_station_work_in_range(station_code, today_start, tomorrow_start)
        completed_count = int(completed_work['items_count'])
        completed_volume = float(completed_work['m3_done'])
    except Exception as e:
        logger.warning("Nie udało się pobrać station_events dla mobile", extra={
            'station': station_code, 'error': str(e)
        })
        completed_count = 0
        completed_volume = 0.0

    # Częstotliwość auto-refresh listy zleceń (klient mobilny używa jej zamiast
    # hardcoded 30s). Źródło: config_service z tabeli ProductionConfig,
    # fallback 30 zgodny z ProductionConfigService._default_values.
    from modules.production.services.config_service import get_config_service
    try:
        refresh_interval = int(
            get_config_service().get_config('REFRESH_INTERVAL_SECONDS', 30)
        )
    except Exception as e:
        logger.warning("Nie udało się pobrać REFRESH_INTERVAL_SECONDS, fallback 30", extra={
            'error': str(e)
        })
        refresh_interval = 30

    return {
        'station_code': station_code,
        'queue': {
            'count': int(queue_agg[0] or 0),
            'total_volume_m3': float(queue_agg[1] or 0),
            'priority_count': int(queue_agg[2] or 0),
        },
        'completed_today': {
            'count': completed_count,
            'total_volume_m3': completed_volume,
        },
        'refresh_interval_seconds': refresh_interval,
        'server_time': get_local_now().isoformat(),
    }


# ============================================================================
# DELTA SYNC
# ============================================================================

def parse_since_ts(ts_str):
    """
    Parsuje ISO 8601 timestamp do naive datetime w strefie Warszawy.
    Akceptuje: '2026-04-23T14:00:00Z', '2026-04-23T14:00:00+00:00', '2026-04-23T14:00:00'.
    Timestamp bez strefy traktowany jako UTC.
    """
    if not ts_str:
        raise ValueError('ts is required')
    s = ts_str.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f'Invalid ISO timestamp: {e}')

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    warsaw = pytz.timezone('Europe/Warsaw')
    return dt.astimezone(warsaw).replace(tzinfo=None)


def get_station_queue_delta(station_code, since_ts):
    """
    Delta sync dla stanowiska. Zwraca:
    - all_ids: lista wszystkich zleceń aktualnie w kolejce (do wykrycia usunięć po stronie klienta)
    - changed: pełne DTO dla zleceń z updated_at > since_ts

    Klient po otrzymaniu:
    - usuwa ze swojego cache'u te których nie ma w all_ids
    - aktualizuje DTO dla zleceń z listy changed
    """
    status = STATION_STATUS_MAP.get(station_code)
    if not status:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    base = ProductionItem.query.filter(ProductionItem.current_status == status)

    all_ids = [
        row[0] for row in base.with_entities(ProductionItem.id)
        .order_by(
            func.coalesce(ProductionItem.priority_rank, 999999).asc(),
            ProductionItem.created_at.asc(),
        ).all()
    ]

    changed_items = base.options(
        joinedload(ProductionItem.order),
        joinedload(ProductionItem.configuration),
    ).filter(
        ProductionItem.updated_at > since_ts
    ).order_by(
        func.coalesce(ProductionItem.priority_rank, 999999).asc(),
        ProductionItem.created_at.asc(),
    ).all()

    return {
        'station_code': station_code,
        'server_time': get_local_now().isoformat(),
        'since_ts': since_ts.isoformat(),
        'all_ids': all_ids,
        'changed': [serialize_order(it, station_code=station_code) for it in changed_items],
    }
