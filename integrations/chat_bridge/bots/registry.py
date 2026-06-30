# -*- coding: utf-8 -*-
# Rejestr botow: mapuje inbox_id -> BotConfig(name, persona_key) na podstawie
# zmiennej srodowiskowej BOT_INBOX_MAP, czytanej NA BIEZACO (format
# "3:olx,4:allegro,8:mail,9:mail"). Pusta mapa = zaden bot nie jest aktywny (uspiony).
# Wlaczanie per kanal = dopisanie wpisu do BOT_INBOX_MAP i restart mostka (bez zmian w kodzie).
# Czytamy os.environ wprost (nie przez config), zeby uniknac cache'owania przy imporcie
# i umozliwic prosty rollout/test per inbox.
import os
from collections import namedtuple

BotConfig = namedtuple("BotConfig", ["name", "persona_key"])


def _parse_map():
    m = {}
    for part in (os.environ.get("BOT_INBOX_MAP", "") or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        iid, persona = part.split(":", 1)
        iid = iid.strip(); persona = persona.strip()
        if iid and persona:
            m[iid] = BotConfig(persona, persona)
    return m


def bot_for_inbox(inbox_id):
    # Zwraca BotConfig dla aktywnego inboxu albo None (gdy nie ma w BOT_INBOX_MAP).
    return _parse_map().get(str(inbox_id))
