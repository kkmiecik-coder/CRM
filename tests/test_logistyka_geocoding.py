# -*- coding: utf-8 -*-
"""Odpowiedzi usług to kopie zapytań wykonanych 24.09.2026 (patrz „Zmierzone” w planie)."""
import pytest
import requests

from modules.production.logistics.services import geocoding as g

FLORIANSKA = {'type': 'address', 'returned objects': 2, 'results': {
    '1': {'city': 'Kraków', 'street': 'Floriańska', 'number': '10', 'code': '31-021',
          'accuracy': '1', 'x': '19.9396202491515', 'y': '50.0627258466159'},
    '2': {'city': 'Kraków', 'street': 'Ariańska', 'number': '10', 'code': '31-505',
          'accuracy': '0.666667', 'x': '19.9542258649548', 'y': '50.0665202'}}}
BACHORZ = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Bachórz', 'street': None, 'number': '14N', 'code': '36-065',
          'accuracy': '1', 'x': '22.2540527461363', 'y': '49.8404376841563'}}}
REJTANA = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Rzeszów', 'street': 'Tadeusza Rejtana', 'number': '16c', 'code': '35-310',
          'accuracy': '0.678571', 'x': '22.01588', 'y': '50.03016'}}}
PUSTO = {'type': 'address', 'returned objects': 0, 'results': None}
MIASTO = {'type': 'city', 'returned objects': 1, 'results': {
    '1': {'city': 'Dynów', 'accuracy': '1', 'x': '22.23386', 'y': '49.81479'}}}


class Odp(object):
    def __init__(self, dane, status=200):
        self.dane, self.status_code = dane, status

    def json(self):
        return self.dane

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeHttp(object):
    """Odpowiada według (usługa, klucz) — klucz: adres dla GUGiK, krotka parametrów dla Nominatim.

    `awaria_gugik_zapytania` (rozszerzenie do R3, runda 1 poprawek): zbiór
    dokładnych treści zapytań GUGiK, które mają zawieść — pozwala wysadzić
    JEDNO konkretne zapytanie (np. tylko krok 3 „miejscowość”), zostawiając
    inne zapytania GUGiK (np. krok 1 „adres”) działające normalnie. Domyślnie
    pusty zbiór — nie zmienia zachowania testów z briefu.
    """

    def __init__(self, gugik=None, nominatim=None, awaria=(), awaria_gugik_zapytania=()):
        self.gugik, self.nominatim, self.awaria = gugik or {}, nominatim or [], set(awaria)
        self.awaria_gugik_zapytania = set(awaria_gugik_zapytania)
        self.wywolania = []

    def __call__(self, url, params=None, timeout=None, headers=None):
        self.wywolania.append((url, dict(params or {}), dict(headers or {})))
        usluga = 'gugik' if url == g.GUGIK_URL else 'nominatim'
        if usluga in self.awaria:
            raise requests.ConnectionError('awaria testowa')
        if usluga == 'gugik':
            if params['address'] in self.awaria_gugik_zapytania:
                raise requests.ConnectionError('awaria testowa (GUGiK, zapytanie)')
            return Odp(self.gugik.get(params['address'], PUSTO))
        return Odp(self.nominatim.pop(0) if self.nominatim else [])


def _bez_spania(_):
    pass


def test_zapytanie_bez_mieszkania_i_kodu():
    assert g.zapytania_gugik('ul. Floriańska 10/5', 'Kraków') == (['Kraków, Floriańska 10'], '10')
    assert g.zapytania_gugik('36-068 Bachórz 14N', 'Bachórz') == (['Bachórz 14N'], '14N')
    assert g.zapytania_gugik('Rynek', 'Kraków') == ([], '')


def test_wybor_trafienia_po_kodzie_i_numerze():
    assert g.wybierz_trafienie(FLORIANSKA, '10', '31-021')['street'] == 'Floriańska'
    assert g.wybierz_trafienie(FLORIANSKA, '10', None)['street'] == 'Floriańska'  # max accuracy
    assert g.wybierz_trafienie(BACHORZ, '14N', '36-068')['number'] == '14N'  # kod inny, numer pewny
    assert g.wybierz_trafienie(REJTANA, '16C', '35-310')['number'] == '16c'  # wielkość liter
    assert g.wybierz_trafienie(FLORIANSKA, '12', None) is None  # zły numer
    assert g.wybierz_trafienie(MIASTO, '10', None) is None  # nie adres


def test_mieszkanie_m_nie_trafia_w_zly_numer():
    http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
    wynik = g.geokoduj_adres('Floriańska 10 m. 5', 'Kraków', '31-021', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.0627258466159, 19.9396202491515, 'gugik', 'dokladna')


def test_wies_bez_ulic():
    http = FakeHttp(gugik={'Bachórz 14N': BACHORZ})
    wynik = g.geokoduj_adres('Bachórz 14N', 'Bachórz', '36-068', 'PL', http, _bez_spania)
    assert (wynik.source, wynik.quality) == ('gugik', 'dokladna')


def test_nominatim_gdy_gugik_nic_nie_zna_i_tylko_adres_do_uslug():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Nowa 5', 'Kraków', '30-001', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.1, 19.9, 'nominatim', 'dokladna')
    url, params, naglowki = http.wywolania[-1]
    assert url == g.NOMINATIM_URL
    assert params['street'] == 'Nowa 5' and params['city'] == 'Kraków'
    assert naglowki['User-Agent'] == g.USER_AGENT


def test_nominatim_na_poziomie_ulicy_to_przyblizenie():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 26}]])
    assert g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, _bez_spania).quality == 'przyblizona'


def test_przyblizenie_do_miejscowosci():
    http = FakeHttp(gugik={'Dynów': MIASTO}, nominatim=[[]])
    wynik = g.geokoduj_adres('Nieistniejąca 1', 'Dynów', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(49.81479, 22.23386, 'gugik', 'przyblizona')


def test_zagranica_bez_gugik():
    http = FakeHttp(nominatim=[[{'lat': '52.5', 'lon': '13.4', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Unter den Linden 1', 'Berlin', '10117', 'DE', http, _bez_spania)
    assert wynik.source == 'nominatim'
    assert all(u == g.NOMINATIM_URL for u, _, _ in http.wywolania)
    assert http.wywolania[0][1]['countrycodes'] == 'de'


def test_nic_nie_znaleziono():
    http = FakeHttp(nominatim=[[], []])
    assert g.geokoduj_adres('Nowa 5', 'Xyz', None, 'PL', http, _bez_spania).quality == 'nie_znaleziono'


def test_awaria_uslug_to_blad_a_nie_nie_znaleziono():
    http = FakeHttp(awaria={'gugik', 'nominatim'})
    with pytest.raises(g.BladUslugi):
        g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)


def test_odstep_przed_nominatim():
    przerwy = []
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, przerwy.append)
    assert g.ODSTEP_NOMINATIM_S in przerwy


# --- R3: po awarii którejkolwiek usługi w tym wywołaniu wolno zwrócić TYLKO wynik dokładny ---
# (przybliżenie po awarii nie jest zapisywane — automat nie ponawia samych przybliżeń,
# więc chwilowa awaria GUGiK-a na trwałe degradowałaby adres, który dałoby się przypiąć
# dokładnie; zamiast tego próba wraca w kolejnym przebiegu).

def test_awaria_gugik_nie_zapisuje_przyblizenia():
    http = FakeHttp(awaria={'gugik'}, nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 26}]])
    with pytest.raises(g.BladUslugi):
        g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)


def test_awaria_gugik_ale_nominatim_dokladny():
    http = FakeHttp(awaria={'gugik'}, nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.1, 19.9, 'nominatim', 'dokladna')


def test_awaria_nominatim_nie_daje_przyblizenia_miejscowosci():
    http = FakeHttp(gugik={'Dynów': MIASTO}, awaria={'nominatim'})
    with pytest.raises(g.BladUslugi):
        g.geokoduj_adres('Nieistniejąca 1', 'Dynów', None, 'PL', http, _bez_spania)


def test_awaria_gugik_miejscowosci_nie_maskuje_sukcesu_nominatim():
    """R3 (poprawka rundy 1): krok 3 ma dwie usługi z rzędu (GUGiK, potem Nominatim
    dla miejscowości). Awaria pierwszej nie może zostać zamaskowana sukcesem drugiej —
    GUGiK dla adresu PUSTO, Nominatim dla adresu [], GUGiK dla miejscowości pada,
    Nominatim dla miejscowości i tak zwróciłby punkt, gdybyśmy go zapytali."""
    http = FakeHttp(nominatim=[[], [{'lat': '49.8', 'lon': '22.2', 'place_rank': 16}]],
                     awaria_gugik_zapytania={'Dynów'})
    with pytest.raises(g.BladUslugi):
        g.geokoduj_adres('Nieistniejąca 1', 'Dynów', None, 'PL', http, _bez_spania)
