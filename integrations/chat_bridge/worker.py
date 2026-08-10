# -*- coding: utf-8 -*-
# Kolejka wysylki: pobiera pending z bridge.db, wysyla przez REGISTRY[channel].send,
# retry+backoff, po MAX_ATTEMPTS alert jako prywatna notatka. Po sukcesie mark-read (jesli kanal ma).
import time
import json
from config import MAX_ATTEMPTS
from core.log import log
from core.db import db, init_db
from core.chatwoot import cw_note, cw_mark_failed, cw_reopen
from core.errors import PermanentSendError
from channels import REGISTRY
from sanitize import sanitize_outgoing


def _zablokuj(row, violations):
    """Tresc lamie regulamin Allegro (dane kontaktowe) — nie wysylamy jej wcale.
    Status 'blocked' jest poza petla retry; agent dostaje notatke, czerwony dymek
    i rozmowe z powrotem w 'open', zeby poprawil tresc i wyslal ponownie."""
    qid, conv_id, channel = row["id"], row["conv_id"], (row["channel"] or "olx")
    opis = ", ".join("%s: %s" % (typ, frag) for typ, frag in violations)
    c = db()
    c.execute("UPDATE queue SET status='blocked', last_error=? WHERE id=?", ("ZABLOKOWANO " + opis, qid))
    c.commit(); c.close()
    log("ZABLOKOWANO wysylke (%s) watek %s — %s" % (channel, row["thread_id"], opis))
    if not conv_id:
        return
    powod = ("Regulamin Allegro zabrania danych kontaktowych poza serwisem. "
             "Wykryto — %s. Usuń je z treści i wyślij ponownie." % opis)
    cw_note(conv_id, "[BLOKADA] Wiadomość NIE została wysłana na Allegro. " + powod)
    cw_mark_failed(conv_id, row["cw_msg_id"] if "cw_msg_id" in row.keys() else None, powod)
    cw_reopen(conv_id)


def _zakoncz_porazka(row, code, detail, powod_dla_agenta, attempts):
    """Wspolne domkniecie nieudanej wysylki: status w kolejce, notatka, czerwony dymek."""
    qid, conv_id, channel = row["id"], row["conv_id"], (row["channel"] or "olx")
    c = db()
    c.execute("UPDATE queue SET status='failed', attempts=?, last_error=? WHERE id=?",
              (attempts, str(code) + " " + str(detail), qid))
    c.commit(); c.close()
    log("WYSYLKA NIEUDANA (%s) watek %s kod %s" % (channel, row["thread_id"], code))
    if conv_id:
        cw_note(conv_id, "[ALERT] Wiadomość NIE dotarła na %s. %s" % (channel.upper(), powod_dla_agenta))
        cw_msg_id = row["cw_msg_id"] if "cw_msg_id" in row.keys() else None
        cw_mark_failed(conv_id, cw_msg_id, powod_dla_agenta)


def process_row(row):
    """Jedna pozycja kolejki: wysylka + rozstrzygniecie (sent / retry / failed)."""
    now = time.time()
    qid, tid, conv_id, content, attempts = row["id"], row["thread_id"], row["conv_id"], row["content"], row["attempts"]
    channel = row["channel"] or "olx"
    # Kontrola tresci agenta PRZED stopka mostu (stopka jest nasza i zaufana):
    # podpis Chatwoota wycinamy, a dane kontaktowe na Allegro wstrzymuja wysylke.
    content, violations = sanitize_outgoing(channel, content)
    if violations:
        _zablokuj(row, violations)
        return
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
    except PermanentSendError as e:
        # Ponawianie nic nie da (np. PDF na OLX) — konczymy od razu i mowimy agentowi dlaczego.
        _zakoncz_porazka(row, "TRWALY", str(e), str(e), attempts + 1)
        return
    except Exception as e:
        ok = False; err = repr(e)
    if ok:
        c = db(); c.execute("UPDATE queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        log("wyslano (%s) watek %s (q#%s)" % (channel, tid, qid))
        # po udanej odpowiedzi oznacz watek jako przeczytany na platformie (jesli kanal to wspiera)
        mr = getattr(ch, "mark_read", None)
        if mr:
            mr(tid)
        return
    attempts += 1
    code = (r.status_code if r is not None else "EXC")
    detail = (r.text[:200] if r is not None else err)
    if attempts >= MAX_ATTEMPTS:
        _zakoncz_porazka(row, code, detail,
                         "Nie udało się wysłać po %d próbach (kod %s) — wyślij ręcznie lub spróbuj ponownie."
                         % (attempts, code), attempts)
    else:
        backoff = min(60, 2 ** attempts)
        c = db()
        c.execute("UPDATE queue SET attempts=?, next_at=?, last_error=? WHERE id=?",
                  (attempts, now + backoff, str(code) + " " + detail, qid))
        c.commit(); c.close()
        log("retry (%s) watek %s za %ss (proba %s kod %s)" % (channel, tid, backoff, attempts, code))


def worker():
    init_db()
    while True:
        try:
            c = db()
            row = c.execute("SELECT * FROM queue WHERE status='pending' AND next_at<=? ORDER BY id LIMIT 1",
                            (time.time(),)).fetchone()
            c.close()
            if not row:
                time.sleep(2); continue
            process_row(row)
        except Exception as e:
            log("worker ERROR:", repr(e)); time.sleep(3)
