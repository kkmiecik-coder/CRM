# Wdrożenie bota „Asystent AI v1" (quote-bot)

## 1. bridge.env (VPS, NIE w gicie)
CRM_API_BASE=https://crm.woodpower.pl
CRM_BOT_API_KEY=<= BOT_API_KEY z config/core.json CRM>
BOT_QUOTE_AGENT_WEBHOOK_TOKEN=<losowy token webhooka>
BOT_QUOTE_CLIENT_TYPE=<dokładny client_type z /api/bot/options, np. „Klient indywidualny">
BOT_QUOTE_MAX_TURNS=30
# BOT_QUOTE_CW_AGENT_TOKEN uzupełnisz po kroku 3.

## 2. CRM
- Upewnij się, że BOT_API_KEY i BOT_USER_ID są ustawione w config/core.json CRM.
- Sprawdź client_types: curl -H "X-Bot-Api-Key: <klucz>" https://crm.woodpower.pl/api/bot/options
  → ustaw BOT_QUOTE_CLIENT_TYPE dokładnie na jeden z client_types.

## 3. Utwórz Agent Bota
docker exec <kontener-mostu> python3 -m setup.create_agent_bot quote
→ skopiuj access_token do BOT_QUOTE_CW_AGENT_TOKEN w bridge.env.

## 4. Restart + przypięcie
bridge-deploy.sh  (lub docker compose up -d --force-recreate)
Chatwoot UI → testowa skrzynka live chat → Konfiguracja bota → „Asystent AI v1" → Aktualizuj.
(Zdejmuje to poprzedniego bota z TEJ skrzynki — świadome, na czas testów.)

## 5. Smoke E2E
Na testowej skrzynce: pełna rozmowa wyceny (blat dąb lity A/B olejowany 200×60×4, 2 szt.)
→ cena w czacie; z e-mailem w pre-chat → link do wyceny w CRM.
