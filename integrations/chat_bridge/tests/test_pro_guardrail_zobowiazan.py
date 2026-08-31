# -*- coding: utf-8 -*-
"""
Guardrail G3 — zakazane zobowiązania.

Do tej pory guardrail wyjściowy chronił WYŁĄCZNIE kwoty (G1, integralność ceny).
Twarde fakty, których firma nie może obiecać — „wytrzyma", „gwarantujemy",
„nie ugnie się", „mamy atest" — mogły wyjść do klienta w dowolnej postaci,
bo żaden mechanizm ich nie oglądał. Prompt (sekcja KONSTRUKCJA, N10) mówi
modelowi, żeby tego nie robił, ale prompt jest prośbą, nie bramką: dokładnie
ta sama różnica, dla której powstał G1 mimo reguły CENY w prompcie.

G3 nie ma rundy korekty (w odróżnieniu od G1). „Napisz to jeszcze raz bez
obietnicy" prowadziłoby do odpowiedzi, która mówi to samo innymi słowami —
a pytanie, które taką obietnicę wywołało, i tak należy do człowieka.
"""
from bots_pro import guardraile


class TestZnajdzZakazaneZobowiazania:
    def test_czysta_odpowiedz_nie_jest_naruszeniem(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Blat dębowy lity A/B, 180x60x4 cm, 1 szt. Cena 843,04 zł brutto.") == []

    def test_pusty_tekst_nie_wywala_sie(self):
        assert guardraile.znajdz_zakazane_zobowiazania("") == []
        assert guardraile.znajdz_zakazane_zobowiazania(None) == []

    def test_obietnica_gwarancji(self):
        assert guardraile.znajdz_zakazane_zobowiazania("Gwarantujemy, że będzie idealny.")

    def test_orzeczenie_o_nosnosci(self):
        assert guardraile.znajdz_zakazane_zobowiazania("Ten blat wytrzyma 200 kg.")
        assert guardraile.znajdz_zakazane_zobowiazania("Blaty wytrzymają obciążenie.")
        assert guardraile.znajdz_zakazane_zobowiazania("Udźwignie zlew podblatowy.")

    def test_orzeczenie_o_ugieciu_i_odksztalceniu(self):
        assert guardraile.znajdz_zakazane_zobowiazania("Przy 4 cm nie ugnie się.")
        assert guardraile.znajdz_zakazane_zobowiazania("W wilgoci nie odkształci się.")

    def test_orzeczenie_o_uzytku_zewnetrznym_i_bezpieczenstwie(self):
        assert guardraile.znajdz_zakazane_zobowiazania("Dąb nadaje się na zewnątrz.")
        assert guardraile.znajdz_zakazane_zobowiazania("Ten olej jest bezpieczny dla dzieci.")

    def test_certyfikat_i_atest(self):
        assert guardraile.znajdz_zakazane_zobowiazania("Mamy certyfikat na te blaty.")
        assert guardraile.znajdz_zakazane_zobowiazania("Blaty mają atest higieniczny.")

    def test_dziala_bez_diakrytykow(self):
        # Kanały marketplace potrafią rozebrać polskie znaki (patrz sanitize.py);
        # guardrail ma widzieć obietnicę także po takim przejściu.
        assert guardraile.znajdz_zakazane_zobowiazania("Udzwignie zlew podblatowy.")
        assert guardraile.znajdz_zakazane_zobowiazania("Nie ugnie sie przy tej grubosci.")

    def test_wielkosc_liter_nie_ma_znaczenia(self):
        assert guardraile.znajdz_zakazane_zobowiazania("GWARANTUJEMY trwałość.")

    def test_zwraca_KTORE_zwroty_naruszyly(self):
        # Powód handoffu trafia do prywatnej notatki konsultanta — ma powiedzieć,
        # CO bot obiecał, nie tylko że coś obiecał.
        wynik = guardraile.znajdz_zakazane_zobowiazania(
            "Gwarantujemy, że blat wytrzyma obciążenie.")
        assert set(wynik) == {"gwarantujemy", "wytrzyma"}

    def test_slowo_z_tym_samym_rdzeniem_nie_jest_obietnica(self):
        # „wytrzymałość" to RZECZOWNIK — pada w zdaniu, którym bot poprawnie
        # ODMAWIA orzekania („o wytrzymałość pytamy konsultanta"). Gdyby
        # wpadał w regex, guardrail karałby dokładnie to zachowanie, które
        # sekcja KONSTRUKCJA promptu każe modelowi wybrać.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Pytanie o wytrzymałość przekazuję konsultantowi.") == []

    def test_zamknieta_lista_nie_rosnie_po_cichu(self):
        # Każdy dopisany zwrot to nowa klasa fałszywych alarmów, a fałszywy
        # alarm G3 kosztuje CAŁĄ rozmowę (handoff bez rundy korekty). Zmiana
        # tej listy ma być świadoma, nie odruchowa.
        assert len(guardraile.ZAKAZANE_ZOBOWIAZANIA) == 9
