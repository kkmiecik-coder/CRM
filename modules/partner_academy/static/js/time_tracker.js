// ============================================================================
// PARTNER ACADEMY - TIME TRACKER & ANALYTICS
// Śledzenie czasu, eventów użytkownika, heartbeat synchronizacja
// ============================================================================

// ============================================================================
// TRACKER STATE
// ============================================================================

const TimeTracker = {
    // Tracking state
    isTracking: false,
    isPageVisible: true,
    
    // Time tracking
    sessionStartTime: null,
    currentStepStartTime: null,
    lastHeartbeat: null,
    
    // Counters
    totalTimeSpent: 0,
    currentStepTime: 0,
    
    // Event buffer
    eventBuffer: [],
    maxBufferSize: 50,
    
    // Intervals
    heartbeatInterval: null,
    heartbeatFrequency: 10000, // 10 sekund
    
    // Scroll tracking
    maxScrollDepth: 0,
    scrollMilestones: [25, 50, 75, 100],
    reachedMilestones: [],
    
    // Network status
    isOnline: navigator.onLine,
    offlineBuffer: []
};

// ============================================================================
// INITIALIZATION
// ============================================================================

function initTimeTracker() {
    console.log('[Tracker] Inicjalizacja time trackera...');
    
    // Ustaw czas rozpoczęcia sesji
    TimeTracker.sessionStartTime = Date.now();
    TimeTracker.currentStepStartTime = Date.now();
    TimeTracker.lastHeartbeat = Date.now();
    
    // Załaduj zapisane eventy z localStorage
    loadEventBuffer();
    
    // Uruchom tracking
    startTracking();
    
    // Ustaw event listeners
    setupEventListeners();
    
    // Uruchom heartbeat
    startHeartbeat();
    
    console.log('[Tracker] Time tracker uruchomiony');
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function setupEventListeners() {
    // Visibility API - pause gdy karta ukryta
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    // Scroll tracking
    window.addEventListener('scroll', handleScroll, { passive: true });
    
    // Click tracking
    document.addEventListener('click', handleClick);
    
    // Network status
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    // Before unload - zapisz dane przed zamknięciem
    window.addEventListener('beforeunload', handleBeforeUnload);
    
    // Step changes - będzie wywoływane z learning.js
    // Można podpiąć customowy event
    document.addEventListener('stepChanged', handleStepChange);
}

function handleVisibilityChange() {
    if (document.hidden) {
        // Karta ukryta - pauzuj tracking
        TimeTracker.isPageVisible = false;
        pauseTracking();
        
        logEvent('page_hidden', {
            total_time: TimeTracker.totalTimeSpent,
            step_time: TimeTracker.currentStepTime
        });
        
        console.log('[Tracker] Karta ukryta - tracking zatrzymany');
    } else {
        // Karta widoczna - wznów tracking
        TimeTracker.isPageVisible = true;
        resumeTracking();
        
        logEvent('page_visible', {});
        
        console.log('[Tracker] Karta widoczna - tracking wznowiony');
    }
}

function handleScroll() {
    // Oblicz scroll depth
    const windowHeight = window.innerHeight;
    const documentHeight = document.documentElement.scrollHeight;
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    
    const scrollPercent = Math.round((scrollTop / (documentHeight - windowHeight)) * 100);
    
    // Aktualizuj max scroll depth
    if (scrollPercent > TimeTracker.maxScrollDepth) {
        TimeTracker.maxScrollDepth = scrollPercent;
    }
    
    // Sprawdź milestones (25%, 50%, 75%, 100%)
    TimeTracker.scrollMilestones.forEach(milestone => {
        if (scrollPercent >= milestone && !TimeTracker.reachedMilestones.includes(milestone)) {
            TimeTracker.reachedMilestones.push(milestone);
            
            logEvent('scroll_milestone', {
                milestone: milestone,
                step: LearningPlatform.currentStep
            });
            
            console.log('[Tracker] Scroll milestone:', milestone + '%');
        }
    });
}

function handleClick(e) {
    // Trackuj kliknięcia w ważne elementy
    const target = e.target;
    
    let elementType = 'other';
    let elementData = {};
    
    if (target.classList.contains('btn-primary') || target.classList.contains('btn-secondary')) {
        elementType = 'button';
        elementData.text = target.textContent.trim();
    } else if (target.classList.contains('step-item')) {
        elementType = 'sidebar_navigation';
        elementData.target_step = target.getAttribute('data-step');
    } else if (target.classList.contains('quiz-option')) {
        elementType = 'quiz_option';
        elementData.quiz_id = target.closest('.quiz-container')?.id;
    }
    
    if (elementType !== 'other') {
        logEvent('click', {
            element_type: elementType,
            ...elementData
        });
    }
}

function handleStepChange(e) {
    const newStep = e.detail.stepId;
    const timeSpent = Date.now() - TimeTracker.currentStepStartTime;
    
    logEvent('step_change', {
        from_step: LearningPlatform.currentStep,
        to_step: newStep,
        time_spent: timeSpent
    });
    
    // Reset czasu dla nowego kroku
    TimeTracker.currentStepTime = 0;
    TimeTracker.currentStepStartTime = Date.now();
    TimeTracker.maxScrollDepth = 0;
    TimeTracker.reachedMilestones = [];
    
    console.log('[Tracker] Zmiana kroku:', LearningPlatform.currentStep, '→', newStep);
}

function handleOnline() {
    TimeTracker.isOnline = true;
    
    logEvent('online', {});
    
    // Wyślij buforowane eventy
    if (TimeTracker.offlineBuffer.length > 0) {
        console.log('[Tracker] Online - wysyłanie buforowanych eventów:', TimeTracker.offlineBuffer.length);
        flushOfflineBuffer();
    }
}

function handleOffline() {
    TimeTracker.isOnline = false;
    
    logEvent('offline', {});
    
    console.log('[Tracker] Offline - eventy będą buforowane');
}

function handleBeforeUnload(e) {
    // Zapisz dane przed zamknięciem strony
    pauseTracking();
    
    // Synchronizuj czas
    syncTimeSpent(true);
    
    // Zapisz buffer w localStorage
    saveEventBuffer();
    
    logEvent('session_end', {
        total_time: TimeTracker.totalTimeSpent,
        completed_steps: LearningPlatform.completedSteps.length
    });
    
    console.log('[Tracker] Session end - dane zapisane');
}

// ============================================================================
// TRACKING CONTROL
// ============================================================================

function startTracking() {
    if (TimeTracker.isTracking) return;
    
    TimeTracker.isTracking = true;
    TimeTracker.sessionStartTime = Date.now();
    TimeTracker.currentStepStartTime = Date.now();
    
    logEvent('session_start', {
        step: LearningPlatform.currentStep
    });
    
    console.log('[Tracker] Tracking rozpoczęty');
}

function pauseTracking() {
    if (!TimeTracker.isTracking) return;
    
    // Oblicz czas od ostatniego heartbeat
    const now = Date.now();
    const timeSinceLastHeartbeat = now - TimeTracker.lastHeartbeat;
    
    TimeTracker.totalTimeSpent += timeSinceLastHeartbeat;
    TimeTracker.currentStepTime += timeSinceLastHeartbeat;
    
    TimeTracker.isTracking = false;
    
    // Zatrzymaj heartbeat
    if (TimeTracker.heartbeatInterval) {
        clearInterval(TimeTracker.heartbeatInterval);
        TimeTracker.heartbeatInterval = null;
    }
    
    console.log('[Tracker] Tracking zatrzymany. Całkowity czas:', Math.round(TimeTracker.totalTimeSpent / 1000) + 's');
}

function resumeTracking() {
    if (TimeTracker.isTracking) return;
    
    TimeTracker.isTracking = true;
    TimeTracker.lastHeartbeat = Date.now();
    
    // Wznów heartbeat
    startHeartbeat();
    
    console.log('[Tracker] Tracking wznowiony');
}

// ============================================================================
// HEARTBEAT - SYNCHRONIZACJA CO 10s
// ============================================================================

function startHeartbeat() {
    // Wyczyść poprzedni interval jeśli istnieje
    if (TimeTracker.heartbeatInterval) {
        clearInterval(TimeTracker.heartbeatInterval);
    }
    
    // Uruchom nowy heartbeat
    TimeTracker.heartbeatInterval = setInterval(() => {
        if (TimeTracker.isTracking && TimeTracker.isPageVisible) {
            heartbeat();
        }
    }, TimeTracker.heartbeatFrequency);
    
    console.log('[Tracker] Heartbeat uruchomiony (co 10s)');
}

function heartbeat() {
    const now = Date.now();
    const timeSinceLastHeartbeat = now - TimeTracker.lastHeartbeat;
    
    // Aktualizuj czasy
    TimeTracker.totalTimeSpent += timeSinceLastHeartbeat;
    TimeTracker.currentStepTime += timeSinceLastHeartbeat;
    TimeTracker.lastHeartbeat = now;
    
    // Synchronizuj z backendem
    syncTimeSpent(false);
    
    console.log('[Tracker] Heartbeat - czas:', Math.round(TimeTracker.totalTimeSpent / 1000) + 's');
}

// ============================================================================
// TIME SYNCHRONIZATION WITH BACKEND
// ============================================================================

async function syncTimeSpent(isBeforeUnload = false) {
    const data = {
        session_id: LearningPlatform.sessionId,
        total_time: Math.round(TimeTracker.totalTimeSpent / 1000), // sekundy
        current_step: LearningPlatform.currentStep,
        step_time: Math.round(TimeTracker.currentStepTime / 1000),
        timestamp: Date.now()
    };
    
    try {
        if (isBeforeUnload) {
            // Użyj sendBeacon dla synchronicznego wysłania przy zamykaniu
            const blob = new Blob([JSON.stringify(data)], { type: 'application/json' });
            navigator.sendBeacon('/partner-academy/api/time/sync', blob);
        } else {
            // Normalny fetch
            const response = await fetch('/partner-academy/api/time/sync', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                console.log('[Tracker] Czas zsynchronizowany z backendem');
            }
        }
    } catch (error) {
        console.error('[Tracker] Błąd synchronizacji czasu:', error);
        
        // Dodaj do offline buffer
        if (!TimeTracker.isOnline) {
            TimeTracker.offlineBuffer.push({
                type: 'time_sync',
                data: data,
                timestamp: Date.now()
            });
        }
    }
}

// ============================================================================
// EVENT LOGGING
// ============================================================================

function logEvent(eventType, eventData) {
    const event = {
        type: eventType,
        step: LearningPlatform.currentStep,
        data: eventData,
        timestamp: Date.now(),
        session_id: LearningPlatform.sessionId
    };
    
    // Dodaj do buffera
    TimeTracker.eventBuffer.push(event);
    
    // Ogranicz rozmiar buffera
    if (TimeTracker.eventBuffer.length > TimeTracker.maxBufferSize) {
        TimeTracker.eventBuffer.shift();
    }
    
    // Zapisz w localStorage
    saveEventBuffer();
    
    // Wyślij do backendu (opcjonalnie - można zbierać i wysyłać okresowo)
    sendEventToBackend(event);
}

async function sendEventToBackend(event) {
    // Nie wysyłaj jeśli offline
    if (!TimeTracker.isOnline) {
        TimeTracker.offlineBuffer.push({
            type: 'event',
            data: event,
            timestamp: Date.now()
        });
        return;
    }
    
    try {
        await fetch('/partner-academy/api/events/log', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(event)
        });
    } catch (error) {
        console.error('[Tracker] Błąd wysyłania eventu:', error);
        
        // Dodaj do offline buffer
        TimeTracker.offlineBuffer.push({
            type: 'event',
            data: event,
            timestamp: Date.now()
        });
    }
}

// ============================================================================
// OFFLINE BUFFER MANAGEMENT
// ============================================================================

async function flushOfflineBuffer() {
    if (TimeTracker.offlineBuffer.length === 0) return;
    
    console.log('[Tracker] Wysyłanie buforowanych danych:', TimeTracker.offlineBuffer.length);
    
    const buffer = [...TimeTracker.offlineBuffer];
    TimeTracker.offlineBuffer = [];
    
    try {
        const response = await fetch('/partner-academy/api/events/bulk', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: LearningPlatform.sessionId,
                events: buffer
            })
        });
        
        if (response.ok) {
            console.log('[Tracker] Buforowane dane wysłane pomyślnie');
        } else {
            // Przywróć buffer jeśli nie udało się wysłać
            TimeTracker.offlineBuffer = buffer;
        }
    } catch (error) {
        console.error('[Tracker] Błąd wysyłania bufora:', error);
        // Przywróć buffer
        TimeTracker.offlineBuffer = buffer;
    }
}

// ============================================================================
// LOCALSTORAGE PERSISTENCE
// ============================================================================

function saveEventBuffer() {
    try {
        localStorage.setItem('learning_events', JSON.stringify(TimeTracker.eventBuffer));
    } catch (error) {
        console.error('[Tracker] Błąd zapisywania eventów do localStorage:', error);
    }
}

function loadEventBuffer() {
    try {
        const saved = localStorage.getItem('learning_events');
        if (saved) {
            TimeTracker.eventBuffer = JSON.parse(saved);
            console.log('[Tracker] Załadowano eventy z localStorage:', TimeTracker.eventBuffer.length);
        }
    } catch (error) {
        console.error('[Tracker] Błąd ładowania eventów z localStorage:', error);
        TimeTracker.eventBuffer = [];
    }
}

// ============================================================================
// PUBLIC API - CUSTOM EVENTS
// ============================================================================

// Eksportowane funkcje dla learning.js

function trackQuizAttempt(quizId, success, attempts) {
    logEvent('quiz_attempt', {
        quiz_id: quizId,
        success: success,
        attempts: attempts
    });
}

function trackStepCompletion(stepId, timeSpent) {
    logEvent('step_completion', {
        step_id: stepId,
        time_spent: timeSpent
    });
}

function trackCertificateDownload() {
    logEvent('certificate_download', {
        completed_steps: LearningPlatform.completedSteps.length,
        total_time: TimeTracker.totalTimeSpent
    });
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function getFormattedTime(milliseconds) {
    const seconds = Math.floor(milliseconds / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (hours > 0) {
        return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
    } else {
        return `${seconds}s`;
    }
}

function getTrackerStats() {
    return {
        total_time: TimeTracker.totalTimeSpent,
        total_time_formatted: getFormattedTime(TimeTracker.totalTimeSpent),
        current_step_time: TimeTracker.currentStepTime,
        current_step_time_formatted: getFormattedTime(TimeTracker.currentStepTime),
        events_logged: TimeTracker.eventBuffer.length,
        max_scroll_depth: TimeTracker.maxScrollDepth,
        is_tracking: TimeTracker.isTracking,
        is_online: TimeTracker.isOnline
    };
}

// ============================================================================
// AUTO-INIT AFTER PLATFORM LOADS
// ============================================================================

// Inicjalizuj tracker gdy platforma jest gotowa
document.addEventListener('DOMContentLoaded', function() {
    // Poczekaj aż learning.js zainicjalizuje platformę
    const checkPlatformReady = setInterval(() => {
        if (LearningPlatform.isAuthenticated) {
            clearInterval(checkPlatformReady);
            initTimeTracker();
        }
    }, 500);
    
    // Timeout po 10 sekundach
    setTimeout(() => {
        clearInterval(checkPlatformReady);
    }, 10000);
});

console.log('[Tracker] time_tracker.js załadowany');