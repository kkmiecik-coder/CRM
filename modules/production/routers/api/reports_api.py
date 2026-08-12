# modules/production/routers/api/reports_api.py
"""
Reports tab content endpoints.
Extracted from api_routers.py.
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func

from . import api_bp, logger, ProductionItem, ProductionSyncLog, get_local_now
from modules.production.models import ProductionConfiguration, ProductionOrder

from ...services.station_catalog import (
    STATION_LABELS, STATION_ORDER, STATION_PENDING_STATUS,
    station_choices, station_label,
)

# Jedno źródło nazw i kolejności — patrz services/station_catalog.py. Wcześniej
# ten moduł miał własną kopię etykiet ('Wycinanie'), a tabela pod widgetem brała
# je skądinąd ('Wycinanie - mikro') — w jednym widoku dwie nazwy tego samego.
VALID_STATIONS = set(STATION_ORDER)


def _parsuj_zakres_dat(domyslne_dni=7):
    """
    Wspólne parsowanie start_date/end_date dla raportów. Zwraca
    (start_date, end_date, error_response) — jak w reports_station_output,
    tylko wyciągnięte, żeby nie kopiować walidacji do raportu pracowników.

    Domyślny zakres liczymy z get_local_now(), NIE z date.today(): kontener
    chodzi na UTC, więc między północą a 02:00 czasu polskiego date.today()
    oddaje wczoraj i nocna zmiana wchodząca na Raporty bez ustawienia zakresu
    widziała poprzedni dzień.

    NIEPEŁNA PARA DAT TO BŁĄD, nie zaproszenie do zakresu domyślnego. Warunek
    `if start and end` po cichu wyrzucał do kosza całe podane wejście:
    ?start_date=2026-05-01 oddawało HTTP 200 z danymi ostatnich siedmiu dni,
    a eksport XLSX wychodził z domyślnym zakresem w nazwie pliku. Zapisany
    link albo ręcznie sklejony URL odpowiadał wtedy na inne pytanie, niż
    zadano, i nic tego nie sygnalizowało.
    """
    start_str = request.args.get('start_date', '').strip()
    end_str = request.args.get('end_date', '').strip()

    if bool(start_str) != bool(end_str):
        return None, None, (jsonify({
            'success': False,
            'error': 'Podaj obie daty zakresu (start_date i end_date) albo żadnej'
        }), 400)

    try:
        if start_str and end_str:
            start = datetime.strptime(start_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_str, '%Y-%m-%d').date()
        else:
            # Domyślnie ostatnie `domyslne_dni` dni — sensowny zakres na wejściu
            end = get_local_now().date()
            start = end - timedelta(days=domyslne_dni - 1)
    except ValueError:
        return None, None, (jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400)

    return start, end, None


# Ile wierszy listy pozycji oddajemy domyślnie. Front pokazuje dziesięć naraz
# (SO_PAGE_SIZE w stations.html) — wcześniej dostawał WSZYSTKIE i stronicował
# w przeglądarce, co przy jednym kliknięciu w preset „30 dni" znaczyło 1.3 MB
# JSON-a, a przy 90 dniach 3.4 MB.
DOMYSLNY_LIMIT_POZYCJI = 10
MAKS_LIMIT_POZYCJI = 200


def _parsuj_stronicowanie(domyslny_limit=DOMYSLNY_LIMIT_POZYCJI):
    """(limit, offset, error_response) — wspólna walidacja limit/offset."""
    def _liczba(nazwa, domyslna, minimum, maksimum):
        surowa = request.args.get(nazwa, '').strip()
        if not surowa:
            return domyslna, None
        if not surowa.isdigit():
            return None, (jsonify({
                'success': False,
                'error': f'{nazwa} musi być liczbą całkowitą nieujemną'
            }), 400)
        return max(minimum, min(int(surowa), maksimum)), None

    limit, err = _liczba('limit', domyslny_limit, 1, MAKS_LIMIT_POZYCJI)
    if err:
        return None, None, err
    offset, err = _liczba('offset', 0, 0, 10 ** 7)
    if err:
        return None, None, err
    return limit, offset, None


def _blad_serwera(nazwa, wyjatek, **kontekst):
    """
    Awaria endpointu: szczegóły do logu, do klienta stały komunikat.

    Treść wyjątku NIE MOŻE jechać do przeglądarki. Przy błędzie SQLAlchemy
    str(e) niesie pełne zapytanie razem z parametrami — czyli nazwy klientów
    i produktów z BaseLinkera — a wszystkie te endpointy mają wyłącznie
    @login_required, bez sprawdzania roli. Do tego front w kilku miejscach
    wstawia `data.error` do innerHTML, więc treść wyjątku jest jednocześnie
    ścieżką wykonania kodu.
    """
    logger.error(f"Błąd {nazwa}", extra=dict(
        kontekst, user_id=current_user.id, error=str(wyjatek)))
    return jsonify({
        'success': False,
        'error': 'Nie udało się policzyć danych. Szczegóły w logach serwera.',
    }), 500


def _odpowiedz_wykresu(nazwa, buduj):
    """
    Wspólna koperta endpointów wykresów.

    Każdy wykres ma WŁASNY endpoint (a nie jeden gruby /reports/all) dokładnie
    po to, żeby awaria albo wolne zapytanie kładło jeden widget, a nie całą
    podzakładkę. Ta funkcja tego pilnuje: zły zakres → 400, awaria → 500
    z logiem, sukces → {'success': True, ...payload}.
    """
    from ...services.worker_stats_service import ZakresError

    try:
        payload = buduj()
    except ZakresError as e:
        # ZakresError niesie WYŁĄCZNIE nasz własny komunikat walidacji
        # („Maksymalny zakres to 365 dni") — ten wolno pokazać.
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return _blad_serwera("wykresu raportów", e, wykres=nazwa)

    payload['success'] = True
    return jsonify(payload)


def _waliduj_stanowisko(domyslne='all'):
    """(kod, error_response) — 'all' albo kod z jedynej listy stanowisk."""
    station = request.args.get('station', domyslne).strip().lower() or domyslne
    if station != 'all' and station not in VALID_STATIONS:
        return None, (jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400)
    return station, None


# ════════════════════════════════════════════════════════════════════════════
# Wykresy zakładki Raporty
#
# Osiem endpointów, jeden na wykres. Agregaty siedzą w services/reports_service
# — tutaj zostaje wyłącznie parsowanie parametrów i koperta odpowiedzi, bo
# router nie jest miejscem na definicję tego, co znaczy „zrobione".
# ════════════════════════════════════════════════════════════════════════════

@api_bp.route('/reports/days-of-supply')
@login_required
def reports_days_of_supply():
    """
    GET /production/api/reports/days-of-supply

    Wykres 1: ile dni roboczych zajmie wypalenie kolejki przed stanowiskiem
    przy jego ostatnim tempie. Bez parametrów — to migawka stanu bieżącego
    zestawiona ze średnią z 14 ostatnich DNI ROBOCZYCH (liczonych z danych,
    nie z kalendarza).

    Odpowiedź niesie okno_dni/okno_od/okno_do i front MUSI je pokazać
    w nagłówku: przy krótszym oknie liczby skaczą (test na oknie jednodniowym
    dał wykańczaniu 64 dni zapasu zamiast 4,3) i bez podpisu nikt tego nie
    wytłumaczy.

    Badge „Trwa nauka" tu NIE występuje — wykres nie czyta atrybucji ani razu.
    """
    from ...services import reports_service

    return _odpowiedz_wykresu('days-of-supply',
                              reports_service.dni_zapasu_stanowisk)


@api_bp.route('/reports/deadline-progress')
@login_required
def reports_deadline_progress():
    """
    GET /production/api/reports/deadline-progress

    Wykres 2: ile m³ stoi w którym koszyku terminu i na jakim stanowisku.
    Bez parametrów — migawka stanu bieżącego, bez zakresu dat i presetów.

    `items` (do 500 pozycji + flaga items_truncated) jedzie w tej samej
    odpowiedzi, żeby klik w segment filtrował tabelę bez drugiego requestu.
    To nie ozdoba: w dniu wdrożenia wszystkie trzy pozycje ze słupka
    „Po terminie" to brud w danych (zamknięta logistyka ze statusem sprzed
    trzech miesięcy, pozycje z pakowaniem 3/3 i statusem „czeka na
    formatowanie") — sama liczba jest myląca, dopiero lista mówi, co z tym
    zrobić.

    ?items=0 — sama migawka koszyków, bez listy pozycji. Przegląd czyta
    WYŁĄCZNIE totals/datasets i lista jest dla niego czystym balastem:
    zmierzone na kopii produkcji 59.5 kB JSON (165 pozycji razem z nazwami
    klientów) wobec 1.6 kB samych agregatów. To nie jest nowy agregat — ten
    sam `termin_vs_postep()`, tylko z parametrem, który serwis miał od
    początku (limit_pozycji). Domyślne zachowanie bez parametru się nie
    zmienia, więc podzakładka Terminy nic o tym nie musi wiedzieć.
    """
    from ...services import reports_service

    bez_pozycji = request.args.get('items', '').strip() == '0'

    def buduj():
        if not bez_pozycji:
            return reports_service.termin_vs_postep()
        payload = reports_service.termin_vs_postep(limit_pozycji=0)
        # Przy limit_pozycji=0 serwis liczy przycięcie względem zera i ZAWSZE
        # oddaje items_truncated=True przy items=[] — czyli „lista przycięta",
        # choć listy nie było jak przyciąć. Skoro jej nie zamawiano, oba klucze
        # wypadają: brak pola jest uczciwszy niż pole kłamiące.
        payload.pop('items', None)
        payload.pop('items_truncated', None)
        return payload

    return _odpowiedz_wykresu('deadline-progress', buduj)


@api_bp.route('/reports/flow-in-out')
@login_required
def reports_flow_in_out():
    """
    GET /production/api/reports/flow-in-out
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        &granularity=auto|dzien|tydzien

    Wykres 3: m³ wchodzące (nowe pozycje) vs wychodzące (pakowanie) dzień po
    dniu plus skumulowana różnica. Domyślnie 90 dni.

    `days` jest ZAWSZE ciągłe i pełne (z zerami), a cumulative_diff_m3 jest już
    policzone narastająco po stronie serwera — dwa widgety nie mają jak
    skumulować tego samego inaczej. Oś jest 7-dniowa: zamówienia wpadają też
    w weekend, choć hala wtedy nie pracuje.
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat(domyslne_dni=90)
    if err:
        return err

    granulacja = request.args.get('granularity', 'auto').strip().lower()
    if granulacja not in ('auto', 'dzien', 'tydzien'):
        return jsonify({'success': False,
                        'error': 'granularity: auto | dzien | tydzien'}), 400

    return _odpowiedz_wykresu(
        'flow-in-out',
        lambda: reports_service.wejscie_vs_wyjscie(start_date, end_date, granulacja))


@api_bp.route('/reports/hourly-heatmap')
@login_required
def reports_hourly_heatmap():
    """
    GET /production/api/reports/hourly-heatmap
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    Wykres 4: siatka 7 × 24 (wiersz 0 = poniedziałek) ze ŚREDNIM m³ na jedno
    wystąpienie danego dnia tygodnia. Domyślnie 30 dni.

    grid_m3 jest JUŻ ZNORMALIZOWANY — front nie dzieli przez nic. Dzielnik
    jedzie osobno (weekday_occurrences) do podpisu, bo okno 30-dniowe potrafi
    mieć pięć poniedziałków i cztery czwartki.
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat(domyslne_dni=30)
    if err:
        return err

    return _odpowiedz_wykresu(
        'hourly-heatmap',
        lambda: reports_service.heatmapa_godzinowa(start_date, end_date))


@api_bp.route('/reports/staffing-vs-output')
@login_required
def reports_staffing_vs_output():
    """
    GET /production/api/reports/staffing-vs-output
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    Wykres 5: osobogodziny (z sesji pracy) vs przerób (z eventów) per
    stanowisko, plus iloraz m³ na osobogodzinę. Domyślnie 7 dni.

    Odpowiedź niesie `learning` — to główny konsument badge'a „Trwa nauka":
    obsada jest wiarygodna wyłącznie tam, gdzie ludzie się logują. Front
    porównuje stanowisko ZE SOBĄ W CZASIE, nigdy stanowiska między sobą
    (m³ nie są porównywalne: spakowanie metra trwa minuty, sklejenie godziny).
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat()
    if err:
        return err

    def buduj():
        payload = reports_service.obsada_vs_przerob(start_date, end_date)
        # Badge liczony na KONIEC zakresu, nie na jego długość — patrz
        # docstring reports_service.stan_nauki().
        payload['learning'] = reports_service.stan_nauki(end_date=end_date)
        return payload

    return _odpowiedz_wykresu('staffing-vs-output', buduj)


@api_bp.route('/reports/attribution-coverage')
@login_required
def reports_attribution_coverage():
    """
    GET /production/api/reports/attribution-coverage
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&station=all|<kod>

    Wykres 6: jaki procent zarejestrowanego ruchu ma podpis pracownika, dzień
    po dniu. Domyślnie 7 dni.

    Badge „Trwa nauka" tu NIE występuje i to jest świadome: ten wykres JEST
    miernikiem nauki, więc oznaczanie go byłoby błędnym kołem.

    Dzień bez produkcji ma coverage_pct = None (dziura w linii, spanGaps:false),
    a nie zero. summary.coverage_pct to suma liczników / suma mianowników,
    czyli wartość ważona wykresu — tą samą liczbą zasilany jest kafelek
    pokrycia w widgecie wydajności pracowników.
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat()
    if err:
        return err

    station, err = _waliduj_stanowisko()
    if err:
        return err

    return _odpowiedz_wykresu(
        'attribution-coverage',
        lambda: reports_service.pokrycie_atrybucji_dziennie(
            start_date, end_date, station=station))


@api_bp.route('/reports/rework-registration')
@login_required
def reports_rework_registration():
    """
    GET /production/api/reports/rework-registration
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    Wykres 7: doróbki tydzień po tygodniu. Domyślnie 90 dni.

    UWAGA DLA FRONTU: dopóki `threshold_met` jest false, widget ma rysować
    PANEL INFORMACYJNY (liczby + zdanie diagnozy z `reporting_stations`),
    a nie pusty wykres. Powód jest merytoryczny: zgłaszać doróbkę da się dziś
    tylko z formatowania, więc słupek „prawie zero doróbek" czyta się jako
    „jakość świetna", a znaczy „sześć z siedmiu stanowisk nie ma jak zgłosić".
    Pusty canvas z napisem „brak danych w wybranym okresie" byłby tu
    podpowiedzią, że wystarczy zmienić zakres dat — a nie wystarczy.

    Badge „Trwa nauka" tu NIE występuje: ograniczeniem jest zakres endpointu
    mobilnego, nie doświadczenie hali z apką. Czekanie niczego nie zmieni.
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat(domyslne_dni=90)
    if err:
        return err

    return _odpowiedz_wykresu(
        'rework-registration',
        lambda: reports_service.rejestracja_dorobek(start_date, end_date))


@api_bp.route('/reports/station-worker-output')
@login_required
def reports_station_worker_output():
    """
    GET /production/api/reports/station-worker-output
        ?station=<kod>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    Wykres 8: kto ile zrobił na JEDNYM stanowisku — m³ (oś lewa) i wkład
    w sztukach (oś prawa), plus wyszarzony słupek „Nieprzypisane". Domyślnie
    jeden dzień, jak sąsiedni widget „Wykonanie stanowiska w dniu".

    `station` jest OBOWIĄZKOWE i 'all' leci 400, a nie sumą wszystkich
    stanowisk. To nie jest niedoróbka walidacji, tylko warunek, pod którym ten
    wykres w ogóle powstał: porównywanie ludzi między stanowiskami mierzy, kto
    stał na końcu procesu (spakowanie metra trwa minuty, sklejenie godziny),
    a nie kto się narobił. Wewnątrz jednego stanowiska to samo porównanie jest
    uczciwe — i tylko takie ten endpoint oddaje.

    Odpowiedź niesie `learning`: widget stoi w całości na atrybucji, więc badge
    „Trwa nauka" należy mu się tak samo jak wykresowi obsady. Liczony na koniec
    zakresu, nie na jego długość.

    Bramka stoi PO OBU STRONACH: tutaj (żeby przeglądarka dostała czytelne 400
    z listą dozwolonych kodów) i w serwisie (żeby każdy inny konsument dostał
    to samo). Router bez serwisu przepuszczał literówkę w kodzie stanowiska
    wszędzie tam, gdzie agregat woła się bezpośrednio — a odpowiedzią było
    ciche „stanowisko nic nie zrobiło".
    """
    from ...services import reports_service

    start_date, end_date, err = _parsuj_zakres_dat(domyslne_dni=1)
    if err:
        return err

    station = request.args.get('station', '').strip().lower()
    if station in ('', 'all'):
        return jsonify({
            'success': False,
            'error': ('Podaj JEDNO stanowisko — m³ nie są porównywalne między '
                      'stanowiskami, więc wykres zbiorczy nie znaczyłby nic. '
                      f'Dozwolone: {sorted(VALID_STATIONS)}'),
        }), 400
    if station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: {sorted(VALID_STATIONS)}',
        }), 400

    def buduj():
        payload = reports_service.wklad_pracownikow_na_stanowisku(
            station, start_date, end_date)
        payload['learning'] = reports_service.stan_nauki(end_date=end_date)
        return payload

    return _odpowiedz_wykresu('station-worker-output', buduj)


@api_bp.route('/reports/worker-output')
@login_required
def reports_worker_output():
    """
    GET /production/api/reports/worker-output
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        &station=all|<station_code>&worker_id=<opcjonalnie>
        &format=json|xlsx

    Wydajność pracowników liczona z atrybucji eventów stanowiskowych
    (docs/worker-profiles-backend.md §7.2). Jeden event dzieli się między
    pracowników przez share = 1/N, więc sumy są ułamkowe.

    Dane są POGLĄDOWE: wybór profilu na tablecie nie jest chroniony hasłem.
    Odpowiedź niesie attribution_coverage_pct — ile produkcji w okresie
    w ogóle da się komuś przypisać.
    """
    from ...services import worker_stats_service
    from ...services.worker_stats_service import ZakresError

    start_date, end_date, err = _parsuj_zakres_dat()
    if err:
        return err

    station = request.args.get('station', 'all').strip().lower() or 'all'
    if station != 'all' and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    worker_id = request.args.get('worker_id', '').strip()
    try:
        worker_id = int(worker_id) if worker_id else None
    except ValueError:
        return jsonify({'success': False, 'error': 'worker_id musi być liczbą'}), 400

    try:
        raport = worker_stats_service.raport_wydajnosci(
            start_date, end_date, station=station, worker_id=worker_id)
        # Badge „Trwa nauka" należy do tego widgetu tak samo jak do wykresu
        # obsady: tabela mówi o LUDZIACH, a mówi o nich tyle, ile tablety
        # zdążyły zaraportować. Liczony na koniec zakresu, nie na jego długość.
        from ...services import reports_service
        raport['learning'] = reports_service.stan_nauki(end_date=end_date)
    except ZakresError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    if request.args.get('format', 'json').strip().lower() == 'xlsx':
        return _eksport_raportu_pracownikow(raport)

    return jsonify({'success': True, 'report': raport})


def _eksport_raportu_pracownikow(raport):
    """XLSX z dwoma arkuszami: podsumowanie per pracownik i pełne wiersze."""
    from io import BytesIO

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        logger.warning("openpyxl niedostępne — eksport raportu pracowników odrzucony")
        return jsonify({'success': False,
                        'error': 'Eksport XLSX niedostępny (brak openpyxl)'}), 501

    wb = Workbook()

    ark = wb.active
    ark.title = 'Podsumowanie'
    ark.append(['Pracownik', 'Sztuki', 'm3', 'Godziny', 'Tempo (m3/h)', 'Stanowiska'])
    for komorka in ark[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['worker_totals']:
        ark.append([
            wiersz['worker_name'], wiersz['pieces'], wiersz['m3'],
            wiersz['hours'], wiersz['pace_m3_per_hour'],
            ', '.join(wiersz['stations']),
        ])

    podsumowanie = raport['summary']
    ark.append([])
    ark.append(['Nieprzypisane', podsumowanie['unassigned_pieces'],
                podsumowanie['unassigned_m3']])
    ark.append(['Pokrycie atrybucją (%)', podsumowanie['attribution_coverage_pct']])
    ark.append(['UWAGA: wybór profilu na tablecie nie jest chroniony hasłem — '
                'dane mają charakter poglądowy'])
    # Zastrzeżenie o dojrzałości danych jedzie do arkusza pod istniejącym
    # ostrzeżeniem — wyeksportowana tabela nie ma prawa zgubić kontekstu,
    # który widać w widgecie.
    nauka = raport.get('learning') or {}
    if nauka.get('learning'):
        ark.append([nauka['text']])

    szczegoly = wb.create_sheet('Szczegóły')
    szczegoly.append(['Data', 'Pracownik', 'Stanowisko', 'Sztuki', 'm3'])
    for komorka in szczegoly[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['rows']:
        szczegoly.append([wiersz['work_date'], wiersz['worker_name'],
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])
    for wiersz in raport['unassigned']:
        szczegoly.append([wiersz['work_date'], 'Nieprzypisane',
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])

    strumien = BytesIO()
    wb.save(strumien)
    strumien.seek(0)

    from flask import Response
    nazwa = f"wydajnosc_pracownikow_{raport['start_date']}_{raport['end_date']}.xlsx"
    odpowiedz = Response(
        strumien.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    odpowiedz.headers['Content-Disposition'] = f'attachment; filename={nazwa}'
    return odpowiedz


@api_bp.route('/reports/station-output')
@login_required
def reports_station_output():
    """
    GET /production/api/reports/station-output?station=<code|all>
        &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        (lub: &date=YYYY-MM-DD — wsteczna kompat, pojedynczy dzień)

    Zwraca pozycje produkcyjne, na których wybrane stanowisko (lub
    dowolne stanowisko gdy station='all') wykonało jakąkolwiek operację
    w zakresie dat (włącznie).

    Dla każdej pozycji (wiersz per item × stanowisko):
    - quantity_done_eod: stan quantity_done_<station> po ostatnim evencie
      w zakresie — ile zostało wykonane na koniec zakresu
    - day_delta_sum: netto ruch w zakresie (suma delta) — np. +5,-1,+2 = +6
    - station_code, station_label: stanowisko, którego dotyczy wiersz
    - quantity: total szt. pozycji
    - volume_per_unit, volume_done_eod (m³)
    - meta: short_product_id, original_product_name, baselinker_order_id, status, gatunek/grubość

    Lista jest STRONICOWANA PO STRONIE SERWERA (limit/offset, patrz
    `pagination` w odpowiedzi). Kafelki i timeline liczą się z osobnych
    agregatów, więc nie zależą od strony — przełączanie stron nie zmienia
    ani jednej liczby u góry widgetu.

    Timeline: 48 bucketów po 30 min, sumy delta i delta*volume_m3
    (przez wszystkie stanowiska gdy station='all'). Frontend dzieli
    przez days_count żeby uzyskać średnią dzienną.

    Sortowanie: po ostatnim evencie w zakresie (najnowsze najpierw).
    """
    from ...models import ProductionStationEvent

    station = request.args.get('station', '').strip().lower()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    date_str = request.args.get('date', '').strip()  # wsteczna kompat

    is_all_stations = station == 'all'
    if not is_all_stations and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    limit, offset, err = _parsuj_stronicowanie()
    if err:
        return err

    # Parsowanie zakresu: preferuj start_date/end_date, fallback na date.
    # Podanie TYLKO jednej z dwóch granic to błąd, nie zaproszenie do domyślnego
    # zakresu — patrz _parsuj_zakres_dat().
    if bool(start_date_str) != bool(end_date_str):
        return jsonify({
            'success': False,
            'error': 'Podaj obie daty zakresu (start_date i end_date) albo żadnej'
        }), 400
    try:
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        elif date_str:
            start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            end_date = start_date
        else:
            # get_local_now(), NIE date.today(): kontener chodzi na UTC, więc
            # między północą a 02:00 czasu polskiego date.today() oddawał
            # wczoraj — patrz _parsuj_zakres_dat().
            start_date = end_date = get_local_now().date()
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400

    if start_date > end_date:
        return jsonify({
            'success': False,
            'error': 'Data początkowa musi być wcześniejsza lub równa końcowej'
        }), 400

    days_count = (end_date - start_date).days + 1
    if days_count > 365:
        return jsonify({
            'success': False,
            'error': 'Maksymalny zakres to 365 dni'
        }), 400

    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date, datetime.max.time())

    try:
        # Wspólne filtry zakresu czasu (+ ewentualnie konkretne stanowisko).
        # Filtr ZRODLA_AUTOMATU jest OBOWIĄZKOWY i wspólny ze
        # station_events_service oraz worker_stats_service: complete_task()
        # generuje sztuczne eventy dla stanowisk POMINIĘTYCH (produkt
        # nieprzycinany na wymiar przeskakuje formatowanie i wykańczanie).
        # Bez niego trzy widgety na jednym ekranie pokazywały trzy różne
        # odpowiedzi na pytanie "ile zrobiono na formatowaniu" — a różnicy
        # nie dawało się wytłumaczyć wierszem "Nieprzypisane", bo tych sztuk
        # w liczniku pracowniczym w ogóle nie ma.
        from ...services.station_events_service import ZRODLA_AUTOMATU

        time_filters = [
            ProductionStationEvent.created_at >= range_start,
            ProductionStationEvent.created_at <= range_end,
            ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if not is_all_stations:
            time_filters.append(ProductionStationEvent.station_code == station)

        # Ile sztuk automat przeskoczył w tym zakresie — pokazujemy to jawnie
        # w widgecie, żeby nikt nie szukał "brakujących" sztuk po zmianie.
        pominiete_filtry = [
            ProductionStationEvent.created_at >= range_start,
            ProductionStationEvent.created_at <= range_end,
            ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if not is_all_stations:
            pominiete_filtry.append(ProductionStationEvent.station_code == station)
        auto_pominiete = db.session.query(
            func.coalesce(func.sum(ProductionStationEvent.delta), 0)
        ).filter(*pominiete_filtry).scalar() or 0

        # Per (item, station) agregacja eventów w zakresie.
        # Group by zawsze po (item_id, station_code) — dla pojedynczego
        # stanowiska wszystkie wiersze i tak mają to samo station_code,
        # więc koszt jest zerowy a kod jest unifikowany.
        # day_delta_sum = SUM(delta) (mimo nazwy — to ruch w całym zakresie)
        # last_event_at = MAX(created_at), last_event_id = MAX(id)
        agg_q = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.station_code.label('station_code'),
            func.sum(ProductionStationEvent.delta).label('day_delta_sum'),
            func.max(ProductionStationEvent.created_at).label('last_event_at'),
            func.max(ProductionStationEvent.id).label('last_event_id'),
            func.count(ProductionStationEvent.id).label('event_count'),
        ).filter(*time_filters).group_by(
            ProductionStationEvent.production_item_id,
            ProductionStationEvent.station_code,
        )
        agg = agg_q.subquery()

        # ── Kafelki: z osobnych agregatów, NIE z sumowania stronicowanej listy ──
        #
        # Liczba WIERSZY (pozycja × stanowisko) i liczba różnych PRODUKTÓW to
        # dwie różne liczby i w trybie „Wszystkie stanowiska" różnią się
        # trzykrotnie: 30 dni to 2540 wierszy przy 789 produktach. Kafelek
        # podpisany „Pozycje" pokazywał tę pierwszą.
        rows_count = db.session.query(func.count()).select_from(agg).scalar() or 0
        distinct_items = db.session.query(
            func.count(func.distinct(ProductionStationEvent.production_item_id))
        ).filter(*time_filters).scalar() or 0
        # Ruch jest ADDYTYWNY — suma delt po wierszach to dokładnie suma delt
        # po eventach, więc jedno skalarne zapytanie zamiast pętli po payloadzie.
        sum_day_delta = int(db.session.query(
            func.coalesce(func.sum(ProductionStationEvent.delta), 0)
        ).filter(*time_filters).scalar() or 0)

        # STAN (EOD) sumujemy WYŁĄCZNIE dla jednego stanowiska. W trybie
        # zbiorczym suma stanów z siedmiu stanowisk nie jest stanem czegokolwiek
        # — zmierzone na 30 dniach: 84.180 m³ „wykonane" przy 28.260 m³ pełnej
        # objętości tych produktów, czyli kafelek przekraczał fizyczne maksimum
        # trzykrotnie. Front w tym trybie chowa oba kafelki stanu (None).
        sum_qty_done_eod = None
        sum_volume_done_eod = None
        if not is_all_stations:
            stan_q = db.session.query(
                func.coalesce(func.sum(ProductionStationEvent.quantity_done_after), 0),
                func.coalesce(func.sum(
                    ProductionStationEvent.quantity_done_after
                    * func.coalesce(ProductionItem.volume_m3, 0)), 0),
            ).select_from(agg).join(
                ProductionStationEvent,
                ProductionStationEvent.id == agg.c.last_event_id,
            ).join(
                ProductionItem, ProductionItem.id == agg.c.item_id
            ).one()
            sum_qty_done_eod = int(stan_q[0] or 0)
            sum_volume_done_eod = round(float(stan_q[1] or 0.0), 4)

        # ── Strona listy ──
        #
        # Jawna lista kolumn zamiast encji ProductionItem: serializer niżej
        # czyta siedem pól, a encja ciągnęła z bazy także shape_svg (1.58 MB
        # w tabeli) i edge_svg (0.69 MB), których nikt tu nie ogląda.
        # Join po `last_event_id` (MAX(id)), nie po `last_event_at`: przy
        # remisie created_at — a tablet zapisuje wsad kilkoma eventami w tej
        # samej sekundzie, takich grup jest w bazie 3053 — join po znaczniku
        # czasu oddawał N wierszy i dedup w pętli brał PIERWSZY Z BRZEGU.
        # Zmierzone 2026-08-12: pozycja 887_1 pokazywała „1 / 3" przy eventach
        # kończących się na quantity_done_after = 3. MAX(id) jest przy okazji
        # właściwą definicją „stanu po ostatnim zdarzeniu": quantity_done_after
        # to migawka zapisana w chwili INSERT-u, więc rozstrzyga kolejność
        # zapisu, nie znacznik czasu (który admin może wpisać wstecz).
        rows = db.session.query(
            agg.c.item_id,
            agg.c.station_code,
            agg.c.day_delta_sum,
            agg.c.last_event_at,
            agg.c.event_count,
            ProductionStationEvent.quantity_done_after.label('quantity_done_eod'),
            ProductionItem.short_product_id,
            ProductionItem.original_product_name,
            ProductionItem.current_status,
            ProductionItem.quantity,
            ProductionItem.volume_m3,
            ProductionItem.parsed_thickness_cm,
            ProductionOrder.baselinker_order_id,
            ProductionOrder.internal_order_number,
            ProductionConfiguration.species,
        ).select_from(agg).join(
            ProductionStationEvent,
            ProductionStationEvent.id == agg.c.last_event_id,
        ).join(
            ProductionItem, ProductionItem.id == agg.c.item_id
        ).outerjoin(
            ProductionOrder, ProductionOrder.id == ProductionItem.order_id
        ).outerjoin(
            ProductionConfiguration,
            ProductionConfiguration.id == ProductionItem.configuration_id
        ).order_by(
            agg.c.last_event_at.desc(), agg.c.item_id.desc()
        ).limit(limit).offset(offset).all()

        items_payload = []
        for w in rows:
            qty_done_eod = int(w.quantity_done_eod or 0)
            volume_per_unit = float(w.volume_m3 or 0)
            items_payload.append({
                'item_id': w.item_id,
                'short_product_id': w.short_product_id,
                'product_name': w.original_product_name,
                'baselinker_order_id': w.baselinker_order_id,
                'internal_order_number': w.internal_order_number,
                'current_status': w.current_status,
                'quantity': w.quantity,
                'quantity_done_eod': qty_done_eod,
                'day_delta_sum': int(w.day_delta_sum or 0),
                'event_count': int(w.event_count or 0),
                'volume_per_unit_m3': round(volume_per_unit, 4),
                'volume_done_eod_m3': round(volume_per_unit * qty_done_eod, 4),
                'wood_species': w.species,
                'thickness_cm': (float(w.parsed_thickness_cm)
                                 if w.parsed_thickness_cm else None),
                'last_event_at': (w.last_event_at.isoformat()
                                  if w.last_event_at else None),
                'station_code': w.station_code,
                'station_label': STATION_LABELS.get(w.station_code, w.station_code),
            })

        # Timeline 48 bucketów po 30 minut (00:00, 00:30, ..., 23:30)
        # bucket_idx = floor((HOUR*60 + MINUTE) / 30) ∈ [0, 47]
        # Net delta per bucket (cofnięcia mogą dać wartość ujemną).
        # Sumowanie po wszystkich dniach w zakresie — frontend dzieli
        # przez days_count żeby uzyskać średnią dzienną gdy zakres > 1 dnia.
        bucket_idx_expr = func.floor(
            (func.hour(ProductionStationEvent.created_at) * 60
             + func.minute(ProductionStationEvent.created_at)) / 30
        ).label('bucket_idx')

        timeline_rows = db.session.query(
            bucket_idx_expr,
            func.sum(ProductionStationEvent.delta).label('pieces_sum'),
            func.sum(
                ProductionStationEvent.delta * ProductionItem.volume_m3
            ).label('m3_sum'),
        ).join(
            ProductionItem,
            ProductionItem.id == ProductionStationEvent.production_item_id
        ).filter(*time_filters).group_by(bucket_idx_expr).all()

        pieces_buckets = [0] * 48
        m3_buckets = [0.0] * 48
        for bucket_idx, pieces_sum, m3_sum in timeline_rows:
            idx = int(bucket_idx) if bucket_idx is not None else None
            if idx is None or idx < 0 or idx > 47:
                continue
            pieces_buckets[idx] = int(pieces_sum or 0)
            m3_buckets[idx] = round(float(m3_sum or 0.0), 4)

        bucket_labels = [
            f"{i // 2:02d}:{'30' if i % 2 else '00'}"
            for i in range(48)
        ]

        return jsonify({
            'success': True,
            'station': station,
            'station_label': 'Wszystkie stanowiska' if is_all_stations
                else STATION_LABELS.get(station, station),
            'is_all_stations': is_all_stations,
            # Wsteczna kompat: 'date' = start gdy pojedynczy dzień, inaczej None
            'date': start_date.isoformat() if days_count == 1 else None,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'days_count': days_count,
            'items': items_payload,
            'pagination': {
                'limit': limit,
                'offset': offset,
                'total': int(rows_count),
            },
            'summary': {
                # Wiersz = pozycja × stanowisko. W trybie zbiorczym ta liczba
                # NIE jest liczbą produktów — stąd druga obok.
                'items_count': int(rows_count),
                'distinct_items_count': int(distinct_items),
                # None w trybie zbiorczym: suma stanów z różnych stanowisk nie
                # jest stanem niczego (patrz komentarz przy stan_q wyżej).
                'total_quantity_done_eod': sum_qty_done_eod,
                'total_volume_done_eod_m3': sum_volume_done_eod,
                'total_day_delta': sum_day_delta,
                # Sztuki, które automat przeskoczył — NIE są wliczone powyżej.
                # Pokazujemy je jawnie, żeby nikt nie szukał różnicy między
                # tym widgetem a stanem quantity_done produktu.
                'auto_skipped_pieces': int(auto_pominiete),
            },
            'timeline': {
                'buckets': bucket_labels,
                'pieces': pieces_buckets,
                'volume_m3': m3_buckets,
                'days_count': days_count,
            },
        })

    except Exception as e:
        # str(e) idzie do LOGU, nie do przeglądarki: przy błędzie SQLAlchemy
        # tekst wyjątku niesie pełne zapytanie razem z bindami (nazwy klientów
        # i produktów z BaseLinkera), a zakładkę czyta każdy zalogowany —
        # endpoint ma tylko @login_required, bez sprawdzania roli.
        return _blad_serwera("/reports/station-output", e, station=station)


@api_bp.route('/reports-tab-content')
@login_required
def reports_tab_content():
    """
    Szkielet zakładki Raporty: pasek KPI + nawigacja podzakładek.

    Dane widgetów NIE jadą tędy — każda podzakładka pobiera swoje osobno
    (patrz /reports/sub/<nazwa>). Tutaj zostają dwa agregaty na trzy kafelki.
    """
    try:
        logger.info("AJAX: Ładowanie zawartości reports-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem

        # get_local_now(), NIE date.today(): kontener chodzi na UTC (tzname
        # ('UTC','UTC'), datetime.now() 09:07 przy get_local_now() 11:07), więc
        # date.today() między północą a 02:00 czasu polskiego oddaje WCZORAJ.
        # Wszystkie widgety pod tym paskiem liczą z czasu lokalnego, więc pasek
        # KPI pokazywał wtedy inne okno niż one: zmierzone na prod_products,
        # okno lokalne 08-06..08-12 = 163 poz / 5.849 m³, okno przesunięte
        # o dobę = 195 poz / 7.657 m³ (+19.6% / +30.9%).
        today = get_local_now().date()

        # Kafelki KPI: ukończone i m³ z ostatnich 7 dni. Wcześniej liczyła to
        # pętla po dniach — 14 zapytań na dwie liczby, które i tak zaraz były
        # sumowane. Rozbicie dzienne nie miało konsumenta (ani szablon, ani JS
        # go nie czytały), więc jeden agregat na całym zakresie daje ten sam
        # wynik za jedno zapytanie.
        tydzien_start = datetime.combine(today - timedelta(days=6), datetime.min.time())
        tydzien_koniec = datetime.combine(today, datetime.max.time())

        tydzien_sztuk, tydzien_m3 = db.session.query(
            func.count(ProductionItem.id),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity)
        ).filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= tydzien_start,
            ProductionItem.packaging_completed_at <= tydzien_koniec
        ).one()

        # Osobny COUNT zamiast sumy po rozbiciu statusów: pasek KPI szkieletu
        # nie może zależeć od danych widgetu, który po przebudowie mieszka
        # w innej podzakładce i ładuje się dopiero po kliknięciu.
        total_in_system = db.session.query(func.count(ProductionItem.id)).filter(
            ProductionItem.current_status.isnot(None)
        ).scalar() or 0

        # Szkielet nie zna już danych widgetów — dostaje wyłącznie trzy liczby
        # do kafelków. Reszta jedzie przez /reports/sub/<nazwa>, każda porcja
        # dopiero wtedy, gdy ktoś na nią patrzy.
        rendered_html = render_template(
            'components/reports-tab-content.html',
            reports_summary={
                'week_completed': int(tydzien_sztuk or 0),
                'week_volume': float(tydzien_m3 or 0.0),
                'total_in_system': int(total_in_system),
            },
        )

        # Bez klucza 'data': jedyny konsument odpowiedzi (production-app-loader
        # loadReportsTab) czyta wyłącznie 'html', a kopia całego kompletu danych
        # dorzucała ~5 kB do każdego wejścia na zakładkę.
        return jsonify({
            'success': True,
            'html': rendered_html,
            'last_updated': get_local_now().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX reports-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ════════════════════════════════════════════════════════════════════════════
# Podzakładki zakładki Raporty
#
# Zakładka Raporty ładowała jednym strzałem komplet danych dla sześciu widgetów
# naraz — także tych, w które nikt nie patrzy. Podzakładka to fragment HTML
# pobierany dopiero przy kliknięciu, z własnym (i tylko własnym) kompletem
# zapytań.
# ════════════════════════════════════════════════════════════════════════════

def _kontekst_przeglad():
    """
    PRZEGLĄD — pierwsza i domyślna podzakładka. Sześć elementów, ZERO SQL tutaj.

    BUDŻET (zmierzony test_clientem na kopii produkcji 2026-08-12, mediana
    z 5 przebiegów po rozgrzewce, kontener worker-profiles-app-1):
      ten kontekst / cały fragment       0 zapytań  (zegar + katalog + konfig)
      /reports-tab-content               2 zapytania — bez zmian, nie dotykamy
      /reports/days-of-supply            3 zapytania / 20.3 ms / 1.7 kB
      /reports/deadline-progress?items=0 2 zapytania /  4.1 ms / 3.5 kB
      /workers/active-sessions           2 zapytania /  0.7 ms / 2.3 kB
      /reports/staffing-vs-output        7 zapytań   /  8.1 ms / 2.5 kB
      /reports/flow-in-out               3 zapytania /  3.1 ms / 2.0 kB
      ────────────────────────────────────────────────────────────────────
      pięć żądań danych razem:  17 zapytań / 36.4 ms SQL / 12.0 kB
      wejście na Raporty z Przeglądem:  2 + 17 = 19 zapytań
      to samo wejście ze Stanowiskami:  2 + 34 = 36 zapytań (7 żądań, 129 kB)

    TWARDY LIMIT: 20 zapytań. Przekroczenie znaczy, że element ma wypaść albo
    zacytować liczbę już policzoną — nie że dokładamy szóste żądanie.

    Przegląd nie ma ANI JEDNEGO własnego agregatu — cytuje pięć endpointów,
    które już istnieją i już mają swoich konsumentów:

      /reports/days-of-supply                      → Kolejki
      /reports/deadline-progress?items=0           → Terminy + Praca po terminie
      /workers/active-sessions                     → Kto jest na hali (lista)
      /reports/staffing-vs-output?start=end=dziś   → osobogodziny + badge nauki
      /reports/flow-in-out?start=dziś-13&end=dziś  → Wejście/wyjście hali

    `stan_nauki()` leci przez to DOKŁADNIE RAZ na wejście — jedzie w kopercie
    staffing-vs-output i zasila zarówno badge „Trwa nauka", jak i element
    „Wdrożenie profili". Osobne żądanie po stan nauki byłoby drugim wywołaniem
    tej samej funkcji w tym samym ekranie.

    Wszystkie trzy wartości niżej są liczone z GET_LOCAL_NOW(), nie z zegara
    przeglądarki: kontener chodzi na UTC, a przeglądarka bywa w innej strefie —
    data wysyłana do endpointów musi być tą samą dobą, którą serwis nazywa
    „dziś" w polu as_of.
    """
    from ...services.worker_service import get_idle_timeout_minutes

    teraz = get_local_now()
    dzis = teraz.date()

    return {
        # Stempel „Stan na HH:MM" — element 1 Przeglądu. Odświeżenie przeładowuje
        # cały fragment, więc stempel odnawia się razem z danymi.
        'przeglad_stan_na': teraz.strftime('%H:%M'),
        'przeglad_dzis': dzis.isoformat(),
        # Okno przepływu: 14 dni włącznie z dziś. Poniżej progu agregacji
        # tygodniowej (120 dni), więc granularity='dzien' jest gwarantowane.
        'przeglad_przeplyw_od': (dzis - timedelta(days=13)).isoformat(),
        # Próg bezczynności do zdania „wszystkie sesje przekroczyły N min".
        # Z konfiguracji (cache'owanej), nigdy zaszyty w szablonie — admin
        # zmienia go w prod_config bez deployu.
        'przeglad_idle_minut': get_idle_timeout_minutes(),
        # Które kody to STANOWISKA — do rozdzielenia „po terminie na produkcji"
        # od „po terminie poza produkcją (Logistyka, Wstrzymane)". Z katalogu,
        # nie z listy literałów w JS (zasada: nazwy stanowisk tylko stamtąd).
        'przeglad_kody_stanowisk': list(STATION_ORDER),
    }


def _kontekst_stanowiska():
    """Wykonanie stanowiska w dniu + wydajność dzienna. Zero SQL — oba widgety
    dociągają swoje liczby własnymi endpointami po stronie przeglądarki."""
    return {'station_choices': station_choices()}


def _kontekst_ludzie():
    """Wydajność pracowników. Jak wyżej: sam <select> stanowisk, dane z
    /reports/worker-output."""
    return {'station_choices': station_choices()}


def _kontekst_terminy():
    """
    „Czy nadążamy": termin vs postęp + wejście vs wyjście hali.

    Zero SQL — oba widgety dociągają swoje liczby własnymi endpointami
    (/reports/deadline-progress i /reports/flow-in-out) po stronie
    przeglądarki. Wejście na zakładkę Raporty ma dalej kosztować dwa agregaty
    do kafelków KPI i ani jednego zapytania więcej.

    Selektora stanowisk tu nie ma celowo: pierwszy widget jest migawką całej
    hali rozbitą na stanowiska, drugi pyta o przepływ hali jako całości.
    """
    return {}


# Odwrotność STATION_PENDING_STATUS — status kolejki → kod stanowiska.
_STATUS_NA_STANOWISKO = {
    status: kod for kod, status in STATION_PENDING_STATUS.items()
}

# Statusy, które stanowiskiem NIE SĄ. Osobny słownik, bo station_catalog ich
# nie zna i znać nie powinien — to etapy cyklu życia pozycji, nie miejsca
# w hali. Nazwy zgodne z reports_service.ETAPY_POZA_STANOWISKAMI.
_ETYKIETY_STATUSOW_POZA_PIPELINE = {
    'spakowane': 'Spakowane',
    'anulowane': 'Anulowane',
    'czeka_na_logistyke': 'Logistyka',
    'wstrzymane': 'Wstrzymane',
    'w_realizacji': 'W realizacji',
}


def _etykieta_statusu(status):
    """
    Nazwa statusu do wyświetlenia — Z KATALOGU, nie ze składania stringów.

    Szablon robił dotąd `status.replace('czeka_na_','').replace('_',' ').title()`
    i produkował TRZECI zestaw nazw tych samych stanowisk: „Lakiernie" zamiast
    „Lakiernia", „Skladanie" zamiast „Składanie - lite", „Wykanczanie" zamiast
    „Wykańczanie" — pięć z dziesięciu wierszy pod inną nazwą niż reszta
    aplikacji i bez polskich znaków. Liczby zgadzały się co do trzeciego
    miejsca; rozjeżdżały się wyłącznie etykiety.
    """
    kod = _STATUS_NA_STANOWISKO.get(status)
    if kod:
        return station_label(kod)
    return _ETYKIETY_STATUSOW_POZA_PIPELINE.get(
        status, str(status or '').replace('_', ' ').capitalize())


def _kontekst_miks():
    """Rozkład wg statusów + analiza produktów.

    Sześć GROUP BY po całej tabeli, bez zakresu dat — najdroższa podzakładka
    i jednocześnie ta, w którą klika się najrzadziej. Dlatego liczy się dopiero
    tutaj, a nie przy każdym wejściu na Raporty.
    """
    # Raport statusów - dynamicznie ze wszystkich istniejących w bazie
    status_stats = db.session.query(
        ProductionItem.current_status,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).filter(
        ProductionItem.current_status.isnot(None)
    ).group_by(ProductionItem.current_status).all()

    status_report = [
        {
            'status': row[0],
            # Gotowa etykieta jedzie z serwera. Szablon i JS mają ją tylko
            # wypisać — składanie nazwy w dwóch miejscach (Jinja i Chart.js)
            # to dwie kopie tej samej reguły i dwie okazje do rozjazdu.
            'label': _etykieta_statusu(row[0]),
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in status_stats
    ]

    # Species+technology breakdown per status
    species_by_status_raw = db.session.query(
        ProductionItem.current_status,
        ProductionConfiguration.species,
        ProductionConfiguration.technology,
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionItem.current_status.isnot(None),
        ProductionConfiguration.species.isnot(None)
    ).group_by(
        ProductionItem.current_status,
        ProductionConfiguration.species,
        ProductionConfiguration.technology
    ).all()

    species_by_status = {}
    for row in species_by_status_raw:
        status = row[0]
        species = row[1] or '—'
        tech = row[2] or ''
        label = f"{species} {tech}".strip()
        vol = float(row[3] or 0)
        if status not in species_by_status:
            species_by_status[status] = []
        species_by_status[status].append({'label': label, 'volume': round(vol, 3)})

    # Sort each status's species list by volume desc
    for status in species_by_status:
        species_by_status[status].sort(key=lambda x: -x['volume'])

    # Attach to status_report
    for item in status_report:
        item['species_breakdown'] = species_by_status.get(item['status'], [])

    # Rozkład według gatunków drewna
    species_stats = db.session.query(
        ProductionConfiguration.species,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.species.isnot(None),
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.species).all()

    species_breakdown = [
        {
            'name': row[0] or 'Nieokreślony',
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in species_stats
    ]

    # Rozkład według grubości
    thickness_stats = db.session.query(
        ProductionItem.parsed_thickness_cm,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).filter(
        ProductionItem.parsed_thickness_cm.isnot(None),
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionItem.parsed_thickness_cm).all()

    thickness_breakdown = [
        {
            'thickness': float(row[0]) if row[0] else 0,
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in thickness_stats
    ]
    # Sortowanie po grubości
    thickness_breakdown.sort(key=lambda x: x['thickness'])

    # Rozkład według technologii
    technology_stats = db.session.query(
        ProductionConfiguration.technology,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.technology.isnot(None),
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.technology).all()

    technology_breakdown = [
        {
            'name': row[0] or 'Nieokreślona',
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in technology_stats
    ]

    # Rozkład według klasy drewna
    wood_class_stats = db.session.query(
        ProductionConfiguration.wood_class,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.wood_class.isnot(None),
        ProductionConfiguration.wood_class != 'unknown',
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.wood_class).all()

    wood_class_breakdown = [
        {
            'name': row[0] or 'Nieokreślona',
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in wood_class_stats
    ]

    return {
        'status_breakdown': status_report,
        'species_breakdown': species_breakdown,
        'thickness_breakdown': thickness_breakdown,
        'technology_breakdown': technology_breakdown,
        'wood_class_breakdown': wood_class_breakdown,
        # Mianownik kolumny "% całości" liczymy z tego, co już mamy w ręku:
        # status_report obejmuje wszystkie produkty z niepustym statusem, czyli
        # dokładnie tyle, ile liczy COUNT(*) w pasku KPI. Osobne zapytanie
        # dołożyłoby siódme na tę samą liczbę.
        'total_in_system': sum(poz['count'] for poz in status_report),
    }


def _kontekst_system():
    """Historia synchronizacji — jedno zapytanie, oglądane raz na miesiąc."""
    sync_history = ProductionSyncLog.query\
                                   .order_by(ProductionSyncLog.sync_started_at.desc())\
                                   .limit(10).all()
    return {
        'sync_history': [
            {
                'date': sync.sync_started_at.isoformat(),
                'status': sync.sync_status,  # POPRAWIONE: sync_status zamiast status
                'items_processed': (sync.products_created or 0) + (sync.products_updated or 0),
                'duration_seconds': sync.sync_duration_seconds or 0
            }
            for sync in sync_history
        ]
    }


# Jedna mapa zamiast osobnej trasy na podzakładkę: whitelist i router siedzą
# w tym samym miejscu, więc nowa podzakładka to jedna linia, a nieznany slug
# z URL-a nie ma jak dojechać do render_template.
_PODZAKLADKI = {
    # Przegląd PIERWSZY, bo jest domyślny. Sama kolejność w tym słowniku nie
    # wystarcza — o domyślnej podzakładce decyduje PODZAKLADKA_DOMYSLNA
    # w reports-tab-content.html, a lista PODZAKLADKI tam musi zgadzać się
    # z kluczami tutaj (nazwa spoza tej mapy dostaje 404, nazwa brakująca tam
    # jest nieosiągalna z paska).
    'przeglad': (_kontekst_przeglad, 'components/reports/overview.html'),
    'stanowiska': (_kontekst_stanowiska, 'components/reports/stations.html'),
    'terminy': (_kontekst_terminy, 'components/reports/deadlines.html'),
    'ludzie': (_kontekst_ludzie, 'components/reports/workers.html'),
    'miks': (_kontekst_miks, 'components/reports/mix.html'),
    'system': (_kontekst_system, 'components/reports/system.html'),
}


@api_bp.route('/reports/sub/<nazwa>')
@login_required
def reports_subtab(nazwa):
    """
    Fragment HTML jednej podzakładki Raportów.

    Zwraca surowy text/html, nie kopertę JSON: markup widgetów jest renderowany
    w Jinja (tabele, legendy, dane przez |tojson), a skrypty i tak muszą jechać
    razem z nim — koperta niczego by nie uprościła, a doklejała martwe kilobajty.
    Błąd jednej podzakładki kończy się jej własnym komunikatem, a nie wywaloną
    całą zakładką (ten sam wzorzec co workers_tab_content).
    """
    wpis = _PODZAKLADKI.get(nazwa)
    if wpis is None:
        return (
            '<div class="alert alert-warning">Nieznana podzakładka raportów.</div>',
            404,
        )

    buduj_kontekst, szablon = wpis
    try:
        return render_template(szablon, **buduj_kontekst())
    except Exception as e:
        logger.error("Błąd podzakładki raportów", extra={
            'user_id': current_user.id,
            'podzakladka': nazwa,
            'error': str(e),
        })
        # STAŁY komunikat, bez treści wyjątku. Front wstawia to ciało przez
        # `panel.innerHTML = await odp.text()` BEZWARUNKOWO (komentarz w kodzie:
        # „treść wstawiamy zawsze"), więc f-string z {e} był niezabezpieczonym
        # wstrzyknięciem do DOM: odtworzone realnym żądaniem — wyjątek
        # RuntimeError('<img src=x onerror=alert(1)>') wracał HTTP 500 z tym
        # tagiem dosłownie w ciele, a innerHTML nie wykonuje <script>, ale
        # onerror na <img> odpala się normalnie. To było jedyne miejsce
        # w przepływie Raportów łamiące zasadę „escapuj wszystko z bazy".
        return (
            '<div class="alert alert-danger">Nie udało się wczytać podzakładki. '
            'Szczegóły w logach serwera.</div>',
            500,
        )
