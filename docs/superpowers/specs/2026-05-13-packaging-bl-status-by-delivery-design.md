# Status BL po pakowaniu w zależności od metody dostawy

**Data:** 2026-05-13
**Moduł:** `production` — integracja Baselinker
**Zakres:** zmiana logiki wyboru statusu BL wysyłanego po ukończeniu pakowania zamówienia.

## Problem

Po ukończeniu pakowania (ostatni produkt zamówienia osiąga `current_status='spakowane'`) integracja BL wysyła zawsze ten sam status: **138623 "Zamówienie spakowane"**. Biznesowo jednak status powinien zależeć od metody dostawy zamówienia, bo dalsza obsługa rozgałęzia się na trzy ścieżki.

## Cel

Wybierać docelowy status BL na podstawie typu dostawy zamówienia:

| Typ dostawy | Status BL | ID |
|---|---|---|
| Odbiór osobisty | Czeka na odbiór osobisty | **149777** |
| Transport WoodPower | Planowana trasa | **417343** |
| Kurier (Baselinker) | Zamówienie spakowane | **138623** *(bez zmian)* |

## Sposób rozpoznania typu dostawy

Mechanizm istnieje już w bazie:

- **Odbiór osobisty** — property `ProductionOrder.is_personal_pickup` (`modules/production/models.py:170`). Heurystyka oparta na słowach kluczowych w `delivery_method` i braku adresu dostawy. Zamówienia takie pomijają stanowisko logistyki (patrz `complete_task` w `models.py:505`).
- **Transport WoodPower vs Kurier** — pole `ProductionOrder.override_delivery_method` ustawiane przez panel logistyki (`modules/production/routers/api/logistics_api.py:114` endpoint `POST /logistics/approve`). Dozwolone wartości: `'kurier_baselinker'` lub `'transport_woodpower'`.

Reguła decyzyjna (w kolejności):

1. `order.is_personal_pickup == True` → **149777** (Czeka na odbiór osobisty)
2. `order.override_delivery_method == 'transport_woodpower'` → **417343** (Planowana trasa)
3. `order.override_delivery_method == 'kurier_baselinker'` → **138623** (Zamówienie spakowane)
4. Fallback (np. `override_delivery_method=NULL` i nie-personal-pickup) → **138623** + `logger.warning`. Prawdopodobieństwo bliskie 0 (logistyka jest wymagana zanim pakowanie startuje), ale zachowujemy defensywę.

Kolejność warunków jest istotna: `is_personal_pickup` musi być pierwsze, bo dla odbioru osobistego `override_delivery_method` często będzie `NULL` (zamówienie pomija logistykę) — bez tej kolejności wpadłoby w fallback.

## Architektura zmiany

Zmiana ograniczona do jednego pliku: `modules/production/services/baselinker_status_sync.py`. Plik ten jest "single owner" całej logiki "kto i kiedy zmienia status zamówienia w BL", więc rozróżnienie typu dostawy ląduje w jednym miejscu.

**Bez zmian** w: modelach, schemacie DB, endpointach (`complete-order` web + mobile), `complete_task`, panelu logistyki, retry/backoff, agregatorze "wszystkie produkty spakowane".

### Nowe stałe

```python
ORDER_PACKED_STATUS_ID = 138623             # kurier (istnieje)
WAITING_PERSONAL_PICKUP_STATUS_ID = 149777  # NOWE — odbiór osobisty
PLANNED_ROUTE_STATUS_ID = 417343            # NOWE — transport WoodPower
```

### Nowy helper

```python
def _determine_packaging_target_status(order) -> int:
    """
    Wybiera ID statusu BL dla zakończonego pakowania na podstawie typu dostawy.

    - is_personal_pickup                              → 149777
    - override_delivery_method == 'transport_woodpower' → 417343
    - override_delivery_method == 'kurier_baselinker'   → 138623
    - inne / NULL                                       → 138623 + warn log
    """
    if order.is_personal_pickup:
        return WAITING_PERSONAL_PICKUP_STATUS_ID

    override = (order.override_delivery_method or '').strip()
    if override == 'transport_woodpower':
        return PLANNED_ROUTE_STATUS_ID
    if override == 'kurier_baselinker':
        return ORDER_PACKED_STATUS_ID

    logger.warning("Pakowanie ukończone bez decyzji logistyki - fallback na 'spakowane'", extra={
        'internal_order_number': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'override_delivery_method': order.override_delivery_method,
    })
    return ORDER_PACKED_STATUS_ID
```

### Modyfikacja `_process_pending`

W obecnym kodzie (`baselinker_status_sync.py:225-228`):

```python
if station_code == 'packaging':
    if not all(p.current_status == 'spakowane' for p in products):
        return
    target = ORDER_PACKED_STATUS_ID
```

Po zmianie:

```python
if station_code == 'packaging':
    if not all(p.current_status == 'spakowane' for p in products):
        return
    target = _determine_packaging_target_status(products[0].order)
```

Reszta funkcji (`baselinker_order_id`, `_call_set_order_status`, retry) bez zmian — `target` jest abstrakcją, retry odpala się identycznie dla każdego z trzech ID.

## Edge cases

1. **`override_delivery_method = NULL` + nie-personal-pickup** — fallback na 138623 + warning. Nie powinno się zdarzyć (logistyka jest wymagana przed pakowaniem), ale defensywnie.
2. **Mixed override w produktach** — niemożliwe: `logistics_approve` ustawia `override_delivery_method` na `ProductionOrder` (kolumna w `prod_orders`), nie per-produkt. Helper czyta `products[0].order`, jedno źródło prawdy.
3. **Doróbka po pakowaniu oryginału** — agregator dalej liczy WSZYSTKIE prod_products (włącznie z doróbkami `original_product_id IS NOT NULL`), warunek "wszystkie spakowane" gwarantuje wysłanie statusu dopiero po spakowaniu doróbki. Doróbka dziedziczy `is_personal_pickup`/`override_delivery_method` z tego samego order.
4. **Anulowane zamówienie podczas pakowania** — produkt `current_status='anulowane'` nie spełnia warunku `== 'spakowane'`, BL nie dostaje aktualizacji. Zachowanie obecne, nie zmieniamy.

## Weryfikacja

Pomijamy formalne testy jednostkowe (mock SQLAlchemy dla jednego helpera + jednej linii zmiany jest większy niż sama zmiana). Zamiast tego:

### Dry-run trace po implementacji

Po zaimplementowaniu, przejść linia po linii przez `_determine_packaging_target_status` z trzema sample orderami i zaraportować jaką gałąź każdy hituje + jaki `target` zwraca:

1. **Scenariusz "odbiór osobisty"**
   - `delivery_method='Odbiór osobisty'`, `override_delivery_method=NULL`
   - Oczekiwane: `is_personal_pickup=True` → return **149777**

2. **Scenariusz "transport WoodPower"**
   - `delivery_method='InPost Kurier'`, `override_delivery_method='transport_woodpower'`
   - Oczekiwane: `is_personal_pickup=False`, override matches → return **417343**

3. **Scenariusz "kurier"**
   - `delivery_method='InPost Kurier'`, `override_delivery_method='kurier_baselinker'`
   - Oczekiwane: `is_personal_pickup=False`, override matches → return **138623**

### Smoke test produkcyjny

Po deploy ręcznie zweryfikować trzy zamówienia (po jednym z każdej kategorii) — czy po ukończeniu pakowania w panelu BL ustawia się właściwy status.

## Out of scope

- Tworzenie etykiety/przesyłki kurierskiej (osobny flow w `shipping_service.py` + panel admina).
- Zmiany w mobile API endpoincie `POST /api/mobile/orders/<id>/complete` — używa tego samego hook'a `flush_pending_syncs`, więc nowa logika działa automatycznie.
- Zmiany w statusie po imporcie ("W produkcji - X") — niezwiązane.
- Refaktor `is_personal_pickup` (heurystyka stringowa) — działa, nie ruszamy.

## Pliki dotknięte

- `modules/production/services/baselinker_status_sync.py` — dodanie 2 stałych, 1 helper'a, 1 linia zmiany w `_process_pending`.
