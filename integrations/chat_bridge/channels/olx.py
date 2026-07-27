# -*- coding: utf-8 -*-
# Kanal OLX: token (refresh), GET z retry, wysylka, mark-read, poller odbioru.
import time
import threading
import traceback
import requests
from config import (OLX_CLIENT_ID, OLX_CLIENT_SECRET, OLX_REFRESH_TOKEN,
                    OLX_TOKEN_URL, OLX_API_BASE, POLL_INTERVAL, CW_OLX_INBOX,
                    BOT_QUOTE_PERSONAS)
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.util import parse_ts, upsert_thread, deliver_in_order
from core.chatwoot import ensure_conversation, cw_incoming, conv_exists, clear_thread_conv
from core.http import get_with_retry
from bots.quote_intake import enqueue_quote_turn

name = "olx"
_token = {"access": None, "exp": 0}
_tlock = threading.Lock()


def _refresh_token():
    """Aktualny refresh token: baza (rotowany) > bridge.env (bootstrap po wdrozeniu)."""
    return meta_get("olx_refresh_token") or OLX_REFRESH_TOKEN


def get_access_token(force=False):
    with _tlock:
        now = time.time()
        if not force and _token["access"] and now < _token["exp"] - 60:
            return _token["access"]
        rt = _refresh_token()
        r = requests.post(OLX_TOKEN_URL, data={
            "grant_type": "refresh_token", "client_id": OLX_CLIENT_ID,
            "client_secret": OLX_CLIENT_SECRET, "refresh_token": rt,
        }, headers={"Version": "2.0"}, timeout=20)
        if r.status_code >= 400:
            # Slad dla alertu: pad autoryzacji ubija OLX w calosci (wysylka I poller),
            # a bez tego znacznika nikt sie o tym nie dowie (awaria 26.07 = ~26 h ciszy).
            # Tokenu NIE kasujemy — 400 bywa tez przejsciowe po stronie OLX.
            if not meta_get("olx_auth_error"):
                meta_set("olx_auth_error", now)
            log("OLX AUTORYZACJA PADLA: HTTP %s %s" % (r.status_code, (r.text or "")[:200]))
        r.raise_for_status()
        t = r.json()
        _token["access"] = t["access_token"]
        _token["exp"] = now + int(t.get("expires_in", 3600))
        # OLX rotuje refresh token przy odswiezaniu, a stary zyje twarde 30 dni
        # (2592000 s) od wydania. Bez zapisu jedziemy na pierwszym tokenie az do
        # jego wygasniecia — tak umarl kanal 26.07.2026. Zapis resetuje zegar.
        nowy = t.get("refresh_token")
        if nowy and nowy != rt:
            meta_set("olx_refresh_token", nowy)
            meta_set("olx_refresh_token_ts", now)
            log("OLX refresh token zrotowany i zapisany")
        elif not meta_get("olx_refresh_token") and rt:
            meta_set("olx_refresh_token", rt)
        if meta_get("olx_auth_error"):
            meta_set("olx_auth_error", "")
            log("OLX autoryzacja odzyskana")
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
    # OLX od ~2026-07-14 odrzuca (400 Bad Request, detail "Forbidden") wysylke do watku
    # z nieprzeczytanymi wiadomosciami. mark-as-read musi byc PRZED wysylka (dotad byl
    # tylko po udanej — za pozno). Stan read po stronie OLX propaguje sie z opoznieniem
    # (eventual consistency) — ewentualny pierwszy 400 domyka retry+backoff workera,
    # ktory przy kazdej probie znow przejdzie przez mark-as-read.
    olx_mark_read(thread_id)
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


def _mark_quote_olx_eligible(conv_id):
    """Oznacza rozmowe OLX jako SWIEZA (utworzona po go-live) — tylko takie obsluguje quote-bot.
    Wolane przez poller w chwili UTWORZENIA rozmowy, gdy bot jest wlaczony. Nigdy nie rzuca."""
    if not conv_id:
        return
    try:
        c = db()
        c.execute("INSERT OR IGNORE INTO quote_olx_conv(conv_id, created_at) VALUES(?, ?)",
                  (conv_id, time.time()))
        c.commit(); c.close()
    except Exception as e:
        log("quote-olx: mark eligible blad (pomijam):", repr(e))


def _quote_olx_conv_eligible(conv_id):
    """True tylko dla rozmow OLX oznaczonych jako swieze (utworzone po go-live). Rozmowy
    sprzed go-live nie sa oznaczone -> bot ich nie rusza nawet przy nowej wiadomosci; watki
    przejete przez czlowieka chroni osobno status-gate pending (run_quote_turn). Blad odczytu
    -> False (bezpieczniej zamilczec niz wskoczyc w cudza rozmowe)."""
    if not conv_id:
        return False
    try:
        c = db()
        row = c.execute("SELECT 1 FROM quote_olx_conv WHERE conv_id=?", (conv_id,)).fetchone()
        c.close()
        return row is not None
    except Exception:
        return False


def _enqueue_quote_olx(conv_id, olx_msg_id, content, att_urls=None):
    """Wyzwala ture quote-bota dla PRZYCHODZACEJ wiadomosci OLX — Z MOSTU (nie z webhooka
    Chatwoota; odpornosc na D1: most i tak widzi kazda wiadomosc OLX). Gate wlaczenia:
    'olx' in BOT_QUOTE_PERSONAS (kill-switch bez zmiany kodu). Dedup po OLX msg id (jedno
    zrodlo -> dokladnie raz). Tag persona=quote_olx -> worker dobierze caps i prompt OLX.
    NIGDY nie rzuca — blad kolejkowania nie moze zaklocic dostawy wiadomosci do Chatwoota."""
    try:
        if "olx" not in BOT_QUOTE_PERSONAS:
            return
        content = (content or "").strip()
        if not conv_id or olx_msg_id is None or (not content and not att_urls):
            return
        if not _quote_olx_conv_eligible(conv_id):
            return
        seen_key = "olx-%s" % olx_msg_id  # prefiks kanalu: brak kolizji z mid Chatwoota + klucz dedupu
        # Dedup + okno ciszy (scalanie serii w jedna ture) — atomowo w enqueue_quote_turn.
        if enqueue_quote_turn(conv_id, CW_OLX_INBOX, seen_key, content,
                              attachments=(att_urls or []), persona="quote_olx") == "duplicate":
            return
        log("quote-olx: zakolejkowano ture (conv %s, msg %s)" % (conv_id, olx_msg_id))
    except Exception as e:
        log("quote-olx: enqueue blad (pomijam):", repr(e))


def _should_mark_eligible(st):
    """Czy oznaczyc rozmowe jako swieza (obslugiwana przez quote-bota). TYLKO gdy watek jest
    NIGDY wczesniej niewidziany przez most (st is None) i bot OLX wlaczony. Self-heal
    (odtworzenie conv ZNANEGO watku, np. po usunieciu rozmowy w Chatwoocie) NIE oznacza —
    inaczej watek sprzed go-live wskoczylby do bota (review FAZY 2/3, #1)."""
    return st is None and "olx" in BOT_QUOTE_PERSONAS


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
                            # Swieza rozmowa (watek nigdy niewidziany, st is None) i bot OLX
                            # wlaczony -> oznacz jako obslugiwana (FAZA 3a: tylko po go-live).
                            # NIE oznaczamy przy self-heal recreate znanego watku (review #1).
                            if conv_id and _should_mark_eligible(st):
                                _mark_quote_olx_eligible(conv_id)
                        if conv_id:
                            def _send(m):
                                txt = (m.get("text") or "").strip()
                                atts = m.get("attachments") or []
                                if not txt and not atts:
                                    txt = "(wiadomosc bez tresci)"
                                ok = cw_incoming(conv_id, txt, atts)
                                if ok:
                                    # Po dostarczeniu do Chatwoota wyzwol ture quote-bota (gate,
                                    # dedup i eligibility rozstrzygaja sie w _enqueue_quote_olx).
                                    att_urls = [a.get("url") for a in atts
                                                if isinstance(a, dict) and a.get("url")]
                                    _enqueue_quote_olx(conv_id, m.get("id"),
                                                       m.get("text") or "", att_urls)
                                return ok
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
