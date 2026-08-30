# -*- coding: utf-8 -*-
"""
Sciezka awaryjna Debusia Pro w quote_worker.py (W2, code review — runda poprawek 1).

Przeprosiny po wyczerpaniu prob i komunikat o obciazeniu przy otwarciu obwodu NIE
moga isc przez legacy bots/quotebot.py dla wierszy na inboksie Debusia Pro: ta
sciezka uzywa STAREGO tokenu (BOT_QUOTE_CW_AGENT_TOKEN) i DEFAULT_CAPS (markdown/
emoji/LINKI wlaczone) niezaleznie od kanalu, a `_do_handoff` czyta/zeruje
quote_state/quote_dane — tabele legacy silnika, puste dla rozmowy Debusia Pro.
Wlasna sciezka (`_pro_wyslij`/`_pro_apologia_i_handoff`) uzywa BOT_PRO_CW_AGENT_TOKEN
i przechodzi przez bots_pro.wysylka.przygotuj (kanalowe caps — bez linkow na Allegro).
"""
import os
import tempfile

import pytest

os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BOT_PRO_CW_AGENT_TOKEN"] = "TOKEN-PRO-TEST"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_pro_failover.db"))

import importlib

import config
importlib.reload(config)
db_mod = importlib.import_module("core.db")
db_mod.init_db()
qw = importlib.import_module("quote_worker")
importlib.reload(qw)


class TestJestProInbox:
    def test_inbox_na_liscie_jest_pro(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"5", "7"})
        assert qw._jest_pro_inbox("5") is True

    def test_inbox_liczba_jest_koercjonowana_do_stringa(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"5"})
        assert qw._jest_pro_inbox(5) is True

    def test_inbox_spoza_listy_nie_jest_pro(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"5"})
        assert qw._jest_pro_inbox("9") is False


class TestProWyslij:
    def test_uzywa_wlasnego_tokenu_debusia_pro(self, monkeypatch):
        wywolania = []
        monkeypatch.setattr(qw, "_cw_reply_raw",
                            lambda conv_id, tekst, token=None: wywolania.append((conv_id, tekst, token)))
        qw._pro_wyslij(555, "Mamy chwilowe obciazenie systemu.", "pro")
        assert len(wywolania) == 1
        assert wywolania[0][2] == qw.BOT_PRO_CW_AGENT_TOKEN

    def test_wycina_linki_na_allegro(self, monkeypatch):
        # Krytyczne: bez przejscia przez bots_pro.wysylka ten komunikat wychodzilby
        # z linkiem na Allegro, wbrew regulaminowi marketplace'u.
        wyslane = []
        monkeypatch.setattr(qw, "_cw_reply_raw",
                            lambda conv_id, tekst, token=None: wyslane.append(tekst))
        qw._pro_wyslij(556, "Szczegoly na https://crm.woodpower.pl/quotes/c/XYZ", "allegro")
        assert wyslane
        assert "https://" not in wyslane[0]

    def test_link_zostaje_na_domyslnej_personie_pro(self, monkeypatch):
        # Kontrola negatywna: kanaly BEZ zakazu linkow (domyslny profil "pro") nie
        # maja niepotrzebnie tracic tresci.
        wyslane = []
        monkeypatch.setattr(qw, "_cw_reply_raw",
                            lambda conv_id, tekst, token=None: wyslane.append(tekst))
        qw._pro_wyslij(557, "Szczegoly na https://crm.woodpower.pl/quotes/c/XYZ", "pro")
        assert "https://crm.woodpower.pl" in wyslane[0]

    def test_wyjatek_wysylki_nie_wybucha_na_zewnatrz(self, monkeypatch):
        monkeypatch.setattr(qw, "_cw_reply_raw",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Chatwoot padl")))
        qw._pro_wyslij(558, "tresc", "pro")   # nie rzuca — sciezka awaryjna


class TestProApologiaIHandoff:
    def test_wysyla_i_oddaje_rozmowe_wlasnym_tokenem(self, monkeypatch):
        wyslane = []
        handoff = []
        monkeypatch.setattr(qw, "_cw_reply_raw",
                            lambda conv_id, tekst, token=None: wyslane.append((tekst, token)))
        monkeypatch.setattr(qw, "_cw_handoff_raw",
                            lambda conv_id, token=None: handoff.append((conv_id, token)))
        qw._pro_apologia_i_handoff(559, "Przepraszam, mam problem techniczny.", "pro")
        assert wyslane and wyslane[0][1] == qw.BOT_PRO_CW_AGENT_TOKEN
        assert handoff == [(559, qw.BOT_PRO_CW_AGENT_TOKEN)]

    def test_niepowodzenie_handoffu_nie_wybucha_na_zewnatrz(self, monkeypatch):
        monkeypatch.setattr(qw, "_cw_reply_raw", lambda *a, **k: None)
        monkeypatch.setattr(qw, "_cw_handoff_raw",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        qw._pro_apologia_i_handoff(560, "tresc", "pro")   # nie rzuca


class TestFailPermanentlyRozgalezienie:
    def test_jest_pro_uzywa_wlasnej_sciezki_nie_legacy(self, monkeypatch):
        wolane_legacy = []
        wolane_pro = []
        monkeypatch.setattr(qw, "handoff_with_apology",
                            lambda *a, **k: wolane_legacy.append((a, k)))
        monkeypatch.setattr(qw, "_pro_apologia_i_handoff",
                            lambda conv_id, tekst, persona: wolane_pro.append((conv_id, tekst, persona)))
        qw._fail_permanently(1, 561, 3, "err", retryable=True, persona="olx", jest_pro=True)
        assert wolane_legacy == []
        assert wolane_pro == [(561, qw.APOLOGY_MSG, "olx")]

    def test_legacy_nadal_uzywa_handoff_with_apology(self, monkeypatch):
        wolane_legacy = []
        wolane_pro = []
        monkeypatch.setattr(
            qw, "handoff_with_apology",
            lambda conv_id, reason=None, persona=None: wolane_legacy.append((conv_id, reason, persona)))
        monkeypatch.setattr(qw, "_pro_apologia_i_handoff", lambda *a, **k: wolane_pro.append(1))
        qw._fail_permanently(1, 562, 3, "err", retryable=True, persona="quote", jest_pro=False)
        assert wolane_pro == []
        assert len(wolane_legacy) == 1


class _BladRetryable(Exception):
    """Wyjatek symulujacy przejsciowa awarie (np. SDK) — jawnie retryable=True,
    zeby test wymusil sciezke circuit-breakera (nie natychmiastowy _fail_permanently
    z K2, ktory dla nieoznaczonych wyjatkow na inboksie pro klasyfikuje jako
    NIEretryable)."""
    retryable = True


class TestProcessOneKomunikatObciazeniaRozgalezienie:
    def test_otwarcie_obwodu_pro_uzywa_pro_wyslij_nie_komunikat_obciazenia(self, monkeypatch):
        pytest.importorskip("agents")
        from bots_pro import tura as tura_pro
        monkeypatch.setattr(tura_pro, "uruchom",
                            lambda *a, **k: (_ for _ in ()).throw(_BladRetryable("awaria SDK")))

        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"18"})
        monkeypatch.setattr(qw, "BOT_CIRCUIT_THRESHOLD", 1)
        wolane_pro = []
        wolane_legacy = []
        monkeypatch.setattr(qw, "_pro_wyslij",
                            lambda conv_id, tekst, persona: wolane_pro.append((conv_id, tekst, persona)))
        monkeypatch.setattr(qw, "komunikat_obciazenia", lambda *a, **k: wolane_legacy.append(1))

        c = db_mod.db()
        c.execute("DELETE FROM quote_queue")
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
                  "VALUES(?,?,?,?,?,0)", (563, 18, "mP", "tak", "allegro"))
        c.commit(); c.close()

        qw.process_one(9_999_999_999)

        assert wolane_legacy == []
        assert len(wolane_pro) == 1
        assert wolane_pro[0][1] == qw._OBCIAZENIE_MSG
        assert wolane_pro[0][2] == "allegro"


class TestWierszSilnikaPro:
    """N3 (code review, runda 2): kluczowanie silnika WYLACZNIE po inboksie
    (BOT_PRO_INBOXES) przejmuje takze wiersze wyprodukowane przez STARE tory na
    tym samym inboksie — realny scenariusz przy migracji inbox-po-inboksie.
    Producenci takich wierszy istnieja naprawde: webhooks._process_agent_bot w
    trybie notatki (persona "quote_olx"/"quote_allegro") i poller channels/olx.py
    (persona "quote_olx" na sztywno). `_wiersz_silnika_pro` wymaga OBU warunkow:
    inbox W BOT_PRO_INBOXES ORAZ persona nalezaca do zbioru, jaki faktycznie
    produkuje Debus Pro."""

    def test_inbox_pro_z_persona_pro_jest_silnikiem_pro(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"7"})
        assert qw._wiersz_silnika_pro("7", "pro") is True
        assert qw._wiersz_silnika_pro("7", "olx") is True
        assert qw._wiersz_silnika_pro("7", "allegro") is True

    def test_inbox_pro_z_persona_legacy_nie_jest_silnikiem_pro(self, monkeypatch):
        # DOKLADNIE sonda z code review: wiersz persona='quote_olx' na inboksie
        # nalezacym do BOT_PRO_INBOXES - to NIE jest wiersz Debusia Pro.
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"7"})
        assert qw._wiersz_silnika_pro("7", "quote_olx") is False
        assert qw._wiersz_silnika_pro("7", "quote_allegro") is False
        assert qw._wiersz_silnika_pro("7", "quote") is False

    def test_inbox_spoza_bot_pro_inboxes_nigdy_nie_jest_pro(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", set())
        assert qw._wiersz_silnika_pro("7", "pro") is False


class TestMigracjaInboxPoInboksieProcessOne:
    """N3 integracyjnie: wiersz zalegly w kolejce z persony legacy, na inboksie
    juz przelaczonym do BOT_PRO_INBOXES, MA isc do run_quote_turn (legacy),
    NIE do bots_pro.tura.uruchom — inaczej wyszedlby PUBLICZNIE do kupujacego
    na OLX/Allegro zamiast do notatki, ze stanem rozmowy liczonym od zera."""

    def test_wiersz_legacy_na_inboksie_pro_idzie_do_run_quote_turn(self, monkeypatch):
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"7"})
        wolane_legacy = []
        monkeypatch.setattr(qw, "run_quote_turn",
                            lambda *a, **k: wolane_legacy.append((a, k)))

        c = db_mod.db()
        c.execute("DELETE FROM quote_queue")
        # Wiersz zakolejkowany PRZED migracja inboxu do Pro (np. przez
        # webhooks._process_agent_bot w trybie notatki) - persona legacy.
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
                  "VALUES(?,?,?,?,?,0)", (601, 7, "mL", "ile kosztuje?", "quote_olx"))
        c.commit(); c.close()

        assert qw.process_one(9_999_999_999) is True
        assert len(wolane_legacy) == 1

        c = db_mod.db()
        st = c.execute("SELECT status FROM quote_queue WHERE conv_id=601").fetchone()["status"]
        c.close()
        assert st == "sent"

    def test_wiersz_legacy_na_inboksie_pro_nie_idzie_do_bots_pro(self, monkeypatch):
        pytest.importorskip("agents")
        from bots_pro import tura as tura_pro
        wolane_pro = []
        monkeypatch.setattr(tura_pro, "uruchom",
                            lambda *a, **k: wolane_pro.append(1))
        monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"7"})

        c = db_mod.db()
        c.execute("DELETE FROM quote_queue")
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
                  "VALUES(?,?,?,?,?,0)", (602, 7, "mL2", "ile kosztuje?", "quote_allegro"))
        c.commit(); c.close()

        qw.process_one(9_999_999_999)

        assert wolane_pro == []

    def test_obwod_pro_otwarty_nie_wstrzymuje_zaleglego_wiersza_legacy(self, monkeypatch):
        # Bez N3 filtr SQL wykluczalby ten wiersz (jego inbox jest w BOT_PRO_INBOXES),
        # mimo ze to wiersz legacy, ktory nie ma nic wspolnego z awaria Debusia Pro.
        monkeypatch.setattr(qw, "BOT_PRO_INBOXES", {"7"})
        from core.db import meta_set
        now = 5_000_000
        klucz_until, _ = qw._klucze_obwodu("pro")
        meta_set(klucz_until, now + 999999)
        monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)

        c = db_mod.db()
        c.execute("DELETE FROM quote_queue")
        c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
                  "VALUES(?,?,?,?,?,0)", (603, 7, "mL3", "ile kosztuje?", "quote_olx"))
        c.commit(); c.close()

        assert qw.process_one(now) is True
        c = db_mod.db()
        st = c.execute("SELECT status FROM quote_queue WHERE conv_id=603").fetchone()["status"]
        c.close()
        assert st == "sent"
        meta_set(klucz_until, 0)
