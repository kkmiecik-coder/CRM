# -*- coding: utf-8 -*-
"""
Guard startowy Task 7: brak BOT_PRO_AGENT_WEBHOOK_TOKEN przy niepustym BOT_PRO_INBOXES
oznacza, ze weryfikacja tokenu w webhooks.py (`if TOKEN and ...`) jest pomijana i
webhook /agent-bot-pro stoi otworem. `bridge.sprawdz_guard_pro()` ma przerwac start
procesu w tej sytuacji, zamiast pozwolic mu wystartowac bez ochrony.
"""
import pytest

import bridge


def test_brak_tokenu_i_niepuste_inboxy_przerywa_start(monkeypatch):
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", {"5"})
    with pytest.raises(SystemExit):
        bridge.sprawdz_guard_pro()


def test_pusty_token_string_tez_przerywa_start(monkeypatch):
    # "" jest falsy tak samo jak None - literowka w bridge.env (pusta wartosc zamiast
    # braku zmiennej) nie moze po cichu ominac guarda.
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "")
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", {"5"})
    with pytest.raises(SystemExit):
        bridge.sprawdz_guard_pro()


def test_pusty_bot_pro_inboxes_nie_wymaga_tokenu(monkeypatch):
    # Bot wylaczony wszedzie (kill-switch) - brak tokenu jest wtedy nieszkodliwy,
    # bo i tak nic sie nie kolejkuje (webhooks._process_pro filtruje po inboxie).
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", set())
    bridge.sprawdz_guard_pro()   # nie rzuca


def test_token_ustawiony_pozwala_startowac_mimo_inboxow(monkeypatch):
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", {"5", "18"})
    bridge.sprawdz_guard_pro()   # nie rzuca
