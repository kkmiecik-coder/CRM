// Modern Dashboard JavaScript - Corrected Version
document.addEventListener('DOMContentLoaded', function () {
    console.log('[Dashboard] Inicjalizacja nowoczesnego dashboard');

    // Detect container queries support
    const supportsContainerQueries = CSS.supports('container-type', 'inline-size');

    if (!supportsContainerQueries) {
        console.warn('[Dashboard] Container Queries not supported, using flexbox fallback');
        document.body.classList.add('no-container-queries');
    } else {
        console.log('[Dashboard] Container Queries supported');
        document.body.classList.add('has-container-queries');
    }

    // Inicjalizacja komponentów
    initActivityTabs();
    initWeatherWidget();
    initQuotesChart();
    initQuickActions();
    initChangelogWidget();
    initStatsAnimation();
    initTooltips();
    initUserGreetingAnimation();
    initKeyboardAccessibility();

    setTimeout(() => {
        if (document.querySelector('.dashboard-grid')) {
            triggerFadeInAnimations();
        }
    }, 100);

    // Odśwież dane co 5 minut
    setInterval(refreshDashboardData, 5 * 60 * 1000);

    console.log('[Dashboard] Stats from server:', window.dashboardStats);
    console.log('[Dashboard] Weather from server:', window.weatherData);
    console.log('[Dashboard] Chart data from server:', window.chartData);
});

/**
 * Inicjalizacja tabów w Recent Activity Widget z animacjami
 */
function initActivityTabs() {
    const activityTabs = document.querySelectorAll('.activity-tab');
    const activityContents = document.querySelectorAll('.activity-content');

    if (!activityTabs.length || !activityContents.length) {
        console.log('[Dashboard] Brak elementów activity tabs');
        return;
    }

    activityTabs.forEach(tab => {
        tab.addEventListener('click', function () {
            const targetTab = this.getAttribute('data-tab');

            // Usuń active z wszystkich tabów
            activityTabs.forEach(t => t.classList.remove('active'));

            // Ukryj wszystkie contenty z animacją
            activityContents.forEach(content => {
                content.style.opacity = '0';
                content.style.transform = 'translateY(10px)';
                setTimeout(() => {
                    content.classList.add('hidden');
                }, 150);
            });

            // Aktywuj kliknięty tab
            this.classList.add('active');

            // Pokaż odpowiedni content z animacją
            const targetContent = document.getElementById(targetTab + '-content');
            if (targetContent) {
                setTimeout(() => {
                    targetContent.classList.remove('hidden');
                    targetContent.style.opacity = '0';
                    targetContent.style.transform = 'translateY(10px)';
                    targetContent.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                    
                    setTimeout(() => {
                        targetContent.style.opacity = '1';
                        targetContent.style.transform = 'translateY(0)';
                    }, 10);
                }, 150);
            }
        });
    });
    
    console.log(`[Dashboard] Activity tabs zainicjalizowane - ${activityTabs.length} tabów`);
}

/**
 * Inicjalizacja changelog z rozwijaniem/zwijaniem
 */
function initChangelogWidget() {
    console.log('[Dashboard] Inicjalizacja changelog widget');

    // Załaduj wpisy changelog
    loadChangelogEntries();

    // Inicjalizacja przycisku sync (tylko admin)
    const syncBtn = document.getElementById('changelog-sync-btn');
    if (syncBtn) {
        syncBtn.addEventListener('click', async () => {
            const icon = syncBtn.querySelector('.sync-icon');
            const originalDisabled = syncBtn.disabled;
            syncBtn.disabled = true;
            if (icon) icon.style.opacity = '0.5';

            try {
                const response = await fetch('/dashboard/api/changelog-sync/manual', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();

                if (!response.ok) {
                    const msg = `Błąd synchronizacji: ${result.detail || result.error}`;
                    if (typeof showToast === 'function') {
                        showToast(msg, 'error');
                    } else {
                        alert(msg);
                    }
                    return;
                }

                if (result.created) {
                    const msg = `Dodano wersję ${result.version} (${result.items_count} wpisów)`;
                    if (typeof showToast === 'function') {
                        showToast(msg, 'success');
                    } else {
                        alert(msg);
                    }
                    // Odśwież listę wpisów
                    if (typeof loadChangelogEntries === 'function') {
                        loadChangelogEntries();
                    }
                } else {
                    const msg = 'Brak nowych zmian do dodania';
                    if (typeof showToast === 'function') {
                        showToast(msg, 'info');
                    } else {
                        alert(msg);
                    }
                }
            } catch (err) {
                console.error('[Changelog sync]', err);
                const msg = 'Błąd sieci podczas synchronizacji';
                if (typeof showToast === 'function') {
                    showToast(msg, 'error');
                } else {
                    alert(msg);
                }
            } finally {
                syncBtn.disabled = originalDisabled;
                if (icon) icon.style.opacity = '1';
            }
        });
        console.log('[Dashboard] Przycisk sync changelog zainicjalizowany');
    }
}

/**
 * Animacja statystyk z licznikami
 */
function initStatsAnimation() {
    console.log('[Dashboard] Inicjalizacja animacji statystyk');
    
    const statNumbers = document.querySelectorAll('.stat-number');
    
    if (!statNumbers.length) {
        console.log('[Dashboard] Brak elementów stat-number');
        return;
    }
    
    // Intersection Observer - animuj gdy element wejdzie w viewport
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !entry.target.dataset.animated) {
                animateCounter(entry.target);
                entry.target.dataset.animated = 'true';
            }
        });
    }, { threshold: 0.5 });
    
    statNumbers.forEach(counter => {
        observer.observe(counter);
    });
    
    function animateCounter(element) {
        const text = element.textContent;
        const numberMatch = text.match(/[\d,.\s]+/);
        
        if (!numberMatch) return;
        
        const numberText = numberMatch[0];
        const cleanNumber = parseFloat(numberText.replace(/[^\d.]/g, ''));
        const suffix = text.replace(numberText, '');
        
        if (isNaN(cleanNumber)) return;
        
        let current = 0;
        const increment = cleanNumber / 60; // 60 kroków = ~1 sekunda przy 60fps
        const isDecimal = numberText.includes('.');
        
        const timer = setInterval(() => {
            current += increment;
            
            if (current >= cleanNumber) {
                current = cleanNumber;
                clearInterval(timer);
            }
            
            // Formatowanie liczby
            let displayNumber;
            if (isDecimal) {
                displayNumber = current.toFixed(1);
            } else {
                displayNumber = Math.floor(current).toLocaleString('pl-PL');
            }
            
            element.textContent = displayNumber + suffix;
        }, 16); // ~60fps
    }
    
    console.log(`[Dashboard] Stats animation zainicjalizowana - ${statNumbers.length} liczników`);
}

/**
 * Tooltips dla elementów z data-tooltip
 */
function initTooltips() {
    console.log('[Dashboard] Inicjalizacja tooltips');
    
    const elements = document.querySelectorAll('[data-tooltip]');
    
    if (!elements.length) {
        console.log('[Dashboard] Brak elementów z data-tooltip');
        return;
    }
    
    elements.forEach(element => {
        element.addEventListener('mouseenter', function (e) {
            const tooltipText = this.getAttribute('data-tooltip');
            if (!tooltipText) return;
            
            // Utwórz tooltip
            const tooltip = document.createElement('div');
            tooltip.className = 'dashboard-tooltip';
            tooltip.textContent = tooltipText;
            
            // Style tooltip
            tooltip.style.cssText = `
                position: absolute;
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 12px;
                white-space: nowrap;
                z-index: 1000;
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.2s ease;
                backdrop-filter: blur(4px);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            `;
            
            document.body.appendChild(tooltip);
            
            // Pozycjonowanie
            const rect = this.getBoundingClientRect();
            const tooltipRect = tooltip.getBoundingClientRect();
            
            let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
            let top = rect.top - tooltipRect.height - 8;
            
            // Sprawdź czy tooltip mieści się w viewport
            if (left < 8) left = 8;
            if (left + tooltipRect.width > window.innerWidth - 8) {
                left = window.innerWidth - tooltipRect.width - 8;
            }
            if (top < 8) {
                top = rect.bottom + 8; // Pokaż pod elementem
            }
            
            tooltip.style.left = left + 'px';
            tooltip.style.top = top + 'px';
            
            // Animacja pojawiania
            setTimeout(() => {
                tooltip.style.opacity = '1';
            }, 10);
            
            // Usuń tooltip przy opuszczeniu
            const removeTooltip = () => {
                tooltip.remove();
                this.removeEventListener('mouseleave', removeTooltip);
            };
            
            this.addEventListener('mouseleave', removeTooltip);
        });
    });
    
    console.log(`[Dashboard] Tooltips zainicjalizowane - ${elements.length} elementów`);
}

/**
 * User greeting animation
 */
function initUserGreetingAnimation() {
    const greetingElement = document.querySelector('.user-greeting');
    
    if (!greetingElement) {
        console.log('[Dashboard] Brak elementu .user-greeting');
        return;
    }
    
    // Sprawdź czy animacje są włączone
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        console.log('[Dashboard] Animacje wyłączone - prefers-reduced-motion');
        greetingElement.classList.add('expanded');
        return;
    }
    
    console.log('[Dashboard] User greeting animation started');
    
    // Uruchom animację po krótkim opóźnieniu
    setTimeout(() => {
        greetingElement.classList.add('expanded');
    }, 1000);
    
    // Debug clicking for testing
    if (window.dashboardDebug) {
        greetingElement.addEventListener('click', function() {
            this.classList.remove('expanded');
            setTimeout(() => {
                this.classList.add('expanded');
            }, 100);
        });
    }
}

/**
 * Keyboard accessibility
 */
function initKeyboardAccessibility() {
    // Tab navigation dla activity tabs
    const activityTabs = document.querySelectorAll('.activity-tab');
    
    activityTabs.forEach(tab => {
        tab.setAttribute('tabindex', '0');
        tab.setAttribute('role', 'button');
        
        tab.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
    });
    
    // Changelog entries
    const changelogDates = document.querySelectorAll('.changelog-date.toggle-entry');
    
    changelogDates.forEach(date => {
        date.setAttribute('tabindex', '0');
        date.setAttribute('role', 'button');
        
        date.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
    });
}

/**
 * Trigger fade-in animations - POPRAWIONA WERSJA
 */
function triggerFadeInAnimations() {
    // Sprawdź czy animacje są włączone
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        console.log('[Dashboard] Animacje wyłączone - prefers-reduced-motion');
        return;
    }

    // Znajdź wszystkie elementy w dashboard-grid
    const dashboardGrid = document.querySelector('.dashboard-grid');
    if (!dashboardGrid) {
        console.log('[Dashboard] Nie znaleziono .dashboard-grid');
        return;
    }

    // Pobierz wszystkie dzieci grid (widgety)
    const widgets = Array.from(dashboardGrid.children);
    console.log(`[Dashboard] Znaleziono ${widgets.length} widgetów do animacji`);

    // Quick actions bar
    const quickActions = document.querySelector('.quick-actions-bar');

    // Animuj quick actions najpierw (jeśli istnieje)
    if (quickActions) {
        quickActions.style.opacity = '0';
        quickActions.style.transform = 'translateY(30px)';
        quickActions.style.transition = 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)';

        setTimeout(() => {
            quickActions.style.opacity = '1';
            quickActions.style.transform = 'translateY(0)';
        }, 50);
    }

    // Animuj widgety z opóźnieniem
    widgets.forEach((widget, index) => {
        // Ustaw początkowy stan
        widget.style.opacity = '0';
        widget.style.transform = 'translateY(30px)';
        widget.style.transition = 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)';

        // Animuj z opóźnieniem
        setTimeout(() => {
            widget.style.opacity = '1';
            widget.style.transform = 'translateY(0)';
        }, 100 + (index * 100)); // 100ms base delay + 100ms per widget
    });

    // Dodaj klasę która wskazuje że animacje zostały uruchomione
    document.body.classList.add('dashboard-animations-loaded');

    console.log(`[Dashboard] Fade-in animations triggered for ${widgets.length} widgets`);
}

/**
 * Reset animacji (przydatne do debugowania)
 */
function resetDashboardAnimations() {
    const dashboardGrid = document.querySelector('.dashboard-grid');
    if (!dashboardGrid) return;

    const widgets = Array.from(dashboardGrid.children);
    const quickActions = document.querySelector('.quick-actions-bar');

    // Reset wszystkich elementów
    [...widgets, quickActions].forEach(element => {
        if (element) {
            element.style.opacity = '0';
            element.style.transform = 'translateY(30px)';
        }
    });

    document.body.classList.remove('dashboard-animations-loaded');
    console.log('[Dashboard] Animacje zresetowane');
}

/**
 * Sprawdź czy widget jest widoczny w viewport (dla lazy loading)
 */
function isWidgetInViewport(widget) {
    const rect = widget.getBoundingClientRect();
    return (
        rect.top >= 0 &&
        rect.left >= 0 &&
        rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        rect.right <= (window.innerWidth || document.documentElement.clientWidth)
    );
}

/**
 * Animacja na scroll (opcjonalna)
 */
function initScrollAnimations() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !entry.target.classList.contains('animated')) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
                entry.target.classList.add('animated');
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    // Obserwuj wszystkie widgety
    const widgets = document.querySelectorAll('.dashboard-grid > *');
    widgets.forEach(widget => {
        widget.style.opacity = '0';
        widget.style.transform = 'translateY(30px)';
        widget.style.transition = 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)';
        observer.observe(widget);
    });

    console.log(`[Dashboard] Scroll animations initialized for ${widgets.length} widgets`);
}

/**
 * API calls dla odświeżania danych
 */
async function refreshStatsData() {
    try {
        console.log('[Dashboard] Odświeżanie statystyk...');
        
        const response = await fetch('/dashboard/api/refresh-stats');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            updateStatsDisplay(data.stats);
            console.log('[Dashboard] Statystyki odświeżone');
        } else {
            console.warn('[Dashboard] Błąd odświeżania statystyk:', data.error);
        }
        
    } catch (error) {
        console.error('[Dashboard] Błąd API refresh-stats:', error);
    }
}

/**
 * Aktualizacja wyświetlania statystyk
 */
function updateStatsDisplay(stats) {
    const elements = {
        monthCount: document.querySelector('[data-stat="month-count"]'),
        weekCount: document.querySelector('[data-stat="week-count"]'),
        monthValue: document.querySelector('[data-stat="month-value"]'),
        acceptanceRate: document.querySelector('[data-stat="acceptance-rate"]'),
        clientsTotal: document.querySelector('[data-stat="clients-total"]')
    };
    
    if (elements.monthCount && stats.quotes) {
        elements.monthCount.textContent = stats.quotes.month_count || 0;
    }
    if (elements.weekCount && stats.quotes) {
        elements.weekCount.textContent = stats.quotes.week_count || 0;
    }
    if (elements.monthValue && stats.quotes) {
        elements.monthValue.textContent = formatCurrency(stats.quotes.month_value || 0);
    }
    if (elements.acceptanceRate && stats.quotes) {
        elements.acceptanceRate.textContent = (stats.quotes.acceptance_rate || 0) + '%';
    }
    if (elements.clientsTotal && stats.clients) {
        elements.clientsTotal.textContent = stats.clients.total_count || 0;
    }
}

/**
 * Inicjalizacja widgetu pogodowego
 */
function initWeatherWidget() {
    const weatherWidget = document.getElementById('weather-widget');
    if (!weatherWidget) {
        console.log('[Dashboard] Brak widgetu pogodowego');
        return;
    }

    // Jeśli mamy dane z serwera, użyj ich
    if (window.weatherData && window.weatherData.success) {
        updateWeatherDisplay(window.weatherData);
        return;
    }

    // W przeciwnym razie pobierz dane z API
    loadWeatherData();
}

/**
 * Ładowanie danych pogodowych z API
 */
function loadWeatherData() {
    const apiKey = 'b51440a74a7cc3b6e342b57a9f9ff22e';

    // Koordynaty miast
    const rzeszowCoords = { lat: 50.0413, lon: 21.9990 };
    const bachorzCoords = { lat: 49.8427, lon: 22.3636 };

    detectUserLocation();

    function detectUserLocation() {
        if (!navigator.geolocation) {
            console.warn("[Weather] Geolokalizacja niedostępna – fallback: IP");
            fetchLocationByIP();
            return;
        }

        navigator.geolocation.getCurrentPosition(
            position => {
                const { latitude, longitude } = position.coords;
                console.log("[Weather] Współrzędne:", latitude, longitude);

                const distanceToRzeszow = getDistance(latitude, longitude, rzeszowCoords.lat, rzeszowCoords.lon);
                const distanceToBachorz = getDistance(latitude, longitude, bachorzCoords.lat, bachorzCoords.lon);

                const selectedCity = distanceToRzeszow < distanceToBachorz ? 'Rzeszów' : 'Bachórz';
                console.log(`[Weather] Wybrano: ${selectedCity}`);
                fetchWeather(selectedCity);
            },
            error => {
                console.warn("[Weather] Geolokalizacja odrzucona. Kod:", error.code);
                fetchLocationByIP();
            }
        );
    }

    function fetchLocationByIP() {
        fetch('https://ipapi.co/json/')
            .then(response => response.json())
            .then(data => {
                const lat = parseFloat(data.latitude);
                const lon = parseFloat(data.longitude);

                if (!isNaN(lat) && !isNaN(lon)) {
                    const distanceToRzeszow = getDistance(lat, lon, rzeszowCoords.lat, rzeszowCoords.lon);
                    const distanceToBachorz = getDistance(lat, lon, bachorzCoords.lat, bachorzCoords.lon);
                    const selectedCity = distanceToRzeszow < distanceToBachorz ? 'Rzeszów' : 'Bachórz';
                    fetchWeather(selectedCity);
                } else {
                    const fallbackCity = ['Rzeszów', 'Bachórz'].includes(data.city) ? data.city : 'Rzeszów';
                    fetchWeather(fallbackCity);
                }
            })
            .catch(err => {
                console.warn('[Weather] IP location failed:', err);
                fetchWeather('Rzeszów');
            });
    }

    function getDistance(lat1, lon1, lat2, lon2) {
        const toRad = x => (x * Math.PI) / 180;
        const R = 6371;
        const dLat = toRad(lat2 - lat1);
        const dLon = toRad(lon2 - lon1);
        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    function fetchWeather(city) {
        console.log("[Weather] Fetch dla:", city);
        const url = `https://api.openweathermap.org/data/2.5/weather?q=${encodeURIComponent(city)}&units=metric&lang=pl&appid=${apiKey}`;

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.cod === 200) {
                    const weatherData = {
                        temperature: Math.round(data.main.temp),
                        feels_like: Math.round(data.main.feels_like),
                        description: data.weather[0].description,
                        city: data.name,
                        humidity: data.main.humidity,
                        pressure: data.main.pressure,
                        wind_speed: data.wind.speed,
                        icon: data.weather[0].icon,
                        sunrise: formatTime(data.sys.sunrise),
                        sunset: formatTime(data.sys.sunset),
                        success: true
                    };

                    updateWeatherDisplay(weatherData);
                } else {
                    console.warn("[Weather] Odpowiedź API:", data);
                    showWeatherError('Błąd API');
                }
            })
            .catch(err => {
                console.error("[Weather] Fetch error:", err);
                showWeatherError('Brak połączenia');
            });
    }

    function formatTime(unixTimestamp) {
        const date = new Date(unixTimestamp * 1000);
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${hours}:${minutes}`;
    }
}

/**
 * Aktualizacja wyświetlania pogody
 */
function updateWeatherDisplay(weatherData) {
    const tempElement = document.getElementById('weather-temp');
    const locationElement = document.getElementById('weather-location');
    const descElement = document.getElementById('weather-desc');
    const humidityElement = document.getElementById('weather-humidity');
    const windElement = document.getElementById('weather-wind');
    const sunriseElement = document.getElementById('weather-sunrise');
    const sunsetElement = document.getElementById('weather-sunset');
    const iconElement = document.getElementById('weather-icon');

    if (weatherData.success) {
        tempElement.textContent = `${weatherData.temperature}°C`;
        locationElement.textContent = weatherData.city;
        descElement.textContent = weatherData.description;
        humidityElement.textContent = `Wilgotność: ${weatherData.humidity}%`;
        windElement.textContent = `Wiatr: ${weatherData.wind_speed} m/s`;
        sunriseElement.textContent = `Wschód: ${weatherData.sunrise}`;
        sunsetElement.textContent = `Zachód: ${weatherData.sunset}`;

        // Ikona pogody - mapowanie kodów API na emoji
        const weatherIcons = {
            '01d': '☀️', '01n': '🌙',
            '02d': '⛅', '02n': '☁️',
            '03d': '☁️', '03n': '☁️',
            '04d': '☁️', '04n': '☁️',
            '09d': '🌧️', '09n': '🌧️',
            '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️',
            '13d': '❄️', '13n': '❄️',
            '50d': '🌫️', '50n': '🌫️'
        };

        iconElement.textContent = weatherIcons[weatherData.icon] || '☀️';
    } else {
        showWeatherError(weatherData.message || 'Błąd pobierania danych');
    }
}

/**
 * Wyświetlenie błędu pogody
 */
function showWeatherError(msg) {
    document.getElementById('weather-temp').textContent = '--°C';
    document.getElementById('weather-location').textContent = msg || 'Błąd';
    document.getElementById('weather-desc').textContent = 'Nie udało się pobrać danych';
    document.getElementById('weather-humidity').textContent = 'Wilgotność: --%';
    document.getElementById('weather-wind').textContent = 'Wiatr: -- m/s';
    document.getElementById('weather-sunrise').textContent = 'Wschód: --:--';
    document.getElementById('weather-sunset').textContent = 'Zachód: --:--';
    document.getElementById('weather-icon').textContent = '❓';
}

/**
 * Inicjalizacja wykresu wycen
 */
function initQuotesChart() {
    console.log('[Dashboard] DEBUG: initQuotesChart called');
    
    // Rysuj prawdziwy wykres
    drawRealChart();
    
    // Aktualizuj metryki
    if (window.chartData) {
        console.log('[Dashboard] DEBUG: Chart data summary:', window.chartData.summary);
        
        const totalElement = document.querySelector('.quotes-metric .metric-dot.total');
        const acceptedElement = document.querySelector('.quotes-metric .metric-dot.accepted');
        const orderedElement = document.querySelector('.quotes-metric .metric-dot.ordered');
        
        if (totalElement && totalElement.nextElementSibling) {
            totalElement.nextElementSibling.textContent = `Wszystkie wyceny: ${window.chartData.summary.total_quotes || 0}`;
        }
        if (acceptedElement && acceptedElement.nextElementSibling) {
            acceptedElement.nextElementSibling.textContent = `Zaakceptowane: ${window.chartData.summary.accepted_quotes || 0}`;
        }
        if (orderedElement && orderedElement.nextElementSibling) {
            orderedElement.nextElementSibling.textContent = `Zamówienia (BL): ${window.chartData.summary.ordered_quotes || 0}`;
        }
    }
}

/**
 * Rysowanie prawdziwego wykresu słupkowego
 */
function drawRealChart() {
    const canvas = document.getElementById('quotes-canvas-chart');
    const container = document.getElementById('real-chart-container');
    const noDataDiv = document.getElementById('chart-no-data');
    
    if (!canvas || !container) {
        console.log('[Dashboard] Brak canvas lub kontenera dla wykresu');
        return;
    }

    // Ustaw rozmiar canvas na podstawie kontenera
    const containerRect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    
    // Rozmiar wyświetlania (CSS)
    canvas.style.width = (containerRect.width - 16) + 'px';
    canvas.style.height = (containerRect.height - 16) + 'px';
    
    // Rzeczywisty rozmiar canvas (dla ostrości)
    canvas.width = (containerRect.width - 16) * dpr;
    canvas.height = (containerRect.height - 16) * dpr;
    
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    
    // Sprawdź czy mamy dane
    if (!window.chartData || !window.chartData.labels || window.chartData.labels.length === 0) {
        console.log('[Dashboard] Brak danych dla wykresu');
        canvas.style.display = 'none';
        if (noDataDiv) noDataDiv.style.display = 'block';
        return;
    }

    console.log('[Dashboard] Rysowanie wykresu z danymi:', window.chartData);

    // Ukryj no-data, pokaż canvas
    canvas.style.display = 'block';
    if (noDataDiv) noDataDiv.style.display = 'none';

    // Ustawienia wykresu
    const width = containerRect.width - 16;
    const height = containerRect.height - 16;
    const padding = Math.min(width * 0.08, 50);
    const chartWidth = width - (padding * 2);
    const chartHeight = height - (padding * 2);
    
    const labels = window.chartData.labels;
    const totalQuotes = window.chartData.datasets.total_quotes;
    const acceptedQuotes = window.chartData.datasets.accepted_quotes;
    const orderedQuotes = window.chartData.datasets.ordered_quotes;
    
    // Znajdź maksymalną wartość
    const maxValue = Math.max(
        ...totalQuotes,
        ...acceptedQuotes,
        ...orderedQuotes,
        1
    );
    
    // Wyczyść canvas
    ctx.clearRect(0, 0, width, height);
    
    // Kolory
    const colors = {
        total: '#94a3b8',
        accepted: '#22c55e',
        ordered: '#ED6B24'
    };
    
    // Rysuj tło
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
    
    // Szerokość słupka
    const groupWidth = chartWidth / labels.length;
    const barWidth = Math.min(groupWidth / 4, 40);
    const barSpacing = barWidth * 0.1;
    
    // Rysuj słupki dla każdego miesiąca
    labels.forEach((label, monthIndex) => {
        const groupX = padding + (monthIndex * groupWidth);
        const centerX = groupX + groupWidth / 2;
        
        // Pozycje słupków w grupie
        const totalX = centerX - barWidth * 1.5 - barSpacing;
        const acceptedX = centerX - barWidth * 0.5;
        const orderedX = centerX + barWidth * 0.5 + barSpacing;
        
        // Wysokości słupków
        const totalHeight = (totalQuotes[monthIndex] / maxValue) * chartHeight;
        const acceptedHeight = (acceptedQuotes[monthIndex] / maxValue) * chartHeight;
        const orderedHeight = (orderedQuotes[monthIndex] / maxValue) * chartHeight;
        
        // Funkcja rysowania słupka z zaokrąglonymi górami
        function drawRoundedBar(x, y, width, height, color) {
            if (height < 2) return;
            
            ctx.fillStyle = color;
            ctx.fillRect(x, y, width, height);
            
            // Zaokrąglona góra
            ctx.beginPath();
            ctx.arc(x + width/2, y, width/2, 0, Math.PI, true);
            ctx.fill();
        }
        
        // Rysuj wszystkie słupki
        drawRoundedBar(totalX, padding + chartHeight - totalHeight, barWidth, totalHeight, colors.total);
        drawRoundedBar(acceptedX, padding + chartHeight - acceptedHeight, barWidth, acceptedHeight, colors.accepted);
        drawRoundedBar(orderedX, padding + chartHeight - orderedHeight, barWidth, orderedHeight, colors.ordered);
        
        // Etykiety miesięcy
        ctx.fillStyle = '#374151';
        ctx.font = `${Math.min(width/50, 14)}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText(label, centerX, height - 8);
        
        // Wartości nad słupkami (jeśli są większe niż 0 i słupek jest widoczny)
        ctx.font = `${Math.min(width/60, 12)}px sans-serif`;
        if (totalQuotes[monthIndex] > 0 && totalHeight > 20) {
            ctx.fillStyle = colors.total;
            ctx.fillText(totalQuotes[monthIndex], totalX + barWidth/2, padding + chartHeight - totalHeight - 5);
        }
        if (acceptedQuotes[monthIndex] > 0 && acceptedHeight > 20) {
            ctx.fillStyle = colors.accepted;
            ctx.fillText(acceptedQuotes[monthIndex], acceptedX + barWidth/2, padding + chartHeight - acceptedHeight - 5);
        }
        if (orderedQuotes[monthIndex] > 0 && orderedHeight > 20) {
            ctx.fillStyle = colors.ordered;
            ctx.fillText(orderedQuotes[monthIndex], orderedX + barWidth/2, padding + chartHeight - orderedHeight - 5);
        }
    });
    
    // Rysuj oś Y (skala)
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    const steps = Math.min(Math.floor(maxValue/20), 8);
    
    for (let i = 0; i <= steps; i++) {
        const y = padding + (chartHeight / steps) * i;
        const value = Math.round(maxValue - (maxValue / steps) * i);
        
        // Delikatna linia siatki
        if (i > 0 && i < steps) {
            ctx.beginPath();
            ctx.moveTo(padding, y);
            ctx.lineTo(padding + chartWidth, y);
            ctx.stroke();
        }
        
        // Etykieta wartości
        ctx.fillStyle = '#6b7280';
        ctx.font = `${Math.min(width/60, 11)}px sans-serif`;
        ctx.textAlign = 'right';
        ctx.fillText(value.toString(), padding - 8, y + 4);
    }
    
    console.log('[Dashboard] Wykres narysowany pomyślnie');
}

/**
 * Inicjalizacja przycisków szybkich akcji
 */
function initQuickActions() {
    const quickActions = document.querySelectorAll('.quick-action-btn');

    quickActions.forEach(btn => {
        btn.addEventListener('mouseenter', function () {
            this.style.transform = 'translateY(-2px) scale(1.02)';
        });

        btn.addEventListener('mouseleave', function () {
            this.style.transform = 'translateY(0) scale(1)';
        });

        // Dodaj ripple effect przy kliknięciu
        btn.addEventListener('click', function (e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            ripple.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                left: ${x}px;
                top: ${y}px;
                background: rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                transform: scale(0);
                animation: ripple 0.6s ease-out;
                pointer-events: none;
            `;

            this.style.position = 'relative';
            this.style.overflow = 'hidden';
            this.appendChild(ripple);

            setTimeout(() => {
                ripple.remove();
            }, 600);
        });
    });

    // Dodaj style dla ripple animation
    if (!document.getElementById('ripple-styles')) {
        const style = document.createElement('style');
        style.id = 'ripple-styles';
        style.textContent = `
            @keyframes ripple {
                to {
                    transform: scale(2);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }
}

/**
 * Odświeżanie danych dashboard
 */
function refreshDashboardData() {
    console.log('[Dashboard] Odświeżanie wszystkich danych dashboard...');

    // Odśwież pogodę
    loadWeatherData();
    
    // Odśwież statystyki
    refreshStatsData();
    
    // Jeśli mamy endpoint dla wykresów
    if (typeof refreshChartData === 'function') {
        refreshChartData();
    }
}

/**
 * Obsługa resize dla wykresów
 */
function handleResize() {
    if (window.resizeTimeout) {
        clearTimeout(window.resizeTimeout);
    }
    
    window.resizeTimeout = setTimeout(() => {
        console.log('[Dashboard] Window resized - redrawing charts');
        
        if (typeof drawRealChart === 'function') {
            drawRealChart();
        }
        
        repositionTooltips();
    }, 150);
}

/**
 * Reposition tooltips on resize
 */
function repositionTooltips() {
    const tooltips = document.querySelectorAll('.dashboard-tooltip');
    tooltips.forEach(tooltip => tooltip.remove());
}

/**
 * Formatowanie liczb z separatorami tysięcy
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return new Intl.NumberFormat('pl-PL').format(num);
}

/**
 * Formatowanie kwoty w PLN
 */
function formatCurrency(amount) {
    if (amount === null || amount === undefined) return '0 zł';
    return new Intl.NumberFormat('pl-PL', {
        style: 'currency',
        currency: 'PLN',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}

/**
 * Formatowanie procentów
 */
function formatPercentage(value, total) {
    if (total === 0 || !value || !total) return '0%';
    const percentage = (value / total) * 100;
    return `${percentage.toFixed(1)}%`;
}

/**
 * Debug mode
 */
function enableDebugMode() {
    window.dashboardDebug = true;
    console.log('[Dashboard] Debug mode enabled');

    document.addEventListener('click', function (e) {
        if (window.dashboardDebug) {
            console.log('[Dashboard] Click:', e.target);
        }
    });
}

/**
 * Performance monitoring
 */
function monitorPerformance() {
    if ('performance' in window) {
        window.addEventListener('load', function() {
            setTimeout(() => {
                const perfData = performance.getEntriesByType('navigation')[0];
                console.log('[Dashboard] Load Performance:', {
                    domContentLoaded: Math.round(perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart),
                    loadComplete: Math.round(perfData.loadEventEnd - perfData.loadEventStart),
                    totalTime: Math.round(perfData.loadEventEnd - perfData.navigationStart)
                });
            }, 0);
        });
    }
}

/**
 * NOWA FUNKCJA: Ładowanie wpisów changelog
 */
async function loadChangelogEntries() {
    const container = document.getElementById('changelog-entries');
    if (!container) {
        console.log('[Dashboard] Brak kontenera changelog-entries');
        return;
    }
    
    try {
        // Pokaż loading
        container.innerHTML = '<div class="changelog-loading">Ładowanie nowości...</div>';
        
        // Spróbuj załadować z API
        const response = await fetch('/dashboard/api/changelog-entries');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success && data.entries && data.entries.length > 0) {
            renderChangelogEntries(data.entries);
        } else {
            // Pokaż przykładowe dane jeśli brak wpisów
            renderFallbackChangelog();
        }
        
    } catch (error) {
        console.log('[Changelog] Błąd ładowania z API, pokazuję fallback data:', error);
        renderFallbackChangelog();
    }
}

/**
 * NOWA FUNKCJA: Renderowanie fallback changelog
 */
function renderFallbackChangelog() {
    const container = document.getElementById('changelog-entries');
    if (!container) return;
    
    container.innerHTML = `
        <div class="changelog-entry open">
            <div class="changelog-date toggle-entry">
                <span>05.09.2025 - Dashboard v2.0</span>
                <img src="/static/icons/sidebar-icon/footer-options.svg" alt="Rozwiń" class="changelog-chevron">
            </div>
            <div class="changelog-list animated-toggle">
                <div class="changelog-section">
                    <strong>Dodano</strong>
                    <ul>
                        <li>Nowoczesny moduł Dashboard</li>
                        <li>Widget statystyk z animacjami</li>
                        <li>System tooltips i modali</li>
                    </ul>
                    <strong>Ulepszono</strong>
                    <ul>
                        <li>Interfejs użytkownika</li>
                        <li>Wydajność ładowania</li>
                    </ul>
                </div>
            </div>
        </div>
        <div class="changelog-entry">
            <div class="changelog-date toggle-entry">
                <span>30.08.2025 - System v1.9</span>
                <img src="/static/icons/sidebar-icon/footer-options.svg" alt="Rozwiń" class="changelog-chevron">
            </div>
            <div class="changelog-list animated-toggle">
                <div class="changelog-section">
                    <strong>Naprawiono</strong>
                    <ul>
                        <li>Błędy w module wycen</li>
                        <li>Problemy z synchronizacją</li>
                    </ul>
                </div>
            </div>
        </div>
    `;
    
    // Zainicjalizuj interakcje po renderowaniu
    initChangelogInteractions();
}

/**
 * NOWA FUNKCJA: Renderowanie wpisów z bazy danych
 * Pokazuje pierwsze 3 wpisy, resztę ukrywa za przyciskiem "Załaduj więcej"
 */
function renderChangelogEntries(entries) {
    const container = document.getElementById('changelog-entries');
    if (!container) return;

    const INITIAL_VISIBLE = 3; // Liczba widocznych wpisów na start
    let html = '';

    entries.forEach((entry, index) => {
        const isOpen = index === 0 ? 'open' : '';
        const isHidden = index >= INITIAL_VISIBLE ? 'changelog-hidden' : '';

        html += `
            <div class="changelog-entry ${isOpen} ${isHidden}" data-changelog-index="${index}">
                <div class="changelog-date toggle-entry">
                    <span>${formatChangelogDate(entry.created_at)} - v${entry.version}</span>
                    <img src="/static/icons/sidebar-icon/footer-options.svg" alt="Rozwiń" class="changelog-chevron">
                </div>
                <div class="changelog-list animated-toggle">
                    ${renderChangelogItems(entry.items)}
                </div>
            </div>
        `;
    });

    // Dodaj przycisk "Załaduj więcej" jeśli jest więcej niż INITIAL_VISIBLE wpisów
    if (entries.length > INITIAL_VISIBLE) {
        const hiddenCount = entries.length - INITIAL_VISIBLE;
        html += `
            <button class="changelog-load-more" id="changelog-load-more">
                <span class="load-more-icon">📜</span>
                <span class="load-more-text">Pokaż więcej (${hiddenCount})</span>
            </button>
        `;
    }

    container.innerHTML = html;
    initChangelogInteractions();
    initChangelogLoadMore(entries.length, INITIAL_VISIBLE);
}

/**
 * NOWA FUNKCJA: Inicjalizacja przycisku "Załaduj więcej"
 */
function initChangelogLoadMore(totalEntries, initialVisible) {
    const loadMoreBtn = document.getElementById('changelog-load-more');
    if (!loadMoreBtn) return;

    loadMoreBtn.addEventListener('click', function() {
        // Pokaż wszystkie ukryte wpisy
        const hiddenEntries = document.querySelectorAll('.changelog-entry.changelog-hidden');

        hiddenEntries.forEach((entry, index) => {
            // Animacja pojawiania się z opóźnieniem
            setTimeout(() => {
                entry.classList.remove('changelog-hidden');
                entry.style.animation = 'changelogFadeIn 0.3s ease forwards';
            }, index * 100);
        });

        // Ukryj przycisk po kliknięciu
        this.style.animation = 'changelogFadeOut 0.2s ease forwards';
        setTimeout(() => {
            this.remove();
        }, 200);
    });
}

/**
 * NOWA FUNKCJA: Renderowanie elementów wpisu
 */
function renderChangelogItems(items) {
    const sections = {
        'added': { title: 'Dodano', items: [] },
        'improved': { title: 'Ulepszono', items: [] },
        'fixed': { title: 'Naprawiono', items: [] },
        'custom': { title: '', items: [] }
    };
    
    // Grupuj items według typu
    items.forEach(item => {
        if (sections[item.section_type]) {
            sections[item.section_type].items.push(item);
        }
    });
    
    let html = '<div class="changelog-section">';
    
    Object.keys(sections).forEach(sectionType => {
        const section = sections[sectionType];
        if (section.items.length > 0) {
            const title = sectionType === 'custom' && section.items[0].custom_section_name 
                ? section.items[0].custom_section_name 
                : section.title;
                
            html += `<strong>${title}</strong><ul>`;
            section.items.forEach(item => {
                html += `<li>${item.item_text}</li>`;
            });
            html += '</ul>';
        }
    });
    
    html += '</div>';
    return html;
}

/**
 * NOWA FUNKCJA: Formatowanie daty changelog
 */
function formatChangelogDate(dateString) {
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString('pl-PL');
    } catch (error) {
        return dateString;
    }
}

/**
 * NOWA FUNKCJA: Inicjalizacja interakcji changelog
 */
function initChangelogInteractions() {
    const entries = document.querySelectorAll('.changelog-entry');
    
    entries.forEach((entry, index) => {
        const dateElement = entry.querySelector('.changelog-date.toggle-entry');
        const listElement = entry.querySelector('.changelog-list.animated-toggle');
        const chevron = entry.querySelector('.changelog-chevron');
        
        if (dateElement && listElement) {
            dateElement.style.cursor = 'pointer';
            
            // Ustaw początkowy stan
            if (entry.classList.contains('open')) {
                listElement.style.maxHeight = listElement.scrollHeight + 'px';
                listElement.style.opacity = '1';
                if (chevron) chevron.style.transform = 'rotate(90deg)';
            } else {
                listElement.style.maxHeight = '0';
                listElement.style.opacity = '0';
                if (chevron) chevron.style.transform = 'rotate(-90deg)';
            }
            
            // Dodaj transition
            listElement.style.transition = 'max-height 0.3s ease, opacity 0.3s ease';
            if (chevron) chevron.style.transition = 'transform 0.3s ease';
            
            dateElement.addEventListener('click', function() {
                const isOpen = entry.classList.contains('open');
                
                if (isOpen) {
                    entry.classList.remove('open');
                    listElement.style.maxHeight = '0';
                    listElement.style.opacity = '0';
                    if (chevron) chevron.style.transform = 'rotate(-90deg)';
                } else {
                    entry.classList.add('open');
                    listElement.style.maxHeight = listElement.scrollHeight + 'px';
                    listElement.style.opacity = '1';
                    if (chevron) chevron.style.transform = 'rotate(90deg)';
                }
            });
        }
    });
    
    console.log(`[Dashboard] Changelog interactions zainicjalizowane - ${entries.length} wpisów`);
}

// Event Listeners
window.addEventListener('resize', handleResize);
window.addEventListener('error', function (e) {
    console.error('[Dashboard] JavaScript Error:', {
        message: e.message,
        filename: e.filename,
        lineno: e.lineno,
        colno: e.colno,
        error: e.error
    });
});

window.addEventListener('unhandledrejection', function(event) {
    console.error('[Dashboard] Unhandled Promise Rejection:', event.reason);
    
    if (typeof showToast === 'function') {
        showToast('Wystąpił błąd podczas ładowania danych', 'error');
    }
});

// Uruchom monitoring wydajności
monitorPerformance();

// Eksport funkcji do globalnego scope dla debugowania
window.dashboardFunctions = {
    loadWeatherData,
    updateWeatherDisplay,
    refreshDashboardData,
    refreshStatsData,
    updateStatsDisplay,
    formatNumber,
    formatCurrency,
    formatPercentage,
    enableDebugMode,
    initChangelogWidget,
    initStatsAnimation,
    initTooltips,
    triggerFadeInAnimations,
    drawRealChart,
    loadChangelogEntries,
    renderFallbackChangelog
};

// Export dla globalnego dostępu
window.dashboardAnimations = {
    trigger: triggerFadeInAnimations,
    reset: resetDashboardAnimations,
    initScroll: initScrollAnimations
};

// Dashboard Fireworks System - Dodaj do dashboard.js

/**
 * 🎆 WOOD POWER FIREWORKS SYSTEM 🎆
 * Efektowny system fajerwerków dla dashboardu
 */

// Konfiguracja systemu fajerwerków
const FIREWORKS_CONFIG = {
    DOUBLE_CLICK_THRESHOLD: 2000, // 2 sekundy na double click
    ANIMATION_DURATION: 5000, // 5 sekund animacji
    FIREWORKS_COUNT: 12, // Liczba fajerwerków
    COLORS: ['#ED6B24', '#FFD700', '#FFFFFF', '#FF4444', '#4A90E2', '#22c55e'],
    LOGO_PATH: '/static/images/favicon.png'
};

// Stan systemu fajerwerków
let fireworksState = {
    canvas: null,
    ctx: null,
    animationFrame: null,
    particles: [],
    isActive: false,
    lastClickTime: 0,
    clickCount: 0,
    achievementShown: false
};

/**
 * Inicjalizacja systemu fajerwerków
 */
function initFireworksSystem() {
    console.log('[Fireworks] Inicjalizacja systemu fajerwerków');

    // Dodaj event listener na user-greeting
    const userGreeting = document.getElementById('user-greeting');
    if (userGreeting) {
        userGreeting.addEventListener('click', handleGreetingClick);
        userGreeting.style.cursor = 'pointer';
        userGreeting.title = 'Double-click szybko dla niespodzianki! 🎆';
        console.log('[Fireworks] Event listener dodany do user-greeting');
    }

    // Przygotuj canvas
    createFireworksCanvas();
}

/**
 * Obsługa kliknięć w user-greeting
 */
function handleGreetingClick(event) {
    const now = Date.now();

    // Reset licznika jeśli minęło za dużo czasu
    if (now - fireworksState.lastClickTime > FIREWORKS_CONFIG.DOUBLE_CLICK_THRESHOLD) {
        fireworksState.clickCount = 0;
    }

    fireworksState.clickCount++;
    fireworksState.lastClickTime = now;

    console.log(`[Fireworks] Click ${fireworksState.clickCount} w czasie ${now}`);

    // Double click detection
    if (fireworksState.clickCount === 2) {
        console.log('[Fireworks] 🎆 DOUBLE CLICK DETECTED! Odpalam fajerwerki!');
        triggerFireworks();
        fireworksState.clickCount = 0; // Reset
    }
}

/**
 * Tworzy canvas dla fajerwerków
 */
function createFireworksCanvas() {
    // Usuń poprzedni canvas jeśli istnieje
    const existingCanvas = document.getElementById('fireworks-canvas');
    if (existingCanvas) {
        existingCanvas.remove();
    }

    // Utwórz nowy canvas
    const canvas = document.createElement('canvas');
    canvas.id = 'fireworks-canvas';
    canvas.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        pointer-events: none;
        z-index: 9999;
        display: none;
    `;

    document.body.appendChild(canvas);

    // Ustaw rozmiar canvas
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    fireworksState.canvas = canvas;
    fireworksState.ctx = canvas.getContext('2d');

    console.log('[Fireworks] Canvas utworzony:', canvas.width, 'x', canvas.height);
}

/**
 * Główna funkcja odpalaująca fajerwerki
 */
function triggerFireworks() {
    if (fireworksState.isActive) {
        console.log('[Fireworks] Fajerwerki już aktywne, ignoruję');
        return;
    }

    console.log('[Fireworks] 🚀 ROZPOCZYNANIE POKAZU FAJERWERKÓW!');
    fireworksState.isActive = true;
    fireworksState.particles = [];

    // Pokaż canvas
    fireworksState.canvas.style.display = 'block';

    // Screen shake effect
    addScreenShake();

    // Generuj fajerwerki
    generateFireworks();

    // Uruchom animację
    startFireworksAnimation();

    // Pokaż achievement toast (tylko raz)
    if (!fireworksState.achievementShown) {
        showAchievementToast();
        fireworksState.achievementShown = true;
    }

    // Automatyczne zakończenie po czasie
    setTimeout(() => {
        endFireworks();
    }, FIREWORKS_CONFIG.ANIMATION_DURATION);
}

/**
 * Generuje różne rodzaje fajerwerków
 */
function generateFireworks() {
    const types = ['classic', 'golden_rain', 'spiral', 'heart', 'logo'];

    for (let i = 0; i < FIREWORKS_CONFIG.FIREWORKS_COUNT; i++) {
        // Losowy typ fajerwerku
        const type = types[Math.floor(Math.random() * types.length)];

        // Losowa pozycja
        const x = Math.random() * fireworksState.canvas.width;
        const y = Math.random() * (fireworksState.canvas.height * 0.6) + 100; // Górne 60% ekranu

        // Opóźnienie między fajerwerkami
        const delay = i * 200 + Math.random() * 300;

        setTimeout(() => {
            createFirework(type, x, y);
        }, delay);
    }
}

/**
 * Tworzy pojedynczy fajerwerk
 */
function createFirework(type, x, y) {
    console.log(`[Fireworks] Tworzę fajerwerk typu ${type} na pozycji (${x}, ${y})`);

    const color = FIREWORKS_CONFIG.COLORS[Math.floor(Math.random() * FIREWORKS_CONFIG.COLORS.length)];

    switch (type) {
        case 'classic':
            createClassicFirework(x, y, color);
            break;
        case 'golden_rain':
            createGoldenRain(x, y);
            break;
        case 'spiral':
            createSpiralFirework(x, y, color);
            break;
        case 'heart':
            createHeartFirework(x, y);
            break;
        case 'logo':
            createLogoFirework(x, y);
            break;
    }
}

/**
 * 1. Klasyczne eksplozje - kolorowe okręgi
 */
function createClassicFirework(x, y, color) {
    const particleCount = 25 + Math.random() * 15;

    for (let i = 0; i < particleCount; i++) {
        const angle = (Math.PI * 2 * i) / particleCount;
        const velocity = 2 + Math.random() * 4;

        const particle = {
            x: x,
            y: y,
            vx: Math.cos(angle) * velocity,
            vy: Math.sin(angle) * velocity,
            life: 1.0,
            decay: 0.015 + Math.random() * 0.01,
            color: color,
            size: 2 + Math.random() * 3,
            type: 'classic',
            gravity: 0.05
        };

        fireworksState.particles.push(particle);
    }
}

/**
 * 2. Złoty deszcz - spadające iskry
 */
function createGoldenRain(x, y) {
    const particleCount = 40;

    for (let i = 0; i < particleCount; i++) {
        const particle = {
            x: x + (Math.random() - 0.5) * 100,
            y: y,
            vx: (Math.random() - 0.5) * 2,
            vy: Math.random() * 2 + 1,
            life: 1.0,
            decay: 0.008,
            color: '#FFD700',
            size: 1 + Math.random() * 2,
            type: 'rain',
            gravity: 0.08,
            sparkle: Math.random() > 0.5
        };

        fireworksState.particles.push(particle);
    }
}

/**
 * 3. Spirale - wirujące fajerwerki
 */
function createSpiralFirework(x, y, color) {
    const particleCount = 30;

    for (let i = 0; i < particleCount; i++) {
        const angle = (Math.PI * 4 * i) / particleCount; // 2 pełne obroty
        const radius = 1 + (i / particleCount) * 3;

        const particle = {
            x: x,
            y: y,
            vx: Math.cos(angle) * radius,
            vy: Math.sin(angle) * radius,
            life: 1.0,
            decay: 0.012,
            color: color,
            size: 1.5 + Math.random() * 2,
            type: 'spiral',
            gravity: 0.03,
            rotation: angle
        };

        fireworksState.particles.push(particle);
    }
}

/**
 * 4. Serca - romantyczne fajerwerki
 */
function createHeartFirework(x, y) {
    const heartPoints = generateHeartShape();

    heartPoints.forEach(point => {
        const particle = {
            x: x,
            y: y,
            vx: point.x * 0.5,
            vy: point.y * 0.5,
            life: 1.0,
            decay: 0.01,
            color: '#FF69B4',
            size: 2 + Math.random(),
            type: 'heart',
            gravity: 0.02
        };

        fireworksState.particles.push(particle);
    });
}

/**
 * 5. Logo Wood Power - eksplozja w kształcie logo
 */
function createLogoFirework(x, y) {
    // Symulacja punktów logo - możesz dostosować do faktycznego kształtu
    const logoPoints = [
        // Zewnętrzny okrąg
        ...generateCirclePoints(x, y, 30, 20),
        // Wewnętrzny wzór
        ...generateCirclePoints(x, y, 15, 12),
        // Środek
        { x: 0, y: 0 }
    ];

    logoPoints.forEach(point => {
        const particle = {
            x: x,
            y: y,
            vx: point.x * 0.3,
            vy: point.y * 0.3,
            life: 1.0,
            decay: 0.008,
            color: '#ED6B24', // Brand color
            size: 2.5,
            type: 'logo',
            gravity: 0.03
        };

        fireworksState.particles.push(particle);
    });
}

/**
 * Pomocnicze funkcje dla kształtów
 */
function generateHeartShape() {
    const points = [];
    for (let t = 0; t < Math.PI * 2; t += 0.15) { // Gęstsze punkty - z 0.2 na 0.15
        const x = 16 * Math.pow(Math.sin(t), 3);
        const y = -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t));
        points.push({ x: x * 0.4, y: y * 0.4 }); // Większe serce - z 0.2 na 0.4
    }
    return points;
}

function generateCirclePoints(centerX, centerY, radius, count) {
    const points = [];
    for (let i = 0; i < count; i++) {
        const angle = (Math.PI * 2 * i) / count;
        points.push({
            x: Math.cos(angle) * radius,
            y: Math.sin(angle) * radius
        });
    }
    return points;
}

/**
 * Animacja fajerwerków
 */
function startFireworksAnimation() {
    function animate() {
        if (!fireworksState.isActive) return;

        // Wyczyść canvas
        fireworksState.ctx.clearRect(0, 0, fireworksState.canvas.width, fireworksState.canvas.height);

        // Aktualizuj i rysuj cząsteczki
        for (let i = fireworksState.particles.length - 1; i >= 0; i--) {
            const particle = fireworksState.particles[i];

            // Aktualizuj pozycję
            particle.x += particle.vx;
            particle.y += particle.vy;
            particle.vy += particle.gravity; // Grawitacja
            particle.life -= particle.decay;

            // Usuń martwe cząsteczki
            if (particle.life <= 0) {
                fireworksState.particles.splice(i, 1);
                continue;
            }

            // Rysuj cząsteczkę
            drawParticle(particle);
        }

        fireworksState.animationFrame = requestAnimationFrame(animate);
    }

    animate();
}

/**
 * Rysowanie pojedynczej cząsteczki
 */
function drawParticle(particle) {
    const ctx = fireworksState.ctx;

    ctx.save();
    ctx.globalAlpha = particle.life;

    // Różne style dla różnych typów
    switch (particle.type) {
        case 'classic':
            ctx.fillStyle = particle.color;
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
            break;

        case 'rain':
            ctx.fillStyle = particle.color;
            if (particle.sparkle && Math.random() > 0.7) {
                ctx.shadowBlur = 10;
                ctx.shadowColor = particle.color;
            }
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
            break;

        case 'spiral':
            ctx.strokeStyle = particle.color;
            ctx.lineWidth = particle.size;
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size / 2, 0, Math.PI * 2);
            ctx.stroke();
            break;

        case 'heart':
            ctx.fillStyle = particle.color;
            ctx.shadowBlur = 5;
            ctx.shadowColor = particle.color;
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
            break;

        case 'logo':
            ctx.fillStyle = particle.color;
            ctx.shadowBlur = 8;
            ctx.shadowColor = particle.color;
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
            break;
    }

    ctx.restore();
}

/**
 * Screen shake effect
 */
function addScreenShake() {
    const originalTransform = document.body.style.transform;
    let shakeCount = 0;
    const maxShakes = 10;

    function shake() {
        if (shakeCount >= maxShakes) {
            document.body.style.transform = originalTransform;
            return;
        }

        const x = (Math.random() - 0.5) * 4; // ±2px
        const y = (Math.random() - 0.5) * 4;

        document.body.style.transform = `translate(${x}px, ${y}px)`;
        shakeCount++;

        setTimeout(shake, 50);
    }

    shake();
}

/**
 * Achievement Toast
 */
function showAchievementToast() {
    const toast = document.createElement('div');
    toast.className = 'achievement-toast';
    toast.innerHTML = `
        <div class="achievement-content">
            <div class="achievement-icon">🎉</div>
            <div class="achievement-text">
                <strong>Odkryłeś sekret!</strong>
                <div>Wood Power Fireworks unlocked!</div>
            </div>
        </div>
    `;

    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: linear-gradient(135deg, #ED6B24, #f39c12);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(237, 107, 36, 0.3);
        z-index: 10000;
        animation: achievementSlideIn 0.5s ease-out, achievementSlideOut 0.5s ease-in 3s forwards;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        max-width: 300px;
        border: 2px solid rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(10px);
    `;

    // Style dla contentu
    const style = document.createElement('style');
    style.textContent = `
        .achievement-content {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .achievement-icon {
            font-size: 2rem;
            animation: achievementPulse 2s infinite;
        }
        .achievement-text strong {
            display: block;
            font-size: 1rem;
            margin-bottom: 2px;
        }
        .achievement-text div {
            font-size: 0.85rem;
            opacity: 0.9;
        }
        
        @keyframes achievementSlideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        @keyframes achievementSlideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
        
        @keyframes achievementPulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.2); }
        }
    `;

    document.head.appendChild(style);
    document.body.appendChild(toast);

    // Usuń toast po 4 sekundach
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
        if (style.parentNode) {
            style.parentNode.removeChild(style);
        }
    }, 4000);

    console.log('[Fireworks] 🏆 Achievement toast wyświetlony!');
}

/**
 * Konfetti effect (dodatkowy bonus)
 */
function createConfetti() {
    const colors = FIREWORKS_CONFIG.COLORS;

    // DESZCZ KONFETTI - 150 elementów! (było 50)
    for (let i = 0; i < 150; i++) {
        setTimeout(() => {
            const confetti = document.createElement('div');
            const size = 8 + Math.random() * 12; // Większe konfetti (było 8px)
            const color = colors[Math.floor(Math.random() * colors.length)];

            confetti.style.cssText = `
                position: fixed;
                top: -20px;
                left: ${Math.random() * 100}vw;
                width: ${size}px;
                height: ${size}px;
                background: ${color};
                pointer-events: none;
                z-index: 9998;
                border-radius: ${Math.random() > 0.5 ? '50%' : '0'}; 
                box-shadow: 0 0 ${size}px ${color};
                animation: confettiFall ${3 + Math.random() * 4}s linear forwards;
                transform: rotate(${Math.random() * 360}deg);
            `;

            document.body.appendChild(confetti);

            setTimeout(() => {
                if (confetti.parentNode) {
                    confetti.parentNode.removeChild(confetti);
                }
            }, 8000);
        }, i * 50); // Szybszy spawn (było 100ms)
    }

    // DODAJ ZŁOTE KONFETTI SPECJALNE
    setTimeout(() => {
        for (let i = 0; i < 50; i++) {
            setTimeout(() => {
                const goldConfetti = document.createElement('div');
                goldConfetti.style.cssText = `
                    position: fixed;
                    top: -10px;
                    left: ${Math.random() * 100}vw;
                    width: 15px;
                    height: 15px;
                    background: linear-gradient(45deg, #FFD700, #FFA500);
                    pointer-events: none;
                    z-index: 9998;
                    border-radius: 50%;
                    box-shadow: 0 0 20px #FFD700;
                    animation: confettiFall ${4 + Math.random() * 3}s linear forwards;
                `;

                document.body.appendChild(goldConfetti);

                setTimeout(() => {
                    if (goldConfetti.parentNode) {
                        goldConfetti.parentNode.removeChild(goldConfetti);
                    }
                }, 8000);
            }, i * 80);
        }
    }, 1000);

    // Dodaj style konfetti jeśli nie istnieją
    if (!document.getElementById('confetti-styles')) {
        const style = document.createElement('style');
        style.id = 'confetti-styles';
        style.textContent = `
            @keyframes confettiFall {
                0% {
                    transform: translateY(-20px) rotate(0deg) scale(1);
                    opacity: 1;
                }
                50% {
                    transform: translateY(50vh) rotate(180deg) scale(1.2);
                    opacity: 0.8;
                }
                100% {
                    transform: translateY(120vh) rotate(360deg) scale(0.8);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }
}

/**
 * Zakończenie pokazu fajerwerków
 */
function endFireworks() {
    console.log('[Fireworks] 🎆 Kończę pokaz fajerwerków');

    fireworksState.isActive = false;

    if (fireworksState.animationFrame) {
        cancelAnimationFrame(fireworksState.animationFrame);
    }

    // Fade out canvas
    fireworksState.canvas.style.transition = 'opacity 1s ease-out';
    fireworksState.canvas.style.opacity = '0';

    setTimeout(() => {
        fireworksState.canvas.style.display = 'none';
        fireworksState.canvas.style.opacity = '1';
        fireworksState.canvas.style.transition = '';
        fireworksState.particles = [];
    }, 1000);

    // Bonus konfetti
    createConfetti();
}

/**
 * Obsługa resize okna
 */
function handleFireworksResize() {
    if (fireworksState.canvas) {
        fireworksState.canvas.width = window.innerWidth;
        fireworksState.canvas.height = window.innerHeight;
    }
}

// Event listeners
window.addEventListener('resize', handleFireworksResize);

// Dodaj inicjalizację do głównej funkcji dashboard
document.addEventListener('DOMContentLoaded', function () {
    // Opóźnienie żeby dashboard się załadował
    setTimeout(() => {
        initFireworksSystem();
        console.log('[Fireworks] 🎆 System fajerwerków gotowy!');
    }, 1000);
});

// Debug funkcje (możesz usunąć w produkcji)
window.debugFireworks = {
    trigger: () => triggerFireworks(),
    test: (type) => {
        createFireworksCanvas();
        fireworksState.canvas.style.display = 'block';
        fireworksState.isActive = true;
        createFirework(type, window.innerWidth / 2, window.innerHeight / 2);
        startFireworksAnimation();
        setTimeout(endFireworks, 3000);
    },

    // NOWE DEBUG FUNKCJE
    checkLogo: () => {
        console.log('=== FIREWORKS LOGO DEBUG ===');
        console.log('Logo path:', FIREWORKS_CONFIG.LOGO_PATH);
        console.log('Logo loaded:', fireworksState.logoLoaded);
        console.log('Logo error:', fireworksState.logoError);
        console.log('Logo image object:', fireworksState.logoImage);

        if (fireworksState.logoImage) {
            console.log('Logo dimensions:', fireworksState.logoImage.width, 'x', fireworksState.logoImage.height);
        }

        // Test fetch
        fetch(FIREWORKS_CONFIG.LOGO_PATH)
            .then(r => console.log('Fetch test result:', r.status, r.ok))
            .catch(e => console.log('Fetch test error:', e));
    },

    testAllLogos: () => {
        const paths = [
            '/static/images/logo.svg',
            '/static/images/logo.png',
            './static/images/logo.svg',
            '../static/images/logo.svg',
            '/app/static/images/logo.svg'
        ];

        paths.forEach(path => {
            fetch(path)
                .then(r => console.log(`✅ FOUND: ${path} (${r.status})`))
                .catch(() => console.log(`❌ NOT FOUND: ${path}`));
        });
    },

    reloadLogo: () => {
        console.log('Reloading logo...');
        fireworksState.logoLoaded = false;
        fireworksState.logoError = false;
        fireworksState.logoImage = null;
        debugAndLoadLogo();
    },

    state: () => fireworksState,
    config: () => FIREWORKS_CONFIG
};

console.log('[Dashboard] Enhanced JavaScript loaded successfully');