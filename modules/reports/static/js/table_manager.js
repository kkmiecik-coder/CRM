// modules/reports/static/js/table_manager.js
/**
 * Manager zarządzający filtrami dropdown i dodawaniem/edycją wierszy
 * Odpowiedzialny za filtry wielokrotne, dodawanie/edycję wierszy z systemem zakładek
 */

class TableManager {
    constructor() {
        this.filterElements = {};
        this.modalElements = {};
        this.tabElements = {};
        this.isInitialized = false;

        // NOWE: Dane produktów i system zakładek
        this.productsData = []; // Tablica przechowująca dane produktów
        this.currentTab = 'client'; // Aktywna zakładka
        this.currentEditRecord = null; // Rekord w trybie edycji

        // Dane dropdown'ów
        this.dropdownData = {
            customer_name: [],
            delivery_state: [],
            wood_species: [],
            current_status: [],
            delivery_method: [],
            order_source: [],
            payment_method: []
        };

        // Aktywne filtry (checkbox states)
        this.activeFilters = {
            customer_name: [],
            delivery_state: [],
            wood_species: [],
            current_status: []
        };

        // Stany dropdown'ów
        this.dropdownStates = {
            customer_name: false,
            delivery_state: false,
            wood_species: false,
            current_status: false
        };

        console.log('[TableManager] Initialized');
    }

    /**
     * Inicjalizacja managera
     */
    init() {
        console.log('[TableManager] Starting initialization...');

        this.cacheElements();
        this.setupEventListeners();
        this.loadDropdownData();
        this.initializeTabs(); // NOWE: Inicjalizacja zakładek

        this.isInitialized = true;
        console.log('[TableManager] Initialization complete');
    }

    /**
     * Cache elementów DOM - ROZSZERZONA WERSJA Z ZAKŁADKAMI
     */
    cacheElements() {
        // Filtry dat
        this.filterElements = {
            filterDateFrom: document.getElementById('filterDateFrom'),
            filterDateTo: document.getElementById('filterDateTo'),

            // Dropdown elementy
            customerNameDropdown: document.getElementById('filterCustomerNameDropdown'),
            customerNameToggle: document.getElementById('filterCustomerNameToggle'),
            customerNameMenu: document.getElementById('filterCustomerNameMenu'),
            customerNameLabel: document.querySelector('#filterCustomerNameToggle .filter-dropdown-label'),
            customerNameOptions: document.getElementById('filterCustomerNameOptions'),
            searchCustomerName: document.getElementById('searchCustomerName'),

            deliveryStateDropdown: document.getElementById('filterDeliveryStateDropdown'),
            deliveryStateToggle: document.getElementById('filterDeliveryStateToggle'),
            deliveryStateMenu: document.getElementById('filterDeliveryStateMenu'),
            deliveryStateLabel: document.querySelector('#filterDeliveryStateToggle .filter-dropdown-label'),
            deliveryStateOptions: document.getElementById('filterDeliveryStateOptions'),
            searchDeliveryState: document.getElementById('searchDeliveryState'),

            woodSpeciesDropdown: document.getElementById('filterWoodSpeciesDropdown'),
            woodSpeciesToggle: document.getElementById('filterWoodSpeciesToggle'),
            woodSpeciesMenu: document.getElementById('filterWoodSpeciesMenu'),
            woodSpeciesLabel: document.querySelector('#filterWoodSpeciesToggle .filter-dropdown-label'),
            woodSpeciesOptions: document.getElementById('filterWoodSpeciesOptions'),
            searchWoodSpecies: document.getElementById('searchWoodSpecies'),

            currentStatusDropdown: document.getElementById('filterCurrentStatusDropdown'),
            currentStatusToggle: document.getElementById('filterCurrentStatusToggle'),
            currentStatusMenu: document.getElementById('filterCurrentStatusMenu'),
            currentStatusLabel: document.querySelector('#filterCurrentStatusToggle .filter-dropdown-label'),
            currentStatusOptions: document.getElementById('filterCurrentStatusOptions'),
            searchCurrentStatus: document.getElementById('searchCurrentStatus')
        };

        // Modal elementy - ROZSZERZONE O NOWE POLA
        this.modalElements = {
            modal: document.getElementById('manualRowModal'),
            title: document.getElementById('manualRowModalTitle'),
            form: document.getElementById('manualRowForm'),
            cancelBtn: document.getElementById('manualRowCancel'),
            saveBtn: document.getElementById('manualRowSave'),
            closeBtn: document.querySelector('#manualRowModal .close'),

            // Pola formularza - Tab Klient
            recordId: document.getElementById('recordId'),
            customerName: document.getElementById('customerName'),
            phone: document.getElementById('phone'),
            caretaker: document.getElementById('caretaker'),
            deliveryAddress: document.getElementById('deliveryAddress'),
            deliveryPostcode: document.getElementById('deliveryPostcode'),
            deliveryCity: document.getElementById('deliveryCity'),
            deliveryState: document.getElementById('deliveryState'),

            // Tab Zamówienie
            dateCreated: document.getElementById('dateCreated'),
            baselinkerOrderId: document.getElementById('baselinkerOrderId'),
            internalOrderNumber: document.getElementById('internalOrderNumber'),
            orderSource: document.getElementById('orderSource'),
            deliveryMethod: document.getElementById('deliveryMethod'),
            deliveryCost: document.getElementById('deliveryCost'),
            paymentMethod: document.getElementById('paymentMethod'),
            paidAmountNet: document.getElementById('paidAmountNet'),
            currentStatus: document.getElementById('currentStatus'),

            // STARE POLA - zachowane dla kompatybilności z pojedynczym produktem w trybie edycji
            groupType: document.getElementById('groupType'),
            productType: document.getElementById('productType'),
            woodSpecies: document.getElementById('woodSpecies'),
            technology: document.getElementById('technology'),
            woodClass: document.getElementById('woodClass'),
            finishState: document.getElementById('finishState'),
            lengthCm: document.getElementById('lengthCm'),
            widthCm: document.getElementById('widthCm'),
            thicknessCm: document.getElementById('thicknessCm'),
            quantity: document.getElementById('quantity'),
            priceGross: document.getElementById('priceGross')
        };

        // NOWE: Elementy zakładek i produktów
        this.tabElements = {
            buttons: document.querySelectorAll('.tab-button'),
            contents: document.querySelectorAll('.tab-content'),
            productCountBadge: document.getElementById('productCountBadge'),
            productsList: document.getElementById('productsList'),
            productsTabs: document.getElementById('productsTabs'),
            addProductBtn: document.getElementById('addProductBtn'),
            totalVolume: document.getElementById('totalVolume'),
            totalValueGross: document.getElementById('totalValueGross'),
            totalValueNet: document.getElementById('totalValueNet'),
            productTemplate: document.getElementById('productItemTemplate')
        };

        // NOWE: Stan przełączania produktów
        this.activeProductIndex = 0;

        console.log('[TableManager] Elements cached');
    }

    /**
     * Ustawienie event listenerów - ROZSZERZONA WERSJA
     */
    setupEventListeners() {
        // Obsługa dat
        if (this.filterElements.filterDateFrom) {
            this.filterElements.filterDateFrom.addEventListener('change', () => {
                this.handleDateFilterChange();
            });
        }

        if (this.filterElements.filterDateTo) {
            this.filterElements.filterDateTo.addEventListener('change', () => {
                this.handleDateFilterChange();
            });
        }

        // Obsługa dropdown'ów
        this.setupDropdownEventListeners();

        // Zamknięcie dropdown'ów przy kliknięciu poza nimi
        document.addEventListener('click', (e) => {
            this.handleOutsideClick(e);
        });

        // Obsługa klawisza Escape
        document.addEventListener('keydown', (e) => {
            this.handleEscapeKey(e);
        });

        // NOWE: Event listenery dla zakładek
        this.setupTabEventListeners();

        // Modal events
        if (this.modalElements.modal) {
            if (this.modalElements.closeBtn) {
                this.modalElements.closeBtn.addEventListener('click', () => this.hideManualRowModal());
            }

            this.modalElements.modal.addEventListener('click', (e) => {
                if (e.target === this.modalElements.modal) {
                    this.hideManualRowModal();
                }
            });
        }

        if (this.modalElements.cancelBtn) {
            this.modalElements.cancelBtn.addEventListener('click', () => {
                this.hideManualRowModal();
            });
        }

        if (this.modalElements.saveBtn) {
            this.modalElements.saveBtn.addEventListener('click', () => {
                this.saveManualRow();
            });
        }

        if (this.modalElements.form) {
            this.modalElements.form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.saveManualRow();
            });
        }

        this.setupRealTimeValidation();

        console.log('[TableManager] Event listeners setup complete');
    }

    /**
     * NOWE: Inicjalizacja systemu zakładek
     */
    initializeTabs() {
        // Ustaw pierwszą zakładkę jako aktywną
        this.switchTab('client');
        console.log('[TableManager] Tabs initialized');
    }

    /**
     * NOWE: Setup event listenerów dla zakładek z obserwatorem DOM i postcodeAutoFill
     */
    setupTabEventListeners() {
        // Zakładki
        if (this.tabElements.buttons) {
            this.tabElements.buttons.forEach(button => {
                button.addEventListener('click', () => {
                    const tabName = button.getAttribute('data-tab');
                    this.switchTab(tabName);
                });
            });
        }

        // Dodawanie produktu
        if (this.tabElements.addProductBtn) {
            this.tabElements.addProductBtn.addEventListener('click', () => this.addProduct());
        }

        // Walidacja formularza w czasie rzeczywistym dla zakładek
        if (this.modalElements.form) {
            this.modalElements.form.addEventListener('input', (e) => this.handleFormInput(e));
        }

        // NOWE: Obserwator dla pola deliveryState (dla PostcodeAutoFill)
        this.setupDeliveryStateObserver();

        // NOWE: Obserwator kodu pocztowego z weryfikacją województwa
        this.setupPostcodeObserver();
    }

    /**
     * NOWE: Obserwator kodu pocztowego z automatyczną weryfikacją województwa
     */
    setupPostcodeObserver() {
        if (!this.modalElements.deliveryPostcode || !this.modalElements.deliveryState) {
            console.warn('[TableManager] Missing postcode or state elements for observer');
            return;
        }

        console.log('[TableManager] Setting up postcode observer with province verification...');

        // Mapa kodów pocztowych na województwa
        const postcodeToProvince = {
            // Dolnośląskie: 50-59
            '50': 'dolnośląskie', '51': 'dolnośląskie', '52': 'dolnośląskie', '53': 'dolnośląskie',
            '54': 'dolnośląskie', '55': 'dolnośląskie', '56': 'dolnośląskie', '57': 'dolnośląskie',
            '58': 'dolnośląskie', '59': 'dolnośląskie',

            // Kujawsko-pomorskie: 85-89
            '85': 'kujawsko-pomorskie', '86': 'kujawsko-pomorskie', '87': 'kujawsko-pomorskie',
            '88': 'kujawsko-pomorskie', '89': 'kujawsko-pomorskie',

            // Lubelskie: 20-24
            '20': 'lubelskie', '21': 'lubelskie', '22': 'lubelskie', '23': 'lubelskie', '24': 'lubelskie',

            // Lubuskie: 65-68
            '65': 'lubuskie', '66': 'lubuskie', '67': 'lubuskie', '68': 'lubuskie',

            // Łódzkie: 90-99
            '90': 'łódzkie', '91': 'łódzkie', '92': 'łódzkie', '93': 'łódzkie', '94': 'łódzkie',
            '95': 'łódzkie', '96': 'łódzkie', '97': 'łódzkie', '98': 'łódzkie', '99': 'łódzkie',

            // Małopolskie: 30-34
            '30': 'małopolskie', '31': 'małopolskie', '32': 'małopolskie', '33': 'małopolskie', '34': 'małopolskie',

            // Mazowieckie: 00-09
            '00': 'mazowieckie', '01': 'mazowieckie', '02': 'mazowieckie', '03': 'mazowieckie',
            '04': 'mazowieckie', '05': 'mazowieckie', '06': 'mazowieckie', '07': 'mazowieckie',
            '08': 'mazowieckie', '09': 'mazowieckie',

            // Opolskie: 45-49
            '45': 'opolskie', '46': 'opolskie', '47': 'opolskie', '48': 'opolskie', '49': 'opolskie',

            // Podkarpackie: 35-39
            '35': 'podkarpackie', '36': 'podkarpackie', '37': 'podkarpackie', '38': 'podkarpackie', '39': 'podkarpackie',

            // Podlaskie: 15-19
            '15': 'podlaskie', '16': 'podlaskie', '17': 'podlaskie', '18': 'podlaskie', '19': 'podlaskie',

            // Pomorskie: 80-84
            '80': 'pomorskie', '81': 'pomorskie', '82': 'pomorskie', '83': 'pomorskie', '84': 'pomorskie',

            // Śląskie: 40-44
            '40': 'śląskie', '41': 'śląskie', '42': 'śląskie', '43': 'śląskie', '44': 'śląskie',

            // Świętokrzyskie: 25-29
            '25': 'świętokrzyskie', '26': 'świętokrzyskie', '27': 'świętokrzyskie', '28': 'świętokrzyskie', '29': 'świętokrzyskie',

            // Warmińsko-mazurskie: 10-14
            '10': 'warmińsko-mazurskie', '11': 'warmińsko-mazurskie', '12': 'warmińsko-mazurskie',
            '13': 'warmińsko-mazurskie', '14': 'warmińsko-mazurskie',

            // Wielkopolskie: 60-64
            '60': 'wielkopolskie', '61': 'wielkopolskie', '62': 'wielkopolskie', '63': 'wielkopolskie', '64': 'wielkopolskie',

            // Zachodniopomorskie: 70-79
            '70': 'zachodniopomorskie', '71': 'zachodniopomorskie', '72': 'zachodniopomorskie',
            '73': 'zachodniopomorskie', '74': 'zachodniopomorskie', '75': 'zachodniopomorskie',
            '76': 'zachodniopomorskie', '77': 'zachodniopomorskie', '78': 'zachodniopomorskie', '79': 'zachodniopomorskie'
        };

        // Event listener na zmianę kodu pocztowego
        this.modalElements.deliveryPostcode.addEventListener('input', (e) => {
            const postcode = e.target.value.trim();
            console.log(`[TableManager] Postcode input changed: "${postcode}"`);

            // Sprawdź czy kod ma odpowiedni format (XX-XXX lub XX)
            const postcodeMatch = postcode.match(/^(\d{2})/);
            if (postcodeMatch) {
                const prefix = postcodeMatch[1];
                const expectedProvince = postcodeToProvince[prefix];

                console.log(`[TableManager] Postcode prefix: "${prefix}", expected province: "${expectedProvince}"`);

                if (expectedProvince) {
                    // Sprawdź aktualną wartość województwa
                    const currentProvince = this.modalElements.deliveryState.value;
                    console.log(`[TableManager] Current province: "${currentProvince}"`);

                    if (currentProvince !== expectedProvince) {
                        console.log(`[TableManager] Province mismatch, updating: "${currentProvince}" → "${expectedProvince}"`);

                        // Ustaw nowe województwo
                        this.setProvinceValue(expectedProvince);
                    } else {
                        console.log(`[TableManager] Province already correct: "${expectedProvince}"`);
                    }
                }
            }
        });

        // Event listener na zmianę (blur) - dodatkowa weryfikacja
        this.modalElements.deliveryPostcode.addEventListener('blur', (e) => {
            const postcode = e.target.value.trim();
            if (postcode.length >= 2) {
                console.log(`[TableManager] Postcode blur verification: "${postcode}"`);
                // Repeat the same logic as in input event
                const postcodeMatch = postcode.match(/^(\d{2})/);
                if (postcodeMatch) {
                    const prefix = postcodeMatch[1];
                    const expectedProvince = postcodeToProvince[prefix];
                    if (expectedProvince && this.modalElements.deliveryState.value !== expectedProvince) {
                        this.setProvinceValue(expectedProvince);
                    }
                }
            }
        });

        console.log('[TableManager] Postcode observer with province verification setup completed');
    }

    /**
     * NOWE: Ustawienie wartości województwa z wszystkimi metodami renderingu
     */
    setProvinceValue(provinceValue) {
        if (!provinceValue || !this.modalElements.deliveryState) return;

        console.log(`[TableManager] Setting province value: "${provinceValue}"`);

        // Sprawdź czy taka opcja istnieje
        const option = this.modalElements.deliveryState.querySelector(`option[value="${provinceValue}"]`);
        if (!option) {
            console.warn(`[TableManager] Province option not found: "${provinceValue}"`);
            return;
        }

        // Zapamiętaj aktywny element
        const activeElement = document.activeElement;

        // Ustaw wartość na wszystkie możliwe sposoby
        this.modalElements.deliveryState.value = provinceValue;
        this.modalElements.deliveryState.selectedIndex = option.index;

        // Wywołaj eventy
        this.modalElements.deliveryState.dispatchEvent(new Event('change', { bubbles: true }));
        this.modalElements.deliveryState.dispatchEvent(new Event('input', { bubbles: true }));

        // Przywróć focus
        if (activeElement && activeElement !== this.modalElements.deliveryState) {
            setTimeout(() => activeElement.focus(), 10);
        }

        // Wymusz rerender
        setTimeout(() => {
            try {
                // Metoda 1: Style manipulation
                const originalOpacity = this.modalElements.deliveryState.style.opacity;
                this.modalElements.deliveryState.style.opacity = '0.99';
                setTimeout(() => {
                    this.modalElements.deliveryState.style.opacity = originalOpacity;
                }, 1);

                // Sprawdź końcowy stan
                const finalValue = this.modalElements.deliveryState.value;
                const finalText = this.modalElements.deliveryState.selectedOptions[0]?.textContent;
                console.log(`[TableManager] Province set - value: "${finalValue}", text: "${finalText}"`);

            } catch (error) {
                console.error('[TableManager] Error during province rerender:', error);
            }
        }, 20);
    }

    /**
     * ZAKTUALIZOWANA: Obserwator zmian w polu deliveryState z ciągłym nasłuchiwaniem
     */
    setupDeliveryStateObserver() {
        if (!this.modalElements.deliveryState) return;

        console.log('[TableManager] Setting up continuous deliveryState observer...');

        // Obserwator mutacji DOM - zawsze aktywny
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'value') {
                    const newValue = mutation.target.value;
                    console.log(`[TableManager] DOM mutation detected on deliveryState: ${newValue}`);
                    this.handleDeliveryStateChange(newValue);
                }
            });
        });

        // Obserwuj zmiany atrybutu value
        observer.observe(this.modalElements.deliveryState, {
            attributes: true,
            attributeFilter: ['value']
        });

        // ULEPSZONE: Ciągłe przechwytywanie właściwości value
        const deliveryStateElement = this.modalElements.deliveryState;
        const originalDescriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');

        // Zapisz referencję do oryginalnych funkcji
        const originalSetter = originalDescriptor.set;
        const originalGetter = originalDescriptor.get;

        // Zdefiniuj nową właściwość value z ciągłym nasłuchiwaniem
        Object.defineProperty(deliveryStateElement, 'value', {
            set: function (newValue) {
                console.log(`[TableManager] Continuous value setter intercepted: "${newValue}"`);

                // Wywołaj oryginalny setter
                originalSetter.call(this, newValue);

                // ZAWSZE sprawdź czy wartość została ustawiona prawidłowo
                const actualValue = originalGetter.call(this);
                console.log(`[TableManager] After setter - requested: "${newValue}", actual: "${actualValue}"`);

                // Jeśli wartość się nie zgadza, spróbuj mapowania
                if (actualValue !== newValue && newValue) {
                    console.log(`[TableManager] Value mismatch detected, attempting mapping...`);

                    // Użyj setTimeout żeby upewnić się, że DOM jest gotowy
                    setTimeout(() => {
                        // Odwołaj się do TableManager przez window, żeby nie było problemów z kontekstem
                        if (window.tableManager) {
                            window.tableManager.handleDeliveryStateChange(newValue);
                        }
                    }, 10);
                }
            },
            get: function () {
                return originalGetter.call(this);
            },
            configurable: true,
            enumerable: true
        });

        // DODATKOWE: Nasłuchuj również eventów input i change
        deliveryStateElement.addEventListener('input', (e) => {
            console.log(`[TableManager] Input event on deliveryState: ${e.target.value}`);
            this.handleDeliveryStateChange(e.target.value);
        });

        deliveryStateElement.addEventListener('change', (e) => {
            console.log(`[TableManager] Change event on deliveryState: ${e.target.value}`);
            // Nie wywołujemy handleDeliveryStateChange dla eventów change,
            // bo to mogą być normalne interakcje użytkownika
        });

        console.log('[TableManager] Continuous deliveryState observer setup completed');
    }

    /**
     * ZAKTUALIZOWANA: Obsługa zmiany wartości deliveryState z lepszym debugowaniem
     */
    handleDeliveryStateChange(newValue) {
        if (!newValue || !this.modalElements.deliveryState) {
            console.log(`[TableManager] Skipping deliveryState change - empty value or missing element`);
            return;
        }

        console.log(`[TableManager] Processing deliveryState change: "${newValue}" (length: ${newValue.length})`);

        // Sprawdź aktualną wartość w select'cie
        const currentValue = this.modalElements.deliveryState.value;
        console.log(`[TableManager] Current select value: "${currentValue}"`);

        // Sprawdź czy wartość została prawidłowo ustawiona
        if (currentValue === newValue) {
            console.log(`[TableManager] Value already set correctly, no mapping needed`);
            return;
        }

        // Sprawdź czy podana wartość w ogóle może być województwem (podstawowa walidacja)
        if (newValue.length < 3) {
            console.log(`[TableManager] Value too short to be a province name: "${newValue}"`);
            return;
        }

        console.log(`[TableManager] Attempting to map province: "${newValue}"`);

        // Spróbuj mapowania
        const success = this.trySetProvinceValue(this.modalElements.deliveryState, newValue);
        if (success) {
            const finalValue = this.modalElements.deliveryState.value;
            console.log(`[TableManager] ✅ Successfully mapped: "${newValue}" → "${finalValue}"`);

            // Wyślij dodatkowy event żeby poinformować inne części systemu
            this.modalElements.deliveryState.dispatchEvent(new CustomEvent('provinceAutoFilled', {
                detail: {
                    originalValue: newValue,
                    mappedValue: finalValue
                },
                bubbles: true
            }));
        } else {
            console.error(`[TableManager] ❌ Failed to map province: "${newValue}"`);
        }
    }

    /**
     * NOWE: Przełączanie zakładek
     */
    switchTab(tabName) {
        console.log('[TableManager] Switching to tab:', tabName);

        // Usuń aktywną klasę ze wszystkich przycisków i zawartości
        if (this.tabElements.buttons) {
            this.tabElements.buttons.forEach(btn => btn.classList.remove('active'));
        }
        if (this.tabElements.contents) {
            this.tabElements.contents.forEach(content => content.classList.remove('active'));
        }

        // Dodaj aktywną klasę do wybranej zakładki
        const activeButton = document.querySelector(`[data-tab="${tabName}"]`);
        const activeContent = document.getElementById(`${tabName}Tab`);

        if (activeButton && activeContent) {
            activeButton.classList.add('active');
            activeContent.classList.add('active');
            this.currentTab = tabName;
        }

        // Zaktualizuj fokus dla accessibility
        if (tabName === 'client' && this.modalElements.customerName) {
            setTimeout(() => this.modalElements.customerName.focus(), 100);
        }
    }

    /**
     * NOWE: Dodaj nowy produkt
     */
    addProduct() {
        const productData = {
            group_type: 'towar',
            product_type: 'klejonka',
            wood_species: '',
            technology: '',
            wood_class: '',
            finish_state: 'surowy',
            length_cm: '',
            width_cm: '',
            thickness_cm: '',
            quantity: 1,
            price_net: '' // ZMIANA: price_net zamiast price_gross
        };

        this.productsData.push(productData);
        this.renderProducts();
        this.renderProductTabs();
        this.updateProductCountBadge();

        // Przełącz na nowo dodany produkt
        this.switchToProduct(this.productsData.length - 1);

        console.log('[TableManager] Product added, total:', this.productsData.length);
    }

    /**
     * NOWE: Usuń produkt
     */
    removeProduct(index) {
        if (this.productsData.length <= 1) {
            this.showMessage('Musi pozostać przynajmniej jeden produkt', 'warning');
            return;
        }

        this.productsData.splice(index, 1);

        // Dostosuj aktywny indeks jeśli usunięto aktywny produkt
        if (this.activeProductIndex >= this.productsData.length) {
            this.activeProductIndex = this.productsData.length - 1;
        }

        this.renderProducts();
        this.renderProductTabs();
        this.updateProductCountBadge();
        this.calculateTotals();

        // Przełącz na aktywny produkt
        this.switchToProduct(this.activeProductIndex);

        console.log('[TableManager] Product removed, total:', this.productsData.length);
    }

    /**
     * NOWE: Renderuj zakładki produktów
     */
    renderProductTabs() {
        if (!this.tabElements.productsTabs) return;

        this.tabElements.productsTabs.innerHTML = '';

        this.productsData.forEach((product, index) => {
            const tabName = this.getProductTabName(product, index);

            const tabButton = document.createElement('button');
            tabButton.type = 'button';
            tabButton.className = `product-tab-btn ${index === this.activeProductIndex ? 'active' : ''}`;
            tabButton.setAttribute('data-product-index', index);

            tabButton.innerHTML = `
                ${tabName}
                ${this.productsData.length > 1 ? `<span class="remove-tab-btn" data-remove="${index}">×</span>` : ''}
            `;

            this.tabElements.productsTabs.appendChild(tabButton);
        });

        // Binduj eventy
        this.bindProductTabEvents();
    }

    /**
     * NOWE: Pobierz nazwę zakładki produktu
     */
    getProductTabName(product, index) {
        const length = parseFloat(product.length_cm);
        const width = parseFloat(product.width_cm);
        const thickness = parseFloat(product.thickness_cm);

        // Jeśli wszystkie wymiary są wypełnione, pokaż wymiary
        if (length > 0 && width > 0 && thickness > 0) {
            return `${length}×${width}×${thickness}cm`;
        }

        // W przeciwnym razie pokaż "Produkt X"
        return `Produkt ${index + 1}`;
    }

    /**
     * NOWE: Binduj eventy zakładek produktów
     */
    bindProductTabEvents() {
        // Przełączanie produktów
        const tabButtons = this.tabElements.productsTabs.querySelectorAll('.product-tab-btn');
        tabButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                // Jeśli kliknięto na przycisk usuwania, nie przełączaj
                if (e.target.classList.contains('remove-tab-btn')) {
                    return;
                }

                const productIndex = parseInt(button.getAttribute('data-product-index'));
                this.switchToProduct(productIndex);
            });
        });

        // Usuwanie produktów
        const removeButtons = this.tabElements.productsTabs.querySelectorAll('.remove-tab-btn');
        removeButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.stopPropagation();
                const productIndex = parseInt(button.getAttribute('data-remove'));
                this.removeProduct(productIndex);
            });
        });
    }

    /**
     * NOWE: Przełącz na konkretny produkt
     */
    switchToProduct(index) {
        if (index < 0 || index >= this.productsData.length) return;

        this.activeProductIndex = index;

        // Zaktualizuj przyciski zakładek
        const tabButtons = this.tabElements.productsTabs.querySelectorAll('.product-tab-btn');
        tabButtons.forEach((button, btnIndex) => {
            if (btnIndex === index) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });

        // Pokaż tylko aktywny produkt
        this.showActiveProduct(index);
    }

    /**
     * NOWE: Pokaż tylko aktywny produkt
     */
    showActiveProduct(index) {
        const productItems = this.tabElements.productsList.querySelectorAll('.product-item');
        productItems.forEach((item, itemIndex) => {
            if (itemIndex === index) {
                item.style.display = 'block';
            } else {
                item.style.display = 'none';
            }
        });
    }

    /**
     * NOWE: Renderuj listę produktów z obsługą zakładek
     */
    renderProducts() {
        if (!this.tabElements.productsList || !this.tabElements.productTemplate) {
            console.error('[TableManager] Products elements not found');
            return;
        }

        // Wyczyść listę
        this.tabElements.productsList.innerHTML = '';

        // Renderuj każdy produkt
        this.productsData.forEach((product, index) => {
            const productElement = this.createProductElement(product, index);
            this.tabElements.productsList.appendChild(productElement);
        });

        // Binduj eventy dla nowych elementów
        this.bindProductEvents();

        // Pokaż tylko aktywny produkt
        this.showActiveProduct(this.activeProductIndex);

        // Renderuj zakładki produktów
        this.renderProductTabs();
    }

    /**
     * ZAKTUALIZOWANA: Utwórz element produktu z nowymi polami
     */
    createProductElement(product, index) {
        const template = this.tabElements.productTemplate.content.cloneNode(true);
        const productDiv = template.querySelector('.product-item');

        // Ustaw indeks
        productDiv.setAttribute('data-product-index', index);

        // Ustaw numer produktu
        const productNumber = template.querySelector('.product-number');
        if (productNumber) {
            productNumber.textContent = index + 1;
        }

        // Wypełnij pola wartościami
        const fields = {
            'group_type': product.group_type,
            'product_type': product.product_type,
            'wood_species': product.wood_species,
            'technology': product.technology,
            'wood_class': product.wood_class,
            'finish_state': product.finish_state,
            'length_cm': product.length_cm,
            'width_cm': product.width_cm,
            'thickness_cm': product.thickness_cm,
            'quantity': product.quantity,
            'price_net': product.price_net // ZMIANA: price_net zamiast price_gross
        };

        Object.keys(fields).forEach(fieldName => {
            const field = template.querySelector(`[name="${fieldName}"]`);
            if (field && fields[fieldName] !== null && fields[fieldName] !== undefined) {
                field.value = fields[fieldName];
            }
        });

        // Przelicz wartości dla tego produktu
        this.calculateProductValues(template, product);

        return template;
    }

    /**
     * ZAKTUALIZOWANA: Binduj eventy dla produktów
     */
    bindProductEvents() {
        // Usuwanie produktów - usunięte, bo teraz usuwamy przez zakładki

        // Obliczenia w czasie rzeczywistym
        const productFields = this.tabElements.productsList.querySelectorAll('.product-field');
        productFields.forEach(field => {
            field.addEventListener('input', (e) => {
                const productIndex = parseInt(e.target.closest('.product-item').getAttribute('data-product-index'));
                this.updateProductData(productIndex, e.target);
                this.calculateProductValues(e.target.closest('.product-item'));
                this.calculateTotals();

                // NOWE: Zaktualizuj nazwę zakładki jeśli zmieniły się wymiary
                if (['length_cm', 'width_cm', 'thickness_cm'].includes(e.target.name)) {
                    this.renderProductTabs();
                }
            });
        });
    }

    /**
     * ZAKTUALIZOWANA: Aktualizuj dane produktu z price_net
     */
    updateProductData(index, field) {
        if (!this.productsData[index]) return;

        const fieldName = field.getAttribute('name');
        let value = field.value;

        // Konwersja typów
        if (['length_cm', 'width_cm', 'thickness_cm', 'price_net'].includes(fieldName)) {
            value = parseFloat(value) || 0;
        } else if (fieldName === 'quantity') {
            value = parseInt(value) || 1;
        }

        this.productsData[index][fieldName] = value;
    }

    /**
     * ZAKTUALIZOWANA: Oblicz wartości dla pojedynczego produktu z ceną netto
     */
    calculateProductValues(productElement, productData = null) {
        // Pobierz dane z pól jeśli nie podano
        if (!productData) {
            const index = parseInt(productElement.getAttribute('data-product-index'));
            productData = this.productsData[index];
            if (!productData) return;
        }

        const length = parseFloat(productData.length_cm) || 0;
        const width = parseFloat(productData.width_cm) || 0;
        const thickness = parseFloat(productData.thickness_cm) || 0;
        const quantity = parseInt(productData.quantity) || 1;
        const priceNet = parseFloat(productData.price_net) || 0; // ZMIANA: price_net

        // Obliczenia
        const volumePerPiece = (length * width * thickness) / 1000000; // cm³ na m³
        const totalVolume = volumePerPiece * quantity;
        const totalPriceNet = priceNet * quantity;
        const totalPriceGross = totalPriceNet * 1.23; // VAT 23%

        // Aktualizuj wyświetlanie
        const volumePerPieceEl = productElement.querySelector('.volume-per-piece');
        const totalVolumeEl = productElement.querySelector('.total-volume');
        const totalPriceNetEl = productElement.querySelector('.total-price-net');
        const totalPriceGrossEl = productElement.querySelector('.total-price-gross');

        if (volumePerPieceEl) volumePerPieceEl.textContent = `${volumePerPiece.toFixed(4)} m³`;
        if (totalVolumeEl) totalVolumeEl.textContent = `${totalVolume.toFixed(4)} m³`;
        if (totalPriceNetEl) totalPriceNetEl.textContent = `${totalPriceNet.toFixed(2)} zł`;
        if (totalPriceGrossEl) totalPriceGrossEl.textContent = `${totalPriceGross.toFixed(2)} zł`;
    }

    /**
     * ZAKTUALIZOWANA: Oblicz łączne sumy z ceną netto
     */
    calculateTotals() {
        let totalVolume = 0;
        let totalValueNet = 0;

        this.productsData.forEach(product => {
            const length = parseFloat(product.length_cm) || 0;
            const width = parseFloat(product.width_cm) || 0;
            const thickness = parseFloat(product.thickness_cm) || 0;
            const quantity = parseInt(product.quantity) || 1;
            const priceNet = parseFloat(product.price_net) || 0; // ZMIANA: price_net

            const volumePerPiece = (length * width * thickness) / 1000000;
            totalVolume += volumePerPiece * quantity;
            totalValueNet += priceNet * quantity;
        });

        const totalValueGross = totalValueNet * 1.23;

        // Aktualizuj wyświetlanie
        if (this.tabElements.totalVolume) {
            this.tabElements.totalVolume.textContent = `${totalVolume.toFixed(4)} m³`;
        }
        if (this.tabElements.totalValueNet) {
            this.tabElements.totalValueNet.textContent = `${totalValueNet.toFixed(2)} zł`;
        }
        if (this.tabElements.totalValueGross) {
            this.tabElements.totalValueGross.textContent = `${totalValueGross.toFixed(2)} zł`;
        }
    }

    /**
     * NOWE: Aktualizuj badge z liczbą produktów
     */
    updateProductCountBadge() {
        if (this.tabElements.productCountBadge) {
            this.tabElements.productCountBadge.textContent = this.productsData.length;
        }
    }

    /**
     * NOWE: Obsługa input events z walidacją
     */
    handleFormInput(e) {
        const target = e.target;

        // Walidacja kodu pocztowego
        if (target.name === 'delivery_postcode') {
            const value = target.value;
            const pattern = /^\d{2}-\d{3}$/;

            if (value && !pattern.test(value)) {
                target.setCustomValidity('Kod pocztowy musi mieć format XX-XXX');
            } else {
                target.setCustomValidity('');
            }
        }

        // Walidacja numeru Baselinker
        if (target.name === 'baselinker_order_id') {
            const value = parseInt(target.value);
            if (target.value && (isNaN(value) || value < 1)) {
                target.setCustomValidity('Numer zamówienia musi być liczbą większą od 0');
            } else {
                target.setCustomValidity('');
            }
        }
    }

    /**
     * Obsługa zmiany filtrów dat
     */
    handleDateFilterChange() {
        const dateFrom = this.filterElements.filterDateFrom?.value;
        const dateTo = this.filterElements.filterDateTo?.value;

        console.log('[TableManager] Date filter changed:', { dateFrom, dateTo });

        // Przekaż do ReportsManager
        if (window.reportsManager) {
            window.reportsManager.setDateRange(dateFrom, dateTo);
        }
    }

    /**
     * Ustawienie event listenerów dla dropdown'ów
     */
    setupDropdownEventListeners() {
        const filterKeys = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        filterKeys.forEach(filterKey => {
            const camelCase = this.snakeToCamel(filterKey);
            const toggle = this.filterElements[`${camelCase}Toggle`];
            const menu = this.filterElements[`${camelCase}Menu`];
            const search = this.filterElements[`search${this.capitalizeFirst(camelCase)}`];

            // Toggle dropdown
            if (toggle) {
                toggle.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.toggleDropdown(filterKey);
                });
            }

            // Search input
            if (search) {
                search.addEventListener('input', (e) => {
                    this.filterDropdownOptions(filterKey, e.target.value);
                });

                // Zapobiegaj zamykaniu dropdown'a przy kliknięciu w search
                search.addEventListener('click', (e) => {
                    e.stopPropagation();
                });
            }

            // Zapobiegaj zamykaniu dropdown'a przy kliknięciu w menu
            if (menu) {
                menu.addEventListener('click', (e) => {
                    e.stopPropagation();
                });
            }
        });
    }

    /**
     * Toggle dropdown'a
     */
    toggleDropdown(filterKey) {
        const isOpen = this.dropdownStates[filterKey];

        // Zamknij wszystkie inne dropdown'y
        Object.keys(this.dropdownStates).forEach(key => {
            if (key !== filterKey) {
                this.closeDropdown(key);
            }
        });

        if (isOpen) {
            this.closeDropdown(filterKey);
        } else {
            this.openDropdown(filterKey);
        }
    }

    /**
     * Otwórz dropdown
     */
    openDropdown(filterKey) {
        const camelCase = this.snakeToCamel(filterKey);
        const toggle = this.filterElements[`${camelCase}Toggle`];
        const menu = this.filterElements[`${camelCase}Menu`];
        const search = this.filterElements[`search${this.capitalizeFirst(camelCase)}`];

        if (toggle && menu) {
            toggle.classList.add('active');
            menu.classList.add('show');
            this.dropdownStates[filterKey] = true;

            // Dostosuj pozycję w fullscreen
            this.adjustDropdownPosition(menu);

            // Focus na search input
            if (search) {
                setTimeout(() => {
                    search.focus();
                }, 100);
            }

            console.log('[TableManager] Dropdown opened:', filterKey, 'fullscreen:', this.isInFullscreenMode());
        }
    }

    /**
     * Zarządzanie dropdown'ami w fullscreen
     */
    manageFullscreenDropdowns() {
        const filterKeys = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        filterKeys.forEach(filterKey => {
            const camelCase = this.snakeToCamel(filterKey);
            const dropdown = this.filterElements[`${camelCase}Dropdown`];
            const menu = this.filterElements[`${camelCase}Menu`];

            if (dropdown && menu) {
                if (this.isInFullscreenMode()) {
                    // Dodaj klasy fullscreen
                    dropdown.classList.add('fullscreen-mode');
                    menu.classList.add('fullscreen-mode');

                    // Ustaw z-index
                    dropdown.style.zIndex = '1001';
                    menu.style.zIndex = '1002';
                } else {
                    // Usuń klasy fullscreen
                    dropdown.classList.remove('fullscreen-mode');
                    menu.classList.remove('fullscreen-mode');

                    // Reset z-index
                    dropdown.style.zIndex = '';
                    menu.style.zIndex = '';
                }
            }
        });
    }

    /**
     * Zamknij wszystkie dropdown'y w fullscreen
     */
    closeAllDropdownsInFullscreen() {
        if (this.isInFullscreenMode()) {
            this.closeAllDropdowns();
        }
    }

    /**
     * Dostosowanie pozycji dropdown'a w fullscreen
     */
    adjustDropdownPosition(menu) {
        if (!menu) return;

        if (this.isInFullscreenMode()) {
            // W fullscreen zawsze nad przyciskiem
            menu.style.top = 'auto';
            menu.style.bottom = '100%';
            menu.style.marginBottom = '2px';

            // Dodaj wyższy z-index
            menu.style.zIndex = '1002';

            console.log('[TableManager] Dropdown positioned above in fullscreen');
        } else {
            // W normalnym trybie sprawdź czy zmieści się pod przyciskiem
            const rect = menu.getBoundingClientRect();
            const viewportHeight = window.innerHeight;

            if (rect.bottom > viewportHeight) {
                menu.style.top = 'auto';
                menu.style.bottom = '100%';
                menu.style.marginBottom = '2px';
            } else {
                menu.style.top = '100%';
                menu.style.bottom = 'auto';
                menu.style.marginBottom = '0';
            }

            // Normalny z-index
            menu.style.zIndex = '1000';
        }
    }

    /**
     * Zamknij dropdown
     */
    closeDropdown(filterKey) {
        const camelCase = this.snakeToCamel(filterKey);
        const toggle = this.filterElements[`${camelCase}Toggle`];
        const menu = this.filterElements[`${camelCase}Menu`];

        if (toggle && menu) {
            toggle.classList.remove('active');
            menu.classList.remove('show');
            this.dropdownStates[filterKey] = false;
        }
    }

    /**
     * Zamknij dropdown przy kliknięciu poza nim
     */
    handleOutsideClick(e) {
        const filterKeys = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        filterKeys.forEach(filterKey => {
            const camelCase = this.snakeToCamel(filterKey);
            const dropdown = this.filterElements[`${camelCase}Dropdown`];

            if (dropdown && !dropdown.contains(e.target)) {
                this.closeDropdown(filterKey);
            }
        });
    }

    /**
     * Obsługa klawisza Escape
     */
    handleEscapeKey(e) {
        if (e.key === 'Escape') {
            this.closeAllDropdowns();
        }
    }

    /**
     * Filtrowanie opcji dropdown'a
     */
    filterDropdownOptions(filterKey, searchTerm) {
        const camelCase = this.snakeToCamel(filterKey);
        const optionsContainer = this.filterElements[`${camelCase}Options`];

        if (!optionsContainer) return;

        const options = optionsContainer.querySelectorAll('.filter-option');
        const term = searchTerm.toLowerCase();

        let visibleCount = 0;
        const maxVisible = this.isInFullscreenMode() ? 6 : 8; // Mniej opcji w fullscreen

        options.forEach(option => {
            const label = option.querySelector('label');
            if (label) {
                const labelText = label.textContent.toLowerCase();
                const matches = labelText.includes(term);

                if (matches && visibleCount < maxVisible) {
                    option.classList.remove('hidden');
                    visibleCount++;
                } else if (!matches || visibleCount >= maxVisible) {
                    option.classList.add('hidden');
                }
            }
        });

        // Pokaż komunikat jeśli zbyt dużo wyników
        if (visibleCount >= maxVisible && this.isInFullscreenMode()) {
            this.showTooManyResultsMessage(optionsContainer);
        } else {
            this.hideTooManyResultsMessage(optionsContainer);
        }
    }

    /**
     * Pokazanie komunikatu o zbyt dużej liczbie wyników
     */
    showTooManyResultsMessage(container) {
        let message = container.querySelector('.too-many-results-message');
        if (!message) {
            message = document.createElement('div');
            message.className = 'too-many-results-message';
            message.innerHTML = '<small style="color: #6c757d; padding: 0.5rem; display: block;">Doprecyzuj wyszukiwanie...</small>';
            container.appendChild(message);
        }
    }

    /**
     * Ukrycie komunikatu o zbyt dużej liczbie wyników
     */
    hideTooManyResultsMessage(container) {
        const message = container.querySelector('.too-many-results-message');
        if (message) {
            message.remove();
        }
    }

    /**
     * Ładowanie danych dla dropdown'ów
     */
    async loadDropdownData() {
        console.log('[TableManager] Loading dropdown data...');

        const fieldsToLoad = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        try {
            // Ustaw wszystkie dropdown'y w trybie loading
            fieldsToLoad.forEach(field => {
                this.setDropdownLoading(field, true);
            });

            // Ładuj dane dla każdego pola równolegle
            const promises = fieldsToLoad.map(field => this.loadDropdownValues(field));
            const results = await Promise.all(promises);

            // Aktualizuj dropdown'y
            fieldsToLoad.forEach((field, index) => {
                this.dropdownData[field] = results[index] || [];
                this.setDropdownLoading(field, false);
                this.updateDropdownOptions(field);
            });

        } catch (error) {
            console.error('[TableManager] Error loading dropdown data:', error);

            // W przypadku błędu, usuń loading ze wszystkich dropdown'ów
            fieldsToLoad.forEach(field => {
                this.setDropdownLoading(field, false);
            });
        }
    }

    /**
     * Ładowanie wartości dla konkretnego dropdown'a
     */
    async loadDropdownValues(fieldName) {
        try {
            const response = await fetch(`/reports/api/dropdown-values/${fieldName}`);
            const result = await response.json();

            if (result.success) {
                return result.values || [];
            } else {
                console.error(`[TableManager] Error loading ${fieldName}:`, result.error);
                return [];
            }
        } catch (error) {
            console.error(`[TableManager] Network error loading ${fieldName}:`, error);
            return [];
        }
    }

    /**
     * Aktualizacja opcji dropdown'a
     */
    updateDropdownOptions(fieldName) {
        const camelCase = this.snakeToCamel(fieldName);
        const container = this.filterElements[`${camelCase}Options`];

        if (!container) {
            console.warn(`[TableManager] Container not found for field: ${fieldName}`);
            return;
        }

        const values = this.dropdownData[fieldName] || [];

        // Wyczyść kontener
        container.innerHTML = '';

        // Dodaj opcje checkbox - w fullscreen ograniczamy liczbę wyświetlanych
        const maxOptions = this.isInFullscreenMode() ? 50 : 100;
        const displayValues = values.slice(0, maxOptions);

        displayValues.forEach(value => {
            const isChecked = this.activeFilters[fieldName] &&
                this.activeFilters[fieldName].includes(value);

            const optionHtml = `
                <div class="filter-option">
                    <input type="checkbox" 
                           id="${fieldName}_${this.sanitizeId(value)}" 
                           value="${value}" 
                           ${isChecked ? 'checked' : ''}
                           data-filter="${fieldName}">
                    <label for="${fieldName}_${this.sanitizeId(value)}">${value}</label>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', optionHtml);
        });

        // Pokaż komunikat jeśli ograniczono opcje
        if (values.length > maxOptions) {
            const messageHtml = `
                <div class="options-limited-message">
                    <small style="color: #6c757d; padding: 0.5rem; display: block;">
                        Pokazano ${maxOptions} z ${values.length} opcji. Użyj wyszukiwania.
                    </small>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', messageHtml);
        }

        // Dodaj event listenery do nowych checkbox'ów
        container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                this.handleFilterChange(e.target.dataset.filter, e.target.value, e.target.checked);
            });
        });

        // Aktualizuj label dropdown'a
        this.updateDropdownLabel(fieldName);
    }

    /**
     * Aktualizacja label dropdown'a
     */
    updateDropdownLabel(fieldName) {
        const camelCase = this.snakeToCamel(fieldName);
        const label = this.filterElements[`${camelCase}Label`];
        const toggle = this.filterElements[`${camelCase}Toggle`];

        if (!label || !toggle) return;

        const activeCount = this.activeFilters[fieldName] ? this.activeFilters[fieldName].length : 0;

        const defaultLabels = {
            customer_name: 'Wszyscy klienci',
            delivery_state: 'Wszystkie województwa',
            wood_species: 'Wszystkie gatunki',
            current_status: 'Wszystkie statusy'
        };

        // W fullscreen skracamy etykiety
        const compactLabels = {
            customer_name: 'Klienci',
            delivery_state: 'Województwa',
            wood_species: 'Gatunki',
            current_status: 'Statusy'
        };

        const labels = this.isInFullscreenMode() ? compactLabels : defaultLabels;

        if (activeCount === 0) {
            label.textContent = labels[fieldName];
            label.classList.add('placeholder');
            toggle.classList.remove('has-selection');

            // Usuń counter jeśli istnieje
            const existingCounter = toggle.querySelector('.filter-dropdown-counter');
            if (existingCounter) {
                existingCounter.remove();
            }
        } else {
            const selectedValues = this.activeFilters[fieldName];

            if (activeCount === 1 && !this.isInFullscreenMode()) {
                // W trybie normalnym pokaż pełną nazwę dla pojedynczej wartości
                label.textContent = selectedValues[0];
            } else {
                // W fullscreen lub dla wielokrotnego wyboru pokaż liczbę
                label.textContent = `${activeCount} wybranych`;
            }

            label.classList.remove('placeholder');
            toggle.classList.add('has-selection');

            // Dodaj lub aktualizuj counter
            let counter = toggle.querySelector('.filter-dropdown-counter');
            if (!counter) {
                counter = document.createElement('span');
                counter.className = 'filter-dropdown-counter';
                toggle.insertBefore(counter, toggle.querySelector('i'));
            }
            counter.textContent = activeCount;
        }
    }

    /**
     * Obsługa zmiany filtra
     */
    handleFilterChange(filterKey, value, isChecked) {
        console.log('[TableManager] Filter changed:', filterKey, value, isChecked);

        if (!this.activeFilters[filterKey]) {
            this.activeFilters[filterKey] = [];
        }

        if (isChecked) {
            if (!this.activeFilters[filterKey].includes(value)) {
                this.activeFilters[filterKey].push(value);
            }
        } else {
            const index = this.activeFilters[filterKey].indexOf(value);
            if (index > -1) {
                this.activeFilters[filterKey].splice(index, 1);
            }
        }

        // Wyczyść puste filtry
        if (this.activeFilters[filterKey].length === 0) {
            delete this.activeFilters[filterKey];
        }

        // Aktualizuj label dropdown'a
        this.updateDropdownLabel(filterKey);

        // Prześlij zmiany do ReportsManager
        if (window.reportsManager) {
            window.reportsManager.setFilter(filterKey, this.activeFilters[filterKey] || []);
        }
    }

    /**
     * Aktualizacja checkboxów z zewnątrz
     */
    updateFilterCheckboxes(filterKey, value, isChecked) {
        const camelCase = this.snakeToCamel(filterKey);
        const container = this.filterElements[`${camelCase}Options`];

        if (!container) return;

        const checkbox = container.querySelector(`input[value="${value}"]`);
        if (checkbox) {
            checkbox.checked = isChecked;
        }

        // Aktualizuj lokalny stan
        if (!this.activeFilters[filterKey]) {
            this.activeFilters[filterKey] = [];
        }

        if (isChecked) {
            if (!this.activeFilters[filterKey].includes(value)) {
                this.activeFilters[filterKey].push(value);
            }
        } else {
            const index = this.activeFilters[filterKey].indexOf(value);
            if (index > -1) {
                this.activeFilters[filterKey].splice(index, 1);
            }
        }

        if (this.activeFilters[filterKey].length === 0) {
            delete this.activeFilters[filterKey];
        }

        // Aktualizuj label
        this.updateDropdownLabel(filterKey);
    }

    /**
     * Czyszczenie filtrów
     */
    clearFilters() {
        console.log('[TableManager] Clearing filters...');

        // Wyczyść daty
        if (this.filterElements.filterDateFrom) {
            this.filterElements.filterDateFrom.value = '';
        }
        if (this.filterElements.filterDateTo) {
            this.filterElements.filterDateTo.value = '';
        }

        // Wyczyść stany checkbox'ów i dropdown'ów
        Object.keys(this.activeFilters).forEach(filterKey => {
            const camelCase = this.snakeToCamel(filterKey);
            const container = this.filterElements[`${camelCase}Options`];

            if (container) {
                container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
                    checkbox.checked = false;
                });

                // Wyczyść komunikaty w fullscreen
                this.hideTooManyResultsMessage(container);
                const limitedMessage = container.querySelector('.options-limited-message');
                if (limitedMessage) {
                    limitedMessage.remove();
                }
            }

            // Wyczyść search input
            const searchElement = this.filterElements[`search${this.capitalizeFirst(camelCase)}`];
            if (searchElement) {
                searchElement.value = '';
                // Pokaż wszystkie opcje
                this.filterDropdownOptions(filterKey, '');
            }

            // Zamknij dropdown
            this.closeDropdown(filterKey);
        });

        // Wyczyść lokalny stan
        this.activeFilters = {
            customer_name: [],
            delivery_state: [],
            wood_species: [],
            current_status: []
        };

        // Aktualizuj wszystkie labels
        Object.keys(this.activeFilters).forEach(filterKey => {
            this.updateDropdownLabel(filterKey);
        });

        console.log('[TableManager] Filters cleared');
    }

    /**
     * Walidacja stanu managera z fullscreen
     */
    validateState() {
        const issues = [];

        if (!this.filterElements.filterDateFrom || !this.filterElements.filterDateTo) {
            issues.push('Missing date filter elements');
        }

        if (this.elementsToMove && this.elementsToMove.some(item => !item.element)) {
            issues.push('Some filter elements are missing');
        }

        // Sprawdź czy FullscreenManager jest dostępny
        if (!window.fullscreenManager) {
            issues.push('FullscreenManager not available');
        }

        return {
            isValid: issues.length === 0,
            issues: issues
        };
    }

    /**
     * Zamknięcie wszystkich dropdown'ów
     */
    closeAllDropdowns() {
        Object.keys(this.dropdownStates).forEach(filterKey => {
            this.closeDropdown(filterKey);
        });
    }

    /**
     * Ustawienie dropdown'a w trybie loading
     */
    setDropdownLoading(filterKey, isLoading) {
        const camelCase = this.snakeToCamel(filterKey);
        const container = this.filterElements[`${camelCase}Options`];

        if (!container) return;

        if (isLoading) {
            container.innerHTML = `
                <div class="filter-option">
                    <div class="loading-spinner"></div>
                    <label>Ładowanie...</label>
                </div>
            `;
        } else {
            this.updateDropdownOptions(filterKey);
        }
    }

    /**
     * Konwersja snake_case na camelCase
     */
    snakeToCamel(str) {
        return str.replace(/_([a-z])/g, (match, letter) => letter.toUpperCase());
    }

    /**
     * Sanityzacja ID dla HTML
     */
    sanitizeId(value) {
        return value.replace(/[^a-zA-Z0-9]/g, '_');
    }

    /**
     * Kapitalizacja pierwszej litery
     */
    capitalizeFirst(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    /**
     * Pobieranie kontenera filtru (dla kompatybilności)
     */
    getFilterContainer(filterKey) {
        const camelCase = this.snakeToCamel(filterKey);
        return this.filterElements[`${camelCase}Options`];
    }

    /**
     * Ustawienie walidacji w czasie rzeczywistym
     */
    setupRealTimeValidation() {
        // Walidacja wymiarów dla automatycznego obliczania objętości (stare pola)
        const dimensionFields = [
            this.modalElements.lengthCm,
            this.modalElements.widthCm,
            this.modalElements.thicknessCm,
            this.modalElements.quantity
        ];

        dimensionFields.forEach(field => {
            if (field) {
                field.addEventListener('input', () => {
                    this.calculateVolumePreview();
                });
            }
        });

        // Walidacja ceny brutto dla obliczania netto (stare pola)
        if (this.modalElements.priceGross) {
            this.modalElements.priceGross.addEventListener('input', () => {
                this.calculatePricePreview();
            });
        }
    }

    /**
     * ZAKTUALIZOWANA: Pokazanie modala dodawania/edycji z obsługą wszystkich typów rekordów
     */
    showManualRowModal(record = null, allOrderProducts = null) {
        console.log(`[TableManager] ${record ?
            `Opening modal for edit (${record.is_manual ? 'manual' : 'Baselinker'})` : 'Opening modal for add'}`);

        if (!this.modalElements.modal) {
            console.error('[TableManager] Modal element not found');
            return;
        }

        // Ustaw tytuł i tryb
        const isEdit = record !== null;
        this.currentEditRecord = record;

        if (this.modalElements.title) {
            if (isEdit) {
                const recordType = record.is_manual ? 'ręczne' : 'z Baselinker';
                const productCount = allOrderProducts ? allOrderProducts.length : 1;
                this.modalElements.title.textContent = `Edytuj zamówienie (${recordType}) - ${productCount} produktów`;
            } else {
                this.modalElements.title.textContent = 'Dodaj nowe zamówienie';
            }
        }

        // Wypełnij formularz
        if (isEdit) {
            this.populateFormWithRecord(record, allOrderProducts);
        } else {
            this.resetForm();
        }

        // Przełącz na pierwszą zakładkę
        this.switchTab('client');

        // Pokaż modal
        this.modalElements.modal.classList.add('show');
        this.modalElements.modal.style.display = 'block';

        // Zablokuj scroll na body
        document.body.style.overflow = 'hidden';

        // Focus na pierwszy input
        if (this.modalElements.customerName) {
            setTimeout(() => {
                this.modalElements.customerName.focus();
            }, 100);
        }
    }

    /**
     * ZAKTUALIZOWANA: Ukrycie modala z odblokowanym scroll
     */
    hideManualRowModal() {
        console.log('[TableManager] Hiding manual row modal');

        if (this.modalElements.modal) {
            this.modalElements.modal.classList.remove('show');
            this.modalElements.modal.style.display = 'none';
        }

        // Przywróć scroll
        document.body.style.overflow = '';

        // Zresetuj dane
        this.currentEditRecord = null;
        this.resetForm();
    }

    /**
     * ZAKTUALIZOWANA: Wypełnienie formularza z obsługą wszystkich typów rekordów
     */
    populateFormWithRecord(record, allOrderProducts = null) {
        console.log(`[TableManager] Populating form with ${record.is_manual ? 'manual' : 'Baselinker'} record:`, record.id);
        console.log(`[TableManager] Record date_created value:`, record.date_created, 'type:', typeof record.date_created);

        if (allOrderProducts && allOrderProducts.length > 1) {
            console.log(`[TableManager] Loading ${allOrderProducts.length} products for order`);
        }

        // Podstawowe dane (z pierwszego rekordu lub głównego rekordu)
        this.setFieldValue('recordId', record.id);

        // Tab Klient
        this.setFieldValue('customerName', record.customer_name);
        this.setFieldValue('phone', record.phone);
        this.setFieldValue('caretaker', record.caretaker);
        this.setFieldValue('deliveryAddress', record.delivery_address);
        this.setFieldValue('deliveryPostcode', record.delivery_postcode);
        this.setFieldValue('deliveryCity', record.delivery_city);
        if (record.delivery_state) {
            const stateValue = record.delivery_state.toLowerCase();
            this.setFieldValue('deliveryState', stateValue);
        } else {
            this.setFieldValue('deliveryState', '');
        }

        // Tab Zamówienie - POPRAWIONA OBSŁUGA DATY
        console.log(`[TableManager] Processing date_created: "${record.date_created}"`);
        const formattedDate = convertDateToInputFormat(record.date_created);
        console.log(`[TableManager] Formatted date for input: "${formattedDate}"`);

        this.setFieldValue('dateCreated', formattedDate);
        this.setFieldValue('baselinkerOrderId', record.baselinker_order_id);
        this.setFieldValue('internalOrderNumber', record.internal_order_number);
        this.setFieldValue('orderSource', record.order_source);
        this.setFieldValue('deliveryMethod', record.delivery_method);
        this.setFieldValue('deliveryCost', record.delivery_cost);
        this.setFieldValue('paymentMethod', record.payment_method);
        this.setFieldValue('paidAmountNet', record.paid_amount_net);
        this.setFieldValue('currentStatus', record.current_status);

        // KLUCZOWA ZMIANA: Obsługa wielu produktów
        if (allOrderProducts && allOrderProducts.length > 0) {
            // Mapuj wszystkie produkty z zamówienia
            this.productsData = allOrderProducts.map(productRecord => ({
                group_type: productRecord.group_type || 'towar',
                product_type: productRecord.product_type || 'klejonka',
                wood_species: productRecord.wood_species || '',
                technology: productRecord.technology || '',
                wood_class: productRecord.wood_class || '',
                finish_state: productRecord.finish_state || 'surowy',
                length_cm: productRecord.length_cm || '',
                width_cm: productRecord.width_cm || '',
                thickness_cm: productRecord.thickness_cm || '',
                quantity: productRecord.quantity || 1,
                // KONWERSJA: rekordy z Baselinker mają price_gross, przelicz na netto
                price_net: productRecord.is_manual
                    ? productRecord.price_net || (productRecord.price_gross ? (parseFloat(productRecord.price_gross) / 1.23).toFixed(2) : '')
                    : productRecord.price_gross ? (parseFloat(productRecord.price_gross) / 1.23).toFixed(2) : '',
                // Przechowuj ID rekordu dla późniejszej aktualizacji
                record_id: productRecord.id
            }));

            console.log(`[TableManager] Loaded ${this.productsData.length} products:`, this.productsData);
        } else {
            // Pojedynczy produkt (ręczny rekord lub przypadek fallback)
            this.productsData = [{
                group_type: record.group_type || 'towar',
                product_type: record.product_type || 'klejonka',
                wood_species: record.wood_species || '',
                technology: record.technology || '',
                wood_class: record.wood_class || '',
                finish_state: record.finish_state || 'surowy',
                length_cm: record.length_cm || '',
                width_cm: record.width_cm || '',
                thickness_cm: record.thickness_cm || '',
                quantity: record.quantity || 1,
                price_net: record.is_manual
                    ? record.price_net || (record.price_gross ? (parseFloat(record.price_gross) / 1.23).toFixed(2) : '')
                    : record.price_gross ? (parseFloat(record.price_gross) / 1.23).toFixed(2) : '',
                record_id: record.id
            }];
        }

        // Ustaw aktywny produkt na pierwszy
        this.activeProductIndex = 0;

        // Odśwież interfejs produktów - POPRAWKA: sprawdź czy elementy istnieją
        this.updateProductCountBadge();

        // Sprawdź czy elementy zakładek produktów istnieją
        if (this.tabElements.productsTabs) {
            this.renderProductTabs();
        } else {
            console.warn('[TableManager] Product tabs element not found, skipping tab rendering');
        }

        // Sprawdź czy element listy produktów istnieje
        if (this.tabElements.productsList) {
            this.renderProducts();
            this.showActiveProduct(this.activeProductIndex);
        } else {
            console.warn('[TableManager] Products list element not found, skipping products rendering');
        }

        this.calculateTotals();

        console.log('[TableManager] Form populated with all products from order');
    }

    /**
     * ZAKTUALIZOWANA: Reset formularza z produktami
     */
    resetForm() {
        if (!this.modalElements.form) return;

        this.modalElements.form.reset();

        // Ustaw wartości domyślne - TYLKO ISTNIEJĄCE POLA
        this.setFieldValue('dateCreated', new Date().toISOString().split('T')[0]);
        this.setFieldValue('deliveryCost', '0');
        this.setFieldValue('paidAmountNet', '0');
        this.setFieldValue('currentStatus', 'Nowe - opłacone');
        this.setFieldValue('recordId', '');

        // Zresetuj produkty
        this.productsData = [];
        this.activeProductIndex = 0;
        this.addProduct(); // Dodaj pierwszy produkt
        this.updateProductCountBadge();

        console.log('[TableManager] Form reset');
    }

    /**
     * ZAKTUALIZOWANA: Ustawienie wartości pola - obsługuje input i select
     */
    setFieldValue(fieldName, value) {
        const element = this.modalElements[fieldName];

        if (!element) {
            // Sprawdź czy to stare pole - jeśli tak, po prostu je zignoruj
            const ignoredOldFields = ['quantity', 'finishState', 'productType', 'priceGross', 'lengthCm', 'widthCm', 'thicknessCm', 'groupType', 'woodSpecies', 'technology', 'woodClass'];

            if (ignoredOldFields.includes(fieldName)) {
                // Stare pole - zignoruj bez logowania błędu
                return;
            }

            console.warn(`[TableManager] Element '${fieldName}' not found in modalElements`);
            return;
        }

        // Sprawdź czy value jest null lub undefined
        if (value === null || value === undefined) {
            element.value = '';
            return;
        }

        // Konwertuj value do string
        const stringValue = String(value);

        // Ustaw wartość
        element.value = stringValue;

        // Weryfikuj tylko gdy jest potrzeba (dla select'ów)
        if (element.tagName === 'SELECT' && element.value !== stringValue) {
            // Spróbuj znaleźć odpowiednią opcję
            const options = Array.from(element.options);
            const exactMatch = options.find(option => option.value === stringValue);
            if (exactMatch) {
                element.selectedIndex = exactMatch.index;
            }
        }

        // Wywołaj event dla pól, które mogą mieć listenery
        if (element.tagName === 'SELECT') {
            element.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            element.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    /**
     * ZAKTUALIZOWANA: Próba ustawienia wartości województwa z rozszerzonym debugowaniem
     */
    trySetProvinceValue(selectElement, value) {
        console.log(`[TableManager] trySetProvinceValue called with: "${value}"`);

        if (!value) {
            console.warn('[TableManager] Empty value provided to trySetProvinceValue');
            return false;
        }

        const normalizedValue = value.toLowerCase().trim();
        console.log(`[TableManager] Normalized value: "${normalizedValue}"`);

        // Wylistuj wszystkie dostępne opcje w select'cie
        const allOptions = Array.from(selectElement.options).map(opt => ({
            value: opt.value,
            text: opt.textContent
        }));
        console.log('[TableManager] Available options in select:', allOptions);

        // Mapowanie nazw województw do wartości w select'cie
        const provinceMapping = {
            // Małe litery (dla bezpośrednich wartości)
            'podkarpackie': 'podkarpackie',
            'mazowieckie': 'mazowieckie',
            'śląskie': 'śląskie',
            'slaskie': 'śląskie',
            'dolnośląskie': 'dolnośląskie',
            'dolnoslaskie': 'dolnośląskie',
            'wielkopolskie': 'wielkopolskie',
            'małopolskie': 'małopolskie',
            'malopolskie': 'małopolskie',
            'łódzkie': 'łódzkie',
            'lodzkie': 'łódzkie',
            'lubelskie': 'lubelskie',
            'zachodniopomorskie': 'zachodniopomorskie',
            'pomorskie': 'pomorskie',
            'warmińsko-mazurskie': 'warmińsko-mazurskie',
            'warminsko-mazurskie': 'warmińsko-mazurskie',
            'kujawsko-pomorskie': 'kujawsko-pomorskie',
            'podlaskie': 'podlaskie',
            'świętokrzyskie': 'świętokrzyskie',
            'swietokrzyskie': 'świętokrzyskie',
            'opolskie': 'opolskie',
            'lubuskie': 'lubuskie'
        };

        // Znajdź odpowiadającą wartość
        const mappedValue = provinceMapping[normalizedValue];
        console.log(`[TableManager] Mapped value from dictionary: "${mappedValue}"`);

        if (mappedValue) {
            // Sprawdź czy taka opcja istnieje w select'cie
            const option = selectElement.querySelector(`option[value="${mappedValue}"]`);
            console.log(`[TableManager] Found option for "${mappedValue}":`, option);

            if (option) {
                // Zapamiętaj który element obecnie ma focus
                const activeElement = document.activeElement;
                console.log(`[TableManager] Current focused element:`, activeElement);

                // Ustaw wartość
                selectElement.value = mappedValue;
                console.log(`[TableManager] Successfully set select value to: "${selectElement.value}"`);

                // DODATKOWE: Wymusz refresh UI
                selectElement.selectedIndex = option.index;
                console.log(`[TableManager] Set selectedIndex to: ${option.index}`);

                // Sprawdź czy wartość rzeczywiście się ustawiła
                const finalValue = selectElement.value;
                const selectedOption = selectElement.options[selectElement.selectedIndex];
                console.log(`[TableManager] Final verification - value: "${finalValue}", selectedOption:`, selectedOption);

                // WAŻNE: Wywołaj change event żeby inne systemy wiedziały o zmianie
                selectElement.dispatchEvent(new Event('change', { bubbles: true }));
                console.log(`[TableManager] Change event dispatched for select`);

                // NOWE: Dodatkowe eventy dla pewności, ale BEZ zmiany focus'a
                selectElement.dispatchEvent(new Event('input', { bubbles: true }));

                // POPRAWKA: Przywróć focus na oryginalny element (kod pocztowy)
                if (activeElement && activeElement !== selectElement) {
                    setTimeout(() => {
                        activeElement.focus();
                        console.log(`[TableManager] Focus restored to:`, activeElement);
                    }, 10);
                }

                // NOWE: Wymusz ponowne renderowanie select'a
                setTimeout(() => {
                    // Sprawdzenie stanu i wymuszenie refresh'a
                    const currentValue = selectElement.value;
                    const displayedText = selectElement.options[selectElement.selectedIndex]?.textContent;

                    console.log(`[TableManager] Post-render check - value: "${currentValue}", displayed: "${displayedText}"`);

                    // EKSPERYMENTALNE: Różne metody wymuszania renderingu
                    try {
                        // Metoda 1: Krótkie ukrycie/pokazanie
                        const originalDisplay = selectElement.style.display;
                        selectElement.style.display = 'none';
                        selectElement.offsetHeight; // Trigger reflow
                        selectElement.style.display = originalDisplay;

                        // Metoda 2: Trigger layout recalculation
                        selectElement.style.transform = 'translateZ(0)';
                        setTimeout(() => {
                            selectElement.style.transform = '';
                        }, 1);

                        // Metoda 3: Re-append element to force redraw
                        const parent = selectElement.parentNode;
                        const nextSibling = selectElement.nextSibling;
                        parent.removeChild(selectElement);
                        parent.insertBefore(selectElement, nextSibling);

                        console.log(`[TableManager] All rerender methods applied`);

                        // Final verification
                        setTimeout(() => {
                            const finalCheck = {
                                value: selectElement.value,
                                selectedIndex: selectElement.selectedIndex,
                                selectedText: selectElement.options[selectElement.selectedIndex]?.textContent,
                                visibleValue: selectElement.selectedOptions[0]?.textContent
                            };
                            console.log(`[TableManager] Final visual check:`, finalCheck);
                        }, 100);

                    } catch (error) {
                        console.error(`[TableManager] Error during rerender:`, error);
                    }
                }, 50);

                return true;
            }
        }

        // Jeśli nie znaleziono mapowania, spróbuj dopasować po pierwszych literach
        console.log(`[TableManager] Trying partial matching for: "${normalizedValue}"`);
        const options = Array.from(selectElement.options);
        const matchingOption = options.find(option => {
            const optionValueMatch = option.value.toLowerCase().startsWith(normalizedValue.substring(0, 3));
            const optionTextMatch = option.textContent.toLowerCase().startsWith(normalizedValue.substring(0, 3));
            console.log(`[TableManager] Checking option "${option.value}" (${option.textContent}): value match=${optionValueMatch}, text match=${optionTextMatch}`);
            return optionValueMatch || optionTextMatch;
        });

        if (matchingOption) {
            selectElement.value = matchingOption.value;
            selectElement.dispatchEvent(new Event('change', { bubbles: true }));
            console.log(`[TableManager] Partial match success: ${value} → ${matchingOption.value}`);
            return true;
        }

        console.error(`[TableManager] Could not map province: "${value}" (normalized: "${normalizedValue}")`);
        console.error('[TableManager] No exact or partial match found');
        return false;
    }

    /**
     * Pobieranie wartości pola
     */
    getFieldValue(fieldName) {
        const element = this.modalElements[fieldName];
        return element ? element.value : '';
    }

    /**
     * Obliczanie podglądu objętości (stare pola - zachowane)
     */
    calculateVolumePreview() {
        const length = parseFloat(this.getFieldValue('lengthCm')) || 0;
        const width = parseFloat(this.getFieldValue('widthCm')) || 0;
        const thickness = parseFloat(this.getFieldValue('thicknessCm')) || 0;
        const quantity = parseInt(this.getFieldValue('quantity')) || 0;

        if (length > 0 && width > 0 && thickness > 0 && quantity > 0) {
            const volumePerPiece = (length * width * thickness) / 1000000; // cm3 to m3
            const totalVolume = volumePerPiece * quantity;

            // Pokaż podgląd (można dodać element do formularza)
            console.log('[TableManager] Volume preview:', {
                volumePerPiece: volumePerPiece.toFixed(4),
                totalVolume: totalVolume.toFixed(4)
            });
        }
    }

    /**
     * Obliczanie podglądu ceny netto (stare pola - zachowane)
     */
    calculatePricePreview() {
        const priceGross = parseFloat(this.getFieldValue('priceGross')) || 0;

        if (priceGross > 0) {
            const priceNet = priceGross / 1.23;

            console.log('[TableManager] Price preview:', {
                priceGross: priceGross.toFixed(2),
                priceNet: priceNet.toFixed(2)
            });
        }
    }

    /**
     * ZAKTUALIZOWANA: Zapisywanie z obsługą wielu produktów
     */
    async saveManualRow() {
        console.log('[TableManager] Starting save process...');

        if (!this.validateForm()) {
            console.log('[TableManager] Validation failed, aborting save');
            return;
        }

        this.setLoadingState(true);

        try {
            // Przygotuj dane
            const formData = this.prepareFormData();
            console.log('[TableManager] Form data prepared:', formData);

            // Endpoint
            const endpoint = this.currentEditRecord ?
                '/reports/api/update-manual-row' :
                '/reports/api/add-manual-row';

            console.log('[TableManager] Sending to endpoint:', endpoint);
            console.log('[TableManager] Request payload:', JSON.stringify(formData, null, 2));

            // Wyślij zapytanie
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });

            console.log('[TableManager] Response status:', response.status);
            console.log('[TableManager] Response headers:', response.headers);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('[TableManager] Response data:', result);

            if (result.success) {
                console.log('[TableManager] Save successful');

                // Zamknij modal
                this.hideManualRowModal();

                // Odśwież dane
                if (window.reportsManager) {
                    console.log('[TableManager] Refreshing data...');
                    window.reportsManager.refreshData();
                }

                // Pokaż komunikat sukcesu
                this.showMessage(result.message || 'Zamówienie zostało zapisane', 'success');

            } else {
                throw new Error(result.error || 'Błąd zapisu');
            }

        } catch (error) {
            console.error('[TableManager] Save error:', error);
            console.error('[TableManager] Error details:', {
                message: error.message,
                stack: error.stack
            });
            this.showMessage('Błąd zapisu: ' + error.message, 'error');
        } finally {
            this.setLoadingState(false);
        }
    }

    /**
     * NOWA: Przygotuj dane formularza do wysłania z produktami
     */
    prepareFormData() {
        console.log('[TableManager] Preparing form data...');
        console.log('[TableManager] Current products data:', this.productsData);
        console.log('[TableManager] Current edit record:', this.currentEditRecord);

        // DEBUGOWANIE: Sprawdź wszystkie elementy formularza produktów
        console.log('[TableManager] Debug form elements:');
        console.log('- productsList exists:', !!this.tabElements?.productsList);
        console.log('- productTemplate exists:', !!this.tabElements?.productTemplate);

        // Sprawdź czy są elementy produktów w DOM
        const productItems = document.querySelectorAll('.product-item');
        console.log('[TableManager] Product items in DOM:', productItems.length);

        // NOWA LOGIKA: Zbierz dane bezpośrednio z formularza
        let productsFromForm = [];

        if (productItems.length > 0) {
            // Zbierz dane z każdego elementu produktu w DOM
            productItems.forEach((item, index) => {
                console.log(`[TableManager] Reading product ${index} from DOM...`);

                const productData = {
                    group_type: item.querySelector('[name="group_type"]')?.value || 'towar',
                    product_type: item.querySelector('[name="product_type"]')?.value || 'klejonka',
                    wood_species: item.querySelector('[name="wood_species"]')?.value || '',
                    technology: item.querySelector('[name="technology"]')?.value || '',
                    wood_class: item.querySelector('[name="wood_class"]')?.value || '',
                    finish_state: item.querySelector('[name="finish_state"]')?.value || 'surowy',
                    length_cm: item.querySelector('[name="length_cm"]')?.value || '',
                    width_cm: item.querySelector('[name="width_cm"]')?.value || '',
                    thickness_cm: item.querySelector('[name="thickness_cm"]')?.value || '',
                    quantity: item.querySelector('[name="quantity"]')?.value || 1,
                    price_net: item.querySelector('[name="price_net"]')?.value || ''
                };

                console.log(`[TableManager] Product ${index} from DOM:`, productData);
                productsFromForm.push(productData);
            });
        } else {
            console.log('[TableManager] No product items in DOM, using fallback...');

            // FALLBACK: Zbierz dane ze starych pól formularza (jeśli istnieją)
            const fallbackProduct = {
                group_type: this.getFieldValue('groupType') || 'towar',
                product_type: this.getFieldValue('productType') || 'klejonka',
                wood_species: this.getFieldValue('woodSpecies') || '',
                technology: this.getFieldValue('technology') || '',
                wood_class: this.getFieldValue('woodClass') || '',
                finish_state: this.getFieldValue('finishState') || 'surowy',
                length_cm: this.getFieldValue('lengthCm') || '',
                width_cm: this.getFieldValue('widthCm') || '',
                thickness_cm: this.getFieldValue('thicknessCm') || '',
                quantity: this.getFieldValue('quantity') || 1,
                price_net: this.getFieldValue('priceGross') ? (parseFloat(this.getFieldValue('priceGross')) / 1.23).toFixed(2) : ''
            };

            console.log('[TableManager] Fallback product data:', fallbackProduct);
            productsFromForm.push(fallbackProduct);
        }

        // Sprawdź czy this.productsData jest aktualne
        if (this.productsData && this.productsData.length > 0) {
            console.log('[TableManager] Using this.productsData:', this.productsData);
        } else {
            console.log('[TableManager] Using productsFromForm:', productsFromForm);
            this.productsData = productsFromForm;
        }

        const formData = {
            // Dane podstawowe
            record_id: this.getFieldValue('recordId') || null,

            // Tab Klient
            customer_name: this.getFieldValue('customerName'),
            phone: this.getFieldValue('phone'),
            caretaker: this.getFieldValue('caretaker'),
            delivery_address: this.getFieldValue('deliveryAddress'),
            delivery_postcode: this.getFieldValue('deliveryPostcode'),
            delivery_city: this.getFieldValue('deliveryCity'),
            delivery_state: this.getFieldValue('deliveryState'),

            // Tab Zamówienie
            date_created: this.getFieldValue('dateCreated'),
            baselinker_order_id: this.getFieldValue('baselinkerOrderId') || null,
            internal_order_number: this.getFieldValue('internalOrderNumber'),
            order_source: this.getFieldValue('orderSource'),
            delivery_method: this.getFieldValue('deliveryMethod'),
            delivery_cost: parseFloat(this.getFieldValue('deliveryCost')) || 0,
            payment_method: this.getFieldValue('paymentMethod'),
            paid_amount_net: parseFloat(this.getFieldValue('paidAmountNet')) || 0,
            current_status: this.getFieldValue('currentStatus'),

            // Produkty - sprawdź różne źródła danych
            products: this.productsData.map((product, index) => {
                console.log(`[TableManager] Processing product ${index}:`, product);

                const processedProduct = {
                    group_type: product.group_type || 'towar',
                    product_type: product.product_type || 'klejonka',
                    wood_species: product.wood_species || '',
                    technology: product.technology || '',
                    wood_class: product.wood_class || '',
                    finish_state: product.finish_state || 'surowy',
                    length_cm: parseFloat(product.length_cm) || 0,
                    width_cm: parseFloat(product.width_cm) || 0,
                    thickness_cm: parseFloat(product.thickness_cm) || 0,
                    quantity: parseInt(product.quantity) || 1,
                    price_net: parseFloat(product.price_net) || 0,
                    record_id: product.record_id || null
                };

                console.log(`[TableManager] Processed product ${index}:`, processedProduct);
                return processedProduct;
            })
        };

        console.log('[TableManager] Final form data:', formData);
        return formData;
    }

    /**
     * NOWA: Debug obecnego stanu produktów
     */
    debugProductsState() {
        console.log('=== PRODUCTS DEBUG ===');
        console.log('this.productsData:', this.productsData);
        console.log('this.activeProductIndex:', this.activeProductIndex);
        console.log('this.currentTab:', this.currentTab);

        // Sprawdź elementy DOM
        const productItems = document.querySelectorAll('.product-item');
        console.log('Product items in DOM:', productItems.length);

        productItems.forEach((item, index) => {
            console.log(`Product item ${index}:`, {
                displayed: item.style.display !== 'none',
                groupType: item.querySelector('[name="group_type"]')?.value,
                productType: item.querySelector('[name="product_type"]')?.value,
                length: item.querySelector('[name="length_cm"]')?.value,
                width: item.querySelector('[name="width_cm"]')?.value,
                thickness: item.querySelector('[name="thickness_cm"]')?.value,
                quantity: item.querySelector('[name="quantity"]')?.value,
                priceNet: item.querySelector('[name="price_net"]')?.value
            });
        });

        // Sprawdź zakładki
        const productTabs = document.querySelectorAll('.product-tab-btn');
        console.log('Product tabs:', productTabs.length);

        console.log('=== END DEBUG ===');
    }

    /**
     * ZAKTUALIZOWANA: Walidacja formularza z produktami
     */
    validateForm() {
        console.log('[TableManager] Validating form...');
        const errors = [];

        // Walidacja danych klienta
        const customerName = this.getFieldValue('customerName');
        console.log('[TableManager] Customer name:', customerName);
        if (!customerName) {
            errors.push('Imię i nazwisko klienta jest wymagane');
        }

        const dateCreated = this.getFieldValue('dateCreated');
        console.log('[TableManager] Date created:', dateCreated);
        if (!dateCreated) {
            errors.push('Data zamówienia jest wymagana');
        }

        // Walidacja produktów
        console.log('[TableManager] Products data for validation:', this.productsData);
        if (!this.productsData || this.productsData.length === 0) {
            errors.push('Musi być dodany przynajmniej jeden produkt');
        } else {
            // Walidacja każdego produktu
            this.productsData.forEach((product, index) => {
                console.log(`[TableManager] Validating product ${index}:`, product);

                if (!product.group_type) {
                    errors.push(`Produkt ${index + 1}: Grupa jest wymagana`);
                }

                // NOWE: Różna walidacja dla usług vs produktów fizycznych
                if (product.group_type === 'usługa') {
                    // === WALIDACJA DLA USŁUG ===
                    if (!product.quantity || parseInt(product.quantity) <= 0) {
                        errors.push(`Usługa ${index + 1}: Ilość musi być większa od 0`);
                    }
                    if (!product.price_net || parseFloat(product.price_net) <= 0) {
                        errors.push(`Usługa ${index + 1}: Cena netto jest wymagana`);
                    }

                    console.log(`[TableManager] Usługa ${index + 1}: walidacja przeszła`);
                } else {
                    // === WALIDACJA DLA PRODUKTÓW FIZYCZNYCH (istniejąca logika) ===
                    if (!product.product_type) {
                        errors.push(`Produkt ${index + 1}: Rodzaj jest wymagany`);
                    }
                    if (!product.length_cm || parseFloat(product.length_cm) <= 0) {
                        errors.push(`Produkt ${index + 1}: Długość musi być większa od 0`);
                    }
                    if (!product.width_cm || parseFloat(product.width_cm) <= 0) {
                        errors.push(`Produkt ${index + 1}: Szerokość musi być większa od 0`);
                    }
                    if (!product.thickness_cm || parseFloat(product.thickness_cm) <= 0) {
                        errors.push(`Produkt ${index + 1}: Grubość musi być większa od 0`);
                    }
                    if (!product.quantity || parseInt(product.quantity) <= 0) {
                        errors.push(`Produkt ${index + 1}: Ilość musi być większa od 0`);
                    }

                    console.log(`[TableManager] Produkt fizyczny ${index + 1}: walidacja przeszła`);
                }
            });
        }

        console.log('[TableManager] Validation errors:', errors);

        if (errors.length > 0) {
            this.showMessage('Błędy walidacji:\n' + errors.join('\n'), 'error');
            return false;
        }

        console.log('[TableManager] Form validation passed');
        return true;
    }

    /**
     * STARA METODA - zachowana dla kompatybilności
     */
    collectFormData() {
        const data = {};

        // Pobierz wszystkie wartości z formularza
        Object.keys(this.modalElements).forEach(key => {
            if (key !== 'modal' && key !== 'title' && key !== 'form' &&
                key !== 'cancelBtn' && key !== 'saveBtn' && key !== 'closeBtn') {
                const value = this.getFieldValue(key);
                if (value !== '') {
                    data[this.camelToSnake(key)] = value;
                }
            }
        });

        console.log('[TableManager] Collected form data:', data);
        return data;
    }

    /**
     * Konwersja camelCase na snake_case
     */
    camelToSnake(str) {
        return str.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`);
    }

    /**
     * Ustawienie stanu ładowania dla modala
     */
    setLoadingState(loading) {
        if (this.modalElements.saveBtn) {
            this.modalElements.saveBtn.disabled = loading;
            this.modalElements.saveBtn.innerHTML = loading ?
                '<i class="fas fa-spinner fa-spin"></i> Zapisywanie...' :
                '<i class="fas fa-save"></i> Zapisz';
        }

        if (this.modalElements.cancelBtn) {
            this.modalElements.cancelBtn.disabled = loading;
        }
    }

    /**
     * Pokazywanie komunikatu
     */
    showMessage(message, type = 'info') {
        console.log(`[TableManager] ${type.toUpperCase()}:`, message);

        // TODO: Implementacja lepszego systemu notyfikacji
        if (type === 'error') {
            alert('Błąd: ' + message);
        } else if (type === 'success') {
            console.log('Success:', message);
        } else if (type === 'warning') {
            console.warn('Warning:', message);
        }
    }

    /**
     * Obsługa kliknięć w przyciski edycji w tabeli
     */
    handleEditButtonClick(recordId, event) {
        event.preventDefault();
        event.stopPropagation();

        console.log('[TableManager] Edit button clicked for record:', recordId, 'type:', typeof recordId);

        try {
            // POPRAWKA: Konwertuj recordId na liczbę jeśli to string
            const numericRecordId = typeof recordId === 'string' ? parseInt(recordId, 10) : recordId;
            console.log('[TableManager] Converted recordId:', numericRecordId, 'type:', typeof numericRecordId);

            // Znajdź rekord w danych
            if (window.reportsManager && window.reportsManager.currentData) {
                console.log('[TableManager] Searching in', window.reportsManager.currentData.length, 'records');

                // POPRAWKA: Porównuj zarówno jako string jak i jako liczbę
                const clickedRecord = window.reportsManager.currentData.find(r => {
                    return r.id === numericRecordId || r.id === recordId || String(r.id) === String(recordId);
                });

                if (clickedRecord) {
                    console.log('[TableManager] Found record:', clickedRecord.id, 'baselinker_order_id:', clickedRecord.baselinker_order_id);

                    // NOWA LOGIKA: Jeśli to zamówienie z Baselinker, zbierz wszystkie produkty
                    let orderProducts = [];

                    if (clickedRecord.baselinker_order_id) {
                        // Znajdź wszystkie produkty z tym samym baselinker_order_id
                        orderProducts = window.reportsManager.currentData.filter(r =>
                            r.baselinker_order_id === clickedRecord.baselinker_order_id
                        );

                        console.log(`[TableManager] Found ${orderProducts.length} products for Baselinker order ${clickedRecord.baselinker_order_id}`);
                    } else {
                        // Dla ręcznych rekordów, tylko jeden produkt
                        orderProducts = [clickedRecord];
                        console.log('[TableManager] Manual record - single product');
                    }

                    // Pokaż modal z wszystkimi produktami
                    this.showManualRowModal(clickedRecord, orderProducts);
                } else {
                    // DEBUG: Pokaż kilka pierwszych rekordów do analizy
                    const sampleRecords = window.reportsManager.currentData.slice(0, 3).map(r => ({
                        id: r.id,
                        id_type: typeof r.id,
                        customer_name: r.customer_name
                    }));
                    console.log('[TableManager] Sample records for debugging:', sampleRecords);
                    console.log('[TableManager] Looking for recordId:', recordId, 'converted:', numericRecordId);

                    this.showMessage('Nie znaleziono rekordu do edycji', 'error');
                }
            } else {
                console.error('[TableManager] No data available - reportsManager or currentData missing');
                this.showMessage('Dane nie są dostępne', 'error');
            }
        } catch (error) {
            console.error('[TableManager] Error in handleEditButtonClick:', error);
            this.showMessage('Błąd podczas otwierania edycji: ' + error.message, 'error');
        }
    }

    /**
     * Sprawdzenie czy dropdown jest otwarty
     */
    isDropdownOpen(filterKey) {
        return this.dropdownStates[filterKey] || false;
    }

    /**
     * Refresh dropdown'a po zmianie danych
     */
    refreshDropdown(filterKey) {
        this.updateDropdownOptions(filterKey);

        // Jeśli dropdown jest otwarty, odśwież search
        if (this.isDropdownOpen(filterKey)) {
            const camelCase = this.snakeToCamel(filterKey);
            const search = this.filterElements[`search${this.capitalizeFirst(camelCase)}`];
            if (search) {
                this.filterDropdownOptions(filterKey, search.value);
            }
        }
    }

    /**
     * Pobieranie aktualnych filtrów
     */
    getCurrentFilters() {
        return { ...this.activeFilters };
    }

    /**
     * Sprawdzenie czy jakiś filtr jest aktywny
     */
    hasActiveFilters() {
        return Object.keys(this.activeFilters).some(key =>
            this.activeFilters[key] && this.activeFilters[key].length > 0
        );
    }

    /**
     * Pobieranie liczby aktywnych filtrów
     */
    getActiveFiltersCount() {
        return Object.keys(this.activeFilters).reduce((count, key) => {
            return count + (this.activeFilters[key] ? this.activeFilters[key].length : 0);
        }, 0);
    }

    /**
     * Eksport stanu filtrów
     */
    exportFiltersState() {
        return {
            activeFilters: { ...this.activeFilters },
            dropdownStates: { ...this.dropdownStates }
        };
    }

    /**
     * Import stanu filtrów
     */
    importFiltersState(state) {
        if (state.activeFilters) {
            this.activeFilters = { ...state.activeFilters };
        }
        if (state.dropdownStates) {
            this.dropdownStates = { ...state.dropdownStates };
        }

        // Aktualizuj interfejs
        Object.keys(this.activeFilters).forEach(filterKey => {
            this.updateDropdownOptions(filterKey);
        });
    }

    /**
     * Publiczne API
     */
    refreshDropdownData() {
        console.log('[TableManager] Manual dropdown refresh requested');
        this.loadDropdownData();
    }

    getDropdownData(fieldName) {
        return this.dropdownData[fieldName] || [];
    }

    getActiveFilters() {
        return { ...this.activeFilters };
    }

    setActiveFilters(filters) {
        this.activeFilters = { ...filters };

        // Aktualizuj interfejs
        Object.keys(this.activeFilters).forEach(filterKey => {
            this.updateDropdownOptions(filterKey);
        });
    }

    /**
     * Obsługa zmiany trybu fullscreen
     */
    onFullscreenChange(isFullscreen) {
        console.log('[TableManager] Fullscreen mode changed:', isFullscreen);

        // Zamknij wszystkie dropdown'y przy zmianie trybu
        this.closeAllDropdowns();

        // Dostosuj filtry do trybu fullscreen
        this.adaptFiltersToFullscreen(isFullscreen);

        // Zarządzaj dropdown'ami w fullscreen
        this.manageFullscreenDropdowns();

        // Odśwież dropdown'y po zmianie trybu
        setTimeout(() => {
            this.refreshAllDropdowns();
        }, 300);
    }

    /**
     * Dostosowanie filtrów do trybu fullscreen
     */
    adaptFiltersToFullscreen(isFullscreen) {
        const filterKeys = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        filterKeys.forEach(filterKey => {
            const camelCase = this.snakeToCamel(filterKey);
            const dropdown = this.filterElements[`${camelCase}Dropdown`];
            const menu = this.filterElements[`${camelCase}Menu`];

            if (dropdown && menu) {
                if (isFullscreen) {
                    // Zmniejsz maksymalną wysokość menu w fullscreen
                    menu.style.maxHeight = '180px';

                    // Dodaj klasy fullscreen
                    dropdown.classList.add('fullscreen-mode');
                } else {
                    // Przywróć normalne rozmiary
                    menu.style.maxHeight = '300px';

                    // Usuń klasy fullscreen
                    dropdown.classList.remove('fullscreen-mode');
                }
            }
        });

        // Dostosuj wysokość options containers
        const optionsContainers = document.querySelectorAll('.filter-options');
        optionsContainers.forEach(container => {
            if (isFullscreen) {
                container.style.maxHeight = '150px';
            } else {
                container.style.maxHeight = '200px';
            }
        });
    }

    /**
     * Odświeżenie wszystkich dropdown'ów
     */
    refreshAllDropdowns() {
        const filterKeys = ['customer_name', 'delivery_state', 'wood_species', 'current_status'];

        filterKeys.forEach(filterKey => {
            this.refreshDropdown(filterKey);
        });
    }

    /**
     * Sprawdzenie czy jesteśmy w trybie fullscreen
     */
    isInFullscreenMode() {
        if (window.fullscreenManager && typeof window.fullscreenManager.isFullscreenActive === 'function') {
            return window.fullscreenManager.isFullscreenActive();
        }
        return false;
    }

    /**
     * Debug info z fullscreen
     */
    getDebugInfo() {
        return {
            activeFilters: this.activeFilters,
            dropdownStates: this.dropdownStates,
            dropdownData: Object.keys(this.dropdownData).reduce((acc, key) => {
                acc[key] = this.dropdownData[key].length;
                return acc;
            }, {}),
            hasActiveFilters: this.hasActiveFilters(),
            activeFiltersCount: this.getActiveFiltersCount(),
            isInitialized: this.isInitialized,
            isFullscreen: this.isInFullscreenMode(),
            // Informacje o fullscreen
            fullscreenManager: {
                available: !!window.fullscreenManager,
                active: this.isInFullscreenMode()
            },
            // NOWE: Informacje o zakładkach i produktach
            currentTab: this.currentTab,
            productsCount: this.productsData.length,
            currentEditRecord: this.currentEditRecord ? this.currentEditRecord.id : null
        };
    }

    /**
     * Publiczne API dla fullscreen
     */

    // Dostosuj filtry do fullscreen
    adaptToFullscreen() {
        this.adaptFiltersToFullscreen(true);
    }

    // Przywróć filtry do normalnego trybu
    adaptToNormal() {
        this.adaptFiltersToFullscreen(false);
    }

    // Odśwież wszystkie dropdown'y
    refreshAllFilters() {
        this.refreshAllDropdowns();
    }

    // Sprawdź czy filtry są w trybie fullscreen
    isFiltersInFullscreen() {
        return this.isInFullscreenMode();
    }

    /**
     * Optymalizacja dla fullscreen
     */
    optimizeForFullscreen() {
        // Zamknij wszystkie otwarte dropdown'y
        this.closeAllDropdowns();

        // Wyczyść search inputy
        const searchInputs = document.querySelectorAll('.filter-search-input');
        searchInputs.forEach(input => {
            input.value = '';
        });

        // Dostosuj rozmiary
        this.adaptFiltersToFullscreen(true);

        console.log('[TableManager] Optimized for fullscreen');
    }

    /**
     * Przywrócenie po fullscreen
     */
    restoreFromFullscreen() {
        // Przywróć normalne rozmiary
        this.adaptFiltersToFullscreen(false);

        // Odśwież wszystkie dropdown'y
        this.refreshAllDropdowns();

        console.log('[TableManager] Restored from fullscreen');
    }

    /**
     * Sprawdzenie czy dropdown może być otwarty w fullscreen
     */
    canOpenDropdownInFullscreen(filterKey) {
        if (!this.isInFullscreenMode()) return true;

        const dataLength = this.dropdownData[filterKey] ? this.dropdownData[filterKey].length : 0;
        return dataLength <= 100; // Limit dla fullscreen
    }

    /**
     * Otwarcie dropdown z walidacją fullscreen
     */
    openDropdownWithValidation(filterKey) {
        if (!this.canOpenDropdownInFullscreen(filterKey)) {
            console.warn(`[TableManager] Too many options for dropdown in fullscreen: ${filterKey}`);
            return;
        }

        this.openDropdown(filterKey);
    }

    /**
     * NOWE API dla systemu zakładek
     */

    // Przełącz na konkretną zakładkę
    switchToTab(tabName) {
        this.switchTab(tabName);
    }

    // Pobierz aktywną zakładkę
    getCurrentTab() {
        return this.currentTab;
    }

    // Pobierz liczbę produktów
    getProductsCount() {
        return this.productsData.length;
    }

    // Pobierz dane produktów
    getProductsData() {
        return [...this.productsData];
    }

    // Wyczyść wszystkie produkty i dodaj jeden pusty
    resetProducts() {
        this.productsData = [];
        this.addProduct();
    }

    // Sprawdź czy formularz jest w trybie edycji
    isEditMode() {
        return this.currentEditRecord !== null;
    }

    // Pobierz rekord w trybie edycji
    getCurrentEditRecord() {
        return this.currentEditRecord;
    }

    /**
     * NOWA: Aktualizuj zakładki produktów
     */
    updateProductTabs() {
        this.renderProductTabs();
    }

    /**
     * NOWA: Wyświetl aktualny produkt
     */
    displayCurrentProduct() {
        if (this.productsData.length === 0) {
            console.warn('[TableManager] No products data to display');
            return;
        }

        // Renderuj wszystkie produkty
        this.renderProducts();

        // Pokaż aktywny produkt
        this.showActiveProduct(this.activeProductIndex);
    }

    /**
     * NOWA: Aktualizuj podsumowanie produktów
     */
    updateProductsSummary() {
        this.calculateTotals();
    }

    /**
     * NOWE: API dla PostcodeAutoFill - umożliwia ustawianie wartości z zewnątrz
     */
    setFormFieldValue(fieldName, value) {
        console.log(`[TableManager] External field update: ${fieldName} = ${value}`);
        this.setFieldValue(fieldName, value);
    }

    /**
     * NOWE: API dla PostcodeAutoFill - sprawdza czy modal jest otwarty
     */
    isModalOpen() {
        return this.modalElements.modal &&
            this.modalElements.modal.style.display === 'block' &&
            this.modalElements.modal.classList.contains('show');
    }

    /**
     * NOWE: Obsługa błędów walidacji per zakładka
     */
    showTabValidationError(tabName, message) {
        // Przełącz na zakładkę z błędem
        this.switchTab(tabName);

        // Dodaj wizualny wskaźnik błędu na zakładce
        const tabButton = document.querySelector(`[data-tab="${tabName}"]`);
        if (tabButton) {
            tabButton.classList.add('tab-error');
            setTimeout(() => {
                tabButton.classList.remove('tab-error');
            }, 3000);
        }

        // Pokaż komunikat
        this.showMessage(message, 'error');
    }

    /**
     * NOWE: Walidacja per zakładka
     */
    validateTab(tabName) {
        const errors = [];

        switch (tabName) {
            case 'client':
                if (!this.getFieldValue('customerName')) {
                    errors.push('Imię i nazwisko klienta jest wymagane');
                }
                break;

            case 'products':
                if (this.productsData.length === 0) {
                    errors.push('Musi być dodany przynajmniej jeden produkt');
                }
                this.productsData.forEach((product, index) => {
                    if (!product.group_type) {
                        errors.push(`Produkt ${index + 1}: Grupa jest wymagana`);
                    }
                    if (!product.product_type) {
                        errors.push(`Produkt ${index + 1}: Rodzaj jest wymagany`);
                    }
                    if (!product.length_cm || product.length_cm <= 0) {
                        errors.push(`Produkt ${index + 1}: Długość musi być większa od 0`);
                    }
                });
                break;

            case 'order':
                if (!this.getFieldValue('dateCreated')) {
                    errors.push('Data zamówienia jest wymagana');
                }
                break;
        }

        return {
            isValid: errors.length === 0,
            errors: errors
        };
    }

    /**
     * NOWE: Walidacja wszystkich zakładek z przełączaniem na błędną
     */
    validateAllTabs() {
        const tabs = ['client', 'products', 'order'];

        for (const tab of tabs) {
            const validation = this.validateTab(tab);
            if (!validation.isValid) {
                this.showTabValidationError(tab, validation.errors.join('\n'));
                return false;
            }
        }

        return true;
    }

    /**
     * NOWE: Automatyczne zapisywanie draftu (opcjonalnie)
     */
    saveDraft() {
        if (!window.localStorage) return;

        const draftData = {
            timestamp: Date.now(),
            currentTab: this.currentTab,
            formData: this.prepareFormData(),
            productsData: this.productsData
        };

        try {
            localStorage.setItem('reports_modal_draft', JSON.stringify(draftData));
            console.log('[TableManager] Draft saved');
        } catch (error) {
            console.warn('[TableManager] Failed to save draft:', error);
        }
    }

    /**
     * NOWE: Ładowanie draftu
     */
    loadDraft() {
        if (!window.localStorage) return null;

        try {
            const draftJson = localStorage.getItem('reports_modal_draft');
            if (draftJson) {
                const draft = JSON.parse(draftJson);

                // Sprawdź czy draft nie jest starszy niż godzina
                const hourAgo = Date.now() - (60 * 60 * 1000);
                if (draft.timestamp > hourAgo) {
                    return draft;
                }
            }
        } catch (error) {
            console.warn('[TableManager] Failed to load draft:', error);
        }

        return null;
    }

    /**
     * NOWE: Wyczyść draft
     */
    clearDraft() {
        if (!window.localStorage) return;

        try {
            localStorage.removeItem('reports_modal_draft');
            console.log('[TableManager] Draft cleared');
        } catch (error) {
            console.warn('[TableManager] Failed to clear draft:', error);
        }
    }
}

// Export dla global scope
window.TableManager = TableManager;

/**
* Funkcja konwersji formatu daty
* @param {string} dateString - Data w formacie "dd-MM-yyyy" lub "yyyy-MM-dd"
* @returns {string} - Data w formacie "yyyy-MM-dd" dla input[type="date"]
*/
function convertDateToInputFormat(dateString) {
    if (!dateString) {
        return new Date().toISOString().split('T')[0];
    }

    try {
        // Format już prawidłowy yyyy-MM-dd
        if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
            return dateString;
        }

        // Format dd-MM-yyyy → yyyy-MM-dd  
        const ddmmyyyyMatch = dateString.match(/^(\d{2})-(\d{2})-(\d{4})$/);
        if (ddmmyyyyMatch) {
            const [, day, month, year] = ddmmyyyyMatch;
            return `${year}-${month}-${day}`;
        }

        // Format ISO z czasem
        if (dateString.includes('T')) {
            return dateString.split('T')[0];
        }

        // Spróbuj parsować jako Date
        const dateObj = new Date(dateString);
        if (!isNaN(dateObj.getTime())) {
            return dateObj.toISOString().split('T')[0];
        }

        // Fallback
        return new Date().toISOString().split('T')[0];

    } catch (error) {
        return new Date().toISOString().split('T')[0];
    }
}