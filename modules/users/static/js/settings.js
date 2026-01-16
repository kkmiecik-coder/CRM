/* ============================================================================
   SETTINGS.JS - Obsługa strony ustawień użytkownika
   Wood Power CRM - Moduł Users
   ============================================================================ */

document.addEventListener('DOMContentLoaded', function() {
    initAvatarSelection();
    initAvatarUpload();
    initPasswordValidation();
    initFlashMessages();
});

/* ============================================================================
   WYBÓR DOMYŚLNEGO AVATARA
   ============================================================================ */
function initAvatarSelection() {
    const avatarOptions = document.querySelectorAll('.avatar-option');
    const defaultAvatarField = document.getElementById('defaultAvatarField');
    const avatarFileInput = document.getElementById('avatarFileInput');
    const uploadPreview = document.getElementById('uploadPreview');

    // Zaznacz obecnie wybrany avatar na starcie
    avatarOptions.forEach(option => {
        if (option.dataset.selected === 'true') {
            option.classList.add('selected');
            defaultAvatarField.value = option.dataset.avatarValue;
        }
    });

    // Obsługa kliknięcia w domyślny avatar
    avatarOptions.forEach(option => {
        option.addEventListener('click', function() {
            // Usuń zaznaczenie ze wszystkich
            avatarOptions.forEach(opt => opt.classList.remove('selected'));
            
            // Zaznacz kliknięty
            this.classList.add('selected');
            
            // Zapisz wartość
            const avatarValue = this.dataset.avatarValue;
            defaultAvatarField.value = avatarValue;
            
            // Wyczyść upload file i jego podgląd
            avatarFileInput.value = '';
            uploadPreview.style.display = 'none';
            
            console.log('✓ Wybrany domyślny avatar:', avatarValue);
        });
    });
}

/* ============================================================================
   UPLOAD WŁASNEGO AVATARA (Drag & Drop + Click)
   ============================================================================ */
function initAvatarUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const avatarFileInput = document.getElementById('avatarFileInput');
    const uploadPreview = document.getElementById('uploadPreview');
    const previewImage = document.getElementById('previewImage');
    const cancelUpload = document.getElementById('cancelUpload');
    const defaultAvatarField = document.getElementById('defaultAvatarField');
    const avatarOptions = document.querySelectorAll('.avatar-option');

    // Kliknięcie w upload area - otwórz file picker
    uploadArea.addEventListener('click', function() {
        avatarFileInput.click();
    });

    // Zapobiegnij domyślnej akcji dla drag & drop
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Highlight podczas przeciągania
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, function() {
            uploadArea.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, function() {
            uploadArea.classList.remove('drag-over');
        });
    });

    // Obsługa drop
    uploadArea.addEventListener('drop', function(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        if (files.length > 0) {
            avatarFileInput.files = files;
            handleFileSelect(files[0]);
        }
    });

    // Obsługa wyboru pliku przez input
    avatarFileInput.addEventListener('change', function(e) {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    // Funkcja obsługująca wybrany plik
    function handleFileSelect(file) {
        // Walidacja typu pliku
        if (!file.type.match('image.*')) {
            alert('⚠️ Proszę wybrać plik graficzny (PNG, JPG, GIF)');
            return;
        }

        // Walidacja rozmiaru (2MB)
        const maxSize = 2 * 1024 * 1024; // 2MB w bajtach
        if (file.size > maxSize) {
            alert('⚠️ Plik jest za duży. Maksymalny rozmiar to 2MB');
            return;
        }

        // Wyświetl podgląd
        const reader = new FileReader();
        reader.onload = function(event) {
            previewImage.src = event.target.result;
            uploadPreview.style.display = 'block';
            uploadArea.style.display = 'none';
            
            // Wyczyść zaznaczenie domyślnych avatarów
            avatarOptions.forEach(opt => opt.classList.remove('selected'));
            defaultAvatarField.value = '';
            
            console.log('✓ Wczytano własny avatar:', file.name);
        };
        reader.readAsDataURL(file);
    }

    // Anulowanie uploadu
    cancelUpload.addEventListener('click', function() {
        avatarFileInput.value = '';
        uploadPreview.style.display = 'none';
        uploadArea.style.display = 'block';
        defaultAvatarField.value = '';
        
        console.log('✗ Anulowano upload avatara');
    });
}

/* ============================================================================
   WALIDACJA HASŁA (na żywo)
   ============================================================================ */
function initPasswordValidation() {
    const passwordForm = document.getElementById('passwordForm');
    const newPassword = document.getElementById('new_password');
    const confirmPassword = document.getElementById('confirm_password');
    const passwordError = document.getElementById('passwordError');

    if (!passwordForm || !newPassword || !confirmPassword) {
        return; // Brak formularza hasła na stronie
    }

    // Walidacja podczas wpisywania w pole "Powtórz nowe hasło"
    confirmPassword.addEventListener('input', function() {
        validatePasswordMatch();
    });

    // Walidacja podczas wpisywania w pole "Nowe hasło"
    newPassword.addEventListener('input', function() {
        if (confirmPassword.value) {
            validatePasswordMatch();
        }
    });

    // Walidacja przed wysłaniem formularza
    passwordForm.addEventListener('submit', function(e) {
        if (!validatePasswordMatch()) {
            e.preventDefault();
            confirmPassword.focus();
        }
    });

    function validatePasswordMatch() {
        const newPass = newPassword.value;
        const confirmPass = confirmPassword.value;

        if (confirmPass === '') {
            passwordError.style.display = 'none';
            confirmPassword.style.borderColor = '#e9ecef';
            return true;
        }

        if (newPass !== confirmPass) {
            passwordError.textContent = '⚠️ Hasła nie są identyczne';
            passwordError.style.display = 'block';
            confirmPassword.style.borderColor = '#dc3545';
            return false;
        } else {
            passwordError.style.display = 'none';
            confirmPassword.style.borderColor = '#28a745';
            return true;
        }
    }
}

/* ============================================================================
   OBSŁUGA FLASH MESSAGES (auto-hide)
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
   DODATKOWE FUNKCJE POMOCNICZE
   ============================================================================ */

// Animacja przycisku po kliknięciu
document.querySelectorAll('.btn-primary, .btn-secondary').forEach(button => {
    button.addEventListener('click', function(e) {
        // Dodaj efekt "ripple"
        const ripple = document.createElement('span');
        ripple.style.position = 'absolute';
        ripple.style.borderRadius = '50%';
        ripple.style.background = 'rgba(255, 255, 255, 0.6)';
        ripple.style.width = '20px';
        ripple.style.height = '20px';
        ripple.style.animation = 'ripple 0.6s ease-out';
        
        const rect = this.getBoundingClientRect();
        ripple.style.left = (e.clientX - rect.left - 10) + 'px';
        ripple.style.top = (e.clientY - rect.top - 10) + 'px';
        
        this.style.position = 'relative';
        this.style.overflow = 'hidden';
        this.appendChild(ripple);
        
        setTimeout(() => ripple.remove(), 600);
    });
});

// Dodaj animację CSS dla efektu ripple (jeśli nie ma w CSS)
const style = document.createElement('style');
style.textContent = `
    @keyframes ripple {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

console.log('✓ Settings.js załadowany pomyślnie!');