"""
Audyt zdarzeń produktu — ustalanie aktora i zapis zmian.

Listener SQLAlchemy (before_flush) wykrywa zmiany śledzonych pól na
ProductionProduct i dopisuje wiersze do prod_product_events w tej samej
transakcji. Dzięki temu nie da się zmienić statusu bez zostawienia śladu,
także ze ścieżek, które powstaną w przyszłości.
"""
import time
from collections import namedtuple

from modules.logging import get_structured_logger

logger = get_structured_logger('production.product_events')

Actor = namedtuple('Actor', 'actor_type user_id device_id source endpoint ip_address')

# Śledzone pola ProductionProduct → typ zdarzenia
TRACKED_FIELDS = {
    'current_status': 'status_change',
    'priority_rank': 'priority_change',
}


def build_actor(*, user=None, device=None, endpoint=None, ip_address=None,
                in_request=False):
    """
    Czysta funkcja: składa Actor z podanych elementów kontekstu.

    Urządzenie ma pierwszeństwo przed użytkownikiem — żądania z tabletu
    lecą przez JWT urządzenia i to ono jest sprawcą, nawet gdyby w tej
    samej przeglądarce istniała sesja web.

    `in_request` odróżnia dwie różne sytuacje, które inaczej trafiały do
    tego samego, mylącego `source='system'`: brak kontekstu żądania w ogóle
    (scheduler, CLI, synchronizacja BaseLinkera) od żądania HTTP, w którym
    po prostu nie ma ani urządzenia, ani zalogowanego użytkownika — czyli
    panelu stanowiskowego (`/production/stations/complete-order`,
    `/production/api/complete-task`), chronionego walidacją IP, a nie
    logowaniem. Operator czytający historię musi umieć odróżnić człowieka
    przy stanowisku od automatu pomijającego stanowiska.
    """
    if device is not None:
        return Actor('device', None, getattr(device, 'device_id', None),
                     'mobile', endpoint, ip_address)

    if user is not None and getattr(user, 'is_authenticated', False):
        return Actor('user', getattr(user, 'id', None), None,
                     'web', endpoint, ip_address)

    if in_request:
        # Żądanie HTTP istnieje, ale nie ma ani urządzenia, ani zalogowanego
        # użytkownika — panel stanowiskowy bez logowania, nie automat.
        return Actor('system', None, None, 'web', endpoint, ip_address)

    return Actor('system', None, None, 'system', endpoint, ip_address)


def current_actor():
    """
    Actor na podstawie bieżącego kontekstu Flaska. Poza requestem
    (scheduler, CLI, testy) zwraca aktora systemowego. Nigdy nie rzuca —
    audyt nie może wywrócić operacji biznesowej.
    """
    try:
        from flask import g, has_request_context, request

        if not has_request_context():
            return build_actor()

        device = getattr(g, 'device', None)

        user = None
        try:
            from flask_login import current_user
            user = current_user
        except Exception:
            user = None

        return build_actor(
            user=user,
            device=device,
            endpoint=request.endpoint,
            ip_address=request.remote_addr,
            # Wołane tylko wtedy, gdy kontekst żądania istnieje (sprawdzone
            # wyżej przez has_request_context) — stąd zawsze True.
            in_request=True,
        )
    except Exception:
        logger.warning("Nie udało się ustalić aktora zdarzenia", exc_info=True)
        return Actor('system', None, None, 'system', None, None)


def build_event_rows(product_id, changes, actor, now):
    """
    Czysta funkcja: zamienia listę zmian (field, old, new) na wiersze
    gotowe do zapisania jako ProductionProductEvent.

    Pomija pola nieśledzone oraz zmiany pozorne (stara wartość == nowa).
    """
    rows = []
    for field, old, new in changes:
        event_type = TRACKED_FIELDS.get(field)
        if event_type is None or old == new:
            continue
        rows.append({
            'production_item_id': product_id,
            'event_type': event_type,
            'old_value': None if old is None else str(old),
            'new_value': None if new is None else str(new),
            'actor_type': actor.actor_type,
            'user_id': actor.user_id,
            'device_id': actor.device_id,
            'source': actor.source,
            'endpoint': actor.endpoint,
            'ip_address': actor.ip_address,
            'created_at': now,
        })
    return rows


# Próg masowej renumeracji kolejki priorytetów. assign_sequential_ranks
# renumeruje rangi CAŁEJ kolejki (setki produktów) przy każdej synchronizacji
# z BaseLinkerem i po kliknięciu przycisku w panelu — jeden taki przebieg
# zalałby historię setkami wierszy „Priorytet: 120 → 119", topiąc nieliczne,
# istotne zmiany statusu. Powyżej tego progu liczbę produktów ze zmianą
# priority_rank w JEDNYM flushu uznajemy za masową renumerację kolejki
# (decyzję o kolejności całej produkcji), a nie decyzję o pojedynczym
# produkcie, i nie zapisujemy dla nich zdarzeń priority_change.
_BULK_PRIORITY_CHANGE_THRESHOLD = 5


def build_event_rows_for_flush(changes_by_product, actor, now):
    """
    Czysta funkcja: jak `build_event_rows`, ale dla WSZYSTKICH produktów
    zmienionych w jednym flushu naraz — tylko widząc całość da się odróżnić
    masową renumerację kolejki priorytetów (setki produktów) od pojedynczej,
    ręcznej decyzji o priorytecie jednego produktu.

    `changes_by_product`: lista (production_item_id, changes), gdzie
    `changes` ma format jak w `build_event_rows` — lista (field, old, new).

    Zdarzenia priority_change są pomijane, gdy:
    - liczba produktów ze zmianą priority_rank w tym flushu przekracza
      `_BULK_PRIORITY_CHANGE_THRESHOLD` (masowa renumeracja kolejki), lub
    - aktorem jest automat (`actor_type == 'system'`) — automat nigdy nie
      podejmuje pojedynczej, świadomej decyzji o priorytecie.

    Zmiany statusu (`status_change`) w tym samym flushu są zawsze zapisywane
    normalnie — filtr dotyczy wyłącznie priority_change.
    """
    priority_change_count = sum(
        1
        for _, changes in changes_by_product
        for field, old, new in changes
        if field == 'priority_rank' and old != new
    )
    suppress_priority = (
        priority_change_count > _BULK_PRIORITY_CHANGE_THRESHOLD
        or actor.actor_type == 'system'
    )

    rows = []
    for product_id, changes in changes_by_product:
        for row in build_event_rows(product_id, changes, actor, now):
            if suppress_priority and row['event_type'] == 'priority_change':
                continue
            rows.append(row)
    return rows


def _extract_changes(obj):
    """Wyciąga (field, old, new) dla śledzonych pól z historii atrybutów ORM."""
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(obj)
    changes = []
    for field in TRACKED_FIELDS:
        history = state.attrs[field].history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        changes.append((field, old, new))
    return changes


_LISTENER_REGISTERED = False

# Co ile sekund wolno ponowić sprawdzenie tabeli audytu, gdy poprzednie
# sprawdzenie wypadło NEGATYWNIE. Wynik pozytywny cache'ujemy na stałe (tabela
# nie zniknie z bazy w trakcie działania procesu), ale wynik negatywny może
# się zmienić — administrator mógł wykonać migrację PO starcie procesu, albo
# baza była tylko chwilowo niedostępna. Bez odświeżania audyt milczałby do
# restartu aplikacji, mimo że tabela od dawna już istnieje.
_TABLE_RECHECK_INTERVAL_SECONDS = 300

_TABLE_AVAILABLE = False
# Moment (time.monotonic()) ostatniego sprawdzenia. None = jeszcze nie
# sprawdzano ani razu (proces dopiero wystartował).
_LAST_CHECK_MONOTONIC = None


def _table_exists():
    """
    Rzeczywiste sprawdzenie w bazie, czy istnieje tabela prod_product_events.

    Wydzielone do osobnej funkcji, żeby dało się je podstawić (monkeypatch)
    w testach jednostkowych bez potrzeby uruchamiania bazy danych.

    UWAGA na wersję SQLAlchemy: projekt trzyma się serii 1.4.x (produkcja
    wymaga SQLAlchemy <2.0), dlatego używamy `sqlalchemy.inspect(engine)
    .has_table(...)` — API z 1.4. W 2.0 preferowane jest
    `sqlalchemy.inspect(engine).has_table(name, schema=...)` w kontekście
    connection lub `Inspector.has_table` na Connection, ale to nie ma tu
    znaczenia dopóki projekt zostaje na 1.4.
    """
    from sqlalchemy import inspect as sa_inspect
    from extensions import db

    return sa_inspect(db.engine).has_table('prod_product_events')


def _audit_table_available(check_fn=_table_exists):
    """
    Zwraca True, jeśli tabela prod_product_events istnieje i audyt może
    bezpiecznie dopisywać do niej wiersze.

    DLACZEGO cache (i dlaczego niesymetryczny): to jest gorący kod — listener
    before_flush wykonuje się przy każdym zapisie w całej aplikacji (nie
    tylko przy zmianie statusu produktu), więc pytanie bazy o istnienie
    tabeli za każdym razem byłoby zbędnym, powtarzalnym obciążeniem.

    Wynik POZYTYWNY zapamiętujemy NA STAŁE (do restartu procesu) — tabela raz
    założona nie zniknie z bazy w trakcie działania aplikacji.

    Wynik NEGATYWNY zapamiętujemy tylko na `_TABLE_RECHECK_INTERVAL_SECONDS`
    (patrz stała na górze modułu). Inaczej: administrator wykonał migrację
    PO starcie tego procesu (kolejność „migracja przed deployem" zawiodła),
    albo baza była tylko chwilowo niedostępna przy starcie — bez odświeżania
    audyt milczałby do restartu aplikacji, a modal produktu pokazywałby
    łagodne „Brak zarejestrowanych zdarzeń", nie do odróżnienia od
    poprawnie pustej historii.

    DLACZEGO to sprawdzenie w ogóle istnieje: na produkcji tabelę
    prod_product_events zakłada ręcznie administrator PRZED wdrożeniem tego
    kodu (patrz migrations/2026-07-31-prod-product-events.sql) — ale
    kolejność „migracja przed deployem" może zawieść. Bez tego sprawdzenia
    listener próbowałby dodać wiersz do nieistniejącej tabeli, co skończyłoby
    się błędem INSERT wewnątrz tego samego flush()/commit() co zapis statusu
    produktu — a audyt (funkcja czysto obserwacyjna) NIGDY nie może wywrócić
    operacji biznesowej.
    """
    global _TABLE_AVAILABLE, _LAST_CHECK_MONOTONIC

    if _TABLE_AVAILABLE:
        return True

    now = time.monotonic()
    is_first_check = _LAST_CHECK_MONOTONIC is None
    if not is_first_check and (now - _LAST_CHECK_MONOTONIC) < _TABLE_RECHECK_INTERVAL_SECONDS:
        # Wciąż w oknie „niedawno sprawdzone negatywnie" — nie odpytujemy
        # bazy ponownie i nie logujemy (logowaliśmy już przy tamtej próbie).
        return False

    _LAST_CHECK_MONOTONIC = now
    try:
        _TABLE_AVAILABLE = bool(check_fn())
    except Exception:
        # Nie udało się nawet sprawdzić istnienia tabeli (np. baza chwilowo
        # niedostępna) — to sprawdzenie też nie może niczego wywrócić, więc
        # uznajemy audyt za niedostępny i idziemy dalej bez niego.
        _TABLE_AVAILABLE = False

    if not _TABLE_AVAILABLE:
        # Logujemy przy pierwszym sprawdzeniu i potem najwyżej raz na próbę
        # odświeżenia (czyli raz na `_TABLE_RECHECK_INTERVAL_SECONDS`) — nie
        # przy każdym flushu, stąd logowanie jest tutaj, a nie w listenerze.
        logger.error(
            "Audyt zdarzeń produktu jest WYŁĄCZONY: tabela prod_product_events "
            "nie istnieje w bazie. Wykonaj migrację "
            "migrations/2026-07-31-prod-product-events.sql, aby przywrócić audyt."
        )

    return _TABLE_AVAILABLE


def register_product_event_listener():
    """
    Rejestruje hook before_flush. Idempotentne — wielokrotne wywołanie
    (np. przy re-imporcie modułu) nie duplikuje zdarzeń.
    """
    global _LISTENER_REGISTERED
    if _LISTENER_REGISTERED:
        return

    from sqlalchemy import event as sa_event
    from extensions import db

    @sa_event.listens_for(db.session, 'before_flush')
    def _capture_product_events(session, flush_context, instances):
        # Cały hook w try/except: audyt NIGDY nie może przerwać zapisu statusu
        try:
            # Jeśli tabeli audytu nie ma (albo nie da się tego sprawdzić),
            # wychodzimy natychmiast — zanim wyliczymy cokolwiek innego
            # (dirty_products, aktora, itd.), żeby nie marnować pracy na
            # ścieżce, która i tak nic nie zapisze.
            if not _audit_table_available():
                return

            from modules.production.models import (
                ProductionProduct, ProductionProductEvent, get_local_now,
            )

            dirty_products = [o for o in session.dirty
                              if isinstance(o, ProductionProduct)]
            if not dirty_products:
                return

            actor = current_actor()
            now = get_local_now()

            # Zbieramy zmiany WSZYSTKICH produktów z tego flushu przed
            # zbudowaniem wierszy — build_event_rows_for_flush musi widzieć
            # całość, żeby odróżnić masową renumerację kolejki priorytetów
            # (assign_sequential_ranks, setki produktów) od pojedynczej
            # decyzji o priorytecie jednego produktu.
            changes_by_product = []
            for product in dirty_products:
                if product.id is None:
                    continue
                changes_by_product.append((product.id, _extract_changes(product)))

            for row in build_event_rows_for_flush(changes_by_product, actor, now):
                session.add(ProductionProductEvent(**row))
        except Exception:
            logger.error("Nie udało się zapisać zdarzenia audytu produktu",
                         exc_info=True)

    _LISTENER_REGISTERED = True
