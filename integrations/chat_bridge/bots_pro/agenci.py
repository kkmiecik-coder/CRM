# -*- coding: utf-8 -*-
"""
Router i agenci wyspecjalizowani.

Kształt Kodee: router klasyfikuje i przekazuje, agenci mają małe prompty
i małe zestawy narzędzi. Router zastępuje pięć regexów rozpoznających intencje
(_czy_reklamacja, _czy_prosi_o_czlowieka, _pyta_o_wysylke, _czy_odmowa,
_jest_potwierdzenie) jedną decyzją modelu.

Guardrail wyjściowy G1 (integralność ceny, bots_pro/guardraile.py) NIE jest
tutaj podpięty jako output_guardrails= — samo podpięcie do pętli rozmowy
(Runner) jest zadaniem Task 6 (tura.py). Deklarowanie go tutaj bez podpięcia
w Runnerze byłoby martwym kodem.

WYJĄTEK od reguły "agenci wyspecjalizowani nie mają własnych handoffs"
(Task 8, B4): Wiedza dostaje handoff DO Wyceny (nie w drugą stronę, nie do
Posprzedaży). Bez tego droga z Wiedzy do Wyceny istniała WYŁĄCZNIE między
turami, przez ponowne wejście przez Router (patrz `tura.py`, docstring o
"ślepej uliczce" z Task 6) — co ma dwie wady: (a) pytanie łączące wiedzę i
cenę w JEDNEJ wiadomości ("z czego robicie blaty i ile wyjdzie 180x60x4?")
nie dostawało wyceny w tej samej turze; (b) komunikat korekty guardraila G1
(`tura._KOMUNIKAT_KOREKTY`) wraca przez Router, który teoretycznie mógł
przekazać go do Wiedzy — agenta BEZ `policz_wycene`, niezdolnego naprawić
ceny. Handoff Wiedza -> Wycena daje jej drogę ucieczki w OBU przypadkach, bez
omijania Routera (którego `tura.py` świadomie NIE robi — patrz jej docstring).

ŚWIADOMIE bez handoffu Posprzedaż -> Wycena: Posprzedaż obsługuje sprawy
INDYWIDUALNE (reklamacje, status zamówienia, faktury, zwroty) — cały jej sens
to eskalacja do człowieka (`prompty.POSPRZEDAZ`: "Spraw indywidualnych nie
obsługujesz samodzielnie"), nie liczenie nowych wycen. W odróżnieniu od
Wiedzy, pytanie łączące sprawę posprzedażową z prośbą o NOWĄ wycenę w jednym
zdaniu nie jest naturalnym, częstym przypadkiem — a dodanie tu handoffu
rozmywałoby granicę "sprawy indywidualne = zawsze człowiek" bez wyraźnej
korzyści.
"""
from agents import Agent

from bots_pro import prompty
from bots_pro.models import model_dla_roli
from bots_pro.narzedzia import NARZEDZIA_WYCENY, oddaj_czlowiekowi


def zbuduj_agenta_wyceny():
    return Agent(
        name="Wycena",
        instructions=prompty.ROLA + "\n\n" + prompty.WYCENA,
        model=model_dla_roli("wycena"),
        tools=NARZEDZIA_WYCENY,
    )


def zbuduj_agenta_wiedzy():
    # Import lokalny: narzedzia_wiedzy.py importuje bots_pro.wiedza, a agent
    # wyceny (ten plik importowany jako całość) nie ma po co jej ciągnąć.
    from bots_pro.narzedzia_wiedzy import szukaj_w_bazie_wiedzy
    return Agent(
        name="Wiedza",
        instructions=prompty.ROLA + "\n\n" + prompty.WIEDZA,
        model=model_dla_roli("wiedza"),
        tools=[szukaj_w_bazie_wiedzy, oddaj_czlowiekowi],
        # Task 8, B4 — patrz docstring modułu ("WYJĄTEK..."). Osobna instancja
        # agenta Wyceny (nie ta sama, którą dostaje Router) — Agents SDK nie
        # wymaga współdzielenia obiektu, a handoffy są zakresowane do agenta,
        # który je deklaruje.
        handoffs=[zbuduj_agenta_wyceny()],
    )


def zbuduj_agenta_posprzedazowego():
    return Agent(
        name="Posprzedaz",
        instructions=prompty.ROLA + "\n\n" + prompty.POSPRZEDAZ,
        model=model_dla_roli("posprzedaz"),
        tools=[oddaj_czlowiekowi],
    )


def zbuduj_router():
    return Agent(
        name="Router",
        instructions=prompty.ROLA + "\n\n" + prompty.ROUTER,
        model=model_dla_roli("router"),
        tools=[],
        handoffs=[
            zbuduj_agenta_wyceny(),
            zbuduj_agenta_wiedzy(),
            zbuduj_agenta_posprzedazowego(),
        ],
    )
