"""Zatrzymanie usługi (czekanie na porcję) i statyczne reguły instalatora oraz konfiguracji WinSW.

Instalatora Inno Setup nie da się uruchomić w kontenerze Linux — sprawdzamy kolejność i kształt wywołań
w skrypcie; prawdziwe przejście instalatora to lista kontrolna w runbooku (krok na hubie)."""
import re
import types
from pathlib import Path

from agent_druku import __main__ as wejscie, konfiguracja, lokalne_api, petla

PACZKA = Path(__file__).resolve().parents[2] / 'tools' / 'agent_druku' / 'packaging'


def test_zatrzymanie_uslugi_czeka_na_watek_roboczy(monkeypatch):
    zdarzenia = []

    class Watek:
        def __init__(self):
            self.zyje = True
            self.pytania = 0

        def is_alive(self):
            self.pytania += 1
            if self.pytania == 1:
                raise KeyboardInterrupt   # WinSW zatrzymuje usługę Ctrl+C
            return self.zyje

        def join(self, limit=None):
            zdarzenia.append(('join', limit))
            if limit == wejscie.CZEKANIE_NA_PORCJE_S:
                self.zyje = False         # porcja skończona w limicie

    class Agent:
        def __init__(self, sciezki, klient):
            self.lokalna = types.SimpleNamespace(crm_url='', token='')
            self.klient = klient

        def uruchom(self):
            return Watek()

        def zatrzymaj(self):
            zdarzenia.append('zatrzymaj')

    serwer = types.SimpleNamespace(shutdown=lambda: zdarzenia.append('shutdown'),
                                   server_close=lambda: zdarzenia.append('server_close'))
    monkeypatch.setattr(wejscie, '_ustaw_logi', lambda: None)
    monkeypatch.setattr(petla, 'Agent', Agent)
    monkeypatch.setattr(konfiguracja, 'wczytaj_przypiety_adres', lambda: 'https://crm.example.test')
    monkeypatch.setattr(lokalne_api, 'zapewnij_klucz', lambda: 'a' * 64)
    monkeypatch.setattr(lokalne_api, 'uruchom', lambda agent, **kw: serwer)
    assert wejscie.usluga() == 0
    assert zdarzenia == ['zatrzymaj', ('join', 12), 'shutdown', 'server_close']


def test_stoptimeout_winsw_dluzszy_niz_czekanie_na_porcje():
    xml = (PACZKA / 'AgentDrukuUsluga.xml').read_text(encoding='utf-8')
    sekundy = int(re.search(r'<stoptimeout>(\d+) sec</stoptimeout>', xml).group(1))
    assert sekundy >= 15 and sekundy > wejscie.CZEKANIE_NA_PORCJE_S


def _iss():
    return (PACZKA / 'instalator.iss').read_text(encoding='utf-8-sig')


def _cialo(iss, naglowek):
    start = iss.index(naglowek)
    return iss[start:iss.index('\nend;', start)]


def test_instalator_icacls_bez_C():
    """/C ukrywa błędy icacls (kod 0 mimo porażki) — instalacja szłaby dalej z dziurawym ACL."""
    for linia in _iss().splitlines():
        if 'Icacls(' in linia:
            assert ' /C' not in linia, linia


def test_instalator_kolejnosc_uprawnien():
    """setowner → dziecko chronione → rodzic /reset → /inheritance:r /grant:r → dziecko /reset → pliki →
    prawo odczytu klucza dla ikony z powrotem."""
    cialo = _cialo(_iss(), 'function ZabezpieczKatalogi')
    kolejnosc = [cialo.index(x) for x in (
        "Korzen + '\" /setowner",
        "Icacls('\"' + Dane + '\"' + Chron)",
        "Korzen + '\" /reset /Q'",
        "Icacls('\"' + Korzen + '\"' + Chron)",
        "Dane + '\" /reset /Q'",
        "Dane + '\\*\" /reset /T /Q'",
        "Klucz + '\" /grant *S-1-5-4:(R)'",
    )]
    assert kolejnosc == sorted(kolejnosc)
    assert '/inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F' in cialo


def test_instalator_ikony_przed_uprawnieniami_i_katalog_na_bok():
    cialo = _cialo(_iss(), 'function PrepareToInstall')
    ikony = cialo.index('CzekajNaIkony;')
    na_bok = cialo.index('PrzeniesDaneNaBok')
    zabezpiecz = cialo.index('ZabezpieczKatalogi')
    assert ikony < na_bok < zabezpiecz
    assert 'if PierwszaInstalacja then' in cialo[ikony:na_bok]


def test_instalator_dowiazanie_usuwane_nie_sledzone():
    cialo = _cialo(_iss(), 'function PrzeniesDaneNaBok')
    assert '$400' in cialo                       # FILE_ATTRIBUTE_REPARSE_POINT
    assert 'RemoveDir(Korzen)' in cialo and 'RenameFile(Korzen, Cel)' in cialo
    assert "'.przed-instalacja-'" in cialo


def test_instalator_usuwa_zastany_klucz_przy_pierwszej_instalacji():
    cialo = _cialo(_iss(), 'procedure PoInstalacji')
    assert cialo.index("DeleteFile(Dane + '\\klucz_lokalny')") < cialo.index("'klucz') <> 0")
