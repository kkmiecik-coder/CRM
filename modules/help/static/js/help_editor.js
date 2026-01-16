/**
 * Help Module - Editor JavaScript
 * Obsługa edytora artykułów (toolbar, live preview, autosave, modals)
 */

// ==================== CONSTANTS ====================
const AUTOSAVE_INTERVAL = 60000; // 1 minuta
const AUTOSAVE_KEY_PREFIX = 'help_article_draft_';

// ==================== STATE ====================
let autosaveTimer = null;
let hasUnsavedChanges = false;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    initEditor();
    initToolbar();
    initLivePreview();
    initAutoSave();
    initModals();
    initSlugGenerator();
    initCategoryManagement();
    checkForDraft();
});

// ==================== EDITOR INITIALIZATION ====================
function initEditor() {
    const editorForm = document.getElementById('editorForm');
    if (!editorForm) return;

    // Track changes
    editorForm.addEventListener('input', function() {
        hasUnsavedChanges = true;
    });

    // Cancel button with confirmation
    const cancelBtn = document.getElementById('cancelBtn');
    const cancelFooterBtn = document.getElementById('cancelFooterBtn');
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function(e) {
            if (hasUnsavedChanges) {
                if (!confirm('Masz niezapisane zmiany. Czy na pewno chcesz wyjść?')) {
                    e.preventDefault();
                }
            }
        });
    }

    if (cancelFooterBtn) {
        cancelFooterBtn.addEventListener('click', function() {
            if (hasUnsavedChanges) {
                if (confirm('Masz niezapisane zmiany. Czy na pewno chcesz wyjść?')) {
                    window.location.href = '/help/admin/articles';
                }
            } else {
                window.location.href = '/help/admin/articles';
            }
        });
    }

    // Form submission
    editorForm.addEventListener('submit', function() {
        hasUnsavedChanges = false;
        clearDraft();
    });
}

// ==================== TOOLBAR ====================
function initToolbar() {
    const toolButtons = document.querySelectorAll('.help-editor-tool-btn');
    
    toolButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const action = this.getAttribute('data-action');
            handleToolbarAction(action);
        });
    });
}

function handleToolbarAction(action) {
    const editor = document.getElementById('contentEditor');
    if (!editor) return;

    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selectedText = editor.value.substring(start, end);
    const beforeText = editor.value.substring(0, start);
    const afterText = editor.value.substring(end);

    let newText = '';
    let cursorPos = start;

    switch(action) {
        case 'h1':
            newText = `<h1>${selectedText || 'Nagłówek 1'}</h1>`;
            cursorPos = start + 4;
            break;
        case 'h2':
            newText = `<h2>${selectedText || 'Nagłówek 2'}</h2>`;
            cursorPos = start + 4;
            break;
        case 'h3':
            newText = `<h3>${selectedText || 'Nagłówek 3'}</h3>`;
            cursorPos = start + 4;
            break;
        case 'p':
            newText = `<p>${selectedText || 'Paragraf'}</p>`;
            cursorPos = start + 3;
            break;
        case 'strong':
            newText = `<strong>${selectedText || 'pogrubiony tekst'}</strong>`;
            cursorPos = selectedText ? end + 17 : start + 8;
            break;
        case 'em':
            newText = `<em>${selectedText || 'kursywa'}</em>`;
            cursorPos = selectedText ? end + 9 : start + 4;
            break;
        case 'u':
            newText = `<u>${selectedText || 'podkreślony'}</u>`;
            cursorPos = selectedText ? end + 7 : start + 3;
            break;
        case 'strike':
            newText = `<strike>${selectedText || 'przekreślony'}</strike>`;
            cursorPos = selectedText ? end + 17 : start + 8;
            break;
        case 'ul':
            newText = `<ul>\n  <li>${selectedText || 'Element listy'}</li>\n</ul>`;
            cursorPos = start + 10;
            break;
        case 'ol':
            newText = `<ol>\n  <li>${selectedText || 'Element listy'}</li>\n</ol>`;
            cursorPos = start + 10;
            break;
        case 'link':
            const url = prompt('Wpisz URL:');
            if (url) {
                newText = `<a href="${url}">${selectedText || 'link'}</a>`;
            }
            break;
        case 'image':
            openMediaGallery();
            return;
        case 'video':
            insertVideo();
            return;
        case 'code':
            newText = `<code>${selectedText || 'kod'}</code>`;
            cursorPos = selectedText ? end + 13 : start + 6;
            break;
        case 'blockquote':
            newText = `<blockquote>${selectedText || 'Cytat'}</blockquote>`;
            cursorPos = start + 12;
            break;
        case 'hr':
            newText = '<hr>';
            cursorPos = start + 4;
            break;
        case 'table':
            newText = `<table>\n  <tr>\n    <th>Nagłówek 1</th>\n    <th>Nagłówek 2</th>\n  </tr>\n  <tr>\n    <td>Komórka 1</td>\n    <td>Komórka 2</td>\n  </tr>\n</table>`;
            cursorPos = start + 18;
            break;
        default:
            return;
    }

    editor.value = beforeText + newText + afterText;
    editor.selectionStart = editor.selectionEnd = cursorPos;
    editor.focus();

    updatePreview();
    hasUnsavedChanges = true;
}

function insertVideo() {
    const url = prompt('Wklej URL wideo (YouTube, Vimeo):');
    if (!url) return;

    const editor = document.getElementById('contentEditor');
    let embedCode = '';

    if (url.includes('youtube.com') || url.includes('youtu.be')) {
        const videoId = extractYouTubeId(url);
        embedCode = `<iframe width="560" height="315" src="https://www.youtube.com/embed/${videoId}" frameborder="0" allowfullscreen></iframe>`;
    } else if (url.includes('vimeo.com')) {
        const videoId = url.split('/').pop();
        embedCode = `<iframe src="https://player.vimeo.com/video/${videoId}" width="560" height="315" frameborder="0" allowfullscreen></iframe>`;
    } else {
        alert('Nieobsługiwany format URL. Użyj YouTube lub Vimeo.');
        return;
    }

    const cursorPos = editor.selectionStart;
    const before = editor.value.substring(0, cursorPos);
    const after = editor.value.substring(cursorPos);
    
    editor.value = before + '\n' + embedCode + '\n' + after;
    updatePreview();
    hasUnsavedChanges = true;
}

function extractYouTubeId(url) {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
}

// ==================== LIVE PREVIEW ====================
function initLivePreview() {
    const editor = document.getElementById('contentEditor');
    const preview = document.getElementById('livePreview');
    
    if (!editor || !preview) return;

    editor.addEventListener('input', debounce(updatePreview, 300));
    
    // Initial preview
    updatePreview();
}

function updatePreview() {
    const editor = document.getElementById('contentEditor');
    const preview = document.getElementById('livePreview');
    
    if (!editor || !preview) return;

    const content = editor.value.trim();
    
    if (content) {
        preview.innerHTML = content;
    } else {
        preview.innerHTML = '<p class="help-editor-preview-placeholder">Podgląd pojawi się tutaj...</p>';
    }
}

// ==================== AUTO-SAVE ====================
function initAutoSave() {
    const editor = document.getElementById('contentEditor');
    if (!editor) return;

    autosaveTimer = setInterval(function() {
        if (hasUnsavedChanges) {
            saveDraft();
        }
    }, AUTOSAVE_INTERVAL);
}

function saveDraft() {
    const form = document.getElementById('editorForm');
    if (!form) return;

    const articleId = getArticleIdFromUrl() || 'new';
    const draftKey = AUTOSAVE_KEY_PREFIX + articleId;

    const draft = {
        title: document.getElementById('title')?.value || '',
        category_id: document.getElementById('category')?.value || '',
        slug: document.getElementById('slug')?.value || '',
        content: document.getElementById('contentEditor')?.value || '',
        is_published: document.getElementById('is_published')?.checked || false,
        timestamp: new Date().toISOString()
    };

    localStorage.setItem(draftKey, JSON.stringify(draft));
    showAutoSaveStatus('Zapisano lokalnie');
}

function checkForDraft() {
    const articleId = getArticleIdFromUrl() || 'new';
    const draftKey = AUTOSAVE_KEY_PREFIX + articleId;
    const draft = localStorage.getItem(draftKey);

    if (draft) {
        const confirmed = confirm('Znaleziono niezapisane zmiany. Przywrócić?');
        if (confirmed) {
            restoreDraft(JSON.parse(draft));
        } else {
            clearDraft();
        }
    }
}

function restoreDraft(draft) {
    if (draft.title) document.getElementById('title').value = draft.title;
    if (draft.category_id) document.getElementById('category').value = draft.category_id;
    if (draft.slug) document.getElementById('slug').value = draft.slug;
    if (draft.content) {
        document.getElementById('contentEditor').value = draft.content;
        updatePreview();
    }
    if (draft.is_published !== undefined) {
        document.getElementById('is_published').checked = draft.is_published;
    }
    
    showAutoSaveStatus('Przywrócono z lokalnego zapisu');
}

function clearDraft() {
    const articleId = getArticleIdFromUrl() || 'new';
    const draftKey = AUTOSAVE_KEY_PREFIX + articleId;
    localStorage.removeItem(draftKey);
}

function showAutoSaveStatus(message) {
    const statusEl = document.getElementById('autoSaveStatus');
    const textEl = document.getElementById('autoSaveText');
    
    if (!statusEl) return;

    if (textEl) textEl.textContent = message;
    statusEl.style.display = 'flex';

    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 3000);
}

function getArticleIdFromUrl() {
    const match = window.location.pathname.match(/\/articles\/(\d+)\//);
    return match ? match[1] : null;
}

// ==================== SLUG GENERATOR ====================
function initSlugGenerator() {
    const titleInput = document.getElementById('title');
    const slugInput = document.getElementById('slug');

    if (!titleInput || !slugInput) return;

    titleInput.addEventListener('blur', function() {
        if (!slugInput.value) {
            const slug = generateSlug(this.value);
            slugInput.value = slug;
        }
    });
}

function generateSlug(text) {
    return text
        .toLowerCase()
        .trim()
        .replace(/[^\w\s-]/g, '')
        .replace(/[\s_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/ą/g, 'a')
        .replace(/ć/g, 'c')
        .replace(/ę/g, 'e')
        .replace(/ł/g, 'l')
        .replace(/ń/g, 'n')
        .replace(/ó/g, 'o')
        .replace(/ś/g, 's')
        .replace(/ź|ż/g, 'z');
}

// ==================== MEDIA GALLERY ====================
function openMediaGallery() {
    const modal = document.getElementById('mediaGalleryModal');
    if (modal) {
        modal.style.display = 'flex';
        loadMediaGallery();
    }
}

function closeMediaGallery() {
    const modal = document.getElementById('mediaGalleryModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function loadMediaGallery() {
    // Wywołaj funkcję z help_media_gallery.js (jeśli dostępna)
    if (typeof window.HelpMediaGallery !== 'undefined' && window.HelpMediaGallery.loadGalleryInModal) {
        window.HelpMediaGallery.loadGalleryInModal();
    } else {
        console.error('Help Media Gallery module not loaded!');
    }
}

// Close modal on overlay click
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('help-admin-modal-overlay')) {
        const modal = e.target.closest('.help-admin-modal');
        if (modal) {
            modal.style.display = 'none';
        }
    }
});

// Close modal on close button
const closeMediaBtn = document.getElementById('closeMediaGalleryBtn');
if (closeMediaBtn) {
    closeMediaBtn.addEventListener('click', closeMediaGallery);
}

// ==================== CATEGORY MANAGEMENT ====================
function initCategoryManagement() {
    // Add category button
    const addCategoryBtn = document.getElementById('addCategoryBtn');
    const addFirstCategoryBtn = document.getElementById('addFirstCategoryBtn');
    
    if (addCategoryBtn) {
        addCategoryBtn.addEventListener('click', () => openCategoryModal('create'));
    }
    
    if (addFirstCategoryBtn) {
        addFirstCategoryBtn.addEventListener('click', () => openCategoryModal('create'));
    }

    // Edit category buttons
    const editButtons = document.querySelectorAll('.help-category-admin-btn-edit');
    editButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const categoryId = this.getAttribute('data-category-id');
            const categoryName = this.getAttribute('data-category-name');
            const categoryIcon = this.getAttribute('data-category-icon');
            const categoryOrder = this.getAttribute('data-category-order');
            const categoryVisible = this.getAttribute('data-category-visible') === 'true';
            
            openCategoryModal('edit', {
                id: categoryId,
                name: categoryName,
                icon: categoryIcon,
                order: categoryOrder,
                visible: categoryVisible
            });
        });
    });

    // Delete category buttons
    const deleteButtons = document.querySelectorAll('.help-category-admin-btn-delete');
    deleteButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const categoryId = this.getAttribute('data-category-id');
            const categoryName = this.getAttribute('data-category-name');
            const articlesCount = parseInt(this.getAttribute('data-articles-count'));
            
            openDeleteCategoryModal(categoryId, categoryName, articlesCount);
        });
    });
}

function openCategoryModal(mode, data = null) {
    const modal = document.getElementById('categoryModal');
    const form = document.getElementById('categoryForm');
    const titleText = document.getElementById('categoryModalTitleText');
    const submitText = document.getElementById('categorySubmitBtnText');

    if (!modal || !form) return;

    if (mode === 'create') {
        titleText.textContent = 'Nowa kategoria';
        submitText.textContent = 'Utwórz kategorię';
        form.action = '/help/admin/categories/create';
        form.reset();
    } else {
        titleText.textContent = 'Edytuj kategorię';
        submitText.textContent = 'Zapisz zmiany';
        form.action = `/help/admin/categories/${data.id}/edit`;
        
        document.getElementById('categoryName').value = data.name;
        document.getElementById('categoryIcon').value = data.icon;
        document.getElementById('categoryOrder').value = data.order;
        document.getElementById('categoryVisible').checked = data.visible;
    }

    modal.style.display = 'flex';
}

function openDeleteCategoryModal(categoryId, categoryName, articlesCount) {
    const modal = document.getElementById('deleteCategoryModal');
    const form = document.getElementById('deleteCategoryForm');
    const nameEl = document.getElementById('deleteCategoryName');
    const moveSection = document.getElementById('moveCategorySection');
    const articlesCountEl = document.getElementById('articlesCount');

    if (!modal || !form) return;

    nameEl.textContent = categoryName;
    form.action = `/help/admin/categories/${categoryId}/delete`;

    if (articlesCount > 0) {
        moveSection.style.display = 'block';
        articlesCountEl.textContent = articlesCount;
        // Load other categories for dropdown - simplified version
    } else {
        moveSection.style.display = 'none';
    }

    modal.style.display = 'flex';
}

// Modal close buttons
const closeCategoryModalBtn = document.getElementById('closeCategoryModalBtn');
const cancelCategoryBtn = document.getElementById('cancelCategoryBtn');

if (closeCategoryModalBtn) {
    closeCategoryModalBtn.addEventListener('click', () => {
        document.getElementById('categoryModal').style.display = 'none';
    });
}

if (cancelCategoryBtn) {
    cancelCategoryBtn.addEventListener('click', () => {
        document.getElementById('categoryModal').style.display = 'none';
    });
}

// ==================== MODALS ====================
function initModals() {
    // Close modals on ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('.help-admin-modal').forEach(modal => {
                modal.style.display = 'none';
            });
        }
    });
}

// ==================== UTILITY FUNCTIONS ====================
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

// Cleanup on page unload
window.addEventListener('beforeunload', function(e) {
    if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = '';
    }
    
    if (autosaveTimer) {
        clearInterval(autosaveTimer);
    }
});