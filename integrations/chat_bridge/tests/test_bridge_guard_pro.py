# -*- coding: utf-8 -*-
"""
Guard startowy Debusia Pro (`guard_pro.sprawdz_guard_pro`).

Dwie kontrole: brak BOT_PRO_AGENT_WEBHOOK_TOKEN przy niepustym BOT_PRO_INBOXES
(weryfikacja tokenu w webhooks.py jest warunkowa — `if TOKEN and ...` — wiec
webhook /agent-bot-pro stalby otworem) oraz konflikt konfiguracji OLX (U10,
patrz TestGuardWyscigNaOlx).

Reakcja na blad to WYLACZENIE Pro, nie ubicie procesu (U14b, patrz
TestGuardNieUbijaKontenera) — w tym samym kontenerze mieszka stary silnik
obslugujacy zywy ruch.

B1 (Debus Pro na slocie kandydata): guard zyl w `bridge.py` i byl wolany TYLKO
tam — kandydat (`bridge_quote_candidate.py`) startowal bez niego. Modul jest
teraz osobny (`guard_pro.py`), bo `bridge.py` na poziomie modulu ciagnie rejestr
kanalow, wszystkie workery i tworzy obiekt Flask — kandydat nie moze go
importowac. Patrz TestGuardWObuEntrypointach.
"""
import ast
import os

import pytest

import guard_pro

_KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _przechwyc_logi(monkeypatch):
    logi = []
    monkeypatch.setattr(guard_pro, "log", lambda *czesci: logi.append(" ".join(str(c) for c in czesci)))
    return logi


def _zdrowa_konfiguracja(monkeypatch):
    """Komplet tokenow Pro — punkt wyjscia dla testow, ktore psuja JEDNA rzecz."""
    monkeypatch.setattr(guard_pro, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret-webhook")


def test_brak_tokenu_i_niepuste_inboxy_wylacza_pro(monkeypatch):
    _zdrowa_konfiguracja(monkeypatch)
    monkeypatch.setattr(guard_pro, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    inboxy = {"5"}
    monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", inboxy)
    logi = _przechwyc_logi(monkeypatch)

    assert guard_pro.sprawdz_guard_pro() is False
    assert inboxy == set()   # Pro wylaczone, stary silnik dziala dalej
    assert any("BOT_PRO_AGENT_WEBHOOK_TOKEN" in wpis for wpis in logi)


def test_pusty_token_string_tez_wylacza_pro(monkeypatch):
    # "" jest falsy tak samo jak None - literowka w bridge.env (pusta wartosc zamiast
    # braku zmiennej) nie moze po cichu ominac guarda.
    _zdrowa_konfiguracja(monkeypatch)
    monkeypatch.setattr(guard_pro, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "")
    inboxy = {"5"}
    monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", inboxy)
    _przechwyc_logi(monkeypatch)

    assert guard_pro.sprawdz_guard_pro() is False
    assert inboxy == set()


def test_pusty_bot_pro_inboxes_nie_wymaga_tokenu(monkeypatch):
    # Bot wylaczony wszedzie (kill-switch) - brak tokenu jest wtedy nieszkodliwy,
    # bo i tak nic sie nie kolejkuje (webhooks._process_pro filtruje po inboxie).
    monkeypatch.setattr(guard_pro, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
    monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", set())
    assert guard_pro.sprawdz_guard_pro() is True


def test_token_ustawiony_pozwala_startowac_mimo_inboxow(monkeypatch):
    _zdrowa_konfiguracja(monkeypatch)
    inboxy = {"5", "18"}
    monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", inboxy)
    assert guard_pro.sprawdz_guard_pro() is True
    assert inboxy == {"5", "18"}   # nietkniete


# ---------------------------------------------------------------------------
# B1 — guard w OBU entrypointach
# ---------------------------------------------------------------------------

def _blok_main(nazwa_pliku):
    """Instrukcje z bloku `if __name__ == "__main__":` danego pliku zrodlowego.

    Czytamy AST, nie importujemy — blok `__main__` entrypointu uruchamia watki
    i serwer Flask, wiec jedyny sposob, zeby sprawdzic JEGO zawartosc w tescie
    jednostkowym, to lektura zrodla."""
    sciezka = os.path.join(_KATALOG, nazwa_pliku)
    with open(sciezka, encoding="utf-8") as f:
        drzewo = ast.parse(f.read(), filename=sciezka)
    for wezel in drzewo.body:
        if isinstance(wezel, ast.If) and "__main__" in ast.dump(wezel.test):
            return wezel.body
    raise AssertionError("brak bloku __main__ w %s" % nazwa_pliku)


def _nazwy_wolanych(instrukcje):
    """Nazwy funkcji wolanych w danych instrukcjach, w kolejnosci wystapienia."""
    nazwy = []
    for instrukcja in instrukcje:
        for wezel in ast.walk(instrukcja):
            if isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Name):
                nazwy.append(wezel.func.id)
    return nazwy


class TestGuardWObuEntrypointach:
    """B1: `sprawdz_guard_pro` byl w `bridge.py` i wolany TYLKO tam. Kandydat
    (`bridge_quote_candidate.py`) startowal bez zadnej kontroli — `bridge-candidate.env`
    z `BOT_PRO_INBOXES=18` i pustym `BOT_PRO_AGENT_WEBHOOK_TOKEN` zostawial
    `/cand/agent-bot-pro` OTWARTY na dowolny nieautoryzowany POST (weryfikacja
    tokenu w `webhooks.py` jest warunkowa). Wstrzykniety JSON z `conv_id` i
    `inbox_id` 18 wywolywal PUBLICZNA odpowiedz bota — bez wpisu w logu, bo
    guard nigdy sie nie odezwal."""

    def test_bridge_wola_guard_przed_init_db(self):
        nazwy = _nazwy_wolanych(_blok_main("bridge.py"))
        assert "sprawdz_guard_pro" in nazwy
        assert "init_db" in nazwy
        assert nazwy.index("sprawdz_guard_pro") < nazwy.index("init_db")

    def test_kandydat_wola_guard_jako_pierwsza_instrukcje(self):
        blok = _blok_main("bridge_quote_candidate.py")
        nazwy = _nazwy_wolanych(blok)
        assert "sprawdz_guard_pro" in nazwy, (
            "kandydat startuje BEZ guarda — /cand/agent-bot-pro staje otworem")
        assert "init_db" in nazwy
        assert nazwy.index("sprawdz_guard_pro") < nazwy.index("init_db")
        assert _nazwy_wolanych([blok[0]])[:1] == ["sprawdz_guard_pro"]

    def test_oba_entrypointy_uzywaja_TEJ_SAMEJ_funkcji(self):
        import bridge
        import bridge_quote_candidate
        assert bridge.sprawdz_guard_pro is guard_pro.sprawdz_guard_pro
        assert bridge_quote_candidate.sprawdz_guard_pro is guard_pro.sprawdz_guard_pro

    def test_import_guard_pro_nie_ciagnie_calego_mostka(self):
        """Kandydat NIE MOZE dostac guarda przez `from bridge import ...`:
        `bridge.py` na poziomie modulu importuje rejestr kanalow i wszystkie
        workery oraz tworzy obiekt Flask — kandydat dostalby wtedy DRUGI obiekt
        aplikacji i polowe produkcyjnego mostka jako efekt uboczny importu."""
        import subprocess
        import sys

        kod = (
            "import sys\n"
            "import guard_pro\n"
            "assert 'bridge' not in sys.modules, 'guard_pro ciagnie bridge'\n"
            "assert 'channels' not in sys.modules, 'guard_pro ciagnie rejestr kanalow'\n"
            "assert 'flask' not in sys.modules, 'guard_pro ciagnie Flaska'\n"
            "print('OK')\n"
        )
        wynik = subprocess.run([sys.executable, "-c", kod], cwd=_KATALOG,
                               capture_output=True, text=True,
                               env=dict(os.environ, OLX_CLIENT_ID="x", OLX_CLIENT_SECRET="x",
                                        OLX_REFRESH_TOKEN="x"))
        assert wynik.returncode == 0, wynik.stderr
        assert "OK" in wynik.stdout


class TestGuardNieUbijaKontenera:
    """U14b (recenzja końcowa): guard był `SystemExit`, czyli wadliwa konfiguracja
    DOTYCZĄCA WYŁĄCZNIE Dębusia Pro zdejmowała CAŁY kontener mostka — razem ze
    starym silnikiem, który obsługuje dziś żywy ruch na livechacie, OLX i Allegro,
    oraz z pollerami kanałów, sweeperami i indeksem bazy wiedzy. Ma wyłączać Pro
    i głośno logować, nie zabijać procesu."""

    def test_zla_konfiguracja_nie_rzuca_systemexit(self, monkeypatch):
        _zdrowa_konfiguracja(monkeypatch)
        monkeypatch.setattr(guard_pro, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", {"5"})
        _przechwyc_logi(monkeypatch)
        guard_pro.sprawdz_guard_pro()   # brak wyjatku == kontener wstaje

    def test_konflikt_olx_tez_tylko_wylacza(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"})
        logi = _przechwyc_logi(monkeypatch)

        assert guard_pro.sprawdz_guard_pro() is False
        assert guard_pro.BOT_PRO_INBOXES == set()
        assert any("quote_olx" in wpis for wpis in logi)

    def test_wyczyszczenie_listy_wylacza_pro_w_calym_mostku(self):
        """Dowód, że „wyłączenie Pro" naprawdę działa: `BOT_PRO_INBOXES` to JEDEN
        obiekt (zbiór) współdzielony przez wszystkie moduły, które o Pro decydują —
        wyczyszczenie go w `guard_pro` jest tym samym kill-switchem, co pusta zmienna
        środowiskowa. Gdyby któryś moduł trzymał KOPIĘ, guard wyłączałby Pro tylko
        na papierze.

        Sprawdzane w OSOBNYM PROCESIE, na czystym imporcie: kilka innych plików
        testowych robi `importlib.reload(config)` / `reload(webhooks)`, co rebinduje
        te nazwy do NOWYCH zbiorów. To artefakt harnessu (produkcja niczego nie
        przeładowuje), ale w jednym procesie pytest zamazywałby dokładnie tę
        własność, którą ten test ma udowodnić."""
        import subprocess
        import sys

        kod = (
            "import config, guard_pro, bridge, bridge_quote_candidate, webhooks, "
            "quote_worker, pro_watchdog\n"
            "assert guard_pro.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert webhooks.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert quote_worker.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "assert pro_watchdog.BOT_PRO_INBOXES is config.BOT_PRO_INBOXES\n"
            "config.BOT_PRO_INBOXES.add('7')\n"
            "assert quote_worker._jest_pro_inbox('7') is True\n"
            "guard_pro.BOT_PRO_INBOXES.clear()\n"
            "assert quote_worker._jest_pro_inbox('7') is False\n"
            "print('OK')\n"
        )
        wynik = subprocess.run([sys.executable, "-c", kod], cwd=_KATALOG,
                               capture_output=True, text=True)
        assert wynik.returncode == 0, wynik.stderr
        assert "OK" in wynik.stdout


def _konfiguracja_olx(monkeypatch, inboxy_pro, note_persony, quote_persony,
                      olx_inbox="7"):
    _zdrowa_konfiguracja(monkeypatch)
    monkeypatch.setattr(guard_pro, "BOT_PRO_INBOXES", set(inboxy_pro))
    monkeypatch.setattr(guard_pro, "CW_OLX_INBOX", olx_inbox)
    monkeypatch.setattr(guard_pro, "BOT_QUOTE_NOTE_PERSONAS", set(note_persony))
    monkeypatch.setattr(guard_pro, "BOT_QUOTE_PERSONAS", set(quote_persony))


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

        assert guard_pro.sprawdz_guard_pro() is False
        komunikat = " ".join(logi)
        assert "BOT_QUOTE_NOTE_PERSONAS" in komunikat
        assert "BOT_PRO_INBOXES" in komunikat
        assert "quote_olx" in komunikat

    def test_quote_olx_w_trybie_notatki_jest_bezpieczne(self, monkeypatch):
        # Poller ustepuje sam (`if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS: return`),
        # wiec jedynym torem jest webhook Pro — brak wyscigu.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony={"quote_olx"},
                          quote_persony={"olx"})
        assert guard_pro.sprawdz_guard_pro() is True
        assert guard_pro.BOT_PRO_INBOXES == {"7"}

    def test_poller_wylaczony_przez_quote_personas_jest_bezpieczny(self, monkeypatch):
        # Druga bezpieczna droga: poller w ogole nie kolejkuje tur quote-bota.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"allegro"})
        assert guard_pro.sprawdz_guard_pro() is True

    def test_olx_poza_bot_pro_inboxes_nie_jest_konfliktem(self, monkeypatch):
        # KLUCZOWE dla starego silnika: dopoki OLX nie jest przelaczony na Pro,
        # zdjecie `quote_olx` z trybu notatki to normalna, dozwolona konfiguracja
        # legacy (bot odpowiada publicznie na OLX) — guard nie ma prawa jej ruszac.
        _konfiguracja_olx(monkeypatch, inboxy_pro={"18"}, note_persony=set(),
                          quote_persony={"olx"})
        assert guard_pro.sprawdz_guard_pro() is True
        assert guard_pro.BOT_PRO_INBOXES == {"18"}

    def test_brak_skonfigurowanego_inboxu_olx_nie_jest_konfliktem(self, monkeypatch):
        _konfiguracja_olx(monkeypatch, inboxy_pro={"7"}, note_persony=set(),
                          quote_persony={"olx"}, olx_inbox="")
        assert guard_pro.sprawdz_guard_pro() is True
