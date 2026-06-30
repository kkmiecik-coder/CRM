# -*- coding: utf-8 -*-
# Jednorazowy backfill historii rozmow OLX/Allegro do Chatwoota (migracja z Responso).
# Importuje OBIE strony chronologicznie: wiadomosci klienta jako "incoming",
# nasze (sprzedawcy) jako PRYWATNE NOTATKI — webhook Chatwoota ignoruje private,
# wiec NIE ma ryzyka ponownej wysylki do klientow.
#
# Uruchamiac przy ZATRZYMANYM kontenerze glownym (zeby live pollery nie scigaly sie o te same watki),
# najlepiej: docker compose run --rm olx-bridge python backfill.py [--dry-run] [--channel olx|allegro_msg|allegro_dispute]
# Zaklada czysty stan: rozmowy w Chatwoocie skasowane + tabela threads wyczyszczona.
import sys
from datetime import datetime, timezone

from config import (CW_OLX_INBOX, CW_ALLEGRO_MSG_INBOX, CW_ALLEGRO_DISPUTE_INBOX,
                    ALLEGRO_API, ALLEGRO_BETA_ACCEPT)
from core.log import log
from core.db import db, init_db
from core.util import parse_ts, upsert_thread
from core.chatwoot import ensure_conversation, cw_incoming, cw_note
from channels.olx import olx_get
from channels.allegro_auth import get_allegro_token, allegro_get
from channels.allegro_msg import allegro_offer_card
from channels.allegro_dispute import allegro_issue_card


# ---------- BUDOWA REKORDOW (czyste, testowalne) ----------
# Rekord: {"kind": "incoming"|"note", "text": str, "ts": original_ts|None, "m": surowa wiadomosc}

def build_olx_records(msgs):
    """OLX: type=='received' => klient (incoming); pozostale (nasze 'sent') => note. Sort po id."""
    recs = []
    for m in sorted(msgs, key=lambda x: int(x["id"])):
        kind = "incoming" if m.get("type") == "received" else "note"
        recs.append({"kind": kind, "text": (m.get("text") or "").strip(),
                     "ts": m.get("created_at"), "m": m})
    return recs


def build_allegro_msg_records(msgs):
    """Allegro Wiadomosci: author.isInterlocutor => klient (incoming); inaczej => note.
    Temat doklejany do tresci jak w live pollerze. Sort po createdAt."""
    recs = []
    for m in sorted(msgs, key=lambda x: x.get("createdAt") or ""):
        txt = (m.get("text") or "").strip()
        subj = (m.get("subject") or "").strip()
        if subj and subj not in txt:
            txt = (subj + "\n\n" + txt).strip()
        is_buyer = bool((m.get("author") or {}).get("isInterlocutor"))
        recs.append({"kind": "incoming" if is_buyer else "note", "text": txt,
                     "ts": m.get("createdAt"), "m": m})
    return recs


def build_dispute_records(chat):
    """Allegro Dyskusje: role SELLER => nasze (note); ADMIN => mediator (incoming z prefiksem);
    pozostale (BUYER) => klient (incoming). Sort po createdAt."""
    recs = []
    for m in sorted(chat, key=lambda x: x.get("createdAt") or ""):
        role = (m.get("author") or {}).get("role")
        txt = (m.get("text") or "").strip()
        if role == "ADMIN":
            txt = ("[Mediator Allegro] " + txt).strip()
        kind = "note" if role == "SELLER" else "incoming"
        recs.append({"kind": kind, "text": txt, "ts": m.get("createdAt"), "m": m})
    return recs


# ---------- POMOCNICZE ----------

def _note_label(ts):
    """Etykieta naglowka notatki z oryginalnej historii, np. '[My — 2026-05-12 14:03]'."""
    t = parse_ts(ts)
    if t is None:
        return "[My]"
    try:
        return "[My — %s]" % datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "[My]"


def _already_done(channel, tid):
    """Idempotencja: watek z ustawionym conv_id juz zaimportowany — pomijamy przy ponownym uruchomieniu."""
    c = db()
    row = c.execute("SELECT conv_id FROM threads WHERE thread_id=? AND channel=?", (str(tid), channel)).fetchone()
    c.close()
    return bool(row and row["conv_id"])


def _olx_atts(m):
    return m.get("attachments") or []


def _allegro_msg_atts(m):
    atts = []
    for a in (m.get("attachments") or []):
        if a.get("url"):
            atts.append({"name": a.get("fileName") or "plik", "url": a["url"], "mime": a.get("mimeType"),
                         "headers": {"Authorization": "Bearer " + get_allegro_token()}})
    return atts


def _dispute_atts(m):
    atts = []
    for a in (m.get("attachments") or []):
        u = a.get("url") or (ALLEGRO_API + "/sale/issues/attachments/%s" % a.get("id") if a.get("id") else None)
        if u:
            atts.append({"name": a.get("fileName") or "plik", "url": u,
                         "headers": {"Authorization": "Bearer " + get_allegro_token(), "Accept": ALLEGRO_BETA_ACCEPT}})
    return atts


def _post_record(conv_id, rec, atts_fn):
    """Wstawia rekord do rozmowy: klient -> incoming (z zalacznikami); nasze -> notatka prywatna."""
    if rec["kind"] == "incoming":
        atts = atts_fn(rec["m"])
        cw_incoming(conv_id, rec["text"] or "(wiadomosc bez tresci)", atts)
    else:
        body = (_note_label(rec["ts"]) + "\n" + (rec["text"] or "(wiadomosc bez tresci / zalacznik)")).strip()
        cw_note(conv_id, body)


def _summ(recs):
    # incoming = klient + mediator(ADMIN); notatki = nasze (sprzedawca)
    n_in = sum(1 for r in recs if r["kind"] == "incoming")
    return "%d wiad (%d incoming / %d notatki-nasze)" % (len(recs), n_in, len(recs) - n_in)


# ---------- BACKFILL PER KANAL ----------

def backfill_olx(dry):
    threads = olx_get("/threads?limit=50&offset=0").get("data", [])
    log("OLX: %d watkow do przejrzenia" % len(threads))
    for th in threads:
        tid = str(th["id"])
        try:
            if _already_done("olx", tid):
                continue
            msgs = olx_get("/threads/%s/messages?limit=30" % tid).get("data", [])
            if not msgs:
                continue
            recs = build_olx_records(msgs)
            if dry:
                log("[DRY] OLX %s: %s" % (tid, _summ(recs)))
                continue
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
            cname = bname or ("OLX kupujacy %s" % th.get("interlocutor_id"))
            ident = "olx-%s-%s" % (th.get("interlocutor_id"), tid)
            card = ("Oferta: %s\nLink: %s" % (title, url)) if (title and url) else ("Ogloszenie OLX #%s" % th.get("advert_id"))
            conv_id = ensure_conversation("olx", tid, CW_OLX_INBOX, cname, ident, card, img)
            if not conv_id:
                log("OLX %s: nie utworzono rozmowy, pomijam" % tid)
                continue
            for r in recs:
                _post_record(conv_id, r, _olx_atts)
            upsert_thread(tid, conv_id, msgs[-1]["id"], th.get("total_count"), "olx")
            log("OLX %s -> zaimportowano %s (conv %s)" % (tid, _summ(recs), conv_id))
        except Exception as e:
            log("OLX backfill %s pominiety (blad):" % tid, repr(e))
            continue


def backfill_allegro_msg(dry):
    threads = allegro_get("/messaging/threads?limit=20").get("threads", [])
    log("Allegro wiadomosci: %d watkow" % len(threads))
    for th in threads:
        tid = str(th["id"])
        try:
            if _already_done("allegro_msg", tid):
                continue
            msgs = allegro_get("/messaging/threads/%s/messages?limit=20" % tid).get("messages", [])
            if not msgs:
                continue
            recs = build_allegro_msg_records(msgs)
            if dry:
                log("[DRY] Allegro msg %s: %s" % (tid, _summ(recs)))
                continue
            login = (th.get("interlocutor") or {}).get("login") or "klient"
            ident = "allegro-%s-%s" % (login, tid)
            card = allegro_offer_card((msgs[0] or {}).get("relatesTo"))
            ctext = card.get("text") if card else None
            cimg = card.get("image") if card else None
            conv_id = ensure_conversation("allegro_msg", tid, CW_ALLEGRO_MSG_INBOX, login, ident, ctext, cimg)
            if not conv_id:
                log("Allegro msg %s: nie utworzono rozmowy, pomijam" % tid)
                continue
            for r in recs:
                _post_record(conv_id, r, _allegro_msg_atts)
            upsert_thread(tid, conv_id, msgs[-1].get("createdAt"), None, "allegro_msg")
            log("Allegro msg %s -> zaimportowano %s (conv %s)" % (tid, _summ(recs), conv_id))
        except Exception as e:
            log("Allegro msg backfill %s pominiety (blad):" % tid, repr(e))
            continue


def backfill_allegro_dispute(dry):
    issues = allegro_get("/sale/issues?limit=20", beta=True).get("issues", [])
    log("Allegro dyskusje: %d spraw" % len(issues))
    for iss in issues:
        iid = str(iss["id"])
        try:
            if _already_done("allegro_dispute", iid):
                continue
            chat = allegro_get("/sale/issues/%s/chat" % iid, beta=True).get("chat", [])
            if not chat:
                continue
            recs = build_dispute_records(chat)
            if dry:
                log("[DRY] Allegro dyskusja %s: %s" % (iid, _summ(recs)))
                continue
            login = (iss.get("buyer") or {}).get("login") or "klient"
            ident = "allegrodisp-%s-%s" % (login, iid)
            card = allegro_issue_card(iss)
            conv_id = ensure_conversation("allegro_dispute", iid, CW_ALLEGRO_DISPUTE_INBOX, login, ident, card.get("text"), card.get("image"))
            if not conv_id:
                log("Allegro dyskusja %s: nie utworzono rozmowy, pomijam" % iid)
                continue
            chat_sorted = sorted(chat, key=lambda m: m.get("createdAt") or "")
            for r in recs:
                _post_record(conv_id, r, _dispute_atts)
            upsert_thread(iid, conv_id, chat_sorted[-1].get("createdAt"), None, "allegro_dispute")
            log("Allegro dyskusja %s -> zaimportowano %s (conv %s)" % (iid, _summ(recs), conv_id))
        except Exception as e:
            log("Allegro dyskusja backfill %s pominieta (blad):" % iid, repr(e))
            continue


def main(argv):
    dry = "--dry-run" in argv
    channel = None
    if "--channel" in argv:
        try:
            channel = argv[argv.index("--channel") + 1]
        except IndexError:
            pass
    init_db()
    log("=== BACKFILL start (dry_run=%s, channel=%s) ===" % (dry, channel or "wszystkie"))
    if channel in (None, "olx"):
        backfill_olx(dry)
    if channel in (None, "allegro_msg"):
        backfill_allegro_msg(dry)
    if channel in (None, "allegro_dispute"):
        backfill_allegro_dispute(dry)
    log("=== BACKFILL koniec ===")


if __name__ == "__main__":
    main(sys.argv[1:])
