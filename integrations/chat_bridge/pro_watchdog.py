# -*- coding: utf-8 -*-
"""
Watchdog porzuconej rozmowy.

Rozmowa w statusie 'pending', w której ostatnia wiadomość jest od bota i minął
próg ciszy, dostaje automatyczny handoff. Bez tego lead ginie: bot może pisać
wyłącznie przy 'pending', a handoff (`bots_pro.tura._oddaj_konsultantowi`,
guardrail, limity tur — Task 8/B2) odpala się dziś tylko z jawnej decyzji
modelu albo z twardych reguł WEWNĄTRZ tury, NIGDY z samej bezczynności klienta
— rozmowa, w której klient po prostu przestał pisać, nie ma kto by ją
przekazała dalej. Audyt: w jednym shardzie 10 z 24 rozmów kończyło się
dokładnie tak — bot ostatni, bez handoffu, bez właściciela.
"""
import time

from config import BOT_PRO_WATCHDOG_MINUTES
from core.chatwoot import cw_bot_handoff, cw_pending_conversations
from core.log import log

# Chatwoot niesie last_msg_type PROSTO z pola API "message_type" — to LICZBA
# (0=incoming, 1=outgoing, patrz core/chatwoot.py:_cw_conversations_by_status),
# nie string. Sprawdzamy OBIE postacie — dokladnie ten sam wzorzec obronny co
# w sweeper.py/hot_lead_sweeper.py (`in (0, "incoming")` / `in (1, "outgoing")`),
# zeby watchdog dzialal na PRAWDZIWYM ksztalcie danych z API, nie tylko na
# stringu, ktorego produkcja nigdy nie wysyla.
_BOT_MOWIL_OSTATNI = (1, "outgoing")


def znajdz_porzucone(rozmowy, teraz, prog_minut):
    """Identyfikatory rozmów, w których bot mówił ostatni i minął próg ciszy."""
    prog = prog_minut * 60
    porzucone = []
    for rozmowa in rozmowy or []:
        znacznik = rozmowa.get("last_msg_ts")
        if not znacznik:
            continue
        if rozmowa.get("last_msg_type") not in _BOT_MOWIL_OSTATNI:
            continue
        if teraz - znacznik >= prog:
            porzucone.append(rozmowa["id"])
    return porzucone


def watchdog():
    """Wątek tła: co 5 minut oddaje porzucone rozmowy konsultantowi."""
    while True:
        try:
            porzucone = znajdz_porzucone(
                cw_pending_conversations(), time.time(), BOT_PRO_WATCHDOG_MINUTES)
            for conv_id in porzucone:
                if cw_bot_handoff(conv_id):
                    log("watchdog: rozmowa %s porzucona przez bota -> konsultant" % conv_id)
        except Exception as e:
            log("watchdog ERROR:", repr(e))
        time.sleep(300)
