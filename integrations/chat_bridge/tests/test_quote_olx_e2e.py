# -*- coding: utf-8 -*-
# E2E-kontrakt wyjscia OLX (FAZA 4, deterministyczny): przepuszcza realistyczna odpowiedz bota
# przez PELNA sciezke run_quote_turn -> caps kanalu -> wrapper cw_agent_reply i sprawdza, co
# faktycznie poszloby na OLX. Live-E2E (wstrzykniecie na testowym inboxie Api) to osobny krok
# operacyjny przy deployu — tu weryfikujemy gwarancje, ktore daje kod (bez sieci).
import pytest
from bots import quotebot


class _Calls(list):
    pass


@pytest.fixture
def wyslane(monkeypatch):
    """Przechwytuje surowa wysylke do klienta (to, co trafiloby na OLX/relay)."""
    calls = _Calls()

    def fake(conv_id, text, image_path=None, image_name=None, image_mime="image/jpeg", token=None):
        calls.append({"text": text, "image_path": image_path})
        return True

    monkeypatch.setattr(quotebot, "_cw_agent_reply_raw", fake)
    return calls


def _turn_with_reply(monkeypatch, persona, text, image_path=None):
    """Symuluje ture: inner (jak LLM) wola cw_agent_reply z gotowa tresc; run_quote_turn
    ustawia caps kanalu wokol tury. Zwraca nic — efekt widac w fixture `wyslane`."""
    def _inner(conv_id, inbox_id, message_id, content, attachments=None, persona="quote"):
        quotebot.cw_agent_reply(conv_id, text, image_path=image_path, token="T")
    monkeypatch.setattr(quotebot, "_run_quote_turn_inner", _inner)
    quotebot.run_quote_turn(7, 18, "olx-1", "poproszę wycenę", persona=persona)


# --- Scenariusz 1: pelna wycena na OLX -> czysty tekst, gole URL, obraz jpg dozwolony ---

def test_e2e_olx_wycena_plain_text_url_i_jpg(wyslane, monkeypatch):
    _turn_with_reply(
        monkeypatch, "quote_olx",
        "**Twoja wycena:** 1200 zł 😊\nSzczegóły tutaj: https://woodpower.pl/q/abc123\n"
        "- dąb lity\n- wykończenie surowe 👇",
        image_path="gatunki_porownanie.jpg")
    laczny = "\n".join(c["text"] for c in wyslane)
    assert "**" not in laczny            # brak markdownu
    assert "😊" not in laczny and "👇" not in laczny  # brak emoji
    assert "https://woodpower.pl/q/abc123" in laczny  # czytelny goly URL
    assert "1200 zł" in laczny
    assert any(c["image_path"] == "gatunki_porownanie.jpg" for c in wyslane)  # jpg dozwolony


# --- Scenariusz 2: dlugie podsumowanie rozbite w limicie OLX ---

def test_e2e_olx_dlugie_podsumowanie_rozbite_w_limicie(wyslane, monkeypatch):
    dlugi = " ".join("Pozycja numer %d dębowa lita surowa." % i for i in range(300))
    _turn_with_reply(monkeypatch, "quote_olx", dlugi)
    assert len(wyslane) > 1                       # rozbite na wiele wiadomosci
    assert all(len(c["text"]) <= 2000 for c in wyslane)  # kazda w limicie OLX


# --- Scenariusz 3: obraz o zlym formacie (gif) pominiety, sam tekst idzie ---

def test_e2e_olx_gif_pominiety(wyslane, monkeypatch):
    _turn_with_reply(monkeypatch, "quote_olx", "Zerknij na wzornik", image_path="wzornik.gif")
    assert all(c["image_path"] is None for c in wyslane)      # gif niedozwolony
    assert any("Zerknij na wzornik" in c["text"] for c in wyslane)


# --- Scenariusz 4: livechat BEZ REGRESJI — markdown/emoji/obraz zachowane, jedna wiadomosc ---

def test_e2e_livechat_bez_regresji(wyslane, monkeypatch):
    tekst = "**Twoja wycena:** 1200 zł 😊 https://woodpower.pl/q/x"
    _turn_with_reply(monkeypatch, "quote", tekst, image_path="probka.jpg")
    assert len(wyslane) == 1
    assert wyslane[0]["text"] == tekst            # dokladnie bez zmian
    assert wyslane[0]["image_path"] == "probka.jpg"


# --- Scenariusz 5: caps przywracane po turze OLX (kolejna tura livechat nie dziedziczy) ---

def test_e2e_caps_nie_wyciekaja_na_kolejna_ture(wyslane, monkeypatch):
    _turn_with_reply(monkeypatch, "quote_olx", "**x** 😊", image_path="a.jpg")
    # druga tura, persona livechat: markdown/emoji musza przetrwac (caps OLX nie wyciekly)
    _turn_with_reply(monkeypatch, "quote", "**y** 😊", image_path="b.jpg")
    assert wyslane[-1]["text"] == "**y** 😊"
    assert wyslane[-1]["image_path"] == "b.jpg"
