/**
 * Help Module - Media Gallery JavaScript
 * Obsługa galerii mediów (upload, drag&drop, preview, delete)
 */

// ==================== CONSTANTS ====================
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml'];
const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp', '.svg'];

// ==================== STATE ====================
let uploadQueue = [];
let isUploading = false;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    initUploadArea();
    initFileInput();
    initMediaGrid();
    initMediaPreview();
    initMediaDelete();
    initMediaSort();
});

// ==================== UPLOAD AREA ====================
function initUploadArea() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    if (!uploadArea || !fileInput) return;
    
    // Click to select files
    uploadArea.addEventListener('click', function() {
        fileInput.click();
    });
    
    // Drag and drop
    uploadArea.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.add('help-media-drag-over');
    });
    
    uploadArea.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.remove('help-media-drag-over');
    });
    
    uploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        this.classList.remove('help-media-drag-over');
        
        const files = e.dataTransfer.files;
        handleFiles(files);
    });
}

// ==================== FILE INPUT ====================
function initFileInput() {
    const fileInput = document.getElementById('fileInput');
    const selectFilesBtn = document.getElementById('selectFilesBtn');
    const uploadMediaBtn = document.getElementById('uploadMediaBtn');
    
    if (!fileInput) return;
    
    // Select files button
    if (selectFilesBtn) {
        selectFilesBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            fileInput.click();
        });
    }
    
    // Upload button (header)
    if (uploadMediaBtn) {
        uploadMediaBtn.addEventListener('click', function() {
            fileInput.click();
        });
    }
    
    // File input change
    fileInput.addEventListener('change', function() {
        handleFiles(this.files);
    });
}

// ==================== FILE HANDLING ====================
function handleFiles(files) {
    if (!files || files.length === 0) return;
    
    const validFiles = [];
    const errors = [];
    
    Array.from(files).forEach(file => {
        const validation = validateFile(file);
        
        if (validation.valid) {
            validFiles.push(file);
        } else {
            errors.push({
                file: file.name,
                error: validation.error
            });
        }
    });
    
    // Show errors
    if (errors.length > 0) {
        showUploadErrors(errors);
    }
    
    // Upload valid files
    if (validFiles.length > 0) {
        uploadFiles(validFiles);
    }
}

function validateFile(file) {
    // Check file type
    if (!ALLOWED_TYPES.includes(file.type)) {
        return {
            valid: false,
            error: 'Nieprawidłowy format pliku. Dozwolone: JPG, PNG, WebP, SVG'
        };
    }
    
    // Check file size
    if (file.size > MAX_FILE_SIZE) {
        return {
            valid: false,
            error: `Plik jest za duży. Maksymalny rozmiar: ${formatFileSize(MAX_FILE_SIZE)}`
        };
    }
    
    // Check file extension
    const extension = '.' + file.name.split('.').pop().toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(extension)) {
        return {
            valid: false,
            error: 'Nieprawidłowe rozszerzenie pliku'
        };
    }
    
    return { valid: true };
}

function showUploadErrors(errors) {
    let message = 'Następujące pliki nie mogły zostać przesłane:\n\n';
    
    errors.forEach(item => {
        message += `• ${item.file}: ${item.error}\n`;
    });
    
    alert(message);
}

// ==================== FILE UPLOAD ====================
function uploadFiles(files) {
    if (isUploading) {
        alert('Trwa już przesyłanie plików. Poczekaj na zakończenie.');
        return;
    }
    
    isUploading = true;
    uploadQueue = Array.from(files);
    
    showUploadToast('Przesyłanie plików...', 'loading');
    
    uploadNextFile();
}

function uploadNextFile() {
    if (uploadQueue.length === 0) {
        isUploading = false;
        showUploadToast('Wszystkie pliki zostały przesłane!', 'success');
        
        // Reload page after successful upload
        setTimeout(() => {
            location.reload();
        }, 1500);
        return;
    }
    
    const file = uploadQueue.shift();
    
    const formData = new FormData();
    formData.append('file', file);
    
    fetch('/help/admin/media/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('File uploaded:', data.filename);
            uploadNextFile();
        } else {
            throw new Error(data.error || 'Upload failed');
        }
    })
    .catch(error => {
        console.error('Upload error:', error);
        showUploadToast(`Błąd: ${error.message}`, 'error');
        isUploading = false;
    });
}

function showUploadToast(message, type) {
    const toast = document.getElementById('uploadToast');
    if (!toast) return;
    
    const icon = toast.querySelector('.help-upload-toast-icon');
    const text = toast.querySelector('.help-upload-toast-text');
    
    if (icon) {
        icon.className = 'help-upload-toast-icon fas ';
        if (type === 'loading') {
            icon.className += 'fa-spinner fa-spin';
        } else if (type === 'success') {
            icon.className += 'fa-check-circle';
        } else if (type === 'error') {
            icon.className += 'fa-exclamation-circle';
        }
    }
    
    if (text) {
        text.textContent = message;
    }
    
    toast.style.display = 'flex';
    
    if (type !== 'loading') {
        setTimeout(() => {
            toast.style.display = 'none';
        }, 3000);
    }
}

// ==================== MEDIA GRID ====================
function initMediaGrid() {
    const mediaItems = document.querySelectorAll('.help-media-item');
    
    mediaItems.forEach(item => {
        // Lazy loading images
        const img = item.querySelector('img[loading="lazy"]');
        if (img && 'IntersectionObserver' in window) {
            const observer = new IntersectionObserver(entries => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src || img.src;
                        observer.unobserve(img);
                    }
                });
            });
            
            observer.observe(img);
        }
    });
}

// ==================== MEDIA PREVIEW ====================
function initMediaPreview() {
    const viewButtons = document.querySelectorAll('.help-media-btn-view');
    const modal = document.getElementById('imagePreviewModal');
    const previewImg = document.getElementById('previewImage');
    const previewFilename = document.getElementById('previewFilename');
    const closeBtn = document.getElementById('closePreviewBtn');
    const copyBtn = document.getElementById('previewCopyBtn');
    
    viewButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const url = this.getAttribute('data-url');
            const filename = this.getAttribute('data-filename');
            
            if (modal && previewImg && previewFilename) {
                previewImg.src = url;
                previewFilename.textContent = filename;
                
                if (copyBtn) {
                    copyBtn.setAttribute('data-url', url);
                }
                
                modal.style.display = 'flex';
            }
        });
    });
    
    // Close button
    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            if (modal) {
                modal.style.display = 'none';
            }
        });
    }
    
    // Close on overlay click
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === this || e.target.classList.contains('help-admin-modal-overlay')) {
                this.style.display = 'none';
            }
        });
    }
    
    // Close on ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && modal.style.display === 'flex') {
            modal.style.display = 'none';
        }
    });
    
    // Copy URL button
    if (copyBtn) {
        copyBtn.addEventListener('click', function() {
            const url = this.getAttribute('data-url');
            copyToClipboard(url);
        });
    }
}

// ==================== COPY TO CLIPBOARD ====================
function initCopyButtons() {
    const copyButtons = document.querySelectorAll('.help-media-btn-copy');
    
    copyButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const url = this.getAttribute('data-url');
            copyToClipboard(url);
        });
    });
}

initCopyButtons();

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showCopyFeedback('Skopiowano URL do schowka!');
    }).catch(err => {
        console.error('Failed to copy:', err);
        
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        
        try {
            document.execCommand('copy');
            showCopyFeedback('Skopiowano URL do schowka!');
        } catch (err) {
            showCopyFeedback('Nie udało się skopiować URL', 'error');
        }
        
        document.body.removeChild(textarea);
    });
}

function showCopyFeedback(message, type = 'success') {
    const feedback = document.createElement('div');
    feedback.className = 'help-copy-feedback';
    feedback.innerHTML = `<i class="fas fa-${type === 'success' ? 'check' : 'times'}-circle"></i> ${message}`;
    
    document.body.appendChild(feedback);
    
    setTimeout(() => {
        feedback.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        feedback.classList.remove('show');
        setTimeout(() => {
            feedback.remove();
        }, 300);
    }, 2000);
}

// ==================== MEDIA DELETE ====================
function initMediaDelete() {
    const deleteButtons = document.querySelectorAll('.help-media-btn-delete');
    const modal = document.getElementById('deleteMediaModal');
    const form = document.getElementById('deleteMediaForm');
    const filenameEl = document.getElementById('deleteMediaFilename');
    const closeBtn = document.getElementById('closeDeleteMediaBtn');
    const cancelBtn = document.getElementById('cancelDeleteMediaBtn');
    
    deleteButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const filename = this.getAttribute('data-filename');
            
            if (modal && form && filenameEl) {
                filenameEl.textContent = filename;
                form.action = `/help/admin/media/${encodeURIComponent(filename)}/delete`;
                modal.style.display = 'flex';
            }
        });
    });
    
    // Close buttons
    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            if (modal) modal.style.display = 'none';
        });
    }
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            if (modal) modal.style.display = 'none';
        });
    }
    
    // Close on overlay
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === this || e.target.classList.contains('help-admin-modal-overlay')) {
                this.style.display = 'none';
            }
        });
    }
}

// ==================== MEDIA SORT ====================
function initMediaSort() {
    const sortSelect = document.getElementById('sortBy');
    
    if (!sortSelect) return;
    
    sortSelect.addEventListener('change', function() {
        const sortBy = this.value;
        sortMediaGrid(sortBy);
    });
}

function sortMediaGrid(sortBy) {
    const grid = document.getElementById('mediaGrid');
    if (!grid) return;
    
    const items = Array.from(grid.querySelectorAll('.help-media-item'));
    
    items.sort((a, b) => {
        switch(sortBy) {
            case 'newest':
                return parseFloat(b.getAttribute('data-date')) - parseFloat(a.getAttribute('data-date'));
            
            case 'oldest':
                return parseFloat(a.getAttribute('data-date')) - parseFloat(b.getAttribute('data-date'));
            
            case 'largest':
                return parseInt(b.getAttribute('data-size')) - parseInt(a.getAttribute('data-size'));
            
            case 'smallest':
                return parseInt(a.getAttribute('data-size')) - parseInt(b.getAttribute('data-size'));
            
            case 'name':
                const nameA = a.getAttribute('data-filename').toLowerCase();
                const nameB = b.getAttribute('data-filename').toLowerCase();
                return nameA.localeCompare(nameB);
            
            default:
                return 0;
        }
    });
    
    // Reorder DOM
    items.forEach(item => {
        grid.appendChild(item);
    });
}

// ==================== MEDIA SELECTION ====================
function initMediaSelection() {
    const mediaItems = document.querySelectorAll('.help-media-item');
    let selectedItems = [];
    
    mediaItems.forEach(item => {
        item.addEventListener('click', function(e) {
            // Skip if clicking on button
            if (e.target.closest('button')) return;
            
            // Ctrl/Cmd + Click = multiple selection
            if (e.ctrlKey || e.metaKey) {
                this.classList.toggle('selected');
                
                if (this.classList.contains('selected')) {
                    selectedItems.push(this);
                } else {
                    selectedItems = selectedItems.filter(i => i !== this);
                }
            } else {
                // Single selection
                mediaItems.forEach(i => i.classList.remove('selected'));
                this.classList.add('selected');
                selectedItems = [this];
            }
            
            updateSelectionToolbar(selectedItems.length);
        });
    });
}

function updateSelectionToolbar(count) {
    let toolbar = document.getElementById('selectionToolbar');
    
    if (count > 0) {
        if (!toolbar) {
            toolbar = createSelectionToolbar();
            document.body.appendChild(toolbar);
        }
        
        toolbar.querySelector('.selection-count').textContent = count;
        toolbar.style.display = 'flex';
    } else {
        if (toolbar) {
            toolbar.style.display = 'none';
        }
    }
}

function createSelectionToolbar() {
    const toolbar = document.createElement('div');
    toolbar.id = 'selectionToolbar';
    toolbar.className = 'help-media-selection-toolbar';
    toolbar.innerHTML = `
        <span class="selection-count">0</span> wybranych plików
        <button class="help-media-toolbar-btn" onclick="deleteSelectedMedia()">
            <i class="fas fa-trash"></i> Usuń
        </button>
        <button class="help-media-toolbar-btn" onclick="clearSelection()">
            <i class="fas fa-times"></i> Anuluj
        </button>
    `;
    return toolbar;
}

window.deleteSelectedMedia = function() {
    if (confirm('Czy na pewno chcesz usunąć wybrane pliki?')) {
        console.log('Deleting selected media...');
        // Implementation needed
    }
};

window.clearSelection = function() {
    document.querySelectorAll('.help-media-item.selected').forEach(item => {
        item.classList.remove('selected');
    });
    updateSelectionToolbar(0);
};

initMediaSelection();

// ==================== INSERT IMAGE TO EDITOR ====================
function insertImageToEditor(url) {
    const editor = window.opener?.document.getElementById('contentEditor');
    
    if (editor) {
        const cursorPos = editor.selectionStart;
        const before = editor.value.substring(0, cursorPos);
        const after = editor.value.substring(cursorPos);
        
        const imgTag = `<img src="${url}" alt="Image" class="help-article-image">`;
        
        editor.value = before + '\n' + imgTag + '\n' + after;
        
        // Trigger preview update
        if (window.opener.updatePreview) {
            window.opener.updatePreview();
        }
        
        window.close();
    } else {
        // Copy URL if not opened from editor
        copyToClipboard(url);
    }
}

// Add insert button to media items (when opened from editor)
if (window.opener) {
    const mediaItems = document.querySelectorAll('.help-media-item');
    
    mediaItems.forEach(item => {
        const overlay = item.querySelector('.help-media-overlay');
        if (overlay) {
            const insertBtn = document.createElement('button');
            insertBtn.className = 'help-media-overlay-btn help-media-btn-insert';
            insertBtn.innerHTML = '<i class="fas fa-plus"></i>';
            insertBtn.title = 'Wstaw do edytora';
            
            const url = item.querySelector('.help-media-btn-view')?.getAttribute('data-url');
            if (url) {
                insertBtn.onclick = function(e) {
                    e.stopPropagation();
                    insertImageToEditor(url);
                };
                
                overlay.appendChild(insertBtn);
            }
        }
    });
}

// ==================== UTILITY FUNCTIONS ====================
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ==================== PASTE UPLOAD ====================
document.addEventListener('paste', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        return;
    }
    
    const items = e.clipboardData?.items;
    if (!items) return;
    
    const files = [];
    
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
            const file = items[i].getAsFile();
            if (file) {
                files.push(file);
            }
        }
    }
    
    if (files.length > 0) {
        e.preventDefault();
        handleFiles(files);
    }
});

console.log('Help Media Gallery initialized');