# modules/production/services/worker_service.py
"""
Profile pracowników produkcji — katalog, sesje pracy, atrybucja.

Projekt: docs/worker-profiles-backend.md (§4-§6)

Trzy rzeczy w jednym miejscu, bo trzymają się tej samej encji:
  1. katalog pracowników (CRUD z panelu CRM, katalog dla tabletu),
  2. sesje pracy (start/koniec/domykanie po czasie),
  3. walidacja nagłówka X-Worker-Ids i rozwiązanie atrybucji.

Czego tu NIE ma świadomie:
  - liczenia share — to robi models.attach_worker_attribution() przy tworzeniu
    eventu, żeby atrybucja powstawała w tej samej transakcji co event,
  - raportów wydajności — to osobny worker_stats_service (etap 6).
"""

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger

from ..models import (
    ProductionDevice, ProductionWorker, ProductionWorkerSession, get_local_now,
)
from .config_service import get_config

logger = get_structured_logger('production.workers')


# ============================================================================
# KONFIGURACJA
# ============================================================================

# Domyślne wartości muszą być identyczne z migracją 2026-08-11-worker-config-keys.sql.
# Powielenie jest celowe: gdy klucza w bazie nie ma (świeże środowisko, ktoś go
# skasował), API i tak ma odpowiedzieć sensowną wartością zamiast wywalić się
# na None. Kill-switch domyślnie WYŁĄCZONY — patrz docstring is_selection_required().
DOMYSLNA_KONFIGURACJA = {
    'WORKER_SELECTION_REQUIRED': False,
    'WORKER_SESSION_IDLE_TIMEOUT_MINUTES': 120,
    'WORKER_SESSION_NIGHT_CUTOFF': '23:00',
    'WORKER_QUICK_PICK_COUNT': 8,
}

# Ile dni wstecz liczy się jako "ostatnio pracował na tym stanowisku"
# dla sekcji szybkiego wyboru na tablecie.
DNI_SZYBKIEGO_WYBORU = 7


class WorkerError(Exception):
    """
    Błąd walidacji do zamiany na odpowiedź HTTP. Kody i statusy są kontraktem
    z apką (docs/worker-profiles-backend.md §6.6) — apka reaguje na nie różnie:
    400/409 wyrzucają na ekran wyboru i ZOSTAWIAJĄ akcję w kolejce, 422 kasuje.
    """

    def __init__(self, status_code, error_code, detail=None):
        super().__init__(error_code)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail

    def as_response(self):
        payload = {'error': self.error_code}
        if self.detail:
            payload['detail'] = self.detail
        return payload, self.status_code


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_selection_required():
    """
    Kill-switch. False = akcje bez X-Worker-Ids przechodzą normalnie.

    Włączenie bramki zatrzymuje halę, jeśli katalog pracowników przestanie
    działać — dlatego jest w prod_config (zmienialne bez deployu), a nie w kodzie.
    """
    return _to_bool(get_config('WORKER_SELECTION_REQUIRED',
                               DOMYSLNA_KONFIGURACJA['WORKER_SELECTION_REQUIRED']))


def get_idle_timeout_minutes():
    return _to_int(get_config('WORKER_SESSION_IDLE_TIMEOUT_MINUTES',
                              DOMYSLNA_KONFIGURACJA['WORKER_SESSION_IDLE_TIMEOUT_MINUTES']),
                   DOMYSLNA_KONFIGURACJA['WORKER_SESSION_IDLE_TIMEOUT_MINUTES'])


def get_night_cutoff():
    """Zwraca datetime.time; przy śmieciach w konfiguracji wraca do domyślnej."""
    raw = get_config('WORKER_SESSION_NIGHT_CUTOFF',
                     DOMYSLNA_KONFIGURACJA['WORKER_SESSION_NIGHT_CUTOFF'])
    try:
        godzina, minuta = str(raw).strip().split(':')[:2]
        return time(int(godzina), int(minuta))
    except (ValueError, AttributeError):
        logger.warning("Nieprawidłowy WORKER_SESSION_NIGHT_CUTOFF, używam domyślnego",
                       extra={'wartosc': raw})
        return time(23, 0)


def get_quick_pick_count():
    return _to_int(get_config('WORKER_QUICK_PICK_COUNT',
                              DOMYSLNA_KONFIGURACJA['WORKER_QUICK_PICK_COUNT']),
                   DOMYSLNA_KONFIGURACJA['WORKER_QUICK_PICK_COUNT'])


def get_worker_config():
    """Cała konfiguracja w jednym dicie — apka pobiera ją razem z katalogiem."""
    cutoff = get_night_cutoff()
    return {
        'selection_required': is_selection_required(),
        'idle_timeout_minutes': get_idle_timeout_minutes(),
        'night_cutoff': cutoff.strftime('%H:%M'),
        'quick_pick_count': get_quick_pick_count(),
    }


# ============================================================================
# KATALOG
# ============================================================================

def list_workers(include_inactive=False):
    zapytanie = ProductionWorker.query
    if not include_inactive:
        zapytanie = zapytanie.filter(ProductionWorker.is_active.is_(True))
    return zapytanie.order_by(
        ProductionWorker.sort_order.asc(),
        ProductionWorker.last_name.asc(),
        ProductionWorker.first_name.asc(),
    ).all()


def get_catalog_version():
    """
    MAX(updated_at) z katalogu — apka wysyła to jako ETag i pomija pobieranie
    listy, gdy nic się nie zmieniło. Pusty katalog daje stałą wartość, żeby
    ETag nie był None.
    """
    najnowsza = db.session.query(func.max(ProductionWorker.updated_at)).scalar()
    return najnowsza.isoformat() if najnowsza else 'empty'


def _workers_recent_on_station(station_code, dni=DNI_SZYBKIEGO_WYBORU):
    """Zbiór worker_id, które miały sesję na tym stanowisku w ostatnich N dniach."""
    if not station_code:
        return set()
    prog = get_local_now() - timedelta(days=dni)
    wiersze = db.session.query(ProductionWorkerSession.worker_id).filter(
        ProductionWorkerSession.station_code == station_code,
        ProductionWorkerSession.started_at >= prog,
    ).distinct().all()
    return {w[0] for w in wiersze}


def serialize_worker_for_mobile(worker, avatar_base_url=None, recent=False):
    """
    DTO kafelka na tablecie.

    avatar_url zwracamy tylko gdy ktoś kiedyś wgra zdjęcie — dziś kafelki
    rysują inicjały na tile_color i avatar_path jest zawsze NULL. Gdy zdjęcia
    wejdą, URL MUSI być pełny: BASE_URL apki kończy się na /api/mobile/,
    więc ścieżka root-relative by się nie skleiła.
    """
    avatar_url = None
    if worker.avatar_path and avatar_base_url:
        avatar_url = f"{avatar_base_url.rstrip('/')}/{worker.avatar_path.lstrip('/')}"

    return {
        'id': worker.id,
        'first_name': worker.first_name,
        'last_name': worker.last_name,
        'initials': worker.initials,
        'avatar_url': avatar_url,
        'color_hex': worker.tile_color,
        'allowed_stations': worker.allowed_stations_list,
        'recent_on_station': recent,
        'sort_order': worker.sort_order or 0,
    }


def build_mobile_catalog(station_code=None, avatar_base_url=None):
    """Katalog + pełna konfiguracja — apka nie hardkoduje żadnej z tych wartości."""
    pracownicy = list_workers(include_inactive=False)
    ostatnio = _workers_recent_on_station(station_code)

    dane = get_worker_config()
    dane['catalog_version'] = get_catalog_version()
    dane['workers'] = [
        serialize_worker_for_mobile(w, avatar_base_url, recent=w.id in ostatnio)
        for w in pracownicy
    ]
    return dane


# ============================================================================
# CRUD (panel CRM)
# ============================================================================

def _normalize_stations(stations):
    """Lista/CSV kodów stanowisk → CSV albo None (= wszystkie)."""
    if not stations:
        return None
    if isinstance(stations, str):
        stations = stations.split(',')
    kody = [str(s).strip() for s in stations if str(s).strip()]
    nieznane = [k for k in kody if k not in ProductionDevice.VALID_STATION_CODES]
    if nieznane:
        raise WorkerError(422, 'invalid_station_code', f"Nieznane stanowiska: {nieznane}")
    return ','.join(kody) if kody else None


def _normalize_color(color):
    if not color:
        return None
    color = str(color).strip()
    if not color.startswith('#'):
        color = '#' + color
    if len(color) != 7:
        raise WorkerError(422, 'invalid_color', 'Kolor musi być w formacie #RRGGBB')
    return color.upper()


def create_worker(first_name, last_name, *, color_hex=None, allowed_stations=None,
                  sort_order=0, user_id=None, worker_code=None):
    if not (first_name or '').strip() or not (last_name or '').strip():
        raise WorkerError(422, 'invalid_name', 'Imię i nazwisko są wymagane')

    worker = ProductionWorker(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        color_hex=_normalize_color(color_hex),
        allowed_stations=_normalize_stations(allowed_stations),
        sort_order=_to_int(sort_order, 0),
        user_id=user_id or None,
        worker_code=(worker_code or '').strip() or None,
        is_active=True,
    )
    db.session.add(worker)
    db.session.commit()
    logger.info("Dodano pracownika", extra={'worker_id': worker.id,
                                            'nazwisko': worker.full_name})
    return worker


def update_worker(worker_id, **pola):
    worker = ProductionWorker.query.get(worker_id)
    if not worker:
        raise WorkerError(404, 'worker_not_found', f'Brak pracownika o id={worker_id}')

    if 'first_name' in pola or 'last_name' in pola:
        imie = (pola.get('first_name', worker.first_name) or '').strip()
        nazwisko = (pola.get('last_name', worker.last_name) or '').strip()
        if not imie or not nazwisko:
            raise WorkerError(422, 'invalid_name', 'Imię i nazwisko są wymagane')
        worker.first_name, worker.last_name = imie, nazwisko

    if 'color_hex' in pola:
        worker.color_hex = _normalize_color(pola['color_hex'])
    if 'allowed_stations' in pola:
        worker.allowed_stations = _normalize_stations(pola['allowed_stations'])
    if 'sort_order' in pola:
        worker.sort_order = _to_int(pola['sort_order'], worker.sort_order or 0)
    if 'user_id' in pola:
        worker.user_id = pola['user_id'] or None
    if 'worker_code' in pola:
        worker.worker_code = (pola['worker_code'] or '').strip() or None

    db.session.commit()
    logger.info("Zaktualizowano pracownika", extra={'worker_id': worker.id})
    return worker


def deactivate_worker(worker_id):
    """
    Dezaktywacja zamiast kasowania (§4.1). Domyka też otwarte sesje — inaczej
    zwolniony pracownik wisiałby w panelu "kto na hali" do nocnego cutoffu.
    """
    worker = ProductionWorker.query.get(worker_id)
    if not worker:
        raise WorkerError(404, 'worker_not_found', f'Brak pracownika o id={worker_id}')

    worker.deactivate()
    otwarte = ProductionWorkerSession.query.filter(
        ProductionWorkerSession.worker_id == worker_id,
        ProductionWorkerSession.ended_at.is_(None),
    ).all()
    for sesja in otwarte:
        sesja.close('admin')

    db.session.commit()
    logger.info("Dezaktywowano pracownika", extra={'worker_id': worker_id,
                                                   'domkniete_sesje': len(otwarte)})
    return worker


def reactivate_worker(worker_id):
    worker = ProductionWorker.query.get(worker_id)
    if not worker:
        raise WorkerError(404, 'worker_not_found', f'Brak pracownika o id={worker_id}')
    worker.reactivate()
    db.session.commit()
    return worker


# ============================================================================
# WALIDACJA X-Worker-Ids
# ============================================================================

def parse_worker_ids_header(raw):
    """
    '3,7' → [3, 7]. Zwraca None gdy nagłówka NIE MA — to nie to samo co pusty.

    Rozróżnienie jest istotne: brak nagłówka przy włączonej bramce to 400
    (apka ma wyrzucić na ekran wyboru i zachować akcję w kolejce), a nagłówek
    pusty albo ze śmieciami to 422 (apka ma skasować wpis, bo retry nie pomoże).
    """
    if raw is None:
        return None
    surowe = [c.strip() for c in str(raw).split(',') if c.strip()]
    if not surowe:
        raise WorkerError(422, 'invalid_worker_ids', 'Pusty nagłówek X-Worker-Ids')
    try:
        identyfikatory = [int(c) for c in surowe]
    except ValueError:
        raise WorkerError(422, 'invalid_worker_ids',
                          'X-Worker-Ids musi być listą liczb rozdzielonych przecinkiem')
    if any(i <= 0 for i in identyfikatory):
        raise WorkerError(422, 'invalid_worker_ids', 'Identyfikatory muszą być dodatnie')
    return list(dict.fromkeys(identyfikatory))


def validate_worker_ids(worker_ids):
    """
    Sprawdza istnienie i aktywność. Zwraca listę ProductionWorker w kolejności
    z nagłówka — pierwszy element trafia do jednokolumnowego audytu
    (prod_product_events.worker_id, prod_rework_log.worker_id).
    """
    if not worker_ids:
        raise WorkerError(422, 'invalid_worker_ids', 'Pusta lista pracowników')

    znalezieni = {w.id: w for w in ProductionWorker.query.filter(
        ProductionWorker.id.in_(worker_ids)).all()}

    brakujace = [i for i in worker_ids if i not in znalezieni]
    if brakujace:
        raise WorkerError(404, 'worker_not_found', f'Nieznani pracownicy: {brakujace}')

    nieaktywni = [i for i in worker_ids if not znalezieni[i].is_active]
    if nieaktywni:
        raise WorkerError(409, 'worker_inactive', f'Pracownicy nieaktywni: {nieaktywni}')

    return [znalezieni[i] for i in worker_ids]


def resolve_worker_ids(raw_header, *, required=None):
    """
    Pełna ścieżka nagłówka → lista id. Zwraca [] gdy bramka wyłączona i apka
    nagłówka nie przysłała.
    """
    if required is None:
        required = is_selection_required()

    worker_ids = parse_worker_ids_header(raw_header)
    if worker_ids is None:
        if required:
            raise WorkerError(400, 'worker_ids_required',
                              'Nagłówek X-Worker-Ids jest wymagany')
        return []

    validate_worker_ids(worker_ids)
    return worker_ids


# ============================================================================
# SESJE
# ============================================================================

def _close_device_sessions(device_id, reason='replaced', ended_at=None):
    """Domyka wszystkie otwarte sesje urządzenia. Zwraca liczbę domkniętych."""
    if not device_id:
        return 0
    otwarte = ProductionWorkerSession.query.filter(
        ProductionWorkerSession.device_id == device_id,
        ProductionWorkerSession.ended_at.is_(None),
    ).all()
    for sesja in otwarte:
        sesja.close(reason, ended_at)
    return len(otwarte)


def start_session(worker_ids, station_code, *, device_id=None, session_group=None,
                  started_at=None, source='mobile', commit=True):
    """
    Start sesji dla N pracowników (praca zespołowa = N wierszy, jeden session_group).

    session_group przychodzi Z APKI — sesja startuje offline i UUID jest tam
    kluczem głównym encji w Room. Serwer generuje własny tylko dla panelu CRM.

    started_at przycinamy do min(client, now): tablet mógł mieć rozjechany
    zegar, a sesji z przyszłości nie przyjmujemy. work_date liczymy serwerowo.

    commit=False dla handlerów pod @with_idempotency — ten dekorator zapisuje
    odpowiedź i wykonuje commit sam, w jednej transakcji z akcją.
    """
    pracownicy = validate_worker_ids(worker_ids)

    teraz = get_local_now()
    poczatek = min(started_at, teraz) if started_at else teraz
    grupa = session_group or str(uuid.uuid4())

    # Zmiana obsady to KONIEC poprzedniej sesji, nie jej modyfikacja.
    zastapione = _close_device_sessions(device_id, 'replaced', poczatek)

    sesje = []
    for worker in pracownicy:
        sesja = ProductionWorkerSession(
            worker_id=worker.id,
            station_code=station_code,
            device_id=device_id,
            session_group=grupa,
            started_at=poczatek,
            last_activity_at=poczatek,
            work_date=poczatek.date(),
            source=source,
        )
        db.session.add(sesja)
        sesje.append(sesja)

    if device_id:
        urzadzenie = ProductionDevice.query.filter_by(device_id=device_id).first()
        if urzadzenie:
            urzadzenie.last_worker_session_at = poczatek

    if commit:
        db.session.commit()
    else:
        # Bez id-ków odpowiedź nie miałaby czego zwrócić, a commit zrobi dekorator.
        db.session.flush()

    logger.info("Start sesji pracowników", extra={
        'session_group': grupa,
        'station_code': station_code,
        'device_id': device_id,
        'worker_ids': [w.id for w in pracownicy],
        'zastapione_sesje': zastapione,
    })
    return sesje


def end_session(session_group, *, ended_at=None, reason='manual', device_id=None,
                commit=True):
    """
    Domyka wszystkie sesje grupy. Idempotentne — powtórka po retry z kolejki
    offline nie zmienia już zamkniętych sesji i nie jest błędem.
    """
    if reason not in ProductionWorkerSession.CLIENT_END_REASONS:
        raise WorkerError(422, 'invalid_end_reason',
                          f"Dozwolone: {sorted(ProductionWorkerSession.CLIENT_END_REASONS)}")

    sesje = ProductionWorkerSession.query.filter_by(session_group=session_group).all()
    if not sesje:
        raise WorkerError(404, 'session_not_found', f'Brak sesji {session_group}')

    koniec = ended_at or get_local_now()
    domkniete = sum(1 for s in sesje if s.close(reason, koniec))
    if commit:
        db.session.commit()

    logger.info("Koniec sesji pracowników", extra={
        'session_group': session_group, 'reason': reason,
        'domkniete': domkniete, 'device_id': device_id,
    })
    return sesje


def get_active_sessions(device_id=None, station_code=None):
    zapytanie = ProductionWorkerSession.query.options(
        joinedload(ProductionWorkerSession.worker)
    ).filter(ProductionWorkerSession.ended_at.is_(None))

    if device_id:
        zapytanie = zapytanie.filter(ProductionWorkerSession.device_id == device_id)
    if station_code:
        zapytanie = zapytanie.filter(ProductionWorkerSession.station_code == station_code)

    return zapytanie.order_by(ProductionWorkerSession.started_at.asc()).all()


def touch_sessions(worker_ids, station_code=None, device_id=None, when=None):
    """
    Odświeża last_activity_at przy akcji produkcyjnej i zwraca mapę
    {worker_id: session_id} do wpięcia w atrybucję.

    Brak otwartej sesji NIE jest błędem: akcja mogła powstać offline, a sesja
    zamknąć się w międzyczasie nocnym cutoffem. Backend wymaga tylko, żeby
    pracownicy istnieli i byli aktywni (§5.4).
    """
    if not worker_ids:
        return {}

    kiedy = when or get_local_now()
    zapytanie = ProductionWorkerSession.query.filter(
        ProductionWorkerSession.worker_id.in_(worker_ids),
        ProductionWorkerSession.ended_at.is_(None),
    )
    if station_code:
        zapytanie = zapytanie.filter(ProductionWorkerSession.station_code == station_code)
    if device_id:
        zapytanie = zapytanie.filter(ProductionWorkerSession.device_id == device_id)

    mapa = {}
    for sesja in zapytanie.all():
        sesja.last_activity_at = kiedy
        # Przy kilku otwartych sesjach tego pracownika bierzemy najświeższą.
        poprzednia = mapa.get(sesja.worker_id)
        if poprzednia is None or sesja.started_at >= poprzednia[1]:
            mapa[sesja.worker_id] = (sesja.id, sesja.started_at)

    return {worker_id: dane[0] for worker_id, dane in mapa.items()}


def close_stale_sessions(now=None):
    """
    Domyka sesje zapomniane: po nocnym cutoffie i po bezczynności.

    Wołane cronem hostingu (wzorzec: /production/api/sync-cron) — w repo NIE MA
    schedulera, `scheduler_daemon.py` został usunięty. Idempotentne: działa
    wyłącznie na wierszach z ended_at IS NULL.

    ended_at ustawiamy na moment, w którym sesja FAKTYCZNIE powinna była się
    skończyć (cutoff doby / ostatnia aktywność + timeout), nie na czas
    uruchomienia crona — inaczej opóźniony cron zawyżałby czas pracy.
    """
    teraz = now or get_local_now()
    cutoff = get_night_cutoff()
    timeout = timedelta(minutes=get_idle_timeout_minutes())

    otwarte = ProductionWorkerSession.query.filter(
        ProductionWorkerSession.ended_at.is_(None)).all()

    zamkniete = {'night_cutoff': 0, 'idle_timeout': 0}

    for sesja in otwarte:
        granica_nocna = datetime.combine(sesja.work_date, cutoff)
        if teraz > granica_nocna:
            # Sesja nie mogła się zacząć po swoim cutoffie, ale gdyby zegar
            # tabletu spłatał figla — nie cofamy końca przed początek.
            koniec = max(granica_nocna, sesja.started_at)
            if sesja.close('night_cutoff', koniec):
                zamkniete['night_cutoff'] += 1
            continue

        granica_bezczynnosci = sesja.last_activity_at + timeout
        if teraz > granica_bezczynnosci:
            if sesja.close('idle_timeout', granica_bezczynnosci):
                zamkniete['idle_timeout'] += 1

    if any(zamkniete.values()):
        db.session.commit()
        logger.info("Domknięto zapomniane sesje", extra=zamkniete)

    return zamkniete


# ============================================================================
# PANEL "KTO TERAZ NA HALI"
# ============================================================================

def serialize_session_for_panel(sesja):
    return {
        'id': sesja.id,
        'worker_id': sesja.worker_id,
        'worker_name': sesja.worker.full_name if sesja.worker else '—',
        'initials': sesja.worker.initials if sesja.worker else '?',
        'color_hex': sesja.worker.tile_color if sesja.worker else None,
        'station_code': sesja.station_code,
        'device_id': sesja.device_id,
        'started_at': sesja.started_at.isoformat() if sesja.started_at else None,
        'last_activity_at': (sesja.last_activity_at.isoformat()
                             if sesja.last_activity_at else None),
        'duration_minutes': sesja.duration_minutes,
        'session_group': sesja.session_group,
    }


def get_workers_activity_summary(dni=7):
    """
    {worker_id: {'pieces': float, 'm3': float, 'last_activity_at': datetime|None}}
    dla listy w panelu — jedno zapytanie na całą tabelę, nie jedno na wiersz.

    Filtr source NOT IN ('auto_skip','system') jest OBOWIĄZKOWY, nie kosmetyczny
    (§7.2 i pułapka nr 2): to eventy stanowisk POMINIĘTYCH, których nikt
    fizycznie nie wykonał. Bez filtra sklejacz dostałby kredyt za formatowanie,
    którego nie było.

    To skrócona wersja liczenia dla listy pracowników. Pełny raport wydajności
    (dzień × pracownik × stanowisko, tempo, eksport) to osobny
    worker_stats_service — etap 6, jeszcze nieistniejący.
    """
    from ..models import ProductionProduct, ProductionStationEvent, ProductionStationEventWorker

    prog = get_local_now() - timedelta(days=dni)

    robota = db.session.query(
        ProductionStationEventWorker.worker_id,
        func.sum(ProductionStationEvent.delta * ProductionStationEventWorker.share),
        func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                 * ProductionStationEvent.delta * ProductionStationEventWorker.share),
    ).join(
        ProductionStationEvent,
        ProductionStationEvent.id == ProductionStationEventWorker.event_id,
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).filter(
        ProductionStationEvent.created_at >= prog,
        ~ProductionStationEvent.source.in_(('auto_skip', 'system')),
    ).group_by(ProductionStationEventWorker.worker_id).all()

    aktywnosc = db.session.query(
        ProductionWorkerSession.worker_id,
        func.max(ProductionWorkerSession.last_activity_at),
    ).group_by(ProductionWorkerSession.worker_id).all()

    podsumowanie = {}
    for worker_id, sztuki, metry in robota:
        podsumowanie.setdefault(worker_id, {})
        podsumowanie[worker_id]['pieces'] = round(float(sztuki or 0), 1)
        podsumowanie[worker_id]['m3'] = round(float(metry or 0), 3)

    for worker_id, ostatnia in aktywnosc:
        podsumowanie.setdefault(worker_id, {})
        podsumowanie[worker_id]['last_activity_at'] = ostatnia

    return podsumowanie


def find_crm_users(fraza=None, limit=20):
    """
    Konta CRM do opcjonalnego powiązania z profilem (§7.1). Zwraca lekkie dicty —
    formularz potrzebuje tylko id i etykiety.
    """
    from modules.users.models import User

    zapytanie = User.query
    if fraza:
        wzorzec = f'%{fraza.strip()}%'
        zapytanie = zapytanie.filter(User.email.ilike(wzorzec))

    return [
        {'id': u.id,
         'label': getattr(u, 'first_name', None) and f'{u.first_name} ({u.email})' or u.email}
        for u in zapytanie.order_by(User.email.asc()).limit(limit).all()
    ]


def close_session_by_admin(session_id):
    sesja = ProductionWorkerSession.query.get(session_id)
    if not sesja:
        raise WorkerError(404, 'session_not_found', f'Brak sesji o id={session_id}')
    sesja.close('admin')
    db.session.commit()
    logger.info("Brygadzista domknął sesję", extra={'session_id': session_id})
    return sesja
