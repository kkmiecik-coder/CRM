# Production Page Optimization - Design Spec

## Problem

Strona `/production/` ma problemy z wydajnością i utrzymaniem kodu:
1. Przełączanie zakładek wymaga AJAX request za każdym razem (wolne)
2. `api_routers.py` ma 327KB - niemożliwy do utrzymania
3. Status synchronizacji + przycisk "Odśwież system" z licznikiem nie działa poprawnie przy zmianie zakładek (timer się zatrzymuje)
4. Nagłówek `<h1>` i sekcja `.user-greeting` marnują przestrzeń pionową

## Rozwiązanie

### 1. Prefetch hot tabs + skeleton loading

**Flow przy wejściu na stronę:**
1. Render `dashboard.html` z wbudowanymi skeletonami (HTML+CSS) dla Dashboard i Produktów
2. Skeletony widoczne natychmiast (zero JS delay)
3. Równoległy prefetch Dashboard + Produkty (`Promise.all`)
4. Gdy dane przyjdą → skeleton zamieniony na content (fade-in 150-200ms CSS transition)

**Flow przy przełączaniu zakładek:**
- Załadowana zakładka zostaje w DOM (cache) - przełączanie = instant DOM swap
- Lazy tabs (Raporty, Stanowiska, Konfiguracja) → skeleton pojawia się przy pierwszym kliknięciu, potem cache
- Auto-refresh aktualizuje dane w aktywnej zakładce (nie przeładowuje HTML)

**Skeleton loading:**
- Skeletony dla hot tabs (Dashboard, Produkty) zahardcodowane w `dashboard.html`
- Lazy tabs mają skeleton wstawiany przy kliknięciu
- Skeleton tylko na dynamicznych danych (liczby, daty, statusy) - statyczne elementy (nagłówki, etykiety) zostają
- Klasa `.skeleton-pulse` z animacją pulsowania (CSS `@keyframes`)
- Po załadowaniu: klasa `.loaded` chowa skeleton, pokazuje content

### 2. URL sync z aktywną zakładką

- Przełączenie zakładki → `history.replaceState` aktualizuje URL na `?tab=products`, `?tab=reports` itd.
- Przy wejściu → odczyt `?tab=` z URL → ta zakładka aktywna
- Domyślnie (brak parametru) → Dashboard
- Jeśli `?tab=products` → skeleton Produktów widoczny jako pierwszy, prefetch obu hot tabs nadal leci, ale Produkty priorytetowo

### 3. Usunięcie status bar + nowy auto-refresh

**Usunięte:**
- Cały `div.user-greeting` z `dashboard.html`
- Status synchronizacji, przycisk "Odśwież system", licznik auto-refresh
- Powiązany JS: `updateProductionStatusWidget()`, `handleRefreshSystem()`, `setupAutoRefresh()`, `setupAutoRefreshCountdown()`
- CSS: `.user-greeting`, `.production-status`, `.refresh-system-btn`, `.refresh-timer`, `.system-refresh-section`, `.status-indicator`, `.status-dot`

**Przeniesione:**
- Info o czasie ostatniej synchronizacji → istniejąca sekcja "Status systemu" w Dashboard, przy "Sync Baselinker"
- Kolorowanie daty synchronizacji:
  - Zielona (`.sync-fresh`): < 24h
  - Żółta (`.sync-warning`): 24-48h
  - Czerwona (`.sync-stale`): > 48h

**Nowy auto-refresh:**
- Timer żyje w `ProductionApp` (globalnie), nie w `DashboardModule`
- Interwał: 60s
- Przy każdym ticku: `refreshActiveTab()` na aktualnie widocznej zakładce
- Każdy moduł rejestruje swój `refresh()` handler w `ProductionApp`
- Przełączenie zakładki nie resetuje timera

**Przycisk refresh per tab:**
- W tej samej linii co taby, dociśnięty do prawej strony (flexbox `margin-left: auto`)
- Kliknięcie → skeleton na dynamicznych danych aktywnej zakładki → fetch nowych danych → podmiana
- Resetuje timer auto-refresh

### 4. Layout - usunięcie h1, kompaktowe taby

- Usunięty `<h1>` (tytuł strony)
- Taby + przycisk refresh w jednej linii (flexbox): taby po lewej, refresh po prawej
- Zakładki mają maksymalną dostępną wysokość viewportu
- Wygląd tabów dostosowany pod design systemu produkcyjnego (Dashboard + Lista produktów)

### 5. Rozbicie `api_routers.py` (327KB)

Nowa struktura:
```
routers/
├── __init__.py              # Blueprint rejestracja
├── main_routers.py          # /production/ (bez zmian)
├── admin_routers.py         # Admin endpoints (bez zmian)
├── station_routers.py       # Stanowiska tablet (bez zmian)
├── api/
│   ├── __init__.py          # Sub-blueprint, importy
│   ├── dashboard_api.py     # /api/dashboard-tab-content, /api/dashboard-stats
│   ├── products_api.py      # /api/products-tab-content, CRUD produktów
│   ├── reports_api.py       # /api/reports-tab-content, /api/chart-data
│   ├── stations_api.py      # /api/stations-tab-content
│   ├── config_api.py        # /api/config-tab-content
│   ├── sync_api.py          # /api/manual-sync, status synchronizacji
│   └── common_api.py        # /api/health, współdzielone endpointy
```

Zasada: każdy plik = jedna zakładka. `api_routers.py` znika.

## Pliki do modyfikacji

**Szablony:**
- `templates/panel/dashboard.html` - usunięcie h1, user-greeting, dodanie skeletonów, nowy layout tabów
- `templates/components/*-tab-content.html` - bez zmian strukturalnych

**JavaScript:**
- `static/js/production-app-loader.js` - prefetch, cache, URL sync, globalny auto-refresh, skeleton management
- `static/js/modules/dashboard-module.js` - usunięcie starego auto-refresh, rejestracja refresh handlera
- `static/js/modules/products-module.js` - rejestracja refresh handlera
- `static/js/shared-services.js` - ewentualne uproszczenia

**CSS:**
- `static/css/production-panel.css` - nowy layout tabów, usunięcie starych stylów, skeleton styles, sync date coloring, styl tabów dopasowany do design systemu

**Python:**
- `routers/api_routers.py` → rozbicie na `routers/api/*.py`
- `routers/__init__.py` - aktualizacja importów

## Czego NIE zmieniamy

- Backend logic (serwisy, modele)
- Zawartość poszczególnych zakładek (HTML wewnątrz)
- Endpointy API (URL-e zostają te same)
- `admin_routers.py`, `station_routers.py`, `main_routers.py`
- Logika poszczególnych modułów JS (DashboardModule internals poza auto-refresh)
