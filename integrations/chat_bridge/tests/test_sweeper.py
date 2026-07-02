# -*- coding: utf-8 -*-
# Test: sweeper pending — otwiera tylko rozmowy z ostatnia wiadomoscia klienta starsza niz prog;
# parsowanie listy pending z API; wylaczenie przez SWEEP_INTERVAL<=0.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_sweep.db"))
import importlib

import config; importlib.reload(config)
cwm = importlib.import_module("core.chatwoot")
sw = importlib.import_module("sweeper"); importlib.reload(sw)


def _conv(cid=1, last_type=0, age=9999, now=100000):
    return {"id": cid, "inbox_id": 12, "last_msg_type": last_type, "last_msg_ts": now - age}


def _mock(monkeypatch, convs):
    calls = {"handoff": [], "note": []}
    monkeypatch.setattr(sw, "cw_pending_conversations", lambda: convs)
    monkeypatch.setattr(sw, "cw_bot_handoff", lambda cid, token=None: calls["handoff"].append((cid, token)) or True)
    monkeypatch.setattr(sw, "cw_note", lambda cid, t: calls["note"].append(cid))
    return calls


def test_otwiera_stara_rozmowe_z_ostatnia_od_klienta(monkeypatch):
    """Ostatnia wiadomosc incoming, starsza niz prog -> toggle open tokenem ADMINA + notatka."""
    calls = _mock(monkeypatch, [_conv(cid=7, last_type=0, age=config.SWEEP_PENDING_AGE + 1)])

    n = sw.sweep_once(100000)

    assert n == 1
    assert calls["handoff"] == [(7, config.CW_TOKEN)]
    assert calls["note"] == [7]


def test_pomija_gdy_ostatnie_slowo_bota(monkeypatch):
    """Ostatnia wiadomosc outgoing (bot/agent) -> rozmowa czeka na klienta, nie ruszamy."""
    calls = _mock(monkeypatch, [_conv(last_type=1, age=99999), _conv(last_type="outgoing", age=99999)])

    assert sw.sweep_once(100000) == 0
    assert calls["handoff"] == []


def test_pomija_mlodsza_niz_prog(monkeypatch):
    """Incoming mlodsza niz SWEEP_PENDING_AGE -> jeszcze okno retry bota."""
    calls = _mock(monkeypatch, [_conv(age=config.SWEEP_PENDING_AGE - 5)])

    assert sw.sweep_once(100000) == 0
    assert calls["handoff"] == []


def test_nieudany_toggle_bez_notatki_i_bez_zliczenia(monkeypatch):
    """Porazka toggle -> brak notatki, rozmowa niezaliczona (sprobujemy w kolejnym przejsciu)."""
    calls = _mock(monkeypatch, [_conv(cid=9, age=99999)])
    monkeypatch.setattr(sw, "cw_bot_handoff", lambda cid, token=None: False)

    assert sw.sweep_once(100000) == 0
    assert calls["note"] == []


def test_sweeper_wylaczony_przez_interval_zero(monkeypatch):
    """SWEEP_INTERVAL<=0 -> sweeper() wraca natychmiast (petla nie startuje)."""
    monkeypatch.setattr(sw, "SWEEP_INTERVAL", 0)
    sw.sweeper()  # brak zawieszenia = sukces


class _Resp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return {"data": {"payload": self._payload}}


def test_cw_pending_conversations_parsuje_i_stronicuje(monkeypatch):
    """Parsowanie last_non_activity_message + stop na niepelnej stronie."""
    pages = {
        1: [{"id": 1, "inbox_id": 3, "timestamp": 50,
             "last_non_activity_message": {"message_type": 0, "created_at": 111}}],
    }
    def fake_cw(method, path, payload=None):
        page = int(path.split("page=")[1])
        return _Resp(pages.get(page, []))
    monkeypatch.setattr(cwm, "cw", fake_cw)

    out = cwm.cw_pending_conversations()

    assert out == [{"id": 1, "inbox_id": 3, "last_msg_type": 0, "last_msg_ts": 111}]


def test_cw_pending_conversations_fallback_timestamp_i_blad(monkeypatch):
    """Brak last_non_activity_message -> last_msg_ts z timestamp; wyjatek API -> []."""
    def fake_cw(method, path, payload=None):
        return _Resp([{"id": 2, "inbox_id": 3, "timestamp": 77}])
    monkeypatch.setattr(cwm, "cw", fake_cw)
    out = cwm.cw_pending_conversations()
    assert out[0]["last_msg_ts"] == 77 and out[0]["last_msg_type"] is None

    def boom(*a, **k):
        raise RuntimeError("siec")
    monkeypatch.setattr(cwm, "cw", boom)
    assert cwm.cw_pending_conversations() == []
