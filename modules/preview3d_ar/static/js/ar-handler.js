// app/modules/preview3d_ar/static/js/ar-handler.js
// POPRAWIONA WERSJA z popup potwierdzającym

class ARHandler {
    constructor() {
        this.isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        this.isAndroid = /Android/.test(navigator.userAgent);
        this.isMobile = this.isIOS || this.isAndroid;

        this.iosVersion = this.getIOSVersion();
        this.isSafari = /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent);

        // Punkt końcowy API
        this.apiEndpoint = '/preview3d-ar/api';

        // Cache URL-i
        this.modelCache = new Map();

        console.log('[ARHandler] Inicjalizacja AR Handler z popup');
        console.log('[ARHandler] iOS:', this.iosVersion, 'Safari:', this.isSafari);
    }

    /**
     * NOWA: Główna metoda z popup potwierdzającym
     */
    async initiateAR(productData) {
        console.log('[ARHandler] Inicjowanie AR z popup dla produktu:', productData);

        if (!this.isMobile) {
            this.showDesktopMessage();
            return;
        }

        if (!productData) {
            this.showError('Brak danych produktu do wyświetlenia w AR');
            return;
        }

        // NOWE: Pokaż popup potwierdzający
        this.showARConfirmationPopup(productData);
    }

    /**
     * Bezpośrednie AR z touch event (iOS optimized)
     */
    launchARWithTouchEvent(modelUrl, productData) {
        console.log('[ARHandler] Launch AR z touch event dla iOS');

        // Utwórz przycisk który symuluje user interaction
        const arButton = document.createElement('button');
        arButton.style.position = 'fixed';
        arButton.style.top = '50%';
        arButton.style.left = '50%';
        arButton.style.transform = 'translate(-50%, -50%)';
        arButton.style.zIndex = '999999';
        arButton.style.padding = '20px';
        arButton.style.fontSize = '18px';
        arButton.style.backgroundColor = '#007AFF';
        arButton.style.color = 'white';
        arButton.style.border = 'none';
        arButton.style.borderRadius = '10px';
        arButton.style.cursor = 'pointer';
        arButton.textContent = 'Uruchom AR';

        // Dodaj do DOM
        document.body.appendChild(arButton);

        // Event listener z prawdziwym user gesture
        arButton.addEventListener('click', () => {
            console.log('[ARHandler] User kliknął przycisk AR');

            // Teraz możemy bezpiecznie przekierować
            window.location.href = modelUrl;

            // Usuń przycisk
            document.body.removeChild(arButton);
        });

        // Auto-click po krótkim czasie (fallback)
        setTimeout(() => {
            if (document.body.contains(arButton)) {
                arButton.click();
            }
        }, 500);
    }

    /**
     * NOWA METODA: Popup potwierdzający AR
     */
    showARConfirmationPopup(productData) {
        const variant = productData.variant_code || 'Produkt';
        const dims = productData.dimensions || {};
        const dimensions = `${dims.length || 0}×${dims.width || 0}×${dims.thickness || 0} cm`;

        const modal = this.createARModal('Otwórz w rzeczywistości rozszerzonej', {
            icon: '📱',
            title: 'Czy chcesz otworzyć model w AR?',
            message: `Model: ${variant}\nWymiary: ${dimensions}`,
            details: [
                '📱 Wymagane: iPhone/iPad z iOS 12+',
                '🌐 Potrzebne: Safari (nie Chrome)',
                '🚀 Technologia: Apple QuickLook AR',
                '⚡ Model zostanie pobrany automatycznie'
            ],
            buttons: [
                {
                    text: 'Anuluj',
                    action: () => this.closeModal(),
                    primary: false
                },
                {
                    text: 'Otwórz AR',
                    action: () => this.confirmOpenAR(productData),
                    primary: true
                }
            ]
        });

        this.showModal(modal);
    }

    /**
     * NOWA METODA: Potwierdzenie otwarcia AR
     */
    async confirmOpenAR(productData) {
        console.log('[ARHandler] Użytkownik potwierdził otwarcie AR');

        // Zamknij popup
        this.closeModal();

        const arSupport = this.getARSupport();
        console.log('[ARHandler] AR Support:', arSupport);

        try {
            // Pokaż loading
            this.showLoadingModal('Przygotowywanie modelu AR...');

            if (arSupport.ios) {
                // iOS Safari - USDZ + QuickLook
                console.log('[ARHandler] Używam iOS QuickLook AR');
                await this.initiateIOSAR(productData);
            } else if (arSupport.android) {
                // Android Chrome - GLB + model-viewer
                console.log('[ARHandler] Używam Android model-viewer AR');
                this.hideLoadingModal();
                await this.initiateAndroidAR(productData);
            } else {
                // Nieobsługiwane urządzenie
                this.hideLoadingModal();
                this.showUnsupportedMessage();
            }

        } catch (err) {
            this.hideLoadingModal();
            console.error('[ARHandler] Błąd AR:', err);
            this.showError('Błąd generowania modelu AR: ' + err.message);
        }
    }

    /**
     * POPRAWIONA: AR dla iOS z lepszym plikiem USDZ
     */
    async initiateIOSAR(productData) {
        console.log('[ARHandler] iOS AR - generowanie poprawnego USDZ');

        try {
            // Użyj USDZ zamiast Reality (bardziej stabilne)
            const usdzUrl = await this.generateUSDZFile(productData);

            this.hideLoadingModal();

            // BEZPOŚREDNIE uruchomienie AR bez przekierowań
            this.launchARWithTouchEvent(usdzUrl, productData);

        } catch (err) {
            this.hideLoadingModal();
            console.error('[ARHandler] Błąd iOS AR:', err);
            this.showError('Błąd generowania modelu AR: ' + err.message);
        }
    }

    /**
     * POPRAWIONA: Generowanie USDZ z lepszymi parametrami
     */
    async generateUSDZFile(productData) {
        const key = this._getCacheKey(productData, 'usdz');
        if (this.modelCache.has(key)) {
            console.log('[ARHandler] USDZ z cache:', this.modelCache.get(key));
            return this.modelCache.get(key);
        }

        console.log('[ARHandler] Generowanie nowego pliku USDZ...');

        const requestData = {
            variant_code: productData.variant_code,
            dimensions: {
                length: productData.dimensions.length,
                width: productData.dimensions.width,
                thickness: productData.dimensions.thickness
            },
            // NOWE: Dodatkowe parametry dla lepszej jakości
            quality: 'high',
            format: 'usdz',
            optimize_for_ar: true
        };

        const res = await fetch(`${this.apiEndpoint}/generate-usdz`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(requestData)
        });

        if (!res.ok) {
            const errorText = await res.text();
            console.error('[ARHandler] USDZ API error:', res.status, errorText);
            throw new Error(`Błąd API (${res.status}): ${errorText}`);
        }

        const result = await res.json();
        console.log('[ARHandler] USDZ API response:', result);

        if (!result.success || !result.usdz_url) {
            throw new Error('Brak usdz_url w odpowiedzi API');
        }

        // Sprawdź czy plik istnieje
        await this.validateARFile(result.usdz_url);

        this.modelCache.set(key, result.usdz_url);
        console.log('[ARHandler] USDZ file wygenerowany:', result.usdz_url);

        return result.usdz_url;
    }

    /**
     * NOWA METODA: Walidacja pliku AR
     */
    async validateARFile(fileUrl) {
        console.log('[ARHandler] Walidacja pliku AR:', fileUrl);

        try {
            const response = await fetch(fileUrl, { method: 'HEAD' });

            if (!response.ok) {
                throw new Error(`Plik AR niedostępny (${response.status})`);
            }

            const contentType = response.headers.get('content-type');
            const contentLength = response.headers.get('content-length');

            console.log('[ARHandler] Plik AR - Type:', contentType, 'Size:', contentLength);

            // Sprawdź MIME type
            if (!contentType || (!contentType.includes('usdz') && !contentType.includes('octet-stream'))) {
                console.warn('[ARHandler] Nieprawidłowy MIME type:', contentType);
            }

            // Sprawdź rozmiar
            if (!contentLength || parseInt(contentLength) < 1000) {
                throw new Error('Plik AR jest za mały (prawdopodobnie uszkodzony)');
            }

            console.log('[ARHandler] Plik AR zwalidowany pomyślnie');

        } catch (error) {
            console.error('[ARHandler] Błąd walidacji pliku AR:', error);
            throw error;
        }
    }

    /**
     * POPRAWIONA: Bezpośrednie otwarcie QuickLook AR
     */
    openQuickLookARDirect(modelUrl, productData) {
        console.log('[ARHandler] Bezpośrednie otwarcie QuickLook AR:', modelUrl);

        // Metoda 1: Próba bezpośredniego URL scheme (najlepsze dla iOS)
        if (this.isIOS && this.isSafari) {
            console.log('[ARHandler] Używam bezpośredniego URL scheme dla iOS');

            try {
                // KLUCZOWE: Użyj window.location.href zamiast kliknięcia w link
                // To wymusza bezpośrednie otwarcie w AR zamiast w przeglądarce
                window.location.href = modelUrl;
                console.log('[ARHandler] Przekierowano bezpośrednio na URL USDZ');
                return;
            } catch (error) {
                console.error('[ARHandler] Błąd bezpośredniego przekierowania:', error);
            }
        }

        // Metoda 2: Fallback z ukrytym linkiem (dla starszych wersji iOS)
        console.log('[ARHandler] Używam fallback metody z ukrytym linkiem');

        // Usuń stary link jeśli istnieje
        const existingLink = document.getElementById('ar-quicklook-link');
        if (existingLink) {
            existingLink.remove();
        }

        // Utwórz nowy link AR z optymalnymi atrybutami
        const link = document.createElement('a');
        link.id = 'ar-quicklook-link';
        link.href = modelUrl;
        link.rel = 'ar';
        link.type = 'model/vnd.usdz+zip';

        // Metadane AR
        const variant = productData?.variant_code || 'Wood Panel';
        const dims = productData?.dimensions || {};
        const subtitle = `${dims.length || 0}×${dims.width || 0}×${dims.thickness || 0} cm`;

        link.setAttribute('data-ar-title', variant);
        link.setAttribute('data-ar-subtitle', subtitle);
        link.setAttribute('data-ar-placement', 'floor');
        link.setAttribute('data-ar-scale', 'auto');

        // KLUCZOWE dla bezpośredniego AR: dodaj atrybut download
        link.download = `${variant}.usdz`;

        // Link musi być niewidoczny ale w DOM
        link.style.position = 'absolute';
        link.style.top = '-1000px';
        link.style.left = '-1000px';
        link.style.width = '1px';
        link.style.height = '1px';
        link.style.opacity = '0';
        link.style.pointerEvents = 'auto'; // WAŻNE: Pozwól na interakcję

        // Dodaj do DOM
        document.body.appendChild(link);

        console.log('[ARHandler] Link AR utworzony:', {
            href: link.href,
            rel: link.rel,
            type: link.type,
            download: link.download
        });

        // NATYCHMIASTOWE kliknięcie z user gesture
        setTimeout(() => {
            try {
                console.log('[ARHandler] Programmatic click na link AR...');

                // METODA 1: Focus + click (symuluje user interaction)
                link.focus();
                link.click();

                // METODA 2: Dispatch click event z bubbles
                setTimeout(() => {
                    const clickEvent = new MouseEvent('click', {
                        view: window,
                        bubbles: true,
                        cancelable: true,
                        detail: 1
                    });
                    link.dispatchEvent(clickEvent);
                    console.log('[ARHandler] Click events wysłane');
                }, 50);

                // Cleanup po 5 sekundach
                setTimeout(() => {
                    if (document.body.contains(link)) {
                        document.body.removeChild(link);
                    }
                }, 5000);

            } catch (error) {
                console.error('[ARHandler] Błąd kliknięcia AR:', error);
            }
        }, 100);
    }

    /**
     * Pomocnicze metody UI
     */
    createARModal(title, options) {
        const modal = document.createElement('div');
        modal.className = 'ar-modal-overlay';

        const detailsHtml = options.details ? options.details.map(detail =>
            '<div class="ar-detail-item">' + detail + '</div>'
        ).join('') : '';

        const buttonsHtml = options.buttons ? options.buttons.map(btn =>
            '<button class="ar-modal-btn ' + (btn.primary ? 'primary' : '') + '" data-action="' + btn.text + '">' +
            btn.text +
            '</button>'
        ).join('') : '';

        modal.innerHTML =
            '<div class="ar-modal-content">' +
            '<div class="ar-modal-header">' +
            '<div class="ar-modal-icon">' + options.icon + '</div>' +
            '<h2 class="ar-modal-title">' + title + '</h2>' +
            '</div>' +
            '<div class="ar-modal-body">' +
            '<div class="ar-modal-message" style="white-space: pre-line;">' + options.message + '</div>' +
            (detailsHtml ? '<div class="ar-modal-details">' + detailsHtml + '</div>' : '') +
            '</div>' +
            '<div class="ar-modal-footer">' +
            buttonsHtml +
            '</div>' +
            '</div>';

        // Event listenery dla przycisków
        if (options.buttons) {
            options.buttons.forEach(btn => {
                const btnElement = modal.querySelector('[data-action="' + btn.text + '"]');
                if (btnElement) {
                    btnElement.addEventListener('click', btn.action);
                }
            });
        }

        return modal;
    }

    showLoadingModal(message) {
        const modal = document.createElement('div');
        modal.className = 'ar-loading-overlay';
        modal.innerHTML =
            '<div class="ar-loading-content">' +
            '<div class="ar-loading-spinner"></div>' +
            '<div class="ar-loading-message">' + message + '</div>' +
            '</div>';

        modal.id = 'ar-loading-modal';
        document.body.appendChild(modal);
    }

    hideLoadingModal() {
        const modal = document.getElementById('ar-loading-modal');
        if (modal) {
            modal.remove();
        }
    }

    showModal(modal) {
        this.closeModal();
        modal.id = 'ar-modal';
        document.body.appendChild(modal);

        // ESC key handler
        this._escHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
            }
        };
        document.addEventListener('keydown', this._escHandler);

        // Click outside handler
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeModal();
            }
        });
    }

    closeModal() {
        const modal = document.getElementById('ar-modal');
        if (modal) {
            modal.remove();
            if (this._escHandler) {
                document.removeEventListener('keydown', this._escHandler);
                this._escHandler = null;
            }
        }
    }

    showDesktopMessage() {
        const modal = this.createARModal('AR dostępne na urządzeniach mobilnych', {
            icon: '🖥️',
            title: 'Rzeczywistość rozszerzona wymaga urządzenia mobilnego',
            message: 'Funkcja AR działa na iPhone i iPad z iOS 12+ oraz Safari.',
            details: [
                '📱 iPhone/iPad z iOS 12+',
                '🌐 Safari (nie Chrome)',
                '🔧 Viewer 3D działa na wszystkich urządzeniach'
            ],
            buttons: [
                {
                    text: 'Rozumiem',
                    action: () => this.closeModal(),
                    primary: true
                }
            ]
        });

        this.showModal(modal);
    }

    showUnsupportedMessage() {
        let details = [];
        let message = 'Twoje urządzenie nie spełnia wymagań dla rzeczywistości rozszerzonej.';

        if (!this.isIOS) {
            details.push('❌ Wykryto: ' + (this.isAndroid ? 'Android' : 'Desktop'));
            details.push('✅ Wymagane: iPhone/iPad');
        } else if (this.iosVersion < 12) {
            details.push('❌ iOS ' + this.iosVersion + ' (za stara wersja)');
            details.push('✅ Wymagane: iOS 12 lub nowszy');
        } else if (!this.isSafari) {
            details.push('❌ Wykryta przeglądarka: ' + this.getBrowserName());
            details.push('✅ Wymagana: Safari');
            message = 'AR działa tylko w przeglądarce Safari na iOS.';
        }

        const modal = this.createARModal('AR nie jest obsługiwane', {
            icon: '⚠️',
            title: 'Urządzenie nie obsługuje AR',
            message: message,
            details: details,
            buttons: [
                {
                    text: 'Zamknij',
                    action: () => this.closeModal(),
                    primary: true
                }
            ]
        });

        this.showModal(modal);
    }

    showError(message) {
        const modal = this.createARModal('Błąd AR', {
            icon: '🚫',
            title: 'Wystąpił błąd',
            message: message,
            details: [
                'Spróbuj ponownie za chwilę',
                'Sprawdź połączenie internetowe',
                'Upewnij się, że używasz Safari na iOS',
                'Skontaktuj się z pomocą techniczną jeśli problem się powtarza'
            ],
            buttons: [
                {
                    text: 'Zamknij',
                    action: () => this.closeModal(),
                    primary: true
                }
            ]
        });

        this.showModal(modal);
    }

    /**
 * NOWA METODA: Sprawdza wsparcie AR dla różnych platform
 */
    getARSupport() {
        return {
            ios: this.isIOS && this.iosVersion >= 12 && this.isSafari,
            android: this.isAndroid && this.getBrowserName() === 'Chrome',
            webxr: 'xr' in navigator && 'requestSession' in navigator.xr,
            modelViewer: true // Google model-viewer działa wszędzie
        };
    }

    /**
     * NOWA METODA: Inicjuje AR dla Android używając model-viewer
     */
    async initiateAndroidAR(productData) {
        console.log('[ARHandler] Android AR - używanie model-viewer');

        try {
            // Sprawdź czy model-viewer jest załadowany
            if (!customElements.get('model-viewer')) {
                console.log('[ARHandler] Ładowanie model-viewer...');
                await this.loadModelViewer();
            }

            // Wygeneruj GLB file dla Android (zamiast USDZ)
            const glbUrl = await this.generateGLBFile(productData);

            // Pokaż AR viewer
            this.showAndroidARViewer(glbUrl, productData);

        } catch (error) {
            console.error('[ARHandler] Błąd Android AR:', error);
            throw error;
        }
    }

    /**
     * NOWA METODA: Ładuje Google model-viewer
     */
    async loadModelViewer() {
        return new Promise((resolve, reject) => {
            if (customElements.get('model-viewer')) {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.type = 'module';
            script.src = 'https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js';

            script.onload = () => {
                console.log('[ARHandler] model-viewer załadowany');
                resolve();
            };

            script.onerror = () => {
                reject(new Error('Nie udało się załadować model-viewer'));
            };

            document.head.appendChild(script);
        });
    }

    /**
     * NOWA METODA: Generuje GLB file dla Android
     */
    async generateGLBFile(productData) {
        const key = this._getCacheKey(productData, 'glb');
        if (this.modelCache.has(key)) {
            console.log('[ARHandler] GLB z cache:', this.modelCache.get(key));
            return this.modelCache.get(key);
        }

        console.log('[ARHandler] Generowanie nowego pliku GLB...');

        const requestData = {
            variant_code: productData.variant_code,
            dimensions: {
                length: productData.dimensions.length,
                width: productData.dimensions.width,
                thickness: productData.dimensions.thickness
            },
            quality: 'high',
            format: 'glb',
            optimize_for_ar: true
        };

        const res = await fetch(`${this.apiEndpoint}/generate-glb`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(requestData)
        });

        if (!res.ok) {
            const errorText = await res.text();
            console.error('[ARHandler] GLB API error:', res.status, errorText);
            throw new Error(`Błąd API (${res.status}): ${errorText}`);
        }

        const result = await res.json();
        console.log('[ARHandler] GLB API response:', result);

        if (!result.success || !result.glb_url) {
            throw new Error('Brak glb_url w odpowiedzi API');
        }

        this.modelCache.set(key, result.glb_url);
        console.log('[ARHandler] GLB file wygenerowany:', result.glb_url);

        return result.glb_url;
    }

    /**
     * NOWA METODA: Pokazuje AR viewer dla Android
     */
    showAndroidARViewer(glbUrl, productData) {
        console.log('[ARHandler] Tworzenie Android AR viewer');

        // Usuń poprzedni viewer jeśli istnieje
        const existingViewer = document.getElementById('android-ar-viewer');
        if (existingViewer) {
            existingViewer.remove();
        }

        // Utwórz kontener modal
        const modal = document.createElement('div');
        modal.id = 'android-ar-viewer';
        modal.className = 'android-ar-modal';

        const variant = productData?.variant_code || 'Wood Panel';
        const dims = productData?.dimensions || {};
        const dimensions = `${dims.length || 0}×${dims.width || 0}×${dims.thickness || 0} cm`;

        modal.innerHTML = `
        <div class="android-ar-content">
            <div class="android-ar-header">
                <h2>${variant}</h2>
                <p>${dimensions}</p>
                <button class="android-ar-close" onclick="this.closest('#android-ar-viewer').remove()">✕</button>
            </div>
            <div class="android-ar-viewer-container">
                <model-viewer
                    src="${glbUrl}"
                    alt="${variant} - ${dimensions}"
                    ar
                    ar-modes="webxr scene-viewer quick-look"
                    camera-controls
                    auto-rotate
                    shadow-intensity="1"
                    environment-image="neutral"
                    exposure="1"
                    style="width: 100%; height: 400px; background-color: #f0f0f0;">
                    
                    <button slot="ar-button" class="android-ar-button">
                        📱 Pokaż w AR
                    </button>
                    
                    <div class="android-ar-loading" slot="poster">
                        <div class="loading-spinner"></div>
                        <p>Ładowanie modelu 3D...</p>
                    </div>
                </model-viewer>
            </div>
            <div class="android-ar-info">
                <p>🤖 <strong>Android AR:</strong> Naciśnij przycisk "Pokaż w AR" aby uruchomić rzeczywistość rozszerzoną</p>
                <p>📱 <strong>Wymagania:</strong> Android 7.0+ z Google Chrome lub ARCore</p>
            </div>
        </div>
    `;

        // Dodaj style CSS
        this.addAndroidARStyles();

        // Dodaj do DOM
        document.body.appendChild(modal);

        console.log('[ARHandler] Android AR viewer utworzony');
    }

    /**
     * NOWA METODA: Dodaje style CSS dla Android AR
     */
    addAndroidARStyles() {
        if (document.getElementById('android-ar-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'android-ar-styles';
        styles.textContent = `
        .android-ar-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10000;
            padding: 20px;
            box-sizing: border-box;
        }

        .android-ar-content {
            background: white;
            border-radius: 12px;
            width: 100%;
            max-width: 500px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }

        .android-ar-header {
            padding: 20px;
            border-bottom: 1px solid #eee;
            position: relative;
            text-align: center;
        }

        .android-ar-header h2 {
            margin: 0 0 8px 0;
            color: #333;
            font-size: 18px;
        }

        .android-ar-header p {
            margin: 0;
            color: #666;
            font-size: 14px;
        }

        .android-ar-close {
            position: absolute;
            top: 15px;
            right: 15px;
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: #666;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .android-ar-viewer-container {
            padding: 0;
        }

        .android-ar-button {
            background: #4285f4;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            margin: 10px;
            box-shadow: 0 2px 8px rgba(66, 133, 244, 0.3);
        }

        .android-ar-loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 400px;
            color: #666;
        }

        .android-ar-loading .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #4285f4;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 16px;
        }

        .android-ar-info {
            padding: 20px;
            background: #f8f9fa;
            border-top: 1px solid #eee;
        }

        .android-ar-info p {
            margin: 8px 0;
            font-size: 13px;
            color: #555;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        @media (max-width: 768px) {
            .android-ar-modal {
                padding: 10px;
            }
            .android-ar-content {
                max-height: 95vh;
            }
        }
    `;

        document.head.appendChild(styles);
    }

    // Pomocnicze metody
    getIOSVersion() {
        if (!this.isIOS) return 0;
        const match = navigator.userAgent.match(/OS (\d+)_/);
        return match ? parseInt(match[1]) : 0;
    }

    getBrowserName() {
        const ua = navigator.userAgent;
        if (ua.includes('Chrome')) return 'Chrome';
        if (ua.includes('Firefox')) return 'Firefox';
        if (ua.includes('Safari')) return 'Safari';
        if (ua.includes('Edge')) return 'Edge';
        return 'Nieznana';
    }

    _getCacheKey(productData, format) {
        const variant = productData.variant_code || 'unknown';
        const dims = productData.dimensions || {};
        const l = dims.length || 0;
        const w = dims.width || 0;
        const t = dims.thickness || 0;
        return `${variant}-${l}x${w}x${t}-${format}`;
    }

    getStatus() {
        return {
            platform: this.isIOS ? `iOS ${this.iosVersion}` : 'Other',
            browser: this.getBrowserName(),
            safari: this.isSafari,
            arSupported: this.isIOS && this.iosVersion >= 12 && this.isSafari,
            cacheSize: this.modelCache.size,
            apiEndpoint: this.apiEndpoint
        };
    }

    // Debug methods
    clearCache() {
        this.modelCache.clear();
        console.log('[ARHandler] Cache wyczyszczony');
    }

    debugInfo() {
        console.log('[ARHandler] Debug Info:', this.getStatus());
        return this.getStatus();
    }
}

// Globalna instancja
window.ARHandler = new ARHandler();

console.log('[ARHandler] AR Handler z popup załadowany');

// Debug methods
window.debugARHandler = () => window.ARHandler.debugInfo();
window.clearARCache = () => window.ARHandler.clearCache();