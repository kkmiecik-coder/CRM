document.addEventListener('DOMContentLoaded', () => {
    // -----------------------------------------------------
    // 1. Elementy na stronie
    // -----------------------------------------------------
    const form = document.querySelector('.inputs');
    const overlay = document.getElementById('loadingOverlay');

    // Pola logowania
    const emailInput = document.getElementById('email');
    const emailFrame = document.getElementById('emailFrame');
    const emailErrorMsg = emailInput
        ? emailInput.parentElement.nextElementSibling
        : null;

    const passwordInput = document.getElementById('password');
    const passwordFrame = document.getElementById('passwordFrame');
    const passwordErrorMsg = passwordInput
        ? passwordInput.parentElement.nextElementSibling
        : null;

    // Pola resetu hasła (jeśli istnieją)
    const newPasswordInput = document.getElementById('new_password');
    const newPasswordFrame = newPasswordInput
        ? newPasswordInput.closest('.input-frame')
        : null;
    const newPasswordErrorMsg = newPasswordInput
        ? newPasswordInput.parentElement.nextElementSibling
        : null;

    const repeatPasswordInput = document.getElementById('repeat_password');
    const repeatPasswordFrame = repeatPasswordInput
        ? repeatPasswordInput.closest('.input-frame')
        : null;
    const repeatPasswordErrorMsg = repeatPasswordInput
        ? repeatPasswordInput.parentElement.nextElementSibling
        : null;

    // Przycisk (np. .login-button)
    const submitButton = document.querySelector('.login-button')
        || document.querySelector('.submit-button');

    // -----------------------------------------------------
    // 2. Obsługa focus/blur/input
    // -----------------------------------------------------
    function handleFocus(input, frame) {
        // Usuwamy stany i dodajemy "active"
        frame.classList.remove('static', 'error', 'correct-waiting');
        frame.classList.add('active');
    }

    function handleBlur(input, frame) {
        // Jeśli pole jest puste, wróć do "static"
        if (input.value.trim() === '') {
            frame.classList.remove('active', 'error', 'correct-waiting', 'has-content');
            frame.classList.add('static');
        }
        // Jeśli nie jest puste, walidacja w funkcji validateXXX ustawi .error/.correct-waiting
    }

    function handleInput(input, frame) {
        // Gdy jest cokolwiek w polu, label ma być u góry
        if (input.value.trim() !== '') {
            frame.classList.add('has-content');
        } else {
            frame.classList.remove('has-content');
        }
    }

    // -----------------------------------------------------
    // 3. Funkcje walidacji (przykład)
    // -----------------------------------------------------
    function validateEmail() {
        if (!emailInput || !emailFrame) return;
        const value = emailInput.value.trim();

        // Sprawdzamy, czy jest błąd serwerowy
        const serverEmailError = emailFrame.getAttribute('data-server-error');
        if (serverEmailError) {
            // Mamy błąd serwerowy – jeśli user jeszcze nie zmienił maila,
            // nie nadpisuj stanu. Ale jak user wpisze coś nowego (zdarzenie input),
            // usuniemy data-server-error i przejdziemy do reszty walidacji.
            return;
        }

        // Dalej walidacja front-endowa: np. sprawdzamy czy jest '@'
        if (value === '') {
            // ...
        } else if (value.includes('@')) {
            emailFrame.classList.remove('error', 'active', 'static');
            emailFrame.classList.add('correct-waiting', 'has-content');
            if (emailErrorMsg) emailErrorMsg.style.display = 'none';
        } else {
            emailFrame.classList.remove('correct-waiting', 'active', 'static');
            emailFrame.classList.add('error', 'has-content');
            if (emailErrorMsg) {
                emailErrorMsg.textContent = 'Wprowadź poprawny adres e-mail.';
                emailErrorMsg.style.display = 'block';
            }
        }
        checkFormValidity();
    }

    function validatePassword() {
        if (!passwordInput || !passwordFrame) return;
        const value = passwordInput.value.trim();

        if (value === '') {
            // Błąd – puste hasło
            passwordFrame.classList.remove('correct-waiting', 'active', 'static');
            passwordFrame.classList.add('error', 'has-content');
            if (passwordErrorMsg) {
                passwordErrorMsg.textContent = 'To pole jest wymagane.';
                passwordErrorMsg.style.display = 'block';
            }
        } else {
            // OK
            passwordFrame.classList.remove('error', 'active', 'static');
            passwordFrame.classList.add('correct-waiting', 'has-content');
            if (passwordErrorMsg) {
                passwordErrorMsg.style.display = 'none';
            }
        }
        checkFormValidity();
    }

    function validateNewPasswords() {
        if (!newPasswordInput || !repeatPasswordInput
            || !newPasswordFrame || !repeatPasswordFrame) {
            return;
        }
        const newPass = newPasswordInput.value.trim();
        const repeatPass = repeatPasswordInput.value.trim();

        // Walidacja "Nowe hasło"
        if (newPass === '') {
            newPasswordFrame.classList.remove('correct-waiting', 'active', 'static');
            newPasswordFrame.classList.add('error', 'has-content');
            if (newPasswordErrorMsg) {
                newPasswordErrorMsg.textContent = 'To pole jest wymagane.';
                newPasswordErrorMsg.style.display = 'block';
            }
        } else {
            newPasswordFrame.classList.remove('error', 'active', 'static');
            newPasswordFrame.classList.add('correct-waiting', 'has-content');
            if (newPasswordErrorMsg) {
                newPasswordErrorMsg.style.display = 'none';
            }
        }

        // Walidacja "Powtórz hasło"
        if (repeatPass === '') {
            repeatPasswordFrame.classList.remove('correct-waiting', 'active', 'static');
            repeatPasswordFrame.classList.add('error', 'has-content');
            if (repeatPasswordErrorMsg) {
                repeatPasswordErrorMsg.textContent = 'To pole jest wymagane.';
                repeatPasswordErrorMsg.style.display = 'block';
            }
        } else {
            // Jeśli oba pola wypełnione, sprawdzamy czy są identyczne
            if (newPass !== '' && repeatPass !== '' && newPass !== repeatPass) {
                repeatPasswordFrame.classList.remove('correct-waiting', 'active', 'static');
                repeatPasswordFrame.classList.add('error', 'has-content');
                if (repeatPasswordErrorMsg) {
                    repeatPasswordErrorMsg.textContent = 'Hasła muszą być identyczne.';
                    repeatPasswordErrorMsg.style.display = 'block';
                }
            } else {
                repeatPasswordFrame.classList.remove('error', 'active', 'static');
                repeatPasswordFrame.classList.add('correct-waiting', 'has-content');
                if (repeatPasswordErrorMsg) {
                    repeatPasswordErrorMsg.style.display = 'none';
                }
            }
        }
        checkFormValidity();
    }

    // -----------------------------------------------------
    // 4. Sprawdzanie, czy formularz można wysłać
    // -----------------------------------------------------
    function checkFormValidity() {
        let emailIsOk = true;
        if (emailFrame) {
            emailIsOk = emailFrame.classList.contains('correct-waiting')
                || emailFrame.classList.contains('static');
        }

        let passwordIsOk = true;
        if (passwordFrame) {
            passwordIsOk = passwordFrame.classList.contains('correct-waiting')
                || passwordFrame.classList.contains('static');
        }

        let newPassIsOk = true;
        if (newPasswordFrame) {
            newPassIsOk = newPasswordFrame.classList.contains('correct-waiting');
        }

        let repeatPassIsOk = true;
        if (repeatPasswordFrame) {
            repeatPassIsOk = repeatPasswordFrame.classList.contains('correct-waiting');
        }

        const allValid = emailIsOk && passwordIsOk && newPassIsOk && repeatPassIsOk;

        if (submitButton) {
            if (allValid) {
                submitButton.classList.remove('disabled');
                submitButton.removeAttribute('disabled');
            } else {
                submitButton.classList.add('disabled');
                submitButton.setAttribute('disabled', 'true');
            }
        }
    }

    // -----------------------------------------------------
    // 5. Podpinanie zdarzeń
    // -----------------------------------------------------
    if (emailInput && emailFrame) {
        emailInput.addEventListener('focus', () => handleFocus(emailInput, emailFrame));
        emailInput.addEventListener('blur', () => {
            handleBlur(emailInput, emailFrame);
            validateEmail();
        });
        emailInput.addEventListener('input', () => {
            handleInput(emailInput, emailFrame);
            validateEmail();
        });
    }

    if (passwordInput && passwordFrame) {
        passwordInput.addEventListener('focus', () => handleFocus(passwordInput, passwordFrame));
        passwordInput.addEventListener('blur', () => {
            handleBlur(passwordInput, passwordFrame);
            validatePassword();
        });
        passwordInput.addEventListener('input', () => {
            handleInput(passwordInput, passwordFrame);
            validatePassword();
        });
    }

    if (newPasswordInput && newPasswordFrame) {
        newPasswordInput.addEventListener('focus', () => handleFocus(newPasswordInput, newPasswordFrame));
        newPasswordInput.addEventListener('blur', () => {
            handleBlur(newPasswordInput, newPasswordFrame);
            validateNewPasswords();
        });
        newPasswordInput.addEventListener('input', () => {
            handleInput(newPasswordInput, newPasswordFrame);
            validateNewPasswords();
        });
    }

    if (repeatPasswordInput && repeatPasswordFrame) {
        repeatPasswordInput.addEventListener('focus', () => handleFocus(repeatPasswordInput, repeatPasswordFrame));
        repeatPasswordInput.addEventListener('blur', () => {
            handleBlur(repeatPasswordInput, repeatPasswordFrame);
            validateNewPasswords();
        });
        repeatPasswordInput.addEventListener('input', () => {
            handleInput(repeatPasswordInput, repeatPasswordFrame);
            validateNewPasswords();
        });
    }

    // -----------------------------------------------------
    // 6. Obsługa wysyłania formularza
    // -----------------------------------------------------
    if (form) {
        form.addEventListener('submit', (event) => {
            // Wymuszenie walidacji
            validateEmail();
            validatePassword();
            validateNewPasswords();

            // Sprawdzamy przycisk (czy włączyć/wyłączyć)
            checkFormValidity();

            // Sprawdzanie, czy nie ma żadnego .error
            const frames = [emailFrame, passwordFrame, newPasswordFrame, repeatPasswordFrame].filter(Boolean);
            const hasError = frames.some(frame => frame.classList.contains('error'));

            if (hasError) {
                event.preventDefault();
                alert('Popraw błędy przed wysłaniem formularza.');
            } else {
                // Jeśli wszystko ok – pokazujemy overlay
                if (overlay) {
                    setTimeout(() => {
                        overlay.style.display = 'flex';
                    }, 100);
                }
            }
        });
    }

    // -----------------------------------------------------
    // 7. Inicjalizacja przy starcie
    // -----------------------------------------------------
    // Dodajemy sprawdzenie dla inputa email (np. w resetowaniu hasła)
    if (emailInput && emailFrame) {
        emailInput.addEventListener('focus', () => handleFocus(emailInput, emailFrame));
        emailInput.addEventListener('blur', () => {
            handleBlur(emailInput, emailFrame);
            validateEmail();
        });
        emailInput.addEventListener('input', () => {
            handleInput(emailInput, emailFrame);

            // Usuwamy błąd serwerowy, jeśli był
            emailFrame.removeAttribute('data-server-error');
            // Usuwamy klasę .error, by ponownie mogła zadziałać walidacja front-end
            emailFrame.classList.remove('error');

            // Teraz wywołujemy walidację
            validateEmail();
            checkFormValidity();
        });
    }
});
