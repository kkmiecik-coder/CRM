/**
 * Drukowanie etykiet produkcyjnych — handler dla stanowisk formatting/packaging.
 *
 * Buttony renderowane przez stations/_print_label_button.html z atrybutami:
 *   data-mode="single"   data-product-id="..."   data-station="..."
 *   data-mode="batch"    data-order-id="..."     data-station="..."
 *
 * Tryby:
 *  1) TCP direct (LABEL_PRINTER_USE_AGENT=false): backend zwraca finalny status.
 *     Toast jednorazowy, ikona resetuje się od razu.
 *  2) Queue + agent (LABEL_PRINTER_USE_AGENT=true): backend zwraca queue_job_ids.
 *     Frontend pollu je /print-job-status co 2s aż status != pending. UI aktualnie:
 *       pending  → ikona zegar, button disabled, tooltip "W kolejce"
 *       printed  → ikona check zielony, toast "Wydrukowano", po 4s reset
 *       failed/expired → ikona ✗ czerwony, toast błędu, po 4s reset
 */
(function () {
    'use strict';

    const POLL_INTERVAL_MS = 2000;
    const POLL_TIMEOUT_MS = 90000;  // 90s — po tym oddajemy
    const RESET_DELAY_MS = 4000;

    const SVG_PRINTER = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z"/></svg>';
    const SVG_CLOCK = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>';
    const SVG_CHECK = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
    const SVG_CROSS = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>';

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

    function setIcon(btn, kind) {
        const map = { printer: SVG_PRINTER, clock: SVG_CLOCK, check: SVG_CHECK, cross: SVG_CROSS };
        // Zachowaj batch text (jeśli jest) — partial dodaje go po SVG dla mode=batch
        const existingText = btn.querySelector('.station-print-label-text');
        const textHtml = existingText ? existingText.outerHTML : '';
        btn.innerHTML = (map[kind] || SVG_PRINTER) + textHtml;
    }

    function setState(btn, state) {
        // states: idle | sending | queued | printed | failed
        btn.classList.remove('is-loading', 'state-queued', 'state-printed', 'state-failed');
        if (state === 'sending') {
            btn.classList.add('is-loading');
            btn.disabled = true;
            setIcon(btn, 'printer');
        } else if (state === 'queued') {
            btn.classList.add('state-queued');
            btn.disabled = true;
            setIcon(btn, 'clock');
            btn.title = 'W kolejce — drukowanie za chwilę...';
        } else if (state === 'printed') {
            btn.classList.add('state-printed');
            btn.disabled = true;
            setIcon(btn, 'check');
            btn.title = 'Wydrukowano';
        } else if (state === 'failed') {
            btn.classList.add('state-failed');
            btn.disabled = true;
            setIcon(btn, 'cross');
            btn.title = 'Błąd drukowania';
        } else {
            btn.disabled = false;
            setIcon(btn, 'printer');
            btn.title = btn.dataset.mode === 'batch'
                ? 'Drukuj etykiety wszystkich produktów z zamówienia'
                : 'Drukuj etykietę produktu';
        }
    }

    function resetAfterDelay(btn, ms) {
        setTimeout(() => setState(btn, 'idle'), ms);
    }

    async function pollStatus(btn, queueIds, totalCount) {
        const ids = queueIds.slice();
        const startedAt = Date.now();
        let printed = 0;
        let failed = 0;

        while (ids.length > 0) {
            if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
                notify('Drukowanie trwa nietypowo długo. Sprawdź drukarkę i logi agenta.', 'warning');
                setState(btn, 'failed');
                resetAfterDelay(btn, RESET_DELAY_MS);
                return;
            }

            await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));

            try {
                const url = '/production/stations/ajax/print-job-status?ids=' + ids.join(',');
                const resp = await fetch(url, { credentials: 'same-origin' });
                if (!resp.ok) continue;
                const data = await resp.json();
                const jobs = data.jobs || [];

                for (const j of jobs) {
                    if (j.status === 'printed') {
                        printed++;
                        const idx = ids.indexOf(j.id);
                        if (idx >= 0) ids.splice(idx, 1);
                    } else if (j.status === 'failed' || j.status === 'expired') {
                        failed++;
                        const idx = ids.indexOf(j.id);
                        if (idx >= 0) ids.splice(idx, 1);
                    }
                }
            } catch (e) {
                console.warn('[print-label] poll failed', e);
            }
        }

        // Wszystkie zadania doszły do końcowego statusu
        if (failed === 0) {
            const msg = totalCount === 1 ? 'Wydrukowano etykietę.' : `Wydrukowano ${printed} etykiet.`;
            notify(msg, 'success');
            setState(btn, 'printed');
        } else if (printed > 0) {
            notify(`Wydrukowano ${printed}/${totalCount} — ${failed} nieudanych. Sprawdź logi agenta.`, 'warning');
            setState(btn, 'failed');
        } else {
            notify('Nie udało się wydrukować. Sprawdź drukarkę i logi agenta.', 'error');
            setState(btn, 'failed');
        }
        resetAfterDelay(btn, RESET_DELAY_MS);
    }

    async function handleClick(btn) {
        if (btn.classList.contains('is-loading') || btn.disabled) return;
        const station = btn.dataset.station;
        if (!station) {
            notify('Brak parametru station_code w przycisku.', 'error');
            return;
        }

        setState(btn, 'sending');
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
                setState(btn, 'failed');
                resetAfterDelay(btn, RESET_DELAY_MS);
                return;
            }
            if (resp.status === 403) {
                notify(data.message || 'Stanowisko nie ma uprawnień do drukowania.', 'error');
                setState(btn, 'idle');
                return;
            }
            if (!resp.ok) {
                notify(data.message || ('Błąd HTTP ' + resp.status), 'error');
                setState(btn, 'failed');
                resetAfterDelay(btn, RESET_DELAY_MS);
                return;
            }

            // Wyciągnij queue_job_ids z results (tryb agent) — N rekordów per pozycja
            // (1 job per sztukę quantity). Backward-compat: gdy serwer zwraca tylko
            // queue_job_id (pojedynczy), traktujemy go jak jednoelementową listę.
            const results = Array.isArray(data.results) ? data.results : [];
            const queueIds = results
                .filter(r => r && r.success)
                .flatMap(r => {
                    if (Array.isArray(r.queue_job_ids)) {
                        return r.queue_job_ids.filter(id => typeof id === 'number');
                    }
                    return typeof r.queue_job_id === 'number' ? [r.queue_job_id] : [];
                });

            if (queueIds.length > 0) {
                // Tryb queue — pollu jemy do skutku. Liczymy etykiety (sztuki),
                // nie pozycje: 1 queue_job = 1 etykieta = 1 sztuka quantity.
                const total = data.total_labels || queueIds.length;
                notify(total === 1 ? 'Wysłano do drukarki — drukowanie w toku...' : `Wysłano ${total} etykiet — drukowanie w toku...`, 'info');
                setState(btn, 'queued');
                pollStatus(btn, queueIds, total);
                return;
            }

            // Tryb TCP direct — finalny status już mamy
            if (data.success) {
                notify(data.message || 'Wydrukowano.', 'success');
                setState(btn, 'printed');
                resetAfterDelay(btn, RESET_DELAY_MS);
            } else if (data.success_count && data.success_count > 0) {
                notify(data.message || `Wydrukowano ${data.success_count}/${data.success_count + data.failed_count}.`, 'warning');
                setState(btn, 'failed');
                resetAfterDelay(btn, RESET_DELAY_MS);
            } else {
                notify(data.message || 'Nie udało się wydrukować etykiet.', 'error');
                setState(btn, 'failed');
                resetAfterDelay(btn, RESET_DELAY_MS);
            }
        } catch (err) {
            console.error('[print-label] fetch failed', err);
            notify('Błąd komunikacji z serwerem.', 'error');
            setState(btn, 'failed');
            resetAfterDelay(btn, RESET_DELAY_MS);
        }
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.station-print-label-btn');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        handleClick(btn);
    });
})();
