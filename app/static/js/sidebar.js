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
            const betaTag = document.querySelector('.beta-tag');
            console.log('[SIDEBAR] Beta tag element:', betaTag);

            if (betaTag && data.version) {
                console.log('[SIDEBAR] Aktualizuję wersję na:', data.version);
                betaTag.textContent = `BETA ${data.version}`;
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
// MOBILE MENU FUNCTIONALITY
// ============================================

(function() {
    'use strict';
    
    // Sprawdź czy jesteśmy na mobile
    function isMobile() {
        return window.innerWidth <= 768;
    }
    
    // Inicjalizacja mobile menu
    function initMobileMenu() {
        // Sprawdź czy elementy już istnieją
        if (document.querySelector('.mobile-menu-toggle')) {
            return;
        }
        
        // Utwórz hamburger button
        const mobileToggle = document.createElement('button');
        mobileToggle.className = 'mobile-menu-toggle';
        mobileToggle.setAttribute('aria-label', 'Toggle menu');
        mobileToggle.innerHTML = `
            <div class="hamburger-icon">
                <span></span>
                <span></span>
                <span></span>
            </div>
        `;
        
        // Utwórz overlay
        const mobileOverlay = document.createElement('div');
        mobileOverlay.className = 'mobile-overlay';
        mobileOverlay.setAttribute('aria-hidden', 'true');
        
        // Dodaj do body
        document.body.appendChild(mobileToggle);
        document.body.appendChild(mobileOverlay);
        
        // Ukryj elementy na desktop
        if (!isMobile()) {
            mobileToggle.style.display = 'none';
        }
        
        const sidebar = document.querySelector('.sidebar');
        
        // Toggle menu function
        function toggleMobileMenu(event) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            
            const isOpen = sidebar.classList.contains('mobile-open');
            
            if (isOpen) {
                // Zamknij menu
                sidebar.classList.remove('mobile-open');
                mobileToggle.classList.remove('active');
                mobileOverlay.classList.remove('active');
                document.body.style.overflow = '';
                
                console.log('[Mobile Menu] Menu zamknięte');
            } else {
                // Otwórz menu
                sidebar.classList.add('mobile-open');
                mobileToggle.classList.add('active');
                mobileOverlay.classList.add('active');
                document.body.style.overflow = 'hidden';
                
                console.log('[Mobile Menu] Menu otwarte');
            }
        }
        
        // Event listeners
        mobileToggle.addEventListener('click', toggleMobileMenu);
        mobileToggle.addEventListener('touchstart', function(e) {
            e.preventDefault();
            toggleMobileMenu();
        }, { passive: false });
        
        mobileOverlay.addEventListener('click', toggleMobileMenu);
        
        // Zamknij menu po kliknięciu w link
        const menuLinks = sidebar.querySelectorAll('.menu-options a, .shorts-link, .footer-menu-item');
        menuLinks.forEach(link => {
            link.addEventListener('click', function() {
                if (isMobile() && sidebar.classList.contains('mobile-open')) {
                    setTimeout(() => {
                        toggleMobileMenu();
                    }, 200);
                }
            });
        });
        
        // Handle resize
        let resizeTimer;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() {
                if (!isMobile()) {
                    // Desktop mode
                    sidebar.classList.remove('mobile-open');
                    mobileToggle.classList.remove('active');
                    mobileOverlay.classList.remove('active');
                    document.body.style.overflow = '';
                    mobileToggle.style.display = 'none';
                } else {
                    // Mobile mode
                    mobileToggle.style.display = 'flex';
                }
            }, 250);
        });
        
        // Zapobiegnij scrollowaniu sidebara gdy jest otwarty
        sidebar.addEventListener('touchmove', function(e) {
            if (sidebar.classList.contains('mobile-open')) {
                e.stopPropagation();
            }
        }, { passive: true });
        
        console.log('[Mobile Menu] Initialized');
    }
    
    // Inicjalizuj po załadowaniu DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMobileMenu);
    } else {
        initMobileMenu();
    }
    
})();