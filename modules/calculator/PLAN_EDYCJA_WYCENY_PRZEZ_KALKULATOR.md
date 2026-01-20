# Plan Implementacji: Edycja Wyceny przez Kalkulator

## Cel

Zastąpienie obecnego edytora wycen w module `quotes` mechanizmem edycji przez kalkulator:
- Przekazanie ID wyceny przez URL: `/calculator?edit_quote=123`
- Pobranie danych wyceny z bazy przez API
- Wczytanie danych do kalkulatora (mechanizm podobny do backup/restore)
- Zmodyfikowany flow "Zapisz wycenę" dla trybu edycji

---

## Architektura rozwiązania

```
┌─────────────────────────────────────────────────────────────────┐
│                        MODULE: QUOTES                            │
├─────────────────────────────────────────────────────────────────┤
│  Przycisk "Edytuj" → redirect do /calculator?edit_quote={id}    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MODULE: CALCULATOR                          │
├─────────────────────────────────────────────────────────────────┤
│  1. Wykrycie parametru edit_quote w URL                         │
│  2. Pokazanie overlay "Wczytywanie wyceny..."                   │
│  3. GET /calculator/api/load_quote/{id}                         │
│  4. Transformacja danych → format backup                        │
│  5. restoreQuoteData() - wypełnienie formularzy                 │
│  6. setEditMode() - ustawienie trybu edycji                     │
│  7. Ukrycie overlay                                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SAVE QUOTE MODAL (Tryb edycji)               │
├─────────────────────────────────────────────────────────────────┤
│  ❌ Krok 1: Wyszukiwanie klienta - POMINIĘTY                    │
│  ✅ Krok 2: Formularz                                           │
│     ├─ Karta klienta (read-only) z danymi klienta               │
│     ├─ Numer wyceny: "#01/12/26/W"                              │
│     ├─ Tabela produktów (jak w trybie normalnym)                │
│     ├─ Podsumowanie cenowe                                      │
│     └─ Przycisk: "Zapisz edycję wyceny"                         │
│  ✅ Krok 3: Sukces - "Wycena zaktualizowana"                    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        BACKEND API                               │
├─────────────────────────────────────────────────────────────────┤
│  PUT /calculator/api/update_quote/{id}                          │
│  - Aktualizacja Quote (notes, shipping, quote_type)             │
│  - Aktualizacja QuoteItems (warianty, ceny)                     │
│  - Aktualizacja QuoteItemDetails (wykończenie, krawędzie)       │
│  - Obsługa dodawania/usuwania produktów                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pliki do modyfikacji/utworzenia

### Backend (Python)

| Plik | Akcja | Zakres |
|------|-------|--------|
| `modules/calculator/routers.py` | MODYFIKACJA | Nowe endpointy: `load_quote`, `update_quote` |
| `modules/calculator/services/quote_loader_service.py` | NOWY | Serwis ładowania i transformacji danych wyceny |

### Frontend (JavaScript)

| Plik | Akcja | Zakres |
|------|-------|--------|
| `modules/calculator/static/js/quote_edit_loader.js` | NOWY | Klasa do ładowania wyceny do edycji |
| `modules/calculator/static/js/save_quote.js` | MODYFIKACJA | Obsługa trybu edycji |
| `modules/calculator/static/js/calculator.js` | MODYFIKACJA | Inicjalizacja trybu edycji |

### Frontend (HTML/CSS)

| Plik | Akcja | Zakres |
|------|-------|--------|
| `modules/calculator/templates/save_quote.html` | MODYFIKACJA | Karta klienta, zmiana przycisku |
| `modules/calculator/static/css/style_calculator.css` | MODYFIKACJA | Style dla karty klienta, overlay |

### Module Quotes

| Plik | Akcja | Zakres |
|------|-------|--------|
| `modules/quotes/static/js/quotes.js` | MODYFIKACJA | Zmiana przycisku "Edytuj" na redirect |

---

## Szczegółowa specyfikacja

### 1. Backend: Endpoint `GET /calculator/api/load_quote/{id}`

**Plik:** `modules/calculator/routers.py`

**Cel:** Zwrócenie danych wyceny w formacie kompatybilnym z mechanizmem restore

**Request:**
```
GET /calculator/api/load_quote/123
Headers: Cookie (sesja użytkownika)
```

**Response (sukces):**
```json
{
    "success": true,
    "quote": {
        "id": 123,
        "quote_number": "01/12/26/W",
        "created_at": "2026-01-15T10:30:00",
        "status_name": "Nowa",

        "client": {
            "id": 5,
            "client_number": "ACME",
            "client_name": "Jan Kowalski",
            "email": "jan@acme.pl",
            "phone": "123456789"
        },

        "settings": {
            "clientType": "Partner",
            "multiplier": 1.1,
            "quoteType": "brutto",
            "courierName": "DPD",
            "shippingNetto": 50.00,
            "shippingBrutto": 61.50,
            "notes": "Notatka do wyceny"
        },

        "products": [
            {
                "index": 1,
                "length": 200.0,
                "width": 100.0,
                "thickness": 2.0,
                "quantity": 1,
                "selectedVariant": "dab-lity-ab",

                "finishing": {
                    "type": "Lakierowanie",
                    "variant": "bezbarwne",
                    "color": null,
                    "gloss": "satyna",
                    "priceNetto": 50.00,
                    "priceBrutto": 61.50
                },

                "edges": {
                    "data": [
                        {"letter": "A", "type": "round", "r_value": 5},
                        {"letter": "B", "type": "round", "r_value": 5}
                    ],
                    "type": "round",
                    "rValue": 5,
                    "netto": 30.00,
                    "brutto": 36.90,
                    "svg": "<svg>...</svg>"
                },

                "variants": [
                    {
                        "item_id": 100,
                        "variant_code": "dab-lity-ab",
                        "is_selected": true,
                        "show_on_client_page": true,
                        "price_per_m3": 2500.0,
                        "volume_m3": 0.04,
                        "unit_price_netto": 1000.00,
                        "unit_price_brutto": 1230.00
                    },
                    {
                        "item_id": 101,
                        "variant_code": "dab-micro-ab",
                        "is_selected": false,
                        "show_on_client_page": true,
                        "price_per_m3": 2800.0,
                        "volume_m3": 0.04,
                        "unit_price_netto": 1120.00,
                        "unit_price_brutto": 1377.60
                    }
                ]
            }
        ]
    }
}
```

**Response (błąd - brak dostępu):**
```json
{
    "success": false,
    "error": "Brak uprawnień do edycji tej wyceny"
}
```

**Response (błąd - nie znaleziono):**
```json
{
    "success": false,
    "error": "Wycena nie istnieje"
}
```

**Logika uprawnień:**
- Admin: może edytować wszystkie wyceny
- User: może edytować tylko swoje wyceny (`quote.user_id == current_user.id`)

---

### 2. Backend: Endpoint `PUT /calculator/api/update_quote/{id}`

**Plik:** `modules/calculator/routers.py`

**Cel:** Aktualizacja istniejącej wyceny na podstawie danych z kalkulatora

**Request:**
```json
{
    "settings": {
        "notes": "Zaktualizowana notatka",
        "courierName": "DPD",
        "shippingNetto": 50.00,
        "shippingBrutto": 61.50,
        "quoteType": "brutto",
        "clientType": "Partner",
        "multiplier": 1.1
    },

    "products": [
        {
            "index": 1,
            "length": 200.0,
            "width": 100.0,
            "thickness": 2.0,
            "quantity": 2,

            "finishing": {
                "type": "Lakierowanie",
                "variant": "bezbarwne",
                "color": null,
                "gloss": "satyna",
                "priceNetto": 100.00,
                "priceBrutto": 123.00
            },

            "edges": {
                "data": [...],
                "type": "round",
                "rValue": 5,
                "netto": 60.00,
                "brutto": 73.80,
                "svg": "<svg>...</svg>"
            },

            "variants": [
                {
                    "variant_code": "dab-lity-ab",
                    "is_selected": true,
                    "show_on_client_page": true,
                    "price_per_m3": 2500.0,
                    "volume_m3": 0.04,
                    "unit_price_netto": 1000.00,
                    "unit_price_brutto": 1230.00
                }
            ]
        }
    ],

    "deleted_product_indexes": [3]
}
```

**Response (sukces):**
```json
{
    "success": true,
    "message": "Wycena została zaktualizowana",
    "quote_id": 123,
    "quote_number": "01/12/26/W"
}
```

**Logika aktualizacji:**

1. **Walidacja uprawnień** - jak w `load_quote`

2. **Aktualizacja Quote:**
   ```python
   quote.notes = data['settings']['notes']
   quote.courier_name = data['settings']['courierName']
   quote.shipping_cost_netto = data['settings']['shippingNetto']
   quote.shipping_cost_brutto = data['settings']['shippingBrutto']
   quote.quote_type = data['settings']['quoteType']
   quote.quote_client_type = data['settings']['clientType']
   quote.quote_multiplier = data['settings']['multiplier']
   ```

3. **Usunięcie produktów:**
   ```python
   for idx in data['deleted_product_indexes']:
       QuoteItem.query.filter_by(quote_id=id, product_index=idx).delete()
       QuoteItemDetails.query.filter_by(quote_id=id, product_index=idx).delete()
   ```

4. **Aktualizacja/dodanie produktów:**
   - Dla każdego produktu w `products`:
     - Sprawdź czy `QuoteItemDetails` istnieje dla `product_index`
     - Jeśli tak → UPDATE
     - Jeśli nie → INSERT (nowy produkt dodany w edycji)
   - Analogicznie dla `QuoteItem` (warianty)

5. **Wpis do QuoteLog:**
   ```python
   QuoteLog(
       quote_id=id,
       user_id=current_user.id,
       action="Zaktualizowano wycenę",
       details=f"Zmieniono: {changed_fields}"
   )
   ```

---

### 3. Frontend: Klasa `QuoteEditLoader`

**Plik:** `modules/calculator/static/js/quote_edit_loader.js`

```javascript
/**
 * Klasa odpowiedzialna za ładowanie wyceny do edycji w kalkulatorze
 */
class QuoteEditLoader {
    constructor() {
        this.editQuoteId = null;
        this.quoteData = null;
        this.isEditMode = false;
    }

    /**
     * Inicjalizacja - sprawdza URL i ładuje wycenę jeśli tryb edycji
     */
    async init() {
        const params = new URLSearchParams(window.location.search);
        this.editQuoteId = params.get('edit_quote');

        if (this.editQuoteId) {
            await this.loadQuoteForEdit();
        }
    }

    /**
     * Pokazuje overlay ładowania
     */
    showLoadingOverlay(message = 'Wczytywanie wyceny...') {
        const overlay = document.createElement('div');
        overlay.id = 'quote-edit-loading-overlay';
        overlay.innerHTML = `
            <div class="quote-edit-loading-content">
                <div class="spinner"></div>
                <p>${message}</p>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    /**
     * Ukrywa overlay ładowania
     */
    hideLoadingOverlay() {
        const overlay = document.getElementById('quote-edit-loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    /**
     * Główna metoda ładowania wyceny
     */
    async loadQuoteForEdit() {
        this.showLoadingOverlay();

        try {
            const response = await fetch(`/calculator/api/load_quote/${this.editQuoteId}`);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Błąd ładowania wyceny');
            }

            this.quoteData = data.quote;

            // Przywróć dane do kalkulatora
            await this.restoreQuoteToCalculator();

            // Ustaw tryb edycji
            this.setEditMode();

        } catch (error) {
            console.error('Błąd ładowania wyceny:', error);
            alert(`Nie udało się załadować wyceny: ${error.message}`);
            // Przekieruj z powrotem do quotes
            window.location.href = '/quotes';
        } finally {
            this.hideLoadingOverlay();
        }
    }

    /**
     * Przywraca dane wyceny do formularzy kalkulatora
     * (mechanizm podobny do QuoteDraftBackup.restoreQuote)
     */
    async restoreQuoteToCalculator() {
        const { settings, products } = this.quoteData;

        // 1. Ustaw grupę cenową
        if (settings.clientType) {
            const clientTypeSelect = document.querySelector('[data-field="clientType"]');
            if (clientTypeSelect) {
                clientTypeSelect.value = settings.clientType;
                clientTypeSelect.dispatchEvent(new Event('change'));
            }
        }

        // 2. Ustaw tryb cen (brutto/netto)
        const priceMode = settings.quoteType || 'brutto';
        const priceModeRadio = document.getElementById(
            priceMode === 'brutto' ? 'priceModeBrutto' : 'priceModeNetto'
        );
        if (priceModeRadio) {
            priceModeRadio.checked = true;
            priceModeRadio.dispatchEvent(new Event('change'));
        }

        // 3. Ustaw wysyłkę
        const deliveryBrutto = document.getElementById('delivery-brutto');
        const deliveryNetto = document.getElementById('delivery-netto');
        const courierName = document.getElementById('courier-name');

        if (deliveryBrutto) deliveryBrutto.value = settings.shippingBrutto || 0;
        if (deliveryNetto) deliveryNetto.value = settings.shippingNetto || 0;
        if (courierName) courierName.value = settings.courierName || '';

        // 4. Przywróć produkty
        await this.restoreProducts(products);
    }

    /**
     * Przywraca produkty do formularzy
     */
    async restoreProducts(products) {
        // Usuń wszystkie formularze oprócz pierwszego
        const forms = document.querySelectorAll('.quote-form');
        forms.forEach((form, index) => {
            if (index > 0) form.remove();
        });

        // Resetuj pierwszy formularz
        const firstForm = document.querySelector('.quote-form');
        if (firstForm) {
            this.resetForm(firstForm);
        }

        // Przywróć każdy produkt
        for (let i = 0; i < products.length; i++) {
            const product = products[i];

            // Dodaj nowy formularz jeśli potrzeba
            if (i > 0) {
                // Wywołaj funkcję dodawania produktu (zakładam że istnieje)
                if (typeof addNewProduct === 'function') {
                    addNewProduct();
                }
                await this.delay(100);
            }

            const form = document.querySelectorAll('.quote-form')[i];
            if (form) {
                await this.restoreProduct(form, product);
            }
        }
    }

    /**
     * Przywraca pojedynczy produkt do formularza
     */
    async restoreProduct(form, product) {
        // Wymiary
        this.setFieldValue(form, 'length', product.length);
        this.setFieldValue(form, 'width', product.width);
        this.setFieldValue(form, 'thickness', product.thickness);
        this.setFieldValue(form, 'quantity', product.quantity);

        // Poczekaj na przeliczenie wariantów
        await this.delay(200);

        // Wybierz wariant
        if (product.selectedVariant) {
            const variantRadio = form.querySelector(
                `input[type="radio"][value="${product.selectedVariant}"]`
            );
            if (variantRadio) {
                variantRadio.checked = true;
                variantRadio.dispatchEvent(new Event('change'));
            }
        }

        // Wykończenie
        if (product.finishing) {
            await this.restoreFinishing(form, product.finishing);
        }

        // Krawędzie
        if (product.edges) {
            this.restoreEdges(form, product.edges);
        }
    }

    /**
     * Przywraca wykończenie
     */
    async restoreFinishing(form, finishing) {
        // Typ wykończenia
        if (finishing.type) {
            const typeBtn = form.querySelector(
                `[data-finishing-type="${finishing.type}"]`
            );
            if (typeBtn) {
                typeBtn.click();
                await this.delay(100);
            }
        }

        // Wariant (bezbarwne/barwne)
        if (finishing.variant) {
            const variantBtn = form.querySelector(
                `[data-finishing-variant="${finishing.variant}"]`
            );
            if (variantBtn) {
                variantBtn.click();
                await this.delay(100);
            }
        }

        // Kolor
        if (finishing.color) {
            const colorBtn = form.querySelector(
                `[data-finishing-color="${finishing.color}"]`
            );
            if (colorBtn) {
                colorBtn.click();
                await this.delay(100);
            }
        }

        // Połysk
        if (finishing.gloss) {
            const glossBtn = form.querySelector(
                `[data-finishing-gloss="${finishing.gloss}"]`
            );
            if (glossBtn) {
                glossBtn.click();
            }
        }
    }

    /**
     * Przywraca krawędzie
     */
    restoreEdges(form, edges) {
        if (edges.data) {
            form.dataset.edgesData = JSON.stringify(edges.data);
        }
        if (edges.type) {
            form.dataset.edgesType = edges.type;
        }
        if (edges.rValue) {
            form.dataset.edgesRValue = edges.rValue;
        }
        if (edges.netto !== undefined) {
            form.dataset.edgesNetto = edges.netto;
        }
        if (edges.brutto !== undefined) {
            form.dataset.edgesBrutto = edges.brutto;
        }
        if (edges.svg) {
            form.dataset.edgesSvg = edges.svg;
        }

        // Trigger aktualizacji UI krawędzi jeśli istnieje taka funkcja
        if (typeof updateEdgesDisplay === 'function') {
            updateEdgesDisplay(form);
        }
    }

    /**
     * Ustawia wartość pola w formularzu
     */
    setFieldValue(form, fieldName, value) {
        const field = form.querySelector(`[data-field="${fieldName}"]`);
        if (field) {
            field.value = value;
            field.dispatchEvent(new Event('input'));
            field.dispatchEvent(new Event('change'));
        }
    }

    /**
     * Resetuje formularz do stanu początkowego
     */
    resetForm(form) {
        form.querySelectorAll('[data-field]').forEach(field => {
            if (field.tagName === 'SELECT') {
                field.selectedIndex = 0;
            } else {
                field.value = '';
            }
        });

        // Resetuj wykończenie na "Surowe"
        const suroweBtn = form.querySelector('[data-finishing-type="Surowe"]');
        if (suroweBtn) suroweBtn.click();

        // Wyczyść krawędzie
        delete form.dataset.edgesData;
        delete form.dataset.edgesType;
        delete form.dataset.edgesRValue;
        delete form.dataset.edgesNetto;
        delete form.dataset.edgesBrutto;
        delete form.dataset.edgesSvg;
    }

    /**
     * Ustawia tryb edycji w UI
     */
    setEditMode() {
        this.isEditMode = true;

        // Zapisz dane w globalnym obiekcie
        window.quoteEditMode = {
            isActive: true,
            quoteId: this.editQuoteId,
            quoteNumber: this.quoteData.quote_number,
            client: this.quoteData.client,
            notes: this.quoteData.settings.notes
        };

        // Dodaj klasę do body dla stylów
        document.body.classList.add('quote-edit-mode');

        // Aktualizuj tytuł strony
        document.title = `Edycja wyceny #${this.quoteData.quote_number} - Kalkulator`;

        // Dodaj banner informacyjny
        this.showEditModeBanner();
    }

    /**
     * Pokazuje banner informujący o trybie edycji
     */
    showEditModeBanner() {
        const banner = document.createElement('div');
        banner.id = 'edit-mode-banner';
        banner.innerHTML = `
            <div class="edit-mode-banner-content">
                <i class="fas fa-edit"></i>
                <span>Tryb edycji wyceny <strong>#${this.quoteData.quote_number}</strong></span>
                <span class="client-info">Klient: ${this.quoteData.client.client_name || this.quoteData.client.client_number}</span>
                <a href="/quotes" class="cancel-edit-btn">Anuluj edycję</a>
            </div>
        `;

        const mainContent = document.querySelector('.calculator-container')
            || document.querySelector('main')
            || document.body.firstElementChild;
        mainContent.insertBefore(banner, mainContent.firstChild);
    }

    /**
     * Helper - opóźnienie
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Eksport globalny
window.QuoteEditLoader = QuoteEditLoader;
```

---

### 4. Frontend: Modyfikacja `save_quote.js`

**Plik:** `modules/calculator/static/js/save_quote.js`

**Zmiany do wprowadzenia:**

#### 4.1. Dodaj na początku pliku (po DOMContentLoaded):

```javascript
// Sprawdź tryb edycji
const isEditMode = window.quoteEditMode?.isActive || false;
const editQuoteId = window.quoteEditMode?.quoteId || null;

if (isEditMode) {
    initEditModeUI();
}
```

#### 4.2. Nowa funkcja `initEditModeUI()`:

```javascript
/**
 * Inicjalizuje UI dla trybu edycji wyceny
 */
function initEditModeUI() {
    const { quoteNumber, client, notes } = window.quoteEditMode;

    // 1. Ukryj krok 1 (wyszukiwanie klienta)
    const stepSearch = document.querySelector('.sq-step-search');
    if (stepSearch) {
        stepSearch.style.display = 'none';
    }

    // 2. Dodaj kartę klienta w kroku 2
    const formSection = document.querySelector('.sq-form-section');
    if (formSection) {
        const clientCard = createClientCard(client, quoteNumber);
        formSection.insertBefore(clientCard, formSection.firstChild);
    }

    // 3. Ukryj pola formularza klienta
    const clientFields = document.querySelectorAll(
        '[name="client_login"], [name="client_name"], [name="client_phone"], [name="client_email"]'
    );
    clientFields.forEach(field => {
        const wrapper = field.closest('.form-group') || field.parentElement;
        if (wrapper) wrapper.style.display = 'none';
    });

    // 4. Wypełnij notatkę z wyceny
    const noteField = document.getElementById('quote_note');
    if (noteField && notes) {
        noteField.value = notes;
        updateNoteCounter();
    }

    // 5. Zmień tekst przycisku
    const saveButton = document.getElementById('confirmSaveQuote');
    if (saveButton) {
        saveButton.innerHTML = '<i class="fas fa-save"></i> Zapisz edycję wyceny';
    }

    // 6. Zmień handler zapisu
    overrideSaveHandler();
}

/**
 * Tworzy kartę klienta dla trybu edycji
 */
function createClientCard(client, quoteNumber) {
    const card = document.createElement('div');
    card.className = 'edit-mode-client-card';
    card.innerHTML = `
        <div class="client-card-header">
            <i class="fas fa-file-invoice"></i>
            <span>Edycja wyceny <strong>#${quoteNumber}</strong></span>
        </div>
        <div class="client-card-body">
            <div class="client-info-row">
                <i class="fas fa-user"></i>
                <span class="client-name">${client.client_name || client.client_number}</span>
            </div>
            ${client.email ? `
            <div class="client-info-row">
                <i class="fas fa-envelope"></i>
                <span>${client.email}</span>
            </div>
            ` : ''}
            ${client.phone ? `
            <div class="client-info-row">
                <i class="fas fa-phone"></i>
                <span>${client.phone}</span>
            </div>
            ` : ''}
        </div>
        <div class="client-card-footer">
            <small><i class="fas fa-lock"></i> Klient przypisany do wyceny nie może być zmieniony</small>
        </div>
    `;
    return card;
}

/**
 * Nadpisuje handler zapisu dla trybu edycji
 */
function overrideSaveHandler() {
    const saveButton = document.getElementById('confirmSaveQuote');
    if (!saveButton) return;

    // Usuń stary handler
    const newSaveButton = saveButton.cloneNode(true);
    saveButton.parentNode.replaceChild(newSaveButton, saveButton);

    // Dodaj nowy handler
    newSaveButton.addEventListener('click', async () => {
        await saveQuoteEdit();
    });
}

/**
 * Zapisuje edycję wyceny
 */
async function saveQuoteEdit() {
    const saveButton = document.getElementById('confirmSaveQuote');
    const feedback = document.getElementById('quoteSaveFeedback');

    // Walidacja produktów (bez walidacji klienta)
    if (!validateProductsOnly()) {
        return;
    }

    // Zbierz dane z kalkulatora
    const quoteData = collectQuoteDataForEdit();

    // Pokaż loader
    saveButton.disabled = true;
    saveButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Zapisywanie...';

    try {
        const response = await fetch(`/calculator/api/update_quote/${window.quoteEditMode.quoteId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(quoteData)
        });

        const result = await response.json();

        if (result.success) {
            // Pokaż sukces
            showEditSuccessStep(result.quote_number);
        } else {
            throw new Error(result.error || 'Błąd aktualizacji wyceny');
        }

    } catch (error) {
        console.error('Błąd zapisu:', error);
        feedback.textContent = error.message;
        feedback.style.display = 'block';

        saveButton.disabled = false;
        saveButton.innerHTML = '<i class="fas fa-save"></i> Zapisz edycję wyceny';
    }
}

/**
 * Walidacja tylko produktów (bez klienta)
 */
function validateProductsOnly() {
    // Sprawdź czy wszystkie produkty mają wybrany wariant
    const forms = document.querySelectorAll('.quote-form');
    for (const form of forms) {
        const selectedVariant = form.querySelector('input[type="radio"]:checked');
        if (!selectedVariant) {
            alert('Każdy produkt musi mieć wybrany wariant');
            return false;
        }
    }
    return true;
}

/**
 * Zbiera dane do aktualizacji wyceny
 */
function collectQuoteDataForEdit() {
    // Wykorzystaj istniejącą logikę zbierania danych
    // Struktura musi odpowiadać PUT /calculator/api/update_quote/{id}

    const products = [];
    const forms = document.querySelectorAll('.quote-form');

    forms.forEach((form, index) => {
        const product = {
            index: index + 1,
            length: parseFloat(form.querySelector('[data-field="length"]')?.value) || 0,
            width: parseFloat(form.querySelector('[data-field="width"]')?.value) || 0,
            thickness: parseFloat(form.querySelector('[data-field="thickness"]')?.value) || 0,
            quantity: parseInt(form.querySelector('[data-field="quantity"]')?.value) || 1,

            finishing: extractFinishing(form),
            edges: extractEdges(form),
            variants: extractVariants(form)
        };
        products.push(product);
    });

    return {
        settings: {
            notes: document.getElementById('quote_note')?.value || '',
            courierName: document.getElementById('courier-name')?.value || '',
            shippingNetto: parseFloat(document.getElementById('delivery-netto')?.value) || 0,
            shippingBrutto: parseFloat(document.getElementById('delivery-brutto')?.value) || 0,
            quoteType: window.getCurrentPriceMode?.() || 'brutto',
            clientType: document.querySelector('[data-field="clientType"]')?.value || null,
            multiplier: parseFloat(document.querySelector('[data-field="clientType"]')?.selectedOptions[0]?.dataset.multiplier) || 1.0
        },
        products: products,
        deleted_product_indexes: [] // TODO: implementacja usuwania produktów
    };
}

/**
 * Pokazuje krok sukcesu dla edycji
 */
function showEditSuccessStep(quoteNumber) {
    // Ukryj krok 2
    document.querySelector('.sq-step-form')?.classList.remove('active');

    // Pokaż krok 3 ze zmodyfikowanym komunikatem
    const successStep = document.querySelector('.sq-step-success');
    if (successStep) {
        successStep.classList.add('active');

        // Zmień komunikat
        const successTitle = successStep.querySelector('h3') || successStep.querySelector('.success-title');
        if (successTitle) {
            successTitle.innerHTML = '<i class="fas fa-check-circle"></i> Wycena zaktualizowana';
        }

        // Aktualizuj numer wyceny
        const quoteNumberDisplay = document.getElementById('quoteNumberDisplay');
        if (quoteNumberDisplay) {
            quoteNumberDisplay.textContent = quoteNumber;
        }
    }
}
```

---

### 5. Frontend: Modyfikacja `calculator.js`

**Plik:** `modules/calculator/static/js/calculator.js`

**Dodaj na końcu bloku DOMContentLoaded:**

```javascript
// Inicjalizacja trybu edycji wyceny
const quoteEditLoader = new QuoteEditLoader();
quoteEditLoader.init();
```

---

### 6. HTML: Modyfikacja `save_quote.html`

**Plik:** `modules/calculator/templates/save_quote.html`

**Dodaj na początku pliku (po nagłówku):**

```html
<!-- Ładowanie skryptu edycji przed save_quote.js -->
<script src="{{ url_for('calculator.static', filename='js/quote_edit_loader.js') }}"></script>
```

---

### 7. CSS: Style dla trybu edycji

**Plik:** `modules/calculator/static/css/style_calculator.css`

**Dodaj na końcu pliku:**

```css
/* ========================================
   TRYB EDYCJI WYCENY
   ======================================== */

/* Overlay ładowania */
#quote-edit-loading-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(255, 255, 255, 0.95);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
}

.quote-edit-loading-content {
    text-align: center;
}

.quote-edit-loading-content .spinner {
    width: 50px;
    height: 50px;
    border: 4px solid #e0e0e0;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto 16px;
}

.quote-edit-loading-content p {
    font-size: 18px;
    color: #374151;
    margin: 0;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Banner trybu edycji */
#edit-mode-banner {
    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
    border-bottom: 2px solid #f59e0b;
    padding: 12px 20px;
    margin-bottom: 20px;
}

.edit-mode-banner-content {
    display: flex;
    align-items: center;
    gap: 12px;
    max-width: 1200px;
    margin: 0 auto;
    flex-wrap: wrap;
}

.edit-mode-banner-content i {
    color: #d97706;
    font-size: 20px;
}

.edit-mode-banner-content span {
    color: #92400e;
}

.edit-mode-banner-content .client-info {
    margin-left: auto;
    font-weight: 500;
}

.cancel-edit-btn {
    background: white;
    color: #dc2626;
    border: 1px solid #dc2626;
    padding: 6px 12px;
    border-radius: 6px;
    text-decoration: none;
    font-size: 14px;
    transition: all 0.2s;
}

.cancel-edit-btn:hover {
    background: #dc2626;
    color: white;
}

/* Karta klienta w modalu zapisu */
.edit-mode-client-card {
    background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
    border: 1px solid #93c5fd;
    border-radius: 12px;
    padding: 0;
    margin-bottom: 20px;
    overflow: hidden;
}

.client-card-header {
    background: #2563eb;
    color: white;
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 15px;
}

.client-card-header i {
    font-size: 18px;
}

.client-card-body {
    padding: 16px;
}

.client-info-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #bfdbfe;
}

.client-info-row:last-child {
    border-bottom: none;
}

.client-info-row i {
    color: #3b82f6;
    width: 20px;
    text-align: center;
}

.client-info-row .client-name {
    font-weight: 600;
    color: #1e40af;
}

.client-card-footer {
    background: #dbeafe;
    padding: 10px 16px;
    text-align: center;
}

.client-card-footer small {
    color: #1e40af;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
}

.client-card-footer i {
    font-size: 12px;
}

/* Responsywność */
@media (max-width: 768px) {
    .edit-mode-banner-content {
        flex-direction: column;
        align-items: flex-start;
    }

    .edit-mode-banner-content .client-info {
        margin-left: 0;
    }

    .cancel-edit-btn {
        width: 100%;
        text-align: center;
    }
}
```

---

### 8. Modyfikacja przycisku "Edytuj" w module Quotes

**Plik:** `modules/quotes/static/js/quotes.js`

**Znajdź funkcję obsługującą przycisk edycji i zmień na:**

```javascript
// Zamiast otwierania modala edytora, przekieruj do kalkulatora
function editQuote(quoteId) {
    window.location.href = `/calculator?edit_quote=${quoteId}`;
}

// Lub jeśli używasz event listener:
document.querySelectorAll('.edit-quote-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        const quoteId = this.dataset.quoteId;
        window.location.href = `/calculator?edit_quote=${quoteId}`;
    });
});
```

---

## Kolejność implementacji

### Faza 1: Backend (podstawa)
1. ✅ Utworzyć `quote_loader_service.py` z logiką transformacji danych
2. ✅ Dodać endpoint `GET /calculator/api/load_quote/{id}`
3. ✅ Dodać endpoint `PUT /calculator/api/update_quote/{id}`

### Faza 2: Frontend - ładowanie
4. ✅ Utworzyć `quote_edit_loader.js`
5. ✅ Dodać style CSS dla overlay i bannera
6. ✅ Zintegrować z `calculator.js`

### Faza 3: Frontend - zapis
7. ✅ Zmodyfikować `save_quote.js` - tryb edycji
8. ✅ Dodać kartę klienta w `save_quote.html`
9. ✅ Dodać style CSS dla karty klienta

### Faza 4: Integracja
10. ✅ Zmodyfikować `quotes.js` - redirect zamiast modala
11. ✅ Testy end-to-end

---

## Testowanie

### Scenariusze do przetestowania:

1. **Ładowanie wyceny:**
   - Wycena z 1 produktem
   - Wycena z wieloma produktami (5+)
   - Wycena z różnymi wykończeniami
   - Wycena z krawędziami
   - Wycena bez uprawnień (błąd)

2. **Edycja:**
   - Zmiana wymiarów produktu
   - Zmiana ilości
   - Zmiana wykończenia
   - Zmiana wariantu
   - Dodanie krawędzi
   - Dodanie nowego produktu
   - Usunięcie produktu

3. **Zapis:**
   - Zapis bez zmian
   - Zapis ze zmianami cen
   - Zapis z nowymi produktami
   - Zapis po usunięciu produktu

4. **Edge cases:**
   - Odświeżenie strony w trybie edycji
   - Anulowanie edycji
   - Sesja wygasła podczas edycji

---

## Uwagi końcowe

### Korzyści implementacji:
- Jeden spójny UI dla tworzenia i edycji wycen
- Eliminacja osobnego kodu edytora w module quotes
- Pełna funkcjonalność kalkulatora dostępna przy edycji
- Jasne rozdzielenie odpowiedzialności

### Potencjalne problemy:
- Duże wyceny mogą długo się ładować → overlay rozwiązuje UX
- Konieczność synchronizacji struktury danych między formatem backup a bazą
- Obsługa usuwania produktów wymaga dodatkowej logiki

### Przyszłe rozszerzenia:
- Historia zmian wyceny
- Porównanie wersji przed/po edycji
- Częściowe zapisywanie zmian (autosave)
