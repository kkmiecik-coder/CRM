# -*- coding: utf-8 -*-
# Wspolna autoryzacja Allegro: cache tokenu z lockiem, odswiezanie po refresh_token,
# autentykowany GET (msg + dyskusje), oraz wymiana authorization_code (z /allegro/callback).
import time
import threading
import requests
from config import (ALLEGRO_TOKEN_URL, ALLEGRO_API, ALLEGRO_REDIRECT,
                    ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET,
                    ALLEGRO_ACCEPT, ALLEGRO_BETA_ACCEPT)
from core.log import log
from core.db import meta_get, meta_set

_alg_token = {"access": None, "exp": 0}
_alock = threading.Lock()


def get_allegro_token(force=False):
    with _alock:
        now = time.time()
        if not force and _alg_token["access"] and now < _alg_token["exp"] - 60:
            return _alg_token["access"]
        rt = meta_get("allegro_refresh_token")
        if not rt:
            raise RuntimeError("Allegro: brak refresh tokenu (autoryzacja niewykonana)")
        r = requests.post(ALLEGRO_TOKEN_URL,
                          data={"grant_type": "refresh_token", "refresh_token": rt, "redirect_uri": ALLEGRO_REDIRECT},
                          auth=(ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET), timeout=20)
        r.raise_for_status()
        t = r.json()
        _alg_token["access"] = t["access_token"]
        _alg_token["exp"] = now + int(t.get("expires_in", 3600))
        if t.get("refresh_token"):
            meta_set("allegro_refresh_token", t["refresh_token"])
        log("Allegro access token odswiezony")
        return _alg_token["access"]


def allegro_get(path, beta=False):
    at = get_allegro_token()
    acc = ALLEGRO_BETA_ACCEPT if beta else ALLEGRO_ACCEPT
    h = {"Authorization": "Bearer " + at, "Accept": acc}
    r = requests.get(ALLEGRO_API + path, headers=h, timeout=25)
    if r.status_code == 401:
        h["Authorization"] = "Bearer " + get_allegro_token(force=True)
        r = requests.get(ALLEGRO_API + path, headers=h, timeout=25)
    r.raise_for_status()
    return r.json()


def exchange_authorization_code(code):
    """Wymienia authorization_code na tokeny, zapisuje refresh w meta, ustawia cache. Zwraca payload."""
    r = requests.post(ALLEGRO_TOKEN_URL,
                      data={"grant_type": "authorization_code", "code": code, "redirect_uri": ALLEGRO_REDIRECT},
                      auth=(ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET), timeout=20)
    r.raise_for_status()
    t = r.json()
    meta_set("allegro_refresh_token", t["refresh_token"])
    _alg_token["access"] = t["access_token"]
    _alg_token["exp"] = time.time() + int(t.get("expires_in", 3600))
    log("Allegro: refresh token zapisany (autoryzacja OK)")
    return t
