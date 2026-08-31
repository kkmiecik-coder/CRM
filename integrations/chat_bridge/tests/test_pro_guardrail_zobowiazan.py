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
        # RUNDA NAPRAW 6 (P1): zdanie o bezpieczeństwie musi być KATEGORYCZNE.
        # Dotąd wzorzec wymagał przylegania („jest bezpieczny"), więc łapał
        # zwykłą odpowiedź bazy wiedzy o olejach do blatów kuchennych („oleje
        # są bezpieczne przy kontakcie z żywnością" — sonda recenzenta, U-N1),
        # a kategorycznego zapewnienia z przysłówkiem („jest CAŁKOWICIE
        # bezpieczny") nie łapał wcale. Dobór był odwrotny do zamierzonego:
        # karał poprawną odpowiedź, przepuszczał obietnicę.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Ten olej jest całkowicie bezpieczny dla dzieci.")

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


class TestR6ZaweznieDoFormTwierdzacych:
    """Runda napraw 6, P1 — recenzja §5/U-N1.

    Sonda recenzenta wzięła siedem realistycznych, POPRAWNYCH wypowiedzi
    Dębusia i zmierzyła, co robi z nimi G3: siedem na siedem kończyło się
    handoffem. G3 nie ma rundy korekty, więc odpowiedź jest bezpowrotnie
    kasowana, klient dostaje generyczne „Przekazuję rozmowę konsultantowi",
    a wycena w toku umiera.

    Przyczyna nie leżała w implementacji (regex robił dokładnie to, co
    zaprojektowano), tylko w DOBORZE pozycji: wzorce łapały zwrot niezależnie
    od tego, czy bot coś OBIECUJE, czy właśnie temu ZAPRZECZA, i łapały gołe
    rzeczowniki („certyfikat", „atest") bez śladu zobowiązania.

    Dwa przypadki były nie do obrony:

      * `gwarantujemy` w formie zaprzeczonej to LITERALNE wykonanie sekcji
        CZEGO NIE WOLNO („Nigdy nie obiecuj […] terminów realizacji […]; gdy
        klient pyta, krótko to powiedz i wróć do wyceny"). Najkrótsze poprawne
        wykonanie tej reguły po polsku brzmi „terminów nie gwarantujemy" —
        czyli prompt NAKAZYWAŁ zdanie, które bramka karała utratą rozmowy
        (sprzeczność S2 z recenzji).
      * `certyfikat*` i `atest*` wystarczyło, żeby bot POWTÓRZYŁ pytanie
        klienta („pyta Pan o certyfikat FSC"), i wycena w toku przepadała.

    Zawężenie ma trzy elementy, wszystkie w `guardraile`:

      1. przeczenie bezpośrednio przed zwrotem („nie gwarantujemy", „nie mamy
         atestu") — to zaprzeczenie obietnicy, nie obietnica;
      2. klauzula pytajna/referowana („…, czy blat wytrzyma…") — bot cytuje
         pytanie, a nie orzeka;
      3. rzeczowniki `certyfikat`/`atest` wymagają CZASOWNIKA DEKLARATYWNEGO
         posiadania albo wydania tuż przed sobą („mamy certyfikat", „mają
         atest") — sam rzeczownik nie jest zobowiązaniem.

    Lista pozostaje ZAMKNIĘTA i ma nadal dziewięć pozycji — zmieniło się to,
    CO każda z nich łapie, nie ile ich jest."""

    # --- siedem zdań z sondy recenzenta: KAŻDE ma przechodzić ---------------

    def test_terminow_nie_gwarantujemy_przechodzi(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Terminów realizacji nie gwarantujemy — ustala je konsultant "
            "przy finalizacji.") == []

    def test_brak_atestu_przechodzi(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Nie mamy atestu na kontakt z żywnością.") == []

    def test_nie_wydajemy_certyfikatow_przechodzi(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Certyfikatów nie wydajemy.") == []

    def test_odpowiedz_bazy_wiedzy_o_olejach_przechodzi(self):
        # Typowa odpowiedź bazy wiedzy o olejach do blatów kuchennych —
        # rdzeń oferty, nie przypadek brzegowy.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Oleje, których używamy, są bezpieczne przy kontakcie "
            "z żywnością.") == []

    def test_odmowa_orzekania_o_nosnosci_przechodzi(self):
        # Bot robi DOKŁADNIE to, co każe sekcja KONSTRUKCJA: nie orzeka
        # i oddaje pytanie człowiekowi. Za tę odpowiedź tracił rozmowę.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Nie orzekam, czy blat wytrzyma zlew podblatowy — przekażę "
            "pytanie konsultantowi.") == []

    def test_ostrzezenie_o_uzytku_zewnetrznym_przechodzi(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Dąb nie nadaje się na zewnątrz bez impregnacji.") == []

    def test_powtorzenie_pytania_klienta_o_certyfikat_przechodzi(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Rozumiem, że pyta Pan o certyfikat FSC — sprawdzi to "
            "konsultant.") == []

    # --- kontrole pozytywne: prawdziwe obietnice nadal są łapane -----------

    def test_obietnica_gwarancji_nadal_lapana(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Gwarantujemy termin realizacji do 14 dni.") == ["gwarantujemy"]

    def test_orzeczenie_o_nosnosci_nadal_lapane(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Ten blat wytrzyma 200 kg.") == ["wytrzyma"]

    def test_posiadanie_certyfikatu_nadal_lapane(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Mamy certyfikat na te blaty.") == ["certyfikat"]

    def test_posiadanie_atestu_nadal_lapane(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Blaty mają atest higieniczny.") == ["atest"]

    def test_uzytek_zewnetrzny_w_trybie_twierdzacym_nadal_lapany(self):
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Dąb nadaje się na zewnątrz.") == ["nadaje się na zewnątrz"]

    def test_zapewnienie_o_bezpieczenstwie_jest_lapane(self):
        # ZYSK, nie strata: dotychczasowy wzorzec wymagał PRZYLEGANIA
        # („jest bezpieczny"), więc kategorycznego zapewnienia z przysłówkiem
        # — czyli kształtu, w którym obietnica pada naprawdę — NIE łapał
        # wcale. Potwierdza to sonda recenzenta: „Ten olej jest całkowicie
        # bezpieczny dla dzieci." przechodziło przez G3 przed tą rundą.
        for zdanie in ("Ten olej jest całkowicie bezpieczny dla dzieci.",
                       "Nasze oleje są w pełni bezpieczne dla żywności.",
                       "Blat jest absolutnie bezpieczny przy kontakcie z wodą."):
            assert guardraile.znajdz_zakazane_zobowiazania(zdanie) == \
                ["jest bezpieczny"], zdanie

    def test_przeczenie_wewnatrz_zwrotu_nie_jest_zaprzeczeniem_obietnicy(self):
        # „nie ugnie się" i „nie odkształci się" MAJĄ w sobie „nie", ale
        # nadal są orzeczeniem o konstrukcji — sekcja KONSTRUKCJA wymienia je
        # z nazwy. Filtr przeczenia patrzy na to, co stoi PRZED zwrotem,
        # więc tych dwóch nie rozbraja.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Przy 4 cm nie ugnie się.") == ["nie ugnie się"]
        assert guardraile.znajdz_zakazane_zobowiazania(
            "W wilgoci nie odkształci się.") == ["nie odkształci się"]

    def test_obietnica_po_klauzuli_pytajnej_nadal_lapana(self):
        # Filtr klauzuli pytajnej działa NA KLAUZULĘ, nie na całe zdanie:
        # odpowiedź twierdząca po pytaniu jest nadal obietnicą.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Pyta Pan, czy blat wytrzyma zlew? Wytrzyma bez problemu.") == \
            ["wytrzyma"]

    def test_przeczenie_musi_przylegac_do_zwrotu(self):
        # Kontrola granicy filtru: „nie" gdzieś w zdaniu nie rozbraja
        # obietnicy stojącej w innej klauzuli.
        assert guardraile.znajdz_zakazane_zobowiazania(
            "Nie znam wagi zlewu, ale blat wytrzyma każdy.") == ["wytrzyma"]

    def test_lista_nadal_ma_dziewiec_pozycji(self):
        assert len(guardraile.ZAKAZANE_ZOBOWIAZANIA) == 9
