"""Lokalne API usługi agenta druku (127.0.0.1) — bez GUI, z atrapą CRM i drukarek."""
import json
import threading
import time
import types
import urllib.error
import urllib.request

import pytest

from agent_druku import lokalne_api, petla
from tests.agent_druku.test_petla import KONFIGURACJA, Crm, Drukarki

KLUCZ = 'k' * 64
TOKEN = 'tajny-token-agenta-123'
ADRES_CRM = 'https://crm.example.test'   # przypięty instalatorem


@pytest.fixture
def sciezki(tmp_path):
    return types.SimpleNamespace(plik_konfiguracji=lambda: tmp_path / 'konfiguracja.json',
                                 plik_dziennika=lambda: tmp_path / 'dziennik.db')


@pytest.fixture
def uslugi(sciezki, tmp_path):
    """Agent (bez klienta CRM) + lokalne API na losowym porcie."""
    crm, druk = Crm(), Drukarki()
    fabryki = []

    def fabryka(url, token):
        fabryki.append((url, token))
        return crm

    agent = petla.Agent(sciezki, None, drukarki=druk)
    serwer = lokalne_api.uruchom(agent, port=0, klucz=KLUCZ, fabryka_klienta=fabryka,
                                 plik_logu=tmp_path / 'agent.log', adres_crm=ADRES_CRM)
    yield types.SimpleNamespace(agent=agent, serwer=serwer, crm=crm, druk=druk, fabryki=fabryki,
                                port=serwer.server_address[1], sciezki=sciezki)
    agent.zatrzymaj()
    serwer.shutdown()
    serwer.server_close()
    agent.dziennik.zamknij()


def _zapytaj(port, metoda, sciezka, dane=None, klucz=KLUCZ):
    naglowki = {}
    if klucz is not None:
        naglowki['X-Klucz'] = klucz
    tresc = None
    if dane is not None:
        tresc = json.dumps(dane).encode('utf-8')
        naglowki['Content-Type'] = 'application/json'
    zad = urllib.request.Request('http://127.0.0.1:%d%s' % (port, sciezka), data=tresc,
                                 headers=naglowki, method=metoda)
    try:
        with urllib.request.urlopen(zad, timeout=5) as odp:
            return odp.status, odp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


def test_bez_klucza_403(uslugi):
    for metoda, sciezka in (('GET', '/stan'), ('POST', '/ponow-zalegle'), ('GET', '/konfiguracja'),
                            ('GET', '/log'), ('POST', '/nie-ma-takiej')):
        assert _zapytaj(uslugi.port, metoda, sciezka, {} if metoda == 'POST' else None,
                        klucz=None)[0] == 403
        assert _zapytaj(uslugi.port, metoda, sciezka, {} if metoda == 'POST' else None,
                        klucz='zly')[0] == 403
    kod, tresc = _zapytaj(uslugi.port, 'GET', '/stan')
    assert kod == 200
    assert json.loads(tresc)['sparowany'] is False


def test_tylko_127_0_0_1(uslugi):
    assert uslugi.serwer.server_address[0] == '127.0.0.1'


def test_klucz_lokalny_tworzony_raz(tmp_path):
    plik = tmp_path / 'dane' / 'klucz_lokalny'
    pierwszy = lokalne_api.zapewnij_klucz(plik)
    assert len(pierwszy) == 64 and int(pierwszy, 16) >= 0
    assert lokalne_api.zapewnij_klucz(plik) == pierwszy
    assert lokalne_api.wczytaj_klucz(plik) == pierwszy


def test_parowanie_zapisuje_token_i_wysyla_kontakt(uslugi):
    s = uslugi
    watek = threading.Thread(target=s.agent.petla, daemon=True)
    watek.start()

    kod, tresc = _zapytaj(s.port, 'POST', '/parowanie',
                          {'crm_url': 'https://crm.example.test/', 'token': TOKEN})
    assert kod == 200
    assert TOKEN not in tresc

    koniec = time.monotonic() + 5
    while 'kontakt' not in s.crm.nazwy() and time.monotonic() < koniec:
        time.sleep(0.02)
    assert 'kontakt' in s.crm.nazwy()   # natychmiastowy cykl, bez czekania na polling
    assert s.fabryki == [('https://crm.example.test', TOKEN)]

    zapisany = json.loads(s.sciezki.plik_konfiguracji().read_text(encoding='utf-8'))
    assert zapisany['token'] == TOKEN
    assert zapisany['crm_url'] == 'https://crm.example.test'

    kod, stan = _zapytaj(s.port, 'GET', '/stan')
    assert kod == 200 and TOKEN not in stan
    assert json.loads(stan)['crm_url'] == 'https://crm.example.test'


def test_parowanie_odrzuca_zle_dane(uslugi):
    for dane in ({'crm_url': 'crm.example.test', 'token': TOKEN},
                 {'crm_url': 'https://crm.example.test', 'token': ''},
                 {'crm_url': 'https://crm.example.test'}):
        kod, tresc = _zapytaj(uslugi.port, 'POST', '/parowanie', dane)
        assert kod == 400
        assert TOKEN not in tresc
    assert uslugi.agent.lokalna.token == ''
    assert uslugi.fabryki == []


def test_put_konfiguracji_ustawia_oczekujaca(uslugi):
    s = uslugi
    s.agent.lokalna.wersja = 3
    nowe = json.loads(json.dumps(KONFIGURACJA))
    nowe['przesuniecia']['wysylka'] = {'dx': 16, 'dy': -8}

    kod, tresc = _zapytaj(s.port, 'PUT', '/konfiguracja', {'dane': nowe})
    assert kod == 200, tresc

    assert s.agent.lokalna.dane == nowe
    assert s.agent.lokalna.oczekujaca == {'wersja_bazowa': 3, 'dane': nowe}
    zapisany = json.loads(s.sciezki.plik_konfiguracji().read_text(encoding='utf-8'))
    assert zapisany['oczekujaca'] == {'wersja_bazowa': 3, 'dane': nowe}

    kod, tresc = _zapytaj(s.port, 'GET', '/konfiguracja')
    odp = json.loads(tresc)
    assert kod == 200 and odp['dane'] == nowe and odp['oczekujaca'] is True and odp['wersja'] == 3


def test_put_konfiguracji_odrzuca_bledne_dane(uslugi):
    zle = json.loads(json.dumps(KONFIGURACJA))
    zle['drukarki'][0]['port'] = 70000
    zle['godziny']['pn_pt'] = ['15:30', '05:30']
    kod, tresc = _zapytaj(uslugi.port, 'PUT', '/konfiguracja', {'dane': zle})
    assert kod == 400
    odp = json.loads(tresc)
    assert odp['error'] == 'bledna_konfiguracja' and len(odp['bledy']) == 2
    assert uslugi.agent.lokalna.oczekujaca is None


def test_wydruk_probny_idzie_prosto_do_drukarki(uslugi):
    s = uslugi
    s.agent.lokalna.dane = KONFIGURACJA
    wyslane = []

    def wyslij_porcje(drukarka, zadania, przed_wyslaniem):
        wyslane.append((drukarka['nazwa'], zadania))
        return [{'id': z['id'], 'wynik': 'wydrukowane'} for z in zadania if przed_wyslaniem(z['id'])]

    s.druk.wyslij_porcje = wyslij_porcje
    s.druk.zpl_probny = lambda nazwa, przes: 'ZPL %s %r' % (nazwa, sorted(przes.items()))

    kod, tresc = _zapytaj(s.port, 'POST', '/wydruk-probny/wysylka', {})
    assert kod == 200, tresc
    assert json.loads(tresc)['ok'] is True
    assert wyslane == [('wysylka', [{'id': 0, 'zpl': "ZPL wysylka [('dx', 0), ('dy', 0)]"}])]
    assert s.crm.wywolania == []   # bez CRM

    s.druk.wyslij_porcje = lambda d, z, p: [{'id': 0, 'wynik': 'niewyslane'}]
    kod, tresc = _zapytaj(s.port, 'POST', '/wydruk-probny/etykiety', {})
    assert kod == 502 and json.loads(tresc)['ok'] is False

    assert _zapytaj(s.port, 'POST', '/wydruk-probny/nieznana', {})[0] == 404


def test_kalibruj_i_ponow_zalegle(uslugi):
    s = uslugi
    s.agent.lokalna.dane = KONFIGURACJA
    kod, _ = _zapytaj(s.port, 'POST', '/kalibruj/wysylka', {})
    assert kod == 200 and s.druk.kalibracje == ['wysylka']

    kod, _ = _zapytaj(s.port, 'POST', '/ponow-zalegle', {})
    assert kod == 202
    assert s.agent._obudz.is_set()


def test_log_ostatnie_500_linii(uslugi, tmp_path):
    (tmp_path / 'agent.log').write_text(''.join('linia %d\n' % i for i in range(700)),
                                        encoding='utf-8')
    kod, tresc = _zapytaj(uslugi.port, 'GET', '/log')
    linie = tresc.splitlines()
    assert kod == 200 and len(linie) == 500
    assert linie[0] == 'linia 200' and linie[-1] == 'linia 699'


def test_pusty_klucz_regenerowany_przy_starcie(sciezki, tmp_path):
    plik = tmp_path / 'klucz_lokalny'
    plik.write_text('  \n', encoding='ascii')
    klucz = lokalne_api.zapewnij_klucz(plik)
    assert len(klucz) == 64 and plik.read_text(encoding='ascii') == klucz
    plik.write_text('za-krotki', encoding='ascii')
    assert len(lokalne_api.zapewnij_klucz(plik)) == 64

    agent = petla.Agent(sciezki, None, drukarki=Drukarki())
    serwer = lokalne_api.uruchom(agent, port=0, klucz=lokalne_api.zapewnij_klucz(plik),
                                 plik_logu=tmp_path / 'agent.log')
    try:
        port = serwer.server_address[1]
        assert _zapytaj(port, 'GET', '/stan', klucz=None)[0] == 403
        assert _zapytaj(port, 'GET', '/stan', klucz='')[0] == 403
        assert _zapytaj(port, 'GET', '/stan', klucz=plik.read_text(encoding='ascii'))[0] == 200
    finally:
        serwer.shutdown()
        serwer.server_close()
        agent.dziennik.zamknij()


def test_uruchom_z_pustym_kluczem_nie_startuje(sciezki, tmp_path):
    agent = petla.Agent(sciezki, None, drukarki=Drukarki())
    try:
        for zly in ('', 'k' * 31):
            with pytest.raises(lokalne_api.BladKlucza):
                lokalne_api.uruchom(agent, port=0, klucz=zly, plik_logu=tmp_path / 'agent.log')
    finally:
        agent.dziennik.zamknij()


def test_drukarka_starego_agenta_409(uslugi):
    s = uslugi
    s.agent.lokalna.dane = KONFIGURACJA
    wyslane = []
    s.druk.zpl_probny = lambda nazwa, przes: 'ZPL'
    s.druk.wyslij_porcje = lambda d, z, p: wyslane.append(d['nazwa']) or [{'id': 0, 'wynik': 'wydrukowane'}]
    s.agent._ustaw_stan('wysylka', obsluga='stary')

    for sciezka in ('/wydruk-probny/wysylka', '/kalibruj/wysylka'):
        kod, tresc = _zapytaj(s.port, 'POST', sciezka, {})
        assert kod == 409 and json.loads(tresc)['error'] == 'drukarka_starego_agenta'
    assert wyslane == [] and s.druk.kalibracje == []

    assert _zapytaj(s.port, 'POST', '/wydruk-probny/etykiety', {})[0] == 200   # bez wpisu = nowy
    assert wyslane == ['etykiety']


def test_parowanie_samym_tokenem_do_przypietego_crm(uslugi):
    kod, tresc = _zapytaj(uslugi.port, 'POST', '/parowanie', {'token': TOKEN})
    assert kod == 200, tresc
    assert uslugi.fabryki == [(ADRES_CRM, TOKEN)]
    assert uslugi.agent.lokalna.crm_url == ADRES_CRM
    assert json.loads(_zapytaj(uslugi.port, 'GET', '/stan')[1])['crm_url'] == ADRES_CRM


@pytest.mark.parametrize('obcy', ['https://zly.example.test', 'https://crm.example.test:8443',
                                  'http://127.0.0.1:5000'])
def test_parowanie_z_innym_serwerem_crm_409(uslugi, obcy):
    kod, tresc = _zapytaj(uslugi.port, 'POST', '/parowanie', {'crm_url': obcy, 'token': TOKEN})
    assert kod == 409
    odp = json.loads(tresc)
    assert odp['error'] == 'inny_serwer_crm' and 'ponownej instalacji' in odp['opis']
    assert uslugi.agent.lokalna.token == '' and uslugi.fabryki == []


def test_parowanie_bez_przypietego_adresu_409(sciezki, tmp_path):
    agent = petla.Agent(sciezki, None, drukarki=Drukarki())
    serwer = lokalne_api.uruchom(agent, port=0, klucz=KLUCZ, fabryka_klienta=lambda u, t: Crm(),
                                 plik_logu=tmp_path / 'agent.log', adres_crm='')
    try:
        kod, tresc = _zapytaj(serwer.server_address[1], 'POST', '/parowanie',
                              {'crm_url': 'https://crm.example.test', 'token': TOKEN})
        assert kod == 409 and json.loads(tresc)['error'] == 'brak_adresu_crm'
        assert agent.lokalna.token == ''
    finally:
        serwer.shutdown()
        serwer.server_close()
        agent.dziennik.zamknij()


def test_nowy_klucz_dostaje_prawo_odczytu_dla_ikony(tmp_path, monkeypatch):
    wywolania = []

    def run(args, **kw):
        wywolania.append((args, kw))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(lokalne_api, 'NA_WINDOWS', True)
    monkeypatch.setattr(lokalne_api.subprocess, 'run', run)
    monkeypatch.setenv('SystemRoot', r'C:\Windows')
    plik = tmp_path / 'klucz_lokalny'

    klucz = lokalne_api.zapewnij_klucz(plik)
    assert len(wywolania) == 1
    args, kw = wywolania[0]
    assert args[0].endswith('icacls.exe') and args[1:] == [str(plik), '/grant', '*S-1-5-4:(R)']
    assert 'shell' not in kw

    # Istniejący klucz: prawo odczytu nadawane przy KAŻDYM starcie usługi (instalator robi /reset).
    assert lokalne_api.zapewnij_klucz(plik) == klucz
    assert len(wywolania) == 2 and wywolania[1][0] == wywolania[0][0]


def test_klucz_poza_windows_bez_icacls(tmp_path, monkeypatch):
    monkeypatch.setattr(lokalne_api, 'NA_WINDOWS', False)
    monkeypatch.setattr(lokalne_api.subprocess, 'run',
                        lambda *a, **k: pytest.fail('icacls poza Windows'))
    assert len(lokalne_api.zapewnij_klucz(tmp_path / 'k')) == 64


@pytest.mark.parametrize('zawartosc', [b'za-krotki', b'g' * 64, 'ż'.encode('utf-8') * 40, b'a' * 63,
                                       b'a' * 65])
def test_uszkodzony_klucz_odlozony_i_nowy(tmp_path, monkeypatch, caplog, zawartosc):
    """Klucz to 64 znaki hex. Cokolwiek innego (także nie-ASCII ≥ 32 znaki) idzie na bok, a usługa zakłada
    nowy klucz zamiast padać przy starcie."""
    monkeypatch.setattr(lokalne_api, 'NA_WINDOWS', False)
    plik = tmp_path / 'klucz_lokalny'
    plik.write_bytes(zawartosc)
    with caplog.at_level('CRITICAL', logger='agent_druku.lokalne_api'):
        klucz = lokalne_api.zapewnij_klucz(plik)
    assert lokalne_api._KLUCZ.match(klucz) and plik.read_text(encoding='ascii') == klucz
    odlozone = list(tmp_path.glob('klucz_lokalny.uszkodzony-*'))
    assert len(odlozone) == 1 and odlozone[0].read_bytes() == zawartosc
    assert any(r.levelname == 'CRITICAL' for r in caplog.records)


def test_brak_klucza_bez_odkladania(tmp_path, monkeypatch):
    monkeypatch.setattr(lokalne_api, 'NA_WINDOWS', False)
    klucz = lokalne_api.zapewnij_klucz(tmp_path / 'klucz_lokalny')
    assert lokalne_api.zapewnij_klucz(tmp_path / 'klucz_lokalny') == klucz
    assert list(tmp_path.glob('*.uszkodzony-*')) == []
