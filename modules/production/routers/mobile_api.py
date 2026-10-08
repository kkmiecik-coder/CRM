"""
Mobile API router — endpointy REST dla natywnej aplikacji Android.

Blueprint zarejestrowany w app.py pod prefixem `/api/mobile`.
Logika biznesowa w `services/mobile_api_service.py` — router jest cienki.
"""

from datetime import datetime, time, timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import case, func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import (
    ProductionConfig, ProductionDevice, ProductionItem, ProductionOrder, ProductionPackage, ProductionWorker)
from modules.production.utils.cache import (
    cached_json,
    if_none_match,
    make_weak_etag,
    no_store_json,
    not_modified,
)
from modules.production.services import blokady_zamowien, label_print_service, realtime_service, worker_service
from modules.production.services.label_print_service import (
    StationNotAllowed,
    compute_label_offsets,
)
from modules.production.services.worker_service import WorkerError
from modules.production.services.station_catalog import STATION_ORDER, resolve_station_code
from modules.production.logistics import sposoby
# Moduł, nie nazwy: testy podmieniają funkcje stołu (`stol.zablokuj_stanowisko`), a import nazwy ominąłby podmianę.
from modules.production.priorytety import stale as priorytety_stale
from modules.production.priorytety.models import StationDesk
from modules.production.priorytety.services import kolejka, lista, stol, sygnaly
from modules.production.priorytety.services import ustawienia as priorytety_ustawienia
from modules.production.services.mobile_api_service import (
    STATION_QUANTITY_FIELD,
    STATION_STATUS_MAP,
    STATUS_TO_STATION,
    compute_station_summary,
    device_can_access_station,
    get_app_version_info,
    get_station_queue_delta,
    mark_order_complete,
    parse_client_local_ts,
    parse_since_ts,
    register_device,
    require_device_token,
    search_orders_global,
    serialize_order,
    stream_apk_response,
    update_order_quantity,
    with_idempotency,
)


def _resolve_station_code(requested, *, znane_kody=STATION_STATUS_MAP):
    """
    Rozstrzyga station_code dla operacji mutującej. Gdy klient nie poda
    `station_code` w body, używamy `g.device.station_code` (BC). Zwraca
    (station_code, error_response) — gdy error_response != None, wywołujący
    powinien zwrócić go natychmiast.

    GŁÓWNY PUNKT ALIASU okresu przejściowego. Stary APK zna jeszcze stary
    kod wykańczalni 'finishing' (finishing-ZOSTAJE: okres przejściowy,
    literał trzyma STATION_CODE_ALIASES w katalogu stanowisk); rozwijamy
    go na kanoniczne 'edges' PRZED sprawdzeniem
    `znane_kody` i PRZED kontrolą dostępu. Kolejność jest całą logiką:
    po sprawdzeniu `znane_kody` byłoby za późno (kod zniknął z katalogu →
    404 unknown_station), a po kontroli dostępu jeszcze gorzej (403
    station_mismatch, jedyny status, po którym praca z kolejki offline
    przepada bezpowrotnie). W dół idzie już WYŁĄCZNIE kod kanoniczny.

    Ta bramka jest JEDYNĄ obroną prod_station_events i prod_worker_sessions
    przed martwym kodem: obie kolumny to zwykłe stringi bez FK, a Enum
    SQLAlchemy — nawet gdyby tam stał — nie zatrzymałby zapisu, bo nie
    waliduje wartości po stronie Pythona (validate_strings domyślnie False).
    Błąd wyszedłby dopiero przy ODCZYCIE, z zupełnie innego miejsca kodu.

    `znane_kody` rozdziela dwa pytania, które do 09.2026 były tu sklejone:

      - „czy to stanowisko przesuwa produkt w pipelinie" — STATION_STATUS_MAP
        (domyślnie), mapa kod -> status ProductionProduct. Tego pilnują
        complete/quantity/reject: bez statusu nie ma czego domykać;
      - „czy to stanowisko w ogóle istnieje" — ProductionDevice.VALID_STATION_CODES,
        pełna lista kodów, jakie system wystawia urządzeniom.

    Trakownia ('sawmill') jest w drugiej liście, a w pierwszej celowo nie —
    liczy się z własnych tabel prod_sawmill_*, nie ze statusów produktu.
    Dopóki obie role pełniła STATION_STATUS_MAP, start sesji pracownika na
    tablecie trakowni kończył się 404 unknown_station przy KAŻDYM wyborze
    profilu: sesja nigdy się nie otwierała, apka wracała na bramkę, a czas
    pracy na trakowni nie był mierzony w ogóle. Sesja pracownika dotyczy
    każdego stanowiska, nie tylko tych z pipeline'u produktów.
    """
    code = (requested or g.device.station_code or '').strip()
    if not code:
        return None, (jsonify({'error': 'missing_station_code'}), 400)
    code = resolve_station_code(code)
    if code not in znane_kody:
        return None, (jsonify({'error': 'unknown_station'}), 404)
    if not device_can_access_station(g.device, code):
        return None, (jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': code,
        }), 403)
    return code, None

# Kody, po których wpis MUSI zostać w kolejce offline zamiast zostać zapamiętany
# przez @with_idempotency. Wspólny mianownik: przyczyna jest odwracalna BEZ
# udziału tabletu, więc ponowienie tego samego wpisu ma szansę się udać.
#   400 worker_ids_required — admin wyłącza kill-switch,
#   404 worker_not_found    — katalog się odświeża,
#   409 worker_inactive     — admin przywraca pracownika,
#   403 station_mismatch    — rejestracja urządzenia rozjechała się ze
#                             stanowiskiem (_resolve_station_code); wraca do
#                             normy po przerejestrowaniu tabletu albo korekcie
#                             prod_devices.station_code.
# Bez tego dekorator zapisuje odpowiedź pod X-Operation-Id i przy ponowieniu
# ODTWARZA ją bez wywołania handlera — wykonana robota przepada bezpowrotnie,
# mimo że przyczyna błędu już nie istnieje. Przy 403 jest to szczególnie
# zdradliwe: tablet dostaje odpowiedź ostateczną, usuwa akcję z kolejki
# i melduje UDANĄ synchronizację, choć odbite sztuki nigdy nie trafiły do bazy.
# Trakownia używa tego mechanizmu z dokładnie tego powodu
# (sawmill/routers/mobile_api.py) i trzyma własną, bliźniaczą kopię listy.
BLEDY_DO_PONOWIENIA = {400, 403, 404, 409}

# Wersja KSZTAŁTU odpowiedzi kolejki — część ETagu, nie numer API.
#
# ETag kolejki liczy się z max(updated_at) i liczby pozycji, czyli z DANYCH,
# a nie z tego, jakie pola serializer wystawia. Bez tego znacznika dołożenie
# pola przechodzi niezauważone: tablet z zapamiętanym ETagiem dostaje 304
# i dalej serwuje sobie starą odpowiedź, dopóki w kolejce coś się nie zmieni.
# Objaw jest wtedy mylący — aplikacja działa, backend działa, a pola nie ma.
#
# PODBIJ przy każdej zmianie zestawu pól w serialize_order().
#   2 — 2026-09-18: label_print_count, label_offset, label_total (panel kafelków)
#   3 — 2026-09-25: obiekt `transport` (logistyka równoległa)
#   4 — 2026-09-30: `packing_hint` (logistyka etap 4, krok 4.2 — okno paczek na pakowaniu)
#   5 — 2026-09-30: `transport.repack_reason` (logistyka etap 4, krok 4.3 — baner przepakowania)
#   6 — 2026-10-05: `priorytet` i `grupa_wykonczenia` (priorytety produkcji, krok K3)
KSZTALT_ODPOWIEDZI_KOLEJKI = 6

# Wersja KSZTAŁTU odpowiedzi stołu (GET /stations/<kod>/desk i odpowiedź POST /orders/<id>/postpone) — część ETagu
# stołu, jak KSZTALT_ODPOWIEDZI_KOLEJKI dla listy. PODBIJ przy każdej zmianie zestawu pól odpowiedzi stołu
# (`_odpowiedz_stolu`); zmiana pól samej pozycji idzie przez KSZTALT_ODPOWIEDZI_KOLEJKI, który też wchodzi do ETagu.
#   1 — 2026-10-05: pierwsza wersja (priorytety produkcji, krok K3)
#   2 — 2026-10-05: pole `tryb` (K3-poprawka-2 — appka pokazuje stół tylko przy `tryb == "stol"`)
KSZTALT_ODPOWIEDZI_STOLU = 2

# Wersja KSZTAŁTU katalogu pracowników (GET /workers) — część ETagu, jak KSZTALT_ODPOWIEDZI_KOLEJKI.
# ETag katalogu liczy się z MAX(prod_workers.updated_at) i odcisku konfiguracji, więc nowe pole bez tego
# segmentu nie dotarłoby do urządzeń z zapamiętanym katalogiem (304). PODBIJ przy każdej zmianie zestawu pól
# w worker_service.serialize_worker_for_mobile().
#   2 — 2026-10-01: `is_driver` (logistyka etap 4, krok 4.4 — bramka stanowiska Dostawa)
KSZTALT_KATALOGU_PRACOWNIKOW = 2


def _resolve_workers():
    """
    Czyta nagłówek X-Worker-Ids, waliduje i odświeża sesje.

    Zwraca (worker_ids, session_ids, error_response). Gdy error_response != None,
    wywołujący ma go zwrócić natychmiast. Pusta lista worker_ids znaczy
    "bramka wyłączona i tablet nie przysłał nagłówka" — akcja przechodzi
    bez atrybucji.

    Sesje odświeżamy po samym device_id, nie po station_code: tablet
    Krawędzi zamyka też pozycje z Lakierni (station_code='painting'),
    a sesja jest założona na stanowisku z JWT.
    """
    try:
        worker_ids = worker_service.resolve_worker_ids(
            request.headers.get('X-Worker-Ids'))
    except WorkerError as e:
        return None, None, _worker_error_response(e)

    # Audyt zmian statusu (product_events.current_actor) czyta to z g —
    # dzięki temu prod_product_events.worker_id wypełnia się bez przekazywania
    # listy przez cały łańcuch wywołań aż do listenera SQLAlchemy.
    g.worker_ids = worker_ids

    session_ids = worker_service.touch_sessions(
        worker_ids, device_id=g.device.device_id) if worker_ids else {}
    return worker_ids, session_ids, None


logger = get_structured_logger('production.mobile_api.routes')

mobile_api_bp = Blueprint('mobile_api', __name__)


# ============================================================================
# REJESTRACJA URZĄDZENIA
# ============================================================================

@mobile_api_bp.route('/register', methods=['POST'])
def register():
    """
    POST /api/mobile/register

    Body JSON: { device_id: str, device_name: str?, station_code: str }
    Response: { token: str, device_id: str, station_code: str }

    Idempotentne — powtórna rejestracja tego samego device_id aktualizuje
    wpis (nowe station_code / device_name) i zwraca nowy token.
    """
    data = request.get_json(silent=True) or {}
    device_id = (data.get('device_id') or '').strip()
    device_name = (data.get('device_name') or '').strip()
    station_code = (data.get('station_code') or '').strip()
    # Stary APK przedstawia się kodem 'finishing'. Bez rozwinięcia aliasu
    # tutaj każde odnowienie JWT odtwarzałoby w prod_devices wiersz, który
    # migracja przed chwilą poprawiła — a po zdjęciu 'finishing'
    # z VALID_STATION_CODES stary tablet dostałby 400 invalid_station_code
    # i nie odnowiłby tokenu w ogóle. Wołanie stoi PRZED walidacją
    # kompletności pól; pozwala na to kontrakt resolve_station_code
    # opisany w nagłówku planu wdrożenia.
    station_code = resolve_station_code(station_code)

    if not device_id or not station_code:
        return jsonify({
            'error': 'missing_fields',
            'required': ['device_id', 'station_code'],
        }), 400

    if station_code not in ProductionDevice.VALID_STATION_CODES:
        return jsonify({
            'error': 'invalid_station_code',
            'allowed': sorted(ProductionDevice.VALID_STATION_CODES),
        }), 400

    try:
        device, token = register_device(device_id, device_name, station_code)
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API register failed", extra={
            'device_id': device_id,
            'error': str(e),
        })
        return jsonify({'error': 'registration_failed', 'detail': str(e)}), 500

    return jsonify({
        'token': token,
        'device_id': device.device_id,
        'station_code': device.station_code,
    }), 200


# ============================================================================
# ZLECENIA
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/orders', methods=['GET'])
@require_device_token
def station_orders(station_code):
    """
    GET /api/mobile/stations/<station_code>/orders

    Zwraca WSZYSTKIE pozycje z zamówień, w których cokolwiek wisi na danym
    stanowisku — także pozycje sąsiednich stanowisk z tego samego zamówienia.
    Pozwala mobile renderować pełny stan zamówienia z badge'em sąsiada
    (parytet z webem, templates/stations/*.html).

    Urządzenie musi być zarejestrowane pod TEGO stanowiska.
    """
    # Alias okresu przejściowego rozwijamy PRZED wszystkim innym: dzięki temu
    # /stations/finishing/orders i /stations/edges/orders oddają identyczne
    # ciało i identyczny ETag (station_code wchodzi do klucza w :235), więc
    # tablet przełączający adres nie pobiera pełnej listy od nowa.
    station_code = resolve_station_code(station_code)

    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    status = STATION_STATUS_MAP[station_code]

    # Zamówienia (po internal_order_number), w których jakakolwiek pozycja
    # ma current_status pasujący do tego stanowiska. Następnie pobieramy
    # wszystkie pozycje z tych zamówień — także te z innych statusów
    # (sąsiednich stanowisk lub już ukończone), żeby mobile mogło pokazać
    # pełną grupę z badge'em.
    order_numbers_subq = db.session.query(
        ProductionOrder.internal_order_number
    ).join(ProductionItem, ProductionItem.order_id == ProductionOrder.id).filter(
        ProductionItem.current_status == status
    ).distinct().subquery()

    items_filter = ProductionOrder.internal_order_number.in_(
        db.session.query(order_numbers_subq.c.internal_order_number)
    )

    max_updated, total_count = db.session.query(
        func.max(ProductionItem.updated_at),
        func.count(ProductionItem.id),
    ).join(ProductionOrder, ProductionItem.order_id == ProductionOrder.id).filter(items_filter).first()
    etag_ts = int(max_updated.timestamp()) if max_updated else 0
    etag = make_weak_etag('orders', station_code, etag_ts, total_count or 0,
                          KSZTALT_ODPOWIEDZI_KOLEJKI)
    if if_none_match(etag):
        return not_modified(etag)

    items = ProductionItem.query.options(
        joinedload(ProductionItem.order),
        joinedload(ProductionItem.configuration),
    ).join(
        ProductionOrder, ProductionItem.order_id == ProductionOrder.id
    ).filter(items_filter).order_by(
        func.coalesce(ProductionItem.priority_rank, 999999).asc(),
        ProductionOrder.internal_order_number.asc(),
        ProductionItem.id.asc(),
    ).all()
    # Lakiernia (bez stołu): lista ułożona po grupach wykończenia — spec priorytetów 3.2 „Lista Lakierni”. Dla
    # pozostałych stanowisk funkcja oddaje tę samą listę i jedynym źródłem kolejności zostaje ORDER BY wyżej.
    # ETag liczy się bez zmian: kolejność zależy od rangi i pól wykończenia, a ich zmiana podbija updated_at.
    items = lista.porzadek_listy(station_code, items)

    # Jedna mapa numeracji na całą listę — bez niej serializer liczyłby offset
    # osobnym zapytaniem dla każdej pozycji, a ten endpoint jest odpytywany
    # przez sześć tabletów niezależnie, poza cyklem także przy każdym powrocie
    # aplikacji na pierwszy plan.
    numeracja = compute_label_offsets(items)
    # Podpowiedź paczek z tej samej listy (są w niej wszystkie pozycje każdego zamówienia).
    from modules.production.logistics.services.paczki import podpowiedzi_zamowien
    podpowiedzi = podpowiedzi_zamowien(items)
    # Priorytet (gwiazdki, szczebel, trasa, miejsce pozycji w zamówieniu) — też jedna mapa na całą listę; lista
    # ma wszystkie pozycje każdego zamówienia, więc bez dodatkowego zapytania o pozycje (`komplet`).
    priorytety = stol.kontekst_priorytetu(items, komplet=True)

    return cached_json({
        'station_code': station_code,
        'count': len(items),
        'orders': [
            serialize_order(it, station_code=station_code, label_numbering=numeracja,
                            packing_hints=podpowiedzi, priorytety=priorytety)
            for it in items
        ],
    }, etag)


# ============================================================================
# STÓŁ STANOWISKA (priorytety produkcji, spec 2026-10-04, sekcje 5.1–5.2, 6.1)
# ============================================================================

# Pola zamówienia w kaflu-zamówieniu (`kafel.zamowienie`) — brane z serializacji pierwszej pozycji zamówienia.
POLA_ZAMOWIENIA_KAFLA = (
    'internal_order_number', 'baselinker_order_id', 'client_name', 'client_order_number', 'delivery_type',
    'transport', 'packing_hint', 'delivery_city', 'delivery_postcode', 'order_notes', 'order_source',
    'order_source_id', 'order_source_name', 'order_source_display',
)


def _stanowisko_bez_stolu(station_code):
    """409 dla `desk` i `postpone` stanowiska, które pracuje z listy (Lakiernia): „Lakiernia pracuje z listy, bez
    stołu.” Appka nie woła tych końcówek dla Lakierni (wybór ekranu po kodzie stanowiska)."""
    return jsonify({
        'error': 'stanowisko_bez_stolu',
        'message': u'{} pracuje z listy, bez stołu.'.format(
            priorytety_ustawienia.STANOWISKA_BEZ_STOLU[station_code]),
    }), 409


def _znacznik(*czasy):
    """Najpóźniejszy z podanych czasów jako segment ETagu (pusty, gdy żadnego nie ma)."""
    znane = [czas for czas in czasy if czas is not None]
    return max(znane).strftime('%Y%m%d%H%M%S%f') if znane else ''


def _etag_stolu(station_code, tryb=None):
    """
    Słaby ETag odpowiedzi `desk` — kilka agregatów zamiast pełnej serializacji, żeby odpytywanie przy pustym stole
    było tanie (spec 6.1). Podzbiór pozycji jak w liście stanowiska: wszystkie pozycje zamówień, które mają pozycję
    w statusie stanowiska (kafel-zamówienie i sekcja „Niekompletne” pokazują też pozycje w innych statusach).

    Poza max(updated_at) i liczbą pozycji wchodzą tu WPROST: liczba pozycji czekających na stanowisku, suma
    liczników sztuk stanowiska i gwiazdki zamówień. `updated_at` ma w MySQL dokładność sekundy, więc dwie zmiany
    w tej samej sekundzie (dwa kliknięcia licznika) dałyby ten sam znacznik, a drugi tablet zostałby ze starym
    stanem do następnej zmiany. Do tego stół (czasy i liczby wierszy), ustawienia stanowiska z trybem (przełączenie
    `stary` ↔ `stol` w Konfiguracji nie zmienia żadnego wiersza pozycji ani stołu — bez trybu w ETagu tablet
    dostałby 304 i nie wykryłby przełączenia) i wersja kształtu.
    """
    if tryb is None:
        tryb = priorytety_ustawienia.tryb(station_code)
    status = STATION_STATUS_MAP[station_code]
    w_statusie = db.session.query(ProductionItem.order_id).filter(ProductionItem.current_status == status)
    licznik = getattr(ProductionItem, STATION_QUANTITY_FIELD[station_code])
    zmieniono, pozycji, na_stanowisku, zrobione = db.session.query(
        func.max(ProductionItem.updated_at), func.count(ProductionItem.id),
        func.sum(case([(ProductionItem.current_status == status, 1)], else_=0)),
        func.sum(func.coalesce(licznik, 0)),
    ).filter(ProductionItem.order_id.in_(w_statusie)).first()
    gwiazdki_kiedy, gwiazdki = db.session.query(
        func.max(ProductionOrder.priority_stars_set_at), func.sum(ProductionOrder.priority_stars),
    ).filter(ProductionOrder.id.in_(w_statusie)).first()
    pobrano, odlozono, wierszy, odlozonych = db.session.query(
        func.max(StationDesk.pulled_at), func.max(StationDesk.postponed_at), func.count(StationDesk.id),
        func.count(StationDesk.postponed_at),
    ).filter(StationDesk.station_code == station_code).first()
    return make_weak_etag(
        'desk', station_code, _znacznik(zmieniono), pozycji or 0, int(na_stanowisku or 0), int(zrobione or 0),
        _znacznik(gwiazdki_kiedy), int(gwiazdki or 0), _znacznik(pobrano, odlozono), wierszy or 0, odlozonych or 0,
        KSZTALT_ODPOWIEDZI_KOLEJKI, priorytety_ustawienia.miejsca(station_code), priorytety_ustawienia.limit(station_code),
        priorytety_ustawienia.jednostka(station_code), tryb, KSZTALT_ODPOWIEDZI_STOLU)


def _odpowiedz_stolu(station_code, tryb=None):
    """
    Ciało odpowiedzi `desk` i `postpone` (spec 6.1) — zwykłe odczyty, BEZ dopełniania i bez zapisów: tryb stanowiska
    (`stary` | `stol` — appka pokazuje ekran stołu tylko przy `stol`), stół i odłożone w kolejności `stol.kafle`
    (appka nie sortuje — dwa tablety stanowiska pokazują to samo), sekcja „Niekompletne”, ustawienia stanowiska
    i liczba kafli czekających w kolejce.

    `kafel` dla jednostki `pozycja` to obiekt pozycji z `serialize_order`; dla jednostki `zamowienie` —
    `{zamowienie: {...}, pozycje: [...]}` ze WSZYSTKIMI pozycjami zamówienia (także w innych statusach: appka
    pokazuje postęp i plakietki sąsiednich stanowisk), w kolejności pozycji w zamówieniu.
    """
    if tryb is None:
        tryb = priorytety_ustawienia.tryb(station_code)
    stan = stol.stan(station_code)
    id_zamowien = sorted({w.order_id for w in stan.wiersze} | {n.order.id for n in stan.niekompletne})
    pozycje = []
    if id_zamowien:
        # Wszystkie pozycje zamówień z odpowiedzi jednym zapytaniem: numeracja etykiet i podpowiedź paczek liczą
        # się z całego składu zamówienia (jak w liście stanowiska).
        pozycje = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(ProductionItem.order_id.in_(id_zamowien)).order_by(
            ProductionItem.order_id.asc(),
            func.coalesce(ProductionItem.product_sequence_in_order, 0).asc(),
            ProductionItem.id.asc(),
        ).all()
    numeracja = compute_label_offsets(pozycje)
    from modules.production.logistics.services.paczki import podpowiedzi_zamowien
    podpowiedzi = podpowiedzi_zamowien(pozycje)
    priorytety = stol.kontekst_priorytetu(pozycje, komplet=True)
    po_id = {pozycja.id: pozycja for pozycja in pozycje}
    pozycje_zamowien = {}
    for pozycja in pozycje:
        pozycje_zamowien.setdefault(pozycja.order_id, []).append(pozycja)

    def kafel_pozycji(pozycja):
        return serialize_order(pozycja, station_code=station_code, label_numbering=numeracja,
                               packing_hints=podpowiedzi, priorytety=priorytety)

    def kafel_zamowienia(order_id):
        skladowe = pozycje_zamowien.get(order_id)
        if not skladowe:
            return None
        serializowane = [kafel_pozycji(pozycja) for pozycja in skladowe]
        zamowienie = {pole: serializowane[0][pole] for pole in POLA_ZAMOWIENIA_KAFLA}
        termin = kolejka.termin_zamowienia(skladowe)
        zamowienie.update({'order_id': order_id, 'deadline': termin.isoformat() if termin else None,
                           'priorytet': stol.priorytet_zamowienia(skladowe, priorytety)})
        return {'zamowienie': zamowienie, 'pozycje': serializowane}

    def kafel(wiersz):
        if wiersz.product_id is None:
            return kafel_zamowienia(wiersz.order_id)
        pozycja = po_id.get(wiersz.product_id)
        return kafel_pozycji(pozycja) if pozycja is not None else None

    id_pracownikow = sorted({w.postponed_by_worker_id for w in stan.wiersze
                             if w.postponed_at is not None and w.postponed_by_worker_id is not None})
    pracownicy = {}
    if id_pracownikow:
        for pracownik in ProductionWorker.query.filter(ProductionWorker.id.in_(id_pracownikow)).all():
            # Tablet pokazuje „Adam K.” (spec 6.1); pełne nazwisko zostaje w panelu biura.
            pracownicy[pracownik.id] = stol.imie_z_inicjalem(pracownik.first_name, pracownik.last_name)

    na_stole, odlozone = [], []
    for wiersz in stan.wiersze:
        tresc = kafel(wiersz)
        if tresc is None:
            continue            # wiersz bez pozycji w bazie — nie powinien istnieć (FK), ale nie wywracamy stołu
        if wiersz.postponed_at is None:
            na_stole.append({'kafel': tresc, 'pobrano': wiersz.pulled_at.isoformat(), 'zrodlo': wiersz.zrodlo})
        else:
            odlozone.append({'kafel': tresc, 'odlozono': wiersz.postponed_at.isoformat(),
                             'powod': wiersz.postpone_reason, 'notatka': wiersz.postpone_note,
                             'pracownik': pracownicy.get(wiersz.postponed_by_worker_id)})
    niekompletne = []
    for wpis in stan.niekompletne:
        tresc = kafel_zamowienia(wpis.order.id)
        if tresc is None:
            continue
        niekompletne.append({'kafel': tresc, 'na_stanowisku': wpis.na_stanowisku, 'pozycji': wpis.pozycji,
                             'brakuje': [{'short_id': brakujaca.short_product_id, 'stanowisko': stanowisko}
                                         for brakujaca, stanowisko in wpis.brakuje]})
    return {
        'station_code': station_code,
        'tryb': tryb,
        'jednostka': stan.jednostka,
        'miejsca': stan.miejsca,
        'stol': na_stole,
        'odlozone': odlozone,
        'niekompletne': niekompletne,
        'limit_odlozen': stan.limit_odlozen,
        'kolejka_dalej': stan.kolejka_dalej,
    }


def _dopelnij_stol(station_code):
    """
    Dopełnienie stołu dla `GET desk` w trybie `stol`: commit → (krótki limit czekania) `stol.dopelnij` → commit, jedno
    ponowienie po MySQL 1213; po 1205 (limit czekania) stół zostaje bez dopełnienia. Po commicie, jeśli coś
    dołożyło — sygnał `station:<kod>`. Zwraca None albo gotową odpowiedź 500 `desk_failed`.
    """
    def _dopelnij():
        db.session.commit()             # koniec migawki żądania; następny odczyt to blokada stanowiska
        with stol.krotkie_czekanie_na_blokady():
            wynik = stol.dopelnij(station_code)
            pobrano = bool(wynik.pobrane)   # przed commitem: commit wygasza obiekty sesji
        db.session.commit()             # limit czekania już przywrócony; tu idą INSERT-y wierszy stołu
        return pobrano

    pobrano = False
    try:
        for proba in (1, 2):
            try:
                pobrano = _dopelnij()
                break
            except OperationalError as e:
                db.session.rollback()
                kod = blokady_zamowien.kod_mysql(e)
                if kod == stol.KOD_LIMIT_CZEKANIA:
                    # Ktoś trzyma blokadę zamówienia albo stanowiska dłużej niż limit: stół bez dopełnienia.
                    logger.warning("Mobile API desk: limit czekania na blokadę, stół bez dopełnienia", extra={
                        'station_code': station_code})
                    break
                if kod != 1213 or proba == 2:
                    raise
                logger.warning("Mobile API desk: zakleszczenie 1213, ponawiam dopełnienie raz", extra={
                    'station_code': station_code})
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API desk: dopełnienie stołu nieudane", extra={
            'station_code': station_code, 'error': str(e)})
        return jsonify({'error': 'desk_failed'}), 500

    if pobrano:
        # Pobranie na stół przez jeden tablet budzi drugi tablet stanowiska (spec 5.4) — po commicie dopełnienia.
        # `desk`, który niczego nie dołożył, nie wysyła nic (inaczej dwa tablety budziłyby się nawzajem bez końca).
        sygnaly.wyslij(station_code)
    return None


@mobile_api_bp.route('/stations/<station_code>/desk', methods=['GET'])
@require_device_token
def station_desk(station_code):
    """
    GET /api/mobile/stations/<station_code>/desk

    Stół stanowiska z trybem (`tryb`: `stary` | `stol`, spec 6.3): w trybie `stol` dopełnia go z kolejki do K kafli
    (spec 5.2) i oddaje stół, odłożone i sekcję „Niekompletne”. Tablet woła po własnym ZAKOŃCZ/Odłóż, po sygnale
    realtime i co 30 s, gdy stół jest pusty; w trybie `stary` — najwyżej co 30 s, żeby wykryć przełączenie.

    W trybie `stary` (K3-poprawka-2, decyzja centrali 5.10) `desk` jest ZWYKŁYM ODCZYTEM: bez commita, blokady
    stanowiska, limitu czekania i zapisów — oddaje bieżące wiersze stołu (np. kafle startowe po „Przygotuj stoły”)
    w tym samym kształcie, z `tryb: "stary"`. Inaczej nowa appka po wdrożeniu przeszłaby na stół od razu, a `desk`
    kładłby kafle z kolejki przed startem stołów.

    W trybie `stol` to JEDYNY handler GET, który zapisuje i commituje sam: dopełnienie biegnie we własnej transakcji
    (commit → blokada stanowiska → odczyt bieżący → INSERT → commit), poza transakcją ZAKOŃCZ — kolejność
    i uzasadnienie w `priorytety/services/stol.py`. Jedno ponowienie po zakleszczeniu MySQL 1213, drugie → 500
    `desk_failed` (tablet ponowi z siatki odpytywania).

    Dopełnienie czeka na cudzą blokadę najwyżej kilka sekund (`stol.krotkie_czekanie_na_blokady`). Po przekroczeniu
    (MySQL 1205) nie ponawiamy — ponowienie czekałoby na tę samą blokadę — i nie zwracamy błędu: tablet dostaje
    200 z bieżącym stołem BEZ dopełnienia, a wolne miejsce zajmie następny `desk` (sygnał albo siatka odpytywania).

    Odpowiedź z ETagiem i `Cache-Control: private, max-age=0`: tablet pyta serwer za każdym razem (z
    `If-None-Match`), bo w `stol` każde żądanie dopełnia stół, a w `stary` czeka na przełączenie trybu — odpowiedź
    z pamięci tabletu pominęłaby dopełnienie, przełączenie i zmiany z drugiego tabletu.
    """
    station_code = resolve_station_code(station_code)

    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    # Lakiernia nie ma stołu (spec 5.5, ustalenie 15) — odmowa PRZED commitem i blokadą, bez żadnego zapisu.
    if station_code in priorytety_ustawienia.STANOWISKA_BEZ_STOLU:
        return _stanowisko_bez_stolu(station_code)

    # Tryb zwykłym odczytem w transakcji żądania, PRZED commitem dopełnienia. Przełączenie w Konfiguracji tuż po tym
    # odczycie kosztuje najwyżej jedno dopełnienie w starym trybie (`stol` → `stary`) albo jedno bez (odwrotnie).
    tryb = priorytety_ustawienia.tryb(station_code)
    if tryb == 'stol':
        blad = _dopelnij_stol(station_code)
        if blad is not None:
            return blad

    try:
        # `stol` — po commicie: świeża migawka, odpowiedź widzi własne dopełnienie i wszystko, co zatwierdzono
        # wcześniej. `stary` — migawka żądania, bez commita (handler niczego nie zapisuje).
        etag = _etag_stolu(station_code, tryb)
        if if_none_match(etag):
            return not_modified(etag, max_age=0)
        return cached_json(_odpowiedz_stolu(station_code, tryb), etag, max_age=0)
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API desk: odczyt stołu nieudany", extra={
            'station_code': station_code, 'error': str(e)})
        return jsonify({'error': 'desk_failed'}), 500


@mobile_api_bp.route('/orders/<int:order_id>/postpone', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_postpone(order_id):
    """
    POST /api/mobile/orders/<id>/postpone — „Odłóż” kafel z powodem (priorytety produkcji, spec 5.3, 6.2).

    Body JSON: { station_code: str?, zakres: 'pozycja' | 'zamowienie', powod: str, notatka: str? };
    `X-Worker-Ids` jak w ZAKOŃCZ. `zakres` musi zgadzać się z jednostką kafla stanowiska; dla `zamowienie` `<id>`
    w ścieżce to id POZYCJI zamówienia (appka zna id pozycji, jak w `complete`), a odkładany jest kafel zamówienia.

    200 → stół stanowiska jak w `GET desk`, ale BEZ dopełniania: handler trzyma blokadę zamówienia, a dopełnienie
    bierze blokadę stanowiska i czyta inne zamówienia (odwrotna kolejność — cykl). Wolne miejsce zajmie następny
    kafel przy `GET desk`, który appka woła po własnym Odłóż.

    409 `limit_odlozen`, 409 `nie_na_stole`, 400 `powod_niepoprawny`, 400 `dane_niepoprawne`, 404 `order_not_found`.
    Wszystkie są w BLEDY_DO_PONOWIENIA: dekorator ich nie zapamiętuje.
    """
    data = request.get_json(silent=True) or {}
    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    # Lakiernia nie ma stołu ani Odłóż (spec 5.5). 409 jest w BLEDY_DO_PONOWIENIA — bez wpisu idempotencji.
    if station_code in priorytety_ustawienia.STANOWISKA_BEZ_STOLU:
        return _stanowisko_bez_stolu(station_code)

    zakres, powod, notatka = data.get('zakres'), data.get('powod'), data.get('notatka')
    if (zakres not in priorytety_stale.JEDNOSTKI or not isinstance(powod, str)
            or not (notatka is None or isinstance(notatka, str)) or len(notatka or u'') > 255):
        return jsonify({
            'error': 'dane_niepoprawne',
            'message': u'Podaj zakres (pozycja albo zamowienie), powód i opcjonalną notatkę do 255 znaków.',
        }), 400
    jednostka = priorytety_ustawienia.jednostka(station_code)
    if zakres != jednostka:
        return jsonify({
            'error': 'dane_niepoprawne',
            'message': (u'Na tym stanowisku odkłada się całe zamówienia.' if jednostka == 'zamowienie'
                        else u'Na tym stanowisku odkłada się pojedyncze pozycje.'),
        }), 400

    worker_ids, _sesje, err = _resolve_workers()
    if err:
        return err

    # „Zamówienie najpierw”: zamówienie i wszystkie jego pozycje, odczyt bieżący — jak ZAKOŃCZ. Pod tą blokadą
    # `stol.odloz` blokuje już tylko wiersz własnego kafla.
    item = blokady_zamowien.zablokuj_zamowienie_pozycji(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        stol.odloz(item.order_id, item.id if zakres == 'pozycja' else None, station_code, powod, notatka,
                   worker_ids[0] if worker_ids else None, g.device.id)
    except stol.BladStolu as e:
        return jsonify({'error': e.kod, 'message': e.komunikat}), e.status

    logger.info("Mobile API: kafel odłożony", extra={
        'order_id': order_id, 'station_code': station_code, 'powod': powod, 'device_id': g.device.device_id})

    # Drugi tablet stanowiska przenosi kafel do „Odłożonych” i dociąga następny (spec 5.4) — po commicie.
    sygnaly.zaplanuj(station_code)

    return jsonify(_odpowiedz_stolu(station_code)), 200


@mobile_api_bp.route('/realtime-token', methods=['GET'])
@require_device_token
def realtime_token():
    """
    GET /api/mobile/realtime-token — krótkotrwały JWT do połączenia tabletu z Centrifugo (SSE), jak
    /api/print-agent/realtime-token dla agenta druku (priorytety produkcji, spec 5.4, 6.3).

    Kanały przyjeżdżają w tokenie (klient SSE nie subskrybuje sam): stanowisko urządzenia i reszta jego grupy —
    tablet Krawędzi dostaje `station:edges` i `station:painting`. Po sygnale tablet woła `GET desk` (Lakiernia:
    odświeża listę).

    200: {"enabled": true, "token": "<JWT>", "ttl_seconds": 3600, "sse_url": "...", "channels": ["station:gluing"]}
    503: {"enabled": false, "reason": "realtime disabled" | "misconfigured"} — appka zostaje przy odpytywaniu
         (30 s przy pustym stole, 5 min przy pełnym), bez błędu i bez ponawiania w kółko.
    404 `unknown_station`: urządzenie spoza stanowisk produktu (trakownia, weryfikacja, dostawa) nie ma stołu.
    """
    stanowisko = resolve_station_code(g.device.station_code)
    if stanowisko not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not realtime_service.is_enabled():
        return jsonify({'enabled': False, 'reason': 'realtime disabled'}), 503

    # Stanowisko urządzenia pierwsze, potem pozostałe z jego grupy w kolejności procesu.
    stanowiska = [stanowisko] + [kod for kod in STATION_ORDER
                                 if kod != stanowisko and device_can_access_station(g.device, kod)]
    kanaly = [realtime_service.channel_station(kod) for kod in stanowiska]
    try:
        token, ttl = realtime_service.issue_connection_token('device:' + g.device.device_id, kanaly)
    except RuntimeError as e:
        logger.error("Mobile API: nie udało się wystawić tokena realtime dla tabletu", extra={'error': str(e)})
        return jsonify({'enabled': False, 'reason': 'misconfigured'}), 503

    return jsonify({
        'enabled': True,
        'token': token,
        'ttl_seconds': ttl,
        'sse_url': realtime_service.sse_url(),
        'channels': kanaly,
    }), 200


@mobile_api_bp.route('/orders/search', methods=['GET'])
@require_device_token
def orders_search():
    """
    GET /api/mobile/orders/search?q=<query>&limit=<n>

    Globalne wyszukiwanie zamówień po wszystkich stanowiskach (bez
    ograniczeń per device.station_code — operator może znaleźć "cudze"
    zamówienie). Match tekstowy (internal_order_number, baselinker_order_id,
    client_order_number, client_name) LUB wymiarowy (1-3 liczby cm, multiset
    z tolerancją ±5 mm). Zwraca wszystkie pozycje pasujących zamówień,
    każda z dodatkowym polem `current_station` (mapowanie current_status →
    kod stanowiska, lub null gdy pozycja poza produkcją).

    Wyniki obejmują też archiwum (spakowane lub dalej i anulowane) — tablet otwiera je
    tylko do podglądu. Idą ZA aktywnymi zamówieniami, od najświeżej
    spakowanego. Pozycja spakowana ma `packed_at` (ISO 8601) — czas
    zamknięcia pakowania; null dla pozostałych i dla historycznych
    spakowanych sprzed zapisywania tej daty.
    """
    q_raw = request.args.get('q', '')
    q = q_raw.strip()
    if len(q) < 3:
        return jsonify({'error': 'Query too short'}), 400

    limit_raw = request.args.get('limit', '50').strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 50
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    try:
        items, has_more, _total = search_orders_global(q, limit=limit)
    except Exception as e:
        logger.error("Mobile API global search failed", extra={
            'q': q, 'limit': limit, 'error': str(e),
        })
        return jsonify({'error': 'search_failed', 'detail': str(e)}), 500

    numeracja = compute_label_offsets(items)
    from modules.production.logistics.services.paczki import podpowiedzi_zamowien
    podpowiedzi = podpowiedzi_zamowien(items)
    priorytety = stol.kontekst_priorytetu(items)
    serialized = []
    for it in items:
        dto = serialize_order(it, label_numbering=numeracja, packing_hints=podpowiedzi, priorytety=priorytety)
        dto['current_station'] = STATUS_TO_STATION.get(it.current_status)
        # Tylko w wyszukiwarce: listy stanowisk nigdy nie zawierają spakowanych,
        # a nowe pole w serialize_order zmieniłoby im kształt odpowiedzi.
        dto['packed_at'] = (
            it.packaging_completed_at.isoformat()
            if it.current_status in sposoby.STATUSY_PO_SPAKOWANIU and it.packaging_completed_at
            else None
        )
        serialized.append(dto)

    return jsonify({
        'query': q,
        'count': len(serialized),
        'has_more': has_more,
        'orders': serialized,
    }), 200


@mobile_api_bp.route('/orders/<int:order_id>', methods=['GET'])
@require_device_token
def order_details(order_id):
    """
    GET /api/mobile/orders/<id> — szczegóły zlecenia.

    Kod stanowiska normalizujemy tu osobno. To NIE jest jedyny endpoint
    mobilny bez walidacji kodu — bramkę _resolve_station_code (alias +
    unknown_station + station_mismatch) pomijają też: mobile_print_label_single
    i mobile_print_labels_for_order (obie wołają resolve_station_code wprost
    z g.device.station_code — patrz komentarze przy tych funkcjach niżej),
    workers_catalog oraz sessions_active. Wspólny mianownik: kod stanowiska
    pochodzi z JWT urządzenia, nie z body/URL żądania, więc nie ma tu czego
    sprawdzać pod kątem station_mismatch — inaczej niż w complete/quantity/
    reject/sessions_start, gdzie klient może przysłać dowolny kod.

    Bez rozwinięcia aliasu starego kodu wykańczalni 'finishing' (finishing-ZOSTAJE:
    okres przejściowy) TEN konkretny endpoint wypada z bramki członkostwa
    STATION_QUANTITY_FIELD (mobile_api_service.py:1024) i odpowiedź niesie
    quantity_done: null — cicho, bez błędu i bez logu.
    """
    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    station_code = resolve_station_code(g.device.station_code)
    return jsonify(serialize_order(item, station_code=station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/complete', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_complete(order_id):
    """
    POST /api/mobile/orders/<id>/complete

    Body JSON (opcjonalny): { station_code: str } — gdy pominięte, używane
    jest `device.station_code` (BC). Tablet Krawędzi przekazuje
    `station_code='painting'` żeby ukończyć pozycję z Lakierni. Stary kod
    ze starego APK rozwija _resolve_station_code, zanim cokolwiek go zobaczy.

    Pełna tranzycja statusu (z regułami specjalnymi: Lakiernia dla
    olejowanych i lakierowanych, pominięcie Krawędzi dla produktów BEZ
    obróbki krawędzi — niezależnie od wykończenia) jest delegowana do
    `ProductionItem.complete_task()` (przez `mark_order_complete`). Webowy
    handler `/production/api/complete-task` już nie istnieje.

    Idempotency: przy nagłówku X-Operation-Id powtórne wywołanie zwraca
    zapisany response (nie wykonuje akcji drugi raz).
    """
    data = request.get_json(silent=True) or {}
    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    worker_ids, session_ids, err = _resolve_workers()
    if err:
        return err

    # „Zamówienie najpierw” (logistyka etap 4, krok 4.4a): wiersz zamówienia i wszystkie jego pozycje blokujemy
    # i czytamy bieżąco, ZANIM cokolwiek zapiszemy — w kolejności panelu Logistyki i Weryfikacji. Dotąd ZAKOŃCZ
    # zapisywał pozycję przed zamówieniem (1213 ze zmianą sposobu dostawy w panelu), a po_spakowaniu
    # i odnotuj_wejscie_do_pakowania decydowały na migawce: sposób dostawy sprzed zmiany w panelu zamykał cykl
    # odbioru, a pozycja zrobiona chwilę wcześniej na innym tablecie wyglądała na niezrobioną.
    item = blokady_zamowien.zablokuj_zamowienie_pozycji(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    # Logistyka równoległa, krok 4.6 (decyzja Konrada 5.10): pakowanie NIE czeka na sposób dostawy. Zamówienie
    # bez sposobu pakuje się normalnie (etykieta paczki z pasem „NIE USTAWIONO”), Base. nie dostaje wtedy statusu
    # po spakowaniu (baselinker_status_sync._determine_packaging_target_status), a wyśle go pierwsze ustawienie
    # sposobu w panelu (delivery.ustaw_sposob_dostawy, okno 8.7). Dawna odmowa 409 delivery_method_not_set zniknęła.

    # Priorytety produkcji (spec 2026-10-04, 5.5): w trybie `stol` ZAKOŃCZ przyjmujemy tylko dla kafla ze stołu albo
    # odłożonego. Od logistyki 4.6 przed nią nie ma już bramki sposobu dostawy: Pakowanie bez sposobu przechodzi
    # przez stół jak każde inne zamówienie (spec priorytetów 5.1). Własny wiersz stołu czytamy odczytem bieżącym
    # (pod blokadą zamówienia wziętą wyżej): zwykły odczyt pokazałby migawkę żądania, czyli stół sprzed kafla,
    # który dopełnianie drugiego tabletu wstawiło chwilę wcześniej.
    # 409 `nie_na_stole` jest w BLEDY_DO_PONOWIENIA: akcja z kolejki offline przejdzie, gdy kafel wejdzie na stół.
    # Przed nią 409 `pozycja_poza_stanowiskiem` (K3-poprawka-2): pozycja nie czeka na tym stanowisku — sprawdzane
    # na pozycji z blokady, przed zapisem. Też niezapamiętane (status 409), appka porzuca wpis po polu `error`.
    try:
        stol.bramka_zakoncz(item, station_code, g.device, do_zapisu=True)
    except stol.BladStolu as e:
        return jsonify({'error': e.kod, 'message': e.komunikat}), e.status

    try:
        mark_order_complete(item, station_code, device_id=g.device.device_id,
                            worker_ids=worker_ids, session_ids=session_ids)
    except ValueError as e:
        return jsonify({'error': 'invalid_station', 'detail': str(e)}), 400
    except Exception as e:
        logger.error("Mobile API complete failed", extra={
            'order_id': order_id,
            'station_code': station_code,
            'error': str(e),
        })
        return jsonify({'error': 'complete_failed', 'detail': str(e)}), 500

    # Kafel schodzi ze stołu w tej samej transakcji, w której pozycja schodzi ze stanowiska (spec 5.1) — także
    # w trybie `stary` i dla starej appki (5.5). Jedna reguła uzgadniania: kafel-zamówienie z drugą pozycją na
    # stanowisku zostaje, a `odlozenie_zamkniete` loguje się tylko dla wiersza, który naprawdę znika.
    zdjete_ze_stolu = set()
    if item.order is not None:
        zdjete_ze_stolu = stol.zdejmij_nieaktualne(
            item.order, zamkniecie_odlozen=True,
            worker_id=(worker_ids[0] if worker_ids else None), device_id=g.device.id)
    # Sygnały realtime (spec 5.4) — tylko PLAN: wysyła je dekorator po commicie. To stanowisko (kafel zszedł),
    # następne stanowisko pozycji (doszła praca) i stanowiska, z których uzgadnianie zdjęło zaległy kafel.
    sygnaly.zaplanuj_po_zakonczeniu(item, station_code)
    sygnaly.zaplanuj(*sorted(zdjete_ze_stolu))

    logger.info("Mobile API: order completed", extra={
        'order_id': order_id,
        'station_code': station_code,
        'device_id': g.device.device_id,
    })

    return jsonify(serialize_order(item, station_code=station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/quantity', methods=['PATCH'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_quantity(order_id):
    """
    PATCH /api/mobile/orders/<id>/quantity

    Body JSON: { quantity_done: int } — liczba ukończonych sztuk na stanowisku.
    Waliduje 0 <= quantity_done <= item.quantity.

    Idempotency: przy nagłówku X-Operation-Id powtórne wywołanie zwraca
    zapisany response (nie wykonuje akcji drugi raz).
    """
    data = request.get_json(silent=True) or {}
    quantity_done = data.get('quantity_done')
    if not isinstance(quantity_done, int):
        return jsonify({'error': 'missing_or_invalid_quantity_done'}), 400

    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    worker_ids, session_ids, err = _resolve_workers()
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    # Priorytety produkcji (spec 5.5): bramka stołu i statusu (409 `pozycja_poza_stanowiskiem`, K3-poprawka-2)
    # także dla licznika sztuk. Zwykły odczyt stołu i statusu pozycji, BEZ blokady zamówienia — licznik zostaje
    # pisarzem pozycji bez blokady zamówienia (CLAUDE.md), a stołu nie zmienia.
    try:
        stol.bramka_zakoncz(item, station_code, g.device)
    except stol.BladStolu as e:
        return jsonify({'error': e.kod, 'message': e.komunikat}), e.status

    try:
        update_order_quantity(item, station_code, quantity_done,
                              device_id=g.device.device_id,
                              worker_ids=worker_ids, session_ids=session_ids)
    except ValueError as e:
        return jsonify({'error': 'invalid_quantity', 'detail': str(e)}), 400
    except Exception as e:
        logger.error("Mobile API quantity update failed", extra={
            'order_id': order_id,
            'error': str(e),
        })
        return jsonify({'error': 'update_failed', 'detail': str(e)}), 500

    # Drugi tablet stanowiska ma zobaczyć „2/15” od razu (spec 5.4) — sygnał po commicie dekoratora.
    sygnaly.zaplanuj(station_code)

    return jsonify(serialize_order(item, station_code=station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/reject', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_reject(order_id):
    """
    POST /api/mobile/orders/<id>/reject

    Body JSON: {
        quantity: int,
        reason_category: 'wymiary' | 'jakosc_sklejenia' | 'jakosc_produktu' | 'inne'
                         | 'jakosc_krawedzi' | 'jakosc_lakierowania',
        station_code: 'formatting' | 'gluing' | 'edges' (+ stary alias Krawędzi)
                      | 'painting' | 'packaging'
                      (opcjonalne, domyślnie z g.device.station_code)
    }

    Response: { original: serialized, rework: serialized, rework_log_id: int }

    409 gdy sztuka nie czeka na tym stanowisku: 'product_not_in_formatting'
    dla formatowania (parsują go stare APK), 'product_not_on_station' dla reszty.
    """
    from modules.production.services.rework_service import (
        reject_product_quantity,
        RejectError,
    )

    data = request.get_json(silent=True) or {}

    station_code, err = _resolve_station_code(data.get('station_code'))
    if err is not None:
        return err

    quantity = data.get('quantity')
    reason_category = (data.get('reason_category') or '').strip()

    worker_ids, _sesje, err = _resolve_workers()
    if err:
        return err

    try:
        original, rework, log_entry = reject_product_quantity(
            product_id=order_id,
            quantity=int(quantity) if quantity is not None else None,
            reason_category=reason_category,
            rejected_at_station=station_code,
            user_id=None,  # mobile API używa device, nie user
            device_id=g.device.device_id,
            worker_ids=worker_ids,
        )
    except RejectError as e:
        logger.warning(
            "Mobile API reject odrzucony",
            extra={
                'product_id': order_id,
                'code': e.code,
                'device_id': g.device.device_id,
            },
        )
        return jsonify({'error': e.code, 'detail': e.message}), e.status
    except Exception as e:
        logger.error(
            "Mobile API reject błąd",
            extra={'product_id': order_id, 'device_id': g.device.device_id},
            exc_info=True,
        )
        db.session.rollback()
        return jsonify({'error': 'reject_failed', 'detail': str(e)}), 500

    logger.info(
        "Mobile API: reject wykonany",
        extra={
            'product_id': original.id,
            'rework_id': rework.id,
            'quantity': log_entry.quantity,
            'reason': log_entry.reason_category,
            'device_id': g.device.device_id,
        },
    )

    priorytety = stol.kontekst_priorytetu([original, rework])
    return jsonify({
        'original': serialize_order(original, station_code=station_code, priorytety=priorytety),
        'rework': serialize_order(rework, station_code=station_code, priorytety=priorytety),
        'rework_log_id': log_entry.id,
    }), 200


# ============================================================================
# SUMMARY (metryki stanowiska)
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/summary', methods=['GET'])
@require_device_token
def station_summary(station_code):
    """
    GET /api/mobile/stations/<station_code>/summary

    Metryki stanowiska: queue (count, m³, priorytety) + completed_today (count, m³).

    Opcjonalnie ?worker_id=<prod_workers.id> dokłada completed_today_worker —
    wkład tego pracownika w completed_today (udziały: delta × share). Brak albo
    niepoprawna wartość (nie liczba całkowita > 0) = odpowiedź jak bez parametru.
    """
    # Alias okresu przejściowego. Walidacja niżej stoi PRZED getattr znacznika
    # czasu (:526), więc bez tej linii stary tablet dostaje jawne 404, a nie
    # cichy stale cache — ale i tak przestaje widzieć swoje metryki.
    station_code = resolve_station_code(station_code)

    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    # ETag: MAX(updated_at) + COUNT po pozycjach z kolejki LUB ukończonych
    # dziś na tym stanowisku (completed_today resetuje się o północy, dlatego
    # data lokalna trafia do klucza).
    status = STATION_STATUS_MAP[station_code]
    today_start = datetime.combine(datetime.now().date(), time.min)
    completed_attr = getattr(ProductionItem, f'{station_code}_completed_at', None)
    cache_filter = (ProductionItem.current_status == status)
    if completed_attr is not None:
        cache_filter = or_(cache_filter, completed_attr >= today_start)

    max_updated, total_count = db.session.query(
        func.max(ProductionItem.updated_at),
        func.count(ProductionItem.id),
    ).filter(cache_filter).first()
    etag_ts = int(max_updated.timestamp()) if max_updated else 0
    # Payload zawiera refresh_interval_seconds z prod_config — bez tego segmentu
    # zmiany konfigu nie unieważniają ETag i tablet (OkHttp) serwuje stale 304.
    config_max_updated = db.session.query(
        func.max(ProductionConfig.updated_at)
    ).scalar()
    config_etag_ts = int(config_max_updated.timestamp()) if config_max_updated else 0
    worker_id = request.args.get('worker_id', type=int)
    if worker_id is not None and worker_id <= 0:
        worker_id = None
    czesci_etag = [
        'summary', station_code, today_start.date().isoformat(),
        etag_ts, total_count or 0, config_etag_ts,
    ]
    # Dwóch pracowników jednego stanowiska nie może dostać 304 na cudzą odpowiedź.
    # Bez parametru ETag zostaje dokładnie taki jak wcześniej.
    if worker_id is not None:
        czesci_etag.append(f'w{worker_id}')
    etag = make_weak_etag(*czesci_etag)
    if if_none_match(etag):
        return not_modified(etag)

    try:
        return cached_json(compute_station_summary(station_code, worker_id=worker_id), etag)
    except Exception as e:
        logger.error("Mobile API summary failed", extra={
            'station_code': station_code,
            'error': str(e),
        })
        return jsonify({'error': 'summary_failed', 'detail': str(e)}), 500


# ============================================================================
# DELTA SYNC (zmiany od timestamp)
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/orders/since', methods=['GET'])
@require_device_token
def station_orders_since(station_code):
    """
    GET /api/mobile/stations/<station_code>/orders/since?ts=<ISO 8601>

    Delta sync. Zwraca:
    - all_ids: wszystkie zlecenia aktualnie w kolejce (klient wykrywa usunięte)
    - changed: pełne DTO dla zleceń z updated_at > ts
    """
    # Alias okresu przejściowego — jak w /orders i /summary. Kod kanoniczny
    # wraca w polu station_code odpowiedzi (element kontraktu Androida).
    station_code = resolve_station_code(station_code)

    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    ts_raw = request.args.get('ts', '').strip()
    if not ts_raw:
        return jsonify({
            'error': 'missing_ts',
            'detail': 'Wymagany parametr ?ts=<ISO 8601 timestamp>',
        }), 400

    try:
        since_ts = parse_since_ts(ts_raw)
    except ValueError as e:
        return jsonify({'error': 'invalid_ts', 'detail': str(e)}), 400

    try:
        return jsonify(get_station_queue_delta(station_code, since_ts)), 200
    except Exception as e:
        logger.error("Mobile API delta failed", extra={
            'station_code': station_code,
            'since_ts': ts_raw,
            'error': str(e),
        })
        return jsonify({'error': 'delta_failed', 'detail': str(e)}), 500


# ============================================================================
# APP VERSION / APK (publiczne — appka pyta przed rejestracją)
# ============================================================================

@mobile_api_bp.route('/app/version', methods=['GET'])
def app_version():
    """
    GET /api/mobile/app/version

    Metadane najnowszego aktywnego release'u APK. Publiczne (klient woła
    przed rejestracją do sanity-check'u). Gdy w bazie nie ma żadnego release'u,
    zwraca {"version_code": 0} — klient interpretuje "brak update'ów".
    """
    return jsonify(get_app_version_info()), 200


@mobile_api_bp.route('/app/apk', methods=['GET'])
@require_device_token
def app_apk():
    """
    GET /api/mobile/app/apk?version=<int>

    Streaming pliku APK dla zadanego version_code. Wymaga JWT (tablet musi
    być zarejestrowany). 400 gdy brak/zły parametr `version`, 404 gdy release
    nie istnieje lub jest nieaktywny.
    """
    version_raw = request.args.get('version', '').strip()
    if not version_raw:
        return jsonify({
            'error': 'missing_version',
            'detail': 'Wymagany parametr ?version=<int> (version_code z APK).',
        }), 400
    try:
        version_code = int(version_raw)
    except ValueError:
        return jsonify({
            'error': 'invalid_version',
            'detail': f'version_code musi być liczbą, otrzymano: {version_raw!r}',
        }), 400

    return stream_apk_response(version_code)


# ============================================================================
# DRUKOWANIE ETYKIET (MOBILE)
# ============================================================================


def _profil_do_logu():
    """
    Kto wydrukował etykietę — WYŁĄCZNIE do logu, bez zapisu w bazie.

    Decyzja właściciela: wydruk etykiety to czynność pomocnicza, nie praca
    produkcyjna, więc nie zasługuje na kolumnę ani na wiersz atrybucji.
    W logu zostaje, bo przy sporze "kto wydrukował tę etykietę" to jedyny ślad,
    a kosztuje jedno pole w zdarzeniu, które i tak powstaje.

    Nagłówek jest tu MIĘKKI: błędny albo nieznany profil nie może zablokować
    druku. Etykieta bywa potrzebna natychmiast, a brak nazwiska w logu jest
    nieporównanie mniej dotkliwy niż stanowisko, które nie może niczego okleić.
    """
    surowy = request.headers.get('X-Worker-Ids')
    if not surowy:
        return None
    try:
        worker_ids = worker_service.resolve_worker_ids(surowy, required=False)
    except WorkerError as e:
        logger.info("Wydruk etykiety: nagłówek profilu odrzucony, drukuję mimo to",
                    extra={'device_id': g.device.device_id, 'powod': e.error_code})
        return None
    return worker_ids[0] if worker_ids else None


@mobile_api_bp.route('/products/<short_product_id>/print-label', methods=['POST'])
@require_device_token
def mobile_print_label_single(short_product_id):
    # Ten endpoint OMIJA _resolve_station_code (czyta JWT wprost), więc alias
    # okresu przejściowego rozwijamy tutaj osobno. Bez tego tablet
    # z niezmigrowanym wierszem prod_devices dostaje 403 StationNotAllowed.
    station_code = resolve_station_code((g.device.station_code or '').strip())
    worker_id = _profil_do_logu()
    try:
        result = label_print_service.print_labels_batch(
            [short_product_id],
            station_code,
            {'type': 'device', 'id': g.device.device_id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    logger.info("Mobile API: wydruk etykiety", extra={
        'short_product_id': short_product_id,
        'station_code': station_code,
        'device_id': g.device.device_id,
        'worker_id': worker_id,
        'sukces': result['success'],
    })

    if result['connection_error']:
        return jsonify({'success': False, 'message': result['message']}), 502
    return jsonify({'success': result['success'], 'message': result['message']}), 200


@mobile_api_bp.route('/products/by-id/<int:product_id>/print-label', methods=['POST'])
@require_device_token
def mobile_print_label_by_id(product_id):
    """
    POST /api/mobile/v1/products/by-id/<product_id>/print-label

    Druk WYBRANYCH sztuk pozycji — panel kafelków aplikacji stanowiskowej.
    Body (wykluczające się wzajemnie, brak obu = wszystkie sztuki jak dotąd):

        {"upTo": N,    "offsetSeen": O}   drukuj sztuki od pierwszej nieoznaczonej do N
        {"reprint": K, "offsetSeen": O}   przedrukuj dokładnie sztukę K

    Numery są GLOBALNE — takie, jakie wychodzą na papier i jakie operator widzi
    na kafelku. Offset zamówienia odejmujemy tutaj.

    ADRESOWANIE PO id, NIE short_product_id: ten drugi dzielą oryginał i doróbka
    (rework_service), więc żądanie trafiałoby w losowy z dwóch wierszy — a przy
    `upTo`, które USTAWIA licznik, operator widziałby brak reakcji i naciskał
    dalej. Stary endpoint po short_product_id zostaje dla APK w terenie.
    """
    station_code = resolve_station_code((g.device.station_code or '').strip())
    dane = request.get_json(silent=True) or {}
    up_to = dane.get('upTo')
    reprint = dane.get('reprint')
    labels = dane.get('labels')

    podane = [x for x in (up_to, reprint, labels) if x is not None]
    if len(podane) > 1:
        return jsonify({'success': False, 'error': 'parametry_wykluczaja_sie',
                        'message': 'Podaj tylko jedno z: labels, upTo, reprint.'}), 400

    # Blokada wiersza: `upTo` to odczyt-modyfikacja-zapis licznika, a dwa tablety
    # na jednym zamówieniu to realny przypadek. Wartość bezwzględna chroni przed
    # wydrukowaniem nie tych sztuk, ale nie przed zgubionym zapisem.
    item = (ProductionItem.query
            .filter_by(id=product_id)
            .with_for_update()
            .first())
    if item is None:
        return jsonify({'success': False, 'error': 'product_not_found'}), 404

    ilosc = item.quantity or 1
    offset, total = compute_label_offsets([item]).get(item.id, (0, ilosc))

    units_by_item = None

    if podane:
        widziany = dane.get('offsetSeen')
        # Rozbieżność offsetu znaczy, że skład zamówienia zmienił się między
        # odczytem kolejki a naciśnięciem przycisku. Bez tego porównania druk
        # poszedłby po cichu na inne sztuki, niż widział operator.
        if widziany is None or int(widziany) != offset:
            return jsonify({
                'success': False, 'error': 'offset_mismatch',
                'message': 'Skład zamówienia zmienił się — odśwież kolejkę.',
                'label_offset': offset, 'label_total': total,
            }), 409

        juz_wydrukowane = label_print_service.wydrukowane_sztuki(item)
        try:
            if labels is not None:
                # Wolny wybór sztuk — podstawowa droga panelu kafelków.
                wybrane = sorted({int(n) - offset for n in labels})
            elif up_to is not None:
                # Skrót „drukuj do N": od pierwszej nieoznaczonej do wskazanej.
                gorna = int(up_to) - offset
                wybrane = [n for n in range(1, gorna + 1) if n not in juz_wydrukowane]
            else:
                wybrane = [int(reprint) - offset]
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'nieprawidlowy_numer'}), 400

        poza = [n for n in wybrane if not (1 <= n <= ilosc)]
        if poza or (labels is not None and not wybrane):
            return jsonify({
                'success': False, 'error': 'numer_poza_zakresem',
                'message': f'Pozycja ma {ilosc} szt., numery {offset + 1}..{offset + ilosc}.',
            }), 400

        units_by_item = {item.id: wybrane}

        if not wybrane:
            # `upTo` poniżej stanu — bezpieczny no-op, nie sukces i nie błąd.
            # Do przedrukowania służy wskazanie sztuki wprost przez `labels`.
            return jsonify({
                'success': True, 'copies_printed': 0,
                'message': 'Nic do wydrukowania — te sztuki są już oznaczone.',
                'label_print_count': item.label_print_count or 0,
                'label_printed': [n + offset for n in juz_wydrukowane],
            }), 200

    try:
        result = label_print_service.print_labels_batch(
            [item.short_product_id], station_code,
            {'type': 'device', 'id': g.device.device_id},
            units_by_item=units_by_item,
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    # Stan prowadzi serwis: dopisuje wydrukowane sztuki do zbioru pozycji.
    # Przedruk sztuki już w zbiorze niczego nie zmienia, więc reguła
    # „przedruk nie rusza stanu" nie wymaga tu osobnego kroku.
    db.session.commit()

    logger.info("Mobile API: wydruk wybranych sztuk", extra={
        'product_id': product_id, 'short_product_id': item.short_product_id,
        'station_code': station_code, 'device_id': g.device.device_id,
        'labels': labels, 'upTo': up_to, 'reprint': reprint,
        'sukces': result['success'],
    })

    if result['connection_error']:
        return jsonify({'success': False, 'message': result['message']}), 502

    # Liczba kartek, które poszły — z wyników serwisu, a gdy ich nie poda,
    # z liczby sztuk, o które prosiliśmy. Pole ma być ZAWSZE liczbą, także
    # przy `labels`: gałąź no-op wyżej zwraca 0, więc brak pola tutaj kazałby
    # aplikacji odróżniać „zero kartek" od „nie wiadomo ile".
    wydrukowano = sum(r.get('copies_printed') or 0 for r in result.get('results') or [])
    if not result.get('results') and units_by_item:
        wydrukowano = len(units_by_item[item.id])

    wydrukowane = [n + offset for n in label_print_service.wydrukowane_sztuki(item)]
    return jsonify({
        'success': result['success'],
        'message': result['message'],
        'copies_printed': wydrukowano,
        # Licznik z długości listy, nie z kolumny — tak samo jak w kolejce.
        # Rekordy sprzed migracji stanu mają kolumnę zawyżoną przedrukami.
        'label_print_count': len(wydrukowane),
        'label_printed': wydrukowane,
        'label_offset': offset,
        'label_total': total,
    }), 200


@mobile_api_bp.route('/orders/<int:baselinker_order_id>/print-labels', methods=['POST'])
@require_device_token
def mobile_print_labels_for_order(baselinker_order_id):
    # Bliźniacza normalizacja do mobile_print_label_single — ten endpoint też
    # omija _resolve_station_code i czyta kod stanowiska z JWT wprost.
    station_code = resolve_station_code((g.device.station_code or '').strip())
    worker_id = _profil_do_logu()
    items = (ProductionItem.query
             .join(ProductionOrder)
             .filter(ProductionOrder.baselinker_order_id == baselinker_order_id)
             .order_by(ProductionItem.product_sequence_in_order)
             .all())
    if not items:
        return jsonify({'success': False, 'message': 'Brak produktów w zamówieniu.'}), 404

    # „Zamówienie najpierw” (logistyka etap 4, krok 4.4a), TYLKO w trybie agenta (LABEL_PRINTER_USE_AGENT;
    # label_print_service.tryb_agenta, ten sam pomocnik, którym print_labels_batch wybiera tryb wysyłki, więc
    # blokada i tryb zawsze się zgadzają). W trybie agenta druk zapisuje liczniki wydrukowanych
    # sztuk pozycja po pozycji (flush), w kolejności numeracji etykiet (product_sequence_in_order). Doróbka
    # kopiuje sekwencję oryginału, więc ta kolejność nie jest kolejnością id, w której ZAKOŃCZ blokuje pozycje —
    # bez wspólnej blokady zamówienia to cykl (MySQL 1213). Blokujemy więc zamówienie i wszystkie jego pozycje,
    # zanim cokolwiek zapiszemy; kolejność druku etykiet zostaje bez zmian (short_ids niżej z `items`).
    # W trybie TCP cyklu nie ma: pętla druku nie robi zapytań, więc zapisy pozycji idą w końcowym commicie,
    # w kolejności klucza głównego, czyli rosnąco jak w ZAKOŃCZ. Blokada trzymana przez druk po sieci (przy
    # niedostępnej drukarce do (retry_count + 1) × timeout_seconds, domyślnie ok. 6 s) tylko wstrzymywałaby
    # ZAKOŃCZ tego zamówienia.
    if label_print_service.tryb_agenta():
        blokady_zamowien.zablokuj_zamowienie(items[0].order_id)

    short_ids = [i.short_product_id for i in items]
    try:
        result = label_print_service.print_labels_batch(
            short_ids,
            station_code,
            {'type': 'device', 'id': g.device.device_id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    logger.info("Mobile API: wydruk etykiet zamówienia", extra={
        'baselinker_order_id': baselinker_order_id,
        'station_code': station_code,
        'device_id': g.device.device_id,
        'worker_id': worker_id,
        'etykiet': len(short_ids),
        'udanych': result['success_count'],
    })

    if result['connection_error']:
        return jsonify({
            'success': False,
            'success_count': 0,
            'failed_count': len(short_ids),
            'message': result['message'],
        }), 502
    return jsonify({
        'success': result['success'],
        'success_count': result['success_count'],
        'failed_count': result['failed_count'],
        'message': result['message'],
    }), 200


# ============================================================================
# PACZKI (logistyka etap 4, krok 4.2 — spec 7.2 i 7.3)
# ============================================================================

def _stanowisko_paczek():
    """
    (kod, None), gdy stanowisko z JWT deklaruje paczki i drukuje ich etykiety
    (paczki.STANOWISKA_PACZEK), inaczej (None, odpowiedź 403). Kod bierzemy z JWT jak
    druk etykiet produktów — klient nie przysyła go w body, więc nie ma czego porównywać
    pod kątem station_mismatch.
    """
    from modules.production.logistics.services import paczki
    kod = resolve_station_code((g.device.station_code or '').strip())
    if kod not in paczki.STANOWISKA_PACZEK:
        return None, (jsonify({
            'error': 'station_not_allowed',
            'message': u'Paczki deklaruje i drukuje stanowisko Pakowanie albo Weryfikacja.',
        }), 403)
    return kod, None


def _zamowienie_po_numerze(numer, do_zapisu=False):
    """
    Najnowsze zamówienie o numerze wewnętrznym (licznik numerów startuje co roku od nowa,
    więc numer się powtarza — bierzemy wyższe id). `do_zapisu=True` — z blokadą wiersza
    (FOR UPDATE).

    Id ustalamy odczytem BEZ blokady i dopiero po kluczu głównym blokujemy wiersz:
    kolumna internal_order_number nie ma indeksu, więc `FOR UPDATE` po niej skanuje
    tabelę i InnoDB (REPEATABLE READ) zakłada blokady next-key na prawie całym
    prod_orders, czyli wstrzymuje każdy zapis do zamówień na hali.
    """
    order_id = (db.session.query(ProductionOrder.id)
                .filter(ProductionOrder.internal_order_number == str(numer).strip())
                .order_by(ProductionOrder.id.desc())
                .limit(1)
                .scalar())
    if order_id is None:
        return None
    zapytanie = ProductionOrder.query.filter_by(id=order_id)
    if do_zapisu:
        zapytanie = zapytanie.with_for_update().populate_existing()
    return zapytanie.first()


def _brak_zamowienia(numer):
    return jsonify({'error': 'order_not_found',
                    'message': u'Nie ma zamówienia {}.'.format(numer)}), 404


def _blad_paczek(e):
    return jsonify({'error': e.kod, 'message': e.komunikat}), e.status


def _aktor():
    return {'type': 'device', 'id': g.device.device_id}


def _odpowiedz_paczek(order, paczki_lista, **dodatkowe):
    from modules.production.logistics.services import paczki
    dane = {
        'internal_order_number': order.internal_order_number,
        'packages_declared_at': (order.packages_declared_at.isoformat()
                                 if order.packages_declared_at else None),
        'packages': [paczki.serializuj_paczke(p) for p in paczki_lista],
    }
    dane.update(dodatkowe)
    return dane


@mobile_api_bp.route('/orders/<numer>/packages', methods=['GET'])
@require_device_token
def order_packages(numer):
    """
    GET /api/mobile/orders/<internal_order_number>/packages — aktualne paczki zamówienia
    (decyzja Konrada 30.09: tablet pokazuje je i drukuje ponownie jedną albo wszystkie).
    Każde stanowisko może czytać. Bez cache: stan zmienia się deklaracją z innego urządzenia.
    """
    from modules.production.logistics.services import paczki
    order = _zamowienie_po_numerze(numer)
    if order is None:
        return _brak_zamowienia(numer)
    return no_store_json(_odpowiedz_paczek(order, paczki.aktualne_paczki(order.id)))


@mobile_api_bp.route('/orders/<numer>/packages', methods=['PUT'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_packages_declare(numer):
    """
    PUT /api/mobile/orders/<internal_order_number>/packages — deklaracja paczek (spec 7.2).

    Body: {"kind": "paczka"|"paleta", "count": 1..10, "pallet_type": "eur"|"niestandardowa"|null,
           "length_cm": int|null, "width_cm": int|null}

    Appka wysyła ją po „ZAKOŃCZ”, który domyka zamówienie — po zakończeniach pozycji, tą samą
    kolejką offline. 409 order_not_packed jest w BLEDY_DO_PONOWIENIA (niezapamiętane): kolejka
    appki nie gwarantuje, że wszystkie COMPLETE przeszły przed deklaracją, więc ten sam
    X-Operation-Id musi przejść, gdy zamówienie się domknie. Stara appka pakuje bez deklaracji
    (backend to przyjmuje), a nowa appka na starym backendzie dostaje 404 i pomija deklarację.
    """
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    try:
        deklaracja = paczki.waliduj_deklaracje(request.get_json(silent=True))
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    # Kolejność blokad: pracownicy → blokada deklaracji paczek → wiersz zamówienia → paczki.
    # Pracownicy PRZED blokadą zamówienia: order_complete też najpierw dotyka wierszy sesji
    # (touch_sessions), a dopiero potem blokuje zamówienie i jego pozycje — odwrócona kolejność
    # dawałaby zakleszczenie (MySQL 1213) przy równoległym „ZAKOŃCZ” i deklaracji.
    worker_ids, _sesje, err = _resolve_workers()
    if err:
        return err
    # Jedna deklaracja naraz: bez tego dwie pierwsze deklaracje różnych zamówień blokowały
    # tę samą lukę indeksu prod_packages i zakleszczały się (MySQL 1213) — patrz docstring.
    paczki.zablokuj_deklaracje()
    order = _zamowienie_po_numerze(numer, do_zapisu=True)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        nowe, uniewaznione = paczki.zadeklaruj(order, deklaracja, stanowisko, _aktor(),
                                               worker_id=worker_ids[0] if worker_ids else None,
                                               device_id=g.device.id)
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)

    tekst = paczki.opis(deklaracja.kind, deklaracja.count, deklaracja.pallet_type,
                        deklaracja.length_cm, deklaracja.width_cm)
    logger.info("Mobile API: paczki zadeklarowane", extra={
        'internal_order_number': order.internal_order_number, 'paczki': tekst,
        'station_code': stanowisko, 'device_id': g.device.device_id,
    })
    komunikat = u'Zadeklarowano {}. Etykiety poszły do drukarki paczek.'.format(tekst)
    if uniewaznione:
        komunikat += u' Poprzednie etykiety ({}) są nieaktualne.'.format(uniewaznione)
    return jsonify(_odpowiedz_paczek(order, nowe, labels_queued=len(nowe), message=komunikat)), 200


@mobile_api_bp.route('/packages/<int:package_id>/print', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def package_print(package_id):
    """
    POST /api/mobile/packages/<id>/print — ponowny druk etykiety jednej paczki (spec 7.3),
    z tabletu pakowania i (krok 4.3) telefonu Weryfikacji. Etykieta z bieżącymi danymi.
    X-Operation-Id chroni przed podwójnym wydrukiem przy powtórce po timeoucie.
    """
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    paczka = (ProductionPackage.query.filter_by(id=package_id)
              .with_for_update().populate_existing().first())
    if paczka is None:
        return jsonify({'error': 'package_not_found',
                        'message': u'Nie ma paczki P-{}.'.format(package_id)}), 404
    try:
        paczki.drukuj_ponownie_paczke(paczka, stanowisko, _aktor())
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    logger.info("Mobile API: ponowny druk etykiety paczki", extra={
        'package': paczka.kod, 'station_code': stanowisko, 'device_id': g.device.device_id,
        'worker_id': _profil_do_logu(),
    })
    return jsonify({
        'success': True, 'labels_queued': 1, 'package': paczki.serializuj_paczke(paczka),
        'message': u'Etykieta {} poszła do drukarki paczek.'.format(paczka.kod),
    }), 200


@mobile_api_bp.route('/orders/<numer>/packages/print', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_packages_print(numer):
    """POST /api/mobile/orders/<internal_order_number>/packages/print — ponowny druk etykiet
    wszystkich ważnych paczek zamówienia (spec 7.3)."""
    from modules.production.logistics.services import paczki
    stanowisko, err = _stanowisko_paczek()
    if err:
        return err
    order = _zamowienie_po_numerze(numer, do_zapisu=True)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        aktualne = paczki.drukuj_ponownie_zamowienie(order, stanowisko, _aktor())
    except paczki.PaczkiBlad as e:
        return _blad_paczek(e)
    logger.info("Mobile API: ponowny druk etykiet paczek zamówienia", extra={
        'internal_order_number': order.internal_order_number, 'etykiet': len(aktualne),
        'station_code': stanowisko, 'device_id': g.device.device_id,
        'worker_id': _profil_do_logu(),
    })
    return jsonify({
        'success': True, 'labels_queued': len(aktualne),
        'packages': [paczki.serializuj_paczke(p) for p in aktualne],
        'message': u'Etykiety paczek zamówienia {} ({}) poszły do drukarki paczek.'.format(
            order.internal_order_number, len(aktualne)),
    }), 200


# ============================================================================
# DEVICES — heartbeat / telemetria
# ============================================================================

@mobile_api_bp.route('/devices/heartbeat', methods=['POST'])
@require_device_token
def device_heartbeat():
    """
    Tablet wysyła co 15 min telemetrię (bateria/temp/wersja APK/IP).
    Brak idempotency — każdy heartbeat nadpisuje pola na ProductionDevice.
    """
    from modules.production.services.mobile_api_service import (
        validate_heartbeat_payload,
        get_local_now,
    )

    payload = request.get_json(silent=True) or {}
    err = validate_heartbeat_payload(payload)
    if err:
        return jsonify({'error': 'validation', 'detail': err}), 422

    device = g.device
    device.last_heartbeat_at = get_local_now()
    device.last_battery_pct = payload.get('battery_pct')
    device.last_battery_charging = payload.get('battery_charging')
    device.last_temperature_c = payload.get('temperature_c')
    device.last_app_version_code = payload['app_version_code']
    device.app_version = payload['app_version_name']
    ip_addr = payload.get('ip_address')
    if ip_addr:
        device.last_ip = ip_addr

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API: heartbeat commit failed", extra={
            'device_id': device.device_id,
            'station_code': device.station_code,
            'error': str(e),
        })
        return jsonify({'error': 'internal'}), 500

    logger.info("Mobile API: heartbeat OK", extra={
        'event': 'device_heartbeat',
        'device_id': device.device_id,
        'station_code': device.station_code,
        'battery_pct': payload.get('battery_pct'),
        'battery_charging': payload.get('battery_charging'),
        'temperature_c': payload.get('temperature_c'),
        'app_version_code': payload['app_version_code'],
        'app_version_name': payload['app_version_name'],
    })

    return '', 204


# ============================================================================
# PROFILE PRACOWNIKÓW
# docs/worker-profiles-backend.md §6
# ============================================================================

def _worker_error_response(e):
    """WorkerError → (JSON, status) w konwencji mobile API ({error, detail})."""
    payload, status = e.as_response()
    return jsonify(payload), status


@mobile_api_bp.route('/workers', methods=['GET'])
@require_device_token
def workers_catalog():
    """
    GET /api/mobile/workers

    Katalog aktywnych pracowników do ekranu wyboru profilu, razem z PEŁNĄ
    konfiguracją (selection_required, idle_timeout_minutes, night_cutoff,
    quick_pick_count) — apka nie hardkoduje żadnej z tych wartości i nie
    pobiera ich osobnym requestem.

    recent_on_station liczone dla stanowiska z JWT urządzenia — zasila sekcję
    "szybki wybór".

    ETag — JEDEN string w dwóch miejscach. Apka wysyła jako If-None-Match nie
    nagłówek ETag, tylko POLE `catalog_version` z ciała (WorkerRepositoryImpl:
    `configStore.catalogVersion()`, zapisywane z `body.catalogVersion`).
    Dopóki były to różne stringi, warunkowy GET NIGDY nie trafiał: tablet
    dostawał 200 z pełnym katalogiem przy każdym starcie i przy każdym
    odświeżeniu. Dlatego `catalog_version` = dokładnie ta wartość, którą
    wystawiamy w nagłówku.

    W ETag wchodzą TRZY rzeczy (po segmencie kształtu KSZTALT_KATALOGU_PRACOWNIKOW, który tuż za nazwą
    `workers` unieważnia katalog zapamiętany przy starszym zestawie pól):
      1. station_code z JWT — recent_on_station jest per stanowisko;
      2. MAX(prod_workers.updated_at) — zmiana katalogu (dodanie, edycja,
         dezaktywacja pracownika);
      3. odcisk WARTOŚCI konfiguracji: selection_required, idle_timeout_minutes,
         night_cutoff, quick_pick_count.

    Punkt 3 liczymy z tego, co idzie w ciele, a nie z MAX(prod_config
    .updated_at) — patrz get_config_fingerprint(). Plus wymuszenie świeżości
    konfiguracji w tym procesie (odswiez_konfiguracje_jesli_nieaktualna),
    inaczej kill-switch zmieniony z panelu obsługiwanego przez inny proces
    Passengera nie dojechałby na tablety.
    """
    # Alias okresu przejściowego. Bez tego recent_on_station liczy się po
    # martwym kodzie (prod_worker_sessions są już przepisane na 'edges')
    # i sekcja „szybki wybór" profili na tablecie Krawędzi jest pusta —
    # bez błędu i bez logu. Kod wchodzi też do ETaga (:860), więc oba
    # tablety tego samego stanowiska dzielą klucz cache.
    station_code = resolve_station_code(g.device.station_code)

    worker_service.odswiez_konfiguracje_jesli_nieaktualna()

    etag = make_weak_etag('workers', KSZTALT_KATALOGU_PRACOWNIKOW, station_code,
                          worker_service.get_catalog_version(),
                          worker_service.get_config_fingerprint())
    if if_none_match(etag):
        return not_modified(etag)

    katalog = worker_service.build_mobile_catalog(station_code=station_code,
                                                  catalog_version=etag)
    return cached_json(katalog, etag)


def _kontrakt_sesji(sesje):
    """
    Trzy pola KONTRAKTU PRZEWODOWEGO sesji — na POZIOMIE GŁÓWNYM odpowiedzi:

        {"session_group": "...", "worker_ids": [1], "started_at": "..."}

    Dokładnie tego szuka apka: `ActiveSessionResponseDto` ma te trzy pola
    i nic więcej, a `RouterViewModel` porównuje `session_group` z lokalnym,
    żeby wykryć przejęcie profilu. Zagnieżdżenie ich w `sessions[]` (jak było)
    znaczyło, że tablet czytał `worker_ids` = pustą listę z domyślnej wartości
    DTO, choć sesja istniała.

    Pola diagnostyczne (nazwiska, kolory, stanowisko) dokładamy OBOK, nie
    zamiast — apka ma `ignoreUnknownKeys = true`, więc nadmiar jej nie boli,
    a panel i podgląd ruchu z tabletu na nim stoją.

    Pusta lista → session_group: null + worker_ids: [] (nie brak klucza):
    kontrakt mówi wprost „przy braku sesji 200 z session_group: null", a stały
    zestaw kluczy oszczędza apce gałęzi na null vs. brak pola.
    """
    if not sesje:
        return {'session_group': None, 'worker_ids': [], 'started_at': None}

    return {
        'session_group': sesje[0].session_group,
        'worker_ids': [s.worker_id for s in sesje],
        'started_at': sesje[0].started_at.isoformat() if sesje[0].started_at else None,
    }


def _biezaca_grupa(sesje):
    """
    Z otwartych sesji urządzenia zostawia NAJNOWSZĄ grupę.

    Po wariancie A urządzenie ma normalnie jedną otwartą grupę, ale dane
    zastane (sesje sprzed wdrożenia, domykane dopiero przy kolejnym starcie
    albo przez cron) potrafią zostawić dwie. Wtedy `session_group` musi
    wskazywać tę, przy której ktoś faktycznie stoi — get_active_sessions()
    sortuje rosnąco, więc branie `sesje[0]` oddawało apce grupę NAJSTARSZĄ,
    czyli widmo.
    """
    if not sesje:
        return []
    najnowsza = max(sesje, key=lambda s: (s.started_at, s.id)).session_group
    return [s for s in sesje if s.session_group == najnowsza]


def _odpowiedz_startu(sesje, superseded=False):
    """
    Ciało odpowiedzi /sessions/start. Ten sam kształt dla startu udanego
    i dla spóźnionego — apka ma jeden parser, a różnicę widzi po fladze
    `superseded`.

    Kształt jest NADZBIOREM /sessions/active (te same trzy pola kontraktu
    plus `sessions[]` i `expires_at`), żeby obie odpowiedzi dały się czytać
    jednym DTO.
    """
    dane = _kontrakt_sesji(sesje)
    dane.update({
        'sessions': [
            {'id': s.id, 'worker_id': s.worker_id, 'started_at': s.started_at.isoformat()}
            for s in sesje
        ],
        'expires_at': None,
        # Zawsze obecne (nie tylko przy True) — stały zestaw kluczy pozwala
        # apce czytać flagę bez rozróżniania null/brak.
        'superseded': bool(superseded),
    })
    if sesje:
        wygasa = sesje[0].started_at + timedelta(
            minutes=worker_service.get_idle_timeout_minutes())
        dane['expires_at'] = wygasa.isoformat()
    return dane


@mobile_api_bp.route('/sessions/start', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def session_start():
    """
    POST /api/mobile/sessions/start

    Body JSON: {
        worker_ids: [int],        wymagane
        station_code: str,        opcjonalne — domyślnie stanowisko z JWT
        session_group: str,       UUID wygenerowany w apce (klucz encji w Room)
        started_at: ISO8601       opcjonalne — sesja mogła zacząć się offline
    }

    STREFA: started_at bez offsetu jest czytany jako CZAS LOKALNY
    (parse_client_local_ts) — tak samo jak measured_at trakowni i dokładnie tak,
    jak apka to wysyła (SyncQueueDrainer.toLocalIso). Offset, gdy przyjdzie,
    jest przeliczany. Do 08.2026 szedł tu parse_since_ts, który naive czytał
    jako UTC i przesuwał każdą sesję o offset strefy.

    Domykane z end_reason='replaced' są poprzednie sesje TEGO urządzenia
    (zmiana obsady na tablecie) ORAZ sesje WSKAZANYCH pracowników wiszące na
    innych tabletach (wariant A: przejęcie profilu, jeden pracownik = jedna
    sesja). Kolizja NIE jest błędem — nigdy nie odpowiadamy 409, bo w kolejce
    offline 4xx oznacza wpis do interwencji biura i zatrzymuje synchronizację.

    Kod: ZAWSZE 200 dla żądania przyjętego — także przy kolizji (przejęcie
    profilu) i przy starcie spóźnionym. Wcześniej udany start dawał 201.
    Zmiana jest czysto kontraktowa: dokument mobilny mówi 200, a klient
    (SyncQueueDrainer.throwIfError → Response.isSuccessful, classifySyncOutcome
    `200..299 -> Success`) traktuje całe 2xx tak samo, więc nic po drodze się
    nie psuje. Zostawienie 201 utrzymywałoby rozjazd z dokumentem, o który
    prędzej czy później rozbije się kontraktowy test po ich stronie.

    Czy sesja została OTWARTA, mówi pole `superseded` w ciele (false = otwarta,
    true = zaksięgowana jako historyczna), a nie kod HTTP.

    Idempotency: powtórka z tym samym X-Operation-Id zwraca zapisaną odpowiedź,
    nie zakłada drugiego kompletu sesji.
    """
    data = request.get_json(silent=True) or {}

    worker_ids = data.get('worker_ids')
    if not isinstance(worker_ids, list) or not worker_ids:
        return jsonify({'error': 'invalid_worker_ids',
                        'detail': 'worker_ids musi być niepustą listą'}), 422
    try:
        worker_ids = [int(w) for w in worker_ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_worker_ids',
                        'detail': 'worker_ids musi zawierać liczby'}), 422

    # Sesja pracownika stoi na KAŻDYM stanowisku, także poza pipeline'em
    # produktów — stąd pełna lista kodów zamiast mapy statusów produktu.
    station_code, err = _resolve_station_code(
        data.get('station_code'),
        znane_kody=ProductionDevice.VALID_STATION_CODES)
    if err:
        return err

    started_at = None
    if data.get('started_at'):
        try:
            started_at = parse_client_local_ts(data['started_at'])
        except ValueError as e:
            return jsonify({'error': 'invalid_started_at', 'detail': str(e)}), 422

    try:
        sesje = worker_service.start_session(
            worker_ids, station_code,
            device_id=g.device.device_id,
            session_group=data.get('session_group'),
            started_at=started_at,
            source='mobile',
            commit=False,          # commit robi @with_idempotency
        )
    except WorkerError as e:
        return _worker_error_response(e)

    if not sesje[0].is_open:
        # SPÓŹNIONY START: obsadę przejęła w międzyczasie nowsza sesja, więc
        # żądanie zostało zaksięgowane jako sesja historyczna (już domknięta)
        # i NIE wróciło na halę. Oddajemy stan BIEŻĄCY tego urządzenia (ten
        # sam, który za chwilę pokaże /sessions/active), żeby tablet od razu
        # wiedział, że jego grupa jest nieaktualna i wrócił na bramkę. Pusty
        # stan = session_group: null, dokładnie jak w /sessions/active.
        biezace = _biezaca_grupa(
            worker_service.get_active_sessions(device_id=g.device.device_id))
        return jsonify(_odpowiedz_startu(biezace, superseded=True)), 200

    return jsonify(_odpowiedz_startu(sesje)), 200


@mobile_api_bp.route('/sessions/end', methods=['POST'])
@require_device_token
@with_idempotency
def session_end():
    """
    POST /api/mobile/sessions/end

    Body JSON: { session_group: str, ended_at: ISO8601, reason: str }

    Dozwolone reason od klienta: manual, idle_timeout, night_cutoff. Apka
    egzekwuje timeouty lokalnie, żeby UX był natychmiastowy, i raportuje powód —
    serwer go przyjmuje zamiast nadpisywać własnym. 'replaced' i 'admin'
    ustawia wyłącznie backend, więc przysłane z tabletu dają 422.

    ZAWSZE 200 dla poprawnego żądania — również gdy grupa jest już domknięta
    albo w ogóle nie istnieje w bazie. To nie jest kosmetyka kodów:

    - end potrafi przyjść Z KOLEJKI OFFLINE dla sesji, którą serwer domknął
      sam jako 'replaced' (przejęcie profilu). Wcześniejsze 404 klasyfikowało
      się u nich jako Rejected — wpis znikał z kolejki i zliczał się jako błąd
      sesji, choć nic złego się nie stało;
    - 404 było przy tym ZAPAMIĘTYWANE przez @with_idempotency (ten dekorator
      zapisuje 4xx), więc powtórka z tym samym X-Operation-Id dostawała 404
      z bazy, bez wywołania handlera — na zawsze.

    Odpowiadamy JSON-em, nie 204: przy 204 Werkzeug usuwa ciało, a apka
    deklaruje `Response<Unit>` — czyli ciało i tak jest jej obojętne. Ale 200
    Z PUSTYM ciałem wywróciłoby konwerter kotlinx (SerializationException →
    wpis wraca do kolejki jako Transient), więc skoro przechodzimy na 200,
    ciało MUSI być poprawnym obiektem JSON.

    Domknięta sesja NIE dostaje nadpisanego end_reason — ProductionWorkerSession
    .close() jest idempotentne, więc spóźniony 'manual' nie zamaże 'replaced'.
    """
    data = request.get_json(silent=True) or {}

    session_group = (data.get('session_group') or '').strip()
    if not session_group:
        return jsonify({'error': 'missing_session_group'}), 422

    ended_at = None
    if data.get('ended_at'):
        try:
            ended_at = parse_client_local_ts(data['ended_at'])
        except ValueError as e:
            return jsonify({'error': 'invalid_ended_at', 'detail': str(e)}), 422

    try:
        _, domkniete = worker_service.end_session(
            session_group,
            ended_at=ended_at,
            reason=(data.get('reason') or 'manual'),
            device_id=g.device.device_id,
            commit=False,          # commit robi @with_idempotency
        )
    except WorkerError as e:
        return _worker_error_response(e)

    return jsonify({
        'session_group': session_group,
        'closed': domkniete,
        # true = nie było czego domykać (grupa nieznana albo już zamknięta).
        # Apka tego nie czyta, ale w logach ruchu odróżnia realne zamknięcie
        # od spóźnionego echa kolejki.
        'no_op': domkniete == 0,
    }), 200


@mobile_api_bp.route('/sessions/active', methods=['GET'])
@require_device_token
def sessions_active():
    """
    GET /api/mobile/sessions/active

    Otwarta sesja TEGO urządzenia (device_id z JWT — nigdy per pracownik ani
    globalnie). Apka woła to po restarcie/crashu, żeby nie zmuszać do ponownego
    wyboru profilu, ORAZ pollingiem co 60 s, żeby wykryć, że serwer domknął jej
    sesję (przejęcie profilu na innym tablecie albo cron).

    Kontrakt: 200 zawsze — przy braku sesji session_group: null i worker_ids: []
    (nie 404 i nie puste ciało; apka toleruje warianty, ale ustalony jest ten).

    Bez cache: patrz no_store_json(). Endpoint ŚWIADOMIE nie używa cached_json —
    ETag + max-age byłyby tu szkodliwe, bo cała wartość odpowiedzi polega na
    tym, że jest świeża.
    """
    sesje = _biezaca_grupa(
        worker_service.get_active_sessions(device_id=g.device.device_id))

    dane = _kontrakt_sesji(sesje)
    dane.update({
        # Alias okresu przejściowego. Kontrakt przewodowy mówi, że pola
        # station_code w odpowiedziach echują kod KANONICZNY. Bez tego tablet
        # z niezmigrowanym wierszem prod_devices dostaje tu 'finishing',
        # zapisuje go u siebie i odsyła w ciele operacji mutujących — stary
        # kod krążyłby w kółko mimo poprawnej migracji bazy.
        'station_code': resolve_station_code(g.device.station_code),
        'idle_timeout_minutes': worker_service.get_idle_timeout_minutes(),
        'sessions': [
            {
                'id': s.id,
                'worker_id': s.worker_id,
                'worker_name': s.worker.full_name if s.worker else None,
                'initials': s.worker.initials if s.worker else None,
                'color_hex': s.worker.tile_color if s.worker else None,
                # Wiersz sesji otwarty PRZED migracją niesie jeszcze stary kod;
                # to pole rysuje na tablecie nagłówek stanowiska.
                'station_code': resolve_station_code(s.station_code),
                'started_at': s.started_at.isoformat() if s.started_at else None,
                'last_activity_at': (s.last_activity_at.isoformat()
                                     if s.last_activity_at else None),
            }
            for s in sesje
        ],
    })
    return no_store_json(dane)
