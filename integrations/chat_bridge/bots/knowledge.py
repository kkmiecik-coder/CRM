# -*- coding: utf-8 -*-
# Retrieval (RAG) wiedzy z Help Center: indeksacja artykulow w kb_chunks (embeddingi)
# i pobieranie top-K chunkow po cosine. Backend startowy: cosine w Pythonie.
import json
import math
import time
import hashlib
from config import BOT_HELP_CENTER_SLUG, BOT_RETRIEVAL_K, BOT_INDEX_INTERVAL
from core.db import db, init_db
from core.log import log
from core.chatwoot import cw_articles
from bots.llm import embed


def chunk_text(text, max_chars=1800):
    # Dzieli po akapitach; skleja, dopoki miesci sie w max_chars. Dlugie akapity tnie twardo.
    out = []
    buf = ""
    for para in (text or "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:
            out.append(para[:max_chars]); para = para[max_chars:]
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + "\n\n" + para) if buf else para
        else:
            if buf:
                out.append(buf)
            buf = para
    if buf:
        out.append(buf)
    return out


def cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _hash(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sync_index():
    # Pobiera artykuly, chunkuje, embeduje TYLKO nowe (dedup po hashu), usuwa nieaktualne.
    init_db()
    arts = cw_articles(BOT_HELP_CENTER_SLUG)
    wanted = []  # (article_id, chunk, hash)
    for a in arts:
        body = ((a.get("title") or "") + "\n" + (a.get("content") or "")).strip()
        for ch in chunk_text(body):
            wanted.append((a.get("id"), ch, _hash(ch)))
    wanted_hashes = {h for (_, _, h) in wanted}

    c = db()
    existing = {r["hash"] for r in c.execute("SELECT hash FROM kb_chunks").fetchall()}
    to_delete = [h for h in existing if h not in wanted_hashes]
    new = [(aid, ch, h) for (aid, ch, h) in wanted if h not in existing]

    # Embeduj PRZED usunieciem starych chunkow — jesli embed zawiedzie, KB pozostaje nienaruszony.
    vecs = None
    if new:
        vecs = embed([ch for (_, ch, _) in new])
        if vecs is None:
            c.close()
            log("KB sync: embed zwrocil None — pomijam cykl, KB bez zmian")
            return len(existing)

    # Usun nieaktualne i wstaw nowe dopiero po udanym embedowaniu.
    for h in to_delete:
        c.execute("DELETE FROM kb_chunks WHERE hash=?", (h,))
    if new and vecs is not None:
        for (aid, ch, h), v in zip(new, vecs):
            c.execute("INSERT OR IGNORE INTO kb_chunks(article_id, chunk, embedding, hash) VALUES(?,?,?,?)",
                      (aid, ch, json.dumps(v), h))
    c.commit(); c.close()
    return len(wanted)


def retrieve(query, k=None):
    # Top-K chunkow najblizszych zapytaniu (cosine). [] gdy pusty indeks lub blad embeddingu.
    k = k or BOT_RETRIEVAL_K
    c = db()
    rows = c.execute("SELECT chunk, embedding FROM kb_chunks").fetchall()
    c.close()
    if not rows:
        return []
    qv = embed([query])
    if not qv or qv[0] is None:
        # zabezpieczenie: brak/uszkodzony embedding zapytania -> brak wynikow
        return []
    qv = qv[0]
    scored = []
    for r in rows:
        try:
            v = json.loads(r["embedding"])
        except Exception:
            continue
        scored.append((cosine(qv, v), r["chunk"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ch for _, ch in scored[:k]]


def index_loop():
    # Watek tla: cykliczna synchronizacja indeksu wiedzy.
    while True:
        try:
            n = sync_index()
            log("KB index: %s chunkow" % n)
        except Exception as e:
            log("KB index ERROR:", repr(e))
        time.sleep(BOT_INDEX_INTERVAL)
