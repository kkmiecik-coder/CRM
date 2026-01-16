// app/modules/users/static/js/users.js
/**
 * JavaScript dla modułu users
 * Obsługa formularzy, modali i interakcji użytkownika
 */

document.addEventListener('DOMContentLoaded', function() {
    
    // ========================================================================
    // POKAZYWANIE/UKRYWANIE MNOŻNIKA PARTNERA PRZY ZAPROSZENIU
    // ========================================================================
    
    const inviteRoleSelect = document.getElementById('invite_role');
    const inviteMultiplierRow = document.getElementById('inviteMultiplierRow');
    
    if (inviteRoleSelect && inviteMultiplierRow) {
        inviteRoleSelect.addEventListener('change', function() {
            if (this.value === 'partner') {
                inviteMultiplierRow.style.display = 'block';
            } else {
                inviteMultiplierRow.style.display = 'none';
            }
        });
        
        // Sprawdź na starcie
        if (inviteRoleSelect.value === 'partner') {
            inviteMultiplierRow.style.display = 'block';
        }
    }
    
    
    // ========================================================================
    // MODAL EDYCJI UŻYTKOWNIKA
    // ========================================================================
    
    const modalOverlay = document.getElementById('modal-overlay');
    const editModal = document.getElementById('editModal');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const cancelModalBtn = document.getElementById('cancelModalBtn');
    const editUserForm = document.getElementById('editUserForm');
    
    // Otwórz modal
    document.querySelectorAll('.open-edit-modal').forEach(button => {
        button.addEventListener('click', function() {
            const userId = this.dataset.userId;
            const firstName = this.dataset.firstName || '';
            const lastName = this.dataset.lastName || '';
            const role = this.dataset.role || 'user';
            const email = this.dataset.email || '';
            
            // Wypełnij formularz
            document.getElementById('editUserId').value = userId;
            document.getElementById('editFirstName').value = firstName;
            document.getElementById('editLastName').value = lastName;
            document.getElementById('editRole').value = role;
            document.getElementById('editEmail').value = email;
            
            // Aktualizuj action formularza
            editUserForm.action = `/users/${userId}/edit`;
            
            // Pokaż modal
            modalOverlay.style.display = 'block';
            editModal.style.display = 'block';
        });
    });
    
    // Zamknij modal
    function closeModal() {
        if (modalOverlay) modalOverlay.style.display = 'none';
        if (editModal) editModal.style.display = 'none';
    }
    
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', closeModal);
    }
    
    if (cancelModalBtn) {
        cancelModalBtn.addEventListener('click', closeModal);
    }
    
    if (modalOverlay) {
        modalOverlay.addEventListener('click', closeModal);
    }
    
    // Zamknij modal klawiszem ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeModal();
        }
    });
    
    
    // ========================================================================
    // POTWIERDZENIA PRZED USUNIĘCIEM/DEZAKTYWACJĄ
    // ========================================================================
    
    // Obsłużone przez onsubmit w HTML, ale możemy dodać bardziej zaawansowane
    
    
    // ========================================================================
    // WALIDACJA FORMULARZA ZAPROSZENIA
    // ========================================================================
    
    const inviteForm = document.querySelector('form[action*="invite"]');
    
    if (inviteForm) {
        inviteForm.addEventListener('submit', function(e) {
            const emailInput = document.getElementById('invite_email');
            
            if (!emailInput || !emailInput.value) {
                e.preventDefault();
                alert('Adres email jest wymagany');
                return false;
            }
            
            // Prosta walidacja emaila
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(emailInput.value)) {
                e.preventDefault();
                alert('Proszę podać prawidłowy adres email');
                return false;
            }
        });
    }
    
    
    // ========================================================================
    // AUTO-HIDE FLASH MESSAGES
    // ========================================================================
    
    const flashMessages = document.querySelectorAll('.flash');
    
    flashMessages.forEach(function(flash) {
        // Automatycznie ukryj po 5 sekundach
        setTimeout(function() {
            flash.style.opacity = '0';
            flash.style.transition = 'opacity 0.5s';
            
            setTimeout(function() {
                flash.style.display = 'none';
            }, 500);
        }, 5000);
    });
    
});