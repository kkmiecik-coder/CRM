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
# N11: DRUGI silnik, ta sama definicja "klient zobaczyl cene" — patrz docstring
# rozmowy_z_pokazana_cena i komentarz w hot_sweep_once nizej.
from bots_pro.stan import rozmowy_z_pokazana_cena


def hot_sweep_once(now):
    """Jedno przejscie sweepera goracych leadow. Zwraca liczbe oznaczonych rozmow.

    N11 (naprawa po testach na zywym czacie): warunek "bot pokazal cene" pytal
    WYLACZNIE `bots.quotebot._priced`, czyli kolumne STAREGO silnika. Rozmowy
    Debusia Pro byly wiec dla tego sweepera niewidoczne: nowy silnik pokazywal
    klientowi cene, rozmowa szla do czlowieka, klient milkl — i nikt tego nie
    podnosil. Lead jest goracy, gdy KTORYKOLWIEK z dwoch silnikow pokazal cene.

    Zmiana jest ADDYTYWNA: rozmowy starego silnika przechodza dokladnie tak jak
    przed nia, razem z awaria odczytu stanu Pro (patrz `except` nizej)."""
    marked = 0
    prog = HOT_LEAD_SILENCE_HOURS * 3600
    rozmowy = list(cw_open_conversations())
    # JEDNO zapytanie zbiorcze na przejscie, nie jedno na rozmowe: sweeper chodzi
    # po WSZYSTKICH otwartych rozmowach kanalu, wiec zapytanie w petli skalowaloby
    # sie z dlugoscia kolejki agenta.
    #
    # Awaria tego odczytu NIE moze zatrzymac przejscia dla starego silnika. Stan
    # Pro moze w danej instalacji w ogole nie istniec (mostek bez Debusia Pro),
    # albo jeszcze nie powstac przy starcie: `init_pro` wola quote_worker, a
    # sweeper startuje obok niego jako osobny watek (bridge.py).
    try:
        pro_z_cena = rozmowy_z_pokazana_cena([c.get("id") for c in rozmowy])
    except Exception as e:
        log("hot_lead_sweeper: nie mozna odczytac stanu Pro, biore sam stary silnik:", repr(e))
        pro_z_cena = set()
    for conv in rozmowy:
        conv_id = conv.get("id")
        if not conv_id or not (_priced(conv_id) or conv_id in pro_z_cena):
            continue   # bez ceny zadnego z botow to nie "goracy lead" tego sweepera
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
