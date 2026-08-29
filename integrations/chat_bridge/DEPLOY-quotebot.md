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

---

# Tryb notatki (OLX i Allegro)

OLX i Allegro obsługują pełny silnik quotebota, ale jego wyjście trafia do **prywatnej notatki** 
zamiast wiadomości wysyłanej do klienta. Pozwala na przygotowanie oferty bez widoczności dla kupującego 
oraz manualnej akceptacji przed odpowiedzią.

## Sterowanie trybem notatki

### `BOT_QUOTE_NOTE_PERSONAS` — główny przełącznik

Zmienna środowiskowa `BOT_QUOTE_NOTE_PERSONAS` definiuje, które persony piszą do notatek:

```
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
```

**Domyślnie** (jeśli nie ustawisz): `quote_olx,quote_allegro` — obie osoby piszą do notatek.

**Pusta wartość** (`BOT_QUOTE_NOTE_PERSONAS=""`) — żaden kanał nie pisze notatek. To świadome 
zabezpieczenie: nie powraca do domyślnej wartości, ale wyłącza funkcję całkowicie. Jeśli chcesz 
przywrócić notatki po wycofaniu, jawnie ustaw zmienną na listę nazw.

**Zmiana wymaga recreate kontenera**: `bridge-deploy.sh` (nie wystarczy push kodu).

### Jak to działa — scenariusz z OLX

Gdy `quote_olx` jest w `BOT_QUOTE_NOTE_PERSONAS`:

1. Klient pisze wiadomość na OLX
2. Poller mostu (`channels/olx.py`) **ustępuje** — nie kolejkuje tury bezpośrednio
   - W logu pojawia się linia: `OLX poller: tryb notatki włączony (quote_olx w BOT_QUOTE_NOTE_PERSONAS) - tury quote-bota kolejkuje webhook /agent-bot, poller tylko dostarcza wiadomości`
3. Wiadomość trafia do Chatwoota
4. Webhook `/agent-bot` (wyzwolony przez Chatwoot) kolejkuje turę quotebota dla persony `quote_olx`
5. Bot wylicza wycenę i zapisuje ją do **prywatnej notatki** w rozmowie
6. Agent może przeczytać notatkę i ew. poprawić lub wysłać klientowi

### Analogicznie dla Allegro

Allegro zawsze używa webhooka (nie pollers), więc automatyka jest identyczna — 
gdy `quote_allegro` jest w `BOT_QUOTE_NOTE_PERSONAS`, tury są kolejkowane przez webhook 
i zapisywane jako notatki.

## Konfiguracja Chatwoota — NIE ZMIENIA SIĘ

Bot `WoodPower AI` — niezależnie od trybu notatki czy normalnego — zostaje **przypiętty do tych samych inboxów**:

- **OLX** (inbox 3)
- **Allegro** (inbox 4)
- **Kandydat** (inbox 18, jeśli włączysz na tym etapie)

To, czy bot pisze notatkę czy do klienta, jest określone przez `BOT_QUOTE_NOTE_PERSONAS`, 
nie przez konfigurację webhooka w UI. Webhook `/agent-bot` (token `BOT_QUOTE_CW_AGENT_TOKEN`) 
jest identyczny w obu trybach.

Bot `Dębuś` (`/agent-bot-quote`) obsługuje live chat i Messenger bez zmian.

## Wdrażanie — kolejność i zalecenia

### Kolejność wdrożenia

Zalecana sekwencja, aby zminimalizować ryzyko:

1. **Kandydat** (inbox 18) — testowanie w izolacji
2. **Allegro** (inbox 4) — mniejszy ruch niż OLX, łatwiej wychwycić problemy
3. **OLX** (inbox 3) — największy ruch, wdrażamy jako ostatni

### Etap 1: Kandydat (testowanie)

```bash
# W bridge-candidate.env:
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
BOT_QUOTE_PERSONAS=livechat,olx  # jeśli testujesz OLX
```

1. Napisz testową wiadomość (wymiary, gatunek, wykończenie)
2. Sprawdź w UI Chatwoota: pojawia się **prywatna notatka**, zero wiadomości wychodzących
3. Doprowadź do kompletu danych — wycena zapisuje się w CRM, notatka ma cenę

### Etap 2: Allegro (produkcja)

```bash
# W bridge.env na VPS:
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
# BOT_QUOTE_PERSONAS — Allegro jest już w webhooku, bez zmian
```

Po wdrożeniu: weryfikacja jak wyżej, ale na skrzynce **Allegro** (inbox 4).

### Etap 3: OLX (produkcja)

```bash
# W bridge.env na VPS — jak w sekcji O2, bez zmian
BOT_QUOTE_PERSONAS=livechat,olx
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
```

Po wdrożeniu: weryfikacja na OLX.

## Wycofanie — przywracanie normalnego trybu

Aby przywrócić wysyłanie **bezpośrednio do klienta** (wyłączyć notatki):

```bash
# W bridge.env, usuń personę z listy:
BOT_QUOTE_NOTE_PERSONAS=quote_allegro  # OLX wraca do wysyłania do klienta
# lub całkowicie wyłącz:
BOT_QUOTE_NOTE_PERSONAS=
```

Uruchom: `bridge-deploy.sh` (recreate).

**WAŻNE**: Gdy persona zostanie usunięta z `BOT_QUOTE_NOTE_PERSONAS`, kanał **zaczyna pisać 
BEZPOŚREDNIO DO KLIENTA** za pośrednictwem webhooka. To **nie jest neutralne cofnięcie** — 
jeśli bot nie jest przygotowany na pisanie tekstem dla danego kanału (formatowanie, ton, media), 
mogą pojawić się artefakty. W praktyce dla OLX i Allegro (personas dedykowane, persona.json) 
jest to bezpieczne, ale pamiętaj o tym podczas rollbacku.

## Weryfikacja — jak upewnić się, że działa

### Krok 1: Sprawdzić log mostu

Po starcie kontenera:

```bash
docker logs quotebot 2>&1 | grep "tryb notatki"
```

Jeśli persona jest w `BOT_QUOTE_NOTE_PERSONAS`, zobaczysz:

```
OLX poller: tryb notatki włączony (quote_olx w BOT_QUOTE_NOTE_PERSONAS) - tury quote-bota kolejkuje webhook /agent-bot, poller tylko dostarcza wiadomości
```

(Analogicznie dla Allegro w logach webhooków.)

### Krok 2: Sprawdzić bazę mostu

Po wysłaniu testowej wiadomości:

```bash
docker exec quotebot python3 -c "
import sqlite3
c = sqlite3.connect('/data/bridge.db')
# Przychodzące wiadomości zostały przetworzył przez webhooki i poller
print('Wiersze w quote_queue:')
for row in c.execute('SELECT id, persona, status, created_at FROM quote_queue ORDER BY id DESC LIMIT 5'):
    print(row)
c.close()
"
```

Oczekujesz wierszy z `persona='quote_olx'` lub `'quote_allegro'` i `status='done'` (lub `'pending'`, 
jeśli wciąż w trakcie).

### Krok 3: Sprawdzić Chatwoot UI

W rozmowie (w obydwu trybach):

- **Tryb notatki** — w sekcji `Prywatne notatki` pojawia się tekst wyceny (bez emoji, czysty tekst)
- **Tryb normalny** — wiadomość jest widoczna dla klienta w głównym stream rozmowy

---

## Zmienne — szybka referenca

| Zmienna | Domyślnie | Co robi | Gdzie zmienić |
|---------|-----------|--------|---------------|
| `BOT_QUOTE_NOTE_PERSONAS` | `quote_olx,quote_allegro` | Persony piszące do notatek | `bridge.env` |
| `BOT_QUOTE_PERSONAS` | `livechat` | Kanały, które mają wyzwalać bota z mostu (OLX) | `bridge.env` |
| `BOT_QUOTE_CW_AGENT_TOKEN` | — | Token webhooka `/agent-bot` w Chatwoocie | `bridge.env` |

Zmiana dowolnej zmiennej wymaga: `bridge-deploy.sh` (recreate kontenera).
