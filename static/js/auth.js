/* ============================================================================
   AUTH.JS - Complete functionality with Dark Mode (18:00-6:00)
   Wood Power CRM
   ============================================================================ */

document.addEventListener('DOMContentLoaded', () => {
    // Initialize dark mode first
    initDarkMode();

    // Check which page we're on and initialize accordingly
    const loginForm = document.getElementById('loginForm');
    const resetRequestForm = document.getElementById('resetRequestForm');
    const resetPasswordForm = document.getElementById('resetPasswordForm');
    const logoutTime = document.getElementById('logoutTime');

    if (loginForm) {
        initLoginPage();
    }

    if (resetRequestForm) {
        initResetRequestPage();
    }

    if (resetPasswordForm) {
        initResetPasswordPage();
    }

    if (logoutTime) {
        initLoggedOutPage();
    }
});

/* ============================================================================
   DARK MODE - Automatic between 18:00 and 6:00
   ============================================================================ */

function initDarkMode() {
    const currentHour = new Date().getHours();
    
    // Dark mode active between 18:00 (6 PM) and 6:00 (6 AM)
    if (currentHour >= 18 || currentHour < 6) {
        document.body.classList.add('dark-mode');
        console.log('[Dark Mode] Activated (current hour: ' + currentHour + ')');
    } else {
        document.body.classList.remove('dark-mode');
        console.log('[Dark Mode] Deactivated (current hour: ' + currentHour + ')');
    }

    // Optional: Check every minute in case user stays on page past transition time
    setInterval(() => {
        const hour = new Date().getHours();
        const isDarkTime = hour >= 18 || hour < 6;
        const isDarkMode = document.body.classList.contains('dark-mode');

        if (isDarkTime && !isDarkMode) {
            document.body.classList.add('dark-mode');
            console.log('[Dark Mode] Auto-activated at ' + hour + ':00');
        } else if (!isDarkTime && isDarkMode) {
            document.body.classList.remove('dark-mode');
            console.log('[Dark Mode] Auto-deactivated at ' + hour + ':00');
        }
    }, 60000); // Check every minute
}

/* ============================================================================
   LOGIN PAGE
   ============================================================================ */

function initLoginPage() {
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const emailGroup = document.getElementById('emailGroup');
    const passwordGroup = document.getElementById('passwordGroup');
    const submitButton = document.getElementById('submitButton');
    const togglePassword = document.getElementById('togglePassword');
    const loginForm = document.getElementById('loginForm');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // Password toggle functionality
    if (togglePassword && passwordInput) {
        togglePassword.addEventListener('click', () => {
            const type = passwordInput.type === 'password' ? 'text' : 'password';
            passwordInput.type = type;
            togglePassword.textContent = type === 'password' ? '👁️' : '🙈';
        });
    }

    // Email validation
    if (emailInput) {
        emailInput.addEventListener('input', () => {
            validateEmail(emailInput, emailGroup);
            checkFormValidity(emailInput, passwordInput, submitButton);
        });

        emailInput.addEventListener('blur', () => {
            validateEmail(emailInput, emailGroup);
        });
    }

    // Password validation
    if (passwordInput) {
        passwordInput.addEventListener('input', () => {
            validatePassword(passwordInput, passwordGroup);
            checkFormValidity(emailInput, passwordInput, submitButton);
        });

        passwordInput.addEventListener('blur', () => {
            validatePassword(passwordInput, passwordGroup);
        });
    }

    // Fix dla autofill - sprawdzaj co 100ms przez 20 sekund
    if (emailInput && passwordInput) {
        let checkCount = 0;
        const checkAutofill = setInterval(() => {
            // Chrome/Safari/Edge autofill detection
            
            // EMAIL FIELD
            if (emailInput.matches(':-webkit-autofill')) {
                // Ma autofill - podnieś label
                emailInput.parentElement.classList.add('has-autofill');
            } else if (emailInput.value.trim() === '') {
                // Nie ma autofill i pole puste - opuść label
                emailInput.parentElement.classList.remove('has-autofill');
            }
            
            // PASSWORD FIELD
            if (passwordInput.matches(':-webkit-autofill')) {
                // Ma autofill - podnieś label
                passwordInput.parentElement.classList.add('has-autofill');
            } else if (passwordInput.value.trim() === '') {
                // Nie ma autofill i pole puste - opuść label
                passwordInput.parentElement.classList.remove('has-autofill');
            }
            
            checkCount++;
            if (checkCount > 200) clearInterval(checkAutofill); // Stop po 20 sekundach
        }, 100);
    }

    // Form submit
    if (loginForm) {
        loginForm.addEventListener('submit', (e) => {
            if (loadingOverlay) {
                loadingOverlay.classList.add('active');
            }
        });
    }

    // Check form validity on page load (for pre-filled values)
    if (emailInput && passwordInput && submitButton) {
        checkFormValidity(emailInput, passwordInput, submitButton);
    }
}

/* ============================================================================
   RESET PASSWORD REQUEST PAGE
   ============================================================================ */

function initResetRequestPage() {
    const emailInput = document.getElementById('email');
    const emailGroup = document.getElementById('emailGroup');
    const submitButton = document.getElementById('submitButton');
    const resetRequestForm = document.getElementById('resetRequestForm');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // Email validation
    if (emailInput) {
        emailInput.addEventListener('input', () => {
            validateEmail(emailInput, emailGroup);
            checkResetFormValidity(emailInput, submitButton);
        });

        emailInput.addEventListener('blur', () => {
            validateEmail(emailInput, emailGroup);
        });
    }

    // Form submit
    if (resetRequestForm) {
        resetRequestForm.addEventListener('submit', (e) => {
            if (loadingOverlay) {
                loadingOverlay.classList.add('active');
            }
        });
    }

    // Check form validity on page load
    if (emailInput && submitButton) {
        checkResetFormValidity(emailInput, submitButton);
    }
}

/* ============================================================================
   RESET PASSWORD FORM PAGE (with new password)
   ============================================================================ */

function initResetPasswordPage() {
    const newPasswordInput = document.getElementById('new_password');
    const repeatPasswordInput = document.getElementById('repeat_password');
    const newPasswordGroup = document.getElementById('newPasswordGroup');
    const repeatPasswordGroup = document.getElementById('repeatPasswordGroup');
    const submitButton = document.getElementById('submitButton');
    const toggleNewPassword = document.getElementById('toggleNewPassword');
    const toggleRepeatPassword = document.getElementById('toggleRepeatPassword');
    const resetPasswordForm = document.getElementById('resetPasswordForm');
    const loadingOverlay = document.getElementById('loadingOverlay');

    // Password toggle for new password
    if (toggleNewPassword && newPasswordInput) {
        toggleNewPassword.addEventListener('click', () => {
            const type = newPasswordInput.type === 'password' ? 'text' : 'password';
            newPasswordInput.type = type;
            toggleNewPassword.textContent = type === 'password' ? '👁️' : '🙈';
        });
    }

    // Password toggle for repeat password
    if (toggleRepeatPassword && repeatPasswordInput) {
        toggleRepeatPassword.addEventListener('click', () => {
            const type = repeatPasswordInput.type === 'password' ? 'text' : 'password';
            repeatPasswordInput.type = type;
            toggleRepeatPassword.textContent = type === 'password' ? '👁️' : '🙈';
        });
    }

    // New password validation with requirements
    if (newPasswordInput) {
        newPasswordInput.addEventListener('input', () => {
            validatePasswordWithRequirements(newPasswordInput, newPasswordGroup);
            validatePasswordMatch(newPasswordInput, repeatPasswordInput, repeatPasswordGroup);
            checkResetPasswordFormValidity(newPasswordInput, repeatPasswordInput, submitButton);
        });

        newPasswordInput.addEventListener('blur', () => {
            validatePasswordWithRequirements(newPasswordInput, newPasswordGroup);
        });
    }

    // Repeat password validation
    if (repeatPasswordInput) {
        repeatPasswordInput.addEventListener('input', () => {
            validatePasswordMatch(newPasswordInput, repeatPasswordInput, repeatPasswordGroup);
            checkResetPasswordFormValidity(newPasswordInput, repeatPasswordInput, submitButton);
        });

        repeatPasswordInput.addEventListener('blur', () => {
            validatePasswordMatch(newPasswordInput, repeatPasswordInput, repeatPasswordGroup);
        });
    }

    // Form submit
    if (resetPasswordForm) {
        resetPasswordForm.addEventListener('submit', (e) => {
            if (loadingOverlay) {
                loadingOverlay.classList.add('active');
            }
        });
    }
}

/* ============================================================================
   LOGGED OUT PAGE
   ============================================================================ */

function initLoggedOutPage() {
    const logoutTime = document.getElementById('logoutTime');
    
    if (logoutTime) {
        // Display current time
        const now = new Date();
        const timeString = now.toLocaleTimeString('pl-PL', {
            hour: '2-digit',
            minute: '2-digit'
        });
        logoutTime.textContent = timeString;
    }
}

/* ============================================================================
   VALIDATION FUNCTIONS
   ============================================================================ */

function validateEmail(input, group) {
    if (!input || !group) return false;

    const value = input.value.trim();
    const errorMsg = group.querySelector('.error-message');

    if (value === '') {
        group.classList.remove('success', 'error');
        if (errorMsg) errorMsg.style.display = 'none';
        return false;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (emailRegex.test(value)) {
        group.classList.remove('error');
        group.classList.add('success');
        if (errorMsg) errorMsg.style.display = 'none';
        return true;
    } else {
        group.classList.remove('success');
        group.classList.add('error');
        if (errorMsg) {
            errorMsg.textContent = 'Wprowadź poprawny adres e-mail';
            errorMsg.style.display = 'flex';
        }
        return false;
    }
}

function validatePassword(input, group) {
    if (!input || !group) return false;

    const value = input.value.trim();
    const errorMsg = group.querySelector('.error-message');

    if (value === '') {
        group.classList.remove('success', 'error');
        if (errorMsg) errorMsg.style.display = 'none';
        return false;
    }

    group.classList.remove('error');
    group.classList.add('success');
    if (errorMsg) errorMsg.style.display = 'none';
    return true;
}

function validatePasswordWithRequirements(input, group) {
    if (!input || !group) return false;

    const value = input.value;
    const errorMsg = group.querySelector('.error-message');

    // Password requirements
    const requirements = {
        length: value.length >= 8,
        uppercase: /[A-Z]/.test(value),
        lowercase: /[a-z]/.test(value),
        number: /[0-9]/.test(value)
    };

    // Update requirement indicators
    updateRequirement('req-length', requirements.length);
    updateRequirement('req-uppercase', requirements.uppercase);
    updateRequirement('req-lowercase', requirements.lowercase);
    updateRequirement('req-number', requirements.number);

    // Check if all requirements are met
    const allMet = Object.values(requirements).every(req => req === true);

    if (value === '') {
        group.classList.remove('success', 'error');
        if (errorMsg) errorMsg.style.display = 'none';
        return false;
    }

    if (allMet) {
        group.classList.remove('error');
        group.classList.add('success');
        if (errorMsg) errorMsg.style.display = 'none';
        return true;
    } else {
        group.classList.remove('success');
        group.classList.add('error');
        if (errorMsg && value.length > 0) {
            errorMsg.textContent = 'Hasło nie spełnia wszystkich wymagań';
            errorMsg.style.display = 'flex';
        }
        return false;
    }
}

function updateRequirement(id, met) {
    const requirement = document.getElementById(id);
    if (requirement) {
        if (met) {
            requirement.classList.add('met');
        } else {
            requirement.classList.remove('met');
        }
    }
}

function validatePasswordMatch(newPasswordInput, repeatPasswordInput, group) {
    if (!newPasswordInput || !repeatPasswordInput || !group) return false;

    const newPassword = newPasswordInput.value;
    const repeatPassword = repeatPasswordInput.value;
    const errorMsg = group.querySelector('.error-message');

    if (repeatPassword === '') {
        group.classList.remove('success', 'error');
        if (errorMsg) errorMsg.style.display = 'none';
        return false;
    }

    if (newPassword === repeatPassword) {
        group.classList.remove('error');
        group.classList.add('success');
        if (errorMsg) errorMsg.style.display = 'none';
        return true;
    } else {
        group.classList.remove('success');
        group.classList.add('error');
        if (errorMsg) {
            errorMsg.textContent = 'Hasła muszą być identyczne';
            errorMsg.style.display = 'flex';
        }
        return false;
    }
}

/* ============================================================================
   FORM VALIDITY CHECKS
   ============================================================================ */

function checkFormValidity(emailInput, passwordInput, submitButton) {
    if (!emailInput || !passwordInput || !submitButton) return;

    const emailValid = validateEmail(emailInput, emailInput.closest('.form-group'));
    const passwordValid = passwordInput.value.trim().length > 0;

    if (emailValid && passwordValid) {
        submitButton.disabled = false;
    } else {
        submitButton.disabled = true;
    }
}

function checkResetFormValidity(emailInput, submitButton) {
    if (!emailInput || !submitButton) return;

    const emailValid = validateEmail(emailInput, emailInput.closest('.form-group'));

    if (emailValid) {
        submitButton.disabled = false;
    } else {
        submitButton.disabled = true;
    }
}

function checkResetPasswordFormValidity(newPasswordInput, repeatPasswordInput, submitButton) {
    if (!newPasswordInput || !repeatPasswordInput || !submitButton) return;

    const newPasswordGroup = newPasswordInput.closest('.form-group');
    const repeatPasswordGroup = repeatPasswordInput.closest('.form-group');

    const newPasswordValid = validatePasswordWithRequirements(newPasswordInput, newPasswordGroup);
    const passwordsMatch = validatePasswordMatch(newPasswordInput, repeatPasswordInput, repeatPasswordGroup);

    if (newPasswordValid && passwordsMatch) {
        submitButton.disabled = false;
    } else {
        submitButton.disabled = true;
    }
}