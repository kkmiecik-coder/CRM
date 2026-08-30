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


class TestRouter:
    def test_router_ma_trzy_przekazania(self):
        router = agenci.zbuduj_router()
        assert len(router.handoffs) == 3

    def test_router_nie_ma_narzedzi_biznesowych(self):
        router = agenci.zbuduj_router()
        assert router.tools == []

    def test_prompt_routera_jest_krotki(self):
        # Prompt routera ponad ~400 tokenow znaczy, ze wpelza mu logika biznesowa.
        router = agenci.zbuduj_router()
        assert len(router.instructions) < 1600


class TestAgentWyceny:
    def test_agent_wyceny_ma_narzedzia(self):
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.tools) == 11

    def test_agent_wiedzy_nie_ma_narzedzi_cenowych(self):
        # Agent wiedzy nie moze przypadkiem zapisac wyceny.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy


class TestAgentPosprzedazowy:
    def test_agent_posprzedazowy_nie_ma_narzedzi_cenowych(self):
        # Tak samo jak agent wiedzy — sprawy indywidualne nigdy nie licza/zapisuja wyceny.
        agent = agenci.zbuduj_agenta_posprzedazowego()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy
        assert "oddaj_czlowiekowi" in nazwy


class TestHandoffeRoutera(object):
    def test_handoffy_routera_to_trzej_wlasciwi_agenci(self):
        # handoffs=[...] w Agent() przyjmuje surowe obiekty Agent (nie owinięte
        # w Handoff), więc atrybut to .name, tak samo jak przy zwykłym Agent().
        router = agenci.zbuduj_router()
        nazwy = {h.name for h in router.handoffs}
        assert nazwy == {"Wycena", "Wiedza", "Posprzedaz"}
