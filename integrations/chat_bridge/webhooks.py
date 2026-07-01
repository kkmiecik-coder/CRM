# -*- coding: utf-8 -*-
# Trasy HTTP mostka: webhook konta Chatwoota (outgoing -> kolejka wysylki), webhook Agent Bota
# (/agent-bot -> handoff + kolejka podpowiedzi AI), callback OAuth Allegro, health.
import time
import json
from flask import Blueprint, request, jsonify
from config import WEBHOOK_TOKEN, BOT_AGENT_WEBHOOK_TOKEN
from core.log import log
from core.db import db
from core.chatwoot import cw_bot_handoff
from bots.channel_resolver import persona_for
from footer import build_footer
from channels.allegro_auth import exchange_authorization_code

bp = Blueprint("webhooks", __name__)


# ---------- AGENT BOT WEBHOOK ----------
def _process_agent_bot(d):
    # Webhook natywnego Agent Bota: ZAWSZE handoff (rozmowa nie utyka w pending),
    # a jesli inbox ma zmapowana persone -> kolejka podpowiedzi (prywatna notatka).
    if d.get("event") != "message_created":
        return
    mtype = str(d.get("message_type"))
    if mtype not in ("incoming", "0") or d.get("private"):
        return
    conv = d.get("conversation") or {}
    conv_id = conv.get("id") or d.get("conversation_id")
    inbox_id = str(conv.get("inbox_id") or (d.get("inbox") or {}).get("id") or "")
    content = (d.get("content") or "").strip()
    mid = str(d.get("id") or "")
    if not conv_id or not inbox_id:
        return
    # Oddaj rozmowe agentom niezaleznie od persony/tresci (idempotentne dla juz otwartej).
    cw_bot_handoff(conv_id)
    if not content or not mid:
        return
    persona = persona_for(inbox_id)
    if not persona:
        log("agent-bot: niezmapowany inbox %s - bez podpowiedzi" % inbox_id)
        return
    c = db()
    try:
        c.execute("INSERT INTO bot_seen(mid) VALUES(?)", (mid,)); c.commit()
    except Exception:
        c.close(); return  # duplikat
    c.execute("INSERT INTO suggest_queue(conv_id, inbox_id, message_id, content, next_at) VALUES(?,?,?,?,0)",
              (conv_id, inbox_id, mid, content))
    c.commit(); c.close()
    log("agent-bot: zakolejkowano podpowiedz (inbox %s, conv %s)" % (inbox_id, conv_id))


@bp.post("/agent-bot")
def agent_bot():
    if BOT_AGENT_WEBHOOK_TOKEN and request.args.get("token") != BOT_AGENT_WEBHOOK_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    _process_agent_bot(d)
    return jsonify(ok=True)


# ---------- WEBHOOK KONTA (Chatwoot -> most) ----------
@bp.post("/chatwoot-webhook")
def hook():
    if WEBHOOK_TOKEN and request.args.get("token") != WEBHOOK_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    if d.get("event") != "message_created":
        return jsonify(ok=True)
    # Tylko outgoing (wiadomosci agenta do klienta) -> kolejka wysylki na platfomy.
    if str(d.get("message_type")) not in ("outgoing", "1"):
        return jsonify(ok=True)
    if d.get("private"):
        return jsonify(ok=True)
    mid = str(d.get("id") or "")
    if mid:
        c = db()
        try:
            c.execute("INSERT INTO seen(mid) VALUES(?)", (mid,)); c.commit()
        except Exception:
            c.close(); return jsonify(ok=True, note="dup")
        c.close()
    conv = d.get("conversation") or {}
    conv_id = conv.get("id") or d.get("conversation_id")
    content = (d.get("content") or "").strip()
    att_urls = [a.get("data_url") for a in (d.get("attachments") or []) if a.get("data_url")]
    if (not content and not att_urls) or not conv_id:
        return jsonify(ok=True)
    c = db()
    row = c.execute("SELECT thread_id, channel FROM threads WHERE conv_id=?", (conv_id,)).fetchone()
    if not row:
        c.close(); return jsonify(ok=True, note="no_thread")
    tid, channel = row["thread_id"], row["channel"]
    # Footer doklejamy TYLKO do wiadomosci agenta-czlowieka (sender.type == "user").
    # Auto-powitania z reguly automatyzacji maja sender=nil -> nie zlapie ich (brak dublowania).
    sender = d.get("sender") or {}
    footer = ""
    if sender.get("type") == "user":
        footer = build_footer(channel, sender.get("name"))
    c.execute("INSERT INTO queue(thread_id, conv_id, content, attachments, channel, footer, next_at) VALUES(?,?,?,?,?,?,0)",
              (tid, conv_id, content, json.dumps(att_urls), channel, footer))
    c.commit(); c.close()
    log("zakolejkowano wysylke (%s) watek %s (conv %s)%s" % (channel, tid, conv_id, " +footer" if footer else ""))
    return jsonify(ok=True)


@bp.get("/allegro/callback")
def allegro_callback():
    code = request.args.get("code")
    if not code:
        return "Brak parametru code", 400
    try:
        exchange_authorization_code(code)
        return "<h2>Allegro polaczone OK</h2><p>Token zapisany. Mozesz zamknac to okno i wrocic do Chatwoota.</p>"
    except Exception as e:
        log("Allegro callback blad:", repr(e))
        return "Blad: %s" % repr(e), 500


@bp.get("/health")
def health():
    return jsonify(ok=True, ts=int(time.time()))
