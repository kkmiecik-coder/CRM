# -*- coding: utf-8 -*-
"""
Warstwa dostawcy — przenośność modeli OpenAI <-> Anthropic.

Wymóg właściciela: przełączenie dostawcy ma być zmianą konfiguracji, nie kodu.
Testy pilnują, że model nigdy nie jest stałą w kodzie i że prefiks 'litellm/'
przełącza backend bez dotykania agentów.

Trzy testy niżej (oznaczone `pytest.importorskip("agents")`) tworzą realny
`LitellmModel` i wymagają zainstalowanego pakietu 'agents' (openai-agents).
Produkcyjny obraz dostaje tę zależność z requirements.txt; obraz testowy
może jej nie mieć — wtedy testy są pomijane zamiast fałszywie czerwienić.
"""
import importlib
import os
import re

import pytest

from bots_pro import models as m


class TestMakeModel:
    def test_goly_identyfikator_zostaje_stringiem(self):
        # OpenAI jest natywne w Agents SDK — string wystarczy.
        assert m.make_model("gpt-5.6-terra") == "gpt-5.6-terra"

    def test_prefiks_litellm_daje_obiekt_modelu(self):
        pytest.importorskip("agents")  # patrz docstring modulu
        wynik = m.make_model("litellm/anthropic/claude-sonnet-5")
        assert not isinstance(wynik, str)
        assert getattr(wynik, "model", None) == "anthropic/claude-sonnet-5"

    def test_prefiks_jest_zdejmowany_dokladnie_raz(self):
        pytest.importorskip("agents")  # patrz docstring modulu
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
        pytest.importorskip("agents")  # patrz docstring modulu
        monkeypatch.setenv("MODEL_WYCENA", "litellm/anthropic/claude-sonnet-5")
        przeladowany = importlib.reload(m)
        try:
            wynik = przeladowany.model_dla_roli("wycena")
            assert getattr(wynik, "model", None) == "anthropic/claude-sonnet-5"
        finally:
            monkeypatch.setenv("MODEL_WYCENA", "gpt-5.6-terra")
            importlib.reload(m)


# --- Detekcja identyfikatora modelu wewnatrz literalu lancuchowego ---------
#
# Inwariant 1a pilnuje, zeby zaden identyfikator modelu nie byl zapisany na
# sztywno poza bots_pro/models.py. Naiwny regex zakotwiczony zaraz za
# cudzyslowem (`["'](gpt-...)`) wymaga, zeby literal ZACZYNAL SIE od
# chronionego prefiksu — a konwencja tego modulu, 'litellm/<dostawca>/<model>',
# ma prefiks modelu W SRODKU literalu, nie na poczatku. Taki regex przepuszcza
# wiec dokladnie ten literal, ktory najlatwiej przypadkiem skopiowac jako
# fallback do innego pliku bots_pro/. Dlatego szukamy fragmentu identyfikatora
# GDZIEKOLWIEK w tresci kazdego literalu lancuchowego w linii.
_WZORZEC_MODELU = re.compile(r"gpt-[0-9]|claude-|o[134]-")
_WZORZEC_LITERALU = re.compile(r'"([^"]*)"|\'([^\']*)\'')


def _zawiera_identyfikator_modelu(tekst_literalu):
    """Czy zawartosc pojedynczego literalu lancuchowego zawiera fragment
    identyfikatora modelu w dowolnym miejscu (nie tylko na poczatku)."""
    return bool(_WZORZEC_MODELU.search(tekst_literalu))


def _linia_ma_model_na_sztywno(linia):
    """Czy ktorykolwiek literal lancuchowy w linii kodu niesie identyfikator
    modelu. Skanujemy TRESC literalow (wyciagnietych z linii), nie cala linie
    — dzieki temu wynik nie zalezy od tego, co poprzedza cudzyslow."""
    for dopasowanie in _WZORZEC_LITERALU.finditer(linia):
        tresc = dopasowanie.group(1)
        if tresc is None:
            tresc = dopasowanie.group(2)
        if _zawiera_identyfikator_modelu(tresc):
            return True
    return False


class TestWykrywanieModeluWLiteralu:
    """Dowod, ze luka z naiwnego regexu (kotwiczenie zaraz za cudzyslowem)
    nie moze wrocic niezauwazona — w tym konwencja 'litellm/<dostawca>/<model>'
    tego modulu, gdzie identyfikator modelu jest CZESCIA wiekszego literalu."""

    @pytest.mark.parametrize("linia", [
        'router = "gpt-5.6-terra"',
        "wycena = 'claude-sonnet-5'",
        'router = "litellm/anthropic/claude-sonnet-5"',
        'wycena = "litellm/openai/gpt-5.6-terra"',
        'model = "openai/gpt-4o"',
    ])
    def test_wykrywa_identyfikator_gdziekolwiek_w_literale(self, linia):
        assert _linia_ma_model_na_sztywno(linia)

    @pytest.mark.parametrize("linia", [
        'rola = "wycena"',
        '# zwykly komentarz bez identyfikatora modelu',
        'sciezka = "bots_pro/models.py"',
        'x = "hello world"',
        'rola = model_dla_roli("router")',
    ])
    def test_nie_wykrywa_falszywie_na_zwyklym_tekscie(self, linia):
        assert not _linia_ma_model_na_sztywno(linia)


class TestInwariantPrzenosnosci:
    def test_zaden_model_nie_jest_zapisany_na_sztywno_w_kodzie_agentow(self):
        # Inwariant 1a: identyfikator modelu wolno wpisac WYLACZNIE w bots_pro/models.py.
        import glob

        katalog = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
        winowajcy = []
        for sciezka in glob.glob(os.path.join(katalog, "bots_pro", "**", "*.py"),
                                 recursive=True):
            if os.path.basename(sciezka) == "models.py":
                continue
            with open(sciezka, encoding="utf-8") as plik:
                for nr, linia in enumerate(plik, 1):
                    if _linia_ma_model_na_sztywno(linia):
                        winowajcy.append("%s:%d" % (sciezka, nr))
        assert winowajcy == [], "Model wpisany na sztywno poza models.py: %s" % winowajcy
