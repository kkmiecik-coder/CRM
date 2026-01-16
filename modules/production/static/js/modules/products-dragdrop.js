/**
 * products-dragdrop.js
 * ========================================================================
 * 
 * Kompletna implementacja systemu Drag & Drop dla modułu produktów
 * 
 * Funkcjonalności:
 * - HTML5 Drag & Drop API z ghost elementem
 * - Insertion line podczas przeciągania
 * - Optimistic updates z rollback przy błędzie
 * - Animacje success (zielone mruganie 2x) i error (czerwone mruganie 2x)
 * - Integracja z toast systemem z shared_services.js
 * - Przeliczanie priorytetów według nowej kolejności
 * - Obsługa błędów z powrotem elementu na miejsce
 * 
 * Algorytm: Wstawienie elementu w nowe miejsce + przesunięcie reszty
 * Przykład: [1,2,3,4,5,6] -> przeciągnij 5 między 2 a 3 -> [1,2,5,3,4,6]
 * 
 * Autor: Konrad Kmiecik
 * Wersja: 1.0 - Krok 5 restrukturyzacji
 * Data: 2025-01-15
 * ========================================================================
 */

class ProductsDragDrop {
    constructor(productsModule) {
        this.productsModule = productsModule;
        this.enabled = false;
        
        // Drag state
        this.dragState = {
            isDragging: false,
            draggedElement: null,
            draggedProductId: null,
            draggedProductData: null,
            originalPosition: null,
            ghostElement: null,
            insertionLine: null,
            dropTargetElement: null,
            originalProducts: [],
            pendingUpdate: false
        };
        
        // DOM references
        this.elements = {
            container: null,
            viewport: null
        };
        
        // Performance optimization flags
        this.performanceFlags = {
            isThrottling: false,
            rafId: null,
            lastGhostUpdate: 0,
            ghostUpdateThrottle: 16 // ~60fps
        };
        
        console.log('[ProductsDragDrop] Initialized');
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    initialize() {
        try {
            // Get DOM references
            this.elements.container = document.getElementById('virtual-scroll-container');
            this.elements.viewport = document.getElementById('virtual-scroll-viewport');
            
            if (!this.elements.container || !this.elements.viewport) {
                throw new Error('Required DOM elements not found');
            }
            
            // Get toast system reference
            if (window.ProductionShared?.toastSystem) {
                this.toastSystem = window.ProductionShared.toastSystem;
                console.log('[ProductsDragDrop] Toast system found and connected');
            } else {
                console.warn('[ProductsDragDrop] Toast system not found, creating fallback');
                this.createFallbackToastSystem();
            }
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Create insertion line element
            this.createInsertionLine();
            
            this.enabled = true;
            console.log('[ProductsDragDrop] Successfully initialized');
            return true;
            
        } catch (error) {
            console.error('[ProductsDragDrop] Failed to initialize:', error);
            return false;
        }
    }

    setupEventListeners() {
        // Global document listeners for drag events
        document.addEventListener('dragstart', this.onDragStart.bind(this));
        document.addEventListener('dragend', this.onDragEnd.bind(this));
        document.addEventListener('dragover', this.onDragOver.bind(this));
        document.addEventListener('drop', this.onDrop.bind(this));

        // Prevent default drag behavior on container
        this.elements.container.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });

        console.log('[ProductsDragDrop] Event listeners setup complete');
    }

    createInsertionLine() {
        this.dragState.insertionLine = document.createElement('div');
        this.dragState.insertionLine.className = 'drag-insertion-line';
        this.dragState.insertionLine.style.cssText = `
            position: absolute;
            left: 0;
            right: 0;
            height: 3px;
            background-color: #F00B38;
            border-radius: 2px;
            display: none;
            z-index: 1000;
            box-shadow: 0 0 4px rgba(240, 11, 56, 0.5);
            pointer-events: none;
        `;
        document.body.appendChild(this.dragState.insertionLine);
        
        // Add custom CSS for better animations (2x flash)
        this.addCustomAnimationStyles();
    }
    
    addCustomAnimationStyles() {
        if (document.getElementById('products-dragdrop-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'products-dragdrop-styles';
        styles.textContent = `
            /* Override default animations to flash 2 times - NOWE KLASY */
            .prod_list-product-row.update-success {
                animation: successFlash2x 1.2s ease !important;
            }
        
            .prod_list-product-row.update-error {
                animation: errorFlash2x 1.2s ease !important;
            }
        
            /* Zachowaj kompatybilność ze starymi klasami */
            .product-row.update-success {
                animation: successFlash2x 1.2s ease !important;
            }
        
            .product-row.update-error {
                animation: errorFlash2x 1.2s ease !important;
            }
        
            @keyframes successFlash2x {
                0%, 100% { background: white; }
                15% { background: rgba(40, 167, 69, 0.4); }
                30% { background: white; }
                45% { background: rgba(40, 167, 69, 0.4); }
                60% { background: white; }
            }
        
            @keyframes errorFlash2x {
                0%, 100% { background: white; }
                15% { background: rgba(220, 53, 69, 0.4); }
                30% { background: white; }
                45% { background: rgba(220, 53, 69, 0.4); }
                60% { background: white; }
            }
        
            /* Style dla nowych klas podczas przeciągania */
            .prod_list-product-row.dragging {
                opacity: 0.5;
                z-index: 100;
            }
        
            .prod_list-product-row.updating {
                position: relative;
            }
        
            .prod_list-product-row.updating::after {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(59, 130, 246, 0.1);
                border-radius: 8px;
                animation: pulse 1.5s infinite;
            }
        
            @keyframes pulse {
                0%, 100% { opacity: 0.1; }
                50% { opacity: 0.3; }
            }
        `;
        document.head.appendChild(styles);
    }

    createFallbackToastSystem() {
        this.toastSystem = {
            show: (message, type = 'info', duration = 4000) => {
                console.log(`[Toast ${type.toUpperCase()}] ${message}`);
                // Simple fallback - could create a basic toast implementation here
                if (type === 'error') {
                    alert(`Błąd: ${message}`);
                }
            }
        };
    }

    // ========================================================================
    // DRAG START
    // ========================================================================

    onDragStart(e) {
        // ZMIANA: użyj nowej klasy drag cell
        const dragHandle = e.target.closest('.prod_list-drag-cell');
        if (!dragHandle) return;

        // ZMIANA: użyj nowej klasy product row
        const productRow = dragHandle.closest('.prod_list-product-row');
        if (!productRow) return;

        e.stopPropagation();

        const productId = productRow.dataset.productId;
        if (!productId) return;

        console.log(`[ProductsDragDrop] Drag start: ${productId}`);

        // Store drag state
        this.dragState.isDragging = true;
        this.dragState.draggedElement = productRow;
        this.dragState.draggedProductId = productId;

        // Find product data
        const productData = this.productsModule.state.filteredProducts.find(p => p.id == productId);
        if (!productData) {
            console.error('[ProductsDragDrop] Product data not found for ID:', productId);
            console.log('[ProductsDragDrop] Available products:', this.productsModule.state.filteredProducts.map(p => ({ id: p.id, type: typeof p.id })));
            this.cancelDrag();
            return;
        }

        this.dragState.draggedProductData = productData;
        this.dragState.originalPosition = this.getProductPosition(productId);

        // Store original products order for rollback
        this.dragState.originalProducts = [...this.productsModule.state.filteredProducts];

        // Set drag data
        e.dataTransfer.setData('text/plain', productId);
        e.dataTransfer.effectAllowed = 'move';

        // Make original element semi-transparent
        productRow.style.opacity = '0.5';
        productRow.classList.add('dragging');

        // Create ghost element
        this.createGhostElement(productRow, e);

        // Hide default drag image
        const emptyImg = new Image();
        emptyImg.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAUEBAAAACwAAAAAAQABAAACAkQBADs=';
        e.dataTransfer.setDragImage(emptyImg, 0, 0);
    }

    createGhostElement(originalElement, e) {
        // Clone the element
        const ghost = originalElement.cloneNode(true);
        // ZMIANA: użyj nowej klasy dla ghost
        ghost.className = 'prod_list-product-row drag-ghost';
        ghost.style.cssText = `
            position: fixed;
            top: -1000px;
            left: -1000px;
            width: ${originalElement.offsetWidth}px;
            background: white;
            border: 2px solid #F00B38;
            border-radius: 6px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
            z-index: 9999;
            pointer-events: none;
            opacity: 0.95;
            transition: none;
            will-change: transform;
            transform: none !important;
        `;

        // ZMIANA: usuń checkbox z nową klasą
        const checkbox = ghost.querySelector('.prod_list-product-checkbox');
        if (checkbox) checkbox.remove();

        // Remove all event listeners from ghost
        const allElements = ghost.querySelectorAll('*');
        allElements.forEach(el => {
            el.removeAttribute('onclick');
            el.removeAttribute('onmouseover');
            el.removeAttribute('onmouseout');
        });

        document.body.appendChild(ghost);
        this.dragState.ghostElement = ghost;

        // Position ghost element initially
        this.updateGhostPosition(e);
    }

    updateGhostPosition(e) {
        if (!this.dragState.ghostElement) return;
        
        // Throttle updates for performance
        const now = performance.now();
        if (now - this.performanceFlags.lastGhostUpdate < this.performanceFlags.ghostUpdateThrottle) {
            return;
        }
        this.performanceFlags.lastGhostUpdate = now;
        
        // Cancel any pending animation frame
        if (this.performanceFlags.rafId) {
            cancelAnimationFrame(this.performanceFlags.rafId);
        }
        
        // Use requestAnimationFrame for smooth updates
        this.performanceFlags.rafId = requestAnimationFrame(() => {
            if (!this.dragState.ghostElement) return;
            
            const ghost = this.dragState.ghostElement;
            ghost.style.left = (e.clientX + 10) + 'px';
            ghost.style.top = (e.clientY - 20) + 'px';
        });
    }

    // ========================================================================
    // DRAG OVER & DROP TARGET
    // ========================================================================

    onDragOver(e) {
        if (!this.dragState.isDragging) return;
        
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        
        // Throttle dragover processing for performance
        if (this.performanceFlags.isThrottling) return;
        this.performanceFlags.isThrottling = true;
        
        requestAnimationFrame(() => {
            this.performanceFlags.isThrottling = false;
            
            if (!this.dragState.isDragging) return;
            
            // Update ghost position
            this.updateGhostPosition(e);
            
            // Find product row under cursor
            const productRow = this.findProductRowUnderCursor(e);
            if (!productRow || productRow === this.dragState.draggedElement) {
                this.hideInsertionLine();
                return;
            }
            
            // Calculate drop position
            const dropPosition = this.calculateDropPosition(e, productRow);
            this.showInsertionLine(productRow, dropPosition);
            
            this.dragState.dropTargetElement = productRow;
            this.dragState.dropPosition = dropPosition;
        });
    }

    findProductRowUnderCursor(e) {
        // ZMIANA: użyj nowej klasy product row
        const productRows = this.elements.viewport.querySelectorAll('.prod_list-product-row:not(.dragging)');

        for (const row of productRows) {
            const rect = row.getBoundingClientRect();
            if (e.clientY >= rect.top && e.clientY <= rect.bottom) {
                return row;
            }
        }

        return null;
    }

    calculateDropPosition(e, targetRow) {
        const rect = targetRow.getBoundingClientRect();
        const midpoint = rect.top + (rect.height / 2);
        
        return e.clientY < midpoint ? 'before' : 'after';
    }

    showInsertionLine(targetRow, position) {
        const rect = targetRow.getBoundingClientRect();
        const containerRect = this.elements.container.getBoundingClientRect();
        
        let top;
        if (position === 'before') {
            top = rect.top - 2;
        } else {
            top = rect.bottom - 1;
        }
        
        this.dragState.insertionLine.style.display = 'block';
        this.dragState.insertionLine.style.top = top + 'px';
        this.dragState.insertionLine.style.left = containerRect.left + 'px';
        this.dragState.insertionLine.style.width = containerRect.width + 'px';
    }

    hideInsertionLine() {
        this.dragState.insertionLine.style.display = 'none';
    }

    // ========================================================================
    // DROP HANDLING
    // ========================================================================

    onDrop(e) {
        if (!this.dragState.isDragging) return;
        
        e.preventDefault();
        e.stopPropagation();
        
        console.log('[ProductsDragDrop] Drop event');
        
        // Hide insertion line
        this.hideInsertionLine();
        
        // Calculate new position
        const newPosition = this.calculateNewPosition();
        if (newPosition === null || newPosition === this.dragState.originalPosition) {
            console.log('[ProductsDragDrop] No position change, canceling');
            this.cancelDrag();
            return;
        }
        
        console.log(`[ProductsDragDrop] Moving product from position ${this.dragState.originalPosition} to ${newPosition}`);
        
        // Perform optimistic update
        this.performOptimisticUpdate(newPosition);
        
        // Send to backend
        this.updatePriorityOnBackend(newPosition);
    }

    calculateNewPosition() {
        if (!this.dragState.dropTargetElement) {
            return null;
        }
        
        const targetProductId = this.dragState.dropTargetElement.dataset.productId;
        const targetPosition = this.getProductPosition(targetProductId);
        
        if (targetPosition === null) return null;
        
        // Calculate new position based on drop position
        if (this.dragState.dropPosition === 'before') {
            return targetPosition;
        } else {
            return targetPosition + 1;
        }
    }

    getProductPosition(productId) {
        const products = this.productsModule.state.filteredProducts;
        return products.findIndex(p => p.id == productId);
    }

    performOptimisticUpdate(newPosition) {
        console.log(`[ProductsDragDrop] Optimistic update: moving to position ${newPosition}`);
        
        const products = [...this.productsModule.state.filteredProducts];
        const draggedProduct = products.find(p => p.id == this.dragState.draggedProductId);
        
        if (!draggedProduct) {
            console.error('[ProductsDragDrop] Dragged product not found');
            this.handleDropError('Produkt nie został znaleziony');
            return;
        }
        
        // Remove from current position
        const currentIndex = products.findIndex(p => p.id == draggedProduct.id);
        products.splice(currentIndex, 1);
        
        // Insert at new position
        const insertIndex = newPosition > currentIndex ? newPosition - 1 : newPosition;
        products.splice(insertIndex, 0, draggedProduct);
        
        // Update state and re-render
        this.productsModule.state.filteredProducts = products;
        this.productsModule.renderProductsList();
        
        // Mark as updating
        this.dragState.pendingUpdate = true;
        this.showUpdatingState();
    }

    showUpdatingState() {
        const newProductRow = this.findProductRowById(this.dragState.draggedProductId);
        if (newProductRow) {
            newProductRow.classList.add('updating');
        }
    }

    // ========================================================================
    // BACKEND INTEGRATION
    // ========================================================================

    async updatePriorityOnBackend(newPosition) {
        try {
            // Calculate new priorities for all affected products
            const updatedProducts = this.calculateNewPriorities(newPosition);

            console.log('[ProductsDragDrop] Sending priority update to backend:', updatedProducts);

            // ZMIANA: Dostosuj format danych do nowego API
            const requestData = {
                products: updatedProducts.map(product => ({
                    id: product.id,
                    priority_rank: product.priority_rank
                }))
            };

            const response = await fetch('/production/api/update-priority', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(requestData)
            });

            const result = await response.json();

            if (result.success) {
                console.log('[ProductsDragDrop] Priority update successful');
                this.handleDropSuccess();
            } else {
                console.error('[ProductsDragDrop] Priority update failed:', result.error);
                this.handleDropError(result.error || 'Błąd aktualizacji priorytetu');
            }

        } catch (error) {
            console.error('[ProductsDragDrop] Backend request failed:', error);
            this.handleDropError('Błąd połączenia z serwerem');
        }
    }

    calculateNewPriorities(newPosition) {
        const products = this.productsModule.state.filteredProducts;
        const updatedProducts = [];

        products.forEach((product, index) => {
            const newPriorityRank = index + 1;

            if (product.priority_rank !== newPriorityRank) {
                updatedProducts.push({
                    id: product.id,
                    priority_rank: newPriorityRank
                });

                product.priority_rank = newPriorityRank;
            }
        });

        return updatedProducts;
    }

    // ========================================================================
    // SUCCESS/ERROR HANDLING
    // ========================================================================

    handleDropSuccess() {
        console.log('[ProductsDragDrop] Drop successful');
        
        const productRow = this.findProductRowById(this.dragState.draggedProductId);
        if (productRow) {
            // Remove updating state
            productRow.classList.remove('updating');
            
            // Show success animation (green flash 2x)
            this.showSuccessAnimation(productRow);
        }
        
        // Show success toast
        this.toastSystem?.show('Priorytet produktu został zaktualizowany', 'success', 3000);
        
        this.cleanupDrag();
    }

    handleDropError(errorMessage) {
        console.error('[ProductsDragDrop] Drop failed:', errorMessage);
        
        // Rollback to original state
        this.rollbackToOriginalState();
        
        const productRow = this.findProductRowById(this.dragState.draggedProductId);
        if (productRow) {
            // Remove updating state
            productRow.classList.remove('updating');
            
            // Show error animation (red flash 2x)
            this.showErrorAnimation(productRow);
        }
        
        // Show error toast
        this.toastSystem?.show(`Nie udało się zmienić priorytetu: ${errorMessage}`, 'error', 5000);
        
        this.cleanupDrag();
    }

    rollbackToOriginalState() {
        console.log('[ProductsDragDrop] Rolling back to original state');
        
        // Restore original products order
        this.productsModule.state.filteredProducts = [...this.dragState.originalProducts];
        
        // Re-render the list
        this.productsModule.renderProductsList();
    }

    showSuccessAnimation(element) {
        element.classList.add('update-success');
        
        // Remove class after animation completes (1.2s for 2x flash)
        setTimeout(() => {
            element.classList.remove('update-success');
        }, 1200);
    }

    showErrorAnimation(element) {
        element.classList.add('update-error', 'bounce-back');
        
        // Remove classes after animation completes (1.2s for 2x flash)
        setTimeout(() => {
            element.classList.remove('update-error', 'bounce-back');
        }, 1200);
    }

    // ========================================================================
    // DRAG END & CLEANUP
    // ========================================================================

    onDragEnd(e) {
        if (!this.dragState.isDragging) return;
        
        console.log('[ProductsDragDrop] Drag end');
        
        // If update is not pending, this was a cancelled drag
        if (!this.dragState.pendingUpdate) {
            this.cancelDrag();
        }
    }

    cancelDrag() {
        console.log('[ProductsDragDrop] Canceling drag');
        
        // Restore original element opacity
        if (this.dragState.draggedElement) {
            this.dragState.draggedElement.style.opacity = '';
            this.dragState.draggedElement.classList.remove('dragging');
        }
        
        this.cleanupDrag();
    }

    cleanupDrag() {
        // Hide insertion line
        this.hideInsertionLine();
        
        // Remove ghost element
        if (this.dragState.ghostElement) {
            document.body.removeChild(this.dragState.ghostElement);
        }
        
        // Cancel any pending animation frames
        if (this.performanceFlags.rafId) {
            cancelAnimationFrame(this.performanceFlags.rafId);
            this.performanceFlags.rafId = null;
        }
        
        // Reset performance flags
        this.performanceFlags.isThrottling = false;
        this.performanceFlags.lastGhostUpdate = 0;
        
        // Reset drag state
        this.dragState = {
            isDragging: false,
            draggedElement: null,
            draggedProductId: null,
            draggedProductData: null,
            originalPosition: null,
            ghostElement: null,
            insertionLine: this.dragState.insertionLine, // Keep insertion line element
            dropTargetElement: null,
            originalProducts: [],
            pendingUpdate: false
        };
        
        console.log('[ProductsDragDrop] Cleanup complete');
    }

    // ========================================================================
    // UTILITY METHODS
    // ========================================================================

    findProductRowById(productId) {
        // ZMIANA: użyj nowej klasy product row
        return this.elements.viewport.querySelector(`.prod_list-product-row[data-product-id="${productId}"]`);
    }

    enable() {
        this.enabled = true;
        console.log('[ProductsDragDrop] Enabled');
    }

    disable() {
        this.enabled = false;
        if (this.dragState.isDragging) {
            this.cancelDrag();
        }
        console.log('[ProductsDragDrop] Disabled');
    }

    destroy() {
        this.disable();
        
        // Remove insertion line
        if (this.dragState.insertionLine && this.dragState.insertionLine.parentNode) {
            this.dragState.insertionLine.parentNode.removeChild(this.dragState.insertionLine);
        }
        
        // Remove custom styles
        const customStyles = document.getElementById('products-dragdrop-styles');
        if (customStyles && customStyles.parentNode) {
            customStyles.parentNode.removeChild(customStyles);
        }
        
        // Remove event listeners
        document.removeEventListener('dragstart', this.onDragStart.bind(this));
        document.removeEventListener('dragend', this.onDragEnd.bind(this));
        document.removeEventListener('dragover', this.onDragOver.bind(this));
        document.removeEventListener('drop', this.onDrop.bind(this));
        
        console.log('[ProductsDragDrop] Destroyed');
    }

    // ========================================================================
    // PUBLIC API
    // ========================================================================

    isEnabled() {
        return this.enabled;
    }

    isDragging() {
        return this.dragState.isDragging;
    }

    getCurrentDraggedProduct() {
        return this.dragState.draggedProductData;
    }
}

// ========================================================================
// EXPORT
// ========================================================================

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProductsDragDrop;
}

// Make available globally
window.ProductsDragDrop = ProductsDragDrop;