# -*- coding: utf-8 -*-
"""
Guardraile wyjściowe — kontrola odpowiedzi PRZED wysłaniem do klienta.

G1 (integralność ceny) jest jedynym guardrailem od pierwszego dnia. Kolejne
dokładamy dopiero, gdy dane z produkcji pokażą, że są potrzebne — nie na zapas.
"""
import re

# Kwota = liczba z opcjonalnym separatorem tysięcy i walutą tuż za nią.
# Waluta jest OBOWIĄZKOWA — bez niej „14 dni" i „120x60x4" wpadałyby jako ceny.
_KWOTA_RE = re.compile(
    r"(\d{1,3}(?:[  ]\d{3})*|\d+)(?:[,.](\d{2}))?\s*(?:zł|zl|PLN|pln)\b"
)


def znajdz_kwoty(tekst):
    """Zbiór kwot w tekście, znormalizowanych do 'NNNN.GG'."""
    wynik = set()
    for calosc, grosze in _KWOTA_RE.findall(tekst or ""):
        zlote = calosc.replace(" ", "").replace(" ", "")
        wynik.add("%s.%s" % (zlote, grosze if grosze else "00"))
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
