# -*- coding: utf-8 -*-
# Test: odpornosc na awarie LLM (TO-04) — klasyfikacja bledu w quotebot.py, backoff wielopoziomowy
# i circuit-breaker w quote_worker.py.
import os, tempfile
import pytest
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_resilience.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
qw = importlib.import_module("quote_worker"); importlib.reload(qw)


def _reset(conv_id):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()


def test_llm_http_error_4xx_nie_jest_retryable(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    _reset(1101)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (None, {"error_class": "4xx"}))
    try:
        qb.run_quote_turn(1101, 5, "m1", "cześć")
        assert False, "powinno rzucic"
    except qb._LLMHttpError as e:
        assert e.retryable is False


def test_llm_http_error_429_jest_retryable(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    _reset(1102)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (None, {"error_class": "429"}))
    try:
        qb.run_quote_turn(1102, 5, "m1", "cześć")
        assert False, "powinno rzucic"
    except qb._LLMHttpError as e:
        assert e.retryable is True


def test_llm_http_error_transport_jest_retryable(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    _reset(1103)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (None, {"error_class": "transport"}))
    try:
        qb.run_quote_turn(1103, 5, "m1", "cześć")
        assert False, "powinno rzucic"
    except qb._LLMHttpError as e:
        assert e.retryable is True


# --- quote_worker: backoff wielopoziomowy + rozroznienie retryable ---

def _enqueue(conv_id, attempts=0):
    # process_one() bierze GLOBALNIE najstarszy pasujacy rekord (bez filtra po conv_id) —
    # czyscimy CALA kolejke (nie tylko wiersze tego conv_id), zeby porzucone 'pending' rekordy
    # z innych testow/plikow (dzielony bridge.db w calej sesji testowej) nie zostaly wziete
    # zamiast tego, ktory ten test wlasnie przygotowal.
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue")
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, attempts, next_at) "
              "VALUES(?,?,?,?,?,0)", (conv_id, 18, "m1", "tak", attempts))
    c.commit(); c.close()


def _reset_circuit():
    from core.db import meta_set
    meta_set(qw._META_CIRCUIT_UNTIL, 0)
    meta_set(qw._META_CIRCUIT_FAILS, 0)


@pytest.fixture(autouse=True)
def _circuit_state_isolation():
    """Stan circuit-breakera zyje w tabeli meta — GLOBALNEJ, nie per-conv_id — i przetrwalby
    poza ta ture testowa w calym (dzielonym miedzy plikami testow) bridge.db. Bez tego np. test
    otwierajacy obwod zostawilby quote_llm_circuit_open_until w przyszlosci i zepsulby
    process_one(...) w zupelnie innym pliku testow uruchomionym pozniej w tej samej sesji."""
    _reset_circuit()
    yield
    _reset_circuit()


def test_backoff_wielopoziomowy_30_120_300(monkeypatch):
    monkeypatch.setattr(config, "BOT_MAX_ATTEMPTS", 4)
    monkeypatch.setattr(qw, "BOT_MAX_ATTEMPTS", 4)
    monkeypatch.setattr(qw, "BOT_BACKOFF_TIERS", [30, 120, 300])
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda *a, **k: (_ for _ in ()).throw(qb._LLMHttpError("boom", retryable=True)))
    _enqueue(1110)
    now = 1_000_000
    qw.process_one(now)
    c = db_mod.db(); row = c.execute("SELECT attempts, next_at FROM quote_queue WHERE conv_id=1110").fetchone(); c.close()
    assert row["attempts"] == 1 and row["next_at"] == now + 30

    _enqueue(1110, attempts=1)
    qw.process_one(now)
    c = db_mod.db(); row = c.execute("SELECT attempts, next_at FROM quote_queue WHERE conv_id=1110").fetchone(); c.close()
    assert row["attempts"] == 2 and row["next_at"] == now + 120

    _enqueue(1110, attempts=2)
    qw.process_one(now)
    c = db_mod.db(); row = c.execute("SELECT attempts, next_at FROM quote_queue WHERE conv_id=1110").fetchone(); c.close()
    assert row["attempts"] == 3 and row["next_at"] == now + 300


def test_4xx_konczy_sie_od_razu_bez_backoffu(monkeypatch):
    handed = []
    monkeypatch.setattr(qw, "handoff_with_apology", lambda c, reason=None: handed.append(c))
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda *a, **k: (_ for _ in ()).throw(qb._LLMHttpError("boom", retryable=False)))
    _enqueue(1111)
    qw.process_one(1_000_000)
    c = db_mod.db(); row = c.execute("SELECT status, attempts FROM quote_queue WHERE conv_id=1111").fetchone(); c.close()
    assert row["status"] == "failed" and row["attempts"] == 1
    assert handed == [1111]


def test_sukces_resetuje_licznik_circuit_breakera(monkeypatch):
    from core.db import meta_set
    meta_set(qw._META_CIRCUIT_FAILS, 3)
    monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)
    _enqueue(1112)
    qw.process_one(1_000_000)
    from core.db import meta_get
    assert int(meta_get(qw._META_CIRCUIT_FAILS, 0)) == 0


def test_circuit_breaker_otwiera_sie_po_progu_i_wstrzymuje_kolejke(monkeypatch):
    monkeypatch.setattr(qw, "BOT_CIRCUIT_THRESHOLD", 2)
    monkeypatch.setattr(qw, "BOT_CIRCUIT_COOLDOWN", 60)
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda *a, **k: (_ for _ in ()).throw(qb._LLMHttpError("boom", retryable=True)))
    monkeypatch.setattr(qw, "cw_agent_reply", lambda c, t, **kw: True)
    _enqueue(1113)
    now = 2_000_000
    qw.process_one(now)   # 1. blad
    _enqueue(1113, attempts=1)
    qw.process_one(now)   # 2. blad -> prog=2 -> otwiera obwod
    from core.db import meta_get
    assert float(meta_get(qw._META_CIRCUIT_UNTIL, 0)) > now

    _enqueue(1114)   # inna rozmowa - obwod otwarty ma zablokowac przetwarzanie w ogole
    assert qw.process_one(now) is False


def test_obwod_zamyka_sie_po_cooldownie(monkeypatch):
    from core.db import meta_set
    meta_set(qw._META_CIRCUIT_UNTIL, 1_000_000)   # obwod byl otwarty do tego czasu
    monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)
    _enqueue(1115)
    assert qw.process_one(1_000_001) is True   # po cooldownie kolejka znow dziala


def test_meta_get_meta_set_przezywaja_awarie_bazy(monkeypatch):
    """Regresja code review Task 7 (angle C): meta_get/meta_set byly jedynymi helperami w
    core/db.py bez try/except (w odroznieniu od init_db i reszty kodu, gdzie przejsciowe
    bledy sqlite nigdy nie maja crashowac logiki bota). Uwaga: to NIE pokrywa
    _circuit_record_failure — ta funkcja ma WLASNE polaczenie db(), patrz test ponizej."""
    def _boom():
        raise db_mod.sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db_mod, "db", _boom)
    assert db_mod.meta_get("brak-takiego-klucza", "domyslna") == "domyslna"
    db_mod.meta_set("cokolwiek", "1")   # nie rzuca mimo niedostepnej bazy


def test_circuit_record_failure_przezywa_awarie_bazy(monkeypatch):
    """Regresja code review Task 7 (runda 2): _circuit_record_failure robi wlasny atomowy
    UPSERT przez `db()` zaimportowane bezposrednio do quote_worker (nie przez meta_get/meta_set),
    wiec fix powyzej jej NIE obejmuje. Przejsciowy 'database is locked' (najbardziej
    prawdopodobny WLASNIE podczas prawdziwej awarii LLM, gdy nakladajace sie kontenery
    workera rywalizuja o zapis do tego samego wiersza meta) rzucalby sie w gore z process_one
    poza jego wlasny except, zostawiajac zaklamany rekord kolejki utkniety w 'processing'
    i NIE inkrementujac licznika obwodu wlasnie wtedy, gdy jest to najbardziej potrzebne."""
    def _boom():
        raise db_mod.sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(qw, "db", _boom)
    assert qw._circuit_record_failure(1_000_000) is False   # bezpieczny fallback, nie rzuca


def test_stale_recovery_dziala_mimo_otwartego_obwodu(monkeypatch):
    """Regresja: circuit-open MA wstrzymac branie NOWEJ pracy, ale odzyskiwanie rekordow
    utknietych w 'processing' (crash/restart workera w trakcie tury) ma dzialac zawsze —
    inaczej rekord czeka utkniety az do konca pauzy obwodu zamiast wrocic do 'pending' od razu."""
    from core.db import meta_set
    now = 3_000_000
    meta_set(qw._META_CIRCUIT_UNTIL, now + 999999)   # obwod otwarty daleko w przyszlosc
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue")
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, attempts, status, next_at) "
              "VALUES(?,?,?,?,?,?,?)", (1116, 18, "m1", "tak", 0, "processing", now - qw._STALE_PROCESSING - 10))
    c.commit(); c.close()
    assert qw.process_one(now) is False   # obwod otwarty -> nie bierze nowej pracy
    c = db_mod.db(); row = c.execute("SELECT status FROM quote_queue WHERE conv_id=1116").fetchone(); c.close()
    assert row["status"] == "pending"   # ale utkniety rekord ODZYSKANY mimo pauzy


def test_4xx_ma_inny_powod_handoffu_niz_wyczerpane_proby(monkeypatch):
    """Regresja: sciezka 4xx-fail-fast konczy sie po JEDNEJ probie, wiec powod przekazany
    do _do_handoff/notatki dla konsultanta nie moze brzmiec 'wyczerpane proby' (mylace —
    sugerowaloby wielokrotne, przejsciowe niepowodzenia zamiast trwalego bledu konfiguracji)."""
    powody = []
    monkeypatch.setattr(qb, "_do_handoff", lambda conv_id, powod, dane, closing=None: powody.append(powod))
    monkeypatch.setattr(qb, "_load_dane", lambda conv_id: {"pozycje": [], "wspolne": {}})
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda *a, **k: (_ for _ in ()).throw(qb._LLMHttpError("boom", retryable=False)))
    _enqueue(1117)
    qw.process_one(1_000_000)
    assert len(powody) == 1
    assert "wyczerpane" not in powody[0]
