"""Lokalna konfiguracja agenta (plik JSON w ProgramData) i synchronizacja z CRM."""
import copy
import json
import logging
import os
import tempfile
import threading
import urllib.parse

from . import sciezki
from .crm import BladCrm, _pochodzenie

log = logging.getLogger('agent_druku.konfiguracja')

# http tylko do testów i pracy lokalnej; serwer CRM zawsze przez https.
HOSTY_LOKALNE = ('127.0.0.1', 'localhost')


def normalizuj_adres_crm(url):
    """Adres CRM bez końcowego „/”. ValueError, gdy nie https (poza http://127.0.0.1
    i http://localhost) albo gdy ma ścieżkę zapytania, fragment czy dane logowania."""
    url = str(url or '').strip().rstrip('/')
    try:
        p = urllib.parse.urlsplit(url)
        p.port  # noqa: B018 — zły port rzuca ValueError
    except ValueError:
        raise ValueError('niepoprawny adres CRM') from None
    if not p.hostname or p.query or p.fragment or p.username or p.password:
        raise ValueError('niepoprawny adres CRM')
    if p.scheme == 'https' or (p.scheme == 'http' and p.hostname.lower() in HOSTY_LOKALNE):
        return url
    raise ValueError('adres CRM musi zaczynać się od https://')


def ten_sam_serwer(a, b):
    return _pochodzenie(a) == _pochodzenie(b)


def wczytaj_przypiety_adres(plik=None):
    """Adres CRM z instalatora albo '' (brak pliku albo niepoprawny adres — wtedy błąd w logu)."""
    plik = plik or sciezki.plik_adresu_crm()
    try:
        with open(plik, 'r', encoding='utf-8-sig', errors='replace') as f:
            surowy = f.read()
    except FileNotFoundError:
        return ''
    except OSError as e:
        log.error('Nie odczytano adresu CRM z %s: %s', plik, e)
        return ''
    try:
        return normalizuj_adres_crm(surowy)
    except ValueError as e:
        log.error('Adres CRM w %s odrzucony (%s) — zainstaluj agenta ponownie z /CRM=https://...',
                  plik, e)
        return ''


def _drukarki(dane):
    """Niepusta lista drukarek z dokumentu konfiguracji albo pusta lista."""
    lista = dane.get('drukarki') if isinstance(dane, dict) else None
    return lista if isinstance(lista, list) and lista else []


class Lokalna:
    """Token agenta leży tu jawnie (plik chroni ACL z instalatora) — nie logować, nie drukować."""

    def __init__(self, sciezka=None):
        self._sciezka = sciezka
        self._blokada = threading.RLock()  # stan zmienia okienko i wątek synchronizacji
        self.crm_url = ''
        self.token = ''
        self.wersja = 0
        self.dane = {}
        self.oczekujaca = None  # {"wersja_bazowa": int, "dane": dict} albo None
        self._wczytaj()

    def __repr__(self):  # bez tokenu
        return 'Lokalna(crm_url=%r, wersja=%r)' % (self.crm_url, self.wersja)

    def _plik(self):
        return self._sciezka or sciezki.plik_konfiguracji()

    def _wczytaj(self):
        try:
            with open(self._plik(), 'r', encoding='utf-8') as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError('plik nie zawiera obiektu JSON')
            crm_url = str(d.get('crm_url') or '')
            token = str(d.get('token') or '')
            wersja = int(d.get('wersja') or 0)
            dane = d.get('dane') or {}
            oczekujaca = d.get('oczekujaca')
            if not isinstance(dane, dict) or not (oczekujaca is None or isinstance(oczekujaca, dict)):
                raise ValueError('zły kształt danych konfiguracji')
        except FileNotFoundError:
            return
        except (ValueError, TypeError) as e:   # JSONDecodeError i UnicodeDecodeError to też ValueError
            odlozony = sciezki.odloz_uszkodzony(self._plik())
            log.critical('Plik konfiguracji agenta jest uszkodzony (%s) — przeniesiony na %s, start bez '
                         'konfiguracji: sparuj agenta ponownie.', e, odlozony or '(nie udało się przenieść)')
            return
        self.crm_url, self.token, self.wersja = crm_url, token, wersja
        self.dane, self.oczekujaca = dane, oczekujaca

    def zapisz(self):
        """Zapis atomowy: plik tymczasowy w tym samym katalogu + os.replace."""
        plik = os.path.abspath(self._plik())
        katalog = os.path.dirname(plik)
        os.makedirs(katalog, exist_ok=True)
        tresc = json.dumps({
            'crm_url': self.crm_url, 'token': self.token, 'wersja': self.wersja,
            'dane': self.dane, 'oczekujaca': self.oczekujaca,
        }, ensure_ascii=False, indent=2)
        fd, tymczasowy = tempfile.mkstemp(dir=katalog, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
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

    def ustaw_polaczenie(self, crm_url, token):
        """Parowanie z okienka: adres CRM i token agenta, zapisane od razu do pliku.

        Inny token niż dotąd może oznaczać innego agenta w CRM, czyli inny dokument konfiguracji z własną
        numeracją wersji — lokalnej wersji nie wolno z nim porównywać. Wersja wraca do 0, a oczekująca zmiana
        znika (jej baza to wersja starego dokumentu); lokalne `dane` zostają i przy synchronizacji albo
        ustępują dokumentowi serwera, albo — gdy serwer nie ma jeszcze drukarek — trafiają do niego
        (patrz `synchronizuj`)."""
        with self._blokada:
            if token != self.token:
                self.wersja = 0
                self.oczekujaca = None
            self.crm_url = crm_url
            self.token = token
            self.zapisz()

    def zapisz_lokalnie(self, dane):
        """Zmiana z okienka: działa od razu lokalnie, do CRM idzie przy synchronizacji."""
        with self._blokada:
            if self.oczekujaca is None:
                wersja_bazowa = self.wersja
            else:  # kolejna zmiana przed wysłaniem poprzedniej — baza zostaje ta sama
                wersja_bazowa = self.oczekujaca['wersja_bazowa']
            self.dane = dane
            self.oczekujaca = {'wersja_bazowa': wersja_bazowa, 'dane': dane}
            self.zapisz()

    def synchronizuj(self, crm):
        """Najpierw wysyła oczekującą zmianę, potem pobiera nowszą wersję serwera.

        BladCrm (sieć, 400, 409) przechodzi do wołającego; oczekująca zmiana zostaje.
        Blokada nie jest trzymana podczas HTTP; zmiana zapisana w międzyczasie nie ginie."""
        with self._blokada:
            migawka = copy.deepcopy(self.oczekujaca)
        if migawka is not None:
            try:
                odp = crm.zapisz_konfiguracje(migawka['wersja_bazowa'], migawka['dane'])
            except BladCrm as e:
                e.odrzucona = migawka  # do porzuc_oczekujaca(), gdy serwer odrzucił treść
                raise
            with self._blokada:
                self.wersja = int(odp['wersja'])
                if self.oczekujaca == migawka:
                    self.dane = odp.get('dane', migawka['dane'])
                    self.oczekujaca = None
                else:  # użytkownik zmienił dane w trakcie — jego nowsze zostają, baza = nowa wersja
                    self.oczekujaca['wersja_bazowa'] = self.wersja
                self.zapisz()
        serwer = crm.konfiguracja()
        przejecie = False
        with self._blokada:
            if self.oczekujaca is None and int(serwer['wersja']) != self.wersja:
                dane_serwera = serwer.get('dane') or {}
                if self.wersja == 0 and _drukarki(self.dane) and not _drukarki(dane_serwera):
                    # Po parowaniu nowym tokenem dokument serwera jest świeży (bez drukarek), a hub zna
                    # adresy drukarek najlepiej: wysyłamy je jako zmianę na bazie wersji serwera. Przesunięcia
                    # bierzemy z serwera (wspólne w prod_config), drukarki i godziny pracy z huba.
                    dane = copy.deepcopy(dane_serwera)
                    dane['drukarki'] = copy.deepcopy(self.dane['drukarki'])
                    if isinstance(self.dane.get('godziny'), dict):
                        dane['godziny'] = copy.deepcopy(self.dane['godziny'])
                    self.wersja = int(serwer['wersja'])
                    self.oczekujaca = {'wersja_bazowa': self.wersja, 'dane': dane}
                    przejecie = True
                else:
                    self.wersja = int(serwer['wersja'])
                    self.dane = dane_serwera
                self.zapisz()
        if przejecie:
            log.info('Konfiguracja huba przejęta przez nowy dokument CRM — wysyłam drukarki do CRM')
            self.synchronizuj(crm)

    def porzuc_oczekujaca(self, crm, odrzucona):
        """Serwer odrzucił zmianę `odrzucona` (400 bledna_konfiguracja): wracamy do wersji serwera.

        Zmiana zapisana przez użytkownika po wysłaniu odrzuconej zostaje i pójdzie przy kolejnej
        synchronizacji. BladCrm z pobrania przechodzi do wołającego (oczekująca zostaje)."""
        serwer = crm.konfiguracja()
        with self._blokada:
            if self.oczekujaca != odrzucona:
                return
            self.oczekujaca = None
            self.wersja = int(serwer['wersja'])
            self.dane = serwer.get('dane') or {}
            self.zapisz()
