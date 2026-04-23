/**
 * barcode-scanner.js
 * ========================================================================
 *
 * Moduł skanera kodów kreskowych dla zakładki Produkty.
 *
 * API:
 *   window.BarcodeScanner.open(onResult) - otwiera modal, po skanie wywołuje callback
 *   window.BarcodeScanner.close()        - programowe zamknięcie modalu
 *
 * Wykorzystuje @zxing/browser z CDN (lazy load przy pierwszym open).
 */

(function () {
    'use strict';

    const SCAN_REGEX = /^\d{6,12}$/;

    const ZXING_CDN = 'https://cdn.jsdelivr.net/npm/@zxing/browser@0.1.5/+esm';

    const SCANNER_LOAD_ERROR_MSG = 'Nie udało się załadować skanera. Sprawdź połączenie.';

    let zxingPromise = null;

    function loadZXing() {
        if (zxingPromise) return zxingPromise;
        zxingPromise = import(ZXING_CDN).catch(function (err) {
            zxingPromise = null;
            throw err;
        });
        return zxingPromise;
    }

    const state = {
        isOpen: false,
        onResult: null,
        dismissHandler: null,
    };

    function el(id) {
        return document.getElementById(id);
    }

    function showLoading() {
        el('il-scanner-loading').hidden = false;
        el('il-scanner-error').hidden = true;
    }

    function showError(message, withRetry) {
        el('il-scanner-loading').hidden = true;
        const errorBox = el('il-scanner-error');
        el('il-scanner-error-message').textContent = message;
        el('il-scanner-retry').hidden = !withRetry;
        errorBox.hidden = false;
    }

    function hideStates() {
        el('il-scanner-loading').hidden = true;
        el('il-scanner-error').hidden = true;
    }

    // Uruchamia pełną sekwencję: loading UI → ładowanie ZXing → sukces/błąd.
    // Task 7 doda tu start kamery, Task 8 dekodowanie — zawsze w jednym miejscu.
    function attemptLoad(errorLogLabel) {
        showLoading();
        return loadZXing()
            .then(function (zxing) {
                if (!state.isOpen) return;
                console.log('[BarcodeScanner] ZXing załadowany');
                hideStates();
                // placeholder - Task 7 doda tu start kamery
            })
            .catch(function (err) {
                if (!state.isOpen) return;
                console.error('[BarcodeScanner] ' + errorLogLabel + ':', err);
                showError(SCANNER_LOAD_ERROR_MSG, true);
            });
    }

    function onDismissClick(e) {
        const target = e.target;
        if (target && target.closest && target.closest('[data-scanner-dismiss]')) {
            close();
        }
    }

    function open(onResult) {
        if (state.isOpen) return;
        state.isOpen = true;
        state.onResult = typeof onResult === 'function' ? onResult : null;

        const modal = el('il-barcode-scanner-modal');
        modal.removeAttribute('hidden');
        document.addEventListener('click', onDismissClick);

        attemptLoad('Błąd ładowania ZXing');
    }

    function close() {
        if (!state.isOpen) return;
        state.isOpen = false;
        state.onResult = null;
        document.removeEventListener('click', onDismissClick);

        const modal = el('il-barcode-scanner-modal');
        modal.setAttribute('hidden', '');
        hideStates();
    }

    document.addEventListener('click', function (e) {
        if (e.target && e.target.closest && e.target.closest('#il-scanner-retry')) {
            if (!state.isOpen) return;
            attemptLoad('Retry błąd');
        }
    });

    window.BarcodeScanner = { open: open, close: close };
})();
