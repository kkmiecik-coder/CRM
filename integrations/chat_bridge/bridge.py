# -*- coding: utf-8 -*-
# LACZNIK mostka wielokanalowego Chatwoot:
#  - tworzy Flask app i montuje trasy (webhooki + panel Base),
#  - startuje poller kazdego kanalu z rejestru + worker kolejki wysylki,
#  - serwuje na :5005.
# Dodanie kanalu = nowy modul w channels/ + wpis w channels/REGISTRY (tu zero zmian).
import threading
from flask import Flask
from config import (BOT_PRO_AGENT_WEBHOOK_TOKEN, BOT_PRO_INBOXES, BOT_QUOTE_NOTE_PERSONAS,
                    BOT_QUOTE_PERSONAS, CW_OLX_INBOX)
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


def _konflikt_olx_pro():
    """Opis konfliktu konfiguracji OLX <-> Debus Pro, albo None gdy go nie ma (U10).

    `BOT_PRO_INBOXES` i `BOT_QUOTE_NOTE_PERSONAS` sa SPRZEZONE, i nic tego nie
    pilnowalo. Poller OLX (`channels/olx.py`, `_enqueue_quote_olx`) ustepuje
    webhookowi WYLACZNIE dzieki warunkowi `if "quote_olx" in
    BOT_QUOTE_NOTE_PERSONAS: return`. Migracja OLX na Pro to naturalny moment,
    w ktorym operator zdejmuje `quote_olx` z tej listy ("OLX juz nie jest w
    trybie notatki") — i wtedy oba tory kolejkuja TE SAMA wiadomosc:

      - poller:  persona="quote_olx", klucz dedupu "olx-<id>"  -> STARY silnik,
      - webhook: persona="olx",       klucz dedupu = mid       -> Debus Pro.

    `quote_seen` ich nie skojarzy (rozne klucze), a `enqueue_quote_turn` przy
    scalaniu zachowuje persone PIERWSZEGO wiersza — o tym, ktory silnik obsluzy
    rozmowe (i czy odpowie PUBLICZNIE, czy notatka), decyduje wyscig.

    Dwie konfiguracje sa bezpieczne i obie akceptujemy: `quote_olx` zostaje w
    trybie notatki (poller ustepuje sam), albo `olx` znika z `BOT_QUOTE_PERSONAS`
    (poller w ogole nie kolejkuje tur). Guard NIE dotyka OLX-a spoza
    `BOT_PRO_INBOXES` — tam zdjecie trybu notatki to normalna konfiguracja
    starego silnika."""
    if not CW_OLX_INBOX:
        return None
    if str(CW_OLX_INBOX).strip() not in BOT_PRO_INBOXES:
        return None
    if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS:
        return None
    if "olx" not in BOT_QUOTE_PERSONAS:
        return None
    return (
        "Inbox OLX (%s) jest w BOT_PRO_INBOXES, ale 'quote_olx' NIE MA w "
        "BOT_QUOTE_NOTE_PERSONAS, a 'olx' jest w BOT_QUOTE_PERSONAS. Poller OLX i "
        "webhook /agent-bot-pro kolejkowalyby wtedy TE SAMA wiadomosc pod roznymi "
        "kluczami dedupu (olx-<id> vs mid Chatwoota) — dedup ich nie skojarzy, a o "
        "tym, ktory silnik obsluzy rozmowe, decydowalby wyscig. Wybierz JEDNO: "
        "dopisz 'quote_olx' do BOT_QUOTE_NOTE_PERSONAS (poller ustepuje webhookowi) "
        "albo usun 'olx' z BOT_QUOTE_PERSONAS (poller nie kolejkuje tur)."
        % CW_OLX_INBOX)


def sprawdz_guard_pro():
    """Guard startowy (Task 7): weryfikacja tokenu webhooka /agent-bot-pro jest WARUNKOWA
    (`if BOT_PRO_AGENT_WEBHOOK_TOKEN and ...` w webhooks.py) — brak tokenu przy WLACZONYCH
    inboksach (BOT_PRO_INBOXES niepuste) oznacza, ze endpoint przyjmuje DOWOLNE zadanie bez
    autoryzacji. Przerywamy start procesu z czytelnym komunikatem zamiast wystawiac dziurawy
    webhook na produkcji — lepiej, zeby caly kontener nie wstal, niz zeby wstal bez ochrony.
    Wydzielone z `if __name__ == "__main__":` do osobnej funkcji, zeby dalo sie to
    przetestowac bez uruchamiania calego procesu (watki/app.run).

    Druga kontrola (U10, recenzja koncowa): sprzezenie BOT_PRO_INBOXES <->
    BOT_QUOTE_NOTE_PERSONAS na OLX — patrz `_konflikt_olx_pro`."""
    if not BOT_PRO_AGENT_WEBHOOK_TOKEN and BOT_PRO_INBOXES:
        raise SystemExit(
            "BOT_PRO_INBOXES ustawione, a BOT_PRO_AGENT_WEBHOOK_TOKEN puste — "
            "webhook /agent-bot-pro stalby otworem. Uzupelnij bridge.env.")
    konflikt = _konflikt_olx_pro()
    if konflikt:
        raise SystemExit(konflikt)


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
