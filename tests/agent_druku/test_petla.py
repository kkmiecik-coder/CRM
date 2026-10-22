"""Pętla usługi agenta druku v2 — z atrapą klienta CRM i drukarek."""
import types
from datetime import datetime

import pytest

from agent_druku import WERSJA, petla
from agent_druku.crm import BladCrm, NieznanyAgent

ZWYKLY_DZIEN = datetime(2026, 10, 21, 10, 0)    # środa, w godzinach pracy
NOC = datetime(2026, 10, 21, 22, 0)

DRUKARKI = [
    {'nazwa': 'etykiety', 'ip': '192.0.2.10', 'port': 9100, 'model': 'XP-423B',
     'odczyt_stanu': 'snmp', 'limit_wysylki_s': 10},
    {'nazwa': 'wysylka', 'ip': '192.0.2.11', 'port': 9100, 'model': 'XP-410B',
     'odczyt_stanu': 'brak', 'limit_wysylki_s': 30},
]
KONFIGURACJA = {
    'drukarki': DRUKARKI,
    'przesuniecia': {'etykiety': {'lt': 0, 'ls': 0}, 'wysylka': {'dx': 0, 'dy': 0}},
    'godziny': {'pn_pt': ['05:30', '15:30'], 'sobota': ['05:30', '15:30']},
}


class Zegar:
    def __init__(self, teraz=ZWYKLY_DZIEN):
        self.chwila = teraz
        self.mono = 1000.0
        self.czekania = []

    def teraz(self):
        return self.chwila

    def monotonic(self):
        return self.mono

    def czekaj(self, zdarzenie, sekundy):
        self.czekania.append(sekundy)
        return zdarzenie.is_set()


def _zadanie(i, drukarka='etykiety'):
    return {'id': i, 'drukarka': drukarka, 'zpl': '^XA%d^XZ' % i, 'kod': 'K%d' % i,
            'stanowisko': 'formatting', 'zlecono': None}


class Crm:
    """Atrapa klienta CRM: zapisuje wywołania, kolejki zadań per drukarka."""

    def __init__(self):
        self.wywolania = []
        self.kolejki = {'etykiety': [], 'wysylka': []}
        self.obsluga = {}
        self.wyslane_wyniki = []
        self.polecenia = []
        self.awaria = False
        self.nieznany = False
        self.wersja_konf = 1
        self.dane_konf = KONFIGURACJA
        self.blad_zapisu = None
        self.aktualizacja = None

    def _wejscie(self, nazwa, *arg):
        self.wywolania.append((nazwa,) + arg)
        if self.nieznany:
            raise NieznanyAgent(401, 'nieznany_agent')
        if self.awaria:
            raise BladCrm(None, 'brak połączenia')

    def kontakt(self, wersja, drukarki, push, wersja_konfiguracji):
        self._wejscie('kontakt', wersja, drukarki, push, wersja_konfiguracji)
        polecenia, self.polecenia = self.polecenia, []
        return {'wersja_konfiguracji': self.wersja_konf, 'aktualizacja': self.aktualizacja,
                'polecenia': polecenia}

    def pobierz(self, drukarka, limit=10):
        self._wejscie('pobierz', drukarka)
        if self.obsluga.get(drukarka):
            return {'zadania': [], 'obsluga': self.obsluga[drukarka]}
        porcja = self.kolejki[drukarka][:limit]
        self.kolejki[drukarka] = self.kolejki[drukarka][limit:]
        return {'zadania': porcja}

    def wysylam(self, id_zadania):
        self._wejscie('wysylam', id_zadania)
        return {'ok': True}

    def wyniki(self, wyniki):
        self._wejscie('wyniki', wyniki)
        self.wyslane_wyniki.extend(wyniki)
        return {'zmienione': len(wyniki)}

    def konfiguracja(self):
        self._wejscie('konfiguracja')
        return {'wersja': self.wersja_konf, 'dane': self.dane_konf}

    def zapisz_konfiguracje(self, wersja_bazowa, dane):
        self._wejscie('zapisz_konfiguracje', wersja_bazowa)
        if self.blad_zapisu is not None:
            raise self.blad_zapisu
        self.wersja_konf += 1
        self.dane_konf = dane
        return {'wersja': self.wersja_konf, 'dane': dane, 'nadpisano': None}

    def wynik_polecenia(self, id_polecenia, ok, opis=''):
        self._wejscie('wynik_polecenia', id_polecenia, ok, opis)
        return {'ok': True}

    def nazwy(self):
        return [w[0] for w in self.wywolania]


class Drukarki:
    """Atrapa modułu drukarek: stan na nazwę, zapis wysłanych porcji."""

    def __init__(self):
        self.stany = {'etykiety': ('gotowa', ''), 'wysylka': ('gotowa', '')}
        self.porcje = []
        self.kalibracje = []
        self.niedostepne = set()

    def stan(self, drukarka):
        return self.stany[drukarka['nazwa']]

    def wyslij_porcje(self, drukarka, zadania, przed_wyslaniem):
        assert all(set(z) == {'id', 'zpl'} for z in zadania)
        self.porcje.append((drukarka['nazwa'], [z['id'] for z in zadania]))
        if drukarka['nazwa'] in self.niedostepne:
            return [{'id': z['id'], 'wynik': 'niewyslane'} for z in zadania]
        wyniki = []
        for z in zadania:
            if przed_wyslaniem(z['id']):
                wyniki.append({'id': z['id'], 'wynik': 'wydrukowane'})
            else:
                wyniki.append({'id': z['id'], 'wynik': 'niewyslane'})
        return wyniki

    def kalibruj(self, drukarka):
        self.kalibracje.append(drukarka['nazwa'])


@pytest.fixture
def sciezki(tmp_path):
    return types.SimpleNamespace(plik_konfiguracji=lambda: tmp_path / 'konfiguracja.json',
                                 plik_dziennika=lambda: tmp_path / 'dziennik.db')


@pytest.fixture
def srodowisko(sciezki):
    crm, druk, zegar = Crm(), Drukarki(), Zegar()

    def nowy_agent():
        a = petla.Agent(sciezki, crm, zegar, drukarki=druk)
        a.lokalna.token = 'x'
        a.lokalna.wersja = 1
        a.lokalna.dane = KONFIGURACJA
        a.lokalna.zapisz()
        return a

    return types.SimpleNamespace(crm=crm, druk=druk, zegar=zegar, nowy_agent=nowy_agent,
                                 sciezki=sciezki)


def test_cykl_drukuje_i_potwierdza(srodowisko):
    s = srodowisko
    s.crm.kolejki['etykiety'] = [_zadanie(1), _zadanie(2)]
    agent = s.nowy_agent()
    agent.cykl('test')

    assert s.druk.porcje == [('etykiety', [1, 2])]
    assert [w for w in s.crm.wywolania if w[0] == 'wysylam'] == [('wysylam', 1), ('wysylam', 2)]
    assert sorted((w['id'], w['wynik']) for w in s.crm.wyslane_wyniki) == [
        (1, 'wydrukowane'), (2, 'wydrukowane')]
    # Potwierdzone w dzienniku: nic nie czeka na wysłanie, stan końcowy zapisany.
    assert agent.dziennik.niepotwierdzone() == []
    assert {w['job_id']: w['stan'] for w in agent.dziennik.ostatnie(10)} == {
        1: 'wydrukowane', 2: 'wydrukowane'}
    # Kolejność kroków: konfiguracja → pobranie → wyniki → kontakt na końcu.
    nazwy = s.crm.nazwy()
    assert nazwy.index('konfiguracja') < nazwy.index('pobierz') < nazwy.index('wyniki') < nazwy.index('kontakt')
    kontakt = [w for w in s.crm.wywolania if w[0] == 'kontakt'][0]
    assert kontakt[1] == WERSJA
    assert [d['nazwa'] for d in kontakt[2]] == ['etykiety', 'wysylka']


def test_pelna_porcja_pobiera_kolejna(srodowisko):
    s = srodowisko
    s.crm.kolejki['etykiety'] = [_zadanie(i) for i in range(1, 16)]
    s.nowy_agent().cykl('test')
    assert [p[1] for p in s.druk.porcje] == [list(range(1, 11)), list(range(11, 16))]


def test_drukarka_bez_papieru_nie_pobiera_zadan(srodowisko):
    s = srodowisko
    s.druk.stany['etykiety'] = ('brak_papieru', 'brak papieru')
    s.crm.kolejki['etykiety'] = [_zadanie(1)]
    s.crm.kolejki['wysylka'] = [_zadanie(2, 'wysylka')]
    agent = s.nowy_agent()
    agent.cykl('test')

    assert ('pobierz', 'etykiety') not in s.crm.wywolania
    assert s.druk.porcje == [('wysylka', [2])]
    stan = agent.stan_dla_okienka()
    assert stan['ogolny'] == 'uwaga'
    assert {d['nazwa']: d['stan'] for d in stan['drukarki']}['etykiety'] == 'brak_papieru'


def test_drukarka_starego_agenta_pominieta_bez_bledu(srodowisko):
    s = srodowisko
    s.crm.obsluga['wysylka'] = 'stary'
    agent = s.nowy_agent()
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    wysylka = {d['nazwa']: d for d in stan['drukarki']}['wysylka']
    assert wysylka['obsluga'] == 'stary'
    assert 'stary agent' in wysylka['komunikat']
    assert stan['ogolny'] == 'ok'


def test_niedostepna_drukarka_zwraca_niewyslane_i_skraca_polling(srodowisko):
    s = srodowisko
    s.druk.niedostepne.add('etykiety')
    s.crm.kolejki['etykiety'] = [_zadanie(1)]
    agent = s.nowy_agent()
    agent.ustaw_push(True)
    agent.cykl('test')
    assert [(w['id'], w['wynik']) for w in s.crm.wyslane_wyniki] == [(1, 'niewyslane')]
    assert agent.odstep_pollingu() == 10


def test_odstep_pollingu_zalezy_od_pushu(srodowisko):
    agent = srodowisko.nowy_agent()
    agent.cykl('test')
    assert agent.odstep_pollingu() == 10
    agent.ustaw_push(True)
    assert agent.odstep_pollingu() == 60


def test_zalegle_wyniki_najpierw(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    agent.dziennik.zapisz(7, 'etykiety', 'K7', 'wydrukowane')
    s.crm.kolejki['etykiety'] = [_zadanie(8)]
    agent.cykl('test')

    nazwy = s.crm.nazwy()
    assert nazwy[0] == 'wyniki'
    assert s.crm.wywolania[0][1] == [{'id': 7, 'wynik': 'wydrukowane'}]
    assert agent.dziennik.niepotwierdzone() == []


def test_zalegle_wyniki_przy_awarii_crm_czekaja(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    agent.dziennik.zapisz(7, 'etykiety', 'K7', 'wydrukowane')
    s.crm.awaria = True
    agent.cykl('test')
    assert [w['job_id'] for w in agent.dziennik.niepotwierdzone()] == [7]


def test_zadanie_wysylane_w_poprzednim_przebiegu_nie_idzie_drugi_raz(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    agent.dziennik.zapisz(5, 'etykiety', 'K5', 'wysylam')   # przerwane przez restart
    s.crm.kolejki['etykiety'] = [_zadanie(5)]
    agent.cykl('test')

    assert ('wysylam', 5) not in s.crm.wywolania
    wynik = [w for w in s.crm.wyslane_wyniki if w['id'] == 5][0]
    assert wynik['wynik'] == 'blad'
    assert wynik['blad'] == 'agent przerwał wysyłanie — sprawdź, czy etykieta wyszła'


def test_odmowa_wysylam_daje_niewyslane(srodowisko):
    s = srodowisko
    oryginal = s.crm.wysylam

    def odmowa(id_zadania):
        if id_zadania == 2:
            raise BladCrm(409, 'nie_twoje_zadanie')
        return oryginal(id_zadania)

    s.crm.wysylam = odmowa
    s.crm.kolejki['etykiety'] = [_zadanie(1), _zadanie(2)]
    agent = s.nowy_agent()
    agent.cykl('test')
    assert sorted((w['id'], w['wynik']) for w in s.crm.wyslane_wyniki) == [
        (1, 'wydrukowane'), (2, 'niewyslane')]


def test_poza_godzinami_tylko_kontakt(srodowisko):
    s = srodowisko
    s.zegar.chwila = NOC
    s.crm.kolejki['etykiety'] = [_zadanie(1)]
    agent = s.nowy_agent()
    agent.dziennik.zapisz(7, 'etykiety', 'K7', 'wydrukowane')
    agent.cykl('test')
    # Poza godzinami: zaległe wyniki idą, nowych zadań nie pobieramy.
    assert s.crm.nazwy() == ['wyniki', 'kontakt']
    assert agent.dziennik.niepotwierdzone() == []
    assert s.druk.porcje == []
    assert agent.odstep_pollingu() == 60

    # Kolejny cykl przed upływem 60 s nie powtarza kontaktu.
    s.zegar.mono += 30
    agent.cykl('test')
    assert s.crm.nazwy() == ['wyniki', 'kontakt']
    s.zegar.mono += 31
    agent.cykl('test')
    assert s.crm.nazwy() == ['wyniki', 'kontakt', 'kontakt']


def test_poza_godzinami_zmiana_z_okienka_idzie_do_crm(srodowisko):
    """Hub 22.10.2026: zmiana konfiguracji w okienku po godzinach czekała do rana."""
    s = srodowisko
    s.zegar.chwila = NOC
    agent = s.nowy_agent()
    agent.lokalna.zapisz_lokalnie(dict(KONFIGURACJA))
    agent.cykl('konfiguracja')
    assert 'zapisz_konfiguracje' in s.crm.nazwy()
    assert agent.lokalna.oczekujaca is None
    assert 'pobierz' not in s.crm.nazwy()


def test_poza_godzinami_nowsza_konfiguracja_z_crm(srodowisko):
    """Po parowaniu albo zmianie w CRM po godzinach agent pobiera konfigurację od razu, nie rano."""
    s = srodowisko
    s.zegar.chwila = NOC
    agent = s.nowy_agent()
    s.crm.wersja_konf = 2
    agent.cykl('polling')
    assert s.crm.nazwy() == ['kontakt', 'konfiguracja']
    assert agent.lokalna.wersja == 2
    assert 'pobierz' not in s.crm.nazwy()


def test_poza_godzinami_parowanie_synchronizuje(srodowisko):
    s = srodowisko
    s.zegar.chwila = NOC
    agent = s.nowy_agent()
    agent.cykl('parowanie')
    assert s.crm.nazwy()[:2] == ['konfiguracja', 'kontakt']


def test_niedziela_poza_godzinami(srodowisko):
    s = srodowisko
    s.zegar.chwila = datetime(2026, 10, 25, 10, 0)   # niedziela
    s.nowy_agent().cykl('test')
    assert s.crm.nazwy() == ['kontakt']


def test_polaczenie_push_wywoluje_cykl(srodowisko):
    agent = srodowisko.nowy_agent()
    powody = []
    agent.cykl = powody.append
    agent.przy_polaczeniu_push()
    agent.krok()
    assert powody == ['push-polaczony']
    assert agent.stan_dla_okienka()['push'] is True

    agent.przy_sygnale_push('print')
    agent.krok()
    assert powody[-1] == 'push-print'

    # Bez sygnału krok czeka odstęp pollingu i robi cykl „polling”.
    agent.krok()
    assert powody[-1] == 'polling'
    assert srodowisko.zegar.czekania[-1] == 60

    agent.przy_rozlaczeniu_push()
    assert agent.stan_dla_okienka()['push'] is False


def test_stan_bez_crm_czerwony(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    agent.cykl('test')
    assert agent.stan_dla_okienka()['crm'] is True
    assert agent.stan_dla_okienka()['ogolny'] == 'ok'

    s.crm.awaria = True
    s.zegar.mono += 121
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert stan['crm'] is False
    assert stan['ogolny'] == 'awaria'
    assert stan['komunikat']


def test_stan_niesparowany_czerwony(srodowisko):
    s = srodowisko
    s.crm.nieznany = True
    agent = s.nowy_agent()
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert stan['sparowany'] is False
    assert stan['ogolny'] == 'awaria'


def test_stan_zawiera_wersje_aktualizacje_i_dziennik(srodowisko):
    s = srodowisko
    s.crm.aktualizacja = {'wersja': '2.1.0', 'sha256': 'ab', 'rozmiar': 1, 'url': '/x'}
    s.crm.kolejki['etykiety'] = [_zadanie(1)]
    agent = s.nowy_agent()
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert stan['wersja'] == WERSJA
    assert stan['aktualizacja'] == s.crm.aktualizacja
    assert [w['job_id'] for w in stan['ostatnie']] == [1]
    assert stan['sparowany'] is True


def test_polecenie_kalibracji_potwierdzone(srodowisko):
    s = srodowisko
    s.crm.polecenia = [{'id': 4, 'rodzaj': 'kalibracja', 'drukarka': 'etykiety'}]
    s.nowy_agent().cykl('test')
    assert s.druk.kalibracje == ['etykiety']
    wynik = [w for w in s.crm.wywolania if w[0] == 'wynik_polecenia']
    assert len(wynik) == 1 and wynik[0][1:3] == (4, True)


def test_nieudana_kalibracja_zgloszona(srodowisko):
    s = srodowisko

    def awaria(drukarka):
        raise OSError('drukarka nie odpowiada')

    s.druk.kalibruj = awaria
    s.crm.polecenia = [{'id': 4, 'rodzaj': 'kalibracja', 'drukarka': 'wysylka'}]
    s.nowy_agent().cykl('test')
    wynik = [w for w in s.crm.wywolania if w[0] == 'wynik_polecenia'][0]
    assert wynik[1:3] == (4, False)
    assert 'nie odpowiada' in wynik[3]


def test_odrzucona_konfiguracja_porzucona_i_pokazana(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    zla = dict(KONFIGURACJA, godziny={})
    agent.lokalna.zapisz_lokalnie(zla)
    s.crm.blad_zapisu = BladCrm(400, 'bledna_konfiguracja',
                                {'error': 'bledna_konfiguracja', 'bledy': ['Godziny pracy…']})
    agent.cykl('test')
    assert agent.lokalna.oczekujaca is None
    assert agent.lokalna.dane == KONFIGURACJA
    assert agent.stan_dla_okienka()['blad_konfiguracji'] == ['Godziny pracy…']


def test_agent_nieaktywny_zachowuje_zmiane(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()
    agent.lokalna.zapisz_lokalnie(KONFIGURACJA)
    s.crm.blad_zapisu = BladCrm(409, 'agent_nieaktywny', {'error': 'agent_nieaktywny'})
    agent.cykl('test')
    assert agent.lokalna.oczekujaca is not None
    assert agent.stan_dla_okienka()['blad_konfiguracji'] == ['agent nie jest aktywny w CRM']

    s.crm.blad_zapisu = None
    agent.cykl('test')
    assert agent.lokalna.oczekujaca is None
    assert agent.stan_dla_okienka()['blad_konfiguracji'] is None


def test_przerwana_wysylka_przy_starcie_to_nieznany_bez_wyniku(srodowisko):
    s = srodowisko
    pierwszy = s.nowy_agent()
    pierwszy.dziennik.zapisz(5, 'etykiety', 'K5', 'wysylam')   # proces padł w trakcie wysyłki
    pierwszy.dziennik.zamknij()

    agent = petla.Agent(s.sciezki, s.crm, s.zegar, drukarki=s.druk)
    assert {w['job_id']: w['stan'] for w in agent.dziennik.ostatnie(10)} == {5: 'nieznany'}
    agent.cykl('test')
    assert s.crm.wyslane_wyniki == []        # o „unknown” decyduje dzierżawa serwera
    assert agent.dziennik.czy_wysylane(5)


def test_przelaczanie_obslugi_pomija_drukarke_bez_uwagi(srodowisko):
    s = srodowisko
    s.crm.obsluga['etykiety'] = 'przelaczanie'
    s.crm.kolejki['etykiety'] = [_zadanie(1)]
    s.druk.stany['etykiety'] = ('nieznany', '')
    agent = s.nowy_agent()
    agent.cykl('test')
    assert s.druk.porcje == []
    stan = agent.stan_dla_okienka()
    etykiety = {d['nazwa']: d for d in stan['drukarki']}['etykiety']
    assert etykiety['obsluga'] == 'przelaczanie'
    assert etykiety['komunikat'] == 'Przełączanie na nowego agenta — chwila'
    assert stan['ogolny'] == 'ok'


@pytest.mark.parametrize('obsluga, komunikat', [
    ('stary', 'Drukarkę obsługuje stary agent'),
    ('ktos_inny', 'Drukarka obsługiwana gdzie indziej'),
])
def test_komunikaty_obslugi(srodowisko, obsluga, komunikat):
    s = srodowisko
    s.crm.obsluga['wysylka'] = obsluga
    agent = s.nowy_agent()
    agent.cykl('test')
    assert {d['nazwa']: d for d in agent.stan_dla_okienka()['drukarki']}['wysylka']['komunikat'] == komunikat


def test_zatrzymaj_nie_robi_dodatkowego_cyklu(srodowisko):
    agent = srodowisko.nowy_agent()
    powody = []
    agent.cykl = powody.append
    agent.zatrzymaj()
    agent.krok()
    assert powody == []


def test_blad_cyklu_zostaje_mimo_udanego_kontaktu(srodowisko):
    s = srodowisko
    agent = s.nowy_agent()

    def awaria(drukarka, limit=10):
        raise BladCrm(None, 'brak połączenia')

    s.crm.pobierz = awaria
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert 'Nie udało się pobrać zadań' in stan['komunikat']
    assert stan['crm'] is True

    s.crm.pobierz = Crm.pobierz.__get__(s.crm)
    agent.cykl('test')
    assert agent.stan_dla_okienka()['komunikat'] == ''


def test_cykl_po_polaczeniu_push_najwyzej_raz_na_10_s(srodowisko):
    """Kanał, który łączy się i zrywa co sekundę, nie może odpalać pełnego cyklu przy każdym połączeniu."""
    s = srodowisko
    agent = s.nowy_agent()
    agent.przy_polaczeniu_push()
    assert agent._powod == 'push-polaczony'
    agent._powod = None
    agent._obudz.clear()
    for _ in range(5):
        s.zegar.mono += 1.5
        agent.przy_polaczeniu_push()
        assert agent._powod is None and not agent._obudz.is_set()
    assert agent.stan_dla_okienka()['push'] is True     # stan kanału i tak aktualny
    s.zegar.mono += petla.CYKL_PO_POLACZENIU_CO_S
    agent.przy_polaczeniu_push()
    assert agent._powod == 'push-polaczony'


def test_poza_godzinami_ikona_zolta_z_oknem(srodowisko):
    s = srodowisko
    s.zegar.chwila = NOC
    agent = s.nowy_agent()
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert stan['ogolny'] == 'uwaga' and stan['poza_godzinami'] is True
    assert stan['komunikat'] == 'Poza godzinami pracy (05:30–15:30) — etykiety czekają w kolejce'
    # w godzinach wraca „ok”
    s.zegar.chwila = ZWYKLY_DZIEN
    agent.cykl('test')
    stan = agent.stan_dla_okienka()
    assert stan['ogolny'] == 'ok' and stan['poza_godzinami'] is False


def test_poza_godzinami_w_niedziele(srodowisko):
    s = srodowisko
    s.zegar.chwila = datetime(2026, 10, 25, 10, 0)   # niedziela
    agent = s.nowy_agent()
    agent.cykl('test')
    assert agent.stan_dla_okienka()['komunikat'] == (
        'Poza godzinami pracy (dziś bez pracy) — etykiety czekają w kolejce')


def test_zatrzymanie_nie_bierze_kolejnej_porcji(srodowisko):
    """Po zatrzymaj() bieżąca porcja się kończy (wyniki w dzienniku i w CRM), a kolejnej nie pobieramy."""
    s = srodowisko
    s.crm.kolejki['etykiety'] = [_zadanie(i) for i in range(1, 16)]
    s.crm.kolejki['wysylka'] = [_zadanie(100, 'wysylka')]
    agent = s.nowy_agent()
    wyslij = s.druk.wyslij_porcje

    def wyslij_i_zatrzymaj(drukarka, zadania, przed):
        wyniki = wyslij(drukarka, zadania, przed)
        agent.zatrzymaj()        # usługa zatrzymywana w trakcie porcji
        return wyniki
    s.druk.wyslij_porcje = wyslij_i_zatrzymaj
    agent.cykl('test')
    assert s.druk.porcje == [('etykiety', list(range(1, 11)))]
    assert [w['id'] for w in s.crm.wyslane_wyniki] == list(range(1, 11))
    assert agent.dziennik.niepotwierdzone() == []
