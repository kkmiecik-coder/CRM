# -*- coding: utf-8 -*-
# Klient darmowego stocku (Pexels/Unsplash). Zwraca (bytes, ext, attribution) albo None.
# attribution = {photographer, photographer_url, photo_url, source} (Pexels wymaga atrybucji przy publikacji).
import requests
from config import STOCK_PROVIDER, STOCK_API_KEY
from core.log import log


def _download(url):
    r = requests.get(url, timeout=60)
    if r.status_code != 200 or not r.content:
        return None
    ext = "png" if ".png" in url.lower() else "jpg"
    return (r.content, ext)


def _pick(items, exclude, key_of):
    # Pierwszy element, ktorego klucz (photo_url) NIE jest w exclude — dedup zdjec miedzy artykulami.
    ex = exclude or set()
    for it in items:
        if (key_of(it) or "") not in ex:
            return it
    return None


def search_photo(query, exclude=None):
    # Zwraca (bytes, ext, attribution) pierwszego NIEUZYTEGO zdjecia (klucz=photo_url) albo None.
    # Pobiera wiecej kandydatow (per_page=15), zeby bylo z czego pomijac juz uzyte.
    if not STOCK_API_KEY:
        return None
    try:
        if STOCK_PROVIDER == "unsplash":
            r = requests.get("https://api.unsplash.com/search/photos",
                             params={"query": query, "per_page": 15, "orientation": "landscape"},
                             headers={"Authorization": "Client-ID " + STOCK_API_KEY}, timeout=40)
            if r.status_code != 200:
                log("stock unsplash kod:", r.status_code); return None
            res = (r.json().get("results") or [])
            pick = _pick(res, exclude, lambda p: ((p.get("links") or {}).get("html")))
            if not pick:
                return None
            got = _download(pick["urls"]["regular"])
            if not got:
                return None
            u = pick.get("user") or {}
            attr = {"photographer": u.get("name") or "",
                    "photographer_url": ((u.get("links") or {}).get("html")) or "",
                    "photo_url": ((pick.get("links") or {}).get("html")) or "",
                    "source": "Unsplash"}
            return (got[0], got[1], attr)
        # domyslnie Pexels
        r = requests.get("https://api.pexels.com/v1/search",
                         params={"query": query, "per_page": 15, "orientation": "landscape"},
                         headers={"Authorization": STOCK_API_KEY}, timeout=40)
        if r.status_code != 200:
            log("stock pexels kod:", r.status_code); return None
        photos = (r.json().get("photos") or [])
        pick = _pick(photos, exclude, lambda p: p.get("url"))
        if not pick:
            return None
        got = _download(pick["src"]["large"])
        if not got:
            return None
        attr = {"photographer": pick.get("photographer") or "",
                "photographer_url": pick.get("photographer_url") or "",
                "photo_url": pick.get("url") or "",
                "source": "Pexels"}
        return (got[0], got[1], attr)
    except Exception as e:
        log("stock blad:", repr(e)); return None
