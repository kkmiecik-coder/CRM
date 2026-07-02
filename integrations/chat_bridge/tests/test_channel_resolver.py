# -*- coding: utf-8 -*-
# Test resolvera persony: monkeypatch cw_inboxes, zero polaczen sieciowych.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")

import importlib

cr = importlib.import_module("bots.channel_resolver")

# Katalog inboxow uzywany we wszystkich testach (odpowiada faktycznym inboxom CW)
FAKE_CATALOG = [
    {"id": 3,  "name": "OLX",                    "channel_type": "Channel::Api"},
    {"id": 4,  "name": "Allegro - Wiadomosci",    "channel_type": "Channel::Api"},
    {"id": 6,  "name": "Allegro - Dyskusje",      "channel_type": "Channel::Api"},
    {"id": 5,  "name": "Wsparcie WoodPower",       "channel_type": "Channel::WebWidget"},
    {"id": 7,  "name": "kontakt@woodpower.pl",     "channel_type": "Channel::Email"},
    {"id": 8,  "name": "info@woodpower.pl",        "channel_type": "Channel::Email"},
    {"id": 10, "name": "Cokolwiek Api",            "channel_type": "Channel::Api"},
    # Inbox o nazwie zawierajacej oba slowa — "allegro" musi wygrywac
    {"id": 11, "name": "allegro olx promocje",     "channel_type": "Channel::Api"},
]

_call_count = 0


def _fake_cw_inboxes():
    global _call_count
    _call_count += 1
    return FAKE_CATALOG


def setup_function(_):
    """Resetuj cache i licznik wywolan przed kazdym testem."""
    global _call_count
    _call_count = 0
    cr._CACHE.clear()
    cr._CACHE_TS = 0.0


# ---------------------------------------------------------------------------
# Testy podstawowych typow kanalow
# ---------------------------------------------------------------------------

def test_email_zwraca_mail(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(7) == "mail"


def test_email_drugi_inbox_tez_mail(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(8) == "mail"


def test_api_olx_zwraca_olx(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(3) == "olx"


def test_api_allegro_wiadomosci_zwraca_allegro(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(4) == "allegro"


def test_api_allegro_dyskusje_zwraca_allegro(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(6) == "allegro"


def test_api_bez_olx_allegro_zwraca_none(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(10) is None


def test_webwidget_zwraca_livechat(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    assert cr.persona_for(5) == "livechat"


def test_nieznane_id_zwraca_none_po_force_refresh(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    # id 999 nie istnieje w katalogu — resolver musi probic force-refresh i zwrocic None
    assert cr.persona_for(999) is None


# ---------------------------------------------------------------------------
# Test pierwszenstwa "allegro" przed "olx" (restrykcyjna persona wygrywa)
# ---------------------------------------------------------------------------

def test_allegro_ma_pierwszenstwo_przed_olx(monkeypatch):
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    # inbox 11 ma nazwe "allegro olx promocje" — ma zwrocic "allegro", nie "olx"
    assert cr.persona_for(11) == "allegro"


# ---------------------------------------------------------------------------
# Test cache: drugie wywolanie w TTL NIE woluje cw_inboxes ponownie
# ---------------------------------------------------------------------------

def test_cache_drugie_wywolanie_bez_sieci(monkeypatch):
    global _call_count
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    # Pierwsze wywolanie — inicjalizuje cache
    cr.persona_for(3)
    wywolan_po_pierwszym = _call_count
    # Drugie wywolanie — powinno trafic w cache, bez kolejnego wywolania cw_inboxes
    cr.persona_for(4)
    assert _call_count == wywolan_po_pierwszym, (
        "cw_inboxes wywolane %d razy zamiast %d (brak cache w TTL)"
        % (_call_count, wywolan_po_pierwszym)
    )


def test_nieznane_id_wywoluje_force_refresh(monkeypatch):
    """Nieznane id musi wywolac cw_inboxes dwukrotnie: raz normalnie, raz force."""
    global _call_count
    monkeypatch.setattr(cr, "cw_inboxes", _fake_cw_inboxes)
    cr.persona_for(999)
    # Oczekujemy dokladnie 2 wywolan: pierwsze normalne get_catalog(), drugie force=True
    assert _call_count == 2, (
        "Oczekiwano 2 wywolan cw_inboxes dla nieznanego id, got %d" % _call_count
    )
