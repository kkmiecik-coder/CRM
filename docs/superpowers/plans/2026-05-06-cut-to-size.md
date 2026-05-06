# "Docięcie do wymiaru" — Plan implementacji

> **Dla agenta wykonującego:** WYMAGANY SUB-SKILL: `superpowers:subagent-driven-development` (rekomendowany) lub `superpowers:executing-plans`. Kroki używają checkbox `- [ ]`.

**Cel:** Dodać per-produkt flagę `cut_to_size` (Tak/Nie) do kalkulatora i wycen — toggle w sekcji "Wykończenie", widoczny w modalu szczegółów wyceny zawsze, w PDF/widoku klienta tylko gdy "Nie".

**Architektura:** Nowa kolumna `cut_to_size BOOLEAN NOT NULL DEFAULT TRUE` w `quote_items_details`. Toggle radio (wzór `priceMode` brutto/netto) na początku `.finishing-section`. Stan trzymany w `dataset.cutToSize` na `.quote-form`. Pole dołączone do payloadu draft/save/load oraz do `to_dict()`.

**Tech Stack:** Flask + SQLAlchemy + Jinja, MySQL, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-05-06-cut-to-size-design.md`

**Uwaga o testach:** Projekt nie ma frameworka testowego (brak `tests/`, brak `pytest.ini`). Weryfikacja przez smoke test w przeglądarce + sprawdzenie SQL na bazie lokalnej. Każde zadanie kończy się commitem.

---

## Task 1: Migracja bazy danych

**Files:**
- Modify: `modules/calculator/models.py:701-737` (dodanie kolumny do modelu)
- Migration SQL: wykonywana ręcznie przez `flask shell` lub bezpośrednio w MySQL

- [ ] **Krok 1: Dodać kolumnę do modelu `QuoteItemDetails`**

W `modules/calculator/models.py`, w klasie `QuoteItemDetails` (zaczyna się w linii 701), pod istniejącym blokiem pól `lamella_direction`, dodać:

```python
    # Docięcie do wymiaru (czy klient otrzymuje produkt docięty do wymiaru z kalkulatora)
    cut_to_size = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
```

Wstawić **przed** linią `__table_args__ = (`.

- [ ] **Krok 2: Rozszerzyć `to_dict()` o nowe pole**

W tej samej klasie, w metodzie `to_dict()` (linia 739), dodać klucz w zwracanym słowniku — przed `'lamella_direction':`:

```python
            'cut_to_size': bool(self.cut_to_size),
```

- [ ] **Krok 3: Wykonać migrację na bazie lokalnej**

Uruchomić w MySQL (XAMPP) na bazie `woodpower_crm_local`:

```sql
ALTER TABLE quote_items_details
  ADD COLUMN cut_to_size BOOLEAN NOT NULL DEFAULT TRUE;
```

Weryfikacja:

```sql
DESCRIBE quote_items_details;
SELECT id, product_index, cut_to_size FROM quote_items_details LIMIT 5;
```

Oczekiwane: kolumna `cut_to_size` typu `tinyint(1)`, wszystkie istniejące wiersze mają `1`.

- [ ] **Krok 4: Przygotować SQL do wykonania na produkcji**

Stworzyć notatkę w `docs/superpowers/migrations/2026-05-06-cut-to-size.sql` z dokładnym zapytaniem do ręcznego wykonania na produkcji po deployu:

```sql
-- Migracja: dodanie pola cut_to_size do quote_items_details
-- Data: 2026-05-06
-- Wykonać RĘCZNIE na produkcji po wdrożeniu kodu (auto-migracje są zawodne).

ALTER TABLE quote_items_details
  ADD COLUMN cut_to_size BOOLEAN NOT NULL DEFAULT TRUE;

-- Weryfikacja:
-- DESCRIBE quote_items_details;
-- SELECT COUNT(*) FROM quote_items_details WHERE cut_to_size = TRUE;
```

- [ ] **Krok 5: Commit**

```bash
git add modules/calculator/models.py docs/superpowers/migrations/2026-05-06-cut-to-size.sql
git commit -m "feat(calculator): pole cut_to_size w modelu QuoteItemDetails

Migracja dodająca kolumnę cut_to_size BOOLEAN NOT NULL DEFAULT TRUE.
SQL produkcyjny w docs/superpowers/migrations/."
```

---

## Task 2: Backend — zapis przy save_quote (nowa wycena)

**Files:**
- Modify: `modules/calculator/services/quote_service.py:595-618` (konstruktor `QuoteItemDetails` przy zapisie)
- Modify: `modules/calculator/services/quote_service.py` (odczyt z `product` payload przed konstrukcją)

- [ ] **Krok 1: Odczyt `cut_to_size` z payloadu produktu**

W `modules/calculator/services/quote_service.py`, w funkcji `save_quote` (zawierającej linię 595), przed konstrukcją `QuoteItemDetails(...)` dodać odczyt:

```python
            # Docięcie do wymiaru (default True — klient dostaje produkt docięty)
            cut_to_size = product.get('cut_to_size')
            if cut_to_size is None:
                cut_to_size = True
            else:
                cut_to_size = bool(cut_to_size)
```

Umieścić to bezpośrednio przed blokiem `# Szczegóły produktu (wykończenie + krawędzie + kształt)` (linia ~594).

- [ ] **Krok 2: Przekazać do konstruktora `QuoteItemDetails`**

W tej samej funkcji, w wywołaniu `QuoteItemDetails(...)` (linia 595), dodać po `lamella_direction=lamella_direction,`:

```python
                cut_to_size=cut_to_size,
```

- [ ] **Krok 3: Smoke test (po Tasku 6 — gdy frontend wyśle pole)**

Manualny check po wdrożeniu zmian frontendowych — pominąć teraz, oznaczyć przez TODO w pamięci.

- [ ] **Krok 4: Commit**

```bash
git add modules/calculator/services/quote_service.py
git commit -m "feat(calculator): zapis cut_to_size w save_quote

Default TRUE gdy pole nie ma w payloadzie (kompat z draftami sprzed wdrożenia)."
```

---

## Task 3: Backend — zapis przy edycji wyceny (update path)

**Files:**
- Modify: `modules/calculator/services/quote_service.py:269-357` (funkcja edytująca produkt — gałąź update i create)

- [ ] **Krok 1: Znaleźć funkcję update**

Otworzyć `modules/calculator/services/quote_service.py`, znaleźć funkcję zaczynającą się w okolicy linii 247 (zawiera blok `# Aktualizuj lub utworz QuoteItemDetails` w linii 269). Funkcja ma dwie gałęzie: `if detail:` (update istniejącego — linia ~270) i `else:` (create nowego — linia ~333).

- [ ] **Krok 2: Odczytać `cut_to_size` z `product_data`**

Przed blokiem `if detail:`, dodać:

```python
    # Docięcie do wymiaru (default True)
    cut_to_size = product_data.get('cut_to_size')
    if cut_to_size is None:
        cut_to_size = True
    else:
        cut_to_size = bool(cut_to_size)
```

Konkretne miejsce: tuż przed `detail = QuoteItemDetails.query.filter_by(` (linia 270). Sprawdzić nazwę zmiennej źródłowej w funkcji — jeśli zamiast `product_data` jest `product`, użyć tej nazwy.

- [ ] **Krok 3: Update gałąź — przypisać pole**

W bloku `if detail:` (po `detail.lamella_direction = lamella_direction` w linii 331), dodać:

```python
        detail.cut_to_size = cut_to_size
```

- [ ] **Krok 4: Create gałąź — przekazać do konstruktora**

W bloku `else:` w wywołaniu `QuoteItemDetails(...)` (linia 333), po `lamella_direction=lamella_direction,` dodać:

```python
            cut_to_size=cut_to_size,
```

- [ ] **Krok 5: Commit**

```bash
git add modules/calculator/services/quote_service.py
git commit -m "feat(calculator): zapis cut_to_size w trybie edycji wyceny

Zarówno update istniejącego QuoteItemDetails, jak i tworzenie nowego."
```

---

## Task 4: Frontend — toggle HTML w sekcji "Wykończenie"

**Files:**
- Modify: `modules/calculator/templates/calculator.html:402-417` (sekcja `.finishing-section`)
- Modify: `modules/calculator/static/css/calculator_brutto_netto.css` lub osobny CSS dla nowego togglu (decyzja w trakcie)

- [ ] **Krok 1: Dodać HTML togglu na początku sekcji**

W `modules/calculator/templates/calculator.html`, między `<h2 class="title-with-underline-h2">Wykończenie</h2>` (linia 404) a `<!-- Dynamiczne drzewko wykończeń...` (linia 406), wstawić:

```html
                                <!-- Toggle: docięcie do wymiaru (per produkt, default Tak) -->
                                <div class="cut-to-size-toggle-wrapper">
                                    <label class="input-txt">Docięcie do wymiaru:</label>
                                    <div class="toggle-switch cut-to-size-toggle">
                                        <input type="radio" class="cut-to-size-radio" name="cutToSize" value="yes" checked>
                                        <label class="toggle-option toggle-option-active">Tak</label>
                                        <input type="radio" class="cut-to-size-radio" name="cutToSize" value="no">
                                        <label class="toggle-option">Nie</label>
                                        <div class="toggle-slider"></div>
                                    </div>
                                </div>
```

**Uwaga o `name="cutToSize"`:** Każdy `.quote-form` ma własną kopię — kalkulator ma zwykle jeden formularz aktywny w workspace. Przy klonowaniu (`addNewProduct`) JS musi ustawić unikalne `name` lub trzymać selekcję bez konfliktu (sprawdzić w Tasku 5 jak działa istniejący `priceMode` i naśladować). Alternatywa: użyć `data-field="cutToSize"` zamiast radio (jeden checkbox/toggle).

- [ ] **Krok 2: Dodać `data-field="cutToSize"` do `.quote-form` jako początkowy stan**

W `modules/calculator/templates/calculator.html:113`, do `<div class="quote-form" data-product-shape="rectangular">` dodać atrybut:

```html
                        <div class="quote-form" data-product-shape="rectangular" data-cut-to-size="true">
```

- [ ] **Krok 3: CSS — styl togglu**

Dodać do nowego pliku `modules/calculator/static/css/cut_to_size_toggle.css`:

```css
.cut-to-size-toggle-wrapper {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}

.cut-to-size-toggle {
    position: relative;
    display: inline-flex;
    background: #f0f0f0;
    border-radius: 6px;
    padding: 2px;
}

.cut-to-size-toggle input[type="radio"] {
    display: none;
}

.cut-to-size-toggle .toggle-option {
    padding: 6px 16px;
    cursor: pointer;
    z-index: 1;
    font-weight: 500;
    color: #555;
    transition: color 0.2s;
}

.cut-to-size-toggle input[value="yes"]:checked ~ label:nth-of-type(1),
.cut-to-size-toggle input[value="no"]:checked ~ label:nth-of-type(2) {
    color: #fff;
}

.cut-to-size-toggle input[value="yes"]:checked ~ .toggle-slider {
    transform: translateX(0);
}

.cut-to-size-toggle input[value="no"]:checked ~ .toggle-slider {
    transform: translateX(100%);
}

.cut-to-size-toggle .toggle-slider {
    position: absolute;
    top: 2px;
    left: 2px;
    width: calc(50% - 2px);
    height: calc(100% - 4px);
    background: #ED6B24;
    border-radius: 4px;
    transition: transform 0.2s;
    z-index: 0;
}
```

Naśladuje wzorzec `priceMode` z `calculator_brutto_netto.css` — jeśli wzór się różni, dopasować. Kolor `#ED6B24` to firmowy pomarańczowy (sprawdzić w istniejącym CSS).

- [ ] **Krok 4: Załadować nowy CSS w template**

W `modules/calculator/templates/calculator.html`, w sekcji `<head>` lub gdzie ładowane są inne CSS-y modułu (np. obok `calculator_brutto_netto.css`), dodać:

```html
    <link rel="stylesheet" href="{{ url_for('calculator.static', filename='css/cut_to_size_toggle.css') }}">
```

(Sprawdzić jak ładowane są istniejące CSS-y kalkulatora i naśladować — może być przez `{% block extra_css %}` lub bezpośredni `<link>`.)

- [ ] **Krok 5: Smoke test wizualny**

Uruchomić `run_local.bat`, otworzyć `http://127.0.0.1:5000/calculator`, sprawdzić że toggle pojawia się jako pierwszy element w sekcji "Wykończenie", domyślnie zaznaczone "Tak", kliknięcia przełączają stan.

- [ ] **Krok 6: Commit**

```bash
git add modules/calculator/templates/calculator.html modules/calculator/static/css/cut_to_size_toggle.css
git commit -m "feat(calculator): toggle "Docięcie do wymiaru" w sekcji Wykończenie

Per-produkt, domyślnie Tak. Wzorzec wizualny z toggla brutto/netto."
```

---

## Task 5: Frontend JS — synchronizacja togglu z `dataset.cutToSize`

**Files:**
- Create: `modules/calculator/static/js/cut_to_size.js`
- Modify: `modules/calculator/templates/calculator.html` (załadowanie skryptu)

- [ ] **Krok 1: Utworzyć moduł JS**

W `modules/calculator/static/js/cut_to_size.js`:

```javascript
/**
 * Toggle "Docięcie do wymiaru" — per-produkt.
 * Stan trzymany w dataset.cutToSize na elemencie .quote-form.
 * Default: 'true'.
 */

function getCutToSize(form) {
    if (!form) return true;
    const ds = form.dataset.cutToSize;
    if (ds === undefined || ds === null || ds === '') return true;
    return ds === 'true';
}

function setCutToSize(form, value) {
    if (!form) return;
    const boolValue = value === true || value === 'true' || value === 'yes';
    form.dataset.cutToSize = boolValue ? 'true' : 'false';
    syncToggleUI(form);
}

function syncToggleUI(form) {
    if (!form) return;
    const value = getCutToSize(form);
    const radioYes = form.querySelector('.cut-to-size-radio[value="yes"]');
    const radioNo = form.querySelector('.cut-to-size-radio[value="no"]');
    if (radioYes && radioNo) {
        radioYes.checked = value;
        radioNo.checked = !value;
    }
}

function bindCutToSizeToggle(form) {
    if (!form) return;
    const radios = form.querySelectorAll('.cut-to-size-radio');
    radios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (e.target.checked) {
                setCutToSize(form, e.target.value === 'yes');
            }
        });
    });
    // Init: zsynchronizuj UI z dataset (na wypadek wczytania z drafta/edycji)
    syncToggleUI(form);
}

function bindAllCutToSizeToggles() {
    const forms = document.querySelectorAll('.quote-form');
    forms.forEach(bindCutToSizeToggle);
}

document.addEventListener('DOMContentLoaded', bindAllCutToSizeToggles);

window.cutToSize = {
    get: getCutToSize,
    set: setCutToSize,
    sync: syncToggleUI,
    bind: bindCutToSizeToggle,
    bindAll: bindAllCutToSizeToggles,
};
```

- [ ] **Krok 2: Załadować skrypt w `calculator.html`**

Dodać przed `</body>` (lub w sekcji ze skryptami JS kalkulatora — sprawdzić wzorzec):

```html
    <script src="{{ url_for('calculator.static', filename='js/cut_to_size.js') }}"></script>
```

- [ ] **Krok 3: Po dodaniu nowego produktu — zbindować toggle**

W `modules/calculator/static/js/calculator-products.js`, znaleźć funkcję `addNewProduct` (lub miejsce gdzie po klonowaniu formularza są bindowane listenery — np. linia 846). Po klonowaniu nowego `.quote-form` wywołać:

```javascript
        if (window.cutToSize) {
            window.cutToSize.bind(newForm);
        }
```

Dokładne miejsce: tam, gdzie aktualnie są bindowane inne listenery na sklonowanym formularzu (sprawdzić w `addNewProduct`). Jeśli nie ma takiej funkcji, dodać po klonowaniu w funkcji odpowiedzialnej.

- [ ] **Krok 4: Smoke test**

W przeglądarce otworzyć dev tools → Elements, kliknąć toggle Tak/Nie, sprawdzić że `.quote-form` ma `data-cut-to-size="true"` lub `"false"` zgodnie z klikiem. Dodać produkt — sprawdzić że nowy `.quote-form` ma `data-cut-to-size="true"` i toggle reaguje.

- [ ] **Krok 5: Commit**

```bash
git add modules/calculator/static/js/cut_to_size.js modules/calculator/templates/calculator.html modules/calculator/static/js/calculator-products.js
git commit -m "feat(calculator): JS bindowanie togglu cut_to_size do dataset

Stan per-produkt w dataset.cutToSize, sync z radio inputami,
bindowanie nowych formularzy po addNewProduct."
```

---

## Task 6: Frontend JS — zapis pola w payloadzie save_quote

**Files:**
- Modify: `modules/calculator/static/js/save_quote.js` (budowa payloadu produktu)

- [ ] **Krok 1: Znaleźć budowę obiektu produktu w payloadzie**

W `modules/calculator/static/js/save_quote.js` znaleźć miejsce, gdzie składany jest obiekt produktu (zawiera klucze `finishing_type`, `finishing_variant` itd. — np. linie 1196 i 1228 z grepa). Znaleźć też dostęp do `.quote-form` — pewnie iteruje po formularzach.

- [ ] **Krok 2: Dodać pole `cut_to_size` do payloadu produktu**

Do każdego miejsca, gdzie budowany jest obiekt produktu (oba miejsca: 1196 i 1228), dodać klucz:

```javascript
                cut_to_size: window.cutToSize ? window.cutToSize.get(form) : true,
```

(`form` to zmienna iterowanego `.quote-form` w danym scope — sprawdzić jak nazywa się w kontekście. Może to być `quoteForm`, `productForm` itd.)

- [ ] **Krok 3: Smoke test sieciowy**

W przeglądarce: Dev Tools → Network. Wykonać save wyceny. W requeście do `/calculator/save_quote` w body sprawdzić, że każdy produkt zawiera `"cut_to_size": true` (lub `false` po przełączeniu). 

W bazie:

```sql
SELECT product_index, cut_to_size FROM quote_items_details WHERE quote_id = <ostatnia_id> ORDER BY product_index;
```

Oczekiwane: wartości zgodne ze stanem togglu w UI.

- [ ] **Krok 4: Commit**

```bash
git add modules/calculator/static/js/save_quote.js
git commit -m "feat(calculator): cut_to_size w payloadzie save_quote

Pole leci z dataset.cutToSize per .quote-form, default true."
```

---

## Task 7: Frontend JS — backup w drafcie kalkulatora

**Files:**
- Modify: `modules/calculator/static/js/qdraft_backup.js` (zapis i odczyt drafta)

- [ ] **Krok 1: Znaleźć budowę draft_data**

W `modules/calculator/static/js/qdraft_backup.js` znaleźć funkcję, która zbiera dane do zapisu (zawiera linię 198 `let quoteType = 'brutto';` z grepa). Zlokalizować obiekt produktu w `draft_data`.

- [ ] **Krok 2: Dodać `cut_to_size` do drafta**

W obiekcie produktu, gdzie zapisywane są inne flagi (`finishing_type`, `dataset.*`), dodać:

```javascript
            cut_to_size: window.cutToSize ? window.cutToSize.get(form) : true,
```

- [ ] **Krok 3: Odczyt z drafta — przywrócenie stanu**

W tym samym pliku znaleźć funkcję ładującą draft (np. `restoreDraft` lub podobna), w bloku odpowiedzialnym za przywracanie atrybutów produktu, dodać:

```javascript
            if (window.cutToSize) {
                const cts = product.cut_to_size;
                window.cutToSize.set(form, cts === undefined || cts === null ? true : cts);
            }
```

- [ ] **Krok 4: Smoke test**

1. Ustawić toggle na "Nie" → odczekać auto-zapis drafta (sprawdzić w Network requesty `save_draft` — payload zawiera `cut_to_size: false`).
2. Odświeżyć stronę.
3. Po wczytaniu drafta toggle powinien wskazywać "Nie", a `dataset.cutToSize === "false"`.

- [ ] **Krok 5: Commit**

```bash
git add modules/calculator/static/js/qdraft_backup.js
git commit -m "feat(calculator): cut_to_size w backupie drafta

Pole zapisywane w draft_data i odtwarzane przy wczytaniu wersji roboczej."
```

---

## Task 8: Frontend JS — wczytanie pola w trybie edycji wyceny

**Files:**
- Modify: `modules/calculator/static/js/quote_edit_loader.js` (loader stanu edycji)

- [ ] **Krok 1: Sprawdzić, jak loader otrzymuje dane**

W `modules/calculator/static/js/quote_edit_loader.js` znaleźć miejsce, gdzie restorowane są atrybuty produktu (analogiczne do `restorePriceMode` w linii 142). Backend dostarcza dane przez `data` (linia 613: `quote_type: data.quote_type` — analogiczna ścieżka).

- [ ] **Krok 2: Dodać przywracanie `cut_to_size` per produkt**

W metodzie restorującej produkty (gdzie ustawiane są wymiary, wykończenie itd.) dodać:

```javascript
        if (window.cutToSize) {
            const cts = productData.cut_to_size;
            window.cutToSize.set(form, cts === undefined || cts === null ? true : cts);
        }
```

`productData` i `form` — nazwy zgodne z kontekstem funkcji.

- [ ] **Krok 3: Backend — upewnić się, że endpoint `load_quote` zwraca `cut_to_size`**

Znaleźć w `modules/calculator/services/quote_service.py` funkcję `load_quote` lub analogiczną (linia 50: `from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails`). Sprawdzić, czy dane produktu w odpowiedzi zawierają pole z `details.cut_to_size`. Jeśli tak — `to_dict()` z Tasku 1 załatwia. Jeśli budowa odpowiedzi jest ręczna (selektywny dict), dodać:

```python
        'cut_to_size': bool(detail.cut_to_size) if detail else True,
```

w tym samym miejscu co inne pola z `detail`.

- [ ] **Krok 4: Smoke test edycji**

1. Otworzyć istniejącą wycenę w trybie edycji.
2. Sprawdzić, że toggle wskazuje stan zgodny z bazą (dla wycen sprzed migracji: "Tak").
3. Zmienić na "Nie" → zapisać → ponownie otworzyć w edycji → "Nie" zachowane.

- [ ] **Krok 5: Commit**

```bash
git add modules/calculator/static/js/quote_edit_loader.js modules/calculator/services/quote_service.py
git commit -m "feat(calculator): wczytanie cut_to_size w trybie edycji wyceny"
```

---

## Task 9: Frontend — kopiowanie produktu (`duplicateProduct`)

**Files:**
- Modify: `modules/calculator/static/js/calculator-products.js:260-620` (funkcja `duplicateProduct`)

- [ ] **Krok 1: Odczyt `cut_to_size` ze źródłowego formularza**

W `modules/calculator/static/js/calculator-products.js`, w `duplicateProduct(sourceIndex)` (linia 260), w obiekcie `sourceData` (linia 286) dodać po `edgesSvg: sourceForm.dataset.edgesSvg || null`:

```javascript
        // Docięcie do wymiaru
        cutToSize: sourceForm.dataset.cutToSize || 'true',
```

- [ ] **Krok 2: Aplikacja na nowy formularz**

W bloku `setTimeout(() => { ... })` po utworzeniu nowego formularza (linia ~358), w sekcji wypełniania `newForm` dodać:

```javascript
        // Skopiuj cut_to_size
        if (window.cutToSize) {
            window.cutToSize.set(newForm, sourceData.cutToSize === 'true');
        }
```

Umieścić obok przywracania innych atrybutów (np. po wymiarach, przed wykończeniem — kolejność nie ma znaczenia, byle przed końcem `setTimeout`).

- [ ] **Krok 3: Smoke test**

1. W kalkulatorze ustawić w produkcie 1 toggle na "Nie".
2. Kliknąć "Kopiuj produkt".
3. Sprawdzić, że produkt 2 (kopia) ma toggle na "Nie".
4. Zmienić w produkcie 1 z powrotem na "Tak" → produkt 2 nadal "Nie" (niezależne stany).

- [ ] **Krok 4: Commit**

```bash
git add modules/calculator/static/js/calculator-products.js
git commit -m "feat(calculator): kopiowanie produktu przenosi cut_to_size"
```

---

## Task 10: Modal `/quotes/` — wiersz "Docięcie do wymiaru" w tabeli "Wykończenie"

**Files:**
- Modify: `modules/quotes/static/js/quotes.js:2772-2798` (budowa tabeli "Wykończenie")
- Modify: `modules/quotes/routers.py` lub serwis serwujący dane modala (sprawdzić, czy serializuje `cut_to_size`)

- [ ] **Krok 1: Sprawdzić serializację po stronie backendu**

Znaleźć endpoint, który zwraca dane szczegółów wyceny do modala (kandydat: `modules/quotes/routers.py` linia 2601 — `items_with_details.append((item, detail))`). Sprawdzić, czy `detail` jest serializowany przez `to_dict()` (wtedy `cut_to_size` leci automatycznie po Tasku 1) czy ręcznie. Jeśli ręcznie — dodać pole `cut_to_size` w odpowiedzi.

Konkretnie: znaleźć linię z `'finishing_type':` w odpowiedzi modala i obok dodać:

```python
            'cut_to_size': bool(detail.cut_to_size) if detail else True,
```

- [ ] **Krok 2: Wstawić wiersz w tabeli "Wykończenie"**

W `modules/quotes/static/js/quotes.js`, w bloku budowy `finishingTableRows` (linie 2772-2793), zmodyfikować aby pierwszym wierszem zawsze był "Docięcie do wymiaru":

```javascript
    // Buduj tabelę Wykończenie
    let finishingTableRows = '';

    // Pierwszy wiersz: docięcie do wymiaru (zawsze widoczny, niezależnie od finishing)
    const cutToSize = (finishing && finishing.cut_to_size === false) ? false : true;
    const cutToSizeLabel = cutToSize ? 'Tak' : '<strong>Nie</strong>';
    finishingTableRows += '<tr><td>Docięcie do wymiaru</td><td>' + cutToSizeLabel + '</td></tr>';

    if (hasFinishing) {
        if (finishing.finishing_type) finishingTableRows += '<tr><td>Typ</td><td>' + finishing.finishing_type + '</td></tr>';
        if (finishing.finishing_variant) finishingTableRows += '<tr><td>Wariant</td><td>' + finishing.finishing_variant + '</td></tr>';
        if (finishing.finishing_gloss_level) finishingTableRows += '<tr><td>Połysk</td><td>' + finishing.finishing_gloss_level + '</td></tr>';
        if (finishing.finishing_color) finishingTableRows += '<tr><td>Kolor</td><td>' + finishing.finishing_color + '</td></tr>';
        if (finishing) {
            const fCostBrutto = parseFloat(finishing.finishing_price_brutto || 0);
            const fCostNetto = parseFloat(finishing.finishing_price_netto || 0);
            if (fCostBrutto > 0) {
                finishingTableRows += '<tr><td>Koszt</td><td>' + fCostBrutto.toFixed(2) + ' PLN <span class="cost-netto">' + fCostNetto.toFixed(2) + ' PLN</span></td></tr>';
            }
        }
    } else {
        finishingTableRows +=
            '<tr><td>Typ</td><td>Surowe</td></tr>' +
            '<tr><td>Wariant</td><td>Brak</td></tr>' +
            '<tr><td>Połysk</td><td>Brak</td></tr>' +
            '<tr><td>Kolor</td><td>Brak</td></tr>' +
            '<tr><td>Koszt</td><td>0.00 PLN <span class="cost-netto">0.00 PLN</span></td></tr>';
    }
```

(Zmiana: nowy blok przed `if (hasFinishing)` + zmiana `=` na `+=` w gałęzi `else`).

- [ ] **Krok 3: Smoke test modala**

1. Otworzyć `/quotes/` → modal szczegółów wyceny dla istniejącej wyceny → sprawdzić, że pierwszy wiersz w "Wykończenie" to "Docięcie do wymiaru: Tak".
2. Wycena z `cut_to_size=false` (zmienić w bazie ręcznie: `UPDATE quote_items_details SET cut_to_size=FALSE WHERE id=...`) → odświeżyć modal → "Docięcie do wymiaru: **Nie**" (pogrubione).

- [ ] **Krok 4: Commit**

```bash
git add modules/quotes/static/js/quotes.js modules/quotes/routers.py
git commit -m "feat(quotes): wiersz "Docięcie do wymiaru" w modalu wyceny

Pierwszy wiersz w tabeli Wykończenie, zawsze widoczny.
Wartość "Nie" pogrubiona — odstępstwo od standardu."
```

---

## Task 11: PDF oferty — warunkowy fragment "Docięcie do wymiaru: Nie"

**Files:**
- Modify: `modules/quotes/templates/offer_pdf.html:603-...` (sekcja "Wykończenie")
- Modify: backend renderujący PDF (przekazanie `cut_to_size` do kontekstu — sprawdzić w `modules/quotes/services/`)

- [ ] **Krok 1: Sprawdzić jak `item` jest budowany w kontekście Jinja**

W `modules/quotes/services/` lub `modules/quotes/routers.py` znaleźć kod renderujący `offer_pdf.html` (`render_template('offer_pdf.html', ...)`). Zobaczyć, jak wygląda `item` przekazywany do template — czy ma `details.cut_to_size`, czy `cut_to_size` bezpośrednio.

- [ ] **Krok 2: Zapewnić obecność `cut_to_size` w kontekście**

Jeśli kontekst zawiera obiekt z `details` (relacją SQLAlchemy) — dostępne automatycznie po Tasku 1 (`item.details.cut_to_size`). Jeśli kontekst jest dictem ręcznie składanym, dodać pole.

- [ ] **Krok 3: Dodać warunkowy fragment w `offer_pdf.html`**

W `modules/quotes/templates/offer_pdf.html` po bloku "Wykończenie" (linie 603-...) dodać:

```jinja
                        {# Informacja o docięciu — pokazujemy TYLKO gdy klient sam dotina (cut_to_size=false) #}
                        {% if item.details and item.details.cut_to_size == False %}
                        <div class="cut-to-size-info" style="margin-top: 4px; font-size: 11px; color: #555;">
                            Docięcie do wymiaru: <strong>Nie</strong>
                        </div>
                        {% endif %}
```

(Dokładna ścieżka `item.details.cut_to_size` — dostosować do struktury kontekstu znalezionej w kroku 1. Jeśli `cut_to_size` jest na innym poziomie, użyć właściwej ścieżki.)

- [ ] **Krok 4: Smoke test PDF**

1. Wycena z `cut_to_size=true` → PDF: brak wzmianki o docięciu.
2. Wycena z `cut_to_size=false` (ręcznie ustawić w bazie) → PDF: pojawia się "Docięcie do wymiaru: **Nie**".

Generowanie PDF: jeśli endpoint to `/quotes/<id>/pdf`, otworzyć w przeglądarce.

- [ ] **Krok 5: Commit**

```bash
git add modules/quotes/templates/offer_pdf.html modules/quotes/services/
git commit -m "feat(quotes): info o braku docięcia w PDF oferty

Pokazujemy "Docięcie do wymiaru: Nie" tylko gdy odstępstwo od standardu.
Domyślnie (cut_to_size=true) — brak wzmianki, zero szumu."
```

---

## Task 12: Strona klienta — warunkowy fragment "Docięcie do wymiaru: Nie"

**Files:**
- Modify: `modules/quotes/static/js/client_quote.js` (linie 670, 688, 752, 768 — miejsca z "Wykończenie:")

- [ ] **Krok 1: Sprawdzić strukturę produktu w kontekście klienta**

Otworzyć `modules/quotes/static/js/client_quote.js` w okolicy linii 670, znaleźć obiekt z którego pobierane jest `Wykończenie:` (np. `product.finishing_type`). Sprawdzić, czy jest pole `cut_to_size` w danych pobieranych przez ten widok.

- [ ] **Krok 2: Zapewnić serializację po stronie backendu**

Backend serwujący widok klienta (`modules/quotes/routers.py` — endpoint dla strony klienta z tokenem) musi zwracać `cut_to_size` w danych produktu. Jeśli używa `to_dict()` z modelu — załatwione. Jeśli ręczna serializacja — dodać.

- [ ] **Krok 3: Render warunkowy w JS**

W każdym z 4 miejsc renderujących "Wykończenie:" (linie 670, 688, 752, 768) dodać po bloku wykończenia warunkowy element:

```javascript
                ${product.cut_to_size === false ? `
                    <div class="cut-to-size-info">
                        Docięcie do wymiaru: <strong>Nie</strong>
                    </div>
                ` : ''}
```

Dostosować do konwencji istniejącego kodu (template literals vs string concatenation — sprawdzić w danym miejscu i naśladować).

- [ ] **Krok 4: CSS dla strony klienta**

Sprawdzić istniejące style klienckie (`modules/quotes/static/css/client_quote.css` lub podobny) i dodać styl `.cut-to-size-info` neutralny (mały font, szary kolor).

- [ ] **Krok 5: Smoke test strony klienta**

1. Wygenerować link klienta dla wyceny z `cut_to_size=true` → otworzyć → brak wzmianki.
2. Wycena z `cut_to_size=false` → otworzyć → "Docięcie do wymiaru: **Nie**".

- [ ] **Krok 6: Commit**

```bash
git add modules/quotes/static/js/client_quote.js modules/quotes/static/css/
git commit -m "feat(quotes): info o braku docięcia w widoku klienta

Wyświetlamy tylko gdy cut_to_size=false (odstępstwo)."
```

---

## Task 13: End-to-end smoke test i deploy

**Files:** —

- [ ] **Krok 1: Pełny scenariusz E2E lokalnie**

1. Otworzyć `/calculator` → toggle "Tak" → zapisać wycenę → zweryfikować w bazie:
   ```sql
   SELECT cut_to_size FROM quote_items_details WHERE quote_id = (SELECT MAX(id) FROM quotes);
   ```
   Oczekiwane: `1`.
2. Otworzyć tę wycenę w trybie edycji → toggle pokazuje "Tak" → zmienić na "Nie" → zapisać → ponowna weryfikacja w bazie: `0`.
3. Otworzyć modal `/quotes/` dla tej wyceny → wiersz "Docięcie do wymiaru: **Nie**" (pogrubione) na początku tabeli "Wykończenie".
4. Otworzyć PDF tej wyceny → pojawia się "Docięcie do wymiaru: **Nie**".
5. Otworzyć stronę klienta tej wyceny → pojawia się "Docięcie do wymiaru: **Nie**".
6. Edytuj z powrotem na "Tak" → modal: "Tak" (normalny styl), PDF i strona klienta: brak wzmianki.
7. Skopiuj produkt → kopia ma ten sam stan togglu.

- [ ] **Krok 2: Sprawdzić draft**

Otworzyć kalkulator → ustawić toggle "Nie" → odczekać auto-zapis → odświeżyć stronę → toggle nadal "Nie".

- [ ] **Krok 3: Push na main**

```bash
git push origin main
```

GitHub Actions zdeployuje na produkcję.

- [ ] **Krok 4: Wykonać migrację SQL na produkcji**

Po zakończeniu deployu, ręcznie połączyć się z bazą produkcyjną i wykonać:

```sql
ALTER TABLE quote_items_details
  ADD COLUMN cut_to_size BOOLEAN NOT NULL DEFAULT TRUE;
```

(Dokładny SQL w `docs/superpowers/migrations/2026-05-06-cut-to-size.sql`.)

- [ ] **Krok 5: Smoke test produkcji**

Powtórzyć skrócony scenariusz (kroki 1-3 z Kroku 1) na `crm.woodpower.pl`.

---

## Self-Review (po napisaniu planu)

**Spec coverage:**
- ✅ Migracja DB + SQL produkcji → Task 1
- ✅ Model SQLAlchemy `cut_to_size` + `to_dict()` → Task 1
- ✅ UI toggle w kalkulatorze (pierwszy element sekcji "Wykończenie") → Task 4
- ✅ Per-produkt stan w `dataset.cutToSize` → Task 5
- ✅ Save w kalkulatorze (nowa wycena + edycja) → Task 2, 3, 6
- ✅ Backup w drafcie → Task 7
- ✅ Edycja wyceny — wczytanie pola → Task 8
- ✅ Kopiowanie produktu → Task 9
- ✅ Modal `/quotes/` — pierwszy wiersz w tabeli "Wykończenie", "Nie" pogrubione → Task 10
- ✅ PDF — tylko gdy `false` → Task 11
- ✅ Strona klienta — tylko gdy `false` → Task 12
- ✅ Smoke test E2E → Task 13

**Placeholder scan:** Brak TODO/TBD w treści. Dwa miejsca z świadomą frazą "sprawdzić jak nazywa się w kontekście" — bo dokładna nazwa zmiennej JS w istniejącym kodzie wymaga zerknięcia. To uzasadnione, nie placeholder.

**Type consistency:** `cut_to_size` (snake_case w Pythonie/SQL/JSON) + `cutToSize` (camelCase w `dataset.*` — JS standard dla `dataset`). Spójne we wszystkich zadaniach.
