# Numer wyceny — osobne pole w Baselinker i prod_orders

**Status:** Design zaakceptowany — gotowy do planu wdrożenia
**Data:** 2026-05-24

## Problem

Aktualnie numer wyceny (`quotes.quote_number`, np. `226/04/26/W`) jest doklejany do notatki zamówienia wysyłanej do Baselinker przez `_build_user_comments()` w `modules/baselinker/service.py:1205`, w formacie `"Wycena {quote_number} - {notes}"`. Wynik trafia do pola `admin_comments` zamówienia BL i — przez sync — do kolumny `prod_orders.order_notes` w bazie produkcji.

Skutki:
- Notatka w panelu BL jest zaśmiecona prefiksem nawet gdy nie ma realnej notatki użytkownika (na screenie produkcji widać `NOTATKA Z BASELINKERA: Wycena 226/04/26/W` jako jedyną treść).
- Numer wyceny nie jest osobnym, indeksowanym polem — nie można po nim wygodnie filtrować w panelu produkcji ani w BL.
- Limit 200 znaków pola jest zjadany przez prefiks.

## Cel

Rozdzielić numer wyceny od notatki:
- W BL numer wyceny ląduje w dedykowanym polu dodatkowym **`extra_field_170043`** (utworzonym ręcznie w panelu BL).
- W `prod_orders` powstaje nowa kolumna `quote_number` (VARCHAR(16), indexed, nullable).
- W panelu produkcji numer wyceny wyświetla się jako osobny badge w wierszu listy produktów i jako pole w sekcji "Identyfikacja" modala szczegółów (zarówno "Lista produktów" jak i "Archiwum").
- Historyczne rekordy zostają posprzątane jednorazowym skryptem backfill uruchamianym przez SSH.

## Architektura zmian

### 1. Schemat bazy

```sql
ALTER TABLE prod_orders
  ADD COLUMN quote_number VARCHAR(16) NULL AFTER internal_order_number;
CREATE INDEX idx_prod_orders_quote_number ON prod_orders(quote_number);
```

ALTER wykonuje user ręcznie przez phpMyAdmin **przed deployem kodu** (zgodnie z polityką [[feedback_db_operations]] — brak idempotent migracji ze względu na blokadę `information_schema` na hostingu).

W modelu `modules/production/models.py:130` dodanie pola obok `client_order_number`/`order_notes`:

```python
quote_number = Column(String(16), index=True)
```

Pole jest na poziomie zamówienia (`ProductionOrder`), nie produktu (`ProductionProduct`).

### 2. Strona Baselinker — wysyłka

Plik: `modules/baselinker/service.py`

**a) `_build_user_comments()` (linia 1205) — przestaje sklejać numer wyceny:**

```python
def _build_user_comments(self, quote):
    """Zwraca samą notatkę użytkownika (numer wyceny idzie do extra_field_170043)."""
    notes = (quote.notes or '').strip()
    if len(notes) > 200:
        notes = notes[:197] + '...'
    return notes
```

**b) `order_data['custom_extra_fields']` (linia 843-846) — dorzucenie nowego pola:**

```python
'custom_extra_fields': {
    '105623': creator_name,                 # Opiekun
    '106169': payment_type_value,           # Typ płatności (Brutto/Netto)
    '170043': quote.quote_number or '',     # 🆕 Numer wyceny
},
```

Efekt: `admin_comments` w BL zawiera odtąd tylko notatkę (lub jest pusty); numer wyceny ląduje w dedykowanym polu dodatkowym.

### 3. Strona Production — sync z BL

Plik: `modules/production/services/sync_service.py`

**a) Ekstrakcja `quote_number` z `custom_extra_fields['170043']`** (w okolicy linii 1092-1109, analogicznie do `extra_field_1`):

```python
custom_fields = order.get('custom_extra_fields', {}) or {}
quote_number = (custom_fields.get('170043') or '').strip() or None
if quote_number:
    product_data['quote_number'] = quote_number
```

**b) Zapis do `ProductionOrder`** — w funkcji tworzącej/aktualizującej order, obok `client_order_number` i `order_notes`. Pole pochodzi z poziomu zamówienia BL i ląduje na poziomie `prod_orders`.

**c) `compare_order_with_baselinker()` (linia 1830+)** — dodanie porównania `quote_number` analogicznego do `client_order_number`, żeby diff w panelu admina pokazywał rozjazd między BL a bazą produkcji.

### 4. UI Dashboardu produkcji

**a) Lista produktów — wiersz tabeli:**

`modules/production/static/js/modules/products-module.js`:
- `:1342-1370` (`groupProductsByOrder`) — dorzucenie `quoteNumber: product.quote_number` do agregowanego obiektu order.
- `:1529-1535` — dodanie czwartego badge'a pod nazwą klienta, obok `internal_order_number`, `BL-XXX`, `client_order_number`. Format: sam numer (`226/04/26/W`), bez prefiksu — spójnie z istniejącym wzorcem `il-order-id-tag`.

**b) Modal szczegółów — sekcja "Identyfikacja":**

Render modala (lokalizacja w `products-module.js` — do zidentyfikowania w planie wdrożenia): dodanie pola `NUMER WYCENY` w lewej kolumnie sekcji "Identyfikacja", pod `BASELINKER ID`. Wartość: `product.quote_number` lub pusty string (gdy brak).

**c) Archiwum:**

`modules/production/static/js/modules/archive-module.js:171-181` — analogiczna agregacja jak w `products-module.js`; ten sam wzorzec UI (badge + pole w modalu).

**d) Wyszukiwarka / filtrowanie:**

Dodanie `'quote_number'` do:
- `products-module.js:359` (`exactMatchFields`)
- `products-module.js:2451` (`fields` dla wyszukiwarki)
- analogicznie w `archive-module.js`

**e) Serializer API:**

Endpoint zwracający produkty (w `modules/production/routers/`) — dorzucenie `quote_number` z joinu `ProductionOrder` do JSON-a (pole na poziomie order, więc każdy produkt z danego zamówienia ma tę samą wartość; w odpowiedzi pojawia się jako `product.quote_number` przez `joinedload(ProductionProduct.order)`).

### 5. Backfill historycznych zamówień

Plik: `scripts/backfill_quote_number.py`

Skrypt jednorazowy uruchamiany przez SSH na produkcji. Idempotentny (filtruje `quote_number IS NULL`).

```python
import re, sys
from app import create_app
from extensions import db
from modules.production.models import ProductionOrder

PATTERN = re.compile(r'^Wycena\s+(\S+?)(?:\s*-\s*(.*))?$', re.DOTALL)
DRY_RUN = '--dry-run' in sys.argv

app = create_app()
with app.app_context():
    orders = ProductionOrder.query.filter(
        ProductionOrder.quote_number.is_(None),
        ProductionOrder.order_notes.isnot(None)
    ).all()

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
    print(f"{'[DRY] would update' if DRY_RUN else 'Updated'}: {updated}, "
          f"Skipped (no match): {skipped}")
```

**Bezpieczeństwo:**
- `--dry-run` tylko loguje, **żadnego `commit()`**, baza nietknięta.
- Skrypt zostaje w repo (nie usuwany po uruchomieniu) — pomocny przy ewentualnej weryfikacji/rollbacku.

### 6. Kolejność wdrożenia

1. Utworzenie pola dodatkowego w BL: **ID 170043** ✓ (wykonane).
2. **ALTER TABLE** przez phpMyAdmin (dodanie `quote_number` + indeksu).
3. Deploy kodu (push na `main` → GitHub Actions). Od tego momentu nowe zamówienia mają numer wyceny w nowym polu.
4. SSH na prod: `python3 scripts/backfill_quote_number.py --dry-run` — weryfikacja co skrypt zrobi (bez modyfikacji bazy).
5. SSH: `python3 scripts/backfill_quote_number.py` — właściwy backfill.

## Decyzje i ich uzasadnienie

- **`VARCHAR(16)` zamiast 50:** user potwierdził, że format `XX/MM/RR/L` (np. `226/04/26/W`) mieści się w 16 znakach.
- **Backfill regexem zamiast joinu z `quotes`:** prostsze, nie wymaga sprawdzania istnienia relacji `quotes.baselinker_order_id`. Skrypt obsługuje też przypadki gdy notatka ma dodatkową treść po `" - "`.
- **Brak prefiksu `Wycena` w badge'u listy:** spójność z innymi badge'ami (`BL-X`, `client_order_number` — gołe numery).
- **`extra_field_170043` jako string (`quote.quote_number or ''`):** BL akceptuje puste stringi w extra_field; brak quote_number to edge case (manual_entry / starsze flow), więc zapis pustego pola w BL jest akceptowalny.
- **`_build_user_comments()` zwraca pusty string gdy brak notatki:** akceptowalne — `admin_comments=''` w BL jest poprawne i czyste.

## Zakres celowo poza specem

- **Edycja `quote_number` z poziomu dashboardu produkcji:** poza zakresem — pole jest read-only, ustawiane tylko przez sync z BL lub backfill.
- **Wyświetlenie w stacjach (Android / web stations):** poza zakresem — operatorzy stanowisk nie potrzebują numeru wyceny.
- **Migracja `quote_number` w innych systemach (kalkulator, quoty):** poza zakresem — to tylko transport BL → produkcja.

## Pliki do zmiany (skrócona lista)

- `modules/production/models.py` (+1 kolumna)
- `modules/baselinker/service.py` (`_build_user_comments`, `order_data`)
- `modules/production/services/sync_service.py` (ekstrakcja + zapis + compare)
- `modules/production/routers/` (serializer — endpoint listy produktów)
- `modules/production/static/js/modules/products-module.js` (agregacja, badge, modal, wyszukiwarka)
- `modules/production/static/js/modules/archive-module.js` (j.w. dla archiwum)
- `scripts/backfill_quote_number.py` (nowy plik)
