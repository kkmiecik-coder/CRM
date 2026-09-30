# -*- coding: utf-8 -*-
"""Agent druku na dwie drukarki (logistyka etap 4, krok 4.1, spec 6.2)."""
import configparser
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
AGENT_DIR = os.path.join(REPO_ROOT, 'tools', 'print_agent')

_spec = importlib.util.spec_from_file_location('print_agent_drukarki', os.path.join(AGENT_DIR, 'print_agent.py'))
print_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(print_agent)

TCP = {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '127.0.0.1', 'port': 9100, 'timeout': 1}
WIN = {'nazwa': 'wysylka', 'type': 'windows', 'name': 'Xprinter XP-410B', 'timeout': 1}


def _cp(tekst):
    cp = configparser.ConfigParser()
    cp.read_string(tekst)
    return cp


def _cfg(**drukarki):
    return {'jobs_limit': 10, 'request_timeout': 5, 'printers': drukarki}


def _zadanie(i, drukarka=None):
    z = {'id': i, 'short_product_id': 'X', 'zpl_payload': '^XA%d^XZ' % i, 'requested_at': None}
    if drukarka:
        z['printer'] = drukarka
    return z


# --- konfiguracja ---

def test_stara_sekcja_printer_to_etykiety():
    d = print_agent.wczytaj_drukarki(_cp('[printer]\nip = 10.0.0.5\nport = 9100\nsend_timeout_seconds = 7\n'))
    assert d == {'etykiety': {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.5',
                              'port': 9100, 'timeout': 7}}


def test_dwie_drukarki_tcp_i_windows():
    d = print_agent.wczytaj_drukarki(_cp(
        '[printer:etykiety]\nip = 10.0.0.5\n'
        '[printer:wysylka]\ntype = windows\nname = Xprinter XP-410B\n'))
    assert d['etykiety'] == {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.5', 'port': 9100, 'timeout': 15}
    assert d['wysylka'] == {'nazwa': 'wysylka', 'type': 'windows', 'name': 'Xprinter XP-410B', 'timeout': 15}


def test_nowa_sekcja_wygrywa_ze_stara():
    d = print_agent.wczytaj_drukarki(_cp('[printer]\nip = 1.1.1.1\n[printer:etykiety]\nip = 2.2.2.2\n'))
    assert d['etykiety']['ip'] == '2.2.2.2'


@pytest.mark.parametrize('tekst', [
    '[crm]\nurl = x\n',                                     # brak drukarek
    '[printer:wysylka]\ntype = usb\nname = X\n',            # nieznany typ
    '[printer:wysylka]\ntype = windows\n',                  # brak nazwy kolejki
    '[printer:wysylka]\ntype = tcp\n',                      # brak ip
    '[printer:wysylka]\ntype = windows\nname =   \n',       # pusta nazwa kolejki
    '[printer:]\nip = 1.1.1.1\n',                           # brak nazwy drukarki
    '[printer:etykiety]\nip = 1.1.1.1\nport = abc\n',       # port nie jest liczbą
])
def test_bledna_konfiguracja_drukarek(tekst):
    with pytest.raises(ValueError):
        print_agent.wczytaj_drukarki(_cp(tekst))


def test_wzor_konfiguracji_jest_poprawny():
    cfg = print_agent.load_config(os.path.join(AGENT_DIR, 'config.example.ini'))
    assert set(cfg['printers']) == {'etykiety'}
    assert 'printer_ip' not in cfg


def test_zapytanie_o_zadania_podaje_drukarke(monkeypatch):
    adresy = []
    monkeypatch.setattr(print_agent, 'crm_request',
                        lambda metoda, url, token, **k: (adresy.append(url), {'jobs': []})[1])
    print_agent.fetch_jobs({'crm_url': 'https://crm', 'jobs_limit': 10, 'token': 't',
                            'request_timeout': 5}, 'wysylka')
    assert adresy == ['https://crm/api/print-agent/jobs?limit=10&printers=wysylka']


# --- kierowanie zadań ---

def test_kazda_drukarka_pobiera_swoja_kolejke(monkeypatch):
    kolejki = {'etykiety': [_zadanie(1, 'etykiety')], 'wysylka': [_zadanie(2, 'wysylka')]}
    pobrania, wyslane = [], []
    monkeypatch.setattr(print_agent, 'fetch_jobs',
                        lambda c, n: (pobrania.append(n), {'jobs': kolejki[n]})[1])
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: wyslane.append((d['nazwa'], z)))
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})
    assert print_agent.run_once(_cfg(etykiety=TCP, wysylka=WIN)) is True
    assert pobrania == ['etykiety', 'wysylka']
    assert wyslane == [('etykiety', '^XA1^XZ'), ('wysylka', '^XA2^XZ')]


def test_martwa_drukarka_paczek_nie_wstrzymuje_etykiet(monkeypatch):
    """Pełna kolejka martwej drukarki paczek nie może zasłonić etykiet produktów."""
    kolejki = {'wysylka': [_zadanie(i, 'wysylka') for i in range(10)],
               'etykiety': [_zadanie(100, 'etykiety')]}
    wyslane, potwierdzone = [], []

    def druk(d, z):
        if d['nazwa'] == 'wysylka':
            raise OSError('drukarka paczek nie odpowiada')
        wyslane.append(z)

    monkeypatch.setattr(print_agent, 'fetch_jobs', lambda c, n: {'jobs': kolejki[n]})
    monkeypatch.setattr(print_agent, 'send_to_printer', druk)
    monkeypatch.setattr(print_agent, 'log_printer_status', lambda d: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: (potwierdzone.extend(r), {'updated': len(r)})[1])
    stan = {}
    print_agent.run_once(_cfg(wysylka=WIN, etykiety=TCP), stan=stan)
    assert wyslane == ['^XA100^XZ']
    assert [r['id'] for r in potwierdzone if not r['success']] == [0], 'jedna próba na martwej drukarce'
    assert stan.get('drukarka_padla') is True


def test_stary_serwer_bez_pola_printer(monkeypatch):
    """Serwer sprzed etapu 4 ignoruje ?printers= i nie podaje drukarki: każde zadanie
    to etykieta produktu — drukarka paczek nie może jej wydrukować ani potwierdzić."""
    wyslane, potwierdzone = [], []
    monkeypatch.setattr(print_agent, 'fetch_jobs', lambda c, n: {'jobs': [_zadanie(5)]})
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: wyslane.append(d['nazwa']))
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: (potwierdzone.extend(r), {'updated': len(r)})[1])
    print_agent.run_once(_cfg(etykiety=TCP, wysylka=WIN))
    assert wyslane == ['etykiety']
    assert [r['id'] for r in potwierdzone] == [5]


def test_cudza_pelna_porcja_nie_zapetla_oprozniania(monkeypatch):
    pobrania = []
    monkeypatch.setattr(print_agent, 'fetch_jobs',
                        lambda c, n: (pobrania.append(n), {'jobs': [_zadanie(i) for i in range(10)]})[1])
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda d, z: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})
    print_agent.run_once(_cfg(wysylka=WIN))
    assert pobrania == ['wysylka'], 'porcja z samymi cudzymi zadaniami kończy cykl drukarki'


def test_nieznana_drukarka_w_konfiguracji_bez_pola_printers():
    """Słownik bez 'printers' (starsze wywołania, testy SSE) = jedna drukarka TCP 'etykiety'."""
    d = print_agent._drukarki({'printer_ip': '10.0.0.9', 'printer_port': 9100, 'printer_timeout': 3})
    assert d == {'etykiety': {'nazwa': 'etykiety', 'type': 'tcp', 'ip': '10.0.0.9', 'port': 9100, 'timeout': 3}}


# --- kolejka Windows ---

class _FakeWinspool:
    def __init__(self, otworz=True, zapisz_ile=None):
        self.otworz = otworz
        self.zapisz_ile = zapisz_ile
        self.wywolania = []
        self.dane = None

    def OpenPrinterW(self, nazwa, uchwyt, _domyslne):
        self.wywolania.append(('open', nazwa))
        if not self.otworz:
            return 0
        uchwyt._obj.value = 42
        return 1

    def StartDocPrinterW(self, uchwyt, poziom, info):
        self.wywolania.append(('doc', info._obj.pDatatype))
        return 7

    def StartPagePrinter(self, uchwyt):
        self.wywolania.append(('page',))
        return 1

    def WritePrinter(self, uchwyt, bufor, dlugosc, zapisane):
        self.dane = bufor.raw[:dlugosc]
        zapisane._obj.value = dlugosc if self.zapisz_ile is None else self.zapisz_ile
        self.wywolania.append(('write', dlugosc))
        return 1

    def EndPagePrinter(self, uchwyt):
        self.wywolania.append(('endpage',))
        return 1

    def EndDocPrinter(self, uchwyt):
        self.wywolania.append(('enddoc',))
        return 1

    def ClosePrinter(self, uchwyt):
        self.wywolania.append(('close',))
        return 1


def test_windows_wysyla_surowe_bajty(monkeypatch):
    fake = _FakeWinspool()
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    print_agent.send_to_printer(WIN, '^XA^XZ')
    assert fake.dane == b'^XA^XZ'
    assert fake.wywolania == [('open', 'Xprinter XP-410B'), ('doc', 'RAW'), ('page',), ('write', 6),
                              ('endpage',), ('enddoc',), ('close',)]


def test_windows_brak_kolejki_to_blad_drukarki(monkeypatch):
    fake = _FakeWinspool(otworz=False)
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    with pytest.raises(OSError) as blad:
        print_agent.send_to_printer(WIN, '^XA^XZ')
    assert 'Xprinter XP-410B' in str(blad.value)
    assert ('close',) not in fake.wywolania


def test_windows_niepelny_zapis_to_blad_i_zamyka_kolejke(monkeypatch):
    fake = _FakeWinspool(zapisz_ile=2)
    monkeypatch.setattr(print_agent, '_winspool', lambda: fake)
    with pytest.raises(OSError):
        print_agent.send_to_printer(WIN, '^XA^XZ')
    assert fake.wywolania[-2:] == [('enddoc',), ('close',)]


def test_windows_bez_zapytan_o_stan():
    wyniki = print_agent.query_printer_status(WIN)
    assert len(wyniki) == 1 and 'Windows' in wyniki[0][2]


# --- kalibracja ---

def test_kalibracja_wysyla_gapdetect(monkeypatch):
    wyslane = []
    monkeypatch.setattr(print_agent, 'wyslij_surowe', lambda d, b: wyslane.append((d['nazwa'], b)))
    print_agent.kalibruj(_cfg(wysylka=WIN), 'wysylka')
    assert wyslane == [('wysylka', b'GAPDETECT\r\n')]


def test_kalibracja_nieznanej_drukarki():
    with pytest.raises(ValueError):
        print_agent.kalibruj(_cfg(wysylka=WIN), 'etykiety')
