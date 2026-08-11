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

import hashlib
import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger

from ..models import (
    ProductionConfig, ProductionDevice, ProductionWorker, ProductionWorkerSession,
    get_local_now,
)
from . import station_catalog
from .config_service import get_config, invalidate_config_cache

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


# Nazwy stanowisk mają JEDNO źródło — station_catalog. Re-eksport, żeby
# dotychczasowi wołający worker_service.station_label() nie musieli się zmieniać.
station_label = station_catalog.station_label


def station_choices():
    """
    [(kod, nazwa)] do formularza pracownika — pełna lista stanowisk produkcyjnych
    RAZEM z lakiernią i trakownią.

    Wcześniej lista pomijała 'painting', więc nie dało się nikogo przypisać do
    stanowiska, po którym raport pozwalał filtrować.
    """
    return station_catalog.station_choices(include_sawmill=True)


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


# MAX(prod_config.updated_at) zaobserwowany ostatnio w TYM procesie. Passenger
# trzyma kilka procesów i każdy ma własny ProductionConfigService z 60-minutowym
# cache, invalidowany tylko tam, gdzie wykonano set_config.
_ostatnia_wersja_konfiguracji = None


def odswiez_konfiguracje_jesli_nieaktualna():
    """
    Wymusza przeładowanie konfiguracji, gdy prod_config zmienił się poza tym
    procesem. Jeden lekki SELECT MAX(updated_at) przed odpowiedzią.

    Bez tego kill-switch potrafił nie dojechać na tablety wcale: zmiana szła
    z panelu obsługiwanego przez proces B, a proces A serwujący /workers do
    końca swojego 60-minutowego cache oddawał STARĄ wartość — przy ETagu
    liczonym prosto z bazy, czyli już NOWYM. Tablet zapisywał starą wartość
    pod nowym ETagiem i od następnego żądania dostawał 304, więc zostawał
    na niej także po wygaśnięciu cache w procesie A.

    Dziś ETag liczymy z WARTOŚCI (get_config_fingerprint), więc ciało i ETag
    nie mogą się rozjechać; ta funkcja zdejmuje drugą połowę problemu, czyli
    opóźnienie do 60 minut, po którym kill-switch dopiero by ruszył.
    """
    global _ostatnia_wersja_konfiguracji

    wersja = db.session.query(func.max(ProductionConfig.updated_at)).scalar()
    if wersja != _ostatnia_wersja_konfiguracji:
        _ostatnia_wersja_konfiguracji = wersja
        invalidate_config_cache()
    return wersja


def get_config_fingerprint():
    """
    Odcisk WARTOŚCI konfiguracji trafiających do katalogu — segment ETagu.

    Liczony z tego, co faktycznie idzie w ciele, a nie z MAX(prod_config
    .updated_at). Znacznik czasu zawodził na trzy sposoby naraz: miał
    rozdzielczość sekundy (dwie zmiany w tej samej sekundzie = ten sam ETag,
    czyli druga nieosiągalna dla tabletu na zawsze), kolumna jest `datetime
    NULL` bez ON UPDATE (zmiana surowym SQL-em nie ruszała ETagu), a wartości
    w ciele i tak brał inny mechanizm niż ETag.
    """
    cfg = get_worker_config()
    surowe = '|'.join(f'{klucz}={cfg[klucz]}' for klucz in sorted(cfg))
    return hashlib.sha1(surowe.encode('utf-8')).hexdigest()[:12]


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


def build_mobile_catalog(station_code=None, avatar_base_url=None, catalog_version=None):
    """
    Katalog + pełna konfiguracja — apka nie hardkoduje żadnej z tych wartości.

    catalog_version podaje router: to DOKŁADNIE ten sam string, który idzie
    w nagłówku ETag. Apka odsyła pole `catalog_version` (nie nagłówek) jako
    If-None-Match, więc muszą być tożsame — inaczej warunkowy GET nigdy nie
    trafia. Patrz docstring workers_catalog().
    """
    pracownicy = list_workers(include_inactive=False)
    ostatnio = _workers_recent_on_station(station_code)

    dane = get_worker_config()
    dane['catalog_version'] = catalog_version or get_catalog_version()
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

def _open_conflicting_sessions(device_id, worker_ids):
    """
    Otwarte sesje kolidujące z nowym startem — suma DWÓCH zakresów:

      1. sesje TEGO urządzenia — zmiana obsady na tablecie kończy poprzednią
         sesję, niezależnie od tego, kto na niej wisiał;
      2. sesje WSKAZANYCH pracowników na DOWOLNYM urządzeniu — wariant A
         kolizji z decyzji zespołu mobilnego z 11.08.2026: jeden tablet =
         jeden pracownik, więc jeden pracownik = maksymalnie jedna otwarta
         sesja. Gdy ten sam profil zostanie wskazany na drugim tablecie,
         serwer domyka poprzednią zamiast pozwolić na dwie naraz.

    Bez punktu 2 pracownik wisiał na dwóch stanowiskach jednocześnie: panel
    "kto na hali" pokazywał go dwa razy, raport wydajności liczył nakładające
    się minuty podwójnie, a stary tablet nigdy nie wracał na bramkę wyboru
    (jego /sessions/active dalej zwracał session_group).
    """
    warunki = []
    if device_id:
        warunki.append(ProductionWorkerSession.device_id == device_id)
    if worker_ids:
        warunki.append(ProductionWorkerSession.worker_id.in_(list(worker_ids)))
    if not warunki:
        return []

    return ProductionWorkerSession.query.filter(
        ProductionWorkerSession.ended_at.is_(None),
        or_(*warunki),
    ).order_by(ProductionWorkerSession.started_at.asc()).all()


def _nastepczyni_pracownika(worker_ids, poczatek, grupa):
    """
    started_at NAJWCZEŚNIEJSZEJ sesji TYCH pracowników nowszej niż `poczatek`,
    OTWARTEJ LUB ZAMKNIĘTEJ (z pominięciem tej samej grupy). None = nikt ich
    w międzyczasie nie przejął.

    Dokładka do zbioru otwartych kolizji, nie zamiennik. Sesja domknięta
    w międzyczasie (brygadzista z panelu, nocny cron) też jest dowodem, że ten
    pracownik poszedł dalej — a wśród OTWARTYCH sesji jej nie widać. Bez tego
    start z tabletu, który był offline cały dzień, zakładał wiersz OTWARTY
    wstecz i pracownik wracał na panel „kto na hali" godziny po wyjściu z hali,
    z kilkunastoma godzinami na liczniku.
    """
    if not worker_ids:
        return None

    return db.session.query(func.min(ProductionWorkerSession.started_at)).filter(
        ProductionWorkerSession.worker_id.in_(list(worker_ids)),
        ProductionWorkerSession.started_at > poczatek,
        ProductionWorkerSession.session_group != grupa,
    ).scalar()


def start_session(worker_ids, station_code, *, device_id=None, session_group=None,
                  started_at=None, source='mobile', commit=True):
    """
    Start sesji dla N pracowników (praca zespołowa = N wierszy, jeden session_group).

    session_group przychodzi Z APKI — sesja startuje offline i UUID jest tam
    kluczem głównym encji w Room. Serwer generuje własny tylko dla panelu CRM.

    started_at przycinamy do min(client, now): tablet mógł mieć rozjechany
    zegar, a sesji z przyszłości nie przyjmujemy. work_date liczymy serwerowo.

    Dwa pytania, celowo rozdzielone — ich sklejenie było źródłem błędu, w
    którym wskazany pracownik kończył z ZEREM sesji:

      1. „czy ten start jest spóźniony" — decyduje istnienie NOWSZEJ sesji
         (otwarte kolizje urządzenia i pracowników + zamknięte sesje samych
         pracowników). Odpowiedź „tak" znaczy tylko tyle, że nowa sesja jest
         HISTORYCZNA;
      2. „które sesje domknąć" — dopiero gdy odpowiedź na (1) brzmi „nie",
         czyli gdy obsada naprawdę się zmienia. Start spóźniony nie domyka
         niczego, bo sam nie wchodzi na halę.

    Zwracamy listę utworzonych sesji — gdy przyszły JUŻ DOMKNIĘTE
    (`not sesja.is_open`), znaczy to, że żądanie było SPÓŹNIONE i nie objęło
    obsady; wołający ma wtedy oddać apce stan bieżący, a nie stan z żądania.

    commit=False dla handlerów pod @with_idempotency — ten dekorator zapisuje
    odpowiedź i wykonuje commit sam, w jednej transakcji z akcją.
    """
    pracownicy = validate_worker_ids(worker_ids)

    teraz = get_local_now()
    poczatek = min(started_at, teraz) if started_at else teraz
    grupa = session_group or str(uuid.uuid4())

    ids_pracownikow = [w.id for w in pracownicy]

    # Ta sama grupa już jest w bazie: to powtórka startu z kolejki offline
    # (retry z innym X-Operation-Id albo bez nagłówka idempotencji). Drugi
    # komplet wierszy dla tego samego UUID podwoiłby czas pracy w raporcie,
    # więc oddajemy to, co już jest. Patrzymy też na wiersze ZAMKNIĘTE — start
    # spóźniony księguje się od razu domknięty, a bez tego jego powtórka
    # zakładałaby kolejną kopię sesji historycznej.
    istniejaca_grupa = ProductionWorkerSession.query.filter_by(
        session_group=grupa).order_by(ProductionWorkerSession.id.asc()).all()
    if istniejaca_grupa:
        logger.info("Powtórka startu tej samej grupy — bez nowych sesji", extra={
            'session_group': grupa, 'device_id': device_id,
        })
        return istniejaca_grupa

    # SPÓŹNIONY START. session_group generuje apka, a SESSION_START potrafi
    # dojść godzinami później (tablet był offline). Gdyby taki start przejął
    # obsadę, pracownik "wróciłby" na tablet, przy którym już nie stoi, a
    # sesja domykana wstecz dostałaby ended_at < started_at, czyli ujemny czas
    # pracy w panelu.
    #
    # Wybór: żądania NIE odrzucamy (4xx zablokowałoby kolejkę offline — u nich
    # 409 znaczy "wpis do interwencji biura") i nie zmieniamy obsady. Zapisujemy
    # je jako sesję HISTORYCZNĄ, od razu domkniętą w momencie startu następczyni.
    # Alternatywa "nie zapisuj nic" gubiłaby czas pracy: akcje z tej samej
    # kolejki i tak wejdą (idą po X-Worker-Ids), więc raport miałby sztuki bez
    # minut, a tempo szłoby w kosmos. Apka dostaje 200 ze stanem bieżącym
    # i domyka rozjazd przez /sessions/active.
    #
    # Dwa sygnały "ktoś już jest nowszy", brany najwcześniejszy z nich:
    #   1. otwarte kolizje URZĄDZENIA i pracowników — reguła kolejności z pisma
    #      zespołu mobilnego, więc świeża obsada tabletu wygrywa z wpisem
    #      z kolejki nawet wtedy, gdy wpis dotyczy innego człowieka;
    #   2. sesje WSKAZANYCH pracowników również ZAMKNIĘTE — patrz
    #      _nastepczyni_pracownika.
    kolidujace = _open_conflicting_sessions(device_id, ids_pracownikow)
    kandydaci = [s.started_at for s in kolidujace if s.started_at > poczatek]
    nastepczyni = _nastepczyni_pracownika(ids_pracownikow, poczatek, grupa)
    if nastepczyni:
        kandydaci.append(nastepczyni)

    koniec_historyczny = min(kandydaci) if kandydaci else None
    powod_historyczny = 'replaced' if koniec_historyczny else None

    # Start z POPRZEDNIEJ doby, którego nikt nie zastąpił (tablet był offline
    # cały dzień). Bez tego wiersz powstawał OTWARTY wstecz: pracownik pojawiał
    # się dziś na panelu "kto na hali" z kilkunastoma godzinami na liczniku,
    # a czas pracy leciał do teraz. Domykamy go tam, gdzie domknąłby go cron —
    # na nocnym cutoffie jego doby (ta sama reguła co close_stale_sessions).
    if koniec_historyczny is None:
        granica_nocna = datetime.combine(poczatek.date(), get_night_cutoff())
        if teraz > granica_nocna and poczatek < granica_nocna:
            koniec_historyczny = granica_nocna
            powod_historyczny = 'night_cutoff'

    zastapione = 0
    if koniec_historyczny is None:
        # Obsada faktycznie się zmienia — dopiero teraz wolno domykać kolizje.
        # Na ścieżce spóźnionej NIE domykamy NICZEGO. Dawniej domykaliśmy tam
        # kolizje starsze od `poczatek`, przez co wskazany pracownik tracił
        # sesję, którą realnie miał na innym tablecie, i zostawał z zerem:
        # nowa nie wchodziła na halę (jest historyczna), a stara właśnie
        # zniknęła.
        for sesja in kolidujace:
            # Gdy nowy start jest STARSZY niż domykana sesja (zegar tabletu do
            # tyłu albo wpis z kolejki), koniec == started_at dałby 0 minut
            # i skasował faktycznie przepracowany czas. Kończymy wtedy w chwili
            # dotarcia żądania, bo właśnie wtedy nastąpiła zmiana obsady.
            koniec = poczatek if poczatek > sesja.started_at else teraz
            if sesja.close('replaced', koniec):
                zastapione += 1

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
            ended_at=koniec_historyczny,
            end_reason=powod_historyczny,
        )
        db.session.add(sesja)
        sesje.append(sesja)

    if device_id and not koniec_historyczny:
        urzadzenie = ProductionDevice.query.filter_by(device_id=device_id).first()
        # Spóźniony start nie cofa znacznika — to "kiedy ostatnio ktoś siadł
        # do tego tabletu", a nie "kiedy przyszło ostatnie żądanie".
        if urzadzenie and (urzadzenie.last_worker_session_at is None
                           or urzadzenie.last_worker_session_at < poczatek):
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
        'spozniony_start': bool(koniec_historyczny),
    })
    return sesje


def _skoryguj_koniec_zastapionej(sesja, ended_at):
    """
    Skraca ended_at sesji domkniętej przez SERWER jako 'replaced', gdy tablet
    przysłał wcześniejszy, prawdziwy koniec. Powód zostaje nietknięty.

    'replaced' to nasze ZGADNIĘCIE: „skoro pracownik pojawił się gdzie indziej,
    poprzednią sesję kończymy w chwili startu następczyni". Gdy tablet po
    odzyskaniu sieci dosyła SESSION_END z faktyczną godziną wyjścia, jest ona
    bliższa prawdzie — bez tej korekty raport dopisywał człowiekowi cały czas
    między realnym wyjściem a przejęciem profilu (przy tablecie offline od
    poprzedniego dnia: do nocnego cutoffu włącznie).

    Wymóg (c) zespołu mobilnego mówi „nie nadpisujcie POWODU" — i nie
    nadpisujemy. Czasu nie dotyczy, a idempotentne close() samo z siebie nie
    poprawi wartości, bo widzi tylko ended_at IS NULL.

    Skracamy wyłącznie w oknie [started_at, obecny ended_at): koniec spoza
    sesji byłby danymi śmieciowymi, a wydłużanie oznaczałoby cofnięcie
    przejęcia profilu, którego nie robimy nigdy.
    """
    if ended_at is None or sesja.end_reason != 'replaced' or sesja.ended_at is None:
        return False
    if not (sesja.started_at <= ended_at < sesja.ended_at):
        return False

    sesja.ended_at = ended_at
    return True


def end_session(session_group, *, ended_at=None, reason='manual', device_id=None,
                commit=True):
    """
    Domyka wszystkie sesje grupy. Zwraca (sesje_grupy, ile_faktycznie_domknięto).

    NIE-OPERACJA zamiast błędu, gdy nie ma czego domykać. Dwa przypadki:

      - grupa jest już zamknięta — close() jest idempotentne, więc spóźniony
        'manual' z kolejki offline NIE nadpisze 'replaced' ustawionego przez
        serwer przy przejęciu profilu;
      - grupy w ogóle nie ma w bazie — dawniej 404. To był realny problem, a nie
        czystość HTTP: end idzie tą samą kolejką offline co start, więc potrafi
        dojść PRZED swoim startem (albo po czyszczeniu danych), a u klienta
        każde 4xx to wpis wyrzucony z kolejki albo czekający na interwencję
        biura. Domknięcie nieistniejącej sesji jest bezstanowe — nie ma czego
        zepsuć, więc nie ma o czym informować błędem.

    Nadal 422 dla 'replaced'/'admin': to powody zastrzeżone dla backendu, a
    przysłanie ich świadczy o błędzie klienta, nie o wyścigu kolejki.
    """
    if reason not in ProductionWorkerSession.CLIENT_END_REASONS:
        raise WorkerError(422, 'invalid_end_reason',
                          f"Dozwolone: {sorted(ProductionWorkerSession.CLIENT_END_REASONS)}")

    sesje = ProductionWorkerSession.query.filter_by(session_group=session_group).all()

    koniec = ended_at or get_local_now()
    domkniete = sum(1 for s in sesje if s.close(reason, koniec))
    skorygowane = sum(1 for s in sesje if _skoryguj_koniec_zastapionej(s, ended_at))
    if commit:
        db.session.commit()

    logger.info("Koniec sesji pracowników", extra={
        'session_group': session_group, 'reason': reason,
        'domkniete': domkniete, 'skorygowane': skorygowane,
        'device_id': device_id, 'nieznana_grupa': not sesje,
    })
    return sesje, domkniete


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
        # started_at < granica: sesja zaczęta PO nocnym cutoffie (druga zmiana
        # wchodząca o 23:30 przy cutoffie 23:00) należy już do następnej doby
        # i nie wolno jej ubić przy najbliższym przebiegu crona z czasem 0 min.
        if teraz > granica_nocna and sesja.started_at < granica_nocna:
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

def sessions_output(sesje):
    """
    {session_id: {'pieces': x, 'm3': y}} — ile zrobiono W TEJ sesji.

    Jedno zapytanie dla całej listy. Spec §7.1 wymagała „roboty w tej sesji",
    bez niej panel jest listą zalogowanych, a nie obrazem hali: nie widać
    różnicy między kimś, kto pracuje, a kimś, kto tylko się zalogował.
    """
    from ..models import ProductionProduct, ProductionStationEvent, ProductionStationEventWorker

    identyfikatory = [s.id for s in sesje if s.id]
    if not identyfikatory:
        return {}

    wiersze = db.session.query(
        ProductionStationEventWorker.session_id,
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
        ProductionStationEventWorker.session_id.in_(identyfikatory),
        # Ten sam filtr co w raportach — eventy automatu nie są niczyją pracą
        ~ProductionStationEvent.source.in_(('auto_skip', 'system')),
    ).group_by(ProductionStationEventWorker.session_id).all()

    return {
        sid: {'pieces': round(float(sztuki or 0), 1), 'm3': round(float(metry or 0), 3)}
        for sid, sztuki, metry in wiersze
    }


def serialize_session_for_panel(sesja, wynik=None):
    """
    wynik: wpis z sessions_output() — gdy podany, panel pokazuje dorobek sesji.
    """
    teraz = get_local_now()
    bezczynnosc = None
    if sesja.last_activity_at:
        bezczynnosc = max(0, int((teraz - sesja.last_activity_at).total_seconds() // 60))

    dorobek = wynik or {}
    return {
        'id': sesja.id,
        'worker_id': sesja.worker_id,
        'worker_name': sesja.worker.full_name if sesja.worker else '—',
        'initials': sesja.worker.initials if sesja.worker else '?',
        'color_hex': sesja.worker.tile_color if sesja.worker else None,
        'station_code': sesja.station_code,
        'station_label': station_label(sesja.station_code),
        'device_id': sesja.device_id,
        'started_at': sesja.started_at.isoformat() if sesja.started_at else None,
        'last_activity_at': (sesja.last_activity_at.isoformat()
                             if sesja.last_activity_at else None),
        'duration_minutes': sesja.duration_minutes,
        # Czas od OSTATNIEJ AKCJI, nie od startu sesji — to jest ta liczba,
        # która odpowiada na pytanie "czy ktoś stoi bezczynnie". Wcześniej
        # kierownik musiał odejmować w pamięci dwie godziny w formacie HH:MM.
        'idle_minutes': bezczynnosc,
        'idle_over_timeout': (bezczynnosc is not None
                              and bezczynnosc >= get_idle_timeout_minutes()),
        'pieces': dorobek.get('pieces', 0),
        'm3': dorobek.get('m3', 0),
        'session_group': sesja.session_group,
    }


def serialize_sessions_for_panel(sesje):
    """Cała lista naraz — dorobek liczony jednym zapytaniem, nie jednym na sesję."""
    wyniki = sessions_output(sesje)
    return [serialize_session_for_panel(s, wyniki.get(s.id)) for s in sesje]


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
