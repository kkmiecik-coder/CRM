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
