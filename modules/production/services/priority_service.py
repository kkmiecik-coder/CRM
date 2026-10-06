# modules/production/services/priority_service.py
"""
Serwis priorytetów dla modułu Production - ENHANCED VERSION 2.0
================================================================

NOWY SYSTEM PRIORYTETÓW oparty na dacie opłacenia i grupowaniu tygodniowym
Zastępuje poprzedni system wagowy (deadline/value/volume/fifo).

ALGORYTM ENHANCED PRIORITY SYSTEM 2.0:
1. Pobieranie WSZYSTKICH produktów z kolejki produkcyjnej (niespakowanych)
2. Grupowanie po tygodniach (pon-niedz) względem payment_date
3. Obliczanie statystyk częstotliwości dla każdego tygodnia:
   - species (gatunek drewna)
   - finish_state (stan wykończenia) 
   - thickness_group (grupa grubości)
   - wood_class (klasa drewna)
4. Ustalanie priorytetów grup: "więcej = wyżej" w każdym tygodniu
5. Sortowanie wielopoziomowe:
   payment_date ASC → species → thickness_group → finish_state → wood_class
6. Przypisywanie numeracji sekwencyjnej 1,2,3,4... z pomijaniem manual overrides
7. Przypisywanie numeracji sekwencyjnej priority_rank

WŁASNOŚĆ SESJI (przebudowa 22.09.2026 — znalezisko KRYTYCZNE)
=============================================================
`recalculate_all_priorities` pracuje na WŁASNEJ sesji bazodanowej, którą
sama zakłada i sama zamyka, i NIGDY nie woła `commit()`, `rollback()` ani
`begin_nested()` na `db.session`.

Dwa poprzednie podejścia leczyły objaw. Punkt kontrolny (SAVEPOINT) bronił
wołającego przed COFNIĘCIEM jego pracy, ale nie przed jej ZATWIERDZENIEM —
a KROK 8 commitował WSPÓŁDZIELONĄ sesję. Kontrola adwersaryjna wykazała
wykonaniem trzy skutki:
  * ścieżka POWODZENIA zatwierdzała cudzą, świadomie niezacommitowaną pracę
    (gałęzie pętli `SyncService`: „Brak produktów do zapisania",
    `except Exception as item_error`, zostawiają zflushowany
    `ProductionOrder` bez commita i bez rollbacku);
  * między zwolnieniem punktu kontrolnego a zatwierdzeniem transakcji było
    OKNO, w którym gałąź błędu nie miała już czego wycofać — metoda meldowała
    porażkę, a jej praca i tak wjeżdżała do bazy pierwszym commitem
    wołającego;
  * prawdziwa awaria COMMIT-u (zerwane połączenie, zakleszczenie) zabierała
    wołającemu transakcję RAZEM z jego pracą (`PendingRollbackError`).

Dopóki ta funkcja commituje sesję, której NIE JEST WŁAŚCICIELEM, żadna
dyscyplina punktów zapisu tego nie uratuje. Ten sam wniosek i ten sam
wzorzec, co w `modules/reports/ingest.py` (sekcja „WŁASNOŚĆ SESJI") —
tam zadziałał i jest precedensem dla tej zmiany.

Konsekwencje praktyczne:
  * `Model.query` rozwiązuje się przez rejestr `scoped_session`, czyli ZAWSZE
    przez `db.session` — dlatego zapytania tego modułu idą przez
    `self._sesja_robocza()`, a nie przez `ProductionItem.query`;
  * pozycje przechodzą przez `_pozycje_w_mojej_sesji`, więc KROK 2 i KROK 7
    zmieniają WYŁĄCZNIE obiekty naszej sesji. Bez tego wystarczy, żeby
    wołający (albo podmiana w teście) podał pozycje wczytane gdzie indziej,
    a zmiany priorytetów wylądowałyby w cudzej sesji — czyli dokładnie tam,
    skąd je właśnie wyprowadzamy;
  * własna sesja to jedno dodatkowe połączenie do MySQL-a (limit 40
    na użytkownika) na czas jednego przeliczenia — zamykane jawnie
    w `finally`, także przy wyjątku.

Autor: Konrad Kmiecik
Wersja: 2.0 (Enhanced Priority System - Payment Date + Weekly Grouping)
Data: 2025-01-22
"""

import threading
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict
from modules.logging import get_structured_logger
from sqlalchemy import func, inspect as sa_inspect
from sqlalchemy.orm import joinedload, object_session

logger = get_structured_logger('production.priority.v2')

class PriorityError(Exception):
    """Wyjątek dla błędów kalkulacji priorytetów"""
    pass


def nowa_sesja_priorytetow():
    """Świeża, WŁASNA sesja przeliczania priorytetów. Wołający ją zamyka.

    Fabryka Flask-SQLAlchemy (`db.create_session`) zamiast gołego
    `sessionmaker(bind=db.engine)`: daje tę samą klasę sesji i to samo
    rozwiązywanie bindów, co `db.session`, tylko poza rejestrem
    `scoped_session`. Dzięki temu commit i rollback tej sesji dotyczą
    WYŁĄCZNIE pracy priorytetów — patrz „WŁASNOŚĆ SESJI" w docstringu modułu.
    """
    from extensions import db

    return db.create_session({})()

class NewPriorityCalculator:
    """
    Nowy kalkulator priorytetów oparty na dacie opłacenia i grupowaniu tygodniowym
    
    ENHANCED VERSION 2.0 - kompletnie przepisany algorytm:
    - Zastąpienie systemu wagowego logiką opartą na payment_date
    - Grupowanie tygodniowe z priorytetem dla częściej występujących kombinacji
    - Numeracja sekwencyjna 1,2,3,4... zamiast punktowej 100,110,120...
    - Respect manual overrides (priority_manual_override = TRUE)
    - Scope: wszystkie produkty w kolejce bez ograniczenia czasowego
    """
    
    def __init__(self):
        """
        Inicjalizacja nowego kalkulatora priorytetów
        """
        self._lock = threading.RLock()

        # Sesja bieżącego przeliczania. Żyje W WĄTKU (`threading.local`),
        # nie na instancji — bo instancja jest SINGLETONEM procesu
        # (`get_priority_calculator`), a gunicorn obsługuje żądania wątkami.
        #
        # ZNALEZISKO WAŻNE (trzecia kontrola adwersaryjna). Stało tu wcześniej
        # zdanie, że sesja jest „ustawiana i zerowana WYŁĄCZNIE pod `self._lock`,
        # więc dwa przeliczenia nie mogą sobie jej podmienić". Było nieprawdziwe
        # na dwa niezależne sposoby:
        #
        #   * ODCZYTY nie brały blokady w ogóle.
        #     `get_active_products_for_prioritization` i `get_reserved_ranks`
        #     są publiczne i — zgodnie z własnym opisem — wolno je wołać
        #     samodzielnie. Wątek B, wołając je na tym samym singletonie
        #     w trakcie przeliczania w wątku A, dostawał PRYWATNĄ sesję wątku A
        #     i puszczał po niej zapytanie. `Session` SQLAlchemy nie jest
        #     bezpieczna wątkowo, a A zamyka ją w `finally` — B trafiał
        #     w najlepszym razie na `ResourceClosedError`;
        #   * `self._lock` to RLock, czyli blokada WZNAWIALNA. Ten sam wątek
        #     wchodzi w nią drugi raz bez oporu, więc zagnieżdżone przeliczanie
        #     podmieniało sesję zewnętrznemu i zamykało ją w swoim `finally`.
        #
        # Teraz niezmiennik trzyma KOD, nie obietnica: sesja jest widoczna
        # wyłącznie we własnym wątku, a wejście w przeliczanie po raz drugi
        # w TYM SAMYM wątku jest odrzucane (`PriorityError`, patrz
        # `recalculate_all_priorities`). Poza przeliczaniem atrybutu nie ma
        # i metody pomocnicze wracają do `db.session` (są wyłącznie czytające,
        # patrz `_sesja_robocza`).
        #
        # Blokada zostaje, ale w swojej właściwej roli: szereguje przeliczenia
        # między wątkami, żeby dwa naraz nie renumerowały tej samej kolejki.
        self._watek = threading.local()

        # Konfiguracja algorytmu
        self.active_statuses = [
            'czeka_na_wyciecie',
            'czeka_na_skladanie',
            'czeka_na_sklejanie',
            'czeka_na_formatowanie',
            # Wykańczanie rozpadło się na dwa stanowiska. Bez OBU kluczy
            # pozycje z tych kolejek wypadają z przeliczania priorytetów
            # po cichu — algorytm ich po prostu nie widzi.
            'czeka_na_krawedzie',
            'czeka_na_lakiernie',
            'czeka_na_pakowanie',
            'w_realizacji'
        ]
        
        logger.info("Inicjalizacja NewPriorityCalculator v2.0", extra={
            'algorithm': 'payment_date_weekly_grouping',
            'active_statuses': self.active_statuses,
            'scope': 'all_active_products_unlimited'
        })
    
    def recalculate_all_priorities(self) -> Dict[str, Any]:
        """
        Główna metoda przeliczająca wszystkie priorytety

        ALGORYTM:
        1. Pobiera WSZYSTKIE aktywne produkty z kolejki (niespakowane)
        2. Grupuje po tygodniach względem payment_date
        3. Oblicza statystyki częstotliwości w każdym tygodniu
        4. Ustala priorytety grup: "więcej = wyżej"
        5. Sortuje produkty wielopoziomowo
        6. Przypisuje numery 1,2,3,4... z pomijaniem manual overrides
        7. Aktualizuje bazę danych

        CAŁOŚĆ IDZIE PO WŁASNEJ SESJI, którą ta metoda zakłada i zamyka
        w `finally` — patrz „WŁASNOŚĆ SESJI" w docstringu modułu.
        `db.session` nie jest tu tykana ani razu, więc przeliczanie
        priorytetów nie może ani zatwierdzić, ani cofnąć pracy wołającego.

        Returns:
            Dict[str, Any]: Szczegółowy raport z przeliczenia
        """
        start_time = datetime.now()

        try:
            with self._lock:
                logger.info("Rozpoczęcie przeliczania wszystkich priorytetów v2.0")

                # Wejście zagnieżdżone. `self._lock` jest WZNAWIALNA, więc
                # nie zatrzyma wątku, który już ją trzyma — a każde drugie
                # wejście podmieniłoby sesję przeliczaniu zewnętrznemu
                # i zamknęło ją w swoim `finally`. Nie ma przypadku,
                # w którym to jest pożądane: renumerujemy CAŁĄ kolejkę,
                # więc przeliczanie w przeliczaniu i tak liczyłoby to samo.
                if self._sesja_watku() is not None:
                    raise PriorityError(
                        'Przeliczanie priorytetów już trwa w tym wątku — '
                        'zagnieżdżone wywołanie odrzucone')

                sesja = nowa_sesja_priorytetow()
                try:
                    # Od tej chwili `_sesja_robocza()` oddaje NASZĄ sesję, więc
                    # zapytania KROKU 1 i KROKU 7 nie odpalają autoflushu
                    # sesji wołającego (nieudany flush na poziomie KORZENIA
                    # jego transakcji zabrałby mu całą pracę).
                    self._watek.sesja = sesja

                    # KROK 1: Pobieranie wszystkich aktywnych produktów
                    products = self._pozycje_w_mojej_sesji(
                        self.get_active_products_for_prioritization(), sesja)
                    logger.info(f"Pobrano {len(products)} aktywnych produktów z kolejki")

                    if not products:
                        # Niczego nie zmieniliśmy — nie ma czego zatwierdzać.
                        return {
                            'success': True,
                            'products_processed': 0,
                            'message': 'Brak produktów w kolejce do priorytetyzacji',
                            'duration_seconds': 0
                        }

                    # KROK 2: Aktualizacja thickness_group dla wszystkich produktów
                    thickness_updated = self.update_thickness_groups_batch(products)
                    logger.debug(f"Zaktualizowano thickness_group dla {thickness_updated} produktów")

                    # KROK 3: Grupowanie po tygodniach
                    weekly_groups = self.group_products_by_weeks(products)
                    logger.info(f"Pogrupowano produkty w {len(weekly_groups)} tygodni")

                    # KROK 4-6: Przetwarzanie każdego tygodnia i sortowanie globalne
                    all_sorted_products = []
                    week_stats = {}

                    for week_key, week_products in weekly_groups.items():
                        # Statystyki częstotliwości dla tygodnia
                        stats = self.calculate_week_statistics(week_products)
                        week_stats[week_key] = stats

                        # Priorytety grup dla tygodnia
                        group_priorities = self.determine_group_priorities(stats)

                        # Sortowanie produktów w tygodniu
                        sorted_week_products = self.sort_products_by_rules(week_products, group_priorities)
                        all_sorted_products.extend(sorted_week_products)

                    logger.info(f"Posortowano wszystkie produkty globalnie: {len(all_sorted_products)}")

                    # KROK 7: Przypisanie numeracji sekwencyjnej
                    ranking_result = self.assign_sequential_ranks(all_sorted_products)

                    # KROK 8: Zatwierdzenie WŁASNEJ transakcji.
                    #
                    # Jedno `commit()` na własnej sesji, bez punktów zapisu
                    # i bez okien: cokolwiek tu padnie — flush odrzucony
                    # przez bazę, zerwane połączenie, zakleszczenie — leci
                    # do gałęzi błędu, która wycofuje NASZĄ sesję. Transakcja
                    # wołającego jest poza tym wszystkim i zostaje nietknięta.
                    sesja.commit()

                    duration = (datetime.now() - start_time).total_seconds()

                    result = {
                        'success': True,
                        'products_processed': len(products),
                        'products_prioritized': ranking_result['products_updated'],
                        'manual_overrides_preserved': ranking_result['manual_overrides_preserved'],
                        'weekly_groups_processed': len(weekly_groups),
                        'duration_seconds': round(duration, 2),
                        'algorithm_version': '2.0',
                        'week_statistics': week_stats,
                        'ranking_details': ranking_result
                    }

                    logger.info("Zakończono przeliczanie priorytetów", extra=result)
                    return result

                except Exception:
                    self._wycofaj_wlasna_prace(sesja)
                    raise
                finally:
                    # Kolejność jest istotna: najpierw odcinamy sesję od metod
                    # pomocniczych, dopiero potem ją zamykamy. Odwrotnie
                    # `_sesja_robocza()` mogłaby wydać zamkniętą sesję.
                    self._watek.sesja = None
                    self._zamknij_sesje(sesja)

        except Exception as e:
            logger.error("Błąd przeliczania priorytetów", extra={
                'error': str(e),
                'duration_seconds': (datetime.now() - start_time).total_seconds()
            })

            return {
                'success': False,
                'error': str(e),
                'products_processed': 0,
                'duration_seconds': (datetime.now() - start_time).total_seconds()
            }

    def _sesja_watku(self):
        """Sesja przeliczania trwającego W TYM WĄTKU albo `None`.

        Atrybut `sesja` istnieje na `threading.local()` tylko w tych wątkach,
        które kiedykolwiek weszły w przeliczanie — stąd `getattr`
        z domyślną wartością, a nie gołe sięgnięcie po atrybut.
        """
        return getattr(self._watek, 'sesja', None)

    def _sesja_robocza(self):
        """Sesja, po której mają iść zapytania tego kalkulatora.

        W trakcie przeliczania jest to WŁASNA sesja TEGO WĄTKU. Poza nim
        `None`, więc metody czytające (`get_active_products_for_prioritization`,
        `get_reserved_ranks`) da się nadal wywołać samodzielnie — wracają
        wtedy do `db.session`. Są WYŁĄCZNIE czytające, więc taki fallback
        niczego cudzego nie zatwierdza ani nie cofa.

        Sesja jest czytana z `threading.local()`, więc wątek, który woła te
        metody samodzielnie, NIGDY nie dostanie prywatnej sesji przeliczania
        trwającego obok — patrz komentarz przy `self._watek` w `__init__`.
        """
        sesja = self._sesja_watku()
        if sesja is not None:
            return sesja

        from extensions import db
        return db.session

    @staticmethod
    def _pozycje_w_mojej_sesji(pozycje: List, sesja) -> List:
        """Zamienia pozycje na ich odpowiedniki z WŁASNEJ sesji.

        KROK 2 (`update_thickness_groups_batch`) i KROK 7
        (`assign_sequential_ranks`) zmieniają obiekty ORM-a. Gdyby trafiły
        na obiekt wczytany przez `db.session`, zmiana priorytetów wylądowałaby
        w sesji WOŁAJĄCEGO — czyli dokładnie tam, skąd tę pracę wyprowadzamy:
        czekałaby na jego commit albo padłaby ofiarą jego rollbacku.

        Tożsamość czytamy przez `sa_inspect(...).identity`, a nie przez
        `pozycja.id`: dla obiektu wygaszonego po cudzym commicie samo sięgnięcie
        po atrybut wywołałoby doczytanie, a z nim AUTOFLUSH cudzej sesji.

        Pozycje bez tożsamości w bazie (jeszcze niezapisane) pomijamy —
        nie ma czego przenieść, a przypisywanie im rangi i tak nie miałoby
        gdzie wylądować.
        """
        from ..models import ProductionItem

        moje = []
        przeniesione = 0
        pominiete = 0

        for pozycja in pozycje:
            if object_session(pozycja) is sesja:
                moje.append(pozycja)
                continue

            klucz = sa_inspect(pozycja).identity
            if klucz is None:
                pominiete += 1
                continue

            wlasna = sesja.query(ProductionItem).get(klucz)
            if wlasna is None:
                pominiete += 1
                continue

            moje.append(wlasna)
            przeniesione += 1

        if przeniesione or pominiete:
            logger.debug("Pozycje przeniesione do własnej sesji priorytetów", extra={
                'przeniesione': przeniesione,
                'pominiete': pominiete,
                'razem': len(moje),
            })

        return moje

    @staticmethod
    def _wycofaj_wlasna_prace(sesja) -> None:
        """Cofa WYŁĄCZNIE pracę przeliczania priorytetów.

        Rollback idzie po WŁASNEJ sesji, więc jego zasięg kończy się
        na naszych zmianach z definicji — nie trzeba już żadnych punktów
        zapisu ani sprawdzania, czy jest do czego wracać. Praca wołającego
        wisi w `db.session` i jest poza tą transakcją.
        """
        try:
            sesja.rollback()
        except Exception as blad_rollbacku:
            logger.error("Nie udalo sie wycofac nieudanego przeliczania priorytetow",
                         extra={'error': str(blad_rollbacku)})

    @staticmethod
    def _zamknij_sesje(sesja) -> None:
        """Zamyka własną sesję. Niepowodzenie nie może przesłonić wyniku.

        Bez tego jedno połączenie zostawałoby wiszące przy każdej awarii,
        a hosting ma limit 40 połączeń na użytkownika (awaria 1040/1203
        w historii projektu) — stąd ślad w logu, mimo że wynik przeliczania
        to nie zmienia.
        """
        try:
            sesja.close()
        except Exception as blad_zamkniecia:
            logger.error("Nie udalo sie zamknac sesji priorytetow",
                         extra={'error': str(blad_zamkniecia)})

    def get_active_products_for_prioritization(self) -> List:
        """
        Pobiera WSZYSTKIE produkty aktywne w kolejce produkcyjnej
        
        KRYTERIA WŁĄCZENIA:
        - Status w kolejce produkcyjnej (przed pakowaniem)
        - BEZ ograniczenia czasowego - wszystkie aktywne niezależnie od daty
        - Wykluczone: produkty już spakowane przez ostatnie stanowisko
        
        PUSTA LISTA ZNACZY „PUSTA KOLEJKA” I NIC INNEGO (znalezisko WAŻNE,
        trzecia kontrola adwersaryjna). Metoda łapała tu KAŻDY wyjątek
        i zwracała `[]`, więc `recalculate_all_priorities` widziało pustą
        kolejkę i kończyło `success: True` z komunikatem „Brak produktów
        w kolejce do priorytetyzacji". Operator dostawał zielony wynik, choć
        baza nie odpowiedziała, a numeracja na hali została nieprzeliczona.
        „Nie ma czego przeliczać" i „nie udało się odpytać" to dwa różne
        zdania i muszą dać dwa różne wyniki — dlatego awaria leci dalej
        jako `PriorityError`.

        Returns:
            List[ProductionItem]: Lista aktywnych produktów (może być pusta)

        Raises:
            PriorityError: gdy zapytania NIE DA SIĘ wykonać
        """
        try:
            from ..models import ProductionItem, ProductionOrder

            # `ProductionItem.query` szłoby przez rejestr `scoped_session`,
            # czyli przez `db.session` — a tam autoflush zabrałby się
            # za NIEZACOMMITOWANĄ pracę wołającego. Patrz „WŁASNOŚĆ SESJI".
            sesja = self._sesja_robocza()

            # Query wszystkich produktów w statusach aktywnych
            query = sesja.query(ProductionItem).join(ProductionOrder).options(
                joinedload(ProductionItem.order),
                joinedload(ProductionItem.configuration),
            ).filter(
                ProductionItem.current_status.in_(self.active_statuses)
            ).order_by(
                func.isnull(ProductionOrder.payment_date),
                ProductionOrder.payment_date.asc(),
                ProductionItem.created_at.asc()
            )

            products = query.all()
            
            logger.debug("Pobrano produkty dla priorytetyzacji", extra={
                'total_count': len(products),
                'active_statuses': self.active_statuses,
                'scope': 'unlimited_time_range'
            })
            
            return products
            
        except Exception as e:
            logger.error("Błąd pobierania produktów dla priorytetyzacji", extra={
                'error': str(e)
            })
            raise PriorityError(
                'Nie udało się pobrać produktów do priorytetyzacji: %s' % e) from e
    
    def group_products_by_weeks(self, products: List) -> Dict[str, List]:
        """
        Grupuje produkty według tygodni (poniedziałek 00:00 - niedziela 23:59)
        na podstawie payment_date
        
        Args:
            products: Lista produktów do pogrupowania
            
        Returns:
            Dict[str, List]: Słownik "2025-W03" -> [produkty]
        """
        weekly_groups = defaultdict(list)
        
        for product in products:
            if product.order and product.order.payment_date:
                # Oblicz granice tygodnia dla payment_date
                week_start, week_end = self.get_week_boundaries(product.order.payment_date)

                # Format klucza: YYYY-WNN
                year = week_start.year
                week_number = week_start.isocalendar()[1]
                week_key = f"{year}-W{week_number:02d}"

            else:
                # Produkty bez payment_date w osobnej grupie
                week_key = "no-payment-date"

            weekly_groups[week_key].append(product)
        
        # Sortowanie kluczy tygodni chronologicznie
        sorted_groups = {}
        for week_key in sorted(weekly_groups.keys()):
            sorted_groups[week_key] = weekly_groups[week_key]
        
        logger.debug("Pogrupowano produkty po tygodniach", extra={
            'weekly_groups': {k: len(v) for k, v in sorted_groups.items()}
        })
        
        return sorted_groups
    
    def get_week_boundaries(self, date_input: datetime) -> Tuple[datetime, datetime]:
        """
        Oblicza początek i koniec tygodnia (poniedziałek 00:00 - niedziela 23:59)
        
        Args:
            date_input: Data wejściowa
            
        Returns:
            Tuple[datetime, datetime]: (week_start, week_end)
        """
        if isinstance(date_input, str):
            date_input = datetime.fromisoformat(date_input)
        elif isinstance(date_input, date):
            date_input = datetime.combine(date_input, datetime.min.time())
        
        # Znajdź poniedziałek tego tygodnia (weekday: 0=Mon, 6=Sun)
        days_since_monday = date_input.weekday()
        week_start = date_input - timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Niedziela 23:59:59
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        return week_start, week_end
    
    def calculate_week_statistics(self, products: List) -> Dict[str, Dict[str, int]]:
        """
        Oblicza statystyki częstotliwości występowania dla produktów w danym tygodniu
        
        Args:
            products: Lista produktów z danego tygodnia
            
        Returns:
            Dict[str, Dict[str, int]]: Statystyki {kategoria: {wartość: count}}
        """
        stats = {
            'species': defaultdict(int),
            'technology': defaultdict(int),
            'finish_state': defaultdict(int),
            'thickness_group': defaultdict(int),
            'wood_class': defaultdict(int)
        }
        
        for product in products:
            # Zliczanie gatunków
            if product.configuration and product.configuration.species:
                stats['species'][product.configuration.species] += 1

            # Zliczanie technologii
            if product.configuration and product.configuration.technology:
                stats['technology'][product.configuration.technology] += 1

            # Zliczanie stanów wykończenia
            if product.parsed_finish_state:
                stats['finish_state'][product.parsed_finish_state] += 1

            # Zliczanie grup grubości
            if product.thickness_group:
                stats['thickness_group'][product.thickness_group] += 1

            # Zliczanie klas drewna
            if product.configuration and product.configuration.wood_class:
                stats['wood_class'][product.configuration.wood_class] += 1
        
        # Konwersja defaultdict na dict dla loggingu
        final_stats = {
            category: dict(counts) 
            for category, counts in stats.items()
        }
        
        return final_stats
    
    def determine_group_priorities(self, stats: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
        """
        Ustala priorytety grup na zasadzie "więcej = wyżej"
        
        Args:
            stats: Statystyki częstotliwości z calculate_week_statistics
            
        Returns:
            Dict[str, Dict[str, int]]: {kategoria: {wartość: priorytet}}
                gdzie priorytet: 1=najwyższy, 2=drugi, etc.
        """
        group_priorities = {}
        
        for category, value_counts in stats.items():
            if not value_counts:
                group_priorities[category] = {}
                continue
            
            # Sortowanie według częstotliwości malejąco (więcej = wyżej)
            sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
            
            # Przypisanie priorytetów: 1=najczęściej występujący, 2=drugi, etc.
            priorities = {}
            for rank, (value, count) in enumerate(sorted_values, 1):
                priorities[value] = rank
            
            group_priorities[category] = priorities
        
        logger.debug("Ustalono priorytety grup", extra={
            'group_priorities': group_priorities
        })
        
        return group_priorities
    
    def sort_products_by_rules(self, products: List, group_priorities: Dict[str, Dict[str, int]]) -> List:
        """
        Sortuje produkty według nowych reguł priorytetów
        
        SORTOWANIE WIELOPOZIOMOWE:
        1. payment_date ASC (starsze = wyższy priorytet)
        2. species (według group_priorities)
        3. thickness_group (według group_priorities) 
        4. finish_state (według group_priorities)
        5. wood_class (według group_priorities)
        
        Args:
            products: Lista produktów do posortowania
            group_priorities: Priorytety grup z determine_group_priorities
            
        Returns:
            List: Posortowana lista produktów
        """
        logger.debug("Group priorities calculated", extra={
            'group_priorities': group_priorities,
            'products_count': len(products)
        })
        
        def get_sort_key(product):
            """
            POPRAWIONA LOGIKA - deadline_date jako primary key
            
            Kolejność sortowania priorytetów:
            1. DEADLINE_DATE (tylko dzień, bez godzin) - najważniejszy
            2. SPECIES (gatunek drewna) - według częstotliwości w tygodniu
            3. TECHNOLOGY (technologia wykonania) - według częstotliwości
            4. THICKNESS_GROUP (grupa grubości) - według częstotliwości
            5. WOOD_CLASS (klasa drewna) - według częstotliwości
            6. PAYMENT_DATE (data opłacenia) - tie-breaker, starsze = wyższy priorytet
            7. ID produktu - final tie-breaker dla stabilności sortowania
            """

            logger.debug(f"Product {product.id} sort data", extra={
                'product_id': product.id,
                'deadline_date': product.deadline_date,
                'parsed_wood_species': getattr(product.configuration, 'species', 'NONE') if product.configuration else 'NONE',
                'parsed_technology': (product.configuration.technology if product.configuration else None) or 'NONE',
                'thickness_group': getattr(product, 'thickness_group', 'NONE'),
                'parsed_wood_class': getattr(product.configuration, 'wood_class', 'NONE') if product.configuration else 'NONE',
                'payment_date': product.order.payment_date if product.order else None
            })
            
            # 1. DEADLINE_DATE - najważniejszy (termin dostawy) - tylko DZIEŃ!
            deadline_key = product.deadline_date if product.deadline_date else date.max
            
            # 2. W ramach tego samego deadline - parametry wykonawcze:
            # SPECIES (gatunek drewna) - według group_priorities
            species_priority = group_priorities.get('species', {}).get(
                product.configuration.species if product.configuration else None, 999
            )

            # TECHNOLOGY (technologia) - według group_priorities
            tech_priority = group_priorities.get('technology', {}).get(
                product.configuration.technology if product.configuration else None, 999
            )

            # THICKNESS_GROUP (grubość) - według group_priorities
            thickness_priority = group_priorities.get('thickness_group', {}).get(
                product.thickness_group, 999
            )

            # WOOD_CLASS (klasa drewna) - według group_priorities
            wood_class_priority = group_priorities.get('wood_class', {}).get(
                product.configuration.wood_class if product.configuration else None, 999
            )

            # 3. Payment_date jako tie-breaker (starsze opłacenie = wyższy priorytet)
            payment_date_key = (product.order.payment_date if product.order else None) or datetime.max
            
            # 4. ID jako final tie-breaker
            id_key = product.id
            
            return (
                deadline_key,          # 1. Deadline (najważniejszy)
                species_priority,      # 2. Gatunek 
                tech_priority,         # 3. Technologia
                thickness_priority,    # 4. Grubość
                wood_class_priority,   # 5. Klasa
                payment_date_key,      # 6. Data opłacenia (tie-breaker)
                id_key                 # 7. ID (stabilność)
            )
        
        try:
            sorted_products = sorted(products, key=get_sort_key)
            
            logger.debug("Posortowano produkty według nowych reguł", extra={
                'products_count': len(products),
                'sorted_count': len(sorted_products)
            })
            
            return sorted_products
            
        except Exception as e:
            logger.error("Błąd sortowania produktów", extra={
                'error': str(e),
                'products_count': len(products)
            })
            # Fallback - return unsorted
            return products
    
    def assign_sequential_ranks(self, sorted_products: List) -> Dict[str, Any]:
        """
        Przypisuje numery priorytetów 1,2,3,4... z pomijaniem manual overrides
    
        Args:
            sorted_products: Lista produktów posortowanych według reguł
        
        Returns:
            Dict[str, Any]: Statystyki przypisania rang
        """
        # Pobierz zarezerwowane rangi (manual overrides)
        reserved_ranks = self.get_reserved_ranks()
    
        current_rank = 1
        products_updated = 0
        manual_overrides_preserved = len(reserved_ranks)
    
        for product in sorted_products:
            # Pomijaj produkty z manual override
            if product.is_priority_locked:
                logger.debug(f"Pominięto produkt z manual override: {product.short_product_id} (rank: {product.priority_rank})")
                continue
        
            # Znajdź następny dostępny rank (pomijając zarezerwowane)
            while current_rank in reserved_ranks:
                current_rank += 1
        
            # ZMIANA: Przypisz tylko priority_rank (usuń priority_score)
            old_rank = product.priority_rank
            product.priority_rank = current_rank
        
            logger.debug(f"Zaktualizowano priorytet: {product.short_product_id} {old_rank} → {current_rank}")
        
            current_rank += 1
            products_updated += 1
    
        result = {
            'products_updated': products_updated,
            'manual_overrides_preserved': manual_overrides_preserved,
            'highest_rank_assigned': current_rank - 1,
            'reserved_ranks_count': len(reserved_ranks),
            'reserved_ranks': sorted(list(reserved_ranks)) if reserved_ranks else []
        }
    
        logger.info("Przypisano numery priorytetów", extra=result)
        return result
    
    def get_reserved_ranks(self) -> Set[int]:
        """
        Pobiera numery priorytetów zarezerwowane przez manual overrides
        
        Returns:
            Set[int]: Zestaw zajętych numerów priorytetu (może być pusty)

        PUSTY ZBIÓR ZNACZY „NIC NIE JEST ZAREZERWOWANE” I NIC INNEGO — ta sama
        poprawka i to samo uzasadnienie, co w
        `get_active_products_for_prioritization`, tylko skutek groźniejszy:
        pusty zbiór po awarii kazałby `assign_sequential_ranks` rozdać numery
        zajęte przez ręczne nadpisania operatora (`priority_manual_override`),
        czyli zdublować pozycje w kolejce na hali — po cichu i z wynikiem
        `success: True`.

        Raises:
            PriorityError: gdy zapytania NIE DA SIĘ wykonać
        """
        try:
            from ..models import ProductionItem

            # Własna sesja, nie `db.session` — patrz „WŁASNOŚĆ SESJI".
            sesja = self._sesja_robocza()

            # Query produktów z manual override i przypisanym priority_rank
            reserved_products = sesja.query(ProductionItem).filter(
                ProductionItem.priority_manual_override == True,
                ProductionItem.priority_rank.isnot(None),
                ProductionItem.current_status.in_(self.active_statuses)
            ).all()
            
            reserved_ranks = {p.priority_rank for p in reserved_products if p.priority_rank}
            
            logger.debug(f"Znaleziono {len(reserved_ranks)} zarezerwowanych rangów: {sorted(reserved_ranks)}")
            return reserved_ranks
            
        except Exception as e:
            logger.error("Błąd pobierania zarezerwowanych rangów", extra={'error': str(e)})
            raise PriorityError(
                'Nie udało się pobrać zarezerwowanych numerów priorytetu: %s' % e) from e
    
    def update_thickness_groups_batch(self, products: List) -> int:
        """
        Masowa aktualizacja thickness_group dla produktów
        
        Args:
            products: Lista produktów do zaktualizowania
            
        Returns:
            int: Liczba zaktualizowanych produktów
        """
        updated_count = 0
        
        for product in products:
            old_group = product.thickness_group
            new_group = product.update_thickness_group()
            
            if old_group != new_group:
                updated_count += 1
        
        logger.debug(f"Masowa aktualizacja thickness_group: {updated_count} produktów")
        return updated_count
    
    def validate_product_for_prioritization(self, product) -> Tuple[bool, List[str]]:
        """
        Sprawdza czy produkt może uczestniczyć w priorytetyzacji

        Args:
            product: Instancja ProductionItem

        Returns:
            Tuple[bool, List[str]]: (is_valid, missing_fields)
        """
        return product.validate_for_prioritization()

# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_priority_calculator_instance = None
_calculator_lock = threading.Lock()

def get_priority_calculator() -> NewPriorityCalculator:
    """
    Pobiera singleton instance NewPriorityCalculator
    
    Returns:
        NewPriorityCalculator: Instancja nowego kalkulatora
    """
    global _priority_calculator_instance
    
    if _priority_calculator_instance is None:
        with _calculator_lock:
            if _priority_calculator_instance is None:
                _priority_calculator_instance = NewPriorityCalculator()
                logger.info("Utworzono singleton NewPriorityCalculator v2.0")
    
    return _priority_calculator_instance

# ============================================================================
# HELPER FUNCTIONS - ZACHOWANE DLA KOMPATYBILNOŚCI
# ============================================================================

def recalculate_priorities() -> Dict[str, Any]:
    """
    Przelicza priorytety wszystkich aktywnych produktów

    Returns:
        dict: Rezultat przeliczenia
    """
    calculator = get_priority_calculator()
    if not calculator:
        return {'success': False, 'error': 'Calculator unavailable'}
    return calculator.recalculate_all_priorities()

# ============================================================================
# HELPER FUNCTIONS DLA ENHANCED PRIORITY SYSTEM 2.0
# ============================================================================

def recalculate_all_priorities() -> Dict[str, Any]:
    """
    Helper function dla pełnego przeliczenia wszystkich priorytetów
    
    Returns:
        Dict[str, Any]: Raport z przeliczenia
    """
    return get_priority_calculator().recalculate_all_priorities()

def get_priority_statistics() -> Dict[str, Any]:
    """
    Pobiera statystyki systemu priorytetów
    
    Returns:
        Dict[str, Any]: Statystyki priorytetów
    """
    try:
        from ..models import ProductionItem
        
        # Policz produkty w kolejce
        # DRUGA kopia listy z NewPriorityCalculator.active_statuses — kto
        # zmienia jedną, musi zmienić obie, inaczej kafelek statystyk mówi
        # co innego niż algorytm, który właśnie przeliczył kolejkę.
        active_count = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie',
                'czeka_na_sklejanie',
                'czeka_na_formatowanie', 'czeka_na_krawedzie',
                'czeka_na_lakiernie',
                'czeka_na_pakowanie', 'w_realizacji'
            ])
        ).count()

        # Policz manual overrides
        # TRZECIA kopia tej samej listy.
        manual_overrides = ProductionItem.query.filter(
            ProductionItem.priority_manual_override == True,
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie',
                'czeka_na_sklejanie',
                'czeka_na_formatowanie', 'czeka_na_krawedzie',
                'czeka_na_lakiernie',
                'czeka_na_pakowanie', 'w_realizacji'
            ])
        ).count()
        
        # Ostatnia aktualizacja (najnowszy updated_at)
        latest_update = ProductionItem.query.filter(
            ProductionItem.priority_rank.isnot(None)
        ).order_by(ProductionItem.updated_at.desc()).first()
        
        return {
            'active_products_count': active_count,
            'manual_overrides_count': manual_overrides,
            'last_calculation': latest_update.updated_at if latest_update else None,
            'algorithm_version': '2.0',
            'algorithm_type': 'payment_date_weekly_grouping'
        }
        
    except Exception as e:
        logger.error("Błąd pobierania statystyk priorytetów", extra={'error': str(e)})
        return {
            'error': str(e),
            'active_products_count': 0,
            'manual_overrides_count': 0,
            'last_calculation': None
        }