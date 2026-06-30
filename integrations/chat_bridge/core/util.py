# -*- coding: utf-8 -*-
# Helpery wspoldzielone przez kanaly: HTML->tekst (Allegro), parsowanie dat, upsert stanu watku.
import re
import html as _htmlmod
from datetime import datetime
from core.db import db
from core.log import log


def html_to_text(s):
    """Konwersja HTML (Allegro) na czysty tekst: <br>/<li>/<p> -> nowe linie, linki -> 'tekst (url)', reszta tagow usunieta, encje odkodowane."""
    if not s or "<" not in s:
        return s
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</p\s*>', '\n\n', s)
    s = re.sub(r'(?i)<li[^>]*>', '\n• ', s)
    s = re.sub(r'(?i)</li\s*>', '', s)
    s = re.sub(r'(?is)<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'\2 (\1)', s)
    s = re.sub(r'(?s)<[^>]+>', '', s)
    s = _htmlmod.unescape(s)
    s = re.sub(r'[ \t]+\n', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def cw_ok(resp):
    """Czy odpowiedz Chatwoota to sukces (200/201). None = brak odpowiedzi => porazka."""
    return resp is not None and getattr(resp, "status_code", 0) in (200, 201)


def deliver_in_order(new_msgs, msg_key, send_fn):
    """Dostarcza wiadomosci po kolei: send_fn(m) -> odpowiedz Chatwoota.
    Zatrzymuje sie na pierwszej nieudanej dostawie (status != 2xx / None).
    Zwraca (delivered_key, all_ok):
      - delivered_key: msg_key(m) ostatniej DOSTARCZONEJ wiadomosci (None gdy zadna),
      - all_ok: True gdy wszystkie dostarczone (lub lista pusta).
    Dzieki temu wodowskaz (last_seen) przesuwamy wylacznie za realnie dostarczone
    wiadomosci — niedostarczone (np. 401 z Chatwoota) zostaja do ponowienia w kolejnym
    cyklu pollera, zamiast byc po cichu oznaczone jako 'widziane'.
    Wyjatek z send_fn (np. timeout sieci) tez traktujemy jak niedostawe: zatrzymujemy sie
    i zwracamy postep do ostatniej DOSTARCZONEJ wiadomosci (bez gubienia juz wyslanych).
    Klucz None (brak uzytecznego identyfikatora) nie cofa wodowskazu — trzymamy poprzedni."""
    delivered_key = None
    for m in new_msgs:
        try:
            ok = cw_ok(send_fn(m))
        except Exception as e:
            log("deliver_in_order: wyjatek dostawy, wstrzymuje wodowskaz:", repr(e))
            return delivered_key, False
        if not ok:
            return delivered_key, False
        k = msg_key(m)
        if k is not None:
            delivered_key = k
    return delivered_key, True


def parse_ts(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def upsert_thread(tid, conv_id, last_seen, total, channel):
    c = db()
    # nie nadpisuj conv_id/last_seen wartoscia None jesli juz sa ustawione
    row = c.execute("SELECT conv_id, last_seen_msg_id, total_count FROM threads WHERE thread_id=? AND channel=?", (str(tid), channel)).fetchone()
    if row:
        conv_id = conv_id if conv_id is not None else row["conv_id"]
        ls = str(last_seen) if last_seen is not None else row["last_seen_msg_id"]
        tot = total if total is not None else row["total_count"]
        c.execute("UPDATE threads SET conv_id=?, last_seen_msg_id=?, total_count=? WHERE thread_id=? AND channel=?",
                  (conv_id, ls, tot, str(tid), channel))
    else:
        c.execute("INSERT INTO threads(thread_id, conv_id, last_seen_msg_id, total_count, channel) VALUES(?,?,?,?,?)",
                  (str(tid), conv_id, str(last_seen) if last_seen is not None else None, total, channel))
    c.commit(); c.close()
