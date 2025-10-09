// modules/analytics/static/js/sales_analytics.js

/**
 * SALES ANALYTICS - Moduł zakładki sprzedaży
 * Obsługuje: KPI, trendy, popularne produkty, wykresy
 */

class SalesAnalytics {
    constructor() {
        this.data = {
            kpi: null,
            trends: null,
            products: null
        };
        this.charts = {
            salesTrend: null
        };
        this.isInitialized = false;

        this.init();
    }

    init() {
        console.log('[SalesAnalytics] Inicjalizacja...');

        this.setupEventListeners();
        this.isInitialized = true;

        console.log('[SalesAnalytics] Gotowe!');
    }

    /**
     * Ładowanie danych sprzedażowych
     */
    async loadData() {
        console.log('[SalesAnalytics] Ładowanie danych...');

        try {
            const response = await fetch('/analytics/data/sales');
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania danych sprzedaży');
            }

            this.data.kpi = result.kpi;
            this.data.trends = result.trends;
            this.data.products = result.popular_products;

            this.updateKPICards();
            this.updateTrendsChart();
            this.updateProductsTable();

            console.log('[SalesAnalytics] Dane załadowane:', this.data);

        } catch (error) {
            console.error('[SalesAnalytics] Błąd ładowania:', error);
            this.showError('Nie można załadować danych sprzedaży: ' + error.message);
        }
    }

    /**
     * Aktualizacja KPI cards
     */
    updateKPICards() {
        if (!this.data.kpi) return;

        const kpi = this.data.kpi;

        // Miesięczna wartość
        const monthlyValue = document.getElementById('sales-monthly-value');
        if (monthlyValue) {
            monthlyValue.textContent = window.AnalyticsUtils.formatCurrency(kpi.monthly_value);
        }

        // Konwersja Accepted
        const conversionAccepted = document.getElementById('sales-conversion-accepted');
        if (conversionAccepted) {
            conversionAccepted.textContent = window.AnalyticsUtils.formatPercent(kpi.conversion_accepted);
            conversionAccepted.className = window.AnalyticsUtils.getConversionClass(kpi.conversion_accepted);
        }

        // Konwersja Baselinker
        const conversionBaselinker = document.getElementById('sales-conversion-baselinker');
        if (conversionBaselinker) {
            conversionBaselinker.textContent = window.AnalyticsUtils.formatPercent(kpi.conversion_baselinker);
            conversionBaselinker.className = window.AnalyticsUtils.getConversionClass(kpi.conversion_baselinker);
        }

        // Średnia wartość oferty
        const avgDeal = document.getElementById('sales-avg-deal');
        if (avgDeal) {
            avgDeal.textContent = window.AnalyticsUtils.formatCurrency(kpi.avg_deal_value);
        }

        console.log('[SalesAnalytics] KPI cards zaktualizowane');
    }

    /**
     * Aktualizacja wykresu trendów
     */
    updateTrendsChart() {
        if (!this.data.trends) return;

        const canvas = document.getElementById('salesTrendChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        // Zniszcz poprzedni wykres
        if (this.charts.salesTrend) {
            this.charts.salesTrend.destroy();
        }

        // Przygotuj dane
        const labels = this.data.trends.map(item => item.month);
        const valuesData = this.data.trends.map(item => item.total_value);
        const quotesData = this.data.trends.map(item => item.quotes_count);

        // Konfiguracja wykresu
        const config = {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Wartość ofert (PLN)',
                        data: valuesData,
                        borderColor: '#ED6B24',
                        backgroundColor: 'rgba(237, 107, 36, 0.1)',
                        yAxisID: 'y',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Liczba ofert',
                        data: quotesData,
                        borderColor: '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.1)',
                        yAxisID: 'y1',
                        tension: 0.4
                    }
                ]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {
                            display: true,
                            text: 'Wartość (PLN)'
                        },
                        ticks: {
                            callback: function (value) {
                                return window.AnalyticsUtils.formatCurrency(value);
                            }
                        }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {
                            display: true,
                            text: 'Liczba ofert'
                        },
                        grid: {
                            drawOnChartArea: false,
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Miesiąc'
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const datasetLabel = context.dataset.label;
                                const value = context.raw;

                                if (datasetLabel.includes('Wartość')) {
                                    return `${datasetLabel}: ${window.AnalyticsUtils.formatCurrency(value)}`;
                                } else {
                                    return `${datasetLabel}: ${window.AnalyticsUtils.formatNumber(value)}`;
                                }
                            }
                        }
                    }
                }
            }
        };

        this.charts.salesTrend = new Chart(ctx, config);

        console.log('[SalesAnalytics] Wykres trendów zaktualizowany');
    }

    /**
     * Aktualizacja tabeli produktów
     */
    updateProductsTable() {
        if (!this.data.products) return;

        const tbody = document.querySelector('#popular-products-table tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (this.data.products.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="analytics-empty-state">
                        <div class="empty-icon">📦</div>
                        <h3>Brak danych o produktach</h3>
                        <p>Nie znaleziono żadnych produktów w ofertach.</p>
                    </td>
                </tr>
            `;
            return;
        }

        this.data.products.forEach((product, index) => {
            const row = document.createElement('tr');

            // Bezpieczne tłumaczenie produktu
            let translatedName = product.variant_code;
            if (window.ProductTranslator) {
                const translated = window.ProductTranslator.translateCode(product.variant_code);
                if (translated !== product.variant_code) {
                    translatedName = `${translated}`;
                } else {
                    translatedName = translated;
                }
            }

            row.innerHTML = `
                <td>
                    <strong>${translatedName}</strong>
                </td>
                <td>
                    <span class="analytics-badge badge-info">
                        ${window.AnalyticsUtils.formatNumber(product.usage_count)}
                    </span>
                </td>
                <td>
                    ${window.AnalyticsUtils.formatCurrency(product.avg_price_m3)}
                </td>
                <td>
                    ${window.AnalyticsUtils.formatNumber(product.total_volume, 3)} m³
                </td>
                <td>
                    <span class="analytics-tooltip" data-tooltip="Długość x Szerokość x Grubość">
                        ${product.avg_dimensions} cm
                    </span>
                </td>
            `;

            tbody.appendChild(row);
        });

        console.log('[SalesAnalytics] Tabela produktów zaktualizowana');
    }

    /**
     * Event listeners
     */
    setupEventListeners() {
        // Selektor miesięcy dla trendów
        const monthsSelect = document.getElementById('sales-months-select');
        if (monthsSelect) {
            monthsSelect.addEventListener('change', (e) => {
                const months = parseInt(e.target.value);
                this.loadTrendsData(months);
            });
        }

        console.log('[SalesAnalytics] Event listeners skonfigurowane');
    }

    /**
     * Ładowanie trendów z parametrem miesięcy
     */
    async loadTrendsData(months = 12) {
        console.log(`[SalesAnalytics] Ładowanie trendów dla ${months} miesięcy...`);

        try {
            const response = await fetch(`/analytics/api/sales/trends?months=${months}`);
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania trendów');
            }

            this.data.trends = result.trends;
            this.updateTrendsChart();

            console.log(`[SalesAnalytics] Trendy załadowane dla ${months} miesięcy`);

        } catch (error) {
            console.error('[SalesAnalytics] Błąd ładowania trendów:', error);
            this.showError('Nie można załadować trendów: ' + error.message);
        }
    }

    /**
     * Wyświetlanie błędów
     */
    showError(message) {
        console.error(`[SalesAnalytics] ${message}`);

        // Pokaż błąd w interfejsie
        const errorDiv = document.createElement('div');
        errorDiv.className = 'analytics-error alert alert-danger';
        errorDiv.innerHTML = `
            <strong>Błąd:</strong> ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;

        const salesTab = document.getElementById('sales-analytics');
        if (salesTab) {
            salesTab.insertBefore(errorDiv, salesTab.firstChild);
        }
    }

    /**
     * Odświeżenie danych
     */
    async refresh() {
        console.log('[SalesAnalytics] Odświeżanie danych...');
        await this.loadData();
    }

    /**
     * Cleanup przy przełączaniu zakładek
     */
    cleanup() {
        // Zniszcz wykresy
        Object.values(this.charts).forEach(chart => {
            if (chart) {
                chart.destroy();
            }
        });

        this.charts = {
            salesTrend: null
        };

        console.log('[SalesAnalytics] Cleanup wykonany');
    }

    /**
     * Pobierz dane do exportu
     */
    getExportData() {
        return {
            kpi: this.data.kpi,
            trends: this.data.trends,
            products: this.data.products
        };
    }
}

/**
 * Inicjalizacja
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[SalesAnalytics] Inicjalizacja modułu...');

    window.SalesAnalytics = new SalesAnalytics();

    console.log('[SalesAnalytics] Moduł gotowy!');
});