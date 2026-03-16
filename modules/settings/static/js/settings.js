/**
 * Ustawienia aplikacji - JavaScript
 * ==================================
 * Wersja z bulk save - jeden przycisk "Zapisz zmiany" na dole każdej sekcji
 */

document.addEventListener('DOMContentLoaded', function() {

    // =============================================
    // SYSTEM ŚLEDZENIA ZMIAN - BULK SAVE
    // =============================================

    // Store dla zmienionych rekordów per sekcja
    const changedRecords = {
        orderSources: new Map(),    // id -> { allowed_roles: [...] }
        prices: new Map(),          // id -> { species, technology, ... }
        finishingTree: new Map(),   // id -> { name, code, price_netto }
        edgeOptions: new Map(),     // id -> { price_per_mb, corner_price, ... }
        quoteSources: new Map()     // id -> { name, allowed_roles, skip_contact_validation }
    };

    // Oryginalne wartości (do porównania i resetu)
    const originalValues = {
        orderSources: new Map(),
        prices: new Map(),
        finishingTree: new Map(),
        edgeOptions: new Map(),
        quoteSources: new Map()
    };

    // =============================================
    // INICJALIZACJA ORYGINALNYCH WARTOŚCI
    // =============================================

    function initializeOriginalValues() {
        // Order Sources
        document.querySelectorAll('#orderSourcesTableBody tr').forEach(row => {
            const id = row.dataset.dbId;
            if (id) {
                const roleCheckboxes = row.querySelectorAll('.role-checkbox');
                const allowedRoles = Array.from(roleCheckboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                originalValues.orderSources.set(id, { allowed_roles: [...allowedRoles] });
            }
        });

        // Prices
        document.querySelectorAll('#pricesTableBody tr').forEach(row => {
            const id = row.dataset.id;
            if (id) {
                originalValues.prices.set(id, {
                    species: row.querySelector('.species-input')?.value || '',
                    technology: row.querySelector('.technology-input')?.value || '',
                    wood_class: row.querySelector('.wood-class-input')?.value || '',
                    thickness_min: row.querySelector('[data-field="thickness_min"]')?.value || '',
                    thickness_max: row.querySelector('[data-field="thickness_max"]')?.value || '',
                    length_min: row.querySelector('[data-field="length_min"]')?.value || '',
                    length_max: row.querySelector('[data-field="length_max"]')?.value || '',
                    width_min: row.querySelector('[data-field="width_min"]')?.value || '',
                    width_max: row.querySelector('[data-field="width_max"]')?.value || '',
                    price_per_m3: row.querySelector('[data-field="price_per_m3"]')?.value || ''
                });
            }
        });

        // Finishing Tree
        document.querySelectorAll('#finishingTreeTableBody tr').forEach(row => {
            const id = row.dataset.id;
            if (id) {
                originalValues.finishingTree.set(id, {
                    name: row.querySelector('.tree-name-input')?.value || '',
                    code: row.querySelector('.code-input')?.value || '',
                    price_netto: row.querySelector('.price-value-input')?.value || ''
                });
            }
        });

        // Edge Options
        document.querySelectorAll('#edgeOptionsTableBody tr').forEach(row => {
            const id = row.dataset.id;
            if (id) {
                originalValues.edgeOptions.set(id, {
                    price_per_mb: row.querySelector('[data-field="price_per_mb"]')?.value || '',
                    corner_price: row.querySelector('[data-field="corner_price"]')?.value || '',
                    r_min: row.querySelector('[data-field="r_min"]')?.value || '',
                    r_max: row.querySelector('[data-field="r_max"]')?.value || '',
                    r_default: row.querySelector('[data-field="r_default"]')?.value || '',
                    chamfer_angles: row.querySelector('[data-field="chamfer_angles"]')?.value || '',
                    angle_default: row.querySelector('[data-field="angle_default"]')?.value || ''
                });
            }
        });

        // Quote Sources
        document.querySelectorAll('#sourcesTableBody tr').forEach(row => {
            const id = row.dataset.id;
            if (id) {
                const roleCheckboxes = row.querySelectorAll('.source-role-checkbox');
                const allowedRoles = Array.from(roleCheckboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                const skipValidation = row.querySelector('.skip-validation-checkbox')?.checked || false;
                originalValues.quoteSources.set(id, {
                    name: row.querySelector('.name-input')?.value || '',
                    allowed_roles: [...allowedRoles],
                    skip_contact_validation: skipValidation
                });
            }
        });
    }

    // =============================================
    // FUNKCJE POMOCNICZE DLA ŚLEDZENIA ZMIAN
    // =============================================

    function arraysEqual(a, b) {
        if (a.length !== b.length) return false;
        const sortedA = [...a].sort();
        const sortedB = [...b].sort();
        return sortedA.every((val, idx) => val === sortedB[idx]);
    }

    function normalizeValue(val) {
        // Normalizuje wartość do porównania
        if (val === null || val === undefined) return '';
        if (typeof val === 'boolean') return val;
        if (Array.isArray(val)) return val;
        // Usuń białe znaki z początku i końca, zamień na string
        return String(val).trim();
    }

    function isNumericString(str) {
        // Sprawdza czy string reprezentuje POJEDYNCZĄ liczbę (obsługuje przecinek jako separator dziesiętny)
        // Nie traktuje list wartości (np. "30, 45, 60") jako liczb
        if (typeof str !== 'string') return false;
        const trimmed = str.trim();
        // Jeśli zawiera przecinek z spacją lub więcej niż jeden przecinek - to lista, nie liczba
        if (trimmed.includes(', ') || (trimmed.match(/,/g) || []).length > 1) return false;
        const normalized = trimmed.replace(',', '.');
        return !isNaN(normalized) && !isNaN(parseFloat(normalized)) && normalized !== '';
    }

    function normalizeNumeric(val) {
        // Normalizuje wartość numeryczną do porównania
        // "500,00", "500.00", "500" -> wszystkie stają się równe
        if (val === null || val === undefined || val === '') return '';
        const str = String(val).trim();
        if (str === '') return '';
        // Jeśli zawiera spację lub więcej niż jeden przecinek - to lista, nie liczba
        if (str.includes(' ') || (str.match(/,/g) || []).length > 1) {
            return str; // Zwróć jako string
        }
        const normalized = str.replace(',', '.');
        const num = parseFloat(normalized);
        // Sprawdź czy cały string to liczba (nie tylko początek)
        if (isNaN(num) || normalized !== String(num) && normalized !== num.toFixed(2) && normalized !== num.toFixed(0)) {
            // Dodatkowe sprawdzenie - czy parseFloat sparsował cały string
            if (String(num) !== normalized && num.toFixed(2) !== normalized) {
                return str;
            }
        }
        if (isNaN(num)) return str;
        return num;
    }

    function valuesEqual(a, b) {
        // Porównuje dwie wartości z normalizacją
        const normA = normalizeValue(a);
        const normB = normalizeValue(b);

        if (Array.isArray(normA) && Array.isArray(normB)) {
            return arraysEqual(normA, normB);
        }
        if (typeof normA === 'boolean' || typeof normB === 'boolean') {
            return normA === normB;
        }

        // Dla wartości numerycznych, porównuj jako liczby
        const isNumA = isNumericString(normA);
        const isNumB = isNumericString(normB);

        if (isNumA || isNumB) {
            const numA = normalizeNumeric(normA);
            const numB = normalizeNumeric(normB);

            // Jeśli obie są puste stringi lub obie są liczbami
            if (numA === '' && numB === '') return true;
            if (typeof numA === 'number' && typeof numB === 'number') {
                return numA === numB;
            }
            // Jeśli jedna jest liczbą a druga nie - są różne
            if (typeof numA !== typeof numB) {
                return false;
            }
        }

        return normA === normB;
    }

    function trackChange(section, recordId, field, newValue) {
        const original = originalValues[section].get(recordId);
        if (!original) return;

        // Pobierz aktualny stan zmian lub utwórz nowy z oryginału
        let current = changedRecords[section].get(recordId);
        if (!current) {
            // Głęboka kopia oryginału
            current = {};
            for (const key of Object.keys(original)) {
                if (Array.isArray(original[key])) {
                    current[key] = [...original[key]];
                } else {
                    current[key] = original[key];
                }
            }
        }

        // Aktualizuj pole z nową wartością
        if (Array.isArray(newValue)) {
            current[field] = [...newValue];
        } else if (typeof newValue === 'boolean') {
            current[field] = newValue;
        } else {
            current[field] = newValue;
        }

        // Sprawdź czy wszystkie pola są takie same jak oryginalne
        let hasChanges = false;
        for (const key of Object.keys(original)) {
            if (!valuesEqual(current[key], original[key])) {
                hasChanges = true;
                break;
            }
        }

        if (hasChanges) {
            changedRecords[section].set(recordId, current);
        } else {
            changedRecords[section].delete(recordId);
        }

        updateSaveFooter(section);
        updateRowVisual(section, recordId);
    }

    function updateRowVisual(section, recordId) {
        let row;
        if (section === 'orderSources') {
            row = document.querySelector(`#orderSourcesTableBody tr[data-db-id="${recordId}"]`);
        } else if (section === 'prices') {
            row = document.querySelector(`#pricesTableBody tr[data-id="${recordId}"]`);
        } else if (section === 'finishingTree') {
            row = document.querySelector(`#finishingTreeTableBody tr[data-id="${recordId}"]`);
        } else if (section === 'edgeOptions') {
            row = document.querySelector(`#edgeOptionsTableBody tr[data-id="${recordId}"]`);
        } else if (section === 'quoteSources') {
            row = document.querySelector(`#sourcesTableBody tr[data-id="${recordId}"]`);
        }

        if (row) {
            if (changedRecords[section].has(recordId)) {
                row.classList.add('row-changed');
            } else {
                row.classList.remove('row-changed');
            }
        }
    }

    function updateSaveFooter(section) {
        const footerMap = {
            orderSources: 'saveFooterOrderSources',
            prices: 'saveFooterPrices',
            finishingTree: 'saveFooterFinishingTree',
            edgeOptions: 'saveFooterEdgeOptions',
            quoteSources: 'saveFooterQuoteSources'
        };
        const countMap = {
            orderSources: 'changesCountOrderSources',
            prices: 'changesCountPrices',
            finishingTree: 'changesCountFinishingTree',
            edgeOptions: 'changesCountEdgeOptions',
            quoteSources: 'changesCountQuoteSources'
        };

        const footer = document.getElementById(footerMap[section]);
        const countEl = document.getElementById(countMap[section]);
        const count = changedRecords[section].size;

        if (footer && countEl) {
            countEl.textContent = count;
            if (count > 0) {
                footer.classList.add('visible');
            } else {
                footer.classList.remove('visible');
            }
        }
    }

    function discardChanges(section) {
        changedRecords[section].forEach((_, recordId) => {
            const original = originalValues[section].get(recordId);
            if (!original) return;

            let row;
            if (section === 'orderSources') {
                row = document.querySelector(`#orderSourcesTableBody tr[data-db-id="${recordId}"]`);
                if (row) {
                    row.querySelectorAll('.role-checkbox').forEach(cb => {
                        cb.checked = original.allowed_roles.includes(cb.value);
                    });
                }
            } else if (section === 'prices') {
                row = document.querySelector(`#pricesTableBody tr[data-id="${recordId}"]`);
                if (row) {
                    row.querySelector('.species-input').value = original.species;
                    row.querySelector('.technology-input').value = original.technology;
                    row.querySelector('.wood-class-input').value = original.wood_class;
                    row.querySelector('[data-field="thickness_min"]').value = original.thickness_min;
                    row.querySelector('[data-field="thickness_max"]').value = original.thickness_max;
                    row.querySelector('[data-field="length_min"]').value = original.length_min;
                    row.querySelector('[data-field="length_max"]').value = original.length_max;
                    row.querySelector('[data-field="price_per_m3"]').value = original.price_per_m3;
                }
            } else if (section === 'finishingTree') {
                row = document.querySelector(`#finishingTreeTableBody tr[data-id="${recordId}"]`);
                if (row) {
                    row.querySelector('.tree-name-input').value = original.name;
                    row.querySelector('.code-input').value = original.code;
                    row.querySelector('.price-value-input').value = original.price_netto;
                }
            } else if (section === 'edgeOptions') {
                row = document.querySelector(`#edgeOptionsTableBody tr[data-id="${recordId}"]`);
                if (row) {
                    const pmb = row.querySelector('[data-field="price_per_mb"]');
                    const cp = row.querySelector('[data-field="corner_price"]');
                    const rmin = row.querySelector('[data-field="r_min"]');
                    const rmax = row.querySelector('[data-field="r_max"]');
                    const rdef = row.querySelector('[data-field="r_default"]');
                    if (pmb) pmb.value = original.price_per_mb;
                    if (cp) cp.value = original.corner_price;
                    if (rmin && !rmin.disabled) rmin.value = original.r_min;
                    if (rmax && !rmax.disabled) rmax.value = original.r_max;
                    if (rdef && !rdef.disabled) rdef.value = original.r_default;
                }
            } else if (section === 'quoteSources') {
                row = document.querySelector(`#sourcesTableBody tr[data-id="${recordId}"]`);
                if (row) {
                    row.querySelector('.name-input').value = original.name;
                    row.querySelectorAll('.source-role-checkbox').forEach(cb => {
                        cb.checked = original.allowed_roles.includes(cb.value);
                    });
                    const skipCb = row.querySelector('.skip-validation-checkbox');
                    if (skipCb) skipCb.checked = original.skip_contact_validation;
                }
            }

            if (row) {
                row.classList.remove('row-changed');
            }
        });

        changedRecords[section].clear();
        updateSaveFooter(section);
        showNotification('Zmiany zostały odrzucone', 'info');
    }

    // =============================================
    // BULK SAVE FUNCTIONS
    // =============================================

    async function bulkSaveOrderSources() {
        const items = Array.from(changedRecords.orderSources.entries())
            .map(([id, data]) => ({ id: parseInt(id), ...data }));

        if (items.length === 0) return;

        try {
            const response = await fetch('/settings/api/order-sources/bulk', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });

            const result = await response.json();

            if (result.success) {
                // Zaktualizuj oryginalne wartości
                items.forEach(item => {
                    const current = changedRecords.orderSources.get(String(item.id));
                    if (current) {
                        originalValues.orderSources.set(String(item.id), { ...current });
                    }
                    const row = document.querySelector(`#orderSourcesTableBody tr[data-db-id="${item.id}"]`);
                    if (row) row.classList.remove('row-changed');
                });
                changedRecords.orderSources.clear();
                updateSaveFooter('orderSources');
                showNotification(`Zapisano ${result.updated} źródeł zamówień`, 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function bulkSavePrices() {
        const items = Array.from(changedRecords.prices.entries())
            .map(([id, data]) => ({
                id: parseInt(id),
                species: data.species,
                technology: data.technology,
                wood_class: data.wood_class,
                thickness_min: parseFloat(data.thickness_min) || 0,
                thickness_max: parseFloat(data.thickness_max) || 0,
                length_min: parseFloat(data.length_min) || 0,
                length_max: parseFloat(data.length_max) || 0,
                width_min: parseFloat(data.width_min) || 0,
                width_max: parseFloat(data.width_max) || 0,
                price_per_m3: parseFloat(data.price_per_m3) || 0
            }));

        if (items.length === 0) return;

        try {
            const response = await fetch('/settings/api/prices/bulk', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });

            const result = await response.json();

            if (result.success) {
                items.forEach(item => {
                    const current = changedRecords.prices.get(String(item.id));
                    if (current) {
                        originalValues.prices.set(String(item.id), { ...current });
                    }
                    const row = document.querySelector(`#pricesTableBody tr[data-id="${item.id}"]`);
                    if (row) {
                        row.classList.remove('row-changed');
                        // Aktualizuj data atrybuty dla filtrów
                        row.dataset.species = item.species;
                        row.dataset.technology = item.technology;
                        row.dataset.woodClass = item.wood_class;
                    }
                });
                changedRecords.prices.clear();
                updateSaveFooter('prices');
                showNotification(`Zapisano ${result.updated} cen`, 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function bulkSaveFinishingTree() {
        const items = Array.from(changedRecords.finishingTree.entries())
            .map(([id, data]) => ({
                id: parseInt(id),
                name: data.name,
                code: data.code || null,
                price_netto: data.price_netto ? parseFloat(data.price_netto) : null
            }));

        if (items.length === 0) return;

        try {
            const response = await fetch('/settings/api/finishing-options/bulk', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });

            const result = await response.json();

            if (result.success) {
                items.forEach(item => {
                    const current = changedRecords.finishingTree.get(String(item.id));
                    if (current) {
                        originalValues.finishingTree.set(String(item.id), { ...current });
                    }
                    const row = document.querySelector(`#finishingTreeTableBody tr[data-id="${item.id}"]`);
                    if (row) row.classList.remove('row-changed');
                });
                changedRecords.finishingTree.clear();
                updateSaveFooter('finishingTree');
                showNotification(`Zapisano ${result.updated} opcji wykończeń. Odśwież stronę aby zobaczyć zaktualizowane ceny efektywne.`, 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function bulkSaveEdgeOptions() {
        const items = Array.from(changedRecords.edgeOptions.entries())
            .map(([id, data]) => {
                // Parsuj kąty z stringa do tablicy liczb
                let chamferAngles = null;
                if (data.chamfer_angles && data.chamfer_angles.trim()) {
                    chamferAngles = data.chamfer_angles
                        .split(',')
                        .map(a => parseInt(a.trim()))
                        .filter(a => !isNaN(a) && a > 0 && a < 90);
                    if (chamferAngles.length === 0) chamferAngles = null;
                }

                return {
                    id: parseInt(id),
                    price_per_mb: parseFloat(data.price_per_mb) || 0,
                    corner_price: parseFloat(data.corner_price) || 0,
                    r_min: data.r_min ? parseInt(data.r_min) : null,
                    r_max: data.r_max ? parseInt(data.r_max) : null,
                    r_default: data.r_default ? parseInt(data.r_default) : null,
                    chamfer_angles: chamferAngles,
                    angle_default: data.angle_default ? parseInt(data.angle_default) : null
                };
            });

        if (items.length === 0) return;

        try {
            const response = await fetch('/settings/api/edge-options/bulk', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });

            const result = await response.json();

            if (result.success) {
                items.forEach(item => {
                    const current = changedRecords.edgeOptions.get(String(item.id));
                    if (current) {
                        originalValues.edgeOptions.set(String(item.id), { ...current });
                    }
                    const row = document.querySelector(`#edgeOptionsTableBody tr[data-id="${item.id}"]`);
                    if (row) row.classList.remove('row-changed');
                });
                changedRecords.edgeOptions.clear();
                updateSaveFooter('edgeOptions');
                showNotification(`Zapisano ${result.updated} opcji krawędzi`, 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function bulkSaveQuoteSources() {
        const items = Array.from(changedRecords.quoteSources.entries())
            .map(([id, data]) => ({
                id: parseInt(id),
                name: data.name,
                allowed_roles: data.allowed_roles.length > 0 ? data.allowed_roles : null,
                skip_contact_validation: data.skip_contact_validation
            }));

        if (items.length === 0) return;

        try {
            const response = await fetch('/settings/api/sources/bulk', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });

            const result = await response.json();

            if (result.success) {
                items.forEach(item => {
                    const current = changedRecords.quoteSources.get(String(item.id));
                    if (current) {
                        originalValues.quoteSources.set(String(item.id), { ...current });
                    }
                    const row = document.querySelector(`#sourcesTableBody tr[data-id="${item.id}"]`);
                    if (row) row.classList.remove('row-changed');
                });
                changedRecords.quoteSources.clear();
                updateSaveFooter('quoteSources');
                showNotification(`Zapisano ${result.updated} źródeł wycen`, 'success');
            } else {
                showNotification(result.error || 'Błąd zapisu', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    // =============================================
    // EVENT LISTENERS DLA SAVE FOOTERS
    // =============================================

    // Order Sources
    document.getElementById('saveAllBtnOrderSources')?.addEventListener('click', bulkSaveOrderSources);
    document.getElementById('discardChangesOrderSources')?.addEventListener('click', () => discardChanges('orderSources'));

    // Prices
    document.getElementById('saveAllBtnPrices')?.addEventListener('click', bulkSavePrices);
    document.getElementById('discardChangesPrices')?.addEventListener('click', () => discardChanges('prices'));

    // Finishing Tree
    document.getElementById('saveAllBtnFinishingTree')?.addEventListener('click', bulkSaveFinishingTree);
    document.getElementById('discardChangesFinishingTree')?.addEventListener('click', () => discardChanges('finishingTree'));

    // Edge Options
    document.getElementById('saveAllBtnEdgeOptions')?.addEventListener('click', bulkSaveEdgeOptions);
    document.getElementById('discardChangesEdgeOptions')?.addEventListener('click', () => discardChanges('edgeOptions'));

    // Round Shape Surcharge
    document.getElementById('saveRoundSurchargeBtn')?.addEventListener('click', async () => {
        const input = document.getElementById('roundSurchargeNetto');
        const statusEl = document.getElementById('roundSurchargeSaveStatus');
        if (!input) return;

        const value = parseFloat(input.value);
        if (isNaN(value) || value < 0) {
            statusEl.textContent = 'Nieprawidłowa wartość!';
            statusEl.style.color = '#dc3545';
            statusEl.style.display = 'inline';
            setTimeout(() => statusEl.style.display = 'none', 3000);
            return;
        }

        try {
            const resp = await fetch('/settings/api/calculator-settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ round_shape_surcharge_netto: value })
            });
            const data = await resp.json();
            if (data.success) {
                statusEl.textContent = 'Zapisano!';
                statusEl.style.color = '#28a745';
            } else {
                statusEl.textContent = data.error || 'Błąd zapisu';
                statusEl.style.color = '#dc3545';
            }
            statusEl.style.display = 'inline';
            setTimeout(() => statusEl.style.display = 'none', 3000);
        } catch (err) {
            statusEl.textContent = 'Błąd połączenia';
            statusEl.style.color = '#dc3545';
            statusEl.style.display = 'inline';
            setTimeout(() => statusEl.style.display = 'none', 3000);
        }
    });

    // Quote Sources
    document.getElementById('saveAllBtnQuoteSources')?.addEventListener('click', bulkSaveQuoteSources);
    document.getElementById('discardChangesQuoteSources')?.addEventListener('click', () => discardChanges('quoteSources'));

    // =============================================
    // OSTRZEŻENIE PRZY OPUSZCZANIU STRONY
    // =============================================

    window.addEventListener('beforeunload', (e) => {
        const totalChanges =
            changedRecords.orderSources.size +
            changedRecords.prices.size +
            changedRecords.finishingTree.size +
            changedRecords.edgeOptions.size +
            changedRecords.quoteSources.size;

        if (totalChanges > 0) {
            e.preventDefault();
            e.returnValue = 'Masz niezapisane zmiany. Czy na pewno chcesz opuścić stronę?';
            return e.returnValue;
        }
    });

    // =============================================
    // ŹRÓDŁA WYCEN (QUOTE SOURCES)
    // =============================================

    const addSourceBtn = document.getElementById('addSourceBtn');
    const addSourceModal = document.getElementById('addSourceModal');
    const closeModalBtn = document.getElementById('closeAddSourceModal');
    const cancelBtn = document.getElementById('cancelAddSource');
    const addSourceForm = document.getElementById('addSourceForm');
    const sourcesTableBody = document.getElementById('sourcesTableBody');

    // Modal
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

    // Dodawanie źródła
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

    // Obsługa tabeli - śledzenie zmian
    sourcesTableBody?.addEventListener('input', (e) => {
        if (e.target.classList.contains('name-input')) {
            const id = e.target.dataset.id;
            const row = e.target.closest('tr');
            const roleCheckboxes = row.querySelectorAll('.source-role-checkbox');
            const allowedRoles = Array.from(roleCheckboxes).filter(cb => cb.checked).map(cb => cb.value);
            const skipValidation = row.querySelector('.skip-validation-checkbox')?.checked || false;

            trackChange('quoteSources', id, 'name', e.target.value);
        }
    });

    sourcesTableBody?.addEventListener('change', (e) => {
        if (e.target.classList.contains('source-role-checkbox')) {
            const row = e.target.closest('tr');
            const id = row.dataset.id;
            const roleCheckboxes = row.querySelectorAll('.source-role-checkbox');
            const allowedRoles = Array.from(roleCheckboxes).filter(cb => cb.checked).map(cb => cb.value);
            trackChange('quoteSources', id, 'allowed_roles', allowedRoles);
        }

        if (e.target.classList.contains('skip-validation-checkbox')) {
            const id = e.target.dataset.id;
            trackChange('quoteSources', id, 'skip_contact_validation', e.target.checked);
        }
    });

    // Usuwanie i przesuwanie (natychmiastowe)
    sourcesTableBody?.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.btn-delete');
        const upBtn = e.target.closest('.btn-up');
        const downBtn = e.target.closest('.btn-down');

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

    async function deleteSource(sourceId, row) {
        try {
            const response = await fetch(`/settings/api/sources/${sourceId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Źródło usunięte', 'success');
                changedRecords.quoteSources.delete(sourceId);
                originalValues.quoteSources.delete(sourceId);
                updateSaveFooter('quoteSources');

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

    updateOrderButtons();

    // =============================================
    // ŹRÓDŁA ZAMÓWIEŃ BASELINKER
    // =============================================

    const orderSourcesTableBody = document.getElementById('orderSourcesTableBody');
    const syncOrderSourcesBtn = document.getElementById('syncOrderSourcesBtn');

    // Synchronizacja
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

    // Obsługa tabeli - śledzenie zmian
    orderSourcesTableBody?.addEventListener('change', (e) => {
        if (e.target.classList.contains('role-checkbox')) {
            const row = e.target.closest('tr');
            const id = row.dataset.dbId;
            const roleCheckboxes = row.querySelectorAll('.role-checkbox');
            const allowedRoles = Array.from(roleCheckboxes).filter(cb => cb.checked).map(cb => cb.value);
            trackChange('orderSources', id, 'allowed_roles', allowedRoles);
        }
    });

    // Usuwanie i przesuwanie
    orderSourcesTableBody?.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.btn-delete-order');
        const upBtn = e.target.closest('.btn-up-order');
        const downBtn = e.target.closest('.btn-down-order');

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

    async function deleteOrderSource(dbId) {
        try {
            const response = await fetch(`/settings/api/order-sources/${dbId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Źródło usunięte', 'success');
                changedRecords.orderSources.delete(dbId);
                originalValues.orderSources.delete(dbId);
                updateSaveFooter('orderSources');

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

    updateOrderSourceButtons();

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

    // Modal
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

    // Dodawanie ceny
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
            width_min: parseFloat(formData.get('width_min')),
            width_max: parseFloat(formData.get('width_max')),
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

    // Obsługa tabeli - śledzenie zmian
    pricesTableBody?.addEventListener('input', (e) => {
        if (e.target.classList.contains('price-input')) {
            const id = e.target.dataset.id;
            const field = e.target.dataset.field || e.target.className.match(/(\w+)-input/)?.[1];
            const row = e.target.closest('tr');

            // Zbierz wszystkie wartości z wiersza
            const data = {
                species: row.querySelector('.species-input')?.value || '',
                technology: row.querySelector('.technology-input')?.value || '',
                wood_class: row.querySelector('.wood-class-input')?.value || '',
                thickness_min: row.querySelector('[data-field="thickness_min"]')?.value || '',
                thickness_max: row.querySelector('[data-field="thickness_max"]')?.value || '',
                length_min: row.querySelector('[data-field="length_min"]')?.value || '',
                length_max: row.querySelector('[data-field="length_max"]')?.value || '',
                width_min: row.querySelector('[data-field="width_min"]')?.value || '',
                width_max: row.querySelector('[data-field="width_max"]')?.value || '',
                price_per_m3: row.querySelector('[data-field="price_per_m3"]')?.value || ''
            };

            // Użyj konkretnego pola
            const fieldName = e.target.dataset.field ||
                (e.target.classList.contains('species-input') ? 'species' :
                 e.target.classList.contains('technology-input') ? 'technology' :
                 e.target.classList.contains('wood-class-input') ? 'wood_class' : null);

            if (fieldName) {
                trackChange('prices', id, fieldName, e.target.value);
            }
        }
    });

    // Usuwanie
    pricesTableBody?.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.btn-delete-price');

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

    async function deletePrice(priceId, row) {
        try {
            const response = await fetch(`/settings/api/prices/${priceId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Cena usunięta', 'success');
                changedRecords.prices.delete(priceId);
                originalValues.prices.delete(priceId);
                updateSaveFooter('prices');

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

    // Filtry
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
    // CENNIK OBRÓBKI KRAWĘDZI
    // =============================================

    const edgeOptionsTableBody = document.getElementById('edgeOptionsTableBody');

    // Obsługa inputów numerycznych (ceny, R wartości)
    edgeOptionsTableBody?.addEventListener('input', (e) => {
        if (e.target.classList.contains('price-input') || e.target.classList.contains('number-input')) {
            const id = e.target.dataset.id;
            const field = e.target.dataset.field;
            if (id && field) {
                trackChange('edgeOptions', id, field, e.target.value);
            }
        }
    });

    // Obsługa zmiany selecta domyślnego kąta
    edgeOptionsTableBody?.addEventListener('change', (e) => {
        if (e.target.classList.contains('angle-default-select')) {
            const id = e.target.dataset.id;
            const field = e.target.dataset.field;
            if (id && field) {
                trackChange('edgeOptions', id, field, e.target.value);
            }
        }
    });

    // =============================================
    // KĄTY FAZOWANIA - TAGI UI
    // =============================================

    // Obsługa usuwania tagu kąta
    edgeOptionsTableBody?.addEventListener('click', (e) => {
        if (e.target.classList.contains('angle-remove')) {
            const tag = e.target.closest('.angle-tag');
            const container = e.target.closest('.angles-container');
            if (tag && container) {
                tag.remove();
                updateAnglesFromTags(container);
            }
        }

        // Obsługa dodawania nowego kąta
        if (e.target.classList.contains('angle-add-btn')) {
            const container = e.target.closest('.angles-container');
            const input = container?.querySelector('.angle-new-input');
            if (container && input) {
                addAngleTag(container, input);
            }
        }
    });

    // Obsługa Enter w inpucie dodawania kąta
    edgeOptionsTableBody?.addEventListener('keypress', (e) => {
        if (e.target.classList.contains('angle-new-input') && e.key === 'Enter') {
            e.preventDefault();
            const container = e.target.closest('.angles-container');
            if (container) {
                addAngleTag(container, e.target);
            }
        }
    });

    // Funkcja dodająca nowy tag kąta
    function addAngleTag(container, input) {
        const value = parseInt(input.value);
        if (isNaN(value) || value < 1 || value > 89) {
            input.classList.add('error');
            setTimeout(() => input.classList.remove('error'), 500);
            return;
        }

        // Sprawdź czy kąt już istnieje
        const existingAngles = getAnglesFromContainer(container);
        if (existingAngles.includes(value)) {
            input.value = '';
            return;
        }

        // Utwórz nowy tag
        const tag = document.createElement('span');
        tag.className = 'angle-tag';
        tag.dataset.angle = value;
        tag.innerHTML = `${value}°<button type="button" class="angle-remove">&times;</button>`;

        // Dodaj tag do kontenera
        const tagsContainer = container.querySelector('.angles-tags');
        tagsContainer.appendChild(tag);

        // Wyczyść input
        input.value = '';

        // Aktualizuj hidden input i trackChange
        updateAnglesFromTags(container);
    }

    // Funkcja pobierająca kąty z tagów
    function getAnglesFromContainer(container) {
        const tags = container.querySelectorAll('.angle-tag');
        return Array.from(tags).map(tag => parseInt(tag.dataset.angle)).filter(a => !isNaN(a));
    }

    // Funkcja aktualizująca hidden input i wywołująca trackChange
    function updateAnglesFromTags(container) {
        const id = container.dataset.id;
        const angles = getAnglesFromContainer(container);
        const anglesStr = angles.join(', ');

        // Zaktualizuj hidden input
        const hiddenInput = container.querySelector('.angles-hidden');
        if (hiddenInput) {
            hiddenInput.value = anglesStr;
        }

        // Wywołaj trackChange
        trackChange('edgeOptions', id, 'chamfer_angles', anglesStr);

        // Zaktualizuj select domyślnego kąta
        updateAngleDefaultSelect(id, angles);
    }

    // Funkcja aktualizująca select domyślnego kąta
    function updateAngleDefaultSelect(id, angles) {
        const row = document.querySelector(`#edgeOptionsTableBody tr[data-id="${id}"]`);
        if (!row) return;

        const select = row.querySelector('.angle-default-select');
        if (!select) return;

        // Zachowaj obecną wartość jeśli możliwe
        const currentValue = parseInt(select.value);

        // Wyczyść i wypełnij na nowo
        select.innerHTML = '';
        angles.forEach(angle => {
            const option = document.createElement('option');
            option.value = angle;
            option.textContent = angle + '°';
            if (angle === currentValue) option.selected = true;
            select.appendChild(option);
        });

        // Jeśli obecna wartość nie jest w nowej liście, wybierz pierwszą
        if (angles.length > 0 && !angles.includes(currentValue)) {
            select.value = angles[0];
            trackChange('edgeOptions', id, 'angle_default', angles[0].toString());
        }
    }

    // =============================================
    // HIERARCHICZNE DRZEWKO WYKOŃCZEŃ
    // =============================================

    const finishingTreeTableBody = document.getElementById('finishingTreeTableBody');
    const addFinishingOptionBtn = document.getElementById('addFinishingOptionBtn');
    const addFinishingOptionModal = document.getElementById('addFinishingOptionModal');
    const closeAddFinishingOptionModal = document.getElementById('closeAddFinishingOptionModal');
    const cancelAddFinishingOption = document.getElementById('cancelAddFinishingOption');
    const addFinishingOptionForm = document.getElementById('addFinishingOptionForm');
    const finishingOptionParentSelect = document.getElementById('finishingOptionParentSelect');

    // Modal
    addFinishingOptionBtn?.addEventListener('click', () => {
        addFinishingOptionModal.style.display = 'flex';
        addFinishingOptionForm.reset();
        if (finishingOptionParentSelect) {
            finishingOptionParentSelect.value = '';
        }
        addFinishingOptionForm.querySelector('input[name="name"]')?.focus();
    });

    closeAddFinishingOptionModal?.addEventListener('click', () => {
        addFinishingOptionModal.style.display = 'none';
    });

    cancelAddFinishingOption?.addEventListener('click', () => {
        addFinishingOptionModal.style.display = 'none';
    });

    addFinishingOptionModal?.addEventListener('click', (e) => {
        if (e.target === addFinishingOptionModal) {
            addFinishingOptionModal.style.display = 'none';
        }
    });

    // Dodawanie opcji
    addFinishingOptionForm?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(addFinishingOptionForm);
        const parentId = formData.get('parent_id');
        const priceNetto = formData.get('price_netto');

        const data = {
            parent_id: parentId ? parseInt(parentId) : null,
            name: formData.get('name'),
            code: formData.get('code') || null,
            price_netto: priceNetto ? parseFloat(priceNetto) : null
        };

        if (!data.name || data.name.trim() === '') {
            showNotification('Nazwa jest wymagana', 'error');
            return;
        }

        try {
            const response = await fetch('/settings/api/finishing-options', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Opcja została dodana', 'success');
                addFinishingOptionModal.style.display = 'none';
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification(result.error || 'Błąd dodawania opcji', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    });

    // Obsługa tabeli - śledzenie zmian
    finishingTreeTableBody?.addEventListener('input', (e) => {
        const id = e.target.dataset.id;
        if (!id) return;

        if (e.target.classList.contains('tree-name-input')) {
            trackChange('finishingTree', id, 'name', e.target.value);
        } else if (e.target.classList.contains('code-input')) {
            trackChange('finishingTree', id, 'code', e.target.value);
        } else if (e.target.classList.contains('price-value-input')) {
            trackChange('finishingTree', id, 'price_netto', e.target.value);
        }
    });

    // Akcje (usuwanie, dodawanie pod-opcji, przesuwanie, upload)
    finishingTreeTableBody?.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.btn-delete-tree');
        const addChildBtn = e.target.closest('.btn-add-child');
        const upBtn = e.target.closest('.btn-up-tree');
        const downBtn = e.target.closest('.btn-down-tree');
        const uploadBtn = e.target.closest('.btn-upload-image');

        if (deleteBtn) {
            const optionId = deleteBtn.dataset.id;
            const row = deleteBtn.closest('tr');
            const name = row.querySelector('.tree-name-input')?.value || 'tę opcję';

            if (confirm(`Czy na pewno chcesz usunąć "${name}" i wszystkie jej pod-opcje?`)) {
                await deleteFinishingOption(optionId);
            }
        }

        if (addChildBtn) {
            const parentId = addChildBtn.dataset.id;
            addFinishingOptionModal.style.display = 'flex';
            addFinishingOptionForm.reset();
            if (finishingOptionParentSelect) {
                finishingOptionParentSelect.value = parentId;
            }
            addFinishingOptionForm.querySelector('input[name="name"]')?.focus();
        }

        if (upBtn && !upBtn.disabled) {
            const optionId = upBtn.dataset.id;
            await moveFinishingOption(optionId, 'up');
        }

        if (downBtn && !downBtn.disabled) {
            const optionId = downBtn.dataset.id;
            await moveFinishingOption(optionId, 'down');
        }

        if (uploadBtn) {
            const optionId = uploadBtn.dataset.id;
            const fileInput = document.querySelector(`.image-upload-input[data-id="${optionId}"]`);
            if (fileInput) {
                fileInput.click();
            }
        }
    });

    // Upload obrazka
    finishingTreeTableBody?.addEventListener('change', async (e) => {
        if (e.target.classList.contains('image-upload-input')) {
            const optionId = e.target.dataset.id;
            const file = e.target.files[0];
            if (file) {
                await uploadFinishingOptionImage(optionId, file);
            }
        }
    });

    async function deleteFinishingOption(optionId) {
        try {
            const response = await fetch(`/settings/api/finishing-options/${optionId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Opcja usunięta', 'success');
                changedRecords.finishingTree.delete(optionId);
                originalValues.finishingTree.delete(optionId);
                updateSaveFooter('finishingTree');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification(result.error || 'Błąd usuwania', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    async function moveFinishingOption(optionId, direction) {
        try {
            const response = await fetch(`/settings/api/finishing-options/${optionId}/move`, {
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

    async function uploadFinishingOptionImage(optionId, file) {
        const formData = new FormData();
        formData.append('image', file);

        try {
            const response = await fetch(`/settings/api/finishing-options/${optionId}/upload-image`, {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                showNotification('Obrazek został przesłany', 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification(result.error || 'Błąd przesyłania obrazka', 'error');
            }
        } catch (error) {
            console.error('Błąd:', error);
            showNotification('Błąd komunikacji z serwerem', 'error');
        }
    }

    // Aktualizacja przycisków kolejności
    function updateFinishingTreeOrderButtons() {
        const rows = finishingTreeTableBody?.querySelectorAll('tr');
        if (!rows) return;

        const rowsByParent = {};
        rows.forEach(row => {
            const parentId = row.dataset.parentId || '';
            if (!rowsByParent[parentId]) {
                rowsByParent[parentId] = [];
            }
            rowsByParent[parentId].push(row);
        });

        Object.values(rowsByParent).forEach(siblings => {
            siblings.forEach((row, index) => {
                const upBtn = row.querySelector('.btn-up-tree');
                const downBtn = row.querySelector('.btn-down-tree');

                if (upBtn) {
                    upBtn.disabled = (index === 0);
                    upBtn.classList.toggle('disabled', index === 0);
                }
                if (downBtn) {
                    downBtn.disabled = (index === siblings.length - 1);
                    downBtn.classList.toggle('disabled', index === siblings.length - 1);
                }
            });
        });
    }

    updateFinishingTreeOrderButtons();

    // =============================================
    // NOTYFIKACJE
    // =============================================

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
            fontWeight: '500',
            maxWidth: '400px'
        });

        document.body.appendChild(notification);

        notification.querySelector('.notification-close').addEventListener('click', () => {
            notification.remove();
        });

        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transition = 'opacity 0.3s';
            setTimeout(() => notification.remove(), 300);
        }, 4000);
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
            @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            .spin {
                animation: spin 1s linear infinite;
            }
        `;
        document.head.appendChild(style);
    }

    // =============================================
    // TRYB KONSERWACJI
    // =============================================

    const maintenanceToggle = document.getElementById('maintenanceToggle');
    const maintenanceWarning = document.getElementById('maintenanceWarning');
    const maintenanceStatus = document.getElementById('maintenanceStatus');

    if (maintenanceToggle) {
        // Pokaż ostrzeżenie gdy toggle nie jest zaznaczony (będzie włączany)
        maintenanceToggle.addEventListener('change', function() {
            if (maintenanceWarning) {
                maintenanceWarning.style.display = this.checked ? 'none' : 'none';
            }

            const enabled = this.checked;
            const action = enabled ? 'WŁĄCZYĆ' : 'WYŁĄCZYĆ';
            const msg = enabled
                ? 'Czy na pewno chcesz włączyć tryb konserwacji?\n\nWszyscy użytkownicy (poza administratorami) zostaną wylogowani.'
                : 'Czy na pewno chcesz wyłączyć tryb konserwacji?\n\nUżytkownicy będą mogli normalnie korzystać z aplikacji.';

            if (!confirm(msg)) {
                this.checked = !enabled;
                return;
            }

            // Wyślij żądanie do API
            fetch('/settings/api/maintenance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabled })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Aktualizuj badge statusu
                    if (maintenanceStatus) {
                        maintenanceStatus.innerHTML = enabled
                            ? '<span class="status-badge status-active">AKTYWNY</span>'
                            : '<span class="status-badge status-inactive">WYŁĄCZONY</span>';
                    }

                    // Aktualizuj kolor toggle slidera
                    const slider = maintenanceToggle.nextElementSibling;
                    if (slider) {
                        if (enabled) {
                            slider.classList.add('danger-toggle');
                        } else {
                            slider.classList.remove('danger-toggle');
                        }
                    }
                } else {
                    alert('Błąd: ' + (data.message || 'Nie udało się zmienić trybu'));
                    maintenanceToggle.checked = !enabled;
                }
            })
            .catch(err => {
                alert('Błąd połączenia z serwerem');
                maintenanceToggle.checked = !enabled;
            });
        });

        // Pokaż ostrzeżenie gdy hover na wyłączonym toggle
        if (!maintenanceToggle.checked && maintenanceWarning) {
            maintenanceToggle.closest('.maintenance-toggle-row')?.addEventListener('mouseenter', function() {
                if (!maintenanceToggle.checked) {
                    maintenanceWarning.style.display = 'flex';
                }
            });
            maintenanceToggle.closest('.maintenance-toggle-row')?.addEventListener('mouseleave', function() {
                maintenanceWarning.style.display = 'none';
            });
        }
    }

    // =============================================
    // INICJALIZACJA
    // =============================================

    initializeOriginalValues();
});
