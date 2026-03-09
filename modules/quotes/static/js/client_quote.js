// ===================================
// CLIENT QUOTE JS - Wood Power v3.0
// Redesign 2025
// ===================================

// ===================================
// GLOBAL STATE
// ===================================
const globalState = {
    quoteData: null,
    selectedVariants: new Map(),
    currentProductIndex: 1,
    isQuoteAccepted: window.IS_ACCEPTED || false,
    isLoading: false,
    hasUnsavedChanges: false
};

// ===================================
// API CALLS
// ===================================
const api = {
    /**
     * Wykonuje request do API
     * @param {string} url - URL endpointu
     * @param {Object} options - Opcje fetch
     * @returns {Promise} Odpowiedź z API
     */
    async call(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        };

        const config = { ...defaultOptions, ...options };

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (!response.ok) {
                const errorMessage = data.error || data.message || `Błąd serwera (${response.status})`;
                throw new Error(errorMessage);
            }

            return data;
        } catch (error) {
            console.error('[API] Request failed:', error);
            throw error;
        }
    },

    /**
     * Pobiera dane wyceny
     * @param {string} token - Token publiczny wyceny
     * @returns {Promise} Dane wyceny
     */
    async getQuoteData(token) {
        return this.call(`/quotes/api/client/quote/${token}`);
    },

    /**
     * Aktualizuje wybrany wariant
     * @param {string} token - Token publiczny wyceny
     * @param {number} itemId - ID wybranego wariantu
     * @returns {Promise} Odpowiedź z API
     */
    async updateVariant(token, itemId) {
        return this.call(`/quotes/api/client/quote/${token}/update-variant`, {
            method: 'PATCH',
            body: JSON.stringify({ item_id: itemId })
        });
    },

    /**
     * Akceptuje wycenę
     * @param {string} token - Token publiczny wyceny
     * @param {Object} data - Dane do akceptacji
     * @returns {Promise} Odpowiedź z API
     */
    async acceptQuote(token, data) {
        return this.call(`/quotes/api/client/quote/${token}/accept`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
};

// ===================================
// UTILS
// ===================================
const utils = {
    /**
     * Formatuje kwotę w PLN
     * @param {number} amount - Kwota
     * @returns {string} Sformatowana kwota
     */
    formatCurrency(amount) {
        return new Intl.NumberFormat('pl-PL', {
            style: 'currency',
            currency: 'PLN'
        }).format(amount || 0);
    },

    /**
     * Tłumaczy kod wariantu na czytelną nazwę
     * @param {string} code - Kod wariantu
     * @returns {string} Nazwa wariantu
     */
    translateVariantCode(code) {
        const dict = {
            'dab-lity-ab': 'Klejonka dębowa lita A/B',
            'dab-lity-bb': 'Klejonka dębowa lita B/B',
            'dab-micro-ab': 'Klejonka dębowa mikrowczep A/B',
            'dab-micro-bb': 'Klejonka dębowa mikrowczep B/B',
            'jes-lity-ab': 'Klejonka jesionowa lita A/B',
            'jes-micro-ab': 'Klejonka jesionowa mikrowczep A/B',
            'buk-lity-ab': 'Klejonka bukowa lita A/B',
            'buk-micro-ab': 'Klejonka bukowa mikrowczep A/B'
        };
        return dict[code] || code || 'Nieznany wariant';
    },

    /**
     * Sprawdza czy urządzenie jest mobilne
     * @returns {boolean} True jeśli mobilne
     */
    isMobile() {
        return window.innerWidth <= 768;
    },

    /**
     * Pokazuje/ukrywa loading
     * @param {boolean} show - Czy pokazać loading
     */
    setLoading(show) {
        const loadingEl = document.getElementById('loadingOverlay');
        if (loadingEl) {
            loadingEl.classList.toggle('hidden', !show);
        }
        globalState.isLoading = show;
    },

    /**
     * Pokazuje alert z komunikatem
     * @param {string} message - Treść komunikatu
     * @param {string} type - Typ komunikatu (success, error, warning)
     */
    showAlert(message, type = 'info') {
        // TODO: Implementacja toastu/alertu
        console.log(`[Alert ${type}]:`, message);
    },

    /**
    * Generuje kod QR
    * @param {string} text - Tekst do zakodowania
    * @param {string} elementId - ID elementu canvas
    */
    generateQRCode(text, elementId = 'qrCode') {
        const canvas = document.getElementById(elementId);
        if (!canvas) {
            console.error('QR Canvas element not found:', elementId);
            return;
        }

        if (!window.QRCode) {
            console.error('QRCode library not loaded');
            return;
        }

        // Wyczyść poprzedni kod
        canvas.innerHTML = '';

        try {
            new QRCode(canvas, {
                text: text,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.H
            });
            console.log('QR code generated successfully for:', text);
        } catch (error) {
            console.error('Error generating QR code:', error);
        }
    }
};

// ===================================
// RENDER FUNCTIONS
// ===================================
const render = {
    /**
     * Renderuje przyciski/dropdown produktów
     */
    productTabs() {
        const buttonsContainer = document.getElementById('productButtons');
        const selectElement = document.getElementById('productSelect');

        if (!buttonsContainer || !selectElement || !globalState.quoteData) return;

        buttonsContainer.innerHTML = '';
        selectElement.innerHTML = '';

        // Grupuj produkty według product_index
        const products = this.groupProductsByIndex();

        products.forEach(product => {
            // Desktop button
            const button = document.createElement('button');
            button.className = `product-button ${product.index === globalState.currentProductIndex ? 'active' : ''}`;
            button.onclick = () => handlers.switchProduct(product.index);
            button.innerHTML = `
                <div class="product-button-title">Produkt ${product.index}</div>
                <div class="product-button-dimensions">${product.dimensions}</div>
            `;
            buttonsContainer.appendChild(button);

            // Mobile option
            const option = document.createElement('option');
            option.value = product.index;
            option.textContent = `Produkt ${product.index} - ${product.dimensions}`;
            option.selected = product.index === globalState.currentProductIndex;
            selectElement.appendChild(option);
        });
    },

    /**
     * Renderuje sekcje produktów
     */
    productSections() {
        const sectionsContainer = document.getElementById('productSections');
        if (!sectionsContainer || !globalState.quoteData) return;

        sectionsContainer.innerHTML = '';

        const products = this.groupProductsByIndex();

        products.forEach(product => {
            const section = document.createElement('div');
            section.className = `product-section ${product.index === globalState.currentProductIndex ? 'active' : ''}`;
            section.id = `product-${product.index}`;

            section.innerHTML = `
                <div class="product-header">
                    <div class="product-info">
                        <h2>Produkt ${product.index}</h2>
                        <div class="product-details">
                            <div class="product-detail">
                                <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"></path>
                                </svg>
                                <span>${product.dimensions}</span>
                            </div>
                            <div class="product-detail">
                                <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"></path>
                                </svg>
                                <span>${product.finishing}</span>
                            </div>
                            <div class="product-detail">
                                <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14"></path>
                                </svg>
                                <span>Ilość: ${product.quantity} szt.</span>
                            </div>
                        </div>
                    </div>
                    <div class="product-actions">
                        <button class="btn btn-3d" onclick="handlers.open3DViewer(${product.index})">
                            <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"></path>
                            </svg>
                            3D
                        </button>
                        <button class="btn btn-ar" onclick="handlers.openARModal(${product.index})">
                            <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                            </svg>
                            AR
                        </button>
                    </div>
                </div>

                <div class="variants-grid">
                    ${this.renderVariants(product)}
                </div>

                ${this.renderEdgesSection(product)}

                <div class="save-changes-section ${globalState.hasUnsavedChanges ? 'visible' : 'hidden'}" id="saveChangesSection-${product.index}">
                    <div class="save-changes-content">
                        <span class="save-changes-text">Masz niezapisane zmiany</span>
                        <button class="btn-save-changes" onclick="handlers.saveChanges()">
                            Zapisz zmiany
                        </button>
                    </div>
                </div>
            `;

            sectionsContainer.appendChild(section);
        });
    },

    /**
     * Renderuje sekcję obróbki krawędzi (tylko podgląd) pod wariantami
     * @param {Object} product - Dane produktu
     * @returns {string} HTML sekcji krawędzi
     */
    renderEdgesSection(product) {
        if (!globalState.quoteData?.finishing) return '';

        const finishing = globalState.quoteData.finishing.find(
            f => f.product_index === product.index
        );

        // Sprawdź czy są dane krawędzi
        if (!finishing || !finishing.edges_config || !Array.isArray(finishing.edges_config) || finishing.edges_config.length === 0) {
            return '';
        }

        const edgesConfig = finishing.edges_config;
        const edgesType = finishing.edges_type;
        const edgesRValue = finishing.edges_r_value;
        const edgesSvg = finishing.edges_svg || '';

        // Nazwy krawędzi
        const edgeNames = {
            'A': 'Góra przednia', 'B': 'Góra tylna',
            'C': 'Góra lewa', 'D': 'Góra prawa',
            'E': 'Dół przednia', 'F': 'Dół tylna',
            'G': 'Dół lewa', 'H': 'Dół prawa',
            'N1': 'Narożnik przedni lewy', 'N2': 'Narożnik przedni prawy',
            'N3': 'Narożnik tylny lewy', 'N4': 'Narożnik tylny prawy',
            'KG': 'Krawędź górna (obwód)', 'KD': 'Krawędź dolna (obwód)'
        };

        // Typ obróbki
        const typeLabel = edgesType === 'chamfer' ? 'Fazowanie' : 'Zaokrąglenie';

        // Kąt (tylko dla fazowania)
        const firstEdge = edgesConfig[0];
        const angleValue = firstEdge?.angle_value;
        const angleInfo = (edgesType === 'chamfer' && angleValue) ? `, kąt ${angleValue}°` : '';

        // Pogrupuj krawędzie
        const topEdges = edgesConfig.filter(e => ['A','B','C','D'].includes(e.letter));
        const bottomEdges = edgesConfig.filter(e => ['E','F','G','H'].includes(e.letter));
        const cornerEdges = edgesConfig.filter(e => e.letter && e.letter.startsWith('N'));
        const roundEdges = edgesConfig.filter(e => ['KG','KD'].includes(e.letter));

        const renderEdgeGroup = (label, edges) => {
            if (edges.length === 0) return '';
            return `
                <div class="edges-spec-group">
                    <div class="edges-spec-group-label">${label}</div>
                    <div class="edges-spec-items">
                        ${edges.map(e => `
                            <span class="edges-spec-tag">${e.letter} <span class="edges-spec-tag-name">– ${edgeNames[e.letter] || e.letter}</span></span>
                        `).join('')}
                    </div>
                </div>
            `;
        };

        // SVG podgląd - jeśli zapisany, użyj go; w przeciwnym razie generuj
        let svgPreview = '';
        if (edgesSvg) {
            svgPreview = `<div class="edges-preview-svg">${edgesSvg}</div>`;
        } else {
            const firstItem = product.variants[0];
            if (firstItem) {
                svgPreview = `<div class="edges-preview-svg">${this.generateEdgesIsometricSVG(
                    firstItem.length_cm, firstItem.width_cm, firstItem.thickness_cm, edgesConfig
                )}</div>`;
            }
        }

        return `
            <div class="edges-display-section">
                <div class="edges-display-header">
                    <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6z"></path>
                    </svg>
                    <h3>Obróbka krawędzi</h3>
                </div>
                <div class="edges-display-content">
                    ${svgPreview}
                    <div class="edges-display-spec">
                        <div class="edges-spec-summary">
                            <div class="edges-spec-row">
                                <span class="edges-spec-label">Sposób obróbki:</span>
                                <span class="edges-spec-value">${typeLabel}</span>
                            </div>
                            <div class="edges-spec-row">
                                <span class="edges-spec-label">Promień R:</span>
                                <span class="edges-spec-value">${edgesRValue} mm${angleInfo}</span>
                            </div>
                            <div class="edges-spec-row">
                                <span class="edges-spec-label">Liczba krawędzi:</span>
                                <span class="edges-spec-value">${edgesConfig.length}</span>
                            </div>
                        </div>
                        <div class="edges-spec-details">
                            ${renderEdgeGroup('Krawędzie górne', topEdges)}
                            ${renderEdgeGroup('Krawędzie dolne', bottomEdges)}
                            ${renderEdgeGroup('Narożniki', cornerEdges)}
                            ${renderEdgeGroup('Krawędzie obwodowe', roundEdges)}
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    /**
     * Generuje izometryczny SVG podglądu produktu z zaznaczonymi krawędziami
     * @param {number} length - długość w cm
     * @param {number} width - szerokość w cm
     * @param {number} thickness - grubość w cm
     * @param {Array} edgesConfig - konfiguracja krawędzi
     * @returns {string} HTML SVG
     */
    generateEdgesIsometricSVG(length, width, thickness, edgesConfig) {
        const viewBoxWidth = 320;
        const viewBoxHeight = 220;
        const margin = 35;
        const workWidth = viewBoxWidth - 2 * margin;
        const workHeight = viewBoxHeight - 2 * margin;
        const isoAngle = Math.PI / 6;

        const maxDim = Math.max(length, width);
        const effectiveThickness = Math.max(thickness, maxDim * 0.15);

        const projectedWidth = (length + width) * Math.cos(isoAngle);
        const projectedHeight = (length + width) * Math.sin(isoAngle) + effectiveThickness;

        const scale = Math.min(workWidth / projectedWidth, workHeight / projectedHeight) * 0.85;

        const L = length * scale;
        const W = width * scale;
        const T = effectiveThickness * scale;

        const vecX = { x: Math.cos(isoAngle), y: Math.sin(isoAngle) };
        const vecY = { x: -Math.cos(isoAngle), y: Math.sin(isoAngle) };

        const totalProjWidth = L * vecX.x + W * Math.abs(vecY.x);
        const totalProjHeight = L * vecX.y + W * vecY.y + T;

        const startX = (viewBoxWidth - totalProjWidth) / 2 + W * Math.abs(vecY.x);
        const startY = (viewBoxHeight - totalProjHeight) / 2 + T;

        const tld = { x: startX, y: startY };
        const tpd = { x: tld.x + L * vecX.x, y: tld.y + L * vecX.y };
        const ppd = { x: tpd.x + W * vecY.x, y: tpd.y + W * vecY.y };
        const pld = { x: tld.x + W * vecY.x, y: tld.y + W * vecY.y };
        const tlg = { x: tld.x, y: tld.y - T };
        const tpg = { x: tpd.x, y: tpd.y - T };
        const ppg = { x: ppd.x, y: ppd.y - T };
        const plg = { x: pld.x, y: pld.y - T };

        const selectedLetters = new Set(edgesConfig.map(e => e.letter));
        const mid = (p1, p2) => ({ x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 });

        const edgeCoords = {
            'A': [plg, ppg], 'B': [tlg, tpg], 'C': [tlg, plg], 'D': [tpg, ppg],
            'E': [pld, ppd], 'F': [tld, tpd], 'G': [tld, pld], 'H': [tpd, ppd],
            'N1': [plg, pld], 'N2': [ppg, ppd], 'N3': [tlg, tld], 'N4': [tpg, tpd]
        };
        const hiddenEdges = new Set(['F', 'G', 'N3']);

        const renderLine = (letter) => {
            const [p1, p2] = edgeCoords[letter];
            const isActive = selectedLetters.has(letter);
            const isHidden = hiddenEdges.has(letter);
            return `<line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}"
                stroke="${isActive ? '#ED6B24' : '#666'}" stroke-width="${isActive ? '3' : '2'}"
                ${isHidden && !isActive ? 'stroke-dasharray="4 3"' : ''} fill="none"/>`;
        };

        const renderLabel = (letter, pos, offsetX = 0) => {
            const isActive = selectedLetters.has(letter);
            const r = letter.startsWith('N') ? 14 : 12;
            return `<g>
                <circle cx="${pos.x + offsetX}" cy="${pos.y}" r="${r}"
                    fill="${isActive ? '#ED6B24' : '#f5f5f5'}" stroke="${isActive ? '#ED6B24' : '#ccc'}" stroke-width="1"/>
                <text x="${pos.x + offsetX}" y="${pos.y + 4}" text-anchor="middle" font-size="10"
                    font-family="Poppins, sans-serif" font-weight="600"
                    fill="${isActive ? '#fff' : '#666'}">${letter}</text>
            </g>`;
        };

        return `<svg viewBox="0 0 ${viewBoxWidth} ${viewBoxHeight}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:320px;">
            <polygon points="${tld.x},${tld.y} ${tpd.x},${tpd.y} ${tpg.x},${tpg.y} ${tlg.x},${tlg.y}" fill="#b8b8b8" stroke="none"/>
            <polygon points="${tld.x},${tld.y} ${pld.x},${pld.y} ${plg.x},${plg.y} ${tlg.x},${tlg.y}" fill="#d0d0d0" stroke="none"/>
            <polygon points="${tlg.x},${tlg.y} ${tpg.x},${tpg.y} ${ppg.x},${ppg.y} ${plg.x},${plg.y}" fill="#e8e8e8" stroke="none"/>
            <polygon points="${pld.x},${pld.y} ${ppd.x},${ppd.y} ${ppg.x},${ppg.y} ${plg.x},${plg.y}" fill="#d8d8d8" stroke="none"/>
            <polygon points="${tpd.x},${tpd.y} ${ppd.x},${ppd.y} ${ppg.x},${ppg.y} ${tpg.x},${tpg.y}" fill="#c8c8c8" stroke="none"/>
            ${['F','G','N3','B','C','A','D','E','H','N1','N2','N4'].map(renderLine).join('')}
            ${renderLabel('A', mid(plg, ppg))}
            ${renderLabel('B', mid(tlg, tpg))}
            ${renderLabel('C', mid(tlg, plg))}
            ${renderLabel('D', mid(tpg, ppg))}
            ${renderLabel('E', mid(pld, ppd))}
            ${renderLabel('F', mid(tld, tpd))}
            ${renderLabel('G', mid(tld, pld))}
            ${renderLabel('H', mid(tpd, ppd))}
            ${renderLabel('N1', mid(plg, pld), -14)}
            ${renderLabel('N2', mid(ppg, ppd), 14)}
            ${renderLabel('N3', mid(tlg, tld), -14)}
            ${renderLabel('N4', mid(tpg, tpd), 14)}
        </svg>`;
    },

    /**
 * Renderuje karty wariantów
 * @param {Object} product - Dane produktu
 * @returns {string} HTML wariantów
 */
    renderVariants(product) {
        // Pobierz koszty wykończenia i krawędzi dla tego produktu (wspólne dla wszystkich wariantów)
        const finishing = globalState.quoteData?.finishing?.find(
            f => f.product_index === product.index
        );
        const finishingNetto = (finishing ? (parseFloat(finishing.finishing_price_netto) || 0) + (parseFloat(finishing.edges_price_netto) || 0) : 0);
        const finishingBrutto = (finishing ? (parseFloat(finishing.finishing_price_brutto) || 0) + (parseFloat(finishing.edges_price_brutto) || 0) : 0);

        return product.variants
            .filter(v => v.show_on_client_page !== false)
            .map(variant => {
                const isSelected = globalState.selectedVariants.get(product.index) === variant.id;
                const isDisabled = globalState.isQuoteAccepted && !isSelected;

                // Użyj ścieżki z podwójnym quotes
                const variantImagePath = `/quotes/quotes/static/img/${variant.variant_code}.jpg`;

                // Ceny surowe (już przemnożone przez ilość w API) + koszty wykończenia/krawędzi
                const rawBrutto = variant.final_price_brutto || variant.unit_price_brutto || 0;
                const rawNetto = variant.final_price_netto || variant.unit_price_netto || 0;
                const totalBrutto = rawBrutto + finishingBrutto;
                const totalNetto = rawNetto + finishingNetto;

                // Oblicz cenę jednostkową (podziel przez ilość)
                const quantity = variant.quantity || 1;
                const unitPriceBrutto = totalBrutto / quantity;
                const unitPriceNetto = totalNetto / quantity;

                return `
            <div class="variant-card ${isSelected ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}" 
                 ${globalState.isQuoteAccepted ? '' : `onclick="handlers.selectVariant(${product.index}, ${variant.id})"`}>
                <div class="variant-content">
                    <div class="variant-image" 
                         style="background-image: url('${variantImagePath}')" 
                         onerror="console.error('Failed to load image: ${variantImagePath}')">
                        <div class="variant-badge-overlay ${isSelected ? 'selected' : 'available'}">
                            ${globalState.isQuoteAccepted ? (isSelected ? 'Wybrany' : '') : (isSelected ? 'Wybrany' : 'Wybierz')}
                        </div>
                    </div>
                    <div class="variant-info">
                        <div class="variant-header">
                            <div class="variant-name">${utils.translateVariantCode(variant.variant_code)}</div>
                        </div>
                        <div class="variant-pricing-flex">
                            <div class="price-left">
                                <div class="price-label">Cena:</div>
                                <div class="price-brutto">${utils.formatCurrency(unitPriceBrutto)}</div>
                                <div class="price-netto">${utils.formatCurrency(unitPriceNetto)} netto</div>
                            </div>
                            <div class="price-right">
                                <div class="price-label">Wartość:</div>
                                <div class="price-brutto total">${utils.formatCurrency(totalBrutto)}</div>
                                <div class="price-netto">${utils.formatCurrency(totalNetto)} netto</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
            }).join('');
    },

    /**
     * Renderuje tabelę porównania wariantów
     */
    comparison() {
        const tbody = document.getElementById('comparisonBody');
        if (!tbody || !globalState.quoteData) return;

        const variants = this.getUniqueVariants();

        // POPRAWKA: Pobierz pierwszy produkt jako bazę do porównania
        const firstProduct = this.groupProductsByIndex()[0];
        if (!firstProduct) return;

        // Koszty wykończenia/krawędzi wspólne dla wszystkich wariantów danego produktu
        const finishing = globalState.quoteData?.finishing?.find(f => f.product_index === firstProduct.index);
        const finNetto = finishing ? (parseFloat(finishing.finishing_price_netto) || 0) + (parseFloat(finishing.edges_price_netto) || 0) : 0;
        const finBrutto = finishing ? (parseFloat(finishing.finishing_price_brutto) || 0) + (parseFloat(finishing.edges_price_brutto) || 0) : 0;

        tbody.innerHTML = variants.map(variant => {
            // POPRAWKA: Znajdź wariant dla pierwszego produktu
            const variantForProduct = firstProduct.variants.find(v => v.variant_code === variant.code);
            if (!variantForProduct) return '';

            // Oblicz ceny dla tego konkretnego wariantu (surowe + wykończenie)
            const totalBrutto = (variantForProduct.final_price_brutto || variantForProduct.unit_price_brutto || 0) + finBrutto;
            const totalNetto = (variantForProduct.final_price_netto || variantForProduct.unit_price_netto || 0) + finNetto;

            // Sprawdź czy jest wybrany
            const isSelected = globalState.selectedVariants.get(firstProduct.index) === variantForProduct.id;

            // Oblicz różnicę względem aktualnie wybranego (finishing się skraca)
            const selectedVariantId = globalState.selectedVariants.get(firstProduct.index);
            const selectedVariant = firstProduct.variants.find(v => v.id === selectedVariantId);
            const selectedTotal = selectedVariant ? (selectedVariant.final_price_brutto || selectedVariant.unit_price_brutto || 0) + finBrutto : 0;
            const difference = totalBrutto - selectedTotal;

            return `
            <tr class="${isSelected ? 'selected-row' : ''}">
                <td>${variant.name}</td>
                <td class="price-cell">${utils.formatCurrency(totalNetto)}</td>
                <td class="price-cell">${utils.formatCurrency(totalBrutto)}</td>
                <td class="price-cell">
                    ${difference !== 0 ? (difference > 0 ? '+' : '') + utils.formatCurrency(difference) : '-'}
                </td>
            </tr>
        `;
        }).filter(row => row !== '').join('');
    },

    /**
    * Renderuje podsumowanie na desktop z cenami brutto i netto
    */
    desktopSummary() {
        const summaryContainer = document.getElementById('desktopSummaryContent');
        const totalContainer = document.getElementById('desktopTotalSummary');

        if (!summaryContainer || !totalContainer || !globalState.quoteData) return;

        const selectedItems = this.getSelectedItems();
        const costs = globalState.quoteData.costs || {};

        // Renderuj karty produktów z podziałem na surowe / wykończenie
        summaryContainer.innerHTML = selectedItems.map(item => {
            const product = this.getProductByIndex(item.product_index);
            const variantName = utils.translateVariantCode(item.variant_code);
            const quantity = item.quantity || 1;
            const productName = product ? product.full_name || `Produkt ${item.product_index}` : `Produkt ${item.product_index}`;

            // Koszty wykończenia dla tego produktu
            const finishing = globalState.quoteData?.finishing?.find(f => f.product_index === item.product_index);
            const finishingNetto = finishing ? (parseFloat(finishing.finishing_price_netto) || 0) + (parseFloat(finishing.edges_price_netto) || 0) : 0;
            const finishingBrutto = finishing ? (parseFloat(finishing.finishing_price_brutto) || 0) + (parseFloat(finishing.edges_price_brutto) || 0) : 0;
            const hasFinishing = finishingNetto > 0;

            return `
        <div class="summary-product-card ${item.product_index === globalState.currentProductIndex ? 'active' : ''}" data-product-index="${item.product_index}">
            <div class="summary-product-title">${productName} · ${variantName} <small>(${quantity} szt.)</small></div>
            <div class="summary-product-rows">
                <div class="summary-product-row">
                    <span>Produkt:</span>
                    <span class="summary-product-price">${utils.formatCurrency(item.final_price_brutto)} <small>${utils.formatCurrency(item.final_price_netto)} netto</small></span>
                </div>
                ${hasFinishing ? `
                <div class="summary-product-row">
                    <span>Wykończenie:</span>
                    <span class="summary-product-price">${utils.formatCurrency(finishingBrutto)} <small>${utils.formatCurrency(finishingNetto)} netto</small></span>
                </div>` : ''}
            </div>
        </div>
    `;
        }).join('');

        // Renderuj podsumowanie całkowite
        totalContainer.innerHTML = `
    <div class="summary-total-row">
        <span class="summary-total-label">Produkty:</span>
        <div class="summary-total-value">
            <div class="price-brutto">${utils.formatCurrency(costs.products?.brutto || 0)}</div>
            <div class="price-netto">${utils.formatCurrency(costs.products?.netto || 0)} netto</div>
        </div>
    </div>
    <div class="summary-total-row">
        <span class="summary-total-label">Wykończenie:</span>
        <div class="summary-total-value">
            <div class="price-brutto">${utils.formatCurrency(costs.finishing?.brutto || 0)}</div>
            <div class="price-netto">${utils.formatCurrency(costs.finishing?.netto || 0)} netto</div>
        </div>
    </div>
    <div class="summary-total-row">
        <span class="summary-total-label">Transport:</span>
        <div class="summary-total-value">
            <div class="price-brutto">${utils.formatCurrency(costs.shipping?.brutto || 0)}</div>
            <div class="price-netto">${utils.formatCurrency(costs.shipping?.netto || 0)} netto</div>
        </div>
    </div>
    <div class="summary-total-row total-row">
        <span class="summary-total-label summary-total-main">RAZEM:</span>
        <div class="summary-total-value">
            <div class="price-brutto summary-total-main">${utils.formatCurrency(costs.total?.brutto || 0)}</div>
            <div class="price-netto total-netto">${utils.formatCurrency(costs.total?.netto || 0)} netto</div>
        </div>
    </div>
    `;
    },

    /**
 * Aktualizuje mobilne podsumowanie z cenami brutto i netto
 */
    mobileSummary() {
        const detailsContent = document.getElementById('mobileDetailsContent');
        const totalPrice = document.getElementById('mobileTotalPrice');

        if (!detailsContent || !totalPrice || !globalState.quoteData) return;

        const selectedItems = this.getSelectedItems();
        const costs = globalState.quoteData.costs || {};

        // Aktualizuj całkowitą cenę
        totalPrice.innerHTML = `
        <div class="price-netto mobile-total-netto">${utils.formatCurrency(costs.total?.netto || 0)} netto</div>
        <div class="price-brutto">${utils.formatCurrency(costs.total?.brutto || 0)}</div>
    `;

        // Renderuj karty produktów z podziałem surowe / wykończenie
        detailsContent.innerHTML = `
        <div class="mobile-summary-details">
            ${selectedItems.map(item => {
            const product = this.getProductByIndex(item.product_index);
            const variantName = utils.translateVariantCode(item.variant_code);
            const quantity = item.quantity || 1;
            const productName = product ? product.full_name || `Produkt ${item.product_index}` : `Produkt ${item.product_index}`;

            const finishing = globalState.quoteData?.finishing?.find(f => f.product_index === item.product_index);
            const finishingNetto = finishing ? (parseFloat(finishing.finishing_price_netto) || 0) + (parseFloat(finishing.edges_price_netto) || 0) : 0;
            const finishingBrutto = finishing ? (parseFloat(finishing.finishing_price_brutto) || 0) + (parseFloat(finishing.edges_price_brutto) || 0) : 0;
            const hasFinishing = finishingNetto > 0;

            return `
                    <div class="mobile-summary-product-card">
                        <div class="mobile-summary-product-title">${productName} · ${variantName} <small>(${quantity} szt.)</small></div>
                        <div class="mobile-summary-item">
                            <span>Produkt:</span>
                            <span class="mobile-summary-price">${utils.formatCurrency(item.final_price_brutto)} <small>${utils.formatCurrency(item.final_price_netto)} netto</small></span>
                        </div>
                        ${hasFinishing ? `
                        <div class="mobile-summary-item">
                            <span>Wykończenie:</span>
                            <span class="mobile-summary-price">${utils.formatCurrency(finishingBrutto)} <small>${utils.formatCurrency(finishingNetto)} netto</small></span>
                        </div>` : ''}
                    </div>
                `;
        }).join('')}

        <div class="mobile-summary-section">
            <div class="mobile-summary-item">
                <span>Produkty:</span>
                <div class="mobile-price-stack">
                    <div class="price-netto">${utils.formatCurrency(costs.products?.netto || 0)} netto</div>
                    <div class="price-brutto">${utils.formatCurrency(costs.products?.brutto || 0)}</div>
                </div>
            </div>
            <div class="mobile-summary-item">
                <span>Wykończenie:</span>
                <div class="mobile-price-stack">
                    <div class="price-netto">${utils.formatCurrency(costs.finishing?.netto || 0)} netto</div>
                    <div class="price-brutto">${utils.formatCurrency(costs.finishing?.brutto || 0)}</div>
                </div>
            </div>
            <div class="mobile-summary-item">
                <span>Transport:</span>
                <div class="mobile-price-stack">
                    <div class="price-netto">${utils.formatCurrency(costs.shipping?.netto || 0)} netto</div>
                    <div class="price-brutto">${utils.formatCurrency(costs.shipping?.brutto || 0)}</div>
                </div>
            </div>
            <div class="mobile-summary-item total">
                <span>RAZEM:</span>
                <div class="mobile-price-stack">
                    <div class="price-netto">${utils.formatCurrency(costs.total?.netto || 0)} netto</div>
                    <div class="price-brutto">${utils.formatCurrency(costs.total?.brutto || 0)}</div>
                </div>
            </div>
        </div>
    </div>
    `;
    },

    /**
    * Renderuje porównanie wariantów na desktop
    */
    desktopComparison() {
        const tbody = document.getElementById('desktopComparisonBody');
        if (!tbody || !globalState.quoteData) return;

        const variants = this.getUniqueVariants();

        // POPRAWKA: Pobierz pierwszy produkt jako bazę do porównania
        const firstProduct = this.groupProductsByIndex()[0];
        if (!firstProduct) return;

        // Koszty wykończenia/krawędzi wspólne dla wszystkich wariantów
        const finishing = globalState.quoteData?.finishing?.find(f => f.product_index === firstProduct.index);
        const finNetto = finishing ? (parseFloat(finishing.finishing_price_netto) || 0) + (parseFloat(finishing.edges_price_netto) || 0) : 0;
        const finBrutto = finishing ? (parseFloat(finishing.finishing_price_brutto) || 0) + (parseFloat(finishing.edges_price_brutto) || 0) : 0;

        tbody.innerHTML = variants.map(variant => {
            // POPRAWKA: Znajdź wariant dla pierwszego produktu
            const variantForProduct = firstProduct.variants.find(v => v.variant_code === variant.code);
            if (!variantForProduct) return '';

            // Oblicz ceny dla tego konkretnego wariantu (surowe + wykończenie)
            const totalBrutto = (variantForProduct.final_price_brutto || variantForProduct.unit_price_brutto || 0) + finBrutto;
            const totalNetto = (variantForProduct.final_price_netto || variantForProduct.unit_price_netto || 0) + finNetto;

            // Sprawdź czy jest wybrany
            const isSelected = globalState.selectedVariants.get(firstProduct.index) === variantForProduct.id;

            // Oblicz różnicę względem aktualnie wybranego (finishing się skraca)
            const selectedVariantId = globalState.selectedVariants.get(firstProduct.index);
            const selectedVariant = firstProduct.variants.find(v => v.id === selectedVariantId);
            const selectedTotal = selectedVariant ? (selectedVariant.final_price_brutto || selectedVariant.unit_price_brutto || 0) + finBrutto : 0;
            const difference = totalBrutto - selectedTotal;

            return `
            <tr class="${isSelected ? 'selected-row' : ''}">
                <td>${variant.name}</td>
                <td class="price-cell">${utils.formatCurrency(totalNetto)}</td>
                <td class="price-cell">${utils.formatCurrency(totalBrutto)}</td>
                <td class="price-cell">
                    ${difference !== 0 ? (difference > 0 ?
                    `+${utils.formatCurrency(difference)}` :
                    `${utils.formatCurrency(difference)}`
                ) : '-'}
                </td>
            </tr>
        `;
        }).filter(row => row !== '').join('');
    },

    /**
     * Pobiera wybrane pozycje wyceny
     */
    getSelectedItems() {
        if (!globalState.quoteData?.items) return [];
        return globalState.quoteData.items.filter(item => item.is_selected);
    },

    /**
     * Pobiera produkt według indeksu
     */
    getProductByIndex(index) {
        const products = this.groupProductsByIndex();
        return products.find(p => p.index === index);
    },

    // Helper functions
    groupProductsByIndex() {
        if (!globalState.quoteData || !globalState.quoteData.items) return [];

        const groups = new Map();

        globalState.quoteData.items.forEach(item => {
            if (!groups.has(item.product_index)) {
                // Pobierz dane o wykończeniu dla tego produktu
                const finishing = globalState.quoteData.finishing?.find(
                    f => f.product_index === item.product_index
                );

                groups.set(item.product_index, {
                    index: item.product_index,
                    dimensions: `${item.length_cm} × ${item.width_cm} × ${item.thickness_cm} cm`,
                    volume: `${item.volume_m3.toFixed(3)} m³`,
                    finishing: this.formatFinishing(finishing),
                    quantity: finishing?.quantity || 1,
                    variants: []
                });
            }

            groups.get(item.product_index).variants.push(item);
        });

        return Array.from(groups.values()).sort((a, b) => a.index - b.index);
    },

    formatFinishing(finishing) {
        if (!finishing || !finishing.finishing_type || finishing.finishing_type === 'Brak') {
            return 'Brak wykończenia';
        }

        const parts = [];
        if (finishing.finishing_type) parts.push(finishing.finishing_type);
        if (finishing.finishing_variant) parts.push(finishing.finishing_variant);
        if (finishing.finishing_gloss_level) parts.push(finishing.finishing_gloss_level);
        if (finishing.finishing_color) parts.push(finishing.finishing_color);

        return parts.join(' | ');
    },

    getUniqueVariants() {
        const variantsMap = new Map();
        const products = this.groupProductsByIndex();

        products.forEach(product => {
            product.variants
                .filter(v => v.show_on_client_page !== false)
                .forEach(variant => {
                    if (!variantsMap.has(variant.variant_code)) {
                        variantsMap.set(variant.variant_code, {
                            code: variant.variant_code,
                            name: utils.translateVariantCode(variant.variant_code)
                        });
                    }
                });
        });

        return Array.from(variantsMap.values());
    },

    calculateVariantTotal(variantCode) {
        let totalNetto = 0;
        let totalBrutto = 0;
        const products = this.groupProductsByIndex();

        products.forEach(product => {
            const variant = product.variants.find(v => v.variant_code === variantCode);
            if (variant) {
                // POPRAWKA: Użyj final_price zamiast price
                const priceBrutto = variant.final_price_brutto || variant.unit_price_brutto || 0;
                const priceNetto = variant.final_price_netto || variant.unit_price_netto || 0;

                totalNetto += priceNetto * product.quantity;
                totalBrutto += priceBrutto * product.quantity;
            }
        });

        // Add shipping
        if (globalState.quoteData.shipping_cost_netto) {
            totalNetto += globalState.quoteData.shipping_cost_netto;
        }
        if (globalState.quoteData.shipping_cost_brutto) {
            totalBrutto += globalState.quoteData.shipping_cost_brutto;
        }

        return { netto: totalNetto, brutto: totalBrutto };
    },

    calculateCurrentTotal() {
        let totalNetto = 0;
        let totalBrutto = 0;
        const products = this.groupProductsByIndex();

        products.forEach(product => {
            const selectedId = globalState.selectedVariants.get(product.index);
            const variant = product.variants.find(v => v.id === selectedId);
            if (variant) {
                // POPRAWKA: Użyj final_price zamiast price
                const priceBrutto = variant.final_price_brutto || variant.unit_price_brutto || 0;
                const priceNetto = variant.final_price_netto || variant.unit_price_netto || 0;

                totalNetto += priceNetto * product.quantity;
                totalBrutto += priceBrutto * product.quantity;
            }
        });

        // Add shipping
        if (globalState.quoteData.shipping_cost_netto) {
            totalNetto += globalState.quoteData.shipping_cost_netto;
        }
        if (globalState.quoteData.shipping_cost_brutto) {
            totalBrutto += globalState.quoteData.shipping_cost_brutto;
        }

        return { netto: totalNetto, brutto: totalBrutto };
    },

    isVariantSelected(variantCode) {
        const products = this.groupProductsByIndex();

        return products.some(product => {
            const selectedId = globalState.selectedVariants.get(product.index);
            const variant = product.variants.find(v => v.id === selectedId);
            return variant && variant.variant_code === variantCode;
        });
    },

    /**
     * Odświeża wszystkie elementy UI
     */
    refreshUI() {
        this.productTabs();
        this.productSections();
        this.comparison();
        this.mobileSummary();
        this.desktopSummary();
        this.desktopComparison();
    }

};

// ===================================
// EVENT HANDLERS
// ===================================
const handlers = {
    /**
     * Przełącza między produktami
     * @param {number} index - Indeks produktu
     */
    switchProduct(index) {
        globalState.currentProductIndex = index;

        // Update tabs
        document.querySelectorAll('.product-button').forEach((btn, i) => {
            const products = render.groupProductsByIndex();
            btn.classList.toggle('active', products[i]?.index === index);
        });

        // Update sections
        document.querySelectorAll('.product-section').forEach(section => {
            section.classList.remove('active');
        });
        const activeSection = document.getElementById(`product-${index}`);
        if (activeSection) {
            activeSection.classList.add('active');
        }

        // Update mobile select
        const mobileSelect = document.getElementById('productSelect');
        if (mobileSelect) {
            mobileSelect.value = index;
        }

        // Update summary product cards
        document.querySelectorAll('.summary-product-card').forEach(card => {
            card.classList.toggle('active', parseInt(card.dataset.productIndex) === index);
        });
    },

    /**
     * Wybiera wariant produktu
     * @param {number} productIndex - Indeks produktu
     * @param {number} variantId - ID wariantu
     */
    async selectVariant(productIndex, variantId) {
        if (globalState.isQuoteAccepted || globalState.isLoading) return;

        // POPRAWKA: Sprawdź czy już wybrany wariant
        const currentlySelected = globalState.selectedVariants.get(productIndex);
        if (currentlySelected === variantId) {
            console.log('Wariant już wybrany, nie pokazuj przycisku');
            return; // Nie rób nic jeśli kliknięto już wybrany wariant
        }

        // Zaktualizuj stan lokalny BEZ wywoływania API
        globalState.selectedVariants.set(productIndex, variantId);
        globalState.hasUnsavedChanges = true;

        // Odśwież UI żeby pokazać nowy wybór i przycisk Zapisz
        render.productSections();
        render.comparison();
        render.mobileSummary();
        render.desktopSummary();
        render.desktopComparison();

        // Pokaż przycisk zapisz
        this.showSaveButton();

        utils.showAlert('Wariant został wybrany. Kliknij "Zapisz" aby potwierdzić.', 'info');
    },

    // NOWA funkcja zapisywania zmian:
    async saveChanges() {
        if (!globalState.hasUnsavedChanges || globalState.isLoading) return;

        const saveButton = document.querySelector('.btn-save-changes');
        if (saveButton) {
            saveButton.disabled = true;
            saveButton.textContent = 'Zapisywanie...';
        }

        try {
            utils.setLoading(true);

            // Znajdź ostatnio zmieniony wariant
            const changes = [];
            globalState.selectedVariants.forEach((variantId, productIndex) => {
                changes.push({ productIndex, variantId });
            });

            // Zapisz każdą zmianę przez API
            for (const change of changes) {
                await api.updateVariant(window.QUOTE_TOKEN, change.variantId);
            }

            // Oznacz zmiany jako zapisane
            globalState.hasUnsavedChanges = false;

            // Ukryj przycisk
            this.hideSaveButton();

            // Odśwież dane z serwera
            await init.loadQuoteData();

            utils.showAlert('Zmiany zostały zapisane!', 'success');

        } catch (error) {
            console.error('Błąd przy zapisywaniu zmian:', error);
            utils.showAlert('Błąd przy zapisywaniu zmian', 'error');

            // Przywróć przycisk w przypadku błędu
            if (saveButton) {
                saveButton.disabled = false;
                saveButton.textContent = 'Zapisz zmiany';
            }
        } finally {
            utils.setLoading(false);
        }
    },

    // NOWE funkcje pomocnicze:
    showSaveButton() {
        document.querySelectorAll('.save-changes-section').forEach(section => {
            section.classList.remove('hidden');

            // Opóźnienie żeby animacja zadziałała
            requestAnimationFrame(() => {
                section.classList.add('visible');
            });
        });
    },

    hideSaveButton() {
        document.querySelectorAll('.save-changes-section').forEach(section => {
            section.classList.remove('visible');

            // Opóźnienie przed ukryciem
            setTimeout(() => {
                section.classList.add('hidden');
            }, 400);
        });
    },

    /**
    * Otwiera AR - inteligentnie wybiera między bezpośrednim AR a QR code
    * @param {number} productIndex - Indeks produktu
    */
    openARModal(productIndex) {
        console.log('[ClientAR] Otwieranie AR dla produktu:', productIndex);

        // Sprawdź czy ARHandler jest dostępny
        if (typeof window.ARHandler === 'undefined') {
            console.error('[ClientAR] ARHandler nie jest załadowany');
            utils.showAlert('Błąd: Moduł AR nie jest dostępny. Odśwież stronę.', 'error');
            return;
        }

        // Sprawdź czy są dane wyceny
        if (!globalState.quoteData || !globalState.quoteData.items) {
            console.error('[ClientAR] Brak danych wyceny');
            utils.showAlert('Błąd: Brak danych wyceny', 'error');
            return;
        }

        // Znajdź produkty dla danego indeksu
        const productItems = globalState.quoteData.items.filter(item =>
            item.product_index === productIndex
        );

        if (productItems.length === 0) {
            console.error('[ClientAR] Brak produktów dla indeksu:', productIndex);
            utils.showAlert('Błąd: Nie znaleziono produktów', 'error');
            return;
        }

        // Znajdź aktualnie wybrany wariant
        const currentVariantId = globalState.selectedVariants.get(productIndex);
        let selectedItem = null;

        if (currentVariantId) {
            selectedItem = productItems.find(item => item.id === currentVariantId);
        }

        // Fallback: użyj pierwszego dostępnego lub zaznaczonego
        if (!selectedItem) {
            selectedItem = productItems.find(item => item.is_selected) || productItems[0];
        }

        if (!selectedItem) {
            console.error('[ClientAR] Nie znaleziono wybranego wariantu');
            utils.showAlert('Błąd: Nie można określić wariantu produktu', 'error');
            return;
        }

        // Przygotuj dane produktu w formacie oczekiwanym przez ARHandler
        const productData = {
            variant_code: selectedItem.variant_code,
            product_index: selectedItem.product_index,
            dimensions: {
                length: parseFloat(selectedItem.length_cm),
                width: parseFloat(selectedItem.width_cm),
                thickness: parseFloat(selectedItem.thickness_cm)
            },
            quantity: selectedItem.quantity || 1
        };

        console.log('[ClientAR] Dane produktu dla AR:', productData);

        // INTELIGENTNY WYBÓR: Mobile vs Desktop
        if (utils.isMobile()) {
            // Na mobile - BEZPOŚREDNIO uruchom AR bez modala
            try {
                console.log('[ClientAR] Mobile detected - launching AR directly');
                this.launchDirectAR(productData);
            } catch (error) {
                console.error('[ClientAR] Błąd bezpośredniego AR:', error);
                utils.showAlert(`Błąd AR: ${error.message}`, 'error');
            }
        } else {
            // Na desktop - pokaż nowy modal z QR code
            console.log('[ClientAR] Desktop detected - showing AR modal with QR code');
            this.showDesktopARModal(productData);
        }
    },

    /**
     * Uruchamia AR bezpośrednio na mobile (bez modala)
     */
    async launchDirectAR(productData) {
        console.log('[ClientAR] Bezpośrednie uruchomienie AR dla mobile');

        // Sprawdź czy jesteśmy na iOS Safari
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        const isSafari = /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);

        if (!isIOS) {
            // Android - pokaż komunikat
            utils.showAlert('AR jest dostępne tylko na iPhone i iPad', 'info');
            return;
        }

        if (!isSafari) {
            // iOS ale nie Safari - pokaż komunikat
            utils.showAlert('AR wymaga przeglądarki Safari', 'warning');
            return;
        }

        try {
            // Pokaż krótki loading
            utils.setLoading(true, 'Przygotowywanie AR...');

            console.log('[ClientAR] Wywołanie ARHandler.initiateIOSAR...');

            // Użyj bezpośrednio metody z ARHandler
            await window.ARHandler.initiateIOSAR(productData);

            utils.setLoading(false);
            console.log('[ClientAR] AR uruchomiony pomyślnie');

        } catch (error) {
            utils.setLoading(false);
            console.error('[ClientAR] Błąd bezpośredniego AR:', error);
            utils.showAlert(`Nie udało się uruchomić AR: ${error.message}`, 'error');
        }
    },

    /**
     * NOWA METODA: Pokazuje przycisk do ręcznego uruchomienia AR (fallback)
     */
    showManualARButton(usdzUrl, productData, errorMessage) {
        console.log('[ClientAR] Pokazuję ręczny przycisk AR jako fallback');

        // Utwórz modal z przyciskiem AR
        const modal = this.createARModalElement('Uruchom AR ręcznie', {
            icon: '📱',
            title: 'Kliknij przycisk poniżej aby uruchomić AR',
            message: `Wystąpił problem z automatycznym uruchomieniem AR.\n\nBłąd: ${errorMessage}\n\nModel: ${productData.variant_code}`,
            buttons: [
                {
                    text: 'Uruchom AR',
                    action: () => {
                        window.location.href = usdzUrl;
                        this.closeARModal();
                    },
                    primary: true
                },
                {
                    text: 'Anuluj',
                    action: () => this.closeARModal(),
                    primary: false
                }
            ]
        });

        this.showARModal(modal);
    },

    /**
     * Pokazuje nowy modal AR dla desktop z QR code
     */
    showDesktopARModal(productData) {
        const variant = productData.variant_code || 'Produkt';
        const dims = productData.dimensions || {};
        const dimensions = `${dims.length || 0}×${dims.width || 0}×${dims.thickness || 0} cm`;
        const currentUrl = window.location.href;

        // Utwórz modal w stylu preview3d_ar
        const modal = this.createARModalElement('Rzeczywistość rozszerzona', {
            icon: '🖥️',
            title: 'Zeskanuj kod QR swoim telefonem',
            message: `Model: ${variant}\nWymiary: ${dimensions}\n\nFunkcja AR działa na iPhone i iPad z iOS 12+ oraz Safari.`,
            qrUrl: currentUrl,
            buttons: [
                {
                    text: 'Zamknij',
                    action: () => this.closeARModal(),
                    primary: false
                }
            ]
        });

        this.showARModal(modal);

        // Wygeneruj QR code po pokazaniu modala
        setTimeout(() => {
            this.generateQRCodeInModal(currentUrl);
        }, 100);
    },

    /**
    * Tworzy element AR modal (w stylu preview3d_ar)
    */
    createARModalElement(title, options) {
        const modal = document.createElement('div');
        modal.className = 'ar-modal-overlay';

        const qrHtml = options.qrUrl ? '<div class="ar-qr-container"><div class="ar-qr-code" id="arQrCode"></div><div class="ar-qr-url" id="arQrUrl"></div></div>' : '';

        const buttonsHtml = options.buttons ? options.buttons.map(btn =>
            `<button class="ar-modal-btn ${btn.primary ? 'primary' : ''}" data-action="${btn.text}">${btn.text}</button>`
        ).join('') : '';

        modal.innerHTML = `
        <div class="ar-modal-content">
            <div class="ar-modal-header">
                <div class="ar-modal-icon">${options.icon}</div>
                <h2 class="ar-modal-title">${title}</h2>
            </div>
            <div class="ar-modal-body">
                <div class="ar-modal-message" style="white-space: pre-line;">${options.message}</div>
                ${qrHtml}
            </div>
            <div class="ar-modal-footer">
                ${buttonsHtml}
            </div>
        </div>
    `;

        // Event listenery dla przycisków
        if (options.buttons) {
            options.buttons.forEach(btn => {
                const btnElement = modal.querySelector(`[data-action="${btn.text}"]`);
                if (btnElement) {
                    btnElement.addEventListener('click', btn.action);
                }
            });
        }

        return modal;
    },

    /**
     * Pokazuje AR modal
     */
    showARModal(modal) {
        this.closeARModal(); // Zamknij poprzedni jeśli istnieje
        modal.id = 'ar-modal';
        document.body.appendChild(modal);

        // ESC key handler
        this._escHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeARModal();
            }
        };
        document.addEventListener('keydown', this._escHandler);

        // Click outside handler
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeARModal();
            }
        });
    },

    /**
 * Otwiera nową kartę z Quote Viewer 3D/AR (zamiast modal iframe)
 * @param {number} productIndex - Indeks produktu
 */
    open3DViewer(productIndex) {
        console.log('[Client3D] Otwieranie Quote Viewer 3D/AR dla produktu:', productIndex);

        // Walidacja
        if (!window.QUOTE_TOKEN) {
            console.error('[Client3D] Brak tokenu wyceny');
            utils.showAlert('Błąd: Brak tokenu zabezpieczającego', 'error');
            return;
        }

        if (!globalState.quoteData || !globalState.quoteData.items) {
            console.error('[Client3D] Brak danych wyceny');
            utils.showAlert('Błąd: Brak danych wyceny', 'error');
            return;
        }

        // Sprawdź czy są produkty w wycenie
        const productItems = globalState.quoteData.items.filter(item =>
            item.product_index === productIndex
        );

        if (productItems.length === 0) {
            console.error('[Client3D] Brak produktów dla indeksu:', productIndex);
            utils.showAlert('Błąd: Nie znaleziono produktów w wycenie', 'error');
            return;
        }

        try {
            // URL nowego viewer'a z tokenem (tak samo jak w modalu quotes)
            const viewerUrl = `/preview3d-ar/${window.QUOTE_TOKEN}`;

            // Parametry okna - takie same jak w modalu quotes
            const windowFeatures = [
                'width=1600',
                'height=1000',
                'scrollbars=yes',
                'resizable=yes',
                'menubar=no',
                'toolbar=no',
                'location=no',
                'status=no',
                'left=' + Math.max(0, (screen.width - 1600) / 2),
                'top=' + Math.max(0, (screen.height - 1000) / 2)
            ].join(',');

            console.log('[Client3D] Otwieranie URL:', viewerUrl);

            // Otwórz nową kartę/okno
            const viewer3DWindow = window.open(viewerUrl, 'QuoteViewer3D_' + window.QUOTE_TOKEN, windowFeatures);

            if (!viewer3DWindow) {
                // Fallback - spróbuj otworzyć w nowej karcie
                window.open(viewerUrl, '_blank');
                utils.showAlert('Quote Viewer 3D/AR został otwarty w nowej karcie (sprawdź ustawienia blokady popup)', 'info');
            } else {
                console.log('[Client3D] Quote Viewer 3D/AR otwarty pomyślnie');

                // Spróbuj ustawić tytuł okna
                try {
                    viewer3DWindow.addEventListener('load', function () {
                        if (viewer3DWindow.document) {
                            viewer3DWindow.document.title = `${window.QUOTE_NUMBER} - Podgląd 3D/AR`;
                        }
                    });
                } catch (e) {
                    // Ignore cross-origin errors
                }
            }

        } catch (error) {
            console.error('[Client3D] Błąd uruchamiania Quote Viewer:', error);
            utils.showAlert('Błąd uruchamiania Quote Viewer 3D/AR', 'error');
        }
    },

    /**
     * Zamyka AR modal
     */
    closeARModal() {
        const modal = document.getElementById('ar-modal');
        if (modal) {
            modal.remove();
            if (this._escHandler) {
                document.removeEventListener('keydown', this._escHandler);
                this._escHandler = null;
            }
        }
    },

    /**
     * Generuje QR code w modal
     */
    generateQRCodeInModal(url) {
        const qrContainer = document.getElementById('arQrCode');
        const urlDisplay = document.getElementById('arQrUrl');

        if (qrContainer && urlDisplay) {
            // Wyczyść poprzedni QR code
            qrContainer.innerHTML = '';

            // Wygeneruj nowy QR code
            new QRCode(qrContainer, {
                text: url,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });

            // Pokaż URL
            urlDisplay.textContent = url;

            console.log('QR code generated in AR modal');
        }
    },

    /**
     * Pokazuje modal akceptacji
     */
    showAcceptModal() {
        if (globalState.isQuoteAccepted) return;

        const modal = document.getElementById('acceptModal');
        if (modal) {
            modal.classList.add('active');
        }
    },

    /**
     * Obsługa formularza akceptacji
     * @param {Event} event - Event formularza
     */
    async handleAcceptSubmit(event) {
        event.preventDefault();

        // Pobierz dane z formularza
        const email = document.getElementById('acceptEmail').value;
        const phone = document.getElementById('acceptPhone').value;
        const comments = document.getElementById('acceptComments').value;
        const terms = document.getElementById('acceptTerms').checked;

        // Walidacja
        let hasErrors = false;

        if (!email || !email.includes('@')) {
            document.getElementById('emailError').textContent = 'Podaj prawidłowy adres email';
            document.getElementById('emailError').classList.remove('hidden');
            hasErrors = true;
        }

        if (!phone || phone.length < 9) {
            document.getElementById('phoneError').textContent = 'Podaj prawidłowy numer telefonu';
            document.getElementById('phoneError').classList.remove('hidden');
            hasErrors = true;
        }

        if (!terms) {
            document.getElementById('termsError').textContent = 'Musisz zaakceptować warunki';
            document.getElementById('termsError').classList.remove('hidden');
            hasErrors = true;
        }

        if (hasErrors) return;

        try {
            utils.setLoading(true);

            // Wyślij dane do API
            const response = await api.acceptQuote(window.QUOTE_TOKEN, {
                email_or_phone: email,
                phone: phone,
                comments: comments
            });

            // Sukces - odśwież stronę
            utils.showAlert('Wycena została zaakceptowana!', 'success');
            setTimeout(() => {
                window.location.reload();
            }, 1500);

        } catch (error) {
            console.error('Błąd akceptacji:', error);
            utils.showAlert(error.message || 'Błąd podczas akceptacji wyceny', 'error');
        } finally {
            utils.setLoading(false);
        }
    },

    /**
     * Zamyka modal
     * @param {string} modalId - ID modala
     */
    closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
        }

        // Wyczyść błędy formularza
        document.querySelectorAll('.form-error').forEach(el => {
            el.classList.add('hidden');
            el.textContent = '';
        });
    },

    /**
     * Przełącza widoczność podsumowania mobilnego
     */
    toggleSummary() {
        const details = document.getElementById('bottomBarDetails');
        const chevron = document.getElementById('summaryChevron');

        if (details && chevron) {
            details.classList.toggle('open');
            chevron.classList.toggle('open');
        }
    }
};

// ===================================
// INITIALIZATION
// ===================================
const init = {
    /**
     * Ładuje dane wyceny
     */
    async loadQuoteData() {
        try {
            utils.setLoading(true);

            const token = window.QUOTE_TOKEN;
            if (!token) {
                throw new Error('Brak tokenu wyceny');
            }

            // Pobierz dane z API
            globalState.quoteData = await api.getQuoteData(token);
            console.log('Załadowano dane wyceny:', globalState.quoteData);

            // Ustaw domyślnie wybrane warianty
            if (globalState.quoteData.items) {
                globalState.quoteData.items.forEach(item => {
                    if (item.is_selected) {
                        globalState.selectedVariants.set(item.product_index, item.id);
                    }
                });
            }

            // Sprawdź czy wycena jest zaakceptowana
            globalState.isQuoteAccepted = !globalState.quoteData.is_client_editable;

            // Renderuj UI
            this.renderAll();

        } catch (error) {
            console.error('Błąd ładowania danych:', error);
            utils.showAlert('Błąd ładowania danych wyceny', 'error');
        } finally {
            utils.setLoading(false);
        }
    },

    /**
     * Renderuje wszystkie elementy UI
     */
    renderAll() {
        render.productTabs();
        render.productSections();
        render.comparison();
        render.mobileSummary();
        render.desktopSummary();
        render.desktopComparison();

        // Pokaż/ukryj elementy w zależności od stanu
        if (globalState.isQuoteAccepted) {
            this.disableInteractions();
        }
    },

    /**
     * Wyłącza interakcje dla zaakceptowanej wyceny
     */
    disableInteractions() {
        // Wyłącz przycisk akceptacji
        const acceptBtn = document.querySelector('.btn-accept');
        if (acceptBtn) {
            acceptBtn.disabled = true;
            acceptBtn.textContent = 'Wycena zaakceptowana';
        }

        // Dodaj klasę do body
        document.body.classList.add('quote-accepted');
    },

    /**
     * Ustawia event listenery
     */
    setupEventListeners() {
        // Product selection (mobile)
        const productSelect = document.getElementById('productSelect');
        if (productSelect) {
            productSelect.addEventListener('change', (e) => {
                handlers.switchProduct(parseInt(e.target.value));
            });
        }

        // Close modals on outside click
        document.querySelectorAll('.modal-overlay').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    handlers.closeModal(modal.id);
                }
            });
        });

        // Close 3D viewer on click outside
        const viewerModal = document.getElementById('viewerModal');
        if (viewerModal) {
            viewerModal.addEventListener('click', (e) => {
                if (e.target === viewerModal) {
                    handlers.close3DViewer();
                }
            });
        }

        // DODANE: Close QR modal on click outside
        const qrModal = document.getElementById('qrModal');
        if (qrModal) {
            qrModal.addEventListener('click', (e) => {
                if (e.target === qrModal) {
                    handlers.closeModal('qrModal');
                }
            });
        }

        // DODANE: Close QR modal on ESC key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const activeModal = document.querySelector('.modal-overlay.active');
                if (activeModal) {
                    handlers.closeModal(activeModal.id);
                }
            }
        });

        // Expose handlers to global scope for onclick attributes
        window.handlers = handlers;
        window.toggleSummary = handlers.toggleSummary;
        window.showAcceptModal = handlers.showAcceptModal;
        window.closeModal = handlers.closeModal;
        window.handleAcceptSubmit = handlers.handleAcceptSubmit;
    }
};

// ===================================
// MAIN ENTRY POINT
// ===================================
document.addEventListener('DOMContentLoaded', async () => {
    console.log('Client Quote JS - Initializing...');

    try {
        // Ustaw event listenery
        init.setupEventListeners();

        // Załaduj dane wyceny
        await init.loadQuoteData();

        console.log('Client Quote JS - Ready');

    } catch (error) {
        console.error('Błąd inicjalizacji:', error);
        utils.showAlert('Błąd ładowania strony', 'error');
    }
});

// ===================================
// PUBLIC API (dla debugowania)
// ===================================
window.clientQuote = {
    state: globalState,
    api: api,
    utils: utils,
    render: render,
    handlers: handlers,
    init: init
};