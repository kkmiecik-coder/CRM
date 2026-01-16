console.log("[public_tracking.js] załadowany!");

document.addEventListener("DOMContentLoaded", () => {
    console.log("[public_tracking.js] DOMContentLoaded");

    window._sessionData = {
        start: Date.now(),
        inputs: {},
        variant: null,
        finishing: null,
        color: null
    };

    function sendSession() {
        const payload = {
            inputs: window._sessionData.inputs,
            variant: window._sessionData.variant,
            finishing: window._sessionData.finishing,
            color: window._sessionData.color,
            duration_ms: Date.now() - window._sessionData.start
        };

        console.log("[public_tracking] Wysyłam sesję do backendu:");
        console.table(payload);

        fetch("/log_session_public", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).catch(err => console.warn("❌ Błąd zapisu sesji:", err));
    }

    // Inputy
    ["length", "width", "thickness", "quantity"].forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener("change", () => {
                window._sessionData.inputs[id] = input.value;
                console.log(`[public_tracking] Zmieniono input: ${id} → ${input.value}`);
            });
        }
    });

    // Warianty – dynamiczne
    const observer = new MutationObserver(() => {
        document.querySelectorAll(".variants input[type='radio']").forEach(radio => {
            if (!radio.dataset.listenerAttached) {
                radio.addEventListener("change", () => {
                    window._sessionData.variant = radio.value;
                    console.log(`[public_tracking] Wybrano wariant: ${radio.value}`);
                    sendSession();
                });
                radio.dataset.listenerAttached = "true";
            }
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    // Wykończenie – przyciski z data-finishing-type
    document.querySelectorAll(".finishing-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const type = btn.dataset.finishingType;
            if (type) {
                window._sessionData.finishing = type;
                console.log(`[public_tracking] Wybrano wykończenie: ${type}`);
            }

            const variant = btn.dataset.finishingVariant;
            if (variant) {
                window._sessionData.variant = variant;
                console.log(`[public_tracking] Wybrano wariant: ${variant}`);
            }
        });
    });

    // Kolor – klik na przycisk z kolorem
    document.querySelectorAll("button.color-btn[data-finishing-color]").forEach(btn => {
        btn.addEventListener("click", () => {
            const color = btn.dataset.finishingColor || btn.innerText.trim();
            window._sessionData.color = color;
            console.log(`[public_tracking] Wybrano kolor: ${color}`);
        });
    });

    // Ostatnia szansa
    window.addEventListener("beforeunload", () => {
        if (
            window._sessionData.variant ||
            Object.keys(window._sessionData.inputs).length > 0 ||
            window._sessionData.finishing ||
            window._sessionData.color
        ) {
            const payload = {
                inputs: window._sessionData.inputs,
                variant: window._sessionData.variant,
                finishing: window._sessionData.finishing,
                color: window._sessionData.color,
                duration_ms: Date.now() - window._sessionData.start
            };
            console.log("[public_tracking] Wysyłam sesję przez navigator.sendBeacon:");
            console.table(payload);

            navigator.sendBeacon("/log_session_public", JSON.stringify(payload));
        }
    });
});
