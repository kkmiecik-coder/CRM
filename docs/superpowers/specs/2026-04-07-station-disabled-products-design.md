# Wyszarzenie produktow na stanowiskach Formatowanie i Pakowanie

## Zakres

Na stanowiskach **Formatowanie** i **Pakowanie** — produkty w karcie zamowienia ktore nie maja jeszcze statusu odpowiedniego dla danego stanowiska sa:
- Wyszarzone (opacity, brak interakcji)
- Maja zablokowane przyciski (+/-, ZAKONCZ nie liczy ich)
- Maja badge z ikona SVG stanowiska na ktorym aktualnie sie znajduja (przed badge'ami gatunek/technologia/klasa)

## Ikony stanowisk

| Stanowisko | Ikona SVG | Klasa CSS |
|---|---|---|
| Wycinanie | Nozyczki | `.badge-station-cutting` |
| Skladanie | Nozyczki (ta sama) | `.badge-station-assembly` |
| Sklejanie | Kropla kleju | `.badge-station-gluing` |
| Formatowanie | Pila/obcinarka | `.badge-station-formatting` |
| Wykanczanie | Pedzel | `.badge-station-finishing` |
| Logistyka | Ciezarowka | `.badge-station-logistics` |

## Mapowanie statusu na stanowisko

```python
STATUS_TO_STATION = {
    'czeka_na_wyciecie': 'cutting',       # Nozyczki
    'czeka_na_skladanie': 'assembly',     # Nozyczki
    'czeka_na_sklejanie': 'gluing',       # Kropla kleju
    'czeka_na_formatowanie': 'formatting', # Pila
    'czeka_na_wykanczanie': 'finishing',   # Pedzel
    'czeka_na_logistyke': 'logistics',    # Ciezarowka
    'czeka_na_pakowanie': 'packaging',    # -
}

STATUS_TO_LABEL = {
    'czeka_na_wyciecie': 'Wycinanie',
    'czeka_na_skladanie': 'Skladanie',
    'czeka_na_sklejanie': 'Sklejanie',
    'czeka_na_formatowanie': 'Formatowanie',
    'czeka_na_wykanczanie': 'Wykanczanie',
    'czeka_na_logistyke': 'Logistyka',
    'czeka_na_pakowanie': 'Pakowanie',
}
```

## Logika wyszarzenia

**Formatowanie** — produkt aktywny gdy `current_status == 'czeka_na_formatowanie'`. Wszystko inne = wyszarzone + ikona stanowiska.

**Pakowanie** — produkt aktywny gdy `current_status == 'czeka_na_pakowanie'`. Wszystko inne = wyszarzone + ikona stanowiska.

## CSS

### Nowa klasa `.product-disabled`

```css
.product-row.product-disabled {
    opacity: 0.4;
    position: relative;
}

.product-row.product-disabled .btn-qty {
    pointer-events: none;
    cursor: not-allowed;
}
```

Produkty z klasa `.product-disabled`:
- NIE licza sie do sumy "gotowych" w zamowieniu
- NIE blokuja przycisku ZAKONCZ (przycisk patrzy tylko na aktywne produkty)
- Maja zablokowane przyciski qty (+/-)

### Nowa klasa `.badge-station`

```css
.badge-station {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 4px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
}

.badge-station svg {
    width: 14px;
    height: 14px;
}
```

## Backend

Bez zmian — backend juz wysyla `current_status` per produkt w ramach `orders_grouped`. Logika wyszarzenia jest czysto frontendowa (template + JS).

## Frontend — Template

Dotyczy: `formatting.html`, `packaging.html`

W petli `{% for product in order.products %}`:

```jinja
{% set expected_status = 'czeka_na_formatowanie' %}  {# lub 'czeka_na_pakowanie' dla pakowania #}
{% set is_disabled = product.current_status != expected_status %}

<div class="product-row {% if is_disabled %}product-disabled{% endif %}"
     data-product-id="{{ product.id }}"
     data-disabled="{{ 'true' if is_disabled else 'false' }}"
     ...>
    <div class="product-left-col">
        <div class="product-params">
            {% if is_disabled %}
                {# Mapowanie statusu na stanowisko — inline w szablonie #}
                {% set station_map = {
                    'czeka_na_wyciecie': ('cutting', 'Wycinanie'),
                    'czeka_na_skladanie': ('assembly', 'Skladanie'),
                    'czeka_na_sklejanie': ('gluing', 'Sklejanie'),
                    'czeka_na_formatowanie': ('formatting', 'Formatowanie'),
                    'czeka_na_wykanczanie': ('finishing', 'Wykanczanie'),
                    'czeka_na_logistyke': ('logistics', 'Logistyka'),
                } %}
                {% set station_info = station_map.get(product.current_status, ('unknown', 'Nieznane')) %}
                <span class="badge badge-station badge-station-{{ station_info[0] }}">
                    [SVG ikona inline] {{ station_info[1] }}
                </span>
            {% endif %}
            {# Reszta badge'ow: gatunek, technologia, klasa #}
        </div>
    </div>
    ...
</div>
```

Ikony SVG beda inline w szablonie (maly rozmiar, 14x14px).

## Frontend — JavaScript (AJAX re-render)

W `createOrderCardHTML()` dla formatowania/pakowania — przy renderowaniu produktow sprawdz `current_status` i dodaj klase `.product-disabled` + badge z ikona.

### updateCompleteButtonState()

Przycisk ZAKONCZ powinien ignorowac produkty z `.product-disabled` — liczyc tylko aktywne:

```javascript
function updateCompleteButtonState(card) {
    const activeRows = card.querySelectorAll('.product-row:not(.product-disabled)');
    const allDone = Array.from(activeRows).every(row => {
        const done = parseInt(row.dataset.quantityDone) || 0;
        const total = parseInt(row.dataset.quantity) || 1;
        return done >= total;
    });
    const completeBtn = card.querySelector('.btn-complete');
    if (completeBtn) completeBtn.disabled = !allDone || activeRows.length === 0;
}
```

### updateOrderCounter()

Licznik zamowienia powinien sumowac tylko aktywne produkty.

## Pliki do modyfikacji

| Warstwa | Plik | Zmiana |
|---------|------|--------|
| CSS | `station-shared.css` | Dodac `.product-disabled`, `.badge-station` |
| Template | `formatting.html` | Dodac logike wyszarzenia + badge stanowiska |
| Template | `packaging.html` | Dodac logike wyszarzenia + badge stanowiska |
| JS | `station-formatting.js` | Zaktualizowac AJAX rendering + complete button logic |
| JS | `station-packaging.js` | Zaktualizowac AJAX rendering + complete button logic |

## Pliki BEZ ZMIAN

- Backend (interfaces.py, ajax.py, __init__.py)
- Wycinanie/Skladanie/Sklejanie (juz przebudowane na flat tiles)
- Wykanczanie, Logistyka
- models.py
