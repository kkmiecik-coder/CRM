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

    // Definicje pól formularzy słownikowych (modal Dostawcy/Gatunki) — jedno
    // źródło prawdy zarówno dla renderowania formularza, jak i zbierania
    // payloadu do POST/PATCH. Zestaw i kolejność pól dostawcy odpowiada
    // SUPPLIER_FIELDS w panel_api.py — tam backend przyjmuje dokładnie te
    // osiem pól (plus notes), a bez formularza dla wszystkich pozostawały
    // puste na zawsze, mimo że trafiają na protokół PDF idący do dostawcy.
    var DICT_FIELDS = {
        suppliers: [
            { field: 'name', label: 'Nazwa', type: 'text', required: true },
            { field: 'nip', label: 'NIP', type: 'text' },
            { field: 'address_street', label: 'Ulica i numer', type: 'text' },
            { field: 'address_zip', label: 'Kod pocztowy', type: 'text' },
            { field: 'address_city', label: 'Miasto', type: 'text' },
            { field: 'contact_person', label: 'Osoba kontaktowa', type: 'text' },
            { field: 'phone', label: 'Telefon', type: 'text' },
            { field: 'email', label: 'E-mail', type: 'email' },
            { field: 'notes', label: 'Notatki', type: 'textarea' },
        ],
        species: [
            { field: 'name', label: 'Nazwa', type: 'text', required: true },
            { field: 'short_code', label: 'Skrót (opcjonalnie)', type: 'text', maxlength: 8 },
            { field: 'sort_order', label: 'Kolejność sortowania', type: 'number' },
        ],
    };

    // Kolumny listy pozycji w modalu słownika — osobny, krótszy zestaw niż
    // pełny formularz: tyle, żeby dało się odróżnić dwa podobne wpisy
    // (np. dwóch dostawców o zbliżonej nazwie), bez przeładowania tabeli.
    function dictListColumns(type) {
        if (type === 'suppliers') {
            return [
                { label: 'Nazwa', render: function (r) { return escapeHtml(r.name); } },
                { label: 'NIP', render: function (r) { return escapeHtml(r.nip || '—'); } },
                { label: 'Miasto', render: function (r) { return escapeHtml(r.address_city || '—'); } },
            ];
        }
        return [
            { label: 'Nazwa', render: function (r) { return escapeHtml(r.name); } },
            { label: 'Skrót', render: function (r) { return escapeHtml(r.short_code || '—'); } },
            { label: 'Kolejność', render: function (r) { return escapeHtml(r.sort_order); } },
        ];
    }

    // Stan modułu — cache ostatnio wczytanej listy i aktualnie otwartego
    // zlecenia, żeby akcje (rozlicz/wznów/edycja pomiaru) mogły odświeżyć
    // widok bez zbędnych dodatkowych zapytań.
    var state = {
        lastOrders: {},
        currentOrder: null,
        dictType: null,
        // id edytowanej pozycji słownika (dostawcy/gatunku) — null = formularz
        // w trybie dodawania nowej pozycji, patrz renderDictBody()/submitDictForm().
        dictEditingId: null,
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

    // Protokół PDF — GET /orders/<id>/protocol.pdf otwierany w nowej karcie.
    // Zwykły <a target="_blank">, nie fetch: to endpoint zwracający plik,
    // sesja (ciasteczko) idzie automatycznie z nawigacją przeglądarki tak
    // samo jak przy exportXlsx() niżej.
    function protocolPdfLinkHtml(orderId) {
        return '<a class="btn btn-sm btn-outline-secondary" href="' + API + '/orders/' + orderId + '/protocol.pdf" ' +
            'target="_blank" rel="noopener" title="Protokół PDF">' +
            '<i class="fas fa-file-pdf"></i></a>';
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
            protocolPdfLinkHtml(o.id) +
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

    // Struktura kolumn MUSI odpowiadać statycznemu wierszowi w tab_content.html
    // (3/2/2/2/1/2 = 12) — to samo pole "Usuń pozycję", zawsze widoczne,
    // stan disabled/enabled ustawia potem updateRemoveButtonsVisibility().
    function buildItemRow() {
        var row = document.createElement('div');
        row.className = 'sawmill-item-row row g-2 align-items-end mb-2';
        row.innerHTML =
            '<div class="col-md-3">' +
            '<label class="form-label">Gatunek</label>' +
            '<select class="form-select sawmill-item-species" data-field="species_id" required>' +
            '<option value="">— wybierz —</option>' + state.speciesOptionsHtml +
            '</select></div>' +
            '<div class="col-md-2">' +
            '<label class="form-label">Deklarowana obj. m³</label>' +
            '<input type="number" step="0.001" min="0" class="form-control sawmill-item-declared-volume" ' +
            'data-field="declared_volume_m3" required></div>' +
            '<div class="col-md-2">' +
            '<label class="form-label">Liczba kłód</label>' +
            '<input type="number" step="1" min="0" class="form-control sawmill-item-logs-count"></div>' +
            '<div class="col-md-2">' +
            '<label class="form-label">Cena/m³</label>' +
            '<input type="number" step="0.01" min="0" class="form-control sawmill-item-price" data-field="price_per_m3"></div>' +
            '<div class="col-md-1 text-end">' +
            '<label class="form-label d-block">&nbsp;</label>' +
            '<span class="sawmill-item-value-preview text-muted small">— zł</span></div>' +
            '<div class="col-md-2 text-end">' +
            '<label class="form-label d-block">&nbsp;</label>' +
            '<button type="button" class="btn btn-sm btn-outline-danger sawmill-item-remove w-100" title="Usuń pozycję" ' +
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

    // Przycisk usuwania pozycji jest ZAWSZE widoczny (nie chowamy go przez
    // display:none) — przy jednej pozycji jest tylko disabled, żeby układ
    // wiersza nie "skakał" przy dodawaniu/usuwaniu kolejnych pozycji.
    function updateRemoveButtonsVisibility() {
        var rows = el('sawmill-delivery-items').querySelectorAll('.sawmill-item-row');
        var onlyOneRow = rows.length <= 1;
        rows.forEach(function (r) {
            var btn = r.querySelector('.sawmill-item-remove');
            if (btn) btn.disabled = onlyOneRow;
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
        toggleInlineNewSupplier(false);

        var itemsContainer = el('sawmill-delivery-items');
        itemsContainer.innerHTML = '';
        itemsContainer.appendChild(buildItemRow());
        updateRemoveButtonsVisibility();
    }

    function openDeliveryModal() {
        resetDeliveryForm();
        bootstrap.Modal.getOrCreateInstance(el('sawmillDeliveryModal')).show();
    }

    // ── Modal: Nowa dostawa — dodanie dostawcy "w locie" ────────────────────
    //
    // Zamiast zagnieżdżonego modalu Bootstrapa (który renderował się POD
    // przyciemnieniem tła własnego overlaya — klasyczny problem z-index przy
    // dwóch modalach naraz, gdzie jedynym wyjściem był Escape) — rozwijany
    // formularz WEWNĄTRZ modalu dostawy. Po zapisaniu dostawcy dopisujemy go
    // do listy i od razu zaznaczamy w select-cie, więc użytkownik nie musi
    // zamykać modalu, odświeżać słownika ani szukać świeżo dodanej pozycji.

    function toggleInlineNewSupplier(show) {
        var box = el('sawmill-inline-new-supplier');
        box.style.display = show ? '' : 'none';
        el('sawmill-inline-supplier-error').style.display = 'none';
        if (show) {
            el('sawmill-inline-supplier-name').value = '';
            el('sawmill-inline-supplier-name').focus();
        }
    }

    function saveInlineSupplier() {
        var nameInput = el('sawmill-inline-supplier-name');
        var name = nameInput.value.trim();
        var errorEl = el('sawmill-inline-supplier-error');
        errorEl.style.display = 'none';

        if (!name) {
            errorEl.textContent = 'Podaj nazwę dostawcy.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }

        var saveBtn = el('sawmill-btn-save-inline-supplier');
        saveBtn.disabled = true;

        return fetch(API + '/suppliers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify({ name: name }),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            return resp.json().then(function (data) {
                var supplier = data.supplier;
                toast('Dodano dostawcę: ' + supplier.name, 'success');
                // Odświeżamy select filtra i select dostawy z serwera (spójne
                // dane, ta sama funkcja co przy zwykłym CRUD-zie słownika),
                // a potem zaznaczamy świeżo utworzoną pozycję.
                return loadSupplierOptions().then(function () {
                    var select = el('sawmill-delivery-supplier');
                    select.value = String(supplier.id);
                    select.classList.remove('is-invalid');
                    toggleInlineNewSupplier(false);
                });
            });
        }).catch(function (err) {
            console.error('[Sawmill] Błąd dodawania dostawcy:', err);
            errorEl.textContent = 'Błąd połączenia z serwerem.';
            errorEl.style.display = 'block';
        }).finally(function () {
            saveBtn.disabled = false;
        });
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

            manualLogFormHtml(o.id) +

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

    // Ratunek dla pomiarów odrzuconych przez 409 — droga druga (obok
    // Sawmill.reopenOrder): ręczne dopisanie pomiaru, gdy tablet padł albo
    // kolejka na tablecie została wyczyszczona. Backend (POST /orders/<id>/logs)
    // istniał od dawna, ale bez tego formularza nie miał żadnej drogi
    // dojścia w interfejsie.
    function manualLogFormHtml(orderId) {
        function numberField(field, label) {
            return '<div class="col-6 col-md-2"><label class="form-label small mb-1">' + label + '</label>' +
                '<input type="number" step="0.1" min="0" class="form-control form-control-sm" ' +
                'data-field="' + field + '" id="sawmill-manual-log-' + field + '"></div>';
        }

        return (
            '<div class="sawmill-manual-log-section mb-3">' +
            '<h6>Dopisz pomiar ręcznie</h6>' +
            '<p class="text-muted small mb-2">Ścieżka awaryjna — gdy tablet padł albo kolejka pomiarów na tablecie została wyczyszczona.</p>' +
            '<div class="row g-2 align-items-end" id="sawmill-manual-log-form">' +
            numberField('butt_d1_cm', 'Odziomek D1') +
            numberField('butt_d2_cm', 'Odziomek D2') +
            numberField('top_d1_cm', 'Wierzchołek D1') +
            numberField('top_d2_cm', 'Wierzchołek D2') +
            numberField('length_cm', 'Długość') +
            '<div class="col-6 col-md-2"><label class="form-label small mb-1">Czas pomiaru</label>' +
            '<input type="datetime-local" class="form-control form-control-sm" ' +
            'data-field="measured_at" id="sawmill-manual-log-measured_at"></div>' +
            '</div>' +
            '<div class="mt-2">' +
            '<button type="button" class="btn btn-sm btn-outline-primary" id="sawmill-btn-manual-log-submit" ' +
            'onclick="Sawmill.submitManualLog(' + orderId + ')">' +
            '<i class="fas fa-plus me-1"></i>Dopisz pomiar</button>' +
            '<div class="alert alert-danger mt-2" id="sawmill-manual-log-error" style="display:none;"></div>' +
            '</div>' +
            '</div>'
        );
    }

    function collectManualLogPayload() {
        var payload = {};
        el('sawmill-manual-log-form').querySelectorAll('[data-field]').forEach(function (input) {
            payload[input.dataset.field] = input.value;
        });
        return payload;
    }

    function submitManualLog(orderId) {
        var errorEl = el('sawmill-manual-log-error');
        errorEl.style.display = 'none';
        var payload = collectManualLogPayload();
        var submitBtn = el('sawmill-btn-manual-log-submit');
        submitBtn.disabled = true;

        return fetch(API + '/orders/' + orderId + '/logs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            toast('Pomiar dopisany ręcznie', 'success');
            return openDetails(orderId).then(loadOrders);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd ręcznego dopisania pomiaru:', err);
            errorEl.textContent = 'Błąd połączenia z serwerem.';
            errorEl.style.display = 'block';
        }).finally(function () {
            // Po sukcesie openDetails() i tak przebudowuje cały modal (nowy
            // przycisk, nowy element DOM) — disabled=false na starym elemencie
            // nic już wtedy nie zmienia, ale przy błędzie (formularz zostaje)
            // przywraca możliwość poprawienia i ponowienia.
            if (submitBtn) submitBtn.disabled = false;
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
    //
    // Zawsze pobieramy z include_inactive=1 — nieaktywne (miękko skasowane)
    // pozycje muszą być widoczne, z jasnym opisem co to znaczy i przyciskiem
    // przywrócenia. To ważne, bo sprawdzenie duplikatu nazwy po stronie
    // backendu NIE filtruje is_active — po dezaktywacji nie da się dodać
    // nowej pozycji o tej samej nazwie, jedyną drogą jest przywrócenie starej.

    function renderDictRow(r, type) {
        var cols = dictListColumns(type)
            .map(function (c) { return '<td>' + c.render(r) + '</td>'; })
            .join('');
        var statusBadge = r.is_active
            ? '<span class="badge bg-success">aktywny</span>'
            : '<span class="badge bg-secondary">nieaktywny</span>';
        var actionBtns =
            '<button type="button" class="btn btn-sm btn-outline-secondary" ' +
            'onclick="Sawmill.editDictItem(' + r.id + ')" title="Edytuj"><i class="fas fa-pen"></i></button> ' +
            (r.is_active
                ? '<button type="button" class="btn btn-sm btn-outline-danger" ' +
                  'onclick="Sawmill.deleteDictItem(' + r.id + ')" title="Dezaktywuj"><i class="fas fa-trash"></i></button>'
                : '<button type="button" class="btn btn-sm btn-outline-success" ' +
                  'onclick="Sawmill.restoreDictItem(' + r.id + ')" title="Przywróć"><i class="fas fa-undo"></i></button>');
        return '<tr' + (r.is_active ? '' : ' class="text-muted"') + '>' + cols +
            '<td>' + statusBadge + '</td><td class="sawmill-actions">' + actionBtns + '</td></tr>';
    }

    // Buduje formularz dodawania/edycji z DICT_FIELDS. `values` (opcjonalne)
    // to rekord edytowanej pozycji — gdy podany, pola wypełniają się jego
    // wartościami (tryb edycji), inaczej formularz jest pusty (tryb dodawania).
    function renderDictFormFields(type, values) {
        values = values || {};
        return DICT_FIELDS[type].map(function (f) {
            var raw = values[f.field];
            var value = (raw === undefined || raw === null) ? '' : raw;
            var fieldId = 'sawmill-dict-field-' + f.field;
            var colClass = f.type === 'textarea' ? 'col-12' : 'col-md-6';
            var inputHtml;
            if (f.type === 'textarea') {
                inputHtml = '<textarea class="form-control" rows="2" data-field="' + f.field + '" id="' + fieldId + '">' +
                    escapeHtml(value) + '</textarea>';
            } else {
                var maxlenAttr = f.maxlength ? ' maxlength="' + f.maxlength + '"' : '';
                inputHtml = '<input type="' + f.type + '" class="form-control" data-field="' + f.field + '" ' +
                    'id="' + fieldId + '" value="' + escapeHtml(value) + '"' + maxlenAttr +
                    (f.required ? ' required' : '') + '>';
            }
            return '<div class="' + colClass + '">' +
                '<label class="form-label small mb-1" for="' + fieldId + '">' + escapeHtml(f.label) +
                (f.required ? ' *' : '') + '</label>' + inputHtml + '</div>';
        }).join('');
    }

    function renderDictBody() {
        var type = state.dictType;
        return fetch(API + '/' + type + '?include_inactive=1', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (resp) {
                if (!resp.ok) return handleErrorResponse(resp);
                return resp.json().then(function (data) {
                    var rows = data[type];
                    var cols = dictListColumns(type);
                    var theadHtml = '<tr>' + cols.map(function (c) { return '<th>' + escapeHtml(c.label) + '</th>'; }).join('') +
                        '<th>Status</th><th>Akcje</th></tr>';
                    var tbodyHtml = rows.map(function (r) { return renderDictRow(r, type); }).join('') ||
                        ('<tr><td colspan="' + (cols.length + 2) + '" class="text-center text-muted">Brak pozycji</td></tr>');

                    var editing = state.dictEditingId
                        ? rows.filter(function (r) { return r.id === state.dictEditingId; })[0]
                        : null;
                    // Edytowana pozycja mogła zniknąć spod nas (np. ktoś inny ją
                    // dezaktywował) — wtedy po cichu wracamy do trybu dodawania.
                    if (state.dictEditingId && !editing) state.dictEditingId = null;

                    var formTitle = editing ? ('Edycja: ' + escapeHtml(editing.name)) : 'Nowa pozycja';
                    var submitLabel = editing ? 'Zapisz zmiany' : 'Dodaj';
                    var cancelBtnHtml = editing
                        ? '<button type="button" class="btn btn-sm btn-outline-secondary ms-2" ' +
                          'onclick="Sawmill.cancelDictEdit()">Anuluj edycję</button>'
                        : '';

                    el('sawmill-dict-body').innerHTML =
                        '<p class="text-muted small mb-2">Usunięcie oznacza dezaktywację — pozycja znika z list wyboru ' +
                        'przy nowych dostawach, ale historyczne zlecenia w bazie pozostają nienaruszone. Nieaktywne ' +
                        'pozycje (poniżej, wyszarzone) można w każdej chwili przywrócić przyciskiem ' +
                        '<i class="fas fa-undo"></i> — jeśli dodanie nowej pozycji zgłasza, że nazwa już istnieje, ' +
                        'sprawdź najpierw, czy nie jest już na liście jako nieaktywna.</p>' +
                        '<div class="table-responsive mb-3"><table class="table table-sm align-middle sawmill-dict-table">' +
                        '<thead>' + theadHtml + '</thead><tbody>' + tbodyHtml + '</tbody></table></div>' +
                        '<h6 class="mb-2">' + formTitle + '</h6>' +
                        '<div class="row g-2">' + renderDictFormFields(type, editing) + '</div>' +
                        '<div class="mt-3">' +
                        '<button type="button" class="btn btn-primary btn-sm" onclick="Sawmill.submitDictForm()">' +
                        escapeHtml(submitLabel) + '</button>' + cancelBtnHtml +
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
        state.dictEditingId = null;
        el('sawmill-dict-title').textContent = type === 'species' ? 'Gatunki' : 'Dostawcy';
        el('sawmill-dict-body').innerHTML = '<div class="text-center py-3"><i class="fas fa-spinner fa-spin"></i></div>';
        bootstrap.Modal.getOrCreateInstance(el('sawmillDictModal')).show();
        return renderDictBody();
    }

    function editDictItem(id) {
        state.dictEditingId = id;
        return renderDictBody();
    }

    function cancelDictEdit() {
        state.dictEditingId = null;
        return renderDictBody();
    }

    function collectDictFormPayload(type) {
        var payload = {};
        DICT_FIELDS[type].forEach(function (f) {
            var input = el('sawmill-dict-field-' + f.field);
            if (input) payload[f.field] = input.value;
        });
        return payload;
    }

    function submitDictForm() {
        var type = state.dictType;
        var errorEl = el('sawmill-dict-error');
        errorEl.style.display = 'none';

        var payload = collectDictFormPayload(type);
        if (!payload.name || !payload.name.trim()) {
            errorEl.textContent = 'Podaj nazwę.';
            errorEl.style.display = 'block';
            return Promise.resolve();
        }
        payload.name = payload.name.trim();

        var editingId = state.dictEditingId;
        var request = editingId
            ? fetch(API + '/' + type + '/' + editingId, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify(payload),
            })
            : fetch(API + '/' + type, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                body: JSON.stringify(payload),
            });

        return request.then(function (resp) {
            if (!resp.ok) return handleErrorResponse(resp, errorEl);
            toast(editingId ? 'Zapisano zmiany' : 'Dodano pozycję', 'success');
            state.dictEditingId = null;
            return renderDictBody().then(refreshDictOptions);
        }).catch(function (err) {
            console.error('[Sawmill] Błąd zapisu słownika:', err);
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
        if (!confirm('Dezaktywować tę pozycję? Zniknie z list wyboru, ale historyczne dostawy/zlecenia ' +
            'pozostaną nienaruszone — pozycję można później przywrócić.')) return Promise.resolve();
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
        el('sawmill-btn-export').addEventListener('click', exportXlsx);
        el('sawmill-btn-apply-filters').addEventListener('click', loadOrders);
        el('sawmill-btn-add-item').addEventListener('click', addItemRow);
        el('sawmill-btn-submit-delivery').addEventListener('click', submitDelivery);
        el('sawmill-btn-confirm-settle').addEventListener('click', confirmSettle);

        // "+ Nowy dostawca" — formularz inline zamiast zagnieżdżonego modalu
        // (patrz sekcja "Modal: Nowa dostawa — dodanie dostawcy w locie" wyżej).
        el('sawmill-btn-new-supplier').addEventListener('click', function () { toggleInlineNewSupplier(true); });
        el('sawmill-btn-cancel-inline-supplier').addEventListener('click', function () { toggleInlineNewSupplier(false); });
        el('sawmill-btn-save-inline-supplier').addEventListener('click', saveInlineSupplier);
        el('sawmill-inline-supplier-name').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); saveInlineSupplier(); }
        });

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
        submitManualLog: submitManualLog,
        removeItemRow: removeItemRow,
        submitDictForm: submitDictForm,
        editDictItem: editDictItem,
        cancelDictEdit: cancelDictEdit,
        deleteDictItem: deleteDictItem,
        restoreDictItem: restoreDictItem,
    };

    init();
})();
