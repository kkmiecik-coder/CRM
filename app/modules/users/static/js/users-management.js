/* ============================================================================
   USERS-MANAGEMENT.JS - Zarządzanie zespołem
   ============================================================================ */

document.addEventListener('DOMContentLoaded', function() {
    initMultiplierToggle();
    initModalHandlers();
    initSearchFilter();
    initFlashMessages();
});

/* ============================================================================
   TOGGLE MNOŻNIKA PARTNERA
   ============================================================================ */
function initMultiplierToggle() {
    const roleSelect = document.getElementById('invite_role');
    const multiplierGroup = document.getElementById('multiplierGroup');
    
    if (!roleSelect || !multiplierGroup) return;
    
    roleSelect.addEventListener('change', function() {
        if (this.value === 'partner') {
            multiplierGroup.style.display = 'block';
            multiplierGroup.style.animation = 'slideInDown 0.3s ease-out';
        } else {
            multiplierGroup.style.display = 'none';
        }
    });
}

/* ============================================================================
   OBSŁUGA MODALU EDYCJI
   ============================================================================ */
function initModalHandlers() {
    const modalOverlay = document.getElementById('modalOverlay');
    const editModal = document.getElementById('editModal');
    const closeModalBtn = document.getElementById('closeModal');
    const cancelModalBtn = document.getElementById('cancelModal');
    const editButtons = document.querySelectorAll('.btn-edit');
    const editUserForm = document.getElementById('editUserForm');
    
    if (!modalOverlay || !editModal) return;
    
    // Otwórz modal przy kliknięciu w przycisk Edytuj
    editButtons.forEach(button => {
        button.addEventListener('click', function() {
            const userId = this.dataset.userId;
            const firstName = this.dataset.firstName;
            const lastName = this.dataset.lastName;
            const role = this.dataset.role;
            const email = this.dataset.email;
            
            // Wypełnij formularz danymi użytkownika
            document.getElementById('editUserId').value = userId;
            document.getElementById('editFirstName').value = firstName;
            document.getElementById('editLastName').value = lastName;
            document.getElementById('editRole').value = role;
            document.getElementById('editEmail').value = email;
            
            // Zaktualizuj action formularza
            editUserForm.action = `/users/${userId}/edit`;
            
            // Pokaż modal
            openModal();
        });
    });
    
    // Zamknij modal
    closeModalBtn.addEventListener('click', closeModal);
    cancelModalBtn.addEventListener('click', closeModal);
    
    // Zamknij modal po kliknięciu w overlay
    modalOverlay.addEventListener('click', closeModal);
    
    // Zamknij modal po naciśnięciu ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && editModal.classList.contains('active')) {
            closeModal();
        }
    });
    
    function openModal() {
        modalOverlay.classList.add('active');
        editModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
    
    function closeModal() {
        modalOverlay.classList.remove('active');
        editModal.classList.remove('active');
        document.body.style.overflow = '';
    }
}

/* ============================================================================
   FILTROWANIE WYSZUKIWANIA
   ============================================================================ */
function initSearchFilter() {
    const searchInput = document.getElementById('searchInput');
    const tableRows = document.querySelectorAll('.table-row');
    
    if (!searchInput || !tableRows.length) return;
    
    searchInput.addEventListener('input', function() {
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
   FLASH MESSAGES (auto-hide)
   ============================================================================ */
function initFlashMessages() {
    const flashMessages = document.querySelectorAll('.flash');
    
    flashMessages.forEach(function(flash) {
        // Auto-hide po 5 sekundach
        setTimeout(function() {
            flash.style.opacity = '0';
            flash.style.transition = 'opacity 0.5s ease';
            
            setTimeout(function() {
                flash.remove();
            }, 500);
        }, 5000);
        
        // Możliwość zamknięcia po kliknięciu
        flash.style.cursor = 'pointer';
        flash.addEventListener('click', function() {
            this.style.opacity = '0';
            this.style.transition = 'opacity 0.3s ease';
            
            setTimeout(function() {
                flash.remove();
            }, 300);
        });
    });
}

/* ============================================================================
   ANIMACJE CSS (dodatkowe)
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
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }
`;
document.head.appendChild(style);

console.log('✓ Users Management JS załadowany pomyślnie!');