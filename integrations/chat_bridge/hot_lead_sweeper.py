# -*- coding: utf-8 -*-
# Sweeper "goracy lead": rozmowa juz oddana agentowi (status open) po cenie bota (priced=1),
# ale klient milczy dluzej niz HOT_LEAD_SILENCE_HOURS — dopisujemy prywatna notatke priorytetowa,
# zeby lead nie zgubil sie w kolejce agenta (LS-04). Bot NIE odpowiada tu sam — rozmowa zostaje
# przypisana czlowiekowi, sweeper tylko podbija jej widocznosc.
import time
from config import HOT_LEAD_SWEEP_INTERVAL, HOT_LEAD_SILENCE_HOURS
from core.log import log
from core.chatwoot import cw_open_conversations, cw_note
from bots.quotebot import _priced


def hot_sweep_once(now):
    """Jedno przejscie sweepera goracych leadow. Zwraca liczbe oznaczonych rozmow."""
    marked = 0
    prog = HOT_LEAD_SILENCE_HOURS * 3600
    for conv in cw_open_conversations():
        conv_id = conv.get("id")
        if not conv_id or not _priced(conv_id):
            continue   # bez ceny bota to nie "goracy lead" tego sweepera
        if conv.get("last_msg_type") in (0, "incoming"):
            continue   # ostatnie slowo klienta -> agent juz to widzi, nie duplikuj
        last_ts = conv.get("last_msg_ts") or 0
        if now - last_ts < prog:
            continue
        try:
            cw_note(conv_id, "🔥 Gorący lead: klient dostał wycenę i milczy od dłuższego czasu — "
                    "warto dopytać.")
        except Exception:
            continue
        marked += 1
        log("hot_lead_sweeper: oznaczono conv %s (cisza %ss)" % (conv_id, int(now - last_ts)))
    return marked


def hot_lead_sweeper():
    if HOT_LEAD_SWEEP_INTERVAL <= 0:
        log("hot_lead_sweeper: wylaczony (HOT_LEAD_SWEEP_INTERVAL<=0)")
        return
    while True:
        try:
            hot_sweep_once(time.time())
        except Exception as e:
            log("hot_lead_sweeper ERROR:", repr(e))
        time.sleep(HOT_LEAD_SWEEP_INTERVAL)
