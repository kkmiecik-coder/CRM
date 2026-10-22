"""Kanał push agenta druku v2 (port SSE ze starego agenta)."""
import socket
import threading
import time

import pytest

from agent_druku import push
from agent_druku.crm import BladCrm


@pytest.mark.parametrize('linia', ['data: {}', 'data: {}\n', 'data:{}', 'data: ', b'data: {}'])
def test_ping_nie_budzi(linia):
    assert push.klasyfikuj_linie(linia) == ('ping', None)


def test_ramka_powitalna_nie_jest_sygnalem():
    linia = 'data: {"connect":{"client":"c0","version":"6.9.1 OSS","subs":{},"ping":25}}'
    assert push.klasyfikuj_linie(linia) == ('connect', None)


@pytest.mark.parametrize('linia', ['', ': keep-alive', 'event: message', 'id: 5', 'retry: 1000'])
def test_szum_protokolu(linia):
    assert push.klasyfikuj_linie(linia) == ('noise', None)


@pytest.mark.parametrize('rodzaj', ['print', 'config', 'command', 'update'])
def test_publikacja_niesie_rodzaj(rodzaj):
    linia = 'data: {"channel":"print:agent","pub":{"data":{"kind":"%s"}}}' % rodzaj
    assert push.klasyfikuj_linie(linia) == ('signal', rodzaj)


@pytest.mark.parametrize('linia', ['data: {"pub":{"data":{"kind":"inny"}}}',
                                   'data: {"cos_nowego":{"x":1}}', 'data: {niedomkniety'])
def test_nieznana_ramka_budzi_bez_rodzaju(linia):
    assert push.klasyfikuj_linie(linia) == ('signal', None)


def test_drabinka_ponawiania():
    bez_jittera = lambda a, b: 1.0  # noqa: E731
    assert [push.opoznienie(n, bez_jittera) for n in range(0, 10)] == [1, 1, 2, 5, 10, 15, 30, 60, 60, 60]
    assert push.DRABINKA == (1, 2, 5, 10, 15, 30, 60)


def test_drabinka_ma_jitter():
    assert push.opoznienie(4, lambda a, b: a) == pytest.approx(9.0)
    assert push.opoznienie(4, lambda a, b: b) == pytest.approx(11.0)


def test_wygasniecie_tokena_planowe():
    assert push.wygasl_planowo(3600, 3600)
    assert push.wygasl_planowo(3560, 3600)
    assert not push.wygasl_planowo(100, 3600)
    assert not push.wygasl_planowo(3600, None)


def test_limit_nawiazania_krotszy_niz_limit_ciszy():
    assert push.LIMIT_POLACZENIA_S < push.LIMIT_PINGA_S


class _Strumien:
    def __init__(self, linie, wiek=0):
        self.linie = list(linie)
        self.zamkniety = False
        self.expires_in = None
        self.wiek = wiek

    def czytaj_linie(self, limit_s):
        if not self.linie:
            return b''
        linia = self.linie.pop(0)
        if isinstance(linia, Exception):
            raise linia
        return linia

    def czas_zycia(self):
        return self.wiek

    def zamknij(self):
        self.zamkniety = True


class _Klient:
    def __init__(self, odpowiedz=None, blad=None):
        self.odpowiedz = odpowiedz or {'enabled': True, 'token': 't', 'sse_url': 'http://broker/sse',
                                       'expires_in': 3600}
        self.blad = blad

    def realtime_token(self):
        if self.blad:
            raise self.blad
        return self.odpowiedz


def _kanal(klient, strumienie, zdarzenia):
    otwarte = []

    def otworz(adres, token):
        otwarte.append((adres, token))
        if not strumienie:
            raise OSError('broker nie odpowiada')
        return strumienie.pop(0)

    kanal = push.Kanal(klient,
                       przy_polaczeniu=lambda: zdarzenia.append('polaczony'),
                       przy_sygnale=lambda r: zdarzenia.append(('sygnal', r)),
                       przy_rozlaczeniu=lambda: zdarzenia.append('rozlaczony'),
                       otworz=otworz, losuj=lambda a, b: 1.0)
    return kanal, otwarte


def test_polaczenie_i_sygnaly():
    zdarzenia = []
    strumien = _Strumien([b'data: {"connect":{}}', b'data: {}',
                          b'data: {"pub":{"data":{"kind":"print"}}}',
                          b'data: {"pub":{"data":{"kind":"config"}}}'])
    kanal, otwarte = _kanal(_Klient(), [strumien], zdarzenia)
    assert kanal.krok() == 1          # zerwanie przed TTL → pierwszy stopień drabinki
    assert otwarte == [('http://broker/sse', 't')]
    assert zdarzenia == ['polaczony', ('sygnal', 'print'), ('sygnal', 'config'), 'rozlaczony']
    assert strumien.zamkniety
    assert not kanal.polaczony


def test_ponowne_polaczenie_znowu_wola_przy_polaczeniu():
    zdarzenia = []
    kanal, _ = _kanal(_Klient(), [_Strumien([]), _Strumien([])], zdarzenia)
    kanal.krok()
    kanal.krok()
    assert zdarzenia.count('polaczony') == 2


def test_planowe_wygasniecie_bez_czekania():
    zdarzenia = []
    kanal, _ = _kanal(_Klient(), [_Strumien([], wiek=3600)], zdarzenia)
    assert kanal.krok() == 0
    assert kanal.nieudane == 0


def test_cisza_brokera_zamyka_kanal():
    zdarzenia = []
    kanal, _ = _kanal(_Klient(), [_Strumien([socket.timeout('cisza')])], zdarzenia)
    kanal.krok()
    assert zdarzenia == ['polaczony', 'rozlaczony']


def test_realtime_wylaczony_idzie_drabinka():
    zdarzenia = []
    kanal, otwarte = _kanal(_Klient(blad=BladCrm(503, 'SERVICE UNAVAILABLE')), [], zdarzenia)
    assert [kanal.krok() for _ in range(3)] == [1, 2, 5]
    assert otwarte == [] and zdarzenia == []


def test_broker_nie_odpowiada_idzie_drabinka():
    zdarzenia = []
    kanal, otwarte = _kanal(_Klient(), [], zdarzenia)
    assert [kanal.krok() for _ in range(2)] == [1, 2]
    assert len(otwarte) == 2 and zdarzenia == []


def test_brak_adresu_sse_bierze_adres_crm():
    kanal = push.Kanal(_Klient({'enabled': True, 'token': 't'}), lambda: None, lambda r: None,
                       otworz=lambda a, t: (_ for _ in ()).throw(OSError(a)),
                       adres_crm='https://crm.example/')
    assert kanal._adres_sse({}) == 'https://crm.example/realtime/connection/uni_sse'


def test_watek_kanalu_zatrzymuje_sie():
    zdarzenia = []
    blokada = threading.Event()

    class Wiszacy(_Strumien):
        def czytaj_linie(self, limit_s):
            blokada.wait(5)
            return b''

        def zamknij(self):
            self.zamkniety = True
            blokada.set()

    kanal, _ = _kanal(_Klient(), [Wiszacy([])], zdarzenia)
    kanal.uruchom()
    for _ in range(100):
        if kanal.polaczony:
            break
        time.sleep(0.02)
    assert kanal.polaczony
    kanal.zatrzymaj()
    kanal._watek.join(2)
    assert not kanal._watek.is_alive()
    assert zdarzenia[0] == 'polaczony'


def test_limit_czytania_nie_dziedziczy_limitu_nawiazania(monkeypatch):
    """Regresja z produkcji 12.08.2026 (stary agent): kanał rozpadał się co 5 s, bo limit czytania
    ustawiany przez conn.sock po cichu nic nie robił."""
    monkeypatch.setattr(push, 'LIMIT_POLACZENIA_S', 1)
    cisza_s = 3

    def broker(sock):
        conn, _ = sock.accept()
        conn.recv(4096)
        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n')
        conn.sendall(b'data: {"connect":{"ping":25}}\n\n')
        time.sleep(cisza_s)
        conn.sendall(b'data: {"channel":"print:agent","pub":{"data":{"kind":"print"}}}\n\n')
        time.sleep(10)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    threading.Thread(target=broker, args=(srv,), daemon=True).start()

    strumien = push.otworz_sse('http://127.0.0.1:%d/connection/uni_sse' % srv.getsockname()[1], 'token')
    try:
        start = time.monotonic()
        assert push.klasyfikuj_linie(strumien.czytaj_linie(30))[0] == 'connect'
        while True:
            typ, rodzaj = push.klasyfikuj_linie(strumien.czytaj_linie(30))
            if typ == 'signal':
                break
        assert rodzaj == 'print'
        assert time.monotonic() - start >= cisza_s - 0.5
    finally:
        strumien.zamknij()
        srv.close()


def test_szybkie_zerwanie_idzie_drabinka():
    """Broker przyjmuje i od razu rozłącza: każde takie połączenie to porażka, odstępy rosną."""
    zdarzenia = []
    kanal, _ = _kanal(_Klient(), [_Strumien([], wiek=0.5) for _ in range(4)], zdarzenia)
    assert [kanal.krok() for _ in range(4)] == [1, 2, 5, 10]
    assert zdarzenia.count('polaczony') == 4


def test_zerwanie_po_dluzszym_zyciu_zeruje_drabinke():
    zdarzenia = []
    strumienie = [_Strumien([], wiek=1), _Strumien([], wiek=1), _Strumien([], wiek=push.MIN_ZYCIE_S + 30),
                  _Strumien([], wiek=1)]
    kanal, _ = _kanal(_Klient(), strumienie, zdarzenia)
    assert [kanal.krok() for _ in range(4)] == [1, 2, 1, 2]
