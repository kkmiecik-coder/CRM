# modules/production/services/worker_stats_service.py
"""
Statystyki pracy pracowników — wydajność, czas pracy, tempo.

Projekt: docs/worker-profiles-backend.md §7.2

Wzorowane na station_events_service: liczymy z prod_station_events, tyle że
przez tabelę atrybucji, więc jeden event potrafi zasilić kilku pracowników
ułamkami (share = 1/N).

DWIE ZASADY, których nie wolno tu ruszyć:

1. Filtr `source NOT IN ('auto_skip','system')` jest OBOWIĄZKOWY. To eventy
   stanowisk POMINIĘTYCH, generowane przez complete_task() — nikt ich fizycznie
   nie wykonał. Bez filtra sklejacz dostaje kredyt za formatowanie, którego
   nie było. Filtrujemy po source, a nie po „braku wiersza atrybucji", bo to
   odporniejsze: działa nawet gdyby ktoś kiedyś nieopatrznie dopisał atrybucję
   do tych ścieżek.

2. Eventy bez atrybucji trafiają do osobnego wiersza „Nieprzypisane", a nie
   znikają. To cała produkcja sprzed wdrożenia profili oraz akcje wykonane
   przy wyłączonej bramce. Ukrywanie ich kłamałoby o sumach; pokazywanie
   pozwala zobaczyć, kiedy pokrycie atrybucją dojdzie do 100%.

Czas pracy liczymy w PYTHONIE, nie przez TIMESTAMPDIFF: sesji jest rzędu
dziesiątek dziennie, a funkcje czasu w SQL rozjeżdżają się między MySQL
a SQLite (na którym chodzą testy).
"""

from datetime import datetime, timedelta

from sqlalchemy import func

from extensions import db
from modules.logging import get_structured_logger

from ..models import (
    ProductionProduct, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession, get_local_now,
)
from .worker_service import station_label

logger = get_structured_logger('production.worker_stats')

# Eventy, których nikt nie wykonał — patrz zasada 1 w docstringu modułu.
ZRODLA_AUTOMATU = ('auto_skip', 'system')

MAKS_ZAKRES_DNI = 365


class ZakresError(ValueError):
    """Nieprawidłowy zakres dat — router zamienia to na 400."""


def granice_zakresu(start_date, end_date):
    """
    (początek, koniec) jako naive datetime + walidacja zakresu.

    Publiczna, bo reports_service liczy z tych samych tabel i musi rozumieć
    zakres identycznie — inaczej ten sam „ostatni tydzień" obejmowałby w dwóch
    widgetach różne godziny ostatniej doby.
    """
    if start_date > end_date:
        raise ZakresError('Data początkowa musi być wcześniejsza lub równa końcowej')
    if (end_date - start_date).days + 1 > MAKS_ZAKRES_DNI:
        raise ZakresError(f'Maksymalny zakres to {MAKS_ZAKRES_DNI} dni')
    return (datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time()))


def _zaokraglij(wartosc, miejsca=1):
    return round(float(wartosc or 0), miejsca)


# Ile miejsc po przecinku ma „wkład w sztukach". Wkład bywa ułamkowy, bo przy
# brygadzie share = 1/N — i przy jednym miejscu trzy udziały po 0.3 nie składają
# się z powrotem w sztukę (0.9 ≠ 1). Stała jest publiczna i wspólna z wykresem
# „Kto ile zrobił na stanowisku": ta sama osoba, to samo stanowisko i ten sam
# dzień muszą dawać tę samą liczbę w obu podzakładkach, bo użytkownik przechodzi
# między nimi jednym kliknięciem.
MIEJSC_WKLADU = 2


def zaokr_wklad(wartosc):
    """Zaokrąglenie wkładu w sztukach — jedno dla wszystkich widgetów."""
    return _zaokraglij(wartosc, MIEJSC_WKLADU)


def granica_nocna_sesji(sesja, cutoff):
    """
    Do której chwili wolno liczyć sesję OTWARTĄ — nocny cutoff jej doby.

    Sesja zaczęta PO cutoffie swojej doby (druga zmiana wchodząca o 23:55 przy
    cutoffie 23:00) należy już do doby NASTĘPNEJ, więc jej granicą jest cutoff
    dnia następnego. Ta sama reguła co w worker_service.close_stale_sessions(),
    gdzie warunek `sesja.started_at < granica_nocna` chroni taką sesję przed
    domknięciem z czasem zero.
    """
    granica = datetime.combine(sesja.work_date, cutoff)
    if sesja.started_at >= granica:
        granica = datetime.combine(sesja.work_date + timedelta(days=1), cutoff)
    return granica


def minuty_sesji(sesja, teraz, cutoff, idle_minut=None):
    """
    Ile minut liczy się z jednej sesji pracy.

    DWA STANY, DWIE REGUŁY:

    1. Sesja DOMKNIĘTA ma autorytatywny koniec i liczy się w całości — dokładnie
       tak, jak liczy ją ProductionWorkerSession.duration_minutes. Koniec stawia
       albo serwer (cutoff / idle_timeout w close_stale_sessions), albo tablet,
       a korekta z tabletu działa wyłącznie W DÓŁ, w oknie
       [started_at, obecny ended_at) — nie ma tu czego przycinać.
    2. Sesja OTWARTA liczy się do NAJWCZEŚNIEJSZEJ z trzech granic:
       teraz, nocny cutoff swojej doby, ostatnia aktywność + idle_timeout.
       To DOKŁADNIE ta sama trójka, którą stosuje worker_service
       .close_stale_sessions() na ścieżce ZAPISU.

    Reguła bezczynności musi tu być, bo inaczej ta sama sesja ma dwie różne
    długości zależnie od tego, czy cron zdążył ją domknąć. Zmierzone
    2026-08-12 o 11:31: sesja 12 (pakowanie, Owsiany, start 06:16:57, ostatnia
    aktywność 08:33:18) liczyła się na 314 min, a cron domknąłby ją na
    10:33:18, czyli 256 min — kafelek „osobogodzin" i tempo m³/h kurczyły się
    WSTECZ po każdym przebiegu crona. Że ścieżka zapisu tak właśnie liczy,
    widać w danych: sesja 5 ma ended_at dokładnie 120 minut po last_activity_at.

    Poprzednia wersja przycinała OBA stany do `min(teraz, combine(work_date,
    cutoff))` i miała przez to dwie dziury, obie widoczne tylko o pewnych
    porach doby — dlatego przeszły w ciągu dnia i wjechały na produkcję:

      • sesja rozpoczęta PO cutoffie swojej doby miała granicę WCZEŚNIEJ niż
        własny start, więc wychodziło ZERO minut. Cała zmiana takiego
        pracownika znikała z raportu, a tempo m³/h dzieliło przez zero;
      • sesja domknięta, która przekroczyła cutoff (22:55 → 00:55) albo miała
        koniec późniejszy niż moment liczenia raportu, gubiła przepracowane
        minuty — z dwóch godzin robiło się pięć minut.

    Wyciągnięte z czas_pracy(), bo tę samą regułę stosuje wykres „Obsada vs
    przerób" w reports_service. Dwie kopie tej reguły to dwie różne odpowiedzi
    na pytanie „ile godzin przepracowało stanowisko".
    """
    if sesja.ended_at is not None:
        koniec = sesja.ended_at
    else:
        if idle_minut is None:
            from .worker_service import get_idle_timeout_minutes
            idle_minut = get_idle_timeout_minutes()
        # last_activity_at bywa puste na świeżo wstawionym wierszu (kolumna ma
        # default dopiero na poziomie bazy) — wtedy odpowiednikiem ostatniej
        # aktywności jest sam start sesji.
        ostatnia = sesja.last_activity_at or sesja.started_at
        koniec = min(teraz,
                     granica_nocna_sesji(sesja, cutoff),
                     ostatnia + timedelta(minutes=idle_minut))
    return max(0, int((koniec - sesja.started_at).total_seconds() // 60))


def wydajnosc_pracownikow(start_date, end_date, station=None, worker_id=None):
    """
    Wiersze dzień × pracownik × stanowisko.

    Zwraca listę dictów posortowaną po dacie malejąco, potem po nazwisku —
    tak jak ma się wyświetlać w tabeli, żeby front nie musiał sortować.
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    zapytanie = db.session.query(
        ProductionStationEventWorker.worker_id,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
        func.date(ProductionStationEvent.created_at).label('dzien'),
        ProductionStationEvent.station_code,
        func.sum(ProductionStationEvent.delta * ProductionStationEventWorker.share),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta * ProductionStationEventWorker.share),
    ).join(
        ProductionStationEvent,
        ProductionStationEvent.id == ProductionStationEventWorker.event_id,
    ).join(
        ProductionWorker,
        ProductionWorker.id == ProductionStationEventWorker.worker_id,
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    )

    if station and station != 'all':
        zapytanie = zapytanie.filter(ProductionStationEvent.station_code == station)
    if worker_id:
        zapytanie = zapytanie.filter(ProductionStationEventWorker.worker_id == worker_id)

    zapytanie = zapytanie.group_by(
        ProductionStationEventWorker.worker_id,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
        func.date(ProductionStationEvent.created_at),
        ProductionStationEvent.station_code,
    )

    wiersze = []
    for wid, imie, nazwisko, dzien, kod, sztuki, metry in zapytanie.all():
        wiersze.append({
            'worker_id': wid,
            'worker_name': f'{imie} {nazwisko}'.strip(),
            'work_date': str(dzien)[:10],
            'station_code': kod,
            'station_label': station_label(kod),
            'pieces': zaokr_wklad(sztuki),
            'm3': _zaokraglij(metry, 3),
        })

    wiersze.sort(key=lambda w: (w['work_date'], w['worker_name'], w['station_label']),
                 reverse=False)
    return wiersze


def praca_nieprzypisana(start_date, end_date, station=None):
    """
    Eventy BEZ wiersza atrybucji — produkcja, przy której nie wiadomo kto pracował.

    Nie ukrywamy jej: to uczciwsze niż zerowanie i pokazuje postęp pokrycia
    (§4.7). Przy filtrze na konkretnego pracownika ta sekcja i tak nie ma sensu,
    więc router jej wtedy nie woła.
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    zapytanie = db.session.query(
        func.date(ProductionStationEvent.created_at).label('dzien'),
        ProductionStationEvent.station_code,
        func.sum(ProductionStationEvent.delta),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta),
    ).outerjoin(
        ProductionStationEventWorker,
        ProductionStationEventWorker.event_id == ProductionStationEvent.id,
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ProductionStationEventWorker.event_id.is_(None),
    )

    if station and station != 'all':
        zapytanie = zapytanie.filter(ProductionStationEvent.station_code == station)

    zapytanie = zapytanie.group_by(
        func.date(ProductionStationEvent.created_at),
        ProductionStationEvent.station_code,
    )

    return [
        {
            'work_date': str(dzien)[:10],
            'station_code': kod,
            'station_label': station_label(kod),
            'pieces': zaokr_wklad(sztuki),
            'm3': _zaokraglij(metry, 3),
        }
        for dzien, kod, sztuki, metry in zapytanie.all()
    ]


def czas_pracy(start_date, end_date, worker_id=None, station=None):
    """
    {(worker_id, 'YYYY-MM-DD'): minuty} z sesji pracy.

    `station` MUSI być przekazywane razem z filtrem stanowiska na wydajności —
    inaczej licznik (m³ z jednego stanowiska) dzieli się przez mianownik (czas
    ze wszystkich), co zaniża tempo tym, którzy pracują na kilku stanowiskach.

    Sesja otwarta liczy się do teraz, ale NIE dłużej niż do nocnego cutoffu
    swojej doby. Bez tego ogranicznika sesja zapomniana miesiąc temu — a taka
    powstanie, dopóki nie ma wpisu w crontabie domykającego zapomniane sesje —
    dorzucałaby do jednej doby setki godzin i rozwalała tempo w raporcie.

    Liczone w Pythonie, nie w SQL: TIMESTAMPDIFF nie istnieje w SQLite,
    a wolumen danych jest znikomy.
    """
    from .worker_service import get_night_cutoff, get_idle_timeout_minutes

    zapytanie = ProductionWorkerSession.query.filter(
        ProductionWorkerSession.work_date >= start_date,
        ProductionWorkerSession.work_date <= end_date,
    )
    if worker_id:
        zapytanie = zapytanie.filter(ProductionWorkerSession.worker_id == worker_id)
    if station and station != 'all':
        zapytanie = zapytanie.filter(ProductionWorkerSession.station_code == station)

    teraz = get_local_now()
    cutoff = get_night_cutoff()
    # Konfiguracja czytana RAZ na wywołanie, nie raz na sesję: get_config()
    # trafia do bazy, a sesji bywają dziesiątki.
    idle_minut = get_idle_timeout_minutes()

    minuty = {}
    for sesja in zapytanie.all():
        trwanie = minuty_sesji(sesja, teraz, cutoff, idle_minut)
        klucz = (sesja.worker_id, sesja.work_date.isoformat())
        minuty[klucz] = minuty.get(klucz, 0) + trwanie
    return minuty


def liczba_eventow_pracy(start_date, end_date, station=None):
    """
    Ile ZDARZEŃ ludzkich zarejestrowano w zakresie (z filtrem stanowiska).

    Osobna liczba od sumy delt, bo suma delt potrafi wyjść ZERO na dobie,
    w której pracowano: 2026-04-29 formatowanie ma 4 eventy (2 dorobki i
    2 cofnięcia), netto 0. Raport rozstrzygający pustkę po netto pisał wtedy
    „żadne stanowisko nie zarejestrowało wykonania", podczas gdy widget obok
    (pokrycie atrybucją) raportował 4 sztuki ruchu. Pustkę rozstrzyga się po
    LICZBIE ZDARZEŃ, nie po ich wypadkowej.

    Ta sama rola co pole `station_events` w reports_service
    .wklad_pracownikow_na_stanowisku — jedna definicja „czy coś się działo".
    """
    poczatek, koniec = granice_zakresu(start_date, end_date)

    zapytanie = db.session.query(func.count(ProductionStationEvent.id)).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    )
    if station and station != 'all':
        zapytanie = zapytanie.filter(ProductionStationEvent.station_code == station)
    return int(zapytanie.scalar() or 0)


def otwarte_sesje(start_date, end_date, worker_id=None, station=None):
    """
    {worker_id: ile} sesji BEZ ended_at w zakresie.

    Godziny takiej sesji rosną w trakcie oglądania raportu, więc tempo w jej
    wierszu jest wartością chwilową. Widget „Obsada vs przerób" mówi o tym
    wprost od początku (kafelek „otwartych sesji"); tabela wydajności — jako
    jedyna podająca tempo PER OSOBA — nie miała skąd wziąć tej liczby.
    """
    zapytanie = db.session.query(
        ProductionWorkerSession.worker_id,
        func.count(ProductionWorkerSession.id),
    ).filter(
        ProductionWorkerSession.work_date >= start_date,
        ProductionWorkerSession.work_date <= end_date,
        ProductionWorkerSession.ended_at.is_(None),
    )
    if worker_id:
        zapytanie = zapytanie.filter(ProductionWorkerSession.worker_id == worker_id)
    if station and station != 'all':
        zapytanie = zapytanie.filter(ProductionWorkerSession.station_code == station)

    return {wid: int(ile or 0)
            for wid, ile in zapytanie.group_by(
                ProductionWorkerSession.worker_id).all()}


def raport_wydajnosci(start_date, end_date, station=None, worker_id=None):
    """
    Komplet danych do raportu: wiersze, sumy per pracownik, sumy dzienne,
    praca nieprzypisana i podsumowanie okresu.

    Tempo = m³ / (minuty / 60). Liczymy je tylko tam, gdzie pracownik ma
    JAKĄKOLWIEK atrybucję: bez sesji tempo byłoby dzieleniem przez zero,
    a bez atrybucji — dzieleniem zera, czyli „0 m³/h" postawionym przy
    nazwisku człowieka, o którym raport nic nie wie.
    """
    wiersze = wydajnosc_pracownikow(start_date, end_date, station, worker_id)
    # Ten sam filtr stanowiska co w liczniku — patrz docstring czas_pracy()
    minuty = czas_pracy(start_date, end_date, worker_id, station)
    nieprzypisane = [] if worker_id else praca_nieprzypisana(start_date, end_date, station)

    # Sumy per pracownik
    per_pracownik = {}
    for w in wiersze:
        wpis = per_pracownik.setdefault(w['worker_id'], {
            'worker_id': w['worker_id'],
            'worker_name': w['worker_name'],
            'pieces': 0.0, 'm3': 0.0, 'minutes': 0, 'stations': set(),
        })
        wpis['pieces'] += w['pieces']
        wpis['m3'] += w['m3']
        wpis['stations'].add(w['station_label'])

    # Pracownicy, którzy MIELI SESJĘ, ale nie odbili ani jednej sztuki, też
    # muszą się pojawić — wiersz "8,0 h / 0 m³ / tempo —" sam rzuca się w oczy
    # i jest jedyną odpowiedzią na pytanie "czy ktoś stoi bezczynnie".
    # Wcześniej tabela powstawała wyłącznie z atrybucji, więc taka osoba
    # znikała, a jej godziny zostawały tylko w sumie zbiorczej.
    braki = {wid for (wid, _d) in minuty if wid not in per_pracownik}
    if braki:
        for pracownik in ProductionWorker.query.filter(
                ProductionWorker.id.in_(list(braki))).all():
            per_pracownik[pracownik.id] = {
                'worker_id': pracownik.id,
                'worker_name': pracownik.full_name,
                'pieces': 0.0, 'm3': 0.0, 'minutes': 0, 'stations': set(),
            }

    for (wid, _dzien), minut in minuty.items():
        wpis = per_pracownik.get(wid)
        if wpis is not None:
            wpis['minutes'] += minut

    otwarte = otwarte_sesje(start_date, end_date, worker_id, station)

    podsumowanie_pracownikow = []
    for wpis in per_pracownik.values():
        godziny = wpis['minutes'] / 60 if wpis['minutes'] else 0
        # `stations` jest niepuste dokładnie wtedy, gdy pracownik ma choć jeden
        # wiersz atrybucji — to jedyny sygnał odróżniający „zmierzone zero"
        # od „nie wiemy nic".
        ma_atrybucje = bool(wpis['stations'])
        podsumowanie_pracownikow.append({
            'worker_id': wpis['worker_id'],
            'worker_name': wpis['worker_name'],
            'pieces': zaokr_wklad(wpis['pieces']),
            'm3': _zaokraglij(wpis['m3'], 3),
            'minutes': wpis['minutes'],
            'hours': _zaokraglij(godziny, 1),
            'stations': sorted(wpis['stations']),
            # Bramka na atrybucji, nie tylko na godzinach. Sama bramka `if
            # godziny` chroniła przed dzieleniem PRZEZ zero, ale nie przed
            # dzieleniem ZERA: Józef Pustelnik (87 min sesji, ani jednej
            # atrybucji) dostawał „tempo 0.0 m³/h", czyli zarzut bezczynności
            # postawiony na podstawie braku danych. Docstring obok obiecuje
            # dla takiego wiersza „8,0 h / 0 m³ / tempo —" i to jest ta obietnica.
            'pace_m3_per_hour': (_zaokraglij(wpis['m3'] / godziny, 3)
                                 if godziny and ma_atrybucje else None),
            'has_attribution': ma_atrybucje,
            # Wiersz z otwartą sesją ma mianownik, który rośnie w trakcie
            # oglądania — front oznacza go gwiazdką zamiast udawać pomiar.
            'open_sessions': otwarte.get(wpis['worker_id'], 0),
        })
    # Sortowanie po NAZWISKU, nie po m³. Sortowanie malejąco po objętości robi
    # z tej tabeli ranking wydajności, a m³ nie są porównywalne między
    # stanowiskami: spakowanie metra sześciennego trwa minuty, sklejenie —
    # godziny. Na górze zawsze lądowałby pakowacz, niezależnie od tego, kto
    # naprawdę się narobił. Kto chce rankingu, filtruje po stanowisku.
    podsumowanie_pracownikow.sort(key=lambda p: p['worker_name'])

    # Sumy dzienne (razem z nieprzypisanymi — to nadal wykonana produkcja)
    per_dzien = {}
    for zrodlo in (wiersze, nieprzypisane):
        for w in zrodlo:
            wpis = per_dzien.setdefault(w['work_date'], {
                'work_date': w['work_date'], 'pieces': 0.0, 'm3': 0.0})
            wpis['pieces'] += w['pieces']
            wpis['m3'] += w['m3']

    podsumowanie_dzienne = sorted(
        ({'work_date': w['work_date'],
          'pieces': zaokr_wklad(w['pieces']),
          'm3': _zaokraglij(w['m3'], 3)} for w in per_dzien.values()),
        key=lambda w: w['work_date'])

    sztuki_nieprzypisane = sum(w['pieces'] for w in nieprzypisane)
    sztuki_przypisane = sum(w['pieces'] for w in wiersze)

    # Pokrycie liczy JEDNA funkcja — ta sama, która rysuje wykres „Pokrycie
    # atrybucją w czasie". Kafelek i wykres stojące obok siebie nie mają jak
    # pokazać dwóch różnych liczb.
    #
    # Wcześniej liczyło się tutaj, z wartości bezwzględnych nałożonych na sumę
    # NETTO per (dzień, stanowisko) — a to za późno: cofnięcia kasowały się
    # z dorobkami w mianowniku. Zmierzone na 2026-08-01..08-11: 80.2% zamiast
    # uczciwych 73.2%; realny przykład to 2026-08-11 na sklejaniu bez
    # atrybucji, gdzie netto wynosi +1 przy 39 sztukach ruchu i 11 eventach
    # ujemnych. Nowa wersja bierze ABS na poziomie EVENTU, więc licznik jest
    # podzbiorem mianownika i wynik jest z definicji zamknięty w 0-100%.
    #
    # Import lokalny, bo reports_service importuje ten moduł na górze pliku.
    from .reports_service import pokrycie_atrybucji_dziennie

    pokrycie = pokrycie_atrybucji_dziennie(
        start_date, end_date, station=station)['summary']

    # Osobogodziny CAŁEJ hali — bez filtra stanowiska i bez filtra pracownika.
    # Wcześniej ta liczba brała się z tego samego dictu `minuty` co kafelek
    # obok, więc obie były z definicji identyczne (blok `braki` dopisuje do
    # tabeli każdego pracownika z sesją, więc zbiory kluczy są równe) — a przy
    # filtrze stanowiska kafelek podpisany „na hali" pokazywał godziny jednego
    # stanowiska: zmierzone 2026-08-12 „Składanie - lite" 5.4 h przy 24.5 h
    # przepracowanych na hali. Teraz to dwie RÓŻNE liczby o dwóch różnych
    # definicjach, zgodne z podpisami.
    minuty_hali = (sum(czas_pracy(start_date, end_date).values())
                   if (station and station != 'all') or worker_id
                   else sum(minuty.values()))

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'station': station or 'all',
        'worker_id': worker_id,
        'rows': wiersze,
        'unassigned': nieprzypisane,
        'worker_totals': podsumowanie_pracownikow,
        'daily_totals': podsumowanie_dzienne,
        'summary': {
            'pieces': zaokr_wklad(sztuki_przypisane),
            'm3': _zaokraglij(sum(w['m3'] for w in wiersze), 3),
            # Godziny liczone z TEGO SAMEGO zbioru pracowników co tabela niżej,
            # czyli z aktywnym filtrem stanowiska. Kafelek ma się zgadzać
            # z kolumną „Godziny" zsumowaną wzrokiem; osobogodziny CAŁEJ hali
            # (bez filtra) jadą osobno jako session_*_all.
            'minutes': sum(p['minutes'] for p in podsumowanie_pracownikow),
            'hours': _zaokraglij(
                sum(p['minutes'] for p in podsumowanie_pracownikow) / 60, 1),
            'session_minutes_all': minuty_hali,
            'session_hours_all': _zaokraglij(minuty_hali / 60, 1),
            'workers_count': len(podsumowanie_pracownikow),
            'open_sessions': sum(otwarte.values()),
            # Liczba ZDARZEŃ, nie ich wypadkowa: doba, w której tyle samo
            # odhaczono, co cofnięto, ma netto 0 i bez tego pola front pisał
            # o niej „nic nie zarejestrowano". Patrz liczba_eventow_pracy().
            'station_events': liczba_eventow_pracy(start_date, end_date, station),
            'unassigned_pieces': zaokr_wklad(sztuki_nieprzypisane),
            'unassigned_m3': _zaokraglij(sum(w['m3'] for w in nieprzypisane), 3),
            # Ile produkcji w tym okresie wiadomo komu przypisać. Ten jeden
            # procent mówi, na ile raportowi w ogóle można ufać.
            #
            # UWAGA: to pokrycie CAŁEJ produkcji w zakresie (z filtrem
            # stanowiska), a nie udział wybranego pracownika — przy
            # worker_id=... liczba się NIE zmienia i tak ma być. „Ile roboty
            # ma podpis" nie zależy od tego, czyj wiersz ktoś właśnie ogląda.
            'attribution_coverage_pct': pokrycie['coverage_pct'],
        },
    }


def get_workers_for_products(product_ids):
    """
    {product_id: {station_code: ['Adam K.', 'Bartek N.']}} — kto pracował
    przy danym produkcie na danym stanowisku.

    JEDNO zapytanie na całą stronę listy produktów, nie jedno na produkt
    (§7.3). Przy pustej liście nie odpytujemy bazy w ogóle.
    """
    if not product_ids:
        return {}

    wiersze = db.session.query(
        ProductionStationEvent.production_item_id,
        ProductionStationEvent.station_code,
        ProductionWorker.first_name,
        ProductionWorker.last_name,
    ).join(
        ProductionStationEventWorker,
        ProductionStationEventWorker.event_id == ProductionStationEvent.id,
    ).join(
        ProductionWorker,
        ProductionWorker.id == ProductionStationEventWorker.worker_id,
    ).filter(
        ProductionStationEvent.production_item_id.in_(list(product_ids)),
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).distinct().all()

    wynik = {}
    for produkt_id, kod, imie, nazwisko in wiersze:
        inicjal = f'{nazwisko[0]}.' if nazwisko else ''
        etykieta = f'{imie} {inicjal}'.strip()
        na_stanowisku = wynik.setdefault(produkt_id, {}).setdefault(kod, [])
        if etykieta not in na_stanowisku:
            na_stanowisku.append(etykieta)

    for stanowiska in wynik.values():
        for nazwiska in stanowiska.values():
            nazwiska.sort()

    return wynik
