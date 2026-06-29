# -*- coding: utf-8 -*-
# Warstwa stanu: polaczenie SQLite, inicjalizacja schematu, tabela meta (klucz-wartosc).
import sqlite3
from config import DB_PATH


def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS threads(
      thread_id TEXT PRIMARY KEY, conv_id INTEGER,
      last_seen_msg_id TEXT, total_count INTEGER, channel TEXT);
    CREATE TABLE IF NOT EXISTS queue(
      id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, conv_id INTEGER,
      content TEXT, attempts INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
      next_at REAL DEFAULT 0, last_error TEXT, attachments TEXT, channel TEXT);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS seen(mid TEXT PRIMARY KEY);
    """)
    for stmt in ("ALTER TABLE queue ADD COLUMN attachments TEXT",
                 "ALTER TABLE threads ADD COLUMN channel TEXT",
                 "ALTER TABLE queue ADD COLUMN channel TEXT"):
        try:
            c.execute(stmt)
        except Exception:
            pass
    try:
        c.execute("UPDATE threads SET channel='olx' WHERE channel IS NULL")
        c.execute("UPDATE queue SET channel='olx' WHERE channel IS NULL")
    except Exception:
        pass
    c.commit(); c.close()


def meta_get(k, default=None):
    c = db(); r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); c.close()
    return r["v"] if r else default


def meta_set(k, v):
    c = db(); c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v))); c.commit(); c.close()
