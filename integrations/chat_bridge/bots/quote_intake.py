# -*- coding: utf-8 -*-
# Wejscie kolejki quote-bota z oknem ciszy (debounce). Serie szybkich wiadomosci tej samej rozmowy
# scalamy w JEDEN rekord `pending` (tresc akumulowana, next_at przesuwany na now+BOT_DEBOUNCE_SECONDS)
# -> bot odpowiada RAZ na cala serie, a nie na kazda wiadomosc. Dedup po message_id robi WOLAJACY
# (quote_seen) — tu wiadomosc jest juz odduplikowana. Wspoldzielone przez webhook (livechat/Messenger)
# i most OLX; latwe do rozszerzenia na inne kolejki botow.
import json
import time
from config import BOT_DEBOUNCE_SECONDS
from core.db import db
from core.log import log


def _merge_atts(existing_json, new_list):
    """Unia list zalacznikow (JSON) — zachowuje kolejnosc, bez duplikatow."""
    try:
        old = json.loads(existing_json) if existing_json else []
    except Exception:
        old = []
    if not isinstance(old, list):
        old = []
    out = list(old)
    for x in (new_list or []):
        if x not in out:
            out.append(x)
    return out


def enqueue_quote_turn(conv_id, inbox_id, message_id, content, attachments=None, persona="quote", now=None):
    """Wstawia lub SCALA ture quote-bota w quote_queue z oknem ciszy (sliding debounce).
    Gdy istnieje rekord `pending` dla conv_id -> dokleja tresc ("\\n"), aktualizuje message_id i
    zalaczniki (unia), przesuwa next_at=now+BOT_DEBOUNCE_SECONDS. Inaczej (brak pending albo przegrany
    wyscig z workerem) -> INSERT z tym next_at. Persony przy scalaniu NIE zmieniamy (ta sama rozmowa =
    ten sam kanal). Zwraca 'coalesced' albo 'inserted'."""
    now = time.time() if now is None else now
    next_at = now + BOT_DEBOUNCE_SECONDS
    atts_list = attachments if isinstance(attachments, list) else None
    c = db()
    try:
        row = c.execute("SELECT id, content, attachments FROM quote_queue "
                        "WHERE conv_id=? AND status='pending' ORDER BY id LIMIT 1", (conv_id,)).fetchone()
        if row is not None:
            stara = row["content"] or ""
            nowa = (stara + "\n" + content) if (stara and content) else (content or stara)
            merged = _merge_atts(row["attachments"], atts_list)
            # Warunek status='pending' chroni przed wyscigiem: jesli worker wlasnie przejal rekord
            # (processing), rowcount=0 -> spadamy do INSERT (nowa wiadomosc = osobna tura).
            cur = c.execute("UPDATE quote_queue SET content=?, message_id=?, attachments=?, next_at=? "
                            "WHERE id=? AND status='pending'",
                            (nowa, message_id, json.dumps(merged), next_at, row["id"]))
            if cur.rowcount:
                c.commit(); c.close()
                log("quotebot: scalono wiadomosc w oknie ciszy (conv %s, +%ss)" % (conv_id, BOT_DEBOUNCE_SECONDS))
                return "coalesced"
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, attachments, persona, next_at) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (conv_id, inbox_id, message_id, content, json.dumps(atts_list or []), persona, next_at))
        c.commit(); c.close()
        return "inserted"
    except Exception:
        try:
            c.close()
        except Exception:
            pass
        raise
