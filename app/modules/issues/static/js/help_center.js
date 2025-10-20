// app/modules/issues/static/js/help_center.js
/**
 * Logika dla widoku Help Center - NOWA WERSJA
 * Multi-step form: Kategoria → Podkategoria → Formularz
 * 
 * Autor: Konrad Kmiecik
 * Data: 2025-01-20
 */

// ============================================================================
// NAMESPACE
// ============================================================================

const IssuesHelpCenter = {
    // Stan
    state: {
        uploadedFiles: [],
        currentTickets: [],
        currentFilter: '',
        selectedCategory: '',
        selectedSubcategory: '',
        currentStep: 1,
        categories: [], // ← Pobrane z API
        subcategories: {} // ← Wygenerowane z categories
    },

    // Elementy DOM
    elements: {}
};

// ============================================================================
// INICJALIZACJA
// ============================================================================

IssuesHelpCenter.init = async function () {
    console.log('🚀 Inicjalizacja Help Center (nowa wersja)...');

    // Pobierz elementy DOM
    IssuesHelpCenter.elements = {
        // Przycisk toggle
        toggleFormBtn: document.getElementById('issuesToggleFormBtn'),
        closeFormBtn: document.getElementById('issuesCloseFormBtn'),

        // Kontener formularza
        formContainer: document.getElementById('issuesFormContainer'),

        // Kroki
        step1: document.getElementById('issuesStep1'),
        step2: document.getElementById('issuesStep2'),
        step3: document.getElementById('issuesStep3'),

        // Kategorie i podkategorie
        categoryCards: document.querySelectorAll('.issues-category-card'),
        subcategoryGrid: document.getElementById('issuesSubcategoryGrid'),

        // Breadcrumbs i nawigacja
        backToStep1: document.getElementById('issuesBackToStep1'),
        backToStep2: document.getElementById('issuesBackToStep2'),
        breadcrumbStep2: document.getElementById('issuesBreadcrumbStep2'),
        breadcrumbStep3: document.getElementById('issuesBreadcrumbStep3'),

        // Formularz
        form: document.getElementById('issuesNewTicketForm'),
        selectedCategory: document.getElementById('issuesSelectedCategory'),
        selectedSubcategory: document.getElementById('issuesSelectedSubcategory'),

        // Upload
        uploadArea: document.getElementById('issuesUploadArea'),
        fileInput: document.getElementById('issuesFileInput'),
        filesList: document.getElementById('issuesFilesList'),

        // Tabela ticketów
        ticketsList: document.getElementById('issuesTicketsList'),
        filterStatus: document.getElementById('issuesFilterStatus'),
        refreshTickets: document.getElementById('issuesRefreshTickets')
    };

    // Najpierw pobierz kategorie z API
    await IssuesHelpCenter.loadCategories();

    // Potem inicjalizuj komponenty
    IssuesHelpCenter.initToggleForm();
    IssuesHelpCenter.initNavigation();
    IssuesHelpCenter.initForm();
    IssuesHelpCenter.initUpload();
    IssuesHelpCenter.loadTickets();
    IssuesHelpCenter.initFilters();

    console.log('✅ Help Center zainicjalizowany');
};
// ============================================================================
// TOGGLE FORMULARZA
// ============================================================================

IssuesHelpCenter.initToggleForm = function () {
    const toggleBtn = IssuesHelpCenter.elements.toggleFormBtn;
    const closeBtn = IssuesHelpCenter.elements.closeFormBtn;

    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            IssuesHelpCenter.openForm();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            IssuesHelpCenter.closeForm();
        });
    }
};

IssuesHelpCenter.loadCategories = async function () {
    try {
        console.log('📥 Pobieranie kategorii z API...');

        const response = await fetch('/issues/api/categories');
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Błąd pobierania kategorii');
        }

        IssuesHelpCenter.state.categories = data.categories;

        // Wygeneruj słownik podkategorii dla łatwiejszego dostępu
        IssuesHelpCenter.state.subcategories = {};
        data.categories.forEach(cat => {
            IssuesHelpCenter.state.subcategories[cat.key] = cat.subcategories.map(sub => sub.name);
        });

        console.log('✅ Kategorie załadowane:', IssuesHelpCenter.state.categories);

        IssuesHelpCenter.renderCategories();

    } catch (error) {
        console.error('❌ Błąd ładowania kategorii:', error);
        IssuesCommon.showToast('error', 'Błąd', 'Nie udało się załadować kategorii');
    }
};

// ============================================================================
// RENDEROWANIE KATEGORII
// ============================================================================

IssuesHelpCenter.renderCategories = function () {
    console.log('🎨 Renderowanie kategorii...');

    const grid = document.getElementById('issuesCategoryGrid');
    console.log('📋 Grid element:', grid);

    if (!grid) {
        console.error('❌ Nie znaleziono elementu issuesCategoryGrid');
        return;
    }

    const categories = IssuesHelpCenter.state.categories;
    console.log('📁 Liczba kategorii:', categories.length);

    if (categories.length === 0) {
        grid.innerHTML = '<p class="issues-ticket-empty">Brak kategorii</p>';
        return;
    }

    grid.innerHTML = categories.map(cat => `
        <div class="issues-category-card" data-category="${cat.key}">
            <div class="issues-category-icon">${cat.icon}</div>
            <h3 class="issues-category-name">${cat.name}</h3>
            <p class="issues-category-desc">${cat.description || ''}</p>
        </div>
    `).join('');

    console.log('✅ HTML kategorii wygenerowany');

    // Dodaj event listenery
    const cards = grid.querySelectorAll('.issues-category-card');
    console.log('🎯 Znaleziono kart do podpięcia:', cards.length);

    cards.forEach((card, index) => {
        console.log(`➕ Dodaję listener dla karty ${index + 1}:`, card.dataset.category);
        card.addEventListener('click', () => {
            const category = card.dataset.category;
            console.log('🖱️ KLIKNIĘTO kategorię:', category);
            IssuesHelpCenter.selectCategory(category);
        });
    });

    console.log('✅ Event listenery dodane do wszystkich kart');
};

IssuesHelpCenter.openForm = function () {
    const container = IssuesHelpCenter.elements.formContainer;
    if (container) {
        container.style.display = 'block';

        // Dodaj klasę z lekkim opóźnieniem dla płynnej animacji
        setTimeout(() => {
            container.classList.add('issues-form-open');
        }, 10);

        // Reset do kroku 1
        IssuesHelpCenter.goToStep(1);
    }
};

IssuesHelpCenter.closeForm = function () {
    const container = IssuesHelpCenter.elements.formContainer;
    if (container) {
        // Usuń klasę - animacja zamknięcia
        container.classList.remove('issues-form-open');

        // Ukryj po zakończeniu animacji
        setTimeout(() => {
            container.style.display = 'none';
            // Reset stanu
            IssuesHelpCenter.resetForm();
        }, 500);  // 500ms = czas trwania animacji CSS
    }
};

// ============================================================================
// KROK 1: Wybór kategorii
// ============================================================================

IssuesHelpCenter.initCategorySelection = function () {
    const cards = IssuesHelpCenter.elements.categoryCards;

    cards.forEach(card => {
        card.addEventListener('click', () => {
            const category = card.dataset.category;
            IssuesHelpCenter.selectCategory(category);
        });
    });
};

IssuesHelpCenter.selectCategory = function (category) {
    console.log('📁 Wybrano kategorię:', category);

    IssuesHelpCenter.state.selectedCategory = category;

    // Znajdź kategorię w danych z API
    const categoryData = IssuesHelpCenter.state.categories.find(cat => cat.key === category);

    // Aktualizuj breadcrumb
    const breadcrumb = IssuesHelpCenter.elements.breadcrumbStep2;
    if (breadcrumb && categoryData) {
        breadcrumb.textContent = categoryData.name;
    }

    // Wygeneruj podkategorie
    IssuesHelpCenter.renderSubcategories(category);

    // Przejdź do kroku 2
    IssuesHelpCenter.goToStep(2);
};

// ============================================================================
// KROK 2: Wybór podkategorii
// ============================================================================

IssuesHelpCenter.renderSubcategories = function (category) {
    const grid = IssuesHelpCenter.elements.subcategoryGrid;
    if (!grid) return;

    const subcategories = IssuesHelpCenter.state.subcategories[category] || [];

    if (subcategories.length === 0) {
        grid.innerHTML = '<p class="issues-ticket-empty">Brak podkategorii</p>';
        return;
    }

    grid.innerHTML = subcategories.map(subcat => `
        <div class="issues-subcategory-card" data-subcategory="${subcat}">
            ${subcat}
        </div>
    `).join('');

    // Dodaj event listenery
    grid.querySelectorAll('.issues-subcategory-card').forEach(card => {
        card.addEventListener('click', () => {
            const subcategory = card.dataset.subcategory;
            IssuesHelpCenter.selectSubcategory(subcategory);
        });
    });
};

IssuesHelpCenter.selectSubcategory = function (subcategory) {
    console.log('📂 Wybrano podkategorię:', subcategory);

    IssuesHelpCenter.state.selectedSubcategory = subcategory;

    // Znajdź kategorię w danych z API
    const categoryData = IssuesHelpCenter.state.categories.find(
        cat => cat.key === IssuesHelpCenter.state.selectedCategory
    );

    // Aktualizuj breadcrumb
    const breadcrumb = IssuesHelpCenter.elements.breadcrumbStep3;
    if (breadcrumb && categoryData) {
        breadcrumb.textContent = `${categoryData.name} > ${subcategory}`;
    }

    // Ustaw ukryte pola w formularzu
    if (IssuesHelpCenter.elements.selectedCategory) {
        IssuesHelpCenter.elements.selectedCategory.value = IssuesHelpCenter.state.selectedCategory;
    }
    if (IssuesHelpCenter.elements.selectedSubcategory) {
        IssuesHelpCenter.elements.selectedSubcategory.value = subcategory;
    }

    // Przejdź do kroku 3
    IssuesHelpCenter.goToStep(3);
};

// ============================================================================
// NAWIGACJA MIĘDZY KROKAMI
// ============================================================================

IssuesHelpCenter.initNavigation = function () {
    const backToStep1 = IssuesHelpCenter.elements.backToStep1;
    const backToStep2 = IssuesHelpCenter.elements.backToStep2;

    if (backToStep1) {
        backToStep1.addEventListener('click', () => {
            IssuesHelpCenter.goToStep(1);
        });
    }

    if (backToStep2) {
        backToStep2.addEventListener('click', () => {
            IssuesHelpCenter.goToStep(2);
        });
    }
};

IssuesHelpCenter.goToStep = function (step) {
    console.log('🔄 Przejście do kroku:', step);

    IssuesHelpCenter.state.currentStep = step;

    // Ukryj wszystkie kroki
    const steps = [
        IssuesHelpCenter.elements.step1,
        IssuesHelpCenter.elements.step2,
        IssuesHelpCenter.elements.step3
    ];

    steps.forEach(s => {
        if (s) {
            s.style.display = 'none';
            s.classList.remove('issues-form-step-active');
        }
    });

    // Pokaż aktywny krok
    const activeStep = steps[step - 1];
    if (activeStep) {
        activeStep.style.display = 'block';
        activeStep.classList.add('issues-form-step-active');
    }
};

// ============================================================================
// FORMULARZ
// ============================================================================

IssuesHelpCenter.initForm = function () {
    const form = IssuesHelpCenter.elements.form;
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await IssuesHelpCenter.handleSubmit();
    });
};

IssuesHelpCenter.handleSubmit = async function () {
    const form = IssuesHelpCenter.elements.form;
    const submitBtn = form.querySelector('button[type="submit"]');

    try {
        // Disable przycisku
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Wysyłanie...';

        // Pobierz dane z formularza
        const formData = new FormData(form);
        const ticketData = {
            category: formData.get('category'),
            subcategory: formData.get('subcategory'),
            priority: formData.get('priority'),
            title: formData.get('title'),
            message: formData.get('message'),
            attachment_ids: IssuesHelpCenter.state.uploadedFiles.map(f => f.id)
        };

        console.log('📤 Wysyłanie ticketu:', ticketData);

        // Walidacja
        if (!ticketData.category) {
            throw new Error('Wybierz kategorię');
        }
        if (!ticketData.title || ticketData.title.length < 5) {
            throw new Error('Temat musi mieć min. 5 znaków');
        }
        if (!ticketData.message || ticketData.message.length < 10) {
            throw new Error('Opis musi mieć min. 10 znaków');
        }

        // Wyślij ticket
        const response = await IssuesCommon.createTicket(ticketData);

        // Sukces
        IssuesCommon.showToast(
            'success',
            'Zgłoszenie wysłane!',
            `Ticket #${response.ticket.ticket_number} został utworzony`
        );

        // Zamknij formularz
        IssuesHelpCenter.closeForm();

        // Odśwież listę ticketów
        await IssuesHelpCenter.loadTickets();

        // Przewiń do tabeli
        setTimeout(() => {
            document.querySelector('.issues-tickets-section').scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }, 500);

    } catch (error) {
        console.error('Error submitting ticket:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    } finally {
        // Przywróć przycisk
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Wyślij zgłoszenie';
    }
};

IssuesHelpCenter.resetForm = function () {
    // Reset stanu
    IssuesHelpCenter.state.selectedCategory = '';
    IssuesHelpCenter.state.selectedSubcategory = '';
    IssuesHelpCenter.state.currentStep = 1;

    // Reset formularza
    const form = IssuesHelpCenter.elements.form;
    if (form) form.reset();

    // Wyczyść pliki
    IssuesHelpCenter.clearFiles();
};

// ============================================================================
// UPLOAD PLIKÓW
// ============================================================================

IssuesHelpCenter.initUpload = function () {
    const uploadArea = IssuesHelpCenter.elements.uploadArea;
    const fileInput = IssuesHelpCenter.elements.fileInput;

    if (!uploadArea || !fileInput) return;

    // Kliknięcie w upload area
    uploadArea.addEventListener('click', (e) => {
        if (e.target !== fileInput) {
            fileInput.click();
        }
    });

    // Wybór plików
    fileInput.addEventListener('change', () => {
        IssuesHelpCenter.handleFileSelect(fileInput.files);
    });

    // Drag & Drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('issues-drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('issues-drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('issues-drag-over');
        IssuesHelpCenter.handleFileSelect(e.dataTransfer.files);
    });
};

IssuesHelpCenter.handleFileSelect = async function (files) {
    const fileArray = Array.from(files);

    // Sprawdź limit
    if (IssuesHelpCenter.state.uploadedFiles.length + fileArray.length > IssuesCommon.config.maxFiles) {
        IssuesCommon.showToast('error', 'Za dużo plików', `Możesz dodać maksymalnie ${IssuesCommon.config.maxFiles} plików`);
        return;
    }

    // Upload każdego pliku
    for (const file of fileArray) {
        try {
            // Walidacja
            IssuesCommon.validateFile(file);

            // Upload
            const response = await IssuesCommon.uploadAttachment(file);

            // Dodaj do stanu
            IssuesHelpCenter.state.uploadedFiles.push({
                id: response.attachment_id,
                filename: file.name,
                size: file.size
            });

            // Odśwież UI
            IssuesHelpCenter.renderFilesList();

        } catch (error) {
            console.error('Upload error:', error);
            IssuesCommon.showToast('error', 'Błąd uploadu', error.message);
        }
    }

    // Wyczyść input
    IssuesHelpCenter.elements.fileInput.value = '';
};

IssuesHelpCenter.renderFilesList = function () {
    const filesList = IssuesHelpCenter.elements.filesList;
    if (!filesList) return;

    if (IssuesHelpCenter.state.uploadedFiles.length === 0) {
        filesList.innerHTML = '';
        return;
    }

    filesList.innerHTML = IssuesHelpCenter.state.uploadedFiles.map((file, index) => `
        <div class="issues-file-item" data-index="${index}">
            <div class="issues-file-info">
                <i class="fas fa-file issues-file-icon"></i>
                <div class="issues-file-details">
                    <p class="issues-file-name">${IssuesCommon.escapeHtml(file.filename)}</p>
                    <p class="issues-file-size">${IssuesCommon.formatFileSize(file.size)}</p>
                </div>
            </div>
            <button type="button" class="issues-file-remove" data-index="${index}">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');

    // Obsługa usuwania
    filesList.querySelectorAll('.issues-file-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            const index = parseInt(btn.dataset.index);
            IssuesHelpCenter.removeFile(index);
        });
    });
};

IssuesHelpCenter.removeFile = function (index) {
    IssuesHelpCenter.state.uploadedFiles.splice(index, 1);
    IssuesHelpCenter.renderFilesList();
};

IssuesHelpCenter.clearFiles = function () {
    IssuesHelpCenter.state.uploadedFiles = [];
    IssuesHelpCenter.renderFilesList();
};

// ============================================================================
// TABELA TICKETÓW
// ============================================================================

IssuesHelpCenter.loadTickets = async function () {
    const ticketsList = IssuesHelpCenter.elements.ticketsList;
    if (!ticketsList) return;

    try {
        // Loading state
        ticketsList.innerHTML = `
            <div class="issues-loading">
                <i class="fas fa-spinner fa-spin"></i> Ładowanie zgłoszeń...
            </div>
        `;

        // Pobierz tickety
        const filters = {};
        if (IssuesHelpCenter.state.currentFilter) {
            filters.status = IssuesHelpCenter.state.currentFilter;
        }

        const response = await IssuesCommon.getTickets(filters);
        IssuesHelpCenter.state.currentTickets = response.tickets;

        // Renderuj tickety
        IssuesHelpCenter.renderTickets();

    } catch (error) {
        console.error('Error loading tickets:', error);
        ticketsList.innerHTML = `
            <div class="issues-ticket-empty">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Wystąpił błąd podczas ładowania zgłoszeń</p>
            </div>
        `;
    }
};

IssuesHelpCenter.renderTickets = function () {
    const ticketsList = IssuesHelpCenter.elements.ticketsList;
    if (!ticketsList) return;

    const tickets = IssuesHelpCenter.state.currentTickets;

    if (tickets.length === 0) {
        ticketsList.innerHTML = `
            <div class="issues-ticket-empty">
                <i class="fas fa-inbox"></i>
                <p>Nie masz jeszcze żadnych zgłoszeń</p>
            </div>
        `;
        return;
    }

    ticketsList.innerHTML = `
        <table class="issues-tickets-table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Priorytet</th>
                    <th>Kategoria</th>
                    <th>Temat</th>
                    <th>Status</th>
                    <th>Data utworzenia</th>
                    <th>Statystyki</th>
                </tr>
            </thead>
            <tbody>
                ${tickets.map(ticket => `
                    <tr onclick="location.href='/issues/ticket/${ticket.ticket_number}'">
                        <td>
                            <a href="/issues/ticket/${ticket.ticket_number}" class="issues-ticket-number-link">
                                #${ticket.ticket_number}
                            </a>
                        </td>
                        <td>
                            <span class="issues-badge issues-badge-priority-${ticket.priority}">
                                ${IssuesCommon.getPriorityName(ticket.priority)}
                            </span>
                        </td>
                        <td class="issues-ticket-category-cell">${ticket.category}</td>
                        <td class="issues-ticket-title-cell">${IssuesCommon.escapeHtml(ticket.title)}</td>
                        <td>
                            <span class="issues-badge issues-badge-status-${ticket.status}">
                                ${IssuesCommon.getStatusName(ticket.status)}
                            </span>
                        </td>
                        <td class="issues-ticket-date-cell">${IssuesCommon.formatDate(ticket.created_at)}</td>
                        <td class="issues-ticket-stats-cell">
                            <span class="issues-ticket-stat">
                                <i class="fas fa-comments"></i> ${ticket.messages_count || 0}
                            </span>
                            <span class="issues-ticket-stat">
                                <i class="fas fa-paperclip"></i> ${ticket.attachments_count || 0}
                            </span>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
};

// ============================================================================
// FILTRY
// ============================================================================

IssuesHelpCenter.initFilters = function () {
    const filterStatus = IssuesHelpCenter.elements.filterStatus;
    const refreshBtn = IssuesHelpCenter.elements.refreshTickets;

    if (filterStatus) {
        filterStatus.addEventListener('change', () => {
            IssuesHelpCenter.state.currentFilter = filterStatus.value;
            IssuesHelpCenter.loadTickets();
        });
    }

    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            IssuesHelpCenter.loadTickets();
        });
    }
};

// ============================================================================
// URUCHOMIENIE PO ZAŁADOWANIU DOM
// ============================================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', IssuesHelpCenter.init);
} else {
    IssuesHelpCenter.init();
}