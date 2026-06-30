# -*- coding: utf-8 -*-
# Test rejestru botow: BOT_INBOX_MAP steruje aktywacja per inbox; pusta mapa = uspiony.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

reg = importlib.import_module("bots.registry")

FULL = "3:olx,4:allegro,8:mail,9:mail"


def setup_function(_):
    os.environ["BOT_INBOX_MAP"] = FULL


def test_olx_i_allegro_maja_persony():
    assert reg.bot_for_inbox("3").persona_key == "olx"
    assert reg.bot_for_inbox("4").persona_key == "allegro"


def test_mail_inboxy():
    assert reg.bot_for_inbox("8").persona_key == "mail"
    assert reg.bot_for_inbox("9").persona_key == "mail"


def test_niezmapowane_zwracaja_none():
    assert reg.bot_for_inbox("6") is None   # Allegro-Dyskusje
    assert reg.bot_for_inbox("5") is None   # Chat live
    assert reg.bot_for_inbox("999") is None


def test_akceptuje_int_i_str():
    assert reg.bot_for_inbox(3).persona_key == "olx"


def test_pusta_mapa_uspiony():
    os.environ["BOT_INBOX_MAP"] = ""
    assert reg.bot_for_inbox("3") is None
    assert reg.bot_for_inbox("4") is None
