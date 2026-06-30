# -*- coding: utf-8 -*-
# Kolejka wysylki: pobiera pending z bridge.db, wysyla przez REGISTRY[channel].send,
# retry+backoff, po MAX_ATTEMPTS alert jako prywatna notatka. Po sukcesie mark-read (jesli kanal ma).
import time
import json
from config import MAX_ATTEMPTS
from core.log import log
from core.db import db, init_db
from core.chatwoot import cw_note
from channels import REGISTRY

def worker():
    init_db()
    while True:
        try:
            now = time.time()
            c = db()
            row = c.execute("SELECT * FROM queue WHERE status='pending' AND next_at<=? ORDER BY id LIMIT 1", (now,)).fetchone()
            c.close()
            if not row:
                time.sleep(2); continue
            qid, tid, conv_id, content, attempts = row["id"], row["thread_id"], row["conv_id"], row["content"], row["attempts"]
            channel = row["channel"] or "olx"
            # Stopka (jesli ustawiona przy kolejkowaniu = wiadomosc agenta) doklejana do tresci.
            footer = row["footer"] if "footer" in row.keys() else None
            if footer:
                content = (content + "\n\n" + footer) if content else footer
            att_urls = []
            try:
                if row["attachments"]:
                    att_urls = json.loads(row["attachments"])
            except Exception:
                att_urls = []
            r = None; err = ""
            ch = REGISTRY.get(channel) or REGISTRY["olx"]
            try:
                r = ch.send(tid, content, att_urls)
                ok = r.status_code in (200, 201)
            except Exception as e:
                ok = False; err = repr(e)
            if ok:
                c = db(); c.execute("UPDATE queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
                log("wyslano (%s) watek %s (q#%s)" % (channel, tid, qid))
                # po udanej odpowiedzi oznacz watek jako przeczytany na platformie (jesli kanal to wspiera)
                mr = getattr(ch, "mark_read", None)
                if mr:
                    mr(tid)
            else:
                attempts += 1
                code = (r.status_code if r is not None else "EXC")
                detail = (r.text[:200] if r is not None else err)
                if attempts >= MAX_ATTEMPTS:
                    c = db(); c.execute("UPDATE queue SET status='failed', attempts=?, last_error=? WHERE id=?", (attempts, str(code) + " " + detail, qid)); c.commit(); c.close()
                    log("WYSYLKA NIEUDANA (%s) watek %s kod %s" % (channel, tid, code))
                    if conv_id:
                        cw_note(conv_id, "[ALERT] Nie udalo sie wyslac wiadomosci na %s (kod %s) po %d probach. Wiadomosc NIE dotarla - wyslij recznie lub sprobuj ponownie." % (channel.upper(), code, attempts))
                else:
                    backoff = min(60, 2 ** attempts)
                    c = db(); c.execute("UPDATE queue SET attempts=?, next_at=?, last_error=? WHERE id=?", (attempts, now + backoff, str(code) + " " + detail, qid)); c.commit(); c.close()
                    log("retry (%s) watek %s za %ss (proba %s kod %s)" % (channel, tid, backoff, attempts, code))
        except Exception as e:
            log("worker ERROR:", repr(e)); time.sleep(3)
