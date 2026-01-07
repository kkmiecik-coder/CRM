/**
 * AI Chat Widget
 * Floating chat widget dla asystenta AI WoodPower CRM
 */

(function() {
    'use strict';

    // ================================
    // KONFIGURACJA
    // ================================
    const CONFIG = {
        apiEndpoint: '/ai-assistant/chat',
        streamEndpoint: '/ai-assistant/chat/stream',
        statusEndpoint: '/ai-assistant/status',
        storageKey: 'woodpower_ai_chat_history',
        maxHistoryMessages: 50,
        welcomeMessage: 'Cześć! Jestem asystentem WoodPower CRM. Mogę pomóc Ci w kwestiach związanych z produktami, zamówieniami i obsługą systemu. W czym mogę pomóc?',
        useSSE: true  // Włącz Server-Sent Events dla statusów
    };

    // ================================
    // STAN APLIKACJI
    // ================================
    let state = {
        isOpen: false,
        isLoading: false,
        history: [],
        hasBeenOpened: false
    };

    // ================================
    // ELEMENTY DOM
    // ================================
    let elements = {};

    // ================================
    // INICJALIZACJA
    // ================================
    function init() {
        createWidget();
        loadHistory();
        attachEventListeners();

        // Oznacz jako otwarte wcześniej
        if (localStorage.getItem('ai_chat_opened')) {
            state.hasBeenOpened = true;
            elements.trigger.classList.add('opened');
        }

        console.log('[AI Chat] Widget zainicjalizowany');
    }

    // ================================
    // TWORZENIE WIDGETU
    // ================================
    function createWidget() {
        // Floating trigger button
        const trigger = document.createElement('button');
        trigger.className = 'ai-chat-trigger';
        trigger.innerHTML = `
            <svg class="ai-chat-open-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/>
                <path d="M7 9h10v2H7zm0-3h10v2H7z"/>
            </svg>
            <svg class="ai-chat-close-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
        `;
        trigger.setAttribute('aria-label', 'Otwórz czat z asystentem AI');
        trigger.setAttribute('title', 'Asystent AI WoodPower');

        // Chat window
        const chatWindow = document.createElement('div');
        chatWindow.className = 'ai-chat-window';
        chatWindow.innerHTML = `
            <div class="ai-chat-header">
                <div class="ai-chat-avatar">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                    </svg>
                </div>
                <div class="ai-chat-header-info">
                    <h3 class="ai-chat-header-title">Asystent WoodPower</h3>
                    <p class="ai-chat-header-subtitle">Zawsze gotowy do pomocy</p>
                </div>
                <button class="ai-chat-header-close" aria-label="Zamknij czat">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                    </svg>
                </button>
            </div>
            <div class="ai-chat-messages" id="ai-chat-messages">
                <!-- Messages will be inserted here -->
            </div>
            <div class="ai-chat-input-container">
                <textarea
                    class="ai-chat-input"
                    id="ai-chat-input"
                    placeholder="Napisz wiadomość..."
                    rows="1"
                ></textarea>
                <button class="ai-chat-send" id="ai-chat-send" aria-label="Wyślij wiadomość">
                    <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                    </svg>
                </button>
            </div>
        `;

        // Dodaj do DOM
        document.body.appendChild(trigger);
        document.body.appendChild(chatWindow);

        // Zapisz referencje
        elements = {
            trigger: trigger,
            window: chatWindow,
            messages: chatWindow.querySelector('#ai-chat-messages'),
            input: chatWindow.querySelector('#ai-chat-input'),
            sendBtn: chatWindow.querySelector('#ai-chat-send'),
            closeBtn: chatWindow.querySelector('.ai-chat-header-close')
        };
    }

    // ================================
    // EVENT LISTENERS
    // ================================
    function attachEventListeners() {
        // Toggle chat
        elements.trigger.addEventListener('click', toggleChat);
        elements.closeBtn.addEventListener('click', closeChat);

        // Send message
        elements.sendBtn.addEventListener('click', sendMessage);
        elements.input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Auto-resize textarea
        elements.input.addEventListener('input', autoResizeTextarea);

        // Kliknięcie poza oknem - zamknij
        document.addEventListener('click', function(e) {
            if (state.isOpen &&
                !elements.window.contains(e.target) &&
                !elements.trigger.contains(e.target)) {
                closeChat();
            }
        });

        // Escape key - zamknij
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && state.isOpen) {
                closeChat();
            }
        });
    }

    // ================================
    // TOGGLE CHAT
    // ================================
    function toggleChat() {
        if (state.isOpen) {
            closeChat();
        } else {
            openChat();
        }
    }

    function openChat() {
        state.isOpen = true;
        elements.window.classList.add('open');
        elements.trigger.classList.add('active');
        elements.input.focus();

        // Oznacz jako otwarte
        if (!state.hasBeenOpened) {
            state.hasBeenOpened = true;
            localStorage.setItem('ai_chat_opened', 'true');
            elements.trigger.classList.add('opened');
        }

        // Renderuj historię lub powitanie
        renderMessages();
        scrollToBottom();
    }

    function closeChat() {
        state.isOpen = false;
        elements.window.classList.remove('open');
        elements.trigger.classList.remove('active');
    }

    // ================================
    // WYSYŁANIE WIADOMOŚCI
    // ================================
    async function sendMessage() {
        const message = elements.input.value.trim();

        if (!message || state.isLoading) {
            return;
        }

        // Wyczyść input
        elements.input.value = '';
        autoResizeTextarea();

        // Dodaj wiadomość użytkownika
        addMessage('user', message);

        // Pokaż typing indicator
        state.isLoading = true;
        elements.sendBtn.disabled = true;
        showTypingIndicator();

        console.log('[AI Chat] Wysyłam wiadomość:', message);

        // Przygotuj historię dla API (ostatnie 10 wiadomości)
        const historyForApi = state.history.slice(-10).map(msg => ({
            role: msg.role,
            content: msg.content
        }));

        if (CONFIG.useSSE) {
            // Użyj SSE dla statusów w czasie rzeczywistym
            sendMessageSSE(message, historyForApi);
        } else {
            // Fallback na zwykły fetch
            sendMessageFetch(message, historyForApi);
        }
    }

    /**
     * Wysyła wiadomość używając Server-Sent Events
     */
    async function sendMessageSSE(message, historyForApi) {
        console.log('[AI Chat] Używam SSE endpoint:', CONFIG.streamEndpoint);

        try {
            // SSE wymaga POST, więc musimy użyć fetch + reader zamiast EventSource
            const response = await fetch(CONFIG.streamEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    history: historyForApi
                })
            });

            if (!response.ok) {
                // Błąd HTTP - spróbuj sparsować jako JSON
                const errorText = await response.text();
                let errorMsg = `Błąd serwera: ${response.status}`;
                try {
                    const errorData = JSON.parse(errorText);
                    errorMsg = errorData.error || errorMsg;
                } catch (e) {}

                hideTypingIndicator();
                addMessage('error', errorMsg);
                state.isLoading = false;
                elements.sendBtn.disabled = false;
                return;
            }

            // Odczytuj stream SSE
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) {
                    console.log('[AI Chat] SSE stream zakończony');
                    break;
                }

                buffer += decoder.decode(value, { stream: true });

                // Przetwórz kompletne eventy (oddzielone \n\n)
                const events = buffer.split('\n\n');
                buffer = events.pop(); // Ostatni może być niekompletny

                for (const eventText of events) {
                    if (!eventText.trim() || eventText.startsWith(':')) {
                        // Pomiń puste i komentarze (keepalive)
                        continue;
                    }

                    // Parsuj event SSE
                    const lines = eventText.split('\n');
                    let eventType = 'message';
                    let eventData = '';

                    for (const line of lines) {
                        if (line.startsWith('event:')) {
                            eventType = line.slice(6).trim();
                        } else if (line.startsWith('data:')) {
                            eventData = line.slice(5).trim();
                        }
                    }

                    if (!eventData) continue;

                    try {
                        const data = JSON.parse(eventData);
                        handleSSEEvent(eventType, data);

                        // Zakończ po complete lub error
                        if (eventType === 'complete' || eventType === 'error') {
                            return;
                        }
                    } catch (e) {
                        console.error('[AI Chat] Błąd parsowania SSE:', e, eventData);
                    }
                }
            }

        } catch (error) {
            console.error('[AI Chat] SSE error:', error);
            hideTypingIndicator();
            addMessage('error', `Problem z połączeniem: ${error.message}`);
        } finally {
            state.isLoading = false;
            elements.sendBtn.disabled = false;
            elements.input.focus();
        }
    }

    /**
     * Tłumaczy angielskie komunikaty błędów na polski
     */
    function translateErrorMessage(message) {
        const translations = {
            'The model is overloaded. Please try again later.': 'Mam za duże obciążenie. Proszę spróbuj zapytać jeszcze raz za chwilę.',
            'model is overloaded': 'Model AI jest przeciążony. Spróbuj ponownie za chwilę.',
            'rate limit': 'Osiągnięto limit zapytań.',
            'timeout': 'Przekroczono czas oczekiwania na odpowiedź.',
        };

        // Sprawdź dokładne dopasowanie
        if (translations[message]) {
            return translations[message];
        }

        // Sprawdź częściowe dopasowanie (case-insensitive)
        const messageLower = message.toLowerCase();
        for (const [eng, pl] of Object.entries(translations)) {
            if (messageLower.includes(eng.toLowerCase())) {
                return pl;
            }
        }

        return message;
    }

    /**
     * Obsługuje zdarzenia SSE
     */
    function handleSSEEvent(eventType, data) {
        console.log('[AI Chat] SSE event:', eventType, data);

        switch (eventType) {
            case 'status':
                // Aktualizuj tekst statusu
                updateTypingStatus(data.message);
                break;

            case 'complete':
                // Odpowiedź gotowa
                hideTypingIndicator();
                addMessage('assistant', data.response);
                break;

            case 'error':
                // Błąd
                hideTypingIndicator();
                if (data.retry_after) {
                    addMessage('error', `⏳ Osiągnięto limit zapytań. Spróbuj ponownie za **${data.retry_after} sekund**.`);
                } else {
                    const errorMsg = translateErrorMessage(data.error || 'Wystąpił nieznany błąd');
                    addMessage('error', errorMsg);
                }
                break;
        }
    }

    /**
     * Fallback - wysyła wiadomość używając zwykłego fetch
     */
    async function sendMessageFetch(message, historyForApi) {
        console.log('[AI Chat] Wysyłam request do:', CONFIG.apiEndpoint);

        try {
            const response = await fetch(CONFIG.apiEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    history: historyForApi
                })
            });

            console.log('[AI Chat] Response status:', response.status);

            // Spróbuj sparsować JSON
            let data;
            const responseText = await response.text();
            console.log('[AI Chat] Response body:', responseText.substring(0, 500));

            try {
                data = JSON.parse(responseText);
            } catch (parseError) {
                console.error('[AI Chat] Błąd parsowania JSON:', parseError);
                console.error('[AI Chat] Raw response:', responseText);
                hideTypingIndicator();
                addMessage('error', `Błąd serwera (nie-JSON response). Status: ${response.status}`);
                return;
            }

            hideTypingIndicator();

            if (data.success) {
                console.log('[AI Chat] Sukces! Odpowiedź:', data.response?.substring(0, 100));
                addMessage('assistant', data.response);
            } else {
                // Sprawdź czy to błąd limitu z czasem retry
                if (data.retry_after) {
                    const retryMsg = `⏳ Osiągnięto limit zapytań. Spróbuj ponownie za **${data.retry_after} sekund**.`;
                    addMessage('error', retryMsg);
                } else {
                    const errorMsg = translateErrorMessage(data.error || 'Wystąpił nieznany błąd');
                    console.error('[AI Chat] Błąd z serwera:', errorMsg);
                    addMessage('error', errorMsg);
                }
            }
        } catch (error) {
            console.error('[AI Chat] Fetch error:', error);
            console.error('[AI Chat] Error stack:', error.stack);
            hideTypingIndicator();
            addMessage('error', translateErrorMessage(`Problem z połączeniem: ${error.message}`));
        } finally {
            state.isLoading = false;
            elements.sendBtn.disabled = false;
            elements.input.focus();
        }
    }

    // ================================
    // ZARZĄDZANIE WIADOMOŚCIAMI
    // ================================
    function addMessage(role, content) {
        const message = {
            role: role,
            content: content,
            timestamp: new Date().toISOString()
        };

        state.history.push(message);
        saveHistory();
        renderMessage(message);
        scrollToBottom();
    }

    function renderMessages() {
        elements.messages.innerHTML = '';

        if (state.history.length === 0) {
            // Pokaż powitanie
            renderWelcome();
        } else {
            // Renderuj historię
            state.history.forEach(msg => renderMessage(msg));

            // Dodaj przycisk czyszczenia
            const clearBtn = document.createElement('button');
            clearBtn.className = 'ai-chat-clear';
            clearBtn.textContent = 'Wyczyść historię';
            clearBtn.addEventListener('click', clearHistory);
            elements.messages.appendChild(clearBtn);
        }
    }

    function renderMessage(message) {
        const div = document.createElement('div');
        div.className = `ai-chat-message ${message.role}`;

        // Konwersja markdown
        let content = message.content;

        // WAŻNE: Linki markdown [tekst](url) - musi być przed innymi zamianami!
        content = content.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

        // Separator poziomy --- (musi być przed pogrubieniem)
        content = content.replace(/\n---\n/g, '<hr class="ai-chat-separator">');

        // Pogrubienie **tekst**
        content = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Kursywa *tekst* (ale nie ** które już zamieniliśmy)
        content = content.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

        // Listy punktowane
        content = content.replace(/\n- /g, '<br>• ');

        // Listy numerowane
        content = content.replace(/\n\d+\. /g, function(match) {
            return '<br>' + match.trim() + ' ';
        });

        // Kod inline `tekst`
        content = content.replace(/`(.*?)`/g, '<code>$1</code>');

        // Nowe linie
        content = content.replace(/\n/g, '<br>');

        div.innerHTML = content;

        // Wstaw przed przyciskiem clear (jeśli istnieje)
        const clearBtn = elements.messages.querySelector('.ai-chat-clear');
        if (clearBtn) {
            elements.messages.insertBefore(div, clearBtn);
        } else {
            elements.messages.appendChild(div);
        }
    }

    function renderWelcome() {
        const welcome = document.createElement('div');
        welcome.className = 'ai-chat-welcome';
        welcome.innerHTML = `
            <div class="ai-chat-welcome-icon">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                </svg>
            </div>
            <h4>Witaj!</h4>
            <p>${CONFIG.welcomeMessage}</p>
            <div class="ai-chat-quick-actions">
                <button class="ai-chat-quick-action" data-question="Jakie macie gatunki drewna?">Gatunki drewna</button>
                <button class="ai-chat-quick-action" data-question="Jakie są dostępne wymiary desek?">Wymiary desek</button>
                <button class="ai-chat-quick-action" data-question="Jak działa panel produkcji?">Panel produkcji</button>
            </div>
        `;

        // Event listeners dla quick actions
        welcome.querySelectorAll('.ai-chat-quick-action').forEach(btn => {
            btn.addEventListener('click', function() {
                const question = this.getAttribute('data-question');
                elements.input.value = question;
                sendMessage();
            });
        });

        elements.messages.appendChild(welcome);
    }

    // ================================
    // TYPING INDICATOR
    // ================================
    function showTypingIndicator() {
        const typing = document.createElement('div');
        typing.className = 'ai-chat-typing';
        typing.id = 'ai-chat-typing';
        typing.innerHTML = `
            <div class="ai-chat-typing-icon">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                </svg>
            </div>
            <span class="ai-chat-typing-text">Przetwarzam...</span>
        `;
        elements.messages.appendChild(typing);
        scrollToBottom();
    }

    function updateTypingStatus(message) {
        const typingText = document.querySelector('#ai-chat-typing .ai-chat-typing-text');
        if (typingText) {
            typingText.textContent = message;
            scrollToBottom();
        }
    }

    function hideTypingIndicator() {
        const typing = document.getElementById('ai-chat-typing');
        if (typing) {
            typing.remove();
        }
    }

    // ================================
    // STORAGE
    // ================================
    function loadHistory() {
        try {
            const saved = localStorage.getItem(CONFIG.storageKey);
            if (saved) {
                state.history = JSON.parse(saved);
                // Limit historii
                if (state.history.length > CONFIG.maxHistoryMessages) {
                    state.history = state.history.slice(-CONFIG.maxHistoryMessages);
                    saveHistory();
                }
            }
        } catch (e) {
            console.error('[AI Chat] Error loading history:', e);
            state.history = [];
        }
    }

    function saveHistory() {
        try {
            // Limit historii przed zapisem
            if (state.history.length > CONFIG.maxHistoryMessages) {
                state.history = state.history.slice(-CONFIG.maxHistoryMessages);
            }
            localStorage.setItem(CONFIG.storageKey, JSON.stringify(state.history));
        } catch (e) {
            console.error('[AI Chat] Error saving history:', e);
        }
    }

    function clearHistory() {
        if (confirm('Czy na pewno chcesz wyczyścić historię rozmowy?')) {
            state.history = [];
            localStorage.removeItem(CONFIG.storageKey);
            renderMessages();
        }
    }

    // ================================
    // HELPERS
    // ================================
    function scrollToBottom() {
        setTimeout(() => {
            elements.messages.scrollTop = elements.messages.scrollHeight;
        }, 100);
    }

    function autoResizeTextarea() {
        const textarea = elements.input;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
    }

    // ================================
    // START
    // ================================
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
