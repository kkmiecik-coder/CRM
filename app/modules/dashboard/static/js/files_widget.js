/**
 * Files Widget - Pliki do pobrania
 * Obsługa widgetu plików na dashboardzie
 */

(function() {
    'use strict';

    // Elementy DOM
    const filesList = document.getElementById('files-list');
    const filesEmpty = document.getElementById('files-empty');
    const filesAddBtn = document.getElementById('files-add-btn');
    const filesModalOverlay = document.getElementById('files-modal-overlay');
    const filesModalClose = document.getElementById('files-modal-close');
    const filesCancelBtn = document.getElementById('files-cancel-btn');
    const filesUploadForm = document.getElementById('files-upload-form');
    const filesSubmitBtn = document.getElementById('files-submit-btn');

    // Dropzone elements
    const fileDropzone = document.getElementById('file-dropzone');
    const fileInput = document.getElementById('file-input');
    const dropzoneContent = document.getElementById('dropzone-content');
    const dropzoneSelected = document.getElementById('dropzone-selected');
    const dropzoneProgress = document.getElementById('dropzone-progress');
    const dropzoneSuccess = document.getElementById('dropzone-success');
    const selectedFilename = document.getElementById('selected-filename');
    const selectedFilesize = document.getElementById('selected-filesize');
    const removeFileBtn = document.getElementById('remove-file');
    const progressFill = document.getElementById('progress-fill');
    const progressPercent = document.getElementById('progress-percent');
    const progressFilename = document.getElementById('progress-filename');
    const progressStatus = document.getElementById('progress-status');

    // State
    let selectedFile = null;
    let isUploading = false;
    let isAdmin = !!filesAddBtn; // Jeśli przycisk istnieje, to jest admin

    /**
     * Inicjalizacja widgetu
     */
    function init() {
        loadFiles();
        setupEventListeners();
    }

    /**
     * Konfiguracja event listenerów
     */
    function setupEventListeners() {
        // Modal - otwieranie/zamykanie
        if (filesAddBtn) {
            filesAddBtn.addEventListener('click', openModal);
        }
        if (filesModalClose) {
            filesModalClose.addEventListener('click', closeModal);
        }
        if (filesCancelBtn) {
            filesCancelBtn.addEventListener('click', closeModal);
        }
        if (filesModalOverlay) {
            filesModalOverlay.addEventListener('click', (e) => {
                if (e.target === filesModalOverlay) {
                    closeModal();
                }
            });
        }

        // Dropzone - kliknięcie
        if (fileDropzone) {
            fileDropzone.addEventListener('click', () => {
                if (!isUploading) {
                    fileInput.click();
                }
            });

            // Drag & Drop
            fileDropzone.addEventListener('dragover', handleDragOver);
            fileDropzone.addEventListener('dragleave', handleDragLeave);
            fileDropzone.addEventListener('drop', handleDrop);
        }

        // Input file change
        if (fileInput) {
            fileInput.addEventListener('change', handleFileSelect);
        }

        // Usunięcie wybranego pliku
        if (removeFileBtn) {
            removeFileBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                clearSelectedFile();
            });
        }

        // Formularz - submit
        if (filesUploadForm) {
            filesUploadForm.addEventListener('submit', handleFormSubmit);
        }

        // ESC key to close modal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && filesModalOverlay && filesModalOverlay.classList.contains('active')) {
                closeModal();
            }
        });
    }

    /**
     * Ładowanie listy plików
     */
    async function loadFiles() {
        try {
            const response = await fetch('/dashboard/api/files');
            const data = await response.json();

            if (data.success) {
                renderFiles(data.files);
            } else {
                showError('Błąd ładowania plików');
            }
        } catch (error) {
            console.error('[FilesWidget] Błąd:', error);
            showError('Błąd połączenia z serwerem');
        }
    }

    /**
     * Renderowanie listy plików
     */
    function renderFiles(files) {
        if (!filesList) return;

        if (files.length === 0) {
            filesList.style.display = 'none';
            if (filesEmpty) {
                filesEmpty.style.display = 'block';
            }
            return;
        }

        filesList.style.display = 'flex';
        if (filesEmpty) {
            filesEmpty.style.display = 'none';
        }

        filesList.innerHTML = files.map(file => createFileItemHTML(file)).join('');

        // Dodaj event listenery do przycisków
        filesList.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const fileId = btn.dataset.fileId;
                downloadFile(fileId);
            });
        });

        if (isAdmin) {
            filesList.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const fileId = btn.dataset.fileId;
                    const fileName = btn.dataset.fileName;
                    confirmDeleteFile(fileId, fileName);
                });
            });
        }
    }

    /**
     * Tworzenie HTML dla pojedynczego pliku
     */
    function createFileItemHTML(file) {
        const deleteButton = isAdmin
            ? `<button class="file-action-btn delete-btn" data-file-id="${file.id}" data-file-name="${escapeHtml(file.display_name)}" title="Usuń plik">🗑️</button>`
            : '';

        return `
            <div class="file-item" data-file-id="${file.id}">
                <div class="file-icon">${file.icon}</div>
                <div class="file-info">
                    <div class="file-name" title="${escapeHtml(file.display_name)}">${escapeHtml(file.display_name)}</div>
                    <div class="file-meta">
                        <span>${file.extension}</span>
                        <span>•</span>
                        <span>${file.filesize_formatted}</span>
                        <span>•</span>
                        <span>Dodano: ${file.uploaded_at}</span>
                    </div>
                </div>
                <div class="file-actions">
                    <button class="file-action-btn download-btn" data-file-id="${file.id}" title="Pobierz plik">⬇️</button>
                    ${deleteButton}
                </div>
            </div>
        `;
    }

    /**
     * Pobieranie pliku
     */
    function downloadFile(fileId) {
        window.location.href = `/dashboard/api/files/${fileId}/download`;
    }

    /**
     * Potwierdzenie usunięcia pliku
     */
    function confirmDeleteFile(fileId, fileName) {
        if (confirm(`Czy na pewno chcesz usunąć plik "${fileName}"?`)) {
            deleteFile(fileId);
        }
    }

    /**
     * Usuwanie pliku
     */
    async function deleteFile(fileId) {
        try {
            const response = await fetch(`/dashboard/api/files/${fileId}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            if (data.success) {
                showNotification(data.message, 'success');
                loadFiles();
            } else {
                showNotification(data.error || 'Błąd usuwania pliku', 'error');
            }
        } catch (error) {
            console.error('[FilesWidget] Błąd usuwania:', error);
            showNotification('Błąd połączenia z serwerem', 'error');
        }
    }

    /**
     * Otwieranie modala
     */
    function openModal() {
        if (filesModalOverlay) {
            filesModalOverlay.classList.add('active');
            document.body.style.overflow = 'hidden';
            resetForm();
        }
    }

    /**
     * Zamykanie modala
     */
    function closeModal() {
        if (filesModalOverlay && !isUploading) {
            filesModalOverlay.classList.remove('active');
            document.body.style.overflow = '';
            resetForm();
        }
    }

    /**
     * Reset formularza
     */
    function resetForm() {
        if (filesUploadForm) {
            filesUploadForm.reset();
        }
        clearSelectedFile();
        showDropzoneState('content');
    }

    /**
     * Obsługa drag over
     */
    function handleDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        if (!isUploading) {
            fileDropzone.classList.add('dragover');
        }
    }

    /**
     * Obsługa drag leave
     */
    function handleDragLeave(e) {
        e.preventDefault();
        e.stopPropagation();
        fileDropzone.classList.remove('dragover');
    }

    /**
     * Obsługa drop
     */
    function handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        fileDropzone.classList.remove('dragover');

        if (isUploading) return;

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    }

    /**
     * Obsługa wyboru pliku
     */
    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    }

    /**
     * Przetwarzanie wybranego pliku
     */
    function handleFile(file) {
        // Walidacja rozmiaru (100 MB)
        const maxSize = 100 * 1024 * 1024;
        if (file.size > maxSize) {
            showNotification('Plik jest za duży. Maksymalny rozmiar: 100 MB', 'error');
            return;
        }

        // Walidacja rozszerzenia
        const allowedExtensions = [
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
            'txt', 'csv', 'zip', 'rar', '7z',
            'jpg', 'jpeg', 'png', 'gif', 'svg', 'webp'
        ];
        const extension = file.name.split('.').pop().toLowerCase();
        if (!allowedExtensions.includes(extension)) {
            showNotification(`Niedozwolony typ pliku: .${extension}`, 'error');
            return;
        }

        selectedFile = file;
        showSelectedFile(file);
    }

    /**
     * Wyświetlenie wybranego pliku
     */
    function showSelectedFile(file) {
        if (selectedFilename) {
            selectedFilename.textContent = file.name;
        }
        if (selectedFilesize) {
            selectedFilesize.textContent = formatFileSize(file.size);
        }
        showDropzoneState('selected');
    }

    /**
     * Czyszczenie wybranego pliku
     */
    function clearSelectedFile() {
        selectedFile = null;
        if (fileInput) {
            fileInput.value = '';
        }
        showDropzoneState('content');
    }

    /**
     * Zmiana stanu dropzone
     */
    function showDropzoneState(state) {
        if (dropzoneContent) dropzoneContent.style.display = state === 'content' ? 'block' : 'none';
        if (dropzoneSelected) dropzoneSelected.style.display = state === 'selected' ? 'flex' : 'none';
        if (dropzoneProgress) dropzoneProgress.style.display = state === 'progress' ? 'block' : 'none';
        if (dropzoneSuccess) dropzoneSuccess.style.display = state === 'success' ? 'block' : 'none';
    }

    /**
     * Obsługa wysyłania formularza
     */
    async function handleFormSubmit(e) {
        e.preventDefault();

        if (isUploading) return;

        const displayName = document.getElementById('display-name').value.trim();

        if (!displayName) {
            showNotification('Podaj nazwę wyświetlaną', 'error');
            return;
        }

        if (!selectedFile) {
            showNotification('Wybierz plik do przesłania', 'error');
            return;
        }

        await uploadFile(displayName, selectedFile);
    }

    /**
     * Upload pliku
     */
    async function uploadFile(displayName, file) {
        isUploading = true;
        setSubmitButtonLoading(true);
        showDropzoneState('progress');

        if (progressFilename) {
            progressFilename.textContent = file.name;
        }

        const formData = new FormData();
        formData.append('display_name', displayName);
        formData.append('file', file);

        try {
            const xhr = new XMLHttpRequest();

            // Progress tracking
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    updateProgress(percent, e.loaded, e.total);
                }
            });

            // Promise wrapper
            const response = await new Promise((resolve, reject) => {
                xhr.onload = () => {
                    console.log('[FilesWidget] XHR onload, status:', xhr.status);
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try {
                            resolve(JSON.parse(xhr.responseText));
                        } catch (e) {
                            console.error('[FilesWidget] JSON parse error:', e);
                            reject({ error: 'Nieprawidłowa odpowiedź serwera' });
                        }
                    } else if (xhr.status === 413) {
                        reject({ error: 'Plik jest za duży. Maksymalny rozmiar: 100 MB' });
                    } else {
                        try {
                            reject(JSON.parse(xhr.responseText));
                        } catch {
                            reject({ error: `Błąd serwera (${xhr.status})` });
                        }
                    }
                };
                xhr.onerror = () => {
                    console.error('[FilesWidget] XHR onerror');
                    reject({ error: 'Błąd połączenia z serwerem' });
                };
                xhr.ontimeout = () => {
                    console.error('[FilesWidget] XHR timeout');
                    reject({ error: 'Przekroczono limit czasu. Spróbuj ponownie.' });
                };
                xhr.onabort = () => {
                    console.error('[FilesWidget] XHR aborted');
                    reject({ error: 'Upload został przerwany' });
                };

                xhr.timeout = 300000; // 5 minut timeout dla dużych plików
                xhr.open('POST', '/dashboard/api/files');
                xhr.send(formData);
            });

            if (response.success) {
                showDropzoneState('success');
                showNotification('Plik został dodany pomyślnie', 'success');

                // Zamknij modal po chwili i odśwież listę
                setTimeout(() => {
                    closeModal();
                    loadFiles();
                }, 1500);
            } else {
                throw response;
            }

        } catch (error) {
            console.error('[FilesWidget] Błąd uploadu:', error);
            showNotification(error.error || 'Błąd podczas wysyłania pliku', 'error');
            showDropzoneState('selected');
        } finally {
            isUploading = false;
            setSubmitButtonLoading(false);
        }
    }

    /**
     * Aktualizacja paska postępu
     */
    function updateProgress(percent, loaded, total) {
        if (progressFill) {
            progressFill.style.width = `${percent}%`;
        }
        if (progressPercent) {
            progressPercent.textContent = `${percent}%`;
        }
        if (progressStatus) {
            if (percent >= 100) {
                // Plik przesłany, teraz serwer go zapisuje
                progressStatus.textContent = 'Zapisywanie na serwerze...';
            } else {
                progressStatus.textContent = `Wysyłanie... ${formatFileSize(loaded)} / ${formatFileSize(total)}`;
            }
        }
    }

    /**
     * Ustawienie stanu ładowania przycisku
     */
    function setSubmitButtonLoading(loading) {
        if (!filesSubmitBtn) return;

        const btnText = filesSubmitBtn.querySelector('.btn-text');
        const btnLoading = filesSubmitBtn.querySelector('.btn-loading');

        if (loading) {
            filesSubmitBtn.disabled = true;
            if (btnText) btnText.style.display = 'none';
            if (btnLoading) btnLoading.style.display = 'flex';
        } else {
            filesSubmitBtn.disabled = false;
            if (btnText) btnText.style.display = 'inline';
            if (btnLoading) btnLoading.style.display = 'none';
        }
    }

    /**
     * Formatowanie rozmiaru pliku
     */
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    /**
     * Escape HTML
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Wyświetlenie błędu w liście
     */
    function showError(message) {
        if (filesList) {
            filesList.innerHTML = `
                <div class="files-error" style="text-align: center; padding: 2rem; color: var(--error);">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">⚠️</div>
                    <div>${message}</div>
                </div>
            `;
        }
    }

    /**
     * Wyświetlenie notyfikacji
     */
    function showNotification(message, type = 'info') {
        // Sprawdź czy istnieje globalna funkcja notyfikacji
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else {
            // Fallback - prosta notyfikacja
            const notification = document.createElement('div');
            notification.className = `files-notification files-notification-${type}`;
            notification.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                padding: 1rem 1.5rem;
                border-radius: 8px;
                background: ${type === 'success' ? '#22c55e' : type === 'error' ? '#ef4444' : '#3b82f6'};
                color: white;
                font-weight: 500;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                z-index: 10001;
                animation: slideIn 0.3s ease;
            `;
            notification.textContent = message;
            document.body.appendChild(notification);

            setTimeout(() => {
                notification.style.animation = 'slideOut 0.3s ease';
                setTimeout(() => notification.remove(), 300);
            }, 3000);
        }
    }

    // Dodaj style animacji dla notyfikacji
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
    `;
    document.head.appendChild(style);

    // Inicjalizacja po załadowaniu DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
