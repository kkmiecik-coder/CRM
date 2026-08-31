# -*- coding: utf-8 -*-
"""
Guard startowy Debusia Pro (`bridge.sprawdz_guard_pro`).

Dwie kontrole: brak BOT_PRO_AGENT_WEBHOOK_TOKEN przy niepustym BOT_PRO_INBOXES
(weryfikacja tokenu w webhooks.py jest warunkowa — `if TOKEN and ...` — wiec
webhook /agent-bot-pro stalby otworem) oraz konflikt konfiguracji OLX (U10,
patrz TestGuardWyscigNaOlx).

Reakcja na blad to WYLACZENIE Pro, nie ubicie procesu (U14b, patrz
TestGuardNieUbijaKontenera) — w tym samym kontenerze mieszka stary silnik
obslugujacy zywy ruch.
"""
import pytest

import bridge


def _przechwyc_logi(monkeypatch):
    logi = []
    monkeypatch.setattr(bridge, "log", lambda *czesci: logi.append(" ".join(str(c) for c in czesci)))
    return logi


def test_brak_tokenu_i_niepuste_inboxy_wylacza_pro(monkeypatch):
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    inboxy = {"5"}
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", inboxy)
    logi = _przechwyc_logi(monkeypatch)

    assert bridge.sprawdz_guard_pro() is False
    assert inboxy == set()   # Pro wylaczone, stary silnik dziala dalej
    assert any("BOT_PRO_AGENT_WEBHOOK_TOKEN" in wpis for wpis in logi)


def test_pusty_token_string_tez_wylacza_pro(monkeypatch):
    # "" jest falsy tak samo jak None - literowka w bridge.env (pusta wartosc zamiast
    # braku zmiennej) nie moze po cichu ominac guarda.
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "")
    inboxy = {"5"}
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", inboxy)
    _przechwyc_logi(monkeypatch)

    assert bridge.sprawdz_guard_pro() is False
    assert inboxy == set()


def test_pusty_bot_pro_inboxes_nie_wymaga_tokenu(monkeypatch):
    # Bot wylaczony wszedzie (kill-switch) - brak tokenu jest wtedy nieszkodliwy,
    # bo i tak nic sie nie kolejkuje (webhooks._process_pro filtruje po inboxie).
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", set())
    assert bridge.sprawdz_guard_pro() is True


def test_token_ustawiony_pozwala_startowac_mimo_inboxow(monkeypatch):
    monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
    inboxy = {"5", "18"}
    monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", inboxy)
    assert bridge.sprawdz_guard_pro() is True
    assert inboxy == {"5", "18"}   # nietkniete


class TestGuardNieUbijaKontenera:
    """U14b (recenzja końcowa): guard był `SystemExit`, czyli wadliwa konfiguracja
    DOTYCZĄCA WYŁĄCZNIE Dębusia Pro zdejmowała CAŁY kontener mostka — razem ze
    starym silnikiem, który obsługuje dziś żywy ruch na livechacie, OLX i Allegro,
    oraz z pollerami kanałów, sweeperami i indeksem bazy wiedzy. Ma wyłączać Pro
    i głośno logować, nie zabijać procesu."""

    def test_zla_konfiguracja_nie_rzuca_systemexit(self, monkeypatch):
        monkeypatch.setattr(bridge, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(bridge, "BOT_PRO_INBOXES", {"5"})
        _przechwyc_logi(monkeypatch)
        bridge.sprawdz_guard_pro()   # brak wyjatku == kontener wstaje

    def test_konflikt_olx_tez_tylko_wylacza(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"})
        logi = _przechwyc_logi(monkeypatch)

        assert bridge.sprawdz_guard_pro() is False
        assert bridge.BOT_PRO_INBOXES == set()
        assert any("quote_olx" in wpis for wpis in logi)

    def test_wyczyszczenie_listy_wylacza_pro_w_calym_mostku(self):
        """Dowód, że „wyłączenie Pro" naprawdę działa: `BOT_PRO_INBOXES` to JEDEN
        obiekt (zbiór) współdzielony przez wszystkie moduły, które o Pro decydują —
        wyczyszczenie go w `bridge` jest tym samym kill-switchem, co pusta zmienna
        środowiskowa. Gdyby któryś moduł trzymał KOPIĘ, guard wyłączałby Pro tylko
        na papierze.

        Sprawdzane w OSOBNYM PROCESIE, na czystym imporcie: kilka innych plików
        testowych robi `importlib.reload(config)` / `reload(webhooks)`, co rebinduje
        te nazwy do NOWYCH zbiorów. To artefakt harnessu (produkcja niczego nie
        przeładowuje), ale w jednym procesie pytest zamazywałby dokładnie tę
        własność, którą ten test ma udowodnić."""
        import os
        import subprocess
        import sys

        kod = (
            "import config, bridge, webhooks, quote_worker, pro_watchdog\n"
            "assert bridge.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert webhooks.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert quote_worker.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert pro_watchdog.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "config.BOT_PRO_INBOXES.add('7')\n"
            "assert quote_worker._jest_pro_inbox('7') is True\n"
            "bridge.BOT_PRO_INBOXES.clear()\n"
            "assert quote_worker._jest_pro_inbox('7') is False\n"
            "print('OK')\n"
        )
        katalog = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        wynik = subprocess.run([sys.executable, "-c", kod], cwd=katalog,
                               capture_output=True, text=True)
        assert wynik.returncode == 0, wynik.stderr
        assert "OK" in wynik.stdout


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

    def test_konflikt_wylacza_pro_z_czytelnym_komunikatem(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"})
        logi = _przechwyc_logi(monkeypatch)

        assert bridge.sprawdz_guard_pro() is False
        komunikat = " ".join(logi)
        assert "BOT_QUOTE_NOTE_PERSONAS" in komunikat
        assert "BOT_PRO_INBOXES" in komunikat
        assert "quote_olx" in komunikat

    def test_quote_olx_w_trybie_notatki_jest_bezpieczne(self, monkeypatch):
        # Poller ustepuje sam (`if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS: return`),
        # wiec jedynym torem jest webhook Pro — brak wyscigu.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony={"quote_olx"},
                          quote_persony={"olx"})
        assert bridge.sprawdz_guard_pro() is True
        assert bridge.BOT_PRO_INBOXES == {"7"}

    def test_poller_wylaczony_przez_quote_personas_jest_bezpieczny(self, monkeypatch):
        # Druga bezpieczna droga: poller w ogole nie kolejkuje tur quote-bota.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"allegro"})
        assert bridge.sprawdz_guard_pro() is True

    def test_olx_poza_bot_pro_inboxes_nie_jest_konfliktem(self, monkeypatch):
        # KLUCZOWE dla starego silnika: dopoki OLX nie jest przelaczony na Pro,
        # zdjecie `quote_olx` z trybu notatki to normalna, dozwolona konfiguracja
        # legacy (bot odpowiada publicznie na OLX) — guard nie ma prawa jej ruszac.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"18"}, note_persony=set(),
                          quote_persony={"olx"})
        assert bridge.sprawdz_guard_pro() is True
        assert bridge.BOT_PRO_INBOXES == {"18"}

    def test_brak_skonfigurowanego_inboxu_olx_nie_jest_konfliktem(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"}, olx_inbox="")
        assert bridge.sprawdz_guard_pro() is True
