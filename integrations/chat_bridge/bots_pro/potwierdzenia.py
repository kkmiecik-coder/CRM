# -*- coding: utf-8 -*-
"""
Inwariant I2: nic nie idzie dalej bez potwierdzenia klienta.

Stary silnik miał flagę awaiting_confirm — mówiła, ŻE potwierdzenie było, ale nie
mówiła, CZEGO dotyczyło. Rozmowa #2016 z audytu: klient zmienił grubość, potwierdził
podsumowanie, a w CRM wylądowała wycena sprzed zmiany. Dlatego potwierdzamy PODPIS
TREŚCI: każda zmiana pozycji po potwierdzeniu unieważnia je automatycznie.

I2 działa w OBIE STRONY, bo dane mogą zmienić się w dwóch różnych oknach czasowych:
  1. między wysłaniem podsumowania a odpowiedzią klienta (`potwierdz` porównuje
     bieżące pozycje z `oczekiwany_podpis` zapisanym przez `podsumowanie.wyslij`),
  2. między potwierdzeniem a faktycznym zapisem/wysłaniem linku (`sprawdz_bramke`
     porównuje bieżące pozycje z `potwierdzony_podpis` zapisanym przez `potwierdz`).
Bez strony (1) model mógłby w tej samej turze zmienić dane PO złożeniu podsumowania,
a klienckie „Tak" podpisałoby zmienione dane, których klient nigdy nie widział.
"""
import hashlib
import json
import re
import time

from core.db import db

# Pola cenotwórcze — KAŻDE z nich zmienia wynik kalkulatora, więc pominięcie
# któregoś tutaj oznacza „nie unieważniaj podpisu przy zmianie tego pola". Każde
# nowe pole wpływające na cenę MUSI trafić do tej listy świadomie — inaczej
# powtórzy się klasa błędu #2016 (bramka przepuszcza mimo zmiany danych).
_POLA_ISTOTNE = ("id", "produkt", "dlugosc", "szerokosc", "grubosc", "ilosc",
                 "selected_variant", "gatunek", "technologia", "klasa",
                 "wykonczenie", "finishing_id", "edges", "otwory")

# Cytat musi mieć sensowną długość — pojedynczy znak interpunkcyjny ("." wyrwane
# z końca zdania klienta) nie jest potwierdzeniem.
_MIN_DLUGOSC_CYTATU = 2
# Słowa, które TUŻ PRZED cytowanym fragmentem odwracają jego sens — "nie potwierdzam"
# nie jest potwierdzeniem, mimo że słowo "potwierdzam" faktycznie pada w wiadomości.
_NEGACJE = {"nie", "bez", "niestety"}


def podpis(pozycje):
    """Stabilny odcisk tego, co klient potwierdza."""
    istotne = [
        {k: p.get(k) for k in _POLA_ISTOTNE if k in p}
        for p in sorted(pozycje or [], key=lambda x: str(x.get("id")))
    ]
    material = json.dumps(istotne, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _znormalizuj(tekst):
    return (tekst or "").strip().lower()


def _slowo_przed(tekst, pozycja):
    """Ostatnie słowo w tekście PRZED podaną pozycją — do wykrycia negacji tuż
    przed cytatem ("nie zgadzam się" — słowo przed "zgadzam się" to "nie")."""
    dopasowanie = re.search(r"(\w+)\s*$", tekst[:pozycja])
    return dopasowanie.group(1) if dopasowanie else ""


def sprawdz_cytat(cytat, ostatnia_wiadomosc_klienta):
    """Czy cytat dosłownie występuje w ostatniej wiadomości klienta — i NIE jest
    częścią odmowy ("nie potwierdzam", "nie zgadzam się na tę cenę").

    To jest zabezpieczenie przed zgodą, której nie było: model nie może wymyślić
    potwierdzenia, bo musi wskazać fragment realnego tekstu. Dopasowanie idzie na
    granicach słów (żeby "tak" nie trafiało w środek "taka" ani "kontakt"), wymaga
    sensownej długości cytatu, i odrzuca dopasowanie, przed którym stoi negacja —
    inaczej cytat "potwierdzam" wyłowiony z "nie potwierdzam, proszę o korektę"
    przepchnąłby zgodę, której klient nie wyraził.
    """
    fragment = _znormalizuj(cytat)
    tekst = _znormalizuj(ostatnia_wiadomosc_klienta)
    if not fragment or not tekst or len(fragment) < _MIN_DLUGOSC_CYTATU:
        return False
    wzorzec = re.compile(r"(?<!\w)%s(?!\w)" % re.escape(fragment))
    for dopasowanie in wzorzec.finditer(tekst):
        if _slowo_przed(tekst, dopasowanie.start()) not in _NEGACJE:
            return True
    return False


def _biezace_pozycje():
    from bots_pro import stan
    return stan.pozycje()


def _stan_potwierdzenia():
    """(potwierdzony_podpis, cytat) dla bieżącej rozmowy."""
    from bots_pro import stan
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT potwierdzony_podpis, potwierdzenie_cytat FROM pro_stan WHERE conv_id=?",
            (stan.conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    if not wiersz:
        return (None, None)
    return (wiersz["potwierdzony_podpis"], wiersz["potwierdzenie_cytat"])


def _oczekiwany_podpis():
    """Podpis pozycji z chwili WYSŁANIA podsumowania (zapisany przez
    `podsumowanie.wyslij`) — to jest podpis tego, co klient FAKTYCZNIE widział."""
    from bots_pro import stan
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT oczekiwany_podpis FROM pro_stan WHERE conv_id=?",
            (stan.conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["oczekiwany_podpis"] if wiersz else None


def potwierdz(cytat_klienta):
    """Rejestruje zgodę klienta na pozycje pokazane w ostatnim podsumowaniu.

    Podpisujemy `oczekiwany_podpis` (co klient WIDZIAŁ w podsumowaniu), nie
    podpis pozycji z chwili wołania tego narzędzia — gdyby model zdążył w tej
    samej turze po cichu zmienić dane między podsumowaniem a potwierdzeniem,
    "Tak" klienta podpisałoby dane, których klient nigdy nie zobaczył."""
    from bots_pro import stan
    ostatnia = stan.ostatnia_wiadomosc_klienta()
    if not sprawdz_cytat(cytat_klienta, ostatnia):
        return {"ok": False, "error": "CYTAT_SPOZA_WIADOMOSCI",
                "wskazowka": "Podaj dosłowny fragment ostatniej wiadomości klienta. "
                             "Jeśli klient nie potwierdził — nie wołaj tego narzędzia."}

    oczekiwany = _oczekiwany_podpis()
    biezacy = podpis(_biezace_pozycje())
    if not oczekiwany or oczekiwany != biezacy:
        return {"ok": False, "error": "DANE_ZMIENIONE_OD_PODSUMOWANIA",
                "wskazowka": "Dane zmieniły się od wysłania podsumowania (albo podsumowanie "
                             "nie zostało jeszcze wysłane). Wyślij (nowe) podsumowanie i "
                             "poproś o ponowne potwierdzenie."}

    stan.zapisz_stan(potwierdzony_podpis=biezacy, potwierdzenie_cytat=cytat_klienta,
                     potwierdzenie_ts=time.time())
    return {"ok": True, "podpis": biezacy}


def sprawdz_bramke():
    """Czy wolno zapisać wycenę albo podać link do zamówienia."""
    zapisany, cytat = _stan_potwierdzenia()
    if not zapisany:
        return {"ok": False, "error": "BRAK_POTWIERDZENIA",
                "wskazowka": "Najpierw wyślij podsumowanie i poczekaj, aż klient je potwierdzi."}

    if zapisany != podpis(_biezace_pozycje()):
        return {"ok": False, "error": "POTWIERDZENIE_NIEAKTUALNE",
                "wskazowka": "Dane zmieniły się po potwierdzeniu. Wyślij nowe podsumowanie "
                             "i poproś o ponowne potwierdzenie."}

    return {"ok": True, "cytat": cytat}
