// modules/analytics/static/js/export_utils.js

/**
 * EXPORT UTILS - Moduł obsługi exportu danych
 * Obsługuje: export do Excel/CSV, progress, błędy
 */

class ExportUtils {
    constructor() {
        this.isExporting = false;
        this.exportQueue = [];

        this.init();
    }

    init() {
        console.log('[ExportUtils] Inicjalizacja...');

        this.setupEventListeners();

        console.log('[ExportUtils] Gotowe!');
    }

    /**
     * Główna funkcja exportu
     */
    async exportData(type, format) {
        if (this.isExporting) {
            this.showMessage('Export już w toku. Proszę czekać...', 'warning');
            return;
        }

        console.log(`[ExportUtils] Rozpoczynam export: ${type} -> ${format}`);

        try {
            this.isExporting = true;
            this.showExportProgress(true);

            // Walidacja parametrów
            if (!this.validateExportParams(type, format)) {
                throw new Error('Nieprawidłowe parametry exportu');
            }

            // Prepare download
            const downloadUrl = `/analytics/export/${type}/${format}`;

            // Show progress
            this.updateExportProgress('Przygotowywanie danych...', 30);

            // Dodatkowe dane dla contextu
            const exportContext = this.getExportContext(type);

            // Download file
            await this.downloadFile(downloadUrl, `analytics_${type}_${this.getTimestamp()}.${format}`);

            this.updateExportProgress('Export zakończony!', 100);
            this.showMessage(`Dane ${type} zostały wyeksportowane do ${format.toUpperCase()}`, 'success');

            // Log export event
            this.logExportEvent(type, format, 'success');

        } catch (error) {
            console.error('[ExportUtils] Błąd exportu:', error);
            this.showMessage(`Błąd exportu: ${error.message}`, 'error');
            this.logExportEvent(type, format, 'error', error.message);
        } finally {
            this.isExporting = false;
            this.showExportProgress(false);
        }
    }

    /**
     * Walidacja parametrów exportu
     */
    validateExportParams(type, format) {
        const validTypes = ['sales', 'team', 'clients', 'baselinker', 'public_calc'];
        const validFormats = ['xlsx', 'csv'];

        if (!validTypes.includes(type)) {
            console.error(`[ExportUtils] Nieprawidłowy typ: ${type}`);
            return false;
        }

        if (!validFormats.includes(format)) {
            console.error(`[ExportUtils] Nieprawidłowy format: ${format}`);
            return false;
        }

        return true;
    }

    /**
     * Pobieranie kontekstu exportu (dodatkowe parametry)
     */
    getExportContext(type) {
        const context = {
            timestamp: new Date().toISOString(),
            user_agent: navigator.userAgent,
            current_tab: window.AnalyticsManager ? window.AnalyticsManager.getCurrentTab() : null
        };

        // Dodaj specyficzne dane dla każdego typu
        switch (type) {
            case 'sales':
                if (window.SalesAnalytics) {
                    const salesData = window.SalesAnalytics.getExportData();
                    context.sales_months = document.getElementById('sales-months-select')?.value || 12;
                    context.has_trends = salesData.trends ? salesData.trends.length : 0;
                    context.has_products = salesData.products ? salesData.products.length : 0;
                }
                break;

            case 'team':
                if (window.TeamAnalytics) {
                    const teamData = window.TeamAnalytics.getExportData();
                    context.team_members = teamData.team_performance ? teamData.team_performance.length : 0;
                }
                break;

            case 'clients':
                if (window.ClientsAnalytics) {
                    const clientsData = window.ClientsAnalytics.getExportData();
                    context.clients_limit = clientsData.current_limit || 20;
                    context.clients_count = clientsData.top_clients ? clientsData.top_clients.length : 0;
                }
                break;

            case 'baselinker':
                if (window.BaselinkerAnalytics) {
                    const blData = window.BaselinkerAnalytics.getExportData();
                    context.has_logs = blData.baselinker && blData.baselinker.recent_logs ? blData.baselinker.recent_logs.length : 0;
                }
                break;
        }

        return context;
    }

    /**
    * Download pliku - POPRAWIONA WERSJA
    */
    async downloadFile(url, filename) {
        this.updateExportProgress('Pobieranie pliku...', 60);

        try {
            // Fetch file as blob
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const blob = await response.blob();

            this.updateExportProgress('Przygotowywanie do pobrania...', 80);

            // Create download URL
            const downloadUrl = window.URL.createObjectURL(blob);

            // Create download link
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = filename;
            link.style.display = 'none';

            // Add to DOM, click, and remove
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            // Cleanup blob URL
            setTimeout(() => {
                window.URL.revokeObjectURL(downloadUrl);
            }, 1000);

            this.updateExportProgress('Plik pobierany...', 90);
            console.log(`[ExportUtils] Plik ${filename} przygotowany do pobrania`);

        } catch (error) {
            console.error('[ExportUtils] Błąd pobierania pliku:', error);
            throw new Error(`Nie można pobrać pliku: ${error.message}`);
        }
    }

    /**
     * Progress export
     */
    showExportProgress(show) {
        const loadingEl = document.getElementById('analytics-loading');
        if (loadingEl) {
            if (show) {
                loadingEl.classList.remove('hidden');
                this.updateExportProgress('Inicjalizacja exportu...', 0);
            } else {
                loadingEl.classList.add('hidden');
            }
        }
    }

    updateExportProgress(message, progress) {
        const loadingEl = document.getElementById('analytics-loading');
        if (loadingEl) {
            const messageEl = loadingEl.querySelector('p');
            if (messageEl) {
                messageEl.textContent = message;
            }

            // Dodaj progress bar jeśli nie istnieje
            let progressBar = loadingEl.querySelector('.export-progress-bar');
            if (!progressBar) {
                progressBar = document.createElement('div');
                progressBar.className = 'export-progress-bar';
                progressBar.innerHTML = `
                    <div class="export-progress-fill"></div>
                    <span class="export-progress-text">0%</span>
                `;
                loadingEl.appendChild(progressBar);
            }

            const progressFill = progressBar.querySelector('.export-progress-fill');
            const progressText = progressBar.querySelector('.export-progress-text');

            if (progressFill) {
                progressFill.style.width = `${progress}%`;
            }
            if (progressText) {
                progressText.textContent = `${progress}%`;
            }
        }
    }

    /**
     * Wyświetlanie wiadomości
     */
    showMessage(message, type = 'info') {
        console.log(`[ExportUtils] ${type.toUpperCase()}: ${message}`);

        // Utwórz toast notification
        const toast = document.createElement('div');
        toast.className = `export-toast export-toast-${type}`;
        toast.innerHTML = `
            <div class="export-toast-content">
                <span class="export-toast-icon">${this.getToastIcon(type)}</span>
                <span class="export-toast-message">${message}</span>
                <button class="export-toast-close" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;

        // Dodaj style jeśli nie istnieją
        this.addToastStyles();

        document.body.appendChild(toast);

        // Auto remove po 5 sekundach
        setTimeout(() => {
            if (toast.parentElement) {
                toast.remove();
            }
        }, 5000);

        // Animacja wejścia
        setTimeout(() => {
            toast.classList.add('export-toast-show');
        }, 100);
    }

    /**
     * Ikony dla toast
     */
    getToastIcon(type) {
        switch (type) {
            case 'success': return '✅';
            case 'error': return '❌';
            case 'warning': return '⚠️';
            case 'info': return 'ℹ️';
            default: return '📢';
        }
    }

    /**
     * Dodanie stylów toast
     */
    addToastStyles() {
        if (document.getElementById('export-toast-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'export-toast-styles';
        styles.textContent = `
            .export-toast {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                max-width: 400px;
                transform: translateX(100%);
                transition: transform 0.3s ease;
            }
            .export-toast-show {
                transform: translateX(0);
            }
            .export-toast-content {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 12px 16px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                font-size: 14px;
                font-weight: 500;
            }
            .export-toast-success .export-toast-content {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .export-toast-error .export-toast-content {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            .export-toast-warning .export-toast-content {
                background: #fff3cd;
                color: #856404;
                border: 1px solid #ffeaa7;
            }
            .export-toast-info .export-toast-content {
                background: #d1ecf1;
                color: #0c5460;
                border: 1px solid #bee5eb;
            }
            .export-toast-close {
                background: none;
                border: none;
                font-size: 18px;
                cursor: pointer;
                opacity: 0.7;
                margin-left: auto;
            }
            .export-toast-close:hover {
                opacity: 1;
            }
            .export-progress-bar {
                margin-top: 10px;
                background: rgba(255,255,255,0.2);
                border-radius: 4px;
                overflow: hidden;
                position: relative;
                height: 20px;
            }
            .export-progress-fill {
                height: 100%;
                background: #ED6B24;
                transition: width 0.3s ease;
                border-radius: 4px;
            }
            .export-progress-text {
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                font-size: 12px;
                font-weight: 600;
                color: white;
                text-shadow: 0 1px 2px rgba(0,0,0,0.5);
            }
        `;

        document.head.appendChild(styles);
    }

    /**
     * Event listeners
     */
    setupEventListeners() {
        // Keyboard shortcut: Ctrl+Shift+E dla export aktualnej zakładki
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'E') {
                e.preventDefault();
                this.exportCurrentTab();
            }
        });

        console.log('[ExportUtils] Event listeners skonfigurowane');
    }

    /**
     * Export aktualnej zakładki
     */
    exportCurrentTab() {
        const currentTab = window.AnalyticsManager ? window.AnalyticsManager.getCurrentTab() : null;

        if (!currentTab) {
            this.showMessage('Nie można określić aktualnej zakładki', 'warning');
            return;
        }

        let exportType = currentTab;
        if (currentTab === 'public-calc') {
            exportType = 'public_calc';
        } else {
            exportType = currentTab.replace('-analytics', '');
        }

        this.exportData(exportType, 'xlsx');
    }

    /**
     * Logowanie zdarzeń exportu
     */
    logExportEvent(type, format, status, error = null) {
        const event = {
            timestamp: new Date().toISOString(),
            type: type,
            format: format,
            status: status,
            error: error,
            user_agent: navigator.userAgent
        };

        console.log('[ExportUtils] Export event:', event);

        // Możesz dodać wysyłanie do analytics lub logowanie na serwerze
    }

    /**
     * Utilities
     */
    getTimestamp() {
        const now = new Date();
        return now.toISOString().slice(0, 19).replace(/[:]/g, '-');
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

/**
 * Inicjalizacja
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[ExportUtils] Inicjalizacja modułu...');

    window.ExportUtils = new ExportUtils();

    console.log('[ExportUtils] Moduł gotowy!');
});