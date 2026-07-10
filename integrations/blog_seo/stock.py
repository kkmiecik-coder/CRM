# -*- coding: utf-8 -*-
# Klient darmowego stocku (Pexels lub Unsplash) — pobiera jedno trafne zdjecie do obrazu hero.
# Zwraca (bytes, ext) albo None (brak klucza/bledu). Licencja Pexels/Unsplash OK do uzytku komercyjnego.
import requests
from config import STOCK_PROVIDER, STOCK_API_KEY
from core.log import log


def _download(url):
    r = requests.get(url, timeout=60)
    if r.status_code != 200 or not r.content:
        return None
    ext = "jpg"
    low = url.lower()
    if ".png" in low:
        ext = "png"
    return (r.content, ext)


def search_photo(query):
    if not STOCK_API_KEY:
        return None
    try:
        if STOCK_PROVIDER == "unsplash":
            r = requests.get("https://api.unsplash.com/search/photos",
                             params={"query": query, "per_page": 1, "orientation": "landscape"},
                             headers={"Authorization": "Client-ID " + STOCK_API_KEY}, timeout=40)
            if r.status_code != 200:
                log("stock unsplash kod:", r.status_code); return None
            res = (r.json().get("results") or [])
            if not res:
                return None
            return _download(res[0]["urls"]["regular"])
        # domyslnie Pexels
        r = requests.get("https://api.pexels.com/v1/search",
                         params={"query": query, "per_page": 1, "orientation": "landscape"},
                         headers={"Authorization": STOCK_API_KEY}, timeout=40)
        if r.status_code != 200:
            log("stock pexels kod:", r.status_code); return None
        photos = (r.json().get("photos") or [])
        if not photos:
            return None
        return _download(photos[0]["src"]["large"])
    except Exception as e:
        log("stock blad:", repr(e)); return None
