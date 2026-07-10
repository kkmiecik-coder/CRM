# -*- coding: utf-8 -*-
# Wspolne narzedzia warstwy LLM: wyodrebnienie roli system (dla Anthropic) i luzne parsowanie JSON.
import json


def pull_system(messages):
    # Anthropic przyjmuje `system` osobno od `messages`. Skladamy tresci rol 'system' w jeden string,
    # a reszte zwracamy jako liste wiadomosci user/assistant.
    system_parts, rest = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            rest.append(m)
    return ("\n\n".join(p for p in system_parts if p), rest)


def extract_json(text):
    # Wyciaga pierwszy obiekt JSON z tekstu modelu — odporne na ```json ... ``` i tekst wokol.
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(t[start:end + 1])
    except Exception:
        return None
