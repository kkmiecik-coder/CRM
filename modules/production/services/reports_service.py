# modules/production/services/reports_service.py
"""
Agregaty wykresów zakładki Raporty.

Osiem wykresów, jeden moduł — bo wszystkie odpowiadają na warianty tego samego
pytania („czy hala nadąża i gdzie się korkuje") i muszą liczyć TAK SAMO. Każdy
z nich rozsypany po własnym routerze skończyłby się tym, czym już raz się
skończył: dwa widgety obok siebie pokazywały dwie różne odpowiedzi na to samo
pytanie i nikt nie umiał wytłumaczyć różnicy.

ZASADY, KTÓRYCH TU NIE WOLNO RUSZYĆ
===================================

1. Filtr `source NOT IN ('auto_skip','system')` jest OBOWIĄZKOWY wszędzie tam,
   gdzie liczymy PRACĘ CZŁOWIEKA. Eventy auto_skip/system powstają
   strukturalnie w complete_task(): produkt „surowe" bez obróbki krawędzi
   pomija wykańczanie, cut_to_size=False pomija formatowanie. Nikt ich fizycznie
   nie wykonał. Filtr jest wspólny ze station_events_service i
   worker_stats_service (stąd import, a nie własna krotka).

   Dwa wykresy filtru NIE stosują i to jest świadome, nie przeoczenie:
     - „Termin vs postęp" (termin_vs_postep) w ogóle nie czyta
       prod_station_events — liczy stan pozycji z current_status/deadline_date,
       więc nie ma do czego filtru przyczepić;
     - „Dorobki" (rejestracja_dorobek) czyta prod_rework_log, który nie ma
       kolumny source i nie ma automatycznego pisarza — ale MIANOWNIK tego
       wykresu (sztuki sformatowane) filtr ma, bo to już eventy.

2. Wszystko liczymy w strefie lokalnej przez get_local_now(). Kontenery chodzą
   na UTC: zmierzone get_local_now()=2026-08-12 00:18 przy date.today()=
   2026-08-11. Między północą a 02:00 CURDATE()/date.today() gubi cały dzień,
   a koszyki terminów przeskakują o jeden.

3. Serwis nie zna Flaska, requestów ani HTML-a. Zwraca gołe słowniki i listy;
   formatowanie, kolory i etykiety osi robi front. Jedyny wyjątek to nazwy
   stanowisk — te idą przez station_catalog.station_label(), żeby panel mówił
   tym samym językiem co monitory na hali.

4. Dialekt SQL: testy chodzą na SQLite, produkcja na MySQL. Dlatego NIE ma tu
   ani DAYOFWEEK/HOUR, ani WEEKDAY, ani TIMESTAMPDIFF, ani rekursywnych CTE.
   Kubełkowanie po godzinie i dniu tygodnia oraz oś kalendarzowa liczą się
   w Pythonie — wolumeny są rzędu tysięcy wierszy, a przenośność jest warta
   więcej niż te kilka milisekund.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import case, distinct, func

from extensions import db
from modules.logging import get_structured_logger

from ..models import (
    ProductionOrder, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession, get_local_now,
)
from .station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS, station_label,
)
from .station_events_service import ZRODLA_AUTOMATU
from .worker_stats_service import (
    ZakresError, granice_zakresu, minuty_sesji, praca_nieprzypisana,
    zaokr_wklad,
)

logger = get_structured_logger('production.reports')


# ── Wykres 1: okno dni roboczych ────────────────────────────────────────────
# „Dzień roboczy" liczymy Z DANYCH, nie z kalendarza — reguła kalendarzowa nie
# umie obsłużyć świąt ani zmiany rytmu hali, a przy tym wpuszcza do mianownika
# soboty serwisowe. 2026-08-01 (sobota) miała 0.043 m³ przy średniej ~4 m³:
# bez progu taka doba nie tylko zaniża średnią o ~7%, ale WYPYCHA z okna jeden
# realny dzień roboczy.
PROG_DNIA_ROBOCZEGO = 0.05      # 5% średniej dobowej
OKNO_SREDNIEJ_DNI = 60          # z ilu ostatnich dób liczymy tę średnią
OKNO_DNI_ROBOCZYCH = 14         # ile dni roboczych wchodzi do mianownika

# ── Dolna granica dla agregatów „ostatnie N dni produkcyjnych" ───────────────
# Oba agregaty, które szukają OSTATNICH dni z pracą (dni_robocze_hali,
# stan_nauki), pytały o nie przez `created_at <= koniec` + GROUP BY date()
# + LIMIT — bez dolnej granicy, czyli skanem całej historii. To jedyne dwa
# agregaty zakładki rosnące z WIEKIEM instalacji, a nie z wybranym zakresem:
# zmierzone na kopii powiększonej 5× (92 605 eventów, historia od 2025-03)
# lista dni produkcyjnych szła 4.12 → 20.27 ms, a dni_robocze_hali
# 12.80 → 60.92 ms, podczas gdy heatmapa 90-dniowa stała na 47 ms.
# Z dolną granicą 60 dni te same zapytania na tej samej kopii: 7.46 i 12.42 ms,
# nadal z kompletem 14 dni.
#
# Mnożnik, nie stała: okno musi pomieścić `limit` dni ROBOCZYCH, a hala pracuje
# pn-pt, więc kalendarzowo trzeba ich ok. 1,5×. Przy dłuższym postoju wyjdzie
# mniej dni niż limit — wtedy _dni_z_praca() sam rozszerza okno (patrz niżej),
# bo zawężenie nie ma prawa zmienić WYNIKU, tylko koszt.
MNOZNIK_OKNA_SKANU = 4

# ── Wykres 2: koszyki terminu ───────────────────────────────────────────────
# Stała kolejność i stały skład — oś jest SKALĄ PILNOŚCI, nie listą kategorii
# wyciągniętą z danych. Gdyby puste koszyki wypadały, przy dobrej robocie oś
# miałaby dwa słupki, przy złej sześć, i nie dałoby się porównać dwóch dni.
KOSZYKI_TERMINU = (
    'po_terminie', 'dzis', '1_2_dni', '3_7_dni', '8_dni_plus', 'bez_terminu',
)
ETYKIETY_KOSZYKOW = {
    'po_terminie': 'Po terminie',
    'dzis': 'Dziś',
    '1_2_dni': '1-2 dni',
    '3_7_dni': '3-7 dni',
    '8_dni_plus': '8+ dni',
    'bez_terminu': 'Bez terminu',
}

# Praca skończona albo odwołana wypada — wykres pokazuje stan bieżący, nie
# historię. Zmierzone: bez tego filtra słupek „Po terminie" pokazuje 83.7 m³
# zamiast 0.889, bo 2133 spakowanych pozycji ma termin w przeszłości.
STATUSY_ZAMKNIETE = ('spakowane', 'anulowane')

# Etapy w toku, które nie są stanowiskiem. To nazwy STATUSÓW, nie stanowisk,
# więc station_catalog ich nie dotyczy i nic się nie rozjeżdża.
ETAPY_POZA_STANOWISKAMI = {
    'czeka_na_logistyke': 'Logistyka',
    'wstrzymane': 'Wstrzymane',
    'w_realizacji': 'W realizacji',
}

# Ile pozycji jedzie w payloadzie wykresu 2 do drill-downu. 161 pozycji w toku
# ≈ 32 kB; przy ~580 produktach/miesiąc i 2-3-tygodniowym oknie realizacji
# szczyt to 300-400 pozycji, więc 500 wystarcza z zapasem. Po przekroczeniu
# lecimy z flagą items_truncated, a nie po cichu.
LIMIT_POZYCJI_TERMINOW = 500

# ── Wykres 3: kiedy agregować tygodniowo ────────────────────────────────────
# 90 słupków × 2 serie jest jeszcze czytelne; 365 zlewa się w kaszę. Powyżej
# tego progu serwer oddaje ten sam kształt JSON, tylko date = poniedziałek.
PROG_AGREGACJI_TYGODNIOWEJ_DNI = 120

# ── Wykres 6: mała próbka ───────────────────────────────────────────────────
# Dzień z 2-3 eventami daje skoki 0%/100%, które nie znaczą nic. Front rysuje
# taki punkt pusty w środku i dopisuje „mała próbka" — próg zostaje tutaj,
# żeby XLSX i widget mówiły to samo.
PROG_MALEJ_PROBKI = 10

# ── Wykres 7: kiedy panel ustępuje miejsca wykresowi ────────────────────────
# Dziś w całej bazie jest 6 zgłoszeń doróbek z 15 tygodni (9 tygodni pustych),
# bo zgłaszać można TYLKO z formatowania (rework_service.VALID_REJECT_STATIONS).
# Słupek „prawie zero doróbek" czyta się jako „jakość świetna", a znaczy „sześć
# stanowisk nie ma jak zgłosić". Wykres włącza się sam, gdy dane go uniosą.
PROG_DOROBEK_WPISOW = 12
PROG_DOROBEK_TYGODNI = 4

ETYKIETY_POWODOW_DOROBEK = {
    'wymiary': 'Wymiary',
    'jakosc_sklejenia': 'Jakość sklejenia',
    'jakosc_produktu': 'Jakość produktu',
    'inne': 'Inne',
}


def _zaokr(wartosc, miejsca=3):
    return round(float(wartosc or 0), miejsca)


def _na_date(wartosc):
    """
    Wynik func.date() to obiekt date w MySQL i tekst w SQLite. Jedna funkcja
    zamiast dwóch gałęzi rozsianych po module.
    """
    if wartosc is None:
        return None
    if isinstance(wartosc, datetime):
        return wartosc.date()
    if isinstance(wartosc, date):
        return wartosc
    return datetime.strptime(str(wartosc)[:10], '%Y-%m-%d').date()


def _os_dni(start_date, end_date):
    """Pełna, ciągła oś dni [start, end] — także tych bez ani jednego wiersza."""
    dni = []
    biezacy = start_date
    while biezacy <= end_date:
        dni.append(biezacy)
        biezacy += timedelta(days=1)
    return dni


def _filtry_eventow_pracy(poczatek, koniec, station=None):
    """Wspólny zestaw filtrów „to zrobił człowiek, w tym oknie"."""
    filtry = [
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ]
    if station and station != 'all':
        filtry.append(ProductionStationEvent.station_code == station)
    return filtry


def _kolejnosc_stanowisk(kod):
    """Klucz sortowania: najpierw kolejność procesu, potem reszta alfabetycznie."""
    try:
        return (0, STATION_ORDER.index(kod))
    except ValueError:
        return (1, 0)


def _ostatnie_doby(buduj_zapytanie, koniec_daty, limit):
    """
    Ostatnie `limit` dób z jakąkolwiek pracą — bez skanowania całej historii.

    `buduj_zapytanie(dolna_granica_albo_None)` ma oddać najwyżej `limit`
    wierszy, posortowanych po dobie malejąco. Wołamy je najpierw z wąskim
    oknem, a gdy okno nie dowiozło kompletu (świeża baza, długi postój,
    hala stojąca dłużej niż MNOZNIK_OKNA_SKANU × limit dni) — jeszcze raz bez
    granicy. Zawężenie nie ma prawa zmienić WYNIKU, tylko koszt, i ten fallback
    jest jedyną gwarancją, że tak zostaje.
    """
    wiersze = buduj_zapytanie(
        koniec_daty - timedelta(days=limit * MNOZNIK_OKNA_SKANU))
    if len(wiersze) < limit:
        wiersze = buduj_zapytanie(None)
    return wiersze


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 1 — Dni zapasu przed stanowiskiem
# ════════════════════════════════════════════════════════════════════════════

def dni_robocze_hali(end_date=None, ile_dni=OKNO_DNI_ROBOCZYCH,
                     okno_sredniej=OKNO_SREDNIEJ_DNI):
    """
    Ostatnie `ile_dni` dób, w których hala FAKTYCZNIE pracowała, licząc wstecz
    od end_date włącznie. Zwraca listę dat rosnąco (może być krótsza niż
    ile_dni, a na pustej bazie pusta).

    Dzień roboczy = doba, w której przerób sięgnął co najmniej
    PROG_DNIA_ROBOCZEGO średniej dobowej z ostatnich `okno_sredniej` dób
    z jakąkolwiek pracą.
    """
    end_date = end_date or get_local_now().date()
    koniec = datetime.combine(end_date, datetime.max.time())

    dzien = func.date(ProductionStationEvent.created_at).label('dzien')

    def zapytaj(dolna_granica):
        filtry = [
            ProductionStationEvent.created_at <= koniec,
            ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if dolna_granica is not None:
            filtry.append(ProductionStationEvent.created_at
                          >= datetime.combine(dolna_granica, datetime.min.time()))
        return db.session.query(
            dzien,
            func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                     * ProductionStationEvent.delta).label('m3'),
        ).join(
            ProductionProduct,
            ProductionProduct.id == ProductionStationEvent.production_item_id,
        ).filter(*filtry).group_by(dzien).order_by(
            dzien.desc()).limit(okno_sredniej).all()

    wiersze = _ostatnie_doby(zapytaj, end_date, okno_sredniej)

    if not wiersze:
        return []

    metry = [float(w[1] or 0) for w in wiersze]
    # max(..., 0): przy oknie zdominowanym przez cofnięcia średnia potrafi wyjść
    # UJEMNA, a wtedy próg ujemny przepuszczałby doby, w których hala oddała
    # więcej niż zrobiła. Warunek `m3 > 0` domyka to samo od drugiej strony:
    # doba o zerowym przerobie netto nie jest dniem roboczym w sensie tempa.
    prog = max((sum(metry) / len(metry)) * PROG_DNIA_ROBOCZEGO, 0.0)

    robocze = [_na_date(d) for d, m3 in wiersze
               if float(m3 or 0) > 0 and float(m3 or 0) >= prog]
    return sorted(robocze[:ile_dni])


def dni_zapasu_stanowisk(end_date=None, okno_dni=OKNO_DNI_ROBOCZYCH):
    """
    Ile dni roboczych zajmie wypalenie kolejki stojącej przed stanowiskiem
    przy jego ostatnim tempie.

    LICZNIK i MIANOWNIK MIERZĄ RÓŻNE RZECZY i to jest świadome (tak liczy też
    dashboard): pending_m3 to STAN BIEŻĄCY z current_status — pozycja czeka
    jako całość, z pełnym quantity, nawet jeśli jest w połowie zrobiona.
    Przerób to NETTO EVENTÓW, sztuka po sztuce. Licznik jest więc zawyżony
    i front musi to napisać w tooltipie.

    reason:
      None            — policzone normalnie,
      'brak_przerobu' — stanowisko nic nie zrobiło w oknie, a kolejka stoi;
                        days_of_supply = None (NIE dzielimy przez zero i NIE
                        rysujemy nieskończoności — to najgorszy możliwy stan,
                        więc idzie na górę wykresu),
      'pusto'         — ani pracy, ani kolejki; days_of_supply = 0.0 i słupek
                        zerowej długości na dole. Stanowisko bez roboty i bez
                        kolejki nie jest wąskim gardłem.
    """
    end_date = end_date or get_local_now().date()
    dni = dni_robocze_hali(end_date, okno_dni)

    if not dni:
        # Świeża baza albo długa przerwa — nie ma z czego policzyć tempa.
        # Front pisze „Za mało danych, żeby policzyć tempo".
        return {'stations': [], 'okno_dni': 0, 'okno_od': None, 'okno_do': None}

    dni_iso = [d.isoformat() for d in dni]

    # Kolejki: jeden GROUP BY zamiast siedmiu skalarów. Definicja 1:1 jak
    # w dashboardzie (SUM(volume_m3 * quantity) po current_status), a mapa
    # statusów jest wspólna — patrz station_catalog.STATION_PENDING_STATUS.
    kolejki = dict(db.session.query(
        ProductionProduct.current_status,
        func.coalesce(func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                               * ProductionProduct.quantity), 0),
    ).filter(
        ProductionProduct.current_status.in_(list(STATION_PENDING_STATUS.values()))
    ).group_by(ProductionProduct.current_status).all())

    # Przerób w oknie. Filtr źródła OBOWIĄZKOWY: bez niego formatowanie
    # dostaje kredyt za 170 eventów auto_skip i 1503 system, mianownik rośnie
    # i dni zapasu spadają sztucznie — akurat na stanowisku z drugą co do
    # wielkości kolejką.
    przerob = dict(db.session.query(
        ProductionStationEvent.station_code,
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta),
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        func.date(ProductionStationEvent.created_at).in_(dni_iso),
    ).group_by(ProductionStationEvent.station_code).all())

    stanowiska = []
    for kod, status_kolejki in STATION_PENDING_STATUS.items():
        kolejka_m3 = float(kolejki.get(status_kolejki, 0) or 0)
        okno_m3 = float(przerob.get(kod, 0) or 0)
        srednia = okno_m3 / len(dni)

        # `<= 0`, nie `== 0`: w bazie jest 587 cofnięć na -985 sztuk, więc przy
        # wąskim oknie mianownik potrafi wyjść ujemny. Ujemne dni zapasu nie
        # znaczą nic — taka gałąź ma iść w „brak przerobu".
        if okno_m3 <= 0:
            powod = 'brak_przerobu' if kolejka_m3 > 0 else 'pusto'
            dni_zapasu = None if powod == 'brak_przerobu' else 0.0
        else:
            powod = None
            dni_zapasu = round(kolejka_m3 / srednia, 2)

        stanowiska.append({
            'station_code': kod,
            'station_label': station_label(kod),
            'pending_m3': _zaokr(kolejka_m3),
            'avg_daily_m3': _zaokr(srednia, 4),
            'window_m3': _zaokr(okno_m3),
            'days_of_supply': dni_zapasu,
            'reason': powod,
        })

    kolejnosc_powodu = {'brak_przerobu': 0, None: 1, 'pusto': 2}
    stanowiska.sort(key=lambda s: (kolejnosc_powodu[s['reason']],
                                   -(s['days_of_supply'] or 0)))

    return {
        'stations': stanowiska,
        'okno_dni': len(dni),
        'okno_od': dni[0].isoformat(),
        'okno_do': dni[-1].isoformat(),
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 2 — Termin vs postęp
# ════════════════════════════════════════════════════════════════════════════

def _koszyk_terminu(deadline, dzis):
    """
    JEDNA definicja koszyka — używa jej i agregat, i lista do drill-downu.
    Dwie kopie (jedna w SQL, druga w Pythonie) prędzej czy później rozjadą się
    na granicy „dziś".
    """
    if deadline is None:
        return 'bez_terminu'
    if deadline < dzis:
        return 'po_terminie'
    if deadline == dzis:
        return 'dzis'
    if deadline <= dzis + timedelta(days=2):
        return '1_2_dni'
    if deadline <= dzis + timedelta(days=7):
        return '3_7_dni'
    return '8_dni_plus'


def _segment_pozycji(status):
    """status → (kod segmentu, etykieta). Stanowisko ma pierwszeństwo."""
    from .mobile_api_service import STATUS_TO_STATION

    stanowisko = STATUS_TO_STATION.get(status)
    if stanowisko:
        return stanowisko, station_label(stanowisko)
    return status, ETAPY_POZA_STANOWISKAMI.get(status, status)


def termin_vs_postep(limit_pozycji=LIMIT_POZYCJI_TERMINOW):
    """
    Migawka: ile m³ stoi w którym koszyku terminu i na jakim stanowisku.

    Bez zakresu dat — w odróżnieniu od pozostałych widgetów raportów to jest
    STAN NA TERAZ, nie historia.

    Trzy rzeczy, które łatwo tu zrobić źle:
      1. `dzis` MUSI pochodzić z get_local_now() (Europe/Warsaw). Kontener
         chodzi na UTC, więc CURDATE() między 22:00 a północą daje inny dzień —
         zmierzone: koszyk 1-2 dni 4 poz./0.104 m³ lokalnie vs 2 poz./0.036 m³
         po CURDATE().
      2. NIE używać kolumny days_until_deadline — liczy się raz przy syncu
         i wietrzeje. Zmierzone: pozycja z zapisanym 14 ma faktycznie -98 dni.
      3. Mapa statusów to STATUS_TO_STATION z mobile_api_service (7 stanowisk),
         a nie sześciostanowiskowy zestaw dashboardu — ten drugi wyciąłby
         lakiernię (49% słupka 3-7 dni) i logistykę (89% słupka „Po terminie").

    Filtru source NOT IN ('auto_skip','system') tu nie ma i nie ma go do czego
    przyczepić: wykres nie czyta prod_station_events ani razu.
    """
    dzis = get_local_now().date()

    # GROUP BY po (status, deadline_date), a nie po gotowym koszyku: dat jest
    # kilkadziesiąt, więc wynik i tak jest mały, a koszyk liczy JEDNA funkcja
    # w Pythonie — ta sama, którą dostaje lista pozycji niżej.
    wiersze = db.session.query(
        ProductionProduct.current_status,
        ProductionProduct.deadline_date,
        func.count(ProductionProduct.id),
        func.sum(ProductionProduct.quantity),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionProduct.quantity),
    ).filter(
        ProductionProduct.current_status.isnot(None),
        ProductionProduct.current_status.notin_(STATUSY_ZAMKNIETE),
    ).group_by(
        ProductionProduct.current_status,
        ProductionProduct.deadline_date,
    ).all()

    indeks_koszyka = {kod: i for i, kod in enumerate(KOSZYKI_TERMINU)}
    segmenty = {}
    sumy_m3 = [0.0] * len(KOSZYKI_TERMINU)
    sumy_poz = [0] * len(KOSZYKI_TERMINU)

    for status, deadline, pozycji, sztuk, metry in wiersze:
        idx = indeks_koszyka[_koszyk_terminu(_na_date(deadline), dzis)]
        kod, etykieta = _segment_pozycji(status)
        wpis = segmenty.setdefault(kod, {
            'code': kod,
            'label': etykieta,
            'm3': [0.0] * len(KOSZYKI_TERMINU),
            'items': [0] * len(KOSZYKI_TERMINU),
            'pieces': [0] * len(KOSZYKI_TERMINU),
        })
        wpis['m3'][idx] += float(metry or 0)
        wpis['items'][idx] += int(pozycji or 0)
        wpis['pieces'][idx] += int(sztuk or 0)
        sumy_m3[idx] += float(metry or 0)
        sumy_poz[idx] += int(pozycji or 0)

    datasety = sorted(segmenty.values(),
                      key=lambda d: _kolejnosc_stanowisk(d['code']))
    for wpis in datasety:
        wpis['m3'] = [_zaokr(v) for v in wpis['m3']]

    # Lista do klikania w segment. Jedzie w tej samej odpowiedzi, bo klik ma
    # filtrować tabelę bez drugiego requestu. Sortowanie: najpilniejsze u góry,
    # pozycje bez terminu na końcu.
    pozycje = []
    zapytanie = db.session.query(ProductionProduct, ProductionOrder).join(
        ProductionOrder, ProductionOrder.id == ProductionProduct.order_id
    ).filter(
        ProductionProduct.current_status.isnot(None),
        ProductionProduct.current_status.notin_(STATUSY_ZAMKNIETE),
    ).order_by(
        ProductionProduct.deadline_date.is_(None),
        ProductionProduct.deadline_date,
        ProductionProduct.priority_rank,
    ).limit(limit_pozycji + 1)

    surowe = zapytanie.all()
    przyciete = len(surowe) > limit_pozycji
    for produkt, zamowienie in surowe[:limit_pozycji]:
        deadline = _na_date(produkt.deadline_date)
        kod, etykieta = _segment_pozycji(produkt.current_status)
        pozycje.append({
            'product_id': produkt.id,
            'short_product_id': produkt.short_product_id,
            'internal_order_number': zamowienie.internal_order_number if zamowienie else None,
            'baselinker_order_id': zamowienie.baselinker_order_id if zamowienie else None,
            'client': zamowienie.client_name if zamowienie else None,
            'status': produkt.current_status,
            'station_code': kod,
            'station_label': etykieta,
            'bucket': _koszyk_terminu(deadline, dzis),
            'deadline': deadline.isoformat() if deadline else None,
            'days': (deadline - dzis).days if deadline else None,
            'quantity': produkt.quantity,
            'm3': _zaokr(float(produkt.volume_m3 or 0) * (produkt.quantity or 0), 4),
            'is_priority': bool(produkt.is_priority),
        })

    return {
        'as_of': dzis.isoformat(),
        'buckets': list(KOSZYKI_TERMINU),
        'bucket_labels': [ETYKIETY_KOSZYKOW[k] for k in KOSZYKI_TERMINU],
        'datasets': datasety,
        'totals': {
            'm3': [_zaokr(v) for v in sumy_m3],
            'items': sumy_poz,
            'm3_total': _zaokr(sum(sumy_m3)),
            'items_total': sum(sumy_poz),
        },
        'items': pozycje,
        'items_truncated': przyciete,
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 3 — Wejście vs wyjście hali
# ════════════════════════════════════════════════════════════════════════════

def wejscie_vs_wyjscie(start_date, end_date, agregacja='auto'):
    """
    Ile m³ dziennie wchodzi do produkcji (nowe pozycje) i ile wychodzi
    (pakowanie), plus skumulowana różnica.

    WEEKENDÓW NIE WOLNO WYCIĄĆ — odwrotnie niż przy wykresach 1 i 4. Hala
    pracuje pn-pt (sobota 12 eventów, niedziela 1 w całej historii), ale
    zamówienia wpadają też w weekend: 2026-08-09, niedziela, 0.367 m³ wejścia
    przy zerowym wyjściu. Wycięcie weekendów skasowałoby realny napływ i wykres
    skłamałby w stronę „nadążamy". Oś jest 7-dniowa.

    LINIA SKUMULOWANA MIERZY DRYF W OKNIE, NIE WIP: startuje od zera w pierwszym
    dniu zakresu, więc +2.5 m³ znaczy „w tych 90 dniach weszło o 2.5 m³ więcej
    niż wyszło", a nie „w hali leży 2.5 m³" (to jest ~6.2 m³ z kolejek).

    Pozycje anulowane wypadają po stronie wejścia — anulowany produkt nigdy nie
    przejdzie przez pakowanie, więc trzymanie go trwale zawyżałoby linię.
    Koszt tej decyzji: słupek historyczny zmienia się wstecz w dniu, w którym
    ktoś anuluje stare zamówienie. To wybór, nie oczywistość.

    Strefa czasowa: prod_products.created_at i prod_station_events.created_at
    zapisuje ten sam get_local_now(), więc obie strony wykresu mają tę samą
    granicę doby. Gdyby kiedyś jedna strona przeszła na UTC, wykres rozjechałby
    się o dwie godziny na granicy doby i nikt by tego nie zauważył.
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    # Historia produktów zaczyna się 2026-04-08 — dla dłuższych zakresów oś
    # pokazywałaby setki pustych dni udających „hala nic nie robiła". Zamiast
    # badge'a: przycięcie okna i jawny zakres w nagłówku.
    najstarszy = db.session.query(func.min(ProductionProduct.created_at)).scalar()
    najstarszy = _na_date(najstarszy)
    przyciete = False
    # `najstarszy <= end_date` chroni przed odwróceniem osi: zakres w całości
    # sprzed pierwszego produktu ma zwrócić PEŁNĄ oś zer („brak ruchu"), a nie
    # pustą listę dni, bo pusta lista wygląda u frontu jak awaria zapytania.
    if najstarszy and start_date < najstarszy <= end_date:
        start_date = najstarszy
        poczatek = datetime.combine(start_date, datetime.min.time())
        przyciete = True

    dzien_wejscia = func.date(ProductionProduct.created_at).label('dzien')
    weszlo = {
        _na_date(d): float(m3 or 0)
        for d, m3 in db.session.query(
            dzien_wejscia,
            func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                     * ProductionProduct.quantity),
        ).filter(
            ProductionProduct.created_at >= poczatek,
            ProductionProduct.created_at <= koniec,
            func.coalesce(ProductionProduct.current_status, '') != 'anulowane',
        ).group_by(dzien_wejscia).all()
    }

    dzien_wyjscia = func.date(ProductionStationEvent.created_at).label('dzien')
    wyszlo = {
        _na_date(d): float(m3 or 0)
        for d, m3 in db.session.query(
            dzien_wyjscia,
            func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                     * ProductionStationEvent.delta),
        ).join(
            ProductionProduct,
            ProductionProduct.id == ProductionStationEvent.production_item_id,
        ).filter(
            *_filtry_eventow_pracy(poczatek, koniec, 'packaging')
        ).group_by(dzien_wyjscia).all()
    }

    # Oś kalendarzowa i kumulacja w Pythonie: pełna oś musi zawierać dni bez
    # ANI JEDNEGO wiersza po obu stronach, więc kalendarz i tak trzeba
    # wygenerować, a rekursywne CTE w MySQL nie przejdzie testów na SQLite.
    dni = _os_dni(start_date, end_date)
    tygodniowo = (agregacja == 'tydzien' or
                  (agregacja == 'auto' and len(dni) > PROG_AGREGACJI_TYGODNIOWEJ_DNI))

    punkty = []
    kumulacja = 0.0
    for d in dni:
        we = weszlo.get(d, 0.0)
        wy = wyszlo.get(d, 0.0)
        kumulacja += we - wy
        punkty.append({'date': d, 'in_m3': we, 'out_m3': wy, 'cum': kumulacja})

    if tygodniowo:
        zgrupowane = {}
        for p in punkty:
            poniedzialek = p['date'] - timedelta(days=p['date'].weekday())
            wpis = zgrupowane.setdefault(poniedzialek, {
                'date': poniedzialek, 'in_m3': 0.0, 'out_m3': 0.0, 'cum': 0.0})
            wpis['in_m3'] += p['in_m3']
            wpis['out_m3'] += p['out_m3']
            wpis['cum'] = p['cum']   # stan na koniec tygodnia
        punkty = [zgrupowane[k] for k in sorted(zgrupowane)]

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'granularity': 'tydzien' if tygodniowo else 'dzien',
        'range_trimmed': przyciete,
        'first_product_date': najstarszy.isoformat() if najstarszy else None,
        'days': [
            {
                'date': p['date'].isoformat(),
                'in_m3': _zaokr(p['in_m3']),
                'out_m3': _zaokr(p['out_m3']),
                'cumulative_diff_m3': _zaokr(p['cum']),
            }
            for p in punkty
        ],
        'total_in_m3': _zaokr(sum(weszlo.values())),
        'total_out_m3': _zaokr(sum(wyszlo.values())),
        'cumulative_end_m3': _zaokr(punkty[-1]['cum'] if punkty else 0.0),
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 4 — Kiedy hala realnie pracuje (godzina × dzień tygodnia)
# ════════════════════════════════════════════════════════════════════════════

def heatmapa_godzinowa(start_date, end_date):
    """
    Siatka 7 × 24 (wiersz 0 = poniedziałek), wartość = ŚREDNIE m³ na jedno
    wystąpienie danego dnia tygodnia w oknie.

    NORMALIZACJA JEST OBOWIĄZKOWA. Okno 30-dniowe 2026-07-13..2026-08-11 ma
    pięć poniedziałków i pięć wtorków, a po cztery pozostałe dni — surowe sumy
    zawyżałyby początek tygodnia o 25% i heatmapa skłamałaby dokładnie o tym,
    o co się ją pyta. Dzielnik bierzemy z KALENDARZA okna (ile razy poniedziałek
    wypadł), nie z danych: pytanie brzmi „ile średnio robimy w poniedziałek",
    więc poniedziałek bez pracy MUSI wejść do mianownika jako zero.

    24 KOLUMNY, NIE „TYLKO GODZINY PRACY". „W nocy nic się nie dzieje" to
    ODPOWIEDŹ tego widgetu, a nie puste miejsce do zaoszczędzenia.

    Kubełkowanie robimy w Pythonie, bo DAYOFWEEK/HOUR nie istnieją w SQLite,
    a EXTRACT(dow) nie istnieje w MySQL — jedno przejście po eventach zakresu
    jest przenośne i przy 18 tys. wierszy całej historii kosztuje kilkanaście ms.
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    wiersze = db.session.query(
        ProductionStationEvent.created_at,
        (func.coalesce(ProductionProduct.volume_m3, 0)
         * ProductionStationEvent.delta).label('m3'),
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(*_filtry_eventow_pracy(poczatek, koniec)).all()

    siatka_m3 = [[0.0] * 24 for _ in range(7)]
    siatka_ev = [[0] * 24 for _ in range(7)]
    for utworzono, m3 in wiersze:
        chwila = utworzono if isinstance(utworzono, datetime) else \
            datetime.strptime(str(utworzono)[:19], '%Y-%m-%d %H:%M:%S')
        siatka_m3[chwila.weekday()][chwila.hour] += float(m3 or 0)
        siatka_ev[chwila.weekday()][chwila.hour] += 1

    # Ile razy każdy dzień tygodnia wypadł w oknie — mianownik normalizacji.
    wystapienia = [0] * 7
    for d in _os_dni(start_date, end_date):
        wystapienia[d.weekday()] += 1

    maks = 0.0
    ujemne = False
    for wiersz_idx in range(7):
        dzielnik = wystapienia[wiersz_idx] or 1
        for godzina in range(24):
            wartosc = siatka_m3[wiersz_idx][godzina] / dzielnik
            siatka_m3[wiersz_idx][godzina] = round(wartosc, 4)
            if wartosc < 0:
                ujemne = True
            maks = max(maks, abs(wartosc))

    return {
        'range_from': start_date.isoformat(),
        'range_to': end_date.isoformat(),
        'grid_m3': siatka_m3,
        'grid_events': siatka_ev,
        'weekday_occurrences': wystapienia,
        # Skala kolorów liczona z WARTOŚCI BEZWZGLĘDNYCH: w bazie są komórki
        # ujemne (cofnięcia). Wersja z max(v) dałaby komórce ujemnej ten sam
        # kolor co zerowej i cofnięcia stałyby się niewidoczne.
        'max_abs_m3': round(maks, 4),
        'has_negative': ujemne,
        'events_total': len(wiersze),
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 5 — Obsada vs przerób per stanowisko
# ════════════════════════════════════════════════════════════════════════════

def obsada_vs_przerob(start_date, end_date):
    """
    Osobogodziny (z sesji pracy) zestawione z przerobem (z eventów), plus
    iloraz m³ na osobogodzinę.

    NIE PORÓWNUJ STANOWISK MIĘDZY SOBĄ w trybie m³/h. Zmierzone: cutting 0.021
    vs gluing 0.224 — dziesięciokrotna różnica, która nie mówi nic o ludziach,
    bo m³ nie są porównywalne między stanowiskami (spakowanie metra trwa minuty,
    sklejenie godziny). To ten sam powód, dla którego tabela wydajności jest
    sortowana po nazwisku, a nie po m³.

    in_pipeline=False dostaje trakownia: sesja tam być może, ale
    prod_station_events tego kodu nie zna (to rejestr surowca), więc wyszłoby
    „8 h / 0 m³" czytane jako bezczynność. Tempa dla takich wierszy nie liczymy.

    TEMPO LICZY SIĘ Z DÓB, KTÓRE MAJĄ SESJE — nie z całego zakresu. Licznik
    brany z całego okna przy mianowniku istniejącym tylko dla części dób dawał
    wskaźnik rosnący razem z zakresem zamiast się stabilizować: zmierzone
    2026-08-12 na sklejaniu 0.056 (Dziś) → 0.614 (7 dni) → 2.898 m³/h (30 dni),
    czyli 52× dla tego samego stanowiska, przy osobogodzinach stojących
    w miejscu (24.5 / 24.6 / 24.6 h — wszystkie 14 sesji jest z dziś).
    Wiersz niesie `days_with_sessions` i `days_in_range`, żeby front mógł
    napisać, z ilu dni ta liczba pochodzi; `m3` i `pieces` zostają liczone
    z CAŁEGO zakresu, bo to one rysują słupek i muszą zgadzać się z resztą
    zakładki.
    """
    from .worker_service import get_night_cutoff, get_idle_timeout_minutes

    poczatek, koniec = granice_zakresu(start_date, end_date)
    dni_zakresu = (end_date - start_date).days + 1

    teraz = get_local_now()
    cutoff = get_night_cutoff()
    idle_minut = get_idle_timeout_minutes()
    minuty = {}
    otwarte = {}
    doby_sesji = {}
    for sesja in ProductionWorkerSession.query.filter(
            ProductionWorkerSession.work_date >= start_date,
            ProductionWorkerSession.work_date <= end_date).all():
        minut = minuty_sesji(sesja, teraz, cutoff, idle_minut)
        minuty[sesja.station_code] = minuty.get(sesja.station_code, 0) + minut
        if minut:
            doby_sesji.setdefault(sesja.station_code, set()).add(
                sesja.work_date.isoformat())
        if sesja.ended_at is None:
            otwarte[sesja.station_code] = otwarte.get(sesja.station_code, 0) + 1

    # GROUP BY (stanowisko, doba), nie po samym stanowisku: z tego samego
    # przebiegu wychodzi i suma całego zakresu (słupek), i suma ograniczona do
    # dób z sesjami (mianownik tempa). Dwa zapytania dałyby dwie okazje do
    # rozjazdu filtrów.
    przerob = {}
    for kod, dzien, sztuki, metry, eventy in db.session.query(
            ProductionStationEvent.station_code,
            func.date(ProductionStationEvent.created_at),
            func.sum(ProductionStationEvent.delta),
            func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                     * ProductionStationEvent.delta),
            func.count(ProductionStationEvent.id),
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(
        *_filtry_eventow_pracy(poczatek, koniec)
    ).group_by(
        ProductionStationEvent.station_code,
        func.date(ProductionStationEvent.created_at),
    ).all():
        wpis = przerob.setdefault(kod, {'pieces': 0, 'm3': 0.0, 'events': 0,
                                        'per_dzien': {}})
        wpis['pieces'] += int(sztuki or 0)
        wpis['m3'] += float(metry or 0)
        wpis['events'] += int(eventy or 0)
        wpis['per_dzien'][_na_date(dzien).isoformat()] = float(metry or 0)

    # Suma kodów z obu stron: stanowisko z sesjami bez eventów I stanowisko
    # z eventami bez sesji muszą się pokazać — to dwa różne, ważne stany.
    kody = sorted(set(minuty) | set(przerob), key=_kolejnosc_stanowisk)

    wiersze = []
    for kod in kody:
        minut = minuty.get(kod, 0)
        godziny = minut / 60
        praca = przerob.get(kod) or {'pieces': 0, 'm3': 0.0, 'events': 0,
                                     'per_dzien': {}}
        w_pipeline = kod in STATION_ORDER
        doby = doby_sesji.get(kod, set())
        # Licznik tempa z tych samych dób, z których pochodzi mianownik.
        metry_w_dobach = sum(m for d, m in praca['per_dzien'].items() if d in doby)
        wiersze.append({
            'station_code': kod,
            'station_label': station_label(kod),
            'person_hours': round(godziny, 1),
            'person_minutes': minut,
            'pieces': praca['pieces'],
            'm3': _zaokr(praca['m3']),
            'station_events': praca['events'],
            'm3_per_person_hour': (round(metry_w_dobach / godziny, 3)
                                   if godziny and w_pipeline else None),
            'm3_in_session_days': _zaokr(metry_w_dobach),
            'days_with_sessions': len(doby),
            'days_in_range': dni_zakresu,
            'open_sessions': otwarte.get(kod, 0),
            'in_pipeline': w_pipeline,
        })

    # Sumy z MINUT, nie z zaokrąglonych godzin: siedem stanowisk × do 0.05 h
    # błędu dawało 234.6 zamiast 234.7 i kafelek kłócił się z tabelą.
    minut_razem = sum(minuty.values())
    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'days_in_range': dni_zakresu,
        'rows': wiersze,
        'summary': {
            'person_hours': round(minut_razem / 60, 1),
            'person_minutes': minut_razem,
            'm3': _zaokr(sum(w['m3'] for w in wiersze)),
            'pieces': sum(w['pieces'] for w in wiersze),
            'stations_with_hours': sum(1 for w in wiersze if w['person_minutes'] > 0),
            # Po LICZBIE ZDARZEŃ, nie po netto delt: doba, w której tyle samo
            # odhaczono, co cofnięto, ma netto 0 przy realnej pracy i kafelek
            # „0 / 0" udawał, że wszystko się zgadza.
            'stations_with_work': sum(1 for w in wiersze if w['station_events']),
            'station_events': sum(w['station_events'] for w in wiersze),
            'open_sessions': sum(otwarte.values()),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 6 — Pokrycie atrybucją w czasie
# ════════════════════════════════════════════════════════════════════════════

def pokrycie_atrybucji_dziennie(start_date, end_date, station=None):
    """
    Jaki procent zarejestrowanego RUCHU produkcyjnego ma podpis pracownika,
    dzień po dniu.

    DWIE DECYZJE, które trzymają ten wskaźnik w ryzach:

    1. MIANOWNIK NA ABS(delta) NA POZIOMIE EVENTU. Poprzednia ścieżka brała
       wartość bezwzględną dopiero z sumy netto per (dzień, stanowisko), więc
       cofnięcia kasowały się z dorobkami W MIANOWNIKU i pokrycie potrafiło
       przekroczyć 100%. Realny przykład: 2026-08-11, sklejanie bez atrybucji —
       netto +1 przy 39 sztukach ruchu i 11 eventach ujemnych. Przy ABS na
       evencie licznik jest podzbiorem mianownika, więc wynik jest zamknięty
       w 0-100% z definicji.
    2. KLASYFIKACJA PRZEZ EXISTS, NIE PRZEZ SUM(share). Shares sumują się dziś
       do 1.000000 dla każdego eventu, ale to niezmiennik zapisu, nie schematu —
       jeden błąd przy zapisie zespołowym dałby licznik większy od mianownika.
       EXISTS jest odporny z definicji i nie zbiera błędu zaokrągleń.

    Dzień bez produkcji dostaje coverage_pct = None (DZIURA w linii), a nie
    zero: płaska linia na zerze czyta się jak „pracowali i nikt się nie
    podpisał", a to nieprawda.
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    ma_atrybucje = db.session.query(ProductionStationEventWorker).filter(
        ProductionStationEventWorker.event_id == ProductionStationEvent.id
    ).exists()
    ruch = func.abs(ProductionStationEvent.delta)

    dzien = func.date(ProductionStationEvent.created_at).label('dzien')
    wiersze = db.session.query(
        dzien,
        func.sum(ruch),
        func.sum(case((ma_atrybucje, ruch), else_=0)),
        func.count(ProductionStationEvent.id),
        func.sum(case((ProductionStationEvent.delta < 0, 1), else_=0)),
    ).filter(
        *_filtry_eventow_pracy(poczatek, koniec, station)
    ).group_by(dzien).all()

    wg_dnia = {
        _na_date(d): (int(razem or 0), int(przypisane or 0),
                      int(eventy or 0), int(ujemne or 0))
        for d, razem, przypisane, eventy, ujemne in wiersze
    }

    # Pętla po WSZYSTKICH dniach zakresu, nie po wierszach z bazy — dzień bez
    # produkcji ma zostać na osi X.
    punkty = []
    suma_razem = suma_przypisanych = 0
    dni_z_danymi = 0
    for d in _os_dni(start_date, end_date):
        razem, przypisane, eventy, ujemne = wg_dnia.get(d, (0, 0, 0, 0))
        suma_razem += razem
        suma_przypisanych += przypisane
        if eventy:
            dni_z_danymi += 1
        punkty.append({
            'work_date': d.isoformat(),
            'coverage_pct': round(100 * przypisane / razem, 1) if razem else None,
            'pieces_abs': razem,
            'pieces_attributed': przypisane,
            'events': eventy,
            'negative_events': ujemne,
            'small_sample': bool(eventy) and razem < PROG_MALEJ_PROBKI,
        })

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'station': station or 'all',
        'points': punkty,
        'summary': {
            # Suma liczników / suma mianowników, czyli wartość WAŻONA wykresu —
            # kafelek zasilany tą liczbą nie ma jak rozjechać się z wykresem.
            'coverage_pct': (round(100 * suma_przypisanych / suma_razem, 1)
                             if suma_razem else None),
            'pieces_abs': suma_razem,
            'pieces_attributed': suma_przypisanych,
            'days_with_data': dni_z_danymi,
            'days_in_range': len(punkty),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 7 — Doróbki: ile i z czego
# ════════════════════════════════════════════════════════════════════════════

def rejestracja_dorobek(start_date, end_date):
    """
    Doróbki tydzień po tygodniu — ale dopóki próg nie jest spełniony, ten
    widget ma pokazywać PANEL, a nie wykres.

    Powód jest merytoryczny, nie techniczny: zgłaszać doróbkę można dziś TYLKO
    z formatowania (rework_service.VALID_REJECT_STATIONS), więc słupek „prawie
    zero doróbek" czyta się jako „jakość świetna", podczas gdy prawda brzmi
    „sześć z siedmiu stanowisk nie ma jak zgłosić". To nie jest brak danych,
    to byłaby błędna odpowiedź. Dlatego backend zwraca ZAWSZE oba komplety
    (liczby do panelu i tygodnie do wykresu) plus `threshold_met`, a wykres
    zapala się sam, gdy dane go uniosą.

    Filtr źródła: prod_rework_log go nie ma i nie potrzebuje (jedyny pisarz to
    reject_product_quantity() z jednego endpointu mobilnego, więc każdy wiersz
    jest z definicji pracą człowieka). Ale MIANOWNIK — sztuki sformatowane —
    filtr mieć MUSI, inaczej urośnie o auto_skip i wskaźnik doróbek sztucznie
    spadnie. To ten sam błąd co P4, tylko w drugiej pozycji ułamka.
    """
    from .rework_service import VALID_REJECT_STATIONS

    poczatek, koniec = granice_zakresu(start_date, end_date)

    wpisy = db.session.query(
        ProductionReworkLog.created_at,
        ProductionReworkLog.reason_category,
        ProductionReworkLog.quantity,
    ).filter(
        ProductionReworkLog.created_at >= poczatek,
        ProductionReworkLog.created_at <= koniec,
    ).all()

    # Tygodnie liczone w Pythonie: WEEKDAY()/DATE_SUB to MySQL, a wierszy jest
    # tu kilka. Klucz tygodnia = poniedziałek.
    tygodnie = {}
    powody = {}
    sztuk_razem = 0
    for utworzono, powod, sztuk in wpisy:
        chwila = utworzono if isinstance(utworzono, datetime) else \
            datetime.strptime(str(utworzono)[:19], '%Y-%m-%d %H:%M:%S')
        poniedzialek = (chwila.date() - timedelta(days=chwila.weekday())).isoformat()
        wpis = tygodnie.setdefault(poniedzialek, {})
        wpis[powod] = wpis.get(powod, {'entries': 0, 'pieces': 0})
        wpis[powod]['entries'] += 1
        wpis[powod]['pieces'] += int(sztuk or 0)
        licznik = powody.setdefault(powod, {'entries': 0, 'pieces': 0})
        licznik['entries'] += 1
        licznik['pieces'] += int(sztuk or 0)
        sztuk_razem += int(sztuk or 0)

    mianownik = db.session.query(
        func.coalesce(func.sum(ProductionStationEvent.delta), 0)
    ).filter(
        *_filtry_eventow_pracy(poczatek, koniec, 'formatting')
    ).scalar() or 0

    tygodnie_lista = [
        {
            'week_start': klucz,
            'reasons': {
                powod: {'entries': dane['entries'], 'pieces': dane['pieces']}
                for powod, dane in sorted(wartosc.items())
            },
            'entries': sum(d['entries'] for d in wartosc.values()),
            'pieces': sum(d['pieces'] for d in wartosc.values()),
        }
        for klucz, wartosc in sorted(tygodnie.items())
    ]

    daty = sorted(
        (w[0] if isinstance(w[0], datetime)
         else datetime.strptime(str(w[0])[:19], '%Y-%m-%d %H:%M:%S'))
        for w in wpisy
    )

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'entries': len(wpisy),
        'pieces': sztuk_razem,
        'formatted_pieces': int(mianownik),
        'rate_pct': (round(100 * sztuk_razem / int(mianownik), 2)
                     if int(mianownik) > 0 else None),
        'first_entry': daty[0].date().isoformat() if daty else None,
        'last_entry': daty[-1].date().isoformat() if daty else None,
        'reasons': [
            {
                'code': kod,
                'label': ETYKIETY_POWODOW_DOROBEK.get(kod, kod),
                'entries': dane['entries'],
                'pieces': dane['pieces'],
            }
            for kod, dane in sorted(powody.items(),
                                    key=lambda p: -p[1]['pieces'])
        ],
        'weeks': tygodnie_lista,
        # Skąd w ogóle da się dziś zgłosić doróbkę — front pisze z tego zdanie
        # diagnozy zamiast zaszywać nazwę stanowiska w szablonie.
        'reporting_stations': [
            {'station_code': kod, 'station_label': station_label(kod)}
            for kod in sorted(VALID_REJECT_STATIONS, key=_kolejnosc_stanowisk)
        ],
        'stations_total': len(STATION_ORDER),
        'threshold_entries': PROG_DOROBEK_WPISOW,
        'threshold_weeks': PROG_DOROBEK_TYGODNI,
        'threshold_met': (len(wpisy) >= PROG_DOROBEK_WPISOW
                          and len(tygodnie_lista) >= PROG_DOROBEK_TYGODNI),
    }


# ════════════════════════════════════════════════════════════════════════════
# WYKRES 8 — Wkład osób na JEDNYM stanowisku
# ════════════════════════════════════════════════════════════════════════════

# Ile wolno się rozjechać sumie słupków wobec przerobu całego stanowiska, zanim
# powiemy o tym wprost. To nie jest zapas na błąd logiczny — udziały (share)
# sumują się do 1.0 na event, więc różnicy z definicji nie ma. Tolerancja
# pokrywa WYŁĄCZNIE zaokrąglenia: praca_nieprzypisana() oddaje wiersze już
# zaokrąglone do 3 miejsc na (dzień, stanowisko), więc 30-dniowy zakres potrafi
# uzbierać do ~0.015 m³ czystej arytmetyki zmiennoprzecinkowej.
TOLERANCJA_SUMY_M3 = 0.02
TOLERANCJA_SUMY_SZTUK = 0.5


def _sprawdz_stanowisko(station):
    """
    Bramka „JEDNO, ISTNIEJĄCE stanowisko" — po stronie serwisu, nie tylko
    routera.

    Router ma własną walidację i to dobrze, ale nie może być jedyną: serwis
    woła też eksport, testy i (docelowo) każdy inny konsument, a każdy z nich
    dostawał do tej pory pusty, wyglądający na poprawny wynik dla literówki
    w kodzie stanowiska. Zmierzone przed poprawką: `station='nie_ma_takiego'`
    zwracało komplet zer z `empty_reason='brak_pracy'`, czyli odpowiedź
    „stanowisko nic nie zrobiło" na pytanie o stanowisko, którego nie ma.
    """
    if not station or station == 'all':
        raise ZakresError(
            'Ten wykres wymaga JEDNEGO stanowiska — m³ nie są porównywalne '
            'między stanowiskami, więc wykres zbiorczy nie znaczyłby nic.')
    if station not in STATION_ORDER:
        raise ZakresError(
            f'Nieznane stanowisko „{station}". Dozwolone: '
            f'{", ".join(sorted(STATION_ORDER))}.')


def _slupek_osoby(worker_id, nazwa, sztuki, metry, eventy):
    """
    Jeden słupek wykresu — z FLAGAMI LICZONYMI PO ZAOKRĄGLENIU.

    Kolejność ma znaczenie: `-1e-16 < 0` jest prawdą, więc flaga liczona
    z surowej sumy zmiennoprzecinkowej malowała na czerwono słupek, który
    użytkownik widzi jako 0.000 — „ta osoba więcej cofnęła, niż odhaczyła"
    przy zerowym słupku. Front dostaje flagi zgodne z tym, co sam narysuje.

    `zero` istnieje z tego samego powodu, tylko po drugiej stronie: słupek
    o wysokości zero jest NIEWIDOCZNY, więc nazwisko wisi na osi bez niczego
    obok. Bez tej flagi taka osoba wypadała z bilansu ostrzeżeń i wyglądała
    jak usterka renderowania.
    """
    m3 = _zaokr(metry)
    szt = zaokr_wklad(sztuki)
    return {
        'worker_id': worker_id,
        'worker_name': nazwa,
        'pieces': szt,
        'm3': m3,
        'events': eventy,
        'negative': m3 < 0 or szt < 0,
        'zero': m3 == 0 and szt == 0,
    }


def wklad_pracownikow_na_stanowisku(station, start_date, end_date):
    """
    Kto ile zrobił na JEDNYM, wybranym stanowisku — m³ i wkład w sztukach.

    DLACZEGO STANOWISKO JEST OBOWIĄZKOWE (i dlaczego nie ma tu 'all')
    -----------------------------------------------------------------
    Audyt odrzucił listę porównującą ludzi MIĘDZY stanowiskami: m³ na sklejaniu
    i m³ na pakowaniu to inna robota, więc taki ranking mierzy, kto miał
    szczęście stać na końcu procesu, a nie kto się narobił. Ten agregat jest
    odwrotnością tamtego pomysłu — stanowisko jest WYBRANE, a porównanie
    odbywa się wewnątrz niego, czyli dokładnie w warunku, który audyt postawił
    („m³ i tempo porównywalne wyłącznie w obrębie jednego stanowiska").
    Dlatego `station='all'` leci błędem, a nie sumą: zbiorczy wykres wszystkich
    stanowisk naraz JEST tamtym odrzuconym leaderboardem.

    TRZY LICZBY, KTÓRE MUSZĄ SIĘ ZGADZAĆ
    ------------------------------------
    Sam wykres osób kłamie, gdy stanowisko zrobiło 40 m³, a podpisane jest 22:
    czyta się go jako całą produkcję stanowiska. Dlatego obok osób jedzie
    `unassigned` (praca BEZ wiersza atrybucji, liczona tą samą funkcją, co
    tabela wydajności — nie drugą kopią) oraz `station_*` z własnego agregatu.
    Front rysuje osoby + jeden wyszarzony słupek „Bez podpisu", a suma
    słupków ma się zgadzać z widgetem „Wykonanie stanowiska w dniu".
    Gdyby się nie zgodziła, mówimy o tym wprost przez `sums_match`, zamiast
    dosypywać różnicę do któregokolwiek słupka.

    UWAGA NA JEDNOSTKĘ `station_m3`: to RUCH NETTO w zakresie (suma
    delta × objętość), a NIE stan „wykonane na koniec zakresu" z sąsiedniego
    widgetu. Te dwie liczby różnią się z definicji i mają prawo się różnić —
    zmierzone na kopii produkcji 06-12.08: pakowanie 5.849 m³ ruchu wobec
    5.250 m³ stanu EOD. Kafelki są podpisane tak, żeby nikt ich nie zestawiał
    jako „ta sama liczba, dwie wartości".

    KTO WCHODZI NA OŚ
    -----------------
    Nie tylko ci z atrybucją. Osoba, która MIAŁA SESJĘ na tym stanowisku
    w tym zakresie, wchodzi na wykres nawet z zerem — bo otwarta sesja też
    jest aktywnością, a wykres ma odpowiadać na pytanie „kto tu dziś był
    i co z tego wyszło". Lista budowana wyłącznie z atrybucji gubiła człowieka,
    który stał przy maszynie i nie odhaczył ani sztuki; ten sam błąd
    naprawialiśmy już raz w tabeli wydajności (wiersz „8 h / 0 m³").

    UJEMNE NETTO
    ------------
    Cofnięcia (source='admin', ludzkie korekty na tablecie) są zwykłymi
    eventami z delta < 0, więc pracownik potrafi wyjść na minus — najczęściej
    wtedy, gdy poprawia własną pomyłkę z poprzedniego dnia albo cudzą z tego
    samego. TAKIEJ OSOBY NIE UKRYWAMY i nie zerujemy jej słupka: ujemny wynik
    to informacja („tego dnia głównie cofał"), a schowanie go rozjechałoby sumę
    z przerobem stanowiska. Sortowanie malejąco po m³ i tak zsuwa takie słupki
    na koniec, a flaga `negative` pozwala frontowi je odróżnić kolorem.

    Pieces są ułamkowe, bo share = 1/N — przy brygadzie nikt nie zrobił jednej
    trzeciej deski, każdy uczestniczył w całej. Stąd nazwa „wkład", nie „sztuki",
    i stąd wspólne z tabelą wydajności zaokrąglenie (zaokr_wklad): przy jednym
    miejscu po przecinku ta sama brygada dawała 0.33 tutaj i 0.3 w podzakładce
    Ludzie.
    """
    _sprawdz_stanowisko(station)

    poczatek, koniec = granice_zakresu(start_date, end_date)
    filtry = _filtry_eventow_pracy(poczatek, koniec, station)

    # ── Wkład per osoba ──────────────────────────────────────────────────
    wiersze = db.session.query(
        ProductionStationEventWorker.worker_id,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
        func.sum(ProductionStationEvent.delta * ProductionStationEventWorker.share),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta * ProductionStationEventWorker.share),
        func.count(ProductionStationEvent.id),
    ).join(
        ProductionStationEvent,
        ProductionStationEvent.id == ProductionStationEventWorker.event_id,
    ).join(
        ProductionWorker,
        ProductionWorker.id == ProductionStationEventWorker.worker_id,
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(*filtry).group_by(
        ProductionStationEventWorker.worker_id,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
    ).all()

    osoby = []
    surowe_sztuki = surowe_metry = 0.0
    for wid, imie, nazwisko, sztuki, metry, eventy in wiersze:
        sztuki = float(sztuki or 0)
        metry = float(metry or 0)
        surowe_sztuki += sztuki
        surowe_metry += metry
        osoby.append(_slupek_osoby(
            wid, f'{imie} {nazwisko}'.strip(), sztuki, metry, int(eventy or 0)))

    # ── Osoby, które BYŁY, ale nic nie odbiły ────────────────────────────
    # Sesja na tym stanowisku to aktywność, więc taka osoba należy na oś tak
    # samo jak ta z atrybucją — tylko z zerem. Wcześniej znikała bez śladu,
    # bo lista powstawała wyłącznie z wierszy atrybucji, i wykres milczał
    # o kimś, kto przestał przez zmianę przy maszynie.
    znani = {o['worker_id'] for o in osoby}
    obecni = db.session.query(
        ProductionWorkerSession.worker_id,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
    ).join(
        ProductionWorker,
        ProductionWorker.id == ProductionWorkerSession.worker_id,
    ).filter(
        ProductionWorkerSession.station_code == station,
        ProductionWorkerSession.work_date >= start_date,
        ProductionWorkerSession.work_date <= end_date,
    ).distinct().all()
    for wid, imie, nazwisko in obecni:
        if wid in znani:
            continue
        znani.add(wid)
        osoby.append(_slupek_osoby(
            wid, f'{imie} {nazwisko}'.strip(), 0.0, 0.0, 0))

    # Malejąco po m³ — w obrębie JEDNEGO stanowiska to uczciwe porównanie i o to
    # w tym widgecie chodzi. Nazwisko jako drugi klucz, żeby dwie osoby z tym
    # samym wynikiem nie zamieniały się miejscami między odświeżeniami.
    osoby.sort(key=lambda o: (-o['m3'], o['worker_name']))

    # ── Praca bez podpisu ────────────────────────────────────────────────
    # Ta sama funkcja, z której liczy tabela wydajności pracowników. Druga
    # kopia tej logiki oznaczałaby dwie odpowiedzi na pytanie „ile roboty
    # przeszło bez profilu" — a to jest ten sam błąd, który już raz naprawialiśmy.
    nieprzypisane = praca_nieprzypisana(start_date, end_date, station=station)
    sztuki_bez = sum(w['pieces'] for w in nieprzypisane)
    metry_bez = sum(w['m3'] for w in nieprzypisane)

    # ── Przerób całego stanowiska (punkt odniesienia) ────────────────────
    # Osobny agregat, a nie suma dwóch powyższych: to właśnie ta liczba stoi
    # w sąsiednim widgecie „Wykonanie stanowiska w dniu" i to z nią suma
    # słupków ma się zgadzać. Liczba EVENTÓW, nie suma delt, rozstrzyga
    # o pustym stanie — dzień, w którym wszystko dorobiono i cofnięto, ma netto
    # zero, ale pracą był.
    sztuki_stanowiska, metry_stanowiska, eventy_stanowiska = db.session.query(
        func.sum(ProductionStationEvent.delta),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta),
        func.count(ProductionStationEvent.id),
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(*filtry).one()

    eventy_stanowiska = int(eventy_stanowiska or 0)
    sztuki_stanowiska = float(sztuki_stanowiska or 0)
    metry_stanowiska = float(metry_stanowiska or 0)

    # ── Dwa RÓŻNE puste stany ────────────────────────────────────────────
    # (a) stanowisko nic nie zrobiło — informacja o PRODUKCJI,
    # (b) zrobiło, ale na osi nie ma ani jednej osoby (ani podpisu, ani sesji)
    #     — informacja o WDROŻENIU profili.
    # Zlanie ich w jedno „brak danych" podpowiadałoby, że wystarczy zmienić
    # zakres dat — a w przypadku (b) nie wystarczy, bo tablet na tym stanowisku
    # w ogóle nie wysyła jeszcze identyfikatorów pracowników. Uwaga: (b) NIE
    # wygasza wykresu. Właściciel chce oglądać dane historyczne, a wykres
    # z jednym szarym słupkiem jest dla nich poprawną odpowiedzią — trzeba go
    # tylko podpisać tak, żeby czytało się go jako fakt, a nie awarię.
    if not eventy_stanowiska:
        powod_pustki = 'brak_pracy'
    elif not osoby:
        powod_pustki = 'brak_profili'
    else:
        powod_pustki = None

    zgodne = (
        abs(surowe_metry + metry_bez - metry_stanowiska) <= TOLERANCJA_SUMY_M3
        and abs(surowe_sztuki + sztuki_bez - sztuki_stanowiska) <= TOLERANCJA_SUMY_SZTUK
    )

    # ── Ile tej roboty ma podpis ─────────────────────────────────────────
    # JEDNA funkcja — ta sama, z której rysuje się wykres „Pokrycie atrybucją
    # w czasie" i kafelek w tabeli wydajności. Stała tu wcześniej DRUGA
    # implementacja: udział m³ netto (na ABS dopiero z sumy per osoba) zamiast
    # ruchu w sztukach z ABS na poziomie eventu. Dwie odpowiedzi na to samo
    # pytanie, dwa widgety w zasięgu wzroku — zmierzone na kopii produkcji
    # 06-12.08: montaż 28.4% tu wobec 25.4% na wykresie pokrycia, formatowanie
    # 8.8% wobec 6.6%, sklejanie 9.1% wobec 10.7%.
    #
    # Cena: jednostką jest RUCH W SZTUKACH, nie m³ — i kafelek jest tak
    # podpisany. Przeliczanie tego na m³ oznaczałoby napisanie tej definicji
    # po raz drugi, czyli powrót dokładnie tam, skąd wyszliśmy.
    pokrycie = pokrycie_atrybucji_dziennie(
        start_date, end_date, station=station)['summary']

    # Od kiedy w ogóle da się cokolwiek podpisać NA TYM stanowisku. Przypis pod
    # wykresem liczy z tego zdanie „pracy sprzed tej daty nie da się przypisać
    # wstecz" — bez niego szary słupek na danych historycznych czyta się jak
    # awaria, a jest normalnym stanem sprzed wdrożenia profili.
    pierwszy_podpis = db.session.query(
        func.min(ProductionStationEvent.created_at)
    ).join(
        ProductionStationEventWorker,
        ProductionStationEventWorker.event_id == ProductionStationEvent.id,
    ).filter(
        ProductionStationEvent.station_code == station,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).scalar()
    # MIN() po kolumnie DATETIME oddaje w SQLite tekst, a w MySQL obiekt —
    # front dostaje ISO w obu przypadkach, bo inaczej przypis wyglądałby
    # inaczej na testach niż na produkcji.
    if isinstance(pierwszy_podpis, str):
        pierwszy_podpis = datetime.strptime(pierwszy_podpis[:19], '%Y-%m-%d %H:%M:%S')

    sztuki_bez = zaokr_wklad(sztuki_bez)
    metry_bez = _zaokr(metry_bez)

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'station': station,
        'station_label': station_label(station),
        'workers': osoby,
        # Osobne pole, a nie kolejny wiersz w `workers`: „Bez podpisu" nie
        # jest osobą, nie wchodzi do sortowania i nie ma prawa wylądować
        # w środku wykresu ani zostać policzone jako pracownik. Flagi ma za to
        # te same co osoby — słupek pod zerem znaczy to samo niezależnie od
        # tego, czy stoi nad nim nazwisko.
        'unassigned': {
            'pieces': sztuki_bez,
            'm3': metry_bez,
            'present': bool(nieprzypisane),
            'negative': metry_bez < 0 or sztuki_bez < 0,
            'zero': metry_bez == 0 and sztuki_bez == 0,
        },
        'summary': {
            # RUCH NETTO w zakresie (Σ delta × m³), nie stan „wykonane na
            # koniec zakresu" z sąsiedniego widgetu — patrz docstring.
            'station_pieces': zaokr_wklad(sztuki_stanowiska),
            'station_m3': _zaokr(metry_stanowiska),
            'station_events': eventy_stanowiska,
            'attributed_pieces': zaokr_wklad(surowe_sztuki),
            'attributed_m3': _zaokr(surowe_metry),
            'unassigned_pieces': sztuki_bez,
            'unassigned_m3': metry_bez,
            'workers_count': len(osoby),
            'workers_negative': sum(1 for o in osoby if o['negative']),
            # Osoby bez widocznego słupka: sesja bez ani jednej sztuki albo
            # tyle samo cofnięte, co odhaczone. Front musi mieć z czego
            # napisać, dlaczego nazwisko wisi na osi bez niczego obok.
            'workers_zero': sum(1 for o in osoby if o['zero']),
            # Ta sama liczba, którą pokazuje wykres „Pokrycie atrybucją
            # w czasie" — jedna definicja, jedno miejsce w kodzie. Jednostka:
            # ruch w SZTUKACH (ABS na poziomie eventu).
            'attribution_coverage_pct': pokrycie['coverage_pct'],
            'coverage_pieces_abs': pokrycie['pieces_abs'],
            'coverage_pieces_attributed': pokrycie['pieces_attributed'],
            'first_attribution_at': (pierwszy_podpis.isoformat()
                                     if pierwszy_podpis else None),
            'empty_reason': powod_pustki,
            # Fałsz znaczy, że udziały eventów nie zsumowały się do 1.0 —
            # mówimy o tym wprost, zamiast dosypywać różnicę do słupków.
            'sums_match': zgodne,
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# BADGE „TRWA NAUKA" — stan dojrzałości danych z profili
# ════════════════════════════════════════════════════════════════════════════

def zloz_stan_nauki(dni_z_danymi, prog_dni, stanowiska_z_profilami,
                    stanowiska_pracujace, window_start=None, window_end=None,
                    production_days_in_window=0, stations_with_attribution=0,
                    stations_without_profiles=()):
    """
    CZYSTA decyzja — bez bazy, żeby dało się ją przetestować tabelą prawdy.

    Dwa wymiary naraz, oba liczone Z DANYCH:
      1. CZAS     — ile dni produkcyjnych w oknie ma sesje, wobec progu,
      2. POKRYCIE — ile stanowisk raportuje profile, wobec liczby stanowisk,
                    które w tym oknie COKOLWIEK zrobiły.

    Mianownik pokrycia jest RUCHOMY i to jest zamierzone: stanowisko stojące bez
    roboty nie może trzymać badge'a w nieskończoność. Skutek uboczny — badge
    potrafi mrugnąć między zakresami — gasi tooltip z listą stanowisk bez
    profili.

    Badge znika, gdy OBA warunki są spełnione, i WRACA, gdy którykolwiek się
    cofnie. Żadnego odliczania „zostało X dni": taka reguła nie potrafi wrócić,
    gdy jeden tablet wypadnie.
    """
    czas_ok = dni_z_danymi >= prog_dni
    pokrycie_ok = (stanowiska_z_profilami >= stanowiska_pracujace
                   if stanowiska_pracujace else True)
    uczy_sie = not (czas_ok and pokrycie_ok)

    # Przycięcie do progu, żeby nigdy nie wyszło „dane z 16 z 14 dni".
    dni_w_tekscie = min(dni_z_danymi, prog_dni)
    czesci = [f'dane z {dni_w_tekscie} z {prog_dni} dni']
    if stanowiska_pracujace:
        czesci.append(f'profile na {stanowiska_z_profilami} '
                      f'z {stanowiska_pracujace} pracujących stanowisk')
    elif not production_days_in_window:
        czesci.append('brak pracy na stanowiskach w tym okresie')
    tekst = 'Trwa nauka — ' + ' · '.join(czesci)

    return {
        'learning': uczy_sie,
        'label': 'Trwa nauka',
        # Tekst składa się po stronie serwera: jedno źródło brzmienia dla
        # widgetów i dla arkusza XLSX.
        'text': tekst,
        'days_with_data': dni_z_danymi,
        'days_required': prog_dni,
        'days_ok': czas_ok,
        'stations_with_profiles': stanowiska_z_profilami,
        'stations_working': stanowiska_pracujace,
        'stations_ok': pokrycie_ok,
        'stations_with_attribution': stations_with_attribution,
        'stations_without_profiles': list(stations_without_profiles),
        'window_start': window_start.isoformat() if window_start else None,
        'window_end': window_end.isoformat() if window_end else None,
        'production_days_in_window': production_days_in_window,
    }


def stan_nauki(end_date=None, prog_dni=None):
    """
    Stan badge'a na dany dzień. Cztery lekkie agregaty, wołane raz na request.

    OKNO = OSTATNIE `prog_dni` DNI PRODUKCYJNYCH, nie kalendarzowych. To jedyne
    odstępstwo od dosłownego brzmienia kontraktu badge'a i jest konieczne:
    hala pracuje pn-pt, więc w 14 dniach kalendarza mieści się góra 10 dni
    roboczych, a „dane z 14 z 14 dni" liczone po kalendarzu NIGDY by się nie
    spełniło i badge zostałby na ekranie na zawsze.

    Okno jest przywiązane do end_date, a nie do długości wybranego zakresu —
    dzięki temu badge nie zmienia znaczenia, gdy ktoś przełącza „Dziś" na
    „30 dni" (przy zakresie 7-dniowym wymiar czasu z definicji nie mógłby
    dobić do 14).
    """
    from .worker_service import get_learning_days

    end_date = end_date or get_local_now().date()
    prog_dni = prog_dni or get_learning_days()
    koniec = datetime.combine(end_date, datetime.max.time())

    dzien = func.date(ProductionStationEvent.created_at).label('dzien')

    def zapytaj(dolna_granica):
        filtry = [
            ProductionStationEvent.created_at <= koniec,
            ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if dolna_granica is not None:
            filtry.append(ProductionStationEvent.created_at
                          >= datetime.combine(dolna_granica, datetime.min.time()))
        return db.session.query(dzien).filter(*filtry).group_by(
            dzien).order_by(dzien.desc()).limit(prog_dni).all()

    dni_produkcyjne = [_na_date(d)
                       for (d,) in _ostatnie_doby(zapytaj, end_date, prog_dni)]

    if not dni_produkcyjne:
        return zloz_stan_nauki(0, prog_dni, 0, 0, window_end=end_date)

    okno_start = min(dni_produkcyjne)
    okno_poczatek = datetime.combine(okno_start, datetime.min.time())

    dni_z_sesjami = {
        d for (d,) in db.session.query(
            distinct(ProductionWorkerSession.work_date)
        ).filter(
            ProductionWorkerSession.work_date >= okno_start,
            ProductionWorkerSession.work_date <= end_date,
        ).all()
    }
    dni_z_danymi = len(set(dni_produkcyjne) & {_na_date(d) for d in dni_z_sesjami})

    pracujace = {
        kod for (kod,) in db.session.query(
            distinct(ProductionStationEvent.station_code)
        ).filter(*_filtry_eventow_pracy(okno_poczatek, koniec)).all()
    }
    z_sesjami = {
        kod for (kod,) in db.session.query(
            distinct(ProductionWorkerSession.station_code)
        ).filter(
            ProductionWorkerSession.work_date >= okno_start,
            ProductionWorkerSession.work_date <= end_date,
        ).all()
    }
    # Przecięcie z mianownikiem, nie sama liczba sesji: sesja na trakowni —
    # której prod_station_events w ogóle nie zna — dałaby „6 z 5 stanowisk".
    z_profilami = pracujace & z_sesjami

    z_atrybucja = {
        kod for (kod,) in db.session.query(
            distinct(ProductionStationEvent.station_code)
        ).join(
            ProductionStationEventWorker,
            ProductionStationEventWorker.event_id == ProductionStationEvent.id,
        ).filter(*_filtry_eventow_pracy(okno_poczatek, koniec)).all()
    }

    return zloz_stan_nauki(
        dni_z_danymi, prog_dni, len(z_profilami), len(pracujace),
        window_start=okno_start, window_end=end_date,
        production_days_in_window=len(dni_produkcyjne),
        # stations_with_attribution jedzie tylko do tooltipa i NIE bramkuje
        # decyzji: bramkowanie na atrybucji duplikowałoby wykres 6 i trzymało
        # badge przy jednym stanowisku ze starszym APK.
        stations_with_attribution=len(z_atrybucja & pracujace),
        stations_without_profiles=sorted(
            station_label(kod) for kod in (pracujace - z_sesjami)),
    )
