# Production Page Optimization - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize the `/production/` page with prefetch hot tabs, skeleton loading, URL sync, global auto-refresh, and split the 327KB `api_routers.py` into focused files.

**Architecture:** Prefetch Dashboard + Products tabs on page load with skeleton placeholders. Cache loaded tabs in DOM. Move auto-refresh from DashboardModule to ProductionApp (global). Split api_routers.py into per-tab API files.

**Tech Stack:** Flask/Jinja2, vanilla JS (ES6 classes), CSS3 animations, Bootstrap 5.3

---

## File Structure

### Modified Files
- `modules/production/templates/panel/dashboard.html` — remove h1, user-greeting, add skeletons, new tab layout
- `modules/production/static/js/production-app-loader.js` — prefetch, cache, URL sync, global refresh
- `modules/production/static/js/modules/dashboard-module.js` — remove old auto-refresh/status methods
- `modules/production/static/css/production-panel.css` — skeleton styles, tab redesign, remove old styles
- `modules/production/templates/components/dashboard-tab-content.html` — sync date coloring
- `modules/production/routers/__init__.py` — update imports for new api/ sub-package

### New Files
- `modules/production/routers/api/__init__.py` — sub-blueprint init, re-export api_bp
- `modules/production/routers/api/dashboard_api.py` — dashboard tab content + data endpoints
- `modules/production/routers/api/products_api.py` — products tab content + CRUD endpoints
- `modules/production/routers/api/reports_api.py` — reports tab content
- `modules/production/routers/api/stations_api.py` — stations tab content
- `modules/production/routers/api/config_api.py` — config tab content + config endpoints
- `modules/production/routers/api/sync_api.py` — sync/cron endpoints
- `modules/production/routers/api/common_api.py` — health, decorators, error handlers, middleware

### Deleted Files
- `modules/production/routers/api_routers.py` — replaced by api/ sub-package

---

### Task 1: Add skeleton CSS styles to production-panel.css

**Files:**
- Modify: `modules/production/static/css/production-panel.css`

- [ ] **Step 1: Add skeleton animation and base classes**

Add at the end of `production-panel.css` (before any media queries if present):

```css
/* ========================================
   SKELETON LOADING
   ======================================== */
@keyframes skeleton-pulse {
    0% { opacity: 0.6; }
    50% { opacity: 0.3; }
    100% { opacity: 0.6; }
}

.skeleton {
    background: #e2e8f0;
    border-radius: 4px;
    animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-text {
    height: 14px;
    margin-bottom: 8px;
    border-radius: 4px;
}

.skeleton-text.short { width: 40%; }
.skeleton-text.medium { width: 65%; }
.skeleton-text.long { width: 90%; }

.skeleton-heading {
    height: 22px;
    width: 50%;
    margin-bottom: 12px;
}

.skeleton-stat {
    height: 36px;
    width: 80px;
    border-radius: 6px;
}

.skeleton-card {
    background: #fff;
    border-radius: var(--border-radius-md, 8px);
    padding: 16px;
    box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1));
}

.skeleton-row {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid #f1f5f9;
}

.skeleton-row:last-child { border-bottom: none; }

.skeleton-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    flex-shrink: 0;
}

.skeleton-badge {
    width: 64px;
    height: 22px;
    border-radius: 12px;
}

/* Skeleton -> content transition */
.tab-skeleton {
    transition: opacity 0.15s ease;
}

.tab-skeleton.hidden {
    opacity: 0;
    pointer-events: none;
    position: absolute;
}

.tab-content-wrapper {
    transition: opacity 0.15s ease;
}

.tab-content-wrapper.fade-in {
    opacity: 1;
}
```

- [ ] **Step 2: Add sync date coloring classes**

Add right after the skeleton section:

```css
/* ========================================
   SYNC DATE COLORING
   ======================================== */
.sync-fresh { color: var(--status-active, #28a745); font-weight: 600; }
.sync-warning { color: var(--status-warning, #ffc107); font-weight: 600; }
.sync-stale { color: var(--status-danger, #dc3545); font-weight: 600; }
```

- [ ] **Step 3: Add new tab bar styles**

Add right after sync coloring:

```css
/* ========================================
   TAB BAR REDESIGN
   ======================================== */
.production-tabs-bar {
    display: flex;
    align-items: center;
    gap: 0;
    border-bottom: 2px solid #e2e8f0;
    padding: 0;
    background: transparent;
}

.production-tabs-bar .nav-tabs {
    border-bottom: none;
    flex: 1;
    gap: 0;
}

.production-tabs-bar .nav-link {
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 500;
    color: #64748b;
    background: transparent;
    transition: color 0.2s, border-color 0.2s;
    white-space: nowrap;
}

.production-tabs-bar .nav-link:hover {
    color: var(--production-primary, #2c5530);
    border-bottom-color: #cbd5e1;
}

.production-tabs-bar .nav-link.active {
    color: var(--production-primary, #2c5530);
    border-bottom-color: var(--production-primary, #2c5530);
    font-weight: 600;
    background: transparent;
}

.production-tabs-bar .nav-link i {
    font-size: 12px;
}

.tab-refresh-btn {
    background: none;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 6px 10px;
    color: #64748b;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    margin-left: auto;
    flex-shrink: 0;
}

.tab-refresh-btn:hover {
    background: #f1f5f9;
    color: var(--production-primary, #2c5530);
    border-color: #cbd5e1;
}

.tab-refresh-btn.refreshing {
    pointer-events: none;
    opacity: 0.6;
}

.tab-refresh-btn.refreshing .refresh-icon {
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* Full height tab content */
.production-tab-content {
    flex: 1;
    min-height: 0;
}

.production-dashboard-tabs {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
}
```

- [ ] **Step 4: Remove old status bar CSS**

Remove these CSS blocks from `production-panel.css`:
- `.user-greeting` (around line 112)
- `.production-status` (around line 781)
- `.system-refresh-section` (around line 794)
- `.refresh-system-btn` and its hover/disabled states (around lines 800-831)
- `.refresh-icon` (around line 834)
- `.refresh-text` (around line 840)
- `.refresh-timer` and its states (around lines 846-875)

Search for each class name and remove the entire rule block.

- [ ] **Step 5: Commit**

```bash
git add modules/production/static/css/production-panel.css
git commit -m "style: add skeleton loading, tab redesign, sync coloring CSS; remove old status bar styles"
```

---

### Task 2: Restructure dashboard.html — remove h1, status bar, add skeletons and new tab layout

**Files:**
- Modify: `modules/production/templates/panel/dashboard.html`

- [ ] **Step 1: Replace header and tab navigation (lines 29-113)**

Replace everything from `<div class="dashboard-header">` (line 29) through `</nav>` (line 113) with:

```html
            <!-- Production Tabs Bar -->
            <div class="production-tabs-bar">
                <nav class="nav nav-tabs" id="productionDashboardTabs" role="tablist">
                    <button class="nav-link active"
                            id="dashboard-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#dashboard-tab-content"
                            type="button" role="tab"
                            aria-controls="dashboard-tab-content"
                            aria-selected="true">
                        <i class="fas fa-tachometer-alt me-2"></i>Dashboard
                    </button>
                    <button class="nav-link"
                            id="products-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#products-tab-content"
                            type="button" role="tab"
                            aria-controls="products-tab-content"
                            aria-selected="false">
                        <i class="fas fa-list me-2"></i>Lista produktów
                    </button>
                    <button class="nav-link"
                            id="reports-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#reports-tab-content"
                            type="button" role="tab"
                            aria-controls="reports-tab-content"
                            aria-selected="false">
                        <i class="fas fa-chart-bar me-2"></i>Raporty
                    </button>
                    <button class="nav-link"
                            id="stations-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#stations-tab-content"
                            type="button" role="tab"
                            aria-controls="stations-tab-content"
                            aria-selected="false">
                        <i class="fas fa-industry me-2"></i>Stanowiska
                    </button>
                    <button class="nav-link"
                            id="config-tab"
                            data-bs-toggle="tab"
                            data-bs-target="#config-tab-content"
                            type="button" role="tab"
                            aria-controls="config-tab-content"
                            aria-selected="false">
                        <i class="fas fa-cog me-2"></i>Konfiguracja
                    </button>
                </nav>
                <button class="tab-refresh-btn" id="tab-refresh-btn" title="Odśwież aktywną zakładkę">
                    <i class="fas fa-sync-alt refresh-icon"></i>
                    <span>Odśwież</span>
                </button>
            </div>
```

- [ ] **Step 2: Replace dashboard tab pane loading state (lines 124-128)**

Replace the `<div class="tab-loading" id="dashboard-tab-loading">` block with a skeleton:

```html
                        <div class="tab-skeleton" id="dashboard-tab-skeleton">
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; padding: 16px 0;">
                                <div class="skeleton-card"><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-stat"></div></div>
                                <div class="skeleton-card"><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-stat"></div></div>
                                <div class="skeleton-card"><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-stat"></div></div>
                                <div class="skeleton-card"><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-stat"></div></div>
                            </div>
                            <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 16px;">
                                <div class="skeleton-card" style="min-height: 200px;"><div class="skeleton skeleton-heading"></div><div class="skeleton skeleton-text long"></div><div class="skeleton skeleton-text medium"></div><div class="skeleton skeleton-text long"></div></div>
                                <div class="skeleton-card" style="min-height: 200px;"><div class="skeleton skeleton-heading"></div><div class="skeleton skeleton-text medium"></div><div class="skeleton skeleton-text short"></div><div class="skeleton skeleton-text medium"></div></div>
                            </div>
                        </div>
```

- [ ] **Step 3: Replace products tab pane loading state (lines 153-158)**

Replace the `<div class="tab-loading" id="products-tab-loading">` block with a skeleton:

```html
                        <div class="tab-skeleton" id="products-tab-skeleton">
                            <div style="padding: 16px 0;">
                                <div style="display: flex; gap: 12px; margin-bottom: 16px;">
                                    <div class="skeleton skeleton-badge" style="width: 120px; height: 32px;"></div>
                                    <div class="skeleton skeleton-badge" style="width: 100px; height: 32px;"></div>
                                    <div class="skeleton skeleton-badge" style="width: 160px; height: 32px; margin-left: auto;"></div>
                                </div>
                                <div class="skeleton-card">
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                    <div class="skeleton-row"><div class="skeleton skeleton-avatar"></div><div class="skeleton skeleton-text long" style="flex:1;margin:0;"></div><div class="skeleton skeleton-badge"></div></div>
                                </div>
                            </div>
                        </div>
```

- [ ] **Step 4: Keep lazy tab loading states as simple spinners**

Leave reports, stations, and config tab loading divs as they are (spinner-based). They only show on first click so a skeleton isn't needed.

- [ ] **Step 5: Commit**

```bash
git add modules/production/templates/panel/dashboard.html
git commit -m "feat: restructure dashboard.html — remove h1/status bar, add skeletons, new tab layout"
```

---

### Task 3: Rewrite production-app-loader.js — prefetch, cache, URL sync, global refresh

**Files:**
- Modify: `modules/production/static/js/production-app-loader.js`

- [ ] **Step 1: Update constructor state and add tab cache**

In the `ProductionApp` constructor (around line 32), replace the state initialization with:

```javascript
constructor() {
    this.shared = window.ProductionShared;

    this.state = {
        currentTab: null,
        isInitialized: false,
        loadedModules: new Map(),
        isLoading: false,
        tabCache: new Map(), // tracks which tabs have been loaded
    };

    this.modules = {};
    this.autoRefreshTimer = null;
    this.AUTO_REFRESH_INTERVAL = 60000; // 60 seconds

    // Hot tabs loaded on page entry
    this.HOT_TABS = ['dashboard-tab', 'products-tab'];

    this.handleTabClick = this.handleTabClick.bind(this);
    this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
    this.handleBeforeUnload = this.handleBeforeUnload.bind(this);
}
```

- [ ] **Step 2: Update init() method to prefetch hot tabs**

Replace the `init()` method (around lines 54-93) with:

```javascript
async init() {
    if (this.state.isInitialized) {
        console.warn('[ProductionApp] Already initialized');
        return;
    }

    console.log('[ProductionApp] Initializing...');

    this.setupEventListeners();
    this.initTabSystem();

    // Determine initial tab from URL param or default
    const initialTab = this.getInitialTabFromURL();
    this.updateTabUI(initialTab);
    this.state.currentTab = initialTab;

    // Prefetch hot tabs in parallel
    await this.prefetchHotTabs(initialTab);

    // Setup global auto-refresh
    this.setupAutoRefresh();

    // Setup refresh button
    this.setupRefreshButton();

    this.state.isInitialized = true;
    this.shared.eventBus.emit('app:ready', { tab: initialTab });
    console.log('[ProductionApp] Initialized successfully');
}
```

- [ ] **Step 3: Add URL sync methods**

Add after the init() method:

```javascript
// ========================================================================
// URL SYNC
// ========================================================================

getInitialTabFromURL() {
    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get('tab');
    if (tabParam) {
        const tabName = tabParam.endsWith('-tab') ? tabParam : `${tabParam}-tab`;
        const validTabs = ['dashboard-tab', 'products-tab', 'reports-tab', 'stations-tab', 'config-tab'];
        if (validTabs.includes(tabName)) {
            return tabName;
        }
    }
    return 'dashboard-tab';
}

updateURL(tabName) {
    const shortName = tabName.replace('-tab', '');
    const params = new URLSearchParams(window.location.search);
    if (shortName === 'dashboard') {
        params.delete('tab');
    } else {
        params.set('tab', shortName);
    }
    const newURL = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
    history.replaceState(null, '', newURL);
}
```

- [ ] **Step 4: Add prefetch logic**

Add after URL sync methods:

```javascript
// ========================================================================
// PREFETCH HOT TABS
// ========================================================================

async prefetchHotTabs(initialTab) {
    // Prioritize the initial tab, then load other hot tabs
    const prioritized = [initialTab, ...this.HOT_TABS.filter(t => t !== initialTab)];
    // Only prefetch hot tabs
    const toPrefetch = prioritized.filter(t => this.HOT_TABS.includes(t));

    console.log(`[ProductionApp] Prefetching hot tabs: ${toPrefetch.join(', ')}`);

    // Load initial tab first (user sees it)
    if (toPrefetch.length > 0) {
        await this.loadTabContent(toPrefetch[0]);
    }

    // Then load remaining hot tabs in background
    const remaining = toPrefetch.slice(1);
    if (remaining.length > 0) {
        Promise.all(remaining.map(tab => this.loadTabContent(tab))).catch(err => {
            console.warn('[ProductionApp] Background prefetch error:', err);
        });
    }
}
```

- [ ] **Step 5: Rewrite switchToTab with cache support**

Replace the `switchToTab()` method with:

```javascript
async switchToTab(tabName) {
    if (!tabName) {
        console.error('[ProductionApp] switchToTab called with null/undefined tabName');
        return;
    }

    if (this.state.isLoading) {
        console.log('[ProductionApp] Tab switch ignored - currently loading');
        return;
    }

    if (this.state.currentTab === tabName) {
        console.log(`[ProductionApp] Already on tab: ${tabName}`);
        return;
    }

    console.log(`[ProductionApp] Switching to ${tabName}`);

    try {
        // 1. Update UI immediately (tabs + panes)
        this.updateTabUI(tabName);
        this.state.currentTab = tabName;
        this.updateURL(tabName);

        // 2. If tab not cached, load it
        if (!this.state.tabCache.has(tabName)) {
            this.state.isLoading = true;
            await this.loadTabContent(tabName);
        }

        // 3. Emit event
        this.shared.eventBus.emit('tab:changed', { tab: tabName });

    } catch (error) {
        console.error(`[ProductionApp] Error switching to tab ${tabName}:`, error);
        this.shared.toastSystem.show(`Błąd ładowania zakładki: ${error.message}`, 'error');
    } finally {
        this.state.isLoading = false;
    }
}
```

- [ ] **Step 6: Rewrite loadTabContent with skeleton and cache**

Replace the `loadTabContent()` method with:

```javascript
async loadTabContent(tabName) {
    // Check if Baselinker sync modal is active
    if (typeof window.isBaselinkerSyncModalActive === 'function' && window.isBaselinkerSyncModalActive()) {
        console.log('[ProductionApp] Cannot load tab - sync modal active');
        return;
    }

    if (this.state.tabCache.has(tabName)) {
        console.log(`[ProductionApp] Tab ${tabName} already cached`);
        return;
    }

    console.log(`[ProductionApp] Loading tab content: ${tabName}`);

    const normalizedTabName = tabName.endsWith('-tab') ? tabName : `${tabName}-tab`;

    switch (normalizedTabName) {
        case 'dashboard-tab': await this.loadDashboardTab(); break;
        case 'products-tab': await this.loadProductsTab(); break;
        case 'reports-tab': await this.loadReportsTab(); break;
        case 'stations-tab': await this.loadStationsTab(); break;
        case 'config-tab': await this.loadConfigTab(); break;
        default: throw new Error(`Unknown tab: ${normalizedTabName}`);
    }

    this.state.tabCache.set(tabName, true);
}
```

- [ ] **Step 7: Update individual tab loaders to use skeletons**

Replace `loadDashboardTab()` with:

```javascript
async loadDashboardTab() {
    console.log('[ProductionApp] Loading dashboard tab...');
    try {
        const response = await this.shared.apiClient.getDashboardTabContent();
        if (!response.success) throw new Error(response.error || 'Failed to load dashboard');

        const wrapper = document.getElementById('dashboard-tab-wrapper');
        const skeleton = document.getElementById('dashboard-tab-skeleton');

        if (wrapper) {
            wrapper.innerHTML = response.html;
            wrapper.style.display = 'block';
            wrapper.classList.add('fade-in');
        }
        if (skeleton) skeleton.classList.add('hidden');

        await this.initializeDashboardModule();
        console.log('[ProductionApp] Dashboard tab loaded');
    } catch (error) {
        console.error('[ProductionApp] Dashboard loading failed:', error);
        this.showTabError('dashboard-tab', error.message);
        throw error;
    }
}
```

Replace `loadProductsTab()` with:

```javascript
async loadProductsTab() {
    console.log('[ProductionApp] Loading products tab...');
    try {
        const response = await this.shared.apiClient.getProductsTabContent();
        if (!response.success) throw new Error(response.error || 'Failed to load products');

        const wrapper = document.getElementById('products-tab-wrapper');
        const skeleton = document.getElementById('products-tab-skeleton');

        if (wrapper) {
            wrapper.innerHTML = response.html;
            wrapper.style.display = 'block';
            wrapper.classList.add('fade-in');
        }
        if (skeleton) skeleton.classList.add('hidden');

        await this.initializeProductsModule();
        console.log('[ProductionApp] Products tab loaded');
    } catch (error) {
        console.error('[ProductionApp] Products loading failed:', error);
        this.showTabError('products-tab', error.message);
        throw error;
    }
}
```

Leave `loadReportsTab()`, `loadStationsTab()`, `loadConfigTab()` mostly unchanged — they already use `loading.style.display = 'none'` which is fine for lazy tabs.

- [ ] **Step 8: Rewrite auto-refresh to be global**

Replace the `setupAutoRefresh()` and `refreshCurrentTab()` methods with:

```javascript
// ========================================================================
// GLOBAL AUTO REFRESH
// ========================================================================

setupAutoRefresh() {
    if (this.autoRefreshTimer) clearInterval(this.autoRefreshTimer);

    this.autoRefreshTimer = setInterval(() => {
        if (!document.hidden && !this.state.isLoading) {
            this.refreshActiveTab();
        }
    }, this.AUTO_REFRESH_INTERVAL);

    console.log(`[ProductionApp] Global auto-refresh: ${this.AUTO_REFRESH_INTERVAL / 1000}s`);
}

resetAutoRefreshTimer() {
    this.setupAutoRefresh(); // restart the interval
}

async refreshActiveTab() {
    const tabName = this.state.currentTab;
    if (!tabName || this.state.isLoading) return;

    if (typeof window.isBaselinkerSyncModalActive === 'function' && window.isBaselinkerSyncModalActive()) {
        console.log('[ProductionApp] Skipping refresh - sync modal active');
        return;
    }

    console.log(`[ProductionApp] Refreshing active tab: ${tabName}`);

    try {
        // Show skeleton on dynamic content
        this.showRefreshSkeleton(tabName);

        // Delegate to module if it has a refresh method
        const moduleName = tabName.replace('-tab', '');
        const module = this.state.loadedModules.get(moduleName);
        if (module && typeof module.refresh === 'function') {
            await module.refresh();
        } else {
            // Fallback: reload tab HTML
            this.state.tabCache.delete(tabName);
            await this.loadTabContent(tabName);
        }
    } catch (error) {
        console.error(`[ProductionApp] Refresh failed for ${tabName}:`, error);
    }
}

showRefreshSkeleton(tabName) {
    // Apply skeleton class to dynamic values in the active tab
    const wrapper = document.getElementById(`${tabName}-wrapper`);
    if (!wrapper) return;

    wrapper.querySelectorAll('[data-skeleton]').forEach(el => {
        el.dataset.originalText = el.textContent;
        el.classList.add('skeleton');
        el.style.minWidth = el.offsetWidth + 'px';
        el.textContent = '';
    });
}

clearRefreshSkeleton(tabName) {
    const wrapper = document.getElementById(`${tabName}-wrapper`);
    if (!wrapper) return;

    wrapper.querySelectorAll('[data-skeleton].skeleton').forEach(el => {
        el.classList.remove('skeleton');
        el.style.minWidth = '';
        // Text will be updated by the refresh data
    });
}
```

- [ ] **Step 9: Add refresh button handler**

Add after auto-refresh section:

```javascript
// ========================================================================
// REFRESH BUTTON
// ========================================================================

setupRefreshButton() {
    const btn = document.getElementById('tab-refresh-btn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (btn.classList.contains('refreshing')) return;

        btn.classList.add('refreshing');
        try {
            await this.refreshActiveTab();
            this.resetAutoRefreshTimer();
        } finally {
            btn.classList.remove('refreshing');
        }
    });
}
```

- [ ] **Step 10: Update loadInitialTab to be removed (replaced by prefetchHotTabs)**

Remove the `loadInitialTab()` method entirely (lines 729-775). It's replaced by `prefetchHotTabs()` called from `init()`.

- [ ] **Step 11: Update handleVisibilityChange**

Replace `handleVisibilityChange()`:

```javascript
handleVisibilityChange() {
    if (document.hidden) {
        console.log('[ProductionApp] Page hidden');
    } else {
        console.log('[ProductionApp] Page visible - scheduling refresh');
        setTimeout(() => this.refreshActiveTab(), 1000);
    }
}
```

- [ ] **Step 12: Update forceRefresh**

Replace:

```javascript
async forceRefresh() {
    await this.refreshActiveTab();
    this.resetAutoRefreshTimer();
}
```

- [ ] **Step 13: Commit**

```bash
git add modules/production/static/js/production-app-loader.js
git commit -m "feat: rewrite production-app-loader — prefetch, cache, URL sync, global refresh"
```

---

### Task 4: Clean up DashboardModule — remove old auto-refresh and status widget code

**Files:**
- Modify: `modules/production/static/js/modules/dashboard-module.js`

- [ ] **Step 1: Remove auto-refresh methods from DashboardModule**

Remove these methods entirely:
- `setupAutoRefresh()` (lines ~1864-1900)
- `setupAutoRefreshCountdown()` (lines ~1902-1915)
- `updateRefreshButtonText()` (lines ~1918-1938)
- `performAutoRefresh()` (lines ~1941-1962)
- `handleRefreshSystem()` (lines ~1768-1858)

- [ ] **Step 2: Remove production status widget method**

Remove `updateProductionStatusWidget()` (lines ~342-356).

- [ ] **Step 3: Remove auto-refresh timer properties**

In the constructor/init, remove references to:
- `this.autoRefreshInterval`
- `this.productionStatusInterval`
- `this.autoRefreshTimer`
- `this.autoRefreshCountdown`
- `this.refreshDuration`

Also remove any `setupAutoRefresh()` calls from initialization methods.

- [ ] **Step 4: Remove refresh button event listener**

In `setupEventListeners()` (around line 1050), remove the event listener for `#refresh-system-btn`.

- [ ] **Step 5: Remove auto-refresh timer cleanup from destroy/clearAllTimers**

In `destroy()` and `clearAllTimers()` methods, remove lines that clear `autoRefreshInterval`, `productionStatusInterval`, and `autoRefreshTimer`.

- [ ] **Step 6: Ensure refresh() method exists for ProductionApp delegation**

Make sure DashboardModule has a `refresh()` method that ProductionApp can call. It should call `refreshDataOnly()` which already exists. If `refresh()` doesn't exist, add it:

```javascript
async refresh() {
    console.log('[DashboardModule] Refresh triggered by ProductionApp');
    await this.refreshDataOnly();
}
```

- [ ] **Step 7: Commit**

```bash
git add modules/production/static/js/modules/dashboard-module.js
git commit -m "refactor: remove auto-refresh/status-widget from DashboardModule, add refresh() delegate"
```

---

### Task 5: Add sync date coloring to dashboard-tab-content.html

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html`

- [ ] **Step 1: Update the Sync BaseLinker row (line 302)**

Replace line 302:
```html
            <span class="il-system-value" id="last-sync-display">Ostatnia: {% if dashboard_stats.system_health.last_sync %}{{ dashboard_stats.system_health.last_sync[:16]|replace('T', ' ') }}{% else %}--{% endif %}</span>
```

With:
```html
            <span class="il-system-value" id="last-sync-display">Ostatnia: {% if dashboard_stats.system_health.last_sync %}<span class="sync-date-value" data-sync-time="{{ dashboard_stats.system_health.last_sync }}">{{ dashboard_stats.system_health.last_sync[:16]|replace('T', ' ') }}</span>{% else %}--{% endif %}</span>
```

- [ ] **Step 2: Add inline script to color the sync date**

Add at the bottom of `dashboard-tab-content.html`, inside a `<script>` tag:

```html
<script>
(function() {
    const el = document.querySelector('.sync-date-value');
    if (!el || !el.dataset.syncTime) return;

    const syncTime = new Date(el.dataset.syncTime);
    const hoursAgo = (Date.now() - syncTime.getTime()) / (1000 * 60 * 60);

    if (hoursAgo < 24) {
        el.classList.add('sync-fresh');
    } else if (hoursAgo < 48) {
        el.classList.add('sync-warning');
    } else {
        el.classList.add('sync-stale');
    }
})();
</script>
```

- [ ] **Step 3: Commit**

```bash
git add modules/production/templates/components/dashboard-tab-content.html
git commit -m "feat: add sync date coloring (green/yellow/red) in Status systemu section"
```

---

### Task 6: Split api_routers.py into api/ sub-package — common_api.py (decorators, error handlers, middleware)

**Files:**
- Create: `modules/production/routers/api/__init__.py`
- Create: `modules/production/routers/api/common_api.py`

- [ ] **Step 1: Create api/__init__.py**

```python
# modules/production/routers/api/__init__.py
"""
API sub-package for production module.
Split from monolithic api_routers.py into per-tab files.
"""
from flask import Blueprint

api_bp = Blueprint('production_api', __name__)

from modules.logging import get_structured_logger
logger = get_structured_logger('production.api')

# Import models (shared across all API files)
try:
    from ...models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig, get_local_now
except ImportError:
    from modules.production.models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig, get_local_now

# Import common utilities
from .common_api import admin_required, cron_secret_required, ip_validation_required

# Register all route modules (order doesn't matter - they register on import)
from . import dashboard_api
from . import products_api
from . import reports_api
from . import stations_api
from . import config_api
from . import sync_api
```

- [ ] **Step 2: Create common_api.py with decorators, error handlers, middleware**

Copy from `api_routers.py`:
- Decorators: `admin_required` (lines 48-68), `cron_secret_required` (lines 70-91), `ip_validation_required` (lines 93-131)
- Helper: `_validate_config_value` (lines 2101-2139)
- Error handlers (lines 2376-2470): `bad_request`, `unauthorized`, `forbidden`, `not_found`, `method_not_allowed`, `internal_server_error`
- Middleware (lines 2473-2510): `log_api_request`, `add_api_headers`
- Helper: `_format_status` (lines 5031-5050), `calculate_duration` (lines 5527-5560)

```python
# modules/production/routers/api/common_api.py
"""
Shared decorators, error handlers, middleware, and utility functions for production API.
"""
import traceback
from functools import wraps
from flask import request, jsonify, current_app
from flask_login import current_user
from modules.logging import get_structured_logger

logger = get_structured_logger('production.api')


# ============================================================================
# DECORATORS
# ============================================================================

def admin_required(f):
    # Copy exact implementation from api_routers.py lines 48-68
    ...

def cron_secret_required(f):
    # Copy exact implementation from api_routers.py lines 70-91
    ...

def ip_validation_required(f):
    # Copy exact implementation from api_routers.py lines 93-131
    ...


# ============================================================================
# ERROR HANDLERS (registered on api_bp)
# ============================================================================

def register_error_handlers(api_bp):
    @api_bp.errorhandler(400)
    def bad_request(error):
        # Copy from lines 2376-2390
        ...

    @api_bp.errorhandler(401)
    def unauthorized(error):
        # Copy from lines 2391-2405
        ...

    @api_bp.errorhandler(403)
    def forbidden(error):
        # Copy from lines 2406-2421
        ...

    @api_bp.errorhandler(404)
    def not_found(error):
        # Copy from lines 2422-2436
        ...

    @api_bp.errorhandler(405)
    def method_not_allowed(error):
        # Copy from lines 2437-2452
        ...

    @api_bp.errorhandler(500)
    def internal_server_error(error):
        # Copy from lines 2453-2470
        ...


def register_middleware(api_bp):
    # Copy before_request and after_request from lines 2473-2510
    ...


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _validate_config_value(value, config_type):
    # Copy from lines 2101-2139
    ...

def _format_status(status):
    # Copy from lines 5031-5050
    ...

def calculate_duration(start, end):
    # Copy from lines 5527-5560
    ...
```

**IMPORTANT:** Copy the exact implementation from the original file for each function. The `...` placeholders above mean "copy the function body verbatim".

- [ ] **Step 3: Call register_error_handlers and register_middleware in __init__.py**

Add to end of `api/__init__.py`:

```python
from .common_api import register_error_handlers, register_middleware
register_error_handlers(api_bp)
register_middleware(api_bp)
```

- [ ] **Step 4: Commit**

```bash
git add modules/production/routers/api/__init__.py modules/production/routers/api/common_api.py
git commit -m "refactor: create api/ sub-package with common decorators, error handlers, middleware"
```

---

### Task 7: Split api_routers.py — dashboard_api.py

**Files:**
- Create: `modules/production/routers/api/dashboard_api.py`

- [ ] **Step 1: Create dashboard_api.py**

Move these routes from `api_routers.py`:
- `/dashboard-stats` (lines 133-340)
- `/chart-data` (lines 339-857)
- `/dashboard-tab-content` (lines 2511-2900)
- `/dashboard-data` (lines 6156-6439)
- `/production-status-data` (lines 6440-6520)
- `/dashboard-stats-data` (lines 6521-6697)

```python
# modules/production/routers/api/dashboard_api.py
"""Dashboard API endpoints."""
import json
from datetime import datetime, date, timedelta
from flask import request, jsonify, current_app, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import and_, or_, text, func, distinct, cast, String
from modules.logging import get_structured_logger

from . import api_bp, ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, get_local_now
from .common_api import admin_required

logger = get_structured_logger('production.api.dashboard')

# Paste each route function here verbatim from api_routers.py
# @api_bp.route('/dashboard-stats') ...
# @api_bp.route('/chart-data', methods=['GET', 'POST']) ...
# @api_bp.route('/dashboard-tab-content') ...
# @api_bp.route('/dashboard-data') ...
# @api_bp.route('/production-status-data') ...
# @api_bp.route('/dashboard-stats-data') ...
```

Copy each route function body exactly from the original file. Adjust imports as needed (all from the package `__init__.py` or `common_api`).

- [ ] **Step 2: Commit**

```bash
git add modules/production/routers/api/dashboard_api.py
git commit -m "refactor: extract dashboard API routes to dashboard_api.py"
```

---

### Task 8: Split api_routers.py — products_api.py

**Files:**
- Create: `modules/production/routers/api/products_api.py`

- [ ] **Step 1: Create products_api.py**

Move these routes:
- `/products-tab-content` (lines 2900-3200)
- `/products-paginated` (lines 3200-3287)
- `/products-filtered` (lines 5215-5450)
- `/products/bulk-action` (lines 4099-4213)
- `/products/export` (lines 4214-5049) + helpers `_export_csv`, `_export_excel`, `_export_pdf`
- `/products/filters-data` (lines 5049-5151)
- `/products/<product_id>/priority` (lines 5151-5214)
- `/products/<product_id>/notes` (lines 6698-6772)
- `/products/<product_id>/order-products` (lines 6773-6835)
- `/products/<product_id>/set-manual-priority` (lines 7015-7132)
- `/update-priority` (lines 5451-5527)
- `/priority-statistics` (lines 7133-7313)
- `/set-priority` (lines 7708-7825)
- `/recalculate-all-priorities` (lines 6896-7014)
- `/get-order-products-count/<order_number>` (lines 7826-7856)
- Helper: `_format_product_for_navigation` (lines 6836-6897)
- `/complete-task` (lines 858-974)
- `/toggle-product-done` (lines 975-1080)
- `/update-quantity-done` (lines 1081-1202)
- `/complete-packaging` (lines 2139-2374)
- `/admin/update-quantity-done` (lines 3288-3445)
- `/admin/compare-baselinker-order` (lines 3446-3502)
- `/admin/apply-baselinker-changes` (lines 3503-3573)
- `/get-cutting-progress` (lines 1203-1273)
- `/get-assembly-progress` (lines 1273-1347)

Same pattern as dashboard_api.py — import from package, copy route functions verbatim.

- [ ] **Step 2: Commit**

```bash
git add modules/production/routers/api/products_api.py
git commit -m "refactor: extract products API routes to products_api.py"
```

---

### Task 9: Split api_routers.py — reports, stations, config, sync API files

**Files:**
- Create: `modules/production/routers/api/reports_api.py`
- Create: `modules/production/routers/api/stations_api.py`
- Create: `modules/production/routers/api/config_api.py`
- Create: `modules/production/routers/api/sync_api.py`

- [ ] **Step 1: Create reports_api.py**

Move: `/reports-tab-content` (lines 3574-3764)

- [ ] **Step 2: Create stations_api.py**

Move: `/stations-tab-content` (lines 3764-3900)

- [ ] **Step 3: Create config_api.py**

Move:
- `/config-tab-content` (lines 3900-4099)
- `/update-config` (lines 1671-1771)
- `/update-configs` (lines 7314-7445)
- `/reset-configs` (lines 7514-7575)
- `/validate-config` (lines 7575-7642)
- `/config-info/<config_key>` (lines 7643-7707)
- `/get_config_days_range` (lines 5643-5716)

- [ ] **Step 4: Create sync_api.py**

Move:
- `/sync-cron` (lines 1347-1448)
- `/sync/baselinker` (lines 1448-1502)
- `/manual-sync` (lines 1503-1670)
- `/health` (lines 1953-2100)
- `/baselinker-health` (lines 1772-1906)
- `/station-health` (lines 1907-1952)
- `/baselinker_statuses` (lines 5560-5642)
- `/fetch_orders_preview` (lines 5716-5920)
- `/save_selected_orders` (lines 5921-6155)
- `/clear-cache` (lines 7446-7513)

- [ ] **Step 5: Commit**

```bash
git add modules/production/routers/api/reports_api.py modules/production/routers/api/stations_api.py modules/production/routers/api/config_api.py modules/production/routers/api/sync_api.py
git commit -m "refactor: extract reports, stations, config, sync API routes"
```

---

### Task 10: Update routers/__init__.py and delete old api_routers.py

**Files:**
- Modify: `modules/production/routers/__init__.py`
- Delete: `modules/production/routers/api_routers.py`

- [ ] **Step 1: Update imports in __init__.py**

Replace the api_bp import block (lines 49-54):

```python
# OLD:
# from .api_routers import api_bp

# NEW:
from .api import api_bp
```

- [ ] **Step 2: Delete api_routers.py**

```bash
git rm modules/production/routers/api_routers.py
```

- [ ] **Step 3: Verify the app starts**

```bash
cd C:/Users/Grafik/Desktop/Github/CRM/CRM
# Start the Flask app and check for import errors
python -c "from modules.production.routers import api_bp; print('OK:', api_bp.name)"
```

Expected output: `OK: production_api`

- [ ] **Step 4: Commit**

```bash
git add modules/production/routers/__init__.py
git commit -m "refactor: wire up api/ sub-package, delete monolithic api_routers.py"
```

---

### Task 11: Manual testing and final verification

- [ ] **Step 1: Start the app locally**

```bash
cd C:/Users/Grafik/Desktop/Github/CRM/CRM
python -m flask run --host=127.0.0.1 --port=5000
```

- [ ] **Step 2: Test tab loading**

Open http://127.0.0.1:5000/production/ and verify:
- Skeletons appear immediately for Dashboard
- Dashboard content replaces skeleton with fade-in
- Products tab loads in background (switch to it — should be instant)
- Reports/Stations/Config show spinner on first click, then cached

- [ ] **Step 3: Test URL sync**

- Click Products tab → URL should show `?tab=products`
- Press F5 → should land on Products tab directly
- Click Dashboard → URL should drop the `?tab` param
- Navigate to `?tab=reports` manually → should open Reports tab

- [ ] **Step 4: Test refresh**

- Click the refresh button (right of tabs) → icon spins, active tab refreshes
- Wait 60s → auto-refresh should fire
- Switch tabs → auto-refresh timer continues (doesn't reset/stop)

- [ ] **Step 5: Test sync date coloring**

- On Dashboard, check "Status systemu" → "Sync BaseLinker" row
- Date should be colored: green (<24h), yellow (24-48h), or red (>48h)

- [ ] **Step 6: Verify old elements are gone**

- No `<h1>` visible
- No "Synchronizacja przestarzała" banner
- No "Odśwież system" button with countdown timer
- No `.user-greeting` section

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "fix: post-review adjustments from manual testing"
```
