# -*- coding: utf-8 -*-
# Wrapper OpenAI przez requests (bez SDK): chat() i embed().
# Zasada: nigdy nie rzucamy wyjatkiem na zewnatrz — blad -> None + log.
import time
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


def _error_class(status_code):
    """Klasyfikacja bledu HTTP dla circuit-breakera/backoffu (TO-04): '4xx' nie-retryable
    (poza 429), '429'/'5xx' i 'transport' (blad polaczenia) retryable."""
    if status_code == 429:
        return "429"
    if status_code is not None and 400 <= status_code < 500:
        return "4xx"
    if status_code is not None and status_code >= 500:
        return "5xx"
    return "transport"


def chat(messages, model=None, temperature=0.3, timeout=40, response_format=None, return_meta=False):
    # Zwraca tresc odpowiedzi modelu albo None przy bledzie. return_meta=True zwraca zamiast tego
    # (tresc_albo_None, meta) — meta = {model, ms, usage, finish_reason, error_class} (TO-05/TO-06).
    # response_format (np. {"type":"json_object"}) wymusza JSON u botow wyceniajacych — przekazywany
    # tylko przez nie; suggester (proza) go nie ustawia.
    mdl = model or BOT_CHAT_MODEL
    # max_completion_tokens dziala dla nowych i starych modeli; max_tokens jest deprecated i odrzucany przez GPT-5.
    payload = {"model": mdl, "messages": messages, "max_completion_tokens": BOT_MAX_TOKENS}
    if response_format:
        payload["response_format"] = response_format
    if _is_reasoning_model(mdl):
        # GPT-5: sterujemy glebokoscia myslenia i dlugoscia odpowiedzi (temperature pomijamy — nieobslugiwane).
        if _is_gpt5(mdl):
            payload["reasoning_effort"] = BOT_REASONING_EFFORT
            payload["verbosity"] = BOT_VERBOSITY
    else:
        payload["temperature"] = temperature
    t0 = time.monotonic()
    try:
        r = requests.post(OPENAI_API_BASE + "/chat/completions", headers=_headers(),
                          json=payload, timeout=timeout)
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            log("OpenAI chat kod:", r.status_code, r.text[:200])
            meta = {"model": mdl, "ms": ms, "usage": {}, "finish_reason": None,
                    "error_class": _error_class(r.status_code)}
            return (None, meta) if return_meta else None
        data = r.json() or {}
        choice = (data.get("choices") or [{}])[0]
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        # Log BEZWARUNKOWY (TO-06/TO-09): model/czas/usage widoczne za kazdym wywolaniem, nie
        # tylko przy uciety finish_reason (PL-04) — koszt i wydajnosc bota widoczne w docker logs.
        log("OpenAI chat model=%s ms=%s finish=%s usage=%s" % (mdl, ms, finish, usage))
        content = ((choice.get("message") or {}).get("content") or "").strip() or None
        meta = {"model": mdl, "ms": ms, "usage": usage, "finish_reason": finish, "error_class": None}
        return (content, meta) if return_meta else content
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        log("OpenAI chat blad:", repr(e))
        meta = {"model": mdl, "ms": ms, "usage": {}, "finish_reason": None, "error_class": "transport"}
        return (None, meta) if return_meta else None


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
