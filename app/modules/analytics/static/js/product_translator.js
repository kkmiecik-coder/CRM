// modules/analytics/static/js/product_translator.js

/**
 * PRODUCT TRANSLATOR - System tłumaczenia kodów produktów
 * Konwertuje kody typu "dab-lity-ab" na czytelne nazwy "Dąb lity A/B"
 */

class ProductTranslator {
    constructor() {
        this.translations = {
            // Gatunki drewna
            species: {
                'dab': 'Dąb',
                'buk': 'Buk',
                'jes': 'Jesion',
                'brzoza': 'Brzoza',
                'sosna': 'Sosna',
                'swierk': 'Świerk',
                'modrzew': 'Modrzew',
                'grab': 'Grab',
                'klon': 'Klon',
                'wiaz': 'Wiąz',
                'olsza': 'Olsza',
                'topola': 'Topola',
                'lipa': 'Lipa'
            },

            // Technologie
            technology: {
                'lity': 'lity',
                'lam': 'laminowany',
                'klejony': 'klejony',
                'finger': 'finger joint',
                'micro': 'mikrowczep',
                'panel': 'panel',
                'deck': 'deck',
                'parkiet': 'parkiet'
            },

            // Klasy drewna
            woodClass: {
                'a': 'A',
                'b': 'B',
                'c': 'C',
                'ab': 'A/B',
                'bb': 'B/B',
                'bc': 'B/C',
                'rustic': 'Rustic',
                'select': 'Select',
                'nature': 'Nature',
                'prime': 'Prime'
            }
        };

        // Wzorce do rozpoznawania kodów
        this.patterns = [
            // Wzorzec: gatunek-technologia-klasa (np. dab-lity-ab)
            /^([a-z]+)-([a-z]+)-([a-z]+)$/i,
            // Wzorzec: gatunek-klasa (np. dab-ab)  
            /^([a-z]+)-([a-z]+)$/i,
            // Wzorzec: gatunek-technologia (np. dab-lam)
            /^([a-z]+)-([a-z]+)$/i
        ];
    }

    /**
     * Główna funkcja tłumaczenia kodu na nazwę
     */
    translateCode(code) {
        if (!code || typeof code !== 'string') {
            return code || '-';
        }

        const cleanCode = code.toLowerCase().trim();

        // Spróbuj różnych wzorców
        let translated = this.tryPattern1(cleanCode); // gatunek-technologia-klasa
        if (translated !== cleanCode) return translated;

        translated = this.tryPattern2(cleanCode); // gatunek-klasa
        if (translated !== cleanCode) return translated;

        translated = this.tryPattern3(cleanCode); // gatunek-technologia
        if (translated !== cleanCode) return translated;

        // Jeśli nic nie pasuje, zwróć oryginalny kod
        return this.capitalizeFirst(code);
    }

    /**
     * Wzorzec 1: gatunek-technologia-klasa (np. dab-lity-ab)
     */
    tryPattern1(code) {
        const match = code.match(/^([a-z]+)-([a-z]+)-([a-z]+)$/);
        if (!match) return code;

        const [, species, technology, woodClass] = match;

        const speciesName = this.translations.species[species];
        const technologyName = this.translations.technology[technology];
        const className = this.translations.woodClass[woodClass];

        if (speciesName && technologyName && className) {
            return `${speciesName} ${technologyName} ${className}`;
        }

        return code;
    }

    /**
     * Wzorzec 2: gatunek-klasa (np. dab-ab, buk-bb)
     */
    tryPattern2(code) {
        const match = code.match(/^([a-z]+)-([a-z]+)$/);
        if (!match) return code;

        const [, part1, part2] = match;

        const speciesName = this.translations.species[part1];
        const className = this.translations.woodClass[part2];

        // Sprawdź czy to gatunek + klasa
        if (speciesName && className) {
            return `${speciesName} ${className}`;
        }

        return code;
    }

    /**
     * Wzorzec 3: gatunek-technologia (np. dab-lam, buk-finger)
     */
    tryPattern3(code) {
        const match = code.match(/^([a-z]+)-([a-z]+)$/);
        if (!match) return code;

        const [, part1, part2] = match;

        const speciesName = this.translations.species[part1];
        const technologyName = this.translations.technology[part2];

        // Sprawdź czy to gatunek + technologia
        if (speciesName && technologyName) {
            return `${speciesName} ${technologyName}`;
        }

        return code;
    }

    /**
     * Kapitalizacja pierwszej litery
     */
    capitalizeFirst(str) {
        if (!str) return str;
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    /**
     * Dodanie nowego tłumaczenia
     */
    addTranslation(type, code, translation) {
        if (this.translations[type]) {
            this.translations[type][code.toLowerCase()] = translation;
        }
    }

    /**
     * Sprawdzenie czy kod jest rozpoznawalny
     */
    isRecognizedCode(code) {
        if (!code) return false;

        const translated = this.translateCode(code);
        return translated !== code && translated !== this.capitalizeFirst(code);
    }

    /**
     * Pobierz wszystkie dostępne tłumaczenia
     */
    getAllTranslations() {
        return this.translations;
    }

    /**
     * Batch translation - tłumacz tablicę kodów
     */
    translateCodes(codes) {
        if (!Array.isArray(codes)) return [];

        return codes.map(code => ({
            original: code,
            translated: this.translateCode(code),
            isRecognized: this.isRecognizedCode(code)
        }));
    }

    /**
     * Debug - wyświetl analizę kodu
     */
    analyzeCode(code) {
        if (!code) return null;

        const cleanCode = code.toLowerCase().trim();
        const parts = cleanCode.split('-');

        const analysis = {
            original: code,
            parts: parts,
            possibleMeanings: []
        };

        parts.forEach((part, index) => {
            const meanings = {
                species: this.translations.species[part],
                technology: this.translations.technology[part],
                woodClass: this.translations.woodClass[part]
            };

            analysis.possibleMeanings.push({
                part: part,
                index: index,
                meanings: meanings
            });
        });

        analysis.finalTranslation = this.translateCode(code);

        return analysis;
    }
}

// Globalna instancja
window.ProductTranslator = new ProductTranslator();

/**
 * Rozszerzenie AnalyticsUtils o funkcje produktów
 */
if (window.AnalyticsUtils) {
    window.AnalyticsUtils.translateProductCode = function (code) {
        return window.ProductTranslator.translateCode(code);
    };

    window.AnalyticsUtils.formatProductName = function (code, showCode = false) {
        const translated = window.ProductTranslator.translateCode(code);

        if (showCode && translated !== code) {
            return `${translated} (${code})`;
        }

        return translated;
    };
}

console.log('[ProductTranslator] Moduł tłumaczenia produktów załadowany');