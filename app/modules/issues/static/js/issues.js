// app/modules/issues/static/js/issues.js
/**
 * Wspólne funkcje dla modułu Issues
 * Zawiera: Toast notifications, AJAX helpers, API calls
 * 
 * Autor: Konrad Kmiecik
 * Data: 2025-10-20
 */

// ============================================================================
// NAMESPACE
// ============================================================================

const IssuesCommon = {
    // Konfiguracja
    config: {
        apiBaseUrl: '/issues/api',
        toastDuration: 5000,
        maxFileSize: 5 * 1024 * 1024, // 5 MB
        maxFiles: 5
    },

    // Stan
    state: {
        uploadedFiles: [],
        currentToasts: []
    }
};

// ============================================================================
// TOAST NOTIFICATIONS
// ============================================================================

/**
 * Wyświetla toast notification
 * @param {string} type - Typ: 'success', 'error', 'warning', 'info'
 * @param {string} message - Wiadomość główna
 * @param {string} description - Dodatkowy opis (opcjonalnie)
 */
IssuesCommon.showToast = function (type, message, description = null) {
    // Znajdź lub utwórz container
    let container = document.getElementById('issuesToastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'issuesToastContainer';
        container.className = 'issues-toast-container';
        document.body.appendChild(container);
    }

    // Ikony dla różnych typów
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    // Utwórz toast
    const toast = document.createElement('div');
    toast.className = `issues-toast issues-toast-${type}`;
    toast.innerHTML = `
        <i class="fas ${icons[type]} issues-toast-icon"></i>
        <div class="issues-toast-content">
            <div class="issues-toast-message">${message}</div>
            ${description ? `<div class="issues-toast-description">${description}</div>` : ''}
        </div>
        <button class="issues-toast-close">&times;</button>
    `;

    // Dodaj toast
    container.appendChild(toast);
    IssuesCommon.state.currentToasts.push(toast);

    // Obsługa zamknięcia
    const closeBtn = toast.querySelector('.issues-toast-close');
    closeBtn.addEventListener('click', () => {
        IssuesCommon.removeToast(toast);
    });

    // Auto-zamknięcie
    setTimeout(() => {
        IssuesCommon.removeToast(toast);
    }, IssuesCommon.config.toastDuration);
};

/**
 * Usuwa toast
 */
IssuesCommon.removeToast = function (toast) {
    if (!toast || !toast.parentNode) return;

    toast.style.animation = 'issuesSlideOut 0.3s ease';

    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
        const index = IssuesCommon.state.currentToasts.indexOf(toast);
        if (index > -1) {
            IssuesCommon.state.currentToasts.splice(index, 1);
        }
    }, 300);
};

// CSS dla animacji wyjścia
if (!document.getElementById('issues-toast-animations')) {
    const style = document.createElement('style');
    style.id = 'issues-toast-animations';
    style.textContent = `
        @keyframes issuesSlideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);
}

// ============================================================================
// AJAX HELPERS
// ============================================================================

/**
 * Wykonuje zapytanie AJAX
 * @param {string} method - GET, POST, PATCH, DELETE
 * @param {string} url - URL endpointu
 * @param {object} data - Dane do wysłania (opcjonalnie)
 * @returns {Promise}
 */
IssuesCommon.ajax = async function (method, url, data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(url, options);
        const json = await response.json();

        if (!response.ok) {
            throw new Error(json.error || 'Wystąpił błąd');
        }

        return json;
    } catch (error) {
        console.error('AJAX Error:', error);
        throw error;
    }
};

// ============================================================================
// API CALLS - TICKETS
// ============================================================================

/**
 * Pobiera listę ticketów
 */
IssuesCommon.getTickets = async function (filters = {}) {
    const params = new URLSearchParams();

    if (filters.status) params.append('status', filters.status);
    if (filters.limit) params.append('limit', filters.limit);
    if (filters.offset) params.append('offset', filters.offset);

    const url = `${IssuesCommon.config.apiBaseUrl}/tickets?${params.toString()}`;
    return await IssuesCommon.ajax('GET', url);
};

/**
 * Tworzy nowy ticket
 */
IssuesCommon.createTicket = async function (ticketData) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets`;
    return await IssuesCommon.ajax('POST', url, ticketData);
};

/**
 * Pobiera szczegóły ticketu
 */
IssuesCommon.getTicket = async function (ticketNumber) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}`;
    return await IssuesCommon.ajax('GET', url);
};

/**
 * Zmienia status ticketu
 */
IssuesCommon.changeTicketStatus = async function (ticketNumber, newStatus) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}/status`;
    return await IssuesCommon.ajax('PATCH', url, { status: newStatus });
};

/**
 * Zmienia priorytet ticketu
 */
IssuesCommon.changeTicketPriority = async function (ticketNumber, newPriority) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}/priority`;
    return await IssuesCommon.ajax('PATCH', url, { priority: newPriority });
};

/**
 * Przypisuje ticket do admina
 */
IssuesCommon.assignTicket = async function (ticketNumber, adminUserId) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}/assign`;
    return await IssuesCommon.ajax('PATCH', url, { admin_user_id: adminUserId });
};

// ============================================================================
// API CALLS - MESSAGES
// ============================================================================

/**
 * Pobiera wiadomości ticketu
 */
IssuesCommon.getMessages = async function (ticketNumber) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}/messages`;
    return await IssuesCommon.ajax('GET', url);
};

/**
 * Dodaje wiadomość do ticketu
 */
IssuesCommon.addMessage = async function (ticketNumber, messageData) {
    const url = `${IssuesCommon.config.apiBaseUrl}/tickets/${ticketNumber}/messages`;
    return await IssuesCommon.ajax('POST', url, messageData);
};

// ============================================================================
// API CALLS - ATTACHMENTS
// ============================================================================

/**
 * Uploaduje załącznik
 */
IssuesCommon.uploadAttachment = async function (file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${IssuesCommon.config.apiBaseUrl}/attachments/upload`, {
            method: 'POST',
            body: formData
        });

        const json = await response.json();

        if (!response.ok) {
            throw new Error(json.error || 'Błąd uploadu');
        }

        return json;
    } catch (error) {
        console.error('Upload Error:', error);
        throw error;
    }
};

// ============================================================================
// API CALLS - ADMIN
// ============================================================================

/**
 * Pobiera aktywne tickety (admin)
 */
IssuesCommon.getActiveTickets = async function (filters = {}) {
    const params = new URLSearchParams();

    if (filters.priority) params.append('priority', filters.priority);
    if (filters.limit) params.append('limit', filters.limit);
    if (filters.offset) params.append('offset', filters.offset);

    const url = `${IssuesCommon.config.apiBaseUrl}/admin/tickets/active?${params.toString()}`;
    return await IssuesCommon.ajax('GET', url);
};

/**
 * Pobiera zamknięte tickety (admin)
 */
IssuesCommon.getClosedTickets = async function (filters = {}) {
    const params = new URLSearchParams();

    if (filters.limit) params.append('limit', filters.limit);
    if (filters.offset) params.append('offset', filters.offset);

    const url = `${IssuesCommon.config.apiBaseUrl}/admin/tickets/closed?${params.toString()}`;
    return await IssuesCommon.ajax('GET', url);
};

/**
 * Pobiera statystyki (admin)
 */
IssuesCommon.getStats = async function () {
    const url = `${IssuesCommon.config.apiBaseUrl}/admin/stats`;
    return await IssuesCommon.ajax('GET', url);
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Formatuje rozmiar pliku
 */
IssuesCommon.formatFileSize = function (bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
};

/**
 * Waliduje plik
 */
IssuesCommon.validateFile = function (file) {
    if (file.size > IssuesCommon.config.maxFileSize) {
        throw new Error(`Plik "${file.name}" jest za duży (max 5 MB)`);
    }
    return true;
};

/**
 * Formatuje datę
 */
IssuesCommon.formatDate = function (dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 7) {
        return date.toLocaleDateString('pl-PL', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } else if (days > 0) {
        return `${days} dni temu`;
    } else if (hours > 0) {
        return `${hours} godz. temu`;
    } else if (minutes > 0) {
        return `${minutes} min. temu`;
    } else {
        return 'Przed chwilą';
    }
};

/**
 * Escape HTML
 */
IssuesCommon.escapeHtml = function (text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
};

/**
 * Pobiera ikonę dla statusu
 */
IssuesCommon.getStatusIcon = function (status) {
    const icons = {
        'new': '🟢',
        'open': '🟡',
        'in_progress': '🔵',
        'closed': '✅',
        'cancelled': '❌'
    };
    return icons[status] || '❓';
};

/**
 * Pobiera ikonę dla priorytetu
 */
IssuesCommon.getPriorityIcon = function (priority) {
    const icons = {
        'low': '🟢',
        'medium': '🟡',
        'high': '🟠',
        'critical': '🔴'
    };
    return icons[priority] || '❓';
};

/**
 * Pobiera nazwę statusu
 */
IssuesCommon.getStatusName = function (status) {
    const names = {
        'new': 'Nowy',
        'open': 'Otwarty',
        'in_progress': 'W trakcie',
        'closed': 'Zamknięty',
        'cancelled': 'Anulowany'
    };
    return names[status] || status;
};

/**
 * Pobiera nazwę priorytetu
 */
IssuesCommon.getPriorityName = function (priority) {
    const names = {
        'low': 'Niski',
        'medium': 'Średni',
        'high': 'Wysoki',
        'critical': 'Krytyczny'
    };
    return names[priority] || priority;
};

// ============================================================================
// INICJALIZACJA
// ============================================================================

console.log('✅ Issues Common module loaded');