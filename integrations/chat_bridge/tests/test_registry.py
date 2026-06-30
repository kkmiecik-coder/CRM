# -*- coding: utf-8 -*-
# Test: rejestr mapuje inboxy na persony; wyklucza Dyskusje/Chat.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CHATWOOT_OLX_INBOX_ID"] = "3"
os.environ["CHATWOOT_ALLEGRO_MSG_INBOX_ID"] = "4"
os.environ["CW_MAIL_BOT_INBOXES"] = "8,9"
import importlib

import config; importlib.reload(config)
reg = importlib.import_module("bots.registry"); importlib.reload(reg)


def test_olx_i_allegro_maja_persony():
    assert reg.bot_for_inbox("3").persona_key == "olx"
    assert reg.bot_for_inbox("4").persona_key == "allegro"


def test_mail_inboxy():
    assert reg.bot_for_inbox("8").persona_key == "mail"
    assert reg.bot_for_inbox("9").persona_key == "mail"


def test_dyskusje_i_chat_wykluczone():
    assert reg.bot_for_inbox("6") is None   # Allegro-Dyskusje
    assert reg.bot_for_inbox("5") is None   # Chat live
    assert reg.bot_for_inbox("999") is None


def test_akceptuje_int_i_str():
    assert reg.bot_for_inbox(3).persona_key == "olx"
