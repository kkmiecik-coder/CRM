#!/usr/bin/env python3
"""
Print agent — drukuje zadania ZPL z kolejki CRM na drukarce w LAN.

Uruchamiany 24/7 na hubie biura, pracuje tylko w godzinach pracy
(domyślnie pn-pt + sb 5:30-15:30).

Jak dostaje zadania:
  1. Sygnał push — otwarte połączenie SSE do Centrifugo (kanał `print:agent`).
     Po sygnale agent natychmiast woła GET /jobs. Etykieta wyjeżdża w ~50 ms
     od kliknięcia operatora zamiast średnio 5 s.
  2. Polling — siatka bezpieczeństwa, która była tu od początku i zostaje.
     Co `push_idle_interval_seconds` (60 s) gdy kanał push żyje, co
     `interval_seconds` (10 s) gdy padł. Kolejka w bazie jest źródłem prawdy;
     sygnał tylko usuwa czekanie.

Przez brokera NIE idą żadne dane — sam budzik. ZPL zawsze przyjeżdża przez
REST z /jobs, żeby restart agenta w trakcie nie gubił etykiety po cichu.

Uruchomienie: `python print_agent.py` (lub `start.bat` na Windowsie).
Konfiguracja: `config.ini` (skopiuj z `config.example.ini`).

Uwaga: stdlib only (urllib + socket + configparser). Świadomie nie używamy
`requests` ani SDK Centrifugo — agent ma działać po `python print_agent.py`
na świeżym Pythonie. Dlatego transportem push jest unidirectional SSE, które
jest zwykłym POST-em i czytaniem linii. `colorama` jest opcjonalna.
"""
import configparser
import json
import logging
import os
import random
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, time as dtime, timezone
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from urllib import request as urlreq
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

try:
    import colorama
    colorama.init()
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False


class C:
    RESET = '\033[0m'
    DIM = '\033[2m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    CYAN = '\033[36m'
    BOLD = '\033[1m'


def ts():
    return datetime.now().strftime('[%H:%M:%S]')


def info(msg):
    print(f"{C.DIM}{ts()}{C.RESET} {msg}", flush=True)


def ok(msg):
    print(f"{C.DIM}{ts()}{C.RESET} {C.GREEN}{msg}{C.RESET}", flush=True)


def warn(msg):
    print(f"{C.DIM}{ts()}{C.RESET} {C.YELLOW}{msg}{C.RESET}", flush=True)


def err(msg):
    print(f"{C.DIM}{ts()}{C.RESET} {C.RED}{msg}{C.RESET}", flush=True, file=sys.stderr)


# === Error log file ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG_PATH = os.path.join(SCRIPT_DIR, 'print_agent_errors.log')
err_logger = logging.getLogger('print_agent.errors')
err_logger.setLevel(logging.ERROR)
_handler = logging.FileHandler(ERROR_LOG_PATH, encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
err_logger.addHandler(_handler)


def log_error(msg, exc=None):
    """Loguj błąd do konsoli + pliku."""
    err(msg)
    if exc:
        err_logger.error(f"{msg}\n{traceback.format_exc()}")
    else:
        err_logger.error(msg)


# === Konsola Windows: QuickEdit ===
def disable_console_quick_edit():
    """Wyłącza tryb QuickEdit w konsoli Windows. Zwraca opis wyniku.

    ===========================================================================
    TO NIE JEST KOSMETYKA — bez tego agent potrafi zamilknąć na godziny.
    ===========================================================================
    W cmd.exe QuickEdit jest domyślnie WŁĄCZONY. Przypadkowe kliknięcie w oknie
    (albo samo przeciągnięcie myszą) przechodzi w tryb zaznaczania i
    ZAWIESZA PROCES przy najbliższym zapisie na stdout — do czasu wciśnięcia
    Esc lub Enter. Proces nie pada, nie loguje, nie odpytuje serwera; system
    widzi go jako żywy, połączenia TCP zostają otwarte.

    Objaw z produkcji 12.08.2026: agent stanął po `POST /connection/uni_sse`,
    a przed `GET /jobs` — czyli dokładnie na instrukcji `info("Otwarto kanał
    push")`. Zero wpisów w logu błędów, broker cały czas widział klienta jako
    podłączonego, 51 etykiet czekało w kolejce, pomagał tylko restart.

    Dla agenta pracującego 24/7 w otwartym oknie na hubie to nie jest scenariusz
    teoretyczny — to kwestia czasu.
    """
    if os.name != 'nt':
        return 'pominięte (nie Windows)'
    try:
        import ctypes
        from ctypes import wintypes

        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_INSERT_MODE = 0x0020
        ENABLE_EXTENDED_FLAGS = 0x0080

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        uchwyt = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if uchwyt in (0, -1, None):
            return 'nie udało się (brak uchwytu konsoli)'

        tryb = wintypes.DWORD()
        if not kernel32.GetConsoleMode(uchwyt, ctypes.byref(tryb)):
            # Brak prawdziwej konsoli (usługa, przekierowanie) = brak problemu.
            return 'pominięte (brak konsoli — stdin przekierowany)'

        if not tryb.value & ENABLE_QUICK_EDIT_MODE:
            return 'już był wyłączony'

        # ENABLE_EXTENDED_FLAGS trzeba ustawić RAZEM ze zmianą, inaczej Windows
        # zignoruje wyczyszczenie bitu QuickEdit.
        nowy = (tryb.value & ~ENABLE_QUICK_EDIT_MODE & ~ENABLE_INSERT_MODE) | ENABLE_EXTENDED_FLAGS
        if not kernel32.SetConsoleMode(uchwyt, nowy):
            return f'nie udało się (SetConsoleMode, błąd {ctypes.get_last_error()})'
        return 'WYŁĄCZONY (kliknięcie w oknie nie zamrozi już agenta)'
    except Exception as e:
        return f'nie udało się ({type(e).__name__}: {e})'


# === Czujka zastoju ===
#
# Wątek-czujka pilnuje, czy pętla główna się rusza. Pisze WYŁĄCZNIE do pliku,
# nigdy na konsolę — bo najczęstsza przyczyna zastoju (QuickEdit, patrz
# disable_console_quick_edit) blokuje właśnie zapis na konsolę i uciszyłaby
# także czujkę. Czujka nie potrafi odwiesić pętli; jej zadaniem jest zamienić
# „agent zamilkł bez śladu" w „agent zamilkł o 15:52:33, oto wpis w logu".
_ostatni_postep = time.monotonic()
_zastoj_zgloszony = False
# Po tylu sekundach bez obiegu pętli uznajemy zastój. Najdłuższy normalny obieg
# to okno pollingu (60 s) plus zapas na ping brokera — 180 s daje margines,
# żeby nie krzyczeć przy zwykłej zadyszce sieci.
_ZASTOJ_PO_SEKUNDACH = 180
_CZUJKA_CO_SEKUND = 30


def _oznacz_postep():
    """Wołane na początku każdego obiegu pętli głównej."""
    global _ostatni_postep, _zastoj_zgloszony
    _ostatni_postep = time.monotonic()
    if _zastoj_zgloszony:
        err_logger.error("Pętla główna ruszyła z powrotem po zastoju")
        _zastoj_zgloszony = False


def _czujka_zastoju():
    global _zastoj_zgloszony
    while True:
        time.sleep(_CZUJKA_CO_SEKUND)
        cisza = time.monotonic() - _ostatni_postep
        if cisza > _ZASTOJ_PO_SEKUNDACH and not _zastoj_zgloszony:
            _zastoj_zgloszony = True
            err_logger.error(
                f"ZASTÓJ: pętla główna nie ruszyła się od {int(cisza)}s. "
                "Najczęstsza przyczyna na Windowsie to zaznaczenie tekstu w oknie "
                "konsoli (QuickEdit) — wciśnij Esc w oknie agenta. Jeśli to nie "
                "pomoże, zrestartuj agenta i wyślij ten log."
            )


def start_czujki():
    watek = threading.Thread(target=_czujka_zastoju, name='czujka-zastoju', daemon=True)
    watek.start()
    return watek


# === Config ===
def load_config(path):
    cp = configparser.ConfigParser()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Brak pliku konfiguracji: {path}. "
            "Skopiuj config.example.ini do config.ini i ustaw token."
        )
    cp.read(path, encoding='utf-8')

    # config.ini nie jest w gicie — na hubie stoi wersja sprzed pusha i nikt jej
    # nie zaktualizuje przy `git pull`. Brakujące sekcje dorabiamy w locie, żeby
    # wszystkie nowe klucze zadziałały z fallbacków (fallback= w configparser
    # ratuje brakującą OPCJĘ, ale przy brakującej SEKCJI leci NoSectionError).
    for section in ('polling', 'realtime'):
        if not cp.has_section(section):
            cp.add_section(section)

    return {
        'crm_url': cp.get('crm', 'url').rstrip('/'),
        'token': cp.get('crm', 'token'),
        'jobs_limit': cp.getint('crm', 'jobs_limit', fallback=10),
        'request_timeout': cp.getint('crm', 'request_timeout_seconds', fallback=10),
        'printer_ip': cp.get('printer', 'ip'),
        'printer_port': cp.getint('printer', 'port', fallback=9100),
        'printer_timeout': cp.getint('printer', 'send_timeout_seconds', fallback=15),
        'poll_interval': cp.getint('polling', 'interval_seconds', fallback=10),
        'push_idle_interval': cp.getint('polling', 'push_idle_interval_seconds', fallback=60),
        'idle_check_interval': cp.getint('polling', 'idle_check_interval_seconds', fallback=60),
        'realtime_enabled': cp.getboolean('realtime', 'enabled', fallback=True),
        'realtime_sse_url': cp.get('realtime', 'sse_url', fallback='').strip(),
        'workdays_start': dtime.fromisoformat(cp.get('schedule', 'workdays_start')),
        'workdays_end': dtime.fromisoformat(cp.get('schedule', 'workdays_end')),
        'saturday_start': dtime.fromisoformat(cp.get('schedule', 'saturday_start')),
        'saturday_end': dtime.fromisoformat(cp.get('schedule', 'saturday_end')),
    }


# === Schedule ===
def in_working_hours(cfg, now=None):
    """True jeśli teraz jest okno pracy (pn-pt = workdays, sb = saturday)."""
    now = now or datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    t = now.time()
    if 0 <= weekday <= 4:
        return cfg['workdays_start'] <= t <= cfg['workdays_end']
    if weekday == 5:
        return cfg['saturday_start'] <= t <= cfg['saturday_end']
    return False


# === HTTP to CRM ===
def crm_request(method, url, token, *, body=None, timeout=10):
    headers = {'Authorization': f'Bearer {token}'}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urlreq.Request(url, data=data, headers=headers, method=method)
    with urlreq.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw else {}


def fetch_jobs(cfg):
    url = f"{cfg['crm_url']}/api/print-agent/jobs?limit={cfg['jobs_limit']}"
    return crm_request('GET', url, cfg['token'], timeout=cfg['request_timeout'])


def ack_jobs(cfg, results):
    url = f"{cfg['crm_url']}/api/print-agent/ack"
    return crm_request('POST', url, cfg['token'], body={'results': results}, timeout=cfg['request_timeout'])


# === Realtime (Centrifugo, unidirectional SSE) ===
#
# Brak pinga przez tyle sekund = połączenie martwe. Centrifugo domyślnie pinguje
# co 25 s, więc 40 s daje zapas na zadyszkę sieci, a jednocześnie wyłapuje
# "zawieszone" połączenie (TCP żyje, ruchu nie ma) w rozsądnym czasie.
SSE_PING_TIMEOUT_SECONDS = 40
# Limit na SAMO nawiązanie połączenia — celowo osobny i krótki. Broker, który
# przyjmuje TCP i milczy (zawieszony, a nie padnięty), zablokowałby inaczej całą
# pętlę agenta na czas limitu ciszy, a razem z nią zapasowy polling. Czekanie na
# push nigdy nie może opóźnić drogi awaryjnej.
SSE_CONNECT_TIMEOUT_SECONDS = 5
# Drabinka ponawiania połączenia z brokerem (sekundy). Po ostatnim stopniu
# zostajemy na nim — czyli próba co minutę, bez końca.
SSE_RECONNECT_LADDER = (1, 2, 5, 10, 15, 30, 60)
SSE_RECONNECT_MAX_SECONDS = SSE_RECONNECT_LADDER[-1]
# Co która nieudana próba połączenia trafia do logu (poza pierwszą, zawsze głośną).
_CONNECT_LOG_EVERY = 30
# Ile porcji po `jobs_limit` wolno pobrać w jednym cyklu, zanim oddamy sterowanie
# pętli głównej. Bezpiecznik przed zapętleniem na kolejce, która rośnie szybciej,
# niż drukarka nadąża — przy limicie 10 to 200 etykiet na cykl, czyli grubo
# ponad dzienny wolumen.
_MAX_BATCHES_PER_CYCLE = 20


def fetch_realtime_config(cfg, quiet=False):
    """
    Wymienia stały token agenta na krótkotrwały JWT do Centrifugo.

    Zwraca dict {'token', 'sse_url'} albo None, gdy push jest niedostępny
    (wyłączony w CRM, nieskonfigurowany, sieć padła). None NIE jest błędem —
    agent po prostu leci dalej na pollingu.

    `quiet` wycisza log przy powtarzających się awariach — patrz connect_push().
    """
    url = f"{cfg['crm_url']}/api/print-agent/realtime-token"
    try:
        data = crm_request('GET', url, cfg['token'], timeout=cfg['request_timeout'])
    except HTTPError as e:
        if e.code == 503:
            return None  # realtime wyłączony po stronie CRM — cicho, to nie awaria
        if not quiet:
            log_error(f"Nie udało się pobrać tokena realtime: HTTP {e.code} {e.reason}", exc=e)
        return None
    except (URLError, TimeoutError, OSError, ValueError) as e:
        if not quiet:
            log_error(f"Nie udało się pobrać tokena realtime: {e}", exc=e)
        return None

    if not data.get('enabled') or not data.get('token'):
        return None

    # Kolejność: override z config.ini (awaryjna zmiana infry bez deployu CRM),
    # potem to co poda CRM, na końcu wyprowadzone z crm_url.
    sse_url = (cfg['realtime_sse_url'] or data.get('sse_url') or '').strip()
    if not sse_url:
        sse_url = f"{cfg['crm_url']}/realtime/connection/uni_sse"
    return {'token': data['token'], 'sse_url': sse_url}


class SseStream:
    """Otwarty strumień SSE razem z połączeniem, żeby dało się je domknąć.

    Używamy `http.client` zamiast `urlopen`, bo tylko tak mamy dostęp do gniazda
    i możemy sterować limitem czasu ODDZIELNIE dla nawiązania połączenia i dla
    czekania na dane. `urlopen` przyjmuje jeden timeout na jedno i drugie,
    a to są tu dwie zupełnie różne sprawy.

    UWAGA: gniazdo trzeba zapamiętać SAMEMU, przed `getresponse()`. Odpowiedź
    bez `Content-Length` (a taki jest strumień SSE) trwa do zamknięcia
    połączenia, więc http.client „przekazuje gniazdo odpowiedzi” i ustawia
    `conn.sock = None`. Sam deskryptor żyje dalej, bo trzyma go plik zrobiony
    przez `makefile()` — ale `conn.sock` jest już nie do użycia. Sięganie po
    limit czasu przez `conn.sock` po cichu nic nie robi i gniazdo zostaje
    z limitem od nawiązywania połączenia (5 s), czyli krótszym niż odstęp
    między pingami brokera (25 s) — połączenie rozpada się co pięć sekund.
    """

    def __init__(self, conn, sock, resp):
        self._conn = conn
        self._sock = sock
        self._resp = resp

    def read_line(self, timeout):
        """Czyta jedną linię, czekając najwyżej `timeout` sekund.

        Timeout przerywa czytanie w pół i TRWALE psuje bufor — kolejne czytania
        rzucają „cannot read from timed out object”. Po timeoucie strumień
        nadaje się już tylko do zamknięcia, nigdy do dalszego użycia.
        """
        if self._sock is not None:
            try:
                self._sock.settimeout(max(1.0, timeout))
            except OSError:
                pass
        return self._resp.readline()

    def close(self):
        try:
            self._resp.close()
        finally:
            self._conn.close()


def open_sse(sse_url, token):
    """Otwiera strumień SSE. Zwraca SseStream albo rzuca wyjątkiem sieciowym.

    Centrifugo przyjmuje na tym endpoincie POST z JSON-em w ciele — dzięki temu
    wystarczy stdlib, bez klienta EventSource i bez zewnętrznych pakietów.
    """
    parts = urlsplit(sse_url)
    connection_class = HTTPSConnection if parts.scheme == 'https' else HTTPConnection
    default_port = 443 if parts.scheme == 'https' else 80
    conn = connection_class(
        parts.hostname, parts.port or default_port,
        timeout=SSE_CONNECT_TIMEOUT_SECONDS,
    )
    path = parts.path or '/'
    if parts.query:
        path = f'{path}?{parts.query}'
    conn.request(
        'POST', path,
        body=json.dumps({'token': token}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
    )
    # Gniazdo zapamiętujemy PRZED getresponse() — potem `conn.sock` bywa None.
    # Powód i skutki pomyłki: patrz docstring SseStream.
    sock = conn.sock
    resp = conn.getresponse()
    if resp.status != 200:
        conn.close()
        raise OSError(f"broker odpowiedział HTTP {resp.status} {resp.reason}")
    return SseStream(conn, sock, resp)


def classify_sse_line(raw):
    """
    Klasyfikuje linię strumienia: 'ping' | 'connect' | 'signal' | 'noise'.

    Celowo NIE parsujemy protokołu Centrifugo poza rozpoznaniem pingu i ramki
    powitalnej: KAŻDA inna ramka danych to 'signal', czyli "coś się wydarzyło,
    idź po zadania". Dzięki temu zmiana formatu push po stronie brokera nie
    wywróci agenta — sygnał ma tylko obudzić, treść i tak przyjeżdża z /jobs.
    Z tego samego powodu niesparsowalny JSON traktujemy jako sygnał: fałszywe
    obudzenie kosztuje jedno puste zapytanie, przespany sygnał kosztuje minutę
    czekania operatora przy drukarce.
    """
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    line = raw.strip()
    if not line or line.startswith(':'):
        return 'noise'          # pusta linia rozdzielająca zdarzenia / komentarz keep-alive
    if not line.startswith('data:'):
        return 'noise'          # pola 'event:', 'id:', 'retry:'
    payload = line[len('data:'):].strip()
    if not payload:
        return 'ping'
    try:
        obj = json.loads(payload)
    except ValueError:
        return 'signal'
    if not isinstance(obj, dict) or not obj:
        return 'ping'           # '{}' — ping protokołu Centrifugo
    if set(obj.keys()) == {'connect'}:
        return 'connect'
    return 'signal'


def wait_for_signal(stream, poll_deadline, cfg):
    """
    Blokuje na strumieniu SSE do jednego z trzech zdarzeń.

    Zwraca:
        'signal' — przyszedł budzik, trzeba iść po zadania
        'poll'   — minął deadline zapasowego pollingu albo skończyły się
                   godziny pracy; pętla główna i tak zrobi swoje
        'closed' — strumień padł (brak pinga, zamknięcie, błąd sieci)

    Deadline sprawdzamy MIĘDZY ramkami, nigdy nie przerywając czytania w pół.

    Dlaczego nie przycinamy limitu czytania do deadline'u (kuszące i błędne):
    przerwany timeoutem `readline()` TRWALE psuje bufor strumienia — każde
    kolejne czytanie rzuca wtedy „cannot read from timed out object”. Przycinanie
    limitu oznaczałoby więc wymuszony timeout przy każdym oknie pollingu, czyli
    zabijanie zdrowego połączenia co 60 s. Tak właśnie padał kanał na produkcji
    12.08.2026.

    Deadline jest przez to dotrzymywany z dokładnością do jednego odstępu między
    pingami (Centrifugo: 25 s), bo dopiero ramka daje okazję do sprawdzenia
    zegara. Zapasowy polling wykonuje się więc po ~60-85 s zamiast równo po 60 —
    i to jest w porządku, bo jego zadaniem jest złapać zgubiony sygnał, a nie
    trzymać rytm co do sekundy.
    """
    while True:
        if time.monotonic() >= poll_deadline or not in_working_hours(cfg):
            return 'poll'
        try:
            raw = stream.read_line(SSE_PING_TIMEOUT_SECONDS)
        except (socket.timeout, TimeoutError):
            # Timeout zdarza się TYLKO przy prawdziwej ciszy brokera — a wtedy
            # i tak zrywamy połączenie, więc zepsuty bufor nikomu nie szkodzi.
            warn("Brak pinga z brokera — uznaję połączenie push za martwe")
            return 'closed'
        except (OSError, ValueError, URLError, HTTPException) as e:
            log_error(f"Strumień push przerwany: {e}", exc=e)
            return 'closed'

        if not raw:
            return 'closed'     # serwer zamknął strumień (np. wygasł token)

        kind = classify_sse_line(raw)
        if kind == 'signal':
            return 'signal'
        if kind == 'connect':
            ok("Kanał push aktywny (print:agent)")

        # Ping i szum są okazją do sprawdzenia zegara — dlatego nie potrzebujemy
        # osobnego wątku ani budzika, wystarczy że broker regularnie się odzywa.
        if time.monotonic() >= poll_deadline or not in_working_hours(cfg):
            return 'poll'


def close_sse(stream):
    """Zamyka strumień, ignorując błędy. Zwraca None (do przypisania)."""
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass
    return None


# Do tylu sekund różnicy zegarów huba i serwera traktujemy wiek zadania jak zero.
_CLOCK_SKEW_TOLERANCE_SECONDS = 5


def _utcnow():
    """Naive UTC — odpowiednik `datetime.utcnow()`, ale bez ostrzeżenia.

    Od Pythona 3.12 `utcnow()` jest przestarzałe i wypisuje DeprecationWarning
    wprost do okna agenta na hubie. Zwracamy czas nieświadomy strefy, bo taki
    przychodzi z API CRM-a (`datetime.utcnow` w modelu) i takie dwie wartości
    wolno od siebie odejmować.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_reaction(seconds):
    """'42 ms' / '1.3 s' — czas reakcji agenta, mierzony zegarem monotonicznym."""
    if seconds < 1:
        return f'{seconds * 1000:.0f} ms'
    return f'{seconds:.1f} s'


def _describe_job_age(requested_at_iso):
    """Zwraca ' (czekało Xs)' albo '' — jak długo zadanie leżało w kolejce.

    Od migracji 2026-08-12 kolumna `requested_at` to DATETIME(3), więc ułamki
    sekundy nie giną już przy zapisie i wiek ma sens także poniżej sekundy.

    Czego ta liczba NIE mierzy: szybkości samego agenta. `requested_at` stawia
    zegar serwera CRM, odejmowanie robi zegar huba — różnica zegarów obu maszyn
    wchodzi w wynik. Przy niezsynchronizowanym hubie potrafi to być więcej niż
    cały mierzony czas. Do oceny reakcji agenta służy pole „reakcja”, liczone
    jednym zegarem monotonicznym na jednej maszynie.

    Pole requested_at z API to naive UTC (datetime.utcnow w modelu CRM-a),
    isoformat bez offsetu — dlatego po naszej stronie też schodzimy do naive UTC
    (`_utcnow()`), zamiast mieszać czas świadomy strefy z nieświadomym.
    """
    if not requested_at_iso:
        return ''
    try:
        req = datetime.fromisoformat(requested_at_iso.rstrip('Z'))
    except (ValueError, TypeError, AttributeError):
        return ''
    age = (_utcnow() - req).total_seconds()
    if age < 0:
        # Zegar huba idzie odrobinę za serwerem — przy wydruku w ułamku sekundy
        # od zlecenia wychodzi z tego ujemny wiek. Kilka sekund różnicy między
        # maszynami to normalka, więc pokazujemy zero zamiast straszyć.
        if age > -_CLOCK_SKEW_TOLERANCE_SECONDS:
            return ' (czekało 0.0s)'
        # Większy rozjazd to już realny problem z zegarem — pokazujemy surowo.
        return f' (req {requested_at_iso})'
    if age < 60:
        return f' (czekało {age:.2f}s)' if age < 1 else f' (czekało {age:.1f}s)'
    if age < 3600:
        return f' (czekało {int(age // 60)}m {int(age % 60)}s)'
    return f' (czekało {int(age // 3600)}h {int((age % 3600) // 60)}m)'


def _describe_timing(signal_at, requested_at_iso):
    """Sufiks do logu wydruku: czas reakcji na sygnał + ewentualny czas w kolejce.

    Reakcja pokazywana tylko dla zadań pobranych po sygnale push — przy pollingu
    liczba nic by nie znaczyła, bo zadanie mogło czekać całe okno pollingu.
    """
    parts = ''
    if signal_at is not None:
        parts += f' (reakcja {_format_reaction(time.monotonic() - signal_at)})'
    return parts + _describe_job_age(requested_at_iso)


# === Printer (TCP) ===
def send_to_printer(cfg, zpl):
    with socket.create_connection((cfg['printer_ip'], cfg['printer_port']), timeout=cfg['printer_timeout']) as sock:
        sock.sendall(zpl.encode('utf-8'))


# Zapytania o stan drukarki. Port 9100 jest dwukierunkowy — drukarka potrafi
# odpowiedzieć, o ile firmware to wspiera. XP-423B ma EMULACJĘ ZPL, nie
# oryginalny firmware Zebry, więc nie każda z tych komend musi zadziałać.
# Dlatego pytamy kilkoma i logujemy surowe odpowiedzi zamiast udawać, że
# rozumiemy format.
_PRINTER_QUERIES = (
    ('~HQES', 'stan błędów i ostrzeżeń'),
    ('~HS', 'status hosta'),
    ('~HI', 'identyfikacja modelu'),
)
_PRINTER_QUERY_TIMEOUT = 3


def query_printer_status(cfg):
    """Pyta drukarkę o stan. Zwraca listę (komenda, opis, odpowiedź).

    Nigdy nie rzuca i nigdy nie blokuje dłużej niż _PRINTER_QUERY_TIMEOUT na
    komendę — wołamy to z pętli drukowania, a ta nie może się zawiesić na
    diagnostyce. Osobne gniazdo na każdą komendę, żeby odpowiedzi się nie
    posklejały.
    """
    wyniki = []
    for komenda, opis in _PRINTER_QUERIES:
        try:
            with socket.create_connection((cfg['printer_ip'], cfg['printer_port']),
                                          timeout=_PRINTER_QUERY_TIMEOUT) as sock:
                sock.settimeout(_PRINTER_QUERY_TIMEOUT)
                sock.sendall(komenda.encode('ascii'))
                surowa = sock.recv(4096)
            odpowiedz = surowa.decode('ascii', 'replace').strip() or '(pusta odpowiedź)'
        except (socket.timeout, TimeoutError):
            odpowiedz = '(brak odpowiedzi w limicie — drukarka milczy)'
        except OSError as e:
            odpowiedz = f'(błąd połączenia: {e})'
        wyniki.append((komenda, opis, odpowiedz))
    return wyniki


def log_printer_status(cfg):
    """Wypytuje drukarkę i wypisuje odpowiedzi do konsoli oraz logu błędów."""
    warn("Pytam drukarkę o stan...")
    linie = []
    for komenda, opis, odpowiedz in query_printer_status(cfg):
        info(f"  {komenda} ({opis}): {odpowiedz}")
        linie.append(f"{komenda}={odpowiedz}")
    err_logger.error("Stan drukarki po nieudanym wydruku: " + " | ".join(linie))


# === Banner ===
def print_banner(cfg):
    masked = (cfg['token'][:4] + '...' + cfg['token'][-4:]) if len(cfg['token']) > 12 else '***'
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  WoodPower CRM — Print Agent{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}")
    info(f"CRM URL:        {cfg['crm_url']}")
    info(f"Token:          {masked}")
    info(f"Drukarka:       {cfg['printer_ip']}:{cfg['printer_port']}")
    info(f"Push (SSE):     {'włączony' if cfg['realtime_enabled'] else 'WYŁĄCZONY w config.ini'}")
    info(f"Polling co:     {cfg['push_idle_interval']}s z pushem / {cfg['poll_interval']}s bez")
    info(f"Godziny pracy:  pn-pt {cfg['workdays_start'].strftime('%H:%M')}-{cfg['workdays_end'].strftime('%H:%M')}, "
         f"sb {cfg['saturday_start'].strftime('%H:%M')}-{cfg['saturday_end'].strftime('%H:%M')}, niedz: idle")
    info(f"Konsola:        QuickEdit {cfg.get('_quick_edit', 'nie sprawdzano')}")
    info(f"Log błędów:     {ERROR_LOG_PATH}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}\n", flush=True)


# === Main loop ===
def run_once(cfg, signal_at=None, stan=None):
    """Jeden cykl: opróżnij kolejkę — pobierz, wydrukuj, ACK, powtórz.

    stan: opcjonalny słownik na sygnały poboczne dla pętli głównej. Ustawiamy
        w nim 'drukarka_padla', żeby main mógł skrócić czekanie — po awarii
        drukarki WIEMY, że zadania czekają, więc nie ma po co spać pełnego okna
        pollingu. Wartość zwracana zostaje bez zmian (True/False = zdrowie
        komunikacji z CRM), żeby nie ruszać kontraktu funkcji.

    signal_at: znacznik monotoniczny chwili, w której przyszedł sygnał push
        (None = cykl z pollingu). Służy tylko do zmierzenia czasu reakcji
        do logu — zegar monotoniczny, więc odporny na zmianę czasu w systemie.

    Zwraca:
        True  — komunikacja z CRM OK (fetch + ACK przeszły, lub brak zadań).
        False — fetch lub ACK rzucił błąd sieci/HTTP (sygnał dla backoffu w main).

    Awaria pojedynczego wydruku (drukarka offline) NIE liczy się jako fail
    komunikacji z CRM — ACK i tak idzie z success=False dla tego joba, więc
    serwer nie próbuje go ponownie i nie ma sensu uruchamiać backoffu.

    DLACZEGO PĘTLA, a nie jedna porcja: `/jobs` oddaje najwyżej `jobs_limit`
    (domyślnie 10) zadań, a CRM wysyła JEDEN sygnał na całe zlecenie, choćby
    miało 20 etykiet. Pobranie jednej porcji i pójście spać zostawiało resztę
    w kolejce do następnego obudzenia — i to się samo napędzało, bo kolejny
    sygnał szedł na dociągnięcie zaległości, a zadanie, które ten sygnał
    wywołało, stawało się nową zaległością. Tak właśnie 12.08.2026 jedna
    etykieta czekała 85 s przy sprawnym kanale push.
    """
    for _ in range(_MAX_BATCHES_PER_CYCLE):
        wynik = _process_one_batch(cfg, signal_at, stan=stan)
        if wynik != 'more':
            return wynik == 'ok'
        # Pełna porcja = w kolejce może czekać więcej. Dociągamy od razu,
        # zamiast czekać na następny sygnał albo na zapasowy polling.
    warn(f"Przerwano opróżnianie kolejki po {_MAX_BATCHES_PER_CYCLE} porcjach — "
         "reszta pójdzie następnym cyklem")
    return True


def _process_one_batch(cfg, signal_at=None, stan=None):
    """Jedna porcja zadań. Zwraca 'ok' | 'more' (porcja była pełna) | 'error'."""
    try:
        data = fetch_jobs(cfg)
    except HTTPError as e:
        if e.code == 401:
            log_error("401 Unauthorized z CRM — sprawdź token w panelu. Czekam 60s.")
            time.sleep(60)
            return 'error'
        log_error(f"CRM HTTP {e.code}: {e.reason}", exc=e)
        return 'error'
    except (URLError, TimeoutError, OSError) as e:
        log_error(f"Błąd sieci do CRM: {e}", exc=e)
        return 'error'

    jobs = data.get('jobs', [])
    if not jobs:
        return 'ok'  # cisza w logach przy braku zadań

    info(f"Pobrano {len(jobs)} zadań → drukuję...")
    results = []
    drukarka_padla = False
    for j in jobs:
        timing = _describe_timing(signal_at, j.get('requested_at'))
        if drukarka_padla:
            # Nie dobijamy się do martwej drukarki resztą porcji — każda próba
            # to kolejne `send_timeout_seconds` blokady, a efekt i tak ten sam.
            # Te zadania zostawiamy w kolejce (bez ACK), więc pozostaną `pending`
            # i wyjadą, gdy drukarka wróci.
            continue
        try:
            send_to_printer(cfg, j['zpl_payload'])
            ok(f"  ✓ id={j['id']} short={j['short_product_id']}{timing}")
            results.append({'id': j['id'], 'success': True})
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            err(f"  ✗ id={j['id']} short={j['short_product_id']}{timing} ({e})")
            log_error(f"Drukowanie id={j['id']} nieudane{timing}: {e}", exc=e)
            results.append({'id': j['id'], 'success': False, 'error': str(e)[:200]})
            drukarka_padla = True
            # Raz na porcję pytamy drukarkę, co jej dolega — sam komunikat
            # gniazda („timed out") nie odróżnia braku etykiet od wyłączonego
            # zasilania, a operator przy maszynie potrzebuje właśnie tego.
            log_printer_status(cfg)

    try:
        resp = ack_jobs(cfg, results)
        success_count = sum(1 for r in results if r['success'])
        ok(f"ACK: {success_count}/{len(results)} OK (server updated={resp.get('updated', '?')})")
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        log_error(f"Nie udało się wysłać ACK: {e}", exc=e)
        return 'error'

    # Po resztę wracamy TYLKO wtedy, gdy porcja była pełna I cała się wydrukowała.
    #
    # Warunek „cała się wydrukowała" jest tu kluczowy. Przy niedostępnej drukarce
    # każda etykieta blokuje się na pełny `send_timeout_seconds`, a ACK oznacza
    # zadania jako `failed` — czyli bezpowrotnie. Bez tego warunku agent
    # przemieliłby na porażki CAŁĄ kolejkę jednym ciągiem (przy 50 zadaniach to
    # kilkanaście minut blokady i 50 spalonych etykiet). Zatrzymujemy się na
    # pierwszej porcji z błędem: operator zdąży zauważyć problem z drukarką,
    # a reszta zadań zostaje w kolejce jako `pending`.
    if success_count < len(results):
        warn("Drukarka nie przyjęła części etykiet — przerywam opróżnianie kolejki")
        if stan is not None:
            stan['drukarka_padla'] = True
        return 'ok'
    return 'more' if len(jobs) >= cfg['jobs_limit'] else 'ok'


def _reconnect_delay(failures):
    """Odstęp do kolejnej próby połączenia z brokerem, wg drabinki.

    Pierwsze próby są gęste, bo najczęstsze zerwanie jest chwilowe (restart
    brokera, mrugnięcie sieci) i wtedy kanał wraca w sekundę. Dopiero trwała
    awaria schodzi do sprawdzania raz na minutę — i tam zostaje, bez końca.

    Jitter ±10%: przy jednym agencie bez znaczenia, ale etap 2 dokłada na ten
    sam broker tablety hali. Po jego restarcie wszystkie odcięte klienty
    ruszyłyby w tej samej milisekundzie. Celowo mały, żeby nie rozmywać
    drabinki — 1 s ma zostać sekundą, nie czterema.
    """
    stopien = SSE_RECONNECT_LADDER[min(max(failures, 1), len(SSE_RECONNECT_LADDER)) - 1]
    return stopien * random.uniform(0.9, 1.1)


def connect_push(cfg, failures=0):
    """Pobiera świeży token i otwiera kanał push. Zwraca strumień albo None.

    Token jest krótkotrwały i brany przy każdym połączeniu — gdy wygaśnie,
    Centrifugo rozłącza, agent wraca tędy i dostaje nowy. Zero odnawiania
    w tle, zero stanu do pilnowania.

    `failures` = ile prób z rzędu już się nie udało. Pierwszą awarię logujemy
    głośno, kolejne co _CONNECT_LOG_EVERY — broker potrafi być wyłączony przez
    cały weekend, a agent próbuje kilka razy na minutę. Bez tego wyciszenia
    `print_agent_errors.log` zapełniłby się tysiącami identycznych wpisów
    i utopił w nich prawdziwe błędy drukowania.
    """
    quiet = failures > 0 and failures % _CONNECT_LOG_EVERY != 0
    realtime = fetch_realtime_config(cfg, quiet=quiet)
    if realtime is None:
        return None
    try:
        stream = open_sse(realtime['sse_url'], realtime['token'])
    except (HTTPError, URLError, TimeoutError, OSError, HTTPException) as e:
        if not quiet:
            log_error(f"Nie udało się otworzyć kanału push ({realtime['sse_url']}): {e}", exc=e)
        return None
    info(f"Otwarto kanał push: {realtime['sse_url']}")
    return stream


def main():
    config_path = os.path.join(SCRIPT_DIR, 'config.ini')
    try:
        cfg = load_config(config_path)
    except Exception as e:
        err(f"Błąd ładowania konfiguracji: {e}")
        sys.exit(1)

    # Kolejność ma znaczenie: QuickEdit wyłączamy PRZED pierwszym wypisaniem
    # czegokolwiek na konsolę, bo to właśnie zapis na konsolę potrafi zamrozić.
    cfg['_quick_edit'] = disable_console_quick_edit()
    start_czujki()

    print_banner(cfg)

    # Exponential backoff przy seryjnych błędach komunikacji z CRM.
    # Powód: 5 maja 2026 podczas 22-min outage backendu (MySQL "Too many
    # connections") agent stuknął ~58 razy co 20s spamując i logi i serwer.
    # Po BACKOFF_THRESHOLD błędach z rzędu sleep dwoi się do BACKOFF_MAX_SECONDS.
    # Reset licznika po pierwszym sukcesie.
    #
    # Sufit obniżony z 300 s do 60 s (12.08.2026). 300 s znaczyło, że jedno
    # potknięcie sieci wyłączało agenta na pięć minut — przy operatorze stojącym
    # przy drukarce to wieczność, a serwerowi nic nie daje: przy 4 workerach
    # gunicorna jedno zapytanie na minutę i jedno na pięć minut to ta sama
    # znikoma różnica.
    BACKOFF_THRESHOLD = 3
    BACKOFF_MAX_SECONDS = 60

    in_idle = False
    consecutive_errors = 0
    stream = None            # otwarty kanał push albo None (= jedziemy na pollingu)
    sse_failures = 0         # nieudane próby połączenia z rzędu → backoff
    sse_retry_at = 0.0       # monotonic; przed tym czasem nie próbujemy ponownie
    signal_at = None         # monotonic chwili sygnału — do pomiaru czasu reakcji
    while True:
        try:
            _oznacz_postep()
            if not in_working_hours(cfg):
                stream = close_sse(stream)
                if not in_idle:
                    warn(f"Poza godzinami pracy — śpię (sprawdzam co {cfg['idle_check_interval']}s)")
                    in_idle = True
                # Wyjście z okna pracy = reset liczników; po wznowieniu nie chcemy
                # startować z poprzedniego backoffu z innego dnia.
                consecutive_errors = 0
                sse_failures = 0
                sse_retry_at = 0.0
                time.sleep(cfg['idle_check_interval'])
                continue

            if in_idle:
                info(f"{C.GREEN}Wracam do pracy (okno {cfg['workdays_start']}-{cfg['workdays_end']}){C.RESET}")
                in_idle = False

            # Łączymy się PRZED pobraniem zadań. Odwrotna kolejność zostawia okno
            # wyścigu: sygnał wysłany między naszym GET /jobs a otwarciem kanału
            # przepadłby, a etykieta czekałaby do zapasowego pollingu.
            # Przy backoffie CRM-a nie łączymy się z brokerem: token do niego
            # wydaje ten sam CRM, więc próba i tak padnie i tylko rozpędzi
            # drabinkę bez powodu.
            crm_sie_dlawi = consecutive_errors >= BACKOFF_THRESHOLD
            if (cfg['realtime_enabled'] and stream is None and not crm_sie_dlawi
                    and time.monotonic() >= sse_retry_at):
                new_stream = connect_push(cfg, failures=sse_failures)
                if new_stream is None:
                    sse_failures += 1
                    sse_retry_at = time.monotonic() + _reconnect_delay(sse_failures)
                    if sse_failures == 1:
                        warn(f"Brak kanału push — jadę na pollingu co {cfg['poll_interval']}s")
                else:
                    if sse_failures:
                        ok("Kanał push wrócił")
                    sse_failures = 0
                    stream = new_stream

            stan_cyklu = {}
            ok_run = run_once(cfg, signal_at=signal_at, stan=stan_cyklu)
            signal_at = None
            if ok_run:
                if consecutive_errors >= BACKOFF_THRESHOLD:
                    ok(f"CRM odpowiada — reset backoffu (po {consecutive_errors} błędach)")
                consecutive_errors = 0
                # Z żywym pushem polling jest tylko siatką bezpieczeństwa (60 s).
                # Bez niego wracamy do dotychczasowej częstotliwości (10 s) —
                # inaczej awaria brokera byłaby dla operatora GORSZA niż stan
                # sprzed wdrożenia pusha, a ma być co najwyżej taka sama.
                if stan_cyklu.get('drukarka_padla'):
                    # Wiemy, że w kolejce zostały zadania — czekamy krótko,
                    # żeby złapać moment powrotu drukarki. Bez tego operator
                    # czekałby pełne okno pollingu po dołożeniu etykiet.
                    wait_seconds = cfg['poll_interval']
                else:
                    wait_seconds = cfg['push_idle_interval'] if stream is not None else cfg['poll_interval']
            else:
                consecutive_errors += 1
                if consecutive_errors >= BACKOFF_THRESHOLD:
                    wait_seconds = min(
                        cfg['poll_interval'] * (2 ** (consecutive_errors - BACKOFF_THRESHOLD + 1)),
                        BACKOFF_MAX_SECONDS,
                    )
                    warn(f"Backoff: {consecutive_errors} błędów z rzędu → sleep {wait_seconds}s")
                else:
                    wait_seconds = cfg['poll_interval']

            in_backoff = consecutive_errors >= BACKOFF_THRESHOLD
            if in_backoff and stream is not None:
                # Wchodząc w backoff ZAMYKAMY kanał push. Wcześniej strumień
                # zostawał otwarty i nieczytany przez cały sen — czyli push
                # i polling padały razem, a po powrocie łączności agent czytał
                # z gniazda, które od minut nikt nie obsługiwał. Sygnały i tak
                # przychodzą z CRM-a, a skoro to z nim nie umiemy się dogadać,
                # nie ma czego nasłuchiwać.
                warn("Backoff — zamykam kanał push do czasu odzyskania łączności")
                stream = close_sse(stream)
            if stream is not None and not in_backoff:
                outcome = wait_for_signal(stream, time.monotonic() + wait_seconds, cfg)
                if outcome == 'signal':
                    signal_at = time.monotonic()
                elif outcome == 'closed':
                    # Zerwanie kanału MUSI być widoczne. Wcześniej operator nie
                    # dostawał ani słowa — ani na konsoli, ani w logu — bo
                    # komunikat siedział tylko w gałęzi nieudanego łączenia,
                    # a licznik prób był już wtedy podbity i wyciszał go.
                    warn(f"Kanał push zerwany — ponawiam, w międzyczasie polling "
                         f"co {cfg['poll_interval']}s")
                    err_logger.error("Kanał push zerwany (strumień zamknięty przez drugą stronę)")
                    stream = close_sse(stream)
                    # Zerwanie ZUŻYWA pierwszy stopień drabinki: próbujemy po
                    # sekundzie, a licznik ustawiamy na 1, żeby kolejna nieudana
                    # próba wzięła stopień DRUGI (2 s), a nie znowu pierwszy.
                    # Bez tego odstępy wychodziły 1, 1, 2, 5... zamiast 1, 2, 5...
                    sse_failures = 1
                    sse_retry_at = time.monotonic() + _reconnect_delay(1)
            else:
                # Gdy kanał push jest zerwany, śpimy najwyżej do najbliższej
                # zaplanowanej próby połączenia. Bez tego drabinka ponawiania
                # jest więźniem cyklu pętli: zaplanowane 1 s czekałoby na
                # kolejny obieg, czyli pełne okno pollingu, i pierwsze stopnie
                # (1, 2, 5 s) nigdy by się nie odpaliły.
                if cfg['realtime_enabled'] and stream is None and not in_backoff:
                    do_ponowienia = sse_retry_at - time.monotonic()
                    if 0 < do_ponowienia < wait_seconds:
                        wait_seconds = max(0.5, do_ponowienia)
                # Backoff obowiązuje też przy żywym pushu: skoro CRM się dławi,
                # sygnał nie jest powodem, żeby do niego wracać częściej.
                time.sleep(wait_seconds)
        except KeyboardInterrupt:
            close_sse(stream)
            info("Przerwano (Ctrl+C). Zamykam.")
            sys.exit(0)
        except Exception as e:
            stream = close_sse(stream)
            log_error(f"Niespodziewany wyjątek w main loop: {e}", exc=e)
            time.sleep(60)


def printer_status_mode():
    """`python print_agent.py --drukarka` — sprawdza drukarkę i kończy.

    Do odpalenia w drugim oknie, bez zatrzymywania agenta: pytania idą osobnym
    połączeniem i nie mieszają się z kolejką wydruków.
    """
    cfg = load_config(os.path.join(SCRIPT_DIR, 'config.ini'))
    print(f"{C.BOLD}{C.CYAN}Drukarka {cfg['printer_ip']}:{cfg['printer_port']}{C.RESET}\n")
    for komenda, opis, odpowiedz in query_printer_status(cfg):
        print(f"  {C.BOLD}{komenda}{C.RESET} ({opis}):\n      {odpowiedz}\n")
    print("Brak odpowiedzi na wszystkie komendy nie musi znaczyć awarii — XP-423B ma\n"
          "emulację ZPL i może nie wspierać zapytań o stan. Ale jeśli nie udaje się\n"
          "nawet POŁĄCZYĆ, drukarka jest odcięta i to jest odpowiedź sama w sobie.")


if __name__ == '__main__':
    if '--drukarka' in sys.argv or '--printer-status' in sys.argv:
        printer_status_mode()
    else:
        main()
