/**
 * Issues Widget - Ostatnie niezamknięte tickety użytkownika
 *
 * Wyświetla 5 ostatnich ticketów użytkownika w statusach: new, open, in_progress
 * Dla każdego ticketa pokazuje: tytuł, status, datę ostatniej wiadomości
 */

(function() {
    'use strict';

    console.log('[Issues Widget] Initializing...');

    // Konfiguracja
    const CONFIG = {
        apiEndpoint: '/issues/api/tickets',
        limit: 5,
        excludedStatuses: ['closed', 'cancelled'],
        refreshInterval: 60000 // 1 minuta
    };

    // Statusy ticketów z kolorami i ikonami
    const STATUS_CONFIG = {
        'new': { label: 'Nowy', color: '#3498db', icon: '🆕' },
        'open': { label: 'Otwarty', color: '#f39c12', icon: '📂' },
        'in_progress': { label: 'W trakcie', color: '#9b59b6', icon: '⚙️' },
        'closed': { label: 'Zamknięty', color: '#95a5a6', icon: '✅' },
        'cancelled': { label: 'Anulowany', color: '#7f8c8d', icon: '❌' }
    };

    // Elementy DOM
    const elements = {
        list: document.getElementById('issues-list'),
        empty: document.getElementById('issues-empty')
    };

    /**
     * Formatuje datę zgodnie z wymaganiami:
     * - < 5 dni: relatywnie (np. "2 dni temu")
     * - > 5 dni: konkretnie (np. "20.10.2025 14:30")
     */
    function formatDate(dateString) {
        if (!dateString) return 'Brak danych';

        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

        // Jeśli > 5 dni, pokaż konkretną datę
        if (diffDays > 5) {
            const day = String(date.getDate()).padStart(2, '0');
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const year = date.getFullYear();
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            return `${day}.${month}.${year} ${hours}:${minutes}`;
        }

        // Jeśli <= 5 dni, pokaż relatywnie
        if (diffDays === 0) {
            const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
            if (diffHours === 0) {
                const diffMinutes = Math.floor(diffMs / (1000 * 60));
                if (diffMinutes < 1) return 'przed chwilą';
                if (diffMinutes === 1) return '1 minutę temu';
                return `${diffMinutes} minut temu`;
            }
            if (diffHours === 1) return '1 godzinę temu';
            return `${diffHours} godzin temu`;
        }

        if (diffDays === 1) return 'wczoraj';
        return `${diffDays} dni temu`;
    }

    /**
     * Pobiera ostatnią wiadomość z ticketa
     */
    function getLastMessageDate(ticket) {
        // Używamy updated_at jeśli dostępne, inaczej created_at
        return ticket.updated_at || ticket.created_at;
    }

    /**
     * Renderuje pojedynczy ticket
     */
    function renderTicket(ticket) {
        const status = STATUS_CONFIG[ticket.status] || STATUS_CONFIG['new'];
        const lastMessageDate = getLastMessageDate(ticket);
        const formattedDate = formatDate(lastMessageDate);

        return `
            <a href="/issues/ticket/${ticket.ticket_number}" class="issue-item" data-ticket-id="${ticket.id}">
                <div class="issue-header">
                    <div class="issue-number">#${ticket.ticket_number}</div>
                    <div class="issue-status" style="background-color: ${status.color};">
                        <span class="status-icon">${status.icon}</span>
                        <span class="status-label">${status.label}</span>
                    </div>
                </div>
                <div class="issue-title">${escapeHtml(ticket.title)}</div>
                <div class="issue-footer">
                    <div class="issue-date">
                        <span class="date-icon">💬</span>
                        <span class="date-text">Ostatnia wiadomość: ${formattedDate}</span>
                    </div>
                    ${ticket.priority === 'critical' || ticket.priority === 'high' ?
                        `<div class="issue-priority issue-priority-${ticket.priority}">
                            ${ticket.priority === 'critical' ? '🔥' : '⚠️'}
                            ${ticket.priority === 'critical' ? 'Krytyczny' : 'Wysoki'}
                        </div>` :
                        ''}
                </div>
            </a>
        `;
    }

    /**
     * Escape HTML dla bezpieczeństwa
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Renderuje listę ticketów
     */
    function renderTickets(tickets) {
        if (!tickets || tickets.length === 0) {
            showEmptyState();
            return;
        }

        const html = tickets.map(ticket => renderTicket(ticket)).join('');
        elements.list.innerHTML = html;
        elements.list.style.display = 'flex';
        elements.empty.style.display = 'none';
    }

    /**
     * Pokazuje pusty stan
     */
    function showEmptyState() {
        elements.list.style.display = 'none';
        elements.empty.style.display = 'flex';
    }

    /**
     * Pokazuje komunikat błędu
     */
    function showError(message) {
        elements.list.innerHTML = `
            <div class="issues-error">
                <div class="error-icon">⚠️</div>
                <p class="error-message">${escapeHtml(message)}</p>
                <button class="error-retry-btn" onclick="location.reload()">Spróbuj ponownie</button>
            </div>
        `;
        elements.list.style.display = 'block';
        elements.empty.style.display = 'none';
    }

    /**
     * Pobiera tickety z API
     */
    async function fetchTickets() {
        try {
            console.log('[Issues Widget] Fetching tickets...');

            const response = await fetch(`${CONFIG.apiEndpoint}?limit=${CONFIG.limit + 10}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Błąd pobierania danych');
            }

            console.log('[Issues Widget] Received tickets:', data.tickets.length);

            // Filtruj niezamknięte tickety
            const openTickets = data.tickets.filter(ticket =>
                !CONFIG.excludedStatuses.includes(ticket.status)
            );

            console.log('[Issues Widget] Open tickets:', openTickets.length);

            // Sortuj po dacie ostatniej wiadomości (updated_at lub created_at)
            openTickets.sort((a, b) => {
                const dateA = new Date(a.updated_at || a.created_at);
                const dateB = new Date(b.updated_at || b.created_at);
                return dateB - dateA; // Najnowsze pierwsze
            });

            // Weź tylko pierwsze 5
            const topTickets = openTickets.slice(0, CONFIG.limit);

            // Renderuj
            renderTickets(topTickets);

        } catch (error) {
            console.error('[Issues Widget] Error fetching tickets:', error);
            showError('Nie udało się pobrać zgłoszeń. Spróbuj ponownie później.');
        }
    }

    /**
     * Inicjalizacja widgetu
     */
    function init() {
        if (!elements.list || !elements.empty) {
            console.warn('[Issues Widget] Widget elements not found. Skipping initialization.');
            return;
        }

        console.log('[Issues Widget] Starting fetch...');

        // Pierwsze pobranie danych
        fetchTickets();

        // Automatyczne odświeżanie co minutę
        setInterval(fetchTickets, CONFIG.refreshInterval);

        console.log('[Issues Widget] Initialized successfully');
    }

    // Inicjalizacja po załadowaniu DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
