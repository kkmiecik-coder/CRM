// app/modules/reports/static/js/sync_manager.js
/**
 * KOMPLETNIE NOWY SyncManager - System synchronizacji z obsługą problemów wymiarów
 * Obsługuje dwuetapowy proces: wybór dni -> wybór zamówień -> opcjonalne uzupełnienie wymiarów -> zapis
 */

/**
 * GLOBALNA FUNKCJA TOASTÓW - IMPLEMENTACJA
 * Ta funkcja zastąpi wszystkie alert() w aplikacji
 */
window.showToast = function (message, type = 'info', duration = 5000) {
    console.log(`[Toast] Pokazywanie toast: ${type.toUpperCase()} - ${message}`);

    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = createToastContainer();
    }

    const toastElement = document.createElement('div');
    toastElement.className = `toast ${type} show`;
    toastElement.setAttribute('role', 'alert');

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    toastElement.innerHTML = `
        <div class="toast-header">
            <i class="fas ${icons[type] || icons.info} toast-icon"></i>
            <strong class="toast-title">${getToastTitle(type)}</strong>
            <button type="button" class="toast-close" aria-label="Zamknij">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="toast-body">${message}</div>
    `;

    const closeBtn = toastElement.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => removeToast(toastElement));

    toastContainer.appendChild(toastElement);

    setTimeout(() => toastElement.classList.add('toast-visible'), 10);

    if (type !== 'error' && duration > 0) {
        setTimeout(() => removeToast(toastElement), duration);
    }
};

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = `
        position: fixed; top: 20px; right: 20px; z-index: 99999999;
        max-width: 400px; pointer-events: none;
    `;
    document.body.appendChild(container);
    addToastStyles();
    return container;
}

function generateProductKey(orderId, product, productIndex) {
    /**
     * ✅ ZSYNCHRONIZOWANA FUNKCJA: Identyczna z Python generate_product_key
     * PRIORYTET 1: product_index z prefiksem "idx_" (gdy podany)
     */
    // ✅ PRIORYTET 1: product_index z prefiksem "idx_" (gdy podany)
    if (productIndex !== null && productIndex !== undefined) {
        return `${orderId}_idx_${productIndex}`;
    }

    // PRIORYTET 2: order_product_id (najbardziej unikalne)
    if (product.order_product_id && String(product.order_product_id).trim()) {
        return `${orderId}_${product.order_product_id}`;
    }

    // PRIORYTET 3: product_id (jeśli nie jest pusty)
    if (product.product_id && String(product.product_id).trim() && product.product_id !== "") {
        return `${orderId}_${product.product_id}`;
    }

    // OSTATECZNOŚĆ: 'unknown' (może powodować konflikty)
    return `${orderId}_unknown`;
}

function addToastStyles() {
    if (document.getElementById('toast-styles')) return;

    const styleSheet = document.createElement('style');
    styleSheet.id = 'toast-styles';
    styleSheet.textContent = `
        .toast {
            pointer-events: auto; position: relative; margin-bottom: 12px;
            background: white; border-radius: 8px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
            border-left: 4px solid #007bff; opacity: 0; transform: translateX(100%);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); overflow: hidden;
            min-width: 300px; max-width: 400px;
        }
        .toast.toast-visible { opacity: 1; transform: translateX(0); }
        .toast.success { border-left-color: #28a745; }
        .toast.error { border-left-color: #dc3545; }
        .toast.warning { border-left-color: #ffc107; }
        .toast.info { border-left-color: #17a2b8; }
        .toast-header {
            display: flex; align-items: center; padding: 12px 16px 8px 16px;
            background: linear-gradient(135deg, rgba(0, 0, 0, 0.03) 0%, rgba(0, 0, 0, 0.01) 100%);
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
        }
        .toast-icon { margin-right: 8px; font-size: 16px; }
        .toast.success .toast-icon { color: #28a745; }
        .toast.error .toast-icon { color: #dc3545; }
        .toast.warning .toast-icon { color: #ffc107; }
        .toast.info .toast-icon { color: #17a2b8; }
        .toast-title { flex: 1; font-size: 14px; font-weight: 600; color: #333; }
        .toast-close {
            background: none; border: none; padding: 4px; cursor: pointer;
            color: #666; font-size: 12px; border-radius: 4px; transition: all 0.2s ease;
        }
        .toast-close:hover { background: rgba(0, 0, 0, 0.05); color: #333; }
        .toast-body { padding: 8px 16px 12px 16px; color: #555; font-size: 14px; line-height: 1.4; }
        .toast.removing { opacity: 0; transform: translateX(100%); margin-bottom: 0; }
    `;
    document.head.appendChild(styleSheet);
}

function removeToast(toastElement) {
    if (!toastElement || !toastElement.parentNode) return;
    toastElement.classList.add('removing');
    setTimeout(() => {
        if (toastElement.parentNode) {
            toastElement.parentNode.removeChild(toastElement);
        }
    }, 300);
}

function getToastTitle(type) {
    const titles = { success: 'Sukces', error: 'Błąd', warning: 'Ostrzeżenie', info: 'Informacja' };
    return titles[type] || titles.info;
}

class SyncManager {
    constructor() {
        console.log('[SyncManager] 🚀 Inicjalizacja nowego SyncManager z obsługą wymiarów');
        
        // === ELEMENTY DOM - KROK 1 (wybór dni) ===
        this.daysModal = null;
        this.daysSelect = null;
        this.datePreview = null;
        this.dateFromPreview = null;
        this.dateToPreview = null;
        this.daysConfirmBtn = null;
        this.daysCancelBtn = null;
        this.daysCloseBtn = null;

        // === ELEMENTY DOM - KROK 2 (lista zamówień) ===
        this.ordersModal = null;
        this.ordersLoadingState = null;
        this.ordersListContainer = null;
        this.ordersList = null;
        this.ordersEmptyState = null;
        this.ordersErrorState = null;
        this.ordersCount = null;
        this.selectAllBtn = null;
        this.deselectAllBtn = null;
        this.ordersBackBtn = null;
        this.ordersCancelBtn = null;
        this.ordersSaveBtn = null;
        this.ordersCloseBtn = null;

        // === ELEMENTY DOM - Loading overlay ===
        this.globalLoading = null;
        this.globalLoadingTitle = null;
        this.globalLoadingText = null;

        // === Template ===
        this.orderTemplate = null;

        // Referencja do VolumeManager dla dwukierunkowej komunikacji
        this.volumeManager = null;

        // === STAN APLIKACJI ===
        this.selectedDays = null;
        this.dateFrom = null;
        this.dateTo = null;
        this.fetchedOrders = [];
        this.selectedOrderIds = new Set();
        this.isProcessing = false;

        // === NOWE ELEMENTY DOM - KROK 3 (modal wymiarów) ===
        this.dimensionsModal = null;
        this.dimensionsList = null;
        this.dimensionsBackBtn = null;
        this.dimensionsSkipBtn = null;
        this.dimensionsSaveBtn = null;
        this.dimensionsCloseBtn = null;
        
        // === NOWE TEMPLATES ===
        this.dimensionOrderTemplate = null;
        this.dimensionProductTemplate = null;
        
        // === NOWY STAN ===
        this.ordersWithDimensionIssues = new Map();
        this.dimensionFixes = {};  // {order_id: {product_id: {length_cm: X, width_cm: Y, thickness_mm: Z}}}

        this.statusMap = {
            105112: 'Nowe - nieopłacone',
            155824: 'Nowe - opłacone',
            138619: 'W produkcji - surowe',
            148832: 'W produkcji - olejowanie',
            148831: 'W produkcji - bejcowanie',
            148830: 'W produkcji - lakierowanie',
            332355: 'W produkcji - suszenie usługowe',
            138620: 'Produkcja zakończona',
            138623: 'Zamówienie spakowane',
            105113: 'Paczka zgłoszona do wysyłki',
            105114: 'Wysłane - kurier',
            149763: 'Wysłane - transport WoodPower',
            149777: 'Czeka na odbiór osobisty',
            138624: 'Dostarczona - kurier',
            149778: 'Dostarczona - transport WoodPower',
            149779: 'Odebrane',
            316636: 'Reklamacja',
            138625: 'Zamówienie anulowane'
        };

        // NOWE właściwości dla obsługi objętości
        this.productsNeedingVolume = [];
        this.volumeModal = null;

        console.log('[SyncManager] ✅ Konstruktor zakończony');
    }

    // =====================================================
    // INICJALIZACJA
    // =====================================================

    init() {
        console.log('[SyncManager] 🔧 Rozpoczęcie inicjalizacji...');

        try {
            this.cacheElements();
            this.setupEventListeners();
            this.addConfirmationModalStyles();
            console.log('[SyncManager] ✅ Inicjalizacja zakończona pomyślnie');
        } catch (error) {
            console.error('[SyncManager] ❌ Błąd podczas inicjalizacji:', error);
        }

        this.bindEvents();

        // NOWA inicjalizacja: sprawdź dostępność VolumeManager
        this.initVolumeSupport();

    }

    initVolumeSupport() {
        // Poczekaj na załadowanie VolumeManager
        const checkVolumeManager = () => {
            if (window.volumeManager) {
                console.log('[SyncManager] VolumeManager dostępny');
                this.volumeManager = window.volumeManager;
            } else {
                setTimeout(checkVolumeManager, 100);
            }
        };
        checkVolumeManager();
    }

    cacheElements() {
        console.log('[SyncManager] 📋 Cachowanie elementów DOM...');

        // KROK 1 - Modal wyboru dni
        this.daysModal = document.getElementById('syncDaysModal');
        this.daysSelect = document.getElementById('daysSelect');
        this.datePreview = document.getElementById('datePreview');
        this.dateFromPreview = document.getElementById('dateFromPreview');
        this.dateToPreview = document.getElementById('dateToPreview');
        this.daysConfirmBtn = document.getElementById('syncDaysConfirm');
        this.daysCancelBtn = document.getElementById('syncDaysCancel');
        this.daysCloseBtn = document.getElementById('syncDaysModalClose');

        // DEBUG: Sprawdź które elementy nie zostały znalezione
        const step1Elements = {
            'daysModal': this.daysModal,
            'daysSelect': this.daysSelect,
            'datePreview': this.datePreview,
            'dateFromPreview': this.dateFromPreview,
            'dateToPreview': this.dateToPreview,
            'daysConfirmBtn': this.daysConfirmBtn,
            'daysCancelBtn': this.daysCancelBtn,
            'daysCloseBtn': this.daysCloseBtn
        };

        const missingStep1 = Object.entries(step1Elements)
            .filter(([name, element]) => !element)
            .map(([name]) => name);

        if (missingStep1.length > 0) {
            console.error('[SyncManager] ❌ BRAKUJĄCE ELEMENTY KROK 1:', missingStep1);
            console.log('[SyncManager] 🔍 Wszystkie elementy z id="sync*":',
                Array.from(document.querySelectorAll('[id*="sync"]')).map(el => el.id));
        }

        // KROK 2 - Modal zamówień (reszta kodu bez zmian)
        this.ordersModal = document.getElementById('syncOrdersModal');
        this.ordersLoadingState = document.getElementById('ordersLoadingState');
        this.ordersListContainer = document.getElementById('ordersListContainer');
        this.ordersList = document.getElementById('ordersList');
        this.ordersEmptyState = document.getElementById('ordersEmptyState');
        this.ordersErrorState = document.getElementById('ordersErrorState');
        this.ordersCount = document.getElementById('ordersCount');
        this.selectAllBtn = document.getElementById('selectAllOrders');
        this.deselectAllBtn = document.getElementById('deselectAllOrders');
        this.ordersBackBtn = document.getElementById('ordersBack');
        this.ordersCancelBtn = document.getElementById('ordersCancel');
        this.ordersSaveBtn = document.getElementById('ordersSave');
        this.ordersCloseBtn = document.getElementById('syncOrdersModalClose');

        // DEBUG: Sprawdź elementy KROK 2
        const step2Elements = {
            'ordersModal': this.ordersModal,
            'ordersLoadingState': this.ordersLoadingState,
            'ordersListContainer': this.ordersListContainer,
            'ordersList': this.ordersList,
            'ordersCount': this.ordersCount,
            'selectAllBtn': this.selectAllBtn,
            'deselectAllBtn': this.deselectAllBtn,
            'ordersBackBtn': this.ordersBackBtn,
            'ordersCancelBtn': this.ordersCancelBtn,
            'ordersSaveBtn': this.ordersSaveBtn,
            'ordersCloseBtn': this.ordersCloseBtn
        };

        const missingStep2 = Object.entries(step2Elements)
            .filter(([name, element]) => !element)
            .map(([name]) => name);

        if (missingStep2.length > 0) {
            console.error('[SyncManager] ❌ BRAKUJĄCE ELEMENTY KROK 2:', missingStep2);
        }

        // Reszta elementów...
        this.globalLoading = document.getElementById('syncLoadingOverlay');
        this.globalLoadingTitle = document.getElementById('syncLoadingTitle');
        this.globalLoadingText = document.getElementById('syncLoadingText');

        this.orderTemplate = document.getElementById('modalBlSyncOrderTemplate');
        if (!this.orderTemplate) {
            console.error('[SyncManager] ❌ Brak template modalBlSyncOrderTemplate');
            throw new Error('Brakujący template: modalBlSyncOrderTemplate');
        }
        console.log('[SyncManager] ✅ Template modalBlSyncOrderTemplate znaleziony');

        // Walidacja podstawowych elementów
        const requiredElements = [
            'daysModal', 'daysSelect', 'daysConfirmBtn',
            'ordersModal', 'ordersLoadingState', 'ordersListContainer', 'ordersList',
            'ordersCount', 'selectAllBtn', 'deselectAllBtn', 'ordersSaveBtn',
            'globalLoading'
        ];

        const missingElements = requiredElements.filter(element => !this[element]);
        if (missingElements.length > 0) {
            console.error('[SyncManager] ❌ BRAKUJĄCE WYMAGANE ELEMENTY DOM:', missingElements);

            // Dodatkowy debug - sprawdź cały DOM
            console.log('[SyncManager] 🔍 PEŁNY DEBUG DOM:');
            requiredElements.forEach(elementName => {
                const element = this[elementName];
                console.log(`  ${elementName}: ${element ? '✅ znaleziony' : '❌ BRAK'}`);
            });

            throw new Error(`Brakujące elementy DOM: ${missingElements.join(', ')}`);
        }

        console.log('[SyncManager] ✅ Wszystkie elementy DOM zacachowane');
    }

    bindEvents() {
        // Ta metoda może być pusta na razie lub zawierać podstawowe event listenery
        console.log('[SyncManager] 🔗 bindEvents - metoda dodana, ale podstawowa, bez kodu');
    }

    setupEventListeners() {
        console.log('[SyncManager] 🔗 Ustawianie event listenerów...');

        // === KROK 1: Wybór dni ===
        this.daysSelect.addEventListener('change', (e) => {
            console.log('[SyncManager] 📅 Zmiana wyboru dni:', e.target.value);
            this.handleDaysChange(e.target.value);
        });

        this.daysConfirmBtn.addEventListener('click', () => {
            console.log('[SyncManager] ✅ Potwierdzenie wyboru dni');
            this.handleDaysConfirm();
        });

        this.daysCancelBtn.addEventListener('click', () => {
            console.log('[SyncManager] ❌ Anulowanie wyboru dni');
            this.reset();
        });

        this.daysCloseBtn.addEventListener('click', () => {
            console.log('[SyncManager] ❌ Zamykanie modala dni (X)');
            this.reset();
        });

        // === KROK 2: Lista zamówień ===
        this.ordersBackBtn.addEventListener('click', () => {
            console.log('[SyncManager] ⬅️ Powrót do wyboru dni');
            this.hideOrdersModal();
            this.showDaysModal();
        });

        this.ordersCancelBtn.addEventListener('click', () => {
            console.log('[SyncManager] ❌ Anulowanie wyboru zamówień');
            this.reset();
        });

        this.ordersCloseBtn.addEventListener('click', () => {
            console.log('[SyncManager] ❌ Zamykanie modala zamówień (X)');
            this.reset();
        });

        // === PROGRESSIVE LOADING EVENT LISTENERS ===
        // Przycisk "Zaznacz wszystkie"
        if (this.selectAllBtn) {
            this.selectAllBtn.addEventListener('click', () => {
                this.selectAllOrders();
            });
        }

        // Przycisk "Odznacz wszystkie"  
        if (this.deselectAllBtn) {
            this.deselectAllBtn.addEventListener('click', () => {
                this.deselectAllOrders();
            });
        }

        // Przycisk zapisz zamówienia - będzie kierować do wymiarów lub zapisywać
        if (this.ordersSaveBtn) {
            this.ordersSaveBtn.addEventListener('click', async () => {
                await this.handleOrdersSave();
            });
        }

        // === KROK 3: Modal wymiarów (jeśli istnieje) ===
        if (this.dimensionsBackBtn) {
            this.dimensionsBackBtn.addEventListener('click', () => this.handleDimensionsBack());
        }

        if (this.dimensionsSkipBtn) {
            this.dimensionsSkipBtn.addEventListener('click', () => this.handleDimensionsSkip());
        }

        if (this.dimensionsSaveBtn) {
            this.dimensionsSaveBtn.addEventListener('click', () => this.handleDimensionsSave());
        }

        if (this.dimensionsCloseBtn) {
            this.dimensionsCloseBtn.addEventListener('click', () => this.reset());
        }

        // === Globalne event listenery ===
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (this.ordersModal && this.ordersModal.classList.contains('show')) {
                    console.log('[SyncManager] ⌨️ Escape - zamykanie modala zamówień');
                    this.reset();
                } else if (this.daysModal && this.daysModal.classList.contains('show')) {
                    console.log('[SyncManager] ⌨️ Escape - zamykanie modala dni');
                    this.reset();
                }
            }
        });

        // Zamykanie przez kliknięcie w overlay
        this.daysModal.addEventListener('click', (e) => {
            if (e.target === this.daysModal || e.target.classList.contains('sync-modal-overlay')) {
                console.log('[SyncManager] 🖱️ Kliknięcie w overlay - zamykanie modala dni');
                this.reset();
            }
        });

        this.ordersModal.addEventListener('click', (e) => {
            if (e.target === this.ordersModal || e.target.classList.contains('sync-modal-overlay')) {
                console.log('[SyncManager] 🖱️ Kliknięcie w overlay - zamykanie modala zamówień');
                this.reset();
            }
        });

        // Zamykanie przez kliknięcie w overlay - modal wymiarów
        if (this.dimensionsModal) {
            this.dimensionsModal.addEventListener('click', (e) => {
                if (e.target === this.dimensionsModal || e.target.classList.contains('sync-modal-overlay')) {
                    console.log('[SyncManager] 🖱️ Kliknięcie w overlay - zamykanie modala wymiarów');
                    this.reset();
                }
            });
        }

        console.log('[SyncManager] ✅ Event listenery ustawione');
    }

    // =====================================================
    // PUBLICZNE API
    // =====================================================

    showSyncModal() {
        console.log('[SyncManager] 🎯 Rozpoczęcie procesu synchronizacji');
        
        if (this.isProcessing) {
            console.warn('[SyncManager] ⚠️ Proces już trwa - ignorowanie');
            return;
        }

        this.resetState();
        this.showDaysModal();
    }

    // =====================================================
    // KROK 1: WYBÓR ILOŚCI DNI
    // =====================================================

    showDaysModal() {
        console.log('[SyncManager] 📅 Pokazywanie modala wyboru dni');

        // WALIDACJA: Sprawdź czy element istnieje
        if (!this.daysModal) {
            console.error('[SyncManager] ❌ Element daysModal nie istnieje! Sprawdzam DOM...');

            // Spróbuj ponownie znaleźć element
            this.daysModal = document.getElementById('syncDaysModal');

            if (!this.daysModal) {
                console.error('[SyncManager] ❌ syncDaysModal nadal nie istnieje w DOM');
                console.log('[SyncManager] 🔍 Dostępne elementy:',
                    Array.from(document.querySelectorAll('[id*="sync"]')).map(el => el.id));
                this.showErrorMessage('Błąd: Modal synchronizacji nie został znaleziony. Odśwież stronę.');
                return;
            }

            console.log('[SyncManager] ✅ Element daysModal znaleziony ponownie');
        }

        // POPRAWKA: Usuń konfliktujące klasy i ustaw wszystkie style na raz
        this.daysModal.className = 'sync-modal'; // Reset klas

        // Wymusz wszystkie style inline z najwyższym priorytetem
        this.daysModal.style.cssText = `
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100% !important;
            height: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            z-index: 9999 !important;
            opacity: 0 !important;
            visibility: visible !important;
            transition: opacity 0.3s ease !important;
            background: rgba(0, 0, 0, 0.5) !important;
        `;

        const modalContent = this.daysModal.querySelector('.sync-modal-content');
        if (modalContent) {
            modalContent.style.position = 'relative';
            modalContent.style.margin = 'auto';
        }

        // Dodaj klasę show i animuj opacity
        setTimeout(() => {
            this.daysModal.classList.add('show');
            this.daysModal.style.opacity = '1';
        }, 10);
    }

    hideDaysModal() {
        console.log('[SyncManager] 📅 Ukrywanie modala wyboru dni');

        // Animuj opacity przed ukryciem
        this.daysModal.style.opacity = '0';
        this.daysModal.classList.remove('show');

        setTimeout(() => {
            this.daysModal.style.display = 'none';
        }, 300);
    }

    handleDaysChange(selectedDays) {
        console.log('[SyncManager] 📊 Przetwarzanie zmiany dni:', selectedDays);

        if (!selectedDays || selectedDays === '') {
            console.log('[SyncManager] ❌ Brak wyboru - ukrywanie preview');
            this.hideDatePreview();
            this.daysConfirmBtn.disabled = true;
            return;
        }

        this.selectedDays = parseInt(selectedDays);
        this.calculateDateRange();
        this.showDatePreview();
        this.daysConfirmBtn.disabled = false;

        console.log('[SyncManager] ✅ Wybór dni zaktualizowany:', {
            selectedDays: this.selectedDays,
            dateFrom: this.dateFrom,
            dateTo: this.dateTo
        });
    }

    calculateDateRange() {
        const today = new Date();
        this.dateTo = this.formatDate(today);
        
        const fromDate = new Date(today);
        fromDate.setDate(today.getDate() - this.selectedDays + 1);
        this.dateFrom = this.formatDate(fromDate);

        console.log('[SyncManager] 📊 Obliczony zakres dat:', {
            from: this.dateFrom,
            to: this.dateTo,
            days: this.selectedDays
        });
    }

    showDatePreview() {
        if (this.dateFromPreview && this.dateToPreview && this.datePreview) {
            this.dateFromPreview.textContent = this.dateFrom;
            this.dateToPreview.textContent = this.dateTo;
            this.datePreview.style.display = 'block';
            
            console.log('[SyncManager] 👁️ Preview dat wyświetlony');
        }
    }

    hideDatePreview() {
        if (this.datePreview) {
            this.datePreview.style.display = 'none';
            console.log('[SyncManager] 👁️ Preview dat ukryty');
        }
    }

    async handleDaysConfirm() {
        console.log('[SyncManager] ✅ Potwierdzenie wyboru dni - przechodzę do pobierania zamówień');

        if (!this.selectedDays || !this.dateFrom || !this.dateTo) {
            console.error('[SyncManager] ❌ Brak wymaganych danych do pobrania zamówień');
            this.showError('Błąd: Nie wybrano prawidłowego zakresu dat');
            return;
        }

        this.hideDaysModal();
        this.showOrdersModal();
        await this.fetchOrders();
    }

    // =====================================================
    // KROK 2: LISTA ZAMÓWIEŃ
    // =====================================================

    showOrdersModal() {
        console.log('[SyncManager] 📦 Pokazywanie nowego modala zamówień');

        const modal = document.getElementById('syncOrdersModal');
        if (modal) {
            modal.style.display = 'flex';
            setTimeout(() => {
                modal.classList.add('show');
            }, 10);

            // Aktualizuj zakres dat w headerze
            this.updateModalDateRange();
        }
    }

    hideOrdersModal() {
        console.log('[SyncManager] 📦 Ukrywanie nowego modala zamówień');

        const modal = document.getElementById('syncOrdersModal');
        if (modal) {
            modal.classList.remove('show');
            setTimeout(() => {
                modal.style.display = 'none';
            }, 300);
        }
    }

    updateModalDateRange() {
        const dateRangeElement = document.getElementById('modalBlSyncDateRange');
        if (dateRangeElement && this.dateFrom && this.dateTo) {
            // ✅ DODAJ DEBUGOWANIE
            console.log('[SyncManager] 📅 Formatowanie dat:', {
                dateFrom: this.dateFrom,
                dateTo: this.dateTo
            });

            const formatDisplayDate = (dateStr) => {
                if (!dateStr || typeof dateStr !== 'string') {
                    return 'Błędna data';
                }
                const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
                if (match) {
                    const [, year, month, day] = match;
                    return `${day}.${month}.${year}`;
                }
                return dateStr;
            };

            const fromFormatted = formatDisplayDate(this.dateFrom);
            const toFormatted = formatDisplayDate(this.dateTo);

            dateRangeElement.textContent = `${fromFormatted} - ${toFormatted}`;
        }
    }

    formatPolishDate(dateStr) {
        try {
            let date;
            // Sprawdź format ISO YYYY-MM-DD
            if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
                date = new Date(dateStr + 'T00:00:00');
            } else {
                date = new Date(dateStr);
            }

            if (isNaN(date.getTime())) {
                return dateStr; // Fallback - zwróć oryginalny string
            }

            return date.toLocaleDateString('pl-PL');
        } catch (error) {
            console.error('[SyncManager] Błąd formatowania daty:', error);
            return dateStr;
        }
    }

    showOrdersLoading() {
        console.log('[SyncManager] ⏳ Pokazywanie loading state (nowy styl)');

        const loadingState = document.getElementById('ordersLoadingState');
        const listContainer = document.getElementById('ordersListContainer');
        const emptyState = document.getElementById('ordersEmptyState');
        const errorState = document.getElementById('ordersErrorState');

        if (loadingState) loadingState.style.display = 'block';
        if (listContainer) listContainer.style.display = 'none';
        if (emptyState) emptyState.style.display = 'none';
        if (errorState) errorState.style.display = 'none';
    }

    showOrdersList() {
        console.log('[SyncManager] 📋 Pokazywanie listy zamówień (nowy styl)');

        const loadingState = document.getElementById('ordersLoadingState');
        const listContainer = document.getElementById('ordersListContainer');
        const emptyState = document.getElementById('ordersEmptyState');
        const errorState = document.getElementById('ordersErrorState');

        if (loadingState) loadingState.style.display = 'none';
        if (listContainer) listContainer.style.display = 'block';
        if (emptyState) emptyState.style.display = 'none';
        if (errorState) errorState.style.display = 'none';
    }

    showOrdersEmptyState() {
        console.log('[SyncManager] 📭 Pokazywanie pustego stanu');

        this.ordersLoadingState.style.display = 'none';
        this.ordersListContainer.style.display = 'none';
        this.ordersEmptyState.style.display = 'block';
        this.ordersErrorState.style.display = 'none';
    }

    showOrdersError(errorMessage) {
        console.log('[SyncManager] ❌ Pokazywanie błędu:', errorMessage);

        this.ordersLoadingState.style.display = 'none';
        this.ordersListContainer.style.display = 'none';
        this.ordersEmptyState.style.display = 'none';
        this.ordersErrorState.style.display = 'block';

        // Aktualizuj tekst błędu jeśli element istnieje
        const errorText = this.ordersErrorState.querySelector('.error-message');
        if (errorText) {
            errorText.textContent = errorMessage;
        }
    }

    async fetchOrders() {
        console.log('[SyncManager] 📡 Pobieranie zamówień z SSE stream');

        try {
            // KROK 1: Łączenie z Baselinker
            this.showProgressiveLoading('Łączenie z Baselinker...', 1);

            // Walidacja danych
            const selectedDaysNumber = parseInt(this.selectedDays, 10);
            if (isNaN(selectedDaysNumber)) {
                throw new Error(`Nieprawidłowa wartość selectedDays: ${this.selectedDays}`);
            }

            const convertPolishDateToISO = (polishDate) => {
                if (/^\d{4}-\d{2}-\d{2}$/.test(polishDate)) return polishDate;
                const match = polishDate.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
                if (match) {
                    const [, day, month, year] = match;
                    return `${year}-${month}-${day}`;
                }
                throw new Error(`Nieprawidłowy format daty: ${polishDate}`);
            };

            const isoDateFrom = convertPolishDateToISO(this.dateFrom);
            const isoDateTo = convertPolishDateToISO(this.dateTo);

            const requestData = {
                date_from: isoDateFrom,
                date_to: isoDateTo,
                days_count: selectedDaysNumber,
                get_all_statuses: false
            };

            console.log('[SyncManager] 📤 SSE stream request:', requestData);

            // SSE stream przez fetch + ReadableStream
            const response = await fetch('/reports/api/fetch-orders-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                let errorBody = '';
                try { errorBody = await response.text(); } catch (e) {}
                throw new Error(`HTTP ${response.status}: ${response.statusText}. ${errorBody}`);
            }

            // Parsuj SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let result = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // zachowaj niekompletną linię

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;

                    try {
                        const event = JSON.parse(line.slice(6));
                        console.log('[SyncManager] 📨 SSE event:', event.type, event.message);

                        if (event.type === 'start') {
                            this.updateProgressiveLoading('Łączenie z Baselinker...', 1);
                        } else if (event.type === 'progress') {
                            // Prawdziwy postęp: "Pobrano X zamówień (strona Y/Z)"
                            this.updateProgressiveLoading(event.message, 2);
                        } else if (event.type === 'processing') {
                            this.updateProgressiveLoading(event.message, 3);
                        } else if (event.type === 'done') {
                            result = event;
                        }
                    } catch (e) {
                        console.warn('[SyncManager] Błąd parsowania SSE:', e, line);
                    }
                }
            }

            if (!result) {
                throw new Error('Stream zakończony bez danych końcowych');
            }

            // KROK 4: Przygotowywanie listy
            this.updateProgressiveLoading('Przygotowywanie listy...', 4);

            this.fetchedOrders = result.orders || [];
            console.log('[SyncManager] ✅ Pobrano zamówienia:', this.fetchedOrders.length);

            if (result.message) {
                this.showApiMessage(result.message, result.ignored_existing > 0 ? 'info' : 'success');
            }

            // Sprawdź problemy z objętością i wymiarami
            this.analyzeOrdersForDimensionIssues();

            await new Promise(resolve => setTimeout(resolve, 300));

            // Ukryj progressive loading
            this.hideProgressiveLoading();

            // Pokaż rezultat
            if (this.fetchedOrders.length === 0) {
                this.showOrdersEmptyState();
            } else {
                this.showOrdersListSuccess();
                if (result.volume_issues_count > 0) {
                    this.showVolumeIssuesInfo(result.volume_issues_count);
                }
            }

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd pobierania zamówień:', error);
            this.hideProgressiveLoading();
            this.showOrdersError(`Błąd połączenia: ${error.message}`);
        }
    }

    showOrdersListSuccess() {
        console.log('[SyncManager] ✅ Pokazywanie listy zamówień');

        // Ukryj loading, pokaż listę
        this.ordersLoadingState.style.display = 'none';
        this.ordersListContainer.style.display = 'flex';
        this.ordersEmptyState.style.display = 'none';
        this.ordersErrorState.style.display = 'none';

        // Aktualizuj licznik
        this.updateOrdersCount();

        // Renderuj zamówienia
        this.renderOrdersList();
    }

    // NOWA METODA: Analiza problemów z wymiarami
    analyzeOrdersForDimensionIssues() {
        console.log('[SyncManager] 🔍 Analizowanie problemów z wymiarami');

        this.ordersWithDimensionIssues.clear();

        this.fetchedOrders.forEach(order => {
            let hasIssues = false;
            const issueDetails = [];

            if (order.products) {
                order.products.forEach(product => {
                    // Sprawdź czy brakuje wymiarów
                    if (!product.length_cm || !product.width_cm || !product.thickness_mm) {
                        hasIssues = true;
                        issueDetails.push({
                            product_id: product.id || product.product_id,
                            product_name: product.name,
                            missing_dimensions: {
                                length: !product.length_cm,
                                width: !product.width_cm,
                                thickness: !product.thickness_mm
                            }
                        });
                    }

                    // Sprawdź czy wymiary są zerowe lub ujemne
                    if (product.length_cm <= 0 || product.width_cm <= 0 || product.thickness_mm <= 0) {
                        hasIssues = true;
                        if (!issueDetails.find(issue => issue.product_id === (product.id || product.product_id))) {
                            issueDetails.push({
                                product_id: product.id || product.product_id,
                                product_name: product.name,
                                invalid_dimensions: true
                            });
                        }
                    }
                });
            }

            if (hasIssues) {
                // POPRAWKA: Używaj order.order_id (z danych API) zamiast order.id
                const orderId = order.order_id || order.id;
                this.ordersWithDimensionIssues.set(orderId, {
                    order: order,
                    issues: issueDetails
                });

                // POPRAWKA: Używaj order.order_id dla logów
                console.log(`[SyncManager] ⚠️ Zamówienie ${order.order_id} ma problemy z wymiarami:`, issueDetails);
            }
        });

        console.log(`[SyncManager] 📊 Znaleziono ${this.ordersWithDimensionIssues.size} zamówień z problemami wymiarów`);
    }

    // NOWA metoda: pokazuje informację o problemach z objętością
    showVolumeIssuesInfo(count) {
        const container = document.getElementById('ordersListContainer');
        if (!container) return;

        // Usuń poprzednie powiadomienie jeśli istnieje
        const existingAlert = container.querySelector('.volume-issues-alert');
        if (existingAlert) {
            existingAlert.remove();
        }

        // Utwórz nowe powiadomienie
        const alert = document.createElement('div');
        alert.className = 'volume-issues-alert';
        alert.innerHTML = `
            <div class="alert alert-warning" style="margin-bottom: 20px;">
                <div class="alert-content">
                    <div class="alert-icon">⚠️</div>
                    <div class="alert-text">
                        <strong>Uwaga:</strong> ${count} produktów wymaga uzupełnienia objętości.
                        <br><small>Po wybraniu zamówień zostaniesz poproszony o wprowadzenie objętości dla produktów bez wymiarów.</small>
                    </div>
                </div>
            </div>
        `;

        // Wstaw na początku kontenera
        container.insertBefore(alert, container.firstChild);
    }

    // NOWA METODA: Renderowanie listy zamówień
    renderOrdersList() {
        console.log('[SyncManager] 🎨 Renderowanie listy zamówień');

        if (!this.ordersList || !this.orderTemplate) {
            console.error('[SyncManager] ❌ Brak ordersList lub orderTemplate');
            return;
        }

        // Wyczyść listę
        this.ordersList.innerHTML = '';

        this.fetchedOrders.forEach(order => {
            // POPRAWKA: Używaj createNewOrderElement zamiast createOrderElement
            const orderElement = this.createNewOrderElement(order);
            this.ordersList.appendChild(orderElement);
        });

        setTimeout(() => {
            this.selectAllOrders();
        }, 100);

        console.log(`[SyncManager] ✅ Wyrenderowano ${this.fetchedOrders.length} zamówień`);
    }

    createNewOrderElement(order) {
        console.log(`[SyncManager] 🏗️ Tworzenie nowego elementu zamówienia ${order.order_id}`);

        const template = document.getElementById('modalBlSyncOrderTemplate');
        if (!template) {
            console.error('[SyncManager] ❌ Brak template modalBlSyncOrderTemplate');
            return document.createElement('div');
        }

        const clone = template.content.cloneNode(true);
        const orderCard = clone.querySelector('.modal-bl-sync-order-card');

        if (!orderCard) {
            console.error('[SyncManager] ❌ Brak .modal-bl-sync-order-card w template');
            return clone;
        }

        // Ustaw ID zamówienia
        orderCard.setAttribute('data-order-id', order.order_id);

        // Ustaw checkbox
        const checkbox = clone.querySelector('.modal-bl-sync-checkbox');
        if (checkbox) {
            checkbox.setAttribute('data-order-id', order.order_id);
            checkbox.id = `order_${order.order_id}`;

            // Event listener dla nowego checkboxa
            checkbox.addEventListener('change', (e) => this.handleOrderSelection(e));
        }

        // Wypełnij dane zamówienia
        this.setNewOrderElementData(clone, order);

        // Wyłącz checkbox jeśli zamówienie już istnieje w bazie
        if (order.exists_in_database && checkbox) {
            checkbox.disabled = true;
            orderCard.classList.add('disabled');
        }

        console.log(`[SyncManager] ✅ Nowy element zamówienia ${order.order_id} utworzony`);
        return clone;
    }

    setNewOrderElementData(clone, order) {
        console.log(`[SyncManager] 🎨 Wypełnianie danych nowego zamówienia ${order.order_id}`);

        // Podstawowe elementy
        const orderNumber = clone.querySelector('.order-number');
        const customerName = clone.querySelector('.customer-name');
        const deliveryInfo = clone.querySelector('.delivery-info');
        const statusBadge = clone.querySelector('.order-status-badge');
        const statusBadgeContainer = clone.querySelector('.modal-bl-sync-status-badge');
        const baselinkerBtn = clone.querySelector('.baselinker-link');

        // Elementy kwot
        const paidAmount = clone.querySelector('.paid-amount');
        const remainingAmount = clone.querySelector('.remaining-amount');
        const productsAmount = clone.querySelector('.products-amount');
        const deliveryAmount = clone.querySelector('.delivery-amount');
        const totalAmount = clone.querySelector('.total-amount');

        // Daty zamówienia
        const dateAdd = clone.querySelector('.date-add');
        const dateConfirmed = clone.querySelector('.date-confirmed');
        const dateStatus = clone.querySelector('.date-status');

        // Ustaw podstawowe dane
        if (orderNumber) orderNumber.textContent = order.order_id || 'Brak ID';
        if (customerName) customerName.textContent = order.customer_name || order.delivery_fullname || 'Nieznany klient';

        // Informacje o dostawie  
        if (deliveryInfo) {
            const info = `${order.delivery_postcode || ''} ${order.delivery_city || ''}`.trim();
            deliveryInfo.textContent = info || 'Brak danych dostawy';
        }

        // Status zamówienia z kolorami
        if (statusBadge && statusBadgeContainer) {
            const statusId = order.order_status_id;
            const statusName = this.getStatusName(statusId);
            statusBadge.textContent = statusName;

            // Reset klas i dodaj odpowiednią
            statusBadgeContainer.className = 'modal-bl-sync-status-badge';
            if (statusId === 105112) {
                statusBadgeContainer.classList.add('status-new-unpaid');
            } else if (statusId === 155824) {
                statusBadgeContainer.classList.add('status-new-paid');
            } else if ([138619, 148832, 148831, 148830].includes(statusId)) {
                statusBadgeContainer.classList.add('status-in-production');
            } else if ([105113, 105114, 149763].includes(statusId)) {
                statusBadgeContainer.classList.add('status-shipped');
            } else if ([138624, 149778, 149779].includes(statusId)) {
                statusBadgeContainer.classList.add('status-delivered');
            } else if (statusId === 138625) {
                statusBadgeContainer.classList.add('status-cancelled');
            }
        }

        // Oblicz kwoty finansowe
        const financialData = this.calculateOrderAmounts(order);

        // Ustaw kwoty podsumowania
        if (productsAmount) productsAmount.textContent = financialData.productsAmount;
        if (deliveryAmount) deliveryAmount.textContent = financialData.deliveryAmount;
        if (totalAmount) totalAmount.textContent = financialData.totalAmount;

        // Ustaw kwoty płatności
        if (paidAmount) paidAmount.textContent = financialData.paidAmount;
        if (remainingAmount) {
            remainingAmount.textContent = financialData.remainingAmount;

            // Zmień kolor w zależności od kwoty
            if (financialData.remainingAmountNum > 0) {
                remainingAmount.classList.add('unpaid');
                // Dodaj też klasę do labela "Do zapłaty"
                const paymentLabel = remainingAmount.parentElement.querySelector('.modal-bl-sync-payment-label');
                if (paymentLabel && paymentLabel.textContent.includes('Do zapłaty')) {
                    paymentLabel.style.color = '#DC3545';
                }
            } else {
                remainingAmount.classList.remove('unpaid');
                remainingAmount.textContent = '0.00 PLN';
            }
        }

        // POPRAWKA: Link do Baselinker - prawidłowy schemat URL
        if (baselinkerBtn) {
            const correctUrl = `https://panel-f.baselinker.com/orders.php#order:${order.order_id}`;
            baselinkerBtn.href = correctUrl;
            baselinkerBtn.addEventListener('click', (e) => {
                e.preventDefault();
                window.open(correctUrl, '_blank');
                console.log(`[SyncManager] 🔗 Otwieranie Baselinker: ${correctUrl}`);
            });
        }

        // Ustaw daty - NOWE
        if (dateAdd) {
            dateAdd.textContent = order.date_add ? this.formatDateTime(order.date_add) : 'Brak';
        }
        if (dateConfirmed) {
            dateConfirmed.textContent = order.date_confirmed ? this.formatDateTime(order.date_confirmed) : 'Brak';
        }
        if (dateStatus) {
            dateStatus.textContent = order.date_in_status ? this.formatDateTime(order.date_in_status) : 'Brak';
        }

        // === NOWY KOD: Obsługa price type badge ===
        const priceTypeBadge = clone.querySelector('.price-type-badge');
        const priceTypeText = clone.querySelector('.price-type-text');

        if (priceTypeBadge && priceTypeText) {
            // Pobierz typ ceny z custom_extra_fields
            const priceType = order.custom_extra_fields && order.custom_extra_fields["106169"];

            if (priceType) {
                priceTypeBadge.style.display = 'block';

                // Usuń poprzednie klasy
                priceTypeBadge.classList.remove('netto', 'brutto', 'unknown');

                if (priceType.toLowerCase() === 'netto') {
                    priceTypeBadge.classList.add('netto');
                    priceTypeText.textContent = 'Netto';
                } else if (priceType.toLowerCase() === 'brutto') {
                    priceTypeBadge.classList.add('brutto');
                    priceTypeText.textContent = 'Brutto';
                } else {
                    priceTypeBadge.classList.add('unknown');
                    priceTypeText.textContent = 'Nieznane';
                }

                console.log(`[SyncManager] ℹ️ Zamówienie ${order.order_id} ma typ ceny: ${priceType}`);
            } else {
                // Brak informacji o price_type - ukryj badge
                priceTypeBadge.style.display = 'none';
            }
        }

        // === NOWY KOD: Stylowanie kafelka z problemami wymiarów ===
        const orderCard = clone.querySelector('.modal-bl-sync-order-card');
        if (orderCard) {
            // Sprawdź czy zamówienie ma usługi
            const hasManualInputNeeded = order.products && order.products.some(p =>
                p.volume_analysis && p.volume_analysis.analysis_type === 'manual_input_needed'
            );
            const hasVolumeOnly = order.products && order.products.some(p =>
                p.volume_analysis && p.volume_analysis.analysis_type === 'volume_only'
            );
            const hasServices = order.products && order.products.some(p =>
                p.volume_analysis && p.volume_analysis.analysis_type === 'service'
            );

            // Ogólne problemy z wymiarami (stara logika jako fallback)
            const hasDimensionIssues = order.has_dimension_issues || order.has_volume_issues;

            // ULEPSZONA LOGIKA KOLOROWANIA KAFELKA:
            if ((hasManualInputNeeded || hasDimensionIssues) && hasServices) {
                // Kombinacja problemów + usługi: tło czerwone/pomarańczowe + obrys niebieski
                orderCard.style.backgroundColor = hasManualInputNeeded ? '#FDF2F2' : '#FFFAF5'; // Czerwonawe lub pomarańczowe tło
                orderCard.style.border = '2px solid #007BFF'; // Niebieski obrys
                console.log(`[SyncManager] 🎨 Zamówienie ${order.order_id} ma problemy + usługi`);
            } else if (hasManualInputNeeded) {
                // Poważny problem: brak wymiarów i objętości - CZERWONY
                orderCard.style.backgroundColor = '#FDF2F2';
                orderCard.style.border = '2px solid #DC3545';
                console.log(`[SyncManager] 🚫 Zamówienie ${order.order_id} ma poważne problemy - czerwony`);
            } else if (hasVolumeOnly || hasDimensionIssues) {
                // Mniejszy problem: brak wymiarów ale ma objętość - POMARAŃCZOWY
                orderCard.style.backgroundColor = '#FFFAF5';
                orderCard.style.border = '2px solid #F48313';
                console.log(`[SyncManager] 📦 Zamówienie ${order.order_id} ma mniejsze problemy - pomarańczowy`);
            } else if (hasServices) {
                // Tylko usługi: niebieski
                orderCard.style.backgroundColor = '#F0F8FF';
                orderCard.style.border = '2px solid #007BFF';
                console.log(`[SyncManager] 🔧 Zamówienie ${order.order_id} ma tylko usługi - niebieski`);
            }
        }

        // Renderuj listę produktów w nowym stylu
        this.renderNewProductsList(clone, order);
    }

    renderNewProductsList(clone, order) {
        console.log(`[SyncManager] 📦 Renderowanie listy produktów (nowy styl) dla zamówienia ${order.order_id}`);

        const productsList = clone.querySelector('.modal-bl-sync-products-list');

        if (!order.products || !Array.isArray(order.products)) {
            console.log(`[SyncManager] ⚠️ Brak produktów dla zamówienia ${order.order_id}`);
            if (productsList) {
                productsList.innerHTML = '<div class="modal-bl-sync-product-item"><span class="modal-bl-sync-product-name">Brak danych o produktach</span></div>';
            }
            return;
        }

        // Wyczyść listę produktów
        if (productsList) {
            productsList.innerHTML = '';

            // Dodaj produkty do listy
            order.products.forEach((product) => {
                const productDiv = document.createElement('div');
                productDiv.className = 'modal-bl-sync-product-item';

                const productName = product.name || 'Nieznany produkt';
                const quantity = parseInt(product.quantity) || 1;
                const price = parseFloat(product.price_brutto) || 0;
                const totalPrice = price * quantity;

                // === NOWE: Sprawdź problemy z wymiarami i usługi ===
                const hasDimensionIssues = product.has_dimension_issues;
                const hasVolumeIssues = product.needs_manual_volume;
                const hasVolumeOnly = product.volume_analysis?.analysis_type === 'volume_only';
                const isService = product.volume_analysis?.analysis_type === 'service';

                // DODAJ SZCZEGÓŁOWY DEBUG
                console.log(`[SyncManager] 🔍 Produkt "${productName}":`, {
                    has_dimension_issues: hasDimensionIssues,
                    needs_manual_volume: hasVolumeIssues,
                    analysis_type: product.volume_analysis?.analysis_type,
                    has_volume_only: hasVolumeOnly,
                    is_service: isService
                });

                const hasProblems = hasDimensionIssues || hasVolumeIssues || hasVolumeOnly;

                // === NOWE: Ikona i kolor tekstu ===
                let problemIcon = '';
                let textColor = '#314254'; // Domyślny kolor

                if (isService) {
                    // Usługi: niebieski tekst + ikona
                    problemIcon = '🔧 ';
                    textColor = '#007BFF';
                    console.log(`[SyncManager] 🔧 Usługa - niebieski kolor`);
                } else if (product.volume_analysis?.analysis_type === 'manual_input_needed') {
                    // Brak wymiarów I objętości: CZERWONY (poważniejszy problem)
                    problemIcon = '🚫 ';
                    textColor = '#DC3545';
                    console.log(`[SyncManager] 🚫 Brak wymiarów i objętości - czerwony kolor`);
                } else if (product.volume_analysis?.analysis_type === 'volume_only') {
                    // Brak wymiarów, ale MA objętość: POMARAŃCZOWY (mniejszy problem)
                    problemIcon = '📦 ';
                    textColor = '#F48313';
                    console.log(`[SyncManager] 📦 Brak wymiarów, ale ma objętość - pomarańczowy kolor`);
                } else if (hasDimensionIssues) {
                    // Inne problemy z wymiarami: pomarańczowy (fallback)
                    problemIcon = '⚠️ ';
                    textColor = '#F48313';
                    console.log(`[SyncManager] ⚠️ Inne problemy wymiarów - pomarańczowy kolor`);
                }

                console.log(`[SyncManager] 🎨 Finalny kolor tekstu: ${textColor}, ikona: ${problemIcon}`);

                const nameWithQuantity = `${problemIcon}${productName} <span style="padding: 1px 5px; background-color: #EEEEEE; border-radius: 6px; font-size: 10px;">${quantity} szt.</span>`;

                productDiv.innerHTML = `
                <span class="modal-bl-sync-product-name" style="color: ${textColor}; font-weight: ${hasProblems || isService ? '600' : '400'};">${nameWithQuantity}</span>
                <span class="modal-bl-sync-product-price">${totalPrice.toFixed(2)} PLN</span>
            `;

                productsList.appendChild(productDiv);
            });

            console.log(`[SyncManager] 📦 Wyrenderowano ${order.products.length} produktów dla zamówienia ${order.order_id}`);
        }
    }

    updateOrdersCount() {
        console.log('[SyncManager] 🔄 Aktualizacja licznika zamówień (nowy styl)');

        // Pobierz rzeczywisty stan checkboxów
        const actuallySelectedOrderIds = this.getActuallySelectedOrderIds();
        const selectedCount = actuallySelectedOrderIds.length;
        const totalCount = this.fetchedOrders.length;

        // Synchronizuj selectedOrderIds z rzeczywistym stanem
        this.selectedOrderIds.clear();
        actuallySelectedOrderIds.forEach(id => this.selectedOrderIds.add(id));

        console.log(`[SyncManager] 📊 Rzeczywisty stan: ${selectedCount}/${totalCount} zamówień zaznaczonych`);

        // Aktualizuj licznik znalezionych zamówień
        const counter = document.getElementById('ordersCount');
        if (counter) {
            counter.textContent = `Znaleziono ${totalCount} ${totalCount === 1 ? 'zamówienie' : totalCount < 5 ? 'zamówienia' : 'zamówień'}`;
        }

        // Aktualizuj przycisk zapisu z prawidłową liczbą
        const saveBtn = document.getElementById('ordersSave');
        if (saveBtn) {
            saveBtn.disabled = selectedCount === 0;
            saveBtn.textContent = `Wybierz zamówienia`;

            console.log(`[SyncManager] 💾 Przycisk zaktualizowany: "Zapisz zamówienia (${selectedCount})"`);
        }
    }

    // ZAKTUALIZOWANA metoda tworzenia elementu zamówienia z oznaczeniem problemów objętości
    createOrderElement(order) {
        console.log(`[SyncManager] 🏗️ FALLBACK - createOrderElement dla zamówienia ${order.order_id}`);

        // POPRAWKA: Przekieruj do createNewOrderElement
        return this.createNewOrderElement(order);
    }

    getStatusText(status) {
        const statusMap = {
            'new': 'Nowe',
            'confirmed': 'Potwierdzone',
            'in_production': 'W produkcji',
            'ready': 'Gotowe',
            'sent': 'Wysłane',
            'delivered': 'Dostarczone',
            'cancelled': 'Anulowane',
            'returned': 'Zwrócone'
        };

        return statusMap[status] || status;
    }

    async startFetchingOrders() {
        console.log('[SyncManager] 🚀 Rozpoczynanie pobierania zamówień');

        if (this.isProcessing) {
            console.log('[SyncManager] ⏳ Już w trakcie pobierania, pomijam');
            return;
        }

        this.isProcessing = true;

        try {
            // Ukryj modal dni, pokaż modal zamówień
            this.hideDaysModal();
            this.showOrdersModal();

            // Pokaż stan loading w modal zamówień
            this.showOrdersLoadingState();

            // Rozpocznij pobieranie z progressive loading
            await this.fetchOrders();

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd w startFetchingOrders:', error);
            this.hideProgressiveLoading();
            this.showOrdersError(`Nieoczekiwany błąd: ${error.message}`);
        } finally {
            this.isProcessing = false;
        }
    }

    initProgressiveLoadingEventListeners() {
        console.log('[SyncManager] 🔗 Inicjalizacja event listenerów progressive loading');

        // Przycisk "Zaznacz wszystkie"
        if (this.selectAllBtn) {
            this.selectAllBtn.addEventListener('click', () => {
                this.selectAllOrders();
            });
        }

        // Przycisk "Odznacz wszystkie"  
        if (this.deselectAllBtn) {
            this.deselectAllBtn.addEventListener('click', () => {
                this.deselectAllOrders();
            });
        }

        // Przycisk zapisz zamówienia - będzie kierować do wymiarów lub zapisywać
        if (this.ordersSaveBtn) {
            this.ordersSaveBtn.addEventListener('click', async () => {
                await this.handleOrdersSave();
            });
        }
    }

    // NOWA METODA: Pokazywanie stanu loading w modal zamówień
    showOrdersLoadingState() {
        if (this.ordersLoadingState) {
            this.ordersLoadingState.style.display = 'block';
        }
        if (this.ordersListContainer) {
            this.ordersListContainer.style.display = 'none';
        }
        if (this.ordersEmptyState) {
            this.ordersEmptyState.style.display = 'none';
        }
        if (this.ordersErrorState) {
            this.ordersErrorState.style.display = 'none';
        }
    }

    handleOrderSelection(event) {
        const checkbox = event.target;
        const orderId = checkbox.getAttribute('data-order-id');
        const isSelected = checkbox.checked;

        console.log(`[SyncManager] 📋 Zmiana selekcji zamówienia ${orderId}: ${isSelected}`);

        if (isSelected) {
            this.selectedOrderIds.add(orderId);
            console.log(`[SyncManager] ✅ Zaznaczono zamówienie: ${orderId}`);
        } else {
            this.selectedOrderIds.delete(orderId);
            console.log(`[SyncManager] ❌ Odznaczono zamówienie: ${orderId}`);
        }

        // Aktualizuj UI
        this.updateOrdersCount();
        this.updateOrdersSaveButton();
    }

    updateOrdersSaveButton() {
        if (this.ordersSaveBtn) {
            const hasSelected = this.selectedOrderIds.size > 0;
            this.ordersSaveBtn.disabled = !hasSelected;

            if (hasSelected) {
                // POPRAWKA: Sprawdź problemy używając order.order_id (string)
                const hasProblems = Array.from(this.selectedOrderIds).some(id =>
                    this.ordersWithDimensionIssues.has(id) // id już jest stringiem
                );

                if (hasProblems) {
                    this.ordersSaveBtn.textContent = `Dalej (${this.selectedOrderIds.size}) - wymiary wymagane`;
                    this.ordersSaveBtn.classList.add('btn-warning');
                    this.ordersSaveBtn.classList.remove('btn-primary');
                } else {
                    this.ordersSaveBtn.textContent = `Zapisz zamówienia (${this.selectedOrderIds.size})`;
                    this.ordersSaveBtn.classList.add('btn-primary');
                    this.ordersSaveBtn.classList.remove('btn-warning');
                }
            } else {
                this.ordersSaveBtn.textContent = 'Wybierz zamówienia';
                this.ordersSaveBtn.classList.remove('btn-primary', 'btn-warning');
            }
        }
    }

    setOrderElementData(clone, order) {
        console.log(`[SyncManager] 🎨 Wypełnianie danych zamówienia ${order.order_id}`);

        // Podstawowe dane zamówienia
        const orderNumber = clone.querySelector('.order-number');
        const customerName = clone.querySelector('.customer-name');
        const orderDate = clone.querySelector('.order-date');
        const deliveryInfo = clone.querySelector('.delivery-info');

        // Elementy statusu i kwot
        const statusBadge = clone.querySelector('.order-status-badge');
        const productsAmount = clone.querySelector('.products-amount');
        const deliveryAmount = clone.querySelector('.delivery-amount');
        const totalAmount = clone.querySelector('.total-amount');
        const paidAmount = clone.querySelector('.paid-amount');
        const remainingAmount = clone.querySelector('.remaining-amount');
        const baselinkerLink = clone.querySelector('.baselinker-link');

        // Ustaw podstawowe dane
        if (orderNumber) orderNumber.textContent = order.order_id || 'Brak ID';
        if (customerName) customerName.textContent = order.customer_name || order.delivery_fullname || 'Nieznany klient';

        // Data - konwersja timestamp
        if (orderDate) {
            const date = order.date_add ?
                new Date(order.date_add * 1000).toLocaleDateString('pl-PL') : 'Brak daty';
            orderDate.textContent = date;
        }

        // Informacje o dostawie  
        if (deliveryInfo) {
            const info = `${order.delivery_postcode || ''} ${order.delivery_city || ''}`.trim();
            deliveryInfo.textContent = info || 'Brak danych dostawy';
        }

        // Status zamówienia
        if (statusBadge) {
            const statusId = order.order_status_id;
            const statusName = this.getStatusName(statusId);
            statusBadge.textContent = statusName;

            // Reset klas i dodaj odpowiednią
            statusBadge.className = 'order-status-badge';
            if (statusId === 105112) {
                statusBadge.classList.add('status-new-unpaid');
            } else if (statusId === 155824) {
                statusBadge.classList.add('status-new-paid');
            } else if ([138619, 148832, 148831, 148830].includes(statusId)) {
                statusBadge.classList.add('status-in-production');
            } else if ([105113, 105114, 149763].includes(statusId)) {
                statusBadge.classList.add('status-shipped');
            } else if ([138624, 149778, 149779].includes(statusId)) {
                statusBadge.classList.add('status-delivered');
            } else if (statusId === 138625) {
                statusBadge.classList.add('status-cancelled');
            }
        }

        // Kwoty finansowe
        const financialData = this.calculateOrderAmounts(order);
        if (productsAmount) productsAmount.textContent = financialData.productsAmount;
        if (deliveryAmount) deliveryAmount.textContent = financialData.deliveryAmount;
        if (totalAmount) totalAmount.textContent = financialData.totalAmount;
        if (paidAmount) paidAmount.textContent = financialData.paidAmount;
        if (remainingAmount) remainingAmount.textContent = financialData.remainingAmount;

        // POPRAWKA: Link do Baselinker - prawidłowy schemat URL
        if (baselinkerLink) {
            const correctUrl = `https://panel-f.baselinker.com/orders.php#order:${order.order_id}`;
            baselinkerLink.href = correctUrl;
            baselinkerLink.addEventListener('click', (e) => {
                e.preventDefault();
                window.open(correctUrl, '_blank');
                console.log(`[SyncManager] 🔗 Otwieranie Baselinker: ${correctUrl}`);
            });
        }

        // Renderuj listę produktów
        this.renderProductsList(clone, order);

    }

    // NOWA metoda: dodaje oznaczenie problemów z objętością
    addVolumeIssueBadge(orderItem, order) {
        const badge = orderItem.querySelector('.volume-issue-badge');
        if (badge) {
            const volumeProductsCount = order.products?.filter(p => p.needs_manual_volume)?.length || 0;
            badge.textContent = `📏 Brak objętości (${volumeProductsCount})`;
            badge.style.display = 'block';
            badge.title = `${volumeProductsCount} produktów wymaga uzupełnienia objętości`;
        }
    }

    // NOWA metoda: dodaje oznaczenie istniejącego zamówienia
    addExistsBadge(orderItem) {
        const existsBadge = orderItem.querySelector('.exists-badge');
        if (existsBadge) {
            existsBadge.style.display = 'block';
        }
    }

    // NOWA metoda: pokazuje stan postępu zapisu
    showSaveProgress(message = 'Zapisywanie...') {
        const saveBtn = document.getElementById('ordersSave');
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${message}`;
        }

        // Pokaż overlay ładowania jeśli istnieje
        const loadingOverlay = document.getElementById('syncLoadingOverlay');
        if (loadingOverlay) {
            const title = document.getElementById('syncLoadingTitle');
            const text = document.getElementById('syncLoadingText');

            if (title) title.textContent = message;
            if (text) text.textContent = 'Proszę czekać...';

            loadingOverlay.style.display = 'flex';
        }
    }

    // NOWA metoda: ukrywa stan postępu zapisu
    hideSaveProgress() {
        const saveBtn = document.getElementById('ordersSave');
        if (saveBtn) {
            saveBtn.disabled = this.selectedOrderIds.size === 0;
            this.updateOrdersCounter(); // Przywróć oryginalny tekst
        }

        // Ukryj overlay ładowania
        const loadingOverlay = document.getElementById('syncLoadingOverlay');
        if (loadingOverlay) {
            loadingOverlay.style.display = 'none';
        }
    }

    // NOWA metoda: pokazuje komunikat sukcesu
    showSuccessMessage(result) {
        const message = result.message || 'Zamówienia zostały pomyślnie zapisane';

        // Użyj toast jeśli dostępny, w przeciwnym razie alert
        if (window.showToast) {
            window.showToast(message, 'success');
        } else {
            alert(message);
        }

        console.log('[SyncManager] ✅ Sukces:', message);
    }

    validateSelectedOrders() {
        const selectedOrders = this.fetchedOrders.filter(order =>
            this.selectedOrderIds.has(order.order_id.toString())
        );

        const ordersWithIssues = selectedOrders.filter(order => order.has_volume_issues);

        return {
            valid: ordersWithIssues.length === 0,
            ordersWithIssues: ordersWithIssues,
            totalSelected: selectedOrders.length
        };
    }

    // NOWA metoda: czyści dane po zakończeniu procesu
    clearSyncData() {
        this.fetchedOrders = [];
        this.selectedOrderIds.clear();
        this.productsNeedingVolume = [];
        this.isProcessing = false;
    }

    // NOWA METODA: Automatyczne zaznaczanie nowych zamówień
    autoSelectNewOrders() {
        console.log('[SyncManager] 🔄 Automatyczne zaznaczanie nowych zamówień');

        let autoSelectedCount = 0;
        let totalNewOrders = 0;

        // Znajdź wszystkie checkboxy dla zamówień które nie istnieją w bazie
        const checkboxes = this.ordersList.querySelectorAll('.order-select');

        checkboxes.forEach(checkbox => {
            const orderId = checkbox.getAttribute('data-order-id');

            // Znajdź odpowiadające zamówienie w danych
            const order = this.fetchedOrders.find(o => o.order_id == orderId);

            if (order && !order.exists_in_db) {
                totalNewOrders++;

                if (!checkbox.disabled) {
                    // Zaznacz zamówienie które nie istnieje w bazie i nie jest zablokowane
                    checkbox.checked = true;
                    this.selectedOrderIds.add(orderId);
                    autoSelectedCount++;

                    console.log(`[SyncManager] ✅ Auto-zaznaczono nowe zamówienie: ${orderId}`);
                } else {
                    console.log(`[SyncManager] ⚠️ Zamówienie ${orderId} jest nowe, ale zablokowane (prawdopodobnie problemy z wymiarami)`);
                }
            }
        });

        console.log(`[SyncManager] 📊 Automatyczne zaznaczanie zakończone:`, {
            totalNewOrders: totalNewOrders,
            autoSelectedCount: autoSelectedCount,
            skippedCount: totalNewOrders - autoSelectedCount
        });

        // Zapisz statystyki do użycia w innych metodach
        this.autoSelectionStats = {
            totalNewOrders: totalNewOrders,
            autoSelectedCount: autoSelectedCount,
            skippedCount: totalNewOrders - autoSelectedCount
        };
    }

    renderSingleOrder(order) {
        const orderElement = this.orderTemplate.content.cloneNode(true);

        const orderItem = orderElement.querySelector('.order-item');
        if (orderItem) {
            orderItem.setAttribute('data-order-id', order.order_id);
        }

        // WAŻNE: Sprawdź problemy z wymiarami i zaznacz wizualnie
        console.log(`[SyncManager] 🔍 Sprawdzanie wymiarów zamówienia ${order.order_id}:`, {
            has_dimension_issues: order.has_dimension_issues,
            products_with_issues: order.products_with_issues
        });

        if (order.has_dimension_issues) {
            if (orderItem) {
                orderItem.classList.add('has-dimension-issues');
            }
            console.log(`[SyncManager] ⚠️ Zamówienie ${order.order_id} ma problemy z wymiarami:`, order.products_with_issues);

            this.ordersWithDimensionIssues.set(order.order_id, {
                order: order,
                products_with_issues: order.products_with_issues || []
            });

            // Pokaż badge problemów z wymiarami
            const dimensionsBadge = orderElement.querySelector('.dimensions-issue-badge');
            if (dimensionsBadge) {
                dimensionsBadge.style.display = 'block';
                const issuesCount = order.products_with_issues?.length || 0;
                dimensionsBadge.textContent = `⚠️ Brak wymiarów (${issuesCount})`;
            }
        }

        // === NOWY KOD: Obsługa price type badge ===
        const priceTypeBadge = orderElement.querySelector('.price-type-badge');
        const priceTypeText = orderElement.querySelector('.price-type-text');

        if (priceTypeBadge && priceTypeText && order.price_type) {
            priceTypeBadge.style.display = 'block';

            // Usuń poprzednie klasy
            priceTypeBadge.classList.remove('netto', 'brutto', 'unknown');

            if (order.price_type === 'netto') {
                priceTypeBadge.classList.add('netto');
                priceTypeText.textContent = 'Netto';
            } else if (order.price_type === 'brutto') {
                priceTypeBadge.classList.add('brutto');
                priceTypeText.textContent = 'Brutto';
            } else {
                priceTypeBadge.classList.add('unknown');
                priceTypeText.textContent = 'Nieznane';
            }

            console.log(`[SyncManager] ℹ️ Zamówienie ${order.order_id} ma typ ceny: ${order.price_type}`);
        } else if (priceTypeBadge) {
            // Brak informacji o price_type - ukryj badge
            priceTypeBadge.style.display = 'none';
        }

        const checkbox = orderElement.querySelector('.order-select');
        if (checkbox) {
            checkbox.setAttribute('data-order-id', order.order_id);
        }

        if (order.exists_in_db) {
            console.log(`[SyncManager] ⚠️ Zamówienie ${order.order_id} już istnieje w bazie`);
            if (orderItem) {
                orderItem.classList.add('disabled');
            }
            if (checkbox) {
                checkbox.disabled = true;
            }
            const existsBadge = orderElement.querySelector('.exists-badge');
            if (existsBadge) {
                existsBadge.style.display = 'block';
            }
        } else {
            if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                    this.handleOrderCheckboxChange(order.order_id, e.target.checked);
                });
            }
        }

        if (orderCard && (order.has_dimension_issues || order.has_volume_issues)) {
            orderCard.style.backgroundColor = '#FFFAF5';
            orderCard.style.border = '2px solid #F48313';
        }

        // Ustawianie statusu
        const statusBadge = orderElement.querySelector('.order-status-badge');
        if (statusBadge) {
            const statusId = order.order_status_id;
            const statusName = this.getStatusName(statusId);

            statusBadge.textContent = statusName;
            statusBadge.className = 'order-status-badge';

            // Dodaj klasę CSS w zależności od statusu
            if (statusId === 105112) {
                statusBadge.classList.add('status-new-unpaid');
            } else if (statusId === 155824) {
                statusBadge.classList.add('status-new-paid');
            } else if ([138619, 148832, 148831, 148830].includes(statusId)) {
                statusBadge.classList.add('status-in-production');
            } else if ([105113, 105114, 149763].includes(statusId)) {
                statusBadge.classList.add('status-shipped');
            } else if ([138624, 149778, 149779].includes(statusId)) {
                statusBadge.classList.add('status-delivered');
            } else if (statusId === 138625) {
                statusBadge.classList.add('status-cancelled');
            }

            console.log(`[SyncManager] 📊 Status zamówienia ${order.order_id}: ${statusName} (ID: ${statusId})`);
        }

        // Obliczanie kwot finansowych
        const financialData = this.calculateOrderAmounts(order);

        // Bezpieczne ustawianie tekstu
        const safeSetText = (selector, text, fallback = 'Brak danych') => {
            const element = orderElement.querySelector(selector);
            if (element) {
                element.textContent = text || fallback;
            }
        };

        // Wypełnij podstawowe informacje
        safeSetText('.order-number', order.order_id);
        safeSetText('.customer-name', order.customer_name || order.delivery_fullname);

        // Data - konwersja timestamp na datę
        const orderDate = order.date_add ? new Date(order.date_add * 1000).toLocaleDateString('pl-PL') : 'Brak daty';
        safeSetText('.order-date', orderDate);

        // Informacje o dostawie
        const deliveryInfo = `${order.delivery_postcode || ''} ${order.delivery_city || ''}`.trim();
        safeSetText('.delivery-info', deliveryInfo);

        // NOWE: Renderuj listę produktów
        this.renderProductsList(orderElement, order);

        // Wypełnij szczegółowe kwoty
        safeSetText('.products-amount', financialData.productsAmount);
        safeSetText('.delivery-amount', financialData.deliveryAmount);
        safeSetText('.total-amount', financialData.totalAmount);

        // Link do Baselinker
        const baselinkerLink = orderElement.querySelector('.baselinker-link');
        if (baselinkerLink) {
            baselinkerLink.addEventListener('click', (e) => {
                e.preventDefault();
                const url = `https://panel.baselinker.com/orders.php?action=order_details&order_id=${order.order_id}`;
                window.open(url, '_blank');
                console.log(`[SyncManager] 🔗 Otwieranie Baselinker dla zamówienia ${order.order_id}`);
            });
        }

        // Dodaj element do listy
        if (this.ordersList) {
            this.ordersList.appendChild(orderElement);
        }
    }

    renderProductsList(clone, order) {
        console.log(`[SyncManager] 📦 Renderowanie listy produktów dla zamówienia ${order.order_id}`);

        const productsSection = clone.querySelector('.products-section');
        const productsCountText = clone.querySelector('.products-count-text');
        const productsList = clone.querySelector('.products-list');

        if (!order.products || !Array.isArray(order.products)) {
            console.log(`[SyncManager] ⚠️ Brak produktów dla zamówienia ${order.order_id}`);
            if (productsCountText) {
                productsCountText.textContent = 'Brak danych o produktach';
            }
            if (productsSection) {
                productsSection.style.display = 'none';
            }
            return;
        }

        const productsCount = order.products.length;
        const problemProducts = order.products.filter(p =>
            p.has_dimension_issues || p.needs_manual_volume
        ).length;

        // Ustaw licznik produktów
        if (productsCountText) {
            let countText = `${productsCount} ${productsCount === 1 ? 'produkt' :
                productsCount < 5 ? 'produkty' : 'produktów'}`;

            if (problemProducts > 0) {
                countText += ` (${problemProducts} wymaga uzupełnienia)`;
            }

            productsCountText.textContent = countText;
            productsCountText.style.color = problemProducts > 0 ? '#dc3545' : '#495057';
            productsCountText.style.fontWeight = problemProducts > 0 ? '600' : '500';
        }

        // Wyczyść listę produktów
        if (productsList) {
            productsList.innerHTML = '';

            // Dodaj produkty do listy
            order.products.forEach((product, index) => {
                const productDiv = document.createElement('div');
                productDiv.className = 'product-item';
                productDiv.style.cssText = `
                padding: 8px 12px;
                border-bottom: 1px solid #f1f3f4;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 12px;
            `;

                // Usuń border z ostatniego elementu
                if (index === order.products.length - 1) {
                    productDiv.style.borderBottom = 'none';
                }

                // Oznacz produkty z problemami
                const hasDimensionIssues = product.has_dimension_issues;
                const hasVolumeIssues = product.needs_manual_volume;

                if (hasDimensionIssues || hasVolumeIssues) {
                    productDiv.classList.add('has-dimension-issues');
                    productDiv.style.backgroundColor = '#fff5f5';
                    productDiv.style.borderLeft = '3px solid #dc3545';
                    productDiv.style.paddingLeft = '8px';
                }

                const productName = product.name || 'Nieznany produkt';
                const quantity = parseInt(product.quantity) || 1;
                const price = parseFloat(product.price_brutto) || 0;
                const totalPrice = price * quantity;

                // Określ ikonę problemu
                let problemIcon = '';
                if (hasDimensionIssues && hasVolumeIssues) {
                    problemIcon = '⚠️📏 ';
                } else if (hasDimensionIssues) {
                    problemIcon = '⚠️ ';
                } else if (hasVolumeIssues) {
                    problemIcon = '📏 ';
                }

                productDiv.innerHTML = `
                <div class="product-name" style="flex: 1; color: ${hasDimensionIssues || hasVolumeIssues ? '#F48313' : '#2c3e50'}; margin-right: 10px; line-height: 1.3; font-weight: ${hasDimensionIssues || hasVolumeIssues ? '600' : 'normal'};">
                    ${problemIcon}${productName}
                </div>
                <div class="product-details" style="display: flex; gap: 12px; align-items: center; color: #6c757d; white-space: nowrap;">
                    <span class="product-quantity" style="font-weight: 500;">${quantity} szt.</span>
                    <span class="product-price" style="font-weight: 500;">${totalPrice.toFixed(2)} PLN</span>
                </div>
            `;

                productsList.appendChild(productDiv);
            });

            console.log(`[SyncManager] 📦 Wyrenderowano ${order.products.length} produktów dla zamówienia ${order.order_id}`);
        }
    }

    updateRemainingAmount(clone, financialData) {
        const remainingAmount = clone.querySelector('.remaining-amount');
        if (remainingAmount) {
            remainingAmount.textContent = financialData.remainingAmount;

            // Zmień kolor w zależności od kwoty
            if (financialData.remainingAmountNum > 0) {
                remainingAmount.style.color = '#dc3545'; // Czerwony jeśli jest do zapłaty
            } else {
                remainingAmount.style.color = '#28a745'; // Zielony jeśli opłacone
                remainingAmount.textContent = 'Opłacone';
            }
        }
    }

    addOrderBadges(orderItem, order) {
        console.log(`[SyncManager] 🏷️ Dodawanie badge'ów dla zamówienia ${order.order_id}`);

        // Priorytet badge'ów (tylko jeden na raz):
        // 1. Zamówienie już w bazie (zielony)
        // 2. Problemy z wymiarami (czerwony) 
        // 3. Problemy z objętością (pomarańczowy)

        if (order.exists_in_database) {
            this.addExistsBadge(orderItem);
            console.log(`[SyncManager] 🏷️ Zamówienie ${order.order_id}: badge "W bazie"`);
            return;
        }

        if (order.has_dimension_issues) {
            this.addDimensionIssueBadge(orderItem, order);
            console.log(`[SyncManager] 🏷️ Zamówienie ${order.order_id}: badge "Brak wymiarów"`);
            return;
        }

        if (order.has_volume_issues) {
            this.addVolumeIssueBadge(orderItem, order);
            console.log(`[SyncManager] 🏷️ Zamówienie ${order.order_id}: badge "Brak objętości"`);
        }
    }

    addDimensionIssueBadge(orderItem, order) {
        const badge = orderItem.querySelector('.dimensions-issue-badge');
        if (badge) {
            const issuesCount = order.products_with_issues?.length ||
                order.products?.filter(p => p.has_dimension_issues)?.length || 0;
            badge.textContent = `⚠️ Brak wymiarów (${issuesCount})`;
            badge.style.display = 'block';
            badge.title = `${issuesCount} produktów nie ma wymiarów w nazwie`;
        }
    }

    // NOWA METODA: Renderowanie pojedynczych produktów w liście
    renderProductsInList(productsList, order) {
        if (!order.products || !Array.isArray(order.products)) {
            return;
        }

        // Stwórz mapę produktów z problemami wymiarów dla szybkiego dostępu
        const problemProductsMap = new Map();
        if (order.products_with_issues) {
            order.products_with_issues.forEach(problemProduct => {
                // Użyj nazwy produktu jako klucza, bo product_id może nie być unikalne
                problemProductsMap.set(problemProduct.name, problemProduct);
            });
        }

        order.products.forEach((product, index) => {
            const productDiv = document.createElement('div');
            productDiv.className = 'product-item';

            const productName = product.name || 'Nieznany produkt';
            const quantity = parseInt(product.quantity) || 1;
            const price = parseFloat(product.price_brutto) || 0;
            const totalPrice = price * quantity;

            // Sprawdź czy produkt ma problemy z wymiarami
            const hasDimensionIssues = problemProductsMap.has(productName);
            if (hasDimensionIssues) {
                productDiv.classList.add('has-dimension-issues');
            }

            productDiv.innerHTML = `
            <div class="product-name">
                ${hasDimensionIssues ? '⚠️ ' : ''}${productName}
            </div>
            <div class="product-details">
                <span class="product-quantity">${quantity} szt.</span>
                <span class="product-price">${totalPrice.toFixed(2)} PLN</span>
            </div>
        `;

            productsList.appendChild(productDiv);
        });

        console.log(`[SyncManager] 📦 Wyrenderowano ${order.products.length} produktów dla zamówienia ${order.order_id}`);
    }

    getStatusName(statusId) {
        if (!this.statusMap) {
            this.statusMap = {
                105112: 'NOWE - NIEOPŁACONE',
                155824: 'NOWE - OPŁACONE',
                138619: 'W PRODUKCJI - SUROWE',
                148832: 'W PRODUKCJI - OLEJOWANIE',
                148831: 'W PRODUKCJI - BEJCOWANIE',
                148830: 'W PRODUKCJI - LAKIEROWANIE',
                138620: 'PRODUKCJA ZAKOŃCZONA',
                138623: 'ZAMÓWIENIE SPAKOWANE',
                105113: 'PACZKA ZGŁOSZONA DO WYSYŁKI',
                105114: 'WYSŁANE - KURIER',
                149763: 'WYSŁANE - TRANSPORT WOODPOWER',
                149777: 'CZEKA NA ODBIÓR OSOBISTY',
                138624: 'DOSTARCZONA - KURIER',
                149778: 'DOSTARCZONA - TRANSPORT WOODPOWER',
                149779: 'ODEBRANE',
                138625: 'ZAMÓWIENIE ANULOWANE'
            };
        }

        return this.statusMap[statusId] || `STATUS ${statusId}` || 'NIEZNANY';
    }

    // Obliczanie kwot zamówienia
    calculateOrderAmounts(order) {
        console.log(`[SyncManager] 💰 Obliczanie kwot dla zamówienia ${order.order_id}`);

        let productsTotal = 0;
        let deliveryPrice = parseFloat(order.delivery_price) || 0;

        // Oblicz sumę produktów z order.products jeśli istnieje (preferowane)
        if (order.products && Array.isArray(order.products)) {
            productsTotal = order.products.reduce((sum, product) => {
                const price = parseFloat(product.price_brutto) || 0;
                const quantity = parseInt(product.quantity) || 1;
                return sum + (price * quantity);
            }, 0);
            console.log(`[SyncManager] 📊 Suma z produktów: ${productsTotal} PLN`);
        } else {
            // Fallback: jeśli nie ma szczegółów produktów, użyj order_value minus dostawa
            const orderValue = parseFloat(order.order_value) || 0;
            productsTotal = Math.max(0, orderValue - deliveryPrice); // zabezpieczenie przed ujemną wartością
            console.log(`[SyncManager] 📊 Suma fallback (order_value - delivery): ${productsTotal} PLN`);
        }

        const totalAmount = productsTotal + deliveryPrice;

        // NOWE: Obsługa payment_done i obliczanie pozostałej kwoty
        const paymentDone = parseFloat(order.payment_done) || 0;
        const remainingAmount = Math.max(0, totalAmount - paymentDone);

        // Formatowanie kwot
        const formatCurrency = (amount) => {
            return `${amount.toFixed(2)} PLN`;
        };

        const result = {
            productsAmount: formatCurrency(productsTotal),
            deliveryAmount: formatCurrency(deliveryPrice),
            totalAmount: formatCurrency(totalAmount),
            paidAmount: formatCurrency(paymentDone),
            remainingAmount: formatCurrency(remainingAmount),

            // Surowe wartości do obliczeń
            productsTotal: productsTotal,
            deliveryPrice: deliveryPrice,
            totalAmountNum: totalAmount,
            paidAmountNum: paymentDone,
            remainingAmountNum: remainingAmount
        };

        console.log(`[SyncManager] 💰 Kwoty zamówienia ${order.order_id}:`, {
            produkty: productsTotal,
            dostawa: deliveryPrice,
            razem: totalAmount,
            zapłacono: paymentDone,
            pozostało: remainingAmount
        });

        return result;
    }

    handleOrderCheckboxChange(orderId, isChecked) {
        console.log(`[SyncManager] ☑️ Zmiana checkbox zamówienia ${orderId}:`, isChecked);

        // Konwertuj na string aby być spójnym z resztą kodu
        const orderIdStr = String(orderId);

        if (isChecked) {
            this.selectedOrderIds.add(orderIdStr);
        } else {
            this.selectedOrderIds.delete(orderIdStr);
        }

        // DODANE: Sprawdź czy checkbox rzeczywiście został zaznaczony/odznaczony
        const checkbox = this.ordersList.querySelector(`[data-order-id="${orderIdStr}"]`);
        if (checkbox && checkbox.checked !== isChecked) {
            console.warn(`[SyncManager] ⚠️ Niezgodność stanu checkbox dla ${orderIdStr}: checkbox.checked=${checkbox.checked}, isChecked=${isChecked}`);
        }

        this.updateSaveButton();
        console.log('[SyncManager] 📊 Aktualnie wybrane zamówienia:', Array.from(this.selectedOrderIds));
    }

    // POPRAWKA 3: Dodaj walidację czy zamówienia netto powinny iść do modala wymiarów
    shouldCheckDimensions(order) {
        // Zamówienia netto nie wymagają sprawdzania wymiarów
        if (order.price_type === 'netto') {
            console.log(`[SyncManager] ℹ️ Zamówienie ${order.order_id} jest typu NETTO - pomijam sprawdzanie wymiarów`);
            return false;
        }

        // Tylko zamówienia brutto lub bez typu wymagają sprawdzania wymiarów
        return order.has_dimension_issues === true;
    }

    selectAllOrders() {
        console.log('[SyncManager] ✅ Zaznaczanie wszystkich zamówień');

        this.selectedOrderIds.clear();

        // POPRAWKA: Używaj order.order_id (to co przychodzi z API)
        this.fetchedOrders.forEach(order => {
            const orderId = String(order.order_id); // order_id z API
            this.selectedOrderIds.add(orderId);
        });

        // Aktualizuj checkboxy - znajdź po data-order-id
        const checkboxes = this.ordersList.querySelectorAll('.modal-bl-sync-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = true;
        });

        this.updateOrdersCount();
        this.updateOrdersSaveButton();
    }

    deselectAllOrders() {
        console.log('[SyncManager] ❌ Odznaczanie wszystkich zamówień');

        this.selectedOrderIds.clear();

        // Aktualizuj checkboxy - znajdź po właściwej klasie
        const checkboxes = this.ordersList.querySelectorAll('.modal-bl-sync-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });

        this.updateOrdersCount();
        this.updateOrdersSaveButton();
    }

    showEmptyState() {
        console.log('[SyncManager] 📭 Pokazywanie empty state (nowy styl)');

        const loadingState = document.getElementById('ordersLoadingState');
        const listContainer = document.getElementById('ordersListContainer');
        const emptyState = document.getElementById('ordersEmptyState');
        const errorState = document.getElementById('ordersErrorState');

        if (loadingState) loadingState.style.display = 'none';
        if (listContainer) listContainer.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        if (errorState) errorState.style.display = 'none';
    }

    updateSaveButton() {
        const selectedCount = this.selectedOrderIds.size;
        
        if (this.ordersSaveBtn) {
            this.ordersSaveBtn.disabled = selectedCount === 0;
            this.ordersSaveBtn.textContent = `Zapisz zamówienia (${selectedCount})`;
        }

        console.log('[SyncManager] 🔄 Przycisk zapisz zaktualizowany:', selectedCount);
    }

    showDimensionsModal(orderIdsWithIssues) {
        console.log('[SyncManager] 📐 Pokazywanie modala wymiarów:', orderIdsWithIssues);
        
        this.hideOrdersModal();
        this.renderDimensionsList(orderIdsWithIssues);
        
        this.dimensionsModal.style.display = 'flex';
        setTimeout(() => {
            this.dimensionsModal.classList.add('show');
        }, 10);
    }

    hideDimensionsModal() {
        console.log('[SyncManager] 📐 Ukrywanie modala wymiarów');
        
        this.dimensionsModal.classList.remove('show');
        setTimeout(() => {
            this.dimensionsModal.style.display = 'none';
        }, 300);
    }

    renderDimensionsList(orderIdsWithIssues) {
        console.log('[SyncManager] 🎨 Renderowanie listy wymiarów dla zamówień:', orderIdsWithIssues);
        
        if (!this.dimensionsList || !this.dimensionOrderTemplate || !this.dimensionProductTemplate) {
            console.error('[SyncManager] ❌ Brak wymaganych elementów do renderowania wymiarów');
            return;
        }

        this.dimensionsList.innerHTML = '';
        this.dimensionFixes = {};

        orderIdsWithIssues.forEach(orderId => {
            const order = this.fetchedOrders.find(o => o.order_id == orderId);
            if (order && order.has_dimension_issues) {
                this.renderSingleOrderDimensions(order);
            }
        });

        console.log('[SyncManager] ✅ Lista wymiarów wyrenderowana');
    }

    renderSingleOrderDimensions(order) {
        const orderElement = this.dimensionOrderTemplate.content.cloneNode(true);
        
        // Wypełnij header zamówienia
        orderElement.querySelector('.order-number').textContent = order.order_id;
        orderElement.querySelector('.customer-name').textContent = order.delivery_fullname || 'Brak nazwy';
        orderElement.querySelector('.order-date').textContent = new Date(order.date_add).toLocaleDateString('pl-PL');
        
        const productsContainer = orderElement.querySelector('.dimension-products-list');
        
        // Renderuj produkty z problemami wymiarów
        order.products_with_issues.forEach(product => {
            const productElement = this.renderSingleProductDimensions(order.order_id, product);
            productsContainer.appendChild(productElement);
        });
        
        this.dimensionsList.appendChild(orderElement);
    }

    renderSingleProductDimensions(orderId, product) {
        const productElement = this.dimensionProductTemplate.content.cloneNode(true);
        
        // Wypełnij informacje o produkcie
        productElement.querySelector('.product-name').textContent = product.name;
        productElement.querySelector('.product-quantity span').textContent = product.quantity;
        productElement.querySelector('.missing-list').textContent = product.missing_dimensions.join(', ');
        
        // Ustaw obecne wartości wymiarów
        const currentDimensions = product.current_dimensions || {};
        const inputs = productElement.querySelectorAll('.dimension-input');

        const volumeInput = productElement.querySelector('.calculated-volume');
        // Ustaw data-attributes analogicznie do pozostałych:
        volumeInput.setAttribute('data-order-id', orderId);
        volumeInput.setAttribute('data-product-id', product.product_id);
        // Obsługa ręcznej zmiany objętości:
        volumeInput.addEventListener('input', () => {
            const manualValue = parseFloat(volumeInput.value);
            if (!isNaN(manualValue) && manualValue > 0) {
                // Nadpisz w tymczasowych poprawkach
                if (!this.dimensionFixes[orderId]) this.dimensionFixes[orderId] = {};
                if (!this.dimensionFixes[orderId][product.product_id]) this.dimensionFixes[orderId][product.product_id] = {};
                this.dimensionFixes[orderId][product.product_id]['volume_m3'] = manualValue;
            }
        });
        
        inputs.forEach(input => {
            const dimension = input.getAttribute('data-dimension');
            const currentValue = currentDimensions[dimension];
            
            if (currentValue) {
                input.value = currentValue;
            }
            
            // Dodaj data attributes dla identyfikacji
            input.setAttribute('data-order-id', orderId);
            input.setAttribute('data-product-id', product.product_id);
            
            // Obsługa zmiany wartości
            input.addEventListener('input', () => {
                this.handleDimensionChange(orderId, product.product_id, product.quantity);
            });
        });
        
        return productElement;
    }

    handleDimensionChange(orderId, productId, quantity) {
        const container = this.dimensionsList.querySelector(
            `.dimension-product-item input[data-order-id="${orderId}"][data-product-id="${productId}"]`
        ).closest('.dimension-product-item');
        const inputs = container.querySelectorAll('.dimension-input');
        const volumeInput = container.querySelector('.calculated-volume');

        const dims = {};
        let hasAll = true;
        inputs.forEach(input => {
            const key = input.getAttribute('data-dimension');
            const val = parseFloat(input.value);
            if (!isNaN(val) && val > 0) dims[key] = val;
            else hasAll = false;

            // Zapiszę w poprawkach wymiary
            if (!this.dimensionFixes[orderId]) this.dimensionFixes[orderId] = {};
            if (!this.dimensionFixes[orderId][productId]) this.dimensionFixes[orderId][productId] = {};
            this.dimensionFixes[orderId][productId][key] = val;
        });

        // Jeżeli wymiary zmienione, usuń ewentualne manualne nadpisanie objętości
        if (this.dimensionFixes[orderId] && this.dimensionFixes[orderId][productId]) {
            delete this.dimensionFixes[orderId][productId]['volume_m3'];
        }

        // Automatyczne obliczenie objętości
        if (hasAll && dims.length_cm && dims.width_cm && dims.thickness_mm) {
            const lengthM = dims.length_cm / 100;
            const widthM = dims.width_cm / 100;
            const thicknessM = dims.thickness_mm / 1000;
            const computed = lengthM * widthM * thicknessM * quantity;
            volumeInput.value = computed.toFixed(4);
        } else {
            volumeInput.value = '';
        }
    }

    async saveSelectedOrders() {
        console.log('[SyncManager] 💾 Zapisywanie zaznaczonych zamówień');
        try {
            // Pokaż globalny loading
            this.showGlobalLoading('Zapisywanie zamówień...');

            // POPRAWKA: Przygotuj order_ids zamiast całych obiektów
            const orderIds = Array.from(this.selectedOrderIds);

            console.log('[SyncManager] 📦 Zamówienia do zapisania:', orderIds.length);

            // POPRAWKA: Używaj tego samego endpointu co performSaveOrders()
            const response = await fetch('/reports/api/save-selected-orders-with-dimensions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    order_ids: orderIds,                    // tablica ID zamówień
                    dimension_fixes: this.dimensionFixes || {}   // poprawki wymiarów (może być puste)
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (result.success) {
                console.log('[SyncManager] ✅ Zamówienia zapisane pomyślnie');

                // Ukryj modal i odśwież tabelę
                this.hideAllModals();

                // Odśwież tabelę raportów jeśli istnieje
                if (window.reportsManager && typeof window.reportsManager.refreshTable === 'function') {
                    window.reportsManager.refreshTable();
                }

                // Pokaż komunikat sukcesu
                this.showSuccessMessage({
                    message: result.message || `Zapisano ${orderIds.length} zamówień`
                });
            } else {
                throw new Error(result.error || 'Błąd zapisu zamówień');
            }
        } catch (error) {
            console.error('[SyncManager] ❌ Błąd zapisywania:', error);
            this.showErrorMessage(`Błąd zapisu: ${error.message}`);
        } finally {
            this.hideGlobalLoading();
        }
    }

    hideAllModals() {
        if (this.daysModal) this.daysModal.style.display = 'none';
        if (this.ordersModal) this.ordersModal.style.display = 'none';
        if (this.dimensionsModal) this.dimensionsModal.style.display = 'none';
    }

    // Pomocnicza metoda dla zamówień bez problemów
    async saveSelectedOrdersWithoutIssues(selectedOrders) {
        // Implementacja zapisu bez poprawek wymiarów
        console.log('[SyncManager] ✅ Zapisywanie zamówień bez problemów z wymiarami');
        // Tu będzie logika zapisu do bazy...
    }

    async handleDimensionsBack() {
        console.log('[SyncManager] ⬅️ Powrót z modala wymiarów do listy zamówień');
        this.hideDimensionsModal();
        this.showOrdersModal();
    }

    async handleDimensionsSkip() {
        console.log('[SyncManager] ⏭️ Pomiń wymiary i zapisz zamówienia');
        
        if (!confirm('Czy na pewno chcesz pominąć uzupełnianie wymiarów? Produkty bez wymiarów nie będą miały obliczonej objętości (m³).')) {
            return;
        }
        
        const selectedOrdersList = Array.from(this.selectedOrderIds);
        this.hideDimensionsModal();
        await this.saveOrdersWithoutDimensions(selectedOrdersList);
    }

    async handleDimensionsSave() {
        console.log('[SyncManager] 💾 Zapisz zamówienia z uzupełnionymi wymiarami');
        
        const selectedOrdersList = Array.from(this.selectedOrderIds);
        this.hideDimensionsModal();
        await this.saveOrdersWithDimensions(selectedOrdersList, this.dimensionFixes);
    }

    async saveOrdersWithoutDimensions(orderIds) {
        console.log('[SyncManager] 💾 Zapisywanie zamówień bez poprawek wymiarów');
        await this.performSaveOrders(orderIds, {});
    }

    async saveOrdersWithDimensions(orderIds, dimensionFixes) {
        console.log('[SyncManager] 💾 Zapisywanie zamówień z poprawkami wymiarów:', dimensionFixes);
        await this.performSaveOrders(orderIds, dimensionFixes);
    }

    async performSaveOrders(orderIds, dimensionFixes = {}) {
        if (this.isProcessing) {
            console.warn('[SyncManager] ⚠️ Proces zapisywania już trwa');
            return;
        }

        this.isProcessing = true;
        this.showGlobalLoading('Zapisywanie zamówień...', 'Przetwarzanie wybranych zamówień');

        try {
            const requestData = {
                order_ids: orderIds,
                dimension_fixes: dimensionFixes
            };

            console.log('[SyncManager] 📤 Wysyłanie zamówień do zapisania:', requestData);

            const response = await fetch('/reports/api/save-selected-orders-with-dimensions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('[SyncManager] 📥 Wynik zapisywania:', result);

            if (result.success) {
                this.handleSaveSuccess(result);
            } else {
                throw new Error(result.error || 'Błąd zapisywania zamówień');
            }

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd zapisywania zamówień:', error);
            this.handleSaveError(error);
        } finally {
            this.isProcessing = false;
            this.hideGlobalLoading();
        }
    }

    handleSaveSuccess(result) {
        console.log('[SyncManager] ✅ Zamówienia zapisane pomyślnie');

        // Przygotuj wiadomość dla toast'a
        let message = '🎉 Synchronizacja zakończona pomyślnie!';

        // Dodaj szczegóły jeśli są dostępne
        const details = [];
        if (result.orders_added > 0) {
            details.push(`✅ Zapisano ${result.orders_added} produktów`);
        }
        if (result.orders_updated > 0) {
            details.push(`🔄 Zaktualizowano ${result.orders_updated} zamówień`);
        }
        if (result.orders_processed > 0) {
            details.push(`📊 Przetworzono ${result.orders_processed} zamówień`);
        }

        // Połącz wiadomość główną ze szczegółami
        if (details.length > 0) {
            message += ' ' + details.join(', ');
        }

        // Użyj toast zamiast alert
        this.showSuccessMessage({ message: message });

        // Zamknij wszystkie modale po krótkim opóźnieniu (żeby toast był widoczny)
        setTimeout(() => {
            this.resetState();
            this.hideDaysModal();
            this.hideOrdersModal();
            this.hideDimensionsModal();

            // Odśwież dane na stronie
            if (window.reportsManager && typeof window.reportsManager.refreshData === 'function') {
                window.reportsManager.refreshData();
            } else {
                window.location.reload();
            }
        }, 1000); // 1 sekunda żeby toast był widoczny
    }

    handleSaveError(error) {
        console.error('[SyncManager] ❌ Błąd zapisywania:', error);

        // Użyj toast zamiast alert dla błędów
        this.showErrorMessage(`Błąd podczas zapisywania zamówień: ${error.message}`);
    }

    // =====================================================
    // ZAPISYWANIE ZAMÓWIEŃ Z OBSŁUGĄ PROBLEMÓW WYMIARÓW
    // =====================================================

    async checkOrdersForVolumeProblems() {
        console.log('[SyncManager] 🔍 Sprawdzanie problemów z objętością');

        try {
            if (!this.fetchedOrders || this.fetchedOrders.length === 0) {
                console.log('[SyncManager] ⚠️ Brak pobranych zamówień do sprawdzenia');
                this.showErrorMessage('Nie pobrano zamówień do sprawdzenia problemów z objętością.');
                this.showOrdersModal();
                return;
            }

            const selectedOrders = this.fetchedOrders.filter(order => 
                this.selectedOrderIds.has(order.order_id.toString())
            );

            console.log(`[SyncManager] 📊 Sprawdzanie ${selectedOrders.length} zaznaczonych zamówień`);

            // DODAJ DEBUGGING - sprawdź co mają zamówienia
            selectedOrders.forEach(order => {
                console.log(`[DEBUG] Zamówienie ${order.order_id}:`, {
                    has_volume_issues: order.has_volume_issues,
                    products: order.products?.length || 0,
                    produkty_details: order.products?.map(p => ({
                        name: p.name,
                        analysis_type: p.volume_analysis?.analysis_type,
                        volume: p.volume_analysis?.volume,
                        has_dimension_issues: p.has_dimension_issues
                    }))
                });
            });

            const productsNeedingVolume = [];
            
            selectedOrders.forEach(order => {
                console.log(`[DEBUG] Sprawdzam zamówienie ${order.order_id}, has_volume_issues: ${order.has_volume_issues}`);
                
                if (order.products) {
                    order.products.forEach(product => {
                        const analysis = product.volume_analysis;
                        console.log(`[DEBUG] Produkt ${product.name}:`, {
                            analysis_type: analysis?.analysis_type,
                            volume: analysis?.volume,
                            will_include: analysis && (
                                analysis.analysis_type === 'manual_input_needed'
                            )
                        });

                        // NOWE: Pomiń usługi przy sprawdzaniu potrzeby modala objętości
                        if (analysis && analysis.analysis_type === 'service') {
                            console.log(`[SyncManager] 📋 Pominięto usługę: ${product.name}`);
                            return; // Pomiń usługi - nie dodawaj do productsNeedingVolume
                        }
                        
                        if (analysis && (
                            analysis.analysis_type === 'manual_input_needed' ||
                            analysis.analysis_type === 'volume_only'
                        )) {
                            productsNeedingVolume.push({
                                order_id: order.order_id,
                                product_id: product.id || product.product_id,
                                product_name: product.name,
                                quantity: product.quantity || 1,
                                analysis: product.volume_analysis,
                                order_info: {
                                    // POPRAWKA: Lepsze mapowanie danych klienta
                                    customer_name: order.customer_name || order.delivery_fullname || order.invoice_fullname || 'Nieznany klient',
                                    order_date: order.date_add || order.order_date,
                                    
                                    // DODAJ WSZYSTKIE 3 DATY:
                                    date_add: order.date_add,           // Data złożenia
                                    payment_date: order.payment_date,   // Data płatności  
                                    delivery_date: order.delivery_date, // Data dostawy
                                    
                                    // DODATKOWE INFORMACJE:
                                    order_status: order.order_status_name || order.current_status || 'Nieznany status',
                                    total_value: order.total_value || order.value_net || 0
                                }
                            });
                        }
                    });
                }
            });

            console.log(`[SyncManager] 📊 Produkty wymagające objętości: ${productsNeedingVolume.length}`);
            console.log('[DEBUG] Lista produktów:', productsNeedingVolume);

            if (productsNeedingVolume.length > 0) {
                console.log('[SyncManager] ✅ Pokazuję modal objętości');
                this.productsNeedingVolume = productsNeedingVolume;
                this.volumeManager.showModal(productsNeedingVolume);
            } else {
                console.log('[SyncManager] ✅ Brak problemów z objętością, przechodzę do zapisu');
                await this.saveOrdersDirectly(selectedOrders);
            }

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd sprawdzania problemów z objętością:', error);
            this.showErrorMessage('Wystąpił błąd podczas sprawdzania problemów z objętością. Odśwież stronę i spróbuj ponownie.');
            this.showOrdersModal();
        }
    }
    
    async handleOrdersSave() {
        console.log('[SyncManager] 💾 Obsługa zapisywania zamówień');

        if (this.selectedOrderIds.size === 0) {
            console.log('[SyncManager] ⚠️ Brak zaznaczonych zamówień');
            return;
        }

        // NOWA LOGIKA: Sprawdź problemy z objętością ZAMIAST wymiarów
        await this.checkOrdersForVolumeProblems();
    }

    proceedToDimensionsStep() {
        console.log('[SyncManager] 📐 Przejście do kroku wymiarów');

        // Tu będzie logika przejścia do kroku 3 (modal wymiarów)
        // Na razie placeholder
        this.showInfoToast('Przejście do uzupełnienia wymiarów - do implementacji w następnym kroku');
    }

    // NOWA metoda: pokazuje modal objętości
    async showVolumeModal(ordersData) {
        console.log('[SyncManager] 📏 Pokazywanie modala objętości z analizą', ordersData);

        // Przygotuj dane produktów wymagających objętości
        const productsNeedingVolume = [];

        ordersData.forEach(order => {
            if (order.products && Array.isArray(order.products)) {
                order.products.forEach(product => {
                    // Sprawdź czy produkt wymaga ręcznego wprowadzenia objętości
                    if (product.volume_analysis && 
                        (product.volume_analysis.analysis_type === 'manual_input_needed' || 
                        product.volume_analysis.analysis_type === 'volume_only')) {
                        
                        productsNeedingVolume.push({
                            order_id: order.order_id,
                            product_id: product.product_id || 'unknown',
                            product_name: product.name,
                            quantity: product.quantity,
                            analysis: product.volume_analysis,
                            order_info: {
                                customer_name: order.delivery_fullname || order.buyer_company || 'Nieznany klient',
                                date: order.date_add ? this.formatDate(new Date(order.date_add * 1000)) : 'Brak daty'
                            }
                        });
                    }
                });
            }
        });

        console.log(`[SyncManager] Produkty wymagające uzupełnienia objętości: ${productsNeedingVolume.length}`);

        if (productsNeedingVolume.length === 0) {
            // Brak produktów wymagających objętości - przejdź do zapisu
            this.saveSelectedOrders();
            return;
        }

        // Ukryj modal zamówień
        this.hideOrdersModal();

        // Pokaż modal objętości z przygotowanymi danymi
        if (window.volumeManager) {
            window.volumeManager.showModal(productsNeedingVolume);
        } else {
            console.error('[SyncManager] VolumeManager nie jest dostępny');
            alert('Błąd: Moduł zarządzania objętościami nie jest dostępny.');
        }
    }

    // NOWA metoda: pokazuje stan postępu zapisu
    showSaveProgress(message = 'Zapisywanie...') {
        const saveBtn = document.getElementById('ordersSave');
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" style="width: 1rem; height: 1rem;"></span>${message}`;
        }

        // Pokaż overlay ładowania jeśli istnieje
        if (this.globalLoading) {
            if (this.globalLoadingTitle) this.globalLoadingTitle.textContent = message;
            if (this.globalLoadingText) this.globalLoadingText.textContent = 'Proszę czekać...';
            this.globalLoading.style.display = 'flex';
        }
    }

    // NOWA metoda: ukrywa stan postępu zapisu
    hideSaveProgress() {
        const saveBtn = document.getElementById('ordersSave');
        if (saveBtn) {
            saveBtn.disabled = this.selectedOrderIds.size === 0;
            this.updateSaveButton(); // Przywróć oryginalny tekst
        }

        // Ukryj overlay ładowania
        if (this.globalLoading) {
            this.globalLoading.style.display = 'none';
        }
    }

    // NOWA metoda: pokazuje komunikat sukcesu
    showSuccessMessage(result) {
        const message = result.message || 'Zamówienia zostały pomyślnie zapisane';

        // Użyj toast jeśli dostępny, w przeciwnym razie alert
        if (window.showToast) {
            window.showToast(message, 'success');
        } else {
            alert(message);
        }

        console.log('[SyncManager] ✅ Sukces:', message);
    }

    // NOWA metoda: pokazuje komunikat błędu
    showErrorMessage(message) {
        // Użyj toast jeśli dostępny, w przeciwnym razie alert
        if (window.showToast) {
            window.showToast(message, 'error');
        } else {
            alert(message);
        }
        console.error('[SyncManager] ❌ Błąd:', message);
    }

    /**
     * NOWA: Pokazuje toast ostrzeżenia
     */
    showWarningToast(message) {
        if (window.showToast) {
            window.showToast(message, 'warning');
        } else {
            alert(message);
        }
        console.warn('[SyncManager] ⚠️ Ostrzeżenie:', message);
    }

    /**
     * NOWA: Pokazuje toast informacyjny
     */
    showInfoToast(message) {
        if (window.showToast) {
            window.showToast(message, 'info');
        } else {
            alert(message);
        }
        console.info('[SyncManager] ℹ️ Info:', message);
    }

    /**
     * NOWA: Modal potwierdzenia zastępujący confirm()
     */
    showConfirmDialog(message, title = 'Potwierdzenie') {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'sync-modal-overlay';
            modal.innerHTML = `
                <div class="sync-modal-content confirmation-modal">
                    <div class="sync-modal-header">
                        <h5 class="sync-modal-title">${title}</h5>
                        <button type="button" class="sync-modal-close" aria-label="Zamknij">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="sync-modal-body">
                        <p>${message}</p>
                    </div>
                    <div class="sync-modal-footer">
                        <button type="button" class="btn btn-secondary confirm-cancel">Anuluj</button>
                        <button type="button" class="btn btn-primary confirm-ok">OK</button>
                    </div>
                </div>
            `;

            const closeModal = (result) => {
                modal.remove();
                resolve(result);
            };

            modal.querySelector('.sync-modal-close').addEventListener('click', () => closeModal(false));
            modal.querySelector('.confirm-cancel').addEventListener('click', () => closeModal(false));
            modal.querySelector('.confirm-ok').addEventListener('click', () => closeModal(true));

            const handleKeydown = (e) => {
                if (e.key === 'Escape') {
                    closeModal(false);
                    document.removeEventListener('keydown', handleKeydown);
                }
            };
            document.addEventListener('keydown', handleKeydown);

            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal(false);
            });

            document.body.appendChild(modal);
            setTimeout(() => modal.querySelector('.confirm-ok').focus(), 100);
        });
    }

    /**
     * NOWA: Dodawanie stylów dla modala potwierdzenia
     */
    addConfirmationModalStyles() {
        if (document.getElementById('confirmation-modal-styles')) return;

        const styleSheet = document.createElement('style');
        styleSheet.id = 'confirmation-modal-styles';
        styleSheet.textContent = `
            .confirmation-modal { max-width: 500px; width: 90%; z-index: 9999; }
            .confirmation-modal .sync-modal-body {
                padding: 20px; font-size: 16px; line-height: 1.5; color: #555;
            }
            .confirmation-modal .sync-modal-footer {
                padding: 15px 20px; display: flex; gap: 10px; justify-content: flex-end;
                background: #f8f9fa; border-top: 1px solid #dee2e6;
            }
            .confirmation-modal .btn {
                padding: 8px 20px; border-radius: 6px; font-weight: 500;
                transition: all 0.2s ease;
            }
            .confirmation-modal .btn-secondary {
                background: #6c757d; border-color: #6c757d; color: white;
            }
            .confirmation-modal .btn-secondary:hover {
                background: #5a6268; border-color: #545b62;
            }
            .confirmation-modal .btn-primary {
                background: #007bff; border-color: #007bff; color: white;
            }
            .confirmation-modal .btn-primary:hover {
                background: #0069d9; border-color: #0062cc;
            }
        `;
        document.head.appendChild(styleSheet);
    }

    extractProductsNeedingVolume(selectedOrders) {
        const productsNeedingVolume = [];

        selectedOrders.forEach(order => {
            order.products.forEach((product, productIndex) => {
                if (product.needs_manual_volume) {
                    productsNeedingVolume.push({
                        order_id: order.order_id,
                        product_id: product.product_id || 'unknown',
                        order_product_id: product.order_product_id, // ✅ DODAJ order_product_id
                        product_index: productIndex, // ✅ DODAJ indeks produktu
                        product_name: product.name,
                        quantity: product.quantity || 1,
                        order_info: {
                            customer_name: order.customer_name,
                            date: order.date_created
                        },
                        analysis: product.volume_analysis
                    });
                }
            });
        });

        return productsNeedingVolume;
    }

    // NOWA metoda: pokazuje modal objętości
    async showVolumeModal(productsNeedingVolume) {
        console.log('[SyncManager] 📏 Pokazywanie modala objętości');

        // Ukryj modal zamówień
        this.hideOrdersModal();

        // Sprawdź dostępność VolumeManager
        if (!this.volumeManager) {
            console.error('[SyncManager] VolumeManager nie jest dostępny');
            alert('Błąd: moduł obsługi objętości nie jest dostępny. Odśwież stronę i spróbuj ponownie.');
            this.showOrdersModal();
            return;
        }

        // Zapisz produkty do późniejszego użycia
        this.productsNeedingVolume = productsNeedingVolume;

        // Pokaż modal objętości
        this.volumeManager.showModal(productsNeedingVolume);
    }

    // NOWA metoda: bezpośredni zapis zamówień (bez problemów z objętością)
    async saveOrdersDirectly(selectedOrders) {
        console.log('[SyncManager] 💾 Bezpośredni zapis zamówień z analizą objętości');

        try {
            this.showSaveProgress('Zapisywanie zamówień...');

            const orderIds = selectedOrders.map(order => order.order_id);

            // ✅ DODAJ DEBUGOWANIE DANYCH PRZED WYSŁANIEM
            console.log('[SyncManager] 🔍 Dane do wysłania:', {
                orderIds: orderIds,
                selectedOrders: selectedOrders.length,
                firstOrder: selectedOrders[0]
            });

            const response = await fetch('/reports/api/save-orders-with-volumes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    order_ids: orderIds,
                    volume_fixes: {}, // Pusty - system użyje automatycznej analizy
                    orders_data: selectedOrders  // ✅ DODAJ PEŁNE DANE ZAMÓWIEŃ!
                })
            });

            if (!response.ok) {
                const errorText = await response.text();
                console.error('[SyncManager] ❌ HTTP Error:', response.status, errorText);
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (result.success) {
                this.showSuccessMessage(result);
                this.hideOrdersModal();

                // ✅ POPRAWKA: Wymuś odświeżenie tabeli
                if (window.reportsManager && typeof window.reportsManager.refreshData === 'function') {
                    window.reportsManager.refreshData();
                } else {
                    setTimeout(() => window.location.reload(), 1000);
                }
            }

        } catch (error) {
            console.error('[SyncManager] Błąd bezpośredniego zapisu:', error);
            throw error;
        } finally {
            this.hideSaveProgress();
        }
    }

    // NOWA metoda: wyodrębnia produkty wymagające ręcznego wprowadzenia objętości
    extractProductsNeedingVolume(selectedOrders) {
        const productsNeedingVolume = [];

        selectedOrders.forEach(order => {
            order.products.forEach((product, productIndex) => {
                if (product.needs_manual_volume) {
                    productsNeedingVolume.push({
                        order_id: order.order_id,
                        product_id: product.product_id || 'unknown',
                        order_product_id: product.order_product_id, // ✅ DODAJ order_product_id
                        product_index: productIndex, // ✅ DODAJ indeks produktu
                        product_name: product.name,
                        quantity: product.quantity || 1,
                        order_info: {
                            customer_name: order.customer_name,
                            date: order.date_created
                        },
                        analysis: product.volume_analysis
                    });
                }
            });
        });

        return productsNeedingVolume;
    }

    getActuallySelectedOrderIds() {
        const selectedIds = [];
        const checkboxes = document.querySelectorAll('#ordersList .modal-bl-sync-checkbox:checked');

        checkboxes.forEach(checkbox => {
            const orderId = checkbox.getAttribute('data-order-id');
            if (orderId) {
                selectedIds.push(orderId);
            }
        });

        console.log('[SyncManager] 🔍 Rzeczywisty stan checkboxów:', selectedIds);
        return selectedIds;
    }

    showDimensionFixModal(ordersWithIssues, allSelectedOrders) {
        console.log('[SyncManager] 🔧 Tworzenie modala uzupełnienia wymiarów dla zamówień:', ordersWithIssues);
        
        this.hideOrdersModal();
        
        const issuesData = ordersWithIssues.map(orderId => {
            const issueInfo = this.ordersWithDimensionIssues.get(orderId);
            return {
                orderId: orderId,
                order: issueInfo.order,
                products: issueInfo.products_with_issues
            };
        });

        this.createDimensionFixModal(issuesData, allSelectedOrders);
    }

    createDimensionFixModal(issuesData, allSelectedOrders) {
        console.log('[SyncManager] 🏗️ Tworzenie modala uzupełnienia wymiarów');

        const existingModal = document.getElementById('dimensionFixModal');
        if (existingModal) {
            existingModal.remove();
        }

        const modal = document.createElement('div');
        modal.id = 'dimensionFixModal';
        modal.className = 'sync-modal show';
        
        let productsHtml = '';
        
        issuesData.forEach(issue => {
            const order = issue.order;
            
            productsHtml += `
                <div class="dimension-fix-order">
                    <div class="dimension-fix-order-header">
                        <h4>Zamówienie #${order.order_id}</h4>
                        <span class="order-customer">👤 ${order.customer_name}</span>
                    </div>
                    <div class="dimension-fix-products">
            `;
            
            issue.products.forEach(product => {
                productsHtml += `
                    <div class="dimension-fix-product" data-order-id="${order.order_id}" data-product-index="${product.index}">
                        <div class="product-info">
                            <strong>${product.index}. ${product.name}</strong>
                            <span class="product-quantity">Ilość: ${product.quantity} szt.</span>
                        </div>
                        
                        <!-- Opcjonalne pola wymiarów jeśli chcemy umożliwić ich wpisanie -->
                        <div class="optional-dimensions" style="margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 5px;">
                            <h6 style="margin: 0 0 10px 0; color: #6c757d;">Opcjonalnie - wpisz wymiary aby auto-obliczyć objętość:</h6>
                            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;">
                                <div>
                                    <label style="font-size: 12px;">Długość (cm):</label>
                                    <input type="number" step="0.1" class="dimension-input" 
                                        data-dimension="length_cm" 
                                        style="width: 100%; padding: 5px; border: 1px solid #ddd; border-radius: 3px;">
                                </div>
                                <div>
                                    <label style="font-size: 12px;">Szerokość (cm):</label>
                                    <input type="number" step="0.1" class="dimension-input" 
                                        data-dimension="width_cm"
                                        style="width: 100%; padding: 5px; border: 1px solid #ddd; border-radius: 3px;">
                                </div>
                                <div>
                                    <label style="font-size: 12px;">Grubość (cm):</label>
                                    <input type="number" step="0.1" class="dimension-input" 
                                        data-dimension="thickness_cm"
                                        style="width: 100%; padding: 5px; border: 1px solid #ddd; border-radius: 3px;">
                                </div>
                            </div>
                        </div>
                        
                        <div class="volume-input-group">
                            <label>Objętość (m³):</label>
                            <input type="number" 
                                step="0.0001" 
                                min="0" 
                                class="volume-input" 
                                data-order-id="${order.order_id}" 
                                data-product-index="${product.index}"
                                placeholder="np. 0.0640"
                                required>
                            <small class="volume-help">Wpisz objętość lub podaj wymiary powyżej</small>
                        </div>
                    </div>
                `;
            });
            
            productsHtml += `
                    </div>
                </div>
            `;
        });

        modal.innerHTML = `
            <div class="sync-modal-overlay">
                <div class="sync-modal-content sync-modal-large">
                    <div class="sync-modal-header">
                        <h3>Uzupełnij objętości produktów</h3>
                        <button class="sync-modal-close" id="dimensionFixClose">&times;</button>
                    </div>
                    
                    <div class="sync-modal-body">
                        <div class="dimension-fix-info">
                            <div class="info-icon">⚠️</div>
                            <div class="info-text">
                                <p><strong>Niektóre produkty nie mają wymiarów w nazwie.</strong></p>
                                <p>Uzupełnij objętość (m³) dla każdego produktu, aby system mógł poprawnie obliczyć statystyki.</p>
                            </div>
                        </div>
                        
                        <div class="dimension-fix-list">
                            ${productsHtml}
                        </div>
                    </div>
                    
                    <div class="sync-modal-footer">
                        <button id="dimensionFixBack" class="btn btn-secondary">Wstecz</button>
                        <button id="dimensionFixCancel" class="btn btn-secondary">Anuluj</button>
                        <button id="dimensionFixSave" class="btn btn-primary">Zapisz z uzupełnionymi objętościami</button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        this.setupDimensionFixModalEvents(modal, allSelectedOrders);
        
        console.log('[SyncManager] ✅ Modal uzupełnienia wymiarów utworzony');
    }

    // NOWA metoda: pokazuje informację o problemach z objętością
    showVolumeIssuesInfo(count) {
        const content = document.querySelector('.modal-bl-sync-content');
        const ordersListContainer = document.getElementById('ordersListContainer');

        if (!content || !ordersListContainer) return;

        // Usuń poprzednie powiadomienie jeśli istnieje
        const existingAlert = content.querySelector('.volume-issues-alert');
        if (existingAlert) {
            existingAlert.remove();
        }

        // Utwórz nowe powiadomienie
        const alert = document.createElement('div');
        alert.className = 'volume-issues-alert';
        alert.style.cssText = `
        padding: 8px 10px;
        background: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 8px;
        width: 100%;
    `;

        alert.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="font-size: 20px;">⚠️</div>
            <div>
                <strong style="color: #856404;">Uwaga:</strong> <span style="color: #856404;">${count} produktów wymaga uzupełnienia objętości.</span>
            </div>
        </div>
    `;

        // ZMIANA: Wstaw PO ordersListContainer, ale przed ordersList
        const ordersList = document.getElementById('ordersList');
        if (ordersList) {
            content.insertBefore(alert, ordersList);
        } else {
            // Fallback - dodaj na koniec content
            content.appendChild(alert);
        }
    }

    setupDimensionFixModalEvents(modal, allSelectedOrders) {
        console.log('[SyncManager] 🔗 Ustawianie event listenerów dla modala wymiarów');

        const closeBtn = modal.querySelector('#dimensionFixClose');
        const cancelBtn = modal.querySelector('#dimensionFixCancel');
        const backBtn = modal.querySelector('#dimensionFixBack');
        const saveBtn = modal.querySelector('#dimensionFixSave');

        const closeModal = () => {
            modal.remove();
            this.showOrdersModal();
        };

        closeBtn?.addEventListener('click', () => this.reset());
        cancelBtn?.addEventListener('click', () => this.reset());
        backBtn?.addEventListener('click', closeModal);

        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                this.reset();
                document.removeEventListener('keydown', handleKeydown);
            }
        };
        document.addEventListener('keydown', handleKeydown);

        modal.addEventListener('click', (e) => {
            if (e.target === modal || e.target.classList.contains('sync-modal-overlay')) {
                this.reset();
            }
        });

        saveBtn?.addEventListener('click', async () => {
            console.log('[SyncManager] 💾 Zapisywanie z uzupełnionymi objętościami');
            
            const volumeInputs = modal.querySelectorAll('.volume-input');
            const volumeOverrides = {};
            let allValid = true;

            volumeInputs.forEach(input => {
                const orderId = input.getAttribute('data-order-id');
                const productIndex = input.getAttribute('data-product-index');
                const volume = parseFloat(input.value);

                if (!input.value || isNaN(volume) || volume < 0) {
                    input.classList.add('error');
                    allValid = false;
                } else {
                    input.classList.remove('error');
                    
                    if (!volumeOverrides[orderId]) {
                        volumeOverrides[orderId] = {};
                    }
                    volumeOverrides[orderId][productIndex] = volume;
                }
            });

            if (!allValid) {
                this.showError('Wszystkie pola objętości muszą być wypełnione poprawnymi wartościami');
                return;
            }

            console.log('[SyncManager] 📊 Zebrane objętości:', volumeOverrides);

            modal.remove();
            document.removeEventListener('keydown', handleKeydown);
            
            await this.performOrdersSave(allSelectedOrders, volumeOverrides);
        });

        const volumeInputs = modal.querySelectorAll('.volume-input');
        volumeInputs.forEach(input => {
            input.addEventListener('input', () => {
                const value = parseFloat(input.value);
                if (input.value && (!isNaN(value) && value >= 0)) {
                    input.classList.remove('error');
                } else if (input.value) {
                    input.classList.add('error');
                }
            });
        });
        this.setupVolumeCalculation(modal);
        console.log('[SyncManager] 🔧 Event listenery dla modala wymiarów ustawione');
    }

    setupVolumeCalculation(modal) {
        console.log('[SyncManager] 🔧 Ustawianie automatycznego obliczania objętości');

        // Znajdź wszystkie grupy produktów z inputami wymiarów i objętości
        const productGroups = modal.querySelectorAll('.dimension-fix-product');
        
        productGroups.forEach(productGroup => {
            const orderId = productGroup.getAttribute('data-order-id');
            const productIndex = productGroup.getAttribute('data-product-index');
            
            // Sprawdź czy istnieją pola wymiarów (w niektórych modalach mogą być)
            const lengthInput = productGroup.querySelector('.dimension-input[data-dimension="length_cm"]');
            const widthInput = productGroup.querySelector('.dimension-input[data-dimension="width_cm"]');
            const thicknessInput = productGroup.querySelector('.dimension-input[data-dimension="thickness_cm"]');
            const volumeInput = productGroup.querySelector('.volume-input');
            
            if (!volumeInput) return;
            
            // Funkcja obliczająca objętość z wymiarów
            const calculateAndUpdateVolume = () => {
                if (lengthInput && widthInput && thicknessInput && volumeInput) {
                    const length = parseFloat(lengthInput.value) || 0;
                    const width = parseFloat(widthInput.value) || 0;
                    const thickness = parseFloat(thicknessInput.value) || 0;
                    
                    if (length > 0 && width > 0 && thickness > 0) {
                        // Konwersja z cm na m³
                        const volume = (length / 100) * (width / 100) * (thickness / 100);
                        
                        // Znajdź ilość produktu
                        const quantityElement = productGroup.querySelector('.product-quantity');
                        let quantity = 1;
                        if (quantityElement) {
                            const quantityMatch = quantityElement.textContent.match(/(\d+)/);
                            if (quantityMatch) {
                                quantity = parseInt(quantityMatch[1]);
                            }
                        }
                        
                        const totalVolume = volume * quantity;
                        volumeInput.value = totalVolume.toFixed(4);
                        
                        // Dodaj wizualną informację o automatycznym obliczeniu
                        volumeInput.style.backgroundColor = '#e8f5e8';
                        volumeInput.title = `Automatycznie obliczone z wymiarów: ${length}×${width}×${thickness} cm × ${quantity} szt.`;
                    }
                }
            };
            
            // Dodaj event listenery do pól wymiarów
            if (lengthInput && widthInput && thicknessInput) {
                [lengthInput, widthInput, thicknessInput].forEach(input => {
                    input.addEventListener('input', calculateAndUpdateVolume);
                    input.addEventListener('change', calculateAndUpdateVolume);
                });
            }
            
            // Dodaj event listener do pola objętości - usuń auto-obliczenie gdy użytkownik wpisuje ręcznie
            volumeInput.addEventListener('input', () => {
                volumeInput.style.backgroundColor = '';
                volumeInput.title = 'Wartość wpisana ręcznie';
            });
        });
    }

    async performOrdersSave(selectedOrdersList, volumeOverrides = null) {
        console.log('[SyncManager] 💾 Rozpoczęcie faktycznego zapisywania zamówień:', selectedOrdersList);

        this.isProcessing = true;
        
        this.showGlobalLoading('Zapisywanie zamówień...', 'Proszę czekać, trwa zapisywanie wybranych zamówień do bazy danych.');

        try {
            const requestData = {
                order_ids: selectedOrdersList,
                date_from: this.dateFrom,
                date_to: this.dateTo,
                volume_overrides: volumeOverrides || {}
            };

            console.log('[SyncManager] 📤 Wysyłanie zamówień do zapisania:', requestData);

            const response = await fetch('/reports/api/save-selected-orders', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('[SyncManager] 📥 Wynik zapisywania:', result);

            if (result.success) {
                this.showGlobalLoading('Sukces!', `Pomyślnie zapisano ${result.orders_saved || selectedOrdersList.length} zamówień do bazy danych.`);
                
                setTimeout(() => {
                    this.hideGlobalLoading();
                    this.resetState();
                    
                    if (window.reportsManager) {
                        window.reportsManager.refreshData();
                    }
                }, 3000);

            } else {
                throw new Error(result.error || 'Błąd zapisywania zamówień');
            }

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd zapisywania zamówień:', error);
            this.hideGlobalLoading();
            this.showError(`Błąd zapisywania zamówień: ${error.message}`);
        } finally {
            this.isProcessing = false;
        }
    }

    // =====================================================
    // GLOBALNY LOADING
    // =====================================================

    showGlobalLoading(text = 'Przetwarzanie...') {
        if (this.globalLoading) {
            this.globalLoading.style.display = 'flex';
        }
        if (this.globalLoadingText) {
            this.globalLoadingText.textContent = text;
        }
    }

    hideGlobalLoading() {
        if (this.globalLoading) {
            this.globalLoading.style.display = 'none';
        }
    }

    // =====================================================
    // FUNKCJE POMOCNICZE
    // =====================================================

    resetState() {
        console.log('[SyncManager] 🔄 Resetowanie stanu aplikacji');

        this.selectedDays = null;
        this.dateFrom = null;
        this.dateTo = null;
        this.fetchedOrders = [];
        this.selectedOrderIds.clear();
        this.ordersWithDimensionIssues.clear();
        this.isProcessing = false;

        if (this.daysSelect) this.daysSelect.value = '';
        if (this.daysConfirmBtn) this.daysConfirmBtn.disabled = true;
        this.hideDatePreview();
        this.ordersWithDimensionIssues.clear();
        this.dimensionFixes = {};

        // Wyczyszczenie stanów i widoków modala zamówień
        if (this.ordersList) this.ordersList.innerHTML = '';
        if (this.ordersCount) this.ordersCount.textContent = '';
        if (this.ordersListContainer) this.ordersListContainer.style.display = 'none';
        if (this.ordersLoadingState) this.ordersLoadingState.style.display = 'none';
        if (this.ordersEmptyState) this.ordersEmptyState.style.display = 'none';
        if (this.ordersErrorState) this.ordersErrorState.style.display = 'none';

        // Wyczyść listę wymiarów jeśli była używana
        if (this.dimensionsList) this.dimensionsList.innerHTML = '';
    }

    formatDate(date) {
        return date.toISOString().split('T')[0];
    }

    formatDateTime(dateString) {
        if (!dateString) return 'Brak daty';
        
        try {
            let date;
            
            if (typeof dateString === 'number') {
                console.log(`[SyncManager] 📅 Formatowanie timestamp: ${dateString}`);
                date = new Date(dateString * 1000);
            } else if (typeof dateString === 'string') {
                if (dateString.match(/^\d+$/)) {
                    console.log(`[SyncManager] 📅 Formatowanie timestamp jako string: ${dateString}`);
                    date = new Date(parseInt(dateString) * 1000);
                } else {
                    console.log(`[SyncManager] 📅 Formatowanie string daty: ${dateString}`);
                    date = new Date(dateString);
                }
            } else {
                date = new Date(dateString);
            }

            if (isNaN(date.getTime())) {
                console.warn(`[SyncManager] ⚠️ Nieprawidłowa data: ${dateString}`);
                return `Błędna data: ${dateString}`;
            }

            console.log(`[SyncManager] 🔍 Debug formatowania daty:`, {
                input: dateString,
                inputType: typeof dateString,
                parsedDate: date.toISOString(),
                year: date.getFullYear()
            });

            if (date.getFullYear() < 2000) {
                console.warn(`[SyncManager] ⚠️ Podejrzany rok w dacie: ${date.getFullYear()}`);
                if (typeof dateString === 'number' && dateString > 1000000000000) {
                    date = new Date(dateString);
                    console.log(`[SyncManager] 🔧 Próba naprawy - używam timestamp w ms: ${date.toISOString()}`);
                }
            }

            const formattedDate = date.toLocaleDateString('pl-PL') + ' ' + date.toLocaleTimeString('pl-PL', { 
                hour: '2-digit', 
                minute: '2-digit' 
            });

            console.log(`[SyncManager] ✅ Sformatowana data: ${formattedDate}`);
            return formattedDate;
            
        } catch (error) {
            console.error('[SyncManager] ❌ Błąd formatowania daty:', dateString, error);
            return `Błąd: ${dateString}`;
        }
    }

    formatMoney(amount) {
        if (amount === null || amount === undefined || isNaN(amount)) {
            return '0,00 zł';
        }
        
        return parseFloat(amount).toLocaleString('pl-PL', {
            style: 'currency',
            currency: 'PLN',
            minimumFractionDigits: 2
        });
    }

    getStatusColor(status) {
        const statusColors = {
            'new': '#28a745',
            'processing': '#ffc107',
            'shipped': '#17a2b8',
            'delivered': '#6f42c1',
            'cancelled': '#dc3545',
            'paid': '#20c997',
            'unpaid': '#fd7e14'
        };

        return statusColors[status?.toLowerCase()] || '#6c757d';
    }

    showError(message) {
        console.error('[SyncManager] 💥 Wyświetlanie błędu:', message);
        
        alert(message);
        
        if (window.reportsManager && window.reportsManager.showError) {
            window.reportsManager.showError(message);
        }
    }

    // =====================================================
    // PUBLICZNE API DLA KOMPATYBILNOŚCI
    // =====================================================

    isInProgress() {
        return this.isProcessing;
    }

    reset() {
        console.log('[SyncManager] 🔄 Manualny reset przez publiczne API');
        this.resetState();
        this.hideDaysModal();
        this.hideOrdersModal();
        this.hideGlobalLoading();
        
        // Usuń modal wymiarów jeśli istnieje
        const dimensionModal = document.getElementById('dimensionFixModal');
        if (dimensionModal) {
            dimensionModal.remove();
        }
    }

    debugSelectionState() {
        const checkboxes = document.querySelectorAll('#ordersList .order-select');
        const checkedBoxes = document.querySelectorAll('#ordersList .order-select:checked');

        console.log('[SyncManager] 🐛 DEBUG - Stan zaznaczenia:', {
            totalCheckboxes: checkboxes.length,
            checkedCheckboxes: checkedBoxes.length,
            selectedOrderIds: Array.from(this.selectedOrderIds),
            selectedOrderIdsSize: this.selectedOrderIds.size,
            actuallyChecked: Array.from(checkedBoxes).map(cb => cb.getAttribute('data-order-id'))
        });

        // Sprawdź czy są rozbieżności
        const actuallyChecked = Array.from(checkedBoxes).map(cb => cb.getAttribute('data-order-id'));
        const selectedArray = Array.from(this.selectedOrderIds);

        const mismatch = selectedArray.length !== actuallyChecked.length ||
            !selectedArray.every(id => actuallyChecked.includes(id));

        if (mismatch) {
            console.warn('[SyncManager] ⚠️ ROZBIEŻNOŚĆ w stanie zaznaczenia!', {
                selectedOrderIds: selectedArray,
                actuallyChecked: actuallyChecked
            });
        }

        return {
            mismatch: mismatch,
            selectedOrderIds: selectedArray,
            actuallyChecked: actuallyChecked
        };
    }

    // NOWA METODA: Pokazywanie progressive loading
    showProgressiveLoading(stepText = 'Łączenie z Baselinker...', stepNumber = 1) {
        console.log(`[SyncManager] 🔄 Progressive loading: ${stepText} (krok ${stepNumber})`);

        const loadingOverlay = document.getElementById('modalBlSyncProgressiveLoading');
        const loadingText = document.getElementById('modalBlSyncLoadingText');
        const stepLabel = document.getElementById('modalBlSyncStepLabel');

        if (loadingOverlay) {
            loadingOverlay.style.display = 'flex';
        }

        if (loadingText) {
            loadingText.textContent = stepText;
        }

        if (stepLabel) {
            stepLabel.textContent = `Krok ${stepNumber} z 4`;
        }

        // Aktualizuj progress dots
        this.updateProgressDots(stepNumber);
    }

    // NOWA METODA: Aktualizacja progressive loading
    updateProgressiveLoading(stepText, stepNumber) {
        console.log(`[SyncManager] 🔄 Aktualizacja loading: ${stepText} (krok ${stepNumber})`);

        const loadingText = document.getElementById('modalBlSyncLoadingText');
        const stepLabel = document.getElementById('modalBlSyncStepLabel');

        if (loadingText) {
            // Smooth transition tekstu
            loadingText.style.opacity = '0.5';
            setTimeout(() => {
                loadingText.textContent = stepText;
                loadingText.style.opacity = '1';
            }, 150);
        }

        if (stepLabel) {
            stepLabel.textContent = `Krok ${stepNumber} z 4`;
        }

        // Aktualizuj progress dots
        this.updateProgressDots(stepNumber);
    }

    // NOWA METODA: Aktualizacja progress dots
    updateProgressDots(currentStep) {
        const dots = document.querySelectorAll('#modalBlSyncProgressDots .modal-bl-sync-progress-dot');

        dots.forEach((dot, index) => {
            const stepNumber = index + 1;

            // Usuń wszystkie klasy
            dot.classList.remove('active', 'completed');

            if (stepNumber < currentStep) {
                // Ukończone kroki
                dot.classList.add('completed');
            } else if (stepNumber === currentStep) {
                // Aktualny krok
                dot.classList.add('active');
            }
            // Pozostałe pozostają w domyślnym stanie (szare)
        });
    }

    // NOWA METODA: Ukrywanie progressive loading
    hideProgressiveLoading() {
        console.log('[SyncManager] ✅ Ukrywanie progressive loading');

        const loadingOverlay = document.getElementById('modalBlSyncProgressiveLoading');

        if (loadingOverlay) {
            // Płynne zniknięcie
            loadingOverlay.style.opacity = '0';
            setTimeout(() => {
                loadingOverlay.style.display = 'none';
                loadingOverlay.style.opacity = '1'; // Reset dla następnego użycia
            }, 300);
        }
    }

    // ============ NOWE METODY DO OBSŁUGI OBJĘTOŚCI ============

    async loadDatabaseOrders() {
        console.log('[SyncManager] 🔄 Odświeżanie listy zamówień z bazy danych');
        try {
            await this.fetchOrders();
            if (window.reportsManager && typeof window.reportsManager.refreshData === 'function') {
                window.reportsManager.refreshData();
            }
        } catch (error) {
            console.error('[SyncManager] ❌ Błąd odświeżania zamówień:', error);
            this.showNotification(`❌ Błąd odświeżania: ${error.message}`, 'error');
        }
    }

    updateBulkActionsVisibility() {
        if (typeof this.updateOrdersSaveButton === 'function') {
            this.updateOrdersSaveButton();
        }
    }

    updateSelectedOrdersDisplay() {
        if (!this.ordersList) return;
        const checkboxes = this.ordersList.querySelectorAll('.modal-bl-sync-checkbox');
        checkboxes.forEach(checkbox => {
            const id = String(checkbox.getAttribute('data-order-id'));
            checkbox.checked = this.selectedOrderIds.has(id);
        });
        if (typeof this.updateOrdersCount === 'function') {
            this.updateOrdersCount();
        }
    }

    saveOrdersWithVolumes(volumeData) {
        console.log('[SyncManager] 📥 Zapisywanie zamówień z objętościami');

        try {
            this.showSaveProgress('Zapisywanie zamówień z objętościami...');

            // ✅ POPRAWKA 1: Dodaj informacje o product_index dla każdego produktu w selectedOrdersData
            const selectedOrderIdsAsNumbers = Array.from(this.selectedOrderIds).map(id => parseInt(id));
            console.log('[SyncManager] 🔍 DEBUGGING IDs CONVERSION:');
            console.log('selectedOrderIds (original):', Array.from(this.selectedOrderIds));
            console.log('selectedOrderIdsAsNumbers:', selectedOrderIdsAsNumbers);

            const selectedOrdersData = this.fetchedOrders
                .filter(order => {
                    const orderIdAsNumber = parseInt(order.order_id);
                    const isSelected = selectedOrderIdsAsNumbers.includes(orderIdAsNumber);
                    console.log(`Order ${order.order_id} (${typeof order.order_id}) -> ${orderIdAsNumber} (${typeof orderIdAsNumber}) - Selected: ${isSelected}`);
                    return isSelected;
                })
                .map(order => {
                    return {
                        ...order,
                        products: order.products.map((product, productIndex) => ({
                            ...product,
                            product_index: productIndex  // ✅ DODAJ INDEKS PRODUKTU
                        }))
                    };
                });

            // ✅ DEBUGOWANIE PRZED WYSŁANIEM
            console.log('[SyncManager] 🔍 DEBUGGING VOLUME DATA:');
            console.log('1. Otrzymane volumeData:', volumeData);
            console.log('2. Klucze w volumeData:', Object.keys(volumeData));
            console.log('3. Przykładowa wartość volumeData:', Object.values(volumeData)[0]);

            console.log('[SyncManager] 🔍 DEBUGGING SELECTED ORDERS DATA:');
            console.log('4. selectedOrdersData length:', selectedOrdersData.length);
            console.log('5. selectedOrdersData:', selectedOrdersData);

            if (selectedOrdersData.length === 0) {
                console.error('[SyncManager] ❌ BRAK selectedOrdersData! Sprawdzamy fetchedOrders...');
                console.log('fetchedOrders:', this.fetchedOrders);
                console.log('selectedOrderIds:', Array.from(this.selectedOrderIds));
                throw new Error('Brak danych wybranych zamówień. Problem z filtrowaniem zamówień.');
            }

            // ✅ POPRAWKA 2: Debuguj strukturę produktów w selectedOrdersData
            selectedOrdersData.forEach((order, orderIndex) => {
                console.log(`[DEBUG] Zamówienie ${order.order_id} (${orderIndex}):`);
                if (order.products && Array.isArray(order.products)) {
                    order.products.forEach((product, productIndex) => {
                        // ✅ UŻYJ JEDNOLITEJ FUNKCJI generateProductKey
                        const expectedKey = generateProductKey(order.order_id, product, productIndex);
                        const hasVolumeData = volumeData.hasOwnProperty(expectedKey);
                        console.log(`  - Produkt ${productIndex}: ${product.name}`);
                        console.log(`    product_id: ${product.product_id || 'unknown'}`);
                        console.log(`    order_product_id: ${product.order_product_id || 'BRAK'}`);
                        console.log(`    product_index: ${product.product_index}`);  // ✅ NOWE POLE
                        console.log(`    expected key: ${expectedKey}`);
                        console.log(`    has volume data: ${hasVolumeData}`);
                        if (hasVolumeData) {
                            console.log(`    volume data:`, volumeData[expectedKey]);
                        }
                    });
                }
            });

            // ✅ POPRAWKA 3: Sprawdź zgodność kluczy
            const volumeKeys = Object.keys(volumeData);
            const expectedKeys = [];
            selectedOrdersData.forEach(order => {
                if (order.products && Array.isArray(order.products)) {
                    order.products.forEach((product, productIndex) => {
                        expectedKeys.push(generateProductKey(order.order_id, product, productIndex));
                    });
                }
            });

            console.log('[SyncManager] 🔍 PORÓWNANIE KLUCZY:');
            console.log('Klucze z volumeData:', volumeKeys);
            console.log('Oczekiwane klucze z produktów:', expectedKeys);
            console.log('Zgodność kluczy:', volumeKeys.every(key => expectedKeys.includes(key)));

            // ✅ POPRAWKA 4: Waliduj czy mamy zgodność
            const hasMatchingKeys = volumeKeys.some(key => expectedKeys.includes(key));
            if (!hasMatchingKeys && volumeKeys.length > 0) {
                console.error('[SyncManager] ❌ BRAK ZGODNOŚCI KLUCZY!');
                console.error('Volume keys nie pasują do expected keys. Sprawdź generateProductKey.');
                throw new Error('Brak zgodności kluczy między danymi objętości a produktami.');
            }

            const payload = {
                order_ids: selectedOrderIdsAsNumbers,
                orders_data: selectedOrdersData,
                volume_fixes: volumeData
            };

            console.log('[SyncManager] 📤 Wysyłanie żądania zapisania zamówień:', payload);

            fetch('/reports/api/save-orders-with-volumes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload)
            })
                .then(response => response.json())
                .then(data => {
                    console.log('[SyncManager] 📥 Odpowiedź z serwera:', data);

                    if (data.success) {
                        window.showToast('✅ Zamówienia zapisane pomyślnie!', 'success');
                        this.hideSaveProgress();

                        // Odśwież listę zamówień z bazy danych
                        this.loadDatabaseOrders();

                        // ✅ POPRAWKA 5: Wyczyść zaznaczenie zamówień
                        this.selectedOrderIds.clear();
                        this.updateBulkActionsVisibility();

                        // ✅ POPRAWKA 6: Odśwież widok tabeli
                        this.updateSelectedOrdersDisplay();

                    } else {
                        throw new Error(data.error || 'Nieznany błąd podczas zapisywania');
                    }
                })
                .catch(error => {
                    console.error('[SyncManager] ❌ Błąd zapisywania zamówień:', error);
                    window.showToast(`❌ Błąd zapisywania: ${error.message}`, 'error');
                    this.hideSaveProgress();
                });

        } catch (error) {
            console.error('[SyncManager] ❌ Błąd przygotowania danych:', error);
            window.showToast(`❌ Błąd przygotowania danych: ${error.message}`, 'error');
            this.hideSaveProgress();
        }
    }

    convertVolumeDataToFixes(volumeData) {
        const fixes = {};
        
        Object.entries(volumeData).forEach(([productKey, data]) => {
            // productKey format: "order_id_product_id"
            fixes[productKey] = {
                volume: parseFloat(data.volume) || 0,
                wood_species: data.wood_species || null,
                technology: data.technology || null,
                wood_class: data.wood_class || null
            };
        });
        
        return fixes;
    }

    showSyncSuccess(result) {
        const loadingOverlay = document.getElementById('syncLoadingOverlay');
        const loadingText = document.getElementById('syncLoadingText');

        if (loadingText) {
            loadingText.innerHTML = `
                <div style="text-align: center;">
                    <div style="font-size: 24px; margin-bottom: 10px;">✅</div>
                    <div style="font-weight: bold; margin-bottom: 5px;">Synchronizacja zakończona!</div>
                    <div>Zapisano: ${result.orders_added || 0} zamówień</div>
                    ${result.orders_updated ? `<div>Zaktualizowano: ${result.orders_updated} zamówień</div>` : ''}
                    <div style="margin-top: 10px; font-size: 12px; opacity: 0.7;">
                        Zamykanie automatyczne za 3 sekundy...
                    </div>
                </div>
            `;
        }

        // Automatyczne zamknięcie po 3 sekundach
        setTimeout(() => {
            if (loadingOverlay) {
                loadingOverlay.classList.add('hidden');
            }
            this.clearSelectedOrders();
        }, 3000);
    }

    // *** NOWA FUNKCJA: Pokazywanie komunikatu z API ***
    showApiMessage(message, type = 'info') {
        console.log(`[SyncManager] 📢 Pokazywanie komunikatu API: ${message}`);

        // Użyj systemu toastów jeśli dostępny
        if (window.showToast) {
            window.showToast(message, type, 8000); // 8 sekund dla dłuższych komunikatów
            return;
        }

        // Fallback - użyj systemu komunikatów reports managera jeśli dostępny
        if (window.reportsManager && typeof window.reportsManager.showMessage === 'function') {
            window.reportsManager.showMessage(message, type);
            return;
        }

        // Ostateczny fallback - alert
        alert(message);
    }

    updateSyncStatus() {
        // Odśwież informacje o nowych zamówieniach
        this.fetchNewOrdersInfo();
        
        // Odśwież ostatnią synchronizację
        if (window.reportsConfig) {
            window.reportsConfig.lastSync = new Date().toISOString();
        }
    }

    clearSelectedOrders() {
        this.selectedOrderIds = new Set();
        
        // Wyczyść checkboxy w modalu zamówień jeśli jest otwarty
        const checkboxes = document.querySelectorAll('.order-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });
        
        // Aktualizuj licznik wybranych
        this.updateSelectedCount();
    }

    formatDate(dateString) {
        if (!dateString) return 'Brak daty';
        
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('pl-PL', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit'
            });
        } catch (error) {
            console.warn('[SyncManager] Błąd formatowania daty:', dateString);
            return 'Nieprawidłowa data';
        }
    }

}

// =====================================================
// INICJALIZACJA GLOBALNEGO OBIEKTU
// =====================================================

// Aktualizacja inicializacji - sprawdź czy VolumeManager jest załadowany
document.addEventListener('DOMContentLoaded', function () {
    if (window.syncManager) return;
    // Poczekaj na załadowanie wszystkich zależności
    const initSyncManager = () => {
        if (window.volumeManager || document.getElementById('volumeModal')) {
            window.syncManager = new SyncManager();
            window.syncManager.init();
            console.log('[SyncManager] Inicjalizacja zakończona z obsługą objętości');
        } else {
            setTimeout(initSyncManager, 100);
        }
    };

    initSyncManager();

    // Inicjalizuj po załadowaniu DOM
    setTimeout(() => {
        this.volumeManager = window.volumeManager;
        if (this.volumeManager) {
            console.log('[SyncManager] VolumeManager połączony');
        }
    }, 100);
});

console.log('[SyncManager] 🌟 Kompletny nowy SyncManager z obsługą wymiarów załadowany - gotowy do użycia');