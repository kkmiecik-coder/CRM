/**
 * Ustawienia aplikacji - JavaScript
 * ==================================
 */

document.addEventListener('DOMContentLoaded', function() {
    const addSourceBtn = document.getElementById('addSourceBtn');
    const addSourceModal = document.getElementById('addSourceModal');
    const closeModalBtn = document.getElementById('closeAddSourceModal');
    const cancelBtn = document.getElementById('cancelAddSource');
    const addSourceForm = document.getElementById('addSourceForm');
    const sourcesTableBody = document.getElementById('sourcesTableBody');

    // ===== MODAL =====
    addSourceBtn?.addEventListener('click', () => {
        addSourceModal.style.display = 'flex';
        addSourceForm.reset();
        addSourceForm.querySelector('input[name="name"]')?.focus();
    });

    closeModalBtn?.addEventListener('click', () => {
        addSourceModal.style.display = 'none';
    });

    cancelBtn?.addEventListener('click', () => {
        addSourceModal.style.display = 'none';
    });

    addSourceModal?.addEventListener('click', (e) => {
        if (e.target === addSourceModal) {
            addSourceModal.style.display = 'none';
        }
    });

    // ===== DODAWANIE ŹRÓDŁA =====
    addSourceForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = addSourceForm.querySelector('input[name="name"]').value.trim();

        if (!name) {
            showNotification('Podaj nazwę źródła', 'error');
            return;
        }

        try {
            const response = await fetch('/settings/api/sources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Źródło zostało dodane', 'success');
                addSourceModal.style.display = 'none';
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification(result.error || 'Błąd dodawania źródła', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    });

    // ===== OBSŁUGA TABELI =====
    sourcesTableBody?.addEventListener('click', async (e) => {
        const saveBtn = e.target.closest('.btn-save');
        const deleteBtn = e.target.closest('.btn-delete');
        const upBtn = e.target.closest('.btn-up');
        const downBtn = e.target.closest('.btn-down');

        if (saveBtn) {
            const sourceId = saveBtn.dataset.id;
            const row = saveBtn.closest('tr');
            const nameInput = row.querySelector('.name-input');
            await saveSource(sourceId, nameInput.value.trim());
        }

        if (deleteBtn) {
            const sourceId = deleteBtn.dataset.id;
            const row = deleteBtn.closest('tr');
            const name = row.querySelector('.name-input')?.value || 'to źródło';

            if (confirm(`Czy na pewno chcesz usunąć "${name}"?`)) {
                await deleteSource(sourceId, row);
            }
        }

        if (upBtn && !upBtn.disabled) {
            const sourceId = upBtn.dataset.id;
            await moveSource(sourceId, 'up');
        }

        if (downBtn && !downBtn.disabled) {
            const sourceId = downBtn.dataset.id;
            await moveSource(sourceId, 'down');
        }
    });

    // Enter w input zapisuje
    sourcesTableBody?.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('name-input')) {
            e.preventDefault();
            const sourceId = e.target.dataset.id;
            await saveSource(sourceId, e.target.value.trim());
        }
    });

    // Checkbox "Pomiń walidację" - zmiana natychmiastowa
    sourcesTableBody?.addEventListener('change', async (e) => {
        if (e.target.classList.contains('skip-validation-checkbox')) {
            const sourceId = e.target.dataset.id;
            const skipValidation = e.target.checked;
            await updateSkipValidation(sourceId, skipValidation);
        }
    });

    // ===== API FUNCTIONS =====
    async function saveSource(sourceId, name) {
        if (!name) {
            showNotification('Nazwa nie może być pusta', 'error');
            return;
        }

        const row = document.querySelector(`tr[data-id="${sourceId}"]`);
        if (!row) return;

        // Pobierz zaznaczone role
        const roleCheckboxes = row.querySelectorAll('.source-role-checkbox:checked');
        const allowedRoles = Array.from(roleCheckboxes).map(cb => cb.value);

        try {
            const response = await fetch(`/settings/api/sources/${sourceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    allowed_roles: allowedRoles.length > 0 ? allowedRoles : null
                })
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Zapisano', 'success');
                if (row) {
                    row.style.backgroundColor = '#dcfce7';
                    setTimeout(() => row.style.backgroundColor = '', 500);
                }
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function deleteSource(sourceId, row) {
        try {
            const response = await fetch(`/settings/api/sources/${sourceId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Źródło usunięte', 'success');
                row.style.backgroundColor = '#fee2e2';
                row.style.opacity = '0';
                row.style.transition = 'opacity 0.3s';
                setTimeout(() => {
                    row.remove();
                    updateOrderButtons();
                }, 300);
            } else {
                showNotification(result.error || 'Błąd usuwania', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function moveSource(sourceId, direction) {
        try {
            const response = await fetch(`/settings/api/sources/${sourceId}/move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction })
            });

            const result = await response.json();

            if (result.success) {
                location.reload();
            } else {
                showNotification(result.error || 'Błąd zmiany kolejności', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function updateSkipValidation(sourceId, skipValidation) {
        try {
            const response = await fetch(`/settings/api/sources/${sourceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ skip_contact_validation: skipValidation })
            });

            const result = await response.json();

            if (result.success) {
                showNotification(skipValidation ? 'Walidacja wyłączona' : 'Walidacja włączona', 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    // ===== AKTUALIZACJA PRZYCISKÓW KOLEJNOŚCI =====
    function updateOrderButtons() {
        const rows = sourcesTableBody?.querySelectorAll('tr');
        if (!rows) return;

        rows.forEach((row, index) => {
            const upBtn = row.querySelector('.btn-up');
            const downBtn = row.querySelector('.btn-down');

            if (upBtn) {
                upBtn.disabled = (index === 0);
                upBtn.classList.toggle('disabled', index === 0);
            }
            if (downBtn) {
                downBtn.disabled = (index === rows.length - 1);
                downBtn.classList.toggle('disabled', index === rows.length - 1);
            }
        });
    }

    // Inicjalizacja
    updateOrderButtons();

    // ===== NOTYFIKACJE =====
    function showNotification(message, type = 'info') {
        document.querySelectorAll('.settings-notification').forEach(n => n.remove());

        const notification = document.createElement('div');
        notification.className = `settings-notification settings-notification-${type}`;
        notification.innerHTML = `
            <span>${message}</span>
            <button class="notification-close">&times;</button>
        `;

        Object.assign(notification.style, {
            position: 'fixed',
            top: '20px',
            right: '20px',
            padding: '12px 20px',
            borderRadius: '8px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            zIndex: '9999',
            animation: 'slideIn 0.3s ease',
            backgroundColor: type === 'success' ? '#22c55e' : type === 'error' ? '#ef4444' : '#3b82f6',
            color: 'white',
            fontWeight: '500'
        });

        document.body.appendChild(notification);

        notification.querySelector('.notification-close').addEventListener('click', () => {
            notification.remove();
        });

        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transition = 'opacity 0.3s';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // CSS animacje
    if (!document.getElementById('settings-animations')) {
        const style = document.createElement('style');
        style.id = 'settings-animations';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100px); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            .notification-close {
                background: none;
                border: none;
                color: white;
                font-size: 20px;
                cursor: pointer;
                padding: 0;
                line-height: 1;
            }
        `;
        document.head.appendChild(style);
    }

    // =============================================
    // ŹRÓDŁA ZAMÓWIEŃ BASELINKER
    // =============================================

    const orderSourcesTableBody = document.getElementById('orderSourcesTableBody');
    const syncOrderSourcesBtn = document.getElementById('syncOrderSourcesBtn');

    // Synchronizacja źródeł z Baselinker
    syncOrderSourcesBtn?.addEventListener('click', async () => {
        syncOrderSourcesBtn.disabled = true;
        syncOrderSourcesBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" class="spin">
                <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
            </svg>
            Synchronizuję...
        `;

        try {
            const response = await fetch('/settings/api/order-sources/sync', {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                showNotification(`Zsynchronizowano ${result.synced} źródeł`, 'success');
                setTimeout(() => location.reload(), 1000);
            } else {
                showNotification(result.error || 'Błąd synchronizacji', 'error');
                resetSyncButton();
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
            resetSyncButton();
        }
    });

    function resetSyncButton() {
        if (syncOrderSourcesBtn) {
            syncOrderSourcesBtn.disabled = false;
            syncOrderSourcesBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                </svg>
                Synchronizuj z Baselinker
            `;
        }
    }

    // Obsługa tabeli źródeł zamówień
    orderSourcesTableBody?.addEventListener('click', async (e) => {
        const saveBtn = e.target.closest('.btn-save-order');
        const deleteBtn = e.target.closest('.btn-delete-order');
        const upBtn = e.target.closest('.btn-up-order');
        const downBtn = e.target.closest('.btn-down-order');

        if (saveBtn) {
            const dbId = saveBtn.dataset.dbId;
            await saveOrderSource(dbId);
        }

        if (deleteBtn) {
            const dbId = deleteBtn.dataset.dbId;
            const name = deleteBtn.dataset.name;
            if (confirm(`Czy na pewno chcesz usunąć źródło "${name}"?`)) {
                await deleteOrderSource(dbId);
            }
        }

        if (upBtn && !upBtn.disabled) {
            const dbId = upBtn.dataset.dbId;
            await moveOrderSource(dbId, 'up');
        }

        if (downBtn && !downBtn.disabled) {
            const dbId = downBtn.dataset.dbId;
            await moveOrderSource(dbId, 'down');
        }
    });

    async function saveOrderSource(dbId) {
        const row = document.querySelector(`tr[data-db-id="${dbId}"]`);
        if (!row) return;

        // Pobierz zaznaczone role
        const roleCheckboxes = row.querySelectorAll('.role-checkbox:checked');
        const allowedRoles = Array.from(roleCheckboxes).map(cb => cb.value);

        try {
            const response = await fetch(`/settings/api/order-sources/${dbId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    allowed_roles: allowedRoles.length > 0 ? allowedRoles : null
                })
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Zapisano', 'success');
                row.style.backgroundColor = '#dcfce7';
                setTimeout(() => row.style.backgroundColor = '', 500);
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function deleteOrderSource(dbId) {
        try {
            const response = await fetch(`/settings/api/order-sources/${dbId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Źródło usunięte', 'success');
                const row = document.querySelector(`tr[data-db-id="${dbId}"]`);
                if (row) {
                    row.style.backgroundColor = '#fee2e2';
                    row.style.opacity = '0';
                    row.style.transition = 'opacity 0.3s';
                    setTimeout(() => {
                        row.remove();
                        updateOrderSourceButtons();
                    }, 300);
                }
            } else {
                showNotification(result.error || 'Błąd usuwania', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function moveOrderSource(dbId, direction) {
        try {
            const response = await fetch(`/settings/api/order-sources/${dbId}/move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction })
            });

            const result = await response.json();

            if (result.success) {
                location.reload();
            } else {
                showNotification(result.error || 'Błąd zmiany kolejności', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    // Aktualizacja przycisków kolejności dla źródeł zamówień
    function updateOrderSourceButtons() {
        const rows = orderSourcesTableBody?.querySelectorAll('tr');
        if (!rows) return;

        rows.forEach((row, index) => {
            const upBtn = row.querySelector('.btn-up-order');
            const downBtn = row.querySelector('.btn-down-order');

            if (upBtn) {
                upBtn.disabled = (index === 0);
                upBtn.classList.toggle('disabled', index === 0);
            }
            if (downBtn) {
                downBtn.disabled = (index === rows.length - 1);
                downBtn.classList.toggle('disabled', index === rows.length - 1);
            }
        });
    }

    // Inicjalizacja przycisków kolejności dla źródeł zamówień
    updateOrderSourceButtons();

    // Dodaj style dla animacji spin
    if (!document.getElementById('settings-extra-styles')) {
        const extraStyle = document.createElement('style');
        extraStyle.id = 'settings-extra-styles';
        extraStyle.textContent = `
            @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            .spin {
                animation: spin 1s linear infinite;
            }
        `;
        document.head.appendChild(extraStyle);
    }
});
