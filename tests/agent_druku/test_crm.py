import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_druku.crm import BladCrm, Klient, NieznanyAgent


class _Obsluga(BaseHTTPRequestHandler):
    zadania = []
    inny_port = 0

    def log_message(self, *a):
        pass

    def _odp(self, kod, cialo, typ='application/json'):
        surowe = cialo if isinstance(cialo, bytes) else json.dumps(cialo).encode()
        self.send_response(kod)
        self.send_header('Content-Type', typ)
        self.send_header('Content-Length', str(len(surowe)))
        self.end_headers()
        self.wfile.write(surowe)

    def _obsluz(self):
        dlugosc = int(self.headers.get('Content-Length') or 0)
        tresc = json.loads(self.rfile.read(dlugosc)) if dlugosc else None
        _Obsluga.zadania.append((self.command, self.path, self.headers.get('Authorization'), tresc))
        if self.headers.get('Authorization') != 'Bearer dobry':
            return self._odp(401, {'error': 'nieznany_agent'})
        if self.path.endswith('/konfiguracja') and self.command == 'PUT':
            return self._odp(400, {'error': 'bledna_konfiguracja', 'bledy': ['zły adres']})
        if self.path.endswith('/zadania/7/wysylam'):
            return self._odp(409, {'error': 'nie_twoje_zadanie'})
        if self.path.endswith('/przekieruj'):
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1:%d/inny' % _Obsluga.inny_port)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path.endswith('/plik'):
            return self._odp(200, b'x' * 200000, 'application/octet-stream')
        if self.path.endswith('/zepsute'):
            return self._odp(200, b'to nie json')
        if self.path.endswith('/kontakt'):
            return self._odp(200, {'wersja_konfiguracji': 2, 'aktualizacja': None, 'polecenia': []})
        self._odp(200, {'zadania': []})

    do_GET = do_POST = do_PUT = _obsluz


@pytest.fixture
def serwer():
    _Obsluga.zadania = []
    s = HTTPServer(('127.0.0.1', 0), _Obsluga)
    watek = threading.Thread(target=s.serve_forever, daemon=True)
    watek.start()
    yield 'http://127.0.0.1:%d' % s.server_port
    s.shutdown()
    s.server_close()


def test_crm_401_to_nieznany_agent(serwer):
    with pytest.raises(NieznanyAgent) as e:
        Klient(serwer, 'zly').kontakt('2.0.0', [], False, 0)
    assert e.value.kod_http == 401
    assert 'zly' not in str(e.value) and 'zly' not in repr(Klient(serwer, 'zly'))


def test_kontakt_i_sciezki(serwer):
    k = Klient(serwer, 'dobry')
    assert k.kontakt('2.0.0', [{'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': ''}], True, 1)[
        'wersja_konfiguracji'] == 2
    k.pobierz('etykiety', 5)
    k.wyniki([])
    metoda, sciezka, auth, tresc = _Obsluga.zadania[0]
    assert (metoda, sciezka, auth) == ('POST', '/api/print-agent/v2/kontakt', 'Bearer dobry')
    assert tresc['push'] is True and tresc['wersja_konfiguracji'] == 1
    assert _Obsluga.zadania[1][3] == {'drukarka': 'etykiety', 'limit': 5}
    assert _Obsluga.zadania[2][1] == '/api/print-agent/v2/zadania/wyniki'


def test_400_i_409_zachowuja_cialo(serwer):
    k = Klient(serwer, 'dobry')
    with pytest.raises(BladCrm) as e:
        k.zapisz_konfiguracje(1, {})
    assert e.value.kod_http == 400 and e.value.opis == 'bledna_konfiguracja'
    assert e.value.cialo['bledy'] == ['zły adres']
    with pytest.raises(BladCrm) as e:
        k.wysylam(7)
    assert (e.value.kod_http, e.value.opis) == (409, 'nie_twoje_zadanie')


def test_brak_polaczenia_i_zly_json(serwer):
    with pytest.raises(BladCrm) as e:
        Klient('http://127.0.0.1:9', 'dobry', limit_s=1).konfiguracja()
    assert e.value.kod_http is None
    with pytest.raises(BladCrm) as e:
        Klient(serwer, 'dobry')._wywolaj('/zepsute')
    assert e.value.kod_http is None


def test_pobierz_plik_wzgledny_url(serwer, tmp_path):
    cel = tmp_path / 'pod' / 'instalator.exe'
    Klient(serwer, 'dobry').pobierz_plik('/api/print-agent/v2/wydania/2.1.0/plik', str(cel))
    assert cel.read_bytes() == b'x' * 200000
    assert [p.name for p in cel.parent.iterdir()] == ['instalator.exe']


def test_pobierz_plik_blad_nie_zostawia_pliku(serwer, tmp_path):
    cel = tmp_path / 'i.exe'
    with pytest.raises(NieznanyAgent):
        Klient(serwer, 'zly').pobierz_plik('/api/print-agent/v2/wydania/2.1.0/plik', str(cel))
    assert list(tmp_path.iterdir()) == []


def test_pobierz_plik_inny_host_odrzucony(serwer, tmp_path):
    with pytest.raises(BladCrm):
        Klient(serwer, 'dobry').pobierz_plik('http://evil.example/plik', str(tmp_path / 'i.exe'))
    assert _Obsluga.zadania == [] and list(tmp_path.iterdir()) == []


def test_przekierowanie_nie_wysyla_tokenu(serwer, tmp_path):
    drugi = HTTPServer(('127.0.0.1', 0), _Obsluga)
    threading.Thread(target=drugi.serve_forever, daemon=True).start()
    _Obsluga.inny_port = drugi.server_port
    try:
        with pytest.raises(BladCrm):
            Klient(serwer, 'dobry').pobierz_plik('/przekieruj', str(tmp_path / 'i.exe'))
    finally:
        drugi.shutdown()
        drugi.server_close()
    assert all(z[1] != '/inny' for z in _Obsluga.zadania)
    assert list(tmp_path.iterdir()) == []
