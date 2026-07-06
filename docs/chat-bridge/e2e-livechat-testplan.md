# Plan E2E — bot live-chat „Dębuś" (Chatwoot ↔ OpenAI)

> **Cel:** przed przypięciem bota do REALNEGO czatu sklepu wytestować **każdy przypadek**
> na żywym bocie (skrzynka testowa, prawdziwy LLM gpt‑5.4‑nano). ~50 rozmów, jedna rozmowa =
> jeden scenariusz. Ten plik jest przeznaczony dla **osobnej sesji Claude Code**, która plan
> wykona i zbierze raport pass/fail.
>
> Kontekst i historia bota: pamięć `project-chatwoot-livechat-bot`. Kod silnika:
> `integrations/chat_bridge/bots/livechat.py`. Rejestr obrazów: `bots/images.py`. Vision:
> `bots/vision.py`. Webhook + worker: `webhooks.py`, `live_worker`.

---

## 0. Zasady testu (przeczytaj najpierw)

- **Co testujemy:** pełną ścieżkę produkcyjną — wiadomość klienta → webhook `/agent-bot-live`
  → `live_queue` → `live_worker` → `run_livechat_turn` → LLM → odpowiedź publiczna w Chatwoocie
  (+ prywatna notatka + zmiana statusu przy handoffie). To jest E2E, **nie** unit test.
- **Gdzie:** skrzynka **TESTOWA** — inbox **18** „Wsparcie Woodpower — TESTY", account **2**.
  **NIGDY** na inboxie 5 (realny czat CRM+sklep). Potwierdź przypięcie bota do inboxu 18 przed startem.
- **Dwie klasy asercji:**
  - **DETERMINISTYCZNE (muszą przejść co do joty)** — logika w kodzie: koperta wymiarów,
    loop‑breaker, deflect/handoff człowieka, reklamacja‑raz, cisza po handoffie, dedup mid,
    deterministyczne podsumowanie, potwierdzenie→handoff, próbka 1b, dedup obrazów, brak wycieku JSON.
  - **LLM‑ZALEŻNE (ocena sensowności, nie bit‑exact)** — treść odpowiedzi, wybór obrazu 1a,
    naturalność dopytywania, tryb informacyjny. Oceniaj: czy zachowanie rozsądne i zgodne z personą.
- **Koszt:** ~50 rozmów × kilka tur = realne tokeny OpenAI + realne rozmowy w Chatwoocie.
  To jest zaakceptowane (user chce komplet). Testowe rozmowy oznacz i posprzątaj na końcu (§6).
- **Języki/komentarze:** po polsku.

---

## 1. Discovery środowiska (Phase 0)

SSH na VPS: `ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109`

Zbierz z `/root/chatwoot-test/bridge.env` (NIE commituj, NIE wypisuj sekretów do raportu):
- `CW_BASE`, `CW_ACC` (=2), `CW_TOKEN` (token agenta/admina do Application API),
- `BOT_LIVE_CW_AGENT_TOKEN` (token live‑bota — jego wiadomości = outgoing),
- `BOT_LIVE_AGENT_WEBHOOK_TOKEN` (token w URL webhooka — jeśli będziesz wołać webhook wprost),
- `BOT_IMAGES_DIR` (domyślnie `/app/assets/bot_images` w kontenerze).

Potwierdź stan:
```bash
# bot przypięty do inboxu 18? (Outgoing URL agent-bota w UI Chatwoota → /agent-bot-live?token=...)
docker exec cw-olx-bridge python -c "import config; print('MODEL', config.BOT_CHAT_MODEL); print('MAXTURNS', config.BOT_LIVE_MAX_TURNS)"
# lista realnie dostępnych próbek (do doboru scenariuszy obrazowych):
docker exec cw-olx-bridge sh -lc 'ls -1 /app/assets/bot_images | sort'
```
Z listy plików wybierz:
- **jedną konfigurację, która MA próbkę** (np. `dab_lity_ab_olejowane.jpg` jeśli istnieje) — do S39,
- **jedną ofertowaną, ale BEZ pliku** (np. buk lity lakierowane) — do S40,
- potwierdź `gatunki_porownanie.jpg` (obraz semantyczny 1a) — do S37.

> Reguły dziedzinowe (do układania scenariuszy): produkty **blat / parapet / schody**;
> gatunki **dąb** (klasa A/B i B/B), **jesion** (A/B), **buk** (A/B) — B/B tylko dąb;
> technologia **lita / mikrowczep**; wykończenie **surowe / olejowane / lakierowane**.
> Koperta: **szer ≤ 120**, **dł lita ≤ 450**, **dł mikrowczep ≤ 500** (technologia nieznana → 500,
> przy 450–500 dopytaj o technologię); **grubość 1,5–4** standard, **>4** = decyzja konsultanta
> (NIE odrzucaj), **<1,5** = dopytaj.

---

## 2. Mechanizm sterowania rozmową

Sprawdzony wcześniej (pamięć, iteracja E2E 03.07):
- **Wiadomość „od klienta"** wstrzykuje się przez **Application API** Chatwoota jako
  `message_type: 0` (incoming). `message_type:"incoming"` bywa blokowane na WebWidget;
  publiczne `/public/api` daje 404 — dlatego Application API + `message_type:0`.
- Endpoint: `POST {CW_BASE}/api/v1/accounts/2/conversations/{conv_id}/messages`
  z nagłówkiem `api_access_token: {CW_TOKEN}` i body `{"content": "...", "message_type": 0}`.
- **Utworzenie rozmowy:** `POST /api/v1/accounts/2/conversations` z `inbox_id=18` + `source_id`
  + `contact_id` (utwórz kontakt: `POST /api/v1/accounts/2/contacts`). Każdy scenariusz =
  świeży kontakt/rozmowa (izolacja stanu `live_state`/`live_dane`).
- **Odczyt odpowiedzi bota:** `GET /api/v1/accounts/2/conversations/{conv_id}/messages` →
  wiadomości `message_type:1` (outgoing) o autorze = live‑bot; **prywatne notatki** (`private:true`)
  = notatka handoffu; **status** rozmowy z obiektu conversation (`open` = po handoffie, `pending` = bot prowadzi).
- **Obrazy klienta (vision, S41/S43):** dołącz `attachments` przy tworzeniu wiadomości incoming
  (multipart z plikiem) — Chatwoot nada `data_url` i `file_type:"image"`, webhook je przekaże.
- **Timing:** worker działa w pętli (poll). Po wysłaniu wiadomości **poll co ~2 s do ~30 s**
  aż pojawi się nowa outgoing/notatka lub zmieni się status. Nie zakładaj sztywnego sleepa.

### Reference harness (adaptuj — nie kopiuj bezmyślnie)

Napisz mały skrypt Pythona (uruchamiany lokalnie lub na VPS — wygodniej **na VPS**, sieć do CW lokalna),
np. `scratchpad/e2e_livechat.py`. Szkielet:

```python
import requests, time, json
CW = "<CW_BASE>"; ACC = 2; TOK = "<CW_TOKEN>"; INBOX = 18
H = {"api_access_token": TOK}

def nowa_rozmowa(nazwa):
    c = requests.post(f"{CW}/api/v1/accounts/{ACC}/contacts", headers=H,
                      json={"name": nazwa, "identifier": f"e2e-{nazwa}"}).json()
    cid = c["payload"]["contact"]["id"]
    src = c["payload"]["contact"]["contact_inboxes"][0]["source_id"] if c["payload"]["contact"].get("contact_inboxes") else None
    if not src:  # dołóż kontakt do inboxu
        ci = requests.post(f"{CW}/api/v1/accounts/{ACC}/contacts/{cid}/contact_inboxes",
                           headers=H, json={"inbox_id": INBOX}).json()
        src = ci["source_id"]
    conv = requests.post(f"{CW}/api/v1/accounts/{ACC}/conversations", headers=H,
                         json={"inbox_id": INBOX, "contact_id": cid, "source_id": src}).json()
    return conv["id"]

def klient(conv_id, tekst):
    requests.post(f"{CW}/api/v1/accounts/{ACC}/conversations/{conv_id}/messages",
                  headers=H, json={"content": tekst, "message_type": 0})

def czekaj_na_bota(conv_id, po_id=0, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        msgs = requests.get(f"{CW}/api/v1/accounts/{ACC}/conversations/{conv_id}/messages",
                            headers=H).json()["payload"]
        nowe = [m for m in msgs if m["id"] > po_id and (m.get("message_type") == 1 or m.get("private"))]
        if nowe:
            return nowe, max(m["id"] for m in msgs)
        time.sleep(2)
    return [], po_id

def status(conv_id):
    return requests.get(f"{CW}/api/v1/accounts/{ACC}/conversations/{conv_id}",
                        headers=H).json()["status"]
```
> Uwaga: dokładne kształty payloadów (`contact_inboxes`, `source_id`) zweryfikuj empirycznie
> jednym wywołaniem — wersje Chatwoota różnią się. Zbuduj harness iteracyjnie na 1 rozmowie (§3),
> dopiero potem puść matrycę.

---

## 3. Pre‑flight (zanim puścisz 50)

1. Utwórz 1 rozmowę, wyślij „Dzień dobry, czym się różni dąb od jesionu?".
2. Potwierdź, że w ≤40 s pojawia się **outgoing** od bota, sensowny, **bez powitania „jestem Dębuś"**
   (powitanie robi widget, nie bot) i **bez wycieku JSON**.
3. Dopiero gdy to działa — puszczaj matrycę. Jeśli nie działa: sprawdź czy bot przypięty do inboxu 18,
   czy webhook ma `?token=`, logi `docker logs --tail 50 cw-olx-bridge`.

---

## 4. Matryca scenariuszy (~52)

Legenda: **[D]** = asercja deterministyczna (musi przejść), **[L]** = ocena LLM (sensowność).
„→” = kolejne tury klienta. Każdy scenariusz = osobna rozmowa.

### A. Persona / tryby
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S01 | „czy jesteś botem?" | **[D]** NIE handoff, NIE deflect; **[L]** uczciwie: asystent AI wspierający zespół WoodPower |
| S02 | „z kim rozmawiam?" | **[D]** brak deflectu człowieka (guard `_PYTANIE_O_BOTA_RE`); **[L]** uczciwa odpowiedź |
| S03 | „jaki olej polecacie do blatu kuchennego?" | **[L]** odpowiedź doradcza z wiedzy, **[D]** `pozycje` puste (brak wyceny z tematu doradczego) |
| S04 | „ile trwa realizacja?" | **[L]** odpowiedź informacyjna, bez obietnicy konkretnego terminu, bez dopytywania o parametry |
| S05 | „jaka jest pogoda?" (poza tematem) | **[L]** jedno zdanie: pomaga tylko w sprawach WoodPower, wraca do tematu |

### B. Wyzwalacz A — prośba o człowieka
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S06 | „chcę rozmawiać z konsultantem" | **[D]** `DEFLECT_MSG` (miękkie odbicie), status dalej `pending`, `human_deflected=1` |
| S07 | „chcę konsultanta" → „nie, jednak połącz z człowiekiem" | **[D]** tura 2 = **handoff** (status→`open`, notatka), po odbiciu |
| S08 | „dostałem próbki od konsultanta, mam pytanie o olej" | **[D]** NIE handoff/deflect (pasywne `od konsultanta`); **[L]** odpowiada na pytanie |
| S09 | pełna wycena do potwierdzenia → „poproszę konsultanta" | **[D]** w stanie `awaiting_confirm` prośba o człowieka = **handoff od razu** (bez deflectu) |

### C. Reklamacja
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S10 | „chcę złożyć reklamację" | **[D]** `COMPLAINT_MSG` (reklamacje@woodpower.pl + nr zam. + zdjęcia), **BEZ handoffu** (status `pending`), `complaint_sent=1` |
| S11 | „mój blat pękł, kupiłem 2 mies. temu" | **[D]** reklamacja (uszkodzenie+posiadanie) → `COMPLAINT_MSG`, bez handoffu |
| S12 | „czy taki blat może z czasem pęknąć?" | **[D]** NIE reklamacja (brak posiadania); **[L]** normalna odpowiedź przedsprzedażowa |
| S13 | „chcę reklamację" → „ok, wysłałem na reklamacje@woodpower.pl, co dalej?" | **[D]** tura 2 NIE powtarza canned (idzie do LLM), **[L]** sensowny follow‑up |

### D. Sprawy indywidualne → handoff (przepuszczane przez strażnika mimo braku danych)
| # | Klient | Oczekiwane |
|---|---|---|
| S14 | „jaki jest status mojego zamówienia 12345?" | **[D]** handoff (status→`open`, notatka z powodem) |
| S15 | „potrzebuję fakturę do zamówienia" | **[D]** handoff |
| S16 | „chcę zwrócić blat" | **[D]** handoff (`zwrot` łapane, ale „kontakt zwrotny" NIE) |
| S17 | „chcę zmienić adres w moim zamówieniu" | **[D]** handoff (zmiana istniejącego zamówienia) |

### E. Wycena — happy path (1 pozycja)
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S18 | „wycena blatu dębowego 200×60×4, lity, klasa A/B, 1 szt, olejowany" (wszystko naraz) | **[D]** komplet → **deterministyczne `_podsumowanie_msg`** (nie proza LLM) + „Czy wszystko się zgadza?", `awaiting_confirm=1` |
| S19 | S18 → „tak, zgadza się" | **[D]** deterministyczny **handoff** „klient potwierdził dane do wyceny", notatka z pełną specyfikacją, status→`open` |
| S20 | krok po kroku: „chcę wycenę blatu" → „dąb" → „200 na 60" → „grubość 4" → „lity, A/B" → „1 sztuka, olejowany" | **[D]** dopytywanie 1–2 pola/turę (nie zasypuje); na końcu podsumowanie |
| S21 | S18 → „zmień długość na 180" | **[D]** merge (długość 180, reszta zostaje), **nowe** podsumowanie, `awaiting` utrzymane |
| S22 | S18 → „a jaką macie gwarancję?" | **[D]** NIE handoff (pytanie ≠ potwierdzenie, `?` w treści); **[L]** odpowiada, podsumowanie/awaiting bez utraty danych |

### F. Strażnik kompletności / backstop / reaktywne otwory‑krawędzie
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S23 | „ile kosztuje blat?" | **[D]** NIE handoff na samo pytanie o cenę → zaczyna zbierać dane (pyta o produkt/parametry) |
| S24 | „wycena blatu" (bez niczego) | **[L]** pyta najpierw o produkt/wymiary, max 2 rzeczy naraz |
| S25 | pełna konfiguracja + „z 3 otworami pod zlew" | **[D]** `otwory` zapisane i w podsumowaniu; **[D/L]** bot sam NIGDY nie zaproponował otworów wcześniej |
| S26 | pełna konfiguracja + „krawędzie zaokrąglone" | **[D]** `krawedzie` w podsumowaniu; bot nie proponował sam |
| S27 | „blat dąb 200×60×4 lity A/B 1szt olejowany" ale bez wykończenia → dopytać, potem „surowy" | **[D]** „surowe" = komplet wykończenia (nie drąży koloru/połysku) → podsumowanie |

### G. Koperta wymiarów (twarda, w kodzie) + loop‑breaker
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S28 | „blat 200×**150**×4" (szer 150 > 120) | **[D]** odrzucenie: „Maksymalna szerokość … 120 cm … 150 cm. Proszę o korektę" |
| S29 | „blat **500**×60×4, **lity**" (dł lita > 450) | **[D]** odrzucenie z sugestią mikrowczepu |
| S30 | „blat **520**×60×4, mikrowczep" (dł > 500) | **[D]** odrzucenie absolutne 500 |
| S31 | „blat 300×60×4" (bez technologii) → dł 480 | **[D/L]** przy 450–500 bez technologii: dopyta o technologię / powyżej 500 zawsze odrzuć |
| S32 | S28 → ponownie „150" (to samo odrzucenie) | **[D]** 2. raz → dopisek „jeśli w milimetrach, proszę o wartość w cm (np. 65 zamiast 650)" |
| S33 | S28 → „150" → „150" (3×) | **[D]** 3. raz → **handoff** „wymiar poza zakresem — do ustalenia z konsultantem" |
| S34 | S28 → „118" (poprawny) | **[D]** akceptacja, reset licznika odrzuceń, zbieranie leci dalej |
| S35 | „blat 200×60×**6** lity A/B 1szt olejowany" (grubość >4) | **[D]** NIE odrzucone kodem; **[L]** persona: ponadstandardowa, decyzja konsultanta |
| S36 | „blat 200×60×**0,8** …" (grubość <1,5) | **[L]** persona dopytuje/oznacza niestandardową (kod nie waliduje grubości) |

### H. Wielopozycyjna wycena
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S37h | „2 blaty 150×40×4 i 3 parapety 150×30×2, wszystko dąb lity A/B olejowane" | **[D]** 2 pozycje (id 1/2) bez nadpisywania; **[D]** podsumowanie **numerowane** „1. …/2. …"; wspólne cechy zastosowane do obu |
| S38h | S37h → „usuń parapety" | **[D]** pozycja parapetu znika (`usun:true`), zostaje blat |
| S39h | „blat 200×60×4 i parapet 300×**150**×2, oba dąb lity A/B olejowane" | **[D]** odrzucenie wskazuje **którą pozycję** dotyczy (parapet, szer 150) |
| S40h | blat + parapet + „schody 12 stopni…" | **[D]** schody wymagają pola `schody` (nie dł/szer/grub); 3 pozycje |

### I. Schody
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S41s | „wycena schodów dębowych" | **[D/L]** pyta o szczegóły schodów (liczba stopni, wymiar stopnia, podstopnice), **nie** o długość/szerokość/grubość |
| S42s | „schody dąb lity A/B 1 komplet olejowane, 14 stopni 90×30 cm, z podstopnicami" | **[D]** komplet schodów → podsumowanie |

### J. Obrazy (1a semantyczny / 1b próbka / vision inbound)
| # | Klient (tury) | Oczekiwane |
|---|---|---|
| S43 | „czym różni się dąb od buka i jesionu wizualnie?" | **[L/D]** bot dołącza obraz `gatunki_porownanie` (pole `send_image`), obraz realnie wysłany (attachment w wiadomości) |
| S44 | S43 → ponownie pytanie o różnice gatunków | **[D]** obraz `gatunki_porownanie` **NIE** wysłany drugi raz (dedup `sent_images`) |
| S45 | pełna konfiguracja **mająca próbkę** (dobrana w §1, np. dąb lity A/B olejowane) → potwierdzenie | **[D]** do podsumowania **doklejona próbka 1b** (multipart, `_PROBKA_PODPIS` „…próbka … 👇") |
| S46 | pełna konfiguracja **bez pliku** (buk lity lakierowane) → potwierdzenie | **[D]** podsumowanie **bez** próbki (`resolve_sample`=None), tekst i tak poprawny |
| S47 | wyślij **zdjęcie** (attachment image) + „czy taki słój to dąb?" | **[D]** rozmowa zakolejkowana z `attachments`; **[L]** bot odnosi się do treści zdjęcia (vision) |
| S48 | wyślij **PDF** (`file_type:file`) BEZ tekstu | **[D]** **NIE** zakolejkowane (guard `not content and not att`) → brak odpowiedzi bota |
| S49 | wyślij **zdjęcie** BEZ tekstu | **[D]** zakolejkowane (tylko obrazy), **[L]** bot reaguje na obraz |

### K. Bezpieczniki / stan / cisza
| # | Scenariusz | Oczekiwane |
|---|---|---|
| S50 | po handoffie (np. z S19) wyślij kolejną wiadomość klienta gdy status=`open` | **[D]** bot **milczy** (żadnej nowej outgoing) |
| S51 | podwójny webhook: ta sama wiadomość/`message_id` 2× | **[D]** jedna tura (dedup `live_seen`); jeśli sterujesz przez API, zasymuluj przez bezpośredni podwójny POST do `/agent-bot-live` z tym samym `id` |
| S52 | **limit tur** (`BOT_LIVE_MAX_TURNS`=30) | **[D]** po przekroczeniu → handoff „limit tur bota (bezpiecznik)". *Kosztowne:* opcjonalnie tymczasowo ustaw w `bridge.env` niższy `BOT_LIVE_MAX_TURNS` (np. 4), `bridge-deploy.sh`, przetestuj, **przywróć 30 i redeploy**. Odnotuj w raporcie, jeśli pominięte. |

### L. Odporność / edge
| # | Scenariusz | Oczekiwane |
|---|---|---|
| S53 | dowolna tura wyceny — sprawdź wszystkie odpowiedzi | **[D]** NIGDY surowy JSON w treści do klienta (`_znajdz_json`/`_parse_llm` chroni) |
| S54 | podsumowanie → „tak, ale zaokrąglicie krawędzie?" | **[D]** `?` w treści → NIE handoff; **[L]** bot odpowiada na pytanie, nie oddaje po cichu |
| S55 | podsumowanie → „nie, źle policzone" | **[D]** negacja → NIE potwierdzenie, wraca do korekty, nie handoff |

> Numeracja przeskakuje (S37h/S39h itd.) celowo — grupuj w raporcie po literach A–L.

---

## 5. Wykonanie

1. Zbuduj harness (§2), przejdź pre‑flight (§3).
2. Dla każdego scenariusza: świeża rozmowa → wyślij tury → zbierz outgoing/notatki/status →
   zapisz **surowy transkrypt** + wynik asercji (PASS/FAIL/UWAGA) + krótkie uzasadnienie.
3. Scenariusze zależne (S19 od S18, S32/33/34 od S28, S38h od S37h) rób w **tej samej** rozmowie sekwencyjnie.
4. Przy FAIL deterministycznym — **nie naprawiaj w locie**; zapisz dokładny transkrypt + `docker logs`
   z okna czasu tury (do diagnozy w sesji naprawczej).
5. LLM‑zależne oceniaj łagodnie, ale zapisz każdy przypadek „na granicy" (do ewentualnej korekty persony).

---

## 6. Sprzątanie + raport

- **Sprzątanie:** rozmowy testowe rozwiąż/oznacz etykietą `e2e` lub usuń kontakty `e2e-*`
  (Application API `DELETE`), żeby nie śmiecić skrzynki 18. Skrypt harness zapisz do
  `docs/superpowers/` lub scratchpada (nie do produkcyjnego kodu mostu).
- **Raport (artefakt):** tabela wszystkich S## z kolumnami `kategoria | scenariusz | wynik | uwagi`
  + sekcja „FAIL/UWAGI do naprawy" z transkryptami. Podsumowanie „X/Y czysto".
- **Rekomendacja go‑live:** na podstawie wyników — czy przypinać do realnego czatu i czy do
  inboxu 5 (wspólny CRM+sklep) czy dedykowanego. Patrz pamięć `project-chatwoot-livechat-bot`
  („STAN GO‑LIVE").

## 7. Znane pułapki (z historii E2E)

- `message_type:"incoming"` blokowane na WebWidget → używaj `message_type:0` (Application API).
- Bot działa **tylko** przy statusie rozmowy `pending`; po handoffie `open` = cisza. Reset stanu
  (`live_state`/`live_dane`) następuje przy handoffie — powrót `open→pending` startuje bota od zera.
- Env w kontenerze bije default z kodu — jeśli zmieniasz `BOT_LIVE_MAX_TURNS` do testu, pamiętaj
  o `bridge-deploy.sh` po zmianie `bridge.env` i o **przywróceniu** wartości.
- Model gpt‑5.4‑nano: `reasoning_effort=minimal` → błąd 400. Nie ruszaj (`low`).
- Próbki 1b: macierz niepełna — buk/jesion tylko klasa A/B; „buk lity lakierowane" bez pliku →
  brak próbki to POPRAWNE zachowanie (S46), nie bug.
- `gatunki_porownanie.jpg` bez podpisów gatunków — jeśli bot opisuje „na zdjęciu od lewej…",
  a obraz nie ma etykiet, to treść LLM, nie błąd wysyłki.
