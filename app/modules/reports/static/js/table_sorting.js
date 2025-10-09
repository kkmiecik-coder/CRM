// table_sorting.js - Kompletna wersja z wszystkimi kolumnami

class TableSorting {
    constructor() {
        this.currentSort = {
            column: null,
            direction: null // 'asc' lub 'desc'
        };
        this.sortableColumns = [
            'date_created',
            'total_m3',
            'order_amount_net',
            'baselinker_order_id',
            'internal_order_number',
            'customer_name',
            'delivery_address',
            'delivery_city',
            'delivery_postcode',
            'delivery_state',
            'phone',
            'caretaker',
            'delivery_method',
            'order_source',
            'group_type',
            'product_type',
            'finish_state',
            'wood_species',
            'technology',
            'wood_class',
            'length_cm',
            'width_cm',
            'thickness_cm',
            'quantity',
            'price_gross',
            'price_net',
            'value_gross',
            'value_net',
            'volume_per_piece',
            'total_volume',
            'price_per_m3',
            'avg_order_price_per_m3',
            'realization_date',
            'current_status',
            'delivery_cost',
            'delivery_cost_net',
            'payment_method',
            'paid_amount_net',
            'balance_due',
            'production_volume',
            'production_value_net',
            'ready_pickup_volume',
            'ready_pickup_value_net',
            'pickup_ready'
        ];
    }

    init() {
        this.setupSortableHeaders();
        console.log('[TableSorting] Inicjalizacja sortowania tabeli');
    }

    setupSortableHeaders() {
        const table = document.querySelector('.reports-table');
        if (!table) return;

        const headers = table.querySelectorAll('th[data-column]');

        headers.forEach(header => {
            const column = header.getAttribute('data-column');

            if (this.sortableColumns.includes(column)) {
                // Dodaj klasy i ikonę
                header.classList.add('sortable-header');

                // Dodaj ikonę sortowania
                const sortIcon = document.createElement('span');
                sortIcon.className = 'sort-icon';
                header.appendChild(sortIcon);

                // Dodaj event listener
                header.addEventListener('click', () => {
                    this.handleSort(column, header);
                });
            }
        });
    }

    handleSort(column, headerElement) {
        // Określ kierunek sortowania
        let direction = 'asc';

        if (this.currentSort.column === column) {
            // Jeśli klikamy w tę samą kolumnę, zmień kierunek
            direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        }

        // Zaktualizuj stan sortowania
        this.currentSort = { column, direction };

        // Zaktualizuj wizualne wskaźniki
        this.updateSortIcons(headerElement, direction);

        // Posortuj dane
        this.sortTableData(column, direction);

        console.log(`[TableSorting] Sortowanie po kolumnie: ${column}, kierunek: ${direction}`);
    }

    updateSortIcons(activeHeader, direction) {
        // Usuń aktywne klasy ze wszystkich nagłówków
        document.querySelectorAll('.sortable-header').forEach(header => {
            header.classList.remove('active');
            const icon = header.querySelector('.sort-icon');
            if (icon) {
                icon.classList.remove('asc', 'desc');
            }
        });

        // Dodaj aktywne klasy do wybranego nagłówka
        activeHeader.classList.add('active');
        const icon = activeHeader.querySelector('.sort-icon');
        if (icon) {
            icon.classList.add(direction);
        }
    }

    sortTableData(column, direction) {
        // Pobierz aktualne dane z ReportsManager
        if (!window.reportsManager || !window.reportsManager.currentData) {
            console.warn('[TableSorting] Brak danych do sortowania');
            return;
        }

        const data = [...window.reportsManager.currentData];

        // Posortuj dane
        data.sort((a, b) => {
            let valueA = this.getSortValue(a, column);
            let valueB = this.getSortValue(b, column);

            // Obsługa wartości null/undefined
            if (valueA === null || valueA === undefined) valueA = '';
            if (valueB === null || valueB === undefined) valueB = '';

            let comparison = 0;

            // Sprawdź typ danych i sortuj odpowiednio
            if (this.isNumericColumn(column)) {
                const numA = parseFloat(valueA) || 0;
                const numB = parseFloat(valueB) || 0;
                comparison = numA - numB;
            } else if (this.isDateColumn(column)) {
                const dateA = new Date(valueA);
                const dateB = new Date(valueB);
                comparison = dateA - dateB;
            } else {
                // Sortowanie tekstowe
                comparison = String(valueA).localeCompare(String(valueB), 'pl', {
                    numeric: true,
                    sensitivity: 'base'
                });
            }

            return direction === 'desc' ? -comparison : comparison;
        });

        // Zaktualizuj tabelę z posortowanymi danymi
        this.updateTable(data);
    }

    getSortValue(item, column) {
        // Mapowanie kolumn na właściwości obiektu
        const columnMapping = {
            'date_created': item.date_created,
            'total_m3': item.total_m3,
            'order_amount_net': item.order_amount_net,
            'baselinker_order_id': item.baselinker_order_id,
            'internal_order_number': item.internal_order_number,
            'customer_name': item.customer_name,
            'delivery_address': item.delivery_address,
            'delivery_city': item.delivery_city,
            'delivery_postcode': item.delivery_postcode,
            'delivery_state': item.delivery_state,
            'phone': item.phone,
            'caretaker': item.caretaker,
            'delivery_method': item.delivery_method,
            'order_source': item.order_source,
            'group_type': item.group_type,
            'product_type': item.product_type,
            'finish_state': item.finish_state,
            'wood_species': item.wood_species,
            'technology': item.technology,
            'wood_class': item.wood_class,
            'length_cm': item.length_cm,
            'width_cm': item.width_cm,
            'thickness_cm': item.thickness_cm,
            'quantity': item.quantity,
            'price_gross': item.price_gross,
            'price_net': item.price_net,
            'value_gross': item.value_gross,
            'value_net': item.value_net,
            'volume_per_piece': item.volume_per_piece,
            'total_volume': item.total_volume,
            'price_per_m3': item.price_per_m3,
            'avg_order_price_per_m3': item.avg_order_price_per_m3,
            'realization_date': item.realization_date,
            'current_status': item.current_status,
            'delivery_cost': item.delivery_cost,
            'delivery_cost_net': item.delivery_cost_net,
            'payment_method': item.payment_method,
            'paid_amount_net': item.paid_amount_net,
            'balance_due': item.balance_due,
            'production_volume': item.production_volume,
            'production_value_net': item.production_value_net,
            'ready_pickup_volume': item.ready_pickup_volume,
            'ready_pickup_value_net': item.ready_pickup_value_net,
            'pickup_ready': item.pickup_ready
        };

        return columnMapping[column];
    }

    isNumericColumn(column) {
        const numericColumns = [
            'total_m3', 'order_amount_net', 'baselinker_order_id', 'quantity',
            'price_gross', 'price_net', 'value_gross', 'value_net',
            'volume_per_piece', 'total_volume', 'price_per_m3', 'avg_order_price_per_m3',
            'delivery_cost', 'delivery_cost_net', 'paid_amount_net', 'balance_due',
            'production_volume', 'production_value_net', 'ready_pickup_volume',
            'ready_pickup_value_net', 'length_cm', 'width_cm', 'thickness_cm',
            'pickup_ready'
        ];
        return numericColumns.includes(column);
    }

    isDateColumn(column) {
        const dateColumns = ['date_created', 'realization_date'];
        return dateColumns.includes(column);
    }

    updateTable(sortedData) {
        // Zaktualizuj dane w ReportsManager
        if (window.reportsManager) {
            window.reportsManager.currentData = sortedData;

            // Wywołaj odpowiednią metodę renderowania
            if (typeof window.reportsManager.updateTable === 'function') {
                window.reportsManager.updateTable();
            } else if (typeof window.reportsManager.renderOrderRows === 'function') {
                window.reportsManager.renderOrderRows(sortedData);
            } else {
                console.warn('[TableSorting] Nie znaleziono metody renderowania tabeli');
            }
        } else {
            console.warn('[TableSorting] ReportsManager nie jest dostępny');
        }
    }

    // Publiczna metoda do resetowania sortowania
    resetSort() {
        this.currentSort = { column: null, direction: null };

        // Usuń wszystkie aktywne klasy
        document.querySelectorAll('.sortable-header').forEach(header => {
            header.classList.remove('active');
            const icon = header.querySelector('.sort-icon');
            if (icon) {
                icon.classList.remove('asc', 'desc');
            }
        });

        console.log('[TableSorting] Sortowanie zresetowane');
    }
}

// Ekspozycja klasy do użycia globalnego
window.TableSorting = TableSorting;