# -*- coding: utf-8 -*-
# Centralna konfiguracja automatu blogowego. Wszystkie zmienne z prefiksem BLOG_, czytane przez
# os.environ.get (import nie rzuca przy braku sekretu — blad dopiero przy uzyciu). Sekrety w
# osobnym pliku .env na VPS, poza gitem, dedykowane dla tej integracji (nie CRM/mostek).
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _list(name, default):
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _int_list(name, default):
    # Lista intow z env; nienumeryczne elementy pomijamy, pusta -> default. Import nie moze rzucac.
    out = []
    for x in _list(name, []):
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out or list(default)


# ----- Wybor dostawcy LLM (tekst) -----
LLM_PROVIDER = os.environ.get("BLOG_LLM_PROVIDER", "openai")  # openai | anthropic

# ----- OpenAI (raw HTTP, bez SDK — jak chat_bridge/bots/llm.py) -----
OPENAI_API_KEY  = os.environ.get("BLOG_OPENAI_API_KEY")
OPENAI_API_BASE = os.environ.get("BLOG_OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ.get("BLOG_OPENAI_MODEL", "gpt-5.4")

# ----- Anthropic (raw HTTP, bez SDK — symetria z OpenAI) -----
ANTHROPIC_API_KEY  = os.environ.get("BLOG_ANTHROPIC_API_KEY")
ANTHROPIC_API_BASE = os.environ.get("BLOG_ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")
# Domyslnie najzdolniejszy Opus 4.8; tansze alternatywy: claude-sonnet-5, claude-haiku-4-5.
ANTHROPIC_MODEL    = os.environ.get("BLOG_ANTHROPIC_MODEL", "claude-opus-4-8")
ANTHROPIC_VERSION  = os.environ.get("BLOG_ANTHROPIC_VERSION", "2023-06-01")

MAX_TOKENS = _int("BLOG_MAX_TOKENS", 6000)  # limit dlugosci odpowiedzi (artykul + JSON)

# ----- Obrazy (niezalezne od LLM_PROVIDER) -----
IMAGE_PROVIDER = os.environ.get("BLOG_IMAGE_PROVIDER", "none")   # none | openai (fallback hero)
STOCK_PROVIDER = os.environ.get("BLOG_STOCK_PROVIDER", "pexels") # pexels | unsplash
STOCK_API_KEY  = os.environ.get("BLOG_STOCK_API_KEY")

# ----- Baza PrestaShop (odczyt katalogu + zapis szkicu bloga) -----
PS_DB_HOST = os.environ.get("BLOG_PS_DB_HOST", "127.0.0.1")
PS_DB_NAME = os.environ.get("BLOG_PS_DB_NAME", "presta")
PS_DB_USER = os.environ.get("BLOG_PS_DB_USER")
PS_DB_PASS = os.environ.get("BLOG_PS_DB_PASS")
PS_PREFIX  = os.environ.get("BLOG_PS_PREFIX", "ps_")
PS_SHOP_ID = _int("BLOG_PS_SHOP_ID", 1)
PS_LANG_IDS = _int_list("BLOG_PS_LANG_IDS", [1, 2])   # 1=PL (aktywny), 2=EN
PS_AUTHOR_ID = _int("BLOG_PS_AUTHOR_ID", 23)                # id_employee autora szkicu
PS_DEFAULT_CATEGORY_ID = _int("BLOG_PS_DEFAULT_CATEGORY_ID", 4)  # 4=Edukacja (fallback)

# ----- Obrazy na dysku sklepu (moduł ETS Simple Blog) -----
PS_IMG_DIR = os.environ.get("BLOG_PS_IMG_DIR",
                            "/home/woodpower/htdocs/woodpower.pl/img/ets_blog/post")
PS_IMG_URL_BASE = os.environ.get("BLOG_PS_IMG_URL_BASE",
                                 "https://woodpower.pl/img/ets_blog/post")

# ----- Sklep / linkowanie -----
SHOP_BASE_URL = os.environ.get("BLOG_SHOP_BASE_URL", "https://woodpower.pl")
LINK_CLASS    = os.environ.get("BLOG_LINK_CLASS", "kontakt-link-descr")

# ----- Stan lokalny -----
DB_PATH    = os.environ.get("BLOG_DB_PATH", "/data/blog_seo.db")
MIN_BACKLOG = _int("BLOG_MIN_BACKLOG", 5)  # ponizej tego progu auto-uzupelniamy backlog

# Tematy startowe (seed) — uzywane, gdy backlog pusty, zanim LLM dopisze wlasne.
TOPIC_SEEDS = _list("BLOG_TOPIC_SEEDS", [
    "Jak dbać o blat dębowy w kuchni",
    "Czym różni się blat lity od mikrowczepu",
    "Na co uważać przy drewnianym blacie w łazience",
])

# ----- Sygnaly popytu (wybor tematow bloga) -----
# GSC = glowne zrodlo realnego popytu; domyslnie OFF (wymaga konta uslugowego Google Cloud
# z dostepem do property w Search Console). Autocomplete + Trends = darmowa warstwa swiezych fraz.
GSC_ENABLED          = _int("BLOG_GSC_ENABLED", 0)
GSC_SITE_URL         = os.environ.get("BLOG_GSC_SITE_URL", "sc-domain:woodpower.pl")
GSC_CREDENTIALS_JSON = os.environ.get("BLOG_GSC_CREDENTIALS_JSON")  # sciezka do klucza konta uslugowego
GSC_DAYS             = _int("BLOG_GSC_DAYS", 28)             # okno danych (dni wstecz)
GSC_MIN_IMPRESSIONS  = _int("BLOG_GSC_MIN_IMPRESSIONS", 20)  # prog wyswietlen (odsiew szumu)
GSC_POS_MIN          = _int("BLOG_GSC_POS_MIN", 6)           # striking distance: dolna granica pozycji
GSC_POS_MAX          = _int("BLOG_GSC_POS_MAX", 20)          # ... i gorna (tam awans na 1. strone jest realny)
TRENDS_ENABLED       = _int("BLOG_TRENDS_ENABLED", 1)
SUGGEST_ENABLED      = _int("BLOG_SUGGEST_ENABLED", 1)
SIGNALS_GEO          = os.environ.get("BLOG_SIGNALS_GEO", "PL")
SIGNALS_HL           = os.environ.get("BLOG_SIGNALS_HL", "pl")
