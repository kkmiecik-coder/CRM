"""
Sygnał realtime przez Centrifugo — budzik dla klientów, NIE kanał danych.

Model: CRM zapisuje stan do bazy (kolejka `prod_print_queue`, tabele produkcji),
a potem wysyła krótki sygnał "coś się zmieniło" na kanał Centrifugo. Odbiorca
po sygnale robi to samo, co robił przy pollingu — woła REST API i pobiera stan.
Przez brokera NIGDY nie idzie ładunek użytkowy (ZPL, dane zamówień): restart
odbiorcy w trakcie transmisji oznaczałby cichą utratę zadania bez śladu w bazie.

Kanały:
    print:agent      — etap 1, budzi print-agenta na hubie biura
    station:<code>   — etap 2 (tablety), namespace przygotowany w configu brokera

Konfiguracja w `config/core.json` → sekcja `REALTIME`. Broker słucha wyłącznie
na 127.0.0.1 — publish leci po localhoście, a nginx wystawia publicznie tylko
ścieżkę połączeniową (`/realtime/connection/...`), nie server API.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import jwt
import requests
from flask import current_app

from modules.logging import get_structured_logger

logger = get_structured_logger('production.realtime')

CHANNEL_PRINT_AGENT = 'print:agent'

DEFAULT_API_URL = 'http://127.0.0.1:8091/api/publish'
DEFAULT_TOKEN_TTL_SECONDS = 3600
# Rozdzielone timeouty: connect krótki (localhost — albo odpowiada od razu, albo
# nie ma go wcale), read nieco dłuższy (broker pod obciążeniem).
DEFAULT_CONNECT_TIMEOUT = 0.3
DEFAULT_READ_TIMEOUT = 0.7

# Ile nieudanych publikacji z rzędu zanim znowu zawołamy Sentry. Pierwsza awaria
# leci od razu, kolejne co N — inaczej padnięty broker przy serii wydruków
# wygenerowałby setki identycznych zdarzeń.
_SENTRY_EVERY_N_FAILURES = 50

# Stan per-worker (gunicorn ma kilka procesów — każdy liczy swoje; to wystarcza,
# bo chodzi o rate-limit alertu, nie o dokładną statystykę).
_consecutive_failures = 0


def _config():
    return current_app.config.get('REALTIME', {}) or {}


def is_enabled():
    """Realtime jest opt-in — bez tego CRM zachowuje się dokładnie jak przed
    wdrożeniem pusha (kolejka + polling agenta)."""
    return bool(_config().get('enabled'))


def _api_url():
    return (_config().get('api_url') or DEFAULT_API_URL).strip()


def _api_key():
    return (_config().get('api_key') or '').strip()


def _hmac_secret():
    return (_config().get('token_hmac_secret') or '').strip()


def _timeout():
    cfg = _config()
    return (
        float(cfg.get('connect_timeout_seconds', DEFAULT_CONNECT_TIMEOUT)),
        float(cfg.get('read_timeout_seconds', DEFAULT_READ_TIMEOUT)),
    )


def sse_url():
    """Publiczny URL endpointu unidirectional SSE, podawany agentowi.
    Pusty string = agent wyprowadzi go sam z własnego `crm_url`."""
    return (_config().get('sse_url') or '').strip()


def _alert(message, extra):
    """Zgłasza awarię brokera do Sentry, z rate-limitem po stronie licznika.

    Dlaczego w ogóle alert: degradacja jest z założenia cicha — padnięte
    Centrifugo nie psuje niczego, tylko wydłuża czas do wydruku z ~50 ms do
    interwału pollingu. Bez alertu nikt by tego nie zauważył miesiącami.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        # sentry-sdk 2.x: new_scope(); 1.x: push_scope(). Trzymamy oba, bo wersja
        # SDK nie jest przypięta w requirements.txt.
        scope_factory = getattr(sentry_sdk, 'new_scope', None) or sentry_sdk.push_scope
        with scope_factory() as scope:
            for key, value in (extra or {}).items():
                scope.set_extra(key, value)
            scope.set_tag('subsystem', 'realtime')
            sentry_sdk.capture_message(message, level='error')
    except Exception:
        # Awaria alertowania nie może wywrócić akcji operatora — patrz publish().
        pass


def publish(channel, data):
    """
    Wysyła sygnał na kanał Centrifugo. Zwraca True/False, NIGDY nie rzuca.

    ==========================================================================
    UWAGA — ten try/except jest funkcją, a nie zaniedbaniem. Nie "sprzątać".
    ==========================================================================
    `publish()` jest wołany synchronicznie w trakcie obsługi żądania operatora
    (kliknięcie "Drukuj etykietę"). Sygnał jest OPCJONALNY: zadanie jest już
    zacommitowane w `prod_print_queue`, a odbiorca i tak pollinguje jako siatka
    bezpieczeństwa — więc brak sygnału opóźnia wydruk, ale niczego nie gubi.

    Gdyby wyjątek propagował, awaria brokera zamieniłaby się w awarię CRM-a.
    Gdyby timeout był długi (albo domyślny — czyli żaden), ZAWIESZONE (nie
    padnięte — zawieszone, czyli przyjmujące TCP i milczące) Centrifugo
    zawiesiłoby każde kliknięcie operatora na czas tego timeoutu.
    Stąd: krótki timeout + łykanie wszystkiego + log.
    """
    global _consecutive_failures

    if not is_enabled():
        return False

    api_key = _api_key()
    if not api_key:
        logger.warning("Realtime włączony, ale brak REALTIME.api_key — pomijam publish",
                       extra={'channel': channel})
        return False

    try:
        resp = requests.post(
            _api_url(),
            json={'channel': channel, 'data': data},
            headers={'X-API-Key': api_key, 'Content-Type': 'application/json'},
            timeout=_timeout(),
        )
        body = resp.json() if resp.content else {}
        # Centrifugo zwraca HTTP 200 również dla błędów logicznych (np. kanał
        # spoza zdefiniowanego namespace'u) — błąd siedzi w ciele odpowiedzi.
        if resp.status_code != 200 or 'error' in body:
            raise RuntimeError(f"HTTP {resp.status_code}, body={body}")
    except Exception as e:
        _consecutive_failures += 1
        logger.warning("Publikacja sygnału realtime nieudana (degradacja do pollingu)",
                       extra={'channel': channel, 'error': str(e)[:300],
                              'consecutive_failures': _consecutive_failures})
        if _consecutive_failures == 1 or _consecutive_failures % _SENTRY_EVERY_N_FAILURES == 0:
            _alert(
                "Centrifugo nie przyjmuje publikacji — wydruki spadły na polling",
                {'channel': channel, 'error': str(e)[:300],
                 'consecutive_failures': _consecutive_failures},
            )
        return False

    if _consecutive_failures:
        logger.info("Realtime znowu odpowiada",
                    extra={'channel': channel, 'after_failures': _consecutive_failures})
        _consecutive_failures = 0
    return True


def publish_print_signal(job_count):
    """Budzi print-agenta: 'są nowe zadania, przyjdź po nie'.

    Payload celowo minimalny — agent po sygnale i tak woła
    GET /api/print-agent/jobs i to ono jest źródłem prawdy.
    """
    return publish(CHANNEL_PRINT_AGENT, {'kind': 'print', 'count': int(job_count or 0)})


def issue_connection_token(subject, channels, ttl_seconds=None):
    """
    Wystawia krótkotrwały JWT do połączenia z Centrifugo.

    Claim `channels` = subskrypcje server-side. Klient unidirectional (SSE) nie
    umie subskrybować sam, więc kanały muszą przyjechać w tokenie.

    Returns: (token, ttl_seconds)
    Raises: RuntimeError gdy brak sekretu w konfiguracji.
    """
    secret = _hmac_secret()
    if not secret:
        raise RuntimeError(
            "REALTIME.token_hmac_secret nie jest skonfigurowany w config/core.json "
            "(musi być identyczny z client.token.hmac_secret_key w configu Centrifugo)."
        )
    ttl = int(ttl_seconds or _config().get('token_ttl_seconds') or DEFAULT_TOKEN_TTL_SECONDS)
    now = datetime.utcnow()
    payload = {
        'sub': str(subject),
        'iat': now,
        'exp': now + timedelta(seconds=ttl),
        'channels': list(channels),
    }
    return jwt.encode(payload, secret, algorithm='HS256'), ttl
