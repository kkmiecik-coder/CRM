# Stanowisko Logistyka — Design Spec

## Problem

Brak pośredniego kroku między produkcją (formatowanie/wykańczanie) a pakowaniem, w którym decyduje się o sposobie transportu zamówienia. Stanowisko pakowania musi wiedzieć czy wysyłamy kurierem, transportem WoodPower, czy klient odbiera osobiście — ta decyzja wpływa na sposób pakowania.

## Rozwiązanie

Nowe stanowisko "Logistyka" w flow produkcyjnym. Zatrzymuje zamówienia z dostawą inną niż odbiór osobisty. Operator widzi dane adresowe i kontekst zamówienia, wybiera sposób transportu, zatwierdza. Zamówienie przechodzi na pakowanie z ustaloną decyzją.

---

## 1. Model danych

### Nowe pola w `ProductionItem`:

| Pole | Typ | Default | Opis |
|------|-----|---------|------|
| `override_delivery_method` | String(255) | NULL | Nadpisanie sposobu dostawy. NULL = brak decyzji |
| `logistics_completed_at` | DateTime | NULL | Timestamp zatwierdzenia decyzji logistycznej |

### Nowy status:

`czeka_na_logistyke` — dodany do enuma statusów, pomiędzy `czeka_na_wykanczanie` a `czeka_na_pakowanie`.

### Wartości `override_delivery_method`:

- `NULL` — brak decyzji (lub odbiór osobisty — omija stanowisko)
- `"kurier_baselinker"` — wysyłka oryginalnym kurierem z Baselinkera
- `"transport_woodpower"` — transport własny WoodPower

### Nie dodajemy:

- `quantity_done_logistics` — stanowisko działa na poziomie zamówienia, nie sztuka po sztuce
- `logistics_started_at` — niepotrzebne
- `logistics_note` — używamy istniejącego `production_notes`

---

## 2. Flow produkcyjny

### Trigger wejścia na Logistykę:

W momencie gdy produkt miałby dostać status `czeka_na_pakowanie` (po zakończeniu ostatniego stanowiska produkcyjnego — formatowania lub wykańczania):

- Jeśli `is_personal_pickup == True` → status `czeka_na_pakowanie` (omija logistykę, bez zmian)
- Jeśli `is_personal_pickup == False` → status `czeka_na_logistyke`

To przechwytuje dokładnie w jednym punkcie — tam gdzie istniejący kod ustawia `current_status = 'czeka_na_pakowanie'` po ukończeniu ostatniego stanowiska.

### Zatwierdzenie na Logistyce:

Operator wybiera sposób transportu → klik "Zatwierdź":
- Ustawiane: `override_delivery_method`, `logistics_completed_at = now()`
- Status zmienia się na `czeka_na_pakowanie`
- Zmiana dotyczy WSZYSTKICH produktów w zamówieniu (grupowe zatwierdzenie)

### Odbiór osobisty:

Zamówienia z `is_personal_pickup == True` nigdy nie trafiają na stanowisko Logistyka. Istniejąca logika `is_personal_pickup` (sprawdza `delivery_method` + puste dane adresowe) działa bez zmian.

---

## 3. UI — widok stanowiska Logistyka

### Dostęp:

- Przycisk/karta na dashboardzie produkcji (sekcja stanowisk), widoczny dla zalogowanych użytkowników
- NIE pojawia się w `/stations/station-select` (to jest dla tabletów)
- Otwiera się w tej samej karcie przeglądarki
- Wymaga zalogowania (nie IP whitelist jak stacje tabletowe)

### Widok — lista zamówień:

Lista zamówień ze statusem `czeka_na_logistyke`, pogrupowana po zamówieniach. Dla każdego zamówienia:

**Dane kontekstowe:**
- Nazwa klienta, numer zamówienia (wewnętrzny + Baselinker)
- Adres dostawy: miasto, kod pocztowy, ulica, kraj
- Obecny sposób dostawy z Baselinkera (`delivery_method`) — to co klient wybrał
- Liczba produktów w zamówieniu
- Łączna objętość m³
- Notatka produkcyjna (`production_notes`) — edytowalna

**Decyzja:**
- Select/radio z opcjami: "Kurier (z Baselinker)", "Transport WoodPower"
- Przycisk "Zatwierdź i prześlij na pakowanie"

**Styl:** IL design system (jak reszta dashboardu — karty, monospace headers, 3px radius, brak cieni).

---

## 4. Wpływ na istniejący system

### Dashboard:
- Nowa karta "Logistyka" w sekcji stanowisk — lżejsza niż stacje produkcyjne (liczba oczekujących zamówień + link)
- Nie potrzebuje: m³ dziś, ukończonych dziś, progress bara

### Timeline w modalu produktu:
- Nowy krok "Logistyka" między wykańczanie/formatowanie a pakowanie
- Logika skip: `is_personal_pickup` → "Pominięto", `logistics_completed_at` → "Zakończone", `czeka_na_logistyke` → "W trakcie"

### Raporty:
- `czeka_na_logistyke` pojawi się automatycznie w "Rozkład produktów według statusów" (zapytanie jest dynamiczne z GROUP BY)

### Lista produktów (JS):
- `czeka_na_logistyke` → wpis w `STATUS_CONFIG` i `getStatusConfig()` — ikona: `fa-truck`, nazwa: "Logistyka", kolor: nowy kolor stanowiska

### Stanowisko pakowania:
- Wyświetla `override_delivery_method` zamiast oryginalnego `delivery_method` (jeśli ustawione)
- Operator pakowania widzi: "Transport WoodPower" lub "Kurier DPD" — wie jak pakować

### Czego NIE zmieniamy:
- Stacje tabletowe (`/stations/*`) — logistyka nie jest stacją tabletową
- Sync z Baselinker — `delivery_method` nie jest nadpisywane w Baselinkerze, `override_delivery_method` to pole wewnętrzne
- `is_personal_pickup` property — działa bez zmian

---

## 5. Pliki do modyfikacji/utworzenia

### Nowe pliki:
- `modules/production/templates/logistics/logistics.html` — szablon widoku stanowiska
- `modules/production/routers/api/logistics_api.py` — API endpoints (lista zamówień, zatwierdzenie)

### Modyfikowane:
- `modules/production/models.py` — nowe pola + status
- `modules/production/routers/api/__init__.py` — import logistics_api
- `modules/production/templates/components/dashboard-tab-content.html` — karta Logistyka
- `modules/production/routers/api/dashboard_api.py` — dane dla karty Logistyka
- `modules/production/static/js/modules/products-module.js` — STATUS_CONFIG + getStatusConfig + timeline
- `modules/production/static/css/production-panel.css` — kolor stanowiska logistyka
- Logika zmiany statusu (tam gdzie ustawiany jest `czeka_na_pakowanie` po produkcji) — dodanie sprawdzenia `is_personal_pickup`
