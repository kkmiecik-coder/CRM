document.addEventListener('DOMContentLoaded', function () {
    const sidebarLinks = document.querySelectorAll('.menu-options a');

    sidebarLinks.forEach(link => {
        link.addEventListener('click', function (event) {
            const url = this.getAttribute('href');

            // Aktywacja stylu klikniętego menu
            document.querySelectorAll('.menu-options').forEach(item => item.classList.remove('active'));
            const parentOption = this.closest('.menu-options');
            if (parentOption) parentOption.classList.add('active');

            // Wymuszenie pełnego przeładowania strony
            window.location.href = url;
        });
    });

    const footerOptionsIcon = document.querySelector('.footer-options-icon');
    const footerOptionsPanel = document.querySelector('.footer-options-panel');

    if (footerOptionsIcon && footerOptionsPanel) {
        footerOptionsPanel.classList.remove('open');
        footerOptionsIcon.style.transform = 'rotate(0deg)';

        footerOptionsIcon.addEventListener('click', function () {
            if (footerOptionsPanel.classList.contains('open')) {
                footerOptionsPanel.classList.remove('open');
                footerOptionsIcon.style.transform = 'rotate(0deg)';
            } else {
                footerOptionsPanel.classList.add('open');
                footerOptionsIcon.style.transform = 'rotate(180deg)';
            }
        });
    }

    // Inicjalizacja stanu sidebara z localStorage
    initializeSidebar();

    // Inicjalizacja tooltipów
    initializeTooltips();

    // Pobieranie najnowszej wersji
    console.log('[SIDEBAR] Rozpoczynam pobieranie wersji...');
    fetch('/api/latest-version')
        .then(response => {
            console.log('[SIDEBAR] Response status:', response.status);
            console.log('[SIDEBAR] Response ok:', response.ok);
            return response.json();
        })
        .then(data => {
            console.log('[SIDEBAR] Otrzymane dane:', data);
            // Aktualizuj wszystkie beta tagi (desktop i mobile)
            const betaTags = document.querySelectorAll('.beta-tag');
            console.log('[SIDEBAR] Beta tag elements found:', betaTags.length);

            if (betaTags.length > 0 && data.version) {
                console.log('[SIDEBAR] Aktualizuję wersję na:', data.version);
                betaTags.forEach(tag => {
                    tag.textContent = `BETA ${data.version}`;
                });
            } else {
                console.log('[SIDEBAR] Brak beta-tag lub wersji w danych');
            }
        })
        .catch(error => {
            console.log('[SIDEBAR] Błąd fetch:', error);
        });
});

// === FUNKCJE ZWIJANIA SIDEBARA ===

function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');

    if (sidebar.classList.contains('collapsed')) {
        // Rozwiń sidebar
        sidebar.classList.remove('collapsed');
        if (mainContent) {
            mainContent.classList.remove('sidebar-collapsed');
        }
        localStorage.setItem('sidebarCollapsed', 'false');
    } else {
        // Zwiń sidebar
        sidebar.classList.add('collapsed');
        if (mainContent) {
            mainContent.classList.add('sidebar-collapsed');
        }
        localStorage.setItem('sidebarCollapsed', 'true');
    }
}

function initializeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';

    if (isCollapsed) {
        sidebar.classList.add('collapsed');
        if (mainContent) {
            mainContent.classList.add('sidebar-collapsed');
        }
    }
}

// === FUNKCJE TOOLTIPÓW ===

function initializeTooltips() {
    const elementsWithTooltips = document.querySelectorAll('[data-sidebar-tooltip]');

    elementsWithTooltips.forEach(element => {
        element.addEventListener('mouseenter', showTooltip);
        element.addEventListener('mouseleave', handleMouseLeave);
    });
}

function showTooltip(event) {
    const sidebar = document.querySelector('.sidebar');

    // Pokaż tooltip tylko gdy sidebar jest zwinięty
    if (!sidebar.classList.contains('collapsed')) {
        return;
    }

    const allTimeouts = window.tooltipTimeouts || [];
    allTimeouts.forEach(timeoutId => clearTimeout(timeoutId));
    window.tooltipTimeouts = [];

    // Usuń poprzedni tooltip jeśli istnieje
    const existingTooltip = document.querySelector('.sidebar-tooltip');
    if (existingTooltip) {
        existingTooltip.remove();
    }

    const tooltip = document.createElement('div');
    tooltip.className = 'sidebar-tooltip';
    tooltip.textContent = this.getAttribute('data-sidebar-tooltip');

    // Dodaj referencję do elementu źródłowego
    tooltip.sourceElement = this;

    document.body.appendChild(tooltip);

    // Pozycjonowanie tooltip - zawsze po prawej stronie sidebara
    const rect = this.getBoundingClientRect();
    const sidebarWidth = 100; // szerokość zwiniętego sidebara

    tooltip.style.left = sidebarWidth + 15 + 'px'; // 15px odstępu od sidebara
    tooltip.style.top = rect.top + (rect.height / 2) - (tooltip.offsetHeight / 2) + 'px';

    // Event listenery dla tooltipa
    tooltip.addEventListener('mouseenter', function () {
        // Tooltip pozostaje widoczny
    });

    tooltip.addEventListener('mouseleave', function () {
        this.remove();
    });

    // Animacja pojawiania się
    requestAnimationFrame(() => {
        tooltip.classList.add('visible');
    });
}

function handleMouseLeave(event) {

    // Sprawdź czy kursor nie przeszedł na tooltip
    const timeoutId = setTimeout(() => {
        const tooltip = document.querySelector('.sidebar-tooltip');
        if (tooltip) {
            const tooltipRect = tooltip.getBoundingClientRect();
            const mouseX = event.clientX;
            const mouseY = event.clientY;

            // Jeśli kursor nie jest nad tooltipem, usuń go
            if (mouseX < tooltipRect.left ||
                mouseX > tooltipRect.right ||
                mouseY < tooltipRect.top ||
                mouseY > tooltipRect.bottom) {

                tooltip.classList.remove('visible');
                setTimeout(() => {
                    if (tooltip.parentNode) {
                        tooltip.remove();
                    }
                }, 300);
            }
        }

        // Usuń timeout z listy po wykonaniu
        window.tooltipTimeouts = (window.tooltipTimeouts || []).filter(id => id !== timeoutId);
    }, 50);

    // Zapisz timeout do listy
    if (!window.tooltipTimeouts) window.tooltipTimeouts = [];
    window.tooltipTimeouts.push(timeoutId);
}

// Funkcja globalna dostępna w HTML
window.toggleSidebar = toggleSidebar;

// ============================================
// MOBILE TOPBAR MENU FUNCTIONALITY
// ============================================

(function() {
    'use strict';

    // Zabezpieczenie przed podwójną inicjalizacją
    if (window._mobileTopbarInitialized) {
        console.log('[Mobile Topbar] Already initialized, skipping');
        return;
    }
    window._mobileTopbarInitialized = true;

    // Sprawdź czy jesteśmy na mobile
    function isMobile() {
        return window.innerWidth <= 768;
    }

    // Inicjalizacja mobile topbar menu
    function initMobileTopbarMenu() {
        const topbarToggle = document.getElementById('mobileTopbarToggle');
        const mobileMenu = document.getElementById('mobileMenu');
        const mobileOverlay = document.getElementById('mobileMenuOverlay');

        if (!topbarToggle || !mobileMenu || !mobileOverlay) {
            console.log('[Mobile Topbar] Elements not found, skipping initialization');
            return;
        }

        // Toggle menu function
        function toggleMobileMenu(event) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }

            const isOpen = mobileMenu.classList.contains('open');

            if (isOpen) {
                // Zamknij menu
                mobileMenu.classList.remove('open');
                topbarToggle.classList.remove('active');
                mobileOverlay.classList.remove('active');
                document.body.style.overflow = '';

                console.log('[Mobile Topbar] Menu zamknięte');
            } else {
                // Otwórz menu
                mobileMenu.classList.add('open');
                topbarToggle.classList.add('active');
                mobileOverlay.classList.add('active');
                document.body.style.overflow = 'hidden';

                console.log('[Mobile Topbar] Menu otwarte');
            }
        }

        // Event listeners dla przycisku toggle
        let touchHandled = false;

        topbarToggle.addEventListener('touchend', function(e) {
            e.preventDefault();
            touchHandled = true;
            toggleMobileMenu();
            // Reset po krótkim czasie
            setTimeout(() => { touchHandled = false; }, 300);
        }, { passive: false });

        topbarToggle.addEventListener('click', function(e) {
            if (!touchHandled) {
                toggleMobileMenu(e);
            }
        });

        // Zamknij menu po kliknięciu w overlay
        mobileOverlay.addEventListener('click', toggleMobileMenu);

        // Zamknij menu po kliknięciu w link
        const menuLinks = mobileMenu.querySelectorAll('.mobile-menu-item a');
        menuLinks.forEach(link => {
            link.addEventListener('click', function() {
                if (isMobile() && mobileMenu.classList.contains('open')) {
                    setTimeout(() => {
                        toggleMobileMenu();
                    }, 150);
                }
            });
        });

        // Handle resize - zamknij menu przy zmianie rozmiaru
        let resizeTimer;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() {
                if (!isMobile()) {
                    // Desktop mode - zamknij menu
                    mobileMenu.classList.remove('open');
                    topbarToggle.classList.remove('active');
                    mobileOverlay.classList.remove('active');
                    document.body.style.overflow = '';
                }
            }, 250);
        });

        // Zamknij menu klawiszem Escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && mobileMenu.classList.contains('open')) {
                toggleMobileMenu();
            }
        });

        console.log('[Mobile Topbar] Initialized');
    }

    // Inicjalizuj po załadowaniu DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMobileTopbarMenu);
    } else {
        initMobileTopbarMenu();
    }

})();