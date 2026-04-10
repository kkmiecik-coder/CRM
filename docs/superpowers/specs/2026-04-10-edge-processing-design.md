# Strukturalna obróbka krawędzi — specyfikacja

## Kontekst

Obecny stan: `parsed_edge_processing` (Boolean) w `ProductionItem` — wykrywa obecność obróbki krawędzi, ale nie przechowuje szczegółów (typ, promień, kąt, które krawędzie). `_extract_edge_description()` w `interfaces.py` parsuje szczegóły ad-hoc przy renderowaniu — nie zapisuje w DB.

Kalkulator (`modules/calculator`) ma pełny system krawędzi: 12 krawędzi prostokąta (A-H + N1-N4), dynamiczne wielokąty (G1-GN, D1-DN, P1-PN), SVG izometryczny 3D, typy obróbki (zaokrąglenie/fazowanie), promienie R, kąty. Dane zapisywane w `QuoteItemDetails` jako `edges_config` (JSON), `edges_svg`, `edges_type`, `edges_r_value`, `edges_angle_value`.

Cel: dodanie strukturalnych danych o obróbce krawędzi do modułu produkcji — analogicznie do systemu wykończeń (`parsed_finish_*`). Parsowanie z nazwy + powiązanie z danymi kalkulatora + wizualizacja SVG na stanowiskach.

## Źródła zamówień

- **Sklep** — tylko prostokąty, krawędzie `A-H, N1-N4`, nie przechodzi przez kalkulator CRM
- **CRM kalkulator** — prostokąty + wielokąty (trójkąt, trapez, polygon), krawędzie `A-H, N1-N4` lub `G1-GN, D1-DN, P1-PN`, pełne dane w `QuoteItemDetails`

Oba źródła trafiają do BaseLinkera, skąd są importowane do modułu produkcji.

---

## 1. Model danych

### Nowe pola w `ProductionItem` (`modules/production/models.py`)

```python
parsed_edge_type       = Column(String(20), nullable=True,
                                comment='Typ obróbki: zaokrąglenie / fazowanie')
parsed_edge_radius     = Column(Integer, nullable=True,
                                comment='Wartość promienia R (np. 3, 6, 30)')
parsed_edge_angle      = Column(Integer, nullable=True,
                                comment='Kąt fazowania w stopniach (30, 45, 60) — NULL dla zaokrąglenia')
parsed_edge_letters    = Column(JSON, nullable=True,
                                comment='Lista krawędzi: ["A","B","N1"] lub ["G1","G2","P1"]')
edge_svg               = Column(Text, nullable=True,
                                comment='SVG izometryczny 3D z zaznaczonymi krawędziami')
shape_svg              = Column(Text, nullable=True,
                                comment='SVG kształtu 2D (z QuoteItemDetails lub generowany)')
quote_item_detail_id   = Column(Integer, nullable=True,
                                comment='FK do QuoteItemDetails — NULL dla zamówień sklepowych')
```

Dotychczasowe `parsed_edge_processing` (Boolean) **zostaje** — zachowuje kompatybilność z `skip_finishing_station()`.

### Nowe pole w `QuoteItemDetails` (`modules/calculator/models.py`)

```python
baselinker_order_product_id = Column(Integer, nullable=True,
                                     comment='ID produktu z BaseLinker getOrders — do matchowania z ProductionItem')
```

---

## 2. Kaskada pozyskiwania danych

Trzy poziomy, w kolejności priorytetu. Parser odpala się **tylko gdy nazwa zawiera słowa kluczowe obróbki krawędzi**.

### Flow importu do produkcji

```
1. Parser nazwy → czy ma obróbkę krawędzi?
   │
   ├─ NIE → parsed_edge_processing = False, koniec
   │        (brak badge'a, brak ikony, brak modala)
   │
   └─ TAK → parsed_edge_processing = True
            → parsuj typ/R/kąt/krawędzie z nazwy (zawsze, jako baseline)
            │
            → Czy zamówienie ma link do PDF specyfikacji?
              ├─ TAK → pobierz PDF z URL BaseLinkera (requests.get → BytesIO)
              │        → odczytaj /WoodPowerMeta z metadanych PDF (pypdf)
              │        → znajdź QuoteItemDetails po detail_id
              │        → kopiuj: edges_config→parsed_edge_letters, edges_type→parsed_edge_type,
              │          edges_r_value→parsed_edge_radius, edges_angle_value→parsed_edge_angle,
              │          edges_svg, shape_svg
              │        → zapisz quote_item_detail_id
              │        → PDF NIE jest zapisywany na dysk (BytesIO, odczyt w pamięci)
              │
              └─ NIE → Czy istnieje QuoteItemDetails z tym baselinker_order_id + order_product_id?
                       ├─ TAK → kopiuj dane jak wyżej
                       │
                       └─ NIE → zostań przy danych z parsera
                                → generuj SVG prostokąta server-side (EdgeSvgGenerator)
```

### Przy składaniu zamówienia w BaseLinkerze (`baselinker/service.py`)

**Krok 1 — Metadane w PDF:**
W `edges_pdf_generator.py` po wygenerowaniu PDF przez WeasyPrint → post-process z `pypdf` do osadzenia metadanych:

```python
# Custom metadata PDF:
/WoodPowerMeta: {"quote_id": 123, "items": [
  {"position": 1, "detail_id": 789, "sku": "BLADEBLIT350100..."},
  {"position": 2, "detail_id": 790, "sku": "BLADEBLIT250080..."}
]}
```

**Krok 2 — Zapis `order_product_id`:**
Po udanym `addOrder`:
1. Odpytaj `getOrders(order_id)` → tablica `products[]` z `order_product_id` + `sku`
2. Matchuj po SKU: `products[].sku` ↔ `QuoteItemDetails` (generowane tym samym `_generate_sku()`)
3. Zapisz `order_product_id` w `QuoteItemDetails.baselinker_order_product_id`

---

## 3. Parser nazwy (fallback — zamówienia sklepowe / stare)

Rozbudowa `_parse_edge_processing()` w `parser_service.py` — zamiast `bool` zwraca dict.

### Wzorce do parsowania

```
zaokrąglenie R3 (A)                           → type=zaokrąglenie, R=3, angle=null, letters=[A]
zaokrąglenie R30 (N4, N2, N1, N3)             → type=zaokrąglenie, R=30, angle=null, letters=[N4,N2,N1,N3]
zaokrąglenie R3 (G1, G2, G3, D1, D2, D3)     → type=zaokrąglenie, R=3, angle=null, letters=[G1,G2,G3,D1,D2,D3]
fazowanie R3 45° E, F, G, H                   → type=fazowanie, R=3, angle=45, letters=[E,F,G,H]
zaokrąglenie R3 E, F, G, H                    → type=zaokrąglenie, R=3, angle=null, letters=[E,F,G,H]
fazowanie R6 60° N1, N2, N3, N4               → type=fazowanie, R=6, angle=60, letters=[N1,N2,N3,N4]
zaokrąglenie R3 (B, C, A, D)                  → type=zaokrąglenie, R=3, angle=null, letters=[B,C,A,D]
```

### Sygnatura

```python
def _parse_edge_processing(self, name: str) -> dict:
    """
    Parsuje obróbkę krawędzi z nazwy produktu.

    Returns:
        dict: {
            'has_edge': bool,
            'edge_type': str|None,      # 'zaokrąglenie' / 'fazowanie'
            'edge_radius': int|None,     # wartość R
            'edge_angle': int|None,      # kąt (tylko fazowanie)
            'edge_letters': list|None    # ['A','B','N1'] lub ['G1','D2','P3']
        }
    """
```

### Strategia regex

Jeden główny wzorzec z nazwanymi grupami:
```
(zaokrąglenie|fazowanie)\s+R(\d+)\s*(?:(\d+)°)?\s*[\(]?((?:[A-H]|[GDPN]\d+)(?:\s*,\s*(?:[A-H]|[GDPN]\d+))*)[\)]?
```

Kroki:
1. Wykryj typ: `zaokrąglenie` lub `fazowanie` (case-insensitive)
2. Wykryj promień: `R` + cyfry
3. Opcjonalnie kąt: cyfry + `°` (tylko fazowanie)
4. Wykryj krawędzie: litery/kody w nawiasach lub po przecinkach

`parsed_edge_processing` (bool) ustawiany na `True` jeśli `has_edge == True` — kompatybilność wsteczna z `skip_finishing_station()`.

---

## 4. Generator SVG prostokąta (server-side)

Nowa klasa `EdgeSvgGenerator` w `modules/production/services/edge_svg_generator.py`.

Python port logiki z `edges.js:generateRectPreviewSVG()`:
- Izometryczny prostopadłościan (te same wektory projekcji co w JS)
- Krawędzie z `edge_letters` → pomarańczowe (`#f59e0b`, grubsza linia, stroke-width 3)
- Reszta krawędzi → szare (`#475569`, stroke-width 1.5)
- Labelki z literami (kółko + tekst) — pomarańczowe dla aktywnych, szare dla nieaktywnych
- Ściany jako półprzezroczyste polygony
- Przyjmuje: wymiary (L×W×T), lista aktywnych krawędzi
- Zwraca: string SVG

Używany **tylko** gdy brak danych z `QuoteItemDetails` (zamówienia sklepowe / stare). Obsługuje wyłącznie prostokąty — wielokąty dostają SVG z kalkulatora.

---

## 5. UI na stanowiskach produkcji

### Badge w `.product-params`

Nowy badge obok gatunku, technologii i klasy drewna:
- Kolor: pomarańczowy (`#f59e0b`), border `rgba(245,158,11,0.3)`
- Format tekstu:
  - Zaokrąglenie: `Zaokrąglenie R3`
  - Fazowanie: `Fazowanie R3 45°`
- Czysty tekst, bez ikon/symboli na początku
- Widoczny **tylko** gdy `parsed_edge_processing == True`
- CSS klasa: `.badge-edge`

### Ikona w `.order-icons`

- Ikona: prostopadłościan z perspektywy narożnej (SVG inline)
- Kolor: żółty/pomarańczowy (`#f59e0b`)
- Background: `rgba(245,158,11,0.1)`
- Min rozmiar: 48×48px (touch target)
- Widoczna **tylko** gdy `parsed_edge_processing == True`
- Po kliknięciu → otwiera modal
- CSS klasa: `.edge-icon-wrapper`

### Modal obróbki krawędzi

Styl analogiczny do istniejących modali (attachment, notes). Zawiera:

**Nagłówek:** "Obróbka krawędzi — #[ID]" + przycisk zamknięcia

**Dwie kolumny wizualizacji:**
- Lewa: **Kształt 2D** (`shape_svg`) z wymiarami
- Prawa: **Izometria 3D** (`edge_svg`) z zaznaczonymi krawędziami na pomarańczowo

**Sekcja informacji (pod wizualizacjami):**
- Typ obróbki (pomarańczowy tekst)
- Promień R
- Kąt (tylko fazowanie)
- Lista krawędzi

Dark theme, zero animacji, min 48px touch targets na przyciskach.

---

## 6. Pliki do modyfikacji

### Nowe pliki
- `modules/production/services/edge_svg_generator.py` — generator SVG prostokąta server-side

### Modyfikowane pliki
- `modules/production/models.py` — nowe pola w ProductionItem
- `modules/production/services/parser_service.py` — rozbudowa `_parse_edge_processing()`
- `modules/production/services/sync_service.py` — kaskada pozyskiwania danych przy imporcie
- `modules/production/routers/stations/interfaces.py` — nowe dane do frontendu, usunięcie `_extract_edge_description()`
- `modules/production/templates/stations/cutting.html` (i inne stanowiska) — badge + ikona + modal HTML
- `modules/production/static/css/stations/station-shared.css` — style badge'a, ikony, modala
- `modules/production/static/js/stations/station-attachments.js` (lub nowy plik) — obsługa modala krawędzi
- `modules/production/static/js/modules/products-module.js` — aktualizacja wyświetlania danych krawędzi
- `modules/calculator/models.py` — nowe pole `baselinker_order_product_id` w QuoteItemDetails
- `modules/baselinker/service.py` — zapis `order_product_id` po `addOrder`
- `modules/baselinker/edges_pdf_generator.py` — osadzanie metadanych JSON w PDF
- `migrations/` — nowa migracja SQL

### Nowe zależności
- `pypdf` — odczyt/zapis metadanych PDF (dodać do `requirements.txt`)

---

## 7. Scope

### W scope
1. Model danych — nowe pola w ProductionItem + QuoteItemDetails
2. Migracja DB — lokalna, SQL na live po testach
3. Parser nazwy — rozbudowa na dict
4. Metadane PDF — osadzenie JSON w specyfikacji
5. Zapis `order_product_id` — po `addOrder` → `getOrders` → matchowanie po SKU
6. Import do produkcji — kaskada PDF → order_product_id → parser (PDF w pamięci, bez zapisu na dysk)
7. Generator SVG — izometryczny prostokąt server-side
8. UI stanowisk — badge + ikona + modal
9. Interfejsy — aktualizacja danych do frontendu

### Poza scope
- Modyfikacja kalkulatora / sklepu
- Edycja danych obróbki krawędzi na stanowiskach (read-only)
- Obsługa kształtów okrągłych/eliptycznych w generatorze SVG (tylko prostokąt — reszta z QuoteItemDetails)
- Migracja historycznych zamówień (dotyczy tylko nowych od momentu wdrożenia)
