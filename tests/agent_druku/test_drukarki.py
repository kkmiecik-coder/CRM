"""Transport z budzeniem i stan drukarek (agent druku v2)."""
import socket
import types

import pytest

from agent_druku import drukarki


class _ZegarTestowy:
    """sleep przesuwa zegar zamiast czekać."""
    def __init__(self):
        self.teraz = 1000.0

    def monotonic(self):
        return self.teraz

    def sleep(self, s):
        self.teraz += s


class _Gniazdo:
    def __init__(self, awaria_na_sendall=None):
        self.awaria_na_sendall = awaria_na_sendall
        self.blad_recv = None
        self.wyslane = []
        self.zdarzenia = []

    def __enter__(self):
        return self

    def __exit__(self, *wyjatek):
        self.zdarzenia.append('close')
        return False

    def settimeout(self, t):
        pass

    def sendall(self, dane):
        if self.awaria_na_sendall is not None and len(self.wyslane) + 1 == self.awaria_na_sendall:
            raise ConnectionResetError('reset')
        self.wyslane.append(dane)
        self.zdarzenia.append('sendall')

    def shutdown(self, jak):
        assert jak == socket.SHUT_WR
        self.zdarzenia.append('shutdown')

    def recv(self, n):
        self.zdarzenia.append('recv')
        if self.blad_recv is not None:
            raise self.blad_recv
        return b''


@pytest.fixture
def zegar(monkeypatch):
    z = _ZegarTestowy()
    monkeypatch.setattr(drukarki, 'time', types.SimpleNamespace(monotonic=z.monotonic, sleep=z.sleep))
    return z


@pytest.fixture(autouse=True)
def _czysty_stan():
    drukarki._ostatnie_polaczenie.clear()
    yield
    drukarki._ostatnie_polaczenie.clear()


def _timeout(nr):
    raise OSError('timed out')


def _podstaw_polaczenia(monkeypatch, zegar, fabryka):
    """fabryka(nr_proby) -> gniazdo albo rzuca OSError; nieudana próba zjada swój timeout."""
    proby = []

    def polacz(adres, timeout=None):
        proby.append(adres)
        try:
            return fabryka(len(proby))
        except OSError:
            zegar.teraz += timeout
            raise

    monkeypatch.setattr(drukarki, 'socket', types.SimpleNamespace(
        create_connection=polacz, SHUT_WR=socket.SHUT_WR))
    return proby


def _drukarka(**dodatki):
    d = {'nazwa': 'wysylka', 'ip': '10.0.0.7', 'port': 9100, 'model': 'XP-410B',
         'odczyt_stanu': 'brak', 'limit_wysylki_s': 15}
    d.update(dodatki)
    return d


def _zadania(*ids):
    return [{'id': i, 'zpl': f'^XA{i}^XZ'} for i in ids]


def test_budzenie_trzecia_proba(monkeypatch, zegar):
    gniazdo = _Gniazdo()

    def fabryka(nr):
        if nr < 3:
            raise OSError('timed out')
        return gniazdo

    proby = _podstaw_polaczenia(monkeypatch, zegar, fabryka)
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1), lambda i: True)
    assert len(proby) == 3
    assert wynik == [{'id': 1, 'wynik': 'wydrukowane'}]
    assert gniazdo.wyslane == [b'^XA1^XZ']


def test_brak_polaczenia_wszystko_niewyslane(monkeypatch, zegar):
    wolane = []
    proby = _podstaw_polaczenia(monkeypatch, zegar, _timeout)
    start = zegar.teraz
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1, 2), lambda i: wolane.append(i) or True)
    assert wynik == [{'id': 1, 'wynik': 'niewyslane'}, {'id': 2, 'wynik': 'niewyslane'}]
    assert wolane == []                                  # bez połączenia nic nie zgłaszamy
    assert len(proby) > 1
    assert zegar.teraz - start <= drukarki.BUDZENIE_LIMIT_S + drukarki.BUDZENIE_PROBA_S
    assert drukarki.stan(_drukarka())[0] == 'offline'


def test_jedno_polaczenie_na_porcje(monkeypatch, zegar):
    gniazda = []

    def fabryka(nr):
        gniazda.append(_Gniazdo())
        return gniazda[-1]

    proby = _podstaw_polaczenia(monkeypatch, zegar, fabryka)
    zgloszone = []
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1, 2, 3), lambda i: zgloszone.append(i) or True)
    assert len(proby) == 1
    assert [w['wynik'] for w in wynik] == ['wydrukowane'] * 3
    assert zgloszone == [1, 2, 3]
    # Kolejność: 3x sendall, potem shutdown, czekanie na zamknięcie (recv), close.
    assert gniazda[0].zdarzenia == ['sendall'] * 3 + ['shutdown', 'recv', 'close']


def test_blad_w_polowie_reszta_niewyslane(monkeypatch, zegar):
    gniazdo = _Gniazdo(awaria_na_sendall=2)
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1, 2, 3), lambda i: True)
    assert wynik[0] == {'id': 1, 'wynik': 'wydrukowane'}
    assert wynik[1]['wynik'] == 'blad' and 'reset' in wynik[1]['blad']
    assert wynik[2] == {'id': 3, 'wynik': 'niewyslane'}
    assert 'shutdown' not in gniazdo.zdarzenia


def test_przed_wyslaniem_false_pomija_zadanie(monkeypatch, zegar):
    gniazdo = _Gniazdo()
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1, 2), lambda i: i != 1)
    assert wynik == [{'id': 1, 'wynik': 'niewyslane'}, {'id': 2, 'wynik': 'wydrukowane'}]
    assert gniazdo.wyslane == [b'^XA2^XZ']


def test_wyjatek_w_przed_wyslaniem_zatrzymuje_porcje(monkeypatch, zegar):
    gniazdo = _Gniazdo()
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)

    def zgloszenie(i):
        if i == 2:
            raise OSError('serwer nie odpowiada')
        return True

    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1, 2, 3), zgloszenie)
    assert [w['wynik'] for w in wynik] == ['wydrukowane', 'niewyslane', 'niewyslane']
    assert gniazdo.wyslane == [b'^XA1^XZ']


def test_kalibruj_wysyla_gapdetect(monkeypatch, zegar):
    gniazdo = _Gniazdo()
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)
    drukarki.kalibruj(_drukarka())
    assert gniazdo.wyslane == [b'GAPDETECT\r\n']


def test_kalibruj_bez_polaczenia_rzuca_niedostepna(monkeypatch, zegar):
    _podstaw_polaczenia(monkeypatch, zegar, _timeout)
    with pytest.raises(drukarki.DrukarkaNiedostepna):
        drukarki.kalibruj(_drukarka())


def _snmp_odpowiedz(monkeypatch, status=3, bledy=b'\x00', konsola=b'Online'):
    odp = {drukarki.OID_STATUS: status, drukarki.OID_BLEDY: bledy, drukarki.OID_KONSOLA: konsola}
    monkeypatch.setattr(drukarki.snmp, 'pobierz', lambda ip, oidy, limit_s=2: dict(odp))


_XP423 = {'nazwa': 'etykiety', 'ip': '10.0.0.8', 'port': 9100, 'model': 'XP-423B',
          'odczyt_stanu': 'snmp', 'limit_wysylki_s': 15}


def test_snmp_gotowa_jak_na_prawdziwej_drukarce(monkeypatch):
    _snmp_odpowiedz(monkeypatch)
    assert drukarki.stan(_XP423) == ('gotowa', 'Online')


def test_snmp_brak_papieru(monkeypatch):
    _snmp_odpowiedz(monkeypatch, bledy=b'\x40', konsola=b'Paper Out')
    assert drukarki.stan(_XP423) == ('brak_papieru', 'Paper Out')


@pytest.mark.parametrize('bajt, oczekiwany', [
    (0x08, 'otwarta_klapa'), (0x04, 'blad'), (0x02, 'offline')])
def test_snmp_pozostale_bity(monkeypatch, bajt, oczekiwany):
    _snmp_odpowiedz(monkeypatch, bledy=bytes([bajt]), konsola=b'')
    assert drukarki.stan(_XP423)[0] == oczekiwany


def test_snmp_malo_papieru_nie_zmienia_stanu(monkeypatch):
    _snmp_odpowiedz(monkeypatch, bledy=b'\x80')
    stan, opis = drukarki.stan(_XP423)
    assert stan == 'gotowa' and 'mało papieru' in opis


@pytest.mark.parametrize('status, oczekiwany', [
    (1, 'blad'), (2, 'nieznany'), (3, 'gotowa'), (4, 'gotowa'), (5, 'gotowa')])
def test_snmp_hr_printer_status(monkeypatch, status, oczekiwany):
    _snmp_odpowiedz(monkeypatch, status=status, konsola=b'')
    assert drukarki.stan(_XP423)[0] == oczekiwany


def test_snmp_cisza_to_nieznany(monkeypatch):
    monkeypatch.setattr(drukarki.snmp, 'pobierz', lambda ip, oidy, limit_s=2: {})
    assert drukarki.stan(_XP423)[0] == 'nieznany'


def test_bez_odczytu_stan_z_polaczenia(monkeypatch, zegar):
    d = _drukarka()
    assert drukarki.stan(d)[0] == 'nieznany'             # przed pierwszą próbą
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: _Gniazdo())
    drukarki.wyslij_porcje(d, _zadania(1), lambda i: True)
    assert drukarki.stan(d)[0] == 'gotowa'
    _podstaw_polaczenia(monkeypatch, zegar, _timeout)
    drukarki.wyslij_porcje(d, _zadania(2), lambda i: True)
    assert drukarki.stan(d)[0] == 'offline'


def test_stan_bez_odczytu_jest_osobny_dla_kazdej_drukarki(monkeypatch, zegar):
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: _Gniazdo())
    drukarki.wyslij_porcje(_drukarka(nazwa='wysylka'), _zadania(1), lambda i: True)
    assert drukarki.stan(_drukarka(nazwa='etykiety'))[0] == 'nieznany'


@pytest.mark.parametrize('lt, ls', [(0, 0), (3, -4), (-8, 12)])
def test_zpl_probny_zgodny_z_serwerem_etykiety(lt, ls):
    from modules.production.services import print_queue_service
    assert (drukarki.zpl_probny('etykiety', {'lt': lt, 'ls': ls})
            == print_queue_service._zpl_probny_etykiet(lt, ls))


@pytest.mark.parametrize('x, y', [(0, 0), (16, -8), (-120, 120)])
def test_zpl_probny_zgodny_z_serwerem_paczki(x, y):
    from modules.production.services import package_label
    assert (drukarki.zpl_probny('wysylka', {'dx': x, 'dy': y})
            == package_label.generate_test_label_zpl((x, y)))


def test_zpl_probny_nieznana_drukarka():
    with pytest.raises(ValueError):
        drukarki.zpl_probny('inna', {})


def test_zpl_probny_brakujace_klucze_to_blad():
    with pytest.raises(ValueError, match='lt'):
        drukarki.zpl_probny('etykiety', {'ls': 1})
    with pytest.raises(ValueError, match='dy'):
        drukarki.zpl_probny('wysylka', {'dx': 1})
    with pytest.raises(ValueError):
        drukarki.zpl_probny('wysylka', {'x': 1, 'y': 2})   # stare klucze nie przechodzą


def test_reset_przy_zamknieciu_porcja_blad(monkeypatch, zegar):
    gniazdo = _Gniazdo()
    gniazdo.blad_recv = ConnectionResetError('reset')
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)
    d = _drukarka()
    wynik = drukarki.wyslij_porcje(d, _zadania(1, 2), lambda i: True)
    assert [w['wynik'] for w in wynik] == ['blad', 'blad']
    assert all(w['blad'] == drukarki.BLAD_ZAMKNIECIA for w in wynik)
    assert drukarki.stan(d)[0] == 'offline'


def test_czyste_zamkniecie_wydrukowane(monkeypatch, zegar):
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: _Gniazdo())
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1), lambda i: True)
    assert wynik == [{'id': 1, 'wynik': 'wydrukowane'}]


def test_cisza_przy_zamknieciu_bez_bledu_to_wydrukowane(monkeypatch, zegar):
    gniazdo = _Gniazdo()
    gniazdo.blad_recv = socket.timeout('timed out')
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: gniazdo)
    wynik = drukarki.wyslij_porcje(_drukarka(), _zadania(1), lambda i: True)
    assert wynik == [{'id': 1, 'wynik': 'wydrukowane'}]


def test_blad_w_polowie_ustawia_offline(monkeypatch, zegar):
    _podstaw_polaczenia(monkeypatch, zegar, lambda nr: _Gniazdo(awaria_na_sendall=1))
    d = _drukarka()
    drukarki.wyslij_porcje(d, _zadania(1), lambda i: True)
    assert drukarki.stan(d)[0] == 'offline'


def test_wysylki_do_jednej_drukarki_nie_przeplataja_sie(monkeypatch):
    """Wydruk próbny/kalibracja z okienka czeka na trwającą porcję tej samej drukarki."""
    import threading
    import time as czas

    w_porcji = threading.Event()
    zwolnij = threading.Event()
    kolejnosc = []

    class Gniazdo:
        def __init__(self, nazwa):
            self.nazwa = nazwa

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, s):
            pass

        def sendall(self, dane):
            kolejnosc.append((self.nazwa, dane))
            if dane == b'porcja':
                w_porcji.set()
                zwolnij.wait(5)

    def polacz(drukarka):
        return Gniazdo(threading.current_thread().name)

    monkeypatch.setattr(drukarki, '_polacz_z_budzeniem', polacz)
    monkeypatch.setattr(drukarki, '_zamknij_po_wyslaniu', lambda sock: True)
    d = {'nazwa': 'etykiety', 'ip': '192.0.2.1', 'port': 9100, 'limit_wysylki_s': 5}

    porcja = threading.Thread(name='porcja', target=lambda: drukarki.wyslij_porcje(
        d, [{'id': 1, 'zpl': 'porcja'}], lambda _id: True))
    kalibracja = threading.Thread(name='kalibracja', target=lambda: drukarki.kalibruj(d))
    porcja.start()
    assert w_porcji.wait(5)
    kalibracja.start()
    czas.sleep(0.2)
    assert [k for k, _ in kolejnosc] == ['porcja']   # kalibracja czeka na blokadę
    zwolnij.set()
    porcja.join(5)
    kalibracja.join(5)
    assert [k for k, _ in kolejnosc] == ['porcja', 'kalibracja']
