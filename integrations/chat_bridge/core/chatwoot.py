# -*- coding: utf-8 -*-
# Klient Chatwoot Application API: tworzenie/uzupelnianie rozmow, wiadomosci przychodzace,
# prywatne notatki (karty ofert/alerty), sprawdzanie istnienia rozmowy.
import requests
from config import CW_BASE, CW_ACC, CW_TOKEN, BOT_CW_AGENT_TOKEN, BOT_LIVE_CW_AGENT_TOKEN
from core.log import log
from core.db import db
from core.util import upsert_thread, html_to_text


def cw(method, path, payload=None):
    url = "%s/api/v1/accounts/%s%s" % (CW_BASE, CW_ACC, path)
    h = {"api_access_token": CW_TOKEN, "Content-Type": "application/json"}
    return requests.request(method, url, headers=h, json=payload, timeout=25)


def ensure_conversation(channel, thread_id, inbox_id, name, ident, card_text=None, card_image=None, card_image_headers=None):
    tid = str(thread_id)
    c = db()
    row = c.execute("SELECT conv_id FROM threads WHERE thread_id=? AND channel=?", (tid, channel)).fetchone()
    if row and row["conv_id"]:
        c.close(); return row["conv_id"]
    c.close()
    rc = cw("POST", "/contacts", {"inbox_id": int(inbox_id), "name": name, "identifier": ident})
    cid = None
    try:
        d = rc.json().get("payload", {})
        cid = (d.get("contact") or {}).get("id") or d.get("id")
    except Exception:
        pass
    if not cid:
        rs = cw("GET", "/contacts/search?q=" + ident)
        try:
            arr = rs.json().get("payload", [])
            if arr:
                cid = arr[0]["id"]
        except Exception:
            pass
    if not cid:
        log("BLAD: kontakt", channel, rc.status_code, rc.text[:150]); return None
    rconv = cw("POST", "/conversations", {"inbox_id": int(inbox_id), "contact_id": cid})
    conv_id = None
    try:
        conv_id = rconv.json().get("id")
    except Exception:
        pass
    if not conv_id:
        log("BLAD: rozmowa", channel, rconv.status_code, rconv.text[:150]); return None
    upsert_thread(tid, conv_id, None, None, channel)
    if card_text:
        try:
            cw_note(conv_id, card_text, card_image, card_image_headers)
        except Exception:
            pass
    log("utworzono rozmowe conv_id=%s (%s watek %s)" % (conv_id, channel, tid))
    return conv_id


def cw_incoming(conv_id, text, attachments=None):
    text = html_to_text(text)
    if not attachments:
        return cw("POST", "/conversations/%s/messages" % conv_id, {"content": text, "message_type": "incoming"})
    url = "%s/api/v1/accounts/%s/conversations/%s/messages" % (CW_BASE, CW_ACC, conv_id)
    files = []
    for a in attachments:
        u = a.get("url")
        if not u:
            continue
        try:
            resp = requests.get(u, headers=a.get("headers") or {}, timeout=40)
            if resp.status_code == 200:
                files.append(("attachments[]", (a.get("name") or "plik", resp.content,
                              a.get("mime") or resp.headers.get("Content-Type", "application/octet-stream"))))
            else:
                log("pobranie zalacznika kod:", resp.status_code)
        except Exception as e:
            log("pobranie zalacznika nieudane:", repr(e))
    if not files:
        return cw("POST", "/conversations/%s/messages" % conv_id, {"content": text, "message_type": "incoming"})
    return requests.post(url, headers={"api_access_token": CW_TOKEN},
                         data={"content": text or "", "message_type": "incoming"}, files=files, timeout=90)


def cw_note(conv_id, text, image_url=None, image_headers=None):
    if not image_url:
        return cw("POST", "/conversations/%s/messages" % conv_id, {"content": text, "private": True})
    try:
        resp = requests.get(image_url, headers=image_headers or {}, timeout=40)
        if resp.status_code == 200:
            url = "%s/api/v1/accounts/%s/conversations/%s/messages" % (CW_BASE, CW_ACC, conv_id)
            files = [("attachments[]", ("oferta.jpg", resp.content, resp.headers.get("Content-Type", "image/jpeg")))]
            return requests.post(url, headers={"api_access_token": CW_TOKEN},
                                 data={"content": text, "private": "true"}, files=files, timeout=90)
    except Exception as e:
        log("card image fail:", repr(e))
    return cw("POST", "/conversations/%s/messages" % conv_id, {"content": text, "private": True})


def conv_exists(conv_id):
    """Czy rozmowa nadal istnieje w Chatwoocie (mogla zostac usunieta przez agenta)."""
    try:
        return cw("GET", "/conversations/%s" % conv_id).status_code == 200
    except Exception:
        return True  # przy bledzie sieci nie kasujemy mapowania


def clear_thread_conv(channel, tid):
    c = db()
    c.execute("UPDATE threads SET conv_id=NULL WHERE thread_id=? AND channel=?", (str(tid), channel))
    c.commit(); c.close()


def cw_messages(conv_id, limit=12):
    """Historia watku jako [{role, text}] (najstarsze->najnowsze), bez notatek private i pustych."""
    try:
        payload = cw("GET", "/conversations/%s/messages" % conv_id).json().get("payload", [])
    except Exception:
        return []
    out = []
    for m in payload:
        if m.get("private"):
            continue
        txt = html_to_text(m.get("content") or "")
        if not txt:
            continue
        mt = m.get("message_type")
        role = "user" if mt in (0, "incoming") else "assistant"
        out.append({"role": role, "text": txt})
    return out[-limit:]


def cw_contact(conv_id):
    """Tozsamosc klienta z meta.sender: {name, identifier}."""
    try:
        meta = cw("GET", "/conversations/%s" % conv_id).json().get("meta", {})
        sender = meta.get("sender") or {}
        return {"name": sender.get("name") or "", "identifier": sender.get("identifier") or ""}
    except Exception:
        return {"name": "", "identifier": ""}


def cw_inboxes():
    """Katalog inboxow: [{id, name, channel_type}] z Application API; [] przy bledzie."""
    try:
        payload = cw("GET", "/inboxes").json().get("payload", [])
    except Exception:
        return []
    out = []
    for i in payload:
        out.append({"id": i.get("id"), "name": i.get("name") or "",
                    "channel_type": i.get("channel_type") or ""})
    return out


def cw_articles(slug):
    """Opublikowane artykuly Help Center danego portalu: [{id, title, content}]."""
    if not slug:
        return []
    try:
        payload = cw("GET", "/portals/%s/articles" % slug).json().get("payload", [])
    except Exception:
        return []
    out = []
    for a in payload:
        status = a.get("status")
        if status not in (None, 1, "published"):
            continue
        out.append({"id": a.get("id"), "title": a.get("title") or "",
                    "content": html_to_text(a.get("content") or "")})
    return out


def cw_bot_handoff(conv_id, token=None):
    """Oddaje rozmowe z 'pending' do agentow (status open). Token z parametru (live-bot)
    lub domyslnie token bota-podpowiadacza (fallback: admin). Nigdy nie rzuca."""
    tok = token or BOT_CW_AGENT_TOKEN or CW_TOKEN
    try:
        url = "%s/api/v1/accounts/%s/conversations/%s/toggle_status" % (CW_BASE, CW_ACC, conv_id)
        r = requests.post(url, headers={"api_access_token": tok, "Content-Type": "application/json"},
                          json={"status": "open"}, timeout=20)
        if r.status_code != 200:
            log("bot_handoff kod:", r.status_code, r.text[:150]); return False
        return True
    except Exception as e:
        log("bot_handoff blad:", repr(e)); return False


def cw_agent_reply(conv_id, text):
    """Publiczna odpowiedz live-bota do klienta (message_type=outgoing, token live-bota).
    Nigdy nie rzuca — True gdy 200, inaczej False + log."""
    tok = BOT_LIVE_CW_AGENT_TOKEN or CW_TOKEN
    try:
        url = "%s/api/v1/accounts/%s/conversations/%s/messages" % (CW_BASE, CW_ACC, conv_id)
        r = requests.post(url, headers={"api_access_token": tok, "Content-Type": "application/json"},
                          json={"content": text, "message_type": "outgoing"}, timeout=25)
        if r.status_code not in (200, 201):
            log("agent_reply kod:", r.status_code, r.text[:150]); return False
        return True
    except Exception as e:
        log("agent_reply blad:", repr(e)); return False


def cw_conv_status(conv_id):
    """Status rozmowy ('pending'/'open'/'resolved'/'snoozed') lub None przy bledzie."""
    try:
        return cw("GET", "/conversations/%s" % conv_id).json().get("status")
    except Exception:
        return None


def cw_pending_conversations(max_pages=5):
    """Rozmowy w statusie pending: [{id, inbox_id, last_msg_type, last_msg_ts}].
    Czyta liste stronami (Application API); przerywa na pustej/niepelnej stronie; [] przy bledzie."""
    out = []
    for page in range(1, max_pages + 1):
        try:
            data = cw("GET", "/conversations?status=pending&assignee_type=all&page=%s" % page).json().get("data", {})
        except Exception:
            break
        payload = data.get("payload") or []
        if not payload:
            break
        for conv in payload:
            last = conv.get("last_non_activity_message") or {}
            out.append({"id": conv.get("id"),
                        "inbox_id": conv.get("inbox_id"),
                        "last_msg_type": last.get("message_type"),
                        "last_msg_ts": last.get("created_at") or conv.get("timestamp") or 0})
        if len(payload) < 25:  # Chatwoot stronicuje po 25 — niepelna strona = ostatnia
            break
    return out
