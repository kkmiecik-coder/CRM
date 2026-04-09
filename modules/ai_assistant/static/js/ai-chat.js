(function() {
    'use strict';

    // ============ CONVERSATIONS LIST PAGE ============
    var convList = document.getElementById('conversations-list');
    if (convList) {
        initConversationsPage();
    }

    // ============ CHAT PAGE ============
    var messagesContainer = document.getElementById('messages-container');
    if (messagesContainer) {
        initChatPage();
    }

    // ============ SHARED: New conversation button ============
    var newBtn = document.getElementById('new-conversation-btn');
    if (newBtn) {
        newBtn.addEventListener('click', createNewConversation);
    }

    async function createNewConversation() {
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

    // ============ CONVERSATIONS LIST ============
    async function initConversationsPage() {
        try {
            var resp = await fetch('/ai-assistant/api/conversations');
            var data = await resp.json();
            if (data.success) {
                renderConversationsList(data.conversations);
            }
        } catch (e) {
            convList.innerHTML = '<p class="ai-error">Błąd ładowania rozmów</p>';
        }
    }

    function renderConversationsList(conversations) {
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

    // ============ CHAT PAGE ============
    var pollInterval = null;
    var isLoading = false;

    function initChatPage() {
        var main = document.querySelector('main.main-content');
        var conversationId = main.dataset.conversationId;
        var isReadonly = main.dataset.readonly === 'true';

        loadMessages(conversationId);

        if (!isReadonly) {
            var input = document.getElementById('message-input');
            var sendBtn = document.getElementById('send-btn');

            sendBtn.addEventListener('click', function() { sendMessage(conversationId); });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage(conversationId);
                }
            });
            // Auto-resize textarea
            input.addEventListener('input', function() {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            });
        }
    }

    async function loadMessages(conversationId) {
        try {
            var resp = await fetch('/ai-assistant/api/conversations/' + conversationId + '/messages');
            var data = await resp.json();
            if (data.success) {
                renderMessages(data.messages);
            }
        } catch (e) {
            messagesContainer.innerHTML = '<p class="ai-error">Błąd ładowania wiadomości</p>';
        }
    }

    function renderMessages(messages) {
        if (messages.length === 0) {
            messagesContainer.innerHTML = '<p class="ai-empty">Rozpocznij rozmowę...</p>';
            return;
        }
        messagesContainer.innerHTML = messages.map(function(m) {
            return '<div class="ai-message ai-message-' + m.role + '">' +
                renderMarkdown(m.content) +
                '</div>';
        }).join('');
        scrollToBottom();
    }

    async function sendMessage(conversationId) {
        var input = document.getElementById('message-input');
        var message = input.value.trim();
        if (!message || isLoading) return;

        input.value = '';
        input.style.height = 'auto';
        isLoading = true;
        document.getElementById('send-btn').disabled = true;

        // Add user message to UI
        appendMessage('user', message);

        // Show status
        showStatus('Analizuję pytanie...');

        try {
            var resp = await fetch('/ai-assistant/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, conversation_id: parseInt(conversationId) })
            });
            var data = await resp.json();

            if (data.success && data.request_id) {
                startPolling(data.request_id);
            } else {
                hideStatus();
                appendMessage('error', data.error || 'Błąd wysyłania');
                isLoading = false;
                document.getElementById('send-btn').disabled = false;
            }
        } catch (e) {
            hideStatus();
            appendMessage('error', 'Problem z połączeniem');
            isLoading = false;
            document.getElementById('send-btn').disabled = false;
        }
    }

    function startPolling(requestId) {
        pollInterval = setInterval(async function() {
            try {
                var resp = await fetch('/ai-assistant/api/chat/status/' + requestId);
                var data = await resp.json();

                if (!data.success) {
                    stopPolling();
                    hideStatus();
                    appendMessage('error', data.error || 'Błąd');
                    isLoading = false;
                    document.getElementById('send-btn').disabled = false;
                    return;
                }

                // Status mapping for Polish display
                var statusTexts = {
                    'pending': 'Oczekuję...',
                    'analyzing': 'Analizuję pytanie...',
                    'knowledge_base': 'Przeszukuję bazę wiedzy...',
                    'crm': 'Sprawdzam dane w CRM...',
                    'baselinker': 'Pobieram dane z Baselinker...',
                    'prestashop': 'Szukam produktów w sklepie...',
                    'generating': 'Generuję odpowiedź...'
                };

                if (data.status === 'complete') {
                    stopPolling();
                    hideStatus();
                    appendMessage('assistant', data.response);
                    isLoading = false;
                    document.getElementById('send-btn').disabled = false;
                    document.getElementById('message-input').focus();
                } else if (data.status === 'error') {
                    stopPolling();
                    hideStatus();
                    appendMessage('error', data.error || 'Wystąpił błąd');
                    isLoading = false;
                    document.getElementById('send-btn').disabled = false;
                } else {
                    showStatus(statusTexts[data.status] || 'Przetwarzam...');
                }
            } catch (e) {
                // Network error — keep polling, might recover
            }
        }, 1500);
    }

    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    function appendMessage(role, content) {
        // Remove empty state message if present
        var empty = messagesContainer.querySelector('.ai-empty');
        if (empty) empty.remove();

        var div = document.createElement('div');
        div.className = 'ai-message ai-message-' + role;
        div.innerHTML = renderMarkdown(content);
        messagesContainer.appendChild(div);
        scrollToBottom();
    }

    function showStatus(text) {
        var el = document.getElementById('status-indicator');
        if (el) {
            el.textContent = text;
            el.style.display = 'block';
        }
    }

    function hideStatus() {
        var el = document.getElementById('status-indicator');
        if (el) {
            el.style.display = 'none';
        }
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // ============ HELPERS ============
    function renderMarkdown(text) {
        if (!text) return '';
        var html = escapeHtml(text);
        // Links [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        // Bold **text**
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Italic *text*
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
        // Code `text`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        // Horizontal rule
        html = html.replace(/\n---\n/g, '<hr>');
        // Bullet lists
        html = html.replace(/\n- /g, '<br>• ');
        // Numbered lists
        html = html.replace(/\n(\d+)\. /g, '<br>$1. ');
        // Newlines
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

})();
