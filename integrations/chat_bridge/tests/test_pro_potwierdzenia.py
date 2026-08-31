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
        # („biorę" z „cena wyższa niż myślałem, ALE biorę" stało tu do rundy D.
        # Po D1 spójnik przeciwstawny unieważnia całą wypowiedź, więc ta forma
        # wymaga dopytania — zmierzona cena poprawki, przeniesiona do
        # `TestD1ZgodaCzesciowaNieOtwieraBramki`, żeby koszt był JAWNY.)
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


class TestWiodaceNieZawszeNeguje:
    """Runda D (C1): wiodące „nie," ZAWSZE neguje cytat z następnej klauzuli.

    Poprzednia runda (`96bb162`) dołożyła wyjątek: negację odpuszczano, gdy
    klauzula za „nie," zawierała słowo z listy zgody. Rerecenzja przemyciła przez
    ten wyjątek 15 fałszywych zgód — bo to test typu „worek słów" na klauzuli,
    która bywa CAŁYM zdaniem odmownym, a treść odmowy stoi naturalnie w
    NASTĘPNEJ klauzuli („Nie, dobrze. Proszę poprawić wymiar na 200 cm."). Warunek
    „cytat obejmuje resztę klauzuli" tego nie ratuje. Polszczyzna ma nieskończenie
    wiele form „nie, ale", więc wyjątek został WYCOFANY — świadomie, nie przez
    przeoczenie.

    Znany i ZAAKCEPTOWANY koszt: klient piszący „nie, wszystko się zgadza"
    dostanie prośbę o potwierdzenie jeszcze raz (jedno pytanie). Fałszywa zgoda
    kosztuje zamówienie zapisane wbrew klientowi — te dwa błędy nie ważą tyle
    samo. NIE dokładać tu z powrotem listy słów zgody ani innego wyjątku
    „nie, ale": kierunek bezpieczny to odrzucenie."""

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Sondy rerecenzji rundy C — KAŻDA musi być odrzucona. Cytat jest
        # prawdziwym fragmentem wiadomości, ale klient w niej ODMAWIA.
        ("dobrze", "Nie, dobrze. Prosze poprawic wymiar na 200 cm."),
        ("ok", "Nie, ok. Ale zmienmy grubosc na 6 cm."),
        ("poprawnie ma byc 200 cm", "Nie, poprawnie ma byc 200 cm."),
        ("biore", "Nie, biore. Ale dwa blaty, nie jeden."),
        ("tak", "Nie, tak. Ale dlugosc 200 zamiast 180."),
        ("pasuje", "Nie, pasuje. Tylko wykonczenie na olej."),
        ("zgoda", "Nie, zgoda. Ale bez dostawy, odbior osobisty."),
        ("dobrze", "Nie, dobrze, ale grubosc ma byc 6 cm."),
        ("zamawiam ale w innej grubosci", "Nie, zamawiam ale w innej grubosci."),
        ("dobrze byloby taniej", "Nie, dobrze byloby taniej."),
        ("super drogo", "Nie, super drogo."),
        ("dobrze ze pytacie", "Nie, dobrze ze pytacie. Cena jest za wysoka."),
    ])
    def test_zgoda_przemycona_po_wiodacym_nie_jest_odrzucona(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Te warianty przechodziły po `96bb162`. Po cofnięciu wyjątku są
        # odrzucane — to CENA przywróconego inwariantu, nie usterka: bot
        # dopyta jeszcze raz.
        ("wszystko się zgadza", "nie, wszystko się zgadza"),
        ("wszystko się zgadza", "Nie, wszystko się zgadza."),
        ("wszystko się zgadza", "Nie, wszystko się zgadza, proszę o link"),
        ("zgadza się", "nie, zgadza się"),
        ("potwierdzam", "nie, potwierdzam"),
        ("wszystko ok", "nie, wszystko ok"),
        ("zamawiam", "nie, zamawiam"),
    ])
    def test_zgoda_po_wiodacym_nie_tez_wymaga_dopytania(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        ("tak", "Nie, tak nie może być"),
        ("zgadzam się", "nie, zgadzam się tylko z terminem"),
        ("dziękuję", "nie, dziękuję"),
        ("na razie wstrzymuję się", "nie, na razie wstrzymuję się"),
        ("wszystko", "nie, wszystko trzeba przeliczyć od nowa"),
        ("zgadza", "nie, cena się nie zgadza"),
    ])
    def test_jawna_odmowa_po_wiodacym_nie_nadal_odrzucona(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Kontrola dodatnia: cofnięcie wyjątku NIE może zjeść zwykłych zgód —
        # tu przed cytatem nie stoi samotne „nie,".
        ("tak, zgadzam się", "Tak, zgadzam się"),
        ("wszystko się zgadza", "Wszystko się zgadza, proszę o link"),
        ("potwierdzam", "nie zmieniam nic, potwierdzam"),
    ])
    def test_zwykla_zgoda_nadal_przechodzi(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True

    def test_pelna_sciezka_potwierdz_i_bramka_odrzuca_falszywa_zgode(self, monkeypatch):
        """Sonda rerecenzji w całości, nie sam `sprawdz_cytat`: klient prosi o
        zmianę wymiaru, a do CRM szły pozycje SPRZED zmiany (klasa #2016)."""
        conv_id = 96005
        _zapisz_pozycje_i_oczekiwany_podpis(conv_id)
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta",
                            lambda: "Nie, dobrze. Prosze poprawic wymiar na 200 cm.")
        wynik = p.potwierdz("dobrze")
        assert wynik["ok"] is False
        assert wynik["error"] == "CYTAT_SPOZA_WIADOMOSCI"
        # Bramka nie może się otworzyć — nic nie ma prawa pójść do CRM.
        bramka = p.sprawdz_bramke()
        assert bramka["ok"] is False
        assert bramka["error"] == "BRAK_POTWIERDZENIA"


# --- D1: korpus rerecenzji D (sonda `d1_bramka.py`, sekcja b) -----------------
#
# 34 wypowiedzi, w których klient NIE potwierdza wszystkiego: zgoda CZĘŚCIOWA
# („zgadzam się co do ceny, ale termin nie"), WARUNKOWA („zamawiam pod
# warunkiem, że...") albo prośba o zmianę podana w formie zgody („ok, tylko
# zmieńmy grubość na 6 cm"). Cytat jest ZA KAŻDYM RAZEM dosłownym fragmentem
# wiadomości, więc sama reguła cytatu ich nie odsiewa.
#
# Zapisany bez polskich znaków — dokładnie tak, jak w sondzie rerecenzji, żeby
# liczby w testach niżej były TYMI SAMYMI liczbami co w raporcie.
_D1_KORPUS_ZGODA_CZESCIOWA = [
    ("zgadzam sie co do ceny", "Zgadzam sie co do ceny, ale termin nie."),
    ("zgadzam sie co do ceny", "Zgadzam sie co do ceny. Termin za dlugi."),
    ("ok", "Ok, tylko zmienmy grubosc na 6 cm."),
    ("ok", "Ok. Tylko zmienmy grubosc na 6 cm."),
    ("dobrze", "Dobrze, choc wolalbym dab."),
    ("dobrze", "Dobrze. Choc wolalbym dab zamiast jesionu."),
    ("pasuje", "Pasuje, ale prosze o dluzszy blat."),
    ("wszystko sie zgadza", "Wszystko sie zgadza poza cena."),
    ("wszystko sie zgadza", "Wszystko sie zgadza, poza cena."),
    ("wszystko sie zgadza", "Czy wszystko sie zgadza?"),
    ("zgadza sie", "Nic sie nie zgadza."),
    ("potwierdzam", "Jeszcze nie potwierdzam."),
    ("potwierdzam", "Na razie nie potwierdzam, musze przemyslec."),
    ("biore", "Biore, ale w innej grubosci."),
    ("zamawiam", "Zamawiam pod warunkiem, ze zmienicie termin."),
    ("tak", "Tak, ale najpierw prosze o korekte wymiaru."),
    ("tak", "Tak? A moze jednak inaczej."),
    ("moze byc", "Moze byc, tylko dodajcie fazowanie."),
    ("zgoda", "Zgoda na cene, nie na termin."),
    ("akceptuje", "Akceptuje cene, ale nie akceptuje terminu."),
    ("wszystko ok", "Wszystko ok oprocz wykonczenia."),
    ("dobrze", "No dobrze, ale to za drogo."),
    ("swietnie", "Swietnie, tylko prosze zmienic dlugosc na 200."),
    ("zgadzam sie", "Zgadzam sie tylko czesciowo."),
    ("jest ok", "Cena jest ok, reszta nie."),
    ("potwierdzam", "Potwierdzam odbior wiadomosci, nie zamowienie."),
    ("tak jest", "Tak jest za drogo."),
    ("zgadza sie", "Zgadza sie? Bo mnie cos nie pasuje."),
    ("dobrze", "Dobrze - ale grubosc 6 cm."),
    ("ok", "Ok — tylko zmienmy gatunek."),
    ("zgadzam sie", "Nie do konca sie zgadzam."),
    ("pasuje", "Raczej nie pasuje."),
    ("w porzadku", "W porzadku, ale prosze o rabat."),
    ("niech bedzie", "Niech bedzie, chociaz termin mi nie odpowiada."),
]

# Siedem wypowiedzi z korpusu wyżej, które przechodzą DALEJ — nie niosą
# spójnika przeciwstawnego, a zastrzeżenie jest wyrażone SEMANTYCZNIE (osobne
# zdanie, pytanie, „reszta nie"). To udokumentowana granica mechanizmu opartego
# na dosłownym cytacie, nie luka do zamknięcia kolejnym słowem na liście.
_D1_NADAL_PRZEPUSZCZANE = [
    ("zgadzam sie co do ceny", "Zgadzam sie co do ceny. Termin za dlugi."),
    ("wszystko sie zgadza", "Czy wszystko sie zgadza?"),
    ("zgoda", "Zgoda na cene, nie na termin."),
    ("jest ok", "Cena jest ok, reszta nie."),
    ("potwierdzam", "Potwierdzam odbior wiadomosci, nie zamowienie."),
    ("tak jest", "Tak jest za drogo."),
    ("zgadza sie", "Zgadza sie? Bo mnie cos nie pasuje."),
]

_D1_ODRZUCANE = [x for x in _D1_KORPUS_ZGODA_CZESCIOWA
                 if x not in _D1_NADAL_PRZEPUSZCZANE]

# Kontrola dodatnia rerecenzji: 11 PRAWDZIWYCH zgód. Dziesięć MUSI przechodzić —
# fałszywa odmowa kosztuje rundę rozmowy, ale przy skali „co druga zgoda
# odrzucona" bot przestaje być użyteczny.
_D1_PRAWDZIWE_ZGODY = [
    ("tak, zgadzam sie", "Tak, zgadzam sie"),
    ("wszystko sie zgadza", "Wszystko sie zgadza, prosze o link"),
    ("potwierdzam", "nie zmieniam nic, potwierdzam"),
    ("tak, potwierdzam", "Tak, potwierdzam. Prosze o link do zamowienia."),
    ("wszystko sie zgadza", "Dziekuje, wszystko sie zgadza."),
    ("wszystko sie zgadza", "Wszystko sie zgadza, dziekuje."),
    ("tak, zamawiam", "Tak, zamawiam. Prosze o link."),
    ("potwierdzam", "Potwierdzam, mozemy skladac zamowienie."),
    ("wszystko ok", "Wszystko ok, czekam na link."),
    ("zgadza sie", "Zgadza sie, prosze o fakture na firme."),
]

# Jedenasta — zmierzona CENA poprawki D1, przyjęta świadomie. Druga pozycja to
# ta sama forma, która do rundy D stała w `TestNegacjaWCalejKlauzuli` jako
# kontrola dodatnia; po D1 zmienia stronę i jest tu, żeby koszt był JAWNY.
_D1_UTRACONA_ZGODA = [
    ("biore", "Myslalem ze za drogo, ale biore."),
    ("biorę", "cena wyższa niż myślałem, ale biorę"),
]


class TestD1ZgodaCzesciowaNieOtwieraBramki:
    """D1 (rerecenzja rundy D): bramka przepuszczała zgodę CZĘŚCIOWĄ.

    Klasa błędu jest DOKŁADNIE ta sama co #2016, tylko wejście inne niż w
    rundzie C: klient prosi o zmianę („Ok, tylko zmieńmy grubość na 6 cm."),
    model cytuje z tego „ok", bramka się otwiera i do CRM idzie grubość SPRZED
    prośby. Stan zastany — zachowywało się tak przed rundą D i po niej, żadna
    z czterech rund tej klasy nie dotykała.

    Naprawa: spójniki przeciwstawne i zastrzeżenia („ale", „tylko", „jedynie",
    „choć", „jednak", „natomiast", „lecz", „poza", „oprócz", „z wyjątkiem",
    „pod warunkiem", „za to", „częściowo") unieważniają CAŁĄ wypowiedź —
    tak, jak robi to „rezygnuję", a nie lokalnie w klauzuli. Zmierzone na
    korpusie rerecenzji: fałszywe zgody 29/34 → 7/34, koszt 1 prawdziwa
    zgoda na 11.

    Kierunek jest asymetryczny świadomie: fałszywa zgoda łamie wymóg
    właściciela („zawsze bot musi mieć potwierdzone od klienta, że wszystko
    się zgadza") i zapisuje zamówienie wbrew klientowi; fałszywa odmowa
    kosztuje jedno dodatkowe pytanie. Przy wątpliwości — odmowa."""

    @pytest.mark.parametrize("cytat,wiadomosc", _D1_ODRZUCANE)
    def test_zgoda_czesciowa_jest_odrzucana(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    @pytest.mark.parametrize("cytat,wiadomosc", _D1_NADAL_PRZEPUSZCZANE)
    def test_zastrzezenie_bez_spojnika_przechodzi_swiadomie(self, cytat, wiadomosc):
        """Udokumentowana GRANICA: te siedem nie ma spójnika przeciwstawnego,
        a zastrzeżenie stoi w osobnym zdaniu albo jest pytaniem. Odróżnienie
        ich od zgody wymaga rozumienia zdania, nie kolejnego słowa na liście —
        każde dołożone tutaj wraca fałszywymi odmowami."""
        assert p.sprawdz_cytat(cytat, wiadomosc) is True

    @pytest.mark.parametrize("cytat,wiadomosc", _D1_PRAWDZIWE_ZGODY)
    def test_prawdziwa_zgoda_nadal_przechodzi(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True

    @pytest.mark.parametrize("cytat,wiadomosc", _D1_UTRACONA_ZGODA)
    def test_zgoda_ze_spojnikiem_przeciwstawnym_wymaga_dopytania(self, cytat, wiadomosc):
        """CENA poprawki: „myślałem, że za drogo, ALE biorę" to prawdziwa
        zgoda, a mimo to zostanie odrzucona — bot dopyta jeszcze raz. Jedna
        taka forma na 11 kontrolnych, w zamian za 22 zamknięte fałszywe zgody.
        Gdyby produkcja pokazała, że ta forma jest częsta, granicę trzeba
        przesunąć POMIAREM, nie wyjątkiem na „ale" — wyjątek na worku słów
        został już raz cofnięty w rundzie D (C1)."""
        assert p.sprawdz_cytat(cytat, wiadomosc) is False

    def test_pomiar_na_calym_korpusie_rerecenzji(self):
        """Pomiar recenzenta odtworzony co do sztuki: 29 → 7 fałszywych zgód
        na 34, przy 1 utraconej prawdziwej zgodzie na 11."""
        przemycone = [x for x in _D1_KORPUS_ZGODA_CZESCIOWA if p.sprawdz_cytat(*x)]
        assert len(przemycone) == 7, przemycone
        odrzucone_zgody = [x for x in _D1_PRAWDZIWE_ZGODY if not p.sprawdz_cytat(*x)]
        assert odrzucone_zgody == []
        assert p.sprawdz_cytat(*_D1_UTRACONA_ZGODA[0]) is False

    @pytest.mark.parametrize("cytat,wiadomosc", [
        # Nowe słowa MUSZĄ być dopasowywane na OBU granicach słowa. Bez
        # domknięcia `(?!\w)` „ale" łapie „alergię" i „Aleję", „poza" łapie
        # „pozamiatane", a „lecz" — „lecznicze": cztery fałszywe odmowy na
        # wypowiedziach, które są zwykłymi zgodami (zmierzone, nie hipoteza).
        ("potwierdzam", "Mam alergie na olej lniany, potwierdzam reszte."),
        ("zgadza sie", "Aleja Grunwaldzka 5, zgadza sie."),
        ("wszystko ok", "Pozamiatane, wszystko ok."),
        ("potwierdzam", "Lecznicze wlasciwosci mnie nie interesuja, potwierdzam."),
    ])
    def test_spojnik_nie_lapie_wewnatrz_innego_slowa(self, cytat, wiadomosc):
        assert p.sprawdz_cytat(cytat, wiadomosc) is True

    def test_pelna_sciezka_2016_prosba_o_zmiane_nie_otwiera_bramki(self, monkeypatch):
        """Sonda `d1d_2016.py` w całości, nie sam `sprawdz_cytat`: klient prosi
        o zmianę grubości na 6 cm, model cytuje „ok". Przed D1: `potwierdz()`
        ok=True, `sprawdz_bramke()` ok=True, a do CRM szła grubość 4 — STARA."""
        conv_id = 96006
        _zapisz_pozycje_i_oczekiwany_podpis(conv_id)
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta",
                            lambda: "Ok, tylko zmienmy grubosc na 6 cm.")
        wynik = p.potwierdz("ok")
        assert wynik["ok"] is False
        assert wynik["error"] == "CYTAT_SPOZA_WIADOMOSCI"
        bramka = p.sprawdz_bramke()
        assert bramka["ok"] is False
        assert bramka["error"] == "BRAK_POTWIERDZENIA"
