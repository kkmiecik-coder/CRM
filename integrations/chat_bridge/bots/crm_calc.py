# -*- coding: utf-8 -*-
# Klient API kalkulatora CRM dla bota wyceniajacego: katalog /options (cache),
# mapowanie danych PL na parametry API, wywolania /calculate, /clients/find-or-create, /quotes.
# Zasada: bledy API nie rzucaja do klienta — zwracamy struktury {ok, ...} i logujemy.
import time
import unicodedata
import re
import requests
from config import CRM_API_BASE, CRM_BOT_API_KEY, BOT_QUOTE_CLIENT_TYPE
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
    """Czy finishing_id istnieje w katalogu /options. Bledne wpisy katalogu sa omijane."""
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return False
    # Iterujemy po wpisach, przeskakujac te z niepoprawnym id (bledy API nie rzucaja do klienta)
    for o in (options.get("finishing_options") or []):
        try:
            if int(o.get("id")) == fid:
                return True
        except (TypeError, ValueError):
            # Zepsuty wpis w katalogu — pomijamy i kontynuujemy
            continue
    return False


def _finish_type(wykonczenie):
    a = _ascii_low(wykonczenie)
    for klucz, val in (("surow", "Surowe"), ("olej", "Olejowane"), ("lakier", "Lakierowane")):
        if klucz in a:
            return val
    return None


def _find_finishing_option(fid, options):
    """Wpis finishing_options po id (bledny wpis katalogu -> pomijamy, nie rzucamy)."""
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return None
    for o in (options.get("finishing_options") or []):
        try:
            if int(o.get("id")) == fid:
                return o
        except (TypeError, ValueError):
            continue
    return None


def finishing_full_path(fid, options):
    """Pelna sciezka wykonczenia (np. 'Lakierowane/Barwne/BRUNAT 22-15') dla finishing_id z katalogu,
    albo '' gdy brak. Sluzy do pokazania wybranego koloru w podsumowaniu."""
    opt = _find_finishing_option(fid, options)
    return str((opt or {}).get("full_path") or "")


def _num(v):
    """String/float z LLM -> float; None gdy nie liczba."""
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


# --- Krawedzie (tryb advanced): walidacja + rozwiniecie "wszystkie" ---
# Litery wg EDGE_DEFINITIONS kalkulatora: A-D gora, E-H dol, N1-N4 narozniki, KG/KD obwod (okragly).
EDGE_LETTERS = {"A", "B", "C", "D", "E", "F", "G", "H", "N1", "N2", "N3", "N4", "KG", "KD"}
# Typy krawedzi z /options: sharp (ostra), chamfer (fazowanie), round (zaokraglenie, np. R4).
_EDGE_TYPE_ALIAS = {
    "sharp": "sharp", "ostra": "sharp", "ostre": "sharp", "prosta": "sharp",
    "chamfer": "chamfer", "faza": "chamfer", "fazowanie": "chamfer", "fazowane": "chamfer", "fazowana": "chamfer",
    "round": "round", "zaokraglenie": "round", "zaokraglone": "round", "zaokraglona": "round", "r": "round",
}
_ALL_TOP = ["A", "B", "C", "D"]   # "wszystkie/kazda krawedz" prostokata = 4 krawedzie gorne
_WSZYSTKIE = {"WSZYSTKIE", "ALL", "*", "KAZDA", "KAŻDA", "OBWOD", "OBWÓD"}


def _norm_edge_type(v):
    """PL/EN opis typu krawedzi -> 'sharp'|'chamfer'|'round' albo None."""
    a = _ascii_low(v)
    if a in _EDGE_TYPE_ALIAS:
        return _EDGE_TYPE_ALIAS[a]
    for k, val in _EDGE_TYPE_ALIAS.items():
        if k in a:
            return val
    return None


_R_DEFAULT = 5     # domyslny promien zaokraglenia (mm) — jak w UI kalkulatora
_KAT_DEFAULT = 45  # domyslny kat fazowania (stopnie)


def _num_int(v, default=None):
    """Liczba calkowita z 'R3'/'3 mm'/3 albo default; None gdy brak i default=None."""
    m = re.search(r"\d+", str(v if v is not None else ""))
    return int(m.group(0)) if m else default


def normalize_edges(raw):
    """Lista {litera,typ,[r,kat]} z LLM -> znormalizowana lista {litera,typ,r_value,angle_value}:
    waliduje litery/typy, rozwija 'wszystkie/kazda' -> A,B,C,D, dolacza promien (round) lub kat
    (chamfer). Odrzuca nieznane. Dedup po (litera,typ,r_value,angle_value). Zwraca [] gdy nic
    sensownego (nigdy nie rzuca — dane z LLM sa niepewne)."""
    out, seen = [], set()
    for e in (raw or []):
        if not isinstance(e, dict):
            continue
        lit = str(e.get("litera") or e.get("letter") or "").strip().upper()
        typ = _norm_edge_type(e.get("typ") or e.get("type"))
        if not typ:
            continue
        if typ == "sharp":
            # Ostra = BRAK obrobki: nie dodajemy jej do listy (inaczej w wycenie 'sharp Rnull').
            # Intencje 'ostre'/usun obrobke wykrywa osobno raw_ma_sharp() -> czysci krawedzie.
            continue
        r_raw = e.get("r") if e.get("r") is not None else e.get("r_value")
        kat_raw = e.get("kat") if e.get("kat") is not None else e.get("angle_value")
        if typ == "round":
            r_value, angle_value = _num_int(r_raw, _R_DEFAULT), None
        else:  # chamfer
            r_value, angle_value = None, _num_int(kat_raw, _KAT_DEFAULT)
        litery = _ALL_TOP if lit in _WSZYSTKIE else [lit]
        for L in litery:
            klucz = (L, typ, r_value, angle_value)
            if L in EDGE_LETTERS and klucz not in seen:
                seen.add(klucz)
                out.append({"litera": L, "typ": typ, "r_value": r_value, "angle_value": angle_value})
    return out


def raw_ma_sharp(raw):
    """True gdy LLM podal w krawedziach JAWNIE typ 'sharp' (ostra) — sygnal, ze klient chce
    krawedzie bez obrobki / usunac wczesniejsze zaokraglenia (a nie tylko ich nie zmienia)."""
    for e in (raw or []):
        if isinstance(e, dict) and _norm_edge_type(e.get("typ") or e.get("type")) == "sharp":
            return True
    return False


def build_products(pozycje, options):
    """Mapuje pozycje bota (PL) na produkty API /calculate. Zwraca (products, braki),
    gdzie braki = [(pozycja, powod_pl)] dla pozycji, ktorych nie da sie zmapowac."""
    products = []
    braki = []
    for i, poz in enumerate(pozycje or [], 1):
        code = variant_code(poz.get("gatunek"), poz.get("technologia"), poz.get("klasa"))
        if not code:
            braki.append((poz, "nie rozpoznano wariantu drewna (gatunek/technologia/klasa)"))
            continue
        ftype = _finish_type(poz.get("wykonczenie"))
        if ftype is None:
            braki.append((poz, "nie rozpoznano wykończenia"))
            continue
        prod = {
            "index": i,
            "length": _num(poz.get("dlugosc")),
            "width": _num(poz.get("szerokosc")),
            "thickness": _num(poz.get("grubosc")),
            "quantity": int(_num(poz.get("ilosc")) or 1),
            "selected_variant": code,
            "shape": "rectangular",
            "finishing_type": ftype,
        }
        if ftype != "Surowe":
            fid = poz.get("finishing_id")
            if not valid_finishing_id(fid, options):
                braki.append((poz, "nie rozpoznano wykończenia (finishing_id spoza katalogu)"))
                continue
            prod["finishing_option_id"] = int(fid)
            if ftype == "Lakierowane":
                # calculate_finishing (CRM) liczy 0 dla Lakierowane bez finishing_gloss_level —
                # bez konkretnego wariantu (polysku) z cena wycena wyszlaby zerowa.
                opt = _find_finishing_option(fid, options)
                if not opt or not opt.get("price_netto"):
                    braki.append((poz, "wykończenie lakierowane wymaga wyboru konkretnego "
                                       "wariantu (połysk) z ceną"))
                    continue
                prod["finishing_gloss_level"] = str(opt.get("full_path") or "z katalogu")
        # Krawedzie (tryb advanced): litera->letter, typ->type. Pozycja bez krawedzi -> brak edges.
        edges = normalize_edges(poz.get("edges"))
        if edges:
            prod["edges"] = [{"letter": e["litera"], "type": e["typ"],
                              "r_value": e["r_value"], "angle_value": e["angle_value"]}
                             for e in edges]
            prod["edges_mode"] = "advanced"
        products.append(prod)
    return products, braki


def _send(method, path, body):
    """Zadanie JSON (POST/PUT) do CRM API; zwraca JSON albo {ok:False} przy bledzie transportu.
    Uzywa requests.post/requests.put (przez getattr), zeby testy mogly je mockowac."""
    try:
        r = getattr(requests, method.lower())(CRM_API_BASE + path, headers=_headers(),
                                               json=body, timeout=30)
        if r.status_code != 200:
            log("crm_calc %s %s kod:" % (method, path), r.status_code, r.text[:200])
            return {"ok": False, "errors": [{"field": None, "code": "HTTP_%s" % r.status_code,
                                             "message": "Błąd połączenia z wyceną."}]}
        return r.json() or {"ok": False, "errors": []}
    except Exception as e:
        log("crm_calc %s %s blad:" % (method, path), repr(e))
        return {"ok": False, "errors": [{"field": None, "code": "TRANSPORT",
                                         "message": "Błąd połączenia z wyceną."}]}


def _post(path, body):
    return _send("POST", path, body)


def calculate(pozycje, options):
    """POST /api/bot/calculate — cena bez zapisu. Zwraca surowy JSON kontraktu bota."""
    products, braki = build_products(pozycje, options)
    if braki:
        return {"ok": False, "missing_fields": [], "errors": [],
                "braki_mapowania": [{"powod": powod} for _, powod in braki]}
    body = {"products": products, "client_type": BOT_QUOTE_CLIENT_TYPE}
    return _post("/api/bot/calculate", body)


def find_or_create_client(email, phone, name):
    """POST /api/bot/clients/find-or-create."""
    return _post("/api/bot/clients/find-or-create",
                 {"email": email or None, "phone": phone or None, "name": name or None})


def create_quote(pozycje, options, client_id, notes=""):
    """POST /api/bot/quotes — pelna wycena + publiczny link. Zwraca m.in. edit_uuid do aktualizacji."""
    products, braki = build_products(pozycje, options)
    if braki:
        return {"ok": False, "errors": [{"field": None, "code": "MAP",
                                         "message": powod} for _, powod in braki]}
    body = {"products": products, "client_id": client_id,
            "quote_client_type": BOT_QUOTE_CLIENT_TYPE, "notes": notes}
    return _post("/api/bot/quotes", body)


def shipping_quote(pozycje, postcode, options=None):
    """POST /api/bot/shipping-quote — szacuje wysylke (najtanszy kurier +30%) dla pozycji i kodu
    pocztowego odbiorcy. Zwraca surowy JSON kontraktu ({ok, carriers, carrier_name, ...}).
    Braki mapowania -> {ok:False} bez wolania API."""
    if options is None:
        options = get_options()
    products, braki = build_products(pozycje, options)
    if braki:
        return {"ok": False, "errors": [{"field": None, "code": "MAP",
                                         "message": powod} for _, powod in braki]}
    return _post("/api/bot/shipping-quote",
                 {"products": products, "receiver_postcode": postcode})


def update_quote(edit_uuid, pozycje, options, notes="",
                 courier_name=None, shipping_netto=None, shipping_brutto=None):
    """PUT /api/bot/quotes/<edit_uuid> — aktualizuje istniejaca wycene (dodanie/zmiana pozycji)
    zamiast tworzyc nowa. Opcjonalnie dopisuje kuriera + koszt wysylki (courier_name podany).
    Zwraca ten sam numer wyceny + publiczny link.
    INWARIANT: BOT_QUOTE_CLIENT_TYPE MUSI byc poprawna grupa z /options — inaczej update
    (jak i create/calculate) zwroci {ok:False} (walidacja client_type po stronie CRM)."""
    products, braki = build_products(pozycje, options)
    if braki:
        return {"ok": False, "errors": [{"field": None, "code": "MAP",
                                         "message": powod} for _, powod in braki]}
    body = {"products": products, "quote_client_type": BOT_QUOTE_CLIENT_TYPE, "notes": notes}
    if courier_name:
        body["courier_name"] = courier_name
        body["shipping_netto"] = shipping_netto
        body["shipping_brutto"] = shipping_brutto
    return _send("PUT", "/api/bot/quotes/" + str(edit_uuid), body)
