# -*- coding: utf-8 -*-
# Kolejka tur quote-bota: pobiera pending z quote_queue, wola run_quote_turn, retry+backoff
# wielopoziomowy, circuit-breaker na seryjne awarie LLM (TO-04); po wyczerpaniu prob ->
# failed + przeprosiny i handoff do agenta.
import time
from config import (BOT_MAX_ATTEMPTS, BOT_BACKOFF_TIERS, BOT_CIRCUIT_THRESHOLD,
                    BOT_CIRCUIT_COOLDOWN, BOT_QUOTE_CW_AGENT_TOKEN)
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.events import log_event
from core.chatwoot import cw_agent_reply
from bots.quotebot import run_quote_turn, handoff_with_apology

_STALE_PROCESSING = 180   # rekord 'processing' bez postepu dluzej niz tyle sekund -> odzyskujemy

# Circuit-breaker (TO-04): licznik kolejnych bledow retryable i deadline pauzy kolejki,
# trzymane w tabeli meta (przetrwaja restart workera).
_META_CIRCUIT_UNTIL = "quote_llm_circuit_open_until"
_META_CIRCUIT_FAILS = "quote_llm_circuit_consecutive_fails"

_OBCIAZENIE_MSG = "Mamy chwilowe obciążenie systemu — odpowiemy za chwilę."


def _circuit_open(now):
    return now < float(meta_get(_META_CIRCUIT_UNTIL, 0) or 0)


def _circuit_record_success():
    meta_set(_META_CIRCUIT_FAILS, 0)


def _circuit_record_failure(now):
    """Zwraca True gdy ten blad WLASNIE otworzyl obwod (pierwszy raz po progu) — wtedy
    wolajacy wysyla klientowi lagodny komunikat zamiast pelnego handoffu z kasowaniem danych."""
    fails = int(meta_get(_META_CIRCUIT_FAILS, 0) or 0) + 1
    meta_set(_META_CIRCUIT_FAILS, fails)
    if fails >= BOT_CIRCUIT_THRESHOLD:
        meta_set(_META_CIRCUIT_UNTIL, now + BOT_CIRCUIT_COOLDOWN)
        meta_set(_META_CIRCUIT_FAILS, 0)
        return True
    return False


def _backoff_for(attempts):
    idx = min(attempts, len(BOT_BACKOFF_TIERS)) - 1
    return BOT_BACKOFF_TIERS[max(0, idx)]


def process_one(now):
    if _circuit_open(now):
        return False   # kolejka wstrzymana — awaria LLM w trakcie, nie mnozymy identycznych bledow
    c = db()
    # Stale-recovery (AR-04): rekord utknal w 'processing' (crash/restart w trakcie tury) -> pending.
    c.execute("UPDATE quote_queue SET status='pending' WHERE status='processing' AND next_at<=?",
              (now - _STALE_PROCESSING,))
    # Szeregowanie per conv_id (API-06): nie bierzemy nowszego rekordu rozmowy, gdy starszy tej samej
    # rozmowy jeszcze czeka (pending/processing) — zachowujemy kolejnosc wiadomosci.
    row = c.execute(
        "SELECT * FROM quote_queue q WHERE q.status='pending' AND q.next_at<=? "
        "AND NOT EXISTS (SELECT 1 FROM quote_queue e WHERE e.conv_id=q.conv_id AND e.id<q.id "
        "AND e.status IN ('pending','processing')) ORDER BY q.id LIMIT 1", (now,)).fetchone()
    if not row:
        c.commit(); c.close()
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    # Atomowy claim (API-09/AR-04): tylko jeden worker przetworzy rekord — deploy/overlap kontenerow
    # nie zdubluje tury. next_at = deadline claimu (stale-recovery po _STALE_PROCESSING).
    cur = c.execute("UPDATE quote_queue SET status='processing', next_at=? WHERE id=? AND status='pending'",
                    (now + _STALE_PROCESSING, qid))
    claimed = cur.rowcount
    c.commit(); c.close()
    if not claimed:
        return True   # ktos inny zajal rekord w miedzyczasie — sprobuj kolejny obieg
    try:
        run_quote_turn(conv_id, inbox_id, mid, content, attachments=row["attachments"])
        c = db(); c.execute("UPDATE quote_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        _circuit_record_success()
        log("quotebot: tura przetworzona (conv %s)" % conv_id)
    except Exception as e:
        attempts += 1
        err = repr(e)
        retryable = getattr(e, "retryable", True)
        if not retryable:
            # TO-04: 4xx (zla konfiguracja/klucz) -> fail od razu, bez backoffu ani wliczania
            # w prog circuit-breakera (to nie przejsciowa niedostepnosc LLM, tylko trwaly blad).
            c = db(); c.execute("UPDATE quote_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                                (attempts, err, qid)); c.commit(); c.close()
            log("quotebot: tura NIEUDANA (4xx, bez retry) (conv %s): %s" % (conv_id, err))
            log_event(conv_id, "failed", {"powod": err, "retryable": False})
            try:
                handoff_with_apology(conv_id)
            except Exception:
                pass
            return True
        if _circuit_record_failure(now):
            # Obwod WLASNIE sie otworzyl — jeden lagodny komunikat zamiast lawiny handoffow
            # z kasowaniem danych (kolejne rekordy z pending poczekaja, bo process_one
            # sprawdza _circuit_open na starcie).
            try:
                cw_agent_reply(conv_id, _OBCIAZENIE_MSG, token=BOT_QUOTE_CW_AGENT_TOKEN)
            except Exception:
                pass
            log("quote_worker: circuit-breaker OTWARTY na %ss (conv %s)" % (BOT_CIRCUIT_COOLDOWN, conv_id))
        if attempts >= BOT_MAX_ATTEMPTS:
            c = db(); c.execute("UPDATE quote_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                                (attempts, err, qid)); c.commit(); c.close()
            log("quotebot: tura NIEUDANA (conv %s): %s" % (conv_id, err))
            log_event(conv_id, "failed", {"powod": err, "retryable": True})
            try:
                handoff_with_apology(conv_id)
            except Exception:
                pass
        else:
            backoff = _backoff_for(attempts)
            # Wracamy do 'pending' (claim ustawil 'processing') z opoznieniem backoff.
            c = db(); c.execute("UPDATE quote_queue SET status='pending', attempts=?, next_at=?, "
                                "last_error=? WHERE id=?", (attempts, now + backoff, err, qid))
            c.commit(); c.close()
            log("quotebot: retry (conv %s) za %ss (proba %s): %s" % (conv_id, backoff, attempts, err))
    return True


def quote_worker():
    # Demonu wątku: ciągły loop przetwarzający quote_queue.
    init_db()
    while True:
        try:
            if not process_one(time.time()):
                time.sleep(2)
        except Exception as e:
            log("quote_worker ERROR:", repr(e)); time.sleep(3)
