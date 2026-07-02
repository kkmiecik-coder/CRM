# -*- coding: utf-8 -*-
# Sweeper "pending": samonaprawa rozmow, ktore utknely w pending bez odpowiedzi bota
# (zgubiony webhook, restart mostu, wyczerpane retry). Otwiera TYLKO rozmowy, w ktorych
# ostatnia wiadomosc jest od KLIENTA i starsza niz SWEEP_PENDING_AGE — rozmowy czekajace
# na klienta (ostatnie slowo bota) zostawia w pending.
import time
from config import CW_TOKEN, SWEEP_INTERVAL, SWEEP_PENDING_AGE
from core.log import log
from core.chatwoot import cw_pending_conversations, cw_bot_handoff, cw_note


def sweep_once(now):
    """Jedno przejscie sweepera. Zwraca liczbe otwartych rozmow."""
    opened = 0
    for conv in cw_pending_conversations():
        if conv.get("last_msg_type") not in (0, "incoming"):
            continue  # ostatnie slowo ma bot/agent -> czekamy na klienta
        last_ts = conv.get("last_msg_ts") or 0
        if now - last_ts < SWEEP_PENDING_AGE:
            continue  # jeszcze w oknie retry bota
        conv_id = conv.get("id")
        if not conv_id:
            continue
        # Token admina: dziala na kazdym inboxie (token bota mogl stracic dostep — znany incydent).
        if not cw_bot_handoff(conv_id, token=CW_TOKEN):
            continue  # sprobujemy w kolejnym przejsciu
        opened += 1
        log("sweeper: otwarto conv %s (pending %ss bez odpowiedzi bota)" % (conv_id, int(now - last_ts)))
        try:
            cw_note(conv_id, "🧹 Sweeper: rozmowa otwarta automatycznie — bot nie odpowiedział w terminie.")
        except Exception:
            pass
    return opened


def sweeper():
    if SWEEP_INTERVAL <= 0:
        log("sweeper: wylaczony (SWEEP_INTERVAL<=0)")
        return
    while True:
        try:
            sweep_once(time.time())
        except Exception as e:
            log("sweeper ERROR:", repr(e))
        time.sleep(SWEEP_INTERVAL)
