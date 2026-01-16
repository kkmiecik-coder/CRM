document.addEventListener('DOMContentLoaded', function () {
    const tabs = document.querySelectorAll('.tab[data-tab]');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', function () {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            this.classList.add('active');
            const tabId = this.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });
});

document.addEventListener('DOMContentLoaded', function () {
    // Znajdź przyciski "Edytuj"
    const editButtons = document.querySelectorAll('.open-edit-modal');
    const modalOverlay = document.getElementById('modal-overlay');
    const editModal = document.getElementById('editModal');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const cancelModalBtn = document.getElementById('cancelModalBtn');

    // Pola formularza w modalu
    const editUserId = document.getElementById('editUserId');
    const editFirstName = document.getElementById('editFirstName');
    const editLastName = document.getElementById('editLastName');
    const editRole = document.getElementById('editRole');
    const editEmail = document.getElementById('editEmail');

    editButtons.forEach(btn => {
        btn.addEventListener('click', function () {
            // Pobierz dane z data-*
            const userId = this.dataset.userId;
            const firstName = this.dataset.firstName || '';
            const lastName = this.dataset.lastName || '';
            const role = this.dataset.role || 'user';
            const email = this.dataset.email || '';

            // Ustaw w formularzu
            editUserId.value = userId;
            editFirstName.value = firstName;
            editLastName.value = lastName;
            editRole.value = role;
            editEmail.value = email;

            // Pokaż modal
            modalOverlay.style.display = 'block';
            editModal.style.display = 'block';
        });
    });

    // Zamknięcie modala (X lub Anuluj)
    function closeModal() {
        modalOverlay.style.display = 'none';
        editModal.style.display = 'none';
    }
    if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
    if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);
});

document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.querySelector('.upload-avatar');
    const ownPreview = document.querySelector('.own-preview');
    const ownPreviewImg = document.getElementById('ownPreviewImg');
    const defaultAvatars = document.querySelectorAll('.avatar-default');
    const defaultAvatarField = document.getElementById('defaultAvatarField');

    if (fileInput && ownPreview && ownPreviewImg) {
        fileInput.addEventListener('change', function() {
            if (fileInput.files && fileInput.files[0]) {
                // Usuń zaznaczenie domyślnych avatarów
                defaultAvatars.forEach(avatar => avatar.classList.remove('selected'));
                if (defaultAvatarField) {
                    defaultAvatarField.value = "";
                }
                const reader = new FileReader();
                reader.onload = function(e) {
                    ownPreviewImg.src = e.target.result;
                    ownPreview.style.display = 'block';
                };
                reader.readAsDataURL(fileInput.files[0]);
            } else {
                ownPreview.style.display = 'none';
            }
        });
    }

    // Obsługa kliknięcia w domyślne avatary
    if (defaultAvatars && defaultAvatarField) {
        defaultAvatars.forEach(avatar => {
            avatar.addEventListener('click', function() {
                // Wyczyść input pliku
                if (fileInput) {
                    fileInput.value = "";
                }
                // Odznacz wszystkie, a zaznacz kliknięty
                defaultAvatars.forEach(a => a.classList.remove('selected'));
                this.classList.add('selected');
                // Ustaw wartość w ukrytym polu
                defaultAvatarField.value = this.dataset.avatarValue;
                // Ukryj podgląd własnego avatara
                if (ownPreview) {
                    ownPreview.style.display = 'none';
                }
            });
        });
    }
});

document.addEventListener('DOMContentLoaded', () => {
    // Znajdź pola dla nowych haseł w formularzu zmiany hasła
    const newPasswordInput = document.getElementById('new_password');
    const confirmPasswordInput = document.getElementById('confirm_password');

    // Zakładamy, że w HTML obok pola potwierdzenia hasła mamy element,
    // w którym będzie komunikat błędu – nadajmy mu np. id "confirmPasswordError"
    const confirmPasswordErrorMsg = document.getElementById('confirmPasswordError');

    // Funkcja walidująca, czy nowe hasła są identyczne
    function validateNewPasswords() {
        const newPass = newPasswordInput.value.trim();
        const confirmPass = confirmPasswordInput.value.trim();

        // Jeśli oba pola nie są puste, sprawdzamy równość
        if (newPass !== '' && confirmPass !== '') {
            if (newPass !== confirmPass) {
                // Wyświetlamy komunikat błędu
                if (confirmPasswordErrorMsg) {
                    confirmPasswordErrorMsg.textContent = 'Hasła muszą być identyczne.';
                    confirmPasswordErrorMsg.style.display = 'block';
                }
                // Możemy dodać klasę błędu do kontenera, jeśli potrzebujemy
                confirmPasswordInput.classList.add('error');
            } else {
                // Usuwamy komunikat błędu, jeśli hasła się zgadzają
                if (confirmPasswordErrorMsg) {
                    confirmPasswordErrorMsg.style.display = 'none';
                }
                confirmPasswordInput.classList.remove('error');
            }
        } else {
            // Gdy jedno z pól jest puste, ukrywamy komunikat błędu
            if (confirmPasswordErrorMsg) {
                confirmPasswordErrorMsg.style.display = 'none';
            }
            confirmPasswordInput.classList.remove('error');
        }
    }

    // Podpinamy walidację na zdarzenia "input"
    if (newPasswordInput && confirmPasswordInput) {
        newPasswordInput.addEventListener('input', validateNewPasswords);
        confirmPasswordInput.addEventListener('input', validateNewPasswords);
    }
});

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.toggle-entry').forEach(entry => {
        entry.addEventListener('click', () => {
            const parent = entry.closest('.changelog-entry');
            const content = parent.querySelector('.animated-toggle');
            const allEntries = document.querySelectorAll('.changelog-entry');

            allEntries.forEach(other => {
                if (other !== parent && other.classList.contains('open')) {
                    const otherContent = other.querySelector('.animated-toggle');
                    otherContent.style.maxHeight = otherContent.scrollHeight + 'px';
                    requestAnimationFrame(() => {
                        otherContent.style.maxHeight = '0';
                    });
                    other.classList.remove('open');
                }
            });

            if (parent.classList.contains('open')) {
                // Zamykanie klikniętego
                content.style.maxHeight = content.scrollHeight + 'px';
                requestAnimationFrame(() => {
                    content.style.maxHeight = '0';
                });
                parent.classList.remove('open');
            } else {
                // Otwieranie nowego
                content.style.maxHeight = content.scrollHeight + 'px';
                parent.classList.add('open');
            }
        });
    });
});


document.addEventListener('DOMContentLoaded', function () {
    const inviteRole = document.getElementById('invite_role');
    const inviteMultiplierRow = document.getElementById('inviteMultiplierRow');
    const editRole = document.getElementById('editRole');
    const editMultiplierRow = document.getElementById('partnerMultiplierRow');

    if (inviteRole) {
        inviteRole.addEventListener('change', function () {
            inviteMultiplierRow.style.display = this.value === 'partner' ? 'block' : 'none';
        });

        // Pokaż od razu, jeśli "partner" jest domyślnie wybrane (np. po błędzie formularza)
        if (inviteRole.value === 'partner') {
            inviteMultiplierRow.style.display = 'block';
        }
    }

    if (editRole) {
        editRole.addEventListener('change', function () {
            editMultiplierRow.style.display = this.value === 'partner' ? 'block' : 'none';
        });

        // Pokaż od razu, jeśli "partner" jest ustawione
        if (editRole.value === 'partner') {
            editMultiplierRow.style.display = 'block';
        }
    }
});