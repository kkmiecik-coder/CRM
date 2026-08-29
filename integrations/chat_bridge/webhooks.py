# -*- coding: utf-8 -*-
# Trasy HTTP mostka: webhook konta Chatwoota (outgoing -> kolejka wysylki), webhook Agent Bota
# (/agent-bot -> handoff + kolejka podpowiedzi AI), webhook Agent Bota live-chat
# (/agent-bot-live -> kolejka tur konwersacyjnych), callback OAuth Allegro, health.
import time
import json
from flask import Blueprint, request, jsonify
from config import (WEBHOOK_TOKEN, BOT_AGENT_WEBHOOK_TOKEN, BOT_LIVE_AGENT_WEBHOOK_TOKEN,
                     BOT_QUOTE_AGENT_WEBHOOK_TOKEN,
                     CW_OLX_INBOX, CW_ALLEGRO_MSG_INBOX)
from core.log import log
from core.db import db
from core.chatwoot import cw_bot_handoff
from bots.channel_resolver import persona_for
from bots.quote_intake import enqueue_quote_turn
from footer import build_footer
from channels.allegro_auth import exchange_authorization_code

bp = Blueprint("webhooks", __name__)


def _quote_persona_dla_inboxu(inbox_id):
    """Klucz persony quotebota dla inboxu, albo None gdy inbox jest poza zakresem trybu notatki.
    Rozgalezienie idzie po IDENTYFIKATORZE INBOXU, nie po kluczu persony: persona_for zwraca
    "allegro" dla KAZDEGO inboxu Channel::Api z "allegro" w nazwie, wiec mapowanie po personie
    wciagalo w zakres takze inbox "Allegro - Dyskusje" (spory i reklamacje), ktory spec wyklucza
    wprost (Decyzja 5) — wysoka stawka bledu, a persona i tak kaze oddac reklamacje czlowiekowi.
    Poza zakresem sa wiec: Dyskusje, skrzynki mailowe i wszystko inne — te zostaja na starym
    podpowiadaczu (suggest_queue). Identyfikatory bierzemy z konfiguracji (CHATWOOT_*_INBOX_ID),
    nigdy na sztywno z kodu; sa to STRINGI z env, wiec porownujemy stringi po obu stronach."""
    iid = str(inbox_id or "").strip()
    if not iid:
        return None
    for skonfigurowany, persona in ((CW_OLX_INBOX, "quote_olx"),
                                    (CW_ALLEGRO_MSG_INBOX, "quote_allegro")):
        if skonfigurowany and iid == str(skonfigurowany).strip():
            return persona
    return None


# ---------- AGENT BOT WEBHOOK ----------
def _process_agent_bot(d):
    # Webhook natywnego Agent Bota: ZAWSZE handoff (rozmowa nie utyka w pending),
    # a jesli inbox ma zmapowana persone -> kolejka podpowiedzi (prywatna notatka)
    # albo, dla OLX/Allegro, pelna tura silnika quotebota (tez notatka).
    if d.get("event") != "message_created":
        return
    mtype = str(d.get("message_type"))
    if mtype not in ("incoming", "0") or d.get("private"):
        return
    conv = d.get("conversation") or {}
    conv_id = conv.get("id") or d.get("conversation_id")
    inbox_id = str(d.get("inbox_id") or conv.get("inbox_id") or (d.get("inbox") or {}).get("id") or "")
    content = (d.get("content") or "").strip()
    mid = str(d.get("id") or "")
    # Tylko zalaczniki-obrazy (file_type == 'image') trafiaja do LLM jako vision — zbierane tak
    # samo jak w /agent-bot-live i /agent-bot-quote. Bez tego rozpoznawanie obrazow (bots/vision.py)
    # bylo na OLX/Allegro martwe: bot nie widzial zdjecia przyslanego przez klienta.
    att = [a.get("data_url") for a in (d.get("attachments") or [])
           if a.get("data_url") and str(a.get("file_type") or "").lower() == "image"]
    if not conv_id or not inbox_id:
        return
    # Oddaj rozmowe agentom niezaleznie od persony/tresci (idempotentne dla juz otwartej).
    # Handoff MUSI byc wolany dla obu torow, przed rozgalezieniem ponizej — bramka statusu
    # w quotebocie jest zniesiona dla trybu notatki, wiec bez tego rozmowa utknelaby w pending.
    cw_bot_handoff(conv_id)
    if not mid or (not content and not att):
        return
    persona = persona_for(inbox_id)
    if not persona or persona == "livechat":
        log("agent-bot: inbox %s bez persony podpowiedzi - bez podpowiedzi" % inbox_id)
        return
    quote_persona = _quote_persona_dla_inboxu(inbox_id)
    if quote_persona:
        # OLX/Allegro-Wiadomosci: pelna tura quotebota (wycena, lead w CRM) z wyjsciem do notatki.
        # Dedup + okno ciszy atomowo w enqueue_quote_turn — dlatego BEZ wpisu do bot_seen.
        if enqueue_quote_turn(conv_id, inbox_id, mid, content, attachments=att,
                              persona=quote_persona) == "duplicate":
            return
        log("agent-bot: zakolejkowano ture quotebota (%s, inbox %s, conv %s)%s"
            % (quote_persona, inbox_id, conv_id, (" +%d obrazy" % len(att)) if att else ""))
        return
    if persona in ("olx", "allegro"):
        # Inbox marketplace POZA mapa z konfiguracji: albo "Allegro - Dyskusje" (swiadomie poza
        # zakresem), albo brak CHATWOOT_*_INBOX_ID w bridge.env. Logujemy, bo drugi przypadek
        # to blad konfiguracji, ktory inaczej po cichu zepchnalby kanal na stary podpowiadacz.
        log("agent-bot: inbox %s (persona %s) poza zakresem quotebota - stary podpowiadacz"
            % (inbox_id, persona))
    # Pozostale kanaly (mail, Allegro-Dyskusje) — stary podpowiadacz, ktory pracuje na samym
    # tekscie: bez tresci nie ma czego podpowiadac (zalaczniki obsluguje tylko tor quotebota).
    if not content:
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


# ---------- AGENT BOT LIVE-CHAT (konwersacyjny) ----------
def _process_livechat_bot(d):
    # Webhook live-bota: kolejkuje ture rozmowy. BEZ natychmiastowego handoffu —
    # o przekazaniu decyduje silnik (bots/livechat.py, wyzwalacze A/B/C/D).
    if d.get("event") != "message_created":
        return
    mtype = str(d.get("message_type"))
    if mtype not in ("incoming", "0") or d.get("private"):
        return
    conv = d.get("conversation") or {}
    conv_id = conv.get("id") or d.get("conversation_id")
    inbox_id = str(d.get("inbox_id") or conv.get("inbox_id") or (d.get("inbox") or {}).get("id") or "")
    content = (d.get("content") or "").strip()
    mid = str(d.get("id") or "")
    # Tylko zalaczniki-obrazy (file_type == 'image') trafiaja do LLM jako vision.
    att = [a.get("data_url") for a in (d.get("attachments") or [])
           if a.get("data_url") and str(a.get("file_type") or "").lower() == "image"]
    if not conv_id or not mid or (not content and not att):
        return
    # Guard: live-bot dziala TYLKO na inboxach WebWidget (persona livechat) — ochrona przed
    # omylkowym przypieciem bota do inboxu OLX/Allegro w UI.
    if persona_for(inbox_id) != "livechat":
        log("agent-bot-live: inbox %s bez persony livechat - pomijam" % inbox_id)
        return
    c = db()
    try:
        c.execute("INSERT INTO live_seen(mid) VALUES(?)", (mid,))
    except Exception:
        c.close(); return  # duplikat
    c.execute("INSERT INTO live_queue(conv_id, inbox_id, message_id, content, attachments, next_at) "
              "VALUES(?,?,?,?,?,0)", (conv_id, inbox_id, mid, content, json.dumps(att)))
    c.commit(); c.close()
    log("agent-bot-live: zakolejkowano ture (inbox %s, conv %s)%s"
        % (inbox_id, conv_id, (" +%d obrazy" % len(att)) if att else ""))


@bp.post("/agent-bot-live")
def agent_bot_live():
    if BOT_LIVE_AGENT_WEBHOOK_TOKEN and request.args.get("token") != BOT_LIVE_AGENT_WEBHOOK_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    _process_livechat_bot(d)
    return jsonify(ok=True)


# ---------- AGENT BOT QUOTE (wyceniajacy, live chat testowy) ----------
def _process_quotebot(d):
    # Webhook quote-bota: kolejkuje ture do quote_queue. Guard: tylko inboxy WebWidget
    # (persona livechat), zeby omylkowe przypiecie do OLX/Allegro nic nie robilo.
    if d.get("event") != "message_created":
        return
    mtype = str(d.get("message_type"))
    if mtype not in ("incoming", "0") or d.get("private"):
        return
    conv = d.get("conversation") or {}
    conv_id = conv.get("id") or d.get("conversation_id")
    inbox_id = str(d.get("inbox_id") or conv.get("inbox_id") or (d.get("inbox") or {}).get("id") or "")
    content = (d.get("content") or "").strip()
    mid = str(d.get("id") or "")
    att = [a.get("data_url") for a in (d.get("attachments") or [])
           if a.get("data_url") and str(a.get("file_type") or "").lower() == "image"]
    if not conv_id or not mid or (not content and not att):
        return
    if persona_for(inbox_id) != "livechat":
        log("agent-bot-quote: inbox %s bez persony livechat - pomijam" % inbox_id)
        return
    # Dedup + okno ciszy (scalanie serii wiadomosci w jedna ture) — atomowo w enqueue_quote_turn.
    if enqueue_quote_turn(conv_id, inbox_id, mid, content, attachments=att) == "duplicate":
        return
    log("agent-bot-quote: zakolejkowano ture (inbox %s, conv %s)" % (inbox_id, conv_id))


@bp.post("/agent-bot-quote")
def agent_bot_quote():
    if BOT_QUOTE_AGENT_WEBHOOK_TOKEN and request.args.get("token") != BOT_QUOTE_AGENT_WEBHOOK_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    _process_quotebot(d)
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
    # cw_msg_id zapamietujemy, zeby przy nieudanej wysylce oznaczyc TEN dymek w Chatwoocie
    # jako niedostarczony — inaczej agent widzi "ptaszka" przy wiadomosci, ktora nie wyszla.
    c.execute("INSERT INTO queue(thread_id, conv_id, content, attachments, channel, footer, next_at, cw_msg_id) "
              "VALUES(?,?,?,?,?,?,0,?)",
              (tid, conv_id, content, json.dumps(att_urls), channel, footer, mid or None))
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
