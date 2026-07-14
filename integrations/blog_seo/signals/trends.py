# -*- coding: utf-8 -*-
# Google Trends (nieoficjalne endpointy): zapytania powiazane/rosnace dla sezonowosci i typu "Trendy".
# Best-effort — Google potrafi zmienic format; caly przeplyw owiniety never-raises (blad -> []).
# Dwustopniowo: /explore zwraca widgety z tokenem -> /widgetdata/relatedsearches zwraca frazy.
import json
import requests
from config import TRENDS_ENABLED, SIGNALS_GEO, SIGNALS_HL
from core.log import log

_EXPLORE = "https://trends.google.com/trends/api/explore"
_RELATED = "https://trends.google.com/trends/api/widgetdata/relatedsearches"


def _strip(text):
    # Odpowiedzi Trends zaczynaja sie od ")]}',\n" — odcinamy wszystko przed pierwszym '{'.
    i = (text or "").find("{")
    return text[i:] if i >= 0 else ""


def _related_for(seed):
    hl = "%s-%s" % (SIGNALS_HL, SIGNALS_GEO)
    req = {"comparisonItem": [{"keyword": seed, "geo": SIGNALS_GEO, "time": "today 12-m"}],
           "category": 0, "property": ""}
    r = requests.get(_EXPLORE, params={"hl": hl, "tz": "-120", "req": json.dumps(req)}, timeout=20)
    widgets = (json.loads(_strip(r.text)) or {}).get("widgets") or []
    w = next((x for x in widgets if x.get("id") == "RELATED_QUERIES"), None)
    if not w:
        return []
    r2 = requests.get(_RELATED, params={"hl": hl, "tz": "-120",
                                        "req": json.dumps(w.get("request") or {}),
                                        "token": w.get("token")}, timeout=20)
    data = json.loads(_strip(r2.text)) or {}
    ranked = ((data.get("default") or {}).get("rankedList")) or []
    out = []
    for rl in ranked:
        for kw in (rl.get("rankedKeyword") or []):
            q = kw.get("query")
            if isinstance(q, str) and q.strip():
                out.append({"query": q.strip(), "score": float(kw.get("value") or 0), "source": "trends"})
    return out


def fetch_trends(seeds):
    if not TRENDS_ENABLED:
        return []
    out = []
    for seed in (seeds or [])[:5]:
        try:
            out.extend(_related_for(seed))
        except Exception as e:
            log("trends: blad dla", seed, e)
            continue
    return out
