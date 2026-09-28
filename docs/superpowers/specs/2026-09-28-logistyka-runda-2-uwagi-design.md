# Logistyka równoległa — runda 2: uwagi Konrada po testach (projekt)

- **Data:** 2026-09-28
- **Status:** projekt zatwierdzony w rozmowie 28.09 („Tak”), do przeglądu spisanej wersji
- **Podstawa:** spec `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md` (etapy 1–3) i przekazanie
  `docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md`. Gałąź `claude/logistyka-etap-3-trasy` (jedyna
  gałąź logistyki), podgląd 127.0.0.1:5003 (kopia produkcji z 28.09).
- **Repo jest publiczne** — bez sekretów i uwag bezpieczeństwa.

## 1. Cel

Poprawki po testach Konrada na kopii produkcji: logistyka ma przestać udawać stanowisko w pipeline'ie produkcji,
praca na mapie i liście ma wymagać mniej klikania, a kierowcy tras mają być wyróżnioną grupą pracowników, a nie
wszystkimi pracownikami hali.

**Sukces:** każda z 7 uwag zamknięta i obejrzana w przeglądarce na 5003; pełny pakiet testów zielony; adwersaryjny
przegląd całej gałęzi (odłożony z rundy 4.1) bez otwartych krytycznych/ważnych.

## 2. Zakres (7 punktów)

### 2.1. Dashboard produkcji — logistyka poza pipeline'em
- Dziś: w karcie stanowisk jest kafelek-bramka `il-station--gate` `data-station="logistics"` z licznikiem
  „N bez sposobu dostawy” (`modules/production/templates/components/dashboard-tab-content.html`), a szyna SVG
  (`modules/production/static/js/modules/dashboard-module.js`, lista `kody`) ma węzeł `logistics` między lakiernią
  a pakowaniem (z twardo wpisanym kolorem).
- Zmiana: kafelek i węzeł znikają z pipeline'u (szyna: cięcie … lakiernia → pakowanie). **Pod pipeline'em, w tej samej
  karcie**, pasek: ikona, „Logistyka: **N** bez sposobu dostawy”, przycisk „Otwórz Logistykę” (ten sam link co dziś
  do zakładki Logistyka). Liczba ta sama co dziś (`lista_logistyki.liczba_bez_sposobu()` w `dashboard_api.py`),
  element z liczbą zachowuje identyfikator, który aktualizuje odświeżanie dashboardu. N = 0 → pasek zostaje,
  wyciszony, z tekstem „wszystkie zamówienia mają sposób dostawy”.
- Backend bez zmian.

### 2.2. Dymek pinezki — wybór sposobu dostawy
- Dziś dymek (`dymekHtml` w `logistics-map.js`) ma tylko „Popraw lokalizację” (i warunkowo „Potwierdź punkt”,
  „Przywróć automat”).
- Zmiana: w dymku ten sam wybór sposobu dostawy co w wierszu listy (`selectSposobu` w `logistics.js`: Nie ustawiono,
  Kurier, Transport własny, Odbiór osobisty), z bieżącą wartością zamówienia.
- Wysyłka tą samą drogą co z listy (`POST /production/api/logistics/orders/delivery-method` przez funkcję listy —
  mapa przekazuje wybór do `logistics.js` przez istniejący most `window.LogisticsMap` ↔ lista, nowy punkt zaczepienia
  w rodzaju `onSposob(cb)`); **bez nowego endpointu**. Te same blokady i komunikaty co z listy (np. spakowane nie cofnie
  się do „Nie ustawiono”, zamówienie z trasy zatwierdzonej → 409 z komunikatem). Po odpowiedzi wiersz, liczniki
  i kolor pinezki odświeżają się istniejącą ścieżką (`podmienWiersze` → `przekazDoMapy`).
- W trakcie wysyłki wybór w dymku nieaktywny; błąd → komunikat jak z listy, wybór wraca do poprzedniej wartości.

### 2.3. Lista — odstęp pola wyboru od krawędzi
- Dziś `.lg-k-zaznacz` ma `padding-left: 6px`, tabela `padding: 6–8px`.
- Zmiana: pierwsza kolumna ok. 14 px z lewej, ostatnia kolumna tyle samo z prawej; w progach RWD proporcjonalnie
  mniej (dziś 7 px i 5 px). Tylko CSS (`logistics.css`).

### 2.4. Filtry zamówień przełączają mapę na „Zamówienia”
- Gdy mapa jest w widoku „Trasy”, zmiana filtra zamówień — liczniki sposobu (`.lg-liczniki`), „Transport bez trasy”,
  etap, lokalizacja (geo), województwa — przełącza mapę na „Zamówienia”
  (`window.LogisticsMap.ustawWidok('zamowienia')`, jak robi to dziś `logistics-routes.js`).
- **Wyszukiwarka nie przełącza** (samo pisanie nie przestawia mapy).
- Zdjęcie filtra (drugi klik w licznik) też nie przełącza z powrotem na „Trasy”.

### 2.5. Filtr województw (wybór kilku naraz)
- UI: w pasku filtrów listy przycisk „Województwa” (z liczbą wybranych, np. „Województwa (2)”), otwierający panel
  z polami wyboru: 16 województw (nazwy kanoniczne z `PostcodeToStateMapper.STATE_NORMALIZATION`), „Zagranica”,
  „Bez województwa”; przycisk „Wyczyść”. Zamknięcie Esc / klik obok. Działa jak pozostałe filtry: na listę i na mapę,
  bez zapamiętywania w przeglądarce.
- Znaczenie: województwo liczone z **kodu pocztowego** tymi samymi zakresami co kolumna „Region” w eksporcie Routimo
  (`modules/reports/utils.py`, `PostcodeToStateMapper.POSTCODE_RANGES` — jedno źródło prawdy; zakresy po dwóch
  pierwszych cyfrach kodu). „Zagranica” = kraj dostawy inny niż PL; „Bez województwa” = PL (albo pusty kraj) z pustym,
  nieczytelnym kodem albo z prefiksem, którego mapa nie zna.
- Backend: parametr listy `woj` (wielokrotny: `?woj=podkarpackie&woj=malopolskie`, wartości = identyfikatory bez
  polskich znaków + `zagranica`, `bez_wojewodztwa`) w `GET /production/api/logistics/orders` → `lista.pobierz(...)`.
  Filtr **w SQL**, po dwóch pierwszych cyfrach kodu (po usunięciu myślnika/spacji), przed `order_by/limit` (reguła R3
  z docstringu `lista.pobierz`); działa na SQLite (testy) i MySQL. Nieznany identyfikator → 422 (jak inne złe
  parametry listy). Brak kolumny ani migracji.
- **Znane ograniczenie mapy kodów** (jest też w Region w Routimo i w Analizie sprzedażowej): prefiksy 24, 69, 88, 89
  nie mają województwa (trafią do „Bez województwa”), a niektóre prefiksy obejmują dwa województwa (np. 27, 96) —
  mapa przypisuje je jednemu. Podpowiedź przy filtrze: „wg kodu pocztowego, w przybliżeniu”. Poprawa mapy kodów —
  **poza zakresem, decyzja Konrada** (zmieniłaby też Analizę sprzedażową i Region w Routimo).

### 2.6. Flota — kierowcy jako wyróżnieni pracownicy
- Dane: nowa kolumna `prod_workers.is_driver` (BOOL NOT NULL DEFAULT 0), migracja
  `migrations/2026-09-28-logistyka-kierowcy.sql` — idempotentna, bez `DELIMITER`, wzorem istniejących migracji
  z osłoniętym `ALTER`. Na start nikt nie jest kierowcą (logistyk dodaje).
- Serwis (`modules/production/logistics/services/fleet.py`) i API (`routers/trasy_api.py`):
  - `GET /drivers` — **tylko aktywni pracownicy z `is_driver`** (dziś: wszyscy aktywni);
  - lista kandydatów do dodania — aktywni pracownicy bez `is_driver`;
  - dodanie kierowcy (`worker_id`) i zdjęcie znacznika (pracownik zostaje w systemie). Idempotentne; nieistniejący albo
    nieaktywny pracownik przy dodaniu → 404/409 z komunikatem po polsku; złe ciało → 422.
- Trasy (`services/routes.py`, `_sprawdz_zasoby`, `dostepnosc/zajetosc`): wybór kierowcy tylko spośród kierowców
  (z „(zajęty)” jak dziś). Zapis trasy z **nowym albo zmienionym** kierowcą bez znacznika → 409 z komunikatem.
  Kierowca **już przypisany** do trasy zostaje po zdjęciu znacznika (reguła jak dla wyłączonego pojazdu — spec 8.1,
  rozstrzygnięcie 33): edycja i przywrócenie trasy go nie odrzucają, a w wyborze tej trasy widać go z dopiskiem
  „(nie jest już kierowcą)”.
- UI Floty (`logistics-fleet.js`, prawy panel): nagłówek „Kierowcy”, nad listą przycisk „Dodaj kierowcę” (okno
  `<dialog class="lg-dialog">` z wyszukiwaną listą kandydatów), w wierszu kierowcy czerwona ikona kosza (potwierdzenie;
  gdy kierowca jest na trasie roboczej/zatwierdzonej, potwierdzenie podaje nazwy tras i mówi, że na nich zostanie).
  Pusta lista → podpowiedź „Dodaj kierowców spośród pracowników”.
- Zakładka Pracownicy bez zmian (znacznik ustawia się tylko we Flocie).

### 2.7. Mapka podglądu trasy — kółko przybliża od razu
- Dziś `zapewnijMapke()` w `logistics-routes.js` ustawia `scrollWheelZoom: false` i włącza je dopiero po kliknięciu
  w mapkę (wyłącza po wyjściu kursora).
- Zmiana: `scrollWheelZoom` włączone od razu, bez aktywacji kliknięciem — tak jak mapa Dashboardu. Świadomy koszt:
  przewijając stronę edytora z kursorem nad mapką, przybliża się mapka zamiast strony.

## 3. Poza zakresem
- Poprawa mapy kodów pocztowych na województwa (2.5).
- Zarządzanie znacznikiem kierowcy w zakładce Pracownicy; kierowca na tablecie; stanowisko kierowcy.
- Zapamiętywanie filtrów w przeglądarce.
- Drobiazgi odłożone w przekazaniu (4.3) — chyba że przegląd całej gałęzi uzna któryś za konieczny przed merge.

## 4. Zasady i ograniczenia (jak w etapie 3)
- Komentarze w kodzie po polsku; w UI „Base.”, nie „BaseLinker”; teksty z poprawną odmianą.
- Interfejs ze skillem `frontend-design:frontend-design`, w stylu zakładki (klasy `lg-*`, okna `<dialog class="lg-dialog">`,
  komunikaty mechanizmem `pokazKomunikat` / `window.LogisticsTab.komunikat`), `?v=` podbijane przy każdej zmianie
  pliku statycznego; większy nowy kod JS w nowym pliku (`logistics.js` ~2100, `logistics-map.js` ~1800,
  `logistics-routes.js` ~3800 linii) — w starych tylko punkty zaczepienia.
- Blokady tras: piszący trasy biorą najpierw `routes.zablokuj_trasy()`; zmiana znacznika kierowcy nie jest zapisem
  trasy (bez blokady), ale walidacja kierowcy przy zapisie trasy czyta stan pod blokadą jak dziś.
- Gunicorn: sync, 30 s — żadnych wywołań zewnętrznych w nowych żądaniach.
- Migracja idempotentna, nazwa `2026-09-28-…`, wykonuje się przy starcie i w `deploy.sh` (`flask migrate`).
- Testy: pytest (SQLite) z katalogu worktree przez `docker compose -p logistyka3 run --rm --no-deps app pytest …`;
  UI — testy tekstu źródła (`tests/test_logistyka_trasy_ui.py` i pokrewne) + oględziny kontrolera we wbudowanej
  przeglądarce na 5003 (karta w tle nie ma klatek animacji — pomiar zdarzeń, nie sam efekt).

## 5. Testy
- Migracja: kolumna `is_driver` istnieje i ma domyślnie 0 (wzór: `tests/test_logistyka_trasy_schemat.py`).
- Kierowcy: `GET /drivers` tylko ze znacznikiem i aktywni; kandydaci bez kierowców i nieaktywnych; dodanie/zdjęcie
  (idempotencja, 404/409/422, uprawnienia 401/403 jak reszta panelu); zapis trasy z nowym kierowcą bez znacznika → 409;
  zostawiony kierowca po zdjęciu znacznika nie blokuje edycji i przywrócenia; dostępność pokazuje go tylko w jego trasie.
- Województwa: `lista.pobierz` / `GET /orders?woj=…` — granice zakresów (np. 34/35, 59/60), kod z myślnikiem i bez,
  kod ze spacją, kilka województw naraz, `zagranica`, `bez_wojewodztwa` (pusty kod, śmieci, prefiks 24),
  zła wartość → 422; filtr razem z innymi filtrami i limitem (R3).
- UI (tekst źródła): pasek logistyki poza pipeline'em i brak `logistics` w liście szyny; select w dymku i przekazanie
  do funkcji listy; przełączenie widoku mapy przy filtrach i brak przy wyszukiwarce; panel województw; panel kierowców
  (dodaj, kosz); `scrollWheelZoom: true` w mapce; podbite `?v=`.
- Oględziny na 5003: każdy z 7 punktów.

## 6. Wdrożenie
Jak etapy 1–3 (lista w przekazaniu, sekcja 6) + migracja `2026-09-28-logistyka-kierowcy.sql` (wykona się sama).
Po wdrożeniu logistyk dodaje kierowców we Flocie przed układaniem tras z kierowcą.
