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
    """Dedup + wstawienie/SCALENIE tury quote-bota w quote_queue z oknem ciszy (sliding debounce).
    CALOSC w JEDNEJ transakcji BEGIN IMMEDIATE — serializuje rownolegle enqueue tej samej rozmowy
    (app.run threaded) i wyscig z claimem workera, wiec nie ma lost-update ani cichej utraty
    wiadomosci; dedup (quote_seen) jest atomowy z enqueue (przy bledzie rollback -> retry moze
    odzyskac wiadomosc, nie ginie jak przy osobnym commicie seen).
    Gdy istnieje rekord `pending` dla conv_id -> dokleja tresc ("\\n"), unia zalacznikow, przesuwa
    next_at. Inaczej (brak pending albo rekord juz `processing`) -> INSERT. Persony przy scalaniu NIE
    zmieniamy. message_id = klucz dedupu (goly mid dla livechatu, 'olx-<id>' dla OLX).
    Zwraca 'duplicate' | 'coalesced' | 'inserted'."""
    now = time.time() if now is None else now
    next_at = now + BOT_DEBOUNCE_SECONDS
    atts_list = attachments if isinstance(attachments, list) else None
    c = db()
    c.isolation_level = None   # autocommit -> jawne BEGIN IMMEDIATE/COMMIT dzialaja poprawnie
    try:
        c.execute("BEGIN IMMEDIATE")   # blokada zapisu na czas read-modify-write (busy_timeout=30s)
        try:
            c.execute("INSERT INTO quote_seen(mid) VALUES(?)", (message_id,))
        except Exception:
            c.execute("ROLLBACK"); c.close(); return "duplicate"
        row = c.execute("SELECT id, content, attachments FROM quote_queue "
                        "WHERE conv_id=? AND status='pending' ORDER BY id LIMIT 1", (conv_id,)).fetchone()
        if row is not None:
            stara = row["content"] or ""
            nowa = (stara + "\n" + content) if (stara and content) else (content or stara)
            merged = _merge_atts(row["attachments"], atts_list)
            # Warunek status='pending' chroni przed wyscigiem z workerem: jesli wlasnie przejal
            # rekord (processing), rowcount=0 -> spadamy do INSERT (nowa wiadomosc = osobna tura).
            cur = c.execute("UPDATE quote_queue SET content=?, message_id=?, attachments=?, next_at=? "
                            "WHERE id=? AND status='pending'",
                            (nowa, message_id, json.dumps(merged), next_at, row["id"]))
            if cur.rowcount:
                c.execute("COMMIT"); c.close()
                log("quotebot: scalono wiadomosc w oknie ciszy (conv %s, +%ss)" % (conv_id, BOT_DEBOUNCE_SECONDS))
                return "coalesced"
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, attachments, persona, next_at) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (conv_id, inbox_id, message_id, content, json.dumps(atts_list or []), persona, next_at))
        c.execute("COMMIT"); c.close()
        return "inserted"
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass
        raise
