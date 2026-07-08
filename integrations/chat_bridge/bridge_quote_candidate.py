# -*- coding: utf-8 -*-
# Entrypoint KANDYDATA quote-bota (FAZA 0) — izolowana instancja do testow na skrzynce testowej
# (inbox 18). Startuje TYLKO webhook Flask + quote_worker (+ init_db). ZERO pollerow OLX/Allegro,
# live_worker, suggest_worker, sweeper i indeksacji — zeby NIE dublowac produkcji (kontener
# cw-olx-bridge). Nasluchuje na :5006 (produkcja jest na :5005). Konfiguracja przez env
# (bridge-candidate.env): wlasny BOT_QUOTE_CW_AGENT_TOKEN, BOT_QUOTE_AGENT_WEBHOOK_TOKEN i
# osobny BRIDGE_DB (brak kolizji stanu z produkcja).
import threading
from flask import Flask
from core.db import init_db
from quote_worker import quote_worker
from webhooks import bp as webhooks_bp

app = Flask(__name__)
app.register_blueprint(webhooks_bp)

if __name__ == "__main__":
    init_db()
    # Tylko kolejka tur quote-bota — reszta workerow/pollerow zostaje na produkcji.
    threading.Thread(target=quote_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5006, threaded=True)
