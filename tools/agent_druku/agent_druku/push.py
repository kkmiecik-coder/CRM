"""Kanał push (Centrifugo, jednokierunkowe SSE) — przeniesiony ze starego agenta (print_agent.py).

Sygnał niesie tylko „obudź się”: treść (zadania, konfiguracja, polecenia, aktualizacja) i tak
przyjeżdża z API agenta. Czytnik kanału działa we własnym wątku i niczego sam nie robi poza
wywołaniem funkcji zwrotnych — pętla usługi tylko ustawia w nich zdarzenie.

Historii kanału nie ma: po każdym (ponownym) połączeniu agent robi natychmiastowy cykl
(`przy_polaczeniu`), więc sygnał zgubiony w czasie przerwy nadrabia to pobranie.
"""
import json
import logging
import random
import threading
import time
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from urllib.parse import urlsplit

from agent_druku.crm import BladCrm

log = logging.getLogger('agent_druku.push')

# Brak pinga przez tyle sekund = połączenie martwe (Centrifugo pinguje co 25 s).
LIMIT_PINGA_S = 40
# Limit na samo nawiązanie połączenia — osobny i krótki: broker, który przyjmuje TCP
# i milczy, nie może zablokować wątku kanału na czas limitu ciszy.
LIMIT_POLACZENIA_S = 5
# Drabinka ponawiania połączenia (sekundy); po ostatnim stopniu próba co minutę, bez końca.
DRABINKA = (1, 2, 5, 10, 15, 30, 60)
# O tyle sekund przed nominalnym TTL tokena zerwanie wciąż uznajemy za planowe wygaśnięcie.
TOLERANCJA_TTL_S = 60
# Strumień zerwany szybciej niż po tylu sekundach liczy się jak nieudane połączenie: broker, który
# przyjmuje i od razu rozłącza (zły sekret po rotacji, brak uprawnień), nie może kręcić pętli co 1 s.
MIN_ZYCIE_S = 5

# Rodzaje sygnałów publikowanych przez CRM na kanale agenta.
RODZAJE = ('print', 'config', 'command', 'update')


class Strumien:
    """Otwarty strumień SSE razem z połączeniem (port SseStream ze starego agenta).

    Gniazdo trzeba zapamiętać PRZED getresponse(): odpowiedź bez Content-Length przejmuje
    gniazdo i `conn.sock` staje się None — limit czasu ustawiany przez `conn.sock` po cichu
    nic by nie robił, a gniazdo zostałoby z limitem nawiązywania (5 s < odstęp pingów 25 s)."""

    def __init__(self, conn, sock, resp):
        self._conn = conn
        self._sock = sock
        self._resp = resp
        self._otwarty_o = time.monotonic()
        self.expires_in = None

    def czas_zycia(self):
        return time.monotonic() - self._otwarty_o

    def czytaj_linie(self, limit_s):
        """Jedna linia, najwyżej `limit_s` czekania. Timeout trwale psuje bufor — po nim
        strumień nadaje się tylko do zamknięcia."""
        if self._sock is not None:
            try:
                self._sock.settimeout(max(1.0, limit_s))
            except OSError:
                pass
        return self._resp.readline()

    def zamknij(self):
        try:
            self._resp.close()
        finally:
            self._conn.close()


def otworz_sse(sse_url, token):
    """Otwiera strumień SSE (POST z tokenem w JSON-ie). Rzuca wyjątkiem sieciowym przy porażce."""
    czesci = urlsplit(sse_url)
    klasa = HTTPSConnection if czesci.scheme == 'https' else HTTPConnection
    port = czesci.port or (443 if czesci.scheme == 'https' else 80)
    conn = klasa(czesci.hostname, port, timeout=LIMIT_POLACZENIA_S)
    sciezka = czesci.path or '/'
    if czesci.query:
        sciezka = '%s?%s' % (sciezka, czesci.query)
    conn.request('POST', sciezka, body=json.dumps({'token': token}).encode('utf-8'),
                 headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
    sock = conn.sock  # przed getresponse() — patrz docstring Strumien
    resp = conn.getresponse()
    if resp.status != 200:
        conn.close()
        raise OSError('broker odpowiedział HTTP %s %s' % (resp.status, resp.reason))
    return Strumien(conn, sock, resp)


def _rodzaj(obj):
    """`kind` publikacji (`{"pub": {"data": {"kind": ...}}}`) albo None."""
    pub = obj.get('pub')
    dane = pub.get('data') if isinstance(pub, dict) else None
    rodzaj = dane.get('kind') if isinstance(dane, dict) else None
    return rodzaj if rodzaj in RODZAJE else None


def klasyfikuj_linie(surowa):
    """(typ, rodzaj): typ ∈ ping|connect|signal|noise; rodzaj ∈ RODZAJE albo None.

    Każda ramka danych poza pingiem i powitaniem to sygnał — także nieznana albo
    niesparsowalna: fałszywe obudzenie kosztuje jedno puste zapytanie, przespany sygnał
    minutę czekania operatora przy drukarce."""
    if isinstance(surowa, bytes):
        surowa = surowa.decode('utf-8', 'replace')
    linia = surowa.strip()
    if not linia or linia.startswith(':') or not linia.startswith('data:'):
        return 'noise', None
    tresc = linia[len('data:'):].strip()
    if not tresc:
        return 'ping', None
    try:
        obj = json.loads(tresc)
    except ValueError:
        return 'signal', None
    if not isinstance(obj, dict) or not obj:
        return 'ping', None
    if set(obj) == {'connect'}:
        return 'connect', None
    return 'signal', _rodzaj(obj)


def opoznienie(nieudane, losuj=random.uniform):
    """Odstęp do kolejnej próby wg drabinki, z jitterem ±10%."""
    stopien = DRABINKA[min(max(nieudane, 1), len(DRABINKA)) - 1]
    return stopien * losuj(0.9, 1.1)


def wygasl_planowo(czas_zycia, expires_in):
    """Zerwanie po (prawie) pełnym TTL tokena to rutyna, nie awaria. Bez TTL — awaria."""
    if not expires_in:
        return False
    return czas_zycia >= expires_in - TOLERANCJA_TTL_S


class Kanal:
    """Wątek czytający kanał push. Funkcje zwrotne wołane są z wątku kanału — mają być krótkie
    (pętla usługi ustawia w nich tylko zdarzenie).

    przy_polaczeniu() — po każdym (ponownym) otwarciu strumienia,
    przy_sygnale(rodzaj) — rodzaj ∈ RODZAJE albo None (nieznana ramka też budzi),
    przy_rozlaczeniu() — po zamknięciu strumienia."""

    def __init__(self, klient, przy_polaczeniu, przy_sygnale, przy_rozlaczeniu=None,
                 otworz=otworz_sse, losuj=random.uniform, czekaj=None, adres_crm=''):
        self._klient = klient
        self._przy_polaczeniu = przy_polaczeniu
        self._przy_sygnale = przy_sygnale
        self._przy_rozlaczeniu = przy_rozlaczeniu or (lambda: None)
        self._otworz = otworz
        self._losuj = losuj
        self._stop = threading.Event()
        self._czekaj = czekaj or self._stop.wait
        self._adres_crm = (adres_crm or '').rstrip('/')
        self._blokada = threading.Lock()
        self._strumien = None
        self._watek = None
        self.nieudane = 0

    @property
    def polaczony(self):
        with self._blokada:
            return self._strumien is not None

    def uruchom(self):
        self._watek = threading.Thread(target=self._petla, name='agent-druku-push', daemon=True)
        self._watek.start()

    def zatrzymaj(self):
        self._stop.set()
        with self._blokada:
            strumien = self._strumien
        if strumien is not None:  # odblokowuje czekające czytanie
            try:
                strumien.zamknij()
            except Exception:
                pass

    def _petla(self):
        while not self._stop.is_set():
            try:
                odstep = self.krok()
            except Exception:  # wątek kanału nie może umrzeć — push to tylko przyspieszenie
                log.exception('Nieoczekiwany błąd kanału push')
                self.nieudane += 1
                odstep = opoznienie(self.nieudane, self._losuj)
            if odstep > 0:
                self._czekaj(odstep)

    def krok(self):
        """Jedna próba połączenia i czytanie do zamknięcia. Zwraca odstęp do kolejnej próby."""
        wynik = self.przebieg()
        if wynik in ('brak', 'zerwany_szybko'):
            self.nieudane += 1
            return opoznienie(self.nieudane, self._losuj)
        if wynik == 'wygasl':
            self.nieudane = 0
            return 0
        # Zerwanie strumienia, który pożył, zeruje drabinkę i zużywa jej pierwszy stopień: próba po sekundzie.
        self.nieudane = 1
        return opoznienie(1, self._losuj)

    def _adres_sse(self, dane):
        adres = (dane.get('sse_url') or '').strip()
        if not adres and self._adres_crm:
            adres = self._adres_crm + '/realtime/connection/uni_sse'
        return adres

    def przebieg(self):
        """'brak' (nie połączono), 'wygasl' (token dożył TTL), 'zerwany_szybko' (zerwany przed upływem
        MIN_ZYCIE_S) albo 'zerwany'."""
        try:
            dane = self._klient.realtime_token()
        except BladCrm:
            return 'brak'  # 503 = realtime wyłączony; sieć — i tak jedziemy na pollingu
        if not isinstance(dane, dict) or not dane.get('enabled') or not dane.get('token'):
            return 'brak'
        adres = self._adres_sse(dane)
        if not adres:
            return 'brak'
        try:
            strumien = self._otworz(adres, dane['token'])
        except (OSError, HTTPException, ValueError) as e:
            if self.nieudane == 0:
                log.warning('Nie udało się otworzyć kanału push: %s', e)
            return 'brak'
        try:
            strumien.expires_in = int(dane.get('expires_in'))
        except (TypeError, ValueError):
            strumien.expires_in = None
        with self._blokada:
            if self._stop.is_set():
                strumien.zamknij()
                return 'zerwany'
            self._strumien = strumien
        try:
            self._przy_polaczeniu()
            self._czytaj(strumien)
        finally:
            with self._blokada:
                self._strumien = None
            try:
                strumien.zamknij()
            except Exception:
                pass
            self._przy_rozlaczeniu()
        czas_zycia = strumien.czas_zycia()
        if wygasl_planowo(czas_zycia, strumien.expires_in):
            return 'wygasl'
        return 'zerwany_szybko' if czas_zycia < MIN_ZYCIE_S else 'zerwany'

    def _czytaj(self, strumien):
        while not self._stop.is_set():
            try:
                surowa = strumien.czytaj_linie(LIMIT_PINGA_S)
            except (OSError, ValueError, HTTPException):
                return  # cisza dłuższa niż limit pinga albo zerwanie
            if not surowa:
                return  # broker zamknął strumień (np. wygasł token)
            typ, rodzaj = klasyfikuj_linie(surowa)
            if typ == 'signal':
                self._przy_sygnale(rodzaj)
