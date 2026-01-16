// modules/reports/static/js/postcode_auto_fill.js
/**
 * Automatyczne uzupełnianie województwa na podstawie kodu pocztowego
 * Integruje się z formularzem dodawania/edycji zamówień
 */

class PostcodeAutoFill {
    constructor() {
        // Mapowanie przedziałów kodów pocztowych na województwa
        this.postcodeRanges = {
            'Dolnośląskie': [[50, 59]],
            'Kujawsko-Pomorskie': [[85, 87]],
            'Lubelskie': [[20, 23]],
            'Lubuskie': [[65, 68]],
            'Łódzkie': [[90, 99]],
            'Małopolskie': [[30, 34]],
            'Mazowieckie': [[0, 9], [26, 27]],
            'Opolskie': [[45, 49]],
            'Podkarpackie': [[35, 39]],
            'Podlaskie': [[15, 19]],
            'Pomorskie': [[80, 84]],
            'Śląskie': [[40, 44]],
            'Świętokrzyskie': [[25, 25], [28, 29]],
            'Warmińsko-Mazurskie': [[10, 14]],
            'Wielkopolskie': [[60, 64]],
            'Zachodniopomorskie': [[70, 79]]
        };

        this.init();
    }

    init() {
        // Znajdź pole kodu pocztowego i województwa
        this.postcodeInput = document.getElementById('deliveryPostcode');
        this.stateInput = document.getElementById('deliveryState');

        if (this.postcodeInput && this.stateInput) {
            // Dodaj event listener na zmianę kodu pocztowego
            this.postcodeInput.addEventListener('input', (e) => {
                this.handlePostcodeChange(e.target.value);
            });

            // Dodaj event listener na blur (utrata fokusa)
            this.postcodeInput.addEventListener('blur', (e) => {
                this.handlePostcodeChange(e.target.value);
            });

            console.log('[PostcodeAutoFill] Inicjalizacja zakończona');
        } else {
            console.warn('[PostcodeAutoFill] Nie znaleziono pól formularza');
        }
    }

    /**
     * Obsługuje zmianę kodu pocztowego
     */
    handlePostcodeChange(postcode) {
        const cleanPostcode = this.cleanPostcode(postcode);

        if (!cleanPostcode || cleanPostcode.length < 2) {
            return;
        }

        const state = this.getStateFromPostcode(cleanPostcode);

        if (state) {
            // Sprawdź czy pole województwa jest puste lub ma inną wartość
            const currentState = this.stateInput.value.trim();

            if (!currentState || this.shouldOverrideState(currentState, state)) {
                this.stateInput.value = state;

                // Dodaj wizualną informację o auto-uzupełnieniu
                this.showAutoFillNotification(state);

                console.log(`[PostcodeAutoFill] Auto-uzupełniono: ${postcode} → ${state}`);
            }
        }
    }

    /**
     * Czyści kod pocztowy - zostawia tylko cyfry
     */
    cleanPostcode(postcode) {
        if (!postcode) return '';
        return postcode.replace(/[^0-9]/g, '');
    }

    /**
     * Zwraca województwo na podstawie kodu pocztowego
     */
    getStateFromPostcode(cleanPostcode) {
        if (cleanPostcode.length < 2) return null;

        const prefix = parseInt(cleanPostcode.substring(0, 2));

        for (const [state, ranges] of Object.entries(this.postcodeRanges)) {
            for (const [start, end] of ranges) {
                if (prefix >= start && prefix <= end) {
                    return state;
                }
            }
        }

        return null;
    }

    /**
     * Sprawdza czy należy nadpisać istniejące województwo
     */
    shouldOverrideState(currentState, newState) {
        // Nie nadpisuj jeśli to to samo województwo
        if (currentState.toLowerCase() === newState.toLowerCase()) {
            return false;
        }

        // Lista "niepewnych" wartości, które można nadpisać
        const uncertainValues = [
            'brak',
            'nieznane',
            'inne',
            'test',
            'temp',
            'tymczasowe'
        ];

        return uncertainValues.some(uncertain =>
            currentState.toLowerCase().includes(uncertain)
        );
    }

    /**
     * Pokazuje powiadomienie o automatycznym uzupełnieniu
     */
    showAutoFillNotification(state) {
        // Usuń poprzednie powiadomienie jeśli istnieje
        const existingNotification = document.querySelector('.auto-fill-notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        // Stwórz nowe powiadomienie
        const notification = document.createElement('div');
        notification.className = 'auto-fill-notification';
        notification.innerHTML = `
            <i class="fas fa-map-marker-alt"></i>
            Auto-uzupełniono: <strong>${state}</strong>
        `;

        // Dodaj style
        notification.style.cssText = `
            position: absolute;
            top: -35px;
            left: 0;
            background: #4CAF50;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 1000;
            animation: fadeInOut 3s ease-in-out;
        `;

        // Dodaj animację CSS jeśli nie istnieje
        if (!document.querySelector('#auto-fill-animation-style')) {
            const style = document.createElement('style');
            style.id = 'auto-fill-animation-style';
            style.textContent = `
                @keyframes fadeInOut {
                    0% { opacity: 0; transform: translateY(-10px); }
                    20% { opacity: 1; transform: translateY(0); }
                    80% { opacity: 1; transform: translateY(0); }
                    100% { opacity: 0; transform: translateY(-10px); }
                }
            `;
            document.head.appendChild(style);
        }

        // Znajdź kontener dla powiadomienia
        const stateContainer = this.stateInput.parentElement;
        stateContainer.style.position = 'relative';
        stateContainer.appendChild(notification);

        // Usuń powiadomienie po 3 sekundach
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 3000);
    }

    /**
     * Testuje mapowanie dla różnych kodów pocztowych
     */
    test() {
        const testCases = [
            '00-001', // Warszawa -> Mazowieckie
            '30-001', // Kraków -> Małopolskie  
            '50-001', // Wrocław -> Dolnośląskie
            '60-001', // Poznań -> Wielkopolskie
            '80-001', // Gdańsk -> Pomorskie
            '90-001', // Łódź -> Łódzkie
            '40-001', // Katowice -> Śląskie
            '20-001', // Lublin -> Lubelskie
        ];

        console.log('🧪 TEST MAPOWANIA KODÓW POCZTOWYCH:');
        testCases.forEach(postcode => {
            const state = this.getStateFromPostcode(this.cleanPostcode(postcode));
            console.log(`${postcode} → ${state || 'NIEZNANE'}`);
        });
    }
}

// Inicjalizuj gdy DOM jest gotowy
document.addEventListener('DOMContentLoaded', function () {
    // Inicjalizuj auto-uzupełnianie województwa
    window.postcodeAutoFill = new PostcodeAutoFill();

    // Testuj w trybie dev (odkomentuj jeśli potrzebne)
    // window.postcodeAutoFill.test();
});

// Eksportuj dla użycia w innych skryptach
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PostcodeAutoFill;
}