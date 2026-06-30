# -*- coding: utf-8 -*-
# Kanal OLX: token (refresh), GET z retry, wysylka, mark-read, poller odbioru.
import time
import threading
import traceback
import requests
from config import (OLX_CLIENT_ID, OLX_CLIENT_SECRET, OLX_REFRESH_TOKEN,
                    OLX_TOKEN_URL, OLX_API_BASE, POLL_INTERVAL, CW_OLX_INBOX)
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.util import parse_ts, upsert_thread, deliver_in_order
from core.chatwoot import ensure_conversation, cw_incoming, conv_exists, clear_thread_conv
from core.http import get_with_retry

name = "olx"
_token = {"access": None, "exp": 0}
_tlock = threading.Lock()


def get_access_token(force=False):
    with _tlock:
        now = time.time()
        if not force and _token["access"] and now < _token["exp"] - 60:
            return _token["access"]
        r = requests.post(OLX_TOKEN_URL, data={
            "grant_type": "refresh_token", "client_id": OLX_CLIENT_ID,
            "client_secret": OLX_CLIENT_SECRET, "refresh_token": OLX_REFRESH_TOKEN,
        }, headers={"Version": "2.0"}, timeout=20)
        r.raise_for_status()
        t = r.json()
        _token["access"] = t["access_token"]
        _token["exp"] = now + int(t.get("expires_in", 3600))
        log("OLX access token odswiezony")
        return _token["access"]


def olx_get(path, _tries=3):
    # GET do OLX z retry+backoffem (przejsciowe 400/401/429/5xx) — logika w core/http.
    def headers_fn(force_refresh=False):
        at = get_access_token(force=force_refresh)
        return {"Authorization": "Bearer " + at, "Version": "2.0", "Accept": "application/json"}
    r = get_with_retry(OLX_API_BASE + path, headers_fn, tries=_tries, label="OLX " + path)
    return r.json()


def olx_send(thread_id, text, att_urls=None):
    text = (text or "").strip()
    if not text and att_urls:
        text = "(załącznik)"
    body = {"text": text}
    if att_urls:
        body["attachments"] = [{"url": u} for u in att_urls]
    def do(tok):
        return requests.post(OLX_API_BASE + "/threads/%s/messages" % thread_id,
            headers={"Authorization": "Bearer " + tok, "Version": "2.0", "Content-Type": "application/json"},
            json=body, timeout=30)
    r = do(get_access_token())
    if r.status_code == 401:
        r = do(get_access_token(force=True))
    return r


def olx_mark_read(thread_id):
    try:
        tok = get_access_token()
        requests.post(OLX_API_BASE + "/threads/%s/commands" % thread_id,
                      headers={"Authorization": "Bearer " + tok, "Version": "2.0", "Content-Type": "application/json"},
                      json={"command": "mark-as-read"}, timeout=15)
    except Exception as e:
        log("OLX mark-read fail:", repr(e))


def olx_poller():
    init_db()
    if meta_get("olx_start_ts") is None:
        meta_set("olx_start_ts", time.time())
    START_TS = float(meta_get("olx_start_ts"))
    log("OLX poller start, START_TS=%s, interval=%ss" % (int(START_TS), POLL_INTERVAL))
    while True:
        try:
            data = olx_get("/threads?limit=50&offset=0").get("data", [])
            c = db()
            known = {r["thread_id"]: dict(r) for r in c.execute("SELECT * FROM threads WHERE channel='olx'").fetchall()}
            c.close()
            for th in data:
                tid = str(th["id"])
                st = known.get(tid)
                # Nowe wiadomosci wykrywamy po zmianie total_count (last_seen_msg_id i tak deduplikuje).
                # NIE po unread_count>0: watek czekajacy na odpowiedz agenta ma unread>0 w KAZDYM cyklu,
                # co wczesniej wymuszalo zbedny fetch /messages co 25s i nasilalo przejsciowe bledy OLX.
                changed = (st is None) or (st.get("total_count") != th.get("total_count"))
                if st is not None and not changed:
                    continue
                # Izolacja per-watek: przejsciowy blad jednego watku nie przerywa calego cyklu.
                try:
                    msgs = sorted(olx_get("/threads/%s/messages?limit=30" % tid).get("data", []), key=lambda m: int(m["id"]))
                    if not msgs:
                        continue
                    last_seen = st.get("last_seen_msg_id") if st else None
                    conv_id = st.get("conv_id") if st else None
                    all_ok = True; delivered_id = None
                    new = []
                    for m in msgs:
                        if m.get("type") != "received":
                            continue
                        if last_seen is not None and int(m["id"]) <= int(last_seen):
                            continue
                        ts = parse_ts(m.get("created_at"))
                        if ts is not None and ts <= START_TS:
                            continue
                        new.append(m)
                    if new:
                        if conv_id and not conv_exists(conv_id):
                            clear_thread_conv("olx", tid); conv_id = None
                        if not conv_id:
                            bname = None
                            try:
                                bname = (olx_get("/users/%s" % th.get("interlocutor_id")).get("data") or {}).get("name")
                            except Exception:
                                pass
                            title = url = img = None
                            try:
                                ad = olx_get("/adverts/%s" % th.get("advert_id")).get("data") or {}
                                title = ad.get("title"); url = ad.get("url")
                                imgs = ad.get("images") or []
                                if imgs:
                                    img = imgs[0].get("url")
                            except Exception:
                                pass
                            name = bname or ("OLX kupujacy %s" % th.get("interlocutor_id"))
                            ident = "olx-%s-%s" % (th.get("interlocutor_id"), tid)
                            card = ("Oferta: %s\nLink: %s" % (title, url)) if (title and url) else ("Ogloszenie OLX #%s" % th.get("advert_id"))
                            conv_id = ensure_conversation("olx", tid, CW_OLX_INBOX, name, ident, card, img)
                        if conv_id:
                            def _send(m):
                                txt = (m.get("text") or "").strip()
                                atts = m.get("attachments") or []
                                if not txt and not atts:
                                    txt = "(wiadomosc bez tresci)"
                                return cw_incoming(conv_id, txt, atts)
                            delivered_id, all_ok = deliver_in_order(new, lambda m: m["id"], _send)
                            if delivered_id is not None:
                                log("OLX watek %s -> dostarczono do msg %s (conv %s)" % (tid, delivered_id, conv_id))
                            if not all_ok:
                                log("OLX watek %s: dostawa do Chatwoota wstrzymana — wodowskaz nieprzesuwany" % tid)
                        else:
                            all_ok = False  # brak rozmowy => nic nie dostarczono, ponowimy w kolejnym cyklu
                    # Wodowskaz: po pelnej dostawie (lub gdy nie bylo nowych) zapisujemy biezacy stan watku.
                    # Po czesciowej/zerowej dostawie cofamy last_seen do ostatniej DOSTARCZONEJ wiadomosci
                    # i NIE ruszamy total_count, by changed=True wymusilo ponowienie w kolejnym cyklu.
                    if all_ok:
                        upsert_thread(tid, conv_id, msgs[-1]["id"], th.get("total_count"), "olx")
                    else:
                        ls = delivered_id if delivered_id is not None else last_seen
                        upsert_thread(tid, conv_id, ls, None, "olx")
                except Exception as e:
                    log("OLX watek %s pominiety (blad przejsciowy):" % tid, repr(e))
                    continue
        except Exception as e:
            log("OLX poller ERROR:", repr(e)); traceback.print_exc()
        time.sleep(POLL_INTERVAL)


# Kontrakt kanalu (uzywany przez lacznik i worker):
poller = olx_poller
send = olx_send
mark_read = olx_mark_read
