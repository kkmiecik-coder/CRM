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
        timeline: [],  // ← DODANE (zamiast messages)
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
    IssuesTicketDetail.loadTimeline();  // ← ZMIENIONE z loadMessages()
    IssuesTicketDetail.initReplyForm();
    IssuesTicketDetail.initUpload();
    IssuesTicketDetail.initDropdown();
    IssuesTicketDetail.initModals();

    // Przetłumacz statusy i priorytety przy starcie
    IssuesTicketDetail.translateBadges();  // ← DODANE

    console.log('✅ Ticket Detail zainicjalizowany');
};

// ============================================================================
// ŁADOWANIE TIMELINE (wiadomości + eventy)
// ============================================================================

IssuesTicketDetail.loadTimeline = async function () {
    const container = IssuesTicketDetail.elements.messagesContainer;
    if (!container) return;

    try {
        // Loading state
        container.innerHTML = `
            <div class="issues-loading">
                <i class="fas fa-spinner fa-spin"></i> Ładowanie konwersacji...
            </div>
        `;

        // Pobierz timeline z API
        const response = await IssuesCommon.getTimeline(IssuesTicketDetail.state.ticketNumber);

        IssuesTicketDetail.state.timeline = response.timeline || [];

        // Renderuj timeline
        IssuesTicketDetail.renderTimeline();
    } catch (error) {
        console.error('Error loading timeline:', error);
        container.innerHTML = `
            <div class="issues-error">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Błąd ładowania konwersacji</p>
            </div>
        `;
    }
};

IssuesTicketDetail.renderTimeline = function () {
    const container = IssuesTicketDetail.elements.messagesContainer;
    if (!container) return;

    const timeline = IssuesTicketDetail.state.timeline;

    if (timeline.length === 0) {
        container.innerHTML = `
            <div class="issues-ticket-empty">
                <i class="fas fa-comments"></i>
                <p>Brak wiadomości</p>
            </div>
        `;
        return;
    }

    container.innerHTML = timeline.map(item => {
        if (item.type === 'message') {
            return IssuesTicketDetail.renderMessage(item);
        } else if (item.type === 'event') {
            return IssuesTicketDetail.renderEvent(item);
        }
    }).join('');

    // Scroll na dół
    setTimeout(() => {
        container.scrollTop = container.scrollHeight;
    }, 100);
};

IssuesTicketDetail.renderMessage = function (msg) {
    // Odczytaj dane użytkownika
    const userEmail = msg.user_email || 'Nieznany użytkownik';
    const userName = msg.user_name || userEmail;
    const userRole = msg.user_role || 'user';
    const isAdmin = userRole === 'admin';
    const isInternal = msg.is_internal_note || false;
    const showInternal = isInternal && IssuesTicketDetail.state.currentUserRole === 'admin';

    // Ukryj notatki wewnętrzne dla nie-adminów
    if (isInternal && IssuesTicketDetail.state.currentUserRole !== 'admin') {
        return '';
    }

    // Inicjały użytkownika (fallback gdy brak avatara)
    const initials = userName.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
    const userAvatar = msg.user_avatar;

    // Klasa CSS
    let messageClass = 'issues-message';
    if (isAdmin) messageClass += ' issues-message-admin';
    if (isInternal) messageClass += ' issues-message-internal';

    return `
        <div class="${messageClass}">
            <div class="issues-message-avatar ${isAdmin ? 'issues-message-avatar-admin' : ''}">
                ${userAvatar ?
            `<img src="/static/${userAvatar}" alt="${IssuesCommon.escapeHtml(userName)}" class="issues-avatar-image">`
            : initials
        }
            </div>
            <div class="issues-message-content">
                <div class="issues-message-header">
                    <div class="issues-message-author">
                        <div class="issues-message-name">${IssuesCommon.escapeHtml(userName)}</div>
                        <div class="issues-message-email">${IssuesCommon.escapeHtml(userEmail)}${isAdmin ? ' • Administrator' : ''}</div>
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
                        <div class="issues-attachments-label">
                            <i class="fas fa-paperclip"></i> Załączniki (${msg.attachments.length})
                        </div>
                        <div class="issues-attachments-grid">
                            ${msg.attachments.map(att => {
            const isImage = att.mimetype.startsWith('image/');
            const isPDF = att.mimetype === 'application/pdf';
            const viewUrl = `/issues/api/attachments/${att.id}/view`;
            const downloadUrl = `/issues/api/attachments/${att.id}`;

            if (isImage) {
                return `
                                        <div class="issues-attachment-item issues-attachment-image" 
                                             onclick="IssuesTicketDetail.openLightbox(${att.id}, '${IssuesCommon.escapeHtml(att.original_filename)}', '${viewUrl}')">
                                            <img src="${viewUrl}" alt="${IssuesCommon.escapeHtml(att.original_filename)}" loading="lazy">
                                            <div class="issues-attachment-overlay">
                                                <i class="fas fa-search-plus"></i>
                                            </div>
                                        </div>
                                    `;
            } else {
                const icon = isPDF ? 'fa-file-pdf' : 'fa-file';
                const color = isPDF ? '#d32f2f' : '#757575';
                return `
                                        <a href="${downloadUrl}" 
                                           class="issues-attachment-item issues-attachment-file" 
                                           download="${IssuesCommon.escapeHtml(att.original_filename)}"
                                           title="${IssuesCommon.escapeHtml(att.original_filename)}">
                                            <i class="fas ${icon}" style="color: ${color}; font-size: 48px;"></i>
                                            <div class="issues-attachment-filename">${IssuesCommon.escapeHtml(att.original_filename)}</div>
                                            <div class="issues-attachment-size">${IssuesCommon.formatFileSize(att.filesize)}</div>
                                        </a>
                                    `;
            }
        }).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
};

IssuesTicketDetail.renderEvent = function (event) {
    // Tłumaczenie typów eventów
    const eventTexts = {
        'created': `Ticket utworzony przez ${event.performed_by_name}`,
        'status_changed': `Status zmieniony: ${IssuesCommon.getStatusName(event.old_value)} → ${IssuesCommon.getStatusName(event.new_value)}`,
        'priority_changed': `Priorytet zmieniony: ${IssuesCommon.getPriorityName(event.old_value)} → ${IssuesCommon.getPriorityName(event.new_value)}`,
        'assigned': `Przypisano do: ${event.new_value}`,
        'closed': 'Ticket zamknięty'
    };

    const text = eventTexts[event.event_type] || `Zdarzenie: ${event.event_type}`;

    return `
        <div class="issues-timeline-event">
            <div class="issues-timeline-line"></div>
            <div class="issues-timeline-text">${text}</div>
            <div class="issues-timeline-line"></div>
        </div>
    `;
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
        await IssuesTicketDetail.loadTimeline();

        // Odśwież informacje o tickecie (status, statystyki)
        await IssuesTicketDetail.refreshTicketInfo();

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
// LIGHTBOX
// ============================================================================

IssuesTicketDetail.openLightbox = function (attachmentId, filename, imageUrl) {
    // Usuń istniejący lightbox jeśli jest
    let lightbox = document.getElementById('issuesLightbox');
    if (lightbox) {
        lightbox.remove();
    }

    // Utwórz nowy lightbox
    lightbox = document.createElement('div');
    lightbox.id = 'issuesLightbox';
    lightbox.className = 'issues-lightbox';
    lightbox.innerHTML = `
        <div class="issues-lightbox-overlay" onclick="IssuesTicketDetail.closeLightbox()"></div>
        <div class="issues-lightbox-content">
            <button class="issues-lightbox-close" onclick="IssuesTicketDetail.closeLightbox()">
                <i class="fas fa-times"></i>
            </button>
            <div class="issues-lightbox-header">
                <span class="issues-lightbox-filename">${IssuesCommon.escapeHtml(filename)}</span>
                <a href="/issues/api/attachments/${attachmentId}" 
                   download="${IssuesCommon.escapeHtml(filename)}"
                   class="issues-lightbox-download">
                    <i class="fas fa-download"></i> Pobierz
                </a>
            </div>
            <div class="issues-lightbox-image-container">
                <img src="${imageUrl}" alt="${IssuesCommon.escapeHtml(filename)}" class="issues-lightbox-image">
            </div>
        </div>
    `;

    document.body.appendChild(lightbox);

    // Animacja wejścia
    setTimeout(() => {
        lightbox.classList.add('issues-lightbox-active');
    }, 10);

    // Zamknij na ESC
    document.addEventListener('keydown', IssuesTicketDetail.handleLightboxKeydown);
};

IssuesTicketDetail.closeLightbox = function () {
    const lightbox = document.getElementById('issuesLightbox');
    if (!lightbox) return;

    lightbox.classList.remove('issues-lightbox-active');
    setTimeout(() => {
        lightbox.remove();
    }, 300);

    document.removeEventListener('keydown', IssuesTicketDetail.handleLightboxKeydown);
};

IssuesTicketDetail.handleLightboxKeydown = function (e) {
    if (e.key === 'Escape') {
        IssuesTicketDetail.closeLightbox();
    }
};

// ============================================================================
// ODŚWIEŻANIE INFORMACJI O TICKECIE
// ============================================================================

IssuesTicketDetail.refreshTicketInfo = async function () {
    try {
        // Pobierz aktualne dane ticketu z API
        const response = await IssuesCommon.getTicket(IssuesTicketDetail.state.ticketNumber);
        const ticket = response.ticket;

        // Zaktualizuj badge statusu
        document.querySelectorAll('.issues-badge-status-new, .issues-badge-status-open, .issues-badge-status-in_progress, .issues-badge-status-in-progress, .issues-badge-status-closed, .issues-badge-status-cancelled').forEach(badge => {
            // Usuń wszystkie klasy statusów
            badge.className = badge.className.replace(/issues-badge-status-\w+/g, '');
            // Dodaj nową klasę statusu
            badge.classList.add(`issues-badge-status-${ticket.status}`);
            // Zaktualizuj tekst
            badge.textContent = IssuesCommon.getStatusName(ticket.status);
        });

        // Zaktualizuj licznik wiadomości
        const messagesCountElement = document.querySelector('.issues-stats-item .issues-stats-value');
        if (messagesCountElement && ticket.messages_count) {
            messagesCountElement.textContent = ticket.messages_count;
        }

        // Zaktualizuj licznik załączników
        const attachmentsCountElements = document.querySelectorAll('.issues-stats-item .issues-stats-value');
        if (attachmentsCountElements[1] && ticket.attachments_count !== undefined) {
            attachmentsCountElements[1].textContent = ticket.attachments_count;
        }

        console.log('✅ Informacje o tickecie odświeżone');
    } catch (error) {
        console.error('Błąd odświeżania informacji o tickecie:', error);
        // Nie pokazuj błędu użytkownikowi - to tylko odświeżenie UI
    }
};

// ============================================================================
// TŁUMACZENIE BADGE'ÓW
// ============================================================================

IssuesTicketDetail.translateBadges = function () {
    // Przetłumacz wszystkie statusy
    document.querySelectorAll('[class*="issues-badge-status-"]').forEach(badge => {
        const statusMatch = badge.className.match(/issues-badge-status-(\w+)/);
        if (statusMatch) {
            const status = statusMatch[1].replace('-', '_'); // in-progress -> in_progress
            badge.textContent = IssuesCommon.getStatusName(status);
        }
    });

    // Przetłumacz wszystkie priorytety
    document.querySelectorAll('[class*="issues-badge-priority-"]').forEach(badge => {
        const priorityMatch = badge.className.match(/issues-badge-priority-(\w+)/);
        if (priorityMatch) {
            const priority = priorityMatch[1];
            badge.textContent = IssuesCommon.getPriorityName(priority);
        }
    });
};

// ============================================================================
// URUCHOMIENIE PO ZAŁADOWANIU DOM
// ============================================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', IssuesTicketDetail.init);
} else {
    IssuesTicketDetail.init();
}