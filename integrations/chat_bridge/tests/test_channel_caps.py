# -*- coding: utf-8 -*-
# Testy warstwy zdolnosci kanalu (caps) + sanitizera wyjscia bota.
# Cel: bot potrafi mowic "po OLX-owemu" (czysty tekst, bez emoji, w limicie dlugosci)
# NIE zmieniajac zachowania na livechat/Messenger (DEFAULT_CAPS = no-op).
from bots.channel_caps import (
    to_channel_text, split_message, caps_for, DEFAULT_CAPS, OLX_CAPS,
)


# --- caps_for: mapowanie persony/kanalu -> zdolnosci ---

def test_caps_for_olx_plain_text_ale_obrazy_wlaczone_jpg_png():
    caps = caps_for("quote_olx")
    assert caps["markdown"] is False
    assert caps["emoji"] is False
    assert caps["max_len"] and caps["max_len"] > 0
    # Obrazy WLACZONE na OLX (odczyt+wysylka), ale tylko jpg/png.
    assert caps["images"] is True
    assert set(caps["image_formats"]) == {"jpg", "jpeg", "png"}


def test_caps_for_livechat_to_default_wszystko_dozwolone():
    caps = caps_for("quote")
    assert caps == DEFAULT_CAPS
    assert caps["markdown"] is True and caps["images"] is True
    assert caps["emoji"] is True and caps["max_len"] is None
    assert caps["image_formats"] is None   # brak ograniczenia formatu na livechacie


def test_caps_for_nieznany_klucz_to_default():
    assert caps_for("cokolwiek") == DEFAULT_CAPS


# --- to_channel_text: transformacje markdown ---

def test_markdown_off_usuwa_pogrubienie():
    out = to_channel_text("Twoja wycena: **1200 zł** brutto", OLX_CAPS)
    assert "**" not in out
    assert "1200 zł" in out


def test_markdown_off_link_zamienia_na_gole_url():
    out = to_channel_text("Szczegoly: [Twoja wycena](https://woodpower.pl/q/abc123)", OLX_CAPS)
    assert "https://woodpower.pl/q/abc123" in out
    assert "[" not in out and "](" not in out


def test_markdown_off_nie_psuje_url_z_podkresleniami():
    # URL moze zawierac __ lub ** — sanitizer usuwajac emfaze NIE moze ich zjesc (defekt #1 z review).
    tekst = "Zobacz https://woodpower.pl/a__b__c?utm=1 — szczegóły"
    out = to_channel_text(tekst, OLX_CAPS)
    assert "https://woodpower.pl/a__b__c?utm=1" in out


def test_markdown_off_link_z_podkresleniem_w_url_zostaje_caly():
    out = to_channel_text("[oferta](https://woodpower.pl/x__y)", OLX_CAPS)
    assert out.strip() == "https://woodpower.pl/x__y"


def test_markdown_off_usuwa_naglowki_i_cytaty():
    out = to_channel_text("# Podsumowanie\n> uwaga do klienta", OLX_CAPS)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    assert lines == ["Podsumowanie", "uwaga do klienta"]


def test_markdown_off_normalizuje_wypunktowanie_gwiazdka():
    out = to_channel_text("* pozycja jeden\n* pozycja dwa", OLX_CAPS)
    assert "* pozycja" not in out
    assert "pozycja jeden" in out and "pozycja dwa" in out


# --- to_channel_text: emoji ---

def test_emoji_off_usuwa_emoji_i_nie_zostawia_podwojnych_spacji():
    out = to_channel_text("Dziękujemy 😊 wyślemy kurierem 🚚 do Pana", OLX_CAPS)
    assert "😊" not in out and "🚚" not in out
    assert "  " not in out  # brak podwojnych spacji po usunieciu emoji
    assert "Dziękujemy" in out and "kurierem" in out


# --- DEFAULT_CAPS = brak zmian (zero regresji na livechat) ---

def test_default_caps_nie_rusza_markdownu_ani_emoji():
    tekst = "Twoja wycena: **1200 zł** 😊\n[link](https://woodpower.pl/q/x)"
    assert to_channel_text(tekst, DEFAULT_CAPS) == tekst


# --- idempotencja ---

def test_idempotencja_na_juz_oczyszczonym():
    tekst = "Twoja wycena: **1200 zł** 😊 [link](https://woodpower.pl/q/x)\n> uwaga"
    raz = to_channel_text(tekst, OLX_CAPS)
    dwa = to_channel_text(raz, OLX_CAPS)
    assert raz == dwa


def test_pusty_tekst_zostaje_pusty():
    assert to_channel_text("", OLX_CAPS) == ""


# --- split_message: limit dlugosci ---

def test_split_bez_limitu_zwraca_jedna_wiadomosc():
    assert split_message("krótka wiadomość", DEFAULT_CAPS) == ["krótka wiadomość"]


def test_split_pusty_tekst_zwraca_pusta_liste():
    assert split_message("", OLX_CAPS) == []
    assert split_message("   ", OLX_CAPS) == []


def test_split_respektuje_max_len_na_granicach_zdan():
    caps = {"markdown": False, "images": False, "emoji": False, "max_len": 60}
    tekst = ("Pierwsze zdanie wyceny. Drugie zdanie wyceny. Trzecie zdanie wyceny. "
             "Czwarte zdanie wyceny. Piąte zdanie wyceny.")
    czesci = split_message(tekst, caps)
    assert len(czesci) > 1
    assert all(len(c) <= 60 for c in czesci)
    # zadne slowo nie ginie przy rozbijaniu
    for slowo in ("Pierwsze", "Piąte", "wyceny."):
        assert any(slowo in c for c in czesci)


def test_split_twardo_tnie_gdy_brak_granic():
    caps = {"markdown": False, "images": False, "emoji": False, "max_len": 100}
    tekst = "a" * 250  # brak spacji/kropek -> twarde ciecie
    czesci = split_message(tekst, caps)
    assert all(len(c) <= 100 for c in czesci)
    assert "".join(czesci) == tekst
