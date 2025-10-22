// modules/public_calculator/static/js/public_calculator.js

console.log("[public_calculator.js] załadowany!");

document.addEventListener("DOMContentLoaded", () => {
    const prices = JSON.parse(document.getElementById("prices-data")?.textContent || "[]");

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
        Olejowanie: { Bezbarwne: 300, Barwne: 350 }
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
            const glossWrap = document.getElementById("finishing-gloss-wrapper");
            const finishingSummary = document.getElementById("finishingSummary");

            if (type === "Brak") {
                if (variantWrap) variantWrap.style.display = "none";
                if (colorWrap) colorWrap.style.display = "none";
                if (glossWrap) glossWrap.style.display = "none";
                if (finishingSummary) {
                    finishingSummary.innerHTML = "";
                    finishingSummary.style.display = "none";
                }
            } else {
                if (variantWrap) variantWrap.style.display = "block";
                const variantActive = document.querySelector(".finishing-btn.active[data-finishing-variant]")?.dataset.finishingVariant;
                if (variantActive === "Barwne") {
                    if (colorWrap) colorWrap.style.display = "block";
                    if (glossWrap) glossWrap.style.display = "block";
                } else {
                    if (colorWrap) colorWrap.style.display = "none";
                    if (glossWrap) glossWrap.style.display = "none";
                }
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
            const glossWrap = document.getElementById("finishing-gloss-wrapper");

            if (variant === "Barwne") {
                if (colorWrap) colorWrap.style.display = "block";
                if (glossWrap) glossWrap.style.display = "block";
            } else {
                if (colorWrap) colorWrap.style.display = "none";
                if (glossWrap) glossWrap.style.display = "none";
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

    document.querySelectorAll(".finishing-btn[data-finishing-gloss]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".finishing-btn[data-finishing-gloss]").forEach(b => b.classList.remove("active"));
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

        // Sprawdź czy są dane do obliczenia
        if (!tRaw || tRaw.trim() === '') {
            return; // Nic nie rób jeśli brak danych
        }

        const t = parseFloat(tRaw.replace(',', '.'));
        const q = parseInt(qtyInput?.value || "1");

        // Sprawdź czy dane są liczbami
        if (isNaN(l) || isNaN(w) || isNaN(t) || isNaN(q)) {
            return; // Nic nie rób jeśli nieprawidłowe dane
        }

        // Sprawdź zakres - jeśli poza zakresem, wyświetl "Brak ceny"
        const isOutOfRange = l > 450 || w > 120 || t > 8;

        const tRounded = roundUpThickness(t);
        const vol = (l / 100) * (w / 100) * (tRounded / 100);
        const lRounded = Math.ceil(l);

        const finishingType = document.querySelector(".finishing-btn.active[data-finishing-type]")?.dataset.finishingType || "Brak";
        const finishingVariant = document.querySelector(".finishing-btn.active[data-finishing-variant]")?.dataset.finishingVariant || null;

        let finishingCost = 0;
        if (finishingType !== "Brak" && finishingVariant && finishingCosts[finishingType]?.[finishingVariant]) {
            finishingCost = finishingCosts[finishingType][finishingVariant];
        }

        const totalArea = calculateSurfaceArea(l, w, tRounded, q);

        const container = document.getElementById("variantsContainer");
        container.innerHTML = "";

        variants.forEach(v => {
            const div = document.createElement("div");
            div.className = "variant-result";
            const title = `${v.species} ${v.technology} ${v.wood_class}`;

            // Jeśli poza zakresem, od razu wyświetl "Brak ceny"
            if (isOutOfRange) {
                div.innerHTML = `<p class='variant-title' style="font-size: 18px; font-weight: 600; color: #ED6B24;">${title}</p><p>Brak ceny</p>`;
                container.appendChild(div);
                return;
            }

            // Szukaj w cenniku
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
                div.innerHTML = `<p class='variant-title' style="font-size: 18px; font-weight: 600; color: #ED6B24;">${title}</p><p>Brak ceny</p>`;
            } else {
                const netto = match.price_per_m3 * vol * 1.1;
                const brutto = netto * 1.23;
                const totalNetto = netto * q;
                const totalBrutto = brutto * q;

                div.innerHTML = `
                    <p class='variant-title' style="font-size: 18px; font-weight: 600; color: #ED6B24;">${title}</p>
                    <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: bold; margin-bottom: 4px;">
                        <span>Cena za 1 szt. surową</span>
                        <span style="text-align: left;">Cena za ${q} szt. surowych</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 13px;">
                        <span>${brutto.toFixed(2)} PLN brutto</span>
                        <span style="text-align: left;">${totalBrutto.toFixed(2)} PLN brutto</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 13px;">
                        <span>${netto.toFixed(2)} PLN netto</span>
                        <span style="text-align: left;">${totalNetto.toFixed(2)} PLN netto</span>
                    </div>
                `;
            }

            container.appendChild(div);
        });

        const finishingSummary = document.getElementById("finishingSummary");
        if (finishingSummary) {
            if (finishingType === "Brak" || !finishingVariant || isOutOfRange) {
                finishingSummary.innerHTML = "";
            } else {
                const totalFinishingPrice = finishingCost * totalArea;
                finishingSummary.innerHTML = `
                    <div class='variant-result'>
                        <p class='variant-title' style="font-size: 18px; font-weight: 600; color: #ED6B24;">Całkowity koszt wykończenia za ${q} szt.</p>
                        <p style="font-size: 13px;">${totalFinishingPrice.toFixed(2)} PLN</p>
                    </div>
                `;
            }
        }

        // Pokaż disclaimer zawsze gdy są wyświetlone jakiekolwiek wyniki
        const disclaimer = document.getElementById("priceDisclaimer");
        if (disclaimer) {
            disclaimer.style.display = "block";
        }
    }

    calculate();
});