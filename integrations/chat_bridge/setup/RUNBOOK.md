# Runbook: centrum wiadomości Chatwoot

## Co robi skrypt (automat)
`python3 -m setup.provision_chatwoot [--apply]` — tworzy etykiety, foldery,
reguły tagujące (aktywne) i auto-powitanie (NIEAKTYWNE). Idempotentny.

Wymaga env: `CHATWOOT_BASE`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN`
(token z rolą Administrator). Uruchamiać z katalogu `integrations/chat_bridge`.

Rekonesans przed zmianami: `python3 setup/inspect_chatwoot.py` (read-only).

## Kroki ręczne w UI (świadomie poza skryptem)

### 1. Widoczność inboxów (wrażliwe)
Settings → Inboxes → (każdy inbox) → Collaborators:
- prywatny inbox Sylwestra: tylko Sylwester
- prywatny inbox Anny: tylko Anna
- wspólne inboxy (OLX/Allegro/email/www): oboje

### 2. Folder „Moje otwarte"
Jeśli custom_filters nie wspiera „assignee = ja" — utwórz ręcznie filtr:
Status: Open + Assignee: (zalogowany agent), zapisz jako widok „Moje otwarte".

### 3. Auto-powitanie (NA RAZIE WYŁĄCZONE)
Decyzja: JEDEN komunikat (msg1) na każdą nową rozmowę OLX/Allegro — bez
osobnego "poza godzinami" (tekst msg1 sam wspomina godziny 8–16). Realizacja:
reguła "Auto: powitanie (wylaczone)" (event conversation_created, inbox 3/4/6,
send_message). Business Hours/OOO NIE używamy.
⚠️ Reguła ograniczona do OLX/Allegro — **nigdy poczta** (maile wewnętrzne).

### 4. Tekst powitania
Tekst (msg1) jest już wpisany w regule (stała `GREETING_TEXT` w desired_state.py).
Nic nie trzeba wklejać.

## Po przepięciu z Responso — WŁĄCZENIE auto-powitania (TYLKO OLX/Allegro)
1. Settings → Automation → „Auto: powitanie (wylaczone)" → Toggle ON.
   (Reguła ograniczona do inboxów 3/4/6 — poczty nie dotknie. Można też zmienić
   nazwę na „Auto: powitanie".)
2. Test: napisz z zewnątrz na OLX/Allegro — ma przyjść powitanie (msg1).

---

## Wariant B: Agent Boty (ingress przez /agent-bot)

Wariant B zastępuje gałąź INCOMING z `/chatwoot-webhook` natywnym Agent Botem
Chatwoota (przypinany per skrzynka w UI). Podpowiedzi AI nadal jako prywatne
notatki; handoff (reopen z pending) zawsze gdy bot przypisany do skrzynki.

### Różnica vs. wariantu A (webhook konta)
- Podpowiedzi pojawiają się **tylko** w skrzynkach z przypiętym botem.
- Wejście: `/agent-bot?token=<BOT_AGENT_WEBHOOK_TOKEN>` zamiast `/chatwoot-webhook`.
- Persona rozwiązywana przez katalog inboxów (nie BOT_INBOX_MAP).

### 1. Env w bridge.env

```
# Losowy token chroniący endpoint webhooka bota (wygeneruj: openssl rand -hex 16)
BOT_AGENT_WEBHOOK_TOKEN=<losowy-token>

# Wypełnij PO kroku 2 (skrypt wypisze wartość):
BOT_CW_AGENT_TOKEN=<access_token bota>

# Klucz OpenAI (taki sam jak dla wariantu A)
OPENAI_API_KEY=sk-...

# Slug portalu Help Center w Chatwoocie
BOT_HELP_CENTER_SLUG=woodpower
```

### 2. Utwórz Agent Bota przez API (idempotentne)

Uruchom ze środowiska mostka (VPS, kontener z dostępem do Chatwoota):

```
cd integrations/chat_bridge
CHATWOOT_BASE=https://chat.woodpower.pl \
  CHATWOOT_ACCOUNT_ID=2 \
  CHATWOOT_API_TOKEN=<admin_token> \
  BOT_AGENT_WEBHOOK_TOKEN=<losowy-token> \
  python3 -m setup.create_agent_bot
```

Skrypt wypisze:
- `id` bota (do ewentualnej weryfikacji w UI)
- `access_token` — wklej jako `BOT_CW_AGENT_TOKEN=<wartość>` do bridge.env
- `outgoing_url` — potwierdź że wskazuje `https://chatbridge.woodpower.pl/agent-bot?token=...`

Skrypt jest idempotentny: jeśli bot „WoodPower AI" już istnieje — nic nie tworzy,
tylko wypisuje dane istniejącego bota.

### 3. Webhook bota

Adres: `https://chatbridge.woodpower.pl/agent-bot?token=<BOT_AGENT_WEBHOOK_TOKEN>`
(Chatwoot wysyła na ten URL zdarzenia z inboxów, do których bot jest przypisany.)

### 4. Restart mostka

```
bash bridge-deploy.sh
docker logs --tail 50 cw-olx-bridge | grep -E "agent-bot|suggest_worker"
```

### 5. Włączanie kanału per skrzynka (UI Chatwoota)

```
Settings → Inboxes → (wybierz inbox np. OLX) → Settings → Konfiguracja bota
→ Wybierz "WoodPower AI" → Aktualizuj
```

Odłączenie bota = wybierz „Brak bota" → Aktualizuj.

Persona rozpoznawana automatycznie z typu i nazwy kanału:
- `Channel::Email` (dowolna skrzynka e-mail) → persona `mail`
- `Channel::Api` + nazwa zawiera „allegro" → persona `allegro`
- `Channel::Api` + nazwa zawiera „olx" → persona `olx`
- Pozostałe typy (WebWidget itd.) → pominięcie podpowiedzi; handoff i tak wykonany

Reguła restrykcyjności: „allegro" sprawdzane PRZED „olx" (nazwa „allegro olx" → allegro).

### 6. Test po jednym kanale

Napisz z zewnątrz na wybrany kanał → w wątku powinny pojawić się:
1. Zmiana statusu (reopen z pending — handoff)
2. Prywatna notatka `🤖 Podpowiedź AI: …`

Obserwuj logi: `docker logs --tail 100 cw-olx-bridge | grep -E "agent-bot|handoff|suggest"`

### Uwaga: stary webhook konta (wariant A)

Gałąź INCOMING z `/chatwoot-webhook` została **usunięta** w ramach wdrożenia
wariantu B. Podpowiedzi przychodzą wyłącznie przez `/agent-bot` gdy bot jest
przypisany do skrzynki. Subskrypcja `message_created` w webhooku konta może
pozostać (używana przez inne zdarzenia mostka), ale INCOMING nie generuje już
podpowiedzi.
