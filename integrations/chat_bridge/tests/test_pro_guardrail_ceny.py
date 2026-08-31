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


class TestN1JednostkiWPelnychNazwach:
    """N1 (rerecenzja gałęzi): biała lista jednostek znała WYŁĄCZNIE skróty
    (cm/mm/kg/szt/dni/%), więc każde zdanie, w którym bot wypowiada jednostkę
    po polsku — „90 centymetrów", „55 kilogramów", „80 km", „240 minut" —
    kończyło się fałszywym alarmem G1 na liczbie, która nigdy nie była ceną.

    Koszt fałszywego alarmu jest DOKŁADNIE taki, jak przepuszczenia
    halucynacji: runda korekty, a przy powtórzeniu tej samej liczby (model nie
    wie, co „naprawia") oddanie rozmowy człowiekowi — w momencie zamykania
    sprzedaży. Zestaw niżej to realistyczne wypowiedzi bota o blatach
    dębowych, nie sztuczne przypadki brzegowe."""

    # Rejestr kwot typowej rozmowy: blat 843,04 zł, z wysyłką 1 093,04 zł,
    # drugi blat 1 936,71 zł, para blatów 1 686,08 zł.
    ZNANE = {"843.04", "1093.04", "1936.71", "1686.08"}

    @pytest.mark.parametrize("tekst", [
        # WYMIARY po polsku, pełną nazwą jednostki.
        "Wysokość blatu wynosi 90 centymetrów.",
        "Maksymalna długość blatu z dębu litego wynosi 450 centymetrów.",
        "Szerokość parapetu wynosi 60 centymetrów.",
        "Grubość to około 40 milimetrów.",
        "Blat ma około 180 centymetrów długości.",
        "Łącznie 240 centymetrów bieżących.",
        # WAGI.
        "Waga takiego blatu wynosi 55 kilogramów.",
        "Blat waży około 120 kilogramów.",
        "Paczka waży 55 kg.",
        # ODLEGŁOŚCI.
        "Nasz zakład jest około 80 km od Olsztyna.",
        "Wysyłamy w promieniu około 300 km.",
        "Do Warszawy jest około 210 kilometrów.",
        # CZAS.
        "Olej schnie około 240 minut.",
        "Wysyłka trwa około 72 h.",
        "Termin realizacji wynosi około 60 dni roboczych.",
        "Gwarancja wynosi 60 miesięcy.",
        "Blat sezonuje około 720 godzin.",
        # PROCENTY, TEMPERATURY, ZUŻYCIE.
        "Około 60 procent klientów wybiera dąb lity.",
        "Wilgotność drewna wynosi około 60 procent.",
        "Blat wytrzyma temperaturę około 120 stopni.",
        "Zużycie oleju to około 80 mililitrów na metr kwadratowy.",
        "Na blat schodzi około 250 ml oleju.",
        # ILOŚCI.
        "Łącznie 75 sztuk lameli w blacie.",
        "Razem 60 sztuk.",
    ])
    def test_zdanie_z_jednostka_nie_jest_naruszeniem(self, tekst):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == []

    @pytest.mark.parametrize("tekst", [
        # Kontrola POZYTYWNA: prawdziwe kwoty z rejestru przechodzą tak samo
        # jak dotąd — poprawka nie może uciszyć guardraila na cenach.
        "Blat dębowy kosztuje 843,04 zł brutto.",
        "Razem z wysyłką 1 093,04 zł brutto.",
        "Razem około 843 brutto.",
        "Drugi blat to 1 936,71 zł brutto.",
    ])
    def test_prawdziwe_kwoty_nadal_przechodza(self, tekst):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == []

    @pytest.mark.parametrize("tekst,oczekiwana", [
        # Kontrola NEGATYWNA: zmyślone kwoty nadal są łapane — rozszerzenie
        # listy jednostek nie może otworzyć furtki na halucynacje.
        ("Blat kosztuje około 2400 zł.", "2400.00"),
        ("Razem jakieś 2650.", "2650.00"),
        ("Dopłata 90.", "90.00"),
        ("Wysyłka kosztuje 180.", "180.00"),
        ("2400 netto", "2400.00"),
        ("Razem 55 brutto", "55.00"),
    ])
    def test_zmyslona_kwota_nadal_jest_naruszeniem(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == [oczekiwana]


class TestN1LiczbaPrzedSlowemCenowym:
    """N1, druga przyczyna: wzorzec „liczba PRZED słowem cenowym" dopuszczał
    KAŻDE słowo cenowe, także te, które po polsku stoją PRZED kwotą
    („razem", „cena", „kosztuje", „wynosi"). Liczba tuż przed nimi jest wtedy
    prawie zawsze czymś INNYM — nazwą handlową („Blat 180"), numerem
    zamówienia albo numerem wyceny — a prawdziwa cena stoi dopiero ZA słowem
    cenowym. Filtr jednostki nie miał tam nic do roboty, bo jednostka nie
    mieści się między liczbą a słowem.

    Zostają wyłącznie „brutto"/„netto" — jedyne słowa cenowe, które w
    polszczyźnie faktycznie NASTĘPUJĄ po kwocie."""

    ZNANE = {"843.04", "1686.08"}

    @pytest.mark.parametrize("tekst", [
        "Blat 180 razem 1 686,08 zł brutto.",
        "Dwa blaty 180 kosztują 1 686,08 zł.",
        "Wycena 1234 wynosi 843,04 zł brutto.",
        "Zamówienie 100234 kosztuje 843,04 zł.",
        "Model 2026 cena 843,04 zł brutto.",
        "Parapet 120 łącznie 843,04 zł brutto.",
        "Blat 180 w sumie 843,04 zł.",
    ])
    def test_nazwa_handlowa_i_numer_nie_sa_kwota(self, tekst):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == []

    def test_jednostka_przed_slowem_cenowym_tez_odsiewa(self):
        # Filtr jednostki działa teraz w OBU kierunkach: liczba z jednostką
        # nie jest kwotą niezależnie od tego, który wzorzec ją znalazł.
        assert g.sprawdz_ceny("Blat 180 cm netto waży 55 kg.", self.ZNANE) == []

    @pytest.mark.parametrize("tekst,oczekiwana", [
        # Kontrola negatywna kierunku „po kwocie" — TA droga ma zostać czynna.
        ("2400 netto", "2400.00"),
        ("Blat dębowy 2400 brutto.", "2400.00"),
    ])
    def test_kwota_przed_brutto_netto_nadal_lapana(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, set()) == [oczekiwana]


class TestN1ProgPiecdziesiatBezFalszywychAlarmow:
    """N1: potwierdzenie, że przyczyną fałszywych alarmów NIE był próg 50 zł,
    tylko jednostki. Próg zostaje; przy poprawnie rozpoznanych jednostkach
    liczby z przedziału 50-100 (najczęstsze wymiary i terminy w tej branży)
    nie generują ani jednego naruszenia."""

    @pytest.mark.parametrize("tekst", [
        "Wysokość blatu wynosi 90 centymetrów.",
        "Szerokość parapetu wynosi 60 centymetrów.",
        "Waga blatu wynosi 55 kilogramów.",
        "Zakład jest około 80 km od Olsztyna.",
        "Około 60 procent klientów wybiera dąb lity.",
        "Termin to około 60 dni roboczych.",
        "Razem 75 sztuk lameli.",
        "Łącznie 90 minut szlifowania.",
    ])
    def test_liczby_50_100_z_jednostka_sa_ciche(self, tekst):
        assert g.sprawdz_ceny(tekst, set()) == []

    def test_prog_nadal_wynosi_50(self):
        assert g._PROG_GOLEJ_KWOTY == 50.0

    @pytest.mark.parametrize("tekst,oczekiwana", [
        ("Dopłata 90", "90.00"),
        ("Opcja wycięcia kosztuje 81,30", "81.30"),
    ])
    def test_zmyslone_kwoty_50_100_bez_jednostki_nadal_lapane(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, set()) == [oczekiwana]

class TestC4GolaLiczbaMusiZamykacKlauzule:
    """C4 (runda D): po rundzie N1 zostawała JEDNA klasa fałszywych alarmów —
    liczba, po której stoi RZECZOWNIK POLICZALNY spoza białej listy jednostek,
    poprzedzona „około"/„razem"/„łącznie": „około 80 blatów dębowych",
    „około 90 lamel", „razem 150 zamówień". Cztery pierwsze to prawdopodobne
    odpowiedzi z bazy wiedzy o blatach, więc alarm zdarzałby się w normalnej
    rozmowie.

    Biała lista jednostek zawsze będzie niepełna, więc reguła jest ODWRÓCONA:
    goła liczba jest kandydatem na kwotę tylko wtedy, gdy ZAMYKA klauzulę —
    stoi na końcu zdania, przed znakiem interpunkcyjnym albo przed
    „brutto"/„netto", które samo zamyka klauzulę. „około 2400 brutto" łapiemy,
    „około 80 blatów" nie.

    Rejestr kwot jak w sondzie rerecenzji."""

    ZNANE = {"843.04", "1093.04", "1686.08", "250.00", "203.25", "1936.71", "2382.15"}

    @pytest.mark.parametrize("tekst", [
        "Mamy w ofercie około 120 wzorów wykończenia.",
        "W magazynie mamy około 80 blatów dębowych.",
        "Około 200 klientów miesięcznie zamawia blaty dębowe.",
        "Zrobiliśmy już około 500 schodów dębowych.",
        "Do wyboru jest około 60 odcieni oleju.",
        "Blat składa się z około 90 lamel.",
        "Suszarnia mieści około 300 blatów naraz.",
        "Razem 150 zamówień w tym miesiącu.",
        "Łącznie 400 pozycji w katalogu.",
        "Nasza załoga to około 55 osób.",
        # Kierunek „przed brutto/netto": nazwa handlowa, a prawdziwa cena stoi
        # dalej — „netto" nie zamyka tu klauzuli.
        "Blat 200 netto kosztuje 843,04 zł.",
    ])
    def test_rzeczownik_po_liczbie_nie_jest_falszywym_alarmem(self, tekst):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == []

    @pytest.mark.parametrize("tekst,oczekiwane", [
        ("Blat kosztuje 1 936,71 zł netto, czyli około 2400 brutto.", ["2400.00"]),
        ("Z wysyłką wyjdzie razem jakieś 2650.", ["2650.00"]),
        ("Dopłata 90", ["90.00"]),
        ("Opcja wycięcia kosztuje 81,30", ["81.30"]),
    ])
    def test_zmyslone_kwoty_z_sondy_nadal_lapane(self, tekst, oczekiwane):
        assert sorted(g.sprawdz_ceny(tekst, self.ZNANE)) == oczekiwane

    @pytest.mark.parametrize("tekst,oczekiwana", [
        # Zamkniecie klauzuli to takze przecinek, srednik i koniec LINII —
        # bot pisze wypunktowane wyceny, wiec kwota konczy wiersz.
        ("Razem 2650, z dostawą.", "2650.00"),
        ("Cena to 2400; dostawa osobno.", "2400.00"),
        ("- Razem: 2650\n- Termin: 14 dni", "2650.00"),
    ])
    def test_interpunkcja_i_koniec_linii_tez_zamykaja_kwote(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, self.ZNANE) == [oczekiwana]

    @pytest.mark.parametrize("tekst", [
        "Koszt wynosi 350 dopłaty.",
    ])
    def test_kwota_ze_zwyklym_slowem_za_soba_przechodzi_swiadomie(self, tekst):
        """Udokumentowana GRANICA mechanizmu: po gołej liczbie stoi słowo
        TREŚCIOWE, więc nie da się jej odróżnić od „około 80 blatów" bez
        rozumienia zdania. Z tokenem waluty kwota jest łapana normalnie
        (test niżej).

        D2 zawęziło tę granicę: „Razem 2650 za komplet." i „Cena to 2400
        z dostawą." stały tu do rerecenzji rundy D i BYŁY kosztem C4. Po
        dopuszczeniu słów funkcyjnych jako zamknięcia klauzuli są znowu łapane
        — patrz `TestD2SlowaFunkcyjneZamykajaKlauzule`. Zostaje wyłącznie
        kształt „kwota + rzeczownik", którego odróżnić się nie da."""
        assert g.sprawdz_ceny(tekst, self.ZNANE) == []

    def test_ta_sama_kwota_z_waluta_jest_nadal_lapana(self):
        # Druga strona kompromisu wyżej: token waluty wystarcza niezależnie od
        # tego, co stoi za kwotą.
        assert g.sprawdz_ceny("Razem 2650 zł za komplet.", self.ZNANE) == ["2650.00"]

    def test_zdania_naprawione_w_rundzie_c_nadal_ciche(self):
        # Kontrola, ze odwrocenie reguly nie cofa niczego z N1.
        for tekst in ("Wysokość blatu wynosi 90 centymetrów.",
                      "Waga takiego blatu wynosi 55 kilogramów.",
                      "Nasz zakład jest około 80 km od Olsztyna.",
                      "Olej schnie około 240 minut.",
                      "Wysyłka trwa około 72 h.",
                      "Blat 180 razem 1 686,08 zł brutto.",
                      "Zamówienie 100234 kosztuje 843,04 zł."):
            assert g.sprawdz_ceny(tekst, self.ZNANE) == [], tekst


# --- D2: korpusy rerecenzji D (sonda `d4b_kompromis.py`) ----------------------
#
# 40 naturalnych sposobów, w jakie bot sprzedażowy podaje kwotę BEZ tokenu
# waluty, i 40 zdań bazy wiedzy z gołą liczbą, która kwotą NIE jest. Ten sam
# korpus mierzył recenzent przed i po C4 — zapisany dosłownie, bez polskich
# znaków, żeby liczby w testach niżej były TYMI SAMYMI liczbami co w raporcie.
_D2_REJESTR = {"843.04", "1093.04", "1686.08", "250.00", "203.25", "1936.71", "2382.15"}

# (zdanie, kwota którą MUSI zgłosić) — 37 z 40 form korpusu.
_D2_ZMYSLONE_LAPANE = [
    ("Czyli razem 2650.", "2650.00"),
    ("Razem 2650 za komplet.", "2650.00"),
    ("Cena to 2400 brutto.", "2400.00"),
    ("Cena to 2400 brutto za caly blat.", "2400.00"),
    ("Lacznie wychodzi 2650.", "2650.00"),
    ("Lacznie wychodzi 2650 z dostawa.", "2650.00"),
    ("Koszt blatu to okolo 2400.", "2400.00"),
    ("Koszt blatu to okolo 2400 plus wysylka.", "2400.00"),
    ("Doplata 90.", "90.00"),
    ("Doplata 90 za wyciecie.", "90.00"),
    ("W sumie 2650 brutto.", "2650.00"),
    ("Cena wyniesie 2650.", "2650.00"),
    ("Cena wyniesie 2650 przy tej grubosci.", "2650.00"),
    ("Razem jakies 2650.", "2650.00"),
    ("Razem jakies 2650 za dwie sztuki.", "2650.00"),
    ("Blat debowy 2400 netto.", "2400.00"),
    ("Blat debowy 2400 netto plus VAT.", "2400.00"),
    ("Suma 2650.", "2650.00"),
    ("Suma 2650 do zaplaty przy odbiorze.", "2650.00"),
    ("Koszt wynosi 350.", "350.00"),
    ("- Razem: 2650\n- Termin: 14 dni", "2650.00"),
    ("- Razem: 2650 brutto\n- Termin: 14 dni", "2650.00"),
    ("Cena okolo 2650 brutto.", "2650.00"),
    ("Cena okolo 2650 brutto za sztuke.", "2650.00"),
    ("Razem 2650, plus dostawa.", "2650.00"),
    ("Razem 2650 i dostawa osobno.", "2650.00"),
    ("Lacznie 2650 netto.", "2650.00"),
    ("Lacznie 2650 netto za komplet.", "2650.00"),
    ("Mniej wiecej 2650 brutto.", "2650.00"),
    ("Cena bedzie 2650.", "2650.00"),
    ("Cena bedzie 2650 od sztuki.", "2650.00"),
    ("Koszt: 2650.", "2650.00"),
    ("Koszt: 2650 z montazem.", "2650.00"),
    ("Razem 2650 brutto.", "2650.00"),
    ("Razem 2650 brutto plus transport.", "2650.00"),
    ("Doplata za fazowanie 120 brutto.", "120.00"),
    ("Cena 2400 netto, dostawa gratis.", "2400.00"),
]

# Trzy formy korpusu, które przechodzą DALEJ — udokumentowana granica.
_D2_ZMYSLONE_PRZEPUSZCZANE = [
    # po kwocie stoi „razem"/„dopłaty" — słowo TREŚCIOWE, nie funkcyjne
    "W sumie 2650 brutto razem z kurierem.",
    "Koszt wynosi 350 doplaty.",
    # dwa wyrazy odstępu między słowem cenowym a liczbą — ta forma przechodziła
    # także PRZED C4, nie jest kosztem odwrócenia reguły
    "Doplata za fazowanie 120.",
]

_D2_NIE_KWOTY = [
    "Mamy okolo 120 wzorow wykonczenia.",
    "W magazynie mamy okolo 80 blatow debowych.",
    "Okolo 200 klientow miesiecznie zamawia blaty.",
    "Zrobilismy juz okolo 500 schodow debowych.",
    "Do wyboru jest okolo 60 odcieni oleju.",
    "Blat sklada sie z okolo 90 lamel.",
    "Suszarnia miesci okolo 300 blatow naraz.",
    "Razem 150 zamowien w tym miesiacu.",
    "Lacznie 400 pozycji w katalogu.",
    "Nasza zaloga to okolo 55 osob.",
    "Lacznie 220 wariantow wykonczenia.",
    "Razem 96 lamel w blacie 240 cm.",
    "W sumie 75 gatunkow drewna.",
    "Cena zalezy od okolo 300 czynnikow.",
    "Razem 12 krawedzi do obrobki.",
    "Lacznie 240 blatow wyprodukowanych w lipcu.",
    "W sumie 65 zamowien czeka na wysylke.",
    "Okolo 180 firm wspolpracuje z nami.",
    "Razem 320 metrow biezacych lameli.",
    "Lacznie 99 wzorow krawedzi.",
    "Blat ma 180 cm dlugosci.",
    "Wysokosc blatu wynosi 90 centymetrow.",
    "Waga blatu wynosi 55 kilogramow.",
    "Olej schnie okolo 240 minut.",
    "Jestesmy okolo 80 km od Olsztyna.",
    "Termin to okolo 14 dni roboczych.",
    "Wilgotnosc wynosi okolo 8 procent.",
    "Blat 180-200 cm to najczestszy wybor.",
    "Sezonowanie trwa okolo 12 miesiecy.",
    "Temperatura suszenia wynosi okolo 60 stopni.",
    "Rabat wynosi 10 procent przy dwoch blatach.",
    "Blat 200 cm netto wazy okolo 60 kg.",
    "Zamowienie 100234 jest w produkcji.",
    "Numer wyceny to 20260830.",
    "Gwarancja to 24 miesiace.",
    "Razem 3 sztuki, kazda 4 cm grubosci.",
    "Lacznie 12 sztuk lameli na metr.",
    "Cena obowiazuje do 2026 roku.",
    "Okolo 70 procent klientow wybiera olej.",
    "Razem 5 pozycji w tej wycenie.",
]


class TestD2SlowaFunkcyjneZamykajaKlauzule:
    """D2 (rerecenzja rundy D): po C4 guardrail łapał 55% naturalnych form
    zmyślonej ceny.

    C4 odwrócił regułę (goła liczba musi ZAMYKAĆ klauzulę) i zabił fałszywe
    alarmy — 0/40, potwierdzone. Zawęził jednak wykrywanie dużo mocniej, niż
    raportowano: 98% → 55% na korpusie 40 naturalnych sformułowań. Kluczowe
    przeoczenie: „brutto"/„netto" zamykało klauzulę TYLKO przed interpunkcją,
    więc `Około 2400 brutto za cały blat.` przechodziło bez śladu — a to
    NAJCZĘSTSZY kształt wypowiedzi bota, nie przypadek brzegowy. Bot pisze
    pełnymi zdaniami, a cena prawie zawsze coś obejmuje („za komplet",
    „z dostawą", „plus transport", „od sztuki", „przy tej grubości").

    Naprawa: obok interpunkcji klauzulę zamyka też ZAMKNIĘTA LISTA SŁÓW
    FUNKCYJNYCH (`_SLOWA_FUNKCYJNE`). Przyimek ani spójnik nie wprowadza
    rzeczownika policzalnego („80 blatów", „150 zamówień"), a prawie zawsze
    wprowadza to, co kwota obejmuje. Zmierzone na tym korpusie:
    trafienia 22/40 (55%) → 37/40 (92%), fałszywe alarmy nadal 0/40."""

    @pytest.mark.parametrize("tekst,oczekiwana", _D2_ZMYSLONE_LAPANE)
    def test_zmyslona_kwota_jest_lapana(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, _D2_REJESTR) == [oczekiwana]

    @pytest.mark.parametrize("tekst", _D2_ZMYSLONE_PRZEPUSZCZANE)
    def test_trzy_formy_przechodza_swiadomie(self, tekst):
        """Udokumentowana GRANICA: po kwocie stoi słowo TREŚCIOWE („razem",
        „dopłaty"), a nie funkcyjne. Dołożenie ich do listy zamknięć wraca
        fałszywymi alarmami na nazwach i numerach — lista funkcyjnych jest
        ZAMKNIĘTA świadomie. Trzecia forma („dopłata ZA FAZOWANIE 120")
        przechodziła także PRZED C4: to dwa wyrazy odstępu między słowem
        cenowym a liczbą, osobna sprawa niż zamknięcie klauzuli."""
        assert g.sprawdz_ceny(tekst, _D2_REJESTR) == []

    @pytest.mark.parametrize("tekst", _D2_NIE_KWOTY)
    def test_gola_liczba_niebedaca_kwota_nie_alarmuje(self, tekst):
        assert g.sprawdz_ceny(tekst, _D2_REJESTR) == []

    def test_pomiar_na_obu_korpusach_rerecenzji(self):
        """Pomiar recenzenta odtworzony co do sztuki: 22/40 → 37/40 trafień
        przy niezmiennych 0/40 fałszywych alarmów."""
        wszystkie = ([t for t, _ in _D2_ZMYSLONE_LAPANE]
                     + list(_D2_ZMYSLONE_PRZEPUSZCZANE))
        assert len(wszystkie) == 40
        trafione = [t for t in wszystkie if g.sprawdz_ceny(t, _D2_REJESTR)]
        assert len(trafione) == 37
        falszywe = [t for t in _D2_NIE_KWOTY if g.sprawdz_ceny(t, _D2_REJESTR)]
        assert falszywe == []

    @pytest.mark.parametrize("tekst,oczekiwana", [
        # Zdanie, które recenzja wskazała jako najczęstszy kształt wypowiedzi
        # bota — z polskimi znakami, bo tak bot pisze do klienta.
        ("Około 2400 brutto za cały blat.", "2400.00"),
        ("Razem 2650 brutto plus transport.", "2650.00"),
        ("Łącznie 2650 netto za komplet.", "2650.00"),
        ("Dopłata 90 za wycięcie.", "90.00"),
        ("Cena to 2400 z dostawą.", "2400.00"),
    ])
    def test_najczestszy_ksztalt_wypowiedzi_bota_jest_lapany(self, tekst, oczekiwana):
        assert g.sprawdz_ceny(tekst, _D2_REJESTR) == [oczekiwana]

    @pytest.mark.parametrize("tekst", [
        # Kontrola, że lista funkcyjnych NIE otwiera z powrotem klasy fałszywych
        # alarmów zamkniętej w C4: po liczbie stoi rzeczownik policzalny.
        "W magazynie mamy około 80 blatów dębowych.",
        "Blat składa się z około 90 lamel.",
        "Razem 150 zamówień w tym miesiącu.",
        "Łącznie 400 pozycji w katalogu.",
        # ...ani klasy zamkniętej w N1: jednostka po polsku.
        "Wysokość blatu wynosi 90 centymetrów.",
        "Nasz zakład jest około 80 km od Olsztyna.",
        # Przyimek po JEDNOSTCE nie robi z wymiaru kwoty — filtr jednostki
        # jest drugą linią obrony i musi zadziałać przed listą funkcyjnych.
        "Zużycie oleju to około 80 mililitrów na metr kwadratowy.",
        "Blat ma około 180 centymetrów do krawędzi.",
    ])
    def test_lista_funkcyjnych_nie_wraca_falszywymi_alarmami(self, tekst):
        assert g.sprawdz_ceny(tekst, _D2_REJESTR) == []

    def test_lista_slow_funkcyjnych_jest_zamknieta(self):
        """Lista jest ZAMKNIĘTA i krótka świadomie — każde poszerzenie o słowo
        treściowe wraca fałszywymi alarmami na nazwach handlowych i numerach
        (dowód: N1). Ten test jest zaporą na ciche dopisanie kolejnego słowa:
        zmiana listy ma być decyzją opartą na pomiarze, nie odruchem."""
        assert g._SLOWA_FUNKCYJNE_ZAMYKAJACE == (
            "za", "z", "plus", "i", "przy", "od", "do", "wraz", "bez", "na", "oraz")
