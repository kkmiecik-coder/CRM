// public_analytics.js

document.addEventListener("DOMContentLoaded", () => {
    fetch("/analytics/data")
        .then(res => {
            console.log("[analytics] Fetch status:", res.status);
            return res.text(); // <-- najpierw raw text
        })
        .then(text => {
            console.log("[analytics] Response preview:", text.slice(0, 200)); // tylko początek
            return JSON.parse(text);
        })
        .then(data => {
            renderChart("variantChart", data.variants);
            renderChart("finishingChart", data.finishings);
            renderChart("dimensionChart", data.dimensions);
            renderChart("colorChart", data.colors);
        })
        .catch(err => console.error("[analytics] Błąd ładowania danych:", err));
});

function renderChart(canvasId, chartData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: "bar",
        data: {
            labels: chartData.labels,
            datasets: [{
                label: chartData.label,
                data: chartData.values,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    console.log("[analytics] JS ready");

    const tabs = document.querySelectorAll(".analytics-sub-tab");
    const charts = document.querySelectorAll(".analytics-sub-chart");

    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            const targetId = tab.dataset.target;

            // Dezaktywuj wszystkie taby
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");

            // Ukryj wszystkie wykresy
            charts.forEach(chart => chart.classList.remove("visible"));

            // Pokaż wybrany
            const targetChart = document.getElementById(targetId);
            if (targetChart) {
                targetChart.classList.add("visible");
            }
        });
    });
});