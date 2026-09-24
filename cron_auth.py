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
- ani sekret, ani podana wartość nie trafiają do logów ani do odpowiedzi;
- brak sekretu w konfiguracji to alarm CRITICAL, czyli zdarzenie w Sentry
  (sentry_config.py: LoggingIntegration robi zdarzenia dopiero od CRITICAL).
  Odpowiedź 500 nie jest wyjątkiem, więc integracja Flaska jej nie zgłasza,
  a cron z `curl --silent` bez -f kończy się kodem 0. Bez alarmu
  synchronizacja BaseLinkera, statusy raportów i domykanie sesji pracowników
  stałyby po cichu całymi dniami.
"""

import hmac
import time
from functools import wraps

from flask import current_app, jsonify, request

from modules.logging import get_structured_logger

CRON_SECRET_CONFIG_KEY = 'PRODUCTION_CRON_SECRET'
CRON_SECRET_HEADER = 'X-Cron-Secret'

logger = get_structured_logger('cron_auth')

# Alarm CRITICAL o braku sekretu najwyżej raz na ten odstęp, osobno dla
# każdego endpointu w każdym procesie (workerze gunicorna). Pierwsze wywołanie
# alarmuje od razu, kolejne w odstępie idą jako ERROR (plik logu, bez Sentry).
# Po co limit: cron woła endpointy co kilka minut, a przy braku sekretu może je
# wołać także każdy z internetu. Bez limitu każde wywołanie byłoby zdarzeniem
# Sentry i zjadałoby miesięczny limit, zasłaniając inne błędy.
ODSTEP_ALARMU_S = 3600

# Zegar podmieniany w testach; monotoniczny, bo nie cofa się przy zmianie czasu.
_teraz = time.monotonic

# endpoint -> chwila ostatniego alarmu (per proces). Wyścig dwóch wątków daje
# co najwyżej jeden alarm więcej, więc bez blokady.
_ostatni_alarm = {}


def _czas_na_alarm(endpoint):
    """True, gdy dla tego endpointu nie było alarmu od ODSTEP_ALARMU_S sekund."""
    teraz = _teraz()
    poprzedni = _ostatni_alarm.get(endpoint)
    if poprzedni is not None and teraz - poprzedni < ODSTEP_ALARMU_S:
        return False
    _ostatni_alarm[endpoint] = teraz
    return True


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

    - brak sekretu w konfiguracji -> 500 (błąd serwera, nie klienta) i alarm
      CRITICAL do Sentry, najwyżej raz na ODSTEP_ALARMU_S na endpoint i proces,
    - zły albo brakujący nagłówek -> 403.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        oczekiwany = skonfigurowany_sekret_crona(current_app.config)
        if oczekiwany is None:
            if _czas_na_alarm(request.endpoint):
                # Bez IP klienta: treść ma być stała, żeby Sentry grupowało
                # zdarzenia w jedno zgłoszenie na endpoint. Adres nie pomaga
                # w naprawie, bo winna jest konfiguracja serwera, nie wołający.
                logger.critical("CRON: brak PRODUCTION_CRON_SECRET w config/core.json - endpoint "
                                "zamkniety, zadanie cykliczne NIE wykonuje sie",
                                endpoint=request.endpoint)
            else:
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
