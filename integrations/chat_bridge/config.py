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

# ----- BaseLinker -----
BASELINKER_TOKEN = os.environ.get("BASELINKER_TOKEN")
BASE_PANEL_TOKEN = os.environ.get("BASE_PANEL_TOKEN")
BL_API = "https://api.baselinker.com/connector.php"

DB_PATH = os.environ.get("BRIDGE_DB", "/data/bridge.db")
MAX_ATTEMPTS = 5

# ----- Boty AI (podpowiadacze) -----
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY")
OPENAI_API_BASE     = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
BOT_CHAT_MODEL      = os.environ.get("BOT_OPENAI_MODEL", "gpt-4.1-mini")
BOT_EMBEDDING_MODEL = os.environ.get("BOT_EMBEDDING_MODEL", "text-embedding-3-small")
BOT_RETRIEVAL_K     = int(os.environ.get("BOT_RETRIEVAL_K", "5"))
BOT_HELP_CENTER_SLUG = os.environ.get("BOT_HELP_CENTER_SLUG", "")
BOT_HISTORY_LIMIT   = int(os.environ.get("BOT_HISTORY_LIMIT", "12"))
BOT_INDEX_INTERVAL  = int(os.environ.get("BOT_INDEX_INTERVAL", "600"))
BOT_MAX_ATTEMPTS    = int(os.environ.get("BOT_MAX_ATTEMPTS", "3"))
BOT_MAX_TOKENS      = int(os.environ.get("BOT_MAX_TOKENS", "700"))
# Inboxy mailowe objete botem (CSV id-kow Chatwoota): #8 Biuro, #9 Sprzedaz.
CW_MAIL_BOT_INBOXES = os.environ.get("CW_MAIL_BOT_INBOXES", "8,9")
