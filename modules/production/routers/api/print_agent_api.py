"""
Endpointy dla print-agenta (skrypt na hubie biura).
Autoryzacja: nagłówek `Authorization: Bearer <LABEL_PRINTER_AGENT_TOKEN>`.
NIE wymaga sesji webowej.

Wzorzec: agent budzi się na sygnał push (Centrifugo, kanał `print:agent`),
woła GET /api/print-agent/jobs?limit=10&printers=<drukarka>, drukuje lokalnie ZPL z pola
zpl_payload, potem POST /api/print-agent/ack z listą wyników. Każda drukarka ma własną
kolejkę (etap 4 logistyki: 'etykiety' 60x40 i 'wysylka' 100x150); agent sprzed etapu 4
nie podaje parametru i dostaje wyłącznie 'etykiety'. Polling został
jako siatka bezpieczeństwa — 60 s gdy kanał push żyje, 10 s gdy padł.
Token do połączenia z brokerem agent bierze z GET /realtime-token.

TTL: pending starsze niż 1h są oznaczane jako 'expired' i nigdy nie drukowane
(operator powinien kliknąć ponownie). Sprzątanie jest throttlowane — patrz
_expire_stale_pending().
"""
import hmac
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import NoSuchColumnError, OperationalError, ResourceClosedError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.production.services import realtime_service
from modules.production.services.label_print_service import (
    rollback_label_count_for_jobs,
)

logger = get_structured_logger('production.print_agent')

print_agent_bp = Blueprint('print_agent', __name__)

_AGENT_JOB_TTL = timedelta(hours=1)

# Minimalny odstęp między przebiegami sprzątania wygasłych zadań.
# None = jeszcze nie sprzątaliśmy w tym workerze. Celowo None, a nie 0.0:
# time.monotonic() bywa liczone od startu procesu (tak jest na macOS), więc
# zero jako "dawno temu" oznaczałoby, że świeży worker przez pierwszą minutę
# nie sprząta w ogóle.
_EXPIRE_THROTTLE_SECONDS = 60
_last_expire_at = None

# Wyjątki które wskazują na padnięte połączenie z poola — agent puka co 5s,
# więc co jakiś czas trafia na martwy socket mimo pool_pre_ping.
_TRANSIENT_DB_ERRORS = (NoSuchColumnError, OperationalError, ResourceClosedError)


def _query_agent_token():
    row = ProductionConfig.query.filter_by(config_key='LABEL_PRINTER_AGENT_TOKEN').first()
    return (row.config_value or '').strip() if row else ''


def _get_agent_token():
    """Pobiera token agenta z prod_config; przy padniętym połączeniu robi
    rollback+invalidate i ponawia raz. Brak tokena = '' (agent dostanie 401)."""
    try:
        return _query_agent_token()
    except _TRANSIENT_DB_ERRORS as e:
        logger.warning("Padnięte połączenie podczas odczytu tokena agenta — retry",
                       extra={'error_type': type(e).__name__})
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            db.session.invalidate()
        except Exception:
            pass
        try:
            return _query_agent_token()
        except Exception as e2:
            logger.error("Retry tokena agenta nie powiódł się",
                         extra={'error_type': type(e2).__name__, 'error': str(e2)})
            return ''


def require_agent_token(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        prefix = 'Bearer '
        if not header.startswith(prefix):
            return jsonify({'error': 'unauthorized', 'reason': 'missing bearer'}), 401
        token = header[len(prefix):].strip()
        expected = _get_agent_token()
        # (B-5, przegląd końcowy 4.10) Porównanie stałoczasowe, jak X-Cron-Secret; na bajtach, bo
        # compare_digest na str przyjmuje tylko ASCII (token spoza ASCII = 401, nie 500).
        if not expected or not token or not hmac.compare_digest(token.encode('utf-8'), expected.encode('utf-8')):
            return jsonify({'error': 'unauthorized', 'reason': 'invalid token'}), 401
        return view(*args, **kwargs)
    return wrapper


def _zmien_oczekujace(job_id, zmiany):
    """UPDATE zadania tylko gdy wciąż `pending`; True, gdy wiersz się zmienił."""
    tabela = LabelPrintJob.__table__
    wynik = db.session.execute(tabela.update()
                               .where(tabela.c.id == job_id, tabela.c.status == LabelPrintJob.STATUS_PENDING)
                               .values(**zmiany))
    return wynik.rowcount == 1


def _expire_stale_pending(force=False):
    """Oznacza pending starsze niż _AGENT_JOB_TTL jako expired.

    Throttlowane do raz na _EXPIRE_THROTTLE_SECONDS: TTL to godzina, więc
    sprzątanie przy każdym GET /jobs było marnotrawstwem już przy pollingu co
    10 s, a przy sygnale push kadencja przestała być przewidywalna — seria
    wydruków potrafi zawołać /jobs kilkanaście razy w minutę.

    Licznik jest per-worker gunicorna. To wystarcza: kilku workerów oznacza
    kilka przebiegów na minutę zamiast jednego, a sam UPDATE jest idempotentny.
    """
    global _last_expire_at
    now = time.monotonic()
    if not force and _last_expire_at is not None and (now - _last_expire_at) < _EXPIRE_THROTTLE_SECONDS:
        return 0
    _last_expire_at = now

    cutoff = datetime.utcnow() - _AGENT_JOB_TTL
    # Wybieramy PRZED aktualizacją, bo licznik wydrukowanych etykiet trzeba
    # cofnąć o te zadania — a po bulk UPDATE nie wiadomo już, które to były.
    wygasajace = (LabelPrintJob.query
                  .filter(LabelPrintJob.status == 'pending',
                          LabelPrintJob.requested_at < cutoff)
                  .order_by(LabelPrintJob.id)   # stała kolejność zapisów jak w ACK — bez 1213 między nimi
                  .all())
    # (M3 po re-review) Zapis warunkowy: drugi worker (albo ACK) mógł zmienić zadanie między odczytem a zapisem —
    # cofamy wydruk tylko za zadania, które naprawdę przestawiliśmy z `pending`.
    wygasajace = [job for job in wygasajace
                  if _zmien_oczekujace(job.id, {'status': 'expired',
                                                'error_message': f'TTL: pending starsze niż {_AGENT_JOB_TTL}'})]
    expired_count = len(wygasajace)
    if expired_count:
        rollback_label_count_for_jobs(wygasajace)
        db.session.commit()
        logger.info("Expired stale print jobs", extra={'count': expired_count})
    return expired_count


def _drukarki_z_zapytania(surowe):
    """`?printers=etykiety,wysylka` → krotka znanych nazw w kolejności podania.

    Brak parametru = tylko dotychczasowa drukarka: agent sprzed etapu 4 nie zna
    parametru, a etykieta 100x150 wysłana na drukarkę 60x40 to zmarnowane etykiety.
    Parametr podany, ale pusty albo z samymi nieznanymi nazwami = nic (agent z
    literówką w config.ini nie może przejąć cudzej kolejki).
    """
    if surowe is None:
        return (LabelPrintJob.DRUKARKA_ETYKIETY,)
    nazwy = []
    for nazwa in str(surowe).split(','):
        nazwa = nazwa.strip().lower()
        if nazwa in LabelPrintJob.DRUKARKI and nazwa not in nazwy:
            nazwy.append(nazwa)
    return tuple(nazwy)


@print_agent_bp.route('/jobs', methods=['GET'])
@require_agent_token
def list_jobs():
    """
    GET /api/print-agent/jobs?limit=10&printers=etykiety,wysylka
    Zwraca pending zadania ZPL wskazanych drukarek (FIFO). Bez `printers` —
    tylko 'etykiety' (zgodność ze starym agentem). Przy okazji oznacza zadania
    starsze niż 1h jako expired.
    """
    _expire_stale_pending()

    try:
        limit = max(1, min(int(request.args.get('limit', 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    drukarki = _drukarki_z_zapytania(request.args.get('printers'))
    if not drukarki:
        return jsonify({'jobs': [], 'count': 0}), 200

    jobs = (LabelPrintJob.query
            .filter(LabelPrintJob.status == 'pending',
                    LabelPrintJob.printer.in_(drukarki))
            # id jako drugi klucz: zadania z tej samej milisekundy wychodzą w kolejności wstawienia
            .order_by(LabelPrintJob.requested_at.asc(), LabelPrintJob.id.asc())
            .limit(limit)
            .all())

    return jsonify({
        'jobs': [
            {
                'id': j.id,
                'printer': j.printer,
                'short_product_id': j.short_product_id,
                'baselinker_order_id': j.baselinker_order_id,
                'station_code': j.station_code,
                'zpl_payload': j.zpl_payload,
                'requested_at': j.requested_at.isoformat() if j.requested_at else None,
            }
            for j in jobs
        ],
        'count': len(jobs),
    }), 200


@print_agent_bp.route('/ack', methods=['POST'])
@require_agent_token
def ack_jobs():
    """
    POST /api/print-agent/ack
    Body: {"results": [{"id": 1, "success": true} | {"id": 2, "success": false, "error": "..."}]}
    Aktualizuje status zadań w kolejce.
    """
    data = request.get_json(silent=True) or {}
    results = data.get('results') or []
    if not isinstance(results, list):
        return jsonify({'error': 'invalid_results', 'reason': 'expected list'}), 400

    # Zadania przestawiamy rosnąco po id (jak _expire_stale_pending) — dwa zapisy tych samych wierszy w różnej
    # kolejności mogłyby się zakleszczyć (1213). Powtórzone id: liczy się pierwszy wynik.
    wyniki = {}
    for r in results:
        try:
            job_id = int(r.get('id'))
        except (TypeError, ValueError, AttributeError):
            continue
        wyniki.setdefault(job_id, r)

    updated = 0
    nieudane = []
    for job_id in sorted(wyniki):
        r = wyniki[job_id]
        success = bool(r.get('success'))
        error = (r.get('error') or '')[:1000] if not success else None
        # (M3 po re-review) Zapis warunkowy na `status = 'pending'` zamiast odczytu i zapisu obiektu: zadanie mógł
        # w międzyczasie wygasić inny worker (_expire_stale_pending, throttling per worker) i cofnąć już wydruk —
        # drugi raz go nie cofamy ani nie nadpisujemy statusu.
        if success:
            zmiany = {'status': 'printed', 'printed_at': datetime.utcnow()}
        else:
            zmiany = {'status': 'failed', 'error_message': error}
        if not _zmien_oczekujace(job_id, zmiany):
            continue
        if not success:
            nieudane.append(job_id)
        updated += 1

    # Etykieta, która nie wyszła, nie może zostawić pozycji oznaczonej jako
    # wydrukowana — inaczej panel kafelków pokaże operatorowi „jest" dla czegoś,
    # czego nie znajdzie na paczce.
    if nieudane:
        rollback_label_count_for_jobs(LabelPrintJob.query.filter(LabelPrintJob.id.in_(nieudane))
                                      .populate_existing().all())

    if updated:
        db.session.commit()
        logger.info("Print agent ACK processed", extra={'updated': updated})

    return jsonify({'updated': updated}), 200


@print_agent_bp.route('/realtime-token', methods=['GET'])
@require_agent_token
def realtime_token():
    """
    GET /api/print-agent/realtime-token

    Wymienia stały Bearer agenta (LABEL_PRINTER_AGENT_TOKEN z prod_config) na
    krótkotrwały JWT do Centrifugo. Dzięki temu na hubie biura nie ląduje żaden
    dodatkowy sekret — agent ma dalej jedno hasło, to samo co do REST API.

    Zwraca 503 gdy realtime jest wyłączony albo nieskonfigurowany. Agent traktuje
    to jako "brak pusha" i spada na polling — bez błędu, bez retry-spamu.

    Response 200:
        {"enabled": true, "token": "<JWT>", "channel": "print:agent",
         "sse_url": "https://crm.woodpower.pl/realtime/connection/uni_sse",
         "expires_in": 3600}
    """
    if not realtime_service.is_enabled():
        return jsonify({'enabled': False, 'reason': 'realtime disabled'}), 503

    try:
        token, ttl = realtime_service.issue_connection_token(
            'print-agent', [realtime_service.CHANNEL_PRINT_AGENT],
        )
    except RuntimeError as e:
        logger.error("Nie udało się wystawić tokena realtime dla agenta",
                     extra={'error': str(e)})
        return jsonify({'enabled': False, 'reason': 'misconfigured'}), 503

    return jsonify({
        'enabled': True,
        'token': token,
        'channel': realtime_service.CHANNEL_PRINT_AGENT,
        'sse_url': realtime_service.sse_url(),
        'expires_in': ttl,
    }), 200
