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

# Boty AI (podpowiadacze) — uruchomienie

Boty proponują odpowiedź jako PRYWATNĄ notatkę (`🤖 Podpowiedź AI:`) na każdą
wiadomość przychodzącą w inboxach: #3 OLX, #4 Allegro-Wiadomości, #8 Biuro,
#9 Sprzedaż. Tryb tylko-podpowiedź (agent zatwierdza i wysyła ręcznie).
Wiedza pochodzi z Help Center (retrieval RAG na embeddingach OpenAI).

### 1. Env na VPS (`bridge.env`, NIE w repo)
```
OPENAI_API_KEY=sk-...            # ten sam klucz co w Chatwoocie, ale tu osobno
BOT_HELP_CENTER_SLUG=woodpower   # slug portalu Help Center (po jego utworzeniu)
CW_MAIL_BOT_INBOXES=8,9          # Biuro, Sprzedaz (potwierdzic ID-ki)
```
Opcjonalne (mają sensowne domyślne): `BOT_OPENAI_MODEL` (gpt-4.1-mini),
`BOT_EMBEDDING_MODEL` (text-embedding-3-small), `BOT_RETRIEVAL_K` (5),
`BOT_HISTORY_LIMIT` (12), `BOT_INDEX_INTERVAL` (600), `BOT_MAX_ATTEMPTS` (3),
`CHATWOOT_OLX_INBOX_ID`, `CHATWOOT_ALLEGRO_MSG_INBOX_ID`.

### 2. Portal Help Center w Chatwoocie
Help Center → utwórz Portal → zapamiętaj `slug` → wpisz do `BOT_HELP_CENTER_SLUG`.
Weryfikacja (token mostka w kontenerze `cw-olx-bridge`):
```
docker exec cw-olx-bridge sh -c 'curl -s -H "api_access_token: $CHATWOOT_API_TOKEN" \
  "$CHATWOOT_BASE/api/v1/accounts/$CHATWOOT_ACCOUNT_ID/portals" | head -c 400'
```

### 3. Treść wiedzy (osobny task redakcyjny)
Artykuły (cennik/parametry wyceny, czasy realizacji, gatunki/możliwości,
wykończenia, obróbka krawędzi, wysyłka, FAQ) zbierane z CRM (`modules/calculator`)
i strony woodpower.pl, zatwierdzane z zespołem, publikowane jako „published".
Bez artykułów boty działają, ale głównie dopytują i odsyłają do konsultanta.

### 4. Webhook Chatwoota
Webhook konta (kierujący na `/chatwoot-webhook` mostka) musi subskrybować
`message_created` — domyślnie dostaje incoming i outgoing (incoming napędza boty).

### 5. Deploy mostka
```
bash bridge-deploy.sh
docker logs --tail 50 cw-olx-bridge | grep -E "KB index|suggest_worker|poller"
```
Oczekiwane: `KB index: N chunkow` (N>0 po zasianiu artykułów).

### 6. Test E2E
Napisz z zewnątrz na OLX/Allegro/Sprzedaż → w wątku ma pojawić się prywatna
notatka `🤖 Podpowiedź AI: …` zgodna z wiedzą i regułami kanału (Allegro:
bez kontaktu poza platformą; przy pytaniu o cenę: dopytanie o parametry).
