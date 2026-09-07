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
from core.events import log_event

# Pola CENOTWÓRCZE — KAŻDE z nich czyta `crm_calc.build_products`, więc jego
# zmiana zmienia wynik kalkulatora. Pominięcie któregoś tutaj oznacza „zmiana
# tego pola NIE unieważnia ani podpisu, ani rejestru kwot" — każde nowe pole
# wpływające na cenę MUSI trafić do tej listy świadomie, inaczej powtórzy się
# klasa błędu #2016 (bramka przepuszcza mimo zmiany danych).
#
# JEDNA definicja dla DWÓCH mechanizmów (U6): podpisu potwierdzenia (niżej) i
# czyszczenia rejestru kwot G1 (`bots_pro.stan._zmien_pozycje` woła `odcisk_cenotworczy`).
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
_POLA_OPISOWE = ("produkt", "otwory", "ksztalt")

# `ksztalt` (U-N7) jest tu z powodu ODWROTNEGO niż reszta tej listy: klient go
# w podsumowaniu NIE zobaczy, bo pozycja z kształtem innym niż prostokąt w ogóle
# do podsumowania nie dojdzie (`podsumowanie.blokada_ksztaltu`). Pole wchodzi do
# podpisu po to, żeby domknąć jedyną drogę, którą kształt mógłby ominąć bramkę:
# klient potwierdza prostokąt -> model dopisuje ksztalt="sześciokąt" ->
# `zapisz_wycene` (które kształtu nie sprawdza, sprawdza podpis) wysyła do CRM
# wycenę sześciokąta w cenie prostokąta. Z polem w podpisie taka zmiana
# unieważnia potwierdzenie i `sprawdz_bramke` odmawia.
#
# `ksztalt` NIE jest polem CENOTWÓRCZYM, bo `odcisk_cenotworczy` odpowiada na
# pytanie „czy kalkulator policzyłby to samo" (`narzedzia.policz_wycene` używa
# go do wykrycia, że pozycje zmieniły się W TRAKCIE liczenia), a
# `crm_calc.build_products` kształtu nie czyta — wpisuje `shape: "rectangular"`
# na sztywno. Rejestr kwot G1 to jednak osobne pytanie: „czy ta kwota nadal
# opisuje tę pozycję". Odpowiedź jest NIE w chwili, gdy pozycja przestaje być
# prostokątem, więc zejście z prostokąta czyści rejestr — patrz
# `ksztalty_nieprostokatne` niżej i `stan._zmien_pozycje`.

_POLA_ISTOTNE = _POLA_CENOTWORCZE + _POLA_OPISOWE

# Pola DOSTAWY wchodzące do podpisu (U4). Osobna lista od `_POLA_ISTOTNE`, bo
# dostawa jest stanem PER ROZMOWA (`bots_pro.stan.dostawa`), nie polem pozycji —
# ale obowiązuje ją dokładnie ta sama reguła: pominięcie pola tutaj znaczy „zmiana
# tego pola NIE unieważnia potwierdzenia". Wymóg właściciela mówi wprost, że cena
# to produkt + ew. dostawa, więc zmiana kodu pocztowego, kuriera albo kosztu
# wysyłki musi wymusić nowe podsumowanie i nowe „tak" klienta.
_POLA_DOSTAWY = ("kod_pocztowy", "kurier", "netto", "brutto")

# Deklaracja kształtu z pola `ksztalt` (U-N7). Prostokątem jest pozycja, która
# pola nie ma wcale (domyślny, milczący przypadek — cały normalny ruch), albo
# ma w nim SAMO słowo prostokąt/kwadrat w dowolnej odmianie.
#
# FAIL-CLOSED I TO ŚWIADOMIE: wszystko inne — także wpis, którego nie umiemy
# odczytać („prostokąt z zaokrąglonym rogiem", „prostokat?") — jest traktowane
# jak kształt nieprostokątny i blokuje wycenę. Odwrotna konwencja (nieznane =
# prostokąt) znaczyłaby, że literówka modelu przywraca dokładnie tę cichą
# wycenę sześciokąta jak prostokąta, przed którą ta bramka ma chronić. Koszt
# pomyłki w tę stronę to jedna rozmowa oddana konsultantowi; koszt pomyłki w
# drugą to zła cena pod podpisem klienta — te dwa błędy nie ważą tyle samo.
# Docstring narzędzia mówi wprost, żeby wpisywać SAM kształt, nie opis blatu.
#
# Definicja mieszka TU, a nie przy bramce w `podsumowanie.py`, bo służy DWÓM
# mechanizmom naraz — dokładnie jak `_POLA_CENOTWORCZE` wyżej (U6): bramce
# kształtu (`podsumowanie.blokada_ksztaltu`) i czyszczeniu rejestru kwot G1
# (`stan._zmien_pozycje`). Dwie kopie tego wyrażenia rozjechałyby się przy
# pierwszej poprawce i jeden z mechanizmów cicho przestałby działać.
KSZTALT_PROSTOKATNY = re.compile(r"(?:prostok[ąa]t\w*|kwadrat\w*)", re.IGNORECASE)


def ksztalty_nieprostokatne(pozycje):
    """Zbiór identyfikatorów pozycji ZADEKLAROWANYCH jako coś innego niż
    prostokąt. Puste/brakujące pole `ksztalt` to prostokąt.

    Po co identyfikatory, a nie samo „czy jest tu nieprostokąt": wołający
    (`stan._zmien_pozycje`) porównuje zbiór SPRZED zapisu ze zbiorem PO nim i
    reaguje wyłącznie na pozycje, które właśnie PRZESTAŁY być prostokątem.
    Dzięki temu powtórzony zapis tej samej deklaracji niczego nie kasuje, a
    poprawka „jednak prostokąt" (droga wyjścia z pomyłki, którą obiecuje
    wskazówka bramki) nie unieważnia kwot policzonych wcześniej."""
    wynik = set()
    for poz in pozycje or []:
        deklaracja = str(poz.get("ksztalt") or "").strip()
        if deklaracja and not KSZTALT_PROSTOKATNY.fullmatch(deklaracja):
            wynik.add(str(poz.get("id") or ""))
    return wynik

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

# CZEGO TU CELOWO NIE MA (runda D, C1) — nie dokładać z powrotem:
# listy słów zgody („tak", „ok", „dobrze"...) ani żadnego innego wyjątku
# „nie, ale". Taki wyjątek TU BYŁ (commit `96bb162`): wiodące „nie," było
# ignorowane, gdy klauzula za nim zawierała słowo z listy zgody, a cytat
# obejmował całą resztę tej klauzuli. Rerecenzja przemyciła przez niego
# 15 fałszywych zgód — „Nie, dobrze. Proszę poprawić wymiar na 200 cm."
# (cytat „dobrze") otwierało bramkę i do CRM szła pozycja SPRZED zmiany, czyli
# dokładnie klasa błędu #2016. Przyczyna jest konstrukcyjna, nie w doborze słów:
# to test typu „worek słów" na klauzuli, która bywa całym zdaniem odmownym, bo
# treść odmowy stoi naturalnie w NASTĘPNEJ klauzuli — a polszczyzna ma
# nieskończenie wiele form „nie, ale". Warunek „cytat obejmuje resztę klauzuli"
# tego nie ratuje.
# Skutek uboczny wycofania jest ZNANY i ZAAKCEPTOWANY przez właściciela: klient
# piszący „nie, wszystko się zgadza" zostanie poproszony o potwierdzenie jeszcze
# raz. Kosztuje to jedno pytanie; fałszywa zgoda kosztuje zamówienie zapisane
# wbrew klientowi — te dwa błędy nie ważą tyle samo.

# Granice klauzul. Negacja NIE przechodzi przez taką granicę — z jednym wyjątkiem
# opisanym w `_zanegowany` (samotne "nie," tuż przed cytatem).
_SEPARATOR_KLAUZULI = re.compile(r"[,;:.!?\n—–]")

# Jawne wycofanie się klienta ORAZ zastrzeżenie do niego. Jedno i drugie NIE
# jest lokalne dla klauzuli — unieważnia CAŁĄ wypowiedź, także cytat stojący
# PRZED nim ("To za drogo, rezygnuję": model cytuje pierwszą połowę, a klient
# właśnie odszedł).
#
# D1 (rerecenzja rundy D): do czasowników rezygnacji dołączają SPÓJNIKI
# PRZECIWSTAWNE. Bramka przepuszczała zgodę CZĘŚCIOWĄ i WARUNKOWą — 29 z 34
# wypowiedzi korpusu rerecenzji ("Ok, tylko zmieńmy grubość na 6 cm." z cytatem
# „ok") otwierało ją jako pełne potwierdzenie, po czym do CRM szła wartość
# SPRZED prośby klienta. To ta sama klasa błędu co #2016, tylko innym wejściem
# niż w rundzie C, i stan zastany — żadna z czterech rund jej nie dotykała.
# Podpis treści tu NIE ratuje: model prośby klienta nie realizuje, więc pozycje
# się nie zmieniają i podpis się zgadza.
#
# Mechanizm jest ten sam co przy „rezygnuję", bo problem jest ten sam: klient
# zgłasza zastrzeżenie, a model cytuje drugą, przychylną połowę wypowiedzi.
# Zasięg musi więc być CAŁĄ wypowiedzią — lokalny (klauzulowy) nie działa,
# bo zastrzeżenie stoi naturalnie w INNEJ klauzuli niż zacytowana zgoda.
#
# Zmierzone na korpusie rerecenzji (sonda `d1e_propozycja.py`, odtworzona
# w `TestD1ZgodaCzesciowaNieOtwieraBramki`): fałszywe zgody 29/34 → 7/34,
# koszt 1 prawdziwa zgoda na 11 („myślałem, że za drogo, ALE biorę" — bot
# dopyta jeszcze raz). Wymiana jest świadoma i asymetryczna: fałszywa zgoda
# łamie wymóg właściciela („zawsze bot musi mieć potwierdzone od klienta, że
# wszystko się zgadza") i zapisuje zamówienie wbrew klientowi, fałszywa odmowa
# kosztuje jedno dodatkowe pytanie. Przy wątpliwości — odmowa.
#
# `(?!\w)` na końcu jest OBOWIĄZKOWE, nie kosmetyką: bez niego „ale" łapie
# „alergię" i „Aleję", „poza" — „pozamiatane", a „lecz" — „lecznicze", czyli
# cztery fałszywe odmowy na wypowiedziach będących zwykłymi zgodami
# (zmierzone). Pomiar 7/34 i 1/11 jest przy domknięciu IDENTYCZNY.
#
# Nowe wpisy dodawać wyłącznie świadomie i tylko na SPÓJNIKI/PRZYIMKI
# zastrzeżenia. Poszerzanie o słowa TREŚCIOWE (np. „za drogo") zjadałoby
# prawdziwe zgody; wyjątki typu „nie, ale" oparte na worku słów zostały już
# raz cofnięte w rundzie D (C1) — patrz komentarz przy `_NEGACJE`.
_ODMOWY = re.compile(
    r"(?<!\w)(?:rezygn\w*|odmawiam|anuluj\w*|wycofuj\w*|odst[ęe]puj\w*|"
    r"(?:ale|tylko|jedynie|cho[ćc]|chocia[żz]|jednak|natomiast|lecz|poza|"
    r"opr[óo]cz|z wyj[ąa]tkiem|pod warunkiem|za to|cz[ęe][śs]ciowo)(?!\w))",
    re.IGNORECASE)


def odcisk_cenotworczy(pozycje):
    """Kanoniczny obraz pozycji OGRANICZONY do pól cenotwórczych (U6).

    `bots_pro.stan._zmien_pozycje` porównuje ten odcisk sprzed i po zapisie, żeby
    zdecydować, czy wyczyścić rejestr kwot G1. Mieszka tutaj, a nie w `stan`,
    bo to ta sama definicja „co zmienia cenę", której używa podpis — dwie
    kopie tej listy rozjechałyby się przy pierwszym nowym polu."""
    istotne = [
        {k: p.get(k) for k in _POLA_CENOTWORCZE if k in p}
        for p in sorted(pozycje or [], key=lambda x: str(x.get("id")))
    ]
    return json.dumps(istotne, ensure_ascii=False, sort_keys=True)


def kwota_nadal_opisuje(stare_pozycje, nowe_pozycje):
    """Czy kwota policzona dla `stare_pozycje` nadal opisuje `nowe_pozycje`.

    JEDNA definicja predykatu „czy ta kwota nadal obowiązuje", wołana ze
    WSZYSTKICH trzech miejsc, które to pytanie zadają:
      - `stan._zmien_pozycje` — czy zapis pozycji ma wyczyścić rejestr G1,
      - `narzedzia.policz_wycene` — czy wolno zarejestrować kwotę, która
        wróciła z kalkulatora PO tym, jak pozycje mogły się już zmienić,
      - `podsumowanie.wyslij` — to samo pytanie dla drugiej funkcji wołającej
        kalkulator.

    Definicje BYŁY DWIE i się rozjechały, i to jest cały powód, dla którego ta
    funkcja istnieje: `_zmien_pozycje` liczyło zejście z prostokąta, a
    `policz_wycene` patrzyło WYŁĄCZNIE na odcisk cenotwórczy — a `ksztalt`
    polem cenotwórczym świadomie nie jest. Deklaracja kształtu, która trafiła
    do bazy w trakcie liczenia (okno = całe `crm_calc.calculate`, HTTP z
    timeoutem 30 s, świadomie poza zamkiem), była więc dla tej kontroli
    NIEWIDZIALNA: cena prostokąta wchodziła do rejestru G1 dla pozycji, która
    w bazie miała już `ksztalt="sześciokąt"`, i guardrail pozwalał ją
    wypowiedzieć klientowi jako prawdziwą (rozmowa 4727, sześciokąt 87x75).

    DWA CZŁONY, bo to dwa różne pytania (patrz komentarz przy `ksztalt` wyżej):
      1. odcisk cenotwórczy — „czy kalkulator policzyłby to samo";
      2. zejście z prostokąta — „czy ta kwota nadal opisuje tę pozycję", mimo
         że kalkulator policzyłby identycznie, bo kształtu nie czyta.

    Człon drugi to różnica ZBIORÓW, nie pytanie „czy jest tu nieprostokąt":
    reagujemy wyłącznie na pozycje, które WŁAŚNIE przestały być prostokątem.
    Powtórzona deklaracja tego samego kształtu niczego nie unieważnia (N1),
    a poprawka „jednak prostokąt" tym bardziej — tam kwota znów obowiązuje."""
    return (odcisk_cenotworczy(stare_pozycje) == odcisk_cenotworczy(nowe_pozycje)
            and not (ksztalty_nieprostokatne(nowe_pozycje)
                     - ksztalty_nieprostokatne(stare_pozycje)))


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
    odmowa, tylko z przecinkiem w środku. Dosięga ZAWSZE, także gdy dalsza część
    klauzuli brzmi jak zgoda: uzasadnienie w komentarzu przy `_NEGACJE` (C1)."""
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

    C1 (runda D): wiodące "nie," neguje cytat z następnej klauzuli ZAWSZE, także
    gdy ta klauzula brzmi jak zgoda ("nie, wszystko się zgadza" — bot dopyta
    jeszcze raz). Wyjątek, który to przepuszczał, został wycofany razem z
    listą słów zgody; powód i koszt opisuje komentarz przy `_NEGACJE`.

    D1 (rerecenzja rundy D): `_ODMOWY` obejmuje też SPÓJNIKI PRZECIWSTAWNE, więc
    zgoda CZĘŚCIOWA i WARUNKOWA nie jest już pełnym potwierdzeniem — "Ok, tylko
    zmieńmy grubość na 6 cm." (cytat "ok") i "Zamawiam pod warunkiem, że
    zmienicie termin." są odrzucane. Zasięg jest CAŁĄ wypowiedzią, bo
    zastrzeżenie stoi naturalnie w innej klauzuli niż zacytowana zgoda.

    Czego to NADAL nie łapie (świadomie): oceny semantycznej. "A ile to potrwa?"
    zacytowane jako zgoda przejdzie — fragment naprawdę jest w wiadomości i nie ma
    w niej ani negacji, ani rezygnacji, ani zastrzeżenia. Tak samo przechodzi
    zastrzeżenie postawione BEZ spójnika, w osobnym zdaniu ("Zgadzam się co do
    ceny. Termin za długi.") albo w pytaniu ("Czy wszystko się zgadza?") — siedem
    takich form na korpusie rerecenzji, wymienionych w
    `TestD1ZgodaCzesciowaNieOtwieraBramki`. To ograniczenie mechanizmu opartego
    na dosłownym cytacie, nie luka do zamknięcia regexem.
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
    # T1 (telemetria lejka): `confirmed` — ta sama nazwa co w starym silniku.
    # PO zapisie podpisu, nie przed: inwariant I2 mówi, że potwierdzenie jest
    # przypięte do PODPISU TREŚCI, a nie do faktu wywołania narzędzia, więc
    # zdarzenie ma opisywać potwierdzenie, które naprawdę wylądowało w
    # `pro_stan`. Obie ścieżki odrzucenia wyżej robią `return` przed tym
    # miejscem, więc na jedno udane `potwierdz` przypada dokładnie jedno
    # zdarzenie. Zero zmian w samej bramce I2 — to wyłącznie obserwacja.
    log_event(stan.conv_id(), "confirmed")
    return {"ok": True, "podpis": biezacy}


def sprawdz_bramke(pozycje=None, dostawa=None):
    """Czy wolno zapisać wycenę albo podać link do zamówienia.

    K2: wołający, który zaraz WYŚLE dane dalej (do CRM, a stamtąd pod link
    klienta i do zamówienia w BaseLinkerze), MUSI podać dokładnie tę migawkę,
    którą wyśle — `stan.migawka()`. Bez tego bramka liczyła podpis z WŁASNEGO
    odczytu, a `create_quote`/`update_quote` dostawały DRUGI, niezależny —
    między nimi nie było zamka, więc równoległy `zapisz_pozycje` z tego samego
    kroku modelu wchodził w środek. Inwariant I2 mówi „nic dalej bez
    potwierdzenia przypiętego do PODPISU TREŚCI"; sprawdzanie jednej treści
    i wysyłanie innej jest złamaniem tego zdania, nawet gdy obie są poprawne
    z osobna. ZMIERZONE: klient potwierdził blat 180 cm, do CRM szło 300 cm
    w 10/15 przebiegów przy samym oknie bramka->odczyt, bez żadnego
    złośliwego przeplotu.

    Argumenty domyślne (`None`) znaczą „policz podpis z bieżącego stanu" — tak
    woła `przygotuj_zamowienie`, które niczego do CRM nie wysyła: pyta
    wyłącznie o link do wyceny JUŻ tam zapisanej, więc nie ma migawki, którą
    miałoby przypiąć."""
    zapisany, cytat = _stan_potwierdzenia()
    if not zapisany:
        return {"ok": False, "error": "BRAK_POTWIERDZENIA",
                "wskazowka": "Najpierw wyślij podsumowanie i poczekaj, aż klient je potwierdzi."}

    biezacy = podpis(pozycje, dostawa) if pozycje is not None else _biezacy_podpis()
    if zapisany != biezacy:
        return {"ok": False, "error": "POTWIERDZENIE_NIEAKTUALNE",
                "wskazowka": "Dane zmieniły się po potwierdzeniu. Wyślij nowe podsumowanie "
                             "i poproś o ponowne potwierdzenie."}

    return {"ok": True, "cytat": cytat}
