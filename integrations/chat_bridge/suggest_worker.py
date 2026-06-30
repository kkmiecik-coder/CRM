# -*- coding: utf-8 -*-
# Kolejka podpowiedzi AI: pobiera pending z suggest_queue, woła run_suggestion,
# retry+backoff; po wyczerpaniu prob -> failed + prywatna notatka z powodem.
import time
from config import BOT_MAX_ATTEMPTS
from core.log import log
from core.db import db, init_db
from core.chatwoot import cw_note
from bots.suggester import run_suggestion


def process_one(now):
    # Przetwarza jeden rekord pending. Zwraca True gdy cos bylo, False gdy kolejka pusta.
    c = db()
    row = c.execute("SELECT * FROM suggest_queue WHERE status='pending' AND next_at<=? ORDER BY id LIMIT 1",
                    (now,)).fetchone()
    c.close()
    if not row:
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    try:
        run_suggestion(conv_id, inbox_id, mid, content)
        c = db(); c.execute("UPDATE suggest_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        log("podpowiedz AI gotowa (inbox %s, conv %s)" % (inbox_id, conv_id))
    except Exception as e:
        attempts += 1
        err = repr(e)
        if attempts >= BOT_MAX_ATTEMPTS:
            c = db(); c.execute("UPDATE suggest_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                                (attempts, err, qid)); c.commit(); c.close()
            log("podpowiedz AI NIEUDANA (conv %s): %s" % (conv_id, err))
            try:
                cw_note(conv_id, "🤖 [AI] Nie udało się wygenerować podpowiedzi: %s" % err)
            except Exception:
                pass
        else:
            backoff = min(60, 2 ** attempts)
            c = db(); c.execute("UPDATE suggest_queue SET attempts=?, next_at=?, last_error=? WHERE id=?",
                                (attempts, now + backoff, err, qid)); c.commit(); c.close()
            log("podpowiedz AI retry (conv %s) za %ss (proba %s): %s" % (conv_id, backoff, attempts, err))
    return True


def suggest_worker():
    init_db()
    while True:
        try:
            if not process_one(time.time()):
                time.sleep(2)
        except Exception as e:
            log("suggest_worker ERROR:", repr(e)); time.sleep(3)
