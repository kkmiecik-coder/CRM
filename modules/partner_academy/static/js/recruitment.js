// ============================================================================
// RECRUITMENT.JS - Partner Academy Recruitment Logic
// ============================================================================

// Globalne zmienne
let currentStep = 1;
const totalSteps = 7; // POZOSTAJE 7
const stepLabels = [
    'Rekrutacja',
    'Kim jesteśmy',
    'Korzyści',
    'Produkty',
    'Nasi klienci',
    'Zespół',
    'Formularz'
];

let uploadedFiles = [];
const MAX_FILES = 2;
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB per plik
let formData = {};

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function () {
    setupCooperationCardSelector();
    updateProgress();
    updateNavigationButtons();
    renderMobileProgress();
    setupFileUpload();
    setupFormValidation();
    setupErrorClearing();
});

// ============================================================================
// COOPERATION TYPE CARD SELECTOR
// ============================================================================

function setupCooperationCardSelector() {
    const radioButtons = document.querySelectorAll('input[name="cooperation_type"]');
    // FIX: Zmieniono selektor z '.cooperation-card' na '.cooperation-card-compact'
    const cards = document.querySelectorAll('.cooperation-card-compact');
    const b2bFields = document.getElementById('b2bFields');
    
    if (!radioButtons.length || !b2bFields) return;
    
    radioButtons.forEach(radio => {
        radio.addEventListener('change', function() {
            // Usuń active z wszystkich kart
            cards.forEach(card => card.classList.remove('active'));
            
            // FIX: Zmieniono selektor z '.cooperation-card' na '.cooperation-card-compact'
            const selectedCard = this.closest('.cooperation-card-compact');
            if (selectedCard) {
                selectedCard.classList.add('active');
            }
            
            // Pokaż/ukryj pola B2B
            if (this.value === 'b2b') {
                b2bFields.style.display = 'block';
                // Animacja
                setTimeout(() => {
                    b2bFields.classList.add('show');
                }, 10);

                // Ustaw required dla pól B2B
                setB2BFieldsRequired(true);
            } else {
                b2bFields.classList.remove('show');
                setTimeout(() => {
                    b2bFields.style.display = 'none';
                }, 400);

                // Usuń required z pól B2B i wyczyść błędy
                setB2BFieldsRequired(false);
                clearB2BFieldsErrors();
            }
            // Aktualizuj stan przycisku generowania NDA
            checkGenerateNDAButton();
        });
    });
    
    // Kliknięcie w całą kartę zaznacza radio
    cards.forEach(card => {
        card.addEventListener('click', function(e) {
            if (e.target.type !== 'radio') {
                const radio = this.querySelector('input[type="radio"]');
                if (radio) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change'));
                }
            }
        });
    });
}

function setB2BFieldsRequired(required) {
    const b2bInputs = ['company_name', 'nip', 'company_address', 'company_city', 'company_postal_code'];
    
    b2bInputs.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            if (required) {
                field.setAttribute('required', 'required');
            } else {
                field.removeAttribute('required');
                field.value = ''; // Wyczyść wartość
            }
        }
    });
}

function clearB2BFieldsErrors() {
    const b2bInputs = ['company_name', 'nip', 'regon', 'company_address', 'company_city', 'company_postal_code'];
    
    b2bInputs.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        const errorSpan = document.getElementById(`error_${fieldId}`);
        
        if (field) {
            field.classList.remove('error');
        }
        if (errorSpan) {
            errorSpan.textContent = '';
            errorSpan.style.display = 'none';
        }
    });
}

// ============================================================================
// STEP NAVIGATION
// ============================================================================

function nextStep() {
    // Jeśli jesteśmy na ostatnim kroku (formularz), wywołaj submitForm
    if (currentStep === totalSteps) {
        submitForm();
        return;
    }

    if (currentStep < totalSteps) {
        const oldStep = currentStep;
        currentStep++;
        transitionStep(oldStep, currentStep, 'next');
    }
}

function prevStep() {
    if (currentStep > 1) {
        const oldStep = currentStep;
        currentStep--;
        transitionStep(oldStep, currentStep, 'prev');
    }
}

function goToStep(step) {
    if (step !== currentStep && step >= 1 && step <= totalSteps) {
        const oldStep = currentStep;
        currentStep = step;
        const direction = step > oldStep ? 'next' : 'prev';
        transitionStep(oldStep, currentStep, direction);
    }
}

function transitionStep(oldStep, newStep, direction) {
    const oldContent = document.querySelector(`.step-content[data-step="${oldStep}"]`);
    const newContent = document.querySelector(`.step-content[data-step="${newStep}"]`);

    if (!oldContent || !newContent) return;

    // Usuń poprzednie klasy animacji
    oldContent.classList.remove('slide-in-left', 'slide-in-right', 'slide-out-left', 'slide-out-right');
    newContent.classList.remove('slide-in-left', 'slide-in-right', 'slide-out-left', 'slide-out-right');

    // Dodaj animację wyjścia
    if (direction === 'next') {
        oldContent.classList.add('slide-out-left');
    } else {
        oldContent.classList.add('slide-out-right');
    }

    setTimeout(() => {
        oldContent.classList.remove('active', 'slide-out-left', 'slide-out-right');

        // Dodaj animację wejścia
        if (direction === 'next') {
            newContent.classList.add('slide-in-right');
        } else {
            newContent.classList.add('slide-in-left');
        }

        newContent.classList.add('active');
        updateProgress();
        updateNavigationButtons();
        renderMobileProgress();

        // Przy przejściu na krok z formularzem - sprawdź stan przycisku NDA
        if (newStep === totalSteps) {
            checkGenerateNDAButton();
        }

        // Scroll do góry
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 500);
}

// Zaktualizowana funkcja updateNavigationButtons()
function updateNavigationButtons() {
    const btnBack = document.getElementById('btnBack');
    const btnNext = document.getElementById('btnNext');
    const navButtons = document.getElementById('navButtons');

    if (!btnBack || !btnNext || !navButtons) return;

    // NOWA LOGIKA: Ukryj cały kontener nawigacji na kroku 7 (formularz)
    if (currentStep === totalSteps) {
        navButtons.style.display = 'none';
        return; // Wyjdź z funkcji, reszta nie jest potrzebna
    } else {
        navButtons.style.display = 'flex'; // Pokaż nawigację na innych krokach
    }

    // Logika dla kroków 1-6
    if (currentStep === 1) {
        btnBack.style.display = 'none';
        btnNext.textContent = 'Rozpocznij';
    } else {
        btnBack.style.display = 'flex';
        btnNext.textContent = 'Następny krok';
    }
}

function updateProgress() {
    const steps = document.querySelectorAll('.progress-step');
    const progressFill = document.getElementById('progressFill');

    if (!progressFill) return;

    steps.forEach((step, index) => {
        const stepNumber = index + 1;
        step.classList.remove('active', 'completed');

        if (stepNumber === currentStep) {
            step.classList.add('active');
        } else if (stepNumber < currentStep) {
            step.classList.add('completed');
        }
    });

    const progressPercentage = ((currentStep - 1) / (totalSteps - 1)) * 100;
    progressFill.style.width = `${progressPercentage}%`;
}

function renderMobileProgress() {
    const track = document.getElementById('mobileProgressTrack');
    if (!track) return;

    track.innerHTML = '';

    const steps = [currentStep - 1, currentStep, currentStep + 1].filter(s => s >= 1 && s <= totalSteps);

    steps.forEach(stepNum => {
        const stepDiv = document.createElement('div');
        stepDiv.className = 'mobile-step';

        if (stepNum < currentStep) {
            stepDiv.classList.add('prev');
        } else if (stepNum === currentStep) {
            stepDiv.classList.add('current');
        } else {
            stepDiv.classList.add('next');
        }

        stepDiv.innerHTML = `
            <div class="mobile-step-number">Krok ${stepNum} z ${totalSteps}</div>
            <div class="mobile-step-label">${stepLabels[stepNum - 1]}</div>
        `;

        track.appendChild(stepDiv);
    });
}

// ============================================================================
// FORM VALIDATION
// ============================================================================

function setupFormValidation() {
    const form = document.getElementById('applicationForm');
    if (!form) return;

    // Walidacja w czasie rzeczywistym dla każdego pola
    const fields = form.querySelectorAll('input, textarea, select');
    fields.forEach(field => {
        field.addEventListener('blur', function () {
            validateField(this);
        });

        field.addEventListener('input', function () {
            // Usuń błąd podczas wpisywania
            const errorSpan = document.getElementById(`error_${this.id}`);
            if (errorSpan) {
                errorSpan.textContent = '';
                errorSpan.style.display = 'none';
            }
            this.classList.remove('error');
            // Sprawdź czy przycisk NDA może być aktywny
            checkGenerateNDAButton();
        });

        field.addEventListener('change', function () {
            checkGenerateNDAButton();
        });
    });

    // Początkowe sprawdzenie stanu przycisku
    checkGenerateNDAButton();
}

// ============================================================================
// NDA BUTTON STATE (disabled dopóki formularz niekompletny)
// ============================================================================

function isFieldFormatValid(field) {
    const value = field.value.trim();
    if (!value) return false;

    // Email
    if (field.type === 'email') {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
    }
    // Telefon
    if (field.id === 'phone') {
        return /^[\d\s\+\-\(\)]+$/.test(value) && value.replace(/\D/g, '').length >= 9;
    }
    // Kod pocztowy
    if (field.id === 'postal_code' || field.id === 'company_postal_code') {
        return /^\d{2}-\d{3}$/.test(value);
    }
    // NIP
    if (field.id === 'nip') {
        return /^\d{10}$/.test(value.replace(/\D/g, ''));
    }

    return true;
}

function checkGenerateNDAButton() {
    const btn = document.getElementById('btnGenerateNDA');
    if (!btn) return;

    const form = document.getElementById('applicationForm');
    if (!form) return;

    let allValid = true;

    // Sprawdź wszystkie wymagane pola (input, select) - bez textarea
    const requiredFields = form.querySelectorAll('input[required], select[required]');
    requiredFields.forEach(field => {
        // Pomiń ukryte pola B2B jeśli nie wybrano B2B
        const b2bContainer = document.getElementById('b2bFields');
        if (b2bContainer && b2bContainer.style.display === 'none' && b2bContainer.contains(field)) {
            return;
        }

        if (field.type === 'checkbox') {
            if (!field.checked) allValid = false;
        } else if (field.type === 'radio') {
            const radioGroup = form.querySelectorAll(`input[name="${field.name}"]`);
            const anyChecked = Array.from(radioGroup).some(r => r.checked);
            if (!anyChecked) allValid = false;
        } else {
            if (!isFieldFormatValid(field)) allValid = false;
        }
    });

    // Sprawdź pola B2B jeśli wybrano B2B
    const cooperationType = document.querySelector('input[name="cooperation_type"]:checked');
    if (cooperationType && cooperationType.value === 'b2b') {
        const b2bFieldIds = ['company_name', 'nip', 'company_address', 'company_city', 'company_postal_code'];
        b2bFieldIds.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field && !isFieldFormatValid(field)) {
                allValid = false;
            }
        });
    }

    // Sprawdź zgodę RODO
    const consent = document.getElementById('data_processing_consent');
    if (consent && !consent.checked) {
        allValid = false;
    }

    // Aktualizuj stan przycisku (styl obsługuje CSS :disabled)
    btn.disabled = !allValid;
}

function validateField(field) {
    const fieldValue = field.value.trim();
    const errorSpan = document.getElementById(`error_${field.id}`);

    if (!errorSpan) return true;

    // Wyczyść poprzedni błąd
    errorSpan.textContent = '';
    errorSpan.style.display = 'none';
    field.classList.remove('error');

    // Sprawdź czy pole jest wymagane i puste
    if (field.hasAttribute('required') && !fieldValue) {
        errorSpan.textContent = 'To pole jest wymagane';
        errorSpan.style.display = 'block';
        field.classList.add('error');
        return false;
    }

    // Walidacja email
    if (field.type === 'email' && fieldValue) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(fieldValue)) {
            errorSpan.textContent = 'Nieprawidłowy format email';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    // Walidacja telefonu
    if (field.id === 'phone' && fieldValue) {
        const phoneRegex = /^[\d\s\+\-\(\)]+$/;
        if (!phoneRegex.test(fieldValue) || fieldValue.replace(/\D/g, '').length < 9) {
            errorSpan.textContent = 'Nieprawidłowy numer telefonu';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    // Walidacja kodu pocztowego (osobisty)
    if (field.id === 'postal_code' && fieldValue) {
        if (!/^\d{2}-\d{3}$/.test(fieldValue)) {
            errorSpan.textContent = 'Format: 00-000';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    // Walidacja NIP
    if (field.id === 'nip' && fieldValue) {
        const nipClean = fieldValue.replace(/\D/g, '');
        if (!/^\d{10}$/.test(nipClean)) {
            errorSpan.textContent = 'NIP musi zawierać 10 cyfr';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    // Walidacja kodu pocztowego firmy
    if (field.id === 'company_postal_code' && fieldValue) {
        if (!/^\d{2}-\d{3}$/.test(fieldValue)) {
            errorSpan.textContent = 'Format: 00-000';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    // Walidacja select (województwo)
    if (field.tagName === 'SELECT') {
        if (field.hasAttribute('required') && (!fieldValue || fieldValue === '')) {
            errorSpan.textContent = 'To pole jest wymagane';
            errorSpan.style.display = 'block';
            field.classList.add('error');
            return false;
        }
    }

    return true;
}

function validateForm() {
    const form = document.getElementById('applicationForm');
    if (!form) return false;

    let isValid = true;
    const fields = form.querySelectorAll('input[required], textarea[required], select[required]');

    fields.forEach(field => {
        if (!validateField(field)) {
            isValid = false;
        }
    });

    // NOWE: Walidacja pól B2B jeśli wybrano B2B
    const cooperationType = document.querySelector('input[name="cooperation_type"]:checked');
    if (cooperationType && cooperationType.value === 'b2b') {
        // Sprawdź czy pola B2B są wypełnione
        const b2bFields = ['company_name', 'nip', 'company_address', 'company_city', 'company_postal_code'];
        b2bFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field && !validateField(field)) {
                isValid = false;
            }
        });
    }

    // Sprawdź zgodę RODO
    const consentCheckbox = document.getElementById('data_processing_consent');
    if (consentCheckbox && !consentCheckbox.checked) {
        alert('Musisz wyrazić zgodę na przetwarzanie danych osobowych');
        isValid = false;
    }

    return isValid;
}

// ============================================================================
// ERROR DISPLAY HELPERS
// ============================================================================

function showFieldError(fieldName, errorMessage) {
    const input = document.querySelector(`[name="${fieldName}"]`);
    if (!input) return;

    // Dodaj klasę error do inputa
    input.classList.add('error');

    // Znajdź lub stwórz kontener na błąd
    const formGroup = input.closest('.form-group');
    if (!formGroup) return;

    let errorDiv = formGroup.querySelector('.error-message');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        formGroup.appendChild(errorDiv);
    }

    errorDiv.textContent = errorMessage;
    errorDiv.style.display = 'block';
}

function clearFieldError(fieldName) {
    const input = document.querySelector(`[name="${fieldName}"]`);
    if (!input) return;

    input.classList.remove('error');

    const formGroup = input.closest('.form-group');
    if (!formGroup) return;

    const errorDiv = formGroup.querySelector('.error-message');
    if (errorDiv) {
        errorDiv.style.display = 'none';
        errorDiv.textContent = '';
    }
}

function clearAllErrors() {
    // Usuń wszystkie klasy error z inputów
    document.querySelectorAll('.error').forEach(el => el.classList.remove('error'));

    // Ukryj wszystkie error-message
    document.querySelectorAll('.error-message').forEach(el => {
        el.style.display = 'none';
        el.textContent = '';
    });
}

function setupErrorClearing() {
    const form = document.getElementById('applicationForm');
    if (!form) return;

    const inputs = form.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        input.addEventListener('input', function () {
            if (this.name) {
                clearFieldError(this.name);
            }
        });

        input.addEventListener('change', function () {
            if (this.name) {
                clearFieldError(this.name);
            }
        });
    });
}

// ============================================================================
// FILE UPLOAD
// ============================================================================

function setupFileUpload() {
    const uploadArea = document.getElementById('fileUploadArea');
    const fileInput = document.getElementById('ndaFile');

    if (!uploadArea || !fileInput) return;

    fileInput.addEventListener('change', function (e) {
        if (e.target.files.length > 0) {
            // Obsługa wielu plików naraz
            for (let i = 0; i < e.target.files.length; i++) {
                handleFile(e.target.files[i]);
            }
        }
    });

    uploadArea.addEventListener('dragover', function (e) {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', function (e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', function (e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');

        if (e.dataTransfer.files.length > 0) {
            // Obsługa wielu plików naraz
            for (let i = 0; i < e.dataTransfer.files.length; i++) {
                handleFile(e.dataTransfer.files[i]);
            }
        }
    });
}

function handleFile(file) {
    const allowedTypes = [
        'application/pdf',
        'image/jpeg',
        'image/png',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.oasis.opendocument.text'
    ];

    // Sprawdź limit plików
    if (uploadedFiles.length >= MAX_FILES) {
        alert(`Można dodać maksymalnie ${MAX_FILES} pliki NDA`);
        return;
    }

    // Sprawdź rozmiar
    if (file.size > MAX_FILE_SIZE) {
        alert(`Plik "${file.name}" jest za duży (${(file.size / 1024 / 1024).toFixed(1)} MB). Maksymalny rozmiar to 5 MB.`);
        return;
    }

    // Sprawdź typ
    if (!allowedTypes.includes(file.type)) {
        alert('Niedozwolony typ pliku. Akceptowane formaty: PDF, JPG, PNG, DOCX, ODT');
        return;
    }

    // Sprawdź czy plik o tej nazwie już nie został dodany
    if (uploadedFiles.some(f => f.name === file.name)) {
        alert(`Plik "${file.name}" został już dodany`);
        return;
    }

    // Detekcja nazw plików sugerujących CV
    const cvPatterns = [/cv[_\-\s.]/i, /curriculum/i, /resume/i, /życiorys/i, /zyciorys/i, /lebenslauf/i];
    const fileNameLower = file.name.toLowerCase();
    if (cvPatterns.some(pattern => pattern.test(fileNameLower))) {
        alert('Nazwa pliku sugeruje, że to CV. Tutaj załączasz wyłącznie podpisaną umowę NDA.');
        return;
    }

    uploadedFiles.push(file);
    renderFilePreviews();
}

function renderFilePreviews() {
    const uploadArea = document.getElementById('fileUploadArea');
    const previewContainer = document.getElementById('filesPreviewContainer');
    const confirmSection = document.getElementById('ndaConfirmSection');
    const submitSection = document.getElementById('submitSection');

    if (!previewContainer) return;

    // Wyczyść kontener
    previewContainer.innerHTML = '';

    if (uploadedFiles.length === 0) {
        // Pokaż obszar uploadu
        if (uploadArea) uploadArea.style.display = 'block';
        previewContainer.style.display = 'none';
        // Ukryj sekcję potwierdzenia i submit
        if (confirmSection) confirmSection.style.display = 'none';
        if (submitSection) submitSection.style.display = 'none';
        return;
    }

    previewContainer.style.display = 'block';

    // Renderuj preview każdego pliku
    uploadedFiles.forEach((file, index) => {
        const filePreview = document.createElement('div');
        filePreview.className = 'file-preview-item';
        filePreview.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px; background: #f9f9f9; border-radius: 8px; border: 2px solid var(--accent-orange); margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 24px;">📄</span>
                    <div>
                        <p style="font-weight: 600; margin-bottom: 2px; color: var(--text-primary); font-size: 13px;">
                            Plik ${index + 1}: ${file.name}
                        </p>
                        <p style="font-size: 12px; color: #666;">(${(file.size / 1024).toFixed(1)} KB)</p>
                    </div>
                </div>
                <button type="button" onclick="removeFile(${index})" style="background: #ff4444; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 12px;">
                    Usuń
                </button>
            </div>
        `;
        previewContainer.appendChild(filePreview);
    });

    // Pokaż/ukryj obszar uploadu w zależności od liczby plików
    if (uploadArea) {
        uploadArea.style.display = uploadedFiles.length < MAX_FILES ? 'block' : 'none';
    }

    // Aktualizuj licznik plików
    const filesCountInfo = document.getElementById('filesCountInfo');
    const filesCount = document.getElementById('filesCount');
    if (filesCountInfo && filesCount) {
        filesCount.textContent = uploadedFiles.length;
        filesCountInfo.style.display = uploadedFiles.length > 0 ? 'block' : 'none';
    }

    // Pokaż sekcję potwierdzenia NDA (ukryj submit do czasu potwierdzenia)
    if (confirmSection) confirmSection.style.display = 'block';
    if (submitSection) submitSection.style.display = 'none';
}

function handleFileSelect(event) {
    if (event.target.files.length > 0) {
        for (let i = 0; i < event.target.files.length; i++) {
            handleFile(event.target.files[i]);
        }
    }
    // Reset inputa, żeby można było ponownie wybrać ten sam plik
    event.target.value = '';
}

function removeFile(index) {
    uploadedFiles.splice(index, 1);

    // Reset inputa
    const fileInput = document.getElementById('ndaFile');
    if (fileInput) fileInput.value = '';

    renderFilePreviews();
}

// ============================================================================
// "MAM UMOWĘ NDA" - odkrycie uploadu bez generowania
// ============================================================================

function showUploadSection() {
    const ndaUploadSection = document.getElementById('ndaUploadSection');
    if (ndaUploadSection) {
        ndaUploadSection.style.display = 'block';
        ndaUploadSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// ============================================================================
// NDA CONFIRMATION (Tak / Nie, chcę podmienić plik)
// ============================================================================

function confirmNDA() {
    const confirmSection = document.getElementById('ndaConfirmSection');
    const submitSection = document.getElementById('submitSection');

    // Ukryj sekcję potwierdzenia, pokaż przycisk "Wyślij aplikację"
    if (confirmSection) confirmSection.style.display = 'none';
    if (submitSection) {
        submitSection.style.display = 'block';
        submitSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function rejectNDA() {
    // Usuń wszystkie załączone pliki
    uploadedFiles = [];

    // Reset inputa
    const fileInput = document.getElementById('ndaFile');
    if (fileInput) fileInput.value = '';

    // Przerenderuj (pokaże pustą strefę uploadu, ukryje potwierdzenie i submit)
    renderFilePreviews();
}

// ============================================================================
// NDA GENERATION
// ============================================================================

async function generateNDA() {
    // Waliduj formularz najpierw
    if (!validateForm()) {
        alert('Proszę poprawnie wypełnić wszystkie wymagane pola formularza przed wygenerowaniem NDA');
        return;
    }

    const form = document.getElementById('applicationForm');
    const formDataObj = new FormData(form);

    // Konwertuj do JSON
    const data = {};
    formDataObj.forEach((value, key) => {
        data[key] = value;
    });

    // Zapisz dane globalnie
    formData = data;

    const button = event.target;
    const originalHTML = button.innerHTML;
    const originalBg = button.style.backgroundColor;

    // Dodaj spinner i zmień tekst
    button.innerHTML = `
        <span style="display: inline-flex; align-items: center; gap: 8px;">
            <span class="spinner"></span>
            Generowanie PDF...
        </span>
    `;
    button.disabled = true;
    button.style.cursor = 'wait';

    // Ukryj komunikat błędu jeśli istnieje
    const existingError = button.parentElement.querySelector('.nda-error-message');
    if (existingError) {
        existingError.remove();
    }

    try {
        const response = await fetch('/partner-academy/api/application/generate-nda', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `NDA_${data.last_name}_${data.first_name}.pdf`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            // Status sukcesu
            button.style.backgroundColor = '#2ECC71';
            button.style.transition = 'all 0.3s ease';
            button.innerHTML = `
                <span style="display: inline-flex; align-items: center; gap: 8px;">
                    ✓ Wygenerowano
                </span>
            `;

            // Odkryj sekcję uploadu NDA
            const ndaUploadSection = document.getElementById('ndaUploadSection');
            if (ndaUploadSection) {
                ndaUploadSection.style.display = 'block';
                ndaUploadSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }

            // Przywróć oryginalny stan po 3 sekundach
            setTimeout(() => {
                button.innerHTML = originalHTML;
                button.style.backgroundColor = originalBg;
                button.disabled = false;
                button.style.cursor = 'pointer';
            }, 3000);

        } else {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Wystąpił błąd podczas generowania PDF');
        }
    } catch (error) {
        console.error('Error:', error);

        // Status błędu
        button.style.backgroundColor = '#E74C3C';
        button.style.transition = 'all 0.3s ease';
        button.innerHTML = `
            <span style="display: inline-flex; align-items: center; gap: 8px;">
                ⚠ Błąd generowania
            </span>
        `;

        // Dodaj komunikat pod przyciskiem
        const errorMessage = document.createElement('p');
        errorMessage.className = 'nda-error-message';
        errorMessage.style.cssText = `
            color: #E74C3C;
            font-size: 13px;
            margin-top: 12px;
            padding: 12px;
            background: #FEE;
            border-radius: 6px;
            border-left: 3px solid #E74C3C;
            animation: slideDown 0.3s ease;
        `;
        errorMessage.textContent = 'Wystąpił błąd podczas generowania PDF. Prosimy o kontakt z nami.';
        button.parentElement.appendChild(errorMessage);

        // Przywróć oryginalny stan po 5 sekundach
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.style.backgroundColor = originalBg;
            button.disabled = false;
            button.style.cursor = 'pointer';
            if (errorMessage.parentElement) {
                errorMessage.remove();
            }
        }, 5000);
    }
}

// ============================================================================
// FORM SUBMISSION
// ============================================================================

async function submitForm() {
    // Wyczyść poprzednie błędy
    clearAllErrors();

    // Walidacja formularza
    if (!validateForm()) {
        alert('Proszę poprawnie wypełnić wszystkie wymagane pola');
        return;
    }

    // Sprawdź czy przynajmniej 1 plik NDA został załączony
    if (uploadedFiles.length === 0) {
        alert('Proszę załączyć przynajmniej jeden plik NDA');
        return;
    }

    const form = document.getElementById('applicationForm');

    const submitButton = document.querySelector('.btn-submit-form') || document.getElementById('btnNext');

    if (!submitButton) {
        console.error('Submit button not found!');
        alert('Błąd: nie znaleziono przycisku wysyłania');
        return;
    }

    // Zapisz oryginalny HTML przycisku
    const originalHTML = submitButton.innerHTML;

    // ANIMACJA PRZYCISKU - Spinning Border
    submitButton.innerHTML = `
        <span style="display: inline-flex; align-items: center; gap: 10px;">
            <div style="width: 20px; height: 20px; border: 3px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
            Sprawdzanie...
        </span>
    `;
    submitButton.disabled = true;
    submitButton.style.opacity = '0.7';
    submitButton.style.cursor = 'not-allowed';

    try {
        // ====================================================================
        // KROK 1: Sprawdź czy email już istnieje (bez plików - lekkie żądanie)
        // ====================================================================
        const email = form.querySelector('#email').value;

        const checkEmailResponse = await fetch('/partner-academy/api/application/check-email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ email: email })
        });

        if (checkEmailResponse.ok) {
            const checkResult = await checkEmailResponse.json();
            if (checkResult.exists) {
                // Email już istnieje - pokaż błąd
                const emailField = document.getElementById('email');
                const errorSpan = document.getElementById('error_email');
                const errorMessage = 'Na podany adres email została już złożona aplikacja. Jeśli chcesz zaktualizować swoje zgłoszenie, skontaktuj się z nami.';

                if (emailField && errorSpan) {
                    errorSpan.textContent = errorMessage;
                    errorSpan.style.display = 'block';
                    emailField.classList.add('error');
                    emailField.scrollIntoView({ behavior: 'smooth', block: 'center' });
                } else {
                    alert(errorMessage);
                }

                // Przywróć przycisk
                submitButton.innerHTML = originalHTML;
                submitButton.disabled = false;
                submitButton.style.opacity = '1';
                submitButton.style.cursor = 'pointer';
                return;
            }
        }

        // ====================================================================
        // KROK 2: Email OK - wysyłamy pełny formularz z plikami
        // ====================================================================
        submitButton.innerHTML = `
            <span style="display: inline-flex; align-items: center; gap: 10px;">
                <div style="width: 20px; height: 20px; border: 3px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
                Wysyłanie...
            </span>
        `;

        // Przygotuj FormData
        const formDataToSend = new FormData(form);

        // Dodaj wszystkie pliki NDA
        uploadedFiles.forEach((file) => {
            formDataToSend.append('nda_files', file);
        });

        const response = await fetch('/partner-academy/api/application/submit', {
            method: 'POST',
            body: formDataToSend
        });

        const contentType = response.headers.get('content-type');

        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Serwer zwrócił nieprawidłową odpowiedź. Spróbuj ponownie za chwilę.');
        }

        const result = await response.json();

        if (response.ok && result.success) {
            // SUKCES - pokaż ekran potwierdzenia
            const userEmail = form.querySelector('#email').value;
            const step7Content = document.querySelector('.step-content[data-step="7"]');

            if (step7Content) {
                step7Content.style.transition = 'opacity 0.5s ease-out';
                step7Content.style.opacity = '0';

                setTimeout(() => {
                    step7Content.innerHTML = `
                        <div style="text-align: center; padding: 60px 20px; max-width: 800px; margin: 0 auto;">
                            <div style="margin-bottom: 30px; animation: scaleIn 0.6s ease-out;">
                                <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <circle cx="60" cy="60" r="55" stroke="#2ECC71" stroke-width="6" fill="none"/>
                                    <path d="M35 62L52 79L85 41" stroke="#2ECC71" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </div>
                            
                            <h2 style="color: var(--primary-color); font-size: 32px; margin-bottom: 20px; font-weight: 600;">
                                Dziękujemy za aplikację!
                            </h2>
                            
                            <p style="font-size: 18px; color: var(--text-secondary); margin-bottom: 30px; line-height: 1.6;">
                                Twoja aplikacja została pomyślnie wysłana. Wkrótce skontaktujemy się z Tobą w celu omówienia dalszych kroków.
                            </p>
                            
                            <div style="background: #F8F9FA; border-radius: 12px; padding: 30px; margin-bottom: 30px; border: 2px solid #E0E0E0;">
                                <p style="font-size: 16px; color: var(--text-primary); margin-bottom: 15px; font-weight: 500;">
                                    Email potwierdzający został wysłany na:
                                </p>
                                <p style="font-size: 20px; color: var(--primary-color); font-weight: 600; margin-bottom: 20px;">
                                    ${userEmail}
                                </p>
                                <div style="background: #FFF3CD; border-left: 4px solid #FFC107; padding: 15px; border-radius: 4px; text-align: left;">
                                    <p style="font-size: 14px; color: #856404; margin: 0; line-height: 1.5;">
                                        <strong>⚠️ Ważne:</strong> Jeśli nie widzisz wiadomości w skrzynce odbiorczej, sprawdź folder <strong>SPAM/Wiadomości-śmieci</strong>.
                                    </p>
                                </div>
                            </div>
                        </div>
                        
                        <style>
                            @keyframes scaleIn {
                                0% { transform: scale(0); opacity: 0; }
                                50% { transform: scale(1.1); }
                                100% { transform: scale(1); opacity: 1; }
                            }
                        </style>
                    `;

                    step7Content.style.opacity = '1';
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }, 500);
            }

        } else {
            // BŁĄD WALIDACJI - wyświetl błędy pod polami
            if (result.errors) {
                // Wyświetl błędy pod konkretnymi polami
                Object.keys(result.errors).forEach(fieldName => {
                    showFieldError(fieldName, result.errors[fieldName]);
                });

                // Przewiń do pierwszego błędu
                const firstErrorField = document.querySelector('.error');
                if (firstErrorField) {
                    firstErrorField.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }

                alert('Proszę poprawić zaznaczone pola formularza');
            }
            // Duplikat emaila
            else if (result.error && (result.error.includes('email') && result.error.includes('aplikacja'))) {
                const emailField = document.getElementById('email');
                const errorSpan = document.getElementById('error_email');

                if (emailField && errorSpan) {
                    errorSpan.textContent = result.error;
                    errorSpan.style.display = 'block';
                    emailField.classList.add('error');
                    emailField.scrollIntoView({ behavior: 'smooth', block: 'center' });
                } else {
                    alert(result.error);
                }
            }
            // Inny błąd ogólny
            else {
                alert(result.error || 'Wystąpił błąd podczas wysyłania formularza. Spróbuj ponownie.');
            }
        }
    } catch (error) {
        console.error('Error:', error);
        alert(error.message || 'Wystąpił błąd podczas wysyłania formularza. Spróbuj ponownie.');
    } finally {
        // Przywróć przycisk
        submitButton.innerHTML = originalHTML;
        submitButton.disabled = false;
        submitButton.style.opacity = '1';
        submitButton.style.cursor = 'pointer';
    }
}

// ============================================================================
// PRIVACY MODAL
// ============================================================================

function showPrivacyModal() {
    const modal = document.getElementById('privacyModal');
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closePrivacyModal() {
    const modal = document.getElementById('privacyModal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
}

// Zamknij modal po kliknięciu w tło
window.onclick = function (event) {
    const modal = document.getElementById('privacyModal');
    if (event.target === modal) {
        closePrivacyModal();
    }
}

// ============================================================================
// KEYBOARD NAVIGATION
// ============================================================================

document.addEventListener('keydown', function (e) {
    // Nie reaguj jeśli użytkownik pisze w polu
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        return;
    }

    // Strzałka w prawo lub Enter - następny krok
    if (e.key === 'ArrowRight' || e.key === 'Enter') {
        nextStep();
    }

    // Strzałka w lewo - poprzedni krok
    if (e.key === 'ArrowLeft') {
        prevStep();
    }
});