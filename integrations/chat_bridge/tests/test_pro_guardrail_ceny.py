# -*- coding: utf-8 -*-
"""
Guardrail integralności ceny.

Audyt 117 rozmów: w 8 rozmowach wycena zapisana w CRM miała inną kwotę niż ta,
którą bot podał klientowi (rekord: bot mówi 1 936,71 zł, w CRM leży 1 268,97 zł).
Guardrail nie pozwala wysłać kwoty, która nie wyszła z kalkulatora.
"""
import pytest

from bots_pro import guardraile as g


class TestZnajdzKwoty:
    def test_kwota_z_przecinkiem_i_zlotowkami(self):
        assert g.znajdz_kwoty("Razem 1 936,71 zł") == {"1936.71"}

    def test_kwota_z_kropka(self):
        assert g.znajdz_kwoty("Razem 1936.71 PLN") == {"1936.71"}

    def test_spacja_jako_separator_tysiecy(self):
        assert g.znajdz_kwoty("12 345,00 zł") == {"12345.00"}

    def test_kilka_kwot_w_jednym_zdaniu(self):
        wynik = g.znajdz_kwoty("Blat 843,04 zł, wysyłka 123,00 zł")
        assert wynik == {"843.04", "123.00"}

    def test_wymiary_nie_sa_kwotami(self):
        # 120x60x4 cm nie moze wygladac jak cena.
        assert g.znajdz_kwoty("Blat 120x60x4 cm, 3 sztuki") == set()

    def test_liczba_bez_waluty_nie_jest_kwota(self):
        assert g.znajdz_kwoty("Termin to 14 dni") == set()


class TestSprawdzCeny:
    def test_kwota_z_kalkulatora_przechodzi(self):
        assert g.sprawdz_ceny("Razem 843,04 zł", {"843.04"}) == []

    def test_kwota_spoza_kalkulatora_jest_zgloszona(self):
        naruszenia = g.sprawdz_ceny("Razem 1 936,71 zł", {"1268.97"})
        assert naruszenia == ["1936.71"]

    def test_brak_kwot_w_tekscie_przechodzi(self):
        assert g.sprawdz_ceny("Jakiego wykończenia sobie Pan życzy?", set()) == []

    def test_zaokraglenie_do_pelnych_zlotych_przechodzi(self):
        # Bot bywa proszony o "w przyblizeniu" — 843,04 -> "okolo 843 zl".
        assert g.sprawdz_ceny("około 843 zł", {"843.04"}) == []

    def test_kilka_naruszen_zwracanych_razem(self):
        naruszenia = g.sprawdz_ceny("100,00 zł oraz 200,00 zł", {"300.00"})
        assert sorted(naruszenia) == ["100.00", "200.00"]


class TestSeparatoryTysiecyIFormyWaluty:
    """Runda poprawek 1, K4+K5: audytowy cytat "1 936,71 zł" w prawdziwych rozmowach
    bywa zapisany spacją NIEROZDZIELAJĄCĄ (NBSP), nie zwykłą — oryginalny regex
    (dwa identyczne znaki 0x20 w klasie znaków) jej nie łapał, więc "1 " odpadało
    z liczby: kwota wychodziła jako "936.71" zamiast "1936.71". Podwójna awaria —
    prawdziwa kwota zgłoszona jako naruszenie, a halucynacja porównana z niewłaściwą
    liczbą. K5: waluta pisana zwykłą polszczyzną ("złotych", wielkie litery, PLN
    przed liczbą) w ogóle nie była rozpoznawana — zmyślona kwota przechodziła bez
    śladu."""

    def test_nbsp_jako_separator_tysiecy(self):
        assert g.znajdz_kwoty("Razem 1 936,71 zł") == {"1936.71"}

    def test_waska_spacja_nierozdzielajaca_jako_separator_tysiecy(self):
        assert g.znajdz_kwoty("Razem 1 936,71 zł") == {"1936.71"}

    def test_kropka_jako_separator_tysiecy(self):
        assert g.znajdz_kwoty("1.936,71 zł") == {"1936.71"}

    def test_nbsp_nie_generuje_falszywego_naruszenia_w_sprawdz_ceny(self):
        # Prawdziwa kwota z NBSP musi zniknąć z naruszeń, gdy jest w rejestrze kalkulatora —
        # przy starym regexie zostałaby zgłoszona jako "936.71" (spoza rejestru "1936.71").
        assert g.sprawdz_ceny("Razem 1 936,71 zł", {"1936.71"}) == []

    def test_waluta_zlotych_z_ogonkami(self):
        assert g.znajdz_kwoty("Razem 9999,99 złotych") == {"9999.99"}

    def test_waluta_zlotych_bez_ogonkow(self):
        assert g.znajdz_kwoty("Razem 9999,99 zlotych") == {"9999.99"}

    def test_waluta_wielkimi_literami(self):
        assert g.znajdz_kwoty("1936,71 ZŁ") == {"1936.71"}

    def test_waluta_pierwsza_litera_wielka(self):
        assert g.znajdz_kwoty("1936,71 Zł") == {"1936.71"}

    def test_waluta_pln_przed_liczba(self):
        assert g.znajdz_kwoty("PLN 1936,71") == {"1936.71"}

    def test_zmyslona_kwota_zlotych_nie_przechodzi_bez_sladu(self):
        # K5 dokladnie: przed poprawka to zwracalo [] (regex w ogole nie widzial kwoty).
        assert g.sprawdz_ceny("Razem 9999,99 złotych", set()) == ["9999.99"]


class TestOdstepNiePrzechodziPrzezNowaLinie:
    """Runda poprawek 2, N1: naprawa K4 (spacja->separator tysiecy) uzyla \\s* jako
    odstepu miedzy waluta a liczba, a \\s LAPIE TEZ znak nowej linii. Efekt: waluta
    z konca jednej linii doklejala sie do przypadkowej liczby z POCZATKU nastepnej
    — a wypunktowana, wielolinijkowa wycena to normalny ksztalt odpowiedzi bota, nie
    brzeg. Kierunek byl bezpieczny (falszywe naruszenie na PRAWDZIWEJ kwocie), ale
    w docelowym podpieciu to wywracaloby prawie kazda wycene z >1 pozycja."""

    def test_waluta_na_koncu_linii_nie_lapie_liczby_z_nastepnej(self):
        tekst = "Razem 1 000,00 zł\n3 dni robocze na realizację"
        assert g.znajdz_kwoty(tekst) == {"1000.00"}

    def test_dwukropek_przed_waluta_i_liczba_z_nastepnej_linii(self):
        tekst = "Blat: 843,04 zł\n2 sztuki parapetu policzę osobno"
        assert g.znajdz_kwoty(tekst) == {"843.04"}

    def test_waluta_bez_liczby_nie_lapie_wymiarow_z_nastepnej_linii(self):
        # "Koszt w zł" to samo w sobie nie jest kwota — "zł" nie ma tu przy sobie
        # liczby w OGOLE, a stary regex i tak doklejal "180" z linii nizej.
        tekst = "Koszt w zł\n180x60x4 cm"
        assert g.znajdz_kwoty(tekst) == set()

    def test_sprawdz_ceny_nie_zglasza_falszywego_naruszenia_przez_nowa_linie(self):
        tekst = "Razem 1 000,00 zł\n3 dni robocze na realizację"
        assert g.sprawdz_ceny(tekst, {"1000.00"}) == []


class TestWalutaOddzielonaDwukropkiem:
    """Runda poprawek 2, N3: waluta oddzielona od liczby dwukropkiem+spacja
    ("Cena w zł: 9999,99") nie byla w ogole widziana — zmyslona kwota w takim
    zapisie przechodzila guardrail bez sladu (ten sam falszywy negatyw co
    pierwotne K5). Naprawa NIE moze psuc N1 — dwukropek tak, nowa linia nie
    (patrz TestOdstepNiePrzechodziPrzezNowaLinie wyzej)."""

    def test_dwukropek_i_spacja_miedzy_waluta_a_liczba(self):
        assert g.znajdz_kwoty("Cena w zł: 9999,99") == {"9999.99"}

    def test_zmyslona_kwota_po_dwukropku_nie_przechodzi_bez_sladu(self):
        assert g.sprawdz_ceny("Cena w zł: 9999,99", set()) == ["9999.99"]


class TestGolaKwotaPrzySlowieCenowym:
    """U8 (recenzja koncowa): waluta byla w regexie OBOWIAZKOWA, wiec najczestsza
    forma halucynacji z audytu — "okolo X brutto", "razem jakies Y" — przechodzila
    zupelnie niezauwazona. Naprawa jest WASKA: gola liczba liczy sie jako kwota
    tylko powyzej progu i tylko w bezposrednim sasiedztwie slowa cenowego."""

    def test_sonda_p3_z_recenzji_lapie_obie_zmyslone_liczby(self):
        tekst = ("Blat kosztuje 1 936,71 zł netto, czyli około 2400 brutto. "
                 "Z wysyłką wyjdzie razem jakieś 2650.")
        assert sorted(g.sprawdz_ceny(tekst, {"1936.71"})) == ["2400.00", "2650.00"]

    @pytest.mark.parametrize("tekst,oczekiwana", [
        ("Razem 2400 brutto", "2400.00"),
        ("Cena to 2400", "2400.00"),
        ("Koszt wynosi 2400", "2400.00"),
        ("Łącznie jakieś 2400", "2400.00"),
        ("Dopłata około 350", "350.00"),
        ("2400 netto", "2400.00"),
    ])
    def test_gola_liczba_przy_slowie_cenowym_jest_naruszeniem(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, set()) == [oczekiwana]

    @pytest.mark.parametrize("tekst", [
        # Wymiary — najczestszy falszywy alarm, gdyby lapac kazda gola liczbe.
        "Blat 180x60x4 cm",
        "Razem 240 cm długości",
        "Łącznie 150 cm szerokości",
        # Sztuki, terminy, kontakt, lata.
        "Razem 12 sztuk",
        "Termin to 14 dni",
        "Cena obowiązuje do 2026 roku",
        "Proszę o kontakt: 500 123 456",
        # Liczba ponizej progu tuz przy slowie cenowym — to policzalna rzecz,
        # nie kwota (bot pisze "razem 3 pozycje" czesciej niz "razem 3 zl").
        "Razem 3 pozycje",
    ])
    def test_liczby_niebedace_cenami_nie_sa_zglaszane(self, tekst):
        assert g.sprawdz_ceny(tekst, set()) == []

    def test_prawdziwa_kwota_bez_waluty_nadal_przechodzi(self):
        # Kontrola negatywna: kwota Z REJESTRU wypowiedziana bez "zl" to nie
        # halucynacja — falszywy alarm kosztuje tu tyle samo co przepuszczenie.
        assert g.sprawdz_ceny("Razem 843,04 brutto", {"843.04"}) == []

    def test_zaokraglona_kwota_z_rejestru_bez_waluty_przechodzi(self):
        assert g.sprawdz_ceny("Razem około 843 brutto", {"843.04"}) == []


class TestProgGolejKwoty:
    """R2 (recenzja końcowa, runda 2): próg 100 zł był wybrany „z palca" i
    przepuszczał zmyślone kwoty poniżej — a w cenniku WoodPower są realne
    pozycje w tym przedziale (opcja wycięcia w blacie: 81,30 zł). Próg to 50 zł:
    niżej niż najtańsza realna pozycja cennika, wyżej niż liczebniki, którymi
    bot się posługuje."""

    def test_prog_wynosi_50(self):
        assert g._PROG_GOLEJ_KWOTY == 50.0

    @pytest.mark.parametrize("tekst,oczekiwana", [
        # Sonda z recenzji: przy progu 100 ta zmyslona doplata przechodzila.
        ("Dopłata 90", "90.00"),
        # Realna pozycja cennika (wyciecie w blacie 81,30 zl) — zmyslona przez
        # model kwota w tym przedziale wyglada wiarygodnie, wiec musi byc lapana.
        ("Opcja wycięcia kosztuje 81,30", "81.30"),
        ("Razem 55 brutto", "55.00"),
    ])
    def test_przedzial_50_100_jest_teraz_lapany(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, set()) == [oczekiwana]

    @pytest.mark.parametrize("tekst", [
        # WYMIARY — liczby 50-100 sa tu najczestsze ze wszystkich (szerokosc
        # blatu, grubosc, dlugosc parapetu), wiec to najwazniejszy test progu.
        "Blat 90x60x4 cm",
        "Razem 90 cm długości",
        "Łącznie 80 cm szerokości",
        "Szerokość maksymalnie 90 cm",
        # ILOSCI.
        "Razem 60 sztuk",
        "Łącznie 75 szt.",
        # DNI (terminy realizacji).
        "Termin to 60 dni",
        "Razem 90 dni roboczych",
        # NUMERY TELEFONU — polski numer zapisany grupami ("500 123 456") jest
        # dla regexu JEDNA liczba grupowana, wiec prog go nie dotyczy w ogole;
        # liczy sie brak slowa cenowego w sasiedztwie.
        "Proszę o kontakt: 500 123 456",
        "Numer telefonu to 600 700 800",
        "Zostawiam numer 89 123 45 67",
        # Rok i liczebnik ponizej progu — kontrola, ze nic sie nie zmienilo.
        "Cena obowiązuje do 2026 roku",
        "Razem 3 pozycje",
    ])
    def test_prog_50_nie_lapie_wymiarow_ilosci_dni_ani_telefonow(self, tekst):
        assert g.sprawdz_ceny(tekst, set()) == []

    def test_ponizej_progu_nadal_przechodzi_swiadomie(self):
        # Udokumentowana granica mechanizmu: gola liczba ponizej 50 zl przy slowie
        # cenowym nadal nie jest naruszeniem. To swiadomy kompromis — ponizej tego
        # progu liczebniki ("razem 12 sztuk", "3 pozycje") sa czestsze niz kwoty.
        assert g.sprawdz_ceny("Dopłata 40", set()) == []
