/**
 * Quote Edit Loader
 * Laduje wycene z bazy danych do kalkulatora w trybie edycji.
 * Niezalezny od systemu backup/restore (qdraft_backup_cookies.js).
 */

class QuoteEditLoader {
    constructor() {
        this.editQuoteUuid = null;
        this.quoteData = null;
    }

    /**
     * Sprawdza URL i rozpoczyna ladowanie jesli tryb edycji
     */
    async init() {
        const params = new URLSearchParams(window.location.search);
        this.editQuoteUuid = params.get('edit_quote');

        if (!this.editQuoteUuid) return;

        await this.loadQuoteForEdit();
    }

    // ========================================
    // LADOWANIE DANYCH Z API
    // ========================================

    async loadQuoteForEdit() {
        this.showLoadingOverlay('Pobieranie danych wyceny...');
        this.updateProgress(0);

        try {
            const response = await fetch(`/calculator/api/load_quote/${this.editQuoteUuid}`);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Blad ladowania wyceny');
            }

            this.quoteData = data.quote;
            this.updateProgress(10);

            // Przywroc dane do kalkulatora
            await this.restoreQuoteToCalculator();

            // Ustaw tryb edycji (badge, globalna zmienna)
            this.setEditMode();

            // Snapshot stanu po wczytaniu + detekcja zmian
            this.initChangeDetection();

        } catch (error) {
            console.error('[QuoteEditLoader] Blad:', error);
            alert('Nie udalo sie zaladowac wyceny: ' + error.message);
            window.location.href = '/quotes';
        } finally {
            this.hideLoadingOverlay();
        }
    }

    // ========================================
    // RESTORE DANYCH DO KALKULATORA
    // ========================================

    async restoreQuoteToCalculator() {
        const { settings, products } = this.quoteData;
        const totalProducts = products ? products.length : 0;

        // Wagi etapow (suma = 90, bo 10% to pobranie danych)
        const SETTINGS_WEIGHT = 10;
        const PRODUCTS_WEIGHT = 65;
        const FINALIZE_WEIGHT = 15;

        // 1. Tryb brutto/netto + Grupa cenowa
        this.showLoadingOverlay('Wczytywanie ustawień...');
        await this.restorePriceMode(settings.quoteType);
        await this.restoreClientType(settings.clientType);
        this.updateProgress(10 + SETTINGS_WEIGHT);

        // 2. Produkty
        if (products && products.length > 0) {
            const quoteFormsContainer = document.querySelector('.quote-forms');
            if (!quoteFormsContainer) {
                console.error('[QuoteEditLoader] Brak .quote-forms container');
                return;
            }

            // Usun dodatkowe formularze (zostaw tylko pierwszy)
            const existingForms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
            for (let i = existingForms.length - 1; i > 0; i--) {
                existingForms[i].remove();
            }

            for (let i = 0; i < totalProducts; i++) {
                this.showLoadingOverlay(`Wczytywanie produktu ${i + 1} z ${totalProducts}...`);

                if (i > 0 && typeof addNewProduct === 'function') {
                    addNewProduct();
                    await this.delay(300);
                }

                const form = quoteFormsContainer.querySelectorAll('.quote-form')[i];
                if (form) {
                    await this.restoreProduct(form, products[i]);
                }

                const productProgress = ((i + 1) / totalProducts) * PRODUCTS_WEIGHT;
                this.updateProgress(10 + SETTINGS_WEIGHT + productProgress);
            }

            // Drugie przejscie: napraw ksztalty
            await this.restoreShapesSecondPass(products);
        }

        // 3. Finalizacja
        this.showLoadingOverlay('Finalizacja...');
        this.restoreShipping(settings);

        // Przelicz wykończenie dla każdego formularza przed generowaniem podsumowania
        const allForms = document.querySelectorAll('.quote-form');
        allForms.forEach(form => {
            if (typeof calculateFinishingCost === 'function') {
                calculateFinishingCost(form);
            }
        });

        if (typeof generateProductsSummary === 'function') {
            generateProductsSummary();
        }

        if (typeof activateProductCard === 'function') {
            activateProductCard(0);
        }

        this.updateProgress(100);
    }

    /**
     * Przywraca tryb brutto/netto
     */
    async restorePriceMode(quoteType) {
        if (!quoteType) return;

        const radio = document.getElementById(
            quoteType === 'netto' ? 'priceModeNetto' : 'priceModeBrutto'
        );
        if (radio) {
            radio.checked = true;
            radio.dispatchEvent(new Event('change', { bubbles: true }));
            await this.delay(100);
        }
    }

    /**
     * Przywraca grupe cenowa na wszystkich formularzach
     */
    async restoreClientType(clientType) {
        if (!clientType) return;

        document.querySelectorAll('select[data-field="clientType"]').forEach(select => {
            select.value = clientType;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        });

        await this.delay(100);
    }

    /**
     * Przywraca pojedynczy produkt
     */
    async restoreProduct(form, product) {

        // Ksztalt (przed wymiarami - bo nieprosto. blokuje length/width)
        form._pendingLamellaDirection = product.lamella_direction;
        await this.restoreShape(form, product.shape, product.shape_data);

        // Grupa cenowa na tym formularzu (przed wymiarami - wplywa na ceny)
        const clientType = this.quoteData.settings.clientType;
        if (clientType) {
            const select = form.querySelector('select[data-field="clientType"]');
            if (select) select.value = clientType;
        }

        // Wymiary - ustawiamy sekwencyjnie z delay miedzy polami
        this.setField(form, '[data-field="length"]', product.length);
        await this.delay(50);
        this.setField(form, '[data-field="width"]', product.width);
        await this.delay(50);
        this.setField(form, '[data-field="thickness"]', product.thickness);
        await this.delay(50);
        this.setField(form, '[data-field="quantity"]', product.quantity);

        // Poczekaj na przeliczenie cen po wymiarach
        await this.delay(400);

        // Wybrany wariant
        if (product.selectedVariant) {
            const radio = form.querySelector(
                `.variants input[type="radio"][value="${product.selectedVariant}"]`
            );
            if (radio) {
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));

                // Dodaj klase selected do parent
                const variantOption = radio.closest('.variant-option');
                if (variantOption) {
                    form.querySelectorAll('.variant-option.selected').forEach(el => {
                        el.classList.remove('selected');
                    });
                    variantOption.classList.add('selected');
                }
            }
            await this.delay(150);
        }

        // Wykonczenie
        await this.restoreFinishing(form, product.finishing);

        // Krawedzie
        this.restoreEdges(form, product.edges);

        // Docięcie do wymiaru (per-produkt)
        if (window.cutToSize) {
            const cts = product.cut_to_size;
            window.cutToSize.set(form, cts === undefined || cts === null ? true : cts);
        }
    }

    // ========================================
    // RESTORE: KSZTALT
    // ========================================

    async restoreShape(form, shape, shapeData) {
        // Mapowanie legacy 'round' na 'circle'
        var mappedShape = shape === 'round' ? 'circle' : (shape || 'rectangular');

        var editor = form._shapeEditor;
        if (editor) {
            // Parse shape_data jesli string
            var parsedData = shapeData;
            if (typeof shapeData === 'string') {
                try { parsedData = JSON.parse(shapeData); } catch(e) { parsedData = null; }
            }
            editor.restore(mappedShape, parsedData);
            // Przywroc kierunek lameli
            if (typeof form._pendingLamellaDirection !== 'undefined' && form._pendingLamellaDirection !== null && editor.setLamellaDirection) {
                editor.setLamellaDirection(form._pendingLamellaDirection);
                delete form._pendingLamellaDirection;
            }
        } else {
            // Fallback: ustaw dropdown bezposrednio
            var select = form.querySelector('[data-field="shapeSelect"]');
            if (select) {
                select.value = mappedShape;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
            form.dataset.productShape = mappedShape;
        }

        await this.delay(50);
    }

    /**
     * Drugie przejscie naprawiajace ksztalty (radio groups w roznych formularzach
     * moga sie nadpisywac nawzajem)
     */
    async restoreShapesSecondPass(products) {
        const forms = document.querySelectorAll('.quote-form');
        for (let i = 0; i < products.length; i++) {
            const form = forms[i];
            if (!form || !products[i]) continue;

            const shape = products[i].shape || 'rectangular';
            const mappedShape = shape === 'round' ? 'circle' : shape;
            form.dataset.productShape = mappedShape;

            const select = form.querySelector('[data-field="shapeSelect"]');
            if (select && select.value !== mappedShape) {
                select.value = mappedShape;
            }

            // Ukryj length/width wrappery dla nie-prostokatnych ksztaltow
            if (mappedShape !== 'rectangular') {
                const lengthWrap = form.querySelector('[data-dim-field="length-wrapper"]');
                const widthWrap = form.querySelector('[data-dim-field="width-wrapper"]');
                if (lengthWrap) lengthWrap.style.display = 'none';
                if (widthWrap) widthWrap.style.display = 'none';
            }
        }
    }

    // ========================================
    // RESTORE: WYKONCZENIE
    // ========================================

    async restoreFinishing(form, finishing) {
        if (!finishing || !finishing.type || finishing.type === 'Surowe') return;


        // Nowy system - drzewko hierarchiczne
        const treeContainer = form.querySelector('.finishing-tree-container');

        if (treeContainer) {
            // Poziom 0: typ (np. "Lakierowanie")
            const typeBtn = treeContainer.querySelector(
                `.finishing-option-btn[data-option-name="${finishing.type}"]`
            );
            if (typeBtn) {
                typeBtn.click();
                await this.delay(150);

                // Poziom 1: wariant (np. "Bezbarwne", "Barwne")
                if (finishing.variant) {
                    const variantBtn = treeContainer.querySelector(
                        `.finishing-option-btn[data-option-name="${finishing.variant}"]`
                    );
                    if (variantBtn) {
                        variantBtn.click();
                        await this.delay(150);

                        // Poziom 2: kolor
                        if (finishing.color) {
                            const colorBtn = treeContainer.querySelector(
                                `.finishing-option-btn[data-option-name="${finishing.color}"]`
                            );
                            if (colorBtn) {
                                colorBtn.click();
                                await this.delay(100);
                            }
                        }
                    }
                }

                // Połysk - klikamy przycisk żeby uruchomić handler z calculateFinishingCost
                if (finishing.gloss) {
                    const glossBtn = treeContainer.querySelector(`.finishing-gloss-btn[data-gloss-value="${finishing.gloss}"]`);
                    if (glossBtn) {
                        glossBtn.click();
                        await this.delay(100);
                    }
                }
            }

            // Po ustawieniu wszystkich opcji wykończenia, przelicz koszt
            if (typeof calculateFinishingCost === 'function') {
                calculateFinishingCost(form);
            }
        } else {
            // Stary system - fallback
            const typeBtn = form.querySelector(`[data-finishing-type="${finishing.type}"]`);
            if (typeBtn) {
                typeBtn.click();
                await this.delay(100);
            }
            if (finishing.variant) {
                const variantBtn = form.querySelector(`[data-finishing-variant="${finishing.variant}"]`);
                if (variantBtn) {
                    variantBtn.click();
                    await this.delay(100);
                }
            }
            if (finishing.color) {
                const colorBtn = form.querySelector(`[data-finishing-color="${finishing.color}"]`);
                if (colorBtn) {
                    colorBtn.click();
                    await this.delay(100);
                }
            }
            if (finishing.gloss) {
                const glossBtn = form.querySelector(`[data-finishing-gloss="${finishing.gloss}"]`);
                if (glossBtn) glossBtn.click();
            }
        }
    }

    // ========================================
    // RESTORE: KRAWEDZIE
    // ========================================

    restoreEdges(form, edges) {
        if (!edges || (!edges.type && !edges.mode)) return;


        // Zapisz do dataset
        if (edges.config) form.dataset.edgesData = JSON.stringify(edges.config);
        if (edges.type) form.dataset.edgesType = edges.type;
        if (edges.mode) form.dataset.edgesMode = edges.mode;
        if (edges.rValue) form.dataset.edgesRValue = edges.rValue;
        if (edges.angleValue) form.dataset.edgesAngleValue = edges.angleValue;
        if (edges.netto !== undefined) form.dataset.edgesNetto = edges.netto;
        if (edges.brutto !== undefined) form.dataset.edgesBrutto = edges.brutto;

        // Aktualizuj UI podsumowania krawedzi
        const summary = form.querySelector('.edges-options-summary');
        if (summary) {
            const edgesRow = summary.querySelector('.edges-row');
            if (edgesRow && edges.config) {
                const letters = edges.config.map(e => e.letter).sort().join(', ');
                let typeLabel;
                if (edges.type === 'chamfer') {
                    typeLabel = edges.angleValue
                        ? `Fazowanie R${edges.rValue} (${edges.angleValue})`
                        : `Fazowanie R${edges.rValue}`;
                } else {
                    typeLabel = `Zaokraglenie R${edges.rValue}`;
                }

                const textEl = edgesRow.querySelector('.edges-summary-text');
                const priceEl = edgesRow.querySelector('.edges-summary-price');
                const priceNettoEl = edgesRow.querySelector('.edges-summary-price-netto');

                if (textEl) textEl.textContent = `${typeLabel} - krawedzie: ${letters}`;
                if (priceEl) priceEl.textContent = `${parseFloat(edges.brutto).toFixed(2)} zl brutto`;
                if (priceNettoEl) priceNettoEl.textContent = `${parseFloat(edges.netto).toFixed(2)} zl netto`;

                summary.style.display = '';
                edgesRow.style.display = '';
            }
        }

        // SVG
        if (edges.svg) {
            form.dataset.edgesSvg = edges.svg;
        }
    }

    // ========================================
    // RESTORE: WYSYLKA
    // ========================================

    restoreShipping(settings) {
        if (!settings.courierName) return;

        const courierEl = document.getElementById('courier-name');
        const bruttoEl = document.getElementById('delivery-brutto');
        const nettoEl = document.getElementById('delivery-netto');

        // To sa spany (textContent), nie inputy (value)
        if (courierEl) courierEl.textContent = settings.courierName;
        if (bruttoEl) bruttoEl.textContent = parseFloat(settings.shippingBrutto || 0).toFixed(2) + ' PLN';
        if (nettoEl) nettoEl.textContent = parseFloat(settings.shippingNetto || 0).toFixed(2) + ' PLN';

        // Pokaz przycisk X
        const clearBtn = document.querySelector('.clear-delivery');
        if (clearBtn) clearBtn.style.display = '';

        // Przelicz sume calkowita
        if (typeof updateGlobalSummary === 'function') {
            updateGlobalSummary();
        }

        // Ustaw snapshot parametrow wysylki (zeby badge nieaktualnosci nie pojawial sie od razu)
        if (typeof setDeliveryParamsSnapshot === 'function') {
            setTimeout(() => setDeliveryParamsSnapshot(), 500);
        }
    }

    // ========================================
    // TRYB EDYCJI - UI
    // ========================================

    setEditMode() {
        // Globalna zmienna - uzywana przez save_quote.js
        window.quoteEditMode = {
            isActive: true,
            editUuid: this.editQuoteUuid,
            quoteId: this.quoteData.id,
            quoteNumber: this.quoteData.quote_number,
            client: this.quoteData.client,
            notes: this.quoteData.settings.notes,
            source: this.quoteData.settings.source,
            attachmentFilename: this.quoteData.settings.attachment_filename || null,
        };

        // Klasa na body
        document.body.classList.add('quote-edit-mode');

        // Tytul strony
        document.title = `Edycja wyceny #${this.quoteData.quote_number} - Kalkulator`;

        // Badge obok H1 (zamiast bannera)
        this.showEditModeBadge();

        // Info o kliencie i wycenie w sekcji podsumowania
        this.showEditInfoInSummary();

        // Zmien tekst przycisku "Zapisz wycene" na "Aktualizuj wycene"
        const saveBtn = document.querySelector('.save-quote span');
        if (saveBtn) saveBtn.textContent = 'Aktualizuj wycenę';

        // Ukryj badge backupu w trybie edycji
        const draftBadge = document.getElementById('draftStatusBadge');
        if (draftBadge) draftBadge.style.display = 'none';

    }

    showEditModeBadge() {
        const badge = document.createElement('div');
        badge.className = 'edit-mode-badge';
        badge.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
            </svg>
            <span>Edycja wyceny: <strong>${this.quoteData.quote_number}</strong></span>
        `;

        const headerRow = document.querySelector('.calculator-header-row');
        if (headerRow) {
            headerRow.appendChild(badge);
        }
    }

    showEditInfoInSummary() {
        const clientName = this.quoteData.client.client_name
            || this.quoteData.client.client_number
            || 'Nieznany';

        const infoDiv = document.createElement('div');
        infoDiv.className = 'edit-mode-summary-info';
        infoDiv.innerHTML = `
            <span class="input-txt-bold">Edycja wyceny:</span>
            <span class="edit-info-value">${this.quoteData.quote_number}</span>
            <span class="edit-info-client">${clientName}</span>
            <a href="/quotes?open_quote=${this.quoteData.id}" class="edit-info-cancel">Anuluj</a>
        `;

        const quoteSummary = document.querySelector('.quote-summary');
        if (quoteSummary) {
            quoteSummary.insertBefore(infoDiv, quoteSummary.firstChild);
        }
    }

    // ========================================
    // DETEKCJA ZMIAN (wlacz/wylacz przycisk)
    // ========================================

    initChangeDetection() {
        const saveBtn = document.querySelector('.save-quote');
        if (!saveBtn) return;

        // Wylacz przycisk na start
        saveBtn.disabled = true;

        // Poczekaj az dane sie ustabilizuja, zrob snapshot,
        // i DOPIERO POTEM podlacz listenery/observer.
        // Kolejnosc jest kluczowa — listenery przed snapshotem
        // powodowaly falszywe wykrycia zmian.
        setTimeout(() => {
            this.initialSnapshot = this.takeSnapshot();
            this._attachChangeListeners();
        }, 1500);
    }

    /**
     * Podlacza listenery i observer do detekcji zmian.
     * Wywolywane DOPIERO PO zrobieniu snapshota.
     */
    _attachChangeListeners() {
        console.log('[ChangeDetection] Listenery podlaczone, snapshot:', this.initialSnapshot?.substring(0, 200));

        const scheduleCheck = (reason) => {
            const src = reason instanceof Event ? `event:${reason.type} target:${reason.target?.tagName}.${reason.target?.className?.substring?.(0,30)}` : 'MutationObserver';
            console.log('[ChangeDetection] scheduleCheck z:', src);
            this.checkForChanges(src);
            setTimeout(() => this.checkForChanges(src + ' (delayed)'), 350);
        };

        const calculator = document.querySelector('.calculatorrr');
        if (calculator) {
            calculator.addEventListener('input', (e) => scheduleCheck(e), true);
            calculator.addEventListener('change', (e) => scheduleCheck(e), true);
        }

        // Dodanie/usunięcie produktu
        document.addEventListener('products-changed', () => scheduleCheck('products-changed'));

        // Zmiana/dodanie/usunięcie wysyłki
        document.addEventListener('delivery-changed', () => scheduleCheck('delivery-changed'));

        // MutationObserver na dataset formularzy (finishing, edges, shape)
        const forms = document.querySelectorAll('.quote-form');
        this.datasetObserver = new MutationObserver((mutations) => {
            const changed = mutations.map(m => m.attributeName).join(', ');
            console.log('[ChangeDetection] MutationObserver:', changed);
            scheduleCheck('MutationObserver: ' + changed);
        });
        forms.forEach(form => {
            this.datasetObserver.observe(form, { attributes: true, attributeFilter: ['data-finishing-type', 'data-finishing-variant', 'data-finishing-color', 'data-finishing-gloss', 'data-edges-type', 'data-edges-r-value', 'data-edges-angle-value', 'data-edges-brutto', 'data-edges-data', 'data-product-shape', 'data-shape-real-area-cm2', 'data-cut-to-size'] });
        });
    }

    takeSnapshot() {
        if (typeof collectQuoteData !== 'function') return null;
        const data = collectQuoteData();
        if (!data) return null;

        // Wyciagnij tylko to co wplywa na wycene
        const slim = {
            products: data.products.map(p => ({
                length: p.length,
                width: p.width,
                thickness: p.thickness,
                quantity: p.quantity,
                selectedVariant: p.variants.find(v => v.is_selected)?.variant_code || null,
                finishing_type: p.finishing_type,
                finishing_variant: p.finishing_variant,
                finishing_color: p.finishing_color,
                finishing_gloss: p.finishing_gloss_level,
                edges_type: p.edges_type,
                edges_r_value: p.edges_r_value,
                edges_angle_value: p.edges_angle_value,
                edges: p.edges ? JSON.stringify(p.edges) : null,
                shape: p.shape,
                shape_data: p.shape_data,
                cut_to_size: p.cut_to_size,
            })),
            courier_name: data.courier_name,
            shipping_cost_brutto: data.shipping_cost_brutto,
            quote_client_type: data.quote_client_type,
            quote_type: data.quote_type,
        };
        return JSON.stringify(slim);
    }

    checkForChanges(source) {
        if (!this.initialSnapshot) return;

        const current = this.takeSnapshot();
        const hasChanges = current !== this.initialSnapshot;

        if (hasChanges) {
            // Znajdz dokladnie co sie zmienilo
            try {
                const initial = JSON.parse(this.initialSnapshot);
                const curr = JSON.parse(current);
                const diffs = [];
                // Porownaj pola globalne
                ['courier_name', 'shipping_cost_brutto', 'quote_client_type', 'quote_type'].forEach(key => {
                    if (JSON.stringify(initial[key]) !== JSON.stringify(curr[key])) {
                        diffs.push(`${key}: ${JSON.stringify(initial[key])} → ${JSON.stringify(curr[key])}`);
                    }
                });
                // Porownaj produkty
                const maxLen = Math.max(initial.products?.length || 0, curr.products?.length || 0);
                for (let i = 0; i < maxLen; i++) {
                    const p1 = initial.products?.[i];
                    const p2 = curr.products?.[i];
                    if (!p1) { diffs.push(`Produkt ${i}: NOWY`); continue; }
                    if (!p2) { diffs.push(`Produkt ${i}: USUNIETY`); continue; }
                    Object.keys({...p1, ...p2}).forEach(key => {
                        if (JSON.stringify(p1[key]) !== JSON.stringify(p2[key])) {
                            diffs.push(`Produkt ${i}.${key}: ${JSON.stringify(p1[key])} → ${JSON.stringify(p2[key])}`);
                        }
                    });
                }
                console.warn('[ChangeDetection] ZMIANA WYKRYTA! Zrodlo:', source, '\nRoznice:', diffs);
            } catch(e) {
                console.warn('[ChangeDetection] ZMIANA WYKRYTA! Zrodlo:', source);
            }
        }

        const saveBtn = document.querySelector('.save-quote');
        if (saveBtn) {
            saveBtn.disabled = !hasChanges;
        }
    }

    // ========================================
    // OVERLAY LADOWANIA
    // ========================================

    showLoadingOverlay(message) {
        const overlay = document.getElementById('edit-overlay');
        if (overlay) {
            const textEl = document.getElementById('editLoadingText');
            if (textEl) textEl.textContent = message || 'Wczytywanie wyceny...';
            overlay.style.display = 'flex';
        }
    }

    updateProgress(percent) {
        const fill = document.getElementById('editProgressFill');
        const text = document.getElementById('editProgressPercent');
        if (fill) fill.style.width = Math.round(percent) + '%';
        if (text) text.textContent = Math.round(percent) + '%';
    }

    hideLoadingOverlay() {
        const overlay = document.getElementById('edit-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
        this.updateProgress(0);
    }

    // ========================================
    // HELPERS
    // ========================================

    setField(form, selector, value) {
        const field = form.querySelector(selector);
        if (field && value !== undefined && value !== null) {
            field.value = value;
            field.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Eksport globalny
window.QuoteEditLoader = QuoteEditLoader;
