# -*- coding: utf-8 -*-
# Kanal Allegro (Centrum wiadomosci): wysylka z zalacznikami, mark-read, karta oferty, poller.
import time
import traceback
import requests
from config import (ALLEGRO_API, ALLEGRO_ACCEPT, POLL_INTERVAL, CW_ALLEGRO_MSG_INBOX)
from channels.allegro_auth import get_allegro_token, allegro_get
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.util import parse_ts, upsert_thread
from core.chatwoot import ensure_conversation, cw_incoming, conv_exists, clear_thread_conv

name = "allegro_msg"


def allegro_upload_attachment(content, filename, mime):
    """Deklaruje i wgrywa zalacznik do Allegro; zwraca attachmentId albo None."""
    tok = get_allegro_token()
    rd = requests.post(ALLEGRO_API + "/messaging/message-attachments",
                       headers={"Authorization": "Bearer " + tok, "Accept": ALLEGRO_ACCEPT, "Content-Type": ALLEGRO_ACCEPT},
                       json={"fileName": filename, "size": len(content)}, timeout=30)
    if rd.status_code not in (200, 201):
        log("Allegro deklaracja zalacznika fail:", rd.status_code, rd.text[:150]); return None
    aid = rd.json().get("id")
    if not aid:
        return None
    rp = requests.put(ALLEGRO_API + "/messaging/message-attachments/%s" % aid,
                      headers={"Authorization": "Bearer " + tok, "Content-Type": mime or "application/octet-stream"},
                      data=content, timeout=90)
    if rp.status_code not in (200, 201, 204):
        log("Allegro upload zalacznika fail:", rp.status_code, rp.text[:150]); return None
    return aid


def allegro_send(thread_id, text, att_urls=None):
    text = (text or "").strip()
    attach_ids = []
    if att_urls:
        for u in att_urls:
            try:
                resp = requests.get(u, timeout=40)
                if resp.status_code == 200:
                    fn = (u.split("?")[0].rstrip("/").split("/")[-1]) or "plik"
                    aid = allegro_upload_attachment(resp.content, fn, resp.headers.get("Content-Type"))
                    if aid:
                        attach_ids.append(aid)
            except Exception as e:
                log("Allegro pobranie zal. z Chatwoota fail:", repr(e))
    if not text:
        text = "(załącznik)"
    body = {"text": text}
    if attach_ids:
        body["attachments"] = [{"id": a} for a in attach_ids]
    def do(tok):
        return requests.post(ALLEGRO_API + "/messaging/threads/%s/messages" % thread_id,
            headers={"Authorization": "Bearer " + tok, "Accept": ALLEGRO_ACCEPT, "Content-Type": ALLEGRO_ACCEPT},
            json=body, timeout=40)
    r = do(get_allegro_token())
    if r.status_code == 401:
        r = do(get_allegro_token(force=True))
    return r


def allegro_mark_read(thread_id):
    try:
        tok = get_allegro_token()
        requests.put(ALLEGRO_API + "/messaging/threads/%s/read" % thread_id,
                     headers={"Authorization": "Bearer " + tok, "Accept": ALLEGRO_ACCEPT, "Content-Type": ALLEGRO_ACCEPT},
                     json={"read": True}, timeout=15)
    except Exception as e:
        log("Allegro mark-read fail:", repr(e))


def allegro_offer_card(relates_to):
    try:
        off = (relates_to or {}).get("offer")
        if not off or not off.get("id"):
            return None
        oid = off["id"]
        title = None; img = None
        try:
            d = allegro_get("/sale/product-offers/%s" % oid)
            title = d.get("name")
            imgs = d.get("images") or []
            if imgs:
                img = imgs[0] if isinstance(imgs[0], str) else imgs[0].get("url")
        except Exception:
            pass
        return {"text": "Oferta: %s\nLink: https://allegro.pl/oferta/%s" % (title or oid, oid), "image": img}
    except Exception:
        return None


def allegro_poller():
    init_db()
    # czekaj na autoryzacje
    while not meta_get("allegro_refresh_token"):
        time.sleep(10)
    if meta_get("allegro_start_ts") is None:
        meta_set("allegro_start_ts", time.time())
    START_TS = float(meta_get("allegro_start_ts"))
    log("Allegro poller start, START_TS=%s, interval=%ss" % (int(START_TS), POLL_INTERVAL))
    while True:
        try:
            threads = allegro_get("/messaging/threads?limit=20").get("threads", [])
            c = db()
            known = {r["thread_id"]: dict(r) for r in c.execute("SELECT * FROM threads WHERE channel='allegro_msg'").fetchall()}
            c.close()
            for th in threads:
                tid = str(th["id"])
                st = known.get(tid)
                last_dt = th.get("lastMessageDateTime") or ""
                changed = (st is None) or (not th.get("read", True)) or (last_dt > (st.get("last_seen_msg_id") or ""))
                if st is not None and not changed:
                    continue
                msgs = allegro_get("/messaging/threads/%s/messages?limit=20" % tid).get("messages", [])
                msgs = sorted(msgs, key=lambda m: m.get("createdAt") or "")
                if not msgs:
                    continue
                last_seen = st.get("last_seen_msg_id") if st else None
                conv_id = st.get("conv_id") if st else None
                new = []
                for m in msgs:
                    if not (m.get("author") or {}).get("isInterlocutor"):
                        continue  # nasza wiadomosc -> pomijamy (brak echa)
                    cat = m.get("createdAt") or ""
                    ts = parse_ts(cat)
                    if ts is not None and ts <= START_TS:
                        continue
                    if last_seen and cat <= last_seen:
                        continue
                    new.append(m)
                if new:
                    if conv_id and not conv_exists(conv_id):
                        clear_thread_conv("allegro_msg", tid); conv_id = None
                    if not conv_id:
                        login = (th.get("interlocutor") or {}).get("login") or "klient"
                        name = login
                        ident = "allegro-%s-%s" % (login, tid)
                        card = allegro_offer_card(new[0].get("relatesTo"))
                        ctext = card.get("text") if card else None
                        cimg = card.get("image") if card else None
                        conv_id = ensure_conversation("allegro_msg", tid, CW_ALLEGRO_MSG_INBOX, name, ident, ctext, cimg)
                    if conv_id:
                        for m in new:
                            txt = (m.get("text") or "").strip()
                            subj = (m.get("subject") or "").strip()
                            if subj and subj not in txt:
                                txt = (subj + "\n\n" + txt).strip()
                            atts = []
                            for a in (m.get("attachments") or []):
                                if a.get("url"):
                                    atts.append({"name": a.get("fileName") or "plik", "url": a["url"],
                                                 "mime": a.get("mimeType"),
                                                 "headers": {"Authorization": "Bearer " + get_allegro_token()}})
                            if not txt and not atts:
                                txt = "(wiadomosc bez tresci)"
                            cw_incoming(conv_id, txt, atts)
                        log("Allegro watek %s -> %d nowych do conv %s" % (tid, len(new), conv_id))
                upsert_thread(tid, conv_id, (msgs[-1].get("createdAt") or last_dt), None, "allegro_msg")
        except Exception as e:
            log("Allegro poller ERROR:", repr(e)); traceback.print_exc()
        time.sleep(POLL_INTERVAL)


poller = allegro_poller
send = allegro_send
mark_read = allegro_mark_read
