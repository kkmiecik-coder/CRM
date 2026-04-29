#!/usr/bin/env python3
"""
Print agent — polluje CRM po pending zadania ZPL i drukuje na drukarce w LAN.

Uruchamiany 24/7 na hubie biura. Polling tylko w godzinach pracy
(domyślnie pn-pt + sb 5:30-15:30).

Uruchomienie: `python print_agent.py` (lub `start.bat` na Windowsie).
Konfiguracja: `config.ini` (skopiuj z `config.example.ini`).

Uwaga: stdlib only (urllib + socket + configparser). Świadomie nie używamy
`requests`, żeby zero-dep — agent ma działać po `python print_agent.py`
na świeżym Pythonie. `colorama` jest opcjonalna (tylko kolory na starym CMD).
"""
import configparser
import json
import logging
import os
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
    return {
        'crm_url': cp.get('crm', 'url').rstrip('/'),
        'token': cp.get('crm', 'token'),
        'jobs_limit': cp.getint('crm', 'jobs_limit', fallback=10),
        'request_timeout': cp.getint('crm', 'request_timeout_seconds', fallback=10),
        'printer_ip': cp.get('printer', 'ip'),
        'printer_port': cp.getint('printer', 'port', fallback=9100),
        'printer_timeout': cp.getint('printer', 'send_timeout_seconds', fallback=5),
        'poll_interval': cp.getint('polling', 'interval_seconds', fallback=10),
        'idle_check_interval': cp.getint('polling', 'idle_check_interval_seconds', fallback=60),
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
    info(f"Polling co:     {cfg['poll_interval']}s")
    info(f"Godziny pracy:  pn-pt {cfg['workdays_start'].strftime('%H:%M')}-{cfg['workdays_end'].strftime('%H:%M')}, "
         f"sb {cfg['saturday_start'].strftime('%H:%M')}-{cfg['saturday_end'].strftime('%H:%M')}, niedz: idle")
    info(f"Log błędów:     {ERROR_LOG_PATH}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}\n", flush=True)


# === Main loop ===
def run_once(cfg):
    """Jeden cykl: pobierz pending, wydrukuj, ACK."""
    try:
        data = fetch_jobs(cfg)
    except HTTPError as e:
        if e.code == 401:
            log_error("401 Unauthorized z CRM — sprawdź token w panelu. Czekam 60s.")
            time.sleep(60)
            return
        log_error(f"CRM HTTP {e.code}: {e.reason}", exc=e)
        return
    except (URLError, TimeoutError, OSError) as e:
        log_error(f"Błąd sieci do CRM: {e}", exc=e)
        return

    jobs = data.get('jobs', [])
    if not jobs:
        return  # cisza w logach przy braku zadań

    info(f"Pobrano {len(jobs)} zadań → drukuję...")
    results = []
    for j in jobs:
        try:
            send_to_printer(cfg, j['zpl_payload'])
            ok(f"  ✓ id={j['id']} short={j['short_product_id']}")
            results.append({'id': j['id'], 'success': True})
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            err(f"  ✗ id={j['id']} short={j['short_product_id']} ({e})")
            log_error(f"Drukowanie id={j['id']} nieudane: {e}", exc=e)
            results.append({'id': j['id'], 'success': False, 'error': str(e)[:200]})

    try:
        resp = ack_jobs(cfg, results)
        success_count = sum(1 for r in results if r['success'])
        ok(f"ACK: {success_count}/{len(results)} OK (server updated={resp.get('updated', '?')})")
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        log_error(f"Nie udało się wysłać ACK: {e}", exc=e)


def main():
    config_path = os.path.join(SCRIPT_DIR, 'config.ini')
    try:
        cfg = load_config(config_path)
    except Exception as e:
        err(f"Błąd ładowania konfiguracji: {e}")
        sys.exit(1)

    print_banner(cfg)

    in_idle = False
    while True:
        try:
            if in_working_hours(cfg):
                if in_idle:
                    info(f"{C.GREEN}Wracam do pracy (okno {cfg['workdays_start']}-{cfg['workdays_end']}){C.RESET}")
                    in_idle = False
                run_once(cfg)
                time.sleep(cfg['poll_interval'])
            else:
                if not in_idle:
                    warn(f"Poza godzinami pracy — śpię (sprawdzam co {cfg['idle_check_interval']}s)")
                    in_idle = True
                time.sleep(cfg['idle_check_interval'])
        except KeyboardInterrupt:
            info("Przerwano (Ctrl+C). Zamykam.")
            sys.exit(0)
        except Exception as e:
            log_error(f"Niespodziewany wyjątek w main loop: {e}", exc=e)
            time.sleep(60)


if __name__ == '__main__':
    main()
