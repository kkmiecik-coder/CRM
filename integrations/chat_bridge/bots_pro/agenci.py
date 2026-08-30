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
