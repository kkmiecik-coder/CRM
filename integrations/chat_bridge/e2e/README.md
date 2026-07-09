# E2E quote-bota („Dębuś") — zestaw scenariuszy wielokrotnego użytku

Trwały zestaw testów rozmów end-to-end dla quote-bota na **skrzynce testowej (inbox 18)**.
Wstrzykuje wiadomości klienta przez Chatwoot Application API, wyzwala webhook kandydata i ocenia
odpowiedzi bota — deterministycznie (`oczekuj`) oraz jakościowo przez człowieka (`human`).

## Pliki

- `scenarios.py` — **katalog scenariuszy** (dane, edytowalne). Tu dopisujemy nowe przypadki.
- `harness.py` — silnik (tworzenie rozmowy, wstrzykiwanie tur, polling, ocena).
- `run_e2e.py` — runner CLI (filtry, raport JSON + Markdown, sprzątanie).

## Uruchomienie (na VPS, w sieci dockera kandydata)

Sekrety podajemy przez `--env-file` (NIE na linii poleceń), więc nie trafiają do historii/logów:

```bash
# katalog e2e zmontowany do /e2e, obraz kandydata ma requests
docker run --rm \
  --network chatwoot-test_default \
  --env-file /root/chatwoot-test/bridge-candidate.env \
  -e E2E_INBOX_ID=18 \
  -v /root/chatwoot-test/e2e:/e2e -w /e2e \
  chat-bridge-candidate \
  python run_e2e.py --bez-leadow --md /e2e/raport.md --out /e2e/raport.json --sprzataj
```

Najczęstsze flagi:

- `--lista` — tylko wypisz scenariusze (nic nie wysyła).
- `--bez-leadow` — pomiń scenariusze, które piszą do CRM (patrz niżej).
- `--only V01,V04,S02` — tylko wybrane id.
- `--kat Wariantowa` — cała kategoria.
- `--md raport.md --out raport.json` — zapis raportu.
- `--sprzataj` — po teście ustawia rozmowy testowe na `resolved`.

## ⚠️ Efekt uboczny: zapisy w realnym CRM

Kandydat używa **produkcyjnego** CRM (`crm.woodpower.pl`). Scenariusze oznaczone `tworzy_lead`
doprowadzają do policzonej ceny → bot zapisuje **lead/wycenę** (`chat-<conv_id>`) w CRM (LS-01).
Scenariusze wariantowe (tabela cen) **nie** zapisują — dopiero wybór wariantu + kontakt.

- Chcesz zero zapisów w CRM → uruchom z `--bez-leadow`.
- Uruchamiasz z leadami → posprzątaj testowe rekordy w CRM (klienci `chat-<conv_id>` z raportu).

## Werdykty

- **PASS** — wszystkie asercje `oczekuj` spełnione, brak flagi `human`.
- **REVIEW** — asercje OK, ale scenariusz wymaga oceny jakościowej człowieka (persona/merytoryka).
- **FAIL** — złamana asercja (np. cisza bota, brak wymaganego fragmentu, zły status).

## Rozwijanie

Dopisz nowy scenariusz do `SCENARIUSZE` w `scenarios.py` (schemat w docstringu pliku).
Trzymaj `id` unikalne. Deterministyczne asercje dawaj tam, gdzie zachowanie gwarantuje kod;
tam gdzie decyduje LLM/persona — użyj `human` + miękkich guardów (`min_odp`, `nie_zawiera`).
