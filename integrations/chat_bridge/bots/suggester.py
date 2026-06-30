# -*- coding: utf-8 -*-
# Orkiestracja podpowiedzi: historia + tozsamosc + wiedza (RAG) + persona -> OpenAI -> notatka.
# Rzuca wyjatkiem przy niepowodzeniu; retry i notatke bledu obsluguje suggest_worker.
from config import BOT_HISTORY_LIMIT
from core.chatwoot import cw_messages, cw_contact, cw_note
from bots.registry import bot_for_inbox
from bots.knowledge import retrieve
from bots.personas import build_system_prompt
from bots.llm import chat

PREFIX = "🤖 Podpowiedź AI:\n"


def run_suggestion(conv_id, inbox_id, message_id, content):
    cfg = bot_for_inbox(inbox_id)
    if not cfg:
        raise RuntimeError("AI: brak bota dla inboxu %s" % inbox_id)

    history = cw_messages(conv_id, BOT_HISTORY_LIMIT)
    identity = cw_contact(conv_id)
    query = (content or "").strip() or (history[-1]["text"] if history else "")
    knowledge = "\n\n".join(retrieve(query))
    system = build_system_prompt(cfg.persona_key, knowledge, identity)

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["text"]} for m in history]

    reply = chat(messages)
    if not reply:
        raise RuntimeError("AI: brak odpowiedzi modelu")
    cw_note(conv_id, PREFIX + reply)
