# Wdrożenie bota „Asystent AI v1" (quote-bot)

## 1. bridge.env (VPS, NIE w gicie)
CRM_API_BASE=https://crm.woodpower.pl
CRM_BOT_API_KEY=<= BOT_API_KEY z config/core.json CRM>
BOT_QUOTE_AGENT_WEBHOOK_TOKEN=<losowy token webhooka>
BOT_QUOTE_CLIENT_TYPE=<dokładny client_type z /api/bot/options, np. „Klient indywidualny">
BOT_QUOTE_MAX_TURNS=30
BOT_DEBOUNCE_SECONDS=10   # okno ciszy: bot czeka N s na kolejne wiadomości klienta i odpowiada RAZ
                         # na całą serię (0 = bez opóźnienia). Dotyczy wszystkich kanałów Dębusia.
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

---

# Rozszerzenie na kanał OLX (quote-bot na skrzynce OLX)

Bot działa na OLX bez pinowania do webhooka — turę wyzwala MOST (`channels/olx.py` po
odebraniu wiadomości), nie webhook Chatwoota. Guard webhooka zostaje livechat-only, więc
nie ma podwójnych odpowiedzi. Format wyjścia: czysty tekst (bez markdown/emoji), obrazy
tylko jpg/png, wiadomości rozbijane w limicie 2000 znaków. Bot wchodzi TYLKO w świeże
rozmowy (utworzone po włączeniu); rozmów sprzed go-live i przejętych przez człowieka
(status `open`) nie rusza.

## O1. Migracja bazy mostu (automatyczna)
`init_db()` sam tworzy kolumnę `quote_queue.persona` i tabelę `quote_olx_conv`
(idempotentnie, przy starcie mostu). Nic ręcznie nie trzeba.

## O2. Włącz OLX w bridge.env (kill-switch)
```
BOT_QUOTE_PERSONAS=livechat,olx      # dodanie "olx" włącza bota na OLX
```
Domyślnie (bez tej zmiennej) = tylko `livechat` → bot na OLX MILCZY. Zmienna czytana przy
starcie mostu; zmiana wymaga recreate kontenera (krok O4), nie pushu kodu.
UWAGA: `BOT_QUOTE_PERSONAS` steruje wyłącznie kanałami wyzwalanymi z mostu (dziś: OLX).
Livechat/Messenger są od niej niezależne (twardy guard webhooka).

## O3. (Opcjonalnie) parametry OLX
- Persona `quote_olx` (czysty tekst, ton marketplace) — w `bots/personas.json`, edytowalna na żywo.
- Limit długości/format obrazów — `OLX_CAPS` w `bots/channel_caps.py` (domyślnie 2000 zn., jpg/png).

## O4. Deploy + przypięcie bota do OLX
```
git push            # auto-deploy CRM (jeśli zmiany po stronie CRM)
bridge-deploy.sh    # recreate mostu (GOTCHA: recreatuje też cw-rails, ~10 s do 200)
```
Następnie w Chatwoot UI → skrzynka **OLX** → Konfiguracja bota → „Asystent AI v1" → Aktualizuj.
(Przypięcie samo w sobie nic nie robi bez `olx` w `BOT_QUOTE_PERSONAS` — most i tak wyzwala turę;
przypięcie ustala tożsamość agenta-bota i handoff.)

## O5. Weryfikacja po go-live
- Napisz z testowego konta OLX (lub poproś kogoś) — bot ma odpowiedzieć CZYSTYM tekstem,
  bez `**`/emoji, link do wyceny jako zwykły URL.
- Podejrzyj log mostu: `quote-olx: zakolejkowano ture (conv …)` oraz relay `zakolejkowano
  wysylke (olx) …` — potwierdza obieg incoming OLX → bot → relay → olx_send.
- Rozmowa sprzed go-live NIE dostaje odpowiedzi (nie jest w `quote_olx_conv`).
- Lead w CRM zapisuje się pod numerem `olx-<id_kupującego>` (panel „Wyceny CRM" dopasuje).

## O6. Wyłączenie (kill-switch, bez deployu kodu)
Usuń `olx` z `BOT_QUOTE_PERSONAS` w bridge.env → `bridge-deploy.sh` (recreate). Bot na OLX
zamilknie natychmiast; livechat działa dalej. Przypięcia w UI można nie zdejmować.
