# -*- coding: utf-8 -*-
"""
Guardraile wyjściowe — kontrola odpowiedzi PRZED wysłaniem do klienta.

G1 (integralność ceny) jest jedynym guardrailem od pierwszego dnia. Kolejne
dokładamy dopiero, gdy dane z produkcji pokażą, że są potrzebne — nie na zapas.
"""
import re

# Waluta: dowolna wielkość liter, formy skrócone i odmienione. "złotych"/"zlotych"
# MUSI stać w alternatywie PRZED "zł"/"zl" — inaczej krótszy wariant dopasowałby się
# pierwszy i zostawił nierozpoznany ogon "otych" tuż za dopasowaniem.
_WALUTA = r"(?:z[lł]otych|z[lł]|PLN)"

# Separator tysięcy: spacja zwykła, spacja nierozdzielająca (NBSP, U+00A0), wąska
# spacja nierozdzielająca (U+202F, spotykana w eksportach/PDF-ach) albo kropka
# (notacja "1.936,71"). Separator dziesiętny w tej (grupowanej) notacji to ZAWSZE
# przecinek — polska konwencja.
_SEP_TYSIECY = "[   .]"
_LICZBA_GRUPOWANA = r"\d{1,3}(?:%s\d{3})+(?:,\d{2})?" % _SEP_TYSIECY

# Notacja "prosta": bez grupowania tysięcy, separator dziesiętny przecinek LUB
# kropka (np. zapis anglosaski "1936.71").
_LICZBA_PROSTA = r"\d+(?:[,.]\d{2})?"

_LICZBA = r"(?:%s|%s)" % (_LICZBA_GRUPOWANA, _LICZBA_PROSTA)

# Odstęp między liczbą a walutą: spacja (zwykła/NBSP/wąska nierozdzielająca) i/lub
# dwukropek ("Cena w zł: 9999,99"), w dowolnej kombinacji do 3 znaków. CELOWO bez
# \s — \s łapie też znak nowej linii, więc "Razem 1000 zł\n3 dni robocze" doklejałoby
# "3" z kolejnej linii jako kolejną kwotę (bot zwraca wypunktowane, wielolinijkowe
# odpowiedzi — to normalny kształt wyceny, nie brzeg).
_ODSTEP = "[ \xa0 :]{0,3}"

# Kwota = liczba + waluta, w DOWOLNEJ kolejności (bot bywa proszony o "PLN 1936,71"
# tak samo jak o "1936,71 zł") — waluta jest OBOWIĄZKOWA, bez niej "14 dni" czy
# "120x60x4" wpadałyby jako ceny.
_KWOTA_LICZBA_WALUTA = re.compile(r"(%s)%s%s\b" % (_LICZBA, _ODSTEP, _WALUTA), re.IGNORECASE)
_KWOTA_WALUTA_LICZBA = re.compile(r"\b%s%s(%s)" % (_WALUTA, _ODSTEP, _LICZBA), re.IGNORECASE)

# --- Kwota BEZ waluty, przy słowie cenowym (U8, recenzja końcowa) -------------
#
# Waluta wyżej jest obowiązkowa świadomie, ale skutek był taki, że NAJCZĘSTSZA
# forma halucynacji z audytu — „czyli około 2400 brutto", „razem jakieś 2650" —
# przechodziła bez śladu. Naprawa jest CELOWO wąska, bo fałszywy alarm kosztuje
# tu tyle samo co przepuszczenie (patrz U6: niepotrzebna runda korekty, a przy
# drugim niepowodzeniu oddanie rozmowy człowiekowi na końcu udanej wyceny).
#
# Trzy warunki naraz — dopiero komplet robi z gołej liczby „kwotę":
#   1. liczba stoi BEZPOŚREDNIO przy słowie cenowym (najwyżej jedno słowo
#      wtrącone, i to z zamkniętej listy zwrotów przybliżających),
#   2. jest WIĘKSZA niż próg — „razem 3 pozycje" i „łącznie 12 sztuk" to rzeczy
#      policzalne, nie ceny; próg 100 zł jest niżej niż jakakolwiek realna suma
#      wyceny blatu, a wyżej niż typowe liczebniki, terminy i liczby sztuk,
#   3. NIE ma tuż za sobą jednostki (cm/mm/szt./dni/kg/%) — „Razem 240 cm
#      długości" nadal nie jest kwotą.
# Wymiary („180x60x4") wypadają wcześniej, na granicy słowa: po liczbie stoi
# tam „x", który jest znakiem słownym.
_SLOWA_CENOWE = (r"(?:brutto|netto|razem|[łl][ąa]cznie|cen[aeyęą]|kosztuj\w*|koszt\w*|"
                 r"dop[łl]at\w*|wynosi|wyniesie|oko[łl]o|sum[aęy]|w sumie)")

# Zwroty przybliżające, które model wtrąca MIĘDZY słowo cenowe a liczbę
# („razem JAKIEŚ 2650"). Zamknięta lista, nie „dowolne słowo" — inaczej „cena
# obowiązuje do 2026 roku" byłaby naruszeniem.
_PRZYBLIZENIE = (r"(?:jakie[śs]|oko[łl]o|ok|mniej wi[ęe]cej|to|wynosi|wyniesie|"
                 r"jest|b[ęe]dzie|wychodzi|wyjdzie)")

# Odstęp między słowem a liczbą — jak _ODSTEP, CELOWO bez \s (nowa linia nie
# łączy słowa cenowego z liczbą z następnego wiersza; patrz N1 wyżej).
_ODSTEP_SLOWNY = "[ \xa0 :,\\-–—]{1,3}"

_JEDNOSTKI = r"(?:cm|mm|m2|m3|m|szt\w*|dni|dzie[ńn]|tygod\w*|godz\w*|kg|%)"

_GOLA_PO_SLOWIE_CENOWYM = re.compile(
    r"(?<!\w)%s%s(?:%s%s)?(%s)(?!\w)" % (
        _SLOWA_CENOWE, _ODSTEP_SLOWNY, _PRZYBLIZENIE, _ODSTEP_SLOWNY, _LICZBA),
    re.IGNORECASE)
_GOLA_PRZED_SLOWEM_CENOWYM = re.compile(
    r"(?<!\w)(%s)%s%s(?!\w)" % (_LICZBA, _ODSTEP_SLOWNY, _SLOWA_CENOWE), re.IGNORECASE)

_JEDNOSTKA_ZA_LICZBA = re.compile(r"[ \xa0 ]*%s(?!\w)" % _JEDNOSTKI, re.IGNORECASE)

# Poniżej tego progu goła liczba przy słowie cenowym to prawie zawsze liczebnik
# ("razem 3 pozycje"), nie kwota. Kwoty ZNANE rejestrowi i tak nie są
# naruszeniem, więc próg ogranicza wyłącznie zasięg wykrywania halucynacji.
_PROG_GOLEJ_KWOTY = 100.0


def _normalizuj_liczbe(tekst):
    """'1 936,71' / '1.936,71' / '1936.71' / '843' -> 'NNNN.GG'.

    Separator dziesiętny to ostatni przecinek LUB kropka, o ile bezpośrednio po nim
    stoją dokładnie 2 cyfry — cokolwiek zostaje w części całkowitej to separatory
    tysięcy (spacja/NBSP/wąska spacja/kropka), więc po prostu je wyrzucamy."""
    tekst = tekst.strip()
    dopasowanie = re.search(r"[,.](\d{2})$", tekst)
    if dopasowanie:
        grosze = dopasowanie.group(1)
        calosc = tekst[:dopasowanie.start()]
    else:
        grosze = "00"
        calosc = tekst
    zlote = re.sub(r"\D", "", calosc)
    return "%s.%s" % (zlote, grosze)


def znajdz_kwoty(tekst):
    """Zbiór kwot w tekście, znormalizowanych do 'NNNN.GG'."""
    tekst = tekst or ""
    wynik = set()
    for wzorzec in (_KWOTA_LICZBA_WALUTA, _KWOTA_WALUTA_LICZBA):
        for liczba in wzorzec.findall(tekst):
            wynik.add(_normalizuj_liczbe(liczba))
    return wynik


def znajdz_gole_kwoty(tekst):
    """Kwoty BEZ tokenu waluty, rozpoznane po sąsiedztwie słowa cenowego (U8).

    Osobna funkcja od `znajdz_kwoty` świadomie: tamta odpowiada na pytanie „co
    w tym tekście JEST kwotą", i „14 dni" ma tam nadal nie być kwotą. Ta
    odpowiada na węższe: „co w tym tekście WYGLĄDA jak wypowiedziana cena, mimo
    braku »zł«" — i jest używana wyłącznie przez `sprawdz_ceny`."""
    tekst = tekst or ""
    wynik = set()
    for wzorzec in (_GOLA_PO_SLOWIE_CENOWYM, _GOLA_PRZED_SLOWEM_CENOWYM):
        for dopasowanie in wzorzec.finditer(tekst):
            liczba = dopasowanie.group(1)
            if _JEDNOSTKA_ZA_LICZBA.match(tekst, dopasowanie.end(1)):
                continue   # "Razem 240 cm" — wymiar, nie cena
            znormalizowana = _normalizuj_liczbe(liczba)
            try:
                if float(znormalizowana) <= _PROG_GOLEJ_KWOTY:
                    continue   # "razem 3 pozycje" — liczebnik, nie cena
            except ValueError:
                continue
            wynik.add(znormalizowana)
    return wynik


def sprawdz_ceny(tekst, znane_kwoty):
    """Kwoty z tekstu, których NIE ma wśród zwróconych przez kalkulator.

    Zaokrąglenie do pełnych złotych jest dozwolone — bot bywa proszony
    o przybliżenie, a 843,04 zł jako „około 843 zł" nie jest halucynacją.

    Sprawdzamy kwoty z walutą ORAZ gołe liczby przy słowie cenowym (U8) — bez
    tych drugich „około 2400 brutto" przechodziło bez śladu, a to najczęstsza
    forma zmyślonej ceny w audycie.
    """
    pelne_zlote = {k.split(".")[0] for k in znane_kwoty}
    naruszenia = []
    for kwota in znajdz_kwoty(tekst) | znajdz_gole_kwoty(tekst):
        if kwota in znane_kwoty:
            continue
        if kwota.endswith(".00") and kwota.split(".")[0] in pelne_zlote:
            continue
        naruszenia.append(kwota)
    return naruszenia
