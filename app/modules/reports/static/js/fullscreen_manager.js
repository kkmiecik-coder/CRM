// modules/reports/static/js/fullscreen_manager.js
/**
 * Manager trybu pełnego ekranu dla modułu Reports
 * Odpowiedzialny za przełączanie między trybem normalnym a pełnym ekranem
 */

class FullscreenManager {
    constructor() {
        this.isFullscreen = false;
        this.originalParent = null;
        this.fullscreenContainer = null;
        this.fullscreenToggle = null;
        this.elementsToMove = [];
        this.elementsToHide = [];
        this.savedState = {};

        // Preferencje użytkownika
        this.storageKey = 'reports_fullscreen_mode';

        console.log('[FullscreenManager] Initialized');
    }

    /**
     * Inicjalizacja managera
     */
    init() {
        console.log('[FullscreenManager] Starting initialization...');

        this.cacheElements();
        this.setupEventListeners();
        this.createFullscreenContainer();
        this.loadUserPreferences();

        console.log('[FullscreenManager] Initialization complete');
    }

    /**
     * Cache elementów DOM
     */
    cacheElements() {
        this.fullscreenToggle = document.getElementById('fullscreenToggle');

        // Elementy do przeniesienia w trybie fullscreen
        this.elementsToMove = [
            {
                element: document.querySelector('.stats-container'),
                target: 'stats'
            },
            {
                element: document.querySelector('.column-filters'),
                target: 'filters'
            },
            {
                element: document.querySelector('.reports-table-container'),
                target: 'table'
            }
        ];

        // Elementy do ukrycia w trybie fullscreen
        this.elementsToHide = [
            document.querySelector('.reports-header'),
            document.querySelector('.reports-controls'),
            document.querySelector('aside.sidebar'), // Sidebar
            document.querySelector('.main-content > h1'), // Tytuł strony jeśli istnieje
        ];

        console.log('[FullscreenManager] Elements cached');
    }

    /**
     * Ustawienie event listenerów
     */
    setupEventListeners() {
        // Przycisk toggle fullscreen
        if (this.fullscreenToggle) {
            this.fullscreenToggle.addEventListener('click', () => {
                this.toggle();
            });
        }

        // Klawisz ESC - wyjście z fullscreen
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isFullscreen) {
                this.exitFullscreen();
            }
        });

        // Zapobieganie przypadkowemu zamknięciu
        window.addEventListener('beforeunload', () => {
            this.saveUserPreferences();
        });

        console.log('[FullscreenManager] Event listeners setup complete');
    }

    /**
     * Utworzenie kontenera dla trybu fullscreen
     */
    createFullscreenContainer() {
        this.fullscreenContainer = document.createElement('div');
        this.fullscreenContainer.id = 'fullscreenContainer';
        this.fullscreenContainer.className = 'fullscreen-container hidden';

        // Struktura kontenera fullscreen
        this.fullscreenContainer.innerHTML = `
            <div class="fullscreen-header">
                <div class="fullscreen-title">
                    <i class="fas fa-chart-line"></i>
                    Raporty - Tryb pełnego ekranu
                </div>
                <button id="fullscreenExit" class="btn btn-outline-secondary btn-sm">
                    <i class="fas fa-compress"></i>
                    Wyjdź
                </button>
            </div>
            <div class="fullscreen-stats-container">
                <!-- Statystyki zostaną przeniesione tutaj -->
            </div>
            <div class="fullscreen-filters-container">
                <!-- Filtry zostaną przeniesione tutaj -->
            </div>
            <div class="fullscreen-table-container">
                <!-- Tabela zostanie przeniesiona tutaj -->
            </div>
        `;

        // Dodaj do body
        document.body.appendChild(this.fullscreenContainer);

        // Event listener dla przycisku wyjścia
        const exitBtn = this.fullscreenContainer.querySelector('#fullscreenExit');
        if (exitBtn) {
            exitBtn.addEventListener('click', () => {
                this.exitFullscreen();
            });
        }

        console.log('[FullscreenManager] Fullscreen container created');
    }

    /**
     * Przełączenie między trybami
     */
    toggle() {
        if (this.isFullscreen) {
            this.exitFullscreen();
        } else {
            this.enterFullscreen();
        }
    }

    /**
    * Wejście w tryb pełnego ekranu
    */
    enterFullscreen() {
        console.log('[FullscreenManager] Entering fullscreen mode...');

        if (this.isFullscreen) {
            console.log('[FullscreenManager] Already in fullscreen mode');
            return;
        }

        // Zapisz oryginalnych rodziców elementów
        this.saveOriginalState();

        // Przenieś elementy do fullscreen container
        this.moveElementsToFullscreen();

        // Ukryj niepotrzebne elementy
        this.hideElements();

        // Pokaż fullscreen container
        this.fullscreenContainer.classList.remove('hidden');
        this.fullscreenContainer.classList.add('active');

        // Dodaj klasę do body
        document.body.classList.add('fullscreen-mode');

        // Ustaw flagę PRZED aktualizacją przycisku
        this.isFullscreen = true;

        // Zaktualizuj przycisk toggle
        this.updateToggleButton();

        // Powiadom inne managery
        this.notifyManagersAboutFullscreen(true);

        // Zapisz preferencje
        this.saveUserPreferences();

        console.log('[FullscreenManager] Fullscreen mode activated');
    }


    /**
    * Wyjście z trybu pełnego ekranu
    */
    exitFullscreen() {
        console.log('[FullscreenManager] Exiting fullscreen mode...');

        if (!this.isFullscreen) {
            console.log('[FullscreenManager] Not in fullscreen mode');
            return;
        }

        // Przywróć elementy do oryginalnych miejsc
        this.restoreElementsFromFullscreen();

        // Pokaż ukryte elementy
        this.showElements();

        // Ukryj fullscreen container
        this.fullscreenContainer.classList.remove('active');
        this.fullscreenContainer.classList.add('hidden');

        // Usuń klasę z body
        document.body.classList.remove('fullscreen-mode');

        // Ustaw flagę PRZED aktualizacją przycisku
        this.isFullscreen = false;

        // Zaktualizuj przycisk toggle
        this.updateToggleButton();

        // Powiadom inne managery
        this.notifyManagersAboutFullscreen(false);

        // Zapisz preferencje
        this.saveUserPreferences();

        console.log('[FullscreenManager] Fullscreen mode deactivated');
    }

    /**
     * Zapisanie oryginalnego stanu elementów
     */
    saveOriginalState() {
        this.savedState = {
            parents: {},
            nextSiblings: {}
        };

        this.elementsToMove.forEach((item, index) => {
            if (item.element) {
                this.savedState.parents[index] = item.element.parentNode;
                this.savedState.nextSiblings[index] = item.element.nextSibling;
            }
        });

        console.log('[FullscreenManager] Original state saved');
    }

    /**
     * Przeniesienie elementów do fullscreen container
     */
    moveElementsToFullscreen() {
        this.elementsToMove.forEach((item, index) => {
            if (!item.element) return;

            // Znajdź docelowy kontener
            let targetContainer;
            switch (item.target) {
                case 'stats':
                    targetContainer = this.fullscreenContainer.querySelector('.fullscreen-stats-container');
                    break;
                case 'filters':
                    targetContainer = this.fullscreenContainer.querySelector('.fullscreen-filters-container');
                    break;
                case 'table':
                    targetContainer = this.fullscreenContainer.querySelector('.fullscreen-table-container');
                    break;
                default:
                    console.warn(`[FullscreenManager] Unknown target: ${item.target}`);
                    return;
            }

            if (targetContainer) {
                // Dodaj klasy fullscreen
                item.element.classList.add('fullscreen-mode');

                // Specjalne klasy dla poszczególnych elementów
                if (item.target === 'stats') {
                    item.element.classList.add('compact');
                }
                if (item.target === 'filters') {
                    item.element.classList.add('compact');
                }
                if (item.target === 'table') {
                    item.element.classList.add('fullscreen');
                }

                // Przenieś element
                targetContainer.appendChild(item.element);
            }
        });

        console.log('[FullscreenManager] Elements moved to fullscreen container');
    }

    /**
     * Przywrócenie elementów z fullscreen container
     */
    restoreElementsFromFullscreen() {
        this.elementsToMove.forEach((item, index) => {
            if (!item.element) return;

            // Usuń klasy fullscreen
            item.element.classList.remove('fullscreen-mode', 'compact', 'fullscreen');

            // Przywróć do oryginalnego miejsca
            const originalParent = this.savedState.parents[index];
            const nextSibling = this.savedState.nextSiblings[index];

            if (originalParent) {
                if (nextSibling) {
                    originalParent.insertBefore(item.element, nextSibling);
                } else {
                    originalParent.appendChild(item.element);
                }
            }
        });

        console.log('[FullscreenManager] Elements restored from fullscreen container');
    }

    /**
     * Ukrycie elementów w trybie fullscreen
     */
    hideElements() {
        this.elementsToHide.forEach(element => {
            if (element) {
                element.classList.add('hidden-in-fullscreen');
            }
        });

        console.log('[FullscreenManager] Elements hidden');
    }

    /**
     * Pokazanie ukrytych elementów
     */
    showElements() {
        this.elementsToHide.forEach(element => {
            if (element) {
                element.classList.remove('hidden-in-fullscreen');
            }
        });

        console.log('[FullscreenManager] Elements shown');
    }

    /**
     * Aktualizacja przycisku toggle
     */
    updateToggleButton() {
        if (!this.fullscreenToggle) return;

        const icon = this.fullscreenToggle.querySelector('i');
        const text = this.fullscreenToggle.querySelector('.fullscreen-text');

        if (this.isFullscreen) {
            if (icon) {
                icon.className = 'fas fa-compress';
            }
            if (text) {
                text.textContent = 'Wyjdź';
            }
            this.fullscreenToggle.classList.add('active');
        } else {
            if (icon) {
                icon.className = 'fas fa-expand';
            }
            if (text) {
                text.textContent = 'Pełny ekran';
            }
            this.fullscreenToggle.classList.remove('active');
        }

        console.log('[FullscreenManager] Toggle button updated, isFullscreen:', this.isFullscreen);
    }

    /**
     * Powiadomienie innych managerów o zmianie trybu
     */
    notifyManagersAboutFullscreen(isFullscreen) {
        // Powiadom ReportsManager
        if (window.reportsManager && typeof window.reportsManager.onFullscreenChange === 'function') {
            window.reportsManager.onFullscreenChange(isFullscreen);
        }

        // Powiadom TableManager
        if (window.tableManager && typeof window.tableManager.onFullscreenChange === 'function') {
            window.tableManager.onFullscreenChange(isFullscreen);
        }

        // Powiadom ExportManager
        if (window.exportManager && typeof window.exportManager.onFullscreenChange === 'function') {
            window.exportManager.onFullscreenChange(isFullscreen);
        }

        console.log('[FullscreenManager] Managers notified about fullscreen change:', isFullscreen);
    }

    /**
     * Zapisanie preferencji użytkownika
     */
    saveUserPreferences() {
        try {
            const preferences = {
                isFullscreen: this.isFullscreen,
                lastUpdated: new Date().toISOString()
            };

            localStorage.setItem(this.storageKey, JSON.stringify(preferences));
            console.log('[FullscreenManager] User preferences saved');
        } catch (error) {
            console.warn('[FullscreenManager] Failed to save preferences:', error);
        }
    }

    /**
     * Ładowanie preferencji użytkownika
     */
    loadUserPreferences() {
        try {
            const stored = localStorage.getItem(this.storageKey);
            if (stored) {
                const preferences = JSON.parse(stored);

                // Nie przywracaj automatycznie trybu fullscreen przy ładowaniu strony
                // Użytkownik musi świadomie go aktywować
                console.log('[FullscreenManager] User preferences loaded:', preferences);
            }
        } catch (error) {
            console.warn('[FullscreenManager] Failed to load preferences:', error);
        }
    }

    /**
     * Sprawdzenie czy tryb fullscreen jest aktywny
     */
    isFullscreenActive() {
        return this.isFullscreen;
    }

    /**
     * Wymuszenie odświeżenia layoutu po zmianie trybu
     */
    refreshLayout() {
        if (this.isFullscreen) {
            // POPRAWKA: Odśwież layout bez resetowania scroll
            setTimeout(() => {
                // Nie używamy display: none, który resetuje scroll
                const tableWrapper = document.querySelector('.fullscreen-table-container .table-wrapper');
                if (tableWrapper) {
                    // Wymusz repaint bez resetowania pozycji scroll
                    tableWrapper.style.transform = 'translateZ(0)';
                    requestAnimationFrame(() => {
                        tableWrapper.style.transform = '';
                    });
                }

                // Soft resize event
                window.dispatchEvent(new Event('resize'));
            }, 50);
        }
    }

    /**
     * NOWA METODA - Zapobieganie resetowaniu scroll w fullscreen
     */
    preserveScrollPosition() {
        if (!this.isFullscreen) return;

        const tableWrapper = document.querySelector('.fullscreen-table-container .table-wrapper');
        if (tableWrapper) {
            // Zapisz pozycję scroll
            const scrollTop = tableWrapper.scrollTop;
            const scrollLeft = tableWrapper.scrollLeft;

            // Przywróć pozycję po micro-delay
            requestAnimationFrame(() => {
                tableWrapper.scrollTop = scrollTop;
                tableWrapper.scrollLeft = scrollLeft;
            });
        }
    }

    /**
     * NOWA METODA - Obsługa resize z zachowaniem scroll
     */
    handleFullscreenResize() {
        if (this.isFullscreen) {
            this.preserveScrollPosition();

            // Delikatne odświeżenie bez resetowania
            setTimeout(() => {
                this.refreshLayout();
            }, 100);
        }
    }

    /**
     * Obsługa resize okna
     */
    handleWindowResize() {
        if (this.isFullscreen) {
            this.refreshLayout();
        }
    }

    /**
     * Wyłączenie trybu fullscreen programowo (np. przy błędach)
     */
    forceExitFullscreen() {
        if (this.isFullscreen) {
            console.log('[FullscreenManager] Force exiting fullscreen mode...');
            this.exitFullscreen();
        }
    }

    /**
     * Sprawdzenie dostępności funkcji
     */
    checkCompatibility() {
        const issues = [];

        if (!this.fullscreenToggle) {
            issues.push('Fullscreen toggle button not found');
        }

        if (this.elementsToMove.some(item => !item.element)) {
            issues.push('Some elements to move are missing');
        }

        return {
            isCompatible: issues.length === 0,
            issues: issues
        };
    }

    /**
     * Publiczne API
     */

    // Aktywuj tryb fullscreen
    activate() {
        this.enterFullscreen();
    }

    // Deaktywuj tryb fullscreen
    deactivate() {
        this.exitFullscreen();
    }

    // Przełącz tryb
    toggleMode() {
        this.toggle();
    }

    // Pobierz stan
    getState() {
        return {
            isFullscreen: this.isFullscreen,
            isCompatible: this.checkCompatibility().isCompatible
        };
    }

    /**
     * Debug info
     */
    getDebugInfo() {
        const compatibility = this.checkCompatibility();

        return {
            isFullscreen: this.isFullscreen,
            elementsToMove: this.elementsToMove.map(item => ({
                target: item.target,
                found: !!item.element
            })),
            elementsToHide: this.elementsToHide.map(el => !!el),
            compatibility: compatibility,
            fullscreenContainer: {
                exists: !!this.fullscreenContainer,
                isActive: this.fullscreenContainer ? this.fullscreenContainer.classList.contains('active') : false
            },
            savedState: Object.keys(this.savedState).length > 0,
            userPreferences: this.storageKey in localStorage
        };
    }
}

// Export dla global scope
window.FullscreenManager = FullscreenManager;