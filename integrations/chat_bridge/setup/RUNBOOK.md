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

### 3. Godziny pracy + komunikat poza godzinami (NA RAZIE WYŁĄCZONE)
Settings → Inboxes → (inbox) → Business Hours:
- Pn–Pt 08:00–16:00, strefa Europe/Warsaw
- wklej tekst OOO (szablon z Responso)
- **Enabled: NIE** (włączyć dopiero po przepięciu z Responso)

### 4. Tekst powitania
Settings → Automation → „Auto: powitanie (wylaczone)" → podmień
`[[SZABLON_POWITALNY]]` na finalny tekst z Responso. Zostaw regułę wyłączoną.

## Po przepięciu z Responso — WŁĄCZENIE auto-responderów
1. Settings → Automation → „Auto: powitanie (wylaczone)" → Toggle ON.
2. Settings → Inboxes → (każdy inbox) → Business Hours → Enabled ON.
3. Test: napisz z zewnątrz w godzinach pracy (ma przyjść powitanie)
   i poza godzinami (ma przyjść OOO).
