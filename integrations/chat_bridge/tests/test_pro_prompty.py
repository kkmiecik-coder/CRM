# -*- coding: utf-8 -*-
"""
Reguły promptu, które powstały z naprawy KONKRETNEGO błędu zaobserwowanego na
żywym czacie (runda napraw 1, sześć rozmów). Prompt jest tu jedynym miejscem,
w którym te reguły żyją — nie ma pod nimi kodu, który by je egzekwował — więc
test pilnuje jedynej rzeczy, jakiej może: że reguła NIE ZNIKNĘŁA. Przypadkowe
usunięcie zdania z długiego stringa jest niewidoczne w code review, a każde
z tych zdań kosztowało jedną rozmowę z klientem.

Testujemy KOTWICE (nagłówek sekcji + fragment nośny), nie brzmienie słowo
w słowo — przeredagowanie stylu ma przechodzić, wycięcie reguły ma oblewać.

`bots_pro.prompty` nie importuje `agents` (to gołe stringi), więc ten plik —
w odróżnieniu od test_pro_agenci.py — NIE ma `importorskip` i chodzi także
w obrazie bez SDK.
"""
import re

from bots_pro import prompty


def _ciagiem(tekst):
    """Prompt bez łamania wierszy — jeden ciąg, pojedyncze spacje.

    Reguły są w źródle zawijane do ~90 kolumn, więc szukana fraza potrafi mieć
    w środku znak nowej linii („nie wspominaj z własnej\ninicjatywy"). Test ma
    oblewać na WYCIĘCIU reguły, nie na przelaniu akapitu przy dopisaniu jednego
    słowa gdzieś wyżej — stąd normalizacja białych znaków przed porównaniem."""
    return re.sub(r"\s+", " ", tekst)


ROLA = _ciagiem(prompty.ROLA)
WYCENA = _ciagiem(prompty.WYCENA)
WIEDZA = _ciagiem(prompty.WIEDZA)
KONSTRUKCJA = _ciagiem(prompty.KONSTRUKCJA)


class TestN1PytanieZobowiazuje:
    """Trzy rozmowy z żywego czatu, jedna figura: bot w JEDNEJ turze zadawał
    pytanie i wołał oddaj_czlowiekowi. „Czy jesteś botem?" -> oferta konsultanta
    i natychmiastowe przekazanie. Obietnica porównania wariantów -> dopytanie
    i przekazanie. Przekroczony limit wariantu -> propozycja wyboru i
    przekazanie. Za każdym razem klient zostawał z pytaniem bez adresata:
    rozmowa była już u człowieka, więc odpowiedź klienta trafiała w próżnię."""

    def test_rola_kaze_poczekac_na_odpowiedz_po_pytaniu_o_bota(self):
        assert "czy to bot" in ROLA
        assert "poczekaj na odpowiedź klienta" in ROLA

    def test_rola_nie_wozi_juz_dopisku_o_imieniu_klienta(self):
        # Ta zmiana jest opłaceniem tej wyżej: ROLA doklejana jest do WSZYSTKICH
        # agentów, w tym do routera, którego budżet (ROLA+ROUTER) ma limit 400
        # tokenów i stał na 393. Dopisek o imieniu klienta jest kosmetyką stylu
        # — reguła o czekaniu na odpowiedź chroni przed zostawieniem klienta
        # bez adresata. Wycięcie zwolniło zapas: 393 -> 388 tokenów.
        assert "imieniem klienta" not in ROLA

    def test_wycena_ma_regule_pytanie_zobowiazuje(self):
        assert "PYTANIE ZOBOWIĄZUJE" in WYCENA
        assert "nie wołaj w tej samej turze oddaj_czlowiekowi" in WYCENA


class TestN2PodsumowaniePoDoliczeniuDostawy:
    """Rozmowa z żywego czatu: po policz_wysylke bot poprosił o ponowne
    potwierdzenie, NIE pokazując nowego podsumowania — musiałem sam poprosić
    o zestawienie. Klient miałby potwierdzić kwotę, której nigdy nie zobaczył,
    czyli dokładnie to, przed czym chroni wymóg potwierdzenia (I2), wpuszczone
    bocznymi drzwiami."""

    def test_wycena_kaze_wyslac_podsumowanie_ponownie_po_dostawie(self):
        assert "Po policz_wysylke zawsze wołaj wyslij_podsumowanie ponownie" in WYCENA
        assert "nie potwierdzać starą" in WYCENA


class TestN4KsztaltInnyNizProstokat:
    """Rozmowa z żywego czatu: klient poprosił o blat okrągły ⌀120. Bot nazwał
    go okrągłym i policzył kwadrat 120x120. Koło o średnicy 120 to 1,13 m2,
    kwadrat 120x120 to 1,44 m2 — 27% materiału różnicy, czyli kwota bez
    pokrycia, podana klientowi jako cena wiążąca do potwierdzenia. Kalkulator
    CRM nie zna innych kształtów niż prostokąt; jedynym poprawnym wyjściem
    jest człowiek."""

    def test_wycena_ma_sekcje_ksztalt(self):
        assert "KSZTAŁT." in WYCENA
        assert "Wyceniamy wyłącznie prostokąty i kwadraty" in WYCENA

    def test_wycena_wymienia_ksztalty_ktorych_nie_liczymy(self):
        for ksztalt in ("okrągły", "owalny", "litery L", "łukiem", "nieregularny"):
            assert ksztalt in WYCENA, ksztalt

    def test_wycena_zabrania_liczenia_ksztaltu_jak_prostokata(self):
        assert "Nigdy nie licz takiego kształtu jak prostokąta" in WYCENA

    def test_wycena_kaze_oddac_taki_ksztalt_czlowiekowi(self):
        assert "kształt inny niż prostokąt" in WYCENA


class TestN5WymiaryIPoprawkiKlienta:
    """Rozmowa z żywego czatu, trzy błędy w jednym wątku: bot po cichu zmienił
    interpretację, który z podanych wymiarów jest szerokością, a który
    długością; zignorował poprawkę, którą klient podał wprost; a na zadane na
    wprost „o co chodzi?" odesłał samo podsumowanie, bez ani jednego zdania
    wyjaśnienia.

    Runda 1 zapisała regułę jako „najpierw wyjaśnij jednym zdaniem, dopiero
    potem wyślij podsumowanie" i zostawiła w tym miejscu ostrzeżenie, że jest
    ona NIEWYKONALNA w jednej turze: `tura.py` (bramka W3) świadomie nie wysyła
    `final_output`, gdy w tej samej turze poszło deterministyczne podsumowanie
    (dowód: test_pro_tura.py::
    test_niepusty_final_output_po_wyslaniu_podsumowania_tez_nie_jest_wysylany).
    Runda 2 (P1) dopisała brakującą połowę wprost do promptu — zakaz wołania
    `wyslij_podsumowanie` w turze z wyjaśnieniem i przeniesienie zestawienia na
    turę następną — więc reguła jest dziś spełnialna dokładnie tak, jak brzmi.
    Pilnują tego dwa ostatnie testy tej klasy."""

    def test_wycena_zabrania_cichej_zamiany_dlugosci_i_szerokosci(self):
        assert "Nie zmieniaj po cichu tego, który wymiar jest długością" in WYCENA

    def test_wycena_kaze_stosowac_poprawke_doslownie(self):
        assert "zastosuj poprawkę dosłownie" in WYCENA

    def test_wycena_kaze_wyjasnic_zanim_wysle_podsumowanie(self):
        assert "najpierw wyjaśnij jednym zdaniem" in WYCENA

    def test_wycena_zabrania_podsumowania_w_turze_z_wyjasnieniem(self):
        """Runda napraw 2, P1 — bez tego zastrzeżenia reguła jest NIEWYKONALNA.

        Bramka W3 w `tura.py` świadomie nie wysyła `final_output`, gdy w tej
        samej turze poszło deterministyczne podsumowanie (dowód:
        test_pro_tura.py::test_niepusty_final_output_po_wyslaniu_podsumowania_
        tez_nie_jest_wysylany). Model, który wykonałby regułę dosłownie w JEDNEJ
        turze — napisałby wyjaśnienie i zawołał `wyslij_podsumowanie` — odtworzy
        dokładnie tę awarię, którą reguła miała naprawić: klient dostanie samo
        zestawienie, bez ani jednego zdania wyjaśnienia. Reguła jest spełnialna
        WYŁĄCZNIE w czasie i prompt musi to mówić wprost."""
        assert "nie wołaj wyslij_podsumowanie" in WYCENA

    def test_wycena_odklada_zestawienie_na_nastepna_ture(self):
        """Druga połowa tego samego zastrzeżenia: sam zakaz zostawiłby klienta
        bez podsumowania w ogóle. Reguła ma mówić, KIEDY je wysłać."""
        assert "dopiero w następnej turze" in WYCENA


class TestP2CenyProduktuAObrobkaNiestandardowa:
    """Runda napraw 2, P2 — sekcja CENY zderzała się z adnotacją, którą N3
    dokleja do podsumowania z wycięciami („koszt wycięć nie jest wliczony w tę
    cenę — wycenia je konsultant").

    Oba zdania są prawdziwe, bo mówią o różnych rzeczach: wycenę PRODUKTU liczy
    automat (i obiecywanie tam konsultanta było obietnicą, której nikt by nie
    spełnił), a wycięcia i otwory faktycznie wycenia człowiek — pole `otwory`
    nigdy nie dociera do kalkulatora. Reguła zapisana BEZ zakresu kazała jednak
    modelowi przemilczeć również ten drugi przypadek, a wysłane podsumowanie
    zostaje w historii rozmowy i kusi, żeby frazę z niego uogólnić na całość.
    Zawężamy więc regułę; treści podsumowania NIE ruszamy — ona jest prawdziwa."""

    def test_zakaz_dotyczy_wyceny_produktu_a_nie_kazdej_kwoty(self):
        assert "Nie pisz, że wycenę produktu przygotuje albo policzy konsultant" in WYCENA

    def test_wolno_powiedziec_ze_obrobke_niestandardowa_wycenia_konsultant(self):
        assert "wycięcia i otwory wycenia konsultant" in WYCENA


class TestN8KrawedziePrzyBlacieKuchennym:
    """Wymóg właściciela, nie naprawa błędu: bot ma przy BLATACH KUCHENNYCH sam
    wspomnieć o możliwości obróbki krawędzi. Dotąd prompt zabraniał tego wprost
    („nigdy nie proponuj ani nie wspominaj o otworach, wycięciach i obróbce
    krawędzi z własnej inicjatywy"), więc to zamiana zdania W MIEJSCU, nie
    dołożenie drugiej, sprzecznej reguły obok pierwszej.

    Zakres wyjątku jest wąski i celowo taki został: JEDEN raz, tylko krawędzie,
    tylko blaty kuchenne. Otwory i wycięcia zostają po stronie zakazu — one
    nadal nie wchodzą do ceny (patrz N3), więc zaczynanie o nich rozmowy
    z własnej inicjatywy tworzyłoby oczekiwanie bez pokrycia w wycenie."""

    def test_wycena_pozwala_wspomniec_o_krawedziach_przy_blacie_kuchennym(self):
        assert "Przy blacie kuchennym JEDEN raz" in WYCENA
        assert "obróbki krawędzi" in WYCENA

    def test_wycena_dalej_zabrania_zaczynania_o_otworach_i_wycieciach(self):
        assert "poza blatami kuchennymi" in WYCENA
        assert "nie wspominaj z własnej inicjatywy" in WYCENA

    def test_stary_zakaz_bezwarunkowy_znikl_a_nie_zostal_obok(self):
        # Dwa zdania obok siebie — „nigdy nie wspominaj" i „przy blacie
        # kuchennym wspomnij" — daly model, ktory raz robi jedno, raz drugie.
        assert "Nigdy nie proponuj ani nie" not in WYCENA


class TestN10Konstrukcja:
    """Do tej rundy prompt NIE MIAL zadnego zakazu orzekania o nosnosci i
    wykonalnosci konstrukcyjnej. Bot mogl wiec odpowiedziec „tak, wytrzyma"
    na pytanie, na ktore nie ma danych — a klient, ktory dostal takie
    potwierdzenie, zamawia na jego podstawie.

    Regula jest DUPLIKATEM w dwoch promptach (Wycena i Wiedza), swiadomie.
    Naturalnym miejscem na wspolna regule jest ROLA, doklejana do wszystkich
    agentow — ale ROLA idzie takze do routera, ktorego budzet (ROLA+ROUTER)
    ma limit 400 tokenow i stoi na 388. Duplikat kosztuje znaki w dwoch
    promptach; ROLA kosztowalaby przekroczenie budzetu routera.

    Pytanie konstrukcyjne trafia do obu agentow naprawde: „czy blat 2 cm
    wytrzyma zlew?" to dla routera pytanie o WYCENE (parametry produktu),
    a „czy dab nadaje sie na taras?" to pytanie o OFERTE (Wiedza)."""

    def test_wycena_ma_sekcje_konstrukcja(self):
        assert "KONSTRUKCJA." in WYCENA
        assert "Nie orzekasz o nośności" in WYCENA

    def test_wiedza_ma_te_sama_sekcje(self):
        assert "KONSTRUKCJA." in WIEDZA
        assert "Nie orzekasz o nośności" in WIEDZA

    def test_obie_kopie_pochodza_z_jednego_zrodla(self):
        # Duplikat jest w RENDEROWANYM prompcie, nie w zrodle: obie sekcje sa
        # wstawiane z jednej stalej `prompty.KONSTRUKCJA`. Dwie recznie
        # przepisane kopie rozjechalyby sie przy pierwszej poprawce, a agent
        # Wiedzy odmawialby wtedy inaczej niz agent Wyceny na to samo pytanie.
        assert KONSTRUKCJA in WYCENA
        assert KONSTRUKCJA in WIEDZA

    def test_regula_wymienia_zakazane_orzeczenia(self):
        for zwrot in ("wytrzyma", "udźwignie", "nie ugnie się", "nadaje się",
                      "gwarantujemy"):
            assert zwrot in WYCENA, zwrot

    def test_regula_kaze_oddac_pytanie_konstrukcyjne_czlowiekowi(self):
        assert "pytanie konstrukcyjne" in WYCENA
        assert "pytanie konstrukcyjne" in WIEDZA

    def test_propozycja_grubosci_nie_jest_orzeczeniem_o_nosnosci(self):
        # WYMIARY pozwala zaproponowac grubosc, gdy klient jej nie zna. Bez
        # tego zdania KONSTRUKCJA czytaloby sie jak zakaz tamtej propozycji.
        assert "Propozycja grubości dotyczy standardu i wyglądu, nie nośności" in WYCENA

    def test_reguly_NIE_MA_w_ROLA(self):
        # ROLA idzie takze do routera — patrz docstring klasy.
        assert "KONSTRUKCJA" not in ROLA
