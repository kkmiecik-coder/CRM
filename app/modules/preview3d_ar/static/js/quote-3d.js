// app/modules/preview3d_ar/static/js/quote-3d.js
// POPRAWIONA WERSJA z popup i obsługą USDZ

class Quote3DHandler {
    constructor() {
        this.config = window.Quote3DConfig;
        this.viewer = null;
        this.currentProduct = null;
        this.isLoading = false;

        // Elementy DOM
        this.canvasEl = document.getElementById('wood-canvas');
        this.btnReset = document.getElementById('btn-reset');
        this.btnAr = document.getElementById('btn-ar');
        this.currentTitleEl = document.getElementById('current-product-title');
        this.currentDimensionsEl = document.getElementById('current-product-dimensions');
        this.loadingEl = document.getElementById('loading');
        this.errorEl = document.getElementById('error-message');
        this.errorTextEl = document.getElementById('error-text');

        console.log('[Quote3D] Inicjalizacja handlera z popup AR');
    }

    /**
     * Główna metoda inicjalizacji
     */
    async init() {
        try {
            console.log('[Quote3D] Inicjalizacja viewer\'a');
            await this.initializeViewer();

            console.log('[Quote3D] Konfiguracja event listenerów');
            this.setupEventListeners();

            // Załaduj domyślny produkt
            if (this.config.defaultProduct) {
                console.log('[Quote3D] Ładowanie domyślnego produktu');
                await this.loadProduct(this.config.defaultProduct);
            }

            console.log('[Quote3D] Viewer zainicjalizowany pomyślnie');

        } catch (error) {
            console.error('[Quote3D] Błąd inicjalizacji:', error);
            this.showError(`Błąd inicjalizacji: ${error.message}`);
        }
    }

    /**
     * Konfiguruje event listenery
     */
    setupEventListeners() {
        // Obsługa „pending" wyboru wariantu
        if (window.pendingVariantSelection) {
            this.selectVariant(window.pendingVariantSelection);
            window.pendingVariantSelection = null;
        }

        // Reset kamery
        if (this.btnReset) {
            this.btnReset.addEventListener('click', () => {
                if (this.viewer && typeof this.viewer.resetCamera === 'function') {
                    this.viewer.resetCamera();
                }
            });
        }

        // POPRAWIONY przycisk AR - używa popup
        this.setupARButton();

        console.log('[Quote3D] Event listenery skonfigurowane');
    }

    /**
     * POPRAWIONA: Setup AR button z popup
     */
    setupARButton() {
        if (!this.btnAr) return;
        console.log('[Quote3D] Konfiguracja przycisku AR z popup');

        const handler = (e) => {
            e.preventDefault();
            e.stopPropagation();

            // NOWE: Użyj ARHandler z popup
            this.handleARClickWithPopup();
        };

        this.btnAr.addEventListener('click', handler);
        this.btnAr.addEventListener('touchstart', handler);

        // Ulepsz UX dla touch
        this.btnAr.style.cursor = 'pointer';
        this.btnAr.style.userSelect = 'none';
        this.btnAr.style.webkitTouchCallout = 'none';
        this.btnAr.style.webkitUserSelect = 'none';

        this.btnAr.title = 'Rzeczywistość rozszerzona (iOS Safari)';
    }

    /**
     * NOWA METODA: Obsługa AR z popup
     */
    async handleARClickWithPopup() {
        console.log('[Quote3D] handleARClickWithPopup start');

        // Sprawdź czy jest wybrany produkt
        if (!this.currentProduct) {
            alert('Najpierw wybierz wariant produktu');
            return;
        }

        // Sprawdź czy ARHandler jest załadowany
        if (typeof window.ARHandler === 'undefined') {
            console.error('[Quote3D] ARHandler nie jest załadowany');
            alert('Błąd: Moduł AR nie jest dostępny. Odśwież stronę.');
            return;
        }

        console.log('[Quote3D] Wywołanie ARHandler.initiateAR z popup...');

        // NOWE: Użyj ARHandler.initiateAR (pokaże popup)
        try {
            await window.ARHandler.initiateAR(this.currentProduct);
        } catch (error) {
            console.error('[Quote3D] Błąd ARHandler:', error);
            alert(`Błąd AR: ${error.message}`);
        }
    }

    /**
     * Obsługuje wybór wariantu
     */
    async selectVariant(btn) {
        try {
            console.log('[Quote3D] Wybrano wariant:', btn.dataset);

            // Usuń poprzednie oznaczenia "currently viewing"
            document.querySelectorAll('.variant-btn').forEach(variantBtn => {
                variantBtn.classList.remove('currently-viewing');
                const viewingBadge = variantBtn.querySelector('.viewing-badge');
                if (viewingBadge) {
                    viewingBadge.remove();
                }
            });

            // Dodaj oznaczenie "obecnie wyświetlany" do nowego wariantu
            btn.classList.add('currently-viewing');

            // Przygotuj dane produktu do załadowania
            const productData = {
                variant_code: btn.dataset.variantCode,
                product_index: parseInt(btn.dataset.productIndex),
                dimensions: {
                    length: parseFloat(btn.dataset.length),
                    width: parseFloat(btn.dataset.width),
                    thickness: parseFloat(btn.dataset.thickness)
                },
                quantity: parseInt(btn.dataset.quantity),
                has_textures: btn.dataset.hasTextures === 'true'
            };

            console.log('[Quote3D] Ładowanie produktu:', productData);
            await this.loadProduct(productData);
            console.log('[Quote3D] Wariant wybrany i załadowany pomyślnie');

        } catch (error) {
            console.error('[Quote3D] Błąd wyboru wariantu:', error);
            this.showError(`Błąd wyboru wariantu: ${error.message}`);
        }
    }

    /**
     * UPROSZCZONA: Ładuje produkt w viewer'ze bez prefetch
     */
    async loadProduct(productData) {
        if (this.isLoading) return;
        this.isLoading = true;
        this.showLoading();

        try {
            await this.viewer.loadProduct(productData);
            this.updateProductInfo(productData);
            this.currentProduct = productData;

            console.log('[Quote3D] Produkt załadowany pomyślnie');

        } catch (err) {
            this.showError(`Błąd ładowania produktu: ${err.message}`);
        } finally {
            this.hideLoading();
            this.isLoading = false;
        }
    }

    /**
     * Inicjalizuje WoodViewer
     */
    async initializeViewer() {
        try {
            console.log('[Quote3D] Tworzenie WoodViewer...');

            if (typeof WoodViewer === 'undefined') {
                throw new Error('WoodViewer nie jest załadowany');
            }

            this.viewer = new WoodViewer(this.canvasEl);
            await this.viewer.init();

            // Sprawdź czy wszystko zostało zainicjalizowane
            if (!this.viewer.scene || !this.viewer.camera || !this.viewer.renderer) {
                throw new Error('Błąd inicjalizacji sceny 3D');
            }

            console.log('[Quote3D] WoodViewer zainicjalizowany');

            // Zapisz referencję globalnie dla debugowania
            window.currentViewer = this.viewer;

        } catch (error) {
            console.error('[Quote3D] Błąd inicjalizacji viewera:', error);
            throw error;
        }
    }

    /**
     * Aktualizuje informacje o produkcie w headerze
     */
    updateProductInfo(productData) {
        console.log('[Quote3D] Aktualizacja informacji produktu:', productData);

        if (this.currentTitleEl) {
            // Użyj funkcji tłumaczenia jeśli jest dostępna
            const translatedName = window.translateVariantCode ?
                window.translateVariantCode(productData.variant_code) :
                productData.variant_code;

            this.currentTitleEl.textContent = translatedName;
            console.log('[Quote3D] Zaktualizowano tytuł na:', translatedName);
        }

        if (this.currentDimensionsEl && productData.dimensions) {
            const { length, width, thickness } = productData.dimensions;
            const dimensionsText = `${length}×${width}×${thickness} cm`;
            this.currentDimensionsEl.textContent = dimensionsText;
            console.log('[Quote3D] Zaktualizowano wymiary na:', dimensionsText);
        }
    }

    /**
     * Pokazuje komunikat o ładowaniu
     */
    showLoading() {
        console.log('[Quote3D] Pokazano loading...');
        if (this.loadingEl) {
            this.loadingEl.style.display = 'flex';
        }
    }

    /**
     * Ukrywa komunikat o ładowaniu
     */
    hideLoading() {
        console.log('[Quote3D] Ukryto loading...');
        if (this.loadingEl) {
            this.loadingEl.style.display = 'none';
        }
    }

    /**
     * Pokazuje błąd
     */
    showError(message) {
        console.error('[Quote3D] Error:', message);

        if (this.errorTextEl) {
            this.errorTextEl.textContent = message;
        }

        if (this.errorEl) {
            this.errorEl.style.display = 'block';
        }

        this.hideLoading();

        // Pokazuj alert tylko dla krytycznych błędów
        if (message.includes('nie jest załadowany') || message.includes('nie jest zainicjalizowany')) {
            alert(`Błąd aplikacji: ${message}\n\nSpróbuj odświeżyć stronę.`);
        }
    }

    /**
     * Ukrywa błąd
     */
    hideError() {
        if (this.errorEl) {
            this.errorEl.style.display = 'none';
        }
    }

    /**
     * Debug status
     */
    getStatus() {
        return {
            version: '6.0 - Popup AR',
            isInitialized: !!this.viewer,
            currentProduct: this.currentProduct,
            isLoading: this.isLoading,
            viewerStatus: this.viewer ? this.viewer.getStatus() : null,
            ar: {
                handlerAvailable: typeof window.ARHandler !== 'undefined',
                handlerStatus: window.ARHandler ? window.ARHandler.getStatus() : null
            },
            elements: {
                loading: !!this.loadingEl,
                error: !!this.errorEl,
                canvas: !!this.canvasEl,
                arButton: !!this.btnAr
            }
        };
    }

    /**
     * Test AR (dla debugowania)
     */
    async testAR() {
        console.log('[Quote3D] Test AR...');

        if (!this.currentProduct) {
            console.error('[Quote3D] Brak produktu do testowania');
            return;
        }

        if (typeof window.ARHandler === 'undefined') {
            console.error('[Quote3D] ARHandler nie jest dostępny');
            return;
        }

        try {
            await window.ARHandler.initiateAR(this.currentProduct);
        } catch (error) {
            console.error('[Quote3D] Test AR failed:', error);
        }
    }

    /**
     * Clear cache
     */
    clearCache() {
        console.log('[Quote3D] Czyszczenie cache...');

        if (this.currentProduct) {
            delete this.currentProduct.arUrl;
        }

        // Wyczyść cache ARHandler
        if (window.ARHandler && window.ARHandler.clearCache) {
            window.ARHandler.clearCache();
        }

        console.log('[Quote3D] Cache wyczyszczony');
    }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', async () => {
    console.log('[Quote3D] DOM załadowany, inicjalizacja z popup...');

    // Sprawdź zależności
    if (typeof THREE === 'undefined') {
        console.error('[Quote3D] Three.js nie jest załadowany!');
        alert('Błąd: Three.js nie jest załadowany. Odśwież stronę.');
        return;
    }

    if (typeof WoodViewer === 'undefined') {
        console.error('[Quote3D] WoodViewer nie jest załadowany!');
        alert('Błąd: WoodViewer nie jest załadowany. Sprawdź pliki JavaScript.');
        return;
    }

    if (typeof window.ARHandler === 'undefined') {
        console.error('[Quote3D] ARHandler nie jest załadowany!');
        alert('Błąd: ARHandler nie jest załadowany. Sprawdź pliki JavaScript.');
        return;
    }

    // Sprawdź czy jest konfiguracja
    if (typeof window.Quote3DConfig === 'undefined') {
        console.error('[Quote3D] Brak konfiguracji Quote3DConfig!');
        alert('Błąd: Brak konfiguracji aplikacji.');
        return;
    }

    console.log('[Quote3D] Wszystkie zależności załadowane poprawnie');
    console.log('[Quote3D] Konfiguracja:', window.Quote3DConfig);
    console.log('[Quote3D] ARHandler status:', window.ARHandler.getStatus());

    // Utwórz i zainicjalizuj handler
    try {
        const quote3D = new Quote3DHandler();
        window.quote3DHandler = quote3D; // Dla debugowania

        console.log('[Quote3D] Rozpoczęcie inicjalizacji handlera...');
        await quote3D.init();
        console.log('[Quote3D] Handler z popup zainicjalizowany pomyślnie');

        // Dodaj metody debug do window dla łatwego testowania
        window.testAR = () => quote3D.testAR();
        window.getQuote3DStatus = () => quote3D.getStatus();
        window.clearQuote3DCache = () => quote3D.clearCache();

        console.log('[Quote3D] Debug methods available:');
        console.log('  - testAR() - Test popup AR');
        console.log('  - getQuote3DStatus() - Status aplikacji');
        console.log('  - clearQuote3DCache() - Wyczyść cache');

    } catch (error) {
        console.error('[Quote3D] Błąd inicjalizacji handlera:', error);
        alert(`Błąd inicjalizacji: ${error.message}`);
    }
});

// Export dla compatibility
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Quote3DHandler;
}

console.log('[Quote3D] Script załadowany z popup AR v6.0');