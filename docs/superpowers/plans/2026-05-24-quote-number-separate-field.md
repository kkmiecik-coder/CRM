# Quote Number Separate Field — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rozdzielenie numeru wyceny od notatki — w Baselinker (osobne `extra_field_170043`) i w bazie produkcji (nowa kolumna `prod_orders.quote_number`), z wyświetleniem w UI dashboardu i backfillem historycznych rekordów.

**Architecture:** Po stronie BL: `_build_user_comments()` zwraca tylko notatkę, numer wyceny ląduje w `custom_extra_fields['170043']`. Po stronie produkcji: nowa kolumna `quote_number` na `ProductionOrder`, sync_service czyta z `custom_extra_fields['170043']`, UI (badge w wierszu + pole w Identyfikacji modala) dla zakładek "Lista produktów" i "Archiwum". Backfill historycznych zamówień jednorazowym skryptem z regexem na `order_notes`.

**Tech Stack:** Flask, SQLAlchemy (MySQL), Python 3.9, Jinja2, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-05-24-quote-number-separate-field-design.md`

---

### Task 1: Schemat bazy + model

**Files:**
- Manual SQL (phpMyAdmin / mysql client): `prod_orders` table
- Modify: `modules/production/models.py:130`

- [ ] **Step 1: ALTER TABLE (lokalne dev DB)**

Wykonać w phpMyAdmin lokalnie (XAMPP `woodpower_crm_local`):

```sql
ALTER TABLE prod_orders
  ADD COLUMN quote_number VARCHAR(16) NULL AFTER internal_order_number;
CREATE INDEX idx_prod_orders_quote_number ON prod_orders(quote_number);
```

Sprawdź: `DESCRIBE prod_orders;` — kolumna obecna.

- [ ] **Step 2: Dodaj pole w modelu**

W `modules/production/models.py`, w klasie `ProductionOrder` (~linia 130), tuż za `internal_order_number`:

```python
internal_order_number = Column(String(20), nullable=False)
quote_number = Column(String(16), index=True)
baselinker_status_id = Column(Integer, index=True)
```

(Wcięcie tylko `quote_number` jako nowa linia — `internal_order_number` i `baselinker_status_id` są referencyjne.)

- [ ] **Step 3: Smoke check importu modelu**

Uruchom:

```bash
python3 -c "from modules.production.models import ProductionOrder; print(ProductionOrder.__table__.columns.keys())"
```

Oczekiwany output: lista kolumn zawierająca `'quote_number'` między `'internal_order_number'` a `'baselinker_status_id'`.

- [ ] **Step 4: Commit**

```bash
git add modules/production/models.py
git commit -m "feat(production): dodaj kolumnę quote_number w prod_orders"
```

---

### Task 2: Baselinker — wysyłka numeru wyceny w extra_field_170043

**Files:**
- Modify: `modules/baselinker/service.py:843-846` (custom_extra_fields)
- Modify: `modules/baselinker/service.py:1205-1226` (_build_user_comments)
- Create: `tests/test_baselinker_user_comments.py`

- [ ] **Step 1: Napisz test (TDD) dla `_build_user_comments`**

Utwórz `tests/test_baselinker_user_comments.py`:

```python
"""Test buildera notatki użytkownika (po rozdzieleniu numeru wyceny)."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.baselinker.service import BaselinkerService


def _service():
    svc = BaselinkerService.__new__(BaselinkerService)
    svc.logger = MagicMock()
    return svc


def _quote(quote_number, notes):
    q = MagicMock()
    q.quote_number = quote_number
    q.notes = notes
    return q


def test_returns_only_notes_when_present():
    result = _service()._build_user_comments(_quote("226/04/26/W", "Pilne, klient czeka"))
    assert result == "Pilne, klient czeka"


def test_returns_empty_string_when_no_notes():
    result = _service()._build_user_comments(_quote("226/04/26/W", None))
    assert result == ""


def test_returns_empty_when_notes_whitespace_only():
    result = _service()._build_user_comments(_quote("226/04/26/W", "   "))
    assert result == ""


def test_truncates_notes_over_200_chars():
    long_note = "x" * 250
    result = _service()._build_user_comments(_quote("226/04/26/W", long_note))
    assert len(result) == 200
    assert result.endswith("...")


def test_does_not_include_quote_number_prefix():
    result = _service()._build_user_comments(_quote("226/04/26/W", "uwaga"))
    assert "Wycena" not in result
    assert "226/04/26/W" not in result
```

- [ ] **Step 2: Uruchom test (musi NIE PRZEJŚĆ)**

```bash
python3 -m pytest tests/test_baselinker_user_comments.py -v
```

Expected: FAIL — obecna implementacja `_build_user_comments` doklejaja "Wycena {quote_number}".

- [ ] **Step 3: Przepisz `_build_user_comments` (linie 1205-1226)**

Zastąp całe ciało metody w `modules/baselinker/service.py`:

```python
    def _build_user_comments(self, quote):
        """Zwraca samą notatkę użytkownika (numer wyceny idzie do extra_field_170043)."""
        notes = (quote.notes or '').strip()
        if len(notes) > 200:
            notes = notes[:197] + '...'
            self.logger.warning("Notatka została skrócona do 200 znaków",
                                quote_number=quote.quote_number,
                                original_length=len(quote.notes or ''))
        self.logger.debug("Zbudowano notatkę użytkownika",
                          quote_number=quote.quote_number,
                          has_notes=bool(notes),
                          comment_length=len(notes))
        return notes
```

- [ ] **Step 4: Uruchom test (musi przejść)**

```bash
python3 -m pytest tests/test_baselinker_user_comments.py -v
```

Expected: 5/5 PASS.

- [ ] **Step 5: Dodaj `170043` do `custom_extra_fields`**

W `modules/baselinker/service.py`, w słowniku `order_data` (~linia 843-846), zmień:

```python
            'custom_extra_fields': {
                '105623': creator_name,  # Opiekun
                '106169': payment_type_value  # 🆕 NOWE: Typ płatności (Brutto/Netto)
            },
```

na:

```python
            'custom_extra_fields': {
                '105623': creator_name,                  # Opiekun
                '106169': payment_type_value,            # Typ płatności (Brutto/Netto)
                '170043': quote.quote_number or '',      # 🆕 Numer wyceny
            },
```

- [ ] **Step 6: Smoke import**

```bash
python3 -c "from modules.baselinker.service import BaselinkerService; print('ok')"
```

Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add modules/baselinker/service.py tests/test_baselinker_user_comments.py
git commit -m "feat(baselinker): wyślij numer wyceny w extra_field_170043 zamiast admin_comments"
```

---

### Task 3: Production sync — odczyt quote_number z BL

**Files:**
- Modify: `modules/production/services/sync_service.py:~1092` (ekstrakcja)
- Modify: `modules/production/services/sync_service.py:1204` (ORDER_LEVEL_KEYS)
- Modify: `modules/production/services/sync_service.py:~2009` (compare_order_with_baselinker)

- [ ] **Step 1: Ekstrakcja `quote_number` z `custom_extra_fields['170043']`**

W `modules/production/services/sync_service.py`, znajdź blok przy `# extra_field_1 = wewnętrzny numer zamówienia klienta` (~linia 1092). Dodaj **PRZED** tym blokiem:

```python
        # custom_extra_fields[170043] = numer wyceny
        custom_fields = order.get('custom_extra_fields', {}) or {}
        quote_number = (custom_fields.get('170043') or '').strip() or None
        if quote_number:
            product_data['quote_number'] = quote_number[:16]
            logger.debug("Dodano quote_number", extra={
                'product_id': product_id,
                'quote_number': quote_number
            })
```

- [ ] **Step 2: Dodaj `quote_number` do `ORDER_LEVEL_KEYS`**

W tej samej funkcji (~linia 1204), zmień:

```python
        ORDER_LEVEL_KEYS = {
            'baselinker_order_id', 'internal_order_number', 'baselinker_status_id',
            'payment_date', 'client_order_number', 'order_notes',
```

na:

```python
        ORDER_LEVEL_KEYS = {
            'baselinker_order_id', 'internal_order_number', 'baselinker_status_id',
            'payment_date', 'client_order_number', 'quote_number', 'order_notes',
```

- [ ] **Step 3: Dodaj porównanie `quote_number` w `compare_order_with_baselinker`**

W `modules/production/services/sync_service.py`, w `compare_order_with_baselinker` (~linia 2009), tuż **PRZED** blokiem `# order_notes (admin_comments)`:

```python
            # quote_number (custom_extra_fields[170043])
            bl_custom = bl_order.get('custom_extra_fields', {}) or {}
            bl_quote_number = (bl_custom.get('170043') or '').strip() or None
            current_quote_number = _first_order.quote_number if _first_order else None
            if bl_quote_number != current_quote_number:
                order_level_changes.append({
                    'field': 'quote_number',
                    'label': 'Numer wyceny',
                    'old_value': current_quote_number,
                    'new_value': bl_quote_number
                })

            # order_notes (admin_comments)
```

- [ ] **Step 4: Smoke import**

```bash
python3 -c "from modules.production.services.sync_service import SyncService; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add modules/production/services/sync_service.py
git commit -m "feat(production): odczytuj quote_number z custom_extra_fields[170043] przy syncu"
```

---

### Task 4: API serializer + wyszukiwarka

**Files:**
- Modify: `modules/production/routers/api/products_api.py:891` (serializer)
- Modify: `modules/production/routers/api/products_api.py:686,1070` (search)

- [ ] **Step 1: Dodaj `quote_number` do JSON serializera**

W `modules/production/routers/api/products_api.py`, znajdź blok `# Dodatkowe pola z zamówienia` (~linia 890). Zmień:

```python
                # Dodatkowe pola z zamówienia
                'client_order_number': product.order.client_order_number if product.order else None,
                'order_notes': product.order.order_notes if product.order else None,
```

na:

```python
                # Dodatkowe pola z zamówienia
                'client_order_number': product.order.client_order_number if product.order else None,
                'quote_number': product.order.quote_number if product.order else None,
                'order_notes': product.order.order_notes if product.order else None,
```

- [ ] **Step 2: Dodaj `quote_number` do wyszukiwarki (linia ~686)**

Znajdź blok wyszukiwania (~linia 685-687):

```python
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))
```

Dodaj między te dwie linie:

```python
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.quote_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))
```

- [ ] **Step 3: Powtórz w drugiej wyszukiwarce (linia ~1070)**

W `modules/production/routers/api/products_api.py:1070-1071`:

```python
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))
```

Zmień na:

```python
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.quote_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))
```

- [ ] **Step 4: Smoke import**

```bash
python3 -c "from modules.production.routers.api.products_api import products_api_bp; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add modules/production/routers/api/products_api.py
git commit -m "feat(production): zwracaj quote_number w API i obsłuż w wyszukiwarce"
```

---

### Task 5: UI — szablon modala (sekcja Identyfikacja)

**Files:**
- Modify: `modules/production/templates/components/products-tab-content.html:438`

- [ ] **Step 1: Dodaj pole `Numer wyceny` w sekcji Identyfikacja**

W `modules/production/templates/components/products-tab-content.html` znajdź pole `Pozycja w zamówieniu` (~linia 435-438):

```html
                                    <div class="field-group">
                                        <div class="field-label">Pozycja w zamówieniu</div>
                                        <div class="field-value" data-field="sequence_display">1/3</div>
                                    </div>
                                </div>
```

Dodaj **po** `Pozycja w zamówieniu` jeszcze jedno `field-group`:

```html
                                    <div class="field-group">
                                        <div class="field-label">Pozycja w zamówieniu</div>
                                        <div class="field-value" data-field="sequence_display">1/3</div>
                                    </div>
                                    <div class="field-group">
                                        <div class="field-label">Numer wyceny</div>
                                        <div class="field-value" data-field="quote_number">—</div>
                                    </div>
                                </div>
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/templates/components/products-tab-content.html
git commit -m "feat(production): pole numer wyceny w sekcji Identyfikacja modala"
```

---

### Task 6: UI JS — produktyy: agregacja + badge + render modala

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js`

- [ ] **Step 1: Dodaj `quoteNumber` do agregacji w `groupProductsByOrder`**

Znajdź (~linia 1342-1370) blok dodający produkt do orderu. W obiekcie inicjującym order (przy `clientOrderNumber: product.client_order_number`) dodaj `quoteNumber`:

```javascript
                    clientOrderNumber: product.client_order_number,
                    quoteNumber: product.quote_number,
                    internalOrderNumber: product.internal_order_number,
```

Dodatkowo zaraz po linii `if (product.order_notes && !order.orderNotes) order.orderNotes = product.order_notes;` (~linia 1370) dodaj propagację dla brakujących orderów (przypadek gdy pierwszy produkt ma null):

```javascript
            if (product.order_notes && !order.orderNotes) order.orderNotes = product.order_notes;
            if (product.quote_number && !order.quoteNumber) order.quoteNumber = product.quote_number;
```

- [ ] **Step 2: Dodaj badge `quoteNumber` w renderze wiersza**

Znajdź (~linia 1529-1535) blok renderujący `il-order-id-tag` dla `clientOrderNumber`:

```javascript
        if (order.clientOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${order.clientOrderNumber}</span>`;
        }
```

Dodaj **po** tym bloku:

```javascript
        if (order.clientOrderNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${order.clientOrderNumber}</span>`;
        }
        if (order.quoteNumber) {
            idsContainer.innerHTML += `<span class="il-order-id-tag">${order.quoteNumber}</span>`;
        }
```

- [ ] **Step 3: Dodaj `quote_number` do `exactMatchFields` (linia ~359)**

Zmień:

```javascript
                const exactMatchFields = ['baselinker_order_id', 'client_order_number'];
```

na:

```javascript
                const exactMatchFields = ['baselinker_order_id', 'client_order_number', 'quote_number'];
```

- [ ] **Step 4: Dodaj `quote_number` do listy `fields` wyszukiwarki (linia ~2451)**

Zmień:

```javascript
                    fields: ['original_product_name', 'short_product_id', 'client_name', 'baselinker_order_id', 'client_order_number'],
```

na:

```javascript
                    fields: ['original_product_name', 'short_product_id', 'client_name', 'baselinker_order_id', 'client_order_number', 'quote_number'],
```

- [ ] **Step 5: Sprawdź czy modal automatycznie wypełnia `data-field="quote_number"`**

Modal w `products-tab-content.html` używa `data-field="quote_number"`. Render produktu w modalu wypełnia pola po `data-field` automatycznie (sprawdź szukając `data-field` w `products-module.js`):

```bash
grep -n "data-field" modules/production/static/js/modules/products-module.js | head -10
```

Jeśli render iteruje wszystkie `data-field` i wstawia `product[fieldName]` — żadna dodatkowa zmiana nie jest potrzebna, bo API już zwraca `quote_number`. Jeśli render ręcznie wypełnia każde pole — znajdź miejsce wypełniania `baselinker_order_id` i dodaj analogicznie `quote_number`:

```javascript
modal.querySelector('[data-field="quote_number"]').textContent = product.quote_number || '—';
```

(Wstaw obok podobnych wpisów dla `baselinker_order_id` / `internal_order_number`.)

- [ ] **Step 6: Commit**

```bash
git add modules/production/static/js/modules/products-module.js
git commit -m "feat(production): badge i pole modala dla numeru wyceny w liście produktów"
```

---

### Task 7: UI JS — archiwum

**Files:**
- Modify: `modules/production/static/js/modules/archive-module.js`

- [ ] **Step 1: Dodaj `quoteNumber` do agregacji**

Znajdź (~linia 171-181) blok inicjujący `order`. Dodaj `quoteNumber` analogicznie do Task 6 Step 1:

```javascript
                    clientOrderNumber: product.client_order_number,
                    quoteNumber: product.quote_number,
                    internalOrderNumber: product.internal_order_number,
```

- [ ] **Step 2: Sprawdź czy archiwum używa tego samego renderu co produkty**

```bash
grep -n "il-order-id-tag\|clientOrderNumber" modules/production/static/js/modules/archive-module.js | head -10
```

Jeśli archiwum renderuje własne badge'y — dodaj analogiczny blok `if (order.quoteNumber)` przy `il-order-id-tag` (jak w Task 6 Step 2).

Jeśli archiwum używa wspólnego renderu z `products-module.js` — żadna dodatkowa zmiana niepotrzebna.

- [ ] **Step 3: Sprawdź czy archiwum ma własną wyszukiwarkę**

```bash
grep -n "exactMatchFields\|search_pattern" modules/production/static/js/modules/archive-module.js | head
```

Jeśli tak — dodaj `'quote_number'` do listy pól wyszukiwania analogicznie do Task 6 Step 3-4.

- [ ] **Step 4: Commit**

```bash
git add modules/production/static/js/modules/archive-module.js
git commit -m "feat(production): badge i pole modala dla numeru wyceny w archiwum"
```

---

### Task 8: Skrypt backfill

**Files:**
- Create: `scripts/backfill_quote_number.py`
- Create: `tests/test_backfill_quote_number.py`

- [ ] **Step 1: Napisz testy regexu (TDD)**

Utwórz `tests/test_backfill_quote_number.py`:

```python
"""Testy regexu wyciągającego numer wyceny ze starych notatek."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATTERN = re.compile(r'^Wycena\s+(\S+?)(?:\s*-\s*(.*))?$', re.DOTALL)


def parse(notes):
    m = PATTERN.match((notes or '').strip())
    if not m:
        return None, None
    return m.group(1).strip(), (m.group(2) or '').strip()


def test_quote_only():
    qn, rest = parse("Wycena 226/04/26/W")
    assert qn == "226/04/26/W"
    assert rest == ""


def test_quote_with_note():
    qn, rest = parse("Wycena 226/04/26/W - klient pilnie czeka")
    assert qn == "226/04/26/W"
    assert rest == "klient pilnie czeka"


def test_quote_with_note_multiline():
    qn, rest = parse("Wycena 226/04/26/W - linia 1\nlinia 2")
    assert qn == "226/04/26/W"
    assert rest == "linia 1\nlinia 2"


def test_no_match_when_no_prefix():
    qn, rest = parse("Tylko notatka bez prefiksu")
    assert qn is None
    assert rest is None


def test_no_match_when_empty():
    qn, rest = parse("")
    assert qn is None


def test_extra_whitespace_around_dash():
    qn, rest = parse("Wycena 226/04/26/W    -   notatka")
    assert qn == "226/04/26/W"
    assert rest == "notatka"


def test_quote_number_truncated_to_16_chars():
    qn, _ = parse("Wycena ABCDEFGHIJKLMNOPQRSTUV")
    # parser zwraca pełen string, truncation robi caller
    assert qn[:16] == "ABCDEFGHIJKLMNOP"
```

- [ ] **Step 2: Uruchom testy (muszą przejść — to czysto testy regexu)**

```bash
python3 -m pytest tests/test_backfill_quote_number.py -v
```

Expected: 7/7 PASS.

- [ ] **Step 3: Utwórz skrypt backfill**

Utwórz `scripts/backfill_quote_number.py`:

```python
"""
Backfill numerów wyceny ze starych notatek (Wycena X - Y) do osobnej kolumny.

Użycie:
    python3 scripts/backfill_quote_number.py --dry-run   # tylko pokaż co by się stało
    python3 scripts/backfill_quote_number.py             # właściwy commit

Idempotentny: filtruje quote_number IS NULL.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.production.models import ProductionOrder

PATTERN = re.compile(r'^Wycena\s+(\S+?)(?:\s*-\s*(.*))?$', re.DOTALL)
DRY_RUN = '--dry-run' in sys.argv


def main():
    app = create_app()
    with app.app_context():
        orders = ProductionOrder.query.filter(
            ProductionOrder.quote_number.is_(None),
            ProductionOrder.order_notes.isnot(None)
        ).all()

        print(f"Znaleziono {len(orders)} zamówień z order_notes i pustym quote_number")
        if DRY_RUN:
            print("Tryb --dry-run: BRAK commitów do bazy.\n")

        updated = skipped = 0
        for o in orders:
            notes = (o.order_notes or '').strip()
            m = PATTERN.match(notes)
            if not m:
                skipped += 1
                continue
            quote_num = m.group(1).strip()[:16]
            remaining_note = (m.group(2) or '').strip()

            if DRY_RUN:
                print(f"[DRY] BL={o.baselinker_order_id} #{o.internal_order_number}: "
                      f"quote={quote_num!r}, new_notes={remaining_note!r}")
            else:
                o.quote_number = quote_num
                o.order_notes = remaining_note or None
            updated += 1

        if not DRY_RUN:
            db.session.commit()
            print(f"\n✅ Updated: {updated}, Skipped (brak prefiksu 'Wycena'): {skipped}")
        else:
            print(f"\n[DRY] Would update: {updated}, Skipped (brak prefiksu): {skipped}")


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Lokalny dry-run (jeśli w lokalnej bazie są dane testowe)**

```bash
python3 scripts/backfill_quote_number.py --dry-run
```

Expected: jeśli baza pusta — `Znaleziono 0 zamówień`. Jeśli są dane — lista `[DRY]` bez modyfikacji DB.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_quote_number.py tests/test_backfill_quote_number.py
git commit -m "feat(production): skrypt backfill numerów wyceny ze starych notatek"
```

---

### Task 9: Manualny smoke test end-to-end (dev)

**Files:** brak — manualna weryfikacja.

- [ ] **Step 1: Uruchom aplikację lokalnie**

```bash
run_local.bat
```

Otwórz `http://127.0.0.1:5000`.

- [ ] **Step 2: Wycena → wysyłka do BL**

1. Zaloguj się jako admin.
2. Otwórz istniejącą wycenę (lub utwórz nową testową).
3. Kliknij "Wyślij do Baselinker" / odpowiednia akcja.
4. W panelu Baselinker (dev/sandbox) sprawdź:
   - `admin_comments` zawiera **tylko** notatkę użytkownika (lub jest pusty).
   - Pole dodatkowe ID 170043 zawiera numer wyceny.

- [ ] **Step 3: Sync z BL → produkcja**

1. W panelu produkcji (Dashboard → Produkty) kliknij "Synchronizuj z Baselinker".
2. Sprawdź w bazie:

```sql
SELECT baselinker_order_id, internal_order_number, quote_number, order_notes
FROM prod_orders
WHERE baselinker_order_id = <ID_ZAMÓWIENIA_TESTOWEGO>;
```

Oczekiwane: `quote_number` wypełniony, `order_notes` zawiera samą notatkę (lub NULL).

- [ ] **Step 4: UI — Lista produktów**

1. W Dashboardzie → zakładka "Lista produktów".
2. Sprawdź wiersz testowego zamówienia: pod nazwą klienta widać 4 badge'y, ostatni z numerem wyceny.
3. Kliknij wiersz → modal otwarty.
4. Sekcja "Identyfikacja" → pole "Numer wyceny" wypełnione.

- [ ] **Step 5: UI — Archiwum**

Analogiczna weryfikacja w zakładce "Archiwum" (jeśli zamówienie jest archiwalne lub przejdzie do archiwum).

- [ ] **Step 6: Wyszukiwarka**

W zakładce "Lista produktów" wpisz numer wyceny w wyszukiwarkę. Lista powinna się przefiltrować do tego zamówienia.

- [ ] **Step 7: Backfill dry-run (na lokalnej DB jeśli są stare dane)**

```bash
python3 scripts/backfill_quote_number.py --dry-run
```

Sprawdź output — żadnych commitów do bazy, lista propozycji.

- [ ] **Step 8: Backfill właściwy (na lokalnej DB)**

```bash
python3 scripts/backfill_quote_number.py
```

Weryfikuj SQL-em że stare rekordy mają `quote_number` wypełniony, a `order_notes` nie zaczyna się od "Wycena ".

---

### Task 10: Deploy na produkcję

**Files:** brak — manualne kroki deploymentowe.

- [ ] **Step 1: ALTER TABLE na produkcyjnej DB**

User wykonuje ręcznie przez phpMyAdmin na hostingu:

```sql
ALTER TABLE prod_orders
  ADD COLUMN quote_number VARCHAR(16) NULL AFTER internal_order_number;
CREATE INDEX idx_prod_orders_quote_number ON prod_orders(quote_number);
```

Weryfikacja: `DESCRIBE prod_orders;`.

- [ ] **Step 2: Push na main**

```bash
git push origin main
```

GitHub Actions zrobi deploy. Po deployu touch tmp/restart.txt automatycznie zrestartuje Passengera.

- [ ] **Step 3: SSH na prod — backfill dry-run**

```bash
ssh -p 222 user@195.78.66.85
cd ~/domains/crm.woodpower.pl/public_html/app
source ~/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate
python3 scripts/backfill_quote_number.py --dry-run | tee /tmp/backfill_dryrun.log
```

Przejrzyj `/tmp/backfill_dryrun.log` — sprawdź czy regex łapie historyczne notatki poprawnie.

- [ ] **Step 4: Backfill właściwy**

```bash
python3 scripts/backfill_quote_number.py | tee /tmp/backfill.log
```

Oczekiwane: `Updated: N, Skipped: M` z sumą zgadzającą się z `--dry-run`.

- [ ] **Step 5: Weryfikacja po deployu**

W panelu produkcji:
- Wykonaj sync z BL dla świeżego zamówienia → `quote_number` wypełniony.
- Sprawdź modal historycznego zamówienia → pole "Numer wyceny" z backfillowaną wartością.

---

## Self-Review

**1. Spec coverage:**
- Schemat bazy (sekcja 1 specu) → Task 1 ✓
- Baselinker `_build_user_comments` + `custom_extra_fields` (sekcja 2) → Task 2 ✓
- Production sync ekstrakcja + ORDER_LEVEL_KEYS + compare (sekcja 3) → Task 3 ✓
- UI Lista produktów (sekcja 4a-b) → Task 6 ✓
- UI Modal Identyfikacja (sekcja 4b) → Task 5 (HTML) + Task 6 Step 5 (JS) ✓
- UI Archiwum (sekcja 4c) → Task 7 ✓
- Wyszukiwarka (sekcja 4d) → Task 3 (backend) + Task 6 Steps 3-4 (frontend) ✓
- Serializer (sekcja 4e) → Task 4 ✓
- Backfill (sekcja 5) → Task 8 ✓
- Kolejność wdrożenia (sekcja 6) → Task 10 ✓

**2. Placeholder scan:** brak TBD/TODO/"implement later". Każdy step ma konkretne kod/komendy.

**3. Type consistency:** `quote_number` używane spójnie wszędzie (snake_case w bazie/Pythonie, `quoteNumber` w JS — zgodnie z konwencją projektu).

**4. Drobne uwagi:**
- Task 6 Step 5 ma branching ("jeśli render iteruje / jeśli ręcznie") — to konieczne, bo nie znamy jeszcze wzorca render-u modalu. Engineer wykonujący plan użyje `grep` jak wskazano i wybierze właściwą gałąź.
- Task 7 Step 2-3 podobnie — analogiczne wzorce do products-module.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-24-quote-number-separate-field.md`. Dwie opcje wykonania:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review po każdym, szybka iteracja.
2. **Inline Execution** — wykonanie w tej sesji z checkpointami.

Które wybierasz?
