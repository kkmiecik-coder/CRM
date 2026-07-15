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
    CREATE TABLE IF NOT EXISTS used_images(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ikey TEXT UNIQUE,
      created_at REAL DEFAULT (strftime('%s','now')));
    """)
    c.commit(); c.close()
    _ensure_columns()


def _ensure_columns():
    # Idempotentne dodanie kolumny content_type (starsze bazy nie maja jej z CREATE TABLE IF NOT EXISTS).
    # Blad "duplicate column" lub dowolny inny nie moze przerwac startu.
    for table in ("topics", "published"):
        c = None
        try:
            c = db()
            c.execute("ALTER TABLE %s ADD COLUMN content_type TEXT" % table)
            c.commit()
        except Exception:
            pass
        finally:
            if c is not None:
                c.close()


def add_topic(title, priority=0, source="seed", content_type=None):
    # Zwraca True gdy dodano, False gdy duplikat (po znormalizowanym tytule) lub blad.
    # Polaczenie otwierane WEWNATRZ try — awaria samego db() (zablokowany plik na
    # Windows, brak katalogu, uprawnienia) tez ma zwracac False, nie wywalac wyjatek.
    norm = _norm(title)
    if not norm:
        return False
    c = None
    try:
        c = db()
        c.execute("INSERT INTO topics(title,norm,priority,source,content_type) VALUES(?,?,?,?,?)",
                  (title.strip(), norm, priority, source, content_type))
        c.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        return False
    finally:
        if c is not None:
            c.close()


def topic_exists(title):
    try:
        c = db(); r = c.execute("SELECT 1 FROM topics WHERE norm=?", (_norm(title),)).fetchone()
        c.close(); return r is not None
    except Exception:
        return False


def next_topic():
    try:
        c = db()
        r = c.execute("SELECT id,title,content_type FROM topics WHERE status='pending' "
                      "ORDER BY priority DESC, id ASC LIMIT 1").fetchone()
        c.close()
        return {"id": r["id"], "title": r["title"], "content_type": r["content_type"]} if r else None
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


def record_published(slug, title, content_type=None):
    try:
        c = db()
        c.execute("INSERT OR IGNORE INTO published(slug,title,norm,content_type) VALUES(?,?,?,?)",
                  (slug, title, _norm(title), content_type))
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


def used_image_keys():
    # Klucze (photo_url) zdjec juz uzytych w artykulach — do pomijania duplikatow przy doborze hero.
    try:
        c = db(); rows = c.execute("SELECT ikey FROM used_images").fetchall(); c.close()
        return {r["ikey"] for r in rows if r["ikey"]}
    except Exception:
        return set()


def mark_image_used(key):
    # Zapisuje klucz zdjecia jako uzyty (INSERT OR IGNORE — powtorka nie rzuca). Pusty klucz pomijamy.
    if not key:
        return
    try:
        c = db(); c.execute("INSERT OR IGNORE INTO used_images(ikey) VALUES(?)", (key,))
        c.commit(); c.close()
    except Exception:
        pass


def published_norms():
    # Zbior znormalizowanych tytulow publikacji — do odsiewu kandydatur sygnalow.
    try:
        c = db(); rows = c.execute("SELECT norm FROM published").fetchall(); c.close()
        return {r["norm"] for r in rows if r["norm"]}
    except Exception:
        return set()


def recent_published_types(n=8):
    # Typy tresci ostatnich n publikacji (najnowsze pierwsze) — wejscie do miekkiego limitu.
    try:
        c = db()
        rows = c.execute("SELECT content_type FROM published ORDER BY id DESC LIMIT ?",
                         (int(n),)).fetchall()
        c.close()
        return [r["content_type"] for r in rows if r["content_type"]]
    except Exception:
        return []
