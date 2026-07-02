# -*- coding: utf-8 -*-
# Test: prompt systemowy zawiera reguly wspolne i kanalowe, persony ladowane z JSON.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

p = importlib.import_module("bots.personas")


def test_load_personas_zwraca_common_i_channels():
    dane = p.load_personas()
    assert "common" in dane
    assert "channels" in dane
    assert "olx" in dane["channels"]
    assert "allegro" in dane["channels"]
    assert "mail" in dane["channels"]


def test_pierwsza_osoba_i_wspolne_reguly():
    s = p.build_system_prompt("olx", "", {})
    assert "PIERWSZEJ OSOBIE" in s
    assert "przygotujemy" in s
    assert "Pan/Pani" in s
    assert "cen" in s.lower()
    # Nie moze byc starej, trzecioosobowej frazy bota
    assert "nasz konsultant przygotuje" not in s.lower()


def test_allegro_zakaz_kontaktu_poza_platforma():
    s = p.build_system_prompt("allegro", "", {})
    assert "poza Allegro" in s
    assert "telefon" in s.lower()


def test_mail_i_olx_roznia_sie():
    assert p.build_system_prompt("mail", "", {}) != p.build_system_prompt("olx", "", {})


def test_wiedza_wstawiona_do_promptu():
    s = p.build_system_prompt("olx", "Realizacja 14 dni.", {"name": "Jan", "identifier": "x"})
    assert "Realizacja 14 dni." in s
    assert "Jan" in s


def test_brak_wiedzy_komunikat():
    s = p.build_system_prompt("olx", "", {})
    assert "brak" in s.lower()


def test_fallback_gdy_brak_pliku_json(monkeypatch):
    # Symulujemy zepsuty/brakujacy plik JSON - bot nie moze sie wywalic,
    # a reguly bezpieczenstwa (Allegro, 1. osoba) musza przetrwac.
    monkeypatch.setattr(p, "_PATH", os.path.join(os.path.dirname(p.__file__), "nieistniejacy_plik.json"))
    dane = p.load_personas()
    assert "common" in dane
    assert "channels" in dane
    assert "allegro" in dane["channels"]

    s = p.build_system_prompt("allegro", "", {})
    assert "PIERWSZEJ OSOBIE" in s
    assert "poza Allegro" in s


def test_livechat_ma_pelna_checkliste_do_wyceny():
    s = p.build_system_prompt("livechat", "", {})
    low = s.lower()
    assert "technologia" in low and "mikrowczep" in low
    assert "klasa" in low                      # klasa drewna A/B / B/B
    assert "otwory" in low                     # otwory / wycięcia
    assert "krawęd" in low                     # krawędzie
    assert "podstopnic" in low                 # pola schodów
    assert "surowe" in low                     # reguła wykończenia
    assert "centymetr" in low                  # normalizacja jednostek
    assert "nie potwierdzaj docięcia" in low   # twardy zakaz pytania o docięcie


def test_checklista_dziedziczona_w_podpowiadaczu_olx():
    # common.zasady sa wspolne — podpowiadacz OLX tez dostaje checkliste (technologia/klasa).
    s = p.build_system_prompt("olx", "", {}).lower()
    assert "mikrowczep" in s
    assert "klasa" in s


def test_livechat_ma_regule_koperty_wymiarow():
    s = p.build_system_prompt("livechat", "", {})
    low = s.lower()
    assert "120 cm" in low                 # max szerokość
    assert "450" in low and "500" in low   # max długość lita / mikrowczep
    assert "ponadstandard" in low          # grubość > 4 cm nie odrzucana
    assert "860" in low                    # worked example (nie przyjmuj)


def test_regula_koperty_dziedziczona_w_olx():
    s = p.build_system_prompt("olx", "", {}).lower()
    assert "120 cm" in s
    assert "500" in s
