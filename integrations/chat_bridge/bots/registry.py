# -*- coding: utf-8 -*-
# Rejestr botow: mapa inbox_id -> BotConfig(name, persona_key). Dodanie kanalu = wpis tutaj.
from collections import namedtuple
from config import CW_OLX_INBOX, CW_ALLEGRO_MSG_INBOX, CW_MAIL_BOT_INBOXES

BotConfig = namedtuple("BotConfig", ["name", "persona_key"])


def _build():
    m = {}
    if CW_OLX_INBOX:
        m[str(CW_OLX_INBOX)] = BotConfig("olx", "olx")
    if CW_ALLEGRO_MSG_INBOX:
        m[str(CW_ALLEGRO_MSG_INBOX)] = BotConfig("allegro", "allegro")
    for iid in (CW_MAIL_BOT_INBOXES or "").split(","):
        iid = iid.strip()
        if iid:
            m[iid] = BotConfig("mail", "mail")
    return m


BOTS = _build()


def bot_for_inbox(inbox_id):
    # Zwraca BotConfig dla inboxu objetego botem albo None.
    return BOTS.get(str(inbox_id))
