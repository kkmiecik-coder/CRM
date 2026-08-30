# -*- coding: utf-8 -*-
"""
Bramka potwierdzenia — inwariant I2.

Rozmowa #2016 z audytu: klient zmienił grubość z 10 na 6 cm, bot wysłał podsumowanie,
klient odpowiedział „Tak" — a w CRM wylądowała wycena blatu 10 cm na 7 261,92 zł zamiast
4 681,87 zł. Samo istnienie potwierdzenia nie wystarcza; musi być PRZYPIĘTE DO TREŚCI.
Dlatego potwierdzamy podpis pozycji, a nie flagę boolowską.
"""
from bots_pro import potwierdzenia as p


def _pozycje(grubosc=4):
    return [{"id": "1", "produkt": "blat", "dlugosc": 180, "szerokosc": 60,
             "grubosc": grubosc, "ilosc": 1, "selected_variant": "dab-lity-ab",
             "finishing_id": 3, "edges": []}]


class TestPodpis:
    def test_te_same_pozycje_daja_ten_sam_podpis(self):
        assert p.podpis(_pozycje()) == p.podpis(_pozycje())

    def test_zmiana_grubosci_zmienia_podpis(self):
        assert p.podpis(_pozycje(grubosc=4)) != p.podpis(_pozycje(grubosc=6))

    def test_kolejnosc_pozycji_nie_wplywa_na_podpis(self):
        a = [{"id": "1", "produkt": "blat"}, {"id": "2", "produkt": "parapet"}]
        b = [{"id": "2", "produkt": "parapet"}, {"id": "1", "produkt": "blat"}]
        assert p.podpis(a) == p.podpis(b)

    def test_pola_nieistotne_nie_wplywaja_na_podpis(self):
        # Notatki robocze bota nie moga uniewazniac zgody klienta.
        a = _pozycje()
        b = _pozycje()
        b[0]["_notatka_bota"] = "cokolwiek"
        assert p.podpis(a) == p.podpis(b)


class TestCytat:
    def test_cytat_z_ostatniej_wiadomosci_przechodzi(self):
        wynik = p.sprawdz_cytat("tak, zgadza się", "Tak, zgadza się — proszę o wycenę")
        assert wynik is True

    def test_cytat_spoza_wiadomosci_odrzucony(self):
        # Model NIE MOZE wymyslic zgody, ktorej nie bylo.
        assert p.sprawdz_cytat("tak, potwierdzam", "a ile kosztuje dostawa?") is False

    def test_wielkosc_liter_i_spacje_tolerowane(self):
        assert p.sprawdz_cytat("  TAK  ", "tak") is True

    def test_pusty_cytat_odrzucony(self):
        assert p.sprawdz_cytat("", "tak") is False


class TestBramka:
    def test_brak_potwierdzenia_blokuje(self, monkeypatch):
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (None, None))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje())
        wynik = p.sprawdz_bramke()
        assert wynik["ok"] is False
        assert wynik["error"] == "BRAK_POTWIERDZENIA"

    def test_potwierdzenie_zgodne_przepuszcza(self, monkeypatch):
        podpis = p.podpis(_pozycje())
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (podpis, "tak"))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje())
        assert p.sprawdz_bramke()["ok"] is True

    def test_zmiana_po_potwierdzeniu_uniewaznia(self, monkeypatch):
        # DOKLADNIE przypadek #2016.
        podpis_stary = p.podpis(_pozycje(grubosc=10))
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (podpis_stary, "Tak"))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje(grubosc=6))
        wynik = p.sprawdz_bramke()
        assert wynik["ok"] is False
        assert wynik["error"] == "POTWIERDZENIE_NIEAKTUALNE"
