# -*- coding: utf-8 -*-
"""
Wiedza za stałym interfejsem.

Implementacja jest wymienna (dziś: indeks mostka; jutro ewentualnie vector
store dostawcy albo pgvector, który już stoi na VPS). Agent widzi wyłącznie
szukaj() — dlatego podmiana backendu nie dotyka agentów, a inwariant
przenośności zostaje zachowany: żadnego narzędzia hostowanego przez dostawcę
w liście tools.

POMIAR TRAFNOŚCI „W CIENIU" (P2, runda napraw 5). `bots.knowledge.retrieve`
liczy podobieństwo i odrzuca je w tej samej linii, więc zwraca pięć
NAJBLIŻSZYCH fragmentów także dla pytania, którego w bazie nie ma. Z zewnątrz
„nic nie pasuje" jest przez to nieodróżnialne od „pasuje idealnie", a reguła
bezpieczeństwa niżej (pusta lista -> człowiek) odpala się wyłącznie przy awarii
indeksu. `szukaj()` woła więc `retrieve_scored` i LOGUJE miarę — nic poza tym.

Progu tu NIE MA i świadomie: nie znamy dobrej wartości, a zgadnięta stała
przeniosłaby tylko problem (odcięłaby trafne odpowiedzi albo nie odcięła
żadnej). Najpierw kilka dni ruchu, potem próg dobrany Z DANYCH — instrukcja
odczytu jest w raporcie rundy 5.
"""
import re

from config import BOT_RETRIEVAL_K
from core.log import log
from bots.knowledge import retrieve_scored

# Prefiks stały i unikalny — po nim filtruje się log do pomiaru
# (`docker logs ... | grep 'KB trafnosc:'`).
_PREFIKS_POMIARU = "KB trafnosc:"

# Pytanie pisze KLIENT. Do logu idzie zwinięte do jednej linii (wieloliniowe
# rozbiłoby wpis na kilka i zepsuło zliczanie) i przycięte — bez limitu jedna
# wklejona specyfikacja zalałaby log.
_MAKS_PYTANIE_W_LOGU = 200


def _liczba(wartosc):
    """Wynik z czterema miejscami albo „-", gdy takiego fragmentu nie było.

    Myślnik zamiast 0.0: „nie ma piątego fragmentu" i „piąty fragment ma
    podobieństwo zero" to dwie różne rzeczy, a próg liczony potem z tych danych
    zostałby przez podstawione zero zaniżony."""
    return "-" if wartosc is None else "%.4f" % wartosc


def _pytanie_do_logu(pytanie):
    return re.sub(r"\s+", " ", str(pytanie or "")).strip()[:_MAKS_PYTANIE_W_LOGU]


def _zaloguj_trafnosc(pytanie, trafienia):
    """Jedna linia na zapytanie: najlepszy wynik, wynik OSTATNIEGO zwróconego
    fragmentu (przy domyślnym `BOT_RETRIEVAL_K=5` — piątego, czyli tego, który
    ledwo załapał się do kompletu), liczba fragmentów i samo pytanie.

    `ost` jest kandydatem na próg, `top` mówi, czy w bazie w ogóle było coś
    trafnego, a `n=0` odróżnia AWARIĘ indeksu od słabego dopasowania.

    Cały pomiar w try/except: obserwacja nie ma prawa zabrać klientowi
    odpowiedzi — to jedyna rzecz gorsza od braku pomiaru."""
    try:
        wyniki = [wynik for wynik, _ in trafienia]
        ostatni = wyniki[-1] if len(wyniki) >= BOT_RETRIEVAL_K else None
        log("%s top=%s ost=%s n=%d pytanie=%s" % (
            _PREFIKS_POMIARU, _liczba(wyniki[0] if wyniki else None),
            _liczba(ostatni), len(wyniki), _pytanie_do_logu(pytanie)))
    except Exception as e:
        # Nie przez `log(...)` — gdyby to on był źródłem wyjątku, drugie
        # wywołanie poleciałoby w górę i tura padłaby mimo osłony.
        print("[bridge] KB trafnosc: pomiar nieudany:", repr(e), flush=True)


def szukaj(pytanie):
    """Fragmenty bazy wiedzy pasujące do pytania.

    Pusta lista NIE jest trybem pracy — jest stanem błędu. Agent wiedzy ma
    wtedy oddać rozmowę człowiekowi, a nie odpowiadać „sprawdzimy i wrócimy".

    Wynik jest DOKŁADNIE ten sam co przed pomiarem: `retrieve_scored` oddaje te
    same fragmenty, w tej samej kolejności i w tej samej liczbie co `retrieve`
    (sonda `test_obie_funkcje_zwracaja_te_same_fragmenty`), a miara idzie
    wyłącznie do logu. Wołamy JEDNĄ z tych funkcji, nie obie — dwie kosztowałyby
    dwa embedowania na każde pytanie klienta.
    """
    trafienia = retrieve_scored(pytanie)
    _zaloguj_trafnosc(pytanie, trafienia)
    return [{"tytul": "", "tresc": fragment, "article_id": None}
            for _, fragment in trafienia]
