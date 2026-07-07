# -*- coding: utf-8 -*-
# Rejestr obrazow wysylanych przez bota live-chat + lookup probek wg konfiguracji.
# Jedyne zrodlo prawdy: (a) obrazy semantyczne (model wybiera przez whitelist),
# (b) probki dobierane deterministycznie z konwencji nazwy pliku {g}_{t}_{k}_{w}.jpg.
# Zadna funkcja nie rzuca wyjatku (zasada mostka: obraz nie wywraca tury).
import os
import re
import unicodedata
from config import BOT_IMAGES_DIR as _DEFAULT_DIR


def _dir():
    # Katalog czytany przy KAZDYM wywolaniu (nie wiazany przy imporcie) — testy moga go
    # zmieniac przez env bez reimportu, produkcja korzysta z domyslnego z config.
    return os.environ.get("BOT_IMAGES_DIR") or _DEFAULT_DIR


# --- Obrazy semantyczne: model doklacza je przez pole send_image (whitelist) ---
IMAGES = {
    "gatunki_porownanie": {
        "plik": "gatunki_porownanie.jpg",
        "mime": "image/jpeg",
        "nazwa": "porownanie-gatunkow.jpg",
        "opis": "dąb, buk i jesion (lite, surowe) obok siebie — różnice w usłojeniu i kolorze",
    },
}


def whitelist_prompt():
    """Blok do promptu: linia '- tag — opis' na kazdy obraz semantyczny."""
    return "\n".join("- %s — %s" % (tag, m["opis"]) for tag, m in IMAGES.items())


# --- Obrazy kontekstowe: wysylane DETERMINISTYCZNIE przez kod wg sytuacji (nie przez LLM) ---
CONTEXT_IMAGES = {
    "wymiary": {
        "plik": "oznaczenie_wymiarow.jpg", "mime": "image/jpeg", "nazwa": "oznaczenie-wymiarow.jpg",
        "podpis": "Tak liczymy wymiary blatu — długość × szerokość × grubość 👇",
    },
    "krawedzie": {
        "plik": "oznaczenie_krawedzi.jpg", "mime": "image/jpeg", "nazwa": "oznaczenie-krawedzi.jpg",
        "podpis": ("Tak oznaczamy krawędzie (A–D góra, E–H dół, N1–N4 narożniki) — proszę wskazać, "
                   "które mają być zaokrąglone lub fazowane 👇"),
    },
}


def resolve_context(key):
    """Sciezka obrazu kontekstowego z CONTEXT_IMAGES albo None (nieznany klucz / brak pliku)."""
    m = CONTEXT_IMAGES.get(key or "")
    if not m:
        return None
    path = os.path.join(_dir(), m["plik"])
    return path if os.path.isfile(path) else None


def resolve(tag):
    """Sciezka pliku obrazu semantycznego z IMAGES albo None (nieznany tag / brak pliku)."""
    m = IMAGES.get(tag or "")
    if not m:
        return None
    path = os.path.join(_dir(), m["plik"])
    return path if os.path.isfile(path) else None


def _ascii_low(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()


def _norm_gatunek(v):
    a = _ascii_low(v)
    for g in ("dab", "buk", "jesion"):
        if g in a:
            return g
    return None


def _norm_technologia(v):
    a = _ascii_low(v)
    if "mikro" in a or "wczep" in a:
        return "mikrowczep"
    if "lit" in a:
        return "lity"
    return None


def _norm_klasa(v):
    # Odporne na dopiski LLM ("A/B (AB)", "klasa A/B"): wykrywa wzorzec a/b vs b/b.
    # Gdy oba obecne ("A/B lub B/B" — klient niezdecydowany) -> None (nie zgadujemy).
    a = _ascii_low(v)
    ma = bool(re.search(r"a\s*/?\s*b", a))
    mb = bool(re.search(r"b\s*/?\s*b", a))
    if ma and not mb:
        return "ab"
    if mb and not ma:
        return "bb"
    return None


def _norm_wykonczenie(v):
    a = _ascii_low(v)
    if "surow" in a:
        return "surowe"
    if "olej" in a:
        return "olejowane"
    if "lakier" in a:
        return "lakierowane"
    return None


def _tokeny(poz):
    """(gatunek, technologia, klasa, wykonczenie) znormalizowane albo None gdy niepelne."""
    if not isinstance(poz, dict):
        poz = {}   # zabezpieczenie: zly typ (nie-dict) -> brak tokenow, nie wyjatek
    g = _norm_gatunek(poz.get("gatunek"))
    t = _norm_technologia(poz.get("technologia"))
    k = _norm_klasa(poz.get("klasa"))
    w = _norm_wykonczenie(poz.get("wykonczenie"))
    return (g, t, k, w) if all((g, t, k, w)) else None


def resolve_sample(poz):
    """Sciezka probki dla konfiguracji pozycji (konwencja {g}_{t}_{k}_{w}.jpg) albo None,
    gdy konfiguracja niepelna lub brak pliku dla kombinacji."""
    tk = _tokeny(poz or {})
    if not tk:
        return None
    path = os.path.join(_dir(), "%s_%s_%s_%s.jpg" % tk)
    return path if os.path.isfile(path) else None


def sample_key(poz):
    """Klucz dedupu 'sample:g|t|k|w' albo None gdy konfiguracja niepelna."""
    tk = _tokeny(poz or {})
    return ("sample:%s|%s|%s|%s" % tk) if tk else None
