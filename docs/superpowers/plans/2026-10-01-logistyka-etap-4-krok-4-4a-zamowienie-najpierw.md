# Logistyka etap 4, krok 4.4a — „zamówienie najpierw” dla pisarzy stanowisk — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ZAKOŃCZ i wejście do pakowania na tabletach, doróbka, zmiany z Base. i przeniesienie osieroconych w cronie blokują wiersz zamówienia przed pozycjami i decydują na odczycie bieżącym, więc zmiana sposobu dostawy w panelu w chwili ostatniego ZAKOŃCZ nie daje już ani MySQL 1213, ani błędnie zamkniętego cyklu.

**Architecture:** Nowy moduł `modules/production/services/blokady_zamowien.py` z jedną definicją blokady „zamówienie → wszystkie jego pozycje” (`with_for_update().populate_existing()`, zamówienia rosnąco po id). Każdy pisarz pozycji woła go, zanim cokolwiek zapisze: router ZAKOŃCZ (`mobile_api.order_complete` — wszystkie stanowiska, więc także wejście do pakowania), `rework_service.reject_product_quantity`, `sync_service.apply_baselinker_changes` (wywołanie HTTP do Base. przeniesione PRZED blokady) i `delivery.przenies_osierocone_z_logistyki`. `po_spakowaniu` i `odnotuj_wejscie_do_pakowania` nie zmieniają logiki — dostają zamówienie i pozycje już odczytane bieżąco. Dowód: wyścigi na dwóch sesjach MySQL na podglądzie 5004.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` — sekcje 4.6 („Siatka w cronie”), 8.3 („Współbieżność”, znany wyjątek doróbki), 8.5, 8.7 („Współbieżność”). Zlecenie: prompt kroku 4.4, „Zadanie wstępne (PRZED Dostawą, decyzja Konrada 1.10)”. Dorobek kroku 4.3 i dodatku 8.7: plany `docs/superpowers/plans/2026-09-30-logistyka-etap-4-krok-4-3-weryfikacja.md`, `docs/superpowers/plans/2026-10-01-logistyka-etap-4-krok-4-3-zmiana-sposobu-spakowanego.md`; dzienniki `C:\Users\Grafik\Documents\woodpower-podglady\logistyka43\sdd\` (z `dodatek-8-7\`).

## Global Constraints

- Kod zgodny z **Pythonem 3.9** (produkcja): bez `X | Y` w adnotacjach poza plikami z `from __future__ import annotations` (tak jest w `rework_service.py`), bez `match`.
- Komentarze i docstringi **po polsku**; w tekstach UI „Base.” zamiast BaseLinker (w kodzie nazwy bez zmian).
- **Kolejność blokad (cała gałąź):** [blokada tras `routes.zablokuj_trasy()`] → [blokada deklaracji `paczki.zablokuj_deklaracje()`] → wiersze zamówień `FOR UPDATE` rosnąco po id → paczki `FOR UPDATE` → pozycje `FOR UPDATE` po kluczu głównym rosnąco → dopiero zapisy. Ten krok dopina pisarzy pozycji, którzy dotąd brali pozycję przed zamówieniem. Pisarz, który nie zmienia zamówienia ani paczek (ZAKOŃCZ, doróbka bez pracy dla reguły), paczek nie blokuje.
- **Odczyt bieżący po blokadzie:** MySQL pracuje na REPEATABLE READ, migawka powstaje przy pierwszym zwykłym odczycie transakcji (w API mobilnym: sprawdzenie powtórki `X-Operation-Id` w `with_idempotency`). Stan, na którym zapis decyduje, czytamy `with_for_update().populate_existing()`; blokady bierzemy PRZED pierwszą zmianą obiektów w sesji (`populate_existing` nadpisałby niezapisane zmiany).
- **Bez `db.session.commit()` w handlerach API mobilnego** (kontrakt `with_idempotency`: wpis idempotencji i skutki w jednej transakcji). Trik „commit przed blokadą” z panelu (`_zapis_pod_blokada`) tu NIE wchodzi w grę.
- **Żadnych blokad w czasie wywołań HTTP do Base.** (timeout gunicorna 30 s, tablety czekają na wiersz zamówienia).
- Funkcje serwisów nie commitują (wyjątek istniejący, bez zmian: `reject_product_quantity` commituje sam).
- `tools/print_agent` — bez zmian. Bez migracji w tym kroku.
- Testy WYŁĄCZNIE z katalogu worktree zadania: `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; **nigdy** `docker compose exec`; nie twórz `config/core.json` w worktree. Najwyżej 2 pełne pakiety naraz (Docker VM 15,5 GB, OOM = exit 137).
- Podglądy: **5004** (`logistyka4-podglad`, baza `logistyka4_podglad`, katalog `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4`) jest do wyścigów tego kroku. **5005 i 5003 — nie ruszać** (5005 testuje sesja appki z tabletem po USB).
- Commity: Conventional Commits po polsku **bez polskich znaków w temacie**, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pushu (push robi Konrad z PowerShella: `git push origin claude/logistyka-etap-4`), nigdy do `main`. Spec i plan commitujemy `git add -f`.
- Repo publiczne: żadnych sekretów, adresów IP ani uwag bezpieczeństwa w commitowanych plikach.
- Trzymaj się zakresu: usterki spoza zakresu zgłaszaj kontrolerowi, nie naprawiaj „przy okazji”.

## Review Focus

1. **Logistyk zmienia sposób dostawy w chwili ostatniego ZAKOŃCZ** (na MySQL 11 z 62 przebiegów: zamknięty cykl odbioru, którego nikt nie wydał) — ZAKOŃCZ czyta sposób bieżąco: `test_ostatnie_zakoncz_decyduje_na_biezacym_sposobie_dostawy` (Task 1), tryb MySQL `panel-zakoncz-ostatnie` (Task 3).
2. **Dwa tablety kończą ostatnie dwie pozycje jednego zamówienia** — drugi musi zobaczyć pierwszą pozycję już zrobioną, inaczej ani zamknięcie kuriera, ani „zeszło z produkcji” (`logistics_completed_at`) nie zapadną: `test_ostatnie_zakoncz_widzi_biezace_statusy_pozostalych_pozycji`, `test_wejscie_do_pakowania_widzi_biezace_statusy_pozostalych_pozycji` (Task 1).
3. **Zmiany z Base. trzymają blokady w czasie wywołania HTTP** (tablety czekają na wiersz zamówienia ponad timeout gunicorna) — `test_zmiany_z_base_pytaja_base_przed_blokadami` (Task 2).
4. **Doróbka sztuki, którą inny tablet właśnie spakował** — odmowa 409 zamiast cofnięcia spakowanej sztuki: `test_dorobka_sprawdza_stanowisko_na_biezacym_statusie` (Task 2).
5. **Nowa albo usunięta pozycja z Base. zostawia cykl w złym stanie do godzinnego crona** — przeliczenie od razu: `test_zmiany_z_base_nowa_pozycja_otwiera_zamkniete_od_razu`, `test_zmiany_z_base_usuniecie_niespakowanej_zamyka_kuriera_od_razu` (Task 2).

Poza testami SQLite (Task 3, MySQL na dwóch sesjach): panel ↔ ZAKOŃCZ (częściowo i w całości spakowane), panel ↔ wejście do pakowania, doróbka ↔ ZAKOŃCZ, doróbka ↔ panel, zmiany z Base. ↔ ZAKOŃCZ oraz regresja trybów kroku 4.3. Kryterium: **zero 1213 i zero błędnych zamknięć**.

## Decyzje Konrada (1.10)

1. Kolejność blokad doróbki zostaje do tego kroku; „zamówienie najpierw” dla stanowisk to zadanie wstępne kroku 4.4 (decyzja z oględzin 4.3).
2. Krok 4.4 w dwóch planach: **4.4a** (ten) i **4.4b** (Dostawa + plan appki). 4.4a realizujemy od razu po akceptacji.
3. Etapy 3 i 4 wdrażamy razem (jedno wdrożenie etapów 1–4) — wpis w specu 14 robi Task 3.
4. Plan zaakceptowany („Akceptuję, ruszaj”). **Błąd `sync_source='admin_update'` naprawiamy w 4.4a** (Task 2, Step 4b): dodanie pozycji z Base. w panelu admina nie nadpisuje już zamówieniu `sync_source`.
5. Akcje automatyczne Base. (spec 16): jedyna akcja to „Ustawiono status” → warunek „Status zamówienia = Odebrane” → „Drukuj dokument KP [PDF]” (ID 292653, zrzut od Konrada 1.10). „Odebrane” (149779) ustawia tylko „Wydane klientowi” przy odbiorze osobistym; statusy Dostawy (524520, 149763, 149778, 417343) jej nie wyzwalają — plan 4.4b wysyła statusy jak w specu.

## Doprecyzowania (do specu w Task 3)

- **Zakres „pisarzy”.** Zmianę kolejności dostają: `POST /api/mobile/orders/<id>/complete` (każde stanowisko — także wejście ostatniej pozycji do pakowania, `odnotuj_wejscie_do_pakowania`), `POST /api/mobile/orders/<id>/reject` (`reject_product_quantity`), panel admina „zastosuj zmiany z Base.” (`apply_baselinker_changes`) i `delivery.przenies_osierocone_z_logistyki` (cron; zapisuje pozycję, potem zamówienie). Bez zmian: `PATCH …/quantity` i ręczna edycja sztuk w panelu admina (piszą tylko pozycję, nie sięgają po zamówienie), import nowych zamówień z Base. (`sync_paid_orders_only`: zamówienie przed nowymi pozycjami, istniejących pozycji nie rusza), hurt statusu (już zamówienia przed pozycjami).
- **Lista pozycji do zablokowania** pochodzi z `order.products` (zwykły odczyt), jak w `paczki.zablokuj_stan`: blokada po `order_id` zakładałaby blokady luk indeksu. Pozycja dodana przez inny zapis po migawce, a przed blokadą zamówienia, nie zostanie zablokowana ani policzona. Zmiany z Base. biorą od tego kroku blokadę zamówienia przed dodaniem pozycji, więc okno zamyka się do milisekund; resztę łata cron (`przelicz_otwarte` otwiera zamknięte z aktywną pozycją).
- **Zmiany z Base. przeliczają zamknięcie od razu** (`delivery.przelicz_zamkniecie` po usunięciu/dodaniu pozycji). Dotąd zamknięte zamówienie kurierskie z nową pozycją czekało na godzinny cron, a usunięcie ostatniej niespakowanej pozycji nie zamykało cyklu. Bez tego kryterium „zero błędnych zamknięć” w wyścigu zmian z Base. z ZAKOŃCZ nie byłoby spełnione.
- **Wywołanie Base. przed blokadami.** `apply_baselinker_changes` pobiera zamówienie z Base. (`get_order_from_baselinker`, tylko gdy są pozycje do dodania) na samym początku, przed blokadą zamówienia; dotąd robił to w kroku 3, gdy pozycje usunięte i zmienione były już zablokowane.
- **Siatka w cronie** (spec 4.6) zostaje jako zabezpieczenie; przyczynę (ZAKOŃCZ na migawce sposobu) usuwa ten krok.
- **`sync_source` przy dodaniu pozycji z Base.** (decyzja Konrada 4): zamówienie zachowuje swoje źródło synchronizacji; dawne `admin_update` było spoza ENUM kolumny i na MySQL wywracało całą operację.

## Poza zakresem (zgłoszone kontrolerowi, bez zmian w kodzie)

Z przeglądu ścieżek pisarzy (1.10), do decyzji Konrada (pierwsza pozycja z tej listy — `sync_source='admin_update'` — wyjęta: naprawiamy ją w Task 2 na polecenie Konrada):
- Ten sam panel przy zmianie nazwy pozycji zmienia w miejscu współdzielony wiersz `prod_configurations` (wszystkie pozycje z tą konfiguracją).
- `reject_product_quantity` commituje w handlerze (wbrew kontraktowi `with_idempotency`): błąd po tym commicie i ponowienie z kolejki offline dałyby drugą doróbkę.
- `baselinker_status_sync._produkty_zamowienia` szuka zamówienia po `internal_order_number`, który powtarza się co rok — może wymieszać pozycje starego zamówienia.
- Import z Base. (`sync_paid_orders_only`) nie pomija zamówień już zaimportowanych, gdy w Base. zostały w statusie „Nowe - opłacone”.

## Środowisko i tory

- Główny worktree (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4`, gałąź `claude/logistyka-etap-4`, projekt dockera `logistyka4`.
- `PYTEST <ścieżki>` w krokach = `docker compose -p logistyka4 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` z katalogu worktree.
- Punkt wyjścia: HEAD `b0fc115a` + commit tego planu; **`5480 passed, 3 skipped`**. Po każdym zadaniu pełny pakiet: 0 failed, passed = poprzednio + nowe (± testy świadomie zmienione, wymienione w raporcie).
- Kolejność: Task 1 → Task 2 (przegląd Task 1 równolegle z implementacją Task 2, poprawki Task 1 po skończeniu Task 2) → Task 3. Wszystko w głównym worktree (pliki Task 1 i 2 rozłączne, ale Task 2 korzysta z modułu Task 1).

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/services/blokady_zamowien.py` (nowy) | 1 | `zablokuj_zamowienia`, `zablokuj_pozycje`, `zablokuj_zamowienie`, `zablokuj_zamowienie_pozycji` |
| `modules/production/routers/mobile_api.py` (`order_complete`) | 1 | ZAKOŃCZ i wejście do pakowania: blokada zamówienia i pozycji przed odczytem pozycji |
| `modules/production/logistics/services/delivery.py` (`odnotuj_wejscie_do_pakowania`, `po_spakowaniu`, `przenies_osierocone_z_logistyki`) | 1 | docstringi (warunek odczytu bieżącego), cron osieroconych: zamówienia przed pozycjami |
| `tests/blokady_pomocnicze.py` (nowy), `tests/test_blokady_zamowien.py` (nowy) | 1 | kolejność zapytań, migawka przed zapisem, testy |
| `modules/production/services/rework_service.py` | 2 | doróbka: blokada zamówienia i pozycji zamiast samej pozycji |
| `modules/production/services/sync_service.py` (`apply_baselinker_changes`) | 2 | Base. przed blokadami, blokada zamówienia i pozycji, przeliczenie zamknięcia, bez nadpisywania `sync_source` |
| `tests/test_blokady_dorobka_base.py` (nowy) | 2 | testy |
| skrypty wyścigów w `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\kod\` (poza repo) | 3 | tryby MySQL |
| `CLAUDE.md`, spec | 3 | kolejność blokad, wyniki, decyzje Konrada |

---

### Task 1: Moduł blokad, ZAKOŃCZ (wszystkie stanowiska) i cron osieroconych

**Files:**
- Create: `modules/production/services/blokady_zamowien.py`
- Create: `tests/blokady_pomocnicze.py`, `tests/test_blokady_zamowien.py`
- Modify: `modules/production/routers/mobile_api.py:24` (import), `:443-449` (`order_complete`)
- Modify: `modules/production/logistics/services/delivery.py:120-142` (docstringi), `:528-551` (`przenies_osierocone_z_logistyki`)

**Interfaces:**
- Produces: `blokady_zamowien.zablokuj_zamowienia(order_ids) -> List[ProductionOrder]` (rosnąco po id, bez `None` i nieistniejących; pusta lista → `[]` bez zapytania); `blokady_zamowien.zablokuj_pozycje(order) -> List[ProductionProduct]` (wszystkie pozycje, także anulowane, rosnąco po id); `blokady_zamowien.zablokuj_zamowienie(order_id) -> Optional[ProductionOrder]`; `blokady_zamowien.zablokuj_zamowienie_pozycji(product_id) -> Optional[ProductionProduct]`. Wszystkie: `FOR UPDATE` + `populate_existing`, bez commita. Zapytanie blokady zamówień ma zawsze postać `WHERE prod_orders.id IN (…) ORDER BY prod_orders.id`, a pozycji `WHERE prod_products.id IN (…) ORDER BY prod_products.id` (po tym rozpoznają je testy kolejności).
- Produces (testy): `tests/blokady_pomocnicze.py`: `Zapytania` (kontekst nasłuchujący `before_cursor_execute`; `lista` = `[(sql, parametry)]`, `pierwsze(warunek) -> int`), predykaty `blokada_zamowien(sql)`, `blokada_pozycji(sql)`, `zapis(sql)`.

- [ ] **Step 0: Punkt wyjścia**

Run: `PYTEST tests/`
Expected: `5480 passed, 3 skipped`.

- [ ] **Step 1: Pomocnik testów**

Create `tests/blokady_pomocnicze.py`:

```python
# -*- coding: utf-8 -*-
"""
Pomocnik testów kolejności blokad („zamówienie najpierw”, logistyka etap 4, krok 4.4a).

SQLite pomija FOR UPDATE, więc kolejności blokad pilnujemy na kolejności samych zapytań (jak
tests/test_produkty_masowa_zmiana_statusu.py): blokada zamówień to zawsze `WHERE prod_orders.id IN (…)
ORDER BY prod_orders.id`, blokada pozycji — `WHERE prod_products.id IN (…) ORDER BY prod_products.id`
(modules/production/services/blokady_zamowien.py), a zapis — pierwszy UPDATE albo INSERT zamówienia lub pozycji.
"""
from sqlalchemy import event

from extensions import db


class Zapytania(object):
    """Zapytania SQL w kolejności wykonania (spłaszczone spacje) razem z parametrami."""

    def __init__(self):
        self.lista = []

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self._zapisz)
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, 'before_cursor_execute', self._zapisz)
        return False

    def _zapisz(self, conn, cursor, statement, parameters, context, executemany):
        self.lista.append((' '.join(statement.split()), parameters))

    def pierwsze(self, warunek):
        """Indeks pierwszego zapytania spełniającego `warunek(sql)`; brak → StopIteration (test pada)."""
        return next(i for i, (sql, _parametry) in enumerate(self.lista) if warunek(sql))


def blokada_zamowien(sql):
    return (sql.startswith('SELECT') and 'FROM prod_orders' in sql and 'WHERE prod_orders.id IN' in sql
            and 'ORDER BY prod_orders.id' in sql)


def blokada_pozycji(sql):
    return (sql.startswith('SELECT') and 'FROM prod_products' in sql and 'WHERE prod_products.id IN' in sql
            and 'ORDER BY prod_products.id' in sql)


def zapis(sql):
    return sql.startswith(('UPDATE prod_products', 'UPDATE prod_orders', 'INSERT INTO prod_products',
                           'DELETE FROM prod_products'))
```

- [ ] **Step 2: Testy, które padną**

Create `tests/test_blokady_zamowien.py`:

```python
# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” (logistyka etap 4, krok 4.4a): ZAKOŃCZ i wejście do pakowania na tablecie oraz cron
osieroconych blokują wiersz zamówienia przed pozycjami i decydują na odczycie bieżącym.

SQLite nie ma blokad wierszy ani migawki MySQL. Kolejność blokad sprawdzamy na kolejności zapytań
(tests/blokady_pomocnicze.py), a odczyt bieżący — obiektami zostawionymi w sesji w starym stanie, podczas gdy
w bazie leży już cudzy zapis (surowy UPDATE poza ORM). Stan „migawki” wstrzykujemy przelotką na
mobile_api._resolve_workers: to ostatni krok handlera przed odczytem pozycji, już po commicie
require_device_token (commit wygasza obiekty sesji, więc wcześniej wczytany stan by nie przetrwał).
"""
import itertools

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery
from modules.production.models import ProductionDevice, ProductionOrder, ProductionProduct
from modules.production.routers import mobile_api
from modules.production.services import blokady_zamowien
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, zapis
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

_licznik = itertools.count(1)
_ZAMOWIENIA = ProductionOrder.__table__
_POZYCJE = ProductionProduct.__table__


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie i wyjście z produkcji planują status Base. po commicie — w testach go nie wysyłamy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(stanowisko='packaging'):
    """Nagłówki tabletu danego stanowiska. Wołać PRZED przygotowaniem migawki: commit wygasza sesję."""
    device = ProductionDevice(device_id='TAB-BLK-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device),
            'X-Operation-Id': 'op-blk-%d' % next(_licznik)}


def _zakoncz(client, pozycja_id, naglowki, stanowisko='packaging'):
    return client.post('/api/mobile/orders/%d/complete' % pozycja_id, headers=naglowki,
                       json={'station_code': stanowisko})


def _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie=None, pozycje_w_bazie=None):
    """
    Przelotka na mobile_api._resolve_workers: po prawdziwym wywołaniu wczytuje zamówienie i jego pozycje do sesji
    („migawka” żądania), a potem surowym UPDATE zapisuje w bazie cudzą zmianę (`zamowienie_w_bazie` — kolumny
    zamówienia, `pozycje_w_bazie` — {id pozycji: status}). Obiekty w sesji zostają stare: zmianę zobaczy tylko
    odczyt bieżący (populate_existing).
    """
    oryginal = mobile_api._resolve_workers

    def przelotka():
        wynik = oryginal()
        order = db.session.get(ProductionOrder, order_id)
        stare = (order.override_delivery_method, [p.current_status for p in order.products])
        if zamowienie_w_bazie:
            db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order_id)
                               .values(**zamowienie_w_bazie))
        for pid, status in (pozycje_w_bazie or {}).items():
            db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pid).values(current_status=status))
        assert (order.override_delivery_method, [p.current_status for p in order.products]) == stare
        return wynik

    monkeypatch.setattr(mobile_api, '_resolve_workers', przelotka)


def _po_zadaniu(order_id):
    db.session.expire_all()
    return db.session.get(ProductionOrder, order_id)


# --- Moduł blokad ---------------------------------------------------------------------------------------

def test_zablokuj_zamowienia_rosnaco_bez_pustych_i_brakujacych(app):
    a, b = zamowienie(), zamowienie()
    assert blokady_zamowien.zablokuj_zamowienia([]) == []
    assert blokady_zamowien.zablokuj_zamowienia([None]) == []
    wynik = blokady_zamowien.zablokuj_zamowienia([b.id, a.id, b.id, None, 987654])
    assert [o.id for o in wynik] == sorted([a.id, b.id])


def test_zablokuj_zamowienie_pozycji_czyta_biezaco(app):
    """Zamówienie i pozycje w sesji są nieświeże (migawka), a w bazie leży cudzy zapis — po blokadzie obiekty
    mają wartości z bazy."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    pierwsza, druga = order.products
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order.id)
                       .values(override_delivery_method=s.ODBIOR))
    db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pierwsza.id).values(current_status='spakowane'))
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(druga.id) is druga
    assert (order.override_delivery_method, pierwsza.current_status) == (s.ODBIOR, 'spakowane')


def test_zablokuj_zamowienie_pozycji_bez_pozycji(app):
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(987654) is None
    assert blokady_zamowien.zablokuj_zamowienie(987654) is None


# --- ZAKOŃCZ i wejście do pakowania ---------------------------------------------------------------------

def test_zakoncz_blokuje_zamowienie_przed_pozycjami_przed_zapisem(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    naglowki = _naglowki()
    with Zapytania() as z:
        r = _zakoncz(client, pozycje[1], naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert sorted(z.lista[blokada][1]) == pozycje


def test_ostatnie_zakoncz_decyduje_na_biezacym_sposobie_dostawy(app, client, monkeypatch):
    """Spec 8.7 („Współbieżność”) i 4.6 („Siatka w cronie”): logistyk zmienił w panelu kuriera na odbiór w chwili
    ostatniego ZAKOŃCZ. Na MySQL tablet widział sposób z migawki i zamykał cykl odbioru, którego nikt nie wydał
    (11 z 62 przebiegów). ZAKOŃCZ czyta sposób bieżąco: odbiór czeka na „Wydane klientowi”."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id, ostatnia = order.id, order.products[1].id
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie={'override_delivery_method': s.ODBIOR})
    r = _zakoncz(client, ostatnia, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert order.override_delivery_method == s.ODBIOR
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is None


def test_ostatnie_zakoncz_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """Dwa tablety kończą ostatnie dwie pozycje zamówienia kurierskiego. Drugi czekał na blokadę zamówienia, a jego
    migawka pokazuje pierwszą pozycję jeszcze w pakowaniu — bez odczytu bieżącego cykl nie zamknąłby się wcale."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'spakowane'})
    r = _zakoncz(client, druga, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is not None


def test_wejscie_do_pakowania_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """„Zeszło z produkcji” (logistics_completed_at) zapada przy wejściu OSTATNIEJ pozycji do pakowania — także
    gdy pierwszą przesunął w tej samej chwili inny tablet, a migawka pokazuje ją jeszcze na Krawędziach."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_krawedzie', 'czeka_na_krawedzie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki('edges')
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'czeka_na_pakowanie'})
    r = _zakoncz(client, druga, naglowki, stanowisko='edges')
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert order.logistics_completed_at is not None


def test_zakoncz_brak_pozycji_404(app, client):
    r = _zakoncz(client, 987654, _naglowki())
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


# --- Cron: przeniesienie osieroconych ---------------------------------------------------------------------

def test_cron_osieroconych_blokuje_zamowienia_przed_zapisem_pozycji(app):
    a = zamowienie(sposob=s.KURIER, statusy=('czeka_na_logistyke',))
    b = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_logistyke'))
    ids = sorted([a.id, b.id])
    with Zapytania() as z:
        assert delivery.przenies_osierocone_z_logistyki() == 2
        db.session.flush()
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == ids
```

- [ ] **Step 3: Testy padają**

Run: `PYTEST tests/test_blokady_zamowien.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.production.services.blokady_zamowien'` (import na górze pliku). Po dodaniu samego modułu (Step 4) i przed Step 5–6 padają: `test_zakoncz_blokuje_zamowienie_przed_pozycjami_przed_zapisem` (StopIteration — brak blokady zamówień), `test_ostatnie_zakoncz_decyduje_na_biezacym_sposobie_dostawy` (`logistics_closed_at` ustawione), `test_ostatnie_zakoncz_widzi_biezace_statusy_pozostalych_pozycji` (`logistics_closed_at is None`), `test_wejscie_do_pakowania_widzi_biezace_statusy_pozostalych_pozycji`, `test_cron_osieroconych_blokuje_zamowienia_przed_zapisem_pozycji`.

- [ ] **Step 4: Moduł blokad**

Create `modules/production/services/blokady_zamowien.py`:

```python
# -*- coding: utf-8 -*-
"""
Kolejność blokad pisarzy zamówienia — „zamówienie najpierw” (logistyka etap 4, krok 4.4a).

Zasada (ta sama co w panelu Logistyki, Weryfikacji, deklaracji paczek, hurtowej zmianie statusu i cronie
logistyki): wiersz zamówienia FOR UPDATE po kluczu głównym → pozycje zamówienia FOR UPDATE po kluczu głównym
→ dopiero zapisy. Stanowiska (ZAKOŃCZ i wejście do pakowania), doróbka i zmiany z Base. brały dotąd pozycję przed
zamówieniem: zapisywały pozycję (flush), a zamówienie dopiero w po_spakowaniu albo w regule unieważniania
etapów. Panel trzymał zamówienie i sięgał po pozycję, więc dwie odwrotne kolejności dawały MySQL 1213
(spec 8.7, „Współbieżność”).

Oba odczyty są BIEŻĄCE (`with_for_update().populate_existing()`). MySQL pracuje na REPEATABLE READ, a migawka
transakcji powstaje przy pierwszym zwykłym odczycie (w API mobilnym: sprawdzenie powtórki X-Operation-Id),
więc zwykły odczyt po czekaniu na blokadę pokazałby stan sprzed cudzego zapisu — tak ostatni ZAKOŃCZ zamykał
cykl odbioru osobistego na sposobie „kurier” z migawki (spec 4.6, „Siatka w cronie”). `populate_existing`
nadpisuje atrybuty obiektów już wczytanych do sesji: funkcje wołać PRZED pierwszą zmianą zamówienia i pozycji
w tej transakcji, inaczej niezapisane zmiany przepadną.

Lista kluczy pozycji pochodzi z `order.products` (zwykły odczyt), jak w paczki.zablokuj_stan: blokada po
`order_id` zakładałaby blokady luk indeksu. Pozycja dodana przez inny zapis po migawce, a przed blokadą
zamówienia, nie zostanie więc zablokowana ani policzona. Zmiany z Base. biorą tę samą blokadę zamówienia przed
dodaniem pozycji, więc okno jest rzędu milisekund, a resztę łata cron logistyki (przelicz_otwarte).

Funkcje nie commitują.
"""
from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct


def zablokuj_zamowienia(order_ids):
    """
    Wiersze zamówień `order_ids` FOR UPDATE, rosnąco po id — jedna kolejność dla zapisów, które blokują kilka
    zamówień (jak hurtowa zmiana statusu i cron). Odczyt bieżący. Zwraca zamówienia w tej kolejności, bez
    `None` i bez nieistniejących; pusta lista → [] bez zapytania.
    """
    ids = sorted({i for i in order_ids if i is not None})
    if not ids:
        return []
    return (ProductionOrder.query.filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id)
            .with_for_update().populate_existing().all())


def zablokuj_pozycje(order):
    """
    Wszystkie pozycje zamówienia (także anulowane) FOR UPDATE po kluczu głównym, rosnąco, odczytem bieżącym.
    Zwraca je w tej kolejności. Wołać PO zablokowaniu wiersza zamówienia.
    """
    ids = sorted(p.id for p in order.products if p.id is not None)
    if not ids:
        return []
    return (ProductionProduct.query.filter(ProductionProduct.id.in_(ids)).order_by(ProductionProduct.id)
            .with_for_update().populate_existing().all())


def zablokuj_zamowienie(order_id):
    """Zamówienie, potem wszystkie jego pozycje (odczyt bieżący). Zwraca zamówienie albo None, gdy go nie ma."""
    zamowienia = zablokuj_zamowienia([order_id])
    if not zamowienia:
        return None
    zablokuj_pozycje(zamowienia[0])
    return zamowienia[0]


def zablokuj_zamowienie_pozycji(product_id):
    """
    Pisarz jednej pozycji (ZAKOŃCZ i wejście do pakowania na tablecie, doróbka): zamówienie tej pozycji, potem
    wszystkie jego pozycje — ZANIM cokolwiek zapisze. Zwraca pozycję po odczycie bieżącym albo None, gdy jej nie
    ma. `order_id` pozycji czytamy zwykłym odczytem: ta kolumna się nie zmienia.
    """
    wiersz = (db.session.query(ProductionProduct.order_id)
              .filter(ProductionProduct.id == product_id).first())
    if wiersz is None:
        return None
    zablokuj_zamowienie(wiersz.order_id)
    return (ProductionProduct.query.filter(ProductionProduct.id == product_id)
            .with_for_update().populate_existing().one_or_none())
```

Run: `PYTEST tests/test_blokady_zamowien.py`
Expected: 3 testy modułu PASS; 5 testów ZAKOŃCZ/crona FAIL (jak w Step 3); `test_zakoncz_brak_pozycji_404` PASS.

- [ ] **Step 5: ZAKOŃCZ blokuje zamówienie przed pozycją**

Modify `modules/production/routers/mobile_api.py`:

Import (linia 24):
```python
from modules.production.services import blokady_zamowien, label_print_service, worker_service
```

W `order_complete` zamień (linie 443-449):
```python
    worker_ids, session_ids, err = _resolve_workers()
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404
```
na:
```python
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
```

Reszta funkcji bez zmian (`item.order` jest już odczytane bieżąco, więc 409 `delivery_method_not_set` też decyduje na bieżącym sposobie).

- [ ] **Step 6: Cron osieroconych i docstringi**

Modify `modules/production/logistics/services/delivery.py`.

`odnotuj_wejscie_do_pakowania` (linie 120-126) — sam docstring:
```python
def odnotuj_wejscie_do_pakowania(order, teraz):
    """
    „Zeszło z produkcji” (Arkusz): chwila, gdy OSTATNI aktywny produkt wszedł do pakowania.
    Wołający trzyma blokadę zamówienia i jego pozycji z odczytem bieżącym (blokady_zamowien, krok 4.4a), więc
    statusy pozostałych pozycji są bieżące — także pozycji zrobionej chwilę wcześniej na innym tablecie.
    """
```

`po_spakowaniu` (linie 129-130) — sam docstring:
```python
def po_spakowaniu(order, teraz):
    """
    Wołane z complete_task('packaging'). Kończy przepakowanie i przelicza cykl.
    Wołający (ZAKOŃCZ, mobile_api.order_complete) trzyma blokadę zamówienia i jego pozycji z odczytem bieżącym
    (blokady_zamowien, krok 4.4a): zamknięcie zapada na bieżącym sposobie dostawy i statusach, a nie na migawce
    sprzed zmiany w panelu (spec 4.6, „Siatka w cronie”).
    """
```

`przenies_osierocone_z_logistyki` (linie 528-551) — całość:
```python
def przenies_osierocone_z_logistyki(teraz=None):
    """
    Produkty w `czeka_na_logistyke` → `czeka_na_pakowanie`. Zwraca liczbę przeniesionych.

    Migracja etapu 1 przenosi je raz, ale deploy.sh robi migrate → przeliczenie klientów
    (do 300 s) → restart, a przez ten czas STARY kod wciąż zapisuje `czeka_na_logistyke`.
    Po restarcie taki produkt nie ma kolejki na tablecie ani filtra na liście — wisi
    niewidoczny. Cron zamiata go tą samą drogą, jaką idzie dziś wyjście z produkcji
    (complete_task). Idempotentne: gdy nic nie zostało, zwraca 0.

    (krok 4.4a) Zamówienia (rosnąco po id) i ich pozycje blokujemy odczytem bieżącym PRZED zapisem pozycji —
    w kolejności stanowisk, panelu i reguły unieważniania; dotąd zapis pozycji szedł przed zapisem zamówienia.
    """
    from modules.production.models import ProductionProduct
    from modules.production.services import blokady_zamowien
    teraz = teraz or get_local_now()
    id_zamowien = [order_id for (order_id,) in
                   db.session.query(ProductionProduct.order_id)
                   .filter(ProductionProduct.current_status == 'czeka_na_logistyke').distinct().all()]
    zamowienia = blokady_zamowien.zablokuj_zamowienia(id_zamowien)
    przeniesione = 0
    for order in zamowienia:
        for p in blokady_zamowien.zablokuj_pozycje(order):
            if p.current_status == 'czeka_na_logistyke':
                p.current_status = 'czeka_na_pakowanie'
                p.updated_at = teraz  # ETag kolejki pakowania na tablecie
                przeniesione += 1
    for order in zamowienia:
        odnotuj_wejscie_do_pakowania(order, teraz)
        przelicz_zamkniecie(order, teraz)
    return przeniesione
```

Uwaga: zamówienia blokujemy wszystkie naraz (rosnąco), potem pozycje zamówienie po zamówieniu — jak hurt statusu. Każdy, kto blokuje zamówienia rosnąco i pozycje tylko zamówień już zablokowanych, nie tworzy cyklu z innym takim zapisem.

- [ ] **Step 7: Testy przechodzą**

Run: `PYTEST tests/test_blokady_zamowien.py tests/test_logistyka_cron.py tests/test_logistyka_mobile.py tests/test_mobile_complete_bl_sync_queue.py tests/test_mobile_api_alias_krawedzi.py tests/test_paczki_deklaracja.py tests/test_weryfikacja_cykl.py`
Expected: PASS (wszystkie). Testy ZAKOŃCZ w istniejących plikach przechodzą bez zmian — zmienia się tylko sposób odczytu pozycji.

- [ ] **Step 8: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `5489 passed, 3 skipped` (5480 + 9 nowych). Każdy inny wynik — opisz w raporcie (który test, dlaczego).

- [ ] **Step 9: Commit**

```bash
git add modules/production/services/blokady_zamowien.py modules/production/routers/mobile_api.py \
  modules/production/logistics/services/delivery.py tests/blokady_pomocnicze.py tests/test_blokady_zamowien.py
git commit -m "fix(production): ZAKONCZ blokuje zamowienie przed pozycjami i decyduje na stanie biezacym" \
  -m "Zadanie wstepne kroku 4.4 logistyki (zamowienie najpierw): ZAKONCZ i wejscie do pakowania na tabletach oraz przeniesienie osieroconych w cronie blokuja wiersz zamowienia, potem wszystkie jego pozycje (services/blokady_zamowien.py, odczyt biezacy), zanim cokolwiek zapisza. po_spakowaniu nie zamyka juz cyklu na sposobie dostawy z migawki." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Doróbka i zmiany z Base.

**Files:**
- Modify: `modules/production/services/rework_service.py:1-6` (docstring modułu), `:12-18` (import), `:102-117` (docstring funkcji), `:133-141` (blokada)
- Modify: `modules/production/services/sync_service.py:2602-2830` (`apply_baselinker_changes`)
- Create: `tests/test_blokady_dorobka_base.py`

**Interfaces:**
- Consumes: `blokady_zamowien.zablokuj_zamowienie_pozycji(product_id)`, `blokady_zamowien.zablokuj_zamowienie(order_id)` (Task 1); `tests/blokady_pomocnicze.py` (Task 1).
- Produces: `apply_baselinker_changes` pobiera zamówienie z Base. (tylko gdy `products_to_add`) PRZED blokadami, blokuje zamówienie i jego pozycje przed pierwszym zapisem, nie nadpisuje zamówieniu `sync_source` przy dodawaniu pozycji (decyzja Konrada 4) i na końcu woła `delivery.przelicz_zamkniecie`. Kształt wyniku (`success`, `added`, `removed`, `updated`, `errors`, `error`) bez zmian.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_blokady_dorobka_base.py`:

```python
# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” w doróbce i w zmianach z Base. (logistyka etap 4, krok 4.4a). SQLite pomija FOR UPDATE
i nie ma migawki MySQL: kolejność blokad sprawdzamy na kolejności zapytań (tests/blokady_pomocnicze.py), a odczyt
bieżący — obiektem zostawionym w sesji w starym stanie przy cudzym zapisie w bazie (surowy UPDATE poza ORM).
"""
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.services import rework_service
from modules.production.services.sync_service import BaselinkerSyncService
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, zapis
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

T0 = datetime(2026, 10, 1, 8, 0)
_POZYCJE = ProductionProduct.__table__


def _odrzuc(pozycja_id, stanowisko='packaging'):
    return rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                                  rejected_at_station=stanowisko)


def _serwis_z_nowa_pozycja(monkeypatch, order, zdarzenia=None):
    """Serwis z Base. podmienionym na odpowiedź z jedną nową pozycją (bez sieci, bez parsera nazw).
    `zdarzenia` — lista, do której wywołanie Base. dopisuje ('base', None) w kolejności zapytań SQL."""
    serwis = BaselinkerSyncService()

    def zamowienie_z_base(_id):
        if zdarzenia is not None:
            zdarzenia.append(('base', None))
        return {'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]}

    def nowa_pozycja(dane):
        return ProductionProduct(order_id=order.id, short_product_id=dane['short_product_id'],
                                 product_sequence_in_order=dane['product_sequence_in_order'],
                                 original_product_name=dane['original_product_name'], quantity=1,
                                 current_status='czeka_na_wyciecie')

    monkeypatch.setattr(serwis, 'get_order_from_baselinker', zamowienie_z_base)
    monkeypatch.setattr(serwis, '_create_production_product_from_data', nowa_pozycja)
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    return serwis


# --- Doróbka -------------------------------------------------------------------------------------------

def test_dorobka_blokuje_zamowienie_przed_pozycjami_przed_zapisem(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    with Zapytania() as z:
        _odrzuc(pozycje[1])
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert sorted(z.lista[blokada][1]) == pozycje


def test_dorobka_sprawdza_stanowisko_na_biezacym_statusie(app):
    """Pozycja w sesji czeka na pakowanie (migawka), a w bazie inny tablet ją już spakował — doróbka z pakowania
    dostaje 409 zamiast cofnąć spakowaną sztukę."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    pozycja = order.products[0]
    assert pozycja.current_status == 'czeka_na_pakowanie'
    db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pozycja.id).values(current_status='spakowane'))
    assert pozycja.current_status == 'czeka_na_pakowanie'          # obiekt w sesji nadal stary
    with pytest.raises(rework_service.RejectError) as e:
        _odrzuc(pozycja.id)
    assert e.value.code == 'product_not_on_station'


# --- Zmiany z Base. ---------------------------------------------------------------------------------------

def test_zmiany_z_base_pytaja_base_przed_blokadami(app, monkeypatch):
    """Wywołanie Base. trwa do kilkudziesięciu sekund — nie może się odbyć pod blokadą wiersza zamówienia, na którą
    czekają tablety (timeout gunicorna 30 s)."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
    bl_id = order.baselinker_order_id
    with Zapytania() as z:
        serwis = _serwis_z_nowa_pozycja(monkeypatch, order, zdarzenia=z.lista)
        wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    base = next(i for i, (sql, _p) in enumerate(z.lista) if sql == 'base')
    assert base < z.pierwsze(blokada_zamowien)


def test_zmiany_z_base_blokuja_zamowienie_przed_zapisem_pozycji(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane'))
    order_id = order.id
    pierwsza = order.products[0]
    zmiany = {'products_to_update': [{'id': pierwsza.id, 'short_product_id': pierwsza.short_product_id,
                                      'changes': [{'field': 'quantity', 'new_value': 5}]}],
              'order_level': [{'field': 'delivery_city', 'new_value': u'Rzeszów'}]}
    bl_id = order.baselinker_order_id
    with Zapytania() as z:
        wynik = BaselinkerSyncService().apply_baselinker_changes(bl_id, zmiany)
    assert wynik['success'] is True and wynik['updated'] == 1, wynik
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]


def test_zmiany_z_base_nowa_pozycja_otwiera_zamkniete_od_razu(app, monkeypatch):
    """Zamknięte zamówienie kurierskie z nową pozycją z Base. wraca do otwartych od razu, nie po godzinnym cronie."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=T0)
    order_id, bl_id = order.id, order.baselinker_order_id
    serwis = _serwis_z_nowa_pozycja(monkeypatch, order)
    wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).logistics_closed_at is None


def test_zmiany_z_base_usuniecie_niespakowanej_zamyka_kuriera_od_razu(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_wyciecie'))
    order_id, bl_id = order.id, order.baselinker_order_id
    usuwana = order.products[1]
    wynik = BaselinkerSyncService().apply_baselinker_changes(
        bl_id, {'products_to_remove': [{'id': usuwana.id, 'short_product_id': usuwana.short_product_id}]})
    assert wynik['success'] is True and wynik['removed'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).logistics_closed_at is not None


def test_zmiany_z_base_nowa_pozycja_nie_nadpisuje_zrodla_synchronizacji(app, monkeypatch):
    """Decyzja Konrada 1.10: dodanie pozycji z panelu admina ustawiało zamówieniu sync_source='admin_update', a kolumna
    to ENUM('baselinker_auto','manual_entry') — na MySQL w trybie ścisłym wywracało to całą operację (1265). SQLite
    ENUM-u nie pilnuje, więc sprawdzamy samą wartość. Prawdziwe _create_production_product_from_data (bez podmiany)."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), sync_source='baselinker_auto')
    order_id, bl_id = order.id, order.baselinker_order_id
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    wynik = serwis.apply_baselinker_changes(bl_id, {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order_id).sync_source == 'baselinker_auto'
    assert ProductionProduct.query.filter_by(order_id=order_id).count() == 2
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_blokady_dorobka_base.py`
Expected: FAIL — `test_dorobka_blokuje_zamowienie_przed_pozycjami_przed_zapisem` (StopIteration: brak blokady zamówień), `test_dorobka_sprawdza_stanowisko_na_biezacym_statusie` (brak wyjątku — oryginał z sesji bez `populate_existing`), `test_zmiany_z_base_pytaja_base_przed_blokadami` (StopIteration: brak blokady zamówień), `test_zmiany_z_base_blokuja_zamowienie_przed_zapisem_pozycji`, `test_zmiany_z_base_nowa_pozycja_otwiera_zamkniete_od_razu` (zostaje zamknięte), `test_zmiany_z_base_usuniecie_niespakowanej_zamyka_kuriera_od_razu` (zostaje otwarte), `test_zmiany_z_base_nowa_pozycja_nie_nadpisuje_zrodla_synchronizacji` (`sync_source == 'admin_update'`).

- [ ] **Step 3: Doróbka**

Modify `modules/production/services/rework_service.py`.

Docstring modułu (linie 1-6), ostatnie zdanie:
```python
"""
Service: reject sztuk produktu z aktualnego stanowiska (formatowanie i wszystkie
stanowiska za nim: sklejanie, krawędzie, lakiernia, pakowanie).
Tworzy rekord doróbki w prod_products, decrementuje quantity oryginału,
zapisuje wpis w prod_rework_log. Wszystko w jednej transakcji z blokadą zamówienia
i jego pozycji (SELECT ... FOR UPDATE, „zamówienie najpierw” — services/blokady_zamowien.py).
"""
```

Import (po `from modules.production.services.station_catalog import STATION_PENDING_STATUS`):
```python
from modules.production.services.blokady_zamowien import zablokuj_zamowienie_pozycji
```

Docstring funkcji, zdanie „Cały flow w jednej transakcji z SELECT ... FOR UPDATE na oryginale.” zamień na:
```python
    Cały flow w jednej transakcji: najpierw blokada zamówienia oryginału i wszystkich jego pozycji
    (odczyt bieżący, krok 4.4a logistyki), dopiero potem sprawdzenia i zapisy.
```

Blokada (linie 133-141) — zamień:
```python
    # Pesymistyczna blokada wiersza oryginału
    original: ProductionProduct | None = (
        db.session.query(ProductionProduct)
        .filter(ProductionProduct.id == product_id)
        .with_for_update()
        .one_or_none()
    )
    if original is None:
        raise RejectError('product_not_found', f'product {product_id} nie istnieje', status=404)
```
na:
```python
    # „Zamówienie najpierw” (logistyka etap 4, krok 4.4a): wiersz zamówienia oryginału, potem wszystkie jego
    # pozycje — blokada i odczyt bieżący, zanim cokolwiek sprawdzimy i zapiszemy. Ta sama kolejność co panel
    # Logistyki, Weryfikacja i ZAKOŃCZ. Dotąd doróbka blokowała samą pozycję, a zamówienie brała dopiero reguła
    # unieważniania etapów (1213 z zapisem Weryfikacji, spec 8.3 „Współbieżność”); sprawdzenie stanowiska
    # decyduje teraz na bieżącym statusie, także gdy pozycja była już wczytana do sesji.
    original: ProductionProduct | None = zablokuj_zamowienie_pozycji(product_id)
    if original is None:
        raise RejectError('product_not_found', f'product {product_id} nie istnieje', status=404)
```

Reszta funkcji bez zmian (reguła `uniewaznij_etapy` bierze zamówienie już trzymane przez tę transakcję).

- [ ] **Step 4: Zmiany z Base.**

Modify `modules/production/services/sync_service.py`, metoda `apply_baselinker_changes`.

Na początku metody (zaraz po `from .parser_service import ProductNameParser`) dodaj import:
```python
        from modules.production.logistics.services import delivery
        from .blokady_zamowien import zablokuj_zamowienie
```

Początek bloku `try:` — zamień:
```python
        try:
            parser = ProductNameParser()

            # 1. Usuń produkty
```
na:
```python
        try:
            parser = ProductNameParser()

            # „Zamówienie najpierw” (logistyka etap 4, krok 4.4a). Zamówienie z Base. (pełne dane nowych pozycji)
            # pobieramy PRZED blokadami: wywołanie HTTP trwa do kilkudziesięciu sekund, a tablety czekałyby na wiersz
            # zamówienia dłużej niż timeout gunicorna (30 s). Potem wiersz zamówienia i wszystkie jego pozycje
            # blokujemy odczytem bieżącym, zanim usuniemy, zmienimy albo dodamy pozycję — w kolejności panelu
            # Logistyki, Weryfikacji i stanowisk.
            bl_order = (self.get_order_from_baselinker(baselinker_order_id)
                        if changes.get('products_to_add') else None)
            zamowienie_id = (db.session.query(ProductionOrder.id)
                             .filter(ProductionOrder.baselinker_order_id == baselinker_order_id).scalar())
            zamowienie = zablokuj_zamowienie(zamowienie_id) if zamowienie_id is not None else None

            # 1. Usuń produkty
```

Krok 3 — zamień:
```python
            if changes.get('products_to_add'):
                # Pobierz zamówienie z BL dla pełnych danych
                bl_order = self.get_order_from_baselinker(baselinker_order_id)
                if bl_order:
```
na:
```python
            if changes.get('products_to_add'):
                # Zamówienie z Base. pobrane na początku metody, przed blokadami.
                if bl_order:
```

Reguła po dodaniu (linie ok. 2773-2783) — zamień:
```python
                if result['added']:
                    # Logistyka etap 4 (spec 8.5): nowa pozycja z Base. w zamówieniu z paczkami albo
                    # weryfikacją — jedna reguła unieważnia etapy. Nowe pozycje mają tylko order_id,
                    # więc kolekcję pozycji zamówienia czytamy od nowa.
                    from modules.production.logistics.services import weryfikacja
                    zamowienie = ProductionOrder.query.filter_by(
                        baselinker_order_id=baselinker_order_id).first()
                    if zamowienie is not None:
                        db.session.flush()
                        db.session.expire(zamowienie, ['products'])
                        weryfikacja.uniewaznij_etapy(zamowienie, get_local_now(), u'nowa pozycja z Base.')
```
na:
```python
                if result['added']:
                    # Logistyka etap 4 (spec 8.5): nowa pozycja z Base. w zamówieniu z paczkami albo
                    # weryfikacją — jedna reguła unieważnia etapy. Nowe pozycje mają tylko order_id,
                    # więc kolekcję pozycji zamówienia czytamy od nowa. `zamowienie` — zablokowane na początku.
                    from modules.production.logistics.services import weryfikacja
                    if zamowienie is not None:
                        db.session.flush()
                        db.session.expire(zamowienie, ['products'])
                        weryfikacja.uniewaznij_etapy(zamowienie, get_local_now(), u'nowa pozycja z Base.')
```

- [ ] **Step 4b: `sync_source` przy dodawaniu pozycji (decyzja Konrada 4)**

W kroku 3 (`new_product_data`, linia ok. 2734) usuń linię:
```python
                                    'sync_source': 'admin_update',
```
i w jej miejscu zostaw komentarz:
```python
                                    # sync_source zamówienia zostaje bez zmian (decyzja Konrada 1.10): kolumna to
                                    # ENUM('baselinker_auto','manual_entry'), a 'admin_update' wywracało na MySQL całą
                                    # operację (1265). _create_production_product_from_data przepisuje na zamówienie
                                    # klucze z ORDER_LEVEL_KEYS, więc samo pominięcie klucza wystarcza.
```

- [ ] **Step 4c: Przeliczenie zamknięcia**

Przed `db.session.commit()` (linia ok. 2807) dodaj:
```python
            # Pozycje mogły zniknąć albo dojść — cykl logistyczny przeliczamy od razu (krok 4.4a). Dotąd zamknięte
            # zamówienie kurierskie z nową pozycją czekało na godzinny cron, a usunięcie ostatniej niespakowanej
            # pozycji w ogóle nie zamykało cyklu.
            if zamowienie is not None:
                db.session.flush()
                db.session.expire(zamowienie, ['products'])
                delivery.przelicz_zamkniecie(zamowienie)

            db.session.commit()
```

- [ ] **Step 5: Testy przechodzą**

Run: `PYTEST tests/test_blokady_dorobka_base.py tests/test_weryfikacja_cykl.py tests/test_dorobka_dalsze_stanowiska.py tests/test_dorobka_trasa_krawedzi.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `5496 passed, 3 skipped` (5489 + 7 nowych). Każdy inny wynik — opisz w raporcie.

- [ ] **Step 7: Commit**

```bash
git add modules/production/services/rework_service.py modules/production/services/sync_service.py \
  tests/test_blokady_dorobka_base.py
git commit -m "fix(production): dorobka i zmiany z Base. blokuja zamowienie przed pozycjami" \
  -m "Zadanie wstepne kroku 4.4 logistyki: reject_product_quantity i apply_baselinker_changes biora blokade zamowienia i jego pozycji (odczyt biezacy) przed pierwszym zapisem. Zamowienie z Base. pobierane przed blokadami, zamkniecie cyklu przeliczane od razu po zmianie pozycji, dodanie pozycji nie nadpisuje juz sync_source zamowienia (wartosc spoza ENUM wywracala operacje na MySQL)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Wyścigi MySQL na 5004, dokumentacja

Zadanie dzielone jak Task 10 kroku 4.3: subagent robi kroki 1–7, kontroler krok 8 (meldunek do centrali).

**Files:**
- Create (poza repo): `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\kod\_podglad_wspolne.py`, `…\kod\_zamowienie_najpierw_wyscigi.py` (z kopii skryptów kroku 4.3), wyniki `…\kod\_wyscigi_44a.jsonl`, raport `…\logistyka4\sdd-44a\task-3-report.md`
- Modify: `CLAUDE.md` (sekcja „Ważne”, punkt „Deklaracje paczek — jedna naraz”)
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (4.6, 8.3, 8.7, 14)

- [ ] **Step 1: Kopia bazy i odświeżenie podglądu 5004**

1. Kopia bazy przed zmianami (tylko odczyt): `mysqldump --single-transaction logistyka4_podglad` w kontenerze `db` (`docker ps` — kontener bazy projektu `woodpower-crm`), plik skompresowany do `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\baza-przed-44a.sql.gz`. Dane osobowe kopii nie trafiają do raportu ani do repo.
2. Kod: `git archive HEAD | tar -x -C /c/Users/Grafik/Documents/woodpower-podglady/logistyka4/kod` (zostają pliki spoza repo: `config/core.json` podglądu, `_paczki_tablet.py`), potem `docker restart logistyka4-podglad`.
3. Log kontenera: runner wykonał `2026-09-30-logistyka-weryfikacja.sql` (baza 5004 była na kroku 4.2), bez błędów. `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5004/` → 200. Zapisz w raporcie SHA kodu podglądu.
4. **Nie** uruchamiaj agenta druku. Po każdej serii wygaś etykiety: `UPDATE prod_print_queue SET status='expired' WHERE status='pending' AND printer='wysylka'`.
5. Cron logistyki na podglądzie wołaj tylko w trybach, które go wymagają (`panel-hurt-cron`); geokoder w procesie skryptu podmieniony na „nic” (jak w kroku 4.3).

- [ ] **Step 2: Skrypty wyścigów**

Skopiuj z `C:\Users\Grafik\Documents\woodpower-podglady\logistyka43\kod\` do `…\logistyka4\kod\`: `_podglad_wspolne.py` (zmień prefiks operacji na `lg44a`, nazwy urządzeń zostają, dopisz urządzenie `PODGLAD-KRAWEDZIE` ze stanowiskiem `edges`) i `_weryfikacja_wyscigi.py` jako `_zamowienie_najpierw_wyscigi.py` (te same mechanizmy: dwa wątki z osobnymi `app.test_client()`, `threading.Barrier(2)`, osobne `X-Operation-Id`, ponowienie 500 tym samym op-id, odczyt stanu z bazy; trzy miary zakleszczeń: licznik InnoDB `lock_deadlocks`, logi aplikacji, odpowiedzi 500).

Dopisz **niezmiennik zamknięcia** sprawdzany po KAŻDYM przebiegu każdego trybu, dla każdego zamówienia przebiegu, na świeżym odczycie w nowym kontekście aplikacji:

```python
def zamkniecie_zgodne(order_id):
    """(zgodne, opis) — logistics_closed_at ustawione dokładnie wtedy, gdy reguła delivery.zamkniecie_wyliczone daje True."""
    from extensions import db
    from modules.production.logistics.services import delivery
    from modules.production.models import ProductionOrder
    with w.app.app_context():
        try:
            order = db.session.get(ProductionOrder, order_id)
            regula = delivery.zamkniecie_wyliczone(order)
            zamkniete = order.logistics_closed_at is not None
            return regula == zamkniete, 'regula=%s zamkniete=%s' % (regula, zamkniete)
        finally:
            db.session.remove()
```

Nowe tryby (opis w docstringu trybu, jak w kroku 4.3; stan wyjściowy przez `w.reset` i surowy SQL na zamówieniach z puli `w.pula`):

| Tryb | Stan wyjściowy | Strona A | Strona B | Oczekiwane |
|---|---|---|---|---|
| `panel-zakoncz-ostatnie` (jest) | 2 pozycje, pierwsza spakowana, ostatnia czeka na pakowanie, bez paczek; parzyste kurier → odbiór, nieparzyste transport → kurier | panel: zmiana sposobu, `przepakowanie: true` | ostatnie ZAKOŃCZ pakowania | oba 200, 0 × 1213, zamknięcie zgodne z regułą (odbiór nigdy zamknięty) |
| `panel-zakoncz` (jest) | w całości spakowane, 2 paczki | panel z przepakowaniem | ponowne ZAKOŃCZ ostatniej pozycji | jak w kroku 4.3 + zamknięcie zgodne |
| `panel-wejscie` (nowy) | 2 pozycje: pierwsza `czeka_na_pakowanie`, druga `czeka_na_krawedzie` z `parsed_finish_type='surowe'` i `quantity_done_edges=0`, `logistics_completed_at=NULL`; parzyste kurier → odbiór, nieparzyste transport → kurier | panel: zmiana sposobu (`przepakowanie: true` — pomijane, niespakowane) | ZAKOŃCZ Krawędzi drugiej pozycji (urządzenie `PODGLAD-KRAWEDZIE`, `station_code: edges`) | oba 200, druga `czeka_na_pakowanie`, `logistics_completed_at` ustawione, nowy sposób, 0 × 1213, zamknięcie zgodne |
| `dorobka-zakoncz` (nowy) | kurier, 2 pozycje `czeka_na_pakowanie` (pierwsza `quantity=2`), 2 paczki ważne (stan sztuczny jak `dorobka-weryfikacja`, żeby reguła miała pracę) | doróbka 1 szt. pierwszej pozycji z pakowania | ZAKOŃCZ drugiej pozycji | oba 200, pierwsza `quantity=1`, jest doróbka, druga `spakowane`, paczki unieważnione, 0 × 1213, zamknięcie zgodne (otwarte) |
| `dorobka-panel` (nowy) | 2 pozycje: pierwsza `czeka_na_pakowanie` (`quantity=2`), druga `spakowane`, 2 paczki ważne (stan sztuczny); parzyste kurier → odbiór, nieparzyste transport → kurier | doróbka 1 szt. pierwszej pozycji z pakowania | panel: zmiana sposobu (`przepakowanie: true`) | oba 200, nowy sposób, doróbka istnieje, paczki unieważnione, 0 × 1213, zamknięcie zgodne |
| `sync-zakoncz` (nowy) | kurier, pierwsza `spakowane`, druga `czeka_na_pakowanie` | `POST /production/api/admin/apply-baselinker-changes` (sesja admina). Parzyste: `products_to_update` = ilość pierwszej pozycji +1 i `order_level` = `delivery_city` (zapis zamówienia). Nieparzyste: `products_to_add` z jedną nową pozycją (`BaselinkerSyncService.get_order_from_baselinker` podmienione w procesie skryptu na odpowiedź z tą pozycją — bez sieci) | ostatnie ZAKOŃCZ pakowania | oba 200, druga `spakowane`, 0 × 1213, zamknięcie zgodne. Parzyste: zamówienie zamknięte (kurier, wszystko spakowane), nowe miasto. Nieparzyste: nowa pozycja `czeka_na_wyciecie`, zamówienie OTWARTE, `sync_source` bez zmian |

Przed serią `sync-zakoncz` jedno wywołanie kontrolne ścieżki dodania pozycji (`products_to_add`, podmienione Base.) na osobnym zamówieniu z puli, na kodzie HEAD: oczekiwane 200, `added == 1`, `sync_source` zamówienia bez zmian (poprawka z Task 2, Step 4b — dawniej MySQL odrzucał `admin_update` spoza ENUM). Wynik do raportu.

- [ ] **Step 3: Serie**

Każdy tryb z tabeli (6 trybów): **×20 czysta bariera, ×12 rozjazd startu 0–40 ms, ×30 rozjazd 0–15 ms = 62 przebiegi**. Regresja kroku 4.3 (tryby z `_weryfikacja_wyscigi.py`), po **×10** (czysta bariera ×5 + rozjazd 0–15 ms ×5): `complete-deklaracja`, `weryfikacja-deklaracja`, `dwie-paczki`, `cofniecie-weryfikacja`, `hurt-weryfikacja`, `dorobka-weryfikacja` (w kroku 4.3: 1213 w 13 z 16 — teraz oczekiwane 0), `dorobka-weryfikacja-naturalny`, `unverify-przepakowanie`, `zakoncz-weryfikacja`, `panel-deklaracja`, `panel-weryfikacja`, `panel-hurt-cron` — z niezmiennikiem zamknięcia.

**Kryterium (od centrali): zero 1213 i zero błędnych zamknięć we wszystkich trybach.** Pierwsze 1213 albo niezgodne zamknięcie → zbierz `SHOW ENGINE INNODB STATUS` (sekcja `LATEST DETECTED DEADLOCK`, bez zrzutów rekordów z danymi klientów), dokończ serię dla częstości i **STOP** — meldunek do kontrolera, bez zmian w kodzie (decyzja należy do Konrada).

- [ ] **Step 4: Raport**

`C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\sdd-44a\task-3-report.md`: SHA kodu podglądu, migracja przez runner, tabela trybów (przebiegi, 1213 serwer/log, 500, niezgodne zamknięcia, rozkład odpowiedzi A/B), wynik ścieżki dodania pozycji z Base. na MySQL, uwagi. Wyniki surowe w `_wyscigi_44a.jsonl`.

- [ ] **Step 5: CLAUDE.md**

W `CLAUDE.md`, sekcja „Ważne”, punkt „Deklaracje paczek — jedna naraz”, zamień ostatnie zdania:
```
  sposobu dostawy w panelu (po blokadzie tras) blokują zamówienia rosnąco po id. Stanowiska (ZAKOŃCZ, doróbka)
  i synchronizacja biorą pozycję przed zamówieniem — z zapisami Weryfikacji i ze zmianą sposobu w panelu możliwe
  rzadkie 1213 (panel ponawia raz sam, tablet z kolejki offline).
```
na:
```
  sposobu dostawy w panelu (po blokadzie tras) blokują zamówienia rosnąco po id. **Zamówienie najpierw**
  (krok 4.4a): ZAKOŃCZ i wejście do pakowania na tabletach (`POST /api/mobile/orders/<id>/complete`), doróbka
  (`reject_product_quantity`), zmiany z Base. (`apply_baselinker_changes`) i przeniesienie osieroconych w cronie
  blokują wiersz zamówienia, potem wszystkie jego pozycje (`services/blokady_zamowien.py`, odczyt bieżący), zanim
  cokolwiek zapiszą — `po_spakowaniu` i `odnotuj_wejscie_do_pakowania` decydują więc na bieżącym sposobie dostawy
  i statusach. Nowy zapis pozycji zamówienia zaczyna od tej samej blokady, a wywołanie Base. (HTTP) robi przed
  blokadami. Bez blokady zamówienia piszą tylko liczniki sztuk (`PATCH …/quantity`, edycja sztuk w panelu admina).
```

- [ ] **Step 6: Spec**

W specu (dopiski z „(krok 4.4a)”, jak w poprzednich krokach):
- 4.6, akapit „Siatka w cronie”: na końcu „(krok 4.4a) Przyczynę usuwa zadanie wstępne kroku 4.4: ZAKOŃCZ blokuje zamówienie przed pozycjami i decyduje na odczycie bieżącym; siatka zostaje jako zabezpieczenie.”
- 8.3, „Współbieżność”, zdania o znanym wyjątku doróbki: dopisz „(krok 4.4a) Usunięte: ZAKOŃCZ, wejście do pakowania, doróbka i zmiany z Base. biorą zamówienie przed pozycją (`services/blokady_zamowien.py`); wyścigi MySQL: <liczby z raportu>.”
- 8.7, „Współbieżność”: dopisz „(krok 4.4a) Po zmianie kolejności blokad stanowisk tryb ostatniego ZAKOŃCZ na zamówieniu spakowanym w połowie: 0 × 1213 i 0 błędnych zamknięć w <N> przebiegach.”
- 14, punkt 4: dopisz „Etapy 3 i 4 wdrażamy jednym wdrożeniem (decyzja Konrada 1.10), więc w chwili wdrożenia nie ma tras wykonanych. Gdyby etap 3 poszedł wcześniej, przed 4.4 trzeba dopisać jednorazowe przestawienie pozycji zamówień z tras wykonanych na `dostarczone` (wzór `delivery.dostarcz_wydane`). Kolejność APK ↔ backend przy wspólnym wdrożeniu etapów 1–4 (etap 1 wymagał appki przed backendem, kroki 4.2–4.4 backendu przed appką) ustala plan wdrożenia prowadzony przez centralę.”

- [ ] **Step 7: Pełny pakiet, Python 3.9, commit dokumentów**

Run: `PYTEST tests/` → `5496 passed, 3 skipped`.
Składnia pod 3.9: `compile()` i `ast.parse(feature_version=(3, 9))` w obrazie `python:3.9-slim` dla plików `.py` zmienionych od `b0fc115a` (jak w kroku 4.3) → wszystkie OK; brak `X | Y` w adnotacjach poza plikami z `from __future__ import annotations`.

```bash
git add -f docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md
git add CLAUDE.md
git commit -m "docs: krok 4.4a logistyki - zamowienie najpierw dla stanowisk, wyniki wyscigow" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Meldunek (kontroler)**

SendMessage do „Sesja centralna rozwoju logistyki”: commity 4.4a, wynik pełnego pakietu, tabela wyścigów (przebiegi, 0 × 1213, 0 błędnych zamknięć), wynik ścieżki dodania pozycji z Base. na MySQL (po poprawce `sync_source`), lista „Poza zakresem” do decyzji Konrada, stan podglądu 5004.

---

## Wdrożenie

Bez migracji i bez zmian kontraktu API. Wchodzi razem z całym etapem 4 (i etapami 1–3, jednym wdrożeniem). Po wdrożeniu nic do uruchamiania ręcznie z powodu tego kroku.
