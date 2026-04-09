(function() {
    'use strict';

    function initAll() {

    // ============ FULL-PAGE MODE (existing templates) ============
    var convList = document.getElementById('conversations-list');
    if (convList) {
        initConversationsPage();
    }

    var messagesContainer = document.getElementById('messages-container');
    if (messagesContainer) {
        initChatPage();
    }

    var newBtn = document.getElementById('new-conversation-btn');
    if (newBtn) {
        newBtn.addEventListener('click', createNewConversationFullPage);
    }

    async function createNewConversationFullPage() {
        try {
            var resp = await fetch('/ai-assistant/api/conversations', { method: 'POST' });
            var data = await resp.json();
            if (data.success) {
                window.location.href = '/ai-assistant/conversation/' + data.conversation.id;
            }
        } catch (e) {
            console.error('Error creating conversation:', e);
        }
    }

    async function initConversationsPage() {
        try {
            var resp = await fetch('/ai-assistant/api/conversations');
            var data = await resp.json();
            if (data.success) {
                renderConversationsListFullPage(data.conversations);
            }
        } catch (e) {
            convList.innerHTML = '<p class="ai-error">Błąd ładowania rozmów</p>';
        }
    }

    function renderConversationsListFullPage(conversations) {
        if (conversations.length === 0) {
            convList.innerHTML = '<p class="ai-empty">Brak rozmów. Kliknij "+ Nowa rozmowa" żeby zacząć.</p>';
            return;
        }
        convList.innerHTML = conversations.map(function(c) {
            var timeAgo = getRelativeTime(c.last_message_at || c.created_at);
            var ownerInfo = c.user_name ? '<span class="ai-conv-owner">' + escapeHtml(c.user_name) + '</span> — ' : '';
            return '<a href="/ai-assistant/conversation/' + c.id + '" class="ai-conv-item">' +
                '<div class="ai-conv-title">' + ownerInfo + escapeHtml(c.title) + '</div>' +
                '<div class="ai-conv-time">' + timeAgo + '</div>' +
                '</a>';
        }).join('');
    }

    var fpPollInterval = null;
    var fpIsLoading = false;

    function initChatPage() {
        var main = document.querySelector('main.main-content');
        var conversationId = main.dataset.conversationId;
        var isReadonly = main.dataset.readonly === 'true';

        loadMessagesFullPage(conversationId);

        if (!isReadonly) {
            var input = document.getElementById('message-input');
            var sendBtn = document.getElementById('send-btn');

            sendBtn.addEventListener('click', function() { sendMessageFullPage(conversationId); });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessageFullPage(conversationId);
                }
            });
            input.addEventListener('input', function() {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            });
        }
    }

    async function loadMessagesFullPage(conversationId) {
        try {
            var resp = await fetch('/ai-assistant/api/conversations/' + conversationId + '/messages');
            var data = await resp.json();
            if (data.success) {
                renderMessagesFullPage(data.messages);
            }
        } catch (e) {
            messagesContainer.innerHTML = '<p class="ai-error">Błąd ładowania wiadomości</p>';
        }
    }

    function renderMessagesFullPage(messages) {
        if (messages.length === 0) {
            messagesContainer.innerHTML = '<p class="ai-empty">Rozpocznij rozmowę...</p>';
            return;
        }
        messagesContainer.innerHTML = messages.map(function(m) {
            return '<div class="ai-message ai-message-' + m.role + '">' +
                renderMarkdown(m.content) +
                '</div>';
        }).join('');
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    async function sendMessageFullPage(conversationId) {
        var input = document.getElementById('message-input');
        var message = input.value.trim();
        if (!message || fpIsLoading) return;

        input.value = '';
        input.style.height = 'auto';
        fpIsLoading = true;
        document.getElementById('send-btn').disabled = true;

        appendMessageFullPage('user', message);

        // Thinking placeholder w miejscu odpowiedzi bota
        var thinkingEl = document.createElement('div');
        thinkingEl.className = 'ai-message ai-message-assistant ai-message-thinking';
        thinkingEl.textContent = 'Analizuję pytanie...';
        messagesContainer.appendChild(thinkingEl);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        try {
            var resp = await fetch('/ai-assistant/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, conversation_id: parseInt(conversationId) })
            });
            var data = await resp.json();

            if (data.success && data.request_id) {
                startPollingFullPage(data.request_id, thinkingEl);
            } else if (data.success && data.response) {
                thinkingEl.className = 'ai-message ai-message-assistant';
                thinkingEl.innerHTML = renderMarkdown(data.response);
                fpIsLoading = false;
                document.getElementById('send-btn').disabled = false;
            } else {
                thinkingEl.className = 'ai-message ai-message-error';
                thinkingEl.innerHTML = renderMarkdown(data.error || 'Błąd wysyłania');
                fpIsLoading = false;
                document.getElementById('send-btn').disabled = false;
            }
        } catch (e) {
            thinkingEl.className = 'ai-message ai-message-error';
            thinkingEl.textContent = 'Problem z połączeniem';
            fpIsLoading = false;
            document.getElementById('send-btn').disabled = false;
        }
    }

    function startPollingFullPage(requestId) {
        fpPollInterval = setInterval(async function() {
            try {
                var resp = await fetch('/ai-assistant/api/chat/status/' + requestId);
                var data = await resp.json();
                if (!data.success) {
                    clearInterval(fpPollInterval);
                    hideStatusFullPage();
                    appendMessageFullPage('error', data.error || 'Błąd');
                    fpIsLoading = false;
                    document.getElementById('send-btn').disabled = false;
                    return;
                }
                if (data.status === 'complete') {
                    clearInterval(fpPollInterval);
                    hideStatusFullPage();
                    appendMessageFullPage('assistant', data.response);
                    fpIsLoading = false;
                    document.getElementById('send-btn').disabled = false;
                    document.getElementById('message-input').focus();
                } else if (data.status === 'error') {
                    clearInterval(fpPollInterval);
                    hideStatusFullPage();
                    appendMessageFullPage('error', data.error || 'Wystąpił błąd');
                    fpIsLoading = false;
                    document.getElementById('send-btn').disabled = false;
                } else {
                    showStatusFullPage(getStatusText(data.status));
                }
            } catch (e) { /* keep polling */ }
        }, 1500);
    }

    function appendMessageFullPage(role, content) {
        var empty = messagesContainer.querySelector('.ai-empty');
        if (empty) empty.remove();
        var div = document.createElement('div');
        div.className = 'ai-message ai-message-' + role;
        div.innerHTML = renderMarkdown(content);
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function showStatusFullPage(text) {
        var el = document.getElementById('status-indicator');
        if (el) { el.textContent = text; el.style.display = 'block'; }
    }

    function hideStatusFullPage() {
        var el = document.getElementById('status-indicator');
        if (el) { el.style.display = 'none'; }
    }

    // ============ FLOATING WIDGET ============

    // Don't create widget if we're on the full-page AI assistant
    if (document.querySelector('.ai-chat-container') || convList) {
        return;
    }

    var widgetState = {
        panelOpen: false,
        currentView: 'list', // 'list' or 'chat'
        currentConversationId: null,
        isLoading: false,
        pollInterval: null
    };

    // --- Build DOM ---
    var trigger = document.createElement('button');
    trigger.className = 'ai-chat-trigger';
    trigger.setAttribute('aria-label', 'Otwórz Asystenta AI');
    trigger.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

    var panel = document.createElement('div');
    panel.className = 'ai-chat-panel';
    panel.innerHTML =
        '<div class="ai-chat-header">' +
            '<span class="ai-chat-header-title">Asystent AI</span>' +
            '<div class="ai-chat-header-actions"></div>' +
        '</div>' +
        '<div class="ai-chat-content"></div>' +
        '<div class="ai-chat-input-area" style="display:none;">' +
            '<div class="ai-chat-input-row">' +
                '<textarea class="ai-chat-input" placeholder="Napisz wiadomość..." rows="1"></textarea>' +
                '<button class="ai-chat-send-btn ai-btn ai-btn-primary">Wyślij</button>' +
            '</div>' +
            '<div class="ai-chat-status" style="display:none;"></div>' +
        '</div>';

    document.body.appendChild(trigger);
    document.body.appendChild(panel);

    var headerTitle = panel.querySelector('.ai-chat-header-title');
    var headerActions = panel.querySelector('.ai-chat-header-actions');
    var content = panel.querySelector('.ai-chat-content');
    var inputArea = panel.querySelector('.ai-chat-input-area');
    var inputEl = panel.querySelector('.ai-chat-input');
    var sendBtn = panel.querySelector('.ai-chat-send-btn');
    var statusEl = panel.querySelector('.ai-chat-status');

    // --- Toggle panel ---
    trigger.addEventListener('click', function() {
        if (widgetState.panelOpen) {
            closePanel();
        } else {
            openPanel();
        }
    });

    function openPanel() {
        widgetState.panelOpen = true;
        panel.classList.add('open');
        localStorage.setItem('aiWidgetOpen', '1');
        if (widgetState.currentView === 'list') {
            showConversationList();
        } else {
            showChat(widgetState.currentConversationId);
        }
    }

    function closePanel() {
        widgetState.panelOpen = false;
        panel.classList.remove('open');
        localStorage.setItem('aiWidgetOpen', '0');
        stopWidgetPolling();
    }

    // ESC to close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && widgetState.panelOpen) {
            closePanel();
        }
    });

    // Click outside to close
    document.addEventListener('mousedown', function(e) {
        if (widgetState.panelOpen && !panel.contains(e.target) && !trigger.contains(e.target)) {
            closePanel();
        }
    });

    // --- View A: Conversation List ---
    async function showConversationList() {
        widgetState.currentView = 'list';
        widgetState.currentConversationId = null;
        stopWidgetPolling();

        headerTitle.textContent = 'Asystent AI';
        headerActions.innerHTML = '<button class="ai-btn ai-btn-primary ai-chat-header-btn">Nowa</button>';
        headerActions.querySelector('button').addEventListener('click', createWidgetConversation);

        inputArea.style.display = 'none';
        content.innerHTML = '<p class="ai-chat-loading">Ładowanie...</p>';

        try {
            var resp = await fetch('/ai-assistant/api/conversations');
            var data = await resp.json();
            if (data.success) {
                renderWidgetConversationList(data.conversations);
            } else {
                content.innerHTML = '<p class="ai-error">Błąd ładowania rozmów</p>';
            }
        } catch (e) {
            content.innerHTML = '<p class="ai-error">Błąd połączenia</p>';
        }
    }

    function renderWidgetConversationList(conversations) {
        if (conversations.length === 0) {
            content.innerHTML =
                '<div class="ai-chat-empty">' +
                    '<p>Rozpocznij nową rozmowę</p>' +
                    '<button class="ai-btn ai-btn-primary ai-chat-empty-btn">Nowa rozmowa</button>' +
                '</div>';
            content.querySelector('.ai-chat-empty-btn').addEventListener('click', createWidgetConversation);
            return;
        }
        content.innerHTML = '<div class="ai-chat-conv-list">' +
            conversations.map(function(c) {
                var timeAgo = getRelativeTime(c.last_message_at || c.created_at);
                return '<div class="ai-chat-conv-item" data-id="' + c.id + '">' +
                    '<div class="ai-chat-conv-title">' + escapeHtml(c.title) + '</div>' +
                    '<div class="ai-chat-conv-time">' + timeAgo + '</div>' +
                '</div>';
            }).join('') +
        '</div>';

        content.querySelectorAll('.ai-chat-conv-item').forEach(function(el) {
            el.addEventListener('click', function() {
                showChat(parseInt(this.dataset.id));
            });
        });
    }

    async function createWidgetConversation() {
        try {
            var resp = await fetch('/ai-assistant/api/conversations', { method: 'POST' });
            var data = await resp.json();
            if (data.success) {
                showChat(data.conversation.id);
            }
        } catch (e) {
            console.error('Error creating conversation:', e);
        }
    }

    // --- View B: Chat ---
    async function showChat(conversationId) {
        widgetState.currentView = 'chat';
        widgetState.currentConversationId = conversationId;
        widgetState.isLoading = false;

        headerTitle.textContent = 'Rozmowa';
        headerActions.innerHTML =
            '<button class="ai-btn ai-btn-secondary ai-chat-header-btn ai-chat-back-btn">Lista</button>' +
            '<button class="ai-btn ai-btn-primary ai-chat-header-btn">Nowa</button>';
        headerActions.querySelector('.ai-chat-back-btn').addEventListener('click', showConversationList);
        headerActions.querySelectorAll('button')[1].addEventListener('click', createWidgetConversation);

        inputArea.style.display = 'block';
        sendBtn.disabled = false;
        statusEl.style.display = 'none';
        content.innerHTML = '<p class="ai-chat-loading">Ładowanie...</p>';

        try {
            var resp = await fetch('/ai-assistant/api/conversations/' + conversationId + '/messages');
            var data = await resp.json();
            if (data.success) {
                renderWidgetMessages(data.messages);
            } else {
                content.innerHTML = '<p class="ai-error">Błąd ładowania wiadomości</p>';
            }
        } catch (e) {
            content.innerHTML = '<p class="ai-error">Błąd połączenia</p>';
        }

        inputEl.focus();
    }

    function renderWidgetMessages(messages) {
        if (messages.length === 0) {
            content.innerHTML = '<div class="ai-chat-messages"><p class="ai-empty">Rozpocznij rozmowę...</p></div>';
            return;
        }
        content.innerHTML = '<div class="ai-chat-messages">' +
            messages.map(function(m) {
                return '<div class="ai-message ai-message-' + m.role + '">' +
                    renderMarkdown(m.content) +
                '</div>';
            }).join('') +
        '</div>';
        scrollWidgetToBottom();
    }

    function appendWidgetMessage(role, text) {
        var msgs = content.querySelector('.ai-chat-messages');
        if (!msgs) {
            content.innerHTML = '<div class="ai-chat-messages"></div>';
            msgs = content.querySelector('.ai-chat-messages');
        }
        var empty = msgs.querySelector('.ai-empty');
        if (empty) empty.remove();

        var div = document.createElement('div');
        div.className = 'ai-message ai-message-' + role;
        div.innerHTML = renderMarkdown(text);
        msgs.appendChild(div);
        scrollWidgetToBottom();
    }

    function appendWidgetThinking(text) {
        var msgs = content.querySelector('.ai-chat-messages');
        if (!msgs) {
            content.innerHTML = '<div class="ai-chat-messages"></div>';
            msgs = content.querySelector('.ai-chat-messages');
        }
        var div = document.createElement('div');
        div.className = 'ai-message ai-message-assistant ai-message-thinking';
        div.textContent = text;
        msgs.appendChild(div);
        scrollWidgetToBottom();
        return div;
    }

    function replaceWidgetThinking(div, text, isError) {
        if (!div) return;
        div.className = 'ai-message ' + (isError ? 'ai-message-error' : 'ai-message-assistant');
        div.classList.remove('ai-message-thinking');
        div.innerHTML = renderMarkdown(text);
        scrollWidgetToBottom();
    }

    function scrollWidgetToBottom() {
        var msgs = content.querySelector('.ai-chat-messages');
        if (msgs) {
            content.scrollTop = content.scrollHeight;
        }
    }

    // --- Send message ---
    sendBtn.addEventListener('click', sendWidgetMessage);
    inputEl.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendWidgetMessage();
        }
    });
    inputEl.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 100) + 'px';
    });

    async function sendWidgetMessage() {
        var message = inputEl.value.trim();
        if (!message || widgetState.isLoading) return;

        inputEl.value = '';
        inputEl.style.height = 'auto';
        widgetState.isLoading = true;
        sendBtn.disabled = true;

        appendWidgetMessage('user', message);

        // Placeholder w miejscu odpowiedzi bota
        var thinkingDiv = appendWidgetThinking('Analizuję pytanie...');

        try {
            var resp = await fetch('/ai-assistant/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, conversation_id: widgetState.currentConversationId })
            });
            var data = await resp.json();

            if (data.success && data.request_id) {
                startWidgetPolling(data.request_id, thinkingDiv);
            } else if (data.success && (data.response || (data.data && data.data.response))) {
                var responseText = data.response || data.data.response;
                replaceWidgetThinking(thinkingDiv, responseText);
                widgetState.isLoading = false;
                sendBtn.disabled = false;
            } else {
                replaceWidgetThinking(thinkingDiv, data.error || 'Błąd wysyłania', true);
                widgetState.isLoading = false;
                sendBtn.disabled = false;
            }
        } catch (e) {
            replaceWidgetThinking(thinkingDiv, 'Problem z połączeniem', true);
            widgetState.isLoading = false;
            sendBtn.disabled = false;
        }
    }

    function startWidgetPolling(requestId, thinkingDiv) {
        widgetState.pollInterval = setInterval(async function() {
            try {
                var resp = await fetch('/ai-assistant/api/chat/status/' + requestId);
                var data = await resp.json();

                if (!data.success) {
                    stopWidgetPolling();
                    replaceWidgetThinking(thinkingDiv, data.error || 'Błąd', true);
                    widgetState.isLoading = false;
                    sendBtn.disabled = false;
                    return;
                }

                if (data.status === 'complete') {
                    stopWidgetPolling();
                    replaceWidgetThinking(thinkingDiv, data.response);
                    widgetState.isLoading = false;
                    sendBtn.disabled = false;
                    inputEl.focus();
                } else if (data.status === 'error') {
                    stopWidgetPolling();
                    replaceWidgetThinking(thinkingDiv, data.error || 'Wystąpił błąd', true);
                    widgetState.isLoading = false;
                    sendBtn.disabled = false;
                } else {
                    if (thinkingDiv) thinkingDiv.textContent = getStatusText(data.status);
                }
            } catch (e) { /* keep polling */ }
        }, 1500);
    }

    function stopWidgetPolling() {
        if (widgetState.pollInterval) {
            clearInterval(widgetState.pollInterval);
            widgetState.pollInterval = null;
        }
    }

    function showWidgetStatus(text) {
        statusEl.textContent = text;
        statusEl.style.display = 'block';
    }

    function hideWidgetStatus() {
        statusEl.style.display = 'none';
    }

    // Restore state from localStorage
    if (localStorage.getItem('aiWidgetOpen') === '1') {
        openPanel();
    }

    // ============ SHARED HELPERS ============

    function getStatusText(status) {
        var texts = {
            'pending': 'Oczekuję...',
            'analyzing': 'Analizuję pytanie...',
            'knowledge_base': 'Przeszukuję bazę wiedzy...',
            'crm': 'Sprawdzam dane w CRM...',
            'baselinker': 'Pobieram dane z Baselinker...',
            'prestashop': 'Szukam produktów w sklepie...',
            'generating': 'Generuję odpowiedź...'
        };
        return texts[status] || 'Przetwarzam...';
    }

    function renderMarkdown(text) {
        if (!text) return '';
        var html = escapeHtml(text);
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\n---\n/g, '<hr>');
        html = html.replace(/\n- /g, '<br>• ');
        html = html.replace(/\n(\d+)\. /g, '<br>$1. ');
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getRelativeTime(isoString) {
        if (!isoString) return '';
        var date = new Date(isoString);
        var now = new Date();
        var diffMs = now - date;
        var diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return 'teraz';
        if (diffMin < 60) return diffMin + ' min temu';
        var diffHours = Math.floor(diffMin / 60);
        if (diffHours < 24) return diffHours + ' godz. temu';
        var diffDays = Math.floor(diffHours / 24);
        return diffDays + ' dni temu';
    }

    } // end initAll

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

})();
