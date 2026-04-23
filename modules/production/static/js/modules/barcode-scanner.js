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
        showLoading();
        document.addEventListener('click', onDismissClick);

        // placeholder - kolejne taski: ładowanie ZXing, kamera, dekodowanie
        // na razie po 1.5s chowamy loading, żeby zobaczyć modal
        setTimeout(hideStates, 1500);
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

    window.BarcodeScanner = { open: open, close: close };
})();
