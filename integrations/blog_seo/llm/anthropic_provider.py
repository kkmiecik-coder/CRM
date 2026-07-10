# -*- coding: utf-8 -*-
# Provider Anthropic przez raw requests (bez SDK — symetria z OpenAI). Nigdy nie rzuca.
# WAZNE (Opus 4.8 / Sonnet 5): NIE wysylamy temperature/top_p/top_k ani budget_tokens (zwracaja 400).
# system idzie osobnym polem; max_tokens jest wymagane; odpowiedz w content[].text.
import requests
from config import (ANTHROPIC_API_KEY, ANTHROPIC_API_BASE, ANTHROPIC_MODEL,
                    ANTHROPIC_VERSION, MAX_TOKENS)
from core.log import log
from llm.base import pull_system


def chat_anthropic(messages, want_json, max_tokens):
    # Zwraca tresc odpowiedzi albo None. want_json obslugujemy promptowo (parsowanie po stronie
    # wolajacego przez llm.parse_json) — bez parametrow specyficznych dla dostawcy, by interfejs
    # byl identyczny jak OpenAI.
    try:
        system, rest = pull_system(messages)
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens or MAX_TOKENS,
            "messages": rest,
        }
        if system:
            payload["system"] = system
        r = requests.post(ANTHROPIC_API_BASE + "/messages",
                          headers={"x-api-key": ANTHROPIC_API_KEY or "",
                                   "anthropic-version": ANTHROPIC_VERSION,
                                   "content-type": "application/json"},
                          json=payload, timeout=120)
        if r.status_code != 200:
            log("Anthropic kod:", r.status_code, r.text[:200]); return None
        blocks = (r.json() or {}).get("content") or []
        for b in blocks:
            if b.get("type") == "text":
                return (b.get("text") or "").strip() or None
        return None
    except Exception as e:
        log("Anthropic blad:", repr(e)); return None
