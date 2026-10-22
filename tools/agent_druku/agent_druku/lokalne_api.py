"""Lokalne API usługi agenta druku — rozmowa z zasobnikiem, wyłącznie na 127.0.0.1.

Każde żądanie musi nieść nagłówek `X-Klucz` równy zawartości pliku `klucz_lokalny` w katalogu
danych (losowy, tworzony przy pierwszym starcie usługi albo przez instalator). Brak albo zły
klucz = 403. Token agenta nigdy nie wychodzi w odpowiedzi.

Trasy:
  GET  /stan                     — Agent.stan_dla_okienka() + adres CRM
  POST /wydruk-probny/<drukarka> — etykieta próbna z lokalnymi przesunięciami, prosto do drukarki
  POST /ponow-zalegle            — natychmiastowy cykl (wątek roboczy agenta)
  POST /kalibruj/<drukarka>      — GAPDETECT prosto do drukarki
  GET  /konfiguracja             — {"wersja","dane","oczekujaca": bool,"blad_konfiguracji"}
  PUT  /konfiguracja             — {"dane"} → zapis lokalny, do CRM przy synchronizacji
  POST /parowanie                — {"token", "crm_url"?}; serwer CRM przypięty instalatorem,
                                   inny adres → 409 inny_serwer_crm
  GET  /log                      — ostatnie 500 linii logu usługi (text/plain)
  POST /aktualizacja             — bez ciała: instalator z ostatniego /kontakt, w wątku tła (202);
                                   postęp i błąd w GET /stan → "aktualizacja": {..., "postep", "blad"}
"""
import collections
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_druku import aktualizacja, crm, konfiguracja, sciezki

log = logging.getLogger('agent_druku.lokalne_api')

PORT = 47130
HOST = '127.0.0.1'
MAKS_CIALA = 64 * 1024
LINIE_LOGU = 500
MIN_DLUGOSC_KLUCZA = 32
NA_WINDOWS = os.name == 'nt'
SID_INTERAKTYWNI = '*S-1-5-4'   # zalogowani przy komputerze — ikona w zasobniku czyta klucz

ROLE = ('etykiety', 'wysylka')
ODCZYTY_STANU = ('snmp', 'brak')
KLUCZE_PRZESUNIEC = {'etykiety': ('lt', 'ls'), 'wysylka': ('dx', 'dy')}
_IP = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')
_GODZINA = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


# --- klucz lokalny -------------------------------------------------------
class BladKlucza(RuntimeError):
    """Klucz lokalnego API pusty albo za krótki — serwer nie może wystartować (byłby otwarty)."""


_KLUCZ = re.compile(r'^[0-9a-fA-F]{64}$')


def wczytaj_klucz(plik=None):
    with open(plik or sciezki.plik_klucza_lokalnego(), 'r', encoding='ascii', errors='replace') as f:
        return f.read().strip()


def _zapisz_atomowo(plik, tresc):
    katalog = os.path.dirname(os.path.abspath(plik))
    os.makedirs(katalog, exist_ok=True)
    fd, tymczasowy = tempfile.mkstemp(dir=katalog, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as f:
            f.write(tresc)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tymczasowy, plik)
    except BaseException:
        try:
            os.remove(tymczasowy)
        except OSError:
            pass
        raise


def _udostepnij_klucz(plik):
    """Nowy plik klucza dziedziczy ACL katalogu (tylko SYSTEM i Administratorzy), a ikona
    w zasobniku działa bez podniesienia uprawnień — przywracamy jej prawo odczytu, jak instalator."""
    if not NA_WINDOWS:
        return
    icacls = os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32', 'icacls.exe')
    try:
        wynik = subprocess.run([icacls, str(plik), '/grant', SID_INTERAKTYWNI + ':(R)'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30, check=False,
                               creationflags=aktualizacja.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning('Nie nadano ikonie prawa odczytu klucza %s: %s', plik, e)
        return
    if wynik.returncode != 0:
        log.warning('icacls zakończył się kodem %s dla klucza %s', wynik.returncode, plik)


def zapewnij_klucz(plik=None):
    """Klucz lokalny przy starcie usługi: 64 znaki hex (32 losowe bajty). Brak pliku zakłada nowy klucz
    atomowo; plik z czymkolwiek innym (pusty, za krótki, znaki spoza hex) przenosimy na bok
    (`klucz_lokalny.uszkodzony-<czas>`, CRITICAL w logu) i zakładamy nowy — bez pętli restartów usługi.
    Przy każdym starcie ponownie nadajemy ikonie prawo odczytu (instalator przy aktualizacji robi
    `icacls /reset`). Gdy i potem klucz jest zły — BladKlucza (usługa nie wystartuje z otwartym API)."""
    plik = plik or sciezki.plik_klucza_lokalnego()
    try:
        klucz = wczytaj_klucz(plik)
    except FileNotFoundError:
        klucz = None
    if klucz is not None and _KLUCZ.match(klucz):
        _udostepnij_klucz(plik)
        return klucz
    if klucz is None:
        log.warning('Brak klucza lokalnego API — zakładam nowy: %s', plik)
    else:
        odlozony = sciezki.odloz_uszkodzony(plik)
        log.critical('Klucz lokalnego API jest uszkodzony (oczekiwano 64 znaków hex) — przeniesiony na %s, '
                     'zakładam nowy: %s', odlozony or '(nie udało się przenieść)', plik)
    _zapisz_atomowo(plik, secrets.token_hex(32))
    _udostepnij_klucz(plik)
    klucz = wczytaj_klucz(plik)
    if not _KLUCZ.match(klucz):
        raise BladKlucza('Nie udało się założyć klucza lokalnego API w %s — usługa nie wystartuje.' % plik)
    return klucz


# --- walidacja konfiguracji z okienka -------------------------------------
def _liczba_calkowita(w):
    return isinstance(w, int) and not isinstance(w, bool)


def waliduj_konfiguracje(dane):
    """Ten sam kształt dokumentu co serwer; tylko to, bez czego pętla usługi by się wywróciła.
    Pełne reguły (np. zakres przesunięć) sprawdza serwer przy synchronizacji."""
    if not isinstance(dane, dict):
        return ['konfiguracja musi być obiektem']
    bledy = []
    drukarki = dane.get('drukarki', [])
    if not isinstance(drukarki, list):
        bledy.append('lista drukarek ma zły format')
        drukarki = []
    nazwy = []
    for d in drukarki:
        if not isinstance(d, dict):
            bledy.append('drukarka ma zły format')
            continue
        nazwa = d.get('nazwa')
        if nazwa not in ROLE:
            bledy.append('nieznana drukarka: %s' % nazwa)
            continue
        if nazwa in nazwy:
            bledy.append('drukarka %s występuje dwa razy' % nazwa)
        nazwy.append(nazwa)
        m = _IP.match(str(d.get('ip') or ''))
        if not m or any(int(x) > 255 for x in m.groups()):
            bledy.append('%s: zły adres IP' % nazwa)
        if not _liczba_calkowita(d.get('port')) or not 1 <= d['port'] <= 65535:
            bledy.append('%s: port musi być liczbą 1–65535' % nazwa)
        if d.get('odczyt_stanu') not in ODCZYTY_STANU:
            bledy.append('%s: odczyt stanu musi być „snmp” albo „brak”' % nazwa)
        if not _liczba_calkowita(d.get('limit_wysylki_s')) or not 1 <= d['limit_wysylki_s'] <= 300:
            bledy.append('%s: limit wysyłki musi być liczbą sekund 1–300' % nazwa)
    przesuniecia = dane.get('przesuniecia', {})
    if not isinstance(przesuniecia, dict):
        bledy.append('przesunięcia mają zły format')
        przesuniecia = {}
    for nazwa, klucze in KLUCZE_PRZESUNIEC.items():
        p = przesuniecia.get(nazwa)
        if p is None:
            continue
        if not isinstance(p, dict) or not all(_liczba_calkowita(p.get(k)) for k in klucze):
            bledy.append('%s: przesunięcia muszą być liczbami całkowitymi' % nazwa)
    godziny = dane.get('godziny', {})
    if not isinstance(godziny, dict):
        bledy.append('godziny pracy mają zły format')
        godziny = {}
    for dzien, opis in (('pn_pt', 'pn–pt'), ('sobota', 'sobota')):
        para = godziny.get(dzien)
        if para is None:
            continue
        if (not isinstance(para, list) or len(para) != 2
                or not all(isinstance(g, str) and _GODZINA.match(g) for g in para)):
            bledy.append('godziny %s: wpisz od–do jako GG:MM' % opis)
        elif para[0] >= para[1]:
            bledy.append('godziny %s: początek musi być przed końcem' % opis)
    return bledy


# --- serwer ---------------------------------------------------------------
class _Serwer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False   # drugi proces usługi na tym samym porcie ma się nie uruchomić


def _konfiguracja_drukarki(agent, nazwa):
    for d in (agent.lokalna.dane or {}).get('drukarki') or []:
        if isinstance(d, dict) and d.get('nazwa') == nazwa:
            return d
    return None


OBCA_DRUKARKA = (409, {'ok': False, 'error': 'drukarka_starego_agenta',
                       'opis': 'tę drukarkę obsługuje jeszcze stary agent — przełącz ją w CRM na nowego agenta'})


def _obsluga_drukarki(agent, nazwa):
    """Kto obsługuje drukarkę wg ostatniego pobrania zadań; przed pierwszym pobraniem — „nowy”."""
    for d in agent.stan_dla_okienka().get('drukarki') or []:
        if d.get('nazwa') == nazwa:
            return d.get('obsluga') or 'nowy'
    return 'nowy'


def _wydruk_probny(agent, nazwa):
    drukarka = _konfiguracja_drukarki(agent, nazwa)
    if drukarka is None:
        return 404, {'ok': False, 'opis': 'brak drukarki %s w konfiguracji agenta' % nazwa}
    if _obsluga_drukarki(agent, nazwa) != 'nowy':
        return OBCA_DRUKARKA
    przesuniecia = ((agent.lokalna.dane or {}).get('przesuniecia') or {}).get(nazwa) or {}
    try:
        zpl = agent.drukarki.zpl_probny(nazwa, przesuniecia)
    except ValueError as e:
        return 400, {'ok': False, 'opis': str(e)}
    wyniki = agent.drukarki.wyslij_porcje(drukarka, [{'id': 0, 'zpl': zpl}], lambda _id: True)
    wynik = wyniki[0] if wyniki else {'wynik': 'niewyslane'}
    if wynik['wynik'] == 'wydrukowane':
        log.info('Wydruk próbny wysłany z okienka: %s', nazwa)
        return 200, {'ok': True, 'opis': 'wydruk próbny wysłany do drukarki'}
    if wynik['wynik'] == 'niewyslane':
        opis = 'drukarka nie odpowiada — sprawdź, czy jest włączona i podłączona'
    else:
        opis = 'wysyłka przerwana: %s' % (wynik.get('blad') or 'błąd połączenia')
    log.warning('Wydruk próbny z okienka nieudany (%s): %s', nazwa, opis)
    return 502, {'ok': False, 'opis': opis}


def _kalibruj(agent, nazwa):
    drukarka = _konfiguracja_drukarki(agent, nazwa)
    if drukarka is None:
        return 404, {'ok': False, 'opis': 'brak drukarki %s w konfiguracji agenta' % nazwa}
    if _obsluga_drukarki(agent, nazwa) != 'nowy':
        return OBCA_DRUKARKA
    try:
        agent.drukarki.kalibruj(drukarka)
    except OSError as e:
        log.warning('Kalibracja z okienka nieudana (%s): %s', nazwa, e)
        return 502, {'ok': False, 'opis': 'kalibracja nieudana: %s' % e}
    log.info('Kalibracja wysłana z okienka: %s', nazwa)
    return 200, {'ok': True, 'opis': 'kalibracja wysłana — drukarka przewinie kilka pustych etykiet'}


def _parowanie(agent, cialo, fabryka_klienta, adres_crm):
    """Tylko token: serwer CRM przypiął instalator. Inny serwer znaczyłby, że każdy zalogowany
    przy komputerze może skierować usługę (LocalSystem) po „aktualizację” do własnego serwera."""
    if not adres_crm:
        return 409, {'ok': False, 'error': 'brak_adresu_crm',
                     'opis': 'agent nie zna adresu CRM — zainstaluj go ponownie'}
    podany = str(cialo.get('crm_url') or '').strip()
    if podany:
        try:
            podany = konfiguracja.normalizuj_adres_crm(podany)
        except ValueError as e:
            return 400, {'ok': False, 'opis': str(e)}
        if not konfiguracja.ten_sam_serwer(podany, adres_crm):
            return 409, {'ok': False, 'error': 'inny_serwer_crm',
                         'opis': 'ten agent łączy się tylko z %s — zmiana serwera CRM wymaga '
                                 'ponownej instalacji agenta' % adres_crm}
    token = str(cialo.get('token') or '').strip()
    if not token:
        return 400, {'ok': False, 'opis': 'wklej token agenta z CRM'}
    agent.sparuj(adres_crm, token, fabryka_klienta)
    return 200, {'ok': True, 'opis': 'zapisano — agent łączy się z CRM', 'crm_url': adres_crm}


def _aktualizuj(agent, postep):
    info = agent.stan_dla_okienka().get('aktualizacja')
    if not isinstance(info, dict) or not info.get('wersja'):
        return 409, {'ok': False, 'error': 'brak_aktualizacji',
                     'opis': 'CRM nie ma nowszej wersji agenta'}
    if not postep.zajmij(info):
        return 409, {'ok': False, 'error': 'aktualizacja_trwa',
                     'opis': 'aktualizacja już się pobiera — poczekaj'}
    log.info('Aktualizacja %s zlecona z okienka', info.get('wersja'))
    threading.Thread(target=aktualizacja.wykonaj, args=(agent, dict(info), postep),
                     name='agent-druku-aktualizacja', daemon=True).start()
    return 202, {'ok': True, 'opis': 'pobieram aktualizację %s…' % info.get('wersja')}


def _stan(agent, postep, adres_crm):
    stan = agent.stan_dla_okienka()
    stan['crm_url'] = adres_crm or agent.lokalna.crm_url
    biezacy = postep.stan()
    if biezacy is not None:
        akt = dict(stan.get('aktualizacja') or {})
        akt.update(biezacy)
        stan['aktualizacja'] = akt
    return stan


def _ostatnie_linie(plik, n=LINIE_LOGU):
    try:
        with open(plik, 'r', encoding='utf-8', errors='replace') as f:
            return ''.join(collections.deque(f, maxlen=n))
    except FileNotFoundError:
        return ''


def _obsluga(agent, klucz, fabryka_klienta, plik_logu, postep, adres_crm):
    klucz_b = klucz.encode('ascii')
    if len(klucz_b) < MIN_DLUGOSC_KLUCZA:   # nigdy nie obsługujemy z pustym kluczem
        raise BladKlucza('Klucz lokalnego API jest pusty albo krótszy niż %d znaki — '
                         'lokalne API nie wystartuje.' % MIN_DLUGOSC_KLUCZA)

    class Obsluga(BaseHTTPRequestHandler):
        server_version = 'AgentDruku'
        sys_version = ''
        timeout = 30   # klient, który otworzył połączenie i milczy, nie trzyma wątku bez końca

        def log_message(self, fmt, *args):  # bez wypisywania na stderr
            log.debug('lokalne API: ' + fmt, *args)

        def _odpowiedz(self, kod, tresc, typ='application/json; charset=utf-8'):
            if not isinstance(tresc, bytes):
                tresc = json.dumps(tresc, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(kod)
            self.send_header('Content-Type', typ)
            self.send_header('Content-Length', str(len(tresc)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(tresc)

        def _klucz_ok(self):
            podany = (self.headers.get('X-Klucz') or '').encode('utf-8', 'replace')
            return hmac.compare_digest(podany, klucz_b)

        def _cialo(self):
            try:
                dlugosc = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                return None
            if dlugosc <= 0:
                return {}
            if dlugosc > MAKS_CIALA:
                return None
            try:
                cialo = json.loads(self.rfile.read(dlugosc).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return None
            return cialo if isinstance(cialo, dict) else None

        def _obsluz(self, metoda):
            if not self._klucz_ok():
                self._odpowiedz(403, {'error': 'zly_klucz'})
                return
            sciezka = self.path.split('?', 1)[0].rstrip('/') or '/'
            cialo = {}
            if metoda in ('POST', 'PUT'):
                cialo = self._cialo()
                if cialo is None:
                    self._odpowiedz(400, {'error': 'zle_cialo'})
                    return
            try:
                kod, tresc, *typ = self._trasa(metoda, sciezka, cialo)
            except Exception:
                log.exception('Błąd lokalnego API: %s %s', metoda, sciezka)
                kod, tresc, typ = 500, {'error': 'blad_uslugi'}, []
            self._odpowiedz(kod, tresc, *typ)

        def _trasa(self, metoda, sciezka, cialo):
            czesci = sciezka.strip('/').split('/')
            if metoda == 'GET' and sciezka == '/stan':
                return 200, _stan(agent, postep, adres_crm)
            if metoda == 'POST' and sciezka == '/aktualizacja':
                return _aktualizuj(agent, postep)
            if metoda == 'POST' and len(czesci) == 2 and czesci[0] == 'wydruk-probny':
                return _wydruk_probny(agent, czesci[1])
            if metoda == 'POST' and len(czesci) == 2 and czesci[0] == 'kalibruj':
                return _kalibruj(agent, czesci[1])
            if metoda == 'POST' and sciezka == '/ponow-zalegle':
                agent.obudz('ponow-zalegle')
                return 202, {'ok': True, 'opis': 'zaległe zadania idą teraz'}
            if sciezka == '/konfiguracja' and metoda == 'GET':
                lok = agent.lokalna
                return 200, {'wersja': lok.wersja, 'dane': lok.dane,
                             'oczekujaca': lok.oczekujaca is not None,
                             'blad_konfiguracji': agent.stan_dla_okienka().get('blad_konfiguracji')}
            if sciezka == '/konfiguracja' and metoda == 'PUT':
                dane = cialo.get('dane')
                bledy = waliduj_konfiguracje(dane)
                if bledy:
                    return 400, {'error': 'bledna_konfiguracja', 'bledy': bledy}
                agent.lokalna.zapisz_lokalnie(dane)
                log.info('Konfiguracja zmieniona w okienku agenta')
                agent.obudz('konfiguracja')
                return 200, {'ok': True, 'wersja': agent.lokalna.wersja, 'oczekujaca': True}
            if metoda == 'POST' and sciezka == '/parowanie':
                return _parowanie(agent, cialo, fabryka_klienta, adres_crm)
            if metoda == 'GET' and sciezka == '/log':
                return 200, _ostatnie_linie(plik_logu).encode('utf-8'), 'text/plain; charset=utf-8'
            return 404, {'error': 'nie_znaleziono'}

        def do_GET(self):
            self._obsluz('GET')

        def do_POST(self):
            self._obsluz('POST')

        def do_PUT(self):
            self._obsluz('PUT')

    return Obsluga


def uruchom(agent, port=PORT, klucz=None, fabryka_klienta=crm.Klient, plik_logu=None,
            adres_crm=None):
    """Startuje serwer w wątku tła i zwraca go (`server_address`, `shutdown()`).
    Klucz pusty albo krótszy niż 32 znaki → BladKlucza (serwer nie startuje).
    `serwer.postep_aktualizacji` — postęp aktualizacji zleconej z okienka.
    `adres_crm` — serwer CRM przypięty instalatorem (None: odczyt z pliku; '' — parowanie odmawia)."""
    if adres_crm is None:
        adres_crm = konfiguracja.wczytaj_przypiety_adres()
    if klucz is None:
        klucz = zapewnij_klucz()
    postep = aktualizacja.Postep()
    obsluga = _obsluga(agent, klucz or '', fabryka_klienta, plik_logu or sciezki.plik_logu(), postep,
                       adres_crm)
    serwer = _Serwer((HOST, port), obsluga)
    serwer.postep_aktualizacji = postep
    watek = threading.Thread(target=serwer.serve_forever, name='agent-druku-lokalne-api',
                             daemon=True)
    watek.start()
    log.info('Lokalne API agenta na %s:%d', HOST, serwer.server_address[1])
    return serwer
