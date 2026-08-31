// =============================================================================
// PUBLICZNA STRONA WYCENY  /quotes/c/<token>  —  warstwa renderu
//
// Strona zaczyna się od razu od wyboru pozycji i wariantów — nagłówek pozycji
// (zdjęcie-podkład, nazwa wariantu, wymiary) został usunięty. Warianty są
// kafelkami w poziomym pasku ze scroll-snap, a pod nimi stoją dwie osobne
// sekcje: kształt + specyfikacja oraz obróbka krawędzi. Wymiary i materiał
// przeniosły się do karty specyfikacji, bo była to jedyna droga, żeby ich
// nie stracić przy wycenie z jedną pozycją (przyciski pozycji chowa wtedy CSS).
//
// UMOWA CENOWA (całe liczenie kwot siedzi w obiekcie `money`):
//   * item.final_price_*   — CAŁKOWITA cena materiału pozycji (jednostkowa × ilość),
//   * item.unit_price_*    — cena materiału za sztukę (używana tylko jako awaryjna),
//   * finishing_price_*    — CAŁKOWITY koszt wykończenia pozycji,
//   * edges_price_*        — CAŁKOWITY koszt obróbki krawędzi pozycji.
//   Render operuje więc WYŁĄCZNIE kwotami w skali całej pozycji — nigdzie nie
//   miesza ich z cenami jednostkowymi, więc nigdzie nie dzieli przez ilość sztuk.
//   Wykończenie i obróbka krawędzi to od teraz DWA OSOBNE wiersze podsumowania;
//   wcześniej krawędzie były doliczane do wykończenia w pięciu miejscach tego
//   pliku, każde z własną kopią wzoru.
//
// SUMA CAŁKOWITA: dopóki wybór klienta jest zgodny z tym, co ma serwer,
//   bierzemy `costs` z API bez żadnych przeliczeń (dokładnie ta sama kwota,
//   co przed redesignem). Podgląd liczony lokalnie włącza się dopiero po
//   kliknięciu innego wariantu — i wtedy powtarza arytmetykę serwera
//   (calculate_costs_with_vat) 1:1.
// =============================================================================

// ===================================
// STAN GLOBALNY
// ===================================
const globalState = {
    quoteData: null,
    selectedVariants: new Map(),
    currentProductIndex: 1,
    isQuoteAccepted: window.IS_ACCEPTED || false,
    // Czy klient może z tej strony ZAMÓWIĆ. To nie to samo co isQuoteAccepted:
    // wycena zaakceptowana wciąż czeka na zamówienie. Wylicza to serwer
    // (routers.client_quote_view), bo tylko on widzi base_linker_order_id.
    mozeZamawiac: window.MOZNA_ZAMOWIC === true,
    isLoading: false,
    hasUnsavedChanges: false
};

// Stawka VAT — ta sama, którą stosuje calculate_costs_with_vat na serwerze
const VAT_RATE = 0.23;

// Polskie nazwy typów obróbki krawędzi (jak w offer_pdf.html)
const EDGE_TYPE_PL = { round: 'Zaokrąglenie', chamfer: 'Fazowanie' };

// ===================================
// API
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
     */
    async getQuoteData(token) {
        return this.call(`/quotes/api/client/quote/${token}`);
    },

    /**
     * Zapisuje wybrany wariant
     * @param {string} token - Token publiczny wyceny
     * @param {number} itemId - ID wybranego wariantu
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
     */
    async acceptQuote(token, data) {
        return this.call(`/quotes/api/client/quote/${token}/accept`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
};

// ===================================
// NARZĘDZIA
// ===================================
const utils = {
    /**
     * Escapuje tekst wstawiany do HTML. Render składa markup ze stringów,
     * więc KAŻDA wartość z API musi tędy przejść — wyjątkiem są tylko
     * shape_svg i edges_svg, które serwer oczyszcza whitelistą (sanitize_svg).
     * @param {*} value
     * @returns {string}
     */
    esc(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    /**
     * Kwota bez waluty: "1 234,56"
     */
    amount(value) {
        const number = parseFloat(value);
        return new Intl.NumberFormat('pl-PL', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(Number.isFinite(number) ? number : 0);
    },

    /**
     * Kwota z walutą: "1 234,56 zł"
     */
    formatCurrency(value) {
        const number = parseFloat(value);
        return new Intl.NumberFormat('pl-PL', {
            style: 'currency',
            currency: 'PLN'
        }).format(Number.isFinite(number) ? number : 0);
    },

    /**
     * Liczba bez zer na końcu: 109 → "109", 95.5 → "95,5"
     */
    number(value, maxFractionDigits = 2) {
        const number = parseFloat(value);
        return new Intl.NumberFormat('pl-PL', {
            maximumFractionDigits: maxFractionDigits
        }).format(Number.isFinite(number) ? number : 0);
    },

    /**
     * Polska odmiana przez liczbę: plural(5, 'wariant', 'warianty', 'wariantów')
     */
    plural(count, one, few, many) {
        const abs = Math.abs(Math.trunc(count || 0));
        if (abs === 1) return one;
        const last = abs % 10;
        const lastTwo = abs % 100;
        if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return few;
        return many;
    },

    /**
     * Tłumaczy kod wariantu na czytelną nazwę
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
     * Ścieżka do zdjęcia wariantu. Podwójne "quotes" jest poprawne —
     * blueprint quotes ma prefiks /quotes i własny katalog static.
     */
    variantImage(code) {
        return `/quotes/quotes/static/img/${encodeURIComponent(code || '')}.jpg`;
    },

    /**
     * Zdjęcie na podkład — osobny, panoramiczny kadr 1600x760. Kafelkowe
     * 700x700 rozmywałoby się na pasie 1425 px, a ładowanie hero we
     * wszystkich ośmiu kafelkach byłoby marnotrawstwem.
     */
    variantImageHero(code) {
        return `/quotes/quotes/static/img/${encodeURIComponent(code || '')}-hero.jpg`;
    },


    isMobile() {
        return window.innerWidth <= 768;
    },

    setLoading(show) {
        const loadingEl = document.getElementById('loadingOverlay');
        if (loadingEl) {
            loadingEl.classList.toggle('hidden', !show);
        }
        globalState.isLoading = show;
    },

    /**
     * Komunikat dla klienta. Błędów NIE wolno gubić po cichu — strona wyceny
     * nie ma własnego systemu toastów, a niewidoczna porażka zapisu wygląda
     * jak martwy przycisk.
     */
    showAlert(message, type = 'info') {
        console.log(`[Alert ${type}]:`, message);
        if (type === 'error' && typeof window.alert === 'function') {
            window.alert(message);
        }
    },

};

// ===================================
// KWOTY — jedyne miejsce, w którym liczymy pieniądze
// ===================================
const money = {
    num(value) {
        const number = parseFloat(value);
        return Number.isFinite(number) ? number : 0;
    },

    round2(value) {
        return Math.round((value + Number.EPSILON) * 100) / 100;
    },

    /**
     * Wpis wykończenia/krawędzi dla danej pozycji
     */
    finishingFor(productIndex) {
        const list = globalState.quoteData && globalState.quoteData.finishing;
        if (!Array.isArray(list)) return null;
        return list.find(entry => entry.product_index === productIndex) || null;
    },

    /**
     * Cena MATERIAŁU dla całej pozycji (final_price_* jest już z ilością sztuk).
     *
     * Brutto liczymy z netto tą samą stawką, którą serwer stosuje do sumy
     * (calculate_costs_with_vat). Gdyby brać brutto wprost z bazy — a tam jest
     * ono zaokrąglone na cenie JEDNOSTKOWEJ i dopiero potem mnożone przez ilość —
     * różnica na kafelku rozjeżdżałaby się o kilka groszy ze zmianą kwoty
     * "Do zapłaty", a to klient widzi na jednym ekranie.
     * @returns {{netto: number, brutto: number}}
     */
    material(item) {
        if (!item) return { netto: 0, brutto: 0 };
        const quantity = item.quantity || 1;
        const netto = this.num(item.final_price_netto) || this.num(item.unit_price_netto) * quantity;
        if (netto > 0) {
            return { netto: netto, brutto: this.round2(netto * (1 + VAT_RATE)) };
        }
        // wariant bez ceny netto = niedostępny; brutto z bazy tylko po to,
        // żeby nie uznać za niedostępny czegoś, co cenę jednak ma
        return {
            netto: netto,
            brutto: this.num(item.final_price_brutto) || this.num(item.unit_price_brutto) * quantity
        };
    },

    /**
     * SAMO wykończenie pozycji (bez krawędzi)
     */
    finishingOnly(productIndex) {
        const finishing = this.finishingFor(productIndex);
        return {
            netto: this.num(finishing && finishing.finishing_price_netto),
            brutto: this.num(finishing && finishing.finishing_price_brutto)
        };
    },

    /**
     * SAMA obróbka krawędzi pozycji (bez wykończenia)
     */
    edgesOnly(productIndex) {
        const finishing = this.finishingFor(productIndex);
        return {
            netto: this.num(finishing && finishing.edges_price_netto),
            brutto: this.num(finishing && finishing.edges_price_brutto)
        };
    },

    /**
     * Suma wykończenia i suma krawędzi po wszystkich pozycjach wyceny.
     * Serwer trzyma je razem w costs.finishing — tu rozdzielamy je na dwa
     * wiersze podsumowania, nie ruszając sumy: finishing + edges === costs.finishing.
     */
    extrasTotals() {
        const list = (globalState.quoteData && globalState.quoteData.finishing) || [];
        let finishingNetto = 0;
        let edgesNetto = 0;
        list.forEach(entry => {
            finishingNetto += this.num(entry.finishing_price_netto);
            edgesNetto += this.num(entry.edges_price_netto);
        });
        return {
            finishingNetto: this.round2(finishingNetto),
            edgesNetto: this.round2(edgesNetto),
            // brutto liczymy tak jak serwer: netto * (1 + VAT), zaokrąglone na końcu
            finishingBrutto: this.round2(finishingNetto * (1 + VAT_RATE)),
            edgesBrutto: this.round2(edgesNetto * (1 + VAT_RATE)),
            // odpowiednik costs.finishing.netto z serwera (round(sum(fin + edges), 2))
            totalNetto: this.round2(finishingNetto + edgesNetto)
        };
    },

    /**
     * Powtórzenie serwerowego calculate_costs_with_vat dla LOKALNEGO wyboru
     * wariantów. Używane wyłącznie jako podgląd po kliknięciu kafelka —
     * dopóki wybór jest zapisany, podsumowanie bierze kwoty prosto z API.
     */
    computeLocalCosts() {
        const products = render.products();
        let productsNetto = 0;
        products.forEach(product => {
            const item = render.selectedItem(product);
            productsNetto += this.material(item).netto;
        });
        productsNetto = this.round2(productsNetto);

        const extras = this.extrasTotals();
        const finishingNetto = extras.totalNetto;
        const shippingBrutto = this.num(globalState.quoteData && globalState.quoteData.shipping_cost_brutto);

        const productsVat = productsNetto * VAT_RATE;
        const finishingVat = finishingNetto * VAT_RATE;
        const shippingNetto = shippingBrutto / (1 + VAT_RATE);
        const shippingVat = shippingBrutto - shippingNetto;

        const totalNetto = productsNetto + finishingNetto + shippingNetto;
        const totalVat = productsVat + finishingVat + shippingVat;

        return {
            products: {
                netto: this.round2(productsNetto),
                vat: this.round2(productsVat),
                brutto: this.round2(productsNetto + productsVat)
            },
            finishing: {
                netto: this.round2(finishingNetto),
                vat: this.round2(finishingVat),
                brutto: this.round2(finishingNetto + finishingVat)
            },
            shipping: {
                netto: this.round2(shippingNetto),
                vat: this.round2(shippingVat),
                brutto: this.round2(shippingBrutto)
            },
            total: {
                netto: this.round2(totalNetto),
                vat: this.round2(totalVat),
                brutto: this.round2(totalNetto + totalVat)
            }
        };
    },

    /**
     * Kwoty do wyświetlenia. Bez niezapisanych zmian — dokładnie to, co
     * policzył serwer. Z niezapisanym wyborem — podgląd lokalny.
     */
    view() {
        if (!globalState.hasUnsavedChanges) {
            return (globalState.quoteData && globalState.quoteData.costs) || {};
        }
        return this.computeLocalCosts();
    },

    /**
     * Bezpieczny odczyt zagnieżdżonej kwoty (costs.total.brutto itp.)
     */
    pick(costs, group, kind) {
        const section = costs && costs[group];
        return this.num(section && section[kind]);
    }
};

// ===================================
// RENDER
// ===================================
const render = {

    // -------------------------------------------------------------------------
    // DANE POMOCNICZE
    // -------------------------------------------------------------------------

    /**
     * Pozycje wyceny pogrupowane po product_index
     */
    products() {
        if (!globalState.quoteData || !Array.isArray(globalState.quoteData.items)) return [];

        const groups = new Map();
        globalState.quoteData.items.forEach(item => {
            if (!groups.has(item.product_index)) {
                const finishing = money.finishingFor(item.product_index);
                groups.set(item.product_index, {
                    index: item.product_index,
                    length: item.length_cm,
                    width: item.width_cm,
                    thickness: item.thickness_cm,
                    quantity: (finishing && finishing.quantity) || item.quantity || 1,
                    finishing: finishing,
                    variants: []
                });
            }
            groups.get(item.product_index).variants.push(item);
        });

        return Array.from(groups.values()).sort((a, b) => a.index - b.index);
    },

    productAt(productIndex) {
        return this.products().find(product => product.index === productIndex) || null;
    },

    /**
     * Warianty widoczne dla klienta
     */
    visibleVariants(product) {
        if (!product) return [];
        return product.variants.filter(variant => variant.show_on_client_page !== false);
    },

    /**
     * Wariant wybrany dla pozycji (lokalny wybór klienta ma pierwszeństwo)
     */
    selectedItem(product) {
        if (!product) return null;
        const variants = this.visibleVariants(product);
        const selectedId = globalState.selectedVariants.get(product.index);
        return variants.find(variant => variant.id === selectedId)
            || variants.find(variant => variant.is_selected)
            || variants.find(variant => money.material(variant).brutto > 0)
            || variants[0]
            || null;
    },

    /**
     * Powierzchnia jednej sztuki w m²
     */
    areaM2(item) {
        if (!item) return 0;
        const length = money.num(item.length_cm);
        const width = money.num(item.width_cm);
        if (length <= 0 || width <= 0) return 0;
        return (length * width) / 10000;
    },

    /**
     * Opis wykończenia pozycji
     */
    formatFinishing(finishing) {
        if (!finishing || !finishing.finishing_type || finishing.finishing_type === 'Brak') {
            return 'Brak wykończenia';
        }
        return [
            finishing.finishing_type,
            finishing.finishing_variant,
            finishing.finishing_gloss_level,
            finishing.finishing_color
        ].filter(part => part && part !== 'Brak').join(' · ');
    },

    /**
     * Powód niedostępności wariantu. Cena 0 znaczy "nie ma takiej płyty
     * w tej grubości" — pokazanie "0,00 zł" i różnicy "−952,34 zł"
     * wyglądało jak awaria systemu.
     */
    unavailableReason(item) {
        const thicknessMm = Math.round(money.num(item && item.thickness_cm) * 10);
        if (thicknessMm > 0) return `niedostępna w ${thicknessMm} mm`;
        return 'niedostępna w tym wymiarze';
    },

    // -------------------------------------------------------------------------
    // GÓRA STRONY
    // -------------------------------------------------------------------------



    // -------------------------------------------------------------------------
    // PRZEŁĄCZNIK POZYCJI
    // -------------------------------------------------------------------------

    /**
     * Podkład góry strony — zdjęcie WYBRANEGO wariantu. Nowy obraz wgrywamy
     * do warstwy wierzchniej i wypuszczamy dopiero PO jego wczytaniu, żeby
     * nie przenikać do pustego tła; po przejściu ląduje na warstwie bazowej,
     * a wierzchnia wraca do zera z wyłączoną animacją.
     */
    backdrop() {
        const base = document.getElementById('stageShot');
        const next = document.getElementById('stageShotNext');
        if (!base) return;

        const products = this.products();
        if (products.length === 0) return;
        const product = products.find(p => p.index === globalState.currentProductIndex) || products[0];
        const item = this.selectedItem(product);
        if (!item) return;

        const css = `url('${utils.variantImageHero(item.variant_code)}')`;
        if (!next || !base.style.backgroundImage) { base.style.backgroundImage = css; return; }
        if (base.style.backgroundImage === css) return;

        const zamien = () => {
            base.style.backgroundImage = css;
            next.style.transition = 'none';
            next.classList.remove('on');
            void next.offsetWidth;
            next.style.transition = '';
        };

        const img = new Image();
        img.onload = () => {
            next.style.backgroundImage = css;
            requestAnimationFrame(() => next.classList.add('on'));
            window.setTimeout(zamien, 520);
        };
        img.onerror = () => { base.style.backgroundImage = css; };
        img.src = utils.variantImageHero(item.variant_code);
    },

    productTabs() {
        const buttonsContainer = document.getElementById('productButtons');
        const selectElement = document.getElementById('productSelect');
        if (!buttonsContainer || !selectElement) return;

        const products = this.products();

        buttonsContainer.innerHTML = products.map((product, position) => {
            const active = product.index === globalState.currentProductIndex ? ' active' : '';
            const item = this.selectedItem(product);
            // Pełne trzy wymiary — grubość jest tym, co odróżnia dwie pozycje
            // o tym samym obrysie, więc jej brak czynił przycisk bezużytecznym
            const dimensions = item
                ? `${utils.number(item.length_cm)} × ${utils.number(item.width_cm)} × ${utils.number(item.thickness_cm)} cm`
                : `${product.quantity} szt.`;
            return `
                <button type="button" class="product-button${active}" data-product-index="${product.index}">
                    <div class="product-button-title">Produkt ${position + 1}</div>
                    <div class="product-button-dimensions">${utils.esc(dimensions)}</div>
                </button>`;
        }).join('');

        selectElement.innerHTML = products.map((product, position) => {
            const selected = product.index === globalState.currentProductIndex ? ' selected' : '';
            return `<option value="${product.index}"${selected}>Produkt ${position + 1}</option>`;
        }).join('');
    },

    // -------------------------------------------------------------------------
    // SEKCJE POZYCJI
    // -------------------------------------------------------------------------

    productSections() {
        const container = document.getElementById('productSections');
        if (!container) return;

        const products = this.products();
        container.innerHTML = products.map(product => {
            const active = product.index === globalState.currentProductIndex ? ' active' : '';
            return `
                <div class="product-section${active}" id="product-${product.index}">
                    ${this.variantsSection(product)}
                    ${this.shapeSection(product)}
                    ${this.edgesSection(product)}
                </div>`;
        }).join('');

        this.setupRails();
    },

    /**
     * Kontekst wspólny dla wszystkich kafelków jednej pozycji
     */
    tileContext(product) {
        const selected = this.selectedItem(product);
        const selectedPrice = money.material(selected);
        return {
            productIndex: product.index,
            selectedId: selected ? selected.id : null,
            // porównujemy tylko z wariantem, który MA cenę — inaczej różnica
            // względem niedostępnego wariantu byłaby bez sensu
            selectedBrutto: selectedPrice.brutto > 0 ? selectedPrice.brutto : null,
            interactive: !globalState.isQuoteAccepted
        };
    },

    /**
     * SEKCJA 1 — warianty materiału jako kafelki
     */
    variantsSection(product) {
        const variants = this.visibleVariants(product);
        if (variants.length === 0) return '';

        const context = this.tileContext(product);
        const optionsLabel = `${variants.length} ${utils.plural(variants.length, 'opcja', 'opcje', 'opcji')}`;
        const hintParts = [optionsLabel];
        if (product.quantity > 1) {
            hintParts.push(`cena za ${product.quantity} szt.`);
        } else if (context.interactive) {
            hintParts.push('dotknij, aby wybrać');
        }

        const tiles = variants.map(item => this.tileMarkup(item, context)).join('');
        const railhint = variants.length > 1
            ? `<div class="railhint">
                   <span data-rail-text></span>
                   <span class="raildots" data-rail-dots></span>
               </div>`
            : '';

        // 3D i AR siedzą w nagłówku wariantów, bo to jedyny nagłówek, który
        // klient ogląda przy każdej pozycji. Podpowiedź o liczbie opcji
        // i przeliczniku sztuk schodzi pod nagłówek.
        return `
            <div class="sect">
                <div class="sect-hd sect-hd--actions">
                    <div class="sect-hd-txt">
                        <h3>Wariant materiału</h3>
                        <p class="sect-note">${utils.esc(hintParts.join(' · '))}</p>
                    </div>
                    <div class="product-actions">
                        <button type="button" class="btn-3d" data-action="view-3d" data-product-index="${product.index}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21 7.5 12 12m9-4.5v9L12 21m9-13.5L12 3 3 7.5m9 4.5v9m0-9L3 7.5m0 0v9L12 21"/></svg>
                            Podgląd 3D
                        </button>
                        <button type="button" class="btn-ar" data-action="view-ar" data-product-index="${product.index}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3 8V5.5A1.5 1.5 0 0 1 4.5 4H7m10 0h2.5A1.5 1.5 0 0 1 21 5.5V8m0 8v2.5a1.5 1.5 0 0 1-1.5 1.5H17M7 20H4.5A1.5 1.5 0 0 1 3 18.5V16"/><rect x="8" y="9" width="8" height="6" rx="1"/></svg>
                            Zobacz u siebie
                        </button>
                    </div>
                </div>
                <div class="tiles rail" data-rail data-product-index="${product.index}">${tiles}</div>
                ${railhint}
            </div>`;
    },

    tileMarkup(item, context) {
        const price = money.material(item);
        const available = price.brutto > 0;
        const isSelected = item.id === context.selectedId;

        const classes = ['tile'];
        if (isSelected) classes.push('sel');
        if (!available) classes.push('off');

        // niedostępnego wariantu nie da się wybrać; przy zaakceptowanej wycenie
        // nie da się wybrać żadnego
        const disabled = (!available || !context.interactive) ? ' disabled' : '';

        return `
            <button type="button" class="${classes.join(' ')}"${disabled}
                    data-item-id="${item.id}" data-product-index="${context.productIndex}"
                    aria-pressed="${isSelected ? 'true' : 'false'}">
                ${this.tileInner(item, context)}
            </button>`;
    },

    /**
     * Wnętrze kafelka — osobno, bo przy zmianie wyboru podmieniamy tylko je
     * (przebudowa całego paska zresetowałaby jego przewinięcie).
     */
    tileInner(item, context) {
        const price = money.material(item);
        const available = price.brutto > 0;
        const isSelected = item.id === context.selectedId;
        const name = utils.translateVariantCode(item.variant_code);
        const photo = `<div class="ph" style="background-image:url('${utils.variantImage(item.variant_code)}')"></div>`;
        const flag = isSelected ? '<div class="flag">✓ wybrany</div>' : '';

        if (!available) {
            return `${photo}
                <div class="tb">
                    <div class="tn">${utils.esc(name)}</div>
                    <div class="tp">${utils.esc(this.unavailableReason(item))}</div>
                </div>`;
        }

        return `${photo}${flag}
            <div class="tb">
                <div class="tn">${utils.esc(name)}</div>
                <div class="tp">${utils.esc(utils.formatCurrency(price.brutto))}</div>
                <div class="tnet">${utils.esc(utils.amount(price.netto))} netto</div>
                ${this.chipMarkup(price.brutto, isSelected, context)}
            </div>`;
    },

    /**
     * Chip z różnicą względem wybranego wariantu (na wybranym go nie ma)
     */
    chipMarkup(brutto, isSelected, context) {
        if (isSelected || context.selectedBrutto === null) return '';

        const difference = money.round2(brutto - context.selectedBrutto);
        if (Math.abs(difference) < 0.005) {
            return '<div class="chip eq">bez różnicy</div>';
        }
        const cssClass = difference < 0 ? 'dn' : 'up';
        // U+2212 (minus) zamiast dywizu — jak w makiecie
        const sign = difference < 0 ? '−' : '+';
        return `<div class="chip ${cssClass}">${sign}${utils.esc(utils.formatCurrency(Math.abs(difference)))}</div>`;
    },

    /**
     * SEKCJA 2 — kształt i specyfikacja.
     * Warunek pokazania rysunku kształtu jest NIEZALEŻNY od obróbki krawędzi:
     * wcześniej cały blok wisiał na niepustym edges_config, więc produkt
     * z ciekawym kształtem, ale bez obróbki krawędzi nie pokazywał nic.
     */
    shapeSection(product) {
        const finishing = product.finishing;
        const item = this.selectedItem(product);
        const shapeSvg = (finishing && finishing.shape_svg) || '';

        const rows = [];
        // Wymiary i wybrany materiał stały wcześniej w nagłówku strony.
        // Po jego usunięciu to jedyne miejsce, w którym klient je widzi —
        // przyciski pozycji chowają się, gdy wycena ma tylko jeden produkt.
        if (item) {
            rows.push(['Wymiary', `${utils.number(item.length_cm)} × ${utils.number(item.width_cm)} × ${utils.number(item.thickness_cm)} cm`]);
            rows.push(['Materiał', utils.translateVariantCode(item.variant_code)]);
        }
        rows.push(['Wykończenie', this.formatFinishing(finishing)]);
        if (finishing && typeof finishing.cut_to_size === 'boolean') {
            rows.push(['Docięcie do wymiaru', finishing.cut_to_size ? 'Tak' : 'Nie']);
        }
        // Osobnego wiersza "Grubość" już nie ma — trzeci wymiar stoi
        // w "Wymiary", a powtarzanie go w milimetrach tylko myliło.
        const area = this.areaM2(item);
        if (area > 0) rows.push(['Powierzchnia', `${utils.number(area, 2)} m²`]);
        rows.push(['Ilość', `${product.quantity} szt.`]);

        const rowsHtml = rows.map(([label, value]) => `
            <div><dt>${utils.esc(label)}</dt><dd>${utils.esc(value)}</dd></div>`).join('');

        // shape_svg jest oczyszczony na serwerze (sanitize_svg, whitelist tagów),
        // dlatego jako jedyny obok edges_svg wchodzi bez escapowania
        const drawing = shapeSvg ? `<div class="draw">${shapeSvg}</div>` : '';
        const bodyClass = shapeSvg ? 'sect-bd shapegrid' : 'sect-bd';
        const heading = shapeSvg ? 'Kształt i specyfikacja' : 'Specyfikacja';

        return `
            <div class="sect">
                <div class="sect-hd">
                    <h3>${heading}</h3>
                </div>
                <div class="${bodyClass}">
                    ${drawing}
                    <dl class="rows">${rowsHtml}</dl>
                </div>
            </div>`;
    },

    /**
     * SEKCJA 3 — obróbka krawędzi.
     * Etykiety krawędzi bierzemy z pola "label", które backend dopisuje do
     * każdego wpisu edges_config (human_edge_label). Lokalna mapa liter znała
     * tylko prostokąt A-H i obwód KG/KD, więc dla kształtów nieregularnych
     * (G1/D1/P1) i krawędzi wycięć (H1.G2) lista renderowała się PUSTA.
     * Gdy edges_svg jest puste, NIE generujemy zastępczej izometrii —
     * rysowanie prostopadłościanu dla koła wprowadzało klienta w błąd.
     */
    edgesSection(product) {
        const finishing = product.finishing;
        const config = finishing && finishing.edges_config;
        if (!Array.isArray(config) || config.length === 0) return '';

        const edgesSvg = finishing.edges_svg || '';
        const isAdvanced = finishing.edges_mode === 'advanced';
        const countLabel = `${config.length} ${utils.plural(config.length, 'krawędź', 'krawędzie', 'krawędzi')}`;

        let headline;
        let detailLines;

        if (isAdvanced) {
            // Tryb mieszany: edges_r_value i edges_angle_value są NULL na poziomie
            // wyceny, promień siedzi per krawędź — grupujemy jak offer_pdf.html
            headline = `Obróbka mieszana — ${countLabel}`;
            detailLines = this.groupEdges(config).map(group => {
                const typeName = EDGE_TYPE_PL[group.type] || group.type || 'Obróbka';
                const radius = group.r !== null && group.r !== undefined ? ` R${utils.number(group.r)}` : '';
                const angle = (group.type === 'chamfer' && group.angle) ? ` ${utils.number(group.angle)}°` : '';
                return `${typeName}${radius}${angle} — ${group.labels.join(', ')}`;
            });
        } else {
            const first = config[0] || {};
            const type = finishing.edges_type || first.type || '';
            const typeName = EDGE_TYPE_PL[type] || 'Obróbka krawędzi';
            const rValue = finishing.edges_r_value !== null && finishing.edges_r_value !== undefined
                ? finishing.edges_r_value
                : first.r_value;
            const angleValue = finishing.edges_angle_value !== null && finishing.edges_angle_value !== undefined
                ? finishing.edges_angle_value
                : first.angle_value;

            const radius = (rValue !== null && rValue !== undefined) ? ` R${utils.number(rValue)} mm` : '';
            const angle = (type === 'chamfer' && angleValue) ? `, kąt ${utils.number(angleValue)}°` : '';
            headline = `${typeName}${radius}${angle} — ${countLabel}`;
            detailLines = [this.edgeLabels(config).join(', ')];
        }

        const details = detailLines
            .filter(line => line && line.length > 0)
            .map(line => `<span>${utils.esc(line)}</span>`)
            .join('');

        // edges_svg jest oczyszczony na serwerze (sanitize_svg)
        return `
            <div class="sect">
                <div class="sect-hd"><h3>Obróbka krawędzi</h3></div>
                <div class="sect-bd">
                    <div class="edge">
                        ${edgesSvg}
                        <div class="etxt">
                            <b>${utils.esc(headline)}</b>
                            ${details}
                        </div>
                    </div>
                </div>
            </div>`;
    },

    /**
     * Czytelne nazwy krawędzi, posortowane po oznaczeniu (G1, G3, G4...)
     */
    edgeLabels(config) {
        return config
            .slice()
            .sort((a, b) => String(a.letter || '').localeCompare(String(b.letter || ''), 'pl', { numeric: true }))
            .map(entry => entry.label || entry.letter || '')
            .filter(label => label.length > 0);
    },

    /**
     * Grupowanie krawędzi po (type, r_value, angle_value) — klucz i sortowanie
     * jak w offer_pdf.html, żeby PDF i strona mówiły to samo.
     */
    groupEdges(config) {
        const groups = new Map();
        config.forEach(entry => {
            const key = `${entry.type || ''}|${entry.r_value}|${entry.angle_value !== null && entry.angle_value !== undefined ? entry.angle_value : ''}`;
            if (!groups.has(key)) {
                groups.set(key, { key: key, type: entry.type, r: entry.r_value, angle: entry.angle_value, entries: [] });
            }
            groups.get(key).entries.push(entry);
        });

        return Array.from(groups.values())
            .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
            .map(group => ({
                type: group.type,
                r: group.r,
                angle: group.angle,
                labels: this.edgeLabels(group.entries)
            }));
    },

    /**
     * Informacja o niezapisanym wyborze — pokazywana POD podsumowaniem,
     * bo tam klient patrzy tuż przed akceptacją. Dopóki wisi, przycisk
     * akceptacji jest zablokowany: wysłanie wyceny z niezapisanym wyborem
     * zamówiłoby STARY wariant, a modal pokazywałby kwoty podglądu.
     */
    unsavedNotice() {
        const visibility = globalState.hasUnsavedChanges ? 'visible' : 'hidden';
        return `
            <div class="save-changes-section ${visibility}">
                <div class="save-changes-content">
                    <span class="save-changes-text">Masz niezapisany wybór wariantu — zapisz go, żeby móc zaakceptować wycenę.</span>
                    <button type="button" class="btn-save-changes" data-action="save-changes">Zapisz zmiany</button>
                </div>
            </div>`;
    },


    /**
     * Blokuje przyciski akceptacji, dopóki wybór nie jest zapisany.
     */
    syncAcceptButtons() {
        const zablokowane = globalState.hasUnsavedChanges || !globalState.mozeZamawiac;
        ['acceptQuoteBtnDesktop', 'acceptQuoteBtnMobile'].forEach(id => {
            const btn = document.getElementById(id);
            if (!btn) return;
            btn.disabled = zablokowane;
            btn.title = (globalState.mozeZamawiac && globalState.hasUnsavedChanges)
                ? 'Najpierw zapisz wybrany wariant'
                : '';
        });
    },

    /**
     * Podmienia wnętrza kafelków po zmianie wyboru. Świadomie NIE przebudowuje
     * paska — inaczej po kliknięciu kafelka pasek wracałby na początek.
     */
    refreshTiles(productIndex) {
        const product = this.productAt(productIndex);
        if (!product) return;

        const section = document.getElementById(`product-${productIndex}`);
        if (!section) return;

        const context = this.tileContext(product);
        const byId = new Map(this.visibleVariants(product).map(item => [String(item.id), item]));

        section.querySelectorAll('.tile').forEach(tile => {
            const item = byId.get(tile.dataset.itemId);
            if (!item) return;
            const isSelected = item.id === context.selectedId;
            const available = money.material(item).brutto > 0;
            tile.classList.toggle('sel', isSelected);
            tile.classList.toggle('off', !available);
            tile.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            tile.disabled = !available || !context.interactive;
            tile.innerHTML = this.tileInner(item, context);
        });
    },

    // -------------------------------------------------------------------------
    // PASEK KAFELKÓW — kropki i podpowiedź przewijania
    // -------------------------------------------------------------------------

    setupRails() {
        document.querySelectorAll('[data-rail]').forEach(rail => {
            if (!rail.dataset.railBound) {
                rail.addEventListener('scroll', () => this.updateRail(rail), { passive: true });
                rail.dataset.railBound = '1';
            }
            this.updateRail(rail);
        });
    },

    updateRail(rail) {
        const section = rail.closest('.sect');
        if (!section) return;

        const dotsBox = section.querySelector('[data-rail-dots]');
        const textBox = section.querySelector('[data-rail-text]');
        if (!dotsBox && !textBox) return;

        const tiles = Array.from(rail.querySelectorAll('.tile'));
        const railBox = rail.getBoundingClientRect();

        // ile kafelków nie mieści się w kadrze przy obecnym przewinięciu
        const hidden = tiles.filter(tile => {
            const box = tile.getBoundingClientRect();
            return box.left < railBox.left - 1 || box.right > railBox.right + 1;
        }).length;

        if (textBox) {
            textBox.innerHTML = hidden > 0
                ? `Przesuń, aby zobaczyć pozostałe <b>${hidden} ${utils.plural(hidden, 'wariant', 'warianty', 'wariantów')}</b>`
                : 'To wszystkie warianty';
        }

        if (dotsBox) {
            const pages = Math.max(1, Math.min(8, Math.ceil(rail.scrollWidth / Math.max(1, rail.clientWidth))));
            const active = Math.max(0, Math.min(pages - 1, Math.round(rail.scrollLeft / Math.max(1, rail.clientWidth))));
            if (dotsBox.children.length !== pages) {
                dotsBox.innerHTML = new Array(pages).fill('<i></i>').join('');
            }
            Array.from(dotsBox.children).forEach((dot, index) => {
                dot.classList.toggle('on', index === active);
            });
        }
    },

    // -------------------------------------------------------------------------
    // PODSUMOWANIE
    // -------------------------------------------------------------------------

    /**
     * Wiersze podsumowania (kwoty NETTO) — wykończenie i obróbka krawędzi
     * stoją tu jako DWA OSOBNE wiersze; ich suma to dokładnie ta kwota,
     * którą serwer trzyma razem w costs.finishing.
     */
    summaryRows() {
        const costs = money.view();
        const products = this.products();
        const extras = money.extrasTotals();
        const rows = [];

        products.forEach((product, position) => {
            const item = this.selectedItem(product);
            rows.push({
                label: `Produkt ${position + 1} · ${product.quantity} szt.`,
                // pod pozycją nazwa wybranego wariantu — inaczej "Produkt 1"
                // i "Produkt 2" niczym się nie różnią
                sub: item ? utils.translateVariantCode(item.variant_code) : '',
                value: money.material(item).netto
            });
        });

        // Koszty dodatkowe o wartości zero nie są pokazywane — pusty wiersz
        // "Wykończenie 0,00 zł" niczego klientowi nie mówi. Dostawa jest
        // wyjątkiem: jej brak to informacja (odbiór osobisty / gratis).
        const dodatkowe = [
            { label: 'Wykończenie', value: extras.finishingNetto },
            { label: 'Obróbka krawędzi', value: extras.edgesNetto }
        ].filter(row => money.round2(row.value) !== 0);

        dodatkowe.forEach(row => rows.push(row));
        rows.push({ label: 'Dostawa', value: money.pick(costs, 'shipping', 'netto') });

        // Filtrujemy PRZED liczeniem brutto — inaczej reszta groszowa mogłaby
        // trafić na wiersz, którego klient nie widzi, i kolumna przestałaby
        // się sumować do kwoty "Do zapłaty".
        //
        // Osobnego wiersza VAT nie ma — każdy wiersz pokazuje brutto i netto,
        // więc podatek jest widoczny jako różnica między nimi.
        //
        // Brutto każdego wiersza to round2(netto * 1,23), ale serwer zaokrągla
        // dopiero sumę (calculate_costs_with_vat), więc suma zaokrąglonych
        // wierszy potrafi różnić się o grosz od kwoty "Do zapłaty" — a klient
        // sprawdza właśnie tę pionową sumę.
        //
        // Resztę doklejamy do wiersza kosztu dodatkowego (dostawa / krawędzie /
        // wykończenie), NIE do pozycji. Rozrzucanie jej po pozycjach sprawiało,
        // że dwie identyczne pozycje pokazywały 2545,80 i 2545,81.
        rows.forEach(row => {
            row.brutto = money.round2(row.value * (1 + VAT_RATE));
        });

        const docelowoBrutto = money.pick(costs, 'total', 'brutto');
        const sumaBrutto = money.round2(rows.reduce((acc, row) => acc + row.brutto, 0));
        const reszta = money.round2(docelowoBrutto - sumaBrutto);

        if (reszta !== 0) {
            const kandydaci = rows.filter(row => !row.sub && row.value > 0);
            const nosnik = kandydaci.length
                ? kandydaci[kandydaci.length - 1]
                : rows[rows.length - 1];
            if (nosnik) nosnik.brutto = money.round2(nosnik.brutto + reszta);
        }

        return rows;
    },

    summaryLinesHtml() {
        return this.summaryRows().map(row => {
            const podpis = row.sub
                ? `<span class="sumline-sub">${utils.esc(row.sub)}</span>`
                : '';
            return `
            <div class="sumline">
                <span class="sumline-label">${utils.esc(row.label)}${podpis}</span>
                <span class="sumline-amounts">
                    <b>${utils.esc(utils.formatCurrency(row.brutto))}</b>
                    <span class="sumline-netto">netto ${utils.esc(utils.formatCurrency(row.value))}</span>
                </span>
            </div>`;
        }).join('');
    },

    /**
     * Podsumowanie w kolumnie desktopowej.
     * Klasy price-brutto/summary-total-main i price-netto/total-netto MUSZĄ
     * zostać — z nich korzysta awaryjny scraper w client_accept_modal.js.
     * Z tego samego powodu nigdzie wyżej na stronie nie używamy tych klas.
     */
    desktopSummary() {
        const summaryContainer = document.getElementById('desktopSummaryContent');
        const totalContainer = document.getElementById('desktopTotalSummary');
        if (!summaryContainer || !totalContainer) return;

        const costs = money.view();
        summaryContainer.innerHTML = this.summaryLinesHtml();
        totalContainer.innerHTML = `
            <div class="sumtot">
                <span>Do zapłaty</span>
                <b class="price-brutto summary-total-main">${utils.esc(utils.formatCurrency(money.pick(costs, 'total', 'brutto')))}</b>
            </div>
            <div class="price-netto total-netto">${utils.esc(utils.amount(money.pick(costs, 'total', 'netto')))} netto</div>`;

        // ostrzeżenie POD przyciskiem akceptacji, nie nad nim
        const notice = document.getElementById('desktopUnsavedNotice');
        if (notice) notice.innerHTML = this.unsavedNotice();

        this.syncAcceptButtons();
    },

    /**
     * Dolny pasek mobilny i jego rozwijana szuflada
     */
    mobileSummary() {
        const detailsContent = document.getElementById('mobileDetailsContent');
        const totalPrice = document.getElementById('mobileTotalPrice');
        const costs = money.view();

        if (totalPrice) {
            totalPrice.innerHTML = `
                <b class="price-brutto">${utils.esc(utils.formatCurrency(money.pick(costs, 'total', 'brutto')))}</b>
                <span class="price-netto">${utils.esc(utils.amount(money.pick(costs, 'total', 'netto')))} netto</span>`;
        }

        if (detailsContent) {
            detailsContent.innerHTML = `
                ${this.summaryLinesHtml()}
                <div class="sumtot">
                    <span>Do zapłaty</span>
                    <b>${utils.esc(utils.formatCurrency(money.pick(costs, 'total', 'brutto')))}</b>
                </div>`;
        }

        // poza szufladą, żeby było widać także przy zwiniętym podsumowaniu
        const notice = document.getElementById('barUnsavedNotice');
        if (notice) notice.innerHTML = this.unsavedNotice();

        this.syncAcceptButtons();
        this.syncBarHeight();
    },

    /**
     * Rezerwacja miejsca pod dolnym paskiem liczona z JEGO REALNEJ wysokości.
     * Sztywne 80 px przy pasku wysokim na 222 px chowało 142 px treści.
     */
    syncBarHeight() {
        const wrap = document.getElementById('mobileBottomBar');
        if (!wrap) return;

        // Szuflada podsumowania jest chwilowa — rezerwujemy miejsce tylko pod
        // stałą częścią paska (razem z jego górną kreską), więc jej wysokość
        // odejmujemy, gdy akurat jest rozwinięta.
        const details = document.getElementById('bottomBarDetails');
        const height = Math.round(
            wrap.getBoundingClientRect().height - (details ? details.getBoundingClientRect().height : 0)
        );
        if (height > 0) {
            document.documentElement.style.setProperty('--barh', `${height}px`);
        }
    },

    /**
     * Pełne odświeżenie widoku
     */
    refreshUI() {
        this.backdrop();
        this.productTabs();
        this.productSections();
        this.desktopSummary();
        this.mobileSummary();
    }
};

// ===================================
// ZDARZENIA
// ===================================
const handlers = {
    /**
     * Przełącza między pozycjami wyceny
     */
    switchProduct(index) {
        globalState.currentProductIndex = index;

        document.querySelectorAll('.product-button').forEach(button => {
            button.classList.toggle('active', Number(button.dataset.productIndex) === index);
        });

        document.querySelectorAll('.product-section').forEach(section => {
            section.classList.toggle('active', section.id === `product-${index}`);
        });

        const mobileSelect = document.getElementById('productSelect');
        if (mobileSelect) mobileSelect.value = String(index);

        // pasek kafelków dopiero co stał się widoczny — kropki liczą się
        // z wymiarów, więc trzeba je przeliczyć po pokazaniu sekcji
        render.backdrop();
        render.setupRails();
    },

    /**
     * Wybiera wariant pozycji (zapis dopiero po kliknięciu "Zapisz zmiany")
     */
    selectVariant(productIndex, variantId) {
        if (globalState.isQuoteAccepted || globalState.isLoading) return;
        if (globalState.selectedVariants.get(productIndex) === variantId) return;

        globalState.selectedVariants.set(productIndex, variantId);
        globalState.hasUnsavedChanges = true;

        render.refreshTiles(productIndex);
        render.backdrop();
        render.desktopSummary();
        render.mobileSummary();
        this.showSaveButton();
    },

    /**
     * Zapisuje wybrane warianty na serwerze
     */
    async saveChanges() {
        if (!globalState.hasUnsavedChanges || globalState.isLoading) return;

        const saveButtons = Array.from(document.querySelectorAll('.btn-save-changes'));
        saveButtons.forEach(button => {
            button.disabled = true;
            button.textContent = 'Zapisywanie...';
        });

        try {
            utils.setLoading(true);

            const changes = [];
            globalState.selectedVariants.forEach((variantId, productIndex) => {
                changes.push({ productIndex, variantId });
            });

            for (const change of changes) {
                await api.updateVariant(window.QUOTE_TOKEN, change.variantId);
            }

            globalState.hasUnsavedChanges = false;
            this.hideSaveButton();

            await init.loadQuoteData();
            utils.showAlert('Zmiany zostały zapisane', 'success');

        } catch (error) {
            console.error('Błąd przy zapisywaniu zmian:', error);
            utils.showAlert('Nie udało się zapisać wyboru wariantu. Spróbuj ponownie.', 'error');
            saveButtons.forEach(button => {
                button.disabled = false;
                button.textContent = 'Zapisz zmiany';
            });
        } finally {
            utils.setLoading(false);
        }
    },

    showSaveButton() {
        document.querySelectorAll('.save-changes-section').forEach(section => {
            section.classList.remove('hidden');
            requestAnimationFrame(() => section.classList.add('visible'));
        });
        render.syncAcceptButtons();
        render.syncBarHeight();
    },

    hideSaveButton() {
        document.querySelectorAll('.save-changes-section').forEach(section => {
            section.classList.remove('visible', 'pulse');
            section.classList.add('hidden');
        });
        render.syncAcceptButtons();
        render.syncBarHeight();
    },

    /**
     * Otwiera AR — na telefonie bezpośrednio, na desktopie przez kod QR
     */
    openARModal(productIndex) {
        if (typeof window.ARHandler === 'undefined') {
            utils.showAlert('Moduł AR nie jest dostępny. Odśwież stronę.', 'error');
            return;
        }

        const product = render.productAt(productIndex);
        const selectedItem = render.selectedItem(product);
        if (!selectedItem) {
            utils.showAlert('Nie można określić wariantu produktu', 'error');
            return;
        }

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

        if (utils.isMobile()) {
            this.launchDirectAR(productData);
        } else {
            this.showDesktopARModal(productData);
        }
    },

    async launchDirectAR(productData) {
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        const isSafari = /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);

        if (!isIOS) {
            utils.showAlert('AR jest dostępne tylko na iPhone i iPad', 'info');
            return;
        }
        if (!isSafari) {
            utils.showAlert('AR wymaga przeglądarki Safari', 'info');
            return;
        }

        try {
            utils.setLoading(true);
            await window.ARHandler.initiateIOSAR(productData);
        } catch (error) {
            console.error('[ClientAR] Błąd bezpośredniego AR:', error);
            utils.showAlert(`Nie udało się uruchomić AR: ${error.message}`, 'error');
        } finally {
            utils.setLoading(false);
        }
    },

    showDesktopARModal(productData) {
        const dims = productData.dimensions || {};
        const dimensions = `${dims.length || 0}×${dims.width || 0}×${dims.thickness || 0} cm`;
        const currentUrl = window.location.href;

        const modal = this.createARModalElement('Rzeczywistość rozszerzona', {
            icon: '🖥️',
            title: 'Zeskanuj kod QR swoim telefonem',
            message: `Model: ${utils.translateVariantCode(productData.variant_code)}\nWymiary: ${dimensions}\n\nFunkcja AR działa na iPhone i iPad z iOS 12+ oraz Safari.`,
            qrUrl: currentUrl,
            buttons: [
                { text: 'Zamknij', action: () => this.closeARModal(), primary: false }
            ]
        });

        this.showARModal(modal);
        setTimeout(() => this.generateQRCodeInModal(currentUrl), 100);
    },

    createARModalElement(title, options) {
        const modal = document.createElement('div');
        modal.className = 'ar-modal-overlay';

        const qrHtml = options.qrUrl
            ? '<div class="ar-qr-container"><div class="ar-qr-code" id="arQrCode"></div><div class="ar-qr-url" id="arQrUrl"></div></div>'
            : '';

        const buttonsHtml = (options.buttons || []).map(button =>
            `<button type="button" class="ar-modal-btn ${button.primary ? 'primary' : ''}" data-action="${utils.esc(button.text)}">${utils.esc(button.text)}</button>`
        ).join('');

        modal.innerHTML = `
            <div class="ar-modal-content">
                <div class="ar-modal-header">
                    <div class="ar-modal-icon">${utils.esc(options.icon)}</div>
                    <h2 class="ar-modal-title">${utils.esc(title)}</h2>
                </div>
                <div class="ar-modal-body">
                    <div class="ar-modal-message" style="white-space: pre-line;">${utils.esc(options.message)}</div>
                    ${qrHtml}
                </div>
                <div class="ar-modal-footer">${buttonsHtml}</div>
            </div>`;

        (options.buttons || []).forEach(button => {
            const element = modal.querySelector(`[data-action="${button.text}"]`);
            if (element) element.addEventListener('click', button.action);
        });

        return modal;
    },

    showARModal(modal) {
        this.closeARModal();
        modal.id = 'ar-modal';
        document.body.appendChild(modal);

        this._escHandler = (event) => {
            if (event.key === 'Escape') this.closeARModal();
        };
        document.addEventListener('keydown', this._escHandler);

        modal.addEventListener('click', (event) => {
            if (event.target === modal) this.closeARModal();
        });
    },

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

    generateQRCodeInModal(url) {
        const qrContainer = document.getElementById('arQrCode');
        const urlDisplay = document.getElementById('arQrUrl');
        if (!qrContainer || !urlDisplay || !window.QRCode) return;

        qrContainer.innerHTML = '';
        new QRCode(qrContainer, {
            text: url,
            width: 200,
            height: 200,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
        urlDisplay.textContent = url;
    },

    /**
     * Otwiera podgląd 3D/AR w nowym oknie
     */
    open3DViewer(productIndex) {
        if (!window.QUOTE_TOKEN) {
            utils.showAlert('Brak tokenu zabezpieczającego', 'error');
            return;
        }

        const viewerUrl = `/preview3d-ar/${window.QUOTE_TOKEN}`;
        const windowFeatures = [
            'width=1600', 'height=1000', 'scrollbars=yes', 'resizable=yes',
            'menubar=no', 'toolbar=no', 'location=no', 'status=no',
            'left=' + Math.max(0, (screen.width - 1600) / 2),
            'top=' + Math.max(0, (screen.height - 1000) / 2)
        ].join(',');

        const viewerWindow = window.open(viewerUrl, 'QuoteViewer3D_' + window.QUOTE_TOKEN, windowFeatures);
        if (!viewerWindow) {
            window.open(viewerUrl, '_blank');
        }
    },

    /**
     * Zamyka modal sterowany klasą .active (np. #qrModal)
     */
    closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.classList.remove('active');

        document.querySelectorAll('.form-error').forEach(element => {
            element.classList.add('hidden');
            element.textContent = '';
        });
    },

    /**
     * Rozwija/zwija szufladę podsumowania w dolnym pasku
     */
    toggleSummary() {
        const details = document.getElementById('bottomBarDetails');
        const chevron = document.getElementById('summaryChevron');
        if (details) details.classList.toggle('open');
        if (chevron) chevron.classList.toggle('open');
    }
};

// ===================================
// START
// ===================================
const init = {
    async loadQuoteData() {
        try {
            utils.setLoading(true);

            const token = window.QUOTE_TOKEN;
            if (!token) throw new Error('Brak tokenu wyceny');

            globalState.quoteData = await api.getQuoteData(token);

            globalState.selectedVariants.clear();
            if (Array.isArray(globalState.quoteData.items)) {
                globalState.quoteData.items.forEach(item => {
                    if (item.is_selected) {
                        globalState.selectedVariants.set(item.product_index, item.id);
                    }
                });
            }

            const products = render.products();
            if (products.length > 0 && !products.some(p => p.index === globalState.currentProductIndex)) {
                globalState.currentProductIndex = products[0].index;
            }

            globalState.isQuoteAccepted = !globalState.quoteData.is_client_editable;
            globalState.hasUnsavedChanges = false;

            this.syncAcceptModalData();
            render.refreshUI();

            if (globalState.isQuoteAccepted) this.disableInteractions();

        } catch (error) {
            console.error('Błąd ładowania danych:', error);
            utils.showAlert('Nie udało się wczytać wyceny. Odśwież stronę.', 'error');
        } finally {
            utils.setLoading(false);
        }
    },

    /**
     * Modal akceptacji czyta kwoty z window.currentQuoteData (szablon wstrzykuje
     * je przy renderze). Po zapisie wariantu te kwoty byłyby nieaktualne,
     * więc odświeżamy je razem z danymi z API.
     */
    syncAcceptModalData() {
        const costs = (globalState.quoteData && globalState.quoteData.costs) || {};
        window.currentQuoteData = Object.assign({}, window.currentQuoteData, {
            quote_number: globalState.quoteData.quote_number,
            total_netto: money.pick(costs, 'total', 'netto').toFixed(2),
            total_vat: money.pick(costs, 'total', 'vat').toFixed(2),
            total_brutto: money.pick(costs, 'total', 'brutto').toFixed(2)
        });
    },

    /**
     * Wycena zaakceptowana = koniec edycji wariantów. NIE gasimy tu przycisku
     * zamawiania: wycena zaakceptowana i jeszcze niezamówiona ma dać się
     * zamówić — o stanie przycisku decyduje wyłącznie syncAcceptButtons()
     * na podstawie mozeZamawiac.
     */
    disableInteractions() {
        document.body.classList.add('quote-accepted');
        // `render.`, nie `this.` — ta metoda mieszka na obiekcie `render`,
        // a wołamy ją z `init`. Wywołanie przez `this` kończyło się
        // TypeError-em, który `loadQuoteData` łapało i zamieniało na fałszywe
        // „Nie udało się wczytać wyceny. Odśwież stronę." na KAŻDEJ
        // zaakceptowanej wycenie.
        render.syncAcceptButtons();
    },

    /**
     * Akceptacja z niezapisanym wyborem wariantu wysłałaby na serwer STARY
     * wariant, a modal pokazałby kwoty podglądu. Dlatego przy niezapisanym
     * wyborze modal się NIE otwiera — klient musi najpierw kliknąć "Zapisz
     * zmiany". Świadomie nie zapisujemy za niego po cichu: zapis zmienia
     * wycenę na serwerze i ma być decyzją, a nie efektem ubocznym.
     */
    guardAcceptModal() {
        const original = window.openAcceptModal;
        if (typeof original !== 'function' || original.__wpGuarded) return;

        const guarded = function (quoteData) {
            if (globalState.hasUnsavedChanges) {
                init.highlightUnsavedNotice();
                return undefined;
            }
            return original.call(this, quoteData || window.currentQuoteData);
        };
        guarded.__wpGuarded = true;
        window.openAcceptModal = guarded;
    },

    /**
     * Zwraca uwagę na informację o niezapisanym wyborze — gdy przycisk
     * akceptacji jest zablokowany, klient musi wiedzieć dlaczego.
     */
    highlightUnsavedNotice() {
        const notices = Array.from(document.querySelectorAll('.save-changes-section.visible'));
        const widoczna = notices.find(el => el.offsetParent !== null);
        if (!widoczna) return;

        widoczna.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        widoczna.classList.remove('pulse');
        // reflow, żeby animacja odpaliła też przy powtórnym kliknięciu
        void widoczna.offsetWidth;
        widoczna.classList.add('pulse');
    },

    setupEventListeners() {
        // "Zapisz zmiany" żyje teraz POD podsumowaniem, czyli poza
        // #productSections — delegacja z tamtej sekcji już go nie łapie.
        document.addEventListener('click', (event) => {
            const btn = event.target.closest('[data-action="save-changes"]');
            if (btn) handlers.saveChanges();
        });

        // Wybór pozycji (telefon)
        const productSelect = document.getElementById('productSelect');
        if (productSelect) {
            productSelect.addEventListener('change', (event) => {
                handlers.switchProduct(parseInt(event.target.value, 10));
            });
        }

        // Przełącznik pozycji (desktop) — delegacja, bo przyciski powstają w renderze
        const productButtons = document.getElementById('productButtons');
        if (productButtons) {
            productButtons.addEventListener('click', (event) => {
                const button = event.target.closest('.product-button');
                if (!button) return;
                handlers.switchProduct(Number(button.dataset.productIndex));
            });
        }

        // Kafelki wariantów, przyciski 3D/AR i zapis zmian — jedna delegacja
        const sections = document.getElementById('productSections');
        if (sections) {
            sections.addEventListener('click', (event) => {
                const actionButton = event.target.closest('[data-action]');
                if (actionButton) {
                    const productIndex = Number(actionButton.dataset.productIndex);
                    if (actionButton.dataset.action === 'view-3d') return handlers.open3DViewer(productIndex);
                    if (actionButton.dataset.action === 'view-ar') return handlers.openARModal(productIndex);
                    if (actionButton.dataset.action === 'save-changes') return handlers.saveChanges();
                    return undefined;
                }

                const tile = event.target.closest('.tile');
                if (!tile || tile.disabled) return undefined;
                handlers.selectVariant(Number(tile.dataset.productIndex), Number(tile.dataset.itemId));
                return undefined;
            });
        }

        // Zamykanie modali klasą .active
        document.querySelectorAll('.modal-overlay').forEach(modal => {
            modal.addEventListener('click', (event) => {
                if (event.target === modal) handlers.closeModal(modal.id);
            });
        });

        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const activeModal = document.querySelector('.modal-overlay.active');
            if (activeModal) handlers.closeModal(activeModal.id);
        });

        // Wysokość dolnego paska zmienia się razem z układem strony
        window.addEventListener('resize', () => {
            render.syncBarHeight();
            document.querySelectorAll('[data-rail]').forEach(rail => render.updateRail(rail));
        });

        const bar = document.querySelector('#mobileBottomBar .bar');
        if (bar && typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(() => render.syncBarHeight()).observe(bar);
        }

        // Rozwinięcie szuflady nie może zmienić rezerwacji miejsca pod paskiem
        const summaryToggle = document.getElementById('summaryToggle');
        if (summaryToggle) {
            summaryToggle.addEventListener('click', () => render.syncBarHeight());
        }

        // Funkcje wołane z atrybutów onclick w szablonie
        window.handlers = handlers;
        window.toggleSummary = () => handlers.toggleSummary();
        window.closeModal = (modalId) => handlers.closeModal(modalId);
    }
};

// ===================================
// WEJŚCIE
// ===================================
document.addEventListener('DOMContentLoaded', async () => {
    try {
        init.setupEventListeners();
        init.guardAcceptModal();
        render.syncBarHeight();
        await init.loadQuoteData();
    } catch (error) {
        console.error('Błąd inicjalizacji:', error);
        utils.showAlert('Nie udało się wczytać strony wyceny. Odśwież stronę.', 'error');
    }
});

// ===================================
// API PUBLICZNE (debug i testy)
// ===================================
window.clientQuote = {
    state: globalState,
    api: api,
    utils: utils,
    money: money,
    render: render,
    handlers: handlers,
    init: init
};
