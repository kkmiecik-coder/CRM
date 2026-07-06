# -*- coding: utf-8 -*-
# Kolejka tur live-bota: pobiera pending z live_queue, wola run_livechat_turn,
# retry+backoff; po wyczerpaniu prob -> failed + przeprosiny i handoff do agenta.
import time
from config import BOT_MAX_ATTEMPTS
from core.log import log
from core.db import db, init_db
from bots.livechat import run_livechat_turn, handoff_with_apology


def process_one(now):
    # Przetwarza jeden rekord pending. Zwraca True gdy cos bylo, False gdy kolejka pusta.
    c = db()
    row = c.execute("SELECT * FROM live_queue WHERE status='pending' AND next_at<=? ORDER BY id LIMIT 1",
                    (now,)).fetchone()
    c.close()
    if not row:
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    try:
        run_livechat_turn(conv_id, inbox_id, mid, content, attachments=row["attachments"])
        c = db(); c.execute("UPDATE live_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        log("livechat: tura przetworzona (conv %s)" % conv_id)
    except Exception as e:
        attempts += 1
        err = repr(e)
        if attempts >= BOT_MAX_ATTEMPTS:
            c = db(); c.execute("UPDATE live_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                                (attempts, err, qid)); c.commit(); c.close()
            log("livechat: tura NIEUDANA (conv %s): %s" % (conv_id, err))
            try:
                handoff_with_apology(conv_id)
            except Exception:
                pass
        else:
            backoff = min(60, 2 ** attempts)
            c = db(); c.execute("UPDATE live_queue SET attempts=?, next_at=?, last_error=? WHERE id=?",
                                (attempts, now + backoff, err, qid)); c.commit(); c.close()
            log("livechat: retry (conv %s) za %ss (proba %s): %s" % (conv_id, backoff, attempts, err))
    return True


def live_worker():
    init_db()
    while True:
        try:
            if not process_one(time.time()):
                time.sleep(2)
        except Exception as e:
            log("live_worker ERROR:", repr(e)); time.sleep(3)
