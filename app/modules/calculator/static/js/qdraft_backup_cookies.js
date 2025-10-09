/**
 * Quote Draft Backup System using Cookies
 * Automatically saves quote drafts every 10 seconds
 * Handles cookie size limits by splitting data into multiple parts
 */

class QuoteDraftBackup {
    constructor() {
        this.saveInterval = 10000; // 10 sekund
        this.maxCookieSize = 3800; // 3.8KB bezpieczny limit
        this.validityMinutes = 5; // Ważność 5 minut
        this.userId = null;
        this.intervalId = null;
        this.cookiePrefix = 'woodpower_quotedraft';
        this.version = '1.0';
    }

    /**
     * Inicjalizacja systemu backup
     */
    init(userId) {
        console.log('[QuoteDraftBackup] Inicjalizacja systemu backup dla użytkownika:', userId);
        this.userId = userId;

        // Sprawdź czy istnieje draft do przywrócenia
        this.checkExistingDraft();

        // Rozpocznij automatyczne zapisywanie
        this.startAutoSave();
    }

    /**
     * Rozpoczyna automatyczne zapisywanie co 10 sekund
     */
    startAutoSave() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
        }

        this.intervalId = setInterval(() => {
            this.saveCurrentState();
        }, this.saveInterval);

        console.log('[QuoteDraftBackup] Automatyczne zapisywanie uruchomione');
    }

    /**
     * Zatrzymuje automatyczne zapisywanie
     */
    stopAutoSave() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
            console.log('[QuoteDraftBackup] Automatyczne zapisywanie zatrzymane');
        }
    }

    /**
     * Zapisuje aktualny stan wyceny
     */
    saveCurrentState() {
        try {
            const quoteData = this.collectQuoteData();

            // Jeśli brak kompletnych produktów, nie zapisuj
            if (!quoteData.products || quoteData.products.length === 0) {
                console.log('[QuoteDraftBackup] Brak kompletnych produktów do zapisania');
                return;
            }

            // Usuń poprzednie drafty tego użytkownika
            this.clearExistingDrafts();

            // Podziel dane na części jeśli potrzeba
            const parts = this.splitDataIntoParts(quoteData);

            // Zapisz dane do cookies
            this.saveDataToCookies(quoteData, parts);

            console.log(`[QuoteDraftBackup] Zapisano draft z ${quoteData.products.length} produktami w ${parts.length} częściach`);

        } catch (error) {
            console.error('[QuoteDraftBackup] Błąd podczas zapisywania:', error);
        }
    }

    /**
     * Zbiera dane z aktualnego stanu kalkulatora
     */
    collectQuoteData() {
        const timestamp = Date.now();
        const quoteFormsContainer = document.querySelector('.quote-forms');
        const forms = Array.from(quoteFormsContainer?.querySelectorAll('.quote-form') || []);

        // Pobierz grupę cenową z pierwszego formularza
        let clientType = null;
        let multiplier = 1.0;

        if (forms.length > 0) {
            const firstForm = forms[0];
            const clientTypeSelect = firstForm.querySelector('select[data-field="clientType"]');
            clientType = clientTypeSelect?.value || null;

            // Pobierz multiplier
            if (clientType && window.multiplierMapping && window.multiplierMapping[clientType]) {
                multiplier = window.multiplierMapping[clientType];
            } else if (window.isPartner && window.userMultiplier) {
                multiplier = window.userMultiplier;
                clientType = 'Partner';
            }
        }

        const products = [];

        forms.forEach((form, index) => {
            const productData = this.extractProductData(form, index);

            // Sprawdź czy produkt jest kompletny (ma wszystkie wymagane dane)
            if (this.isProductComplete(productData)) {
                products.push(productData);
            }
        });

        return {
            timestamp,
            userId: this.userId,
            version: this.version,
            clientType,
            multiplier,
            totalProducts: products.length,
            products
        };
    }

    /**
     * Wyciąga dane produktu z formularza
     */
    extractProductData(form, index) {
        // Podstawowe wymiary
        const length = parseFloat(form.querySelector('[data-field="length"]')?.value || 0);
        const width = parseFloat(form.querySelector('[data-field="width"]')?.value || 0);
        const thickness = parseFloat(form.querySelector('[data-field="thickness"]')?.value || 0);
        const quantity = parseInt(form.querySelector('[data-field="quantity"]')?.value || 1);

        // Wybrany wariant (radio button)
        const selectedRadio = form.querySelector('input[type="radio"]:checked');
        const selectedVariant = selectedRadio ? selectedRadio.value : null;

        // Dane wykończenia
        const finishingType = form.querySelector('.finishing-btn[data-finishing-type].active')?.dataset.finishingType || 'Surowe';
        const finishingVariant = form.querySelector('.finishing-btn[data-finishing-variant].active')?.dataset.finishingVariant || null;
        const finishingColor = form.querySelector('.color-btn[data-finishing-color].active')?.dataset.finishingColor || null;
        const finishingGloss = form.querySelector('.finishing-btn[data-finishing-gloss].active')?.dataset.finishingGloss || null;

        // Grupa cenowa (może być różna dla każdego produktu, chociaż zwykle jest synchronizowana)
        const clientType = form.querySelector('select[data-field="clientType"]')?.value || null;

        return {
            index,
            length,
            width,
            thickness,
            quantity,
            selectedVariant,
            clientType,
            finishing: {
                type: finishingType,
                variant: finishingVariant,
                color: finishingColor,
                gloss: finishingGloss
            }
        };
    }

    /**
     * Sprawdza czy produkt ma wszystkie wymagane dane
     */
    isProductComplete(productData) {
        const hasBasicDimensions = productData.length > 0 &&
            productData.width > 0 &&
            productData.thickness > 0;

        const hasClientType = productData.clientType || window.isPartner;

        return hasBasicDimensions && hasClientType;
    }

    /**
     * Dzieli dane na części jeśli przekraczają limit cookie
     */
    splitDataIntoParts(quoteData) {
        const parts = [];
        let currentPart = { products: [] };

        for (const product of quoteData.products) {
            // Dodaj produkt do aktualnej części
            const testPart = {
                ...currentPart,
                products: [...currentPart.products, product]
            };

            // Sprawdź rozmiar po dodaniu produktu
            const testSize = new Blob([JSON.stringify(testPart)]).size;

            if (testSize > this.maxCookieSize && currentPart.products.length > 0) {
                // Aktualna część jest za duża, zapisz ją i rozpocznij nową
                parts.push(currentPart);
                currentPart = { products: [product] };
            } else {
                // Produkt mieści się w aktualnej części
                currentPart = testPart;
            }
        }

        // Dodaj ostatnią część jeśli nie jest pusta
        if (currentPart.products.length > 0) {
            parts.push(currentPart);
        }

        return parts;
    }

    /**
     * Zapisuje dane do cookies (główny plik + części)
     */
    saveDataToCookies(quoteData, parts) {
        const timestamp = quoteData.timestamp;
        const expirationDate = new Date(Date.now() + (this.validityMinutes * 60 * 1000));

        // Zapisz główny plik z metadanymi
        const mainData = {
            userId: this.userId,
            timestamp,
            version: this.version,
            partsCount: parts.length,
            clientType: quoteData.clientType,
            multiplier: quoteData.multiplier,
            totalProducts: quoteData.totalProducts,
            expires: expirationDate.getTime()
        };

        const mainCookieName = `${this.cookiePrefix}_main_${this.userId}_${timestamp}`;
        this.setCookie(mainCookieName, JSON.stringify(mainData), expirationDate);

        // Zapisz części z produktami
        parts.forEach((part, index) => {
            const partCookieName = `${this.cookiePrefix}_part${index + 1}_${this.userId}_${timestamp}`;
            this.setCookie(partCookieName, JSON.stringify(part), expirationDate);
        });
    }

    /**
     * Sprawdza czy istnieje draft do przywrócenia
     */
    checkExistingDraft() {
        try {
            const draftData = this.loadDraftFromCookies();

            if (draftData && this.isDraftValid(draftData)) {
                this.showRestoreModal(draftData);
            } else if (draftData) {
                // Draft nieważny - usuń
                this.clearDraft();
            }
        } catch (error) {
            console.error('[QuoteDraftBackup] Błąd podczas sprawdzania draftu:', error);
            this.clearAllDrafts();
        }
    }

    /**
     * Ładuje draft z cookies
     */
    loadDraftFromCookies() {
        // Znajdź główny plik tego użytkownika
        const cookies = document.cookie.split(';');
        let mainCookie = null;

        for (const cookie of cookies) {
            const [name] = cookie.trim().split('=');
            if (name.startsWith(`${this.cookiePrefix}_main_${this.userId}_`)) {
                mainCookie = this.getCookie(name);
                break;
            }
        }

        if (!mainCookie) {
            return null;
        }

        const mainData = JSON.parse(mainCookie);
        const timestamp = mainData.timestamp;

        // Załaduj wszystkie części
        const allProducts = [];
        for (let i = 1; i <= mainData.partsCount; i++) {
            const partCookieName = `${this.cookiePrefix}_part${i}_${this.userId}_${timestamp}`;
            const partCookie = this.getCookie(partCookieName);

            if (partCookie) {
                const partData = JSON.parse(partCookie);
                allProducts.push(...partData.products);
            }
        }

        return {
            ...mainData,
            products: allProducts
        };
    }

    /**
     * Sprawdza czy draft jest nadal ważny
     */
    isDraftValid(draftData) {
        if (!draftData || !draftData.expires) {
            return false;
        }

        return Date.now() < draftData.expires;
    }

    /**
     * Wyświetla modal z opcją przywrócenia wyceny
     */
    showRestoreModal(draftData) {
        // Sprawdź czy modal już istnieje
        let modal = document.getElementById('autosave-modal');
        if (!modal) {
            console.error('[QuoteDraftBackup] Modal przywracania nie został znaleziony');
            return;
        }

        // Wylicz ile czasu temu została wykonana wycena
        const timeAgo = this.getTimeAgo(draftData.timestamp);

        // Wypełnij dane w modalu
        document.getElementById('draft-timestamp').textContent = timeAgo;

        // Wygeneruj listę produktów
        this.generateProductsList(draftData.products);

        // Dodaj event listenery do przycisków
        document.getElementById('restore-quote-btn').onclick = () => this.restoreQuote(draftData);
        document.getElementById('new-quote-btn').onclick = () => this.startNewQuote();

        // Pokaż modal
        modal.style.display = 'flex';
    }

    /**
     * Generuje listę produktów do wyświetlenia w modalu
     */
    generateProductsList(products) {
        const container = document.getElementById('products-list');
        container.innerHTML = '';

        products.forEach((product, index) => {
            const productDiv = document.createElement('div');
            productDiv.className = 'product-item';

            // Wygeneruj opis produktu
            let description = `Produkt ${index + 1} - ${product.length}×${product.width}×${product.thickness}cm`;

            if (product.selectedVariant) {
                // Zmapuj kod wariantu na czytelną nazwę
                const variantName = this.getVariantDisplayName(product.selectedVariant);
                description = `${variantName} ${product.length}×${product.width}×${product.thickness}cm`;
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

            productDiv.textContent = description;
            container.appendChild(productDiv);
        });
    }

    /**
     * Konwertuje kod wariantu na czytelną nazwę
     */
    getVariantDisplayName(variantCode) {
        const variantNames = {
            'dab-lity-ab': 'Dąb lity A/B',
            'dab-lity-bb': 'Dąb lity B/B',
            'dab-micro-ab': 'Dąb mikrowczep A/B',
            'dab-micro-bb': 'Dąb mikrowczep B/B',
            'jes-lity-ab': 'Jesion lity A/B',
            'jes-micro-ab': 'Jesion mikrowczep A/B',
            'buk-lity-ab': 'Buk lity A/B',
            'buk-micro-ab': 'Buk mikrowczep A/B'
        };

        return variantNames[variantCode] || variantCode;
    }

    /**
     * Wylicza ile czasu temu była wykonana wycena
     */
    getTimeAgo(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;
        const minutes = Math.floor(diff / (1000 * 60));

        if (minutes < 1) {
            return 'przed chwilą';
        } else if (minutes === 1) {
            return '1 minutę temu';
        } else if (minutes < 5) {
            return `${minutes} minuty temu`;
        } else {
            return `${minutes} minut temu`;
        }
    }

    /**
     * Przywraca wycenę z draftu
     */
    async restoreQuote(draftData) {
        try {
            // Pokaż overlay ładowania
            this.showLoadingOverlay('Wczytuję wycenę...');

            // Ukryj modal wyboru
            document.getElementById('autosave-modal').style.display = 'none';

            // Zatrzymaj autosave podczas przywracania
            this.stopAutoSave();

            console.log('[QuoteDraftBackup] Rozpoczynam przywracanie wyceny z', draftData.products.length, 'produktami');

            // Wyczyść aktualny stan kalkulatora
            await this.clearCurrentCalculator();

            // Przywróć grupę cenową
            if (draftData.clientType) {
                await this.restoreClientType(draftData.clientType);
            }

            // Przywróć produkty jeden po drugim
            for (let i = 0; i < draftData.products.length; i++) {
                await this.restoreProduct(draftData.products[i], i);

                // Dodaj krótkie opóźnienie między produktami dla płynności
                await this.delay(200);
            }

            // Usuń draft po udanym przywróceniu
            this.clearDraft();

            // Uruchom ponownie autosave
            this.startAutoSave();

            console.log('[QuoteDraftBackup] Wycena została przywrócona pomyślnie');

            // Ukryj overlay
            this.hideLoadingOverlay();

            // Aktywuj pierwszy produkt
            if (typeof activateProductCard === 'function') {
                activateProductCard(0);
            }

        } catch (error) {
            console.error('[QuoteDraftBackup] Błąd podczas przywracania:', error);
            this.hideLoadingOverlay();
            this.showError('Wystąpił błąd podczas wczytywania wyceny: ' + error.message);
        }
    }

    /**
     * Czyści aktualny stan kalkulatora
     */
    async clearCurrentCalculator() {
        const quoteFormsContainer = document.querySelector('.quote-forms');
        if (!quoteFormsContainer) return;

        // Usuń wszystkie formularze oprócz pierwszego
        const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
        for (let i = forms.length - 1; i > 0; i--) {
            forms[i].remove();
        }

        // Wyczyść pierwszy formularz
        if (forms[0]) {
            this.clearProductForm(forms[0]);
        }
    }

    /**
     * Czyści pojedynczy formularz produktu
     */
    clearProductForm(form) {
        // Wyczyść pola tekstowe
        form.querySelectorAll('input[data-field]').forEach(input => {
            input.value = '';
        });

        // Resetuj select grupy cenowej
        const clientTypeSelect = form.querySelector('select[data-field="clientType"]');
        if (clientTypeSelect) {
            clientTypeSelect.selectedIndex = 0;
        }

        // Odznacz wszystkie radio buttony
        form.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.checked = false;
        });

        // Usuń aktywne klasy z wykończenia
        form.querySelectorAll('.finishing-btn.active, .color-btn.active').forEach(btn => {
            btn.classList.remove('active');
        });

        // Ustaw domyślne wykończenie "Surowe"
        const defaultFinishing = form.querySelector('.finishing-btn[data-finishing-type="Surowe"]');
        if (defaultFinishing) {
            defaultFinishing.classList.add('active');
        }

        // Ukryj sekcje wykończenia
        const sections = ['finishing-wrapper', 'color-section', 'gloss-section'];
        sections.forEach(sectionClass => {
            const section = form.querySelector(`.${sectionClass}`);
            if (section) {
                section.style.display = 'none';
            }
        });
    }

    /**
     * Przywraca grupę cenową
     */
    async restoreClientType(clientType) {
        const forms = document.querySelectorAll('.quote-form');
        forms.forEach(form => {
            const select = form.querySelector('select[data-field="clientType"]');
            if (select) {
                select.value = clientType;
                // Wywołaj event change dla synchronizacji
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });

        await this.delay(100);
    }

    /**
     * Przywraca pojedynczy produkt
     */
    async restoreProduct(productData, index) {
        // Dodaj nowy formularz jeśli potrzeba
        if (index > 0) {
            if (typeof addNewProduct === 'function') {
                addNewProduct();
                await this.delay(300); // Poczekaj na utworzenie formularza
            }
        }

        const forms = document.querySelectorAll('.quote-form');
        const form = forms[index];

        if (!form) {
            throw new Error(`Nie można znaleźć formularza dla produktu ${index + 1}`);
        }

        // Przywróć wymiary
        await this.restoreFormField(form, '[data-field="length"]', productData.length);
        await this.restoreFormField(form, '[data-field="width"]', productData.width);
        await this.restoreFormField(form, '[data-field="thickness"]', productData.thickness);
        await this.restoreFormField(form, '[data-field="quantity"]', productData.quantity);

        // Przywróć grupę cenową
        if (productData.clientType) {
            const select = form.querySelector('select[data-field="clientType"]');
            if (select) {
                select.value = productData.clientType;
            }
        }

        // Poczekaj na przeliczenie cen
        await this.delay(200);

        // Przywróć wybrany wariant
        if (productData.selectedVariant) {
            const radio = form.querySelector(`input[type="radio"][value="${productData.selectedVariant}"]`);
            if (radio) {
                radio.checked = true;
                radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        // Przywróć wykończenie
        await this.restoreFinishing(form, productData.finishing);
    }

    /**
     * Przywraca wartość pola formularza
     */
    async restoreFormField(form, selector, value) {
        const field = form.querySelector(selector);
        if (field && value !== undefined && value !== null) {
            field.value = value;
            field.dispatchEvent(new Event('input', { bubbles: true }));
            await this.delay(50);
        }
    }

    /**
     * Przywraca ustawienia wykończenia
     */
    async restoreFinishing(form, finishing) {
        if (!finishing || finishing.type === 'Surowe') {
            return;
        }

        // Przywróć typ wykończenia
        const typeBtn = form.querySelector(`[data-finishing-type="${finishing.type}"]`);
        if (typeBtn) {
            typeBtn.click();
            await this.delay(100);
        }

        // Przywróć wariant (bezbarwne/barwne)
        if (finishing.variant) {
            const variantBtn = form.querySelector(`[data-finishing-variant="${finishing.variant}"]`);
            if (variantBtn) {
                variantBtn.click();
                await this.delay(100);
            }
        }

        // Przywróć kolor
        if (finishing.color) {
            const colorBtn = form.querySelector(`[data-finishing-color="${finishing.color}"]`);
            if (colorBtn) {
                colorBtn.click();
                await this.delay(100);
            }
        }

        // Przywróć połysk
        if (finishing.gloss) {
            const glossBtn = form.querySelector(`[data-finishing-gloss="${finishing.gloss}"]`);
            if (glossBtn) {
                glossBtn.click();
                await this.delay(100);
            }
        }
    }

    /**
     * Rozpoczyna nową wycenę (usuwa draft)
     */
    startNewQuote() {
        document.getElementById('autosave-modal').style.display = 'none';
        this.clearDraft();
        console.log('[QuoteDraftBackup] Rozpoczęto nową wycenę - draft usunięty');
    }

    /**
     * Usuwa aktualny draft
     */
    clearDraft() {
        this.clearExistingDrafts();
    }

    /**
     * Usuwa wszystkie istniejące drafty tego użytkownika
     */
    clearExistingDrafts() {
        const cookies = document.cookie.split(';');
        const toDelete = [];

        for (const cookie of cookies) {
            const [name] = cookie.trim().split('=');
            if (name.startsWith(`${this.cookiePrefix}_`) && name.includes(`_${this.userId}_`)) {
                toDelete.push(name);
            }
        }

        toDelete.forEach(cookieName => {
            this.deleteCookie(cookieName);
        });

        if (toDelete.length > 0) {
            console.log(`[QuoteDraftBackup] Usunięto ${toDelete.length} starych plików draft`);
        }
    }

    /**
     * Usuwa wszystkie drafty ze wszystkich użytkowników
     */
    clearAllDrafts() {
        const cookies = document.cookie.split(';');
        const toDelete = [];

        for (const cookie of cookies) {
            const [name] = cookie.trim().split('=');
            if (name.startsWith(`${this.cookiePrefix}_`)) {
                toDelete.push(name);
            }
        }

        toDelete.forEach(cookieName => {
            this.deleteCookie(cookieName);
        });

        console.log(`[QuoteDraftBackup] Usunięto wszystkie pliki draft (${toDelete.length})`);
    }

    /**
     * Wyświetla overlay ładowania
     */
    showLoadingOverlay(message) {
        let overlay = document.getElementById('restore-overlay');
        if (overlay) {
            const messageEl = overlay.querySelector('p');
            if (messageEl) {
                messageEl.textContent = message;
            }
            overlay.style.display = 'flex';
        }
    }

    /**
     * Ukrywa overlay ładowania
     */
    hideLoadingOverlay() {
        const overlay = document.getElementById('restore-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    /**
     * Wyświetla komunikat błędu
     */
    showError(message) {
        alert('Błąd przywracania wyceny:\n\n' + message + '\n\nZalecamy weryfikację danych.');
    }

    /**
     * Opóźnienie (Promise)
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Ustawia cookie
     */
    setCookie(name, value, expirationDate) {
        const expires = expirationDate ? `; expires=${expirationDate.toUTCString()}` : '';
        document.cookie = `${name}=${value}${expires}; path=/; SameSite=Lax`;
    }

    /**
     * Pobiera wartość cookie
     */
    getCookie(name) {
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [cookieName, cookieValue] = cookie.trim().split('=');
            if (cookieName === name) {
                return decodeURIComponent(cookieValue);
            }
        }
        return null;
    }

    /**
     * Usuwa cookie
     */
    deleteCookie(name) {
        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
    }

    /**
     * Czyści system przed zniszczeniem obiektu
     */
    destroy() {
        this.stopAutoSave();
        console.log('[QuoteDraftBackup] System backup został zatrzymany');
    }
}

// Eksportuj klasę do globalnego scope
window.QuoteDraftBackup = QuoteDraftBackup;