# -*- coding: utf-8 -*-
"""
Skład routera i agentów.

Router ma JEDNO zadanie: wybrać agenta. Nie wolno mu dać narzędzi biznesowych,
bo wtedy zacznie sam prowadzić rozmowę i wracamy do jednego wielkiego promptu.

narzedzia.py (i przez niego agenci.py) importuje `agents` na poziomie modułu —
bez zainstalowanego SDK cały ten plik ma zostać POMINIĘTY (wzorzec z
test_pro_narzedzia.py / test_pro_models.py).
"""
import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from bots_pro import agenci

# Narzędzia hostowane przez dostawcę zamykają drogę do Anthropica (inwariant
# przenośności 1b, patrz test_pro_narzedzia.py::TestZestawNarzedzi).
_ZAKAZANE_NARZEDZIA = {"file_search", "web_search", "code_interpreter", "computer"}


class TestRouter:
    def test_router_ma_trzy_przekazania(self):
        router = agenci.zbuduj_router()
        assert len(router.handoffs) == 3

    def test_router_nie_ma_narzedzi_biznesowych(self):
        router = agenci.zbuduj_router()
        assert router.tools == []

    def test_prompt_routera_jest_krotki(self):
        # Runda poprawek 1 (recenzja): licznik ZNAKÓW mierzył niewłaściwą
        # jednostkę — polski tekst to ~3,1 znaku na token (nie ~4 jak dla
        # angielskiego), więc próg "< 1600 znaków" przepuszczał prompt, który
        # w tokenach modelu (o200k_base) już przekraczał budżet 400 tokenów
        # (ROLA+ROUTER wyszło wtedy 451 tokenów). Liczymy teraz naprawdę.
        tiktoken = pytest.importorskip("tiktoken")
        router = agenci.zbuduj_router()
        enc = tiktoken.get_encoding("o200k_base")
        liczba_tokenow = len(enc.encode(router.instructions))
        assert liczba_tokenow < 400, (
            "Prompt routera (ROLA+ROUTER) ma %d tokenow, budzet to 400 — "
            "logika biznesowa wpelza w ROLA albo ROUTER." % liczba_tokenow
        )


class TestAgentWyceny:
    def test_agent_wyceny_ma_narzedzia(self):
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.tools) == 11

    def test_prompt_wyceny_ma_hojny_ale_skonczony_budzet(self):
        # Runda poprawek 1: nie ograniczamy tresci merytorycznej (reguly
        # handlowe z personas.json) sztywnym niskim progiem jak dla routera —
        # ale hojny sufit pilnuje, zeby przyszle zadanie nie dokladalo po
        # cichu bez zauwazenia. 6000 znakow to ok. 1150 znakow zapasu ponad
        # stan z tej rundy (ROLA+WYCENA ~5170 zn) — i tak to ok. 28% dlugosci
        # STAREGO promptu (8203 zn kontraktu formatu + 10416 zn regul).
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.instructions) < 6000


class TestAgentWiedzy:
    def test_agent_wiedzy_nie_ma_narzedzi_cenowych(self):
        # Agent wiedzy nie moze przypadkiem zapisac wyceny.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy

    def test_agent_wiedzy_bez_narzedzi_hostowanych_przez_dostawce(self):
        # Ten sam inwariant 1b co dla NARZEDZIA_WYCENY (test_pro_narzedzia.py)
        # — recenzja: dotad sprawdzany tylko dla zestawu agenta Wyceny.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert nazwy & _ZAKAZANE_NARZEDZIA == set()


class TestAgentPosprzedazowy:
    def test_agent_posprzedazowy_nie_ma_narzedzi_cenowych(self):
        # Tak samo jak agent wiedzy — sprawy indywidualne nigdy nie licza/zapisuja wyceny.
        agent = agenci.zbuduj_agenta_posprzedazowego()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy
        assert "oddaj_czlowiekowi" in nazwy

    def test_agent_posprzedazowy_bez_narzedzi_hostowanych_przez_dostawce(self):
        agent = agenci.zbuduj_agenta_posprzedazowego()
        nazwy = {t.name for t in agent.tools}
        assert nazwy & _ZAKAZANE_NARZEDZIA == set()


class TestHandoffeRoutera(object):
    def test_handoffy_routera_to_trzej_wlasciwi_agenci(self):
        # handoffs=[...] w Agent() przyjmuje surowe obiekty Agent (nie owinięte
        # w Handoff), więc atrybut to .name, tak samo jak przy zwykłym Agent().
        router = agenci.zbuduj_router()
        nazwy = {h.name for h in router.handoffs}
        assert nazwy == {"Wycena", "Wiedza", "Posprzedaz"}
