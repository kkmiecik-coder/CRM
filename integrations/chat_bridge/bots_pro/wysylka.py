# -*- coding: utf-8 -*-
"""
Jedno wejście do wysyłki wiadomości do klienta.

Profil kanału jest egzekwowany TUTAJ, w Pythonie, a nie proszony od modelu —
komunikaty sklejane w kodzie nigdy nie przechodzą przez personę, więc zakaz
oparty wyłącznie na prompcie jest nieskuteczny.

Zakres: TYLKO profil TEKSTU (markdown/emoji przez `to_channel_text`, linki, limit
długości). Flagi `images`/`image_formats` z `channel_caps.py` NIE są tu egzekwowane —
`przygotuj()` przyjmuje wyłącznie `tekst`, Dębuś Pro dziś nie ma ścieżki wysyłki obrazu,
więc nie ma czego filtrować. Gdy taka ścieżka powstanie, ma sprawdzać te flagi SAMA,
analogicznie do tego, jak `links`/`max_len` są egzekwowane tutaj — ten moduł nie obiecuje
więcej, niż faktycznie robi.
"""
import re

from bots.channel_caps import caps_for, split_message, to_channel_text

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

# Gola domena (bez protokolu) z zamkniętej listy TLD — jak w sanitize.py
# (integrations/chat_bridge/sanitize.py, kontrola treści wychodzącej na OLX/Allegro
# w STARYM silniku): zamknięta lista, żeby liczby/skróty w rodzaju "sp. z o.o." nie
# były brane za adres. `(?<!@)` na starcie chroni adresy e-mail — bez tego
# "kontakt@woodpower.pl" straciłoby domenę i zostałoby jako osierocone "kontakt@"
# (ten sam problem, przed którym sanitize.py broni się, maskując maile PRZED
# uruchomieniem wzorca domeny).
_TLD = "pl|com|eu|net|org|de|shop|store|info"
_DOMENA_RE = re.compile(
    r"(?<!@)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:%s)\b(?:/[^\s]*)?" % _TLD, re.I)

# Własna oferta na Allegro to NIE jest kierowanie kupującego poza platformę — jak
# sanitize.py._HOSTY_DOZWOLONE. Dziś links=False ma WYŁĄCZNIE ALLEGRO_CAPS, więc lista
# jest specyficzna dla Allegro (nie generyczna per-kanał); gdyby w przyszłości inny
# kanał też dostał links=False, ta lista wymagałaby sparametryzowania per kanał.
_HOSTY_DOZWOLONE = ("allegro.pl", "allegrolokalnie.pl", "allegro.com")

# Kikuty zdania zostające po wycięciu linku ("Link: " / "Szczegóły wyceny: ") —
# dwukropek albo słowo "Link" (z dwukropkiem albo bez) na końcu linii.
_OSIEROCONY_LINK_RE = re.compile(r"(?im)\blink\s*:?[ \t]*$")
_OSIEROCONY_DWUKROPEK_RE = re.compile(r"(?m):[ \t]*$")


def wolno_linkowac(persona):
    """Czy na tym kanale wolno kierować klienta poza platformę."""
    return bool(caps_for(persona).get("links", True))


def _host_dozwolony(fragment):
    """Czy dopasowany link wskazuje na WŁASNĄ domenę Allegro (self-reference —
    nie jest kierowaniem kupującego poza platformę)."""
    host = re.sub(r"^https?://", "", fragment, flags=re.I).split("/")[0].lower()
    host = host.split("?")[0].strip(".")
    return any(host == d or host.endswith("." + d) for d in _HOSTY_DOZWOLONE)


def _usun_link(dopasowanie):
    fragment = dopasowanie.group(0)
    return fragment if _host_dozwolony(fragment) else ""


def _wytnij_linki(tekst):
    """Wycina URL-e (ze schematem) i gołe domeny (bez schematu). `to_channel_text`
    sam nie rozróżnia 'linku' od zwykłego tekstu — bez tej drugiej fazy
    `crm.woodpower.pl` napisane bez `https://` przechodziłoby bez zmian (runda
    poprawek 1, W4: pierwsza wersja łapała wyłącznie `https?://`)."""
    tekst = _URL_RE.sub(_usun_link, tekst)
    tekst = _DOMENA_RE.sub(_usun_link, tekst)
    return tekst


def _posprzataj_po_wycieciu_linkow(tekst):
    """Wycięcie linku zostawia czasem kikut zdania ('Link: ' / 'Szczegóły wyceny: ')
    — usuwamy dwukropek i osierocone słowo 'Link' na końcu linii (runda poprawek 1,
    drobne)."""
    tekst = _OSIEROCONY_LINK_RE.sub("", tekst)
    tekst = _OSIEROCONY_DWUKROPEK_RE.sub("", tekst)
    return tekst


def przygotuj(tekst, persona):
    """Tekst gotowy do wysłania, pocięty na części mieszczące się w limicie."""
    caps = caps_for(persona)
    tresc = to_channel_text(tekst or "", caps)

    if not caps.get("links", True):
        # Allegro: regulamin zabrania kierowania kupującego poza platformę.
        tresc = _wytnij_linki(tresc)
        tresc = _posprzataj_po_wycieciu_linkow(tresc)
        tresc = re.sub(r"[ \t]{2,}", " ", tresc).strip()

    # split_message(text, caps) — sygnatura w bots/channel_caps.py:123 przyjmuje CAŁY
    # słownik caps (czyta z niego "max_len" sama), nie gołą liczbę. Przekazanie samego
    # limitu (int) wywaliłoby się na `caps.get(...)` wewnątrz split_message.
    return split_message(tresc, caps)
