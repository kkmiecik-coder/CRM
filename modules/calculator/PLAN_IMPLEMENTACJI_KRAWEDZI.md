# Plan Implementacji Funkcjonalności Obróbki Krawędzi

## Spis treści
1. [Przegląd](#1-przegląd)
2. [Architektura](#2-architektura)
3. [Baza danych](#3-baza-danych)
4. [Backend (Python/Flask)](#4-backend-pythonflask)
5. [Frontend (HTML/CSS/JS)](#5-frontend-htmlcssjs)
6. [Integracja z istniejącym systemem](#6-integracja-z-istniejącym-systemem)
7. [Harmonogram implementacji](#7-harmonogram-implementacji)

---

## 1. Przegląd

### 1.1 Cel
Dodanie funkcjonalności obróbki krawędzi do modułu kalkulatora, wzorowanej na module PrestaShop `woodconfigurator`.

### 1.2 Funkcjonalności
- Wybór krawędzi do obróbki (8 poziomych + 4 narożniki)
- Wybór typu obróbki (ostre, fazowanie, zaokrąglenie)
- Wybór promienia R (3-20mm w zależności od typu)
- Kalkulacja ceny w czasie rzeczywistym
- Wizualizacja SVG z interaktywnym podświetlaniem
- Zapis konfiguracji krawędzi w wycenie

### 1.3 Źródło wzorca
- **PrestaShop moduł**: `C:\xampp\htdocs\woodpower\modules\woodconfigurator`
- **Kluczowe pliki**:
  - `views/templates/hook/configurator.tpl` - HTML/SVG
  - `views/js/front/woodconfigurator.js` - logika JS
  - `classes/helpers/WoodPriceCalculator.php` - kalkulacja cen

---

## 2. Architektura

### 2.1 Struktura plików do utworzenia/modyfikacji

```
modules/calculator/
├── models.py                          # MODYFIKACJA: Dodać modele EdgeOption, EdgeConfig
├── routers.py                         # MODYFIKACJA: Dodać endpoint /api/edges-config
├── services/
│   └── edge_calculator.py             # NOWY: Serwis kalkulacji cen krawędzi
├── templates/
│   ├── calculator.html                # MODYFIKACJA: Dodać modal krawędzi
│   └── partials/
│       └── edges_modal.html           # NOWY: Szablon modala krawędzi
├── static/
│   ├── js/
│   │   └── edges.js                   # NOWY: Logika JS dla krawędzi
│   └── css/
│       └── edges.css                  # NOWY: Style modala krawędzi
```

### 2.2 Przepływ danych

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Klik "Dodaj obróbkę krawędzi"                               │
│     ↓                                                            │
│  2. Otwiera się modal z:                                        │
│     - SVG wizualizacją sześcianu                                │
│     - Checkboxami krawędzi (A-H, N1-N4)                         │
│     - Selektorem typu obróbki                                   │
│     - Polem promienia R                                         │
│     ↓                                                            │
│  3. Użytkownik wybiera krawędzie i typ                          │
│     ↓                                                            │
│  4. JS oblicza cenę LIVE (bez AJAX)                             │
│     ↓                                                            │
│  5. Klik "Zastosuj" → dane zapisane w form.dataset              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    ZAPIS WYCENY                                  │
├─────────────────────────────────────────────────────────────────┤
│  6. collectQuoteData() zbiera dane krawędzi z form.dataset      │
│     ↓                                                            │
│  7. POST /calculator/save_quote z JSON zawierającym edges[]     │
│     ↓                                                            │
│  8. Backend zapisuje do QuoteItemEdges                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Baza danych

### 3.1 Architektura (UPROSZCZONA)

**Decyzja architektoniczna:** Zamiast tworzyć osobną tabelę `quote_item_edges` (która wymagałaby do 12 rekordów na produkt), przechowujemy dane krawędzi jako JSON w istniejącej tabeli `quote_items_details`. To upraszcza zapytania i utrzymuje relację 1:1 z produktem.

#### Tabela: `edge_options` (typy obróbki - słownik)
```sql
CREATE TABLE edge_options (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type VARCHAR(32) NOT NULL,              -- 'sharp', 'chamfer', 'round'
    name VARCHAR(100) NOT NULL,             -- 'Ostre', 'Fazowanie', 'Zaokrąglenie'
    price_per_mb DECIMAL(10, 2) NOT NULL,   -- Cena za metr bieżący (netto)
    corner_price DECIMAL(10, 2) NOT NULL,   -- Cena za narożnik (netto)
    r_min INT,                              -- Minimalny promień (NULL dla sharp)
    r_max INT,                              -- Maksymalny promień
    r_default INT,                          -- Domyślny promień
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Dane początkowe:
INSERT INTO edge_options (type, name, price_per_mb, corner_price, r_min, r_max, r_default) VALUES
('sharp', 'Ostre', 0.00, 0.00, NULL, NULL, NULL),
('chamfer', 'Fazowanie', 15.00, 5.00, 3, 10, 3),
('round', 'Zaokrąglenie', 15.00, 5.00, 3, 20, 5);
```

### 3.2 Rozszerzenie tabeli `quote_items_details`

```sql
ALTER TABLE quote_items_details
    ADD COLUMN edges_config JSON DEFAULT NULL,           -- Konfiguracja krawędzi (lista)
    ADD COLUMN edges_type VARCHAR(32) DEFAULT NULL,      -- 'chamfer' lub 'round'
    ADD COLUMN edges_r_value INT DEFAULT NULL,           -- Promień R
    ADD COLUMN edges_price_netto DECIMAL(10, 2) DEFAULT 0,
    ADD COLUMN edges_price_brutto DECIMAL(10, 2) DEFAULT 0;
```

**Struktura `edges_config` (JSON):**
```json
[
    {"letter": "A", "type": "chamfer", "r_value": 3, "length_mm": 1000, "price_netto": 15.00, "price_brutto": 18.45},
    {"letter": "B", "type": "chamfer", "r_value": 3, "length_mm": 1000, "price_netto": 15.00, "price_brutto": 18.45},
    {"letter": "N1", "type": "chamfer", "r_value": 3, "length_mm": 30, "price_netto": 5.00, "price_brutto": 6.15}
]
```

**Zalety tego podejścia:**
- Jedno zapytanie zamiast JOIN z wieloma rekordami
- Spójność danych (1:1 z produktem)
- Łatwiejsze debugowanie i eksport
- Brak potrzeby tworzenia relacji i kaskadowego usuwania

---

## 4. Backend (Python/Flask)

### 4.1 Modele SQLAlchemy

**Plik: `models.py`** - modyfikacje:

#### 4.1.1 Model `EdgeOption` (słownik typów - BEZ ZMIAN)
```python
class EdgeOption(db.Model):
    """Typy obróbki krawędzi (ostre, fazowanie, zaokrąglenie)"""
    __tablename__ = 'edge_options'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(32), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    price_per_mb = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    corner_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    r_min = db.Column(db.Integer, nullable=True)
    r_max = db.Column(db.Integer, nullable=True)
    r_default = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'price_per_mb': float(self.price_per_mb),
            'corner_price': float(self.corner_price),
            'r_min': self.r_min,
            'r_max': self.r_max,
            'r_default': self.r_default
        }
```

#### 4.1.2 Rozszerzenie `QuoteItemDetails` (dodać kolumny)
```python
class QuoteItemDetails(db.Model):
    __tablename__ = 'quote_items_details'

    # ... istniejące kolumny ...

    # NOWE KOLUMNY - obróbka krawędzi
    edges_config = db.Column(db.JSON, nullable=True)      # Lista krawędzi jako JSON
    edges_type = db.Column(db.String(32), nullable=True)  # 'chamfer' lub 'round'
    edges_r_value = db.Column(db.Integer, nullable=True)  # Promień R
    edges_price_netto = db.Column(db.Numeric(10, 2), default=0)
    edges_price_brutto = db.Column(db.Numeric(10, 2), default=0)
```

#### 4.1.3 ~~Model `QuoteItemEdge`~~ - **USUNIĘTY** (zbędny)

### 4.2 Serwis kalkulacji

**Nowy plik: `services/edge_calculator.py`**

```python
"""
Serwis do kalkulacji cen obróbki krawędzi.
Wzorowany na WoodPriceCalculator.php z PrestaShop.
"""

from decimal import Decimal

# Definicje 12 krawędzi
EDGE_DEFINITIONS = {
    # Krawędzie poziome górne (źródło wymiaru)
    'A': {'group': 'top', 'dimension': 'length', 'name': 'Góra przednia'},
    'B': {'group': 'top', 'dimension': 'length', 'name': 'Góra tylna'},
    'C': {'group': 'top', 'dimension': 'width', 'name': 'Góra lewa'},
    'D': {'group': 'top', 'dimension': 'width', 'name': 'Góra prawa'},

    # Krawędzie poziome dolne
    'E': {'group': 'bottom', 'dimension': 'length', 'name': 'Dół przednia'},
    'F': {'group': 'bottom', 'dimension': 'length', 'name': 'Dół tylna'},
    'G': {'group': 'bottom', 'dimension': 'width', 'name': 'Dół lewa'},
    'H': {'group': 'bottom', 'dimension': 'width', 'name': 'Dół prawa'},

    # Narożniki (krawędzie pionowe)
    'N1': {'group': 'corner', 'dimension': 'thickness', 'name': 'Przedni lewy'},
    'N2': {'group': 'corner', 'dimension': 'thickness', 'name': 'Przedni prawy'},
    'N3': {'group': 'corner', 'dimension': 'thickness', 'name': 'Tylny lewy'},
    'N4': {'group': 'corner', 'dimension': 'thickness', 'name': 'Tylny prawy'},
}

# Ceny (można później przenieść do bazy)
EDGE_PRICES = {
    'sharp': {'per_mb': Decimal('0.00'), 'per_corner': Decimal('0.00')},
    'chamfer': {'per_mb': Decimal('15.00'), 'per_corner': Decimal('5.00')},
    'round': {'per_mb': Decimal('15.00'), 'per_corner': Decimal('5.00')},
}


def get_edge_length_mm(edge_letter: str, dimensions: dict) -> int:
    """
    Zwraca długość krawędzi w mm na podstawie litery i wymiarów produktu.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)
        dimensions: Słownik z kluczami 'length', 'width', 'thickness' (w cm)

    Returns:
        Długość krawędzi w mm
    """
    definition = EDGE_DEFINITIONS.get(edge_letter.upper())
    if not definition:
        return 0

    dimension_key = definition['dimension']
    length_cm = dimensions.get(dimension_key, 0)

    return int(float(length_cm) * 10)  # cm → mm


def calculate_edge_price(edge_letter: str, edge_type: str, dimensions: dict, r_value: int = None) -> dict:
    """
    Oblicza cenę dla pojedynczej krawędzi.

    Args:
        edge_letter: Litera krawędzi (A-H, N1-N4)
        edge_type: Typ obróbki ('sharp', 'chamfer', 'round')
        dimensions: Wymiary produktu w cm
        r_value: Promień R (opcjonalny)

    Returns:
        Słownik z ceną netto, brutto i długością
    """
    if edge_type == 'sharp':
        return {
            'edge_letter': edge_letter,
            'edge_type': edge_type,
            'length_mm': 0,
            'r_value': None,
            'price_netto': Decimal('0.00'),
            'price_brutto': Decimal('0.00')
        }

    length_mm = get_edge_length_mm(edge_letter, dimensions)
    prices = EDGE_PRICES.get(edge_type, EDGE_PRICES['sharp'])

    definition = EDGE_DEFINITIONS.get(edge_letter.upper())
    is_corner = definition and definition['group'] == 'corner'

    if is_corner:
        # Narożniki - stała cena za sztukę
        price_netto = prices['per_corner']
    else:
        # Krawędzie poziome - cena za metr bieżący
        length_mb = Decimal(length_mm) / Decimal('1000')
        price_netto = length_mb * prices['per_mb']

    price_brutto = price_netto * Decimal('1.23')

    return {
        'edge_letter': edge_letter,
        'edge_type': edge_type,
        'length_mm': length_mm,
        'r_value': r_value,
        'price_netto': round(price_netto, 2),
        'price_brutto': round(price_brutto, 2)
    }


def calculate_all_edges(edges_config: list, dimensions: dict) -> dict:
    """
    Oblicza cenę dla wszystkich wybranych krawędzi.

    Args:
        edges_config: Lista konfiguracji krawędzi [{'letter': 'A', 'type': 'chamfer', 'r_value': 3}, ...]
        dimensions: Wymiary produktu {'length': 100, 'width': 25, 'thickness': 3}

    Returns:
        Słownik z podsumowaniem i listą szczegółów
    """
    details = []
    total_netto = Decimal('0.00')
    total_brutto = Decimal('0.00')
    total_length_mm = 0
    horizontal_count = 0
    corner_count = 0

    for edge in edges_config:
        letter = edge.get('letter', '').upper()
        edge_type = edge.get('type', 'sharp')
        r_value = edge.get('r_value')

        if edge_type == 'sharp':
            continue

        result = calculate_edge_price(letter, edge_type, dimensions, r_value)
        details.append(result)

        total_netto += result['price_netto']
        total_brutto += result['price_brutto']
        total_length_mm += result['length_mm']

        definition = EDGE_DEFINITIONS.get(letter)
        if definition:
            if definition['group'] == 'corner':
                corner_count += 1
            else:
                horizontal_count += 1

    return {
        'details': details,
        'horizontal_count': horizontal_count,
        'corner_count': corner_count,
        'total_length_mm': total_length_mm,
        'total_length_mb': round(total_length_mm / 1000, 2),
        'total_netto': round(total_netto, 2),
        'total_brutto': round(total_brutto, 2)
    }
```

### 4.3 Endpoint API

**Plik: `routers.py`** - dodać endpoint:

```python
from services.edge_calculator import EDGE_DEFINITIONS, calculate_all_edges

@calculator_bp.route('/api/edge-options', methods=['GET'])
def get_edge_options():
    """Zwraca dostępne typy obróbki krawędzi"""
    options = EdgeOption.query.filter_by(is_active=True).order_by(EdgeOption.id).all()
    return jsonify([opt.to_dict() for opt in options])


@calculator_bp.route('/api/edge-definitions', methods=['GET'])
def get_edge_definitions():
    """Zwraca definicje 12 krawędzi"""
    return jsonify(EDGE_DEFINITIONS)


@calculator_bp.route('/api/calculate-edges', methods=['POST'])
def calculate_edges():
    """Oblicza cenę obróbki krawędzi (opcjonalnie - można liczyć na froncie)"""
    data = request.get_json()

    edges_config = data.get('edges', [])
    dimensions = {
        'length': data.get('length', 0),
        'width': data.get('width', 0),
        'thickness': data.get('thickness', 0)
    }

    result = calculate_all_edges(edges_config, dimensions)
    return jsonify(result)
```

### 4.4 Modyfikacja zapisu wyceny

**Plik: `routers.py`** - w funkcji `save_quote()`, po zapisie `QuoteItemDetails`:

```python
# W pętli for i, product in enumerate(products):
# Po linii z db.session.add(item_details):

# Zapisz krawędzie dla produktu
edges_data = product.get('edges', [])
if edges_data:
    for edge in edges_data:
        if edge.get('type') == 'sharp':
            continue  # Pomijamy ostre

        quote_edge = QuoteItemEdge(
            quote_id=quote.id,
            product_index=i + 1,
            edge_letter=edge.get('letter'),
            edge_type=edge.get('type'),
            edge_length_mm=edge.get('length_mm', 0),
            r_value=edge.get('r_value'),
            price_netto=edge.get('price_netto', 0),
            price_brutto=edge.get('price_brutto', 0)
        )
        db.session.add(quote_edge)
```

---

## 5. Frontend (HTML/CSS/JS)

### 5.1 Modal HTML

**Nowy plik: `templates/partials/edges_modal.html`**

```html
<!-- Modal obróbki krawędzi -->
<div id="edgesModal" class="edges-modal-overlay" style="display: none;">
    <div class="edges-modal-container">
        <div class="edges-modal-header">
            <h3>Obróbka krawędzi</h3>
            <button type="button" class="edges-modal-close" id="closeEdgesModal">&times;</button>
        </div>

        <div class="edges-modal-body">
            <!-- Sekcja górna: Wizualizacja + Opcje -->
            <div class="edges-top-section">
                <!-- Wizualizacja SVG -->
                <div class="edges-visualization">
                    <button type="button" class="edges-toggle-labels" id="toggleEdgeLabels">
                        Ukryj etykiety
                    </button>
                    <div class="edges-svg-container">
                        <!-- SVG izometryczny sześcian -->
                        <svg viewBox="0 0 320 200" class="edges-interactive-svg" id="edgesSvg">
                            <!-- Ściany (tło) -->
                            <polygon class="edges-face edges-face-top"
                                     points="50,120 120,70 270,100 200,150"/>
                            <polygon class="edges-face edges-face-front"
                                     points="50,120 200,150 200,175 50,145"/>
                            <polygon class="edges-face edges-face-right"
                                     points="200,150 270,100 270,125 200,175"/>

                            <!-- Krawędzie ukryte (przerywane) -->
                            <line class="edges-line edges-hidden" data-edge="F" x1="120" y1="95" x2="270" y2="125"/>
                            <line class="edges-line edges-hidden" data-edge="G" x1="50" y1="145" x2="120" y2="95"/>
                            <line class="edges-line edges-hidden edges-corner" data-edge="N3" x1="120" y1="70" x2="120" y2="95"/>

                            <!-- Krawędzie górne -->
                            <line class="edges-line" data-edge="A" x1="50" y1="120" x2="200" y2="150"/>
                            <line class="edges-line" data-edge="B" x1="120" y1="70" x2="270" y2="100"/>
                            <line class="edges-line" data-edge="C" x1="50" y1="120" x2="120" y2="70"/>
                            <line class="edges-line" data-edge="D" x1="200" y1="150" x2="270" y2="100"/>

                            <!-- Krawędzie dolne widoczne -->
                            <line class="edges-line" data-edge="E" x1="50" y1="145" x2="200" y2="175"/>
                            <line class="edges-line" data-edge="H" x1="200" y1="175" x2="270" y2="125"/>

                            <!-- Narożniki (pionowe) -->
                            <line class="edges-line edges-corner" data-edge="N1" x1="50" y1="120" x2="50" y2="145"/>
                            <line class="edges-line edges-corner" data-edge="N2" x1="200" y1="150" x2="200" y2="175"/>
                            <line class="edges-line edges-corner" data-edge="N4" x1="270" y1="100" x2="270" y2="125"/>

                            <!-- Etykiety -->
                            <g class="edges-labels" id="edgeLabelsGroup">
                                <!-- Górne poziome -->
                                <g class="edges-label" data-edge="A">
                                    <circle cx="125" cy="138" r="12"/>
                                    <text x="125" y="143">A</text>
                                </g>
                                <g class="edges-label" data-edge="B">
                                    <circle cx="195" cy="88" r="12"/>
                                    <text x="195" y="93">B</text>
                                </g>
                                <g class="edges-label" data-edge="C">
                                    <circle cx="80" cy="92" r="12"/>
                                    <text x="80" y="97">C</text>
                                </g>
                                <g class="edges-label" data-edge="D">
                                    <circle cx="238" cy="128" r="12"/>
                                    <text x="238" y="133">D</text>
                                </g>

                                <!-- Dolne poziome -->
                                <g class="edges-label" data-edge="E">
                                    <circle cx="125" cy="163" r="12"/>
                                    <text x="125" y="168">E</text>
                                </g>
                                <g class="edges-label" data-edge="F">
                                    <circle cx="195" cy="113" r="12"/>
                                    <text x="195" y="118">F</text>
                                </g>
                                <g class="edges-label" data-edge="G">
                                    <circle cx="80" cy="118" r="12"/>
                                    <text x="80" y="123">G</text>
                                </g>
                                <g class="edges-label" data-edge="H">
                                    <circle cx="238" cy="153" r="12"/>
                                    <text x="238" y="158">H</text>
                                </g>

                                <!-- Narożniki -->
                                <g class="edges-label edges-label-corner" data-edge="N1">
                                    <circle cx="38" cy="132" r="14"/>
                                    <text x="38" y="137">N1</text>
                                </g>
                                <g class="edges-label edges-label-corner" data-edge="N2">
                                    <circle cx="212" cy="165" r="14"/>
                                    <text x="212" y="170">N2</text>
                                </g>
                                <g class="edges-label edges-label-corner" data-edge="N3">
                                    <circle cx="132" cy="82" r="14"/>
                                    <text x="132" y="87">N3</text>
                                </g>
                                <g class="edges-label edges-label-corner" data-edge="N4">
                                    <circle cx="282" cy="115" r="14"/>
                                    <text x="282" y="120">N4</text>
                                </g>
                            </g>
                        </svg>
                    </div>
                </div>

                <!-- Panel opcji -->
                <div class="edges-options-panel">
                    <!-- Szybkie akcje -->
                    <div class="edges-quick-actions">
                        <button type="button" class="edges-quick-btn" data-action="select-top">Góra</button>
                        <button type="button" class="edges-quick-btn" data-action="select-bottom">Dół</button>
                        <button type="button" class="edges-quick-btn" data-action="select-all">Wszystkie</button>
                        <button type="button" class="edges-quick-btn" data-action="deselect-all">Odznacz</button>
                    </div>

                    <!-- Typ obróbki -->
                    <div class="edges-type-selector">
                        <label>Typ obróbki:</label>
                        <select id="edgeTypeSelect">
                            <option value="chamfer" data-r-min="3" data-r-max="10" data-r-default="3">Fazowanie</option>
                            <option value="round" data-r-min="3" data-r-max="20" data-r-default="5">Zaokrąglenie</option>
                        </select>
                    </div>

                    <!-- Promień R -->
                    <div class="edges-r-value-group">
                        <label>Promień R:</label>
                        <input type="number" id="edgeRValue" min="3" max="10" value="3">
                        <span>mm</span>
                    </div>
                </div>
            </div>

            <!-- Sekcja krawędzi poziomych -->
            <div class="edges-section">
                <h4>Krawędzie poziome</h4>

                <!-- Góra -->
                <div class="edges-group">
                    <h5>GÓRA</h5>
                    <div class="edges-list">
                        <div class="edges-item" data-edge="A">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_A">
                                <span class="edges-letter">A</span>
                                <span class="edges-name">Góra przednia</span>
                                <span class="edges-length" data-dimension="length">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="B">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_B">
                                <span class="edges-letter">B</span>
                                <span class="edges-name">Góra tylna</span>
                                <span class="edges-length" data-dimension="length">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="C">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_C">
                                <span class="edges-letter">C</span>
                                <span class="edges-name">Góra lewa</span>
                                <span class="edges-length" data-dimension="width">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="D">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_D">
                                <span class="edges-letter">D</span>
                                <span class="edges-name">Góra prawa</span>
                                <span class="edges-length" data-dimension="width">(0 cm)</span>
                            </label>
                        </div>
                    </div>
                </div>

                <!-- Dół -->
                <div class="edges-group">
                    <h5>DÓŁ</h5>
                    <div class="edges-list">
                        <div class="edges-item" data-edge="E">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_E">
                                <span class="edges-letter">E</span>
                                <span class="edges-name">Dół przednia</span>
                                <span class="edges-length" data-dimension="length">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="F">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_F">
                                <span class="edges-letter">F</span>
                                <span class="edges-name">Dół tylna</span>
                                <span class="edges-length" data-dimension="length">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="G">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_G">
                                <span class="edges-letter">G</span>
                                <span class="edges-name">Dół lewa</span>
                                <span class="edges-length" data-dimension="width">(0 cm)</span>
                            </label>
                        </div>
                        <div class="edges-item" data-edge="H">
                            <label class="edges-checkbox">
                                <input type="checkbox" name="edge_H">
                                <span class="edges-letter">H</span>
                                <span class="edges-name">Dół prawa</span>
                                <span class="edges-length" data-dimension="width">(0 cm)</span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sekcja narożników -->
            <div class="edges-section edges-corners-section">
                <h4>Narożniki (krawędzie pionowe)</h4>
                <div class="edges-list edges-corners-list">
                    <div class="edges-item edges-corner-item" data-edge="N1">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_N1">
                            <span class="edges-letter edges-letter-corner">N1</span>
                            <span class="edges-name">Przedni lewy</span>
                            <span class="edges-length" data-dimension="thickness">(0 cm)</span>
                        </label>
                    </div>
                    <div class="edges-item edges-corner-item" data-edge="N2">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_N2">
                            <span class="edges-letter edges-letter-corner">N2</span>
                            <span class="edges-name">Przedni prawy</span>
                            <span class="edges-length" data-dimension="thickness">(0 cm)</span>
                        </label>
                    </div>
                    <div class="edges-item edges-corner-item" data-edge="N3">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_N3">
                            <span class="edges-letter edges-letter-corner">N3</span>
                            <span class="edges-name">Tylny lewy</span>
                            <span class="edges-length" data-dimension="thickness">(0 cm)</span>
                        </label>
                    </div>
                    <div class="edges-item edges-corner-item" data-edge="N4">
                        <label class="edges-checkbox">
                            <input type="checkbox" name="edge_N4">
                            <span class="edges-letter edges-letter-corner">N4</span>
                            <span class="edges-name">Tylny prawy</span>
                            <span class="edges-length" data-dimension="thickness">(0 cm)</span>
                        </label>
                    </div>
                </div>
            </div>
        </div>

        <!-- Stopka z ceną i przyciskiem -->
        <div class="edges-modal-footer">
            <div class="edges-price-summary">
                <span class="edges-price-label">Cena za obróbkę krawędzi:</span>
                <span class="edges-price-brutto" id="edgesPriceBrutto">0,00 zł</span>
                <span class="edges-price-netto" id="edgesPriceNetto">(0,00 zł netto)</span>
            </div>
            <button type="button" class="edges-apply-btn" id="applyEdgesBtn">ZASTOSUJ</button>
        </div>
    </div>
</div>
```

### 5.2 Style CSS

**Nowy plik: `static/css/edges.css`**

```css
/* ==========================================
   MODAL OBRÓBKI KRAWĘDZI
   ========================================== */

.edges-modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
}

.edges-modal-container {
    background: #fff;
    border-radius: 16px;
    width: 850px;
    max-width: 95vw;
    max-height: 90vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

/* Header */
.edges-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    background: #ED6B24;
    color: #fff;
}

.edges-modal-header h3 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
}

.edges-modal-close {
    background: none;
    border: none;
    color: #fff;
    font-size: 28px;
    cursor: pointer;
    line-height: 1;
    padding: 0;
    opacity: 0.8;
    transition: opacity 0.2s;
}

.edges-modal-close:hover {
    opacity: 1;
}

/* Body */
.edges-modal-body {
    padding: 24px;
    overflow-y: auto;
    flex: 1;
}

/* Top section: SVG + Options */
.edges-top-section {
    display: flex;
    gap: 24px;
    margin-bottom: 24px;
    padding-bottom: 24px;
    border-bottom: 1px solid #eee;
}

/* SVG Visualization */
.edges-visualization {
    flex: 0 0 320px;
    position: relative;
}

.edges-toggle-labels {
    position: absolute;
    top: 0;
    left: 0;
    padding: 6px 12px;
    font-size: 12px;
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 6px;
    cursor: pointer;
    z-index: 1;
}

.edges-svg-container {
    padding-top: 20px;
}

.edges-interactive-svg {
    width: 100%;
    height: auto;
}

/* SVG Faces */
.edges-face {
    fill: #f0f0f0;
    stroke: none;
}

.edges-face-top {
    fill: #e8e8e8;
}

.edges-face-front {
    fill: #d8d8d8;
}

.edges-face-right {
    fill: #c8c8c8;
}

/* SVG Lines */
.edges-line {
    stroke: #666;
    stroke-width: 2;
    fill: none;
    transition: stroke 0.2s, stroke-width 0.2s;
}

.edges-line.edges-hidden {
    stroke-dasharray: 5, 5;
    stroke: #999;
}

.edges-line.active {
    stroke: #ED6B24;
    stroke-width: 3;
}

.edges-line.highlight {
    stroke: #ED6B24;
    stroke-width: 4;
}

/* SVG Labels */
.edges-label circle {
    fill: #ED6B24;
    transition: fill 0.2s, r 0.2s;
}

.edges-label text {
    fill: #fff;
    font-size: 11px;
    font-weight: 600;
    text-anchor: middle;
    font-family: 'Poppins', sans-serif;
}

.edges-label-corner circle {
    r: 14;
}

.edges-label-corner text {
    font-size: 9px;
}

.edges-label.active circle {
    fill: #c45a1e;
}

.edges-labels-hidden .edges-label {
    opacity: 0;
}

/* Options Panel */
.edges-options-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

/* Quick Actions */
.edges-quick-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.edges-quick-btn {
    padding: 8px 16px;
    font-size: 13px;
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}

.edges-quick-btn:hover {
    background: #ED6B24;
    color: #fff;
    border-color: #ED6B24;
}

/* Type Selector */
.edges-type-selector {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    background: #f9f9f9;
    border-radius: 12px;
}

.edges-type-selector label {
    font-weight: 500;
    color: #333;
}

.edges-type-selector select {
    flex: 1;
    padding: 10px 14px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 14px;
    cursor: pointer;
}

/* R Value */
.edges-r-value-group {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    background: #f9f9f9;
    border-radius: 12px;
}

.edges-r-value-group label {
    font-weight: 500;
    color: #333;
}

.edges-r-value-group input {
    width: 80px;
    padding: 10px 14px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 14px;
    text-align: center;
}

.edges-r-value-group span {
    color: #666;
}

/* Edges Sections */
.edges-section {
    margin-bottom: 20px;
}

.edges-section h4 {
    font-size: 14px;
    font-weight: 600;
    color: #333;
    margin: 0 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #ED6B24;
}

.edges-group {
    margin-bottom: 16px;
}

.edges-group h5 {
    font-size: 12px;
    font-weight: 600;
    color: #666;
    margin: 0 0 8px 0;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Edges List */
.edges-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
}

.edges-corners-list {
    grid-template-columns: repeat(2, 1fr);
}

/* Edge Item */
.edges-item {
    background: #f9f9f9;
    border-radius: 10px;
    padding: 12px 16px;
    transition: all 0.2s;
    border: 2px solid transparent;
}

.edges-item:hover {
    background: #f0f0f0;
}

.edges-item.selected {
    background: #FFF5F0;
    border-color: #ED6B24;
}

.edges-checkbox {
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
}

.edges-checkbox input[type="checkbox"] {
    width: 18px;
    height: 18px;
    accent-color: #ED6B24;
    cursor: pointer;
}

.edges-letter {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: #ED6B24;
    color: #fff;
    border-radius: 50%;
    font-weight: 600;
    font-size: 13px;
}

.edges-letter-corner {
    width: 32px;
    height: 32px;
    font-size: 11px;
}

.edges-name {
    flex: 1;
    font-size: 13px;
    color: #333;
}

.edges-length {
    font-size: 12px;
    color: #888;
}

/* Footer */
.edges-modal-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    background: #FFF5F0;
    border-top: 1px solid #ffd9c7;
}

.edges-price-summary {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.edges-price-label {
    font-size: 13px;
    color: #666;
}

.edges-price-brutto {
    font-size: 24px;
    font-weight: 700;
    color: #ED6B24;
}

.edges-price-netto {
    font-size: 13px;
    color: #888;
}

.edges-apply-btn {
    padding: 14px 40px;
    font-size: 15px;
    font-weight: 600;
    background: #ED6B24;
    color: #fff;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
}

.edges-apply-btn:hover {
    background: #d55a1a;
    transform: translateY(-1px);
}

/* Responsive */
@media (max-width: 768px) {
    .edges-top-section {
        flex-direction: column;
    }

    .edges-visualization {
        flex: none;
    }

    .edges-list {
        grid-template-columns: 1fr;
    }

    .edges-modal-footer {
        flex-direction: column;
        gap: 16px;
        text-align: center;
    }
}
```

### 5.3 Logika JavaScript

**Nowy plik: `static/js/edges.js`**

```javascript
/**
 * Moduł obróbki krawędzi dla kalkulatora WoodPower CRM
 * Wzorowany na woodconfigurator.js z PrestaShop
 */

const EdgesModule = (function() {
    'use strict';

    // ==========================================
    // KONFIGURACJA
    // ==========================================

    const CONFIG = {
        // Ceny (netto, PLN)
        PRICE_PER_MB: 15.00,      // Cena za metr bieżący
        PRICE_PER_CORNER: 5.00,   // Cena za narożnik
        VAT_RATE: 1.23,           // Stawka VAT

        // Promienie R
        R_LIMITS: {
            chamfer: { min: 3, max: 10, default: 3 },
            round: { min: 3, max: 20, default: 5 }
        }
    };

    // Definicje krawędzi
    const EDGES = {
        // Poziome górne
        A: { group: 'top', dimension: 'length', name: 'Góra przednia' },
        B: { group: 'top', dimension: 'length', name: 'Góra tylna' },
        C: { group: 'top', dimension: 'width', name: 'Góra lewa' },
        D: { group: 'top', dimension: 'width', name: 'Góra prawa' },

        // Poziome dolne
        E: { group: 'bottom', dimension: 'length', name: 'Dół przednia' },
        F: { group: 'bottom', dimension: 'length', name: 'Dół tylna' },
        G: { group: 'bottom', dimension: 'width', name: 'Dół lewa' },
        H: { group: 'bottom', dimension: 'width', name: 'Dół prawa' },

        // Narożniki
        N1: { group: 'corner', dimension: 'thickness', name: 'Przedni lewy' },
        N2: { group: 'corner', dimension: 'thickness', name: 'Przedni prawy' },
        N3: { group: 'corner', dimension: 'thickness', name: 'Tylny lewy' },
        N4: { group: 'corner', dimension: 'thickness', name: 'Tylny prawy' }
    };

    // ==========================================
    // STAN
    // ==========================================

    let state = {
        isOpen: false,
        currentForm: null,
        selectedEdges: new Set(),
        edgeType: 'chamfer',
        rValue: 3,
        dimensions: { length: 0, width: 0, thickness: 0 },
        labelsVisible: true
    };

    // ==========================================
    // ELEMENTY DOM
    // ==========================================

    let elements = {};

    function cacheElements() {
        elements = {
            modal: document.getElementById('edgesModal'),
            closeBtn: document.getElementById('closeEdgesModal'),
            applyBtn: document.getElementById('applyEdgesBtn'),
            toggleLabelsBtn: document.getElementById('toggleEdgeLabels'),
            typeSelect: document.getElementById('edgeTypeSelect'),
            rValueInput: document.getElementById('edgeRValue'),
            priceBrutto: document.getElementById('edgesPriceBrutto'),
            priceNetto: document.getElementById('edgesPriceNetto'),
            svg: document.getElementById('edgesSvg'),
            labelsGroup: document.getElementById('edgeLabelsGroup'),
            quickBtns: document.querySelectorAll('.edges-quick-btn'),
            checkboxes: document.querySelectorAll('.edges-item input[type="checkbox"]'),
            items: document.querySelectorAll('.edges-item')
        };
    }

    // ==========================================
    // INICJALIZACJA
    // ==========================================

    function init() {
        cacheElements();
        attachEventListeners();
        console.log('EdgesModule initialized');
    }

    function attachEventListeners() {
        // Otwieranie modala - nasłuchuj na przycisku w każdym formularzu
        document.addEventListener('click', function(e) {
            if (e.target.closest('#openEdgesModal')) {
                const form = e.target.closest('.quote-form');
                openModal(form);
            }
        });

        // Zamykanie modala
        if (elements.closeBtn) {
            elements.closeBtn.addEventListener('click', closeModal);
        }

        // Zamykanie przez klik na overlay
        if (elements.modal) {
            elements.modal.addEventListener('click', function(e) {
                if (e.target === elements.modal) {
                    closeModal();
                }
            });
        }

        // Zamykanie przez ESC
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && state.isOpen) {
                closeModal();
            }
        });

        // Przycisk Zastosuj
        if (elements.applyBtn) {
            elements.applyBtn.addEventListener('click', applyEdges);
        }

        // Toggle etykiet
        if (elements.toggleLabelsBtn) {
            elements.toggleLabelsBtn.addEventListener('click', toggleLabels);
        }

        // Zmiana typu obróbki
        if (elements.typeSelect) {
            elements.typeSelect.addEventListener('change', onTypeChange);
        }

        // Zmiana promienia R
        if (elements.rValueInput) {
            elements.rValueInput.addEventListener('input', onRValueChange);
        }

        // Szybkie akcje
        elements.quickBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                const action = this.dataset.action;
                handleQuickAction(action);
            });
        });

        // Checkboxy krawędzi
        elements.checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', onCheckboxChange);
        });

        // Hover na elementach listy
        elements.items.forEach(item => {
            item.addEventListener('mouseenter', function() {
                const edge = this.dataset.edge;
                highlightEdge(edge, true);
            });
            item.addEventListener('mouseleave', function() {
                const edge = this.dataset.edge;
                highlightEdge(edge, false);
            });
        });
    }

    // ==========================================
    // MODAL
    // ==========================================

    function openModal(form) {
        state.currentForm = form || document.querySelector('.quote-form');
        state.isOpen = true;

        // Pobierz wymiary z formularza
        loadDimensionsFromForm();

        // Aktualizuj długości krawędzi w UI
        updateEdgeLengths();

        // Wczytaj zapisany stan (jeśli istnieje)
        loadSavedState();

        // Pokaż modal
        elements.modal.style.display = 'flex';

        // Przelicz cenę
        calculatePrice();
    }

    function closeModal() {
        state.isOpen = false;
        elements.modal.style.display = 'none';
    }

    // ==========================================
    // WYMIARY
    // ==========================================

    function loadDimensionsFromForm() {
        if (!state.currentForm) return;

        const lengthInput = state.currentForm.querySelector('input[data-field="length"]');
        const widthInput = state.currentForm.querySelector('input[data-field="width"]');
        const thicknessInput = state.currentForm.querySelector('input[data-field="thickness"]');

        state.dimensions = {
            length: parseFloat(lengthInput?.value) || 0,
            width: parseFloat(widthInput?.value) || 0,
            thickness: parseFloat(thicknessInput?.value) || 0
        };
    }

    function updateEdgeLengths() {
        elements.items.forEach(item => {
            const edge = item.dataset.edge;
            const lengthSpan = item.querySelector('.edges-length');

            if (lengthSpan && EDGES[edge]) {
                const dimension = EDGES[edge].dimension;
                const lengthCm = state.dimensions[dimension] || 0;
                lengthSpan.textContent = `(${lengthCm.toFixed(1)} cm)`;
            }
        });
    }

    // ==========================================
    // OBSŁUGA ZDARZEŃ
    // ==========================================

    function onTypeChange() {
        state.edgeType = elements.typeSelect.value;

        // Aktualizuj limity promienia R
        const limits = CONFIG.R_LIMITS[state.edgeType];
        if (limits) {
            elements.rValueInput.min = limits.min;
            elements.rValueInput.max = limits.max;

            // Jeśli aktualna wartość poza limitami, ustaw domyślną
            if (state.rValue < limits.min || state.rValue > limits.max) {
                state.rValue = limits.default;
                elements.rValueInput.value = limits.default;
            }
        }

        calculatePrice();
    }

    function onRValueChange() {
        state.rValue = parseInt(elements.rValueInput.value) || 3;
        calculatePrice();
    }

    function onCheckboxChange(e) {
        const item = e.target.closest('.edges-item');
        const edge = item.dataset.edge;

        if (e.target.checked) {
            state.selectedEdges.add(edge);
            item.classList.add('selected');
            updateSvgEdge(edge, true);
        } else {
            state.selectedEdges.delete(edge);
            item.classList.remove('selected');
            updateSvgEdge(edge, false);
        }

        calculatePrice();
    }

    function handleQuickAction(action) {
        const topEdges = ['A', 'B', 'C', 'D'];
        const bottomEdges = ['E', 'F', 'G', 'H'];
        const allEdges = [...topEdges, ...bottomEdges, 'N1', 'N2', 'N3', 'N4'];

        let edgesToSelect = [];

        switch (action) {
            case 'select-top':
                edgesToSelect = topEdges;
                break;
            case 'select-bottom':
                edgesToSelect = bottomEdges;
                break;
            case 'select-all':
                edgesToSelect = allEdges;
                break;
            case 'deselect-all':
                // Odznacz wszystkie
                state.selectedEdges.clear();
                elements.checkboxes.forEach(cb => {
                    cb.checked = false;
                    cb.closest('.edges-item').classList.remove('selected');
                });
                allEdges.forEach(edge => updateSvgEdge(edge, false));
                calculatePrice();
                return;
        }

        // Zaznacz wybrane
        edgesToSelect.forEach(edge => {
            state.selectedEdges.add(edge);
            const item = document.querySelector(`.edges-item[data-edge="${edge}"]`);
            if (item) {
                item.querySelector('input[type="checkbox"]').checked = true;
                item.classList.add('selected');
                updateSvgEdge(edge, true);
            }
        });

        calculatePrice();
    }

    function toggleLabels() {
        state.labelsVisible = !state.labelsVisible;

        if (state.labelsVisible) {
            elements.labelsGroup.classList.remove('edges-labels-hidden');
            elements.toggleLabelsBtn.textContent = 'Ukryj etykiety';
        } else {
            elements.labelsGroup.classList.add('edges-labels-hidden');
            elements.toggleLabelsBtn.textContent = 'Pokaż etykiety';
        }
    }

    // ==========================================
    // SVG
    // ==========================================

    function updateSvgEdge(edge, active) {
        const line = elements.svg.querySelector(`.edges-line[data-edge="${edge}"]`);
        const label = elements.svg.querySelector(`.edges-label[data-edge="${edge}"]`);

        if (line) {
            line.classList.toggle('active', active);
        }
        if (label) {
            label.classList.toggle('active', active);
        }
    }

    function highlightEdge(edge, highlight) {
        const line = elements.svg.querySelector(`.edges-line[data-edge="${edge}"]`);
        if (line) {
            line.classList.toggle('highlight', highlight);
        }
    }

    // ==========================================
    // KALKULACJA CENY
    // ==========================================

    function calculatePrice() {
        let totalNetto = 0;
        let horizontalCount = 0;
        let cornerCount = 0;

        state.selectedEdges.forEach(edge => {
            const def = EDGES[edge];
            if (!def) return;

            if (def.group === 'corner') {
                // Narożnik - stała cena
                totalNetto += CONFIG.PRICE_PER_CORNER;
                cornerCount++;
            } else {
                // Krawędź pozioma - cena za metr bieżący
                const lengthCm = state.dimensions[def.dimension] || 0;
                const lengthMb = lengthCm / 100;  // cm → m
                totalNetto += lengthMb * CONFIG.PRICE_PER_MB;
                horizontalCount++;
            }
        });

        const totalBrutto = totalNetto * CONFIG.VAT_RATE;

        // Aktualizuj UI
        elements.priceBrutto.textContent = formatPLN(totalBrutto);
        elements.priceNetto.textContent = `(${formatPLN(totalNetto)} netto)`;

        return {
            netto: Math.round(totalNetto * 100) / 100,
            brutto: Math.round(totalBrutto * 100) / 100,
            horizontalCount,
            cornerCount
        };
    }

    function formatPLN(value) {
        return value.toLocaleString('pl-PL', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }) + ' zł';
    }

    // ==========================================
    // ZAPIS / ODCZYT STANU
    // ==========================================

    function applyEdges() {
        if (!state.currentForm) return;

        const prices = calculatePrice();

        // Zbierz dane o wybranych krawędziach
        const edgesData = [];
        state.selectedEdges.forEach(edge => {
            const def = EDGES[edge];
            if (!def) return;

            const lengthCm = state.dimensions[def.dimension] || 0;
            const lengthMm = lengthCm * 10;

            let priceNetto = 0;
            if (def.group === 'corner') {
                priceNetto = CONFIG.PRICE_PER_CORNER;
            } else {
                priceNetto = (lengthCm / 100) * CONFIG.PRICE_PER_MB;
            }

            edgesData.push({
                letter: edge,
                type: state.edgeType,
                r_value: state.rValue,
                length_mm: lengthMm,
                price_netto: Math.round(priceNetto * 100) / 100,
                price_brutto: Math.round(priceNetto * CONFIG.VAT_RATE * 100) / 100
            });
        });

        // Zapisz w dataset formularza
        state.currentForm.dataset.edgesData = JSON.stringify(edgesData);
        state.currentForm.dataset.edgesNetto = prices.netto;
        state.currentForm.dataset.edgesBrutto = prices.brutto;
        state.currentForm.dataset.edgesCount = state.selectedEdges.size;
        state.currentForm.dataset.edgesType = state.edgeType;
        state.currentForm.dataset.edgesRValue = state.rValue;

        // Aktualizuj przycisk (opcjonalnie - zmień tekst na "Edytuj obróbkę")
        const openBtn = state.currentForm.querySelector('#openEdgesModal');
        if (openBtn && state.selectedEdges.size > 0) {
            openBtn.innerHTML = `Obróbka krawędzi (${state.selectedEdges.size})<br><span style="font-size: 12px;">${formatPLN(prices.brutto)}</span>`;
        }

        // Wywołaj aktualizację globalnego podsumowania
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }

        closeModal();
    }

    function loadSavedState() {
        if (!state.currentForm) return;

        const savedData = state.currentForm.dataset.edgesData;
        if (!savedData) {
            // Reset stanu
            state.selectedEdges.clear();
            state.edgeType = 'chamfer';
            state.rValue = 3;

            // Reset UI
            elements.checkboxes.forEach(cb => {
                cb.checked = false;
                cb.closest('.edges-item').classList.remove('selected');
            });
            document.querySelectorAll('.edges-line').forEach(line => {
                line.classList.remove('active');
            });

            return;
        }

        try {
            const edges = JSON.parse(savedData);

            // Przywróć stan
            state.selectedEdges.clear();
            edges.forEach(edge => {
                state.selectedEdges.add(edge.letter);
            });

            // Przywróć typ i R
            if (edges.length > 0) {
                state.edgeType = edges[0].type || 'chamfer';
                state.rValue = edges[0].r_value || 3;
            }

            // Aktualizuj UI
            elements.typeSelect.value = state.edgeType;
            elements.rValueInput.value = state.rValue;

            elements.checkboxes.forEach(cb => {
                const item = cb.closest('.edges-item');
                const edge = item.dataset.edge;
                const isSelected = state.selectedEdges.has(edge);

                cb.checked = isSelected;
                item.classList.toggle('selected', isSelected);
                updateSvgEdge(edge, isSelected);
            });

        } catch (e) {
            console.error('Error loading saved edges state:', e);
        }
    }

    // ==========================================
    // PUBLICZNE API
    // ==========================================

    return {
        init,
        openModal,
        closeModal,
        getState: () => ({ ...state }),
        getSelectedEdges: () => Array.from(state.selectedEdges),
        getEdgesData: (form) => {
            const data = form?.dataset?.edgesData;
            return data ? JSON.parse(data) : [];
        }
    };

})();

// Inicjalizuj po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
    EdgesModule.init();
});
```

---

## 6. Integracja z istniejącym systemem

### 6.1 Modyfikacja calculator.html

W sekcji `finishing-actions` (po linii 278), zmodyfikować przycisk:

```html
<!-- Przyciski do modali -->
<div class="finishing-actions">
    <button type="button" class="modal-trigger" id="openEdgesModal">
        + Dodaj obróbkę krawędzi
    </button>
</div>
```

Na końcu pliku (przed `</body>`), dodać include modala:

```html
{% include 'partials/edges_modal.html' %}

<!-- Dodać style i skrypt -->
<link rel="stylesheet" href="{{ url_for('calculator.static', filename='css/edges.css') }}">
<script src="{{ url_for('calculator.static', filename='js/edges.js') }}"></script>
```

### 6.2 Modyfikacja save_quote.js

W funkcji `collectQuoteData()`, dodać zbieranie danych krawędzi:

```javascript
// W pętli po formularzach produktów, dodać:
const edgesData = form.dataset.edgesData ? JSON.parse(form.dataset.edgesData) : [];
const edgesNetto = parseFloat(form.dataset.edgesNetto) || 0;
const edgesBrutto = parseFloat(form.dataset.edgesBrutto) || 0;

// Do obiektu produktu dodać:
product.edges = edgesData;
product.edges_netto = edgesNetto;
product.edges_brutto = edgesBrutto;
```

### 6.3 Modyfikacja calculator.js

W funkcji `updateGlobalSummary()`, dodać sumowanie kosztów krawędzi:

```javascript
// Po linii z sumFinishingBrutto += fBr:
const eBr = parseFloat(form.dataset.edgesBrutto) || 0;
const eNt = parseFloat(form.dataset.edgesNetto) || 0;
sumEdgesBrutto += eBr;
sumEdgesNetto += eNt;
```

---

## 7. Harmonogram implementacji

### Faza 1: Baza danych i Backend
1. [x] Utworzenie migracji SQL - **ZROBIONE** (`migrations/001_edges_feature.sql`)
2. [x] Modyfikacja modelu `QuoteItemDetails` - **ZROBIONE** (dodano kolumny edges_*)
3. [x] Usunięcie modelu `QuoteItemEdge` - **ZROBIONE** (zbędny po zmianie architektury)
4. [x] Utworzenie serwisu `services/edge_calculator.py` - **ZROBIONE**
5. [x] Dodanie endpointów API w `routers.py` - **ZROBIONE** (/api/edge-options, /api/edge-definitions, /api/calculate-edges)
6. [x] Modyfikacja `save_quote()` - **ZROBIONE** (zapis do QuoteItemDetails jako JSON)

### Faza 2: Frontend - HTML/CSS
1. [x] Utworzenie `templates/partials/edges_modal.html` - **ZROBIONE**
2. [x] Utworzenie `static/css/edges.css` - **ZROBIONE**
3. [x] Modyfikacja `calculator.html` - **ZROBIONE** (linie 11, 430, 435)

### Faza 3: Frontend - JavaScript
1. [x] Utworzenie `static/js/edges.js` - **ZROBIONE**
2. [x] Implementacja obsługi modala - **ZROBIONE**
3. [x] Implementacja kalkulacji ceny live - **ZROBIONE**
4. [x] Implementacja interakcji SVG - **ZROBIONE**
5. [x] Integracja z `save_quote.js` - **ZROBIONE** (linie 756-792)
6. [x] Integracja z `calculator.js` - **ZROBIONE** (sumEdgesBrutto/Netto w liniach 506-528)

### Faza 4: Wdrożenie i Testy
1. [ ] **WYMAGANE:** Uruchomienie migracji SQL na bazie danych (lokalnej i produkcyjnej)
2. [ ] Test otwierania/zamykania modala
3. [ ] Test zaznaczania krawędzi
4. [ ] Test kalkulacji ceny
5. [ ] Test zapisu do bazy
6. [ ] Test wyświetlania w wycenie

---

## Uwagi końcowe

1. **Ceny** - aktualnie hardkodowane (15 zł/mb, 5 zł/narożnik). Można przenieść do bazy danych i panelu admina.

2. **Wizualizacja SVG** - statyczna izometria. Można rozbudować o dynamiczne skalowanie proporcji na podstawie wymiarów produktu (jak w PrestaShop).

3. **Walidacja** - dodać walidację minimalnych/maksymalnych wartości R.

4. **Responsywność** - CSS uwzględnia podstawową responsywność, ale może wymagać dopracowania na urządzeniach mobilnych.

5. **Internacjonalizacja** - teksty po polsku. Jeśli potrzebna wielojęzyczność, przenieść do systemu tłumaczeń.

---

## 8. SQL do wykonania na serwerze produkcyjnym

**Data utworzenia:** 2026-01-19
**Status lokalnej bazy:** ✅ Zmigrowane

```sql
-- ============================================
-- MIGRACJA: Funkcjonalność obróbki krawędzi
-- Wykonaj na bazie produkcyjnej (crm.woodpower.pl)
-- ============================================

-- 1. Tabela słownikowa typów obróbki
CREATE TABLE IF NOT EXISTS edge_options (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    price_per_mb DECIMAL(10, 2) NOT NULL DEFAULT 0,
    corner_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    r_min INT DEFAULT NULL,
    r_max INT DEFAULT NULL,
    r_default INT DEFAULT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Dane początkowe dla edge_options
INSERT IGNORE INTO edge_options (type, name, price_per_mb, corner_price, r_min, r_max, r_default) VALUES
('sharp', 'Ostre', 0.00, 0.00, NULL, NULL, NULL),
('chamfer', 'Fazowanie', 15.00, 5.00, 3, 10, 3),
('round', 'Zaokrąglenie', 15.00, 5.00, 3, 20, 5);

-- 3. Rozszerzenie tabeli quote_items_details o kolumny krawędzi
ALTER TABLE quote_items_details ADD COLUMN edges_config JSON DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_type VARCHAR(32) DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_r_value INT DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_price_netto DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE quote_items_details ADD COLUMN edges_price_brutto DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE quote_items_details ADD COLUMN edges_svg TEXT DEFAULT NULL;

-- 4. Usunięcie starej tabeli (jeśli istnieje)
DROP TABLE IF EXISTS quote_item_edges;

-- 5. Weryfikacja
SELECT 'Migracja zakończona' AS status;
SELECT * FROM edge_options;
SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'quote_items_details' AND COLUMN_NAME LIKE 'edges%';
```

**UWAGA:** Jeśli któryś ALTER TABLE zwróci błąd "Duplicate column name", oznacza to że kolumna już istnieje - można zignorować ten błąd i kontynuować.
