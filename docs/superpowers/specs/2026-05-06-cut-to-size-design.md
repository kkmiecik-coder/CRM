# Spec: Pole "Docięcie do wymiaru" w kalkulatorze i wycenach

**Data:** 2026-05-06
**Status:** Zatwierdzony do implementacji
**Zakres:** kalkulator + quotes (modal szczegółów, PDF oferty, strona klienta). Moduł produkcji — w osobnej iteracji.

## Cel

Dodać per-produkt flagę `cut_to_size` (Tak/Nie) — informację, czy produkt ma być docięty do wymiaru z kalkulatora, czy klient sam dotnie. Pole nie wpływa na cenę. Domyślnie `Tak` (standard). Wartość `Nie` to odstępstwo (klient zamawia w przybliżonym wymiarze i sam dotina).

## Model danych

### Tabela `quote_items_details`

Dodać kolumnę:

```sql
ALTER TABLE quote_items_details
  ADD COLUMN cut_to_size BOOLEAN NOT NULL DEFAULT TRUE;
```

Backfill istniejących rekordów (DEFAULT TRUE załatwia, ale jawnie dla pewności):

```sql
UPDATE quote_items_details SET cut_to_size = TRUE WHERE cut_to_size IS NULL;
```

**Migracja produkcji:** Auto-migracje na produkcji są zawodne — wykonać powyższe zapytania ręcznie po deployu.

### Model SQLAlchemy

Plik: `modules/calculator/models.py` — klasa `QuoteItemDetails`:

```python
cut_to_size = db.Column(db.Boolean, nullable=False, default=True)
```

`to_dict()` rozszerzony o:

```python
'cut_to_size': bool(self.cut_to_size),
```

### Brak osobnego pola w `quote_items`

Pole semantycznie pasuje do "details" (jak `finishing_*`, `edges_*`, `shape`). Wszystkie ścieżki, które wczytują `details`, dostaną `cut_to_size` automatycznie po dorzuceniu do `to_dict()`.

## UI: Kalkulator

**Lokalizacja:** `modules/calculator/templates/calculator.html`, sekcja `.finishing-section` — **pierwszy element pod `<h2>Wykończenie</h2>`**, przed `#finishing-tree-container`.

**Komponent:** Toggle Tak/Nie w stylu istniejącego przełącznika `quote_type` (brutto/netto). Para przycisków radio-like.

**Etykieta:** "Docięcie do wymiaru:"

**Stan domyślny:** `Tak`.

**Per-produkt:** Każdy produkt w kalkulatorze ma własny stan toggle'a — trzymany w obiekcie produktu w stanie JS, obok `finishing_*`.

**Kopiowanie produktu:** Funkcja "kopiuj produkt" musi przenieść `cut_to_size` razem z resztą atrybutów.

**Brak wpływu na cenę:** Zmiana toggle'a nie triggeruje rekalkulacji ceny ani podsumowania wykończenia. Niezależny od drzewka wykończenia (reset wykończenia nie zmienia `cut_to_size`).

### Persistence: `CalculatorDraft`

Pole leci do `draft_data` (JSON) wraz z resztą stanu produktu. Auto-zapis drafta (już istnieje) zacznie zapisywać pole automatycznie, jeśli serializacja jest generyczna; jeśli pola są wymieniane jawnie — dorzucić.

### Persistence: zapis wyceny (save_quote)

Pole `cut_to_size` leci w payloadzie produktu z JS do backendu. Backend zapisuje w `QuoteItemDetails.cut_to_size`.

### Edycja wyceny (`quote_edit_loader.js`)

Wczytanie produktu odczytuje `details.cut_to_size` z payloadu i ustawia stan toggle'a. Brak wartości → default `true` (zgodnie z backfillem).

## UI: Modal szczegółów wyceny w `/quotes/`

**Lokalizacja:** `modules/quotes/static/js/quotes.js` — sekcja budująca tabelę "Wykończenie" (~linia 2772-2798).

**Zmiana:** **Pierwszy wiersz tabeli "Wykończenie"** — wstawiany zawsze, niezależnie od `hasFinishing`:

```javascript
const cutToSize = finishing && finishing.cut_to_size === false ? false : true;
const cutToSizeLabel = cutToSize ? 'Tak' : '<strong>Nie</strong>';
let firstRow = '<tr><td>Docięcie do wymiaru</td><td>' + cutToSizeLabel + '</td></tr>';
```

Wiersz dołączany na początku zarówno gałęzi `hasFinishing`, jak i fallbacku "Surowe / Brak …".

**Stylistyka:**
- "Tak" — normalny styl tekstu (jak reszta wartości).
- "Nie" — pogrubione (`<strong>`).

**Fallback:** `finishing == null` lub brak `cut_to_size` w payloadzie → wyświetl "Tak".

### Backend serwujący dane modala

Serwis zwracający szczegóły wyceny (kandydat: `modules/quotes/services/`) musi dołączyć `cut_to_size` w obiekcie reprezentującym wykończenie/produkt. Jeśli korzysta z `QuoteItemDetails.to_dict()` — załatwione automatycznie.

## Widoczność dla klienta: PDF + strona klienta

**Reguła:** Pokazujemy tylko gdy `cut_to_size === false`. Gdy `Tak` — nic nie wyświetlamy (default, zero szumu).

### `offer_pdf.html`

`modules/quotes/templates/offer_pdf.html` — w sekcji każdego produktu, po bloku "Wykończenie":

```jinja
{% if not item.details.cut_to_size %}
  <div class="cut-to-size-info">Docięcie do wymiaru: <strong>Nie</strong></div>
{% endif %}
```

(Dokładna ścieżka do pola w kontekście Jinja zależna od tego, jak template ma wstrzykiwane dane — do potwierdzenia w fazie implementacji.)

### `client_quote.js`

`modules/quotes/static/js/client_quote.js` — w miejscach renderujących "Wykończenie" (linie 670, 688, 752, 768) dodać warunkowy wiersz pokazywany tylko dla `cut_to_size === false`.

**Stylistyka:** Drobny, neutralny — informacja, nie ostrzeżenie. Konkretny styl do dopracowania w trakcie implementacji.

## Poza zakresem

- **Moduł produkcji** (`modules/production/`) — integracja w osobnej iteracji.
- **Wpływ na cenę** — pole bez wpływu na kalkulację.
- **Tryb porównania wersji wyceny** — pole automatycznie znajdzie się w snapshotach wersji jako część `QuoteItemDetails`; brak dodatkowych zmian.

## Plan testów (high-level)

1. Migracja: ALTER TABLE wykonuje się czysto; wszystkie istniejące rekordy mają `TRUE`.
2. Nowa wycena: nowy produkt ma `cut_to_size=true`; toggle przełącza stan.
3. Save → reload (edycja): wartość zachowana.
4. Kopiowanie produktu: `cut_to_size` skopiowany.
5. Draft auto-zapis: pole obecne w `draft_data`.
6. Modal `/quotes/`: zawsze widoczny pierwszy wiersz "Docięcie do wymiaru"; "Nie" pogrubione.
7. PDF + strona klienta: brak wzmianki gdy `Tak`; widoczna informacja gdy `Nie`.
8. Historyczne wyceny (sprzed wdrożenia): wyświetlają "Tak" (po backfillu).

## Deployment

1. Merge do `main` → auto-deploy.
2. **Ręcznie na produkcji:** wykonać `ALTER TABLE` z sekcji "Model danych".
3. Smoke test: nowy produkt w kalkulatorze, zapis, edycja, podgląd w `/quotes/`.
