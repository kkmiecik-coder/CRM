# -*- coding: utf-8 -*-
"""Katalog statystyk pulpitu Analizy sprzedażowej.

Te testy nie dotykają bazy ani Flaska — `uklad.py` jest, tak jak `fields.py`,
czystym rejestrem, który da się czytać i sprawdzać bez podnoszenia aplikacji.

NIEZMIENNIK, dla którego ten plik w ogóle powstał: katalog i
`analiza_service.DOMYSLNE_WYMIARY` opisują TO SAMO — które karty mają selektor
wymiaru i jaki wymiar pokazują na start. Dwie listy, które muszą znaczyć to samo,
rozjeżdżają się zawsze; tu rozjazd kończy się czerwonym testem, a nie kartą bez
selektora albo kartą z selektorem, którego nikt nie obsługuje.
"""
import dataclasses
import importlib.util
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.reports.fields import POLA, wymiary
from modules.reports.uklad import (
    KATALOG, MAKS_KAFELKOW, UKLAD_DOMYSLNY, Instancja, TypKafelka,
    katalog_do_json, wymiary_typu,
)

# Kolejność DOM-u dashboardu z makiety: rząd 1 (kpi, wnioski, kanal),
# rząd 2 (opiekun, mix, klienci, wojewodztwo), rząd 3 (lejek, wykonczenie,
# dostawa). Spisana z modules/reports/templates/analiza/dashboard.html.
#
# BEZ „Należności według" (partia E, punkt E1): decyzja prezesa z 23.09.2026,
# doprecyzowana przez użytkownika — karta znika TYLKO z układu domyślnego.
# Typ zostaje w katalogu i da się go dodać przez „+ Dodaj statystykę".
KOLEJNOSC_Z_MAKIETY = ['kpi', 'wnioski', 'kanal', 'opiekun', 'mix', 'klienci',
                       'wojewodztwo', 'lejek', 'wykonczenie', 'dostawa']


def test_katalog_ma_jedenascie_typow():
    """Katalog ma dalej jedenaście typów — o jeden więcej niż układ domyślny,
    bo należności wypadły wyłącznie z układu (E1)."""
    assert len(KATALOG) == 11


def test_naleznosci_zostaja_w_katalogu_ale_nie_w_ukladzie_domyslnym():
    assert 'naleznosci' in KATALOG
    assert 'naleznosci' in [p['klucz'] for p in katalog_do_json()]
    assert 'naleznosci' not in [i.typ for i in UKLAD_DOMYSLNY]
    # Wszystkie POZOSTAŁE typy katalogu stoją na pulpicie domyślnym.
    assert set(KATALOG) - {i.typ for i in UKLAD_DOMYSLNY} == {'naleznosci'}


def test_klucz_slownika_zgadza_sie_z_kluczem_typu():
    for klucz, typ in KATALOG.items():
        assert klucz == typ.klucz


@pytest.mark.parametrize('klucz', KOLEJNOSC_Z_MAKIETY + ['naleznosci'])
def test_kazda_dzisiejsza_karta_ma_swoj_typ(klucz):
    """Żadna z jedenastu kart nie może wypaść z katalogu — inaczej układ
    domyślny przestałby być dzisiejszym układem, a karty spoza niego (dziś:
    należności) nie dałoby się dodać przez „+ Dodaj statystykę"."""
    assert klucz in KATALOG


def test_kazdy_typ_wymiarowy_jest_znany_serwisowi():
    """Katalog nie może uznać karty za wymiarową, jeśli serwis o tym nie wie.

    Serwis opisuje to w DWÓCH miejscach, bo karty kubełkowe („Klienci według",
    „Należności według") mają własną, węższą listę wymiarów i pseudo-wymiar
    domyślny spoza rejestru (commit 5206f18). Katalog musi się zgadzać z sumą
    obu."""
    from modules.reports.analiza_service import DOMYSLNE_WYMIARY, KARTY_KUBELKOWE
    wymiarowe = {k for k, t in KATALOG.items() if t.wymiarowy}
    assert wymiarowe == set(DOMYSLNE_WYMIARY) | set(KARTY_KUBELKOWE)


def test_domyslny_wymiar_typu_zwyklego_zgadza_sie_z_domyslne_wymiary():
    from modules.reports.analiza_service import DOMYSLNE_WYMIARY
    z_katalogu = {k: t.domyslny_wymiar for k, t in KATALOG.items()
                  if t.wymiarowy and t.wymiary is None}
    assert z_katalogu == dict(DOMYSLNE_WYMIARY)


def test_domyslny_wymiar_karty_kubelkowej_to_jej_pseudo_wymiar():
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    for klucz, opis in KARTY_KUBELKOWE.items():
        assert KATALOG[klucz].domyslny_wymiar == opis['domyslny']


def test_lista_wymiarow_karty_kubelkowej_zgadza_sie_z_serwisem():
    """Gdyby katalog przepuścił wymiar POZYCJI na kartę należności, saldo
    zwielokrotniłoby się przez liczbę pozycji — ten sam błąd 7,58×, od którego
    zaczął się cały projekt."""
    from modules.reports.analiza_service import wymiary_karty_kubelkowej
    from modules.reports.analiza_service import KARTY_KUBELKOWE
    for klucz in KARTY_KUBELKOWE:
        z_serwisu = [p['nazwa'] for p in wymiary_karty_kubelkowej(klucz)]
        assert list(KATALOG[klucz].wymiary) == z_serwisu, klucz


def test_typ_bez_wlasnej_listy_przyjmuje_caly_rejestr():
    for klucz in ('kanal', 'opiekun', 'mix', 'wojewodztwo', 'wykonczenie', 'dostawa'):
        assert KATALOG[klucz].wymiary is None
        assert wymiary_typu(klucz) == wymiary()


def test_typ_z_wlasna_lista_przyjmuje_tylko_ja():
    for klucz in ('klienci', 'naleznosci'):
        assert wymiary_typu(klucz) == list(KATALOG[klucz].wymiary)


def test_pseudo_wymiar_nie_jest_polem_rejestru():
    """To jest cała przyczyna, dla której `TypKafelka.wymiary` w ogóle istnieje:
    „kubełki po liczbie zamówień" nie są kolumną i nigdy nią nie będą."""
    dozwolone = set(wymiary())
    for klucz in ('klienci', 'naleznosci'):
        assert KATALOG[klucz].domyslny_wymiar not in dozwolone


def test_domyslny_wymiar_typu_zwyklego_jest_w_rejestrze_pol():
    dozwolone = set(wymiary())
    for typ in KATALOG.values():
        if typ.wymiarowy and typ.wymiary is None:
            assert typ.domyslny_wymiar in dozwolone, f'{typ.klucz}: {typ.domyslny_wymiar}'


def test_domyslny_wymiar_jest_zawsze_na_liscie_wymiarow_swojego_typu():
    for klucz, typ in KATALOG.items():
        if typ.wymiarowy:
            assert typ.domyslny_wymiar in wymiary_typu(klucz), klucz


def test_wymiary_naleznosci_nie_zawieraja_wymiaru_pozycji():
    """Wprost, a nie tylko przez porównanie z serwisem: gdyby ktoś kiedyś dopisał
    tu `wood_species`, saldo zamówienia pomnożyłoby się przez liczbę jego pozycji."""
    from modules.reports.fields import POLA, Poziom
    for nazwa in KATALOG['naleznosci'].wymiary:
        if nazwa in POLA:
            assert POLA[nazwa].poziom is Poziom.ZAMOWIENIE, nazwa


def test_tylko_kpi_jest_szeroki_na_dwie_kolumny():
    """Rozstrzygnięcie 2: szerokość wynika z typu i tylko KPI ma dwie kolumny."""
    szerokie = {k for k, t in KATALOG.items() if t.szerokosc == 2}
    assert szerokie == {'kpi'}


def test_typ_bez_wymiaru_nie_ma_domyslnego_wymiaru():
    for typ in KATALOG.values():
        if not typ.wymiarowy:
            assert typ.domyslny_wymiar is None, typ.klucz


def test_typ_bez_wymiaru_jest_jednokrotny():
    """Druga instancja typu bez wymiaru pokazywałaby co do cyfry to samo,
    a kosztowała drugi komplet zapytań."""
    for typ in KATALOG.values():
        if not typ.wymiarowy:
            assert typ.wielokrotny is False, typ.klucz


def test_kpi_wnioski_i_lejek_sa_jednokrotne():
    for klucz in ('kpi', 'wnioski', 'lejek'):
        assert KATALOG[klucz].wielokrotny is False


def test_kazdy_typ_wymiarowy_jest_wielokrotny():
    """Cel funkcji wprost: „3× klienci wg, ale z różnymi »według«". Gdyby
    którykolwiek typ wymiarowy był jednokrotny, ten przykład przestałby działać
    akurat dla niego."""
    for klucz, typ in KATALOG.items():
        if typ.wymiarowy:
            assert typ.wielokrotny is True, klucz


def test_klienci_i_naleznosci_sa_wymiarowe_i_wielokrotne():
    """Dosłowny przykład użytkownika dotyczył karty klientów."""
    for klucz in ('klienci', 'naleznosci'):
        assert KATALOG[klucz].wymiarowy is True
        assert KATALOG[klucz].wielokrotny is True
        assert len(KATALOG[klucz].wymiary) >= 3


@pytest.mark.parametrize('klucz', sorted(KOLEJNOSC_Z_MAKIETY))
def test_typ_ma_niepusta_nazwe_i_opis(klucz):
    typ = KATALOG[klucz]
    assert typ.nazwa.strip()
    assert typ.opis.strip()
    assert typ.opis.rstrip().endswith('.'), 'opis to zdanie, z kropką'


def test_nazwy_typow_sa_parami_rozne():
    """Cztery karty noszą na pulpicie tytuł »Sprzedaż netto według:«. W modalu
    muszą dać się rozróżnić, inaczej użytkownik dodaje losową z nich."""
    nazwy = [t.nazwa for t in KATALOG.values()]
    assert len(set(nazwy)) == len(nazwy), 'dwa typy mają tę samą nazwę w modalu'


def test_uklad_domyslny_ma_kolejnosc_dzisiejszego_dashboardu():
    assert [i.typ for i in UKLAD_DOMYSLNY] == KOLEJNOSC_Z_MAKIETY


def test_uklad_domyslny_bierze_wymiary_z_katalogu():
    for instancja in UKLAD_DOMYSLNY:
        assert instancja.wymiar == KATALOG[instancja.typ].domyslny_wymiar


def test_uklad_domyslny_miesci_sie_w_limicie():
    assert len(UKLAD_DOMYSLNY) <= MAKS_KAFELKOW


def test_limit_kafelkow_zostawia_zapas_ponad_uklad_domyslny():
    """20 to nie liczba z sufitu — patrz sekcja R3 planu z pomiarami.
    Ma zostać miejsce na co najmniej pięć własnych kafelków."""
    assert MAKS_KAFELKOW - len(UKLAD_DOMYSLNY) >= 5


def test_klucz_instancji_bez_wymiaru_to_sam_typ():
    assert Instancja('kpi').klucz == 'kpi'


def test_klucz_instancji_z_wymiarem_niesie_wymiar():
    assert Instancja('kanal', 'caretaker').klucz == 'kanal:caretaker'


def test_dwie_instancje_tego_samego_typu_maja_rozne_klucze():
    """Sedno całej funkcji: »3× klienci wg, ale z różnymi według«."""
    a = Instancja('kanal', 'order_source')
    b = Instancja('kanal', 'caretaker')
    assert a.klucz != b.klucz


def test_klucze_ukladu_domyslnego_sa_unikalne():
    klucze = [i.klucz for i in UKLAD_DOMYSLNY]
    assert len(set(klucze)) == len(klucze)


def test_instancja_jest_niemutowalna():
    """Układ wędruje przez serwis, payload i szablon — mutacja po drodze
    byłaby nie do wyśledzenia. Gołe `Exception` złapałoby też pomyłkę w samym
    teście (np. literówkę w nazwie pola), więc łapiemy konkretny wyjątek
    dataclasses dla frozen=True."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        Instancja('kpi').typ = 'wnioski'


def test_typ_z_bledna_szerokoscia_nie_powstaje():
    with pytest.raises(ValueError):
        TypKafelka('x', 'X', 'Opis.', szerokosc=3)


def test_typ_wymiarowy_bez_domyslnego_wymiaru_nie_powstaje():
    with pytest.raises(ValueError):
        TypKafelka('x', 'X', 'Opis.', wymiarowy=True)


def test_typ_niewymiarowy_z_domyslnym_wymiarem_nie_powstaje():
    with pytest.raises(ValueError):
        TypKafelka('x', 'X', 'Opis.', domyslny_wymiar='caretaker')


def test_typ_z_wymiarem_spoza_rejestru_powstaje_a_rozjazd_lapia_testy():
    """KONTRAKT ODWRÓCONY 23.09.2026 (przegląd całej gałęzi, M7).

    `TypKafelka` sprawdza przy budowie WYŁĄCZNIE własną spójność — nie pyta
    rejestru pól. Do tej pory pytał i jedna zmiana w `fields.py` (pole traci
    `wymiar=True`, np. żeby zniknęło z Eksploratora) wywracała import całej
    aplikacji: gunicorn nie wstawał, a `flask migrate` w `deploy.sh` padał już
    po `git reset --hard`. Zgodność katalogu z rejestrem pilnują teraz TESTY
    tego pliku (niżej: „…jest_w_rejestrze_pol", „…wlasna_lista_wskazuje…"),
    czyli przed deployem, a nie import na produkcji.

    `email` jest w POLA, ale nie ma wymiar=True — typ powstaje, a kafelek po
    nim po prostu nie przejdzie walidacji (patrz `wymiary_typu`)."""
    assert 'email' in POLA and 'email' not in set(wymiary())
    typ = TypKafelka('x', 'X', 'Opis.', wymiarowy=True, domyslny_wymiar='email')
    assert typ.domyslny_wymiar == 'email'


def test_domyslny_wymiar_spoza_wlasnej_listy_nadal_nie_powstaje():
    """Sprawdzenie STRUKTURALNE zostaje: domyślny wymiar typu z własną listą
    musi na niej stać — to spójność samego wpisu, nie rejestru."""
    with pytest.raises(ValueError):
        TypKafelka('x', 'X', 'Opis.', wymiarowy=True, domyslny_wymiar='a',
                   wielokrotny=True, wymiary=('b', 'c'))


def test_wlasna_lista_wskazuje_wylacznie_rejestr_albo_pseudo_wymiar():
    """Przeniesione z `TypKafelka.__post_init__` (M7). Pozycja z własnej
    listy albo jest polem rejestru z wymiar=True, albo pseudo-wymiarem, czyli
    domyślną wartością tego samego typu spoza rejestru. Trzeciej możliwości
    nie ma: literówka przeszłaby walidację zapisu i wywróciła kartę."""
    dozwolone = set(wymiary())
    for typ in KATALOG.values():
        if typ.wymiary is None:
            continue
        for nazwa in typ.wymiary:
            pseudo = nazwa == typ.domyslny_wymiar and nazwa not in POLA
            assert nazwa in dozwolone or pseudo, f'{typ.klucz}: {nazwa}'


def test_uklad_domyslny_ma_wszystkie_dziesiec_kafelkow():
    """Układ domyślny pomija przy budowie kafelek, którego wymiar przestał być
    ważny (zamiast wywracać import). Ten test pilnuje, żeby to pominięcie nigdy
    nie przeszło po cichu przez deploy: na dziś żadnego nie brakuje."""
    assert len(UKLAD_DOMYSLNY) == len(KOLEJNOSC_Z_MAKIETY) == 10


# --- zmiana rejestru pól nie wywraca aplikacji (M7) -------------------------
# Symulacja zmiany w `fields.py`: pole traci wymiar=True. Plik rejestru zostaje
# nietknięty — podmieniamy wpis w słowniku POLA na czas testu.

SCIEZKA_UKLADU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'modules', 'reports', 'uklad.py')

# Wszystkie pola, na które wskazuje katalog. `konfiguracja` nie ma tu miejsca:
# to wymiar złożony i `fields.Pole` sam odrzuca jego wyłączenie (błąd siedzi
# wtedy w edytowanym wpisie, nie w innym pliku).
POLA_KATALOGU = ['payment_method', 'current_status', 'client_origin', 'finish_state',
                 'order_source', 'caretaker', 'delivery_state', 'delivery_method']


def _bez_wymiaru(monkeypatch, nazwa):
    monkeypatch.setitem(POLA, nazwa, dataclasses.replace(POLA[nazwa], wymiar=False))


def _swiezy_import_ukladu(monkeypatch):
    """`uklad.py` wykonany od nowa, pod osobną nazwą — dokładnie to, co robi
    import przy starcie aplikacji. Prawdziwy moduł zostaje nietknięty, więc
    reszta pakietu nie widzi ani nowego KATALOG-u, ani nowych klas."""
    nazwa = 'uklad_swiezy_import_testu'
    spec = importlib.util.spec_from_file_location(nazwa, SCIEZKA_UKLADU)
    modul = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, nazwa, modul)
    spec.loader.exec_module(modul)
    return modul


@pytest.mark.parametrize('nazwa', POLA_KATALOGU)
def test_pole_ktore_stracilo_wymiar_nie_wywraca_budowy_katalogu(monkeypatch, caplog, nazwa):
    """Przed poprawką M7 ten import rzucał ValueError dla każdego z tych pól,
    czyli `import app` padał i cały CRM (razem z API tabletów hali) nie
    wstawał. Teraz katalog powstaje, wymiar znika z list, a układ domyślny
    pomija tylko kafelek, którego wymiar przestał być ważny — z ostrzeżeniem
    w logu."""
    _bez_wymiaru(monkeypatch, nazwa)
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        modul = _swiezy_import_ukladu(monkeypatch)
    assert list(modul.KATALOG) == list(KATALOG)
    for klucz in modul.KATALOG:
        assert nazwa not in modul.wymiary_typu(klucz), klucz
    oczekiwany = [i.klucz for i in UKLAD_DOMYSLNY if i.wymiar != nazwa]
    assert [i.klucz for i in modul.UKLAD_DOMYSLNY] == oczekiwany
    if len(oczekiwany) < len(UKLAD_DOMYSLNY):
        assert any(r.name == 'reports.uklad' and r.levelno >= logging.WARNING
                   and nazwa in r.getMessage() for r in caplog.records)


def test_wymiary_typu_pomija_pole_ktore_stracilo_wymiar(monkeypatch):
    """Samo zdjęcie wyjątku nie wystarczy: nieaktualna pozycja z krotki
    przeszłaby `_rozpoznaj`, a `naleznosci_wg_wymiaru` rzuciłby ValueError,
    czyli 500. Lista typu to część wspólna krotki i BIEŻĄCEGO rejestru."""
    _bez_wymiaru(monkeypatch, 'payment_method')
    lista = wymiary_typu('naleznosci')
    assert 'payment_method' not in lista
    # Pseudo-wymiaru w rejestrze nie ma nigdy — zostaje.
    assert lista[0] == KATALOG['naleznosci'].domyslny_wymiar
    assert 'caretaker' in lista


def test_wymiary_typu_bez_wlasnej_listy_idzie_za_biezacym_rejestrem(monkeypatch):
    _bez_wymiaru(monkeypatch, 'finish_state')
    assert 'finish_state' not in wymiary_typu('wykonczenie')


def test_zapisany_kafelek_z_polem_ktore_stracilo_wymiar_jest_pomijany(monkeypatch):
    """R2 planu: pozycja pominięta i policzona, nie kasowana i nie 500."""
    from modules.reports.uklad import uklad_z_bazy
    _bez_wymiaru(monkeypatch, 'payment_method')
    uklad, pominietych = uklad_z_bazy([{'typ': 'kpi', 'wymiar': None},
                                       {'typ': 'naleznosci', 'wymiar': 'payment_method'}])
    assert uklad == [Instancja('kpi')]
    assert pominietych == 1


def test_domyslne_wymiary_serwisu_pomijaja_niewazny_wymiar_bez_wyjatku(monkeypatch, caplog):
    from modules.reports.analiza_service import _domyslne_wymiary
    _bez_wymiaru(monkeypatch, 'finish_state')
    with caplog.at_level(logging.WARNING, logger='reports.uklad'):
        domyslne = _domyslne_wymiary()
    assert 'wykonczenie' not in domyslne
    assert domyslne['kanal'] == 'order_source'
    assert any(r.name == 'reports.uklad' and 'finish_state' in r.getMessage()
               for r in caplog.records)


def test_katalog_do_json_niesie_wszystko_czego_potrzebuje_modal():
    pozycje = katalog_do_json()
    assert len(pozycje) == len(KATALOG)
    for pozycja in pozycje:
        assert set(pozycja) == {'klucz', 'nazwa', 'opis', 'szerokosc',
                                'wymiarowy', 'wielokrotny', 'domyslny_wymiar',
                                'wymiary'}


def test_katalog_do_json_niesie_liste_wymiarow_gotowa_dla_modalu():
    """Modal nie ma wyliczać, które wymiary wolno wybrać dla którego typu —
    dostaje gotową listę nazw. Etykiety bierze z osobnej listy wymiarów."""
    po_kluczu = {p['klucz']: p for p in katalog_do_json()}
    assert po_kluczu['kanal']['wymiary'] == wymiary()
    assert po_kluczu['klienci']['wymiary'] == list(KATALOG['klienci'].wymiary)
    assert po_kluczu['kpi']['wymiary'] == []


def test_katalog_do_json_zachowuje_kolejnosc_katalogu():
    assert [p['klucz'] for p in katalog_do_json()] == list(KATALOG)
