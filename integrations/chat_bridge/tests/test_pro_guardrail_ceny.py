# -*- coding: utf-8 -*-
"""
Guardrail integralności ceny.

Audyt 117 rozmów: w 8 rozmowach wycena zapisana w CRM miała inną kwotę niż ta,
którą bot podał klientowi (rekord: bot mówi 1 936,71 zł, w CRM leży 1 268,97 zł).
Guardrail nie pozwala wysłać kwoty, która nie wyszła z kalkulatora.
"""
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
