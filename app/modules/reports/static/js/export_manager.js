// modules/reports/static/js/export_manager.js
/**
 * Manager eksportu danych do Excel
 * Odpowiedzialny za generowanie i pobieranie plików Excel
 */

class ExportManager {
    constructor() {
        this.isExporting = false;
        this.exportDropdown = null;
        this.fullscreenExportDropdown = null;
        this.lastExportTime = null;

        console.log('[ExportManager] Initialized with dropdown support');
    }

    /**
     * Inicjalizacja managera
     */
    init() {
        console.log('[ExportManager] Starting initialization...');

        this.cacheElements();
        this.setupEventListeners();
        this.initDropdowns();

        console.log('[ExportManager] Initialization complete');
    }

    /**
     * Cache elementów DOM - ZAKTUALIZOWANE dla dropdown
     */
    cacheElements() {
        // Dropdown'y export
        this.exportDropdown = document.querySelector('.export-dropdown');
        this.fullscreenExportDropdown = document.querySelector('.fullscreen-export-btn.export-dropdown');

        // Przyciski główne
        this.exportButton = document.getElementById('exportBtn');
        this.fullscreenExportButton = document.getElementById('fullscreenExportBtn');

        // Opcje export
        this.exportExcelOption = document.getElementById('exportExcelOption');
        this.exportRoutimoOption = document.getElementById('exportRoutimoOption');
        this.fullscreenExportExcelOption = document.getElementById('fullscreenExportExcelOption');
        this.fullscreenExportRoutimoOption = document.getElementById('fullscreenExportRoutimoOption');

        console.log('[ExportManager] Elements cached:', {
            exportDropdown: !!this.exportDropdown,
            exportButton: !!this.exportButton,
            exportExcelOption: !!this.exportExcelOption,
            exportRoutimoOption: !!this.exportRoutimoOption
        });
    }

    setupEventListeners() {
        // === OBSŁUGA DROPDOWN EXPORT ===

        // Excel export - normalny tryb
        if (this.exportExcelOption) {
            this.exportExcelOption.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeAllDropdowns(); // Zamknij dropdown po kliknięciu
                this.exportToExcel();
            });
        }

        // Excel export - fullscreen
        if (this.fullscreenExportExcelOption) {
            this.fullscreenExportExcelOption.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeAllDropdowns();
                this.exportToExcel();
            });
        }

        // Routimo export - normalny tryb  
        if (this.exportRoutimoOption) {
            this.exportRoutimoOption.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeAllDropdowns();
                this.exportToRoutimo();
            });
        }

        // Routimo export - fullscreen
        if (this.fullscreenExportRoutimoOption) {
            this.fullscreenExportRoutimoOption.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeAllDropdowns();
                this.exportToRoutimo();
            });
        }

        // === OBSŁUGA PRZYCISKÓW DROPDOWN TOGGLE ===

        // Główny przycisk dropdown
        if (this.exportButton) {
            this.exportButton.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleDropdown(this.exportDropdown);
            });
        }

        // Fullscreen przycisk dropdown
        if (this.fullscreenExportButton) {
            this.fullscreenExportButton.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleDropdown(this.fullscreenExportDropdown);
            });
        }

        // Zamknięcie dropdown'a po kliknięciu poza nim
        document.addEventListener('click', (e) => {
            this.handleOutsideClick(e);
        });

        // Obsługa klawisza ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllDropdowns();
            }
        });

        console.log('[ExportManager] Event listeners setup complete');
    }

    /**
     * NOWA METODA - Toggle dropdown
     */
    toggleDropdown(dropdown) {
        if (!dropdown) return;

        const button = dropdown.querySelector('.dropdown-toggle');
        const menu = dropdown.querySelector('.dropdown-menu');

        if (!button || !menu) return;

        const isOpen = menu.classList.contains('show');

        // Zamknij wszystkie inne dropdown'y
        this.closeAllDropdowns();

        if (!isOpen) {
            // Otwórz ten dropdown
            button.setAttribute('aria-expanded', 'true');
            menu.classList.add('show');

            // Dostosuj pozycję w fullscreen
            if (dropdown.classList.contains('fullscreen-export-btn') ||
                dropdown.closest('.fullscreen-mode')) {
                this.adjustDropdownPositionFullscreen(menu);
            }

            console.log('[ExportManager] Dropdown opened');
        }
    }

    /**
     * ZAKTUALIZOWANA METODA - Obsługa kliknięcia poza dropdown'em
     */
    handleOutsideClick(e) {
        // Sprawdź czy kliknięto poza dropdown'ami export
        const exportDropdowns = document.querySelectorAll('.export-dropdown');
        let clickedInside = false;

        exportDropdowns.forEach(dropdown => {
            if (dropdown.contains(e.target)) {
                clickedInside = true;
            }
        });

        if (!clickedInside) {
            this.closeAllDropdowns();
        }
    }

    /**
     * ZAKTUALIZOWANA METODA - Zamknięcie dropdown'a
     */
    closeDropdown(dropdown) {
        if (!dropdown) return;

        const button = dropdown.querySelector('.dropdown-toggle');
        const menu = dropdown.querySelector('.dropdown-menu');

        if (button && menu) {
            button.setAttribute('aria-expanded', 'false');
            menu.classList.remove('show');
        }
    }

    /**
     * NOWA METODA - Inicjalizacja dropdown'ów (wywołaj w init())
     */
    initDropdowns() {
        // Upewnij się, że wszystkie dropdown'y są zamknięte na start
        this.closeAllDropdowns();

        // Sprawdź czy Bootstrap jest dostępny
        if (typeof bootstrap !== 'undefined') {
            console.log('[ExportManager] Bootstrap detected, using Bootstrap dropdowns');
            this.initBootstrapDropdowns();
        } else {
            console.log('[ExportManager] Bootstrap not detected, using manual dropdowns');
        }
    }

    /**
     * NOWA METODA - Zamknij wszystkie dropdown'y
     */
    closeAllDropdowns() {
        const dropdowns = document.querySelectorAll('.export-dropdown');

        dropdowns.forEach(dropdown => {
            this.closeDropdown(dropdown);
        });
    }

    /**
     * NOWA METODA - Dostosuj pozycję dropdown'a w fullscreen
     */
    adjustDropdownPositionFullscreen(menu) {
        if (!menu) return;

        menu.style.position = 'absolute';
        menu.style.top = 'auto';
        menu.style.bottom = '100%';
        menu.style.left = '0';
        menu.style.marginBottom = '2px';
        menu.style.zIndex = '1002';
    }

    /**
     * Główna funkcja eksportu do Excel - POPRAWKA: Dodano timeout i retry logic
     */
    async exportToExcel() {
        if (this.isExporting) {
            console.log('[ExportManager] Export already in progress, skipping...');
            this.showNotification('Eksport już w toku. Proszę czekać...', 'warning');
            return;
        }

        // POPRAWKA: Sprawdź czy nie eksportowano zbyt niedawno (throttling)
        if (this.isExporting) {
            console.log('[ExportManager] Export already in progress, skipping...');
            return; // Bez alert'a
        }

        console.log('[ExportManager] Starting Excel export...');

        this.setExportingState(true);
        this.lastExportTime = Date.now();

        try {
            // Pobierz aktualne filtry i zakres dat z ReportsManager
            const dateRange = this.getCurrentDateRange();
            const filters = this.getCurrentFilters();

            console.log('[ExportManager] Export parameters:', {
                dateRange,
                filtersCount: Object.keys(filters).length,
                isFullscreen: this.isInFullscreenMode()
            });

            // Walidacja danych przed eksportem
            const validationResult = this.validateExportData(dateRange, filters);
            if (!validationResult.isValid) {
                throw new Error(validationResult.message);
            }

            // Przygotuj parametry URL
            const params = new URLSearchParams();

            // Dodaj daty
            if (dateRange.date_from) {
                params.append('date_from', dateRange.date_from);
            }
            if (dateRange.date_to) {
                params.append('date_to', dateRange.date_to);
            }

            // Dodaj filtry (obsługa multiple values)
            for (const [key, values] of Object.entries(filters)) {
                if (values && Array.isArray(values) && values.length > 0) {
                    values.forEach(value => {
                        if (value && value.trim()) {
                            params.append(`filter_${key}`, value.trim());
                        }
                    });
                }
            }

            // NOWE: Dodaj informację o trybie fullscreen
            if (this.isInFullscreenMode()) {
                params.append('fullscreen_mode', 'true');
            }

            // POPRAWKA: Dodano timeout i retry logic
            const response = await this.fetchWithTimeout(`/reports/api/export-excel?${params}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                }
            }, 30000); // 30 sekund timeout

            if (!response.ok) {
                // Sprawdź czy to JSON z błędem
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const errorResult = await response.json();
                    throw new Error(errorResult.error || 'Błąd eksportu');
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            }

            // Pobierz blob z pliku Excel
            const blob = await response.blob();

            if (blob.size === 0) {
                throw new Error('Otrzymano pusty plik');
            }

            // POPRAWKA: Sprawdź czy blob jest prawidłowy
            if (blob.type && !blob.type.includes('sheet') && !blob.type.includes('excel')) {
                console.warn('[ExportManager] Unexpected blob type:', blob.type);
            }

            // Pobierz nazwę pliku z nagłówka lub wygeneruj
            const filename = this.getFilenameFromResponse(response) || this.generateFilename();

            // Pobierz plik
            this.downloadBlob(blob, filename);

            console.log('[ExportManager] Excel export completed successfully', {
                filename,
                fileSize: blob.size,
                isFullscreen: this.isInFullscreenMode()
            });

            // Pokaż komunikat sukcesu
            this.showExportSuccess(filename, blob.size);

        } catch (error) {
            console.error('[ExportManager] Export error:', error);
            this.showExportError(error.message);
        } finally {
            this.setExportingState(false);
        }
    }

    /**
 * NOWA METODA - Export do Routimo CSV
 */
    async exportToRoutimo() {
        if (this.isExporting) {
            console.log('[ExportManager] Export already in progress, skipping...');
            return;
        }

        if (this.lastExportTime && (Date.now() - this.lastExportTime) < 2000) {
            console.log('[ExportManager] Export throttled - too soon after last export');
            return;
        }

        console.log('[ExportManager] Starting Routimo export...');

        this.setExportingState(true, 'routimo');
        this.lastExportTime = Date.now();

        try {
            // Pobierz aktualne filtry i zakres dat z ReportsManager
            const dateRange = this.getCurrentDateRange();
            const filters = this.getCurrentFilters();

            console.log('[ExportManager] Routimo export parameters:', {
                dateRange,
                filtersCount: Object.keys(filters).length,
                isFullscreen: this.isInFullscreenMode()
            });

            // Walidacja danych przed eksportem
            const validationResult = this.validateRoutimoExportData(dateRange, filters);
            if (!validationResult.isValid) {
                throw new Error(validationResult.message);
            }

            // Przygotuj parametry URL
            const params = new URLSearchParams();

            // Dodaj daty
            if (dateRange.date_from) {
                params.append('date_from', dateRange.date_from);
            }
            if (dateRange.date_to) {
                params.append('date_to', dateRange.date_to);
            }

            // WAŻNE: Routimo nie używa filtrów kolumn - tylko statusy są filtrowane backend
            // Dodaj informację o trybie fullscreen
            if (this.isInFullscreenMode()) {
                params.append('fullscreen_mode', 'true');
            }

            const response = await this.fetchWithTimeout(`/reports/api/export-routimo?${params}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                }
            }, 30000); // 30 sekund timeout

            if (!response.ok) {
                // Sprawdź czy to JSON z błędem
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const errorResult = await response.json();
                    throw new Error(errorResult.error || 'Błąd eksportu Routimo');
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            }

            // Pobierz blob z pliku CSV
            const blob = await response.blob();

            if (blob.size === 0) {
                throw new Error('Otrzymano pusty plik CSV');
            }

            // Pobierz nazwę pliku z nagłówka lub wygeneruj
            const filename = this.getFilenameFromResponse(response) || this.generateRoutimoFilename(dateRange);

            // Pobierz plik
            this.downloadBlob(blob, filename);

            console.log('[ExportManager] Routimo export completed successfully', {
                filename,
                fileSize: blob.size,
                isFullscreen: this.isInFullscreenMode()
            });

            // Pokaż komunikat sukcesu (opcjonalnie)
            console.log(`✅ Plik "${filename}" został pobrany pomyślnie (${Math.round(blob.size / 1024)} KB)`);

        } catch (error) {
            console.error('[ExportManager] Routimo export error:', error);
            // Pokaż błąd użytkownikowi
            alert('Błąd eksportu Routimo: ' + error.message);
        } finally {
            this.setExportingState(false);
        }
    }

    /**
     * NOWA METODA - Walidacja danych przed eksportem Routimo
     */
    validateRoutimoExportData(dateRange, filters) {
        // Sprawdź czy są dane do eksportu
        const currentData = this.getCurrentData();
        if (!currentData || currentData.length === 0) {
            return {
                isValid: false,
                message: 'Brak danych do eksportu. Sprawdź filtry i zakres dat.'
            };
        }

        // ZMIANA: Sprawdź czy są zamówienia INNE NIŻ wykluczone statusy
        const excludedStatusIds = [138625, 149779, 149778, 138624, 149777, 149763, 105114];
        const excludedStatusNames = [
            'Zamówienie anulowane',
            'Odebrane',
            'Dostarczona - transport WoodPower',
            'Dostarczona - kurier',
            'Czeka na odbiór osobisty',
            'Wysłane - transport WoodPower',
            'Wysłane - kurier'
        ];

        const hasValidOrders = currentData.some(record => {
            // Sprawdź czy status NIE jest na liście wykluczonych
            return !excludedStatusNames.includes(record.current_status);
        });

        if (!hasValidOrders) {
            return {
                isValid: false,
                message: 'Brak zamówień dostępnych do eksportu. Wszystkie zamówienia mają wykluczone statusy (anulowane, dostarczone, odebrane).'
            };
        }

        // Sprawdź zakres dat
        if (!dateRange.date_from || !dateRange.date_to) {
            return {
                isValid: false,
                message: 'Nieprawidłowy zakres dat. Wybierz datę początkową i końcową.'
            };
        }

        return {
            isValid: true,
            message: 'Dane są prawidłowe dla eksportu Routimo'
        };
    }

    /**
     * NOWA METODA - Generowanie nazwy pliku CSV dla Routimo
     */
    generateRoutimoFilename(dateRange) {
        const now = new Date();
        const dateString = now.toISOString().slice(0, 10); // YYYY-MM-DD

        // Dodaj informacje o zakresie dat jeśli dostępne
        let dateRangeStr = dateString;
        if (dateRange.date_from && dateRange.date_to) {
            const fromStr = dateRange.date_from.replace(/-/g, '');
            const toStr = dateRange.date_to.replace(/-/g, '');
            if (fromStr === toStr) {
                dateRangeStr = fromStr;
            } else {
                dateRangeStr = `${fromStr}_${toStr}`;
            }
        }

        return `routimo_export_${dateRangeStr}.xlsx`; // ZMIANA: .xlsx zamiast .csv
    }

    /**
     * NOWA METODA - Fetch z timeout
     */
    async fetchWithTimeout(url, options = {}, timeout = 30000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Timeout - eksport trwa zbyt długo');
            }
            throw error;
        }
    }

    /**
     * NOWA METODA - Walidacja danych przed eksportem
     */
    validateExportData(dateRange, filters) {
        // Sprawdź czy są dane do eksportu
        const currentData = this.getCurrentData();
        if (!currentData || currentData.length === 0) {
            return {
                isValid: false,
                message: 'Brak danych do eksportu. Zmień filtry lub zakres dat.'
            };
        }

        // Sprawdź zakres dat
        if (!dateRange.date_from || !dateRange.date_to) {
            return {
                isValid: false,
                message: 'Nieprawidłowy zakres dat. Wybierz datę początkową i końcową.'
            };
        }

        // Sprawdź czy data końcowa nie jest wcześniejsza niż początkowa
        if (dateRange.date_from > dateRange.date_to) {
            return {
                isValid: false,
                message: 'Data końcowa nie może być wcześniejsza niż data początkowa.'
            };
        }

        // Sprawdź czy zakres dat nie jest zbyt duży (max 1 rok)
        const dateFrom = new Date(dateRange.date_from);
        const dateTo = new Date(dateRange.date_to);
        const daysDiff = Math.ceil((dateTo - dateFrom) / (1000 * 60 * 60 * 24));

        if (daysDiff > 365) {
            return {
                isValid: false,
                message: 'Zakres dat nie może być większy niż 1 rok.'
            };
        }

        // Sprawdź czy nie ma zbyt dużo danych (max 10000 rekordów)
        if (currentData.length > 10000) {
            return {
                isValid: false,
                message: `Zbyt dużo danych do eksportu (${currentData.length} rekordów). Ogranicz zakres dat lub użyj filtrów.`
            };
        }

        return {
            isValid: true,
            message: 'Dane są prawidłowe'
        };
    }

    /**
     * Pobranie nazwy pliku z nagłówka odpowiedzi
     */
    getFilenameFromResponse(response) {
        const contentDisposition = response.headers.get('Content-Disposition');
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (filenameMatch && filenameMatch[1]) {
                return filenameMatch[1].replace(/['"]/g, '');
            }
        }
        return null;
    }

    /**
     * Generowanie nazwy pliku - POPRAWKA: Bezpieczniejsze generowanie
     */
    generateFilename() {
        const now = new Date();
        const dateString = now.toISOString().slice(0, 10).replace(/-/g, ''); // YYYYMMDD
        const timeString = now.toTimeString().slice(0, 8).replace(/:/g, ''); // HHMMSS

        // Pobierz informacje o zakresie dat
        const dateRange = this.getCurrentDateRange();
        let dateRangeStr = 'custom';

        if (dateRange.date_from && dateRange.date_to) {
            const fromStr = dateRange.date_from.replace(/-/g, '');
            const toStr = dateRange.date_to.replace(/-/g, '');
            if (fromStr === toStr) {
                dateRangeStr = fromStr;
            } else {
                dateRangeStr = `${fromStr}_${toStr}`;
            }
        }

        // POPRAWKA: Dodano informacje o filtrach w nazwie
        const filters = this.getCurrentFilters();
        const filtersCount = Object.keys(filters).length;
        const filtersStr = filtersCount > 0 ? `_filtered_${filtersCount}` : '';

        // NOWE: Dodaj informację o fullscreen
        const fullscreenStr = this.isInFullscreenMode() ? '_fullscreen' : '';

        return `raporty_sprzedazy_${dateRangeStr}${filtersStr}${fullscreenStr}_${dateString}_${timeString}.xlsx`;
    }

    /**
     * Pobieranie blob'a jako plik - POPRAWKA: Lepsza obsługa błędów
     */
    downloadBlob(blob, filename) {
        console.log('[ExportManager] Downloading file:', filename);

        try {
            // Sprawdź czy przeglądarka obsługuje download
            if (window.navigator && window.navigator.msSaveOrOpenBlob) {
                // Internet Explorer
                window.navigator.msSaveOrOpenBlob(blob, filename);
            } else {
                // Nowoczesne przeglądarki
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = filename;
                link.style.display = 'none';

                // Dodaj do DOM, kliknij, usuń
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);

                // Zwolnij URL po krótkiej chwili
                setTimeout(() => {
                    window.URL.revokeObjectURL(url);
                }, 1000);
            }
        } catch (error) {
            console.error('[ExportManager] Error downloading file:', error);
            throw new Error('Nie udało się pobrać pliku');
        }
    }

    /**
     * Ustawienie stanu eksportowania - ZAKTUALIZOWANE dla dropdown
     */
    setExportingState(isExporting, exportType = 'excel') {
        this.isExporting = isExporting;

        // Aktualizuj wszystkie dropdown'y export
        this.updateDropdownState(this.exportDropdown, isExporting, exportType);
        this.updateDropdownState(this.fullscreenExportDropdown, isExporting, exportType);

        console.log('[ExportManager] Export state changed:', isExporting, 'type:', exportType);
    }

    /**
     * Komunikat sukcesu eksportu
     */
    showExportSuccess(filename, fileSize) {
        const fileSizeKB = Math.round(fileSize / 1024);
        const message = `Plik "${filename}" został pobrany pomyślnie (${fileSizeKB} KB)`;
        console.log('[ExportManager] Export success:', message);
        // Usunięte wszystkie notyfikacje - plik się pobiera, to wystarczy
    }

    /**
     * ZAKTUALIZOWANA METODA - Aktualizacja stanu dropdown'a z obsługą Routimo
     */
    updateDropdownState(dropdown, isExporting, exportType) {
        if (!dropdown) return;

        const button = dropdown.querySelector('.dropdown-toggle');
        if (!button) return;

        button.disabled = isExporting;

        if (isExporting) {
            dropdown.classList.add('exporting');

            let exportLabel = 'Eksportowanie';
            if (exportType === 'excel') {
                exportLabel = 'Eksport Excel...';
            } else if (exportType === 'routimo') {
                exportLabel = 'Eksport Routimo...';
            }

            button.innerHTML = `
            <i class="fas fa-spinner fa-spin"></i>
            ${exportLabel}
        `;
        } else {
            dropdown.classList.remove('exporting');
            button.innerHTML = `
            <i class="fas fa-download"></i>
            Export
        `;
        }
    }

    /**
     * Komunikat błędu eksportu
     */
    showExportError(errorMessage) {
        const message = `Błąd eksportu: ${errorMessage}`;

        console.error('[ExportManager] Export error:', message);

        // NOWE: W fullscreen pokaż bardziej dyskretną notyfikację
        if (this.isInFullscreenMode()) {
            this.showFullscreenNotification(message, 'error');
        } else {
            this.showNotification(message, 'error');
        }
    }

    /**
     * NOWA METODA - Notyfikacja w trybie fullscreen
     */
    showFullscreenNotification(message, type = 'info') {
        console.log(`[ExportManager] Fullscreen ${type.toUpperCase()}: ${message}`);

        // Utwórz toast notification
        const notification = document.createElement('div');
        notification.className = `fullscreen-notification ${type}`;
        notification.innerHTML = `
            <i class="fas fa-${this.getNotificationIcon(type)}"></i>
            <span>${message}</span>
        `;

        // Style dla notyfikacji
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${this.getNotificationColor(type)};
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 10003;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 500;
            max-width: 300px;
            animation: slideInRight 0.3s ease;
        `;

        // Dodaj do fullscreen container
        const fullscreenContainer = document.getElementById('fullscreenContainer');
        if (fullscreenContainer) {
            fullscreenContainer.appendChild(notification);
        } else {
            document.body.appendChild(notification);
        }

        // Automatyczne usunięcie po 5 sekundach
        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 5000);
    }

    /**
     * NOWA METODA - Pobieranie ikony dla notyfikacji
     */
    getNotificationIcon(type) {
        const icons = {
            success: 'check-circle',
            error: 'exclamation-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
        return icons[type] || 'info-circle';
    }

    /**
     * NOWA METODA - Pobieranie koloru dla notyfikacji
     */
    getNotificationColor(type) {
        const colors = {
            success: '#28a745',
            error: '#dc3545',
            warning: '#ffc107',
            info: '#17a2b8'
        };
        return colors[type] || '#17a2b8';
    }

    /**
     * Pokazanie notyfikacji - POPRAWKA: Lepszy system notyfikacji
     */
    showNotification(message, type = 'info') {
        console.log(`[ExportManager] ${type.toUpperCase()}: ${message}`);
        // Wszystkie alert'y usunięte - tylko console.log
    }

    /**
     * Eksport z niestandardowymi parametrami
     */
    async exportWithCustomParams(customParams = {}) {
        console.log('[ExportManager] Custom export with params:', customParams);

        if (this.isExporting) {
            console.log('[ExportManager] Export already in progress, skipping...');
            return; // Bez alert'a
        }

        this.setExportingState(true);

        try {
            // Przygotuj parametry URL
            const params = new URLSearchParams(customParams);

            // POPRAWKA: Użyj fetchWithTimeout
            const response = await this.fetchWithTimeout(`/reports/api/export-excel?${params}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                }
            }, 30000);

            if (!response.ok) {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const errorResult = await response.json();
                    throw new Error(errorResult.error || 'Błąd eksportu');
                } else {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
            }

            // Pobierz i zapisz plik
            const blob = await response.blob();
            const filename = this.getFilenameFromResponse(response) || this.generateCustomFilename(customParams);

            this.downloadBlob(blob, filename);
            this.showExportSuccess(filename, blob.size);

        } catch (error) {
            console.error('[ExportManager] Custom export error:', error);
            this.showExportError(error.message);
        } finally {
            this.setExportingState(false);
        }
    }

    /**
     * Generowanie nazwy pliku dla niestandardowego eksportu
     */
    generateCustomFilename(params) {
        const now = new Date();
        const dateString = now.toISOString().slice(0, 10).replace(/-/g, ''); // YYYYMMDD
        const timeString = now.toTimeString().slice(0, 8).replace(/:/g, ''); // HHMMSS

        let suffix = '';
        if (params.date_from && params.date_to) {
            const fromStr = params.date_from.replace(/-/g, '');
            const toStr = params.date_to.replace(/-/g, '');
            if (fromStr === toStr) {
                suffix = `_${fromStr}`;
            } else {
                suffix = `_${fromStr}_${toStr}`;
            }
        }

        return `raporty_sprzedazy${suffix}_${dateString}_${timeString}.xlsx`;
    }

    /**
     * Sprawdzenie czy eksport jest możliwy - POPRAWKA: Ulepszona walidacja
     */
    canExport() {
        // Sprawdź czy są dane do eksportu
        const currentData = this.getCurrentData();

        if (!currentData || currentData.length === 0) {
            console.log('[ExportManager] Cannot export: no data available');
            const message = 'Brak danych do eksportu. Zmień filtry lub zakres dat.';

            if (this.isInFullscreenMode()) {
                this.showFullscreenNotification(message, 'warning');
            } else {
                this.showNotification(message, 'warning');
            }
            return false;
        }

        if (this.isExporting) {
            console.log('[ExportManager] Cannot export: export in progress');
            const message = 'Eksport już w toku. Proszę czekać...';

            if (this.isInFullscreenMode()) {
                this.showFullscreenNotification(message, 'warning');
            } else {
                this.showNotification(message, 'warning');
            }
            return false;
        }

        // POPRAWKA: Sprawdź throttling
        if (this.lastExportTime && (Date.now() - this.lastExportTime) < 2000) {
            console.log('[ExportManager] Cannot export: too soon after last export');
            const message = 'Proszę poczekać przed kolejnym eksportem';

            if (this.isInFullscreenMode()) {
                this.showFullscreenNotification(message, 'warning');
            } else {
                this.showNotification(message, 'warning');
            }
            return false;
        }

        // POPRAWKA: Sprawdź czy ReportsManager jest dostępny
        if (!window.reportsManager) {
            console.log('[ExportManager] Cannot export: ReportsManager not available');
            const message = 'System raportów nie jest dostępny';

            if (this.isInFullscreenMode()) {
                this.showFullscreenNotification(message, 'error');
            } else {
                this.showNotification(message, 'error');
            }
            return false;
        }

        return true;
    }

    /**
     * Eksport z walidacją
     */
    async exportToExcelWithValidation() {
        if (!this.canExport()) {
            return;
        }

        await this.exportToExcel();
    }

    /**
     * Pobieranie informacji o aktualnych danych do eksportu
     */
    getExportInfo() {
        const currentData = this.getCurrentData();
        const currentStats = this.getCurrentStats();
        const dateRange = this.getCurrentDateRange();
        const filters = this.getCurrentFilters();

        return {
            recordsCount: currentData ? currentData.length : 0,
            dateRange: dateRange,
            filtersCount: Object.keys(filters).length,
            totalValue: currentStats.value_net || 0,
            totalVolume: currentStats.total_m3 || 0
        };
    }

    /**
     * Podgląd danych przed eksportem
     */
    showExportPreview() {
        const info = this.getExportInfo();

        const message = `
Eksport będzie zawierał:
• Liczba rekordów: ${info.recordsCount}
• Zakres dat: ${this.getDateRangeLabel(info.dateRange)}
• Aktywne filtry: ${info.filtersCount}
• Łączna wartość: ${info.totalValue.toFixed(2)} zł netto
• Łączna objętość: ${info.totalVolume.toFixed(2)} m³

Czy chcesz kontynuować eksport?
        `.trim();

        return confirm(message);
    }

    /**
     * Etykiety dla zakresów dat
     */
    getDateRangeLabel(dateRange) {
        if (!dateRange.date_from || !dateRange.date_to) {
            return 'Nieokreślony';
        }

        const fromDate = new Date(dateRange.date_from);
        const toDate = new Date(dateRange.date_to);

        // Format dd-mm-yyyy
        const formatDate = (date) => {
            const day = date.getDate().toString().padStart(2, '0');
            const month = (date.getMonth() + 1).toString().padStart(2, '0');
            const year = date.getFullYear();
            return `${day}-${month}-${year}`;
        };

        if (dateRange.date_from === dateRange.date_to) {
            return formatDate(fromDate);
        } else {
            return `${formatDate(fromDate)} do ${formatDate(toDate)}`;
        }
    }

    /**
     * Eksport z podglądem
     */
    async exportWithPreview() {
        if (!this.canExport()) {
            return;
        }

        if (this.showExportPreview()) {
            await this.exportToExcel();
        }
    }

    /**
     * Pobieranie danych z ReportsManager - POPRAWKA: Bezpieczniejsze pobieranie
     */
    getCurrentData() {
        if (window.reportsManager && typeof window.reportsManager.getCurrentData === 'function') {
            return window.reportsManager.getCurrentData();
        }
        console.warn('[ExportManager] ReportsManager not available for getCurrentData');
        return [];
    }

    getCurrentStats() {
        if (window.reportsManager && typeof window.reportsManager.getCurrentStats === 'function') {
            return window.reportsManager.getCurrentStats();
        }
        console.warn('[ExportManager] ReportsManager not available for getCurrentStats');
        return {};
    }

    getCurrentFilters() {
        if (window.reportsManager && typeof window.reportsManager.getCurrentFilters === 'function') {
            return window.reportsManager.getCurrentFilters();
        }
        console.warn('[ExportManager] ReportsManager not available for getCurrentFilters');
        return {};
    }

    getCurrentDateRange() {
        if (window.reportsManager && typeof window.reportsManager.getCurrentDateRange === 'function') {
            return window.reportsManager.getCurrentDateRange();
        }

        console.warn('[ExportManager] ReportsManager not available for getCurrentDateRange, using fallback');
        // Fallback - ostatni miesiąc
        const today = new Date();
        const lastMonth = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);

        return {
            date_from: lastMonth.toISOString().split('T')[0],
            date_to: today.toISOString().split('T')[0]
        };
    }

    /**
     * Eksport konkretnego zakresu dat
     */
    async exportDateRange(dateFrom, dateTo, additionalFilters = {}) {
        console.log('[ExportManager] Export date range:', dateFrom, dateTo);

        const params = {
            date_from: dateFrom,
            date_to: dateTo,
            ...additionalFilters
        };

        await this.exportWithCustomParams(params);
    }

    /**
     * Eksport wszystkich danych (bez filtrów)
     */
    async exportAll() {
        console.log('[ExportManager] Export all data...');

        const params = {
            // Brak date_from i date_to - pobierze wszystkie dane
        };

        await this.exportWithCustomParams(params);
    }

    /**
     * Eksport z konkretnymi filtrami
     */
    async exportWithFilters(filters) {
        console.log('[ExportManager] Export with specific filters:', filters);

        const dateRange = this.getCurrentDateRange();
        const params = {
            date_from: dateRange.date_from,
            date_to: dateRange.date_to
        };

        // Dodaj filtry
        for (const [key, values] of Object.entries(filters)) {
            if (values && Array.isArray(values) && values.length > 0) {
                values.forEach(value => {
                    if (value && value.trim()) {
                        params[`filter_${key}`] = value.trim();
                    }
                });
            }
        }

        await this.exportWithCustomParams(params);
    }

    /**
     * NOWA METODA - Anulowanie eksportu
     */
    cancelExport() {
        console.log('[ExportManager] Canceling export...');
        this.isExporting = false;
        this.setExportingState(false);
    }

    /**
     * NOWA METODA - Obsługa zmiany trybu fullscreen
     */
    onFullscreenChange(isFullscreen) {
        console.log('[ExportManager] Fullscreen mode changed:', isFullscreen);

        // Dostosuj UI do trybu fullscreen
        this.adaptExportUIToFullscreen(isFullscreen);

        // Aktualizuj pozycję notyfikacji
        this.updateNotificationPosition(isFullscreen);
    }

    /**
     * NOWA METODA - Dostosowanie UI eksportu do fullscreen
     */
    adaptExportUIToFullscreen(isFullscreen) {
        if (!this.exportButton) return;

        if (isFullscreen) {
            // W fullscreen - przycisk eksportu jest ukryty w normalnym UI
            // Można dodać floating action button lub przycisk w fullscreen header
            this.createFullscreenExportButton();
        } else {
            // W normalnym trybie - usuń floating button jeśli istnieje
            this.removeFullscreenExportButton();
        }
    }

    /**
     * NOWA METODA - Utworzenie floating przycisku eksportu w fullscreen
     */
    createFullscreenExportButton() {
        // POPRAWKA: Przycisk eksportu jest zarządzany przez HTML/CSS, nie tworzymy go dynamicznie
        console.log('[FullscreenManager] Export button managed by static HTML');
    }

    /**
     * NOWA METODA - Usunięcie floating przycisku eksportu
     */
    removeFullscreenExportButton() {
        // POPRAWKA: Usuń stary floating button jeśli istnieje (dla kompatybilności)
        const floatingBtn = document.getElementById('fullscreenFloatingExportBtn');
        if (floatingBtn) {
            floatingBtn.remove();
            console.log('[FullscreenManager] Old floating export button removed');
        }
    }

    /**
     * NOWA METODA - Aktualizacja pozycji notyfikacji
     */
    updateNotificationPosition(isFullscreen) {
        // Możemy dostosować pozycję notyfikacji w fullscreen
        // Na razie używamy standardowych alert'ów, ale można rozszerzyć
        console.log('[ExportManager] Notification position updated for fullscreen:', isFullscreen);
    }

    /**
     * NOWA METODA - Sprawdzenie czy jesteśmy w trybie fullscreen
     */
    isInFullscreenMode() {
        if (window.fullscreenManager && typeof window.fullscreenManager.isFullscreenActive === 'function') {
            return window.fullscreenManager.isFullscreenActive();
        }
        return false;
    }

    /**
     * NOWA METODA - Walidacja stanu managera
     */
    validateState() {
        const issues = [];

        if (!this.exportButton) {
            issues.push('Missing export button element');
        }

        if (!window.reportsManager) {
            issues.push('ReportsManager not available');
        }

        // NOWE: Sprawdź czy FullscreenManager jest dostępny
        if (!window.fullscreenManager) {
            issues.push('FullscreenManager not available');
        }

        return {
            isValid: issues.length === 0,
            issues: issues
        };
    }

    /**
     * Publiczne API
     */

    // Główny eksport (używany przez ReportsManager)
    async exportToExcelMain() {
        await this.exportToExcelWithValidation();
    }

    // Eksport z podglądem (można dodać jako opcję)
    async exportWithPreviewMain() {
        await this.exportWithPreview();
    }

    // Sprawdzenie stanu
    isExportInProgress() {
        return this.isExporting;
    }

    // Informacje o eksporcie
    getExportStatus() {
        return {
            isExporting: this.isExporting,
            canExport: this.canExport(),
            exportInfo: this.getExportInfo(),
            lastExportTime: this.lastExportTime
        };
    }

    // Debug info - POPRAWKA: Rozszerzone informacje
    getDebugInfo() {
        const validation = this.validateState();

        return {
            isExporting: this.isExporting,
            lastExportTime: this.lastExportTime,
            exportInfo: this.getExportInfo(),
            currentData: this.getCurrentData().length,
            currentFilters: this.getCurrentFilters(),
            validation: validation,
            isFullscreen: this.isInFullscreenMode(), // NOWE
            elements: {
                exportButton: !!this.exportButton,
                fullscreenExportBtn: !!document.getElementById('fullscreenExportBtn')
            },
            // NOWE: Informacje o fullscreen
            fullscreenManager: {
                available: !!window.fullscreenManager,
                active: this.isInFullscreenMode()
            }
        };
    }

    /**
     * NOWA METODA - Publiczne API dla fullscreen
     */

    // Aktywuj tryb fullscreen
    activateFullscreenMode() {
        this.adaptExportUIToFullscreen(true);
    }

    // Deaktywuj tryb fullscreen
    deactivateFullscreenMode() {
        this.adaptExportUIToFullscreen(false);
    }

    // Sprawdź czy jest w trybie fullscreen
    isFullscreenActive() {
        return this.isInFullscreenMode();
    }

    // Eksport z informacją o fullscreen
    async exportWithFullscreenInfo() {
        console.log('[ExportManager] Export with fullscreen info, mode:', this.isInFullscreenMode());
        await this.exportToExcel();
    }

    /**
     * NOWA METODA - Cleanup przy wyjściu z fullscreen
     */
    cleanupFullscreenElements() {
        this.removeFullscreenExportButton();

        // Usuń wszystkie fullscreen notifications
        const notifications = document.querySelectorAll('.fullscreen-notification');
        notifications.forEach(notification => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        });

        console.log('[ExportManager] Fullscreen elements cleaned up');
    }

    /**
     * ZAKTUALIZOWANA METODA - Opcje eksportu z Routimo
     */
    getExportOptions() {
        return {
            excel: {
                available: true,
                label: 'Excel',
                icon: 'fas fa-file-excel',
                description: 'Pełny raport wszystkich danych'
            },
            routimo: {
                available: true,
                label: 'Routimo',
                icon: 'fas fa-route',
                description: 'Excel dla planowania tras (wszystkie aktywne zamówienia)' // ZMIANA OPISU
            }
        };
    }

    /**
     * NOWA METODA - Sprawdzenie liczby zamówień dla Routimo
     */
    getRoutimoOrdersCount() {
        const currentData = this.getCurrentData();
        if (!currentData || currentData.length === 0) {
            return 0;
        }

        // ZMIANA: Licz wszystkie OPRÓCZ wykluczonych statusów
        const excludedStatusNames = [
            'Zamówienie anulowane',
            'Odebrane',
            'Dostarczona - transport WoodPower',
            'Dostarczona - kurier',
            'Czeka na odbiór osobisty',
            'Wysłane - transport WoodPower',
            'Wysłane - kurier'
        ];

        return currentData.filter(record =>
            !excludedStatusNames.includes(record.current_status)
        ).length;
    }


    /**
     * NOWA METODA - Debug info dla Routimo
     */
    getRoutimoDebugInfo() {
        const currentData = this.getCurrentData();
        const routimoOrdersCount = this.getRoutimoOrdersCount();

        return {
            totalRecords: currentData.length,
            routimoRecords: routimoOrdersCount,
            routimoAvailable: routimoOrdersCount > 0,
            excludedStatuses: [ // ZMIANA: pokaż wykluczone zamiast wspieranych
                'Zamówienie anulowane',
                'Odebrane',
                'Dostarczona - transport WoodPower',
                'Dostarczona - kurier',
                'Czeka na odbiór osobisty',
                'Wysłane - transport WoodPower',
                'Wysłane - kurier'
            ]
        };
    }
}

// Export dla global scope
window.ExportManager = ExportManager;

class BootstrapDropdownIntegration {
    constructor(exportManager) {
        this.exportManager = exportManager;
        this.dropdownInstances = new Map();

        console.log('[BootstrapDropdownIntegration] Initialized');
    }

    /**
     * Inicjalizacja Bootstrap dropdown'ów
     */
    init() {
        console.log('[BootstrapDropdownIntegration] Starting initialization...');

        // Sprawdź czy Bootstrap jest dostępny
        if (typeof bootstrap === 'undefined') {
            console.warn('[BootstrapDropdownIntegration] Bootstrap not found, using manual implementation');
            this.initManualDropdowns();
            return;
        }

        this.initBootstrapDropdowns();

        console.log('[BootstrapDropdownIntegration] Initialization complete');
    }

    /**
     * NOWA METODA - Inicjalizacja Bootstrap dropdown'ów
     */
    initBootstrapDropdowns() {
        const dropdownElements = document.querySelectorAll('.export-dropdown .dropdown-toggle');

        dropdownElements.forEach(element => {
            try {
                // Disable Bootstrap auto-initialization
                element.setAttribute('data-bs-auto-close', 'true');

                // Jeśli Bootstrap Dropdown jest dostępny, użyj go
                if (bootstrap.Dropdown) {
                    new bootstrap.Dropdown(element);
                }
            } catch (error) {
                console.warn('[ExportManager] Bootstrap dropdown initialization failed:', error);
            }
        });
    }

    /**
     * Ręczna implementacja dropdown'ów (fallback)
     */
    initManualDropdowns() {
        const dropdownToggles = document.querySelectorAll('.export-dropdown .dropdown-toggle');

        dropdownToggles.forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();

                const dropdown = toggle.closest('.export-dropdown');
                const menu = dropdown.querySelector('.dropdown-menu');

                // Zamknij inne dropdown'y
                this.closeAllDropdowns();

                // Toggle current dropdown
                const isOpen = menu.classList.contains('show');
                if (!isOpen) {
                    this.openDropdown(dropdown, toggle, menu);
                }
            });
        });

        // Zamknij dropdown przy kliknięciu poza nim
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.export-dropdown')) {
                this.closeAllDropdowns();
            }
        });

        // Obsługa ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllDropdowns();
            }
        });
    }

    /**
     * Otwórz dropdown
     */
    openDropdown(dropdown, toggle, menu) {
        toggle.setAttribute('aria-expanded', 'true');
        menu.classList.add('show');

        // Dostosuj pozycję w fullscreen
        if (dropdown.closest('.fullscreen-mode')) {
            this.adjustDropdownPositionFullscreen(menu);
        }

        this.onDropdownShow({ target: toggle });
    }

    /**
     * Zamknij dropdown
     */
    closeDropdown(dropdown, toggle, menu) {
        toggle.setAttribute('aria-expanded', 'false');
        menu.classList.remove('show');

        this.onDropdownHide({ target: toggle });
    }

    /**
     * Zamknij wszystkie dropdown'y
     */
    closeAllDropdowns() {
        const dropdowns = document.querySelectorAll('.export-dropdown');

        dropdowns.forEach(dropdown => {
            const toggle = dropdown.querySelector('.dropdown-toggle');
            const menu = dropdown.querySelector('.dropdown-menu');

            if (toggle && menu && menu.classList.contains('show')) {
                this.closeDropdown(dropdown, toggle, menu);
            }
        });
    }

    /**
     * Dostosowanie pozycji dropdown'a w fullscreen
     */
    adjustDropdownPositionFullscreen(menu) {
        // W fullscreen dropdown pojawia się nad przyciskiem
        menu.style.position = 'absolute';
        menu.style.top = 'auto';
        menu.style.bottom = '100%';
        menu.style.left = '0';
        menu.style.marginBottom = '2px';
        menu.style.zIndex = '1002';
    }

    /**
     * Event handler - dropdown pokazany
     */
    onDropdownShow(event) {
        const toggle = event.target;
        const dropdown = toggle.closest('.export-dropdown');

        console.log('[BootstrapDropdownIntegration] Dropdown shown:', toggle.id);

        // Sprawdź czy jesteśmy w fullscreen
        if (dropdown.closest('.fullscreen-mode')) {
            const menu = dropdown.querySelector('.dropdown-menu');
            this.adjustDropdownPositionFullscreen(menu);
        }
    }

    /**
     * Event handler - dropdown ukryty
     */
    onDropdownHide(event) {
        const toggle = event.target;

        console.log('[BootstrapDropdownIntegration] Dropdown hidden:', toggle.id);
    }

    /**
     * Zarządzanie stanem podczas eksportu
     */
    updateDropdownDuringExport(isExporting, exportType) {
        const dropdowns = document.querySelectorAll('.export-dropdown');

        dropdowns.forEach(dropdown => {
            const toggle = dropdown.querySelector('.dropdown-toggle');

            if (!toggle) return;

            if (isExporting) {
                // Zablokuj dropdown podczas eksportu
                toggle.disabled = true;
                dropdown.classList.add('exporting');

                // Zamknij jeśli jest otwarty
                const menu = dropdown.querySelector('.dropdown-menu');
                if (menu.classList.contains('show')) {
                    this.closeDropdown(dropdown, toggle, menu);
                }

            } else {
                // Odblokuj dropdown po eksporcie
                toggle.disabled = false;
                dropdown.classList.remove('exporting');
            }
        });
    }

    /**
     * Cleanup przy niszczeniu
     */
    destroy() {
        // Usuń Bootstrap instances
        this.dropdownInstances.forEach((instance, elementId) => {
            try {
                instance.dispose();
            } catch (error) {
                console.error('[BootstrapDropdownIntegration] Error disposing dropdown:', elementId, error);
            }
        });

        this.dropdownInstances.clear();

        console.log('[BootstrapDropdownIntegration] Destroyed');
    }

    /**
     * Debug info
     */
    getDebugInfo() {
        return {
            bootstrapAvailable: typeof bootstrap !== 'undefined',
            dropdownInstancesCount: this.dropdownInstances.size,
            dropdownInstances: Array.from(this.dropdownInstances.keys())
        };
    }
}

// Integracja z ExportManager
if (window.ExportManager) {
    const originalInit = window.ExportManager.prototype.init;

    window.ExportManager.prototype.init = function () {
        // Wywołaj oryginalną init
        originalInit.call(this);

        // Dodaj Bootstrap dropdown integration
        this.dropdownIntegration = new BootstrapDropdownIntegration(this);
        this.dropdownIntegration.init();

        console.log('[ExportManager] Bootstrap dropdown integration added');
    };

    // Dodaj metodę do zarządzania dropdown'ami podczas eksportu
    const originalSetExportingState = window.ExportManager.prototype.setExportingState;

    window.ExportManager.prototype.setExportingState = function (isExporting, exportType = 'excel') {
        // Wywołaj oryginalną metodę
        originalSetExportingState.call(this, isExporting, exportType);

        // Aktualizuj dropdown'y
        if (this.dropdownIntegration) {
            this.dropdownIntegration.updateDropdownDuringExport(isExporting, exportType);
        }
    };
}

// Export dla global scope
window.BootstrapDropdownIntegration = BootstrapDropdownIntegration;