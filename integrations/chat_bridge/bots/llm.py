# -*- coding: utf-8 -*-
# Wrapper OpenAI przez requests (bez SDK): chat() i embed().
# Zasada: nigdy nie rzucamy wyjatkiem na zewnatrz — blad -> None + log.
import requests
from config import OPENAI_API_KEY, OPENAI_API_BASE, BOT_CHAT_MODEL, BOT_EMBEDDING_MODEL
from core.log import log


def _headers():
    return {"Authorization": "Bearer " + (OPENAI_API_KEY or ""), "Content-Type": "application/json"}


def chat(messages, model=None, temperature=0.3, timeout=40):
    # Zwraca tresc odpowiedzi modelu albo None przy bledzie.
    try:
        r = requests.post(OPENAI_API_BASE + "/chat/completions", headers=_headers(),
                          json={"model": model or BOT_CHAT_MODEL, "messages": messages,
                                "temperature": temperature}, timeout=timeout)
        if r.status_code != 200:
            log("OpenAI chat kod:", r.status_code, r.text[:200]); return None
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as e:
        log("OpenAI chat blad:", repr(e)); return None


def embed(texts, model=None, timeout=40):
    # Zwraca liste wektorow (1 na tekst) albo None przy bledzie.
    try:
        r = requests.post(OPENAI_API_BASE + "/embeddings", headers=_headers(),
                          json={"model": model or BOT_EMBEDDING_MODEL, "input": texts}, timeout=timeout)
        if r.status_code != 200:
            log("OpenAI embed kod:", r.status_code, r.text[:200]); return None
        return [d["embedding"] for d in r.json()["data"]]
    except Exception as e:
        log("OpenAI embed blad:", repr(e)); return None
