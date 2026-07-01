# -*- coding: utf-8 -*-
# Orkiestracja podpowiedzi: historia + tozsamosc + wiedza (RAG) + persona -> OpenAI -> notatka.
# Rzuca wyjatkiem przy niepowodzeniu; retry i notatke bledu obsluguje suggest_worker.
from config import BOT_HISTORY_LIMIT
from core.chatwoot import cw_messages, cw_contact, cw_note
from bots.channel_resolver import persona_for
from bots.knowledge import retrieve
from bots.personas import build_system_prompt
from bots.llm import chat

PREFIX = "🤖 Podpowiedź AI:\n"


def run_suggestion(conv_id, inbox_id, message_id, content):
    persona_key = persona_for(inbox_id)
    if persona_key is None:
        raise RuntimeError("AI: brak persony dla inboxu %s" % inbox_id)

    history = cw_messages(conv_id, BOT_HISTORY_LIMIT)
    identity = cw_contact(conv_id)
    query = (content or "").strip() or (history[-1]["text"] if history else "")
    knowledge = "\n\n".join(retrieve(query))
    system = build_system_prompt(persona_key, knowledge, identity)

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["text"]} for m in history]

    # Fallback: gdy historia jest pusta, ale wiadomosc triggerujaca jest znana — dodaj turn klienta.
    if not history and (content or "").strip():
        messages.append({"role": "user", "content": content})

    reply = chat(messages)
    if not reply:
        raise RuntimeError("AI: brak odpowiedzi modelu")
    cw_note(conv_id, PREFIX + reply)
