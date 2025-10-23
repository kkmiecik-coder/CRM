// modules/public_calculator/static/js/public_calculator.js

console.log("[public_calculator.js] załadowany!");

document.addEventListener("DOMContentLoaded", () => {
    const prices = JSON.parse(document.getElementById("prices-data")?.textContent || "[]");

    // pobieranie mnożnika z routingu:
    const priceMultiplier = parseFloat(document.getElementById("price-multiplier")?.textContent || "1.3");

    const variants = [
        { species: "Dąb", technology: "Lity", wood_class: "A/B" },
        { species: "Dąb", technology: "Lity", wood_class: "B/B" },
        { species: "Dąb", technology: "Mikrowczep", wood_class: "A/B" },
        { species: "Dąb", technology: "Mikrowczep", wood_class: "B/B" },
        { species: "Jesion", technology: "Lity", wood_class: "A/B" },
        { species: "Buk", technology: "Lity", wood_class: "A/B" }
    ];

    const finishingCosts = {
        Brak: 0,
        Lakierowanie: { Bezbarwne: 200, Barwne: 250 },
        Olejowanie: 300  // Olejowanie ma jedną stałą cenę
    };

    const qtyInput = document.getElementById("quantity");
    document.getElementById("qtyPlus").addEventListener("click", () => {
        qtyInput.value = parseInt(qtyInput.value || "1") + 1;
        calculate();
    });
    document.getElementById("qtyMinus").addEventListener("click", () => {
        if (parseInt(qtyInput.value) > 1) {
            qtyInput.value = parseInt(qtyInput.value || "1") - 1;
            calculate();
        }
    });

    const fields = ["length", "width", "thickness"];
    fields.forEach(id => {
        const el = document.getElementById(id);
        el?.addEventListener("input", () => {
            validateField(id);
            calculate();
        });
    });

    document.querySelectorAll(".finishing-btn[data-finishing-type]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".finishing-btn[data-finishing-type]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            const type = btn.dataset.finishingType;
            const variantWrap = document.getElementById("finishing-variant-wrapper");
            const colorWrap = document.getElementById("finishing-color-wrapper");

            if (type === "Brak") {
                // Brak - ukryj wszystko
                if (variantWrap) variantWrap.style.display = "none";
                if (colorWrap) colorWrap.style.display = "none";
            } else if (type === "Lakierowanie") {
                // Lakierowanie - pokaż warianty
                if (variantWrap) variantWrap.style.display = "block";
                const variantActive = document.querySelector(".finishing-btn.active[data-finishing-variant]")?.dataset.finishingVariant;
                if (variantActive === "Barwne") {
                    if (colorWrap) colorWrap.style.display = "block";
                } else {
                    if (colorWrap) colorWrap.style.display = "none";
                }
            } else if (type === "Olejowanie") {
                // Olejowanie - ukryj warianty i kolory
                if (variantWrap) variantWrap.style.display = "none";
                if (colorWrap) colorWrap.style.display = "none";
            }

            calculate();
        });
    });

    document.querySelectorAll(".finishing-btn[data-finishing-variant]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".finishing-btn[data-finishing-variant]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            const variant = btn.dataset.finishingVariant;
            const colorWrap = document.getElementById("finishing-color-wrapper");

            if (variant === "Barwne") {
                if (colorWrap) colorWrap.style.display = "block";
            } else {
                if (colorWrap) colorWrap.style.display = "none";
            }

            calculate();
        });
    });

    document.querySelectorAll(".color-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".color-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            calculate();
        });
    });

    function validateField(field) {
        const el = document.getElementById(field);
        const existingMsg = el.nextElementSibling;
        if (existingMsg?.classList.contains("validation-msg")) {
            existingMsg.remove();
        }

        let valid = true;
        let message = "";
        const val = parseFloat(el.value.replace(',', '.'));
        if (field === "length" && (val < 1 || val > 500)) {
            valid = false;
            message = "Dostępny zakres: 1–500 cm";
        }
        if (field === "width" && (val < 1 || val > 120)) {
            valid = false;
            message = "Dostępny zakres: 1–120 cm";
        }
        if (field === "thickness" && (val < 1 || val > 8)) {
            valid = false;
            message = "Dostępny zakres: 1–8 cm";
        }

        if (!valid) {
            const msg = document.createElement("div");
            msg.className = "validation-msg";
            msg.style.color = "#C00000";
            msg.style.fontSize = "13px";
            msg.style.marginTop = "4px";
            msg.textContent = message;
            el.insertAdjacentElement("afterend", msg);
        }
    }

    function roundUpThickness(val) {
        const raw = String(val).replace(',', '.');
        const num = parseFloat(raw);
        if (isNaN(num)) return null;
        if (Number.isInteger(num)) return num;
        return Math.ceil(num);
    }

    function calculateSurfaceArea(l, w, t, q) {
        const l_m = l / 100;
        const w_m = w / 100;
        const t_m = t / 100;
        const area = 2 * (l_m * w_m + l_m * t_m + w_m * t_m);
        return area * q;
    }

    function calculate() {
        const l = parseFloat(document.getElementById("length")?.value.replace(',', '.'));
        const w = parseFloat(document.getElementById("width")?.value.replace(',', '.'));
        const tRaw = document.getElementById("thickness")?.value;

        if (!tRaw || tRaw.trim() === '') {
            return;
        }

        const t = parseFloat(tRaw.replace(',', '.'));
        const q = parseInt(qtyInput?.value || "1");

        if (isNaN(l) || isNaN(w) || isNaN(t) || isNaN(q)) {
            return;
        }

        const isOutOfRange = l > 450 || w > 120 || t > 8;
        const tRounded = roundUpThickness(t);
        const vol = (l / 100) * (w / 100) * (tRounded / 100);
        const lRounded = Math.ceil(l);

        const finishingType = document.querySelector(".finishing-btn.active[data-finishing-type]")?.dataset.finishingType || "Brak";
        const finishingVariant = document.querySelector(".finishing-btn.active[data-finishing-variant]")?.dataset.finishingVariant || null;

        let finishingCostPerM2 = 0;
        let hasFinishing = false;

        if (finishingType === "Olejowanie") {
            // Olejowanie ma stałą cenę
            finishingCostPerM2 = finishingCosts[finishingType];
            hasFinishing = true;
        } else if (finishingType === "Lakierowanie" && finishingVariant) {
            // Lakierowanie wymaga wybrania wariantu
            finishingCostPerM2 = finishingCosts[finishingType][finishingVariant];
            hasFinishing = true;
        }

        const totalArea = calculateSurfaceArea(l, w, tRounded, q);
        const totalFinishingCost = finishingCostPerM2 * totalArea;
        const totalFinishingCostBrutto = totalFinishingCost * 1.23;

        // Pokaż sekcję wyliczeń i disclaimer
        const calcSection = document.getElementById("calculationsSection");
        const disclaimer = document.getElementById("priceDisclaimer");
        if (calcSection) {
            calcSection.classList.add("visible");
        }
        if (disclaimer) {
            disclaimer.style.display = "block";
        }

        const container = document.getElementById("variantsContainer");
        container.innerHTML = "";

        // Buduj HTML dla tabeli desktop i kart mobile
        let tableHTML = `
            <table class="results-table">
                <thead>
                    <tr>
                        <th>Wariant produktu</th>
                        <th>Cena za 1 szt. (surowa)</th>
                        ${q > 1 ? `<th>Cena za ${q} szt. (surowe)</th>` : ''}
                        ${hasFinishing ? '<th>Koszt wykończenia</th>' : ''}
                        <th>Suma za cały produkt</th>
                    </tr>
                </thead>
                <tbody>
        `;

        let mobileHTML = '<div class="mobile-cards">';

        variants.forEach(v => {
            const title = `${v.species} ${v.technology} ${v.wood_class}`;

            if (isOutOfRange) {
                // Desktop - wiersz z brakiem ceny
                tableHTML += `
                    <tr class="no-price-row">
                        <td colspan="${3 + (q > 1 ? 1 : 0) + (hasFinishing ? 1 : 0)}">
                            <div class="variant-name-cell" style="margin-bottom: 4px;">${title}</div>
                            <div class="no-price-text">Brak ceny dla podanych parametrów</div>
                        </td>
                    </tr>
                `;

                // Mobile - karta z brakiem ceny
                mobileHTML += `
                    <div class="variant-card">
                        <div class="variant-card-header">${title}</div>
                        <div class="no-price-text">Brak ceny dla podanych parametrów</div>
                    </div>
                `;
                return;
            }

            const match = prices.find(p =>
                p.species === v.species &&
                p.technology === v.technology &&
                p.wood_class === v.wood_class &&
                tRounded >= p.thickness_min &&
                tRounded <= p.thickness_max &&
                lRounded >= p.length_min &&
                lRounded <= p.length_max
            );

            if (!match) {
                // Desktop - wiersz z brakiem ceny
                tableHTML += `
                    <tr class="no-price-row">
                        <td colspan="${3 + (q > 1 ? 1 : 0) + (hasFinishing ? 1 : 0)}">
                            <div class="variant-name-cell" style="margin-bottom: 4px;">${title}</div>
                            <div class="no-price-text">Brak ceny dla podanych parametrów</div>
                        </td>
                    </tr>
                `;

                // Mobile - karta z brakiem ceny
                mobileHTML += `
                    <div class="variant-card">
                        <div class="variant-card-header">${title}</div>
                        <div class="no-price-text">Brak ceny dla podanych parametrów</div>
                    </div>
                `;
            } else {
                const netto = match.price_per_m3 * vol * priceMultiplier;
                const brutto = netto * 1.23;
                const totalNetto = netto * q;
                const totalBrutto = brutto * q;

                // Oblicz sumę końcową
                const finalTotalNetto = totalNetto + totalFinishingCost;
                const finalTotalBrutto = totalBrutto + totalFinishingCostBrutto;

                // Desktop - wiersz z cenami
                tableHTML += `
                    <tr>
                        <td>
                            <div class="variant-name-cell">${title}</div>
                        </td>
                        <td>
                            <div class="price-cell">
                                <span class="price-brutto">${brutto.toFixed(2)} zł</span>
                                <span class="price-netto">${netto.toFixed(2)} zł netto</span>
                            </div>
                        </td>
                        ${q > 1 ? `
                            <td>
                                <div class="price-cell">
                                    <span class="price-brutto">${totalBrutto.toFixed(2)} zł</span>
                                    <span class="price-netto">${totalNetto.toFixed(2)} zł netto</span>
                                </div>
                            </td>
                        ` : ''}
                        ${hasFinishing ? `
                            <td>
                                <div class="price-cell">
                                    <span class="price-brutto">${totalFinishingCostBrutto.toFixed(2)} zł</span>
                                    <span class="price-netto">${totalFinishingCost.toFixed(2)} zł netto</span>
                                </div>
                            </td>
                        ` : ''}
                        <td>
                            <div class="price-cell total-price">
                                <span class="price-brutto">${finalTotalBrutto.toFixed(2)} zł</span>
                                <span class="price-netto">${finalTotalNetto.toFixed(2)} zł netto</span>
                            </div>
                        </td>
                    </tr>
                `;

                // Mobile - karta z cenami
                mobileHTML += `
                    <div class="variant-card">
                        <div class="variant-card-header">${title}</div>
                        
                        <div class="card-row">
                            <span class="card-label">Cena za 1 szt. (surowa):</span>
                            <div class="card-value">
                                <div class="price-cell">
                                    <span class="price-brutto">${brutto.toFixed(2)} zł</span>
                                    <span class="price-netto">${netto.toFixed(2)} zł netto</span>
                                </div>
                            </div>
                        </div>
                        
                        ${q > 1 ? `
                            <div class="card-row">
                                <span class="card-label">Cena za ${q} szt. (surowe):</span>
                                <div class="card-value">
                                    <div class="price-cell">
                                        <span class="price-brutto">${totalBrutto.toFixed(2)} zł</span>
                                        <span class="price-netto">${totalNetto.toFixed(2)} zł netto</span>
                                    </div>
                                </div>
                            </div>
                        ` : ''}
                        
                        ${hasFinishing ? `
                            <div class="card-row">
                                <span class="card-label">Koszt wykończenia:</span>
                                <div class="card-value">
                                    <div class="price-cell">
                                        <span class="price-brutto">${totalFinishingCostBrutto.toFixed(2)} zł</span>
                                        <span class="price-netto">${totalFinishingCost.toFixed(2)} zł netto</span>
                                    </div>
                                </div>
                            </div>
                        ` : ''}
                        
                        <div class="card-total-row">
                            <div class="card-row">
                                <span class="card-label"><strong>Suma za cały produkt:</strong></span>
                                <div class="card-value">
                                    <div class="price-cell">
                                        <span class="price-brutto">${finalTotalBrutto.toFixed(2)} zł</span>
                                        <span class="price-netto">${finalTotalNetto.toFixed(2)} zł netto</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }
        });

        tableHTML += '</tbody></table>';
        mobileHTML += '</div>';

        // Wstaw oba układy
        container.innerHTML = tableHTML + mobileHTML;
    }

    // Inicjalna kalkulacja przy załadowaniu
    calculate();
});