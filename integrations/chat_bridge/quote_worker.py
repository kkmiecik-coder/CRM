# -*- coding: utf-8 -*-
# Kolejka tur quote-bota: pobiera pending z quote_queue, wola run_quote_turn (albo,
# dla persony "pro", bots_pro.tura.uruchom), retry+backoff wielopoziomowy, circuit-breaker
# na seryjne awarie LLM (TO-04) KEYOWANY PER PERSONA; po wyczerpaniu prob -> failed +
# przeprosiny i handoff do agenta.
import time
from config import (BOT_MAX_ATTEMPTS, BOT_BACKOFF_TIERS, BOT_CIRCUIT_THRESHOLD,
                    BOT_CIRCUIT_COOLDOWN)
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.events import log_event
from bots.quotebot import run_quote_turn, handoff_with_apology, komunikat_obciazenia, _LLMHttpError
# `bots_pro.stan` NIE zalezy od pakietu `agents` (SDK) — bezpieczny import na poziomie modulu
# nawet w wariancie testow "bez SDK" (w odroznieniu od `bots_pro.tura`, importowanego LOKALNIE
# nizej, w process_one, tylko gdy trafi sie tura persony "pro").
from bots_pro.stan import init_pro as init_pro_stan

_STALE_PROCESSING = 180   # rekord 'processing' bez postepu dluzej niz tyle sekund -> odzyskujemy

# Circuit-breaker (TO-04): licznik kolejnych bledow retryable i deadline pauzy kolejki,
# trzymane w tabeli meta (przetrwaja restart workera).
#
# Task 7 (Debus Pro): obwod byl JEDNYM, globalnym stanem dla calej kolejki — awaria
# NOWEGO silnika (bots_pro, Agents SDK) otwieralaby go i wstrzymywala tez OLX/Allegro/
# livechat (legacy silnik run_quote_turn), mimo ze to dwa NIEZALEZNE punkty awarii
# (rozne biblioteki, rozne wywolania sieciowe). `_klucze_obwodu` daje personie "pro"
# WLASNY klucz w tabeli meta; wszystkie pozostale persony (dzis: quote/quote_olx/
# quote_allegro) nadal dziela DOKLADNIE ten sam, nieformatowany klucz co przed tym
# zadaniem — zero zmiany zachowania/testow dla legacy silnika w typowym przypadku
# (tylko jedna persona naraz w grze).
_META_CIRCUIT_UNTIL = "quote_llm_circuit_open_until"
_META_CIRCUIT_FAILS = "quote_llm_circuit_consecutive_fails"


def _klucze_obwodu(persona):
    """Para (klucz_until, klucz_fails) w tabeli meta dla danej persony tury.

    "pro" (Debus Pro) dostaje wlasny, odrebny klucz. Wszystkie pozostale persony
    (legacy silnik) dziela WSPOLNY, nieformatowany klucz — DOKLADNIE ten sam
    string, ktorego uzywaly przed tym zadaniem (wsteczna zgodnosc z istniejacymi
    testami circuit-breakera w test_llm_resilience.py/test_quote_worker.py, ktore
    odwoluja sie do `_META_CIRCUIT_UNTIL`/`_META_CIRCUIT_FAILS` bezposrednio, bez
    formatowania)."""
    if persona == "pro":
        return (_META_CIRCUIT_UNTIL + "_pro", _META_CIRCUIT_FAILS + "_pro")
    return (_META_CIRCUIT_UNTIL, _META_CIRCUIT_FAILS)


def _circuit_open(now, persona="quote"):
    klucz_until, _ = _klucze_obwodu(persona)
    return now < float(meta_get(klucz_until, 0) or 0)


def _circuit_record_success(persona="quote"):
    _, klucz_fails = _klucze_obwodu(persona)
    meta_set(klucz_fails, 0)


def _circuit_record_failure(now, persona="quote"):
    """Zwraca True gdy ten blad WLASNIE otworzyl obwod (pierwszy raz po progu) — wtedy
    wolajacy wysyla klientowi lagodny komunikat zamiast pelnego handoffu z kasowaniem danych.
    Inkrementacja w jednym atomowym SQL UPSERT (nie get-potem-set na dwoch polaczeniach) —
    kilka nakladajacych sie kontenerow workera (deploy) nie zgubi wtedy przyrostu licznika.
    Wlasne polaczenie (nie meta_get/meta_set) NIE dziedziczy ich ochrony przed przejsciowymi
    bledami sqlite — wlasny try/except jest wiec konieczny (bezpieczny fallback: obwod NIE
    otworzyl sie wlasnie), zeby awaria bazy w trakcie prawdziwej awarii LLM nie wypadla z
    process_one poza jego wlasny except i nie zostawila rekordu kolejki utknietego."""
    klucz_until, klucz_fails = _klucze_obwodu(persona)
    try:
        c = db()
        c.execute("INSERT INTO meta(k, v) VALUES(?, '1') "
                  "ON CONFLICT(k) DO UPDATE SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT)",
                  (klucz_fails,))
        fails = int(c.execute("SELECT v FROM meta WHERE k=?", (klucz_fails,)).fetchone()["v"])
        opened = fails >= BOT_CIRCUIT_THRESHOLD
        if opened:
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (klucz_until, str(now + BOT_CIRCUIT_COOLDOWN)))
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (klucz_fails, "0"))
        c.commit(); c.close()
        return opened
    except Exception:
        return False


def _backoff_for(attempts):
    idx = min(attempts, len(BOT_BACKOFF_TIERS)) - 1
    return BOT_BACKOFF_TIERS[idx]


def _fail_permanently(qid, conv_id, attempts, err, retryable, persona="quote"):
    """Koniec probowania (4xx od razu, albo retryable po wyczerpaniu BOT_MAX_ATTEMPTS) —
    kolejka 'failed', telemetria i przeprosiny+handoff z powodem opisujacym FAKTYCZNA
    przyczyne (dla 4xx to trwaly blad po 1 probie, nie "wyczerpane proby")."""
    c = db(); c.execute("UPDATE quote_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                        (attempts, err, qid)); c.commit(); c.close()
    log("quotebot: tura NIEUDANA%s (conv %s): %s" %
        ("" if retryable else " (4xx, bez retry)", conv_id, err))
    log_event(conv_id, "failed", {"powod": err, "retryable": retryable})
    reason = ("błąd techniczny bota (wyczerpane próby)" if retryable
              else "błąd techniczny bota (trwały błąd, bez ponawiania)")
    try:
        handoff_with_apology(conv_id, reason=reason, persona=persona)
    except Exception:
        pass


def process_one(now):
    c = db()
    # Stale-recovery (AR-04): rekord utknal w 'processing' (crash/restart w trakcie tury) -> pending.
    # Dziala NIEZALEZNIE od stanu OBU obwodow — inaczej rekord utkniety podczas awarii LLM czekalby
    # az do konca _STALE_PROCESSING zamiast odzyskac sie od razu.
    c.execute("UPDATE quote_queue SET status='pending' WHERE status='processing' AND next_at<=?",
              (now - _STALE_PROCESSING,))
    c.commit()
    # Task 7: obwod "pro" (Debus Pro) i obwod "legacy" (run_quote_turn) sa NIEZALEZNE — otwarcie
    # jednego NIE MA wstrzymywac brania pracy nalezacej do drugiego (patrz docstring przy
    # _klucze_obwodu). Zamiast dawnego pojedynczego `if _circuit_open(now): return False` (ktore
    # wstrzymywalo CALA kolejke, niezaleznie od persony), filtrujemy w samym SELECT: wiersze
    # persony, ktorej obwod jest otwarty, po prostu nie sa dzis kandydatami do wziecia. Gdy
    # obwod tej persony sie zamknie, jej wiersze (nadal 'pending', bo status sie nie zmienil)
    # znow staja sie widoczne — bez dodatkowej ksiegowosci.
    legacy_otwarty = _circuit_open(now, persona="quote")
    pro_otwarty = _circuit_open(now, persona="pro")
    if legacy_otwarty and pro_otwarty:
        warunek_persony = "AND 1=0"
    elif legacy_otwarty:
        warunek_persony = "AND COALESCE(q.persona,'quote')='pro'"
    elif pro_otwarty:
        warunek_persony = "AND COALESCE(q.persona,'quote')!='pro'"
    else:
        warunek_persony = ""
    # Szeregowanie per conv_id (API-06): nie bierzemy nowszego rekordu rozmowy, gdy starszy tej samej
    # rozmowy jeszcze czeka (pending/processing) — zachowujemy kolejnosc wiadomosci.
    row = c.execute(
        "SELECT * FROM quote_queue q WHERE q.status='pending' AND q.next_at<=? %s "
        "AND NOT EXISTS (SELECT 1 FROM quote_queue e WHERE e.conv_id=q.conv_id AND e.id<q.id "
        "AND e.status IN ('pending','processing')) ORDER BY q.id LIMIT 1" % warunek_persony,
        (now,)).fetchone()
    if not row:
        c.commit(); c.close()
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    # Persona/kanal tury (kolumna dodana dla OLX) — NULL/brak => domyslnie 'quote' (livechat).
    try:
        persona = row["persona"] or "quote"
    except Exception:
        persona = "quote"
    # Atomowy claim (API-09/AR-04): tylko jeden worker przetworzy rekord — deploy/overlap kontenerow
    # nie zdubluje tury. next_at = deadline claimu (stale-recovery po _STALE_PROCESSING).
    cur = c.execute("UPDATE quote_queue SET status='processing', next_at=? WHERE id=? AND status='pending'",
                    (now + _STALE_PROCESSING, qid))
    claimed = cur.rowcount
    c.commit(); c.close()
    if not claimed:
        return True   # ktos inny zajal rekord w miedzyczasie — sprobuj kolejny obieg
    # Po claimie rekord jest 'processing' -> enqueue nie moze go juz scalic. Odczytujemy FINALNA
    # tresc/zalaczniki/mid (scalenie w oknie ciszy moglo dojsc miedzy pierwszym SELECT a claimem) —
    # inaczej przetworzylibysmy nieaktualna wiadomosc i zgubili dopiski klienta z okna ciszy.
    c = db()
    fresh = c.execute("SELECT message_id, content, attachments FROM quote_queue WHERE id=?", (qid,)).fetchone()
    c.close()
    if fresh is not None:
        mid, content, attachments = fresh["message_id"], fresh["content"], fresh["attachments"]
    else:
        attachments = row["attachments"]
    try:
        if persona == "pro":
            # Debus Pro: silnik Agents SDK, calkowicie osobny od run_quote_turn. Import
            # LOKALNY (nie na poziomie modulu) — `bots_pro.tura` importuje `agents` (SDK)
            # przy imporcie modulu; gdy SDK nie jest zainstalowane (np. testy "bez SDK"),
            # caly quote_worker.py ma zostac importowalny, a blad ma wypasc TYLKO wtedy,
            # gdy naprawde trafi sie tura persony "pro" (i wtedy leci w except ponizej,
            # traktowany jak kazdy inny blad — patrz klasyfikacja retryable nizej).
            from bots_pro.tura import uruchom as uruchom_pro
            uruchom_pro(conv_id, inbox_id, content, zalaczniki=attachments, persona=persona)
        else:
            run_quote_turn(conv_id, inbox_id, mid, content, attachments=attachments, persona=persona)
        c = db(); c.execute("UPDATE quote_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        _circuit_record_success(persona=persona)
        log("quotebot: tura przetworzona (conv %s)" % conv_id)
    except Exception as e:
        attempts += 1
        err = repr(e)
        # Task 7: bylo `retryable = getattr(e, "retryable", True)` — KAZDY nieoznaczony
        # wyjatek (TypeError, KeyError, blad w kodzie bota...) byl domyslnie retryable=True
        # i ponawiany w kolko jak przejsciowa awaria sieci. Przy nowym bocie to grozniejsze
        # niz przy starym: bledy programistyczne w bots_pro (SDK wciaz sie rozwija) NIE maja
        # pchac sie w petle retry+backoff+circuit-breaker, tylko od razu konczyc jako trwaly
        # blad (jak 4xx) — wyjatki BEZ jawnego .retryable sa retryable TYLKO gdy naleza do
        # znanych, faktycznie przejsciowych klas (blad HTTP LLM, siec).
        retryable = getattr(e, "retryable", None)
        if retryable is None:
            retryable = isinstance(e, (_LLMHttpError, ConnectionError, TimeoutError))
        if not retryable:
            # TO-04: 4xx (zla konfiguracja/klucz) -> fail od razu, bez backoffu ani wliczania
            # w prog circuit-breakera (to nie przejsciowa niedostepnosc LLM, tylko trwaly blad).
            _fail_permanently(qid, conv_id, attempts, err, retryable=False, persona=persona)
            return True
        if _circuit_record_failure(now, persona=persona):
            # Obwod WLASNIE sie otworzyl — jeden lagodny komunikat zamiast lawiny handoffow
            # z kasowaniem danych (kolejne rekordy z pending poczekaja, bo process_one
            # filtruje wiersze tej persony az do zamkniecia obwodu).
            try:
                komunikat_obciazenia(conv_id, persona=persona)
            except Exception:
                pass
            log("quote_worker: circuit-breaker (%s) OTWARTY na %ss (conv %s)"
                % (persona, BOT_CIRCUIT_COOLDOWN, conv_id))
        if attempts >= BOT_MAX_ATTEMPTS:
            _fail_permanently(qid, conv_id, attempts, err, retryable=True, persona=persona)
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
    # DDL Debusia Pro (tabele pro_dane/pro_stan) — RAZ, przy starcie workera, nie przy kazdej
    # turze (przeniesione tu z bots_pro.tura.uruchom w ramach Task 7 — patrz jego docstring).
    init_pro_stan()
    while True:
        try:
            if not process_one(time.time()):
                time.sleep(2)
        except Exception as e:
            log("quote_worker ERROR:", repr(e)); time.sleep(3)
