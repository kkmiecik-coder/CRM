# -*- coding: utf-8 -*-
# Wrapper OpenAI przez requests (bez SDK): chat() i embed().
# Zasada: nigdy nie rzucamy wyjatkiem na zewnatrz — blad -> None + log.
import requests
from config import (OPENAI_API_KEY, OPENAI_API_BASE, BOT_CHAT_MODEL, BOT_EMBEDDING_MODEL,
                    BOT_MAX_TOKENS, BOT_REASONING_EFFORT, BOT_VERBOSITY)
from core.log import log


def _headers():
    return {"Authorization": "Bearer " + (OPENAI_API_KEY or ""), "Content-Type": "application/json"}


def _is_reasoning_model(model):
    # GPT-5 oraz o-series (modele rozumujace) nie akceptuja custom temperature — tylko domyslne 1.
    m = (model or "").lower()
    return m.startswith("gpt-5") or m.startswith(("o1", "o3", "o4"))


def _is_gpt5(model):
    # Tylko rodzina GPT-5 obsluguje reasoning_effort=minimal oraz verbosity.
    return (model or "").lower().startswith("gpt-5")


def chat(messages, model=None, temperature=0.3, timeout=40):
    # Zwraca tresc odpowiedzi modelu albo None przy bledzie.
    mdl = model or BOT_CHAT_MODEL
    # max_completion_tokens dziala dla nowych i starych modeli; max_tokens jest deprecated i odrzucany przez GPT-5.
    payload = {"model": mdl, "messages": messages, "max_completion_tokens": BOT_MAX_TOKENS}
    if _is_reasoning_model(mdl):
        # GPT-5: sterujemy glebokoscia myslenia i dlugoscia odpowiedzi (temperature pomijamy — nieobslugiwane).
        if _is_gpt5(mdl):
            payload["reasoning_effort"] = BOT_REASONING_EFFORT
            payload["verbosity"] = BOT_VERBOSITY
    else:
        payload["temperature"] = temperature
    try:
        r = requests.post(OPENAI_API_BASE + "/chat/completions", headers=_headers(),
                          json=payload, timeout=timeout)
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
