# -*- coding: utf-8 -*-
# Silnik tematow: auto-uzupelnianie backlogu z katalogu (LLM) z dedupem oraz wybor nastepnego tematu.
import llm
import store
from config import MIN_BACKLOG, TOPIC_SEEDS
from core.log import log

_SYSTEM = ("Jesteś strategiem SEO sklepu z drewnianymi blatami i schodami. Proponujesz tematy "
           "artykułów blogowych: poradnikowe, edukacyjne, zakupowe — zawsze osadzone w naszych "
           "produktach. Zwracasz WYŁĄCZNIE JSON: {\"topics\": [\"...\", \"...\"]}. Tematy po polsku, "
           "konkretne, bez duplikatów, bez cen.")


def replenish(catalog_summary, count=6):
    # Prosi LLM o nowe tematy na bazie katalogu; odrzuca duplikaty; dodaje reszte. Zwraca liczbe dodanych.
    seen = "\n".join("- " + t for t in store.published_titles()[:50])
    user = ("Katalog (skrót):\n%s\n\nJuż opublikowane (nie powtarzaj):\n%s\n\n"
            "Zaproponuj %d NOWYCH tematów." % (catalog_summary, seen or "(brak)", count))
    raw = llm.chat([{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user}], want_json=True)
    data = llm.parse_json(raw) or {}
    added = 0
    raw_topics = data.get("topics")
    for title in (raw_topics if isinstance(raw_topics, list) else []):
        if isinstance(title, str) and store.add_topic(title, priority=0, source="llm"):
            added += 1
    log("topics.replenish dodano:", added)
    return added


def pick_topic(catalog_summary):
    # Gdy backlog pusty — seed z TOPIC_SEEDS. Gdy ponizej progu — auto-uzupelnianie. Potem next_topic.
    if store.backlog_count() == 0:
        for s in TOPIC_SEEDS:
            store.add_topic(s, priority=1, source="seed")
    if store.backlog_count() < MIN_BACKLOG:
        replenish(catalog_summary)
    return store.next_topic()
