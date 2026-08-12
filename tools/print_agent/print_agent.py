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
import time
import traceback
from datetime import datetime, time as dtime
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

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
SSE_RECONNECT_MAX_SECONDS = 60
# Co która nieudana próba połączenia trafia do logu (poza pierwszą, zawsze głośną).
_CONNECT_LOG_EVERY = 30


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


def open_sse(sse_url, token):
    """Otwiera strumień SSE. Zwraca obiekt odpowiedzi albo None.

    Centrifugo przyjmuje na tym endpoincie POST z JSON-em w ciele — dzięki temu
    wystarczy urllib, bez klienta EventSource i bez zewnętrznych pakietów.
    """
    body = json.dumps({'token': token}).encode('utf-8')
    req = urlreq.Request(
        sse_url,
        data=body,
        headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
        method='POST',
    )
    return urlreq.urlopen(req, timeout=SSE_PING_TIMEOUT_SECONDS)


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
    """
    while True:
        try:
            raw = stream.readline()
        except (socket.timeout, TimeoutError):
            warn("Brak pinga z brokera — uznaję połączenie push za martwe")
            return 'closed'
        except (OSError, ValueError, URLError) as e:
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


def _describe_job_age(requested_at_iso):
    """Zwraca ' (zlecone Xs temu)' lub '' jeśli brak/błąd parsowania.

    Pole requested_at z API to naive UTC (datetime.utcnow w modelu),
    isoformat bez offsetu — porównujemy też z datetime.utcnow().
    """
    if not requested_at_iso:
        return ''
    try:
        req = datetime.fromisoformat(requested_at_iso.rstrip('Z'))
    except (ValueError, TypeError, AttributeError):
        return ''
    age = (datetime.utcnow() - req).total_seconds()
    if age < 0:
        # Zegar huba rozjechany z serwerem albo strefa się popsuła.
        return f' (req {requested_at_iso})'
    if age < 60:
        return f' (zlecone {age:.1f}s temu)'
    if age < 3600:
        return f' (zlecone {int(age // 60)}m {int(age % 60)}s temu)'
    return f' (zlecone {int(age // 3600)}h {int((age % 3600) // 60)}m temu)'


# === Printer (TCP) ===
def send_to_printer(cfg, zpl):
    with socket.create_connection((cfg['printer_ip'], cfg['printer_port']), timeout=cfg['printer_timeout']) as sock:
        sock.sendall(zpl.encode('utf-8'))


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
    info(f"Log błędów:     {ERROR_LOG_PATH}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}\n", flush=True)


# === Main loop ===
def run_once(cfg):
    """Jeden cykl: pobierz pending, wydrukuj, ACK.

    Zwraca:
        True  — komunikacja z CRM OK (fetch + ACK przeszły, lub brak zadań).
        False — fetch lub ACK rzucił błąd sieci/HTTP (sygnał dla backoffu w main).

    Awaria pojedynczego wydruku (drukarka offline) NIE liczy się jako fail
    komunikacji z CRM — ACK i tak idzie z success=False dla tego joba, więc
    serwer nie próbuje go ponownie i nie ma sensu uruchamiać backoffu.
    """
    try:
        data = fetch_jobs(cfg)
    except HTTPError as e:
        if e.code == 401:
            log_error("401 Unauthorized z CRM — sprawdź token w panelu. Czekam 60s.")
            time.sleep(60)
            return False
        log_error(f"CRM HTTP {e.code}: {e.reason}", exc=e)
        return False
    except (URLError, TimeoutError, OSError) as e:
        log_error(f"Błąd sieci do CRM: {e}", exc=e)
        return False

    jobs = data.get('jobs', [])
    if not jobs:
        return True  # cisza w logach przy braku zadań

    info(f"Pobrano {len(jobs)} zadań → drukuję...")
    results = []
    for j in jobs:
        age_suffix = _describe_job_age(j.get('requested_at'))
        try:
            send_to_printer(cfg, j['zpl_payload'])
            ok(f"  ✓ id={j['id']} short={j['short_product_id']}{age_suffix}")
            results.append({'id': j['id'], 'success': True})
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            err(f"  ✗ id={j['id']} short={j['short_product_id']}{age_suffix} ({e})")
            log_error(f"Drukowanie id={j['id']} nieudane{age_suffix}: {e}", exc=e)
            results.append({'id': j['id'], 'success': False, 'error': str(e)[:200]})

    try:
        resp = ack_jobs(cfg, results)
        success_count = sum(1 for r in results if r['success'])
        ok(f"ACK: {success_count}/{len(results)} OK (server updated={resp.get('updated', '?')})")
        return True
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        log_error(f"Nie udało się wysłać ACK: {e}", exc=e)
        return False


def _reconnect_delay(failures):
    """Backoff reconnectu do brokera, z losowym jitterem.

    Jitter, żeby po restarcie Centrifugo wszystkie odcięte klienty nie wróciły
    w tej samej milisekundzie. Dziś agent jest jeden, ale etap 2 dokłada na ten
    sam broker tablety hali.
    """
    return min(2 ** min(failures, 6), SSE_RECONNECT_MAX_SECONDS) + random.uniform(0, 3)


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
    except (HTTPError, URLError, TimeoutError, OSError) as e:
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

    print_banner(cfg)

    # Exponential backoff przy seryjnych błędach komunikacji z CRM.
    # Powód: 5 maja 2026 podczas 22-min outage backendu (MySQL "Too many
    # connections") agent stuknął ~58 razy co 20s spamując i logi i serwer.
    # Po BACKOFF_THRESHOLD błędach z rzędu sleep dwoi się do BACKOFF_MAX_SECONDS.
    # Reset licznika po pierwszym sukcesie.
    BACKOFF_THRESHOLD = 3
    BACKOFF_MAX_SECONDS = 300

    in_idle = False
    consecutive_errors = 0
    stream = None            # otwarty kanał push albo None (= jedziemy na pollingu)
    sse_failures = 0         # nieudane próby połączenia z rzędu → backoff
    sse_retry_at = 0.0       # monotonic; przed tym czasem nie próbujemy ponownie
    while True:
        try:
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
            if cfg['realtime_enabled'] and stream is None and time.monotonic() >= sse_retry_at:
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

            ok_run = run_once(cfg)
            if ok_run:
                if consecutive_errors >= BACKOFF_THRESHOLD:
                    ok(f"CRM odpowiada — reset backoffu (po {consecutive_errors} błędach)")
                consecutive_errors = 0
                # Z żywym pushem polling jest tylko siatką bezpieczeństwa (60 s).
                # Bez niego wracamy do dotychczasowej częstotliwości (10 s) —
                # inaczej awaria brokera byłaby dla operatora GORSZA niż stan
                # sprzed wdrożenia pusha, a ma być co najwyżej taka sama.
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
            if stream is not None and not in_backoff:
                outcome = wait_for_signal(stream, time.monotonic() + wait_seconds, cfg)
                if outcome == 'closed':
                    stream = close_sse(stream)
                    sse_failures += 1
                    sse_retry_at = time.monotonic() + _reconnect_delay(sse_failures)
            else:
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


if __name__ == '__main__':
    main()
