/**
 * Trakownia — logika zakładki panelu produkcji.
 * static/js/sawmill.js
 *
 * Ten plik jest wstrzykiwany razem z fragmentem tab_content.html (tag
 * <script src="..."> na końcu szablonu). production-app-loader.js ustawia
 * innerHTML kontenera #sawmill-tab-content, a potem "odtwarza" tag <script>
 * (innerHTML sam z siebie nie wykonuje <script>), więc w chwili uruchomienia
 * tego pliku cały DOM zakładki (tabela, filtry, modale) już istnieje —
 * dlatego kod inicjalizuje się od razu na dole pliku, bez czekania na
 * DOMContentLoaded (ten event już dawno minął przy pierwszym ładowaniu strony).
 *
 * Całość zamknięta w IIFE, żeby ponowne wstrzyknięcie tego pliku (np. po
 * ProductionApp.forceRefresh()) nie kolidowało z poprzednią instancją
 * zmiennych najwyższego poziomu (redeklaracja `const` w tym samym zasięgu
 * globalnym rzuciłaby SyntaxError).
 */
(function () {
    'use strict';

    var API = '/production/api/sawmill';

    var STATUS_LABELS = {
        new: 'Nowe',
        in_progress: 'W trakcie',
        completed: 'Zakończone',
        settled: 'Rozliczone',
    };

    // Stan modułu — cache ostatnio wczytanej listy i aktualnie otwartego
    // zlecenia, żeby akcje (rozlicz/wznów/edycja pomiaru) mogły odświeżyć
    // widok bez zbędnych dodatkowych zapytań.
    var state = {
        lastOrders: {},
        currentOrder: null,
        dictType: null,
        speciesOptionsHtml: '',
    };

    function el(id) {
        return document.getElementById(id);
    }

    // ── Formatowanie ────────────────────────────────────────────────────────

    function formatNum(value, decimals) {
        if (value === null || value === undefined || value === '') return '—';
        var num = Number(value);
        if (isNaN(num)) return '—';
        return num.toFixed(decimals);
    }

    function formatSigned(value, decimals) {
        if (value === null || value === undefined || value === '') return '—';
        var num = Number(value);
        if (isNaN(num)) return '—';
        var sign = num > 0 ? '+' : '';
        return sign + num.toFixed(decimals);
    }

    function formatDate(iso) {
        if (!iso) return '—';
        var parts = iso.split('-');
        if (parts.length !== 3) return iso;
        return parts[2] + '.' + parts[1] + '.' + parts[0];
    }

    function formatDateTime(iso) {
        if (!iso) return '—';
        return iso.replace('T', ' ');
    }

    function statusLabel(status) {
        return STATUS_LABELS[status] || status;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // Klasa komórki różnicy — kolor wg znaku, flaga wg przekroczenia progu.
    // Nigdy symbol Δ, tylko kolor/flaga — patrz sawmill.css.
    function diffClass(value, isDeviation) {
        if (value === null || value === undefined) return '';
        var num = Number(value);
        var cls = '';
        if (num < 0) cls = 'sawmill-diff-negative';
        else if (num > 0) cls = 'sawmill-diff-positive';
        if (isDeviation) cls += ' sawmill-diff-flag';
        return cls.trim();
    }

    function toast(message, type) {
        if (window.ProductionShared && window.ProductionShared.toastSystem) {
            window.ProductionShared.toastSystem.show(message, type);
        } else {
            // Fallback, gdyby shared-services.js jeszcze się nie załadował.
            console.warn('[Sawmill] toastSystem niedostępny:', message);
        }
    }

    function highlightField(fieldName) {
        if (!fieldName) return;
        var fields = document.querySelectorAll('[data-field="' + fieldName + '"]');
        fields.forEach(function (f) {
            f.classList.add('is-invalid');
            setTimeout(function () { f.classList.remove('is-invalid'); }, 4000);
        });
    }

    // Wspólna obsługa błędów API — dokładnie wg wymagań z briefu:
    // 409 → komunikat z pola detail, 422 → podświetlenie pola z field,
    // 403 → informacja o braku dostępu do modułu.
    function handleErrorResponse(resp, formErrorEl) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
            var message;
            if (resp.status === 403) {
                message = 'Brak dostępu do modułu produkcji';
            } else if (resp.status === 409) {
                message = body.detail || 'Operacja niemożliwa w bieżącym stanie zlecenia';
            } else if (resp.status === 422) {
                message = body.detail || 'Błąd walidacji';
                highlightField(body.field);
            } else if (resp.status === 401) {
                message = 'Sesja wygasła — zaloguj się ponownie';
            } else {
                message = 'Błąd serwera (HTTP ' + resp.status + ')';
            }
            toast(message, 'error');
            if (formErrorEl) {
                formErrorEl.textContent = message;
                formErrorEl.style.display = 'block';
            }
            return body;
        });
    }

    // ── Filtry i lista zleceń ───────────────────────────────────────────────

    function currentFilters() {
        var params = {};
        var status = el('sawmill-filter-status').value;
        if (status) params.status = status;
        var supplier = el('sawmill-filter-supplier').value;
        if (supplier) params.supplier_id = supplier;
        var species = el('sawmill-filter-species').value;
        if (species) params.species_id = species;
        var dateFrom = el('sawmill-filter-date-from').value;
        if (dateFrom) params.date_from = dateFrom;
        var dateTo = el('sawmill-filter-date-to').value;
        if (dateTo) params.date_to = dateTo;
        var q = el('sawmill-filter-q').value.trim();
        if (q) params.q = q;
        if (el('sawmill-filter-only-deviation').checked) params.only_deviation = '1';
        return params;
    }

    function emptyRowHtml(message) {
        return '<tr><td colspan="13" class="text-center text-muted py-4">' + escapeHtml(message) + '</td></tr>';
    }

    function actionButtonsHtml(o) {
        var html = '';
        if (o.status === 'completed') {
            html += '<button type="button" class="btn btn-sm btn-outline-primary" ' +
                'onclick="Sawmill.openSettleModal(' + o.id + ')" title="Rozlicz">' +
                '<i class="fas fa-check-circle"></i></button>';
            html += '<button type="button" class="btn btn-sm btn-outline-secondary" ' +
                'onclick="Sawmill.reopenOrder(' + o.id + ')" title="Wznów">' +
                '<i class="fas fa-undo"></i></button>';
        } else if (o.status === 'settled') {
            html += '<button type="button" class="btn btn-sm btn-outline-warning" ' +
                'onclick="Sawmill.unsettleOrder(' + o.id + ')" title="Cofnij rozliczenie">' +
                '<i class="fas fa-rotate-left"></i></button>';
        }
        if (!o.logs_count) {
            html += '<button type="button" class="btn btn-sm btn-outline-danger" ' +
                'onclick="Sawmill.deleteOrder(' + o.id + ')" title="Usuń zlecenie">' +
                '<i class="fas fa-trash"></i></button>';
        }
        return html;
    }

    function renderOrderRow(o) {
        var flagIcon = o.is_deviation
            ? '<i class="fas fa-flag sawmill-flag-icon" title="Odchylenie powyżej progu"></i>'
            : '';
        return (
            '<tr data-order-id="' + o.id + '">' +
            '<td>' + escapeHtml(o.order_number) + '</td>' +
            '<td>' + escapeHtml(o.supplier_name || '—') + '</td>' +
            '<td>' + escapeHtml(o.invoice_number || '—') + '</td>' +
            '<td>' + formatDate(o.delivery_date) + '</td>' +
            '<td>' + escapeHtml(o.species || '—') + '</td>' +
            '<td>' + formatNum(o.declared_volume_m3, 3) + '</td>' +
            '<td>' + formatNum(o.measured_volume_m3, 3) + '</td>' +
            '<td class="' + diffClass(o.difference_m3, o.is_deviation) + '">' + flagIcon + formatSigned(o.difference_m3, 3) + '</td>' +
            '<td class="' + diffClass(o.difference_pct, o.is_deviation) + '">' + formatSigned(o.difference_pct, 2) + '%</td>' +
            '<td class="' + diffClass(o.difference_value, o.is_deviation) + '">' + formatSigned(o.difference_value, 2) + ' zł</td>' +
            '<td>' + o.logs_count + '</td>' +
            '<td><span class="badge sawmill-status-badge sawmill-status-' + o.status + '">' + statusLabel(o.status) + '</span></td>' +
            '<td class="sawmill-actions">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" onclick="Sawmill.openDetails(' + o.id + ')" title="Szczegóły">' +
            '<i class="fas fa-eye"></i></button>' +
            actionButtonsHtml(o) +
            '</td>' +
            '</tr>'
        );
    }

    function loadOrders() {
        var tbody = el('sawmill-orders-tbody');
        tbody.innerHTML = emptyRowHtml('Ładowanie...');

        var params = new URLSearchParams(currentFilters());
        return fetch(API + '/orders?' + params.toString(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (resp) {
            if (!resp.ok) {
                return handleErrorResponse(resp).then(function () {
                    tbody.innerHTML = emptyRowHtml('Błąd ładowania listy');
                });
            }
            return resp.json().then(function (data) {
                state.lastOrders = {};
                data.orders.forEach(function (o) { state.lastOrders[o.id] = o; });
                if (data.orders.length === 0) {
                    tbody.innerHTML = emptyRowHtml('Brak dostaw spełniających kryteria');
                    return;
                }
                tbody.innerHTML = data.orders.map(renderOrderRow).join('');
            });
        }).catch(function (err) {
            console.error('[Sawmill] Błąd ładowania listy zleceń:', err);
            tbody.innerHTML = emptyRowHtml('Błąd połączenia z serwerem');
        });
    }

    // ── Słowniki (gatunki / dostawcy) — odświeżanie select-ów ──────────────

    function setOptionsKeepingPlaceholder(selectId, optionsHtml) {
        var select = el(selectId);
        if (!select) return;
        var placeholder = select.options.length ? select.options[0].outerHTML : '';
        select.innerHTML = placeholder + optionsHtml;
    }

    function seedSpeciesOptionsFromDOM() {
        // Zanim pierwsze zapytanie do /species wróci, nowe wiersze pozycji
        // muszą już mieć listę gatunków — bierzemy ją z pierwszego, wyrenderowanego
        // przez Jinja wiersza (pomijamy jego placeholder "— wybierz —").
        var firstSelect = document.querySelector('#sawmill-delivery-items .sawmill-item-species');
        if (!firstSelect) return;
        state.speciesOptionsHtml = Array.prototype.slice.call(firstSelect.options, 1)
            .map(function (o) { return o.outerHTML; }).join('');
    }

    function loadSpeciesOptions() {
        return fetch(API + '/species', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (data) {
                if (!data) return;
                var options = data.species.map(function (s) {
                    return '<option value="' + s.id + '">' + escapeHtml(s.name) + '</option>';
                }).join('');
                state.speciesOptionsHtml = options;
                setOptionsKeepingPlaceholder('sawmill-filter-species', options);
            }).catch(function (err) { console.error('[Sawmill] Błąd pobierania gatunków:', err); });
    }

    function loadSupplierOptions() {
        return fetch(API + '/suppliers', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (data) {
                if (!data) return;
                var options = data.suppliers.map(function (s) {
                    return '<option value="' + s.id + '">' + escapeHtml(s.name) + '</option>';
                }).join('');
                setOptionsKeepingPlaceholder('sawmill-filter-supplier', options);
                setOptionsKeepingPlaceholder('sawmill-delivery-supplier', options);
            }).catch(function (err) { console.error('[Sawmill] Błąd pobierania dostawców:', err); });
    }

    function refreshDictOptions() {
        return Promise.all([loadSpeciesOptions(), loadSupplierOptions()]);
    }

    // ── Modal: Nowa dostawa ─────────────────────────────────────────────────

    function todayISO() {
        var d = new Date();
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        var dd = String(d.getDate()).padStart(2, '0');
        return d.getFullYear() + '-' + mm + '-' + dd;
    }

    function buildItemRow() {
        var row = document.createElement('div');
        row.className = 'sawmill-item-row row g-2 align-items-end mb-2';
        row.innerHTML =
            '<div class="col-md-4">' +
            '<label class="form-label">Gatunek</label>' +
            '<select class="form-select sawmill-item-species" data-field="species_id" required>' +
            '<option value="">— wybierz —</option>' + state.speciesOptionsHtml +
            '</select></div>' +
            '<div class="col-md-3">' +
            '<label class="form-label">Deklarowana obj. m³</label>' +
            '<input type="number" step="0.001" min="0" class="form-control sawmill-item-declared-volume" ' +
            'data-field="declared_volume_m3" required></div>' +
            '<div class="col-md-2">' +
            '<label class="form-label">Liczba kłód</label>' +
            '<input type="number" step="1" min="0" class="form-control sawmill-item-logs-count"></div>' +
            '<div class="col-md-2">' +
            '<label class="form-label">Cena/m³</label>' +
            '<input type="number" step="0.01" min="0" class="form-control sawmill-item-price" data-field="price_per_m3"></div>' +
            '<div class="col-md-1 text-end"><span class="sawmill-item-value-preview text-muted small">— zł</span></div>' +
            '<div class="col-12">' +
            '<button type="button" class="btn btn-sm btn-outline-danger sawmill-item-remove" ' +
            'onclick="Sawmill.removeItemRow(this)"><i class="fas fa-trash"></i> Usuń pozycję</button></div>';

        bindItemRowPreview(row);
        return row;
    }

    function bindItemRowPreview(row) {
        var volumeInput = row.querySelector('.sawmill-item-declared-volume');
        var priceInput = row.querySelector('.sawmill-item-price');
        volumeInput.addEventListener('input', function () { updateItemPreview(row); });
        priceInput.addEventListener('input', function () { updateItemPreview(row); });
    }

    function updateItemPreview(row) {
        // Podgląd wyłącznie orientacyjny — serwer i tak przelicza wartość
        // pozycji sam (declared_volume_m3 * price_per_m3), zgodnie z briefem.
        var declared = parseFloat(row.querySelector('.sawmill-item-declared-volume').value);
        var price = parseFloat(row.querySelector('.sawmill-item-price').value);
        var preview = row.querySelector('.sawmill-item-value-preview');
        if (!isNaN(declared) && !isNaN(price)) {
            preview.textContent = (declared * price).toFixed(2) + ' zł';
        } else {
            preview.textContent = '— zł';
        }
    }

    function updateRemoveButtonsVisibility() {
        var rows = el('sawmill-delivery-items').querySelectorAll('.sawmill-item-row');
        rows.forEach(function (r) {
            var btn = r.querySelector('.sawmill-item-remove');
            if (btn) btn.style.display = rows.length > 1 ? '' : 'none';
        });
    }

    function addItemRow() {
        el('sawmill-delivery-items').appendChild(buildItemRow());
        updateRemoveButtonsVisibility();
    }

    function removeItemRow(button) {
        var container = el('sawmill-delivery-items');
        // Zawsze musi zostać przynajmniej jedna pozycja — patrz walidacja w submitDelivery().
        if (container.querySelectorAll('.sawmill-item-row').length <= 1) return;
        var row = button.closest('.sawmill-item-row');
        if (row) row.remove();
        updateRemoveButtonsVisibility();
    }

    function clearValidationState() {
        document.querySelectorAll('#sawmillDeliveryModal .is-invalid').forEach(function (f) {
            f.classList.remove('is-invalid');
        });
        el('sawmill-delivery-form-error').style.display = 'none';
    }

    function resetDeliveryForm() {
        clearValidationState();
        el('sawmill-delivery-supplier').value = '';
        el('sawmill-delivery-date').value = todayISO();
        el('sawmill-invoice-number').value = '';
        el('sawmill-invoice-date').value = ''; // faktura NIE jest domyślnie wypełniana — patrz brief
        el('sawmill-delivery-notes').value = '';

        var itemsContainer = el('sawmill-delivery-items');
        itemsContainer.innerHTML = '';
        itemsContainer.appendChild(buildItemRow());
        updateRemoveButtonsVisibility();
    }

    function openDeliveryModal() {
        resetDeliveryForm();
        bootstrap.Modal.getOrCreateInstance(el('sawmillDeliveryModal')).show();
    }

    // Walidacja po stronie przeglądarki: minimum jedna pozycja, każda
    // z gatunkiem i deklarowaną objętością. Serwer i tak sprawdza to samo
    // ponownie (patrz PanelValidationError w panel_api.py) — to tylko
    // szybki feedback bez zbędnego zapytania.
    function collectDeliveryItems() {
        var rows = el('sawmill-delivery-items').querySelectorAll('.sawmill-item-row');
        var items = [];
        var valid = true;

        rows.forEach(function (row) {
            var speciesSelect = row.querySelector('.sawmill-item-species');
            var volumeInput = row.querySelector('.sawmill-item-declared-volume');
            var logsInput = row.querySelector('.sawmill-item-logs-count');
            var priceInput = row.querySelector('.sawmill-item-price');

            speciesSelect.classList.remove('is-invalid');
            volumeInput.classList.remove('is-invalid');

            var speciesId = speciesSelect.value;
            var volume = parseFloat(volumeInput.value);

            if (!speciesId) { speciesSelect.classList.add('is-invalid'); valid = false; }
            if (!volumeInput.value || isNaN(volume) || volume <= 0) {
                volumeInput.classList.add('is-invalid');
                valid = false;
            }

            items.push({
                species_id: speciesId ? parseInt(speciesId, 10) : null,
                declared_volume_m3: volumeInput.value || null,
                declared_logs_count: logsInput.value ? parseInt(logsInput.value, 10) : null,
                price_per_m3: priceInput.value || null,
            });
        });

        return { items: items, valid: valid };
    }

    function submitDelivery() {
        var errorEl = el('sawmill-delivery-form-error');
        errorEl.style.display = 'none';
        document.querySelectorAll('#sawmillDeliveryModal .is-invalid').forEach(function (f) {
            f.classList.remove('is-invalid');
        });

        var supplierId = el('sawmill-delivery-supplier').value;
        var deliveryDate = el('sawmill-delivery-date').value;
        var collected = collectDeliveryItems();

        if (!supplierId) {
            el('sawmill-delivery-supplier').classList.add('is-invalid');
            errorEl.textContent = 'Wybierz dostawcę.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }
        if (!deliveryDate) {
            el('sawmill-delivery-date').classList.add('is-invalid');
            errorEl.textContent = 'Podaj datę dostawy.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }
        if (collected.items.length === 0 || !collected.valid) {
            errorEl.textContent = 'Dodaj co najmniej jedną pozycję z gatunkiem i deklarowaną objętością.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }

        var payload = {
            supplier_id: parseInt(supplierId, 10),
            invoice_number: el('sawmill-invoice-number').value || null,
            invoice_date: el('sawmill-invoice-date').value || null,
            delivery_date: deliveryDate,
            notes: el('sawmill-delivery-notes').value || null,
            items: collected.items,
        };

        var submitBtn = el('sawmill-btn-submit-delivery');
        submitBtn.disabled = true;

        return fetch(API + '/deliveries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            return resp.json().then(function (data) {
                var numbers = data.orders.map(function (o) { return o.order_number; }).join(', ');
                toast('Zapisano dostawę — utworzono zlecenia: ' + numbers, 'success');
                bootstrap.Modal.getOrCreateInstance(el('sawmillDeliveryModal')).hide();
                return loadOrders();
            });
        }).catch(function (err) {
            console.error('[Sawmill] Błąd zapisu dostawy:', err);
            errorEl.textContent = 'Błąd połączenia z serwerem.';
            errorEl.style.display = 'block';
        }).finally(function () {
            submitBtn.disabled = false;
        });
    }

    // ── Modal: Szczegóły zlecenia ────────────────────────────────────────────

    function renderLogRow(l) {
        return (
            '<tr data-log-id="' + l.id + '">' +
            '<td>' + l.sequence_no + '</td>' +
            '<td>' + formatNum(l.butt_d1_cm, 1) + '</td>' +
            '<td>' + formatNum(l.butt_d2_cm, 1) + '</td>' +
            '<td>' + formatNum(l.top_d1_cm, 1) + '</td>' +
            '<td>' + formatNum(l.top_d2_cm, 1) + '</td>' +
            '<td>' + formatNum(l.length_cm, 1) + '</td>' +
            '<td>' + formatNum(l.volume_m3, 4) + '</td>' +
            '<td>' + formatDateTime(l.measured_at) + '</td>' +
            '<td class="sawmill-actions">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" onclick="Sawmill.editLog(' + l.id + ')" title="Edytuj">' +
            '<i class="fas fa-pen"></i></button>' +
            '<button type="button" class="btn btn-sm btn-outline-danger" onclick="Sawmill.deleteLog(' + l.id + ')" title="Usuń">' +
            '<i class="fas fa-trash"></i></button>' +
            '</td></tr>'
        );
    }

    function renderAuditItem(a) {
        var who = a.user_id ? 'użytkownik #' + a.user_id : (a.device_id ? 'urządzenie ' + escapeHtml(a.device_id) : 'system');
        return (
            '<li class="list-group-item">' +
            '<strong>' + escapeHtml(a.action) + '</strong> — ' + who +
            '<span class="text-muted small d-block">' + formatDateTime(a.created_at) + '</span>' +
            '</li>'
        );
    }

    function renderDetailsBody(data) {
        var o = data.order;
        var d = data.delivery;
        var logs = data.logs.filter(function (l) { return !l.is_deleted; });
        var count = o.logs_count;
        var avgVolume = count > 0 && o.measured_volume_m3 !== null ? o.measured_volume_m3 / count : null;
        var avgDiameter = null;
        var avgLength = null;
        if (logs.length > 0) {
            avgDiameter = logs.reduce(function (acc, l) {
                return acc + (Number(l.butt_d1_cm) + Number(l.butt_d2_cm) + Number(l.top_d1_cm) + Number(l.top_d2_cm)) / 4;
            }, 0) / logs.length;
            avgLength = logs.reduce(function (acc, l) { return acc + Number(l.length_cm); }, 0) / logs.length;
        }

        var invoiceDateSuffix = d.invoice_date ? ' (' + formatDate(d.invoice_date) + ')' : '';

        return (
            '<div class="row g-3 mb-3">' +
            '<div class="col-md-6"><h6>Dostawa</h6><table class="table table-sm mb-0">' +
            '<tr><th>Dostawca</th><td>' + escapeHtml(o.supplier_name || '—') + '</td></tr>' +
            '<tr><th>Faktura</th><td>' + escapeHtml(o.invoice_number || '—') + invoiceDateSuffix + '</td></tr>' +
            '<tr><th>Data dostawy</th><td>' + formatDate(o.delivery_date) + '</td></tr>' +
            '<tr><th>Gatunek</th><td>' + escapeHtml(o.species || '—') + '</td></tr>' +
            '<tr><th>Status</th><td><span class="badge sawmill-status-badge sawmill-status-' + o.status + '">' +
            statusLabel(o.status) + '</span></td></tr>' +
            '<tr><th>Notatki</th><td>' + escapeHtml(o.notes || '—') + '</td></tr>' +
            '</table></div>' +
            '<div class="col-md-6"><h6>Różnica</h6><table class="table table-sm mb-0">' +
            '<tr><th>Deklarowane</th><td>' + formatNum(o.declared_volume_m3, 3) + ' m³</td></tr>' +
            '<tr><th>Zmierzone</th><td>' + formatNum(o.measured_volume_m3, 3) + ' m³</td></tr>' +
            '<tr><th>Uzgodnione</th><td>' + formatNum(o.agreed_volume_m3, 3) + ' m³</td></tr>' +
            '<tr><th>Różnica m³</th><td class="' + diffClass(o.difference_m3, o.is_deviation) + '">' + formatSigned(o.difference_m3, 3) + '</td></tr>' +
            '<tr><th>Różnica %</th><td class="' + diffClass(o.difference_pct, o.is_deviation) + '">' + formatSigned(o.difference_pct, 2) + '%</td></tr>' +
            '<tr><th>Różnica zł</th><td class="' + diffClass(o.difference_value, o.is_deviation) + '">' + formatSigned(o.difference_value, 2) + ' zł</td></tr>' +
            '</table></div></div>' +

            '<div class="mb-3"><h6>Podsumowanie kłód</h6><div class="sawmill-summary-cards">' +
            '<div class="sawmill-summary-card"><span class="label">Suma m³</span><span class="value">' + formatNum(o.measured_volume_m3, 3) + '</span></div>' +
            '<div class="sawmill-summary-card"><span class="label">Liczba kłód</span><span class="value">' + count + '</span></div>' +
            '<div class="sawmill-summary-card"><span class="label">Śr. m³/kłodę</span><span class="value">' + (avgVolume !== null ? avgVolume.toFixed(4) : '—') + '</span></div>' +
            '<div class="sawmill-summary-card"><span class="label">Śr. średnica</span><span class="value">' + (avgDiameter !== null ? avgDiameter.toFixed(1) + ' cm' : '—') + '</span></div>' +
            '<div class="sawmill-summary-card"><span class="label">Śr. długość</span><span class="value">' + (avgLength !== null ? avgLength.toFixed(1) + ' cm' : '—') + '</span></div>' +
            '</div></div>' +

            '<h6>Kłody</h6><div class="table-responsive mb-3"><table class="table table-sm table-hover" id="sawmill-logs-table">' +
            '<thead><tr><th>#</th><th>Odziomek D1</th><th>Odziomek D2</th><th>Wierzchołek D1</th>' +
            '<th>Wierzchołek D2</th><th>Długość</th><th>Objętość m³</th><th>Zmierzono</th><th>Akcje</th></tr></thead>' +
            '<tbody>' + (logs.map(renderLogRow).join('') || '<tr><td colspan="9" class="text-center text-muted">Brak zmierzonych kłód</td></tr>') +
            '</tbody></table></div>' +

            '<div class="sawmill-audit-section">' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-bs-toggle="collapse" data-bs-target="#sawmill-audit-collapse">' +
            '<i class="fas fa-history me-1"></i>Historia audytu (' + data.audit.length + ')</button>' +
            '<div class="collapse mt-2" id="sawmill-audit-collapse"><ul class="list-group list-group-flush sawmill-audit-list">' +
            (data.audit.map(renderAuditItem).join('') || '<li class="list-group-item text-muted">Brak wpisów</li>') +
            '</ul></div></div>'
        );
    }

    function renderDetailsFooter(order) {
        var footer = el('sawmill-details-footer');
        var extra = '';
        if (order.status === 'completed') {
            extra = '<button type="button" class="btn btn-outline-secondary" onclick="Sawmill.reopenOrder(' + order.id + ')">Wznów</button>' +
                '<button type="button" class="btn btn-primary" onclick="Sawmill.openSettleModal(' + order.id + ')">Rozlicz</button>';
        } else if (order.status === 'settled') {
            extra = '<button type="button" class="btn btn-outline-warning" onclick="Sawmill.unsettleOrder(' + order.id + ')">Cofnij rozliczenie</button>';
        }
        footer.innerHTML = extra + '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Zamknij</button>';
    }

    function openDetails(orderId) {
        var body = el('sawmill-details-body');
        body.innerHTML = '<div class="text-center py-4"><i class="fas fa-spinner fa-spin"></i> Ładowanie...</div>';
        el('sawmill-details-footer').innerHTML = '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Zamknij</button>';
        bootstrap.Modal.getOrCreateInstance(el('sawmillDetailsModal')).show();

        return fetch(API + '/orders/' + orderId, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) {
                if (!resp.ok) {
                    return handleErrorResponse(resp).then(function () {
                        body.innerHTML = '<div class="alert alert-danger">Nie udało się wczytać szczegółów zlecenia.</div>';
                    });
                }
                return resp.json().then(function (data) {
                    state.currentOrder = data;
                    el('sawmill-details-title').textContent = 'Zlecenie ' + data.order.order_number;
                    body.innerHTML = renderDetailsBody(data);
                    renderDetailsFooter(data.order);
                });
            }).catch(function (err) {
                console.error('[Sawmill] Błąd ładowania szczegółów:', err);
                body.innerHTML = '<div class="alert alert-danger">Błąd połączenia z serwerem.</div>';
            });
    }

    function findLogInCurrentOrder(logId) {
        if (!state.currentOrder) return null;
        return state.currentOrder.logs.filter(function (l) { return l.id === logId; })[0] || null;
    }

    function editLog(logId) {
        var row = document.querySelector('#sawmill-logs-table tr[data-log-id="' + logId + '"]');
        var log = findLogInCurrentOrder(logId);
        if (!row || !log) return;

        function inputCell(field, value) {
            return '<td><input type="number" step="0.1" class="form-control form-control-sm" ' +
                'data-field="' + field + '" value="' + value + '"></td>';
        }

        row.innerHTML =
            '<td>' + log.sequence_no + '</td>' +
            inputCell('butt_d1_cm', log.butt_d1_cm) +
            inputCell('butt_d2_cm', log.butt_d2_cm) +
            inputCell('top_d1_cm', log.top_d1_cm) +
            inputCell('top_d2_cm', log.top_d2_cm) +
            inputCell('length_cm', log.length_cm) +
            '<td>' + formatNum(log.volume_m3, 4) + '</td>' +
            '<td colspan="2">' +
            '<button type="button" class="btn btn-sm btn-primary" onclick="Sawmill.saveLog(' + logId + ')"><i class="fas fa-check"></i></button> ' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" onclick="Sawmill.openDetails(' + state.currentOrder.order.id + ')"><i class="fas fa-times"></i></button>' +
            '</td>';
    }

    function saveLog(logId) {
        var row = document.querySelector('#sawmill-logs-table tr[data-log-id="' + logId + '"]');
        if (!row) return Promise.resolve();

        var payload = {};
        row.querySelectorAll('[data-field]').forEach(function (input) {
            payload[input.dataset.field] = input.value;
        });

        return fetch(API + '/logs/' + logId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp);
            toast('Pomiar zaktualizowany', 'success');
            var orderId = state.currentOrder.order.id;
            return openDetails(orderId).then(loadOrders);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd zapisu pomiaru:', err);
            toast('Błąd połączenia z serwerem', 'error');
        });
    }

    function deleteLog(logId) {
        if (!confirm('Czy na pewno usunąć ten pomiar?')) return Promise.resolve();

        return fetch(API + '/logs/' + logId, { method: 'DELETE', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) {
                if (!resp.ok) return handleErrorResponse(resp);
                toast('Pomiar usunięty', 'success');
                var orderId = state.currentOrder.order.id;
                return openDetails(orderId).then(loadOrders);
            }).catch(function (err) {
                console.error('[Sawmill] Błąd usuwania pomiaru:', err);
                toast('Błąd połączenia z serwerem', 'error');
            });
    }

    // ── Modal: Rozliczenie ───────────────────────────────────────────────────

    function openSettleModal(orderId) {
        var order = state.lastOrders[orderId];
        var prepare = order ? Promise.resolve(order) : fetch(API + '/orders/' + orderId, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (resp) { return resp.ok ? resp.json().then(function (d) { return d.order; }) : null; });

        return prepare.then(function (o) {
            el('sawmill-settle-order-id').value = orderId;
            el('sawmill-settle-agreed-volume').value = (o && o.measured_volume_m3 !== null && o.measured_volume_m3 !== undefined)
                ? o.measured_volume_m3 : '';
            el('sawmill-settle-notes').value = '';
            el('sawmill-settle-error').style.display = 'none';
            bootstrap.Modal.getOrCreateInstance(el('sawmillSettleModal')).show();
        });
    }

    function confirmSettle() {
        var orderId = parseInt(el('sawmill-settle-order-id').value, 10);
        var errorEl = el('sawmill-settle-error');
        errorEl.style.display = 'none';

        var payload = {
            agreed_volume_m3: el('sawmill-settle-agreed-volume').value || null,
            settlement_notes: el('sawmill-settle-notes').value || null,
        };

        return fetch(API + '/orders/' + orderId + '/settle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            toast('Zlecenie rozliczone', 'success');
            bootstrap.Modal.getOrCreateInstance(el('sawmillSettleModal')).hide();
            var refresh = [loadOrders()];
            if (state.currentOrder && state.currentOrder.order.id === orderId) {
                refresh.push(openDetails(orderId));
            }
            return Promise.all(refresh);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd rozliczenia:', err);
            errorEl.textContent = 'Błąd połączenia z serwerem.';
            errorEl.style.display = 'block';
        });
    }

    // ── Akcje na zleceniu (wznów / cofnij rozliczenie / usuń) ───────────────

    function postAction(orderId, action, successMessage) {
        return fetch(API + '/orders/' + orderId + '/' + action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp);
            toast(successMessage, 'success');
            var refresh = [loadOrders()];
            if (state.currentOrder && state.currentOrder.order.id === orderId) {
                refresh.push(openDetails(orderId));
            }
            return Promise.all(refresh);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd akcji ' + action + ':', err);
            toast('Błąd połączenia z serwerem', 'error');
        });
    }

    function reopenOrder(orderId) {
        if (!confirm('Czy na pewno wznowić to zlecenie (cofnąć zakończenie)?')) return Promise.resolve();
        return postAction(orderId, 'reopen', 'Zlecenie wznowione');
    }

    function unsettleOrder(orderId) {
        if (!confirm('Czy na pewno cofnąć rozliczenie tego zlecenia?')) return Promise.resolve();
        return postAction(orderId, 'unsettle', 'Rozliczenie cofnięte');
    }

    function deleteOrder(orderId) {
        if (!confirm('Czy na pewno usunąć to zlecenie? Operacji nie można cofnąć.')) return Promise.resolve();
        return fetch(API + '/orders/' + orderId, { method: 'DELETE', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) {
                if (!resp.ok) return handleErrorResponse(resp);
                toast('Zlecenie usunięte', 'success');
                return loadOrders();
            }).catch(function (err) {
                console.error('[Sawmill] Błąd usuwania zlecenia:', err);
                toast('Błąd połączenia z serwerem', 'error');
            });
    }

    // ── Eksport XLSX ─────────────────────────────────────────────────────────

    function exportXlsx() {
        var params = new URLSearchParams(currentFilters());
        window.location.href = API + '/export.xlsx?' + params.toString();
    }

    // ── Modal: Słowniki (Dostawcy / Gatunki) ─────────────────────────────────

    function renderDictBody() {
        var type = state.dictType;
        return fetch(API + '/' + type + '?include_inactive=1', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) {
                if (!resp.ok) return handleErrorResponse(resp);
                return resp.json().then(function (data) {
                    var rows = data[type];
                    var listHtml = rows.map(function (r) {
                        var actionBtn = r.is_active
                            ? '<button type="button" class="btn btn-sm btn-outline-danger" onclick="Sawmill.deleteDictItem(' + r.id + ')" title="Dezaktywuj"><i class="fas fa-trash"></i></button>'
                            : '<button type="button" class="btn btn-sm btn-outline-success" onclick="Sawmill.restoreDictItem(' + r.id + ')" title="Przywróć"><i class="fas fa-undo"></i></button>';
                        return '<li class="list-group-item d-flex justify-content-between align-items-center' + (r.is_active ? '' : ' text-muted') + '">' +
                            '<span>' + escapeHtml(r.name) + (r.is_active ? '' : ' (nieaktywny)') + '</span>' +
                            '<span>' + actionBtn + '</span></li>';
                    }).join('') || '<li class="list-group-item text-muted">Brak pozycji</li>';

                    var extraField = type === 'species'
                        ? '<input type="text" class="form-control" id="sawmill-dict-new-code" placeholder="Skrót (opcjonalnie)" style="max-width:140px;">'
                        : '';

                    el('sawmill-dict-body').innerHTML =
                        '<ul class="list-group mb-3">' + listHtml + '</ul>' +
                        '<div class="input-group">' +
                        '<input type="text" class="form-control" id="sawmill-dict-new-name" placeholder="Nazwa">' +
                        extraField +
                        '<button type="button" class="btn btn-primary" onclick="Sawmill.addDictItem()">Dodaj</button>' +
                        '</div>' +
                        '<div class="alert alert-danger mt-2" id="sawmill-dict-error" style="display:none;"></div>';
                });
            }).catch(function (err) {
                console.error('[Sawmill] Błąd ładowania słownika:', err);
                el('sawmill-dict-body').innerHTML = '<div class="alert alert-danger">Błąd połączenia z serwerem.</div>';
            });
    }

    function openDictModal(type) {
        state.dictType = type;
        el('sawmill-dict-title').textContent = type === 'species' ? 'Gatunki' : 'Dostawcy';
        el('sawmill-dict-body').innerHTML = '<div class="text-center py-3"><i class="fas fa-spinner fa-spin"></i></div>';
        bootstrap.Modal.getOrCreateInstance(el('sawmillDictModal')).show();
        return renderDictBody();
    }

    function addDictItem() {
        var type = state.dictType;
        var nameField = el('sawmill-dict-new-name');
        var name = nameField.value.trim();
        var errorEl = el('sawmill-dict-error');
        errorEl.style.display = 'none';

        if (!name) {
            errorEl.textContent = 'Podaj nazwę.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }

        var payload = { name: name };
        if (type === 'species') {
            var codeField = el('sawmill-dict-new-code');
            if (codeField && codeField.value.trim()) payload.short_code = codeField.value.trim();
        }

        return fetch(API + '/' + type, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            toast('Dodano pozycję', 'success');
            return renderDictBody().then(refreshDictOptions);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd dodawania pozycji słownika:', err);
            errorEl.textContent = 'Błąd połączenia z serwerem.';
            errorEl.style.display = 'block';
        });
    }

    function patchDictActive(id, isActive) {
        var type = state.dictType;
        var request = isActive
            ? fetch(API + '/' + type + '/' + id, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify({ is_active: true }),
            })
            : fetch(API + '/' + type + '/' + id, { method: 'DELETE', headers: { 'X-Requested-With': 'XMLHttpRequest' } });

        return request.then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp);
            return renderDictBody().then(refreshDictOptions);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd aktualizacji słownika:', err);
            toast('Błąd połączenia z serwerem', 'error');
        });
    }

    function deleteDictItem(id) {
        if (!confirm('Dezaktywować tę pozycję? Historyczne dostawy/zlecenia pozostaną nienaruszone.')) return Promise.resolve();
        return patchDictActive(id, false);
    }

    function restoreDictItem(id) {
        return patchDictActive(id, true);
    }

    // Uwaga: obsługa kliknięcia ikony "otwórz" na kafelku trakowni
    // ([data-goto-tab="sawmill-tab"] w gridzie "Stanowiska produkcyjne" na
    // Dashboardzie) NIE jest już tutaj — przeniesiona do
    // production-app-loader.js (handleTabClick), bo ten plik ładuje się
    // leniwie dopiero po wejściu na zakładkę Trakownia, a kafelek renderuje
    // się już na Dashboardzie, prefetchowanym od razu.

    // ── Inicjalizacja ────────────────────────────────────────────────────────

    function bindStaticEvents() {
        el('sawmill-btn-new-delivery').addEventListener('click', openDeliveryModal);
        el('sawmill-btn-suppliers').addEventListener('click', function () { openDictModal('suppliers'); });
        el('sawmill-btn-species').addEventListener('click', function () { openDictModal('species'); });
        el('sawmill-btn-new-supplier').addEventListener('click', function () { openDictModal('suppliers'); });
        el('sawmill-btn-export').addEventListener('click', exportXlsx);
        el('sawmill-btn-apply-filters').addEventListener('click', loadOrders);
        el('sawmill-btn-add-item').addEventListener('click', addItemRow);
        el('sawmill-btn-submit-delivery').addEventListener('click', submitDelivery);
        el('sawmill-btn-confirm-settle').addEventListener('click', confirmSettle);

        // Enter w polu szukania też filtruje — bez tego trzeba zawsze klikać "Filtruj".
        el('sawmill-filter-q').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); loadOrders(); }
        });
    }

    function init() {
        seedSpeciesOptionsFromDOM();
        bindStaticEvents();

        var firstRow = document.querySelector('#sawmill-delivery-items .sawmill-item-row');
        if (firstRow) bindItemRowPreview(firstRow);

        loadSpeciesOptions();
        loadSupplierOptions();
        loadOrders();
    }

    // Funkcje wywoływane z atrybutów onclick w dynamicznie generowanym HTML
    // (wiersze zleceń, kłód, słowników) — ten sam wzorzec co window.configModule
    // w config-module.js.
    window.Sawmill = {
        openDetails: openDetails,
        openSettleModal: openSettleModal,
        confirmSettle: confirmSettle,
        reopenOrder: reopenOrder,
        unsettleOrder: unsettleOrder,
        deleteOrder: deleteOrder,
        editLog: editLog,
        saveLog: saveLog,
        deleteLog: deleteLog,
        removeItemRow: removeItemRow,
        addDictItem: addDictItem,
        deleteDictItem: deleteDictItem,
        restoreDictItem: restoreDictItem,
    };

    init();
})();
