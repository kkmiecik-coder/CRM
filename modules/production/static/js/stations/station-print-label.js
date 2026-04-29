/**
 * Drukowanie etykiet produkcyjnych — handler dla stanowisk formatowanie/pakowanie.
 *
 * Buttony renderowane przez stations/_print_label_button.html z atrybutami:
 *   data-mode="single"   data-product-id="..."   data-station="..."
 *   data-mode="batch"    data-order-id="..."     data-station="..."
 */
(function () {
    'use strict';

    function notify(message, type) {
        if (window.showToast) {
            window.showToast(message, type || 'info');
            return;
        }
        if (window.toastr && typeof window.toastr[type || 'info'] === 'function') {
            window.toastr[type || 'info'](message);
            return;
        }
        console[(type === 'error') ? 'error' : 'log']('[print-label]', message);
        if (type === 'error') alert(message);
    }

    function endpointFor(btn) {
        if (btn.dataset.mode === 'batch') {
            return '/production/stations/ajax/print-labels-for-order/' + encodeURIComponent(btn.dataset.orderId);
        }
        return '/production/stations/ajax/print-label/' + encodeURIComponent(btn.dataset.productId);
    }

    async function handleClick(btn) {
        if (btn.classList.contains('is-loading') || btn.disabled) return;
        const station = btn.dataset.station;
        if (!station) {
            notify('Brak parametru station_code w przycisku.', 'error');
            return;
        }

        btn.classList.add('is-loading');
        btn.disabled = true;
        try {
            const resp = await fetch(endpointFor(btn), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ station_code: station }),
            });
            const data = await resp.json().catch(() => ({}));

            if (resp.status === 502 || data.connection_error) {
                notify(data.message || 'Drukarka offline — sprawdź zasilanie/kabel.', 'error');
                return;
            }
            if (resp.status === 403) {
                notify(data.message || 'Stanowisko nie ma uprawnień do drukowania.', 'error');
                return;
            }
            if (!resp.ok) {
                notify(data.message || ('Błąd HTTP ' + resp.status), 'error');
                return;
            }

            if (data.success) {
                notify(data.message || 'Wysłano do drukarki.', 'success');
            } else if (data.success_count && data.success_count > 0) {
                notify(data.message || ('Wydrukowano ' + data.success_count + '/' + (data.success_count + data.failed_count) + ' etykiet.'), 'warning');
            } else {
                notify(data.message || 'Nie udało się wydrukować etykiet.', 'error');
            }

            if (btn.dataset.mode === 'single' && data.success && data.results && data.results[0]) {
                const newCount = data.results[0].label_print_count;
                let badge = btn.querySelector('.station-print-label-badge');
                if (!badge && newCount > 0) {
                    badge = document.createElement('span');
                    badge.className = 'station-print-label-badge';
                    btn.appendChild(badge);
                }
                if (badge) badge.textContent = String(newCount);
            }
        } catch (err) {
            console.error('[print-label] fetch failed', err);
            notify('Błąd komunikacji z serwerem.', 'error');
        } finally {
            btn.classList.remove('is-loading');
            btn.disabled = false;
        }
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.station-print-label-btn');
        if (!btn) return;
        e.preventDefault();
        handleClick(btn);
    });
})();
