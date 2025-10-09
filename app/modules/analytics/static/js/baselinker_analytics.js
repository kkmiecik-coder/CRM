// modules/analytics/static/js/baselinker_analytics.js

/**
 * BASELINKER ANALYTICS - Moduł zakładki Baselinker
 * Obsługuje: KPI Baselinker, konwersję statusów, logi, wykresy
 */

class BaselinkerAnalytics {
    constructor() {
        this.data = {
            baselinker: null
        };
        this.charts = {
            statusConversion: null
        };
        this.isInitialized = false;

        this.init();
    }

    init() {
        console.log('[BaselinkerAnalytics] Inicjalizacja...');

        this.setupEventListeners();
        this.isInitialized = true;

        console.log('[BaselinkerAnalytics] Gotowe!');
    }

    /**
     * Ładowanie danych Baselinker
     */
    async loadData() {
        console.log('[BaselinkerAnalytics] Ładowanie danych Baselinker...');

        try {
            const response = await fetch('/analytics/data/baselinker');
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania danych Baselinker');
            }

            this.data.baselinker = result.baselinker;

            this.updateKPICards();
            this.updateStatusConversionChart();
            this.updateLogsTable();

            console.log('[BaselinkerAnalytics] Dane Baselinker załadowane:', this.data);

        } catch (error) {
            console.error('[BaselinkerAnalytics] Błąd ładowania:', error);
            this.showError('Nie można załadować danych Baselinker: ' + error.message);
        }
    }

    /**
     * Aktualizacja KPI cards
     */
    updateKPICards() {
        if (!this.data.baselinker) return;

        const bl = this.data.baselinker;

        // Total Orders
        const totalOrders = document.getElementById('baselinker-total-orders');
        if (totalOrders) {
            totalOrders.textContent = window.AnalyticsUtils.formatNumber(bl.total_orders);
        }

        // Conversion Rate
        const conversionRate = document.getElementById('baselinker-conversion-rate');
        if (conversionRate) {
            conversionRate.textContent = window.AnalyticsUtils.formatPercent(bl.conversion_rate);
            conversionRate.className = window.AnalyticsUtils.getConversionClass(bl.conversion_rate);
        }

        // Success Rate
        const successRate = document.getElementById('baselinker-success-rate');
        if (successRate) {
            successRate.textContent = window.AnalyticsUtils.formatPercent(bl.logs_stats.success_rate);
            successRate.className = window.AnalyticsUtils.getConversionClass(bl.logs_stats.success_rate);
        }

        // Errors
        const errors = document.getElementById('baselinker-errors');
        if (errors) {
            errors.textContent = window.AnalyticsUtils.formatNumber(bl.logs_stats.errors);

            // Dodaj klasę zależnie od liczby błędów
            if (bl.logs_stats.errors === 0) {
                errors.className = 'status-success';
            } else if (bl.logs_stats.errors < 5) {
                errors.className = 'status-warning';
            } else {
                errors.className = 'status-error';
            }
        }

        console.log('[BaselinkerAnalytics] KPI cards zaktualizowane');
    }

    /**
     * Aktualizacja wykresu konwersji według statusów
     */
    updateStatusConversionChart() {
        if (!this.data.baselinker || !this.data.baselinker.status_conversion) return;

        const canvas = document.getElementById('statusConversionChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.statusConversion) {
            this.charts.statusConversion.destroy();
        }

        // Przygotuj dane
        const statusData = this.data.baselinker.status_conversion;
        const labels = statusData.map(item => item.status_name);
        const conversionRates = statusData.map(item => item.conversion_rate);
        const totalQuotes = statusData.map(item => item.total_quotes);
        const baselinkerOrders = statusData.map(item => item.baselinker_orders);

        const config = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Konwersja (%)',
                        data: conversionRates,
                        backgroundColor: 'rgba(237, 107, 36, 0.8)',
                        borderColor: '#ED6B24',
                        borderWidth: 1,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Liczba ofert',
                        data: totalQuotes,
                        backgroundColor: 'rgba(0, 123, 255, 0.6)',
                        borderColor: '#007bff',
                        borderWidth: 1,
                        yAxisID: 'y1',
                        type: 'line',
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        min: 0,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Konwersja (%)'
                        },
                        ticks: {
                            callback: function (value) {
                                return value + '%';
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
                            text: 'Status oferty'
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top'
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const dataIndex = context.dataIndex;
                                const status = statusData[dataIndex];

                                if (context.datasetIndex === 0) {
                                    return [
                                        `Konwersja: ${context.parsed.y}%`,
                                        `Zamówienia: ${status.baselinker_orders}`,
                                        `Oferty: ${status.total_quotes}`
                                    ];
                                } else {
                                    return `Liczba ofert: ${context.parsed.y}`;
                                }
                            }
                        }
                    }
                }
            }
        };

        this.charts.statusConversion = new Chart(ctx, config);

        console.log('[BaselinkerAnalytics] Wykres konwersji statusów zaktualizowany');
    }

    /**
     * Aktualizacja tabeli logów
     */
    updateLogsTable() {
        if (!this.data.baselinker || !this.data.baselinker.recent_logs) return;

        const tbody = document.querySelector('#baselinker-logs-table tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (this.data.baselinker.recent_logs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="analytics-empty-state">
                        <div class="empty-icon">🔗</div>
                        <h3>Brak logów Baselinker</h3>
                        <p>Nie znaleziono żadnych akcji Baselinker w ostatnim czasie.</p>
                    </td>
                </tr>
            `;
            return;
        }

        this.data.baselinker.recent_logs.forEach((log, index) => {
            const row = document.createElement('tr');

            // Format daty
            const formattedDate = window.AnalyticsUtils.formatDate(log.created_at, 'datetime');

            // Status badge
            const statusClass = window.AnalyticsUtils.getStatusClass(log.status);
            let statusText = log.status;
            let statusIcon = '';

            switch (log.status.toLowerCase()) {
                case 'success':
                case 'successful':
                    statusIcon = '✅';
                    statusText = 'Sukces';
                    break;
                case 'error':
                    statusIcon = '❌';
                    statusText = 'Błąd';
                    break;
                case 'pending':
                    statusIcon = '⏳';
                    statusText = 'Oczekuje';
                    break;
                default:
                    statusIcon = '❓';
                    break;
            }

            // Action translation
            let actionText = log.action;
            switch (log.action.toLowerCase()) {
                case 'create_order':
                    actionText = 'Tworzenie zamówienia';
                    break;
                case 'update_order':
                    actionText = 'Aktualizacja zamówienia';
                    break;
                case 'get_order':
                    actionText = 'Pobieranie zamówienia';
                    break;
                default:
                    actionText = log.action;
                    break;
            }

            row.innerHTML = `
                <td>
                    <span class="analytics-tooltip" data-tooltip="${formattedDate}">
                        ${window.AnalyticsUtils.formatDate(log.created_at)}
                    </span>
                </td>
                <td>
                    <a href="/quotes/${log.quote_id}" target="_blank" class="quote-link">
                        Oferta #${log.quote_id}
                    </a>
                </td>
                <td>
                    <span class="action-badge">
                        ${actionText}
                    </span>
                </td>
                <td>
                    <span class="analytics-badge ${statusClass}">
                        ${statusIcon} ${statusText}
                    </span>
                </td>
                <td>
                    ${log.error_message ?
                    `<span class="error-message analytics-tooltip" data-tooltip="${log.error_message}">
                            ${window.AnalyticsUtils.truncateText(log.error_message, 40)}
                        </span>` :
                    '<span class="text-muted">-</span>'
                }
                </td>
            `;

            tbody.appendChild(row);
        });

        console.log('[BaselinkerAnalytics] Tabela logów zaktualizowana');
    }

    /**
     * Event listeners
     */
    setupEventListeners() {
        // Możesz dodać event listenery dla filtrowania logów, refresh itp.
        console.log('[BaselinkerAnalytics] Event listeners skonfigurowane');
    }

    /**
     * Wyświetlanie błędów
     */
    showError(message) {
        console.error(`[BaselinkerAnalytics] ${message}`);

        const errorDiv = document.createElement('div');
        errorDiv.className = 'analytics-error alert alert-danger';
        errorDiv.innerHTML = `
            <strong>Błąd:</strong> ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;

        const baselinkerTab = document.getElementById('baselinker-analytics');
        if (baselinkerTab) {
            baselinkerTab.insertBefore(errorDiv, baselinkerTab.firstChild);
        }
    }

    /**
     * Odświeżenie danych
     */
    async refresh() {
        console.log('[BaselinkerAnalytics] Odświeżanie danych...');
        await this.loadData();
    }

    /**
     * Cleanup przy przełączaniu zakładek
     */
    cleanup() {
        Object.values(this.charts).forEach(chart => {
            if (chart) {
                chart.destroy();
            }
        });

        this.charts = {
            statusConversion: null
        };

        console.log('[BaselinkerAnalytics] Cleanup wykonany');
    }

    /**
     * Pobierz dane do exportu
     */
    getExportData() {
        return {
            baselinker: this.data.baselinker
        };
    }
}

/**
 * Inicjalizacja
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[BaselinkerAnalytics] Inicjalizacja modułu...');

    window.BaselinkerAnalytics = new BaselinkerAnalytics();

    console.log('[BaselinkerAnalytics] Moduł gotowy!');
});