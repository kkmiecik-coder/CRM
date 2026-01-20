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

    // =============================================
    // KALKULATOR - CENNIK
    // =============================================

    const pricesTableBody = document.getElementById('pricesTableBody');
    const addPriceBtn = document.getElementById('addPriceBtn');
    const addPriceModal = document.getElementById('addPriceModal');
    const closeAddPriceModal = document.getElementById('closeAddPriceModal');
    const cancelAddPrice = document.getElementById('cancelAddPrice');
    const addPriceForm = document.getElementById('addPriceForm');

    // Filtry
    const filterSpecies = document.getElementById('filterSpecies');
    const filterTechnology = document.getElementById('filterTechnology');
    const filterWoodClass = document.getElementById('filterWoodClass');
    const clearFiltersBtn = document.getElementById('clearFiltersBtn');

    // ===== MODAL DODAWANIA CENY =====
    addPriceBtn?.addEventListener('click', () => {
        addPriceModal.style.display = 'flex';
        addPriceForm.reset();
        addPriceForm.querySelector('input[name="species"]')?.focus();
    });

    closeAddPriceModal?.addEventListener('click', () => {
        addPriceModal.style.display = 'none';
    });

    cancelAddPrice?.addEventListener('click', () => {
        addPriceModal.style.display = 'none';
    });

    addPriceModal?.addEventListener('click', (e) => {
        if (e.target === addPriceModal) {
            addPriceModal.style.display = 'none';
        }
    });

    // ===== DODAWANIE CENY =====
    addPriceForm?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(addPriceForm);
        const data = {
            species: formData.get('species'),
            technology: formData.get('technology'),
            wood_class: formData.get('wood_class'),
            thickness_min: parseFloat(formData.get('thickness_min')),
            thickness_max: parseFloat(formData.get('thickness_max')),
            length_min: parseFloat(formData.get('length_min')),
            length_max: parseFloat(formData.get('length_max')),
            price_per_m3: parseFloat(formData.get('price_per_m3'))
        };

        try {
            const response = await fetch('/settings/api/prices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Cena została dodana', 'success');
                addPriceModal.style.display = 'none';
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification(result.error || 'Błąd dodawania ceny', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    });

    // ===== OBSŁUGA TABELI CENNIKA =====
    pricesTableBody?.addEventListener('click', async (e) => {
        const saveBtn = e.target.closest('.btn-save-price');
        const deleteBtn = e.target.closest('.btn-delete-price');

        if (saveBtn) {
            const priceId = saveBtn.dataset.id;
            await savePrice(priceId);
        }

        if (deleteBtn) {
            const priceId = deleteBtn.dataset.id;
            const row = deleteBtn.closest('tr');
            const species = row.querySelector('.species-input')?.value || '';
            const technology = row.querySelector('.technology-input')?.value || '';
            const woodClass = row.querySelector('.wood-class-input')?.value || '';

            if (confirm(`Czy na pewno chcesz usunąć cenę "${species} ${technology} ${woodClass}"?`)) {
                await deletePrice(priceId, row);
            }
        }
    });

    // Enter w input zapisuje
    pricesTableBody?.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('price-input')) {
            e.preventDefault();
            const priceId = e.target.dataset.id;
            await savePrice(priceId);
        }
    });

    async function savePrice(priceId) {
        const row = document.querySelector(`tr[data-id="${priceId}"]`);
        if (!row) return;

        const data = {
            species: row.querySelector('.species-input')?.value.trim(),
            technology: row.querySelector('.technology-input')?.value.trim(),
            wood_class: row.querySelector('.wood-class-input')?.value.trim(),
            thickness_min: parseFloat(row.querySelector('[data-field="thickness_min"]')?.value) || 0,
            thickness_max: parseFloat(row.querySelector('[data-field="thickness_max"]')?.value) || 0,
            length_min: parseFloat(row.querySelector('[data-field="length_min"]')?.value) || 0,
            length_max: parseFloat(row.querySelector('[data-field="length_max"]')?.value) || 0,
            price_per_m3: parseFloat(row.querySelector('[data-field="price_per_m3"]')?.value) || 0
        };

        // Walidacja
        if (!data.species || !data.technology || !data.wood_class) {
            showNotification('Gatunek, technologia i klasa są wymagane', 'error');
            return;
        }

        try {
            const response = await fetch(`/settings/api/prices/${priceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Zapisano', 'success');
                row.style.backgroundColor = '#dcfce7';
                setTimeout(() => row.style.backgroundColor = '', 500);

                // Aktualizuj atrybuty data dla filtrów
                row.dataset.species = data.species;
                row.dataset.technology = data.technology;
                row.dataset.woodClass = data.wood_class;
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function deletePrice(priceId, row) {
        try {
            const response = await fetch(`/settings/api/prices/${priceId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Cena usunięta', 'success');
                row.style.backgroundColor = '#fee2e2';
                row.style.opacity = '0';
                row.style.transition = 'opacity 0.3s';
                setTimeout(() => row.remove(), 300);
            } else {
                showNotification(result.error || 'Błąd usuwania', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    // ===== FILTRY =====
    function applyFilters() {
        const speciesValue = filterSpecies?.value.toLowerCase() || '';
        const technologyValue = filterTechnology?.value.toLowerCase() || '';
        const woodClassValue = filterWoodClass?.value.toLowerCase() || '';

        const rows = pricesTableBody?.querySelectorAll('tr');
        if (!rows) return;

        rows.forEach(row => {
            const species = (row.dataset.species || '').toLowerCase();
            const technology = (row.dataset.technology || '').toLowerCase();
            const woodClass = (row.dataset.woodClass || '').toLowerCase();

            const matchSpecies = !speciesValue || species === speciesValue;
            const matchTechnology = !technologyValue || technology === technologyValue;
            const matchWoodClass = !woodClassValue || woodClass === woodClassValue;

            row.style.display = (matchSpecies && matchTechnology && matchWoodClass) ? '' : 'none';
        });
    }

    filterSpecies?.addEventListener('change', applyFilters);
    filterTechnology?.addEventListener('change', applyFilters);
    filterWoodClass?.addEventListener('change', applyFilters);

    clearFiltersBtn?.addEventListener('click', () => {
        if (filterSpecies) filterSpecies.value = '';
        if (filterTechnology) filterTechnology.value = '';
        if (filterWoodClass) filterWoodClass.value = '';
        applyFilters();
    });

    // =============================================
    // CENNIK WYKOŃCZENIA
    // =============================================

    const finishingPricesTableBody = document.getElementById('finishingPricesTableBody');

    finishingPricesTableBody?.addEventListener('click', async (e) => {
        const saveBtn = e.target.closest('.btn-save-finishing');

        if (saveBtn) {
            const priceId = saveBtn.dataset.id;
            await saveFinishingPrice(priceId);
        }
    });

    // Enter w input zapisuje
    finishingPricesTableBody?.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('price-input')) {
            e.preventDefault();
            const priceId = e.target.dataset.id;
            await saveFinishingPrice(priceId);
        }
    });

    async function saveFinishingPrice(priceId) {
        const row = document.querySelector(`#finishingPricesTableBody tr[data-id="${priceId}"]`);
        if (!row) return;

        const priceNetto = parseFloat(row.querySelector('[data-field="price_netto"]')?.value) || 0;

        try {
            const response = await fetch(`/settings/api/finishing-prices/${priceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ price_netto: priceNetto })
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

    // =============================================
    // CENNIK OBRÓBKI KRAWĘDZI
    // =============================================

    const edgeOptionsTableBody = document.getElementById('edgeOptionsTableBody');

    edgeOptionsTableBody?.addEventListener('click', async (e) => {
        const saveBtn = e.target.closest('.btn-save-edge');

        if (saveBtn) {
            const optionId = saveBtn.dataset.id;
            await saveEdgeOption(optionId);
        }
    });

    // Enter w input zapisuje
    edgeOptionsTableBody?.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('price-input')) {
            e.preventDefault();
            const optionId = e.target.dataset.id;
            await saveEdgeOption(optionId);
        }
    });

    async function saveEdgeOption(optionId) {
        const row = document.querySelector(`#edgeOptionsTableBody tr[data-id="${optionId}"]`);
        if (!row) return;

        const data = {
            price_per_mb: parseFloat(row.querySelector('[data-field="price_per_mb"]')?.value) || 0,
            corner_price: parseFloat(row.querySelector('[data-field="corner_price"]')?.value) || 0
        };

        // Pola R tylko jeśli nie są disabled
        const rMinInput = row.querySelector('[data-field="r_min"]');
        const rMaxInput = row.querySelector('[data-field="r_max"]');
        const rDefaultInput = row.querySelector('[data-field="r_default"]');

        if (rMinInput && !rMinInput.disabled) {
            data.r_min = rMinInput.value ? parseInt(rMinInput.value) : null;
        }
        if (rMaxInput && !rMaxInput.disabled) {
            data.r_max = rMaxInput.value ? parseInt(rMaxInput.value) : null;
        }
        if (rDefaultInput && !rDefaultInput.disabled) {
            data.r_default = rDefaultInput.value ? parseInt(rDefaultInput.value) : null;
        }

        try {
            const response = await fetch(`/settings/api/edge-options/${optionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
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
});
