# -*- coding: utf-8 -*-
# Google Autocomplete (suggestqueries): realne prefiksy zapytan, ktore ludzie wpisuja. Bez auth.
# Never-raises: dowolny blad zwraca [] (lub pomija dany seed). Zwraca frazy bez wolumenu (score=0).
import requests
from config import SUGGEST_ENABLED, SIGNALS_HL
from core.log import log

_ENDPOINT = "https://suggestqueries.google.com/complete/search"


def _suggest_one(seed):
    r = requests.get(_ENDPOINT, params={"client": "firefox", "hl": SIGNALS_HL, "q": seed}, timeout=15)
    data = r.json()
    # Format firefox: [zapytanie, [podpowiedzi...]]
    return list(data[1]) if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []


def fetch_suggestions(seeds):
    if not SUGGEST_ENABLED:
        return []
    out, seen = [], set()
    for seed in (seeds or [])[:10]:
        try:
            for s in _suggest_one(seed):
                if isinstance(s, str) and s.strip() and s not in seen:
                    seen.add(s)
                    out.append({"query": s.strip(), "score": 0.0, "source": "autocomplete"})
        except Exception as e:
            log("suggest: blad dla", seed, e)
            continue
    return out
