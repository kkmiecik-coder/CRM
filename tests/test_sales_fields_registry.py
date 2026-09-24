# -*- coding: utf-8 -*-
"""Rejestr pól jest jedynym źródłem prawdy o kolumnach Analizy sprzedażowej.

Steruje wyglądem kolumny w arkuszu, edytowalnością, metodą zapisu do BaseLinkera
i listą wymiarów w Eksploratorze. Niespójny wpis nie wywali się przy starcie —
objawi się dopiero jako kolumna, która wygląda na edytowalną, a zapisu nie ma
gdzie wysłać. Dlatego niezmienniki pilnujemy testem.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.reports.fields import (
    POLA, Poziom, Zrodlo, miary, pola_poziomu, wymiary,
)


def test_rejestr_nie_jest_pusty():
    assert len(POLA) > 40


def test_kazde_pole_ma_etykiete_poziom_i_zrodlo():
    for nazwa, pole in POLA.items():
        assert pole.etykieta, f"{nazwa}: brak etykiety"
        assert isinstance(pole.poziom, Poziom), f"{nazwa}: zły poziom"
        assert isinstance(pole.zrodlo, Zrodlo), f"{nazwa}: złe źródło"


def test_tylko_pola_z_bl_maja_zapis():
    """Pole CRM-owe z zapisem do BL to sprzeczność — BL tego pola nie zna."""
    for nazwa, pole in POLA.items():
        if pole.zrodlo is not Zrodlo.BL:
            assert pole.zapis is None, f"{nazwa}: {pole.zrodlo} nie może mieć zapisu do BL"


def test_kazde_pole_bl_ma_zapis_albo_jest_jawnie_tylko_do_odczytu():
    """Druga połowa niezmiennika (test wyżej pilnuje tylko pierwszej): pole
    źródła BL bez `zapis` musi jawnie deklarować `edytowalne=False` — inaczej
    kolumna wygląda na edytowalną w UI, a zapisu do BaseLinkera nie ma dokąd
    wysłać."""
    for nazwa, pole in POLA.items():
        if pole.zrodlo is Zrodlo.BL:
            assert pole.zapis is not None or not pole.edytowalne, (
                f"{nazwa}: źródło BL bez zapisu musi mieć edytowalne=False"
            )


def test_wrazliwe_tylko_wsrod_pol_z_zapisem():
    """Potwierdzenie ma sens wyłącznie dla pola, które faktycznie coś wysyła."""
    for nazwa, pole in POLA.items():
        if pole.wrazliwe:
            assert pole.zapis is not None, f"{nazwa}: wrażliwe, ale nic nie wysyła"


def test_wyliczane_i_produkcyjne_nie_sa_edytowalne():
    for nazwa, pole in POLA.items():
        if pole.zrodlo in (Zrodlo.WYLICZANE, Zrodlo.PRODUKCJA):
            assert not pole.edytowalne, f"{nazwa}: nie może być edytowalne"


def test_sa_wymiary_i_miary():
    assert 'delivery_state' in wymiary()
    assert 'caretaker' in wymiary()
    assert 'wood_species' in wymiary()
    assert 'client_origin' in wymiary()
    assert 'value_net' in miary()
    assert 'total_volume' in miary()


def test_pola_poziomu_rozdziela_zamowienie_od_pozycji():
    zam = pola_poziomu(Poziom.ZAMOWIENIE)
    poz = pola_poziomu(Poziom.POZYCJA)
    assert 'caretaker' in zam and 'caretaker' not in poz
    assert 'wood_species' in poz and 'wood_species' not in zam
    assert set(zam) | set(poz) == set(POLA)


def test_rozbicie_wplat_jest_tylko_crm():
    """Sześć kolumn z Excela, których BaseLinker nie zna — zna tylko sumę."""
    for nazwa in ('advance_cash', 'advance_wp', 'advance_loza',
                  'paid_cash', 'paid_wp', 'paid_loza'):
        assert POLA[nazwa].zrodlo is Zrodlo.CRM, f"{nazwa} musi być CRM-owe"


def test_pola_z_nazwy_produktu_sa_crm_owe():
    """setOrderProductFields NIE ustawia nazwy produktu, a parser czyta te
    kolumny właśnie z niej. Zapis do BL jest więc niemożliwy."""
    for nazwa in ('wood_species', 'technology', 'wood_class', 'finish_state',
                  'length_cm', 'width_cm', 'thickness_cm'):
        assert POLA[nazwa].zrodlo is Zrodlo.CRM, f"{nazwa} musi być CRM-owe"


def test_uwagi_maja_limit_dlugosci_z_api_bl():
    assert POLA['notes'].max_dlugosc == 200


def test_wymiary_i_miary_maja_odpowiednik_w_modelu():
    """miary()/wymiary() to kontrakt, z ktorego Plan B zbuduje liste miar
    Eksploratora przez getattr(model, nazwa) — wpis bez kolumny wywali sie
    AttributeError dopiero w Eksploratorze, nie przy imporcie rejestru.

    Kazde pole z wymiar=True albo miara=True musi rozwiazywac sie na
    istniejacy atrybut SalesOrder (poziom ZAMOWIENIE) albo SalesOrderItem
    (poziom POZYCJA), chyba ze jego zrodlo to Zrodlo.PRODUKCJA — te pola
    czyta osobno modul production, nie kolumna sales_*.
    """
    from modules.reports.models_sales import SalesOrder, SalesOrderItem

    for nazwa, pole in POLA.items():
        if not (pole.wymiar or pole.miara):
            continue
        if pole.zrodlo is Zrodlo.PRODUKCJA:
            continue
        if pole.skladniki is not None:
            # Wymiar złożony nie ma własnej kolumny — sprawdzamy jego składniki.
            # Niezmiennik zostaje ten sam: nazwa z rejestru ma się rozwiązywać
            # na istniejący atrybut modelu, tylko przez jeden poziom pośrednictwa.
            for skladnik in pole.skladniki:
                skladowe = POLA[skladnik]
                model_skladnika = (SalesOrder if skladowe.poziom is Poziom.ZAMOWIENIE
                                   else SalesOrderItem)
                assert hasattr(model_skladnika, skladnik), (
                    f"{nazwa}: składnik {skladnik} nie ma kolumny "
                    f"w {model_skladnika.__name__}"
                )
            continue
        model = SalesOrder if pole.poziom is Poziom.ZAMOWIENIE else SalesOrderItem
        assert hasattr(model, nazwa), (
            f"{nazwa}: zadeklarowane jako wymiar/miara, ale {model.__name__} "
            f"nie ma takiej kolumny"
        )


# --- jednostki --------------------------------------------------------------
# Kolumna liczb bez jednostki jest nie do zinterpretowania: „2 204 223" przy
# wierszu „1 zam." czyta sie jak liczba klientow, a sa to zlotowki. Dlatego
# jednostka jest czescia deklaracji pola, a nie ozdobnikiem doklejanym w widoku.

def test_kazda_miara_ma_jednostke():
    for nazwa in miary():
        assert POLA[nazwa].jednostka, f"{nazwa}: miara bez jednostki"


def test_jednostki_sa_po_polsku():
    """Zaden 'PLN', 'm3' ani 'pcs' — na ekranie ma stac to, co tutaj."""
    dozwolone = {'zł', 'm³', 'm²', 'szt.', 'zł/m³', '%'}
    for nazwa, pole in POLA.items():
        if pole.jednostka is None:
            continue
        assert pole.jednostka in dozwolone, f"{nazwa}: nieznana jednostka {pole.jednostka!r}"


def test_miara_bez_jednostki_wywala_sie_przy_tworzeniu():
    """Niezmiennik ma bic przy imporcie rejestru, a nie na ekranie."""
    import pytest

    from modules.reports.fields import Pole, Poziom, Zrodlo

    with pytest.raises(ValueError):
        Pole('Bez jednostki', Poziom.POZYCJA, Zrodlo.WYLICZANE,
             edytowalne=False, miara=True)


def test_jednostki_miar_dashboardu_zgadzaja_sie_z_rejestrem():
    """Dashboard i Eksplorator nazywaja miary po swojemu ('netto', 'objetosc'),
    ale licza je z kolumn rejestru — jednostka musi byc TA SAMA. Rozjazd
    znaczylby, ze kafelek KPI i kolumna arkusza podaja te sama liczbe
    w dwoch roznych jednostkach."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    odpowiedniki = {
        'netto': 'value_net',
        'objetosc': 'total_volume',
        'cena_za_m3': 'price_per_m3',
        'saldo': 'balance_due',
        'srednie_zamowienie': 'value_net',
        'koszt_kuriera': 'delivery_cost',
    }
    for miara, pole in odpowiedniki.items():
        assert JEDNOSTKI_MIAR[miara] == POLA[pole].jednostka, (
            f"{miara}: {JEDNOSTKI_MIAR[miara]!r} wobec {POLA[pole].jednostka!r} "
            f"w rejestrze ({pole})"
        )


def test_kazda_miara_panelu_ma_jednostke():
    from modules.reports.analiza_service import (
        JEDNOSTKI_MIAR, MIARY_PANELU, MIARY_PRZESTAWIENIA,
    )

    for miara in set(MIARY_PANELU) | set(MIARY_PRZESTAWIENIA):
        assert JEDNOSTKI_MIAR.get(miara), f"{miara}: brak jednostki"


def test_kolumna_liczb_kazdej_karty_deklaruje_miare_i_podpis():
    """Nagłowek kolumny na karcie bierze sie WYLACZNIE z tej mapy, wiec
    nieznana miara dalaby KeyError dopiero przy renderowaniu strony."""
    from modules.reports.analiza_service import (
        JEDNOSTKI_MIAR, KOLUMNY_KART, naglowki_kolumn_kart,
    )

    for karta, (miara, podpis) in KOLUMNY_KART.items():
        assert miara in JEDNOSTKI_MIAR, f"{karta}: miara {miara} bez jednostki"
        assert podpis, f"{karta}: pusty podpis kolumny"
    assert set(naglowki_kolumn_kart()) == set(KOLUMNY_KART)


def test_etykieta_z_jednostka_sklada_nazwe_i_jednostke():
    from modules.reports.analiza_service import etykieta_z_jednostka

    assert etykieta_z_jednostka('netto') == 'Netto\u00a0zł'
    assert etykieta_z_jednostka('objetosc') == 'Objętość\u00a0m³'
    assert etykieta_z_jednostka('cena_za_m3') == 'Cena\u00a0zł/m³'
    # Spacja NIEROZDZIELAJACA — naglowek nie ma sie lamac miedzy nazwa
    # a jednostka.
    assert ' zł' not in etykieta_z_jednostka('netto')


# --- porzadek wlasny wartosci wymiaru ---------------------------------------

def test_porzadek_wlasny_maja_tylko_wymiary_o_naturalnej_kolejnosci():
    """Listy wartosci wymiaru ida domyslnie malejaco po sprzedazy — dla kanalu
    czy opiekuna to trafne. Porzadek WLASNY deklaruja tylko te pola, ktore maja
    kolejnosc niezalezna od obrotu: data (chronologicznie) i grubosc (liczbowo).
    Kazde kolejne dopisanie ma byc swiadoma decyzja, a nie odruchem."""
    from modules.reports.fields import POLA, Porzadek

    z_porzadkiem = {n: p.porzadek for n, p in POLA.items() if p.porzadek is not None}
    assert z_porzadkiem == {
        'date_created': Porzadek.MALEJACO,   # najnowsze na gorze
        'thickness_cm': Porzadek.ROSNACO,    # od najcienszej deski
    }


def test_porzadek_wlasny_dotyczy_wylacznie_wymiarow():
    """Porzadek porzadkuje LISTE WARTOSCI wymiaru. Na polu, ktore wymiarem nie
    jest, nie mialby czego uporzadkowac — i nikt by sie nie dowiedzial, ze
    deklaracja jest martwa."""
    from modules.reports.fields import Pole, Porzadek, Poziom, Zrodlo

    for nazwa, pole in POLA.items():
        if pole.porzadek is not None:
            assert pole.wymiar, nazwa

    with pytest.raises(ValueError, match='porządek własny'):
        Pole('Cos', Poziom.ZAMOWIENIE, Zrodlo.CRM, porzadek=Porzadek.ROSNACO)


def test_kazdy_porzadek_ma_wlasne_zdanie_o_ucieciu_listy():
    """Napis o ucietej liscie mowi, CZEGO brakuje, wiec jest inny dla kazdego
    porzadku. Nowa wartosc `Porzadek` bez wlasnego zdania dalaby KeyError
    dopiero wtedy, gdy uzytkownik przekroczy limit wartosci."""
    from modules.reports.analiza_service import _OPISY_UCIECIA, LIMIT_WARTOSCI_FILTRA
    from modules.reports.fields import Porzadek

    assert set(_OPISY_UCIECIA) == {None} | set(Porzadek)
    for zdanie in _OPISY_UCIECIA.values():
        # Kazde zdanie mowi ILE pokazano i ILE zostalo poza lista.
        assert '{ile}' in zdanie and '{reszta}' in zdanie
        assert zdanie.format(ile=LIMIT_WARTOSCI_FILTRA, reszta=7)


# --- karty kubelkowe: wlasna, wezsza lista wymiarow -------------------------

def test_wymiary_kart_kubelkowych_sa_nazwami_z_rejestru():
    """Lista opcji selektora nie jest wpisana w HTML — powstaje z rejestru pol
    i przechodzi przez `wymiary_proste()`, wiec nazwa, ktora z rejestru
    wypadla, po prostu znika z listy zamiast rozsypywac zapytanie."""
    from modules.reports.analiza_service import (
        KARTY_KUBELKOWE, wymiary_karty_kubelkowej,
    )
    from modules.reports.fields import POLA, wymiary_proste

    proste = set(wymiary_proste())
    for klucz, opis in KARTY_KUBELKOWE.items():
        for nazwa in opis['wymiary']:
            assert nazwa in proste, '{}: {} nie jest prostym wymiarem'.format(klucz, nazwa)
        pozycje = wymiary_karty_kubelkowej(klucz)
        # Pierwsza pozycja to pseudo-wymiar domyslny — NIE jest polem rejestru
        # i nie ma nim byc (kubelkowanie liczone w locie nie ma wlasnej kolumny).
        assert pozycje[0]['nazwa'] == opis['domyslny']
        assert opis['domyslny'] not in POLA
        for pozycja in pozycje[1:]:
            assert pozycja['etykieta'] == POLA[pozycja['nazwa']].etykieta


def test_karta_naleznosci_grupuje_wylacznie_po_kolumnach_zamowienia():
    """Saldo zyje na zamowieniu. Wymiar pozycji pomnozylby je przez liczbe
    pozycji — regresja bledu 7,58x z produkcji."""
    from modules.reports.analiza_service import WYMIARY_NALEZNOSCI
    from modules.reports.fields import POLA, Poziom

    for nazwa in WYMIARY_NALEZNOSCI:
        assert POLA[nazwa].poziom is Poziom.ZAMOWIENIE, nazwa


def test_naglowek_karty_kubelkowej_mowi_netto_w_kazdym_wymiarze():
    """Od partii E (punkt E2) karta klientow to kolo udzialu w WARTOSCI
    w kazdym wymiarze: kubelki niosa netto z calej historii, przekroj po
    wymiarze — netto okresu. Kolumna kwoty nazywa sie wiec zawsze „Netto",
    jak na kazdej innej karcie netto (ta sama etykieta znaczy wszedzie to
    samo). Karta naleznosci ma w obu trybach te sama miare, wiec jej podpis
    tez sie NIE zmienia."""
    from modules.reports.analiza_service import (
        KARTY_KUBELKOWE, naglowek_karty_kubelkowej,
    )

    domyslny_klientow = KARTY_KUBELKOWE['klienci']['domyslny']
    netto = {'podpis': 'Netto', 'jednostka': 'zł', 'miara': 'netto'}
    assert naglowek_karty_kubelkowej('klienci', domyslny_klientow) == netto
    assert naglowek_karty_kubelkowej('klienci', 'caretaker') == netto

    domyslny_naleznosci = KARTY_KUBELKOWE['naleznosci']['domyslny']
    assert naglowek_karty_kubelkowej('naleznosci', domyslny_naleznosci) == \
        naglowek_karty_kubelkowej('naleznosci', 'caretaker')
