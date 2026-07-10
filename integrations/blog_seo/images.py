# -*- coding: utf-8 -*-
# Obrazy artykulu: hero = stock (Pexels/Unsplash) z fallbackiem na AI (gpt-image-1), oraz miniatura
# przez Pillow. Generacja AT jest niezalezna od LLM_PROVIDER (osobny przelacznik IMAGE_PROVIDER).
import io
import base64
import requests
import stock
from PIL import Image
from config import IMAGE_PROVIDER, OPENAI_API_KEY, OPENAI_API_BASE
from core.log import log

_MAX_IMG_BYTES = 6 * 1024 * 1024  # zabezpieczenie: nie zapisujemy gigantycznych plikow


def _openai_image(query):
    # Fallback: generacja obrazu przez OpenAI Images (gpt-image-1). Zwraca (bytes, "png") albo None.
    try:
        r = requests.post(OPENAI_API_BASE + "/images/generations",
                          headers={"Authorization": "Bearer " + (OPENAI_API_KEY or ""),
                                   "Content-Type": "application/json"},
                          json={"model": "gpt-image-1", "prompt": query,
                                "size": "1536x1024", "n": 1}, timeout=120)
        if r.status_code != 200:
            log("openai image kod:", r.status_code, r.text[:200]); return None
        b64 = (((r.json().get("data") or [{}])[0]).get("b64_json"))
        if not b64:
            return None
        data = base64.b64decode(b64)
        return (data, "png", None) if len(data) <= _MAX_IMG_BYTES else None
    except Exception as e:
        log("openai image blad:", repr(e)); return None


def acquire_hero(query):
    # Najpierw stock (domyslny wybor uzytkownika), potem ewentualny fallback AI.
    got = stock.search_photo(query)
    if got and len(got[0]) <= _MAX_IMG_BYTES:
        return got
    if IMAGE_PROVIDER == "openai":
        return _openai_image(query)
    return None


def make_thumb(img_bytes, max_w=600):
    # Skala proporcjonalnie do max_w i zwraca JPEG. Blad -> None.
    try:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        if im.width > max_w:
            h = int(im.height * (max_w / im.width))
            im = im.resize((max_w, h), Image.LANCZOS)
        out = io.BytesIO(); im.save(out, "JPEG", quality=82)
        return out.getvalue()
    except Exception as e:
        log("make_thumb blad:", repr(e)); return None
