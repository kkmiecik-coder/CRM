import json

import pytest

from agent_druku import konfiguracja, sciezki
from agent_druku.crm import BladCrm


@pytest.fixture
def katalog(tmp_path, monkeypatch):
    monkeypatch.setattr(sciezki, 'katalog_danych', lambda: tmp_path)
    return tmp_path


class FalszywyCrm:
    def __init__(self, wersja=1, dane=None, awaria=False):
        self.wersja, self.dane, self.awaria = wersja, dane or {}, awaria
        self.put = []

    def zapisz_konfiguracje(self, wersja_bazowa, dane):
        if self.awaria:
            raise BladCrm(None, 'brak połączenia')
        self.put.append((wersja_bazowa, dane))
        self.wersja += 1
        self.dane = dane
        return {'wersja': self.wersja, 'dane': dane, 'nadpisano': None}

    def konfiguracja(self):
        if self.awaria:
            raise BladCrm(None, 'brak połączenia')
        return {'wersja': self.wersja, 'dane': self.dane}


def test_zmiana_lokalna_czeka_i_idzie_po_powrocie(katalog):
    lok = konfiguracja.Lokalna()
    lok.wersja = 3
    lok.zapisz_lokalnie({'drukarki': {'etykiety': {'ip': 'x'}}})
    crm = FalszywyCrm(wersja=3, awaria=True)
    with pytest.raises(BladCrm):
        lok.synchronizuj(crm)
    assert konfiguracja.Lokalna().oczekujaca == {
        'wersja_bazowa': 3, 'dane': {'drukarki': {'etykiety': {'ip': 'x'}}}}

    crm.awaria = False
    lok.synchronizuj(crm)
    assert crm.put == [(3, {'drukarki': {'etykiety': {'ip': 'x'}}})]
    ponownie = konfiguracja.Lokalna()
    assert ponownie.oczekujaca is None
    assert ponownie.wersja == 4


def test_synchronizacja_pobiera_nowsza_wersje_serwera(katalog):
    lok = konfiguracja.Lokalna()
    lok.wersja = 1
    lok.zapisz()
    lok.synchronizuj(FalszywyCrm(wersja=5, dane={'a': 1}))
    assert (lok.wersja, lok.dane) == (5, {'a': 1})


def test_kolejna_zmiana_zachowuje_wersje_bazowa(katalog):
    lok = konfiguracja.Lokalna()
    lok.wersja = 2
    lok.zapisz_lokalnie({'a': 1})
    lok.zapisz_lokalnie({'a': 2})
    assert lok.oczekujaca == {'wersja_bazowa': 2, 'dane': {'a': 2}}


def test_zapis_atomowy(katalog, monkeypatch):
    lok = konfiguracja.Lokalna()
    lok.crm_url, lok.token, lok.wersja = 'http://crm', 'sekret', 7
    lok.zapisz()
    plik = katalog / 'konfiguracja.json'
    przed = plik.read_text(encoding='utf-8')

    def awaria(*a, **k):
        raise OSError('pada przy podmianie')
    monkeypatch.setattr(konfiguracja.os, 'replace', awaria)
    lok.wersja = 8
    with pytest.raises(OSError):
        lok.zapisz()
    assert plik.read_text(encoding='utf-8') == przed  # stary plik nietknięty
    assert json.loads(przed)['wersja'] == 7
    assert [p.name for p in katalog.iterdir()] == ['konfiguracja.json']  # brak śmieci


def test_token_nie_trafia_do_repr(katalog):
    lok = konfiguracja.Lokalna()
    lok.token = 'tajny-token'
    assert 'tajny-token' not in repr(lok)


def test_zmiana_w_trakcie_synchronizacji_nie_ginie(katalog):
    lok = konfiguracja.Lokalna()
    lok.wersja = 3
    lok.zapisz_lokalnie({'a': 1})

    class Crm(FalszywyCrm):
        def zapisz_konfiguracje(self, wersja_bazowa, dane):
            lok.zapisz_lokalnie({'a': 2})  # użytkownik zmienia w trakcie żądania
            return super().zapisz_konfiguracje(wersja_bazowa, dane)

    crm = Crm(wersja=3)
    lok.synchronizuj(crm)
    assert lok.dane == {'a': 2}
    assert lok.oczekujaca == {'wersja_bazowa': 4, 'dane': {'a': 2}}
    lok.synchronizuj(crm)  # druga runda wysyła nowszą zmianę
    assert crm.put[-1] == (4, {'a': 2})
    assert lok.oczekujaca is None and lok.dane == {'a': 2}


def test_odrzucona_zmiana_porzucona_wraca_wersja_serwera(katalog):
    lok = konfiguracja.Lokalna()
    lok.wersja = 2
    lok.zapisz_lokalnie({'zle': True})

    class Odrzuca(FalszywyCrm):
        def zapisz_konfiguracje(self, wersja_bazowa, dane):
            raise BladCrm(400, 'bledna_konfiguracja', {'error': 'bledna_konfiguracja', 'bledy': ['x']})

    crm = Odrzuca(wersja=2, dane={'dobre': True})
    with pytest.raises(BladCrm) as e:
        lok.synchronizuj(crm)
    assert e.value.odrzucona == {'wersja_bazowa': 2, 'dane': {'zle': True}}

    lok.porzuc_oczekujaca(crm, e.value.odrzucona)
    ponownie = konfiguracja.Lokalna()
    assert (ponownie.oczekujaca, ponownie.wersja, ponownie.dane) == (None, 2, {'dobre': True})


def test_porzucenie_nie_kasuje_nowszej_zmiany(katalog):
    lok = konfiguracja.Lokalna()
    lok.zapisz_lokalnie({'zle': True})
    odrzucona = dict(lok.oczekujaca)
    lok.zapisz_lokalnie({'nowsze': True})
    lok.porzuc_oczekujaca(FalszywyCrm(wersja=1, dane={'dobre': True}), odrzucona)
    assert lok.oczekujaca['dane'] == {'nowsze': True}
    assert lok.dane == {'nowsze': True}


@pytest.mark.parametrize('adres,oczekiwany', [
    ('https://crm.example.test/', 'https://crm.example.test'),
    ('  https://crm.example.test:8443 ', 'https://crm.example.test:8443'),
    ('http://127.0.0.1:5002', 'http://127.0.0.1:5002'),
    ('http://localhost:5002/', 'http://localhost:5002'),
])
def test_adres_crm_https_albo_lokalny(adres, oczekiwany):
    assert konfiguracja.normalizuj_adres_crm(adres) == oczekiwany


@pytest.mark.parametrize('adres', ['http://crm.example.test', 'crm.example.test', '',
                                   'ftp://crm.example.test', 'https://u:p@crm.example.test',
                                   'https://crm.example.test/?x=1', 'https://crm.example.test:99999'])
def test_adres_crm_odrzucony(adres):
    with pytest.raises(ValueError):
        konfiguracja.normalizuj_adres_crm(adres)


def test_przypiety_adres_z_pliku(tmp_path):
    plik = tmp_path / 'crm_url.txt'
    assert konfiguracja.wczytaj_przypiety_adres(plik) == ''          # brak pliku
    plik.write_bytes(b'\xef\xbb\xbfhttps://crm.example.test/\r\n')   # BOM i CRLF z Inno Setup
    assert konfiguracja.wczytaj_przypiety_adres(plik) == 'https://crm.example.test'
    plik.write_text('http://crm.example.test', encoding='utf-8')
    assert konfiguracja.wczytaj_przypiety_adres(plik) == ''          # http poza localhost


@pytest.mark.parametrize('tresc', [b'{zly json', b'[1, 2]', b'{"wersja": "abc"}', b'{"dane": [1]}',
                                   b'\xff\xfe\x00zly'])
def test_uszkodzona_konfiguracja_odlozona_start_pusty(katalog, caplog, tresc):
    plik = katalog / 'konfiguracja.json'
    plik.write_bytes(tresc)
    with caplog.at_level('CRITICAL', logger='agent_druku.konfiguracja'):
        lok = konfiguracja.Lokalna()
    assert (lok.token, lok.wersja, lok.dane, lok.oczekujaca) == ('', 0, {}, None)
    assert not plik.exists() and len(list(katalog.glob('konfiguracja.json.uszkodzony-*'))) == 1
    assert any(r.levelname == 'CRITICAL' for r in caplog.records)
    lok.ustaw_polaczenie('https://crm.example.test', 'tok')   # i da się zapisać od nowa
    assert konfiguracja.Lokalna().token == 'tok'


DRUKARKI_HUBA = [{'nazwa': 'etykiety', 'ip': '192.0.2.10', 'port': 9100, 'odczyt_stanu': 'snmp'}]
GODZINY_HUBA = {'pn_pt': ['06:00', '22:00'], 'sobota': ['06:00', '14:00']}


def _sparowany(wersja=1):
    lok = konfiguracja.Lokalna()
    lok.ustaw_polaczenie('https://crm.example.test', 'stary-token')
    lok.wersja = wersja
    lok.dane = {'drukarki': DRUKARKI_HUBA, 'godziny': GODZINY_HUBA,
                'przesuniecia': {'etykiety': {'lt': 1, 'ls': 1}}}
    lok.zapisz()
    return lok


def test_ten_sam_token_nie_zmienia_wersji(katalog):
    lok = _sparowany(wersja=4)
    lok.zapisz_lokalnie(dict(lok.dane))
    lok.ustaw_polaczenie('https://crm.example.test', 'stary-token')
    assert lok.wersja == 4 and lok.oczekujaca is not None


def test_nowy_token_wersja_od_zera_i_dokument_serwera_wygrywa(katalog):
    """Nowy agent w CRM ma wersję 1, tak jak lokalny dokument starego agenta: bez zerowania wersji agent
    zostałby przy starej konfiguracji. Serwer ma już drukarki — wygrywa jego dokument."""
    lok = _sparowany(wersja=1)
    lok.zapisz_lokalnie(dict(lok.dane))           # oczekująca z bazą starego dokumentu znika
    lok.ustaw_polaczenie('https://crm.example.test', 'nowy-token')
    assert (lok.wersja, lok.oczekujaca) == (0, None)
    assert konfiguracja.Lokalna().wersja == 0
    serwerowe = {'drukarki': [{'nazwa': 'wysylka', 'ip': '192.0.2.20', 'port': 9100}], 'godziny': {}}
    crm = FalszywyCrm(wersja=1, dane=serwerowe)
    lok.synchronizuj(crm)
    assert (lok.wersja, lok.dane, crm.put) == (1, serwerowe, [])


def test_nowy_token_swiezy_dokument_przejmuje_drukarki_huba(katalog):
    """Świeży agent w CRM (wersja 1, bez drukarek): hub wysyła swoje drukarki i godziny na bazie wersji
    serwera; przesunięcia zostają z serwera."""
    lok = _sparowany(wersja=7)
    lok.ustaw_polaczenie('https://crm.example.test', 'nowy-token')
    swiezy = {'drukarki': [], 'godziny': {'pn_pt': ['05:30', '15:30'], 'sobota': ['05:30', '15:30']},
              'przesuniecia': {'etykiety': {'lt': 9, 'ls': 9}}}
    crm = FalszywyCrm(wersja=1, dane=swiezy)
    lok.synchronizuj(crm)
    oczekiwane = {'drukarki': DRUKARKI_HUBA, 'godziny': GODZINY_HUBA,
                  'przesuniecia': {'etykiety': {'lt': 9, 'ls': 9}}}
    assert crm.put == [(1, oczekiwane)]
    assert (lok.wersja, lok.dane, lok.oczekujaca) == (2, oczekiwane, None)
    ponownie = konfiguracja.Lokalna()
    assert (ponownie.wersja, ponownie.dane) == (2, oczekiwane)


def test_przejecie_czeka_przy_awarii_crm(katalog):
    lok = _sparowany()
    lok.ustaw_polaczenie('https://crm.example.test', 'nowy-token')
    crm = FalszywyCrm(wersja=1, dane={'drukarki': []})

    def awaria(wersja_bazowa, dane):
        raise BladCrm(None, 'brak połączenia')
    crm.zapisz_konfiguracje = awaria
    with pytest.raises(BladCrm):
        lok.synchronizuj(crm)
    # drukarki huba dalej działają lokalnie, zmiana czeka na wysłanie
    assert lok.dane['drukarki'] == DRUKARKI_HUBA
    assert lok.oczekujaca['wersja_bazowa'] == 1 and lok.oczekujaca['dane']['drukarki'] == DRUKARKI_HUBA
