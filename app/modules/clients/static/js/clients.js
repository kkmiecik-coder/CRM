// static/js/clients.js

let clients = [];
let currentPage = 1;
let rowsPerPage = 20;
let totalPages = 1;
let totalCount = 0;
let currentSearchTerm = '';
let currentSortKey = 'client_name';
let currentSortAsc = true;
let quotesPerPage = 10;
let currentQuotePage = 1;
let allQuotes = [];
let editedClientId = null;

// ========== FUNKCJE WALIDACJI ========== //

/**
 * Walidacja email - wymaga "@" oraz "." w domenie
 */
function validateEmail(email) {
    if (!email) return { valid: true, message: '' }; // Pole opcjonalne
    const atIndex = email.indexOf('@');
    if (atIndex === -1) {
        return { valid: false, message: 'Email musi zawierać znak @' };
    }
    const domain = email.substring(atIndex + 1);
    if (!domain.includes('.')) {
        return { valid: false, message: 'Domena email musi zawierać kropkę' };
    }
    if (domain.indexOf('.') === 0 || domain.endsWith('.')) {
        return { valid: false, message: 'Nieprawidłowy format domeny' };
    }
    return { valid: true, message: '' };
}

/**
 * Walidacja telefonu - min 9 cyfr, dozwolone: cyfry, +, (, ), spacja
 */
function validatePhone(phone) {
    if (!phone) return { valid: true, message: '' }; // Pole opcjonalne
    // Sprawdź dozwolone znaki
    if (!/^[0-9+().\s-]+$/.test(phone)) {
        return { valid: false, message: 'Dozwolone znaki: cyfry, +, (, ), spacja, myślnik' };
    }
    // Policz same cyfry
    const digitsOnly = phone.replace(/\D/g, '');
    if (digitsOnly.length < 9) {
        return { valid: false, message: 'Telefon musi mieć minimum 9 cyfr' };
    }
    return { valid: true, message: '' };
}

/**
 * Walidacja NIP - dokładnie 10 cyfr
 */
function validateNIP(nip) {
    if (!nip) return { valid: true, message: '' }; // Pole opcjonalne
    const digitsOnly = nip.replace(/\D/g, '');
    if (digitsOnly.length !== 10) {
        return { valid: false, message: 'NIP musi mieć dokładnie 10 cyfr' };
    }
    return { valid: true, message: '' };
}

/**
 * Walidacja kodu pocztowego - dla Polski: XX-XXX
 */
function validatePostalCode(zip, country) {
    if (!zip) return { valid: true, message: '' }; // Pole opcjonalne

    // Dla Polski wymagamy formatu XX-XXX
    if (!country || country === 'Polska') {
        if (!/^\d{2}-\d{3}$/.test(zip)) {
            return { valid: false, message: 'Kod pocztowy musi mieć format XX-XXX' };
        }
    }
    return { valid: true, message: '' };
}

/**
 * Formatowanie kodu pocztowego - auto-wstawia "-" po 2 cyfrach
 */
function formatPostalCode(input, country) {
    // Tylko dla Polski stosujemy automatyczne formatowanie
    if (country && country !== 'Polska') {
        return; // Nie formatuj dla innych krajów
    }

    let value = input.value;

    // Usuń wszystko poza cyframi
    let digitsOnly = value.replace(/\D/g, '');

    // Ogranicz do 5 cyfr
    digitsOnly = digitsOnly.substring(0, 5);

    // Wstaw myślnik po 2 cyfrach
    if (digitsOnly.length > 2) {
        input.value = digitsOnly.substring(0, 2) + '-' + digitsOnly.substring(2);
    } else {
        input.value = digitsOnly;
    }
}

/**
 * Wyświetl błąd walidacji dla pola
 */
function showFieldError(inputId, errorId, message) {
    const input = document.getElementById(inputId);
    const errorEl = document.getElementById(errorId);
    if (input) {
        input.classList.remove('input-success-border');
        input.classList.add('input-error-border');
    }
    if (errorEl) {
        errorEl.textContent = message;
    }
}

/**
 * Ukryj błąd walidacji dla pola
 */
function clearFieldError(inputId, errorId) {
    const input = document.getElementById(inputId);
    const errorEl = document.getElementById(errorId);
    if (input) {
        input.classList.remove('input-error-border');
    }
    if (errorEl) {
        errorEl.textContent = '';
    }
}

/**
 * Obsługa zmiany kraju - włącz/wyłącz województwo
 */
function handleCountryChange(countrySelect, regionSelect) {
    const isPoland = countrySelect.value === 'Polska';
    regionSelect.disabled = !isPoland;
    if (!isPoland) {
        regionSelect.value = '';
        regionSelect.classList.add('disabled-select');
    } else {
        regionSelect.classList.remove('disabled-select');
    }
}

const tableBody = document.getElementById('clients-table-body');
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('searchBtn');
const rowsSelect = document.getElementById('rows-per-page');
const paginationControls = document.getElementById('pagination-controls');

function fetchClients() {
    const params = new URLSearchParams({
        page: currentPage,
        per_page: rowsPerPage,
        search: currentSearchTerm
    });

    fetch(`/clients/api/clients?${params}`)
        .then(res => res.json())
        .then(data => {
            clients = data.clients;
            totalPages = data.pagination.total_pages;
            totalCount = data.pagination.total_count;
            currentPage = data.pagination.page;
            renderTable();
        })
        .catch(err => {
            console.error('Błąd podczas pobierania klientów:', err);
            showToast('Błąd podczas pobierania klientów', false);
        });
}

function renderTable() {
    tableBody.innerHTML = '';

    if (clients.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = `<td colspan="5" style="text-align: center; padding: 20px; color: #666;">Brak klientów do wyświetlenia</td>`;
        tableBody.appendChild(row);
        renderPagination();
        return;
    }

    clients.forEach(client => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${client.client_number || '-'}</td>
            <td>${client.client_name || '-'}</td>
            <td>${client.email || '-'}</td>
            <td>${client.phone || '-'}</td>
            <td class="clients-actions"></td>
        `;

        const actionsCell = row.querySelector('.clients-actions');

        const detailsBtn = document.createElement("button");
        detailsBtn.textContent = "Szczegóły";
        detailsBtn.className = "clients-btn-detail";
        detailsBtn.addEventListener("click", () => showClientDetails(client.id));

        actionsCell.appendChild(detailsBtn);

        tableBody.appendChild(row);
    });

    renderPagination();
}

function renderPagination() {
    paginationControls.innerHTML = '';

    if (totalPages <= 1) return;

    // Przycisk "Poprzednia"
    if (currentPage > 1) {
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '←';
        prevBtn.title = 'Poprzednia strona';
        prevBtn.addEventListener('click', () => {
            currentPage--;
            fetchClients();
        });
        paginationControls.appendChild(prevBtn);
    }

    // Numerki stron
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    if (endPage - startPage + 1 < maxVisiblePages) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    if (startPage > 1) {
        const firstBtn = document.createElement('button');
        firstBtn.textContent = '1';
        firstBtn.addEventListener('click', () => {
            currentPage = 1;
            fetchClients();
        });
        paginationControls.appendChild(firstBtn);

        if (startPage > 2) {
            const dots = document.createElement('span');
            dots.textContent = '...';
            dots.className = 'pagination-dots';
            paginationControls.appendChild(dots);
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        if (i === currentPage) btn.classList.add('active');
        btn.addEventListener('click', () => {
            currentPage = i;
            fetchClients();
        });
        paginationControls.appendChild(btn);
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            const dots = document.createElement('span');
            dots.textContent = '...';
            dots.className = 'pagination-dots';
            paginationControls.appendChild(dots);
        }

        const lastBtn = document.createElement('button');
        lastBtn.textContent = totalPages;
        lastBtn.addEventListener('click', () => {
            currentPage = totalPages;
            fetchClients();
        });
        paginationControls.appendChild(lastBtn);
    }

    // Przycisk "Następna"
    if (currentPage < totalPages) {
        const nextBtn = document.createElement('button');
        nextBtn.textContent = '→';
        nextBtn.title = 'Następna strona';
        nextBtn.addEventListener('click', () => {
            currentPage++;
            fetchClients();
        });
        paginationControls.appendChild(nextBtn);
    }

    // Info o stronach
    const pageInfo = document.createElement('span');
    pageInfo.className = 'pagination-info';
    pageInfo.textContent = ` Strona ${currentPage} z ${totalPages} (${totalCount} klientów)`;
    paginationControls.appendChild(pageInfo);
}

// Wyszukiwanie po kliknięciu przycisku lub Enter
function performSearch() {
    currentSearchTerm = searchInput.value.trim();
    currentPage = 1;
    fetchClients();
}

searchBtn.addEventListener('click', performSearch);
searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        performSearch();
    }
});

rowsSelect.addEventListener('change', () => {
    rowsPerPage = parseInt(rowsSelect.value);
    currentPage = 1;
    fetchClients();
});

function showClientDetails(clientId) {
    console.log('=== showClientDetails START ===');
    console.log('Client ID:', clientId);

    currentEditClientId = clientId; // Zapisz ID dla trybu edycji

    // RESETUJ flagę załadowania dla nowego klienta
    const editNameField = document.getElementById('editClientName');
    if (editNameField) {
        editNameField.dataset.loaded = 'false';
        console.log('Reset flagi loaded na false');
    }

    fetch(`/clients/${clientId}/data`)
        .then(res => res.json())
        .then(client => {
            console.log('Otrzymane dane klienta:', client);

            document.getElementById('detailClientName').textContent = client.client_number || '---';
            document.getElementById('detailClientDeliveryName').textContent = client.client_name || '---';
            document.getElementById('detailClientEmail').textContent = client.email || '---';
            document.getElementById('detailClientPhone').textContent = client.phone || '---';
            document.getElementById('detailClientNotes').textContent = client.notes || '---';

            loadClientQuotes(clientId);

            // Upewnij się, że jesteśmy w trybie wyświetlania
            disableEditMode();

            document.getElementById('clients-details-modal').style.display = 'flex';
            console.log('=== showClientDetails END - Modal otwarty ===');
        })
        .catch(err => {
            console.error('Błąd podczas ładowania szczegółów klienta:', err);
        });
}

document.getElementById('clientsDetailsCloseBtn').addEventListener('click', () => {
    document.getElementById('clients-details-modal').style.display = 'none';
});

function loadClientQuotes(clientId) {
    fetch(`/clients/${clientId}/quotes`)
        .then(res => res.json())
        .then(data => {
            allQuotes = data;
            currentQuotePage = 1;

            const noQuotesMsg = document.getElementById('clients-no-quotes');
            const quotesTable = document.querySelector('.clients-quotes-table');
            const tbody = document.getElementById('clients-quotes-body');

            if (!data.length) {
                noQuotesMsg.style.display = 'block';
                quotesTable.style.display = 'none';
                document.getElementById('quotes-pagination-controls').innerHTML = '';
                return;
            }

            noQuotesMsg.style.display = 'none';
            quotesTable.style.display = 'table';
            tbody.innerHTML = '';

            renderQuotesTable();
        });
}

function renderQuotesTable() {
    const tbody = document.getElementById('clients-quotes-body');
    tbody.innerHTML = '';

    const start = (currentQuotePage - 1) * quotesPerPage;
    const end = start + quotesPerPage;
    const visibleQuotes = allQuotes.slice(start, end);

    visibleQuotes.forEach(quote => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${quote.id}</td>
            <td>${quote.date}</td>
            <td><span class="quote-status" style="background-color: ${quote.status_color};">${quote.status}</span></td>
            <td>
                <button class="clients-quote-link" onclick="redirectToQuote(${quote.id})">
                    Przejdź →
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    renderQuotesPagination();
}

function renderQuotesPagination() {
    const paginationContainer = document.getElementById('quotes-pagination-controls');
    paginationContainer.innerHTML = '';
    const totalPages = Math.ceil(allQuotes.length / quotesPerPage);

    for (let i = 1; i <= totalPages; i++) {
        const pageBtn = document.createElement('button');
        pageBtn.textContent = i;
        if (i === currentQuotePage) pageBtn.classList.add('active');
        pageBtn.addEventListener('click', () => {
            currentQuotePage = i;
            renderQuotesTable();
        });
        paginationContainer.appendChild(pageBtn);
    }
}

// ========== DOMContentLoaded ========== //
document.addEventListener('DOMContentLoaded', () => {
    fetchClients();

    // ========== SYSTEM ZAKŁADEK ========== //
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.dataset.tab;

            // Usuń active ze wszystkich
            tabButtons.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            // Dodaj active do klikniętego
            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
        });
    });

    // Funkcja resetująca zakładki do pierwszej
    function resetTabs() {
        tabButtons.forEach(b => b.classList.remove('active'));
        tabPanes.forEach(p => p.classList.remove('active'));
        if (tabButtons.length > 0) tabButtons[0].classList.add('active');
        if (tabPanes.length > 0) tabPanes[0].classList.add('active');
    }

    // ========== WALIDACJA - EVENT LISTENERS ========== //

    // Auto-formatowanie kodu pocztowego (dostawa)
    const addDeliveryZip = document.getElementById('addDeliveryZip');
    const addDeliveryCountry = document.getElementById('addDeliveryCountry');
    if (addDeliveryZip) {
        addDeliveryZip.addEventListener('input', () => {
            const country = addDeliveryCountry ? addDeliveryCountry.value : 'Polska';
            formatPostalCode(addDeliveryZip, country);
        });
    }

    // Auto-formatowanie kodu pocztowego (faktura)
    const addInvoiceZip = document.getElementById('addInvoiceZip');
    if (addInvoiceZip) {
        addInvoiceZip.addEventListener('input', () => {
            // Faktura zawsze Polski format
            formatPostalCode(addInvoiceZip, 'Polska');
        });
    }

    // Zmiana kraju - włącz/wyłącz województwo
    const addDeliveryRegion = document.getElementById('addDeliveryRegion');
    if (addDeliveryCountry && addDeliveryRegion) {
        addDeliveryCountry.addEventListener('change', () => {
            handleCountryChange(addDeliveryCountry, addDeliveryRegion);

            // Jeśli kraj nie jest Polska, wyczyść formatowanie kodu pocztowego
            if (addDeliveryCountry.value !== 'Polska' && addDeliveryZip) {
                // Pozwól na dowolny format dla innych krajów
                addDeliveryZip.removeAttribute('maxlength');
            } else if (addDeliveryZip) {
                addDeliveryZip.setAttribute('maxlength', '6');
            }
        });
    }

    // Walidacja email na blur
    const addClientEmail = document.getElementById('addClientEmail');
    if (addClientEmail) {
        addClientEmail.addEventListener('blur', () => {
            const result = validateEmail(addClientEmail.value.trim());
            if (!result.valid) {
                showFieldError('addClientEmail', 'error-addClientEmail', result.message);
            } else {
                clearFieldError('addClientEmail', 'error-addClientEmail');
                if (addClientEmail.value.trim()) {
                    addClientEmail.classList.add('input-success-border');
                }
            }
        });
    }

    // Walidacja telefonu na blur
    const addClientPhone = document.getElementById('addClientPhone');
    if (addClientPhone) {
        addClientPhone.addEventListener('blur', () => {
            const result = validatePhone(addClientPhone.value.trim());
            if (!result.valid) {
                showFieldError('addClientPhone', 'error-addClientPhone', result.message);
            } else {
                clearFieldError('addClientPhone', 'error-addClientPhone');
                if (addClientPhone.value.trim()) {
                    addClientPhone.classList.add('input-success-border');
                }
            }
        });
    }

    // Walidacja NIP na blur
    const addInvoiceNIP = document.getElementById('addInvoiceNIP');
    if (addInvoiceNIP) {
        addInvoiceNIP.addEventListener('blur', () => {
            const result = validateNIP(addInvoiceNIP.value.trim());
            if (!result.valid) {
                showFieldError('addInvoiceNIP', 'error-addInvoiceNIP', result.message);
            } else {
                clearFieldError('addInvoiceNIP', 'error-addInvoiceNIP');
                if (addInvoiceNIP.value.trim()) {
                    addInvoiceNIP.classList.add('input-success-border');
                }
            }
        });

        // Przy wpisywaniu NIP - tylko cyfry
        addInvoiceNIP.addEventListener('input', () => {
            addInvoiceNIP.value = addInvoiceNIP.value.replace(/\D/g, '').substring(0, 10);
        });
    }

    // Walidacja kodu pocztowego (dostawa) na blur
    if (addDeliveryZip) {
        addDeliveryZip.addEventListener('blur', () => {
            const country = addDeliveryCountry ? addDeliveryCountry.value : 'Polska';
            const result = validatePostalCode(addDeliveryZip.value.trim(), country);
            if (!result.valid) {
                showFieldError('addDeliveryZip', 'error-addDeliveryZip', result.message);
            } else {
                clearFieldError('addDeliveryZip', 'error-addDeliveryZip');
                if (addDeliveryZip.value.trim()) {
                    addDeliveryZip.classList.add('input-success-border');
                }
            }
        });
    }

    // Walidacja kodu pocztowego (faktura) na blur
    if (addInvoiceZip) {
        addInvoiceZip.addEventListener('blur', () => {
            const result = validatePostalCode(addInvoiceZip.value.trim(), 'Polska');
            if (!result.valid) {
                showFieldError('addInvoiceZip', 'error-addInvoiceZip', result.message);
            } else {
                clearFieldError('addInvoiceZip', 'error-addInvoiceZip');
                if (addInvoiceZip.value.trim()) {
                    addInvoiceZip.classList.add('input-success-border');
                }
            }
        });
    }

    const addBtn = document.getElementById('addClientBtn');
    const addModal = document.getElementById('clients-add-modal');

    if (addBtn && addModal) {
        addBtn.addEventListener('click', () => {
            resetTabs(); // Reset do pierwszej zakładki
            // Reset kraju i województwa przy otwarciu
            if (addDeliveryCountry) addDeliveryCountry.value = 'Polska';
            if (addDeliveryRegion) {
                addDeliveryRegion.value = '';
                addDeliveryRegion.disabled = false;
                addDeliveryRegion.classList.remove('disabled-select');
            }
            addModal.style.display = 'flex';
        });
    }

    const cancelAddBtn = document.getElementById('clientsAddCancelBtn');
    if (cancelAddBtn && addModal) {
        cancelAddBtn.addEventListener('click', () => {
            addModal.style.display = 'none';
            resetTabs(); // Reset przy zamknięciu
        });
    }

    const saveAddBtn = document.getElementById('clientsAddSaveBtn');
    console.log('[clients.js] saveAddBtn element:', saveAddBtn);
    console.log('[clients.js] addModal element:', addModal);

    if (saveAddBtn && addModal) {
        console.log('[clients.js] Rejestruję event listener na przycisk Zapisz');
        saveAddBtn.addEventListener('click', () => {
            console.log('[clients.js] Kliknięto przycisk Zapisz Klienta');
            // Wyczyść poprzednie błędy
            const inputs = document.querySelectorAll('#clients-add-modal .clients-input');
            inputs.forEach(input => input.classList.remove('input-error-border', 'input-success-border'));
            document.querySelectorAll('#clients-add-modal .input-error').forEach(el => el.textContent = '');

            const name = document.getElementById('addClientName');
            const email = document.getElementById('addClientEmail');
            const phone = document.getElementById('addClientPhone');
            const deliveryZip = document.getElementById('addDeliveryZip');
            const deliveryCountry = document.getElementById('addDeliveryCountry');
            const invoiceZip = document.getElementById('addInvoiceZip');
            const nip = document.getElementById('addInvoiceNIP');

            let valid = true;

            // Walidacja nazwy klienta (wymagana)
            if (!name.value.trim()) {
                showFieldError('addClientName', 'error-addClientName', 'Nazwa klienta jest wymagana');
                valid = false;
            }

            // Walidacja email
            const emailResult = validateEmail(email.value.trim());
            if (!emailResult.valid) {
                showFieldError('addClientEmail', 'error-addClientEmail', emailResult.message);
                valid = false;
            }

            // Walidacja telefonu
            const phoneResult = validatePhone(phone.value.trim());
            if (!phoneResult.valid) {
                showFieldError('addClientPhone', 'error-addClientPhone', phoneResult.message);
                valid = false;
            }

            // Walidacja kodu pocztowego (dostawa)
            const deliveryCountryVal = deliveryCountry ? deliveryCountry.value : 'Polska';
            const deliveryZipResult = validatePostalCode(deliveryZip.value.trim(), deliveryCountryVal);
            if (!deliveryZipResult.valid) {
                showFieldError('addDeliveryZip', 'error-addDeliveryZip', deliveryZipResult.message);
                valid = false;
            }

            // Walidacja kodu pocztowego (faktura)
            const invoiceZipResult = validatePostalCode(invoiceZip.value.trim(), 'Polska');
            if (!invoiceZipResult.valid) {
                showFieldError('addInvoiceZip', 'error-addInvoiceZip', invoiceZipResult.message);
                valid = false;
            }

            // Walidacja NIP
            const nipResult = validateNIP(nip.value.trim());
            if (!nipResult.valid) {
                showFieldError('addInvoiceNIP', 'error-addInvoiceNIP', nipResult.message);
                valid = false;
            }

            if (!valid) return;

            const payload = {
                client_name: name.value.trim(),
                client_delivery_name: document.getElementById('addClientDeliveryName').value,
                email: email.value.trim(),
                phone: phone.value.trim(),
                notes: document.getElementById('addClientNotes').value.trim(),
                delivery: {
                    name: document.getElementById('addDeliveryName').value,
                    company: document.getElementById('addDeliveryCompany').value,
                    address: document.getElementById('addDeliveryAddress').value,
                    zip: document.getElementById('addDeliveryZip').value,
                    city: document.getElementById('addDeliveryCity').value,
                    region: document.getElementById('addDeliveryRegion').value,
                    country: document.getElementById('addDeliveryCountry').value
                },
                invoice: {
                    name: document.getElementById('addInvoiceName').value,
                    company: document.getElementById('addInvoiceCompany').value,
                    address: document.getElementById('addInvoiceAddress').value,
                    zip: invoiceZip.value.trim(),
                    city: document.getElementById('addInvoiceCity').value,
                    nip: nip.value.trim()
                }
            };

            fetch('/clients/api/add_client', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
                .then(res => {
                    if (!res.ok) {
                        return res.json().then(data => {
                            throw new Error(data.error || 'Błąd zapisu klienta');
                        });
                    }
                    return res.json();
                })
                .then(data => {
                    addModal.style.display = 'none';

                    // Pokaż modal sukcesu
                    const successModal = document.getElementById('clients-success-modal');
                    const successMessage = document.getElementById('successClientName');
                    successMessage.textContent = `Klient "${payload.client_name}" został pomyślnie dodany do bazy.`;
                    successModal.style.display = 'flex';

                    fetchClients();

                    // Wyczyść formularz - inputy
                    document.querySelectorAll('#clients-add-modal .clients-input:not(select)').forEach(input => {
                        input.value = '';
                        input.classList.remove('input-error-border', 'input-success-border');
                    });

                    // Reset selectów do domyślnych wartości
                    document.getElementById('addDeliveryRegion').value = '';
                    document.getElementById('addDeliveryCountry').value = 'Polska';
                })
                .catch(err => {
                    console.error('[add_client] Błąd:', err);
                    showToast(err.message || "Wystąpił błąd podczas zapisu klienta", "error");
                });
        });

        document.querySelectorAll('.clients-input').forEach(input => {
            input.addEventListener('blur', () => {
                const value = input.value.trim();
                let isValid = true;

                if (input.type === 'email') {
                    isValid = !value || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
                } else if (input.id.includes('Phone')) {
                    isValid = !value || /^[0-9+\s]+$/.test(value);
                } else if (input.id.includes('Zip')) {
                    isValid = !value || /^(\d{2}-\d{3}|\d{5})$/.test(value);
                } else if (input.id.includes('NIP')) {
                    isValid = !value || /^\d+$/.test(value);
                } else if (input.required || input.id === 'addClientName') {
                    isValid = !!value;
                }

                input.classList.remove('input-error-border', 'input-success-border');
                if (!isValid) {
                    input.classList.add('input-error-border');
                } else if (value) {
                    input.classList.add('input-success-border');
                }
            });
        });

        const gusBtn = document.getElementById('gusLookupBtn');
        if (gusBtn) {
            gusBtn.addEventListener('click', () => {
                const nipInput = document.getElementById('addInvoiceNIP');
                const nip = nipInput.value.trim();
                const nipError = document.getElementById('error-addInvoiceNIP');

                nipInput.classList.remove('input-error-border');
                nipError.textContent = '';

                if (!/^\d{10}$/.test(nip)) {
                    nipInput.classList.add('input-error-border');
                    nipError.textContent = "Podaj prawidłowy NIP (10 cyfr)";
                    return;
                }

                gusBtn.classList.add('loading');
                gusBtn.innerText = 'Ładowanie...';

                fetch(`/clients/api/gus_lookup?nip=${nip}`)
                    .then(res => res.json())
                    .then(data => {
                        console.log('[GUS API response]', data);
                        gusBtn.classList.remove('loading');
                        gusBtn.innerText = 'Pobrano dane ✅';
                        setTimeout(() => {
                            gusBtn.innerText = 'Pobierz z GUS';
                        }, 3000);

                        if (data && data.name) {
                            const address = data.address || '';
                            const addressParts = address.split(',');
                            const street = addressParts[0] || '';
                            const zipCity = addressParts[1] || '';
                            const zipMatch = zipCity.match(/\d{2}-\d{3}/);
                            const city = zipCity.replace(/\d{2}-\d{3}/, '').trim();

                            document.getElementById('addInvoiceName').value = data.name;
                            document.getElementById('addInvoiceCompany').value = data.company;
                            document.getElementById('addInvoiceAddress').value = street.trim();
                            document.getElementById('addInvoiceZip').value = zipMatch ? zipMatch[0] : '';
                            document.getElementById('addInvoiceCity').value = city;
                        } else {
                            nipError.textContent = "Nie znaleziono danych dla podanego NIP";
                        }
                    })
                    .catch(err => {
                        console.error('[GUS Lookup Error]', err);
                        gusBtn.classList.remove('loading');
                        gusBtn.innerText = 'Pobierz z GUS';
                        nipError.textContent = "Błąd połączenia z API GUS";
                    });
            });
        }
    }

    document.querySelectorAll('.clients-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', e => {
            if (e.target === overlay) {
                overlay.style.display = 'none';
            }
        });
    });
});

function showToast(message, isSuccess = true) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + (isSuccess ? 'toast-success' : 'toast-error');
    toast.style.display = 'block';
    toast.style.opacity = '1';

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.style.display = 'none', 400);
    }, 5000);
}

function redirectToQuote(quoteId) {
    console.log(`[clients] Przekierowanie do wyceny ID: ${quoteId}`);
    
    // Używamy dokładnie tych samych kluczy co w module calculator
    sessionStorage.setItem('openQuoteModal', quoteId);
    sessionStorage.setItem('openQuoteId', quoteId); // backup jak w calculator
    
    // Dodajemy też parametr URL jak w save_quote.js
    window.location.href = `/quotes?open_quote=${quoteId}`;
}

// ========== SCALONY MODAL SZCZEGÓŁÓW + EDYCJI ========== //

let currentEditClientId = null;

function enableEditMode() {
    console.log('=== enableEditMode START ===');
    console.log('currentEditClientId:', currentEditClientId);

    // Przełącz widoki
    document.getElementById('view-mode').style.display = 'none';
    document.getElementById('edit-mode').style.display = 'block';
    document.getElementById('view-actions').style.display = 'none';
    document.getElementById('edit-actions').style.display = 'flex';

    // Zmień tytuł
    document.getElementById('modalTitle').textContent = 'Edytuj dane klienta';

    // TYLKO JEDNORAZOWO załaduj dane - nie przy każdym przełączeniu
    const isAlreadyLoaded = document.getElementById('editClientName').dataset.loaded;
    console.log('isAlreadyLoaded (dataset.loaded):', isAlreadyLoaded);
    console.log('isAlreadyLoaded === "true":', isAlreadyLoaded === 'true');

    if (isAlreadyLoaded !== 'true' && currentEditClientId) {
        console.log('✅ Warunek spełniony - wywołuję loadClientDataForEdit');
        loadClientDataForEdit(currentEditClientId);

        // Oznacz jako załadowane
        document.getElementById('editClientName').dataset.loaded = 'true';
        console.log('Ustawiono dataset.loaded = true');
    } else {
        console.log('❌ Warunek NIE spełniony - dane już załadowane lub brak ID');
        console.log('  isAlreadyLoaded:', isAlreadyLoaded);
        console.log('  isAlreadyLoaded === "true":', isAlreadyLoaded === 'true');
        console.log('  currentEditClientId:', currentEditClientId);
    }

    console.log('=== enableEditMode END ===');
}

function disableEditMode() {
    // Przełącz widoki
    document.getElementById('view-mode').style.display = 'block';
    document.getElementById('edit-mode').style.display = 'none';
    document.getElementById('view-actions').style.display = 'flex';
    document.getElementById('edit-actions').style.display = 'none';

    // Zmień tytuł
    document.getElementById('modalTitle').textContent = 'Szczegóły klienta';
}

function loadClientDataForEdit(clientId) {
    console.log('=== loadClientDataForEdit START ===');
    console.log('Ładuję dane dla klienta ID:', clientId);

    fetch(`/clients/${clientId}/data`)
        .then(res => {
            console.log('Odpowiedź z serwera - status:', res.status);
            return res.json();
        })
        .then(client => {
            console.log('✅ Otrzymane dane z API:', client);

            // Dane podstawowe
            console.log('--- DANE PODSTAWOWE ---');
            console.log('client_number:', client.client_number);
            console.log('client_name:', client.client_name);
            console.log('email:', client.email);
            console.log('phone:', client.phone);

            document.getElementById('editClientName').value = client.client_number || '';
            document.getElementById('editClientDeliveryName').value = client.client_name || '';
            document.getElementById('editClientEmail').value = client.email || '';
            document.getElementById('editClientPhone').value = client.phone || '';
            document.getElementById('editClientNotes').value = client.notes || '';

            console.log('✅ Wypełniono pola podstawowe');

            // Adres dostawy
            console.log('--- ADRES DOSTAWY ---');
            console.log('delivery:', client.delivery);

            document.getElementById('editDeliveryName').value = client.delivery?.name || '';
            document.getElementById('editDeliveryCompany').value = client.delivery?.company || '';
            document.getElementById('editDeliveryAddress').value = client.delivery?.address || '';
            document.getElementById('editDeliveryZip').value = client.delivery?.zip || '';
            document.getElementById('editDeliveryCity').value = client.delivery?.city || '';
            document.getElementById('editDeliveryRegion').value = client.delivery?.region || '';
            document.getElementById('editDeliveryCountry').value = client.delivery?.country || '';

            console.log('✅ Wypełniono pola dostawy');

            // Dane do faktury
            console.log('--- DANE FAKTURY ---');
            console.log('invoice:', client.invoice);

            document.getElementById('editInvoiceName').value = client.invoice?.name || '';
            document.getElementById('editInvoiceCompany').value = client.invoice?.company || '';
            document.getElementById('editInvoiceAddress').value = client.invoice?.address || '';
            document.getElementById('editInvoiceZip').value = client.invoice?.zip || '';
            document.getElementById('editInvoiceCity').value = client.invoice?.city || '';
            document.getElementById('editInvoiceNIP').value = client.invoice?.nip || '';

            console.log('✅ Wypełniono pola faktury');

            // WERYFIKACJA - sprawdź czy pola rzeczywiście mają wartości
            console.log('--- WERYFIKACJA PÓL ---');
            console.log('editClientName.value:', document.getElementById('editClientName').value);
            console.log('editClientEmail.value:', document.getElementById('editClientEmail').value);
            console.log('editDeliveryName.value:', document.getElementById('editDeliveryName').value);
            console.log('editInvoiceName.value:', document.getElementById('editInvoiceName').value);

            console.log('=== loadClientDataForEdit END ===');
        })
        .catch(err => {
            console.error('❌ Błąd podczas ładowania danych klienta:', err);
            showToast('Błąd podczas ładowania danych klienta', false);
        });
}

// ========== EVENT LISTENERS DLA NOWEGO MODALA ========== //

document.addEventListener('DOMContentLoaded', () => {
    // Przycisk OK w modalu sukcesu
    const successModalOkBtn = document.getElementById('successModalOkBtn');
    const successModal = document.getElementById('clients-success-modal');
    if (successModalOkBtn && successModal) {
        successModalOkBtn.addEventListener('click', () => {
            successModal.style.display = 'none';
        });
        // Zamknij też po kliknięciu w tło
        successModal.addEventListener('click', (e) => {
            if (e.target === successModal) {
                successModal.style.display = 'none';
            }
        });
    }

    // Przycisk Anuluj w trybie edycji
    const cancelEditBtn = document.getElementById('cancelEditBtn');
    if (cancelEditBtn) {
        cancelEditBtn.addEventListener('click', disableEditMode);
    }

    // Drugi przycisk Zamknij (w trybie wyświetlania)
    const closeBtn2 = document.getElementById('clientsDetailsCloseBtn2');
    if (closeBtn2) {
        closeBtn2.addEventListener('click', () => {
            document.getElementById('clients-details-modal').style.display = 'none';
        });
    }

    // Przycisk Zapisz zmiany
    const saveEditBtn = document.getElementById('saveEditBtn');
    if (saveEditBtn) {
        saveEditBtn.addEventListener('click', saveClientChanges);
    }
    
    // Przycisk GUS w edycji
    const editGusBtn = document.getElementById('editGusLookupBtn');
    if (editGusBtn) {
        editGusBtn.addEventListener('click', () => {
            const nipInput = document.getElementById('editInvoiceNIP');
            const nip = nipInput.value.trim();
            const nipError = document.getElementById('error-editInvoiceNIP');

            nipInput.classList.remove('input-error-border');
            nipError.textContent = '';

            if (!/^\d{10}$/.test(nip)) {
                nipInput.classList.add('input-error-border');
                nipError.textContent = "Podaj prawidłowy NIP (10 cyfr)";
                return;
            }

            editGusBtn.classList.add('loading');
            editGusBtn.innerText = 'Ładowanie...';

            fetch(`/clients/api/gus_lookup?nip=${nip}`)
                .then(res => res.json())
                .then(data => {
                    console.log('[GUS API response in edit]', data);
                    editGusBtn.classList.remove('loading');
                    editGusBtn.innerText = 'Pobrano dane ✅';
                    setTimeout(() => {
                        editGusBtn.innerText = 'Pobierz z GUS';
                    }, 3000);

                    if (data && data.name) {
                        const address = data.address || '';
                        const addressParts = address.split(',');
                        const street = addressParts[0] || '';
                        const zipCity = addressParts[1] || '';
                        const zipMatch = zipCity.match(/\d{2}-\d{3}/);
                        const city = zipCity.replace(/\d{2}-\d{3}/, '').trim();

                        document.getElementById('editInvoiceName').value = data.name;
                        document.getElementById('editInvoiceCompany').value = data.company;
                        document.getElementById('editInvoiceAddress').value = street.trim();
                        document.getElementById('editInvoiceZip').value = zipMatch ? zipMatch[0] : '';
                        document.getElementById('editInvoiceCity').value = city;
                    } else {
                        nipError.textContent = "Nie znaleziono danych dla podanego NIP";
                    }
                })
                .catch(err => {
                    console.error('[GUS Lookup Error in edit]', err);
                    editGusBtn.classList.remove('loading');
                    editGusBtn.innerText = 'Pobierz z GUS';
                    nipError.textContent = "Błąd połączenia z API GUS";
                });
        });
    }
});

function saveClientChanges() {
    console.log('=== saveClientChanges START ===');

    if (!currentEditClientId) {
        console.error('❌ Brak ID klienta do zapisu');
        return;
    }

    console.log('Zapisuję zmiany dla klienta ID:', currentEditClientId);

    // Pobierz wartości pól
    const clientName = document.getElementById('editClientName').value.trim();
    const email = document.getElementById('editClientEmail').value.trim();

    console.log('Pobrane wartości:');
    console.log('  clientName:', clientName);
    console.log('  email:', email);

    // Walidacja wymaganych pól
    if (!clientName) {
        showToast('Nazwa klienta jest wymagana', false);
        document.getElementById('editClientName').focus();
        return;
    }

    // Email jest opcjonalny, ale jeśli podany to musi być poprawny
    if (email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            showToast('Podaj poprawny adres email', false);
            document.getElementById('editClientEmail').focus();
            return;
        }
    }

    const payload = {
        client_name: clientName,
        client_delivery_name: document.getElementById('editClientDeliveryName').value.trim(),
        email: email,
        phone: document.getElementById('editClientPhone').value.trim(),
        notes: document.getElementById('editClientNotes').value.trim(),
        delivery: {
            name: document.getElementById('editDeliveryName').value.trim(),
            company: document.getElementById('editDeliveryCompany').value.trim(),
            address: document.getElementById('editDeliveryAddress').value.trim(),
            zip: document.getElementById('editDeliveryZip').value.trim(),
            city: document.getElementById('editDeliveryCity').value.trim(),
            region: document.getElementById('editDeliveryRegion').value.trim(),
            country: document.getElementById('editDeliveryCountry').value.trim()
        },
        invoice: {
            name: document.getElementById('editInvoiceName').value.trim(),
            company: document.getElementById('editInvoiceCompany').value.trim(),
            address: document.getElementById('editInvoiceAddress').value.trim(),
            zip: document.getElementById('editInvoiceZip').value.trim(),
            city: document.getElementById('editInvoiceCity').value.trim(),
            nip: document.getElementById('editInvoiceNIP').value.trim()
        }
    };

    fetch(`/clients/${currentEditClientId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => {
        if (!res.ok) {
            return res.json().then(data => {
                throw new Error(data.error || 'Błąd zapisu klienta');
            });
        }
        return res.json();
    })
    .then(() => {
        showToast('Zapisano dane klienta ✔');
        disableEditMode();

        // Odśwież dane w trybie wyświetlania
        showClientDetails(currentEditClientId);

        // Odśwież listę klientów
        fetchClients();
    })
    .catch(err => {
        console.error('❌ Błąd podczas zapisu:', err);
        showToast(err.message || 'Nie udało się zapisać zmian', false);
    });
}

// ========== AKTUALIZACJA FUNKCJI showClientDetails ========== //
// ========== KOPIOWANIE DANYCH Z DOSTAWY DO FAKTURY ========== //

function copyDeliveryToInvoice() {
    // Pobierz dane z pól dostawy
    const deliveryName = document.getElementById('editDeliveryName').value;
    const deliveryCompany = document.getElementById('editDeliveryCompany').value;
    const deliveryAddress = document.getElementById('editDeliveryAddress').value;
    const deliveryZip = document.getElementById('editDeliveryZip').value;
    const deliveryCity = document.getElementById('editDeliveryCity').value;

    // Wstaw do pól faktury
    document.getElementById('editInvoiceName').value = deliveryName;
    document.getElementById('editInvoiceCompany').value = deliveryCompany;
    document.getElementById('editInvoiceAddress').value = deliveryAddress;
    document.getElementById('editInvoiceZip').value = deliveryZip;
    document.getElementById('editInvoiceCity').value = deliveryCity;
    
    // Dodaj wizualny feedback
    const copyBtn = event.target.closest('.copy-delivery-btn');
    if (copyBtn) {
        const originalText = copyBtn.innerHTML;
        const originalClass = copyBtn.className;
        
        copyBtn.className = 'copy-delivery-btn success';
        copyBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;
        
        setTimeout(() => {
            copyBtn.className = originalClass;
            copyBtn.innerHTML = originalText;
        }, 2000);
    }
    
    // Animacja skopiowanych pól
    const invoiceFields = [invoiceNameEl, invoiceCompanyEl, invoiceAddressEl, invoiceZipEl, invoiceCityEl];
    
    invoiceFields.forEach(field => {
        if (field && field.value) {
            field.classList.add('copied-field');
            setTimeout(() => {
                field.classList.remove('copied-field');
            }, 1500);
        }
    });
    
    showToast('Dane z adresu dostawy zostały skopiowane!');
}

// ========== KOPIOWANIE DANYCH Z FAKTURY DO DOSTAWY ========== //

function copyInvoiceToDelivery() {
    // Pobierz dane z pól faktury
    const invoiceName = document.getElementById('editInvoiceName').value;
    const invoiceCompany = document.getElementById('editInvoiceCompany').value;
    const invoiceAddress = document.getElementById('editInvoiceAddress').value;
    const invoiceZip = document.getElementById('editInvoiceZip').value;
    const invoiceCity = document.getElementById('editInvoiceCity').value;

    // Wstaw do pól dostawy
    document.getElementById('editDeliveryName').value = invoiceName;
    document.getElementById('editDeliveryCompany').value = invoiceCompany;
    document.getElementById('editDeliveryAddress').value = invoiceAddress;
    document.getElementById('editDeliveryZip').value = invoiceZip;
    document.getElementById('editDeliveryCity').value = invoiceCity;
    
    // Feedback wizualny
    const copyBtn = event.target.closest('.copy-invoice-btn');
    if (copyBtn) {
        const originalText = copyBtn.innerHTML;
        const originalClass = copyBtn.className;
        
        copyBtn.className = 'copy-invoice-btn success';
        copyBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;
        
        setTimeout(() => {
            copyBtn.className = originalClass;
            copyBtn.innerHTML = originalText;
        }, 2000);
    }
    
    // Animacja pól
    const deliveryFields = [deliveryNameEl, deliveryCompanyEl, deliveryAddressEl, deliveryZipEl, deliveryCityEl];
    
    deliveryFields.forEach(field => {
        if (field && field.value) {
            field.classList.add('copied-field');
            setTimeout(() => {
                field.classList.remove('copied-field');
            }, 1500);
        }
    });
    
    showToast('Dane z faktury zostały skopiowane do adresu dostawy!');
}

// ========== FUNKCJE DLA MODALU DODAWANIA KLIENTA ========== //

function copyDeliveryToInvoiceAdd() {
    console.log('[copyDeliveryToInvoiceAdd] Kopiowanie w modalu dodawania');
    
    // Pobierz dane z pól dostawy (prefix "add")
    const deliveryName = document.getElementById('addDeliveryName').value;
    const deliveryCompany = document.getElementById('addDeliveryCompany').value;
    const deliveryAddress = document.getElementById('addDeliveryAddress').value;
    const deliveryZip = document.getElementById('addDeliveryZip').value;
    const deliveryCity = document.getElementById('addDeliveryCity').value;
    
    // Wstaw do pól faktury (prefix "add")
    document.getElementById('addInvoiceName').value = deliveryName;
    document.getElementById('addInvoiceCompany').value = deliveryCompany;
    document.getElementById('addInvoiceAddress').value = deliveryAddress;
    document.getElementById('addInvoiceZip').value = deliveryZip;
    document.getElementById('addInvoiceCity').value = deliveryCity;
    
    // Dodaj wizualny feedback
    const copyBtn = event.target.closest('.copy-delivery-btn');
    if (copyBtn) {
        const originalText = copyBtn.innerHTML;
        const originalClass = copyBtn.className;
        
        copyBtn.className = 'copy-delivery-btn success';
        copyBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;
        
        setTimeout(() => {
            copyBtn.className = originalClass;
            copyBtn.innerHTML = originalText;
        }, 2000);
    }
    
    // Animacja skopiowanych pól
    const invoiceFields = ['addInvoiceName', 'addInvoiceCompany', 'addInvoiceAddress', 'addInvoiceZip', 'addInvoiceCity'];
    
    invoiceFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field && field.value) {
            field.classList.add('copied-field');
            setTimeout(() => {
                field.classList.remove('copied-field');
            }, 1500);
        }
    });
    
    showToast('Dane z adresu dostawy zostały skopiowane!');
}

function copyInvoiceToDeliveryAdd() {
    console.log('[copyInvoiceToDeliveryAdd] Kopiowanie z faktury do dostawy w modalu dodawania');
    
    // Pobierz dane z pól faktury (prefix "add")
    const invoiceName = document.getElementById('addInvoiceName').value;
    const invoiceCompany = document.getElementById('addInvoiceCompany').value;
    const invoiceAddress = document.getElementById('addInvoiceAddress').value;
    const invoiceZip = document.getElementById('addInvoiceZip').value;
    const invoiceCity = document.getElementById('addInvoiceCity').value;
    
    // Wstaw do pól dostawy (prefix "add")
    document.getElementById('addDeliveryName').value = invoiceName;
    document.getElementById('addDeliveryCompany').value = invoiceCompany;
    document.getElementById('addDeliveryAddress').value = invoiceAddress;
    document.getElementById('addDeliveryZip').value = invoiceZip;
    document.getElementById('addDeliveryCity').value = invoiceCity;
    
    // Dodaj wizualny feedback
    const copyBtn = event.target.closest('.copy-invoice-btn');
    if (copyBtn) {
        const originalText = copyBtn.innerHTML;
        const originalClass = copyBtn.className;
        
        copyBtn.className = 'copy-invoice-btn success';
        copyBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            Skopiowano!
        `;
        
        setTimeout(() => {
            copyBtn.className = originalClass;
            copyBtn.innerHTML = originalText;
        }, 2000);
    }
    
    // Animacja skopiowanych pól
    const deliveryFields = ['addDeliveryName', 'addDeliveryCompany', 'addDeliveryAddress', 'addDeliveryZip', 'addDeliveryCity'];
    
    deliveryFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field && field.value) {
            field.classList.add('copied-field');
            setTimeout(() => {
                field.classList.remove('copied-field');
            }, 1500);
        }
    });

    showToast('Dane z faktury zostały skopiowane do adresu dostawy!');
}

// ============================================
// WYSZUKIWANIE W BAZIE DANYCH
// ============================================

const searchDatabaseModal = document.getElementById('search-database-modal');
const searchInDatabaseBtn = document.getElementById('searchInDatabaseBtn');
const closeDatabaseSearchBtn = document.getElementById('closeDatabaseSearchBtn');
const databaseSearchInput = document.getElementById('databaseSearchInput');
const databaseSearchResults = document.getElementById('databaseSearchResults');

// Otwórz modal wyszukiwania
searchInDatabaseBtn.addEventListener('click', () => {
    searchDatabaseModal.style.display = 'flex';
    databaseSearchInput.value = '';
    databaseSearchResults.style.display = 'none';
    databaseSearchResults.innerHTML = '';
    setTimeout(() => databaseSearchInput.focus(), 100);
});

// Zamknij modal
closeDatabaseSearchBtn.addEventListener('click', () => {
    searchDatabaseModal.style.display = 'none';
});

// Zamknij modal przy kliknięciu poza nim
searchDatabaseModal.addEventListener('click', (e) => {
    if (e.target === searchDatabaseModal) {
        searchDatabaseModal.style.display = 'none';
    }
});

// Debounce function
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

// Funkcja wyszukiwania
const handleDatabaseSearch = debounce(async function(value) {
    const query = value.trim();

    if (query.length < 3) {
        databaseSearchResults.style.display = 'none';
        databaseSearchResults.innerHTML = '';
        return;
    }

    try {
        const res = await fetch(`/clients/search_in_database?q=${encodeURIComponent(query)}`);
        const clients = await res.json();

        let html = '';

        if (!clients || clients.length === 0) {
            html = '<div class="db-search-no-results">Nie znaleziono klientów</div>';
        } else {
            html = clients.map(client => {
                // Przygotuj badge
                let badge = '';
                if (client.is_own_client) {
                    badge = '<span class="db-search-badge db-search-badge-own">Twój klient</span>';
                } else {
                    badge = '<span class="db-search-badge db-search-badge-other">Utworzony przez innego handlowca</span>';
                }

                // Przygotuj dane kontaktowe (jeśli dostępne)
                let contactInfo = '';
                if (client.show_full_data) {
                    const parts = [];
                    if (client.email) parts.push(`Email: ${client.email}`);
                    if (client.phone) parts.push(`Tel: ${client.phone}`);
                    if (client.invoice_nip) parts.push(`NIP: ${client.invoice_nip}`);
                    if (parts.length > 0) {
                        contactInfo = `<div class="db-search-contact">${parts.join(' • ')}</div>`;
                    }
                } else {
                    contactInfo = '<div class="db-search-contact db-search-hidden">Dane kontaktowe ukryte (aktywny klient)</div>';
                }

                // Data ostatniej wyceny
                let quoteInfo = '';
                if (client.latest_quote_date) {
                    quoteInfo = `<div class="db-search-quote-date">Ostatnia wycena: ${client.latest_quote_date}</div>`;
                } else {
                    quoteInfo = '<div class="db-search-quote-date">Brak wycen w systemie</div>';
                }

                return `
                    <div class="db-search-result-item">
                        <div class="db-search-result-header">
                            <div class="db-search-result-names">
                                <div class="db-search-result-name">${client.client_number || '-'}</div>
                                <div class="db-search-result-fullname">${client.client_name || '-'}</div>
                            </div>
                            ${badge}
                        </div>
                        ${contactInfo}
                        ${quoteInfo}
                    </div>
                `;
            }).join('');
        }

        databaseSearchResults.innerHTML = html;
        databaseSearchResults.style.display = 'block';

    } catch (err) {
        console.error('[search_in_database] Błąd fetch:', err);
        databaseSearchResults.innerHTML = '<div class="db-search-no-results">Błąd podczas wyszukiwania</div>';
        databaseSearchResults.style.display = 'block';
    }
}, 300);

// Event listener dla inputa
databaseSearchInput.addEventListener('input', (e) => {
    handleDatabaseSearch(e.target.value);
});