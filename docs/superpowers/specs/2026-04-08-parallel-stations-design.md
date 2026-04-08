# Równoległe stanowiska Wycinanie/Składanie — Design Spec

**Data:** 2026-04-08
**Status:** Zatwierdzony

## Cel

Zmiana przepływu produkcyjnego z sekwencyjnego (Wycinanie → Składanie → Sklejanie → ...) na równoległy dla dwóch pierwszych stanowisk. Pozycje trafiają na stanowisko wg technologii:

- **mikrowczep** → Wycinanie - mikro
- **lity** → Składanie - lite

Z obu stanowisk pozycje przechodzą na Sklejanie. Dalsza ścieżka bez zmian.

## Nowy przepływ

```
┌─ Wycinanie - mikro (parsed_technology == 'mikrowczep') ─┐                    ┌→ Wykańczanie → Logistyka ─┐
│                                                           ├→ Sklejanie → Formatowanie ─┤                          ├→ Pakowanie
└─ Składanie - lite  (parsed_technology == 'lity')        ─┘                    └→ Logistyka (surowe) ─────┘
```

Istniejące skip-y zostają:
- Surowe (`parsed_finish_state == 'surowe'`) pomijają Wykańczanie
- Odbiór osobisty (`is_personal_pickup`) pomija Logistykę

## Zmiany

### 1. Import z BaseLinker — przypisanie pierwszego stanowiska

**Plik:** `modules/production/services/sync_service.py` (~linia 1091)

Zamiast hard-coded `'current_status': 'czeka_na_wyciecie'`:
- `parsed_technology == 'mikrowczep'` → `current_status = 'czeka_na_wyciecie'`
- `parsed_technology == 'lity'` → `current_status = 'czeka_na_skladanie'`
- Inna wartość lub `None` → odrzucenie **całego zamówienia**

### 2. Walidacja technologii przy imporcie

**Walidacja na poziomie zamówienia:** Jeśli choć jedna pozycja zamówienia ma nierozpoznaną technologię (`parsed_technology` nie jest `mikrowczep` ani `lity`):
- Żadna pozycja z tego zamówienia nie trafia do systemu
- Zamówienie zostaje w BaseLinker ze starym statusem
- Błąd zapisany w `ProductionError` z typem `unknown_technology`
- Komunikat: "Nierozpoznana technologia w pozycji [nazwa] zamówienia [numer]"
- Widoczny na stronie `/production/admin/` → błędy systemu

### 3. Modal importu (Krok 3) — walidacja i wyświetlanie

**Plik:** `modules/production/static/js/modules/dashboard_bl_sync_modal.js`

Zamówienia z błędem technologii:
- Wyświetlone na liście, ale **zablokowane** — checkbox wyłączony, nie można zaznaczyć
- Czerwony badge na zamówieniu: `⚠ Nierozpoznana technologia`
- Przy produkcie z problemem: czerwony label `(nieznana technologia)`
- Backend w odpowiedzi `fetch_orders_preview` dodaje: `technology_error: true` na zamówieniu, `unknown_technology: true` na produkcie

Dodatkowo przy każdym produkcie: mały badge obok nazwy produktu z rozpoznaną technologią ("mikrowczep" / "lite") w neutralnym kolorze (szary/niebieski) — żeby operator widział co system rozpoznał.

### 4. `complete_task()` — zmiana mapy przejść

**Plik:** `modules/production/models.py` (linie 607-614)

```python
# PRZED:
next_status_map = {
    'cutting': 'czeka_na_skladanie',
    'assembly': 'czeka_na_sklejanie',
    ...
}

# PO:
next_status_map = {
    'cutting': 'czeka_na_sklejanie',   # cutting → sklejanie (nie składanie)
    'assembly': 'czeka_na_sklejanie',  # bez zmian
    ...
}
```

Usunąć logikę `skipped_cutting` (linie 604, 619-628, 666) — nie ma scenariusza pomijania wycinania przez składanie.

### 5. Nazwy stanowisk — zmiana display names

Zmiana "Wycinanie" → **"Wycinanie - mikro"** i "Składanie" → **"Składanie - lite"** we wszystkich miejscach:

**Python backend:**
- `routers/api/stations_api.py` — station name mapping (~linie 92-99)
- `routers/api/dashboard_api.py` — chart labels (~linie 302-309, 1165, 1190)
- `routers/stations/interfaces.py` — station_name kwarg (~linia 187+)
- `routers/stations/monitors.py` — status-to-display mappings (~linie 184, 330)
- `routers/stations/__init__.py` — station config (~linie 605, 647, 658)

**HTML templates:**
- `templates/components/dashboard-tab-content.html` — hardcoded names (~linie 24, 61)
- `templates/stations/cutting.html` — JS config stationName (~linia 268)
- `templates/stations/assembly.html` — JS config stationName (~linia 268)

**JavaScript:**
- `static/js/modules/dashboard-module.js` — ternary mapping (~linia 286)
- `static/js/modules/products-module.js` — STATUS_TRANSLATIONS, STATUS_CONFIG, getStatusConfig(), timeline stations (~linie 27-28, 42-59, 3676-3693, 3974-3995)

Kody stanowisk (`cutting`, `assembly`) i statusy DB (`czeka_na_wyciecie`, `czeka_na_skladanie`) — **bez zmian**.

### 6. Usunięcie cross-pollingu cutting↔assembly

Stanowiska obsługują różne pozycje — polling postępu drugiego stanowiska nie ma sensu.

**Usunąć:**
- `static/js/stations/station-assembly.js` — polling postępu wycinania (~linie 130-250), badge ✂ z nożyczkami (~linia 1083)
- `static/js/stations/station-cutting.js` — polling postępu składania (~linie 130-250)
- `templates/stations/assembly.html` — badge `badge-cut` z nożyczkami (~linia 185)
- `static/js/modules/products-module.js` — logika "Pominięto wycinanie" (~linie 3919-3929), `prevStations` mapping (~linie 3947-3949)

### 7. Timeline w modalu szczegółów produktu

**Plik:** `modules/production/static/js/modules/products-module.js`

Timeline filtruje stanowiska wg `parsed_technology` produktu:
- `mikrowczep`: Wycinanie - mikro → Sklejanie → Formatowanie → Wykańczanie → Logistyka → Pakowanie (bez Składanie)
- `lity`: Składanie - lite → Sklejanie → Formatowanie → Wykańczanie → Logistyka → Pakowanie (bez Wycinanie)

Zmiana w:
- `generateTimeline()` (~linia 3670) — filtrowanie listy `stations` na podstawie `product.parsed_technology`
- `generateQuantityProgress()` (~linia 3786) — analogiczny filtr dla progress %
- `getTimelineState()` (~linia 3842) — usunięcie logiki skip cutting/assembly

### 8. Backend — daty i quantity

**Bez zmian strukturalnych.** Kolumny `quantity_done_cutting`, `cutting_completed_at`, `quantity_done_assembly`, `assembly_completed_at` pozostają. Każdy produkt używa tylko swojego zestawu kolumn — nieużywane zostają na 0/NULL.

Metody `set_quantity_done()`, `increment_quantity_done()`, `decrement_quantity_done()`, `is_station_complete()` — generyczne, działają poprawnie bez zmian.

### 9. Migracja danych

Brak potrzeby migracji — moduł produkcji nie jest jeszcze aktywny na produkcji. Istniejące lokalne dane można usunąć.

## Poza zakresem

- Zmiana kodów stanowisk (`cutting`/`assembly`) w DB — zostają obecne
- Konfigurowalny graf stanowisk — YAGNI
- Model Station w DB — YAGNI
- Centralizacja nazw stanowisk w jednym miejscu — nice-to-have ale poza tym zadaniem
