# Strukturalna obróbka krawędzi — Plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodanie strukturalnych danych obróbki krawędzi (typ, promień, kąt, które krawędzie) do modułu produkcji z wizualizacją SVG na stanowiskach i kaskadowym pozyskiwaniem danych z QuoteItemDetails/PDF/parser.

**Architecture:** Hybrydowe podejście — dane strukturalne z QuoteItemDetails (zamówienia CRM, powiązane przez metadane PDF lub order_product_id) z fallbackiem na parser nazwy produktu (zamówienia sklepowe). Wizualizacja SVG izometrycznego generowana server-side w Pythonie dla prostokątów lub kopiowana z kalkulatora dla wielokątów.

**Tech Stack:** Python/Flask, SQLAlchemy, pypdf (metadane PDF), SVG (generowanie server-side), JavaScript (modal UI), CSS (badge/ikona)

**Spec:** `docs/superpowers/specs/2026-04-10-edge-processing-design.md`

---

## Struktura plików

### Nowe pliki
- `modules/production/services/edge_svg_generator.py` — generator izometrycznego SVG prostokąta
- `modules/production/static/js/stations/station-edge-modal.js` — obsługa modala krawędzi
- `migrations/XXX_edge_processing_structured.sql` — migracja DB

### Modyfikowane pliki
- `modules/production/models.py` — nowe pola w ProductionItem
- `modules/production/services/parser_service.py` — rozbudowa `_parse_edge_processing()`
- `modules/production/services/sync_service.py` — kaskada pozyskiwania danych
- `modules/production/routers/stations/interfaces.py` — nowe dane do frontendu
- `modules/production/static/icons/station-icons.svg` — nowa ikona prostopadłościanu
- `modules/production/templates/stations/cutting.html` — badge + ikona + modal (wzorzec dla innych stanowisk)
- `modules/production/static/css/stations/station-shared.css` — style badge/ikona/modal
- `modules/production/static/js/modules/products-module.js` — wyświetlanie danych krawędzi w modalu produktu
- `modules/calculator/models.py` — nowe pole `baselinker_order_product_id`
- `modules/baselinker/service.py` — zapis order_product_id po addOrder
- `modules/baselinker/edges_pdf_generator.py` — osadzanie metadanych JSON w PDF
- `requirements.txt` — dodanie pypdf

---

### Task 1: Migracja DB i model danych

**Files:**
- Modify: `modules/production/models.py:122-123`
- Modify: `modules/calculator/models.py:722-723`
- Create: `migrations/XXX_edge_processing_structured.sql`
- Modify: `requirements.txt`

- [ ] **Step 1: Dodaj pypdf do requirements.txt**

W `requirements.txt` dodaj na końcu:

```
pypdf>=4.0.0
```

- [ ] **Step 2: Zainstaluj zależność**

Run: `pip install pypdf>=4.0.0`

- [ ] **Step 3: Dodaj nowe pola do ProductionItem**

W `modules/production/models.py` po linii 123 (po `parsed_edge_processing`) dodaj:

```python
    parsed_edge_type = Column(String(20), nullable=True,
                              comment='Typ obróbki: zaokrąglenie / fazowanie')
    parsed_edge_radius = Column(Integer, nullable=True,
                                comment='Wartość promienia R (np. 3, 6, 30)')
    parsed_edge_angle = Column(Integer, nullable=True,
                               comment='Kąt fazowania w stopniach (30, 45, 60) — NULL dla zaokrąglenia')
    parsed_edge_letters = Column(JSON, nullable=True,
                                 comment='Lista krawędzi: ["A","B","N1"] lub ["G1","G2","P1"]')
    edge_svg = Column(Text, nullable=True,
                      comment='SVG izometryczny 3D z zaznaczonymi krawędziami')
    shape_svg = Column(Text, nullable=True,
                       comment='SVG kształtu 2D')
    quote_item_detail_id = Column(Integer, nullable=True,
                                  comment='ID powiązanego QuoteItemDetails — NULL dla zamówień sklepowych')
```

- [ ] **Step 4: Dodaj nowe pole do QuoteItemDetails**

W `modules/calculator/models.py` po linii 722 (po `edges_svg`) dodaj:

```python
    baselinker_order_product_id = db.Column(db.Integer, nullable=True,
                                            comment='ID produktu z BaseLinker getOrders — do matchowania z ProductionItem')
```

- [ ] **Step 5: Utwórz migrację SQL**

Utwórz `migrations/XXX_edge_processing_structured.sql`:

```sql
-- Migracja: Strukturalna obróbka krawędzi
-- Data: 2026-04-10

-- Nowe pola w prod_items (ProductionItem)
ALTER TABLE prod_items ADD COLUMN parsed_edge_type VARCHAR(20) DEFAULT NULL COMMENT 'Typ obróbki: zaokrąglenie / fazowanie';
ALTER TABLE prod_items ADD COLUMN parsed_edge_radius INT DEFAULT NULL COMMENT 'Wartość promienia R (np. 3, 6, 30)';
ALTER TABLE prod_items ADD COLUMN parsed_edge_angle INT DEFAULT NULL COMMENT 'Kąt fazowania w stopniach (30, 45, 60)';
ALTER TABLE prod_items ADD COLUMN parsed_edge_letters JSON DEFAULT NULL COMMENT 'Lista krawędzi JSON: ["A","B","N1"]';
ALTER TABLE prod_items ADD COLUMN edge_svg TEXT DEFAULT NULL COMMENT 'SVG izometryczny 3D z zaznaczonymi krawędziami';
ALTER TABLE prod_items ADD COLUMN shape_svg TEXT DEFAULT NULL COMMENT 'SVG kształtu 2D';
ALTER TABLE prod_items ADD COLUMN quote_item_detail_id INT DEFAULT NULL COMMENT 'ID powiązanego QuoteItemDetails';

-- Nowe pole w quote_items_details (QuoteItemDetails)
ALTER TABLE quote_items_details ADD COLUMN baselinker_order_product_id INT DEFAULT NULL COMMENT 'ID produktu z BaseLinker getOrders';
```

- [ ] **Step 6: Uruchom migrację lokalnie**

Run: `mysql -u root woodpower_crm_local < migrations/XXX_edge_processing_structured.sql`

Weryfikacja:

```bash
mysql -u root woodpower_crm_local -e "DESCRIBE prod_items" | grep -E "parsed_edge_type|parsed_edge_radius|parsed_edge_angle|parsed_edge_letters|edge_svg|shape_svg|quote_item_detail_id"
```

Expected: 7 wierszy z nowymi kolumnami.

- [ ] **Step 7: Commit**

```bash
git add modules/production/models.py modules/calculator/models.py migrations/XXX_edge_processing_structured.sql requirements.txt
git commit -m "feat(edge): add structured edge processing fields to ProductionItem and QuoteItemDetails"
```

---

### Task 2: Rozbudowa parsera nazwy

**Files:**
- Modify: `modules/production/services/parser_service.py:331-333, 523-547`

- [ ] **Step 1: Zastąp `_parse_edge_processing` nową wersją**

W `modules/production/services/parser_service.py` zastąp linie 523-547 (metoda `_parse_edge_processing`):

```python
    def _parse_edge_processing(self, name: str) -> dict:
        """
        Parsuje obróbkę krawędzi z nazwy produktu.

        Wykrywane wzorce:
          zaokrąglenie R3 (A)
          fazowanie R3 45° E, F, G, H
          zaokrąglenie R30 (N4, N2, N1, N3)
          zaokrąglenie R3 (G1, G2, G3, D1, D2, D3, P1, P2, P3)

        Returns:
            dict: {
                'has_edge': bool,
                'edge_type': str|None,
                'edge_radius': int|None,
                'edge_angle': int|None,
                'edge_letters': list|None
            }
        """
        import re

        result = {
            'has_edge': False,
            'edge_type': None,
            'edge_radius': None,
            'edge_angle': None,
            'edge_letters': None,
        }

        # Główny wzorzec: typ + R + opcjonalny kąt + krawędzie
        pattern = (
            r'(zaokr[aą]glenie|fazowanie)\s+'
            r'R(\d+)\s*'
            r'(?:(\d+)°\s*)?'
            r'[\(]?\s*'
            r'((?:[A-H]|[GDPN]\d+)(?:\s*,\s*(?:[A-H]|[GDPN]\d+))*)'
            r'\s*[\)]?'
        )

        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            result['has_edge'] = True
            edge_type_raw = match.group(1).lower()
            # Normalizacja: zaokraglenie → zaokrąglenie
            if edge_type_raw.startswith('zaokr'):
                result['edge_type'] = 'zaokrąglenie'
            else:
                result['edge_type'] = 'fazowanie'
            result['edge_radius'] = int(match.group(2))
            if match.group(3):
                result['edge_angle'] = int(match.group(3))
            # Parsuj krawędzie
            letters_raw = match.group(4)
            result['edge_letters'] = [l.strip() for l in letters_raw.split(',')]
            return result

        # Fallback: proste wykrywanie słów kluczowych (zachowanie wstecznej kompatybilności)
        edge_keywords = ['fazowanie', 'faza', 'frezowanie', 'kąt', 'zaokrąglenie', 'zaokraglenie']
        for keyword in edge_keywords:
            if keyword in name:
                result['has_edge'] = True
                return result

        if re.search(r'\bR\d+\b', name, re.IGNORECASE):
            result['has_edge'] = True

        return result
```

- [ ] **Step 2: Zaktualizuj miejsce wywołania parsera**

W `parser_service.py` zastąp linie 331-333:

```python
            # 5b. Parsowanie obróbki krawędzi (strukturalne)
            edge_data = self._parse_edge_processing(normalized_name)
            result['edge_processing'] = edge_data.get('has_edge', False)
            result['edge_type'] = edge_data.get('edge_type')
            result['edge_radius'] = edge_data.get('edge_radius')
            result['edge_angle'] = edge_data.get('edge_angle')
            result['edge_letters'] = edge_data.get('edge_letters')
```

- [ ] **Step 3: Zweryfikuj parser na przykładach**

Run: `python -c "
from modules.production.services.parser_service import ProductNameParser
parser = ProductNameParser()

tests = [
    'Klejonka jesionowa lita A/B 130.0×35.0×3.0 cm surowa zaokrąglenie R3 (A)',
    'Blat dębowy mikrowczep A/B 100x50x4 cm lakierowany bezbarwny fazowanie R3 45° E, F, G, H',
    'Klejonka bukowa lita A/B 90.0×90.0×3.0 cm surowa zaokrąglenie R30 (N4, N2, N1, N3)',
    'Klejonka dębowa mikrowczep B/B 80.0×60.0×4.0 cm surowa zaokrąglenie R3 (G1, G2, G3, D1, D2, D3, P1, P2, P3)',
    'Blat 180x80x3 cm dębowy lity A/B surowy',
]

for t in tests:
    r = parser.parse_product_name(t)
    print(f'edge={r.get(\"edge_processing\")}, type={r.get(\"edge_type\")}, R={r.get(\"edge_radius\")}, angle={r.get(\"edge_angle\")}, letters={r.get(\"edge_letters\")}')
    print(f'  -> {t[:60]}...')
    print()
"
`

Expected:
```
edge=True, type=zaokrąglenie, R=3, angle=None, letters=['A']
edge=True, type=fazowanie, R=3, angle=45, letters=['E', 'F', 'G', 'H']
edge=True, type=zaokrąglenie, R=30, angle=None, letters=['N4', 'N2', 'N1', 'N3']
edge=True, type=zaokrąglenie, R=3, angle=None, letters=['G1', 'G2', 'G3', 'D1', 'D2', 'D3', 'P1', 'P2', 'P3']
edge=False, type=None, R=None, angle=None, letters=None
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/services/parser_service.py
git commit -m "feat(edge): expand edge parser to return structured data (type, radius, angle, letters)"
```

---

### Task 3: Aktualizacja sync_service — zapis nowych pól z parsera

**Files:**
- Modify: `modules/production/services/sync_service.py:1218-1232`

- [ ] **Step 1: Rozszerz mapowanie parsed_data → product_data**

W `modules/production/services/sync_service.py` w metodzie `_prepare_product_data_enhanced`, zastąp linię 1230:

```python
            'parsed_edge_processing': parsed_data.get('edge_processing', False),
```

na:

```python
            'parsed_edge_processing': parsed_data.get('edge_processing', False),
            'parsed_edge_type': parsed_data.get('edge_type'),
            'parsed_edge_radius': parsed_data.get('edge_radius'),
            'parsed_edge_angle': parsed_data.get('edge_angle'),
            'parsed_edge_letters': parsed_data.get('edge_letters'),
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/services/sync_service.py
git commit -m "feat(edge): pass structured edge data from parser to ProductionItem"
```

---

### Task 4: Generator SVG izometrycznego prostokąta

**Files:**
- Create: `modules/production/services/edge_svg_generator.py`

- [ ] **Step 1: Utwórz EdgeSvgGenerator**

Utwórz `modules/production/services/edge_svg_generator.py`:

```python
"""
Generator SVG izometrycznego prostokąta z zaznaczonymi krawędziami.

Port logiki z modules/calculator/static/js/edges.js:generateRectPreviewSVG().
Używany jako fallback dla zamówień sklepowych (brak QuoteItemDetails).
"""


class EdgeSvgGenerator:
    """Generuje izometryczny SVG prostokąta z zaznaczonymi krawędziami."""

    # Kolory
    ACTIVE_COLOR = '#f59e0b'
    INACTIVE_COLOR = '#475569'
    FACE_FILL = 'rgba(148,163,184,0.05)'
    FACE_FILL_TOP = 'rgba(148,163,184,0.08)'
    LABEL_BG_ACTIVE = '#f59e0b'
    LABEL_BG_INACTIVE = '#2a2a3e'
    LABEL_TEXT_ACTIVE = '#fff'
    LABEL_TEXT_INACTIVE = '#94a3b8'

    # Wektory projekcji izometrycznej (te same co w edges.js)
    ISO_X = (0.95, 0.0)     # oś X kształtu → ekran
    ISO_Y = (-0.36, -0.75)  # oś Y kształtu → ekran
    ISO_Z = (0.04, 0.65)    # oś Z (grubość) → ekran

    # Definicje krawędzi prostokąta: nazwa → (punkt_start, punkt_end) w lokalnych współrzędnych
    # Współrzędne: (x_factor, y_factor, z_factor) gdzie factor to mnożnik wymiaru (L, W, T)
    EDGE_DEFS = {
        # Górne (z=0)
        'A': {'start': (0, 0, 0), 'end': (1, 0, 0), 'label_pos': 0.5},      # góra przednia (długość)
        'B': {'start': (0, 1, 0), 'end': (1, 1, 0), 'label_pos': 0.5},      # góra tylna (długość)
        'C': {'start': (0, 0, 0), 'end': (0, 1, 0), 'label_pos': 0.5},      # góra lewa (szerokość)
        'D': {'start': (1, 0, 0), 'end': (1, 1, 0), 'label_pos': 0.5},      # góra prawa (szerokość)
        # Dolne (z=1)
        'E': {'start': (0, 0, 1), 'end': (1, 0, 1), 'label_pos': 0.5},      # dół przednia
        'F': {'start': (0, 1, 1), 'end': (1, 1, 1), 'label_pos': 0.5},      # dół tylna
        'G': {'start': (0, 0, 1), 'end': (0, 1, 1), 'label_pos': 0.5},      # dół lewa
        'H': {'start': (1, 0, 1), 'end': (1, 1, 1), 'label_pos': 0.5},      # dół prawa
        # Narożniki pionowe (grubość)
        'N1': {'start': (0, 0, 0), 'end': (0, 0, 1), 'label_pos': 0.5},     # przedni lewy
        'N2': {'start': (1, 0, 0), 'end': (1, 0, 1), 'label_pos': 0.5},     # przedni prawy
        'N3': {'start': (1, 1, 0), 'end': (1, 1, 1), 'label_pos': 0.5},     # tylny prawy
        'N4': {'start': (0, 1, 0), 'end': (0, 1, 1), 'label_pos': 0.5},     # tylny lewy
    }

    def _project(self, x, y, z, length, width, thickness):
        """Rzutuje punkt 3D (w jednostkach kształtu) na 2D izometryczne."""
        px = x * length
        py = y * width
        pz = z * thickness

        screen_x = px * self.ISO_X[0] + py * self.ISO_Y[0] + pz * self.ISO_Z[0]
        screen_y = px * self.ISO_X[1] + py * self.ISO_Y[1] + pz * self.ISO_Z[1]

        return screen_x, screen_y

    def generate(self, length_cm, width_cm, thickness_cm, active_edges):
        """
        Generuje SVG izometrycznego prostokąta.

        Args:
            length_cm: długość w cm
            width_cm: szerokość w cm
            thickness_cm: grubość w cm
            active_edges: lista aktywnych krawędzi np. ['A', 'B', 'N1']

        Returns:
            str: SVG jako string
        """
        active_set = set(active_edges or [])

        # Normalizuj wymiary do rozmiaru SVG (max ~200px)
        max_dim = max(length_cm, width_cm, thickness_cm * 5, 1)
        scale = 150 / max_dim
        L = length_cm * scale
        W = width_cm * scale
        T = max(thickness_cm * scale, 8)  # min grubość żeby była widoczna

        # Oblicz wszystkie 8 wierzchołków prostopadłościanu
        corners = {}
        for name, (xf, yf, zf) in [
            ('TFL', (0, 0, 0)), ('TFR', (1, 0, 0)),
            ('TBR', (1, 1, 0)), ('TBL', (0, 1, 0)),
            ('BFL', (0, 0, 1)), ('BFR', (1, 0, 1)),
            ('BBR', (1, 1, 1)), ('BBL', (0, 1, 1)),
        ]:
            corners[name] = self._project(xf, yf, zf, L, W, T)

        # Oblicz bounding box i przesuń do viewBox
        all_x = [c[0] for c in corners.values()]
        all_y = [c[1] for c in corners.values()]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        padding = 30  # miejsce na labelki
        vb_w = max_x - min_x + padding * 2
        vb_h = max_y - min_y + padding * 2
        ox = -min_x + padding
        oy = -min_y + padding

        def p(name):
            x, y = corners[name]
            return x + ox, y + oy

        def fmt(x, y):
            return f'{x:.1f},{y:.1f}'

        # Buduj SVG
        parts = []
        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.0f} {vb_h:.0f}">')

        # Ściany (tył, lewa, góra, przód, prawa) — kolejność rysowania od tyłu
        faces = [
            ('back',  ['TBL', 'TBR', 'BBR', 'BBL'], self.FACE_FILL),
            ('left',  ['TBL', 'TFL', 'BFL', 'BBL'], self.FACE_FILL),
            ('top',   ['TFL', 'TFR', 'TBR', 'TBL'], self.FACE_FILL_TOP),
            ('front', ['TFL', 'TFR', 'BFR', 'BFL'], self.FACE_FILL),
            ('right', ['TFR', 'TBR', 'BBR', 'BFR'], self.FACE_FILL),
        ]

        for face_name, verts, fill in faces:
            points = ' '.join(fmt(*p(v)) for v in verts)
            parts.append(
                f'<polygon points="{points}" fill="{fill}" '
                f'stroke="{self.INACTIVE_COLOR}" stroke-width="1" opacity="0.6"/>'
            )

        # Krawędzie
        for edge_name, edge_def in self.EDGE_DEFS.items():
            sx, sy, sz = edge_def['start']
            ex, ey, ez = edge_def['end']

            x1, y1 = self._project(sx, sy, sz, L, W, T)
            x2, y2 = self._project(ex, ey, ez, L, W, T)
            x1 += ox; y1 += oy
            x2 += ox; y2 += oy

            is_active = edge_name in active_set
            color = self.ACTIVE_COLOR if is_active else self.INACTIVE_COLOR
            width = 3 if is_active else 1.5
            opacity = '' if is_active else ' opacity="0.6"'

            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"{opacity}/>'
            )

        # Labelki
        label_r = 11
        for edge_name, edge_def in self.EDGE_DEFS.items():
            sx, sy, sz = edge_def['start']
            ex, ey, ez = edge_def['end']
            t = edge_def['label_pos']

            mx = sx + (ex - sx) * t
            my = sy + (ey - sy) * t
            mz = sz + (ez - sz) * t

            lx, ly = self._project(mx, my, mz, L, W, T)
            lx += ox; ly += oy

            is_active = edge_name in active_set
            bg = self.LABEL_BG_ACTIVE if is_active else self.LABEL_BG_INACTIVE
            tc = self.LABEL_TEXT_ACTIVE if is_active else self.LABEL_TEXT_INACTIVE
            stroke = '' if is_active else f' stroke="{self.INACTIVE_COLOR}" stroke-width="1"'

            parts.append(
                f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{label_r}" fill="{bg}"{stroke}/>'
            )
            font_size = 8 if len(edge_name) > 1 else 9
            parts.append(
                f'<text x="{lx:.1f}" y="{ly + 3:.1f}" text-anchor="middle" '
                f'fill="{tc}" font-size="{font_size}" font-weight="bold" '
                f'font-family="Arial,sans-serif">{edge_name}</text>'
            )

        parts.append('</svg>')
        return '\n'.join(parts)
```

- [ ] **Step 2: Zweryfikuj generator**

Run: `python -c "
from modules.production.services.edge_svg_generator import EdgeSvgGenerator
gen = EdgeSvgGenerator()
svg = gen.generate(180, 80, 3, ['A', 'E', 'N1', 'N2'])
print(svg[:200])
print('...')
print(f'Total length: {len(svg)} chars')
assert '<svg' in svg
assert 'f59e0b' in svg  # active color
assert '</svg>' in svg
print('OK')
"
`

- [ ] **Step 3: Commit**

```bash
git add modules/production/services/edge_svg_generator.py
git commit -m "feat(edge): add server-side isometric rectangle SVG generator"
```

---

### Task 5: Metadane JSON w PDF specyfikacji

**Files:**
- Modify: `modules/baselinker/edges_pdf_generator.py:44-60`

- [ ] **Step 1: Dodaj osadzanie metadanych po generowaniu PDF**

W `modules/baselinker/edges_pdf_generator.py` zastąp metodę `generate_pdf` (linie 44-60):

```python
    def generate_pdf(self, products: list, quote_number: str = '', quote_id: int = None) -> bytes:
        """
        Generuje PDF specyfikacji produktów z osadzonymi metadanymi.

        Args:
            products: Lista słowników z danymi produktów
            quote_number: Numer wyceny
            quote_id: ID wyceny (do metadanych)

        Returns:
            bytes: Zawartość PDF jako bajty
        """
        html_content = self._generate_html(products, quote_number)

        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.read()

        # Osadź metadane z mapowaniem produktów
        pdf_bytes = self._embed_metadata(pdf_bytes, products, quote_id)

        return pdf_bytes

    def _embed_metadata(self, pdf_bytes: bytes, products: list, quote_id: int = None) -> bytes:
        """Osadza JSON z mapowaniem produktów w metadanych PDF."""
        import json
        from pypdf import PdfReader, PdfWriter

        items_meta = []
        for product in products:
            item = {
                'position': product.get('product_index'),
                'detail_id': product.get('detail_id'),
                'sku': product.get('sku'),
            }
            items_meta.append(item)

        meta_json = json.dumps({
            'quote_id': quote_id,
            'items': items_meta,
        }, ensure_ascii=False)

        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        writer.add_metadata({
            '/WoodPowerMeta': meta_json,
        })

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return output.read()
```

- [ ] **Step 2: Zaktualizuj `generate_pdf_base64` — przekaż quote_id**

W tym samym pliku, zastąp metodę `generate_pdf_base64` (linie 62-75):

```python
    def generate_pdf_base64(self, products: list, quote_number: str = '', quote_id: int = None) -> dict:
        """
        Generuje PDF i zwraca w formacie dla BaseLinker API.

        Returns:
            dict: {'title': 'filename.pdf', 'file': 'data:base64_content...'}
        """
        pdf_bytes = self.generate_pdf(products, quote_number, quote_id)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        return {
            'title': 'specyfikacja.pdf',
            'file': f'data:{pdf_base64}'
        }
```

- [ ] **Step 3: Commit**

```bash
git add modules/baselinker/edges_pdf_generator.py
git commit -m "feat(edge): embed WoodPowerMeta JSON in specification PDF metadata"
```

---

### Task 6: Zapis order_product_id po addOrder + przekazanie quote_id/detail_id do PDF

**Files:**
- Modify: `modules/baselinker/service.py:411-430, 891-907`

- [ ] **Step 1: Przekaż detail_id i sku do spec_products**

W `modules/baselinker/service.py` znajdź pętlę budującą `spec_products` (około linii 880-889). Dodaj `detail_id`, `sku` i `product_index` do każdego `product_data`:

Przed linią `spec_products.append(product_data)` (linia 889) dodaj:

```python
            'detail_id': finishing_details.id if finishing_details else None,
            'sku': sku,
            'product_index': i + 1,
```

- [ ] **Step 2: Przekaż quote_id do generate_pdf_base64**

W linii 897 zmień wywołanie:

```python
            pdf_data = pdf_generator.generate_pdf_base64(spec_products, quote_number=quote.quote_number, quote_id=quote.id)
```

- [ ] **Step 3: Dodaj zapis order_product_id po addOrder**

Po bloku `if response.get('status') == 'SUCCESS':` (linia 411), po `db.session.commit()` (linia 425), dodaj:

```python
                    # Zapisz order_product_id w QuoteItemDetails
                    self._save_order_product_ids(quote, baselinker_order_id)
```

Dodaj nową metodę w klasie `BaselinkerService`:

```python
    def _save_order_product_ids(self, quote, baselinker_order_id):
        """Po addOrder odpytuje getOrders i zapisuje order_product_id w QuoteItemDetails."""
        try:
            from modules.calculator.models import QuoteItemDetails

            response = self._make_request('getOrders', {
                'order_id': baselinker_order_id,
            })

            if response.get('status') != 'SUCCESS':
                self.logger.warning("Nie udało się pobrać zamówienia po addOrder",
                                   baselinker_order_id=baselinker_order_id)
                return

            orders = response.get('orders', [])
            if not orders:
                return

            bl_products = orders[0].get('products', [])

            # Pobierz QuoteItemDetails dla tego quote
            details = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()

            # Matchuj po SKU
            details_by_sku = {}
            for detail in details:
                sku = self._generate_sku_for_detail(detail)
                if sku:
                    details_by_sku[sku] = detail

            matched = 0
            for bl_product in bl_products:
                bl_sku = bl_product.get('sku', '')
                if bl_sku in details_by_sku:
                    details_by_sku[bl_sku].baselinker_order_product_id = int(bl_product['order_product_id'])
                    matched += 1

            if matched > 0:
                db.session.commit()
                self.logger.info("Zapisano order_product_id",
                               matched=matched,
                               total_bl=len(bl_products),
                               total_details=len(details))

        except Exception as e:
            self.logger.error("Błąd zapisu order_product_id", error=str(e))

    def _generate_sku_for_detail(self, detail):
        """Generuje SKU dla QuoteItemDetails (uproszczony — taki sam jak _generate_sku)."""
        try:
            from modules.calculator.models import QuoteItem
            item = QuoteItem.query.filter_by(
                quote_id=detail.quote_id,
                product_index=detail.product_index
            ).first()
            if item:
                return self._generate_sku(item, detail)
        except Exception:
            pass
        return None
```

- [ ] **Step 4: Commit**

```bash
git add modules/baselinker/service.py
git commit -m "feat(edge): save order_product_id after addOrder and pass metadata to PDF"
```

---

### Task 7: Kaskada danych przy imporcie do produkcji

**Files:**
- Modify: `modules/production/services/sync_service.py:1206-1232`

- [ ] **Step 1: Dodaj metodę wzbogacania danych krawędzi**

W `modules/production/services/sync_service.py` dodaj nową metodę w klasie `SyncService`:

```python
    def _enrich_edge_data_from_quote(self, product_data, order_data):
        """
        Kaskada wzbogacania danych krawędzi z QuoteItemDetails.
        Poziom 1: Metadane PDF → Poziom 2: order_product_id → Poziom 3: parser (już w product_data)
        """
        if not product_data.get('parsed_edge_processing'):
            return product_data

        import json
        import io
        import requests

        detail = None
        baselinker_order_id = product_data.get('baselinker_order_id')

        # Poziom 1: Metadane PDF
        detail = self._try_match_via_pdf(order_data, product_data)

        # Poziom 2: order_product_id
        if not detail:
            detail = self._try_match_via_order_product_id(
                baselinker_order_id,
                product_data.get('baselinker_product_id')
            )

        # Jeśli znaleziono QuoteItemDetails — kopiuj dane
        if detail:
            if detail.edges_type:
                edge_type_map = {'round': 'zaokrąglenie', 'chamfer': 'fazowanie'}
                product_data['parsed_edge_type'] = edge_type_map.get(detail.edges_type, detail.edges_type)
            if detail.edges_r_value:
                product_data['parsed_edge_radius'] = detail.edges_r_value
            if detail.edges_angle_value:
                product_data['parsed_edge_angle'] = detail.edges_angle_value
            if detail.edges_config:
                product_data['parsed_edge_letters'] = [
                    e.get('letter') for e in detail.edges_config if e.get('letter')
                ]
            if detail.edges_svg:
                product_data['edge_svg'] = detail.edges_svg
            if detail.shape_svg:
                product_data['shape_svg'] = detail.shape_svg
            product_data['quote_item_detail_id'] = detail.id

            logger.info("Wzbogacono dane krawędzi z QuoteItemDetails",
                       extra={'detail_id': detail.id, 'source': 'quote'})
        else:
            # Poziom 3: Generuj SVG z parsera (tylko prostokąty)
            if product_data.get('parsed_edge_letters'):
                self._generate_fallback_svg(product_data)

        return product_data

    def _try_match_via_pdf(self, order_data, product_data):
        """Próbuje powiązać przez metadane PDF z załącznika zamówienia."""
        import io
        import json

        try:
            from modules.calculator.models import QuoteItemDetails

            # Szukaj linku do PDF specyfikacji w custom_extra_fields
            custom_fields = order_data.get('custom_extra_fields', {})
            pdf_url = None
            for field_id, value in custom_fields.items():
                if isinstance(value, str) and value.endswith('.pdf'):
                    pdf_url = value
                    break

            if not pdf_url:
                return None

            import requests
            from pypdf import PdfReader

            response = requests.get(pdf_url, timeout=15)
            if response.status_code != 200:
                return None

            reader = PdfReader(io.BytesIO(response.content))
            meta = reader.metadata
            woodpower_meta = meta.get('/WoodPowerMeta') if meta else None

            if not woodpower_meta:
                return None

            meta_data = json.loads(woodpower_meta)
            items = meta_data.get('items', [])

            # Znajdź detail_id dla tego produktu (po pozycji)
            sequence = product_data.get('product_sequence_in_order', 1)
            for item in items:
                if item.get('position') == sequence:
                    detail_id = item.get('detail_id')
                    if detail_id:
                        return QuoteItemDetails.query.get(detail_id)

        except Exception as e:
            logger.warning("Błąd odczytu metadanych PDF", extra={'error': str(e)})

        return None

    def _try_match_via_order_product_id(self, baselinker_order_id, baselinker_product_id):
        """Próbuje powiązać przez order_product_id."""
        if not baselinker_product_id:
            return None

        try:
            from modules.calculator.models import QuoteItemDetails, Quote

            # Znajdź quote z tym baselinker_order_id
            quote = Quote.query.filter_by(
                base_linker_order_id=str(baselinker_order_id)
            ).first()

            if not quote:
                return None

            # Szukaj QuoteItemDetails z tym order_product_id
            detail = QuoteItemDetails.query.filter_by(
                quote_id=quote.id,
                baselinker_order_product_id=int(baselinker_product_id)
            ).first()

            return detail

        except Exception as e:
            logger.warning("Błąd matchowania order_product_id", extra={'error': str(e)})

        return None

    def _generate_fallback_svg(self, product_data):
        """Generuje SVG prostokąta z parsera (fallback dla zamówień sklepowych)."""
        try:
            from modules.production.services.edge_svg_generator import EdgeSvgGenerator

            length = float(product_data.get('parsed_length_cm') or 0)
            width = float(product_data.get('parsed_width_cm') or 0)
            thickness = float(product_data.get('parsed_thickness_cm') or 0)

            if length > 0 and width > 0 and thickness > 0:
                generator = EdgeSvgGenerator()
                product_data['edge_svg'] = generator.generate(
                    length, width, thickness,
                    product_data.get('parsed_edge_letters', [])
                )
        except Exception as e:
            logger.warning("Błąd generowania fallback SVG", extra={'error': str(e)})
```

- [ ] **Step 2: Wywołaj wzbogacanie po zbudowaniu product_data**

W metodzie `_prepare_product_data_enhanced`, po bloku `if parsed_data:` (po linii ~1232), dodaj:

```python
        # Wzbogać dane krawędzi z QuoteItemDetails (kaskada)
        product_data = self._enrich_edge_data_from_quote(product_data, order)
```

- [ ] **Step 3: Commit**

```bash
git add modules/production/services/sync_service.py
git commit -m "feat(edge): add cascading edge data enrichment from QuoteItemDetails/PDF/parser"
```

---

### Task 8: Aktualizacja interfaces.py — nowe dane do frontendu

**Files:**
- Modify: `modules/production/routers/stations/interfaces.py:14-38, 858, 906-907`

- [ ] **Step 1: Usuń `_extract_edge_description` (linie 14-38)**

Usuń całą funkcję `_extract_edge_description` — nie jest już potrzebna, bo dane są w DB.

- [ ] **Step 2: Zastąp linię 858**

Zamień:

```python
        edge_description = _extract_edge_description(product.original_product_name) if product.parsed_edge_processing else None
```

na:

```python
        # Buduj edge_description z danych strukturalnych
        edge_description = None
        if product.parsed_edge_processing and product.parsed_edge_type:
            parts = [product.parsed_edge_type.capitalize()]
            if product.parsed_edge_radius:
                parts.append(f'R{product.parsed_edge_radius}')
            if product.parsed_edge_angle:
                parts.append(f'{product.parsed_edge_angle}°')
            edge_description = ' '.join(parts)
```

- [ ] **Step 3: Dodaj nowe pola do product_data dict**

W dict `product_data` (po linii 907) dodaj:

```python
            'parsed_edge_type': product.parsed_edge_type,
            'parsed_edge_radius': product.parsed_edge_radius,
            'parsed_edge_angle': product.parsed_edge_angle,
            'parsed_edge_letters': product.parsed_edge_letters,
            'edge_svg': product.edge_svg,
            'shape_svg': product.shape_svg,
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/routers/stations/interfaces.py
git commit -m "feat(edge): replace ad-hoc edge description with structured data in station interface"
```

---

### Task 9: Ikona SVG prostopadłościanu

**Files:**
- Modify: `modules/production/static/icons/station-icons.svg`

- [ ] **Step 1: Dodaj symbol icon-edge do station-icons.svg**

Przed zamykającym `</svg>` dodaj:

```xml
  <!-- Edge processing / isometric cube icon -->
  <symbol id="icon-edge" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 2L3 7v10l9 5 9-5V7l-9-5z"/>
    <path d="M12 22V12"/>
    <path d="M12 12L3 7"/>
    <path d="M12 12l9-5"/>
  </symbol>
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/static/icons/station-icons.svg
git commit -m "feat(edge): add isometric cube icon for edge processing"
```

---

### Task 10: CSS — badge, ikona, modal

**Files:**
- Modify: `modules/production/static/css/stations/station-shared.css`

- [ ] **Step 1: Dodaj styl badge'a obróbki krawędzi**

Po `.badge-finish` (linia ~331) dodaj:

```css
/* Obróbka krawędzi - pomarańczowy */
.badge-edge {
    background: rgba(245, 158, 11, 0.15);
    border-color: rgba(245, 158, 11, 0.3);
    color: #f59e0b;
}
```

- [ ] **Step 2: Dodaj styl ikony krawędzi**

Po `.attachment-icon-wrapper:hover .attachment-icon` (linia ~929) dodaj:

```css
/* Ikona obróbki krawędzi */
.edge-icon-wrapper {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    position: relative;
    padding: 4px;
    border-radius: 0;
    color: #f59e0b;
}

.edge-icon-wrapper:hover {
    background-color: rgba(245, 158, 11, 0.1);
}

.edge-icon-wrapper .header-icon {
    stroke: #f59e0b;
}

.edge-icon-wrapper:hover .header-icon {
    stroke: #fbbf24;
}
```

- [ ] **Step 3: Dodaj style modala krawędzi**

Po stylach `#notesModal` dodaj:

```css
/* ============================================================================
   EDGE PROCESSING MODAL
   ============================================================================ */

#edgeModal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background-color: rgba(0, 0, 0, 0.9);
    z-index: 100000;
    justify-content: center;
    align-items: center;
}

#edgeModal.show {
    display: flex;
}

.edge-modal-content {
    background-color: var(--bg-primary, #12121f);
    border: 1px solid var(--border-color, #2a2a3e);
    border-radius: 0;
    max-width: 700px;
    width: 90vw;
    max-height: 90vh;
    overflow-y: auto;
    padding: 24px;
}

.edge-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border-color, #2a2a3e);
}

.edge-modal-header h3 {
    color: var(--text-primary, #f1f5f9);
    margin: 0;
    font-size: 16px;
}

.edge-modal-close {
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: var(--text-secondary, #64748b);
    font-size: 24px;
    background: none;
    border: none;
}

.edge-modal-close:hover {
    color: var(--text-primary, #f1f5f9);
}

.edge-modal-previews {
    display: flex;
    gap: 16px;
    margin-bottom: 20px;
}

.edge-modal-preview {
    flex: 1;
    background: var(--bg-secondary, #1a1a2e);
    border-radius: 0;
    padding: 16px;
    text-align: center;
}

.edge-modal-preview-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-secondary, #64748b);
    margin-bottom: 12px;
    font-weight: 600;
}

.edge-modal-preview svg,
.edge-modal-preview img {
    max-width: 100%;
    max-height: 200px;
}

.edge-modal-info {
    background: var(--bg-secondary, #1a1a2e);
    border-radius: 0;
    padding: 16px;
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 16px;
}

.edge-modal-info-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-secondary, #64748b);
    margin-bottom: 4px;
}

.edge-modal-info-value {
    color: var(--text-primary, #f1f5f9);
    font-size: 14px;
    font-weight: 600;
}

.edge-modal-info-value.accent {
    color: #f59e0b;
}
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/static/css/stations/station-shared.css
git commit -m "feat(edge): add CSS for edge badge, icon, and modal"
```

---

### Task 11: HTML — badge + ikona + modal w template stanowiska

**Files:**
- Modify: `modules/production/templates/stations/cutting.html`

- [ ] **Step 1: Dodaj badge obróbki krawędzi w product-params**

Znajdź sekcję `.product-params` w cutting.html. Po ostatnim badge (np. `badge-class`) dodaj:

```html
      {% if product.parsed_edge_processing and product.parsed_edge_type %}
        <span class="badge badge-edge">
          {{ product.parsed_edge_type|capitalize }}
          {% if product.parsed_edge_radius %}R{{ product.parsed_edge_radius }}{% endif %}
          {% if product.parsed_edge_angle %}{{ product.parsed_edge_angle }}°{% endif %}
        </span>
      {% endif %}
```

- [ ] **Step 2: Dodaj ikonę krawędzi w order-icons**

W sekcji `.order-icons`, przed ikoną attachment dodaj:

```html
      {% if product.parsed_edge_processing %}
        <div class="header-icon-wrapper edge-icon-wrapper"
             data-edge-type="{{ product.parsed_edge_type or '' }}"
             data-edge-radius="{{ product.parsed_edge_radius or '' }}"
             data-edge-angle="{{ product.parsed_edge_angle or '' }}"
             data-edge-letters="{{ product.parsed_edge_letters|tojson if product.parsed_edge_letters else '[]' }}"
             data-edge-svg="{{ product.edge_svg or '' }}"
             data-shape-svg="{{ product.shape_svg or '' }}"
             data-product-id="{{ product.id }}">
          <svg class="header-icon" width="22" height="22"><use href="#icon-edge"/></svg>
        </div>
      {% endif %}
```

- [ ] **Step 3: Dodaj modal HTML**

Przed zamykającym `{% endblock %}` dodaj:

```html
<!-- Modal obróbki krawędzi -->
<div id="edgeModal">
  <div class="edge-modal-content">
    <div class="edge-modal-header">
      <h3 id="edgeModalTitle">Obróbka krawędzi</h3>
      <button class="edge-modal-close" onclick="closeEdgeModal()">&times;</button>
    </div>
    <div class="edge-modal-previews">
      <div class="edge-modal-preview" id="edgeModalShape">
        <div class="edge-modal-preview-label">Kształt</div>
        <div id="edgeModalShapeContent"></div>
      </div>
      <div class="edge-modal-preview" id="edgeModalIsometric">
        <div class="edge-modal-preview-label">Izometria</div>
        <div id="edgeModalIsometricContent"></div>
      </div>
    </div>
    <div class="edge-modal-info">
      <div>
        <div class="edge-modal-info-label">Typ obróbki</div>
        <div class="edge-modal-info-value accent" id="edgeModalType"></div>
      </div>
      <div>
        <div class="edge-modal-info-label">Promień</div>
        <div class="edge-modal-info-value" id="edgeModalRadius"></div>
      </div>
      <div>
        <div class="edge-modal-info-label">Krawędzie</div>
        <div class="edge-modal-info-value" id="edgeModalLetters"></div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Dodaj script tag**

Przed zamykającym `{% endblock %}` (po modalu) dodaj:

```html
<script src="{{ url_for('production.static', filename='js/stations/station-edge-modal.js') }}"></script>
```

- [ ] **Step 5: Commit**

```bash
git add modules/production/templates/stations/cutting.html
git commit -m "feat(edge): add edge badge, icon and modal to cutting station template"
```

---

### Task 12: JavaScript — obsługa modala krawędzi

**Files:**
- Create: `modules/production/static/js/stations/station-edge-modal.js`

- [ ] **Step 1: Utwórz station-edge-modal.js**

```javascript
/**
 * Modal obróbki krawędzi na stanowiskach produkcji.
 * Obsługuje kliknięcie ikony prostopadłościanu → otwiera modal z SVG i danymi.
 */
(function() {
    'use strict';

    const modal = document.getElementById('edgeModal');
    if (!modal) return;

    // Inicjalizacja handlerów
    function initializeEdgeHandlers() {
        document.querySelectorAll('.edge-icon-wrapper').forEach(function(wrapper) {
            wrapper.addEventListener('click', function(e) {
                e.stopPropagation();
                openEdgeModal(this);
            });
        });
    }

    function openEdgeModal(wrapper) {
        const productId = wrapper.dataset.productId;
        const edgeType = wrapper.dataset.edgeType;
        const edgeRadius = wrapper.dataset.edgeRadius;
        const edgeAngle = wrapper.dataset.edgeAngle;
        const edgeSvg = wrapper.dataset.edgeSvg;
        const shapeSvg = wrapper.dataset.shapeSvg;

        var edgeLetters;
        try {
            edgeLetters = JSON.parse(wrapper.dataset.edgeLetters || '[]');
        } catch(e) {
            edgeLetters = [];
        }

        // Tytuł
        document.getElementById('edgeModalTitle').textContent =
            'Obróbka krawędzi — #' + productId;

        // Typ obróbki
        var typeText = edgeType ? (edgeType.charAt(0).toUpperCase() + edgeType.slice(1)) : '—';
        document.getElementById('edgeModalType').textContent = typeText;

        // Promień
        var radiusText = edgeRadius ? ('R' + edgeRadius) : '—';
        if (edgeAngle) {
            radiusText += ' ' + edgeAngle + '°';
        }
        document.getElementById('edgeModalRadius').textContent = radiusText;

        // Krawędzie
        document.getElementById('edgeModalLetters').textContent =
            edgeLetters.length > 0 ? edgeLetters.join(', ') : '—';

        // SVG kształtu
        var shapeContainer = document.getElementById('edgeModalShapeContent');
        var shapePreview = document.getElementById('edgeModalShape');
        if (shapeSvg) {
            shapeContainer.innerHTML = shapeSvg;
            shapePreview.style.display = '';
        } else {
            shapePreview.style.display = 'none';
        }

        // SVG izometrii
        var isoContainer = document.getElementById('edgeModalIsometricContent');
        var isoPreview = document.getElementById('edgeModalIsometric');
        if (edgeSvg) {
            isoContainer.innerHTML = edgeSvg;
            isoPreview.style.display = '';
        } else {
            isoPreview.style.display = 'none';
        }

        modal.classList.add('show');
    }

    function closeEdgeModal() {
        modal.classList.remove('show');
    }

    // Zamknięcie na ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('show')) {
            closeEdgeModal();
        }
    });

    // Zamknięcie na kliknięcie tła
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeEdgeModal();
        }
    });

    // Globalne funkcje
    window.closeEdgeModal = closeEdgeModal;
    window.initializeEdgeHandlers = initializeEdgeHandlers;

    // Hook do refresha (po przeładowaniu kart)
    if (typeof window.stationRefreshHooks !== 'undefined') {
        window.stationRefreshHooks.push(initializeEdgeHandlers);
    }

    // Init
    initializeEdgeHandlers();
})();
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/static/js/stations/station-edge-modal.js
git commit -m "feat(edge): add edge processing modal JavaScript handler"
```

---

### Task 13: Aktualizacja products-module.js — szczegóły krawędzi w modalu produktu

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js:3578-3591`

- [ ] **Step 1: Rozszerz wyświetlanie danych krawędzi w modalu produktu**

Zastąp blok obsługi `edge-processing-field-group` (linie 3578-3591):

```javascript
        // Obsługa pola obróbki krawędzi
        const edgeFieldGroup = modalElement.querySelector('#edge-processing-field-group');
        if (edgeFieldGroup) {
            if (product.parsed_edge_processing) {
                edgeFieldGroup.style.display = '';
                const edgeValue = edgeFieldGroup.querySelector('[data-field="parsed_edge_processing"]');
                if (edgeValue) {
                    var edgeText = '';
                    if (product.parsed_edge_type) {
                        edgeText = product.parsed_edge_type.charAt(0).toUpperCase() + product.parsed_edge_type.slice(1);
                        if (product.parsed_edge_radius) {
                            edgeText += ' R' + product.parsed_edge_radius;
                        }
                        if (product.parsed_edge_angle) {
                            edgeText += ' ' + product.parsed_edge_angle + '°';
                        }
                        if (product.parsed_edge_letters && product.parsed_edge_letters.length > 0) {
                            edgeText += ' (' + product.parsed_edge_letters.join(', ') + ')';
                        }
                    } else {
                        edgeText = 'Tak';
                    }
                    edgeValue.textContent = edgeText;
                    edgeValue.classList.add('text-success');
                }
            } else {
                edgeFieldGroup.style.display = 'none';
            }
        }
```

- [ ] **Step 2: Commit**

```bash
git add modules/production/static/js/modules/products-module.js
git commit -m "feat(edge): show structured edge data in product detail modal"
```

---

### Task 14: Propagacja na pozostałe stanowiska

**Files:**
- Modify: Inne szablony stanowisk w `modules/production/templates/stations/`

- [ ] **Step 1: Zidentyfikuj wszystkie szablony stanowisk**

Run: `ls modules/production/templates/stations/*.html`

Każdy szablon stanowiska powinien zawierać te same zmiany co cutting.html:
- Badge w `.product-params`
- Ikona w `.order-icons`
- Modal HTML + script tag

- [ ] **Step 2: Dodaj badge, ikonę i modal do każdego szablonu**

Dla każdego szablonu stanowiska (np. `gluing.html`, `finishing.html`, `sanding.html` itd.) dodaj identyczne bloki jak w Task 11 (badge, ikona, modal, script tag).

Użyj tych samych warunków:
- Badge: `{% if product.parsed_edge_processing and product.parsed_edge_type %}`
- Ikona: `{% if product.parsed_edge_processing %}`
- Modal i script: na końcu bloku content

- [ ] **Step 3: Commit**

```bash
git add modules/production/templates/stations/
git commit -m "feat(edge): propagate edge badge, icon and modal to all station templates"
```

---

### Task 15: Weryfikacja end-to-end

- [ ] **Step 1: Uruchom aplikację lokalnie**

Run: `python -m flask run --host=127.0.0.1 --port=5000`

- [ ] **Step 2: Zweryfikuj parser**

Run: `python -c "
from modules.production.services.parser_service import ProductNameParser
parser = ProductNameParser()

# Zaokrąglenie
r = parser.parse_product_name('Klejonka jesionowa lita A/B 130.0×35.0×3.0 cm surowa zaokrąglenie R3 (A)')
assert r['edge_processing'] == True
assert r['edge_type'] == 'zaokrąglenie'
assert r['edge_radius'] == 3
assert r['edge_letters'] == ['A']

# Fazowanie z kątem
r = parser.parse_product_name('Blat dębowy mikrowczep A/B 100x50x4 cm lakierowany bezbarwny fazowanie R3 45° E, F, G, H')
assert r['edge_type'] == 'fazowanie'
assert r['edge_angle'] == 45
assert r['edge_letters'] == ['E', 'F', 'G', 'H']

# Wielokąt
r = parser.parse_product_name('Klejonka dębowa mikrowczep B/B 80.0×60.0×4.0 cm surowa zaokrąglenie R3 (G1, G2, G3, D1, D2, D3, P1, P2, P3)')
assert r['edge_letters'] == ['G1', 'G2', 'G3', 'D1', 'D2', 'D3', 'P1', 'P2', 'P3']

# Brak krawędzi
r = parser.parse_product_name('Blat 180x80x3 cm dębowy lity A/B surowy')
assert r['edge_processing'] == False
assert r['edge_type'] is None

print('All parser tests PASSED')
"
`

- [ ] **Step 3: Zweryfikuj generator SVG**

Run: `python -c "
from modules.production.services.edge_svg_generator import EdgeSvgGenerator
gen = EdgeSvgGenerator()
svg = gen.generate(180, 80, 3, ['A', 'B', 'N1'])
assert '<svg' in svg
assert '</svg>' in svg
assert 'f59e0b' in svg
assert len(svg) > 500
print(f'SVG generated: {len(svg)} chars')
print('SVG generator test PASSED')
"
`

- [ ] **Step 4: Zweryfikuj metadane PDF**

Run: `python -c "
from modules.baselinker.edges_pdf_generator import EdgesPdfGenerator
import json
from pypdf import PdfReader
import io

gen = EdgesPdfGenerator()
products = [{
    'product_index': 1,
    'product_name': 'Test',
    'quantity': 1,
    'dimensions': {'length': 100, 'width': 50, 'thickness': 3},
    'shape': 'rectangular',
    'detail_id': 789,
    'sku': 'TESTSKU001',
}]

pdf_bytes = gen.generate_pdf(products, quote_number='Q-001', quote_id=123)
reader = PdfReader(io.BytesIO(pdf_bytes))
meta = reader.metadata
woodpower = meta.get('/WoodPowerMeta')
assert woodpower is not None
data = json.loads(woodpower)
assert data['quote_id'] == 123
assert data['items'][0]['detail_id'] == 789
print(f'PDF metadata: {data}')
print('PDF metadata test PASSED')
"
`

- [ ] **Step 5: Otwórz stanowisko w przeglądarce i zweryfikuj UI**

1. Otwórz http://127.0.0.1:5000 → zaloguj się
2. Przejdź na stanowisko cięcia
3. Znajdź produkt z obróbką krawędzi
4. Sprawdź:
   - Badge "Zaokrąglenie R3" (lub "Fazowanie R3 45°") widoczny w parametrach
   - Żółta ikona prostopadłościanu w nagłówku karty
   - Kliknięcie ikony otwiera modal z SVG i danymi
   - ESC / kliknięcie tła zamyka modal

- [ ] **Step 6: Commit końcowy**

```bash
git add -A
git commit -m "feat(edge): complete structured edge processing implementation with SVG visualization"
```

- [ ] **Step 7: Przygotuj SQL na live**

Podaj użytkownikowi SQL do uruchomienia na serwerze produkcyjnym (ten sam co w migracji z Task 1, Step 5).
