# -*- coding: utf-8 -*-
# Kanal Allegro Dyskusje/Reklamacje (/sale/issues, beta): poller, wysylka, zalaczniki, karta sprawy.
import time
import traceback
import json
import requests
from config import (ALLEGRO_API, ALLEGRO_ACCEPT, ALLEGRO_BETA_ACCEPT, POLL_INTERVAL, CW_ALLEGRO_DISPUTE_INBOX)
from channels.allegro_auth import get_allegro_token, allegro_get
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.util import parse_ts, upsert_thread
from core.chatwoot import ensure_conversation, cw_incoming, conv_exists, clear_thread_conv

name = "allegro_dispute"


def allegro_issue_upload_attachment(content, filename, mime):
    if len(content) > 2000000:
        log("Allegro issue zalacznik za duzy (>2MB), pomijam"); return None
    tok = get_allegro_token()
    rd = requests.post(ALLEGRO_API + "/sale/issues/attachments",
                       headers={"Authorization": "Bearer " + tok, "Accept": ALLEGRO_BETA_ACCEPT, "Content-Type": ALLEGRO_BETA_ACCEPT},
                       json={"size": len(content), "fileName": filename}, timeout=30)
    if rd.status_code not in (200, 201):
        log("Allegro issue attach declare fail:", rd.status_code, rd.text[:150]); return None
    aid = rd.json().get("id")
    if not aid:
        return None
    rp = requests.put(ALLEGRO_API + "/sale/issues/attachments/%s" % aid,
                      headers={"Authorization": "Bearer " + tok, "Content-Type": mime or "application/octet-stream"},
                      data=content, timeout=90)
    if rp.status_code not in (200, 201, 204):
        log("Allegro issue attach upload fail:", rp.status_code, rp.text[:150]); return None
    return aid


def allegro_dispute_send(issue_id, text, att_urls=None):
    text = (text or "").strip()
    att_ids = []
    if att_urls:
        for u in att_urls:
            try:
                resp = requests.get(u, timeout=40)
                if resp.status_code == 200:
                    fn = (u.split("?")[0].rstrip("/").split("/")[-1]) or "plik"
                    aid = allegro_issue_upload_attachment(resp.content, fn, resp.headers.get("Content-Type"))
                    if aid:
                        att_ids.append(aid)
            except Exception as e:
                log("Allegro issue pobranie zal. z Chatwoota fail:", repr(e))
    if not text:
        text = "(załącznik)"
    body = {"text": text, "type": "REGULAR"}
    if att_ids:
        body["attachments"] = [{"id": a} for a in att_ids]
    def do(tok):
        return requests.post(ALLEGRO_API + "/sale/issues/%s/message" % issue_id,
            headers={"Authorization": "Bearer " + tok, "Accept": ALLEGRO_BETA_ACCEPT, "Content-Type": ALLEGRO_BETA_ACCEPT},
            json=body, timeout=40)
    r = do(get_allegro_token())
    if r.status_code == 401:
        r = do(get_allegro_token(force=True))
    return r


def allegro_issue_card(issue):
    subj = issue.get("subject") or "Dyskusja"
    label = "Reklamacja" if issue.get("type") == "CLAIM" else "Dyskusja"
    lines = ["%s (Allegro): %s" % (label, subj)]
    reason = issue.get("reason")
    if reason:
        lines.append("Powod: " + (reason if isinstance(reason, str) else json.dumps(reason, ensure_ascii=False)[:80]))
    img = None
    off = issue.get("offer") or {}
    oid = off.get("id")
    if oid:
        title = off.get("name")
        try:
            d = allegro_get("/sale/product-offers/%s" % oid)
            title = title or d.get("name")
            imgs = d.get("images") or []
            if imgs:
                img = imgs[0] if isinstance(imgs[0], str) else imgs[0].get("url")
        except Exception:
            pass
        lines.append("Oferta: %s" % (title or oid))
        lines.append("Link: https://allegro.pl/oferta/%s" % oid)
    return {"text": "\n".join(lines), "image": img}


def allegro_dispute_poller():
    init_db()
    while not meta_get("allegro_refresh_token"):
        time.sleep(10)
    if meta_get("allegro_disp_start_ts") is None:
        meta_set("allegro_disp_start_ts", time.time())
    START_TS = float(meta_get("allegro_disp_start_ts"))
    log("Allegro dyskusje poller start, START_TS=%s" % int(START_TS))
    while True:
        try:
            issues = allegro_get("/sale/issues?limit=20", beta=True).get("issues", [])
            c = db()
            known = {r["thread_id"]: dict(r) for r in c.execute("SELECT * FROM threads WHERE channel='allegro_dispute'").fetchall()}
            c.close()
            for iss in issues:
                iid = str(iss["id"])
                st = known.get(iid)
                chat = allegro_get("/sale/issues/%s/chat" % iid, beta=True).get("chat", [])
                chat = sorted(chat, key=lambda m: m.get("createdAt") or "")
                if not chat:
                    continue
                last_seen = st.get("last_seen_msg_id") if st else None
                conv_id = st.get("conv_id") if st else None
                new = []
                for m in chat:
                    if (m.get("author") or {}).get("role") == "SELLER":
                        continue  # nasze wiadomosci - pomijamy (brak echa)
                    cat = m.get("createdAt") or ""
                    ts = parse_ts(cat)
                    if ts is not None and ts <= START_TS:
                        continue
                    if last_seen and cat <= last_seen:
                        continue
                    new.append(m)
                if new:
                    if conv_id and not conv_exists(conv_id):
                        clear_thread_conv("allegro_dispute", iid); conv_id = None
                    if not conv_id:
                        login = (iss.get("buyer") or {}).get("login") or "klient"
                        ident = "allegrodisp-%s-%s" % (login, iid)
                        card = allegro_issue_card(iss)
                        conv_id = ensure_conversation("allegro_dispute", iid, CW_ALLEGRO_DISPUTE_INBOX, login, ident, card.get("text"), card.get("image"))
                    if conv_id:
                        for m in new:
                            txt = (m.get("text") or "").strip()
                            if (m.get("author") or {}).get("role") == "ADMIN":
                                txt = "[Mediator Allegro] " + txt
                            atts = []
                            for a in (m.get("attachments") or []):
                                u = a.get("url") or (ALLEGRO_API + "/sale/issues/attachments/%s" % a.get("id") if a.get("id") else None)
                                if u:
                                    atts.append({"name": a.get("fileName") or "plik", "url": u,
                                                 "headers": {"Authorization": "Bearer " + get_allegro_token(), "Accept": ALLEGRO_BETA_ACCEPT}})
                            if not txt and not atts:
                                txt = "(wiadomosc bez tresci)"
                            cw_incoming(conv_id, txt, atts)
                        log("Allegro dyskusja %s -> %d nowych do conv %s" % (iid, len(new), conv_id))
                upsert_thread(iid, conv_id, chat[-1].get("createdAt"), None, "allegro_dispute")
        except Exception as e:
            log("Allegro dyskusje poller ERROR:", repr(e)); traceback.print_exc()
        time.sleep(max(POLL_INTERVAL, 60))


poller = allegro_dispute_poller
send = allegro_dispute_send
