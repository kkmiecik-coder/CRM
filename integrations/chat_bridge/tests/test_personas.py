# -*- coding: utf-8 -*-
# Test: prompt systemowy zawiera reguly wspolne i kanalowe.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

p = importlib.import_module("bots.personas")


def test_wspolne_reguly_ceny_i_imie():
    s = p.build_system_prompt("olx", "", {"name": "", "identifier": ""})
    assert "nie podawaj" in s.lower() or "nie podaje" in s.lower()
    assert "Pan/Pani" in s
    assert "wycen" in s.lower()


def test_allegro_zakaz_kontaktu_poza_platforma():
    s = p.build_system_prompt("allegro", "", {"name": "", "identifier": ""})
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
