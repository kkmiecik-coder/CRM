# -*- coding: utf-8 -*-
# Centralna konfiguracja mostka — wszystkie zmienne srodowiskowe i stale w jednym miejscu.
import os

# ----- OLX -----
OLX_CLIENT_ID     = os.environ["OLX_CLIENT_ID"]
OLX_CLIENT_SECRET = os.environ["OLX_CLIENT_SECRET"]
OLX_REFRESH_TOKEN = os.environ["OLX_REFRESH_TOKEN"]
OLX_TOKEN_URL     = os.environ.get("OLX_TOKEN_URL", "https://www.olx.pl/api/open/oauth/token")
OLX_API_BASE      = os.environ.get("OLX_API_BASE", "https://www.olx.pl/api/partner")
POLL_INTERVAL     = int(os.environ.get("OLX_POLL_INTERVAL", "25"))

# ----- Allegro -----
ALLEGRO_CLIENT_ID     = os.environ.get("ALLEGRO_CLIENT_ID")
ALLEGRO_CLIENT_SECRET = os.environ.get("ALLEGRO_CLIENT_SECRET")
ALLEGRO_AUTH_URL      = "https://allegro.pl/auth/oauth/authorize"
ALLEGRO_TOKEN_URL     = "https://allegro.pl/auth/oauth/token"
ALLEGRO_API           = "https://api.allegro.pl"
ALLEGRO_REDIRECT      = os.environ.get("ALLEGRO_REDIRECT_URI", "https://chatbridge.woodpower.pl/allegro/callback")
ALLEGRO_ACCEPT        = "application/vnd.allegro.public.v1+json"
ALLEGRO_BETA_ACCEPT   = "application/vnd.allegro.beta.v1+json"

# ----- Chatwoot -----
CW_BASE     = os.environ.get("CHATWOOT_BASE", "http://rails:3000")
CW_ACC      = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
CW_OLX_INBOX = os.environ.get("CHATWOOT_OLX_INBOX_ID")
CW_ALLEGRO_MSG_INBOX = os.environ.get("CHATWOOT_ALLEGRO_MSG_INBOX_ID", "4")
CW_ALLEGRO_DISPUTE_INBOX = os.environ.get("CHATWOOT_ALLEGRO_DISPUTE_INBOX_ID", "6")
CW_TOKEN    = os.environ.get("CHATWOOT_API_TOKEN")
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN")
BOT_CW_AGENT_TOKEN     = os.environ.get("BOT_CW_AGENT_TOKEN")      # access_token Agent Bota (do handoffu)
BOT_AGENT_WEBHOOK_TOKEN = os.environ.get("BOT_AGENT_WEBHOOK_TOKEN") # token w URL webhooka /agent-bot

# ----- BaseLinker -----
BASELINKER_TOKEN = os.environ.get("BASELINKER_TOKEN")
BASE_PANEL_TOKEN = os.environ.get("BASE_PANEL_TOKEN")
BL_API = "https://api.baselinker.com/connector.php"

DB_PATH = os.environ.get("BRIDGE_DB", "/data/bridge.db")
MAX_ATTEMPTS = 5

# ----- Boty AI (podpowiadacze) -----
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY")
OPENAI_API_BASE     = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
BOT_CHAT_MODEL      = os.environ.get("BOT_OPENAI_MODEL", "gpt-5.4-nano")
BOT_EMBEDDING_MODEL = os.environ.get("BOT_EMBEDDING_MODEL", "text-embedding-3-small")
BOT_RETRIEVAL_K     = int(os.environ.get("BOT_RETRIEVAL_K", "5"))
BOT_HELP_CENTER_SLUG = os.environ.get("BOT_HELP_CENTER_SLUG", "")
BOT_HISTORY_LIMIT   = int(os.environ.get("BOT_HISTORY_LIMIT", "12"))
BOT_INDEX_INTERVAL  = int(os.environ.get("BOT_INDEX_INTERVAL", "600"))
BOT_MAX_ATTEMPTS    = int(os.environ.get("BOT_MAX_ATTEMPTS", "3"))
BOT_MAX_TOKENS      = int(os.environ.get("BOT_MAX_TOKENS", "4000"))  # obejmuje tokeny rozumowania GPT-5 — podniesione (PL-04), by JSON wielu pozycji sie nie urwal
# Parametry specyficzne dla modeli GPT-5 (ignorowane dla starszych, np. gpt-4.1-mini)
BOT_REASONING_EFFORT = os.environ.get("BOT_REASONING_EFFORT", "low")  # gpt-5.4: none|low|medium|high|xhigh (NIE minimal) — „low" = lekkie rozumowanie, dobra jakosc/koszt
BOT_VERBOSITY        = os.environ.get("BOT_VERBOSITY", "low")             # low|medium|high — krotkie, konkretne odpowiedzi na czacie

# ----- Bot live-chat (konwersacyjny, osobna encja "WoodPower Chat") -----
BOT_LIVE_CW_AGENT_TOKEN      = os.environ.get("BOT_LIVE_CW_AGENT_TOKEN")       # access_token live-bota (odpowiedzi + handoff)
BOT_LIVE_AGENT_WEBHOOK_TOKEN = os.environ.get("BOT_LIVE_AGENT_WEBHOOK_TOKEN")  # token w URL webhooka /agent-bot-live
BOT_LIVE_MAX_TURNS           = int(os.environ.get("BOT_LIVE_MAX_TURNS", "30"))  # bezpiecznik D: max tur bota przed wymuszonym handoffem (podniesione z 10 — dluzsze rozmowy informacyjne + potwierdzenie)

# Katalog zdjec wysylanych przez bota (assety w repo; nadpisywalny env).
BOT_IMAGES_DIR = os.environ.get(
    "BOT_IMAGES_DIR", os.path.join(os.path.dirname(__file__), "assets", "bot_images"))

# ----- Sweeper pending (samonaprawa rozmow bez odpowiedzi bota) -----
SWEEP_INTERVAL    = int(os.environ.get("SWEEP_INTERVAL", "120"))    # sekundy miedzy przejsciami; <=0 = wylaczony
SWEEP_PENDING_AGE = int(os.environ.get("SWEEP_PENDING_AGE", "600")) # min. wiek ostatniej wiadomosci klienta (s)

# ----- Bot wyceniajacy „Asystent AI v1" (live chat, osobna encja od live-bota) -----
# Klient CRM API kalkulatora (te same endpointy co UI, auth naglowkiem X-Bot-Api-Key).
CRM_API_BASE   = os.environ.get("CRM_API_BASE", "https://crm.woodpower.pl").rstrip("/")
CRM_BOT_API_KEY = os.environ.get("CRM_BOT_API_KEY")   # = BOT_API_KEY z config/core.json CRM
# Grupa cenowa na sztywno (NIE z LLM) — musi pasowac do client_types z /api/bot/options.
BOT_QUOTE_CLIENT_TYPE = os.environ.get("BOT_QUOTE_CLIENT_TYPE")
# Tokeny Agent Bota „Asystent AI v1".
BOT_QUOTE_CW_AGENT_TOKEN      = os.environ.get("BOT_QUOTE_CW_AGENT_TOKEN")       # access_token (odpowiedzi + handoff)
BOT_QUOTE_AGENT_WEBHOOK_TOKEN = os.environ.get("BOT_QUOTE_AGENT_WEBHOOK_TOKEN")  # token w URL webhooka /agent-bot-quote
BOT_QUOTE_MAX_TURNS           = int(os.environ.get("BOT_QUOTE_MAX_TURNS", "30")) # bezpiecznik D
# Okno ciszy (debounce) quote-bota: sekundy oczekiwania na kolejne wiadomosci klienta zanim bot
# odpowie. Kazda nowa wiadomosc tej samej rozmowy przesuwa termin (sliding) i doklejana jest do
# jednej tury -> jedna odpowiedz na serie wiadomosci zamiast wielu. 0 = bez opoznienia.
BOT_DEBOUNCE_SECONDS          = int(os.environ.get("BOT_DEBOUNCE_SECONDS", "10"))
# Kanaly WYZWALANE Z MOSTU, dla ktorych quote-bot prowadzi rozmowe (kill-switch bez zmiany kodu;
# zmiana wymaga recreate kontenera mostu przez bridge-deploy.sh — nie pushu kodu). Dzis znaczenie
# ma TYLKO obecnosc "olx" (dodanie wlacza obsluge OLX). UWAGA: livechat/Messenger NIE sa sterowane
# tym configiem — ich obsluguje twardy guard webhooka (_process_quotebot), niezaleznie od tej listy.
BOT_QUOTE_PERSONAS = (set(x.strip() for x in os.environ.get("BOT_QUOTE_PERSONAS", "livechat").split(",") if x.strip())
                      or {"livechat"})

# Persony, ktore pisza PRYWATNA NOTATKE zamiast wiadomosci do klienta (OLX/Allegro).
# Kill-switch trybu notatki: zdjecie persony z listy przywraca wysylke do klienta, dodanie
# wycisza kanal. Persona 'quote' (livechat/Messenger) NIE podlega — Debus tam rozmawia.
# UWAGA: pusta wartosc ("") = zaden kanal nie pisze notatek; swiadomie NIE ma tu fallbacku
# na domyslna liste, bo cichy powrot do wysylki do klienta bylby grozniejszy niz brak notatek.
BOT_QUOTE_NOTE_PERSONAS = set(
    x.strip() for x in os.environ.get("BOT_QUOTE_NOTE_PERSONAS", "quote_olx,quote_allegro").split(",")
    if x.strip()
)

# ----- Sweeper "goracy lead" (rozmowa oddana po cenie bota, klient milczy — LS-04) -----
HOT_LEAD_SWEEP_INTERVAL = int(os.environ.get("HOT_LEAD_SWEEP_INTERVAL", "1800"))  # sekundy; <=0 = wylaczony
HOT_LEAD_SILENCE_HOURS  = float(os.environ.get("HOT_LEAD_SILENCE_HOURS", "24"))

# Godziny pracy konsultantow (Europe/Warsaw) — poza nimi handoff dostaje inny komunikat
# (z prosba o telefon zamiast obietnicy natychmiastowej odpowiedzi) — LS-10.
BOT_BUSINESS_HOURS = os.environ.get("BOT_BUSINESS_HOURS", "08:00-16:00")

# ----- Odpornosc quote_workera na awarie LLM/CRM (TO-04) -----
# Filtr pustych fragmentow + fallback na wartosc domyslna — pusty BOT_BACKOFF_TIERS="" (np. zla
# zmienna srodowiskowa w deployu) nie moze wywalic calego mostka juz przy imporcie configu.
BOT_BACKOFF_TIERS = ([int(x) for x in os.environ.get("BOT_BACKOFF_TIERS", "30,120,300").split(",") if x.strip()]
                     or [30, 120, 300])
BOT_CIRCUIT_THRESHOLD = int(os.environ.get("BOT_CIRCUIT_THRESHOLD", "5"))   # kolejnych bledow -> pauza
BOT_CIRCUIT_COOLDOWN  = int(os.environ.get("BOT_CIRCUIT_COOLDOWN", "120"))  # sekundy pauzy kolejki

# ----- Bot sprzedazowy "Debus Pro" (Agents SDK, osobna encja od quote-bota) -----
# Token uzyty explicite w bots_pro.stan.handoff/podsumowanie.wyslij — domyslny cw_bot_handoff
# siega po token bota-podpowiadacza, wiec Pro potrzebuje wlasnego, jawnie podawanego.
BOT_PRO_CW_AGENT_TOKEN = os.environ.get("BOT_PRO_CW_AGENT_TOKEN")
# Token w URL webhooka /agent-bot-pro. Guard startowy w bridge.py przerywa uruchomienie
# procesu, gdy BOT_PRO_INBOXES jest niepuste, a tego tokenu brak (patrz bridge.py) —
# inaczej weryfikacja w webhooks.py jest warunkowa (`if TOKEN and ...`) i webhook stoi otworem.
BOT_PRO_AGENT_WEBHOOK_TOKEN = os.environ.get("BOT_PRO_AGENT_WEBHOOK_TOKEN")
# Bezpiecznik D (jak BOT_LIVE_MAX_TURNS/BOT_QUOTE_MAX_TURNS): max krokow Runnera w JEDNYM
# wywolaniu Runner.run_sync (petla narzedzie->model wewnatrz jednej tury), zeby zapetlone
# wywolania narzedzi nie chodzily w nieskonczonosc. PRZEMIANOWANE z BOT_PRO_MAX_TURNS (Task 8,
# B2 code review) — ta nazwa myliła się z BEZPIECZNIKIEM DŁUGOŚCI ROZMOWY (BOT_PRO_MAX_TURNS
# poniżej), zupełnie innym pojęciem: to jest limit iteracji narzędzie->model WEWNĄTRZ JEDNEJ
# tury, tamto jest limit liczby TUR całej rozmowy klient<->bot. Nazwa nie zmieniona od
# poprzedniego zadania (Task 6/7) NIC nie mierzyła źle — ale audyt Task 8 pokazał, że zajmowała
# nazwę potrzebną nowemu, faktycznie brakującemu bezpiecznikowi (patrz niżej), więc obie muszą
# się dać odróżnić na pierwszy rzut oka.
BOT_PRO_MAX_RUNNER_STEPS = int(os.environ.get("BOT_PRO_MAX_RUNNER_STEPS", "30"))
# Bezpiecznik DŁUGOŚCI ROZMOWY (Task 8, B2) — licznik TUR całej rozmowy klient<->bot
# (bots_pro.stan.zarejestruj_ture), NIE mylić z BOT_PRO_MAX_RUNNER_STEPS wyżej. Audyt: stary
# limit 30 tur (poprzednik tej zmiennej pod starą nazwą) nie uratował ANI JEDNEJ z 10
# zapętlonych rozmów w zbadanym shardzie — klienci odpadali przy 10-28 turach, więc próg musi
# być NIŻSZY niż cierpliwość klienta. 12 to nowy próg ze specyfikacji zadania.
# <=0 WYLACZA bezpiecznik (nie: "0 tur dozwolonych" — analogicznie do SWEEP_INTERVAL/
# HOT_LEAD_SWEEP_INTERVAL, patrz sweeper.py/hot_lead_sweeper.py), sprawdzane w tura.py.
BOT_PRO_MAX_TURNS = int(os.environ.get("BOT_PRO_MAX_TURNS", "12"))
# Ile kolejnych tur BEZ POSTĘPU (bez żadnej zmiany stanu biznesowego rozmowy — pozycji,
# wysłanego podsumowania, potwierdzenia klienta, zapisanej wyceny; patrz
# bots_pro.stan.migawka_postepu) ma dopuszczać bot, zanim sam odda rozmowę człowiekowi. Task 8,
# B2: PODPIĘTE (poprzednio deklarowane w configu, ale nieużywane nigdzie — "rezerwa pod
# przyszły watchdog tury"). <=0 WYLACZA bezpiecznik, jak wyżej.
BOT_PRO_MAX_BEZ_POSTEPU = int(os.environ.get("BOT_PRO_MAX_BEZ_POSTEPU", "3"))
# Próg ciszy (minuty) dla watchdoga porzuconych rozmów (Task 8, część A) — patrz pro_watchdog.py.
# <=0 WYLACZA caly watchdog (NIE "handoff natychmiast" — runda poprawek 1, drobne: operator
# wpisujacy zero, zeby wylaczyc, nie ma dostac najagresywniejszego ustawienia).
BOT_PRO_WATCHDOG_MINUTES = int(os.environ.get("BOT_PRO_WATCHDOG_MINUTES", "20"))
# Interwal (sekundy) miedzy przejsciami watchdoga — byl zaszyty w kodzie (300), wyciagniety do
# configu dla spojnosci z reszta sweeperow (SWEEP_INTERVAL, HOT_LEAD_SWEEP_INTERVAL).
BOT_PRO_WATCHDOG_INTERVAL = int(os.environ.get("BOT_PRO_WATCHDOG_INTERVAL", "300"))
# Okno historii SQLiteSession Agents SDK (Task 8, B5) — bots_pro/tura.py:_sesja. Bez tego
# SQLiteSession podaje modelowi CAŁĄ historię sesji (a Router płaci ją drugi raz co turę) —
# koszt/opóźnienie rosnące liniowo z długością rozmowy, nie poprawność (BOT_HISTORY_LIMIT
# starego silnika liczył WIADOMOŚCI czatu — tu limit jest w ITEMS SDK, stąd osobna stała).
#
# K2 (code review, runda poprawek 1): zarzut, że okno cięte W ŚRODKU pary narzędzia zostawia
# osierocony `function_call_output` (call bez wyjścia SDK usuwa —
# `drop_orphan_function_calls` — ale rzekomo NIE odwrotnie), co Responses API miałoby odrzucać
# (400). SPRAWDZONE reprodukcją NA ŻYWYM `Runner.run` (nie tylko `session.get_items()` w
# izolacji — TO dawało osierocony wpis, patrz niżej) z realną `SQLiteSession(session_settings=
# SessionSettings(limit=2))` i historią specjalnie przeciętą w środku pary narzędzia: model
# dostał CZYSTE wejście, bez osieroconych `function_call`/`function_call_output`. Powód: SDK
# (openai-agents==0.22.0, dokładnie wersja z requirements.txt) w `prepare_input_with_session`
# (wołanym przez `Runner.run_sync`, NIE gołe `session.get_items()`) ustawia
# `output_pruning_indexes` WŁAŚNIE wtedy, gdy `SessionSettings.limit` jest ustawiony —
# `drop_orphan_function_calls` z tym argumentem czyści OBIE strony pary, nie tylko osierocone
# wywołania. Regresja tego zachowania (np. przy podbiciu wersji SDK) złapie
# test_pro_tura.py::TestSesjaOgraniczaHistorie::test_okno_przeciete_w_srodku_pary_narzedzia_nie_wysyla_osieroconego_wpisu.
BOT_PRO_SESSION_ITEMS_LIMIT = int(os.environ.get("BOT_PRO_SESSION_ITEMS_LIMIT", "60"))
# Inboxy obslugiwane przez Debusia Pro. Pusta wartosc = bot wylaczony wszedzie — kill-switch
# migracji bez zmiany kodu: przelaczamy inbox po inboksie, z natychmiastowym odwrotem (patrz
# webhooks.py, _process_pro). Zmiana wymaga recreate kontenera mostu, nie pushu kodu.
BOT_PRO_INBOXES = set(
    x.strip() for x in os.environ.get("BOT_PRO_INBOXES", "").split(",") if x.strip()
)
# Tracing Agents SDK. W bibliotece jest WLACZONY DOMYSLNIE i wysyla tresc rozmow,
# argumenty narzedzi i handoffy do backendu tracingu OpenAI — TAKZE w konfiguracji
# Anthropic przez LiteLLM (widac to w przebiegu testow jako "[non-fatal] Tracing
# client error 401"). Tresc rozmow to dane klientow, wiec domyslnie WYLACZONE;
# wlaczenie ma byc swiadoma decyzja (U14a, recenzja koncowa). Egzekwowane w
# bots_pro/agenci.py (`zastosuj_ustawienia_tracingu`), przy imporcie modulu.
BOT_PRO_TRACING = os.environ.get("BOT_PRO_TRACING", "0").strip().lower() in (
    "1", "true", "yes", "on")
