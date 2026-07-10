# -*- coding: utf-8 -*-
# Test: config importuje sie bez realnych sekretow i ma sensowne domyslne wartosci.
import importlib
config = importlib.import_module("config")


def test_domyslne_wartosci():
    assert config.LLM_PROVIDER in ("openai", "anthropic")
    assert config.PS_PREFIX == "ps_"
    assert config.PS_SHOP_ID == 1
    assert config.PS_LANG_IDS == [1, 2]
    assert config.PS_AUTHOR_ID == 23
    assert config.LINK_CLASS == "kontakt-link-descr"
    assert isinstance(config.MAX_TOKENS, int) and config.MAX_TOKENS > 0
    assert isinstance(config.TOPIC_SEEDS, list)


def test_ps_lang_ids_nienumeryczne_nie_wywala_importu(monkeypatch):
    # nienumeryczny BLOG_PS_LANG_IDS nie moze wywrocic importu config -> fallback [1,2]
    monkeypatch.setenv("BLOG_PS_LANG_IDS", "pl,en")
    import importlib, config as c
    importlib.reload(c)
    assert c.PS_LANG_IDS == [1, 2]
    monkeypatch.delenv("BLOG_PS_LANG_IDS", raising=False)
    importlib.reload(c)
