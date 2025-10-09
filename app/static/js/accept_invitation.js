document.addEventListener('DOMContentLoaded', function () {
    // Obsługa wyboru domyślnego avatara
    const defaultAvatars = document.querySelectorAll('.avatar-default');
    const defaultAvatarField = document.getElementById('defaultAvatarField');

    defaultAvatars.forEach(avatar => {
        avatar.addEventListener('click', function () {
            // Odznacz wszystkie
            defaultAvatars.forEach(a => a.classList.remove('selected'));
            // Zaznacz kliknięty
            this.classList.add('selected');
            // Ustaw wartość w hidden input
            defaultAvatarField.value = this.dataset.avatarValue;
            // Wyczyść input pliku i ukryj podgląd własnego avatara
            const fileInput = document.getElementById('avatar_file');
            const ownPreview = document.getElementById('ownPreview');
            if (fileInput) {
                fileInput.value = "";
            }
            if (ownPreview) {
                ownPreview.style.display = "none";
            }
        });
    });

    // Obsługa wgrywania własnego avatara – podgląd
    const avatarInput = document.getElementById('avatar_file');
    const ownPreview = document.getElementById('ownPreview');
    const ownPreviewImg = document.getElementById('ownPreviewImg');

    if (avatarInput) {
        avatarInput.addEventListener('change', function () {
            if (avatarInput.files && avatarInput.files[0]) {
                // Odznacz wszystkie domyślne avatary
                defaultAvatars.forEach(a => a.classList.remove('selected'));
                defaultAvatarField.value = "";
                const reader = new FileReader();
                reader.onload = function (e) {
                    ownPreviewImg.src = e.target.result;
                    ownPreview.style.display = "block";
                }
                reader.readAsDataURL(avatarInput.files[0]);
            } else {
                ownPreview.style.display = "none";
            }
        });
    }

    // Walidacja haseł na żywo
    const passwordInput = document.getElementById('password');
    const password2Input = document.getElementById('password2');
    const passwordError = document.getElementById('passwordError');

    function validatePasswords() {
        if (passwordInput.value && password2Input.value && (passwordInput.value !== password2Input.value)) {
            passwordError.style.display = 'block';
        } else {
            passwordError.style.display = 'none';
        }
    }

    passwordInput.addEventListener('input', validatePasswords);
    password2Input.addEventListener('input', validatePasswords);
});
