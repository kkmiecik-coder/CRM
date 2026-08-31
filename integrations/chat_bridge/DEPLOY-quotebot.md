# Wdrożenie bota „Asystent AI v1" (quote-bot)

> **UWAGA (Task 8, code review runda poprawek 2): weryfikacja Dębusia Pro (silnik
> `bots_pro/`, Agents SDK) MUSI iść przez obraz z `docker/python/Dockerfile`
> (Python 3.12 + `requirements.txt`), NIE przez lokalne środowisko developera.**
> Lokalne interpretery mają zwykle inną wersję Pythona/`openai-agents`, a pakiet
> testów `bots_pro`/`tests/test_pro_*.py` w ogóle się nie zbiera poza 3.12
> (importy specyficzne dla tej wersji). Różnica wersji SDK realnie zmienia
> zachowanie biblioteki — dokładnie to było bezpośrednią przyczyną sporu K2
> w rundzie poprawek 1 (zarzut o `SessionSettings(limit=...)` osierocającym
> `function_call_output`, sprawdzony na `openai-agents==0.8.4` lokalnie,
> nieodtwarzalny na `openai-agents==0.22.0` — dokładnej wersji przypiętej w
> `requirements.txt` i faktycznie używanej w kontenerze). Komenda testowa:
> ```
> docker run --rm -v <ścieżka repo>:/app -w /app/integrations/chat_bridge \
>   woodpower-crm-app:latest sh -c \
>   "pip install -q 'openai-agents[litellm]==0.22.0' && python -m pytest -q"
> ```
> Bez `pip install` w tej samej komendzie = wariant „bez SDK" (część testów
> pomijana `pytest.importorskip("agents")`, ale to i tak ten sam obraz/Python).

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

### `BOT_QUOTE_PERSONAS` — już NIE jest warunkiem poprawności

`BOT_QUOTE_PERSONAS` (sekcja O2) to kill-switch STAREGO mechanizmu: pollera
(`channels/olx.py`), który samodzielnie kolejkował tury OLX, sprzed przypięcia bota
Agenta do inboxa OLX. Odkąd `WoodPower AI` jest przypięty do inboxa OLX (patrz niżej)
— i to NIEZALEŻNIE od trybu notatki — webhook `/agent-bot` kolejkuje tury OLX/Allegro
SAM, bez żadnej bramki na `BOT_QUOTE_PERSONAS`. Poprawność trybu notatki zapewnia
WYŁĄCZNIE kod: bramka `"quote_olx" in BOT_QUOTE_NOTE_PERSONAS` w `_enqueue_quote_olx`
(channels/olx.py), która każe pollerowi ustąpić NIEZALEŻNIE od tego, co jest w
`BOT_QUOTE_PERSONAS`.

`BOT_QUOTE_PERSONAS=livechat,olx` w produkcyjnym `bridge.env` (sekcja O2) zostaje —
to nie szkodzi, dopóki `quote_olx` jest w `BOT_QUOTE_NOTE_PERSONAS`. Zmienna jest dziś
porządkowa (ślad po starym mechanizmie), NIE wymagana do poprawnego działania trybu
notatki. Staje się istotna dopiero przy wycofaniu trybu notatki dla OLX — patrz
sekcja „Wycofanie" niżej, gdzie trzeba ją adresować wprost.

### Jak to działa — scenariusz z OLX

Gdy `quote_olx` jest w `BOT_QUOTE_NOTE_PERSONAS`:

1. Klient pisze wiadomość na OLX
2. Poller mostu (`channels/olx.py`) **ustępuje** — nie kolejkuje tury bezpośrednio
   - W logu (przy starcie mostu, linia jednorazowa) pojawia się dokładnie: `OLX poller: tryb notatki wlaczony (quote_olx w BOT_QUOTE_NOTE_PERSONAS) - tury quote-bota kolejkuje webhook /agent-bot, poller tylko dostarcza wiadomosci` (bez polskich znaków — tak brzmi w `channels/olx.py`)
3. Wiadomość trafia do Chatwoota
4. Webhook `/agent-bot` (wyzwolony przez Chatwoot) kolejkuje turę quotebota dla persony `quote_olx`
5. Bot wylicza wycenę i zapisuje ją do **prywatnej notatki** w rozmowie
6. Agent może przeczytać notatkę i ew. poprawić lub wysłać klientowi

### Analogicznie dla Allegro

Allegro zawsze używa webhooka (nie pollera), więc automatyka jest identyczna — gdy
`quote_allegro` jest w `BOT_QUOTE_NOTE_PERSONAS`, tury są kolejkowane przez webhook
i zapisywane jako notatki. Dotyczy to **wyłącznie inboxu „Allegro - Wiadomości"**
(`CHATWOOT_ALLEGRO_MSG_INBOX_ID`); inbox „Allegro - Dyskusje" jest poza zakresem — patrz
sekcja „Zakres" niżej.

## Konfiguracja Chatwoota — NIE ZMIENIA SIĘ

Bot `WoodPower AI` — niezależnie od trybu notatki czy normalnego — zostaje **przypięty do tych samych inboxów**:

- **OLX** (`CHATWOOT_OLX_INBOX_ID`, produkcyjnie inbox 3)
- **Allegro - Wiadomości** (`CHATWOOT_ALLEGRO_MSG_INBOX_ID`, produkcyjnie inbox 4)

### Zakres: Allegro-Dyskusje jest POZA nim

Inbox **Allegro - Dyskusje** (`CHATWOOT_ALLEGRO_DISPUTE_INBOX_ID`, produkcyjnie inbox 6) jest
świadomie poza zakresem (spec, Decyzja 5): to spory i reklamacje, ~5 wątków miesięcznie,
wysoka stawka błędu. Zostaje na starym podpowiadaczu (`suggest_queue`) — żadnej wyceny,
żadnego leada w CRM.

Rozgałęzienie w `webhooks.py` idzie po **`inbox_id` z konfiguracji**, nie po kluczu persony:
`persona_for` zwraca `"allegro"` dla KAŻDEGO inboxu `Channel::Api` z „allegro" w nazwie, więc
mapowanie po personie wciągałoby Dyskusje razem z Wiadomościami. Konsekwencja praktyczna:
**bez poprawnych `CHATWOOT_*_INBOX_ID` w `bridge.env` kanał wypada z zakresu** i cicho
schodzi na stary podpowiadacz (w logu mostu: `agent-bot: inbox N (persona …) poza zakresem
quotebota - stary podpowiadacz`).

To, czy bot pisze notatkę czy do klienta, jest określone przez `BOT_QUOTE_NOTE_PERSONAS`, 
nie przez konfigurację webhooka w UI. Webhook `/agent-bot` jest identyczny w obu trybach —
w kodzie (`webhooks.py`, `_process_agent_bot`) nie ma żadnej bramki na tryb notatki, tylko
mapowanie inbox → persona. Zabezpiecza go token `BOT_AGENT_WEBHOOK_TOKEN` (parametr `token`
w URL webhooka) — to INNY token niż `BOT_QUOTE_CW_AGENT_TOKEN`, czyli access_token Agenta
Bota, którego most używa do wysyłki notatek/odpowiedzi PRZEZ Chatwoot API (`cw_agent_reply`,
`cw_note` w `bots/quotebot.py`). Nie pomyl ich przy rotacji sekretów.

Bot `Dębuś` (`/agent-bot-quote`) obsługuje live chat i Messenger bez zmian.

## Wdrażanie — kolejność i zalecenia

### Kolejność wdrożenia

Zalecana sekwencja, aby zminimalizować ryzyko:

1. **Kandydat** — wyzwolenie tury ręcznie w kontenerze kandydata (patrz Etap 1)
2. **Allegro - Wiadomości** — mniejszy ruch niż OLX, łatwiej wychwycić problemy
3. **OLX** — największy ruch, wdrażamy jako ostatni

### Etap 1: Kandydat (testowanie)

> **Czego NIE da się tu zrobić.** Trybu notatki **nie da się uruchomić na inboksie live chatu**.
> Inbox „Wsparcie Woodpower - TESTY" (18) jest typu `Channel::WebWidget`, więc `persona_for`
> zwraca dla niego `"livechat"`: webhook `/agent-bot` taki inbox **pomija** (`inbox … bez persony
> podpowiedzi`), a `/agent-bot-quote` kolejkuje turę z personą `quote` — czyli w trybie **REPLY**.
> Napisanie tam testowej wiadomości skończy się odpowiedzią Dębusia **do testera**, a nie notatką.
> Tryb notatki wchodzi wyłącznie dla person `quote_olx` / `quote_allegro`, a te przydziela
> wyłącznie mapowanie `inbox_id` → persona z `CHATWOOT_*_INBOX_ID`.

**Wybrana metoda: ręczne wyzwolenie tury w kontenerze kandydata.** Nie wymaga zmian w
konfiguracji Chatwoota ani przekierowania `CHATWOOT_*_INBOX_ID` na inbox testowy (a to na
kandydacie przestawiłoby również poller OLX, który tworzy rozmowy w tym samym inboksie).
Weryfikuje dokładnie to, co jest nowe: silnik + wyjście do notatki. Kolejkowanie po stronie
webhooka weryfikujemy w Etapie 2, na prawdziwym inboksie Allegro.

```bash
# 1. bridge-candidate.env — tryb notatki włączony, ID inboxów jak na produkcji:
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
BOT_CW_AGENT_TOKEN=<access_token bota „WoodPower AI">
CHATWOOT_OLX_INBOX_ID=3
CHATWOOT_ALLEGRO_MSG_INBOX_ID=4
```

```bash
# 2. Recreate kandydata i sprawdź, że most widzi tryb notatki:
bridge-deploy.sh
docker logs <kontener-kandydata> 2>&1 | grep "tryb notatki"
```

```bash
# 3. Wybierz w UI Chatwoota istniejącą rozmowę na inboksie Allegro-Wiadomości i weź jej
#    conv_id z adresu URL (…/conversations/<CONV_ID>). Notatka jest PRYWATNA — kupujący
#    jej nie zobaczy, a tryb notatki gwarantuje, że nic nie wyjdzie na platformę.
docker exec <kontener-kandydata> python3 -c "
from bots.quote_intake import enqueue_quote_turn
print(enqueue_quote_turn(<CONV_ID>, 4, 'test-notatka-1',
      'Dzień dobry, blat dębowy lity A/B olejowany 200x60x4, 2 sztuki. Ile to kosztuje?',
      persona='quote_allegro'))
"
# oczekiwane: inserted
```

```bash
# 4. Po ~15 s (okno ciszy + tura) sprawdź kolejkę:
docker exec <kontener-kandydata> python3 -c "
import sqlite3
c = sqlite3.connect('/data/bridge.db')
for row in c.execute('SELECT id, persona, status, attempts, last_error FROM quote_queue ORDER BY id DESC LIMIT 3'):
    print(row)
c.close()
"
# oczekiwane: persona='quote_allegro', status='sent'
```

5. Sprawdź rozmowę w UI Chatwoota: pojawia się **prywatna notatka** z nagłówkiem
   `Dębuś — propozycja odpowiedzi:` i **zero wiadomości wychodzących** w głównym wątku.
6. Powtórz krok 3 z kolejnymi wiadomościami (dopowiadaj brakujące dane), aż do kompletu —
   wycena zapisuje się w CRM, a notatka ma cenę. Za każdym razem zmień `'test-notatka-1'`
   na nowy identyfikator, inaczej dedup (`quote_seen`) odrzuci turę jako duplikat.

**Wariant pełniejszy (opcjonalny), jeśli chcesz przetestować także webhook:** załóż inbox
`Channel::Api` z „olx" albo „allegro" w nazwie, przypnij do niego bota `WoodPower AI` i wskaż
jego id w `CHATWOOT_OLX_INBOX_ID` / `CHATWOOT_ALLEGRO_MSG_INBOX_ID` **w bridge-candidate.env**.
Wtedy wiadomość wstrzyknięta do tego inboxu przejdzie pełną ścieżkę webhook → kolejka → notatka.
Uwaga: na kandydacie ta sama zmienna steruje pollerem OLX, więc rób to tylko przy wyłączonym
pollerze (`BOT_QUOTE_PERSONAS=livechat`).

### Etap 2: Allegro (produkcja)

```bash
# W bridge.env na VPS:
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
CHATWOOT_ALLEGRO_MSG_INBOX_ID=4        # inbox „Allegro - Wiadomości" — JEDYNY w zakresie
CHATWOOT_ALLEGRO_DISPUTE_INBOX_ID=6    # „Allegro - Dyskusje" — poza zakresem, tylko dla jasności
# BOT_QUOTE_PERSONAS — Allegro jest już w webhooku, bez zmian
```

Po wdrożeniu: weryfikacja na skrzynce **Allegro - Wiadomości** (inbox 4) — napisz z konta
testowego i sprawdź, że pojawia się prywatna notatka. Dodatkowo sprawdź inbox **Dyskusje**
(6): tam notatki quotebota pojawić się **NIE mogą** — nowa wiadomość ma trafić do
`suggest_queue`, a w logu mostu ma być `agent-bot: inbox 6 (persona allegro) poza zakresem
quotebota - stary podpowiadacz`.

### Etap 3: OLX (produkcja)

```bash
# W bridge.env na VPS — jak w sekcji O2, bez zmian
BOT_QUOTE_PERSONAS=livechat,olx
BOT_QUOTE_NOTE_PERSONAS=quote_olx,quote_allegro
CHATWOOT_OLX_INBOX_ID=3    # MUSI być ustawione — bez tego OLX wypada z zakresu trybu notatki
```

Po wdrożeniu: weryfikacja na OLX.

## Wycofanie — przywracanie normalnego trybu

Aby przywrócić wysyłanie **bezpośrednio do klienta** (wyłączyć notatki):

**Allegro** — brak pollera, webhook `/agent-bot` jest jedynym torem w KAŻDYM trybie.
Wystarczy usunąć personę z listy:

```bash
# W bridge.env:
BOT_QUOTE_NOTE_PERSONAS=quote_olx   # Allegro wraca do wysyłania do klienta, OLX zostaje w notatce
```

**OLX** — wymaga DWÓCH zmian w JEDNYM edycie `bridge.env` i JEDNYM recreate. Poller
(`channels/olx.py`, `_enqueue_quote_olx`) ma DWIE bramki, i po wycofaniu OBIE muszą
trzymać jednocześnie, żeby poller zostawał cicho:

```python
if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS:   # bramka 1: tryb notatki
    return
if "olx" not in BOT_QUOTE_PERSONAS:          # bramka 2: kill-switch z sekcji O2
    return
```

Jeśli usuniesz `quote_olx` z `BOT_QUOTE_NOTE_PERSONAS`, ale zostawisz `olx` w
`BOT_QUOTE_PERSONAS` (tak jak jest ustawione od Etapu 3 — `BOT_QUOTE_PERSONAS=livechat,olx`)
— bramka 1 przestaje trzymać, a bramka 2 TEŻ nie trzyma (bo `olx` nadal tam jest). Poller
zaczyna znów kolejkować tury SAMODZIELNIE, RÓWNOLEGLE z webhookiem `/agent-bot`, który
kolejkuje tury OLX/Allegro BEZ ŻADNEJ bramki trybu (patrz sekcja „Konfiguracja Chatwoota"
wyżej). Oba tory używają INNYCH kluczy dedupu w `quote_seen` (`olx-<id>` w pollerze vs
surowy mid Chatwoota w webhooku), więc się wzajemnie nie odsieją — jedna wiadomość klienta
zamienia się w DWIE tury, a skoro tryb wrócił na „reply", klient dostaje odpowiedź DWA RAZY
(i dwa leady w CRM). Dlatego wycofanie OLX-a to ZAWSZE edycja OBU zmiennych naraz, nigdy
tylko `BOT_QUOTE_NOTE_PERSONAS`:

```bash
# W bridge.env — USUŃ personę z BOT_QUOTE_NOTE_PERSONAS ORAZ "olx" z BOT_QUOTE_PERSONAS
# w TEJ SAMEJ edycji:
BOT_QUOTE_NOTE_PERSONAS=quote_allegro   # OLX wraca do wysyłania do klienta
BOT_QUOTE_PERSONAS=livechat             # bez "olx" - domykamy bramkę 2 pollera
```

lub, żeby wyłączyć tryb notatki na obu kanałach naraz:

```bash
BOT_QUOTE_NOTE_PERSONAS=
BOT_QUOTE_PERSONAS=livechat
```

Uruchom: `bridge-deploy.sh` (recreate) — JEDNORAZOWO, z obiema zmianami naraz (nie w dwóch
osobnych deployach — w oknie między nimi kontener chodzi w stanie z podwójnym torem).

**WAŻNE — realnym skutkiem wycofania jest CISZA, nie podwójna odpowiedź do klienta.**

Po zdjęciu persony z `BOT_QUOTE_NOTE_PERSONAS` kanał **nie zaczyna pisać do klienta** — on
**milknie**. Mechanizm, w kolejności wykonania:

1. `webhooks.py`, `_process_agent_bot` woła `cw_bot_handoff(conv_id)` **PRZED** zakolejkowaniem
   tury — bezwarunkowo, w każdym trybie. Rozmowa jest więc od pierwszej wiadomości w statusie
   `open`, nie `pending`.
2. W trybie `reply` bramka `_wolno_prowadzic_rozmowe` (`bots/quotebot.py`) odpytuje status
   i przepuszcza turę **tylko** dla `pending`. Dla `open` loguje `quotebot: conv N status=open -
   bot milczy` i zwraca `False`.
3. `_run_quote_turn_inner` kończy się na tej bramce w pierwszej linii — tura nie robi nic:
   ani wiadomości do klienta, ani notatki. W `quote_queue` wiersz i tak kończy jako `sent`
   (tura przebiegła bez wyjątku), więc **kolejka nie jest sygnałem problemu**.

Bramka jest zniesiona **wyłącznie** dla trybu notatki (notatka jest bezpieczna niezależnie od
tego, kto prowadzi rozmowę) — i to ona sprawia, że tryb notatki w ogóle działa mimo `open`.
Zdjęcie persony z listy zabiera tę zniesioną bramkę i kanał traci wszystkie tury po cichu.

**Żeby po wycofaniu kanał faktycznie wrócił do działania**, trzeba usunąć przyczynę statusu
`open`, czyli bezwarunkowy handoff w webhooku:

- **OLX** — wróć na stary tor pollera: usuń `quote_olx` z `BOT_QUOTE_NOTE_PERSONAS`, zostaw
  `olx` w `BOT_QUOTE_PERSONAS` i **zdejmij bota `WoodPower AI` z inboxu OLX w Chatwoot UI**
  (Konfiguracja bota → usuń). Bez przypiętego bota Chatwoot nie woła `/agent-bot`, nie ma
  handoffu, rozmowy zostają w `pending`, a turę wyzwala poller (`channels/olx.py`) — dokładnie
  jak przed wdrożeniem trybu notatki. Dopiero wtedy `BOT_QUOTE_PERSONAS=livechat,olx` jest
  konfiguracją poprawną, a nie podwójnym torem.
- **Allegro** — nie ma pollera, więc `/agent-bot` jest jedynym torem. Zdjęcie bota z inboxu
  wyłącza kanał całkowicie. Wycofanie Allegro do trybu „bot pisze do kupującego" **wymaga
  zmiany kodu** (zniesienia bezwarunkowego `cw_bot_handoff` przed kolejkowaniem albo
  rozluźnienia bramki statusu) — samą zmianą `bridge.env` się tego nie osiągnie. Wycofanie
  przez `bridge.env` daje dla Allegro wyłącznie stan „kanał milczy, obsługuje człowiek",
  co jest bezpiecznym stanem docelowym rollbacku, ale trzeba go świadomie wybrać.

**Podwójna odpowiedź (dwie tury na jedną wiadomość) dotyczy tylko OLX** i tylko wtedy, gdy
poller i webhook działają równolegle — patrz opis dwóch bramek wyżej. Nawet wtedy druga tura
milknie na bramce statusu, dopóki bot `WoodPower AI` jest przypięty do inboxu (handoff →
`open`). Ryzyko realizuje się dopiero po zdjęciu przypięcia, gdy rozmowy wracają do `pending`:
wtedy dwa tory, dwa różne klucze dedupu (`olx-<id>` w pollerze vs surowy mid Chatwoota
w webhooku) i klient dostaje odpowiedź dwa razy. Dlatego kolejność wycofania OLX-a jest ważna:
najpierw `BOT_QUOTE_PERSONAS=livechat` + edycja `bridge.env` i recreate, potem zdjęcie
przypięcia w UI, a `olx` do `BOT_QUOTE_PERSONAS` wraca dopiero na końcu.

**Weryfikacja po wycofaniu** (nie polegaj na braku błędów w logu):

```bash
# Kanał milczy? To zobaczysz TYLKO tutaj — kolejka pokazuje 'sent' mimo pustej tury.
docker logs <kontener-mostu> 2>&1 | grep "bot milczy"
```

## Weryfikacja — jak upewnić się, że działa

**OSTRZEŻENIE — ryzyko odwrotne, sprawdź PRZED włączeniem trybu notatki**: jeśli ustawisz
personę w `BOT_QUOTE_NOTE_PERSONAS`, ale bot `WoodPower AI` NIE jest (jeszcze, albo już
nie jest) przypięty w Chatwoocie do danego inboxa — pominięty krok przypięcia, przypięty
inny bot, albo ktoś zdjął przypięcie ręcznie — kanał **traci tury CAŁKOWICIE i po cichu**:
poller ustąpił (bramka 1 wyżej), a webhook `/agent-bot` nigdy się nie odpala, bo Chatwoot
nie ma czego wołać na tym inboxie. Żaden tor ich nie produkuje. Nie ma żadnego błędu ani
wyjątku, ani wpisu w logu mostu — po prostu żadna wiadomość klienta nie dostaje ani
odpowiedzi, ani notatki. Jedyny sygnał to BRAK notatek w rozmowach, czego nikt nie
zauważy, jeśli nie sprawdzi się tego aktywnie. Zawsze zweryfikuj przypięcie bota w
Chatwoot UI (Konfiguracja bota danego inboxa → „Asystent AI v1") PRZED ustawieniem persony
w `BOT_QUOTE_NOTE_PERSONAS`, a po ustawieniu — Krokiem 1 poniżej.

### Krok 1: Sprawdzić log mostu

Po starcie kontenera:

```bash
docker logs <kontener-mostu> 2>&1 | grep "tryb notatki"
```

Jeśli persona jest w `BOT_QUOTE_NOTE_PERSONAS`, zobaczysz dokładnie (bez polskich znaków —
tak brzmi w `channels/olx.py`):

```
OLX poller: tryb notatki wlaczony (quote_olx w BOT_QUOTE_NOTE_PERSONAS) - tury quote-bota kolejkuje webhook /agent-bot, poller tylko dostarcza wiadomosci
```

(Allegro nie ma własnego pollera — nie ma odpowiednika tej linii w logu; brak tego wpisu
dla Allegro nie oznacza problemu, patrz sekcja „Analogicznie dla Allegro" wyżej.)

### Krok 2: Sprawdzić bazę mostu

Po wysłaniu testowej wiadomości:

```bash
docker exec <kontener-mostu> python3 -c "
import sqlite3
c = sqlite3.connect('/data/bridge.db')
# Wiadomości przychodzące zostały przetworzone przez webhook lub poller (zależy od trybu)
# Kolumna created_at NIE istnieje w quote_queue (schemat: core/db.py) - sortujemy po id.
print('Wiersze w quote_queue:')
for row in c.execute('SELECT id, persona, status, attempts FROM quote_queue ORDER BY id DESC LIMIT 5'):
    print(row)
c.close()
"
```

Oczekujesz wierszy z `persona='quote_olx'` lub `'quote_allegro'` i `status='sent'` (tura
zakończona — patrz `quote_worker.py`) lub `'pending'`/`'processing'`, jeśli wciąż w
trakcie. `status='failed'` oznacza trwały błąd (sprawdź `last_error` w tym samym wierszu).

### Krok 3: Sprawdzić Chatwoot UI

W rozmowie (w obydwu trybach):

- **Tryb notatki** — w sekcji `Prywatne notatki` pojawia się tekst wyceny (bez emoji, czysty tekst)
- **Tryb normalny** — wiadomość jest widoczna dla klienta w głównym stream rozmowy

---

## Zmienne — szybka referenca

| Zmienna | Domyślnie | Co robi | Gdzie zmienić |
|---------|-----------|--------|---------------|
| `BOT_QUOTE_NOTE_PERSONAS` | `quote_olx,quote_allegro` | Persony piszące do notatek | `bridge.env` |
| `BOT_QUOTE_PERSONAS` | `livechat` | Kill-switch starego pollera OLX (sekcja O2) — bez wpływu na poprawność trybu notatki, dopóki `quote_olx` jest w `BOT_QUOTE_NOTE_PERSONAS`; przy wycofaniu trybu notatki dla OLX MUSI wrócić do `livechat` (patrz „Wycofanie") | `bridge.env` |
| `BOT_AGENT_WEBHOOK_TOKEN` | — | Token w URL webhooka `/agent-bot` (obsługuje OLX, Allegro i mail — bez bramki trybu notatki) | `bridge.env` |
| `BOT_CW_AGENT_TOKEN` | — | **Access_token bota `WoodPower AI`.** Tym tokenem podpisywane są WSZYSTKIE notatki tury na OLX/Allegro (propozycja odpowiedzi, notatka leada, podsumowanie handoffu) oraz handoff. Przy braku wartości kod loguje ostrzeżenie `quotebot: BRAK BOT_CW_AGENT_TOKEN …` i spada na token Dębusia — notatki wtedy powstaną, ale **podpisane innym botem niż widoczny na kanale** | `bridge.env` |
| `BOT_QUOTE_CW_AGENT_TOKEN` | — | Access_token bota `Dębuś` do wywołań Chatwoot API (odpowiedzi na live chacie/Messengerze) — INNY token niż `BOT_AGENT_WEBHOOK_TOKEN` i niż `BOT_CW_AGENT_TOKEN`. Poza trybem notatki to on podpisuje notatki i handoff | `bridge.env` |
| `CHATWOOT_OLX_INBOX_ID` | — | **ID inboxu OLX.** Decyduje o zakresie trybu notatki: tylko ten inbox dostaje personę `quote_olx`. Brak wartości = OLX wypada z zakresu i cicho schodzi na stary podpowiadacz | `bridge.env` |
| `CHATWOOT_ALLEGRO_MSG_INBOX_ID` | `4` | **ID inboxu Allegro - Wiadomości.** Jedyny inbox Allegro w zakresie (persona `quote_allegro`) | `bridge.env` |
| `CHATWOOT_ALLEGRO_DISPUTE_INBOX_ID` | `6` | ID inboxu Allegro - Dyskusje. **Świadomie POZA zakresem** (spec, Decyzja 5) — zostaje na starym podpowiadaczu | `bridge.env` |

Zmiana dowolnej zmiennej wymaga: `bridge-deploy.sh` (recreate kontenera).

## Checklista przed wdrożeniem

Sprawdź **przed** ustawieniem persony w `BOT_QUOTE_NOTE_PERSONAS`:

- [ ] `BOT_CW_AGENT_TOKEN` ustawiony w `bridge.env` i jest to access_token bota `WoodPower AI`
      (nie Dębusia, nie token webhooka). Weryfikacja po recreate:
      `docker logs <kontener-mostu> 2>&1 | grep "BRAK BOT_CW_AGENT_TOKEN"` → **pusto**
- [ ] `CHATWOOT_OLX_INBOX_ID` i `CHATWOOT_ALLEGRO_MSG_INBOX_ID` wskazują właściwe inboxy;
      `CHATWOOT_ALLEGRO_DISPUTE_INBOX_ID` NIE jest wpisane w żadną z dwóch poprzednich
- [ ] Bot `WoodPower AI` przypięty w Chatwoot UI do inboxu OLX i Allegro - Wiadomości
      (bez przypięcia kanał traci tury całkowicie — patrz OSTRZEŻENIE niżej)
- [ ] `BOT_QUOTE_CW_AGENT_TOKEN` nadal ustawiony (live chat Dębusia działa niezależnie)
- [ ] Po recreate: `docker logs <kontener-mostu> 2>&1 | grep "poza zakresem quotebota"` →
      pojawia się **tylko** dla inboxu Dyskusji, nigdy dla OLX ani Allegro-Wiadomości

---

# Dębuś Pro (`bots_pro/`, Agents SDK) — przed włączeniem pierwszego inboxu

> Ta sekcja dotyczy **nowego** silnika (`BOT_PRO_INBOXES`), nie quote-bota wyżej.
> Przeczytaj ją **zanim** wpiszesz pierwszy inbox do `BOT_PRO_INBOXES`.

## Znane ograniczenie: suma „produkt + dostawa" liczona po stronie mostka

Podsumowanie, które klient potwierdza, pokazuje **Razem z dostawą** — a ta jedna liczba
jest **dodawana w Pythonie** (`bots_pro/podsumowanie.py`, `wyslij()`), nie pobierana
z CRM. To jedyny wyjątek od zasady „cena zawsze z CRM" i jest świadomy: sprawdzone,
że **żaden** endpoint bota nie zwraca sumy obejmującej wysyłkę —
`/api/bot/calculate` liczy `totals` wyłącznie z pozycji (nie zna kodu pocztowego),
`/api/bot/shipping-quote` zwraca sam koszt kuriera, `POST`/`PUT /api/bot/quotes`
nie zwracają żadnych kwot, a serializer `GET /api/bot/quotes` ma w kodzie komentarz
wprost: „Wysyłki NIE doliczamy — liczy ją sklep".

**Kiedy to przestanie być bezpieczne:** gdy CRM zacznie stosować rabat na poziomie
SUMY (np. darmowa wysyłka powyżej progu) albo inaczej modyfikować cenę końcową.
Bot pokazywałby wtedy klientowi kwotę **wyższą niż faktyczna**, i to w treści,
którą klient podpisuje (inwariant I2).

**Co zrobić przy takiej zmianie w CRM:** jeśli w odpowiedzi któregokolwiek z tych
endpointów pojawi się pole z sumą razem z wysyłką — użyć JEGO zamiast dodawania
(jedno miejsce w kodzie, oznaczone komentarzem `R3`).
