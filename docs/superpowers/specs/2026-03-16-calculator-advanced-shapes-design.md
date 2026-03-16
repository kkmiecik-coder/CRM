# Kalkulator — Tryb zaawansowany: Nieregularne kształty

**Data:** 2026-03-16
**Status:** Zatwierdzony

## Cel

Rozszerzenie kalkulatora o obsługę nieregularnych kształtów produktów (trapezy schodowe, trójkąty, wielokąty itp.), które obecnie nie mogą być wycenione w prostokątnym modelu kalkulatora.

## Przegląd

Obecny kalkulator obsługuje wyłącznie prostokąty i okręgi. Nowy system zastępuje radio toggle (prostokąt/okrągły) dropdownem z 12 kształtami, dodaje interaktywny canvas z edytowalnymi wierzchołkami i hierarchiczną siatką, oraz integruje się z istniejącym systemem wycen. Zaawansowane kształty dostępne są wyłącznie w kalkulatorze wewnętrznym — kalkulator publiczny (`/kalkulator`, `/kalkulatorb2b`) pozostaje bez zmian (tylko prostokąty).

---

## 1. Wybór kształtu

### Dropdown zastępuje radio toggle

Obecny toggle `shapeRect` / `shapeRound` zostaje zastąpiony elementem `<select>` w sekcji "Kształt" formularza produktu.

### Lista kształtów

| # | Kształt | Wartość `shape` | Podwariant |
|---|---------|-----------------|------------|
| 1 | Prostokąt | `rectangular` | — |
| 2 | Koło | `circle` | — |
| 3 | Elipsa | `ellipse` | — |
| 4 | Trójkąt prostokątny | `triangle_right` | Trójkąt |
| 5 | Trójkąt równoboczny | `triangle_equilateral` | Trójkąt |
| 6 | Trójkąt równoramienny | `triangle_isosceles` | Trójkąt |
| 7 | Trójkąt dowolny | `triangle_custom` | Trójkąt |
| 8 | Trapez symetryczny | `trapezoid_symmetric` | Trapez |
| 9 | Trapez niesymetryczny | `trapezoid_asymmetric` | Trapez |
| 10 | Trapez dowolny | `trapezoid_custom` | Trapez |
| 11 | Równoległobok | `parallelogram` | — |
| 12 | Wielokąt niestandardowy | `polygon` | — |

Wybrany kształt determinuje:
- Jakie inputy wymiarów się pokazują (lewa kolumna)
- Jaki kształt startowy pojawia się na canvasie (prawa kolumna)
- Jak obliczane jest realne pole powierzchni

---

## 2. Layout formularza produktu

### Dwie kolumny po wybraniu kształtu

```
┌─────────────────────────────────────────────────┐
│ Kształt: [Trapez symetryczny ▼]                 │
├──────────────────┬──────────────────────────────┤
│ INPUTY           │ CANVAS                       │
│                  │                              │
│ a: [120] cm      │  ┌──────────────────────┐   │
│ b: [80]  cm      │  │    ╱‾‾‾‾‾‾‾‾‾╲      │   │
│ h: [40]  cm      │  │   ╱     40     ╲     │   │
│ Grubość: [3] cm  │  │  ╱───────────────╲   │   │
│ Ilość: [12]      │  │  │      80       │   │   │
│                  │  │  ╰───────────────╯   │   │
│ Bbox: 120×40 cm  │  │       120            │   │
│                  │  │          ▣ 1kratka=1cm│   │
│                  │  └──────────────────────┘   │
│                  │  [↩] [↪] [⊡]                │
├──────────────────┴──────────────────────────────┤
│ Warianty drewna / Wykończenie (bez zmian)       │
└─────────────────────────────────────────────────┘
```

- **Lewa kolumna:** inputy zależne od kształtu + grubość + ilość + bounding box info
- **Prawa kolumna:** canvas z siatką, liniami wymiarowymi, edytowalnymi wierzchołkami
- **Pod canvasem:** undo, redo, dopasuj do widoku
- **Prostokąt:** canvas opcjonalny (zwinięty domyślnie)
- **Warianty drewna i wykończenie:** pod spodem, pełna szerokość, bez zmian

---

## 3. Inputy per kształt

Grubość i ilość są zawsze obecne dla każdego kształtu.

| Kształt | Inputy |
|---|---|
| Prostokąt | długość, szerokość |
| Koło | średnica |
| Elipsa | oś A, oś B (pełne wymiary osi, nie promienie) |
| Trójkąt prostokątny | przyprostokątna A, przyprostokątna B |
| Trójkąt równoboczny | bok |
| Trójkąt równoramienny | podstawa, ramię |
| Trójkąt dowolny | bok A, bok B, bok C |
| Trapez symetryczny | podstawa A (dłuższa), podstawa B (krótsza), wysokość |
| Trapez niesymetryczny | podstawa A (dłuższa), podstawa B (krótsza), wysokość, offset (przesunięcie krótszej podstawy w lewo od lewej krawędzi dłuższej, w cm; 0 = wyrównane do lewej) |
| Trapez dowolny | podstawa A (dłuższa), podstawa B (krótsza), wysokość, offset |
| Równoległobok | bok A, bok B, kąt (°) |
| Wielokąt niestandardowy | *(brak — tylko canvas + grubość)* |

### Walidacja inputów

Walidacja po stronie klienta, na bieżąco przy zmianie wartości:

- **Trójkąt dowolny:** Nierówność trójkąta — każdy bok < suma dwóch pozostałych. Przy naruszeniu: czerwony obrys inputu + komunikat "Nieprawidłowe wymiary trójkąta".
- **Trójkąt równoramienny:** Podstawa < 2 × ramię. Przy naruszeniu: komunikat "Podstawa zbyt długa".
- **Trapez:** Podstawa A ≥ podstawa B. Offset: 0 ≤ offset ≤ (A - B). Przy naruszeniu: komunikat błędu.
- **Równoległobok:** Kąt: 1° ≤ kąt ≤ 179°. Przy naruszeniu: komunikat.
- **Wielokąt:** Minimum 3 wierzchołki. Krawędzie nie mogą się przecinać (walidacja self-intersection). Przy naruszeniu: podświetlenie przecinających się krawędzi na czerwono.
- **Wszystkie kształty:** Wymiary > 0. Pole powierzchni > 0.

Przy błędzie walidacji: canvas pokazuje kształt w stanie błędu (czerwony obrys), wycena nie jest przeliczana.

### Synchronizacja canvas ↔ inputy

- Zmiana wartości w inpucie → canvas przerysowuje kształt
- Przeciągnięcie wierzchołka na canvasie → inputy aktualizują się na żywo
- Jeśli edycja na canvasie złamie geometrię wariantu (np. trapez symetryczny staje się niesymetryczny), dropdown automatycznie przełącza na wariant "dowolny" danego kształtu
- Auto-przełączenie działa jednokierunkowo: z konkretnego wariantu → dowolny. Odwrotne przełączenie (dowolny → konkretny) nie jest automatyczne — użytkownik musi ręcznie wybrać wariant z dropdown
- Tolerancja geometryczna przy wykrywaniu: ±0.5 cm (np. jeśli różnica symetrii trapezu < 0.5 cm, nadal uznawany za symetryczny)

---

## 4. Canvas — specyfikacja techniczna

### Technologia

HTML5 Canvas API (nie SVG — lepsza wydajność przy siatce i zoom).

### Siatka

- Hierarchiczna: co 10-ta linia jaśniejsza (główna), 9 wewnętrznych ciemniejszych (pomocnicze)
- Skalowalna: zoom zmienia gęstość siatki (1mm → 1cm → 10cm → 20cm → 30cm...)
- Wskaźnik skali w lewym dolnym rogu: "1 kratka = X"
- Tło neutralne, siatka subtelna

### Kształt na canvasie

- Wypełnienie półprzezroczyste
- Obrys wyraźny
- Wierzchołki jako uchwyty do przeciągania (powiększone przy hoverze)
- Linie wymiarowe przy krawędziach — automatyczne, wartości w cm
- **Koło/Elipsa:** renderowane jako krzywe parametryczne (nie wielokąt aproksymacyjny). Uchwyty edycji: punkt na obwodzie do zmiany promienia/osi. W `shape_data.vertices` przechowywane jako `null` — kształt odtwarzany z `params` (średnica / osie).

### Interakcje

| Akcja | Gest |
|---|---|
| Zoom | scroll / pinch |
| Pan (przesuwanie widoku) | przeciąganie tła |
| Edycja kształtu | przeciąganie wierzchołka |
| Dodaj punkt (wielokąt) | klik na krawędzi |
| Usuń punkt (wielokąt, min 3) | prawy klik na punkcie |
| Undo | przycisk [↩] |
| Redo | przycisk [↪] |
| Dopasuj do widoku | przycisk [⊡] — zoom + pan do pełnego kształtu z ~10% marginesem |

### Undo/Redo

- Każda zmiana wierzchołka (zakończenie przeciągania / zmiana inputu) = jeden krok w historii
- Maksymalna głębokość stosu: 50 kroków
- Zmiana typu kształtu (dropdown) czyści historię undo/redo
- Historia nie jest persystowana (reset przy przeładowaniu strony)

### Wartości startowe

- Każdy kształt startuje z sensownymi domyślnymi wymiarami (np. trapez: a=120, b=80, h=40)
- Wielokąt startuje jako pięciokąt foremny
- Canvas automatycznie dopasowuje widok do startowego kształtu (fit-to-view)

### Wielokąt — limity

- Maksymalna liczba wierzchołków: 20 (wystarczająca dla praktycznych kształtów, zapobiega problemom wydajnościowym)
- Przy próbie dodania 21. wierzchołka: komunikat "Maksymalna liczba punktów: 20"

---

## 5. Model wyceny

### Zasady obliczania

| Aspekt | Źródło wymiarów |
|---|---|
| Wycena drewna (cena/m³) | Bounding box × grubość |
| Wykończenie (cena/m²) | Realne pole powierzchni kształtu |
| Objętość wyświetlana | Realne pole × grubość |
| Wycena wysyłki | Realna objętość |
| Waga (kg) | Realna objętość × 800 kg/m³ |
| Krawędzie (cena/mb) | Rzeczywiste boki kształtu |

### Dopłata za kształt

Obecnie dopłata istnieje tylko dla kształtu okrągłego (`round_surcharge_netto`). Nowe kształty (trójkąt, trapez, równoległobok, wielokąt) **nie mają dopłaty** w tej wersji. Model dopłat będzie rozszerzony w przyszłości na podstawie instrukcji obliczania od biznesu.

### Wzory pola powierzchni

Inputy definiują pełne wymiary (nie promienie/półosie).

| Kształt | Wzór |
|---|---|
| Prostokąt | a × b |
| Koło | π × (d/2)² |
| Elipsa | π × (a/2) × (b/2) |
| Trójkąt | Wzór Herona lub ½ × podstawa × h |
| Trapez | ½ × (a + b) × h |
| Równoległobok | a × b × sin(kąt) |
| Wielokąt | Algorytm Shoelace (suma wierzchołków) |

### Bounding box

Obliczany automatycznie jako prostokąt okalający (min/max X i Y wierzchołków). Używany do:
- Lookup ceny z tabeli `Price` (length_min/max, width_min/max)
- Obliczenia ceny drewna
- Dla koła: bbox = d × d
- Dla elipsy: bbox = a × b

---

## 6. Krawędzie (edges) dla nieregularnych kształtów

### Nowy model dynamicznych krawędzi

Obecny system 12 stałych krawędzi (A-H + N1-N4) dotyczy wyłącznie prostokątów i pozostaje bez zmian dla nich.

Dla nieregularnych kształtów krawędzie są generowane dynamicznie na podstawie geometrii:

### Typy krawędzi

Każdy produkt 3D ma trzy rodzaje krawędzi:
- **Górne (G)** — krawędzie konturu górnej powierzchni (patrząc z góry)
- **Dolne (D)** — krawędzie konturu dolnej powierzchni (identyczny kontur jak góra)
- **Pionowe (P)** — boki łączące górę z dołem (wysokość = grubość materiału)

### Numeracja

Krawędzie numerowane sekwencyjnie po bokach kształtu:
- Trójkąt: G1, G2, G3 (góra) + D1, D2, D3 (dół) + P1, P2, P3 (pion)
- Trapez: G1-G4, D1-D4, P1-P4
- Wielokąt N-kątny: G1-GN, D1-DN, P1-PN

### Wybór wykończenia

- Każda krawędź ma indywidualny wybór wykończenia (typ: ostre / fazowanie / zaokrąglenie)
- Brak grupowania — użytkownik wybiera per krawędź
- Krawędzie wizualizowane na canvasie z oznaczeniem numeru (G1, P2 itp.)

### Obliczanie cen krawędzi

- Długość krawędzi górnych/dolnych: z rzeczywistych boków kształtu (z `vertices`)
- Długość krawędzi pionowych: grubość materiału
- Cena: `długość_mm × cena_per_mb / 1000` (jak obecny model)
- Narożniki: cena narożnika per wierzchołek (jak obecny `corner_price`)

### Koło/Elipsa — krawędzie

- Góra/dół: jedna krawędź G1/D1 = obwód (koło: π×d, elipsa: przybliżenie Ramanujana)
- Pion: jedna krawędź P1 = obwód × grubość (cała krawędź boczna jako jeden ciągły pas)
- Brak narożników

---

## 7. Model danych

### Migracja kolumny `shape`

Obecna kolumna `shape` to `String(20)`. Wartość `triangle_equilateral` ma 21 znaków. **Wymagana migracja do `String(50)`** przed wdrożeniem nowych kształtów.

### Zmiany w `QuoteItemDetails`

**Rozszerzenie istniejącego pola:**
- `shape` (`String(50)`) — z dotychczasowych `rectangular`/`round` na pełną listę: `rectangular`, `circle`, `ellipse`, `triangle_right`, `triangle_equilateral`, `triangle_isosceles`, `triangle_custom`, `trapezoid_symmetric`, `trapezoid_asymmetric`, `trapezoid_custom`, `parallelogram`, `polygon`

**Nowe pola:**
- `shape_data` (`TEXT`) — pełna definicja kształtu jako JSON:
```json
{
  "params": {"a": 120, "b": 80, "h": 40},
  "vertices": [[0,0], [20,40], [100,40], [120,0]],
  "real_area_cm2": 4000,
  "bbox": {"width": 120, "height": 40}
}
```
  - `params` — wartości z inputów (do odtworzenia formularza i inputów)
  - `vertices` — współrzędne wierzchołków w cm (do odtworzenia canvasu). `null` dla koła/elipsy.
  - `real_area_cm2` — obliczone realne pole powierzchni
  - `bbox` — wymiary bounding boxa (width, height w cm)

- `shape_svg` (`TEXT`) — wyrenderowany SVG kształtu do wyświetlania w listach wycen i PDF. Generowany po stronie klienta (JS) w momencie zapisu wyceny — analogicznie do istniejącego `edges_svg`. Zawiera obrys kształtu z wypełnieniem, bez siatki i linii wymiarowych. ViewBox dopasowany do bounding boxa.

### Zmiany w `QuoteItemDetails` — krawędzie

Istniejące pole `edges_config` (JSON) rozszerzone o dane krawędzi nieregularnych kształtów:
```json
{
  "edges": [
    {"id": "G1", "type": "top", "length_mm": 1200, "finish": "chamfer"},
    {"id": "G2", "type": "top", "length_mm": 412, "finish": "round"},
    {"id": "P1", "type": "vertical", "length_mm": 30, "finish": "sharp"},
    {"id": "D1", "type": "bottom", "length_mm": 1200, "finish": "sharp"}
  ]
}
```

Dla prostokątów — obecny format `edges_config` pozostaje bez zmian.

### Pola bez zmian

- `QuoteItem.length_cm` / `width_cm` — wypełniane z bounding boxa (kompatybilność wsteczna, lookup cen)
- `QuoteItem.volume_m3` — realna objętość (pole realne × grubość)
- `QuoteItem.price_per_m3`, `multiplier` — bez zmian
- `QuoteItemDetails.edges_svg` — bez zmian (SVG konfiguracji krawędzi, osobne od `shape_svg`)
- Model `Price` — bez zmian (lookup po wymiarach bbox)

### Kompatybilność wsteczna

Istniejące wyceny z `shape=rectangular`/`round` i `shape_data=NULL`, `shape_svg=NULL` działają bez zmian. Logika wykrywania starego formatu: jeśli `shape_data` jest NULL, system traktuje produkt jako prostokąt/okrągły w dotychczasowy sposób.

---

## 8. Integracja z istniejącym systemem

### Zapis wyceny (quote_service.py)

- `create_quote()` / `update_quote()` — rozszerzenie o zapis `shape_data`, `shape_svg` i rozszerzony `edges_config` z danych frontendowych
- Obliczanie `QuoteItem.length_cm`/`width_cm` z bbox zamiast bezpośrednio z inputów
- `QuoteItem.volume_m3` — obliczany z realnego pola (nie bbox)

### Ładowanie do edycji (quote_edit_loader.js)

- `restoreShape()` — rozszerzenie: odczyt `shape` (typ kształtu) + `shape_data` (parametry i wierzchołki) → odtworzenie dropdown, inputów i canvasu
- Dla starych wycen (`shape_data=NULL`): zachowanie dotychczasowe

### Wyświetlanie w listach wycen (quotes.js)

- Badge kształtu rozszerzony z "Okrągły" na nazwę wybranego kształtu (np. "Trapez symetryczny")
- Mini-podgląd `shape_svg` przy produkcie (jeśli dostępny)

### PDF (offer_pdf.html)

- Wyświetlanie nazwy kształtu
- `shape_svg` jako wizualizacja w PDF obok danych produktu

### Drafty (CalculatorDraft)

- `draft_data` (JSON) rozszerzony o dane kształtu: typ, parametry, wierzchołki, stan canvasu
- Przy odtwarzaniu draftu: pełna rekonstrukcja formularza + canvasu
- Undo/redo history nie jest zapisywana w drafcie

### Kalkulator publiczny

Bez zmian. Zaawansowane kształty dostępne wyłącznie w kalkulatorze wewnętrznym. Publiczny kalkulator (`/kalkulator`, `/kalkulatorb2b`) nadal obsługuje tylko prostokąty.
