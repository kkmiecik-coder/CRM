# -*- coding: utf-8 -*-
"""
Warstwa dostawcy — przenośność modeli OpenAI <-> Anthropic.

Wymóg właściciela: przełączenie dostawcy ma być zmianą konfiguracji, nie kodu.
Testy pilnują, że model nigdy nie jest stałą w kodzie i że prefiks 'litellm/'
przełącza backend bez dotykania agentów.
"""
import importlib
import os

import pytest

from bots_pro import models as m


class TestMakeModel:
    def test_goly_identyfikator_zostaje_stringiem(self):
        # OpenAI jest natywne w Agents SDK — string wystarczy.
        assert m.make_model("gpt-5.6-terra") == "gpt-5.6-terra"

    def test_prefiks_litellm_daje_obiekt_modelu(self):
        # Wymaga zainstalowanego pakietu 'agents' (openai-agents) — obraz
        # testowy może go nie mieć, wtedy test jest pomijany.
        pytest.importorskip("agents")
        wynik = m.make_model("litellm/anthropic/claude-sonnet-5")
        assert not isinstance(wynik, str)
        assert getattr(wynik, "model", None) == "anthropic/claude-sonnet-5"

    def test_prefiks_jest_zdejmowany_dokladnie_raz(self):
        pytest.importorskip("agents")
        wynik = m.make_model("litellm/openai/gpt-5.6-terra")
        assert getattr(wynik, "model", None) == "openai/gpt-5.6-terra"


class TestModelDlaRoli:
    def test_kazda_rola_ma_model(self):
        for rola in ("router", "wycena", "wiedza", "posprzedaz", "guardrail"):
            assert m.model_dla_roli(rola) is not None

    def test_nieznana_rola_jest_bledem(self):
        # Cicha podmiana na model domyslny ukrylaby literowke w konfiguracji.
        with pytest.raises(KeyError):
            m.model_dla_roli("nieistniejaca")

    def test_rola_czytana_ze_srodowiska(self, monkeypatch):
        pytest.importorskip("agents")
        monkeypatch.setenv("MODEL_WYCENA", "litellm/anthropic/claude-sonnet-5")
        przeladowany = importlib.reload(m)
        try:
            wynik = przeladowany.model_dla_roli("wycena")
            assert getattr(wynik, "model", None) == "anthropic/claude-sonnet-5"
        finally:
            monkeypatch.setenv("MODEL_WYCENA", "gpt-5.6-terra")
            importlib.reload(m)


class TestInwariantPrzenosnosci:
    def test_zaden_model_nie_jest_zapisany_na_sztywno_w_kodzie_agentow(self):
        # Inwariant 1a: identyfikator modelu wolno wpisac WYLACZNIE w bots_pro/models.py.
        import glob
        import re

        katalog = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
        wzorzec = re.compile(r"[\"'](gpt-[0-9]|claude-|o[134]-)")
        winowajcy = []
        for sciezka in glob.glob(os.path.join(katalog, "bots_pro", "**", "*.py"),
                                 recursive=True):
            if os.path.basename(sciezka) == "models.py":
                continue
            with open(sciezka, encoding="utf-8") as plik:
                for nr, linia in enumerate(plik, 1):
                    if wzorzec.search(linia):
                        winowajcy.append("%s:%d" % (sciezka, nr))
        assert winowajcy == [], "Model wpisany na sztywno poza models.py: %s" % winowajcy
