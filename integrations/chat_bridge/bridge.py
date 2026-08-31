# -*- coding: utf-8 -*-
# LACZNIK mostka wielokanalowego Chatwoot:
#  - tworzy Flask app i montuje trasy (webhooki + panel Base),
#  - startuje poller kazdego kanalu z rejestru + worker kolejki wysylki,
#  - serwuje na :5005.
# Dodanie kanalu = nowy modul w channels/ + wpis w channels/REGISTRY (tu zero zmian).
import threading
from flask import Flask
from config import BOT_PRO_AGENT_WEBHOOK_TOKEN, BOT_PRO_INBOXES
from core.db import init_db
from channels import REGISTRY
from worker import worker
from suggest_worker import suggest_worker
from live_worker import live_worker
from quote_worker import quote_worker
from sweeper import sweeper
from hot_lead_sweeper import hot_lead_sweeper
from pro_watchdog import watchdog as pro_watchdog
from bots.knowledge import index_loop
from panels.base_orders import bp as base_orders_bp
from webhooks import bp as webhooks_bp

app = Flask(__name__)
app.register_blueprint(base_orders_bp)
app.register_blueprint(webhooks_bp)


def sprawdz_guard_pro():
    """Guard startowy (Task 7): weryfikacja tokenu webhooka /agent-bot-pro jest WARUNKOWA
    (`if BOT_PRO_AGENT_WEBHOOK_TOKEN and ...` w webhooks.py) — brak tokenu przy WLACZONYCH
    inboksach (BOT_PRO_INBOXES niepuste) oznacza, ze endpoint przyjmuje DOWOLNE zadanie bez
    autoryzacji. Przerywamy start procesu z czytelnym komunikatem zamiast wystawiac dziurawy
    webhook na produkcji — lepiej, zeby caly kontener nie wstal, niz zeby wstal bez ochrony.
    Wydzielone z `if __name__ == "__main__":` do osobnej funkcji, zeby dalo sie to
    przetestowac bez uruchamiania calego procesu (watki/app.run)."""
    if not BOT_PRO_AGENT_WEBHOOK_TOKEN and BOT_PRO_INBOXES:
        raise SystemExit(
            "BOT_PRO_INBOXES ustawione, a BOT_PRO_AGENT_WEBHOOK_TOKEN puste — "
            "webhook /agent-bot-pro stalby otworem. Uzupelnij bridge.env.")


if __name__ == "__main__":
    sprawdz_guard_pro()
    init_db()
    # Poller kazdego zarejestrowanego kanalu w osobnym watku.
    for ch in REGISTRY.values():
        threading.Thread(target=ch.poller, daemon=True).start()
    # Worker kolejki wysylki (wspolny dla wszystkich kanalow).
    threading.Thread(target=worker, daemon=True).start()
    # Worker kolejki podpowiedzi AI + cykliczna indeksacja wiedzy (Help Center).
    threading.Thread(target=suggest_worker, daemon=True).start()
    threading.Thread(target=index_loop, daemon=True).start()
    # Worker kolejki tur konwersacyjnego live-bota.
    threading.Thread(target=live_worker, daemon=True).start()
    # Worker kolejki tur quote-bota (wyceniajacy, live chat testowy).
    threading.Thread(target=quote_worker, daemon=True).start()
    # Sweeper pending: samonaprawa rozmow, ktore utknely bez odpowiedzi bota.
    threading.Thread(target=sweeper, daemon=True).start()
    # Sweeper goracych leadow: rozmowa oddana po cenie quote-bota, klient milczy (LS-04).
    threading.Thread(target=hot_lead_sweeper, daemon=True).start()
    # Watchdog porzuconych rozmow Debusia Pro: bot mowil ostatni, klient milczy
    # dluzej niz BOT_PRO_WATCHDOG_MINUTES -> automatyczny handoff (Task 8).
    threading.Thread(target=pro_watchdog, daemon=True).start()
    app.run(host="0.0.0.0", port=5005, threaded=True)
