# -*- coding: utf-8 -*-
"""
Jedno wejście do wysyłki wiadomości do klienta.

Profil kanału jest egzekwowany TUTAJ, w Pythonie, a nie proszony od modelu —
komunikaty sklejane w kodzie nigdy nie przechodzą przez personę, więc zakaz
oparty wyłącznie na prompcie jest nieskuteczny.

Zakres: TYLKO profil TEKSTU (markdown/emoji przez `to_channel_text`, linki, limit
długości). Flagi `images`/`image_formats` z `channel_caps.py` NIE są tu egzekwowane —
`przygotuj()` przyjmuje wyłącznie `tekst`, więc nie ma czego filtrować.

Ścieżka wysyłki OBRAZU powstała w rundzie napraw 4 i mieszka w
`bots_pro/obrazy_do_klienta.py`. Sprawdza tamte dwie flagi SAMA — dokładnie tak, jak
zapowiadał ten komentarz, zanim ścieżka istniała — a sam PODPIS obrazu przepuszcza
przez `przygotuj()` niżej, żeby profil tekstowy dalej był egzekwowany w jednym miejscu.
Ten moduł nie obiecuje więcej, niż faktycznie robi.
"""
import re

from bots.channel_caps import caps_for, split_message, to_channel_text

# Gola domena (bez protokolu) z zamkniętej listy TLD — jak w sanitize.py
# (integrations/chat_bridge/sanitize.py, kontrola treści wychodzącej na OLX/Allegro
# w STARYM silniku): zamknięta lista, żeby liczby/skróty w rodzaju "sp. z o.o." nie
# były brane za adres.
_TLD = "pl|com|eu|net|org|de|shop|store|info"

# Kikut zdania ("Link: " / goły ":") liczy się WYŁĄCZNIE wtedy, gdy stoi
# BEZPOŚREDNIO przed faktycznie dopasowanym linkiem — dopisany do TEJ SAMEJ
# grupy w regexie, więc wycięcie kikuta i wycięcie linku to JEDNO przejście,
# nie dwa niezależne globalne sprzątania (runda poprawek 2, N1: poprzednia
# wersja sprzątała "osierocony dwukropek"/"osierocone słowo Link" NA KOŃCU
# DOWOLNEJ LINII, niezależnie od tego, czy cokolwiek faktycznie wycięto —
# "Cena zależy od wymiarów:" (żadnego linku) traciła dwukropek, "Proszę
# kliknij ten link" (żadnego linku) traciła słowo "link". Ten wzorzec nie
# może już tak zadziałać: bez faktycznego dopasowania linku PO prawej stronie
# grupa kikuta w ogóle nie ma czego dopasować, więc regex nie trafia NIGDZIE
# w tekście bez linku — patrz TestWytnijLinkiNieRuszaTekstuBezLinku).
_KIKUT = r"(?:\blink\s*:|:)"

_URL_RE = re.compile(r"(?:%s)?[ \t]*(?P<link>https?://[^\s<>\"']+)" % _KIKUT, re.I)
_DOMENA_RE = re.compile(
    r"(?:%s)?[ \t]*(?P<link>(?<!@)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:%s)\b(?:/[^\s]*)?)"
    % (_KIKUT, _TLD), re.I)
# `(?<!@)` w _DOMENA_RE chroni adresy e-mail — bez tego "kontakt@woodpower.pl"
# straciłoby domenę i zostałoby jako osierocone "kontakt@" (ten sam problem,
# przed którym broni się sanitize.py, maskując maile przed uruchomieniem
# wzorca domeny).

# Własna oferta na Allegro to NIE jest kierowanie kupującego poza platformę — jak
# sanitize.py._HOSTY_DOZWOLONE. Dziś links=False ma WYŁĄCZNIE ALLEGRO_CAPS, więc lista
# jest specyficzna dla Allegro (nie generyczna per-kanał); gdyby w przyszłości inny
# kanał też dostał links=False, ta lista wymagałaby sparametryzowania per kanał.
_HOSTY_DOZWOLONE = ("allegro.pl", "allegrolokalnie.pl", "allegro.com")


def wolno_linkowac(persona):
    """Czy na tym kanale wolno kierować klienta poza platformę."""
    return bool(caps_for(persona).get("links", True))


def _host_dozwolony(fragment):
    """Czy dopasowany link wskazuje na WŁASNĄ domenę Allegro (self-reference —
    nie jest kierowaniem kupującego poza platformę)."""
    host = re.sub(r"^https?://", "", fragment, flags=re.I).split("/")[0].lower()
    host = host.split("?")[0].strip(".")
    return any(host == d or host.endswith("." + d) for d in _HOSTY_DOZWOLONE)


def _usun_link_i_kikut(dopasowanie):
    """Cały dopasowany fragment (ewentualny kikut + sam link) znika razem, w
    jednym przejściu — albo zostaje w całości bez zmian, gdy link jest
    dozwolony (własna domena Allegro). Nigdy nie usuwamy samego kikuta bez
    towarzyszącego mu linku, bo regex go bez linku w ogóle nie dopasowuje."""
    if _host_dozwolony(dopasowanie.group("link")):
        return dopasowanie.group(0)
    return ""


def _wytnij_linki(tekst):
    """Wycina URL-e (ze schematem) i gołe domeny (bez schematu), razem z
    bezpośrednio poprzedzającym je kikutem zdania. `to_channel_text` sam nie
    rozróżnia 'linku' od zwykłego tekstu — bez fazy gołych domen
    `crm.woodpower.pl` napisane bez `https://` przechodziłoby bez zmian
    (runda poprawek 1, W4: pierwsza wersja łapała wyłącznie `https?://`)."""
    tekst = _URL_RE.sub(_usun_link_i_kikut, tekst)
    tekst = _DOMENA_RE.sub(_usun_link_i_kikut, tekst)
    return tekst


def przygotuj(tekst, persona):
    """Tekst gotowy do wysłania, pocięty na części mieszczące się w limicie."""
    caps = caps_for(persona)
    tresc = to_channel_text(tekst or "", caps)

    if not caps.get("links", True):
        # Allegro: regulamin zabrania kierowania kupującego poza platformę.
        tresc = _wytnij_linki(tresc)
        tresc = re.sub(r"[ \t]{2,}", " ", tresc).strip()

    # split_message(text, caps) — sygnatura w bots/channel_caps.py:123 przyjmuje CAŁY
    # słownik caps (czyta z niego "max_len" sama), nie gołą liczbę. Przekazanie samego
    # limitu (int) wywaliłoby się na `caps.get(...)` wewnątrz split_message.
    return split_message(tresc, caps)
