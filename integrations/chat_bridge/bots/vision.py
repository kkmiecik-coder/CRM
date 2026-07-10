# -*- coding: utf-8 -*-
# Vision: pobiera obrazy klienta z Chatwoota i doklacza do wiadomosci multimodalnej OpenAI.
# Zasada mostka: nigdy nie rzuca — blad pobrania -> obraz pomijany, tura leci jako tekst.
import base64
import requests
from config import CW_TOKEN
from core.log import log

# Limit rozmiaru pobranego obrazu — chroni przed wyslaniem gigantycznego base64 do OpenAI
# (ryzyko kosztu/timeoutu przy chat() timeout=40s).
_MAX_IMG_BYTES = 5 * 1024 * 1024


def to_data_uri(url, timeout=30, formats=None):
    """Pobiera obraz i zwraca 'data:<mime>;base64,<...>' albo None przy bledzie.
    formats: dozwolone formaty (rozszerzenia, np. ('jpg','jpeg','png')) albo None = bez
    ograniczenia. Filtrujemy po mime pobranego pliku (Content-Type) — pewniejsze niz po URL.
    Na OLX czytamy tylko jpg/png; livechat (formats=None) przyjmuje kazdy obraz jak dotad."""
    try:
        r = requests.get(url, headers={"api_access_token": CW_TOKEN or ""}, timeout=timeout)
        if r.status_code != 200:
            log("vision fetch kod:", r.status_code); return None
        if len(r.content) > _MAX_IMG_BYTES:
            log("vision fetch za duzy obraz:", len(r.content)); return None
        mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        if formats:
            subtype = mime.split("/")[-1].lower()  # 'image/jpeg' -> 'jpeg'
            if subtype not in formats:
                log("vision fetch format %s niedozwolony (kanal: %s)" % (subtype, formats)); return None
        b64 = base64.b64encode(r.content).decode("ascii")
        return "data:%s;base64,%s" % (mime, b64)
    except Exception as e:
        log("vision fetch blad:", repr(e)); return None


def attach_images(messages, urls, limit=2, formats=None):
    """Dokleja obrazy (do 'limit') jako NOWA wiadomosc user z content multimodalnym.
    Puste/nieudane pobrania -> messages bez zmian (tekst historii wystarcza).
    formats: ograniczenie formatow przekazywane do to_data_uri (None = bez ograniczenia)."""
    uris = []
    for u in (urls or [])[:limit]:
        du = to_data_uri(u, formats=formats) if formats else to_data_uri(u)
        if du:
            uris.append(du)
    if uris:
        messages.append({"role": "user",
                         "content": [{"type": "image_url", "image_url": {"url": u}} for u in uris]})
    return messages
