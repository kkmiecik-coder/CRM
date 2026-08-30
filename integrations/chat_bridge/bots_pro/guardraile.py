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


def sprawdz_ceny(tekst, znane_kwoty):
    """Kwoty z tekstu, których NIE ma wśród zwróconych przez kalkulator.

    Zaokrąglenie do pełnych złotych jest dozwolone — bot bywa proszony
    o przybliżenie, a 843,04 zł jako „około 843 zł" nie jest halucynacją.
    """
    pelne_zlote = {k.split(".")[0] for k in znane_kwoty}
    naruszenia = []
    for kwota in znajdz_kwoty(tekst):
        if kwota in znane_kwoty:
            continue
        if kwota.endswith(".00") and kwota.split(".")[0] in pelne_zlote:
            continue
        naruszenia.append(kwota)
    return naruszenia
