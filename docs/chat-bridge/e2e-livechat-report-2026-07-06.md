# Raport E2E — bot live-chat „Dębuś" (Chatwoot inbox 18 ↔ OpenAI)

**Data:** 2026-07-06 · **Wykonawca:** Claude Code (osobna sesja) · **Model bota:** `gpt-5.4-nano` · **MAX_TURNS:** 30
**Środowisko:** skrzynka TESTOWA — inbox **18** „Wsparcie Woodpower — TESTY", account 2 (bot 3 „WoodPower AI - LIVE CHAT" przypięty potwierdzony). Inbox 5 (realny) NIE dotknięty.
**Metoda:** wstrzykiwanie wiadomości klienta przez Application API (`message_type:0` = incoming), odczyt outgoing/notatek/statusu; scenariusze obrazowe i dedup przez wewnętrzny webhook `/agent-bot-live`. Każdy scenariusz = świeży kontakt/rozmowa. Harness: `scratchpad/e2e_livechat.py` + `e2e_images.py` (surowe transkrypty w `scratchpad/e2e_b1..b3.json`, `e2e_img.json`).

## Podsumowanie: **50 / 55 czysto**

| Wynik | Liczba | Scenariusze |
|---|---|---|
| ✅ PASS (czysto) | 50 | wszystkie poza niżej |
| ❌ FAIL (deterministyczny) | 1 | **S17** |
| ⚠️ UWAGA (LLM/persona) | 3 | **S35, S36, S54** |
| ⏭️ POMINIĘTE (decyzja usera) | 1 | **S52** (wymaga restartu żywego bridge) |

Wszystkie **deterministyczne kontrakty kodu przeszły** poza S17: koperta wymiarów, loop-breaker (2× hint mm / 3× handoff), deflect→handoff człowieka, reklamacja-raz-bez-handoffu, cisza po handoffie, dedup wiadomości i obrazów, deterministyczne podsumowanie, potwierdzenie→handoff, próbka 1b (jest/brak), brak wycieku JSON — potwierdzone na żywym bocie.

---

## Tabela pełna

### A. Persona / tryby
| # | Wynik | Uwagi |
|---|---|---|
| S01 „czy jesteś botem?" | ✅ | Uczciwie: „asystent AI wspomagający zespół WoodPower". Brak handoff/deflect. |
| S02 „z kim rozmawiam?" | ✅ | Uczciwa odpowiedź, brak deflectu człowieka (guard `_PYTANIE_O_BOTA_RE`). |
| S03 „jaki olej do blatu?" | ✅ | Doradza (Osmo/lakier), `pozycje` puste — brak wyceny z tematu doradczego. |
| S04 „ile trwa realizacja?" | ✅ | Podał widełki z KB (16–21 / 28–30 dni) + „potwierdzamy indywidualnie". Brak sztywnej obietnicy, brak dopytywania o parametry. |
| S05 „jaka pogoda?" | ✅ | Jedno zdanie: pomaga tylko w sprawach WoodPower. |

### B. Wyzwalacz A — prośba o człowieka
| # | Wynik | Uwagi |
|---|---|---|
| S06 „chcę konsultanta" | ✅ | `DEFLECT_MSG` co do joty, status `pending`. |
| S07 deflect → „połącz z człowiekiem" | ✅ | Tura 2 = handoff (notatka + `CLOSING_MSG`), status→`open`. |
| S08 „dostałem próbki od konsultanta…" | ✅ | Pasywna wzmianka NIE wyzwala handoffu; odpowiada na pytanie o olej. |
| S09 podsumowanie → „poproszę konsultanta" | ✅ | W `awaiting_confirm` prośba o człowieka = handoff od razu (bez deflectu). |

### C. Reklamacja
| # | Wynik | Uwagi |
|---|---|---|
| S10 „chcę reklamację" | ✅ | `COMPLAINT_MSG` (reklamacje@woodpower.pl), status `pending` (bez handoffu). |
| S11 „blat pękł, kupiłem 2 mies. temu" | ✅ | Uszkodzenie+posiadanie → `COMPLAINT_MSG`, bez handoffu. |
| S12 „czy blat może z czasem pęknąć?" | ✅ | NIE reklamacja (brak posiadania) — normalna odpowiedź przedsprzedażowa. |
| S13 reklamacja → follow-up | ✅ | Tura 2 NIE powtarza canned — sensowny follow-up z LLM. |

### D. Sprawy indywidualne → handoff
| # | Wynik | Uwagi |
|---|---|---|
| S14 „status zamówienia 12345?" | ✅ | Handoff, notatka z powodem, `open`. |
| S15 „faktura do zamówienia" | ✅ | Handoff. |
| S16 „chcę zwrócić blat" | ✅ | Handoff (`zwrot` łapane). |
| **S17 „zmień adres w moim zamówieniu"** | ❌ **FAIL** | Oczekiwano handoff. Bot spytał *„co dokładnie mamy wycenić (blat, parapet czy schody)"*, status `pending`. **Przyczyna:** guard `_POWOD_PRZEPUSC` (regex `zmian\w* zam`) nie dopasował powodu w stylu „zmiana **adresu** w zamówieniu" (brak sąsiedztwa „zmiana"↔„zam"), więc handoff LLM potraktowany jako roszczenie o „komplet danych" → backstop zapytał o produkt. |

### E. Wycena — happy path
| # | Wynik | Uwagi |
|---|---|---|
| S18 pełna wycena naraz | ✅ | Deterministyczne `_podsumowanie_msg` + „Czy wszystko się zgadza?", `awaiting_confirm`, próbka 1b doklejona. |
| S19 S18 → „tak, zgadza się" | ✅ | Handoff „klient potwierdził dane", notatka z pełną specyfikacją, `open`. |
| S20 krok po kroku | ✅ | Dopytywanie 1–2 pola/turę, na końcu podsumowanie. |
| S21 S18 → „zmień długość na 180" | ✅ | Merge (180, reszta zostaje), nowe podsumowanie, `awaiting` utrzymane. |
| S22 S18 → „jaką gwarancję?" | ✅ | NIE handoff, odpowiada (24 mc), dane nienaruszone. |

### F. Strażnik / reaktywne otwory-krawędzie
| # | Wynik | Uwagi |
|---|---|---|
| S23 „ile kosztuje blat?" | ✅ | NIE handoff — zaczyna zbierać dane. |
| S24 „wycena blatu" | ✅ | Pyta o wymiary/ilość, max 2 rzeczy. |
| S25 + „3 otwory pod zlew" | ✅ | `otwory` w podsumowaniu; bot nie proponował sam. |
| S26 + „krawędzie zaokrąglone" | ✅ | `krawedzie` w podsumowaniu; nie proponował sam. |
| S27 bez wykończenia → „surowy" | ✅ | „surowe" = komplet (nie drąży koloru/połysku) → podsumowanie. |

### G. Koperta wymiarów + loop-breaker
| # | Wynik | Uwagi |
|---|---|---|
| S28 szer 150 > 120 | ✅ | Odrzucenie: „Maksymalna szerokość … 120 cm … 150 cm. Proszę o korektę". |
| S29 lita 500 > 450 | ✅ | Odrzucenie z sugestią mikrowczepu. |
| S30 mikrowczep 520 > 500 | ✅ | Odrzucenie absolutne 500. |
| S31 300→480 bez technologii | ✅ | 480 ≤ 500 (kod nie odrzuca); LLM dopytuje o technologię (lita/mikrowczep). |
| S32 S28 → ponownie 150 | ✅ | 2. raz → dopisek o milimetrach. |
| S33 S28 → 150 ×3 | ✅ | 3. raz → handoff „wymiar poza zakresem — do ustalenia z konsultantem". |
| S34 S28 → 118 | ✅ | Akceptacja, reset licznika, podsumowanie. |
| **S35 grubość 6 (>4)** | ⚠️ | [D] kod NIE odrzuca — OK. [L] persona **nie oznaczyła** 6 cm jako ponadstandardowej/decyzji konsultanta (od razu podsumowanie). Do dostrojenia persony. |
| **S36 grubość 0,8 (<1,5)** | ⚠️ | [D] kod nie waliduje grubości — OK. [L] persona **nie zakwestionowała** 8 mm jako niestandardowej (od razu podsumowanie). Do dostrojenia persony. |

### H. Wielopozycyjna wycena
| # | Wynik | Uwagi |
|---|---|---|
| S37h 2 blaty + 3 parapety | ✅ | 2 pozycje (id 1/2) bez nadpisywania, podsumowanie **numerowane** „1./2.", cechy wspólne zastosowane do obu. |
| S38h → „usuń parapety" | ✅ | Parapet znika (`usun:true`), zostaje blat, nowe (nienumerowane) podsumowanie. |
| S39h parapet 300×150 | ✅ | Odrzucenie wskazuje pozycję: „Dotyczy pozycji: parapet". |
| S40h blat + parapet + schody | ✅ | Schody rozpoznane jako osobna pozycja z polem `schody` (pyta o grubość stopnia/podstopnice), 3 pozycje. |

### I. Schody
| # | Wynik | Uwagi |
|---|---|---|
| S41s „wycena schodów dębowych" | ✅ | Pyta o klasę/technologię + liczbę stopni/wymiar stopnia — NIE o dł/szer/grub. |
| S42s pełne schody | ✅ | Komplet → podsumowanie (blok „Schody: 14 stopni…"). |

### J. Obrazy (1a semantyczny / 1b próbka / vision inbound)
| # | Wynik | Uwagi |
|---|---|---|
| S43 „różnice gatunków wizualnie" | ✅ | Dołączony obraz `gatunki_porownanie` (attachment realnie w wiadomości). |
| S44 S43 → ponowne pytanie | ✅ | Obraz **NIE** wysłany drugi raz (dedup `sent_images`). |
| S45 config z próbką → potwierdzenie | ✅ | Do podsumowania doklejona próbka 1b (`dab_lity_ab_olejowane`, podpis „…próbka … 👇"). |
| S46 buk lity lakierowane → potwierdzenie | ✅ | Podsumowanie **bez** próbki (`resolve_sample`=None dla braku pliku), tekst poprawny; potwierdzenie → handoff. |
| S47 zdjęcie + „czy to dąb?" | ✅ | Vision: bot odnosi się do zdjęcia („na podstawie rysunku słojów … wygląda na dąb"). |
| S48 „PDF" (file) bez tekstu | ✅ | NIE zakolejkowane (`not content and not att`) → cisza. |
| S49 zdjęcie bez tekstu | ✅ | Zakolejkowane (tylko obrazy) → bot reaguje na obraz. |

> Uwaga metodyczna: Application API na inboxie WebWidget odrzuca tworzenie wiadomości `incoming` z załącznikiem (422 „Incoming messages are only allowed in Api inboxes"), a integer `message_type:0` niemożliwy w multiparcie. Dlatego S47/S48/S49 wykonano przez wstrzyknięcie tury do webhooka `/agent-bot-live` z prawdziwym, pobieralnym `data_url` obrazu — testuje realny guard webhooka + worker + vision.

### K. Bezpieczniki / stan / cisza
| # | Wynik | Uwagi |
|---|---|---|
| S50 wiadomość po handoffie (status `open`) | ✅ | Bot **milczy** (0 outgoing). |
| S51 podwójny webhook, ten sam `message_id` | ✅ | Jedna tura (dedup `live_seen`) — dokładnie 1 odpowiedź. |
| **S52 limit tur (MAX_TURNS=30)** | ⏭️ POMINIĘTE | Wymaga chwilowej zmiany `bridge.env` + restartu żywego kontenera (OLX/Allegro/Mail). Decyzja usera: pominąć. Logika potwierdzona z kodu: `run_livechat_turn` → `if _bot_turns >= BOT_LIVE_MAX_TURNS: _do_handoff(..., "limit tur bota (bezpiecznik)")`. |

### L. Odporność / edge
| # | Wynik | Uwagi |
|---|---|---|
| S53 brak surowego JSON | ✅ | Skan wszystkich odpowiedzi (55 rozmów) — zero wycieku JSON do klienta. |
| **S54 podsumowanie → „tak, ale czy zaokrąglicie krawędzie?"** | ⚠️ | [D] `?` → NIE handoff — OK (status `pending`). [L] bot **nie odpowiedział** na pytanie o krawędzie — zamiast tego ponowił podsumowanie. Przyczyna = artefakt „Kontakt" (patrz niżej): LLM dopisał `kontakt` → `zmienione=True` → kod ponowił podsumowanie zamiast puścić odpowiedź. |
| S55 podsumowanie → „nie, źle policzone" | ✅ | Negacja → NIE potwierdzenie; wraca do korekty, bez handoffu. |

---

## FAIL / UWAGI do naprawy (dla sesji naprawczej)

### ❌ S17 — zmiana adresu w zamówieniu nie trafia do handoffu (deterministyczny)
- **Transkrypt:** klient: „chcę zmienić adres dostawy w moim zamówieniu" → bot: „Żeby przygotować wycenę, potrzebuję jeszcze: co dokładnie mamy wycenić (blat, parapet czy schody)." (status `pending`).
- **Diagnoza:** `bots/livechat.py`, `_POWOD_PRZEPUSC` = `…|zmian\w* zam|…`. LLM ustawia `handoff=true`, ale `powod` brzmi „zmiana adresu w zamówieniu klienta" — „zmiana" nie sąsiaduje z „zam", więc regex nie łapie → `_czy_powod_kompletu`=True → strażnik traktuje to jak roszczenie o komplet danych → backstop pyta o produkt (bo brak pozycji).
- **Sugestia fix:** rozluźnić wzorzec, np. dodać alternatywę `zmian\w*.*zam(ówieni|owieni)` lub osobny człon `adres\w*.*(zam|dostaw|zamówieni)` / `zmian\w* (adres|danych|dostaw)`. Uwaga na regresję „kontakt zwrotny" (celowo NIE łapany) i inne wyceny.

### ⚠️ Artefakt „Kontakt" w podsumowaniu (systemowy, minor→moderate)
- **Objaw:** LLM wypełnia pole wspólne `kontakt` treścią z tożsamości kontaktu (identifier/`name`, np. „e2e-S19-…", „E2E S22") albo meta-instrukcją („Proszę podać e-mail…"). Widoczne w S09, S19, S20, S21, S22, S26, S36, S42s, S50, **S54**.
- **Dlaczego to nie tylko kosmetyka:** w **S54** dopisanie `kontakt` zmieniło `dane` → `zmienione=True` → kod ponowił deterministyczne podsumowanie **zamiast** odpowiedzieć na pytanie klienta o krawędzie. Czyli artefakt potrafi zdławić odpowiedź w stanie `awaiting_confirm`.
- **Sugestia fix:** (a) w promptcie/`_FORMAT` zabronić wnioskowania `kontakt` z bloku tożsamości (tylko gdy klient sam poda telefon/e-mail); i/lub (b) przy porównaniu `zmienione` ignorować pola „wspólne" nie-krytyczne (kontakt/termin), żeby zmiana kontaktu nie ponawiała podsumowania i nie blokowała normalnej odpowiedzi. W produkcji kontakt WebWidget bywa auto-generowany, więc problem wyjdzie też na realnym ruchu.

### ⚠️ S35 / S36 — persona nie oznacza grubości spoza standardu
- Kod świadomie nie waliduje grubości (koperta tylko szer/dł). Persona miała oznaczać >4 cm jako ponadstandardową (decyzja konsultanta) i <1,5 cm jako niestandardową. Bot od razu podsumował bez adnotacji. **Sugestia:** dopisać do persony regułę komentowania grubości poza 1,5–4 cm (nie odrzucać). Priorytet niski.

---

## Rekomendacja go-live

1. **Przed przypięciem do realnego czatu** naprawić **S17** (mała zmiana regexa) oraz **artefakt „Kontakt"** (bo dotyka realnego ruchu i potrafi zdławić odpowiedź). To jedyne dwie rzeczy z realnym wpływem na klienta.
2. **S35/S36** (adnotacje grubości) — kosmetyka persony, może pójść po go-live.
3. **S52** (limit tur) — dokończyć przy najbliższym oknie serwisowym bridge (MAX_TURNS=4 → recreate → test → przywróć 30). Logika i tak potwierdzona z kodu.
4. **Inbox:** rdzeń konwersacyjny (persona, wyceny na pozycjach, koperta, handoffy, obrazy, vision) działa solidnie — 50/55 czysto, 0 wycieków JSON, 0 błędnych handoffów poza S17. Zalecenie: pierwsze przypięcie na **dedykowanym inboxie** (jak inbox 18), a nie od razu na współdzielonym inboxie 5 (CRM+sklep) — mniejsze ryzyko przy realnym ruchu; po tygodniu obserwacji rozważyć inbox 5. (Patrz pamięć `project-chatwoot-livechat-bot`, „STAN GO-LIVE".)

## Sprzątanie
- Usunięto 58 kontaktów testowych `e2e-*`/`E2E *` (dokładne id z transkryptów) → rozmowy testowe zniknęły z inboxu 18.
- Usunięto harness z kontenera (`/app/e2e_*.py`) i VPS (`/root/e2e_*.py`) oraz wyniki z `/data`; kopie surowych transkryptów zostają w `scratchpad/`.
- Bridge nietknięty: `BOT_LIVE_MAX_TURNS=30`, kontener nie restartowany (zmiana S52 nigdy nie weszła). Realny inbox 5 nietknięty.
