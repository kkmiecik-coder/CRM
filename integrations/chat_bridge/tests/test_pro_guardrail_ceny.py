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
