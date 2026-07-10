# -*- coding: utf-8 -*-
# Test: godziny pracy konsultantow (LS-10) — komunikat handoffu poza godzinami.
import os, tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_hours.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def test_w_godzinach_pracy_w_srodku_dnia():
    dt = datetime(2026, 7, 9, 10, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert qb._w_godzinach_pracy(dt) is True


def test_poza_godzinami_pracy_wieczorem():
    dt = datetime(2026, 7, 9, 20, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert qb._w_godzinach_pracy(dt) is False


def test_dokladnie_na_granicy_startu_jest_w_godzinach():
    dt = datetime(2026, 7, 9, 8, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert qb._w_godzinach_pracy(dt) is True


def test_dokladnie_na_koncu_jest_juz_poza():
    dt = datetime(2026, 7, 9, 16, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    assert qb._w_godzinach_pracy(dt) is False


def test_zly_format_konfiguracji_nie_wywraca_i_zwraca_true(monkeypatch):
    monkeypatch.setattr(qb, "BOT_BUSINESS_HOURS", "cokolwiek-zlego")
    assert qb._w_godzinach_pracy() is True


def test_handoff_poza_godzinami_zmienia_closing(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb, "_w_godzinach_pracy", lambda now=None: False)
    qb._do_handoff(999, "test", {"pozycje": [], "wspolne": {}})
    assert any("godzinach" in r for r in replies)


def test_handoff_w_godzinach_zwykly_closing(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb, "_w_godzinach_pracy", lambda now=None: True)
    qb._do_handoff(1000, "test", {"pozycje": [], "wspolne": {}})
    assert replies[-1] == qb.CLOSING_MSG


def test_handoff_z_wlasnym_closing_nie_jest_nadpisywany_poza_godzinami(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb, "_w_godzinach_pracy", lambda now=None: False)
    qb._do_handoff(1001, "limit", {"pozycje": [], "wspolne": {}}, closing=qb.LIMIT_MSG)
    assert replies[-1] == qb.LIMIT_MSG
