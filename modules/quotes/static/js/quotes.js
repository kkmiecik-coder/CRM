// modules/quotes/static/js/quotes.js

console.log("quotes.js załadowany");

let allStatuses = {};
let allQuotes = [];
let activeStatus = null;
let currentPage = 1;
let resultsPerPage = 20;
let totalPages = 1;
let totalCount = 0;
let allUsers = [];
let currentEditingItem = null;
let currentQuoteData = null;
let discountReasons = [];
let originalPrices = {};
let acceptedQuotes = new Set(); // Set do śledzenia ID zaakceptowanych wycen
let isLoadingQuotes = false; // Flaga czy trwa ładowanie

document.addEventListener("DOMContentLoaded", () => {
    console.log("[DOMContentLoaded] Inicjalizacja komponentów");
    fetchQuotes();
    fetchQuotes().then(() => {
        initDownloadModal();
    });
    initStatusPanel();
    fetchUsers();
    fetchRoles();
    initClearFiltersButton();
    updateClearFiltersButtonState();
    initEditModals();
    initMobileFilters();

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

    // --- DXF Dropdown ---
    const dxfToggle = document.getElementById('dxf-dropdown-toggle');
    const dxfMenu = document.getElementById('dxf-dropdown-menu');

    if (dxfToggle && dxfMenu) {
        dxfToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = dxfMenu.style.display === 'block';
            dxfMenu.style.display = isOpen ? 'none' : 'block';
        });

        // Zamknij dropdown po kliknięciu poza nim
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.dxf-dropdown-wrapper')) {
                dxfMenu.style.display = 'none';
            }
        });

        document.getElementById('dxf-download-zip').addEventListener('click', () => {
            const token = document.getElementById('dxf-dropdown-wrapper').dataset.token;
            if (!token) { alert('Brak tokenu wyceny'); return; }
            window.location.href = `/quotes/api/quotes/${token}/dxf-zip`;
            dxfMenu.style.display = 'none';
        });
    }
});

// --- DXF: Mapowanie wariantów na czytelne nazwy ---
const DXF_VARIANT_LABELS = {
    'dab-lity-ab': 'Dąb Lity A/B',
    'dab-lity-bb': 'Dąb Lity B/B',
    'dab-micro-ab': 'Dąb Mikrowczep A/B',
    'dab-micro-bb': 'Dąb Mikrowczep B/B',
    'jes-lity-ab': 'Jesion Lity A/B',
    'jes-micro-ab': 'Jesion Mikrowczep A/B',
    'buk-lity-ab': 'Buk Lity A/B',
    'buk-micro-ab': 'Buk Mikrowczep A/B',
};

function populateDxfProductSubmenu(quoteData, token) {
    const submenu = document.getElementById('dxf-products-submenu');
    if (!submenu) return;

    submenu.innerHTML = '';
    const items = (quoteData.items || []).filter(i => i.is_selected);

    // Grupuj po product_index (unikalne produkty)
    const seen = new Set();
    items.forEach(item => {
        if (seen.has(item.product_index)) return;
        seen.add(item.product_index);

        const label = DXF_VARIANT_LABELS[item.variant_code] || item.variant_code || '?';
        const dims = `${item.length_cm || '?'}×${item.width_cm || '?'}×${item.thickness_cm || '?'}`;

        const btn = document.createElement('button');
        btn.className = 'dxf-submenu-item';
        btn.textContent = `${item.product_index}. ${label} (${dims} cm)`;
        btn.addEventListener('click', () => {
            window.location.href = `/quotes/api/quotes/${token}/dxf/${item.product_index}`;
            document.getElementById('dxf-dropdown-menu').style.display = 'none';
        });
        submenu.appendChild(btn);
    });
}

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

function fetchQuotes(page = null, perPage = null) {
    if (isLoadingQuotes) {
        console.log("[fetchQuotes] Ładowanie już w trakcie, pomijam...");
        return Promise.resolve();
    }

    // Użyj przekazanych parametrów lub domyślnych
    const targetPage = page !== null ? page : currentPage;
    const targetPerPage = perPage !== null ? perPage : resultsPerPage;

    console.info(`[fetchQuotes] Pobieranie wycen - strona ${targetPage}, wyników na stronę: ${targetPerPage}`);

    // Pokaż overlay z loaderem
    showLoadingOverlay();
    isLoadingQuotes = true;

    // Buduj URL z parametrami paginacji
    const url = `/quotes/api/quotes?page=${targetPage}&per_page=${targetPerPage}`;

    return fetch(url)
        .then(res => res.json())
        .then(data => {
            // Backend zwraca teraz obiekt z quotes i pagination
            allQuotes = data.quotes || [];
            const pagination = data.pagination || {};

            // Zaktualizuj zmienne paginacji
            currentPage = pagination.page || 1;
            resultsPerPage = pagination.per_page || 20;
            totalCount = pagination.total_count || 0;
            totalPages = pagination.total_pages || 1;

            console.log(`[fetchQuotes] Załadowano ${allQuotes.length} wycen (strona ${currentPage}/${totalPages}, łącznie: ${totalCount})`);

            // Pobierz statusy z pierwszej wyceny (jeśli istnieje)
            if (allQuotes.length > 0) {
                allStatuses = allQuotes[0].all_statuses;
            }

            // Renderuj tabelę i paginację
            renderQuotesTable(allQuotes);
            renderPagination();

            // Ukryj overlay
            hideLoadingOverlay();
            isLoadingQuotes = false;

            // NOWA FUNKCJONALNOŚĆ: Sprawdź czy mamy parametr open_quote w URL
            console.log("[fetchQuotes] Sprawdzam parametr open_quote...");
            checkForOpenQuoteParameter();
        })
        .catch(err => {
            console.error("[fetchQuotes] Błąd pobierania wycen:", err);
            hideLoadingOverlay();
            isLoadingQuotes = false;
            alert("Wystąpił błąd podczas pobierania wycen.");
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

function fetchRoles() {
    const select = document.getElementById("role-filter");
    if (!select) return; // Element nie istnieje (ukryty dla partnerów)

    fetch("/quotes/api/roles")
        .then(res => res.json())
        .then(data => {
            // Reset opcji przed dodaniem nowych
            select.innerHTML = '<option value="">Wszystkie</option>';

            data.forEach(role => {
                const opt = document.createElement("option");
                opt.value = role.value;
                opt.textContent = role.label;
                select.appendChild(opt);
            });
        })
        .catch(err => console.error("Błąd pobierania ról:", err));
}

/**
 * Inicjalizacja sekcji notatki w modalu szczegółów wyceny
 */
function initializeNoteSection(quoteData) {
    console.log('[NOTE] Inicjalizacja sekcji notatki dla wyceny:', quoteData.id);
    
    const noteTextarea = document.getElementById('quote-note-textarea');
    const editNoteBtn = document.getElementById('edit-note-btn');
    const saveNoteBtn = document.getElementById('save-note-btn');
    const cancelNoteBtn = document.getElementById('cancel-note-btn');
    const noteActionsRow = document.querySelector('.note-actions-row');
    const noteCounter = document.getElementById('quote-note-counter');
    const noteWarning = document.getElementById('note-length-warning');

    if (!noteTextarea) {
        console.warn('[NOTE] Brak elementu textarea notatki');
        return;
    }

    // Wypełnij textarea danymi z wyceny
    noteTextarea.value = quoteData.notes || '';
    noteTextarea.disabled = true; // Upewnij się że jest disabled na start
    console.log('[NOTE] Wypełniono notatkę:', quoteData.notes);

    // Ukryj elementy edycji na start
    if (noteActionsRow) noteActionsRow.style.display = 'none';
    if (noteWarning) noteWarning.style.display = 'none';
    if (editNoteBtn) editNoteBtn.disabled = false;

    // Usuń poprzednie event listenery (klonowanie elementów)
    if (editNoteBtn) {
        const newEditBtn = editNoteBtn.cloneNode(true);
        editNoteBtn.parentNode.replaceChild(newEditBtn, editNoteBtn);
        
        // Przycisk edycji - aktywuje tryb edycji
        newEditBtn.addEventListener('click', function() {
            console.log('[NOTE] Kliknięto przycisk edycji');
            
            if (quoteData.base_linker_order_id) {
                alert('Nie można edytować notatki - zamówienie zostało już złożone w Baselinker');
                return;
            }
            
            // Aktywuj edycję
            noteTextarea.disabled = false;
            noteTextarea.focus();
            
            // Pokaż wiersz akcji
            if (noteActionsRow) noteActionsRow.style.display = 'flex';
            
            // Dezaktywuj przycisk edycji
            newEditBtn.disabled = true;
            
            // Aktualizuj licznik
            updateNoteCounter();
            
            console.log('[NOTE] Aktywowano tryb edycji notatki');
        });
    }

    // Funkcja aktualizacji licznika znaków
    function updateNoteCounter() {
        if (!noteTextarea || !noteCounter || !noteWarning) return;
        
        const currentLength = noteTextarea.value.length;
        const remaining = 180 - currentLength;
        noteCounter.textContent = remaining;
        
        // Pokaż ostrzeżenie jeśli za długie
        if (currentLength > 180) {
            noteWarning.style.display = 'flex';
            if (noteCounter) noteCounter.classList.add('warning');
        } else {
            noteWarning.style.display = 'none';
            if (noteCounter) noteCounter.classList.remove('warning');
        }
    }

    // Event listener dla zmian w textarea
    const newTextarea = noteTextarea.cloneNode(true);
    noteTextarea.parentNode.replaceChild(newTextarea, noteTextarea);
    newTextarea.addEventListener('input', updateNoteCounter);

    // Przycisk Zapisz
    if (saveNoteBtn) {
        const newSaveBtn = saveNoteBtn.cloneNode(true);
        saveNoteBtn.parentNode.replaceChild(newSaveBtn, saveNoteBtn);
        
        newSaveBtn.addEventListener('click', async function() {
            console.log('[NOTE] Kliknięto przycisk Zapisz');
            const newNote = newTextarea.value.trim();
            
            // Walidacja długości
            if (newNote.length > 180) {
                alert('Notatka jest za długa. Maksymalna długość to 180 znaków.');
                return;
            }
            
            try {
                const response = await fetch(`/quotes/api/quotes/${quoteData.id}/note`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ notes: newNote })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    // Sukces - zaktualizuj dane lokalne
                    quoteData.notes = newNote;
                    
                    // Wyłącz tryb edycji
                    newTextarea.disabled = true;
                    if (noteActionsRow) noteActionsRow.style.display = 'none';
                    if (noteWarning) noteWarning.style.display = 'none';
                    if (document.getElementById('edit-note-btn')) {
                        document.getElementById('edit-note-btn').disabled = false;
                    }
                    
                    console.log('[NOTE] Notatka zapisana pomyślnie');
                    alert('Notatka została zaktualizowana');
                } else {
                    console.error('[NOTE] Błąd zapisu:', data.error);
                    alert(data.error || 'Błąd podczas zapisu notatki');
                }
            } catch (error) {
                console.error('[NOTE] Błąd sieci:', error);
                alert('Wystąpił błąd podczas zapisywania notatki');
            }
        });
    }

    // Przycisk Anuluj
    if (cancelNoteBtn) {
        const newCancelBtn = cancelNoteBtn.cloneNode(true);
        cancelNoteBtn.parentNode.replaceChild(newCancelBtn, cancelNoteBtn);
        
        newCancelBtn.addEventListener('click', function() {
            console.log('[NOTE] Kliknięto przycisk Anuluj');
            
            // Przywróć oryginalną wartość
            newTextarea.value = quoteData.notes || '';
            
            // Wyłącz tryb edycji
            newTextarea.disabled = true;
            if (noteActionsRow) noteActionsRow.style.display = 'none';
            if (noteWarning) noteWarning.style.display = 'none';
            if (document.getElementById('edit-note-btn')) {
                document.getElementById('edit-note-btn').disabled = false;
            }
            
            console.log('[NOTE] Anulowano edycję notatki');
        });
    }

    console.log('[NOTE] Inicjalizacja obsługi notatki zakończona');
}

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

    // Inicjalizuj toggle trybu wyceny
    initializeQuoteTypeToggle(quoteData);

    // ZAKTUALIZUJ Dane klienta
    document.getElementById('quotes-details-modal-client-name').textContent = quoteData.client?.client_name || '-';
    document.getElementById('quotes-details-modal-client-fullname').textContent = quoteData.client?.first_name || '-';
    document.getElementById('quotes-details-modal-client-company').textContent = quoteData.client?.company_name || '-';
    document.getElementById('quotes-details-modal-client-nip').textContent = quoteData.client?.nip || '-';
    const clientEmail = quoteData.client?.email;
    const clientPhone = quoteData.client?.phone;
    const emailSpan = document.getElementById('quotes-details-modal-client-email');
    const phoneSpan = document.getElementById('quotes-details-modal-client-phone');
    if (clientEmail) {
        emailSpan.innerHTML = `<a href="mailto:${clientEmail}" title="Wyślij e-mail">${clientEmail}</a>`;
    } else {
        emailSpan.textContent = '-';
    }
    if (clientPhone) {
        phoneSpan.innerHTML = `<a href="tel:${clientPhone}" title="Zadzwoń">${clientPhone}</a>`;
    } else {
        phoneSpan.textContent = '-';
    }

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

        // DXF button — widoczny tylko gdy zamówienie ma numer BaseLinker
        const dxfWrapper = document.getElementById('dxf-dropdown-wrapper');
        if (dxfWrapper) {
            const hasOrder = quoteData.base_linker_order_id && String(quoteData.base_linker_order_id).trim() !== '';
            dxfWrapper.style.display = hasOrder ? 'inline-flex' : 'none';
            if (hasOrder && token) {
                dxfWrapper.dataset.token = token;
                populateDxfProductSubmenu(quoteData, token);
            }
        }
    }

    updateCostsDisplay(quoteData);
    setupStatusDropdown(quoteData, optionsContainer, selectedDiv, dropdownWrap);
    setupProductTabs(quoteData, tabsContainer, itemsContainer);

    // Podepnij event listener do przycisku rabatu (jeśli istnieje w HTML)
    const totalDiscountBtn = document.getElementById('total-discount-btn');
    if (totalDiscountBtn) {
        // Usuń stare listenery (żeby nie duplikować)
        const newBtn = totalDiscountBtn.cloneNode(true);
        totalDiscountBtn.parentNode.replaceChild(newBtn, totalDiscountBtn);

        // Dodaj nowy listener
        document.getElementById('total-discount-btn').addEventListener('click', () => {
            console.log('[TOTAL DISCOUNT] Otwieranie modala rabatu całkowitego');
            openTotalDiscountModal(currentQuoteData);
        });
    }

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

    // Inicjalizacja sekcji notatki
    initializeNoteSection(quoteData);
    initializeAttachmentSection(quoteData);

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

/**
 * Inicjalizacja toggle trybu wyceny
 */
function initializeQuoteTypeToggle(quoteData) {
    console.log('[QUOTE TYPE] Inicjalizacja toggle, quote_type:', quoteData.quote_type);

    const bruttoRadio = document.getElementById('quoteTypeBrutto');
    const nettoRadio = document.getElementById('quoteTypeNetto');

    if (!bruttoRadio || !nettoRadio) {
        console.warn('[QUOTE TYPE] Brak elementów toggle w DOM');
        return;
    }

    // Ustaw aktualny stan na podstawie danych z API
    const currentType = quoteData.quote_type || 'brutto';

    if (currentType === 'netto') {
        nettoRadio.checked = true;
    } else {
        bruttoRadio.checked = true;
    }

    // Usuń stare listenery (żeby nie duplikować)
    const newBruttoRadio = bruttoRadio.cloneNode(true);
    const newNettoRadio = nettoRadio.cloneNode(true);
    bruttoRadio.parentNode.replaceChild(newBruttoRadio, bruttoRadio);
    nettoRadio.parentNode.replaceChild(newNettoRadio, nettoRadio);

    // Dodaj event listenery do zmiany
    newBruttoRadio.addEventListener('change', function () {
        if (this.checked) {
            handleQuoteTypeChange(quoteData.id, 'brutto');
        }
    });

    newNettoRadio.addEventListener('change', function () {
        if (this.checked) {
            handleQuoteTypeChange(quoteData.id, 'netto');
        }
    });

    console.log('[QUOTE TYPE] Toggle zainicjalizowany:', currentType);
}

/**
 * Obsługa zmiany trybu wyceny
 */
async function handleQuoteTypeChange(quoteId, newQuoteType) {
    console.log('[QUOTE TYPE] Zmiana na:', newQuoteType);

    // Pokaż alert z potwierdzeniem
    const confirmMessage = `Czy na pewno chcesz zmienić tryb wyceny na "${newQuoteType.toUpperCase()}"?\n\nDane zostaną zapisane w bazie danych.`;

    if (!confirm(confirmMessage)) {
        // Anulowano - przywróć poprzedni stan
        const currentType = currentQuoteData.quote_type || 'brutto';
        if (currentType === 'brutto') {
            document.getElementById('quoteTypeBrutto').checked = true;
        } else {
            document.getElementById('quoteTypeNetto').checked = true;
        }
        console.log('[QUOTE TYPE] Zmiana anulowana');
        return;
    }

    // Wywołaj endpoint
    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}/update-quote-type`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                quote_type: newQuoteType
            })
        });

        if (!response.ok) {
            throw new Error('Błąd podczas aktualizacji trybu wyceny');
        }

        const result = await response.json();
        console.log('[QUOTE TYPE] Zaktualizowano:', result);

        // Zaktualizuj currentQuoteData
        currentQuoteData.quote_type = newQuoteType;

        // STARA METODA: Zastosuj nowe style (tylko ukrywa/pokazuje istniejące elementy)
        // applyQuoteTypeStyles(newQuoteType);

        // NOWA METODA: Przeładuj całe kafelki wariantów z nowym trybem
        console.log('[QUOTE TYPE] Przeładowuję kafelki wariantów...');
        await reloadQuoteDetailsModal(quoteId);

        // Pokaż toast sukcesu
        showToast(`Tryb wyceny zmieniony na "${newQuoteType.toUpperCase()}"`, 'success');

    } catch (error) {
        console.error('[QUOTE TYPE] Błąd:', error);
        showToast('Błąd podczas zmiany trybu wyceny', 'error');

        // Przywróć poprzedni stan toggle
        const currentType = currentQuoteData.quote_type || 'brutto';
        if (currentType === 'brutto') {
            document.getElementById('quoteTypeBrutto').checked = true;
        } else {
            document.getElementById('quoteTypeNetto').checked = true;
        }
    }
}

/**
 * Przeładowanie całego modala szczegółów wyceny
 */
async function reloadQuoteDetailsModal(quoteId) {
    console.log('[QUOTE TYPE] === ROZPOCZĘCIE PRZEŁADOWANIA MODALA ===');
    console.log('[QUOTE TYPE] Przeładowuję modal dla wyceny ID:', quoteId);

    try {
        // 1. Pobierz świeże dane z API
        const response = await fetch(`/quotes/api/quotes/${quoteId}`);

        if (!response.ok) {
            throw new Error('Błąd podczas pobierania danych wyceny');
        }

        const freshQuoteData = await response.json();
        console.log('[QUOTE TYPE] Pobrano świeże dane:', freshQuoteData);
        console.log('[QUOTE TYPE] Nowy tryb wyceny:', freshQuoteData.quote_type);

        // 2. Zaktualizuj globalną zmienną
        currentQuoteData = freshQuoteData;
        window.currentQuoteData = freshQuoteData;
        console.log('[QUOTE TYPE] Zaktualizowano currentQuoteData');

        // 3. KLUCZOWE: Reinicjalizuj toggle (żeby wizualnie był w dobrym stanie)
        console.log('[QUOTE TYPE] Reinicjalizuję toggle...');
        initializeQuoteTypeToggle(freshQuoteData);

        // 4. Znajdź kontenery do aktualizacji
        const tabsContainer = document.getElementById('quotes-details-tabs');
        const itemsContainer = document.getElementById('quotes-details-modal-items-body');

        if (!tabsContainer || !itemsContainer) {
            console.error('[QUOTE TYPE] Nie znaleziono kontenerów!');
            console.error('[QUOTE TYPE] tabs:', tabsContainer, 'items:', itemsContainer);
            return;
        }

        // 5. Wyczyść i przebuduj zakładki oraz produkty (kafelki wariantów)
        console.log('[QUOTE TYPE] Przebudowuję zakładki i kafelki produktów...');
        setupProductTabs(freshQuoteData, tabsContainer, itemsContainer);

        // 6. Zaktualizuj sekcję kosztów
        console.log('[QUOTE TYPE] Aktualizuję sekcję kosztów...');
        updateCostsDisplay(freshQuoteData);

        // 7. USUŃ to - nie potrzebujemy już aplikować stylów, bo kafelki są już z dobrym HTML
        // applyQuoteTypeStyles(freshQuoteData.quote_type || 'brutto');

        console.log('[QUOTE TYPE] ✅ Modal przeładowany pomyślnie');

    } catch (error) {
        console.error('[QUOTE TYPE] ❌ Błąd podczas przeładowania modala:', error);
        throw error;
    }
}
function updateMultiplierDisplay(quoteData) {
    const multiplierElement = document.getElementById('quotes-details-modal-multiplier');
    if (!multiplierElement) return;

    if (quoteData.quote_client_type && quoteData.quote_multiplier) {
        multiplierElement.textContent = `${quoteData.quote_client_type} (${quoteData.quote_multiplier})`;
    } else if (quoteData.quote_client_type) {
        multiplierElement.textContent = quoteData.quote_client_type;
    } else {
        multiplierElement.textContent = 'Nie określono';
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

            // Koszt surowych - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-products-brutto').textContent = `${costs.products.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-netto').textContent = `${costs.products.netto.toFixed(2)} PLN`;

            // Koszt wykończenia - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-finishing-brutto').textContent = `${costs.finishing.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-finishing-netto').textContent = `${costs.finishing.netto.toFixed(2)} PLN`;

            // NOWE: Suma produktów bez dostawy (surowe + wykończenie) - POPRAWKA: bez nawiasów
            const productsTotalNetto = costs.products.netto + costs.finishing.netto;
            const productsTotalBrutto = costs.products.brutto + costs.finishing.brutto;

            document.getElementById('quotes-details-modal-cost-products-total-brutto').textContent = `${productsTotalBrutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-total-netto').textContent = `${productsTotalNetto.toFixed(2)} PLN`;

            // Koszt wysyłki - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-shipping-brutto').textContent = `${costs.shipping.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-shipping-netto').textContent = `${costs.shipping.netto.toFixed(2)} PLN`;

            // Koszt całkowity - POPRAWKA: bez nawiasów
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

            // Koszt surowych - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-products-brutto').textContent = `${costs.products.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-netto').textContent = `${costs.products.netto.toFixed(2)} PLN`;

            // Koszt wykończenia - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-finishing-brutto').textContent = `${costs.finishing.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-finishing-netto').textContent = `${costs.finishing.netto.toFixed(2)} PLN`;

            // NOWE: Suma produktów bez dostawy - POPRAWKA: bez nawiasów
            const productsTotalNetto = costs.products.netto + costs.finishing.netto;
            const productsTotalBrutto = costs.products.brutto + costs.finishing.brutto;

            document.getElementById('quotes-details-modal-cost-products-total-brutto').textContent = `${productsTotalBrutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-products-total-netto').textContent = `${productsTotalNetto.toFixed(2)} PLN`;

            // Koszt wysyłki - POPRAWKA: bez nawiasów
            document.getElementById('quotes-details-modal-cost-shipping-brutto').textContent = `${costs.shipping.brutto.toFixed(2)} PLN`;
            document.getElementById('quotes-details-modal-cost-shipping-netto').textContent = `${costs.shipping.netto.toFixed(2)} PLN`;

            // Koszt całkowity - POPRAWKA: bez nawiasów
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

    // DODAJ TO:
    // Zastosuj style dla sekcji kosztów (ukryj/pokaż brutto, styluj netto)
    const currentType = quoteData.quote_type || 'brutto';
    console.log('[updateCostsDisplay] Aplikuję style kosztów dla trybu:', currentType);

    if (currentType === 'netto') {
        // Ukryj kwoty brutto w sekcji kosztów
        const bruttoElements = [
            'quotes-details-modal-cost-products-brutto',
            'quotes-details-modal-cost-finishing-brutto',
            'quotes-details-modal-cost-products-total-brutto',
            'quotes-details-modal-cost-shipping-brutto',
            'quotes-details-modal-cost-total-brutto'
        ];
        bruttoElements.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });

        // Styluj kwoty netto jako główne
        const nettoElements = [
            'quotes-details-modal-cost-products-netto',
            'quotes-details-modal-cost-finishing-netto',
            'quotes-details-modal-cost-products-total-netto',
            'quotes-details-modal-cost-shipping-netto',
            'quotes-details-modal-cost-total-netto'
        ];
        nettoElements.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.style.fontSize = '14px';
                el.style.color = '#1F2020';
            }
        });
    } else {
        // Pokaż kwoty brutto
        const bruttoElements = [
            'quotes-details-modal-cost-products-brutto',
            'quotes-details-modal-cost-finishing-brutto',
            'quotes-details-modal-cost-products-total-brutto',
            'quotes-details-modal-cost-shipping-brutto',
            'quotes-details-modal-cost-total-brutto'
        ];
        bruttoElements.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = '';
        });

        // Przywróć style netto jako drugorzędne
        const nettoElements = [
            'quotes-details-modal-cost-products-netto',
            'quotes-details-modal-cost-finishing-netto',
            'quotes-details-modal-cost-products-total-netto',
            'quotes-details-modal-cost-shipping-netto',
            'quotes-details-modal-cost-total-netto'
        ];
        nettoElements.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.style.fontSize = '';
                el.style.fontWeight = '';
                el.style.color = '';
            }
        });
    }
}
function updateBaselinkerSection(quoteData) {
    console.log('[Baselinker] Aktualizacja sekcji zamówienia:', quoteData.base_linker_order_id);

    const orderBlock = document.getElementById('baselinker-order-block');
    const orderNumber = document.getElementById('baselinker-order-number');
    const orderLink = document.getElementById('baselinker-order-link');
    const orderStatus = document.getElementById('baselinker-order-status');

    if (!orderBlock || !orderNumber || !orderLink || !orderStatus) {
        console.warn('[Baselinker] Brak elementów bloku zamówienia Baselinker');
        return;
    }

    // Sprawdź czy wycena ma zamówienie Baselinker
    if (quoteData.base_linker_order_id) {
        orderBlock.style.display = 'block';
        orderNumber.textContent = `#${quoteData.base_linker_order_id}`;
        orderLink.href = `https://panel-f.baselinker.com/orders.php#order:${quoteData.base_linker_order_id}`;

        // Pobierz status z Baselinker (asynchronicznie)
        fetchBaselinkerOrderStatus(quoteData.base_linker_order_id)
            .then(status => {
                orderStatus.textContent = status || 'Nieznany';
            })
            .catch(error => {
                console.error('[Baselinker] Błąd pobierania statusu:', error);
                orderStatus.textContent = 'Błąd pobierania lub nie znaleziono zamówienia';
            });

        // NOWE: Załaduj dokumenty sprzedaży
        console.log('[Baselinker] Ładuję dokumenty sprzedaży...');
        loadSalesDocuments(quoteData);

        // NOWE: Linia czasu produkcji + status produkcji
        loadProductionTimeline(quoteData.base_linker_order_id);
    } else {
        orderBlock.style.display = 'none';
        hideProductionTimeline();
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

function hideProductionTimeline() {
    const tl = document.getElementById('production-timeline');
    const row = document.getElementById('production-status-row');
    if (tl) tl.style.display = 'none';
    if (row) row.style.display = 'none';
}

async function loadProductionTimeline(baselinkerOrderId) {
    if (!baselinkerOrderId) { hideProductionTimeline(); return; }
    try {
        const resp = await fetch(`/production/api/order-timeline/${baselinkerOrderId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!data.success || !data.has_data) { hideProductionTimeline(); return; }
        renderProductionStatus(data.order_status);
        renderProductionTimeline(data.stations);
    } catch (err) {
        console.error('[Timeline] Błąd ładowania linii czasu produkcji:', err);
        hideProductionTimeline();
    }
}

function renderProductionStatus(orderStatus) {
    const row = document.getElementById('production-status-row');
    const badge = document.getElementById('production-status-badge');
    if (!row || !badge || !orderStatus) return;
    badge.textContent = orderStatus.label;
    badge.className = `prod-status-badge ${orderStatus.badge_class || ''}`;
    row.style.display = '';
}

function renderProductionTimeline(stations) {
    const wrap = document.getElementById('production-timeline');
    const track = document.getElementById('production-timeline-track');
    if (!wrap || !track) return;
    if (!stations || stations.length === 0) { wrap.style.display = 'none'; return; }

    track.innerHTML = '';
    stations.forEach(st => {
        const dot = document.createElement('div');
        dot.className = `timeline-dot dot-${st.color}`;

        const tip = document.createElement('div');
        tip.className = 'timeline-tooltip';

        const title = document.createElement('div');
        title.className = 'timeline-tooltip-title';
        title.textContent = st.name;
        tip.appendChild(title);

        if (st.active && st.products_here && st.products_here.length > 0) {
            const list = document.createElement('div');
            list.className = 'timeline-tooltip-list';
            st.products_here.forEach(p => {
                const item = document.createElement('div');
                item.className = 'timeline-tooltip-item';
                const dims = `${p.length_cm}×${p.width_cm}×${p.thickness_cm} cm`;
                const spec = [p.species, p.technology, p.wood_class].filter(Boolean).join(' · ');
                item.innerHTML =
                    `<b>Poz. ${escapeHtmlTimeline(p.short_product_id)}</b> — ${escapeHtmlTimeline(dims)}` +
                    (spec ? `<br><span class="ti-spec">${escapeHtmlTimeline(spec)}</span>` : '');
                list.appendChild(item);
            });
            tip.appendChild(list);
        }

        dot.appendChild(tip);
        track.appendChild(dot);
    });
    wrap.style.display = '';
}

function escapeHtmlTimeline(str) {
    const d = document.createElement('div');
    d.textContent = str == null ? '' : String(str);
    return d.innerHTML;
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
        opt.dataset.name = s.name;
        opt.dataset.color = s.color || '#999';
        opt.innerHTML = `<span class="status-dot" style="background:${s.color || '#999'}"></span>${s.name}`;
        optionsContainer.appendChild(opt);

        if (s.name === quoteData.status_name) {
            selectedDiv.innerHTML = `<span class="status-dot" style="background:${s.color || '#999'}"></span>${s.name}`;
            selectedDiv.style.removeProperty('background-color');
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
    // NOWE: Sprawdź tryb wyceny
    const quoteType = quoteData.quote_type || 'brutto';
    const isNettoMode = quoteType === 'netto';

    console.log('[buildVariantPriceDisplay] Tryb wyceny:', quoteType, 'isNettoMode:', isNettoMode);

    // Znajdź szczegóły wykończenia dla tego produktu
    const finishing = (quoteData.finishing || []).find(f => f.product_index == variant.product_index);
    const finishingType = finishing ? finishing.finishing_type : 'Surowe';
    const hasPaintFinishing = finishingType && finishingType !== 'Surowe' && finishingType !== 'Brak';
    const hasEdges = finishing && (finishing.edges_price_brutto > 0 || finishing.edges_price_netto > 0);
    // Wykończenie = malowanie LUB obróbka krawędzi
    const hasFinishing = hasPaintFinishing || hasEdges;

    // Przygotuj nazwę wariantu
    const variantName = translateVariantCode(variant.variant_code);

    // Przelicz ceny jednostkowe i całkowite
    const unitPriceBrutto = variant.unit_price_brutto || variant.final_price_brutto || 0;
    const unitPriceNetto = variant.unit_price_netto || variant.final_price_netto || 0;
    const totalBrutto = unitPriceBrutto * quantity;
    const totalNetto = unitPriceNetto * quantity;
    const pricePerM3 = variant.price_per_m3 || 0;

    // Ceny wykończenia i krawędzi (jeśli istnieje)
    let finishingPriceBrutto = 0;
    let finishingPriceNetto = 0;
    if (finishing) {
        const finishingQuantity = finishing.quantity || quantity || 1;
        // Uwzględnij zarówno wykończenie jak i obróbkę krawędzi
        const totalFinishingBrutto = (finishing.finishing_price_brutto || 0) + (finishing.edges_price_brutto || 0);
        const totalFinishingNetto = (finishing.finishing_price_netto || 0) + (finishing.edges_price_netto || 0);
        finishingPriceBrutto = totalFinishingBrutto / finishingQuantity;
        finishingPriceNetto = totalFinishingNetto / finishingQuantity;
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
                    <div class="qvmd-variant-title"><span class="qvmd-variant-name">${variantName}</span></div>
                    <div class="qvmd-price-per-m2-wrapper">
                        <div class="qvmd-price-per-m2-label">Cena za m³:</div>
                        <div class="qvmd-price-per-m2-value">${pricePerM3.toFixed(2)} PLN</div>
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
        `;

        // NOWE: Warunkowe generowanie HTML dla brutto/netto
        if (isNettoMode) {
            // Tryb NETTO - tylko kwoty netto, większe i pogrubione
            cardHTML += `
                            <div class="qvmd-price-netto qvmd-netto-primary">${unitPriceNetto.toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - standard: brutto na górze, netto na dole
            cardHTML += `
                            <div class="qvmd-price-brutto">${unitPriceBrutto.toFixed(2)} PLN</div>
                            <div class="qvmd-price-netto">${unitPriceNetto.toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
                        </div>
                        <div class="qvmd-pricing-values">
        `;

        if (isNettoMode) {
            // Tryb NETTO - tylko wykończenie netto
            cardHTML += `
                            <div class="qvmd-price-netto qvmd-netto-primary qvmd-finishing">${(unitPriceNetto + finishingPriceNetto).toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - wykończenie brutto i netto
            cardHTML += `
                            <div class="qvmd-price-brutto qvmd-finishing">${(unitPriceBrutto + finishingPriceBrutto).toFixed(2)} PLN</div>
                            <div class="qvmd-price-netto">${(unitPriceNetto + finishingPriceNetto).toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
                        </div>
                    </div>
                    
                    <!-- Wiersz "Wartość" -->
                    <div class="qvmd-pricing-row">
                        <span class="qvmd-pricing-label">Wartość</span>
                        <div class="qvmd-pricing-values">
        `;

        if (isNettoMode) {
            // Tryb NETTO - tylko wartość netto
            cardHTML += `
                            <div class="qvmd-price-netto qvmd-netto-primary">${totalNetto.toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - wartość brutto i netto
            cardHTML += `
                            <div class="qvmd-price-brutto">${totalBrutto.toFixed(2)} PLN</div>
                            <div class="qvmd-price-netto">${totalNetto.toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
                        </div>
                        <div class="qvmd-pricing-values">
        `;

        if (isNettoMode) {
            // Tryb NETTO - tylko wykończenie wartość netto
            cardHTML += `
                            <div class="qvmd-price-netto qvmd-netto-primary qvmd-finishing">${(totalNetto + finishingTotalNetto).toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - wykończenie wartość brutto i netto
            cardHTML += `
                            <div class="qvmd-price-brutto qvmd-finishing">${(totalBrutto + finishingTotalBrutto).toFixed(2)} PLN</div>
                            <div class="qvmd-price-netto">${(totalNetto + finishingTotalNetto).toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
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
        `;

        if (isNettoMode) {
            // Tryb NETTO - tylko cena netto
            cardHTML += `
                                <div class="qvmd-price-netto qvmd-netto-primary">${unitPriceNetto.toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - cena brutto i netto
            cardHTML += `
                                <div class="qvmd-price-brutto">${unitPriceBrutto.toFixed(2)} PLN</div>
                                <div class="qvmd-price-netto">${unitPriceNetto.toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
                            </div>
                        </div>
                        <div class="qvmd-pricing-row">
                            <span class="qvmd-pricing-label">Wartość</span>
                            <div class="qvmd-pricing-values">
        `;

        if (isNettoMode) {
            // Tryb NETTO - tylko wartość netto
            cardHTML += `
                                <div class="qvmd-price-netto qvmd-netto-primary">${totalNetto.toFixed(2)} PLN</div>
            `;
        } else {
            // Tryb BRUTTO - wartość brutto i netto
            cardHTML += `
                                <div class="qvmd-price-brutto">${totalBrutto.toFixed(2)} PLN</div>
                                <div class="qvmd-price-netto">${totalNetto.toFixed(2)} PLN</div>
            `;
        }

        cardHTML += `
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

    // Sprawdź rolę użytkownika
    const userRole = window.userRole || 'user';
    const isPartner = userRole === 'partner';

    console.log('[buildVariantPriceDisplay] Rola użytkownika:', userRole, 'isPartner:', isPartner);

    // Przycisk wyboru wariantu - ZAWSZE WIDOCZNY
    if (variant.is_selected) {
        cardHTML += `<button class="qvmd-btn qvmd-btn-selected">✓ Wybrany wariant</button>`;
    } else {
        cardHTML += `<button class="qvmd-btn" onclick="selectVariant(${variant.id})">Ustaw jako wybrany</button>`;
    }

    // Przycisk edycji - TYLKO dla admin i user (UKRYTY dla partnera)
    if (!isPartner) {
        cardHTML += `
                    <button class="qvmd-btn qvmd-btn-edit" onclick="openVariantEditModal(${JSON.stringify(variant).replace(/"/g, '&quot;')}, currentQuoteData)">
                        <img src="/quotes/quotes/static/img/edit.svg" alt="Edytuj" class="qvmd-edit-icon">
                    </button>
        `;
    }

    cardHTML += `
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

    // Badge "Niewidoczny" — wyśrodkowany na górze karty
    if (variant.show_on_client_page === false) {
        badgesHTML = `
            <div class="qvmd-variant-badges">
                <div class="qvmd-badge qvmd-badge-invisible">Niewidoczny</div>
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

        // Sprawdź czy produkt ma wykończenie (malowanie LUB krawędzie)
        const finishing = (quoteData.finishing || []).find(f => f.product_index == index);
        const finishingType = finishing ? finishing.finishing_type : 'Surowe';
        const hasPaintFinishing = finishingType && finishingType !== 'Surowe' && finishingType !== 'Brak';
        const hasEdges = finishing && (finishing.edges_price_brutto > 0 || finishing.edges_price_netto > 0);
        const productHasFinishing = hasPaintFinishing || hasEdges;

        // Znajdź warianty z wykończeniem
        const variantsWithFinishing = productHasFinishing ? grouped[index] : [];

        // Znajdź warianty surowe
        const rawVariants = productHasFinishing ? [] : grouped[index];

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

function filterQuotes(resetPage = true) {
    console.log("[filterQuotes] Uruchamianie filtrowania...");

    // Resetuj do pierwszej strony przy zmianie filtrów (nie przy paginacji)
    if (resetPage) currentPage = 1;

    // Pobierz wartości filtrów
    const quoteNumber = document.getElementById("quote-number-filter")?.value || "";
    const clientNumber = document.getElementById("client-number-filter")?.value || "";
    const clientName = document.getElementById("client-name-filter")?.value || "";
    const source = document.getElementById("source-filter")?.value || "";
    const employee = document.getElementById("employee-filter")?.value || "";
    const userRole = document.getElementById("role-filter")?.value || "";
    const dateFrom = document.getElementById("date-from-filter")?.value || "";
    const dateTo = document.getElementById("date-to-filter")?.value || "";

    if (isLoadingQuotes) {
        console.log("[filterQuotes] Ładowanie już w trakcie, pomijam...");
        return;
    }

    // Pokaż overlay z loaderem
    showLoadingOverlay();
    isLoadingQuotes = true;

    // Buduj URL z parametrami paginacji i filtrów
    const params = new URLSearchParams({
        page: currentPage,
        per_page: resultsPerPage
    });

    // Dodaj filtry tylko jeśli mają wartość
    if (quoteNumber) params.append('quote_number', quoteNumber);
    if (clientNumber) params.append('client_number', clientNumber);
    if (clientName) params.append('client_name', clientName);
    if (source) params.append('source', source);
    if (employee) params.append('employee_id', employee);
    if (userRole) params.append('user_role', userRole);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (activeStatus) params.append('status', activeStatus);

    const url = `/quotes/api/quotes?${params.toString()}`;
    console.log(`[filterQuotes] URL: ${url}`);

    fetch(url)
        .then(res => res.json())
        .then(data => {
            // Backend zwraca teraz obiekt z quotes i pagination
            allQuotes = data.quotes || [];
            const pagination = data.pagination || {};

            // Zaktualizuj zmienne paginacji
            currentPage = pagination.page || 1;
            resultsPerPage = pagination.per_page || 20;
            totalCount = pagination.total_count || 0;
            totalPages = pagination.total_pages || 1;

            console.log(`[filterQuotes] Załadowano ${allQuotes.length} wycen (strona ${currentPage}/${totalPages}, łącznie: ${totalCount})`);

            // Pobierz statusy z pierwszej wyceny (jeśli istnieje)
            if (allQuotes.length > 0) {
                allStatuses = allQuotes[0].all_statuses;
            }

            // Renderuj tabelę i paginację
            renderQuotesTable(allQuotes);
            renderPagination();

            // Ukryj overlay
            hideLoadingOverlay();
            isLoadingQuotes = false;
        })
        .catch(err => {
            console.error("[filterQuotes] Błąd pobierania wycen:", err);
            hideLoadingOverlay();
            isLoadingQuotes = false;
            alert("Wystąpił błąd podczas filtrowania wycen.");
        });
}

function shortenStatus(name) {
    const map = {
        'Nowa wycena': 'Nowa wyc.',
        'Odrzucone': 'Odrzuc.',
        'Rezygnacja': 'Rezygn.',
        'W akceptacji': 'W akcept.',
        'Wysłano przypomnienie': 'Wysł. przyp.',
        'Zaakceptowane': 'Zaakcept.',
        'Zamówione': 'Zam.',
    };
    return map[name] || name;
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
        const statusShort = shortenStatus(quote.status_name);
        const statusPill = `
            <div class="quote-status-pill" style="background-color: ${quote.status_color}">
                <span class="status-full">${quote.status_name}</span>
                <span class="status-short">${statusShort}</span>
            </div>
        `;
        card.innerHTML = `
            <div class="quote-field" data-label="Numer">${quote.quote_number}</div>
            <div class="quote-field" data-label="Data">${new Date(quote.created_at).toLocaleDateString()}</div>
            <div class="quote-field" data-label="Klient">${quote.client_number || "-"}</div>
            <div class="quote-field" data-label="Imię i nazwisko">${quote.client_name || "-"}</div>
            <div class="quote-field" data-label="Opiekun">${quote.client_caretaker_name || "-"}</div>
            <div class="quote-field" data-label="Źródło">${quote.source || "-"}</div>
            <div class="quote-field quote-field-status">${statusPill}</div>
            <div class="quote-field quote-field-actions">
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
        const counts = await fetch("/quotes/api/quotes/status-counts").then(res => res.json());

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
    // Usuń automatyczne filtrowanie - teraz wymaga przycisku "Filtruj wyceny"
    // Dodaj tylko nasłuchiwanie Enter na inputach tekstowych
    ["quote-number-filter", "client-number-filter", "client-name-filter"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("keypress", (e) => {
                if (e.key === "Enter") {
                    filterQuotes();
                }
            });
        }
    });

    // Przycisk "Filtruj wyceny"
    const applyFiltersBtn = document.getElementById("apply-filters");
    if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener("click", () => {
            console.log("[ApplyFilters] Kliknięto przycisk Filtruj wyceny");
            filterQuotes();
        });
    }
});

function renderPagination() {
    console.log(`[renderPagination] Strona ${currentPage}/${totalPages}, łącznie: ${totalCount}`);

    let container = document.getElementById("pagination-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "pagination-container";
        container.className = "quotes-pagination-wrapper";
        document.querySelector(".quotes-main").appendChild(container);
    }

    container.innerHTML = "";

    // Jeśli nie ma wyników, nie pokazuj paginacji
    if (totalPages === 0) {
        return;
    }

    // Kontener na paginację (środek)
    const paginationDiv = document.createElement("div");
    paginationDiv.className = "quotes-pagination-center";

    // Przycisk Previous
    const prevBtn = document.createElement("button");
    prevBtn.className = "pagination-arrow";
    prevBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M7.5 2L3.5 6L7.5 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
    prevBtn.disabled = currentPage === 1;
    prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            goToPage(currentPage - 1);
        }
    });

    // Przycisk pierwszej strony
    const firstPageBtn = document.createElement("button");
    firstPageBtn.className = "pagination-number" + (currentPage === 1 ? " active" : "");
    firstPageBtn.textContent = "1";
    firstPageBtn.addEventListener("click", () => goToPage(1));

    // Kontener na środkowe elementy
    const middleContainer = document.createElement("div");
    middleContainer.className = "pagination-middle";

    // Logika wyświetlania numerów stron
    // Strona 1 (początek): < [1] 2 ... 43 >
    if (currentPage === 1 && totalPages > 1) {
        const page2Btn = document.createElement("button");
        page2Btn.className = "pagination-number";
        page2Btn.textContent = "2";
        page2Btn.addEventListener("click", () => goToPage(2));
        middleContainer.appendChild(page2Btn);

        if (totalPages > 2) {
            const dots = document.createElement("button");
            dots.className = "pagination-dots";
            dots.textContent = "...";
            dots.addEventListener("click", () => openGoToPageModal());
            middleContainer.appendChild(dots);
        }
    }
    // Strona 2: < 1 [2] 3 ... 43 >
    else if (currentPage === 2) {
        const page2Btn = document.createElement("button");
        page2Btn.className = "pagination-number active";
        page2Btn.textContent = "2";
        page2Btn.addEventListener("click", () => goToPage(2));
        middleContainer.appendChild(page2Btn);

        if (totalPages > 2) {
            const page3Btn = document.createElement("button");
            page3Btn.className = "pagination-number";
            page3Btn.textContent = "3";
            page3Btn.addEventListener("click", () => goToPage(3));
            middleContainer.appendChild(page3Btn);
        }

        if (totalPages > 3) {
            const dots = document.createElement("button");
            dots.className = "pagination-dots";
            dots.textContent = "...";
            dots.addEventListener("click", () => openGoToPageModal());
            middleContainer.appendChild(dots);
        }
    }
    // Strona 3: < 1 2 [3] 4 ... 43 >
    else if (currentPage === 3) {
        const page2Btn = document.createElement("button");
        page2Btn.className = "pagination-number";
        page2Btn.textContent = "2";
        page2Btn.addEventListener("click", () => goToPage(2));
        middleContainer.appendChild(page2Btn);

        const page3Btn = document.createElement("button");
        page3Btn.className = "pagination-number active";
        page3Btn.textContent = "3";
        page3Btn.addEventListener("click", () => goToPage(3));
        middleContainer.appendChild(page3Btn);

        if (totalPages > 3) {
            const page4Btn = document.createElement("button");
            page4Btn.className = "pagination-number";
            page4Btn.textContent = "4";
            page4Btn.addEventListener("click", () => goToPage(4));
            middleContainer.appendChild(page4Btn);
        }

        if (totalPages > 4) {
            const dots = document.createElement("button");
            dots.className = "pagination-dots";
            dots.textContent = "...";
            dots.addEventListener("click", () => openGoToPageModal());
            middleContainer.appendChild(dots);
        }
    }
    // Strony środkowe (4+): < 1 ... prev [current] next ... 43 >
    else if (currentPage > 3 && currentPage < totalPages) {
        // Kropki na początku
        const dotsStart = document.createElement("button");
        dotsStart.className = "pagination-dots";
        dotsStart.textContent = "...";
        dotsStart.addEventListener("click", () => openGoToPageModal());
        middleContainer.appendChild(dotsStart);

        // Poprzednia strona
        const prevPageBtn = document.createElement("button");
        prevPageBtn.className = "pagination-number";
        prevPageBtn.textContent = currentPage - 1;
        prevPageBtn.addEventListener("click", () => goToPage(currentPage - 1));
        middleContainer.appendChild(prevPageBtn);

        // Aktualna strona
        const currentBtn = document.createElement("button");
        currentBtn.className = "pagination-number active";
        currentBtn.textContent = currentPage;
        currentBtn.addEventListener("click", () => goToPage(currentPage));
        middleContainer.appendChild(currentBtn);

        // Następna strona
        const nextPageBtn = document.createElement("button");
        nextPageBtn.className = "pagination-number";
        nextPageBtn.textContent = currentPage + 1;
        nextPageBtn.addEventListener("click", () => goToPage(currentPage + 1));
        middleContainer.appendChild(nextPageBtn);

        // Kropki na końcu (tylko jeśli nie jesteśmy obok ostatniej strony)
        if (currentPage < totalPages - 1) {
            const dotsEnd = document.createElement("button");
            dotsEnd.className = "pagination-dots";
            dotsEnd.textContent = "...";
            dotsEnd.addEventListener("click", () => openGoToPageModal());
            middleContainer.appendChild(dotsEnd);
        }
    }
    // Ostatnia strona (jeśli istnieje więcej niż 1 strona)
    let lastPageBtn = null;
    if (totalPages > 1) {
        lastPageBtn = document.createElement("button");
        lastPageBtn.className = "pagination-number" + (currentPage === totalPages ? " active" : "");
        lastPageBtn.textContent = totalPages;
        lastPageBtn.addEventListener("click", () => goToPage(totalPages));
    }

    // Przycisk Next
    const nextBtn = document.createElement("button");
    nextBtn.className = "pagination-arrow";
    nextBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M4.5 2L8.5 6L4.5 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.addEventListener("click", () => {
        if (currentPage < totalPages) {
            goToPage(currentPage + 1);
        }
    });

    // Złóż paginację
    paginationDiv.appendChild(prevBtn);
    paginationDiv.appendChild(firstPageBtn);
    if (totalPages > 1) {
        paginationDiv.appendChild(middleContainer);
        if (lastPageBtn) {
            paginationDiv.appendChild(lastPageBtn);
        }
    }
    paginationDiv.appendChild(nextBtn);

    // Dodaj paginację do kontenera
    container.appendChild(paginationDiv);

    // Selektor ilości wyników — nad tabelą
    renderPerPageSelector();
}

function renderPerPageSelector() {
    const quotesMain = document.querySelector(".quotes-main");
    if (!quotesMain) return;

    let selectWrapper = document.getElementById("per-page-selector");
    if (!selectWrapper) {
        selectWrapper = document.createElement("div");
        selectWrapper.id = "per-page-selector";
        selectWrapper.className = "quotes-per-page-wrapper";

        const selectLabel = document.createElement("span");
        selectLabel.textContent = "Wyników na stronę:";
        selectLabel.className = "pagination-select-label";

        const select = document.createElement("select");
        select.className = "pagination-select";
        select.id = "per-page-select";

        [20, 50, 100, 200].forEach(n => {
            const opt = document.createElement("option");
            opt.value = n;
            opt.textContent = `${n}`;
            select.appendChild(opt);
        });

        select.addEventListener("change", () => {
            resultsPerPage = parseInt(select.value);
            currentPage = 1;
            fetchQuotes();
        });

        selectWrapper.appendChild(selectLabel);
        selectWrapper.appendChild(select);

        // Wstaw przed nagłówkiem tabeli
        const headerRow = quotesMain.querySelector(".quote-header-row");
        if (headerRow) {
            quotesMain.insertBefore(selectWrapper, headerRow);
        } else {
            quotesMain.prepend(selectWrapper);
        }
    }

    // Aktualizuj wybraną wartość
    const select = selectWrapper.querySelector("select");
    if (select) select.value = resultsPerPage;
}

// Funkcja do przechodzenia na konkretną stronę
function goToPage(page) {
    if (page < 1 || page > totalPages || page === currentPage) {
        return;
    }
    currentPage = page;
    filterQuotes(false);
}

// Funkcje dla overlaya ładowania
function showLoadingOverlay() {
    let overlay = document.getElementById("quotes-loading-overlay");
    if (!overlay) {
        overlay = document.createElement("div");
        overlay.id = "quotes-loading-overlay";
        overlay.className = "quotes-loading-overlay";
        overlay.innerHTML = `
            <div class="quotes-loading-spinner">
                <div class="spinner-ring"></div>
                <div class="spinner-ring"></div>
                <div class="spinner-ring"></div>
                <span class="spinner-text">Wczytywanie...</span>
            </div>
        `;
        document.querySelector("#quotes-table-body").parentElement.appendChild(overlay);
    }
    overlay.style.display = "flex";
}

function hideLoadingOverlay() {
    const overlay = document.getElementById("quotes-loading-overlay");
    if (overlay) {
        overlay.style.display = "none";
    }
}

// Mini-modal "Idź do strony"
function openGoToPageModal() {
    // Usuń poprzedni modal jeśli istnieje
    const existingModal = document.getElementById("goto-page-modal");
    if (existingModal) {
        existingModal.remove();
    }

    // Stwórz modal
    const modal = document.createElement("div");
    modal.id = "goto-page-modal";
    modal.className = "goto-page-modal";
    modal.innerHTML = `
        <div class="goto-page-content">
            <h3>Przejdź do strony</h3>
            <div class="goto-page-input-wrapper">
                <input type="number" id="goto-page-input" min="1" max="${totalPages}" value="${currentPage}" />
                <span class="goto-page-max">z ${totalPages}</span>
            </div>
            <div class="goto-page-buttons">
                <button class="goto-page-cancel">Anuluj</button>
                <button class="goto-page-confirm">Przejdź</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Focus na input
    const input = document.getElementById("goto-page-input");
    setTimeout(() => input.focus(), 50);

    // Event listeners
    modal.querySelector(".goto-page-cancel").addEventListener("click", () => {
        modal.remove();
    });

    modal.querySelector(".goto-page-confirm").addEventListener("click", () => {
        const page = parseInt(input.value);
        if (page >= 1 && page <= totalPages) {
            goToPage(page);
            modal.remove();
        } else {
            alert(`Proszę podać numer strony od 1 do ${totalPages}`);
        }
    });

    // Enter na input
    input.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            modal.querySelector(".goto-page-confirm").click();
        }
    });

    // Kliknięcie poza modalem zamyka go
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

function initClearFiltersButton() {
    const clearBtn = document.getElementById("clear-filters");
    if (!clearBtn) {
        console.warn("Przycisk #clear-filters nie znaleziony");
        return;
    }

    clearBtn.addEventListener("click", () => {
        console.log("[ClearFilters] Czyszczenie filtrów");

        // Wyczyść wszystkie pola filtrów
        ["quote-number-filter", "client-number-filter", "client-name-filter", "source-filter", "employee-filter"].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });

        document.getElementById("date-from-filter").value = "";
        document.getElementById("date-to-filter").value = "";

        // Zresetuj statusy - aktywuj "Wszystkie"
        document.querySelectorAll(".status-button").forEach(btn => btn.classList.remove("active"));
        const allButton = document.querySelector('.status-button');
        if (allButton) allButton.classList.add("active");
        activeStatus = null;

        // Odfiltruj od razu
        filterQuotes();
        updateClearFiltersButtonState();
    });

    // Event listeners dla aktualizacji stanu przycisku "Wyczyść filtry"
    ["quote-number-filter", "client-number-filter", "client-name-filter", "source-filter", "employee-filter", "date-from-filter", "date-to-filter"]
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("input", updateClearFiltersButtonState);
                el.addEventListener("change", updateClearFiltersButtonState);
            }
        });
}

function initMobileFilters() {
    const toggle = document.getElementById('mobile-filters-toggle');
    const panel = document.getElementById('quotes-status-panel');
    const overlay = document.getElementById('mobile-filters-overlay');
    const closeBtn = document.getElementById('mobile-filters-close');
    const applyBtn = document.getElementById('apply-filters');

    if (!toggle || !panel || !overlay) return;

    function openFilters() {
        panel.classList.add('open');
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeFilters() {
        panel.classList.remove('open');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    toggle.addEventListener('click', openFilters);
    overlay.addEventListener('click', closeFilters);
    if (closeBtn) closeBtn.addEventListener('click', closeFilters);

    // Zamknij po kliknięciu "Filtruj wyceny"
    if (applyBtn) {
        applyBtn.addEventListener('click', function() {
            if (window.innerWidth <= 768) closeFilters();
        });
    }
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

function parseVariantCode(code) {
    const speciesMap = { 'dab': 'Dąb', 'jes': 'Jesion', 'buk': 'Buk' };
    const techMap = { 'lity': 'Lity', 'micro': 'Mikrowczep' };
    const gradeMap = { 'ab': 'A/B', 'bb': 'B/B' };

    if (!code) return { species: '-', technology: '-', grade: '-' };
    const parts = code.split('-');
    return {
        species: speciesMap[parts[0]] || parts[0] || '-',
        technology: techMap[parts[1]] || parts[1] || '-',
        grade: gradeMap[parts[2]] || parts[2] || '-'
    };
}

function renderSelectedSummary(groupedItems, container) {
    container.innerHTML = "";
    let totalVolume = 0;
    let totalWeight = 0;

    const rows = [];

    Object.keys(groupedItems).forEach((index, idx) => {
        const selected = groupedItems[index].find(i => i.is_selected) || groupedItems[index][0];
        if (!selected) return;

        const parsed = parseVariantCode(selected.variant_code);
        const dims = `${selected.length_cm}×${selected.width_cm}×${selected.thickness_cm}`;

        // Znajdź szczegóły wykończenia dla tego produktu
        const finishing = window.currentQuoteData ?
            (window.currentQuoteData.finishing || []).find(f => f.product_index == index) : null;

        // Pobierz ilość z finishing details lub domyślnie 1
        const quantity = finishing ? (finishing.quantity || 1) : 1;

        // Oblicz ceny bazowe produktu
        const baseUnitPriceBrutto = selected.unit_price_brutto || selected.final_price_brutto || 0;
        const baseUnitPriceNetto = selected.unit_price_netto || selected.final_price_netto || 0;

        // Dodaj cenę wykończenia i krawędzi do ceny jednostkowej (jeśli istnieje)
        let finalUnitPriceBrutto = baseUnitPriceBrutto;
        let finalUnitPriceNetto = baseUnitPriceNetto;

        if (finishing) {
            const finishingQuantity = finishing.quantity || quantity || 1;
            const totalFinishingBrutto = (parseFloat(finishing.finishing_price_brutto || 0)) + (parseFloat(finishing.edges_price_brutto || 0));
            const totalFinishingNetto = (parseFloat(finishing.finishing_price_netto || 0)) + (parseFloat(finishing.edges_price_netto || 0));
            finalUnitPriceBrutto += totalFinishingBrutto / finishingQuantity;
            finalUnitPriceNetto += totalFinishingNetto / finishingQuantity;
        }

        const totalBrutto = finalUnitPriceBrutto * quantity;
        const totalNetto = finalUnitPriceNetto * quantity;

        // Oblicz objętość (m³) i wagę (kg)
        let itemVolume = 0;
        if (selected.real_volume_m3) {
            itemVolume = parseFloat(selected.real_volume_m3) * quantity;
        } else if (selected.volume_m3) {
            itemVolume = parseFloat(selected.volume_m3) * quantity;
        } else if (selected.length_cm && selected.width_cm && selected.thickness_cm) {
            itemVolume = (selected.length_cm / 100) * (selected.width_cm / 100) * (selected.thickness_cm / 100) * quantity;
        }
        const itemWeight = itemVolume * 800;
        totalVolume += itemVolume;
        totalWeight += itemWeight;

        // Przygotuj opis wykończenia
        let finishingText = 'Surowe';
        if (finishing && finishing.finishing_type && finishing.finishing_type !== 'Brak' && finishing.finishing_type !== 'Surowe') {
            const finishingParts = [];
            if (finishing.finishing_type) finishingParts.push(finishing.finishing_type);
            if (finishing.finishing_variant) finishingParts.push(finishing.finishing_variant);
            if (finishing.finishing_gloss_level) finishingParts.push(finishing.finishing_gloss_level);
            if (finishing.finishing_color) finishingParts.push(finishing.finishing_color);
            finishingText = finishingParts.filter(Boolean).join(', ') || 'Surowe';
        }

        // Kształt
        const shapeLabels = {
            'rectangular': 'Prostokąt',
            'circle': 'Koło',
            'round': 'Okrągły',
            'triangle_right': 'Trójkąt prost.',
            'triangle_equilateral': 'Trójkąt równob.',
            'triangle_isosceles': 'Trójkąt równor.',
            'triangle_custom': 'Trójkąt dowoln.',
            'trapezoid_symmetric': 'Trapez sym.',
            'trapezoid_asymmetric': 'Trapez asym.',
            'trapezoid_custom': 'Trapez dowoln.',
            'parallelogram': 'Równoległobok',
            'polygon': 'Wielokąt'
        };
        const shapeText = finishing && finishing.shape ? (shapeLabels[finishing.shape] || finishing.shape) : 'Prostokąt';

        rows.push(`
            <tr>
                <td data-label="Produkt ${parseInt(index)}">${parseInt(index)}</td>
                <td data-label="Kształt">${shapeText}</td>
                <td data-label="Gatunek">${parsed.species}</td>
                <td data-label="Technologia">${parsed.technology}</td>
                <td data-label="Klasa">${parsed.grade}</td>
                <td data-label="Wymiary">${dims}</td>
                <td data-label="Wykończenie">${finishingText}</td>
                <td data-label="Ilość">${quantity}</td>
                <td data-label="Netto" class="num">${totalNetto.toFixed(2)} zł</td>
                <td data-label="VAT" class="num vat">${(totalBrutto - totalNetto).toFixed(2)} zł</td>
                <td data-label="Brutto" class="num">${totalBrutto.toFixed(2)} zł</td>
            </tr>
        `);
    });

    const table = document.createElement("table");
    table.className = "summary-table";
    table.innerHTML = `
        <thead>
            <tr>
                <th>LP.</th>
                <th>Kształt</th>
                <th>Gatunek</th>
                <th>Technologia</th>
                <th>Klasa</th>
                <th>Wymiary</th>
                <th>Wykończenie</th>
                <th>Ilość</th>
                <th class="num">Netto</th>
                <th class="num">VAT</th>
                <th class="num">Brutto</th>
            </tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
    `;
    // Kolumna podsumowania po prawej
    const totalsCol = document.createElement("div");
    totalsCol.className = "summary-totals-col";
    totalsCol.innerHTML = `
        <table class="costs-table">
            <thead><tr><th colspan="2">Podsumowanie</th></tr></thead>
            <tbody>
                <tr><td>Objętość</td><td>${formatVolumeDisplay(totalVolume)}</td></tr>
                <tr><td>Waga</td><td>${formatWeightDisplay(totalWeight)}</td></tr>
            </tbody>
        </table>
    `;

    // Wrapper: tabela + podsumowanie obok siebie
    const tableRow = document.createElement("div");
    tableRow.className = "summary-table-row";
    tableRow.appendChild(table);
    tableRow.appendChild(totalsCol);
    container.appendChild(tableRow);

    // Ukryj wiersze > 5 i dodaj przycisk "Pokaż więcej"
    const MAX_VISIBLE = 4;
    const tbodyRows = table.querySelectorAll('tbody tr');
    if (tbodyRows.length > MAX_VISIBLE) {
        const hiddenCount = tbodyRows.length - MAX_VISIBLE;
        tbodyRows.forEach((tr, i) => {
            if (i >= MAX_VISIBLE) tr.style.display = 'none';
        });

        const showMoreBtn = document.createElement('button');
        showMoreBtn.className = 'summary-table-show-more';
        showMoreBtn.textContent = `Pokaż ${hiddenCount} więcej`;
        showMoreBtn.addEventListener('click', () => {
            tbodyRows.forEach(tr => tr.style.display = '');
            showMoreBtn.remove();
        });
        container.appendChild(showMoreBtn);
    }
}

// Updated renderVariantSummary function with quantity editing functionality
function renderVariantSummary(groupedItemsForIndex, quoteData, productIndex) {
    const item = groupedItemsForIndex.find(i => i.is_selected) || groupedItemsForIndex[0];
    if (!item) return null;

    const wrap = document.createElement('div');
    wrap.className = 'variant-summary-header';

    const dims = `${item.length_cm} × ${item.width_cm} × ${item.thickness_cm} cm`;
    const realVol = item.real_volume_m3 || item.volume_m3;
    const volume = realVol ? `${realVol.toFixed(3)} m³` : '-';

    const finishing = (quoteData.finishing || []).find(f => f.product_index == productIndex);
    
    // Pobierz quantity z finishing details lub z item
    const quantity = finishing ? finishing.quantity || 1 : (item.quantity || 1);
    
    // Wykończenie — osobne wiersze per składowa
    let finishingRowsHtml = '';
    const hasFinishing = finishing && finishing.finishing_type && finishing.finishing_type !== 'Brak' && finishing.finishing_type !== 'Surowe';
    if (hasFinishing) {
        if (finishing.finishing_type) finishingRowsHtml += '<div><span class="vsh-label">Typ:</span> ' + finishing.finishing_type + '</div>';
        if (finishing.finishing_variant) finishingRowsHtml += '<div><span class="vsh-label">Wariant:</span> ' + finishing.finishing_variant + '</div>';
        if (finishing.finishing_gloss_level) finishingRowsHtml += '<div><span class="vsh-label">Połysk:</span> ' + finishing.finishing_gloss_level + '</div>';
        if (finishing.finishing_color) finishingRowsHtml += '<div><span class="vsh-label">Kolor:</span> ' + finishing.finishing_color + '</div>';
    } else {
        finishingRowsHtml = '<div class="vsh-empty">Surowy</div>';
    }

    // Oblicz ceny z wykończeniem
    const baseUnitPriceBrutto = item.unit_price_brutto || item.final_price_brutto || 0;
    const baseUnitPriceNetto = item.unit_price_netto || item.final_price_netto || 0;
    
    let finalUnitPriceBrutto = baseUnitPriceBrutto;
    let finalUnitPriceNetto = baseUnitPriceNetto;

    // Dodaj cenę wykończenia i krawędzi do ceny jednostkowej
    if (finishing) {
        const finishingQuantity = finishing.quantity || quantity || 1;
        // Uwzględnij zarówno wykończenie jak i obróbkę krawędzi
        const totalFinishingBrutto = (parseFloat(finishing.finishing_price_brutto || 0)) + (parseFloat(finishing.edges_price_brutto || 0));
        const totalFinishingNetto = (parseFloat(finishing.finishing_price_netto || 0)) + (parseFloat(finishing.edges_price_netto || 0));
        finalUnitPriceBrutto += totalFinishingBrutto / finishingQuantity;
        finalUnitPriceNetto += totalFinishingNetto / finishingQuantity;
    }

    // Oblicz wartości całkowite
    const totalBrutto = finalUnitPriceBrutto * quantity;
    const totalNetto = finalUnitPriceNetto * quantity;


    // Dane krawędzi
    let edgesSvgHtml = '';
    const hasEdges = finishing && finishing.edges_config && finishing.edges_config.length > 0;
    if (hasEdges && finishing.edges_svg) {
        edgesSvgHtml = '<div class="edges-svg-preview">' + finishing.edges_svg + '</div>';
    }

    // Badge kształtu
    const shapeLabels = {
        'rectangular': 'Prostokąt',
        'circle': 'Koło',
        'round': 'Okrągły',
        'triangle_right': 'Trójkąt prostokątny',
        'triangle_equilateral': 'Trójkąt równoboczny',
        'triangle_isosceles': 'Trójkąt równoramienny',
        'triangle_custom': 'Trójkąt dowolny',
        'trapezoid_symmetric': 'Trapez symetryczny',
        'trapezoid_asymmetric': 'Trapez niesymetryczny',
        'trapezoid_custom': 'Trapez dowolny',
        'parallelogram': 'Równoległobok',
        'polygon': 'Wielokąt'
    };
    const shapeLabel = finishing && finishing.shape ? shapeLabels[finishing.shape] : null;
    const shapeDisplay = shapeLabel
        ? ` <span style="background:#e67e22;color:#fff;padding:1px 6px;border-radius:4px;font-size:11px;margin-left:4px;">${shapeLabel}</span>`
        : '';

    // Shape SVG preview — klikalny z tooltipem
    const shapeSvgHtml = finishing && finishing.shape_svg
        ? '<div class="shape-preview-item shape-zoomable" data-svg-title="Widok kształtu"><div class="shape-preview-label">Kształt</div><div class="shape-svg-preview">' + finishing.shape_svg + '</div></div>'
        : '';

    // Edges SVG — klikalny z tooltipem + info o obróbce pod spodem
    // Helper: grupuj edges_config po (type, r_value, angle_value) dla trybu Advanced
    function _groupEdgesConfig(cfg) {
        var TYPE_PL = { round: 'Zaokrąglenie', chamfer: 'Fazowanie' };
        var groups = new Map();
        cfg.forEach(function(e) {
            var key = (e.type || '') + '|' + e.r_value + '|' + (e.angle_value != null ? e.angle_value : '');
            if (!groups.has(key)) groups.set(key, { key: key, type: e.type, r: e.r_value, angle: e.angle_value, letters: [] });
            groups.get(key).letters.push(e.letter);
        });
        var arr = Array.from(groups.values());
        arr.sort(function(a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
        return arr.map(function(g) {
            var typeName = TYPE_PL[g.type] || g.type;
            var anglePart = (g.type === 'chamfer' && g.angle) ? ' ' + g.angle + '\u00b0' : '';
            return { text: typeName + ' R' + g.r + anglePart, letters: g.letters.slice().sort().join(', ') };
        });
    }

    var edgesCaption = '';
    if (hasEdges) {
        if (finishing.edges_mode === 'advanced') {
            var _groups = _groupEdgesConfig(finishing.edges_config);
            var _lines = _groups.map(function(g) {
                return '<div class="vsh-edges-caption-line">• ' + g.text + ' (' + g.letters + ')</div>';
            });
            edgesCaption = '<div class="vsh-edges-caption"><div class="vsh-edges-caption-title">Obróbka krawędzi (mieszana):</div>' + _lines.join('') + '</div>';
        } else {
            var _et = finishing.edges_type === 'chamfer' ? 'Fazowanie' : finishing.edges_type === 'round' ? 'Zaokrąglenie' : finishing.edges_type;
            var _desc = _et + ' R' + (finishing.edges_r_value || '-');
            if (finishing.edges_type === 'chamfer' && finishing.edges_angle_value) _desc += ' (' + finishing.edges_angle_value + '\u00b0)';
            var _letters = finishing.edges_config.map(function(e) { return e.letter; }).sort().join(', ');
            edgesCaption = '<div class="vsh-edges-caption">' + _desc + ' — ' + _letters + '</div>';
        }
    }
    const edgesSvgWithLabel = edgesSvgHtml
        ? '<div class="shape-preview-item shape-zoomable" data-svg-title="Widok izometryczny"><div class="shape-preview-label">Izometria</div>' + edgesSvgHtml + edgesCaption + '</div>'
        : '';

    // Lamella direction icon
    const lamellaHtml = finishing && finishing.lamella_direction != null
        ? '<div class="shape-preview-item" data-svg-title="Kierunek lameli"><div class="shape-preview-label">Kierunek lameli</div><div class="lamella-direction-preview">' + LamellaIcon.generateSvg(finishing.lamella_direction, 60) + '</div></div>'
        : '';

    // Kolumna podglądu (2D + 3D)
    const hasShapePreview = shapeSvgHtml || edgesSvgWithLabel || lamellaHtml;
    const previewColumnHtml = hasShapePreview
        ? '<div class="vsh-col vsh-preview">' + shapeSvgHtml + lamellaHtml + edgesSvgWithLabel + '</div>'
        : '';

    // Buduj tabelę Produkt
    let productTableHtml =
        '<table class="costs-table vsh-table">' +
            '<thead><tr><th colspan="2">Produkt</th></tr></thead>' +
            '<tbody>' +
                '<tr><td>Wariant</td><td>' + (translateVariantCode(item.variant_code) || 'Nieznany') + shapeDisplay + '</td></tr>' +
                '<tr><td>Wymiary</td><td>' + dims + '</td></tr>' +
                '<tr><td>Objętość</td><td>' + volume + '</td></tr>' +
                '<tr><td>Ilość</td><td>' + quantity + ' szt.</td></tr>' +
            '</tbody>' +
        '</table>';

    // Buduj tabelę Wykończenie
    let finishingTableRows = '';

    // Pierwszy wiersz: docięcie do wymiaru (zawsze widoczny, niezależnie od finishing).
    // "Tak" = standard (default), "Nie" = odstępstwo (klient sam dotina) — pogrubione.
    const cutToSize = (finishing && finishing.cut_to_size === false) ? false : true;
    const cutToSizeLabel = cutToSize ? 'Tak' : '<strong>Nie</strong>';
    finishingTableRows += '<tr><td>Docięcie do wymiaru</td><td>' + cutToSizeLabel + '</td></tr>';

    if (hasFinishing) {
        if (finishing.finishing_type) finishingTableRows += '<tr><td>Typ</td><td>' + finishing.finishing_type + '</td></tr>';
        if (finishing.finishing_variant) finishingTableRows += '<tr><td>Wariant</td><td>' + finishing.finishing_variant + '</td></tr>';
        if (finishing.finishing_gloss_level) finishingTableRows += '<tr><td>Połysk</td><td>' + finishing.finishing_gloss_level + '</td></tr>';
        if (finishing.finishing_color) finishingTableRows += '<tr><td>Kolor</td><td>' + finishing.finishing_color + '</td></tr>';
        if (finishing) {
            const fCostBrutto = parseFloat(finishing.finishing_price_brutto || 0);
            const fCostNetto = parseFloat(finishing.finishing_price_netto || 0);
            if (fCostBrutto > 0) {
                finishingTableRows += '<tr><td>Koszt</td><td>' + fCostBrutto.toFixed(2) + ' PLN <span class="cost-netto">' + fCostNetto.toFixed(2) + ' PLN</span></td></tr>';
            }
        }
    } else {
        finishingTableRows +=
            '<tr><td>Typ</td><td>Surowe</td></tr>' +
            '<tr><td>Wariant</td><td>Brak</td></tr>' +
            '<tr><td>Połysk</td><td>Brak</td></tr>' +
            '<tr><td>Kolor</td><td>Brak</td></tr>' +
            '<tr><td>Koszt</td><td>0.00 PLN <span class="cost-netto">0.00 PLN</span></td></tr>';
    }
    let finishingTableHtml =
        '<table class="costs-table vsh-table">' +
            '<thead><tr><th colspan="2">Wykończenie</th></tr></thead>' +
            '<tbody>' + finishingTableRows + '</tbody>' +
        '</table>';

    // Buduj tabelę Krawędzie
    let edgesTableRows = '';
    if (hasEdges) {
        const edgesPriceBrutto = parseFloat(finishing.edges_price_brutto || 0);
        const edgesPriceNetto = parseFloat(finishing.edges_price_netto || 0);

        if (finishing.edges_mode === 'advanced') {
            const _groupsTbl = _groupEdgesConfig(finishing.edges_config);
            const _rowsHtml = _groupsTbl.map(function(g) {
                return '<div>• ' + g.text + ' (' + g.letters + ')</div>';
            }).join('');
            edgesTableRows += '<tr><td>Tryb</td><td>Mieszany (zaawansowany)</td></tr>';
            edgesTableRows += '<tr><td>Grupy</td><td style="text-align:left;">' + _rowsHtml + '</td></tr>';
        } else {
            const edgesConfig = finishing.edges_config;
            const edgesType = finishing.edges_type === 'chamfer' ? 'Fazowanie' :
                             finishing.edges_type === 'round' ? 'Zaokrąglenie' : finishing.edges_type;
            const edgesRValue = finishing.edges_r_value || '-';
            const edgesAngleValue = finishing.edges_angle_value;
            const edgeLetters = edgesConfig.map(e => e.letter).sort().join(', ');

            let edgesDescription = edgesType + ' R' + edgesRValue;
            if (finishing.edges_type === 'chamfer' && edgesAngleValue) {
                edgesDescription += ' (' + edgesAngleValue + '\u00b0)';
            }

            edgesTableRows += '<tr><td>Typ</td><td>' + edgesDescription + '</td></tr>';
            edgesTableRows += '<tr><td>Krawędzie</td><td>' + edgeLetters + '</td></tr>';
        }
        edgesTableRows += '<tr><td>Koszt</td><td>' + edgesPriceBrutto.toFixed(2) + ' PLN <span class="cost-netto">' + edgesPriceNetto.toFixed(2) + ' PLN</span></td></tr>';
    }
    let edgesTableHtml = '';
    if (hasEdges) {
        edgesTableHtml =
            '<table class="costs-table vsh-table">' +
                '<thead><tr><th colspan="2">Krawędzie</th></tr></thead>' +
                '<tbody>' + edgesTableRows + '</tbody>' +
            '</table>';
    }

    wrap.innerHTML = productTableHtml + finishingTableHtml + edgesTableHtml + previewColumnHtml;

    return wrap;
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
    const editVol = item.real_volume_m3 || item.volume_m3;
    document.getElementById('edit-variant-volume').textContent = `${editVol?.toFixed(3) || '0.000'} m³`;

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

    if (!quoteData || !Array.isArray(quoteData.items)) {
        console.warn('[openTotalDiscountModal] quoteData jeszcze nie zaladowane - ignoruje klik');
        return;
    }

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

// ============================================
// FUNKCJE DO ZARZĄDZANIA NOTATKĄ
// ============================================

let originalNoteValue = '';

function initializeNoteSection(quoteData) {
    console.log('[NOTE] Inicjalizacja sekcji notatki dla wyceny:', quoteData.id);

    const textarea = document.getElementById('quote-note-textarea');
    const editBtn = document.getElementById('edit-note-btn');
    const saveBtn = document.getElementById('save-note-btn');
    const cancelBtn = document.getElementById('cancel-note-btn');
    const actionsRow = document.querySelector('.note-actions-row');
    const counter = document.getElementById('quote-note-counter');
    const warningDiv = document.getElementById('note-length-warning');

    if (!textarea || !editBtn || !saveBtn || !cancelBtn) {
        console.warn('[NOTE] Brak wymaganych elementów w DOM');
        return;
    }

    // Wypełnij textarea wartością z bazy
    const noteValue = quoteData.notes || '';
    textarea.value = noteValue;
    originalNoteValue = noteValue;

    // Sprawdź czy wycena jest już w Baselinkerze
    const isOrdered = quoteData.base_linker_order_id && quoteData.base_linker_order_id.trim() !== '';

    if (isOrdered) {
        editBtn.disabled = true;
        console.log('[NOTE] Wycena złożona w Baselinker - edycja wyłączona');
    } else {
        editBtn.disabled = false;
    }

    // Sprawdź długość notatki i pokaż ostrzeżenie jeśli > 180
    updateNoteLengthWarning(noteValue, warningDiv);

    // Event: Kliknięcie ikony ołówka - włączenie edycji
    const newEditBtn = editBtn.cloneNode(true);
    editBtn.parentNode.replaceChild(newEditBtn, editBtn);

    newEditBtn.addEventListener('click', () => {
        enableNoteEdit(textarea, newEditBtn, actionsRow, counter);
    });

    // Event: Zapisz notatkę
    const newSaveBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newSaveBtn, saveBtn);

    newSaveBtn.addEventListener('click', () => {
        saveNoteEdit(quoteData.id, textarea, newEditBtn, actionsRow, warningDiv);
    });

    // Event: Anuluj edycję
    const newCancelBtn = cancelBtn.cloneNode(true);
    cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

    newCancelBtn.addEventListener('click', () => {
        cancelNoteEdit(textarea, newEditBtn, actionsRow, warningDiv);
    });

    // Event: Licznik znaków podczas pisania
    textarea.addEventListener('input', () => {
        updateNoteCounter(textarea, counter, warningDiv);
    });

    console.log('[NOTE] Notatka zainicjalizowana:', {
        value: noteValue,
        length: noteValue.length,
        isOrdered: isOrdered
    });
}

function enableNoteEdit(textarea, editBtn, actionsRow, counter) {
    console.log('[NOTE] Włączanie trybu edycji notatki');

    textarea.disabled = false;
    textarea.focus();
    editBtn.disabled = true;
    if (actionsRow) actionsRow.style.display = 'flex';

    updateNoteCounter(textarea, counter);
}

function cancelNoteEdit(textarea, editBtn, actionsRow, warningDiv) {
    console.log('[NOTE] Anulowanie edycji notatki');

    textarea.value = originalNoteValue;
    textarea.disabled = true;
    editBtn.disabled = false;
    if (actionsRow) actionsRow.style.display = 'none';

    updateNoteLengthWarning(originalNoteValue, warningDiv);
}

async function saveNoteEdit(quoteId, textarea, editBtn, actionsRow, warningDiv) {
    console.log('[NOTE] Zapisywanie notatki dla wyceny:', quoteId);

    const newNote = textarea.value.trim();

    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}/note`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ notes: newNote })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Błąd podczas zapisywania notatki');
        }

        // Sukces - zaktualizuj wartość oryginalną i wyłącz edycję
        originalNoteValue = newNote;
        textarea.disabled = true;
        editBtn.disabled = false;
        if (actionsRow) actionsRow.style.display = 'none';

        // Zaktualizuj currentQuoteData
        if (currentQuoteData) {
            currentQuoteData.notes = newNote;
        }

        updateNoteLengthWarning(newNote, warningDiv);

        showToast('Notatka została zapisana', 'success');
        console.log('[NOTE] Notatka zapisana pomyślnie');

    } catch (error) {
        console.error('[NOTE] Błąd podczas zapisywania notatki:', error);
        showToast(error.message || 'Błąd podczas zapisywania notatki', 'error');
    }
}

function updateNoteCounter(textarea, counter, warningDiv) {
    const currentLength = textarea.value.length;
    const maxLength = 180;
    const remaining = maxLength - currentLength;

    counter.textContent = remaining;

    const counterElement = counter.parentElement;
    if (remaining <= 20) {
        counterElement.classList.add('warning');
    } else {
        counterElement.classList.remove('warning');
    }

    // Zaktualizuj ostrzeżenie o długości
    if (warningDiv) {
        updateNoteLengthWarning(textarea.value, warningDiv);
    }
}

// ===== ATTACHMENT SECTION =====

const ATTACHMENT_MAX_SIZE = 1 * 1024 * 1024; // 1 MB
const ATTACHMENT_BLOCKED_EXTENSIONS = new Set([
    'exe', 'bat', 'sh', 'php', 'py', 'js', 'cmd', 'ps1',
    'vbs', 'com', 'msi', 'scr', 'cgi', 'pl', 'rb', 'jar', 'war',
    'bash', 'zsh', 'fish', 'pif', 'application', 'gadget',
    'hta', 'inf', 'reg', 'rgs', 'sct', 'shb', 'ws', 'wsf', 'wsh'
]);

function validateAttachmentFile(file) {
    if (!file) return 'Nie wybrano pliku';
    const ext = file.name.split('.').pop().toLowerCase();
    if (ATTACHMENT_BLOCKED_EXTENSIONS.has(ext)) {
        return `Niedozwolone rozszerzenie pliku: .${ext}`;
    }
    if (file.size > ATTACHMENT_MAX_SIZE) {
        const sizeKB = Math.round(file.size / 1024);
        return `Plik jest za duży (${sizeKB} KB). Maksymalny rozmiar to 1 MB.`;
    }
    if (file.size === 0) return 'Plik jest pusty';
    return null;
}

function initializeAttachmentSection(quoteData) {
    const displaySection = document.getElementById('attachment-display');
    const uploadSection = document.getElementById('attachment-upload-section');
    const editActions = document.getElementById('attachment-edit-actions');
    const link = document.getElementById('attachment-link');
    const deleteBtn = document.getElementById('delete-attachment-btn');
    const replaceInput = document.getElementById('attachment-replace-input');
    const uploadInput = document.getElementById('attachment-upload-input');

    if (!displaySection || !uploadSection) return;

    const isOrdered = !!quoteData.base_linker_order_id;
    const hasAttachment = !!quoteData.attachment_filename;

    if (hasAttachment) {
        displaySection.style.display = 'flex';
        uploadSection.style.display = 'none';
        link.textContent = quoteData.attachment_filename;
        link.href = `/quotes/api/attachment/${quoteData.attachment_stored_name}`;
        if (isOrdered && editActions) {
            editActions.style.display = 'none';
        }
    } else {
        displaySection.style.display = 'none';
        uploadSection.style.display = isOrdered ? 'none' : 'flex';
    }

    if (uploadInput) {
        uploadInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const error = validateAttachmentFile(file);
            if (error) { showToast(error, 'error'); uploadInput.value = ''; return; }
            await uploadAttachment(quoteData.id, file);
            uploadInput.value = '';
        });
    }

    if (replaceInput) {
        replaceInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const error = validateAttachmentFile(file);
            if (error) { showToast(error, 'error'); replaceInput.value = ''; return; }
            await uploadAttachment(quoteData.id, file);
            replaceInput.value = '';
        });
    }

    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            if (!confirm('Czy na pewno chcesz usunąć załącznik?')) return;
            await deleteAttachment(quoteData.id);
        });
    }
}

async function uploadAttachment(quoteId, file) {
    try {
        const formData = new FormData();
        formData.append('attachment', file);
        const response = await fetch(`/quotes/api/quotes/${quoteId}/attachment`, {
            method: 'PATCH',
            body: formData
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Błąd podczas zapisywania załącznika');
        }
        const displaySection = document.getElementById('attachment-display');
        const uploadSection = document.getElementById('attachment-upload-section');
        const link = document.getElementById('attachment-link');
        displaySection.style.display = 'flex';
        uploadSection.style.display = 'none';
        const editActions = document.getElementById('attachment-edit-actions');
        if (editActions) editActions.style.display = 'flex';
        link.textContent = data.attachment.filename;
        link.href = `/quotes/api/attachment/${data.attachment.stored_name}`;
        if (currentQuoteData) {
            currentQuoteData.attachment_filename = data.attachment.filename;
        }
        showToast('Załącznik został zapisany', 'success');
    } catch (error) {
        console.error('[ATTACHMENT] Błąd uploadu:', error);
        showToast(error.message || 'Błąd podczas zapisywania załącznika', 'error');
    }
}

async function deleteAttachment(quoteId) {
    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}/attachment`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Błąd podczas usuwania załącznika');
        }
        const displaySection = document.getElementById('attachment-display');
        const uploadSection = document.getElementById('attachment-upload-section');
        displaySection.style.display = 'none';
        uploadSection.style.display = 'flex';
        if (currentQuoteData) {
            currentQuoteData.attachment_filename = null;
        }
        showToast('Załącznik został usunięty', 'success');
    } catch (error) {
        console.error('[ATTACHMENT] Błąd usuwania:', error);
        showToast(error.message || 'Błąd podczas usuwania załącznika', 'error');
    }
}

function updateNoteLengthWarning(noteValue, warningDiv) {
    if (!warningDiv) return;

    const noteLength = noteValue.length;

    if (noteLength > 180) {
        warningDiv.style.display = 'flex';
        console.log('[NOTE] Ostrzeżenie: notatka za długa (', noteLength, '/ 180)');
    } else {
        warningDiv.style.display = 'none';
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
        html += `${brutto.toFixed(2)} PLN`;
    }
    if (netto && brutto) {
        html += ` <span style="font-size: 12px;">• ${netto.toFixed(2)} PLN</span>`;
    } else if (netto && !brutto) {
        html += `${netto.toFixed(2)} PLN`;
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

// ============================================
// FUNKCJE DOKUMENTÓW SPRZEDAŻY BASELINKER
// ============================================

/**
 * Główna funkcja ładująca dokumenty sprzedaży
 */
async function loadSalesDocuments(quoteData) {
    console.log('[SalesDocuments] Rozpoczynam ładowanie dokumentów dla zamówienia:', quoteData.base_linker_order_id);

    if (!quoteData.base_linker_order_id) {
        console.warn('[SalesDocuments] Brak ID zamówienia Baselinker');
        return;
    }

    // NOWE: Pokaż stan ładowania dla całej sekcji
    showDocumentsLoading();

    try {
        // Wywołaj endpoint backendu
        const response = await fetch(`/baselinker/api/order/${quoteData.base_linker_order_id}/sales-documents`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        console.log('[SalesDocuments] Otrzymano dane:', data);

        // Sprawdź czy są JAKIEKOLWIEK dokumenty
        const hasAnyDocument = data.invoice?.exists || data.correction?.exists || data.receipt?.exists;

        if (!hasAnyDocument) {
            // NOWE: Pokaż komunikat "brak dokumentów"
            showNoDocumentsMessage();
        } else {
            // NOWE: Pokaż tylko te dokumenty które istnieją
            showAvailableDocuments(data, quoteData.id);
        }

        // Zawsze aktualizuj order_page
        updateOrderPageLink(data.order_page);

    } catch (error) {
        console.error('[SalesDocuments] Błąd pobierania dokumentów:', error);
        showDocumentsError(error.message);
    }
}

function setDocumentLoading(docType) {
    const link = document.getElementById(`baselinker-${docType}-link`);
    if (link) link.textContent = 'Ładowanie...';
}

function setDocumentError(docType, errorMessage) {
    const row = document.getElementById(`baselinker-${docType}-row`);
    const link = document.getElementById(`baselinker-${docType}-link`);
    if (link) { link.textContent = 'Błąd pobierania'; link.removeAttribute('href'); }
    if (row) row.title = `Błąd: ${errorMessage}`;
    console.error(`[SalesDocuments] ${docType}: błąd - ${errorMessage}`);
}

function updateInvoiceDisplay(invoiceData, quoteId) {
    const row = document.getElementById('baselinker-invoice-row');
    const link = document.getElementById('baselinker-invoice-link');
    if (!row || !link) return;
    if (!invoiceData || !invoiceData.exists) { row.style.display = 'none'; return; }
    row.style.display = '';
    link.textContent = `${invoiceData.number} ↓`;
    link.href = '#';
    const fresh = link.cloneNode(true);
    link.parentNode.replaceChild(fresh, link);
    fresh.addEventListener('click', (e) => { e.preventDefault(); downloadInvoice(quoteId); });
}

function updateCorrectionDisplay(correctionData, quoteId) {
    const row = document.getElementById('baselinker-correction-row');
    const link = document.getElementById('baselinker-correction-link');
    if (!row || !link) return;
    if (!correctionData || !correctionData.exists) { row.style.display = 'none'; return; }
    row.style.display = '';
    link.textContent = `${correctionData.number} ↓`;
    link.href = '#';
    const fresh = link.cloneNode(true);
    link.parentNode.replaceChild(fresh, link);
    fresh.addEventListener('click', (e) => { e.preventDefault(); downloadCorrection(quoteId); });
}

function updateReceiptDisplay(receiptData) {
    const row = document.getElementById('baselinker-receipt-row');
    const link = document.getElementById('baselinker-receipt-link');
    if (!row || !link) return;
    if (!receiptData || !receiptData.exists) { row.style.display = 'none'; return; }
    row.style.display = '';
    link.textContent = 'Otwórz ↗';
    link.href = receiptData.url;
}

function updateOrderPageLink(orderPageUrl) {
    const row = document.getElementById('baselinker-order-page-row');
    const link = document.getElementById('baselinker-order-page-btn');
    if (!row || !link) return;
    if (orderPageUrl) { link.href = orderPageUrl; row.style.display = ''; }
    else { row.style.display = 'none'; }
}

/**
 * Pobiera PDF faktury
 */
async function downloadInvoice(quoteId) {
    console.log('[SalesDocuments] Pobieranie faktury dla wyceny:', quoteId);

    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}/invoice/download`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // Pobierz blob PDF
        const blob = await response.blob();

        // Wyodrębnij nazwę pliku z headera Content-Disposition
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'Faktura.pdf';

        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }

        // Utwórz URL do pobierania
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();

        // Cleanup
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        console.log('[SalesDocuments] Faktura pobrana:', filename);
        showToast('Faktura została pobrana', 'success');

    } catch (error) {
        console.error('[SalesDocuments] Błąd pobierania faktury:', error);
        showToast('Błąd pobierania faktury', 'error');
    }
}

/**
 * Pobiera PDF korekty
 */
async function downloadCorrection(quoteId) {
    console.log('[SalesDocuments] Pobieranie korekty dla wyceny:', quoteId);

    try {
        const response = await fetch(`/quotes/api/quotes/${quoteId}/correction/download`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // Pobierz blob PDF
        const blob = await response.blob();

        // Wyodrębnij nazwę pliku z headera Content-Disposition
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'Korekta.pdf';

        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }

        // Utwórz URL do pobierania
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();

        // Cleanup
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        console.log('[SalesDocuments] Korekta pobrana:', filename);
        showToast('Korekta została pobrana', 'success');

    } catch (error) {
        console.error('[SalesDocuments] Błąd pobierania korekty:', error);
        showToast('Błąd pobierania korekty', 'error');
    }
}

/**
* Pokazuje stan ładowania dla dokumentów
*/
function showDocumentsLoading() {
    console.log('[SalesDocuments] Pokazuję stan ładowania');

    // Ukryj wszystkie przyciski dokumentów
    const invoiceBtn = document.getElementById('baselinker-invoice-btn');
    const correctionBtn = document.getElementById('baselinker-correction-btn');
    const receiptBtn = document.getElementById('baselinker-receipt-btn');

    if (invoiceBtn) invoiceBtn.style.display = 'none';
    if (correctionBtn) correctionBtn.style.display = 'none';
    if (receiptBtn) receiptBtn.style.display = 'none';

    // Pokaż komunikat ładowania
    showDocumentsMessage('Ładowanie dokumentów...', 'loading');
}

/**
 * Pokazuje komunikat "brak dokumentów"
 */
function showNoDocumentsMessage() {
    console.log('[SalesDocuments] Pokazuję komunikat: brak dokumentów');
    showDocumentsMessage('Brak wystawionych dokumentów sprzedaży', 'info');
}

/**
 * Pokazuje komunikat o błędzie
 */
function showDocumentsError(errorMessage) {
    console.error('[SalesDocuments] Pokazuję błąd:', errorMessage);
    showDocumentsMessage('Błąd pobierania lub brak zamówienia w Base.', 'error');
}

/**
 * Wyświetla komunikat w sekcji dokumentów
 */
function showDocumentsMessage(message, type = 'info') {
    // Usuń istniejący komunikat jeśli jest
    const existingMessage = document.querySelector('.documents-message');
    if (existingMessage) {
        existingMessage.remove();
    }

    // Znajdź sekcję dokumentów (container dla przycisków)
    const invoiceBtn = document.getElementById('baselinker-invoice-btn');
    if (!invoiceBtn || !invoiceBtn.parentElement) {
        console.warn('[SalesDocuments] Nie znaleziono kontenera dokumentów');
        return;
    }

    const container = invoiceBtn.parentElement;

    // Utwórz komunikat
    const messageDiv = document.createElement('div');
    messageDiv.className = `documents-message documents-message-${type}`;
    messageDiv.innerHTML = `
        <div class="documents-message-content">
            ${type === 'loading' ? '<div class="documents-spinner"></div>' : ''}
            <span class="documents-message-text">${message}</span>
        </div>
    `;

    // Dodaj na początku kontenera
    container.insertBefore(messageDiv, container.firstChild);
}

/**
 * Pokazuje tylko dostępne dokumenty
 */
function showAvailableDocuments(data, quoteId) {
    console.log('[SalesDocuments] Pokazuję dostępne dokumenty');

    // Usuń komunikat ładowania/błędu jeśli istnieje
    const existingMessage = document.querySelector('.documents-message');
    if (existingMessage) {
        existingMessage.remove();
    }

    // Aktualizuj wyświetlanie dla każdego dokumentu
    updateInvoiceDisplay(data.invoice, quoteId);
    updateCorrectionDisplay(data.correction, quoteId);
    updateReceiptDisplay(data.receipt);

    console.log('[SalesDocuments] Dokumenty wyświetlone:', {
        invoice: data.invoice?.exists,
        correction: data.correction?.exists,
        receipt: data.receipt?.exists
    });
}

/**
 * Przekierowanie do kalkulatora w trybie edycji wyceny.
 * Zastępuje stary openQuoteEditorWithFreshData() - edycja odbywa się teraz w kalkulatorze.
 */
function editQuoteInCalculator() {
    if (!currentQuoteData) {
        console.error('[editQuoteInCalculator] Brak currentQuoteData');
        if (typeof showToast === 'function') {
            showToast('Błąd: Brak danych wyceny', 'error');
        }
        return;
    }

    const editUuid = currentQuoteData.edit_uuid;
    if (!editUuid) {
        console.error('[editQuoteInCalculator] Brak edit_uuid w danych wyceny');
        if (typeof showToast === 'function') {
            showToast('Błąd: Wycena nie ma identyfikatora edycji', 'error');
        }
        return;
    }

    console.log(`[editQuoteInCalculator] Przekierowanie do kalkulatora: edit_uuid=${editUuid}`);
    window.location.href = `/calculator?edit_quote=${editUuid}`;
}

// ============================================
// PODGLĄD SVG — TOOLTIP (hover) + MODAL (click)
// ============================================

(function() {
    // Tooltip — powiększony podgląd przy najechaniu
    var tooltip = document.createElement('div');
    tooltip.className = 'svg-zoom-tooltip';
    tooltip.style.display = 'none';
    document.body.appendChild(tooltip);

    var activeZoomable = null;

    document.addEventListener('mouseover', function(e) {
        var item = e.target.closest('.shape-zoomable');
        if (item === activeZoomable) return;

        if (item) {
            activeZoomable = item;
            var svg = item.querySelector('svg');
            if (!svg) return;
            tooltip.innerHTML = svg.outerHTML;
            tooltip.style.display = 'block';
            _positionTooltip(e, tooltip);
        } else if (activeZoomable) {
            activeZoomable = null;
            tooltip.style.display = 'none';
        }
    });

    document.addEventListener('mousemove', function(e) {
        if (!activeZoomable) return;
        // Sprawdź czy nadal jesteśmy nad elementem
        var item = e.target.closest('.shape-zoomable');
        if (item !== activeZoomable) {
            activeZoomable = null;
            tooltip.style.display = 'none';
            return;
        }
        _positionTooltip(e, tooltip);
    });

    function _positionTooltip(e, tip) {
        var x = e.clientX + 16;
        var y = e.clientY - tip.offsetHeight / 2;
        // Nie wychodź poza ekran
        if (x + tip.offsetWidth > window.innerWidth - 10) x = e.clientX - tip.offsetWidth - 16;
        if (y < 10) y = 10;
        if (y + tip.offsetHeight > window.innerHeight - 10) y = window.innerHeight - tip.offsetHeight - 10;
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
    }

    // Modal — duży podgląd po kliknięciu
    document.addEventListener('click', function(e) {
        var item = e.target.closest('.shape-zoomable');
        if (!item) return;
        var svg = item.querySelector('svg');
        if (!svg) return;
        tooltip.style.display = 'none';

        var title = item.getAttribute('data-svg-title') || 'Podgląd';

        // Stwórz modal
        var overlay = document.createElement('div');
        overlay.className = 'svg-zoom-modal-overlay';
        overlay.innerHTML =
            '<div class="svg-zoom-modal">' +
                '<div class="svg-zoom-modal-header">' +
                    '<span class="svg-zoom-modal-title">' + title + '</span>' +
                    '<button class="svg-zoom-modal-close">&times;</button>' +
                '</div>' +
                '<div class="svg-zoom-modal-body">' + svg.outerHTML + '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        // Zamykanie
        overlay.querySelector('.svg-zoom-modal-close').addEventListener('click', function() {
            overlay.remove();
        });
        overlay.addEventListener('click', function(ev) {
            if (ev.target === overlay) overlay.remove();
        });
    });
})();