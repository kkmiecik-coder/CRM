// calculator-ui.js
// Moduł UI - renderowanie wykończeń, opisy produktów, panel podsumowania

/**
 * Inicjalizuje toggle kształtu produktu dla danego formularza
 */
function initShapeToggle(form) {
    const radios = form.querySelectorAll('input[data-field="shapeRect"], input[data-field="shapeRound"]');
    if (!radios.length) return;

    // Wymusz domyślne zaznaczenie prostokąta jeśli nic nie zaznaczone
    const checkedRadio = form.querySelector('input[data-field="shapeRect"]:checked, input[data-field="shapeRound"]:checked');
    if (checkedRadio) {
        form.dataset.productShape = checkedRadio.value;
    } else {
        const rectRadio = form.querySelector('input[data-field="shapeRect"]');
        if (rectRadio) rectRadio.checked = true;
        form.dataset.productShape = 'rectangular';
    }


    // Dodaj listenery tylko raz (flaga na formularzu)
    if (form.dataset.shapeListenersAttached) return;
    form.dataset.shapeListenersAttached = 'true';

    radios.forEach(radio => {
        radio.addEventListener('change', function () {
            const newShape = this.value;
            const oldShape = form.dataset.productShape;
            if (newShape === oldShape) return;

            form.dataset.productShape = newShape;

            // Okrągły: kopiuj długość na szerokość i zablokuj pole
            const widthInput = form.querySelector('input[data-field="width"]');
            const lengthInput = form.querySelector('input[data-field="length"]');
            if (widthInput) {
                if (newShape === 'round') {
                    if (lengthInput && lengthInput.value) {
                        widthInput.value = lengthInput.value;
                    }
                    widthInput.readOnly = true;
                    widthInput.style.opacity = '0.5';
                    widthInput.style.cursor = 'not-allowed';
                } else {
                    widthInput.readOnly = false;
                    widthInput.style.opacity = '';
                    widthInput.style.cursor = '';
                }
            }

            // Reset krawędzi przy zmianie kształtu
            if (window.EdgesModule && typeof window.EdgesModule.reset === 'function') {
                window.EdgesModule.reset(form);
            }

            // Przelicz ceny
            updatePrices();
        });
    });

    // Listener na długość: kopiuj wartość na szerokość gdy kształt okrągły
    const lengthInput = form.querySelector('input[data-field="length"]');
    const widthInput = form.querySelector('input[data-field="width"]');
    if (lengthInput && widthInput) {
        lengthInput.addEventListener('input', function () {
            if (form.dataset.productShape === 'round') {
                widthInput.value = this.value;
            }
        });
    }

    // Jeśli formularz już jest w trybie okrągłym (np. po załadowaniu)
    if (form.dataset.productShape === 'round' && widthInput) {
        const lengthVal = form.querySelector('input[data-field="length"]');
        if (lengthVal && lengthVal.value) {
            widthInput.value = lengthVal.value;
        }
        widthInput.readOnly = true;
        widthInput.style.opacity = '0.5';
        widthInput.style.cursor = 'not-allowed';
    }
}

// Pobieranie cen wykończeń z bazy danych i renderowanie drzewka
async function loadFinishingPrices() {
    try {

        const response = await fetch('/calculator/api/finishing-prices');
        if (response.ok) {
            const prices = await response.json();
            window.finishingPrices = {};
            window.finishingOptionsFlat = prices; // Przechowaj płaską listę
            window.finishingOptionsById = {}; // Indeks po ID

            prices.forEach(price => {
                // Indeks po ID
                window.finishingOptionsById[price.id] = price;

                // Użyj full_path jeśli dostępny, inaczej name
                const fullPath = price.full_path || price.name;

                // Zapisz po pełnej ścieżce (np. "Lakierowane > Bezbarwne")
                window.finishingPrices[fullPath] = parseFloat(price.price_netto);

                // Mapowanie dla kompatybilności wstecznej z istniejącym kodem
                // Konwertuj "Lakierowane > Bezbarwne" na "Lakierowane bezbarwne"
                const legacyName = fullPath.replace(' > ', ' ').toLowerCase();
                const legacyNameCapitalized = legacyName.charAt(0).toUpperCase() + legacyName.slice(1);
                window.finishingPrices[legacyNameCapitalized] = parseFloat(price.price_netto);

                // Dodaj też samą nazwę (dla opcji głównych jak "Surowe", "Olejowanie")
                if (price.level === 0) {
                    window.finishingPrices[price.name] = parseFloat(price.price_netto);
                }
            });


            // Renderuj drzewko we wszystkich formularzach
            document.querySelectorAll('.quote-form').forEach(form => {
                renderFinishingTree(form);
            });
        } else {
            throw new Error(`HTTP ${response.status}`);
        }
    } catch (error) {
        console.error('[CALCULATOR] Błąd pobierania cen wykończeń z bazy, używam domyślnych:', error);

        // Fallback - domyślne ceny
        window.finishingPrices = {
            'Surowe': 0,
            'Lakierowane bezbarwne': 200,
            'Lakierowane barwne': 250,
            'Olejowanie': 250
        };
        window.finishingOptionsFlat = [];

    }
}

/**
 * Renderuje hierarchiczne drzewko wykończeń w formularzu
 */
function renderFinishingTree(form) {
    const container = form.querySelector('.finishing-tree-container');
    if (!container) return;

    const options = window.finishingOptionsFlat || [];
    if (options.length === 0) {
        container.innerHTML = '<p class="input-txt">Brak opcji wykończeń</p>';
        return;
    }

    // Buduj strukturę - grupuj opcje po parent_id
    const optionsByParent = {};
    options.forEach(opt => {
        const parentKey = opt.parent_id || 'root';
        if (!optionsByParent[parentKey]) {
            optionsByParent[parentKey] = [];
        }
        optionsByParent[parentKey].push(opt);
    });

    // Renderuj poziom 0 (główne opcje)
    const rootOptions = optionsByParent['root'] || [];

    // Znajdź opcję z dziećmi tekstowymi (Lakierowanie) — jej warianty renderujemy od razu
    let level1Html = '';
    const optionWithVariants = rootOptions.find(opt => {
        const children = optionsByParent[opt.id] || [];
        return children.length > 0 && !children.some(c => c.image_path);
    });

    if (optionWithVariants) {
        const variantChildren = optionsByParent[optionWithVariants.id] || [];
        level1Html = `
            <div class="finishing-level finishing-level-variants" data-level="1" data-parent-option-id="${optionWithVariants.id}">
                <p class="input-txt">Wariant:</p>
                <div class="button-group finishing-options-group" data-parent-id="${optionWithVariants.id}">
                    ${renderFinishingOptions(variantChildren, 1)}
                </div>
            </div>
        `;
    }

    container.innerHTML = `
        <div class="finishing-level" data-level="0">
            <p class="input-txt">Rodzaj wykończenia:</p>
            <div class="button-group finishing-options-group" data-parent-id="null">
                ${renderFinishingOptions(rootOptions, 0)}
            </div>
        </div>
        ${level1Html}
        <div class="finishing-level finishing-level-gloss" data-level="gloss" style="display: none;">
            <p class="input-txt">Połysk:</p>
            <div class="button-group finishing-gloss-group">
                <button type="button" class="finishing-btn finishing-gloss-btn" data-gloss-value="Matowy">Matowy</button>
                <button type="button" class="finishing-btn finishing-gloss-btn" data-gloss-value="Półmatowy">Półmatowy</button>
            </div>
        </div>
    `;

    // Warianty domyślnie nieaktywne (CSS), nie trzeba nic ustawiać

    // Dodaj obsługę kliknięć
    setupFinishingTreeHandlers(form, optionsByParent);

    // Domyślnie zaznacz pierwszą opcję (Surowe)
    const firstBtn = container.querySelector('.finishing-level[data-level="0"] .finishing-option-btn');
    if (firstBtn) {
        firstBtn.click();
    }
}

/**
 * Renderuje przyciski opcji wykończenia - różnicuje między tekstowymi a obrazkowymi
 */
function renderFinishingOptions(options, level) {
    // Sprawdź czy są opcje z obrazkami
    const hasImages = options.some(opt => opt.image_path);

    if (hasImages) {
        // Renderuj jako przyciski z obrazkami obok nazwy
        return `<div class="color-group">${options.map(opt => {
            const staticBase = document.body.dataset.staticBase || '/calculator/static/';
            const imgUrl = opt.image_path ? `${staticBase}${opt.image_path}` : '';
            const fullPath = opt.full_path || opt.name;
            const imgHtml = imgUrl
                ? `<img src="${imgUrl}" alt="${opt.name}" onerror="this.classList.add('img-error')">`
                : `<span class="color-placeholder"></span>`;
            return `
                <button type="button" class="color-btn finishing-option-btn"
                        data-option-id="${opt.id}"
                        data-option-name="${opt.name}"
                        data-option-price="${opt.price_netto}"
                        data-option-level="${opt.level}"
                        data-full-path="${fullPath}">
                    ${imgHtml}
                    <span>${opt.name}</span>
                </button>
            `;
        }).join('')}</div>`;
    } else {
        // Renderuj jako przyciski tekstowe
        return options.map(opt => {
            const fullPath = opt.full_path || opt.name;
            return `
                <button type="button" class="finishing-btn finishing-option-btn"
                        data-option-id="${opt.id}"
                        data-option-name="${opt.name}"
                        data-option-price="${opt.price_netto}"
                        data-option-level="${opt.level}"
                        data-full-path="${fullPath}">
                    ${opt.name}
                </button>
            `;
        }).join('');
    }
}

/**
 * Konfiguruje obsługę kliknięć w drzewku wykończeń
 */
function setupFinishingTreeHandlers(form, optionsByParent) {
    const container = form.querySelector('.finishing-tree-container');
    if (!container) return;

    container.addEventListener('click', (e) => {
        const btn = e.target.closest('.finishing-option-btn');
        if (!btn) return;

        // Nie reaguj na kliknięcia w nieaktywnym poziomie
        const parentLevel = btn.closest('.finishing-level');
        if (parentLevel && parentLevel.classList.contains('finishing-level-variants') && !parentLevel.classList.contains('enabled')) return;

        const optionId = parseInt(btn.dataset.optionId);
        const optionLevel = parseInt(btn.dataset.optionLevel);
        const optionName = btn.dataset.optionName;

        // Usuń aktywność z innych przycisków na tym samym poziomie
        const currentLevelContainer = btn.closest('.finishing-level');
        currentLevelContainer.querySelectorAll('.finishing-option-btn').forEach(b => {
            b.classList.remove('active');
        });
        btn.classList.add('active');

        // Usuń dynamiczne poziomy poniżej aktualnego (ale nie stały level wariantów)
        const allLevels = container.querySelectorAll('.finishing-level');
        allLevels.forEach(level => {
            const levelNum = parseInt(level.dataset.level);
            if (levelNum > optionLevel && !level.classList.contains('finishing-level-variants') && !level.classList.contains('finishing-level-gloss')) {
                level.remove();
            }
        });

        // Obsługa poziomu 0 — włącz/wyłącz stały poziom wariantów
        if (optionLevel === 0) {
            const variantLevel = container.querySelector('.finishing-level-variants');
            if (variantLevel) {
                const parentOptionId = variantLevel.dataset.parentOptionId;
                if (String(optionId) === String(parentOptionId)) {
                    // Ta opcja ma warianty — włącz
                    variantLevel.classList.add('enabled');
                } else {
                    // Inna opcja — wyłącz warianty i resetuj zaznaczenie
                    variantLevel.classList.remove('enabled');
                    variantLevel.querySelectorAll('.finishing-option-btn').forEach(b => b.classList.remove('active'));
                    // Usuń dynamiczne poziomy powyżej 1 (np. kolory)
                    container.querySelectorAll('.finishing-level:not([data-level="0"]):not(.finishing-level-variants):not(.finishing-level-gloss)').forEach(l => l.remove());
                }
            }

            // Połysk — pokaż tylko dla Lakierowania (opcja z wariantami)
            const glossLevel = container.querySelector('.finishing-level-gloss');
            if (glossLevel) {
                const isLakierowanie = variantLevel && String(optionId) === String(variantLevel.dataset.parentOptionId);
                if (isLakierowanie) {
                    glossLevel.style.display = '';
                    // Nie ustawiamy automatycznie — użytkownik musi kliknąć
                } else {
                    glossLevel.style.display = 'none';
                    // Reset — odznacz wszystko
                    glossLevel.querySelectorAll('.finishing-gloss-btn').forEach(b => b.classList.remove('active'));
                    form.dataset.finishingGloss = '';
                }
            }
        }

        // Dla wariantów i głębszych poziomów — renderuj dzieci dynamicznie
        if (optionLevel >= 1) {
            // Usuń poziomy głębsze niż aktualny (kolory itp.)
            container.querySelectorAll('.finishing-level').forEach(level => {
                const levelNum = parseInt(level.dataset.level);
                if (levelNum > optionLevel && !level.classList.contains('finishing-level-variants') && !level.classList.contains('finishing-level-gloss')) {
                    level.remove();
                }
            });

            const children = optionsByParent[optionId] || [];
            if (children.length > 0) {
                const nextLevel = optionLevel + 1;
                const hasImages = children.some(opt => opt.image_path);
                const labelText = hasImages ? 'Kolor:' : 'Wariant:';

                const newLevelHtml = `
                    <div class="finishing-level" data-level="${nextLevel}">
                        <p class="input-txt">${labelText}</p>
                        <div class="button-group finishing-options-group" data-parent-id="${optionId}">
                            ${renderFinishingOptions(children, nextLevel)}
                        </div>
                    </div>
                `;

                container.insertAdjacentHTML('beforeend', newLevelHtml);
            }
        }

        // Zaktualizuj wybrane wykończenie w formularzu
        updateSelectedFinishing(form);

        // Przelicz koszt wykończenia
        if (typeof calculateFinishingCost === 'function') {
            calculateFinishingCost(form);
        }

        // Odśwież karty produktów (walidacja kompletności wykończenia)
        if (typeof generateProductsSummary === 'function') {
            generateProductsSummary();
        }
    });

    // Obsługa kliknięć w przyciski połysku
    container.addEventListener('click', (e) => {
        const glossBtn = e.target.closest('.finishing-gloss-btn');
        if (!glossBtn) return;

        container.querySelectorAll('.finishing-gloss-btn').forEach(b => b.classList.remove('active'));
        glossBtn.classList.add('active');
        form.dataset.finishingGloss = glossBtn.dataset.glossValue;

        // Przelicz koszt wykończenia (mógł być zablokowany przez brak wyboru połysku)
        if (typeof calculateFinishingCost === 'function') {
            calculateFinishingCost(form);
        }

        if (typeof generateProductsSummary === 'function') {
            generateProductsSummary();
        }
    });
}

/**
 * Aktualizuje wybrane wykończenie na podstawie aktywnych przycisków
 */
function updateSelectedFinishing(form) {
    const container = form.querySelector('.finishing-tree-container');
    if (!container) return;

    // Zbierz wszystkie aktywne opcje
    const activeButtons = container.querySelectorAll('.finishing-option-btn.active');
    const selectedPath = [];
    let finalOption = null;

    activeButtons.forEach(btn => {
        selectedPath.push(btn.dataset.optionName);
        finalOption = {
            id: parseInt(btn.dataset.optionId),
            name: btn.dataset.optionName,
            fullPath: btn.dataset.fullPath,
            price: parseFloat(btn.dataset.optionPrice) || 0
        };
    });

    // Zapisz w dataset formularza dla kompatybilności
    if (selectedPath.length > 0) {
        form.dataset.finishingType = selectedPath[0]; // Główny typ (Surowe, Lakierowane, Olejowanie)
        form.dataset.finishingVariant = selectedPath[1] || ''; // Wariant (Bezbarwne, Barwne)
        form.dataset.finishingColor = selectedPath[2] || ''; // Kolor (jeśli wybrany)
        form.dataset.finishingFullPath = selectedPath.join(' > ');
        form.dataset.finishingOptionId = finalOption?.id || '';
    }

    // Połysk — tylko dla Lakierowania/Lakierowane
    const glossBtn = container.querySelector('.finishing-gloss-btn.active');
    const glossSection = container.querySelector('.finishing-level-gloss');
    if (glossBtn && glossSection && glossSection.style.display !== 'none') {
        form.dataset.finishingGloss = glossBtn.dataset.glossValue;
    } else if (!glossSection || glossSection.style.display === 'none') {
        form.dataset.finishingGloss = '';
    }
}

function toggleTheme() {
    document.documentElement.toggleAttribute('data-theme', 'dark');
}

// Podpięcie listenerów UI wykończeń do formularza (stary system przycisków)
function attachFinishingUIListeners(form) {
    if (!form) return;

    const formIndex = Array.from(quoteFormsContainer.children).indexOf(form);

    const typeButtons = form.querySelectorAll('.finishing-btn[data-finishing-type]');
    const variantButtons = form.querySelectorAll('.finishing-btn[data-finishing-variant]');
    const glossButtons = form.querySelectorAll('.finishing-btn[data-finishing-gloss]');
    const colorButtons = form.querySelectorAll('.color-btn[data-finishing-color]');

    const variantWrapper = form.querySelector(`#finishing-variant-wrapper-${formIndex}`) ||
                          form.querySelector('#finishing-variant-wrapper');
    const glossWrapper = form.querySelector(`#finishing-gloss-wrapper-${formIndex}`) ||
                        form.querySelector('#finishing-gloss-wrapper');
    const colorWrapper = form.querySelector(`#finishing-color-wrapper-${formIndex}`) ||
                        form.querySelector('#finishing-color-wrapper');

    // ❌ PROBLEM: Te zmienne są ustawiane tylko raz na początku
    // let currentType = form.querySelector('.finishing-btn[data-finishing-type].active')?.dataset.finishingType || 'Surowe';
    // let currentVariant = form.querySelector('.finishing-btn[data-finishing-variant].active')?.dataset.finishingVariant || 'Surowe';

    const resetButtons = buttons => buttons.forEach(btn => btn.classList.remove('active'));
    const show = el => { if (el) el.style.display = 'flex'; };
    const hide = el => { if (el) el.style.display = 'none'; };

    function updateVisibility() {
        const currentType = form.querySelector('.finishing-btn[data-finishing-type].active')?.dataset.finishingType || 'Surowe';
        const currentVariant = form.querySelector('.finishing-btn[data-finishing-variant].active')?.dataset.finishingVariant || 'Surowe';


        if (currentType === 'Surowe') {
            hide(variantWrapper);
            hide(colorWrapper);
            return;
        }

        if (currentType === 'Olejowanie') {
            hide(variantWrapper);
            hide(colorWrapper);
            return;
        }

        if (currentType === 'Lakierowanie') {
            show(variantWrapper);

            if (currentVariant === 'Barwne') {
                show(colorWrapper);
            } else {
                hide(colorWrapper);
            }
        }
    }

    typeButtons.forEach(btn => {
        // Usuń poprzednie listenery specyficzne dla tego formularza
        btn.removeEventListener('click', btn._formSpecificHandler);

        btn._formSpecificHandler = () => {
            resetButtons(typeButtons);
            btn.classList.add('active');
            // ❌ USUNIĘTE: currentType = btn.dataset.finishingType;
            updateVisibility(); // ✅ POPRAWKA: updateVisibility pobierze aktualną wartość
            calculateFinishingCost(form);
            generateProductsSummary();
        };

        btn.addEventListener('click', btn._formSpecificHandler);
    });

    variantButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);

        btn._formSpecificHandler = () => {
            resetButtons(variantButtons);
            btn.classList.add('active');
            // ❌ USUNIĘTE: currentVariant = btn.dataset.finishingVariant;
            updateVisibility(); // ✅ POPRAWKA: updateVisibility pobierze aktualną wartość
            calculateFinishingCost(form);
            generateProductsSummary();
        };

        btn.addEventListener('click', btn._formSpecificHandler);
    });

    glossButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);

        btn._formSpecificHandler = () => {
            resetButtons(glossButtons);
            btn.classList.add('active');
            generateProductsSummary();
        };

        btn.addEventListener('click', btn._formSpecificHandler);
    });

    colorButtons.forEach(btn => {
        btn.removeEventListener('click', btn._formSpecificHandler);

        btn._formSpecificHandler = () => {
            resetButtons(colorButtons);
            btn.classList.add('active');
            generateProductsSummary();
        };

        btn.addEventListener('click', btn._formSpecificHandler);
    });

    // Wywołaj updateVisibility na początku, żeby ustawić prawidłowy stan
    updateVisibility();
}

// Obliczanie kosztu wykończenia dla formularza
function calculateFinishingCost(form) {
    dbg("🧪 calculateFinishingCost start:", form?.id || 'brak ID');

    if (!form) return { netto: null, brutto: null };

    // Pobierz wybrane wykończenie z dynamicznego drzewka
    // Dane są zapisywane w form.dataset przez updateSelectedFinishing()
    const finishingType = form.dataset.finishingType || 'Surowe';
    const finishingVariant = form.dataset.finishingVariant || null;
    const finishingFullPath = form.dataset.finishingFullPath || finishingType;
    const finishingOptionId = form.dataset.finishingOptionId ? parseInt(form.dataset.finishingOptionId) : null;

    // Pobierz elementy input
    const lengthInput = form.querySelector('input[data-field="length"]');
    const widthInput = form.querySelector('input[data-field="width"]');
    const thicknessInput = form.querySelector('input[data-field="thickness"]');
    const quantityInput = form.querySelector('input[data-field="quantity"]');

    // Znajdź elementy do wyświetlania kosztów
    let finishingBruttoEl = form.querySelector('.finishing-brutto') || document.getElementById('finishing-brutto');
    let finishingNettoEl = form.querySelector('.finishing-netto') || document.getElementById('finishing-netto');

    // Jeśli surowe - zwróć 0 i ukryj wiersz wykończenia
    if (finishingType === 'Surowe') {
        form.dataset.finishingBrutto = 0;
        form.dataset.finishingNetto = 0;
        if (finishingBruttoEl) finishingBruttoEl.textContent = '0.00 PLN';
        if (finishingNettoEl) finishingNettoEl.textContent = '0.00 PLN';
        // Ukryj wiersz wykończenia w options-summary
        updateFinishingSummaryRow(form, 'Surowe', null, 0, 0);
        updateGlobalSummary();
        dbg("🧪 calculateFinishingCost end: surowe");
        return { netto: 0, brutto: 0 };
    }

    // Walidacja wymiarów
    if (!lengthInput?.value || !widthInput?.value || !thicknessInput?.value) {
        dbg("🧪 calculateFinishingCost end: brak wymiarów");
        return { netto: null, brutto: null };
    }

    // Walidacja połysku — jeśli sekcja widoczna, ale nic nie wybrano → nie licz ceny
    const glossSection = form.querySelector('.finishing-level-gloss');
    if (glossSection && glossSection.style.display !== 'none') {
        const glossSelected = glossSection.querySelector('.finishing-gloss-btn.active');
        if (!glossSelected) {
            form.dataset.finishingBrutto = 0;
            form.dataset.finishingNetto = 0;
            if (finishingBruttoEl) finishingBruttoEl.textContent = '0.00 PLN';
            if (finishingNettoEl) finishingNettoEl.textContent = '0.00 PLN';
            updateFinishingSummaryRow(form, finishingType, null, 0, 0);
            updateGlobalSummary();
            dbg("🧪 calculateFinishingCost end: brak wyboru połysku");
            return { netto: 0, brutto: 0 };
        }
    }

    const lengthVal = parseFloat(lengthInput.value);
    const widthVal = parseFloat(widthInput.value);
    const thicknessVal = parseFloat(thicknessInput.value);
    const quantityVal = parseInt(quantityInput.value) || 1;

    // POPRAWIONE OBLICZENIE POWIERZCHNI:
    // Wymiary są już w cm, konwertujemy na metry
    const lengthM = lengthVal / 100;     // cm → m
    const widthM = widthVal / 100;       // cm → m
    const thicknessM = thicknessVal / 100; // cm → m

    // Powierzchnia w m² - zależna od kształtu produktu
    const formShape = form.dataset.productShape || 'rectangular';
    let surfaceAreaPerPieceM2;

    if (formShape === 'round') {
        // Elipsa: Góra + Dół = 2 * π * a * b
        // Pasek boczny: obwód elipsy * grubość
        // Obwód Ramanujan: π * [3(a+b) - sqrt((3a+b)(a+3b))]
        const a = lengthM / 2, b = widthM / 2;
        const topBottom = 2 * Math.PI * a * b;
        const perimeter = Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
        const sideBand = perimeter * thicknessM;
        surfaceAreaPerPieceM2 = topBottom + sideBand;
    } else {
        // Prostokąt: 6 ścian
        surfaceAreaPerPieceM2 = 2 * (lengthM * widthM + lengthM * thicknessM + widthM * thicknessM);
    }

    const totalSurfaceAreaM2 = surfaceAreaPerPieceM2 * quantityVal;

    dbg("🧪 Obliczenia powierzchni:", {
        "Wymiary [cm]": `${lengthVal}×${widthVal}×${thicknessVal}`,
        "Wymiary [m]": `${lengthM.toFixed(3)}×${widthM.toFixed(3)}×${thicknessM.toFixed(3)}`,
        "Powierzchnia 1 szt [m²]": surfaceAreaPerPieceM2.toFixed(4),
        "Ilość": quantityVal,
        "Całkowita powierzchnia [m²]": totalSurfaceAreaM2.toFixed(4)
    });

    // Pobierz cenę z bazy danych (dynamicznie z drzewka wykończeń)
    let pricePerM2 = 0;

    // Próbuj pobrać cenę z wybranej opcji (używa ID opcji)
    if (finishingOptionId && window.finishingOptionsById) {
        const selectedOption = window.finishingOptionsById[finishingOptionId];
        if (selectedOption && selectedOption.price_netto) {
            pricePerM2 = parseFloat(selectedOption.price_netto);
        }
    }

    // Fallback: spróbuj po pełnej ścieżce
    if (pricePerM2 === 0 && finishingFullPath && window.finishingPrices) {
        pricePerM2 = window.finishingPrices[finishingFullPath] || 0;
    }

    // Legacy fallback dla kompatybilności wstecznej
    if (pricePerM2 === 0) {
        if (finishingType === 'Lakierowanie' && finishingVariant === 'Bezbarwne') {
            pricePerM2 = window.finishingPrices?.['Lakierowane bezbarwne'] || 200;
        } else if (finishingType === 'Lakierowanie' && finishingVariant === 'Barwne') {
            pricePerM2 = window.finishingPrices?.['Lakierowane barwne'] || 250;
        } else if (finishingType === 'Olejowanie') {
            pricePerM2 = window.finishingPrices?.['Olejowanie'] || 250;
        }
    }

    dbg("🧪 Cena wykończenia:", {
        "Typ": finishingType,
        "Wariant": finishingVariant,
        "Pełna ścieżka": finishingFullPath,
        "ID opcji": finishingOptionId,
        "Cena za m² [PLN netto]": pricePerM2
    });

    // Oblicz końcowe koszty
    const finishingPriceNetto = Math.round(totalSurfaceAreaM2 * pricePerM2 * 100) / 100;
    const finishingPriceBrutto = Math.round(finishingPriceNetto * 1.23 * 100) / 100;

    // Zapisz w dataset formularza
    form.dataset.finishingBrutto = finishingPriceBrutto;
    form.dataset.finishingNetto = finishingPriceNetto;

    // Aktualizuj wyświetlanie
    if (finishingBruttoEl) finishingBruttoEl.textContent = finishingPriceBrutto.toFixed(2) + ' PLN';
    if (finishingNettoEl) finishingNettoEl.textContent = finishingPriceNetto.toFixed(2) + ' PLN';

    // Aktualizuj wiersz wykończenia w sekcji options-summary
    updateFinishingSummaryRow(form, finishingType, finishingVariant, finishingPriceNetto, finishingPriceBrutto);

    // Odśwież globalne podsumowanie
    updateGlobalSummary();
    generateProductsSummary();

    dbg("🧪 calculateFinishingCost end:", {
        finishingPriceNetto,
        finishingPriceBrutto,
        "powierzchnia_m2": totalSurfaceAreaM2.toFixed(4),
        "cena_za_m2": pricePerM2
    });

    return { netto: finishingPriceNetto, brutto: finishingPriceBrutto };
}

/**
 * Aktualizuje wiersz wykończenia w sekcji options-summary
 */
function updateFinishingSummaryRow(form, finishingType, finishingVariant, priceNetto, priceBrutto) {
    if (!form) return;

    const optionsSummary = form.querySelector('.finishing-options-summary');
    const finishingRow = optionsSummary?.querySelector('.finishing-row');

    if (!finishingRow) return;

    // Jeśli surowe lub brak ceny - ukryj wiersz
    if (finishingType === 'Surowe' || !priceBrutto || priceBrutto <= 0) {
        finishingRow.style.display = 'none';
        updateOptionsSummaryVisibility(optionsSummary);
        return;
    }

    // Buduj opis wykończenia - użyj pełnej ścieżki z dynamicznego drzewka
    let description = form.dataset.finishingFullPath || finishingType;

    // Aktualizuj tekst i cenę
    const textEl = finishingRow.querySelector('.finishing-summary-text');
    const priceEl = finishingRow.querySelector('.finishing-summary-price');
    let priceNettoEl = finishingRow.querySelector('.finishing-summary-price-netto');

    // Jeśli element netto nie istnieje, utwórz go dynamicznie
    if (!priceNettoEl) {
        const content = finishingRow.querySelector('.options-summary-content');
        if (content) {
            priceNettoEl = document.createElement('span');
            priceNettoEl.className = 'options-summary-price-netto finishing-summary-price-netto';
            content.appendChild(priceNettoEl);
        }
    }

    if (textEl) textEl.textContent = '';
    if (priceEl) priceEl.textContent = `${priceBrutto.toFixed(2)} PLN brutto`;
    if (priceNettoEl) priceNettoEl.textContent = `${priceNetto.toFixed(2)} PLN netto`;

    // Pokaż wiersz
    finishingRow.style.display = 'flex';
    updateOptionsSummaryVisibility(optionsSummary);

}

/**
 * Aktualizuje widoczność kontenera options-summary
 */
function updateOptionsSummaryVisibility(optionsSummary) {
    if (!optionsSummary) return;

    const row = optionsSummary.querySelector('.options-summary-row');
    const rowVisible = row && row.style.display !== 'none';

    optionsSummary.style.display = rowVisible ? 'flex' : 'none';
}

/**
 * Resetuje wykończenie dla formularza
 */
function resetFinishing(form) {
    if (!form) return;

    // Resetuj drzewko wykończeń - usuń wszystkie poziomy poniżej 0
    const container = form.querySelector('.finishing-tree-container');
    if (container) {
        const allLevels = container.querySelectorAll('.finishing-level');
        allLevels.forEach(level => {
            if (parseInt(level.dataset.level) > 0) {
                level.remove();
            }
        });

        // Na poziomie 0: odznacz wszystkie i zaznacz "Surowe" (pierwszy przycisk)
        const level0Buttons = container.querySelectorAll('.finishing-level[data-level="0"] .finishing-option-btn');
        level0Buttons.forEach(btn => btn.classList.remove('active'));
        const firstBtn = level0Buttons[0];
        if (firstBtn) {
            firstBtn.classList.add('active');
        }
    }

    // Wyczyść dataset
    form.dataset.finishingBrutto = 0;
    form.dataset.finishingNetto = 0;
    form.dataset.finishingType = 'Surowe';
    form.dataset.finishingVariant = '';
    form.dataset.finishingColor = '';

    // Ukryj wiersz wykończenia w options-summary
    const optionsSummary = form.querySelector('.finishing-options-summary');
    const finishingRow = optionsSummary?.querySelector('.finishing-row');
    if (finishingRow) {
        finishingRow.style.display = 'none';
    }
    updateOptionsSummaryVisibility(optionsSummary);

    // Przelicz i odśwież
    updateGlobalSummary();
    generateProductsSummary();

}

/**
 * Podpina listenery wykończeń do inputów formularza (wymiary, ilość)
 */
function attachFinishingListenersToForm(form) {
    if (!form) return;
    const inputs = form.querySelectorAll(
        'input[data-field="length"], input[data-field="width"], input[data-field="thickness"], input[data-field="quantity"]'
    );
    inputs.forEach(input => {
        input.addEventListener('input', () => calculateFinishingCost(form));
    });

    form.querySelectorAll('.finishing-btn').forEach(btn => {
        btn.addEventListener('click', () => calculateFinishingCost(form));
    });
}

/**
 * Pobiera opis wariantu z formularza
 */
function getVariantDescription(form) {
    if (!form) return null;

    const variant = form.querySelector('.variants input[type="radio"]:checked');
    if (!variant) return null;

    // Znajdź label dla tego radio button
    const label = form.querySelector(`label[for="${variant.id}"]`);
    if (label) {
        // Usuń tag "BRAK" jeśli istnieje i pobierz czysty tekst
        return label.textContent.replace(/BRAK/g, '').trim();
    }

    // Fallback - tłumacz kod na czytelną nazwę
    const variantNames = {
        'dab-lity-ab': 'Dąb lity A/B',
        'dab-lity-bb': 'Dąb lity B/B',
        'dab-micro-ab': 'Dąb mikrowczep A/B',
        'dab-micro-bb': 'Dąb mikrowczep B/B',
        'jes-lity-ab': 'Jesion lity A/B',
        'jes-micro-ab': 'Jesion mikrowczep A/B',
        'buk-lity-ab': 'Buk lity A/B',
        'buk-micro-ab': 'Buk mikrowczep A/B'
    };

    return variantNames[variant.value] || variant.value;
}

/**
 * Pobiera opis wykończenia z formularza
 */
function getFinishingDescription(form) {
    if (!form) return null;

    const finishingTypeBtn = form.querySelector('.finishing-btn[data-finishing-type].active');
    const finishingVariantBtn = form.querySelector('.finishing-btn[data-finishing-variant].active');

    if (!finishingTypeBtn || finishingTypeBtn.dataset.finishingType === 'Surowe') {
        return null;
    }

    let description = finishingTypeBtn.dataset.finishingType;

    if (finishingVariantBtn) {
        description += ` ${finishingVariantBtn.dataset.finishingVariant}`;

        // Dodaj kolor jeśli jest wybrany i wariant jest barwny
        if (finishingVariantBtn.dataset.finishingVariant === 'Barwne') {
            const colorBtn = form.querySelector('.color-btn.active');
            if (colorBtn) {
                const color = colorBtn.dataset.finishingColor;
                if (color) {
                    description += ` (${color})`;
                }
            }
        }
    }

    return description;
}

/**
 * Pobiera opis wykończenia z uwzględnieniem połysku (z form.dataset)
 */
function getFinishingDescriptionWithGloss(form) {
    if (!form) return null;

    // ✅ Pobierz dane z form.dataset (zapisane przez updateSelectedFinishing)
    const finishingType = form.dataset.finishingType;
    const finishingVariant = form.dataset.finishingVariant;
    const finishingColor = form.dataset.finishingColor;

    // Jeśli brak wykończenia lub wybrano "Surowe"
    if (!finishingType || finishingType === 'Surowe') {
        return null;
    }

    // Rozpocznij od głównego typu (np. "Lakierowanie", "Olejowanie")
    let description = finishingType;

    // Dodaj wariant jeśli istnieje (np. "Bezbarwne", "Barwne")
    if (finishingVariant) {
        const variantLower = finishingVariant.toLowerCase();
        description += ` ${variantLower}`;
    }

    // Dodaj kolor jeśli istnieje (np. "Orzech 22-74")
    if (finishingColor) {
        description += ` ${finishingColor}`;
    }

    return description;
}

/**
 * Generuje opis produktu z cenami
 * Nowy schemat: [gatunek] | [technologia] | [klasa] | [wymiary] | [wykończenie] | [obróbka krawędzi] | [liczba sztuk]
 */
function generateProductDescription(form, index) {
    if (!form) return { main: `Błąd formularza`, sub: "" };

    const isComplete = checkProductCompleteness(form);
    const isOutOfRange = form.dataset.outOfRange === "true";

    if (isOutOfRange) {
        return { main: `Produkt poza zakresem`, sub: "" };
    }

    if (!isComplete) {
        return { main: `Dokończ wycenę produktu`, sub: "" };
    }

    const length = form.querySelector('[data-field="length"]')?.value;
    const width = form.querySelector('[data-field="width"]')?.value;
    const thickness = form.querySelector('[data-field="thickness"]')?.value;
    const quantity = form.querySelector('[data-field="quantity"]')?.value;

    // Pobierz zaznaczony wariant i parsuj variant_code
    const variantRadio = form.querySelector('.variants input[type="radio"]:checked');
    const variantCode = variantRadio ? variantRadio.value : '';

    // Parsuj variant_code (np. "dab-lity-ab" → Dąb, Lity, A/B)
    let species = '';
    let technology = '';
    let woodClass = '';

    if (variantCode) {
        const parts = variantCode.split('-');

        // Gatunek drewna
        const speciesMap = {
            'dab': 'Dąb',
            'jes': 'Jesion',
            'buk': 'Buk'
        };
        species = speciesMap[parts[0]] || parts[0];

        // Technologia
        const techMap = {
            'lity': 'Lity',
            'micro': 'Mikrowczep'
        };
        technology = techMap[parts[1]] || parts[1];

        // Klasa (np. "ab" → "A/B")
        woodClass = parts[2] ? parts[2].toUpperCase().split('').join('/') : '';
    }

    // Dodaj wykończenie z stopniem połysku
    const finishingDescription = getFinishingDescriptionWithGloss(form);

    // Pobierz dane obróbki krawędzi
    const edgesType = form.dataset.edgesType;
    const edgesRValue = form.dataset.edgesRValue;
    const edgesAngleValue = form.dataset.edgesAngleValue;
    let edgesDescription = '';
    if (edgesType && edgesRValue) {
        const edgeTypeLabel = edgesType === 'chamfer' ? 'Fazowanie' : 'Zaokrąglenie';
        edgesDescription = `${edgeTypeLabel} R${edgesRValue}`;

        // Dodaj kąt dla fazowania
        if (edgesType === 'chamfer' && edgesAngleValue) {
            edgesDescription += ` ${edgesAngleValue}°`;
        }
    }

    // Buduj główny opis według nowego schematu
    // Format: Dąb mikrowczep A/B 100×40×4 cm | Wykończenie | Obróbka krawędzi | Ilość
    let mainParts = [];

    // Część 1: Gatunek + technologia + klasa + wymiary (bez separatorów między nimi)
    let basicInfo = [];
    if (form.dataset.productShape === 'round') mainParts.push('Okrągły');
    if (species) basicInfo.push(species);
    if (technology) basicInfo.push(technology);
    if (woodClass) basicInfo.push(woodClass);
    basicInfo.push(`${length}×${width}×${thickness} cm`);
    mainParts.push(basicInfo.join(' '));

    // Część 2: Wykończenie (lub "Surowy" jeśli brak)
    mainParts.push(finishingDescription || 'Surowy');

    // Część 3: Obróbka krawędzi (opcjonalna)
    if (edgesDescription) {
        mainParts.push(edgesDescription);
    }

    // Część 4: Ilość
    mainParts.push(`${quantity} szt.`);

    const mainDescription = mainParts.join(' | ');

    // ===================================================================
    // Oblicz objętość, wagę i ceny dla informacji dodatkowych
    // ===================================================================
    const volume = calculateProductVolume(form);
    const weight = calculateProductWeight(form);

    // Pobierz ceny z dataset formularza (cena surowa + wykończenie + krawędzie)
    const orderBrutto = parseFloat(form.dataset.orderBrutto) || 0;
    const orderNetto = parseFloat(form.dataset.orderNetto) || 0;
    const finishingBrutto = parseFloat(form.dataset.finishingBrutto) || 0;
    const finishingNetto = parseFloat(form.dataset.finishingNetto) || 0;
    const edgesBrutto = parseFloat(form.dataset.edgesBrutto) || 0;
    const edgesNetto = parseFloat(form.dataset.edgesNetto) || 0;

    // Oblicz całkowite ceny (surowe + wykończenie + krawędzie)
    const totalBrutto = orderBrutto + finishingBrutto + edgesBrutto;
    const totalNetto = orderNetto + finishingNetto + edgesNetto;

    // Formatuj ceny
    const bruttoText = totalBrutto > 0 ? `${totalBrutto.toFixed(2)} PLN brutto` : '';
    const nettoText = totalNetto > 0 ? `${totalNetto.toFixed(2)} PLN netto` : '';

    // Zbuduj tekst dodatkowy
    let subDescription = '';

    if (volume > 0) {
        subDescription = `${formatVolume(volume)} | ${formatWeight(weight)}`;

        // Dodaj ceny jeśli są dostępne
        if (totalBrutto > 0 && totalNetto > 0) {
            subDescription += ` | ${bruttoText} | ${nettoText}`;
        }
    }

    return { main: mainDescription, sub: subDescription };
}

/**
 * Generuje panel produktów (podsumowanie wszystkich produktów w wycenie)
 */
function generateProductsSummary() {
    if (!productSummaryContainer) return;

    const forms = Array.from(quoteFormsContainer.querySelectorAll('.quote-form'));
    productSummaryContainer.innerHTML = '';

    // POPRAWKA: Znajdź główny kontener bezpiecznie
    const summaryMainContainer = productSummaryContainer.parentElement ||
        document.querySelector('.products-summary-main');

    // Usuń istniejące podsumowanie jeśli istnieje
    if (summaryMainContainer) {
        const existingSummary = summaryMainContainer.querySelector('.products-total-summary');
        if (existingSummary) {
            existingSummary.remove();
        }
    }

    if (forms.length === 0) {
        productSummaryContainer.innerHTML = '<div class="no-products">Brak produktów</div>';
        return;
    }

    forms.forEach((form, index) => {
        const descriptionData = generateProductDescription(form, index);
        const isComplete = checkProductCompleteness(form);
        const isOutOfRange = form.dataset.outOfRange === "true";
        const isActive = form === activeQuoteForm;

        const productCard = document.createElement('div');
        productCard.className = `product-card ${isActive ? 'active' : ''} ${(!isComplete || isOutOfRange) ? 'error' : ''}`;
        productCard.dataset.index = index;

        // Przycisk usuwania gdy jest więcej niż 1 produkt
        const removeButton = forms.length > 1 ? `
            <button class="remove-product-btn" data-index="${index}" title="Usuń produkt">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        ` : '';

        const actionsHtml = `
            <div class="product-card-actions">
                <button class="duplicate-product-btn" data-index="${index}" title="Duplikuj produkt">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
                ${removeButton}
            </div>`;

        if (descriptionData.sub) {
            productCard.innerHTML = `
                <div class="product-card-header">
                    <div class="product-card-number">${index + 1}</div>
                    <div class="product-card-main-info">${descriptionData.main}</div>
                </div>
                <div class="product-card-footer">
                    <div class="product-card-sub-info">${descriptionData.sub}</div>
                    ${actionsHtml}
                </div>
            `;
        } else {
            productCard.innerHTML = `
                <div class="product-card-header">
                    <div class="product-card-number">${index + 1}</div>
                    <div class="product-card-main-info">${descriptionData.main}</div>
                    ${actionsHtml}
                </div>
            `;
        }

        // POPRAWKA: Dodaj listener NATYCHMIAST po utworzeniu elementu
        productCard.addEventListener('click', (e) => {
            // Nie przełączaj jeśli kliknięto przycisk usuwania lub duplikowania
            if (e.target.closest('.remove-product-btn') || e.target.closest('.duplicate-product-btn')) return;
            activateProductCard(index);
        });

        productSummaryContainer.appendChild(productCard);
    });

    // Obrys sekcji na czerwono jeśli jest niedokończony produkt
    if (summaryMainContainer) {
        const hasError = forms.some(f => !checkProductCompleteness(f) || f.dataset.outOfRange === "true");
        summaryMainContainer.classList.toggle('has-error', hasError);
    }

    // Podsumowanie objętości i wagi — zawsze widoczne na dole
    const { totalVolume, totalWeight } = calculateTotalVolumeAndWeight();

    if (summaryMainContainer) {
        const summaryCard = document.createElement('div');
        summaryCard.className = 'products-total-summary';
        summaryCard.innerHTML = `
            <div class="products-total-title">Łącznie:</div>
            <div class="products-total-details">
                <span class="products-total-volume">${formatVolume(totalVolume)}</span>
                <span class="products-total-weight">${formatWeight(totalWeight)}</span>
            </div>
        `;
        summaryMainContainer.appendChild(summaryCard);
    }

    // POPRAWKA: Dodaj event listeners FUNKCJĄ DELEGUJĄCĄ aby uniknąć problemów
    attachProductCardListeners();

    // Aktualizuj stan przycisków
    updateCalculateDeliveryButtonState();
}

// ========================================
// EKSPORT FUNKCJI DO GLOBALNEGO ZAKRESU
// ========================================

window.calculateFinishingCost = calculateFinishingCost;
window.resetFinishing = resetFinishing;

window.CalculatorUI = {
    initShapeToggle,
    loadFinishingPrices,
    renderFinishingTree,
    renderFinishingOptions,
    setupFinishingTreeHandlers,
    updateSelectedFinishing,
    toggleTheme,
    attachFinishingUIListeners,
    calculateFinishingCost,
    updateFinishingSummaryRow,
    updateOptionsSummaryVisibility,
    resetFinishing,
    attachFinishingListenersToForm,
    getVariantDescription,
    getFinishingDescription,
    getFinishingDescriptionWithGloss,
    generateProductDescription,
    generateProductsSummary
};
