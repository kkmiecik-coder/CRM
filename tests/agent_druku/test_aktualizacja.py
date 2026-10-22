"""Aktualizacja agenta druku: pobranie instalatora, suma SHA-256, uruchomienie odłączone."""
import hashlib
import json
import os
import time
import types

import pytest

from agent_druku import aktualizacja
from agent_druku.crm import BladCrm
from tests.agent_druku.test_lokalne_api import TOKEN, _zapytaj, uslugi, sciezki  # noqa: F401
from tests.agent_druku.test_petla import Crm

INSTALATOR = b'MZ' + b'\x00instalator agenta druku' * 100
SUMA = hashlib.sha256(INSTALATOR).hexdigest()


def _info(**zmiany):
    info = {'wersja': '2.0.1', 'sha256': SUMA, 'rozmiar': len(INSTALATOR),
            'url': '/api/print-agent/v2/wydania/7/plik'}
    info.update(zmiany)
    return info


class KlientPlikow:
    """Atrapa crm.Klient.pobierz_plik: zapisuje zadaną treść pod `cel`."""

    def __init__(self, tresc=INSTALATOR, blad=None):
        self.tresc = tresc
        self.blad = blad
        self.pobrane = []

    def pobierz_plik(self, url, cel):
        self.pobrane.append((url, str(cel)))
        if self.blad is not None:
            raise self.blad
        with open(cel, 'wb') as f:
            f.write(self.tresc)
        return cel


class Popen:
    """Atrapa subprocess.Popen — zapisuje wywołania, niczego nie uruchamia."""
    wywolania = []

    def __init__(self, args, **kw):
        Popen.wywolania.append((args, kw))


@pytest.fixture(autouse=True)
def katalog(tmp_path, monkeypatch):
    Popen.wywolania = []
    monkeypatch.setattr(aktualizacja.subprocess, 'Popen', Popen)
    monkeypatch.setattr(aktualizacja.sciezki, 'katalog_danych', lambda: tmp_path / 'dane')
    monkeypatch.setenv('SystemRoot', r'C:\Windows')
    return tmp_path / 'dane' / 'aktualizacje'


def test_zla_suma_nie_uruchamia_instalatora(katalog):
    postep = aktualizacja.Postep()
    agent = types.SimpleNamespace(klient=KlientPlikow(tresc=INSTALATOR + b'podmieniony'))

    assert aktualizacja.wykonaj(agent, _info(rozmiar=None), postep) is False

    assert Popen.wywolania == []
    assert list(katalog.iterdir()) == []          # plik usunięty
    stan = postep.stan()
    assert stan['postep'] == 'blad'
    assert 'suma kontrolna' in stan['blad']


def test_zly_rozmiar_nie_uruchamia_instalatora(katalog):
    postep = aktualizacja.Postep()
    agent = types.SimpleNamespace(klient=KlientPlikow())

    assert aktualizacja.wykonaj(agent, _info(rozmiar=len(INSTALATOR) + 1), postep) is False

    assert Popen.wywolania == []
    assert list(katalog.iterdir()) == []
    assert postep.stan()['postep'] == 'blad'


def test_dobra_suma_uruchamia_odlaczony(katalog):
    postep = aktualizacja.Postep()
    klient = KlientPlikow()
    agent = types.SimpleNamespace(klient=klient)

    assert aktualizacja.wykonaj(agent, _info(sha256=SUMA.upper()), postep) is True

    plik = katalog / 'AgentDruku-2.0.1-setup.exe'
    assert klient.pobrane == [('/api/print-agent/v2/wydania/7/plik', str(plik))]
    assert plik.read_bytes() == INSTALATOR
    assert len(Popen.wywolania) == 1
    args, kw = Popen.wywolania[0]
    tekst = args if isinstance(args, str) else ' '.join(args)
    assert '"%s"' % plik in tekst
    for przelacznik in ('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'):
        assert przelacznik in tekst
    flagi = kw['creationflags']
    assert flagi & aktualizacja.DETACHED_PROCESS
    assert flagi & aktualizacja.CREATE_NEW_PROCESS_GROUP
    assert kw.get('close_fds') is True
    assert postep.stan()['postep'] == 'instalacja'


def test_blad_pobierania_nie_uruchamia_instalatora(katalog):
    postep = aktualizacja.Postep()
    agent = types.SimpleNamespace(klient=KlientPlikow(
        blad=BladCrm(None, 'adres pliku spoza serwera CRM — odrzucono')))

    assert aktualizacja.wykonaj(agent, _info(), postep) is False

    assert Popen.wywolania == []
    assert postep.stan() == {'postep': 'blad', 'wersja': '2.0.1',
                             'blad': 'adres pliku spoza serwera CRM — odrzucono'}


@pytest.mark.parametrize('zle', [
    {'wersja': '..\\..\\Windows\\zly'}, {'wersja': ''}, {'sha256': 'abc'}, {'url': ''}])
def test_zle_informacje_odrzucone_bez_pobierania(katalog, zle):
    postep = aktualizacja.Postep()
    klient = KlientPlikow()

    assert aktualizacja.wykonaj(types.SimpleNamespace(klient=klient), _info(**zle), postep) is False

    assert klient.pobrane == [] and Popen.wywolania == []
    assert postep.stan()['postep'] == 'blad'


def test_stare_instalatory_sprzatane(katalog):
    katalog.mkdir(parents=True)
    (katalog / 'AgentDruku-2.0.0-setup.exe').write_bytes(b'stary')
    (katalog / 'tmp123.part').write_bytes(b'przerwany')

    assert aktualizacja.wykonaj(types.SimpleNamespace(klient=KlientPlikow()), _info(),
                                aktualizacja.Postep()) is True

    assert sorted(p.name for p in katalog.iterdir()) == ['AgentDruku-2.0.1-setup.exe']


def test_powrot_zasobnika_bez_wstrzykniecia():
    args = aktualizacja.polecenie_powrotu_zasobnika(r"C:\Program Files\Wood'Power\AgentDruku.exe",
                                                    '2.0.1')
    skrypt = args[-1]
    assert "'C:\\Program Files\\Wood''Power\\AgentDruku.exe'" in skrypt
    assert "'AgentDruku-2.0.1-setup'" in skrypt
    with pytest.raises(ValueError):
        aktualizacja.polecenie_powrotu_zasobnika(r'C:\a.exe', "1'; Remove-Item C:\\ -Recurse; '")


# --- lokalne API ----------------------------------------------------------
class CrmZPlikiem(Crm):
    def __init__(self):
        super().__init__()
        self.pliki = KlientPlikow()

    def pobierz_plik(self, url, cel):
        return self.pliki.pobierz_plik(url, cel)


def _czekaj_na_postep(port, oczekiwany):
    koniec = time.monotonic() + 5
    while time.monotonic() < koniec:
        kod, tresc = _zapytaj(port, 'GET', '/stan')
        akt = json.loads(tresc).get('aktualizacja') or {}
        if akt.get('postep') == oczekiwany:
            return akt
        time.sleep(0.02)
    raise AssertionError('brak postępu %s w /stan: %s' % (oczekiwany, tresc))


def test_aktualizacja_bez_informacji_409(uslugi):
    kod, tresc = _zapytaj(uslugi.port, 'POST', '/aktualizacja', {})
    assert kod == 409
    assert json.loads(tresc)['error'] == 'brak_aktualizacji'
    assert Popen.wywolania == []


def test_aktualizacja_202_i_postep_w_stanie(uslugi, monkeypatch):
    s = uslugi
    crm = CrmZPlikiem()
    crm.aktualizacja = _info()
    s.agent.sparuj('https://crm.example.test', TOKEN, lambda url, token: crm)
    s.agent.cykl('test')     # /kontakt podaje informację o aktualizacji
    assert s.agent.stan_dla_okienka()['aktualizacja'] == _info()

    kod, tresc = _zapytaj(s.port, 'POST', '/aktualizacja')
    assert kod == 202, tresc

    akt = _czekaj_na_postep(s.port, 'instalacja')
    assert akt['wersja'] == '2.0.1' and akt['sha256'] == SUMA
    assert len(Popen.wywolania) == 1
    assert TOKEN not in json.dumps(akt)


def test_aktualizacja_zla_suma_widoczna_w_stanie(uslugi):
    s = uslugi
    crm = CrmZPlikiem()
    crm.aktualizacja = _info(sha256='0' * 64)
    s.agent.sparuj('https://crm.example.test', TOKEN, lambda url, token: crm)
    s.agent.cykl('test')

    assert _zapytaj(s.port, 'POST', '/aktualizacja')[0] == 202

    akt = _czekaj_na_postep(s.port, 'blad')
    assert 'suma kontrolna' in akt['blad']
    assert Popen.wywolania == []
    assert not any(n.endswith('.exe') for n in os.listdir(aktualizacja.katalog_aktualizacji()))


def test_aktualizacja_w_toku_409(uslugi):
    s = uslugi
    crm = CrmZPlikiem()
    crm.aktualizacja = _info()
    s.agent.sparuj('https://crm.example.test', TOKEN, lambda url, token: crm)
    s.agent.cykl('test')
    s.serwer.postep_aktualizacji.zajmij(_info())   # pobieranie trwa

    kod, tresc = _zapytaj(s.port, 'POST', '/aktualizacja')
    assert kod == 409
    assert json.loads(tresc)['error'] == 'aktualizacja_trwa'


def test_instalacja_bez_restartu_uslugi_staje_sie_bledem():
    teraz = [100.0]
    postep = aktualizacja.Postep(zegar=lambda: teraz[0])
    postep.ustaw('instalacja', '2.0.1')
    teraz[0] += aktualizacja.LIMIT_INSTALACJI_S - 1
    assert postep.stan()['postep'] == 'instalacja'
    teraz[0] += 2
    stan = postep.stan()
    assert stan['postep'] == 'blad' and 'instalacja.log' in stan['blad']
    assert postep.zajmij(_info()) is True     # można spróbować ponownie


def test_tryb_klucz_zaklada_klucz_dla_instalatora(tmp_path, monkeypatch):
    from agent_druku import __main__ as wejscie, sciezki as sc
    monkeypatch.setattr(sc, 'katalog_danych', lambda: tmp_path / 'dane')

    assert wejscie.main(['klucz']) == 0
    klucz = (tmp_path / 'dane' / 'klucz_lokalny').read_text(encoding='ascii')
    assert len(klucz) == 64
    assert wejscie.main(['klucz']) == 0          # drugi raz bez zmiany
    assert (tmp_path / 'dane' / 'klucz_lokalny').read_text(encoding='ascii') == klucz


def test_instalator_spoza_serwera_crm_odrzucony(katalog):
    from agent_druku import crm
    postep = aktualizacja.Postep()
    agent = types.SimpleNamespace(klient=crm.Klient('https://crm.example.test', 'tok'))

    assert aktualizacja.wykonaj(agent, _info(url='https://zly.example.test/setup.exe'), postep) is False

    assert Popen.wywolania == []
    assert 'spoza serwera CRM' in postep.stan()['blad']
    assert list(katalog.iterdir()) == []
