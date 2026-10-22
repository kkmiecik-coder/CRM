"""Aktualizacja agenta druku z okienka: pobranie instalatora z CRM, SHA-256, uruchomienie.

Woła ją usługa (LocalSystem) na `POST /aktualizacja` z zasobnika — bez kliknięcia nie dzieje się
nic. Kolejno: pobranie do `katalog_danych()/aktualizacje/` (katalog chroniony ACL z instalatora,
więc pliku nikt nie podmieni między sprawdzeniem a uruchomieniem), porównanie rozmiaru i SHA-256
z informacją z /kontakt (niezgodność = usunięcie pliku i błąd w okienku), uruchomienie instalatora
`/VERYSILENT` jako procesu odłączonego. Instalator zatrzymuje usługę, podmienia pliki i uruchamia
ją z powrotem. Błąd przed kopiowaniem plików (np. drugi instalator, nieudane zatrzymanie) zostawia
starą wersję i usługę uruchamia ponownie; błąd w trakcie kopiowania może zostawić mieszankę plików —
wtedy pomaga ponowna instalacja z pliku setup. W okienku błąd widać tylko wtedy, gdy instalacja
padła, zanim zatrzymała usługę (po LIMIT_INSTALACJI_S); późniejsze błędy są w logu instalatora.

Instalator idzie przez `cmd /c start`, a nie wprost: WinSW przy zatrzymaniu usługi zabija całe
drzewo procesów potomnych usługi, a instalator to drzewo właśnie zatrzymuje. Po `start` rodzicem
instalatora jest już zakończony `cmd`, więc zatrzymanie usługi go nie dotyka.
"""
import hashlib
import hmac
import logging
import os
import re
import subprocess
import threading
import time

from agent_druku import sciezki
from agent_druku.crm import BladCrm

log = logging.getLogger('agent_druku.aktualizacja')

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

PRZELACZNIKI_INSTALATORA = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
ETAPY_W_TOKU = ('pobieranie', 'weryfikacja')
_WERSJA = re.compile(r'^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$')
_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
ROZMIAR_KAWALKA = 1024 * 1024
# Instalator, który działa dłużej, zatrzymałby usługę dawno temu. Usługa, która po tym czasie wciąż
# żyje, wie, że instalacja się nie odbyła (np. drugi instalator, brak uprawnień) — pokazuje błąd.
LIMIT_INSTALACJI_S = 15 * 60
BLAD_INSTALACJI = ('instalator nie zakończył aktualizacji — spróbuj ponownie, a jeśli to się '
                   'powtórzy, sprawdź plik aktualizacje\\instalacja.log w katalogu danych agenta')


class Postep:
    """Postęp aktualizacji dla okienka (GET /stan): pobieranie → weryfikacja → instalacja | blad.
    Czytany z wątków lokalnego API, zmieniany z wątku aktualizacji — stąd blokada."""

    def __init__(self, zegar=time.monotonic):
        self._blokada = threading.Lock()
        self._zegar = zegar
        self._stan = None
        self._od = None

    def zajmij(self, info):
        """Start aktualizacji; False, gdy poprzednia jeszcze pobiera albo sprawdza plik.
        Po „instalacja” wolno ponowić — dwa instalatory naraz blokuje mutex instalatora."""
        with self._blokada:
            if self._stan is not None and self._stan['postep'] in ETAPY_W_TOKU:
                return False
            self._stan = {'postep': 'pobieranie', 'wersja': str((info or {}).get('wersja') or '')}
            self._od = self._zegar()
            return True

    def ustaw(self, etap, wersja, blad=None):
        with self._blokada:
            self._stan = {'postep': etap, 'wersja': wersja}
            self._od = self._zegar()
            if blad is not None:
                self._stan['blad'] = blad

    def stan(self):
        with self._blokada:
            if self._stan is None:
                return None
            if self._stan['postep'] == 'instalacja' and self._zegar() - self._od > LIMIT_INSTALACJI_S:
                self._stan = {'postep': 'blad', 'wersja': self._stan['wersja'],
                              'blad': BLAD_INSTALACJI}
            return dict(self._stan)


def katalog_aktualizacji():
    return sciezki.katalog_danych() / 'aktualizacje'


def plik_instalatora(wersja):
    return katalog_aktualizacji() / ('AgentDruku-%s-setup.exe' % wersja)


def _sprzatnij(katalog):
    """Poprzednie instalatory i przerwane pobrania nie zostają na dysku."""
    for plik in katalog.iterdir():
        if plik.is_file() and plik.suffix.lower() in ('.exe', '.part'):
            try:
                plik.unlink()
            except OSError as e:
                log.warning('Nie usunięto starego pliku aktualizacji %s: %s', plik, e)


def _sha256(plik):
    suma = hashlib.sha256()
    with open(plik, 'rb') as f:
        for kawalek in iter(lambda: f.read(ROZMIAR_KAWALKA), b''):
            suma.update(kawalek)
    return suma.hexdigest()


def _usun(plik):
    try:
        os.remove(plik)
    except OSError:
        pass


def polecenie_instalatora(plik, plik_logu):
    """Linia poleceń: `cmd /c start` (patrz opis modułu), instalator cicho, bez restartu systemu."""
    cmd = os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32', 'cmd.exe')
    return '"%s" /d /c start "" "%s" %s /LOG="%s"' % (cmd, plik, PRZELACZNIKI_INSTALATORA, plik_logu)


def wykonaj(agent, info, postep=None):
    """Pobiera, sprawdza i uruchamia instalator. True = instalator uruchomiony."""
    postep = postep or Postep()
    wersja = str((info or {}).get('wersja') or '')
    postep.ustaw('pobieranie', wersja)
    try:
        return _wykonaj(agent, info or {}, postep, wersja)
    except Exception as e:  # noqa: BLE001 — każdy błąd ma trafić do okienka, a nie zabić wątek
        log.exception('Nieoczekiwany błąd aktualizacji agenta druku')
        return _blad(postep, wersja, 'nieoczekiwany błąd aktualizacji: %s' % e)


def _blad(postep, wersja, opis):
    log.warning('Aktualizacja %s nieudana: %s', wersja or '(brak wersji)', opis)
    postep.ustaw('blad', wersja, opis)
    return False


def _wykonaj(agent, info, postep, wersja):
    suma = str(info.get('sha256') or '')
    url = info.get('url')
    if not _WERSJA.match(wersja):
        return _blad(postep, wersja, 'CRM podał niepoprawny numer wersji')
    if not _SHA256.match(suma):
        return _blad(postep, wersja, 'CRM nie podał sumy kontrolnej SHA-256 instalatora')
    if not isinstance(url, str) or not url:
        return _blad(postep, wersja, 'CRM nie podał adresu instalatora')
    klient = getattr(agent, 'klient', None)
    if klient is None:
        return _blad(postep, wersja, 'agent nie jest sparowany z CRM')

    katalog = katalog_aktualizacji()
    os.makedirs(katalog, exist_ok=True)
    _sprzatnij(katalog)
    plik = plik_instalatora(wersja)
    log.info('Pobieram aktualizację agenta druku %s', wersja)
    try:
        klient.pobierz_plik(url, str(plik))
    except BladCrm as e:
        _usun(plik)
        return _blad(postep, wersja, e.opis)

    postep.ustaw('weryfikacja', wersja)
    rozmiar = info.get('rozmiar')
    if isinstance(rozmiar, int) and not isinstance(rozmiar, bool) \
            and os.path.getsize(plik) != rozmiar:
        _usun(plik)
        return _blad(postep, wersja, 'rozmiar pobranego pliku nie zgadza się z CRM — plik usunięty, '
                                     'instalator nie został uruchomiony')
    if not hmac.compare_digest(_sha256(plik), suma.lower()):
        _usun(plik)
        return _blad(postep, wersja, 'suma kontrolna pobranego pliku nie zgadza się z CRM — plik '
                                     'usunięty, instalator nie został uruchomiony')

    try:
        subprocess.Popen(polecenie_instalatora(plik, katalog / 'instalacja.log'),
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         close_fds=True, cwd=str(katalog), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return _blad(postep, wersja, 'nie udało się uruchomić instalatora: %s' % e)
    postep.ustaw('instalacja', wersja)
    log.info('Uruchomiono instalator aktualizacji %s — usługa zaraz się zatrzyma', wersja)
    return True


# --- powrót ikony w zasobniku po aktualizacji ------------------------------------------------
def polecenie_powrotu_zasobnika(exe, wersja):
    """PowerShell (ukryty), który czeka, aż instalator `wersja` się skończy, i uruchamia ikonę
    z nowego exe. Woła go zasobnik tuż przed zamknięciem się na czas instalacji — instalator
    działa jako SYSTEM i nie może sam uruchomić ikony w sesji zalogowanego użytkownika."""
    if not _WERSJA.match(str(wersja or '')):
        raise ValueError('niepoprawny numer wersji: %r' % (wersja,))
    sciezka = str(exe).replace("'", "''")
    skrypt = (
        "$n = 'AgentDruku-%s-setup'; Start-Sleep -Seconds 5; $t = 0; "
        "while ((Get-Process -Name $n -ErrorAction SilentlyContinue) -and $t -lt 900) "
        "{ Start-Sleep -Seconds 2; $t += 2 }; Start-Sleep -Seconds 5; "
        "Start-Process -FilePath '%s' -ArgumentList 'tray'" % (wersja, sciezka))
    powershell = os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32',
                              'WindowsPowerShell', 'v1.0', 'powershell.exe')
    return [powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden', '-Command', skrypt]


def uruchom_powrot_zasobnika(exe, wersja):
    subprocess.Popen(polecenie_powrotu_zasobnika(exe, wersja),
                     creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
