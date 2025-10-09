// ============================================================================
// PARTNER ACADEMY - LEARNING PLATFORM JAVASCRIPT
// Zarządzanie krokami, progressem, quizami, session management
// ============================================================================

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const LearningPlatform = {
    // Session
    sessionId: null,
    userIp: null,
    isAuthenticated: false,
    
    // Progress
    currentStep: '1.1',
    completedSteps: [],
    lockedSteps: ['1.2', '1.3', '1.4', 'M1', '2.1', '2.2', '2.3', '2.4', 'M2', '3.1'],
    
    // Quiz data
    quizResults: {},
    quizAttempts: {
        'M1': 0,
        'M2': 0
    },
    
    // Time tracking
    totalTimeSpent: 0,
    stepTimes: {},
    
    // Constants
    CORRECT_PIN: '3846',
    ALL_STEPS: ['1.1', '1.2', '1.3', '1.4', 'M1', '2.1', '2.2', '2.3', '2.4', 'M2', '3.1'],
    TOTAL_STEPS: 11,
    
    // Quiz answers (będą załadowane z backendu lub zdefiniowane tutaj)
    correctAnswers: {
        'M1': {
            'q1': 'B',
            'q2': ['A', 'C', 'D'],
            'q3': 'B'
        },
        'M2': {
            // Pytania do M2 - do uzupełnienia
        }
    }
};

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('[Learning] Inicjalizacja platformy...');
    
    // Zawsze pokazuj PIN gate na początku
    showPINGate();
    initPINInputs();
});

// ============================================================================
// PIN AUTHENTICATION
// ============================================================================

function showPINGate() {
    document.getElementById('pinGateOverlay').style.display = 'flex';
    document.getElementById('learningContainer').style.display = 'none';
    
    // Focus na pierwszym polu
    setTimeout(() => {
        document.getElementById('pin1').focus();
    }, 300);
}

function hidePINGate() {
    const overlay = document.getElementById('pinGateOverlay');
    overlay.classList.add('fade-out');
    
    setTimeout(() => {
        overlay.style.display = 'none';
        document.getElementById('learningContainer').style.display = 'block';
    }, 500);
}

function initPINInputs() {
    const inputs = document.querySelectorAll('.pin-digit');
    
    inputs.forEach((input, index) => {
        // Obsługa wpisywania
        input.addEventListener('input', function(e) {
            const value = e.target.value;
            
            // Akceptuj tylko cyfry
            if (!/^\d$/.test(value)) {
                e.target.value = '';
                return;
            }
            
            // Oznacz jako wypełnione
            e.target.classList.add('filled');
            
            // Automatyczne przejście do następnego pola
            if (value && index < inputs.length - 1) {
                inputs[index + 1].focus();
                inputs[index + 1].select();
            }
            
            // Jeśli wszystkie pola wypełnione, waliduj PIN
            if (index === inputs.length - 1 && value) {
                setTimeout(() => validatePIN(), 200);
            }
        });
        
        // Obsługa usuwania (Backspace)
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Backspace' && !e.target.value && index > 0) {
                inputs[index - 1].focus();
                inputs[index - 1].select();
            }
        });
        
        // Obsługa wklejania całego PIN-u
        input.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedData = e.clipboardData.getData('text');
            
            if (/^\d{4}$/.test(pastedData)) {
                pastedData.split('').forEach((digit, i) => {
                    if (inputs[i]) {
                        inputs[i].value = digit;
                        inputs[i].classList.add('filled');
                    }
                });
                
                inputs[3].focus();
                setTimeout(() => validatePIN(), 200);
            }
        });
        
        // Auto-select przy focus
        input.addEventListener('focus', function(e) {
            e.target.select();
        });
    });
}

function validatePIN() {
    const inputs = document.querySelectorAll('.pin-digit');
    const enteredPIN = Array.from(inputs).map(input => input.value).join('');
    
    console.log('[Learning] Walidacja PIN:', enteredPIN);
    
    if (enteredPIN.length !== 4) {
        return;
    }
    
    if (enteredPIN === LearningPlatform.CORRECT_PIN) {
        // PIN poprawny - zielone obramówki
        inputs.forEach(input => {
            input.classList.remove('error', 'filled');
            input.classList.add('success');
            input.disabled = true;
        });
        
        // Ukryj komunikat błędu jeśli był widoczny
        document.getElementById('pinError').classList.remove('show');
        
        LearningPlatform.isAuthenticated = true;
        
        console.log('[Learning] PIN poprawny! Ukrywanie overlaya...');
        
        // Ukryj overlay po 1 sekundzie
        setTimeout(() => {
            hidePINGate();
            initializePlatform();
        }, 1000);
        
    } else {
        // PIN niepoprawny - czerwone obramówki i animacja shake
        const pinInputsContainer = document.getElementById('pinInputs');
        const errorMessage = document.getElementById('pinError');
        
        inputs.forEach(input => {
            input.classList.remove('success', 'filled');
            input.classList.add('error');
        });
        
        // Pokaż komunikat błędu
        errorMessage.classList.add('show');
        
        // Animacja shake
        pinInputsContainer.classList.add('shake');
        
        console.log('[Learning] PIN niepoprawny!');
        
        // Usuń animację shake i wyczyść pola po 500ms
        setTimeout(() => {
            pinInputsContainer.classList.remove('shake');
            
            inputs.forEach(input => {
                input.value = '';
                input.classList.remove('error', 'filled');
                input.disabled = false;
            });
            
            // Focus na pierwszym polu
            inputs[0].focus();
        }, 500);
    }
}

// ============================================================================
// PLATFORM INITIALIZATION
// ============================================================================

async function initializePlatform() {
    console.log('[Learning] Inicjalizacja platformy szkoleniowej...');
    
    // Pobierz IP użytkownika i znajdź/utwórz sesję
    await initializeSession();
    
    // Załaduj progress z localStorage lub backendu
    loadProgressFromLocalStorage();
    await loadProgressFromBackend();
    
    // Inicjalizuj quizy
    initQuizzes();
    
    // Aktualizuj UI
    updateProgressUI();
    updateSidebarUI();
    
    console.log('[Learning] Platforma gotowa!');
}

async function initializeSession() {
    try {
        // Wywołaj backend aby uzyskać/utworzyć sesję na podstawie IP
        const response = await fetch('/partner-academy/api/session/init', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            LearningPlatform.sessionId = data.session_id;
            LearningPlatform.userIp = data.ip_address;
            
            console.log('[Learning] Sesja zainicjalizowana:', LearningPlatform.sessionId);
            console.log('[Learning] IP użytkownika:', LearningPlatform.userIp);
        }
    } catch (error) {
        console.error('[Learning] Błąd inicjalizacji sesji:', error);
        // Fallback - generuj lokalny ID
        LearningPlatform.sessionId = generateSessionId();
    }
}

function generateSessionId() {
    return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// ============================================================================
// PROGRESS MANAGEMENT
// ============================================================================

function loadProgressFromLocalStorage() {
    try {
        const savedProgress = localStorage.getItem('learning_progress');
        if (savedProgress) {
            const progress = JSON.parse(savedProgress);
            
            LearningPlatform.currentStep = progress.currentStep || '1.1';
            LearningPlatform.completedSteps = progress.completedSteps || [];
            LearningPlatform.totalTimeSpent = progress.totalTimeSpent || 0;
            LearningPlatform.quizAttempts = progress.quizAttempts || { 'M1': 0, 'M2': 0 };
            
            updateLockedSteps();
            
            console.log('[Learning] Progress załadowany z localStorage:', progress);
        }
    } catch (error) {
        console.error('[Learning] Błąd ładowania progressu z localStorage:', error);
    }
}

function saveProgressToLocalStorage() {
    try {
        const progress = {
            currentStep: LearningPlatform.currentStep,
            completedSteps: LearningPlatform.completedSteps,
            totalTimeSpent: LearningPlatform.totalTimeSpent,
            quizAttempts: LearningPlatform.quizAttempts,
            lastUpdate: Date.now()
        };
        
        localStorage.setItem('learning_progress', JSON.stringify(progress));
        console.log('[Learning] Progress zapisany w localStorage');
    } catch (error) {
        console.error('[Learning] Błąd zapisywania progressu do localStorage:', error);
    }
}

async function loadProgressFromBackend() {
    try {
        const response = await fetch('/partner-academy/api/progress/load', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: LearningPlatform.sessionId
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            if (data.progress) {
                // Backend ma priorytet nad localStorage
                LearningPlatform.currentStep = data.progress.current_step || LearningPlatform.currentStep;
                LearningPlatform.completedSteps = data.progress.completed_steps || LearningPlatform.completedSteps;
                LearningPlatform.totalTimeSpent = data.progress.total_time || LearningPlatform.totalTimeSpent;
                
                // Zapisz zaktualizowany progress w localStorage
                saveProgressToLocalStorage();
                updateLockedSteps();
                
                console.log('[Learning] Progress załadowany z backendu:', data.progress);
            }
        }
    } catch (error) {
        console.error('[Learning] Błąd ładowania progressu z backendu:', error);
    }
}

async function saveProgress(action, stepId) {
    // Zapisz lokalnie natychmiast
    saveProgressToLocalStorage();
    
    // Wyślij do backendu
    try {
        const response = await fetch('/partner-academy/api/progress/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: LearningPlatform.sessionId,
                action: action,
                completed_step: stepId  // Backend oczekuje 'completed_step' nie 'step_id'
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            if (result.success) {
                console.log('[Learning] Progress zapisany w backendzie:', action, stepId);
            }
        }
    } catch (error) {
        console.error('[Learning] Błąd zapisywania progressu w backendzie:', error);
    }
}

function updateLockedSteps() {
    // Odblokuj wszystkie kroki do ostatniego ukończonego + 1
    const lastCompletedIndex = LearningPlatform.ALL_STEPS.findIndex(
        step => !LearningPlatform.completedSteps.includes(step)
    );
    
    if (lastCompletedIndex !== -1) {
        LearningPlatform.lockedSteps = LearningPlatform.ALL_STEPS.slice(lastCompletedIndex + 1);
    } else {
        LearningPlatform.lockedSteps = [];
    }
}

function updateProgressUI() {
    const completedCount = LearningPlatform.completedSteps.length;
    const progressPercent = (completedCount / LearningPlatform.TOTAL_STEPS) * 100;
    
    // Aktualizuj progress bar
    document.getElementById('progressValue').textContent = `${completedCount}/${LearningPlatform.TOTAL_STEPS}`;
    document.getElementById('progressFill').style.width = `${progressPercent}%`;
}

function updateSidebarUI() {
    const stepItems = document.querySelectorAll('.step-item');
    
    stepItems.forEach(item => {
        const stepId = item.getAttribute('data-step');
        const statusSpan = item.querySelector('.step-status');
        
        // Usuń wszystkie klasy
        item.classList.remove('active', 'completed', 'locked');
        
        // Dodaj odpowiednią klasę
        if (stepId === LearningPlatform.currentStep) {
            item.classList.add('active');
            statusSpan.textContent = '';
        } else if (LearningPlatform.completedSteps.includes(stepId)) {
            item.classList.add('completed');
            statusSpan.textContent = '✓';
        } else if (LearningPlatform.lockedSteps.includes(stepId)) {
            item.classList.add('locked');
            statusSpan.textContent = '🔒';
        } else {
            // Odblokowany ale nie ukończony
            statusSpan.textContent = '';
        }
    });
}

// ============================================================================
// STEP NAVIGATION
// ============================================================================

function goToStep(stepId) {
    // Sprawdź czy krok jest zablokowany
    if (LearningPlatform.lockedSteps.includes(stepId)) {
        alert('Musisz ukończyć poprzednie kroki, aby odblokować ten krok.');
        return;
    }
    
    // Ukryj wszystkie kroki
    document.querySelectorAll('.step-content').forEach(step => {
        step.classList.remove('active');
    });
    
    // Pokaż wybrany krok
    const targetStep = document.querySelector(`.step-content[data-step="${stepId}"]`);
    if (targetStep) {
        targetStep.classList.add('active');
        LearningPlatform.currentStep = stepId;
        
        // Aktualizuj UI
        updateSidebarUI();
        
        // Zapisz progress
        saveProgress('navigate', stepId);
        
        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
        
        console.log('[Learning] Przejście do kroku:', stepId);
    }
}

function nextStep() {
    const currentIndex = LearningPlatform.ALL_STEPS.indexOf(LearningPlatform.currentStep);
    
    if (currentIndex < LearningPlatform.ALL_STEPS.length - 1) {
        const nextStepId = LearningPlatform.ALL_STEPS[currentIndex + 1];
        
        // Oznacz obecny krok jako ukończony
        if (!LearningPlatform.completedSteps.includes(LearningPlatform.currentStep)) {
            completeStep(LearningPlatform.currentStep);
        }
        
        // Przejdź do następnego
        goToStep(nextStepId);
    }
}

function prevStep() {
    const currentIndex = LearningPlatform.ALL_STEPS.indexOf(LearningPlatform.currentStep);
    
    if (currentIndex > 0) {
        const prevStepId = LearningPlatform.ALL_STEPS[currentIndex - 1];
        goToStep(prevStepId);
    }
}

function completeStep(stepId) {
    if (!LearningPlatform.completedSteps.includes(stepId)) {
        LearningPlatform.completedSteps.push(stepId);
        
        // Odblokuj następny krok
        updateLockedSteps();
        
        // Zapisz w backendzie
        saveProgress('complete_step', stepId);
        
        // Aktualizuj UI
        updateProgressUI();
        updateSidebarUI();
        
        console.log('[Learning] Krok ukończony:', stepId);
    }
}

// ============================================================================
// QUIZ MANAGEMENT
// ============================================================================

function initQuizzes() {
    // Quiz M1 - przykładowe pytania
    const quizM1Data = [
        {
            id: 'q1',
            question: 'Jakie jest główne zadanie partnera WoodPower?',
            type: 'single',
            options: [
                { value: 'A', label: 'Produkcja pelletu' },
                { value: 'B', label: 'Sprzedaż i promocja produktów' },
                { value: 'C', label: 'Transport towarów' },
                { value: 'D', label: 'Serwis techniczny' }
            ]
        },
        {
            id: 'q2',
            question: 'Które produkty oferuje WoodPower? (zaznacz wszystkie)',
            type: 'multiple',
            options: [
                { value: 'A', label: 'Pellet drzewny' },
                { value: 'B', label: 'Węgiel' },
                { value: 'C', label: 'Brykiet' },
                { value: 'D', label: 'Drewno opałowe' }
            ]
        },
        {
            id: 'q3',
            question: 'Jaki jest minimalny okres współpracy?',
            type: 'single',
            options: [
                { value: 'A', label: '3 miesiące' },
                { value: 'B', label: '12 miesięcy' },
                { value: 'C', label: '24 miesiące' },
                { value: 'D', label: 'Bez zobowiązań' }
            ]
        }
    ];
    
    renderQuiz('M1', quizM1Data);
}

function renderQuiz(quizId, questions) {
    const container = document.getElementById(`quiz${quizId}`);
    if (!container) return;
    
    let html = '';
    
    questions.forEach((q, index) => {
        html += `
            <div class="quiz-question" data-question="${q.id}">
                <div class="question-header">
                    <div class="question-number">${index + 1}</div>
                    <div class="question-text">${q.question}</div>
                </div>
                <div class="question-options">
        `;
        
        q.options.forEach(option => {
            if (q.type === 'single') {
                html += `
                    <label class="quiz-option">
                        <input type="radio" name="${quizId}_${q.id}" value="${option.value}" class="option-radio">
                        <span class="option-label">${option.label}</span>
                    </label>
                `;
            } else {
                html += `
                    <label class="quiz-option">
                        <input type="checkbox" name="${quizId}_${q.id}" value="${option.value}" class="option-checkbox">
                        <span class="option-label">${option.label}</span>
                    </label>
                `;
            }
        });
        
        html += `
                </div>
                <div class="question-feedback"></div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    
    // Obsługa kliknięć na opcje
    container.querySelectorAll('.quiz-option').forEach(option => {
        option.addEventListener('click', function() {
            this.classList.toggle('selected');
        });
    });
}

function submitQuiz(quizId) {
    console.log('[Learning] Sprawdzanie quizu:', quizId);
    
    const container = document.getElementById(`quiz${quizId}`);
    const questions = container.querySelectorAll('.quiz-question');
    let allCorrect = true;
    
    questions.forEach(questionDiv => {
        const questionId = questionDiv.getAttribute('data-question');
        const correctAnswer = LearningPlatform.correctAnswers[quizId][questionId];
        const feedbackDiv = questionDiv.querySelector('.question-feedback');
        
        // Pobierz wybrane odpowiedzi
        let selectedAnswers;
        const radioInput = questionDiv.querySelector('input[type="radio"]:checked');
        
        if (radioInput) {
            // Single choice
            selectedAnswers = radioInput.value;
        } else {
            // Multiple choice
            const checkboxes = questionDiv.querySelectorAll('input[type="checkbox"]:checked');
            selectedAnswers = Array.from(checkboxes).map(cb => cb.value);
        }
        
        // Sprawdź poprawność
        let isCorrect = false;
        
        if (Array.isArray(correctAnswer)) {
            // Multiple choice - porównaj tablice
            isCorrect = correctAnswer.length === selectedAnswers.length &&
                       correctAnswer.every(ans => selectedAnswers.includes(ans));
        } else {
            // Single choice
            isCorrect = selectedAnswers === correctAnswer;
        }
        
        // Pokaż feedback
        if (isCorrect) {
            feedbackDiv.textContent = '✓ Poprawna odpowiedź!';
            feedbackDiv.className = 'question-feedback show correct';
        } else {
            feedbackDiv.textContent = '✗ Niepoprawna odpowiedź. Spróbuj ponownie.';
            feedbackDiv.className = 'question-feedback show incorrect';
            allCorrect = false;
        }
    });
    
    // Zwiększ licznik prób
    LearningPlatform.quizAttempts[quizId]++;
    
    if (allCorrect) {
        // Quiz zaliczony!
        LearningPlatform.quizResults[quizId] = {
            passed: true,
            attempts: LearningPlatform.quizAttempts[quizId],
            timestamp: Date.now()
        };
        
        // Pokaż komunikat sukcesu
        setTimeout(() => {
            showQuizSuccess(quizId);
            completeStep(quizId);
        }, 1000);
        
        console.log('[Learning] Quiz zaliczony!', quizId);
    } else {
        console.log('[Learning] Quiz niezaliczony. Próba:', LearningPlatform.quizAttempts[quizId]);
    }
}

function showQuizSuccess(quizId) {
    const container = document.getElementById(`quiz${quizId}`);
    
    const successHtml = `
        <div class="quiz-result">
            <div class="result-icon">🎉</div>
            <h3>Gratulacje!</h3>
            <p>Zaliczyłeś quiz z wynikiem 100%. Możesz przejść do kolejnego modułu.</p>
            <button class="btn-primary" onclick="nextStep()">
                Przejdź dalej
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M5 12h14M12 5l7 7-7 7"/>
                </svg>
            </button>
        </div>
    `;
    
    container.innerHTML = successHtml;
}

// ============================================================================
// CERTIFICATE DOWNLOAD
// ============================================================================

function downloadCertificate() {
    console.log('[Learning] Pobieranie certyfikatu...');
    
    // TODO: Implementacja pobierania certyfikatu z backendu
    alert('Funkcja pobierania certyfikatu zostanie wkrótce dodana!');
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

console.log('[Learning] learning.js załadowany');