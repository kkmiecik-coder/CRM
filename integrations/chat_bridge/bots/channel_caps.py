# -*- coding: utf-8 -*-
# Zdolnosci kanalu (caps) + sanitizer wyjscia bota do formatu danego kanalu.
# Czyste funkcje, bez efektow ubocznych. Domyslne caps = wszystko dozwolone
# (livechat/Messenger) -> to_channel_text jest wtedy DOKLADNYM no-opem (zero regresji).
# OLX = czysty tekst: bez markdownu, bez emoji, w limicie dlugosci, bez obrazow.
import re

# Zdolnosci kanalu — co wolno wyslac:
#   markdown:      czy klient renderuje markdown (False -> usuwamy ** __ naglowki > ; linki -> gole URL)
#   images:        czy wolno dolaczac obrazy (False -> pomijamy image_path w wysylce bota)
#   image_formats: dozwolone formaty obrazu (rozszerzenia) albo None = bez ograniczenia
#   emoji:         czy zostawiamy emoji (False -> usuwamy)
#   max_len:       maks. dlugosc jednej wiadomosci (None -> bez limitu; inaczej rozbijamy)
DEFAULT_CAPS = {"markdown": True, "images": True, "image_formats": None, "emoji": True, "max_len": None}

# Marketplace'y (OLX i Allegro): czat tekstowy, markdown NIE jest renderowany, emoji off, limit
# konserwatywny. Obrazy WLACZONE (odczyt + wysylka), ale tylko jpg/png (oba marketplace
# obsluguja te formaty; assety bota i tak sa jpg/png). max_len tunowalny (D2 nie da sie ustalic
# z kodu) — 2000 to bezpieczny domysl.
OLX_CAPS = {"markdown": False, "images": True, "image_formats": ("jpg", "jpeg", "png"),
            "emoji": False, "max_len": 2000}

# Klucze person/kanalow, ktore wymagaja czystego tekstu (marketplace: OLX i Allegro —
# zadne z nich nie renderuje markdownu, a bot/agent wkleja tresc wprost do watku).
_PLAIN_TEXT_PERSONAS = ("quote_olx", "olx", "quote_allegro", "allegro")

# Zakresy emoji (bez blokow strzalek 0x2190-0x21FF — "→" bywa uzywana w tekscie jako separator).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"           # symbole i piktogramy (+ supplemental, extended-A)
    "\U0001F000-\U0001F0FF"           # mahjong / domino / karty
    "\U00002600-\U000027BF"           # rozne symbole + dingbaty (m.in. sloneczko, nozyczki)
    "\U00002B00-\U00002BFF"           # gwiazdki/strzalki ozdobne
    "\U0000FE00-\U0000FE0F"           # variation selectors (np. warianty emoji)
    "\U0001F1E6-\U0001F1FF"           # flagi (regional indicators)
    "\U0000200D"                      # ZWJ (laczy emoji zlozone)
    "\U00002122\U00002139\U000024C2"  # (TM), (i), (M)
    "]+",
    flags=re.UNICODE,
)

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")   # [label](url) -> gole url
_URL_RE = re.compile(r"https?://\S+")                    # goly URL (chroniony przy usuwaniu ** __)
_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")     # naglowki markdown na poczatku linii
_QUOTE_RE = re.compile(r"(?m)^[ \t]*>[ \t]?")            # cytaty blokowe na poczatku linii
_BULLET_RE = re.compile(r"(?m)^([ \t]*)[\*\+][ \t]+")    # wypunktowanie * / + -> - (spojne)
_TRAIL_WS_RE = re.compile(r"(?m)[ \t]+$")                # spacje/taby na koncu linii
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")                # zwielokrotnione spacje w srodku linii
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")            # granica zdania (po . ! ?)


def _strip_md_emphasis(text):
    """Usuwa markdownowe ** i __ (pogrubienie/podkreslenie), CHRONIAC URL-e — mogą one
    zawierac te znaki (np. parametry trackingowe), a nie sa emfaza."""
    stash = []

    def _protect(m):
        stash.append(m.group(0))
        return "\x00%d\x00" % (len(stash) - 1)

    tmp = _URL_RE.sub(_protect, text)
    tmp = tmp.replace("**", "").replace("__", "")
    if stash:
        tmp = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], tmp)
    return tmp


def caps_for(persona_key):
    """Zwraca KOPIE zdolnosci dla klucza persony/kanalu. Nieznany klucz -> DEFAULT_CAPS.
    Kopia, zeby wolajacy nie mutowal wspoldzielonej stalej."""
    if persona_key in _PLAIN_TEXT_PERSONAS:
        return dict(OLX_CAPS)
    return dict(DEFAULT_CAPS)


def to_channel_text(text, caps):
    """Sanitizuje tekst bota do formatu kanalu wg caps. Czysta funkcja, idempotentna.
    NIE rozbija na wiele wiadomosci (od tego jest split_message).
    Gdy caps pozwala na markdown i emoji (np. livechat) -> zwraca tekst BEZ ZMIAN."""
    if not text:
        return text
    md_off = not caps.get("markdown", True)
    emoji_off = not caps.get("emoji", True)
    if not md_off and not emoji_off:
        return text  # nic do zrobienia -> dokladny no-op (zero regresji na livechat/Messenger)
    out = text
    if md_off:
        out = _MD_LINK_RE.sub(r"\2", out)             # linki -> gole URL
        out = _strip_md_emphasis(out)                  # pogrubienie / podkreslenie (chroni URL-e)
        out = _HEADING_RE.sub("", out)                 # naglowki
        out = _QUOTE_RE.sub("", out)                   # cytaty blokowe
        out = _BULLET_RE.sub(r"\1- ", out)             # * / + -> - (spojne wypunktowanie)
    if emoji_off:
        out = _EMOJI_RE.sub("", out)
    # Sprzatanie po usunieciach: zwielokrotnione spacje i konce linii.
    out = _MULTISPACE_RE.sub(" ", out)
    out = _TRAIL_WS_RE.sub("", out)
    return out


def split_message(text, caps):
    """Rozbija tekst na liste wiadomosci <= caps['max_len'] (None -> bez rozbijania).
    Preferuje granice zdan; zdanie dluzsze niz limit tnie twardo. Pusty tekst -> []."""
    if not text or not text.strip():
        return []
    max_len = caps.get("max_len")
    t = text.strip()
    if not max_len or len(t) <= max_len:
        return [t]
    chunks = []
    buf = ""
    for sent in _SENT_SPLIT_RE.split(t):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) > max_len:
            # Zdanie dluzsze niz limit -> najpierw domknij bufor, potem twarde kawalki.
            if buf:
                chunks.append(buf); buf = ""
            for i in range(0, len(sent), max_len):
                chunks.append(sent[i:i + max_len])
            continue
        kandydat = sent if not buf else (buf + " " + sent)
        if len(kandydat) <= max_len:
            buf = kandydat
        else:
            chunks.append(buf); buf = sent
    if buf:
        chunks.append(buf)
    return chunks
