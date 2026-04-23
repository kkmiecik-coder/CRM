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
        stream: null,
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

    function hasMediaDevices() {
        return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    }

    async function startCamera() {
        const video = el('il-scanner-video');
        const constraints = { video: { facingMode: { ideal: 'environment' } }, audio: false };
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        state.stream = stream;
        video.srcObject = stream;
        try { await video.play(); } catch (e) { /* autoplay czasem wymaga interakcji */ }
        return stream;
    }

    function stopCamera() {
        if (state.stream) {
            state.stream.getTracks().forEach(function (t) { t.stop(); });
            state.stream = null;
        }
        const video = el('il-scanner-video');
        if (video) video.srcObject = null;
    }

    function mapCameraError(err) {
        const name = err && err.name;
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
            return 'Brak dostępu do kamery. Zezwól w ustawieniach przeglądarki.';
        }
        if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
            return 'Nie wykryto kamery.';
        }
        if (name === 'NotReadableError' || name === 'TrackStartError') {
            return 'Kamera jest zajęta przez inną aplikację.';
        }
        if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
            return 'Żądane parametry kamery nie są obsługiwane.';
        }
        if (name === 'SecurityError') {
            return 'Skaner wymaga bezpiecznego połączenia (HTTPS).';
        }
        return 'Nie udało się uruchomić kamery.';
    }

    // Uruchamia pełną sekwencję: loading UI → ładowanie ZXing → start kamery → sukces/błąd.
    // Task 8 doda tu dekodowanie — zawsze w jednym miejscu.
    function attemptLoad(errorLogLabel) {
        showLoading();
        return loadZXing()
            .then(function (zxing) {
                if (!state.isOpen) return null;
                console.log('[BarcodeScanner] ZXing załadowany');
                return startCamera();
            })
            .then(function (stream) {
                if (!state.isOpen || !stream) return;
                hideStates();
                // placeholder - Task 8 doda tu start dekodowania
            })
            .catch(function (err) {
                if (!state.isOpen) return;
                console.error('[BarcodeScanner] ' + errorLogLabel + ':', err);
                // Rozrozniamy: blad CDN (brak zxingPromise po reset) vs blad kamery
                const isCameraError = err && err.name && (
                    err.name === 'NotAllowedError' ||
                    err.name === 'PermissionDeniedError' ||
                    err.name === 'NotFoundError' ||
                    err.name === 'DevicesNotFoundError' ||
                    err.name === 'NotReadableError' ||
                    err.name === 'TrackStartError' ||
                    err.name === 'OverconstrainedError' ||
                    err.name === 'ConstraintNotSatisfiedError' ||
                    err.name === 'AbortError' ||
                    err.name === 'SecurityError'
                );
                if (isCameraError) {
                    showError(mapCameraError(err), false);
                } else {
                    showError(SCANNER_LOAD_ERROR_MSG, true);
                }
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

        if (!hasMediaDevices()) {
            showError('Twoja przeglądarka nie obsługuje skanera. Wpisz numer ręcznie.', false);
            return;
        }

        attemptLoad('Błąd ładowania ZXing');
    }

    function close() {
        if (!state.isOpen) return;
        state.isOpen = false;
        state.onResult = null;
        stopCamera();
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
