// app/modules/dashboard/static/js/active_users.js

/**
 * Widget aktywnych użytkowników - JavaScript
 * Real-time tracking użytkowników online dla administratorów
 */

window.ActiveUsersWidget = (function () {
    'use strict';

    // Konfiguracja
    const CONFIG = {
        REFRESH_INTERVAL: 30000, // 30 sekund
        MAX_VISIBLE_USERS: 6,
        API_ENDPOINTS: {
            ACTIVE_USERS: '/dashboard/api/active-users',
            FORCE_LOGOUT: '/dashboard/api/force-logout',
            USER_DETAILS: '/dashboard/api/user-details'
        },
        STATUSES: {
            'active': { icon: '🟢', color: '#22c55e', text: 'Aktywny' },
            'idle': { icon: '🟡', color: '#f59e0b', text: 'Bezczynny' },
            'away': { icon: '🟠', color: '#f97316', text: 'Nieobecny' },
            'offline': { icon: '🔴', color: '#ef4444', text: 'Offline' }
        }
    };

    // Stan widgetu
    let state = {
        users: [],
        isLoading: false,
        isExpanded: false,
        refreshInterval: null,
        lastUpdate: null
    };

    // Elementy DOM
    let elements = {};

    /**
     * Inicjalizacja widgetu
     */
    function init() {
        console.log('[ActiveUsers] Inicjalizacja widgetu aktywnych użytkowników');

        // Znajdź elementy DOM
        cacheElements();

        // Sprawdź czy widget istnieje (tylko dla adminów)
        if (!elements.widget) {
            console.log('[ActiveUsers] Widget nie znaleziony - brak uprawnień administratora');
            return;
        }

        // Inicjalizuj event listeners
        initEventListeners();

        // Załaduj dane
        loadActiveUsers();

        // Uruchom auto-refresh
        startAutoRefresh();

        console.log('[ActiveUsers] Widget zainicjalizowany pomyślnie');
    }

    /**
     * Cachowanie elementów DOM
     */
    function cacheElements() {
        elements = {
            widget: document.getElementById('active-users-widget'),
            titleText: document.getElementById('widget-title-text'),
            activeCount: document.getElementById('active-count'),
            refreshBtn: document.getElementById('refresh-active-users'),
            autoRefreshIndicator: document.getElementById('auto-refresh-indicator'),
            loading: document.getElementById('active-users-loading'),
            usersList: document.getElementById('active-users-list'),
            emptyState: document.getElementById('active-users-empty'),
            errorState: document.getElementById('active-users-error'),
            retryBtn: document.getElementById('retry-active-users'),
            widgetFooter: document.getElementById('widget-footer'),
            expandToggle: document.getElementById('expand-toggle'),
            expandCount: document.getElementById('expand-count'),
            modal: document.getElementById('user-details-modal'),
            modalOverlay: document.getElementById('modal-overlay'),
            modalClose: document.getElementById('modal-close'),
            modalBody: document.getElementById('modal-body'),
            btnCloseModal: document.getElementById('btn-close-modal'),
            btnForceLogout: document.getElementById('btn-force-logout'),
            userTemplate: document.getElementById('user-item-template')
        };
    }

    /**
     * Inicjalizacja event listeners
     */
    function initEventListeners() {
        // Refresh button
        if (elements.refreshBtn) {
            elements.refreshBtn.addEventListener('click', handleManualRefresh);
        }

        // Retry button
        if (elements.retryBtn) {
            elements.retryBtn.addEventListener('click', loadActiveUsers);
        }

        // Expand toggle
        if (elements.expandToggle) {
            elements.expandToggle.addEventListener('click', toggleExpanded);
        }

        // Modal controls
        if (elements.modalClose) {
            elements.modalClose.addEventListener('click', closeModal);
        }
        if (elements.modalOverlay) {
            elements.modalOverlay.addEventListener('click', closeModal);
        }
        if (elements.btnCloseModal) {
            elements.btnCloseModal.addEventListener('click', closeModal);
        }

        // Keyboard navigation
        document.addEventListener('keydown', handleKeyboardEvents);

        // Page visibility API - pause refresh when tab is hidden
        document.addEventListener('visibilitychange', handleVisibilityChange);
    }

    /**
     * Ładowanie listy aktywnych użytkowników
     */
    async function loadActiveUsers() {
        if (state.isLoading) return;

        try {
            state.isLoading = true;
            showLoadingState();

            console.log('[ActiveUsers] Ładowanie aktywnych użytkowników...');

            const response = await fetch(CONFIG.API_ENDPOINTS.ACTIVE_USERS, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.success) {
                state.users = data.users || [];
                state.lastUpdate = new Date();

                console.log(`[ActiveUsers] Załadowano ${state.users.length} użytkowników`);

                renderUsers();
                updateWidgetTitle();
                showSuccessState();
            } else {
                throw new Error(data.error || 'Nieznany błąd API');
            }

        } catch (error) {
            console.error('[ActiveUsers] Błąd ładowania użytkowników:', error);
            showErrorState(error.message);
        } finally {
            state.isLoading = false;
            stopRefreshButtonSpinning();
        }
    }

    /**
     * Renderowanie listy użytkowników
     */
    function renderUsers() {
        if (!elements.usersList || !elements.userTemplate) return;

        // Wyczyść listę
        elements.usersList.innerHTML = '';

        // Posortuj użytkowników według statusu i aktywności
        const sortedUsers = [...state.users].sort((a, b) => {
            // Priorytet: aktywni > bezczynni > nieobecni > offline
            const statusPriority = { 'active': 4, 'idle': 3, 'away': 2, 'offline': 1 };
            const aPriority = statusPriority[a.status] || 0;
            const bPriority = statusPriority[b.status] || 0;

            if (aPriority !== bPriority) {
                return bPriority - aPriority;
            }

            // Jeśli ten sam status, sortuj po ostatniej aktywności
            return new Date(b.last_activity_timestamp || 0) - new Date(a.last_activity_timestamp || 0);
        });

        // Określ użytkowników do wyświetlenia
        const visibleUsers = state.isExpanded ? sortedUsers : sortedUsers.slice(0, CONFIG.MAX_VISIBLE_USERS);
        const hiddenUsersCount = sortedUsers.length - visibleUsers.length;

        // Renderuj widocznych użytkowników
        visibleUsers.forEach(user => {
            const userElement = createUserElement(user);
            elements.usersList.appendChild(userElement);
        });

        // Aktualizuj footer
        updateFooter(hiddenUsersCount);
    }

    /**
     * Tworzenie elementu użytkownika
     */
    function createUserElement(user) {
        // Klonuj template
        const template = elements.userTemplate.content.cloneNode(true);
        const userItem = template.querySelector('.user-item');

        // Podstawowe informacje
        userItem.setAttribute('data-user-id', user.user_id);

        // Avatar
        const avatar = userItem.querySelector('.user-avatar');
        if (user.user_avatar && user.user_avatar !== '/static/images/avatars/default_avatars/avatar1.svg') {
            avatar.src = user.user_avatar;
            avatar.alt = user.user_name;
            avatar.style.backgroundImage = 'none';
            avatar.textContent = '';
        } else {
            // Fallback do inicjałów gdy brak avatara
            avatar.style.backgroundImage = 'linear-gradient(45deg, #ED6B24, #f39c12)';
            avatar.alt = user.user_name;
            avatar.textContent = user.user_name.charAt(0).toUpperCase();
            avatar.style.display = 'flex';
            avatar.style.alignItems = 'center';
            avatar.style.justifyContent = 'center';
            avatar.style.fontSize = '1.2rem';
            avatar.style.fontWeight = 'bold';
            avatar.style.color = 'white';
            // Usuń atrybut src jeśli istnieje
            avatar.removeAttribute('src');
        }

        // Status indicator
        const statusIndicator = userItem.querySelector('.status-indicator');
        statusIndicator.className = `status-indicator ${user.status}`;
        statusIndicator.title = CONFIG.STATUSES[user.status]?.text || user.status;

        // User details
        userItem.querySelector('.user-name').textContent = user.user_name;

        const userRole = userItem.querySelector('.user-role');
        userRole.textContent = user.user_role;
        userRole.className = `user-role ${user.user_role}`;

        const pageLabel = user.page_label || user.current_page || '📱 Aplikacja';
        userItem.querySelector('.user-page').textContent = pageLabel;
        userItem.querySelector('.activity-time').textContent = user.last_activity;

        // Event listeners dla akcji
        const viewDetailsBtn = userItem.querySelector('.view-details');
        const forceLogoutBtn = userItem.querySelector('.force-logout');

        viewDetailsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            showUserDetails(user);
        });

        forceLogoutBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            confirmForceLogout(user);
        });

        // Click na całym item - pokaż szczegóły
        userItem.addEventListener('click', () => {
            showUserDetails(user);
        });

        return userItem;
    }

    /**
     * Aktualizacja tytułu widgetu
     */
    function updateWidgetTitle() {
        if (!elements.activeCount) return;

        const activeUsers = state.users.filter(user => ['active', 'idle', 'away'].includes(user.status));
        const count = activeUsers.length;

        elements.activeCount.textContent = `(${count})`;

        // Aktualizuj tytuł z liczbą
        if (elements.titleText) {
            elements.titleText.textContent = count === 1 ? 'Aktywny użytkownik' : 'Aktywni użytkownicy';
        }
    }

    /**
     * Aktualizacja footera z rozwijaniem
     */
    function updateFooter(hiddenUsersCount) {
        if (!elements.widgetFooter || !elements.expandToggle) return;

        if (hiddenUsersCount > 0) {
            elements.widgetFooter.style.display = 'block';

            const expandText = elements.expandToggle.querySelector('.expand-text');
            const expandCount = elements.expandToggle.querySelector('.expand-count');

            if (state.isExpanded) {
                expandText.textContent = 'Pokaż mniej';
                expandCount.textContent = '';
            } else {
                expandText.textContent = 'Pokaż wszystkich';
                expandCount.textContent = `(${hiddenUsersCount} więcej)`;
            }
        } else {
            elements.widgetFooter.style.display = 'none';
        }
    }

    /**
     * Przełączanie rozszerzonego widoku
     */
    function toggleExpanded() {
        state.isExpanded = !state.isExpanded;
        renderUsers();

        console.log(`[ActiveUsers] Widok ${state.isExpanded ? 'rozszerzony' : 'zwężony'}`);
    }

    /**
     * Pokazanie szczegółów użytkownika
     */
    async function showUserDetails(user) {
        if (!elements.modal || !elements.modalBody) return;

        try {
            // Pokaż modal
            elements.modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';

            // Załaduj szczegółowe dane
            elements.modalBody.innerHTML = '<div class="loading-spinner"></div><span>Ładowanie szczegółów...</span>';

            const response = await fetch(`${CONFIG.API_ENDPOINTS.USER_DETAILS}/${user.user_id}`);
            const data = await response.json();

            if (data.success) {
                renderUserDetails(data.user, data.sessions || []);

                // Pokaż przycisk force logout dla aktywnych użytkowników
                if (elements.btnForceLogout && user.status !== 'offline') {
                    elements.btnForceLogout.style.display = 'inline-block';
                    elements.btnForceLogout.onclick = () => confirmForceLogout(user);
                } else if (elements.btnForceLogout) {
                    elements.btnForceLogout.style.display = 'none';
                }
            } else {
                elements.modalBody.innerHTML = `<div class="error-message">Błąd: ${data.error}</div>`;
            }

        } catch (error) {
            console.error('[ActiveUsers] Błąd ładowania szczegółów użytkownika:', error);
            elements.modalBody.innerHTML = `<div class="error-message">Błąd ładowania: ${error.message}</div>`;
        }
    }

    /**
     * Renderowanie szczegółów użytkownika w modalu
     */
    function renderUserDetails(user, sessions) {
        const statusInfo = CONFIG.STATUSES[user.status] || {};

        const html = `
            <div class="user-details-content">
                <div class="user-header">
                    <div class="user-avatar-large">
                        ${user.user_avatar ?
                `<img src="${user.user_avatar}" alt="${user.user_name}">` :
                `<div class="avatar-placeholder">${user.user_name.charAt(0).toUpperCase()}</div>`
            }
                        <div class="status-badge ${user.status}">
                            ${statusInfo.icon} ${statusInfo.text}
                        </div>
                    </div>
                    <div class="user-info-detailed">
                        <h3>${user.user_name}</h3>
                        <p class="user-email">${user.user_email}</p>
                        <span class="role-badge ${user.user_role}">${user.user_role}</span>
                    </div>
                </div>
                
                <div class="activity-info">
                    <div class="info-row">
                        <strong>Aktualna lokalizacja:</strong>
                        <span>${user.page_label || user.current_page || '📱 Aplikacja'}</span>
                    </div>
                    <div class="info-row">
                        <strong>Ostatnia aktywność:</strong>
                        <span>${user.last_activity}</span>
                    </div>
                    <div class="info-row">
                        <strong>Czas sesji:</strong>
                        <span>${user.session_duration || 'Nieznany'}</span>
                    </div>
                    <div class="info-row">
                        <strong>Adres IP:</strong>
                        <span>${user.ip_address || 'Nieznany'}</span>
                    </div>
                </div>

                ${sessions.length > 0 ? `
                    <div class="sessions-history">
                        <h4>Historia sesji (ostatnie 7 dni)</h4>
                        <div class="sessions-list">
                            ${sessions.map(session => `
                                <div class="session-item">
                                    <div class="session-time">
                                        ${formatDateTime(session.created_at)}
                                        ${session.logout_time ? ` - ${formatDateTime(session.logout_time)}` : ' (aktywna)'}
                                    </div>
                                    <div class="session-duration">${session.duration}</div>
                                    <div class="session-ip">${session.ip_address || 'Nieznany IP'}</div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>

            <style>
                .user-details-content { line-height: 1.6; }
                .user-header { display: flex; gap: 1rem; margin-bottom: 1.5rem; align-items: center; }
                .user-avatar-large { position: relative; }
                .user-avatar-large img, .avatar-placeholder { 
                    width: 80px; height: 80px; border-radius: 50%; 
                    background: linear-gradient(45deg, #ED6B24, #f39c12);
                    display: flex; align-items: center; justify-content: center;
                    font-size: 2rem; font-weight: bold; color: white;
                }
                .status-badge { 
                    position: absolute; bottom: -5px; right: -5px; 
                    background: white; padding: 0.25rem 0.5rem; border-radius: 12px;
                    font-size: 0.75rem; font-weight: 600; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .status-badge.active { color: #22c55e; }
                .status-badge.idle { color: #f59e0b; }
                .status-badge.away { color: #f97316; }
                .status-badge.offline { color: #ef4444; }
                .user-info-detailed h3 { margin: 0 0 0.25rem 0; font-size: 1.25rem; }
                .user-email { margin: 0 0 0.5rem 0; color: #64748b; }
                .role-badge { 
                    padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; 
                    font-weight: 600; text-transform: uppercase;
                }
                .role-badge.admin { background: #fee2e2; color: #dc2626; }
                .role-badge.user { background: #dbeafe; color: #2563eb; }
                .role-badge.partner { background: #f3e8ff; color: #7c3aed; }
                .activity-info { margin-bottom: 1.5rem; }
                .info-row { 
                    display: flex; justify-content: space-between; margin-bottom: 0.5rem;
                    padding: 0.5rem; background: #f8fafc; border-radius: 6px;
                }
                .sessions-history h4 { margin: 0 0 1rem 0; font-size: 1rem; }
                .sessions-list { max-height: 200px; overflow-y: auto; }
                .session-item { 
                    padding: 0.75rem; border: 1px solid #e2e8f0; border-radius: 6px; 
                    margin-bottom: 0.5rem; font-size: 0.875rem;
                }
                .session-time { font-weight: 600; margin-bottom: 0.25rem; }
                .session-duration { color: #64748b; }
                .session-ip { color: #9ca3af; font-size: 0.75rem; }
                .error-message { 
                    text-align: center; padding: 2rem; color: #ef4444; 
                    background: #fef2f2; border-radius: 6px; 
                }
            </style>
        `;

        elements.modalBody.innerHTML = html;
    }

    /**
     * Potwierdzenie wylogowania użytkownika
     */
    function confirmForceLogout(user) {
        const confirmed = confirm(
            `Czy na pewno chcesz wylogować użytkownika "${user.user_name}"?\n\n` +
            `Wszystkie jego aktywne sesje zostaną zakończone.`
        );

        if (confirmed) {
            executeForceLogout(user);
        }
    }

    /**
     * Wykonanie wylogowania użytkownika
     */
    async function executeForceLogout(user) {
        try {
            console.log(`[ActiveUsers] Wymuszanie wylogowania użytkownika ID:${user.user_id}`);

            const response = await fetch(`${CONFIG.API_ENDPOINTS.FORCE_LOGOUT}/${user.user_id}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin'
            });

            const data = await response.json();

            if (data.success) {
                console.log(`[ActiveUsers] Użytkownik ${user.user_name} został wylogowany`);

                // Pokaż komunikat sukcesu
                showNotification(`Użytkownik ${user.user_name} został wylogowany`, 'success');

                // Zamknij modal
                closeModal();

                // Odśwież listę użytkowników
                setTimeout(() => loadActiveUsers(), 1000);

            } else {
                throw new Error(data.error || 'Nieznany błąd');
            }

        } catch (error) {
            console.error('[ActiveUsers] Błąd wylogowywania użytkownika:', error);
            showNotification(`Błąd: ${error.message}`, 'error');
        }
    }

    /**
     * Zamknięcie modala
     */
    function closeModal() {
        if (elements.modal) {
            elements.modal.style.display = 'none';
            document.body.style.overflow = '';
        }
    }

    /**
     * Obsługa manualnego odświeżania
     */
    function handleManualRefresh() {
        if (state.isLoading) return;

        console.log('[ActiveUsers] Manualne odświeżanie');

        // Animacja spinning
        startRefreshButtonSpinning();

        // Załaduj dane
        loadActiveUsers();
    }

    /**
     * Uruchomienie auto-refresh
     */
    function startAutoRefresh() {
        // Wyczyść poprzedni interval
        if (state.refreshInterval) {
            clearInterval(state.refreshInterval);
        }

        // Uruchom nowy interval
        state.refreshInterval = setInterval(() => {
            if (!document.hidden && !state.isLoading) {
                console.log('[ActiveUsers] Auto-refresh');
                loadActiveUsers();
            }
        }, CONFIG.REFRESH_INTERVAL);

        console.log(`[ActiveUsers] Auto-refresh uruchomiony (${CONFIG.REFRESH_INTERVAL}ms)`);
    }

    /**
     * Zatrzymanie auto-refresh
     */
    function stopAutoRefresh() {
        if (state.refreshInterval) {
            clearInterval(state.refreshInterval);
            state.refreshInterval = null;
            console.log('[ActiveUsers] Auto-refresh zatrzymany');
        }
    }

    /**
     * Animacja spinning dla przycisku refresh
     */
    function startRefreshButtonSpinning() {
        if (elements.refreshBtn) {
            elements.refreshBtn.classList.add('spinning');
        }
    }

    function stopRefreshButtonSpinning() {
        if (elements.refreshBtn) {
            elements.refreshBtn.classList.remove('spinning');
        }
    }

    /**
     * Pokazanie stanu ładowania
     */
    function showLoadingState() {
        hideAllStates();
        if (elements.loading) {
            elements.loading.style.display = 'flex';
        }
    }

    /**
     * Pokazanie stanu sukcesu
     */
    function showSuccessState() {
        hideAllStates();

        if (state.users.length > 0) {
            if (elements.usersList) {
                elements.usersList.style.display = 'block';
            }
        } else {
            if (elements.emptyState) {
                elements.emptyState.style.display = 'block';
            }
        }
    }

    /**
     * Pokazanie stanu błędu
     */
    function showErrorState(errorMessage) {
        hideAllStates();

        if (elements.errorState) {
            elements.errorState.style.display = 'block';

            const subtitle = elements.errorState.querySelector('.error-subtitle');
            if (subtitle) {
                subtitle.textContent = errorMessage || 'Wystąpił nieoczekiwany błąd';
            }
        }
    }

    /**
     * Ukrycie wszystkich stanów
     */
    function hideAllStates() {
        const states = [elements.loading, elements.usersList, elements.emptyState, elements.errorState];
        states.forEach(el => {
            if (el) el.style.display = 'none';
        });
    }

    /**
     * Obsługa zmian widoczności strony
     */
    function handleVisibilityChange() {
        if (document.hidden) {
            console.log('[ActiveUsers] Strona ukryta - wstrzymanie auto-refresh');
        } else {
            console.log('[ActiveUsers] Strona widoczna - wznowienie auto-refresh');
            // Odśwież dane gdy strona staje się widoczna
            if (!state.isLoading) {
                loadActiveUsers();
            }
        }
    }

    /**
     * Obsługa klawiatury
     */
    function handleKeyboardEvents(event) {
        // ESC - zamknij modal
        if (event.key === 'Escape' && elements.modal && elements.modal.style.display === 'flex') {
            closeModal();
        }
    }

    /**
     * Pokazanie powiadomienia
     */
    function showNotification(message, type = 'info') {
        // Sprawdź czy istnieje globalna funkcja showToast
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }

        // Fallback - prosta notyfikacja
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;

        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${type === 'success' ? '#22c55e' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10000;
            animation: slideInRight 0.3s ease-out;
        `;

        document.body.appendChild(notification);

        // Usuń po 4 sekundach
        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease-in';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 4000);
    }

    /**
     * Formatowanie daty i czasu
     */
    function formatDateTime(isoString) {
        if (!isoString) return 'Nieznany';

        try {
            const date = new Date(isoString);
            return date.toLocaleString('pl-PL', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (error) {
            return 'Błędna data';
        }
    }

    /**
     * Cleanup przy zniszczeniu widgetu
     */
    function destroy() {
        console.log('[ActiveUsers] Niszczenie widgetu');

        stopAutoRefresh();
        closeModal();

        // Usuń event listeners
        document.removeEventListener('keydown', handleKeyboardEvents);
        document.removeEventListener('visibilitychange', handleVisibilityChange);

        // Wyczyść stan
        state = {
            users: [],
            isLoading: false,
            isExpanded: false,
            refreshInterval: null,
            lastUpdate: null
        };
    }

    /**
     * Debug info
     */
    function getDebugInfo() {
        return {
            state: { ...state },
            config: CONFIG,
            elementsFound: Object.keys(elements).filter(key => elements[key] !== null),
            lastUpdate: state.lastUpdate?.toISOString(),
            isAutoRefreshActive: !!state.refreshInterval
        };
    }

    // CSS dla animacji notyfikacji
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideInRight {
            from {
                opacity: 0;
                transform: translateX(100%);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        @keyframes slideOutRight {
            from {
                opacity: 1;
                transform: translateX(0);
            }
            to {
                opacity: 0;
                transform: translateX(100%);
            }
        }
    `;
    document.head.appendChild(style);

    // Publiczne API
    return {
        init,
        destroy,
        refresh: loadActiveUsers,
        getDebugInfo,

        // Gettery stanu
        get users() { return [...state.users]; },
        get isLoading() { return state.isLoading; },
        get lastUpdate() { return state.lastUpdate; }
    };

})();

// Auto-inicjalizacja gdy DOM jest gotowy
document.addEventListener('DOMContentLoaded', function () {
    // Małe opóźnienie żeby inne skrypty się załadowały
    setTimeout(() => {
        if (window.ActiveUsersWidget && document.getElementById('active-users-widget')) {
            window.ActiveUsersWidget.init();
        }
    }, 100);
});

// Cleanup przy opuszczeniu strony
window.addEventListener('beforeunload', function () {
    if (window.ActiveUsersWidget) {
        window.ActiveUsersWidget.destroy();
    }
});

// Export dla ES modules (jeśli potrzebne)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.ActiveUsersWidget;
}