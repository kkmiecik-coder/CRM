/**
 * Quote Draft Backup System using localStorage + Server-side sync
 * Replaces cookie-based system with localStorage (primary) and server backup (secondary)
 * Status indicator integration for visual feedback
 */

class QuoteDraftBackup {
    constructor() {
        this.saveDebounceMs = 5000; // 5 sekund po ostatniej zmianie
        this.serverSyncInterval = 30000; // 30 sekund
        this.validityHours = 24;
        this.userId = null;
        this._saveDebounceTimer = null;
        this.serverSyncIntervalId = null;
        this.storagePrefix = 'woodpower_draft';
        this.version = '2.0';
        this.isQuoteSaved = false;
        this.lastSavedData = null;
        this._checkIconUntil = 0; // timestamp do kiedy fajka ma byc widoczna
        this._spinnerUntil = 0; // timestamp do kiedy spinner ma byc widoczny
        this._ignoreChanges = false; // blokuje detekcje zmian podczas przywracania
        this._restoredUntil = 0; // timestamp do kiedy status "Przywrocono" jest chroniony
        this._lastSaveTime = ''; // czas ostatniego zapisu (HH:MM:SS)
    }

    // ========================================
    // STORAGE METHODS (localStorage)
    // ========================================

    saveToStorage(key, data) {
        try {
            localStorage.setItem(key, JSON.stringify(data));
            return true;
        } catch (e) {
            console.error('[QuoteDraftBackup] localStorage save error:', e);
            return false;
        }
    }

    loadFromStorage(key) {
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (e) {
            console.error('[QuoteDraftBackup] localStorage load error:', e);
            return null;
        }
    }

    removeFromStorage(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.error('[QuoteDraftBackup] localStorage remove error:', e);
        }
    }

    getStorageKey() {
        return `${this.storagePrefix}_${this.userId}`;
    }

    // ========================================
    // INITIALIZATION
    // ========================================

    init(userId) {
        this.userId = userId;
        this._ignoreChanges = true; // Ignoruj zmiany podczas inicjalizacji

        // Migracja ze starych cookies (jesli istnieja)
        this.migrateCookies();

        // Sprawdz czy istnieje draft do przywrocenia
        this.checkExistingDraft();

        // Rozpocznij automatyczne zapisywanie
        this.startAutoSave();

        // Listener na przycisk recznego zapisu
        this.bindSaveButton();

        // Inicjalizuj szerokosc wrappera tekstu statusu
        this._initTextWrapWidth();

        // Ustaw stan przycisku zapisu
        this.updateSaveButtonDisabled();

        // Listener na zmiany w formularzu
        this.bindChangeDetection();

        // Odblokuj detekcje zmian po ustabilizowaniu sie DOM
        // (jesli jest draft do przywrocenia, restoreQuote zarzadza flaga samodzielnie)
        setTimeout(() => {
            if (this._ignoreChanges) {
                this._ignoreChanges = false;
            }
        }, 2000);
    }

    // ========================================
    // AUTO-SAVE
    // ========================================

    startAutoSave() {
        // Server sync co 30s
        if (this.serverSyncIntervalId) {
            clearInterval(this.serverSyncIntervalId);
        }
        this.serverSyncIntervalId = setInterval(() => {
            this.syncToServer();
        }, this.serverSyncInterval);

    }

    stopAutoSave() {
        if (this._saveDebounceTimer) {
            clearTimeout(this._saveDebounceTimer);
            this._saveDebounceTimer = null;
        }
        if (this.serverSyncIntervalId) {
            clearInterval(this.serverSyncIntervalId);
            this.serverSyncIntervalId = null;
        }
    }

    /**
     * Planuje zapis 5s po ostatniej zmianie (debounce)
     */
    scheduleSave() {
        if (this.isQuoteSaved) return;

        if (this._saveDebounceTimer) {
            clearTimeout(this._saveDebounceTimer);
        }

        this._saveDebounceTimer = setTimeout(() => {
            this._saveDebounceTimer = null;
            this.setSaveButtonIcon('spinner');
            this.updateStatusIndicator('saving', 'Zapisywanie kopii...');
            this.saveCurrentState();
        }, this.saveDebounceMs);
    }

    // ========================================
    // SAVE CURRENT STATE
    // ========================================

    saveCurrentState() {
        if (this.isQuoteSaved) {
            return;
        }

        try {
            const quoteData = this.collectQuoteData();

            if (!quoteData.products || quoteData.products.length === 0) {
                // Wroc do normalnego stanu - nie zostawiaj spinnera
                this._spinnerUntil = 0;
                this.setSaveButtonIcon('floppy');
                this.updateStatusIndicator('idle', 'Brak zmian');
                return;
            }

            // Dodaj metadane
            const draftData = {
                ...quoteData,
                expires: Date.now() + (this.validityHours * 60 * 60 * 1000),
                savedAt: new Date().toISOString()
            };

            const success = this.saveToStorage(this.getStorageKey(), draftData);

            if (success) {
                this.lastSavedData = draftData;
                this.showCheckConfirmation();
            } else {
                this.updateStatusIndicator('error', 'Błąd zapisu kopii');
            }

        } catch (error) {
            console.error('[QuoteDraftBackup] Blad podczas zapisywania:', error);
            this.updateStatusIndicator('error', 'Błąd zapisu kopii');
        }
    }

    // ========================================
    // COLLECT DATA
    // ========================================

    collectQuoteData() {
        const timestamp = Date.now();
        const quoteFormsContainer = document.querySelector('.quote-forms');
        const forms = Array.from(quoteFormsContainer?.querySelectorAll('.quote-form') || []);

        let clientType = null;
        let multiplier = 1.0;
        let quoteType = 'brutto';

        if (forms.length > 0) {
            const firstForm = forms[0];
            const clientTypeSelect = firstForm.querySelector('select[data-field="clientType"]');
            clientType = clientTypeSelect?.value || null;

            if (clientType && window.multiplierMapping && window.multiplierMapping[clientType]) {
                multiplier = window.multiplierMapping[clientType];
            } else if (window.isPartner && window.userMultiplier) {
                multiplier = window.userMultiplier;
                clientType = 'Partner';
            }

            if (typeof window.getCurrentPriceMode === 'function') {
                quoteType = window.getCurrentPriceMode();
            } else {
                const nettoRadio = document.getElementById('priceModeNetto');
                if (nettoRadio && nettoRadio.checked) {
                    quoteType = 'netto';
                }
            }
        }

        const products = [];

        forms.forEach((form, index) => {
            const productData = this.extractProductData(form, index);
            products.push(productData);
        });

        return {
            timestamp,
            userId: this.userId,
            version: this.version,
            clientType,
            multiplier,
            quoteType,
            totalProducts: products.length,
            products
        };
    }

    extractProductData(form, index) {
        const lengthVal = form.querySelector('[data-field="length"]')?.value;
        const widthVal = form.querySelector('[data-field="width"]')?.value;
        const thicknessVal = form.querySelector('[data-field="thickness"]')?.value;
        const quantityVal = form.querySelector('[data-field="quantity"]')?.value;

        const length = lengthVal !== '' && lengthVal != null ? parseFloat(lengthVal) : null;
        const width = widthVal !== '' && widthVal != null ? parseFloat(widthVal) : null;
        const thickness = thicknessVal !== '' && thicknessVal != null ? parseFloat(thicknessVal) : null;
        const quantity = quantityVal !== '' && quantityVal != null ? parseInt(quantityVal) : null;

        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
        const selectedVariant = selectedRadio ? selectedRadio.value : null;

        const shape = form.dataset.productShape || 'rectangular';

        const finishingType = form.dataset.finishingType || 'Surowe';
        const finishingVariant = form.dataset.finishingVariant || null;
        const finishingColor = form.dataset.finishingColor || null;
        const finishingFullPath = form.dataset.finishingFullPath || null;
        const finishingOptionId = form.dataset.finishingOptionId || null;
        const finishingGloss = form.dataset.finishingGloss || null;

        const clientType = form.querySelector('select[data-field="clientType"]')?.value || null;

        let edges = null;
        if (form.dataset.edgesData) {
            try {
                edges = {
                    data: JSON.parse(form.dataset.edgesData),
                    type: form.dataset.edgesType || 'round',
                    rValue: parseInt(form.dataset.edgesRValue) || 5,
                    angleValue: form.dataset.edgesAngleValue ? parseInt(form.dataset.edgesAngleValue) : null,
                    netto: parseFloat(form.dataset.edgesNetto) || 0,
                    brutto: parseFloat(form.dataset.edgesBrutto) || 0
                };
            } catch (e) {
                // Ignore errors when reading edges data from form dataset
            }
        }

        return {
            index,
            length,
            width,
            thickness,
            quantity,
            selectedVariant,
            shape,
            clientType,
            finishing: {
                type: finishingType,
                variant: finishingVariant,
                color: finishingColor,
                fullPath: finishingFullPath,
                optionId: finishingOptionId,
                gloss: finishingGloss
            },
            edges
        };
    }

    /**
     * Sprawdza czy kalkulator ma jakiekolwiek dane warte zapisania
     */
    hasAnyData() {
        const forms = document.querySelectorAll('.quote-forms .quote-form');
        for (const form of forms) {
            const l = form.querySelector('[data-field="length"]')?.value;
            const w = form.querySelector('[data-field="width"]')?.value;
            const t = form.querySelector('[data-field="thickness"]')?.value;
            if ((l && l !== '0') || (w && w !== '0') || (t && t !== '0')) return true;
        }
        return false;
    }

    isProductComplete(productData) {
        const hasBasicDimensions = productData.length > 0 &&
            productData.width > 0 &&
            productData.thickness > 0;

        const hasClientType = productData.clientType || window.isPartner;

        return hasBasicDimensions && hasClientType;
    }

    // ========================================
    // CHECK & RESTORE
    // ========================================

    async checkExistingDraft() {
        try {
            // Sprawdz localStorage
            let draftData = this.loadFromStorage(this.getStorageKey());

            // Jesli brak w localStorage, sprawdz serwer
            if (!draftData) {
                const serverDraft = await this.loadFromServer();
                if (serverDraft) {
                    draftData = serverDraft;
                    // Zapisz do localStorage na przyszlosc
                    this.saveToStorage(this.getStorageKey(), draftData);
                }
            } else if (draftData) {
                // Mamy localStorage, sprawdz czy serwer ma nowszy
                try {
                    const serverDraft = await this.loadFromServer();
                    if (serverDraft && serverDraft.timestamp > draftData.timestamp) {
                        draftData = serverDraft;
                        this.saveToStorage(this.getStorageKey(), draftData);
                    }
                } catch (e) {
                    // Server niedostepny - uzyj localStorage
                }
            }

            if (draftData && this.isDraftValid(draftData)) {
                this.showRestoreModal(draftData);
            } else if (draftData) {
                this.clearDraft();
            }
        } catch (error) {
            console.error('[QuoteDraftBackup] Blad podczas sprawdzania draftu:', error);
            this.clearAllDrafts();
        }
    }

    isDraftValid(draftData) {
        if (!draftData || !draftData.expires) {
            return false;
        }
        return Date.now() < draftData.expires;
    }

    // ========================================
    // RESTORE MODAL & QUOTE
    // ========================================

    showRestoreModal(draftData) {
        let modal = document.getElementById('autosave-modal');
        if (!modal) {
            console.error('[QuoteDraftBackup] Modal przywracania nie zostal znaleziony');
            return;
        }

        const timeAgo = this.getTimeAgo(draftData.timestamp);
        document.getElementById('draft-timestamp').textContent = timeAgo;

        this.generateProductsList(draftData.products);

        document.getElementById('restore-quote-btn').onclick = () => this.restoreQuote(draftData);
        document.getElementById('new-quote-btn').onclick = () => this.startNewQuote();

        modal.style.display = 'flex';
    }

    generateProductsList(products) {
        const container = document.getElementById('products-list');
        container.innerHTML = '';

        const miss = '<span style="color:#ef4444;font-weight:700;font-size:1.2em">?</span>';

        products.forEach((product, index) => {
            const productDiv = document.createElement('div');
            productDiv.className = 'product-item';

            const l = product.length != null ? product.length : miss;
            const w = product.width != null ? product.width : miss;
            const t = product.thickness != null ? product.thickness : miss;

            let description = `Produkt ${index + 1} - ${l}x${w}x${t}cm`;

            if (product.selectedVariant) {
                const variantName = this.getVariantDisplayName(product.selectedVariant);
                description = `${variantName} ${l}x${w}x${t}cm`;
            }

            if (product.shape === 'round') {
                description += ' (okragly)';
            }

            if (product.finishing && product.finishing.type !== 'Surowe') {
                description += ` ${product.finishing.type.toLowerCase()}`;
                if (product.finishing.variant) {
                    description += ` ${product.finishing.variant.toLowerCase()}`;
                }
                if (product.finishing.color) {
                    description += ` (${product.finishing.color})`;
                }
            } else {
                description += ' surowy';
            }

            if (product.edges && product.edges.data && product.edges.data.length > 0) {
                const edgeLetters = product.edges.data.map(e => e.letter).sort().join(', ');
                const edgeTypeLabel = product.edges.type === 'chamfer' ? 'fazowanie' : 'zaokraglenie';
                description += ` + ${edgeTypeLabel} R${product.edges.rValue} (${edgeLetters})`;
            }

            productDiv.innerHTML = description;
            container.appendChild(productDiv);
        });
    }

    getVariantDisplayName(variantCode) {
        const variantNames = {
            'dab-lity-ab': 'Dab lity A/B',
            'dab-lity-bb': 'Dab lity B/B',
            'dab-micro-ab': 'Dab mikrowczep A/B',
            'dab-micro-bb': 'Dab mikrowczep B/B',
            'jes-lity-ab': 'Jesion lity A/B',
            'jes-micro-ab': 'Jesion mikrowczep A/B',
            'buk-lity-ab': 'Buk lity A/B',
            'buk-micro-ab': 'Buk mikrowczep A/B'
        };

        return variantNames[variantCode] || variantCode;
    }

    getTimeAgo(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;
        const minutes = Math.floor(diff / (1000 * 60));
        const hours = Math.floor(diff / (1000 * 60 * 60));

        if (minutes < 1) {
            return 'przed chwila';
        } else if (minutes === 1) {
            return '1 minute temu';
        } else if (minutes < 5) {
            return `${minutes} minuty temu`;
        } else if (minutes < 60) {
            return `${minutes} minut temu`;
        } else if (hours === 1) {
            return '1 godzine temu';
        } else if (hours < 5) {
            return `${hours} godziny temu`;
        } else {
            return `${hours} godzin temu`;
        }
    }

    async restoreQuote(draftData) {
        try {
            this._ignoreChanges = true;
            this.showLoadingOverlay('Przygotowanie...');
            this.updateProgress(0);
            document.getElementById('autosave-modal').style.display = 'none';
            this.stopAutoSave();

            const totalProducts = draftData.products.length;
            // Wagi etapow: przygotowanie 5%, ustawienia 10%, produkty 75%, finalizacja 10%
            const PREP_WEIGHT = 5;
            const SETTINGS_WEIGHT = 10;
            const PRODUCTS_WEIGHT = 75;
            const FINALIZE_WEIGHT = 10;


            // Etap 1: Czyszczenie kalkulatora
            this.showLoadingOverlay('Czyszczenie kalkulatora...');
            await this.clearCurrentCalculator();
            this.updateProgress(PREP_WEIGHT);

            // Etap 2: Ustawienia (grupa cenowa, tryb cen)
            this.showLoadingOverlay('Przywracanie ustawień...');
            if (draftData.clientType) {
                await this.restoreClientType(draftData.clientType);
            }

            if (draftData.quoteType) {
                const bruttoRadio = document.getElementById('priceModeBrutto');
                const nettoRadio = document.getElementById('priceModeNetto');

                if (draftData.quoteType === 'netto' && nettoRadio) {
                    nettoRadio.checked = true;
                    nettoRadio.dispatchEvent(new Event('change', { bubbles: true }));
                } else if (bruttoRadio) {
                    bruttoRadio.checked = true;
                    bruttoRadio.dispatchEvent(new Event('change', { bubbles: true }));
                }

                await this.delay(100);
            }
            this.updateProgress(PREP_WEIGHT + SETTINGS_WEIGHT);

            // Etap 3: Przywracanie produktow
            for (let i = 0; i < totalProducts; i++) {
                this.showLoadingOverlay(`Przywracanie produktu ${i + 1} z ${totalProducts}...`);
                await this.restoreProduct(draftData.products[i], i);
                await this.delay(200);

                const productProgress = PREP_WEIGHT + SETTINGS_WEIGHT +
                    ((i + 1) / totalProducts) * PRODUCTS_WEIGHT;
                this.updateProgress(Math.round(productProgress));
            }

            // Etap 4: Finalizacja (ksztalty, aktywacja)
            this.showLoadingOverlay('Finalizacja...');
            const allRestoredForms = document.querySelectorAll('.quote-form');
            for (let i = 0; i < totalProducts; i++) {
                const form = allRestoredForms[i];
                if (form && draftData.products[i]) {
                    const shape = draftData.products[i].shape || 'rectangular';
                    const mappedShape = shape === 'round' ? 'circle' : shape;
                    const editor = form._shapeEditor;
                    if (editor) {
                        editor.restore(mappedShape, draftData.products[i].shape_data || null);
                    } else {
                        const shapeSelect = form.querySelector('[data-field="shapeSelect"]');
                        if (shapeSelect) shapeSelect.value = mappedShape;
                        form.dataset.productShape = mappedShape;
                    }
                }
            }
            this.updateProgress(100);

            // Nie kasuj draftu - zostaje w localStorage/serwerze az do zapisania wyceny
            this.startAutoSave();


            this.hideLoadingOverlay();

            if (typeof activateProductCard === 'function') {
                activateProductCard(0);
            }

            // Ustaw status po przywroceniu
            const restoreTime = new Date();
            const timeStr = restoreTime.getHours().toString().padStart(2, '0') + ':'
                + restoreTime.getMinutes().toString().padStart(2, '0') + ':'
                + restoreTime.getSeconds().toString().padStart(2, '0');
            this._restoredUntil = Date.now() + 3000;
            this.updateStatusIndicator('saved', 'Przywrócono kopię zapasową', timeStr);
            this.setSaveButtonIcon('floppy');

            // Ignoruj zmiany az DOM sie ustabilizuje (przeliczenia cen itp.)
            setTimeout(() => {
                this._ignoreChanges = false;
            }, 3000);

        } catch (error) {
            this._ignoreChanges = false;
            console.error('[QuoteDraftBackup] Blad podczas przywracania:', error);
            this.hideLoadingOverlay();
            this.showError('Wystapil blad podczas wczytywania wyceny: ' + error.message);
        }
    }

    async clearCurrentCalculator() {
        const quoteFormsContainer = document.querySelector('.quote-forms');
        if (!quoteFormsContainer) return;

        const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
        for (let i = forms.length - 1; i > 0; i--) {
            forms[i].remove();
        }

        if (forms[0]) {
            this.clearProductForm(forms[0]);
        }
    }

    clearProductForm(form) {
        form.querySelectorAll('input[data-field]').forEach(input => {
            if (input.type === 'radio') return;
            input.value = '';
        });

        const clientTypeSelect = form.querySelector('select[data-field="clientType"]');
        if (clientTypeSelect) {
            clientTypeSelect.selectedIndex = 0;
        }

        form.querySelectorAll('.variants input[type="radio"]').forEach(radio => {
            radio.checked = false;
        });

        const shapeSelect = form.querySelector('[data-field="shapeSelect"]');
        if (shapeSelect) shapeSelect.value = 'rectangular';
        form.dataset.productShape = 'rectangular';

        form.querySelectorAll('.finishing-btn.active, .color-btn.active, .finishing-option-btn.active').forEach(btn => {
            btn.classList.remove('active');
        });

        form.dataset.finishingType = 'Surowe';
        form.dataset.finishingVariant = '';
        form.dataset.finishingColor = '';
        form.dataset.finishingGloss = '';
        form.dataset.finishingFullPath = 'Surowe';
        form.dataset.finishingOptionId = '';
        form.dataset.finishingBrutto = '';
        form.dataset.finishingNetto = '';

        if (typeof renderFinishingTree === 'function') {
            renderFinishingTree(form);
        } else {
            const defaultFinishing = form.querySelector('.finishing-btn[data-finishing-type="Surowe"]');
            if (defaultFinishing) {
                defaultFinishing.classList.add('active');
            }
        }

        const sections = ['finishing-wrapper', 'color-section', 'gloss-section'];
        sections.forEach(sectionClass => {
            const section = form.querySelector(`.${sectionClass}`);
            if (section) {
                section.style.display = 'none';
            }
        });

        delete form.dataset.edgesData;
        delete form.dataset.edgesType;
        delete form.dataset.edgesRValue;
        delete form.dataset.edgesNetto;
        delete form.dataset.edgesBrutto;

        const finishingOptionsSummary = form.querySelector('.finishing-options-summary');
        if (finishingOptionsSummary) {
            finishingOptionsSummary.style.display = 'none';
            const finishingRow = finishingOptionsSummary.querySelector('.finishing-row');
            if (finishingRow) finishingRow.style.display = 'none';
        }

        const edgesOptionsSummary = form.querySelector('.edges-options-summary');
        if (edgesOptionsSummary) {
            edgesOptionsSummary.style.display = 'none';
            const edgesRow = edgesOptionsSummary.querySelector('.edges-row');
            if (edgesRow) edgesRow.style.display = 'none';
        }
    }

    async restoreClientType(clientType) {
        const forms = document.querySelectorAll('.quote-form');
        forms.forEach(form => {
            const select = form.querySelector('select[data-field="clientType"]');
            if (select) {
                select.value = clientType;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });

        await this.delay(100);
    }

    async restoreProduct(productData, index) {
        if (index > 0) {
            if (typeof addNewProduct === 'function') {
                addNewProduct();
                await this.delay(300);
            }
        }

        const forms = document.querySelectorAll('.quote-form');
        const form = forms[index];

        if (!form) {
            throw new Error(`Nie mozna znalezc formularza dla produktu ${index + 1}`);
        }

        if (productData.shape && productData.shape !== 'rectangular') {
            const mappedShape = productData.shape === 'round' ? 'circle' : productData.shape;
            const editor = form._shapeEditor;
            if (editor) {
                editor.restore(mappedShape, productData.shape_data || null);
            } else {
                const shapeSelect = form.querySelector('[data-field="shapeSelect"]');
                if (shapeSelect) {
                    shapeSelect.value = mappedShape;
                    shapeSelect.dispatchEvent(new Event('change', { bubbles: true }));
                }
                form.dataset.productShape = mappedShape;
            }
        }

        await this.restoreFormField(form, '[data-field="length"]', productData.length);
        await this.restoreFormField(form, '[data-field="width"]', productData.width);
        await this.restoreFormField(form, '[data-field="thickness"]', productData.thickness);
        await this.restoreFormField(form, '[data-field="quantity"]', productData.quantity);

        if (productData.clientType) {
            const select = form.querySelector('select[data-field="clientType"]');
            if (select) {
                select.value = productData.clientType;
            }
        }

        await this.delay(200);

        if (productData.selectedVariant) {
            const radio = form.querySelector(`input[type="radio"][value="${productData.selectedVariant}"]`);
            if (radio) {
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        await this.restoreFinishing(form, productData.finishing);
        await this.restoreEdges(form, productData.edges);
    }

    async restoreFormField(form, selector, value) {
        const field = form.querySelector(selector);
        if (field && value !== undefined && value !== null) {
            field.value = value;
            field.dispatchEvent(new Event('input', { bubbles: true }));
            await this.delay(50);
        }
    }

    async restoreFinishing(form, finishing) {
        if (!finishing || finishing.type === 'Surowe') {
            return;
        }


        const finishingTreeContainer = form.querySelector('.finishing-tree-container');

        if (finishingTreeContainer) {
            const typeBtn = finishingTreeContainer.querySelector(
                `.finishing-option-btn[data-option-name="${finishing.type}"]`
            );

            if (typeBtn) {
                typeBtn.click();
                await this.delay(100);

                if (finishing.variant) {
                    const variantBtn = finishingTreeContainer.querySelector(
                        `.finishing-option-btn[data-option-name="${finishing.variant}"]`
                    );
                    if (variantBtn) {
                        variantBtn.click();
                        await this.delay(100);

                        if (finishing.color) {
                            const colorBtn = finishingTreeContainer.querySelector(
                                `.finishing-option-btn[data-option-name="${finishing.color}"]`
                            );
                            if (colorBtn) {
                                colorBtn.click();
                                await this.delay(100);
                            }
                        }
                    }
                }

                // Połysk
                if (finishing.gloss) {
                    const glossBtn = finishingTreeContainer.querySelector(`.finishing-gloss-btn[data-gloss-value="${finishing.gloss}"]`);
                    if (glossBtn) {
                        finishingTreeContainer.querySelectorAll('.finishing-gloss-btn').forEach(b => b.classList.remove('active'));
                        glossBtn.classList.add('active');
                        form.dataset.finishingGloss = finishing.gloss;
                    }
                }
            }
        } else {
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
                if (glossBtn) {
                    glossBtn.click();
                    await this.delay(100);
                }
            }
        }
    }

    async restoreEdges(form, edges) {
        if (!edges || !edges.data || edges.data.length === 0) {
            return;
        }


        form.dataset.edgesData = JSON.stringify(edges.data);
        form.dataset.edgesType = edges.type || 'round';
        form.dataset.edgesRValue = edges.rValue || 5;
        form.dataset.edgesNetto = edges.netto || 0;
        form.dataset.edgesBrutto = edges.brutto || 0;

        if (edges.angleValue) {
            form.dataset.edgesAngleValue = edges.angleValue;
        }

        const edgesOptionsSummary = form.closest('.quote-form')?.querySelector('.edges-options-summary');
        if (edgesOptionsSummary) {
            const edgesRow = edgesOptionsSummary.querySelector('.edges-row');
            if (edgesRow) {
                const edgeLetters = edges.data.map(e => e.letter).sort().join(', ');
                let edgeTypeLabel;
                if (edges.type === 'chamfer') {
                    edgeTypeLabel = edges.angleValue ? `Fazowanie R${edges.rValue} (${edges.angleValue})` : `Fazowanie R${edges.rValue}`;
                } else {
                    edgeTypeLabel = `Zaokraglenie R${edges.rValue}`;
                }
                const summaryText = `${edgeTypeLabel} - krawedzie: ${edgeLetters}`;

                const textEl = edgesRow.querySelector('.edges-summary-text');
                const priceEl = edgesRow.querySelector('.edges-summary-price');
                let priceNettoEl = edgesRow.querySelector('.edges-summary-price-netto');

                if (!priceNettoEl) {
                    const content = edgesRow.querySelector('.options-summary-content');
                    if (content) {
                        priceNettoEl = document.createElement('span');
                        priceNettoEl.className = 'options-summary-price-netto edges-summary-price-netto';
                        content.appendChild(priceNettoEl);
                    }
                }

                if (textEl) textEl.textContent = summaryText;
                if (priceEl) priceEl.textContent = `${edges.brutto.toFixed(2)} zl brutto`;
                if (priceNettoEl) priceNettoEl.textContent = `${edges.netto.toFixed(2)} zl netto`;

                edgesRow.style.display = 'flex';
                edgesOptionsSummary.style.display = 'flex';
            }
        }

        if (typeof EdgesModule !== 'undefined' && EdgesModule.updateOpenButton) {
            EdgesModule.updateOpenButton(form);
        }

        if (typeof EdgesModule !== 'undefined' && EdgesModule.openModal) {
            try {
                EdgesModule.openModal(form);
                await this.delay(200);

                const applyBtn = document.getElementById('applyEdgesBtn');
                if (applyBtn) {
                    applyBtn.click();
                } else {
                    EdgesModule.closeModal();
                }
            } catch (e) {
                if (typeof EdgesModule !== 'undefined' && EdgesModule.closeModal) {
                    EdgesModule.closeModal();
                }
            }
        }

        await this.delay(100);
    }

    // ========================================
    // CLEAR & NEW QUOTE
    // ========================================

    startNewQuote() {
        document.getElementById('autosave-modal').style.display = 'none';
        this.clearDraft();
        // Reset trybu cen na brutto przy nowej wycenie
        this.resetPriceModeToBrutto();
    }

    clearDraft() {
        this.clearExistingDrafts();
        this.deleteFromServer();
    }

    clearExistingDrafts() {
        this.removeFromStorage(this.getStorageKey());
        // Wyczysc tez stare cookies jesli istnieja
        this.clearLegacyCookies();
    }

    clearAllDrafts() {
        // Usun z localStorage
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith(this.storagePrefix)) {
                keysToRemove.push(key);
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));

        // Usun stare cookies
        this.clearLegacyCookies();

        // Usun z serwera
        this.deleteFromServer();

    }

    // ========================================
    // MARK AS SAVED / RESET
    // ========================================

    markQuoteAsSaved(quoteNumber) {
        this.isQuoteSaved = true;
        this.stopAutoSave();
        this.clearDraft();
        this.updateStatusIndicator('quote-saved', 'Wycena zapisana', quoteNumber || '');
    }

    resetForNewQuote() {
        this.isQuoteSaved = false;
        this.clearDraft();
        this.resetPriceModeToBrutto();
        this.updateStatusIndicator('idle', 'Brak zmian');
        this.startAutoSave();
    }

    resetPriceModeToBrutto() {
        const bruttoRadio = document.getElementById('priceModeBrutto');
        if (bruttoRadio && !bruttoRadio.checked) {
            bruttoRadio.checked = true;
            bruttoRadio.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    // ========================================
    // SERVER-SIDE SYNC (Faza 2)
    // ========================================

    async syncToServer() {
        if (this.isQuoteSaved) return;

        const draftData = this.loadFromStorage(this.getStorageKey());
        if (!draftData) return;

        try {
            const response = await fetch('/calculator/api/draft', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ draft_data: draftData })
            });

            if (response.ok) {
            }
        } catch (e) {
            // Server niedostepny - ciche niepowodzenie, localStorage jest primary
        }
    }

    async loadFromServer() {
        try {
            const response = await fetch('/calculator/api/draft', {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });

            if (response.ok) {
                const result = await response.json();
                if (result && result.draft_data) {
                    return result.draft_data;
                }
            }
            return null;
        } catch (e) {
            return null;
        }
    }

    async deleteFromServer() {
        try {
            await fetch('/calculator/api/draft', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (e) {
            // Ciche niepowodzenie
        }
    }

    // ========================================
    // STATUS INDICATOR (Faza 3)
    // ========================================

    updateStatusIndicator(state, message, time) {
        const badge = document.getElementById('draftStatusBadge');
        const wrap = document.getElementById('draftStatusTextWrap');
        const text = document.getElementById('draftStatusText');
        const timeEl = document.getElementById('draftStatusTime');

        if (!badge) return;

        // Zapamietaj czas zapisu jesli podany
        if (time !== undefined && time !== '') {
            this._lastSaveTime = time;
        }

        // Usun wszystkie klasy stanu
        badge.classList.remove('idle', 'unsaved', 'saving', 'saved', 'quote-saved', 'error');
        badge.classList.add(state);

        // Animacja tekstu statusu (slide)
        if (wrap && text && message !== undefined && text.textContent !== message) {
            this._animateTextChange(wrap, text, message);
        } else if (text && message !== undefined) {
            text.textContent = message || '';
        }

        // Zawsze pokazuj czas ostatniego zapisu, chyba ze stan "idle" (Brak zmian)
        if (timeEl) {
            if (state === 'idle') {
                timeEl.textContent = '';
            } else if (time !== undefined) {
                timeEl.textContent = time;
            } else {
                timeEl.textContent = this._lastSaveTime || '';
            }
        }
    }

    _animateTextChange(wrap, oldTextEl, newMessage) {
        // Anuluj poprzednia animacje jesli trwa
        const prevExiting = wrap.querySelectorAll('.text-exit');
        prevExiting.forEach(el => el.remove());

        // Stworz nowy element tekstu
        const newText = document.createElement('span');
        newText.className = 'draft-status-text text-enter-from';
        newText.id = 'draftStatusText';
        newText.textContent = newMessage;

        // Usun id ze starego
        oldTextEl.id = '';

        // Dodaj nowy do DOM
        wrap.appendChild(newText);

        // Zmierz i ustaw nowa szerokosc wrappera
        wrap.style.width = newText.scrollWidth + 'px';

        // Stary tekst spada w dol
        oldTextEl.classList.add('text-exit');

        // Nowy tekst wjezdza z gory (potrzebny reflow)
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                newText.classList.remove('text-enter-from');
            });
        });

        // Cleanup po animacji
        setTimeout(() => {
            oldTextEl.remove();
        }, 350);
    }

    _initTextWrapWidth() {
        const wrap = document.getElementById('draftStatusTextWrap');
        const text = document.getElementById('draftStatusText');
        if (wrap && text) {
            wrap.style.width = text.scrollWidth + 'px';
        }
    }

    bindSaveButton() {
        const btn = document.getElementById('draftSaveBtn');
        if (btn) {
            // Ustaw poczatkowa szerokosc na podstawie aktywnego stanu
            const activeState = btn.querySelector('.draft-save-state.active');
            if (activeState) {
                btn.style.width = activeState.scrollWidth + 'px';
            }

            btn.addEventListener('click', async () => {
                if (this.isQuoteSaved || !this.hasAnyData()) return;

                // Anuluj oczekujacy autozapis - manualny go zastepuje
                if (this._saveDebounceTimer) {
                    clearTimeout(this._saveDebounceTimer);
                    this._saveDebounceTimer = null;
                }

                // Pokaz spinner
                this.setSaveButtonIcon('spinner');
                this.updateStatusIndicator('saving', 'Zapisywanie kopii...');

                this.saveCurrentState();
                await this.syncToServer();
            });
        }
    }

    setSaveButtonIcon(icon) {
        const now = Date.now();

        // Nie nadpisuj spinnera jesli jeszcze trwa jego minimalny czas
        if (icon !== 'spinner' && now < this._spinnerUntil) return;
        // Nie nadpisuj fajki jesli jeszcze trwa jej minimalny czas
        if (icon !== 'check' && icon !== 'spinner' && now < this._checkIconUntil) return;

        const btn = document.getElementById('draftSaveBtn');
        const states = document.querySelectorAll('.draft-save-state');
        if (!states.length || !btn) return;

        states.forEach(el => el.classList.remove('active'));

        const target = document.querySelector(`.draft-save-state--${icon}`);
        if (target) {
            target.classList.add('active');
            // Zmierz szerokosc aktywnego stanu i ustaw na przycisku
            const width = target.scrollWidth;
            btn.style.width = width + 'px';
        }

        // Ustaw minimalny czas spinnera
        if (icon === 'spinner') {
            this._spinnerUntil = now + 1000;
        }
    }

    showCheckConfirmation() {
        const now = Date.now();
        const remaining = Math.max(0, this._spinnerUntil - now);

        // Poczekaj az spinner skonczy swoj minimalny czas, potem pokaz fajke
        setTimeout(() => {
            const t = new Date();
            const timeStr = t.getHours().toString().padStart(2, '0') + ':'
                + t.getMinutes().toString().padStart(2, '0') + ':'
                + t.getSeconds().toString().padStart(2, '0');

            this._spinnerUntil = 0;
            this._checkIconUntil = Date.now() + 2000;
            this.setSaveButtonIcon('check');
            this.updateStatusIndicator('saved', 'Kopia zapisana', timeStr);

            // Po 2s wroc do dyskietki
            setTimeout(() => {
                if (Date.now() >= this._checkIconUntil) {
                    this.setSaveButtonIcon('floppy');
                }
            }, 2000);
        }, remaining);
    }

    updateSaveButtonDisabled() {
        const btn = document.getElementById('draftSaveBtn');
        if (!btn) return;
        const disabled = !this.hasAnyData() || this.isQuoteSaved;
        btn.disabled = disabled;
        btn.style.opacity = disabled ? '0.4' : '';
        btn.style.cursor = disabled ? 'default' : '';
    }

    bindChangeDetection() {
        const markUnsaved = () => {
            if (this._ignoreChanges || this.isQuoteSaved) return;
            if (Date.now() < this._restoredUntil) return;

            this.updateSaveButtonDisabled();

            if (!this.hasAnyData()) return;

            if (Date.now() >= this._checkIconUntil) {
                this.updateStatusIndicator('unsaved', 'Niezapisane zmiany kopii');
                this.setSaveButtonIcon('floppy');
            }

            this.scheduleSave();
        };

        // Event delegation na kontenerze kalkulatora
        const container = document.querySelector('.calculatorrr');
        if (container) {
            // Inputy tekstowe/numeryczne
            container.addEventListener('input', (e) => {
                if (e.target.matches('input[data-field], textarea')) {
                    markUnsaved();
                }
            });

            // Selecty, radio buttony, checkboxy
            container.addEventListener('change', (e) => {
                if (e.target.matches('select[data-field], input[type="radio"], input[type="checkbox"]')) {
                    markUnsaved();
                }
            });

            // Klikniecia w przyciski wykonczenia, wariantow, krawedzi
            container.addEventListener('click', (e) => {
                if (e.target.closest('.finishing-option-btn, .finishing-btn, .color-btn, .variant-option, .edges-reset-btn')) {
                    markUnsaved();
                }
            });
        }

        // Tryb cen brutto/netto
        const priceModeToggle = document.getElementById('priceModeToggle');
        if (priceModeToggle) {
            priceModeToggle.addEventListener('change', markUnsaved);
        }

        // Obrobka krawedzi - modal zastosuj/resetuj (eventy na document bo modal jest poza kontenerem)
        document.addEventListener('click', (e) => {
            if (e.target.closest('#applyEdgesBtn')) {
                markUnsaved();
            }
        });

        // Custom event (gdyby ktos go dispatchy w przyszlosci)
        document.addEventListener('calculatorDataChanged', markUnsaved);

        // MutationObserver na dataset formularzy (wykonceznia, krawedzie zmieniaja dataset)
        const quoteForms = document.querySelector('.quote-forms');
        if (quoteForms) {
            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    if (mutation.type === 'attributes' && mutation.attributeName?.startsWith('data-')) {
                        markUnsaved();
                        break;
                    }
                }
            });
            observer.observe(quoteForms, {
                attributes: true,
                attributeFilter: ['data-finishing-type', 'data-finishing-variant', 'data-finishing-color',
                    'data-edges-data', 'data-edges-type', 'data-product-shape'],
                subtree: true
            });
        }
    }

    // ========================================
    // COOKIE MIGRATION
    // ========================================

    migrateCookies() {
        try {
            const cookies = document.cookie.split(';');
            let hasOldDraft = false;

            for (const cookie of cookies) {
                const [name] = cookie.trim().split('=');
                if (name && name.startsWith('woodpower_quotedraft_main_')) {
                    hasOldDraft = true;
                    break;
                }
            }

            if (hasOldDraft) {
                // Usun stare cookies - nowy system zacznie od nowa
                this.clearLegacyCookies();
            }
        } catch (e) {
            // Ignoruj bledy migracji
        }
    }

    clearLegacyCookies() {
        try {
            const cookies = document.cookie.split(';');
            for (const cookie of cookies) {
                const [name] = cookie.trim().split('=');
                if (name && name.startsWith('woodpower_quotedraft_')) {
                    document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
                }
            }
        } catch (e) {
            // Ignoruj
        }
    }

    // ========================================
    // UTILITIES
    // ========================================

    showLoadingOverlay(message) {
        const overlay = document.getElementById('restore-overlay');
        if (overlay) {
            const textEl = document.getElementById('restoreLoadingText');
            if (textEl) textEl.textContent = message;
            overlay.style.display = 'flex';
        }
    }

    updateProgress(percent) {
        const fill = document.getElementById('restoreProgressFill');
        const text = document.getElementById('restoreProgressPercent');
        if (fill) fill.style.width = percent + '%';
        if (text) text.textContent = Math.round(percent) + '%';
    }

    hideLoadingOverlay() {
        const overlay = document.getElementById('restore-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
        this.updateProgress(0);
    }

    showError(message) {
        alert('Blad przywracania wyceny:\n\n' + message + '\n\nZalecamy weryfikacje danych.');
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    destroy() {
        this.stopAutoSave();
    }
}

// Eksportuj klase do globalnego scope
window.QuoteDraftBackup = QuoteDraftBackup;
