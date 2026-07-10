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
            got = _download(res[0]["urls"]["regular"])
            if not got:
                return None
            u = res[0].get("user") or {}
            attr = {"photographer": u.get("name") or "",
                    "photographer_url": ((u.get("links") or {}).get("html")) or "",
                    "photo_url": ((res[0].get("links") or {}).get("html")) or "",
                    "source": "Unsplash"}
            return (got[0], got[1], attr)
        # domyslnie Pexels
        r = requests.get("https://api.pexels.com/v1/search",
                         params={"query": query, "per_page": 1, "orientation": "landscape"},
                         headers={"Authorization": STOCK_API_KEY}, timeout=40)
        if r.status_code != 200:
            log("stock pexels kod:", r.status_code); return None
        photos = (r.json().get("photos") or [])
        if not photos:
            return None
        got = _download(photos[0]["src"]["large"])
        if not got:
            return None
        attr = {"photographer": photos[0].get("photographer") or "",
                "photographer_url": photos[0].get("photographer_url") or "",
                "photo_url": photos[0].get("url") or "",
                "source": "Pexels"}
        return (got[0], got[1], attr)
    except Exception as e:
        log("stock blad:", repr(e)); return None
