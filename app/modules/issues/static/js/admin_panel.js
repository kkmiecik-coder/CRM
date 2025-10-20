// app/modules/issues/static/js/admin_panel.js
/**
 * Logika dla panelu administratora
 * Zawiera: Statystyki, tabs, tabele ticketów, paginacja, filtry, quick actions
 * 
 * Autor: Konrad Kmiecik
 * Data: 2025-01-20
 */

// ============================================================================
// NAMESPACE
// ============================================================================

const IssuesAdminPanel = {
    // Stan
    state: {
        activeTickets: [],
        closedTickets: [],
        currentTab: 'active',
        stats: {},
        filters: {
            active: {
                priority: '',
                limit: 20,
                offset: 0
            },
            closed: {
                limit: 20,
                offset: 0
            }
        },
        pagination: {
            active: {
                currentPage: 1,
                totalPages: 1,
                total: 0
            },
            closed: {
                currentPage: 1,
                totalPages: 1,
                total: 0
            }
        }
    },

    // Elementy DOM
    elements: {}
};

// ============================================================================
// INICJALIZACJA
// ============================================================================

IssuesAdminPanel.init = function () {
    console.log('🚀 Inicjalizacja Admin Panel...');

    // Pobierz elementy DOM
    IssuesAdminPanel.elements = {
        // Statystyki
        statNew: document.getElementById('issuesStatNew'),
        statOpen: document.getElementById('issuesStatOpen'),
        statInProgress: document.getElementById('issuesStatInProgress'),
        statClosedToday: document.getElementById('issuesStatClosedToday'),
        statTotalActive: document.getElementById('issuesStatTotalActive'),

        // Tabs
        tabs: document.querySelectorAll('.issues-tab'),
        tabContents: document.querySelectorAll('.issues-tab-content'),

        // Tabele
        activeTableBody: document.getElementById('issuesActiveTableBody'),
        closedTableBody: document.getElementById('issuesClosedTableBody'),

        // Filtry
        filterPriorityActive: document.getElementById('issuesFilterPriorityActive'),
        refreshActive: document.getElementById('issuesRefreshActive'),
        refreshClosed: document.getElementById('issuesRefreshClosed'),

        // Paginacja
        activePagination: document.getElementById('issuesActivePagination'),
        closedPagination: document.getElementById('issuesClosedPagination')
    };

    // Inicjalizuj komponenty
    IssuesAdminPanel.loadStats();
    IssuesAdminPanel.initTabs();
    IssuesAdminPanel.loadActiveTickets();
    IssuesAdminPanel.initFilters();
    IssuesAdminPanel.initRefreshButtons();

    console.log('✅ Admin Panel zainicjalizowany');
};

// ============================================================================
// STATYSTYKI
// ============================================================================

IssuesAdminPanel.loadStats = async function () {
    try {
        const response = await IssuesCommon.getStats();
        IssuesAdminPanel.state.stats = response.stats;
        IssuesAdminPanel.renderStats();
    } catch (error) {
        console.error('Error loading stats:', error);
    }
};

IssuesAdminPanel.renderStats = function () {
    const stats = IssuesAdminPanel.state.stats;
    const elements = IssuesAdminPanel.elements;

    if (elements.statNew) elements.statNew.textContent = stats.new || 0;
    if (elements.statOpen) elements.statOpen.textContent = stats.open || 0;
    if (elements.statInProgress) elements.statInProgress.textContent = stats.in_progress || 0;
    if (elements.statClosedToday) elements.statClosedToday.textContent = stats.closed_today || 0;
    if (elements.statTotalActive) elements.statTotalActive.textContent = stats.total_active || 0;
};

// ============================================================================
// TABS
// ============================================================================

IssuesAdminPanel.initTabs = function () {
    const tabs = IssuesAdminPanel.elements.tabs;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            IssuesAdminPanel.switchTab(tabName);
        });
    });
};

IssuesAdminPanel.switchTab = function (tabName) {
    const tabs = IssuesAdminPanel.elements.tabs;
    const contents = IssuesAdminPanel.elements.tabContents;

    // Usuń active z wszystkich
    tabs.forEach(t => t.classList.remove('issues-tab-active'));
    contents.forEach(c => {
        c.classList.remove('issues-tab-content-active');
        c.style.display = 'none';
    });

    // Dodaj active do wybranego
    const activeTab = document.querySelector(`[data-tab="${tabName}"]`);
    const activeContent = document.getElementById(`issuesTab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);

    if (activeTab) activeTab.classList.add('issues-tab-active');
    if (activeContent) {
        activeContent.classList.add('issues-tab-content-active');
        activeContent.style.display = 'block';
    }

    // Ustaw stan
    IssuesAdminPanel.state.currentTab = tabName;

    // Załaduj dane jeśli potrzeba
    if (tabName === 'closed' && IssuesAdminPanel.state.closedTickets.length === 0) {
        IssuesAdminPanel.loadClosedTickets();
    }
};

// ============================================================================
// AKTYWNE TICKETY
// ============================================================================

IssuesAdminPanel.loadActiveTickets = async function () {
    const tableBody = IssuesAdminPanel.elements.activeTableBody;
    if (!tableBody) return;

    try {
        // Loading state
        tableBody.innerHTML = `
            <tr>
                <td colspan="8" class="issues-table-loading">
                    <i class="fas fa-spinner fa-spin"></i> Ładowanie ticketów...
                </td>
            </tr>
        `;

        // Pobierz tickety
        const filters = IssuesAdminPanel.state.filters.active;
        const response = await IssuesCommon.getActiveTickets(filters);

        IssuesAdminPanel.state.activeTickets = response.tickets;
        IssuesAdminPanel.state.pagination.active = {
            currentPage: Math.floor(filters.offset / filters.limit) + 1,
            totalPages: Math.ceil(response.total / filters.limit),
            total: response.total
        };

        // Renderuj tickety
        IssuesAdminPanel.renderActiveTickets();
        IssuesAdminPanel.renderPagination('active');

    } catch (error) {
        console.error('Error loading active tickets:', error);
        tableBody.innerHTML = `
            <tr>
                <td colspan="8" class="issues-table-empty">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Wystąpił błąd podczas ładowania ticketów</p>
                </td>
            </tr>
        `;
    }
};

IssuesAdminPanel.renderActiveTickets = function () {
    const tableBody = IssuesAdminPanel.elements.activeTableBody;
    if (!tableBody) return;

    const tickets = IssuesAdminPanel.state.activeTickets;

    if (tickets.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="8" class="issues-table-empty">
                    <i class="fas fa-inbox"></i>
                    <p>Brak aktywnych ticketów</p>
                </td>
            </tr>
        `;
        return;
    }

    tableBody.innerHTML = tickets.map(ticket => `
        <tr>
            <td>
                <a href="/issues/ticket/${ticket.ticket_number}" class="issues-table-ticket-number">
                    #${ticket.ticket_number}
                </a>
            </td>
            <td>
                <span class="issues-badge issues-badge-priority-${ticket.priority}">
                    ${IssuesCommon.getPriorityName(ticket.priority)}
                </span>
            </td>
            <td class="issues-table-category">${ticket.category}</td>
            <td class="issues-table-title">${IssuesCommon.escapeHtml(ticket.title)}</td>
            <td class="issues-table-user">${ticket.created_by.email}</td>
            <td>
                <span class="issues-badge issues-badge-status-${ticket.status}">
                    ${IssuesCommon.getStatusName(ticket.status)}
                </span>
            </td>
            <td class="issues-table-date">${IssuesCommon.formatDate(ticket.updated_at)}</td>
            <td class="issues-table-actions">
                <button class="issues-table-action-btn" onclick="location.href='/issues/ticket/${ticket.ticket_number}'">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
};

// ============================================================================
// ZAMKNIĘTE TICKETY
// ============================================================================

IssuesAdminPanel.loadClosedTickets = async function () {
    const tableBody = IssuesAdminPanel.elements.closedTableBody;
    if (!tableBody) return;

    try {
        // Loading state
        tableBody.innerHTML = `
            <tr>
                <td colspan="7" class="issues-table-loading">
                    <i class="fas fa-spinner fa-spin"></i> Ładowanie ticketów...
                </td>
            </tr>
        `;

        // Pobierz tickety
        const filters = IssuesAdminPanel.state.filters.closed;
        const response = await IssuesCommon.getClosedTickets(filters);

        IssuesAdminPanel.state.closedTickets = response.tickets;
        IssuesAdminPanel.state.pagination.closed = {
            currentPage: Math.floor(filters.offset / filters.limit) + 1,
            totalPages: Math.ceil(response.total / filters.limit),
            total: response.total
        };

        // Renderuj tickety
        IssuesAdminPanel.renderClosedTickets();
        IssuesAdminPanel.renderPagination('closed');

    } catch (error) {
        console.error('Error loading closed tickets:', error);
        tableBody.innerHTML = `
            <tr>
                <td colspan="7" class="issues-table-empty">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Wystąpił błąd podczas ładowania ticketów</p>
                </td>
            </tr>
        `;
    }
};

IssuesAdminPanel.renderClosedTickets = function () {
    const tableBody = IssuesAdminPanel.elements.closedTableBody;
    if (!tableBody) return;

    const tickets = IssuesAdminPanel.state.closedTickets;

    if (tickets.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="7" class="issues-table-empty">
                    <i class="fas fa-inbox"></i>
                    <p>Brak zamkniętych ticketów</p>
                </td>
            </tr>
        `;
        return;
    }

    tableBody.innerHTML = tickets.map(ticket => `
        <tr>
            <td>
                <a href="/issues/ticket/${ticket.ticket_number}" class="issues-table-ticket-number">
                    #${ticket.ticket_number}
                </a>
            </td>
            <td class="issues-table-category">${ticket.category}</td>
            <td class="issues-table-title">${IssuesCommon.escapeHtml(ticket.title)}</td>
            <td class="issues-table-user">${ticket.created_by.email}</td>
            <td class="issues-table-date">${IssuesCommon.formatDate(ticket.created_at)}</td>
            <td class="issues-table-date">${IssuesCommon.formatDate(ticket.closed_at)}</td>
            <td class="issues-table-actions">
                <button class="issues-table-action-btn" onclick="location.href='/issues/ticket/${ticket.ticket_number}'">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
};

// ============================================================================
// PAGINACJA
// ============================================================================

IssuesAdminPanel.renderPagination = function (type) {
    const container = type === 'active'
        ? IssuesAdminPanel.elements.activePagination
        : IssuesAdminPanel.elements.closedPagination;

    if (!container) return;

    const pagination = IssuesAdminPanel.state.pagination[type];
    const { currentPage, totalPages, total } = pagination;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const filters = IssuesAdminPanel.state.filters[type];
    const itemsPerPage = filters.limit;
    const startItem = (currentPage - 1) * itemsPerPage + 1;
    const endItem = Math.min(currentPage * itemsPerPage, total);

    let html = `
        <button class="issues-pagination-btn" data-page="prev" ${currentPage === 1 ? 'disabled' : ''}>
            <i class="fas fa-chevron-left"></i>
        </button>
    `;

    // Strony
    for (let i = 1; i <= totalPages; i++) {
        if (
            i === 1 ||
            i === totalPages ||
            (i >= currentPage - 2 && i <= currentPage + 2)
        ) {
            html += `
                <button class="issues-pagination-btn ${i === currentPage ? 'issues-pagination-btn-active' : ''}" 
                        data-page="${i}">
                    ${i}
                </button>
            `;
        } else if (i === currentPage - 3 || i === currentPage + 3) {
            html += `<span class="issues-pagination-info">...</span>`;
        }
    }

    html += `
        <button class="issues-pagination-btn" data-page="next" ${currentPage === totalPages ? 'disabled' : ''}>
            <i class="fas fa-chevron-right"></i>
        </button>
        <span class="issues-pagination-info">${startItem}-${endItem} z ${total}</span>
    `;

    container.innerHTML = html;

    // Obsługa kliknięć
    container.querySelectorAll('.issues-pagination-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const page = btn.dataset.page;
            IssuesAdminPanel.changePage(type, page);
        });
    });
};

IssuesAdminPanel.changePage = function (type, page) {
    const pagination = IssuesAdminPanel.state.pagination[type];
    const filters = IssuesAdminPanel.state.filters[type];

    let newPage = pagination.currentPage;

    if (page === 'prev') {
        newPage = Math.max(1, pagination.currentPage - 1);
    } else if (page === 'next') {
        newPage = Math.min(pagination.totalPages, pagination.currentPage + 1);
    } else {
        newPage = parseInt(page);
    }

    // Ustaw offset
    filters.offset = (newPage - 1) * filters.limit;

    // Załaduj tickety
    if (type === 'active') {
        IssuesAdminPanel.loadActiveTickets();
    } else {
        IssuesAdminPanel.loadClosedTickets();
    }
};

// ============================================================================
// FILTRY
// ============================================================================

IssuesAdminPanel.initFilters = function () {
    const filterPriority = IssuesAdminPanel.elements.filterPriorityActive;

    if (filterPriority) {
        filterPriority.addEventListener('change', () => {
            IssuesAdminPanel.state.filters.active.priority = filterPriority.value;
            IssuesAdminPanel.state.filters.active.offset = 0; // Reset paginacji
            IssuesAdminPanel.loadActiveTickets();
        });
    }
};

IssuesAdminPanel.initRefreshButtons = function () {
    const refreshActive = IssuesAdminPanel.elements.refreshActive;
    const refreshClosed = IssuesAdminPanel.elements.refreshClosed;

    if (refreshActive) {
        refreshActive.addEventListener('click', () => {
            IssuesAdminPanel.loadActiveTickets();
            IssuesAdminPanel.loadStats();
        });
    }

    if (refreshClosed) {
        refreshClosed.addEventListener('click', () => {
            IssuesAdminPanel.loadClosedTickets();
        });
    }
};

// ============================================================================
// URUCHOMIENIE PO ZAŁADOWANIU DOM
// ============================================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', IssuesAdminPanel.init);
} else {
    IssuesAdminPanel.init();
}