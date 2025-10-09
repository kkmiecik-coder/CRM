// modules/analytics/static/js/clients_analytics.js
// POPRAWIONA WERSJA z obsługą błędów CORS i rate limiting

/**
 * CLIENTS ANALYTICS - Moduł zakładki klientów  
 * Obsługuje: top klientów, geografię, źródła, wykresy, mapę Polski
 * POPRAWKI: geokodowanie z cache, obsługa błędów CORS, fallback coordinates
 */

class ClientsAnalytics {
    constructor() {
        this.data = {
            top_clients: null,
            geography: null
        };
        this.charts = {
            cities: null,
            sources: null
        };
        this.map = null;
        this.isInitialized = false;
        this.currentLimit = 20;

        // NOWE: Cache geokodowania i fallback coordinates
        this.geocodeCache = new Map();
        this.rateLimitDelay = 1000; // 1 sekunda między zapytaniami
        this.maxRetries = 2;

        // Fallback coordinates dla popularnych miast Polski
        this.fallbackCoordinates = {
            'Warszawa': [52.2297, 21.0122],
            'Kraków': [50.0647, 19.9450],
            'Gdańsk': [54.3520, 18.6466],
            'Wrocław': [51.1079, 17.0385],
            'Poznań': [52.4064, 16.9252],
            'Łódź': [51.7592, 19.4560],
            'Katowice': [50.2649, 19.0238],
            'Szczecin': [53.4285, 14.5528],
            'Lublin': [51.2465, 22.5684],
            'Bydgoszcz': [53.1235, 18.0084],
            'Białystok': [53.1325, 23.1688],
            'Rzeszów': [50.0412, 21.9991],
            'Toruń': [53.0138, 18.5984]
        };

        this.init();
    }

    init() {
        console.log('[ClientsAnalytics] Inicjalizacja...');

        this.setupEventListeners();
        this.isInitialized = true;

        console.log('[ClientsAnalytics] Gotowe!');
    }

    /**
     * Ładowanie danych klientów
     */
    async loadData() {
        console.log('[ClientsAnalytics] Ładowanie danych klientów...');

        try {
            const response = await fetch('/analytics/data/clients');
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania danych klientów');
            }

            this.data.top_clients = result.top_clients;
            this.data.geography = result.geography;

            this.updateClientsTable();
            this.updateGeographyCharts();

            console.log('[ClientsAnalytics] Dane klientów załadowane:', this.data);

        } catch (error) {
            console.error('[ClientsAnalytics] Błąd ładowania:', error);
            this.showError('Nie można załadować danych klientów: ' + error.message);
        }
    }

    /**
     * Aktualizacja tabeli top klientów
     */
    updateClientsTable() {
        if (!this.data.top_clients) return;

        const tbody = document.querySelector('#top-clients-table tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        if (this.data.top_clients.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="analytics-empty-state">
                        <div class="empty-icon">👤</div>
                        <h3>Brak danych o klientach</h3>
                        <p>Nie znaleziono żadnych klientów z ofertami.</p>
                    </td>
                </tr>
            `;
            return;
        }

        this.data.top_clients.forEach((client, index) => {
            const row = document.createElement('tr');

            // Ranking position
            const position = index + 1;
            let positionBadge = '';
            if (position === 1) positionBadge = '🥇';
            else if (position === 2) positionBadge = '🥈';
            else if (position === 3) positionBadge = '🥉';

            row.innerHTML = `
                <td>
                    <div class="client-info">
                        ${positionBadge}
                        <strong>${window.AnalyticsUtils.truncateText(client.client_name, 30)}</strong>
                        <br>
                        <small class="text-muted">ID: ${client.client_id}</small>
                    </div>
                </td>
                <td>
                    <span class="analytics-tooltip" data-tooltip="Miasto dostawy">
                        📍 ${client.delivery_city}
                    </span>
                </td>
                <td>
                    <span class="analytics-badge badge-info">
                        ${client.source}
                    </span>
                </td>
                <td>
                    <span class="analytics-badge badge-success">
                        ${window.AnalyticsUtils.formatNumber(client.quotes_count)}
                    </span>
                </td>
                <td>
                    <strong class="value-high">
                        ${window.AnalyticsUtils.formatCurrency(client.total_value)}
                    </strong>
                    <br>
                    <small class="text-muted">
                        Śr: ${window.AnalyticsUtils.formatCurrency(client.avg_value)}
                    </small>
                </td>
                <td>
                    <span class="${window.AnalyticsUtils.getConversionClass(client.conversion_accepted)}">
                        ${window.AnalyticsUtils.formatPercent(client.conversion_accepted)}
                    </span>
                    <div class="analytics-progress">
                        <div class="analytics-progress-bar ${this.getProgressBarClass(client.conversion_accepted)}" 
                             style="width: ${Math.min(client.conversion_accepted, 100)}%"></div>
                    </div>
                </td>
                <td>
                    <span class="${window.AnalyticsUtils.getConversionClass(client.conversion_baselinker)}">
                        ${window.AnalyticsUtils.formatPercent(client.conversion_baselinker)}
                    </span>
                    <div class="analytics-progress">
                        <div class="analytics-progress-bar ${this.getProgressBarClass(client.conversion_baselinker)}" 
                             style="width: ${Math.min(client.conversion_baselinker, 100)}%"></div>
                    </div>
                </td>
            `;

            tbody.appendChild(row);
        });

        console.log('[ClientsAnalytics] Tabela klientów zaktualizowana');
    }

    /**
     * Aktualizacja wykresów geograficznych + MAPA
     */
    updateGeographyCharts() {
        if (!this.data.geography) return;

        this.updateCitiesChart();
        this.updateSourcesChart();
        this.updatePolandMap(); // POPRAWIONA MAPA POLSKI

        console.log('[ClientsAnalytics] Wykresy geograficzne i mapa zaktualizowane');
    }

    /**
     * MAPA POLSKI - POPRAWIONA FUNKCJA z obsługą błędów
     */
    updatePolandMap() {
        if (!this.data.geography || !this.data.geography.cities) return;

        // Sprawdź czy Leaflet jest dostępny
        if (typeof L === 'undefined') {
            console.warn('[ClientsAnalytics] Leaflet nie jest załadowany - mapa niedostępna');
            this.showMapError('Biblioteka mapy nie jest załadowana');
            return;
        }

        // Inicjalizuj mapę jeśli nie istnieje
        if (!this.map) {
            const mapContainer = document.getElementById('poland-map');
            if (!mapContainer) {
                console.warn('[ClientsAnalytics] Kontener mapy #poland-map nie istnieje');
                return;
            }

            try {
                this.map = L.map('poland-map').setView([52.0693, 19.4803], 6); // Centrum Polski

                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap contributors',
                    maxZoom: 18
                }).addTo(this.map);

                console.log('[ClientsAnalytics] Mapa Polski zainicjalizowana');
            } catch (error) {
                console.error('[ClientsAnalytics] Błąd inicjalizacji mapy:', error);
                this.showMapError('Nie można zainicjalizować mapy');
                return;
            }
        }

        // Wyczyść poprzednie markery
        this.map.eachLayer((layer) => {
            if (layer instanceof L.CircleMarker) {
                this.map.removeLayer(layer);
            }
        });

        // NOWE: Dodaj markery z opóźnieniem i obsługą błędów
        this.addMarkersWithDelay();

        console.log('[ClientsAnalytics] Markery miast dodane do mapy');
    }

    /**
     * NOWA FUNKCJA: Dodawanie markerów z opóźnieniem
     */
    async addMarkersWithDelay() {
        const cities = this.data.geography.cities;
        let successfulMarkers = 0;
        let failedMarkers = 0;

        console.log(`[ClientsAnalytics] Dodawanie ${cities.length} markerów...`);

        for (let i = 0; i < cities.length; i++) {
            const city = cities[i];

            try {
                await this.geocodeAndAddMarker(city);
                successfulMarkers++;

                // Opóźnienie między zapytaniami (rate limiting)
                if (i < cities.length - 1) {
                    await this.sleep(this.rateLimitDelay);
                }
            } catch (error) {
                failedMarkers++;
                console.warn(`[ClientsAnalytics] Nie udało się dodać markera dla ${city.city}:`, error.message);
            }
        }

        console.log(`[ClientsAnalytics] Markery dodane: ${successfulMarkers} sukces, ${failedMarkers} błędów`);

        // Pokaż summary jeśli są błędy
        if (failedMarkers > 0) {
            this.showMapWarning(`Nie udało się zlokalizować ${failedMarkers} miast na mapie`);
        }
    }

    /**
     * POPRAWIONE Geokodowanie i dodawanie markerów
     */
    async geocodeAndAddMarker(cityData) {
        const cityName = cityData.city;

        // Sprawdź cache
        if (this.geocodeCache.has(cityName)) {
            const coords = this.geocodeCache.get(cityName);
            if (coords) {
                this.addMarkerToMap(coords[0], coords[1], cityData);
                return;
            }
        }

        // Sprawdź fallback coordinates
        if (this.fallbackCoordinates[cityName]) {
            const coords = this.fallbackCoordinates[cityName];
            this.geocodeCache.set(cityName, coords);
            this.addMarkerToMap(coords[0], coords[1], cityData);
            console.log(`[ClientsAnalytics] Użyto fallback coordinates dla ${cityName}`);
            return;
        }

        // Spróbuj geokodowania z retry
        let lastError;
        for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
            try {
                const coords = await this.geocodeCityWithTimeout(cityName, 5000); // 5s timeout

                if (coords) {
                    this.geocodeCache.set(cityName, coords);
                    this.addMarkerToMap(coords[0], coords[1], cityData);
                    return;
                }
            } catch (error) {
                lastError = error;
                console.warn(`[ClientsAnalytics] Geokodowanie ${cityName} - próba ${attempt}/${this.maxRetries} nie powiodła się:`, error.message);

                if (attempt < this.maxRetries) {
                    await this.sleep(this.rateLimitDelay * attempt); // Zwiększaj opóźnienie
                }
            }
        }

        // Jeśli wszystkie próby się nie powiodły, zapisz w cache jako brak
        this.geocodeCache.set(cityName, null);
        throw new Error(`Nie udało się zlokalizować miasta ${cityName} po ${this.maxRetries} próbach: ${lastError?.message}`);
    }

    /**
     * NOWA FUNKCJA: Geokodowanie z timeout
     */
    async geocodeCityWithTimeout(cityName, timeout = 5000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            // Użyj proxy lub alternatywnego serwisu jeśli CORS jest problemem
            const response = await fetch(
                `https://nominatim.openstreetmap.org/search?format=json&country=Poland&city=${encodeURIComponent(cityName)}&limit=1`,
                {
                    headers: {
                        'User-Agent': 'WoodPowerCRM/1.0 (analytics@woodpower.pl)'
                    },
                    signal: controller.signal
                }
            );

            clearTimeout(timeoutId);

            if (!response.ok) {
                if (response.status === 429) {
                    throw new Error('Rate limit exceeded - zbyt wiele zapytań');
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const results = await response.json();

            if (results.length > 0) {
                const lat = parseFloat(results[0].lat);
                const lon = parseFloat(results[0].lon);
                return [lat, lon];
            }

            return null;

        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw new Error('Timeout - zapytanie trwało zbyt długo');
            }

            if (error.message.includes('CORS')) {
                throw new Error('CORS error - problem z cross-origin');
            }

            throw error;
        }
    }

    /**
     * NOWA FUNKCJA: Dodawanie markera do mapy
     */
    addMarkerToMap(lat, lon, cityData) {
        if (!this.map) return;

        try {
            const marker = L.circleMarker([lat, lon], {
                radius: this.getMarkerSize(cityData.quotes_count),
                fillColor: this.getMarkerColor(cityData.quotes_count),
                color: 'white',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8
            }).addTo(this.map);

            // Popup z informacjami o mieście
            marker.bindPopup(`
                <div class="map-popup">
                    <h4 style="margin: 0 0 8px 0; color: #ED6B24;">📍 ${cityData.city}</h4>
                    <div style="font-size: 13px; line-height: 1.4;">
                        <p style="margin: 4px 0;"><strong>Klienci:</strong> ${cityData.clients_count}</p>
                        <p style="margin: 4px 0;"><strong>Oferty:</strong> ${cityData.quotes_count}</p>
                        <p style="margin: 4px 0;"><strong>Wartość:</strong> ${window.AnalyticsUtils.formatCurrency(cityData.total_value)}</p>
                    </div>
                </div>
            `);

            // Tooltip na hover
            marker.bindTooltip(
                `${cityData.city}: ${cityData.quotes_count} ofert`,
                {
                    permanent: false,
                    direction: 'top',
                    className: 'city-tooltip'
                }
            );

        } catch (error) {
            console.error(`[ClientsAnalytics] Błąd dodawania markera dla ${cityData.city}:`, error);
        }
    }

    /**
     * Rozmiar markera na podstawie liczby ofert
     */
    getMarkerSize(quotesCount) {
        if (quotesCount >= 20) return 20;
        if (quotesCount >= 10) return 15;
        if (quotesCount >= 5) return 10;
        return 6;
    }

    /**
     * Kolor markera na podstawie liczby ofert
     */
    getMarkerColor(quotesCount) {
        if (quotesCount >= 20) return '#dc3545'; // Czerwony - bardzo dużo
        if (quotesCount >= 10) return '#ED6B24'; // Pomarańczowy - dużo
        if (quotesCount >= 5) return '#ffc107';  // Żółty - średnio
        return '#28a745'; // Zielony - mało
    }

    /**
     * Wykres top miast
     */
    updateCitiesChart() {
        const canvas = document.getElementById('citiesChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.cities) {
            this.charts.cities.destroy();
        }

        // Przygotuj dane - top 10 miast
        const topCities = this.data.geography.cities.slice(0, 10);
        const labels = topCities.map(city => city.city);
        const quotesData = topCities.map(city => city.quotes_count);

        const config = {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Liczba ofert',
                    data: quotesData,
                    backgroundColor: [
                        '#ED6B24',
                        '#007bff',
                        '#28a745',
                        '#ffc107',
                        '#dc3545',
                        '#6f42c1',
                        '#20c997',
                        '#fd7e14',
                        '#e83e8c',
                        '#6c757d'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            generateLabels: function (chart) {
                                const data = chart.data;
                                if (data.labels.length && data.datasets.length) {
                                    return data.labels.map((label, index) => {
                                        const value = data.datasets[0].data[index];
                                        const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
                                        const percentage = ((value / total) * 100).toFixed(1);

                                        return {
                                            text: `${label}: ${value} (${percentage}%)`,
                                            fillStyle: data.datasets[0].backgroundColor[index],
                                            index: index
                                        };
                                    });
                                }
                                return [];
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} ofert (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        };

        this.charts.cities = new Chart(ctx, config);
    }

    /**
     * Wykres źródeł klientów
     */
    updateSourcesChart() {
        const canvas = document.getElementById('sourcesChart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        if (this.charts.sources) {
            this.charts.sources.destroy();
        }

        const sources = this.data.geography.sources;
        const labels = sources.map(source => source.source);
        const quotesData = sources.map(source => source.quotes_count);

        const config = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Liczba ofert',
                    data: quotesData,
                    backgroundColor: 'rgba(0, 123, 255, 0.8)',
                    borderColor: '#007bff',
                    borderWidth: 1
                }]
            },
            options: {
                ...window.AnalyticsUtils.getChartDefaults(),
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return `${context.parsed.y} ofert`;
                            },
                            afterLabel: function (context) {
                                const source = sources[context.dataIndex];
                                return [
                                    `Klienci: ${source.clients_count}`,
                                    `Wartość: ${window.AnalyticsUtils.formatCurrency(source.total_value)}`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Liczba ofert'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Źródło'
                        }
                    }
                }
            }
        };

        this.charts.sources = new Chart(ctx, config);
    }

    /**
     * Event listeners
     */
    setupEventListeners() {
        // Selektor limitu klientów
        const limitSelect = document.getElementById('clients-limit-select');
        if (limitSelect) {
            limitSelect.addEventListener('change', (e) => {
                const limit = parseInt(e.target.value);
                this.loadClientsData(limit);
            });
        }

        // NOWY: Przycisk odświeżenia mapy
        this.addMapRefreshButton();

        console.log('[ClientsAnalytics] Event listeners skonfigurowane');
    }

    /**
     * NOWA FUNKCJA: Dodaj przycisk odświeżenia mapy
     */
    addMapRefreshButton() {
        const mapContainer = document.getElementById('poland-map');
        if (!mapContainer) return;

        const refreshButton = document.createElement('button');
        refreshButton.innerHTML = '🔄 Odśwież mapę';
        refreshButton.className = 'btn btn-sm btn-outline-primary map-refresh-btn';
        refreshButton.style.cssText = `
            position: absolute;
            top: 10px;
            right: 10px;
            z-index: 1000;
            font-size: 12px;
            padding: 4px 8px;
        `;

        refreshButton.addEventListener('click', () => {
            this.refreshMap();
        });

        mapContainer.style.position = 'relative';
        mapContainer.appendChild(refreshButton);
    }

    /**
     * NOWA FUNKCJA: Odśwież mapę
     */
    async refreshMap() {
        console.log('[ClientsAnalytics] Odświeżanie mapy...');

        // Wyczyść cache
        this.geocodeCache.clear();

        // Zaktualizuj mapę
        this.updatePolandMap();
    }

    /**
     * Ładowanie klientów z limitem
     */
    async loadClientsData(limit = 20) {
        console.log(`[ClientsAnalytics] Ładowanie klientów z limitem ${limit}...`);
        this.currentLimit = limit;

        try {
            const response = await fetch(`/analytics/api/clients/top?limit=${limit}`);
            const result = await response.json();

            if (!result.success) {
                throw new Error(result.error || 'Błąd ładowania klientów');
            }

            this.data.top_clients = result.clients;
            this.updateClientsTable();

            console.log(`[ClientsAnalytics] Klienci załadowani z limitem ${limit}`);

        } catch (error) {
            console.error('[ClientsAnalytics] Błąd ładowania klientów:', error);
            this.showError('Nie można załadować klientów: ' + error.message);
        }
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
     * Sleep utility
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Wyświetlanie błędów
     */
    showError(message) {
        console.error(`[ClientsAnalytics] ${message}`);

        const errorDiv = document.createElement('div');
        errorDiv.className = 'analytics-error alert alert-danger';
        errorDiv.innerHTML = `
            <strong>Błąd:</strong> ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;

        const clientsTab = document.getElementById('clients-analytics');
        if (clientsTab) {
            clientsTab.insertBefore(errorDiv, clientsTab.firstChild);
        }
    }

    /**
     * NOWA FUNKCJA: Wyświetlanie ostrzeżeń map
     */
    showMapWarning(message) {
        console.warn(`[ClientsAnalytics] ${message}`);

        const warningDiv = document.createElement('div');
        warningDiv.className = 'analytics-warning alert alert-warning';
        warningDiv.innerHTML = `
            <strong>Ostrzeżenie:</strong> ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;

        const mapBox = document.querySelector('#poland-map').closest('.analytics-box');
        if (mapBox) {
            mapBox.insertBefore(warningDiv, mapBox.firstChild);
        }
    }

    /**
     * NOWA FUNKCJA: Wyświetlanie błędów mapy
     */
    showMapError(message) {
        console.error(`[ClientsAnalytics] Map error: ${message}`);

        const mapContainer = document.getElementById('poland-map');
        if (mapContainer) {
            mapContainer.innerHTML = `
                <div class="map-error" style="
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 400px;
                    background: #f8f9fa;
                    border: 2px dashed #dee2e6;
                    border-radius: 8px;
                    flex-direction: column;
                    color: #6c757d;
                ">
                    <div style="font-size: 48px; margin-bottom: 16px;">🗺️</div>
                    <h4>Mapa niedostępna</h4>
                    <p>${message}</p>
                    <button class="btn btn-outline-primary btn-sm" onclick="window.ClientsAnalytics.refreshMap()">
                        Spróbuj ponownie
                    </button>
                </div>
            `;
        }
    }

    /**
     * Odświeżenie danych
     */
    async refresh() {
        console.log('[ClientsAnalytics] Odświeżanie danych...');
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
            cities: null,
            sources: null
        };

        // Zniszcz mapę
        if (this.map) {
            this.map.remove();
            this.map = null;
        }

        console.log('[ClientsAnalytics] Cleanup wykonany');
    }

    /**
     * Pobierz dane do exportu
     */
    getExportData() {
        return {
            top_clients: this.data.top_clients,
            geography: this.data.geography,
            current_limit: this.currentLimit,
            geocode_cache_size: this.geocodeCache.size
        };
    }
}

/**
 * Inicjalizacja
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log('[ClientsAnalytics] Inicjalizacja modułu...');

    window.ClientsAnalytics = new ClientsAnalytics();

    console.log('[ClientsAnalytics] Moduł gotowy!');
});