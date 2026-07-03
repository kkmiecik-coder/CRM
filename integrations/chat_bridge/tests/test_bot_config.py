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
    assert cfg.BOT_MAX_TOKENS == 2000
    assert cfg.BOT_REASONING_EFFORT == "low"
    assert cfg.OPENAI_API_BASE == "https://api.openai.com/v1"
    assert cfg.BOT_LIVE_MAX_TURNS == 30
