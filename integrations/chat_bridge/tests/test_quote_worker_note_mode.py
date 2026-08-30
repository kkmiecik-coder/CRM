# -*- coding: utf-8 -*-
# Sciezki AWARYJNE workera w trybie notatki. Worker wysyla do klienta poza wrapperem
# quotebota, wiec bariera trybu musi byc ustawiona takze tutaj — inaczej przeprosiny
# i komunikat o obciazeniu trafilyby do kupujacego na OLX/Allegro.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_worker_note.db"))
import importlib

qb = importlib.import_module("bots.quotebot")


def test_handoff_z_przeprosinami_w_trybie_notatki_nie_pisze_do_klienta(monkeypatch):
    """Awaria bota na OLX = notatka dla agenta, NIE przeprosiny dla kupujacego."""
    def _boom(*a, **kw):
        raise AssertionError("przeprosiny nie moga trafic do klienta w trybie notatki")
    monkeypatch.setattr(qb, "_cw_agent_reply_raw", _boom)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, token=None: True)
    monkeypatch.setattr(qb, "_load_dane", lambda conv_id: {"pozycje": [], "wspolne": {}})
    qb.handoff_with_apology(1, reason="blad techniczny", persona="quote_olx")
    assert notatki, "agent musi dostac notatke o awarii"


def test_handoff_z_przeprosinami_na_livechacie_bez_zmian(monkeypatch):
    """Na livechacie klient nadal dostaje przeprosiny — zero regresji."""
    wyslane = []
    monkeypatch.setattr(qb, "_cw_agent_reply_raw",
                        lambda conv_id, text, **kw: wyslane.append(text) or True)
    monkeypatch.setattr(qb, "cw_note", lambda *a, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, token=None: True)
    monkeypatch.setattr(qb, "_load_dane", lambda conv_id: {"pozycje": [], "wspolne": {}})
    qb.handoff_with_apology(1, reason="blad techniczny", persona="quote")
    assert wyslane, "livechat nadal informuje klienta"


def test_komunikat_obciazenia_w_trybie_notatki_idzie_do_notatki(monkeypatch):
    """Circuit-breaker: 'Mamy chwilowe obciazenie' to komunikat DLA KLIENTA — na OLX/Allegro
    ma zostac notatka, bo klient nie wie o istnieniu bota."""
    def _boom(*a, **kw):
        raise AssertionError("komunikat o obciazeniu nie moze trafic do klienta")
    monkeypatch.setattr(qb, "_cw_agent_reply_raw", _boom)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    qb.komunikat_obciazenia(1, persona="quote_allegro")
    assert len(notatki) == 1
