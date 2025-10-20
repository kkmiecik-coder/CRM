// app/modules/issues/static/js/ticket_detail.js
/**
 * Logika dla widoku szczegółów ticketu (konwersacja)
 * Zawiera: Ładowanie wiadomości, formularz odpowiedzi, upload plików, modals akcji
 * 
 * Autor: Konrad Kmiecik
 * Data: 2025-01-20
 */

// ============================================================================
// NAMESPACE
// ============================================================================

const IssuesTicketDetail = {
    // Stan
    state: {
        ticketNumber: null,
        ticketData: null,
        messages: [],
        uploadedFiles: [],
        currentUserId: null,
        currentUserRole: null
    },

    // Elementy DOM
    elements: {}
};

// ============================================================================
// INICJALIZACJA
// ============================================================================

IssuesTicketDetail.init = function () {
    console.log('🚀 Inicjalizacja Ticket Detail...');

    // Pobierz dane z window.TICKET_DATA (ustawione w HTML)
    if (window.TICKET_DATA) {
        IssuesTicketDetail.state.ticketNumber = window.TICKET_DATA.ticket_number;
        IssuesTicketDetail.state.currentUserId = window.TICKET_DATA.current_user_id;
        IssuesTicketDetail.state.currentUserRole = window.TICKET_DATA.current_user_role;
    }

    // Pobierz elementy DOM
    IssuesTicketDetail.elements = {
        messagesContainer: document.getElementById('issuesMessagesContainer'),
        replyForm: document.getElementById('issuesReplyForm'),
        replyMessage: document.getElementById('issuesReplyMessage'),
        replyUploadArea: document.getElementById('issuesReplyUploadArea'),
        replyFileInput: document.getElementById('issuesReplyFileInput'),
        replyFilesList: document.getElementById('issuesReplyFilesList'),
        internalNote: document.getElementById('issuesInternalNote'),
        actionsDropdown: document.getElementById('issuesActionsDropdown'),
        actionsMenu: document.getElementById('issuesActionsMenu')
    };

    // Inicjalizuj komponenty
    IssuesTicketDetail.loadMessages();
    IssuesTicketDetail.initReplyForm();
    IssuesTicketDetail.initUpload();
    IssuesTicketDetail.initDropdown();
    IssuesTicketDetail.initModals();

    console.log('✅ Ticket Detail zainicjalizowany');
};

// ============================================================================
// ŁADOWANIE WIADOMOŚCI
// ============================================================================

IssuesTicketDetail.loadMessages = async function () {
    const container = IssuesTicketDetail.elements.messagesContainer;
    if (!container) return;

    try {
        // Loading state
        container.innerHTML = `
            <div class="issues-loading">
                <i class="fas fa-spinner fa-spin"></i> Ładowanie wiadomości...
            </div>
        `;

        // Pobierz wiadomości
        const response = await IssuesCommon.getMessages(IssuesTicketDetail.state.ticketNumber);
        IssuesTicketDetail.state.messages = response.messages;

        // Renderuj wiadomości
        IssuesTicketDetail.renderMessages();

    } catch (error) {
        console.error('Error loading messages:', error);
        container.innerHTML = `
            <div class="issues-ticket-empty">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Wystąpił błąd podczas ładowania wiadomości</p>
            </div>
        `;
    }
};

IssuesTicketDetail.renderMessages = function () {
    const container = IssuesTicketDetail.elements.messagesContainer;
    if (!container) return;

    const messages = IssuesTicketDetail.state.messages;

    if (messages.length === 0) {
        container.innerHTML = `
            <div class="issues-ticket-empty">
                <i class="fas fa-comments"></i>
                <p>Brak wiadomości</p>
            </div>
        `;
        return;
    }

    container.innerHTML = messages.map(msg => {
        // Odczytaj dane użytkownika - STRUKTURA PŁASKA Z BACKENDU
        const userEmail = msg.user_email || 'Nieznany użytkownik';
        const userName = msg.user_name || userEmail;

        // Sprawdź czy to admin (email z domeną woodpower.pl lub rsholding.com.pl)
        const isAdmin = userEmail.includes('@woodpower.pl') || userEmail.includes('@rsholding.com.pl');

        const isInternal = msg.is_internal_note || false;
        const showInternal = isInternal && IssuesTicketDetail.state.currentUserRole === 'admin';

        // Ukryj notatki wewnętrzne dla nie-adminów
        if (isInternal && IssuesTicketDetail.state.currentUserRole !== 'admin') {
            return '';
        }

        // Inicjały użytkownika
        const initials = userName.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);

        // Klasa CSS
        let messageClass = 'issues-message';
        if (isAdmin) messageClass += ' issues-message-admin';
        if (isInternal) messageClass += ' issues-message-internal';

        return `
            <div class="${messageClass}">
                <div class="issues-message-avatar ${isAdmin ? 'issues-message-avatar-admin' : ''}">
                    ${initials}
                </div>
                <div class="issues-message-content">
                    <div class="issues-message-header">
                        <div class="issues-message-author">
                            <div class="issues-message-name">${IssuesCommon.escapeHtml(userName)}</div>
                            ${isAdmin ? '<div class="issues-message-email">Administrator</div>' : ''}
                        </div>
                        <div class="issues-message-date">${IssuesCommon.formatDate(msg.created_at)}</div>
                    </div>
                    <div class="issues-message-text">${IssuesCommon.escapeHtml(msg.message)}</div>
                    ${showInternal ? `
                        <div class="issues-message-internal-badge">
                            <i class="fas fa-lock"></i> Notatka wewnętrzna
                        </div>
                    ` : ''}
                    ${msg.attachments && msg.attachments.length > 0 ? `
                        <div class="issues-message-attachments">
                            ${msg.attachments.map(att => `
                                <a href="/issues/api/attachments/${att.id}/download" class="issues-message-attachment" target="_blank">
                                    <i class="fas fa-paperclip"></i>
                                    <span>${IssuesCommon.escapeHtml(att.filename)}</span>
                                </a>
                            `).join('')}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');

    // Scroll na dół
    setTimeout(() => {
        container.scrollTop = container.scrollHeight;
    }, 100);
};

// ============================================================================
// FORMULARZ ODPOWIEDZI
// ============================================================================

IssuesTicketDetail.initReplyForm = function () {
    const form = IssuesTicketDetail.elements.replyForm;
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await IssuesTicketDetail.handleReplySubmit();
    });
};

IssuesTicketDetail.handleReplySubmit = async function () {
    const form = IssuesTicketDetail.elements.replyForm;
    const submitBtn = form.querySelector('button[type="submit"]');
    const messageInput = IssuesTicketDetail.elements.replyMessage;
    const internalNote = IssuesTicketDetail.elements.internalNote;

    try {
        // Disable przycisku
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Wysyłanie...';

        // Pobierz dane
        const message = messageInput.value.trim();
        const isInternal = internalNote ? internalNote.checked : false;

        // Walidacja
        if (!message || message.length < 5) {
            throw new Error('Wiadomość musi mieć min. 5 znaków');
        }

        // Wyślij wiadomość
        const messageData = {
            message: message,
            is_internal_note: isInternal,
            attachment_ids: IssuesTicketDetail.state.uploadedFiles.map(f => f.id)
        };

        await IssuesCommon.addMessage(IssuesTicketDetail.state.ticketNumber, messageData);

        // Sukces
        IssuesCommon.showToast('success', 'Odpowiedź wysłana!');

        // Reset formularza
        messageInput.value = '';
        if (internalNote) internalNote.checked = false;
        IssuesTicketDetail.clearReplyFiles();

        // Odśwież wiadomości
        await IssuesTicketDetail.loadMessages();

    } catch (error) {
        console.error('Error submitting reply:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    } finally {
        // Przywróć przycisk
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Wyślij odpowiedź';
    }
};

// ============================================================================
// UPLOAD PLIKÓW (REPLY)
// ============================================================================

IssuesTicketDetail.initUpload = function () {
    const uploadArea = IssuesTicketDetail.elements.replyUploadArea;
    const fileInput = IssuesTicketDetail.elements.replyFileInput;

    if (!uploadArea || !fileInput) return;

    // Kliknięcie w upload area
    uploadArea.addEventListener('click', (e) => {
        if (e.target !== fileInput) {
            fileInput.click();
        }
    });

    // Wybór plików
    fileInput.addEventListener('change', () => {
        IssuesTicketDetail.handleReplyFileSelect(fileInput.files);
    });

    // Drag & Drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('issues-drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('issues-drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('issues-drag-over');
        IssuesTicketDetail.handleReplyFileSelect(e.dataTransfer.files);
    });
};

IssuesTicketDetail.handleReplyFileSelect = async function (files) {
    const fileArray = Array.from(files);

    // Sprawdź limit
    if (IssuesTicketDetail.state.uploadedFiles.length + fileArray.length > IssuesCommon.config.maxFiles) {
        IssuesCommon.showToast('error', 'Za dużo plików', `Możesz dodać maksymalnie ${IssuesCommon.config.maxFiles} plików`);
        return;
    }

    // Upload każdego pliku
    for (const file of fileArray) {
        try {
            // Walidacja
            IssuesCommon.validateFile(file);

            // Upload
            const response = await IssuesCommon.uploadAttachment(file);

            // Dodaj do stanu
            IssuesTicketDetail.state.uploadedFiles.push({
                id: response.attachment_id,
                filename: file.name,
                size: file.size
            });

            // Odśwież UI
            IssuesTicketDetail.renderReplyFilesList();

        } catch (error) {
            console.error('Upload error:', error);
            IssuesCommon.showToast('error', 'Błąd uploadu', error.message);
        }
    }

    // Wyczyść input
    IssuesTicketDetail.elements.replyFileInput.value = '';
};

IssuesTicketDetail.renderReplyFilesList = function () {
    const filesList = IssuesTicketDetail.elements.replyFilesList;
    if (!filesList) return;

    if (IssuesTicketDetail.state.uploadedFiles.length === 0) {
        filesList.innerHTML = '';
        return;
    }

    filesList.innerHTML = IssuesTicketDetail.state.uploadedFiles.map((file, index) => `
        <div class="issues-file-item" data-index="${index}">
            <div class="issues-file-info">
                <i class="fas fa-file issues-file-icon"></i>
                <div class="issues-file-details">
                    <p class="issues-file-name">${IssuesCommon.escapeHtml(file.filename)}</p>
                    <p class="issues-file-size">${IssuesCommon.formatFileSize(file.size)}</p>
                </div>
            </div>
            <button type="button" class="issues-file-remove" data-index="${index}">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');

    // Obsługa usuwania
    filesList.querySelectorAll('.issues-file-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            const index = parseInt(btn.dataset.index);
            IssuesTicketDetail.removeReplyFile(index);
        });
    });
};

IssuesTicketDetail.removeReplyFile = function (index) {
    IssuesTicketDetail.state.uploadedFiles.splice(index, 1);
    IssuesTicketDetail.renderReplyFilesList();
};

IssuesTicketDetail.clearReplyFiles = function () {
    IssuesTicketDetail.state.uploadedFiles = [];
    IssuesTicketDetail.renderReplyFilesList();
};

// ============================================================================
// DROPDOWN MENU (AKCJE)
// ============================================================================

IssuesTicketDetail.initDropdown = function () {
    const dropdown = IssuesTicketDetail.elements.actionsDropdown;
    const menu = IssuesTicketDetail.elements.actionsMenu;

    if (!dropdown || !menu) return;

    // Toggle menu
    dropdown.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('issues-show');
    });

    // Zamknij przy kliknięciu poza menu
    document.addEventListener('click', () => {
        menu.classList.remove('issues-show');
    });

    // Obsługa akcji
    menu.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = btn.dataset.action;
            IssuesTicketDetail.handleAction(action);
            menu.classList.remove('issues-show');
        });
    });
};

IssuesTicketDetail.handleAction = function (action) {
    switch (action) {
        case 'change-status':
            IssuesTicketDetail.showChangeStatusModal();
            break;
        case 'change-priority':
            IssuesTicketDetail.showChangePriorityModal();
            break;
        case 'assign-to-me':
            IssuesTicketDetail.assignToMe();
            break;
        case 'close-ticket':
            IssuesTicketDetail.closeTicket();
            break;
    }
};

// ============================================================================
// MODALS
// ============================================================================

IssuesTicketDetail.initModals = function () {
    // Modal: Zmiana statusu
    const statusModal = document.getElementById('issuesChangeStatusModal');
    const statusConfirm = document.getElementById('issuesConfirmStatusChange');

    if (statusConfirm) {
        statusConfirm.addEventListener('click', async () => {
            const newStatus = document.getElementById('issuesNewStatus').value;
            await IssuesTicketDetail.changeStatus(newStatus);
            IssuesTicketDetail.closeModal(statusModal);
        });
    }

    // Modal: Zmiana priorytetu
    const priorityModal = document.getElementById('issuesChangePriorityModal');
    const priorityConfirm = document.getElementById('issuesConfirmPriorityChange');

    if (priorityConfirm) {
        priorityConfirm.addEventListener('click', async () => {
            const newPriority = document.getElementById('issuesNewPriority').value;
            await IssuesTicketDetail.changePriority(newPriority);
            IssuesTicketDetail.closeModal(priorityModal);
        });
    }

    // Obsługa zamykania modali
    document.querySelectorAll('.issues-modal-close, .issues-modal-cancel').forEach(btn => {
        btn.addEventListener('click', () => {
            const modal = btn.closest('.issues-modal');
            IssuesTicketDetail.closeModal(modal);
        });
    });

    // Zamknij przy kliknięciu w overlay
    document.querySelectorAll('.issues-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', () => {
            const modal = overlay.closest('.issues-modal');
            IssuesTicketDetail.closeModal(modal);
        });
    });
};

IssuesTicketDetail.showChangeStatusModal = function () {
    const modal = document.getElementById('issuesChangeStatusModal');
    if (modal) modal.style.display = 'flex';
};

IssuesTicketDetail.showChangePriorityModal = function () {
    const modal = document.getElementById('issuesChangePriorityModal');
    if (modal) modal.style.display = 'flex';
};

IssuesTicketDetail.closeModal = function (modal) {
    if (modal) modal.style.display = 'none';
};

// ============================================================================
// AKCJE NA TICKECIE
// ============================================================================

IssuesTicketDetail.changeStatus = async function (newStatus) {
    try {
        await IssuesCommon.changeTicketStatus(IssuesTicketDetail.state.ticketNumber, newStatus);
        IssuesCommon.showToast('success', 'Status zmieniony!');
        location.reload(); // Odśwież stronę
    } catch (error) {
        console.error('Error changing status:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    }
};

IssuesTicketDetail.changePriority = async function (newPriority) {
    try {
        await IssuesCommon.changeTicketPriority(IssuesTicketDetail.state.ticketNumber, newPriority);
        IssuesCommon.showToast('success', 'Priorytet zmieniony!');
        location.reload(); // Odśwież stronę
    } catch (error) {
        console.error('Error changing priority:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    }
};

IssuesTicketDetail.assignToMe = async function () {
    try {
        await IssuesCommon.assignTicket(
            IssuesTicketDetail.state.ticketNumber,
            IssuesTicketDetail.state.currentUserId
        );
        IssuesCommon.showToast('success', 'Ticket przypisany!');
        location.reload(); // Odśwież stronę
    } catch (error) {
        console.error('Error assigning ticket:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    }
};

IssuesTicketDetail.closeTicket = async function () {
    if (!confirm('Czy na pewno chcesz zamknąć ten ticket?')) return;

    try {
        await IssuesCommon.changeTicketStatus(IssuesTicketDetail.state.ticketNumber, 'closed');
        IssuesCommon.showToast('success', 'Ticket zamknięty!');
        location.reload(); // Odśwież stronę
    } catch (error) {
        console.error('Error closing ticket:', error);
        IssuesCommon.showToast('error', 'Błąd', error.message);
    }
};

// ============================================================================
// URUCHOMIENIE PO ZAŁADOWANIU DOM
// ============================================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', IssuesTicketDetail.init);
} else {
    IssuesTicketDetail.init();
}