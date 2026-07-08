# -*- coding: utf-8 -*-
# Kolejka tur quote-bota: pobiera pending z quote_queue, wola run_quote_turn,
# retry+backoff; po wyczerpaniu prob -> failed + przeprosiny i handoff do agenta.
import time
from config import BOT_MAX_ATTEMPTS
from core.log import log
from core.db import db, init_db
from bots.quotebot import run_quote_turn, handoff_with_apology

_STALE_PROCESSING = 180   # rekord 'processing' bez postepu dluzej niz tyle sekund -> odzyskujemy


def process_one(now):
    # Przetwarza jeden rekord. Zwraca True gdy cos wzieto/probowano, False gdy nic gotowego.
    c = db()
    # Stale-recovery (AR-04): rekord utknal w 'processing' (crash/restart w trakcie tury) -> pending.
    c.execute("UPDATE quote_queue SET status='pending' WHERE status='processing' AND next_at<=?",
              (now - _STALE_PROCESSING,))
    # Szeregowanie per conv_id (API-06): nie bierzemy nowszego rekordu rozmowy, gdy starszy tej samej
    # rozmowy jeszcze czeka (pending/processing) — zachowujemy kolejnosc wiadomosci.
    row = c.execute(
        "SELECT * FROM quote_queue q WHERE q.status='pending' AND q.next_at<=? "
        "AND NOT EXISTS (SELECT 1 FROM quote_queue e WHERE e.conv_id=q.conv_id AND e.id<q.id "
        "AND e.status IN ('pending','processing')) ORDER BY q.id LIMIT 1", (now,)).fetchone()
    if not row:
        c.commit(); c.close()
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    # Atomowy claim (API-09/AR-04): tylko jeden worker przetworzy rekord — deploy/overlap kontenerow
    # nie zdubluje tury. next_at = deadline claimu (stale-recovery po _STALE_PROCESSING).
    cur = c.execute("UPDATE quote_queue SET status='processing', next_at=? WHERE id=? AND status='pending'",
                    (now + _STALE_PROCESSING, qid))
    claimed = cur.rowcount
    c.commit(); c.close()
    if not claimed:
        return True   # ktos inny zajal rekord w miedzyczasie — sprobuj kolejny obieg
    try:
        run_quote_turn(conv_id, inbox_id, mid, content, attachments=row["attachments"])
        c = db(); c.execute("UPDATE quote_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        log("quotebot: tura przetworzona (conv %s)" % conv_id)
    except Exception as e:
        attempts += 1
        err = repr(e)
        if attempts >= BOT_MAX_ATTEMPTS:
            c = db(); c.execute("UPDATE quote_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                                (attempts, err, qid)); c.commit(); c.close()
            log("quotebot: tura NIEUDANA (conv %s): %s" % (conv_id, err))
            try:
                handoff_with_apology(conv_id)
            except Exception:
                pass
        else:
            backoff = min(60, 2 ** attempts)
            # Wracamy do 'pending' (claim ustawil 'processing') z opoznieniem backoff.
            c = db(); c.execute("UPDATE quote_queue SET status='pending', attempts=?, next_at=?, "
                                "last_error=? WHERE id=?", (attempts, now + backoff, err, qid))
            c.commit(); c.close()
            log("quotebot: retry (conv %s) za %ss (proba %s): %s" % (conv_id, backoff, attempts, err))
    return True


def quote_worker():
    # Demonu wątku: ciągły loop przetwarzający quote_queue.
    init_db()
    while True:
        try:
            if not process_one(time.time()):
                time.sleep(2)
        except Exception as e:
            log("quote_worker ERROR:", repr(e)); time.sleep(3)
