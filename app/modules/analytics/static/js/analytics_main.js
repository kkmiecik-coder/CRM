// modules/analytics/static/js/analytics_main.js

/**
 * ANALYTICS MAIN - Główny plik zarządzający systemem analytics
 * Obsługuje: taby, loading, inicjalizację, komunikację między modułami
 */

class AnalyticsManager {
    constructor() {
        this.currentTab = 'sales-analytics'; // ZMIANA: sales-analytics jako domyślna
        this.loadedTabs = new Set(['sales-analytics']); // ZMIANA: sales zamiast public-calc
        this.isLoading = false;

        this.init();
    }

    init() {
        console.log('[AnalyticsManager] Inicjalizacja...');

        this.setupTabSystem();
        this.setupExportButtons();
        this.setupEventListeners();

        // Załaduj dane dla aktywnej zakładki
        this.loadTabData(this.currentTab);

        console.log('[AnalyticsManager] Gotowe!');
    }

    /**
     * Konfiguracja systemu tabów
     */
    setupTabSystem() {
        const tabs = document.querySelectorAll('.tab');
        const tabContents = document.querySelectorAll('.tab-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                const targetTab = tab.getAttribute('data-tab');
                this.switchTab(targetTab);
            });
        });

        console.log('[AnalyticsManager] System tabów skonfigurowany');
    }

    /**
     * Przełączanie zakładek
     */
    switchTab(tabId) {
        if (this.isLoading) {
            console.log('[AnalyticsManager] Ładowanie w toku, ignoruję przełączenie');
            return;
        }

        console.log(`[AnalyticsManager] Przełączanie na zakładkę: ${tabId}`);

        // Update UI
        this.updateTabUI(tabId);

        // Załaduj dane jeśli potrzeba
        if (!this.loadedTabs.has(tabId)) {
            this.loadTabData(tabId);
        }

        this.currentTab = tabId;
    }

    /**
     * Aktualizacja UI tabów
     */
    updateTabUI(activeTabId) {
        // Zaktualizuj taby
        document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.remove('active');
            if (tab.getAttribute('data-tab') === activeTabId) {
                tab.classList.add('active');
            }
        });

        // Zaktualizuj content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
            if (content.id === activeTabId) {
                content.classList.add('active');
            }
        });
    }

    /**
     * Ładowanie danych dla zakładki
     */
    async loadTabData(tabId) {
        console.log(`[AnalyticsManager] Ładowanie danych dla: ${tabId}`);

        try {
            this.showLoading();

            switch (tabId) {
                case 'sales-analytics':
                    if (window.SalesAnalytics) {
                        await window.SalesAnalytics.loadData();
                    }
                    break;

                case 'team-analytics':
                    if (window.TeamAnalytics) {
                        await window.TeamAnalytics.loadData();
                    }
                    break;

                case 'clients-analytics':
                    if (window.ClientsAnalytics) {
                        await window.ClientsAnalytics.loadData();
                    }
                    break;

                case 'baselinker-analytics':
                    if (window.BaselinkerAnalytics) {
                        await window.BaselinkerAnalytics.loadData();
                    }
                    break;

                case 'public-calc':
                    // public-calc ładuje dane automatycznie przez public_analytics.js
                    break;

                default:
                    console.warn(`[AnalyticsManager] Nieznana zakładka: ${tabId}`);
            }

            this.loadedTabs.add(tabId);
            console.log(`[AnalyticsManager] Dane załadowane dla: ${tabId}`);

        } catch (error) {
            console.error(`[AnalyticsManager] Błąd ładowania ${tabId}:`, error);
            this.showError(`Błąd ładowania danych dla zakładki ${tabId}`);
        } finally {
            this.hideLoading();
        }
    }

    /**
     * Konfiguracja przycisków exportu
     */
    setupExportButtons() {
        document.querySelectorAll('.export-btn').forEach(button => {
            button.addEventListener('click', (e) => {
                const type = button.getAttribute('data-type');
                const format = button.getAttribute('data-format');

                if (window.ExportUtils) {
                    window.ExportUtils.exportData(type, format);
                } else {
                    console.error('[AnalyticsManager] ExportUtils nie jest dostępne');
                }
            });
        });

        console.log('[AnalyticsManager] Przyciski exportu skonfigurowane');
    }

    /**
     * Dodatkowe event listenery
     */
    setupEventListeners() {
        // Keyboard shortcuts - ZAKTUALIZOWANA KOLEJNOŚĆ
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key >= '1' && e.key <= '5') {
                e.preventDefault();
                const tabIndex = parseInt(e.key) - 1;
                const tabs = ['sales-analytics', 'team-analytics', 'clients-analytics', 'baselinker-analytics', 'public-calc']; // ZMIANA KOLEJNOŚCI
                if (tabs[tabIndex]) {
                    this.switchTab(tabs[tabIndex]);
                }
            }
        });

        // Refresh na F5 - przeładuj tylko aktualną zakładkę
        document.addEventListener('keydown', (e) => {
            if (e.key === 'F5') {
                e.preventDefault();
                this.refreshCurrentTab();
            }
        });

        console.log('[AnalyticsManager] Event listenery skonfigurowane');
    }

    /**
     * Odświeżenie aktualnej zakładki
     */
    refreshCurrentTab() {
        console.log(`[AnalyticsManager] Odświeżanie zakładki: ${this.currentTab}`);
        this.loadedTabs.delete(this.currentTab);
        this.loadTabData(this.currentTab);
    }

    /**
     * Loading overlay
     */
    showLoading() {
        this.isLoading = true;
        const loadingEl = document.getElementById('analytics-loading');
        if (loadingEl) {
            loadingEl.classList.remove('hidden');
        }
    }

    hideLoading() {
        this.isLoading = false;
        const loadingEl = document.getElementById('analytics-loading');
        if (loadingEl) {
            loadingEl.classList.add('hidden');
        }
    }

    /**
     * Wyświetlanie błędów
     */
    showError(message) {
        console.error(`[AnalyticsManager] ${message}`);

        // Możesz dodać toast notification lub modal
        alert(`Błąd Analytics: ${message}`);
    }

    /**
     * Utility - sprawdź czy zakładka jest załadowana
     */
    isTabLoaded(tabId) {
        return this.loadedTabs.has(tabId);
    }

    /**
     * Utility - pobierz aktualną zakładkę
     */
    getCurrentTab() {
        return this.currentTab;
    }

    /**
     * Public API do wymuszenia odświeżenia zakładki
     */
    forceRefreshTab(tabId) {
        console.log(`[AnalyticsManager] Wymuszenie odświeżenia: ${tabId}`);
        this.loadedTabs.delete(tabId);
        if (this.currentTab === tabId) {
            this.loadTabData(tabId);
        }
    }
}

/**
 * ANALYTICS UTILS - Pomocnicze funkcje
 */
class AnalyticsUtils {
    /**
     * Formatowanie liczb
     */
    static formatNumber(number, decimals = 0) {
        if (number === null || number === undefined) return '-';

        return new Intl.NumberFormat('pl-PL', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(number);
    }

    /**
     * Formatowanie waluty
     */
    static formatCurrency(amount, currency = 'PLN') {
        if (amount === null || amount === undefined) return '-';

        return new Intl.NumberFormat('pl-PL', {
            style: 'currency',
            currency: currency
        }).format(amount);
    }

    /**
     * Formatowanie procentów
     */
    static formatPercent(value, decimals = 1) {
        if (value === null || value === undefined) return '-';

        return `${this.formatNumber(value, decimals)}%`;
    }

    /**
     * Formatowanie dat
     */
    static formatDate(dateString, format = 'short') {
        if (!dateString) return '-';

        const date = new Date(dateString);

        if (format === 'short') {
            return date.toLocaleDateString('pl-PL');
        } else if (format === 'long') {
            return date.toLocaleDateString('pl-PL', {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } else if (format === 'datetime') {
            return date.toLocaleString('pl-PL');
        }

        return date.toLocaleDateString('pl-PL');
    }

    /**
     * Skrócenie długich tekstów
     */
    static truncateText(text, maxLength = 50) {
        if (!text) return '-';
        if (text.length <= maxLength) return text;

        return text.substring(0, maxLength - 3) + '...';
    }

    /**
     * Klasa CSS dla wartości konwersji
     */
    static getConversionClass(value) {
        if (value >= 70) return 'conversion-high';
        if (value >= 40) return 'conversion-medium';
        return 'conversion-low';
    }

    /**
     * Klasa CSS dla statusów
     */
    static getStatusClass(status) {
        switch (status?.toLowerCase()) {
            case 'success':
            case 'successful':
            case 'sukces':
                return 'status-success';
            case 'error':
            case 'błąd':
                return 'status-error';
            case 'pending':
            case 'oczekuje':
                return 'status-pending';
            default:
                return '';
        }
    }

    /**
     * Debounce dla search i filtrów
     */
    static debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Sprawdzenie czy device jest mobilny
     */
    static isMobile() {
        return window.innerWidth <= 768;
    }

    /**
     * Chart.js default config
     */
    static getChartDefaults() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: 'white',
                    bodyColor: 'white',
                    borderColor: '#ED6B24',
                    borderWidth: 1
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.1)'
                    }
                },
                x: {
                    grid: {
                        color: 'rgba(0, 0, 0, 0.1)'
                    }
                }
            }
        };
    }
}

/**
 * Inicjalizacja po załadowaniu DOM
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Analytics] Inicjalizacja głównego systemu...');

    // Globalne obiekty
    window.AnalyticsManager = new AnalyticsManager();
    window.AnalyticsUtils = AnalyticsUtils;

    console.log('[Analytics] System główny gotowy!');
});