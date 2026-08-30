# -*- coding: utf-8 -*-
# Kolejka tur quote-bota: pobiera pending z quote_queue, wola run_quote_turn (albo,
# dla wierszy na inboksie Debusia Pro — patrz _jest_pro_inbox/BOT_PRO_INBOXES —
# bots_pro.tura.uruchom), retry+backoff wielopoziomowy, circuit-breaker na seryjne
# awarie LLM (TO-04) KEYOWANY PER SILNIK (osobno pro/legacy); po wyczerpaniu prob ->
# failed + przeprosiny i handoff do agenta (osobna sciezka dla Debusia Pro — W2).
import time
from config import (BOT_MAX_ATTEMPTS, BOT_BACKOFF_TIERS, BOT_CIRCUIT_THRESHOLD,
                    BOT_CIRCUIT_COOLDOWN, BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_INBOXES)
from core.log import log
from core.db import db, init_db, meta_get, meta_set
from core.events import log_event
from core.chatwoot import cw_agent_reply as _cw_reply_raw, cw_bot_handoff as _cw_handoff_raw
from bots.quotebot import (run_quote_turn, handoff_with_apology, komunikat_obciazenia,
                           _LLMHttpError, APOLOGY_MSG, _OBCIAZENIE_MSG)
# `bots_pro.stan`/`bots_pro.wysylka` NIE zaleza od pakietu `agents` (SDK) — bezpieczny import
# na poziomie modulu nawet w wariancie testow "bez SDK" (w odroznieniu od `bots_pro.tura`,
# importowanego LOKALNIE nizej, w process_one, tylko gdy trafi sie tura na inboksie Pro).
from bots_pro.stan import init_pro as init_pro_stan
from bots_pro.wysylka import przygotuj as _przygotuj_pro

_STALE_PROCESSING = 180   # rekord 'processing' bez postepu dluzej niz tyle sekund -> odzyskujemy

# Circuit-breaker (TO-04): licznik kolejnych bledow retryable i deadline pauzy kolejki,
# trzymane w tabeli meta (przetrwaja restart workera).
#
# Task 7 (Debus Pro): obwod byl JEDNYM, globalnym stanem dla calej kolejki — awaria
# NOWEGO silnika (bots_pro, Agents SDK) otwieralaby go i wstrzymywala tez OLX/Allegro/
# livechat (legacy silnik run_quote_turn), mimo ze to dwa NIEZALEZNE punkty awarii
# (rozne biblioteki, rozne wywolania sieciowe). `_klucze_obwodu` daje KUBELKOWI "pro"
# (wiersze na inboksie Debusia Pro, patrz `_jest_pro_inbox`) WLASNY klucz w tabeli meta;
# kubelek "quote" (wszystko inne — legacy silnik) nadal dostaje DOKLADNIE ten sam,
# nieformatowany klucz co przed tym zadaniem — zero zmiany zachowania/testow dla
# legacy silnika w typowym przypadku (BOT_PRO_INBOXES puste/tylko jeden silnik w grze).
_META_CIRCUIT_UNTIL = "quote_llm_circuit_open_until"
_META_CIRCUIT_FAILS = "quote_llm_circuit_consecutive_fails"


def _klucze_obwodu(kubelek):
    """Para (klucz_until, klucz_fails) w tabeli meta dla danego KUBELKA obwodu
    ("pro" = silnik Debusia Pro, "quote" = legacy silnik run_quote_turn).

    UWAGA (W1 code review, runda poprawek 1): argumentem jest KUBELEK obwodu,
    NIE kolumna `persona` z wiersza kolejki — ta ostatnia dziś niesie WYŁĄCZNIE
    profil kanału/caps (może być "olx"/"allegro"/"pro" nawet dla wierszy Debusia
    Pro, patrz `webhooks._persona_pro_dla_inboxu`). Który silnik obsługuje wiersz
    (a więc i który kubełek obwodu go dotyczy) ustala WYŁĄCZNIE `_jest_pro_inbox`
    (inbox_id + BOT_PRO_INBOXES) — patrz `process_one`.

    "pro" dostaje własny, odrębny klucz. "quote" (wszystko inne — legacy silnik)
    dostaje WSPÓLNY, nieformatowany klucz — DOKŁADNIE ten sam string, którego
    używano przed tym zadaniem (wsteczna zgodność z istniejącymi testami
    circuit-breakera w test_llm_resilience.py/test_quote_worker.py, które
    odwołują się do `_META_CIRCUIT_UNTIL`/`_META_CIRCUIT_FAILS` bezpośrednio,
    bez formatowania)."""
    if kubelek == "pro":
        return (_META_CIRCUIT_UNTIL + "_pro", _META_CIRCUIT_FAILS + "_pro")
    return (_META_CIRCUIT_UNTIL, _META_CIRCUIT_FAILS)


def _circuit_open(now, kubelek="quote"):
    klucz_until, _ = _klucze_obwodu(kubelek)
    return now < float(meta_get(klucz_until, 0) or 0)


def _circuit_record_success(kubelek="quote"):
    _, klucz_fails = _klucze_obwodu(kubelek)
    meta_set(klucz_fails, 0)


def _circuit_record_failure(now, kubelek="quote"):
    """Zwraca True gdy ten blad WLASNIE otworzyl obwod (pierwszy raz po progu) — wtedy
    wolajacy wysyla klientowi lagodny komunikat zamiast pelnego handoffu z kasowaniem danych.
    Inkrementacja w jednym atomowym SQL UPSERT (nie get-potem-set na dwoch polaczeniach) —
    kilka nakladajacych sie kontenerow workera (deploy) nie zgubi wtedy przyrostu licznika.
    Wlasne polaczenie (nie meta_get/meta_set) NIE dziedziczy ich ochrony przed przejsciowymi
    bledami sqlite — wlasny try/except jest wiec konieczny (bezpieczny fallback: obwod NIE
    otworzyl sie wlasnie), zeby awaria bazy w trakcie prawdziwej awarii LLM nie wypadla z
    process_one poza jego wlasny except i nie zostawila rekordu kolejki utknietego."""
    klucz_until, klucz_fails = _klucze_obwodu(kubelek)
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


def _jest_pro_inbox(inbox_id):
    """Czy dany inbox nalezy do Debusia Pro — JEDYNE zrodlo prawdy o tym, KTORY
    silnik obsluguje wiersz kolejki (bots_pro vs legacy run_quote_turn). Task 7,
    W1 code review: wczesniej rozgraniczal to string persona=="pro", ale persona
    dzis niesie profil kanalu (moze byc "olx"/"allegro" nawet dla Debusia Pro) —
    wiec rozgraniczenie silnika MUSI isc inna droga niz rozgraniczenie capsow."""
    return str(inbox_id) in BOT_PRO_INBOXES


def _pro_wyslij(conv_id, tekst, persona):
    """Wysyla komunikat wlasnym tokenem i wlasnymi (kanalowymi) capsami Debusia
    Pro — BEZ handoffu (uzywane przy otwarciu obwodu, gdzie rozmowa zostaje
    dalej przy bocie). Task 7, W2 code review: `komunikat_obciazenia` z
    bots/quotebot.py uzylaby tu STAREGO tokenu (BOT_QUOTE_CW_AGENT_TOKEN) i
    DEFAULT_CAPS (markdown/emoji/LINKI wlaczone) niezaleznie od kanalu — na
    Allegro to dokladnie ten sam wyciek linkow, przed ktorym chroni normalna
    sciezka odpowiedzi (bots_pro.wysylka). Nigdy nie rzuca — sciezka awaryjna."""
    try:
        for czesc in _przygotuj_pro(tekst, persona):
            if czesc:
                _cw_reply_raw(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
    except Exception as e:
        log("quote_worker: wysylka komunikatu pro nieudana (conv %s): %r" % (conv_id, e))


def _pro_apologia_i_handoff(conv_id, tekst, persona):
    """Jak `_pro_wyslij`, plus oddanie rozmowy czlowiekowi wlasnym tokenem
    (uzywane po wyczerpaniu prob — patrz `_fail_permanently`). Swiadomie NIE
    wola `bots.quotebot._do_handoff` — ta funkcja czyta/zeruje quote_state/
    quote_dane (tabele legacy silnika), puste dla rozmowy, ktora cala swoja
    historie ma w bots_pro/SQLiteSession, wiec notatka podsumowujaca bylaby
    pusta i podpisana niewlasciwym botem."""
    _pro_wyslij(conv_id, tekst, persona)
    try:
        _cw_handoff_raw(conv_id, token=BOT_PRO_CW_AGENT_TOKEN)
    except Exception as e:
        log("quote_worker: handoff pro nieudany (conv %s): %r" % (conv_id, e))


def _fail_permanently(qid, conv_id, attempts, err, retryable, persona="quote", jest_pro=False):
    """Koniec probowania (4xx od razu, albo retryable po wyczerpaniu BOT_MAX_ATTEMPTS) —
    kolejka 'failed', telemetria i przeprosiny+handoff z powodem opisujacym FAKTYCZNA
    przyczyne (dla 4xx to trwaly blad po 1 probie, nie "wyczerpane proby").

    `jest_pro` (Task 7, W2 code review) rozgalezia sciezke przeprosin: Debus Pro
    dostaje WLASNA (`_pro_apologia_i_handoff`, wlasny token + wlasne caps kanalu),
    legacy silnik zachowuje dotychczasowa `handoff_with_apology` bez zmian."""
    c = db(); c.execute("UPDATE quote_queue SET status='failed', attempts=?, last_error=? WHERE id=?",
                        (attempts, err, qid)); c.commit(); c.close()
    log("quotebot: tura NIEUDANA%s (conv %s): %s" %
        ("" if retryable else " (4xx, bez retry)", conv_id, err))
    log_event(conv_id, "failed", {"powod": err, "retryable": retryable})
    try:
        if jest_pro:
            _pro_apologia_i_handoff(conv_id, APOLOGY_MSG, persona)
        else:
            reason = ("błąd techniczny bota (wyczerpane próby)" if retryable
                      else "błąd techniczny bota (trwały błąd, bez ponawiania)")
            handoff_with_apology(conv_id, reason=reason, persona=persona)
    except Exception:
        pass


def _filtr_obwodow_sql(now):
    """Fragment WHERE + parametry wykluczajace z SELECT wiersze silnika, ktorego
    obwod jest w tej chwili otwarty. Silnik wiersza jest okreslany przez
    inbox_id + BOT_PRO_INBOXES (`_jest_pro_inbox`), NIE przez kolumne persona —
    patrz `_klucze_obwodu`. Zwraca (sql, parametry); sql to gotowy fragment
    " AND ..." (albo pusty string, gdy zaden obwod nie jest otwarty)."""
    legacy_otwarty = _circuit_open(now, kubelek="quote")
    pro_otwarty = _circuit_open(now, kubelek="pro")
    if not legacy_otwarty and not pro_otwarty:
        return "", []
    if legacy_otwarty and pro_otwarty:
        return "AND 1=0", []
    pro_inboxy = sorted(BOT_PRO_INBOXES)
    if not pro_inboxy:
        # Brak skonfigurowanych inboksow Debusia Pro -> WSZYSTKIE wiersze sa legacy.
        # Obwod "pro" otwarty nie ma wtedy czego blokowac (zero takich wierszy);
        # obwod legacy otwarty blokuje WSZYSTKO (bo wszystko jest legacy).
        return ("", []) if pro_otwarty else ("AND 1=0", [])
    znaczniki = ",".join("?" * len(pro_inboxy))
    if legacy_otwarty:
        return "AND q.inbox_id IN (%s)" % znaczniki, list(pro_inboxy)
    return "AND q.inbox_id NOT IN (%s)" % znaczniki, list(pro_inboxy)


def process_one(now):
    c = db()
    # Stale-recovery (AR-04): rekord utknal w 'processing' (crash/restart w trakcie tury) -> pending.
    # Dziala NIEZALEZNIE od stanu OBU obwodow — inaczej rekord utkniety podczas awarii LLM czekalby
    # az do konca _STALE_PROCESSING zamiast odzyskac sie od razu.
    c.execute("UPDATE quote_queue SET status='pending' WHERE status='processing' AND next_at<=?",
              (now - _STALE_PROCESSING,))
    c.commit()
    # Task 7: obwod "pro" (Debus Pro) i obwod "legacy" (run_quote_turn) sa NIEZALEZNE — otwarcie
    # jednego NIE MA wstrzymywac brania pracy nalezacej do drugiego. Zamiast dawnego pojedynczego
    # `if _circuit_open(now): return False` (ktore wstrzymywalo CALA kolejke), filtrujemy w samym
    # SELECT: wiersze silnika, ktorego obwod jest otwarty, po prostu nie sa dzis kandydatami do
    # wziecia. Gdy obwod sie zamknie, te wiersze (nadal 'pending') znow staja sie widoczne.
    warunek_obwodow, parametry_obwodow = _filtr_obwodow_sql(now)
    # Szeregowanie per conv_id (API-06): nie bierzemy nowszego rekordu rozmowy, gdy starszy tej samej
    # rozmowy jeszcze czeka (pending/processing) — zachowujemy kolejnosc wiadomosci.
    row = c.execute(
        "SELECT * FROM quote_queue q WHERE q.status='pending' AND q.next_at<=? %s "
        "AND NOT EXISTS (SELECT 1 FROM quote_queue e WHERE e.conv_id=q.conv_id AND e.id<q.id "
        "AND e.status IN ('pending','processing')) ORDER BY q.id LIMIT 1" % warunek_obwodow,
        tuple([now] + parametry_obwodow)).fetchone()
    if not row:
        c.commit(); c.close()
        return False
    qid, conv_id, inbox_id = row["id"], row["conv_id"], row["inbox_id"]
    mid, content, attempts = row["message_id"], row["content"], row["attempts"]
    # Persona/kanal tury (kolumna dodana dla OLX) — NULL/brak => domyslnie 'quote' (livechat).
    # Dla wierszy Debusia Pro to profil CAPS kanalu ("olx"/"allegro"/"pro" — patrz
    # webhooks._persona_pro_dla_inboxu), NIE sygnal silnika (ten daje _jest_pro_inbox nizej).
    try:
        persona = row["persona"] or "quote"
    except Exception:
        persona = "quote"
    jest_pro = _jest_pro_inbox(inbox_id)
    kubelek = "pro" if jest_pro else "quote"
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
        if jest_pro:
            # Debus Pro: silnik Agents SDK, calkowicie osobny od run_quote_turn. Import
            # LOKALNY (nie na poziomie modulu) — `bots_pro.tura` importuje `agents` (SDK)
            # przy imporcie modulu; gdy SDK nie jest zainstalowane (np. testy "bez SDK"),
            # caly quote_worker.py ma zostac importowalny, a blad ma wypasc TYLKO wtedy,
            # gdy naprawde trafi sie tura na inboksie Pro (i wtedy leci w except ponizej,
            # traktowany jak kazdy inny blad — patrz klasyfikacja retryable nizej).
            from bots_pro.tura import uruchom as uruchom_pro
            uruchom_pro(conv_id, inbox_id, content, zalaczniki=attachments, persona=persona)
        else:
            run_quote_turn(conv_id, inbox_id, mid, content, attachments=attachments, persona=persona)
        c = db(); c.execute("UPDATE quote_queue SET status='sent' WHERE id=?", (qid,)); c.commit(); c.close()
        _circuit_record_success(kubelek=kubelek)
        log("quotebot: tura przetworzona (conv %s)" % conv_id)
    except Exception as e:
        attempts += 1
        err = repr(e)
        # K2 (code review, runda poprawek 1): bylo `retryable = getattr(e, "retryable", True)`
        # — KAZDY nieoznaczony wyjatek (TypeError, KeyError, przejsciowa czkawka Chatwoota
        # sygnalizowana golym RuntimeError w bots/quotebot.py — 21+ miejsc, w tym
        # _wolno_prowadzic_rozmowe) byl domyslnie retryable=True. Zawezenie do znanych,
        # faktycznie przejsciowych klas MIALO objac WYLACZNIE Debusia Pro (persona "pro" w
        # briefie zlecenia) — zastosowanie go do WSZYSTKICH person cofnieoby retry dla
        # zywego ruchu legacy (livechat/OLX/Allegro), na co nic nie chronilo
        # (test_quote_idempotency.py zaklada, ze po golym RuntimeError przyjdzie retry).
        # Stad rozgraniczenie po `jest_pro`, nie globalnie.
        retryable = getattr(e, "retryable", None)
        if retryable is None:
            if jest_pro:
                retryable = isinstance(e, (_LLMHttpError, ConnectionError, TimeoutError))
            else:
                retryable = True   # zachowanie legacy SPRZED tego zadania, bez zmian
        if not retryable:
            # TO-04: 4xx (zla konfiguracja/klucz) -> fail od razu, bez backoffu ani wliczania
            # w prog circuit-breakera (to nie przejsciowa niedostepnosc LLM, tylko trwaly blad).
            _fail_permanently(qid, conv_id, attempts, err, retryable=False, persona=persona,
                             jest_pro=jest_pro)
            return True
        if _circuit_record_failure(now, kubelek=kubelek):
            # Obwod WLASNIE sie otworzyl — jeden lagodny komunikat zamiast lawiny handoffow
            # z kasowaniem danych (kolejne rekordy z pending poczekaja, bo process_one
            # filtruje wiersze tego silnika az do zamkniecia obwodu).
            try:
                if jest_pro:
                    _pro_wyslij(conv_id, _OBCIAZENIE_MSG, persona)
                else:
                    komunikat_obciazenia(conv_id, persona=persona)
            except Exception:
                pass
            log("quote_worker: circuit-breaker (%s) OTWARTY na %ss (conv %s)"
                % (kubelek, BOT_CIRCUIT_COOLDOWN, conv_id))
        if attempts >= BOT_MAX_ATTEMPTS:
            _fail_permanently(qid, conv_id, attempts, err, retryable=True, persona=persona,
                             jest_pro=jest_pro)
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
