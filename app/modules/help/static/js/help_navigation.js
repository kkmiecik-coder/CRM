/**
 * Help Module - Navigation JavaScript
 * Obsługa sidebara, accordion kategorii, smooth scroll, TOC
 */

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    initSidebarAccordion();
    initSidebarToggle();
    initSmoothScroll();
    initTableOfContents();
    initScrollSpy();
    initStickyElements();
});

// ==================== SIDEBAR ACCORDION ====================
function initSidebarAccordion() {
    const categoryHeaders = document.querySelectorAll('.help-sidebar-category-header');
    
    categoryHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const category = this.closest('.help-sidebar-category');
            const isActive = category.classList.contains('help-sidebar-category-active');
            
            // Close all other categories
            document.querySelectorAll('.help-sidebar-category').forEach(cat => {
                if (cat !== category) {
                    cat.classList.remove('help-sidebar-category-active');
                }
            });
            
            // Toggle current category
            category.classList.toggle('help-sidebar-category-active');
            
            // Save state to localStorage
            const categoryId = this.getAttribute('data-category-id');
            saveAccordionState(categoryId, !isActive);
        });
    });
    
    // Restore accordion state from localStorage
    restoreAccordionState();
    
    // Open category with active article by default
    const activeArticle = document.querySelector('.help-sidebar-article-active');
    if (activeArticle) {
        const category = activeArticle.closest('.help-sidebar-category');
        if (category) {
            category.classList.add('help-sidebar-category-active');
        }
    }
}

function saveAccordionState(categoryId, isOpen) {
    const state = JSON.parse(localStorage.getItem('help_accordion_state') || '{}');
    state[categoryId] = isOpen;
    localStorage.setItem('help_accordion_state', JSON.stringify(state));
}

function restoreAccordionState() {
    const state = JSON.parse(localStorage.getItem('help_accordion_state') || '{}');
    
    Object.keys(state).forEach(categoryId => {
        if (state[categoryId]) {
            const header = document.querySelector(`[data-category-id="${categoryId}"]`);
            if (header) {
                const category = header.closest('.help-sidebar-category');
                if (category) {
                    category.classList.add('help-sidebar-category-active');
                }
            }
        }
    });
}

// ==================== SIDEBAR TOGGLE (MOBILE) ====================
function initSidebarToggle() {
    const toggleBtn = document.getElementById('helpSidebarToggle');
    const sidebar = document.getElementById('helpArticleSidebar');
    
    if (!toggleBtn || !sidebar) return;
    
    toggleBtn.addEventListener('click', function() {
        sidebar.classList.toggle('help-sidebar-open');
        this.classList.toggle('active');
        
        // Update icon
        const icon = this.querySelector('i');
        if (icon) {
            if (sidebar.classList.contains('help-sidebar-open')) {
                icon.className = 'fas fa-times';
            } else {
                icon.className = 'fas fa-bars';
            }
        }
    });
    
    // Close sidebar when clicking outside (mobile)
    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 992) {
            if (!sidebar.contains(e.target) && !toggleBtn.contains(e.target)) {
                sidebar.classList.remove('help-sidebar-open');
                toggleBtn.classList.remove('active');
                
                const icon = toggleBtn.querySelector('i');
                if (icon) {
                    icon.className = 'fas fa-bars';
                }
            }
        }
    });
    
    // Close sidebar on link click (mobile)
    const sidebarLinks = sidebar.querySelectorAll('a');
    sidebarLinks.forEach(link => {
        link.addEventListener('click', function() {
            if (window.innerWidth <= 992) {
                sidebar.classList.remove('help-sidebar-open');
                toggleBtn.classList.remove('active');
                
                const icon = toggleBtn.querySelector('i');
                if (icon) {
                    icon.className = 'fas fa-bars';
                }
            }
        });
    });
}

// ==================== SMOOTH SCROLL ====================
function initSmoothScroll() {
    const links = document.querySelectorAll('a[href^="#"]');
    
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            
            // Skip if it's just "#"
            if (targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            
            if (targetElement) {
                e.preventDefault();
                
                const offset = 80; // Header height + padding
                const targetPosition = targetElement.getBoundingClientRect().top + window.pageYOffset - offset;
                
                window.scrollTo({
                    top: targetPosition,
                    behavior: 'smooth'
                });
                
                // Update URL without jumping
                history.pushState(null, null, targetId);
            }
        });
    });
}

// ==================== TABLE OF CONTENTS (TOC) ====================
function initTableOfContents() {
    const articleBody = document.querySelector('.help-article-body');
    const tocList = document.querySelector('.help-sidebar-toc-list');
    
    if (!articleBody || !tocList) return;
    
    // Clear existing TOC
    tocList.innerHTML = '';
    
    // Find all headings
    const headings = articleBody.querySelectorAll('h2, h3, h4');
    
    if (headings.length === 0) {
        // Hide TOC if no headings
        const tocSection = document.querySelector('.help-sidebar-toc');
        if (tocSection) {
            tocSection.style.display = 'none';
        }
        return;
    }
    
    headings.forEach((heading, index) => {
        // Add ID to heading if it doesn't have one
        if (!heading.id) {
            heading.id = `heading-${index}`;
        }
        
        const level = heading.tagName.toLowerCase().substring(1); // h2 -> 2
        const text = heading.textContent;
        
        const li = document.createElement('li');
        li.className = `help-sidebar-toc-item help-sidebar-toc-level-${level}`;
        
        const a = document.createElement('a');
        a.href = `#${heading.id}`;
        a.className = 'help-sidebar-toc-link';
        a.textContent = text;
        
        li.appendChild(a);
        tocList.appendChild(li);
    });
}

// ==================== SCROLL SPY ====================
function initScrollSpy() {
    const tocLinks = document.querySelectorAll('.help-sidebar-toc-link');
    
    if (tocLinks.length === 0) return;
    
    const observerOptions = {
        root: null,
        rootMargin: '-80px 0px -80% 0px',
        threshold: 0
    };
    
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Remove active class from all links
                tocLinks.forEach(link => {
                    link.classList.remove('active');
                });
                
                // Add active class to current link
                const id = entry.target.getAttribute('id');
                const activeLink = document.querySelector(`.help-sidebar-toc-link[href="#${id}"]`);
                if (activeLink) {
                    activeLink.classList.add('active');
                }
            }
        });
    }, observerOptions);
    
    // Observe all headings
    const headings = document.querySelectorAll('.help-article-body h2, .help-article-body h3, .help-article-body h4');
    headings.forEach(heading => {
        observer.observe(heading);
    });
}

// ==================== STICKY ELEMENTS ====================
function initStickyElements() {
    const sidebar = document.querySelector('.help-article-sidebar');
    
    if (!sidebar) return;
    
    let lastScrollTop = 0;
    let ticking = false;
    
    window.addEventListener('scroll', function() {
        lastScrollTop = window.pageYOffset || document.documentElement.scrollTop;
        
        if (!ticking) {
            window.requestAnimationFrame(function() {
                updateStickyPosition(lastScrollTop);
                ticking = false;
            });
            
            ticking = true;
        }
    });
}

function updateStickyPosition(scrollTop) {
    const sidebar = document.querySelector('.help-article-sidebar');
    
    if (!sidebar) return;
    
    const sidebarRect = sidebar.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    
    // Add/remove sticky class based on scroll position
    if (scrollTop > 100) {
        sidebar.classList.add('help-sidebar-sticky');
    } else {
        sidebar.classList.remove('help-sidebar-sticky');
    }
    
    // Prevent sidebar from going below footer
    const footer = document.querySelector('.help-article-footer');
    if (footer) {
        const footerRect = footer.getBoundingClientRect();
        
        if (footerRect.top < viewportHeight) {
            sidebar.classList.add('help-sidebar-at-footer');
        } else {
            sidebar.classList.remove('help-sidebar-at-footer');
        }
    }
}

// ==================== KEYBOARD NAVIGATION ====================
document.addEventListener('keydown', function(e) {
    // Next/Previous article navigation with arrow keys
    if (e.key === 'ArrowLeft' && !isInputFocused()) {
        const prevLink = document.querySelector('.help-article-nav-prev');
        if (prevLink) {
            window.location.href = prevLink.href;
        }
    }
    
    if (e.key === 'ArrowRight' && !isInputFocused()) {
        const nextLink = document.querySelector('.help-article-nav-next');
        if (nextLink) {
            window.location.href = nextLink.href;
        }
    }
    
    // Home key - scroll to top
    if (e.key === 'Home' && !isInputFocused()) {
        e.preventDefault();
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    }
    
    // End key - scroll to bottom
    if (e.key === 'End' && !isInputFocused()) {
        e.preventDefault();
        window.scrollTo({
            top: document.body.scrollHeight,
            behavior: 'smooth'
        });
    }
});

function isInputFocused() {
    const activeElement = document.activeElement;
    return activeElement && (
        activeElement.tagName === 'INPUT' || 
        activeElement.tagName === 'TEXTAREA' || 
        activeElement.isContentEditable
    );
}

// ==================== BACK TO TOP BUTTON ====================
function initBackToTop() {
    const backToTopBtn = document.getElementById('backToTop');
    
    if (!backToTopBtn) return;
    
    window.addEventListener('scroll', function() {
        if (window.pageYOffset > 300) {
            backToTopBtn.classList.add('visible');
        } else {
            backToTopBtn.classList.remove('visible');
        }
    });
    
    backToTopBtn.addEventListener('click', function() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
}

// Initialize back to top on load
initBackToTop();

// ==================== SEARCH HIGHLIGHT IN SIDEBAR ====================
function highlightSearchInSidebar(query) {
    if (!query) return;
    
    const articleLinks = document.querySelectorAll('.help-sidebar-article-link span');
    
    articleLinks.forEach(link => {
        const text = link.textContent;
        const regex = new RegExp(`(${query})`, 'gi');
        
        if (regex.test(text)) {
            const highlighted = text.replace(regex, '<mark>$1</mark>');
            link.innerHTML = highlighted;
        }
    });
}

// Check for search query in URL
const urlParams = new URLSearchParams(window.location.search);
const searchQuery = urlParams.get('q');
if (searchQuery) {
    highlightSearchInSidebar(searchQuery);
}

// ==================== PRINT FUNCTIONALITY ====================
function initPrintButton() {
    const printBtn = document.getElementById('printArticleBtn');
    
    if (printBtn) {
        printBtn.addEventListener('click', function() {
            window.print();
        });
    }
}

initPrintButton();

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

// Handle window resize
window.addEventListener('resize', debounce(function() {
    // Close mobile sidebar on resize to desktop
    if (window.innerWidth > 992) {
        const sidebar = document.getElementById('helpArticleSidebar');
        const toggleBtn = document.getElementById('helpSidebarToggle');
        
        if (sidebar && toggleBtn) {
            sidebar.classList.remove('help-sidebar-open');
            toggleBtn.classList.remove('active');
            
            const icon = toggleBtn.querySelector('i');
            if (icon) {
                icon.className = 'fas fa-bars';
            }
        }
    }
}, 250));

// ==================== COPY CODE BLOCKS ====================
function initCodeBlockCopy() {
    const codeBlocks = document.querySelectorAll('.help-article-body pre code');
    
    codeBlocks.forEach(codeBlock => {
        const pre = codeBlock.parentElement;
        
        // Add copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'help-code-copy-btn';
        copyBtn.innerHTML = '<i class="fas fa-copy"></i> Kopiuj';
        copyBtn.title = 'Kopiuj kod';
        
        copyBtn.addEventListener('click', function() {
            const code = codeBlock.textContent;
            
            navigator.clipboard.writeText(code).then(() => {
                copyBtn.innerHTML = '<i class="fas fa-check"></i> Skopiowano!';
                copyBtn.classList.add('copied');
                
                setTimeout(() => {
                    copyBtn.innerHTML = '<i class="fas fa-copy"></i> Kopiuj';
                    copyBtn.classList.remove('copied');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy code:', err);
                copyBtn.innerHTML = '<i class="fas fa-times"></i> Błąd';
            });
        });
        
        pre.style.position = 'relative';
        pre.appendChild(copyBtn);
    });
}

initCodeBlockCopy();

// ==================== EXTERNAL LINKS ====================
function initExternalLinks() {
    const articleLinks = document.querySelectorAll('.help-article-body a');
    
    articleLinks.forEach(link => {
        const href = link.getAttribute('href');
        
        // Check if external link
        if (href && (href.startsWith('http://') || href.startsWith('https://')) && !href.includes(window.location.hostname)) {
            link.setAttribute('target', '_blank');
            link.setAttribute('rel', 'noopener noreferrer');
            
            // Add external icon
            if (!link.querySelector('.fa-external-link-alt')) {
                const icon = document.createElement('i');
                icon.className = 'fas fa-external-link-alt';
                icon.style.marginLeft = '4px';
                icon.style.fontSize = '0.8em';
                link.appendChild(icon);
            }
        }
    });
}

initExternalLinks();

console.log('Help Navigation initialized');