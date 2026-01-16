/**
 * Help Module - Search JavaScript
 * Obsługa wyszukiwarki artykułów (walidacja, highlight, historia)
 */

// ==================== CONSTANTS ====================
const MIN_SEARCH_LENGTH = 2;
const MAX_SEARCH_LENGTH = 100;
const SEARCH_HISTORY_KEY = 'help_search_history';
const MAX_HISTORY_ITEMS = 10;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    initSearchForm();
    initSearchInput();
    initSearchHistory();
    initSearchSuggestions();
    highlightSearchResults();
});

// ==================== SEARCH FORM ====================
function initSearchForm() {
    const searchForms = document.querySelectorAll('.help-search-form, .help-main-search-form');
    
    searchForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const input = this.querySelector('input[name="q"]');
            
            if (!input) return;
            
            const query = input.value.trim();
            
            // Validation
            if (query.length < MIN_SEARCH_LENGTH) {
                e.preventDefault();
                showSearchError(input, `Wpisz co najmniej ${MIN_SEARCH_LENGTH} znaki`);
                return;
            }
            
            if (query.length > MAX_SEARCH_LENGTH) {
                e.preventDefault();
                showSearchError(input, `Zapytanie jest za długie (max ${MAX_SEARCH_LENGTH} znaków)`);
                return;
            }
            
            // Save to history
            saveSearchQuery(query);
            
            // Clear error if exists
            clearSearchError(input);
        });
    });
}

// ==================== SEARCH INPUT ====================
function initSearchInput() {
    const searchInputs = document.querySelectorAll('input[name="q"]');
    
    searchInputs.forEach(input => {
        // Clear button
        addClearButton(input);
        
        // Character counter
        addCharacterCounter(input);
        
        // Auto-focus on page load (search results page)
        if (input.hasAttribute('autofocus')) {
            input.focus();
            input.select();
        }
        
        // Keyboard shortcuts
        input.addEventListener('keydown', function(e) {
            // ESC - clear input
            if (e.key === 'Escape') {
                this.value = '';
                this.blur();
                closeSuggestions();
            }
            
            // Arrow down - focus suggestions
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                focusFirstSuggestion();
            }
        });
        
        // Input event - show suggestions
        input.addEventListener('input', debounce(function() {
            const query = this.value.trim();
            
            if (query.length >= MIN_SEARCH_LENGTH) {
                showSearchSuggestions(query, this);
            } else {
                closeSuggestions();
            }
            
            updateCharacterCounter(this);
        }, 300));
        
        // Focus - show history
        input.addEventListener('focus', function() {
            if (this.value.trim().length === 0) {
                showSearchHistory(this);
            }
        });
        
        // Click outside - close suggestions
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.help-search-input-wrapper')) {
                closeSuggestions();
            }
        });
    });
}

// ==================== CLEAR BUTTON ====================
function addClearButton(input) {
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'help-search-clear-btn';
    clearBtn.innerHTML = '<i class="fas fa-times"></i>';
    clearBtn.title = 'Wyczyść';
    clearBtn.style.display = 'none';
    
    clearBtn.addEventListener('click', function() {
        input.value = '';
        input.focus();
        this.style.display = 'none';
        closeSuggestions();
        updateCharacterCounter(input);
    });
    
    input.addEventListener('input', function() {
        if (this.value.trim().length > 0) {
            clearBtn.style.display = 'flex';
        } else {
            clearBtn.style.display = 'none';
        }
    });
    
    // Show clear button if input has value on load
    if (input.value.trim().length > 0) {
        clearBtn.style.display = 'flex';
    }
    
    wrapper.appendChild(clearBtn);
}

// ==================== CHARACTER COUNTER ====================
function addCharacterCounter(input) {
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    const counter = document.createElement('span');
    counter.className = 'help-search-char-counter';
    counter.textContent = `0/${MAX_SEARCH_LENGTH}`;
    
    wrapper.appendChild(counter);
    
    updateCharacterCounter(input);
}

function updateCharacterCounter(input) {
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    const counter = wrapper.querySelector('.help-search-char-counter');
    if (!counter) return;
    
    const length = input.value.length;
    counter.textContent = `${length}/${MAX_SEARCH_LENGTH}`;
    
    if (length > MAX_SEARCH_LENGTH * 0.9) {
        counter.classList.add('warning');
    } else {
        counter.classList.remove('warning');
    }
}

// ==================== SEARCH ERROR ====================
function showSearchError(input, message) {
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    // Remove existing error
    clearSearchError(input);
    
    const error = document.createElement('div');
    error.className = 'help-search-error';
    error.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
    
    wrapper.classList.add('has-error');
    wrapper.parentElement.appendChild(error);
    
    input.focus();
    
    // Shake animation
    wrapper.style.animation = 'shake 0.3s';
    setTimeout(() => {
        wrapper.style.animation = '';
    }, 300);
}

function clearSearchError(input) {
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    wrapper.classList.remove('has-error');
    
    const error = wrapper.parentElement.querySelector('.help-search-error');
    if (error) {
        error.remove();
    }
}

// ==================== SEARCH HISTORY ====================
function saveSearchQuery(query) {
    let history = getSearchHistory();
    
    // Remove duplicates
    history = history.filter(item => item.toLowerCase() !== query.toLowerCase());
    
    // Add to beginning
    history.unshift(query);
    
    // Limit to MAX_HISTORY_ITEMS
    if (history.length > MAX_HISTORY_ITEMS) {
        history = history.slice(0, MAX_HISTORY_ITEMS);
    }
    
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history));
}

function getSearchHistory() {
    const history = localStorage.getItem(SEARCH_HISTORY_KEY);
    return history ? JSON.parse(history) : [];
}

function clearSearchHistory() {
    localStorage.removeItem(SEARCH_HISTORY_KEY);
}

function showSearchHistory(input) {
    const history = getSearchHistory();
    
    if (history.length === 0) return;
    
    const wrapper = input.closest('.help-search-input-wrapper, .help-main-search-input-wrapper');
    if (!wrapper) return;
    
    closeSuggestions();
    
    const dropdown = document.createElement('div');
    dropdown.className = 'help-search-dropdown';
    dropdown.id = 'searchDropdown';
    
    const header = document.createElement('div');
    header.className = 'help-search-dropdown-header';
    header.innerHTML = `
        <span><i class="fas fa-history"></i> Historia wyszukiwania</span>
        <button type="button" class="help-search-clear-history" onclick="clearAllSearchHistory()">
            <i class="fas fa-trash"></i> Wyczyść
        </button>
    `;
    
    dropdown.appendChild(header);
    
    const list = document.createElement('ul');
    list.className = 'help-search-dropdown-list';
    
    history.forEach(item => {
        const li = document.createElement('li');
        li.className = 'help-search-dropdown-item';
        li.innerHTML = `
            <i class="fas fa-search"></i>
            <span>${escapeHtml(item)}</span>
        `;
        
        li.addEventListener('click', function() {
            input.value = item;
            input.form.submit();
        });
        
        list.appendChild(li);
    });
    
    dropdown.appendChild(list);
    wrapper.appendChild(dropdown);
}

function clearAllSearchHistory() {
    if (confirm('Czy na pewno chcesz wyczyścić historię wyszukiwania?')) {
        clearSearchHistory();
        closeSuggestions();
    }
}

window.clearAllSearchHistory = clearAllSearchHistory;

// ==================== SEARCH SUGGESTIONS ====================
function initSearchSuggestions() {
    // Placeholder - w przyszłości można dodać live suggestions z backendu
}

function showSearchSuggestions(query, input) {
    // Placeholder - można implementować AJAX suggestions
    // Na razie pokazujemy tylko historię
}

function focusFirstSuggestion() {
    const dropdown = document.getElementById('searchDropdown');
    if (!dropdown) return;
    
    const firstItem = dropdown.querySelector('.help-search-dropdown-item');
    if (firstItem) {
        firstItem.focus();
    }
}

function closeSuggestions() {
    const dropdown = document.getElementById('searchDropdown');
    if (dropdown) {
        dropdown.remove();
    }
}

// ==================== HIGHLIGHT SEARCH RESULTS ====================
function highlightSearchResults() {
    const urlParams = new URLSearchParams(window.location.search);
    const query = urlParams.get('q');
    
    if (!query || query.length < MIN_SEARCH_LENGTH) return;
    
    const excerpts = document.querySelectorAll('.help-search-result-excerpt');
    
    excerpts.forEach(excerpt => {
        highlightText(excerpt, query);
    });
}

function highlightText(element, query) {
    const words = query.split(/\s+/).filter(word => word.length >= MIN_SEARCH_LENGTH);
    
    words.forEach(word => {
        const regex = new RegExp(`(${escapeRegExp(word)})`, 'gi');
        
        element.innerHTML = element.innerHTML.replace(regex, '<span class="highlight">$1</span>');
    });
}

// ==================== SEARCH FILTERS ====================
function initSearchFilters() {
    const filterButtons = document.querySelectorAll('.help-search-filter-btn');
    
    filterButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const filter = this.getAttribute('data-filter');
            applySearchFilter(filter);
        });
    });
}

function applySearchFilter(filter) {
    const results = document.querySelectorAll('.help-search-result-card');
    
    results.forEach(result => {
        const matchType = result.getAttribute('data-match-type');
        
        if (filter === 'all' || matchType === filter) {
            result.style.display = 'block';
        } else {
            result.style.display = 'none';
        }
    });
    
    // Update active filter button
    document.querySelectorAll('.help-search-filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    document.querySelector(`[data-filter="${filter}"]`)?.classList.add('active');
}

initSearchFilters();

// ==================== SEARCH STATS ====================
function updateSearchStats() {
    const resultsCount = document.querySelectorAll('.help-search-result-card:not([style*="display: none"])').length;
    const statsEl = document.querySelector('.help-search-count');
    
    if (statsEl) {
        statsEl.textContent = resultsCount;
    }
}

// ==================== KEYBOARD SHORTCUTS ====================
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + K - focus search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[name="q"]');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
    }
});

// ==================== UTILITY FUNCTIONS ====================
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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

// ==================== SEARCH ANALYTICS ====================
function trackSearch(query, resultsCount) {
    // Placeholder for analytics tracking
    console.log(`Search: "${query}" - ${resultsCount} results`);
}

// Track current search if on results page
const urlParams = new URLSearchParams(window.location.search);
const currentQuery = urlParams.get('q');
if (currentQuery) {
    const resultsCount = document.querySelectorAll('.help-search-result-card').length;
    trackSearch(currentQuery, resultsCount);
}

// ==================== NO RESULTS ACTIONS ====================
function initNoResultsActions() {
    const noResults = document.querySelector('.help-search-no-results');
    
    if (noResults) {
        // Add feedback button
        const feedbackBtn = document.createElement('button');
        feedbackBtn.className = 'help-search-feedback-btn';
        feedbackBtn.innerHTML = '<i class="fas fa-comment"></i> Zgłoś problem';
        feedbackBtn.onclick = function() {
            alert('Funkcja zgłaszania problemów zostanie dodana wkrótce!');
        };
        
        const actionDiv = noResults.querySelector('.help-search-no-results-action');
        if (actionDiv) {
            actionDiv.appendChild(feedbackBtn);
        }
    }
}

initNoResultsActions();

// ==================== SEARCH RESULT INTERACTIONS ====================
function initSearchResultInteractions() {
    const resultCards = document.querySelectorAll('.help-search-result-card');
    
    resultCards.forEach(card => {
        // Add click tracking
        card.addEventListener('click', function(e) {
            if (!e.target.closest('a')) {
                const link = this.querySelector('.help-search-result-link');
                if (link) {
                    window.location.href = link.href;
                }
            }
        });
        
        // Add hover effect enhancement
        card.addEventListener('mouseenter', function() {
            this.style.cursor = 'pointer';
        });
    });
}

initSearchResultInteractions();

// ==================== MOBILE SEARCH ====================
function initMobileSearch() {
    const searchToggle = document.getElementById('mobileSearchToggle');
    const searchOverlay = document.getElementById('mobileSearchOverlay');
    
    if (searchToggle && searchOverlay) {
        searchToggle.addEventListener('click', function() {
            searchOverlay.classList.add('active');
            const input = searchOverlay.querySelector('input[name="q"]');
            if (input) {
                setTimeout(() => input.focus(), 100);
            }
        });
        
        const closeBtn = searchOverlay.querySelector('.close-search');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                searchOverlay.classList.remove('active');
            });
        }
    }
}

initMobileSearch();

console.log('Help Search initialized');