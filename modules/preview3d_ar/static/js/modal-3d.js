// app/modules/preview3d_ar/static/js/modal-3d.js

/**
 * Modalny viewer 3D - obsługa pojedynczych produktów z URL
 */

class Modal3DHandler {
    constructor() {
        this.viewer = null;
        this.productData = null;

        // Elementy DOM
        this.loadingEl = document.getElementById('loading');
        this.errorEl = document.getElementById('error-message');
        this.errorTextEl = document.getElementById('error-text');
        this.productTitleEl = document.getElementById('product-title');
        this.productDimensionsEl = document.getElementById('product-dimensions');
        this.canvasEl = document.getElementById('wood-canvas');
        this.btnReset = document.getElementById('btn-reset');
        this.btnAr = document.getElementById('btn-ar');

        console.log('[Modal3D] Inicjalizacja handlera');
    }

    /**
     * Inicjalizuje modal - wywołaj po załadowaniu DOM
     */
    async init() {
        try {
            // Pobierz dane z URL
            this.productData = this.getProductDataFromURL();

            if (!this.productData) {
                this.showError('Brak danych produktu w URL');
                return;
            }

            console.log('[Modal3D] Dane produktu:', this.productData);

            // Aktualizuj informacje w headerze
            this.updateProductInfo();

            // Sprawdź czy canvas istnieje i ma rozmiar
            if (!this.canvasEl) {
                throw new Error('Canvas element not found');
            }

            console.log('Canvas dimensions:', this.canvasEl.clientWidth, 'x', this.canvasEl.clientHeight);

            // Sprawdź czy THREE.js jest załadowane
            if (typeof THREE === 'undefined') {
                throw new Error('THREE.js library not loaded');
            }

            if (typeof WoodViewer === 'undefined') {
                throw new Error('WoodViewer class not loaded');
            }

            // Inicjalizuj viewer
            await this.initializeViewer();

            // Setup kontroli
            this.setupControls();

            console.log('[Modal3D] Modal zainicjalizowany pomyślnie');

        } catch (error) {
            console.error('[Modal3D] Błąd inicjalizacji:', error);
            this.showError(`Błąd inicjalizacji: ${error.message}`);
        }
    }

    /**
     * Pobiera dane produktu z parametrów URL
     */
    getProductDataFromURL() {
        const urlParams = new URLSearchParams(window.location.search);
        const encodedData = urlParams.get('data');

        if (!encodedData) {
            return null;
        }

        try {
            return JSON.parse(decodeURIComponent(encodedData));
        } catch (error) {
            console.error('[Modal3D] Błąd parsowania danych:', error);
            return null;
        }
    }

    /**
     * Aktualizuje informacje o produkcie w headerze
     */
    updateProductInfo() {
        if (!this.productData) return;

        // Tytuł produktu
        const variant = this.productData.variant_code || this.productData.variant || 'Nieznany produkt';
        this.productTitleEl.textContent = variant.toUpperCase();

        // Wymiary
        const length = this.productData.length_cm || this.productData.length || 0;
        const width = this.productData.width_cm || this.productData.width || 0;
        const thickness = this.productData.thickness_cm || this.productData.thickness || 0;
        const quantity = this.productData.quantity || 1;

        let dimensionsText = `${length} × ${width} × ${thickness} cm`;
        if (quantity > 1) {
            dimensionsText += ` (${quantity} szt.)`;
        }

        this.productDimensionsEl.textContent = dimensionsText;
    }

    /**
     * Inicjalizuje WoodViewer
     */
    async initializeViewer() {
        try {
            console.log('[Modal3D] Tworzenie WoodViewer...');
            this.viewer = new WoodViewer(this.canvasEl);

            console.log('[Modal3D] Inicjalizacja sceny Three.js...');
            await this.viewer.init();

            console.log('[Modal3D] Sprawdzenie inicjalizacji...');
            if (!this.viewer.scene) {
                throw new Error('Scene nie została zainicjalizowana');
            }
            if (!this.viewer.camera) {
                throw new Error('Camera nie została zainicjalizowana');
            }
            if (!this.viewer.renderer) {
                throw new Error('Renderer nie został zainicjalizowany');
            }

            console.log('[Modal3D] Ładowanie produktu...');
            await this.viewer.loadProduct(this.productData);

            this.hideLoading();
            console.log('[Modal3D] Produkt załadowany pomyślnie');

            // Zapisz referencję globalnie dla debugowania
            window.currentViewer = this.viewer;

        } catch (error) {
            console.error('[Modal3D] Błąd ładowania produktu:', error);
            throw error;
        }
    }

    /**
     * Konfiguruje kontrolki interfejsu
     */
    setupControls() {
        // Przycisk Reset
        if (this.btnReset) {
            this.btnReset.addEventListener('click', () => {
                if (this.viewer && typeof this.viewer.resetCamera === 'function') {
                    this.viewer.resetCamera();
                }
            });
        }

        // Przycisk AR
        if (this.btnAr) {
            const isARSupported = this.isARSupported();
            if (isARSupported) {
                this.btnAr.style.display = 'flex';
                this.btnAr.addEventListener('click', () => {
                    this.handleARClick();
                });
            }
        }

        console.log('[Modal3D] Kontrolki skonfigurowane');
    }

    /**
     * Sprawdza czy AR jest obsługiwane
     */
    isARSupported() {
        return /iPad|iPhone|iPod|Android/.test(navigator.userAgent);
    }

    /**
     * Obsługuje kliknięcie przycisku AR
     */
    handleARClick() {
        if (!this.productData) return;

        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        const isAndroid = /Android/.test(navigator.userAgent);

        if (isIOS) {
            alert('Funkcja AR dla iOS będzie dostępna wkrótce!\n\nProdukt: ' +
                (this.productData.variant_code || this.productData.variant));
        } else if (isAndroid) {
            alert('Funkcja AR dla Android będzie dostępna wkrótce!\n\nProdukt: ' +
                (this.productData.variant_code || this.productData.variant));
        } else {
            alert('AR nie jest obsługiwane na tym urządzeniu.');
        }
    }

    /**
     * Pokazuje komunikat błędu
     */
    showError(message) {
        this.hideLoading();
        this.errorTextEl.textContent = message;
        this.errorEl.style.display = 'block';
        console.error('[Modal3D]', message);
    }

    /**
     * Ukrywa loading
     */
    hideLoading() {
        this.loadingEl.style.display = 'none';
    }

    /**
     * Debug helper
     */
    debug() {
        return {
            productData: this.productData,
            viewer: this.viewer,
            elements: {
                canvas: this.canvasEl,
                loading: this.loadingEl,
                error: this.errorEl
            },
            canvasSize: this.canvasEl ? {
                width: this.canvasEl.clientWidth,
                height: this.canvasEl.clientHeight
            } : null,
            threeJS: typeof THREE,
            woodViewer: typeof WoodViewer
        };
    }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', async function () {
    console.log('[Modal3D] DOM załadowany, inicjalizacja...');

    // Sprawdź czy wszystkie biblioteki są załadowane
    if (typeof THREE === 'undefined') {
        console.error('[Modal3D] THREE.js nie jest załadowane!');
        return;
    }

    if (typeof WoodViewer === 'undefined') {
        console.error('[Modal3D] WoodViewer nie jest załadowany!');
        return;
    }

    // Utwórz i zainicjalizuj handler
    const modal3D = new Modal3DHandler();
    window.modal3DHandler = modal3D; // Dla debugowania

    await modal3D.init();
});

// Export dla compatibility
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Modal3DHandler;
}

console.log('[Modal3D] Script załadowany');