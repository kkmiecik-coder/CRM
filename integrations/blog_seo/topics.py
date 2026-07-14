# -*- coding: utf-8 -*-
# Silnik tematow: kandydatury z realnego popytu (signals) -> klasyfikacja typu -> LLM szlifuje tytul.
# Fallback do starej sciezki (LLM wymysla z katalogu) gdy sygnaly puste. Dedup po znormalizowanym tytule.
import llm
import store
import signals
import content_type
from config import MIN_BACKLOG, TOPIC_SEEDS
from core.log import log

# Baza priorytetu wg sily zrodla; od niej odejmujemy kare za dominacje typu (miekki limit).
_SOURCE_BASE = {"gsc": 30, "trends": 20, "autocomplete": 10, "seed": 25, "llm": 5}

_LLM_SYSTEM = ("Jesteś strategiem SEO sklepu z drewnianymi blatami i schodami. Proponujesz tematy "
               "artykułów blogowych: poradnikowe, edukacyjne, zakupowe — zawsze osadzone w naszych "
               "produktach. Zwracasz WYŁĄCZNIE JSON: {\"topics\": [\"...\", \"...\"]}. Tematy po polsku, "
               "konkretne, bez duplikatów, bez cen.")

_POLISH_SYSTEM = ("Jesteś redaktorem SEO. Dostajesz surową frazę wyszukiwania i typ treści. Zwróć "
                  "WYŁĄCZNIE JSON {\"title\": \"...\"} — zgrabny, konkretny tytuł artykułu po polsku, "
                  "oddający intencję frazy, bez cen i bez myślników.")


def _seeds_from_categories(categories):
    # Frazy zasilajace Autocomplete/Trends: etykiety kategorii sklepu.
    seeds = []
    for c in (categories or []):
        s = c.get("display_name") or c.get("name")
        if s:
            seeds.append(s)
    return seeds[:10]


def _polish_title(query, ctype):
    # LLM szlifuje surowa fraze w tytul; przy dowolnym bledzie fallback = fraza z wielkiej litery.
    try:
        raw = llm.chat([{"role": "system", "content": _POLISH_SYSTEM},
                        {"role": "user", "content": "Fraza: %s\nTyp: %s\nZaproponuj tytuł." % (query, ctype)}],
                       want_json=True, max_tokens=200)
        data = llm.parse_json(raw) or {}
        title = data.get("title") if isinstance(data, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()
    except Exception as e:
        log("topics._polish_title blad:", e)
    return (query or "").strip().capitalize() or None


def _replenish_llm(catalog_summary, count=6):
    # Stara sciezka (fallback): LLM wymysla tematy z katalogu. Uzywana gdy sygnaly nic nie zwroca.
    seen = "\n".join("- " + t for t in store.published_titles()[:50])
    user = ("Katalog (skrót):\n%s\n\nJuż opublikowane (nie powtarzaj):\n%s\n\n"
            "Zaproponuj %d NOWYCH tematów." % (catalog_summary, seen or "(brak)", count))
    raw = llm.chat([{"role": "system", "content": _LLM_SYSTEM},
                    {"role": "user", "content": user}], want_json=True)
    data = llm.parse_json(raw) or {}
    added = 0
    raw_topics = data.get("topics")
    for title in (raw_topics if isinstance(raw_topics, list) else []):
        if isinstance(title, str):
            ctype = content_type.classify(title)
            if store.add_topic(title, priority=_SOURCE_BASE["llm"], source="llm", content_type=ctype):
                added += 1
    log("topics._replenish_llm dodano:", added)
    return added


def replenish(catalog_summary, categories, count=6):
    # Glowna sciezka: sygnaly realnego popytu -> typ -> szlif LLM. Fallback do _replenish_llm gdy pusto.
    candidates = signals.collect_candidates(_seeds_from_categories(categories),
                                            store.published_norms(), limit=count * 3)
    if not candidates:
        return _replenish_llm(catalog_summary, count)
    recent = store.recent_published_types(8)
    added = 0
    for c in candidates:
        if added >= count:
            break
        query = c.get("query", "")
        ctype = content_type.classify(query)
        prio = _SOURCE_BASE.get(c.get("source"), 10) - content_type.type_penalty(ctype, recent)
        title = _polish_title(query, ctype)
        if title and store.add_topic(title, priority=prio, source=c.get("source", "signal"),
                                     content_type=ctype):
            added += 1
    log("topics.replenish (sygnaly) dodano:", added)
    return added


def pick_topic(catalog_summary, categories):
    # Gdy backlog pusty — seed z TOPIC_SEEDS. Ponizej progu — auto-uzupelnianie z sygnalow. Potem next_topic.
    if store.backlog_count() == 0:
        for s in TOPIC_SEEDS:
            store.add_topic(s, priority=_SOURCE_BASE["seed"], source="seed",
                            content_type=content_type.classify(s))
    if store.backlog_count() < MIN_BACKLOG:
        replenish(catalog_summary, categories)
    return store.next_topic()
