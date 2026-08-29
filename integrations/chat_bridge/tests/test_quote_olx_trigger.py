# -*- coding: utf-8 -*-
# Testy triggera OLX (T2-trigger): wyzwalanie tury quote-bota Z MOSTU (nie z webhooka Chatwoota),
# gate configu BOT_QUOTE_PERSONAS, dedup po OLX msg id, tag persona=quote_olx w quote_queue,
# oraz caps-context (OLX_CAPS na czas tury, przywracane po niej) i przekazanie persony przez worker.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_olx_trig.db"))
import importlib
import pytest
import config
db_mod = importlib.import_module("core.db")
olx = importlib.import_module("channels.olx")
qb = importlib.import_module("bots.quotebot")
qw = importlib.import_module("quote_worker")
from bots.channel_caps import OLX_CAPS, DEFAULT_CAPS


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue"); c.execute("DELETE FROM quote_seen")
    c.execute("DELETE FROM quote_olx_conv")
    c.commit(); c.close()


@pytest.fixture(autouse=True)
def _circuit_reset():
    from core.db import meta_set
    meta_set(qw._META_CIRCUIT_UNTIL, 0); meta_set(qw._META_CIRCUIT_FAILS, 0)
    yield
    meta_set(qw._META_CIRCUIT_UNTIL, 0); meta_set(qw._META_CIRCUIT_FAILS, 0)


def _rows():
    c = db_mod.db()
    r = c.execute("SELECT conv_id, message_id, content, persona FROM quote_queue ORDER BY id").fetchall()
    c.close()
    return [dict(x) for x in r]


# --- gate configu + tag persona ---

def test_enqueue_gdy_olx_wlaczony(monkeypatch):
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"livechat", "olx"})
    # stary tryb (bramka trybu notatki wylaczona) - test poza zakresem routingu OLX/webhook.
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", set())
    olx._mark_quote_olx_eligible(55)   # swieza rozmowa (utworzona po go-live)
    olx._enqueue_quote_olx(55, 9001, "Wycena blatu dąb 200x60", [])
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["conv_id"] == 55
    assert rows[0]["persona"] == "quote_olx"
    assert rows[0]["message_id"] == "olx-9001"   # dedup key prefiksowany kanalem
    assert rows[0]["content"] == "Wycena blatu dąb 200x60"


def test_nie_enqueue_gdy_olx_wylaczony(monkeypatch):
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"livechat"})
    olx._mark_quote_olx_eligible(55)
    olx._enqueue_quote_olx(55, 9002, "Wycena blatu", [])
    assert _rows() == []


# --- Runda poprawek: podwojne zakolejkowanie tej samej wiadomosci OLX (poller vs webhook) ---
# Gdy persona 'quote_olx' jest w BOT_QUOTE_NOTE_PERSONAS (tryb notatki), tury dla OLX kolejkuje
# juz webhook /agent-bot (Chatwoot wola go po kazdej wiadomosci dostarczonej przez cw_incoming).
# Poller i webhook uzywaja INNYCH kluczy dedupu w quote_seen ("olx-<id>" vs surowy mid Chatwoota),
# wiec bez bramki nizej jedna wiadomosc klienta dalaby DWIE tury (dwa leady w CRM, dwie notatki).

def test_enqueue_gdy_persona_w_note_personas_nie_kolejkuje(monkeypatch):
    """Bramka trybu notatki: poller ma ustapic samoczynnie, bez kolejkowania. Test odroznia
    'nie zakolejkowano bo bramka' od 'nie zakolejkowano bo cos rzucilo' — _enqueue_quote_olx ma
    szerokie `except`, ktore polyka wyjatki, wiec samo `_rows() == []` mogloby przejsc z
    niewlasciwego powodu. Podmieniamy `log`, zeby upewnic sie, ze funkcja wraca CICHO (bez
    logu bledu z `except`, bez logu sukcesu z kolejkowania) — czyli dzieki bramce na samym
    poczatku, a nie dzieki polkanietemu wyjatkowi gdzies w srodku."""
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", {"quote_olx"})
    wywolania_log = []
    monkeypatch.setattr(olx, "log", lambda *a, **k: wywolania_log.append(a))
    olx._mark_quote_olx_eligible(55)
    olx._enqueue_quote_olx(55, 9005, "Wycena blatu dab", [])
    assert _rows() == [], "tryb notatki: poller nie ma nic dodawac do quote_queue"
    assert wywolania_log == [], "brak logu = wczesny return przez bramke, nie polkniety wyjatek"


def test_enqueue_gdy_persona_nie_w_note_personas_kolejkuje_jak_dotad(monkeypatch):
    """Gdy 'quote_olx' NIE jest w BOT_QUOTE_NOTE_PERSONAS (tryb notatki wylaczony/kill-switch),
    poller ma kolejkowac dokladnie jak przed fixem — upewnia sie, ze bramka nie wylaczyla
    pollera na zawsze, tylko ustepuje webhookowi wylacznie w trybie notatki."""
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", set())
    olx._mark_quote_olx_eligible(56)
    olx._enqueue_quote_olx(56, 9006, "Wycena parapetu", [])
    rows = _rows()
    assert len(rows) == 1, "bez bramki notatki poller ma kolejkowac jak dotad"
    assert rows[0]["conv_id"] == 56
    assert rows[0]["persona"] == "quote_olx"


def test_dedup_po_olx_msg_id(monkeypatch):
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", set())  # stary tryb, poza zakresem gate
    olx._mark_quote_olx_eligible(55)
    olx._enqueue_quote_olx(55, 9003, "Wycena", [])
    olx._enqueue_quote_olx(55, 9003, "Wycena (powtorka)", [])
    assert len(_rows()) == 1


def test_pusta_tresc_bez_zalacznika_nie_enqueue(monkeypatch):
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    olx._mark_quote_olx_eligible(55)
    olx._enqueue_quote_olx(55, 9004, "   ", [])
    assert _rows() == []


# --- FAZA 3a: tylko swieze rozmowy (utworzone po go-live) ---

def test_coalesce_dwie_wiadomosci_olx_jedna_tura(monkeypatch):
    # Okno ciszy dziala tez dla OLX: dwie wiadomosci tej samej rozmowy -> jeden rekord.
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", set())  # stary tryb, poza zakresem gate
    olx._mark_quote_olx_eligible(55)
    olx._enqueue_quote_olx(55, 8001, "poproszę wycenę", [])
    olx._enqueue_quote_olx(55, 8002, "blat dębowy", [])
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["content"] == "poproszę wycenę\nblat dębowy"
    assert rows[0]["persona"] == "quote_olx"


def test_worker_dostaje_scalona_tresc(monkeypatch):
    # Fix #2: po scaleniu serii worker przetwarza POLACZONA tresc (re-odczyt po claimie), nie 1. wiadomosc.
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    monkeypatch.setattr(olx, "BOT_QUOTE_NOTE_PERSONAS", set())  # stary tryb, poza zakresem gate
    olx._mark_quote_olx_eligible(70)
    olx._enqueue_quote_olx(70, 7001, "poproszę wycenę", [])
    olx._enqueue_quote_olx(70, 7002, "blat dębowy 200x60", [])
    zebrane = {}
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda conv_id, inbox_id, mid, content, attachments=None, persona="quote":
                        zebrane.update(content=content, persona=persona))
    assert qw.process_one(9_999_999_999) is True
    assert zebrane["content"] == "poproszę wycenę\nblat dębowy 200x60"
    assert zebrane["persona"] == "quote_olx"


def test_nieoznaczona_rozmowa_nie_enqueue(monkeypatch):
    # Rozmowa sprzed go-live (nieoznaczona) -> bot NIE wchodzi, nawet przy nowej wiadomosci.
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    olx._enqueue_quote_olx(999, 9100, "Nowa wiadomosc w starym watku", [])
    assert _rows() == []


def test_oznaczona_rozmowa_jest_eligible():
    assert olx._quote_olx_conv_eligible(555) is False
    olx._mark_quote_olx_eligible(555)
    assert olx._quote_olx_conv_eligible(555) is True


def test_mark_idempotentny():
    olx._mark_quote_olx_eligible(556)
    olx._mark_quote_olx_eligible(556)   # brak wyjatku przy powtorce
    assert olx._quote_olx_conv_eligible(556) is True


def test_should_mark_eligible_tylko_nowy_watek(monkeypatch):
    # Review #1: oznaczamy jako swieza TYLKO rozmowe z watku nigdy niewidzianego (st is None).
    # Self-heal (odtworzenie conv ZNANEGO watku sprzed go-live) NIE moze oznaczyc -> bot nie
    # wskoczy w stara rozmowe.
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"olx"})
    assert olx._should_mark_eligible(None) is True
    assert olx._should_mark_eligible({"conv_id": 5, "total_count": 3}) is False


def test_should_mark_eligible_gdy_olx_wylaczony(monkeypatch):
    monkeypatch.setattr(olx, "BOT_QUOTE_PERSONAS", {"livechat"})
    assert olx._should_mark_eligible(None) is False


# --- caps-context tury: OLX na czas tury, przywracane po (rekomendacja z review) ---

def test_run_quote_turn_ustawia_caps_olx_i_przywraca(monkeypatch):
    zebrane = {}
    def _fake_inner(conv_id, inbox_id, message_id, content, attachments=None, persona="quote"):
        zebrane["caps"] = qb._reply_caps.get()
        zebrane["persona"] = persona
    monkeypatch.setattr(qb, "_run_quote_turn_inner", _fake_inner)
    qb.run_quote_turn(1, 18, "m1", "hej", persona="quote_olx")
    assert zebrane["caps"] == OLX_CAPS
    assert zebrane["persona"] == "quote_olx"
    # po turze caps wracaja do domyslnych (nie wyciekaja na kolejna, livechatowa ture)
    assert qb._reply_caps.get() == DEFAULT_CAPS


def test_run_quote_turn_domyslnie_quote_i_default_caps(monkeypatch):
    zebrane = {}
    def _fake_inner(conv_id, inbox_id, message_id, content, attachments=None, persona="quote"):
        zebrane["caps"] = qb._reply_caps.get()
        zebrane["persona"] = persona
    monkeypatch.setattr(qb, "_run_quote_turn_inner", _fake_inner)
    qb.run_quote_turn(1, 5, "m1", "hej")   # bez persony -> livechat/quote
    assert zebrane["persona"] == "quote"
    assert zebrane["caps"] == DEFAULT_CAPS


def test_caps_przywracane_takze_gdy_tura_rzuca(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(qb, "_run_quote_turn_inner", _boom)
    with pytest.raises(RuntimeError):
        qb.run_quote_turn(1, 18, "m1", "hej", persona="quote_olx")
    assert qb._reply_caps.get() == DEFAULT_CAPS   # finally przywrocilo caps mimo wyjatku


# --- worker przekazuje persone z kolejki ---

def test_process_one_przekazuje_persone_z_kolejki(monkeypatch):
    c = db_mod.db()
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
              "VALUES(?,?,?,?,?,0)", (77, 18, "olx-1", "tak", "quote_olx"))
    c.commit(); c.close()
    zebrane = {}
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda conv_id, inbox_id, mid, content, attachments=None, persona="quote":
                        zebrane.update(persona=persona, conv=conv_id))
    assert qw.process_one(9_999_999_999) is True
    assert zebrane["persona"] == "quote_olx"
    assert zebrane["conv"] == 77


def test_process_one_domyslna_persona_gdy_null(monkeypatch):
    c = db_mod.db()
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, next_at) "
              "VALUES(?,?,?,?,0)", (78, 5, "m9", "tak"))
    c.commit(); c.close()
    zebrane = {}
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda conv_id, inbox_id, mid, content, attachments=None, persona="quote":
                        zebrane.update(persona=persona))
    assert qw.process_one(9_999_999_999) is True
    assert zebrane["persona"] == "quote"
