// modules/analytics/static/js/team_analytics.js

/**
 * TEAM ANALYTICS - Moduł zakładki zespołu
 * Obsługuje: tabelę performance, wykresy porównawcze zespołu
 */

class TeamAnalytics {
    constructor() {
        this.data = {
            team_performance: null
        };
        this.charts = {
            teamQuotes: null,
            teamValue: null,
            teamConversion: null
        };
        this.isInitialized = false;

        this.init();
    }

    init() {
        console.log('[TeamAnalytics] Inicjalizacja...');

        this.setupEventListeners();
        this.isInitialized = true;

        console.log('[TeamAnalytics] Gotowe!');
    }

    /**
     * Ładowanie danych zespołu
     */
    async loadData() {
        console.log('[TeamAnalytics] Ładowanie danych zespołu...');

        try {
            const response = await fetch('/analytics/data/team');
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania danych zespołu');
            }

            this.data.team_performance = result.team_performance;

            this.updateTeamTable();
            this.updateTeamCharts();
            this.updateTeamSummary();

            console.log('[TeamAnalytics] Dane zespołu załadowane:', this.data);

        } catch (error) {
            console.error('[TeamAnalytics] Błąd ładowania:', error);
            this.showError('Nie można załadować danych zespołu: ' + error.message);
        }
    }

    /**
     * Aktualizacja tabeli zespołu
     */
    updateTeamTable() {
        if (!this.data.team_performance) return;

        const tbody = document.querySelector('#team-performance-table tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (this.data.team_performance.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="analytics-empty-state">
                        <div class="empty-icon">👥</div>
                        <h3>Brak danych o zespole</h3>
                        <p>Nie znaleziono żadnych użytkowników z ofertami.</p>
                    </td>
                </tr>
            `;
            return;
        }

        this.data.team_performance.forEach((user, index) => {
            const row = document.createElement('tr');

            // Ranking position
            const position = index + 1;
            let positionBadge = '';
            if (position === 1) positionBadge = '🥇';
            else if (position === 2) positionBadge = '🥈';
            else if (position === 3) positionBadge = '🥉';

            row.innerHTML = `
                <td>
                    <div class="user-info">
                        ${positionBadge}
                        <strong>${user.full_name}</strong>
                        <br>
                        <small class="text-muted">${user.email}</small>
                    </div>
                </td>
                <td>
                    <span class="analytics-badge badge-info">
                        ${window.AnalyticsUtils.formatNumber(user.quotes_count)}
                    </span>
                </td>
                <td>
                    <strong class="value-high">
                        ${window.AnalyticsUtils.formatCurrency(user.total_value)}
                    </strong>
                </td>
                <td>
                    ${window.AnalyticsUtils.formatCurrency(user.avg_value)}
                </td>
                <td>
                    <span class="${window.AnalyticsUtils.getConversionClass(user.conversion_accepted)}">
                        ${window.AnalyticsUtils.formatPercent(user.conversion_accepted)}
                    </span>
                    <div class="analytics-progress">
                        <div class="analytics-progress-bar ${this.getProgressBarClass(user.conversion_accepted)}" 
                             style="width: ${Math.min(user.conversion_accepted, 100)}%"></div>
                    </div>
                </td>
                <td>
                    <span class="${window.AnalyticsUtils.getConversionClass(user.conversion_baselinker)}">
                        ${window.AnalyticsUtils.formatPercent(user.conversion_baselinker)}
                    </span>
                    <div class="analytics-progress">
                        <div class="analytics-progress-bar ${this.getProgressBarClass(user.conversion_baselinker)}" 
                             style="width: ${Math.min(user.conversion_baselinker, 100)}%"></div>
                    </div>
                </td>
            `;

            tbody.appendChild(row);
        });

        console.log('[TeamAnalytics] Tabela zespołu zaktualizowana');
    }

    /**
     * Aktualizacja wykresów zespołu
     */
    updateTeamCharts() {
        if (!this.data.team_performance) return;

        this.updateQuotesChart();
        this.updateValueChart();
        this.updateConversionChart();

        console.log('[TeamAnalytics] Wykresy zespołu zaktualizowane');
    }

    /**
     * Wykres liczby ofert
     */
    updateQuotesChart() {
        const canvas = document.getElementById('teamQuotesChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.teamQuotes) {
            this.charts.teamQuotes.destroy();
        }

        // Przygotuj dane - top 10 użytkowników
        const topUsers = this.data.team_performance.slice(0, 10);
        const labels = topUsers.map(user => user.full_name);
        const quotesData = topUsers.map(user => user.quotes_count);

        const config = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Liczba ofert',
                    data: quotesData,
                    backgroundColor: 'rgba(237, 107, 36, 0.8)',
                    borderColor: '#ED6B24',
                    borderWidth: 1
                }]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                indexAxis: 'y', // Poziomy wykres słupkowy
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return `${context.parsed.x} ofert`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Liczba ofert'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Użytkownik'
                        }
                    }
                }
            }
        };

        this.charts.teamQuotes = new Chart(ctx, config);
    }

    /**
     * Wykres wartości
     */
    updateValueChart() {
        const canvas = document.getElementById('teamValueChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.teamValue) {
            this.charts.teamValue.destroy();
        }

        const topUsers = this.data.team_performance.slice(0, 10);
        const labels = topUsers.map(user => user.full_name);
        const valueData = topUsers.map(user => user.total_value);

        const config = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Wartość łączna (PLN)',
                    data: valueData,
                    backgroundColor: 'rgba(40, 167, 69, 0.8)',
                    borderColor: '#28a745',
                    borderWidth: 1
                }]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                indexAxis: 'y',
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return window.AnalyticsUtils.formatCurrency(context.parsed.x);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
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
                    y: {
                        title: {
                            display: true,
                            text: 'Użytkownik'
                        }
                    }
                }
            }
        };

        this.charts.teamValue = new Chart(ctx, config);
    }

    /**
     * Wykres konwersji
     */
    updateConversionChart() {
        const canvas = document.getElementById('teamConversionChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.teamConversion) {
            this.charts.teamConversion.destroy();
        }

        const topUsers = this.data.team_performance.slice(0, 10);
        const labels = topUsers.map(user => user.full_name);
        const acceptedData = topUsers.map(user => user.conversion_accepted);
        const baselinkerData = topUsers.map(user => user.conversion_baselinker);

        const config = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Konwersja Accepted (%)',
                        data: acceptedData,
                        backgroundColor: 'rgba(0, 123, 255, 0.8)',
                        borderColor: '#007bff',
                        borderWidth: 1
                    },
                    {
                        label: 'Konwersja Baselinker (%)',
                        data: baselinkerData,
                        backgroundColor: 'rgba(102, 16, 242, 0.8)',
                        borderColor: '#6610f2',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                scales: {
                    y: {
                        beginAtZero: true,
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
                    x: {
                        title: {
                            display: true,
                            text: 'Użytkownik'
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return `${context.dataset.label}: ${context.parsed.y}%`;
                            }
                        }
                    }
                }
            }
        };

        this.charts.teamConversion = new Chart(ctx, config);
    }

    /**
     * Aktualizacja podsumowania zespołu
     */
    updateTeamSummary() {
        const teamCount = document.getElementById('team-count');
        if (teamCount && this.data.team_performance) {
            const activeMembers = this.data.team_performance.filter(user => user.quotes_count > 0).length;
            const totalMembers = this.data.team_performance.length;

            teamCount.textContent = `${activeMembers} aktywnych z ${totalMembers} członków zespołu`;
        }
    }

    /**
     * Event listeners
     */
    setupEventListeners() {
        // Sub-tabs dla wykresów
        const subTabs = document.querySelectorAll('#team-analytics .analytics-sub-tab');
        const subCharts = document.querySelectorAll('#team-analytics .analytics-sub-chart');

        subTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetId = tab.getAttribute('data-target');

                // Dezaktywuj wszystkie sub-tabs
                subTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // Ukryj wszystkie wykresy
                subCharts.forEach(chart => chart.classList.remove('visible'));

                // Pokaż wybrany wykres
                const targetChart = document.getElementById(targetId);
                if (targetChart) {
                    targetChart.classList.add('visible');
                }
            });
        });

        console.log('[TeamAnalytics] Event listeners skonfigurowane');
    }

    /**
     * Pomocnicze funkcje
     */
    getProgressBarClass(value) {
        if (value >= 70) return 'success';
        if (value >= 40) return 'warning';
        return 'danger';
    }

    /**
     * Wyświetlanie błędów
     */
    showError(message) {
        console.error(`[TeamAnalytics] ${message}`);

        const errorDiv = document.createElement('div');
        errorDiv.className = 'analytics-error alert alert-danger';
        errorDiv.innerHTML = `
            <strong>Błąd:</strong> ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;

        const teamTab = document.getElementById('team-analytics');
        if (teamTab) {
            teamTab.insertBefore(errorDiv, teamTab.firstChild);
        }
    }

    /**
     * Odświeżenie danych
     */
    async refresh() {
        console.log('[TeamAnalytics] Odświeżanie danych...');
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
            teamQuotes: null,
            teamValue: null,
            teamConversion: null
        };

        console.log('[TeamAnalytics] Cleanup wykonany');
    }

    /**
     * Pobierz dane do exportu
     */
    getExportData() {
        return {
            team_performance: this.data.team_performance
        };
    }
}

/**
 * Inicjalizacja
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[TeamAnalytics] Inicjalizacja modułu...');

    window.TeamAnalytics = new TeamAnalytics();

    console.log('[TeamAnalytics] Moduł gotowy!');
});