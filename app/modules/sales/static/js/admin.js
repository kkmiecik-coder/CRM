// ============================================================================
// PARTNER ACADEMY - ADMIN PANEL
// Panel administracyjny dla rekrutacji partnerów
// ============================================================================

// ============================================================================
// CONSTANTS & STATE
// ============================================================================

const STATUS_TRANSLATION = {
    'pending': 'Oczekująca',
    'contacted': 'Kontakt nawiązany',
    'accepted': 'Zaakceptowana',
    'rejected': 'Odrzucona'
};

const STATUS_BADGES = {
    'pending': 'status-pending',
    'contacted': 'status-contacted',
    'accepted': 'status-accepted',
    'rejected': 'status-rejected'
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function capitalize(str) {
    if (!str) return '-';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

// State management
let applicationsPage = 1;
let applicationsTotalPages = 1;
let applicationsFilters = {
    status: '',
    search: ''
};
let applicationsSortColumn = 'created_at';
let applicationsSortDirection = 'desc';

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function () {
    console.log('[ADMIN] Inicjalizacja panelu admina...');

    loadStats();
    loadApplications();
    setupModalListeners();
    setupTableSorting();

    console.log('[ADMIN] Panel zainicjalizowany');
});

function setupModalListeners() {
    const appModal = document.getElementById('applicationModal');
    if (appModal) {
        appModal.addEventListener('click', function (e) {
            if (e.target.classList.contains('modal-overlay')) {
                closeApplicationModal();
            }
        });
    }
}

function setupTableSorting() {
    // Event delegation dla sortowania
    document.addEventListener('click', function (e) {
        const th = e.target.closest('th[data-sort]');
        if (th) {
            const column = th.dataset.sort;
            sortApplications(column);
        }
    });
}

// ============================================================================
// STATS - DASHBOARD
// ============================================================================

async function loadStats() {
    console.log('[ADMIN] Ładowanie statystyk...');
    try {
        const response = await fetch('/sales/admin/api/stats');
        const result = await response.json();

        if (result.success) {
            const data = result.data;

            // Statystyki aplikacji
            document.getElementById('stat-total').textContent = data.total_applications || 0;
            document.getElementById('stat-pending').textContent = data.pending_count || 0;
            document.getElementById('stat-contacted').textContent = data.contacted_count || 0;
            document.getElementById('stat-accepted').textContent = data.accepted_count || 0;
            document.getElementById('stat-rejected').textContent = data.rejected_count || 0;

            console.log('[ADMIN] Statystyki załadowane');
        } else {
            console.error('[ADMIN] Błąd ładowania statystyk:', result.message);
        }
    } catch (error) {
        console.error('[ADMIN] Error loading stats:', error);
    }
}

// ============================================================================
// APPLICATIONS - TABLE WITH SORTING
// ============================================================================

function sortApplications(column) {
    if (applicationsSortColumn === column) {
        // Toggle direction
        applicationsSortDirection = applicationsSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        applicationsSortColumn = column;
        applicationsSortDirection = 'desc';
    }

    loadApplications(1);
}

async function loadApplications(page = 1) {
    console.log('[ADMIN] Ładowanie aplikacji, strona:', page);
    try {
        applicationsPage = page;
        const params = new URLSearchParams({
            page: page,
            per_page: 20,
            status: applicationsFilters.status,
            search: applicationsFilters.search,
            sort_by: applicationsSortColumn,
            sort_dir: applicationsSortDirection
        });

        const url = `/sales/admin/api/applications?${params}`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.success) {
            renderApplicationsTable(result.data.applications);
            renderApplicationsPagination(result.data.pagination);
            updateSortIndicators();
            console.log('[ADMIN] Aplikacje załadowane:', result.data.applications.length);
        } else {
            console.error('[ADMIN] Błąd:', result.message);
            showToast('Błąd ładowania aplikacji', 'error');
        }
    } catch (error) {
        console.error('[ADMIN] Error loading applications:', error);
        document.getElementById('applicationsTableBody').innerHTML =
            '<tr><td colspan="8" class="loading-cell">Błąd ładowania danych</td></tr>';
        showToast('Błąd połączenia z serwerem', 'error');
    }
}

function updateSortIndicators() {
    // Usuń wszystkie wskaźniki sortowania
    document.querySelectorAll('.applications-table th[data-sort]').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
    });

    // Dodaj wskaźnik do aktywnej kolumny
    const activeTh = document.querySelector(`.applications-table th[data-sort="${applicationsSortColumn}"]`);
    if (activeTh) {
        activeTh.classList.add(`sort-${applicationsSortDirection}`);
    }
}

function renderApplicationsTable(applications) {
    const tbody = document.getElementById('applicationsTableBody');

    if (applications.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">Brak wyników</td></tr>';
        return;
    }

    tbody.innerHTML = applications.map(app => `
        <tr>
            <td>${app.id}</td>
            <td>${app.created_at}</td>
            <td>${app.first_name} ${app.last_name}</td>
            <td>${app.email}</td>
            <td>${app.phone}</td>
            <td>${capitalize(app.voivodeship)} / ${app.business_location || app.city}</td>
            <td>
                <span class="status-badge ${STATUS_BADGES[app.status]}">
                    ${STATUS_TRANSLATION[app.status]}
                </span>
            </td>
            <td>
                <button class="btn-view" onclick="openApplicationModal(${app.id})">
                    Zobacz
                </button>
            </td>
        </tr>
    `).join('');
}

function renderApplicationsPagination(pagination) {
    applicationsTotalPages = pagination.pages;
    const container = document.getElementById('pagination');

    if (applicationsTotalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';

    html += `<button onclick="loadApplications(${applicationsPage - 1})" ${applicationsPage === 1 ? 'disabled' : ''}>
        ← Poprzednia
    </button>`;

    for (let i = 1; i <= applicationsTotalPages; i++) {
        if (i === 1 || i === applicationsTotalPages || (i >= applicationsPage - 2 && i <= applicationsPage + 2)) {
            html += `<button onclick="loadApplications(${i})" ${i === applicationsPage ? 'class="active"' : ''}>
                ${i}
            </button>`;
        } else if (i === applicationsPage - 3 || i === applicationsPage + 3) {
            html += '<span>...</span>';
        }
    }

    html += `<button onclick="loadApplications(${applicationsPage + 1})" ${applicationsPage === applicationsTotalPages ? 'disabled' : ''}>
        Następna →
    </button>`;

    container.innerHTML = html;
}

function filterApplications() {
    const statusFilter = document.getElementById('statusFilter').value;
    const searchInput = document.getElementById('searchInput').value;

    applicationsFilters.status = statusFilter;
    applicationsFilters.search = searchInput;

    loadApplications(1);
}

// ============================================================================
// MODAL - APPLICATION DETAILS
// ============================================================================

async function openApplicationModal(applicationId) {
    console.log('[ADMIN] Otwieranie modala dla aplikacji:', applicationId);

    const modalContent = document.getElementById('applicationModalContent');
    modalContent.innerHTML = `
        <div style="text-align: center; padding: 60px 20px;">
            <div class="spinner"></div>
            <p style="margin-top: 20px; color: var(--text-gray);">Ładowanie danych...</p>
        </div>
    `;
    document.getElementById('applicationModal').style.display = 'flex';

    try {
        const response = await fetch(`/sales/admin/api/application/${applicationId}`);
        const result = await response.json();

        if (result.success) {
            renderApplicationModalContent(result.data);
            console.log('[ADMIN] Modal aplikacji wyrenderowany');
        } else {
            modalContent.innerHTML = `<p style="color: red;">Błąd: ${result.message}</p>`;
            showToast('Błąd ładowania szczegółów', 'error');
        }
    } catch (error) {
        console.error('[ADMIN] Error loading application details:', error);
        modalContent.innerHTML = `<p style="color: red;">Błąd ładowania szczegółów</p>`;
        showToast('Błąd połączenia z serwerem', 'error');
    }
}

function closeApplicationModal() {
    document.getElementById('applicationModal').style.display = 'none';
}

function renderApplicationModalContent(data) {
    const modalContent = document.getElementById('applicationModalContent');

    const filesizeKB = data.nda_filesize ? (data.nda_filesize / 1024).toFixed(2) : '0';

    let html = `
        <h2>Szczegóły Aplikacji #${data.id}</h2>
        
        <!-- Dane podstawowe -->
        <div class="modal-section">
            <h3>Dane osobowe</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <span class="detail-label">Imię i nazwisko</span>
                    <span class="detail-value">${data.first_name} ${data.last_name}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Email</span>
                    <span class="detail-value">${data.email}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Telefon</span>
                    <span class="detail-value">${data.phone}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Miasto</span>
                    <span class="detail-value">${data.city}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Adres</span>
                    <span class="detail-value">${data.address}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Kod pocztowy</span>
                    <span class="detail-value">${data.postal_code}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Województwo działalności</span>
                    <span class="detail-value">${capitalize(data.voivodeship)}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Miejscowość działalności</span>
                    <span class="detail-value">${data.business_location}</span>
                </div>
            </div>
        </div>
    `;

    // Dane B2B jeśli są
    if (data.is_b2b) {
        html += `
            <div class="modal-section">
                <h3>Dane firmowe (B2B)</h3>
                <div class="detail-grid">
                    <div class="detail-item">
                        <span class="detail-label">Nazwa firmy</span>
                        <span class="detail-value">${data.company_name || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">NIP</span>
                        <span class="detail-value">${data.nip || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">REGON</span>
                        <span class="detail-value">${data.regon || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Adres firmy</span>
                        <span class="detail-value">${data.company_address || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Miasto</span>
                        <span class="detail-value">${data.company_city || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Kod pocztowy</span>
                        <span class="detail-value">${data.company_postal_code || '-'}</span>
                    </div>
                </div>
            </div>
        `;
    }

    // Opis działalności
    html += `
        <div class="modal-section">
            <h3>O sobie / Działalności</h3>
            <div class="about-text">${data.about_text || 'Brak opisu'}</div>
        </div>
    `;

    // Status i NDA w jednym wierszu
    html += `
        <div class="modal-section">
            <h3>Status i dokumenty</h3>
            <div class="status-nda-row">
                <div class="status-control">
                    <label>Status aplikacji:</label>
                    <select id="statusSelect">
                        <option value="pending" ${data.status === 'pending' ? 'selected' : ''}>Oczekująca</option>
                        <option value="contacted" ${data.status === 'contacted' ? 'selected' : ''}>Kontakt nawiązany</option>
                        <option value="accepted" ${data.status === 'accepted' ? 'selected' : ''}>Zaakceptowana</option>
                        <option value="rejected" ${data.status === 'rejected' ? 'selected' : ''}>Odrzucona</option>
                    </select>
                    <button onclick="updateApplicationStatus(${data.id})">Zapisz</button>
                </div>
                <div class="nda-control">
                    ${data.has_nda_file ?
            `<button class="btn-nda" onclick="openNDA(${data.id})">
                            📄 Otwórz NDA (${filesizeKB} KB)
                        </button>` :
            '<p style="color: var(--text-gray); margin: 0;">Brak pliku NDA</p>'}
                </div>
            </div>
        </div>
    `;

    // Notatki - DODAWANIE NA GÓRZE
    html += `
        <div class="modal-section">
            <h3>Notatki</h3>
            <div class="add-note-form">
                <textarea id="newNoteText" placeholder="Dodaj nową notatkę..."></textarea>
                <button onclick="addNote(${data.id})">Dodaj notatkę</button>
            </div>
            <div class="notes-list" id="notesList">
                ${renderNotes(data.notes)}
            </div>
        </div>
    `;

    // Metadane
    html += `
        <div class="modal-section">
            <h3>Metadane</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <span class="detail-label">Data utworzenia</span>
                    <span class="detail-value">${data.created_at || '-'}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Ostatnia aktualizacja</span>
                    <span class="detail-value">${data.updated_at || '-'}</span>
                </div>
            </div>
        </div>
    `;

    modalContent.innerHTML = html;
}

function openNDA(applicationId) {
    // Otwórz PDF w nowym oknie zamiast pobierać
    window.open(`/sales/admin/api/application/${applicationId}/nda`, '_blank');
}

function renderNotes(notes) {
    if (!notes || notes.length === 0) {
        return '<div class="no-notes">Brak notatek</div>';
    }

    return notes.map(note => {
        const date = new Date(note.timestamp);
        const formattedDate = date.toLocaleString('pl-PL');

        return `
            <div class="note-item">
                <div class="note-header">
                    <span><strong>${note.author}</strong></span>
                    <span>${formattedDate}</span>
                </div>
                <div class="note-text">${note.text}</div>
            </div>
        `;
    }).join('');
}

// ============================================================================
// APPLICATION - STATUS UPDATE
// ============================================================================

async function updateApplicationStatus(applicationId) {
    try {
        const select = document.getElementById('statusSelect');
        const newStatus = select.value;

        const response = await fetch(`/sales/admin/api/application/${applicationId}/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: newStatus })
        });

        const result = await response.json();

        if (result.success) {
            showToast('Status zaktualizowany', 'success');
            loadApplications(applicationsPage); // Odśwież tabelę
            loadStats(); // Odśwież statystyki
        } else {
            showToast('Błąd aktualizacji statusu: ' + result.message, 'error');
        }
    } catch (error) {
        console.error('Error updating status:', error);
        showToast('Błąd aktualizacji statusu', 'error');
    }
}

// ============================================================================
// APPLICATION - NOTES
// ============================================================================

async function addNote(applicationId) {
    try {
        const textarea = document.getElementById('newNoteText');
        const noteText = textarea.value.trim();

        if (!noteText) {
            showToast('Wprowadź treść notatki', 'error');
            return;
        }

        const response = await fetch(`/sales/admin/api/application/${applicationId}/note`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ note: noteText })
        });

        const result = await response.json();

        if (result.success) {
            showToast('Notatka dodana', 'success');
            textarea.value = '';

            const notesList = document.getElementById('notesList');
            const newNoteHtml = `
                <div class="note-item">
                    <div class="note-header">
                        <span><strong>${result.note.author}</strong></span>
                        <span>${new Date(result.note.timestamp).toLocaleString('pl-PL')}</span>
                    </div>
                    <div class="note-text">${result.note.text}</div>
                </div>
            `;

            if (notesList.querySelector('.no-notes')) {
                notesList.innerHTML = newNoteHtml;
            } else {
                notesList.innerHTML = newNoteHtml + notesList.innerHTML;
            }
        } else {
            showToast('Błąd dodawania notatki: ' + result.message, 'error');
        }
    } catch (error) {
        console.error('Error adding note:', error);
        showToast('Błąd dodawania notatki', 'error');
    }
}

// ============================================================================
// EXPORT FUNCTIONS
// ============================================================================

async function exportApplications() {
    try {
        showToast('Generowanie pliku XLSX...', 'info');

        const params = new URLSearchParams({
            status: applicationsFilters.status,
            search: applicationsFilters.search
        });

        window.location.href = `/sales/admin/api/export-applications?${params}`;

        setTimeout(() => {
            showToast('Plik został pobrany', 'success');
        }, 1000);
    } catch (error) {
        console.error('Error exporting applications:', error);
        showToast('Błąd eksportu', 'error');
    }
}

// ============================================================================
// UTILITY - TOAST NOTIFICATIONS
// ============================================================================

function showToast(message, type = 'info') {
    const existingToasts = document.querySelectorAll('.toast');
    existingToasts.forEach(toast => toast.remove());

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================================================
// UTILITY - HANDLE LINK ACTION
// ============================================================================

function handleLinkAction(url) {
    window.open(url, '_blank');
}

// ============================================================================
// DEBUG
// ============================================================================

console.log('[ADMIN] admin.js załadowany i gotowy');