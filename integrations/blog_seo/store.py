# -*- coding: utf-8 -*-
# Warstwa stanu (SQLite): backlog tematow z dedupem, oznaczanie uzytych, historia publikacji.
# Wzorzec jak chat_bridge/core/db.py: CREATE TABLE IF NOT EXISTS + polaczenie z Row.
import re
import sqlite3
from config import DB_PATH


def _norm(title):
    # Normalizacja tytulu do dedupu: male litery, bez nadmiarowych spacji, polskie znaki zostaja.
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS topics(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, norm TEXT UNIQUE,
      priority INTEGER DEFAULT 0, source TEXT, status TEXT DEFAULT 'pending',
      created_at REAL DEFAULT (strftime('%s','now')));
    CREATE TABLE IF NOT EXISTS published(
      id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, title TEXT, norm TEXT,
      created_at REAL DEFAULT (strftime('%s','now')));
    """)
    c.commit(); c.close()


def add_topic(title, priority=0, source="seed"):
    # Zwraca True gdy dodano, False gdy duplikat (po znormalizowanym tytule) lub blad.
    norm = _norm(title)
    if not norm:
        return False
    try:
        c = db()
        c.execute("INSERT INTO topics(title,norm,priority,source) VALUES(?,?,?,?)",
                  (title.strip(), norm, priority, source))
        c.commit(); c.close(); return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        return False


def topic_exists(title):
    try:
        c = db(); r = c.execute("SELECT 1 FROM topics WHERE norm=?", (_norm(title),)).fetchone()
        c.close(); return r is not None
    except Exception:
        return False


def next_topic():
    try:
        c = db()
        r = c.execute("SELECT id,title FROM topics WHERE status='pending' "
                      "ORDER BY priority DESC, id ASC LIMIT 1").fetchone()
        c.close()
        return {"id": r["id"], "title": r["title"]} if r else None
    except Exception:
        return None


def mark_topic_used(topic_id):
    try:
        c = db(); c.execute("UPDATE topics SET status='used' WHERE id=?", (topic_id,))
        c.commit(); c.close()
    except Exception:
        pass


def backlog_count():
    try:
        c = db(); n = c.execute("SELECT COUNT(*) n FROM topics WHERE status='pending'").fetchone()["n"]
        c.close(); return n
    except Exception:
        return 0


def record_published(slug, title):
    try:
        c = db()
        c.execute("INSERT OR IGNORE INTO published(slug,title,norm) VALUES(?,?,?)",
                  (slug, title, _norm(title)))
        c.commit(); c.close()
    except Exception:
        pass


def slug_seen(slug):
    try:
        c = db(); r = c.execute("SELECT 1 FROM published WHERE slug=?", (slug,)).fetchone()
        c.close(); return r is not None
    except Exception:
        return False


def published_titles():
    try:
        c = db(); rows = c.execute("SELECT title FROM published").fetchall(); c.close()
        return [r["title"] for r in rows]
    except Exception:
        return []
