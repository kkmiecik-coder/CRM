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


class TestPodpisObejmujeDostawe:
    """U4 (recenzja koncowa): koszt dostawy byl CALKOWICIE poza podpisem — klient
    potwierdzal wylacznie cene produktu, a zmiana kodu pocztowego (a wiec i ceny
    kuriera) NIE uniewazniala potwierdzenia. Wymog wlasciciela mowi wprost: cena
    z CRM to produkt + ew. dostawa, i klient ma potwierdzic calosc."""

    def _dostawa(self, **nadpisz):
        baza = {"kod_pocztowy": "00-001", "kurier": "DPD",
                "netto": 200.0, "brutto": 246.0}
        baza.update(nadpisz)
        return baza

    def test_ta_sama_dostawa_daje_ten_sam_podpis(self):
        assert p.podpis(_pozycje(), self._dostawa()) == p.podpis(_pozycje(), self._dostawa())

    def test_brak_dostawy_i_dostawa_daja_rozne_podpisy(self):
        assert p.podpis(_pozycje()) != p.podpis(_pozycje(), self._dostawa())

    @pytest.mark.parametrize("pole,wartosc", [
        ("kod_pocztowy", "80-001"),
        ("kurier", "InPost"),
        ("netto", 300.0),
        ("brutto", 369.0),
    ])
    def test_zmiana_pola_dostawy_zmienia_podpis(self, pole, wartosc):
        assert p.podpis(_pozycje(), self._dostawa()) != p.podpis(
            _pozycje(), self._dostawa(**{pole: wartosc}))


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


class TestNegacjaPrzezInterpunkcje:
    """Runda poprawek 2, N2 (resztka po K1): negacja tuz przed cytatem, ale
    oddzielona przecinkiem/interpunkcja — to DOKLADNIE ten sam atak co K1
    (falszywa zgoda), tylko z przecinkiem w srodku. "nie, tak nie moze byc" ma
    dalej znaczyc odmowe, mimo przecinka miedzy "nie" a "tak".

    Rownoczesnie negacja MUSI zostac slowem BEZPOSREDNIO przed przecinkiem —
    "Nie mam uwag, potwierdzam" to prawdziwa zgoda (negacja "nie" dotyczy "mam
    uwag", innego zdania), wiec NIE moze zostac odrzucona. Inaczej naprawa N2
    zjadlaby prawdziwe zgody w tej (bardzo naturalnej) formie."""

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("tak", "Nie, tak nie może być"),
        ("zgadzam się", "nie, zgadzam się tylko z terminem"),
    ])
    def test_negacja_oddzielona_przecinkiem_nadal_odrzuca(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("potwierdzam", "Nie mam uwag, potwierdzam"),
        ("zgadzam się", "Nie mam pytań, zgadzam się"),
        ("bierzemy", "no dobra, bierzemy"),
        ("zamawiam", "ok, zamawiam"),
    ])
    def test_negacja_dalekiego_zdania_nie_zjada_prawdziwej_zgody(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True


class TestNegacjaWCalejKlauzuli:
    """U5 (recenzja koncowa): bramka negacji patrzyla WYLACZNIE na JEDNO slowo
    bezposrednio przed cytatem, wiec wystarczylo przesunac poczatek cytatu o jedno
    slowo, zeby wyjac ZGODE z ODMOWY ("sie na te cene" z "Nie zgadzam sie na te
    cene"). Negacja obowiazuje w calej KLAUZULI, w ktorej stoi — a jawne wycofanie
    sie ("rezygnuje") uniewaznia CALA wypowiedz, tez gdy stoi PO cytacie."""

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # sonda P1b/P1c z recenzji — cytat przesuniety o jedno/dwa slowa
        ("się na tę cenę", "Nie zgadzam się na tę cenę"),
        ("na tę cenę", "Nie zgadzam się na tę cenę"),
        ("cenę", "Nie zgadzam się na tę cenę"),
        ("pasuje mi ta grubość", "Nie pasuje mi ta grubość"),
        # sonda P1e — odmowa stoi PO cytacie, w kolejnej klauzuli
        ("To za drogo", "To za drogo, rezygnuję"),
        ("wszystko ok", "wszystko ok było wcześniej, ale rezygnuję"),
        ("zgadza się", "cena zgadza się z ofertą, ale anuluję zamówienie"),
    ])
    def test_cytat_wyjety_z_odmowy_odrzucony(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Druga strona: falszywa odmowa kosztuje sprzedaz. Te MUSZA przechodzic.
        ("nie mam uwag", "nie mam uwag"),
        ("nie, wszystko się zgadza", "nie, wszystko się zgadza"),
        ("nie zmieniam nic, potwierdzam", "nie zmieniam nic, potwierdzam"),
        ("potwierdzam", "nie zmieniam nic, potwierdzam"),
        ("zgadza się", "Nie znalazłem żadnych błędów, zgadza się"),
        ("wszystko się zgadza", "Tak, wszystko się zgadza"),
        ("biorę", "cena wyższa niż myślałem, ale biorę"),
    ])
    def test_prawdziwa_zgoda_nadal_przechodzi(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True


class TestBramka:
    def test_brak_potwierdzenia_blokuje(self, monkeypatch):
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (None, None))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje())
        monkeypatch.setattr(p, "_biezaca_dostawa", dict)
        wynik = p.sprawdz_bramke()
        assert wynik["ok"] is False
        assert wynik["error"] == "BRAK_POTWIERDZENIA"

    def test_potwierdzenie_zgodne_przepuszcza(self, monkeypatch):
        podpis = p.podpis(_pozycje())
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (podpis, "tak"))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje())
        monkeypatch.setattr(p, "_biezaca_dostawa", dict)
        assert p.sprawdz_bramke()["ok"] is True

    def test_zmiana_po_potwierdzeniu_uniewaznia(self, monkeypatch):
        # DOKLADNIE przypadek #2016.
        podpis_stary = p.podpis(_pozycje(grubosc=10))
        monkeypatch.setattr(p, "_stan_potwierdzenia", lambda: (podpis_stary, "Tak"))
        monkeypatch.setattr(p, "_biezace_pozycje", lambda: _pozycje(grubosc=6))
        monkeypatch.setattr(p, "_biezaca_dostawa", dict)
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


class TestZgodaPoWiodacymNie:
    """N6 (rerecenzja gałęzi): „nie, wszystko się zgadza" to POTWIERDZENIE —
    klient przeczy poprzedniemu PYTANIU bota („czy coś jeszcze zmieniamy?"),
    nie wycenie. Bramka odrzucała je, gdy model zacytował samą zgodę bez
    wiodącego „nie," — a to najnaturalniejszy wybór cytatu, bo właśnie ta część
    jest potwierdzeniem. Istniejący test pokrywał WYŁĄCZNIE wariant, w którym
    cytat jest całą wiadomością.

    Wyjątek „samotne »nie,« tuż przed cytatem" (N2 z poprzedniej rundy) musi
    przy tym zostać szczelny: odpuszczamy go tylko wtedy, gdy cytat obejmuje
    CAŁĄ klauzulę, klauzula nie ma własnej negacji i jest jawną zgodą."""

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("wszystko się zgadza", "nie, wszystko się zgadza"),
        ("wszystko się zgadza", "Nie, wszystko się zgadza."),
        ("wszystko się zgadza", "Nie, wszystko się zgadza, proszę o link"),
        ("zgadza się", "nie, zgadza się"),
        ("potwierdzam", "nie, potwierdzam"),
        ("wszystko ok", "nie, wszystko ok"),
        ("zamawiam", "nie, zamawiam"),
    ])
    def test_zgoda_po_wiodacym_nie_przechodzi(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Wyjatek z poprzedniej rundy (N2) MUSI dalej odrzucac.
        ("tak", "Nie, tak nie może być"),
        ("zgadzam się", "nie, zgadzam się tylko z terminem"),
        # Cytat obejmuje CALA klauzule, ale klauzula nie jest zgoda.
        ("dziękuję", "nie, dziękuję"),
        ("na razie wstrzymuję się", "nie, na razie wstrzymuję się"),
        # Cytat urwany w polowie klauzuli — negacja go dosiega.
        ("wszystko", "nie, wszystko trzeba przeliczyć od nowa"),
        ("zgadza", "nie, cena się nie zgadza"),
    ])
    def test_odmowa_po_wiodacym_nie_nadal_odrzucona(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False
