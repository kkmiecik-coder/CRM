# -*- coding: utf-8 -*-
# LACZNIK mostka wielokanalowego Chatwoot:
#  - tworzy Flask app i montuje trasy (webhooki + panel Base),
#  - startuje poller kazdego kanalu z rejestru + worker kolejki wysylki,
#  - serwuje na :5005.
# Dodanie kanalu = nowy modul w channels/ + wpis w channels/REGISTRY (tu zero zmian).
import threading
from flask import Flask
from core.db import init_db
from channels import REGISTRY
from worker import worker
from suggest_worker import suggest_worker
from live_worker import live_worker
from sweeper import sweeper
from bots.knowledge import index_loop
from panels.base_orders import bp as base_orders_bp
from webhooks import bp as webhooks_bp

app = Flask(__name__)
app.register_blueprint(base_orders_bp)
app.register_blueprint(webhooks_bp)

if __name__ == "__main__":
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
    # Sweeper pending: samonaprawa rozmow, ktore utknely bez odpowiedzi bota.
    threading.Thread(target=sweeper, daemon=True).start()
    app.run(host="0.0.0.0", port=5005, threaded=True)
