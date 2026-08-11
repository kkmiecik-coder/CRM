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


def _granice(start_date, end_date):
    if start_date > end_date:
        raise ZakresError('Data początkowa musi być wcześniejsza lub równa końcowej')
    if (end_date - start_date).days + 1 > MAKS_ZAKRES_DNI:
        raise ZakresError(f'Maksymalny zakres to {MAKS_ZAKRES_DNI} dni')
    return (datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time()))


def _zaokraglij(wartosc, miejsca=1):
    return round(float(wartosc or 0), miejsca)


def wydajnosc_pracownikow(start_date, end_date, station=None, worker_id=None):
    """
    Wiersze dzień × pracownik × stanowisko.

    Zwraca listę dictów posortowaną po dacie malejąco, potem po nazwisku —
    tak jak ma się wyświetlać w tabeli, żeby front nie musiał sortować.
    """
    poczatek, koniec = _granice(start_date, end_date)

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
            'pieces': _zaokraglij(sztuki),
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
    poczatek, koniec = _granice(start_date, end_date)

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
            'pieces': _zaokraglij(sztuki),
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
    from .worker_service import get_night_cutoff

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

    minuty = {}
    for sesja in zapytanie.all():
        granica_doby = datetime.combine(sesja.work_date, cutoff)
        koniec = min(sesja.ended_at or teraz, teraz, granica_doby)
        trwanie = max(0, int((koniec - sesja.started_at).total_seconds() // 60))
        klucz = (sesja.worker_id, sesja.work_date.isoformat())
        minuty[klucz] = minuty.get(klucz, 0) + trwanie
    return minuty


def raport_wydajnosci(start_date, end_date, station=None, worker_id=None):
    """
    Komplet danych do raportu: wiersze, sumy per pracownik, sumy dzienne,
    praca nieprzypisana i podsumowanie okresu.

    Tempo = m³ / (minuty / 60). Liczymy je tylko tam, gdzie jest zmierzony
    czas pracy — bez sesji tempo byłoby dzieleniem przez zero, a nie zerem.
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

    for (wid, _dzien), minut in minuty.items():
        wpis = per_pracownik.get(wid)
        if wpis is not None:
            wpis['minutes'] += minut

    podsumowanie_pracownikow = []
    for wpis in per_pracownik.values():
        godziny = wpis['minutes'] / 60 if wpis['minutes'] else 0
        podsumowanie_pracownikow.append({
            'worker_id': wpis['worker_id'],
            'worker_name': wpis['worker_name'],
            'pieces': _zaokraglij(wpis['pieces']),
            'm3': _zaokraglij(wpis['m3'], 3),
            'minutes': wpis['minutes'],
            'hours': _zaokraglij(godziny, 1),
            'stations': sorted(wpis['stations']),
            'pace_m3_per_hour': _zaokraglij(wpis['m3'] / godziny, 3) if godziny else None,
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
          'pieces': _zaokraglij(w['pieces']),
          'm3': _zaokraglij(w['m3'], 3)} for w in per_dzien.values()),
        key=lambda w: w['work_date'])

    sztuki_nieprzypisane = sum(w['pieces'] for w in nieprzypisane)
    sztuki_przypisane = sum(w['pieces'] for w in wiersze)
    razem = sztuki_przypisane + sztuki_nieprzypisane

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
            'pieces': _zaokraglij(sztuki_przypisane),
            'm3': _zaokraglij(sum(w['m3'] for w in wiersze), 3),
            # Godziny liczone z TEGO SAMEGO zbioru pracowników co tabela niżej.
            # Suma wszystkich sesji w zakresie pokazywałaby czas ludzi, których
            # w tabeli nie ma (pracowali bez wybranego profilu albo na innym
            # stanowisku niż filtrowane) — kafelek kłóciłby się z tabelą pod nim.
            # Pełne osobogodziny na hali są osobno, pod własną nazwą.
            'minutes': sum(p['minutes'] for p in podsumowanie_pracownikow),
            'hours': _zaokraglij(
                sum(p['minutes'] for p in podsumowanie_pracownikow) / 60, 1),
            'session_minutes_all': sum(minuty.values()),
            'session_hours_all': _zaokraglij(sum(minuty.values()) / 60, 1),
            'workers_count': len(podsumowanie_pracownikow),
            'unassigned_pieces': _zaokraglij(sztuki_nieprzypisane),
            'unassigned_m3': _zaokraglij(sum(w['m3'] for w in nieprzypisane), 3),
            # Ile produkcji w tym okresie wiadomo komu przypisać. Ten jeden
            # procent mówi, na ile raportowi w ogóle można ufać.
            'attribution_coverage_pct': _zaokraglij(
                100 * sztuki_przypisane / razem, 1) if razem else None,
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
