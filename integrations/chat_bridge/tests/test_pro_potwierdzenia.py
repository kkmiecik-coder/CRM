# -*- coding: utf-8 -*-
"""
Bramka potwierdzenia — inwariant I2.

Rozmowa #2016 z audytu: klient zmienił grubość z 10 na 6 cm, bot wysłał podsumowanie,
klient odpowiedział „Tak" — a w CRM wylądowała wycena blatu 10 cm na 7 261,92 zł zamiast
4 681,87 zł. Samo istnienie potwierdzenia nie wystarcza; musi być PRZYPIĘTE DO TREŚCI.
Dlatego potwierdzamy podpis pozycji, a nie flagę boolowską.
"""
import pytest

from bots_pro import potwierdzenia as p
from bots_pro import stan

stan.init_pro()


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


class TestPodpisPolaCenotworcze:
    """Runda poprawek 1, K3: kazde z tych pol zmienia wynik kalkulatora (gatunek/
    technologia/klasa -> wariant drewna, wykonczenie -> typ wykonczenia). Pominiecie
    ktoregos w _POLA_ISTOTNE oznacza "zmiana tego pola NIE uniewaznia potwierdzenia"
    — dokladnie ta klasa bledu, przed ktora ma chronic I2 (#2016 to byla zmiana
    grubosci; to samo grozi przy zmianie gatunku/technologii/klasy/wykonczenia)."""

    @pytest.mark.parametrize("pole,a,b", [
        ("gatunek", "Dąb", "Jesion"),
        ("technologia", "Lity", "Mikrowczep"),
        ("klasa", "A/B", "B/B"),
        ("wykonczenie", "olejowane", "surowe"),
    ])
    def test_zmiana_pola_cenotworczego_zmienia_podpis(self, pole, a, b):
        baza = _pozycje()[0]
        poz_a = [dict(baza, **{pole: a})]
        poz_b = [dict(baza, **{pole: b})]
        assert p.podpis(poz_a) != p.podpis(poz_b)


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


class TestCytatOdmowaINegacja:
    """Runda poprawek 1, K1: gole `fragment in tekst` przepuszczalo cytat wylowiony
    z ODMOWY klienta ("potwierdzam" wewnatrz "nie potwierdzam...") albo ze srodka
    innego slowa ("tak" wewnatrz "taka"/"kontakt"). Kazda z tych piatek MUSI
    zwracac False, mimo ze fragment doslownie wystepuje w tekscie."""

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("tak", "Nie, taka grubość mi nie pasuje"),
        ("zgadzam się", "nie zgadzam się na tę cenę"),
        ("potwierdzam", "nie potwierdzam, prosze o korekte"),
        ("tak", "kontakt: jan@example.com"),
        (".", "Ile to kosztuje."),
    ])
    def test_cytat_z_odmowy_lub_wewnatrz_innego_slowa_odrzucony(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("tak, zgadza się", "Tak, zgadza się — proszę o wycenę"),
        ("potwierdzam", "Potwierdzam, wszystko ok"),
        ("tak", "tak"),
    ])
    def test_prawdziwe_potwierdzenie_nadal_przechodzi(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True


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


def _zapisz_pozycje_i_oczekiwany_podpis(conv_id, grubosc=4):
    """Symuluje to, co robi podsumowanie.wyslij() (bez liczenia ceny/wysylki):
    zapisuje pozycje przez stan.zapisz_pozycje (realny sklad danych, wlacznie
    z rozlozeniem selected_variant) i zapisuje oczekiwany_podpis tych pozycji."""
    stan.ustaw_kontekst(conv_id)
    stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                        grubosc_cm=grubosc, ilosc=1, selected_variant="dab-lity-ab",
                        wykonczenie="surowe")
    oczekiwany = p.podpis(stan.pozycje())
    stan.zapisz_stan(oczekiwany_podpis=oczekiwany)
    return oczekiwany


class TestPotwierdzFunkcja:
    """Runda poprawek 1, W3: potwierdz() mialo zerowe pokrycie testami — jedyna
    funkcja egzekwujaca regule cytatu i zapisujaca wiersz potwierdzenia. W1:
    potwierdz() musi porownywac biezace pozycje z oczekiwany_podpis (co klient
    FAKTYCZNIE widzial w podsumowaniu), nie tylko podpisywac to, co jest w bazie
    W CHWILI wolania — inaczej zmiana danych miedzy podsumowaniem a "Tak" klienta
    przeszlaby niezauwazona (druga strona inwariantu I2, obok sprawdz_bramke)."""

    def test_odrzuca_cytat_ktorego_nie_bylo(self, monkeypatch):
        conv_id = 96001
        _zapisz_pozycje_i_oczekiwany_podpis(conv_id)
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta",
                            lambda: "a ile kosztuje dostawa?")
        wynik = p.potwierdz("tak, potwierdzam")
        assert wynik["ok"] is False
        assert wynik["error"] == "CYTAT_SPOZA_WIADOMOSCI"

    def test_przyjmuje_prawdziwy_cytat_i_zapisuje_podpis(self, monkeypatch):
        conv_id = 96002
        oczekiwany = _zapisz_pozycje_i_oczekiwany_podpis(conv_id)
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: "Tak, zgadzam się")
        wynik = p.potwierdz("tak, zgadzam się")
        assert wynik == {"ok": True, "podpis": oczekiwany}
        # Po potwierdz() bramka (druga strona I2) tez ma przepuszczac — bez zmian danych.
        assert p.sprawdz_bramke()["ok"] is True

    def test_odrzuca_gdy_dane_zmienily_sie_od_podsumowania(self, monkeypatch):
        # W1, dokladnie sekwencja z przypadku #2016: podsumowanie z gruboscia 10,
        # dane zmienione PRZED potwierdzeniem (bez nowego podsumowania) -> potwierdz()
        # nie moze podpisac danych, ktorych klient nigdy nie widzial.
        conv_id = 96003
        _zapisz_pozycje_i_oczekiwany_podpis(conv_id, grubosc=10)
        stan.zapisz_pozycje("1", grubosc_cm=6)
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: "Tak")
        wynik = p.potwierdz("Tak")
        assert wynik["ok"] is False
        assert wynik["error"] == "DANE_ZMIENIONE_OD_PODSUMOWANIA"

    def test_odrzuca_gdy_nigdy_nie_wyslano_podsumowania(self, monkeypatch):
        conv_id = 96004
        stan.ustaw_kontekst(conv_id)
        stan.zapisz_pozycje("1", produkt="blat", selected_variant="dab-lity-ab")
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: "Tak")
        wynik = p.potwierdz("Tak")
        assert wynik["ok"] is False
        assert wynik["error"] == "DANE_ZMIENIONE_OD_PODSUMOWANIA"
