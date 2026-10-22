"""Klient API agenta druku v2 (serwer CRM) — wyłącznie stdlib."""
import http.client
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

PREFIKS = '/api/print-agent/v2'
ROZMIAR_KAWALKA = 64 * 1024


class BladCrm(Exception):
    """Błąd rozmowy z CRM. kod_http=None oznacza brak połączenia / zły format.

    `cialo` to sparsowane ciało odpowiedzi błędu (np. {"error": ..., "bledy": [...]}) albo None."""

    def __init__(self, kod_http, opis, cialo=None):
        super().__init__('%s: %s' % (kod_http, opis))
        self.kod_http = kod_http
        self.opis = opis
        self.cialo = cialo


class NieznanyAgent(BladCrm):
    """401 — token nieznany albo unieważniony."""


class _BezPrzekierowan(urllib.request.HTTPRedirectHandler):
    """Przekierowanie mogłoby przenieść nagłówek z tokenem na obcy host — nie podążamy."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BladCrm(code, 'przekierowanie odrzucone')


_OTWIERACZ = urllib.request.build_opener(_BezPrzekierowan)


def _pochodzenie(url):
    p = urllib.parse.urlsplit(url)
    port = p.port or {'http': 80, 'https': 443}.get(p.scheme)
    return (p.scheme, (p.hostname or '').lower(), port)


class Klient:
    def __init__(self, url, token, limit_s=10):
        self._url = url.rstrip('/')
        self._token = token
        self._limit_s = limit_s

    def __repr__(self):  # token nigdy w reprezentacji
        return 'Klient(url=%r)' % self._url

    # --- niskopoziomowe -------------------------------------------------
    def _zadanie(self, sciezka, metoda='GET', dane=None):
        naglowki = {'Authorization': 'Bearer ' + self._token,
                    'Accept': 'application/json'}
        tresc = None
        if dane is not None:
            tresc = json.dumps(dane).encode('utf-8')
            naglowki['Content-Type'] = 'application/json'
        return urllib.request.Request(self._url + PREFIKS + sciezka, data=tresc,
                                      headers=naglowki, method=metoda)

    def _wywolaj(self, sciezka, metoda='GET', dane=None):
        zadanie = self._zadanie(sciezka, metoda, dane)
        try:
            with _OTWIERACZ.open(zadanie, timeout=self._limit_s) as odp:
                surowe = odp.read()
        except urllib.error.HTTPError as e:
            self._zglos_http(e)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise BladCrm(None, 'brak połączenia: %s' % type(e).__name__) from None
        try:
            return json.loads(surowe.decode('utf-8')) if surowe else {}
        except ValueError:
            raise BladCrm(None, 'odpowiedź nie jest poprawnym JSON-em') from None

    @staticmethod
    def _zglos_http(e):
        try:
            cialo = json.loads(e.read().decode('utf-8'))
        except Exception:
            cialo = None
        if isinstance(cialo, dict) and cialo.get('error'):
            opis = cialo['error']
        else:
            opis = e.reason or 'błąd'
        if e.code == 401:
            raise NieznanyAgent(401, str(opis), cialo) from None
        raise BladCrm(e.code, str(opis), cialo) from None

    # --- metody 1:1 do API serwera -------------------------------------
    def kontakt(self, wersja, drukarki, push, wersja_konfiguracji):
        return self._wywolaj('/kontakt', 'POST', {
            'wersja': wersja, 'drukarki': drukarki, 'push': bool(push),
            'wersja_konfiguracji': wersja_konfiguracji})

    def pobierz(self, drukarka, limit=10):
        return self._wywolaj('/zadania/pobierz', 'POST',
                             {'drukarka': drukarka, 'limit': limit})

    def wysylam(self, id_zadania):
        return self._wywolaj('/zadania/%d/wysylam' % int(id_zadania), 'POST', {})

    def wyniki(self, wyniki):
        return self._wywolaj('/zadania/wyniki', 'POST', {'wyniki': wyniki})

    def konfiguracja(self):
        return self._wywolaj('/konfiguracja')

    def zapisz_konfiguracje(self, wersja_bazowa, dane):
        return self._wywolaj('/konfiguracja', 'PUT',
                             {'wersja_bazowa': wersja_bazowa, 'dane': dane})

    def wynik_polecenia(self, id_polecenia, ok, opis=''):
        return self._wywolaj('/polecenia/%d/wynik' % int(id_polecenia), 'POST',
                             {'ok': bool(ok), 'opis': opis})

    def realtime_token(self):
        return self._wywolaj('/realtime-token')

    def pobierz_plik(self, url, cel):
        """Strumieniuje plik (np. instalator) do `cel`; względny URL dołącza do adresu CRM."""
        pelny = urllib.parse.urljoin(self._url + '/', url)
        if _pochodzenie(pelny) != _pochodzenie(self._url):
            raise BladCrm(None, 'adres pliku spoza serwera CRM — odrzucono')
        zadanie = urllib.request.Request(
            pelny, headers={'Authorization': 'Bearer ' + self._token})
        katalog = os.path.dirname(os.path.abspath(cel))
        os.makedirs(katalog, exist_ok=True)
        fd, tymczasowy = tempfile.mkstemp(dir=katalog, suffix='.part')
        try:
            with os.fdopen(fd, 'wb') as plik:
                try:
                    with _OTWIERACZ.open(zadanie, timeout=self._limit_s) as odp:
                        while True:
                            kawalek = odp.read(ROZMIAR_KAWALKA)
                            if not kawalek:
                                break
                            plik.write(kawalek)
                except urllib.error.HTTPError as e:
                    self._zglos_http(e)
                except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                    raise BladCrm(None, 'brak połączenia: %s' % type(e).__name__) from None
            os.replace(tymczasowy, cel)
        except BaseException:
            try:
                os.remove(tymczasowy)
            except OSError:
                pass
            raise
        return cel
