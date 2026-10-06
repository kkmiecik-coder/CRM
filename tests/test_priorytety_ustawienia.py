# -*- coding: utf-8 -*-
"""
Stałe i ustawienia pakietu priorytetów (plan K1, Task 1; spec 8.6, 9.1).

Klucze `prod_config` są kontraktem między migracją, serwisami i panelem (K2–K4b) — test porównuje je dosłownie
z napisami z pliku migracji. Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
import pytest

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.priorytety import stale
from modules.production.priorytety.services import ustawienia
from modules.production.services import station_catalog
from tests.logistyka_fixtures import app  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, ustaw  # noqa: F401
from tests.test_migracja_priorytety import wiersze_konfiguracji

pytestmark = pytest.mark.usefixtures('app', 'czyste_ustawienia')


class LoggerSzpieg(object):
    def __init__(self):
        self.ostrzezenia = []

    def debug(self, message, **kwargs):
        pass

    info = error = debug

    def warning(self, message, **kwargs):
        self.ostrzezenia.append((message, kwargs))


@pytest.fixture()
def szpieg(monkeypatch):
    szpieg = LoggerSzpieg()
    monkeypatch.setattr(ustawienia, 'logger', szpieg)
    return szpieg


# ── stałe ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_statusy_produkcji_to_siedem_kolejek_stanowisk():
    assert stale.STATUSY_PRODUKCJI == (
        'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie', 'czeka_na_formatowanie',
        'czeka_na_krawedzie', 'czeka_na_lakiernie', 'czeka_na_pakowanie')
    for obcy in ('w_realizacji', 'czeka_na_logistyke', 'czeka_na_wykanczanie', 'wstrzymane', 'anulowane'):
        assert obcy not in stale.STATUSY_PRODUKCJI
    # Każda kolejka stanowiska jest statusem produkcji i odwrotnie — jedno źródło w station_catalog.
    assert set(stale.STATUSY_PRODUKCJI) == set(station_catalog.STATION_PENDING_STATUS.values())
    assert stale.STATUSY_ZROBIONE == ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')


def test_etapy_statusow_i_stanowisk():
    assert stale.ETAP_STATUSU == {
        'czeka_na_wyciecie': 0, 'czeka_na_skladanie': 0, 'czeka_na_sklejanie': 1, 'czeka_na_formatowanie': 2,
        'czeka_na_krawedzie': 3, 'czeka_na_lakiernie': 4, 'czeka_na_logistyke': 5, 'czeka_na_pakowanie': 5,
        'spakowane': 6, 'zweryfikowane': 6, 'zaladowane': 6, 'dostarczone': 6}
    assert stale.ETAP_STANOWISKA == {'cutting': 0, 'assembly': 0, 'gluing': 1, 'formatting': 2, 'edges': 3,
                                     'painting': 4, 'packaging': 5}
    # Etap stanowiska = etap statusu jego kolejki.
    for kod, status in station_catalog.STATION_PENDING_STATUS.items():
        assert stale.ETAP_STANOWISKA[kod] == stale.ETAP_STATUSU[status], kod
    assert stale.STANOWISKA == station_catalog.STATION_ORDER
    assert stale.STANOWISKA_ZAMOWIENIOWE == ('formatting', 'packaging')


def test_drabina_domyslna_dziewiec_szczebli_w_kolejnosci_3_1():
    assert stale.DRABINA_DOMYSLNA == (
        ('stars', 5), ('tag', 'po_terminie'), ('stars', 4), ('tag', 'blisko_terminu'), ('tag', 'rozpoczete'),
        ('stars', 3), ('stars', 2), ('stars', 1), ('stars', 0))
    assert stale.TAGI == (stale.TAG_PO_TERMINIE, stale.TAG_BLISKO_TERMINU, stale.TAG_ROZPOCZETE)
    assert stale.TAGI == ('po_terminie', 'blisko_terminu', 'rozpoczete')
    assert stale.RODZAJE_SZCZEBLA == ('stars', 'tag', 'route')
    assert stale.GWIAZDKI_MAX == 5


def test_listy_i_wartosci_domyslne():
    assert stale.JEDNOSTKI == ('pozycja', 'zamowienie')
    assert stale.TRYBY == ('stary', 'stol')
    # Trzy ostatnie akcje dochodzą w kroku K3 (spec 8.3: „Wyślij na stanowisko”, „Zdejmij ze stołu”, start stołów).
    assert stale.AKCJE_LOGU == ('gwiazdki', 'szczebel', 'odlozenie', 'odlozenie_zamkniete', 'ustawienia',
                                'przeliczenie', 'wyslanie', 'zdjecie', 'start_stolow')
    assert stale.POWODY_ODLOZENIA == ('brak_materialu', 'awaria_maszyny', 'brak_miejsca', 'czeka_na_biuro', 'inne')
    assert stale.TYPY_DNI == ('robocze', 'kalendarzowe')
    assert (stale.STOL_K, stale.LIMIT_ODLOZEN, stale.BLISKO_TERMINU_DNI, stale.MIN_APP_VERSION_CODE) == (2, 10, 3, 0)
    assert stale.DEADLINE_DAY_TYPE_DOMYSLNY == 'robocze'
    # Ten sam limit hurtu co w panelu Logistyki — serwis nie importuje routera, więc pilnuje tego test.
    from modules.production.logistics.routers import panel_api
    assert stale.LIMIT_HURTU == panel_api.LIMIT_HURTU == 500


def test_klucze_dokladnie_jak_spec_8_6():
    assert stale.klucz_tryb('gluing') == 'priorytety_tryb_gluing'
    assert stale.klucz_stol('gluing') == 'priorytety_stol_gluing'
    assert stale.klucz_jednostka('gluing') == 'priorytety_jednostka_gluing'
    assert stale.klucz_limit('gluing') == 'priorytety_limit_odlozen_gluing'
    assert stale.klucz_blokady('gluing') == 'priorytety_blokada_gluing'
    assert ustawienia.klucz_blokady('gluing') == stale.klucz_blokady('gluing')
    assert stale.KLUCZ_BLISKO == 'priorytety_blisko_terminu_dni'
    assert stale.KLUCZ_MIN_APP == 'priorytety_min_app_version_code'
    assert stale.KLUCZ_TYP_DNI == 'DEADLINE_DAY_TYPE'

    # Migracja zakłada dokładnie te wiersze, które czytają serwisy: 35 stanowiskowych + 3 wspólne.
    z_migracji = set(wiersze_konfiguracji())
    ze_stalych = {stale.KLUCZ_BLISKO, stale.KLUCZ_MIN_APP, stale.KLUCZ_TYP_DNI}
    for kod in stale.STANOWISKA:
        ze_stalych |= {stale.klucz_tryb(kod), stale.klucz_stol(kod), stale.klucz_jednostka(kod),
                       stale.klucz_limit(kod), stale.klucz_blokady(kod)}
    assert len(ze_stalych) == 38
    assert z_migracji == ze_stalych


def test_wartosci_migracji_rowne_domyslnym_w_kodzie():
    """Baza po migracji i baza bez wierszy (testy, samonaprawa) muszą zachowywać się tak samo."""
    wiersze = wiersze_konfiguracji()
    for kod in stale.STANOWISKA:
        assert wiersze[stale.klucz_tryb(kod)][0] == ustawienia.tryb(kod)
        assert int(wiersze[stale.klucz_stol(kod)][0]) == ustawienia.miejsca(kod)
        assert wiersze[stale.klucz_jednostka(kod)][0] == ustawienia.jednostka(kod)
        assert int(wiersze[stale.klucz_limit(kod)][0]) == ustawienia.limit(kod)
    assert int(wiersze[stale.KLUCZ_BLISKO][0]) == ustawienia.prog_blisko()
    assert int(wiersze[stale.KLUCZ_MIN_APP][0]) == ustawienia.min_app_version()
    assert wiersze[stale.KLUCZ_TYP_DNI][0] == ustawienia.typ_dni_terminu()


# ── odczyt ustawień ───────────────────────────────────────────────────────────────────────────────────────────

def test_domyslne_bez_wierszy_w_bazie():
    assert ProductionConfig.query.count() == 0
    assert ustawienia.tryb('gluing') == 'stary'
    assert ustawienia.miejsca('gluing') == 2
    assert ustawienia.jednostka('formatting') == 'zamowienie'
    assert ustawienia.jednostka('packaging') == 'zamowienie'
    assert ustawienia.jednostka('gluing') == 'pozycja'
    assert ustawienia.limit('gluing') == 10
    assert ustawienia.prog_blisko() == 3
    assert ustawienia.min_app_version() == 0
    assert ustawienia.typ_dni_terminu() == 'robocze'


def test_wartosc_z_prod_config_wygrywa():
    ustaw('priorytety_stol_gluing', '1', 'integer')
    ustaw('priorytety_limit_odlozen_gluing', '3', 'integer')
    ustaw('priorytety_jednostka_gluing', 'zamowienie')
    ustaw('priorytety_tryb_gluing', 'stol')
    ustaw('priorytety_blisko_terminu_dni', '5', 'integer')
    ustaw('priorytety_min_app_version_code', '173', 'integer')
    ustaw('DEADLINE_DAY_TYPE', 'kalendarzowe')
    assert ustawienia.miejsca('gluing') == 1
    assert ustawienia.limit('gluing') == 3
    assert ustawienia.jednostka('gluing') == 'zamowienie'
    assert ustawienia.tryb('gluing') == 'stol'
    assert ustawienia.prog_blisko() == 5
    assert ustawienia.min_app_version() == 173
    assert ustawienia.typ_dni_terminu() == 'kalendarzowe'
    # Ustawienie jednego stanowiska nie przecieka na inne.
    assert ustawienia.miejsca('cutting') == 2
    assert ustawienia.tryb('cutting') == 'stary'


def test_wartosc_spoza_listy_wraca_do_domyslnej_z_ostrzezeniem(szpieg):
    ustaw('DEADLINE_DAY_TYPE', 'lunarne')
    ustaw('priorytety_tryb_gluing', 'turbo')
    ustaw('priorytety_jednostka_formatting', 'paleta')
    assert ustawienia.typ_dni_terminu() == 'robocze'
    assert ustawienia.tryb('gluing') == 'stary'
    assert ustawienia.jednostka('formatting') == 'zamowienie'
    assert len(szpieg.ostrzezenia) == 3


def test_liczba_nie_do_odczytania_wraca_do_domyslnej_z_ostrzezeniem(szpieg):
    ustaw('priorytety_stol_gluing', 'dwa')            # typ string — config_service odda napis
    ustaw('priorytety_limit_odlozen_gluing', '0', 'integer')
    ustaw('priorytety_blisko_terminu_dni', '-1', 'integer')
    ustaw('priorytety_min_app_version_code', 'x')
    assert ustawienia.miejsca('gluing') == 2
    assert ustawienia.limit('gluing') == 10
    assert ustawienia.prog_blisko() == 3
    assert ustawienia.min_app_version() == 0
    assert len(szpieg.ostrzezenia) == 4


def test_nieznane_stanowisko_valueerror():
    for funkcja in (ustawienia.tryb, ustawienia.miejsca, ustawienia.jednostka, ustawienia.limit,
                    ustawienia.klucz_blokady):
        with pytest.raises(ValueError):
            funkcja('sawmill')
        with pytest.raises(ValueError):
            funkcja(None)


def test_prog_blisko_wlasna_sesja_czyta_wiersz_i_nie_dotyka_db_session(app, monkeypatch):
    ustaw('priorytety_blisko_terminu_dni', '4', 'integer')
    # Z własną sesją nie wolno iść przez config_service: ten czyta przez db.session (autoflush sesji wołającego).
    from modules.production.services import config_service

    def _zakazane(*a, **k):
        raise AssertionError('prog_blisko(sesja=...) nie moze czytac przez config_service')
    monkeypatch.setattr(config_service, 'get_config', _zakazane)

    niezapisany = ProductionConfig(config_key='niezapisany', config_value='x')
    db.session.add(niezapisany)
    wlasna = db.create_session({})()
    try:
        assert ustawienia.prog_blisko(sesja=wlasna) == 4
    finally:
        wlasna.close()
    # Brak autoflushu db.session: obiekt dalej czeka na zapis.
    assert niezapisany in db.session.new
    db.session.rollback()


def test_prog_blisko_wlasna_sesja_bez_wiersza_i_z_bledna_wartoscia(app, szpieg):
    wlasna = db.create_session({})()
    try:
        assert ustawienia.prog_blisko(sesja=wlasna) == 3
        ustaw('priorytety_blisko_terminu_dni', 'trzy')
        assert ustawienia.prog_blisko(sesja=wlasna) == 3
    finally:
        wlasna.close()
    assert len(szpieg.ostrzezenia) == 1
