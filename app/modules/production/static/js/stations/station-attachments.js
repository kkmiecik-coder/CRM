/**
 * ============================================================================
 * STATION ATTACHMENTS - Obsługa załączników produktów
 * ============================================================================
 *
 * Funkcjonalność:
 * - Tooltip z podglądem obrazka/PDF po najechaniu myszką
 * - Modal pełnoekranowy z załącznikiem po kliknięciu
 * - Wsparcie dla JPG, JPEG, PNG, BMP, PDF
 *
 * @author: Konrad Kmiecik
 * @date: 2025-01-25
 */

(function() {
    'use strict';

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    document.addEventListener('DOMContentLoaded', function() {
        console.log('[Attachments] Inicjalizacja obsługi załączników');
        initializeAttachmentHandlers();
    });

    // Timer do opóźnionego usuwania tooltipa
    let tooltipRemovalTimer = null;

    /**
     * Inicjalizacja handlerów dla ikon załączników
     */
    function initializeAttachmentHandlers() {
        const attachmentIcons = document.querySelectorAll('.attachment-icon-wrapper');

        attachmentIcons.forEach(icon => {
            // Hover - tooltip
            icon.addEventListener('mouseenter', handleAttachmentHover);
            icon.addEventListener('mouseleave', handleAttachmentLeave);

            // Click - modal
            icon.addEventListener('click', handleAttachmentClick);
        });

        console.log(`[Attachments] Zainicjalizowano ${attachmentIcons.length} ikon załączników`);
    }

    /**
     * Re-inicjalizacja handlerów po aktualizacji DOM (np. refresh produktów)
     */
    window.reinitializeAttachmentHandlers = function() {
        console.log('[Attachments] Re-inicjalizacja handlerów załączników');
        initializeAttachmentHandlers();
    };

    // ========================================================================
    // TOOLTIP HANDLERS
    // ========================================================================

    /**
     * Obsługa najechania myszką - pokaż tooltip z podglądem
     */
    function handleAttachmentHover(event) {
        const wrapper = event.currentTarget;
        const attachmentUrl = wrapper.dataset.attachmentUrl;
        const attachmentName = wrapper.dataset.attachmentName;
        const attachmentType = wrapper.dataset.attachmentType;

        // Sprawdź czy tooltip już istnieje
        if (document.querySelector('.attachment-tooltip[data-for-wrapper]')) {
            return;
        }

        // Utwórz tooltip
        const tooltip = document.createElement('div');
        tooltip.className = 'attachment-tooltip';
        tooltip.dataset.forWrapper = 'true';
        tooltip.style.position = 'fixed';
        tooltip.style.zIndex = '10000';

        // Dodaj podgląd w zależności od typu
        if (attachmentType === 'image') {
            const img = document.createElement('img');
            img.src = attachmentUrl;
            img.alt = attachmentName;
            img.onerror = function() {
                console.error('[Attachments] Błąd ładowania obrazka:', attachmentUrl);
                tooltip.innerHTML = '<div style="color: var(--text-secondary); padding: 8px;">Błąd ładowania obrazka</div>';
            };
            tooltip.appendChild(img);
        } else if (attachmentType === 'pdf') {
            // PDF - pokaż podgląd w iframe
            const iframe = document.createElement('iframe');
            iframe.src = attachmentUrl;
            iframe.title = attachmentName;
            iframe.onerror = function() {
                console.error('[Attachments] Błąd ładowania PDF:', attachmentUrl);
                tooltip.innerHTML = '<div style="color: var(--text-secondary); padding: 8px;">Błąd ładowania PDF</div>';
            };
            tooltip.appendChild(iframe);
        }

        // Dodaj nazwę pliku
        const nameLabel = document.createElement('div');
        nameLabel.className = 'attachment-tooltip-name';
        nameLabel.textContent = attachmentName;
        tooltip.appendChild(nameLabel);

        // Dodaj tooltip do body (nie do wrapper!)
        document.body.appendChild(tooltip);

        // Pozycjonuj tooltip względem ikony
        const rect = wrapper.getBoundingClientRect();
        tooltip.style.top = `${rect.bottom + 5}px`;
        tooltip.style.left = `${rect.left}px`;

        // Pokazanie tooltipa z animacją
        setTimeout(() => {
            tooltip.style.opacity = '1';
            tooltip.style.transform = 'translateY(0)';
        }, 10);

        // Zapisz referencję do wrapper w tooltip
        tooltip.wrapperElement = wrapper;

        // Dodaj event listenery do tooltipa - zapobiegaj zamykaniu gdy mysz jest nad tooltipem
        tooltip.addEventListener('mouseenter', function() {
            // Anuluj timer usuwania jeśli mysz weszła na tooltip
            if (tooltipRemovalTimer) {
                clearTimeout(tooltipRemovalTimer);
                tooltipRemovalTimer = null;
                console.log('[Attachments] Anulowano zamykanie tooltipa - mysz na tooltipie');
            }
        });

        tooltip.addEventListener('mouseleave', function() {
            // Gdy mysz opuszcza tooltip - usuń go z opóźnieniem
            scheduleTooltipRemoval(tooltip);
        });
    }

    /**
     * Obsługa opuszczenia myszki - usuń tooltip (z opóźnieniem)
     */
    function handleAttachmentLeave(event) {
        const wrapper = event.currentTarget;

        // Znajdź tooltip w body (nie w wrapper!)
        const tooltip = document.querySelector('.attachment-tooltip[data-for-wrapper]');

        if (tooltip && tooltip.wrapperElement === wrapper) {
            // Usuń tooltip z opóźnieniem - daje czas na najechanie myszą na tooltip
            scheduleTooltipRemoval(tooltip);
        }
    }

    /**
     * Zaplanuj usunięcie tooltipa z opóźnieniem (300ms)
     */
    function scheduleTooltipRemoval(tooltip) {
        // Anuluj poprzedni timer jeśli istnieje
        if (tooltipRemovalTimer) {
            clearTimeout(tooltipRemovalTimer);
        }

        // Ustaw nowy timer - 300ms opóźnienia
        tooltipRemovalTimer = setTimeout(() => {
            if (tooltip && tooltip.parentElement) {
                tooltip.remove();
                console.log('[Attachments] Tooltip usunięty po opóźnieniu');
            }
            tooltipRemovalTimer = null;
        }, 300);

        console.log('[Attachments] Zaplanowano usunięcie tooltipa za 300ms');
    }

    // ========================================================================
    // MODAL HANDLERS
    // ========================================================================

    /**
     * Obsługa kliknięcia - otwórz modal pełnoekranowy
     */
    function handleAttachmentClick(event) {
        event.stopPropagation();

        const wrapper = event.currentTarget;
        const attachmentUrl = wrapper.dataset.attachmentUrl;
        const attachmentName = wrapper.dataset.attachmentName;
        const attachmentType = wrapper.dataset.attachmentType;

        console.log('[Attachments] Otwieranie modalu:', {
            name: attachmentName,
            type: attachmentType,
            url: attachmentUrl
        });

        openAttachmentModal(attachmentUrl, attachmentName, attachmentType);
    }

    /**
     * Otwórz modal z załącznikiem
     */
    function openAttachmentModal(url, name, type) {
        const modal = document.getElementById('attachmentModal');
        const modalContent = document.getElementById('modalAttachmentContent');

        if (!modal || !modalContent) {
            console.error('[Attachments] Nie znaleziono elementów modalu');
            return;
        }

        // Wyczyść poprzednią zawartość
        modalContent.innerHTML = '';

        // Dodaj zawartość w zależności od typu
        if (type === 'image') {
            const img = document.createElement('img');
            img.src = url;
            img.alt = name;
            img.onerror = function() {
                console.error('[Attachments] Błąd ładowania obrazka w modalu:', url);
                modalContent.innerHTML = '<div style="color: white; font-size: 1.2rem;">Błąd ładowania obrazka</div>';
            };
            modalContent.appendChild(img);
        } else if (type === 'pdf') {
            const iframe = document.createElement('iframe');
            iframe.src = url;
            iframe.title = name;
            iframe.onerror = function() {
                console.error('[Attachments] Błąd ładowania PDF w modalu:', url);
                modalContent.innerHTML = '<div style="color: white; font-size: 1.2rem;">Błąd ładowania PDF</div>';
            };
            modalContent.appendChild(iframe);
        }

        // Pokaż modal
        modal.classList.add('show');

        // Dodaj handler zamykania przez ESC
        document.addEventListener('keydown', handleModalEscapeKey);

        // Dodaj handler zamykania przez kliknięcie w tło
        modal.addEventListener('click', handleModalBackgroundClick);
    }

    /**
     * Zamknij modal
     */
    window.closeAttachmentModal = function() {
        const modal = document.getElementById('attachmentModal');
        const modalContent = document.getElementById('modalAttachmentContent');

        if (modal) {
            modal.classList.remove('show');

            // Wyczyść zawartość
            if (modalContent) {
                modalContent.innerHTML = '';
            }

            // Usuń handlery
            document.removeEventListener('keydown', handleModalEscapeKey);
            modal.removeEventListener('click', handleModalBackgroundClick);

            console.log('[Attachments] Modal zamknięty');
        }
    };

    /**
     * Handler zamykania modalu przez ESC
     */
    function handleModalEscapeKey(event) {
        if (event.key === 'Escape' || event.keyCode === 27) {
            window.closeAttachmentModal();
        }
    }

    /**
     * Handler zamykania modalu przez kliknięcie w tło
     */
    function handleModalBackgroundClick(event) {
        const modal = document.getElementById('attachmentModal');

        // Zamknij tylko jeśli kliknięto w tło (nie w treść)
        if (event.target === modal) {
            window.closeAttachmentModal();
        }
    }

    // ========================================================================
    // REFRESH SUPPORT
    // ========================================================================

    /**
     * Hook do istniejącego systemu odświeżania produktów
     * Jeśli stanowisko ma funkcję refreshProducts(), podepnij się do niej
     */
    if (window.StationManager && typeof window.StationManager.afterProductsRefresh === 'function') {
        const originalAfterRefresh = window.StationManager.afterProductsRefresh;

        window.StationManager.afterProductsRefresh = function() {
            originalAfterRefresh.call(window.StationManager);
            window.reinitializeAttachmentHandlers();
        };
    }

    console.log('[Attachments] Moduł załączników załadowany');
})();
