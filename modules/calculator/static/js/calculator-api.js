// calculator-api.js
// Komunikacja z backendowym silnikiem wycen (POST /calculator/api/calculate).
// Frontend NIE liczy cen — zbiera parametry, wysyła (debounce 1 s), renderuje wynik.

(function () {
    const DEBOUNCE_MS = 1000;
    let debounceTimer = null;
    let requestSeq = 0;          // guard: odrzucamy odpowiedzi starsze niż ostatnie żądanie
    let abortController = null;

    function buildProductPayload(form, index) {
        const val = sel => parseFloat(form.querySelector(`input[data-field="${sel}"]`)?.value);
        let edges = null;
        try { edges = form.dataset.edgesData ? JSON.parse(form.dataset.edgesData) : null; }
        catch (e) { edges = null; }
        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
        return {
            index: index + 1,
            length: val('length'),
            width: val('width'),
            thickness: val('thickness'),
            quantity: parseInt(form.querySelector('input[data-field="quantity"]')?.value) || null,
            shape: form.dataset.productShape || 'rectangular',
            shape_data: form.dataset.shapeData || null,
            holes_count: parseInt(form.dataset.shapeHolesCount || '0', 10),
            selected_variant: selectedRadio ? selectedRadio.value : null,
            finishing_type: form.dataset.finishingType || 'Surowe',
            finishing_variant: form.dataset.finishingVariant || null,
            finishing_gloss_level: form.dataset.finishingGloss || null,
            finishing_option_id: form.dataset.finishingOptionId
                ? parseInt(form.dataset.finishingOptionId) : null,
            finishing_full_path: form.dataset.finishingFullPath || null,
            edges: edges,
            edges_mode: form.dataset.edgesMode || null,
        };
    }

    function buildCalculatePayload() {
        const core = window.CalculatorCore;
        const forms = Array.from(core.quoteFormsContainer.querySelectorAll('.quote-form'));
        const clientTypeEl = core.activeQuoteForm
            ? core.activeQuoteForm.querySelector('select[data-field="clientType"]') : null;
        const payload = { products: forms.map(buildProductPayload) };
        const isFlexiblePartner = document.body.dataset.flexiblePartner === 'true';
        if (core.isPartner && !isFlexiblePartner) {
            payload.multiplier = core.userMultiplier;   // partner fixed
        } else {
            payload.client_type = clientTypeEl ? clientTypeEl.value : null;
        }
        return payload;
    }

    /**
     * Ustawia tekst "Obliczam..." we wszystkich miejscach cen — wołane od razu
     * przy zmianie pola (jeszcze w oknie debounce), nie dopiero przy wysyłce.
     * Idempotentne: kolejne zmiany pól w oknie debounce nie migoczą.
     */
    function showCalculatingState() {
        const core = window.CalculatorCore;
        if (!core || !core.quoteFormsContainer) return;
        const CALCULATING = 'Obliczam...';

        const forms = Array.from(core.quoteFormsContainer.querySelectorAll('.quote-form'));
        forms.forEach(form => {
            form.querySelectorAll('.unit-brutto, .unit-netto, .total-brutto, .total-netto').forEach(span => {
                span.textContent = CALCULATING;
            });
            form.querySelectorAll('.finishing-brutto, .finishing-netto').forEach(span => {
                span.textContent = CALCULATING;
            });
        });

        [core.orderSummaryEls, core.finishingSummaryEls, core.finalSummaryEls].forEach(els => {
            if (!els) return;
            if (els.brutto) els.brutto.textContent = CALCULATING;
            if (els.netto) els.netto.textContent = CALCULATING;
        });
    }

    function applyVariantResult(form, variantResult) {
        const radio = form.querySelector(`.variants input[type="radio"][value="${variantResult.variant_code}"]`);
        if (!radio) return;
        const variant = radio.closest('div');
        const spans = {
            unitBrutto: variant?.querySelector('.unit-brutto'),
            unitNetto: variant?.querySelector('.unit-netto'),
            totalBrutto: variant?.querySelector('.total-brutto'),
            totalNetto: variant?.querySelector('.total-netto'),
        };
        if (!variantResult.available) {
            Object.values(spans).forEach(s => { if (s) s.textContent = 'Brak ceny'; });
            delete radio.dataset.totalNetto;
            delete radio.dataset.totalBrutto;
            delete radio.dataset.pricePerM3;
            delete radio.dataset.volumeM3;
            delete radio.dataset.multiplier;
            delete radio.dataset.finalPrice;
            return;
        }
        radio.dataset.totalNetto = variantResult.total_netto;
        radio.dataset.totalBrutto = variantResult.total_brutto;
        radio.dataset.volumeM3 = variantResult.volume_m3;
        radio.dataset.pricePerM3 = variantResult.price_per_m3;
        radio.dataset.multiplier = variantResult.multiplier;
        radio.dataset.finalPrice = variantResult.unit_netto;
        const fmt = window.CalculatorCore.formatPLN;
        if (spans.unitBrutto) spans.unitBrutto.textContent = fmt(variantResult.unit_brutto);
        if (spans.unitNetto) spans.unitNetto.textContent = fmt(variantResult.unit_netto);
        if (spans.totalBrutto) spans.totalBrutto.textContent = fmt(variantResult.total_brutto);
        if (spans.totalNetto) spans.totalNetto.textContent = fmt(variantResult.total_netto);
    }

    function applyProductResult(form, productResult) {
        if (productResult.errors && productResult.errors.length) {
            const msg = productResult.errors[0].message;
            window.showErrorForAllVariants(msg, form.querySelector('.variants'));
            form.dataset.orderBrutto = '';
            form.dataset.orderNetto = '';
            form.dataset.outOfRange = 'true';
            form.dataset.errorMessage = msg;
            return;
        }
        delete form.dataset.outOfRange;
        delete form.dataset.errorMessage;
        (productResult.variants || []).forEach(v => applyVariantResult(form, v));

        const selectedRadio = form.querySelector('.variants input[type="radio"]:checked');
        if (selectedRadio && selectedRadio.dataset.totalBrutto) {
            form.dataset.orderBrutto = selectedRadio.dataset.totalBrutto;
            form.dataset.orderNetto = selectedRadio.dataset.totalNetto;
        } else {
            form.dataset.orderBrutto = '';
            form.dataset.orderNetto = '';
        }

        const fmt = window.CalculatorCore.formatPLN;
        if (productResult.finishing) {
            form.dataset.finishingNetto = productResult.finishing.netto;
            form.dataset.finishingBrutto = productResult.finishing.brutto;
            // Teksty cząstkowe wykończenia (dziś liczone przez calculateFinishingCost) — utrzymujemy zgodność DOM
            const finishingBruttoEl = form.querySelector('.finishing-brutto') || document.getElementById('finishing-brutto');
            const finishingNettoEl = form.querySelector('.finishing-netto') || document.getElementById('finishing-netto');
            if (finishingBruttoEl) finishingBruttoEl.textContent = fmt(productResult.finishing.brutto);
            if (finishingNettoEl) finishingNettoEl.textContent = fmt(productResult.finishing.netto);

            // Wiersz podsumowania wykończenia w options-summary — funkcja przyjmuje gotowe ceny, nie liczy ich ponownie
            if (typeof window.updateFinishingSummaryRow === 'function') {
                const finishingType = form.dataset.finishingType || 'Surowe';
                const finishingVariant = form.dataset.finishingVariant || null;
                window.updateFinishingSummaryRow(
                    form, finishingType, finishingVariant,
                    productResult.finishing.netto, productResult.finishing.brutto
                );
            }
        }
        if (productResult.edges) {
            form.dataset.edgesNetto = productResult.edges.netto;
            form.dataset.edgesBrutto = productResult.edges.brutto;
        }

        // Podgląd SVG krawędzi po przeliczeniu (jeśli moduł krawędzi jest załadowany)
        if (window.EdgesModule && typeof window.EdgesModule.updateEdgesPreview === 'function') {
            window.EdgesModule.updateEdgesPreview(form);
        }
    }

    async function doRequest() {
        const core = window.CalculatorCore;
        const seq = ++requestSeq;
        if (abortController) abortController.abort();
        abortController = new AbortController();

        document.body.classList.add('prices-loading');  // wskaźnik "przeliczanie..."
        try {
            const response = await fetch('/calculator/api/calculate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildCalculatePayload()),
                signal: abortController.signal,
            });
            if (seq !== requestSeq) return;   // przyszła starsza odpowiedź — ignoruj
            const result = await response.json();
            const forms = Array.from(core.quoteFormsContainer.querySelectorAll('.quote-form'));
            (result.products || []).forEach(p => {
                const form = forms[p.index - 1];
                if (form) applyProductResult(form, p);
            });
            window.updateGlobalSummary();
            if (typeof window.generateProductsSummary === 'function') window.generateProductsSummary();
        } catch (e) {
            if (e.name !== 'AbortError') {
                console.error('[CalculatorApi] Błąd przeliczania:', e);
                // Nie zostawiaj wiszącego "Obliczam..." — przywróć stan zerowy/komunikat błędu
                const forms = Array.from(core.quoteFormsContainer.querySelectorAll('.quote-form'));
                forms.forEach(form => {
                    form.querySelectorAll('.unit-brutto, .unit-netto, .total-brutto, .total-netto').forEach(span => {
                        span.textContent = 'Błąd obliczeń';
                    });
                    form.querySelectorAll('.finishing-brutto, .finishing-netto').forEach(span => {
                        span.textContent = '0.00 PLN';
                    });
                });
                [core.orderSummaryEls, core.finishingSummaryEls, core.finalSummaryEls].forEach(els => {
                    if (!els) return;
                    if (els.brutto) els.brutto.textContent = '0.00 PLN';
                    if (els.netto) els.netto.textContent = '0.00 PLN';
                });
            }
        } finally {
            if (seq === requestSeq) document.body.classList.remove('prices-loading');
        }
    }

    function requestRecalculation(immediate) {
        clearTimeout(debounceTimer);
        showCalculatingState();   // "Obliczam..." od razu przy zmianie, nie dopiero przy wysyłce
        if (immediate) { doRequest(); return; }
        debounceTimer = setTimeout(doRequest, DEBOUNCE_MS);
    }

    window.CalculatorApi = { requestRecalculation, buildCalculatePayload };
})();
