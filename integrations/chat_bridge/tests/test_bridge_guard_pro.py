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


def _konfiguracja_olx(monkeypatch, inboxy_pro, note_persony, quote_persony,
                      olx_inbox="7"):
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", set(inboxy_pro))
    monkeypatch.setattr(bridge, "CW_OLX_INBOX", olx_inbox)
    monkeypatch.setattr(bridge, "BOT_QUOTE_NOTE_PERSONAS", set(note_persony))
    monkeypatch.setattr(bridge, "BOT_QUOTE_PERSONAS", set(quote_persony))


class TestGuardWyscigNaOlx:
    """U10 (recenzja końcowa): `BOT_PRO_INBOXES` i `BOT_QUOTE_NOTE_PERSONAS` są
    SPRZĘŻONE, a nic tego nie pilnowało. Poller OLX (`channels/olx.py`,
    `_enqueue_quote_olx`) ustępuje webhookowi WYŁĄCZNIE dzięki warunkowi
    `if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS: return`. Usunięcie `quote_olx`
    z tej listy przy migracji („OLX już nie jest w trybie notatki") budzi poller:
    kolejkuje wiersz `persona='quote_olx'` z kluczem dedupu `olx-<id>`, podczas
    gdy webhook `/agent-bot-pro` kolejkuje `persona='olx'` z gołym `mid`. Klucze
    są różne, więc `quote_seen` ich nie skojarzy, a `enqueue_quote_turn` przy
    scalaniu zachowuje personę PIERWSZEGO wiersza — o tym, który silnik obsłuży
    tę samą wiadomość (i czy odpowie PUBLICZNIE, czy notatką), decyduje wyścig."""

    def test_konflikt_przerywa_start(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"})
        with pytest.raises(SystemExit) as blad:
            bridge.sprawdz_guard_pro()
        komunikat = str(blad.value)
        assert "BOT_QUOTE_NOTE_PERSONAS" in komunikat
        assert "BOT_PRO_INBOXES" in komunikat
        assert "quote_olx" in komunikat

    def test_quote_olx_w_trybie_notatki_jest_bezpieczne(self, monkeypatch):
        # Poller ustepuje sam (`if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS: return`),
        # wiec jedynym torem jest webhook Pro — brak wyscigu.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony={"quote_olx"},
                          quote_persony={"olx"})
        bridge.sprawdz_guard_pro()

    def test_poller_wylaczony_przez_quote_personas_jest_bezpieczny(self, monkeypatch):
        # Druga bezpieczna droga: poller w ogole nie kolejkuje tur quote-bota.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"allegro"})
        bridge.sprawdz_guard_pro()

    def test_olx_poza_bot_pro_inboxes_nie_jest_konfliktem(self, monkeypatch):
        # KLUCZOWE dla starego silnika: dopoki OLX nie jest przelaczony na Pro,
        # zdjecie `quote_olx` z trybu notatki to normalna, dozwolona konfiguracja
        # legacy (bot odpowiada publicznie na OLX) — guard nie ma prawa jej ruszac.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"18"}, note_persony=set(),
                          quote_persony={"olx"})
        bridge.sprawdz_guard_pro()

    def test_brak_skonfigurowanego_inboxu_olx_nie_jest_konfliktem(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"}, olx_inbox="")
        bridge.sprawdz_guard_pro()
