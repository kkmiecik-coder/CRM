# -*- coding: utf-8 -*-
# Entrypoint KANDYDATA quote-bota (FAZA 0) — izolowana instancja do testow na skrzynce testowej
# (inbox 18). Startuje webhook Flask + quote_worker + indeksacje bazy wiedzy + watchdog Pro
# (+ init_db). ZERO pollerow OLX/Allegro, live_worker, suggest_worker i sweeperow — zeby NIE
# dublowac produkcji (kontener cw-olx-bridge). Nasluchuje na :5006 (produkcja jest na :5005).
# Konfiguracja przez env (bridge-candidate.env): wlasny BOT_QUOTE_CW_AGENT_TOKEN,
# BOT_QUOTE_AGENT_WEBHOOK_TOKEN, rodzina BOT_PRO_* i osobny BRIDGE_DB (brak kolizji stanu
# z produkcja).
import threading
from flask import Flask
from bots.knowledge import index_loop
from core.db import init_db
# B1: TEN SAM guard startowy Pro co na produkcji (`bridge.py`). Kandydat dzialal
# bez niego, wiec `bridge-candidate.env` z BOT_PRO_INBOXES=18 i pustym
# BOT_PRO_AGENT_WEBHOOK_TOKEN zostawial `/cand/agent-bot-pro` OTWARTY na dowolny
# nieautoryzowany POST — weryfikacja tokenu w webhooks.py jest WARUNKOWA.
# Import z `guard_pro`, NIE z `bridge` (tamten ciagnie rejestr kanalow, wszystkie
# workery i tworzy drugi obiekt Flask).
from guard_pro import sprawdz_guard_pro
from pro_watchdog import watchdog as pro_watchdog
from quote_worker import quote_worker
from webhooks import bp as webhooks_bp

app = Flask(__name__)
app.register_blueprint(webhooks_bp)

if __name__ == "__main__":
    # PIERWSZA instrukcja — przed init_db i przed startem czegokolwiek: wadliwa
    # konfiguracja Pro ma wylaczyc Pro, zanim webhook zdazy przyjac pierwsze zadanie.
    sprawdz_guard_pro()
    init_db()
    # Kolejka tur quote-bota — pollery kanalow i sweepery zostaja na produkcji.
    threading.Thread(target=quote_worker, daemon=True).start()
    # B3: cykliczna indeksacja bazy wiedzy. Kandydat ma WLASNA baze (osobny BRIDGE_DB),
    # wiec tabela `kb_chunks` powstaje pusta i nikt jej nie zapelni bez tego watku.
    # Lancuch: bots_pro/agenci.py -> narzedzia_wiedzy.py -> wiedza.py -> bots.knowledge.
    # retrieve, ktory przy pustej tabeli zwraca [] — a wg docstringu bots_pro/wiedza.py
    # pusta lista NIE jest trybem pracy, tylko STANEM BLEDU: agent wiedzy oddaje wtedy
    # rozmowe czlowiekowi. To ta sama przyczyna, ktora w audycie starego bota dala 65
    # powtorzen jednej formulki. Do tego alert "indeks wiedzy jest PUSTY" zyje WEWNATRZ
    # index_loop, wiec bez tego watku pusta baza jest calkowicie cicha.
    threading.Thread(target=index_loop, daemon=True).start()
    # B4: watchdog porzuconych rozmow Debusia Pro — JEDYNA droga wyjscia z rozmowy, w
    # ktorej bot odezwal sie ostatni, a klient zamilkl (Pro oddaje rozmowe wylacznie
    # z decyzji modelu albo twardych regul WEWNATRZ tury). Bez niego takie rozmowy
    # zostaja w 'pending' bez wlasciciela — audyt: 10 z 24 rozmow w jednym shardzie.
    # Watek sam sie wylacza przy pustym BOT_PRO_INBOXES, wiec jest bezpieczny takze
    # zanim slot kandydata zostanie zajety przez Pro.
    threading.Thread(target=pro_watchdog, daemon=True).start()
    app.run(host="0.0.0.0", port=5006, threaded=True)
