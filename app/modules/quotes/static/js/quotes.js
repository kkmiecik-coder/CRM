// modules/quotes/static/js/quotes.js

console.log("quotes.js załadowany");

let allStatuses = {};
let allQuotes = [];
let activeStatus = null;
let currentPage = 1;
let resultsPerPage = 20;
let allUsers = [];
let currentEditingItem = null;
let currentQuoteData = null;
let discountReasons = [];
let originalPrices = {};
let acceptedQuotes = new Set(); // Set do śledzenia ID zaakceptowanych wycen

document.addEventListener("DOMContentLoaded", () => {
    console.log("[DOMContentLoaded] Inicjalizacja komponentów");
    fetchQuotes();
    fetchQuotes().then(() => {
        initDownloadModal();
    });
    initStatusPanel();
    fetchUsers();
    initClearFiltersButton();
    updateClearFiltersButtonState();
    initEditModals();

    // Event listeners dla modala
    const closeBtn = document.getElementById("close-details-modal");
    const modal = document.getElementById("quote-details-modal");
    if (closeBtn && modal) {
        closeBtn.addEventListener("click", () => {
            modal.classList.remove("active");
        });
    }

    const toggleFullscreenBtn = document.getElementById("toggle-fullscreen-modal");
    const modalOverlay = document.getElementById("quote-details-modal");
    const downloadBtn = document.getElementById("download-details-btn");

    if (toggleFullscreenBtn && modalOverlay) {
        toggleFullscreenBtn.addEventListener("click", () => {
            modalOverlay.classList.toggle("fullscreen");
        });
    }

    if (downloadBtn) {
        downloadBtn.addEventListener("click", () => {
            const token = downloadBtn.dataset.token;
            console.log(`[DownloadBtn] Klik w modal - token: ${token}`);
            
            if (!token || token === 'undefined') {
                console.error('[DownloadBtn] Brak tokenu lub token undefined');
                alert('Nie można pobrać PDF - brak tokenu zabezpieczającego');
                return;
            }
            
            // ZMIANA: Użyj systemu modala PDF zamiast window.open
            const modal = document.getElementById("download-modal");
            const iframe = document.getElementById("quotePreview");
            const downloadPDF = document.getElementById("downloadPDF");
            const downloadPNG = document.getElementById("downloadPNG");
            
            if (modal && iframe && downloadPDF && downloadPNG) {
                // Ustaw PDF w iframe
                iframe.src = `/quotes/api/quotes/${token}/pdf.pdf`;
                
                // Ustaw token dla przycisków pobierania
                downloadPDF.dataset.token = token;
                downloadPNG.dataset.token = token;
                
                // Pokaż modal
                modal.style.display = "flex";
                
                console.log(`[DownloadBtn] Otworzono modal PDF dla tokenu: ${token}`);
            } else {
                console.error('[DownloadBtn] Brak elementów modala PDF w DOM');
                // Fallback - otwórz w nowej zakładce
                window.open(`/quotes/api/quotes/${token}/pdf.pdf`, "_blank");
            }
        });
    }
});

// Inicjalizacja modali edycji - dodaj do DOMContentLoaded
function initEditModals() {
    console.log("[initEditModals] Inicjalizacja modali edycji");

    // Pobierz powody rabatów
    fetchDiscountReasons();

    // Event listeners dla modali
    setupVariantEditModal();
    setupTotalDiscountModal();
}

function initDownloadModal() {
    const modal = document.getElementById("download-modal");
    const closeBtn = document.getElementById("closeDownloadModal");
    const iframe = document.getElementById("quotePreview");
    const downloadPDF = document.getElementById("downloadPDF");
    const downloadPNG = document.getElementById("downloadPNG");

    document.addEventListener("click", (e) => {
        const downloadBtn = e.target.closest(".quotes-btn-download");
        if (downloadBtn) {
            // ZMIANA: Pobieramy token zamiast ID
            const quoteToken = downloadBtn.dataset.token; // było: dataset.id
            console.log(`[DownloadModal] Klik dla TOKEN: ${quoteToken}`);

            if (!quoteToken) {
                console.warn("❗️Brak quoteToken – dataset.token undefined!");
                return;
            }

            if (!iframe) {
                console.warn("❗️Brak #quotePreview w DOM!");
                return;
            }

            // ZMIANA: Użyj tokenu w URL
            iframe.src = `/quotes/api/quotes/${quoteToken}/pdf.pdf`;

            // ZMIANA: Ustaw token dla przycisków pobierania
            downloadPDF.dataset.token = quoteToken;
            downloadPNG.dataset.token = quoteToken;

            modal.style.display = "flex";
        }
    });

    closeBtn.addEventListener("click", () => {
        modal.style.display = "none";
        iframe.src = "";
    });

    // ZMIANA: Pobieranie PDF z tokenem
    downloadPDF.addEventListener("click", () => {
        const quoteToken = downloadPDF.dataset.token;
        window.open(`/quotes/api/quotes/${quoteToken}/pdf.pdf`, "_blank");
    });

    // ZMIANA: Pobieranie PNG z tokenem
    downloadPNG.addEventListener("click", () => {
        const quoteToken = downloadPNG.dataset.token;
        window.open(`/quotes/api/quotes/${quoteToken}/pdf.png`, "_blank");
    });

    // Zamykanie modal po kliknięciu tła
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.style.display = "none";
            iframe.src = "";
        }
    });
}

function fetchQuotes() {
    console.info("[fetchQuotes] Pobieranie wycen z /quotes/api/quotes");

    return fetch("/quotes/api/quotes")
        .then(res => res.json())
        .then(data => {
            allQuotes = data;
            console.log(`[fetchQuotes] Załadowano ${data.length} wycen`);
            if (data.length > 0) {
                allStatuses = data[0].all_statuses;
            }
            filterQuotes();
            
            // NOWA FUNKCJONALNOŚĆ: Sprawdź czy mamy parametr open_quote w URL
            console.log("[fetchQuotes] Sprawdzam parametr open_quote...");
            checkForOpenQuoteParameter();
        })
        .catch(err => {
            console.error("[fetchQuotes] Błąd pobierania wycen:", err);
        });
}

function fetchUsers() {
    fetch("/quotes/api/users")
        .then(res => res.json())
        .then(data => {
            allUsers = data;
            const select = document.getElementById("employee-filter");
            if (!select) return;

            // Reset opcji przed dodaniem nowych
            select.innerHTML = '<option value="">Wszyscy</option>';

            data.forEach(user => {
                const opt = document.createElement("option");
                opt.value = user.id;
                opt.textContent = user.name;
                select.appendChild(opt);
            });
        })
        .catch(err => console.error("Błąd pobierania użytkowników:", err));
}

// Aktualizacja funkcji showDetailsModal w app/modules/quotes/static/js/quotes.js
// Dodaj te wywołania na końcu istniejącej funkcji showDetailsModal

function showDetailsModal(quoteData) {
    console.log('[MODAL] Otwieranie szczegółów wyceny:', quoteData);

    const modal = document.getElementById('quote-details-modal');
    const modalBox = modal.querySelector('.quotes-details-modal-box');

    // DODANE: Zapisz ID wyceny w modal dla modułu Baselinker
    if (modal && quoteData && quoteData.id) {
        modal.dataset.quoteId = quoteData.id;
        console.log(`[MODAL] Zapisano dataset.quoteId = ${quoteData.id}`);
    }

    const itemsContainer = document.getElementById('quotes-details-modal-items-body');
    const tabsContainer = document.getElementById('quotes-details-tabs');
    const dropdownWrap = document.getElementById('quotes-details-modal-status-dropdown');
    const selectedDiv = document.getElementById('custom-status-selected');
    const optionsContainer = document.getElementById('custom-status-options');

    if (!modal || !itemsContainer || !tabsContainer || !dropdownWrap || !selectedDiv || !optionsContainer) {
        console.warn('[MODAL] Brakuje elementów w DOM!');
        return;
    }

    // Wyczyść i ustaw aktualny kontekst
    tabsContainer.innerHTML = '';
    itemsContainer.innerHTML = '';
    currentQuoteData = quoteData;

    window.currentQuoteData = quoteData;
    console.log('[MODAL] Ustawiono currentQuoteData:', quoteData);

    removeAcceptanceBanner(modalBox);
    removeOrderBanner(modalBox);
    removeUserAcceptanceBanner(modalBox); // NOWE

    // DODAJ TĘ LOGIKĘ TUTAJ:
    // Sprawdź czy wycena jest zaakceptowana i dodaj obramowanie
    const isAccepted = checkIfQuoteAccepted(quoteData);
    const isAcceptedByUser = isQuoteAcceptedByUser(quoteData);
    const isOrdered = checkIfQuoteOrdered(quoteData);

    // Dodaj/usuń klasę CSS dla obramowania - priorytet ma zamówienie nad akceptacją
    if (isOrdered) {
        modalBox.classList.add('quote-ordered');
        modalBox.classList.remove('quote-accepted');
        console.log('[MODAL] Zamówienie złożone - dodano niebieskie obramowanie');
    } else if (isAccepted || isAcceptedByUser) {
        modalBox.classList.add('quote-accepted');
        modalBox.classList.remove('quote-ordered');
        acceptedQuotes.add(quoteData.id);
        console.log('[MODAL] Wycena zaakceptowana - dodano zielone obramowanie');

        // Opcjonalna animacja pulsowania
        setTimeout(() => {
            modalBox.classList.add('pulse-animation');
            setTimeout(() => {
                modalBox.classList.remove('pulse-animation');
            }, 6000);
        }, 500);
    } else {
        modalBox.classList.remove('quote-accepted', 'quote-ordered');
        acceptedQuotes.delete(quoteData.id);
    }

    // ZAKTUALIZUJ Dane klienta
    document.getElementById('quotes-details-modal-client-name').textContent = quoteData.client?.client_name || '-';
    document.getElementById('quotes-details-modal-client-fullname').textContent = 
        `${quoteData.client?.first_name || ''} ${quoteData.client?.last_name || ''}`.trim() || '-';
    document.getElementById('quotes-details-modal-client-company').textContent = quoteData.client?.company_name || '-';
    document.getElementById('quotes-details-modal-client-email').textContent = quoteData.client?.email || '-';
    document.getElementById('quotes-details-modal-client-phone').textContent = quoteData.client?.phone || '-';

    // ZAKTUALIZUJ Dane wyceny
    const parsedDate = quoteData.created_at ? 
        new Date(quoteData.created_at).toLocaleDateString("pl-PL") : '-';
    document.getElementById('quotes-details-modal-quote-number').textContent = quoteData.quote_number || '-';
    document.getElementById('quotes-details-modal-quote-date').textContent = parsedDate;
    document.getElementById('quotes-details-modal-quote-source').textContent = quoteData.source || '-';

    // POPRAWIONE dane pracownika
    const employeeName = `${quoteData.user?.first_name || ''} ${quoteData.user?.last_name || ''}`.trim() || '-';
    document.getElementById('quotes-details-modal-employee-name').textContent = employeeName;

    // NOWE: Wyświetl informacje o mnożniku
    updateMultiplierDisplay(quoteData);

    // ZMIANA: Ustaw token zamiast ID dla przycisku pobierz
    const downloadBtn = document.getElementById("download-details-btn");
    if (downloadBtn) {
        console.log('[MODAL] Otrzymane dane wyceny:', {
            id: quoteData.id,
            quote_number: quoteData.quote_number,
            public_token: quoteData.public_token,
            public_url: quoteData.public_url
        });
        
        let token = quoteData.public_token;
        
        // FALLBACK 1: Jeśli brak tokenu, znajdź go z listy wycen (allQuotes)
        if (!token && allQuotes && allQuotes.length > 0) {
            const quoteInList = allQuotes.find(q => q.id === quoteData.id);
            if (quoteInList && quoteInList.public_token) {
                token = quoteInList.public_token;
                console.log('[MODAL] ✅ Token skopiowany z listy wycen:', token);
            }
        }
        
        // FALLBACK 2: Jeśli nadal brak, wyodrębnij z public_url
        if (!token && quoteData.public_url) {
            const urlMatch = quoteData.public_url.match(/\/wycena\/[^\/]+\/([A-F0-9]+)$/);
            if (urlMatch) {
                token = urlMatch[1];
                console.log('[MODAL] ✅ Token wyodrębniony z public_url:', token);
            }
        }
        
        if (!token) {
            console.error('[MODAL] ❌ BRAK tokenu - sprawdź czy pole public_token jest w bazie danych');
        } else {
            console.log('[MODAL] ✅ Token do użycia:', token);
        }
        
        downloadBtn.dataset.token = token;
        delete downloadBtn.dataset.id;
        
        console.log('[MODAL] Ustawiono dataset.token:', downloadBtn.dataset.token);
    }

    // Reszta istniejącego kodu...
    updateCostsDisplay(quoteData);
    setupStatusDropdown(quoteData, optionsContainer, selectedDiv, dropdownWrap);
    setupProductTabs(quoteData, tabsContainer, itemsContainer);
    addTotalDiscountButton(quoteData);

    const summaryContainer = document.getElementById("quotes-details-selected-summary");
    if (summaryContainer) {
        const grouped = groupItemsByProductIndex(quoteData.items || []);
        renderSelectedSummary(grouped, summaryContainer);
    }

    // Inicjalizuj przyciski strony klienta
    initializeClientPageButtons(quoteData);

    // NOWE: Sprawdź bannery i dodaj odpowiednie
    console.log('[MODAL] Sprawdzanie bannerów akceptacji...');
    if (checkIfQuoteOrdered(quoteData)) {
        addOrderBanner(modalBox, quoteData);
    } else if (isQuoteAcceptedByUser(quoteData)) {
        addUserAcceptanceBanner(modalBox, quoteData);
    } else if (checkIfQuoteAccepted(quoteData)) {
        addAcceptanceBanner(modalBox, quoteData);
    }

    // NOWE: Konfiguracja przycisku akceptacji przez użytkownika
    console.log('[MODAL] Konfiguracja przycisku akceptacji przez użytkownika...');
    setupUserAcceptButton(quoteData);

    // === NOWA OBSŁUGA PRZYCISKU 3D/AR ===
    console.log('[MODAL] Konfiguracja przycisku 3D/AR...');
    const preview3dBtn = document.getElementById("quote-preview3d-btn");
    if (preview3dBtn) {
        console.log('[MODAL] Konfiguracja przycisku 3D/AR:', {
            id: quoteData.id,
            quote_number: quoteData.quote_number,
            public_token: quoteData.public_token
        });

        let token = quoteData.public_token;

        // FALLBACK 1: Jeśli brak tokenu, znajdź go z listy wycen (allQuotes)
        if (!token && allQuotes && allQuotes.length > 0) {
            const quoteInList = allQuotes.find(q => q.id === quoteData.id);
            if (quoteInList && quoteInList.public_token) {
                token = quoteInList.public_token;
                console.log('[MODAL] ✅ Token 3D skopiowany z listy wycen:', token);
            }
        }

        // FALLBACK 2: Jeśli nadal brak, wyodrębnij z public_url
        if (!token && quoteData.public_url) {
            const urlMatch = quoteData.public_url.match(/\/wycena\/[^\/]+\/([A-F0-9]+)$/);
            if (urlMatch) {
                token = urlMatch[1];
                console.log('[MODAL] ✅ Token 3D wyodrębniony z public_url:', token);
            }
        }

        if (!token) {
            console.error('[MODAL] ❌ BRAK tokenu dla 3D - wyłączam przycisk');
            preview3dBtn.disabled = true;
            preview3dBtn.title = 'Brak tokenu zabezpieczającego';
            preview3dBtn.style.opacity = '0.5';
        } else {
            console.log('[MODAL] ✅ Token 3D do użycia:', token);
            preview3dBtn.disabled = false;
            preview3dBtn.style.opacity = '1';
            preview3dBtn.title = 'Podgląd wybranego wariantu w 3D/AR';

            // Usuń poprzednie event listenery i dodaj nowy
            const newPreview3dBtn = preview3dBtn.cloneNode(true);
            preview3dBtn.parentNode.replaceChild(newPreview3dBtn, preview3dBtn);

            newPreview3dBtn.addEventListener('click', () => {
                console.log('[3D Button] Klik - otwieranie z tokenem:', token);

                // Sprawdź czy są produkty w wycenie
                if (!quoteData.items || quoteData.items.length === 0) {
                    alert('Błąd: Wycena nie zawiera żadnych produktów.');
                    return;
                }

                // URL nowego viewer'a z tokenem
                const viewerUrl = `/preview3d-ar/${token}`;

                // Parametry okna
                const windowFeatures = [
                    'width=1600',
                    'height=1000',
                    'scrollbars=yes',
                    'resizable=yes',
                    'menubar=no',
                    'toolbar=no',
                    'location=no',
                    'status=no',
                    'left=' + Math.max(0, (screen.width - 1600) / 2),
                    'top=' + Math.max(0, (screen.height - 1000) / 2)
                ].join(',');

                // Otwórz viewer
                const preview3DWindow = window.open(viewerUrl, 'QuoteViewer3D_' + token, windowFeatures);

                if (!preview3DWindow) {
                    // Fallback - spróbuj otworzyć w nowej karcie
                    window.open(viewerUrl, '_blank');
                    alert('Quote Viewer 3D/AR został otwarty w nowej karcie (sprawdź ustawienia blokady popup).');
                } else {
                    console.log('[3D Button] Okno Preview3D otwarte pomyślnie');
                }
            });
        }
    }

    modal.classList.add('active');
    console.log('[MODAL] Modal powinien być teraz widoczny! Data:', quoteData);

    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.classList.remove("active");
            console.log('[MODAL] Zamykam modal przez kliknięcie tła');
        }
    });

    setTimeout(() => {
        console.log('[MODAL] Inicjalizuję masową zmianę wariantów...');
        console.log('[MODAL] currentQuoteData przed initBulkVariantChange:', currentQuoteData);
        initBulkVariantChange();
    }, 100);
}

function updateMultiplierDisplay(quoteData) {
    console.log('[updateMultiplierDisplay] Aktualizuję wyświetlanie mnożnika:', quoteData);
    
    // Znajdź lub utwórz element do wyświetlania mnożnika
    let multiplierElement = document.getElementById('quotes-details-modal-multiplier');
    
    if (!multiplierElement) {
        // Jeśli element nie istnieje, utwórz go i dodaj do sekcji "Dane wyceny"
        const quoteDataSection = document.querySelector('.modal-block:nth-child(2)'); // Druga kolumna - "Dane wyceny"
        
        if (quoteDataSection) {
            const multiplierParagraph = document.createElement('p');
            multiplierParagraph.innerHTML = '<strong>Grupa cenowa:</strong> <span id="quotes-details-modal-multiplier">-</span>';
            
            // Dodaj po elemencie z pracownikiem
            const employeeElement = quoteDataSection.querySelector('p:nth-child(5)'); // Element z pracownikiem
            if (employeeElement) {
                employeeElement.insertAdjacentElement('afterend', multiplierParagraph);
            } else {
                // Fallback - dodaj na końcu sekcji
                quoteDataSection.appendChild(multiplierParagraph);
            }
            
            multiplierElement = document.getElementById('quotes-details-modal-multiplier');
        }
    }
    
    if (multiplierElement) {
        // Wyświetl informacje o grupie cenowej i mnożniku
        if (quoteData.quote_client_type && quoteData.quote_multiplier) {
            const multiplierText = `${quoteData.quote_client_type} (${quoteData.quote_multiplier})`;
            multiplierElement.textContent = multiplierText;
            console.log('[updateMultiplierDisplay] Wyświetlono mnożnik:', multiplierText);
        } else if (quoteData.quote_client_type) {
            // Tylko grupa cenowa bez mnożnika
            multiplierElement.textContent = quoteData.quote_client_type;
            console.log('[updateMultiplierDisplay] Wyświetlono grupę cenową:', quoteData.quote_client_type);
        } else {
            // Brak informacji o grupie cenowej
            multiplierElement.textContent = 'Nie określono';
            console.log('[updateMultiplierDisplay] Brak informacji o grupie cenowej');
        }
    } else {
        console.warn('[updateMultiplierDisplay] Nie udało się znaleźć lub utworzyć elementu mnożnika');
    }
}

function checkIfQuoteAccepted(quoteData) {
    // Sprawdź po nazwie statusu
    const statusName = quoteData.status_name ? quoteData.status_name.toLowerCase() : '';
    const isAcceptedByName = statusName.includes('akceptow') ||
        statusName.includes('accepted') ||
        statusName.includes('zatwierdzono');

    // Sprawdź po ID statusu (ID 3 = Zaakceptowane)
    const isAcceptedById = quoteData.status_id === 3;

    // Sprawdź po is_client_editable (false = zaakceptowane)
    const isAcceptedByEditability = quoteData.is_client_editable === false;

    console.log('[MODAL] Sprawdzanie akceptacji przez klienta:', {
        statusName: quoteData.status_name,
        statusId: quoteData.status_id,
        isClientEditable: quoteData.is_client_editable,
        isAcceptedByName,
        isAcceptedById,
        isAcceptedByEditability,
        acceptedByEmail: quoteData.accepted_by_email
    });

    // Wycena jest zaakceptowana przez klienta jeśli spełnia warunki I nie jest akceptacją wewnętrzną
    const isAccepted = (isAcceptedByName || isAcceptedById || isAcceptedByEditability);
    const isInternalAcceptance = quoteData.accepted_by_email && quoteData.accepted_by_email.startsWith('internal_user_');
    
    // Zwróć true tylko dla akceptacji przez klienta (nie wewnętrznej)
    return isAccepted && !isInternalAcceptance;
}

function checkIfQuoteOrdered(quoteData) {
    // Sprawdź czy wycena ma przypisane zamówienie Baselinker
    const hasBaselinkerOrder = quoteData.base_linker_order_id && quoteData.base_linker_order_id > 0;

    // Sprawdź po nazwie statusu (ID 4 = Złożone)
    const isOrderedByStatus = quoteData.status_id === 4;

    console.log('[MODAL] Sprawdzanie złożenia zamówienia:', {
        statusId: quoteData.status_id,
        baselinkerOrderId: quoteData.base_linker_order_id,
        hasBaselinkerOrder,
        isOrderedByStatus
    });

    return hasBaselinkerOrder || isOrderedByStatus;
}

// 4. DODAJ funkcję do dodawania bannera akceptacji
function addAcceptanceBanner(modalBox, quoteData) {
    // Usuń istniejący banner jeśli jest
    removeAcceptanceBanner(modalBox);

    // Sprawdź czy są dane o akceptacji
    let acceptanceDate = '';
    if (quoteData.acceptance_date) {
        const date = new Date(quoteData.acceptance_date);
        acceptanceDate = date.toLocaleString('pl-PL');
    }

    const banner = document.createElement('div');
    banner.className = 'acceptance-banner';
    banner.innerHTML = `
        <svg class="banner-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
        </svg>
        <div class="banner-text">
            <div>Wycena została zaakceptowana przez klienta</div>
            ${acceptanceDate ? `<div class="banner-date">Data akceptacji: ${acceptanceDate}</div>` : ''}
        </div>
    `;

    // Wstaw banner na początku modalBox (po headerze)
    const header = modalBox.querySelector('.sticky-header');
    if (header && header.nextSibling) {
        modalBox.insertBefore(banner, header.nextSibling);
    } else {
        modalBox.appendChild(banner);
    }
}

function removeAcceptanceBanner(modalBox) {
    const existingBanner = modalBox.querySelector('.acceptance-banner');
    if (existingBanner) {
        existingBanner.remove();
    }
}

function addOrderBanner(modalBox, quoteData) {
    // Usuń istniejący banner jeśli jest
    removeOrderBanner(modalBox);

    // Sprawdź czy są dane o zamówieniu
    let orderDate = '';
    if (quoteData.order_date) {
        const date = new Date(quoteData.order_date);
        orderDate = date.toLocaleString('pl-PL');
    }

    const banner = document.createElement('div');
    banner.className = 'order-banner';
    banner.innerHTML = `
        <svg class="banner-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
        </svg>
        <div class="banner-text">
            <div>Zamówienie zostało złożone w systemie Baselinker</div>
            ${quoteData.base_linker_order_id ? `<div class="banner-date">Numer zamówienia: #${quoteData.base_linker_order_id}</div>` : ''}
        </div>
    `;

    // Wstaw banner na początku modalBox (po headerze)
    const header = modalBox.querySelector('.sticky-header');
    if (header && header.nextSibling) {
        modalBox.insertBefore(banner, header.nextSibling);
    } else {
        modalBox.appendChild(banner);
    }
}

function removeOrderBanner(modalBox) {
    const existingBanner = modalBox.querySelector('.order-banner');
    if (existingBanner) {
        existingBanner.remove();
    }
}

// POPRAWIONA funkcja wyświetlania kosztów - wklej do app/modules/quotes/static/js/quotes.js
function updateCostsDisplay(quoteData) {
    console.log('[updateCostsDisplay] Aktualizuję wyświetlanie kosztów', quoteData);

    // Sprawdź czy istnieją elementy DOM dla nowej struktury
    const productsBrutto = document.getElementById('quotes-details-modal-cost-products-brutto');
    const productsNetto = document.getElementById('quotes-details-modal-cost-products-netto');

    if (productsBrutto && productsNetto) {
        // NOWA STRUKTURA - elementy istnieją
        if (quoteData.costs) {
            // Użyj nowej struktury z backendu
            const costs = quoteData.costs;

            // Koszt surowych
            document.getElementById('quotes-details-modal-cost-products-brutto').textContent = `${costs.products.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-netto').textContent = `${costs.products.netto.toFixed(2)} PLN`;

            // Koszt wykończenia
            document.getElementById('quotes-details-modal-cost-finishing-brutto').textContent = `${costs.finishing.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-finishing-netto').textContent = `${costs.finishing.netto.toFixed(2)} PLN`;

            // NOWE: Suma produktów bez dostawy (surowe + wykończenie)
            const productsTotalNetto = costs.products.netto + costs.finishing.netto;
            const productsTotalBrutto = costs.products.brutto + costs.finishing.brutto;

            document.getElementById('quotes-details-modal-cost-products-total-brutto').textContent = `${productsTotalBrutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-total-netto').textContent = `${productsTotalNetto.toFixed(2)} PLN`;

            // Koszt wysyłki
            document.getElementById('quotes-details-modal-cost-shipping-brutto').textContent = `${costs.shipping.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-shipping-netto').textContent = `${costs.shipping.netto.toFixed(2)} PLN`;

            // Koszt całkowity
            document.getElementById('quotes-details-modal-cost-total-brutto').textContent = `${costs.total.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-total-netto').textContent = `${costs.total.netto.toFixed(2)} PLN`;

            // Kurier - wypełnij nazwę kuriera
            const courierElement = document.getElementById('quotes-details-modal-courier-name');
            if (courierElement) {
                courierElement.textContent = quoteData.courier_name || '-';
            }
        } else {
            // Oblicz VAT po stronie frontend
            const costs = calculateCostsClientSide(quoteData);

            // Koszt surowych
            document.getElementById('quotes-details-modal-cost-products-brutto').textContent = `${costs.products.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-netto').textContent = `${costs.products.netto.toFixed(2)} PLN`;

            // Koszt wykończenia
            document.getElementById('quotes-details-modal-cost-finishing-brutto').textContent = `${costs.finishing.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-finishing-netto').textContent = `${costs.finishing.netto.toFixed(2)} PLN`;

            // NOWE: Suma produktów bez dostawy
            const productsTotalNetto = costs.products.netto + costs.finishing.netto;
            const productsTotalBrutto = costs.products.brutto + costs.finishing.brutto;

            document.getElementById('quotes-details-modal-cost-products-total-brutto').textContent = `${productsTotalBrutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-total-netto').textContent = `${productsTotalNetto.toFixed(2)} PLN`;

            // Koszt wysyłki
            document.getElementById('quotes-details-modal-cost-shipping-brutto').textContent = `${costs.shipping.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-shipping-netto').textContent = `${costs.shipping.netto.toFixed(2)} PLN`;

            // Koszt całkowity
            document.getElementById('quotes-details-modal-cost-total-brutto').textContent = `${costs.total.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-total-netto').textContent = `${costs.total.netto.toFixed(2)} PLN`;

            // Kurier - wypełnij nazwę kuriera
            const courierElement = document.getElementById('quotes-details-modal-courier-name');
            if (courierElement) {
                courierElement.textContent = quoteData.courier_name || '-';
            }
        }
    } else {
        // STARA STRUKTURA - fallback do starych elementów
        console.warn('[updateCostsDisplay] Używam starej struktury DOM');

        const costs = quoteData.costs || calculateCostsClientSide(quoteData);

        // Spróbuj znaleźć stare elementy
        const oldProducts = document.getElementById('quotes-details-modal-cost-products');
        const oldFinishing = document.getElementById('quotes-details-modal-cost-finishing');
        const oldShipping = document.getElementById('quotes-details-modal-cost-shipping');
        const oldTotal = document.getElementById('quotes-details-modal-cost-total');

        if (oldProducts) oldProducts.textContent = `${costs.products?.brutto?.toFixed(2) || '0.00'} PLN`;
        if (oldFinishing) oldFinishing.textContent = `${costs.finishing?.brutto?.toFixed(2) || '0.00'} PLN`;
        if (oldShipping) oldShipping.textContent = `${costs.shipping?.brutto?.toFixed(2) || '0.00'} PLN`;
        if (oldTotal) oldTotal.textContent = `${costs.total?.brutto?.toFixed(2) || '0.00'} PLN`;
    }
    // NOWE: Sekcja Baselinker
    updateBaselinkerSection(quoteData);
}
function updateBaselinkerSection(quoteData) {
    const section = document.getElementById('baselinker-section');
    const orderNumber = document.getElementById('baselinker-order-number');
    const orderLink = document.getElementById('baselinker-order-link');
    const orderStatus = document.getElementById('baselinker-order-status');
    
    if (!section || !orderNumber || !orderLink || !orderStatus) {
        console.warn('[updateBaselinkerSection] Brak elementów sekcji Baselinker');
        return;
    }
    
    // Sprawdź czy wycena ma zamówienie Baselinker
    if (quoteData.base_linker_order_id) {
        section.style.display = 'block';
        orderNumber.textContent = `#${quoteData.base_linker_order_id}`;
        orderLink.href = `https://panel-f.baselinker.com/orders.php#order:${quoteData.base_linker_order_id}`;
        
        // Pobierz status z Baselinker (asynchronicznie)
        fetchBaselinkerOrderStatus(quoteData.base_linker_order_id)
            .then(status => {
                orderStatus.textContent = status || 'Nieznany';
            })
            .catch(error => {
                console.error('[updateBaselinkerSection] Błąd pobierania statusu:', error);
                orderStatus.textContent = 'Błąd pobierania lub nie znaleziono zamówienia';
            });
    } else {
        section.style.display = 'none';
    }
}

async function fetchBaselinkerOrderStatus(orderId) {
    console.log(`[fetchBaselinkerOrderStatus] Rozpoczynam pobieranie statusu dla zamówienia ID: ${orderId}`);
    
    try {
        const url = `/baselinker/api/order/${orderId}/status`;
        console.log(`[fetchBaselinkerOrderStatus] URL żądania: ${url}`);
        
        const response = await fetch(url);
        console.log(`[fetchBaselinkerOrderStatus] Odpowiedź HTTP status: ${response.status}`);
        
        if (!response.ok) {
            console.error(`[fetchBaselinkerOrderStatus] HTTP błąd: ${response.status} ${response.statusText}`);
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('[fetchBaselinkerOrderStatus] Pełna odpowiedź z API:', data);
        console.log('[fetchBaselinkerOrderStatus] status_name z odpowiedzi:', data.status_name);
        
        const statusName = data.status_name || 'Nieznany';
        console.log(`[fetchBaselinkerOrderStatus] Zwracam status: "${statusName}"`);
        
        return statusName;
    } catch (error) {
        console.error('[fetchBaselinkerOrderStatus] Błąd podczas pobierania statusu:', error);
        console.error('[fetchBaselinkerOrderStatus] Stack trace:', error.stack);
        return 'Błąd pobierania lub nie znaleziono zamówienia';
    }
}

function calculateCostsClientSide(quoteData) {
    const VAT_RATE = 0.23;

    const costProducts = parseFloat(quoteData.cost_products || 0);
    const costFinishing = parseFloat(quoteData.cost_finishing || 0);
    const costShipping = parseFloat(quoteData.cost_shipping || 0);

    // Oblicz brutto dla produktów i wykończenia (zakładamy że są netto)
    const productsBrutto = costProducts * (1 + VAT_RATE);
    const finishingBrutto = costFinishing * (1 + VAT_RATE);

    // Dla wysyłki zakładamy że jest brutto, więc oblicz netto
    const shippingNetto = costShipping / (1 + VAT_RATE);

    const totalNetto = costProducts + costFinishing + shippingNetto;
    const totalBrutto = productsBrutto + finishingBrutto + costShipping;

    return {
        products: { netto: costProducts, brutto: productsBrutto },
        finishing: { netto: costFinishing, brutto: finishingBrutto },
        shipping: { netto: shippingNetto, brutto: costShipping },
        total: { netto: totalNetto, brutto: totalBrutto }
    };
}

function setupStatusDropdown(quoteData, optionsContainer, selectedDiv, dropdownWrap) {
    optionsContainer.innerHTML = '';
    Object.values(quoteData.all_statuses).forEach(s => {
        const opt = document.createElement('div');
        opt.className = 'option';
        opt.textContent = s.name;
        opt.style.backgroundColor = s.color || '#999';
        opt.dataset.name = s.name;
        optionsContainer.appendChild(opt);

        if (s.name === quoteData.status_name) {
            selectedDiv.textContent = s.name;
            selectedDiv.style.backgroundColor = s.color || '#999';
        }
    });

    dropdownWrap.classList.remove('open');

    // Event handlers
    optionsContainer.onclick = (e) => {
        const opt = e.target.closest('.option');
        if (!opt) return;
        const newStatus = opt.dataset.name;
        if (!confirm(`Na pewno zmienić status na: ${newStatus}?`)) return;

        fetch(`/quotes/api/quotes/${quoteData.id}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status_id: getStatusIdByName(newStatus, quoteData.all_statuses) })
        })
            .then(() => fetch(`/quotes/api/quotes/${quoteData.id}`))
            .then(res => res.json())
            .then(fullData => {
                showDetailsModal(fullData);
            })
            .catch(err => console.error('[MODAL] Błąd zmiany statusu:', err));
    };

    selectedDiv.onclick = (e) => {
        e.stopPropagation();
        dropdownWrap.classList.toggle('open');
    };

    document.addEventListener('click', (e) => {
        if (!dropdownWrap.contains(e.target)) {
            dropdownWrap.classList.remove('open');
        }
    });
}

function getStatusIdByName(name, statuses) {
    for (const key in statuses) {
        if (statuses[key].name === name) return statuses[key].id;
    }
    return null;
}

function groupItemsByProductIndex(items) {
    const grouped = {};
    items.forEach(item => {
        if (!grouped[item.product_index]) grouped[item.product_index] = [];
        grouped[item.product_index].push(item);
    });
    return grouped;
}
/**
 * Zwraca URL do pliku edit.svg na podstawie URL skryptu quotes.js
 */
function getEditIconURL() {
    const scripts = document.querySelectorAll('script');
    for (let i = 0; i < scripts.length; i++) {
        const src = scripts[i].src;
        if (!src) continue;
        if (src.match(/\/js\/quotes\.js(\?.*)?$/) || src.match(/quotes\.js(\?.*)?$/)) {
            return src.replace(/\/js\/quotes\.js(\?.*)?$/, '/img/edit.svg');
        }
    }
    return '/quotes/static/img/edit.svg';
}

function buildVariantPriceDisplay(variant, quantity, quoteData) {
    // Znajdź szczegóły wykończenia dla tego produktu
    const finishing = (quoteData.finishing || []).find(f => f.product_index == variant.product_index);
    const finishingType = finishing ? finishing.finishing_type : 'Surowe';
    const hasFinishing = finishingType && finishingType !== 'Surowe' && finishingType !== 'Brak';

    // Przygotuj nazwę wariantu
    const variantName = translateVariantCode(variant.variant_code);

    // Przelicz ceny jednostkowe i całkowite
    const unitPriceBrutto = variant.unit_price_brutto || variant.final_price_brutto || 0;
    const unitPriceNetto = variant.unit_price_netto || variant.final_price_netto || 0;
    const totalBrutto = unitPriceBrutto * quantity;
    const totalNetto = unitPriceNetto * quantity;

    // Ceny wykończenia (jeśli istnieje)
    let finishingPriceBrutto = 0;
    let finishingPriceNetto = 0;
    if (finishing) {
        const finishingQuantity = finishing.quantity || quantity || 1;
        finishingPriceBrutto = (finishing.finishing_price_brutto || 0) / finishingQuantity;
        finishingPriceNetto = (finishing.finishing_price_netto || 0) / finishingQuantity;
    }
    const finishingTotalBrutto = finishingPriceBrutto * quantity;
    const finishingTotalNetto = finishingPriceNetto * quantity;

    // Przygotuj HTML kafelka
    let cardHTML = `
        <div class="qvmd-variant-card ${variant.is_selected ? 'qvmd-selected' : ''}">
            ${buildVariantBadges(variant)}
            <div class="qvmd-wood-texture" style="background-image: url('/quotes/quotes/static/img/${variant.variant_code}.jpg');"></div>
            <div class="qvmd-variant-content">
                <div class="qvmd-variant-header">
                    <div class="qvmd-variant-title">Wariant: <span class="qvmd-variant-name">${variantName}</span></div>
                    <div class="qvmd-price-per-m2-wrapper">
                        <div class="qvmd-price-per-m2-label">Cena za m³:</div>
                        <div class="qvmd-price-per-m2-value">${variant.price_per_m3.toFixed(2)} PLN netto</div>
                    </div>
                </div>

                <div class="qvmd-pricing-section">
    `;

    if (hasFinishing) {
        // Layout z wykończeniem - etykiety z lewej, kolumny z prawej
        cardHTML += `
                <div class="qvmd-pricing-with-finishing">
                    <!-- Nagłówki kolumn -->
                    <div class="qvmd-headers-row">
                        <div class="qvmd-label-spacer"></div>
                        <div class="qvmd-column-header">SUROWE</div>
                        <div class="qvmd-column-header qvmd-finishing">Z WYKOŃCZENIEM</div>
                    </div>
                    
                    <!-- Wiersz "Cena" -->
                    <div class="qvmd-pricing-row">
                        <span class="qvmd-pricing-label">Cena</span>
                        <div class="qvmd-pricing-values">
                            <div class="qvmd-price-brutto">${unitPriceBrutto.toFixed(2)} PLN brutto</div>
                            <div class="qvmd-price-netto">${unitPriceNetto.toFixed(2)} PLN netto</div>
                        </div>
                        <div class="qvmd-pricing-values">
                            <div class="qvmd-price-brutto qvmd-finishing">${(unitPriceBrutto + finishingPriceBrutto).toFixed(2)} PLN brutto</div>
                            <div class="qvmd-price-netto">${(unitPriceNetto + finishingPriceNetto).toFixed(2)} PLN netto</div>
                        </div>
                    </div>
                    
                    <!-- Wiersz "Wartość" -->
                    <div class="qvmd-pricing-row">
                        <span class="qvmd-pricing-label">Wartość</span>
                        <div class="qvmd-pricing-values">
                            <div class="qvmd-price-brutto">${totalBrutto.toFixed(2)} PLN brutto</div>
                            <div class="qvmd-price-netto">${totalNetto.toFixed(2)} PLN netto</div>
                        </div>
                        <div class="qvmd-pricing-values">
                            <div class="qvmd-price-brutto qvmd-finishing">${(totalBrutto + finishingTotalBrutto).toFixed(2)} PLN brutto</div>
                            <div class="qvmd-price-netto">${(totalNetto + finishingTotalNetto).toFixed(2)} PLN netto</div>
                        </div>
                    </div>
                </div>
    `;
    } else {
        // Layout surowy (prosta kolumna)
        cardHTML += `
                    <div class="qvmd-pricing-simple">
                        <div class="qvmd-pricing-row">
                            <span class="qvmd-pricing-label">Cena</span>
                            <div class="qvmd-pricing-values">
                                <div class="qvmd-price-brutto">${unitPriceBrutto.toFixed(2)} PLN brutto</div>
                                <div class="qvmd-price-netto">${unitPriceNetto.toFixed(2)} PLN netto</div>
                            </div>
                        </div>
                        <div class="qvmd-pricing-row">
                            <span class="qvmd-pricing-label">Wartość</span>
                            <div class="qvmd-pricing-values">
                                <div class="qvmd-price-brutto">${totalBrutto.toFixed(2)} PLN brutto</div>
                                <div class="qvmd-price-netto">${totalNetto.toFixed(2)} PLN netto</div>
                            </div>
                        </div>
                    </div>
        `;
    }

    // Dodaj banner rabatu jeśli istnieje
    if (variant.has_discount && variant.discount_percentage !== 0) {
        const discountReasonName = getDiscountReasonName(variant.discount_reason_id);
        cardHTML += `
                    <div class="qvmd-discount-banner">
                        <div class="qvmd-discount-banner-title">Rabat ${variant.discount_percentage}%</div>
                        <div class="qvmd-discount-banner-reason">Powód: ${discountReasonName || 'Nie podano'}</div>
                    </div>
        `;
    }

    cardHTML += `
                </div>

                <div class="qvmd-variant-actions">
    `;

    // Przyciski akcji
    if (variant.is_selected) {
        cardHTML += `<button class="qvmd-btn qvmd-btn-selected">✓ Wybrany wariant</button>`;
    } else {
        cardHTML += `<button class="qvmd-btn" onclick="selectVariant(${variant.id})">Ustaw jako wybrany</button>`;
    }

    cardHTML += `
                    <button class="qvmd-btn qvmd-btn-edit" onclick="openVariantEditModal(${JSON.stringify(variant).replace(/"/g, '&quot;')}, currentQuoteData)">
                        <img src="/quotes/quotes/static/img/edit.svg" alt="Edytuj" class="qvmd-edit-icon">
                    </button>
                </div>
            </div>
        </div>
    `;

    return cardHTML;
}

/**
 * 2. DODAJ TĘ NOWĄ FUNKCJĘ (wstaw gdziekolwiek po buildVariantPriceDisplay)
 */
function buildVariantBadges(variant) {
    let badgesHTML = '';
    const badges = [];

    // Badge "Niewidoczny"
    if (variant.show_on_client_page === false) {
        badges.push('<div class="qvmd-badge qvmd-badge-invisible">Niewidoczny</div>');
    }

    // Badge "Rabat"
    if (variant.has_discount && variant.discount_percentage !== 0) {
        badges.push(`<div class="qvmd-badge qvmd-badge-discount">Rabat ${variant.discount_percentage}%</div>`);
    }

    if (badges.length > 0) {
        badgesHTML = `
            <div class="qvmd-variant-badges">
                ${badges.join('')}
            </div>
        `;
    }

    return badgesHTML;
}

/**
 * 3. DODAJ TĘ NOWĄ FUNKCJĘ (wstaw gdziekolwiek po buildVariantBadges)
 */
function selectVariant(variantId) {
    if (!confirm('Na pewno zmienić wybór wariantu?')) return;

    fetch(`/quotes/api/quote_items/${variantId}/select`, { method: 'PATCH' })
        .then(res => res.json())
        .then(() => fetch(`/quotes/api/quotes/${currentQuoteData.id}`))
        .then(res => res.json())
        .then(fullData => showDetailsModal(fullData))
        .catch(err => console.error('[MODAL] Błąd zmiany wariantu:', err));
}

/**
 * Główna funkcja budująca zakładki produktów i listę wariantów
 * ZASTĄP CAŁĄ ISTNIEJĄCĄ FUNKCJĘ setupProductTabs tym kodem
 */
function setupProductTabs(quoteData, tabsContainer, itemsContainer) {
    const items = quoteData.items || [];
    const grouped = groupItemsByProductIndex(items);

    tabsContainer.innerHTML = '';
    itemsContainer.innerHTML = '';

    // Wyliczamy URL do SVG raz i użyjemy dalej
    const editIconURL = getEditIconURL();

    const indexes = Object.keys(grouped);
    indexes.forEach((index, idx) => {
        // ——— 1. Tworzenie przycisku zakładki ———
        const tabBtn = document.createElement('button');
        tabBtn.className = 'tab-button';
        tabBtn.textContent = `Produkt ${idx + 1}`;
        tabBtn.dataset.tabIndex = index;
        if (idx === 0) tabBtn.classList.add('active');
        tabsContainer.appendChild(tabBtn);

        // ——— 2. Tworzenie kontenera z zawartością zakładki ———
        const tabContent = document.createElement('div');
        tabContent.className = 'tab-content';
        tabContent.style.display = idx === 0 ? 'block' : 'none';
        tabContent.dataset.tabIndex = index;

        // Jeżeli istnieje nagłówek z podsumowaniem wariantów
        const summaryHeader = renderVariantSummary(grouped[index], quoteData, index);
        if (summaryHeader) {
            tabContent.appendChild(summaryHeader);
        }

        // ——— 3. NOWY LAYOUT: KAFELKI WARIANTÓW ———

        // Znajdź warianty z wykończeniem
        const variantsWithFinishing = grouped[index].filter(item => {
            const finishing = (quoteData.finishing || []).find(f => f.product_index == index);
            const finishingType = finishing ? finishing.finishing_type : 'Surowe';
            return finishingType && finishingType !== 'Surowe' && finishingType !== 'Brak';
        });

        // Znajdź warianty surowe
        const rawVariants = grouped[index].filter(item => {
            const finishing = (quoteData.finishing || []).find(f => f.product_index == index);
            const finishingType = finishing ? finishing.finishing_type : 'Surowe';
            return !finishingType || finishingType === 'Surowe' || finishingType === 'Brak';
        });

        // Grid dla wariantów z wykończeniem
        if (variantsWithFinishing.length > 0) {
            const finishingGridDiv = document.createElement('div');
            finishingGridDiv.className = 'qvmd-variants-grid qvmd-with-finishing';
            finishingGridDiv.innerHTML = variantsWithFinishing
                .map(item => {
                    const finishing = (quoteData.finishing || []).find(f => f.product_index == index);
                    const quantity = finishing ? (finishing.quantity || 1) : 1;
                    return buildVariantPriceDisplay(item, quantity, quoteData);
                })
                .join('');
            tabContent.appendChild(finishingGridDiv);
        }

        // Grid dla wariantów surowych
        if (rawVariants.length > 0) {
            const rawGridDiv = document.createElement('div');
            rawGridDiv.className = 'qvmd-variants-grid';
            rawGridDiv.innerHTML = rawVariants
                .map(item => {
                    const finishing = (quoteData.finishing || []).find(f => f.product_index == index);
                    const quantity = finishing ? (finishing.quantity || 1) : 1;
                    return buildVariantPriceDisplay(item, quantity, quoteData);
                })
                .join('');
            tabContent.appendChild(rawGridDiv);
        }

        itemsContainer.appendChild(tabContent);
    });

    // ——— 6. Obsługa przełączania zakładek ———
    tabsContainer.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            const activeIdx = btn.dataset.tabIndex;
            tabsContainer.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            itemsContainer.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');

            btn.classList.add('active');
            const activeContent = itemsContainer.querySelector(`.tab-content[data-tab-index='${activeIdx}']`);
            if (activeContent) {
                activeContent.style.display = 'block';
            }
        });
    });
}

function filterQuotes() {
    console.log("Filtrujemy wyceny...");

    const quoteNumber = document.getElementById("quote-number-filter")?.value?.toLowerCase() || "";
    const clientNumber = document.getElementById("client-number-filter")?.value?.toLowerCase() || "";
    const clientName = document.getElementById("client-name-filter")?.value?.toLowerCase() || "";
    const source = document.getElementById("source-filter")?.value || "";
    const employee = document.getElementById("employee-filter")?.value || "";
    const dateFrom = document.getElementById("date-from-filter")?.value;
    const dateTo = document.getElementById("date-to-filter")?.value;

    const filtered = allQuotes.filter(q => {
        const createdDate = new Date(q.created_at);
        const matchDateFrom = !dateFrom || createdDate >= new Date(dateFrom);
        const matchDateTo = !dateTo || createdDate <= new Date(dateTo);

        return (!quoteNumber || q.quote_number?.toLowerCase().startsWith(quoteNumber)) &&
            (!clientNumber || (q.client_number || "").toLowerCase().includes(clientNumber)) &&
            (!clientName || (q.client_name || "").toLowerCase().includes(clientName)) &&
            (!source || q.source === source) &&
            (!employee || q.user_id == employee) &&
            matchDateFrom &&
            matchDateTo &&
            (!activeStatus || q.status_name === activeStatus);
    });

    console.log(`[filterQuotes] Wszystkich wyników: ${filtered.length}, currentPage: ${currentPage}, resultsPerPage: ${resultsPerPage}`);
    const paginated = filtered.slice((currentPage - 1) * resultsPerPage, currentPage * resultsPerPage);

    renderQuotesTable(paginated);
    renderPagination(filtered.length);
}

function renderQuotesTable(quotes) {
    const wrapper = document.getElementById("quotes-table-body");
    const noResults = document.getElementById("no-results-message");
    wrapper.innerHTML = "";
    if (noResults) noResults.remove();
    if (quotes.length === 0) {
        const msg = document.createElement("div");
        msg.id = "no-results-message";
        msg.className = "no-results-message";
        msg.innerHTML = `<div style="text-align: center; width: 100%;">Brak pasujących wyników</div>`;
        wrapper.appendChild(msg);
        return;
    }
    quotes.forEach(quote => {
        const card = document.createElement("div");
        card.className = "quote-card";
        const statusPill = `
            <div class="quote-status-pill" style="background-color: ${quote.status_color}">
                ${quote.status_name}
            </div>
        `;
        card.innerHTML = `
            <div class="quote-field">${quote.quote_number}</div>
            <div class="quote-field">${new Date(quote.created_at).toLocaleDateString()}</div>
            <div class="quote-field">${quote.client_name || "-"}</div>
            <div class="quote-field">${quote.client_number || "-"}</div>
            <div class="quote-field">${quote.client_caretaker_name || "-"}</div>
            <div class="quote-field">${quote.source || "-"}</div>
            <div class="quote-field">${statusPill}</div>
            <div class="quote-field">
                <button class="quotes-btn quotes-btn-detail" data-id="${quote.id}">
                    <span>Szczegóły</span>
                </button>
                <button class="quotes-btn quotes-btn-download" data-token="${quote.public_token}">
                    <span>Pobierz</span>
                </button>
            </div>
        `;
        wrapper.appendChild(card);
    });
    document.querySelectorAll(".quotes-btn-detail").forEach(btn => {
        btn.addEventListener("click", async e => {
            const id = e.target.closest("button").dataset.id;
            try {
                const res = await fetch(`/quotes/api/quotes/${id}`);
                if (!res.ok) throw new Error("Błąd pobierania szczegółów wyceny");
                const data = await res.json();
                showDetailsModal(data);
            } catch (err) {
                console.error("[MODAL] Błąd ładowania danych:", err);
                alert("Nie udało się załadować szczegółów wyceny.");
            }
        });
    });
    document.querySelectorAll(".quotes-btn-download").forEach(btn => {
        btn.addEventListener("click", e => {
            const token = e.target.closest("button").dataset.token;
            console.log(`Kliknięto pobierz dla TOKEN ${token}`);
        });
    });
}

function renderStatusButton(name, count, color, isActive = false) {
    const btn = document.createElement("div");
    btn.className = "status-button";
    if (isActive) btn.classList.add("active");

    const countSpan = document.createElement("span");
    countSpan.className = "status-count";
    countSpan.textContent = count > 0 ? count : "-";

    if (color) {
        countSpan.style.backgroundColor = color;
    }

    const labelSpan = document.createElement("span");
    labelSpan.textContent = name;

    btn.appendChild(countSpan);
    btn.appendChild(labelSpan);

    btn.addEventListener("click", () => {
        document.querySelectorAll(".status-button").forEach(b => {
            b.classList.remove("active");
        });
        btn.classList.add("active");

        activeStatus = name === "Wszystkie" ? null : name;
        filterQuotes();
    });

    return btn;
}

async function initStatusPanel() {
    const statusPanel = document.getElementById("status-filters-container");
    statusPanel.innerHTML = "";

    try {
        const [counts, statuses] = await Promise.all([
            fetch("/quotes/api/quotes/status-counts").then(res => res.json()),
            fetch("/quotes/api/quotes").then(res => res.json())
        ]);

        const totalCount = counts.reduce((sum, s) => sum + s.count, 0);
        const allBtn = renderStatusButton("Wszystkie", totalCount, "#999", true);
        statusPanel.appendChild(allBtn);

        counts.forEach(status => {
            const btn = renderStatusButton(status.name, status.count, status.color);
            statusPanel.appendChild(btn);
        });
    } catch (error) {
        console.error("Błąd inicjalizacji panelu statusów:", error);
    }
}

// Event listeners dla filtrów
document.addEventListener("DOMContentLoaded", () => {
    ["quote-number-filter", "client-number-filter", "client-name-filter", "source-filter"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            const evt = el.tagName === "SELECT" ? "change" : "input";
            el.addEventListener(evt, filterQuotes);
        }
    });

    ["date-from-filter", "date-to-filter", "employee-filter"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("change", filterQuotes);
        }
    });
});

function renderPagination(total) {
    console.log(`[renderPagination] Łącznie wyników: ${total}, resultsPerPage: ${resultsPerPage}`);

    let container = document.getElementById("pagination-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "pagination-container";
        container.className = "quotes-pagination";
        document.querySelector(".quotes-main").appendChild(container);
    }

    container.innerHTML = "";

    const totalPages = Math.ceil(total / resultsPerPage);

    // Selektor ilości wyników na stronę
    const select = document.createElement("select");
    select.className = "pagination-select";

    [20, 50, 100, 200].forEach(n => {
        const opt = document.createElement("option");
        opt.value = n;
        opt.textContent = `${n}`;
        if (n === resultsPerPage) opt.selected = true;
        select.appendChild(opt);
    });

    select.addEventListener("change", () => {
        resultsPerPage = parseInt(select.value);
        currentPage = 1;
        filterQuotes();
    });

    // Paginacja
    const pagination = document.createElement("div");
    pagination.className = "quotes-pagination";

    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement("button");
        btn.textContent = i;
        if (i === currentPage) btn.classList.add("active");
        btn.addEventListener("click", () => {
            currentPage = i;
            filterQuotes();
        });
        pagination.appendChild(btn);
    }

    container.appendChild(pagination);
    container.appendChild(select);
}

function initClearFiltersButton() {
    const btn = document.getElementById("clear-filters");
    if (!btn) {
        console.warn("Przycisk #clear-filters nie znaleziony");
        return;
    }

    btn.addEventListener("click", () => {
        ["quote-number-filter", "client-number-filter", "client-name-filter", "source-filter", "employee-filter"].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });

        document.getElementById("date-from-filter").value = "";
        document.getElementById("date-to-filter").value = "";

        document.querySelectorAll(".status-button").forEach(btn => btn.classList.remove("active"));
        activeStatus = null;

        filterQuotes();
        updateClearFiltersButtonState();
    });

    // Event listeners dla aktualizacji stanu przycisku
    ["quote-number-filter", "client-number-filter", "client-name-filter", "source-filter", "employee-filter", "date-from-filter", "date-to-filter"]
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("input", updateClearFiltersButtonState);
                el.addEventListener("change", updateClearFiltersButtonState);
            }
        });
}

function updateClearFiltersButtonState() {
    const filters = [
        "quote-number-filter", "client-number-filter", "client-name-filter",
        "source-filter", "employee-filter", "date-from-filter", "date-to-filter"
    ];

    const anyActive = filters.some(id => {
        const el = document.getElementById(id);
        return el && el.value !== "";
    });

    const btn = document.getElementById("clear-filters");
    if (!btn) return;

    if (anyActive || activeStatus !== null) {
        btn.classList.remove("hidden");
        btn.classList.add("active");
    } else {
        btn.classList.remove("active");
        btn.classList.add("hidden");
    }
}

function renderSelectedSummary(groupedItems, container) {
    container.innerHTML = "";
    let totalVolume = 0;
    let totalWeight = 0;
    Object.keys(groupedItems).forEach((index, idx) => {
        const selected = groupedItems[index].find(i => i.is_selected) || groupedItems[index][0];
        if (!selected) return;

        const variant = translateVariantCode(selected.variant_code) || "Nieznany wariant";
        const dims = `${selected.length_cm}×${selected.width_cm}×${selected.thickness_cm} cm`;

        // Znajdź szczegóły wykończenia dla tego produktu
        const finishing = window.currentQuoteData ?
            (window.currentQuoteData.finishing || []).find(f => f.product_index == index) : null;

        // Pobierz ilość z finishing details lub domyślnie 1
        const quantity = finishing ? (finishing.quantity || 1) : 1;

        // Oblicz ceny bazowe produktu
        const baseUnitPriceBrutto = selected.unit_price_brutto || selected.final_price_brutto || 0;
        const baseUnitPriceNetto = selected.unit_price_netto || selected.final_price_netto || 0;

        // Dodaj cenę wykończenia do ceny jednostkowej (jeśli istnieje)
        let finalUnitPriceBrutto = baseUnitPriceBrutto;
        let finalUnitPriceNetto = baseUnitPriceNetto;

        if (finishing && finishing.finishing_price_brutto) {
            const finishingQuantity = finishing.quantity || quantity || 1;
            finalUnitPriceBrutto += parseFloat(finishing.finishing_price_brutto || 0) / finishingQuantity;
        }
        if (finishing && finishing.finishing_price_netto) {
            const finishingQuantity = finishing.quantity || quantity || 1;
            finalUnitPriceNetto += parseFloat(finishing.finishing_price_netto || 0) / finishingQuantity;
        }

        // Oblicz wartości całkowite (cena jednostkowa × ilość)
        const totalBrutto = finalUnitPriceBrutto * quantity;
        const totalNetto = finalUnitPriceNetto * quantity;

        // Oblicz objętość (m³) i wagę (kg)
        let itemVolume = 0;
        if (selected.volume_m3) {
            itemVolume = parseFloat(selected.volume_m3) * quantity;
        } else if (selected.length_cm && selected.width_cm && selected.thickness_cm) {
            itemVolume = (selected.length_cm / 100) * (selected.width_cm / 100) * (selected.thickness_cm / 100) * quantity;
        }
        const itemWeight = itemVolume * 800; // gęstość drewna
        totalVolume += itemVolume;
        totalWeight += itemWeight;

        // Przygotuj opis wykończenia dla wyświetlenia
        let finishingText = '';
        if (finishing && finishing.finishing_type && finishing.finishing_type !== 'Brak' && finishing.finishing_type !== 'Surowe') {
            const finishingParts = [];

            if (finishing.finishing_type) {
                finishingParts.push(finishing.finishing_type);
            }
            if (finishing.finishing_color && finishing.finishing_color !== 'Brak') {
                finishingParts.push(finishing.finishing_color);
            }
            if (finishing.application_method && finishing.application_method !== 'Brak') {
                finishingParts.push(finishing.application_method);
            }

            finishingText = finishingParts.length > 0 ? ` ${finishingParts.join(' ')}` : '';
        }

        const p = document.createElement("p");
        p.className = "selected-summary-item";
        p.innerHTML = `
            <span class='dot'></span>
            <span style="font-size: 14px; font-weight: 600;">Produkt ${parseInt(index)}:</span>
            <span style="font-size: 12px; font-weight: 400;">
                ${variant} ${dims}${finishingText} • ${quantity} szt. • 
                ${formatPriceWithNetto(totalBrutto, totalNetto)}
            </span>
        `;
        container.appendChild(p);
    });

    // Dodaj podsumowanie łącznej objętości i wagi
    const totals = document.createElement('p');
    totals.className = 'summary-totals';
    totals.innerHTML = `<span style="font-weight: 600;">Łączna objętość:</span>${formatVolumeDisplay(totalVolume)} <span style="font-weight: 600;">Łączna waga:</span>${formatWeightDisplay(totalWeight)}`;
    container.appendChild(totals);
}

// Updated renderVariantSummary function with quantity editing functionality
function renderVariantSummary(groupedItemsForIndex, quoteData, productIndex) {
    const item = groupedItemsForIndex.find(i => i.is_selected) || groupedItemsForIndex[0];
    if (!item) return null;

    const wrap = document.createElement('div');
    wrap.className = 'variant-summary-header';

    const dims = `${item.length_cm} × ${item.width_cm} × ${item.thickness_cm} cm`;
    const volume = item.volume_m3 ? `${item.volume_m3.toFixed(3)} m³` : '-';

    const finishing = (quoteData.finishing || []).find(f => f.product_index == productIndex);
    
    // Pobierz quantity z finishing details lub z item
    const quantity = finishing ? finishing.quantity || 1 : (item.quantity || 1);
    
    // Dodaj informacje o wykończeniu
    let finishingDisplay = 'Brak wykończenia';
    if (finishing && finishing.finishing_type && finishing.finishing_type !== 'Brak') {
        const finishingParts = [];
        
        // Typ wykończenia
        if (finishing.finishing_type) {
            finishingParts.push(finishing.finishing_type);
        }
        
        // Kolor wykończenia
        if (finishing.finishing_color && finishing.finishing_color !== 'Brak') {
            finishingParts.push(finishing.finishing_color);
        }
        
        // Metoda aplikacji
        if (finishing.application_method && finishing.application_method !== 'Brak') {
            finishingParts.push(finishing.application_method);
        }
        
        finishingDisplay = finishingParts.length > 0 ? finishingParts.join(' - ') : 'Brak wykończenia';
    }

    // Oblicz ceny z wykończeniem
    const baseUnitPriceBrutto = item.unit_price_brutto || item.final_price_brutto || 0;
    const baseUnitPriceNetto = item.unit_price_netto || item.final_price_netto || 0;
    
    let finalUnitPriceBrutto = baseUnitPriceBrutto;
    let finalUnitPriceNetto = baseUnitPriceNetto;
    
    // Dodaj cenę wykończenia do ceny jednostkowej
    if (finishing && finishing.finishing_price_brutto) {
        const finishingQuantity = finishing.quantity || quantity || 1;
        finalUnitPriceBrutto += parseFloat(finishing.finishing_price_brutto || 0) / finishingQuantity;
    }
    if (finishing && finishing.finishing_price_netto) {
        const finishingQuantity = finishing.quantity || quantity || 1;
        finalUnitPriceNetto += parseFloat(finishing.finishing_price_netto || 0) / finishingQuantity;
    }
    
    // Oblicz wartości całkowite
    const totalBrutto = finalUnitPriceBrutto * quantity;
    const totalNetto = finalUnitPriceNetto * quantity;

    // Oblicz koszt wykończenia dla wyświetlenia
    let finishingCostDisplay = '0.00 PLN';
    if (finishing && finishing.finishing_price_brutto && parseFloat(finishing.finishing_price_brutto) > 0) {
        const finishingCostBrutto = parseFloat(finishing.finishing_price_brutto || 0);
        const finishingCostNetto = parseFloat(finishing.finishing_price_netto || 0);
        finishingCostDisplay = `${finishingCostBrutto.toFixed(2)} PLN <span class="cost-netto">${finishingCostNetto.toFixed(2)} PLN</span>`;
    }

    wrap.innerHTML = `
        <div class="product-details">
            <div><strong>Wariant:</strong> ${translateVariantCode(item.variant_code) || 'Nieznany wariant'}</div>
            <div><strong>Wymiary:</strong> ${dims}</div>
            <div><strong>Objętość:</strong> ${volume}</div>
            <div><strong>Wykończenie:</strong> ${finishingDisplay}</div>
            <div><strong>Koszt wykończenia:</strong> ${finishingCostDisplay}</div>
        </div>
        <div class="product-pricing">
            <div class="pricing-row" style="align-items: center;">
                <span><strong>Ilość:</strong></span>
                <div class="quantity-container">
                    <span id="quantity-field-${productIndex}">
                        ${quantity} szt.
                        <button class="quantity-edit-btn" data-product-index="${productIndex}" data-current-quantity="${quantity}" title="Zmień ilość">
                            <svg class="edit-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                            </svg>
                        </button>
                    </span>
                    <div id="quantity-edit-${productIndex}" class="quantity-edit-form" style="display: none;">
                        <div class="quantity-input-container">
                            <input type="number" 
                                   class="quantity-input" 
                                   value="${quantity}" 
                                   min="1" 
                                   step="1">
                        </div>
                        <div class="quantity-edit-actions">
                            <button class="quantity-save-btn" data-product-index="${productIndex}">Zapisz</button>
                            <button class="quantity-cancel-btn" data-product-index="${productIndex}">Anuluj</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // WAŻNE: Dodaj event listenery po dodaniu do DOM
    setTimeout(() => {
        setupQuantityEditHandlers(productIndex, quoteData);
    }, 0);

    return wrap;
}

// Funkcja do obsługi edycji ilości
function setupQuantityEditHandlers(productIndex, quoteData) {
    const editBtn = document.querySelector(`.quantity-edit-btn[data-product-index="${productIndex}"]`);
    const saveBtn = document.querySelector(`.quantity-save-btn[data-product-index="${productIndex}"]`);
    const cancelBtn = document.querySelector(`.quantity-cancel-btn[data-product-index="${productIndex}"]`);
    const editForm = document.getElementById(`quantity-edit-${productIndex}`);
    const displayField = document.getElementById(`quantity-field-${productIndex}`);
    const input = editForm?.querySelector('.quantity-input');

    if (!editBtn || !saveBtn || !cancelBtn || !editForm || !displayField || !input) {
        console.warn(`[setupQuantityEditHandlers] Brakuje elementów dla produktu ${productIndex}`);
        return;
    }

    // Obsługa kliknięcia przycisku edycji
    editBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        // Ukryj display i pokaż formularz
        displayField.style.display = 'none';
        editBtn.style.display = 'none';
        editForm.style.display = 'flex';
        
        // Focus na input i zaznacz tekst
        input.focus();
        input.select();
    });

    // Obsługa anulowania
    cancelBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        // Przywróć oryginalną wartość
        const originalQuantity = parseInt(editBtn.dataset.currentQuantity);
        input.value = originalQuantity;
        
        // Ukryj formularz i pokaż display
        editForm.style.display = 'none';
        displayField.style.display = 'inline';
        editBtn.style.display = 'inline-block';
    });

    // Obsługa zapisywania
    saveBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const newQuantity = parseInt(input.value);
        
        // Walidacja
        if (!newQuantity || newQuantity < 1) {
            alert('Ilość musi być liczbą większą od 0');
            input.focus();
            return;
        }

        // Sprawdź czy wartość się zmieniła
        const currentQuantity = parseInt(editBtn.dataset.currentQuantity);
        if (newQuantity === currentQuantity) {
            // Anuluj jeśli nie ma zmian
            cancelBtn.click();
            return;
        }

        // Wyłącz przyciski podczas zapisywania
        saveBtn.disabled = true;
        cancelBtn.disabled = true;
        input.disabled = true;
        
        const originalSaveText = saveBtn.textContent;
        saveBtn.textContent = 'Zapisywanie...';
        saveBtn.classList.add('loading');

        try {
            // Wywołaj API do aktualizacji ilości
            const response = await fetch(`/quotes/api/quotes/${quoteData.id}/update-quantity`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    product_index: productIndex,
                    quantity: newQuantity
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || 'Błąd podczas zapisywania ilości');
            }

            // Sukces - odśwież modal
            console.log(`[setupQuantityEditHandlers] Pomyślnie zaktualizowano ilość produktu ${productIndex} na ${newQuantity}`);
            
            // Pobierz zaktualizowane dane wyceny
            const updatedResponse = await fetch(`/quotes/api/quotes/${quoteData.id}`);
            if (!updatedResponse.ok) {
                throw new Error('Błąd podczas odświeżania danych wyceny');
            }
            
            const updatedQuoteData = await updatedResponse.json();
            
            // Odśwież cały modal z nowymi danymi
            showDetailsModal(updatedQuoteData);
            
        } catch (error) {
            console.error('[setupQuantityEditHandlers] Błąd:', error);
            alert(`Błąd podczas zapisywania ilości: ${error.message}`);
            
            // Przywróć kontrolki w przypadku błędu
            saveBtn.disabled = false;
            cancelBtn.disabled = false;
            input.disabled = false;
            saveBtn.textContent = originalSaveText;
            saveBtn.classList.remove('loading');
            input.focus();
        }
    });

    // Obsługa klawisza Enter i Escape
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveBtn.click();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelBtn.click();
        }
    });

    // Zapobiegaj zamknięciu modala podczas edycji
    editForm.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

function translateVariantCode(code) {
    const dict = {
        'dab-lity-ab': 'Dąb lity A/B',
        'dab-lity-bb': 'Dąb lity B/B',
        'dab-micro-ab': 'Dąb mikrowczep A/B',
        'dab-micro-bb': 'Dąb mikrowczep B/B',
        'jes-lity-ab': 'Jesion lity A/B',
        'jes-micro-ab': 'Jesion mikrowczep A/B',
        'buk-lity-ab': 'Buk lity A/B',
        'buk-micro-ab': 'Buk mikrowczep A/B'
    };
    return dict[code] || code || 'Nieznany wariant';
}
function buildFullProductName(variantCode, dimensions, finishing) {
    // Podstawowa nazwa z gatunku, technologii i klasy
    const baseName = translateVariantCode(variantCode);

    // Formatuj wymiary z odstępem przed "cm"
    const formattedDimensions = dimensions ? `${dimensions} cm` : '';

    // Formatuj wykończenie
    let finishingText = '';
    if (finishing && finishing !== 'Surowe' && finishing !== 'Brak' && finishing !== 'brak') {
        // Konwertuj na małe litery zgodnie z wymaganiem (surowa, lakierowana, olejowana)
        const finishingLower = finishing.toLowerCase();
        finishingText = ` ${finishingLower}`;
    } else {
        finishingText = ' surowa'; // Domyślnie surowa
    }

    return `${baseName} ${formattedDimensions}${finishingText}`.trim();
}

// Pobieranie powodów rabatów z API
async function fetchDiscountReasons() {
    try {
        const response = await fetch('/quotes/api/discount-reasons');

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        // Sprawdź czy response zawiera błąd
        if (data.error) {
            console.error("[fetchDiscountReasons] Błąd z API:", data.error);
            discountReasons = [];
            return;
        }

        // Sprawdź czy data jest tablicą
        if (!Array.isArray(data)) {
            console.error("[fetchDiscountReasons] Nieprawidłowy format danych - oczekiwano tablicy:", data);
            discountReasons = [];
            return;
        }

        discountReasons = data;
        console.log("[fetchDiscountReasons] Pobrano powody rabatów:", discountReasons);

    } catch (error) {
        console.error("[fetchDiscountReasons] Błąd pobierania powodów rabatów:", error);
        discountReasons = [];
    }
}

// Konfiguracja modala edycji wariantu
function setupVariantEditModal() {
    const modal = document.getElementById('edit-variant-modal');
    const closeBtn = document.getElementById('close-edit-variant-modal');
    const saveBtn = document.getElementById('save-variant-changes');
    const cancelBtn = document.getElementById('cancel-variant-changes');
    const discountInput = document.getElementById('discount-percentage');

    if (!modal) return;

    // Zamykanie modala
    closeBtn?.addEventListener('click', () => closeVariantEditModal());
    cancelBtn?.addEventListener('click', () => closeVariantEditModal());

    // Zapisywanie zmian
    saveBtn?.addEventListener('click', () => saveVariantChanges());

    // Live preview cen podczas wpisywania rabatu
    discountInput?.addEventListener('input', () => updatePricePreview());

    // Zamykanie przez kliknięcie tła
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeVariantEditModal();
        }
    });
}

// Konfiguracja modala rabatu całkowitego
function setupTotalDiscountModal() {
    const modal = document.getElementById('edit-total-discount-modal');
    const closeBtn = document.getElementById('close-edit-total-discount-modal');
    const saveBtn = document.getElementById('save-total-discount');
    const cancelBtn = document.getElementById('cancel-total-discount');
    const discountInput = document.getElementById('total-discount-percentage');
    const finishingCheckbox = document.getElementById('include-finishing-discount');

    if (!modal) return;

    // Zamykanie modala
    closeBtn?.addEventListener('click', () => closeTotalDiscountModal());
    cancelBtn?.addEventListener('click', () => closeTotalDiscountModal());

    // Zapisywanie zmian
    saveBtn?.addEventListener('click', () => saveTotalDiscount());

    // Live preview cen
    discountInput?.addEventListener('input', () => updateTotalPricePreview());
    finishingCheckbox?.addEventListener('change', () => updateTotalPricePreview());

    // Zamykanie przez kliknięcie tła
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeTotalDiscountModal();
        }
    });
}

// Otwieranie modala edycji wariantu
function openVariantEditModal(item, quoteData) {
    console.log("[openVariantEditModal] Otwieranie modala dla wariantu:", item);

    currentEditingItem = item;
    currentQuoteData = quoteData;

    // Zapisz oryginalne ceny
    originalPrices = {
        netto: item.original_price_netto || item.final_price_netto,
        brutto: item.original_price_brutto || item.final_price_brutto
    };

    // Wypełnij informacje o wariancie
    document.getElementById('edit-variant-name').textContent = translateVariantCode(item.variant_code);
    document.getElementById('edit-variant-dimensions').textContent = `${item.length_cm}×${item.width_cm}×${item.thickness_cm} cm`;
    document.getElementById('edit-variant-volume').textContent = `${item.volume_m3?.toFixed(3) || '0.000'} m³`;

    // Wypełnij formularz
    document.getElementById('discount-percentage').value = item.discount_percentage || 0;
    document.getElementById('show-on-client-page').checked = item.show_on_client_page !== false;

    // Wypełnij dropdown powodów
    populateDiscountReasons('discount-reason', item.discount_reason_id);

    // Aktualizuj podgląd cen
    updatePricePreview();

    // Pokaż modal
    const modal = document.getElementById('edit-variant-modal');
    modal.style.display = 'flex';
    setTimeout(() => modal.classList.add('active'), 10);
}

// Otwieranie modala rabatu całkowitego
function openTotalDiscountModal(quoteData) {
    console.log("[openTotalDiscountModal] Otwieranie modala rabatu całkowitego");

    currentQuoteData = quoteData;

    // Teraz bierzemy pod uwagę WSZYSTKIE pozycje (warianty) w wycenie, a nie tylko te z is_selected
    const allItems = quoteData.items;

    // Grupujemy po product_index, żeby zobaczyć, ile unikalnych produktów w wycenie
    const allProductsCount = [...new Set(allItems.map(item => item.product_index))].length;

    console.log(`[openTotalDiscountModal] Wszystkich wariantów: ${allItems.length}, Unikalnych produktów: ${allProductsCount}`);

    // Wypełnij podstawowe informacje w modalu
    document.getElementById('total-quote-number').textContent = quoteData.quote_number;
    // Pokazujemy, że liczymy rabat od wszystkich produktów (np. "3 z 3")
    document.getElementById('total-products-count').textContent = `${allProductsCount} z ${allProductsCount}`;

    // Jeżeli w HTML jest element służący do ostrzeżenia o niewybranych wariantach,
    // teraz go ukrywamy, bo robimy rabat na wszystkie.
    const warningBox = document.getElementById('products-selection-warning');
    if (warningBox) {
        warningBox.style.display = 'none';
    }

    // Oblicz oryginalną wartość BRUTTO dla wszystkich wariantów:
    const originalValue = allItems.reduce((sum, item) => {
        // Jeśli item.original_price_brutto jest undefined, użyjemy item.final_price_brutto
        return sum + (item.original_price_brutto || item.final_price_brutto || 0);
    }, 0);

    document.getElementById('total-original-value').textContent = `${originalValue.toFixed(2)} PLN`;

    // Zerujemy pole procentu rabatu
    document.getElementById('total-discount-percentage').value = 0;

    // Wypełnij dropdown powodów (jak dotychczas)
    populateDiscountReasons('total-discount-reason');

    // Wywołaj updateTotalPricePreview(), aby uaktualnić podgląd
    updateTotalPricePreview();

    // Pokaż modal
    const modal = document.getElementById('edit-total-discount-modal');
    modal.style.display = 'flex';
    setTimeout(() => modal.classList.add('active'), 10);
}


// Wypełnianie dropdown powodów rabatu
function populateDiscountReasons(selectId, selectedReasonId = null) {
    const select = document.getElementById(selectId);
    if (!select) {
        console.warn(`[populateDiscountReasons] Element #${selectId} nie znaleziony`);
        return;
    }

    // Wyczyść opcje
    select.innerHTML = '<option value="">Wybierz powód...</option>';

    // Sprawdź czy discountReasons jest tablicą
    if (!Array.isArray(discountReasons)) {
        console.warn("[populateDiscountReasons] discountReasons nie jest tablicą:", discountReasons);

        // Dodaj opcję informującą o błędzie
        const errorOption = document.createElement('option');
        errorOption.value = '';
        errorOption.textContent = 'Błąd ładowania powodów rabatów';
        errorOption.disabled = true;
        select.appendChild(errorOption);
        return;
    }

    // Sprawdź czy mamy powody rabatów
    if (discountReasons.length === 0) {
        const noDataOption = document.createElement('option');
        noDataOption.value = '';
        noDataOption.textContent = 'Brak dostępnych powodów';
        noDataOption.disabled = true;
        select.appendChild(noDataOption);
        return;
    }

    // Dodaj powody rabatów
    discountReasons.forEach(reason => {
        if (!reason || typeof reason !== 'object') {
            console.warn("[populateDiscountReasons] Nieprawidłowy obiekt powodu:", reason);
            return;
        }

        const option = document.createElement('option');
        option.value = reason.id || '';
        option.textContent = reason.name || 'Nieznany powód';

        if (reason.id === selectedReasonId) {
            option.selected = true;
        }

        select.appendChild(option);
    });
}

// Aktualizacja podglądu cen dla pojedynczego wariantu
function updatePricePreview() {
    const discountPercentage = parseFloat(document.getElementById('discount-percentage').value) || 0;

    const originalNetto = originalPrices.netto || 0;
    const originalBrutto = originalPrices.brutto || 0;

    const discountMultiplier = 1 - (discountPercentage / 100);
    const finalNetto = originalNetto * discountMultiplier;
    const finalBrutto = originalBrutto * discountMultiplier;

    // Aktualizuj wyświetlanie
    document.getElementById('original-price-netto').textContent = `${originalNetto.toFixed(2)} PLN`;
    document.getElementById('original-price-brutto').textContent = `${originalBrutto.toFixed(2)} PLN`;
    document.getElementById('final-price-netto').textContent = `${finalNetto.toFixed(2)} PLN`;
    document.getElementById('final-price-brutto').textContent = `${finalBrutto.toFixed(2)} PLN`;

    // Pokaż/ukryj różnicę
    const discountAmount = document.getElementById('discount-amount');
    const discountValue = document.getElementById('discount-value');

    if (discountPercentage !== 0) {
        const difference = originalBrutto - finalBrutto;
        discountValue.textContent = `${Math.abs(difference).toFixed(2)} PLN ${difference >= 0 ? '(oszczędność)' : '(dopłata)'}`;
        discountAmount.style.display = 'block';
    } else {
        discountAmount.style.display = 'none';
    }
}

// Aktualizacja podglądu cen dla rabatu całkowitego
function updateTotalPricePreview() {
    const discountPercentage = parseFloat(document.getElementById('total-discount-percentage').value) || 0;
    const includeFinishing = document.getElementById('include-finishing-discount').checked;

    if (!currentQuoteData) return;

    // **Użyj wszystkich pozycji, nie tylko is_selected**
    const allItems = currentQuoteData.items;

    // Oblicz oryginalne wartości NETTO i BRUTTO dla wszystkich produktów:
    const originalNetto = allItems.reduce((sum, item) => {
        return sum + (item.original_price_netto || item.final_price_netto || 0);
    }, 0);

    const originalBrutto = allItems.reduce((sum, item) => {
        return sum + (item.original_price_brutto || item.final_price_brutto || 0);
    }, 0);

    const discountMultiplier = 1 - (discountPercentage / 100);
    const finalNetto = originalNetto * discountMultiplier;
    const finalBrutto = originalBrutto * discountMultiplier;

    document.getElementById('total-original-products-netto').textContent = `${originalNetto.toFixed(2)} PLN`;
    document.getElementById('total-original-products-brutto').textContent = `${originalBrutto.toFixed(2)} PLN`;
    document.getElementById('total-final-products-netto').textContent = `${finalNetto.toFixed(2)} PLN`;
    document.getElementById('total-final-products-brutto').textContent = `${finalBrutto.toFixed(2)} PLN`;

    // Wykończenie - z rabatem lub bez, w zależności od checkboxa
    let finishingCost = currentQuoteData.costs?.finishing?.brutto || 0;
    if (includeFinishing && discountPercentage !== 0) {
        finishingCost = finishingCost * discountMultiplier;
    }

    // Wysyłka ZAWSZE bez rabatu
    const shippingCost = currentQuoteData.costs?.shipping?.brutto || 0;

    // Suma końcowa
    const totalFinal = finalBrutto + finishingCost + shippingCost;

    document.getElementById('total-finishing-cost').textContent = `${finishingCost.toFixed(2)} PLN`;
    document.getElementById('total-shipping-cost').textContent = `${shippingCost.toFixed(2)} PLN`;
    document.getElementById('total-final-value').textContent = `${totalFinal.toFixed(2)} PLN`;

    // Pokaż/ukryj oszczędności - tylko na produktach
    const discountAmount = document.getElementById('total-discount-amount');
    const discountValue = document.getElementById('total-discount-value');

    if (discountPercentage !== 0) {
        let totalSavings = originalBrutto - finalBrutto;

        // Dodaj oszczędności z wykończenia jeśli jest checkbox
        if (includeFinishing) {
            const originalFinishing = currentQuoteData.costs?.finishing?.brutto || 0;
            const finishingSavings = originalFinishing - finishingCost;
            totalSavings += finishingSavings;
        }

        discountValue.textContent = `${Math.abs(totalSavings).toFixed(2)} PLN ${totalSavings >= 0 ? '(oszczędność)' : '(dopłata)'}`;
        discountAmount.style.display = 'block';
    } else {
        discountAmount.style.display = 'none';
    }
}

// Zapisywanie zmian wariantu
async function saveVariantChanges() {
    if (!currentEditingItem || !currentQuoteData) return;

    const saveBtn = document.getElementById('save-variant-changes');
    const discountPercentage = parseFloat(document.getElementById('discount-percentage').value) || 0;
    const reasonId = document.getElementById('discount-reason').value || null;
    const showOnClientPage = document.getElementById('show-on-client-page').checked;

    // Walidacja
    if (Math.abs(discountPercentage) > 100) {
        showToast('Rabat nie może być większy niż 100% lub mniejszy niż -100%', 'error');
        return;
    }

    // Disable przycisk i pokaż loading
    saveBtn.disabled = true;
    saveBtn.querySelector('.btn-text').style.display = 'none';
    saveBtn.querySelector('.btn-loading').style.display = 'inline';

    try {
        const response = await fetch(`/quotes/api/quotes/${currentQuoteData.id}/variant/${currentEditingItem.id}/discount`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                discount_percentage: discountPercentage,
                reason_id: reasonId,
                show_on_client_page: showOnClientPage
            })
        });

        if (!response.ok) {
            throw new Error('Błąd podczas zapisywania zmian');
        }

        const result = await response.json();
        console.log("[saveVariantChanges] Zapisano zmiany:", result);

        // Zamknij modal
        closeVariantEditModal();

        // Odśwież modal szczegółów wyceny
        refreshQuoteDetailsModal();

        // Pokaż toast sukcesu
        showToast('Zmiany zostały zapisane pomyślnie', 'success');

    } catch (error) {
        console.error("[saveVariantChanges] Błąd:", error);
        showToast('Błąd podczas zapisywania zmian', 'error');
    } finally {
        // Przywróć przycisk
        saveBtn.disabled = false;
        saveBtn.querySelector('.btn-text').style.display = 'inline';
        saveBtn.querySelector('.btn-loading').style.display = 'none';
    }
}

// Zapisywanie rabatu całkowitego
async function saveTotalDiscount() {
    if (!currentQuoteData) {
        console.error("[saveTotalDiscount] Brak currentQuoteData");
        return;
    }

    const saveBtn = document.getElementById('save-total-discount');
    const discountPercentage = parseFloat(document.getElementById('total-discount-percentage').value) || 0;
    const reasonId = document.getElementById('total-discount-reason').value || null;
    const includeFinishing = document.getElementById('include-finishing-discount').checked;

    // DODAJ logowanie aby sprawdzić ID wyceny
    console.log(`[saveTotalDiscount] Zapisuję rabat dla wyceny ID: ${currentQuoteData.id} (${currentQuoteData.quote_number})`);

    // Walidacja
    if (Math.abs(discountPercentage) > 100) {
        showToast('Rabat nie może być większy niż 100% lub mniejszy niż -100%', 'error');
        return;
    }

    if (discountPercentage !== 0 && !reasonId) {
        showToast('Wybierz powód zmiany ceny', 'warning');
        return;
    }

    // Confirm action
    let confirmMessage = `Na pewno zastosować rabat ${discountPercentage}% do wszystkich produktów w wycenie ${currentQuoteData.quote_number}?`;
    if (includeFinishing) {
        confirmMessage += '\n\nRabat zostanie również zastosowany do wykończenia.';
    }

    if (!confirm(confirmMessage)) {
        return;
    }

    // Disable przycisk i pokaż loading
    saveBtn.disabled = true;
    saveBtn.querySelector('.btn-text').style.display = 'none';
    saveBtn.querySelector('.btn-loading').style.display = 'inline';

    try {
        const response = await fetch(`/quotes/api/quotes/${currentQuoteData.id}/apply-total-discount`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                discount_percentage: discountPercentage,
                reason_id: reasonId,
                include_finishing: includeFinishing
            })
        });

        if (!response.ok) {
            throw new Error('Błąd podczas stosowania rabatu');
        }

        const result = await response.json();
        console.log("[saveTotalDiscount] Zastosowano rabat:", result);

        // Zamknij modal
        closeTotalDiscountModal();

        // UPEWNIJ SIĘ, że odświeżamy tę samą wycenę
        await refreshQuoteDetailsModal();

        // Pokaż toast sukcesu
        let message = `Rabat został zastosowany do ${result.affected_items} pozycji`;
        if (includeFinishing) {
            message += ' (włącznie z wykończeniem)';
        }
        showToast(message, 'success');

    } catch (error) {
        console.error("[saveTotalDiscount] Błąd:", error);
        showToast('Błąd podczas stosowania rabatu', 'error');
    } finally {
        // Przywróć przycisk
        saveBtn.disabled = false;
        saveBtn.querySelector('.btn-text').style.display = 'inline';
        saveBtn.querySelector('.btn-loading').style.display = 'none';
    }
}

// Zamykanie modala edycji wariantu
function closeVariantEditModal() {
    const modal = document.getElementById('edit-variant-modal');
    modal.classList.remove('active');
    setTimeout(() => {
        modal.style.display = 'none';
        currentEditingItem = null;
    }, 300);
}

// Zamykanie modala rabatu całkowitego
function closeTotalDiscountModal() {
    const modal = document.getElementById('edit-total-discount-modal');
    modal.classList.remove('active');
    setTimeout(() => {
        modal.style.display = 'none';
        currentQuoteData = null;
    }, 300);
}

// Odświeżanie modala szczegółów wyceny
async function refreshQuoteDetailsModal() {
    if (!currentQuoteData || !currentQuoteData.id) {
        console.error("[refreshQuoteDetailsModal] Brak currentQuoteData lub currentQuoteData.id");
        return;
    }

    const quoteId = currentQuoteData.id;
    console.log(`[refreshQuoteDetailsModal] Odświeżam modal dla wyceny ID: ${quoteId}`);

    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const updatedData = await response.json();
        console.log(`[refreshQuoteDetailsModal] Otrzymano dane dla wyceny: ${updatedData.quote_number}`);

        // NOWE: Sprawdź czy status się zmienił na zaakceptowany
        const wasAccepted = acceptedQuotes.has(quoteId);
        const isNowAccepted = checkIfQuoteAccepted(updatedData);

        if (!wasAccepted && isNowAccepted) {
            console.log('[refreshQuoteDetailsModal] Wycena została właśnie zaakceptowana!');
            showToast('Wycena została zaakceptowana przez klienta! 🎉', 'success');
        }

        // Aktualizuj currentQuoteData
        currentQuoteData = updatedData;

        showDetailsModal(updatedData);

    } catch (error) {
        console.error("[refreshQuoteDetailsModal] Błąd:", error);
        showToast('Błąd podczas odświeżania danych wyceny', 'error');
    }
}

// Funkcja toast notifications
function showToast(message, type = 'success') {
    // Usuń istniejące toasty
    const existingToasts = document.querySelectorAll('.toast-notification');
    existingToasts.forEach(toast => toast.remove());

    // Utwórz nowy toast
    const toast = document.createElement('div');
    toast.className = `toast-notification ${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    // Pokaż toast
    setTimeout(() => toast.classList.add('show'), 100);

    // Ukryj toast po 3 sekundach
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Funkcja do pobierania nazwy powodu rabatu
function getDiscountReasonName(reasonId) {
    if (!reasonId || !discountReasons.length) return 'Nie podano';

    const reason = discountReasons.find(r => r.id === reasonId);
    return reason ? reason.name : 'Nieznany powód';
}

// Funkcja dodawania przycisku rabatu całkowitego
function addTotalDiscountButton(quoteData) {
    // Sprawdź czy przycisk już istnieje
    let totalDiscountBtn = document.getElementById('total-discount-btn');

    if (!totalDiscountBtn) {
        // Znajdź kontener dla przycisków w headerze
        const headerActions = document.querySelector('.quotes-details-modal-header-actions');

        if (headerActions) {
            // Utwórz przycisk
            totalDiscountBtn = document.createElement('button');
            totalDiscountBtn.id = 'total-discount-btn';
            totalDiscountBtn.className = 'quotes-btn total-discount-btn';
            totalDiscountBtn.innerHTML = '<span>Rabat całkowity</span>';
            totalDiscountBtn.title = 'Zastosuj rabat do wszystkich produktów';

            // Dodaj event listener
            totalDiscountBtn.onclick = () => {
                console.log('[TOTAL DISCOUNT] Otwieranie modala rabatu całkowitego');
                openTotalDiscountModal(quoteData);
            };

            // Wstaw przycisk przed przyciskiem "Pełny ekran"
            const fullscreenBtn = document.getElementById('toggle-fullscreen-modal');
            if (fullscreenBtn) {
                headerActions.insertBefore(totalDiscountBtn, fullscreenBtn);
            } else {
                headerActions.appendChild(totalDiscountBtn);
            }
        }
    }
}
function initializeClientPageButtons(quoteData) {
    console.log('[ClientPage] Inicjalizacja przycisków strony klienta dla:', quoteData.quote_number);

    const clientPageBtn = document.getElementById('quote-client-page-btn');
    const copyLinkBtn = document.getElementById('quote-link-copy-btn');

    if (!quoteData || !quoteData.public_url) {
        console.warn('[ClientPage] Brak public_url dla wyceny');

        if (clientPageBtn) {
            clientPageBtn.disabled = true;
            clientPageBtn.title = 'Wycena nie ma publicznego linku';
            clientPageBtn.style.opacity = '0.5';
        }
        if (copyLinkBtn) {
            copyLinkBtn.disabled = true;
            copyLinkBtn.title = 'Wycena nie ma publicznego linku';
            copyLinkBtn.style.opacity = '0.5';
        }
        return;
    }

    console.log('[ClientPage] Analizuję public_url:', quoteData.public_url);

    // Użyj bezpośrednio public_url lub skonstruuj URL
    const baseUrl = window.location.origin;
    const fullUrl = `${baseUrl}${quoteData.public_url}`;

    console.log('[ClientPage] Pełny URL strony klienta:', fullUrl);

    // Wyodrębnij quote_number i token dla celów debugowania
    const urlMatch = quoteData.public_url.match(/\/wycena\/(.+)\/([A-F0-9]+)$/);
    if (urlMatch) {
        const [, quoteNumber, token] = urlMatch;
        console.log('[ClientPage] Parsowanie OK:', { quoteNumber, token });
    }

    // Skonfiguruj przycisk "Strona klienta"
    if (clientPageBtn) {
        const newClientPageBtn = clientPageBtn.cloneNode(true);
        clientPageBtn.parentNode.replaceChild(newClientPageBtn, clientPageBtn);

        newClientPageBtn.disabled = false;
        newClientPageBtn.style.opacity = '1';
        newClientPageBtn.title = 'Otwórz stronę klienta w nowej karcie';

        newClientPageBtn.addEventListener('click', (e) => {
            e.preventDefault();
            console.log('[ClientPage] Kliknięto przycisk strony klienta');
            console.log('[ClientPage] Otwieranie URL:', fullUrl);

            // Otwórz stronę używając pełnego URL
            window.open(fullUrl, '_blank', 'noopener,noreferrer');
            showToast('Otwarto stronę klienta w nowej karcie', 'success');
        });

        console.log('[ClientPage] Skonfigurowano przycisk strony klienta');
    }

    // Skonfiguruj przycisk kopiowania linku
    if (copyLinkBtn) {
        const newCopyLinkBtn = copyLinkBtn.cloneNode(true);
        copyLinkBtn.parentNode.replaceChild(newCopyLinkBtn, copyLinkBtn);

        newCopyLinkBtn.disabled = false;
        newCopyLinkBtn.style.opacity = '1';
        newCopyLinkBtn.title = 'Skopiuj link do strony klienta';

        newCopyLinkBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            console.log('[ClientPage] Kliknięto przycisk kopiowania linku');
            console.log('[ClientPage] Kopiowanie URL:', fullUrl);

            try {
                // Najpierw próbujemy Clipboard API
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(fullUrl);
                    showToast('Link do strony klienta skopiowany! 📋', 'success');
                } else {
                    // Fallback: fallbackCopyToClipboard (własna funkcja z execCommand)
                    const textArea = document.createElement('textarea');
                    textArea.value = fullUrl;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-9999px';
                    document.body.appendChild(textArea);
                    textArea.select();
                    // @ts-ignore: document.execCommand jest zdeprecjonowane, ale tutaj wciąż działa
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    showToast('Link do strony klienta skopiowany! 📋', 'success');
                }

                // Wizualna informacja zwrotna
                const originalContent = newCopyLinkBtn.innerHTML;
                newCopyLinkBtn.innerHTML = '✅';
                newCopyLinkBtn.style.backgroundColor = '#28a745';

                setTimeout(() => {
                    newCopyLinkBtn.innerHTML = originalContent;
                    newCopyLinkBtn.style.backgroundColor = '';
                }, 2000);

            } catch (error) {
                console.error('[ClientPage] Błąd kopiowania:', error);
                showToast('Nie udało się skopiować linku', 'error');
            }
        });

        console.log('[ClientPage] Skonfigurowano przycisk kopiowania linku');
    }

}
function generateClientUrl(quoteNumber, token) {
    const baseUrl = window.location.origin;
    return `${baseUrl}/c/${token}`;
}
function openClientPage(quoteNumber, token) {
    if (!quoteNumber || !token) {
        console.error('[ClientPage] Brak quote number lub token');
        showToast('Brak danych do wygenerowania strony klienta', 'error');
        return;
    }

    const url = generateClientUrl(quoteNumber, token);
    console.log('[ClientPage] Otwieranie strony klienta:', url);

    // Otwórz w nowej karcie
    window.open(url, '_blank', 'noopener,noreferrer');

    // Pokaż powiadomienie
    showToast('Otwarto stronę klienta w nowej karcie', 'success');
}
async function copyClientLink(quoteNumber, token) {
    if (!quoteNumber || !token) {
        console.error('[ClientPage] Brak quote number lub token');
        showToast('Brak danych do skopiowania linku', 'error');
        return;
    }

    const url = generateClientUrl(quoteNumber, token);

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            // Nowoczesne API schowka
            await navigator.clipboard.writeText(url);
            showToast('Link do strony klienta skopiowany! 📋', 'success');
        } else {
            // Fallback dla starszych przeglądarek
            fallbackCopyToClipboard(url);
        }

        console.log('[ClientPage] Link skopiowany do schowka:', url);

        // Wizualna informacja zwrotna na przycisku
        const copyBtn = document.getElementById('quote-link-copy-btn');
        if (copyBtn) {
            const originalContent = copyBtn.innerHTML;
            copyBtn.innerHTML = '✅';
            copyBtn.style.backgroundColor = '#28a745';

            setTimeout(() => {
                copyBtn.innerHTML = originalContent;
                copyBtn.style.backgroundColor = '';
            }, 2000);
        }

    } catch (error) {
        console.error('[ClientPage] Nie udało się skopiować linku:', error);
        showToast('Nie udało się skopiować linku', 'error');
    }
}
function fallbackCopyToClipboard(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '-9999px';

    document.body.appendChild(textArea);
    textArea.select();
    textArea.setSelectionRange(0, 99999);

    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showToast('Link do strony klienta skopiowany! 📋', 'success');
        } else {
            throw new Error('Copy command failed');
        }
    } catch (error) {
        console.error('[ClientPage] Fallback copy failed:', error);
        showToast('Skopiuj link ręcznie: ' + text.substring(0, 50) + '...', 'info');
    }

    document.body.removeChild(textArea);
}

function formatPriceWithNetto(brutto, netto) {
    if (!brutto && !netto) return '-';
    
    let html = '';
    if (brutto) {
        html += `${brutto.toFixed(2)} PLN brutto`;
    }
    if (netto && brutto) {
        html += ` <span style="font-size: 12px;">• ${netto.toFixed(2)} PLN netto</span>`;
    } else if (netto && !brutto) {
        html += `${netto.toFixed(2)} PLN netto`;
    }
    
    return html;
}

// Formatowanie wartości wagowych i objętościowych
function formatWeightDisplay(weight) {
    if (!weight || weight <= 0) {
        return "0.0 kg";
    }

    if (weight >= 1000) {
        return `${(weight / 1000).toFixed(2)} t`;
    }

    return `${weight.toFixed(1)} kg`;
}

function formatVolumeDisplay(volume) {
    if (!volume || volume <= 0) {
        return "0.0000 m³";
    }

    return `${volume.toFixed(4)} m³`;
}

// NOWA FUNKCJONALNOŚĆ: Sprawdzanie parametru open_quote w URL
function checkForOpenQuoteParameter() {
    console.log("[checkForOpenQuoteParameter] START - sprawdzam URL:", window.location.search);
    
    const urlParams = new URLSearchParams(window.location.search);
    let openQuoteId = urlParams.get('open_quote');
    
    console.log("[checkForOpenQuoteParameter] Parametr open_quote z URL:", openQuoteId);
    
    // BACKUP: Sprawdź sessionStorage jeśli brak w URL
    if (!openQuoteId) {
        openQuoteId = sessionStorage.getItem('openQuoteId');
        console.log("[checkForOpenQuoteParameter] Parametr open_quote z sessionStorage:", openQuoteId);
        
        // Wyczyść sessionStorage po użyciu
        if (openQuoteId) {
            sessionStorage.removeItem('openQuoteId');
        }
    }
    
    if (openQuoteId) {
        console.log(`[checkForOpenQuoteParameter] ✅ Wykryto parametr open_quote=${openQuoteId}`);
        
        // Usuń parametr z URL (opcjonalnie)
        const newUrl = window.location.pathname;
        window.history.replaceState({}, document.title, newUrl);
        console.log("[checkForOpenQuoteParameter] Usunięto parametr z URL");
        
        // Otwórz modal szczegółów wyceny
        console.log("[checkForOpenQuoteParameter] Ustawiam timeout na otwarcie modala...");
        setTimeout(() => {
            console.log("[checkForOpenQuoteParameter] Wywołuję openQuoteDetailsById");
            openQuoteDetailsById(openQuoteId);
        }, 300);
    } else {
        console.log("[checkForOpenQuoteParameter] ❌ Nie znaleziono parametru open_quote ani w URL ani w sessionStorage");
    }
}

// Funkcja pomocnicza do otwierania modala szczegółów wyceny po ID
async function openQuoteDetailsById(quoteId) {
    try {
        console.log(`[openQuoteDetailsById] Pobieranie szczegółów wyceny ID: ${quoteId}`);
        
        // Sprawdź czy allQuotes jest już załadowane
        if (!allQuotes || allQuotes.length === 0) {
            console.log(`[openQuoteDetailsById] allQuotes nie jest załadowane, czekam...`);
            // Jeśli nie, poczekaj chwilę i spróbuj ponownie
            setTimeout(() => openQuoteDetailsById(quoteId), 500);
            return;
        }
        
        const response = await fetch(`/quotes/api/quotes/${quoteId}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const quoteData = await response.json();
        console.log(`[openQuoteDetailsById] Otrzymano dane wyceny: ${quoteData.quote_number}`);
        
        // Sprawdź czy funkcja showDetailsModal istnieje
        if (typeof showDetailsModal === 'function') {
            // Otwórz modal
            showDetailsModal(quoteData);
            
            // Pokaż toast informacyjny
            if (typeof showToast === 'function') {
                showToast(`Otwarto szczegóły wyceny ${quoteData.quote_number}`, 'success');
            }
        } else {
            console.error('[openQuoteDetailsById] Funkcja showDetailsModal nie istnieje');
        }
        
    } catch (error) {
        console.error(`[openQuoteDetailsById] Błąd podczas otwierania wyceny ID ${quoteId}:`, error);
        if (typeof showToast === 'function') {
            showToast('Nie udało się otworzyć szczegółów wyceny', 'error');
        } else {
            alert('Nie udało się otworzyć szczegółów wyceny');
        }
    }
}

/**
 * Konfiguruje przycisk akceptacji wyceny przez użytkownika
 * @param {Object} quoteData - Dane wyceny
 */
function setupUserAcceptButton(quoteData) {
    const acceptBtn = document.getElementById('quote-user-accept-btn');
    if (!acceptBtn) {
        console.warn('[UserAccept] Brak przycisku akceptacji w DOM');
        return;
    }

    console.log('[UserAccept] Konfiguracja przycisku akceptacji dla wyceny:', quoteData.id);

    // Sprawdź czy wycena może być zaakceptowana
    const canAccept = canUserAcceptQuote(quoteData);
    
    if (canAccept) {
        // Pokaż i skonfiguruj przycisk
        acceptBtn.style.display = 'flex';
        acceptBtn.dataset.quoteId = quoteData.id;
        acceptBtn.disabled = false;
        
        // Usuń stare event listenery i dodaj nowy
        const newAcceptBtn = acceptBtn.cloneNode(true);
        acceptBtn.parentNode.replaceChild(newAcceptBtn, acceptBtn);
        
        newAcceptBtn.addEventListener('click', handleUserAcceptClick);
        
        console.log('[UserAccept] Przycisk akceptacji skonfigurowany i widoczny');
    } else {
        // Ukryj przycisk
        acceptBtn.style.display = 'none';
        console.log('[UserAccept] Przycisk akceptacji ukryty - wycena nie może być zaakceptowana');
    }
}

/**
 * Sprawdza czy użytkownik może zaakceptować wycenę
 * @param {Object} quoteData - Dane wyceny
 * @returns {boolean} - Czy można zaakceptować
 */
function canUserAcceptQuote(quoteData) {
    // Sprawdź czy wycena nie została już zaakceptowana
    const isAlreadyAccepted = checkIfQuoteAccepted(quoteData);
    
    // Sprawdź czy wycena nie została już złożona jako zamówienie
    const isOrdered = checkIfQuoteOrdered(quoteData);
    
    console.log('[UserAccept] Sprawdzanie możliwości akceptacji:', {
        quoteId: quoteData.id,
        isClientEditable: quoteData.is_client_editable,
        isAlreadyAccepted,
        isOrdered,
        statusId: quoteData.status_id,
        statusName: quoteData.status_name
    });
    
    // Można zaakceptować jeśli:
    // - wycena nie została jeszcze zaakceptowana (is_client_editable = true)
    // - wycena nie została złożona jako zamówienie
    return quoteData.is_client_editable && !isAlreadyAccepted && !isOrdered;
}

/**
 * Obsługuje kliknięcie w przycisk akceptacji przez użytkownika
 * @param {Event} event - Event kliknięcia
 */
async function handleUserAcceptClick(event) {
    event.preventDefault();
    
    const acceptBtn = event.target;
    const quoteId = acceptBtn.dataset.quoteId;
    
    if (!quoteId) {
        console.error('[UserAccept] Brak ID wyceny w przycisku');
        showToast('Błąd: Brak ID wyceny', 'error');
        return;
    }
    
    console.log('[UserAccept] Próba akceptacji wyceny:', quoteId);
    
    // Pokaż potwierdzenie
    const confirmed = confirm('Czy na pewno chcesz zaakceptować tę wycenę jako opiekun oferty?\n\nPo akceptacji wycena zostanie oznaczona jako zatwierdzona, a klient otrzyma email z potwierdzeniem.');
    
    if (!confirmed) {
        console.log('[UserAccept] Akceptacja anulowana przez użytkownika');
        return;
    }
    
    // Zablokuj przycisk podczas operacji
    acceptBtn.disabled = true;
    acceptBtn.textContent = 'Akceptuję...';
    
    try {
        // Wyślij żądanie akceptacji
        const response = await fetch(`/quotes/api/quotes/${quoteId}/user-accept`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        
        console.log('[UserAccept] Akceptacja pomyślna:', data);
        
        // Pokaż sukces
        showToast(`✅ Wycena została zaakceptowana przez ${data.accepted_by_user}`, 'success');
        
        // Odśwież modal
        await refreshQuoteModal(quoteId);
        
        console.log('[UserAccept] Modal odświeżony po akceptacji');
        
    } catch (error) {
        console.error('[UserAccept] Błąd akceptacji:', error);
        showToast(`Błąd akceptacji: ${error.message}`, 'error');
        
        // Przywróć przycisk
        acceptBtn.disabled = false;
        acceptBtn.textContent = '✓ Akceptuj';
    }
}

/**
 * Odświeża modal wyceny po akceptacji
 * @param {number} quoteId - ID wyceny
 */
async function refreshQuoteModal(quoteId) {
    try {
        console.log('[UserAccept] Odświeżanie modalu dla wyceny:', quoteId);
        
        // Pobierz zaktualizowane dane wyceny
        const response = await fetch(`/quotes/api/quotes/${quoteId}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const updatedQuoteData = await response.json();
        console.log('[UserAccept] Pobrano zaktualizowane dane:', updatedQuoteData);
        
        // Zaktualizuj zawartość modalu
        showDetailsModal(updatedQuoteData)
        
        console.log('[UserAccept] Modal zaktualizowany pomyślnie');
        
    } catch (error) {
        console.error('[UserAccept] Błąd odświeżania modalu:', error);
        showToast('Błąd odświeżania danych. Odśwież stronę.', 'error');
    }
}

/**
 * Dodaje banner informacji o akceptacji przez użytkownika - ZAKTUALIZOWANA WERSJA
 * @param {HTMLElement} modalBox - Kontener modalu
 * @param {Object} quoteData - Dane wyceny
 */
function addUserAcceptanceBanner(modalBox, quoteData) {
    // Usuń istniejący banner jeśli jest
    removeUserAcceptanceBanner(modalBox);
    
    // Sprawdź czy wycena została zaakceptowana przez użytkownika wewnętrznego
    const isAcceptedByUser = isQuoteAcceptedByUser(quoteData);
    
    if (!isAcceptedByUser) {
        return;
    }
    
    let acceptanceDate = '';
    let acceptedByUserName = 'Opiekun oferty'; // fallback
    
    if (quoteData.acceptance_date) {
        const date = new Date(quoteData.acceptance_date);
        acceptanceDate = date.toLocaleString('pl-PL');
    }
    
    // NOWA LOGIKA: Sprawdź czy mamy dane użytkownika akceptującego
    if (quoteData.accepted_by_user && quoteData.accepted_by_user.full_name) {
        acceptedByUserName = quoteData.accepted_by_user.full_name;
    } else if (quoteData.accepted_by_user && quoteData.accepted_by_user.first_name) {
        // Fallback - zbuduj imię z dostępnych części
        const firstName = quoteData.accepted_by_user.first_name || '';
        const lastName = quoteData.accepted_by_user.last_name || '';
        acceptedByUserName = `${firstName} ${lastName}`.trim() || 'Opiekun oferty';
    }
    
    const banner = document.createElement('div');
    banner.className = 'user-acceptance-banner';
    banner.innerHTML = `
        <svg class="banner-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
        </svg>
        <div class="banner-text">
            <div><strong>Wycena została zaakceptowana przez handlowca ${acceptedByUserName}</strong></div>
            ${acceptanceDate ? `<div class="acceptance-details">Data akceptacji: ${acceptanceDate}</div>` : ''}
        </div>
    `;
    
    // Wstaw banner na początku modalu (po nagłówku)
    const modalHeader = modalBox.querySelector('.quotes-details-modal-header');
    if (modalHeader && modalHeader.nextSibling) {
        modalBox.insertBefore(banner, modalHeader.nextSibling);
    } else {
        modalBox.appendChild(banner);
    }
    
    console.log(`[UserAccept] Dodano banner akceptacji przez handlowca: ${acceptedByUserName}`);
}

/**
 * Usuwa banner akceptacji przez użytkownika
 * @param {HTMLElement} modalBox - Kontener modalu
 */
function removeUserAcceptanceBanner(modalBox) {
    const existingBanner = modalBox.querySelector('.user-acceptance-banner');
    if (existingBanner) {
        existingBanner.remove();
        console.log('[UserAccept] Usunięto banner akceptacji przez opiekuna');
    }
}

/**
 * Sprawdza czy wycena została zaakceptowana przez użytkownika wewnętrznego
 * @param {Object} quoteData - Dane wyceny
 * @returns {boolean}
 */
function isQuoteAcceptedByUser(quoteData) {
    // Sprawdź czy w accepted_by_email jest oznaczenie użytkownika wewnętrznego
    return quoteData.accepted_by_email &&
        quoteData.accepted_by_email.startsWith('internal_user_') &&
        !quoteData.is_client_editable;
}

/**
 * Waliduje dane wariantu dla Preview3D
 * @param {Object} variant - Dane wariantu
 * @returns {boolean} - Czy dane są prawidłowe
 */
function validateVariantForPreview3D(variant) {
    if (!variant || !variant.variant_code) {
        console.warn('[Preview3D] Brak variant_code');
        return false;
    }

    if (!variant.length_cm || !variant.width_cm || !variant.thickness_cm ||
        variant.length_cm <= 0 || variant.width_cm <= 0 || variant.thickness_cm <= 0) {
        console.warn('[Preview3D] Nieprawidłowe wymiary:', variant);
        return false;
    }

    return true;
}

/**
 * Otwiera okno Preview3D z danymi produktu (stara wersja - dla kompatybilności)
 * @param {Object} productData - Dane produktu
 * @param {string} windowTitle - Tytuł okna
 */
function openPreview3DWindow(productData, windowTitle = 'Wood Power - Podgląd 3D') {
    console.log('[Preview3D] Otwieranie starego modala Preview3D:', productData);

    // Zakoduj dane do URL
    const encodedData = encodeURIComponent(JSON.stringify(productData));
    const modalUrl = `/preview3d-ar/modal?data=${encodedData}`;

    // Parametry okna - dostosowane do różnych rozdzielczości
    const windowFeatures = [
        'width=1400',
        'height=900',
        'scrollbars=yes',
        'resizable=yes',
        'menubar=no',
        'toolbar=no',
        'location=no',
        'status=no',
        'left=' + Math.max(0, (screen.width - 1400) / 2),
        'top=' + Math.max(0, (screen.height - 900) / 2)
    ].join(',');

    // Otwórz okno
    const preview3DWindow = window.open(modalUrl, 'Preview3D_' + Date.now(), windowFeatures);

    if (!preview3DWindow) {
        // Fallback - spróbuj otworzyć w nowej karcie
        const fallbackUrl = modalUrl + '&fallback=tab';
        window.open(fallbackUrl, '_blank');

        alert('Okno Preview 3D zostało otwarte w nowej karcie (sprawdź ustawienia blokady popup).');
    } else {
        console.log('[Preview3D] Okno Preview3D otwarte pomyślnie');

        // Spróbuj ustawić tytuł okna
        try {
            preview3DWindow.addEventListener('load', function () {
                if (windowTitle && preview3DWindow.document) {
                    preview3DWindow.document.title = windowTitle;
                }
            });
        } catch (e) {
            // Ignore cross-origin errors
        }
    }
}

/**
 * Helper do debugowania Preview3D
 */
window.debugQuotePreview3D = function () {
    const button = document.getElementById('quote-preview3d-btn');
    console.log('[Preview3D Debug] Przycisk 3D:', button);
    console.log('[Preview3D Debug] Przycisk disabled:', button?.disabled);
    console.log('[Preview3D Debug] currentQuoteData:', window.currentQuoteData);

    if (button && window.currentQuoteData) {
        const variant = findSelectedVariantFromQuote(window.currentQuoteData);
        console.log('[Preview3D Debug] Wybrany wariant:', variant);
    }
};

console.log('[Preview3D] Funkcje Preview3D załadowane - używa Quote Viewer 3D/AR');


// Inicjalizacja masowej zmiany wariantów
function initBulkVariantChange() {
    console.log('[BulkVariant] Inicjalizacja masowej zmiany wariantów');

    const btn = document.getElementById('bulk-variant-change-btn');
    const dropdown = document.getElementById('bulk-variant-dropdown');

    if (!btn || !dropdown) {
        console.warn('[BulkVariant] Brak elementów bulk variant w DOM');
        return;
    }

    // NOWE: Usuń stare event listenery poprzez klonowanie elementu
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);

    // Dodaj event listener do nowego przycisku
    newBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        console.log('[BulkVariant] Kliknięto przycisk masowej zmiany');
        toggleBulkVariantDropdown();
    });

    // NOWE: Usuń globalne event listenery i dodaj nowe
    // Usuń stare listenery dla dokumentu
    document.removeEventListener('click', globalClickHandler);

    // Dodaj nowy listener
    document.addEventListener('click', globalClickHandler);

    console.log('[BulkVariant] Event listenery zaktualizowane');
}

function globalClickHandler(e) {
    const dropdown = document.getElementById('bulk-variant-dropdown');
    const btn = document.getElementById('bulk-variant-change-btn');

    if (dropdown && btn && !dropdown.contains(e.target) && !btn.contains(e.target)) {
        closeBulkVariantDropdown();
    }
}

function toggleBulkVariantDropdown() {
    const btn = document.getElementById('bulk-variant-change-btn');
    const dropdown = document.getElementById('bulk-variant-dropdown');

    if (!btn || !dropdown) return;

    const isOpen = dropdown.style.display !== 'none';

    if (isOpen) {
        closeBulkVariantDropdown();
    } else {
        openBulkVariantDropdown();
    }
}

function openBulkVariantDropdown() {
    const btn = document.getElementById('bulk-variant-change-btn');
    const dropdown = document.getElementById('bulk-variant-dropdown');

    if (!btn || !dropdown) return;

    // Pobierz dostępne warianty
    populateBulkVariantOptions();

    // Pokaż dropdown
    dropdown.style.display = 'block';
    btn.classList.add('active');

    // Dodaj overlay dla łatwiejszego zamykania na mobile
    addBulkVariantOverlay();
}

function closeBulkVariantDropdown() {
    const btn = document.getElementById('bulk-variant-change-btn');
    const dropdown = document.getElementById('bulk-variant-dropdown');

    if (!btn || !dropdown) return;

    dropdown.style.display = 'none';
    btn.classList.remove('active');
    removeBulkVariantOverlay();
}

function addBulkVariantOverlay() {
    removeBulkVariantOverlay(); // Usuń istniejący overlay

    const overlay = document.createElement('div');
    overlay.className = 'bulk-variant-overlay';
    overlay.addEventListener('click', closeBulkVariantDropdown);
    document.body.appendChild(overlay);
}

function removeBulkVariantOverlay() {
    const overlay = document.querySelector('.bulk-variant-overlay');
    if (overlay) {
        overlay.remove();
    }
}

function populateBulkVariantOptions() {
    console.log('[BulkVariant DEBUG] Rozpoczynam populateBulkVariantOptions');

    const optionsContainer = document.getElementById('bulk-variant-options');
    if (!optionsContainer) {
        console.error('[BulkVariant DEBUG] Brak elementu bulk-variant-options w DOM');
        return;
    }

    // POPRAWKA: Użyj currentQuoteData zamiast window.currentQuoteData
    if (!currentQuoteData) {
        console.error('[BulkVariant DEBUG] Brak currentQuoteData (global variable)');
        console.log('[BulkVariant DEBUG] Sprawdzam window.currentQuoteData:', window.currentQuoteData);
        return;
    }

    console.log('[BulkVariant DEBUG] currentQuoteData:', currentQuoteData);
    console.log('[BulkVariant DEBUG] currentQuoteData.items:', currentQuoteData.items);

    // Zbierz wszystkie dostępne warianty z produktów
    const availableVariants = new Set();

    if (currentQuoteData.items) {
        console.log('[BulkVariant DEBUG] Przetwarzam items, długość:', currentQuoteData.items.length);

        currentQuoteData.items.forEach((item, index) => {
            console.log(`[BulkVariant DEBUG] Item ${index}:`, {
                variant_code: item.variant_code,
                product_index: item.product_index,
                is_selected: item.is_selected
            });

            if (item.variant_code) {
                availableVariants.add(item.variant_code);
            }
        });
    } else {
        console.error('[BulkVariant DEBUG] Brak currentQuoteData.items lub jest null/undefined');
    }

    console.log('[BulkVariant DEBUG] Zebrane warianty:', Array.from(availableVariants));

    // Konwertuj na array i posortuj
    const variantsList = Array.from(availableVariants).sort();
    console.log('[BulkVariant DEBUG] Posortowane warianty:', variantsList);

    // Wyczyść i wypełnij opcje
    optionsContainer.innerHTML = '';

    if (variantsList.length === 0) {
        console.warn('[BulkVariant DEBUG] Brak dostępnych wariantów - dodaję komunikat');
        optionsContainer.innerHTML = '<div class="bulk-variant-option" style="color: #6c757d; cursor: default;">Brak dostępnych wariantów</div>';
        return;
    }

    console.log('[BulkVariant DEBUG] Tworzę opcje dla wariantów');

    variantsList.forEach((variantCode, index) => {
        console.log(`[BulkVariant DEBUG] Tworzę opcję ${index} dla wariantu: ${variantCode}`);

        const option = document.createElement('div');
        option.className = 'bulk-variant-option';
        option.dataset.variantCode = variantCode;

        const variantName = translateVariantCode(variantCode) || variantCode;
        console.log(`[BulkVariant DEBUG] Przetłumaczona nazwa: ${variantName}`);

        option.innerHTML = `
            <span class="bulk-variant-option-text">${variantName}</span>
        `;

        option.addEventListener('click', () => {
            console.log(`[BulkVariant DEBUG] Kliknięto wariant: ${variantCode}`);
            handleBulkVariantChange(variantCode);
        });

        optionsContainer.appendChild(option);
        console.log(`[BulkVariant DEBUG] Dodano opcję do DOM`);
    });

    console.log('[BulkVariant DEBUG] Zakończono populateBulkVariantOptions');
}

// Dodaj też funkcję debugowania do sprawdzenia stanu
function debugBulkVariantState() {
    console.log('=== BULK VARIANT DEBUG STATE ===');
    console.log('currentQuoteData (global):', currentQuoteData);
    console.log('window.currentQuoteData:', window.currentQuoteData);
    console.log('bulk-variant-change-btn:', document.getElementById('bulk-variant-change-btn'));
    console.log('bulk-variant-dropdown:', document.getElementById('bulk-variant-dropdown'));
    console.log('bulk-variant-options:', document.getElementById('bulk-variant-options'));

    const quoteData = currentQuoteData || window.currentQuoteData;
    if (quoteData && quoteData.items) {
        console.log('Items count:', quoteData.items.length);
        quoteData.items.forEach((item, i) => {
            console.log(`Item ${i}:`, item.variant_code, item.product_index);
        });
    }
    console.log('=== END DEBUG ===');
}

function checkModalStructure() {
    console.log('=== SPRAWDZENIE STRUKTURY MODALA ===');

    // Sprawdź czy modal istnieje
    const modal = document.getElementById('quote-details-modal');
    console.log('Modal details:', modal);

    // Sprawdź sekcję produktów
    const productsSection = modal?.querySelector('.quotes-details-modal-section');
    console.log('Products section:', productsSection);

    // Sprawdź czy istnieje kontener dla controls
    const controlsContainer = document.querySelector('.products-controls-container');
    console.log('Controls container:', controlsContainer);

    // Sprawdź tabs
    const tabs = document.getElementById('quotes-details-tabs');
    console.log('Tabs container:', tabs);

    // Sprawdź elementy masowej zmiany
    const bulkBtn = document.getElementById('bulk-variant-change-btn');
    const bulkDropdown = document.getElementById('bulk-variant-dropdown');
    const bulkOptions = document.getElementById('bulk-variant-options');

    console.log('Bulk change button:', bulkBtn);
    console.log('Bulk dropdown:', bulkDropdown);
    console.log('Bulk options container:', bulkOptions);

    if (!controlsContainer) {
        console.error('❌ BRAK KONTENERA .products-controls-container - musisz zaktualizować HTML!');
    }

    if (!bulkBtn) {
        console.error('❌ BRAK PRZYCISKU #bulk-variant-change-btn - musisz zaktualizować HTML!');
    }

    if (!bulkDropdown) {
        console.error('❌ BRAK DROPDOWN #bulk-variant-dropdown - musisz zaktualizować HTML!');
    }

    console.log('=== KONIEC SPRAWDZENIA ===');
}

async function handleBulkVariantChange(targetVariantCode) {
    if (!currentQuoteData || !currentQuoteData.items) {
        console.error('[BulkVariantChange] Brak danych wyceny');
        return;
    }

    console.log(`[BulkVariantChange] Zmiana wszystkich produktów na wariant: ${targetVariantCode}`);

    try {
        // Zamknij dropdown
        closeBulkVariantDropdown();

        // Pokaż loader/info o przetwarzaniu
        showBulkChangeProgress();

        // Znajdź wszystkie produkty i ich indeksy
        const productIndexes = [...new Set(currentQuoteData.items.map(item => item.product_index))];
        console.log('[BulkVariantChange] Produkty do przetworzenia:', productIndexes);

        let successCount = 0;
        let errorCount = 0;
        let notFoundCount = 0;

        // Przetwarzaj każdy produkt
        for (const productIndex of productIndexes) {
            try {
                console.log(`[BulkVariantChange] Przetwarzam produkt ${productIndex}`);

                // Znajdź wariant docelowy dla tego produktu
                const targetItem = currentQuoteData.items.find(item =>
                    item.product_index === productIndex &&
                    item.variant_code === targetVariantCode
                );

                if (!targetItem) {
                    console.warn(`[BulkVariantChange] Brak wariantu ${targetVariantCode} dla produktu ${productIndex}`);
                    notFoundCount++;
                    continue;
                }

                // Wyślij request o zmianę wariantu
                const response = await fetch(`/quotes/api/quotes/${currentQuoteData.id}/update-variant`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        product_index: productIndex,
                        variant_code: targetVariantCode,
                        quote_item_id: targetItem.id
                    })
                });

                const responseData = await response.json();

                if (response.ok) {
                    console.log(`[BulkVariantChange] ✅ Sukces dla produktu ${productIndex}`);
                    successCount++;
                } else {
                    console.error(`[BulkVariantChange] ❌ Błąd dla produktu ${productIndex}:`, responseData);
                    errorCount++;
                }

            } catch (error) {
                console.error(`[BulkVariantChange] Błąd przetwarzania produktu ${productIndex}:`, error);
                errorCount++;
            }
        }

        // Ukryj loader
        hideBulkChangeProgress();

        // Pokaż wynik użytkownikowi
        showBulkChangeResult(successCount, errorCount, notFoundCount, targetVariantCode);

        // Jeśli były sukcesy, odśwież modal
        if (successCount > 0) {
            console.log('[BulkVariantChange] Odświeżam modal...');

            setTimeout(async () => {
                try {
                    const response = await fetch(`/quotes/api/quotes/${currentQuoteData.id}`);
                    if (response.ok) {
                        const updatedQuoteData = await response.json();
                        showDetailsModal(updatedQuoteData);

                        // NOWE: Re-inicjalizuj event listenery po odświeżeniu modala
                        setTimeout(() => {
                            console.log('[BulkVariantChange] Re-inicjalizuję event listenery po odświeżeniu');
                            initBulkVariantChange();
                        }, 150);
                    }
                } catch (error) {
                    console.error('[BulkVariantChange] Błąd odświeżania:', error);
                }
            }, 200); // Zmniejszony timeout
        }

    } catch (error) {
        console.error('[BulkVariantChange] Błąd masowej zmiany wariantów:', error);
        hideBulkChangeProgress();
        showNotification('Błąd podczas zmiany wariantów. Spróbuj ponownie.', 'error');
    }
}
function showBulkChangeProgress() {
    // Można pokazać spinner lub progress bar
    const btn = document.getElementById('bulk-variant-change-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
            <span>Zmieniam warianty...</span>
            <div style="width: 16px; height: 16px; border: 2px solid #ccc; border-top: 2px solid #ED6B24; border-radius: 50%; animation: spin 1s linear infinite;"></div>
        `;
    }
}

function hideBulkChangeProgress() {
    const btn = document.getElementById('bulk-variant-change-btn');
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = `
            <span>Zmień wszystkie warianty</span>
            <svg class="bulk-variant-chevron" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M4 6L8 10L12 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        `;
    }
}

function showBulkChangeResult(successCount, errorCount, notFoundCount, variantCode) {
    const variantName = translateVariantCode(variantCode) || variantCode;

    if (errorCount === 0 && notFoundCount === 0) {
        showNotification(`✅ Pomyślnie zmieniono wariant na "${variantName}" dla ${successCount} produktów`, 'success');
    } else if (successCount === 0) {
        if (notFoundCount > 0) {
            showNotification(`❌ Wariant "${variantName}" nie jest dostępny dla żadnego produktu`, 'error');
        } else {
            showNotification(`❌ Nie udało się zmienić żadnego wariantu na "${variantName}"`, 'error');
        }
    } else {
        let message = `⚠️ Zmieniono ${successCount} produktów na "${variantName}".`;
        if (notFoundCount > 0) {
            message += ` ${notFoundCount} produktów nie ma tego wariantu.`;
        }
        if (errorCount > 0) {
            message += ` ${errorCount} produktów nie zostało zmienionych z powodu błędów.`;
        }
        showNotification(message, 'warning');
    }
}

// Dodaj animację spin do CSS (jeśli nie istnieje)
if (!document.querySelector('style[data-bulk-variant-styles]')) {
    const style = document.createElement('style');
    style.setAttribute('data-bulk-variant-styles', 'true');
    style.textContent = `
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    `;
    document.head.appendChild(style);
}


// Dodaj też funkcję pomocniczą do odświeżania modala po zmianach
async function refreshQuoteModal(quoteId) {
    try {
        console.log(`[refreshQuoteModal] Odświeżanie danych wyceny ${quoteId}`);

        // Pobierz zaktualizowane dane wyceny
        const response = await fetch(`/quotes/api/quotes/${quoteId}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const updatedQuoteData = await response.json();

        // Zaktualizuj modal z nowymi danymi
        populateQuoteDetailsModal(updatedQuoteData);

        console.log('[refreshQuoteModal] Modal został odświeżony');

    } catch (error) {
        console.error('[refreshQuoteModal] Błąd odświeżania modala:', error);
        showNotification('Błąd podczas odświeżania danych. Odśwież stronę.', 'error');
    }
}

// Funkcja pomocnicza do wyświetlania powiadomień (jeśli nie istnieje)
function showNotification(message, type = 'info') {
    console.log(`[showNotification] ${type.toUpperCase()}: ${message}`);

    // Sprawdź czy istnieje funkcja showToast (która już jest w Twoim kodzie)
    if (typeof showToast === 'function') {
        showToast(message, type);
        return;
    }

    // Fallback - prosty alert lub console.log
    if (type === 'error') {
        alert(`Błąd: ${message}`);
    } else if (type === 'success') {
        alert(`Sukces: ${message}`);
    } else if (type === 'warning') {
        alert(`Ostrzeżenie: ${message}`);
    } else {
        // Dla typu 'info' tylko console.log
        console.info(`[Info] ${message}`);
    }
}