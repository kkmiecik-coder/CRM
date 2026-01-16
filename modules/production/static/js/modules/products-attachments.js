/**
 * ============================================================================
 * PRODUCTS ATTACHMENTS - Obsługa załączników produktów w panelu admina
 * ============================================================================
 *
 * Funkcjonalność:
 * - Wyświetlanie ikony załącznika dla produktów z załącznikami
 * - Modal pełnoekranowy z podglądem załącznika (obrazki i PDF)
 * - Hook do systemu renderowania produktów
 *
 * @author: Konrad Kmiecik
 * @date: 2025-01-25
 */

(function() {
    'use strict';

    console.log('[ProductsAttachments] Moduł załączników załadowany');

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[ProductsAttachments] Inicjalizacja obsługi załączników w panelu');
        initializeAttachmentHandlers();
    });

    /**
     * Inicjalizacja handlerów dla ikon załączników
     * (obecnie ikony są tylko informacyjne - nie klikalne)
     */
    function initializeAttachmentHandlers() {
        const attachmentIcons = document.querySelectorAll('.prod_list-attachment-icon');
        console.log(`[ProductsAttachments] Znaleziono ${attachmentIcons.length} ikon załączników`);
    }

    /**
     * Re-inicjalizacja handlerów po renderze produktów
     * Ta funkcja jest wywoływana przez products-module.js
     */
    window.reinitializeProductAttachments = function() {
        console.log('[ProductsAttachments] Re-inicjalizacja handlerów załączników');
        initializeAttachmentHandlers();
    };

    /**
     * Hook do renderowania wiersza produktu
     * Ta funkcja jest wywoływana przez products-module.js podczas renderowania każdego produktu
     */
    window.handleProductAttachmentRender = function(productRow, productData) {
        const attachmentIcon = productRow.querySelector('.prod_list-attachment-icon');

        if (!attachmentIcon) {
            return;
        }

        // Sprawdź czy produkt ma załącznik
        if (productData.attachment_file_url && productData.attachment_file_name) {
            // Pokaż ikonę
            attachmentIcon.style.display = 'inline-block';

            console.log('[ProductsAttachments] Produkt ma załącznik:', {
                product_id: productData.id,
                attachment_name: productData.attachment_file_name
            });
        } else {
            // Ukryj ikonę jeśli brak załącznika
            attachmentIcon.style.display = 'none';
        }
    };

    // ========================================================================
    // UWAGA: Ikona załącznika w panelu admina jest tylko informacyjna
    // Pełny podgląd załącznika jest dostępny w modalu szczegółów produktu
    // ========================================================================

    console.log('[ProductsAttachments] Moduł załączników gotowy');
})();
