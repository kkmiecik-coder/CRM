# -*- coding: utf-8 -*-
# Klient API kalkulatora CRM dla bota wyceniajacego: katalog /options (cache),
# mapowanie danych PL na parametry API, wywolania /calculate, /clients/find-or-create, /quotes.
# Zasada: bledy API nie rzucaja do klienta — zwracamy struktury {ok, ...} i logujemy.
import time
import unicodedata
import re
import requests
from config import CRM_API_BASE, CRM_BOT_API_KEY
from core.log import log

_OPTIONS_TTL = 600.0
_opt_cache = {"data": None, "ts": 0.0}

# Lokalna kopia mapy wariantow (zsynchronizowana z modules/calculator/services/pricing_service.py).
VARIANT_CODES = {
    "dab-lity-ab":  {"species": "Dąb", "technology": "Lity", "wood_class": "A/B"},
    "dab-lity-bb":  {"species": "Dąb", "technology": "Lity", "wood_class": "B/B"},
    "dab-micro-ab": {"species": "Dąb", "technology": "Mikrowczep", "wood_class": "A/B"},
    "dab-micro-bb": {"species": "Dąb", "technology": "Mikrowczep", "wood_class": "B/B"},
    "jes-lity-ab":  {"species": "Jesion", "technology": "Lity", "wood_class": "A/B"},
    "jes-micro-ab": {"species": "Jesion", "technology": "Mikrowczep", "wood_class": "A/B"},
    "buk-lity-ab":  {"species": "Buk", "technology": "Lity", "wood_class": "A/B"},
    "buk-micro-ab": {"species": "Buk", "technology": "Mikrowczep", "wood_class": "A/B"},
}


def _headers():
    return {"X-Bot-Api-Key": CRM_BOT_API_KEY or "", "Content-Type": "application/json"}


def _reset_cache():
    """Reset cache /options (uzywane w testach)."""
    _opt_cache["data"] = None
    _opt_cache["ts"] = 0.0


def get_options(force=False):
    """Katalog z /api/bot/options z cache TTL. {} przy bledzie (bot wtedy dopyta/handoff)."""
    now = time.time()
    if not force and _opt_cache["data"] is not None and (now - _opt_cache["ts"]) < _OPTIONS_TTL:
        return _opt_cache["data"]
    try:
        r = requests.get(CRM_API_BASE + "/api/bot/options", headers=_headers(), timeout=25)
        if r.status_code != 200:
            log("crm_calc /options kod:", r.status_code, r.text[:200]); return {}
        data = r.json() or {}
    except Exception as e:
        log("crm_calc /options blad:", repr(e)); return {}
    _opt_cache["data"] = data
    _opt_cache["ts"] = now
    return data


def _ascii_low(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()


def _norm_species(v):
    a = _ascii_low(v)
    if "dab" in a: return "Dąb"
    if "jesion" in a: return "Jesion"
    if "buk" in a: return "Buk"
    return None


def _norm_tech(v):
    a = _ascii_low(v)
    if "mikro" in a or "wczep" in a: return "Mikrowczep"
    if "lit" in a: return "Lity"
    return None


def _norm_class(v):
    a = _ascii_low(v)
    ma = bool(re.search(r"a\s*/?\s*b", a))
    mb = bool(re.search(r"b\s*/?\s*b", a))
    if ma and not mb: return "A/B"
    if mb and not ma: return "B/B"
    return None   # niejednoznaczne / brak -> nie zgadujemy


def variant_code(gatunek, technologia, klasa):
    """PL (gatunek, technologia, klasa) -> kod wariantu z VARIANT_CODES albo None."""
    sp, te, kl = _norm_species(gatunek), _norm_tech(technologia), _norm_class(klasa)
    if not (sp and te and kl):
        return None
    for code, cfg in VARIANT_CODES.items():
        if cfg["species"] == sp and cfg["technology"] == te and cfg["wood_class"] == kl:
            return code
    return None


def valid_finishing_id(fid, options):
    """Czy finishing_id istnieje w katalogu /options."""
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return False
    return any(int(o.get("id")) == fid for o in (options.get("finishing_options") or [])
               if o.get("id") is not None)
