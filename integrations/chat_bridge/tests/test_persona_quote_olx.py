# -*- coding: utf-8 -*-
# Testy persony quote_olx (T2-persona): dziedziczy reguly quote (extends) + delty OLX
# (czysty tekst, bez zdjec, publiczny link zamiast natretnego zbierania e-maila).
from bots import personas
from bots.personas import build_system_prompt


def test_quote_olx_dziedziczy_reguly_quote():
    p = build_system_prompt("quote_olx", "", {})
    # Regula tozsamosci z persony quote (imie Debus) musi byc odziedziczona.
    assert "Dębuś" in p
    # Regula bezpieczenstwa z quote (bez obietnic rabatow) tez.
    assert "rabat" in p.lower()


def test_quote_olx_ma_regule_czystego_tekstu_i_kanal_olx():
    p = build_system_prompt("quote_olx", "", {})
    assert "OLX" in p
    # Instrukcja: bez emoji / pogrubien (LLM nie ma polegac na formatowaniu).
    assert "emoji" in p.lower() or "pogrub" in p.lower()


def test_quote_olx_nie_obiecuje_zdjec():
    p = build_system_prompt("quote_olx", "", {})
    assert "zdj" in p.lower()  # wzmianka: nie wysylamy zdjec, opisujemy slownie


def test_quote_olx_w_default_safeguard():
    # Nawet przy zepsutym personas.json quote_olx istnieje (extends quote w _DEFAULT).
    assert "quote_olx" in personas._DEFAULT["channels"]


def test_extends_laczy_zasady_rodzic_potem_dziecko():
    # Kolejnosc: najpierw zasady rodzica (quote), potem wlasne (OLX).
    dane = {
        "common": {"rola": "R", "zasady": ["C1"]},
        "channels": {
            "quote": {"opis": "OpisQuote", "zasady": ["Q1", "Q2"]},
            "quote_olx": {"extends": "quote", "opis": "OpisOLX", "zasady": ["O1"]},
        },
    }
    # Testujemy resolver bezposrednio (stabilniej niz caly prompt):
    ch = personas._resolve_channel(dane, "quote_olx")
    assert ch["opis"] == "OpisOLX"
    assert ch["zasady"] == ["Q1", "Q2", "O1"]


def test_extends_nieznanego_rodzica_nie_wywala():
    dane = {"common": {}, "channels": {"quote_olx": {"extends": "brak", "zasady": ["O1"]}}}
    ch = personas._resolve_channel(dane, "quote_olx")
    assert ch["zasady"] == ["O1"]
