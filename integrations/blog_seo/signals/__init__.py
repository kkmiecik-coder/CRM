# -*- coding: utf-8 -*-
# Agregator sygnalow popytu: scala GSC + Trends + Autocomplete, dedupuje po znormalizowanym tytule,
# odsiewa juz opublikowane i porzadkuje wg sily zrodla. Kazde zrodlo jest juz never-raises; caly
# agregat dodatkowo owiniety (blad -> []).
from store import _norm
from signals.gsc import fetch_gsc_candidates
from signals.suggest import fetch_suggestions
from signals.trends import fetch_trends


def collect_candidates(seeds, published_norms, limit=30):
    try:
        published = set(published_norms or [])
        gsc = sorted(fetch_gsc_candidates(), key=lambda c: -c.get("score", 0))
        trends = sorted(fetch_trends(seeds), key=lambda c: -c.get("score", 0))
        sugg = fetch_suggestions(seeds)
        merged, seen = [], set()
        for c in gsc + trends + sugg:        # kolejnosc = priorytet zrodla
            n = _norm(c.get("query"))
            if not n or n in published or n in seen:
                continue
            seen.add(n)
            merged.append(c)
        return merged[:limit]
    except Exception:
        return []
