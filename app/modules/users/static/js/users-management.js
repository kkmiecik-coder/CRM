/* ============================================================================
   USERS-MANAGEMENT.JS - Zarządzanie zespołem (v2.0 z uprawnieniami)
   ============================================================================
   Autor: Konrad Kmiecik + Claude AI
   Data: 2025-01-13
   ============================================================================ */

// Stan globalny
let currentUserId = null;
let currentUserData = null;
let rolesCache = null;
let modulesCache = null;
let currentEditingRole = null;

document.addEventListener('DOMContentLoaded', function () {
    console.log('🚀 Users Management JS v2.0 - Inicjalizacja...');

    initMultiplierToggle();
    initModalHandlers();
    initTabHandlers();
    initSearchFilter();
    initFlashMessages();
    initAuditLog();  // NOWE!

    console.log('✅ Users Management JS załadowany pomyślnie!');
});

/* ============================================================================
   TOGGLE MNOŻNIKA PARTNERA (bez zmian)
   ============================================================================ */
function initMultiplierToggle() {
    const roleSelect = document.getElementById('invite_role');
    const multiplierGroup = document.getElementById('multiplierGroup');

    if (!roleSelect || !multiplierGroup) return;

    roleSelect.addEventListener('change', function () {
        if (this.value === 'partner') {
            multiplierGroup.style.display = 'block';
            multiplierGroup.style.animation = 'slideInDown 0.3s ease-out';
        } else {
            multiplierGroup.style.display = 'none';
        }
    });
}

/* ============================================================================
   OBSŁUGA MODALU EDYCJI (rozszerzona)
   ============================================================================ */
function initModalHandlers() {
    const modalOverlay = document.getElementById('modalOverlay');
    const editModal = document.getElementById('editModal');
    const closeModalBtn = document.getElementById('closeModal');
    const cancelModalBtn = document.getElementById('cancelModal');
    const savePermissionsBtn = document.getElementById('savePermissions');
    const editButtons = document.querySelectorAll('.btn-edit');
    const editUserForm = document.getElementById('editUserForm');

    if (!modalOverlay || !editModal) {
        console.warn('⚠️ Modal elements nie znalezione');
        return;
    }

    // Otwórz modal przy kliknięciu w przycisk Edytuj
    editButtons.forEach(button => {
        button.addEventListener('click', async function () {
            const userId = parseInt(this.dataset.userId);
            const firstName = this.dataset.firstName;
            const lastName = this.dataset.lastName;
            const role = this.dataset.role;
            const email = this.dataset.email;

            console.log(`📝 Otwieranie modalu dla użytkownika ID: ${userId}`);

            // Zapisz current user ID
            currentUserId = userId;
            currentUserData = { firstName, lastName, role, email };

            // Wypełnij TAB 1: Dane podstawowe
            document.getElementById('editUserId').value = userId;
            document.getElementById('editFirstName').value = firstName;
            document.getElementById('editLastName').value = lastName;
            document.getElementById('editEmail').value = email;

            // Zaktualizuj action formularza
            editUserForm.action = `/users/${userId}/edit`;

            // Reset tabów do pierwszego
            resetToFirstTab();

            // Pokaż modal
            openModal();

            // Pre-load uprawnień (załaduje się gdy user przełączy na tab 2)
            // Nie ładujemy od razu żeby modal szybciej się otworzył
        });
    });

    // Zamknij modal
    closeModalBtn.addEventListener('click', closeModal);
    cancelModalBtn.addEventListener('click', closeModal);

    // Zamknij modal po kliknięciu w overlay
    modalOverlay.addEventListener('click', closeModal);

    // Zamknij modal po naciśnięciu ESC
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && editModal.classList.contains('active')) {
            closeModal();
        }
    });

    // Zapisz uprawnienia
    savePermissionsBtn.addEventListener('click', handleSavePermissions);

    function openModal() {
        modalOverlay.classList.add('active');
        editModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modalOverlay.classList.remove('active');
        editModal.classList.remove('active');
        document.body.style.overflow = '';

        // Reset stanu
        currentUserId = null;
        currentUserData = null;
    }
}

/* ============================================================================
   OBSŁUGA TABÓW
   ============================================================================ */
function initTabHandlers() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    if (!tabButtons.length || !tabContents.length) {
        console.warn('⚠️ Tab elements nie znalezione');
        return;
    }

    tabButtons.forEach(button => {
        button.addEventListener('click', function () {
            const targetTab = this.dataset.tab;

            // Zmień aktywny przycisk
            tabButtons.forEach(btn => btn.classList.remove('active'));
            this.classList.add('active');

            // Zmień aktywną zawartość
            tabContents.forEach(content => content.classList.remove('active'));
            const targetContent = document.getElementById(targetTab);
            if (targetContent) {
                targetContent.classList.add('active');
            }

            // Jeśli przełączono na tab uprawnień - załaduj dane
            if (targetTab === 'tab-permissions' && currentUserId) {
                loadPermissionsTab();
            }
        });
    });
}

function resetToFirstTab() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach((btn, idx) => {
        if (idx === 0) btn.classList.add('active');
        else btn.classList.remove('active');
    });

    tabContents.forEach((content, idx) => {
        if (idx === 0) content.classList.add('active');
        else content.classList.remove('active');
    });
}

/* ============================================================================
   ŁADOWANIE UPRAWNIEŃ - TAB 2
   ============================================================================ */
async function loadPermissionsTab() {
    console.log(`🔐 Ładowanie uprawnień dla user_id: ${currentUserId}`);

    const loadingDiv = document.getElementById('permissions-loading');
    const contentDiv = document.getElementById('permissions-content');
    const errorDiv = document.getElementById('permissions-error');
    const retryBtn = document.getElementById('retry-permissions');

    // Pokaż loading
    loadingDiv.style.display = 'block';
    contentDiv.style.display = 'none';
    errorDiv.style.display = 'none';

    try {
        // Pobierz dane równolegle
        const [rolesData, modulesData, userPermissionsData] = await Promise.all([
            fetchRoles(),
            fetchModules(),
            fetchUserPermissions(currentUserId)
        ]);

        console.log('📦 Dane załadowane:', { rolesData, modulesData, userPermissionsData });

        // Renderuj role
        renderRolesSelect(rolesData.roles, userPermissionsData.role_id);

        // Renderuj moduły
        renderModulesList(modulesData.modules, userPermissionsData.modules);

        // Nasłuchuj zmiany roli
        initRoleChangeHandler(userPermissionsData);

        // Pokaż content
        loadingDiv.style.display = 'none';
        contentDiv.style.display = 'block';

    } catch (error) {
        console.error('❌ Błąd ładowania uprawnień:', error);

        // Pokaż error
        loadingDiv.style.display = 'none';
        errorDiv.style.display = 'block';

        // Retry button
        retryBtn.onclick = loadPermissionsTab;
    }
}

/* ============================================================================
   API CALLS
   ============================================================================ */
async function fetchRoles() {
    if (rolesCache) return rolesCache;

    const response = await fetch('/users/api/roles');
    if (!response.ok) throw new Error('Błąd pobierania ról');

    const data = await response.json();
    rolesCache = data;
    return data;
}

async function fetchModules() {
    if (modulesCache) return modulesCache;

    const response = await fetch('/users/api/modules');
    if (!response.ok) throw new Error('Błąd pobierania modułów');

    const data = await response.json();
    modulesCache = data;
    return data;
}

async function fetchUserPermissions(userId) {
    const response = await fetch(`/users/api/user-permissions/${userId}`);
    if (!response.ok) throw new Error('Błąd pobierania uprawnień użytkownika');

    const data = await response.json();
    return data;
}

/* ============================================================================
   RENDEROWANIE - Role Select
   ============================================================================ */
function renderRolesSelect(roles, currentRoleId) {
    const roleSelect = document.getElementById('editRolePermissions');
    if (!roleSelect) return;

    roleSelect.innerHTML = '';

    roles.forEach(role => {
        const option = document.createElement('option');
        option.value = role.role_id;
        option.textContent = `${getRoleIcon(role.role_name)} ${role.display_name}`;
        option.dataset.roleName = role.role_name;

        if (role.role_id === currentRoleId) {
            option.selected = true;
        }

        roleSelect.appendChild(option);
    });
}

function getRoleIcon(roleName) {
    const icons = {
        'admin': '⚙️',
        'user': '👤',
        'partner': '🤝'
    };
    return icons[roleName] || '👤';
}

/* ============================================================================
   RENDEROWANIE - Moduły
   ============================================================================ */
function renderModulesList(modules, userModules) {
    const modulesList = document.getElementById('modules-list');
    const template = document.getElementById('module-item-template');

    if (!modulesList || !template) return;

    // Wyczyść listę (zachowaj template)
    Array.from(modulesList.children).forEach(child => {
        if (child.id !== 'module-item-template') {
            child.remove();
        }
    });

    // Grupuj moduły (opcjonalnie można dodać grupowanie)
    modules.forEach(module => {
        // Pomiń public moduły (np. dashboard)
        if (module.access_type === 'public') {
            return;
        }

        // Znajdź dane użytkownika dla tego modułu
        const userModule = userModules.find(um => um.module_key === module.module_key);

        // Klonuj template
        const clone = template.content.cloneNode(true);
        const item = clone.querySelector('.module-item');
        const checkbox = clone.querySelector('.module-checkbox-input');
        const icon = clone.querySelector('.module-icon');
        const name = clone.querySelector('.module-name');
        const badges = clone.querySelector('.module-badges');

        // Ustaw dane
        checkbox.dataset.moduleId = module.id;
        checkbox.dataset.moduleKey = module.module_key;
        checkbox.id = `module-${module.id}`;

        icon.textContent = module.icon || '📦';
        name.textContent = module.display_name;

        // Zaznacz checkbox jeśli user ma dostęp
        if (userModule && userModule.has_access) {
            checkbox.checked = true;
        }

        // Dodaj badge
        if (userModule) {
            const badge = createBadge(userModule);
            if (badge) badges.appendChild(badge);
        }

        // Dodaj do listy
        modulesList.appendChild(clone);
    });
}

function createBadge(userModule) {
    const badge = document.createElement('span');
    badge.className = 'module-badge';

    if (userModule.individual_override === 'grant') {
        badge.classList.add('badge-granted');
        badge.textContent = 'Nadane';
    } else if (userModule.individual_override === 'revoke') {
        badge.classList.add('badge-revoked');
        badge.textContent = 'Odebrane';
    } else if (userModule.access_source === 'role') {
        badge.classList.add('badge-from-role');
        badge.textContent = 'Z roli';
    } else if (userModule.access_source === 'custom') {
        badge.classList.add('badge-custom');
        badge.textContent = 'Custom';
    }

    return badge;
}

/* ============================================================================
   ZMIANA ROLI - Przeładowanie modułów
   ============================================================================ */
function initRoleChangeHandler(userPermissionsData) {
    const roleSelect = document.getElementById('editRolePermissions');
    if (!roleSelect) return;

    roleSelect.addEventListener('change', async function () {
        const newRoleId = parseInt(this.value);
        const roleName = this.options[this.selectedIndex].dataset.roleName;

        console.log(`🔄 Zmiana roli na: ${roleName} (ID: ${newRoleId})`);

        // Pokaż loading na checkboxach
        const modulesList = document.getElementById('modules-list');
        modulesList.style.opacity = '0.5';
        modulesList.style.pointerEvents = 'none';

        try {
            // Pobierz uprawnienia dla wybranej roli
            const rolePermissions = await fetchRolePermissions(newRoleId);

            console.log(`📋 Uprawnienia roli ${roleName}:`, rolePermissions);

            // Zaktualizuj checkboxy według nowej roli
            updateModulesForRole(rolePermissions);

            // Ukryj loading
            modulesList.style.opacity = '1';
            modulesList.style.pointerEvents = 'auto';

            // Pokaż toast
            showToast(`Uprawnienia zaktualizowane dla roli: ${roleName}`, 'info');

        } catch (error) {
            console.error('❌ Błąd ładowania uprawnień roli:', error);
            modulesList.style.opacity = '1';
            modulesList.style.pointerEvents = 'auto';
            showToast('Błąd ładowania uprawnień roli', 'error');
        }
    });
}

/* ============================================================================
   API - Pobierz uprawnienia roli
   ============================================================================ */
async function fetchRolePermissions(roleId) {
    const response = await fetch(`/users/api/roles`);
    if (!response.ok) throw new Error('Błąd pobierania ról');

    const data = await response.json();

    // Znajdź wybraną rolę
    const role = data.roles.find(r => r.role_id === roleId);
    if (!role) throw new Error('Rola nie znaleziona');

    // Pobierz szczegóły roli z modułami
    const roleDetailsResponse = await fetch(`/users/api/role-permissions/${roleId}`);
    if (!roleDetailsResponse.ok) {
        // Jeśli endpoint nie istnieje, użyj logiki client-side
        return inferRolePermissions(role.role_name);
    }

    const roleDetails = await roleDetailsResponse.json();
    return roleDetails.module_ids || [];
}

/* ============================================================================
   LOGIKA - Wywnioskuj uprawnienia roli (fallback)
   ============================================================================ */
function inferRolePermissions(roleName) {
    // Ta funkcja używa znanej logiki uprawnień z bazy
    // (fallback gdyby endpoint API nie istniał)

    if (!modulesCache || !modulesCache.modules) return [];

    const allModules = modulesCache.modules;
    const moduleIds = [];

    allModules.forEach(module => {
        // Pomiń public i custom moduły
        if (module.access_type === 'public' || module.access_type === 'custom') {
            return;
        }

        // Admin: wszystkie moduły
        if (roleName === 'admin') {
            moduleIds.push(module.id);
        }
        // User: wszystkie oprócz 'users'
        else if (roleName === 'user') {
            if (module.module_key !== 'users') {
                moduleIds.push(module.id);
            }
        }
        // Partner: tylko 'quotes'
        else if (roleName === 'partner') {
            if (module.module_key === 'quotes') {
                moduleIds.push(module.id);
            }
        }
    });

    return moduleIds;
}

/* ============================================================================
   AKTUALIZACJA - Zaznacz checkboxy według roli
   ============================================================================ */
function updateModulesForRole(moduleIdsFromRole) {
    const checkboxes = document.querySelectorAll('.module-checkbox-input');

    checkboxes.forEach(checkbox => {
        const moduleId = parseInt(checkbox.dataset.moduleId);
        const moduleKey = checkbox.dataset.moduleKey;

        // Zaznacz jeśli rola ma ten moduł
        if (moduleIdsFromRole.includes(moduleId)) {
            checkbox.checked = true;
        } else {
            checkbox.checked = false;
        }

        // Zaktualizuj badge
        updateModuleBadge(checkbox, moduleIdsFromRole.includes(moduleId));
    });
}

/* ============================================================================
   AKTUALIZACJA - Badge modułu
   ============================================================================ */
function updateModuleBadge(checkbox, hasAccessFromRole) {
    const moduleItem = checkbox.closest('.module-item');
    const badges = moduleItem.querySelector('.module-badges');

    if (!badges) return;

    // Wyczyść stare badge'e
    badges.innerHTML = '';

    // Dodaj badge "Z roli" jeśli ma dostęp z roli
    if (hasAccessFromRole) {
        const badge = document.createElement('span');
        badge.className = 'module-badge badge-from-role';
        badge.textContent = 'Z roli';
        badges.appendChild(badge);
    }
}

/* ============================================================================
   ZAPISYWANIE UPRAWNIEŃ
   ============================================================================ */
async function handleSavePermissions() {
    console.log('💾 Zapisywanie uprawnień...');

    const saveBtn = document.getElementById('savePermissions');
    const originalText = saveBtn.innerHTML;

    try {
        // Disable button
        saveBtn.disabled = true;
        saveBtn.innerHTML = '⏳ Zapisywanie...';

        // Pobierz dane z formularza
        const userId = currentUserId;
        const roleId = parseInt(document.getElementById('editRolePermissions').value);
        const reason = document.getElementById('permissionsReason').value.trim();

        // Pobierz zaznaczone moduły
        const modules = {};
        const checkboxes = document.querySelectorAll('.module-checkbox-input');

        checkboxes.forEach(checkbox => {
            const moduleId = checkbox.dataset.moduleId;

            if (checkbox.checked) {
                modules[moduleId] = 'grant';
            } else {
                modules[moduleId] = 'revoke';
            }
        });

        console.log('📤 Wysyłanie:', { userId, roleId, modules, reason });

        // Wyślij request
        const response = await fetch('/users/api/update-user-permissions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: userId,
                role_id: roleId,
                modules: modules,
                reason: reason || null
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Błąd zapisywania uprawnień');
        }

        console.log('✅ Uprawnienia zapisane:', data);

        // Pokaż komunikat sukcesu
        showToast('Uprawnienia zostały zaktualizowane pomyślnie!', 'success');

        // Zamknij modal po 1 sekundzie
        setTimeout(() => {
            // Reload strony aby odświeżyć listę użytkowników
            window.location.reload();
        }, 1000);

    } catch (error) {
        console.error('❌ Błąd zapisywania:', error);

        showToast(`Błąd: ${error.message}`, 'error');

        // Przywróć button
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalText;
    }
}

/* ============================================================================
   TOAST NOTIFICATIONS
   ============================================================================ */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `flash flash-${type}`;
    toast.textContent = message;
    toast.style.position = 'fixed';
    toast.style.top = '20px';
    toast.style.right = '20px';
    toast.style.zIndex = '9999';
    toast.style.minWidth = '300px';
    toast.style.animation = 'slideInRight 0.3s ease-out';

    document.body.appendChild(toast);

    // Auto remove po 5 sekundach
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

/* ============================================================================
   FILTROWANIE WYSZUKIWANIA (bez zmian)
   ============================================================================ */
function initSearchFilter() {
    const searchInput = document.getElementById('searchInput');
    const tableRows = document.querySelectorAll('.table-row');

    if (!searchInput || !tableRows.length) return;

    searchInput.addEventListener('input', function () {
        const searchTerm = this.value.toLowerCase().trim();

        tableRows.forEach(row => {
            const searchData = row.dataset.userSearch || '';

            if (searchData.includes(searchTerm)) {
                row.style.display = 'grid';
                row.style.animation = 'fadeIn 0.3s ease-out';
            } else {
                row.style.display = 'none';
            }
        });

        // Pokaż komunikat jeśli nie ma wyników
        const visibleRows = Array.from(tableRows).filter(row => row.style.display !== 'none');
        showNoResultsMessage(visibleRows.length === 0);
    });
}

function showNoResultsMessage(show) {
    const tableBody = document.getElementById('usersTableBody');
    let noResultsDiv = document.getElementById('noResults');

    if (show) {
        if (!noResultsDiv) {
            noResultsDiv = document.createElement('div');
            noResultsDiv.id = 'noResults';
            noResultsDiv.className = 'empty-state';
            noResultsDiv.innerHTML = `
                <div class="empty-icon">🔍</div>
                <div class="empty-title">Brak wyników</div>
                <div class="empty-subtitle">Nie znaleziono użytkowników pasujących do wyszukiwania</div>
            `;
            tableBody.appendChild(noResultsDiv);
        }
        noResultsDiv.style.display = 'block';
    } else {
        if (noResultsDiv) {
            noResultsDiv.style.display = 'none';
        }
    }
}

/* ============================================================================
   FLASH MESSAGES (bez zmian)
   ============================================================================ */
function initFlashMessages() {
    const flashMessages = document.querySelectorAll('.flash');

    flashMessages.forEach(function (flash) {
        // Auto-hide po 5 sekundach
        setTimeout(function () {
            flash.style.opacity = '0';
            flash.style.transition = 'opacity 0.5s ease';

            setTimeout(function () {
                flash.remove();
            }, 500);
        }, 5000);

        // Możliwość zamknięcia po kliknięciu
        flash.style.cursor = 'pointer';
        flash.addEventListener('click', function () {
            this.style.opacity = '0';
            this.style.transition = 'opacity 0.3s ease';

            setTimeout(function () {
                flash.remove();
            }, 300);
        });
    });
}

/* ============================================================================
   ANIMACJE CSS
   ============================================================================ */
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInDown {
        from {
            opacity: 0;
            max-height: 0;
            overflow: hidden;
        }
        to {
            opacity: 1;
            max-height: 200px;
        }
    }
    
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    
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

/* ============================================================================
   AUDIT LOG - Historia zmian uprawnień (NOWE)
   ============================================================================ */

// Stan audit log
let auditState = {
    currentPage: 1,
    limit: 20,
    total: 0,
    filters: {
        search: '',
        changeType: '',
        dateFrom: null
    }
};

function initAuditLog() {
    console.log('📜 Inicjalizacja Audit Log...');

    // Elementy
    const searchInput = document.getElementById('auditSearchInput');
    const typeFilter = document.getElementById('auditTypeFilter');
    const dateFromInput = document.getElementById('auditDateFrom');
    const prevPageBtn = document.getElementById('audit-prev-page');
    const nextPageBtn = document.getElementById('audit-next-page');
    const retryBtn = document.getElementById('retry-audit-log');

    if (!searchInput) {
        console.warn('⚠️ Audit log elements nie znalezione');
        return;
    }

    // Event listeners dla filtrów
    searchInput.addEventListener('input', debounce(function () {
        auditState.filters.search = this.value.trim();
        auditState.currentPage = 1;
        loadAuditLog();
    }, 500));

    typeFilter.addEventListener('change', function () {
        auditState.filters.changeType = this.value;
        auditState.currentPage = 1;
        loadAuditLog();
    });

    dateFromInput.addEventListener('change', function () {
        auditState.filters.dateFrom = this.value;
        auditState.currentPage = 1;
        loadAuditLog();
    });

    // Paginacja
    prevPageBtn.addEventListener('click', function () {
        if (auditState.currentPage > 1) {
            auditState.currentPage--;
            loadAuditLog();
        }
    });

    nextPageBtn.addEventListener('click', function () {
        const totalPages = Math.ceil(auditState.total / auditState.limit);
        if (auditState.currentPage < totalPages) {
            auditState.currentPage++;
            loadAuditLog();
        }
    });

    // Retry
    retryBtn.addEventListener('click', loadAuditLog);

    // Załaduj audit log przy starcie
    loadAuditLog();
}

async function loadAuditLog() {
    console.log('📋 Ładowanie audit log...', auditState);

    const loadingDiv = document.getElementById('audit-loading');
    const listDiv = document.getElementById('audit-log-list');
    const emptyDiv = document.getElementById('audit-empty');
    const errorDiv = document.getElementById('audit-error');
    const paginationDiv = document.getElementById('audit-pagination');

    // Pokaż loading
    loadingDiv.style.display = 'block';
    listDiv.style.display = 'none';
    emptyDiv.style.display = 'none';
    errorDiv.style.display = 'none';
    paginationDiv.style.display = 'none';

    try {
        // Buduj query string
        const offset = (auditState.currentPage - 1) * auditState.limit;
        const params = new URLSearchParams({
            limit: auditState.limit,
            offset: offset
        });

        if (auditState.filters.changeType) {
            params.append('change_type', auditState.filters.changeType);
        }

        if (auditState.filters.dateFrom) {
            params.append('date_from', auditState.filters.dateFrom + 'T00:00:00');
        }

        // Fetch data
        const response = await fetch(`/users/api/audit-log?${params.toString()}`);

        if (!response.ok) {
            throw new Error('Błąd pobierania audit log');
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Błąd pobierania danych');
        }

        console.log('✅ Audit log załadowany:', data);

        // Zapisz total
        auditState.total = data.total;

        // Filtruj po search (client-side)
        let logs = data.logs;
        if (auditState.filters.search) {
            const searchLower = auditState.filters.search.toLowerCase();
            logs = logs.filter(log => {
                const userNameLower = log.user_name.toLowerCase();
                const userEmailLower = log.user_email ? log.user_email.toLowerCase() : '';
                return userNameLower.includes(searchLower) || userEmailLower.includes(searchLower);
            });
        }

        // Renderuj
        if (logs.length === 0) {
            loadingDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
        } else {
            renderAuditLog(logs);
            loadingDiv.style.display = 'none';
            listDiv.style.display = 'flex';

            // Pokaż paginację jeśli więcej niż 1 strona
            if (auditState.total > auditState.limit) {
                updatePagination();
                paginationDiv.style.display = 'flex';
            }
        }

    } catch (error) {
        console.error('❌ Błąd ładowania audit log:', error);
        loadingDiv.style.display = 'none';
        errorDiv.style.display = 'block';
    }
}

function renderAuditLog(logs) {
    const listDiv = document.getElementById('audit-log-list');
    const template = document.getElementById('audit-item-template');

    if (!listDiv || !template) return;

    // Wyczyść listę
    listDiv.innerHTML = '';

    logs.forEach(log => {
        const clone = template.content.cloneNode(true);

        // Avatar - UŻYWAMY avatar_path zamiast email
        const avatar = clone.querySelector('.audit-user-avatar');
        avatar.src = getAvatarUrl(log.changed_by_avatar_path);
        avatar.alt = log.changed_by_name;

        // Nazwa użytkownika
        const userName = clone.querySelector('.audit-user-name');
        userName.textContent = log.changed_by_name;

        // Akcja
        const actionText = clone.querySelector('.audit-action-text');
        actionText.textContent = getActionText(log.change_type);

        // Target (kogo dotyczy)
        const targetName = clone.querySelector('.audit-target-name');
        targetName.textContent = log.user_name;

        // Data
        const dateSpan = clone.querySelector('.audit-date');
        dateSpan.textContent = log.created_at_formatted || formatDate(log.created_at);

        // IP
        const ipSpan = clone.querySelector('.audit-ip');
        if (log.ip_address) {
            ipSpan.textContent = log.ip_address;
        } else {
            ipSpan.style.display = 'none';
        }

        // Badge
        const badgeWrapper = clone.querySelector('.audit-badge-wrapper');
        const badge = createAuditBadge(log.change_type);
        badgeWrapper.appendChild(badge);

        // NOWE: Szczegóły zmiany (old_value -> new_value)
        const detailsDiv = clone.querySelector('.audit-details');
        const detailsHTML = renderAuditDetails(log);
        if (detailsHTML) {
            detailsDiv.innerHTML = detailsHTML;
        } else {
            detailsDiv.style.display = 'none';
        }

        // Powód
        const reasonDiv = clone.querySelector('.audit-reason');
        const reasonText = clone.querySelector('.reason-text');
        if (log.reason) {
            reasonText.textContent = log.reason;
            reasonDiv.style.display = 'flex';
        }

        listDiv.appendChild(clone);
    });
}

/**
 * Renderuje szczegóły zmiany (old_value -> new_value)
 */
function renderAuditDetails(log) {
    const { change_type, old_value, new_value } = log;

    if (change_type === 'role_changed') {
        // Zmiana roli: Admin → User
        const oldRole = old_value?.role_name || 'Brak';
        const newRole = new_value?.role_name || 'Brak';

        return `
            <div class="audit-details-row">
                <span class="audit-details-label">🔄 Zmiana roli:</span>
                <span class="audit-value-old">${getRoleDisplayName(oldRole)}</span>
                <span class="audit-value-arrow">→</span>
                <span class="audit-value-new">${getRoleDisplayName(newRole)}</span>
            </div>
        `;
    }

    if (change_type === 'module_granted') {
        // Nadanie dostępu do modułu
        const moduleKey = new_value?.module_key || 'Nieznany';
        const moduleName = getModuleDisplayName(moduleKey);

        return `
            <div class="audit-details-row">
                <span class="audit-details-label">✅ Nadano:</span>
                <span class="audit-module-name">${moduleName}</span>
            </div>
        `;
    }

    if (change_type === 'module_revoked') {
        // Odebranie dostępu do modułu
        const moduleKey = old_value?.module_key || 'Nieznany';
        const moduleName = getModuleDisplayName(moduleKey);

        return `
            <div class="audit-details-row">
                <span class="audit-details-label">❌ Odebrano:</span>
                <span class="audit-module-name">${moduleName}</span>
            </div>
        `;
    }

    return null; // Brak szczegółów do wyświetlenia
}

/**
 * Mapowanie role_name na czytelną nazwę
 */
function getRoleDisplayName(roleName) {
    const roleMap = {
        'admin': '⚙️ Administrator',
        'user': '👤 Użytkownik',
        'partner': '🤝 Partner'
    };
    return roleMap[roleName] || roleName;
}

/**
 * Mapowanie module_key na czytelną nazwę
 */
function getModuleDisplayName(moduleKey) {
    // Pobierz z cache modułów (jeśli dostępny)
    if (modulesCache && modulesCache.modules) {
        const module = modulesCache.modules.find(m => m.module_key === moduleKey);
        if (module) {
            return `${module.icon || '📦'} ${module.display_name}`;
        }
    }

    // Fallback - podstawowe mapowanie
    const moduleMap = {
        'dashboard': '🏠 Dashboard',
        'quotes': '📊 Wyceny',
        'production': '🏭 Produkcja',
        'users': '👥 Zarządzanie zespołem',
        'clients': '👔 Klienci',
        'baselinker': '🔗 Baselinker',
        'analytics': '📈 Analityka',
        'reports': '📄 Raporty'
    };

    return moduleMap[moduleKey] || moduleKey;
}

function getActionText(changeType) {
    const actions = {
        'role_changed': 'zmienił rolę dla użytkownika',
        'module_granted': 'nadał dostęp do modułu dla użytkownika',
        'module_revoked': 'odebrał dostęp do modułu użytkownikowi'
    };
    return actions[changeType] || 'wykonał akcję dla użytkownika';
}

function createAuditBadge(changeType) {
    const badge = document.createElement('span');
    badge.className = 'audit-change-badge';

    if (changeType === 'role_changed') {
        badge.classList.add('audit-badge-role-changed');
        badge.textContent = 'Zmiana roli';
    } else if (changeType === 'module_granted') {
        badge.classList.add('audit-badge-module-granted');
        badge.textContent = 'Nadanie dostępu';
    } else if (changeType === 'module_revoked') {
        badge.classList.add('audit-badge-module-revoked');
        badge.textContent = 'Odebranie dostępu';
    }

    return badge;
}

function updatePagination() {
    const totalPages = Math.ceil(auditState.total / auditState.limit);

    const prevBtn = document.getElementById('audit-prev-page');
    const nextBtn = document.getElementById('audit-next-page');
    const pageInfo = document.getElementById('audit-page-info');

    // Aktualizuj przyciski
    prevBtn.disabled = auditState.currentPage === 1;
    nextBtn.disabled = auditState.currentPage === totalPages;

    // Aktualizuj tekst
    pageInfo.textContent = `Strona ${auditState.currentPage} z ${totalPages}`;
}

/**
 * Buduje pełny URL avatara na podstawie avatar_path
 * 
 * @param {string|null} avatarPath - Ścieżka avatara z bazy (np. "custom/user_1_123456_photo.jpg" lub "default_avatars/avatar1.svg")
 * @returns {string} - Pełny URL avatara
 */
function getAvatarUrl(avatarPath) {
    // Jeśli brak avatar_path, użyj domyślnego
    if (!avatarPath || avatarPath === '') {
        return '/static/images/avatars/default_avatars/avatar1.svg';
    }

    // Ścieżki avatarów custom są zapisane jako: "custom/filename"
    // Ścieżki avatarów default są zapisane jako: "default_avatars/avatar1.svg"
    // Ścieżki avatarów user są zapisane jako: "user_avatars/filename"

    // Jeśli avatar_path już zawiera "avatars/", nie dodawaj ponownie
    if (avatarPath.includes('/avatars/')) {
        return `/static/${avatarPath}`;
    }

    // W przeciwnym razie dodaj pełną ścieżkę
    return `/static/images/avatars/${avatarPath}`;
}

function formatDate(dateString) {
    if (!dateString) return '';

    try {
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;

        // Mniej niż minutę
        if (diff < 60000) {
            return 'przed chwilą';
        }

        // Mniej niż godzinę
        if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes} min temu`;
        }

        // Mniej niż dzień
        if (diff < 86400000) {
            const hours = Math.floor(diff / 3600000);
            return `${hours}h temu`;
        }

        // Pełna data
        return date.toLocaleString('pl-PL', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return dateString;
    }
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func.apply(this, args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/* ============================================================================
   SEKCJA: ZARZĄDZANIE UPRAWNIENIAMI RÓL
   ============================================================================ */

/**
 * Inicjalizacja zarządzania uprawnieniami ról
 */
function initRolePermissionsManagement() {
    const roleSelect = document.getElementById('rolePermissionsSelect');
    const saveBtn = document.getElementById('saveRolePermissions');

    if (!roleSelect || !saveBtn) {
        console.warn('Elementy zarządzania uprawnieniami ról nie znalezione');
        return;
    }

    // Załaduj role
    loadRolesForPermissions();

    // Event listener na zmianę roli
    roleSelect.addEventListener('change', function () {
        const roleId = parseInt(this.value);
        if (roleId) {
            loadRoleModules(roleId);
        }
    });

    // Event listener na zapisanie
    saveBtn.addEventListener('click', saveRolePermissions);
}

/**
 * Ładuje listę ról do selecta
 */
async function loadRolesForPermissions() {
    try {
        const response = await fetch('/users/api/roles');
        if (!response.ok) throw new Error('Błąd pobierania ról');

        const data = await response.json();
        rolesCache = data;

        renderRolesSelect(data.roles);

    } catch (error) {
        console.error('Błąd ładowania ról:', error);
        showToast('Błąd ładowania ról', 'error');
    }
}

/**
 * Renderuje select z rolami
 */
function renderRolesSelect(roles) {
    const roleSelect = document.getElementById('rolePermissionsSelect');
    if (!roleSelect) return;

    roleSelect.innerHTML = '<option value="">-- Wybierz rolę --</option>';

    roles.forEach(role => {
        const option = document.createElement('option');
        option.value = role.role_id;
        option.textContent = `${getRoleIcon(role.role_name)} ${role.display_name} (${role.modules_count} modułów)`;
        option.dataset.roleName = role.role_name;
        option.dataset.isSystem = role.is_system;

        roleSelect.appendChild(option);
    });
}

/**
 * Ładuje moduły dla wybranej roli
 */
async function loadRoleModules(roleId) {
    try {
        const response = await fetch(`/users/api/role-modules/${roleId}`);
        if (!response.ok) throw new Error('Błąd pobierania modułów roli');

        const data = await response.json();
        currentEditingRole = data;

        renderRoleModulesList(data.modules, data.role_name);

    } catch (error) {
        console.error('Błąd ładowania modułów roli:', error);
        showToast('Błąd ładowania modułów', 'error');
    }
}

/**
 * Renderuje listę modułów z checkboxami
 */
function renderRoleModulesList(modules, roleName) {
    const modulesList = document.getElementById('roleModulesList');
    if (!modulesList) return;

    modulesList.innerHTML = '';

    // Header
    const header = document.createElement('div');
    header.className = 'role-modules-header';
    header.innerHTML = `
        <h4>Uprawnienia dla roli: <strong>${roleName}</strong></h4>
        <p class="text-muted">Zaznacz moduły, do których rola ma mieć dostęp</p>
    `;
    modulesList.appendChild(header);

    // Lista modułów
    modules.forEach(module => {
        const moduleItem = document.createElement('div');
        moduleItem.className = 'role-module-item';

        moduleItem.innerHTML = `
            <label class="module-checkbox">
                <input type="checkbox" 
                       class="role-module-checkbox" 
                       data-module-id="${module.module_id}"
                       ${module.has_access ? 'checked' : ''}>
                <span class="checkbox-custom"></span>
                <span class="module-icon">${module.icon}</span>
                <span class="module-name">${module.display_name}</span>
            </label>
        `;

        modulesList.appendChild(moduleItem);
    });

    // ✅ DODAJ TO - Pokaż przycisk "Zapisz"
    const saveBtn = document.getElementById('saveRolePermissions');
    if (saveBtn) {
        saveBtn.style.display = 'inline-flex';
    }
}

/**
 * Zapisuje uprawnienia roli
 */
async function saveRolePermissions() {
    if (!currentEditingRole) {
        showToast('Wybierz rolę do edycji', 'warning');
        return;
    }

    try {
        const checkboxes = document.querySelectorAll('.role-module-checkbox');
        const moduleIds = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => parseInt(cb.dataset.moduleId));

        const saveBtn = document.getElementById('saveRolePermissions');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Zapisywanie...';

        const response = await fetch('/users/api/update-role-modules', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                role_id: currentEditingRole.role_id,
                module_ids: moduleIds
            })
        });

        if (!response.ok) throw new Error('Błąd zapisu uprawnień');

        const data = await response.json();

        if (data.success) {
            showToast(data.message, 'success');

            // Odśwież listę ról (zaktualizuj liczniki)
            await loadRolesForPermissions();

            // Zaznacz z powrotem edytowaną rolę
            document.getElementById('rolePermissionsSelect').value = currentEditingRole.role_id;

        } else {
            throw new Error(data.error || 'Nieznany błąd');
        }

    } catch (error) {
        console.error('Błąd zapisywania uprawnień:', error);
        showToast('Błąd zapisywania uprawnień: ' + error.message, 'error');

    } finally {
        const saveBtn = document.getElementById('saveRolePermissions');
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 Zapisz uprawnienia';
    }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function () {
    initRolePermissionsManagement();
});