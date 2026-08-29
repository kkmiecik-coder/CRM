# -*- coding: utf-8 -*-
# Testy trybu wyjscia tury: "reply" (wiadomosc do klienta) vs "note" (prywatna notatka).
# NAJWAZNIEJSZY test w tym pliku: w trybie "note" ZADNA sciezka nie moze dotknac surowej
# wysylki do klienta (_cw_agent_reply_raw) — to jedyna bariera chroniaca kanaly sprzedazy.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_reply_mode.db"))
import importlib

qb = importlib.import_module("bots.quotebot")
from bots.channel_caps import caps_for


def _zabron_wysylki(monkeypatch):
    """Atrapa surowej wysylki, ktora wywraca test przy jakimkolwiek wywolaniu."""
    def _boom(*a, **kw):
        raise AssertionError("W trybie notatki bot NIE moze wysylac wiadomosci do klienta")
    monkeypatch.setattr(qb, "_cw_agent_reply_raw", _boom)


def test_tryb_note_nie_dotyka_surowej_wysylki(monkeypatch):
    """Bariera bezpieczenstwa: tryb 'note' nigdy nie wola _cw_agent_reply_raw."""
    _zabron_wysylki(monkeypatch)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    tryb = qb._reply_mode.set("note")
    try:
        wynik = qb.cw_agent_reply(1, "Dzień dobry, potrzebuję wymiarów.", token="tok")
    finally:
        qb._reply_mode.reset(tryb)
    assert wynik is True
    assert len(notatki) == 1
    assert "Dzień dobry, potrzebuję wymiarów." in notatki[0]


def test_tryb_note_dokleja_prefiks():
    """Notatka jest oznaczona jako propozycja bota, zeby agent wiedzial co z nia zrobic."""
    assert qb._NOTE_PREFIX.strip()


def test_tryb_note_uzywa_tokenu_z_kontekstu(monkeypatch):
    """Notatka idzie tokenem bota przypisanego do inboxu (_note_token), nie zaszytym."""
    uzyte = {}
    monkeypatch.setattr(qb, "cw_note",
                        lambda conv_id, text, **kw: uzyte.update(kw) or True)
    t1 = qb._reply_mode.set("note")
    t2 = qb._note_token.set("token-woodpower-ai")
    try:
        qb.cw_agent_reply(1, "test", token="token-debusia")
    finally:
        qb._reply_mode.reset(t1); qb._note_token.reset(t2)
    assert uzyte.get("token") == "token-woodpower-ai"


def test_tryb_note_skleja_czesci_w_jedna_notatke(monkeypatch):
    """Podzial na wiadomosci (max_len OLX) zostaje widoczny, ale jako JEDNA notatka —
    inaczej agent dostaje lawine notatek zamiast jednej gotowej tresci."""
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    t1 = qb._reply_mode.set("note")
    t2 = qb._reply_caps.set(dict(caps_for("quote_olx"), max_len=40))
    try:
        qb.cw_agent_reply(1, "Zdanie pierwsze. " * 10, token="tok")
    finally:
        qb._reply_mode.reset(t1); qb._reply_caps.reset(t2)
    assert len(notatki) == 1
    assert qb._SEPARATOR_CZESCI in notatki[0]


def test_tryb_reply_bez_zmian(monkeypatch):
    """Domyslny tryb 'reply' zachowuje sie dokladnie jak dotad (zero regresji na livechacie)."""
    wyslane = []
    monkeypatch.setattr(qb, "_cw_agent_reply_raw",
                        lambda conv_id, text, **kw: wyslane.append(text) or True)
    monkeypatch.setattr(qb, "cw_note",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("nie ta droga")))
    assert qb.cw_agent_reply(1, "Dzień dobry", token="tok") is True
    assert wyslane == ["Dzień dobry"]


def test_tryb_note_blad_zapisu_zwraca_false(monkeypatch):
    """Nieudany zapis notatki musi zwrocic False — od tego zaleza flagi stanu rozmowy."""
    monkeypatch.setattr(qb, "cw_note",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("API padlo")))
    t = qb._reply_mode.set("note")
    try:
        assert qb.cw_agent_reply(1, "test", token="tok") is False
    finally:
        qb._reply_mode.reset(t)


def test_tryb_note_pomija_obraz_na_razie(monkeypatch):
    """Do czasu Task 6 obraz w trybie notatki jest pomijany, ale tekst musi dotrzec."""
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    t = qb._reply_mode.set("note")
    try:
        assert qb.cw_agent_reply(1, "podpis", image_path="/tmp/x.jpg", token="tok") is True
    finally:
        qb._reply_mode.reset(t)
    assert len(notatki) == 1
