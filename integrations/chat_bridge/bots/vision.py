# -*- coding: utf-8 -*-
# Vision: pobiera obrazy klienta z Chatwoota i doklacza do wiadomosci multimodalnej OpenAI.
# Zasada mostka: nigdy nie rzuca — blad pobrania -> obraz pomijany, tura leci jako tekst.
import base64
import requests
from config import CW_TOKEN
from core.log import log


def to_data_uri(url, timeout=30):
    """Pobiera obraz i zwraca 'data:<mime>;base64,<...>' albo None przy bledzie."""
    try:
        r = requests.get(url, headers={"api_access_token": CW_TOKEN or ""}, timeout=timeout)
        if r.status_code != 200:
            log("vision fetch kod:", r.status_code); return None
        mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        b64 = base64.b64encode(r.content).decode("ascii")
        return "data:%s;base64,%s" % (mime, b64)
    except Exception as e:
        log("vision fetch blad:", repr(e)); return None


def attach_images(messages, urls, limit=2):
    """Dokleja obrazy (do 'limit') jako NOWA wiadomosc user z content multimodalnym.
    Puste/nieudane pobrania -> messages bez zmian (tekst historii wystarcza)."""
    uris = []
    for u in (urls or [])[:limit]:
        du = to_data_uri(u)
        if du:
            uris.append(du)
    if uris:
        messages.append({"role": "user",
                         "content": [{"type": "image_url", "image_url": {"url": u}} for u in uris]})
    return messages
