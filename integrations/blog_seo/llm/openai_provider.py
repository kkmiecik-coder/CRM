# -*- coding: utf-8 -*-
# Provider OpenAI przez raw requests (bez SDK — jak chat_bridge/bots/llm.py). Nigdy nie rzuca.
import requests
from config import OPENAI_API_KEY, OPENAI_API_BASE, OPENAI_MODEL, MAX_TOKENS
from core.log import log


def _is_reasoning(model):
    m = (model or "").lower()
    return m.startswith("gpt-5") or m.startswith(("o1", "o3", "o4"))


def chat_openai(messages, want_json, max_tokens):
    # Zwraca tresc odpowiedzi albo None. Dla GPT-5 nie wysylamy temperature (nieobslugiwane).
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens or MAX_TOKENS,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    if not _is_reasoning(OPENAI_MODEL):
        payload["temperature"] = 0.5
    try:
        r = requests.post(OPENAI_API_BASE + "/chat/completions",
                          headers={"Authorization": "Bearer " + (OPENAI_API_KEY or ""),
                                   "Content-Type": "application/json"},
                          json=payload, timeout=120)
        if r.status_code != 200:
            log("OpenAI kod:", r.status_code, r.text[:200]); return None
        choice = ((r.json() or {}).get("choices") or [{}])[0]
        return ((choice.get("message") or {}).get("content") or "").strip() or None
    except Exception as e:
        log("OpenAI blad:", repr(e)); return None
