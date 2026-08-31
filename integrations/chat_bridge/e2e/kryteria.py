# -*- coding: utf-8 -*-
"""
Automatyczne kryteria oceny odtworzonej rozmowy (Task 9: harness ewaluacyjny).

Zestaw z brief'u zadania (powtórzona formułka, obecność wyjścia, zgodność
kwot) jest tu rozszerzony o CZTERY dodatkowe metryki — rozstrzygnięcie
właściciela zadania, które nadpisuje brief: brief mierzy TYLKO to, czy
rozmowa się nie zapętliła i czy dostała jakieś wyjście, ale nie daje niczego,
co pozwoliłoby porównać dwa silniki (OpenAI vs Anthropic) LICZBOWO, a nie na
wyczucie. Dokładamy więc: trafność routingu, handoffy na 100 rozmów, koszt
rozmowy (z `usage` zwracanego przez Agents SDK) i p95 czasu tury.

Wszystkie funkcje tutaj są CZYSTE — bez efektów ubocznych, bez zależności od
`agents`/Chatwoota/sieci — operują wyłącznie na już zebranych danych (listach
odpowiedzi, obiektach/dictach Usage, listach czasów). Dzięki temu dają się
testować (i używać) bez zainstalowanego SDK. Samo ZBIERANIE tych danych z
żywej rozmowy należy do `e2e/replay.py::odtworz`.
"""
import math


def powtorzone_formulki(odpowiedzi):
    """Ile razy bot powtórzył DOKŁADNIE tę samą odpowiedź (po normalizacji
    białych znaków i wielkości liter — audyt pokazał powtórki różniące się
    tylko formatowaniem). Wprost z trybów awarii audytu: 65 wystąpień w 21
    rozmowach — klient dostawał ten sam tekst po raz drugi/trzeci, bez
    żadnego postępu w rozmowie."""
    widziane = set()
    powtorki = 0
    for odpowiedz in odpowiedzi or []:
        klucz = " ".join((odpowiedz or "").split()).lower()
        if not klucz:
            continue
        if klucz in widziane:
            powtorki += 1
        else:
            widziane.add(klucz)
    return powtorki


def zawiera_link(odpowiedzi):
    """Czy KTÓRAKOLWIEK odpowiedź niesie link (np. do zapisanej wyceny/
    checkoutu) — jeden z dwóch legalnych „wyjść" z rozmowy obok handoffu."""
    for odpowiedz in odpowiedzi or []:
        tekst = odpowiedz or ""
        if "http://" in tekst or "https://" in tekst:
            return True
    return False


def zakonczona_poprawnie(odpowiedzi, handoff, link):
    """Rozmowa ma WYJŚCIE: albo trafiła do człowieka, albo klient dostał
    link. Wprost z audytu: leady ginęły w statusie 'pending' bez żadnego z
    tych dwóch — klient zostawał sam na sam z botem, który nie miał już nic
    do zaproponowania (ślepa uliczka)."""
    return bool(handoff or link)


def trafnosc_routingu(pary):
    """Ułamek trafień w liście par (oczekiwany_agent, faktyczny_agent).

    Generyczna i czysta — nie zakłada, SKĄD `oczekiwany` pochodzi (etykieta
    ręcznie przypisana do scenariusza testowego, oznaczony podzbiór audytu...).
    Realne transkrypty audytu NIE niosą etykiety „który agent SDK powinien
    odpowiedzieć" — to surowy tekst rozmowy, nie oznaczenie routingu — więc
    `replay.py` NIE woła tej funkcji dla nich wprost, tylko raportuje SUROWĄ
    trasę (którego agenta faktycznie użyto). Funkcja i tak jest tu, publiczna
    i przetestowana — do użycia z każdym źródłem etykiet, jakie kiedyś powstanie
    (np. ręcznie oznaczony podzbiór audytu).

    Zwraca None dla pustej listy — brak pomiaru to NIE 0% trafności, tylko
    „nie zmierzono", żeby te dwa stany nie zlewały się w raporcie."""
    pary = list(pary or [])
    if not pary:
        return None
    trafienia = sum(1 for oczekiwany, faktyczny in pary if oczekiwany == faktyczny)
    return trafienia / len(pary)


def handoffy_na_100(liczba_rozmow, liczba_handoffow):
    """Handoffy przeliczone na 100 rozmów — porównywalne niezależnie od
    wielkości przebiegu (cały audyt 117 rozmów, jego podzbiór, inny korpus
    w przyszłości). 0.0 gdy `liczba_rozmow` == 0 (brak danych, nie dzielenie
    przez zero)."""
    if not liczba_rozmow:
        return 0.0
    return 100.0 * liczba_handoffow / liczba_rozmow


# Brak realnych cenników dla modeli używanych w tym projekcie — identyfikatory
# per-rola (np. 'gpt-5.6-terra', 'litellm/anthropic/claude-sonnet-5', patrz
# bots_pro/models.py) to WEWNĘTRZNA konfiguracja bez publicznego cennika w tym
# repo. Domyślny cennik liczy więc PROXY porównawcze: koszt = suma tokenów
# (wejście+wyjście), stawka 1.0/token — użyteczne do porównania DWÓCH
# przebiegów tego samego korpusu (mniej/więcej tokenów = taniej/drożej), nie
# realna kwota w żadnej walucie. Podaj własny `cennik` (np.
# {"input": 0.000003, "output": 0.000015} — USD za token), żeby dostać
# rzeczywistą kwotę — jednostka wyniku jest wtedy taka sama jak jednostka
# podanych stawek.
CENNIK_DOMYSLNY = {"input": 1.0, "output": 1.0}


def _liczba_tokenow(uzycie, pole):
    """Odczyt pola z obiektu (kształt agents.usage.Usage — atrybuty) LUB
    dict (syntetyczne dane testowe/fixture) — obie postaci mają być
    obsłużone bez zależności od SDK w samych kryteriach."""
    if uzycie is None:
        return 0
    if isinstance(uzycie, dict):
        return uzycie.get(pole, 0) or 0
    return getattr(uzycie, pole, 0) or 0


def koszt_rozmowy(uzycia, cennik=None):
    """Sumaryczny koszt (proxy tokenowe albo realna kwota, zależnie od
    `cennik`) WSZYSTKICH wywołań modelu w JEDNEJ rozmowie — jedna tura może
    wywołać Runner.run_sync więcej niż raz (korekta guardraila G1), stąd
    `uzycia` to LISTA. Brak/None traktowany jak pusta lista (koszt 0.0)."""
    stawki = cennik or CENNIK_DOMYSLNY
    suma = 0.0
    for uzycie in uzycia or []:
        suma += _liczba_tokenow(uzycie, "input_tokens") * stawki.get("input", 0.0)
        suma += _liczba_tokenow(uzycie, "output_tokens") * stawki.get("output", 0.0)
    return suma


def p95_czas(czasy):
    """95. percentyl listy czasów trwania tur (sekundy), metodą
    "nearest-rank" (bez zależności od numpy, łatwa do ręcznej weryfikacji w
    teście — w odróżnieniu od interpolowanych wariantów `statistics.quantiles`,
    które przy różnych metodach dają różne wyniki dla tych samych danych).
    None dla pustej listy — brak tur, brak pomiaru."""
    wartosci = sorted(t for t in (czasy or []) if t is not None)
    if not wartosci:
        return None
    indeks = math.ceil(0.95 * len(wartosci)) - 1
    indeks = min(max(indeks, 0), len(wartosci) - 1)
    return wartosci[indeks]


def ocen(rozmowa, odpowiedzi, handoff=False, link=None, kwoty_niezgodne=0,
         trasa=None, oczekiwana_trasa=None, uzycia=None, czasy_tur=None):
    """Zbiorcza ocena JEDNEJ odtworzonej rozmowy — pola z brief'u
    (id/tur/powtorki/ma_wyjscie/kwoty_niezgodne) plus cztery metryki
    rozszerzenia opisane w nagłówku modułu.

    `link=None` (domyślnie) liczy obecność linku automatycznie z `odpowiedzi`
    (`zawiera_link`) — jawne True/False nadpisuje, dla wywołań, które już
    wiedzą to inaczej (np. testy, albo profil kanału bez linków wcale).

    `trafnosc_routingu` pojawia się w wyniku TYLKO gdy podano
    `oczekiwana_trasa` — dla realnych transkryptów audytu (bez etykiety)
    ten klucz świadomie nie istnieje, zamiast fałszywie sugerować pomiar,
    którego nie było (patrz docstring `trafnosc_routingu`)."""
    if link is None:
        link = zawiera_link(odpowiedzi)
    wynik = {
        "id": rozmowa.get("id"),
        "tur": len(odpowiedzi or []),
        "powtorki": powtorzone_formulki(odpowiedzi),
        "ma_wyjscie": zakonczona_poprawnie(odpowiedzi, handoff, link),
        "kwoty_niezgodne": kwoty_niezgodne,
        "handoff": bool(handoff),
        "trasa": list(trasa or []),
        "koszt": koszt_rozmowy(uzycia),
        "p95_czasu_tury": p95_czas(czasy_tur),
    }
    if oczekiwana_trasa is not None:
        wynik["trafnosc_routingu"] = trafnosc_routingu(zip(oczekiwana_trasa, trasa or []))
    return wynik
