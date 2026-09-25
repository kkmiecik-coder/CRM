# -*- coding: utf-8 -*-
"""Odpowiedzi usług to kopie zapytań wykonanych 24.09.2026 (patrz „Zmierzone” w planie)."""
import logging

import pytest
import requests

from modules.production.logistics.services import geocoding as g

FLORIANSKA = {'type': 'address', 'returned objects': 2, 'results': {
    '1': {'city': 'Kraków', 'street': 'Floriańska', 'number': '10', 'code': '31-021',
          'teryt': '126101', 'accuracy': '1', 'x': '19.9396202491515', 'y': '50.0627258466159'},
    '2': {'city': 'Kraków', 'street': 'Ariańska', 'number': '10', 'code': '31-505',
          'teryt': '126101', 'accuracy': '0.666667', 'x': '19.9542258649548', 'y': '50.0665202'}}}
BACHORZ = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Bachórz', 'street': None, 'number': '14N', 'code': '36-065',
          'accuracy': '1', 'x': '22.2540527461363', 'y': '49.8404376841563'}}}
REJTANA = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Rzeszów', 'street': 'Tadeusza Rejtana', 'number': '16c', 'code': '35-310',
          'accuracy': '0.678571', 'x': '22.01588', 'y': '50.03016'}}}
PUSTO = {'type': 'address', 'returned objects': 0, 'results': None}
MIASTO = {'type': 'city', 'returned objects': 1, 'results': {
    '1': {'city': 'Dynów', 'accuracy': '1', 'x': '22.23386', 'y': '49.81479'}}}
# Zmierzone 25.09.2026 (przegląd końcowy): „Wola 12” → 5 trafień w różnych województwach,
# każde accuracy 1, różne teryt. Współrzędne zaokrąglone (w teście liczy się wybór).
WOLA_12 = {'type': 'address', 'returned objects': 5, 'results': {
    '1': {'city': 'Wola', 'street': None, 'number': '12', 'code': '83-130', 'teryt': '220405',
          'accuracy': '1', 'x': '18.61', 'y': '53.93'},
    '2': {'city': 'Wola', 'street': None, 'number': '12', 'code': '87-620', 'teryt': '040611',
          'accuracy': '1', 'x': '18.92', 'y': '52.91'},
    '3': {'city': 'Wola', 'street': None, 'number': '12', 'code': '11-606', 'teryt': '280701',
          'accuracy': '1', 'x': '22.01', 'y': '54.12'},
    '4': {'city': 'Wola', 'street': None, 'number': '12', 'code': '09-150', 'teryt': '142008',
          'accuracy': '1', 'x': '20.44', 'y': '52.63'},
    '5': {'city': 'Wola', 'street': None, 'number': '12', 'code': '13-124', 'teryt': '281503',
          'accuracy': '1', 'x': '20.31', 'y': '53.22'}}}
# Zmierzone 25.09.2026: „Józefów, Jana Onufrego Zagłoby 10” (zamówienie bez kodu) → jedno
# trafienie, właściwy punkt, ale accuracy 0.59 — PRG zna ulicę jako „Zagłoby”.
# Współrzędne zaokrąglone (w teście liczy się wybór).
JOZEFOW_ZAGLOBY = {'type': 'address', 'returned objects': 1, 'results': {
    '1': {'city': 'Józefów', 'teryt': '141701', 'street': 'Zagłoby', 'number': '10',
          'code': '05-410', 'accuracy': '0.59375', 'x': '21.23', 'y': '52.13'}}}
JOZEFOWY = {'type': 'city', 'returned objects': 2, 'results': {
    '1': {'city': 'Józefów', 'teryt': '1417011', 'accuracy': '1', 'x': '21.23', 'y': '52.13'},
    '2': {'city': 'Józefów', 'teryt': '0601034', 'accuracy': '1', 'x': '23.05', 'y': '50.48'}}}
# „Nowa Wieś” (type city) → wiele miejscowości o tej samej nazwie.
NOWA_WIES = {'type': 'city', 'returned objects': 3, 'results': {
    '1': {'city': 'Nowa Wieś', 'teryt': '0201011', 'accuracy': '1', 'x': '16.11', 'y': '51.21'},
    '2': {'city': 'Nowa Wieś', 'teryt': '1206052', 'accuracy': '1', 'x': '20.21', 'y': '50.12'},
    '3': {'city': 'Nowa Wieś', 'teryt': '1816042', 'accuracy': '1', 'x': '22.41', 'y': '50.02'}}}


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


# --- R7 (kontroler): BladUslugi.pelna_awaria - tylko PEŁNA awaria (żadna usługa w tym
# wywołaniu nie odpowiedziała) ma się liczyć do serii przerywającej przebieg `lokalizuj`
# (patrz tests/test_logistyka_geo_runner.py) ---

def test_blad_uslugi_pelna_awaria_gdy_wszystko_pada():
    http = FakeHttp(awaria={'gugik', 'nominatim'})
    with pytest.raises(g.BladUslugi) as wyjatek:
        g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)
    assert wyjatek.value.pelna_awaria is True


def test_blad_uslugi_nie_pelna_gdy_gugik_pada_a_nominatim_odpowiada():
    http = FakeHttp(awaria={'gugik'}, nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 26}]])
    with pytest.raises(g.BladUslugi) as wyjatek:
        g.geokoduj_adres('Floriańska 10', 'Kraków', None, 'PL', http, _bez_spania)
    assert wyjatek.value.pelna_awaria is False


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


# ── R9 (kontroler): wybór trafienia GUGiK przy niezgodnym albo brakującym kodzie ──

def test_wola_12_z_obcym_kodem_to_brak_trafienia():
    assert g.wybierz_trafienie(WOLA_12, '12', '36-100') is None


def test_wola_12_bez_kodu_wiele_miejscowosci_to_brak_trafienia():
    assert g.wybierz_trafienie(WOLA_12, '12', None) is None


def test_wola_12_ze_zgodnym_kodem_to_ta_jedna():
    assert g.wybierz_trafienie(WOLA_12, '12', '83-130')['code'] == '83-130'


def test_niezgodny_kod_i_niska_dokladnosc_to_brak_trafienia():
    """Samo „Ariańska 10” (31-505, accuracy 0.667) dla kodu klienta 31-021 — inna ulica."""
    tylko_arianska = {'type': 'address', 'results': {'2': FLORIANSKA['results']['2']}}
    assert g.wybierz_trafienie(tylko_arianska, '10', '31-021') is None


def test_niezgodny_kod_ten_sam_prefiks_wymaga_wysokiej_dokladnosci():
    assert g.wybierz_trafienie(REJTANA, '16c', '35-001') is None  # prefiks 35, accuracy 0.68
    assert g.wybierz_trafienie(BACHORZ, '14N', '36-068')['number'] == '14N'  # prefiks 36, acc 1


def test_niezgodny_prefiks_kodu_to_brak_trafienia():
    assert g.wybierz_trafienie(BACHORZ, '14N', '30-001') is None


def test_zgodny_kod_wybiera_najlepsza_dokladnosc():
    dwa = {'type': 'address', 'results': {
        '1': dict(FLORIANSKA['results']['1'], street='Florianska', accuracy='0.7'),
        '2': FLORIANSKA['results']['1']}}
    assert g.wybierz_trafienie(dwa, '10', '31-021')['street'] == 'Floriańska'


def test_wieloznaczny_adres_idzie_do_nominatim_z_kodem():
    http = FakeHttp(gugik={'Wola 12': WOLA_12},
                    nominatim=[[{'lat': '49.9', 'lon': '21.9', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Wola 12', 'Wola', '36-100', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(49.9, 21.9, 'nominatim', 'dokladna')
    url, params, _ = http.wywolania[-1]
    assert url == g.NOMINATIM_URL
    assert (params['city'], params['postalcode']) == ('Wola', '36-100')


def test_bez_miasta_i_bez_kodu_gugik_pominiety():
    """R9(d): zapytanie ogólnopolskie „Floriańska 10” jest niejednoznaczne."""
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    g.geokoduj_adres('Floriańska 10', '', None, 'PL', http, _bez_spania)
    assert http.wywolania and all(u == g.NOMINATIM_URL for u, _, _ in http.wywolania)


def test_bez_miasta_z_kodem_gugik_wybiera_po_kodzie():
    http = FakeHttp(gugik={'Floriańska 10': FLORIANSKA})
    wynik = g.geokoduj_adres('Floriańska 10', '', '31-021', 'PL', http, _bez_spania)
    assert (wynik.source, wynik.quality, wynik.lat) == ('gugik', 'dokladna', 50.0627258466159)


def test_miasto_wieloznaczne_przyblizenie_z_nominatim():
    """R9(e): „Nowa Wieś” w GUGiK to wiele miejscowości → przybliżenie z Nominatim (miasto + kod)."""
    http = FakeHttp(gugik={'Nowa Wieś': NOWA_WIES},
                    nominatim=[[], [{'lat': '50.1', 'lon': '20.2', 'place_rank': 16}]])
    wynik = g.geokoduj_adres('Nieistniejąca 1', 'Nowa Wieś', '32-100', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.1, 20.2, 'nominatim', 'przyblizona')
    url, params, _ = http.wywolania[-1]
    assert url == g.NOMINATIM_URL
    assert (params['city'], params['postalcode']) == ('Nowa Wieś', '32-100')


# ── I1: nieparsowalne współrzędne to brak wyniku, nie wyjątek ──

@pytest.mark.parametrize('zmiana', [{'y': ''}, {'y': None}, {'x': 'abc'}, {'y': '500'},
                                    {'x': 'nan'}])
def test_trafienie_bez_poprawnych_wspolrzednych_jest_pomijane(zmiana):
    odp = {'type': 'address', 'results': {'1': dict(FLORIANSKA['results']['1'], **zmiana)}}
    assert g.wybierz_trafienie(odp, '10', '31-021') is None


def test_trafienie_bez_x_jest_pomijane():
    bez_x = {k: v for k, v in FLORIANSKA['results']['1'].items() if k != 'x'}
    assert g.wybierz_trafienie({'type': 'address', 'results': {'1': bez_x}}, '10', '31-021') is None


def test_zle_trafienie_obok_dobrego():
    odp = {'type': 'address', 'results': {
        '1': dict(FLORIANSKA['results']['1'], y=''),
        '2': dict(FLORIANSKA['results']['1'], accuracy='0.95')}}
    assert g.wybierz_trafienie(odp, '10', '31-021')['accuracy'] == '0.95'


@pytest.mark.parametrize('odpowiedz', [None, [], 'x', {'type': 'address', 'results': ['x', 5]},
                                       {'type': 'address', 'results': 'x'}])
def test_dziwna_odpowiedz_gugik_to_brak_trafienia(odpowiedz):
    assert g.wybierz_trafienie(odpowiedz, '10', '31-021') is None


def test_zle_trafienie_nie_przerywa_geokodowania():
    zle = {'type': 'address', 'results': {'1': dict(FLORIANSKA['results']['1'], y='')}}
    http = FakeHttp(gugik={'Kraków, Floriańska 10': zle},
                    nominatim=[[{'lat': '50.06', 'lon': '19.94', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Floriańska 10', 'Kraków', '31-021', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.06, 19.94, 'nominatim', 'dokladna')


@pytest.mark.parametrize('odpowiedz', [
    [{'lat': 'abc', 'lon': '19.9', 'place_rank': 30}],
    [{'place_rank': 30}],
    [{'lat': None, 'lon': None}],
    [{'lat': '95', 'lon': '19.9', 'place_rank': 30}],
    {'error': 'Bad request'},
    ['x'],
])
def test_nieparsowalna_odpowiedz_nominatim_to_brak_wyniku(odpowiedz):
    """To ODPOWIEDŹ usługi (nie awaria): nie ma BladUslugi, próba się zużywa."""
    http = FakeHttp(nominatim=[odpowiedz, []])
    assert g.geokoduj_adres('Nowa 5', 'Xyz', None, 'PL', http, _bez_spania).quality == 'nie_znaleziono'


def test_nieczytelna_ranga_nominatim_to_przyblizenie():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 'abc'}]])
    wynik = g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.1, 19.9, 'nominatim', 'przyblizona')


def test_miejscowosc_gugik_ze_zlymi_wspolrzednymi_to_brak_wyniku():
    zle = {'type': 'city', 'results': {'1': dict(MIASTO['results']['1'], x='')}}
    http = FakeHttp(gugik={'Dynów': zle},
                    nominatim=[[], [{'lat': '49.8', 'lon': '22.2', 'place_rank': 16}]])
    wynik = g.geokoduj_adres('Nieistniejąca 1', 'Dynów', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(49.8, 22.2, 'nominatim', 'przyblizona')


# ── R10: oznaczenie lokalu nie trafia do usług jako numer domu ──

def test_oznaczenie_lokalu_nie_jest_numerem_domu():
    assert g.zapytania_gugik('Floriańska 10 lok. 5', 'Kraków') == (['Kraków, Floriańska 10'], '10')
    assert g.zapytania_gugik('Floriańska 10/5, 31-021 Kraków', 'Kraków') == (
        ['Kraków, Floriańska 10'], '10')
    http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
    wynik = g.geokoduj_adres('Floriańska 10 lok 5', 'Kraków', '31-021', 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.0627258466159, 19.9396202491515, 'gugik', 'dokladna')


def test_nominatim_dostaje_adres_bez_oznaczenia_lokalu():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    g.geokoduj_adres('Nowa 5, lokal 3', 'Kraków', '30-001', 'PL', http, _bez_spania)
    assert http.wywolania[-1][1]['street'] == 'Nowa 5'


# ── M2: kraj ze spacjami ──

@pytest.mark.parametrize('kraj', [' pl', 'PL ', 'pl', '', None, '  '])
def test_kraj_ze_spacjami_to_polska(kraj):
    http = FakeHttp(gugik={'Kraków, Floriańska 10': FLORIANSKA})
    wynik = g.geokoduj_adres('Floriańska 10', 'Kraków', '31-021', kraj, http, _bez_spania)
    assert (wynik.source, wynik.quality) == ('gugik', 'dokladna')


def test_countrycodes_bez_spacji():
    http = FakeHttp(nominatim=[[{'lat': '52.5', 'lon': '13.4', 'place_rank': 30}]])
    g.geokoduj_adres('Unter den Linden 1', 'Berlin', '10117', ' de ', http, _bez_spania)
    assert all(u == g.NOMINATIM_URL for u, _, _ in http.wywolania)
    assert http.wywolania[0][1]['countrycodes'] == 'de'


# ── M3: prywatność logów — tekst wyjątku requests niesie URL z adresem klienta ──

NAZWA_LOGGERA = 'app.production.logistics.geocoding'


class FakeHttpAwariaZUrl(object):
    """Awaria jak w prawdziwym requests: komunikat wyjątku zawiera pełny URL z adresem."""

    def __call__(self, url, params=None, timeout=None, headers=None):
        pelny = requests.Request('GET', url, params=params).prepare().url
        if url == g.GUGIK_URL:
            raise requests.ConnectionError('Max retries exceeded with url: %s' % pelny)
        odp = requests.Response()
        odp.status_code, odp.url = 503, pelny
        raise requests.HTTPError('503 Server Error: Service Unavailable for url: %s' % pelny,
                                 response=odp)


def test_log_awarii_bez_adresu_klienta(caplog):
    with caplog.at_level(logging.DEBUG, logger=NAZWA_LOGGERA):
        with pytest.raises(g.BladUslugi):
            g.geokoduj_adres('Floriańska 10', 'Kraków', '31-021', 'PL', FakeHttpAwariaZUrl(),
                             _bez_spania)
    tekst = '\n'.join(r.getMessage() for r in caplog.records if r.name == NAZWA_LOGGERA)
    assert tekst
    assert 'Floria' not in tekst and 'Krak' not in tekst and '31-021' not in tekst
    assert 'ConnectionError' in tekst and 'HTTPError' in tekst and '503' in tekst


# ── Adres bez kodu pocztowego (uwaga właściciela 25.09.2026) ──

def test_bez_kodu_pelna_nazwa_ulicy_trafia_w_punkt_prg():
    http = FakeHttp(gugik={'Józefów, Jana Onufrego Zagłoby 10': JOZEFOW_ZAGLOBY})
    wynik = g.geokoduj_adres('Jana Onufrego Zagłoby 10', 'Józefów', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(52.13, 21.23, 'gugik', 'dokladna')
    assert all(u == g.GUGIK_URL for u, _, _ in http.wywolania)


def test_ta_sama_ulica_wymaga_tej_samej_miejscowosci_i_nazwy():
    trafienie = JOZEFOW_ZAGLOBY['results']['1']
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', None) is None  # bez ulicy: sam próg 0.6
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', None,
                               ulica='Jana Onufrego Zagłoby', miasto='Józefów') is trafienie
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', None,
                               ulica='ul. Zagłoby', miasto='józefów') is trafienie
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', None,
                               ulica='Jana Onufrego Zagłoby', miasto='Otwock') is None
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', None,
                               ulica='Zagłoby Jana', miasto='Józefów') is None
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '12', None,
                               ulica='Zagłoby', miasto='Józefów') is None  # inny numer


def test_ta_sama_ulica_nie_luzuje_kodu_niezgodnego():
    """Kod podany i inny niż w PRG: dalej R9(b) (prefiks + accuracy 0.9), nazwa ulicy nie pomaga."""
    assert g.wybierz_trafienie(JOZEFOW_ZAGLOBY, '10', '05-420',
                               ulica='Zagłoby', miasto='Józefów') is None


def test_bez_kodu_rozrzucone_wyniki_nominatim_to_brak_punktu():
    """Dwa Józefowy 300 km od siebie — żaden punkt nie jest „dokładny”, a przybliżenia
    do miejscowości też nie zgadujemy (GUGiK: kilka miejscowości o tej nazwie)."""
    http = FakeHttp(gugik={'Józefów': JOZEFOWY}, nominatim=[[
        {'lat': '50.48', 'lon': '23.05', 'place_rank': 30},
        {'lat': '52.13', 'lon': '21.23', 'place_rank': 30}]])
    wynik = g.geokoduj_adres('Nieznana 10', 'Józefów', None, 'PL', http, _bez_spania)
    assert wynik.quality == 'nie_znaleziono'
    nominatim = [p for u, p, _ in http.wywolania if u == g.NOMINATIM_URL]
    assert len(nominatim) == 1 and nominatim[0]['limit'] == g.LIMIT_NOMINATIM_BEZ_KODU


def test_bez_kodu_bliskie_wyniki_nominatim_to_punkt():
    http = FakeHttp(nominatim=[[{'lat': '50.10', 'lon': '19.90', 'place_rank': 30},
                                {'lat': '50.11', 'lon': '19.91', 'place_rank': 26}]])
    wynik = g.geokoduj_adres('Nowa 5', 'Kraków', None, 'PL', http, _bez_spania)
    assert wynik == g.Wynik(50.10, 19.90, 'nominatim', 'dokladna')


def test_z_kodem_nominatim_pyta_o_jeden_wynik():
    http = FakeHttp(nominatim=[[{'lat': '50.1', 'lon': '19.9', 'place_rank': 30}]])
    g.geokoduj_adres('Nowa 5', 'Kraków', '30-001', 'PL', http, _bez_spania)
    assert http.wywolania[-1][1]['limit'] == 1


def test_bez_kodu_miejscowosc_wieloznaczna_to_nie_znaleziono():
    """„Nowa Wieś” bez kodu: Nominatim wskazałby którąkolwiek — nie pytamy go o miejscowość."""
    http = FakeHttp(gugik={'Nowa Wieś': NOWA_WIES}, nominatim=[[]])
    wynik = g.geokoduj_adres('Nieistniejąca 1', 'Nowa Wieś', None, 'PL', http, _bez_spania)
    assert wynik.quality == 'nie_znaleziono'
    assert len([u for u, _, _ in http.wywolania if u == g.NOMINATIM_URL]) == 1


def test_odleglosc_km():
    assert g._odleglosc_km((50.0, 20.0), (50.0, 20.0)) == 0
    assert g._odleglosc_km((52.13, 21.23), (50.48, 23.05)) == pytest.approx(221, abs=5)
