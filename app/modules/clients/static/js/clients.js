// static/js/clients.js

let clients = [];
let currentPage = 1;
let rowsPerPage = 20;
let currentSortKey = 'client_name';
let currentSortAsc = true;
let quotesPerPage = 10;
let currentQuotePage = 1;
let allQuotes = [];
let editedClientId = null;

const tableBody = document.getElementById('clients-table-body');
const searchInput = document.getElementById('search-input');
const rowsSelect = document.getElementById('rows-per-page');
const paginationControls = document.getElementById('pagination-controls');

function fetchClients() {
    fetch('/clients/api/clients')
        .then(res => res.json())
        .then(data => {
            clients = data;
            renderTable();
        });
}

function renderTable() {
    const filtered = clients.filter(c => {
        const query = searchInput.value.toLowerCase();
        return (
            (c.client_number || '').toLowerCase().includes(query) ||
            (c.client_name || '').toLowerCase().includes(query) ||
            (c.client_delivery_name || '').toLowerCase().includes(query) ||
            (c.email || '').toLowerCase().includes(query) ||
            (c.phone || '').toLowerCase().includes(query)
        );
    });

    filtered.sort((a, b) => {
        const valA = a[currentSortKey] || '';
        const valB = b[currentSortKey] || '';
        return currentSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
    });

    const start = (currentPage - 1) * rowsPerPage;
    const end = start + rowsPerPage;
    const pageItems = filtered.slice(start, end);

    tableBody.innerHTML = '';
    pageItems.forEach(client => {
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

    renderPagination(filtered.length);
}

function renderPagination(total) {
    const pageCount = Math.ceil(total / rowsPerPage);
    paginationControls.innerHTML = '';
    for (let i = 1; i <= pageCount; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        if (i === currentPage) btn.classList.add('active');
        btn.addEventListener('click', () => {
            currentPage = i;
            renderTable();
        });
        paginationControls.appendChild(btn);
    }
}

searchInput.addEventListener('input', renderTable);
rowsSelect.addEventListener('change', () => {
    rowsPerPage = parseInt(rowsSelect.value);
    currentPage = 1;
    renderTable();
});

function showClientDetails(clientId) {
    currentEditClientId = clientId; // Zapisz ID dla trybu edycji
    
    // RESETUJ flagę załadowania dla nowego klienta
    const editNameField = document.getElementById('editClientName');
    if (editNameField) {
        editNameField.dataset.loaded = 'false';
    }
    
    fetch(`/clients/${clientId}/data`)
        .then(res => res.json())
        .then(client => {
            document.getElementById('detailClientName').textContent = client.client_number || '---';
            document.getElementById('detailClientDeliveryName').textContent = client.client_name || '---';
            document.getElementById('detailClientEmail').textContent = client.email || '---';
            document.getElementById('detailClientPhone').textContent = client.phone || '---';
            
            loadClientQuotes(clientId);
            
            // Upewnij się, że jesteśmy w trybie wyświetlania
            disableEditMode();
            
            document.getElementById('clients-details-modal').style.display = 'flex';
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

document.getElementById('clientsCancelBtn').addEventListener('click', () => {
    document.getElementById('clients-edit-modal').style.display = 'none';
});

document.getElementById('clientsSaveBtn').addEventListener('click', () => {
    if (!editedClientId) return;

    const payload = {
        client_name: document.getElementById('editClientName').value,
        client_delivery_name: document.getElementById('editClientDeliveryName').value,
        email: document.getElementById('editClientEmail').value,
        phone: document.getElementById('editClientPhone').value,
        source: '',
        delivery: {
            name: document.getElementById('editDeliveryName').value,
            company: document.getElementById('editDeliveryCompany').value,
            address: document.getElementById('editDeliveryAddress').value,
            zip: document.getElementById('editDeliveryZip').value,
            city: document.getElementById('editDeliveryCity').value,
            region: document.getElementById('editDeliveryRegion').value,
            country: document.getElementById('editDeliveryCountry').value
        },
        invoice: {
            name: document.getElementById('editInvoiceName').value,
            company: document.getElementById('editInvoiceCompany').value,
            address: document.getElementById('editInvoiceAddress').value,
            zip: document.getElementById('editInvoiceZip').value,
            city: document.getElementById('editInvoiceCity').value,
            nip: document.getElementById('editInvoiceNIP').value
        }
    };

    fetch(`/clients/${editedClientId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(res => {
            if (!res.ok) throw new Error('Błąd zapisu klienta');
            return res.json();
        })
        .then(() => {
            showToast('Zapisano dane klienta ✔');
            document.getElementById('clients-edit-modal').style.display = 'none';
            fetchClients();
        })
        .catch(err => {
            console.error('❌ Błąd podczas zapisu:', err);
            showToast('Nie udało się zapisać zmian ❌', false);
        });
});


// ========== DOMContentLoaded ========== //
document.addEventListener('DOMContentLoaded', () => {
    fetchClients();

    const addBtn = document.getElementById('addClientBtn');
    const addModal = document.getElementById('clients-add-modal');

    if (addBtn && addModal) {
        addBtn.addEventListener('click', () => {
            addModal.style.display = 'flex';
        });
    }

    const cancelAddBtn = document.getElementById('clientsAddCancelBtn');
    if (cancelAddBtn && addModal) {
        cancelAddBtn.addEventListener('click', () => {
            addModal.style.display = 'none';
        });
    }

    const saveAddBtn = document.getElementById('clientsAddSaveBtn');
    if (saveAddBtn && addModal) {
        saveAddBtn.addEventListener('click', () => {
            const inputs = document.querySelectorAll('.clients-input');
            inputs.forEach(input => input.classList.remove('input-error-border', 'input-success-border'));

            const name = document.getElementById('addClientName');
            const email = document.getElementById('addClientEmail');
            const phone = document.getElementById('addClientPhone');
            const zip = document.getElementById('addInvoiceZip');
            const nip = document.getElementById('addInvoiceNIP');

            let valid = true;

            if (!name.value.trim()) {
                name.classList.add('input-error-border');
                valid = false;
            }

            if (email.value.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
                email.classList.add('input-error-border');
                valid = false;
            }

            if (phone.value.trim() && !/^[0-9+\s]+$/.test(phone.value)) {
                phone.classList.add('input-error-border');
                valid = false;
            }

            if (zip.value.trim() && !/^(\d{2}-\d{3}|\d{5})$/.test(zip.value)) {
                zip.classList.add('input-error-border');
                valid = false;
            }

            if (nip.value.trim() && !/^\d+$/.test(nip.value)) {
                nip.classList.add('input-error-border');
                document.getElementById('error-addInvoiceNIP').textContent = "Nieprawidłowy NIP";
                valid = false;
            } else {
                document.getElementById('error-addInvoiceNIP').textContent = "";
            }

            if (!valid) return;

            const payload = {
                client_name: name.value.trim(),
                client_delivery_name: document.getElementById('addClientDeliveryName').value,
                email: email.value.trim(),
                phone: phone.value.trim(),
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
                    zip: zip.value.trim(),
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
                    if (!res.ok) throw new Error('Błąd zapisu klienta');
                    addModal.style.display = 'none';
                    showToast("Dodano nowego klienta", "success");
                    fetchClients();
                })
                .catch(err => {
                    console.error(err);
                    showToast("Wystąpił błąd podczas zapisu klienta", "error");
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
    console.log('[enableEditMode] Przełączam na tryb edycji');
    
    // Przełącz widoki
    document.getElementById('view-mode').style.display = 'none';
    document.getElementById('edit-mode').style.display = 'block';
    document.getElementById('view-actions').style.display = 'none';
    document.getElementById('edit-actions').style.display = 'flex';
    
    // Zmień tytuł
    document.getElementById('modalTitle').textContent = 'Edytuj dane klienta';
    
    // TYLKO JEDNORAZOWO załaduj dane - nie przy każdym przełączeniu
    const isAlreadyLoaded = document.getElementById('editClientName').dataset.loaded;
    
    if (!isAlreadyLoaded && currentEditClientId) {
        console.log('[enableEditMode] Ładuję dane po raz pierwszy...');
        loadClientDataForEdit(currentEditClientId);
        
        // Oznacz jako załadowane
        document.getElementById('editClientName').dataset.loaded = 'true';
    } else {
        console.log('[enableEditMode] Dane już załadowane - pomijam loadClientDataForEdit');
    }
}

function disableEditMode() {
    console.log('[disableEditMode] Powrót do trybu wyświetlania');
    
    // Przełącz widoki
    document.getElementById('view-mode').style.display = 'block';
    document.getElementById('edit-mode').style.display = 'none';
    document.getElementById('view-actions').style.display = 'flex';
    document.getElementById('edit-actions').style.display = 'none';
    
    // Zmień tytuł
    document.getElementById('modalTitle').textContent = 'Szczegóły klienta';
}

function loadClientDataForEdit(clientId) {
    console.log('[loadClientDataForEdit] START - Ładowanie danych klienta ID:', clientId);
    
    fetch(`/clients/${clientId}/data`)
        .then(res => res.json())
        .then(client => {
            console.log('[loadClientDataForEdit] OTRZYMANE DANE KLIENTA:', client);
            console.log('[loadClientDataForEdit] client.invoice:', client.invoice);
            
            // Dane podstawowe
            document.getElementById('editClientName').value = client.client_name || '';
            document.getElementById('editClientDeliveryName').value = client.client_number || '';
            document.getElementById('editClientEmail').value = client.email || '';
            document.getElementById('editClientPhone').value = client.phone || '';
            
            // Adres dostawy
            document.getElementById('editDeliveryName').value = client.delivery?.name || '';
            document.getElementById('editDeliveryCompany').value = client.delivery?.company || '';
            document.getElementById('editDeliveryAddress').value = client.delivery?.address || '';
            document.getElementById('editDeliveryZip').value = client.delivery?.zip || '';
            document.getElementById('editDeliveryCity').value = client.delivery?.city || '';
            document.getElementById('editDeliveryRegion').value = client.delivery?.region || '';
            document.getElementById('editDeliveryCountry').value = client.delivery?.country || '';
            
            // Dane do faktury z logami
            console.log('[loadClientDataForEdit] WYPEŁNIANIE PÓL FAKTURY:');
            
            const invoiceName = client.invoice?.name || '';
            const invoiceCompany = client.invoice?.company || '';
            const invoiceAddress = client.invoice?.address || '';
            const invoiceZip = client.invoice?.zip || '';
            const invoiceCity = client.invoice?.city || '';
            const invoiceNip = client.invoice?.nip || '';
            
            console.log('- invoice name:', invoiceName);
            console.log('- invoice company:', invoiceCompany);
            console.log('- invoice address:', invoiceAddress);
            console.log('- invoice zip:', invoiceZip);
            console.log('- invoice city:', invoiceCity);
            console.log('- invoice nip:', invoiceNip);
            
            document.getElementById('editInvoiceName').value = invoiceName;
            document.getElementById('editInvoiceCompany').value = invoiceCompany;
            document.getElementById('editInvoiceAddress').value = invoiceAddress;
            document.getElementById('editInvoiceZip').value = invoiceZip;
            document.getElementById('editInvoiceCity').value = invoiceCity;
            document.getElementById('editInvoiceNIP').value = invoiceNip;
            
            // Sprawdź czy pola są rzeczywiście wypełnione
            console.log('[loadClientDataForEdit] WERYFIKACJA WYPEŁNIENIA:');
            console.log('- editInvoiceName.value:', document.getElementById('editInvoiceName').value);
            console.log('- editInvoiceCompany.value:', document.getElementById('editInvoiceCompany').value);
            console.log('- editInvoiceAddress.value:', document.getElementById('editInvoiceAddress').value);
            console.log('- editInvoiceZip.value:', document.getElementById('editInvoiceZip').value);
            console.log('- editInvoiceCity.value:', document.getElementById('editInvoiceCity').value);
            
            console.log('[loadClientDataForEdit] END');
        })
        .catch(err => {
            console.error('[loadClientDataForEdit] Błąd:', err);
            showToast('Błąd podczas ładowania danych klienta', false);
        });
}

// ========== EVENT LISTENERS DLA NOWEGO MODALA ========== //

document.addEventListener('DOMContentLoaded', () => {
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
    if (!currentEditClientId) {
        console.error('[saveClientChanges] Brak ID klienta');
        return;
    }
    
    const payload = {
        client_name: document.getElementById('editClientName').value.trim(),
        client_delivery_name: document.getElementById('editClientDeliveryName').value.trim(),
        email: document.getElementById('editClientEmail').value.trim(),
        phone: document.getElementById('editClientPhone').value.trim(),
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
        if (!res.ok) throw new Error('Błąd zapisu klienta');
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
        showToast('Nie udało się zapisać zmian ❌', false);
    });
}

// ========== AKTUALIZACJA FUNKCJI showClientDetails ========== //
// ========== KOPIOWANIE DANYCH Z DOSTAWY DO FAKTURY ========== //

function copyDeliveryToInvoice() {
    console.log('[copyDeliveryToInvoice] Kopiowanie danych z adresu dostawy');
    
    // UŻYWAJ querySelectorAll i weź WIDOCZNY element (ostatni)
    const deliveryNameEls = document.querySelectorAll('#editDeliveryName');
    const deliveryCompanyEls = document.querySelectorAll('#editDeliveryCompany');
    const deliveryAddressEls = document.querySelectorAll('#editDeliveryAddress');
    const deliveryZipEls = document.querySelectorAll('#editDeliveryZip');
    const deliveryCityEls = document.querySelectorAll('#editDeliveryCity');
    
    // Weź ostatni (widoczny) element z każdej listy
    const deliveryNameEl = deliveryNameEls[deliveryNameEls.length - 1];
    const deliveryCompanyEl = deliveryCompanyEls[deliveryCompanyEls.length - 1];
    const deliveryAddressEl = deliveryAddressEls[deliveryAddressEls.length - 1];
    const deliveryZipEl = deliveryZipEls[deliveryZipEls.length - 1];
    const deliveryCityEl = deliveryCityEls[deliveryCityEls.length - 1];
    
    // Pobierz dane z pól dostawy
    const deliveryName = deliveryNameEl ? deliveryNameEl.value : '';
    const deliveryCompany = deliveryCompanyEl ? deliveryCompanyEl.value : '';
    const deliveryAddress = deliveryAddressEl ? deliveryAddressEl.value : '';
    const deliveryZip = deliveryZipEl ? deliveryZipEl.value : '';
    const deliveryCity = deliveryCityEl ? deliveryCityEl.value : '';
    
    // Elementy docelowe (faktury) - także z querySelectorAll
    const invoiceNameEls = document.querySelectorAll('#editInvoiceName');
    const invoiceCompanyEls = document.querySelectorAll('#editInvoiceCompany');
    const invoiceAddressEls = document.querySelectorAll('#editInvoiceAddress');
    const invoiceZipEls = document.querySelectorAll('#editInvoiceZip');
    const invoiceCityEls = document.querySelectorAll('#editInvoiceCity');
    
    const invoiceNameEl = invoiceNameEls[invoiceNameEls.length - 1];
    const invoiceCompanyEl = invoiceCompanyEls[invoiceCompanyEls.length - 1];
    const invoiceAddressEl = invoiceAddressEls[invoiceAddressEls.length - 1];
    const invoiceZipEl = invoiceZipEls[invoiceZipEls.length - 1];
    const invoiceCityEl = invoiceCityEls[invoiceCityEls.length - 1];
    
    // Wstaw do pól faktury
    if (invoiceNameEl) invoiceNameEl.value = deliveryName;
    if (invoiceCompanyEl) invoiceCompanyEl.value = deliveryCompany;
    if (invoiceAddressEl) invoiceAddressEl.value = deliveryAddress;
    if (invoiceZipEl) invoiceZipEl.value = deliveryZip;
    if (invoiceCityEl) invoiceCityEl.value = deliveryCity;
    
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
    console.log('[copyInvoiceToDelivery] START - Kopiowanie danych z faktury do dostawy');
    
    // UŻYWAJ querySelectorAll i weź WIDOCZNY element (ostatni)
    const invoiceNameEls = document.querySelectorAll('#editInvoiceName');
    const invoiceCompanyEls = document.querySelectorAll('#editInvoiceCompany');
    const invoiceAddressEls = document.querySelectorAll('#editInvoiceAddress');
    const invoiceZipEls = document.querySelectorAll('#editInvoiceZip');
    const invoiceCityEls = document.querySelectorAll('#editInvoiceCity');
    
    // Weź ostatni (widoczny) element z każdej listy
    const invoiceNameEl = invoiceNameEls[invoiceNameEls.length - 1];
    const invoiceCompanyEl = invoiceCompanyEls[invoiceCompanyEls.length - 1];
    const invoiceAddressEl = invoiceAddressEls[invoiceAddressEls.length - 1];
    const invoiceZipEl = invoiceZipEls[invoiceZipEls.length - 1];
    const invoiceCityEl = invoiceCityEls[invoiceCityEls.length - 1];
    
    // Pobierz wartości z widocznych elementów
    const invoiceName = invoiceNameEl ? invoiceNameEl.value : '';
    const invoiceCompany = invoiceCompanyEl ? invoiceCompanyEl.value : '';
    const invoiceAddress = invoiceAddressEl ? invoiceAddressEl.value : '';
    const invoiceZip = invoiceZipEl ? invoiceZipEl.value : '';
    const invoiceCity = invoiceCityEl ? invoiceCityEl.value : '';
    
    // Elementy docelowe (także z querySelectorAll)
    const deliveryNameEls = document.querySelectorAll('#editDeliveryName');
    const deliveryCompanyEls = document.querySelectorAll('#editDeliveryCompany');
    const deliveryAddressEls = document.querySelectorAll('#editDeliveryAddress');
    const deliveryZipEls = document.querySelectorAll('#editDeliveryZip');
    const deliveryCityEls = document.querySelectorAll('#editDeliveryCity');
    
    const deliveryNameEl = deliveryNameEls[deliveryNameEls.length - 1];
    const deliveryCompanyEl = deliveryCompanyEls[deliveryCompanyEls.length - 1];
    const deliveryAddressEl = deliveryAddressEls[deliveryAddressEls.length - 1];
    const deliveryZipEl = deliveryZipEls[deliveryZipEls.length - 1];
    const deliveryCityEl = deliveryCityEls[deliveryCityEls.length - 1];
    
    // KOPIOWANIE
    if (deliveryNameEl) deliveryNameEl.value = invoiceName;
    if (deliveryCompanyEl) deliveryCompanyEl.value = invoiceCompany;
    if (deliveryAddressEl) deliveryAddressEl.value = invoiceAddress;
    if (deliveryZipEl) deliveryZipEl.value = invoiceZip;
    if (deliveryCityEl) deliveryCityEl.value = invoiceCity;
    
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