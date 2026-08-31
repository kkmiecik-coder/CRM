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

# Pola CENOTWÓRCZE — KAŻDE z nich czyta `crm_calc.build_products`, więc jego
# zmiana zmienia wynik kalkulatora. Pominięcie któregoś tutaj oznacza „zmiana
# tego pola NIE unieważnia ani podpisu, ani rejestru kwot" — każde nowe pole
# wpływające na cenę MUSI trafić do tej listy świadomie, inaczej powtórzy się
# klasa błędu #2016 (bramka przepuszcza mimo zmiany danych).
#
# JEDNA definicja dla DWÓCH mechanizmów (U6): podpisu potwierdzenia (niżej) i
# czyszczenia rejestru kwot G1 (`bots_pro.stan._zapisz` woła `odcisk_cenotworczy`).
# Wcześniej rejestr czyścił się przy zmianie DOWOLNEGO pola `dane_json`, więc
# dopisanie otworu — pola jawnie NIEWYCENIANEGO — kasowało prawdziwe ceny i
# guardrail zgłaszał je jako halucynację.
_POLA_CENOTWORCZE = ("id", "dlugosc", "szerokosc", "grubosc", "ilosc",
                     "selected_variant", "gatunek", "technologia", "klasa",
                     "wykonczenie", "finishing_id", "edges")

# Pola OPISOWE — ceny NIE zmieniają (`build_products` ich nie czyta), ale klient
# widzi je w podsumowaniu, więc wchodzą do PODPISU: zmiana nazwy produktu albo
# listy otworów po potwierdzeniu ma wymagać nowego „tak", choć rejestr kwot
# zostaje nietknięty (cena się nie zmieniła).
_POLA_OPISOWE = ("produkt", "otwory")

_POLA_ISTOTNE = _POLA_CENOTWORCZE + _POLA_OPISOWE

# Pola DOSTAWY wchodzące do podpisu (U4). Osobna lista od `_POLA_ISTOTNE`, bo
# dostawa jest stanem PER ROZMOWA (`bots_pro.stan.dostawa`), nie polem pozycji —
# ale obowiązuje ją dokładnie ta sama reguła: pominięcie pola tutaj znaczy „zmiana
# tego pola NIE unieważnia potwierdzenia". Wymóg właściciela mówi wprost, że cena
# to produkt + ew. dostawa, więc zmiana kodu pocztowego, kuriera albo kosztu
# wysyłki musi wymusić nowe podsumowanie i nowe „tak" klienta.
_POLA_DOSTAWY = ("kod_pocztowy", "kurier", "netto", "brutto")

# Cytat musi mieć sensowną długość — pojedynczy znak interpunkcyjny ("." wyrwane
# z końca zdania klienta) nie jest potwierdzeniem.
_MIN_DLUGOSC_CYTATU = 2
# Cząstki negujące. Działają LOKALNIE — na KLAUZULI, w której stoją, nie na
# jednym następnym słowie (U5, recenzja końcowa). "Nie zgadzam się na tę cenę"
# jest odmową w całości, więc cytat wyjęty z jej środka ("się na tę cenę") NIE
# jest zgodą — a właśnie tak działała poprzednia wersja, patrząc wyłącznie na
# słowo bezpośrednio przed cytatem. Zasięg klauzuli (a nie całej wypowiedzi) jest
# tu istotny w DRUGĄ stronę: "nie zmieniam nic, potwierdzam" to ZGODA — tam "nie"
# neguje "zmieniam", nie "potwierdzam" zza przecinka.
_NEGACJE = {"nie", "bez", "niestety"}

# Granice klauzul. Negacja NIE przechodzi przez taką granicę — z jednym wyjątkiem
# opisanym w `_zanegowany` (samotne "nie," tuż przed cytatem).
_SEPARATOR_KLAUZULI = re.compile(r"[,;:.!?\n—–]")

# Jawne wycofanie się klienta. W odróżnieniu od negacji NIE jest lokalne dla
# klauzuli — unieważnia CAŁĄ wypowiedź, także cytat stojący PRZED nim ("To za
# drogo, rezygnuję": model cytuje pierwszą połowę, a klient właśnie odszedł).
# Lista jest CELOWO wąska i dotyczy tylko jednoznacznych czasowników rezygnacji —
# szersza (np. "za drogo") zjadałaby prawdziwe zgody w rodzaju "myślałem, że za
# drogo, ale biorę". Nowe wpisy dodawać wyłącznie świadomie: fałszywa odmowa
# kosztuje rundę rozmowy, fałszywa zgoda łamie inwariant I2.
_ODMOWY = re.compile(
    r"(?<!\w)(?:rezygn\w*|odmawiam|anuluj\w*|wycofuj\w*|odst[ęe]puj\w*)", re.IGNORECASE)


def odcisk_cenotworczy(pozycje):
    """Kanoniczny obraz pozycji OGRANICZONY do pól cenotwórczych (U6).

    `bots_pro.stan._zapisz` porównuje ten odcisk sprzed i po zapisie, żeby
    zdecydować, czy wyczyścić rejestr kwot G1. Mieszka tutaj, a nie w `stan`,
    bo to ta sama definicja „co zmienia cenę", której używa podpis — dwie
    kopie tej listy rozjechałyby się przy pierwszym nowym polu."""
    istotne = [
        {k: p.get(k) for k in _POLA_CENOTWORCZE if k in p}
        for p in sorted(pozycje or [], key=lambda x: str(x.get("id")))
    ]
    return json.dumps(istotne, ensure_ascii=False, sort_keys=True)


def podpis(pozycje, dostawa=None):
    """Stabilny odcisk tego, co klient potwierdza — pozycje ORAZ dostawa (U4)."""
    istotne = [
        {k: p.get(k) for k in _POLA_ISTOTNE if k in p}
        for p in sorted(pozycje or [], key=lambda x: str(x.get("id")))
    ]
    istotna_dostawa = {k: (dostawa or {}).get(k)
                       for k in _POLA_DOSTAWY if k in (dostawa or {})}
    material = json.dumps({"pozycje": istotne, "dostawa": istotna_dostawa},
                          ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _znormalizuj(tekst):
    return (tekst or "").strip().lower()


def _slowa(fragment):
    return re.findall(r"\w+", fragment or "")


def _zanegowany(tekst, pozycja):
    """Czy cytat zaczynający się w `pozycja` stoi w klauzuli, którą klient zanegował.

    Patrzymy na CAŁĄ klauzulę przed cytatem, nie na jedno słowo (U5): w "Nie
    zgadzam się na tę cenę" cytat "się na tę cenę" ma przed sobą "Nie zgadzam" —
    negacja jest o dwa słowa dalej, ale neguje całą tę wypowiedź.

    Klauzula kończy się na przecinku/średniku/kropce — dzięki temu "nie zmieniam
    nic, potwierdzam" pozostaje ZGODĄ ("nie" neguje "zmieniam", nie "potwierdzam").
    WYJĄTEK: gdy cytat zaczyna nową klauzulę, a poprzednia to SAMA negacja
    ("nie, tak nie może być"), negacja jednak go dosięga — to nadal ta sama
    odmowa, tylko z przecinkiem w środku (N2 z poprzedniej rundy)."""
    przed = tekst[:pozycja]
    granice = list(_SEPARATOR_KLAUZULI.finditer(przed))
    if not granice:
        return any(s in _NEGACJE for s in _slowa(przed))

    ostatnia = granice[-1]
    klauzula = przed[ostatnia.end():]
    slowa_klauzuli = _slowa(klauzula)
    if slowa_klauzuli:
        return any(s in _NEGACJE for s in slowa_klauzuli)

    poczatek_poprzedniej = granice[-2].end() if len(granice) > 1 else 0
    poprzednia = _slowa(przed[poczatek_poprzedniej:ostatnia.start()])
    return len(poprzednia) == 1 and poprzednia[0] in _NEGACJE


def sprawdz_cytat(cytat, ostatnia_wiadomosc_klienta):
    """Czy cytat dosłownie występuje w ostatniej wiadomości klienta — i NIE jest
    częścią odmowy ("nie potwierdzam", "nie zgadzam się na tę cenę").

    To jest zabezpieczenie przed zgodą, której nie było: model nie może wymyślić
    potwierdzenia, bo musi wskazać fragment realnego tekstu. Dopasowanie idzie na
    granicach słów (żeby "tak" nie trafiało w środek "taka" ani "kontakt"), wymaga
    sensownej długości cytatu, i odrzuca dopasowanie, którego klauzula jest
    zanegowana — inaczej cytat "potwierdzam" wyłowiony z "nie potwierdzam, proszę
    o korektę" (albo "się na tę cenę" z "Nie zgadzam się na tę cenę") przepchnąłby
    zgodę, której klient nie wyraził.

    U5 (recenzja końcowa): dwie zmiany zakresu wobec poprzedniej wersji. (1)
    negacja jest szukana w CAŁEJ klauzuli przed cytatem, nie w jednym słowie —
    przesunięcie początku cytatu o słowo nie omija już bramki. (2) jawne
    wycofanie się klienta (`_ODMOWY`) unieważnia całą wypowiedź, także cytat
    stojący PRZED nim — "To za drogo, rezygnuję" nie jest zgodą w żadnej swojej
    połowie.

    Czego to NADAL nie łapie (świadomie): oceny semantycznej. "A ile to potrwa?"
    zacytowane jako zgoda przejdzie — fragment naprawdę jest w wiadomości i nie ma
    w niej ani negacji, ani rezygnacji. To ograniczenie mechanizmu opartego na
    dosłownym cytacie, nie luka do zamknięcia regexem.
    """
    fragment = _znormalizuj(cytat)
    tekst = _znormalizuj(ostatnia_wiadomosc_klienta)
    if not fragment or not tekst or len(fragment) < _MIN_DLUGOSC_CYTATU:
        return False
    if _ODMOWY.search(tekst):
        return False
    wzorzec = re.compile(r"(?<!\w)%s(?!\w)" % re.escape(fragment))
    for dopasowanie in wzorzec.finditer(tekst):
        if not _zanegowany(tekst, dopasowanie.start()):
            return True
    return False


def _biezace_pozycje():
    from bots_pro import stan
    return stan.pozycje()


def _biezaca_dostawa():
    from bots_pro import stan
    return stan.dostawa()


def _biezacy_podpis():
    """Podpis BIEŻĄCEGO stanu rozmowy — pozycje + dostawa. Jedno miejsce, żeby
    `potwierdz` i `sprawdz_bramke` nie rozjechały się co do zakresu podpisu."""
    return podpis(_biezace_pozycje(), _biezaca_dostawa())


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
    biezacy = _biezacy_podpis()
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

    if zapisany != _biezacy_podpis():
        return {"ok": False, "error": "POTWIERDZENIE_NIEAKTUALNE",
                "wskazowka": "Dane zmieniły się po potwierdzeniu. Wyślij nowe podsumowanie "
                             "i poproś o ponowne potwierdzenie."}

    return {"ok": True, "cytat": cytat}
