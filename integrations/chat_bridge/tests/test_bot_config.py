# -*- coding: utf-8 -*-
# Test: config wystawia domyslne wartosci dla botow AI (bez ustawionych env).
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

cfg = importlib.import_module("config")


def test_domyslne_wartosci_botow():
    assert cfg.BOT_CHAT_MODEL == "gpt-5.4-nano"
    assert cfg.BOT_EMBEDDING_MODEL == "text-embedding-3-small"
    assert cfg.BOT_RETRIEVAL_K == 5
    assert cfg.BOT_HISTORY_LIMIT == 12
    assert cfg.BOT_MAX_ATTEMPTS == 3
    assert cfg.BOT_MAX_TOKENS == 4000   # podniesione w FAZIE 0 zad.4 (PL-04)
    assert cfg.BOT_REASONING_EFFORT == "low"
    assert cfg.OPENAI_API_BASE == "https://api.openai.com/v1"
    assert cfg.BOT_LIVE_MAX_TURNS == 30
    assert cfg.BOT_BUSINESS_HOURS == "08:00-16:00"
    assert cfg.BOT_BACKOFF_TIERS == [30, 120, 300]


def test_backoff_tiers_pusty_env_wraca_do_domyslnych(monkeypatch):
    """Regresja code review Task 7: BOT_BACKOFF_TIERS='' (np. zla zmienna w deployu) nie moze
    wywalic importu configu (a przez to calego mostka) — pusty env ma dac te sama domyslna liste."""
    monkeypatch.setenv("BOT_BACKOFF_TIERS", "")
    importlib.reload(cfg)
    try:
        assert cfg.BOT_BACKOFF_TIERS == [30, 120, 300]
    finally:
        monkeypatch.delenv("BOT_BACKOFF_TIERS", raising=False)
        importlib.reload(cfg)


def test_note_personas_domyslnie_olx_i_allegro():
    """Domyslnie notatki pisza OLX i Allegro; persona 'quote' (livechat) NIE podlega trybowi."""
    importlib.reload(cfg)
    assert cfg.BOT_QUOTE_NOTE_PERSONAS == {"quote_olx", "quote_allegro"}
    assert "quote" not in cfg.BOT_QUOTE_NOTE_PERSONAS


def test_note_personas_z_env(monkeypatch):
    """Kill-switch: lista z env nadpisuje domyslna (zdjecie persony = powrot na stary tor)."""
    monkeypatch.setenv("BOT_QUOTE_NOTE_PERSONAS", "quote_allegro")
    importlib.reload(cfg)
    assert cfg.BOT_QUOTE_NOTE_PERSONAS == {"quote_allegro"}
    monkeypatch.delenv("BOT_QUOTE_NOTE_PERSONAS")
    importlib.reload(cfg)


def test_note_personas_pusta_wartosc_nie_wywala_importu(monkeypatch):
    """Pusty BOT_QUOTE_NOTE_PERSONAS='' (zla zmienna w deployu) = zaden kanal nie pisze
    notatek, ale mostek MUSI wstac (jak BOT_BACKOFF_TIERS)."""
    monkeypatch.setenv("BOT_QUOTE_NOTE_PERSONAS", "")
    importlib.reload(cfg)
    assert cfg.BOT_QUOTE_NOTE_PERSONAS == set()
    monkeypatch.delenv("BOT_QUOTE_NOTE_PERSONAS")
    importlib.reload(cfg)
