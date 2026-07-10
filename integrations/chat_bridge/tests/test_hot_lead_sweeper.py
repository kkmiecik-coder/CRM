# -*- coding: utf-8 -*-
# Test: sweeper "goracy lead" — rozmowa juz oddana agentowi (status open) po cenie bota
# (priced=1), ale klient milczy dluzej niz prog -> notatka priorytetowa (LS-04).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_hotlead.db"))
import importlib

import config; importlib.reload(config)
cwm = importlib.import_module("core.chatwoot")
db_mod = importlib.import_module("core.db"); db_mod.init_db()
quotebot = importlib.import_module("bots.quotebot"); importlib.reload(quotebot)
hls = importlib.import_module("hot_lead_sweeper"); importlib.reload(hls)


class _Resp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return {"data": {"payload": self._payload}}


def test_cw_open_conversations_parsuje_status_open(monkeypatch):
    def fake_cw(method, path, payload=None):
        assert "status=open" in path
        return _Resp([{"id": 5, "inbox_id": 18, "last_non_activity_message":
                       {"message_type": 1, "created_at": 100}, "timestamp": 100}])
    monkeypatch.setattr(cwm, "cw", fake_cw)
    out = cwm.cw_open_conversations()
    assert out == [{"id": 5, "inbox_id": 18, "last_msg_type": 1, "last_msg_ts": 100}]


def _conv(cid=1, last_type="outgoing", age=999999, now=1_000_000):
    return {"id": cid, "inbox_id": 18, "last_msg_type": last_type, "last_msg_ts": now - age}


def test_otwiera_rozmowe_z_cena_i_cisza_klienta(monkeypatch):
    quotebot._set_priced(77, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=77)])
    notes = []
    monkeypatch.setattr(hls, "cw_note", lambda cid, t, **kw: notes.append((cid, t)) or True)
    assert hls.hot_sweep_once(1_000_000) == 1
    assert notes and notes[0][0] == 77


def test_pomija_rozmowe_bez_ceny(monkeypatch):
    quotebot._set_priced(78, False)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=78)])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_pomija_gdy_ostatnie_slowo_klienta(monkeypatch):
    # last_msg_type incoming = klient napisal cos PO cenie -> bot juz odpowie normalnie, nie sweeper
    quotebot._set_priced(79, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=79, last_type="incoming")])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_pomija_mlodsza_niz_prog(monkeypatch):
    quotebot._set_priced(80, True)
    monkeypatch.setattr(hls, "cw_open_conversations", lambda: [_conv(cid=80, age=10)])
    monkeypatch.setattr(hls, "cw_note",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno wolac")))
    assert hls.hot_sweep_once(1_000_000) == 0


def test_sweeper_wylaczony_przez_interval_zero(monkeypatch):
    monkeypatch.setattr(hls, "HOT_LEAD_SWEEP_INTERVAL", 0)
    hls.hot_lead_sweeper()  # brak zawieszenia = sukces
