# -*- coding: utf-8 -*-
"""
Jedno wejście do wysyłki wiadomości do klienta.

Profil kanału jest egzekwowany TUTAJ, w Pythonie, a nie proszony od modelu —
komunikaty sklejane w kodzie nigdy nie przechodzą przez personę, więc zakaz
oparty wyłącznie na prompcie jest nieskuteczny.
"""
import re

from bots.channel_caps import caps_for, split_message, to_channel_text

_URL_RE = re.compile(r"https?://\S+")


def wolno_linkowac(persona):
    """Czy na tym kanale wolno kierować klienta poza platformę."""
    return bool(caps_for(persona).get("links", True))


def przygotuj(tekst, persona):
    """Tekst gotowy do wysłania, pocięty na części mieszczące się w limicie."""
    caps = caps_for(persona)
    tresc = to_channel_text(tekst or "", caps)

    if not caps.get("links", True):
        # Allegro: regulamin zabrania kierowania kupującego poza platformę.
        tresc = _URL_RE.sub("", tresc)
        tresc = re.sub(r"[ \t]{2,}", " ", tresc).strip()

    # split_message(text, caps) — sygnatura w bots/channel_caps.py:123 przyjmuje CAŁY
    # słownik caps (czyta z niego "max_len" sama), nie gołą liczbę. Przekazanie samego
    # limitu (int) wywaliłoby się na `caps.get(...)` wewnątrz split_message.
    return split_message(tresc, caps)
