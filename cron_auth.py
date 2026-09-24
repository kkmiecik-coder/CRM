"""
Autoryzacja endpointów wołanych cronem hostingu (nagłówek X-Cron-Secret).

W aplikacji nie ma schedulera: pracę cykliczną wołają wpisy crontaba przez
HTTP (CLAUDE.md, sekcja „Zadania cykliczne"). Cron nie ma sesji, więc zamiast
@login_required endpoint sprawdza wspólny sekret z config/core.json, pole
PRODUCTION_CRON_SECRET.

Jeden dekorator dla wszystkich takich endpointów. Wcześniej były dwie kopie
(produkcja i raporty) i obie miały wartość zapasową wpisaną w publiczne repo:
brak pola w core.json OTWIERAŁ dostęp dla każdego, kto przeczytał kod.

Zasady (pilnuje ich tests/test_sekret_crona.py):
- brak albo pusta wartość w konfiguracji ZAMYKA endpoint (500), nigdy go nie
  otwiera; wartości zapasowej w kodzie nie ma;
- porównanie stałoczasowe (hmac.compare_digest) na bajtach UTF-8 — na napisach
  compare_digest rzuca TypeError dla znaków spoza ASCII, a nagłówek przychodzi
  od kogokolwiek;
- ani sekret, ani podana wartość nie trafiają do logów ani do odpowiedzi.
"""

import hmac
from functools import wraps

from flask import current_app, jsonify, request

from modules.logging import get_structured_logger

CRON_SECRET_CONFIG_KEY = 'PRODUCTION_CRON_SECRET'
CRON_SECRET_HEADER = 'X-Cron-Secret'

logger = get_structured_logger('cron_auth')


def skonfigurowany_sekret_crona(config):
    """Sekret z konfiguracji albo None, gdy go brak, jest pusty lub nie jest tekstem."""
    wartosc = config.get(CRON_SECRET_CONFIG_KEY)
    if not isinstance(wartosc, str) or not wartosc.strip():
        return None
    return wartosc


def sekret_crona_poprawny(podany, oczekiwany):
    """Stałoczasowe porównanie; brak którejkolwiek strony = odmowa."""
    if not podany or not oczekiwany:
        return False
    return hmac.compare_digest(str(podany).encode('utf-8'),
                               str(oczekiwany).encode('utf-8'))


def cron_secret_required(f):
    """
    Dekorator endpointu CRON: wymaga nagłówka X-Cron-Secret zgodnego
    z PRODUCTION_CRON_SECRET z config/core.json.

    - brak sekretu w konfiguracji -> 500 (błąd serwera, nie klienta; log ERROR),
    - zły albo brakujący nagłówek -> 403.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        oczekiwany = skonfigurowany_sekret_crona(current_app.config)
        if oczekiwany is None:
            logger.error("CRON: brak PRODUCTION_CRON_SECRET w config/core.json - endpoint zamkniety",
                         client_ip=request.remote_addr,
                         endpoint=request.endpoint)
            return jsonify({'success': False,
                            'error': 'Sekret CRON nie jest skonfigurowany na serwerze'}), 500

        podany = request.headers.get(CRON_SECRET_HEADER)
        if not sekret_crona_poprawny(podany, oczekiwany):
            logger.warning("CRON: Nieprawidłowy secret",
                           provided_secret_length=len(podany) if podany else 0,
                           client_ip=request.remote_addr,
                           endpoint=request.endpoint)
            return jsonify({'success': False, 'error': 'Nieprawidłowy CRON secret'}), 403

        return f(*args, **kwargs)
    return decorated_function
